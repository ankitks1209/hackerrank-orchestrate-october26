"""Tests for devtools.confidence (T40; LOCAL_EVALUATION_STRATEGY P4, P6).

Smoke tests run the ablation variants on custom-case mini datasets; the ledger kept in
`docs/DECISIONS.md` is checked for completeness without re-running the whole dataset (the release
gate runs `confidence.py --check` for that).
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from devtools import confidence
from devtools.audit import sampler
from evaluation import ablation, custom_cases
from ghostaudit.config import Config, Flags
from ghostaudit.dataset import DatasetReader
from ghostaudit.pipeline import RunResult


class MiniRun:
    """The ablation variants over one custom-case dataset, run once."""

    def __init__(self, case: custom_cases.CustomCase) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        custom_cases.write_dataset(case.dataset, root / "dataset")
        config = dataclasses.replace(Config(), dataset_dir=root / "dataset", llm_mode="off",
                                     cache_dir=root / "cache", diag_dir=root / "diag")
        self.outcomes = ablation.run_variants(ablation.ablation_variants(config), DatasetReader(config.dataset_dir), {})
        self.result: RunResult = self.outcomes[0].result

    def close(self) -> None:
        self.scratch.cleanup()


class TierTests(unittest.TestCase):
    def test_a_unique_owner_linked_case_with_audit_is_high_and_missing_audit_is_low(self) -> None:
        run = MiniRun(custom_cases.case_c4())
        try:
            found = confidence.tiers(run.result)
            self.assertEqual([(item.case_id, item.tier) for item in found], [("synth_c4", confidence.HIGH)])
        finally:
            run.close()
        run = MiniRun(custom_cases.case_c5())
        try:
            (item,) = confidence.tiers(run.result)
            self.assertEqual((item.tier, item.reasons), (confidence.LOW, ("no audit-record step",)))
        finally:
            run.close()

    def test_a_request_that_is_not_a_deletion_is_high(self) -> None:
        run = MiniRun(custom_cases.case_c2())
        try:
            (item,) = confidence.tiers(run.result)
            self.assertEqual((item.tier, item.reasons), (confidence.HIGH, ()))
        finally:
            run.close()


class FragilityAndLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mini = MiniRun(custom_cases.case_c4())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.mini.close()

    def test_flipping_the_legal_hold_flag_makes_the_case_fragile(self) -> None:
        fragile = confidence.fragility(self.mini.outcomes)
        self.assertEqual(fragile, {"synth_c4": ("verify_legal_holds=off",)})

    def test_ledger_has_one_entry_per_flag(self) -> None:
        entries = confidence.ledger(self.mini.outcomes)
        self.assertEqual([e.flag for e in entries], [f.name for f in dataclasses.fields(Flags)])
        legal = next(e for e in entries if e.flag == "verify_legal_holds")
        self.assertEqual((legal.exposure, legal.rule_class), ("off: 1", confidence.INFERRED))

    def test_classes_follow_the_sample_support(self) -> None:
        make = lambda support: confidence.LedgerEntry("f", "True", support, 0, "off: 0", "-")
        self.assertEqual([make(n).rule_class for n in (0, 1, 2, 9)],
                         [confidence.INFERRED, confidence.WEAK, confidence.EVIDENCED, confidence.EVIDENCED])

    def test_rendered_table_has_a_row_per_entry(self) -> None:
        text = confidence.render_ledger(confidence.ledger(self.mini.outcomes))
        self.assertEqual(len(text.splitlines()), 2 + len(dataclasses.fields(Flags)))

    def test_export_feeds_the_audit_sampler(self) -> None:
        tiers = confidence.tiers(self.mini.result)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "tiers.json"
            confidence.export(tiers, confidence.fragility(self.mini.outcomes), path)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sampler.read_tiers(path), {"synth_c4": confidence.HIGH})
        self.assertEqual(sorted(document), ["fragile", "reasons", "tiers"])
        self.assertEqual(document["fragile"], {"synth_c4": ["verify_legal_holds=off"]})


class DecisionsLedgerTests(unittest.TestCase):
    def table(self) -> str:
        text = confidence.DECISIONS_PATH.read_text(encoding="utf-8")
        block = confidence.block_of(text)
        self.assertIsNotNone(block)
        return block or ""

    def test_every_flag_has_a_row(self) -> None:
        table = self.table()
        for name in [f.name for f in dataclasses.fields(Flags)]:
            self.assertIn("| `%s` |" % name, table)

    def test_every_row_has_a_class(self) -> None:
        rows = [line for line in self.table().splitlines()[2:]]
        classes = {line.split("|")[3].strip() for line in rows}
        self.assertTrue(classes <= {confidence.EVIDENCED, confidence.WEAK, confidence.INFERRED})

    def test_block_markers(self) -> None:
        self.assertIsNone(confidence.block_of("no markers"))
        self.assertEqual(confidence.block_of("a %s\n x \n%s b" % (confidence.LEDGER_BEGIN, confidence.LEDGER_END)), "x")


if __name__ == "__main__":
    unittest.main()
