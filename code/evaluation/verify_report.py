"""Label-free verification report and CLI (checks P2a-d and P5).

Runs the locator check, the recall sweep, the coverage sweep, the redundancy matrix and the
invariants over one run and prints Markdown for the evaluation report and the release
gate. Exit code 0 when no hard failure exists, 1 when one does, 2 on unusable input.

    python3 -m evaluation verify                      # from code/: runs the pipeline into a temp dir
    python3 -m evaluation verify --pred output.csv --samples-pred samples.csv --diag diagnostics.md

Nothing here reads `sample_output.csv`: the sample predictions are the solver's own output.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from evaluation import invariants, redundancy, verify_steps
from evaluation.raw_dataset import RawDataset, load_dataset
from evaluation.runner import run_pipeline

EXIT_OK = 0
EXIT_HARD_FAILURE = 1
EXIT_INPUT = 2
REPO_ROOT = Path(__file__).resolve().parents[2]  # code/evaluation/verify_report.py -> repository root
DATASET_DIR = REPO_ROOT / "dataset"
SHOWN = 12  # failures listed inline per section


@dataclass(frozen=True)
class Report:
    """Everything one verification run found."""

    locator: List[verify_steps.Finding]
    recall: List[verify_steps.Finding]
    coverage: List[verify_steps.Finding]
    matrix: List[redundancy.Row]
    single_signal: tuple
    checks: List[invariants.Check]
    distributions: Mapping[str, object]

    @property
    def hard_failures(self) -> int:
        failed = sum(1 for item in self.locator if item.code == verify_steps.FAILED)
        unexplained = sum(1 for item in self.recall + self.coverage if item.code == verify_steps.UNEXPLAINED)
        return failed + unexplained + len(invariants.failed_hard(self.checks))


def verify(
    dataset: RawDataset, cases: Mapping[str, verify_steps.Case],
    samples: Mapping[str, verify_steps.Case], diagnostics: redundancy.Diagnostics,
) -> Report:
    """Run every label-free check on one run's evaluation cases."""
    locator = verify_steps.locator_check(dataset, cases)
    cited = [item for item in locator if item.code != verify_steps.SOURCE_ROW]
    agree = sum(1 for item in cited if item.code != verify_steps.FAILED)
    steps = {case_id: [step.resource_id for step in case.steps] for case_id, case in cases.items()}
    return Report(
        locator=locator,
        recall=verify_steps.recall_sweep(dataset, cases),
        coverage=verify_steps.coverage_sweep(dataset, cases, samples),
        matrix=redundancy.matrix(diagnostics, agree, len(cited)),
        single_signal=redundancy.single_signal_fraction(diagnostics, steps),
        checks=invariants.run_checks(dataset, cases, diagnostics.unread_media),
        distributions=invariants.distributions(dataset, cases),
    )


def _listing(items: Sequence[verify_steps.Finding], code: str) -> List[str]:
    chosen = [item for item in items if item.code == code]
    lines = ["  - %s %s %s" % (item.case_id, item.resource_id, item.detail) for item in chosen[:SHOWN]]
    return lines + (["  - ... (%d more)" % (len(chosen) - SHOWN)] if len(chosen) > SHOWN else [])


def _counts(items: Sequence[verify_steps.Finding]) -> str:
    return ", ".join("%s=%d" % pair for pair in sorted(Counter(item.code for item in items).items())) or "none"


def _distinct(items: Sequence[verify_steps.Finding]) -> str:
    ids = {}
    for item in items:
        ids.setdefault(item.code, set()).add(item.resource_id)
    return ", ".join("%s=%d" % (code, len(found)) for code, found in sorted(ids.items())) or "none"


def render(report: Report) -> str:
    """The report as Markdown."""
    lines = ["# Label-free verification", ""]
    lines += ["## P2a locator verification (precision)", "",
              "- Cited steps checked: %d (%s)" % (len(report.locator), _counts(report.locator)),
              "- Failures: %d" % sum(1 for i in report.locator if i.code == verify_steps.FAILED)]
    lines += _listing(report.locator, verify_steps.FAILED)
    lines += ["", "`unkeyed` means the state was confirmed but the unit names no subject key, so ownership "
              "rests on timing signals (see P2d); `media` steps cite an image or PDF and cannot be re-read as text.", ""]
    for title, items in (("P2b recall sweep", report.recall), ("P2c proof-file coverage", report.coverage)):
        lines += ["## %s" % title, "", "- Items: %d (%s)" % (len(items), _counts(items)),
                  "- Distinct resource ids by code: %s" % _distinct(items),
                  "- Unexplained: %d" % sum(1 for i in items if i.code == verify_steps.UNEXPLAINED)]
        lines += _listing(items, verify_steps.UNEXPLAINED)
        lines.append("")
    timing, total = report.single_signal
    lines += ["## P2d redundancy matrix", "", "| Component | Alternative signal | Comparable | Agree | Rate |",
              "|---|---|---|---|---|"]
    lines += ["| %s | %s | %d | %d | %.4f |" % (r.component, r.alternative, r.comparable, r.agree, r.rate)
              for r in report.matrix]
    lines += ["", "Single-signal steps (link rests on timing alone): %d of %d (%.1f %%)" % (
        timing, total, 100.0 * timing / total if total else 0.0), ""]
    lines += ["## P5 invariants", "", "| Check | Severity | Failures |", "|---|---|---|"]
    lines += ["| %s | %s | %d |" % (c.name, c.severity, len(c.failures)) for c in report.checks]
    for check in report.checks:
        if check.failures:
            lines += ["", "**%s** (%s). %s" % (check.name, check.severity, check.note)]
            lines += ["  - " + text for text in check.failures[:SHOWN]]
            if len(check.failures) > SHOWN:
                lines.append("  - ... (%d more)" % (len(check.failures) - SHOWN))
    lines += ["", "## Distributions", "", "```", json.dumps(
        {"confusion": {"%s -> %s" % key: n for key, n in report.distributions["confusion"].items()},
         "steps": report.distributions["steps"]}, indent=2, sort_keys=True), "```", "",
        "Hard failures: %d" % report.hard_failures, ""]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--pred", type=Path, help="evaluation output.csv (default: run the pipeline)")
    parser.add_argument("--samples-pred", type=Path, help="sample predictions CSV")
    parser.add_argument("--diag", type=Path, help="diagnostics.md of the run that wrote --pred")
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            paths = (args.pred, args.samples_pred, args.diag)
            pred, samples_pred, diag = paths if all(paths) else run_pipeline(Path(scratch))
            report = verify(load_dataset(args.dataset), verify_steps.read_output(pred),
                            verify_steps.read_output(samples_pred), redundancy.read_diagnostics(diag))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.stderr.write("cannot verify: %s\n" % error)
        return EXIT_INPUT
    sys.stdout.write(render(report))
    return EXIT_OK if report.hard_failures == 0 else EXIT_HARD_FAILURE


if __name__ == "__main__":
    sys.exit(main())
