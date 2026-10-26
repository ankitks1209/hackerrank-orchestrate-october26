"""Tests for ghostaudit.emit and tests.gold (SPEC 8.1, 8.2, 8.4)."""
from __future__ import annotations

import csv
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import List

from ghostaudit import emit as emit_module
from ghostaudit.model import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_NOT_APPLICABLE,
    CaseResult,
    ResourceVerdict,
    Step,
    Treatment,
)
from evaluation.gold import GoldReader, abstract_verdicts
from tests.dataset_guard import needs_dataset

STEP_KEYS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}


def verdict(system: str, resource: str, treatment: Treatment,
            violating: bool, cite: str = "evidence_01") -> ResourceVerdict:
    return ResourceVerdict(system, resource, treatment, violating, cite, "test", "fixture")


def ops(steps) -> List[str]:
    return [(s.phase, s.operation, s.system_id, s.resource_id) for s in steps]


@needs_dataset
class GoldRoundTripTests(unittest.TestCase):
    def test_all_gold_cases_round_trip(self) -> None:
        gold = GoldReader().cases()
        self.assertEqual(len(gold), 32)
        for case_id, expected in sorted(gold.items()):
            status, steps = emit_module.emit(abstract_verdicts(expected.steps))
            self.assertEqual(status, expected.deletion_status, case_id)
            self.assertEqual(emit_module.serialize(steps),
                             emit_module.serialize(expected.steps), case_id)

    def test_gold_steps_have_exactly_seven_keys(self) -> None:
        for expected in GoldReader().cases().values():
            for step in expected.steps:
                self.assertEqual({f.name for f in dataclasses.fields(step)}, STEP_KEYS)

    def test_phase_ordering_of_analytics_support_pair(self) -> None:
        sample = GoldReader().cases()["case_11"]
        _, steps = emit_module.emit(abstract_verdicts(sample.steps))
        remediation = [(s.system_id, s.operation) for s in steps if s.phase == "REMEDIATION"]
        self.assertEqual(remediation, [
            ("integration_service", "DISABLE_DATA_FLOW"),
            ("search_service", "DELETE_RECORD"),
            ("support_platform", "REDACT_RECORD"),
            ("analytics_platform", "ANONYMIZE_RECORD"),
        ])
        findings = [(s.system_id, s.operation) for s in steps if s.phase == "FINDING"]
        self.assertEqual(findings[1:3], [
            ("analytics_platform", "REPORT_EXPOSED_PII"),
            ("support_platform", "REPORT_EXPOSED_PII"),
        ])


class EmitRulesTests(unittest.TestCase):
    def test_violating_resource_gets_three_phases(self) -> None:
        status, steps = emit_module.emit([verdict("search_service", "search_1", Treatment.DELETE, True, "evidence_07")])
        self.assertEqual(status, STATUS_INCOMPLETE)
        self.assertEqual([(s.phase, s.operation, s.state, s.evidence_id) for s in steps], [
            ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_07"),
            ("REMEDIATION", "DELETE_RECORD", "ABSENT", ""),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
        ])
        self.assertEqual([s.step_no for s in steps], [1, 2, 3])

    def test_compliant_resource_in_complete_case_is_cited(self) -> None:
        status, steps = emit_module.emit([verdict("a", "r1", Treatment.RETAIN, False, "evidence_09")])
        self.assertEqual(status, STATUS_COMPLETE)
        self.assertEqual([(s.operation, s.evidence_id) for s in steps],
                         [("VERIFY_RECORD_PRESENT", "evidence_09")])

    def test_compliant_resource_in_incomplete_case_has_empty_evidence(self) -> None:
        _, steps = emit_module.emit([
            verdict("a", "r1", Treatment.RETAIN, False, "evidence_09"),
            verdict("b", "r2", Treatment.FLOW, True, "evidence_10"),
        ])
        retained = [s for s in steps if s.resource_id == "r1"]
        self.assertEqual([s.evidence_id for s in retained], [""])

    def test_remediation_and_verification_never_cite(self) -> None:
        _, steps = emit_module.emit([verdict("a", "r1", Treatment.RESTORE, True, "evidence_10")])
        self.assertEqual([s.evidence_id for s in steps], ["evidence_10", "", ""])

    def test_empty_verdicts_complete_with_no_steps(self) -> None:
        self.assertEqual(emit_module.emit([]), (STATUS_COMPLETE, ()))

    def test_duplicates_collapse_and_renumber(self) -> None:
        item = verdict("a", "r1", Treatment.DELETE, True)
        _, steps = emit_module.emit([item, item, verdict("a", "r2", Treatment.DELETE, True)])
        self.assertEqual(len(steps), 6)
        self.assertEqual([s.step_no for s in steps], [1, 2, 3, 4, 5, 6])

    def test_input_order_does_not_change_output(self) -> None:
        items = [verdict("b", "r2", Treatment.DELETE, True), verdict("a", "r9", Treatment.REDACT, True),
                 verdict("a", "r1", Treatment.FLOW, False)]
        forward = emit_module.emit(items)
        self.assertEqual(forward, emit_module.emit(list(reversed(items))))

    def test_string_comparison_of_resource_ids(self) -> None:
        _, steps = emit_module.emit([verdict("s", "r10", Treatment.DELETE, False),
                                     verdict("s", "r9", Treatment.DELETE, False)])
        self.assertEqual([s.resource_id for s in steps], ["r10", "r9"])

    def test_violating_retain_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            emit_module.emit([verdict("a", "r1", Treatment.RETAIN, True)])


class SerializeAndWriteTests(unittest.TestCase):
    def test_serialize_is_compact_sorted_and_unescaped(self) -> None:
        step = Step(1, "FINDING", "sé", "r1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        text = emit_module.serialize([step])
        self.assertEqual(text, '[{"evidence_id":"evidence_01","operation":"REPORT_REMAINING_RECORD",'
                               '"phase":"FINDING","resource_id":"r1","state":"PRESENT","step_no":1,'
                               '"system_id":"sé"}]')
        self.assertEqual(emit_module.serialize([]), "[]")

    def test_not_applicable_row_has_empty_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            emit_module.write_output([CaseResult("case_1", STATUS_NOT_APPLICABLE, ())], path)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(rows, [{"case_id": "case_1", "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}])

    def test_write_output_header_order_and_line_endings(self) -> None:
        results = [CaseResult(name, STATUS_NOT_APPLICABLE, ()) for name in ("case_10", "case_2", "case_9")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "out.csv"
            emit_module.write_output(results, path)
            raw = path.read_bytes()
        self.assertEqual(raw.decode("utf-8"),
                         "case_id,deletion_status,steps_json\n"
                         "case_2,NOT_APPLICABLE,[]\ncase_9,NOT_APPLICABLE,[]\ncase_10,NOT_APPLICABLE,[]\n")

    def test_write_output_rejects_duplicate_case_ids(self) -> None:
        results = [CaseResult("case_1", STATUS_NOT_APPLICABLE, ())] * 2
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                emit_module.write_output(results, Path(tmp) / "out.csv")

    @needs_dataset
    def test_written_steps_parse_back_equal(self) -> None:
        gold = GoldReader().cases()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            emit_module.write_output(gold.values(), path)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual([r["case_id"] for r in rows], sorted(gold, key=emit_module.case_sort_key))
        for row in rows:
            self.assertEqual(json.loads(row["steps_json"]),
                             [dataclasses.asdict(s) for s in gold[row["case_id"]].steps])


if __name__ == "__main__":
    unittest.main()
