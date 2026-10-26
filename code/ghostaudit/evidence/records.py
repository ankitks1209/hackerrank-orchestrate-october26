"""JSON records parser: service exports, snapshot bundles, flat ledgers, collections.

Implements SPEC 3.1 (normalized records) and 3.2 F4 (service exports), F5
(snapshot bundles, including operational_record_history rows), F6 (flat ledgers
and the result vocabulary) and F7 (single-collection files). The family is
chosen from the top-level keys, never from the file name. Every entry keeps
its own `entry_time`; the SPEC T1 time filter decides what counts at `audit_at`.
Names are never subject keys (SPEC I1); only shapes in `keys.py` are. Ported
from the normalization logic of the analysis prototype records_normalize, with
IDENTIFIABLE renamed to EXPOSED and name keys dropped.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from ghostaudit.evidence.base import ParseError, ParseOutput
from ghostaudit.keys import keys_from_record
from ghostaudit.model import (
    RESULT_STATES,
    ManifestEntry,
    ObsState,
    Observation,
    ScopeAssertion,
)
from ghostaudit.timeutil import to_epoch

LOGGER = logging.getLogger(__name__)

REDACTED_TEXT = "[REDACTED]"
HTTP_NOT_FOUND = 404
HISTORY_COLLECTION = "operational_record_history"

# Top-level keys that identify each family (SPEC F4-F7). Detection looks for the
# quoted key names in the leading bytes; parsing re-checks the decoded keys.
_JSON_START = b"{"
_FAMILY_MARKERS: Tuple[Tuple[bytes, ...], ...] = (
    (b'"service_exports"',),
    (b'"snapshots"',),
    (b'"records"', b'"record_type"'),
    (b'"collection"', b'"records"'),
)


@dataclass(frozen=True)
class _Decoded:
    """Category, state and subject keys decoded from one record."""

    category: Optional[str]
    state: ObsState
    keys: FrozenSet[str]


Decoder = Callable[[Mapping[str, Any]], _Decoded]
Handler = Callable[[ManifestEntry, Mapping[str, Any]], ParseOutput]


def _keys(row: Mapping[str, Any], fields: Sequence[str]) -> FrozenSet[str]:
    """Subject keys of the named fields; names and other free text yield none."""
    return keys_from_record([row.get(field) for field in fields])


def _present(category: str, key_fields: Sequence[str]) -> Decoder:
    """Decoder for a record whose existence is the whole observation (PRESENT)."""

    def decode(row: Mapping[str, Any]) -> _Decoded:
        return _Decoded(category, ObsState.PRESENT, _keys(row, key_fields))

    return decode


def _switch(
    category: str, flag: str, on: ObsState, off: ObsState, key_fields: Sequence[str]
) -> Decoder:
    """Decoder whose state follows a boolean field (enabled, restore_allowed)."""

    def decode(row: Mapping[str, Any]) -> _Decoded:
        return _Decoded(category, on if row.get(flag) else off, _keys(row, key_fields))

    return decode


def _scrubbed(
    category: Optional[str],
    state_fields: Sequence[str],
    clean: ObsState,
    extra_key_fields: Sequence[str] = (),
) -> Decoder:
    """Decoder that is `clean` when every state field is empty, else EXPOSED."""

    def decode(row: Mapping[str, Any]) -> _Decoded:
        exposed = any(row.get(field) for field in state_fields)
        keys = _keys(row, tuple(state_fields) + tuple(extra_key_fields))
        return _Decoded(category, ObsState.EXPOSED if exposed else clean, keys)

    return decode


def _decode_support_conversation(row: Mapping[str, Any]) -> _Decoded:
    """SUPPORT_MESSAGE: only the literal redaction marker is REDACTED (SPEC F1)."""
    redacted = row.get("message_text") == REDACTED_TEXT
    state = ObsState.REDACTED if redacted else ObsState.EXPOSED
    return _Decoded("SUPPORT_MESSAGE", state, _keys(row, ("subject_reference", "message_text")))


def _decode_search_document(row: Mapping[str, Any]) -> _Decoded:
    """SEARCH_INDEX_ENTRY: keys come from the nested `document` (SPEC F1)."""
    return _Decoded(
        "SEARCH_INDEX_ENTRY", ObsState.PRESENT, keys_from_record(row.get("document"))
    )


def _decode_profile_lookup(row: Mapping[str, Any]) -> _Decoded:
    """USER_PROFILE: a 404 or null profile is ABSENT with no keys; 200 is PRESENT (SPEC F4)."""
    profile = row.get("profile")
    if row.get("status_code") == HTTP_NOT_FOUND or profile is None:
        return _Decoded("USER_PROFILE", ObsState.ABSENT, frozenset())
    return _Decoded("USER_PROFILE", ObsState.PRESENT, keys_from_record(profile))


def _decode_index_query(row: Mapping[str, Any]) -> _Decoded:
    """SEARCH_INDEX_ENTRY: PRESENT when the query has hits; keys from the hit documents."""
    hits = row.get("hits") or {}
    if hits.get("total", 0) > 0:
        return _Decoded(
            "SEARCH_INDEX_ENTRY", ObsState.PRESENT, keys_from_record(hits.get("documents"))
        )
    return _Decoded("SEARCH_INDEX_ENTRY", ObsState.ABSENT, frozenset())


# SPEC F4: service export list name -> decoder.
_EXPORT_DECODERS: Dict[str, Decoder] = {
    "profile_lookups": _decode_profile_lookup,
    "profiles": _scrubbed(
        "ANALYTICS_PROFILE",
        ("customer_reference", "email", "email_hash", "phone"),
        ObsState.ANONYMIZED,
    ),
    "restore_entries": _switch(
        "BACKUP_ARCHIVE",
        "restore_allowed",
        ObsState.ACTIVE,
        ObsState.BLOCKED,
        ("customer_reference", "customer_email"),
    ),
    "exports": _present("USER_EXPORT", ("customer_reference", "owner_email", "owner_phone")),
    "connectors": _switch(
        "DATA_FLOW",
        "enabled",
        ObsState.ACTIVE,
        ObsState.DISABLED,
        ("customer_reference", "customer_email"),
    ),
    "index_queries": _decode_index_query,
    "audit_records": _present("SECURITY_AUDIT_LOG", ("subject_reference",)),
    # A ticket row cannot tell a message from an attachment: no category, so the
    # worker's activity event_type decides (DELETE_RECORD attachment, REDACT_RECORD message).
    "tickets": _scrubbed(
        None,
        ("requester_email", "requester_name", "requester_phone"),
        ObsState.REDACTED,
        ("customer_reference",),
    ),
}

# SPEC F1/F5/F7: collection name -> decoder, shared by bundles and collection files.
_COLLECTION_DECODERS: Dict[str, Decoder] = {
    "customer_profiles": _present("USER_PROFILE", ("customer_reference", "email", "phone")),
    "customer_search_documents": _decode_search_document,
    "customer_analytics_reports": _scrubbed(
        "ANALYTICS_PROFILE", ("user_id", "email", "phone", "email_hash"), ObsState.ANONYMIZED
    ),
    "support_conversations": _decode_support_conversation,
    "ticket_attachments": _present("SUPPORT_ATTACHMENT", ("uploaded_by",)),
    "customer_export_jobs": _present("USER_EXPORT", ("owner_email",)),
    "connector_configurations": _switch(
        "DATA_FLOW", "enabled", ObsState.ACTIVE, ObsState.DISABLED, ("subject_selector",)
    ),
    "backup_catalog": _switch(
        "BACKUP_ARCHIVE",
        "restore_allowed",
        ObsState.ACTIVE,
        ObsState.BLOCKED,
        ("subject_reference",),
    ),
    "security_audit_events": _present("SECURITY_AUDIT_LOG", ("subject_reference",)),
    "retained_order_records": _present("LEGAL_HOLD_RECORD", ("subject_reference",)),
    "deleted_customer_references": _scrubbed(
        "ACCOUNT_TOMBSTONE",
        ("name", "email", "phone", "email_hash"),
        ObsState.REDACTED,
        ("subject_reference",),
    ),
}

# SPEC F7: single-collection files carry a `source` that is not a system id.
_COLLECTION_FILE_SYSTEMS: Dict[str, str] = {
    "customer_analytics_reports": "analytics_platform",
    "customer_export_jobs": "export_service",
}


def _epoch(value: Optional[str]) -> Optional[int]:
    """Integer epoch of an ISO timestamp; None when the record has no time."""
    return to_epoch(value) if value else None


def _observation(
    entry: ManifestEntry,
    system_id: str,
    row: Mapping[str, Any],
    decoded: _Decoded,
    entry_time: Optional[int],
    locator: str,
) -> Observation:
    return Observation(
        file_id=entry.file_id,
        captured_at=entry.captured_at,
        entry_time=entry_time,
        system_id=system_id,
        resource_id=row["resource_id"],
        category=decoded.category,
        state=decoded.state,
        subject_keys=decoded.keys,
        locator=locator,
    )


def _ledger_observation(
    entry: ManifestEntry, row: Mapping[str, Any], key_field: str, locator: str
) -> Observation:
    """One F6 ledger row; the key field is `subject_reference` or `lookup_value`."""
    result = row["result"]
    if result not in RESULT_STATES:
        raise ParseError("%s %s: unknown result %r" % (entry.file_id, locator, result))
    decoded = _Decoded(row["record_type"], RESULT_STATES[result], _keys(row, (key_field,)))
    return _observation(entry, row["system"], row, decoded, _epoch(row.get("recorded_at")), locator)


def _decoder_for(entry: ManifestEntry, table: Mapping[str, Decoder], name: str) -> Decoder:
    if name not in table:
        raise ParseError("%s: unknown record list %r" % (entry.file_id, name))
    return table[name]


def _parse_exports(entry: ManifestEntry, doc: Mapping[str, Any]) -> ParseOutput:
    observations: List[Observation] = []
    for system_id, lists in doc["service_exports"].items():
        for list_name, rows in lists.items():
            decode = _decoder_for(entry, _EXPORT_DECODERS, list_name)
            for index, row in enumerate(rows):
                locator = "service_exports.%s.%s[%d]" % (system_id, list_name, index)
                observations.append(
                    _observation(
                        entry, system_id, row, decode(row), _epoch(row.get("observed_at")), locator
                    )
                )
    return ParseOutput(observations=tuple(observations))


def _parse_bundle(entry: ManifestEntry, doc: Mapping[str, Any]) -> ParseOutput:
    observations: List[Observation] = []
    scopes: List[ScopeAssertion] = []
    for snap_index, snapshot in enumerate(doc["snapshots"]):
        captured_at = to_epoch(snapshot["captured_at"])
        store, collection = snapshot["data_store"], snapshot["collection"]
        prefix = "snapshots[%d].records" % snap_index
        rows = snapshot["records"]
        if not rows:
            scopes.append(ScopeAssertion(entry.file_id, captured_at, store, frozenset()))
        for index, row in enumerate(rows):
            locator = "%s[%d]" % (prefix, index)
            if collection == HISTORY_COLLECTION:
                observations.append(_ledger_observation(entry, row, "lookup_value", locator))
                continue
            decoded = _decoder_for(entry, _COLLECTION_DECODERS, collection)(row)
            observations.append(_observation(entry, store, row, decoded, captured_at, locator))
    return ParseOutput(observations=tuple(observations), scopes=tuple(scopes))


def _parse_ledger(entry: ManifestEntry, doc: Mapping[str, Any]) -> ParseOutput:
    observations = tuple(
        _ledger_observation(entry, row, "subject_reference", "records[%d]" % index)
        for index, row in enumerate(doc["records"])
    )
    return ParseOutput(observations=observations)


def _parse_collection(entry: ManifestEntry, doc: Mapping[str, Any]) -> ParseOutput:
    collection = doc["collection"]
    if collection not in _COLLECTION_FILE_SYSTEMS:
        raise ParseError("%s: no system for collection %r" % (entry.file_id, collection))
    system_id = _COLLECTION_FILE_SYSTEMS[collection]
    decode = _COLLECTION_DECODERS[collection]
    captured_at = to_epoch(doc["captured_at"])
    observations = tuple(
        _observation(entry, system_id, row, decode(row), captured_at, "records[%d]" % index)
        for index, row in enumerate(doc["records"])
    )
    return ParseOutput(observations=observations)


def _handler_for(doc: Mapping[str, Any]) -> Optional[Handler]:
    """Pick the family handler from the top-level keys (SPEC F4-F7)."""
    if "service_exports" in doc:
        return _parse_exports
    if "snapshots" in doc:
        return _parse_bundle
    if isinstance(doc.get("records"), list):
        return _parse_collection if "collection" in doc else _parse_ledger
    return None


class RecordsParser:
    """Decodes the four JSON record families (SPEC F4-F7)."""

    name = "json_records"

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        """True for a JSON object whose leading bytes show a family's top-level keys."""
        if not head.lstrip().startswith(_JSON_START):
            return False
        return any(all(token in head for token in tokens) for tokens in _FAMILY_MARKERS)

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        """Decode the whole file; ParseError when it is not one of the four families."""
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError as exc:  # UnicodeDecodeError and JSONDecodeError subclass it
            raise ParseError("%s: not valid JSON: %s" % (entry.file_id, exc))
        handler = _handler_for(doc) if isinstance(doc, dict) else None
        if handler is None:
            raise ParseError("%s: JSON is not a records family" % entry.file_id)
        try:
            output = handler(entry, doc)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ParseError("%s: malformed %s record: %r" % (entry.file_id, handler.__name__, exc))
        LOGGER.info(
            "%s: %d observations, %d scopes",
            entry.file_id,
            len(output.observations),
            len(output.scopes),
        )
        return output
