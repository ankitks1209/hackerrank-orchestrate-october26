"""Tests for the router, the units, the verifier and the agent stage (SPEC 12.5)."""
from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Sequence, Tuple

from ghostaudit.agent import router, units, verifier
from ghostaudit.agent.model import (
    REASON_CACHE_MISS,
    REASON_ROUTER_FAILED,
    ROUTE_ACCEPT,
    ROUTE_INVESTIGATE,
    AgentDecision,
)
from ghostaudit.agent.stage import AgentStage, Solved, disabled_run
from ghostaudit.agent.verifier import Assignment
from ghostaudit.config import DEFAULT_PRICES, HOUR
from ghostaudit.link_graph import ROW_AGENT, ROW_COUPLING, ROW_FIFO, Contest, LinkDecision
from ghostaudit.llm.cache import CachingClient, DiskCache
from ghostaudit.llm.client import CacheMiss, LLMError, NullClient
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import ActKind, CaseLinks, CaseResult, Request
from tests import agent_fixture as fx
from tests.agent_fixture import ScriptedClient, decision, reply, submit, text_reply, tool_use


def routes_json(*pairs: Tuple[str, str]) -> str:
    return json.dumps({"routes": [{"case_id": c, "route": r, "reason": "because"} for c, r in pairs]})


def verdicts_json(*triples: Tuple[str, str, str]) -> str:
    return json.dumps({"verdicts": [{"case_id": c, "activity_id": a, "verdict": v, "reason": "r"}
                                    for c, a, v in triples]})


class RouterTests(unittest.TestCase):
    def summaries(self, count: int):
        return [router.summarize("case_%d" % n, 1, 0, "settled", 1, 0, 0, "INCOMPLETE") for n in range(1, count + 1)]

    def test_the_reply_routes_each_case(self) -> None:
        client = ScriptedClient([text_reply(routes_json(("case_1", "accept"), ("case_2", "investigate")))])
        got = router.route_cases(self.summaries(2), client, "claude-opus-5-5")
        self.assertEqual(dict(got.routes), {"case_1": ROUTE_ACCEPT, "case_2": ROUTE_INVESTIGATE})
        self.assertEqual((got.calls, got.failed), (1, False))
        request = client.requests[0]
        self.assertEqual(request.prompt_version, "router.v1")
        self.assertIs(request.schema, router.ROUTE_SCHEMA)
        self.assertEqual(json.loads(request.messages[0][1])["cases"][0]["case_id"], "case_1")

    def test_cases_are_batched(self) -> None:
        count = router.ROUTER_BATCH + 5
        first = routes_json(*[("case_%d" % n, "accept") for n in range(1, router.ROUTER_BATCH + 1)])
        second = routes_json(*[("case_%d" % n, "accept") for n in range(router.ROUTER_BATCH + 1, count + 1)])
        # batches are in sorted order of case id, which is lexical here
        client = ScriptedClient([text_reply(first), text_reply(second)])
        ordered = sorted(self.summaries(count), key=lambda item: item["case_id"])
        first_ids = [item["case_id"] for item in ordered[: router.ROUTER_BATCH]]
        client = ScriptedClient([
            text_reply(routes_json(*[(c, "accept") for c in first_ids])),
            text_reply(routes_json(*[(i["case_id"], "accept") for i in ordered[router.ROUTER_BATCH:]])),
        ])
        got = router.route_cases(self.summaries(count), client, "claude-opus-5-5")
        self.assertEqual((got.calls, len(got.routes), got.failed), (2, count, False))

    def test_a_failed_call_routes_the_whole_batch_to_investigation(self) -> None:
        for failure in (CacheMiss("no entry"), LLMError("boom"), text_reply("not json"),
                        text_reply(routes_json(("case_1", "accept"))),  # misses case_2
                        text_reply(routes_json(("case_1", "accept"), ("case_2", "maybe")))):
            with self.subTest(failure=str(failure)[:30]):
                got = router.route_cases(self.summaries(2), ScriptedClient([failure]), "claude-opus-5-5")
                self.assertEqual(set(got.routes.values()), {ROUTE_INVESTIGATE})
                self.assertTrue(got.failed)

    def test_duplicate_or_extra_cases_are_invalid(self) -> None:
        self.assertIsNone(router.parse_routes(routes_json(("case_1", "accept"), ("case_1", "accept")), ["case_1"]))
        self.assertIsNone(router.parse_routes(routes_json(("case_1", "accept"), ("case_9", "accept")), ["case_1"]))
        self.assertEqual(router.parse_routes(routes_json(("case_1", "accept")), ["case_1"]), {"case_1": "accept"})

    def test_default_routes_investigate_everything(self) -> None:
        self.assertEqual(router.default_routes(["a", "b"]), {"a": ROUTE_INVESTIGATE, "b": ROUTE_INVESTIGATE})


def contest_of(rows, accounts=None) -> Contest:
    return Contest(rows, accounts or {})


def request_at(case_id: str, reported_at: int) -> Request:
    return Request(case_id, "x@example.com", 0, "COMPLETE", reported_at, reported_at + 100 * HOUR, "t", False)


class UnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = {"case_%d" % n: request_at("case_%d" % n, n * HOUR) for n in range(1, 21)}
        self.activities = {"act_%d" % n: fx.activity("act_%d" % n, 200 * HOUR, ActKind.VIOLATION,
                                                      "search_service", "search_%d" % n) for n in range(1, 8)}

    def test_components_are_split_in_report_order_and_every_target_is_offered_once(self) -> None:
        cases = tuple("case_%d" % n for n in range(1, 21))
        rows = {"act_%d" % n: cases[n - 1 : n + 1] for n in range(1, 8)}
        rows["act_1"] = cases  # one row ties every case together
        routes = {c: ROUTE_INVESTIGATE for c in cases}
        built = units.build_units(contest_of(rows), routes, self.requests, self.activities)
        self.assertTrue(all(len(u.case_ids) <= units.MAX_UNIT_CASES for u in built))
        offered = [row for u in built for row in u.rows]
        self.assertEqual(sorted(offered), sorted(rows))
        self.assertEqual(len(offered), len(set(offered)))
        for unit in built:
            for row, candidates in unit.rows.items():
                self.assertTrue(set(candidates) <= set(unit.case_ids))
        self.assertEqual([u.unit_id for u in built], sorted(u.unit_id for u in built))

    def test_the_row_goes_to_the_unit_of_the_nearest_report(self) -> None:
        cases = tuple("case_%d" % n for n in range(1, 21))
        routes = {c: ROUTE_INVESTIGATE for c in cases}
        built = units.build_units(contest_of({"act_1": cases}), routes, self.requests, self.activities)
        (holder,) = [u for u in built if "act_1" in u.rows]
        self.assertIn("case_20", holder.case_ids)  # a violation row follows the latest report

    def test_a_component_without_an_investigate_case_makes_no_unit(self) -> None:
        routes = {"case_1": ROUTE_ACCEPT, "case_2": ROUTE_ACCEPT, "case_3": ROUTE_INVESTIGATE, "case_4": ROUTE_ACCEPT}
        rows = {"act_1": ("case_1", "case_2"), "act_2": ("case_3", "case_4")}
        built = units.build_units(contest_of(rows), routes, self.requests, self.activities)
        self.assertEqual([u.case_ids for u in built], [("case_3", "case_4")])
        self.assertEqual(list(built[0].rows), ["act_2"])

    def test_accounts_are_offered_to_the_first_unit_holding_a_candidate(self) -> None:
        routes = {"case_1": ROUTE_INVESTIGATE, "case_2": ROUTE_INVESTIGATE}
        built = units.build_units(contest_of({}, {"acc_1": ("case_1", "case_2")}), routes, self.requests, {})
        self.assertEqual(built[0].accounts, {"acc_1": ("case_1", "case_2")})

    def test_competition_counts_the_other_cases(self) -> None:
        contest = contest_of({"act_1": ("case_1", "case_2", "case_3")}, {"acc": ("case_1", "case_2")})
        shared = units.competing_cases(contest)
        self.assertEqual(shared["case_1"], ("case_2", "case_3"))
        self.assertEqual(shared["case_3"], ("case_1", "case_2"))


class VerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fx.make_fixture()
        self.requests = self.fixture.world.requests
        self.activities = self.fixture.world.base.activities
        self.candidates = {fx.VIOLATION: ("case_1", "case_2")}
        ledger = {"evidence_901": fx.EVIDENCE_AT, fx.VIOLATION: fx.REPORTED + HOUR}
        self.decision = AgentDecision("row", fx.VIOLATION, "assign", "case_1", ("evidence_901",), "Evidence ties it.")
        self.assignment = Assignment("case_1", self.decision, ledger)
        self.kinds = {"case_1": {"evidence_901": "file"}}

    def run_verify(self, client, assignment=None):
        return verifier.verify([assignment or self.assignment], self.requests, self.activities, self.candidates,
                               self.kinds, client, "claude-opus-5-5")

    def test_approval_keeps_the_assignment(self) -> None:
        client = ScriptedClient([text_reply(verdicts_json(("case_1", fx.VIOLATION, "approve")))])
        result = self.run_verify(client)
        self.assertEqual((dict(result.rejected), result.checked, result.calls), ({}, 1, 1))
        payload = json.loads(client.requests[0].messages[0][1])["assignments"][0]
        self.assertEqual(payload["cited"], [{"id": "evidence_901", "kind": "file",
                                             "time": payload["cited"][0]["time"]}])
        self.assertEqual(client.requests[0].prompt_version, "verifier.v1")

    def test_a_critic_rejection_is_recorded_with_its_reason(self) -> None:
        client = ScriptedClient([text_reply(verdicts_json(("case_1", fx.VIOLATION, "reject")))])
        result = self.run_verify(client)
        self.assertEqual(list(result.rejected), [("case_1", fx.VIOLATION)])

    def test_an_unavailable_or_incomplete_critic_rejects(self) -> None:
        for failure in (CacheMiss("none"), LLMError("boom"), text_reply("{}"), text_reply(verdicts_json())):
            with self.subTest(failure=str(failure)[:20]):
                result = self.run_verify(ScriptedClient([failure]))
                self.assertEqual(list(result.rejected), [("case_1", fx.VIOLATION)])

    def test_the_deterministic_recheck_rejects_without_a_model_call(self) -> None:
        late = AgentDecision("row", fx.VIOLATION, "assign", "case_2", ("evidence_901",), "r")
        assignment = Assignment("case_2", late, {"evidence_901": fx.EVIDENCE_AT})
        client = ScriptedClient([])
        result = self.run_verify(client, assignment)
        self.assertEqual(client.calls, 0)
        self.assertIn("newer than the audit time", result.rejected[("case_2", fx.VIOLATION)])

    def test_recheck_reports_each_problem(self) -> None:
        request, row = self.requests["case_1"], self.activities[fx.VIOLATION]
        missing = Assignment("case_1", AgentDecision("row", fx.VIOLATION, "assign", "case_1", ("evidence_x",), "r"), {})
        self.assertIn("evidence_x is not in the ledger", verifier.recheck(missing, request, row, ("case_1",)))
        self.assertIn("case was not a candidate of the target", verifier.recheck(self.assignment, request, row, ("case_2",)))
        before_report = fx.activity("a", request.reported_at - 1, ActKind.VIOLATION, "search_service", "search_1")
        self.assertTrue(verifier.recheck(self.assignment, request, before_report, ("case_1",)))
        after_report = fx.activity("b", request.reported_at + 1, ActKind.POLICY_OK, "support_platform", "support_1")
        self.assertTrue(verifier.recheck(self.assignment, request, after_report, ("case_1",)))
        before_request = fx.activity("c", request.requested_at, ActKind.ACCOUNT_SUBMIT, "account_service", "account_1")
        self.assertTrue(verifier.recheck(self.assignment, request, before_request, ("case_1",)))
        self.assertEqual(verifier.recheck(self.assignment, request, row, ("case_1",)), [])

    def test_assigned_only_filters_rejections(self) -> None:
        reject = AgentDecision("row", "x", "reject", "", ("e",), "r")
        self.assertEqual(verifier.assigned_only([self.decision, reject]), (self.decision,))


@dataclass(frozen=True)
class FakeCase:
    request: Request
    links: CaseLinks
    result: CaseResult
    disagreements: Tuple[str, ...] = ()


class StageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fx.make_fixture()
        self.solves = []

    def solve(self, decisions: Sequence[LinkDecision]) -> Solved:
        self.solves.append(tuple(decisions))
        solution = self.fixture.session.solve(decisions)
        cases = tuple(
            FakeCase(self.fixture.world.requests[case_id], solution.links[case_id],
                     CaseResult(case_id, "INCOMPLETE", ()))
            for case_id in sorted(self.fixture.world.requests)
        )
        return Solved(cases, solution.applied)

    def stage(self, client) -> AgentStage:
        return AgentStage(self.fixture.config, client, UsageMeter(DEFAULT_PRICES), self.fixture.world,
                          self.fixture.session.contest(), self.solve, ())

    def basis(self, run, case_id, resource_id):
        case = next(c for c in run.cases if c.request.case_id == case_id)
        return {r.resource_id: r.basis for r in case.links.resources}.get(resource_id)

    ROUTES = text_reply(routes_json(("case_1", "investigate"), ("case_2", "investigate")))
    SEARCH = reply(tool_use("search_evidence", {"case_id": "case_1", "mode": "by_resource", "resource_id": "search_901"}))
    ANSWER = reply(submit([
        decision(fx.VIOLATION, "assign", "case_2", ["activity_901"], rationale="Closest report."),
        decision(fx.POLICY_ROW, "UNSURE", None, []),
    ]))
    OVERRIDE = reply(submit([decision(fx.VIOLATION, "assign", "case_1", ["evidence_901"])]))

    def test_the_agent_decision_is_applied_and_verified(self) -> None:
        client = ScriptedClient([
            self.ROUTES, self.SEARCH, self.OVERRIDE,
            text_reply(verdicts_json(("case_1", fx.VIOLATION, "approve"))),
        ])
        det = self.solve(())
        run = self.stage(client).run(det.cases)
        stats = run.stats
        self.assertEqual((stats.routed_investigate, stats.units, stats.agent_units, stats.fallback_units), (2, 1, 1, 0))
        self.assertEqual((stats.verifier_checked, stats.verifier_rejected, stats.decisions_applied), (1, 0, 1))
        self.assertEqual(self.basis(run, "case_1", "search_901"), ROW_AGENT)
        self.assertEqual(len(run.decisions), 1)

    def test_a_verifier_rejection_sends_the_target_back_to_the_fallback(self) -> None:
        client = ScriptedClient([
            self.ROUTES, self.SEARCH, self.OVERRIDE,
            text_reply(verdicts_json(("case_1", fx.VIOLATION, "reject"))),
        ])
        det = self.solve(())
        run = self.stage(client).run(det.cases)
        self.assertEqual(run.stats.verifier_rejected, 1)
        self.assertEqual(run.decisions, ())
        self.assertIn(self.basis(run, "case_1", "search_901"), (ROW_FIFO, ROW_COUPLING))
        self.assertEqual(self.solves[-1], ())

    def test_a_router_failure_investigates_every_contested_case(self) -> None:
        client = ScriptedClient([LLMError("boom"), LLMError("agent down")])
        run = self.stage(client).run(self.solve(()).cases)
        self.assertTrue(run.stats.router_failed)
        self.assertEqual(run.stats.routed_investigate, 2)
        self.assertIn((REASON_ROUTER_FAILED, 1), run.stats.reasons)
        self.assertEqual(run.stats.fallback_units, 1)

    def test_accepted_cases_are_not_investigated(self) -> None:
        client = ScriptedClient([text_reply(routes_json(("case_1", "accept"), ("case_2", "accept")))])
        run = self.stage(client).run(self.solve(()).cases)
        self.assertEqual((run.stats.units, run.stats.routed_accept, client.calls), (0, 2, 1))

    def test_without_cached_responses_the_result_equals_the_deterministic_one(self) -> None:
        import tempfile
        from pathlib import Path
        det = self.solve(())
        with tempfile.TemporaryDirectory() as directory:
            client = CachingClient(NullClient(), DiskCache(Path(directory)), UsageMeter(DEFAULT_PRICES), "cache")
            run = self.stage(client).run(det.cases)
        self.assertEqual(run.cases, self.solve(()).cases)
        self.assertEqual(run.stats.agent_units, 0)
        self.assertIn((REASON_CACHE_MISS, 1), run.stats.reasons)

    def test_nothing_contested_means_nothing_to_do(self) -> None:
        client = ScriptedClient([])
        stage = AgentStage(self.fixture.config, client, UsageMeter(DEFAULT_PRICES), self.fixture.world,
                           Contest({}, {}), self.solve, ())
        det = self.solve(()).cases
        run = stage.run(det)
        self.assertEqual((run.cases, client.calls, run.stats.enabled), (det, 0, True))

    def test_disabled_run_records_why(self) -> None:
        run = disabled_run((), "disabled")
        self.assertEqual((run.stats.enabled, run.stats.reasons), (False, (("disabled", 1),)))


if __name__ == "__main__":
    unittest.main()
