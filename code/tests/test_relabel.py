"""Override-ban relabeling test.

If the output depended on a hard-coded id, an eval-specific constant or an id's position, a
renamed copy of the dataset would answer differently. Two copies are run offline:

* a monotone relabel (every id number gets a trailing zero, all times move by a constant that is a
  multiple of an hour, emails and hashes stay) must give the baseline answer with the same relabel
  applied, byte for byte, except for cases that rest on the disclosed `account_00N` convention;
* a non-monotone relabel (id numbers mirrored) may change only cases that carry a FIFO or
  convention assumption in the diagnostics, and only in which of two symmetric candidates they
  name: the answer is compared as a set of steps per case.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

from tests import datacopy
from tests.dataset_guard import needs_dataset

SHIFT_SECONDS = 41 * 86400 + 3 * 3600  # a whole number of hours, so minute residues are unchanged
CONVENTION_MARKER = "convention"
FIFO_MARKER = "FIFO"

Rows = Dict[str, Tuple[str, str]]


def steps_as_set(steps_json: str) -> List[str]:
    """Steps of one case without their numbering, as sorted canonical strings."""
    return sorted(json.dumps({k: v for k, v in step.items() if k != "step_no"}, sort_keys=True)
                  for step in json.loads(steps_json))


@needs_dataset
class RelabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        root = Path(cls._scratch.name)
        source = datacopy.default_dataset()
        cls.baseline, cls.baseline_diag = datacopy.run_offline(source, root / "base")
        for name, transform in (
            ("mono", datacopy.compose(datacopy.append_zero, datacopy.shift_times(SHIFT_SECONDS))),
            ("rev", datacopy.compose(datacopy.reverse_numbers, datacopy.shift_times(SHIFT_SECONDS))),
        ):
            target = root / (name + "_dataset")
            datacopy.copy_dataset(source, target, transform)
            rows, diag = datacopy.run_offline(target, root / name)
            setattr(cls, name, rows)
            setattr(cls, name + "_diag", diag)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def convention_cases(self) -> FrozenSet[str]:
        return frozenset(datacopy.flagged_cases(self.baseline_diag, CONVENTION_MARKER)
                         + datacopy.flagged_cases(self.mono_diag, CONVENTION_MARKER)
                         + datacopy.flagged_cases(self.rev_diag, CONVENTION_MARKER))

    def test_every_case_is_answered_in_each_copy(self) -> None:
        self.assertEqual(len(self.baseline), 518)
        self.assertEqual(sorted(self.mono), sorted(self.baseline))
        self.assertEqual(sorted(self.rev), sorted(self.baseline))

    def test_monotone_relabel_gives_the_relabeled_baseline(self) -> None:
        exempt = self.convention_cases()
        different = [case_id for case_id, (status, steps) in sorted(self.baseline.items())
                     if case_id not in exempt
                     and self.mono[case_id] != (status, datacopy.append_zero(steps))]
        self.assertEqual(different, [])

    def test_no_id_convention_is_assumed_in_any_copy(self) -> None:
        self.assertEqual(self.convention_cases(), frozenset())

    def test_non_monotone_relabel_changes_only_flagged_cases(self) -> None:
        allowed = (self.convention_cases()
                   | frozenset(datacopy.flagged_cases(self.baseline_diag, FIFO_MARKER))
                   | frozenset(datacopy.flagged_cases(self.rev_diag, FIFO_MARKER)))
        different = []
        for case_id, (status, steps) in sorted(self.baseline.items()):
            mirrored = datacopy.reverse_numbers(steps)
            if status != self.rev[case_id][0] or steps_as_set(mirrored) != steps_as_set(self.rev[case_id][1]):
                different.append(case_id)
        self.assertEqual([case_id for case_id in different if case_id not in allowed], [])

    def test_a_partial_relabel_is_detected(self) -> None:
        """Negative control: relabeling the CSVs but not the evidence must change many answers."""
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "dataset"
            datacopy.copy_dataset(datacopy.default_dataset(), target, datacopy.append_zero, frozenset({".csv"}))
            rows, _diag = datacopy.run_offline(target, Path(scratch) / "run", tolerate_violations=True)
        changed = [case_id for case_id, (status, steps) in self.baseline.items()
                   if rows[case_id] != (status, datacopy.append_zero(steps))]
        self.assertGreater(len(changed), 100)

    def test_status_never_depends_on_labels(self) -> None:
        changed = [case_id for case_id, (status, _steps) in self.baseline.items()
                   if self.rev[case_id][0] != status and case_id not in self.convention_cases()]
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
