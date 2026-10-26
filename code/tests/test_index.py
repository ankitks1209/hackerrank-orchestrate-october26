"""Tests for ghostaudit.evidence.index (SPEC 3.1, T1-T3).

The synthetic manifest uses fictional ids. The real-dataset class checks the
acceptance counts against the participant files, with no media facts supplied.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Dict, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.config import MEDIA_SUFFIXES, Config
from ghostaudit.dataset import DatasetReader, Identity
from ghostaudit.evidence.index import MEDIA_PARSER, EvidenceIndex, build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import ManifestEntry, MediaFacts, ObsState
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

CAPTURED = "2026-01-02T00:00:00Z"
LATER = "2026-01-05T00:00:00Z"
LINE_TIME = "2026-01-01T00:00:00Z"
EMAIL = "ann.test@example.com"
OTHER_EMAIL = "bob.test@example.com"
HASH_64 = "a" * 64

HANDOVER_A = """- {t} | account_service | account_1 | USER_PROFILE | FOUND | {email}
- {t} | account_service | account_2 | USER_PROFILE | NOT_FOUND | no direct identifier
""".format(t=LINE_TIME, email=EMAIL)
HANDOVER_B = """- {t} | account_service | account_1 | USER_PROFILE | NOT_FOUND | {email}
- {t} | support_platform | support_9 | SUPPORT_MESSAGE | IDENTIFIABLE | {other}
""".format(t=LINE_TIME, email=EMAIL, other=OTHER_EMAIL)
NOT_EVIDENCE = "free text that no parser claims\n"
MEDIA_RECORD = {
    "resource_hint": "support_001",
    "category": "SUPPORT_ATTACHMENT",
    "emails": [EMAIL],
    "state_facts": {"record_shown": True},
}


def identity_index() -> IdentityIndex:
    ann = Identity("user_1", "Ann Test", EMAIL, "+15550000001", HASH_64, 0)
    return IdentityIndex.build([ann], [])


class SyntheticManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.manifest = tuple(
            self._write(root, order, name, body, captured)
            for order, (name, body, captured) in enumerate(
                (
                    ("a.txt", HANDOVER_A, CAPTURED),
                    ("b.txt", HANDOVER_B, CAPTURED),
                    ("c.png", "png bytes", LATER),
                )
            )
        )
        self.facts = {"evidence_c": MediaFacts("evidence_c", (MEDIA_RECORD,))}

    @staticmethod
    def _write(root: Path, order: int, name: str, body: str, captured: str) -> ManifestEntry:
        path = root / name
        path.write_text(body, encoding="utf-8")
        return ManifestEntry("evidence_" + name[0], path, "test", to_epoch(captured), order)

    def build(self, manifest: Tuple[ManifestEntry, ...] = (), facts: Dict = None) -> EvidenceIndex:
        facts = self.facts if facts is None else facts
        return build_index(manifest or self.manifest, identity_index(), facts, ())

    def test_every_file_is_claimed_once_in_manifest_order(self) -> None:
        index = self.build()
        self.assertEqual(
            dict(index.claimed_by),
            {"evidence_a": "handover_txt", "evidence_b": "handover_txt", "evidence_c": MEDIA_PARSER},
        )
        self.assertEqual(tuple(index.claimed_by), ("evidence_a", "evidence_b", "evidence_c"))

    def test_tie_on_entry_and_capture_time_follows_manifest_order(self) -> None:
        index = self.build()
        self.assertEqual([o.file_id for o in index.by_rid["account_1"]], ["evidence_a", "evidence_b"])
        self.assertEqual(index.by_rid["account_1"][-1].state, ObsState.ABSENT)

    def test_reversed_manifest_order_reverses_the_tie(self) -> None:
        reordered = tuple(
            ManifestEntry(e.file_id, e.path, e.origin, e.captured_at, order)
            for order, e in enumerate((self.manifest[1], self.manifest[0], self.manifest[2]))
        )
        index = self.build(reordered)
        self.assertEqual([o.file_id for o in index.by_rid["account_1"]], ["evidence_b", "evidence_a"])

    def test_later_entry_time_sorts_last_whatever_the_manifest_order(self) -> None:
        late = HANDOVER_A.replace(LINE_TIME, "2026-01-01T06:00:00Z")
        self.manifest[0].path.write_text(late, encoding="utf-8")
        rows = self.build().by_rid["account_1"]
        self.assertEqual([o.file_id for o in rows], ["evidence_b", "evidence_a"])

    def test_users_are_resolved_through_subject_keys(self) -> None:
        index = self.build()
        self.assertEqual(index.users_by_rid["account_1"], ("user_1",))
        self.assertEqual(index.users_by_rid["account_2"], ())
        self.assertEqual(index.users_by_rid["support_9"], ())
        self.assertEqual(index.users_by_rid["support_001"], ("user_1",))
        self.assertEqual(index.rids_by_user["user_1"], ("account_1", "support_001"))

    def test_ties_carry_the_earliest_moment_they_are_admissible(self) -> None:
        index = self.build()
        self.assertEqual(index.tied_since[("account_1", "user_1")], to_epoch(CAPTURED))
        self.assertEqual(index.tied_since[("support_001", "user_1")], to_epoch(LATER))
        self.assertTrue(index.tied_by("support_001", "user_1", to_epoch(LATER)))
        self.assertFalse(index.tied_by("support_001", "user_1", to_epoch(LATER) - 1))
        self.assertFalse(index.tied_by("support_9", "user_1", to_epoch(LATER)))

    def test_mentions_list_files_in_manifest_order(self) -> None:
        index = self.build()
        self.assertEqual(index.mentions["account_1"], ("evidence_a", "evidence_b"))
        self.assertEqual(index.mentions["support_9"], ("evidence_b",))
        self.assertEqual(index.mentions["support_001"], ("evidence_c",))

    def test_media_file_without_facts_is_a_note_not_an_observation(self) -> None:
        index = self.build(facts={})
        self.assertNotIn("support_001", index.by_rid)
        self.assertIn("evidence_c: no media facts", index.notes)
        self.assertEqual(index.claimed_by["evidence_c"], MEDIA_PARSER)

    def test_unclaimed_text_file_is_skipped_with_a_note(self) -> None:
        self.manifest[1].path.write_text(NOT_EVIDENCE, encoding="utf-8")
        index = self.build()
        self.assertNotIn("evidence_b", index.claimed_by)
        self.assertTrue(any(note.startswith("evidence_b skipped") for note in index.notes))
        self.assertIn("evidence_b", index.entries)
        self.assertEqual([o.file_id for o in index.by_rid["account_1"]], ["evidence_a"])

    def test_lookups_are_read_only(self) -> None:
        index = self.build()
        with self.assertRaises(TypeError):
            index.by_rid["account_9"] = ()  # type: ignore[index]
        with self.assertRaises(AttributeError):
            index.notes = ()  # type: ignore[misc]

    def test_build_is_repeatable(self) -> None:
        self.assertEqual(self.build().observations, self.build().observations)


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(Config().dataset_dir)
        cls.manifest = reader.manifest()
        identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(cls.manifest, identity, {}, classify_activity(reader.activity()))

    def test_every_text_file_is_claimed_by_one_parser(self) -> None:
        media = {e.file_id for e in self.manifest if e.path.suffix in MEDIA_SUFFIXES}
        text = {e.file_id for e in self.manifest} - media
        self.assertEqual((len(text), len(media)), (79, 15))
        claimed = self.index.claimed_by
        self.assertEqual({fid for fid, name in claimed.items() if name != MEDIA_PARSER}, text)
        self.assertEqual({fid for fid, name in claimed.items() if name == MEDIA_PARSER}, media)

    def test_decoy_search_document_has_no_subject(self) -> None:
        self.assertEqual(self.index.users_by_rid["search_8168"], ())

    def test_tombstone_resolves_to_its_subject(self) -> None:
        self.assertEqual(self.index.users_by_rid["tombstone_9178"], ("user_542",))
        self.assertIn("tombstone_9178", self.index.rids_by_user["user_542"])

    def test_scopes_and_pointers_are_indexed(self) -> None:
        self.assertTrue(self.index.scopes_by_file)
        self.assertTrue(self.index.pointers)
        for accounts in self.index.pointers.values():
            self.assertEqual(accounts, tuple(sorted(accounts)))


if __name__ == "__main__":
    unittest.main()
