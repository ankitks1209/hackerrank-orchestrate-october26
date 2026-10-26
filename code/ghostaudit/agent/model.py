"""Plain records of the agent stage (SPEC 12): units, decisions, outcomes and run statistics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from ghostaudit.link_graph import ACTION_ASSIGN, ACTION_REJECT, LinkDecision

ACTION_UNSURE = "UNSURE"
ACTIONS = (ACTION_ASSIGN, ACTION_REJECT, ACTION_UNSURE)

STATUS_AGENT = "agent"  # the unit was decided by the model and passed the gate
STATUS_FALLBACK = "fallback"  # the deterministic resolution decided it (low confidence)

ROUTE_INVESTIGATE = "investigate"
ROUTE_ACCEPT = "accept"

# Why a unit, a router call or the verifier fell back (counted in the diagnostics).
REASON_ITERATIONS = "iteration_cap"
REASON_TIMEOUT = "timeout"
REASON_COST_CAP = "cost_cap"
REASON_LLM_ERROR = "llm_error"
REASON_CACHE_MISS = "cache_miss"
REASON_INVALID_SUBMIT = "invalid_submit"
REASON_UNSURE = "unsure"
REASON_ROUTER_FAILED = "router_failed"
REASON_DISABLED = "disabled"


@dataclass(frozen=True)
class UnitSpec:
    """One investigation unit: cases that compete, and the contested targets offered to the model.

    `rows` and `accounts` map an activity id to the candidate cases that are inside the unit.
    """

    unit_id: str
    case_ids: Tuple[str, ...]
    rows: Mapping[str, Tuple[str, ...]]
    accounts: Mapping[str, Tuple[str, ...]]


@dataclass(frozen=True)
class AgentDecision:
    """The model's answer for one contested row or account, after the submit gate accepted it."""

    target: str
    activity_id: str
    action: str
    case_id: str
    evidence_ids: Tuple[str, ...]
    rationale: str

    def as_link_decision(self) -> LinkDecision:
        """The graph-level decision; only an assignment or a rejection has one."""
        return LinkDecision(self.target, self.activity_id, self.action, self.case_id)


@dataclass(frozen=True)
class UnitOutcome:
    """What one investigation produced. `decisions` are only the assignments and rejections."""

    unit_id: str
    case_ids: Tuple[str, ...]
    status: str
    reason: str
    iterations: int
    decisions: Tuple[AgentDecision, ...]
    unsure: Tuple[str, ...]  # offered activity ids left to the fallback
    ledger: Mapping[str, int]


@dataclass(frozen=True)
class AgentStats:
    """Counts of an agent stage for the diagnostics and the ablation (SPEC 12.5)."""

    enabled: bool
    router_calls: int = 0
    router_failed: bool = False
    routed_investigate: int = 0
    routed_accept: int = 0
    units: int = 0
    agent_units: int = 0
    fallback_units: int = 0
    iterations: int = 0
    decisions_applied: int = 0
    verifier_checked: int = 0
    verifier_rejected: int = 0
    reasons: Tuple[Tuple[str, int], ...] = ()

    @property
    def fallbacks(self) -> int:
        """Units that fell back, for the ablation table."""
        return self.fallback_units
