"""Append one well-formed entry to the root log.txt (AGENTS.md sections 2 and 5; SCORING_STRATEGY X1).

``--tool`` and ``--model`` are required and never defaulted, so nothing is guessed. The entry is
linted before it is written (a bad entry never reaches the append-only log), written with
O_APPEND under an exclusive lock where the platform has fcntl, then re-read and linted again.

Turn:    append_log.py --kind turn --title T --prompt-file F --summary S --action A [--action A ...]
                       --tool T --model M [--parent-agent P] [--branch B]
Session: append_log.py --kind session --tool T --model M [--branch B] [--language L]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence

try:
    from devtools import check_log
except ImportError:  # run as a script: devtools/ is sys.path[0]
    import check_log

try:
    import fcntl
except ImportError:  # Windows: no lock, but each entry is still one O_APPEND write
    fcntl = None

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "log.txt"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_WORKTREE = "main"
DEFAULT_LANGUAGE = "py"
DEFAULT_PARENT_AGENT = "none"
DEFAULT_TIME_REMAINING = "not configured"
UNKNOWN_BRANCH = "unknown"
READ_CHUNK_BYTES = 1 << 16
# O_BINARY (Windows only) stops text-mode CRLF translation; elsewhere it does not exist.
OPEN_FLAGS = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
LOG_FILE_MODE = 0o644


def _one_line(value: str) -> str:
    return " ".join(value.split())


def render_session(timestamp: str, args: argparse.Namespace) -> str:
    return "\n".join([
        "## [%s] %s" % (timestamp, check_log.SESSION_TITLE),
        "",
        "tool=%s" % args.tool,
        "model=%s" % args.model,
        "Repo Root: %s" % args.repo_root,
        "Branch: %s" % args.branch,
        "Worktree: %s" % args.worktree,
        "Parent Agent: %s" % args.parent_agent,
        "Language: %s" % args.language,
        "Time Remaining: %s" % args.time_remaining,
        "",
    ]) + "\n"


def render_turn(timestamp: str, args: argparse.Namespace, prompt: str) -> str:
    lines = [
        "## [%s] %s" % (timestamp, _one_line(args.title)),
        "",
        check_log.PROMPT_LABEL,
        prompt,
        "",
        check_log.SUMMARY_LABEL,
        args.summary.strip(),
        "",
        check_log.ACTIONS_LABEL,
    ]
    lines += ["* %s" % _one_line(action) for action in args.action]
    lines += [
        "",
        check_log.CONTEXT_LABEL,
        "tool=%s" % args.tool,
        "model=%s" % args.model,
        "branch=%s" % args.branch,
        "repo_root=%s" % args.repo_root,
        "worktree=%s" % args.worktree,
        "parent_agent=%s" % args.parent_agent,
        "",
    ]
    return "\n".join(lines) + "\n"


def _git_branch() -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True)
    branch = result.stdout.decode("utf-8").strip() if result.returncode == 0 else ""
    return branch or UNKNOWN_BRANCH


def _separator(existing: str) -> str:
    """Text needed so the next entry starts after one blank line."""
    if not existing or existing.endswith("\n\n"):
        return ""
    return "\n" if existing.endswith("\n") else "\n\n"


def _read_all(fd: int) -> bytes:
    """Whole file from the start; portable (os.pread is Unix-only), and O_APPEND writes still go to the end."""
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: List[bytes] = []
    while True:
        chunk = os.read(fd, READ_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _new_findings(report: check_log.Report, existing_lines: int) -> check_log.Report:
    """Only the findings located in the new entry."""
    return check_log.Report(
        errors=[f for f in report.errors if f.line > existing_lines],
        warnings=[f for f in report.warnings if f.line > existing_lines],
    )


def append_entry(log_path: Path, make_entry: Callable[[str], str], now: Optional[datetime] = None) -> check_log.Report:
    """Lint the next entry of the log, append it, and verify the written bytes.

    The timestamp is taken while the lock is held, so parallel writers stay in time order.
    Returns the findings in the new entry; the file is untouched when there are errors.
    """
    fd = os.open(str(log_path), OPEN_FLAGS, LOG_FILE_MODE)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        existing = _read_all(fd).decode("utf-8")
        timestamp = (now or datetime.now(timezone.utc)).strftime(TIMESTAMP_FORMAT)
        addition = _separator(existing) + make_entry(timestamp)
        existing_lines = existing.count("\n")
        findings = _new_findings(check_log.lint(existing + addition), existing_lines)
        if findings.errors:
            return findings
        os.write(fd, addition.encode("utf-8"))
        written = _read_all(fd).decode("utf-8")
        if written != existing + addition:
            mismatch = check_log.Finding(existing_lines + 1, "log content differs from the expected text after the write")
            return check_log.Report(errors=[mismatch])
        return _new_findings(check_log.lint(written), existing_lines)
    finally:
        os.close(fd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append a validated entry to log.txt.")
    parser.add_argument("--kind", choices=("session", "turn"), required=True)
    parser.add_argument("--tool", required=True, help="exact harness name, e.g. 'Claude Code'")
    parser.add_argument("--model", required=True, help="exact runtime model id")
    parser.add_argument("--title", help="turn title, at most %d characters" % check_log.TITLE_MAX_CHARS)
    parser.add_argument("--prompt-file", type=Path, help="file holding the verbatim user prompt (secrets redacted)")
    parser.add_argument("--summary", help="2-5 sentences")
    parser.add_argument("--action", action="append", default=[], help="one Actions bullet; repeatable")
    parser.add_argument("--parent-agent", default=DEFAULT_PARENT_AGENT)
    parser.add_argument("--branch", default=None, help="default: current git branch")
    parser.add_argument("--worktree", default=DEFAULT_WORKTREE)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--time-remaining", default=DEFAULT_TIME_REMAINING)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    return parser


def main(argv: Optional[Sequence[str]] = None, now: Optional[datetime] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.kind == "turn":
        required = (("--title", args.title), ("--prompt-file", args.prompt_file),
                    ("--summary", args.summary), ("--action", args.action))
        missing = [flag for flag, value in required if not value]
        if missing:
            parser.error("--kind turn requires " + ", ".join(missing))
    if args.branch is None:
        args.branch = _git_branch()
    if args.kind == "session":
        report = append_entry(args.log, lambda timestamp: render_session(timestamp, args), now)
    else:
        prompt = args.prompt_file.read_bytes().decode("utf-8").strip()
        report = append_entry(args.log, lambda timestamp: render_turn(timestamp, args, prompt), now)
    for label, findings in (("WARNING", report.warnings), ("ERROR", report.errors)):
        for finding in findings:
            print("append_log: line %d: %s %s" % (finding.line, label, finding.message), file=sys.stderr)
    if report.errors:
        print("append_log: %d error(s) in the new entry of %s" % (len(report.errors), args.log), file=sys.stderr)
        return 1
    print("append_log: appended %s entry to %s" % (args.kind, args.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
