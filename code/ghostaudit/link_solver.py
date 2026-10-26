"""Case linking, step two: solve the graph and assemble links (SPEC L4-L8).

Resolves the candidate graph of `linking.generate_candidates` to one account per case
and one case per worker row, with a basis label for every link.

1. The owner filter (L4a) is already in the candidates, cut at each case's `audit_at`.
2. `ghostaudit.link_graph` applies the fixed point (L4), never-mix (L5) and the FIFO
   pairings (L6, L6b). A row with evidence owners is tied to its owner by identifier
   (L1) and is never dropped for want of an account that precedes it.

The FIFO pairings are the deterministic low-confidence fallback; the agent (`ghostaudit.agent`)
resolves the contested rows before that fallback is used, through the `LinkDecision`s that
`LinkSession.solve` applies between the fixed point and the fallback. No identifier arithmetic is used (L8).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ghostaudit.config import Config
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_graph import Contest, LinkDecision, LinkGraph, LinkStats
from ghostaudit.linking import generate_candidates
from ghostaudit.model import CaseLinks, ClassifiedActivity, Request

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkSolution:
    """Links for every request, the contest the fixed point left, and how many decisions applied."""

    links: Mapping[str, CaseLinks]
    stats: LinkStats
    contest: Contest
    applied: int = 0


class LinkSession:
    """Candidates of a request set, solvable any number of times with different agent decisions.

    Every `solve` builds a fresh graph from the same candidates, runs the fixed point, applies
    the decisions and finishes with the FIFO fallback, so the result is a pure function of the
    decisions (SPEC 12.4).
    """

    def __init__(
        self,
        requests: Sequence[Request],
        activities: Iterable[ClassifiedActivity],
        index: EvidenceIndex,
        identity: IdentityIndex,
        config: Config,
    ) -> None:
        self._requests = tuple(requests)
        self._acts = tuple(activities)
        self._index = index
        self._config = config
        self._subjects = {req.case_id: identity.resolve(req.email) for req in self._requests}
        self.base = generate_candidates(self._requests, self._acts, index, identity)

    def _settled(self) -> LinkGraph:
        graph = LinkGraph(self.base, self._requests, self._acts, self._index, self._config, self._subjects)
        graph.settle()
        return graph

    def contest(self) -> Contest:
        """What the fixed point leaves undecided, before any decision."""
        return self._settled().contest()

    def solve(self, decisions: Iterable[LinkDecision] = ()) -> LinkSolution:
        """Fixed point, `decisions`, then the fallback for whatever is left (SPEC L4-L6, 12.4)."""
        graph = self._settled()
        contest = graph.contest()
        applied = graph.apply(tuple(decisions))
        graph.finish()
        solution = LinkSolution(MappingProxyType(graph.links()), graph.stats(), contest, applied)
        _log_stats(solution.stats)
        return solution


def link_cases(
    requests: Sequence[Request],
    activities: Iterable[ClassifiedActivity],
    index: EvidenceIndex,
    identity: IdentityIndex,
    config: Config,
    decisions: Iterable[LinkDecision] = (),
) -> LinkSolution:
    """Generate the candidates and solve them once."""
    return LinkSession(requests, activities, index, identity, config).solve(decisions)


def _log_stats(stats: LinkStats) -> None:
    """Log how many worker rows the fixed point left to the agent or the fallback."""
    LOGGER.info(
        "links: accounts %s (eval %s), rows %s, contested rows %d (eval %d), left to the fallback %d (eval %d)",
        dict(stats.account_basis),
        dict(stats.eval_account_basis),
        dict(stats.row_basis),
        stats.rows_ambiguous,
        stats.eval_rows_ambiguous,
        stats.rows_unresolved,
        stats.eval_rows_unresolved,
    )
