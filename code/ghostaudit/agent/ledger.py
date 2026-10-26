"""CitationLedger: every id a tool returned during one investigation (SPEC 12.3).

The submit gate accepts a cited id only if the ledger holds it, and only if the thing it names
existed by the audit time of the case it supports. The ledger maps an id to the moment it
came into existence (a file's capture time, an activity's event time, an audit entry's
event time).
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Tuple


class CitationLedger:
    """Records ids with their times; the only way an id can become citable."""

    def __init__(self) -> None:
        self._times: Dict[str, int] = {}

    def record(self, identifier: str, moment: int) -> None:
        """Remember that a tool showed `identifier`, which came into existence at `moment`."""
        self._times[identifier] = moment

    def record_all(self, entries: Iterable[Tuple[str, int]]) -> None:
        for identifier, moment in entries:
            self.record(identifier, moment)

    def __contains__(self, identifier: object) -> bool:
        return identifier in self._times

    def time_of(self, identifier: str) -> Optional[int]:
        """The moment an id came into existence, or None when no tool returned it."""
        return self._times.get(identifier)

    def snapshot(self) -> Mapping[str, int]:
        """An immutable-by-convention copy, sorted by id."""
        return dict(sorted(self._times.items()))
