"""Lint log.txt against AGENTS.md sections 2 and 5 (SCORING_STRATEGY X2, X3, X6; LOCAL_EVALUATION_STRATEGY section 7).

Errors: first entry is SESSION START with all 8 keys once; turn sections in order with a
non-empty prompt; Actions as ``* `` bullets; all 6 Context keys once; ``tool=`` on an
allowlist and ``model=`` matching an id pattern; timezone-aware ISO timestamps that never go
backwards; titles of at most 80 characters; no CR; no secret patterns; a summary of more than
5 sentences; a sub-agent id (``agent-`` + 17 hex) or workflow run id (``wf_`` + 8 hex, ``-``,
3 hex) that no Actions line lists.
Warnings: a summary of fewer than 2 sentences.
Entries stamped before LEGACY_CUTOFF report the sentence and id findings as warnings instead, and
an email-like string (dataset or personal data; plan/tasks/README.md "Log hygiene") is an error
only in entries stamped at or after PII_CUTOFF. The log is append-only, so each stricter rule
starts at the instant it was introduced.

``--trace`` (repeatable, one per main Claude Code session JSONL) checks the log against each
session and the sub-agent transcripts Claude Code stores beside it as
``<session>/subagents/[workflows/<run id>/]agent-<id>.jsonl``:
every typed user prompt is logged (a prompt is logged when a logged prompt equals it, with
``[REDACTED]`` standing for any text, or starts or ends with it at a word boundary; one entry may
log consecutive prompts together); each session's first logged turn follows a SESSION START that
comes after the last turn of the other sessions; every sub-agent id and workflow run id (the
session's ``agentId`` and ``runId`` fields and the transcript paths) is listed on an Actions line;
every sub-agent whose transcript starts at or after LEGACY_CUTOFF has its task text (the last user
record that opens its transcript) quoted in an entry that lists its agent or run id on an Actions
line. A quote is the whole task text, or its first N lines followed by the line that ``--quote``
prints, ``[task sha256=<hex of the UTF-8 task text>, first N of M lines]``. The quote rule runs only
under ``--trace`` because append_log lints every new entry and a sub-agent writing its own entry
may not know its id.
``--exclusions FILE`` (default: log_exclusions.txt beside this script) lists prompts the user asked
to keep out of log.txt, one sha256 of the normalized prompt per line (``#`` comments allowed),
never the text; ``--trace`` prints that digest with every unlogged prompt and skips excluded ones.
A line is added only at the user's request; the gate cannot otherwise pass on a session with a
user-removed prompt.
``--pending`` prints, for every transcript that ``--trace`` would report, a block the orchestrator
can paste into a group entry's prompt: a line naming its ids and start stamp, then its quote.
``--baseline-ref`` asserts that the log committed at REF is a byte prefix of the current log, and
fails closed when REF has no log.txt.

Usage: python3 devtools/check_log.py log.txt [--trace session.jsonl ...] [--exclusions FILE]
                                      [--pending] [--quote-lines N] [--baseline-ref REF]
       python3 devtools/check_log.py --quote agent-<id>.jsonl [--quote-lines N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

TITLE_MAX_CHARS = 80
SUMMARY_MIN_SENTENCES = 2
SUMMARY_MAX_SENTENCES = 5
# Entries stamped before this instant were written before the v2 rules; their findings are warnings.
LEGACY_CUTOFF = "2026-10-24T17:24:00Z"
# Entries stamped before this instant report an email-like string as a warning, not an error.
PII_CUTOFF = "2026-10-24T17:50:00Z"
EXCLUSIONS_FILE = Path(__file__).with_name("log_exclusions.txt")
SESSION_TITLE = "SESSION START"
HEADER_PREFIX = "## ["

ALLOWED_TOOLS = frozenset({
    "Claude Code", "OpenAI Codex CLI", "Codex CLI", "Codex Cloud", "Gemini CLI", "Cursor",
    "Windsurf", "opencode", "Aider", "goose", "Factory", "RooCode", "JetBrains Junie",
    "GitHub Copilot", "Devin",
})
SESSION_EQUALS_KEYS = ("tool", "model")
SESSION_COLON_KEYS = ("Repo Root", "Branch", "Worktree", "Parent Agent", "Language", "Time Remaining")
CONTEXT_KEYS = ("tool", "model", "branch", "repo_root", "worktree", "parent_agent")

PROMPT_LABEL = "User Prompt (verbatim, secrets redacted):"
SUMMARY_LABEL = "Agent Response Summary:"
ACTIONS_LABEL = "Actions:"
CONTEXT_LABEL = "Context:"
TURN_LABELS = (PROMPT_LABEL, SUMMARY_LABEL, ACTIONS_LABEL, CONTEXT_LABEL)

HEADER_RE = re.compile(r"^## \[(?P<ts>[^\]]*)\] (?P<title>.+)$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
FRACTION_RE = re.compile(r"\.(\d+)")
FRACTION_DIGITS = 6  # Python 3.9 fromisoformat accepts only 3 or 6 fractional digits
MODEL_ID_RE = re.compile(r"^(?:[a-z0-9_.-]+/)?[a-z][a-z0-9]*(?:[-.:_][a-z0-9]+)+$")
PLACEHOLDER_PARTS = ("unknown", "placeholder", "generic")
SECRET_PATTERNS = (
    re.compile(r"\bsk-ant-"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"PRIVATE KEY"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"api[_-]?key\s*[=:]\s*(?!\[REDACTED\])\S+", re.IGNORECASE),
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[`(])")
# Sub-agent ids are 17 hex digits (the subagent file names); workflow run ids look like wf_173ce708-f03.
AGENT_ID_RE = re.compile(r"\bagent-[0-9a-f]{17}\b")
WORKFLOW_RUN_ID_RE = re.compile(r"\bwf_[0-9a-f]{8}-[0-9a-f]{3}\b")
SESSION_AGENT_ID_RE = re.compile(r'"agentId"\s*:\s*"([0-9a-f]{17})"')
SESSION_RUN_ID_RE = re.compile(r'"runId"\s*:\s*"(wf_[0-9a-f]{8}-[0-9a-f]{3})"')
SUBAGENTS_DIR = "subagents"
TRANSCRIPT_GLOB = "agent-*.jsonl"
QUOTE_LINES = 3
TASK_QUOTE_RE = re.compile(r"^\[task sha256=([0-9a-f]{64}), first (\d+) of (\d+) lines\]$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REDACTED = "[REDACTED]"
# Slash commands are recorded as <command-name> records; a typed '/path ...' is a real prompt.
IGNORED_PROMPT_PREFIXES = ("!", "[Request interrupted")
IGNORED_PROMPT_TAGS = (
    "<bash-input>", "<bash-stdout>", "<command-name>", "<command-message>",
    "<local-command-caveat>", "<local-command-stdout>", "<task-notification>", "<system-reminder>",
)

Lines = List[Tuple[int, str]]
Pairs = Dict[str, Tuple[int, str]]


@dataclass(frozen=True)
class Finding:
    line: int
    message: str


@dataclass
class Report:
    errors: List[Finding] = field(default_factory=list)
    warnings: List[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class Entry:
    line: int
    timestamp: str
    title: str
    body: Tuple[Tuple[int, str], ...]


@dataclass(frozen=True)
class Transcript:
    """A sub-agent transcript: its agent id and workflow run id (if any), task text and start stamp."""
    name: str
    ids: frozenset
    task: str
    started: str


def parse_entries(text: str, report: Report) -> List[Entry]:
    """Split the log into entries; text before the first header is an error."""
    entries: List[Entry] = []
    header: Optional[Tuple[int, str, str]] = None
    body: Lines = []
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith(HEADER_PREFIX):
            if header is not None:
                entries.append(Entry(header[0], header[1], header[2], tuple(body)))
            body = []
            match = HEADER_RE.match(line)
            header = (number, match.group("ts"), match.group("title")) if match else None
            if match is None:
                report.errors.append(Finding(number, "malformed entry header (want '## [TIMESTAMP] title')"))
        elif header is not None:
            body.append((number, line))
        elif line.strip():
            report.errors.append(Finding(number, "text before the first entry header"))
    if header is not None:
        entries.append(Entry(header[0], header[1], header[2], tuple(body)))
    return entries


def _six_digit_fraction(match: re.Match) -> str:
    return "." + match.group(1).ljust(FRACTION_DIGITS, "0")[:FRACTION_DIGITS]


def _parse_timestamp(raw: str) -> Optional[datetime]:
    if not TIMESTAMP_RE.match(raw):
        return None
    iso = FRACTION_RE.sub(_six_digit_fraction, raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _is_legacy(timestamp: str, cutoff: str = LEGACY_CUTOFF) -> bool:
    """True when the stamp is before the cutoff (an unparsable stamp is not legacy)."""
    moment = _parse_timestamp(timestamp)
    return moment is not None and moment < _parse_timestamp(cutoff)


def _findings_for(entry: Entry, report: Report, cutoff: str = LEGACY_CUTOFF) -> List[Finding]:
    """Where a finding of this entry goes: warnings for entries stamped before the cutoff, errors otherwise."""
    return report.warnings if _is_legacy(entry.timestamp, cutoff) else report.errors


def _parse_pairs(lines: Lines, keys: Sequence[str], separator: str, entry_line: int, what: str, report: Report) -> Pairs:
    """Read ``key<separator>value`` lines; unknown, repeated or missing keys are errors."""
    pairs: Pairs = {}
    for number, line in lines:
        if not line.strip():
            continue
        key, found, value = line.partition(separator)
        if not found or key not in keys:
            report.errors.append(Finding(number, "unexpected line in %s: %r" % (what, line)))
        elif key in pairs:
            report.errors.append(Finding(number, "%s key %r appears more than once" % (what, key)))
        else:
            pairs[key] = (number, value.strip())
    for key in keys:
        if key not in pairs:
            report.errors.append(Finding(entry_line, "%s is missing key %r" % (what, key)))
    return pairs


def _check_pairs(pairs: Pairs, report: Report) -> None:
    """Values must be non-blank and not template placeholders; tool and model must be authoritative."""
    for key, (number, value) in pairs.items():
        if not value:
            report.errors.append(Finding(number, "%s is blank" % key))
        elif "<" in value or ">" in value:
            report.errors.append(Finding(number, "%s still holds a template placeholder: %r" % (key, value)))
    if "tool" in pairs and pairs["tool"][1] not in ALLOWED_TOOLS:
        report.errors.append(Finding(pairs["tool"][0], "tool=%r is not an allowed harness name" % pairs["tool"][1]))
    if "model" in pairs:
        number, model = pairs["model"]
        if not MODEL_ID_RE.match(model) or any(part in model for part in PLACEHOLDER_PARTS):
            report.errors.append(Finding(number, "model=%r is not a model id" % model))


def _check_session(entry: Entry, report: Report) -> None:
    equals_lines = [(n, t) for n, t in entry.body if t.partition("=")[0] in SESSION_EQUALS_KEYS]
    colon_lines = [(n, t) for n, t in entry.body if (n, t) not in equals_lines]
    pairs = _parse_pairs(equals_lines, SESSION_EQUALS_KEYS, "=", entry.line, SESSION_TITLE, report)
    pairs.update(_parse_pairs(colon_lines, SESSION_COLON_KEYS, ":", entry.line, SESSION_TITLE, report))
    _check_pairs(pairs, report)


def split_turn(entry: Entry, report: Report) -> Optional[Dict[str, Lines]]:
    """Return the four labelled sections of a turn entry, or None after reporting why not."""
    positions: List[Tuple[str, int]] = []
    start = 0
    for label in TURN_LABELS:
        index = next((i for i in range(start, len(entry.body)) if entry.body[i][1] == label), None)
        if index is None:
            report.errors.append(Finding(entry.line, "missing or out-of-order section %r" % label))
            return None
        positions.append((label, index))
        start = index + 1
    for number, line in entry.body[:positions[0][1]]:
        if line.strip():
            report.errors.append(Finding(number, "text between the header and the prompt label"))
    ends = [index for _, index in positions[1:]] + [len(entry.body)]
    return {label: list(entry.body[index + 1:end]) for (label, index), end in zip(positions, ends)}


def _text(lines: Lines) -> str:
    return "\n".join(line for _, line in lines).strip()


def _check_turn(entry: Entry, report: Report) -> None:
    sections = split_turn(entry, report)
    if sections is None:
        return
    if not _text(sections[PROMPT_LABEL]):
        report.errors.append(Finding(entry.line, "prompt is empty"))
    summary = " ".join(_text(sections[SUMMARY_LABEL]).split())
    if not summary:
        report.errors.append(Finding(entry.line, "summary is empty"))
    else:
        count = len(SENTENCE_SPLIT_RE.split(summary))
        if count < SUMMARY_MIN_SENTENCES:
            report.warnings.append(Finding(entry.line, "summary has %d sentences (want 2-5)" % count))
        elif count > SUMMARY_MAX_SENTENCES:
            _findings_for(entry, report).append(Finding(entry.line, "summary has %d sentences (want 2-5)" % count))
    actions = [(n, t) for n, t in sections[ACTIONS_LABEL] if t.strip()]
    if not actions:
        report.errors.append(Finding(entry.line, "Actions has no bullets"))
    for number, line in actions:
        if not line.startswith("* ") or not line[2:].strip():
            report.errors.append(Finding(number, "Actions line must be a '* ' bullet: %r" % line))
    _check_pairs(_parse_pairs(sections[CONTEXT_LABEL], CONTEXT_KEYS, "=", entry.line, "Context", report), report)


def _ids(text: str) -> Set[str]:
    """Sub-agent ids and workflow run ids written in the text."""
    return set(AGENT_ID_RE.findall(text)) | set(WORKFLOW_RUN_ID_RE.findall(text))


def _turn_sections(entries: Sequence[Entry]) -> List[Tuple[int, Dict[str, Lines]]]:
    """(entry index, sections) for every well-formed turn entry."""
    scratch = Report()
    found: List[Tuple[int, Dict[str, Lines]]] = []
    for index, entry in enumerate(entries):
        sections = None if entry.title == SESSION_TITLE else split_turn(entry, scratch)
        if sections is not None:
            found.append((index, sections))
    return found


def _actions_ids(sections: Dict[str, Lines]) -> Set[str]:
    return {ident for _, line in sections[ACTIONS_LABEL] for ident in _ids(line)}


def _listed_ids(entries: Sequence[Entry]) -> Set[str]:
    """Ids written on an Actions line of a turn entry."""
    listed: Set[str] = set()
    for _, sections in _turn_sections(entries):
        listed |= _actions_ids(sections)
    return listed


def _check_ids(entries: Sequence[Entry], report: Report) -> None:
    """Every id the log mentions must be listed on some Actions line (reported once per id)."""
    listed = _listed_ids(entries)
    reported: Set[str] = set()
    for entry in entries:
        for number, line in [(entry.line, entry.title)] + list(entry.body):
            for ident in sorted(_ids(line) - listed - reported):
                reported.add(ident)
                _findings_for(entry, report).append(Finding(number, "%s is not listed on any Actions line" % ident))


def lint(text: str) -> Report:
    """Lint a whole log text."""
    report = Report()
    entries = parse_entries(text, report)
    if not entries:
        report.errors.append(Finding(1, "log has no entries"))
    elif entries[0].title != SESSION_TITLE:
        report.errors.append(Finding(entries[0].line, "first entry must be %s" % SESSION_TITLE))
    previous: Optional[datetime] = None
    for entry in entries:
        moment = _parse_timestamp(entry.timestamp)
        if moment is None or moment.tzinfo is None:
            report.errors.append(Finding(entry.line, "timestamp %r is not ISO-8601 with timezone" % entry.timestamp))
        else:
            if previous is not None and moment < previous:
                report.errors.append(Finding(entry.line, "timestamp goes backwards"))
            previous = moment
        if len(entry.title) > TITLE_MAX_CHARS:
            report.errors.append(Finding(entry.line, "title is %d characters (max %d)" % (len(entry.title), TITLE_MAX_CHARS)))
        if entry.title == SESSION_TITLE:
            _check_session(entry, report)
        else:
            _check_turn(entry, report)
    _check_ids(entries, report)
    _check_hygiene(text, entries, report)
    return report


def _check_hygiene(text: str, entries: Sequence[Entry], report: Report) -> None:
    for number, line in enumerate(text.split("\n"), start=1):
        if "\r" in line:
            report.errors.append(Finding(number, "CR character (use LF line endings)"))
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            report.errors.append(Finding(number, "possible secret"))
    for entry in entries:
        for number, line in [(entry.line, entry.title)] + list(entry.body):
            if EMAIL_RE.search(line):
                finding = Finding(number, "email-like string (personal and dataset identifiers must not be logged)")
                _findings_for(entry, report, PII_CUTOFF).append(finding)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _prompt_matches(logged: str, user: str) -> bool:
    """True when a normalized logged prompt records the normalized user prompt (see module docstring).

    A logged prompt that is only ``[REDACTED]`` has no literal text and matches nothing.
    """
    if logged == user or logged.startswith(user + " ") or logged.endswith(" " + user):
        return True
    parts = logged.split(REDACTED)
    if len(parts) == 1 or not "".join(parts).strip():
        return False
    return re.fullmatch(".*?".join(re.escape(part) for part in parts), user) is not None


def _turn_prompts(entries: Sequence[Entry]) -> List[Tuple[int, str]]:
    """(entry index, normalized prompt) for every turn entry."""
    return [(index, _normalize(_text(sections[PROMPT_LABEL]))) for index, sections in _turn_sections(entries)]


def logged_prompts(text: str) -> List[str]:
    """Normalized prompts of every turn entry in the log."""
    return [prompt for _, prompt in _turn_prompts(parse_entries(text, Report()))]


def _records(path: Path) -> List[dict]:
    """The JSON object records of a JSONL file; unreadable lines are skipped."""
    records: List[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _content_text(record: dict) -> Optional[str]:
    """A user record's text (text blocks joined; images ignored), or None for a tool result."""
    content = record.get("message", {}).get("content")
    if isinstance(content, list):
        if any(block.get("type") == "tool_result" for block in content):
            return None
        content = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
    return content if isinstance(content, str) else None


def _typed_prompt(record: dict) -> Optional[str]:
    """The normalized text of a user-typed prompt record, or None for tool results, notifications and commands."""
    if record.get("type") != "user" or record.get("isSidechain") or record.get("isMeta"):
        return None
    prompt = (_content_text(record) or "").strip()
    if not prompt or prompt.startswith(IGNORED_PROMPT_PREFIXES) or prompt.startswith(IGNORED_PROMPT_TAGS):
        return None
    return _normalize(prompt)


def session_prompts(path: Path) -> List[str]:
    """User prompts typed in a session JSONL, de-duplicated (collapses /rewind resends)."""
    prompts: List[str] = []
    for record in _records(path):
        prompt = _typed_prompt(record)
        if prompt is not None and prompt not in prompts:
            prompts.append(prompt)
    return prompts


def read_exclusions(path: Path) -> Set[str]:
    """The sha256 digests listed in an exclusions file; a missing file excludes nothing."""
    if not path.exists():
        return set()
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if SHA256_RE.match(line)}


def unlogged_prompts(log_text: str, session_files: Iterable[Path], excluded: Set[str] = frozenset()) -> List[str]:
    """Session prompts that no log entry contains, skipping prompts whose sha256 is excluded."""
    logged = logged_prompts(log_text)
    return [
        prompt
        for path in session_files
        for prompt in session_prompts(path)
        if _sha256(prompt) not in excluded and not any(_prompt_matches(entry, prompt) for entry in logged)
    ]


def _owned_turns(turns: Sequence[Tuple[int, str]], prompts: Sequence[str]) -> List[int]:
    """Indexes of the turn entries that log one of the session's prompts, in log order."""
    return [index for index, logged in turns if any(_prompt_matches(logged, prompt) for prompt in prompts)]


def session_start_problems(log_text: str, session_files: Sequence[Path]) -> List[str]:
    """Each session's first logged turn needs a SESSION START after the last turn of the other sessions before it."""
    entries = parse_entries(log_text, Report())
    starts = [index for index, entry in enumerate(entries) if entry.title == SESSION_TITLE]
    turns = _turn_prompts(entries)
    owned = {path: _owned_turns(turns, session_prompts(path)) for path in session_files}
    problems: List[str] = []
    for path in session_files:
        if not owned[path]:
            continue
        first = owned[path][0]
        foreign = [index for other, indexes in owned.items() if other != path for index in indexes if index < first]
        previous_turn = max(foreign, default=-1)
        if not any(previous_turn < start < first for start in starts):
            problems.append("session %s: no SESSION START before its first logged turn" % path.name)
    return problems


def read_task(path: Path) -> Tuple[str, str]:
    """(task text, timestamp) of a sub-agent transcript: the last of the user records that open it.

    A workflow sub-agent opens with the relayed user request followed by its computed task.
    """
    task, started = "", ""
    for record in _records(path):
        if record.get("type") != "user":
            if task:
                break
            continue
        task = _content_text(record) or task
        started = started or str(record.get("timestamp", ""))
    return task, started


def session_transcripts(session: Path) -> List[Transcript]:
    """The sub-agent transcripts stored beside a session JSONL, in path order."""
    folder = session.with_suffix("") / SUBAGENTS_DIR
    transcripts: List[Transcript] = []
    for path in sorted(folder.rglob(TRANSCRIPT_GLOB)):
        task, started = read_task(path)
        ids = frozenset(_ids(path.relative_to(folder).as_posix()))
        transcripts.append(Transcript(path.name, ids, task, started))
    return transcripts


def session_ids(path: Path) -> Set[str]:
    """Sub-agent and workflow run ids of a session: its ``agentId``/``runId`` fields and its transcripts' paths."""
    raw = path.read_text(encoding="utf-8")
    ids = {"agent-" + ident for ident in SESSION_AGENT_ID_RE.findall(raw)} | set(SESSION_RUN_ID_RE.findall(raw))
    for transcript in session_transcripts(path):
        ids |= transcript.ids
    return ids


def unlisted_session_ids(log_text: str, session_files: Sequence[Path]) -> List[str]:
    """Sub-agent and workflow run ids of the sessions that no Actions line lists, sorted."""
    listed = _listed_ids(parse_entries(log_text, Report()))
    known: Set[str] = set()
    for path in session_files:
        known |= session_ids(path)
    return sorted(known - listed)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def task_quote(task: str, lines: int = QUOTE_LINES) -> str:
    """The first ``lines`` lines of a task text followed by its sha256 marker line."""
    task_lines = task.split("\n")
    shown = task_lines[:max(lines, 1)]
    marker = "[task sha256=%s, first %d of %d lines]" % (_sha256(task), len(shown), len(task_lines))
    return "\n".join(shown + [marker])


def quotes_task(prompt: Sequence[str], task: str) -> bool:
    """True when the prompt lines hold the whole task text or a valid first-N-lines quote of it.

    Lines are compared without leading and trailing whitespace.
    """
    if _normalize(task) and _normalize(task) in _normalize("\n".join(prompt)):
        return True
    digest = _sha256(task)
    task_lines = [line.strip() for line in task.split("\n")]
    for index, line in enumerate(prompt):
        marker = TASK_QUOTE_RE.match(line.strip())
        if marker is None or marker.group(1) != digest or int(marker.group(3)) != len(task_lines):
            continue
        count = int(marker.group(2))
        if 1 <= count <= index and [text.strip() for text in prompt[index - count:index]] == task_lines[:count]:
            return True
    return False


def unquoted_tasks(log_text: str, session_files: Sequence[Path]) -> List[str]:
    """Names of the sub-agent transcripts started at or after LEGACY_CUTOFF whose task no listing entry quotes."""
    turns = [(_actions_ids(sections), [line for _, line in sections[PROMPT_LABEL]])
             for _, sections in _turn_sections(parse_entries(log_text, Report()))]
    missing: List[str] = []
    for session in session_files:
        for transcript in session_transcripts(session):
            if _is_legacy(transcript.started):
                continue
            if not any(transcript.ids & listed and quotes_task(prompt, transcript.task) for listed, prompt in turns):
                missing.append(transcript.name)
    return sorted(set(missing))


def pending_transcripts(log_text: str, session_files: Sequence[Path]) -> List[Transcript]:
    """Transcripts with an unlisted id or an unquoted task, in path order."""
    unlisted = set(unlisted_session_ids(log_text, session_files))
    unquoted = set(unquoted_tasks(log_text, session_files))
    return [transcript
            for session in session_files
            for transcript in session_transcripts(session)
            if transcript.ids & unlisted or transcript.name in unquoted]


def render_pending(transcripts: Sequence[Transcript], lines: int = QUOTE_LINES) -> str:
    """Paste-ready prompt text for a group entry: one header and quote per transcript."""
    blocks = ["Sub-agent %s task (started %s):\n%s" % (" in ".join(sorted(transcript.ids)), transcript.started,
                                                        task_quote(transcript.task, lines))
              for transcript in transcripts]
    return "\n\n".join(blocks)


def trace_problems(log_text: str, session_files: Sequence[Path], excluded: Set[str] = frozenset()) -> List[str]:
    """Everything ``--trace`` reports for the given session files."""
    problems = ["user prompt not in log (sha256 %s): %s" % (_sha256(prompt), prompt[:120])
                for prompt in unlogged_prompts(log_text, session_files, excluded)]
    problems += session_start_problems(log_text, session_files)
    problems += ["sub-agent or workflow id %s is not on any Actions line" % ident
                 for ident in unlisted_session_ids(log_text, session_files)]
    problems += ["sub-agent task of %s is not quoted in an entry that lists its id" % name
                 for name in unquoted_tasks(log_text, session_files)]
    return problems


def baseline_problem(log_path: Path, ref: str) -> Optional[str]:
    """None when the log at REF is a byte prefix of the current log; otherwise the reason (fails closed)."""
    result = subprocess.run(
        ["git", "-C", str(log_path.parent), "show", "%s:./%s" % (ref, log_path.name)],
        capture_output=True,
    )
    if result.returncode != 0:
        return "cannot read %s at %s: %s" % (log_path.name, ref, result.stderr.decode("utf-8", "replace").strip())
    if not log_path.read_bytes().startswith(result.stdout):
        return "%s at %s is not a prefix of the current log (not append-only)" % (log_path.name, ref)
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lint log.txt against AGENTS.md section 5.")
    parser.add_argument("log", type=Path, nargs="?")
    parser.add_argument("--trace", type=Path, action="append", default=[], metavar="SESSION_JSONL")
    parser.add_argument("--exclusions", type=Path, default=EXCLUSIONS_FILE, metavar="FILE",
                        help="sha256 digests of prompts the user asked to keep out of the log")
    parser.add_argument("--pending", action="store_true",
                        help="with --trace: print paste-ready group-entry text for every unlisted or unquoted transcript")
    parser.add_argument("--baseline-ref", metavar="REF")
    parser.add_argument("--quote", type=Path, metavar="SUBAGENT_JSONL",
                        help="print the task quote of a sub-agent transcript and exit")
    parser.add_argument("--quote-lines", type=int, default=QUOTE_LINES, metavar="N")
    args = parser.parse_args(argv)
    if args.quote:
        print(task_quote(read_task(args.quote)[0], args.quote_lines))
        return 0
    if args.log is None:
        parser.error("the log path is required")

    text = args.log.read_bytes().decode("utf-8")
    if args.pending:
        print(render_pending(pending_transcripts(text, args.trace), args.quote_lines))
        return 0
    report = lint(text)
    for finding in report.warnings:
        print("%s:%d: WARNING %s" % (args.log, finding.line, finding.message))
    for finding in report.errors:
        print("%s:%d: ERROR %s" % (args.log, finding.line, finding.message))
    failed = bool(report.errors)
    for problem in trace_problems(text, args.trace, read_exclusions(args.exclusions)):
        print("TRACE: %s" % problem)
        failed = True
    if args.baseline_ref:
        problem = baseline_problem(args.log, args.baseline_ref)
        if problem:
            print("BASELINE: %s" % problem)
            failed = True
    print("%s: %d error(s), %d warning(s)" % (args.log, len(report.errors), len(report.warnings)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
