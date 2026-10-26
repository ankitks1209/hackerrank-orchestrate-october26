"""Tests for ghostaudit.evidence.records (SPEC 3.1, F4-F7).

Fixtures are shaped like the real JSON evidence files; values are synthetic
except in DatasetAcceptanceTests, which parses the real records files.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

from ghostaudit import config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.base import ParseError, ParseOutput
from ghostaudit.evidence.records import RecordsParser
from ghostaudit.keys import email_key, hash_key, phone_key, user_key
from ghostaudit.model import ManifestEntry, ObsState, Observation
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

CAPTURED = "2026-06-10T12:00:00Z"
ENTRY = ManifestEntry("evidence_x", Path("evidence/records/x.json"), "origin", to_epoch(CAPTURED), 0)
HEAD_BYTES = 512
PARSER = RecordsParser()
DIGEST = "a" * 64

EXPORTS_DOC = {
    "exported_at": CAPTURED,
    "region": "global",
    "service_exports": {
        "account_service": {
            "profile_lookups": [
                {
                    "observed_at": "2026-06-10T09:00:00Z",
                    "profile": {"customer_reference": None, "email": "Ann.Lee@mail.test", "email_hash": None,
                                "full_name": None, "phone": None},
                    "resource_id": "account_1",
                    "status_code": 200,
                },
                {"observed_at": "2026-06-10T09:05:00Z", "profile": None, "resource_id": "account_2",
                 "status_code": 404},
                {"observed_at": "2026-06-10T09:06:00Z", "profile": None, "resource_id": "account_3",
                 "status_code": 200},
            ]
        },
        "analytics_platform": {
            "profiles": [
                {"audience_cohort": "x", "customer_reference": None, "email": "ann@mail.test",
                 "email_hash": None, "observed_at": "2026-06-10T09:10:00Z", "phone": None,
                 "resource_id": "analytics_1"},
                {"audience_cohort": "x", "customer_reference": None, "email": None, "email_hash": None,
                 "observed_at": "2026-06-10T09:11:00Z", "phone": None, "resource_id": "analytics_2"},
            ]
        },
        "backup_service": {
            "restore_entries": [
                {"archive_key": "k", "customer_email": "ann@mail.test", "customer_reference": None,
                 "observed_at": "2026-06-10T09:20:00Z", "resource_id": "backup_1", "restore_allowed": True},
                {"archive_key": "k", "customer_email": None, "customer_reference": "user_7",
                 "observed_at": "2026-06-10T09:21:00Z", "resource_id": "backup_2", "restore_allowed": False},
            ]
        },
        "export_service": {
            "exports": [
                {"customer_reference": None, "object_key": "o", "observed_at": "2026-06-10T09:30:00Z",
                 "owner_email": "ann@mail.test", "owner_phone": "+44 7700 900380", "resource_id": "export_1"}
            ]
        },
        "integration_service": {
            "connectors": [
                {"connector_name": "c", "customer_email": "ann@mail.test", "customer_reference": None,
                 "enabled": True, "last_delivery_status": "ok", "observed_at": "2026-06-10T09:40:00Z",
                 "resource_id": "data_flow_1"},
                {"connector_name": "c", "customer_email": "ann@mail.test", "customer_reference": None,
                 "enabled": False, "last_delivery_status": "ok", "observed_at": "2026-06-10T09:41:00Z",
                 "resource_id": "data_flow_2"},
            ]
        },
        "search_service": {
            "index_queries": [
                {"hits": {"documents": [{"customer_reference": None, "display_name": "Ann Lee",
                                         "email": "ann@mail.test", "email_hash": None, "phone": None,
                                         "resource_id": "search_1"}], "total": 1},
                 "observed_at": "2026-06-10T09:50:00Z", "query": "ann@mail.test", "resource_id": "search_1"},
                {"hits": {"documents": [], "total": 0}, "observed_at": "2026-06-10T09:51:00Z",
                 "query": "gone@mail.test", "resource_id": "search_2"},
            ]
        },
        "security_service": {
            "audit_records": [
                {"event_code": "E", "observed_at": "2026-06-10T10:00:00Z", "resource_id": "audit_record_1",
                 "retention_until": "2033-12-31T23:59:59Z", "subject_reference": "user_7"}
            ]
        },
        "support_platform": {
            "tickets": [
                {"customer_reference": None, "message_excerpt": "m", "observed_at": "2026-06-10T10:10:00Z",
                 "requester_email": "ann@mail.test", "requester_name": None, "requester_phone": None,
                 "resource_id": "support_1"},
                {"customer_reference": "user_7", "message_excerpt": "m", "observed_at": "2026-06-10T10:11:00Z",
                 "requester_email": None, "requester_name": None, "requester_phone": None,
                 "resource_id": "support_2"},
            ]
        },
    },
}

TOMBSTONE_EXPOSED = {
    "resource_id": "tombstone_1", "subject_reference": "user_7", "name": "Ann Lee",
    "email": "ann@mail.test", "phone": "+44 7700 900380", "email_hash": DIGEST, "account_status": "DELETED",
}
TOMBSTONE_CLEAN = {
    "resource_id": "tombstone_2", "subject_reference": "user_8", "name": None, "email": None,
    "phone": None, "email_hash": None, "account_status": "DELETED",
}
HISTORY_ROWS = [
    {"recorded_at": "2026-06-10T06:00:00Z", "system": "account_service", "resource_id": "account_9",
     "record_type": "USER_PROFILE", "result": "FOUND", "lookup_value": "old@mail.test"},
    {"recorded_at": "2026-06-11T06:00:00Z", "system": "analytics_platform", "resource_id": "analytics_9",
     "record_type": "ANALYTICS_PROFILE", "result": "ANONYMIZED", "lookup_value": ""},
    {"recorded_at": "2026-06-11T07:00:00Z", "system": "search_service", "resource_id": "search_9",
     "record_type": "SEARCH_INDEX_ENTRY", "result": "NOT_FOUND", "lookup_value": "user_7"},
]
BUNDLE_DOC = {
    "exported_at": CAPTURED,
    "source": "records_assurance_service",
    "snapshots": [
        {"captured_at": "2026-06-09T12:00:00Z", "data_store": "account_service",
         "collection": "customer_profiles", "records": []},
        {"captured_at": "2026-06-09T12:00:00Z", "data_store": "account_service",
         "collection": "customer_profiles",
         "records": [{"resource_id": "account_4", "customer_reference": "user_7", "full_name": "Ann Lee",
                      "email": "ann@mail.test", "phone": "+44 7700 900380", "account_status": "DELETION_PENDING",
                      "signup_channel": "web"}]},
        {"captured_at": "2026-06-09T13:00:00Z", "data_store": "identity_service",
         "collection": "deleted_customer_references", "records": [TOMBSTONE_EXPOSED, TOMBSTONE_CLEAN]},
        {"captured_at": "2026-06-09T14:00:00Z", "data_store": "support_platform",
         "collection": "support_conversations",
         "records": [
             {"resource_id": "support_4", "ticket_id": "CS-1", "subject_reference": "user_7", "channel": "email",
              "message_text": "Send it to Ann@Mail.Test please"},
             {"resource_id": "support_5", "ticket_id": "CS-2", "subject_reference": "user_7", "channel": "email",
              "message_text": "[REDACTED]"},
         ]},
        {"captured_at": "2026-06-09T15:00:00Z", "data_store": "search_service",
         "collection": "customer_search_documents",
         "records": [{"resource_id": "search_4", "index_name": "i",
                      "document": {"display_name": "Ann Lee", "email": "ann@mail.test",
                                   "customer_reference": "user_7"}}]},
        {"captured_at": "2026-06-09T16:00:00Z", "data_store": "backup_service", "collection": "backup_catalog",
         "records": [{"resource_id": "backup_4", "archive_path": "p", "subject_reference": "user_7",
                      "restore_allowed": False, "encryption": "AES-256"}]},
        {"captured_at": "2026-06-10T07:00:00Z", "data_store": "privacy_treatment_service",
         "collection": "operational_record_history", "records": HISTORY_ROWS},
    ],
}
LEDGER_DOC = {
    "exported_at": CAPTURED,
    "origin": "integration_management_service",
    "record_count": 3,
    "records": [
        {"recorded_at": CAPTURED, "system": "account_service", "resource_id": "account_5",
         "record_type": "USER_PROFILE", "result": "NOT_FOUND", "subject_reference": "ann@mail.test"},
        {"recorded_at": "2026-06-12T12:00:00Z", "system": "account_service", "resource_id": "account_5",
         "record_type": "USER_PROFILE", "result": "FOUND", "subject_reference": "ann@mail.test"},
        {"recorded_at": CAPTURED, "system": "support_platform", "resource_id": "support_6",
         "record_type": "SUPPORT_MESSAGE", "result": "IDENTIFIABLE", "subject_reference": "user_7"},
    ],
}
ANALYTICS_COLLECTION_DOC = {
    "captured_at": CAPTURED,
    "source": "analytics_identity_store",
    "collection": "customer_analytics_reports",
    "records": [
        {"resource_id": "analytics_5", "user_id": None, "email": None, "phone": None, "email_hash": None,
         "reporting_window": "w", "metrics": {}, "recent_activity": []},
        {"resource_id": "analytics_6", "user_id": "user_7", "email": "ann@mail.test", "phone": "+44 7700 900380",
         "email_hash": DIGEST, "reporting_window": "w", "metrics": {}, "recent_activity": []},
    ],
}
EXPORT_JOBS_DOC = {
    "captured_at": CAPTURED,
    "source": "user_export_store",
    "collection": "customer_export_jobs",
    "records": [
        {"resource_id": "export_5", "owner_email": "ann@mail.test", "file_name": "f.zip",
         "created_at": "2026-06-01T00:00:00Z", "expires_at": "2026-07-01T00:00:00Z",
         "download_available": True, "included_sections": ["profile"]}
    ],
}
EMPTY_COLLECTION_DOC = dict(ANALYTICS_COLLECTION_DOC, records=[])


def parse(doc: Any) -> ParseOutput:
    return PARSER.parse(ENTRY, json.dumps(doc, indent=2).encode("utf-8"))


def detect(doc: Any) -> bool:
    return PARSER.detect(ENTRY, json.dumps(doc, indent=2).encode("utf-8")[:HEAD_BYTES])


def by_id(output: ParseOutput) -> Dict[str, Observation]:
    """Observations keyed by resource id (the fixtures keep ids unique per document)."""
    return {obs.resource_id: obs for obs in output.observations}


class DetectTests(unittest.TestCase):
    def test_each_family_is_claimed(self) -> None:
        for doc in (EXPORTS_DOC, BUNDLE_DOC, LEDGER_DOC, ANALYTICS_COLLECTION_DOC):
            self.assertTrue(detect(doc))

    def test_non_json_and_unrelated_json_are_not_claimed(self) -> None:
        self.assertFalse(PARSER.detect(ENTRY, b"2026-06-10T09:00:00Z INFO service=x event=y"))
        self.assertFalse(PARSER.detect(ENTRY, b"-- sql\nCREATE TABLE t (a);"))
        self.assertFalse(PARSER.detect(ENTRY, b'{"hello": "world"}'))

    def test_parse_rejects_json_of_no_family(self) -> None:
        with self.assertRaisesRegex(ParseError, "not a records family"):
            PARSER.parse(ENTRY, b'{"hello": "world"}')
        with self.assertRaisesRegex(ParseError, "not a records family"):
            PARSER.parse(ENTRY, b"[1, 2]")

    def test_parse_rejects_invalid_json(self) -> None:
        with self.assertRaisesRegex(ParseError, "not valid JSON"):
            PARSER.parse(ENTRY, b'{"records": [')


class ServiceExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = parse(EXPORTS_DOC)
        self.obs = by_id(self.output)

    def test_every_entry_becomes_an_observation_with_its_observed_at(self) -> None:
        self.assertEqual(len(self.output.observations), 15)
        self.assertEqual(self.output.scopes, ())
        profile = self.obs["account_1"]
        self.assertEqual(profile.entry_time, to_epoch("2026-06-10T09:00:00Z"))
        self.assertEqual(profile.captured_at, ENTRY.captured_at)
        self.assertEqual(profile.system_id, "account_service")
        self.assertEqual(profile.locator, "service_exports.account_service.profile_lookups[0]")

    def test_profile_with_only_an_email_is_present_and_keeps_that_key(self) -> None:
        self.assertEqual(self.obs["account_1"].state, ObsState.PRESENT)
        self.assertEqual(self.obs["account_1"].subject_keys, frozenset({email_key("ann.lee@mail.test")}))
        self.assertEqual(self.obs["account_1"].category, "USER_PROFILE")

    def test_404_and_null_profile_are_absent_without_keys(self) -> None:
        for resource_id in ("account_2", "account_3"):
            self.assertEqual(self.obs[resource_id].state, ObsState.ABSENT)
            self.assertEqual(self.obs[resource_id].subject_keys, frozenset())

    def test_analytics_exposed_or_anonymized(self) -> None:
        self.assertEqual(self.obs["analytics_1"].state, ObsState.EXPOSED)
        self.assertEqual(self.obs["analytics_2"].state, ObsState.ANONYMIZED)
        self.assertEqual(self.obs["analytics_2"].subject_keys, frozenset())

    def test_restore_entries_follow_restore_allowed(self) -> None:
        self.assertEqual(self.obs["backup_1"].state, ObsState.ACTIVE)
        self.assertEqual(self.obs["backup_2"].state, ObsState.BLOCKED)
        self.assertEqual(self.obs["backup_2"].subject_keys, frozenset({user_key("user_7")}))

    def test_exports_carry_email_and_phone_keys(self) -> None:
        export = self.obs["export_1"]
        self.assertEqual(export.state, ObsState.PRESENT)
        self.assertEqual(export.subject_keys, frozenset({email_key("ann@mail.test"), phone_key("+447700900380")}))

    def test_connectors_follow_enabled(self) -> None:
        self.assertEqual(self.obs["data_flow_1"].state, ObsState.ACTIVE)
        self.assertEqual(self.obs["data_flow_2"].state, ObsState.DISABLED)

    def test_index_queries_present_with_hit_keys_or_absent(self) -> None:
        self.assertEqual(self.obs["search_1"].state, ObsState.PRESENT)
        self.assertEqual(self.obs["search_1"].subject_keys, frozenset({email_key("ann@mail.test")}))
        self.assertEqual(self.obs["search_2"].state, ObsState.ABSENT)
        self.assertEqual(self.obs["search_2"].subject_keys, frozenset())

    def test_audit_records_are_present_and_tickets_follow_requester_fields(self) -> None:
        self.assertEqual(self.obs["audit_record_1"].state, ObsState.PRESENT)
        self.assertEqual(self.obs["support_1"].state, ObsState.EXPOSED)
        self.assertEqual(self.obs["support_2"].state, ObsState.REDACTED)
        self.assertEqual(self.obs["support_2"].subject_keys, frozenset({user_key("user_7")}))

    def test_service_export_tickets_carry_no_category(self) -> None:
        self.assertIsNone(self.obs["support_1"].category)
        self.assertIsNone(self.obs["support_2"].category)

    def test_unknown_list_name_is_a_parse_error(self) -> None:
        doc = {"service_exports": {"account_service": {"mystery": [{"resource_id": "a"}]}}}
        with self.assertRaisesRegex(ParseError, "unknown record list 'mystery'"):
            parse(doc)


class SnapshotBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = parse(BUNDLE_DOC)
        self.obs = by_id(self.output)

    def test_entry_time_is_the_snapshot_captured_at_and_system_is_the_data_store(self) -> None:
        profile = self.obs["account_4"]
        self.assertEqual(profile.entry_time, to_epoch("2026-06-09T12:00:00Z"))
        self.assertEqual(profile.system_id, "account_service")
        self.assertEqual(profile.locator, "snapshots[1].records[0]")

    def test_deletion_pending_profile_is_present_with_all_keys(self) -> None:
        self.assertEqual(self.obs["account_4"].state, ObsState.PRESENT)
        self.assertEqual(
            self.obs["account_4"].subject_keys,
            frozenset({user_key("user_7"), email_key("ann@mail.test"), phone_key("+447700900380")}),
        )

    def test_empty_collection_is_a_scope_with_no_ids_at_the_snapshot_time(self) -> None:
        self.assertEqual(len(self.output.scopes), 1)
        scope = self.output.scopes[0]
        self.assertEqual(scope.system_id, "account_service")
        self.assertEqual(scope.present_ids, frozenset())
        self.assertEqual(scope.captured_at, to_epoch("2026-06-09T12:00:00Z"))
        self.assertEqual(scope.file_id, ENTRY.file_id)

    def test_tombstone_exposed_when_any_identifier_remains_and_redacted_when_none(self) -> None:
        exposed, clean = self.obs["tombstone_1"], self.obs["tombstone_2"]
        self.assertEqual(exposed.state, ObsState.EXPOSED)
        self.assertEqual(
            exposed.subject_keys,
            frozenset({user_key("user_7"), email_key("ann@mail.test"), phone_key("+447700900380"),
                       hash_key(DIGEST)}),
        )
        self.assertEqual(clean.state, ObsState.REDACTED)
        self.assertEqual(clean.subject_keys, frozenset({user_key("user_8")}))

    def test_support_conversation_redacted_only_for_the_marker(self) -> None:
        self.assertEqual(self.obs["support_4"].state, ObsState.EXPOSED)
        self.assertEqual(
            self.obs["support_4"].subject_keys, frozenset({user_key("user_7"), email_key("ann@mail.test")})
        )
        self.assertEqual(self.obs["support_5"].state, ObsState.REDACTED)
        self.assertEqual(self.obs["support_5"].subject_keys, frozenset({user_key("user_7")}))

    def test_search_document_keys_come_from_the_nested_document_and_never_from_names(self) -> None:
        self.assertEqual(
            self.obs["search_4"].subject_keys, frozenset({user_key("user_7"), email_key("ann@mail.test")})
        )

    def test_backup_catalog_blocked_when_restore_not_allowed(self) -> None:
        self.assertEqual(self.obs["backup_4"].state, ObsState.BLOCKED)

    def test_history_rows_use_the_row_system_lookup_value_and_ledger_states(self) -> None:
        profile, anonymized, absent = (self.obs[rid] for rid in ("account_9", "analytics_9", "search_9"))
        self.assertEqual(profile.system_id, "account_service")
        self.assertEqual(profile.state, ObsState.PRESENT)
        self.assertEqual(profile.subject_keys, frozenset({email_key("old@mail.test")}))
        self.assertEqual(profile.category, "USER_PROFILE")
        self.assertEqual(profile.entry_time, to_epoch("2026-06-10T06:00:00Z"))
        self.assertEqual(anonymized.state, ObsState.ANONYMIZED)
        self.assertEqual(anonymized.subject_keys, frozenset())
        self.assertEqual(absent.state, ObsState.ABSENT)
        self.assertEqual(absent.subject_keys, frozenset({user_key("user_7")}))
        self.assertEqual(absent.entry_time, to_epoch("2026-06-11T07:00:00Z"))

    def test_history_rows_ignore_the_bundle_data_store_as_system(self) -> None:
        systems = {obs.system_id for obs in self.output.observations if obs.resource_id.endswith("_9")}
        self.assertNotIn("privacy_treatment_service", systems)

    def test_unknown_collection_is_a_parse_error(self) -> None:
        doc = {"snapshots": [{"captured_at": CAPTURED, "data_store": "s", "collection": "mystery",
                              "records": [{"resource_id": "a"}]}]}
        with self.assertRaisesRegex(ParseError, "unknown record list 'mystery'"):
            parse(doc)


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows: List[Observation] = list(parse(LEDGER_DOC).observations)

    def test_result_maps_to_state_and_record_type_is_the_category(self) -> None:
        self.assertEqual([obs.state for obs in self.rows], [ObsState.ABSENT, ObsState.PRESENT, ObsState.EXPOSED])
        self.assertEqual(self.rows[2].category, "SUPPORT_MESSAGE")
        self.assertEqual(self.rows[2].system_id, "support_platform")
        self.assertEqual(self.rows[2].subject_keys, frozenset({user_key("user_7")}))

    def test_tail_entry_keeps_its_post_capture_entry_time(self) -> None:
        tail = self.rows[1]
        self.assertEqual(tail.entry_time, to_epoch("2026-06-12T12:00:00Z"))
        self.assertGreater(tail.entry_time, tail.captured_at)

    def test_unknown_result_is_a_parse_error(self) -> None:
        doc = dict(LEDGER_DOC, records=[dict(LEDGER_DOC["records"][0], result="MAYBE")])
        with self.assertRaisesRegex(ParseError, "unknown result 'MAYBE'"):
            parse(doc)

    def test_missing_field_is_a_parse_error(self) -> None:
        row = {key: value for key, value in LEDGER_DOC["records"][0].items() if key != "system"}
        with self.assertRaisesRegex(ParseError, "malformed"):
            parse(dict(LEDGER_DOC, records=[row]))


class CollectionTests(unittest.TestCase):
    def test_analytics_collection_maps_to_analytics_platform_at_captured_at(self) -> None:
        obs = by_id(parse(ANALYTICS_COLLECTION_DOC))
        self.assertEqual(obs["analytics_5"].system_id, "analytics_platform")
        self.assertEqual(obs["analytics_5"].state, ObsState.ANONYMIZED)
        self.assertEqual(obs["analytics_5"].entry_time, ENTRY.captured_at)
        self.assertEqual(obs["analytics_6"].state, ObsState.EXPOSED)
        self.assertEqual(
            obs["analytics_6"].subject_keys,
            frozenset({user_key("user_7"), email_key("ann@mail.test"), phone_key("+447700900380"),
                       hash_key(DIGEST)}),
        )

    def test_export_jobs_collection_maps_to_export_service(self) -> None:
        job = by_id(parse(EXPORT_JOBS_DOC))["export_5"]
        self.assertEqual((job.system_id, job.state, job.category), ("export_service", ObsState.PRESENT, "USER_EXPORT"))
        self.assertEqual(job.subject_keys, frozenset({email_key("ann@mail.test")}))

    def test_empty_collection_yields_no_observations(self) -> None:
        output = parse(EMPTY_COLLECTION_DOC)
        self.assertEqual((output.observations, output.scopes), ((), ()))

    def test_collection_without_a_system_mapping_is_a_parse_error(self) -> None:
        with self.assertRaisesRegex(ParseError, "no system for collection"):
            parse(dict(EXPORT_JOBS_DOC, collection="customer_profiles"))


@needs_dataset
class DatasetAcceptanceTests(unittest.TestCase):
    """Parses the real records files; ids below come from the verified analysis."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(config.Config().dataset_dir)
        cls.entries = reader.manifest()
        cls.outputs: Dict[str, ParseOutput] = {}
        for entry in cls.entries:
            data = entry.path.read_bytes()
            if PARSER.detect(entry, data[:HEAD_BYTES]):
                cls.outputs[entry.file_id] = PARSER.parse(entry, data)

    def find(self, file_id: str, resource_id: str) -> List[Observation]:
        return [obs for obs in self.outputs[file_id].observations if obs.resource_id == resource_id]

    def history_rows(self, file_id: str) -> List[Observation]:
        """Observations from the operational_record_history snapshot of one bundle."""
        path = next(e.path for e in self.entries if e.file_id == file_id)
        snapshots = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
        (index,) = [i for i, s in enumerate(snapshots) if s["collection"] == "operational_record_history"]
        prefix = "snapshots[%d]." % index
        return [o for o in self.outputs[file_id].observations if o.locator.startswith(prefix)]

    def test_all_28_json_files_parse(self) -> None:
        self.assertEqual(len(self.outputs), 28)

    def test_export_profile_lookups(self) -> None:
        (present,) = self.find("evidence_92", "account_5334")
        (absent,) = self.find("evidence_92", "account_6440")
        self.assertEqual(present.state, ObsState.PRESENT)
        self.assertEqual(len(present.subject_keys), 1)
        self.assertTrue(next(iter(present.subject_keys)).startswith("e:"))
        self.assertEqual((absent.state, absent.subject_keys), (ObsState.ABSENT, frozenset()))

    def test_bundle_with_empty_profiles_and_exposed_tombstone(self) -> None:
        scopes = self.outputs["evidence_51"].scopes
        self.assertEqual([(s.system_id, s.present_ids) for s in scopes], [("account_service", frozenset())])
        (tombstone,) = self.find("evidence_51", "tombstone_9178")
        self.assertEqual(tombstone.state, ObsState.EXPOSED)

    def test_history_row_keys(self) -> None:
        (profile,) = [o for o in self.find("evidence_22", "account_945") if o.state == ObsState.PRESENT]
        self.assertEqual(profile.subject_keys, frozenset({email_key("romero.valeria94@icloud.com")}))
        history = [
            obs
            for file_id in ("evidence_22", "evidence_31", "evidence_45")
            for obs in self.history_rows(file_id)
        ]
        self.assertEqual(len(history), 124)
        keyless = [obs for obs in history if not obs.subject_keys]
        self.assertEqual(len(keyless), 6)
        self.assertEqual({obs.state for obs in keyless}, {ObsState.ANONYMIZED})

    def test_ledger_tail_entry_is_kept_after_capture(self) -> None:
        tail = [o for o in self.find("evidence_13", "account_1417") if o.entry_time > o.captured_at]
        self.assertEqual([o.state for o in tail], [ObsState.PRESENT])


if __name__ == "__main__":
    unittest.main()
