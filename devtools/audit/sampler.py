"""Case selection for the blind audit (T39; LOCAL_EVALUATION_STRATEGY P3a, P3b).

Two selections:

* the coverage set: every forced case, then a greedy cover of the cells (file family, system,
  operation, status) that the output uses. Forced in are the cases that cite an image or PDF, the
  hand-crafted and media family (no account row, read from `diagnostics.md`), the low-confidence
  tier (from the tiers JSON) and every P2 exception (a P2a locator failure, any P2b recall item, a
  P2c unexplained item), plus `--force`. The JSON names the reason of each forced case. The set is
  for bug-hunting and is never an accuracy estimate;
* the estimation sample: drawn once, after the code freeze, from every evaluation case (coverage
  cases included, so that the estimate describes the whole output; a case in both sets is labelled
  once), stratified by confidence tier with a fixed seed. Each draw carries the weight
  `stratum size / stratum quota`, the inverse of its inclusion probability, so a weighted mean over
  the draws estimates the mean over all cases even when a small stratum is oversampled.

Selection is a pure function of the output, the run's diagnostics, the manifest and the seed; ties
break by natural case order, and the draw orders cases by `sha256(seed:case_id)`, so it is identical
on every Python.

    python3 devtools/audit/sampler.py --pred output.csv --diag diagnostics.md \
        --samples-pred sample_predictions.csv --tiers tiers.json [--seed S --size 120]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

CODE_DIR = Path(__file__).resolve().parents[2] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from evaluation import verify_steps  # noqa: E402
from evaluation.raw_dataset import RawDataset, load_dataset  # noqa: E402
from evaluation.redundancy import CASE_HEADING  # noqa: E402
from evaluation.verify_steps import NOT_APPLICABLE, Case, read_output  # noqa: E402

NO_FILE = "none"
UNKNOWN_TIER = "unknown"
LOW_TIER = "low"
NO_ACCOUNT_ROW = re.compile(r"^- Account: .*\(link basis none\)$", re.MULTILINE)
# Reasons a case is forced into the coverage set, in report order.
FORCED_MEDIA = "cites an image or PDF"
FORCED_HANDCRAFTED = "hand-crafted or media family"
FORCED_LOW_TIER = "low confidence tier"
FORCED_P2 = "P2 exception"
FORCED_BY_CALLER = "forced by --force"
MEDIA_SUFFIXES = (".png", ".pdf")
MIN_ESTIMATION_SIZE = 100
DIGITS = re.compile(r"[0-9_]*\d[0-9_]*$")
Cell = Tuple[str, str, str, str]  # file family, system, operation, status


def file_family(dataset: RawDataset, evidence_id: str) -> str:
    """The folder and the name of a cited file without its date or number (`databases/customer_data_inventory`)."""
    if not evidence_id:
        return NO_FILE
    entry = dataset.files.get(evidence_id)
    if entry is None:
        return "row" if evidence_id.startswith(("activity_", "audit_")) else NO_FILE
    stem = DIGITS.sub("", entry.path.stem)
    return "%s/%s" % (entry.path.parent.name, stem.rstrip("_"))


def cells_of(dataset: RawDataset, case: Case) -> FrozenSet[Cell]:
    """Every (file family, system, operation, status) cell that one case exercises."""
    return frozenset((file_family(dataset, step.evidence_id), step.system_id, step.operation, case.status)
                     for step in case.steps)


def image_cases(dataset: RawDataset, cases: Mapping[str, Case]) -> FrozenSet[str]:
    """Cases that cite an image or PDF."""
    media = {file_id for file_id, entry in dataset.files.items() if entry.path.suffix.lower() in MEDIA_SUFFIXES}
    return frozenset(case_id for case_id, case in cases.items() if any(s.evidence_id in media for s in case.steps))


def handcrafted_cases(diagnostics: str) -> FrozenSet[str]:
    """Evaluation deletion cases built without an account row (SPEC L12), read from `diagnostics.md`."""
    sections = CASE_HEADING.split(diagnostics)
    return frozenset(
        sections[index] for index in range(1, len(sections) - 3, 4)
        if sections[index + 1] == "evaluation" and NO_ACCOUNT_ROW.search(sections[index + 3])
    )


def low_tier_cases(tiers: Mapping[str, str]) -> FrozenSet[str]:
    return frozenset(case_id for case_id, tier in tiers.items() if tier == LOW_TIER)


def p2_exception_cases(
    dataset: RawDataset, cases: Mapping[str, Case], samples: Optional[Mapping[str, Case]]
) -> FrozenSet[str]:
    """Cases with a P2a failure, any P2b item or a P2c unexplained item (P2c needs `samples`).

    P2b items are ids beside the subject's own key that the case does not emit, so every one is
    worth a look; P2c's explained items are other people's rows (decoys, ownerless policy rows).
    """
    found = {item.case_id for item in verify_steps.locator_check(dataset, cases) if item.code == verify_steps.FAILED}
    found |= {item.case_id for item in verify_steps.recall_sweep(dataset, cases)}
    if samples is not None:
        found |= {item.case_id for item in verify_steps.coverage_sweep(dataset, cases, samples)
                  if item.code == verify_steps.UNEXPLAINED}
    return frozenset(found)


def forced_cases(
    dataset: RawDataset,
    cases: Mapping[str, Case],
    diagnostics: Optional[str],
    tiers: Mapping[str, str],
    samples: Optional[Mapping[str, Case]],
    extra: Iterable[str] = (),
) -> Dict[str, List[str]]:
    """{reason: case ids} of the cases forced into the coverage set; a missing input gives none.

    The P2 sweeps run only when `cases` answers every evaluation request (they walk the requests).
    """
    evaluation = {req.case_id for req in dataset.requests if not req.is_sample}
    reasons: Dict[str, Iterable[str]] = {
        FORCED_MEDIA: image_cases(dataset, cases),
        FORCED_HANDCRAFTED: handcrafted_cases(diagnostics) if diagnostics else (),
        FORCED_LOW_TIER: low_tier_cases(tiers),
        FORCED_P2: p2_exception_cases(dataset, cases, samples) if evaluation <= set(cases) else (),
        FORCED_BY_CALLER: extra,
    }
    return {reason: sorted((c for c in set(found) if c in cases), key=natural_key) for reason, found in reasons.items()}


def natural_key(case_id: str) -> Tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", case_id))


def coverage_set(
    dataset: RawDataset, cases: Mapping[str, Case], forced: Iterable[str] = ()
) -> List[str]:
    """Forced cases, then the case that adds the most uncovered cells, until every cell is covered."""
    chosen: Set[str] = {case_id for case_id in forced if case_id in cases}
    cells = {case_id: cells_of(dataset, case) for case_id, case in cases.items() if case.status != NOT_APPLICABLE}
    covered: Set[Cell] = set().union(*(cells.get(case_id, frozenset()) for case_id in chosen)) if chosen else set()
    pending = set().union(*cells.values()) - covered if cells else set()
    while pending:
        best = max(sorted(cells, key=natural_key), key=lambda case_id: len(cells[case_id] & pending))
        gain = cells[best] & pending
        if not gain:
            break
        chosen.add(best)
        pending -= gain
    return sorted(chosen, key=natural_key)


@dataclass(frozen=True)
class Draw:
    """One estimation case with its tier and inverse inclusion probability."""

    case_id: str
    tier: str
    weight: float


def _rank(seed: str, case_id: str) -> str:
    return hashlib.sha256(("%s:%s" % (seed, case_id)).encode("utf-8")).hexdigest()


def estimation_sample(
    population: Sequence[str], tiers: Mapping[str, str], size: int, seed: str
) -> List[Draw]:
    """`size` cases drawn stratified by tier with at least one per tier; weights restore tier shares."""
    if size < 1 or size > len(population):
        raise ValueError("sample size %d is outside 1..%d" % (size, len(population)))
    strata: Dict[str, List[str]] = {}
    for case_id in population:
        strata.setdefault(tiers.get(case_id, UNKNOWN_TIER), []).append(case_id)
    names = sorted(strata)
    quotas = _quotas({name: len(strata[name]) for name in names}, size)
    draws: List[Draw] = []
    for name in names:
        ordered = sorted(strata[name], key=lambda case_id: _rank(seed, case_id))
        weight = len(strata[name]) / quotas[name] if quotas[name] else 0.0
        draws += [Draw(case_id, name, weight) for case_id in ordered[:quotas[name]]]
    return sorted(draws, key=lambda draw: natural_key(draw.case_id))


def _quotas(sizes: Mapping[str, int], total: int) -> Dict[str, int]:
    """Proportional allocation by largest remainder, at least one per non-empty stratum."""
    population = sum(sizes.values())
    quotas = {name: min(size, max(1, total * size // population)) for name, size in sizes.items()}
    remainders = sorted(sizes, key=lambda name: (-(total * sizes[name] % population), name))
    while sum(quotas.values()) < total:
        grown = False
        for name in remainders:
            if sum(quotas.values()) < total and quotas[name] < sizes[name]:
                quotas[name] += 1
                grown = True
        if not grown:
            break
    while sum(quotas.values()) > total:
        biggest = max(sorted(quotas), key=lambda name: quotas[name])
        quotas[biggest] -= 1
    return quotas


def read_tiers(path: Optional[Path]) -> Dict[str, str]:
    """{case_id: tier} from the JSON that `evaluation.confidence` exports; empty when no file is given."""
    if path is None:
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8"))["tiers"])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=CODE_DIR.parent / "dataset")
    parser.add_argument("--pred", type=Path, required=True, help="output.csv of the frozen run")
    parser.add_argument("--diag", type=Path, help="diagnostics.md of that run (hand-crafted family)")
    parser.add_argument("--samples-pred", type=Path, help="sample predictions of that run (P2c sweep)")
    parser.add_argument("--tiers", type=Path, help="tiers JSON exported by evaluation.confidence")
    parser.add_argument("--force", action="append", default=[], metavar="CASE", help="case to force into the coverage set")
    parser.add_argument("--seed", default="", help="seed of the estimation draw (required with --size)")
    parser.add_argument("--size", type=int, default=0, help="estimation sample size (>= %d)" % MIN_ESTIMATION_SIZE)
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        cases = read_output(args.pred)
        tiers = read_tiers(args.tiers)
        diagnostics = args.diag.read_text(encoding="utf-8") if args.diag else None
        samples = read_output(args.samples_pred) if args.samples_pred else None
        forced = forced_cases(dataset, cases, diagnostics, tiers, samples, args.force)
        coverage = coverage_set(dataset, cases, [c for found in forced.values() for c in found])
        result: Dict[str, object] = {"coverage": coverage, "forced": forced}
        if args.size:
            if args.size < MIN_ESTIMATION_SIZE or not args.seed:
                raise ValueError("--size needs at least %d and a --seed" % MIN_ESTIMATION_SIZE)
            population = sorted(cases, key=natural_key)
            result["estimation"] = [draw.__dict__ for draw in estimation_sample(population, tiers, args.size, args.seed)]
    except (OSError, ValueError, KeyError) as error:
        sys.stderr.write("cannot sample: %s\n" % error)
        return 2
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
