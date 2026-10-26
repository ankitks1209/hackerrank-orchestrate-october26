"""Pipeline pre-pass: read the facts of each image and PDF with one vision call (SPEC F10, N7).

For every media file of the manifest, one cached, schema-validated call returns the
records the file shows (the extraction contract of `evidence.media`). The model only
transcribes; `evidence.media.map_facts` decides which resource a record is, so a
misread identifier is bounded by its LINK-row and literal-id validation.

Four facts depend on the category (the `evidence.media` contract): `restore_blocked`
applies only to backup archives, `connector_enabled` only to data flows,
`pii_fields_shown` only where the policy keeps a record and strips its identifiers, and
`only_stable_reference_shown` only where it redacts. Validation drops a fact outside its
categories, so a profile, export or audit event that shows identifiers stays a shown
record whatever the model sets. The facts describe a displayed record, so a dropped true
fact sets `record_shown`: the record is never lost, and each drop leaves a note so a
category misread is visible in diagnostics.

The identifier facts are also read from the transcribed lists, because the lists are the
literal transcription and the live model was seen to omit the booleans: a kept record in
scope that lists an email, phone or name shows PII, and one in redact scope that lists
only a `user_` reference shows only the stable reference. A derived fact only adds to
what the model set and leaves a note. The schema lists the facts in `STATE_RULES` order
with `record_shown` last: structured outputs emit properties in schema order, so with
`record_shown` first the live model could add no fact but `restore_blocked` after it.

Stored replies are redacted copies (`redact_reply`, DECISIONS D25): an email or phone is
kept only as `sha256:<hex>` and names are dropped, because names are never matching keys.
`evidence.media` matches the digests against the identity's hash keys, so the redaction does
not change what a record is mapped to.

Failure handling follows SPEC N7: a reply that fails the schema check is retried once
with the error as a hint; a refusal, a cache miss, `--llm off` or an unreadable file
skips that file and leaves a note. The caller then builds the index without those facts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from ghostaudit.config import MEDIA_MAX_TOKENS, MEDIA_SCHEMA_RETRIES
from ghostaudit.evidence.media import STATE_RULES
from ghostaudit.keys import redacted_email, redacted_phone
from ghostaudit.llm.client import (
    PDF_MIME,
    LLMClient,
    LLMDisabled,
    LLMError,
    LLMRequest,
)
from ghostaudit.model import ManifestEntry, MediaFacts

LOGGER = logging.getLogger("ghostaudit.llm")

PROMPT_VERSION = "media_extract.v2"
REDACTION_NOTE = "emails/phones hashed (sha256), names removed; original model text not retained"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / (PROMPT_VERSION + ".md")
USER_TEXT = "Transcribe the records shown in the attached file."
HINT_TEXT = "\n\nYour previous reply was rejected: %s. Reply again with corrected JSON only."
MIME_BY_SUFFIX: Mapping[str, str] = {".png": "image/png", ".pdf": PDF_MIME}

# The 15 data categories of deletion_rules.csv, plus the connector category of SPEC F9.
MEDIA_CATEGORIES: Tuple[str, ...] = (
    "USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY",
    "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT", "ANALYTICS_PROFILE", "PRODUCT_TELEMETRY",
    "USER_EXPORT", "MARKETING_PROFILE", "EMAIL_DELIVERY_LOG", "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD", "BACKUP_ARCHIVE", "ACCOUNT_TOMBSTONE", "DATA_FLOW",
)
# STATE_RULES order, which ends with record_shown (see the module docstring).
STATE_FACT_NAMES: Tuple[str, ...] = tuple(dict.fromkeys(fact for fact, _v, _s in STATE_RULES))
PII_FACT = "pii_fields_shown"
STABLE_FACT = "only_stable_reference_shown"
# Categories whose deletion rule is REDACT or ANONYMIZE: the record stays, identifiers go.
REDACT_CATEGORIES: FrozenSet[str] = frozenset(
    {"SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG", "ACCOUNT_TOMBSTONE"}
)
ANONYMIZE_CATEGORIES: FrozenSet[str] = frozenset({"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"})
# Facts that apply only to some categories; every other fact applies to any record.
FACT_CATEGORIES: Mapping[str, FrozenSet[str]] = {
    "restore_blocked": frozenset({"BACKUP_ARCHIVE"}),
    "connector_enabled": frozenset({"DATA_FLOW"}),
    PII_FACT: REDACT_CATEGORIES | ANONYMIZE_CATEGORIES,
    STABLE_FACT: REDACT_CATEGORIES,
}
SHOWN_FACT = "record_shown"
TEXT_FIELDS = ("display_id", "resource_hint", "system_hint", "category")
LIST_FIELDS = ("emails", "phones", "user_refs", "names", "dates")
DIRECT_ID_FIELDS = ("emails", "phones", "names")  # direct identifiers; user_refs is the stable one
RECORD_FIELDS = TEXT_FIELDS + LIST_FIELDS + ("state_facts",)

_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": _STRING}
MEDIA_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "display_id": _STRING,
                    "resource_hint": _STRING,
                    "system_hint": _STRING,
                    "category": {"type": "string", "enum": [""] + list(MEDIA_CATEGORIES)},
                    "emails": _STRING_LIST,
                    "phones": _STRING_LIST,
                    "user_refs": _STRING_LIST,
                    "names": _STRING_LIST,
                    "dates": _STRING_LIST,
                    "state_facts": {
                        "type": "object",
                        "properties": {fact: {"type": "boolean"} for fact in STATE_FACT_NAMES},
                        "additionalProperties": False,
                    },
                },
                "required": list(RECORD_FIELDS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}


class ExtractionInvalid(ValueError):
    """A model reply that does not satisfy the extraction schema; the text says why."""


@dataclass(frozen=True)
class MediaExtraction:
    """Validated facts by file id, and one note per file that was skipped or retried."""

    facts: Mapping[str, MediaFacts]
    notes: Tuple[str, ...]


def load_prompt(path: Path = PROMPT_PATH) -> str:
    """The versioned system prompt."""
    return path.read_text(encoding="utf-8")


def _check_text_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ExtractionInvalid("%s must be a list of strings" % name)
    return [item.strip() for item in value if item.strip()]


def _check_state_facts(value: Any) -> Dict[str, bool]:
    if not isinstance(value, dict):
        raise ExtractionInvalid("state_facts must be an object")
    unknown = sorted(set(value) - set(STATE_FACT_NAMES))
    if unknown:
        raise ExtractionInvalid("state_facts has unknown facts %s" % unknown)
    if not all(isinstance(flag, bool) for flag in value.values()):
        raise ExtractionInvalid("state_facts values must be booleans")
    return {fact: value[fact] for fact in sorted(value)}


def _in_scope(facts: Mapping[str, bool], category: str) -> Tuple[Dict[str, bool], List[str]]:
    """The facts that apply to a record of `category` (FACT_CATEGORIES), and the dropped ones.

    A dropped fact that is true still says the record is displayed, so it sets `record_shown`.
    """
    kept: Dict[str, bool] = {}
    dropped: List[str] = []
    for fact, flag in facts.items():
        if fact not in FACT_CATEGORIES or category in FACT_CATEGORIES[fact]:
            kept[fact] = flag
        else:
            dropped.append(fact)
    if any(facts[fact] for fact in dropped):
        kept[SHOWN_FACT] = True
    return {fact: kept[fact] for fact in sorted(kept)}, dropped


def _derived_facts(record: Mapping[str, Any], facts: Mapping[str, bool]) -> List[str]:
    """Identifier facts the transcribed lists imply and the model did not set true."""
    category = record["category"]
    if facts.get(PII_FACT):
        return []
    if any(record[name] for name in DIRECT_ID_FIELDS):
        return [PII_FACT] if category in FACT_CATEGORIES[PII_FACT] else []
    stable_scope = category in FACT_CATEGORIES[STABLE_FACT]
    if record["user_refs"] and stable_scope and not facts.get(STABLE_FACT):
        return [STABLE_FACT]
    return []


def _check_record(item: Any, index: int, notes: List[str]) -> Dict[str, Any]:
    """One record in canonical form; `ExtractionInvalid` names the first violation.

    A fact dropped by `_in_scope` or derived by `_derived_facts` adds a note to `notes`.
    """
    if not isinstance(item, dict) or set(item) != set(RECORD_FIELDS):
        raise ExtractionInvalid(
            "records[%d] must have exactly the keys %s" % (index, list(RECORD_FIELDS))
        )
    record: Dict[str, Any] = {}
    for name in TEXT_FIELDS:
        if not isinstance(item[name], str):
            raise ExtractionInvalid("records[%d].%s must be a string" % (index, name))
        record[name] = item[name].strip()
    if record["category"] not in ("",) + MEDIA_CATEGORIES:
        raise ExtractionInvalid(
            "records[%d].category %r is not an allowed category" % (index, record["category"])
        )
    for name in LIST_FIELDS:
        record[name] = _check_text_list(item[name], "records[%d].%s" % (index, name))
    category = record["category"]
    facts, dropped = _in_scope(_check_state_facts(item["state_facts"]), category)
    for fact in dropped:
        notes.append(
            "records[%d]: %s dropped, it does not apply to category %r" % (index, fact, category)
        )
    for fact in _derived_facts(record, facts):
        facts[fact] = True
        notes.append("records[%d]: %s set from the transcribed identifiers" % (index, fact))
    record["state_facts"] = {fact: facts[fact] for fact in sorted(facts)}
    return record


def parse_records(text: str) -> Tuple[Tuple[Dict[str, Any], ...], Tuple[str, ...]]:
    """The records of a model reply, validated and canonical, and one note per dropped fact.

    Raises `ExtractionInvalid` when the reply violates the schema.
    """
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ExtractionInvalid("the reply is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"records"}:
        raise ExtractionInvalid('the reply must be an object with the single key "records"')
    items = payload["records"]
    if not isinstance(items, list):
        raise ExtractionInvalid("records must be an array")
    notes: List[str] = []
    records = tuple(_check_record(item, index, notes) for index, item in enumerate(items))
    return records, tuple(notes)


def redact_reply(text: str) -> str:
    """The reply with emails and phones as `sha256:<hex>`, names removed, as canonical JSON.

    Applied before a reply is stored (DECISIONS D25). The reply is canonicalised first
    (`parse_records`), so the facts derived from the listed identifiers are already in
    `state_facts` when the names go, and redacting twice gives the same text. A reply that is
    not valid JSON, or breaks the schema, is stored as an empty string: it is not redacted
    field by field, and a replay of it is rejected as "not valid JSON".
    """
    try:
        records, _notes = parse_records(text)
    except ExtractionInvalid:
        return ""
    redacted = []
    for record in records:
        emails = (redacted_email(item) for item in record["emails"])
        phones = (redacted_phone(item) for item in record["phones"])
        redacted.append(dict(
            record,
            emails=[item for item in emails if item],
            phones=[item for item in phones if item],
            names=[],
        ))
    return json.dumps({"records": redacted}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_request(
    model: str, system: str, data: bytes, mime: str, hint: Optional[str] = None
) -> LLMRequest:
    """The vision request for one file; `hint` is the error text of a rejected first reply."""
    return LLMRequest(
        model=model,
        system=system,
        messages=(("user", USER_TEXT + (HINT_TEXT % hint if hint else "")),),
        max_tokens=MEDIA_MAX_TOKENS,
        prompt_version=PROMPT_VERSION,
        attachments=((data, mime),),
        schema=MEDIA_SCHEMA,
    )


def _extract_one(
    entry: ManifestEntry, llm: LLMClient, model: str, system: str, notes: List[str]
) -> Optional[MediaFacts]:
    """Facts of one file, or None after a note explains why it was skipped."""
    mime = MIME_BY_SUFFIX.get(entry.path.suffix.lower())
    if mime is None:
        notes.append("%s: unsupported media type %s" % (entry.file_id, entry.path.suffix))
        return None
    try:
        data = entry.path.read_bytes()
    except OSError as exc:
        notes.append("%s: cannot read the file (%s)" % (entry.file_id, exc.__class__.__name__))
        return None
    hint: Optional[str] = None
    for _attempt in range(1 + MEDIA_SCHEMA_RETRIES):
        response = llm.complete(build_request(model, system, data, mime, hint))
        try:
            records, dropped = parse_records(response.text)
        except ExtractionInvalid as exc:
            hint = str(exc)
            notes.append("%s: extraction rejected (%s)" % (entry.file_id, hint))
            continue
        notes.extend("%s: %s" % (entry.file_id, note) for note in dropped)
        return MediaFacts(entry.file_id, records)
    attempts = 1 + MEDIA_SCHEMA_RETRIES
    notes.append("%s: skipped after %d rejected extractions" % (entry.file_id, attempts))
    return None


def extract_media_facts(
    entries: Iterable[ManifestEntry], llm: LLMClient, model: str
) -> MediaExtraction:
    """Facts for each media entry, one call per file, in the order given.

    Under `--llm off` or on a cache miss a file yields no facts and a note.
    """
    system = load_prompt()
    facts: Dict[str, MediaFacts] = {}
    notes: List[str] = []
    for entry in entries:
        try:
            extracted = _extract_one(entry, llm, model, system, notes)
        except LLMDisabled:
            LOGGER.info("media extraction of %s skipped: LLM calls are disabled", entry.file_id)
            notes.append("%s: skipped, LLM calls are disabled" % entry.file_id)
            continue
        except LLMError as exc:
            LOGGER.warning("media extraction of %s skipped: %s", entry.file_id, exc)
            notes.append("%s: skipped, %s" % (entry.file_id, exc))
            continue
        if extracted is not None:
            facts[entry.file_id] = extracted
    return MediaExtraction(facts=facts, notes=tuple(notes))
