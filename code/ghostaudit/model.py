"""Immutable domain vocabulary: enums, records and the operation table.

Implements SPEC 3.1 (normalized records) and 8.4 (operation order);
the operation table is AGENTS 6.4 verbatim and is the single source of
truth for operation names, states and ordering (emitter and validator).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple


# System ids the rules name directly; every other system id comes from policy.SYSTEM_BY_PREFIX.
ACCOUNT_SERVICE = "account_service"
SECURITY_SERVICE = "security_service"
LEGAL_SERVICE = "legal_service"


class Phase(IntEnum):
    """Step phases in required output order."""

    FINDING = 0
    REMEDIATION = 1
    VERIFICATION = 2


class Treatment(Enum):
    """Required handling of a resource under deletion_rules.csv (SPEC 6)."""

    DELETE = "DELETE"
    REDACT = "REDACT"
    ANONYMIZE = "ANONYMIZE"
    RETAIN = "RETAIN"
    FLOW = "FLOW"
    RESTORE = "RESTORE"


class ObsState(Enum):
    """Observed state of a resource (SPEC 3.1)."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXPOSED = "EXPOSED"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"


# SPEC F6: `result` vocabulary of flat ledgers, handover text and record_lookup logs.
RESULT_STATES: Dict[str, ObsState] = {
    "FOUND": ObsState.PRESENT,
    "NOT_FOUND": ObsState.ABSENT,
    "IDENTIFIABLE": ObsState.EXPOSED,
    "ANONYMIZED": ObsState.ANONYMIZED,
    "REDACTED": ObsState.REDACTED,
    "ACTIVE": ObsState.ACTIVE,
    "DISABLED": ObsState.DISABLED,
    "BLOCKED": ObsState.BLOCKED,
}


class ActKind(Enum):
    """Activity template classes (SPEC 4)."""

    ACCOUNT_SUBMIT = "ACCOUNT_SUBMIT"
    POLICY_OK = "POLICY_OK"
    VIOLATION = "VIOLATION"
    FLOW_ENABLED = "FLOW_ENABLED"
    RESTORE_ALLOWED = "RESTORE_ALLOWED"
    REPLICATION_CHECKPOINT = "REPLICATION_CHECKPOINT"
    REPOPULATED = "REPOPULATED"
    RESTORE_REPOPULATED = "RESTORE_REPOPULATED"
    NON_DELETION = "NON_DELETION"
    LINK = "LINK"
    TARGET_RESOURCE = "TARGET_RESOURCE"
    NOISE = "NOISE"
    UNCLASSIFIED = "UNCLASSIFIED"  # matches no template; inert like NOISE and reported in the diagnostics


STATUS_COMPLETE = "COMPLETE"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

# AGENTS 6.4: {phase: ((operation, state), ...)} in table order.
OPERATION_TABLE: Dict[Phase, Tuple[Tuple[str, str], ...]] = {
    Phase.FINDING: (
        ("REPORT_REMAINING_RECORD", "PRESENT"),
        ("REPORT_EXPOSED_PII", "PRESENT"),
        ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
        ("REPORT_RESTORE_RISK", "ACTIVE"),
    ),
    Phase.REMEDIATION: (
        ("DISABLE_DATA_FLOW", "DISABLED"),
        ("BLOCK_RESTORE", "BLOCKED"),
        ("DELETE_RECORD", "ABSENT"),
        ("REDACT_RECORD", "REDACTED"),
        ("ANONYMIZE_RECORD", "ANONYMIZED"),
    ),
    Phase.VERIFICATION: (
        ("VERIFY_RECORD_ABSENT", "ABSENT"),
        ("VERIFY_RECORD_PRESENT", "PRESENT"),
        ("VERIFY_RECORD_REDACTED", "REDACTED"),
        ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
        ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
        ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
    ),
}

_OP_INDEX: Dict[Tuple[Phase, str], int] = {
    (phase, op): index
    for phase, pairs in OPERATION_TABLE.items()
    for index, (op, _state) in enumerate(pairs)
}
_STATE_OF: Dict[str, str] = {
    op: state for pairs in OPERATION_TABLE.values() for op, state in pairs
}

# Treatment -> (finding op, remediation op, verification op); None = not needed.
TREATMENT_OPS: Dict[Treatment, Tuple[Optional[str], Optional[str], str]] = {
    Treatment.DELETE: ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    Treatment.REDACT: ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    Treatment.ANONYMIZE: ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    Treatment.FLOW: ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    Treatment.RESTORE: ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
    Treatment.RETAIN: (None, None, "VERIFY_RECORD_PRESENT"),
}


def op_index(phase: Phase, operation: str) -> int:
    """Position of an operation inside its phase's table (SPEC 8.4 sort key)."""
    return _OP_INDEX[(phase, operation)]


def state_of(operation: str) -> str:
    """State attached to an operation by AGENTS 6.4."""
    return _STATE_OF[operation]


@dataclass(frozen=True)
class Request:
    """One row of deletion_requests.csv with times as integer epochs (AGENTS 6.2)."""

    case_id: str
    email: str
    requested_at: int
    reported_status: str
    reported_at: int
    audit_at: int
    text: str
    is_sample: bool


@dataclass(frozen=True)
class ManifestEntry:
    """One row of evidence_files.csv; `order` is the manifest row index."""

    file_id: str
    path: Path
    origin: str
    captured_at: int
    order: int


@dataclass(frozen=True)
class Observation:
    """Normalized evidence record (SPEC 3.1); entry_time falls back to captured_at."""

    file_id: str
    captured_at: int
    entry_time: Optional[int]
    system_id: str
    resource_id: str
    category: Optional[str]
    state: ObsState
    subject_keys: FrozenSet[str]
    locator: str

    @property
    def effective_entry_time(self) -> int:
        """SPEC T2: the entry time, `captured_at` when the observation has none."""
        return self.captured_at if self.entry_time is None else self.entry_time


@dataclass(frozen=True)
class ScopeAssertion:
    """Resource ids a file asserts as present for a system (SPEC 3.1).

    `cite_only` marks a scope that may be cited as an absence proof by a file the case
    already cites (SPEC V5.1) but never decides a resource's state or the window fallback.
    """

    file_id: str
    captured_at: int
    system_id: str
    present_ids: FrozenSet[str]
    cite_only: bool = False


@dataclass(frozen=True)
class MediaFacts:
    """Validated LLM extraction for one image or PDF (SPEC F10)."""

    file_id: str
    records: Tuple[dict, ...]


@dataclass(frozen=True)
class ClassifiedActivity:
    """A system_activity.csv row classified by template (SPEC 4)."""

    activity_id: str
    t: int
    kind: ActKind
    system_id: str
    resource_id: str
    treatment: Optional[Treatment]
    reported_result: str
    related_rid: Optional[str]
    alias: Optional[str]
    linked_user: Optional[str]
    linked_email: Optional[str]

    @property
    def order_key(self) -> Tuple[int, str]:
        """Stream order of SPEC 4: by time, then activity id."""
        return self.t, self.activity_id


@dataclass(frozen=True)
class LinkedResource:
    """A resource attached to a case by linking (SPEC 7); `basis` names the rule."""

    system_id: str
    resource_id: str
    treatment: Treatment
    basis: str


@dataclass(frozen=True)
class CaseLinks:
    """Linking result for one case (SPEC 7)."""

    case_id: str
    account_id: Optional[str]
    account_basis: str
    resources: Tuple[LinkedResource, ...]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class ResourceVerdict:
    """State decision for one resource at audit_at (SPEC 8)."""

    system_id: str
    resource_id: str
    treatment: Treatment
    violating: bool
    cite: str
    basis: str
    reason: str
    note: str = ""  # evidence/template disagreement the resolver saw for this resource (SPEC 4)


@dataclass(frozen=True)
class Step:
    """One output step; exactly the seven AGENTS 6.3 fields."""

    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str


@dataclass(frozen=True)
class CaseResult:
    """Final answer for one case: status plus ordered steps (AGENTS 6.3)."""

    case_id: str
    deletion_status: str
    steps: Tuple[Step, ...]
