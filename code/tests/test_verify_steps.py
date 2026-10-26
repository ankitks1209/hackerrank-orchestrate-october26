"""Tests for the label-free verifier (checks P2a-d and P5 of the evaluation report).

Fixtures are the synthetic custom cases (`evaluation.custom_cases`): their pipeline output is
verified clean, then single faults are injected and each check must name the fault. Whole-dataset
tests run the real pipeline offline into a temporary directory.
"""
from __future__ import annotations

import ast
import contextlib
import dataclasses
import io
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

from evaluation import custom_cases as cc
from evaluation import invariants, redundancy, verify_report, verify_steps
from evaluation.raw_dataset import Act, load_dataset
from evaluation.raw_units import file_units
from evaluation.runner import run_pipeline
from tests.dataset_guard import needs_dataset

EVALUATION_DIR = Path(__file__).resolve().parents[1] / "evaluation"
VERIFIER_MODULES = ("raw_dataset", "raw_units", "verify_steps", "invariants", "redundancy", "verify_report")
FORBIDDEN_IMPORT_ROOTS = ("ghostaudit", "solution")
FORBIDDEN_TEXT = ("sample_output", "solution/")


def to_cases(projections: Dict[str, cc.Projection]) -> Dict[str, verify_steps.Case]:
    cases = {}
    for case_id, (status, steps) in projections.items():
        cases[case_id] = verify_steps.Case(case_id, status, tuple(
            verify_steps.Step(number, *step) for number, step in enumerate(steps, start=1)))
    return cases


class Fixture:
    """A custom case run end to end: raw dataset, pipeline output and the temp directory."""

    def __init__(self, case: cc.CustomCase) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        dataset_dir = root / "dataset"
        cc.write_dataset(case.dataset, dataset_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            self.cases = to_cases(cc.run_cli(dataset_dir, root))
        self.dataset = load_dataset(dataset_dir)

    def close(self) -> None:
        self.scratch.cleanup()

    def replace_step(self, case_id: str, index: int, **changes: object) -> Dict[str, verify_steps.Case]:
        case = self.cases[case_id]
        steps = list(case.steps)
        steps[index] = dataclasses.replace(steps[index], **changes)
        return {**self.cases, case_id: dataclasses.replace(case, steps=tuple(steps))}


class IsolationTests(unittest.TestCase):
    def test_verifier_modules_import_nothing_from_the_solver(self) -> None:
        for name in VERIFIER_MODULES:
            tree = ast.parse((EVALUATION_DIR / (name + ".py")).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                    [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                for module in modules:
                    self.assertNotIn(module.split(".")[0], FORBIDDEN_IMPORT_ROOTS, name)

    def test_verifier_modules_never_open_labels(self) -> None:
        for name in VERIFIER_MODULES:
            tree = ast.parse((EVALUATION_DIR / (name + ".py")).read_text(encoding="utf-8"))
            strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            for text in FORBIDDEN_TEXT:
                self.assertFalse(any(text in value for value in strings if len(value) < 80), (name, text))


class CleanRunTests(unittest.TestCase):
    """The pipeline output of each custom case passes every hard check."""

    def test_each_custom_case_verifies_clean(self) -> None:
        for build in (cc.case_c1, cc.case_c3, cc.case_c4, cc.case_c5, cc.case_c6, cc.case_c7):
            fixture = Fixture(build())
            try:
                findings = verify_steps.locator_check(fixture.dataset, fixture.cases)
                self.assertEqual([f for f in findings if f.code == verify_steps.FAILED], [], build.__name__)
                self.assertEqual(
                    [f for f in verify_steps.recall_sweep(fixture.dataset, fixture.cases)
                     if f.code == verify_steps.UNEXPLAINED], [], build.__name__)
                self.assertEqual(invariants.failed_hard(invariants.run_checks(fixture.dataset, fixture.cases)), [],
                                 build.__name__)
            finally:
                fixture.close()


class LocatorFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = Fixture(cc.case_c5())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()

    def _codes(self, cases: Dict[str, verify_steps.Case]) -> List[str]:
        return [f.code for f in verify_steps.locator_check(self.fixture.dataset, cases)]

    def _finding_index(self) -> int:
        steps = self.fixture.cases["synth_c5"].steps
        return next(i for i, s in enumerate(steps) if s.operation == "REPORT_REMAINING_RECORD")

    def test_clean_case_has_keyed_findings(self) -> None:
        self.assertIn(verify_steps.KEYED, self._codes(self.fixture.cases))

    def test_wrong_resource_is_not_in_the_cited_file(self) -> None:
        cases = self.fixture.replace_step("synth_c5", self._finding_index(), resource_id="search_7999999")
        self.assertIn(verify_steps.FAILED, self._codes(cases))

    def test_unknown_citation_fails(self) -> None:
        cases = self.fixture.replace_step("synth_c5", self._finding_index(), evidence_id="evidence_zz")
        self.assertIn(verify_steps.FAILED, self._codes(cases))

    def test_file_outside_the_window_fails(self) -> None:
        dataset = self.fixture.dataset
        file_id = next(iter(dataset.files))
        moved = dataclasses.replace(dataset.files[file_id], captured_at=dataset.requests[0].audit_at + 10)
        shifted = dataclasses.replace(dataset, files={**dataset.files, file_id: moved})
        codes = [f.code for f in verify_steps.locator_check(shifted, self.fixture.cases)]
        self.assertIn(verify_steps.FAILED, codes)

    def test_absence_claim_on_a_present_record_fails(self) -> None:
        cases = self.fixture.replace_step("synth_c5", self._finding_index(), operation="VERIFY_RECORD_ABSENT")
        self.assertIn(verify_steps.FAILED, self._codes(cases))

    def test_activity_citation_must_name_the_resource(self) -> None:
        cases = self.fixture.replace_step("synth_c5", self._finding_index(), evidence_id="activity_c5_1")
        self.assertIn(verify_steps.FAILED, self._codes(cases))


class TimeTravelTests(unittest.TestCase):
    def test_later_lines_do_not_change_the_checked_state(self) -> None:
        fixture = Fixture(cc.case_c3())
        try:
            findings = verify_steps.locator_check(fixture.dataset, fixture.cases)
            self.assertEqual([f.code for f in findings], [verify_steps.KEYED])
            units = file_units(fixture.dataset.files["evidence_c3a"].path)
            self.assertEqual(len([u for u in units if u.time and u.time > fixture.dataset.requests[0].audit_at]), 1)
        finally:
            fixture.close()


class SweepTests(unittest.TestCase):
    def test_a_missing_resource_beside_the_key_is_reported(self) -> None:
        fixture = Fixture(cc.case_c5())
        try:
            case = fixture.cases["synth_c5"]
            trimmed = dataclasses.replace(case, steps=tuple(s for s in case.steps if s.resource_id != "search_7000107"))
            found = verify_steps.recall_sweep(fixture.dataset, {"synth_c5": trimmed})
            self.assertEqual([(f.resource_id, f.code) for f in found], [("search_7000107", verify_steps.UNEXPLAINED)])
        finally:
            fixture.close()

    def test_post_audit_lines_are_excluded_with_a_reason(self) -> None:
        fixture = Fixture(cc.case_c3())
        try:
            case = dataclasses.replace(fixture.cases["synth_c3"], steps=())
            codes = {f.code for f in verify_steps.recall_sweep(fixture.dataset, {"synth_c3": case})}
            self.assertIn(verify_steps.POST_AUDIT, codes)
        finally:
            fixture.close()

    def test_coverage_marks_other_users_rows_as_decoys(self) -> None:
        fixture = Fixture(cc.case_c6())
        try:
            found = verify_steps.coverage_sweep(fixture.dataset, fixture.cases, {})
            self.assertTrue(found)
            self.assertEqual({f.code for f in found}, {verify_steps.DECOY})
        finally:
            fixture.close()


class InvariantFaultTests(unittest.TestCase):
    @staticmethod
    def case(status: str, *steps: verify_steps.Step) -> Dict[str, verify_steps.Case]:
        return {"case_x": verify_steps.Case("case_x", status, tuple(steps))}

    @staticmethod
    def step(no: int, phase: str, system: str, rid: str, op: str, evidence: str = "") -> verify_steps.Step:
        return verify_steps.Step(no, phase, system, rid, op, "STATE", evidence)

    def test_phase_order_and_numbering(self) -> None:
        cases = self.case("INCOMPLETE",
                          self.step(1, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT"),
                          self.step(3, "FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "evidence_1"))
        self.assertGreaterEqual(len(invariants.structure(cases).failures), 2)

    def test_unpaired_finding(self) -> None:
        cases = self.case("INCOMPLETE",
                          self.step(1, "FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "evidence_1"))
        self.assertEqual(len(invariants.pairing(cases).failures), 1)

    def test_complete_with_an_uncited_step(self) -> None:
        cases = self.case("COMPLETE", self.step(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT"))
        self.assertEqual(len(invariants.structure(cases).failures), 1)

    def test_illegal_operation_system_pair(self) -> None:
        cases = self.case("INCOMPLETE",
                          self.step(1, "REMEDIATION", "backup_service", "backup_1", "DELETE_RECORD"),
                          self.step(2, "REMEDIATION", "search_service", "search_1", "BLOCK_RESTORE"))
        self.assertEqual(len(invariants.legal_pairs(cases).failures), 2)

    def test_incomplete_needs_a_finding_and_cited_findings(self) -> None:
        cases = self.case("INCOMPLETE", self.step(1, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT"))
        self.assertEqual(len(invariants.structure(cases).failures), 1)

    def test_empty_complete_rows_carry_their_diagnostics_reason(self) -> None:
        fixture = Fixture(cc.case_c5())
        try:
            empty = {"synth_c5": verify_steps.Case("synth_c5", "COMPLETE", ())}
            explained = invariants.empty_complete(fixture.dataset, empty, {"synth_c5": ("evidence_7",)})
            self.assertEqual(explained.failures, ("synth_c5: unread in-window media evidence_7",))
            bare = invariants.empty_complete(fixture.dataset, empty, {})
            self.assertEqual(bare.failures, ("synth_c5: " + invariants.UNEXPLAINED_EMPTY,))
        finally:
            fixture.close()

    def test_not_applicable_has_no_steps(self) -> None:
        cases = self.case("NOT_APPLICABLE", self.step(1, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT"))
        self.assertTrue(invariants.structure(cases).failures)

    def test_audit_parity_flags_an_emitted_audit_without_a_record(self) -> None:
        fixture = Fixture(cc.case_c4())
        try:
            self.assertTrue(invariants.audit_parity(fixture.dataset, verify_steps.Evidence(fixture.dataset),
                                                    fixture.cases).ok)
            case = fixture.cases["synth_c4"]
            without = dataclasses.replace(case, steps=tuple(s for s in case.steps if s.system_id != "security_service"))
            check = invariants.audit_parity(fixture.dataset, verify_steps.Evidence(fixture.dataset),
                                            {"synth_c4": without})
            self.assertEqual(len(check.failures), 1)
        finally:
            fixture.close()

    def test_audit_parity_accepts_a_record_tied_by_a_link_row(self) -> None:
        # A screenshot cannot be grepped for ids; the catalog LINK row is its text trace.
        fixture = Fixture(cc.case_c5())
        try:
            req = fixture.dataset.requests[0]
            subject = fixture.dataset.subject_of(req)
            case = fixture.cases["synth_c5"]
            extra = verify_steps.Step(99, "VERIFICATION", "security_service", "audit_record_900",
                                      "VERIFY_RECORD_PRESENT", "PRESENT", "evidence_c5a")
            cases = {"synth_c5": dataclasses.replace(case, steps=case.steps + (extra,))}
            evidence = verify_steps.Evidence(fixture.dataset)
            self.assertEqual(len(invariants.audit_parity(fixture.dataset, evidence, cases).failures), 1)
            link = Act("activity_link", req.reported_at + 60, "LINK_RESOURCE_IDENTITY", "data_catalog",
                       "security_service", "audit_record_900",
                       "Data catalog linked audit_record_900 (CJX-1) to someone@example.org and %s." % subject)
            linked = dataclasses.replace(fixture.dataset, activity=fixture.dataset.activity + (link,))
            self.assertTrue(invariants.audit_parity(linked, verify_steps.Evidence(linked), cases).ok)
        finally:
            fixture.close()

    def test_distribution_counts_confusion_and_steps(self) -> None:
        fixture = Fixture(cc.case_c5())
        try:
            report = invariants.distributions(fixture.dataset, fixture.cases)
            self.assertEqual(report["steps"]["cases"], 1)
            self.assertEqual(report["confusion"], {("COMPLETE", "INCOMPLETE"): 1})
        finally:
            fixture.close()


DIAGNOSTICS = """\
- Evidence/template disagreements: 1
| lexicon | model | intake row | requests |
|---|---|---|---|
| DELETION | NO_LLM | NO_N_ROW | 7 |
| NON_DELETION | NO_LLM | N_ROW | 2 |
| DELETION | NO_LLM | N_ROW | 1 |
### case_1 (evaluation): INCOMPLETE

- Unread in-window media: evidence_7, evidence_8
- Verdict search_service/search_1 DELETE violating=True basis=elimination: PRESENT via evidence as DELETE
- Verdict security_service/audit_record_1 RETAIN violating=False basis=audit_id: PRESENT via scope as RETAIN
### case_2 (sample): COMPLETE

- Verdict search_service/search_2 DELETE violating=False basis=unique: ABSENT via evidence as DELETE
"""


class RedundancyTests(unittest.TestCase):
    def test_parses_the_sections_it_reads(self) -> None:
        diag = redundancy.parse_diagnostics(DIAGNOSTICS)
        self.assertEqual(diag.template_disagreements, 1)
        self.assertEqual(sorted(diag.verdicts), ["case_1"])
        self.assertEqual(diag.verdicts["case_1"]["search_1"], ("elimination", "evidence"))
        self.assertEqual(dict(diag.unread_media), {"case_1": ("evidence_7", "evidence_8")})

    def test_matrix_rows_and_single_signal_fraction(self) -> None:
        diag = redundancy.parse_diagnostics(DIAGNOSTICS)
        rows = {row.component: row for row in redundancy.matrix(diag, 4, 5)}
        self.assertEqual((rows["state"].agree, rows["state"].comparable), (0, 1))
        self.assertEqual((rows["intent"].agree, rows["intent"].comparable), (9, 10))
        self.assertAlmostEqual(rows["citation"].rate, 0.8)
        self.assertEqual(redundancy.single_signal_fraction(diag, {"case_1": ["search_1", "audit_record_1"]}), (1, 2))

    def test_empty_text_gives_neutral_values(self) -> None:
        diag = redundancy.parse_diagnostics("")
        self.assertEqual(diag.verdicts, {})
        self.assertEqual(redundancy.matrix(diag, 0, 0)[0].rate, 1.0)


@needs_dataset
class WholeDatasetTests(unittest.TestCase):
    """The real pipeline run, offline: hard invariants hold and every sweep item has a reason."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        scratch = Path(cls._scratch.name)
        out, samples, diag = run_pipeline(scratch, "off")
        dataset = load_dataset(verify_report.DATASET_DIR)
        cls.cases = verify_steps.read_output(out)
        cls.report = verify_report.verify(dataset, cls.cases, verify_steps.read_output(samples),
                                          redundancy.read_diagnostics(diag))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def test_every_evaluation_case_is_checked(self) -> None:
        self.assertEqual(len(self.cases), 518)
        self.assertGreater(len(self.report.locator), 1000)

    def test_hard_invariants_hold(self) -> None:
        self.assertEqual([c.name for c in invariants.failed_hard(self.report.checks)], [])

    def test_sweeps_leave_nothing_unexplained(self) -> None:
        for items in (self.report.recall, self.report.coverage):
            self.assertEqual([i for i in items if i.code == verify_steps.UNEXPLAINED], [])

    def test_every_cited_step_is_confirmed_by_its_locator(self) -> None:
        """P2a: 0 failures."""
        failed = [(i.case_id, i.resource_id, i.detail) for i in self.report.locator if i.code == verify_steps.FAILED]
        self.assertEqual(failed, [])

    def test_every_empty_complete_row_has_a_reason(self) -> None:
        check = next(c for c in self.report.checks if c.name == "COMPLETE rows without steps")
        self.assertEqual([text for text in check.failures if text.endswith(invariants.UNEXPLAINED_EMPTY)], [])

    def test_matrix_covers_the_three_components(self) -> None:
        self.assertEqual([r.component for r in self.report.matrix], ["state", "intent", "citation"])
        self.assertTrue(all(r.comparable > 0 for r in self.report.matrix))

    def test_report_renders_every_section(self) -> None:
        text = verify_report.render(self.report)
        for heading in ("P2a", "P2b", "P2c", "P2d", "P5 invariants", "Distributions"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
