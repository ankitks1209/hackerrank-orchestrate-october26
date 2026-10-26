"""Tests for ghostaudit.identity (SPEC I1-I4).

Unit cases use synthetic fixtures. Acceptance cases read the participant dataset and
cite only sample cases (case_12) or request emails as a group.
"""
from __future__ import annotations

import hashlib
import unittest
from typing import Dict, List, Tuple

from ghostaudit import config, keys
from ghostaudit.dataset import AuditRow, DatasetError, DatasetReader, Identity
from ghostaudit.identity import IdentityIndex
from tests.dataset_guard import needs_dataset

DATASET = config.Config().dataset_dir


def sha(email: str) -> str:
    return hashlib.sha256(email.lower().encode("utf-8")).hexdigest()


def identity(user_id: str, name: str, email: str, phone: str) -> Identity:
    return Identity(user_id, name, email, phone, sha(email), 0)


def audit(audit_id: str, user_id: str, field: str, old: str, new: str) -> AuditRow:
    return AuditRow(audit_id, user_id, 0, field, old, new)


def email_chain(user_id: str, start: int, addresses: Tuple[str, ...]) -> List[AuditRow]:
    rows = []
    for offset, (old, new) in enumerate(zip(addresses, addresses[1:])):
        rows.append(audit("a%d" % (start + 2 * offset), user_id, "email", old, new))
        rows.append(audit("a%d" % (start + 2 * offset + 1), user_id, "email_hash", sha(old), sha(new)))
    return rows


CHAIN = ("old@zoho.com", "mid@zoho.com", "now@zoho.com")
USERS = (
    identity("user_1", "Mateo Rios", "now@zoho.com", "+34 612 847 593"),
    identity("user_2", "Mateo Rios", "other@outlook.com", "+34 720 474 294"),
)
HISTORY = email_chain("user_1", 1, CHAIN) + [
    audit("a9", "user_1", "phone", "+34 600 111 222", "+34 612 847 593"),
]


def build() -> IdentityIndex:
    return IdentityIndex.build(USERS, HISTORY)


class ResolveTests(unittest.TestCase):
    def test_every_email_of_a_chain_resolves_to_the_same_user(self) -> None:
        index = build()
        for address in CHAIN:
            self.assertEqual(index.resolve(address), "user_1")

    def test_resolution_ignores_case_and_padding(self) -> None:
        self.assertEqual(build().resolve("  OLD@Zoho.COM "), "user_1")

    def test_unknown_and_lookalike_emails_do_not_resolve(self) -> None:
        index = build()
        for address in ("old@zoho.co", "old.jr@zoho.com", "ld@zoho.com", "other@outlook.com.au"):
            self.assertIsNone(index.resolve(address), address)

    def test_same_name_users_stay_distinct(self) -> None:
        index = build()
        self.assertEqual(index.resolve("other@outlook.com"), "user_2")
        self.assertEqual(index.resolve("now@zoho.com"), "user_1")
        self.assertFalse(index.keys_for("user_1") & index.keys_for("user_2"))


class KeysTests(unittest.TestCase):
    def test_keys_cover_emails_hashes_phones_and_user_reference(self) -> None:
        found = build().keys_for("user_1")
        for address in CHAIN:
            self.assertIn("e:" + address, found)
            self.assertIn("h:" + sha(address), found)
        self.assertIn("p:34612847593", found)
        self.assertIn("p:34600111222", found)
        self.assertIn("u:user_1", found)

    def test_logged_hash_without_a_matching_email_is_kept(self) -> None:
        stray = hashlib.sha256(b"unknown-address").hexdigest()
        history = [audit("a1", "user_1", "email_hash", stray, sha("now@zoho.com"))]
        index = IdentityIndex.build(USERS, history)
        self.assertIn("h:" + stray, index.keys_for("user_1"))
        self.assertEqual(index.users_for(["h:" + stray]), ("user_1",))

    def test_names_are_not_keys(self) -> None:
        self.assertFalse([key for key in build().keys_for("user_1") if "rios" in key.lower()])

    def test_users_for_returns_sorted_unique_owners(self) -> None:
        index = build()
        query = [
            "e:other@outlook.com",
            "h:" + sha("old@zoho.com"),
            "e:now@zoho.com",
            "e:nobody@zoho.com",
        ]
        self.assertEqual(index.users_for(query), ("user_1", "user_2"))
        self.assertEqual(index.users_for([]), ())

    def test_shared_key_raises_dataset_error(self) -> None:
        twin = identity("user_3", "Twin", "twin@zoho.com", "+34 612 847 593")
        with self.assertRaises(DatasetError):
            IdentityIndex.build(USERS + (twin,), HISTORY)

    def test_audit_row_for_unknown_user_raises_dataset_error(self) -> None:
        with self.assertRaises(DatasetError):
            IdentityIndex.build(USERS, [audit("a1", "user_9", "phone", "+1 202 555 0100", "+1 202 555 0101")])


@needs_dataset
class DatasetAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(DATASET)
        cls.identities = reader.identities()
        cls.audit_rows = reader.audit_log()
        cls.requests = reader.requests()
        cls.index = IdentityIndex.build(cls.identities, cls.audit_rows)

    def test_every_request_email_resolves(self) -> None:
        current = {item.email for item in self.identities}
        counts: Dict[str, int] = {"current": 0, "historical": 0, "uppercase": 0}
        evaluation = [request for request in self.requests if not request.is_sample]
        for request in self.requests:
            self.assertIsNotNone(self.index.resolve(request.email), request.case_id)
        for request in evaluation:
            counts["current" if request.email.lower() in current else "historical"] += 1
            counts["uppercase"] += request.email != request.email.lower()
        self.assertEqual(len(evaluation), 518)
        self.assertEqual(counts, {"current": 418, "historical": 100, "uppercase": 20})

    def test_multi_hop_email_chains_resolve_from_every_address(self) -> None:
        emails: Dict[str, set] = {}
        for item in self.identities:
            emails.setdefault(item.user_id, set()).add(item.email)
        for row in self.audit_rows:
            if row.field_name == "email":
                emails[row.user_id].update((row.old_value, row.new_value))
        chains = {user_id: found for user_id, found in emails.items() if len(found) >= 3}
        self.assertTrue(chains)
        for user_id, found in chains.items():
            for address in found:
                self.assertEqual(self.index.resolve(address), user_id)

    def test_email_hash_maps_to_the_subject_of_sample_case_12(self) -> None:
        case = next(request for request in self.requests if request.case_id == "case_12")
        owner = self.index.resolve(case.email)
        self.assertEqual(self.index.users_for(["h:" + sha("minjun.kim90@gmail.com")]), (owner,))

    def test_decoy_emails_do_not_resolve(self) -> None:
        for address in (
            "smartinez6461.jr@gmail.com",
            "g.silva76.jr@gmail.com",
            "nadia.popescu@yahoo.com",
        ):
            self.assertIsNone(self.index.resolve(address), address)

    def test_same_name_users_resolve_apart(self) -> None:
        by_name: Dict[str, List[str]] = {}
        for item in self.identities:
            by_name.setdefault(item.name, []).append(item.user_id)
        twins = [users for users in by_name.values() if len(users) > 1]
        self.assertTrue(twins)
        for users in twins:
            for user_id in users:
                owner = self.index.resolve(next(i.email for i in self.identities if i.user_id == user_id))
                self.assertEqual(owner, user_id)

    def test_keys_for_matches_keys_from_record_over_the_same_raw_values(self) -> None:
        history: Dict[str, List[AuditRow]] = {}
        for row in self.audit_rows:
            history.setdefault(row.user_id, []).append(row)
        for item in self.identities:
            raw = [item.user_id, item.email, item.email_hash, item.phone]
            for row in history.get(item.user_id, []):
                raw.extend((row.old_value, row.new_value))
            emails = [value for value in raw if "@" in value]
            raw.extend(sha(address) for address in emails)
            phones = [item.phone] + [value for row in history.get(item.user_id, []) if row.field_name == "phone"
                                     for value in (row.old_value, row.new_value)]
            digests = {keys.phone_hash_key(phone) for phone in phones} - {None}  # the extra keys of D25
            self.assertEqual(self.index.keys_for(item.user_id), keys.keys_from_record(raw) | digests, item.user_id)


if __name__ == "__main__":
    unittest.main()
