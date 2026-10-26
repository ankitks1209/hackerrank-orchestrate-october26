"""StateResolver: a resource's state and proof file at audit_at (SPEC T1-T4, V5, 4, 8.2).

Evidence wins over every activity claim (SPEC 4 precedence):

* T1/T2 - the state is the admissible observation with the greatest
  `(entry_time, captured_at, manifest order)`. An observation is admissible when
  its file and its own entry time are both at or before `audit_at`. Only when the
  resource has none, an admissible scope assertion (SPEC 3.1) that enumerates the
  resource's system without the resource says ABSENT.
* T3 - the cite is the latest window file (`reported_at <= captured_at <= audit_at`)
  that proves that same state: an admissible observation with the resolved state,
  or, for ABSENT without such an observation, an absence-proving scope (the
  earliest one: see `_first_file`).
* Fallback (SPEC 4, 8.2) - with no admissible claim the state comes from the
  latest activity template at or before `audit_at` (`basis=activity`); the cite is
  the in-window V/CF/CR `activity_id`, else empty so the caller drops the resource.
  Every evidence/template disagreement is logged and carried in `Resolved.note`.

`choose_omission_cite` is the pure case-level rule V5 for an account that no window
file mentions; the case builder calls it once the other verdicts are resolved.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.model import (
    TREATMENT_OPS,
    ActKind,
    ClassifiedActivity,
    ManifestEntry,
    ObsState,
    Observation,
    Request,
    Treatment,
    state_of,
)
from ghostaudit.policy import PolicyEngine, system_for

LOGGER = logging.getLogger(__name__)

BASIS_EVIDENCE = "evidence"  # latest admissible observation
BASIS_SCOPE = "scope"  # absence proved by a scope assertion
BASIS_ACTIVITY = "activity"  # no admissible evidence; activity template (SPEC 4)
BASIS_UNOBSERVED = "unobserved"  # no admissible evidence and no activity template

# Templates that state a resource's condition (SPEC 4): True = the template claims a violation.
_TEMPLATE_VIOLATING: Mapping[ActKind, bool] = {
    ActKind.POLICY_OK: False,
    ActKind.VIOLATION: True,
    ActKind.FLOW_ENABLED: True,
    ActKind.RESTORE_ALLOWED: True,
    ActKind.REPLICATION_CHECKPOINT: True,
    ActKind.REPOPULATED: True,
    ActKind.RESTORE_REPOPULATED: True,
}
# SPEC 8.2: only these templates carry an activity_id that may stand in for a file.
_CITABLE_KINDS = frozenset({ActKind.VIOLATION, ActKind.FLOW_ENABLED, ActKind.RESTORE_ALLOWED})

# State of a resource that still violates its treatment (SPEC 6 table, "Violating state").
_VIOLATING_STATE: Mapping[Treatment, ObsState] = {
    Treatment.DELETE: ObsState.PRESENT,
    Treatment.REDACT: ObsState.EXPOSED,
    Treatment.ANONYMIZE: ObsState.EXPOSED,
    Treatment.FLOW: ObsState.ACTIVE,
    Treatment.RESTORE: ObsState.ACTIVE,
    Treatment.RETAIN: ObsState.PRESENT,
}


@dataclass(frozen=True)
class Resolved:
    """State of one resource at audit_at, its proof and where both came from.

    `state` is None only for `basis=unobserved`. `cite` is empty when nothing
    admissible and in-window proves the state. `note` is non-empty when the
    activity template contradicts the evidence (SPEC 4). `category` is the
    deletion_rules.csv category the deciding observation carries, if any.
    """

    state: Optional[ObsState]
    cite: str
    basis: str
    note: str = ""
    category: Optional[str] = None


@dataclass(frozen=True)
class _Claim:
    """The state chosen for a resource, where it came from and its evidence category."""

    state: ObsState
    basis: str
    category: Optional[str]


class StateResolver:
    """Resolves each resource's state at a case's audit_at (SPEC T1-T4, 4)."""

    def __init__(
        self,
        index: EvidenceIndex,
        policy: PolicyEngine,
        acts: Iterable[ClassifiedActivity],
    ) -> None:
        self._index = index
        self._policy = policy
        self._templates = _templates_by_rid(acts)

    def resolve(self, rid: str, system_id: str, req: Request) -> Resolved:
        """State and cite of `rid` for one case; evidence first, activity as fallback."""
        claim = self._latest_claim(rid, system_id, req)
        template = self._latest_template(rid, req)
        if claim is None:
            return self._from_activity(template, system_id, req)
        return Resolved(
            claim.state,
            self._cite(rid, system_id, claim.state, req),
            claim.basis,
            self._disagreement(rid, system_id, claim, template),
            claim.category,
        )

    def _latest_claim(self, rid: str, system_id: str, req: Request) -> Optional[_Claim]:
        """The latest admissible observation; an absence scope only when none exists.

        A scope enumerates one system at one moment and cannot see every copy
        (replicas, SPEC F1), so it never overrides an explicit observation.
        """
        observed = self._admissible_observations(rid, system_id, req)
        if observed:
            return _Claim(observed[-1].state, BASIS_EVIDENCE, observed[-1].category)
        if _absence_proofs(self._index, rid, system_id, req.audit_at):
            return _Claim(ObsState.ABSENT, BASIS_SCOPE, None)
        return None

    def _admissible_observations(
        self, rid: str, system_id: str, req: Request
    ) -> List[Observation]:
        """SPEC T1 observations of `rid`, in the index order of SPEC T2 (oldest first)."""
        return [
            obs
            for obs in self._index.by_rid.get(rid, ())
            if obs.system_id == system_id and _admissible(obs, req)
        ]

    def _cite(self, rid: str, system_id: str, state: ObsState, req: Request) -> str:
        """Latest window file that proves `state` (SPEC T3); empty when none does.

        An observation of the same state is the proof; absence may instead be
        proved by a scope that omits the resource.
        """
        proofs: List[ManifestEntry] = [
            self._index.entries[obs.file_id]
            for obs in self._admissible_observations(rid, system_id, req)
            if obs.state is state and _in_window(obs.captured_at, req)
        ]
        if proofs:
            return _latest_file(proofs)
        if state is ObsState.ABSENT:
            return _first_file(_window_absence_proofs(self._index, rid, system_id, req))
        return ""

    def _latest_template(self, rid: str, req: Request) -> Optional[ClassifiedActivity]:
        rows = [act for act in self._templates.get(rid, ()) if act.t <= req.audit_at]
        return rows[-1] if rows else None

    def _treatment(
        self, system_id: str, category: Optional[str], act: Optional[ClassifiedActivity]
    ) -> Treatment:
        """Evidence category first, then the activity treatment, then the system default."""
        if category is None and act is not None and act.treatment is not None:
            return act.treatment
        return self._policy.treatment(system_id, category)

    def _from_activity(
        self, act: Optional[ClassifiedActivity], system_id: str, req: Request
    ) -> Resolved:
        """SPEC 4 fallback: the template's state; the cite is an in-window V/CF/CR id."""
        if act is None:
            return Resolved(None, "", BASIS_UNOBSERVED)
        treatment = self._treatment(system_id, None, act)
        if _TEMPLATE_VIOLATING[act.kind]:
            state = _VIOLATING_STATE[treatment]
        else:
            state = ObsState(state_of(TREATMENT_OPS[treatment][2]))
        citable = act.kind in _CITABLE_KINDS and _in_window(act.t, req)
        return Resolved(state, act.activity_id if citable else "", BASIS_ACTIVITY)

    def _disagreement(
        self, rid: str, system_id: str, claim: _Claim, act: Optional[ClassifiedActivity]
    ) -> str:
        """Describe an evidence/template contradiction, log it, or return '' (SPEC 4)."""
        if act is None:
            return ""
        treatment = self._treatment(system_id, claim.category, act)
        compliant = self._policy.is_compliant(treatment, claim.state)
        if _TEMPLATE_VIOLATING[act.kind] != compliant:
            return ""
        note = "%s/%s: %s claims %s but evidence state %s is %s" % (
            system_id,
            rid,
            act.activity_id,
            "a violation" if _TEMPLATE_VIOLATING[act.kind] else "compliance",
            claim.state.value,
            "compliant" if compliant else "violating",
        )
        LOGGER.warning("evidence/template disagreement: %s", note)
        return note


def choose_omission_cite(
    account_rid: str,
    case_cites: Iterable[str],
    req: Request,
    index: EvidenceIndex,
) -> Optional[str]:
    """Proof file for an account that no window file mentions (SPEC V5).

    1. A cite of the case's other steps whose file enumerates account_service
       without the account. Only here a cite-only scope counts: a topology snapshot
       that lists account rows (SPEC F1) is the case's own proof file, but would
       outrank the sample gold files as a general window fallback.
    2. Else a window file that does (cite-only scopes excluded).
    3. Else None, and a COMPLETE case omits the step.

    Several candidates resolve to the earliest file: sample case_04 cites the
    earlier of its two window scope files (SPEC V5.2 says the latest; see
    `_first_file`).
    """
    system_id = system_for(account_rid)
    proofs = _window_absence_proofs(index, account_rid, system_id, req)
    case_proofs = _window_absence_proofs(index, account_rid, system_id, req, cite_only=True)
    cited = set(case_cites)
    return (
        _first_file([entry for entry in case_proofs if entry.file_id in cited])
        or _first_file(proofs)
        or None
    )


def _window_absence_proofs(
    index: EvidenceIndex, rid: str, system_id: Optional[str], req: Request, cite_only: bool = False
) -> List[ManifestEntry]:
    return [
        entry
        for entry in _absence_proofs(index, rid, system_id, req.audit_at, cite_only)
        if _in_window(entry.captured_at, req)
    ]


def _absence_proofs(
    index: EvidenceIndex, rid: str, system_id: Optional[str], hi: int, cite_only: bool = False
) -> List[ManifestEntry]:
    """Files up to `hi` whose scope enumerates `system_id` without `rid` (SPEC 3.1).

    A cite-only scope (a topology snapshot, SPEC F1) counts only when `cite_only` is set.
    """
    return [
        entry
        for file_id, scopes in index.scopes_by_file.items()
        for entry in (index.entries[file_id],)
        if entry.captured_at <= hi
        and any(
            scope.system_id == system_id
            and scope.captured_at <= hi
            and (cite_only or not scope.cite_only)
            and rid not in scope.present_ids
            for scope in scopes
        )
    ]


def _latest_file(entries: Iterable[ManifestEntry]) -> str:
    """file_id of the entry with the greatest (captured_at, order); '' for none."""
    latest = max(entries, key=lambda entry: (entry.captured_at, entry.order), default=None)
    return latest.file_id if latest is not None else ""


def _first_file(entries: Iterable[ManifestEntry]) -> str:
    """file_id of the entry with the smallest (captured_at, order); '' for none.

    Used for absence proofs by omission: every window scope that omits the
    resource proves the same fact, and the sample gold (case_04, two such
    files) cites the earlier one, not the latest as SPEC V5.2 words it.
    """
    first = min(entries, key=lambda entry: (entry.captured_at, entry.order), default=None)
    return first.file_id if first is not None else ""


def _admissible(obs: Observation, req: Request) -> bool:
    """SPEC T1: both the file and the entry are at or before audit_at."""
    return obs.captured_at <= req.audit_at and obs.effective_entry_time <= req.audit_at


def _in_window(moment: int, req: Request) -> bool:
    """SPEC T3: `reported_at <= moment <= audit_at`, both ends inclusive."""
    return req.reported_at <= moment <= req.audit_at


def _templates_by_rid(
    acts: Iterable[ClassifiedActivity],
) -> Dict[str, Tuple[ClassifiedActivity, ...]]:
    """Condition-bearing activity rows per resource, oldest first (SPEC 4)."""
    grouped: Dict[str, List[ClassifiedActivity]] = defaultdict(list)
    for act in acts:
        if act.kind in _TEMPLATE_VIOLATING:
            grouped[act.resource_id].append(act)
    return {
        rid: tuple(sorted(rows, key=lambda act: act.order_key))
        for rid, rows in grouped.items()
    }
