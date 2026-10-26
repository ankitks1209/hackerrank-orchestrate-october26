"""Tests-only skip guard for the tests that read the participant dataset (AGENTS 6.9).

The submitted `code.zip` ships without `dataset/`. A judge who unpacks it and runs the suite
must see the dataset-backed tests skipped with a reason, not failed; the synthetic tests still
run. With the dataset in place (the development tree, the clean room with `--dataset`) nothing
is skipped.
"""
from __future__ import annotations

import unittest

from ghostaudit.config import Config
from ghostaudit.dataset import EVIDENCE_DIR, REQUIRED_CSVS

DATASET_DIR = Config().dataset_dir
GOLD_NAME = "sample_output.csv"
SKIP_REASON = "dataset/ is not present (the submission archive ships without it)"
HAS_DATASET = (DATASET_DIR / EVIDENCE_DIR).is_dir() and all(
    (DATASET_DIR / name).is_file() for name in REQUIRED_CSVS + (GOLD_NAME,)
)

needs_dataset = unittest.skipUnless(HAS_DATASET, SKIP_REASON)
