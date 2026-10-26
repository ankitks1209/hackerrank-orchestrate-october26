"""Case linking, step two, part one: the working graph and its passes (SPEC L4-L7).

`LinkGraph` holds the candidate edges of one solve and narrows them with the fixed
point of L4, the never-mix rule of L5 and the FIFO pairings of L6/L6b. `link_solver`
drives it. The only timing rule inside the graph is process order (L4d): a worker row
belongs to a case only if it follows one of that case's account rows.

Account bases: unique, fifo_pairing, none (the hand-crafted step adds evidence, activity_pointer).
An account is `unique` only when it is the sole candidate of its case and no other
case holds it (L4b); cases left sharing one account stay tied for the FIFO pairing.
Row bases: evidence_owner (identifier link, L1), unique, elimination, coupling,
never_mix and fifo_pairing. Every loop runs over sorted keys; ids are only ordered,
never combined (L8).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ghostaudit.config import Config
from ghostaudit.emit import case_sort_key
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.linking import Candidates, is_compliant_row
from ghostaudit.model import ActKind, CaseLinks, ClassifiedActivity, LinkedResource, Request, Treatment

LOGGER = logging.getLogger(__name__)

ACCOUNT_UNIQUE = "unique"
ACCOUNT_FIFO = "fifo_pairing"
ACCOUNT_NONE = "none"

ROW_OWNER = "evidence_owner"
ROW_UNIQUE = "unique"
ROW_ELIMINATION = "elimination"
ROW_COUPLING = "coupling"
ROW_NEVER_MIX = "never_mix"
ROW_FIFO = "fifo_pairing"
ROW_AGENT = "agent"
ACCOUNT_AGENT = "agent"

TARGET_ROW = "row"
TARGET_ACCOUNT = "account"
ACTION_ASSIGN = "assign"
ACTION_REJECT = "reject"


@dataclass(frozen=True)
class Contest:
    """What the fixed point leaves undecided (SPEC L4, 12.1).

    `rows` maps a worker row's activity id to the cases still competing for it, and
    `accounts` maps an account row's activity id to the tied cases that still hold it,
    both in natural case order. Only the agent (or, failing that, the FIFO fallback)
    decides these.
    """

    rows: Mapping[str, Tuple[str, ...]]
    accounts: Mapping[str, Tuple[str, ...]]


@dataclass(frozen=True)
class LinkDecision:
    """One resolution of a contested row or account: assign it to a case, or reject it as a decoy."""

    target: str  # TARGET_ROW or TARGET_ACCOUNT
    activity_id: str
    action: str  # ACTION_ASSIGN or ACTION_REJECT
    case_id: str = ""  # the owner, for an assignment


@dataclass(frozen=True)
class LinkStats:
    """Counts for the diagnostics and the size of the agent's workload (SPEC L6, L7).

    `rows_ambiguous` and `rows_unresolved` are worker rows still shared by several cases
    after the fixed point and never-mix, and after the agent's decisions, both before the
    FIFO fallback. The `eval_` fields count only rows that an evaluation case could own.
    """

    account_basis: Mapping[str, int]
    eval_account_basis: Mapping[str, int]
    row_basis: Mapping[str, int]
    rows_ambiguous: int
    eval_rows_ambiguous: int
    rows_unresolved: int
    eval_rows_unresolved: int


class LinkGraph:
    """Mutable working graph of one solve; every loop runs over sorted keys."""

    def __init__(
        self,
        base: Candidates,
        requests: Sequence[Request],
        acts: Sequence[ClassifiedActivity],
        index: EvidenceIndex,
        config: Config,
        subjects: Mapping[str, Optional[str]],
    ) -> None:
        self._acts = base.activities
        self._flags = config.flags
        self._requests = {req.case_id: req for req in requests}
        self._accounts: Dict[str, Set[str]] = {
            case_id: set(ids) for case_id, ids in base.accounts_of_case.items()
        }
        self._pin_owned_accounts(index, subjects)
        self._cases_of_row: Dict[str, Set[str]] = {
            row_id: set(ids) for row_id, ids in base.cases_of_row.items()
        }
        self._owned_rows = frozenset(
            row_id for row_id in self._cases_of_row if self._has_owner(index, row_id)
        )
        self._row_basis = {row_id: ROW_UNIQUE for row_id in self._cases_of_row}
        self._account_basis: Dict[str, str] = {}
        self._leftover: Dict[str, Tuple[str, ...]] = {}
        self._checkpoints = _first_checkpoints(acts)
        self._label = ROW_ELIMINATION
        self._decided: FrozenSet[str] = frozenset()
        self._ambiguous = (0, 0)
        self._unresolved = (0, 0)

    def _pin_owned_accounts(self, index: EvidenceIndex, subjects: Mapping[str, Optional[str]]) -> None:
        """L1 is the strongest link: of a case's account candidates, the ones that evidence ties to its own
        subject (admissible at its `audit_at`) replace the ownerless ones."""
        for case_id, pool in self._accounts.items():
            subject = subjects.get(case_id)
            if subject is None:
                continue
            audit_at = self._requests[case_id].audit_at
            own = {
                activity_id for activity_id in pool
                if index.tied_by(self._acts[activity_id].resource_id, subject, audit_at)
            }
            if own:
                self._accounts[case_id] = own

    def solve(self) -> None:
        """Fixed point, then the FIFO tie-breaks of SPEC L6."""
        self.settle()
        self.finish()

    def settle(self) -> None:
        """The fixed point alone: what the evidence and process order decide without a tie-break."""
        self._settle()
        self._decided = frozenset(row_id for row_id, cases in self._cases_of_row.items() if len(cases) == 1)
        self._ambiguous = self._count_ambiguous_rows()

    def contest(self) -> Contest:
        """The rows and accounts that are still contested after `settle`."""
        rows = {
            row_id: tuple(sorted(cases, key=case_sort_key))
            for row_id, cases in sorted(self._cases_of_row.items())
            if len(cases) > 1
        }
        tied = frozenset(self._tied_cases())
        accounts: Dict[str, Tuple[str, ...]] = {}
        for account_id, cases in sorted(self._holders().items()):
            tied_holders = tuple(case_id for case_id in cases if case_id in tied)
            if tied_holders:
                accounts[account_id] = tied_holders
        return Contest(rows, accounts)

    def apply(self, decisions: Iterable[LinkDecision]) -> int:
        """Apply resolutions of contested rows and accounts, then settle again; returns how many applied.

        A decision that names a target the graph no longer contests, or a case that is not a
        candidate of it, is skipped, so a stale or invalid decision cannot change a link.
        """
        applied = 0
        self._label = ROW_AGENT
        for decision in sorted(decisions, key=lambda d: (d.target, d.activity_id)):
            if decision.target == TARGET_ROW:
                applied += self._apply_row(decision)
            elif decision.target == TARGET_ACCOUNT:
                applied += self._apply_account(decision)
        self._label = ROW_ELIMINATION
        self._settle()
        return applied

    def _apply_row(self, decision: LinkDecision) -> int:
        cases = self._cases_of_row.get(decision.activity_id)
        if cases is None or len(cases) < 2:
            return 0
        if decision.action == ACTION_REJECT:
            return 1 if self._narrow(decision.activity_id, set(), ROW_AGENT) else 0
        if decision.action == ACTION_ASSIGN and decision.case_id in cases:
            return 1 if self._narrow(decision.activity_id, {decision.case_id}, ROW_AGENT) else 0
        return 0

    def _apply_account(self, decision: LinkDecision) -> int:
        tied = frozenset(self._tied_cases())
        holders = [c for c in self._holders().get(decision.activity_id, ()) if c in tied]
        if not holders:
            return 0
        if decision.action == ACTION_ASSIGN and decision.case_id in holders:
            self._accounts[decision.case_id] = {decision.activity_id}
            self._account_basis[decision.case_id] = ACCOUNT_AGENT
            return 1
        if decision.action == ACTION_REJECT:
            for case_id in holders:
                self._drop_account(case_id, decision.activity_id)
            return 1
        return 0

    def _drop_account(self, case_id: str, account_id: str) -> None:
        pool = self._accounts[case_id]
        pool.discard(account_id)
        if not pool:
            self._leftover[case_id] = (account_id,)
            del self._accounts[case_id]

    def finish(self) -> None:
        """The FIFO tie-breaks of SPEC L6 for whatever is still contested (the low-confidence fallback)."""
        self._unresolved = self._count_ambiguous_rows()
        if not self._flags.fifo_pairing:
            return
        self._label = ROW_COUPLING
        self._pair_accounts()
        self._settle()
        self._pair_rows()

    def links(self) -> Dict[str, CaseLinks]:
        """`CaseLinks` for every request, in natural case order."""
        rows_of_case: Dict[str, List[str]] = defaultdict(list)
        for row_id in sorted(self._cases_of_row, key=self._row_key):
            cases = self._cases_of_row[row_id]
            if len(cases) == 1:
                rows_of_case[next(iter(cases))].append(row_id)
        tied = frozenset(self._tied_cases())
        return {
            case_id: self._case_links(case_id, rows_of_case.get(case_id, ()), tied)
            for case_id in sorted(self._requests, key=case_sort_key)
        }

    def stats(self) -> LinkStats:
        """Basis counts over all cases and over evaluation cases only."""
        account_all: Dict[str, int] = defaultdict(int)
        account_eval: Dict[str, int] = defaultdict(int)
        tied = frozenset(self._tied_cases())
        for case_id, req in self._requests.items():
            basis = self._account_state(case_id, tied)[1]
            account_all[basis] += 1
            if not req.is_sample:
                account_eval[basis] += 1
        rows: Dict[str, int] = defaultdict(int)
        for row_id, cases in self._cases_of_row.items():
            if len(cases) == 1:
                rows[self._basis_of_row(row_id)] += 1
        return LinkStats(
            account_basis=dict(sorted(account_all.items())),
            eval_account_basis=dict(sorted(account_eval.items())),
            row_basis=dict(sorted(rows.items())),
            rows_ambiguous=self._ambiguous[0],
            eval_rows_ambiguous=self._ambiguous[1],
            rows_unresolved=self._unresolved[0],
            eval_rows_unresolved=self._unresolved[1],
        )

    # -- fixed point (L4) ------------------------------------------------

    def _settle(self) -> None:
        """Repeat the elimination passes until nothing changes (SPEC L4)."""
        changed = True
        while changed:
            changed = self._drop_unfit_edges()
            changed |= self._constrain_accounts()
            changed |= self._fix_singletons()
            changed |= self._flags.never_mix and self._apply_never_mix()

    def _drop_unfit_edges(self) -> bool:
        """L4a, L4d: an ownerless row edge needs an account of its case that the row follows."""
        changed = False
        for row_id in sorted(self._cases_of_row):
            cases = self._cases_of_row[row_id]
            fitting = {case_id for case_id in cases if self._supported(case_id, row_id)}
            keep = fitting if fitting or row_id not in self._owned_rows else cases
            changed |= self._narrow(row_id, keep, self._label)
        return changed

    def _constrain_accounts(self) -> bool:
        """L4: certain rows keep, of a case's accounts, the ones that fit most of them."""
        certain: Dict[str, List[str]] = defaultdict(list)
        for row_id in sorted(self._cases_of_row):
            cases = self._cases_of_row[row_id]
            if len(cases) == 1:
                certain[next(iter(cases))].append(row_id)
        changed = False
        for case_id in self._tied_cases():
            pool = self._accounts[case_id]
            scores = {a: sum(self._fits(r, a) for r in certain[case_id]) for a in pool}
            best = max(scores.values())
            keep = {a for a, score in scores.items() if score == best}
            if keep != pool:
                self._accounts[case_id] = keep
                changed = True
        return changed

    def _fix_singletons(self) -> bool:
        """L4b, L4c: a claimed account leaves every other case.

        A case whose candidates are all claimed by other cases is left with no account,
        and its candidates are kept as its leftover. Claims are computed before any
        removal, so the result does not depend on the order of the cases.
        """
        claims = self._claims()
        changed = False
        for case_id in sorted(self._accounts, key=case_sort_key):
            pool = self._accounts[case_id]
            taken = {a for a in pool if claims.get(a, case_id) != case_id}
            if not taken:
                continue
            changed = True
            if taken == pool:
                self._leftover[case_id] = tuple(sorted(pool, key=self._account_key))
                del self._accounts[case_id]
            else:
                pool -= taken
        return changed

    def _claims(self) -> Dict[str, str]:
        """Account to case, for accounts that are the only candidate of exactly one case (L4c).

        An account that is the only candidate of several cases is claimed by none of
        them; those cases stay tied (L4b) and go to the FIFO pairing.
        """
        sole_holders: Dict[str, List[str]] = defaultdict(list)
        for case_id in sorted(self._accounts, key=case_sort_key):
            pool = self._accounts[case_id]
            if len(pool) == 1:
                sole_holders[next(iter(pool))].append(case_id)
        return {a: cases[0] for a, cases in sole_holders.items() if len(cases) == 1}

    # -- never-mix (L5) --------------------------------------------------

    def _apply_never_mix(self) -> bool:
        """A tied row avoids cases of the opposite class (SPEC L5)."""
        violating, compliant = self._case_classes()
        changed = False
        for row_id in sorted(self._cases_of_row):
            cases = self._cases_of_row[row_id]
            row = self._acts[row_id]
            if len(cases) < 2 or row.treatment is Treatment.RETAIN:
                continue
            allowed = cases - (violating if is_compliant_row(row) else compliant)
            changed |= self._narrow(row_id, allowed or cases, ROW_NEVER_MIX)
        return changed

    def _case_classes(self) -> Tuple[FrozenSet[str], FrozenSet[str]]:
        """Cases with violating rows (or a checkpointed account) and with compliant rows."""
        violating: Set[str] = set()
        compliant: Set[str] = set()
        for row_id, cases in self._cases_of_row.items():
            if len(cases) != 1:
                continue
            row = self._acts[row_id]
            if not is_compliant_row(row):
                violating.update(cases)
            elif row.treatment is not Treatment.RETAIN:
                compliant.update(cases)
        tied = frozenset(self._tied_cases())
        for case_id, accounts in self._accounts.items():
            if case_id not in tied and self._checkpointed(case_id, next(iter(accounts))):
                violating.add(case_id)
        return frozenset(violating), frozenset(compliant)

    def _checkpointed(self, case_id: str, account_id: str) -> bool:
        seen = self._checkpoints.get(self._acts[account_id].resource_id)
        return seen is not None and seen <= self._requests[case_id].audit_at

    # -- FIFO (L6, L6b) ---------------------------------------------------

    def _pair_accounts(self) -> None:
        """Pair the still-tied accounts, ascending id, with their cases, ascending id."""
        tied = self._tied_cases()
        holders = self._holders()
        seen: Set[str] = set()
        for start in tied:
            if start in seen:
                continue
            group = _component(start, self._accounts, holders)
            seen.update(group)
            options = {
                case_id: sorted(self._accounts[case_id], key=self._account_key)
                for case_id in group
            }
            paired = _pair(group, options)
            for case_id in group:
                if case_id in paired:
                    self._accounts[case_id] = {paired[case_id]}
                    self._account_basis[case_id] = ACCOUNT_FIFO
                else:
                    self._leftover[case_id] = tuple(options[case_id])
                    del self._accounts[case_id]

    def _pair_rows(self) -> None:
        """Give each still-tied row to the case whose report is nearest in process order.

        A violation, flow or restore row is observed after the report it follows, so it
        goes to the case with the latest `reported_at` before it; a policy row precedes
        its report, so it goes to the case with the earliest `reported_at` after it. Ties
        go to the lower case id. This is the low-confidence fallback of SPEC L6b: it uses no
        fitted offset, only the order of the reports.
        """
        for row_id in sorted(self._cases_of_row, key=self._row_key):
            cases = self._cases_of_row[row_id]
            if len(cases) > 1:
                self._narrow(row_id, {self._nearest_report(row_id, cases)}, ROW_FIFO)

    def _nearest_report(self, row_id: str, cases: Set[str]) -> str:
        return nearest_report_case(self._acts[row_id], cases, self._requests)

    # -- helpers ----------------------------------------------------------

    def _tied_cases(self) -> List[str]:
        """Cases with several account candidates, or with one that another case also holds."""
        holders = self._holders()
        return [
            case_id
            for case_id in sorted(self._accounts, key=case_sort_key)
            if len(self._accounts[case_id]) > 1
            or len(holders[next(iter(self._accounts[case_id]))]) > 1
        ]

    def _holders(self) -> Dict[str, List[str]]:
        """Account to the cases that hold it as a candidate, in natural case order."""
        holders: Dict[str, List[str]] = defaultdict(list)
        for case_id in sorted(self._accounts, key=case_sort_key):
            for account_id in sorted(self._accounts[case_id]):
                holders[account_id].append(case_id)
        return holders

    def _supported(self, case_id: str, row_id: str) -> bool:
        accounts = self._accounts.get(case_id, ())
        return any(self._fits(row_id, account_id) for account_id in accounts)

    def _fits(self, row_id: str, account_id: str) -> bool:
        """Process order (L4d): a worker row follows the account row it belongs to."""
        return self._acts[row_id].t > self._acts[account_id].t

    def _narrow(self, row_id: str, keep: Set[str], label: str) -> bool:
        """Restrict a row to `keep`; an empty set removes the row as a decoy (L4d)."""
        cases = self._cases_of_row[row_id]
        if keep == cases:
            return False
        if keep:
            self._cases_of_row[row_id] = set(keep)
            self._row_basis[row_id] = label
        else:
            del self._cases_of_row[row_id]
        return True

    def _count_ambiguous_rows(self) -> Tuple[int, int]:
        """(all, evaluation) rows that still belong to several cases."""
        everywhere = evaluation = 0
        for cases in self._cases_of_row.values():
            if len(cases) > 1:
                everywhere += 1
                evaluation += any(not self._requests[c].is_sample for c in cases)
        return everywhere, evaluation

    def _has_owner(self, index: EvidenceIndex, row_id: str) -> bool:
        """True when evidence admissible at the latest audit of the row's candidate cases ties an owner (T1)."""
        rid = self._acts[row_id].resource_id
        horizon = max(self._requests[case_id].audit_at for case_id in self._cases_of_row[row_id])
        return any(index.tied_by(rid, user, horizon) for user in index.users_by_rid.get(rid, ()))

    def _row_key(self, row_id: str) -> Tuple[int, str]:
        return self._acts[row_id].t, row_id

    def _account_key(self, account_id: str) -> Tuple[object, str]:
        return case_sort_key(self._acts[account_id].resource_id), account_id

    def _basis_of_row(self, row_id: str) -> str:
        """The rule that decided the row; an agent decision or a fallback pairing is never shown as evidence."""
        label = self._row_basis[row_id]
        if label in (ROW_AGENT, ROW_FIFO):
            return label
        return ROW_OWNER if row_id in self._owned_rows and row_id in self._decided else label

    def _account_state(self, case_id: str, tied: FrozenSet[str]) -> Tuple[Optional[str], str]:
        """(account activity id, basis) of a case; None when none is determined."""
        pool = self._accounts.get(case_id, ())
        if not pool or case_id in tied:
            return None, ACCOUNT_NONE
        return next(iter(pool)), self._account_basis.get(case_id, ACCOUNT_UNIQUE)

    def _case_links(
        self, case_id: str, row_ids: Sequence[str], tied: FrozenSet[str]
    ) -> CaseLinks:
        account_activity, basis = self._account_state(case_id, tied)
        notes: List[str] = []
        if account_activity is not None:
            notes.append("account_row=%s" % account_activity)
        elif case_id in self._accounts:
            notes.append("account tied between %s" % ", ".join(sorted(self._accounts[case_id])))
        elif case_id in self._leftover:
            notes.append("no free account among %s" % ", ".join(sorted(self._leftover[case_id])))
        resources: Dict[Tuple[str, str], LinkedResource] = {}
        for row_id in row_ids:
            row = self._acts[row_id]
            if row.treatment is None:
                LOGGER.warning("%s has no treatment; not linked to %s", row_id, case_id)
                continue
            resources.setdefault(
                (row.system_id, row.resource_id),
                LinkedResource(
                    row.system_id, row.resource_id, row.treatment, self._basis_of_row(row_id)
                ),
            )
        account_id = None if account_activity is None else self._acts[account_activity].resource_id
        return CaseLinks(case_id, account_id, basis, tuple(resources.values()), tuple(notes))


def nearest_report_case(
    row: ClassifiedActivity, cases: Iterable[str], requests: Mapping[str, Request]
) -> str:
    """The candidate whose report is nearest in process order (the fallback's choice, SPEC L6b).

    A policy row precedes its report, so the earliest `reported_at` wins; a violation, flow or
    restore row follows its report, so the latest wins. Ties go to the lower case id.
    """
    if is_compliant_row(row):
        return min(cases, key=lambda c: (requests[c].reported_at, case_sort_key(c)))
    return min(cases, key=lambda c: (-requests[c].reported_at, case_sort_key(c)))


def _first_checkpoints(acts: Iterable[ClassifiedActivity]) -> Dict[str, int]:
    """Earliest replication checkpoint time per account resource (SPEC L5)."""
    first: Dict[str, int] = {}
    for act in acts:
        if act.kind is ActKind.REPLICATION_CHECKPOINT:
            first[act.resource_id] = min(act.t, first.get(act.resource_id, act.t))
    return first


def _component(
    start: str, accounts: Mapping[str, Set[str]], holders: Mapping[str, Sequence[str]]
) -> List[str]:
    """Tied cases connected to `start` through shared account candidates, in natural order."""
    found = {start}
    pending = [start]
    while pending:
        case_id = pending.pop()
        for account_id in sorted(accounts[case_id]):
            for other in holders[account_id]:
                if other not in found:
                    found.add(other)
                    pending.append(other)
    return sorted(found, key=case_sort_key)


def _pair(cases: Sequence[str], options: Mapping[str, Sequence[str]]) -> Dict[str, str]:
    """Maximum matching in which each case, earliest first, takes its smallest free account.

    A case whose accounts are all taken re-routes the case holding one of them, so no
    case stays unmatched while a matching for everyone exists.
    """
    owner: Dict[str, str] = {}

    def place(case_id: str, visited: Set[str]) -> bool:
        for account_id in options[case_id]:
            if account_id not in owner:
                owner[account_id] = case_id
                return True
        for account_id in options[case_id]:
            if account_id not in visited:
                visited.add(account_id)
                if place(owner[account_id], visited):
                    owner[account_id] = case_id
                    return True
        return False

    for case_id in cases:
        place(case_id, set())
    return {case_id: account_id for account_id, case_id in owner.items()}
