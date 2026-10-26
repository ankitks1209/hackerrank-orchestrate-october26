"""Tests for the shipped quality gate `python3 -m evaluation check` and its dispatcher."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from typing import List
from unittest import mock

from evaluation import __main__ as dispatcher
from evaluation import check
from ghostaudit.config import EVAL_REQUEST_COUNT, REPO_ROOT
from tests.dataset_guard import needs_dataset

HEADER = "case_id,deletion_status,steps_json\n"


def write(directory: str, text: str) -> Path:
    path = Path(directory) / "output.csv"
    path.write_bytes(text.encode("utf-8"))
    return path


def rows(count: int) -> str:
    return "".join("case_%d,NOT_APPLICABLE,[]\n" % number for number in range(1, count + 1))


class FormatTests(unittest.TestCase):
    def problems(self, text: str) -> List[str]:
        with tempfile.TemporaryDirectory() as scratch:
            return check.format_problems(write(scratch, text))

    def test_a_well_formed_file_has_no_problem(self) -> None:
        self.assertEqual(self.problems(HEADER + rows(EVAL_REQUEST_COUNT)), [])

    def test_a_wrong_header_is_reported(self) -> None:
        text = "case_id,status,steps\n" + rows(EVAL_REQUEST_COUNT)
        self.assertIn("header is not case_id,deletion_status,steps_json", self.problems(text))

    def test_a_carriage_return_is_reported(self) -> None:
        text = (HEADER + rows(EVAL_REQUEST_COUNT)).replace("\n", "\r\n")
        self.assertIn("carriage return in the file", self.problems(text))

    def test_a_wrong_row_count_is_reported(self) -> None:
        self.assertEqual(self.problems(HEADER + rows(3)), ["3 rows, expected %d" % EVAL_REQUEST_COUNT])


class MainTests(unittest.TestCase):
    def run_main(self, checks=None, error=None, argv=()) -> int:
        patched = mock.patch.object(check, "run_checks", side_effect=error, return_value=checks)
        with patched, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return check.main(list(argv))

    def test_every_check_passing_exits_zero(self) -> None:
        passed = [check.Check("format", True, "ok"), check.Check("contract", True, "ok")]
        self.assertEqual(self.run_main(passed), check.EXIT_OK)

    def test_one_failing_check_exits_one(self) -> None:
        mixed = [check.Check("format", True, "ok"), check.Check("invariants", False, "3 hard failures")]
        self.assertEqual(self.run_main(mixed), check.EXIT_FAILED)

    def test_an_unusable_run_exits_two(self) -> None:
        self.assertEqual(self.run_main(error=RuntimeError("solver exited 2")), check.EXIT_INPUT)

    def test_each_check_is_printed_with_its_verdict(self) -> None:
        mixed = [check.Check("format", True, "ok"), check.Check("invariants", False, "3 hard failures")]
        out = io.StringIO()
        with mock.patch.object(check, "run_checks", return_value=mixed), contextlib.redirect_stdout(out):
            check.main([])
        self.assertIn("format       PASS  ok", out.getvalue())
        self.assertIn("invariants   FAIL  3 hard failures", out.getvalue())

    def test_live_mode_is_not_offered(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check.main(["--llm", "live"])


class DispatcherTests(unittest.TestCase):
    def test_the_commands_are_check_score_verify_and_custom(self) -> None:
        self.assertEqual(sorted(dispatcher.COMMANDS), ["check", "custom", "score", "verify"])

    def test_no_command_or_an_unknown_one_exits_two(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(dispatcher.main([]), dispatcher.EXIT_USAGE)
            self.assertEqual(dispatcher.main(["frobnicate"]), dispatcher.EXIT_USAGE)

    def test_arguments_after_the_command_reach_it(self) -> None:
        seen: List[List[str]] = []
        with mock.patch.dict(dispatcher.COMMANDS, {"check": lambda argv: seen.append(list(argv)) or 0}):
            self.assertEqual(dispatcher.main(["check", "--min-f1", "0.5"]), 0)
        self.assertEqual(seen, [["--min-f1", "0.5"]])


@needs_dataset
class RealRunTests(unittest.TestCase):
    """The gate on the participant files: the whole run is offline and every check passes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.checks = check.run_checks("cache", "on", None, None)

    def test_the_five_checks_run_in_order(self) -> None:
        self.assertEqual([item.name for item in self.checks],
                         ["format", "contract", "determinism", "invariants", "samples"])

    def test_every_check_passes(self) -> None:
        self.assertEqual([item.name for item in self.checks if not item.passed], [])

    def test_the_sample_score_is_compared_with_the_thresholds_given(self) -> None:
        samples = REPO_ROOT / "dataset" / "sample_output.csv"
        perfect = check._sample_check(samples, 1.0, 1.0)
        self.assertTrue(perfect.passed)
        with tempfile.TemporaryDirectory() as scratch:
            empty = Path(scratch) / "samples.csv"
            empty.write_text(HEADER, encoding="utf-8")
            self.assertFalse(check._sample_check(empty, 0.5, None).passed)


if __name__ == "__main__":
    unittest.main()
