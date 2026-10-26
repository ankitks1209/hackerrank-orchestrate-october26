"""Grader emulations G1-G8, error taxonomy and Pareto comparison (SPEC A2).

Pure functions over `CaseResult` mappings: no I/O. Scoring is over
the gold cases; a gold case without a prediction scores as an empty answer.

Alignment definitions (the numbers are only interpretable with these):
- Step key: (phase, system_id, resource_id, operation, state, evidence_id).
  The order key drops evidence_id, so citations never affect order metrics.
- G3/G4 compare per-case multisets of step keys and pool the counts (micro).
- G5 aligns steps by (phase, system_id, resource_id), pairing duplicates by
  step_no, then compares `FIELD_KEYS`. Unaligned steps miss every field.
- G6 is the pooled LCS length over the pooled longer sequence length, per case
  on order keys; the exact-order rate restricts both sequences to their common
  multiset and requires equality.
- G8 aligns steps by step_no and compares `POSITIONAL_FIELDS`; a step_no present
  on one side only misses every field.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet, Dict, List, Mapping, Optional, Sequence, Tuple

from ghostaudit.config import COMPARE_TOLERANCE, COMPOSITE_WEIGHTS
from ghostaudit.model import ACCOUNT_SERVICE
from ghostaudit.emit import case_sort_key
from ghostaudit.model import CaseResult, Step

GRADERS: Tuple[Tuple[str, str], ...] = (
    ("G1", "status"),
    ("G2", "case exact (row-level)"),
    ("G3", "step F1"),
    ("G4", "step F1 without evidence_id"),
    ("G5", "key-aligned field accuracy"),
    ("G6", "sequence (LCS ratio)"),
    ("G7", "composite"),
    ("G8", "step_no-aligned positional accuracy"),
)

FIELD_KEYS = ("operation", "state", "evidence_id")
POSITIONAL_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
TAXONOMY = ("status", "missing", "extra", "wrong_op_state", "wrong_evidence",
            "order", "identity_miss", "structural")

Key = Tuple[str, ...]


@dataclass(frozen=True)
class Report:
    """All metrics of one scoring run."""

    cases: int
    raw: Mapping[str, float]  # grader id -> score
    normalized: Mapping[str, float]  # raw / ceiling
    ceilings: Mapping[str, float]
    details: Mapping[str, float]  # precision, recall, per-field accuracy, exact order
    taxonomy: Mapping[str, int]
    inexact_cases: Tuple[str, ...]  # cases not row-identical to gold, natural order
    status_mismatches: Tuple[str, ...]


@dataclass(frozen=True)
class Comparison:
    """Pareto verdict between two release candidates."""

    deltas: Mapping[str, float]
    regressions: Tuple[str, ...]
    improvements: Tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True when no grader regressed beyond the tolerance."""
        return not self.regressions


def score(gold: Mapping[str, CaseResult], pred: Mapping[str, CaseResult],
          ceilings: Optional[Mapping[str, float]] = None,
          structural: AbstractSet[str] = frozenset()) -> Report:
    """Score `pred` against `gold`; `structural` case ids bucket all their errors."""
    case_ids = sorted(gold, key=case_sort_key)
    pairs = [(gold[cid], pred.get(cid, CaseResult(cid, "", ()))) for cid in case_ids]
    total = len(pairs)

    exact = [g.deletion_status == p.deletion_status and g.steps == p.steps for g, p in pairs]
    status_ok = [g.deletion_status == p.deletion_status for g, p in pairs]
    f1_full, precision, recall = _step_f1(pairs, with_evidence=True)
    f1_bare, _, _ = _step_f1(pairs, with_evidence=False)
    field_acc, per_field = _field_accuracy(pairs)
    lcs_ratio, exact_order = _sequence(pairs)
    positional = _positional(pairs)

    raw = {
        "G1": _ratio(sum(status_ok), total),
        "G2": _ratio(sum(exact), total),
        "G3": f1_full,
        "G4": f1_bare,
        "G5": field_acc,
        "G6": lcs_ratio,
        "G8": positional,
    }
    raw["G7"] = sum(weight * raw[grader] for grader, weight in COMPOSITE_WEIGHTS.items())
    raw = {grader: raw[grader] for grader, _ in GRADERS}
    ceil = {grader: (ceilings or {}).get(grader, 1.0) for grader, _ in GRADERS}
    details = {"precision": precision, "recall": recall, "exact_order": exact_order}
    details.update(("field_" + name, value) for name, value in per_field.items())
    return Report(
        cases=total,
        raw=raw,
        normalized={grader: raw[grader] / ceil[grader] for grader in raw},
        ceilings=ceil,
        details=details,
        taxonomy=_taxonomy(pairs, structural),
        inexact_cases=tuple(g.case_id for (g, _), ok in zip(pairs, exact) if not ok),
        status_mismatches=tuple(g.case_id for (g, _), ok in zip(pairs, status_ok) if not ok),
    )


def compare(prev: Mapping[str, float], cur: Mapping[str, float],
            tolerance: float = COMPARE_TOLERANCE) -> Comparison:
    """Pareto no-regression between two `Report.normalized` mappings (strategy 1.4)."""
    graders = [grader for grader, _ in GRADERS]
    deltas = {grader: cur[grader] - prev[grader] for grader in graders}
    return Comparison(
        deltas=deltas,
        regressions=tuple(g for g in graders if deltas[g] < -tolerance),
        improvements=tuple(g for g in graders if deltas[g] > tolerance),
    )


def _ratio(numerator: float, denominator: float) -> float:
    """Accuracy with a vacuous 1.0 when nothing was expected."""
    return numerator / denominator if denominator else 1.0


def _step_key(step: Step, with_evidence: bool = True) -> Key:
    key = (step.phase, step.system_id, step.resource_id, step.operation, step.state)
    return key + (step.evidence_id,) if with_evidence else key


def _align_key(step: Step) -> Key:
    return (step.phase, step.system_id, step.resource_id)


def _step_f1(pairs: Sequence[Tuple[CaseResult, CaseResult]],
             with_evidence: bool) -> Tuple[float, float, float]:
    matched = gold_total = pred_total = 0
    for gold, pred in pairs:
        gold_keys = Counter(_step_key(s, with_evidence) for s in gold.steps)
        pred_keys = Counter(_step_key(s, with_evidence) for s in pred.steps)
        matched += sum((gold_keys & pred_keys).values())
        gold_total += len(gold.steps)
        pred_total += len(pred.steps)
    f1 = _ratio(2 * matched, gold_total + pred_total)
    return f1, _ratio(matched, pred_total), _ratio(matched, gold_total)


def _aligned(gold: CaseResult, pred: CaseResult
             ) -> Tuple[List[Tuple[Step, Step]], List[Step], List[Step]]:
    """Pair steps by alignment key (duplicates by step_no); return pairs, missing, extra."""
    gold_groups: Dict[Key, List[Step]] = {}
    pred_groups: Dict[Key, List[Step]] = {}
    for groups, steps in ((gold_groups, gold.steps), (pred_groups, pred.steps)):
        for step in sorted(steps, key=lambda s: s.step_no):
            groups.setdefault(_align_key(step), []).append(step)
    pairs: List[Tuple[Step, Step]] = []
    missing: List[Step] = []
    extra: List[Step] = []
    for key in sorted(set(gold_groups) | set(pred_groups)):
        left, right = gold_groups.get(key, []), pred_groups.get(key, [])
        shared = min(len(left), len(right))
        pairs.extend(zip(left[:shared], right[:shared]))
        missing.extend(left[shared:])
        extra.extend(right[shared:])
    return pairs, missing, extra


def _field_accuracy(pairs: Sequence[Tuple[CaseResult, CaseResult]]
                    ) -> Tuple[float, Dict[str, float]]:
    hits = Counter()
    total = 0
    for gold, pred in pairs:
        aligned, missing, extra = _aligned(gold, pred)
        total += len(aligned) + len(missing) + len(extra)
        for left, right in aligned:
            for name in FIELD_KEYS:
                hits[name] += getattr(left, name) == getattr(right, name)
    per_field = {name: _ratio(hits[name], total) for name in FIELD_KEYS}
    overall = _ratio(sum(hits.values()), total * len(FIELD_KEYS))
    return overall, per_field


def _lcs_length(left: Sequence[Key], right: Sequence[Key]) -> int:
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right):
            current.append(previous[index] + 1 if item == other
                           else max(previous[index + 1], current[index]))
        previous = current
    return previous[-1]


def _common_order(gold: Sequence[Key], pred: Sequence[Key]) -> bool:
    """True when both sequences, restricted to their common multiset, are equal."""
    common = Counter(gold) & Counter(pred)

    def restrict(sequence: Sequence[Key]) -> List[Key]:
        budget = Counter(common)
        kept = []
        for key in sequence:
            if budget[key] > 0:
                budget[key] -= 1
                kept.append(key)
        return kept

    return restrict(gold) == restrict(pred)


def _sequence(pairs: Sequence[Tuple[CaseResult, CaseResult]]) -> Tuple[float, float]:
    lcs_total = longest_total = ordered = 0
    for gold, pred in pairs:
        left = [_step_key(s, with_evidence=False) for s in _by_step_no(gold)]
        right = [_step_key(s, with_evidence=False) for s in _by_step_no(pred)]
        lcs_total += _lcs_length(left, right)
        longest_total += max(len(left), len(right))
        shares_steps = left == right or bool(set(left) & set(right))
        ordered += shares_steps and _common_order(left, right)
    return _ratio(lcs_total, longest_total), _ratio(ordered, len(pairs))


def _by_step_no(result: CaseResult) -> List[Step]:
    return sorted(result.steps, key=lambda step: step.step_no)


def _positional(pairs: Sequence[Tuple[CaseResult, CaseResult]]) -> float:
    hits = total = 0
    for gold, pred in pairs:
        left = {step.step_no: step for step in gold.steps}
        right = {step.step_no: step for step in pred.steps}
        for number in set(left) | set(right):
            total += len(POSITIONAL_FIELDS)
            if number in left and number in right:
                hits += sum(getattr(left[number], name) == getattr(right[number], name)
                            for name in POSITIONAL_FIELDS)
    return _ratio(hits, total)


def _taxonomy(pairs: Sequence[Tuple[CaseResult, CaseResult]],
              structural: AbstractSet[str]) -> Dict[str, int]:
    """Count errors; missing/extra/wrong_* are step-level, status/order case-level."""
    counts = Counter({name: 0 for name in TAXONOMY})
    for gold, pred in pairs:
        case = Counter()
        case["status"] += gold.deletion_status != pred.deletion_status
        aligned, missing, extra = _aligned(gold, pred)
        for step in missing:
            case["identity_miss" if step.system_id == ACCOUNT_SERVICE else "missing"] += 1
        case["extra"] += len(extra)
        for left, right in aligned:
            if (left.operation, left.state) != (right.operation, right.state):
                case["wrong_op_state"] += 1
            elif left.evidence_id != right.evidence_id:
                case["wrong_evidence"] += 1
        case["order"] += not _common_order(
            [_step_key(s, with_evidence=False) for s in _by_step_no(gold)],
            [_step_key(s, with_evidence=False) for s in _by_step_no(pred)])
        if gold.case_id in structural:
            counts["structural"] += sum(case.values())
        else:
            counts.update(case)
    return {name: counts[name] for name in TAXONOMY}
