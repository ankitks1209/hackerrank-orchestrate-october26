"""Override-ban narrow-rule review.

A switch whose flip changes at most two evaluation rows and no public-sample row is a narrow
rule: it exists for a handful of cases and may be an override in disguise. Each narrow rule must
be justified in `docs/DECISIONS.md` (the flag name appears there). The configuration holds no
window or offset tuned to the data.
"""
from __future__ import annotations

import logging
import re
import unittest
from typing import List

from evaluation import ablation
from ghostaudit.config import Config
from ghostaudit.dataset import DatasetReader
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

NARROW_EVAL_ROWS = 2
CONFIG_PATH = Config().cache_dir.parent / "config.py"
DECISIONS_PATH = CONFIG_PATH.parent.parent / "docs" / "DECISIONS.md"
WINDOW_ASSIGNMENT = re.compile(r"^    (\w+_window): Tuple", re.MULTILINE)


def narrow_flags(config: Config) -> List[str]:
    """Flags whose flip leaves the samples as they are and changes at most NARROW_EVAL_ROWS rows."""
    reader = DatasetReader(config.dataset_dir)
    gold = GoldReader().cases()
    package_logger = logging.getLogger("ghostaudit")
    previous = package_logger.level
    package_logger.setLevel(logging.CRITICAL)
    try:
        outcomes = ablation.run_variants(ablation.ablation_variants(config), reader, gold)
    finally:
        package_logger.setLevel(previous)
    reference = outcomes[0]
    narrow = []
    for outcome in outcomes[1:]:
        same_samples = (outcome.report.inexact_cases == reference.report.inexact_cases
                        and outcome.report.status_mismatches == reference.report.status_mismatches)
        if same_samples and ablation.differing(outcome, reference) <= NARROW_EVAL_ROWS:
            narrow.append(outcome.variant.flag)
    return narrow


@needs_dataset
class NarrowRuleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.flags = narrow_flags(Config())

    def test_every_narrow_rule_is_justified_in_the_decisions(self) -> None:
        decisions = DECISIONS_PATH.read_text(encoding="utf-8")
        self.assertEqual([flag for flag in self.flags if flag not in decisions], [])

    def test_the_broad_switches_are_not_narrow(self) -> None:
        """The review is not vacuous: switches that move many rows must stay out of its list."""
        for flag in ("fifo_pairing", "never_mix"):
            self.assertNotIn(flag, self.flags)

    def test_config_holds_no_tuned_window_or_offset(self) -> None:
        source = CONFIG_PATH.read_text(encoding="utf-8")
        self.assertEqual(WINDOW_ASSIGNMENT.findall(source), [])
        for word in ("window_offset_s", "ABLATION_WINDOW_OFFSET_S", "owner_cut"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
