"""Tests for ghostaudit.timeutil and ghostaudit.dataset (SPEC T6, N3, N5, section 2).

Expected epochs were derived outside this code with the system `date` tool. Dataset
fixtures are real lines from the sample files (case_01..case_32), never eval ids.
"""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path

from ghostaudit import config, timeutil
from ghostaudit.dataset import DatasetReader, ForbiddenInputError
from tests.dataset_guard import needs_dataset

DATASET = config.Config().dataset_dir
JULY_16_0800_UTC = 1784188800
TIMESTAMP_FIXTURES = (
    ("2026-07-16T08:00:00Z", JULY_16_0800_UTC),
    ("2026-07-16T08:00:00+00:00", JULY_16_0800_UTC),
    ("2026-07-16T10:00:00+02:00", JULY_16_0800_UTC),
    ("2026-07-16T03:30:00-04:30", JULY_16_0800_UTC),
    ("2026-07-16T08:00:00.250Z", JULY_16_0800_UTC),
    ("2026-07-16 08:00:00Z", JULY_16_0800_UTC),
    ("2026-07-16T08:00Z", JULY_16_0800_UTC),
    ("2026-07-16T08:00:00", JULY_16_0800_UTC),
    ("2026-08-18T09:14:00Z", 1787044440),
    ("2026-09-03T11:30:00Z", 1788435000),
    ("2024-02-29T12:00:00Z", 1709208000),
    ("1970-01-01T00:00:00Z", 0),
)
INVALID_TIMESTAMPS = ("", "not a time", "2026-07-16", "2026-02-30T00:00:00Z", "2026/07/16T08:00:00Z")
TIMESTAMP_COLUMNS = {
    "deletion_requests.csv": ("requested_at", "reported_at", "audit_at"),
    "sample_deletion_requests.csv": ("requested_at", "reported_at", "audit_at"),
    "user_identities.csv": ("updated_at",),
    "user_audit_log.csv": ("event_time",),
    "system_activity.csv": ("event_time",),
    "evidence_files.csv": ("captured_at",),
}


class TimeUtilTests(unittest.TestCase):
    def test_fixture_table_parses_to_expected_epochs(self) -> None:
        for text, expected in TIMESTAMP_FIXTURES:
            with self.subTest(text=text):
                self.assertEqual(timeutil.to_epoch(text), expected)

    def test_iso_formats_canonical_utc(self) -> None:
        self.assertEqual(timeutil.iso(JULY_16_0800_UTC), "2026-07-16T08:00:00Z")
        self.assertEqual(timeutil.iso(0), "1970-01-01T00:00:00Z")

    def test_round_trip_for_canonical_strings(self) -> None:
        for text in ("2026-07-16T08:00:00Z", "2024-02-29T12:00:00Z", "1970-01-01T00:00:00Z"):
            with self.subTest(text=text):
                self.assertEqual(timeutil.iso(timeutil.to_epoch(text)), text)

    def test_invalid_timestamps_raise_value_error(self) -> None:
        for text in INVALID_TIMESTAMPS:
            with self.subTest(text=text), self.assertRaises(ValueError):
                timeutil.to_epoch(text)


@needs_dataset
class DatasetCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = DatasetReader(DATASET)

    def test_request_counts(self) -> None:
        requests = self.reader.requests()
        self.assertEqual(len(requests), 550)
        self.assertEqual(sum(1 for r in requests if r.is_sample), 32)
        self.assertEqual(sum(1 for r in requests if not r.is_sample), 518)

    def test_evaluation_requests_come_before_samples(self) -> None:
        requests = self.reader.requests()
        self.assertFalse(requests[0].is_sample)
        self.assertTrue(requests[-1].is_sample)

    def test_identity_audit_activity_rule_and_manifest_counts(self) -> None:
        self.assertEqual(len(self.reader.identities()), 850)
        self.assertEqual(len(self.reader.audit_log()), 306)
        self.assertEqual(len(self.reader.activity()), 4011)
        self.assertEqual(len(self.reader.rules()), 15)
        self.assertEqual(len(self.reader.manifest()), 94)

    def test_manifest_paths_exist_and_order_follows_file(self) -> None:
        manifest = self.reader.manifest()
        self.assertTrue(all(entry.path.is_file() for entry in manifest))
        self.assertEqual([entry.order for entry in manifest], list(range(94)))
        self.assertEqual(len({entry.file_id for entry in manifest}), 94)

    def test_sample_request_row_fields(self) -> None:
        first = next(r for r in self.reader.requests() if r.case_id == "case_01")
        self.assertEqual(first.email, "amina.elmasri@gmail.com")
        self.assertEqual(first.reported_status, "COMPLETE")
        self.assertEqual(first.requested_at, timeutil.to_epoch("2026-08-18T09:14:00Z"))
        self.assertEqual(first.reported_at, timeutil.to_epoch("2026-08-20T16:42:00Z"))
        self.assertEqual(first.audit_at, timeutil.to_epoch("2026-09-03T11:30:00Z"))
        self.assertTrue(first.is_sample)
        self.assertTrue(first.text.startswith("Hi, I haven"))

    def test_identity_audit_activity_rule_and_manifest_first_rows(self) -> None:
        identity = self.reader.identities()[0]
        self.assertEqual(identity.name, "Amina El-Masri")
        self.assertEqual(identity.updated_at, timeutil.to_epoch("2026-05-28T04:03:00Z"))

        audit = self.reader.audit_log()[0]
        self.assertEqual((audit.audit_id, audit.field_name), ("audit_01", "phone"))
        self.assertEqual(audit.event_time, timeutil.to_epoch("2024-12-14T16:31:44Z"))

        activity = self.reader.activity()[0]
        self.assertEqual((activity.activity_id, activity.event_type), ("activity_01", "INDEX_RECORD"))
        self.assertEqual(activity.event_time, timeutil.to_epoch("2026-01-04T14:56:29Z"))

        rule = self.reader.rules()[4]
        self.assertEqual((rule.rule_id, rule.required_action), ("rule_05", "REDACT"))
        self.assertIn("customer, agent, or order context", rule.condition)

        entry = self.reader.manifest()[0]
        self.assertEqual(entry.file_id, "evidence_01")
        self.assertEqual(entry.captured_at, timeutil.to_epoch("2026-09-15T11:59:39Z"))
        self.assertTrue(str(entry.path).endswith(
            os.path.join("evidence", "logs", "service_events_ap_south_20260915.log")))

    def test_every_dataset_timestamp_is_canonical_and_parses(self) -> None:
        for name, columns in TIMESTAMP_COLUMNS.items():
            with self.subTest(file=name), self.reader.open(name).open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    for column in columns:
                        self.assertEqual(timeutil.iso(timeutil.to_epoch(row[column])), row[column])


@needs_dataset
class ForbiddenInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = DatasetReader(DATASET)

    def test_sample_output_is_forbidden(self) -> None:
        with self.assertRaises(ForbiddenInputError):
            self.reader.open("sample_output.csv")

    def test_paths_outside_dataset_are_forbidden(self) -> None:
        for rel in (
            "../solution/ANALYSIS.md",
            "../README.md",
            "evidence/../sample_output.csv",
            "evidence/../../README.md",
            "dataset_extra.csv",
            str(Path(DATASET).parent / "README.md"),
        ):
            with self.subTest(rel=rel), self.assertRaises(ForbiddenInputError):
                self.reader.open(rel)

    def test_allowlisted_inputs_resolve_to_files(self) -> None:
        self.assertTrue(self.reader.open("deletion_rules.csv").is_file())
        self.assertTrue(self.reader.open("evidence/logs/service_events_ap_south_20260915.log").is_file())

    def test_symlink_out_of_evidence_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            (root / "evidence").mkdir(parents=True)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("not participant data\n", encoding="utf-8")
            os.symlink(str(outside), str(root / "evidence" / "link.txt"))
            with self.assertRaises(ForbiddenInputError):
                DatasetReader(root).open("evidence/link.txt")
