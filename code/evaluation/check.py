"""The shipped quality gate: `python3 -m evaluation check` (from `code/`, or `ghostaudit-eval check`).

Runs the solver offline, twice, with different hash seeds, and verifies what a reviewer needs:

* format: the exact header, LF line endings, one row per evaluation request in natural case order;
* contract: `ghostaudit.contract.validate_file` over the written `output.csv` (status rules,
  step shape, operation order, citations bounded by each case's `audit_at`);
* determinism: the two runs write byte-identical `output.csv` and sample predictions;
* invariants: the label-free verification of `evaluation.verify_report` has no hard failure;
* sample score: status accuracy, row-exact cases and step F1 against the public gold, reported
  (and compared with `--min-status` / `--min-f1` when given).

No model is called: the default `--llm cache` replays stored responses, and `--llm off` uses none.
Exit codes: 0 every check passed; 1 a check failed; 2 the inputs are unusable.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from evaluation import redundancy, verify_report, verify_steps
from evaluation.gold import SAMPLE_OUTPUT, GoldReader
from evaluation.raw_dataset import load_dataset
from evaluation.scoring import score
from ghostaudit.config import EVAL_REQUEST_COUNT, LLM_MODES, REPO_ROOT
from ghostaudit.contract import Citations, validate_file
from ghostaudit.dataset import DatasetReader

CODE_DIR = Path(__file__).resolve().parents[1]
HASH_SEEDS = ("0", "4242")  # two PYTHONHASHSEED values; the output must not depend on them
OUTPUT_HEADER = b"case_id,deletion_status,steps_json\n"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INPUT = 2
STDERR_TAIL = 2000


@dataclass(frozen=True)
class Check:
    """One named check: whether it passed and what it found."""

    name: str
    passed: bool
    detail: str


def _run(scratch: Path, seed: str, llm: str, agent: str) -> Tuple[Path, Path, Path]:
    """One offline solver run under `PYTHONHASHSEED=seed`; returns (output, samples, diagnostics)."""
    out, samples, diag = scratch / "output.csv", scratch / "samples.csv", scratch / "diag"
    command = [sys.executable, str(CODE_DIR / "main.py"), "--include-samples", "--samples-out", str(samples),
               "--out", str(out), "--diag", str(diag), "--llm", llm, "--agent", agent]
    environment = dict(os.environ, PYTHONHASHSEED=seed)
    done = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if done.returncode != 0:
        raise RuntimeError("solver exited %d: %s" % (done.returncode, done.stderr[-STDERR_TAIL:]))
    return out, samples, diag / "diagnostics.md"


def format_problems(path: Path) -> List[str]:
    """Header, line endings and row count of an output file (the contract check covers the rest)."""
    raw = path.read_bytes()
    problems = []
    if b"\r" in raw:
        problems.append("carriage return in the file")
    if not raw.startswith(OUTPUT_HEADER):
        problems.append("header is not case_id,deletion_status,steps_json")
    rows = [line for line in raw.decode("utf-8").split("\n")[1:] if line]
    if len(rows) != EVAL_REQUEST_COUNT:
        problems.append("%d rows, expected %d" % (len(rows), EVAL_REQUEST_COUNT))
    return problems


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checks(llm: str, agent: str, min_status: Optional[float], min_f1: Optional[float]) -> List[Check]:
    """Every check, in order. Raises RuntimeError / OSError when the solver or the data cannot be used."""
    reader = DatasetReader(REPO_ROOT / "dataset")
    requests = [request for request in reader.requests() if not request.is_sample]
    checks: List[Check] = []
    with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
        first = _run(Path(first_dir), HASH_SEEDS[0], llm, agent)
        second = _run(Path(second_dir), HASH_SEEDS[1], llm, agent)
        problems = format_problems(first[0])
        checks.append(Check("format", not problems, "; ".join(problems) or "header, LF, %d rows" % EVAL_REQUEST_COUNT))
        result = validate_file(first[0], requests, Citations.from_reader(reader))
        checks.append(Check("contract", result.ok, "%d violations, %d warnings" % (
            len(result.violations), len(result.warnings))))
        same = _digest(first[0]) == _digest(second[0]) and _digest(first[1]) == _digest(second[1])
        checks.append(Check("determinism", same, "PYTHONHASHSEED=%s and %s %s" % (
            HASH_SEEDS[0], HASH_SEEDS[1], "write identical bytes" if same else "write different bytes")))
        report = verify_report.verify(
            load_dataset(REPO_ROOT / "dataset"), verify_steps.read_output(first[0]),
            verify_steps.read_output(first[1]), redundancy.read_diagnostics(first[2]))
        checks.append(Check("invariants", report.hard_failures == 0, "%d hard failures" % report.hard_failures))
        checks.append(_sample_check(first[1], min_status, min_f1))
    return checks


def _sample_check(samples: Path, min_status: Optional[float], min_f1: Optional[float]) -> Check:
    gold = GoldReader(SAMPLE_OUTPUT).cases()
    report = score(gold, GoldReader(samples).cases())
    status, f1 = report.raw["G1"], report.raw["G3"]
    exact = report.cases - len(report.inexact_cases)
    passed = (min_status is None or status >= min_status) and (min_f1 is None or f1 >= min_f1)
    return Check("samples", passed, "status %.4f, row-exact %d/%d, step F1 %.4f" % (
        status, exact, report.cases, f1))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", choices=[mode for mode in LLM_MODES if mode != "live"], default="cache",
                        help="offline mode of both runs (default: %(default)s)")
    parser.add_argument("--agent", choices=("on", "off"), default="on", help="agent switch of both runs")
    parser.add_argument("--min-status", type=float, default=None, help="fail below this sample status accuracy")
    parser.add_argument("--min-f1", type=float, default=None, help="fail below this sample step F1")
    args = parser.parse_args(argv)
    try:
        checks = run_checks(args.llm, args.agent, args.min_status, args.min_f1)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        sys.stderr.write("cannot check: %s\n" % error)
        return EXIT_INPUT
    for check in checks:
        sys.stdout.write("%-12s %s  %s\n" % (check.name, "PASS" if check.passed else "FAIL", check.detail))
    return EXIT_OK if all(check.passed for check in checks) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
