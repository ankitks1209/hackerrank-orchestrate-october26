"""Tests for ghostaudit.contract (SPEC 8, N8).

Each contract rule has a negative fixture built from synthetic requests and
citations. The one real-data test validates the public gold answers through
tests.gold, the only sanctioned reader of sample_output.csv.
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ghostaudit import contract
from ghostaudit.config import REPO_ROOT
from ghostaudit.dataset import DatasetReader
from ghostaudit.emit import OUTPUT_COLUMNS, serialize
from ghostaudit.model import Request
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

WINDOW_START = 1000
AUDIT_AT = 2000

REQUESTS = (
    Request("case_01", "", 500, "COMPLETE", WINDOW_START, AUDIT_AT, "delete my data", False),
    Request("case_02", "", 500, "PARTIALLY_COMPLETE", WINDOW_START, AUDIT_AT,
            "delete my data", False),
)

CITATIONS = contract.Citations(
    files={
        "evidence_start": WINDOW_START,
        "evidence_01": 1500,
        "evidence_edge": AUDIT_AT,
        "evidence_late": 2500,
        "evidence_early": 900,
    },
    activities={"activity_01": 1500, "activity_late": 2500, "activity_early": 500},
    audits={"audit_01": 1800, "audit_late": 2100, "audit_old": 500},
)


def step(number: int, phase: str, operation: str, state: str, evidence: str = "evidence_01",
         system: str = "account_service", resource: str = "account_001") -> Dict[str, object]:
    """One step dict with exactly the seven AGENTS 6.3 keys."""
    return {"step_no": number, "phase": phase, "system_id": system, "resource_id": resource,
            "operation": operation, "state": state, "evidence_id": evidence}


def row(case_id: str, status: str, steps: Optional[Sequence[object]] = None,
        raw: Optional[str] = None) -> List[str]:
    """One output row; `raw` replaces the serialized steps when a test needs bad JSON."""
    if raw is None:
        raw = json.dumps(list(steps or []), sort_keys=True, separators=(",", ":"))
    return [case_id, status, raw]


def output(*rows: Sequence[str]) -> List[List[str]]:
    """A full csv table: header first, then the given rows."""
    return [list(OUTPUT_COLUMNS)] + [list(item) for item in rows]


def complete_row(case_id: str = "case_01") -> List[str]:
    return row(case_id, "COMPLETE", [step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")])


def incomplete_steps() -> List[Dict[str, object]]:
    """Finding, remediation and verification for a search record, plus the account step."""
    return [
        step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "activity_01",
             "search_service", "search_1"),
        step(2, "REMEDIATION", "DELETE_RECORD", "ABSENT", "", "search_service", "search_1"),
        step(3, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "",
             "account_service", "account_001"),
        step(4, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "", "search_service", "search_1"),
    ]


def valid_rows() -> List[List[str]]:
    return output(complete_row("case_01"), row("case_02", "INCOMPLETE", incomplete_steps()))


def check(rows: Sequence[Sequence[str]]) -> contract.ValidationResult:
    return contract.validate(rows, REQUESTS, CITATIONS)


def rule_names(items: Sequence[contract.Violation]) -> List[str]:
    return sorted(item.rule for item in items)


def _write_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


class ValidOutputTests(unittest.TestCase):
    def test_valid_output_has_no_violations_or_warnings(self) -> None:
        result = check(valid_rows())
        self.assertTrue(result.ok)
        self.assertEqual(result.violations, ())
        self.assertEqual(result.warnings, ())

    def test_not_applicable_with_empty_steps_is_valid(self) -> None:
        result = check(output(row("case_01", "NOT_APPLICABLE"), row("case_02", "NOT_APPLICABLE")))
        self.assertTrue(result.ok)
        self.assertEqual(result.warnings, ())

    def test_window_bounds_are_inclusive(self) -> None:
        steps = [
            step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_start"),
            step(2, "VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT", "evidence_edge",
                 "legal_service", "legal_1"),
        ]
        result = check(output(row("case_01", "COMPLETE", steps), row("case_02", "NOT_APPLICABLE")))
        self.assertTrue(result.ok, result.violations)

    def test_validate_file_reads_written_csv(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "output.csv"
            _write_csv(path, valid_rows())
            self.assertTrue(contract.validate_file(path, REQUESTS, CITATIONS).ok)
            broken = Path(scratch) / "broken.csv"
            rows = valid_rows()
            rows[0] = ["case_id", "deletion_status", "steps"]
            _write_csv(broken, rows)
            broken_result = contract.validate_file(broken, REQUESTS, CITATIONS)
            self.assertEqual(rule_names(broken_result.violations), ["header"])

    @needs_dataset
    def test_gold_sample_output_validates_clean(self) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        samples = tuple(request for request in reader.requests() if request.is_sample)
        citations = contract.Citations.from_reader(reader)
        gold = GoldReader().cases()
        rows = output(*[[case_id, gold[case_id].deletion_status, serialize(gold[case_id].steps)]
                        for case_id in sorted(gold)])
        result = contract.validate(rows, samples, citations)
        self.assertEqual(result.violations, ())
        self.assertEqual(result.warnings, ())

    @needs_dataset
    def test_citations_index_dataset_ids(self) -> None:
        citations = contract.Citations.from_reader(DatasetReader(REPO_ROOT / "dataset"))
        self.assertIn("evidence_01", citations.files)
        self.assertIn("activity_01", citations.activities)
        self.assertIn("audit_01", citations.audits)


class StructureTests(unittest.TestCase):
    def test_bad_header_is_rejected(self) -> None:
        rows = valid_rows()
        rows[0] = ["case_id", "deletion_status", "steps"]
        self.assertEqual(rule_names(check(rows).violations), ["header"])

    def test_row_with_wrong_field_count_is_rejected(self) -> None:
        rows = output(["case_01", "COMPLETE"], row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["row_shape"])

    def test_unknown_status_is_rejected(self) -> None:
        steps = [step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")]
        rows = output(row("case_01", "DONE", steps), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["status"])

    def test_invalid_json_is_rejected(self) -> None:
        rows = output(row("case_01", "COMPLETE", raw="[{"), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["steps_json"])

    def test_json_that_is_not_an_array_is_rejected(self) -> None:
        rows = output(row("case_01", "COMPLETE", raw='{"step_no": 1}'),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["steps_json"])

    def test_step_missing_a_key_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        del bad["evidence_id"]
        rows = output(row("case_01", "COMPLETE", [bad]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["step_shape"])

    def test_step_with_extra_key_is_rejected(self) -> None:
        extra = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        extra["note"] = "x"
        rows = output(row("case_01", "COMPLETE", [extra]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["step_shape"])

    def test_non_object_step_is_rejected(self) -> None:
        rows = output(row("case_01", "COMPLETE", raw="[1]"), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["step_shape"])

    def test_non_string_field_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        bad["resource_id"] = 5
        rows = output(row("case_01", "COMPLETE", [bad]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["step_shape"])

    def test_step_no_must_run_one_to_n(self) -> None:
        bad = step(2, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        rows = output(row("case_01", "COMPLETE", [bad]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["step_no"])

    def test_operation_state_pair_must_match_table(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "PRESENT")
        rows = output(row("case_01", "COMPLETE", [bad]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["operation_table"])

    def test_phase_must_match_operation(self) -> None:
        bad = step(1, "FINDING", "VERIFY_RECORD_ABSENT", "ABSENT")
        rows = output(row("case_01", "COMPLETE", [bad]), row("case_02", "NOT_APPLICABLE"))
        self.assertIn("operation_table", rule_names(check(rows).violations))


class CaseSetTests(unittest.TestCase):
    def test_duplicate_case_is_rejected(self) -> None:
        rows = output(complete_row("case_01"), complete_row("case_01"),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["duplicate_case"])

    def test_unknown_case_is_rejected(self) -> None:
        rows = output(complete_row("case_01"), row("case_02", "NOT_APPLICABLE"),
                      row("case_00", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["unknown_case"])

    def test_missing_case_is_rejected(self) -> None:
        result = check(output(complete_row("case_01")))
        self.assertEqual(rule_names(result.violations), ["missing_case"])

    def test_rows_must_follow_natural_order(self) -> None:
        rows = output(row("case_02", "NOT_APPLICABLE"), complete_row("case_01"))
        self.assertEqual(rule_names(check(rows).violations), ["case_order"])


class OrderTests(unittest.TestCase):
    def test_steps_must_follow_sort_key(self) -> None:
        steps = incomplete_steps()
        swapped = [steps[0], steps[1], steps[3], steps[2]]
        swapped = [dict(item, step_no=number) for number, item in enumerate(swapped, start=1)]
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", swapped))
        self.assertEqual(rule_names(check(rows).violations), ["step_order"])

    def test_duplicate_step_identity_is_rejected(self) -> None:
        first = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        second = step(2, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")
        rows = output(row("case_01", "COMPLETE", [first, second]), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["duplicate_step"])


class StatusRuleTests(unittest.TestCase):
    def test_not_applicable_with_steps_is_rejected(self) -> None:
        steps = [step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT")]
        rows = output(row("case_01", "NOT_APPLICABLE", steps), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["status_rule"])

    def test_complete_with_finding_is_rejected(self) -> None:
        steps = [
            step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "activity_01",
                 "search_service", "search_1"),
            step(2, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
        ]
        rows = output(row("case_01", "COMPLETE", steps), row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["status_rule"])

    def test_incomplete_without_finding_is_rejected(self) -> None:
        steps = [step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "")]
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["status_rule"])

    def test_incomplete_remediation_with_evidence_is_rejected(self) -> None:
        steps = incomplete_steps()
        steps[1] = dict(steps[1], evidence_id="evidence_01")
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["status_rule"])

    def test_incomplete_verification_with_evidence_is_rejected(self) -> None:
        steps = incomplete_steps()
        steps[2] = dict(steps[2], evidence_id="evidence_01")
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["status_rule"])


class CitationTests(unittest.TestCase):
    def test_complete_step_without_citation_is_rejected(self) -> None:
        rows = output(row("case_01", "COMPLETE",
                          [step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "")]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_finding_without_citation_is_rejected(self) -> None:
        steps = incomplete_steps()
        steps[0] = dict(steps[0], evidence_id="")
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_unknown_citation_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_missing")
        rows = output(row("case_01", "COMPLETE", [bad]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_file_captured_after_audit_at_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_late")
        rows = output(row("case_01", "COMPLETE", [bad]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_file_captured_before_reported_at_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_early")
        rows = output(row("case_01", "COMPLETE", [bad]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_activity_before_reported_at_is_rejected(self) -> None:
        steps = incomplete_steps()
        steps[0] = dict(steps[0], evidence_id="activity_early")
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_activity_after_audit_at_is_rejected(self) -> None:
        steps = incomplete_steps()
        steps[0] = dict(steps[0], evidence_id="activity_late")
        rows = output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_audit_after_audit_at_is_rejected(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "audit_late")
        rows = output(row("case_01", "COMPLETE", [bad]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertEqual(rule_names(check(rows).violations), ["citation"])

    def test_audit_before_reported_at_is_accepted(self) -> None:
        bad = step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "audit_old")
        rows = output(row("case_01", "COMPLETE", [bad]),
                      row("case_02", "NOT_APPLICABLE"))
        self.assertTrue(check(rows).ok)


class WarningTests(unittest.TestCase):
    def test_complete_without_steps_warns(self) -> None:
        result = check(output(row("case_01", "COMPLETE"), row("case_02", "NOT_APPLICABLE")))
        self.assertTrue(result.ok)
        self.assertEqual(rule_names(result.warnings),
                         ["complete_without_steps", "no_account_step"])

    def test_deletion_case_without_account_step_warns(self) -> None:
        steps = incomplete_steps()[:2] + incomplete_steps()[3:]
        steps = [dict(item, step_no=number) for number, item in enumerate(steps, start=1)]
        result = check(output(complete_row("case_01"), row("case_02", "INCOMPLETE", steps)))
        self.assertTrue(result.ok, result.violations)
        self.assertEqual(rule_names(result.warnings), ["no_account_step"])

    def test_not_applicable_never_warns_for_missing_account(self) -> None:
        result = check(output(row("case_01", "NOT_APPLICABLE"), row("case_02", "NOT_APPLICABLE")))
        self.assertEqual(result.warnings, ())


if __name__ == "__main__":
    unittest.main()
