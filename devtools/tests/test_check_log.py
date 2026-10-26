"""Tests for devtools.check_log and devtools.append_log (AGENTS section 5; SCORING_STRATEGY X1-X3).

Every error class of the linter has a negative fixture; append_log output must always lint clean.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from unittest import mock

from devtools import append_log, check_log

APPEND_LOG_SCRIPT = Path(append_log.__file__).resolve()

SESSION = """\
## [2026-01-01T10:00:00Z] SESSION START

tool=Claude Code
model=claude-opus-5-5
Repo Root: /work/repo
Branch: main
Worktree: main
Parent Agent: none
Language: py
Time Remaining: not configured

"""

TURN = """\
## [2026-01-01T10:05:00Z] Explain the problem

User Prompt (verbatim, secrets redacted):
explain the problem statement

Agent Response Summary:
Explained the problem. No files changed.

Actions:
* read problem_statement.md

Context:
tool=Claude Code
model=claude-opus-5-5
branch=main
repo_root=/work/repo
worktree=main
parent_agent=none

"""


NEW_TURN = TURN.replace("2026-01-01T10:05:00Z", "2026-10-25T10:05:00Z")
SIX_SENTENCES = "A one. B two. C three. D four. E five. F six."
AGENT_ID = "agent-a5d718e3cfde5b46d"
RUN_ID = "wf_173ce708-f03"


def errors_of(text: str) -> List[str]:
    return [finding.message for finding in check_log.lint(text).errors]


def warnings_of(text: str) -> List[str]:
    return [finding.message for finding in check_log.lint(text).warnings]


def has(messages: List[str], fragment: str) -> bool:
    return any(fragment in message for message in messages)


class LintPositiveTest(unittest.TestCase):
    def test_valid_log_has_no_findings(self) -> None:
        report = check_log.lint(SESSION + TURN)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_equal_timestamps_and_offset_timestamps_are_accepted(self) -> None:
        text = SESSION + TURN.replace("2026-01-01T10:05:00Z", "2026-01-01T10:00:00Z")
        self.assertEqual(errors_of(text), [])
        text = SESSION + TURN.replace("2026-01-01T10:05:00Z", "2026-01-01T12:05:00+02:00")
        self.assertEqual(errors_of(text), [])

    def test_any_number_of_fractional_second_digits_is_accepted(self) -> None:
        for good in ("2026-01-01T10:05:00.1Z", "2026-01-01T10:05:00.12Z", "2026-01-01T10:05:00.123456789+00:00"):
            self.assertEqual(errors_of(SESSION + TURN.replace("2026-01-01T10:05:00Z", good)), [], good)

    def test_branch_unknown_is_allowed_as_agents_template_says(self) -> None:
        self.assertEqual(errors_of(SESSION.replace("Branch: main", "Branch: unknown") + TURN), [])


class LintNegativeTest(unittest.TestCase):
    def test_first_entry_must_be_session_start(self) -> None:
        self.assertTrue(has(errors_of(TURN), "first entry must be SESSION START"))

    def test_empty_log(self) -> None:
        self.assertTrue(has(errors_of(""), "no entries"))

    def test_text_before_first_header(self) -> None:
        self.assertTrue(has(errors_of("stray\n" + SESSION), "before the first entry header"))

    def test_malformed_header(self) -> None:
        self.assertTrue(has(errors_of(SESSION + "## [2026-01-01T10:06:00Z]\nbody\n"), "malformed entry header"))

    def test_session_missing_and_repeated_keys(self) -> None:
        self.assertTrue(has(errors_of(SESSION.replace("Language: py\n", "") + TURN), "missing key 'Language'"))
        self.assertTrue(has(errors_of(SESSION.replace("Branch: main\n", "Branch: main\nBranch: dev\n") + TURN), "more than once"))
        self.assertTrue(has(errors_of(SESSION.replace("tool=Claude Code\n", "") + TURN), "missing key 'tool'"))

    def test_session_unexpected_line(self) -> None:
        self.assertTrue(has(errors_of(SESSION.replace("Language: py\n", "Language: py\nExtra: 1\n") + TURN), "unexpected line"))

    def test_turn_sections_out_of_order_or_missing(self) -> None:
        swapped = TURN.replace("Actions:", "Context:", 1).replace("Context:\ntool", "Actions:\ntool", 1)
        self.assertTrue(has(errors_of(SESSION + swapped), "section"))
        no_actions = TURN.replace("Actions:\n* read problem_statement.md\n\n", "")
        self.assertTrue(has(errors_of(SESSION + no_actions), "'Actions:'"))

    def test_empty_prompt_and_summary(self) -> None:
        empty_prompt = TURN.replace("explain the problem statement\n", "\n")
        self.assertTrue(has(errors_of(SESSION + empty_prompt), "prompt is empty"))
        empty_summary = TURN.replace("Explained the problem. No files changed.\n", "\n")
        self.assertTrue(has(errors_of(SESSION + empty_summary), "summary is empty"))

    def test_actions_must_be_star_bullets(self) -> None:
        self.assertTrue(has(errors_of(SESSION + TURN.replace("* read", "- read")), "'* ' bullet"))
        self.assertTrue(has(errors_of(SESSION + TURN.replace("* read problem_statement.md\n", "")), "no bullets"))

    def test_context_keys_exactly_once(self) -> None:
        self.assertTrue(has(errors_of(SESSION + TURN.replace("worktree=main\n", "")), "missing key 'worktree'"))
        self.assertTrue(has(errors_of(SESSION + TURN.replace("branch=main\n", "branch=main\nbranch=dev\n")), "more than once"))

    def test_tool_must_be_allowlisted(self) -> None:
        for bad in ("AI", "", "<tool>", "claude-opus-5-5", "Some Other Agent"):
            self.assertTrue(errors_of(SESSION + TURN.replace("tool=Claude Code", "tool=%s" % bad)), bad)

    def test_model_must_be_a_model_id(self) -> None:
        for bad in ("unknown", "", "claude", "<model>", "Claude Opus", "claude-unknown", "model-placeholder", "generic-model"):
            self.assertTrue(
                errors_of(SESSION + TURN.replace("model=claude-opus-5-5", "model=%s" % bad)), "model=%r" % bad
            )

    def test_real_model_ids_are_accepted(self) -> None:
        for good in ("claude-opus-5-5", "claude-sonnet-5-5", "gpt-5.1-codex", "gemini-2.5-pro", "o3-mini"):
            self.assertEqual(errors_of(SESSION + TURN.replace("model=claude-opus-5-5", "model=%s" % good)), [], good)

    def test_blank_context_value(self) -> None:
        self.assertTrue(has(errors_of(SESSION + TURN.replace("branch=main", "branch=")), "branch is blank"))

    def test_template_placeholder_value(self) -> None:
        text = SESSION + TURN.replace("branch=main", "branch=<git_branch_or_unknown>")
        self.assertTrue(has(errors_of(text), "template placeholder"))

    def test_text_between_header_and_prompt_label(self) -> None:
        text = SESSION + TURN.replace("Explain the problem\n\n", "Explain the problem\nstray\n")
        self.assertTrue(has(errors_of(text), "between the header and the prompt label"))

    def test_timestamps(self) -> None:
        backwards = TURN.replace("2026-01-01T10:05:00Z", "2026-01-01T09:00:00Z")
        self.assertTrue(has(errors_of(SESSION + backwards), "goes backwards"))
        for bad in ("2026-01-01 10:05:00", "2026-01-01T10:05:00", "yesterday", "2026-13-01T10:05:00Z"):
            self.assertTrue(has(errors_of(SESSION + TURN.replace("2026-01-01T10:05:00Z", bad)), "timestamp"), bad)

    def test_title_length(self) -> None:
        long_title = "x" * (check_log.TITLE_MAX_CHARS + 1)
        self.assertTrue(has(errors_of(SESSION + TURN.replace("Explain the problem", long_title)), "title is 81"))
        ok_title = "x" * check_log.TITLE_MAX_CHARS
        self.assertEqual(errors_of(SESSION + TURN.replace("Explain the problem", ok_title)), [])

    def test_carriage_return(self) -> None:
        self.assertTrue(has(errors_of((SESSION + TURN).replace("\n", "\r\n")), "CR character"))

    def test_secret_patterns(self) -> None:
        secrets = (
            "key sk-ant-abcdef",
            "key sk-abcdefghijklmnopqrstuvwx",
            "id AKIAABCDEFGHIJKLMNOP",
            "-----BEGIN RSA PRIVATE KEY-----",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
            "api_key=hunter2hunter2",
            "API-KEY: hunter2",
        )
        for secret in secrets:
            text = SESSION + TURN.replace("explain the problem statement", secret)
            self.assertTrue(has(errors_of(text), "possible secret"), secret)

    def test_redacted_and_benign_text_is_not_a_secret(self) -> None:
        benign = "api_key=[REDACTED] and ANTHROPIC_API_KEY env var, task-based disk-cache, risk-free"
        self.assertEqual(errors_of(SESSION + TURN.replace("explain the problem statement", benign)), [])


class LintWarningTest(unittest.TestCase):
    def test_summary_sentence_count(self) -> None:
        one = TURN.replace("Explained the problem. No files changed.", "Explained the problem.")
        self.assertTrue(has(warnings_of(SESSION + one), "1 sentences"))
        six = TURN.replace("Explained the problem. No files changed.", "A one. B two. C three. D four. E five. F six.")
        self.assertTrue(has(warnings_of(SESSION + six), "6 sentences"))
        five = TURN.replace("Explained the problem. No files changed.", "A one. B two. C three. D four. E five.")
        self.assertEqual(warnings_of(SESSION + five), [])

    def test_abbreviations_do_not_split_sentences(self) -> None:
        text = TURN.replace("Explained the problem. No files changed.", "Raised f1 from 0.91 to 0.96, e.g. golden 30/32. Done.")
        self.assertEqual(warnings_of(SESSION + text), [])

    def test_email_like_string_in_a_legacy_entry_warns(self) -> None:
        text = SESSION + TURN.replace("explain the problem statement", "contact someone@example.com")
        self.assertTrue(has(warnings_of(text), "email-like"))
        self.assertEqual(errors_of(text), [])


class TraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session_file = Path(self.tmp.name) / "session.jsonl"

    def write_session(self, records: List[Dict[str, object]]) -> None:
        self.session_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    @staticmethod
    def user(content: object, **extra: object) -> Dict[str, object]:
        record: Dict[str, object] = {"type": "user", "message": {"role": "user", "content": content}}
        record.update(extra)
        return record

    def test_missing_prompt_is_listed_and_logged_prompt_is_not(self) -> None:
        self.write_session([self.user("explain   the problem statement"), self.user("do something new")])
        self.assertEqual(check_log.unlogged_prompts(SESSION + TURN, [self.session_file]), ["do something new"])

    def test_non_typed_records_are_skipped(self) -> None:
        self.write_session([
            self.user([{"type": "tool_result", "content": "x"}]),
            self.user("!ls"),
            self.user("<command-name>/plan</command-name>"),
            self.user("<task-notification>done</task-notification>"),
            self.user("<system-reminder>context</system-reminder>"),
            self.user("[Request interrupted by user]"),
            self.user("side chain prompt", isSidechain=True),
            self.user("meta prompt", isMeta=True),
            {"type": "assistant", "message": {"content": "hello"}},
            self.user("   "),
        ])
        self.assertEqual(check_log.unlogged_prompts(SESSION + TURN, [self.session_file]), [])

    def test_rewind_resends_collapse_and_text_blocks_are_read(self) -> None:
        self.write_session([self.user("new work"), self.user([{"type": "text", "text": "new work"}])])
        self.assertEqual(check_log.session_prompts(self.session_file), ["new work"])

    def unlogged_with(self, logged_prompt: str, typed: List[object]) -> List[str]:
        self.write_session([self.user(content) for content in typed])
        log = SESSION + TURN.replace("explain the problem statement", logged_prompt)
        return check_log.unlogged_prompts(log, [self.session_file])

    def test_redacted_wildcard_matches_the_whole_prompt(self) -> None:
        self.assertEqual(self.unlogged_with("use key [REDACTED] now", ["use key abc123 now"]), [])
        self.assertEqual(self.unlogged_with("use key [REDACTED] now", ["use key abc123 now and more"]),
                         ["use key abc123 now and more"])

    def test_only_redacted_log_prompt_matches_nothing(self) -> None:
        self.assertEqual(self.unlogged_with("[REDACTED]", ["anything at all"]), ["anything at all"])

    def test_short_logged_prompt_does_not_cover_a_longer_prompt(self) -> None:
        self.assertEqual(self.unlogged_with("yes", ["yes please delete everything"]), ["yes please delete everything"])

    def test_one_entry_may_log_consecutive_prompts(self) -> None:
        logged = "create the plan (follow-up) don't change code"
        self.assertEqual(self.unlogged_with(logged, ["create the plan", "don't change code"]), [])
        self.assertEqual(self.unlogged_with(logged, ["the plan"]), ["the plan"])

    def test_prompt_with_attached_image_is_checked(self) -> None:
        typed = [[{"type": "text", "text": "what is in this screenshot"}, {"type": "image", "source": {}}]]
        self.assertEqual(self.unlogged_with("something else", typed), ["what is in this screenshot"])

    def test_prompt_starting_with_a_path_is_not_a_slash_command(self) -> None:
        prompt = "/" + "Users/x/file.py is broken"  # split so the packager scan skips this file
        self.assertEqual(self.unlogged_with("something else", [prompt]), [prompt])

    def test_cli_exit_code_reports_unlogged_turn(self) -> None:
        log_path = Path(self.tmp.name) / "log.txt"
        log_path.write_bytes((SESSION + TURN).encode("utf-8"))
        self.write_session([self.user("never logged")])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session_file)]), 1)
            self.write_session([self.user("explain the problem statement")])
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session_file)]), 0)

    def test_excluded_prompt_digest_is_skipped(self) -> None:
        self.write_session([self.user("do  not store this"), self.user("do something new")])
        excluded = {hashlib.sha256(b"do not store this").hexdigest()}
        self.assertEqual(check_log.unlogged_prompts(SESSION + TURN, [self.session_file], excluded), ["do something new"])

    def test_exclusions_file_holds_digests_and_comments_only(self) -> None:
        path = Path(self.tmp.name) / "exclusions.txt"
        digest = "a" * 64
        path.write_text("# reason\n\n  %s  \nnot a digest\n%s\n" % (digest, "b" * 63), encoding="utf-8")
        self.assertEqual(check_log.read_exclusions(path), {digest})
        self.assertEqual(check_log.read_exclusions(path.with_name("missing.txt")), set())

    def test_cli_trace_prints_the_digest_and_honours_exclusions(self) -> None:
        log_path = Path(self.tmp.name) / "log.txt"
        log_path.write_bytes((SESSION + TURN).encode("utf-8"))
        self.write_session([self.user("never logged")])
        digest = hashlib.sha256(b"never logged").hexdigest()
        exclusions = Path(self.tmp.name) / "exclusions.txt"
        exclusions.write_text("# kept out at the user's request\n%s\n" % digest, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session_file),
                                             "--exclusions", str(exclusions.with_name("none.txt"))]), 1)
        self.assertIn("user prompt not in log (sha256 %s): never logged" % digest, out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session_file),
                                             "--exclusions", str(exclusions)]), 0)


class LintV2Test(unittest.TestCase):
    def test_new_entry_with_more_than_five_sentences_is_an_error(self) -> None:
        text = SESSION + NEW_TURN.replace("Explained the problem. No files changed.", SIX_SENTENCES)
        self.assertTrue(has(errors_of(text), "6 sentences"))
        self.assertFalse(has(warnings_of(text), "6 sentences"))

    def test_legacy_entry_with_more_than_five_sentences_is_a_warning(self) -> None:
        text = SESSION + TURN.replace("Explained the problem. No files changed.", SIX_SENTENCES)
        self.assertEqual(errors_of(text), [])
        self.assertTrue(has(warnings_of(text), "6 sentences"))

    def test_entry_stamped_at_the_cutoff_is_new(self) -> None:
        text = SESSION + NEW_TURN.replace("2026-10-25T10:05:00Z", check_log.LEGACY_CUTOFF)
        text = text.replace("Explained the problem. No files changed.", SIX_SENTENCES)
        self.assertTrue(has(errors_of(text), "6 sentences"))

    def test_agent_id_must_be_listed_on_an_actions_line(self) -> None:
        mention = NEW_TURN.replace("Explained the problem.", "Explained the problem with %s." % AGENT_ID)
        self.assertTrue(has(errors_of(SESSION + mention), "%s is not listed" % AGENT_ID))
        listed = mention.replace("* read problem_statement.md", "* read problem_statement.md\n* ran %s" % AGENT_ID)
        self.assertEqual(errors_of(SESSION + listed), [])

    def test_unlisted_run_id_on_a_legacy_entry_is_a_warning(self) -> None:
        text = SESSION + TURN.replace("Explained the problem.", "Explained the problem in %s." % RUN_ID)
        self.assertEqual(errors_of(text), [])
        self.assertTrue(has(warnings_of(text), "%s is not listed" % RUN_ID))

    def test_each_unlisted_id_is_reported_once(self) -> None:
        text = SESSION + NEW_TURN.replace("Explained the problem.", "Explained %s and %s again %s." % ((RUN_ID,) * 3))
        self.assertEqual(sum(RUN_ID in message for message in errors_of(text)), 1)

    def test_email_like_string_in_a_new_entry_is_an_error(self) -> None:
        text = SESSION + NEW_TURN.replace("explain the problem statement", "contact someone@example.com")
        self.assertTrue(has(errors_of(text), "email-like"))
        self.assertFalse(has(warnings_of(text), "email-like"))

    def test_entry_stamped_at_the_pii_cutoff_is_new(self) -> None:
        text = SESSION + NEW_TURN.replace("2026-10-25T10:05:00Z", check_log.PII_CUTOFF)
        self.assertTrue(has(errors_of(text.replace("Explain the problem", "Mail someone@example.com")), "email-like"))

    def test_ids_must_have_the_documented_shape(self) -> None:
        for near_miss in ("agent-12345", "agent-A5D718E3CFDE5B46D", "wf_173ce708", "wf-173ce708-f03"):
            text = SESSION + NEW_TURN.replace("Explained the problem.", "Explained %s." % near_miss)
            self.assertEqual(errors_of(text), [], near_miss)


class TraceV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def session_file(self, name: str, prompts: List[str], extra: Optional[List[Dict[str, object]]] = None) -> Path:
        records: List[Dict[str, object]] = [
            {"type": "user", "message": {"role": "user", "content": prompt}} for prompt in prompts
        ]
        records += extra or []
        path = self.dir / name
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return path

    def test_every_session_file_is_checked(self) -> None:
        first = self.session_file("a.jsonl", ["first session task"])
        second = self.session_file("b.jsonl", ["second session task"])
        problems = check_log.trace_problems(SESSION + TURN, [first, second])
        self.assertEqual(problems, [
            "user prompt not in log (sha256 %s): %s" % (hashlib.sha256(prompt.encode("utf-8")).hexdigest(), prompt)
            for prompt in ("first session task", "second session task")
        ])

    def test_second_session_needs_its_own_session_start(self) -> None:
        first = self.session_file("a.jsonl", ["explain the problem statement"])
        second = self.session_file("b.jsonl", ["second session task"])
        second_turn = TURN.replace("2026-01-01T10:05:00Z", "2026-01-01T10:15:00Z").replace(
            "explain the problem statement", "second session task")
        restart = SESSION.replace("2026-01-01T10:00:00Z", "2026-01-01T10:10:00Z")
        self.assertEqual(len(check_log.session_start_problems(SESSION + TURN + second_turn, [first, second])), 1)
        self.assertEqual(check_log.session_start_problems(SESSION + TURN + restart + second_turn, [first, second]), [])

    def test_session_ids_come_from_agent_id_and_run_id_fields_only(self) -> None:
        path = self.session_file("s.jsonl", ["task"], extra=[
            {"type": "progress", "agentId": AGENT_ID.split("-", 1)[1]},
            {"type": "progress", "toolUseResult": {"runId": RUN_ID}},
            {"type": "progress", "toolUseResult": {"runId": "0mvmi3acd-e1a95515"}},
            {"type": "progress", "message": {"content": "a report quoting agent-0123456789abcdef0"}},
        ])
        self.assertEqual(check_log.session_ids(path), {AGENT_ID, RUN_ID})

    def test_unlisted_session_ids_are_reported_until_an_actions_line_lists_them(self) -> None:
        path = self.session_file("s.jsonl", ["explain the problem statement"], extra=[
            {"type": "progress", "agentId": AGENT_ID.split("-", 1)[1]},
            {"type": "progress", "runId": RUN_ID},
        ])
        self.assertEqual(check_log.unlisted_session_ids(SESSION + TURN, [path]), [AGENT_ID, RUN_ID])
        listed = TURN.replace("* read problem_statement.md", "* read problem_statement.md\n* ran %s and %s" % (AGENT_ID, RUN_ID))
        self.assertEqual(check_log.unlisted_session_ids(SESSION + listed, [path]), [])

    def test_cli_trace_exit_code_covers_all_session_files(self) -> None:
        log_path = self.dir / "log.txt"
        log_path.write_bytes((SESSION + TURN).encode("utf-8"))
        first = self.session_file("a.jsonl", ["explain the problem statement"])
        second = self.session_file("b.jsonl", ["never logged"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(first), "--trace", str(second)]), 1)
            self.assertEqual(check_log.main([str(log_path), "--trace", str(first)]), 0)


class SubagentTraceTest(unittest.TestCase):
    """Sub-agent transcripts beside a session: ids on Actions lines and quoted task texts."""

    TASK = "Implement T99 widget\n\n  run the tests\nreport back"
    WORKFLOW_AGENT = "agent-0a1b2c3d4e5f6a7b8"
    NEW_START = "2026-10-25T09:00:00Z"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Path(self.tmp.name) / "s1.jsonl"
        self.session.write_text(json.dumps({"type": "user", "message": {"content": "explain the problem statement"}}) + "\n",
                                encoding="utf-8")

    def transcript(self, relative: str, tasks: List[str], started: str = NEW_START) -> Path:
        path = self.session.with_suffix("") / "subagents" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{"type": "user", "isSidechain": True, "timestamp": started, "message": {"content": task}}
                   for task in tasks]
        records += [{"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
                    {"type": "user", "message": {"content": "later message"}}]
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return path

    def workflow_transcript(self, started: str = NEW_START) -> Path:
        relay = "[Workflow harness — user request] relayed request"
        return self.transcript("workflows/%s/%s.jsonl" % (RUN_ID, self.WORKFLOW_AGENT), [relay, self.TASK], started)

    def log_with(self, prompt: str, actions: str) -> str:
        turn = NEW_TURN.replace("explain the problem statement", prompt)
        return SESSION + turn.replace("* read problem_statement.md", actions)

    def test_transcript_ids_beside_the_session_are_collected(self) -> None:
        self.transcript("%s.jsonl" % AGENT_ID, [self.TASK])
        self.workflow_transcript()
        self.assertEqual(check_log.session_ids(self.session), {AGENT_ID, self.WORKFLOW_AGENT, RUN_ID})
        self.assertEqual(check_log.unlisted_session_ids(SESSION + TURN, [self.session]),
                         [self.WORKFLOW_AGENT, AGENT_ID, RUN_ID])

    def test_task_is_the_last_user_record_that_opens_the_transcript(self) -> None:
        self.assertEqual(check_log.read_task(self.workflow_transcript()), (self.TASK, self.NEW_START))

    def test_quote_of_the_first_lines_with_sha256_is_accepted(self) -> None:
        quote = check_log.task_quote(self.TASK, 2).split("\n")
        self.assertEqual(quote[:2], ["Implement T99 widget", ""])
        self.assertRegex(quote[2], r"^\[task sha256=[0-9a-f]{64}, first 2 of 4 lines\]$")
        self.assertTrue(check_log.quotes_task(["T99: implement per task file"] + quote, self.TASK))
        self.assertTrue(check_log.quotes_task(["  Implement T99 widget  ", "", quote[2]], self.TASK))

    def test_whole_task_quoted_verbatim_is_accepted(self) -> None:
        self.assertTrue(check_log.quotes_task(["Implement T99 widget run the", "tests report back"], self.TASK))

    def test_bad_quotes_are_rejected(self) -> None:
        good = check_log.task_quote(self.TASK, 2).split("\n")
        wrong_hash = good[:2] + [good[2].replace(good[2][13:17], "0000")]
        wrong_total = good[:2] + [good[2].replace("of 4", "of 5")]
        wrong_line = ["Implement T98 widget"] + good[1:]
        missing_lines = good[2:]
        for prompt in (wrong_hash, wrong_total, wrong_line, missing_lines, ["T99 summary only"]):
            self.assertFalse(check_log.quotes_task(prompt, self.TASK), prompt)

    def test_new_task_must_be_quoted_in_an_entry_that_lists_its_id(self) -> None:
        self.workflow_transcript()
        quote = "T99 summary\n" + check_log.task_quote(self.TASK)
        name = "%s.jsonl" % self.WORKFLOW_AGENT
        self.assertEqual(check_log.unquoted_tasks(SESSION + TURN, [self.session]), [name])
        unlisted = self.log_with(quote, "* ran the widget task")
        self.assertEqual(check_log.unquoted_tasks(unlisted, [self.session]), [name])
        by_run = self.log_with(quote, "* workflow %s" % RUN_ID)
        self.assertEqual(check_log.unquoted_tasks(by_run, [self.session]), [])
        by_agent = self.log_with(quote, "* sub-agent %s" % self.WORKFLOW_AGENT)
        self.assertEqual(check_log.unquoted_tasks(by_agent, [self.session]), [])

    def test_transcript_started_before_the_cutoff_is_exempt(self) -> None:
        self.workflow_transcript(started="2026-01-01T10:00:00Z")
        self.assertEqual(check_log.unquoted_tasks(SESSION + TURN, [self.session]), [])

    def test_cli_trace_reports_subagents_and_quote_prints_the_marker(self) -> None:
        path = self.workflow_transcript()
        log_path = Path(self.tmp.name) / "log.txt"
        log_path.write_bytes((SESSION + TURN).encode("utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session)]), 1)
        self.assertIn("%s is not on any Actions line" % self.WORKFLOW_AGENT, out.getvalue())
        self.assertIn("task of %s.jsonl is not quoted" % self.WORKFLOW_AGENT, out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_log.main(["--quote", str(path), "--quote-lines", "1"]), 0)
        self.assertEqual(out.getvalue(), check_log.task_quote(self.TASK, 1) + "\n")
        logged = self.log_with("T99 summary\n" + check_log.task_quote(self.TASK), "* workflow %s agent %s" % (
            RUN_ID, self.WORKFLOW_AGENT))
        log_path.write_bytes(logged.replace("2026-10-25T10:05:00Z", "2026-01-01T10:05:00Z").encode("utf-8"))
        session_prompt = json.dumps({"type": "user", "message": {"content": "T99 summary"}})
        self.session.write_text(session_prompt + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session)]), 0)

    def test_pending_covers_unlisted_or_unquoted_transcripts_until_the_log_does(self) -> None:
        self.workflow_transcript()
        self.transcript("%s.jsonl" % AGENT_ID, [self.TASK], started="2026-01-01T10:00:00Z")
        pending = check_log.pending_transcripts(SESSION + TURN, [self.session])
        self.assertEqual([t.name for t in pending], ["%s.jsonl" % AGENT_ID, "%s.jsonl" % self.WORKFLOW_AGENT])
        quote = "T99 summary\n" + check_log.task_quote(self.TASK)
        covered = self.log_with(quote, "* workflow %s agents %s %s" % (RUN_ID, self.WORKFLOW_AGENT, AGENT_ID))
        self.assertEqual(check_log.pending_transcripts(covered, [self.session]), [])
        legacy_listed = self.log_with("other prompt", "* agent %s" % AGENT_ID)
        self.assertEqual([t.name for t in check_log.pending_transcripts(legacy_listed, [self.session])],
                         ["%s.jsonl" % self.WORKFLOW_AGENT])

    def test_rendered_pending_text_names_the_ids_and_quotes_the_task(self) -> None:
        self.workflow_transcript()
        text = check_log.render_pending(check_log.pending_transcripts(SESSION + TURN, [self.session]), 2)
        header = "Sub-agent %s in %s task (started %s):" % (self.WORKFLOW_AGENT, RUN_ID, self.NEW_START)
        self.assertEqual(text.split("\n")[0], header)
        self.assertTrue(check_log.quotes_task(text.split("\n"), self.TASK))
        pasted = self.log_with(text, "* workflow %s agent %s" % (RUN_ID, self.WORKFLOW_AGENT))
        self.assertEqual(check_log.unquoted_tasks(pasted, [self.session]), [])

    def test_cli_pending_prints_the_blocks(self) -> None:
        self.workflow_transcript()
        log_path = Path(self.tmp.name) / "log.txt"
        log_path.write_bytes((SESSION + TURN).encode("utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_log.main([str(log_path), "--trace", str(self.session), "--pending"]), 0)
        self.assertIn("Sub-agent %s in %s task" % (self.WORKFLOW_AGENT, RUN_ID), out.getvalue())
        self.assertIn(check_log.task_quote(self.TASK), out.getvalue())

    def test_cli_requires_a_log_without_quote(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check_log.main([])


class BaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.log = self.repo / "log.txt"
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test")
        self.git("init", "-q")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo)] + list(args), check=True, env=self.env, capture_output=True)

    def commit_log(self, text: str) -> None:
        self.log.write_bytes(text.encode("utf-8"))
        self.git("add", "log.txt")
        self.git("commit", "-q", "-m", "log")

    def test_appended_log_is_prefix(self) -> None:
        self.commit_log(SESSION)
        self.log.write_bytes((SESSION + TURN).encode("utf-8"))
        self.assertIsNone(check_log.baseline_problem(self.log, "HEAD"))

    def test_rewritten_log_is_rejected(self) -> None:
        self.commit_log(SESSION + TURN)
        self.log.write_bytes((SESSION + TURN.replace("Explain", "Rewrite")).encode("utf-8"))
        self.assertIn("not append-only", check_log.baseline_problem(self.log, "HEAD") or "")

    def test_missing_ref_or_file_fails_closed(self) -> None:
        self.commit_log(SESSION)
        self.assertIn("cannot read", check_log.baseline_problem(self.log, "no-such-ref") or "")
        self.git("rm", "-q", "--cached", "log.txt")
        self.git("commit", "-q", "-m", "drop")
        self.assertIn("cannot read", check_log.baseline_problem(self.log, "HEAD") or "")

    def test_cli_baseline_fails_closed_when_ref_has_no_log(self) -> None:
        self.commit_log(SESSION)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(self.log), "--baseline-ref", "HEAD"]), 0)
            self.assertEqual(check_log.main([str(self.log), "--baseline-ref", "no-such-ref"]), 1)


class AppendLogTest(unittest.TestCase):
    NOW = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "log.txt"
        self.prompt = self.dir / "prompt.txt"
        self.prompt.write_text("do the thing\nwith two lines\n", encoding="utf-8")

    def session_args(self) -> List[str]:
        return ["--kind", "session", "--tool", "Claude Code", "--model", "claude-opus-5-5",
                "--branch", "main", "--repo-root", "/work/repo", "--log", str(self.log)]

    def turn_args(self, **overrides: str) -> List[str]:
        values = {"--title": "Do the thing", "--summary": "Did it. It works.", "--tool": "Claude Code",
                  "--model": "claude-sonnet-5-5"}
        values.update(overrides)
        args = ["--kind", "turn", "--prompt-file", str(self.prompt), "--action", "edited a.py",
                "--action", "ran tests\nsecond line", "--branch", "main", "--repo-root", "/work/repo",
                "--log", str(self.log)]
        for flag, value in values.items():
            args += [flag, value]
        return args

    def run_main(self, args: List[str], now: Optional[datetime] = None) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return append_log.main(args, now=now or self.NOW)

    def test_session_then_turn_lint_clean(self) -> None:
        self.assertEqual(self.run_main(self.session_args()), 0)
        self.assertEqual(self.run_main(self.turn_args(), now=self.NOW.replace(minute=5)), 0)
        text = self.log.read_bytes().decode("utf-8")
        self.assertEqual(errors_of(text), [])
        self.assertEqual(warnings_of(text), [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_log.main([str(self.log)]), 0)
        self.assertIn("## [2026-01-01T11:05:00Z] Do the thing\n", text)
        self.assertIn("* ran tests second line\n", text)
        self.assertTrue(text.endswith("parent_agent=none\n\n"))
        self.assertEqual(check_log.logged_prompts(text), ["do the thing with two lines"])

    def test_existing_log_without_trailing_blank_line_gets_separated(self) -> None:
        self.log.write_bytes(SESSION.rstrip("\n").encode("utf-8") + b"\n")
        self.assertEqual(self.run_main(self.turn_args(), now=self.NOW.replace(minute=5)), 0)
        self.assertEqual(errors_of(self.log.read_bytes().decode("utf-8")), [])

    def test_existing_entries_are_left_byte_identical(self) -> None:
        self.log.write_bytes(SESSION.encode("utf-8"))
        before = self.log.read_bytes()
        self.assertEqual(self.run_main(self.turn_args(), now=self.NOW.replace(minute=5)), 0)
        self.assertTrue(self.log.read_bytes().startswith(before))

    def test_bad_entries_are_rejected_without_writing(self) -> None:
        self.log.write_bytes(SESSION.encode("utf-8"))
        before = self.log.read_bytes()
        rejected = (
            self.turn_args(**{"--model": "unknown"}),
            self.turn_args(**{"--tool": "AI"}),
            self.turn_args(**{"--title": "x" * 81}),
            self.turn_args(**{"--summary": "key sk-ant-abc123"}),
            self.turn_args(**{"--summary": "ok.\n\nActions:\nfake"}),
        )
        for args in rejected:
            self.assertEqual(self.run_main(args, now=self.NOW.replace(minute=5)), 1, args)
        self.assertEqual(self.log.read_bytes(), before)

    def test_warnings_are_printed_but_do_not_block(self) -> None:
        self.log.write_bytes(SESSION.encode("utf-8"))
        stderr = io.StringIO()
        args = self.turn_args(**{"--summary": "A one. B two. C three. D four. E five. F six."})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            self.assertEqual(append_log.main(args, now=self.NOW.replace(minute=5)), 0)
        self.assertIn("WARNING summary has 6 sentences", stderr.getvalue())
        self.assertIn("F six.", self.log.read_bytes().decode("utf-8"))

    def test_new_entry_with_more_than_five_sentences_or_an_email_is_rejected(self) -> None:
        self.log.write_bytes(SESSION.encode("utf-8"))
        before = self.log.read_bytes()
        later = datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc)
        for summary in (SIX_SENTENCES, "Mapped someone@example.com to a user. Done."):
            self.assertEqual(self.run_main(self.turn_args(**{"--summary": summary}), now=later), 1, summary)
        self.assertEqual(self.log.read_bytes(), before)

    def test_append_works_without_pread_and_fcntl(self) -> None:
        """Windows has neither os.pread nor fcntl."""
        saved_pread = getattr(os, "pread", None)
        if saved_pread is not None:
            del os.pread
        try:
            with mock.patch.object(append_log, "fcntl", None):
                self.assertEqual(self.run_main(self.session_args()), 0)
                self.assertEqual(self.run_main(self.turn_args(), now=self.NOW.replace(minute=5)), 0)
        finally:
            if saved_pread is not None:
                os.pread = saved_pread
        self.assertEqual(errors_of(self.log.read_bytes().decode("utf-8")), [])

    def test_timestamp_going_backwards_is_rejected(self) -> None:
        self.log.write_bytes(SESSION.encode("utf-8"))
        self.assertEqual(self.run_main(self.turn_args(), now=self.NOW.replace(hour=9)), 1)

    def test_turn_as_first_entry_is_rejected(self) -> None:
        self.assertEqual(self.run_main(self.turn_args()), 1)

    def test_tool_and_model_are_required(self) -> None:
        for flag in ("--tool", "--model"):
            args = self.turn_args()
            index = args.index(flag)
            with self.assertRaises(SystemExit):
                self.run_main(args[:index] + args[index + 2:])

    def test_turn_requires_title_prompt_summary_action(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_main(["--kind", "turn", "--tool", "Claude Code", "--model", "claude-opus-5-5", "--log", str(self.log)])

    def test_parallel_appends_never_interleave(self) -> None:
        self.assertEqual(self.run_main(self.session_args()), 0)
        count = 8
        processes = [
            subprocess.Popen(
                [sys.executable, str(APPEND_LOG_SCRIPT)] + self.turn_args(**{"--title": "Parallel %d" % i}),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            for i in range(count)
        ]
        for process in processes:
            process.communicate()
            self.assertEqual(process.returncode, 0)
        text = self.log.read_bytes().decode("utf-8")
        self.assertEqual(text.count("\n## ["), count)
        self.assertEqual(errors_of(text), [])


if __name__ == "__main__":
    unittest.main()
