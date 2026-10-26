"""Golden sample regression gate (SPEC A2).

Runs the whole pipeline over the 32 public samples through the real CLI (replaying the
committed LLM cache, never calling a model) and scores the answers against the public
gold. Every invocation writes only under a fresh temporary directory.

The links come from process order and evidence ownership only; contested rows and accounts are
decided by the agent when its responses are cached and by the deterministic fallback otherwise.
The gate therefore pins a measured floor for the fallback (`--agent off`) and requires the
agent run never to score below it. A later run that fills the agent cache may raise the floor.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from evaluation.scoring import Report, score
from ghostaudit.config import REPO_ROOT
from ghostaudit.model import CaseResult
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

MAIN = REPO_ROOT / "code" / "main.py"
PREDICTIONS_NAME = "sample_predictions.csv"
DIAGNOSTICS_NAME = "diagnostics.md"
SKIPPED_MEDIA_MARKER = ": skipped"
SAMPLE_CASES = 32
# Measured with `--llm cache --agent off` (the fallback links): 31 of 32 statuses, 6 of 32 rows exact,
# step F1 0.8471. They are floors for regression, not targets.
FALLBACK_STATUS_FLOOR = 31
FALLBACK_EXACT_FLOOR = 6
FALLBACK_F1_FLOOR = 0.84
F1_TOLERANCE = 1e-9


class Run:
    """One pipeline run over the samples: predictions, report and media completeness."""

    def __init__(self, agent: str) -> None:
        self.agent = agent
        with tempfile.TemporaryDirectory() as scratch:
            self.diag = Path(scratch) / "diag"
            self.stderr = self._run(Path(scratch), agent)
            self.predictions = GoldReader(self.diag / PREDICTIONS_NAME).cases()
            diagnostics = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        self.media_complete = SKIPPED_MEDIA_MARKER not in diagnostics
        self.gold = GoldReader().cases()
        self.report: Report = score(self.gold, self.predictions)

    def _run(self, scratch: Path, agent: str) -> str:
        command = [sys.executable, str(MAIN), "--llm", "cache", "--include-samples",
                   "--agent", agent,
                   "--out", str(scratch / "output.csv"), "--diag", str(self.diag)]
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
        if done.returncode != 0:
            raise AssertionError("main.py exited %d: %s" % (done.returncode, done.stderr[-2000:]))
        return done.stderr

    @property
    def exact(self) -> int:
        return self.report.cases - len(self.report.inexact_cases)

    @property
    def status_ok(self) -> int:
        return self.report.cases - len(self.report.status_mismatches)

    def summary(self) -> str:
        return ("agent=%s status %d/%d exact %d/%d inexact=%s media_complete=%s "
                "G3=%.4f G5=%.4f G6=%.4f G7=%.4f" % (
                    self.agent, self.status_ok, self.report.cases, self.exact,
                    self.report.cases, ",".join(self.report.inexact_cases) or "none",
                    self.media_complete, self.report.raw["G3"], self.report.raw["G5"],
                    self.report.raw["G6"], self.report.raw["G7"]))

    def diff(self, case_ids: Tuple[str, ...]) -> str:
        """Gold-only and prediction-only steps of the named cases."""
        lines: List[str] = []
        for case_id in case_ids:
            gold, pred = self.gold[case_id], self.predictions.get(case_id)
            lines.append("%s: gold %s, predicted %s" % (
                case_id, gold.deletion_status, pred.deletion_status if pred else "missing"))
            lines += _step_diff(gold, pred)
        return "\n".join(lines)


def _step_diff(gold: CaseResult, pred: Optional[CaseResult]) -> List[str]:
    gold_steps = set(gold.steps)
    pred_steps = set(pred.steps if pred else ())
    lines = ["  gold only: %s" % (step,) for step in gold.steps if step not in pred_steps]
    if pred:
        lines += ["  pred only: %s" % (step,) for step in pred.steps if step not in gold_steps]
    return lines


_RUNS: Dict[str, Run] = {}


def run_once(agent: str) -> Run:
    """The run with the agent `agent`, executed once per test process."""
    if agent not in _RUNS:
        _RUNS[agent] = Run(agent)
    return _RUNS[agent]


@needs_dataset
class GoldenGateTests(unittest.TestCase):
    def test_the_fallback_links_never_regress_below_the_measured_floor(self) -> None:
        run = run_once("off")
        print("\n[golden] " + run.summary(), file=sys.stderr)
        self.assertEqual(run.report.cases, SAMPLE_CASES)
        self.assertGreaterEqual(run.status_ok, FALLBACK_STATUS_FLOOR, run.diff(run.report.status_mismatches))
        self.assertGreaterEqual(run.exact, FALLBACK_EXACT_FLOOR)
        self.assertGreaterEqual(run.report.raw["G3"], FALLBACK_F1_FLOOR)

    def test_the_agent_run_never_scores_below_the_fallback(self) -> None:
        """With no cached agent response every unit falls back, so the two runs agree; with a filled cache
        the agent may only improve on the floor."""
        fallback, agent = run_once("off"), run_once("on")
        print("\n[golden] " + agent.summary(), file=sys.stderr)
        self.assertGreaterEqual(agent.status_ok, fallback.status_ok)
        self.assertGreaterEqual(agent.exact, fallback.exact)
        self.assertGreaterEqual(agent.report.raw["G3"] + F1_TOLERANCE, fallback.report.raw["G3"])


if __name__ == "__main__":
    unittest.main()
