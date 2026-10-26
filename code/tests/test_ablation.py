"""Tests for evaluation.ablation (SPEC L5, L6, V3, V5, N7, 12).

The variants run on a custom-case mini dataset (a retained legal hold, an exposed tombstone),
offline, in a temporary directory; the real dataset is only used to read variant names.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import tempfile
import unittest
from pathlib import Path
from typing import Dict

from evaluation import ablation, custom_cases
from evaluation import main as evaluation_main
from ghostaudit.config import Config, Flags
from ghostaudit.dataset import DatasetReader
from tests.dataset_guard import needs_dataset

DEFAULT_TABLE_LABEL = "default (default)"


class VariantListTests(unittest.TestCase):
    def test_default_is_first_and_every_flag_is_flipped_once(self) -> None:
        variants = ablation.ablation_variants(Config())
        self.assertEqual(variants[0].name, ablation.DEFAULT_NAME)
        flipped = [variant.flag for variant in variants if variant.flag in {f.name for f in dataclasses.fields(Flags)}]
        self.assertEqual(sorted(flipped), sorted(field.name for field in dataclasses.fields(Flags)))

    def test_flipped_variant_differs_from_default_in_exactly_one_flag(self) -> None:
        base = Config()
        for variant in ablation.ablation_variants(base)[1:]:
            changed = [f.name for f in dataclasses.fields(Flags)
                       if getattr(variant.config.flags, f.name) != getattr(base.flags, f.name)]
            self.assertEqual(changed, [variant.flag])

    def test_agent_variants_are_off_then_on(self) -> None:
        variants = ablation.agent_variants(Config())
        self.assertEqual([variant.name for variant in variants], [ablation.AGENT_REFERENCE, "agent=on"])
        self.assertEqual([variant.config.agent for variant in variants], ["off", "on"])
        self.assertEqual({variant.config.llm_mode for variant in variants}, {"cache"})

    def test_strategies_are_s0_s1_s2_with_distinct_models(self) -> None:
        variants = ablation.strategy_variants(Config())
        self.assertEqual([variant.name for variant in variants], ["S0", "S1", "S2"])
        self.assertEqual(variants[0].config.llm_mode, "off")
        self.assertNotEqual(variants[1].config.intent_model, variants[2].config.intent_model)
        self.assertEqual(variants[1].config.media_model, variants[2].config.media_model)


class MiniDatasetRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        root = Path(cls._scratch.name)
        custom_cases.write_dataset(custom_cases.case_c4().dataset, root / "dataset")
        cls.config = dataclasses.replace(
            Config(), dataset_dir=root / "dataset", llm_mode="off",
            cache_dir=root / "cache", diag_dir=root / "diag")
        cls.reader = DatasetReader(cls.config.dataset_dir)
        cls.outcomes = ablation.run_variants(ablation.ablation_variants(cls.config), cls.reader, {})
        cls.by_name: Dict[str, ablation.Outcome] = {outcome.variant.name: outcome for outcome in cls.outcomes}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def test_default_row_differs_from_nothing(self) -> None:
        default = self.outcomes[0]
        self.assertEqual(ablation.differing(default, default), 0)

    def test_dropping_legal_hold_verification_changes_exactly_this_case(self) -> None:
        off = self.by_name["verify_legal_holds=off"]
        self.assertEqual(ablation.differing(off, self.outcomes[0]), 1)
        before = {step.operation for case in self.outcomes[0].result.eval_results for step in case.steps}
        self.assertIn("VERIFY_RECORD_PRESENT", before)

    def test_rendered_table_names_the_default_and_every_variant(self) -> None:
        text = ablation.render_ablation(self.outcomes)
        self.assertIn(DEFAULT_TABLE_LABEL, text)
        for outcome in self.outcomes[1:]:
            self.assertIn("| %s |" % outcome.variant.name, text)
        self.assertIn("## Assumption ledger", text)

    def test_ledger_has_one_row_per_flag(self) -> None:
        rows = ablation.assumption_ledger(self.outcomes)
        self.assertEqual([row.flag for row in rows], [field.name for field in dataclasses.fields(Flags)])
        legal = next(row for row in rows if row.flag == "verify_legal_holds")
        self.assertEqual(legal.changed, "off: 1")

    def test_strategies_run_offline_and_count_cache_misses(self) -> None:
        outcomes = ablation.run_variants(ablation.strategy_variants(self.config), self.reader, {})
        self.assertEqual([outcome.variant.name for outcome in outcomes], ["S0", "S1", "S2"])
        text = ablation.render_strategies(outcomes)
        self.assertIn("## Strategy comparison", text)
        self.assertEqual(ablation.differing(outcomes[1], outcomes[1]), 0)

    def test_agent_ablation_without_cached_responses_changes_nothing(self) -> None:
        outcomes = ablation.run_variants(ablation.agent_variants(
            dataclasses.replace(self.config, llm_mode="cache")), self.reader, {})
        self.assertEqual(ablation.differing(outcomes[1], outcomes[0]), 0)
        text = ablation.render_agent(outcomes)
        self.assertIn("## Agent ablation", text)
        self.assertIn("agent=on", text)

    def test_live_mode_is_refused(self) -> None:
        variant = ablation.Variant("live", "", dataclasses.replace(self.config, llm_mode="live"))
        with self.assertRaises(ValueError):
            ablation.run_variant(variant, self.reader, {})


class CommandLineTests(unittest.TestCase):
    @needs_dataset
    def test_ablate_flag_prints_the_tables(self) -> None:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = evaluation_main.main(["--ablate"])
        self.assertEqual(code, evaluation_main.EXIT_OK)
        self.assertIn(DEFAULT_TABLE_LABEL, captured.getvalue())
        self.assertIn("never_mix=off", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
