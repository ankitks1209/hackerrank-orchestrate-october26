"""Tests for ghostaudit.keys (SPEC I1, I2, 3.1)."""
from __future__ import annotations

import hashlib
import unittest

from ghostaudit import keys

SEAL = "sha256:" + "0" * 61 + "799"
EMAIL_HASH = hashlib.sha256(b"sipho.mokoena@gmail.com").hexdigest()


class KeyFunctionTests(unittest.TestCase):
    def test_email_key_is_stripped_and_lowercased(self) -> None:
        self.assertEqual(keys.email_key("SIPHO.MOKOENA@GMAIL.COM"), "e:sipho.mokoena@gmail.com")
        self.assertEqual(keys.email_key("  a@b.co \n"), "e:a@b.co")

    def test_phone_key_keeps_digits_only(self) -> None:
        self.assertEqual(keys.phone_key("+81 90 6156 0005"), "p:819061560005")
        self.assertEqual(keys.phone_key("+1 (202) 555-0103"), "p:12025550103")

    def test_phone_key_needs_eight_digits(self) -> None:
        self.assertIsNone(keys.phone_key("+1234567"))
        self.assertEqual(keys.phone_key("12345678"), "p:12345678")

    def test_hash_key_accepts_only_bare_64_hex(self) -> None:
        self.assertEqual(keys.hash_key(EMAIL_HASH.upper()), "h:" + EMAIL_HASH)
        self.assertIsNone(keys.hash_key(EMAIL_HASH[:-1]))
        self.assertIsNone(keys.hash_key("z" * 64))

    def test_integrity_seal_is_not_a_hash(self) -> None:
        self.assertIsNone(keys.hash_key(SEAL))
        self.assertEqual(keys.keys_from_record({"integrity_seal": SEAL}), frozenset())

    def test_user_key(self) -> None:
        self.assertEqual(keys.user_key("user_35"), "u:user_35")
        self.assertIsNone(keys.user_key("user_"))
        self.assertIsNone(keys.user_key("account_005"))


class KeysFromRecordTests(unittest.TestCase):
    def test_each_shape_gets_its_key(self) -> None:
        record = {
            "email": "Sipho.Mokoena@Gmail.com",
            "phone": "+81 90 6156 0005",
            "email_hash": EMAIL_HASH,
            "user_id": "user_35",
        }
        self.assertEqual(
            keys.keys_from_record(record),
            frozenset(
                {
                    "e:sipho.mokoena@gmail.com",
                    "p:819061560005",
                    "h:" + EMAIL_HASH,
                    "u:user_35",
                }
            ),
        )

    def test_same_raw_value_gives_same_key_as_the_functions(self) -> None:
        self.assertEqual(
            keys.keys_from_record({"x": "SIPHO.MOKOENA@GMAIL.COM"}),
            {keys.email_key("SIPHO.MOKOENA@GMAIL.COM")},
        )
        self.assertEqual(
            keys.keys_from_record({"x": "+81 90 6156 0005"}), {keys.phone_key("+81 90 6156 0005")}
        )
        self.assertEqual(keys.keys_from_record({"x": EMAIL_HASH}), {keys.hash_key(EMAIL_HASH)})
        self.assertEqual(keys.keys_from_record({"x": "user_7"}), {keys.user_key("user_7")})

    def test_emails_are_extracted_from_free_text(self) -> None:
        text = 'Contact "Ann.Lee@Mail.com", cc bob@x.org. Thanks'
        self.assertEqual(
            keys.keys_from_record({"message_text": text}), {"e:ann.lee@mail.com", "e:bob@x.org"}
        )

    def test_lookalike_email_is_a_different_key(self) -> None:
        real = keys.keys_from_record({"e": "g.silva76@gmail.com"})
        lookalike = keys.keys_from_record({"e": "see g.silva76.jr@gmail.com"})
        self.assertEqual(real, {"e:g.silva76@gmail.com"})
        self.assertEqual(lookalike, {"e:g.silva76.jr@gmail.com"})
        self.assertFalse(real & lookalike)

    def test_names_dates_nulls_and_numbers_are_not_keys(self) -> None:
        record = {
            "name": "Sipho Mokoena",
            "updated_at": "2026-05-28T04:03:00Z",
            "date": "2026-05-28",
            "phone": None,
            "email": "null",
            "amount": 12345678,
            "resource_id": "account_005",
        }
        self.assertEqual(keys.keys_from_record(record), frozenset())

    def test_nested_mappings_and_lists_are_walked(self) -> None:
        record = {"document": {"email": "A@B.com", "refs": ["user_3", {"p": "+44 7700 900016"}]}}
        self.assertEqual(
            keys.keys_from_record(record), {"e:a@b.com", "u:user_3", "p:447700900016"}
        )

    def test_result_is_a_frozenset(self) -> None:
        self.assertIsInstance(keys.keys_from_record({}), frozenset)


if __name__ == "__main__":
    unittest.main()
