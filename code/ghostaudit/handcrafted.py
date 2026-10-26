"""Sources of a case without an A-row account: hand-crafted and media cases (SPEC L12, Q1, Q2).

Implements SPEC L12. Such a case has no deletion-worker run to link, so its resources and
its account id come from other grounded signals, all scoped by the case's own times (T5):

* target-resource (T) rows of the samples, after `requested_at` (process order) and up to
  `audit_at`; non-account T rows are resources, account T rows are account pointers;
* catalog LINK rows (evaluation media cases) that name the subject and fall in
  `[reported_at, audit_at]`; the same rule scopes a user's several cases apart.

The account id (L12) is the first of these that is unambiguous:

1. an account that evidence ties to the subject by identifier (L1), any time, for ids only;
   among several, the ones a window file names;
2. an activity pointer: an account T or LINK row of the case, or the source account of a
   search document the case holds (`EvidenceIndex.pointers`);
3. none: the case gets no account step. No id convention is guessed.

Nothing here reads a state: the resolver and the builder decide those. A resource named
only by a LINK row is dropped by the builder unless evidence observes it (media facts).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import ACCOUNT_SERVICE, ActKind, ClassifiedActivity, LinkedResource, Request
from ghostaudit.policy import PolicyEngine, PolicyError, system_for

LOGGER = logging.getLogger(__name__)

# Basis labels of the resources and accounts this module supplies.
BASIS_TARGET_ROW = "target_row"
BASIS_CATALOG_LINK = "catalog_link"
BASIS_EVIDENCE = "evidence"
BASIS_POINTER = "activity_pointer"
BASIS_NONE = "none"


@dataclass(frozen=True)
class AccountChoice:
    """The case account (SPEC L12), the rule that gave it and a note when a rule was ambiguous."""

    account_id: Optional[str]
    basis: str
    note: str = ""


class HandcraftedSources:
    """T-row and LINK-row resources, and the account choice, of cases without an A-row."""

    def __init__(
        self,
        acts: Iterable[ClassifiedActivity],
        index: EvidenceIndex,
        policy: PolicyEngine,
        identity: IdentityIndex,
    ) -> None:
        rows = sorted(acts, key=lambda act: act.order_key)
        self._targets = tuple(act for act in rows if act.kind is ActKind.TARGET_RESOURCE)
        self._links = tuple(act for act in rows if act.kind is ActKind.LINK)
        self._index = index
        self._policy = policy
        self._identity = identity

    def subject(self, req: Request) -> Optional[str]:
        """The user a request's email belongs to, current or historical (SPEC I1)."""
        return self._identity.resolve(req.email)

    def resources(self, req: Request, subject: Optional[str]) -> Tuple[LinkedResource, ...]:
        """Non-account resources named by the case's T rows and LINK rows (SPEC L12)."""
        if subject is None:
            return ()
        found: List[LinkedResource] = []
        for act, basis in self._rows(req, subject):
            if act.system_id == ACCOUNT_SERVICE:
                continue
            treatment = act.treatment if basis == BASIS_TARGET_ROW else None
            if treatment is None:
                try:
                    treatment = self._policy.treatment(act.system_id, None)
                except PolicyError as error:
                    LOGGER.warning("%s: %s not linked: %s", req.case_id, act.resource_id, error)
                    continue
            found.append(LinkedResource(act.system_id, act.resource_id, treatment, basis))
        return tuple(found)

    def account(
        self, req: Request, subject: Optional[str], resources: Sequence[LinkedResource]
    ) -> AccountChoice:
        """The case account by the first unambiguous L12 rule, else none."""
        if subject is None:
            return AccountChoice(None, BASIS_NONE, "request email matches no subject")
        notes: List[str] = []
        stages = (
            (BASIS_EVIDENCE, self._evidence_accounts(req, subject)),
            (BASIS_POINTER, self._pointer_accounts(req, subject, resources)),
        )
        for basis, candidates in stages:
            if len(candidates) == 1:
                return AccountChoice(candidates[0], basis, "; ".join(notes))
            if candidates:
                notes.append("%s accounts ambiguous: %s" % (basis, ", ".join(candidates)))
        return AccountChoice(None, BASIS_NONE, "; ".join(notes))

    # -- rows --------------------------------------------------------------

    def _rows(self, req: Request, subject: str) -> List[Tuple[ClassifiedActivity, str]]:
        """The case's T rows and LINK rows with their basis label."""
        targets = [
            (act, BASIS_TARGET_ROW)
            for act in self._targets
            if req.requested_at < act.t <= req.audit_at
            and self._index.owned_by(act.resource_id, subject, req.audit_at)
        ]
        links = [
            (act, BASIS_CATALOG_LINK)
            for act in self._links
            if act.linked_user == subject and req.reported_at <= act.t <= req.audit_at
        ]
        return targets + links

    # -- account rules -----------------------------------------------------

    def _evidence_accounts(self, req: Request, subject: str) -> Tuple[str, ...]:
        """Accounts tied to the subject by evidence; among several, the window-named ones."""
        tied = [
            rid
            for rid in self._index.rids_by_user.get(subject, ())
            if system_for(rid) == ACCOUNT_SERVICE and self._index.tied_by(rid, subject, req.audit_at)
        ]
        if len(tied) < 2:
            return tuple(tied)
        named = [rid for rid in tied if self._index.named_between(rid, req.reported_at, req.audit_at)]
        return tuple(named or tied)

    def _pointer_accounts(
        self, req: Request, subject: str, resources: Sequence[LinkedResource]
    ) -> Tuple[str, ...]:
        """Accounts named by the case's account rows or by the source of its search documents."""
        named: Set[str] = {
            act.resource_id
            for act, _basis in self._rows(req, subject)
            if act.system_id == ACCOUNT_SERVICE
        }
        for resource in resources:
            named.update(self._index.pointers.get(resource.resource_id, ()))
        return tuple(sorted(rid for rid in named if self._index.owned_by(rid, subject, req.audit_at)))
