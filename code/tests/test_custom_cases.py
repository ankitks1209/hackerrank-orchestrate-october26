"""Tests for evaluation.custom_cases (AGENTS 6.8 custom cases; SPEC I1-I4, T1-T5, 6, 8, 9).

Every case builds its own mini dataset in a temporary directory, so the tests run offline and
never touch the submission `output.csv`.
"""
from __future__ import annotations

import contextlib
import csv
import dataclasses
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Dict

from evaluation import custom_cases as cc
from ghostaudit.config import Config
from tests.dataset_guard import needs_dataset

CASE_IDS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
ROW_KEYS = {"id", "title", "rationale", "input", "expected", "actual"}
SYNTHETIC_ID = re.compile(r"\b(?:user|account|search|tombstone|legal_hold|audit_record|data_flow)_70\d{5}\b")


class CustomCaseRunTests(unittest.TestCase):
    """The seven cases reproduce the outputs written down before the pipeline runs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        cls.outcomes: Dict[str, cc.Outcome] = {
            outcome.case_id: outcome for outcome in cc.run_all(Path(cls._scratch.name))
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def test_all_seven_cases_run(self) -> None:
        self.assertEqual(tuple(sorted(self.outcomes)), CASE_IDS)

    def test_every_case_reproduces_its_expected_output(self) -> None:
        for case_id in CASE_IDS:
            outcome = self.outcomes[case_id]
            self.assertEqual(outcome.expected, outcome.actual, case_id)

    def test_rows_carry_the_keys_render_reports_reads(self) -> None:
        for outcome in self.outcomes.values():
            row = outcome.as_row()
            self.assertEqual(set(row), ROW_KEYS)
            self.assertTrue(all(row[key] for key in ROW_KEYS), outcome.case_id)

    def test_c2_runs_with_the_lexicon_and_with_the_scripted_model(self) -> None:
        case = cc.case_c2()
        self.assertEqual(case.runs, (cc.RUN_OFF, cc.RUN_SCRIPTED))
        self.assertIn("NOT_APPLICABLE", self.outcomes["C2"].actual)
        self.assertNotIn(" || ", self.outcomes["C2"].actual)

    def test_c4_keeps_the_tombstone_and_leaves_retained_records_unremediated(self) -> None:
        _status, steps = cc.case_c4().expected["synth_c4"]
        operations = {(step[2], step[3]) for step in steps}
        self.assertTrue(any(op == "REDACT_RECORD" for _rid, op in operations))
        self.assertFalse(any(rid.startswith(("legal_hold_", "audit_record_")) and op.startswith(("DELETE", "REDACT"))
                             for rid, op in operations))

    def test_c7_cases_do_not_share_evidence(self) -> None:
        expected = cc.case_c7().expected
        first = {step[5] for step in expected["synth_c7a"][1] if step[5]}
        second = {step[5] for step in expected["synth_c7b"][1] if step[5]}
        self.assertFalse(first & second)


class MismatchDetectionTests(unittest.TestCase):
    """A wrong expectation is reported as a failure, so a pass is not vacuous."""

    def test_changed_expectation_fails(self) -> None:
        case = cc.case_c1()
        wrong = dataclasses.replace(case, expected={"synth_c1": ("COMPLETE", ())})
        with tempfile.TemporaryDirectory() as scratch:
            outcome = cc.run_case(wrong, Path(scratch))
        self.assertFalse(outcome.passed)

    def test_scripted_model_that_disagrees_is_visible(self) -> None:
        case = dataclasses.replace(cc.case_c2(), runs=(cc.RUN_SCRIPTED,))
        wrong = dataclasses.replace(case, expected={"synth_c2": ("INCOMPLETE", ())})
        with tempfile.TemporaryDirectory() as scratch:
            self.assertFalse(cc.run_case(wrong, Path(scratch)).passed)


class SyntheticDataTests(unittest.TestCase):
    """The mini datasets copy the real policy table and share no id with `dataset/`."""

    @needs_dataset
    def test_rules_match_the_dataset_policy_table(self) -> None:
        with (Config().dataset_dir / "deletion_rules.csv").open(encoding="utf-8", newline="") as handle:
            rows = tuple(tuple(row) for row in list(csv.reader(handle))[1:])
        self.assertEqual(rows, cc.RULES)

    def test_no_synthetic_id_occurs_in_the_challenge_dataset(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in sorted(Config().dataset_dir.glob("*.csv"))
        )
        used = set(SYNTHETIC_ID.findall(Path(cc.__file__).read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual({rid for rid in used if rid in text}, set())

    def test_written_dataset_uses_the_participant_layout(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "dataset"
            cc.write_dataset(cc.case_c3().dataset, root)
            names = {path.name for path in root.iterdir()}
            self.assertIn("evidence_files.csv", names)
            self.assertIn("evidence", names)
            self.assertEqual(len(list((root / "evidence").rglob("*.*"))), 2)


class CommandLineTests(unittest.TestCase):
    def test_json_output_lists_every_case(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "custom_cases.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = cc.main(["--json", str(target)])
            rows = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(code, cc.EXIT_OK)
        self.assertEqual(tuple(row["id"] for row in rows), CASE_IDS)


if __name__ == "__main__":
    unittest.main()
