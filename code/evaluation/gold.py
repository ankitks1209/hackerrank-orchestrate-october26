"""Gold helper of the scorer and the tests (AGENTS 6.7; SPEC 8.2, 8.4).

`GoldReader` is the only code that opens `sample_output.csv`; it lives in `evaluation/`. `abstract_verdicts` inverts `ghostaudit.emit.emit`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from ghostaudit.config import REPO_ROOT
from ghostaudit.model import (
    TREATMENT_OPS,
    CaseResult,
    ResourceVerdict,
    Step,
    Treatment,
)

SAMPLE_OUTPUT = REPO_ROOT / "dataset" / "sample_output.csv"
_TREATMENT_BY_REMEDIATION = {ops[1]: treatment for treatment, ops in TREATMENT_OPS.items() if ops[1]}
_TREATMENT_BY_VERIFICATION = {ops[2]: treatment for treatment, ops in TREATMENT_OPS.items()}
_FINDING = "FINDING"
_REMEDIATION = "REMEDIATION"
_VERIFICATION = "VERIFICATION"


class GoldReader:
    """Reads the public gold answers from `sample_output.csv`."""

    def __init__(self, path: Path = SAMPLE_OUTPUT) -> None:
        self._path = path

    def cases(self) -> Dict[str, CaseResult]:
        """Gold CaseResult per case_id, steps in gold array order."""
        with self._path.open(encoding="utf-8", newline="") as handle:
            return {row["case_id"]: _to_result(row) for row in csv.DictReader(handle)}


def _to_result(row: Dict[str, str]) -> CaseResult:
    steps = tuple(Step(**raw) for raw in json.loads(row["steps_json"]))
    return CaseResult(row["case_id"], row["deletion_status"], steps)


def abstract_verdicts(gold_steps: Sequence[Step]) -> List[ResourceVerdict]:
    """Invert `emit`: one verdict per (system, resource), ordered by first appearance.

    The treatment comes from the verification operation (remediation as fallback);
    a resource with a FINDING step is violating and carries that step's evidence,
    otherwise it carries the verification step's evidence.
    """
    grouped: Dict[Tuple[str, str], List[Step]] = {}
    for step in sorted(gold_steps, key=lambda step: step.step_no):
        grouped.setdefault((step.system_id, step.resource_id), []).append(step)
    return [_abstract_resource(key, steps) for key, steps in grouped.items()]


def _abstract_resource(key: Tuple[str, str], steps: Sequence[Step]) -> ResourceVerdict:
    finding = next((s for s in steps if s.phase == _FINDING), None)
    return ResourceVerdict(
        system_id=key[0],
        resource_id=key[1],
        treatment=_treatment_of(key, steps),
        violating=finding is not None,
        cite=finding.evidence_id if finding else _verification_cite(steps),
        basis="gold",
        reason="abstracted from gold steps",
    )


def _treatment_of(key: Tuple[str, str], steps: Sequence[Step]) -> Treatment:
    for step in steps:
        if step.phase == _VERIFICATION:
            return _TREATMENT_BY_VERIFICATION[step.operation]
    for step in steps:
        if step.phase == _REMEDIATION:
            return _TREATMENT_BY_REMEDIATION[step.operation]
    raise ValueError("no verification or remediation step for %s %s" % key)


def _verification_cite(steps: Sequence[Step]) -> str:
    return next((s.evidence_id for s in steps if s.phase == _VERIFICATION), "")
