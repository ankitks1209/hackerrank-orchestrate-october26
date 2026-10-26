"""Scorer CLI: score predictions against the public gold and print Markdown (SPEC A2).

Run `python3 -m evaluation score [--pred PATH]` from `code/` (or `ghostaudit-eval score`). Without `--pred`
the sample pipeline is run afresh into a temporary directory (never a leftover file), so
the scores always describe the current code. `--ablate` and `--strategies` instead run
the pipeline once per variant, offline, and print the comparison tables of
`evaluation.ablation`; `--agent-ablation` compares the agent off and on.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from evaluation.scoring import (
    FIELD_KEYS,
    GRADERS,
    TAXONOMY,
    Report,
    score,
)
from evaluation import ablation
from evaluation.runner import run_pipeline
from ghostaudit.config import Config
from ghostaudit.dataset import DatasetError, DatasetReader
from ghostaudit.llm.client import LLMError
from ghostaudit.policy import PolicyError
from evaluation.gold import SAMPLE_OUTPUT, GoldReader

LOG = logging.getLogger("ghostaudit.evaluation")
EXIT_OK = 0
EXIT_INPUT = 2
ALIGNMENT_NOTES = (
    "G3/G4: per-case multiset of (phase, system, resource, operation, state[, evidence]); "
    "counts pooled.",
    "G5: steps aligned by (phase, system, resource); fields compared: "
    + ", ".join(FIELD_KEYS) + "; unaligned steps miss every field.",
    "G6: pooled LCS length / pooled longer sequence length on order keys (evidence ignored).",
    "G8: steps aligned by step_no; phase, system, resource, operation, state, evidence compared.",
    "Taxonomy: missing/extra/wrong_* count steps, status/order count cases; account_service "
    "misses are identity_miss; structural cases bucket all their errors.",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pred", type=Path,
                        help="predictions CSV (default: run the sample pipeline into a temp dir)")
    parser.add_argument("--gold", type=Path, help="gold CSV (default: dataset/sample_output.csv)")
    parser.add_argument("--structural", default="",
                        help="comma-separated case ids whose errors count as structural")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--ablate", action="store_true",
                        help="run every flag variant offline; print the table and ledger")
    parser.add_argument("--strategies", action="store_true",
                        help="compare the LLM strategies S0, S1 and S2 offline (cache replay only)")
    parser.add_argument("--agent-ablation", action="store_true",
                        help="compare the agent off and on offline (cache replay only)")
    parser.add_argument("--verbose", action="store_true")
    return parser


def render(report: Report) -> str:
    """Markdown tables for one report."""
    lines = ["## Grader emulation (%d cases)" % report.cases, "",
             "| Grader | Name | Score | Ceiling | Normalized |", "|---|---|---|---|---|"]
    for grader, name in GRADERS:
        lines.append("| %s | %s | %.4f | %.3f | %.4f |" % (
            grader, name, report.raw[grader], report.ceilings[grader], report.normalized[grader]))
    lines += ["", "## Details", "", "| Metric | Value |", "|---|---|"]
    lines += ["| %s | %.4f |" % (name, value) for name, value in report.details.items()]
    lines += ["", "## Error taxonomy", "", "| Category | Count |", "|---|---|"]
    lines += ["| %s | %d |" % (name, report.taxonomy[name]) for name in TAXONOMY]
    lines += ["", "## Mismatches", "",
              "- Status mismatches: %s" % (", ".join(report.status_mismatches) or "none"),
              "- Not row-exact: %s" % (", ".join(report.inexact_cases) or "none"),
              "", "## Alignment definitions", ""]
    lines += ["- " + note for note in ALIGNMENT_NOTES]
    return "\n".join(lines) + "\n"


def run_comparisons(args: argparse.Namespace) -> str:
    """Markdown of the requested strategy comparison and ablation table."""
    base = Config()
    reader = DatasetReader(base.dataset_dir)
    reader.check_complete()
    gold = GoldReader(args.gold or SAMPLE_OUTPUT).cases()
    sections = []
    if args.strategies:
        sections.append(ablation.render_strategies(
            ablation.run_variants(ablation.strategy_variants(base), reader, gold)))
    if args.ablate:
        sections.append(ablation.render_ablation(
            ablation.run_variants(ablation.ablation_variants(base), reader, gold)))
    if args.agent_ablation:
        sections.append(ablation.render_agent(
            ablation.run_variants(ablation.agent_variants(base), reader, gold)))
    return "\n".join(sections)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.ablate or args.strategies or args.agent_ablation:
        logging.getLogger("ghostaudit").setLevel(logging.ERROR)
        try:
            sys.stdout.write(run_comparisons(args))
        except (OSError, DatasetError, PolicyError, LLMError,
                ValueError, KeyError) as error:
            LOG.error("cannot compare: %s", error)
            return EXIT_INPUT
        return EXIT_OK
    try:
        gold = GoldReader(args.gold or SAMPLE_OUTPUT).cases()
        with tempfile.TemporaryDirectory() as scratch:
            pred_path = args.pred or run_pipeline(Path(scratch))[1]
            if not pred_path.exists():
                LOG.error("predictions file not found: %s", pred_path)
                return EXIT_INPUT
            pred = GoldReader(pred_path).cases()
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        LOG.error("cannot score: %s", error)
        return EXIT_INPUT
    structural = frozenset(part for part in args.structural.split(",") if part)
    report = score(gold, pred, structural=structural)
    if args.json:
        sys.stdout.write(json.dumps(dataclasses.asdict(report), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render(report))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
