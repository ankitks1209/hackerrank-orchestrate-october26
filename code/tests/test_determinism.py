"""Determinism and latency of the full run (SPEC N1, N2).

`main.py` runs in subprocesses under two `PYTHONHASHSEED` values and in two LLM modes
(`cache` replays stored responses, `off` uses no model). The written `output.csv` must be
byte-identical across seeds, and so must the diagnostics once the wall-clock timing rows
are removed. Every invocation passes `--out` and `--diag` under a fresh temporary
directory, so the submission `output.csv` is never touched. The `cache` run must finish
within the SPEC N2 budget; its stage timings are printed to stderr.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Tuple

from ghostaudit.config import API_KEY_ENV, EVAL_REQUEST_COUNT, REPO_ROOT, Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.diagnostics import DIAGNOSTICS_NAME
from tests.dataset_guard import needs_dataset

MAIN = REPO_ROOT / "code" / "main.py"
SUBMISSION = REPO_ROOT / "output.csv"
HASH_SEEDS = ("0", "4242")
MODES = ("cache", "off")
WALL_LIMIT_S = 5.0  # SPEC N2
TIMING_ROW = re.compile(r"(?m)^\| [^|]+ \| \d+\.\d+ \|\n")
TIMING_SECTION = re.compile(r"## Stage timings\n\n(.*?)\n\n", re.S)
OUTPUT_HEADER = ["case_id", "deletion_status", "steps_json"]


class RunOutcome(NamedTuple):
    code: int
    output: bytes
    diagnostics: str
    seconds: float


def run_main(mode: str, seed: str, workdir: Path) -> RunOutcome:
    """One `main.py` run in a subprocess; all artifacts go under `workdir`."""
    env = dict(os.environ)
    env.pop(API_KEY_ENV, None)
    env["PYTHONHASHSEED"] = seed
    out, diag = workdir / "output.csv", workdir / "diag"
    started = time.perf_counter()
    done = subprocess.run(
        [sys.executable, str(MAIN), "--llm", mode, "--out", str(out), "--diag", str(diag)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    seconds = time.perf_counter() - started
    if done.returncode != 0:
        raise AssertionError("main.py exited %d: %s" % (done.returncode, done.stderr[-2000:]))
    return RunOutcome(
        done.returncode, out.read_bytes(), (diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8"), seconds
    )


def snapshot(path: Path) -> Optional[Tuple[int, int]]:
    """(size, mtime in ns) of a file, or None when it does not exist."""
    if not path.exists():
        return None
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def without_timings(diagnostics: str) -> str:
    return TIMING_ROW.sub("", diagnostics)


@needs_dataset
class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.submission_before = snapshot(SUBMISSION)
        cls._root = Path(tempfile.mkdtemp(prefix="ghostaudit_determinism_"))
        cls.runs: Dict[Tuple[str, str], RunOutcome] = {}
        for mode in MODES:
            for seed in HASH_SEEDS:
                workdir = cls._root / ("%s_%s" % (mode, seed))
                workdir.mkdir()
                cls.runs[(mode, seed)] = run_main(mode, seed, workdir)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._root, ignore_errors=True)

    def test_output_is_byte_identical_across_hash_seeds(self) -> None:
        for mode in MODES:
            first, second = (self.runs[(mode, seed)].output for seed in HASH_SEEDS)
            self.assertEqual(first, second, "output differs across PYTHONHASHSEED in mode %s" % mode)

    def test_diagnostics_are_identical_apart_from_timings(self) -> None:
        for mode in MODES:
            first, second = (without_timings(self.runs[(mode, seed)].diagnostics) for seed in HASH_SEEDS)
            self.assertEqual(first, second, "diagnostics differ across PYTHONHASHSEED in mode %s" % mode)

    def test_output_has_one_row_per_evaluation_request(self) -> None:
        expected = [req.case_id for req in DatasetReader(Config().dataset_dir).requests() if not req.is_sample]
        for key, outcome in sorted(self.runs.items()):
            rows = list(csv.reader(io.StringIO(outcome.output.decode("utf-8"), newline="")))
            self.assertEqual(rows[0], OUTPUT_HEADER, key)
            self.assertEqual(len(rows) - 1, EVAL_REQUEST_COUNT, key)
            self.assertEqual(sorted(row[0] for row in rows[1:]), sorted(expected), key)

    def test_cache_run_meets_the_latency_budget(self) -> None:
        for seed in HASH_SEEDS:
            outcome = self.runs[("cache", seed)]
            section = TIMING_SECTION.search(outcome.diagnostics)
            sys.stderr.write("\n[--llm cache, PYTHONHASHSEED=%s] wall %.2f s\n%s\n" % (
                seed, outcome.seconds, section.group(1) if section else "(no timing section)"))
            self.assertLess(outcome.seconds, WALL_LIMIT_S)

    def test_repository_output_is_untouched(self) -> None:
        self.assertEqual(snapshot(SUBMISSION), self.submission_before)


if __name__ == "__main__":
    unittest.main()
