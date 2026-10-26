"""Judge-like reproduction of the submission across an environment matrix (T34; LOCAL_EVALUATION_STRATEGY 5).

Unzips `code.zip` at a fresh absolute path, takes the commands from the README block that follows
the marker `<!-- clean-room:commands -->` (the first fenced block after it), and runs the
pipeline command in every cell of the matrix:

* `PYTHONHASHSEED` in {0, 4242};
* `TZ` in {UTC, Pacific/Kiritimati};
* working directory in {repository root, `code/`};
* every interpreter given with `--python` (default: the running one).

Every run gets an empty environment (no API key, no home) and, on macOS, `sandbox-exec` with the
network denied; elsewhere the isolation is the environment alone, which the report states. All
cells must write a byte-identical `output.csv`, exit 0, report zero cache misses and finish inside
the wall-time gate. The other README commands run once, in the first cell. A last run without
`dataset/` must exit with a clear message and no traceback. The shipped test suite runs twice
with the first interpreter, with and without `dataset/`: both runs must pass, the second by
skipping the dataset-backed tests.

    python3 devtools/clean_room.py --zip code.zip --dataset dataset [--python PATH ...]

Exit codes: 0 every gate passed; 1 a gate failed; 2 unusable input.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_GATE = 1
EXIT_INPUT = 2

MARKER = "<!-- clean-room:commands -->"
FENCE = "```"
PIPELINE_SCRIPT = "main.py"
HASH_SEEDS = ("0", "4242")
TIME_ZONES = ("UTC", "Pacific/Kiritimati")
WORKING_DIRS = ("", "code")  # relative to the extracted root
OUTPUT_NAME = "output.csv"
DIAGNOSTICS_PATH = ("diagnostics", "diagnostics.md")
TARGET_SECONDS = 5.0
GATE_SECONDS = 30.0
SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"
SANDBOX_TOOL = "sandbox-exec"
MINIMAL_PATH = "/usr/bin:/bin"
MISSING_DATASET_EXIT = 2
TRACEBACK = "Traceback (most recent call last)"
MISSES = re.compile(r"Intent requests without a model verdict: (\d+)")
MEDIA_NOTES = re.compile(r"Media extraction notes: (\d+)")
TEST_COMMAND = ("python3", "-m", "unittest", "discover", "-s", "code/tests", "-t", "code")
DATASET_DIR = "dataset"
HIDDEN_DATASET_DIR = "dataset.hidden"


class CleanRoomError(Exception):
    """The archive or README cannot be used."""


@dataclass(frozen=True)
class Cell:
    python: str
    hash_seed: str
    time_zone: str
    working_dir: str


@dataclass(frozen=True)
class CellResult:
    cell: Cell
    exit_code: int
    seconds: float
    digest: str
    cache_misses: Optional[int]
    traceback: bool


def readme_commands(readme: str) -> List[str]:
    """Commands of the first fenced block after the marker; comment and blank lines are skipped."""
    if MARKER not in readme:
        raise CleanRoomError("README has no %s block" % MARKER)
    after = readme.split(MARKER, 1)[1]
    parts = after.split(FENCE)
    if len(parts) < 3:
        raise CleanRoomError("no fenced block follows the clean-room marker")
    lines = [line.strip() for line in parts[1].splitlines()[1:]]
    commands = [line for line in lines if line and not line.startswith("#")]
    if not commands:
        raise CleanRoomError("the clean-room block holds no command")
    return commands


def relocate(arguments: Sequence[str], working_dir: str) -> List[str]:
    """Rewrite `code/...` paths for a command run from inside `code/`."""
    if working_dir != "code":
        return list(arguments)
    return ["." if arg == "code" else arg[len("code/"):] if arg.startswith("code/") else arg for arg in arguments]


def with_python(arguments: Sequence[str], python: str) -> List[str]:
    """Replace a leading `python3` or `python` by the interpreter of the cell."""
    if arguments and arguments[0] in ("python3", "python"):
        return [python] + list(arguments[1:])
    return list(arguments)


def sandboxed(arguments: Sequence[str], available: bool) -> List[str]:
    """Wrap a command in `sandbox-exec` with the network denied when the tool exists."""
    return [SANDBOX_TOOL, "-p", SANDBOX_PROFILE] + list(arguments) if available else list(arguments)


def sandbox_available() -> bool:
    return sys.platform == "darwin" and shutil.which(SANDBOX_TOOL) is not None


def unzip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(str(archive)) as bundle:
        bundle.extractall(str(destination))


def cache_misses(root: Path) -> Optional[int]:
    """Intent requests without a verdict plus media extraction notes from the run's diagnostics."""
    path = root.joinpath(*DIAGNOSTICS_PATH)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    intent, media = MISSES.search(text), MEDIA_NOTES.search(text)
    return (int(intent.group(1)) if intent else 0) + (int(media.group(1)) if media else 0)


def run_command(
    command: Sequence[str], root: Path, cell: Cell, sandbox: bool
) -> Tuple[int, float, str]:
    """Run one README command in an empty environment; returns (exit code, seconds, stderr)."""
    arguments = sandboxed(relocate(with_python(command, cell.python), cell.working_dir), sandbox)
    env = {"PATH": MINIMAL_PATH, "PYTHONHASHSEED": cell.hash_seed, "TZ": cell.time_zone,
           "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.perf_counter()
    done = subprocess.run(arguments, cwd=str(root / cell.working_dir), env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    return done.returncode, time.perf_counter() - started, done.stderr


def run_cell(command: Sequence[str], root: Path, cell: Cell, sandbox: bool) -> CellResult:
    """Run the pipeline command of one matrix cell and fingerprint its output."""
    for stale in (root / OUTPUT_NAME, root / DIAGNOSTICS_PATH[0]):
        if stale.is_dir():
            shutil.rmtree(str(stale))
        elif stale.exists():
            stale.unlink()
    code, seconds, stderr = run_command(command, root, cell, sandbox)
    output = root / OUTPUT_NAME
    digest = hashlib.sha256(output.read_bytes()).hexdigest() if output.is_file() else ""
    return CellResult(cell, code, seconds, digest, cache_misses(root), TRACEBACK in stderr)


def matrix(pythons: Sequence[str]) -> List[Cell]:
    return [Cell(*parts) for parts in itertools.product(pythons, HASH_SEEDS, TIME_ZONES, WORKING_DIRS)]


def pipeline_command(commands: Sequence[str]) -> List[str]:
    for command in commands:
        arguments = shlex.split(command)
        if any(arg.endswith(PIPELINE_SCRIPT) for arg in arguments):
            return arguments
    raise CleanRoomError("no README command runs %s" % PIPELINE_SCRIPT)


def gate_problems(results: Sequence[CellResult]) -> List[str]:
    """Reasons the matrix fails: exit codes, tracebacks, differing bytes, cache misses and time."""
    problems = []
    for result in results:
        name = "/".join((result.cell.python, "seed " + result.cell.hash_seed, result.cell.time_zone,
                         result.cell.working_dir or "root"))
        if result.exit_code != 0 or not result.digest:
            problems.append("%s: exit %d, no output" % (name, result.exit_code))
        if result.traceback:
            problems.append("%s: traceback on stderr" % name)
        if result.cache_misses:
            problems.append("%s: %d cache misses" % (name, result.cache_misses))
        if result.seconds > GATE_SECONDS:
            problems.append("%s: %.1f s is over the %.0f s gate" % (name, result.seconds, GATE_SECONDS))
    if len({result.digest for result in results}) > 1:
        problems.append("output.csv differs between cells")
    return problems


@contextmanager
def dataset_hidden(root: Path, hide: bool = True) -> Iterator[None]:
    """Rename `dataset/` away for the duration of the block (when `hide`), then restore it."""
    present, hidden = root / DATASET_DIR, root / HIDDEN_DATASET_DIR
    moved = hide and present.exists()
    if moved:
        present.rename(hidden)
    try:
        yield
    finally:
        if moved:
            hidden.rename(present)


def first_cell(python: str) -> Cell:
    return Cell(python, HASH_SEEDS[0], TIME_ZONES[0], "")


def check_without_dataset(root: Path, command: Sequence[str], python: str, sandbox: bool) -> List[str]:
    """Run the pipeline in a copy of the tree without `dataset/`: a clear exit, never a traceback."""
    with dataset_hidden(root):
        code, _seconds, stderr = run_command(command, root, first_cell(python), sandbox)
    problems = []
    if code != MISSING_DATASET_EXIT:
        problems.append("without dataset/: exit %d, expected %d" % (code, MISSING_DATASET_EXIT))
    if TRACEBACK in stderr:
        problems.append("without dataset/: traceback")
    if not stderr.strip():
        problems.append("without dataset/: no message")
    return problems


def check_test_suite(root: Path, python: str, sandbox: bool) -> Tuple[List[str], List[str]]:
    """Run the shipped suite with and without `dataset/`; returns (problems, one summary per run)."""
    problems: List[str] = []
    summaries: List[str] = []
    for label, hide in (("with dataset/", False), ("without dataset/", True)):
        with dataset_hidden(root, hide):
            code, seconds, stderr = run_command(TEST_COMMAND, root, first_cell(python), sandbox)
        lines = [line for line in stderr.splitlines() if line.strip()]
        verdict = lines[-1] if lines else "no output"
        summaries.append("%s: exit %d in %.1f s, %s" % (label, code, seconds, verdict))
        if code != 0:
            problems.append("test suite %s: exit %d, %s" % (label, code, verdict))
    return problems, summaries


def render(
    results: Sequence[CellResult], sandbox: bool, problems: Sequence[str], extra: Sequence[str],
    suite: Sequence[str] = (),
) -> str:
    lines = ["# Clean-room reproduction", "",
             "Isolation: empty environment, %s." % ("network denied by sandbox-exec" if sandbox
                                                    else "no sandbox-exec on this platform, network not blocked"),
             "", "| Python | Hash seed | TZ | cwd | Exit | Seconds | Cache misses | output.csv sha256 |",
             "|---|---|---|---|---|---|---|---|"]
    for result in results:
        cell = result.cell
        lines.append("| %s | %s | %s | %s | %d | %.2f | %s | %s |" % (
            cell.python, cell.hash_seed, cell.time_zone, cell.working_dir or "root", result.exit_code,
            result.seconds, "?" if result.cache_misses is None else result.cache_misses, result.digest[:16]))
    lines += ["", "Target %.0f s, gate %.0f s." % (TARGET_SECONDS, GATE_SECONDS), ""]
    lines += ["Other README commands run once: %s" % (", ".join(extra) or "none"), ""]
    lines += ["Test suite: %s" % ("; ".join(suite) or "not run"), ""]
    lines += ["Problems: %d" % len(problems)] + ["- " + problem for problem in problems] + [""]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, required=True, help="code.zip to reproduce")
    parser.add_argument("--dataset", type=Path, required=True, help="dataset/ copied next to the unpacked code")
    parser.add_argument("--python", action="append", default=[], metavar="PATH", help="interpreter (repeatable)")
    args = parser.parse_args(argv)
    pythons = [os.path.abspath(path) for path in args.python] or [sys.executable]
    try:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "unpacked"
            unzip(args.zip, root)
            shutil.copytree(str(args.dataset), str(root / "dataset"))
            commands = readme_commands((root / "README.md").read_text(encoding="utf-8"))
            pipeline = pipeline_command(commands)
            sandbox = sandbox_available()
            results = [run_cell(pipeline, root, cell, sandbox) for cell in matrix(pythons)]
            problems = gate_problems(results) + check_without_dataset(root, pipeline, pythons[0], sandbox)
            others = [c for c in commands if shlex.split(c) != pipeline]
            for command in others:
                code, _seconds, _stderr = run_command(shlex.split(command), root, results[0].cell, sandbox)
                if code != 0:
                    problems.append("README command failed (exit %d): %s" % (code, command))
            suite_problems, suite = check_test_suite(root, pythons[0], sandbox)
            problems += suite_problems
            report = render(results, sandbox, problems, others, suite)
    except (OSError, zipfile.BadZipFile, CleanRoomError) as error:
        sys.stderr.write("cannot reproduce: %s\n" % error)
        return EXIT_INPUT
    sys.stdout.write(report)
    return EXIT_OK if not problems else EXIT_GATE


if __name__ == "__main__":
    sys.exit(main())
