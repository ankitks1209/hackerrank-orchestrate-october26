"""Tests for ghostaudit.agent.loop with a scripted client (SPEC 12.4). No model is ever called."""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from ghostaudit.agent import loop
from ghostaudit.agent.loop import CALL_TIMEOUT_S, MAX_ITERATIONS, Investigator, opening_message
from ghostaudit.agent.model import (
    REASON_CACHE_MISS,
    REASON_COST_CAP,
    REASON_INVALID_SUBMIT,
    REASON_ITERATIONS,
    REASON_LLM_ERROR,
    REASON_TIMEOUT,
    REASON_UNSURE,
    STATUS_AGENT,
    STATUS_FALLBACK,
)
from ghostaudit.agent.tools import build_registry
from ghostaudit.config import DEFAULT_PRICES
from ghostaudit.llm.cache import CachingClient, DiskCache, request_key
from ghostaudit.llm.client import CacheMiss, LLMBadOutput, LLMError, LLMResponse, LLMTimeout, NullClient
from ghostaudit.llm.usage import UsageMeter
from tests import agent_fixture as fx
from tests.agent_fixture import ScriptedClient, decision, reply, submit, text_reply, tool_use

SEARCH = tool_use("search_evidence", {"case_id": "case_1", "mode": "by_resource", "resource_id": "search_901"})
ACTIVITY = tool_use("get_activity", {"case_id": "case_1", "kind": "ANY"}, "toolu_a")
GOOD = submit([
    decision(fx.VIOLATION, "assign", "case_1", ["evidence_901", fx.VIOLATION]),
    decision(fx.POLICY_ROW, "UNSURE", None, []),
])


def investigate(script, config=None, meter=None):
    fixture = fx.make_fixture()
    client = ScriptedClient(script)
    meter = meter or UsageMeter(DEFAULT_PRICES)
    investigator = Investigator(client, build_registry(), meter, config or fixture.config)
    return investigator.investigate(fixture.workspace()), client


class HappyPathTests(unittest.TestCase):
    def test_search_then_submit_yields_the_agent_decisions(self) -> None:
        outcome, client = investigate([reply(SEARCH), reply(GOOD)])
        self.assertEqual((outcome.status, outcome.reason, outcome.iterations), (STATUS_AGENT, "", 2))
        (kept,) = outcome.decisions
        self.assertEqual((kept.activity_id, kept.action, kept.case_id), (fx.VIOLATION, "assign", "case_1"))
        self.assertIn(fx.POLICY_ROW, outcome.unsure)
        self.assertIn(fx.ACCOUNT_ROW, outcome.unsure)
        self.assertEqual(client.calls, 2)

    def test_requests_carry_the_tools_the_timeout_and_the_replayed_assistant_turn(self) -> None:
        _, client = investigate([reply(SEARCH), reply(GOOD)])
        first, second = client.requests
        self.assertEqual(first.timeout_s, CALL_TIMEOUT_S)
        self.assertEqual(len(first.tools), 6)
        self.assertEqual(first.prompt_version, "agent.v1")
        self.assertEqual(first.messages[0][0], "user")
        self.assertEqual([m[0] for m in second.messages], ["user", "assistant", "user"])
        (result,) = second.messages[2][1]
        self.assertEqual((result["type"], result["tool_use_id"], result["is_error"]), ("tool_result", "toolu_1", False))
        self.assertEqual(json.loads(result["content"])["items"][0]["file_id"], "evidence_901")

    def test_the_opening_message_lists_cases_and_contested_targets(self) -> None:
        fixture = fx.make_fixture()
        body = json.loads(opening_message(fixture.workspace()))
        self.assertEqual([c["case_id"] for c in body["cases"]], ["case_1", "case_2"])
        self.assertEqual({r["activity_id"] for r in body["contested_rows"]}, {fx.VIOLATION, fx.POLICY_ROW})
        self.assertEqual(body["contested_accounts"][0]["activity_id"], fx.ACCOUNT_ROW)
        self.assertEqual(body["contested_rows"][0]["candidates"][0]["case_id"], "case_1")
        self.assertNotIn("please delete my data", json.dumps(body))

    def test_a_text_only_turn_is_nudged_and_counts_as_an_iteration(self) -> None:
        outcome, client = investigate([text_reply("thinking"), reply(SEARCH), reply(GOOD)])
        self.assertEqual((outcome.status, outcome.iterations), (STATUS_AGENT, 3))
        self.assertIn("submit_answer", client.requests[1].messages[-1][1][0]["text"])

    def test_a_rejected_submit_is_fixed_and_resubmitted(self) -> None:
        bad = submit([decision(fx.VIOLATION, "assign", "case_1", ["evidence_404"])], "toolu_b")
        outcome, client = investigate([reply(SEARCH), reply(bad), reply(GOOD)])
        self.assertEqual((outcome.status, outcome.iterations), (STATUS_AGENT, 3))
        (result,) = client.requests[2].messages[-1][1]
        self.assertTrue(result["is_error"])
        self.assertIn("was not returned by any tool", result["content"])

    def test_a_citation_from_an_opening_message_id_is_valid(self) -> None:
        only_ids = submit([decision(fx.VIOLATION, "reject", None, [fx.VIOLATION])])
        outcome, _ = investigate([reply(only_ids)])
        self.assertEqual(outcome.status, STATUS_AGENT)
        self.assertEqual(outcome.decisions[0].action, "reject")


class FallbackTests(unittest.TestCase):
    def test_iteration_cap_falls_back_after_exactly_max_iterations_calls(self) -> None:
        endless = [reply(tool_use("get_activity", {"case_id": "case_1", "kind": "ANY"}, "t%d" % n))
                   for n in range(MAX_ITERATIONS + 3)]
        outcome, client = investigate(endless)
        self.assertEqual(MAX_ITERATIONS, 8)
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_ITERATIONS))
        self.assertEqual(client.calls, MAX_ITERATIONS)
        self.assertEqual(outcome.decisions, ())
        self.assertEqual(set(outcome.unsure), {fx.VIOLATION, fx.POLICY_ROW, fx.ACCOUNT_ROW})

    def test_timeout_falls_back(self) -> None:
        outcome, _ = investigate([reply(SEARCH), LLMTimeout("slow")])
        self.assertEqual((outcome.status, outcome.reason, outcome.iterations), (STATUS_FALLBACK, REASON_TIMEOUT, 2))

    def test_cache_miss_falls_back(self) -> None:
        outcome, _ = investigate([CacheMiss("no entry")])
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_CACHE_MISS))

    def test_any_llm_error_and_a_bad_stop_reason_fall_back(self) -> None:
        outcome, _ = investigate([LLMError("boom")])
        self.assertEqual(outcome.reason, REASON_LLM_ERROR)
        bad = LLMBadOutput("refusal", reply(stop="refusal"))
        outcome, _ = investigate([bad])
        self.assertEqual(outcome.reason, REASON_LLM_ERROR)

    def test_an_empty_reply_falls_back(self) -> None:
        empty = LLMResponse("", 1, 1, "claude-opus-5-5", False)
        outcome, _ = investigate([empty])
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_LLM_ERROR))

    def test_the_cost_cap_stops_before_any_call(self) -> None:
        fixture = fx.make_fixture()
        meter = UsageMeter(DEFAULT_PRICES)
        meter.record_live(fx.LLMRequest("claude-opus-5-5", "s", (("user", "u"),), 1, "p"),
                          LLMResponse("", 2_000_000, 0, "claude-opus-5-5", False))  # $8 of input
        config = dataclasses.replace(fixture.config, agent_max_usd=1.0)
        outcome, client = investigate([reply(GOOD)], config, meter)
        self.assertEqual((outcome.status, outcome.reason, outcome.iterations), (STATUS_FALLBACK, REASON_COST_CAP, 0))
        self.assertEqual(client.calls, 0)

    def test_cost_below_the_cap_does_not_stop(self) -> None:
        outcome, _ = investigate([reply(SEARCH), reply(GOOD)])
        self.assertEqual(outcome.status, STATUS_AGENT)

    def test_repeatedly_invalid_submits_fall_back(self) -> None:
        bad = lambda n: reply(submit([decision(fx.VIOLATION, "assign", "case_1", ["evidence_404"])], "s%d" % n))
        outcome, client = investigate([bad(1), bad(2), bad(3), reply(GOOD)])
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_INVALID_SUBMIT))
        self.assertEqual(client.calls, 3)

    def test_an_all_unsure_answer_falls_back(self) -> None:
        unsure = submit([decision(fx.VIOLATION, "UNSURE", None, []), decision(fx.POLICY_ROW, "UNSURE", None, [])])
        outcome, _ = investigate([reply(unsure)])
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_UNSURE))
        self.assertEqual(outcome.decisions, ())

    def test_evidence_after_the_cutoff_cannot_be_cited_even_if_the_model_guesses_the_id(self) -> None:
        guess = submit([decision(fx.VIOLATION, "assign", "case_2", ["evidence_901"])])
        outcome, _ = investigate([reply(SEARCH), reply(guess), reply(guess), reply(guess)])
        self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_INVALID_SUBMIT))


class ReplayTests(unittest.TestCase):
    def test_a_cached_replay_is_byte_deterministic_and_makes_the_same_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(Path(directory))
            script = ScriptedClient([reply(SEARCH), reply(GOOD)])
            live = CachingClient(script, cache, UsageMeter(DEFAULT_PRICES), "live")
            fixture = fx.make_fixture()
            first = Investigator(live, build_registry(), UsageMeter(DEFAULT_PRICES), fixture.config)
            outcome_live = first.investigate(fixture.workspace())
            keys_live = [request_key(r) for r in script.requests]
            replayed = CachingClient(NullClient(), cache, UsageMeter(DEFAULT_PRICES), "cache")
            second = Investigator(replayed, build_registry(), UsageMeter(DEFAULT_PRICES), fixture.config)
            outcome_replay = second.investigate(fx.make_fixture().workspace())
            self.assertEqual(outcome_replay, outcome_live)
            self.assertEqual(len(keys_live), 2)
            self.assertEqual(script.calls, 2)  # the replay made no live call

    def test_the_cache_key_covers_the_tools_and_the_messages(self) -> None:
        fixture = fx.make_fixture()
        client = ScriptedClient([reply(SEARCH), reply(GOOD)])
        Investigator(client, build_registry(), UsageMeter(DEFAULT_PRICES), fixture.config).investigate(
            fixture.workspace())
        first = client.requests[0]
        self.assertNotEqual(request_key(first), request_key(dataclasses.replace(first, tools=first.tools[:-1])))
        self.assertNotEqual(request_key(first), request_key(client.requests[1]))
        self.assertEqual(request_key(first), request_key(dataclasses.replace(first, timeout_s=1.0)))

    def test_a_cache_miss_in_cache_mode_falls_back_and_never_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            replayed = CachingClient(NullClient(), DiskCache(Path(directory)), UsageMeter(DEFAULT_PRICES), "cache")
            fixture = fx.make_fixture()
            outcome = Investigator(replayed, build_registry(), UsageMeter(DEFAULT_PRICES), fixture.config
                                   ).investigate(fixture.workspace())
            self.assertEqual((outcome.status, outcome.reason), (STATUS_FALLBACK, REASON_CACHE_MISS))

    def test_the_loop_constants_are_the_documented_ones(self) -> None:
        self.assertEqual((loop.MAX_ITERATIONS, loop.CALL_TIMEOUT_S, loop.MAX_SUBMIT_REJECTIONS), (8, 90.0, 2))


if __name__ == "__main__":
    unittest.main()
