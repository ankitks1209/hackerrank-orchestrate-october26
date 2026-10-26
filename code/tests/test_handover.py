"""Tests for ghostaudit.evidence.handover (SPEC F8 and the F6 result vocabulary)."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Dict, Tuple

from ghostaudit.config import REPO_ROOT
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence import REGISTRY
from ghostaudit.evidence.base import ParseError, select_parser
from ghostaudit.evidence.handover import HandoverParser
from ghostaudit.model import ManifestEntry, ObsState, Observation
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

SNAPSHOT = "2026-10-01T12:00:00Z"
ENTRY = ManifestEntry(
    "evidence_03",
    Path("evidence/records/customer_account_handover_20261001.txt"),
    "customer_account_service",
    to_epoch(SNAPSHOT),
    2,
)
# Real lines copied verbatim from evidence_03 (SPEC F8); the header is framing text.
FIXTURE = """CUSTOMER PLATFORM - SHIFT HANDOVER
Snapshot: 2026-10-01T12:00:00Z

Account and downstream checks completed during the shift:

- 2026-10-01T12:00:00Z | account_service | account_146 | USER_PROFILE | NOT_FOUND | e.lindberg18@yahoo.com
- 2026-10-01T12:00:00Z | analytics_platform | analytics_2034 | ANALYTICS_PROFILE | IDENTIFIABLE | novak.tomasz@icloud.com
- 2026-10-01T12:00:00Z | analytics_platform | analytics_6830 | ANALYTICS_PROFILE | ANONYMIZED | no direct identifier
- 2026-10-01T12:00:00Z | backup_service | backup_3870 | BACKUP_ARCHIVE | ACTIVE | y.tanaka32@gmail.com
- 2026-10-01T12:00:00Z | backup_service | backup_706 | BACKUP_ARCHIVE | BLOCKED | user_39
- 2026-10-01T12:00:00Z | integration_service | data_flow_2901 | DATA_FLOW | DISABLED | user_39
- 2026-10-01T12:00:00Z | integration_service | data_flow_9522 | DATA_FLOW | ACTIVE | novak.tomasz@icloud.com
- 2026-10-01T12:00:00Z | security_service | audit_record_2019 | SECURITY_AUDIT_LOG | FOUND | user_35
- 2026-10-01T12:00:00Z | support_platform | support_2667 | SUPPORT_MESSAGE | REDACTED | user_39
- 2026-10-01T12:00:00Z | support_platform | support_4218 | SUPPORT_ATTACHMENT | FOUND | noor-khalil@proton.me
- 2026-10-01T12:00:00Z | support_platform | support_864 | SUPPORT_MESSAGE | IDENTIFIABLE | novak.tomasz@icloud.com
- 2026-10-01T12:00:00Z | support_platform | support_4887 | SUPPORT_MESSAGE | IDENTIFIABLE | CHOI.JIHOON94@GMAIL.COM
"""
FIXTURE_BYTES = FIXTURE.encode("utf-8")
HANDOVER_LINE_COUNT = 12
REAL_HEAD_BYTES = 512  # covers the header and the first handover line of evidence_03


def _by_resource(observations: Tuple[Observation, ...]) -> Dict[str, Observation]:
    return {obs.resource_id: obs for obs in observations}


class DetectTests(unittest.TestCase):
    def test_claims_txt_with_handover_line(self) -> None:
        self.assertTrue(HandoverParser().detect(ENTRY, FIXTURE_BYTES))

    def test_ignores_other_suffixes(self) -> None:
        log_entry = ManifestEntry("evidence_09", Path("evidence/logs/a.log"), "o", 0, 0)
        self.assertFalse(HandoverParser().detect(log_entry, FIXTURE_BYTES))

    def test_rejects_txt_without_handover_line(self) -> None:
        self.assertFalse(HandoverParser().detect(ENTRY, b"CUSTOMER PLATFORM\nSnapshot: x\n"))


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = HandoverParser().parse(ENTRY, FIXTURE_BYTES)
        self.by_resource = _by_resource(self.output.observations)

    def test_one_observation_per_handover_line_and_no_notes(self) -> None:
        self.assertEqual(len(self.output.observations), HANDOVER_LINE_COUNT)
        self.assertEqual(self.output.notes, ())
        self.assertEqual(self.output.scopes, ())

    def test_category_and_state_follow_result_vocabulary(self) -> None:
        expected = {
            "account_146": ("USER_PROFILE", ObsState.ABSENT),
            "analytics_2034": ("ANALYTICS_PROFILE", ObsState.EXPOSED),
            "analytics_6830": ("ANALYTICS_PROFILE", ObsState.ANONYMIZED),
            "backup_3870": ("BACKUP_ARCHIVE", ObsState.ACTIVE),
            "backup_706": ("BACKUP_ARCHIVE", ObsState.BLOCKED),
            "data_flow_2901": ("DATA_FLOW", ObsState.DISABLED),
            "data_flow_9522": ("DATA_FLOW", ObsState.ACTIVE),
            "audit_record_2019": ("SECURITY_AUDIT_LOG", ObsState.PRESENT),
            "support_2667": ("SUPPORT_MESSAGE", ObsState.REDACTED),
            "support_4218": ("SUPPORT_ATTACHMENT", ObsState.PRESENT),
            "support_864": ("SUPPORT_MESSAGE", ObsState.EXPOSED),
        }
        for resource_id, (category, state) in expected.items():
            with self.subTest(resource_id=resource_id):
                self.assertEqual(self.by_resource[resource_id].category, category)
                self.assertEqual(self.by_resource[resource_id].state, state)

    def test_subject_keys_are_normalized_or_empty(self) -> None:
        self.assertEqual(
            self.by_resource["account_146"].subject_keys, frozenset({"e:e.lindberg18@yahoo.com"})
        )
        self.assertEqual(
            self.by_resource["support_4887"].subject_keys, frozenset({"e:choi.jihoon94@gmail.com"})
        )
        self.assertEqual(self.by_resource["backup_706"].subject_keys, frozenset({"u:user_39"}))
        self.assertEqual(self.by_resource["analytics_6830"].subject_keys, frozenset())

    def test_times_locators_and_manifest_fields(self) -> None:
        obs = self.by_resource["support_4218"]
        self.assertEqual(obs.entry_time, to_epoch(SNAPSHOT))
        self.assertEqual(obs.captured_at, ENTRY.captured_at)
        self.assertEqual(obs.file_id, "evidence_03")
        self.assertEqual(obs.system_id, "support_platform")
        self.assertEqual(obs.locator, "evidence_03:L15")

    def test_unknown_result_is_skipped_with_note(self) -> None:
        extra = "- %s | search_service | search_1 | SEARCH_INDEX_ENTRY | MAYBE | user_39" % SNAPSHOT
        output = HandoverParser().parse(ENTRY, (FIXTURE + extra + "\n").encode("utf-8"))
        self.assertEqual(len(output.observations), HANDOVER_LINE_COUNT)
        self.assertEqual(len(output.notes), 1)
        self.assertIn("evidence_03:L18", output.notes[0])
        self.assertIn("unknown result 'MAYBE'", output.notes[0])

    def test_bad_timestamp_is_skipped_with_note(self) -> None:
        extra = "- not-a-time | search_service | search_1 | SEARCH_INDEX_ENTRY | FOUND | user_39"
        output = HandoverParser().parse(ENTRY, (FIXTURE + extra + "\n").encode("utf-8"))
        self.assertEqual(len(output.observations), HANDOVER_LINE_COUNT)
        self.assertIn("evidence_03:L18 skipped", output.notes[0])

    def test_non_utf8_content_raises_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            HandoverParser().parse(ENTRY, b"\xff\xfe- 2026-10-01T12:00:00Z | a")


class RegistryTests(unittest.TestCase):
    def test_registry_claims_fixture_with_handover_parser(self) -> None:
        parser = select_parser(ENTRY, FIXTURE_BYTES[:REAL_HEAD_BYTES], REGISTRY)
        self.assertIsInstance(parser, HandoverParser)


@needs_dataset
class Evidence03AcceptanceTests(unittest.TestCase):
    """Checks the real evidence_03 file through the manifest and DatasetReader (SPEC F8)."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        cls.entry = next(e for e in reader.manifest() if e.file_id == "evidence_03")
        cls.data = cls.entry.path.read_bytes()

    def test_real_file_is_claimed_from_its_head(self) -> None:
        parser = select_parser(self.entry, self.data[:REAL_HEAD_BYTES], REGISTRY)
        self.assertIsInstance(parser, HandoverParser)

    def test_real_file_yields_every_handover_line(self) -> None:
        output = HandoverParser().parse(self.entry, self.data)
        self.assertEqual(len(output.observations), 41)
        self.assertEqual(output.notes, ())

    def test_acceptance_states(self) -> None:
        by_resource = _by_resource(HandoverParser().parse(self.entry, self.data).observations)
        self.assertEqual(by_resource["support_4218"].category, "SUPPORT_ATTACHMENT")
        self.assertEqual(by_resource["support_4218"].state, ObsState.PRESENT)
        for resource_id in ("analytics_2034", "support_864"):
            with self.subTest(resource_id=resource_id):
                self.assertEqual(by_resource[resource_id].state, ObsState.EXPOSED)
        for resource_id in ("backup_3870", "data_flow_9522"):
            with self.subTest(resource_id=resource_id):
                self.assertEqual(by_resource[resource_id].state, ObsState.ACTIVE)


if __name__ == "__main__":
    unittest.main()
