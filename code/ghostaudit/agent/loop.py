"""The bounded tool-use loop of one investigation (SPEC 12.4).

A manual loop over the Messages API: the model calls tools until it calls `submit_answer`.
The loop is bounded three ways and always ends in an outcome, never an exception:

* `MAX_ITERATIONS` model calls per unit;
* `CALL_TIMEOUT_S` per model call;
* the per-run live cost cap `Config.agent_max_usd`, read from the `UsageMeter` before every call.

It also ends in the deterministic fallback (`status=fallback`, with the reason) on an LLM
error, a cache miss, a submit that the gate keeps rejecting, or an answer that is all UNSURE.
The fallback is the pipeline's own resolution (fixed point, never-mix, FIFO): this module only
reports that it must be used.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Sequence, Tuple

from ghostaudit.agent import prompts
from ghostaudit.agent.model import (
    ACTION_UNSURE,
    REASON_CACHE_MISS,
    REASON_COST_CAP,
    REASON_INVALID_SUBMIT,
    REASON_ITERATIONS,
    REASON_LLM_ERROR,
    REASON_TIMEOUT,
    REASON_UNSURE,
    STATUS_AGENT,
    STATUS_FALLBACK,
    AgentDecision,
    UnitOutcome,
)
from ghostaudit.agent.tools import TOOL_SUBMIT, ToolRegistry, check_submission
from ghostaudit.agent.workspace import Workspace
from ghostaudit.config import Config
from ghostaudit.llm.client import (
    CacheMiss,
    LLMClient,
    LLMError,
    LLMRequest,
    LLMTimeout,
)
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.timeutil import iso

LOGGER = logging.getLogger(__name__)

MAX_ITERATIONS = 8  # model calls per investigation unit (the loop's hard stop)
CALL_TIMEOUT_S = 90.0  # per model call; a timeout ends the unit in the fallback
MAX_SUBMIT_REJECTIONS = 2  # rejected submit_answer calls tolerated before the fallback
AGENT_MAX_TOKENS = 16384  # fixed max_tokens (SPEC N1): thinking plus tool calls
AGENT_EFFORT = "medium"
NUDGE = (
    "Call a tool, or call submit_answer with your decisions. "
    "Answer UNSURE for any target the evidence does not settle."
)


def opening_message(ws: Workspace) -> str:
    """The first user message: the unit's cases and contested targets as canonical JSON (SPEC 12.1)."""
    cases: List[Dict[str, Any]] = []
    for case_id in ws.unit.case_ids:
        request = ws.request(case_id)
        cases.append({
            "case_id": case_id,
            "subject": ws.world.subjects[case_id],
            "requested_at": iso(request.requested_at),
            "reported_at": iso(request.reported_at),
            "audit_at": iso(request.audit_at),
            "reported_status": request.reported_status,
        })
    payload = {
        "unit_id": ws.unit.unit_id,
        "cases": cases,
        "contested_rows": _targets(ws, ws.unit.rows),
        "contested_accounts": _targets(ws, ws.unit.accounts),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _targets(ws: Workspace, offered: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for activity_id in sorted(offered):
        row = ws.activity(activity_id)
        ws.ledger.record(activity_id, row.t)
        found.append({
            "activity_id": activity_id,
            "kind": row.kind.value,
            "system_id": row.system_id,
            "resource_id": row.resource_id,
            "time": iso(row.t),
            "candidates": [
                {"case_id": case_id, "offset_from_reported_s": row.t - ws.request(case_id).reported_at}
                for case_id in offered[activity_id]
            ],
        })
    return found


class Investigator:
    """Runs one bounded investigation per workspace against a client."""

    def __init__(
        self, client: LLMClient, registry: ToolRegistry, meter: UsageMeter, config: Config
    ) -> None:
        self._client = client
        self._registry = registry
        self._meter = meter
        self._config = config
        self._system = prompts.load_prompt(prompts.AGENT_PROMPT)
        self._tools = registry.definitions()

    def _request(self, messages: Sequence[Tuple[str, Any]]) -> LLMRequest:
        return LLMRequest(
            model=self._config.agent_model,
            system=self._system,
            messages=tuple(messages),
            max_tokens=AGENT_MAX_TOKENS,
            prompt_version=prompts.AGENT_PROMPT,
            effort=AGENT_EFFORT,
            tools=self._tools,
            timeout_s=CALL_TIMEOUT_S,
        )

    def investigate(self, ws: Workspace) -> UnitOutcome:
        """The unit's outcome: the model's accepted decisions, or the fallback with its reason."""
        messages: List[Tuple[str, Any]] = [("user", opening_message(ws))]
        rejections = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            if self._meter.live_cost_usd() >= self._config.agent_max_usd:
                return self._fallback(ws, REASON_COST_CAP, iteration - 1)
            try:
                response = self._client.complete(self._request(messages))
            except LLMTimeout:
                return self._fallback(ws, REASON_TIMEOUT, iteration)
            except CacheMiss:
                return self._fallback(ws, REASON_CACHE_MISS, iteration)
            except LLMError as error:
                LOGGER.warning("%s: model call failed: %s", ws.unit.unit_id, error)
                return self._fallback(ws, REASON_LLM_ERROR, iteration)
            calls = [block for block in response.content if block.get("type") == "tool_use"]
            if not response.content:
                return self._fallback(ws, REASON_LLM_ERROR, iteration)
            messages.append(("assistant", tuple(response.content)))
            if not calls:
                messages.append(("user", ({"type": "text", "text": NUDGE},)))
                continue
            results, accepted, rejected = self._run_calls(ws, calls)
            if accepted is not None:
                return self._finish(ws, accepted, iteration)
            rejections += rejected
            if rejections > MAX_SUBMIT_REJECTIONS:
                return self._fallback(ws, REASON_INVALID_SUBMIT, iteration)
            messages.append(("user", tuple(results)))
        return self._fallback(ws, REASON_ITERATIONS, MAX_ITERATIONS)

    def _run_calls(
        self, ws: Workspace, calls: Sequence[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Any, int]:
        """Tool results for one model turn, the accepted submission (or None) and the rejected-submit count."""
        results: List[Dict[str, Any]] = []
        accepted = None
        rejected = 0
        for call in calls:
            outcome = self._registry.invoke(call["name"], call.get("input", {}), ws)
            if call["name"] == TOOL_SUBMIT:
                if outcome.is_error:
                    rejected += 1
                else:
                    accepted = check_submission(ws, call["input"])[0]
            results.append({
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": outcome.content,
                "is_error": outcome.is_error,
            })
        return results, accepted, rejected

    def _finish(self, ws: Workspace, submitted: Sequence[AgentDecision], iterations: int) -> UnitOutcome:
        decided = tuple(d for d in submitted if d.action != ACTION_UNSURE)
        if not decided:
            return self._fallback(ws, REASON_UNSURE, iterations)
        left = tuple(sorted(ws.targets() - {d.activity_id for d in decided}))
        return UnitOutcome(
            ws.unit.unit_id, ws.unit.case_ids, STATUS_AGENT, "", iterations, decided, left,
            ws.ledger.snapshot(),
        )

    @staticmethod
    def _fallback(ws: Workspace, reason: str, iterations: int) -> UnitOutcome:
        LOGGER.info("%s: fallback (%s) after %d model calls", ws.unit.unit_id, reason, iterations)
        return UnitOutcome(
            ws.unit.unit_id, ws.unit.case_ids, STATUS_FALLBACK, reason, iterations, (),
            tuple(sorted(ws.targets())), ws.ledger.snapshot(),
        )

