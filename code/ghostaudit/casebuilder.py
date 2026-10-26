"""CaseBuilder: verdicts of a case, generated and hand-crafted families (SPEC 8.2, 8.3, L12).

Implements SPEC V1 (the case account always gets its absence check), V2 (audit records),
V3 (legal holds, flag `verify_legal_holds`), V4 (tombstones, redacted) and V5 (absence by
omission), on the resources linked by `ghostaudit.linking` (SPEC L9-L11).

Every linked resource is resolved by `ghostaudit.state.StateResolver`; its required
treatment is the evidence category when the evidence carries one, else the linked
treatment (SPEC 6 discriminators). A resource is violating when its state is not the
verification state of that treatment; a retained record (audit record, legal hold) never is.
SPEC 8.2 then decides what is kept:

* a violating linked resource without a cite is dropped and logged (activity-basis
  findings need an in-window activity id; no case account is in that state in the data);
* a resource to be redacted or anonymized that is ABSENT is dropped and logged: an
  absence proof backs neither an EXPOSED_PII finding nor a REDACTED or ANONYMIZED check
  (SPEC 8.2, "absent under a keep-the-record treatment");
* in an INCOMPLETE case every compliant resource is kept, with an empty cite;
* in a COMPLETE case a compliant resource is kept only with a cite. The account's cite
  falls back to the omission rule V5 (`choose_omission_cite`), which needs the other
  verdicts of the case and so runs last; with no proof the account step is omitted and
  counted;
* a retained record (audit record, legal hold) is cited only by a file that shows it
  present; a scope that omits it proves absence, so it stays uncited and is dropped
  from a COMPLETE case (SPEC V2, L11).

The builder never invents an id. A case without an account row (hand-crafted samples and
media cases, SPEC L12) goes through the hand-crafted path of `build`: `ghostaudit.handcrafted` supplies
its account and its T-row and LINK-row resources, and the same assembly applies. With no
account the case simply has no account step (SPEC V1 exception L12.4). A LINK-row resource
that no evidence observes, or that ends without a step, is listed in the diagnostics with
the reason (media facts missing is the usual cause).
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

from ghostaudit.config import Config
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.handcrafted import BASIS_CATALOG_LINK, HandcraftedSources
from ghostaudit.model import (
    ACCOUNT_SERVICE,
    LEGAL_SERVICE,
    CaseLinks,
    LinkedResource,
    ObsState,
    Request,
    ResourceVerdict,
    Treatment,
)
from ghostaudit.policy import PolicyEngine
from ghostaudit.state import (
    BASIS_SCOPE,
    BASIS_UNOBSERVED,
    Resolved,
    StateResolver,
    choose_omission_cite,
)

LOGGER = logging.getLogger(__name__)

BASIS_ACCOUNT = "account"  # basis label of the case account's verdict (V1)

# Rules that no public sample exercises; every firing is listed in the diagnostics.
UNTESTED_LEGAL_HOLD = "V3 legal hold linked"
# Treatments that keep the record; an ABSENT state proves neither exposure nor treatment (SPEC 8.2).
_KEEP_RECORD = frozenset({Treatment.REDACT, Treatment.ANONYMIZE})


@dataclass(frozen=True)
class BuildStats:
    """What the builder did so far, for the diagnostics (SPEC 8.3 V1, V5, 8.2).

    `omitted_account` counts COMPLETE cases whose account step was omitted for lack of a
    proof file; `omission_cites` those whose account cite came from rule V5;
    `dropped_violating` and `dropped_compliant` count resources dropped by SPEC 8.2, and
    `dropped_absent` those to be redacted or anonymized that are already ABSENT;
    `category_overrides` counts resources whose evidence category replaced the linked
    treatment; `untested` lists every firing of a rule the samples do not cover.
    For the hand-crafted family (SPEC L12): `handcrafted_cases` counts its cases,
    `account_basis` the cases per account basis, and `handcrafted_notes` every ambiguity and every
    LINK-row resource that no evidence observes.
    """

    cases: int
    omitted_account: int
    omission_cites: int
    category_overrides: int
    dropped_violating: int
    dropped_compliant: int
    untested: Tuple[str, ...]
    dropped_absent: int = 0
    handcrafted_cases: int = 0
    account_basis: Tuple[Tuple[str, int], ...] = ()
    handcrafted_notes: Tuple[str, ...] = ()


class CaseBuilder:
    """Assembles ResourceVerdicts per case from its links (SPEC 8.2, 8.3)."""

    def __init__(
        self,
        resolver: StateResolver,
        policy: PolicyEngine,
        index: EvidenceIndex,
        config: Config,
        handcrafted: HandcraftedSources,
    ) -> None:
        self._resolver = resolver
        self._policy = policy
        self._index = index
        self._flags = config.flags
        self._handcrafted = handcrafted
        self._counts: Counter[str] = Counter()
        self._account_basis: Counter[str] = Counter()
        self._untested: List[str] = []
        self._notes: List[str] = []

    def stats(self) -> BuildStats:
        """Counters of every case built so far."""
        return BuildStats(
            cases=self._counts["cases"],
            omitted_account=self._counts["omitted_account"],
            omission_cites=self._counts["omission_cites"],
            category_overrides=self._counts["category_overrides"],
            dropped_violating=self._counts["dropped_violating"],
            dropped_compliant=self._counts["dropped_compliant"],
            untested=tuple(self._untested),
            dropped_absent=self._counts["dropped_absent"],
            handcrafted_cases=self._counts["handcrafted"],
            account_basis=tuple(sorted(self._account_basis.items())),
            handcrafted_notes=tuple(self._notes),
        )

    def build(self, req: Request, links: CaseLinks) -> Tuple[ResourceVerdict, ...]:
        """Verdicts of any case: with an account row the generated family, else hand-crafted."""
        if links.account_id is not None:
            return self._assemble(req, links.account_id, links.resources)
        return self._build_handcrafted(req, links)

    def _build_handcrafted(self, req: Request, links: CaseLinks) -> Tuple[ResourceVerdict, ...]:
        """Verdicts of a case without an A-row account (SPEC L12).

        Resources are the case's links plus its T and LINK rows; the account is the first
        unambiguous L12 rule, and no account step is made when none applies.
        """
        subject = self._handcrafted.subject(req)
        resources = links.resources + self._handcrafted.resources(req, subject)
        choice = self._handcrafted.account(req, subject, resources)
        self._counts["handcrafted"] += 1
        self._account_basis[choice.basis] += 1
        if choice.note:
            self._notes.append("%s: %s" % (req.case_id, choice.note))
        return self._assemble(req, choice.account_id, resources)

    def _assemble(
        self, req: Request, account_id: Optional[str], resources: Sequence[LinkedResource]
    ) -> Tuple[ResourceVerdict, ...]:
        """The case's verdicts (SPEC 8.2); the account verdict comes first when there is one."""
        self._counts["cases"] += 1
        account: Optional[ResourceVerdict] = None
        by_omission = False
        if account_id is not None:
            account, by_omission = self._account_verdict(req, account_id)
        others = self._resource_verdicts(req, resources, account)
        if (account is not None and account.violating) or any(v.violating for v in others):
            return tuple(self._incomplete(account, others))
        return tuple(self._complete(req, account, others, by_omission))

    # -- verdict construction ---------------------------------------------

    def _account_verdict(self, req: Request, account_id: str) -> Tuple[ResourceVerdict, bool]:
        """The V1 verdict, and whether a COMPLETE case must take its cite from rule V5.

        The account is violating when it is still present. Its absence is proved by
        omission when only a scope, or nothing, shows it gone (SPEC V5).
        """
        resolved = self._resolver.resolve(account_id, ACCOUNT_SERVICE, req)
        violating = self._is_violating(Treatment.DELETE, resolved)
        verdict = ResourceVerdict(
            ACCOUNT_SERVICE,
            account_id,
            Treatment.DELETE,
            violating,
            resolved.cite,
            BASIS_ACCOUNT,
            "%s via %s as DELETE" % (_state_name(resolved), resolved.basis),
            resolved.note,
        )
        by_omission = not violating and (
            not resolved.cite or resolved.basis in (BASIS_SCOPE, BASIS_UNOBSERVED)
        )
        return verdict, by_omission

    def _resource_verdicts(
        self,
        req: Request,
        resources: Sequence[LinkedResource],
        account: Optional[ResourceVerdict],
    ) -> List[ResourceVerdict]:
        """Verdicts of the linked resources other than the account, in link order."""
        seen = set() if account is None else {(account.system_id, account.resource_id)}
        verdicts: List[ResourceVerdict] = []
        for link in resources:
            key = (link.system_id, link.resource_id)
            if key in seen or self._skipped(req, link):
                continue
            seen.add(key)
            verdict = self._linked_verdict(req, link)
            if verdict is not None:
                verdicts.append(verdict)
        return verdicts

    def _skipped(self, req: Request, link: LinkedResource) -> bool:
        """V3: legal holds are verified only when the flag is on."""
        is_hold = link.system_id == LEGAL_SERVICE and link.treatment is Treatment.RETAIN
        skipped = is_hold and not self._flags.verify_legal_holds
        if skipped:
            LOGGER.info("%s: legal hold %s not verified (flag off)", req.case_id, link.resource_id)
        return skipped

    def _linked_verdict(self, req: Request, link: LinkedResource) -> Optional[ResourceVerdict]:
        resolved = self._resolver.resolve(link.resource_id, link.system_id, req)
        treatment = self._treatment(link, resolved)
        violating = self._is_violating(treatment, resolved)
        if resolved.state is None and treatment is not Treatment.RETAIN:
            self._drop(req, link, "unobserved: no evidence and no activity")
            return None
        if resolved.state is ObsState.ABSENT and treatment in _KEEP_RECORD:
            self._drop(
                req, link, "ABSENT via %s under %s: nothing exposed, no treatment to verify"
                % (resolved.basis, treatment.value), "dropped_absent",
            )
            return None
        if violating and (not resolved.cite or resolved.basis == BASIS_SCOPE):
            # A scope that omits a resource proves absence, never an active flow or a remaining record.
            self._drop(req, link, "violating with no citable proof")
            return None
        self._note_untested(req, link)
        return ResourceVerdict(
            link.system_id,
            link.resource_id,
            treatment,
            violating,
            _proof_cite(treatment, resolved),
            link.basis,
            "%s via %s as %s" % (_state_name(resolved), resolved.basis, treatment.value),
            resolved.note,
        )

    def _treatment(self, link: LinkedResource, resolved: Resolved) -> Treatment:
        """The evidence category decides first (SPEC 6 discriminators), then the link."""
        if resolved.category is None:
            return link.treatment
        treatment = self._policy.treatment(link.system_id, resolved.category)
        if treatment is not link.treatment:
            self._counts["category_overrides"] += 1
        return treatment

    def _is_violating(self, treatment: Treatment, resolved: Resolved) -> bool:
        """A retained record is never a finding (SPEC 8.3 V2, V3)."""
        if resolved.state is None or treatment is Treatment.RETAIN:
            return False
        return not self._policy.is_compliant(treatment, resolved.state)

    def _drop(
        self, req: Request, link: LinkedResource, why: str, counter: str = "dropped_violating"
    ) -> None:
        LOGGER.warning("%s: dropped %s/%s: %s", req.case_id, link.system_id, link.resource_id, why)
        self._counts[counter] += 1
        self._note_link_row(req, link.basis, link.resource_id, "dropped, " + why)

    def _note_link_row(self, req: Request, basis: str, resource_id: str, what: str) -> None:
        """Diagnostics note for a LINK-row resource that ends without its step (SPEC L12)."""
        if basis == BASIS_CATALOG_LINK:
            self._notes.append(
                "%s: LINK-row resource %s %s (media facts missing?)" % (req.case_id, resource_id, what)
            )

    def _note_untested(self, req: Request, link: LinkedResource) -> None:
        rule = None
        if link.system_id == LEGAL_SERVICE:
            rule = UNTESTED_LEGAL_HOLD
        if rule is not None:
            self._untested.append("%s: %s (%s)" % (req.case_id, rule, link.resource_id))

    # -- case-level assembly ------------------------------------------------

    @staticmethod
    def _incomplete(
        account: Optional[ResourceVerdict], others: Sequence[ResourceVerdict]
    ) -> List[ResourceVerdict]:
        """SPEC 8.2: findings keep their cite; every compliant resource is kept, uncited."""
        head = [] if account is None else [account]
        return [
            verdict if verdict.violating else _with_cite(verdict, "")
            for verdict in head + list(others)
        ]

    def _complete(
        self,
        req: Request,
        account: Optional[ResourceVerdict],
        others: Sequence[ResourceVerdict],
        by_omission: bool,
    ) -> List[ResourceVerdict]:
        """SPEC 8.2: a compliant resource needs a cite; the account's may fall back to V5."""
        kept = [verdict for verdict in others if verdict.cite]
        self._counts["dropped_compliant"] += len(others) - len(kept)
        for verdict in others:
            if not verdict.cite:
                self._note_link_row(
                    req, verdict.basis, verdict.resource_id,
                    "has no step, %s with no in-window proof" % verdict.reason,
                )
        if account is None:
            return kept
        cite = account.cite
        if by_omission:
            cite = self._omission_cite(req, account, [verdict.cite for verdict in kept])
        if not cite:
            self._counts["omitted_account"] += 1
            LOGGER.warning(
                "%s: account %s step omitted (no proof file)", req.case_id, account.resource_id
            )
            return kept
        return [_with_cite(account, cite)] + kept

    def _omission_cite(
        self, req: Request, account: ResourceVerdict, case_cites: Sequence[str]
    ) -> str:
        """Rule V5: a proof file for an account that no window file mentions."""
        cite = choose_omission_cite(account.resource_id, case_cites, req, self._index)
        if cite:
            self._counts["omission_cites"] += 1
        return cite or ""


def _proof_cite(treatment: Treatment, resolved: Resolved) -> str:
    """The cite of a resource's verdict; a retained record is proved only by a file showing it.

    A scope that omits an audit record proves absence, which cannot back
    VERIFY_RECORD_PRESENT (SPEC V2, L11).
    """
    if treatment is Treatment.RETAIN and resolved.state is not ObsState.PRESENT:
        return ""
    return resolved.cite


def _with_cite(verdict: ResourceVerdict, cite: str) -> ResourceVerdict:
    return replace(verdict, cite=cite)


def _state_name(resolved: Resolved) -> str:
    return "unobserved" if resolved.state is None else resolved.state.value
