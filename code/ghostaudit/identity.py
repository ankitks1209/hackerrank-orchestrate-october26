"""Resolve request emails to subjects and give each subject its match keys.

Implements SPEC I1-I4. A subject's keys are its user reference, every current
and historical email, the sha256 of each email, every logged email_hash,
every current and historical phone, and the sha256 of each phone's digits (the key of a
phone that an at-rest redaction left only as a digest). Keys come only from `ghostaudit.keys`.
Names are never keys, so same-name users stay distinct (I4).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from ghostaudit import keys
from ghostaudit.dataset import AuditRow, DatasetError, Identity

FIELD_EMAIL = "email"
FIELD_EMAIL_HASH = "email_hash"
FIELD_PHONE = "phone"


def _subject_keys(identity: Identity, history: Iterable[AuditRow]) -> FrozenSet[str]:
    """Every key of one subject from its snapshot row and its audit rows (SPEC I2)."""
    emails = {identity.email}
    hashes = [identity.email_hash]
    phones = [identity.phone]
    for row in history:
        if row.field_name == FIELD_EMAIL:
            emails.update((row.old_value, row.new_value))
        elif row.field_name == FIELD_EMAIL_HASH:
            hashes.extend((row.old_value, row.new_value))
        elif row.field_name == FIELD_PHONE:
            phones.extend((row.old_value, row.new_value))
    found: Set[Optional[str]] = {keys.user_key(identity.user_id)}
    for email in emails:
        found.add(keys.email_key(email))
        found.add(keys.hash_key(keys.email_digest(email)))
    found.update(keys.hash_key(value) for value in hashes)
    found.update(keys.phone_key(value) for value in phones)
    found.update(keys.phone_hash_key(value) for value in phones)
    return frozenset(key for key in found if key is not None)


class IdentityIndex:
    """Email-to-subject resolution and the key set of every subject."""

    def __init__(self, subject_keys: Dict[str, FrozenSet[str]]) -> None:
        owners: Dict[str, List[str]] = defaultdict(list)
        for user_id in sorted(subject_keys):
            for key in subject_keys[user_id]:
                owners[key].append(user_id)
        shared = sorted(key for key, users in owners.items() if len(users) > 1)
        if shared:
            raise DatasetError("keys shared by several users: %s" % ", ".join(shared))
        self._keys = dict(subject_keys)
        self._owner = {key: users[0] for key, users in owners.items()}

    @classmethod
    def build(
        cls, identities: Iterable[Identity], audit_log: Iterable[AuditRow]
    ) -> "IdentityIndex":
        """Index the snapshot and its history; raise DatasetError on a shared key (SPEC I4)."""
        snapshot = tuple(identities)
        history: Dict[str, List[AuditRow]] = defaultdict(list)
        for row in audit_log:
            history[row.user_id].append(row)
        unknown = sorted(set(history) - {identity.user_id for identity in snapshot})
        if unknown:
            raise DatasetError("audit log names users without an identity row: %s" % unknown)
        subject_keys = {
            identity.user_id: _subject_keys(identity, history[identity.user_id])
            for identity in snapshot
        }
        return cls(subject_keys)

    def resolve(self, email: str) -> Optional[str]:
        """The user whose current or historical email is `email`, else None (SPEC I1, I3)."""
        return self._owner.get(keys.email_key(email))

    def keys_for(self, user_id: str) -> FrozenSet[str]:
        """All match keys of a subject (SPEC I2)."""
        return self._keys[user_id]

    def users_for(self, subject_keys: Iterable[str]) -> Tuple[str, ...]:
        """Sorted users owning any of the given keys."""
        return tuple(sorted({self._owner[key] for key in subject_keys if key in self._owner}))
