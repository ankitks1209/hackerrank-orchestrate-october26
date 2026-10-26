"""Investigation units: cases that compete for the same contested targets (SPEC 12.1).

Two cases compete when some contested row or account lists both as candidates. A unit is a
connected component of the competition graph that contains at least one case routed
`investigate`. A component larger than `MAX_UNIT_CASES` is cut into consecutive chunks in
order of `reported_at`, so one prompt stays small. A contested target is offered to exactly
one unit: the one holding the case that the deterministic fallback would pick (the nearest
report in process order), or, for an account, the first unit holding a candidate. Inside the
unit the model sees only the candidates that belong to it.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Set, Tuple

from ghostaudit.agent.model import ROUTE_INVESTIGATE, UnitSpec
from ghostaudit.emit import case_sort_key
from ghostaudit.link_graph import Contest, nearest_report_case
from ghostaudit.model import ClassifiedActivity, Request

MAX_UNIT_CASES = 8  # cases per unit; a larger component is split in report order
UNIT_ID_FORMAT = "unit_%03d"


def build_units(
    contest: Contest,
    routes: Mapping[str, str],
    requests: Mapping[str, Request],
    activities: Mapping[str, ClassifiedActivity],
) -> Tuple[UnitSpec, ...]:
    """The investigation units for `routes`, in a deterministic order."""
    components = _components(contest)
    chunks: List[Tuple[str, ...]] = []
    for component in components:
        if not any(routes.get(case_id) == ROUTE_INVESTIGATE for case_id in component):
            continue
        ordered = sorted(component, key=lambda c: (requests[c].reported_at, case_sort_key(c)))
        chunks.extend(
            tuple(ordered[start : start + MAX_UNIT_CASES])
            for start in range(0, len(ordered), MAX_UNIT_CASES)
        )
    owner = {case_id: position for position, chunk in enumerate(chunks) for case_id in chunk}
    rows: List[Dict[str, Tuple[str, ...]]] = [{} for _ in chunks]
    accounts: List[Dict[str, Tuple[str, ...]]] = [{} for _ in chunks]
    for row_id, cases in contest.rows.items():
        if not any(routes.get(case_id) == ROUTE_INVESTIGATE for case_id in cases):
            continue
        prior = nearest_report_case(activities[row_id], cases, requests)
        if prior in owner:
            rows[owner[prior]][row_id] = tuple(c for c in cases if owner.get(c) == owner[prior])
    for account_id, cases in contest.accounts.items():
        placed = [owner[c] for c in cases if c in owner]
        if placed:
            accounts[min(placed)][account_id] = tuple(c for c in cases if owner.get(c) == min(placed))
    units = [
        UnitSpec(UNIT_ID_FORMAT % (position + 1), chunk, rows[position], accounts[position])
        for position, chunk in enumerate(chunks)
        if rows[position] or accounts[position]
    ]
    return tuple(units)


def _components(contest: Contest) -> List[Tuple[str, ...]]:
    """Connected components of the competition graph, each in natural case order."""
    parent: Dict[str, str] = {}

    def find(case_id: str) -> str:
        parent.setdefault(case_id, case_id)
        while parent[case_id] != case_id:
            parent[case_id] = parent[parent[case_id]]
            case_id = parent[case_id]
        return case_id

    for cases in list(contest.rows.values()) + list(contest.accounts.values()):
        for case_id in cases:
            find(case_id)
        for other in cases[1:]:
            parent[find(other)] = find(cases[0])
    groups: Dict[str, Set[str]] = {}
    for case_id in parent:
        groups.setdefault(find(case_id), set()).add(case_id)
    return sorted(
        (tuple(sorted(group, key=case_sort_key)) for group in groups.values()),
        key=lambda group: case_sort_key(group[0]),
    )


def competing_cases(contest: Contest) -> Mapping[str, Tuple[str, ...]]:
    """For every contested case, the other cases it shares a contested target with."""
    shares: Dict[str, Set[str]] = {}
    for cases in list(contest.rows.values()) + list(contest.accounts.values()):
        for case_id in cases:
            shares.setdefault(case_id, set()).update(c for c in cases if c != case_id)
    return {case_id: tuple(sorted(others, key=case_sort_key)) for case_id, others in sorted(shares.items(), key=lambda i: case_sort_key(i[0]))}


def request_map(requests: Sequence[Request]) -> Dict[str, Request]:
    return {request.case_id: request for request in requests}
