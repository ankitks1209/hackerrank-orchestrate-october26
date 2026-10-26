"""The verifier: a narrow second stage over the agent's assignments (SPEC 12.5).

It runs for cases the agent touched whose answer is INCOMPLETE, and has two parts:

1. a deterministic re-check of every assignment: every citation is in the unit's ledger and
   existed by the case's `audit_at`; the row's time fits its kind in the case's process order
   (SPEC L2, L3); the case was a candidate of the target;
2. a critic call (`verifier.v1.md`) that approves or rejects each remaining assignment with a
   reason.

A rejected assignment is dropped and its target goes to the deterministic fallback. If the
critic cannot be reached or its reply does not cover every assignment, the assignments it did
not approve are rejected: an unverified assignment is not used.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ghostaudit.agent import prompts, schema
from ghostaudit.agent.model import AgentDecision
from ghostaudit.link_graph import ACTION_ASSIGN
from ghostaudit.linking import POLICY_KINDS, VIOLATION_KINDS
from ghostaudit.llm.client import LLMClient, LLMError, LLMRequest
from ghostaudit.model import ActKind, ClassifiedActivity, Request
from ghostaudit.timeutil import iso

LOGGER = logging.getLogger(__name__)

VERIFIER_BATCH = 10  # assignments per critic call
VERIFIER_MAX_TOKENS = 8192
VERIFIER_EFFORT = "medium"
VERIFIER_TIMEOUT_S = 90.0
VERDICT_APPROVE = "approve"
VERDICT_REJECT = "reject"

VERDICT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "activity_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": [VERDICT_APPROVE, VERDICT_REJECT]},
                    "reason": {"type": "string"},
                },
                "required": ["activity_id", "case_id", "reason", "verdict"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

Key = Tuple[str, str]  # (case_id, activity_id)


@dataclass(frozen=True)
class Assignment:
    """One agent assignment to re-check: the case, the decision and the unit's ledger."""

    case_id: str
    decision: AgentDecision
    ledger: Mapping[str, int]


@dataclass(frozen=True)
class VerifierResult:
    """Keys of the rejected assignments, the number checked, critic calls made and the reasons."""

    rejected: Mapping[Key, str]
    checked: int
    calls: int


def recheck(
    assignment: Assignment, request: Request, row: ClassifiedActivity, candidates: Sequence[str]
) -> List[str]:
    """Deterministic problems with one assignment; an empty list means it passes (SPEC 12.5)."""
    problems: List[str] = []
    decision = assignment.decision
    if assignment.case_id not in candidates:
        problems.append("case was not a candidate of the target")
    for identifier in decision.evidence_ids:
        moment = assignment.ledger.get(identifier)
        if moment is None:
            problems.append("%s is not in the ledger" % identifier)
        elif moment > request.audit_at:
            problems.append("%s is newer than the audit time" % identifier)
    problems.extend(_process_order(row, request))
    return problems


def _process_order(row: ClassifiedActivity, request: Request) -> List[str]:
    if row.kind is ActKind.ACCOUNT_SUBMIT or row.kind in POLICY_KINDS:
        if not request.requested_at < row.t <= request.reported_at:
            return ["%s row outside (requested_at, reported_at]" % row.kind.value]
    elif row.kind in VIOLATION_KINDS:
        if not request.reported_at < row.t <= request.audit_at:
            return ["%s row outside (reported_at, audit_at]" % row.kind.value]
    return []


def _payload(
    items: Sequence[Tuple[Assignment, Request, ClassifiedActivity, Mapping[str, str]]]
) -> str:
    rows: List[Dict[str, Any]] = []
    for assignment, request, row, kinds in items:
        decision = assignment.decision
        rows.append({
            "case_id": assignment.case_id,
            "activity_id": decision.activity_id,
            "kind": row.kind.value,
            "resource_id": row.resource_id,
            "time": iso(row.t),
            "requested_at": iso(request.requested_at),
            "reported_at": iso(request.reported_at),
            "audit_at": iso(request.audit_at),
            "rationale": decision.rationale,
            "cited": [
                {"id": identifier, "kind": kinds.get(identifier, "unknown"),
                 "time": iso(assignment.ledger[identifier])}
                for identifier in decision.evidence_ids
            ],
        })
    return json.dumps({"assignments": rows}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_verdicts(text: str, expected: Sequence[Key]) -> Optional[Dict[Key, Tuple[str, str]]]:
    """(verdict, reason) per key, or None when the reply is not valid or does not cover `expected` exactly."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if schema.validate(data, VERDICT_SCHEMA):
        return None
    found: Dict[Key, Tuple[str, str]] = {}
    for item in data["verdicts"]:
        key = (item["case_id"], item["activity_id"])
        if key in found:
            return None
        found[key] = (item["verdict"], item["reason"])
    return found if sorted(found) == sorted(expected) else None


def verify(
    assignments: Sequence[Assignment],
    requests: Mapping[str, Request],
    activities: Mapping[str, ClassifiedActivity],
    candidates: Mapping[str, Sequence[str]],
    kind_of: Mapping[str, Mapping[str, str]],
    client: LLMClient,
    model: str,
) -> VerifierResult:
    """Re-check and critique `assignments`; the rejected ones go to the fallback.

    `kind_of[case_id]` names what each cited id is (file, activity or audit) for the critic.
    """
    rejected: Dict[Key, str] = {}
    passing: List[Tuple[Assignment, Request, ClassifiedActivity, Mapping[str, str]]] = []
    for assignment in assignments:
        decision = assignment.decision
        key = (assignment.case_id, decision.activity_id)
        request, row = requests[assignment.case_id], activities[decision.activity_id]
        problems = recheck(assignment, request, row, candidates.get(decision.activity_id, ()))
        if problems:
            rejected[key] = "; ".join(problems)
        else:
            passing.append((assignment, request, row, kind_of.get(assignment.case_id, {})))
    system = prompts.load_prompt(prompts.VERIFIER_PROMPT)
    calls = 0
    for start in range(0, len(passing), VERIFIER_BATCH):
        batch = passing[start : start + VERIFIER_BATCH]
        calls += 1
        keys = [(a.case_id, a.decision.activity_id) for a, _r, _w, _k in batch]
        verdicts = _critic(_payload(batch), keys, system, client, model)
        for key in keys:
            verdict, reason = (verdicts or {}).get(key, (VERDICT_REJECT, "critic unavailable or incomplete"))
            if verdict != VERDICT_APPROVE:
                rejected[key] = reason
    return VerifierResult(rejected, len(assignments), calls)


def _critic(
    payload: str, keys: Sequence[Key], system: str, client: LLMClient, model: str
) -> Optional[Dict[Key, Tuple[str, str]]]:
    request = LLMRequest(
        model=model,
        system=system,
        messages=(("user", payload),),
        max_tokens=VERIFIER_MAX_TOKENS,
        prompt_version=prompts.VERIFIER_PROMPT,
        schema=VERDICT_SCHEMA,
        effort=VERIFIER_EFFORT,
        timeout_s=VERIFIER_TIMEOUT_S,
    )
    try:
        return parse_verdicts(client.complete(request).text, keys)
    except LLMError as error:
        LOGGER.warning("verifier call failed: %s", error)
        return None


def assigned_only(decisions: Sequence[AgentDecision]) -> Tuple[AgentDecision, ...]:
    """The assignments among decisions (rejections as decoys have no case to verify)."""
    return tuple(d for d in decisions if d.action == ACTION_ASSIGN)

