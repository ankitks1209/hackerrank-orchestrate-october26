"""Allowlisted access to participant inputs and typed CSV loaders (SPEC 2, N3, N5).

Implements SPEC 2 (input files and their columns), N3 (the pipeline never reads
sample_output.csv or solution/) and N5 (pathlib, UTF-8, paths relative to the
dataset root). Every input read goes through DatasetReader.open, so the allowlist
is enforced in one place.
"""
from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from ghostaudit.model import ManifestEntry, Request
from ghostaudit.timeutil import to_epoch

PARTICIPANT_CSVS = frozenset(
    {
        "deletion_requests.csv",
        "sample_deletion_requests.csv",
        "user_identities.csv",
        "user_audit_log.csv",
        "system_activity.csv",
        "deletion_rules.csv",
        "evidence_files.csv",
        "output.csv",
    }
)
EVIDENCE_DIR = "evidence"
REQUIRED_CSVS = tuple(sorted(PARTICIPANT_CSVS - {"output.csv"}))  # SPEC 2: the inputs a run reads


class DatasetError(Exception):
    """A dataset file is missing, malformed or inconsistent."""


class ForbiddenInputError(DatasetError):
    """A path is outside the participant allowlist (SPEC N3)."""


@dataclass(frozen=True)
class Identity:
    """One row of user_identities.csv: the current identity snapshot (SPEC 2, I2)."""

    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: int


@dataclass(frozen=True)
class AuditRow:
    """One row of user_audit_log.csv: a historical identity field change (SPEC 2, I2)."""

    audit_id: str
    user_id: str
    event_time: int
    field_name: str
    old_value: str
    new_value: str


@dataclass(frozen=True)
class ActivityRow:
    """One row of system_activity.csv, as recorded; classification is in activity.py."""

    activity_id: str
    event_time: int
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass(frozen=True)
class Rule:
    """One row of deletion_rules.csv; required_action is kept as written (SPEC 6)."""

    rule_id: str
    data_category: str
    condition: str
    required_action: str


def _loaded_once(loader: Callable[["DatasetReader"], Tuple[Any, ...]]) -> Callable[["DatasetReader"], Tuple[Any, ...]]:
    """Parse a file on the first call of a reader and hand the same rows to every later call."""

    @functools.wraps(loader)
    def wrapper(self: "DatasetReader") -> Tuple[Any, ...]:
        if loader.__name__ not in self._loaded:
            self._loaded[loader.__name__] = loader(self)
        return self._loaded[loader.__name__]

    return wrapper


class DatasetReader:
    """Reads the allowlisted participant files under one dataset root (SPEC N3).

    Each typed loader parses its file once per reader; the rows are immutable.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._evidence_root = (self._root / EVIDENCE_DIR).resolve()
        self._loaded: Dict[str, Tuple[Any, ...]] = {}

    def open(self, rel: str) -> Path:
        """Return the resolved path of an allowlisted input; refuse any other path.

        Allowed: the participant CSVs directly under the root, and any file below
        evidence/. Resolution follows symlinks, so a link out of the dataset is
        refused too.
        """
        target = (self._root / rel).resolve()
        if not self._is_allowed(target):
            raise ForbiddenInputError("input is outside the participant allowlist: %s" % rel)
        return target

    def check_complete(self) -> None:
        """Raise DatasetError naming every required input that is missing (SPEC 2)."""
        missing = [name for name in REQUIRED_CSVS if not (self._root / name).is_file()]
        if not self._evidence_root.is_dir():
            missing.append(EVIDENCE_DIR + "/")
        if missing:
            raise DatasetError("dataset %s is missing: %s" % (self._root, ", ".join(missing)))

    @_loaded_once
    def requests(self) -> Tuple[Request, ...]:
        """Evaluation requests in file order, then sample requests (SPEC 2)."""
        return self._requests("deletion_requests.csv", False) + self._requests(
            "sample_deletion_requests.csv", True
        )

    @_loaded_once
    def identities(self) -> Tuple[Identity, ...]:
        """Current identity snapshot, one entry per user (SPEC 2, I2)."""
        return tuple(
            Identity(
                user_id=row["user_id"],
                name=row["name"],
                email=row["email"],
                phone=row["phone"],
                email_hash=row["email_hash"],
                updated_at=to_epoch(row["updated_at"]),
            )
            for row in self._rows("user_identities.csv")
        )

    @_loaded_once
    def audit_log(self) -> Tuple[AuditRow, ...]:
        """Historical identity field changes in file order (SPEC 2, I2)."""
        return tuple(
            AuditRow(
                audit_id=row["audit_id"],
                user_id=row["user_id"],
                event_time=to_epoch(row["event_time"]),
                field_name=row["field_name"],
                old_value=row["old_value"],
                new_value=row["new_value"],
            )
            for row in self._rows("user_audit_log.csv")
        )

    @_loaded_once
    def activity(self) -> Tuple[ActivityRow, ...]:
        """Raw system activity rows in file order (SPEC 2, SPEC 4)."""
        return tuple(
            ActivityRow(
                activity_id=row["activity_id"],
                event_time=to_epoch(row["event_time"]),
                event_type=row["event_type"],
                source_system=row["source_system"],
                target_system=row["target_system"],
                resource_id=row["resource_id"],
                reported_result=row["reported_result"],
                details=row["details"],
            )
            for row in self._rows("system_activity.csv")
        )

    @_loaded_once
    def rules(self) -> Tuple[Rule, ...]:
        """Deletion policy rows in file order (SPEC 6)."""
        return tuple(
            Rule(
                rule_id=row["rule_id"],
                data_category=row["data_category"],
                condition=row["condition"],
                required_action=row["required_action"],
            )
            for row in self._rows("deletion_rules.csv")
        )

    @_loaded_once
    def manifest(self) -> Tuple[ManifestEntry, ...]:
        """Evidence manifest in file order; `order` is the row index (SPEC 5 T2)."""
        return tuple(
            ManifestEntry(
                file_id=row["file_id"],
                path=self.open(row["file_path"]),
                origin=row["origin"],
                captured_at=to_epoch(row["captured_at"]),
                order=index,
            )
            for index, row in enumerate(self._rows("evidence_files.csv"))
        )

    def _is_allowed(self, target: Path) -> bool:
        if target.parent == self._root:
            return target.name in PARTICIPANT_CSVS
        return self._evidence_root in target.parents

    def _requests(self, rel: str, is_sample: bool) -> Tuple[Request, ...]:
        return tuple(
            Request(
                case_id=row["case_id"],
                email=row["email"],
                requested_at=to_epoch(row["requested_at"]),
                reported_status=row["reported_status"],
                reported_at=to_epoch(row["reported_at"]),
                audit_at=to_epoch(row["audit_at"]),
                text=row["request_text"],
                is_sample=is_sample,
            )
            for row in self._rows(rel)
        )

    def _rows(self, rel: str) -> List[Dict[str, str]]:
        with self.open(rel).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
