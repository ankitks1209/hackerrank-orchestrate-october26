"""Output contract validator: structure, status rules and citations (SPEC 8, N8).

Implements SPEC 8.1 (status), 8.2 (step kinds per resource and the activity
citation window), 8.3 V1 (the case account step, reported as a warning), 8.4
(exact header, natural case order, seven keys per step, OPERATION_TABLE
membership, sort key and no duplicates), T3 (citation window) and AGENTS 6.3
to 6.6. This is the only implementation of the contract: main.py,
the evaluation tools and the tests all call it.
"""
from __future__ import annotations

import csv
import dataclasses
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ghostaudit.dataset import DatasetReader
from ghostaudit.emit import OUTPUT_COLUMNS, case_sort_key
from ghostaudit.model import (
    ACCOUNT_SERVICE,
    OPERATION_TABLE,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_NOT_APPLICABLE,
    Phase,
    Request,
    Step,
    op_index,
)

STATUSES = frozenset({STATUS_COMPLETE, STATUS_INCOMPLETE, STATUS_NOT_APPLICABLE})
STEP_FIELDS = frozenset(field.name for field in dataclasses.fields(Step))
_STRING_FIELDS = STEP_FIELDS - {"step_no"}
_VALID_TRIPLES = frozenset(
    (phase.name, operation, state)
    for phase, pairs in OPERATION_TABLE.items()
    for operation, state in pairs
)

StepDict = Dict[str, Any]


@dataclass(frozen=True)
class Violation:
    """One failed rule or warning; `case_id` is empty for file-level rules."""

    case_id: str
    rule: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Failures (must be empty for a valid output) and warnings (SPEC 8.3 V1, 8.4)."""

    violations: Tuple[Violation, ...]
    warnings: Tuple[Violation, ...]

    @property
    def ok(self) -> bool:
        """True when the output has no failures; warnings do not fail the output."""
        return not self.violations


@dataclass(frozen=True)
class Citations:
    """Citable ids and the times that bound them (SPEC T3, 8.2; AGENTS 6.6)."""

    files: Mapping[str, int]  # file_id -> captured_at (manifest clock)
    activities: Mapping[str, int]  # activity_id -> event_time
    audits: Mapping[str, int]  # audit_id -> event_time

    @classmethod
    def from_reader(cls, reader: DatasetReader) -> "Citations":
        """Index every participant-visible citable id of the dataset."""
        return cls(
            files={entry.file_id: entry.captured_at for entry in reader.manifest()},
            activities={row.activity_id: row.event_time for row in reader.activity()},
            audits={row.audit_id: row.event_time for row in reader.audit_log()},
        )


def validate(rows: Sequence[Sequence[str]], requests: Sequence[Request],
             citations: Citations) -> ValidationResult:
    """Check csv rows, header first, against the output contract (SPEC 8, N8)."""
    body = list(rows[1:])
    by_id = {request.case_id: request for request in requests}
    violations: List[Violation] = _check_header(rows) + _check_case_set(body, by_id)
    warnings: List[Violation] = []
    for row in body:
        row_violations, row_warnings = _check_row(row, by_id, citations)
        violations.extend(row_violations)
        warnings.extend(row_warnings)
    return ValidationResult(tuple(violations), tuple(warnings))


def validate_file(path: Path, requests: Sequence[Request],
                  citations: Citations) -> ValidationResult:
    """Validate an output.csv on disk (UTF-8, csv module rules)."""
    with path.open(encoding="utf-8", newline="") as handle:
        return validate(list(csv.reader(handle)), requests, citations)


def _check_header(rows: Sequence[Sequence[str]]) -> List[Violation]:
    if not rows or list(rows[0]) != list(OUTPUT_COLUMNS):
        return [Violation("", "header", "header must be %s" % ",".join(OUTPUT_COLUMNS))]
    return []


def _check_case_set(body: Sequence[Sequence[str]], by_id: Mapping[str, Request]) -> List[Violation]:
    """Rows are exactly the request set, once each, in natural order (SPEC 8.4)."""
    ids = [row[0] for row in body if row]
    counts = Counter(ids)
    failures = [Violation(case_id, "duplicate_case", "case_id appears %d times" % counts[case_id])
                for case_id in sorted(counts, key=case_sort_key) if counts[case_id] > 1]
    failures += [Violation(case_id, "unknown_case", "case_id is not in the request set")
                 for case_id in ids if case_id not in by_id]
    failures += [Violation(case_id, "missing_case", "request has no output row")
                 for case_id in sorted(by_id, key=case_sort_key) if case_id not in counts]
    if not failures and ids != sorted(by_id, key=case_sort_key):
        failures.append(Violation("", "case_order", "rows must follow natural case_id order"))
    return failures


def _check_row(row: Sequence[str], by_id: Mapping[str, Request],
               citations: Citations) -> Tuple[List[Violation], List[Violation]]:
    """Status, step and citation rules for one output row (SPEC 8.1 to 8.4)."""
    if len(row) != len(OUTPUT_COLUMNS):
        case_id = row[0] if row else ""
        message = "row must have %d fields" % len(OUTPUT_COLUMNS)
        return [Violation(case_id, "row_shape", message)], []
    case_id, status, steps_json = row
    request = by_id.get(case_id)
    if request is None:
        return [], []  # unknown ids are reported by _check_case_set
    if status not in STATUSES:
        return [Violation(case_id, "status", "deletion_status %r is not allowed" % status)], []
    steps, failures = _parse_steps(case_id, steps_json)
    if failures:
        return failures, []
    failures = _order_failures(case_id, steps) + _status_failures(
        case_id, status, steps, request, citations)
    return failures, _warnings(case_id, status, steps)


def _parse_steps(case_id: str, steps_json: str) -> Tuple[List[StepDict], List[Violation]]:
    """Decode steps_json and check each step's shape (SPEC 8.4; AGENTS 6.3)."""
    try:
        parsed = json.loads(steps_json)
    except ValueError as error:
        return [], [Violation(case_id, "steps_json", "steps_json is not valid JSON: %s" % error)]
    if not isinstance(parsed, list):
        return [], [Violation(case_id, "steps_json", "steps_json must be a JSON array")]
    failures: List[Violation] = []
    for number, raw in enumerate(parsed, start=1):
        failures.extend(_step_shape(case_id, raw, number))
    return parsed, failures


def _step_shape(case_id: str, raw: Any, number: int) -> List[Violation]:
    """Exactly seven keys, numbered 1..n, and (phase, operation, state) in OPERATION_TABLE."""
    if not isinstance(raw, dict) or set(raw) != STEP_FIELDS:
        message = "each step must have exactly the 7 AGENTS 6.3 keys"
        return [Violation(case_id, "step_shape", message)]
    failures: List[Violation] = []
    if type(raw["step_no"]) is not int or raw["step_no"] != number:
        message = "step %d must have step_no %d" % (number, number)
        failures.append(Violation(case_id, "step_no", message))
    if any(not isinstance(raw[name], str) for name in _STRING_FIELDS):
        message = "step fields other than step_no must be strings"
        return failures + [Violation(case_id, "step_shape", message)]
    triple = (raw["phase"], raw["operation"], raw["state"])
    if triple not in _VALID_TRIPLES:
        failures.append(Violation(case_id, "operation_table",
                                  "%s / %s / %s is not in OPERATION_TABLE" % triple))
    return failures


def _order_failures(case_id: str, steps: Sequence[StepDict]) -> List[Violation]:
    """No duplicate (phase, operation, system, resource) and the SPEC 8.4 sort key."""
    failures: List[Violation] = []
    seen = set()
    for step in steps:
        identity = (step["phase"], step["operation"], step["system_id"], step["resource_id"])
        if identity in seen:
            failures.append(Violation(case_id, "duplicate_step", "duplicate step %s" % (identity,)))
        seen.add(identity)
    keys = [_sort_key(step) for step in steps]
    if keys != sorted(keys):
        failures.append(Violation(case_id, "step_order", "steps must follow the SPEC 8.4 sort key"))
    return failures


def _sort_key(step: StepDict) -> Tuple[Any, ...]:
    phase = Phase[step["phase"]]
    return (phase, op_index(phase, step["operation"]), step["system_id"], step["resource_id"])


def _status_failures(case_id: str, status: str, steps: Sequence[StepDict], request: Request,
                     citations: Citations) -> List[Violation]:
    """Status rules of SPEC 8.1 and 8.2 with citation checks of T3."""
    if status == STATUS_NOT_APPLICABLE:
        if steps:
            message = "NOT_APPLICABLE rows must have steps_json []"
            return [Violation(case_id, "status_rule", message)]
        return []
    if status == STATUS_COMPLETE:
        return _complete_failures(case_id, steps, request, citations)
    return _incomplete_failures(case_id, steps, request, citations)


def _complete_failures(case_id: str, steps: Sequence[StepDict], request: Request,
                       citations: Citations) -> List[Violation]:
    failures: List[Violation] = []
    for step in steps:
        if step["phase"] != Phase.VERIFICATION.name:
            message = "COMPLETE rows may hold VERIFICATION steps only"
            failures.append(Violation(case_id, "status_rule", message))
        failures.extend(_citation_failures(case_id, step, request, citations))
    return failures


def _incomplete_failures(case_id: str, steps: Sequence[StepDict], request: Request,
                         citations: Citations) -> List[Violation]:
    failures: List[Violation] = []
    findings = [step for step in steps if step["phase"] == Phase.FINDING.name]
    if not findings:
        message = "INCOMPLETE rows need at least one FINDING"
        failures.append(Violation(case_id, "status_rule", message))
    for step in steps:
        if step["phase"] == Phase.FINDING.name:
            failures.extend(_citation_failures(case_id, step, request, citations))
        elif step["evidence_id"]:
            message = "REMEDIATION and VERIFICATION steps must have empty evidence_id"
            failures.append(Violation(case_id, "status_rule", message))
    return failures


def _citation_failures(case_id: str, step: StepDict, request: Request,
                       citations: Citations) -> List[Violation]:
    """A citation must be a known id whose time is inside the case window (SPEC T3, 8.2)."""
    evidence_id = step["evidence_id"]
    if not evidence_id:
        return [Violation(case_id, "citation", "%s step must cite a known id" % step["phase"])]
    found = _citable_time(evidence_id, citations)
    if found is None:
        message = "%s is not a known file, activity or audit id" % evidence_id
        return [Violation(case_id, "citation", message)]
    when, lower_bounded = found
    failures: List[Violation] = []
    if when > request.audit_at:
        failures.append(Violation(case_id, "citation", "%s is dated after audit_at" % evidence_id))
    if lower_bounded and when < request.reported_at:
        message = "%s is dated before reported_at" % evidence_id
        failures.append(Violation(case_id, "citation", message))
    return failures


def _citable_time(evidence_id: str, citations: Citations) -> Optional[Tuple[int, bool]]:
    """(time, has lower bound) for a known id.

    Audit ids are identity-history rows whose event may predate the window; they are
    bounded above only, by audit_at (AGENTS 6.2). Files and activity rows have both bounds.
    """
    if evidence_id in citations.files:
        return citations.files[evidence_id], True
    if evidence_id in citations.activities:
        return citations.activities[evidence_id], True
    if evidence_id in citations.audits:
        return citations.audits[evidence_id], False
    return None


def _warnings(case_id: str, status: str, steps: Sequence[StepDict]) -> List[Violation]:
    warnings: List[Violation] = []
    if status == STATUS_COMPLETE and not steps:
        warnings.append(Violation(case_id, "complete_without_steps",
                                  "COMPLETE row has no verification steps (SPEC 8.3 V1)"))
    has_account = any(step["system_id"] == ACCOUNT_SERVICE for step in steps)
    if status != STATUS_NOT_APPLICABLE and not has_account:
        warnings.append(Violation(case_id, "no_account_step",
                                  "deletion case has no account_service step (SPEC 8.3 V1)"))
    return warnings
