"""Tests for the blind-audit tooling (T39; LOCAL_EVALUATION_STRATEGY P3).

The sampler and the scorer run on synthetic cases and on the public sample answers; no audit is
run and no label for the evaluation cases exists.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

from devtools.audit import audit_score as scoring
from devtools.audit import sampler
from evaluation.raw_dataset import File, RawDataset, load_dataset
from evaluation.verify_steps import Case, Step, read_output
from ghostaudit.config import REPO_ROOT
from ghostaudit.emit import write_output
from ghostaudit.model import CaseResult
from ghostaudit.model import Step as ModelStep
from tests.dataset_guard import needs_dataset
from evaluation.gold import SAMPLE_OUTPUT

AUDIT_DIR = REPO_ROOT / "devtools" / "audit"
PACKAGE_FILES = sorted((REPO_ROOT / "code" / "ghostaudit").rglob("*.py")) + [REPO_ROOT / "code" / "main.py"]
# Synthetic diagnostics: sample-range ids stand in for evaluation cases (the tests name no evaluation id).
DIAGNOSTICS = """\
### case_21 (evaluation): COMPLETE

- Account: none (link basis none)
### case_22 (evaluation): INCOMPLETE

- Account: account_9 (hand-crafted rule) (link basis none)
### case_23 (evaluation): INCOMPLETE

- Account: account_7 (link basis unique)
### case_05 (sample): COMPLETE

- Account: none (link basis none)
"""


def step(no: int, phase: str, system: str, rid: str, op: str, state: str, evidence: str = "") -> Step:
    return Step(no, phase, system, rid, op, state, evidence)


def case(case_id: str, status: str, *steps: Step) -> Case:
    return Case(case_id, status, tuple(steps))


def dataset_with(files: Dict[str, str]) -> RawDataset:
    base = load_dataset(REPO_ROOT / "dataset")
    manifest = {file_id: File(file_id, Path("/x") / path, 0, number) for number, (file_id, path) in enumerate(files.items())}
    return RawDataset(base.root, base.requests, manifest, base.activity, base.audit, base.user_by_email,
                      base.keys_by_user, base.user_by_key, base.rule_categories)


@needs_dataset
class FamilyAndCellTests(unittest.TestCase):
    def test_family_drops_dates_and_numbers(self) -> None:
        dataset = dataset_with({
            "e1": "evidence/databases/customer_data_inventory_20260703.sql",
            "e2": "evidence/records/service_resource_export_20260310_1234.json",
            "e3": "evidence/logs/support_replica.log"})
        self.assertEqual(sampler.file_family(dataset, "e1"), "databases/customer_data_inventory")
        self.assertEqual(sampler.file_family(dataset, "e2"), "records/service_resource_export")
        self.assertEqual(sampler.file_family(dataset, "e3"), "logs/support_replica")
        self.assertEqual(sampler.file_family(dataset, ""), sampler.NO_FILE)
        self.assertEqual(sampler.file_family(dataset, "activity_5"), "row")

    def test_cells_combine_family_system_operation_status(self) -> None:
        dataset = dataset_with({"e1": "evidence/databases/customer_data_inventory_20260703.sql"})
        cells = sampler.cells_of(dataset, case("case_1", "COMPLETE",
                                               step(1, "VERIFICATION", "account_service", "account_1",
                                                    "VERIFY_RECORD_ABSENT", "ABSENT", "e1")))
        self.assertEqual(cells, frozenset({("databases/customer_data_inventory", "account_service",
                                            "VERIFY_RECORD_ABSENT", "COMPLETE")}))


class CoverageTests(unittest.TestCase):
    @staticmethod
    def cases() -> Dict[str, Case]:
        verify = lambda no, system, op, ev: step(no, "VERIFICATION", system, "r%d" % no, op, "S", ev)
        return {
            "case_1": case("case_1", "COMPLETE", verify(1, "account_service", "VERIFY_RECORD_ABSENT", "e1")),
            "case_2": case("case_2", "COMPLETE", verify(1, "account_service", "VERIFY_RECORD_ABSENT", "e1"),
                           verify(2, "security_service", "VERIFY_RECORD_PRESENT", "e1")),
            "case_3": case("case_3", "COMPLETE", verify(1, "account_service", "VERIFY_RECORD_ABSENT", "e1")),
            "case_9": case("case_9", "NOT_APPLICABLE"),
            "case_10": case("case_10", "INCOMPLETE", verify(1, "search_service", "VERIFY_RECORD_ABSENT", "")),
        }

    @needs_dataset
    def test_greedy_cover_takes_the_biggest_first_and_covers_every_cell(self) -> None:
        dataset = dataset_with({"e1": "evidence/records/x_1.json"})
        cases = self.cases()
        chosen = sampler.coverage_set(dataset, cases)
        self.assertEqual(chosen, ["case_2", "case_10"])
        covered = set().union(*(sampler.cells_of(dataset, cases[c]) for c in chosen))
        every = set().union(*(sampler.cells_of(dataset, c) for c in cases.values()))
        self.assertEqual(covered, every)

    @needs_dataset
    def test_forced_cases_are_kept_and_unknown_ids_ignored(self) -> None:
        dataset = dataset_with({"e1": "evidence/records/x_1.json"})
        chosen = sampler.coverage_set(dataset, self.cases(), forced=["case_3", "case_31"])
        self.assertIn("case_3", chosen)
        self.assertNotIn("case_31", chosen)

    def test_natural_order_of_case_ids(self) -> None:
        self.assertEqual(sorted(["case_10", "case_9", "case_30"], key=sampler.natural_key),
                         ["case_9", "case_10", "case_30"])

    @needs_dataset
    def test_real_output_cover_is_small_and_complete(self) -> None:
        dataset = load_dataset(REPO_ROOT / "dataset")
        cases = read_output(SAMPLE_OUTPUT)
        samples = {case_id: c for case_id, c in cases.items()}
        chosen = sampler.coverage_set(dataset, samples)
        every = set().union(*(sampler.cells_of(dataset, c) for c in samples.values() if c.status != "NOT_APPLICABLE"))
        covered = set().union(*(sampler.cells_of(dataset, samples[c]) for c in chosen))
        self.assertEqual(covered, every)
        self.assertLess(len(chosen), len(samples))


class ForcedCaseTests(unittest.TestCase):
    def test_handcrafted_family_is_read_from_the_diagnostics(self) -> None:
        self.assertEqual(sampler.handcrafted_cases(DIAGNOSTICS), frozenset({"case_21", "case_22"}))
        self.assertEqual(sampler.handcrafted_cases(""), frozenset())

    def test_low_tier_cases(self) -> None:
        tiers = {"case_1": "high", "case_2": sampler.LOW_TIER, "case_3": "medium"}
        self.assertEqual(sampler.low_tier_cases(tiers), frozenset({"case_2"}))

    @needs_dataset
    def test_every_reason_is_named_and_limited_to_known_cases(self) -> None:
        dataset = dataset_with({"e1": "evidence/images/console_1.png"})
        cases = {cid: case(cid, "COMPLETE", step(1, "VERIFICATION", "account_service", "account_1",
                                                  "VERIFY_RECORD_ABSENT", "ABSENT", "e1" if cid == "case_21" else ""))
                 for cid in ("case_21", "case_22", "case_23", "case_24")}
        forced = sampler.forced_cases(dataset, cases, DIAGNOSTICS, {"case_24": sampler.LOW_TIER}, None,
                                      ["case_23", "synth_unknown"])
        self.assertEqual(forced, {
            sampler.FORCED_MEDIA: ["case_21"],
            sampler.FORCED_HANDCRAFTED: ["case_21", "case_22"],
            sampler.FORCED_LOW_TIER: ["case_24"],
            sampler.FORCED_P2: [],  # the four cases do not answer every evaluation request
            sampler.FORCED_BY_CALLER: ["case_23"],
        })


class EstimationTests(unittest.TestCase):
    POPULATION = ["case_%d" % n for n in range(1, 201)]
    TIERS = {cid: ("high" if n % 5 else "low") for n, cid in enumerate(POPULATION, start=1)}

    def test_size_stratification_and_weights(self) -> None:
        draws = sampler.estimation_sample(self.POPULATION, self.TIERS, 100, "seed")
        self.assertEqual(len(draws), 100)
        self.assertEqual(len({d.case_id for d in draws}), 100)
        by_tier: Dict[str, List[sampler.Draw]] = {}
        for draw in draws:
            by_tier.setdefault(draw.tier, []).append(draw)
        self.assertEqual({tier: len(found) for tier, found in by_tier.items()}, {"high": 80, "low": 20})
        self.assertAlmostEqual(sum(d.weight for d in draws), 200.0)

    def test_every_tier_is_represented_even_when_small(self) -> None:
        tiers = {cid: ("rare" if cid == "case_7" else "common") for cid in self.POPULATION}
        draws = sampler.estimation_sample(self.POPULATION, tiers, 10, "seed")
        self.assertEqual(len(draws), 10)
        self.assertIn("rare", {d.tier for d in draws})

    def test_same_seed_same_draw_other_seed_other_draw(self) -> None:
        one = [d.case_id for d in sampler.estimation_sample(self.POPULATION, self.TIERS, 50, "a")]
        self.assertEqual(one, [d.case_id for d in sampler.estimation_sample(self.POPULATION, self.TIERS, 50, "a")])
        self.assertNotEqual(one, [d.case_id for d in sampler.estimation_sample(self.POPULATION, self.TIERS, 50, "b")])

    def test_unknown_tiers_form_one_stratum(self) -> None:
        draws = sampler.estimation_sample(self.POPULATION, {}, 20, "seed")
        self.assertEqual({d.tier for d in draws}, {sampler.UNKNOWN_TIER})

    def test_bad_sizes_are_rejected(self) -> None:
        for size in (0, 201):
            with self.assertRaises(ValueError):
                sampler.estimation_sample(self.POPULATION, self.TIERS, size, "seed")


class BoundTests(unittest.TestCase):
    def test_zero_errors_matches_the_rule_of_three_style_bound(self) -> None:
        self.assertAlmostEqual(scoring.upper_bound(0, 100), 1 - 0.05 ** (1 / 100), places=6)
        self.assertAlmostEqual(scoring.upper_bound(0, 644), 0.0046, places=4)

    def test_known_values(self) -> None:
        self.assertAlmostEqual(scoring.upper_bound(2, 644), 0.0097, places=4)
        self.assertAlmostEqual(scoring.upper_bound(2, 900), 0.0070, places=4)

    def test_bound_grows_with_errors_and_shrinks_with_trials(self) -> None:
        self.assertLess(scoring.upper_bound(1, 500), scoring.upper_bound(3, 500))
        self.assertLess(scoring.upper_bound(1, 1000), scoring.upper_bound(1, 500))
        self.assertEqual(scoring.upper_bound(5, 5), 1.0)
        self.assertEqual(scoring.upper_bound(0, 0), 1.0)


LABELS = """\
# Header text that is ignored

```text
### case_31
status: COMPLETE
```

### case_1
status: INCOMPLETE
- FINDING | search_service | search_1 | REPORT_REMAINING_RECORD | PRESENT | evidence_01
- REMEDIATION | search_service | search_1 | DELETE_RECORD | ABSENT |
- VERIFICATION | search_service | search_1 | VERIFY_RECORD_ABSENT | ABSENT |
- VERIFICATION | security_service | EXPECTED_UNKNOWN | VERIFY_RECORD_PRESENT | PRESENT |

### case_2
status: NOT_APPLICABLE
"""

FINDING = step(1, "FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
REMEDIATION = step(2, "REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT")
VERIFICATION = step(3, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT", "ABSENT")
AUDIT_GUESS = step(4, "VERIFICATION", "security_service", "audit_record_9", "VERIFY_RECORD_PRESENT", "PRESENT")


class LabelParsingTests(unittest.TestCase):
    def test_fenced_examples_are_ignored_and_fields_parse(self) -> None:
        labels = scoring.parse_labels(LABELS)
        self.assertEqual(sorted(labels), ["case_1", "case_2"])
        self.assertEqual(labels["case_1"].steps[1], ("REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT", ""))
        self.assertEqual(labels["case_2"].steps, ())

    def test_malformed_input_is_rejected(self) -> None:
        for text in ("### case_1\n- FINDING | a | b\n", "### case_1\n- A | b | c | d | e | f\n",
                     "### case_1\nstatus: COMPLETE\n### case_1\nstatus: COMPLETE\n"):
            with self.assertRaises(scoring.LabelError):
                scoring.parse_labels(text)

    def test_the_shipped_label_file_parses_and_holds_no_labels(self) -> None:
        self.assertEqual(scoring.parse_labels((AUDIT_DIR / "audit_labels.md").read_text(encoding="utf-8")), {})


class ScoringTests(unittest.TestCase):
    def labels(self) -> Dict[str, scoring.Label]:
        return scoring.parse_labels(LABELS)

    def test_exact_match_has_no_visible_error_and_one_structural_miss(self) -> None:
        predicted = case("case_1", "INCOMPLETE", FINDING, REMEDIATION, VERIFICATION)
        result = scoring.score_case(self.labels()["case_1"], predicted)
        self.assertEqual((result.status_ok, result.errors, result.trials, result.structural), (True, 0, 3, 1))

    def test_a_guess_at_an_unknowable_id_is_not_a_visible_error(self) -> None:
        predicted = case("case_1", "INCOMPLETE", FINDING, REMEDIATION, VERIFICATION, AUDIT_GUESS)
        result = scoring.score_case(self.labels()["case_1"], predicted)
        self.assertEqual((result.errors, result.structural), (0, 1))

    def test_missing_wrong_and_extra_steps_are_visible_errors(self) -> None:
        wrong = step(2, "REMEDIATION", "search_service", "search_2", "DELETE_RECORD", "ABSENT")
        predicted = case("case_1", "INCOMPLETE", FINDING, wrong)
        result = scoring.score_case(self.labels()["case_1"], predicted)
        self.assertEqual(result.errors, 3)  # missing remediation, extra wrong one, missing verification

    def test_status_error_is_counted(self) -> None:
        predicted = case("case_2", "COMPLETE")
        self.assertFalse(scoring.score_case(self.labels()["case_2"], predicted).status_ok)

    def test_report_gate(self) -> None:
        predictions = {"case_1": case("case_1", "INCOMPLETE", FINDING, REMEDIATION, VERIFICATION),
                       "case_2": case("case_2", "NOT_APPLICABLE")}
        report = scoring.audit(self.labels(), predictions)
        self.assertEqual((report.cases, report.status_errors, report.errors, report.structural), (2, 0, 0, 1))
        self.assertFalse(report.passes)  # 3 steps are too few to bound the error below 1.3 %
        self.assertGreater(report.upper, scoring.MAX_VISIBLE_UPPER)

    def test_enough_clean_steps_pass_and_a_status_error_fails(self) -> None:
        many = {"case_%d" % n: scoring.Label("case_%d" % n, "COMPLETE", ()) for n in range(1, 400)}
        clean = {c: case(c, "COMPLETE", *[step(i, "VERIFICATION", "account_service", "account_%d" % i,
                                              "VERIFY_RECORD_ABSENT", "ABSENT", "e") for i in range(1, 4)])
                 for c in many}
        labels = {c: scoring.Label(c, "COMPLETE", tuple(
            ("VERIFICATION", "account_service", "account_%d" % i, "VERIFY_RECORD_ABSENT", "ABSENT", "e") for i in range(1, 4)))
            for c in many}
        self.assertTrue(scoring.audit(labels, clean).passes)
        clean["case_1"] = case("case_1", "INCOMPLETE", *clean["case_1"].steps)
        self.assertFalse(scoring.audit(labels, clean).passes)

    def test_weights_change_the_point_estimate_only(self) -> None:
        predictions = {"case_1": case("case_1", "INCOMPLETE", FINDING),
                       "case_2": case("case_2", "NOT_APPLICABLE")}
        plain = scoring.audit(self.labels(), predictions)
        weighted = scoring.audit(self.labels(), predictions, {"case_1": 5.0})
        self.assertEqual((plain.errors, plain.trials), (weighted.errors, weighted.trials))

    def test_label_without_prediction_is_an_error(self) -> None:
        with self.assertRaises(scoring.LabelError):
            scoring.audit(self.labels(), {})

    @needs_dataset
    def test_calibration_of_a_perfect_auditor_on_public_answers(self) -> None:
        gold = read_output(SAMPLE_OUTPUT)
        labels = {c: scoring.Label(c, g.status, tuple(
            (s.phase, s.system_id, s.resource_id, s.operation, s.state, s.evidence_id) for s in g.steps))
            for c, g in gold.items()}
        report = scoring.audit(labels, gold)
        self.assertEqual((report.status_errors, report.errors, report.structural), (0, 0, 0))
        self.assertEqual(report.trials, sum(len(g.steps) for g in gold.values()))


class CommandLineTests(unittest.TestCase):
    def test_scorer_cli_reports_and_exits_nonzero_on_fail(self) -> None:
        results = [CaseResult("case_1", "INCOMPLETE", tuple(ModelStep(*s.__dict__.values()) for s in (FINDING, REMEDIATION, VERIFICATION))),
                   CaseResult("case_2", "NOT_APPLICABLE", ())]
        with tempfile.TemporaryDirectory() as scratch:
            labels, pred = Path(scratch) / "labels.md", Path(scratch) / "output.csv"
            labels.write_text(LABELS, encoding="utf-8")
            write_output(results, pred)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scoring.main(["--labels", str(labels), "--pred", str(pred)])
        self.assertIn("One-sided 95%", out.getvalue())
        self.assertEqual(code, 1)  # three steps cannot bound the error below the gate

    def test_scorer_cli_input_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scoring.main(["--labels", "/nonexistent.md", "--pred", str(SAMPLE_OUTPUT)]), 2)

    @needs_dataset
    def test_sampler_cli_prints_json(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as scratch:
            diag = Path(scratch) / "diagnostics.md"
            diag.write_text(DIAGNOSTICS, encoding="utf-8")
            with contextlib.redirect_stdout(out):
                code = sampler.main(["--pred", str(self.population_file(scratch)), "--dataset", str(REPO_ROOT / "dataset"),
                                     "--diag", str(diag), "--force", "case_03", "--seed", "s", "--size", "100"])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["forced"][sampler.FORCED_BY_CALLER], ["case_03"])
        self.assertIn("case_03", result["coverage"])
        drawn = [draw["case_id"] for draw in result["estimation"]]
        self.assertEqual(len(drawn), 100)
        self.assertAlmostEqual(sum(draw["weight"] for draw in result["estimation"]), 120.0)
        self.assertTrue(set(drawn) & set(result["coverage"]), "the draw ignores the coverage set")

    @staticmethod
    def population_file(scratch: str) -> Path:
        """120 public-style rows: the sample answers plus synthetic NOT_APPLICABLE rows."""
        rows = [CaseResult(c.case_id, c.status, tuple(ModelStep(*s.__dict__.values()) for s in c.steps))
                for c in read_output(SAMPLE_OUTPUT).values()]
        rows += [CaseResult("case_%d" % n, "NOT_APPLICABLE", ()) for n in range(1001, 1001 + 120 - len(rows))]
        target = Path(scratch) / "population.csv"
        write_output(rows, target)
        return target

    def test_sampler_rejects_a_small_estimation_sample(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sampler.main(["--pred", str(SAMPLE_OUTPUT), "--size", "10", "--seed", "x"]), 2)


class IsolationTests(unittest.TestCase):
    def test_the_pipeline_never_names_the_audit_package(self) -> None:
        offenders = [path.name for path in PACKAGE_FILES
                     if any(word in path.read_text(encoding="utf-8") for word in ("audit_labels", "evaluation.audit", "evaluation/audit"))]
        self.assertEqual(offenders, [])

    def test_prompts_state_what_each_auditor_may_not_read(self) -> None:
        r2 = (AUDIT_DIR / "prompts" / "r2_spec_free.md").read_text(encoding="utf-8")
        self.assertIn("must not read", r2)
        self.assertIn("SPEC.md", r2.split("must not read")[1])
        self.assertIn("output.csv", r2.split("must not read")[1])
        for name in ("r1_conformance.md", "r3_adversarial.md"):
            self.assertTrue((AUDIT_DIR / "prompts" / name).read_text(encoding="utf-8").strip(), name)


if __name__ == "__main__":
    unittest.main()
