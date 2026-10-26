"""Tests for tools.render_reports (SPEC A5).

Fixtures are synthetic: a small scorer run, a meter fed with synthetic requests and custom cases
written as plain text. The drift tests edit one number by hand and expect `--check` to fail.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Sequence
from unittest import mock

from evaluation import scoring
from ghostaudit.config import (
    DEFAULT_PRICES,
    EVAL_REQUEST_COUNT,
    LIVE_SDK_REQUIREMENT,
    ModelPrice,
)
from ghostaudit.llm import usage
from ghostaudit.llm.client import LLMRequest, LLMResponse
from ghostaudit.model import CaseResult, Step
from tools import render_reports as rr

TEST_COUNT = 7
FIXTURE_CEILINGS = {"G2": 0.8, "G3": 0.9}  # arbitrary, so that the normalization check sees a ratio other than 1
OPUS = DEFAULT_PRICES[0].model
HAIKU = DEFAULT_PRICES[1].model
UNPRICED = "local-model"
FINDING = ("FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
REMEDIATE = ("REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT", "")
README_TEXT = ("# Results\n\n<!-- BEGIN:results -->\nstale\n<!-- END -->\n\n"
               "<!-- BEGIN:tests -->\nstale\n<!-- END -->\n")
EVAL_TEXT = ("# Evaluation\n\nTerms: case-level, row-level, step-level, field-level, "
             "sequence accuracy, strategies, failures, improvements.\n\n"
             "<!-- BEGIN:metrics -->\n<!-- END -->\n\n<!-- BEGIN:custom-cases -->\n<!-- END -->\n")
USAGE_TEXT = "# Usage\n\n<!-- BEGIN:usage -->\n<!-- END -->\n"


def _json_round_trip(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def scorer_fixture() -> Dict[str, Any]:
    """Scorer JSON of a two-case run where the prediction drops one step."""
    gold = {
        "case_1": CaseResult("case_1", "INCOMPLETE", (Step(1, *FINDING), Step(2, *REMEDIATE))),
        "case_2": CaseResult("case_2", "NOT_APPLICABLE", ()),
    }
    pred = {"case_1": CaseResult("case_1", "INCOMPLETE", (Step(1, *FINDING),)), "case_2": gold["case_2"]}
    return _json_round_trip(dataclasses.asdict(scoring.score(gold, pred, ceilings=FIXTURE_CEILINGS)))


def meter_fixture(prices: Sequence[ModelPrice] = DEFAULT_PRICES,
                  models: Sequence[str] = (OPUS, HAIKU)) -> Dict[str, Any]:
    """Meter snapshot of one live call and one replayed call per model, at the release request count."""
    meter = usage.UsageMeter(prices)
    for model in models:
        request = LLMRequest(model=model, system="s", messages=(("user", "text"),),
                             max_tokens=1024, prompt_version="v1")
        response = LLMResponse(text="{}", input_tokens=1200, output_tokens=300, model=model,
                               cached=False, cache_creation_tokens=400, cache_read_tokens=900)
        meter.record_live(request, response)
        meter.record_replay(request, response)
    return _json_round_trip(usage.snapshot(meter, requests=EVAL_REQUEST_COUNT))


def custom_fixture() -> List[Dict[str, str]]:
    return [
        {"id": "C1", "title": "historical email", "rationale": "Old address still searchable.",
         "input": "email: old@example.test", "expected": "INCOMPLETE", "actual": "INCOMPLETE"},
        {"id": "C2", "title": "negated request", "rationale": "Refusal must not delete.",
         "input": "Do not delete ```my``` data", "expected": "NOT_APPLICABLE",
         "actual": "NOT_APPLICABLE"},
        {"id": "C3", "title": "time travel", "rationale": "Later evidence is ignored.",
         "input": "file at audit_at", "expected": "COMPLETE", "actual": "COMPLETE"},
    ]


def sources_fixture() -> rr.Sources:
    return rr.Sources(scorer=scorer_fixture(), meter=meter_fixture(),
                      custom_cases=custom_fixture(), test_count=TEST_COUNT,
                      texts={"strategies": "## Strategy comparison\n\n| S0 | S1 |\n",
                             "ablation": "## Ablation variants\n\n| default |\n"})


class FixtureCase(unittest.TestCase):
    """Writes metrics JSON and three stale report files into a temporary directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.metrics = self.root / "metrics"
        self.metrics.mkdir()
        self.sources = sources_fixture()
        self.write_json(rr.SCORER_FILE, self.sources.scorer)
        self.write_json(rr.METER_FILE, self.sources.meter)
        self.write_json(rr.CUSTOM_FILE, self.sources.custom_cases)
        for name, file in rr.TEXT_FILES.items():
            (self.metrics / file).write_text(self.sources.texts[name], encoding="utf-8")
        self.paths = {"readme": self.root / "README.md", "eval": self.root / "evaluation_report.md",
                      "usage": self.root / "usage_report.md"}
        self.paths["readme"].write_text(README_TEXT, encoding="utf-8")
        self.paths["eval"].write_text(EVAL_TEXT, encoding="utf-8")
        self.paths["usage"].write_text(USAGE_TEXT, encoding="utf-8")
        self.targets = (
            rr.Target(self.paths["readme"], ("results", "tests")),
            rr.Target(self.paths["eval"], ("metrics", "custom-cases"), rr.EVAL_TERMS),
            rr.Target(self.paths["usage"], ("usage",), rr.USAGE_TERMS),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_json(self, name: str, value: Any) -> None:
        (self.metrics / name).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def read(self, key: str) -> str:
        return self.paths[key].read_text(encoding="utf-8")

    def write(self, key: str, text: str) -> None:
        self.paths[key].write_text(text, encoding="utf-8")

    def run_cli(self, *extra: str) -> int:
        argv = ["--metrics-dir", str(self.metrics), *extra]
        with mock.patch.object(rr, "TARGETS", self.targets), \
                mock.patch.object(rr, "count_tests", return_value=TEST_COUNT), \
                mock.patch.object(rr.logging, "basicConfig"), \
                contextlib.redirect_stdout(io.StringIO()):
            return rr.main(argv)


class FillAndCheckTests(FixtureCase):
    def test_fill_then_check_passes(self) -> None:
        self.assertEqual(self.run_cli(), rr.EXIT_OK)
        self.assertIn("Unit tests: %d" % TEST_COUNT, self.read("readme"))
        self.assertEqual(self.run_cli("--check"), rr.EXIT_OK)

    def test_fill_writes_usage_and_metric_numbers(self) -> None:
        self.run_cli()
        usage_text = self.read("usage")
        overall = self.sources.meter["overall"]
        self.assertIn("Models: %s, %s." % (HAIKU, OPUS), usage_text)
        self.assertIn("`%s`" % LIVE_SDK_REQUIREMENT, usage_text)
        for kind in ("replayed", "live"):
            self.assertIn("| %s | %d | %s |" % (kind, EVAL_REQUEST_COUNT,
                                                "%.1f" % overall[kind]["tokens_per_request"]), usage_text)
        self.assertIn("| **overall** | 2 | 2400 | 800 | 1800 | 600 | 5600 |", usage_text)
        self.assertIn("### Grader emulation (2 cases)", self.read("eval"))
        self.assertIn("Sample status accuracy, G1 (2 cases) | 1.0000", self.read("readme"))

    def test_check_flags_hand_edited_number_without_writing(self) -> None:
        self.run_cli()
        edited = self.read("usage").replace("| %d | " % EVAL_REQUEST_COUNT,
                                            "| %d | " % (EVAL_REQUEST_COUNT - 1), 1)
        self.write("usage", edited)
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli("--check"), rr.EXIT_CHECK)
        self.assertEqual(self.read("usage"), edited)

    def test_fill_restores_hand_edited_number(self) -> None:
        self.run_cli()
        self.write("eval", self.read("eval").replace("| G1 |", "| G9 |", 1))
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli("--check"), rr.EXIT_CHECK)
        self.assertEqual(self.run_cli(), rr.EXIT_OK)
        self.assertEqual(self.run_cli("--check"), rr.EXIT_OK)


class ProblemTests(FixtureCase):
    def test_arithmetic_drift_blocks_fill(self) -> None:
        self.sources.meter["overall"]["live"]["total_tokens"] += 1
        self.write_json(rr.METER_FILE, self.sources.meter)
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli(), rr.EXIT_CHECK)
        self.assertEqual(self.read("readme"), README_TEXT)
        self.assertEqual(self.read("usage"), USAGE_TEXT)

    def test_missing_marker_is_input_error(self) -> None:
        self.write("usage", "# Usage without markers\n")
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli("--check"), rr.EXIT_INPUT)

    def test_unknown_marker_is_input_error(self) -> None:
        self.write("readme", README_TEXT + "\n<!-- BEGIN:nonsense -->\n<!-- END -->\n")
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli("--check"), rr.EXIT_INPUT)

    def test_missing_metrics_file_is_input_error(self) -> None:
        (self.metrics / rr.SCORER_FILE).unlink()
        with self.assertLogs(rr.LOG.name, "ERROR"):
            self.assertEqual(self.run_cli(), rr.EXIT_INPUT)


class ArithmeticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scorer = scorer_fixture()
        self.meter = meter_fixture()
        self.custom = custom_fixture()

    def test_consistent_sources_pass(self) -> None:
        problems = rr.arithmetic_problems(
            rr.Sources(self.scorer, self.meter, self.custom, TEST_COUNT), EVAL_REQUEST_COUNT)
        self.assertEqual(problems, [])

    def test_request_count_must_be_the_release_count(self) -> None:
        problems = rr.meter_problems(self.meter, EVAL_REQUEST_COUNT - 1)
        self.assertTrue(any("covers" in problem for problem in problems))

    def test_average_must_be_total_over_request_count(self) -> None:
        self.meter["overall"]["live"]["tokens_per_request"] += 1
        problems = rr.meter_problems(self.meter, EVAL_REQUEST_COUNT)
        self.assertTrue(any("tokens per request" in p for p in problems))

    def test_cost_must_equal_tokens_times_prices(self) -> None:
        self.meter["models"][OPUS]["replayed"]["cost_sync"] += 0.5
        self.assertTrue(any("cost" in p for p in rr.meter_problems(self.meter, EVAL_REQUEST_COUNT)))

    def test_model_total_must_equal_its_tallies(self) -> None:
        self.meter["models"][OPUS]["live"]["total_tokens"] += 1
        self.assertTrue(any("total tokens" in p for p in rr.meter_problems(self.meter, EVAL_REQUEST_COUNT)))

    def test_overall_must_sum_the_models(self) -> None:
        self.meter["overall"]["live"]["input_tokens"] += 1
        self.assertTrue(any("overall live tallies" in p for p in rr.meter_problems(self.meter, EVAL_REQUEST_COUNT)))

    def test_a_meter_without_any_model_call_is_refused(self) -> None:
        empty = _json_round_trip(usage.snapshot(usage.UsageMeter(DEFAULT_PRICES), EVAL_REQUEST_COUNT))
        self.assertTrue(any("no model call" in p for p in rr.meter_problems(empty, EVAL_REQUEST_COUNT)))

    def test_replayed_only_usage_is_reported_not_zero(self) -> None:
        meter = usage.UsageMeter(DEFAULT_PRICES)
        request = LLMRequest(model=OPUS, system="s", messages=(("user", "t"),), max_tokens=1, prompt_version="v1")
        meter.record_replay(request, LLMResponse(text="{}", input_tokens=1000, output_tokens=100, model=OPUS,
                                                 cached=True))
        snap = _json_round_trip(usage.snapshot(meter, EVAL_REQUEST_COUNT))
        self.assertEqual(rr.meter_problems(snap, EVAL_REQUEST_COUNT), [])
        text = rr.usage_block(rr.Sources(self.scorer, snap, self.custom, TEST_COUNT))
        self.assertIn("| %s | 1 | 1000 | 0 | 0 | 100 | 1100 |" % OPUS, text)
        self.assertEqual(snap["overall"]["live"]["calls"], 0)
        self.assertEqual(snap["overall"]["replayed"]["calls"], 1)

    def test_summary_states_the_final_run_and_the_cache_fill_separately(self) -> None:
        meter = usage.UsageMeter(DEFAULT_PRICES)
        request = LLMRequest(model=OPUS, system="s", messages=(("user", "t"),), max_tokens=1, prompt_version="v1")
        meter.record_replay(request, LLMResponse(text="{}", input_tokens=1000, output_tokens=100, model=OPUS,
                                                 cached=True))
        snap = _json_round_trip(usage.snapshot(meter, EVAL_REQUEST_COUNT))
        text = rr.usage_block(rr.Sources(self.scorer, snap, self.custom, TEST_COUNT))
        self.assertIn("The final run made 0 live API call(s) and used 0 live tokens", text)
        self.assertIn("filled the cache billed 1 calls and 1100 tokens (1000 input, 0 cache write, 0 cache read, "
                      "100 output)", text)

    def test_unpriced_model_is_allowed(self) -> None:
        meter = meter_fixture(prices=(DEFAULT_PRICES[0],), models=(OPUS, UNPRICED))
        self.assertEqual(rr.meter_problems(meter, EVAL_REQUEST_COUNT), [])
        self.assertIsNone(meter["overall"]["live"]["cost_sync"])
        self.assertIsNone(meter["overall"]["replayed"]["cost_sync"])
        self.assertIn("unpriced", rr.usage_block(rr.Sources(self.scorer, meter, self.custom, TEST_COUNT)))

    def test_composite_must_be_the_weighted_sum(self) -> None:
        self.scorer["raw"]["G7"] += 0.25
        self.assertTrue(any("G7" in p for p in rr.scorer_problems(self.scorer)))

    def test_normalized_must_be_raw_over_ceiling(self) -> None:
        self.scorer["normalized"]["G2"] += 0.1
        self.assertTrue(any(p.startswith("G2") for p in rr.scorer_problems(self.scorer)))

    def test_custom_cases_must_meet_the_minimum(self) -> None:
        problems = rr.custom_problems(self.custom[:2])
        self.assertTrue(any("at least" in p for p in problems))

    def test_custom_case_must_reproduce_expected_output(self) -> None:
        self.custom[0]["actual"] = "COMPLETE"
        self.assertEqual(rr.custom_problems(self.custom),
                         ["custom case C1: actual output differs from expected"])

    def test_missing_terms_are_reported(self) -> None:
        target = rr.Target(Path("evaluation_report.md"), (), rr.EVAL_TERMS)
        self.assertEqual(len(rr.term_problems("nothing relevant", target)), len(rr.EVAL_TERMS))


class BlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = sources_fixture()

    def test_custom_fence_outgrows_inner_backticks(self) -> None:
        self.assertIn("````text", rr.custom_block(self.sources))

    def test_text_blocks_carry_the_cli_markdown(self) -> None:
        self.assertEqual(rr.strategies_block(self.sources), "## Strategy comparison\n\n| S0 | S1 |\n")
        self.assertIn("## Ablation variants", rr.ablation_block(self.sources))

    def test_metrics_block_names_every_grader(self) -> None:
        block = rr.metrics_block(self.sources)
        for _, name in rr.GRADERS:
            self.assertIn(name, block)

    def test_fill_blocks_is_idempotent(self) -> None:
        blocks = {"tests": rr.tests_block(self.sources)}
        document = "<!-- BEGIN:tests -->\n<!-- END -->\n"
        once = rr.fill_blocks(document, blocks, Path("README.md"))
        self.assertEqual(rr.fill_blocks(once, blocks, Path("README.md")), once)

    def test_fill_blocks_rejects_unknown_and_missing_markers(self) -> None:
        with self.assertRaises(rr.ReportError):
            rr.fill_blocks("<!-- BEGIN:other -->\n<!-- END -->\n", {"tests": ""}, Path("x.md"))
        with self.assertRaises(rr.ReportError):
            rr.fill_blocks("no markers\n", {"tests": ""}, Path("x.md"))


class TestCountTests(unittest.TestCase):
    def test_count_tests_discovers_the_suite(self) -> None:
        self.assertGreater(rr.count_tests(), 0)


if __name__ == "__main__":
    unittest.main()
