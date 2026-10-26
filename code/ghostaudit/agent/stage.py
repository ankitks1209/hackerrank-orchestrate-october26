"""The agent stage: router, investigation units, verifier (SPEC 12.5).

`AgentStage.run` takes the deterministic result (the agent-off result, which is also the
fallback) and returns the final cases:

1. summarise every case that has contested targets and route it (`router`);
2. group the cases routed `investigate` into units (`units`) and run one bounded
   investigation per unit (`loop`);
3. link again with the accepted decisions and re-build the cases;
4. for the cases the agent touched whose answer is INCOMPLETE, re-check and critique every
   assignment (`verifier`); drop the rejected ones and link and build once more.

Everything the model does not decide is decided by the deterministic pipeline, so the stage
never leaves a case without an answer.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Sequence, Set, Tuple

from ghostaudit.agent.loop import Investigator
from ghostaudit.agent.model import (
    REASON_ROUTER_FAILED,
    ROUTE_ACCEPT,
    ROUTE_INVESTIGATE,
    STATUS_AGENT,
    AgentDecision,
    AgentStats,
    UnitOutcome,
)
from ghostaudit.agent.router import route_cases, summarize
from ghostaudit.agent.tools import build_registry
from ghostaudit.agent.units import build_units, competing_cases
from ghostaudit.agent.verifier import Assignment, assigned_only, verify
from ghostaudit.agent.workspace import WorldView, Workspace
from ghostaudit.config import Config
from ghostaudit.emit import case_sort_key
from ghostaudit.link_graph import ACCOUNT_NONE, Contest, LinkDecision
from ghostaudit.llm.client import LLMClient
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import STATUS_INCOMPLETE

LOGGER = logging.getLogger(__name__)

ACCOUNT_SETTLED = "settled"
ACCOUNT_TIED = "tied"
ACCOUNT_MISSING = "missing"
KIND_FILE = "file"
KIND_ACTIVITY = "activity"
KIND_AUDIT = "audit"


@dataclass(frozen=True)
class Solved:
    """Cases built from one link solution, and how many agent decisions that solution applied."""

    cases: Tuple[Any, ...]
    applied: int


SolveCases = Callable[[Sequence[LinkDecision]], Solved]


@dataclass(frozen=True)
class AgentRun:
    """The final cases of a run, the units' outcomes, the decisions in force and the statistics."""

    cases: Tuple[Any, ...]
    stats: AgentStats
    outcomes: Tuple[UnitOutcome, ...] = ()
    decisions: Tuple[AgentDecision, ...] = ()


def disabled_run(cases: Tuple[Any, ...], reason: str) -> AgentRun:
    """The run when the agent is off: the deterministic cases, a stats record that says why."""
    return AgentRun(cases, AgentStats(enabled=False, reasons=((reason, 1),)))


class AgentStage:
    """Runs router, units and verifier over a deterministic result."""

    def __init__(
        self,
        config: Config,
        client: LLMClient,
        meter: UsageMeter,
        world: WorldView,
        contest: Contest,
        solve: SolveCases,
        unread_media: Sequence[str],
    ) -> None:
        self._config = config
        self._client = client
        self._meter = meter
        self._world = world
        self._contest = contest
        self._solve = solve
        self._unread = tuple(unread_media)

    def run(self, deterministic: Tuple[Any, ...]) -> AgentRun:
        """The final cases after routing, investigation and verification."""
        contest = self._contest
        if not contest.rows and not contest.accounts:
            return AgentRun(deterministic, AgentStats(enabled=True))
        summaries = self._summaries(deterministic)
        routed = route_cases(summaries, self._client, self._config.router_model)
        routes = {case_id: ROUTE_ACCEPT for case_id in self._world.requests}
        routes.update(routed.routes)
        units = build_units(contest, routes, self._world.requests, self._world.base.activities)
        investigator = Investigator(self._client, build_registry(), self._meter, self._config)
        outcomes = tuple(investigator.investigate(Workspace(unit, self._world)) for unit in units)
        decisions = tuple(d for outcome in outcomes if outcome.status == STATUS_AGENT for d in outcome.decisions)
        solved = self._solve(tuple(d.as_link_decision() for d in decisions))
        cases, applied = solved.cases, solved.applied
        checked = rejected = 0
        touched = Counter(d.case_id for d in assigned_only(decisions))
        verifiable = self._incomplete(cases, touched)
        if verifiable:
            result = self._verify(outcomes, verifiable, contest)
            checked, rejected = result.checked, len(result.rejected)
            if result.rejected:
                decisions = tuple(
                    d for d in decisions if (d.case_id, d.activity_id) not in result.rejected
                )
                solved = self._solve(tuple(d.as_link_decision() for d in decisions))
                cases, applied = solved.cases, solved.applied
        stats = self._stats(routes, routed.calls, routed.failed, outcomes, applied, checked, rejected)
        return AgentRun(cases, stats, outcomes, decisions)

    # -- routing ----------------------------------------------------------------

    def _summaries(self, deterministic: Sequence[Any]) -> List[Dict[str, Any]]:
        contest = self._contest
        competitors = competing_cases(contest)
        prelim = {case.request.case_id: case for case in deterministic}
        tied_cases = {case_id for cases in contest.accounts.values() for case_id in cases}
        found: List[Dict[str, Any]] = []
        for case_id in sorted(competitors, key=case_sort_key):
            case = prelim[case_id]
            request = case.request
            if case_id in tied_cases:
                state = ACCOUNT_TIED
            elif case.links.account_id is None or case.links.account_basis == ACCOUNT_NONE:
                state = ACCOUNT_MISSING
            else:
                state = ACCOUNT_SETTLED
            unread = sum(
                request.reported_at <= self._world.index.entries[file_id].captured_at <= request.audit_at
                for file_id in self._unread
                if file_id in self._world.index.entries
            )
            found.append(summarize(
                case_id,
                sum(case_id in cases for cases in contest.rows.values()),
                sum(case_id in cases for cases in contest.accounts.values()),
                state,
                len(competitors[case_id]),
                unread,
                len(case.disagreements),
                case.result.deletion_status,
            ))
        return found

    # -- verification -------------------------------------------------------------

    @staticmethod
    def _incomplete(cases: Sequence[Any], touched: Mapping[str, int]) -> Set[str]:
        return {
            case.request.case_id
            for case in cases
            if case.result.deletion_status == STATUS_INCOMPLETE and case.request.case_id in touched
        }

    def _verify(self, outcomes: Sequence[UnitOutcome], case_ids: Set[str], contest: Contest):
        candidates: Dict[str, Tuple[str, ...]] = dict(contest.rows)
        candidates.update(contest.accounts)
        assignments: List[Assignment] = []
        kinds: Dict[str, Dict[str, str]] = {}
        for outcome in outcomes:
            if outcome.status != STATUS_AGENT:
                continue
            for decision in assigned_only(outcome.decisions):
                if decision.case_id not in case_ids:
                    continue
                assignments.append(Assignment(decision.case_id, decision, outcome.ledger))
                kinds.setdefault(decision.case_id, {}).update(
                    {identifier: self._kind_of(identifier) for identifier in decision.evidence_ids}
                )
        return verify(
            assignments, self._world.requests, self._world.base.activities, candidates, kinds,
            self._client, self._config.verifier_model,
        )

    def _kind_of(self, identifier: str) -> str:
        if identifier in self._world.index.entries:
            return KIND_FILE
        if identifier in self._world.base.activities:
            return KIND_ACTIVITY
        return KIND_AUDIT

    # -- statistics -----------------------------------------------------------------

    @staticmethod
    def _stats(
        routes: Mapping[str, str],
        router_calls: int,
        router_failed: bool,
        outcomes: Sequence[UnitOutcome],
        applied: int,
        checked: int,
        rejected: int,
    ) -> AgentStats:
        reasons = Counter(outcome.reason for outcome in outcomes if outcome.reason)
        if router_failed:
            reasons[REASON_ROUTER_FAILED] += 1
        agent_units = sum(outcome.status == STATUS_AGENT for outcome in outcomes)
        return AgentStats(
            enabled=True,
            router_calls=router_calls,
            router_failed=router_failed,
            routed_investigate=sum(route == ROUTE_INVESTIGATE for route in routes.values()),
            routed_accept=sum(route == ROUTE_ACCEPT for route in routes.values()),
            units=len(outcomes),
            agent_units=agent_units,
            fallback_units=len(outcomes) - agent_units,
            iterations=sum(outcome.iterations for outcome in outcomes),
            decisions_applied=applied,
            verifier_checked=checked,
            verifier_rejected=rejected,
            reasons=tuple(sorted(reasons.items())),
        )

