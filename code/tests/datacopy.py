"""Tests-only helper: copy `dataset/` with a text transform, then run the CLI over the copy.

The override-ban tests need the whole participant dataset under a different surface
(relabeled ids, shifted times, extra late evidence). Text files are rewritten through a
function; images and PDFs are copied unchanged, which is safe because the runs use `--llm off`
and never read them. Every run writes into the caller's temporary directory with `--out` and
`--diag`, so the submission `output.csv` is never touched.
"""
from __future__ import annotations

import contextlib
import csv
import io
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Tuple

from ghostaudit import cli
from ghostaudit.config import Config
from ghostaudit.policy import SYSTEM_BY_PREFIX

TEXT_SUFFIXES = frozenset({".csv", ".sql", ".json", ".log", ".txt"})
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIME_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
# Resource, activity, evidence and audit-log id prefixes; the long audit prefix comes first.
ID_PREFIXES = tuple(SYSTEM_BY_PREFIX) + ("activity_", "evidence_", "audit_record_", "audit_")
ID_PATTERN = re.compile(r"\b(%s)(\d+)\b" % "|".join(re.escape(prefix) for prefix in ID_PREFIXES))
REVERSE_BASE = 10 ** 9  # larger than every id number; reversing keeps the digit count fixed
REVERSE_WIDTH = len(str(REVERSE_BASE))
FLAG_LINE = re.compile(r"^- Assumptions fired: (.*)$", re.MULTILINE)
CASE_HEADING = re.compile(r"^### (case_\d+) \(evaluation\): \w+$", re.MULTILINE)
NO_ASSUMPTIONS = "none"

Transform = Callable[[str], str]


def append_zero(text: str) -> str:
    """Monotone relabel: `account_57` becomes `account_570`; numeric and string order are kept."""
    return ID_PATTERN.sub(lambda m: m.group(1) + m.group(2) + "0", text)


def reverse_numbers(text: str) -> str:
    """Non-monotone relabel: id numbers are mirrored, so the largest becomes the smallest."""
    return ID_PATTERN.sub(
        lambda m: "%s%0*d" % (m.group(1), REVERSE_WIDTH, REVERSE_BASE - int(m.group(2))), text)


def shift_times(seconds: int) -> Transform:
    """Transform that moves every `...Z` timestamp by `seconds`."""
    delta = timedelta(seconds=seconds)

    def apply(text: str) -> str:
        def move(match: "re.Match[str]") -> str:
            stamp = datetime.strptime(match.group(0), TIME_FORMAT).replace(tzinfo=timezone.utc)
            return (stamp + delta).strftime(TIME_FORMAT)
        return TIME_PATTERN.sub(move, text)

    return apply


def compose(*transforms: Transform) -> Transform:
    def apply(text: str) -> str:
        for transform in transforms:
            text = transform(text)
        return text
    return apply


def copy_dataset(
    source: Path, target: Path, transform: Transform, suffixes: FrozenSet[str] = TEXT_SUFFIXES
) -> None:
    """Copy `source` to `target`; files with a suffix in `suffixes` go through `transform`, others are copied."""
    for path in sorted(source.rglob("*")):
        destination = target / path.relative_to(source)
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.suffix in suffixes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with path.open(encoding="utf-8", newline="") as handle:
                text = handle.read()
            with destination.open("w", encoding="utf-8", newline="") as handle:
                handle.write(transform(text))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(path), str(destination))


def run_offline(
    dataset_dir: Path, scratch: Path, tolerate_violations: bool = False
) -> Tuple[Dict[str, Tuple[str, str]], str]:
    """`ghostaudit --llm off` over `dataset_dir`: ({case_id: (status, steps_json)}, diagnostics text).

    A contract violation (exit 1) still writes the files; controls that damage the dataset on
    purpose pass `tolerate_violations` to read them anyway.
    """
    out, diag = scratch / "output.csv", scratch / "diag"
    arguments = ["--dataset", str(dataset_dir), "--llm", "off", "--out", str(out), "--diag", str(diag)]
    loggers = [logging.getLogger(name) for name in ("ghostaudit",)]
    previous = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(arguments)
    finally:
        for logger, level in zip(loggers, previous):
            logger.setLevel(level)
    if code != cli.EXIT_OK and not (tolerate_violations and code == cli.EXIT_CONTRACT):
        raise RuntimeError("ghostaudit exited %d" % code)
    with out.open(encoding="utf-8", newline="") as handle:
        rows = {row["case_id"]: (row["deletion_status"], row["steps_json"]) for row in csv.DictReader(handle)}
    return rows, (diag / "diagnostics.md").read_text(encoding="utf-8")


def flagged_cases(diagnostics: str, marker: str = "") -> List[str]:
    """Evaluation cases whose diagnostics list an assumption (containing `marker`, if given)."""
    sections = CASE_HEADING.split(diagnostics)
    flagged = []
    for index in range(1, len(sections), 2):
        match = FLAG_LINE.search(sections[index + 1])
        if match and match.group(1) != NO_ASSUMPTIONS and marker in match.group(1):
            flagged.append(sections[index])
    return flagged


def default_dataset() -> Path:
    return Config().dataset_dir
