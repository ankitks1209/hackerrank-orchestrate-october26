"""IdentityView: the identifiers a subject had at a given moment (SPEC 12.2, I2).

`IdentityIndex` answers "who owns this key" over all time. The agent needs "what did this
subject's identifiers look like at the case's `audit_at`", so this view replays the audit log
backwards from the current snapshot: a change made after the moment is undone, and a change
made after it is not reported at all. Only identifier fields (email, phone, email hash) are
shown, never a name.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, FrozenSet, Iterable, List, Mapping, Set, Tuple

from ghostaudit.dataset import AuditRow, Identity
from ghostaudit.identity import FIELD_EMAIL, FIELD_EMAIL_HASH, FIELD_PHONE

FIELDS = (FIELD_EMAIL, FIELD_PHONE, FIELD_EMAIL_HASH)


class IdentityView:
    """Snapshot plus history of every subject, queried at a moment."""

    def __init__(self, identities: Iterable[Identity], audit_rows: Iterable[AuditRow]) -> None:
        self._current: Dict[str, Mapping[str, str]] = {
            identity.user_id: {
                FIELD_EMAIL: identity.email,
                FIELD_PHONE: identity.phone,
                FIELD_EMAIL_HASH: identity.email_hash,
            }
            for identity in identities
        }
        history: Dict[str, List[AuditRow]] = defaultdict(list)
        for row in audit_rows:
            if row.field_name in FIELDS:
                history[row.user_id].append(row)
        self._history = {
            user_id: tuple(sorted(rows, key=lambda row: (row.event_time, row.audit_id)))
            for user_id, rows in history.items()
        }

    def known_users(self) -> FrozenSet[str]:
        return frozenset(self._current)

    def at(self, user_id: str, moment: int) -> Dict[str, object]:
        """Identifiers of `user_id` at `moment`, with the audit entries made up to then.

        `current` holds the value of each field at `moment`; `previous` the older values
        that had already been replaced by then; `audit_ids` the entries up to `moment`.
        """
        rows = self._history.get(user_id, ())
        current: Dict[str, str] = dict(self._current[user_id])
        for row in reversed(rows):
            if row.event_time > moment:
                current[row.field_name] = row.old_value
        seen: List[AuditRow] = [row for row in rows if row.event_time <= moment]
        previous: Dict[str, Set[str]] = {field: set() for field in FIELDS}
        for row in seen:
            previous[row.field_name].update((row.old_value, row.new_value))
        for field in FIELDS:
            previous[field].discard(current[field])
        return {
            "user_id": user_id,
            "current": current,
            "previous": {field: sorted(values) for field, values in previous.items()},
            "audit_ids": [row.audit_id for row in seen],
        }

    def audit_times(self, user_id: str, moment: int) -> Tuple[Tuple[str, int], ...]:
        """(audit id, event time) entries of a subject up to `moment`."""
        return tuple((row.audit_id, row.event_time) for row in self._history.get(user_id, ()) if row.event_time <= moment)
