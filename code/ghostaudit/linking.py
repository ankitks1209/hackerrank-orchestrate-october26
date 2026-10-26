"""Case linking: candidate generation and the links the worker rows miss (SPEC L2, L3, L9-L11).

Step one builds the case-to-account and case-to-worker-row edges from process order and
ownership only. Work for a request happens after `requested_at`. The deletion worker
submits the account and applies policy actions before the workflow reports, so an account
(ACCOUNT_SUBMIT) row is a candidate when it falls in `(requested_at, reported_at]` and its
result mirrors the reported status (L2), and a policy row in the same interval. Violation,
flow and restore rows are observed after the report and before the audit, so they fall in
`(reported_at, audit_at]` (L3). Both are filtered by evidence ownership as of `audit_at` (L4a).
Inside the link graph a worker row must also follow its case's account row (L4d). There are
no fitted offsets, latencies or residues. No identifier arithmetic is used (L8).

Step two (`add_extras`) runs on the solved links of `ghostaudit.link_solver` and adds
what the worker-row graph cannot see:

* L9  - a flow (or backup) that repopulated a search document the case owns, up to `audit_at`;
* L10 - resources that evidence ties to the subject (L1) inside the case window, whatever
  the activity stream says: violating ones, and compliant ones as verification-only;
* L11 - the subject's security audit records that a file captured in
  `[reported_at, audit_at]` names (an audit id named only outside the window is not emitted).

Account resolution for cases without an account row belongs to the hand-crafted step (L12), so account_service
resources never come from here. The functions are pure; the fixed-point solver and the
tie-breaks live in `ghostaudit.link_solver` and consume `Candidates`.
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import (
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from ghostaudit.config import Config
from ghostaudit.emit import case_sort_key
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import (
    ACCOUNT_SERVICE,
    SECURITY_SERVICE,
    ActKind,
    CaseLinks,
    ClassifiedActivity,
    LinkedResource,
    Observation,
    Request,
    Treatment,
)
from ghostaudit.policy import PolicyError, PolicyEngine, system_for

LOGGER = logging.getLogger(__name__)

# SPEC L2: the account result that mirrors each reported workflow status.
STATUS_MIRROR: Mapping[str, str] = MappingProxyType(
    {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
)
# SPEC L3: compliant policy rows (P) sit at or before the report, the rest after it.
POLICY_KINDS: FrozenSet[ActKind] = frozenset({ActKind.POLICY_OK})
VIOLATION_KINDS: FrozenSet[ActKind] = frozenset(
    {ActKind.VIOLATION, ActKind.FLOW_ENABLED, ActKind.RESTORE_ALLOWED}
)

# SPEC L9: what a repopulation row recreates, and the treatment that stops it.
REPOPULATION_TREATMENT: Mapping[ActKind, Treatment] = MappingProxyType(
    {ActKind.REPOPULATED: Treatment.FLOW, ActKind.RESTORE_REPOPULATED: Treatment.RESTORE}
)

# Basis labels of the resources `add_extras` links.
BASIS_REPOPULATION = "repopulation"
BASIS_EVIDENCE_UNION = "evidence_union"
BASIS_COMPLIANT_UNION = "evidence_union_compliant"
BASIS_AUDIT_ID = "audit_id"

# Audit coverage buckets of a case (SPEC L11).
AUDIT_IN_WINDOW = "in_window"
AUDIT_NONE = "none"

# Outcome of each repopulation row, best first; a row seen by several cases keeps its best.
ROW_ADDED = "added"
ROW_ALREADY_LINKED = "already_linked"
ROW_POST_AUDIT = "post_audit"
ROW_NOT_OWNED = "not_owned"
ROW_OUTCOMES: Tuple[str, ...] = (ROW_ADDED, ROW_ALREADY_LINKED, ROW_POST_AUDIT, ROW_NOT_OWNED)



def is_compliant_row(row: ClassifiedActivity) -> bool:
    """True for a policy-completed (P) row; every other worker row is violation-side (SPEC L3)."""
    return row.kind is ActKind.POLICY_OK


@dataclass(frozen=True)
class Candidates:
    """Candidate edges between cases, account rows and worker rows (SPEC L2, L3).

    Keys of the `*_of_case` maps are case ids in natural order; values are activity
    ids ordered by `(t, activity_id)`. Keys of the `cases_of_*` maps are activity
    ids; values are case ids in natural order. Activities with no edge are absent.
    """

    accounts_of_case: Mapping[str, Tuple[str, ...]]
    cases_of_account: Mapping[str, Tuple[str, ...]]
    rows_of_case: Mapping[str, Tuple[str, ...]]
    cases_of_row: Mapping[str, Tuple[str, ...]]
    activities: Mapping[str, ClassifiedActivity]


def generate_candidates(
    requests: Sequence[Request],
    activities: Iterable[ClassifiedActivity],
    index: EvidenceIndex,
    identity: IdentityIndex,
) -> Candidates:
    """Candidate edges for every request, sample and evaluation alike (SPEC L2, L3)."""
    acts = tuple(activities)
    by_id = {act.activity_id: act for act in acts}
    cases = sorted(requests, key=lambda req: case_sort_key(req.case_id))
    subjects = {req.case_id: identity.resolve(req.email) for req in cases}
    accounts = _account_edges(cases, subjects, acts, index)
    rows = _row_edges(cases, subjects, acts, index)
    return Candidates(
        accounts_of_case=_freeze(_by_case(accounts)),
        cases_of_account=_freeze(_invert(accounts)),
        rows_of_case=_freeze(_by_case(rows)),
        cases_of_row=_freeze(_invert(rows)),
        activities=_freeze(by_id),
    )


def _account_edges(
    cases: Sequence[Request],
    subjects: Mapping[str, Optional[str]],
    acts: Sequence[ClassifiedActivity],
    index: EvidenceIndex,
) -> List[Tuple[str, str]]:
    """(case, account activity) edges: process order, status mirror and owner (SPEC L2, L4a)."""
    submits = _sorted_by_time(act for act in acts if act.kind is ActKind.ACCOUNT_SUBMIT)
    times = [act.t for act in submits]
    edges: List[Tuple[str, str]] = []
    for req in cases:
        mirror = STATUS_MIRROR.get(req.reported_status)
        for act in _after_until(submits, times, req.requested_at, req.reported_at):
            if act.reported_result == mirror and index.owned_by(
                act.resource_id, subjects[req.case_id], req.audit_at
            ):
                edges.append((req.case_id, act.activity_id))
    return edges


def _row_edges(
    cases: Sequence[Request],
    subjects: Mapping[str, Optional[str]],
    acts: Sequence[ClassifiedActivity],
    index: EvidenceIndex,
) -> List[Tuple[str, str]]:
    """(case, worker row) edges: process order by row kind and owner (SPEC L3, L4a).

    A policy row is applied after the request and no later than the report; a violation,
    flow or restore row is observed after the report and no later than the audit.
    """
    policy = _sorted_by_time(act for act in acts if act.kind in POLICY_KINDS)
    violating = _sorted_by_time(act for act in acts if act.kind in VIOLATION_KINDS)
    policy_times = [act.t for act in policy]
    violating_times = [act.t for act in violating]
    edges: List[Tuple[str, str]] = []
    for req in cases:
        subject = subjects[req.case_id]
        found = _after_until(policy, policy_times, req.requested_at, req.reported_at) + _after_until(
            violating, violating_times, req.reported_at, req.audit_at
        )
        edges.extend(
            (req.case_id, act.activity_id)
            for act in _sorted_by_time(found)
            if index.owned_by(act.resource_id, subject, req.audit_at)
        )
    return edges


def _after_until(
    ordered: Sequence[ClassifiedActivity], times: Sequence[int], after: int, until: int
) -> List[ClassifiedActivity]:
    """Activities with `after < t <= until` from a time-sorted sequence."""
    return list(ordered[bisect_right(times, after) : bisect_right(times, until)])


def _sorted_by_time(acts: Iterable[ClassifiedActivity]) -> List[ClassifiedActivity]:
    return sorted(acts, key=lambda act: act.order_key)


def _by_case(edges: Sequence[Tuple[str, str]]) -> Dict[str, Tuple[str, ...]]:
    """Case -> activity ids in edge order (time order inside a case)."""
    grouped: Dict[str, List[str]] = defaultdict(list)
    for case_id, activity_id in edges:
        grouped[case_id].append(activity_id)
    return {case_id: tuple(ids) for case_id, ids in grouped.items()}


def _invert(edges: Sequence[Tuple[str, str]]) -> Dict[str, Tuple[str, ...]]:
    """Activity id -> case ids in natural case order."""
    grouped: Dict[str, List[str]] = defaultdict(list)
    for case_id, activity_id in edges:
        grouped[activity_id].append(case_id)
    return {
        activity_id: tuple(sorted(ids, key=case_sort_key)) for activity_id, ids in grouped.items()
    }


def _freeze(mapping: Mapping[str, object]) -> Mapping:
    return MappingProxyType(dict(mapping))


# -- extras: repopulation, evidence-only union, audit records (SPEC L9-L11) --------------

_Found = Tuple[LinkedResource, str]  # a resource to link, with the note that explains it


@dataclass(frozen=True)
class ExtraStats:
    """What `add_extras` did, for the diagnostics and the coverage report (SPEC L9-L11).

    `repopulation_rows` counts RP/RB activity rows by outcome. `added` counts resources
    by basis; the `eval_` fields count evaluation cases only, `eval_cases_gaining` the
    evaluation cases that gained at least one resource of a basis. `audit` and
    `eval_audit` count cases per coverage bucket (SPEC L11).
    """

    repopulation_rows: Mapping[str, int]
    added: Mapping[str, int]
    eval_added: Mapping[str, int]
    eval_cases_gaining: Mapping[str, int]
    audit: Mapping[str, int]
    eval_audit: Mapping[str, int]


@dataclass(frozen=True)
class ExtraLinks:
    """Links of every request after the extras, in natural case order, plus their stats."""

    links: Mapping[str, CaseLinks]
    stats: ExtraStats


def add_extras(
    links: Mapping[str, CaseLinks],
    requests: Sequence[Request],
    activities: Iterable[ClassifiedActivity],
    index: EvidenceIndex,
    identity: IdentityIndex,
    policy: PolicyEngine,
    config: Config,
) -> ExtraLinks:
    """Add the resources the worker-row graph misses to the solved `links` (SPEC L9-L11).

    `links` must hold every request.
    """
    acts = tuple(activities)
    extender = _Extender(acts, index, identity, policy, config)
    result: Dict[str, CaseLinks] = {}
    for req in sorted(requests, key=lambda item: case_sort_key(item.case_id)):
        result[req.case_id] = extender.extend(req, links[req.case_id], identity.resolve(req.email))
    stats = extender.stats()
    LOGGER.info(
        "extras: added %s (eval %s), repopulation rows %s, eval audit %s",
        stats.added,
        stats.eval_added,
        stats.repopulation_rows,
        stats.eval_audit,
    )
    return ExtraLinks(MappingProxyType(result), stats)


class _Extender:
    """Adds repopulation flows, evidence-only resources and audit records to a case's links."""

    def __init__(
        self,
        acts: Sequence[ClassifiedActivity],
        index: EvidenceIndex,
        identity: IdentityIndex,
        policy: PolicyEngine,
        config: Config,
    ) -> None:
        self._index = index
        self._identity = identity
        self._policy = policy
        self._flags = config.flags
        self._flows = tuple(act for act in acts if act.kind in REPOPULATION_TREATMENT)
        self._treatments = _activity_treatments(acts)
        self._row_outcome: Dict[str, str] = {}
        self._added: Counter[str] = Counter()
        self._eval_added: Counter[str] = Counter()
        self._eval_gaining: Counter[str] = Counter()
        self._audit: Counter[str] = Counter()
        self._eval_audit: Counter[str] = Counter()

    def extend(self, req: Request, links: CaseLinks, subject: Optional[str]) -> CaseLinks:
        """`links` plus the extras of one case; a case without a subject gets none."""
        if subject is None:
            return links
        have = {(res.system_id, res.resource_id) for res in links.resources}
        linked_ids = {res.resource_id for res in links.resources}
        found: List[_Found] = []
        for generated in (
            self._repopulated(req, subject, linked_ids, have),
            self._union(req, subject, have),
            self._audit_records(req, subject),
        ):
            for resource, note in generated:
                key = (resource.system_id, resource.resource_id)
                if key not in have:
                    have.add(key)
                    found.append((resource, note))
        self._count(req, [resource for resource, _note in found])
        if not found:
            return links
        return CaseLinks(
            links.case_id,
            links.account_id,
            links.account_basis,
            links.resources + tuple(resource for resource, _note in found),
            links.notes + tuple(note for _resource, note in found),
        )

    def stats(self) -> ExtraStats:
        """Counters of everything extended so far."""
        outcomes = Counter(
            self._row_outcome.get(row.activity_id, ROW_NOT_OWNED) for row in self._flows
        )
        return ExtraStats(
            repopulation_rows={name: outcomes[name] for name in ROW_OUTCOMES if outcomes[name]},
            added=dict(sorted(self._added.items())),
            eval_added=dict(sorted(self._eval_added.items())),
            eval_cases_gaining=dict(sorted(self._eval_gaining.items())),
            audit=dict(sorted(self._audit.items())),
            eval_audit=dict(sorted(self._eval_audit.items())),
        )

    # -- L9 ----------------------------------------------------------------

    def _repopulated(
        self, req: Request, subject: str, linked_ids: Set[str], have: Set[Tuple[str, str]]
    ) -> List[_Found]:
        """Flows and backups that recreated a search document the case owns (SPEC L9)."""
        found: List[_Found] = []
        for row in self._flows:
            if not self._owns_downstream(req, subject, row, linked_ids):
                continue
            outcome = self._flow_outcome(req, subject, row, have)
            self._keep_best_outcome(row.activity_id, outcome)
            if outcome == ROW_ADDED:
                resource = LinkedResource(
                    row.system_id,
                    row.resource_id,
                    REPOPULATION_TREATMENT[row.kind],
                    BASIS_REPOPULATION,
                )
                found.append((resource, "%s: %s" % (BASIS_REPOPULATION, row.activity_id)))
        return found

    def _owns_downstream(
        self, req: Request, subject: str, row: ClassifiedActivity, linked_ids: Set[str]
    ) -> bool:
        """The case is linked to the search document, or evidence owns it after the report."""
        if row.related_rid in linked_ids:
            return True
        return self._index.tied_by(row.related_rid, subject, req.audit_at) and row.t >= req.reported_at

    def _flow_outcome(
        self, req: Request, subject: str, row: ClassifiedActivity, have: Set[Tuple[str, str]]
    ) -> str:
        if row.t > req.audit_at:
            return ROW_POST_AUDIT
        if not self._index.owned_by(row.resource_id, subject, req.audit_at):
            return ROW_NOT_OWNED
        if (row.system_id, row.resource_id) in have:
            return ROW_ALREADY_LINKED
        return ROW_ADDED

    def _keep_best_outcome(self, activity_id: str, outcome: str) -> None:
        current = self._row_outcome.get(activity_id)
        if current is None or ROW_OUTCOMES.index(outcome) < ROW_OUTCOMES.index(current):
            self._row_outcome[activity_id] = outcome

    # -- L10 ---------------------------------------------------------------

    def _union(self, req: Request, subject: str, have: Set[Tuple[str, str]]) -> List[_Found]:
        """Resources the evidence ties to the subject inside the case window (SPEC L1, L10)."""
        found: List[_Found] = []
        for rid in self._index.rids_by_user.get(subject, ()):
            obs = self._latest_owned(rid, subject, req)
            if obs is None or obs.system_id in (ACCOUNT_SERVICE, SECURITY_SERVICE):
                continue
            treatment = None if (obs.system_id, rid) in have else self._treatment(obs)
            if treatment is None:
                continue
            compliant = self._policy.is_compliant(treatment, obs.state)
            basis = BASIS_COMPLIANT_UNION if compliant else BASIS_EVIDENCE_UNION
            resource = LinkedResource(obs.system_id, rid, treatment, basis)
            found.append((resource, "%s: %s" % (basis, obs.file_id)))
        return found

    def _latest_owned(self, rid: str, subject: str, req: Request) -> Optional[Observation]:
        """Latest observation of `rid` with a subject key that the case may use (SPEC T1, T3)."""
        keys = self._identity.keys_for(subject)
        floor = None if self._flags.allow_pre_request_findings else req.reported_at
        for obs in reversed(self._index.by_rid.get(rid, ())):
            if max(obs.captured_at, obs.effective_entry_time) > req.audit_at:
                continue
            if floor is not None and obs.captured_at < floor:
                continue
            if not obs.subject_keys.isdisjoint(keys):
                return obs
        return None

    def _treatment(self, obs: Observation) -> Optional[Treatment]:
        """Evidence category, then the activity treatment, then the system default (SPEC 6)."""
        if obs.category is None and obs.resource_id in self._treatments:
            return self._treatments[obs.resource_id]
        try:
            return self._policy.treatment(obs.system_id, obs.category)
        except PolicyError as error:
            LOGGER.warning("%s not linked by evidence: %s", obs.resource_id, error)
            return None

    # -- L11 ---------------------------------------------------------------

    def _audit_records(self, req: Request, subject: str) -> List[_Found]:
        """The subject's audit records that a file captured in the case window names (SPEC L11).

        An audit id that no file of `[reported_at, audit_at]` names is not emitted: it would
        rest on a file captured before the report or after the audit.
        """
        found: List[_Found] = []
        for rid in self._index.rids_by_user.get(subject, ()):
            if system_for(rid) != SECURITY_SERVICE:
                continue
            if not self._index.tied_by(rid, subject, req.audit_at):
                continue
            if not self._index.named_between(rid, req.reported_at, req.audit_at):
                continue
            resource = LinkedResource(SECURITY_SERVICE, rid, Treatment.RETAIN, BASIS_AUDIT_ID)
            found.append((resource, "%s: in window" % BASIS_AUDIT_ID))
        bucket = AUDIT_IN_WINDOW if found else AUDIT_NONE
        self._audit[bucket] += 1
        if not req.is_sample:
            self._eval_audit[bucket] += 1
        return found

    # -- statistics --------------------------------------------------------

    def _count(self, req: Request, added: Sequence[LinkedResource]) -> None:
        self._added.update(res.basis for res in added)
        if req.is_sample:
            return
        self._eval_added.update(res.basis for res in added)
        self._eval_gaining.update({res.basis for res in added})


def _activity_treatments(acts: Iterable[ClassifiedActivity]) -> Dict[str, Treatment]:
    """Latest activity treatment per resource id (SPEC 4: the event type names the treatment)."""
    found: Dict[str, Treatment] = {}
    for act in _sorted_by_time(act for act in acts if act.treatment is not None):
        found[act.resource_id] = act.treatment
    return found
