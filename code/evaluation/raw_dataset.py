"""Raw participant-data loader for the label-free verifier (check P2).

Implements SPEC I1 and I2 (exact lower-cased subject keys) and T6 (UTC epoch seconds)
with the stdlib only. The label-free verifier must not share logic with the solver, so
this module re-reads `dataset/` with `csv` and builds its own subject keys; it imports
nothing from `ghostaudit` beyond constants (a test enforces this).

Only participant-facing files are read. `sample_output.csv` and anything outside
`dataset/` are never opened.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FIELD_EMAIL = "email"
FIELD_PHONE = "phone"
FIELD_HASH = "email_hash"
AUDIT_KEY_FIELDS = (FIELD_EMAIL, FIELD_PHONE, FIELD_HASH)
REQUESTS_FILE = "deletion_requests.csv"
SAMPLE_REQUESTS_FILE = "sample_deletion_requests.csv"

# Resource-id prefix -> system id (dataset fact, AGENTS 6.4 and SPEC 4); longest prefix first.
SYSTEM_BY_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("audit_record_", "security_service"),
    ("legal_hold_", "legal_service"),
    ("tombstone_", "identity_service"),
    ("data_flow_", "integration_service"),
    ("marketing_", "marketing_platform"),
    ("analytics_", "analytics_platform"),
    ("account_", "account_service"),
    ("support_", "support_platform"),
    ("search_", "search_service"),
    ("export_", "export_service"),
    ("backup_", "backup_service"),
    ("object_", "object_storage"),
    ("cache_", "cache_service"),
)
RESOURCE_ID_PATTERN = re.compile(
    r"\b(?:%s)\d+\b" % "|".join(prefix for prefix, _system in SYSTEM_BY_PREFIX)
)


def epoch(text: str) -> int:
    """UTC epoch seconds of an ISO-8601 `...Z` timestamp (SPEC T6)."""
    return int(datetime.strptime(text.strip(), TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp())


def system_of(resource_id: str) -> Optional[str]:
    """System that owns a resource id by its prefix, or None for an unknown prefix."""
    for prefix, system in SYSTEM_BY_PREFIX:
        if resource_id.startswith(prefix):
            return system
    return None


@dataclass(frozen=True)
class Req:
    """One request row with epoch times."""

    case_id: str
    email: str
    requested_at: int
    reported_status: str
    reported_at: int
    audit_at: int
    text: str
    is_sample: bool


@dataclass(frozen=True)
class File:
    """One evidence manifest row; `order` is the manifest row index."""

    file_id: str
    path: Path
    captured_at: int
    order: int


@dataclass(frozen=True)
class Act:
    """One system_activity.csv row."""

    activity_id: str
    t: int
    event_type: str
    source: str
    target: str
    resource_id: str
    details: str


@dataclass(frozen=True)
class AuditRow:
    """One user_audit_log.csv row."""

    audit_id: str
    user_id: str
    t: int
    field: str
    old: str
    new: str


@dataclass(frozen=True)
class RawDataset:
    """Everything the verifier reads from `dataset/`, with subject keys resolved."""

    root: Path
    requests: Tuple[Req, ...]
    files: Mapping[str, File]
    activity: Tuple[Act, ...]
    audit: Mapping[str, AuditRow]
    user_by_email: Mapping[str, str]
    keys_by_user: Mapping[str, FrozenSet[str]]
    user_by_key: Mapping[str, str]
    rule_categories: FrozenSet[str]

    def subject_of(self, req: Req) -> Optional[str]:
        """The user a request email resolves to, or None when it resolves to nobody (SPEC I3)."""
        return self.user_by_email.get(req.email.strip().lower())



def load_dataset(root: Path) -> RawDataset:
    """Read the participant files under `root` (the `dataset/` directory)."""
    identities = _read(root / "user_identities.csv")
    audit = tuple(_audit_row(row) for row in _read(root / "user_audit_log.csv"))
    keys, user_by_email = _subject_keys(identities, audit)
    user_by_key = {key: user for user, found in sorted(keys.items()) for key in found}
    requests = _requests(root / REQUESTS_FILE, False) + _requests(root / SAMPLE_REQUESTS_FILE, True)
    return RawDataset(
        root=root,
        requests=requests,
        files=_manifest(root),
        activity=tuple(_act(row) for row in _read(root / "system_activity.csv")),
        audit={row.audit_id: row for row in audit},
        user_by_email=user_by_email,
        keys_by_user={user: frozenset(found) for user, found in keys.items()},
        user_by_key=user_by_key,
        rule_categories=frozenset(row["data_category"] for row in _read(root / "deletion_rules.csv")),
    )


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _requests(path: Path, is_sample: bool) -> Tuple[Req, ...]:
    return tuple(
        Req(
            row["case_id"], row["email"], epoch(row["requested_at"]), row["reported_status"],
            epoch(row["reported_at"]), epoch(row["audit_at"]), row["request_text"], is_sample,
        )
        for row in _read(path)
    )


def _manifest(root: Path) -> Dict[str, File]:
    return {
        row["file_id"]: File(row["file_id"], root / row["file_path"], epoch(row["captured_at"]), index)
        for index, row in enumerate(_read(root / "evidence_files.csv"))
    }


def _act(row: Mapping[str, str]) -> Act:
    return Act(
        row["activity_id"], epoch(row["event_time"]), row["event_type"], row["source_system"],
        row["target_system"], row["resource_id"], row["details"],
    )


def _audit_row(row: Mapping[str, str]) -> AuditRow:
    return AuditRow(
        row["audit_id"], row["user_id"], epoch(row["event_time"]), row["field_name"],
        row["old_value"], row["new_value"],
    )


def _digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _subject_keys(
    identities: Sequence[Mapping[str, str]], audit: Sequence[AuditRow]
) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    """Per user: current and historical emails, hashes, phones and the user id (SPEC I2)."""
    keys: Dict[str, Set[str]] = {}
    user_by_email: Dict[str, str] = {}
    for row in identities:
        user = row["user_id"]
        found = keys.setdefault(user, {user.lower()})
        for value in (row[FIELD_EMAIL], row[FIELD_PHONE], row[FIELD_HASH]):
            if value:
                found.add(value.strip().lower())
        found.add(_digest(row[FIELD_EMAIL]))
        user_by_email[row[FIELD_EMAIL].strip().lower()] = user
    for entry in audit:
        if entry.field not in AUDIT_KEY_FIELDS:
            continue
        found = keys.setdefault(entry.user_id, {entry.user_id.lower()})
        for value in (entry.old, entry.new):
            if value:
                found.add(value.strip().lower())
                if entry.field == FIELD_EMAIL:
                    found.add(_digest(value))
                    user_by_email.setdefault(value.strip().lower(), entry.user_id)
    return keys, user_by_email
