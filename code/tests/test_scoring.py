"""Tests for evaluation.scoring and evaluation.main (SPEC A2).

Perturbation tests use synthetic cases and assert exactly which graders move.
The gold self-score test reads the public samples through tests.gold.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple
from unittest import mock

from evaluation import main as scorer_cli
from evaluation import runner
from evaluation import scoring
from ghostaudit.emit import OUTPUT_COLUMNS, serialize
from ghostaudit.model import CaseResult, Step
from evaluation.gold import SAMPLE_OUTPUT, GoldReader

ALL_GRADERS = {grader for grader, _ in scoring.GRADERS}
EPSILON = 1e-12

Spec = Tuple[str, str, str, str, str, str]  # phase, system, resource, operation, state, evidence

FINDING = ("FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
REMEDIATE = ("REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT", "")
VERIFY_ROW = ("VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT", "ABSENT", "")
VERIFY_ACCOUNT = ("VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "")
COMPLETE_ACCOUNT = ("VERIFICATION", "account_service", "account_2", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_02")
COMPLETE_ROW = ("VERIFICATION", "search_service", "search_2", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_03")


def case(case_id: str, status: str, specs: Sequence[Spec]) -> CaseResult:
    return CaseResult(case_id, status, tuple(Step(number, *spec) for number, spec in enumerate(specs, 1)))


def gold_cases() -> Dict[str, CaseResult]:
    cases = [
        case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ROW, VERIFY_ACCOUNT]),
        case("case_2", "COMPLETE", [COMPLETE_ACCOUNT, COMPLETE_ROW]),
        case("case_3", "NOT_APPLICABLE", []),
    ]
    return {c.case_id: c for c in cases}


def perturbed(case_id: str, replacement: CaseResult) -> Dict[str, CaseResult]:
    pred = gold_cases()
    pred[case_id] = replacement
    return pred


def moved(pred: Dict[str, CaseResult]) -> Set[str]:
    report = scoring.score(gold_cases(), pred)
    return {g for g in ALL_GRADERS if abs(report.raw[g] - 1.0) > EPSILON}


class SelfScoreTests(unittest.TestCase):
    def test_synthetic_gold_scores_one_everywhere(self) -> None:
        report = scoring.score(gold_cases(), gold_cases())
        for grader in ALL_GRADERS:
            self.assertEqual(report.raw[grader], 1.0, grader)
            self.assertEqual(report.normalized[grader], 1.0, grader)
        self.assertEqual(report.inexact_cases, ())
        self.assertEqual(sum(report.taxonomy.values()), 0)

    @unittest.skipUnless(SAMPLE_OUTPUT.exists(), "dataset/sample_output.csv not available")
    def test_public_gold_scores_one_everywhere(self) -> None:
        gold = GoldReader().cases()
        report = scoring.score(gold, gold)
        self.assertEqual(report.cases, 32)
        for value in list(report.raw.values()) + list(report.details.values()):
            self.assertEqual(value, 1.0)
        self.assertEqual(sum(report.taxonomy.values()), 0)


class PerturbationTests(unittest.TestCase):
    def test_swap_moves_only_order_graders(self) -> None:
        swapped = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ACCOUNT, VERIFY_ROW])
        self.assertEqual(moved(perturbed("case_1", swapped)), {"G2", "G6", "G7", "G8"})

    def test_swap_sequence_numbers(self) -> None:
        swapped = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ACCOUNT, VERIFY_ROW])
        report = scoring.score(gold_cases(), perturbed("case_1", swapped))
        self.assertAlmostEqual(report.raw["G6"], 5 / 6)
        self.assertAlmostEqual(report.details["exact_order"], 2 / 3)
        self.assertEqual(report.taxonomy["order"], 1)

    def test_drop_moves_everything_except_status(self) -> None:
        dropped = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ROW])
        self.assertEqual(moved(perturbed("case_1", dropped)), ALL_GRADERS - {"G1"})

    def test_extra_step_moves_everything_except_status(self) -> None:
        extra = ("VERIFICATION", "search_service", "search_9", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        padded = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ROW, VERIFY_ACCOUNT, extra])
        self.assertEqual(moved(perturbed("case_1", padded)), ALL_GRADERS - {"G1"})
        report = scoring.score(gold_cases(), perturbed("case_1", padded))
        self.assertEqual(report.taxonomy["extra"], 1)
        self.assertLess(report.raw["G3"], 1.0)
        self.assertEqual(report.raw["G1"], 1.0)
        self.assertEqual(report.details["recall"], 1.0)

    def test_wrong_evidence_moves_only_evidence_sensitive_graders(self) -> None:
        wrong = FINDING[:5] + ("evidence_99",)
        replaced = case("case_1", "INCOMPLETE", [wrong, REMEDIATE, VERIFY_ROW, VERIFY_ACCOUNT])
        pred = perturbed("case_1", replaced)
        self.assertEqual(moved(pred), {"G2", "G3", "G5", "G7", "G8"})
        self.assertEqual(scoring.score(gold_cases(), pred).taxonomy["wrong_evidence"], 1)

    def test_wrong_operation_moves_everything_except_status(self) -> None:
        wrong = REMEDIATE[:3] + ("REDACT_RECORD", "REDACTED", "")
        replaced = case("case_1", "INCOMPLETE", [FINDING, wrong, VERIFY_ROW, VERIFY_ACCOUNT])
        pred = perturbed("case_1", replaced)
        self.assertEqual(moved(pred), ALL_GRADERS - {"G1"})
        self.assertEqual(scoring.score(gold_cases(), pred).taxonomy["wrong_op_state"], 1)

    def test_wrong_status_moves_status_graders_only(self) -> None:
        flipped = case("case_2", "INCOMPLETE", [COMPLETE_ACCOUNT, COMPLETE_ROW])
        pred = perturbed("case_2", flipped)
        self.assertEqual(moved(pred), {"G1", "G2", "G7"})
        report = scoring.score(gold_cases(), pred)
        self.assertEqual(report.status_mismatches, ("case_2",))
        self.assertEqual(report.taxonomy["status"], 1)

    def test_missing_prediction_scores_as_empty_answer(self) -> None:
        pred = gold_cases()
        del pred["case_1"]
        report = scoring.score(gold_cases(), pred)
        self.assertEqual(report.raw["G1"], 2 / 3)
        self.assertEqual(report.taxonomy["identity_miss"], 1)
        self.assertEqual(report.taxonomy["missing"], 3)

    def test_missing_account_step_is_identity_miss(self) -> None:
        dropped = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ROW])
        taxonomy = scoring.score(gold_cases(), perturbed("case_1", dropped)).taxonomy
        self.assertEqual((taxonomy["identity_miss"], taxonomy["missing"]), (1, 0))

    def test_structural_cases_bucket_their_errors(self) -> None:
        dropped = case("case_1", "INCOMPLETE", [FINDING, REMEDIATE, VERIFY_ROW])
        report = scoring.score(gold_cases(), perturbed("case_1", dropped), structural={"case_1"})
        self.assertEqual(report.taxonomy["structural"], 1)
        self.assertEqual(report.taxonomy["identity_miss"], 0)


class CeilingAndCompareTests(unittest.TestCase):
    def test_normalization_divides_by_ceiling(self) -> None:
        flipped = case("case_2", "INCOMPLETE", [COMPLETE_ACCOUNT, COMPLETE_ROW])
        pred = perturbed("case_2", flipped)
        report = scoring.score(gold_cases(), pred, ceilings={"G2": 0.8})
        self.assertAlmostEqual(report.normalized["G2"], report.raw["G2"] / 0.8)
        self.assertEqual(report.normalized["G1"], report.raw["G1"])

    def test_compare_flags_regression_beyond_tolerance(self) -> None:
        prev = {grader: 0.9 for grader in ALL_GRADERS}
        cur = dict(prev, G3=0.8, G5=0.95, G1=0.8999)
        verdict = scoring.compare(prev, cur, tolerance=0.01)
        self.assertEqual(verdict.regressions, ("G3",))
        self.assertEqual(verdict.improvements, ("G5",))
        self.assertFalse(verdict.ok)

    def test_compare_accepts_equal_and_improving(self) -> None:
        prev = {grader: 0.9 for grader in ALL_GRADERS}
        verdict = scoring.compare(prev, dict(prev, G2=0.95))
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.regressions, ())


def write_csv(path: Path, cases: Dict[str, CaseResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(OUTPUT_COLUMNS)
        for result in cases.values():
            writer.writerow((result.case_id, result.deletion_status, serialize(result.steps)))


def run_cli(argv: List[str]) -> Tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = scorer_cli.main(argv)
    return code, buffer.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.gold = self.root / "gold.csv"
        write_csv(self.gold, gold_cases())

    def test_help_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            scorer_cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_markdown_report_for_explicit_pred(self) -> None:
        code, output = run_cli(["--gold", str(self.gold), "--pred", str(self.gold)])
        self.assertEqual(code, scorer_cli.EXIT_OK)
        self.assertIn("| G8 | step_no-aligned positional accuracy | 1.0000", output)
        self.assertIn("## Error taxonomy", output)
        self.assertIn("## Alignment definitions", output)

    def test_json_report(self) -> None:
        code, output = run_cli(["--gold", str(self.gold), "--pred", str(self.gold), "--json"])
        self.assertEqual(code, scorer_cli.EXIT_OK)
        self.assertEqual(json.loads(output)["raw"]["G2"], 1.0)

    def test_ceilings_are_one_without_an_option(self) -> None:
        _, output = run_cli(["--gold", str(self.gold), "--pred", str(self.gold), "--json"])
        self.assertEqual(set(json.loads(output)["ceilings"].values()), {1.0})
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                run_cli(["--gold", str(self.gold), "--pred", str(self.gold), "--ceilings", "eval"])

    def test_missing_explicit_pred_is_an_input_error(self) -> None:
        with self.assertLogs("ghostaudit.evaluation", level="ERROR"):
            code, _ = run_cli(["--gold", str(self.gold), "--pred", str(self.root / "absent.csv")])
        self.assertEqual(code, scorer_cli.EXIT_INPUT)

    def test_malformed_pred_is_an_input_error(self) -> None:
        bad = self.root / "bad.csv"
        bad.write_text("case_id,deletion_status,steps_json\ncase_1,COMPLETE,not-json\n", encoding="utf-8")
        with self.assertLogs("ghostaudit.evaluation", level="ERROR"):
            code, _ = run_cli(["--gold", str(self.gold), "--pred", str(bad)])
        self.assertEqual(code, scorer_cli.EXIT_INPUT)

    def test_default_pred_runs_a_fresh_sample_pipeline(self) -> None:
        def fake_pipeline(scratch: Path) -> tuple:
            samples = scratch / "samples.csv"
            write_csv(samples, gold_cases())
            return scratch / "output.csv", samples, scratch / "diag" / "diagnostics.md"

        with mock.patch.object(scorer_cli, "run_pipeline", side_effect=fake_pipeline) as run:
            code, output = run_cli(["--gold", str(self.gold)])
        run.assert_called_once()
        self.assertEqual(code, scorer_cli.EXIT_OK)
        self.assertIn("| G2 | case exact (row-level) | 1.0000", output)

    def test_pipeline_command_uses_temp_output(self) -> None:
        with mock.patch.object(runner.subprocess, "run") as run:
            _, samples, _ = runner.run_pipeline(self.root)
        command = run.call_args[0][0]
        self.assertIn("--include-samples", command)
        self.assertEqual(command[command.index("--samples-out") + 1], str(samples))
        self.assertEqual(Path(command[command.index("--out") + 1]).parent, self.root)
        self.assertNotIn(str(runner.CODE_DIR.parent / "output.csv"), command)
        self.assertNotIn("--llm", command)


if __name__ == "__main__":
    unittest.main()
