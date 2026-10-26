"""SQL snapshot parser: topology, inventory and special schemas (SPEC F1-F3).

Each `.sql` file is loaded into an in-memory SQLite database and decoded by the
family its tables identify (SPEC 3.1: content decides the parser, never file_id):

* topology (F1): `customer_data_primary` plus replica tables. The union over every
  table is taken, so a row held by a single replica still counts as present. A
  snapshot holding at least one account_service row also yields a cite-only
  account_service scope (SPEC V5.1): it names the file as an absence proof for a case
  that already cites it, and takes no part in state resolution.
* inventory (F2): typed tables plus `snapshot_scope`. Every in-scope system yields
  one ScopeAssertion; a system outside the scope is unobserved, not absent.
* special (F3): the profile primary/failover pair and `search_documents_primary`.
  The profile pair is also an account_service scope. `source_resource_id` of a
  search document is kept as an account pointer in the locator (SPEC L12.2).

A SQL snapshot asserts what existed at its capture time, so `entry_time` is the
manifest `captured_at` (SPEC F5 snapshot rule), not a row's own `updated_at`.
Subject keys come from `keys.keys_from_record` (SPEC I1/I2).
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from ghostaudit.evidence.base import ParseError, ParseOutput
from ghostaudit.keys import keys_from_record
from ghostaudit.model import ACCOUNT_SERVICE, ManifestEntry, ObsState, Observation, ScopeAssertion

StateRule = Callable[[Mapping[str, Any]], ObsState]

_SQL_HEAD = re.compile(rb"^(PRAGMA|BEGIN TRANSACTION|CREATE TABLE|-- Ghost Data)", re.MULTILINE | re.IGNORECASE)
_POINTER = re.compile(r";source_resource_id=(\S+)")

TOPOLOGY, INVENTORY, SPECIAL = "topology", "inventory", "special"
TOPOLOGY_PRIMARY = "customer_data_primary"
SCOPE_TABLE = "snapshot_scope"
REDACTED_TEXT = "[REDACTED]"

ANALYTICS_IDENTIFIERS = ("user_id", "email", "phone", "email_hash")
TOMBSTONE_IDENTIFIERS = ("name", "email", "phone", "email_hash")
INVENTORY_ANALYTICS_IDENTIFIERS = ("customer_reference", "email", "phone", "email_hash")
SUPPORT_REQUESTER_FIELDS = ("requester_name", "requester_email", "requester_phone")


def _always(state: ObsState) -> StateRule:
    return lambda record: state


def _flag(field: str, on: ObsState, off: ObsState) -> StateRule:
    return lambda record: on if record.get(field) else off


def _identifiers_cleared(fields: Tuple[str, ...], cleared: ObsState, kept: ObsState) -> StateRule:
    return lambda record: cleared if all(record.get(f) is None for f in fields) else kept


def _any_set(fields: Tuple[str, ...], when_set: ObsState, otherwise: ObsState) -> StateRule:
    return lambda record: when_set if any(record.get(f) is not None for f in fields) else otherwise


def _message_state(record: Mapping[str, Any]) -> ObsState:
    return ObsState.REDACTED if record.get("message_text") == REDACTED_TEXT else ObsState.EXPOSED


@dataclass(frozen=True)
class TableRule:
    """How one table's rows map to a system, a policy category and a state."""

    system_id: str
    category: Optional[str]
    state: StateRule


# SPEC F1: collection_name -> (category, state); the system is the row's origin_system.
_COLLECTIONS: Dict[str, Tuple[str, StateRule]] = {
    "customer_profiles": ("USER_PROFILE", _always(ObsState.PRESENT)),
    "customer_search_documents": ("SEARCH_INDEX_ENTRY", _always(ObsState.PRESENT)),
    "customer_analytics_reports": (
        "ANALYTICS_PROFILE",
        _identifiers_cleared(ANALYTICS_IDENTIFIERS, ObsState.ANONYMIZED, ObsState.EXPOSED),
    ),
    "support_conversations": ("SUPPORT_MESSAGE", _message_state),
    "ticket_attachments": ("SUPPORT_ATTACHMENT", _always(ObsState.PRESENT)),
    "customer_export_jobs": ("USER_EXPORT", _always(ObsState.PRESENT)),
    "connector_configurations": ("DATA_FLOW", _flag("enabled", ObsState.ACTIVE, ObsState.DISABLED)),
    "backup_catalog": ("BACKUP_ARCHIVE", _flag("restore_allowed", ObsState.ACTIVE, ObsState.BLOCKED)),
    "security_audit_events": ("SECURITY_AUDIT_LOG", _always(ObsState.PRESENT)),
    "retained_order_records": ("LEGAL_HOLD_RECORD", _always(ObsState.PRESENT)),
    "deleted_customer_references": (
        "ACCOUNT_TOMBSTONE",
        _identifiers_cleared(TOMBSTONE_IDENTIFIERS, ObsState.REDACTED, ObsState.EXPOSED),
    ),
}

# SPEC F2: typed inventory tables. Support rows cannot be told apart as message or
# attachment, so their category stays unset.
_INVENTORY: Dict[str, TableRule] = {
    "customer_profiles": TableRule(ACCOUNT_SERVICE, "USER_PROFILE", _always(ObsState.PRESENT)),
    "customer_search_documents": TableRule("search_service", "SEARCH_INDEX_ENTRY", _always(ObsState.PRESENT)),
    "customer_analytics_profiles": TableRule(
        "analytics_platform",
        "ANALYTICS_PROFILE",
        _identifiers_cleared(INVENTORY_ANALYTICS_IDENTIFIERS, ObsState.ANONYMIZED, ObsState.EXPOSED),
    ),
    "support_records": TableRule(
        "support_platform", None, _any_set(SUPPORT_REQUESTER_FIELDS, ObsState.EXPOSED, ObsState.REDACTED)
    ),
    "customer_exports": TableRule("export_service", "USER_EXPORT", _always(ObsState.PRESENT)),
    "connector_subscriptions": TableRule(
        "integration_service", "DATA_FLOW", _flag("enabled", ObsState.ACTIVE, ObsState.DISABLED)
    ),
    "backup_restore_entries": TableRule(
        "backup_service", "BACKUP_ARCHIVE", _flag("restore_allowed", ObsState.ACTIVE, ObsState.BLOCKED)
    ),
    "security_audit_records": TableRule("security_service", "SECURITY_AUDIT_LOG", _always(ObsState.PRESENT)),
}

# SPEC F3: special schemas.
_PROFILE_RULE = TableRule(ACCOUNT_SERVICE, "USER_PROFILE", _always(ObsState.PRESENT))
_SPECIAL: Dict[str, TableRule] = {
    "customer_profiles_primary": _PROFILE_RULE,
    "customer_profiles_failover_replica": _PROFILE_RULE,
    "search_documents_primary": TableRule("search_service", "SEARCH_INDEX_ENTRY", _always(ObsState.PRESENT)),
}
_POINTER_FIELD = "source_resource_id"


@dataclass(frozen=True)
class _Row:
    """One decoded row; identical rows of several tables are merged by `_merge`."""

    system_id: str
    resource_id: str
    category: Optional[str]
    state: ObsState
    keys: FrozenSet[str]
    pointer: Optional[str] = None


def account_pointer(locator: str) -> Optional[str]:
    """Account id a search document names as its source (SPEC L12.2), read from its locator."""
    match = _POINTER.search(locator)
    return match.group(1) if match else None


class SqlParser:
    """Parses SQLite-compatible `.sql` snapshots (SPEC F1-F3)."""

    name = "sql"

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        """True when the file opens with SQL statements or the snapshot header comment."""
        return _SQL_HEAD.search(head) is not None

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        """Decode every table into Observations plus the scopes the family asserts."""
        with closing(_load(entry, data)) as conn:
            try:
                grouped, scoped, notes = _read(conn, entry)
            except (sqlite3.Error, KeyError, ValueError) as error:
                raise ParseError("%s has malformed SQL rows: %r" % (entry.file_id, error))
        observations = tuple(_observation(entry, row, locator) for row, locator in _merge(grouped))
        scopes = tuple(_scope(entry, system, observations, cite_only) for system, cite_only in scoped)
        return ParseOutput(observations=observations, scopes=scopes, notes=notes)


def _load(entry: ManifestEntry, data: bytes) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(data.decode("utf-8"))
    except (sqlite3.Error, UnicodeDecodeError) as error:
        conn.close()
        raise ParseError("%s is not loadable SQL: %s" % (entry.file_id, error))
    return conn


def _table_names(conn: sqlite3.Connection) -> Tuple[str, ...]:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return tuple(row["name"] for row in cursor)


def _read(
    conn: sqlite3.Connection, entry: ManifestEntry
) -> Tuple[List[Tuple[str, _Row]], Tuple[Tuple[str, bool], ...], Tuple[str, ...]]:
    """Rows, scoped (system, cite_only) pairs and notes for the family the file's tables identify."""
    tables = _table_names(conn)
    family = _family(entry, tables)
    if family == TOPOLOGY:
        rows = _topology_rows(conn, tables)
        return rows, _topology_scope(rows), ()
    if family == INVENTORY:
        scoped, notes = _inventory_scope(conn, entry)
        return _inventory_rows(conn, tables), tuple((system, False) for system in scoped), notes
    return _special_rows(conn, entry, tables), tuple((s, False) for s in _special_scope(tables)), ()


def _family(entry: ManifestEntry, tables: Tuple[str, ...]) -> str:
    if TOPOLOGY_PRIMARY in tables:
        return TOPOLOGY
    if SCOPE_TABLE in tables:
        return INVENTORY
    if any(table in _SPECIAL for table in tables):
        return SPECIAL
    raise ParseError("%s has no recognised SQL schema: %s" % (entry.file_id, ", ".join(tables)))


def _select(conn: sqlite3.Connection, table: str, order_by: str) -> List[Dict[str, Any]]:
    cursor = conn.execute('SELECT * FROM "%s" ORDER BY %s' % (table.replace('"', '""'), order_by))
    return [dict(row) for row in cursor]


def _topology_rows(conn: sqlite3.Connection, tables: Tuple[str, ...]) -> List[Tuple[str, _Row]]:
    found: List[Tuple[str, _Row]] = []
    for table in tables:
        for row in _select(conn, table, "resource_id"):
            collection = row["collection_name"]
            if collection not in _COLLECTIONS:
                raise ParseError("%s: unknown collection %r" % (table, collection))
            category, state = _COLLECTIONS[collection]
            record = json.loads(row["record_json"])
            found.append((table, _Row(
                row["origin_system"], row["resource_id"], category, state(record), keys_from_record(record)
            )))
    return found


def _inventory_rows(conn: sqlite3.Connection, tables: Tuple[str, ...]) -> List[Tuple[str, _Row]]:
    return _typed_rows(conn, [table for table in tables if table in _INVENTORY], _INVENTORY)


def _special_rows(
    conn: sqlite3.Connection, entry: ManifestEntry, tables: Tuple[str, ...]
) -> List[Tuple[str, _Row]]:
    unknown = [table for table in tables if table not in _SPECIAL]
    if unknown:
        raise ParseError("%s: unknown special tables %s" % (entry.file_id, ", ".join(unknown)))
    return _typed_rows(conn, list(tables), _SPECIAL)


def _typed_rows(
    conn: sqlite3.Connection, tables: Iterable[str], rules: Mapping[str, TableRule]
) -> List[Tuple[str, _Row]]:
    found: List[Tuple[str, _Row]] = []
    for table in tables:
        rule = rules[table]
        for row in _select(conn, table, "resource_id"):
            found.append((table, _Row(
                rule.system_id, row["resource_id"], rule.category, rule.state(row),
                keys_from_record(row), row.get(_POINTER_FIELD),
            )))
    return found


def _inventory_scope(conn: sqlite3.Connection, entry: ManifestEntry) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """In-scope systems the inventory can enumerate, plus a note for any it cannot."""
    systems = [row["origin_system"] for row in _select(conn, SCOPE_TABLE, "origin_system")]
    enumerable = {rule.system_id for rule in _INVENTORY.values()}
    skipped = [system for system in systems if system not in enumerable]
    notes = tuple("%s: scope system %s has no inventory table" % (entry.file_id, s) for s in skipped)
    return tuple(system for system in systems if system in enumerable), notes


def _topology_scope(rows: List[Tuple[str, _Row]]) -> Tuple[Tuple[str, bool], ...]:
    """A topology snapshot listing any account row enumerates account_service, for citing only."""
    lists_accounts = any(row.system_id == ACCOUNT_SERVICE for _table, row in rows)
    return ((ACCOUNT_SERVICE, True),) if lists_accounts else ()


def _special_scope(tables: Tuple[str, ...]) -> Tuple[str, ...]:
    """The profile primary and failover tables enumerate account_service (SPEC F3)."""
    covers_accounts = any(_SPECIAL[table].system_id == ACCOUNT_SERVICE for table in tables)
    return (ACCOUNT_SERVICE,) if covers_accounts else ()


def _merge(rows: List[Tuple[str, _Row]]) -> List[Tuple[_Row, str]]:
    """Union rows across tables; one entry per distinct row with its table names as locator."""
    tables_of: Dict[_Row, List[str]] = {}
    for table, row in rows:
        tables_of.setdefault(row, []).append(table)
    merged = [(row, _locator(tuple(tables), row.pointer)) for row, tables in tables_of.items()]
    return sorted(merged, key=lambda item: (item[0].resource_id, item[0].system_id, item[1]))


def _locator(tables: Tuple[str, ...], pointer: Optional[str]) -> str:
    text = ",".join(tables)
    return text if pointer is None else "%s;%s=%s" % (text, _POINTER_FIELD, pointer)


def _observation(entry: ManifestEntry, row: _Row, locator: str) -> Observation:
    return Observation(
        file_id=entry.file_id,
        captured_at=entry.captured_at,
        entry_time=entry.captured_at,
        system_id=row.system_id,
        resource_id=row.resource_id,
        category=row.category,
        state=row.state,
        subject_keys=row.keys,
        locator=locator,
    )


def _scope(
    entry: ManifestEntry, system_id: str, observations: Tuple[Observation, ...], cite_only: bool
) -> ScopeAssertion:
    present = frozenset(o.resource_id for o in observations if o.system_id == system_id)
    return ScopeAssertion(entry.file_id, entry.captured_at, system_id, present, cite_only)
