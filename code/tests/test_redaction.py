"""Tests for the at-rest redaction of stored media replies (DECISIONS D25).

Everything is synthetic except the last class, which scans the committed response cache for
the emails, phones and names of the dataset's identity snapshot (read only to be matched).
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

from ghostaudit import keys
from ghostaudit.activity import classify_row
from ghostaudit.config import Config
from ghostaudit.dataset import ActivityRow, DatasetReader, Identity, ManifestEntry
from ghostaudit.evidence.media import map_facts
from ghostaudit.identity import IdentityIndex
from ghostaudit.llm.cache import REDACTED_FIELD, CachingClient, DiskCache, Redactor, request_key
from ghostaudit.llm.client import LLMRequest, LLMResponse
from ghostaudit.llm.media_extract import (
    PROMPT_VERSION,
    REDACTION_NOTE,
    parse_records,
    redact_reply,
)
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import MediaFacts
from tests.dataset_guard import needs_dataset
from tools import redact_cache

EMAIL = "Sasha.Test@Example.com"
PHONE = "+44 7700 900123"
NAME = "Sasha Test"
OTHER_EMAIL = "someone.else@example.org"
MODEL = "claude-opus-5-5"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(**fields: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "display_id": "", "resource_hint": "", "system_hint": "", "category": "", "emails": [],
        "phones": [], "user_refs": [], "names": [], "dates": [], "state_facts": {},
    }
    base.update(fields)
    return base


def reply(*records: Dict[str, Any]) -> str:
    return json.dumps({"records": list(records)})


PROFILE = record(display_id="account_7001", category="USER_PROFILE", emails=[EMAIL], phones=[PHONE],
                 user_refs=["user_5"], names=[NAME], state_facts={"record_shown": True})
SUPPORT = record(display_id="support_7002", category="SUPPORT_MESSAGE", names=[NAME],
                 state_facts={"record_shown": True})
RAW = reply(PROFILE, SUPPORT, record(display_id="ORD-1", emails=["not an address", OTHER_EMAIL]))


class KeyTests(unittest.TestCase):
    def test_redacted_forms_hash_the_lower_cased_email_and_the_phone_digits(self) -> None:
        self.assertEqual(keys.redacted_email("  " + EMAIL + " "), "sha256:" + sha(EMAIL.lower()))
        self.assertEqual(keys.redacted_phone(PHONE), "sha256:" + sha("447700900123"))

    def test_text_without_an_identifier_has_no_redacted_form_and_a_digest_is_kept(self) -> None:
        digest = "sha256:" + sha("x")
        self.assertIsNone(keys.redacted_email("no address here"))
        self.assertIsNone(keys.redacted_phone("12/03/2026"))
        self.assertEqual((keys.redacted_email(digest), keys.redacted_phone(digest)), (digest, digest))

    def test_digest_keys_equal_the_identity_side_keys(self) -> None:
        self.assertEqual(keys.redacted_email_key(keys.redacted_email(EMAIL)), keys.hash_key(sha(EMAIL.lower())))
        self.assertEqual(keys.redacted_phone_key(keys.redacted_phone(PHONE)), keys.phone_hash_key(PHONE))
        self.assertIsNone(keys.redacted_email_key(EMAIL))
        self.assertIsNone(keys.phone_hash_key("12345"))

    def test_identity_holds_the_hash_key_of_every_phone_and_email(self) -> None:
        index = IdentityIndex.build([Identity("user_5", NAME, EMAIL, PHONE, sha(EMAIL.lower()), 0)], [])
        self.assertIn(keys.phone_hash_key(PHONE), index.keys_for("user_5"))
        self.assertIn(keys.hash_key(sha(EMAIL.lower())), index.keys_for("user_5"))


class RedactReplyTests(unittest.TestCase):
    def test_emails_and_phones_become_digests_and_names_go(self) -> None:
        records = parse_records(redact_reply(RAW))[0]
        self.assertEqual(records[0]["emails"], ["sha256:" + sha(EMAIL.lower())])
        self.assertEqual(records[0]["phones"], ["sha256:" + sha("447700900123")])
        self.assertEqual([item["names"] for item in records], [[], [], []])
        self.assertEqual(records[2]["emails"], ["sha256:" + sha(OTHER_EMAIL)])  # the non-address entry is dropped
        self.assertEqual(records[0]["user_refs"], ["user_5"])

    def test_no_identifier_text_is_left(self) -> None:
        text = redact_reply(RAW)
        for secret in (EMAIL, EMAIL.lower(), OTHER_EMAIL, PHONE, "7700 900123", NAME, "@"):
            self.assertNotIn(secret, text)

    def test_redacting_twice_gives_the_same_text(self) -> None:
        once = redact_reply(RAW)
        self.assertEqual(redact_reply(once), once)

    def test_facts_derived_from_the_names_survive(self) -> None:
        """A support message that lists only a name shows PII; the name is gone, the fact stays."""
        before = parse_records(RAW)[0][1]["state_facts"]
        after = parse_records(redact_reply(RAW))[0][1]["state_facts"]
        self.assertEqual(before, after)
        self.assertTrue(after["pii_fields_shown"])

    def test_a_reply_that_is_not_a_valid_extraction_is_stored_empty(self) -> None:
        for text in ("not json", '{"records": 3}', json.dumps({"records": [{"emails": [EMAIL]}]})):
            with self.subTest(text=text[:20]):
                self.assertEqual(redact_reply(text), "")


class MappingTests(unittest.TestCase):
    """A redacted record maps to the same resources and subjects as the plain one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.identity = IdentityIndex.build(
            [Identity("user_5", NAME, EMAIL, PHONE, sha(EMAIL.lower()), 0),
             Identity("user_6", "Other Person", OTHER_EMAIL, "+44 7700 900999", sha(OTHER_EMAIL), 0)], [])
        cls.entry = ManifestEntry("evidence_x", Path("x.png"), "console", 100, 0)

    def facts(self, text: str) -> MediaFacts:
        return MediaFacts("evidence_x", parse_records(text)[0])

    def link(self, alias: str) -> Any:
        details = "Data catalog linked support_7002 (%s) to %s and user_5." % (alias, EMAIL)
        row = ActivityRow("activity_1", 0, "LINK_RESOURCE_IDENTITY", "data_catalog", "support_platform",
                          "support_7002", "SUCCESS", details)
        return classify_row(row)

    def mapped(self, text: str, links: Any = ()) -> List[Any]:
        output = map_facts(self.entry, self.facts(text), links)
        return [(obs.system_id, obs.resource_id, obs.state, self.identity.users_for(obs.subject_keys))
                for obs in output.observations]

    def test_literal_id_with_a_shown_email_or_phone(self) -> None:
        plain = self.mapped(RAW)
        self.assertEqual(plain[0][:2], ("account_service", "account_7001"))
        self.assertEqual(plain[0][3], ("user_5",))
        self.assertEqual(self.mapped(redact_reply(RAW)), plain)

    def test_a_phone_alone_resolves_through_its_digest(self) -> None:
        text = reply(record(display_id="account_7001", category="USER_PROFILE", phones=[PHONE],
                            state_facts={"record_shown": True}))
        self.assertEqual(self.mapped(text)[0][3], ("user_5",))
        self.assertEqual(self.mapped(redact_reply(text)), self.mapped(text))

    def test_link_row_join_accepts_a_hashed_email_without_a_contradiction(self) -> None:
        text = reply(record(display_id="CS-1", resource_hint="support_7002", category="SUPPORT_MESSAGE",
                            emails=[EMAIL], state_facts={"record_shown": True}))
        links = (self.link("CS-1"),)
        plain, hashed = self.mapped(text, links), self.mapped(redact_reply(text), links)
        self.assertEqual(hashed, plain)
        notes = map_facts(self.entry, self.facts(redact_reply(text)), links).notes
        self.assertFalse([note for note in notes if "contradicts" in note])

    def test_a_hashed_email_of_another_person_still_resolves_to_that_person(self) -> None:
        text = reply(record(display_id="account_7009", category="USER_PROFILE", emails=[OTHER_EMAIL],
                            state_facts={"record_shown": True}))
        self.assertEqual(self.mapped(redact_reply(text))[0][3], ("user_6",))


def live_request() -> LLMRequest:
    return LLMRequest(model=MODEL, system="s", messages=(("user", "u"),), max_tokens=10,
                      prompt_version=PROMPT_VERSION)


class Inner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self.text, input_tokens=1, output_tokens=1, model=MODEL, cached=False)


class CachingTests(unittest.TestCase):
    def client(self, directory: str, inner: Inner, mode: str = "live") -> CachingClient:
        redactors = {PROMPT_VERSION: Redactor(REDACTION_NOTE, redact_reply)}
        return CachingClient(inner, DiskCache(Path(directory)), UsageMeter(Config().prices), mode, redactors)

    def test_live_write_is_redacted_and_marked_but_the_caller_sees_the_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            returned = self.client(tmp, Inner(RAW)).complete(live_request())
            stored = json.loads((Path(tmp) / (request_key(live_request()) + ".json")).read_text(encoding="utf-8"))
            replayed = self.client(tmp, Inner("unused"), "cache").complete(live_request())
        self.assertEqual(returned.text, RAW)
        self.assertEqual(stored[REDACTED_FIELD], REDACTION_NOTE)
        self.assertEqual(stored["text"], redact_reply(RAW))
        self.assertNotIn(EMAIL.lower(), stored["text"].lower())
        self.assertEqual(replayed.text, stored["text"])

    def test_other_prompts_are_stored_as_they_are(self) -> None:
        request = LLMRequest(model=MODEL, system="s", messages=(("user", "u"),), max_tokens=10,
                             prompt_version="intent.v1")
        with tempfile.TemporaryDirectory() as tmp:
            self.client(tmp, Inner(RAW)).complete(request)
            stored = json.loads((Path(tmp) / (request_key(request) + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(stored["text"], RAW)
        self.assertNotIn(REDACTED_FIELD, stored)


class RedactCacheToolTests(unittest.TestCase):
    def write(self, directory: Path, name: str, text: str, **extra: Any) -> None:
        entry = {"text": text, "model": MODEL, "input_tokens": 1, "output_tokens": 1,
                 "cache_creation_tokens": 0, "cache_read_tokens": 0, "stop_reason": "end_turn"}
        entry.update(extra)
        (directory / name).write_text(json.dumps(entry), encoding="utf-8")

    def run_tool(self, directory: Path, *args: str) -> int:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return redact_cache.main(["--cache-dir", str(directory)] + list(args))

    def test_media_entries_are_redacted_in_place_and_other_entries_are_left(self) -> None:
        intent = json.dumps({"deletion": True, "reason": "asked to delete"})
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, "media.json", RAW)
            self.write(directory, "intent.json", intent)
            self.assertEqual(self.run_tool(directory, "--check"), redact_cache.EXIT_UNREDACTED)
            self.assertEqual(self.run_tool(directory), redact_cache.EXIT_OK)
            media = json.loads((directory / "media.json").read_text(encoding="utf-8"))
            untouched = json.loads((directory / "intent.json").read_text(encoding="utf-8"))
            before = (directory / "media.json").read_bytes()
            self.assertEqual(self.run_tool(directory), redact_cache.EXIT_OK)
            self.assertEqual((directory / "media.json").read_bytes(), before)  # idempotent
            self.assertEqual(self.run_tool(directory, "--check"), redact_cache.EXIT_OK)
        self.assertEqual(media["text"], redact_reply(RAW))
        self.assertEqual(media[REDACTED_FIELD], REDACTION_NOTE)
        self.assertEqual((untouched["text"], REDACTED_FIELD in untouched), (intent, False))

    def test_counts_name_the_identifiers_removed(self) -> None:
        counts = redact_cache.count_identifiers(RAW)
        self.assertEqual((counts["emails"], counts["phones"], counts["names"]), (3, 1, 2))


@needs_dataset
class CommittedCacheTests(unittest.TestCase):
    """The shipped response cache holds no email, phone or name of the identity snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.identities = DatasetReader(Config().dataset_dir).identities()
        cls.entries = {path.name: path.read_text(encoding="utf-8") for path in Config().cache_dir.glob("*.json")}

    def media_entries(self) -> Dict[str, str]:
        return {name: text for name, text in self.entries.items() if '"records"' in json.loads(text)["text"]}

    def test_every_media_entry_is_marked_redacted(self) -> None:
        media = self.media_entries()
        self.assertEqual(len(media), 15)
        for name, text in media.items():
            self.assertEqual(json.loads(text)[REDACTED_FIELD], REDACTION_NOTE, name)

    def test_no_identity_email_phone_or_name_is_in_a_media_entry(self) -> None:
        digits = {"".join(ch for ch in person.phone if ch.isdigit()) for person in self.identities}
        for name, text in self.media_entries().items():
            lowered = text.lower()
            for person in self.identities:
                self.assertNotIn(person.email.lower(), lowered, name)
                self.assertNotIn(person.name.lower(), lowered, name)
            self.assertNotIn("@", json.loads(text)["text"], name)
            plain = "".join(ch for ch in re.sub(r"sha256:[0-9a-f]{64}", "", text) if ch.isdigit())
            for number in digits:
                self.assertNotIn(number, plain, name)


if __name__ == "__main__":
    unittest.main()
