"""Turn resource verdicts into ordered steps and write output.csv.

Implements SPEC 8.1 (status), 8.2 (steps per resource) and 8.4 (ordering and
serialization). Ported from the emit prototype; operation names, states and
order come from `model.OPERATION_TABLE` and `model.TREATMENT_OPS`.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import re
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple, Union

from ghostaudit.model import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    TREATMENT_OPS,
    CaseResult,
    Phase,
    ResourceVerdict,
    Step,
    op_index,
    state_of,
)

OUTPUT_COLUMNS = ("case_id", "deletion_status", "steps_json")
_DIGITS = re.compile(r"(\d+)")

_RawStep = Tuple[Phase, str, str, str, str]  # phase, operation, system, resource, evidence


def emit(verdicts: Sequence[ResourceVerdict]) -> Tuple[str, Tuple[Step, ...]]:
    """Return (status, ordered steps) for one deletion case (SPEC 8.1, 8.2, 8.4).

    A violating resource gets FINDING (cited), REMEDIATION and VERIFICATION
    (both with an empty evidence id). A compliant resource gets only a
    VERIFICATION step, cited when the whole case is COMPLETE. Resources with
    no citable proof in a COMPLETE case are omitted by the caller (SPEC 8.2).
    """
    incomplete = any(verdict.violating for verdict in verdicts)
    raw: List[_RawStep] = []
    for verdict in verdicts:
        raw.extend(_resource_steps(verdict, incomplete))
    raw.sort(key=lambda step: (step[0], op_index(step[0], step[1]), step[2], step[3]))
    status = STATUS_INCOMPLETE if incomplete else STATUS_COMPLETE
    return status, _number(_deduplicate(raw))


def _resource_steps(verdict: ResourceVerdict, incomplete: bool) -> List[_RawStep]:
    finding_op, remediation_op, verify_op = TREATMENT_OPS[verdict.treatment]
    system, resource = verdict.system_id, verdict.resource_id
    steps: List[_RawStep] = []
    if verdict.violating:
        if finding_op is None or remediation_op is None:
            raise ValueError(
                "treatment %s has no finding or remediation operation (%s %s)"
                % (verdict.treatment.value, system, resource))
        steps.append((Phase.FINDING, finding_op, system, resource, verdict.cite))
        steps.append((Phase.REMEDIATION, remediation_op, system, resource, ""))
    verify_cite = "" if incomplete else verdict.cite
    steps.append((Phase.VERIFICATION, verify_op, system, resource, verify_cite))
    return steps


def _deduplicate(raw: Sequence[_RawStep]) -> List[_RawStep]:
    """Keep the first step per (phase, operation, system, resource) in sorted order."""
    seen = set()
    unique: List[_RawStep] = []
    for step in raw:
        key = step[:4]
        if key not in seen:
            seen.add(key)
            unique.append(step)
    return unique


def _number(raw: Sequence[_RawStep]) -> Tuple[Step, ...]:
    return tuple(
        Step(step_no=number, phase=phase.name, system_id=system, resource_id=resource,
             operation=operation, state=state_of(operation), evidence_id=evidence)
        for number, (phase, operation, system, resource, evidence) in enumerate(raw, start=1))


def serialize(steps: Iterable[Step]) -> str:
    """Compact JSON array with sorted keys (SPEC 8.4)."""
    return json.dumps([dataclasses.asdict(step) for step in steps],
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def case_sort_key(case_id: str) -> Tuple[Union[int, str], ...]:
    """Natural order: `case_9` sorts before `case_10` (SPEC 8.4)."""
    return tuple(int(part) if part.isdigit() else part for part in _DIGITS.split(case_id))


def write_output(results: Iterable[CaseResult], path: Path) -> None:
    """Write output.csv: exact header, natural case order, UTF-8, LF (SPEC 8.4)."""
    ordered = sorted(results, key=lambda result: case_sort_key(result.case_id))
    ids = [result.case_id for result in ordered]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case_id in results")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(OUTPUT_COLUMNS)
        for result in ordered:
            writer.writerow((result.case_id, result.deletion_status, serialize(result.steps)))
