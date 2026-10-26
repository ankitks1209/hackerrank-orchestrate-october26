"""Confidence tiers, fragility and the rule provenance ledger (T40; LOCAL_EVALUATION_STRATEGY P4, P6).

Shows where the remaining risk is and routes it to the audit:

* tier per evaluation case. Low: the answer rests on a first-in-first-out pairing, a link the agent
  decided, a hand-crafted or image link, a missing account step or no audit-record step. Medium: some
  resource is linked by process-order uniqueness or elimination. High: everything else,
  including the requests that are not deletions;
* fragility: the cases whose row changes under any ablation variant of `evaluation.ablation`;
* ledger: for every switch in `Flags`, how many public-sample cases it keeps
  exact (support) and how many evaluation rows it changes (exposure). The class follows the support:
  `evidenced` (two or more sample cases), `weak` (one), `inferred` (none).

    python3 devtools/confidence.py [--export tiers.json] [--ledger] [--check]

`--export` writes the JSON that `devtools/audit/sampler.py` reads; `--ledger` prints the table kept
in `code/docs/DECISIONS.md`; `--check` exits 1 when that table has drifted from a fresh run. Every
variant runs in the default `--llm cache` mode (stored model responses, no network), so the figures
describe the run that produced `output.csv`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:  # devtools run from the repository root, outside the solver package
    sys.path.insert(0, str(CODE_DIR))

from evaluation import ablation  # noqa: E402
from ghostaudit.config import Config  # noqa: E402
from ghostaudit.dataset import DatasetReader  # noqa: E402
from ghostaudit.diagnostics import (  # noqa: E402
    ASSUMPTION_FIFO_ACCOUNT,
    ASSUMPTION_FIFO_ROWS,
    ASSUMPTION_AGENT,
    case_assumptions,
)
from ghostaudit.handcrafted import BASIS_CATALOG_LINK, BASIS_TARGET_ROW  # noqa: E402
from ghostaudit.link_graph import ROW_COUPLING, ROW_ELIMINATION, ROW_NEVER_MIX, ROW_UNIQUE  # noqa: E402
from ghostaudit.pipeline import CaseRecord, RunResult  # noqa: E402
from evaluation.gold import GoldReader  # noqa: E402

HIGH, MEDIUM, LOW = "high", "medium", "low"
SECURITY_SERVICE = "security_service"
ACCOUNT_SERVICE = "account_service"
MEDIA_SUFFIXES = (".png", ".pdf")
TIMING_BASES = frozenset({ROW_UNIQUE, ROW_ELIMINATION, ROW_COUPLING, ROW_NEVER_MIX})
IMAGE_BASES = frozenset({BASIS_CATALOG_LINK, BASIS_TARGET_ROW})
EVIDENCED_MIN_SUPPORT = 2
LEDGER_BEGIN = "<!-- BEGIN:ledger -->"
LEDGER_END = "<!-- END:ledger -->"
DECISIONS_PATH = CODE_DIR / "docs" / "DECISIONS.md"
EVIDENCED, WEAK, INFERRED = "evidenced", "weak", "inferred"


@dataclass(frozen=True)
class CaseConfidence:
    case_id: str
    tier: str
    reasons: Tuple[str, ...]


def _cites_media(case: CaseRecord, result: RunResult) -> bool:
    entries = result.index.entries
    return any(step.evidence_id in entries and entries[step.evidence_id].path.suffix.lower() in MEDIA_SUFFIXES
               for step in case.result.steps)


def classify_case(case: CaseRecord, result: RunResult) -> CaseConfidence:
    """Tier and reasons of one evaluation case."""
    if not case.decision.deletion:
        return CaseConfidence(case.request.case_id, HIGH, ())
    low: List[str] = []
    bases = {resource.basis for resource in case.links.resources} | {verdict.basis for verdict in case.verdicts}
    assumed = case_assumptions(case)
    if ASSUMPTION_FIFO_ACCOUNT in assumed or ASSUMPTION_FIFO_ROWS in assumed:
        low.append("fifo pairing")
    if ASSUMPTION_AGENT in assumed:
        low.append("agent decision")
    if bases & IMAGE_BASES or _cites_media(case, result):
        low.append("image or hand-crafted link")
    systems = {step.system_id for step in case.result.steps}
    if ACCOUNT_SERVICE not in systems:
        low.append("account step omitted")
    if SECURITY_SERVICE not in systems:
        low.append("no audit-record step")
    if low:
        return CaseConfidence(case.request.case_id, LOW, tuple(low))
    if bases & TIMING_BASES:
        return CaseConfidence(case.request.case_id, MEDIUM, ("link rests on timing",))
    return CaseConfidence(case.request.case_id, HIGH, ())


def tiers(result: RunResult) -> List[CaseConfidence]:
    """Tier of every evaluation case, in case order."""
    return [classify_case(case, result) for case in result.cases if not case.request.is_sample]


def fragility(outcomes: Sequence[ablation.Outcome]) -> Dict[str, Tuple[str, ...]]:
    """Case id -> the ablation variants that change its row (the first outcome is the default)."""
    reference, found = outcomes[0], {}
    for outcome in outcomes[1:]:
        for case_id, row in outcome.eval_rows.items():
            if reference.eval_rows.get(case_id) != row:
                found.setdefault(case_id, []).append(outcome.variant.name)
    return {case_id: tuple(names) for case_id, names in sorted(found.items())}


@dataclass(frozen=True)
class LedgerEntry:
    flag: str
    default: str
    support: int  # public-sample cases that stop being row-exact when the flag is flipped
    regained: int  # public-sample cases that become row-exact when it is flipped
    exposure: str  # evaluation rows changed when flipped, per setting
    fired: str

    @property
    def rule_class(self) -> str:
        if self.support >= EVIDENCED_MIN_SUPPORT:
            return EVIDENCED
        return WEAK if self.support == 1 else INFERRED


def ledger(outcomes: Sequence[ablation.Outcome]) -> List[LedgerEntry]:
    """One entry per switch and for the window sweep, from the default run and its variants."""
    reference = outcomes[0]
    base = set(reference.report.inexact_cases)
    entries = []
    for row in ablation.assumption_ledger(outcomes):
        varied = [o for o in outcomes if o.variant.flag == row.flag]
        worse = {case for o in varied for case in set(o.report.inexact_cases) - base}
        better = {case for o in varied for case in base - set(o.report.inexact_cases)}
        entries.append(LedgerEntry(row.flag, row.default, len(worse), len(better), row.changed, row.fired))
    return entries


def render_ledger(entries: Sequence[LedgerEntry]) -> str:
    lines = ["| Flag | Default | Class | Sample cases it keeps exact | Sample cases it breaks | Eval rows changed when flipped | Relied on |",
             "|---|---|---|---|---|---|---|"]
    lines += ["| `%s` | %s | %s | %d | %d | %s | %s |" % (
        e.flag, e.default, e.rule_class, e.support, e.regained, e.exposure, e.fired) for e in entries]
    return "\n".join(lines)


def render(result_tiers: Sequence[CaseConfidence], fragile: Mapping[str, Tuple[str, ...]]) -> str:
    counts = Counter(item.tier for item in result_tiers)
    reasons = Counter(reason for item in result_tiers for reason in item.reasons)
    lines = ["## Confidence tiers", "", "| Tier | Cases |", "|---|---|"]
    lines += ["| %s | %d |" % (tier, counts[tier]) for tier in (HIGH, MEDIUM, LOW)]
    lines += ["", "Reasons (a case can have several): " +
              (", ".join("%s=%d" % pair for pair in sorted(reasons.items())) or "none"), "",
              "## Fragility", "",
              "Cases whose row changes under at least one flag variant: %d" % len(fragile),
              ""]
    return "\n".join(lines)


def export(
    result_tiers: Sequence[CaseConfidence], fragile: Mapping[str, Tuple[str, ...]], path: Path
) -> None:
    """Write the JSON the audit sampler reads."""
    document = {"tiers": {item.case_id: item.tier for item in result_tiers},
                "reasons": {item.case_id: list(item.reasons) for item in result_tiers if item.reasons},
                "fragile": {case_id: list(names) for case_id, names in fragile.items()}}
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def block_of(text: str) -> Optional[str]:
    """The ledger table kept between the markers of DECISIONS.md, or None."""
    if LEDGER_BEGIN not in text or LEDGER_END not in text:
        return None
    return text.split(LEDGER_BEGIN, 1)[1].split(LEDGER_END, 1)[0].strip()


def run_outcomes(config: Config) -> List[ablation.Outcome]:
    reader = DatasetReader(config.dataset_dir)
    reader.check_complete()
    package_logger = logging.getLogger("ghostaudit")
    previous = package_logger.level
    package_logger.setLevel(logging.CRITICAL)
    try:
        return ablation.run_variants(ablation.ablation_variants(config), reader, GoldReader().cases())
    finally:
        package_logger.setLevel(previous)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", type=Path, help="write tiers and fragile cases as JSON")
    parser.add_argument("--ledger", action="store_true", help="print the provenance ledger table")
    parser.add_argument("--check", action="store_true", help="exit 1 when DECISIONS.md holds a stale ledger")
    args = parser.parse_args(argv)
    try:
        outcomes = run_outcomes(Config())
    except (OSError, ValueError, KeyError) as error:
        sys.stderr.write("cannot assess: %s\n" % error)
        return 2
    table = render_ledger(ledger(outcomes))
    if args.check:
        kept = block_of(DECISIONS_PATH.read_text(encoding="utf-8"))
        if kept != table:
            sys.stderr.write("the ledger in %s is %s\n" % (DECISIONS_PATH.name, "missing" if kept is None else "stale"))
            return 1
        return 0
    found, fragile = tiers(outcomes[0].result), fragility(outcomes)
    if args.export:
        export(found, fragile, args.export)
    sys.stdout.write(table + "\n" if args.ledger else render(found, fragile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
