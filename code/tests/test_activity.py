"""Tests for ghostaudit.activity (SPEC 4).

Template fixtures copy the wording of real system_activity.csv lines with
shortened, synthetic ids; the sample-only "Target resource" lines likewise.
"""
from __future__ import annotations

import collections
import unittest
from typing import Dict, Optional

from ghostaudit import config
from ghostaudit.activity import UnclassifiedActivityError, classify_activity, classify_row, unclassified_ids
from ghostaudit.dataset import ActivityRow, DatasetReader
from ghostaudit.model import ActKind, ClassifiedActivity, Treatment
from ghostaudit.policy import system_for
from tests.dataset_guard import needs_dataset

EXPECTED_KIND_COUNTS: Dict[ActKind, int] = {
    ActKind.ACCOUNT_SUBMIT: 532,
    ActKind.POLICY_OK: 248,
    ActKind.VIOLATION: 558,
    ActKind.FLOW_ENABLED: 89,
    ActKind.RESTORE_ALLOWED: 28,
    ActKind.REPLICATION_CHECKPOINT: 55,
    ActKind.REPOPULATED: 31,
    ActKind.RESTORE_REPOPULATED: 1,
    ActKind.NON_DELETION: 10,
    ActKind.LINK: 12,
    ActKind.TARGET_RESOURCE: 12,
    ActKind.NOISE: 2435,
}
TOTAL_ROWS = 4011


def classify(
    event: str, source: str, target: str, resource: str, details: str
) -> ClassifiedActivity:
    """Classify one synthetic activity row."""
    return classify_row(
        ActivityRow("activity_x", 0, event, source, target, resource, "SUCCESS", details)
    )


class TemplateTests(unittest.TestCase):
    def check(
        self,
        act: ClassifiedActivity,
        kind: ActKind,
        system_id: str,
        treatment: Optional[Treatment],
        related: Optional[str] = None,
    ) -> None:
        self.assertEqual(
            (act.kind, act.system_id, act.treatment, act.related_rid),
            (kind, system_id, treatment, related),
        )

    def test_account_submit(self) -> None:
        act = classify(
            "DELETE_RECORD", "deletion_worker", "account_service", "account_1",
            "Deletion worker submitted primary profile account_1 to account_service.",
        )
        self.check(act, ActKind.ACCOUNT_SUBMIT, "account_service", Treatment.DELETE)
        self.assertEqual(act.reported_result, "SUCCESS")

    def test_policy_ok_redact_and_retain(self) -> None:
        redact = classify(
            "REDACT_RECORD", "deletion_worker", "identity_service", "tombstone_3",
            "Policy action completed for tombstone_3.",
        )
        self.check(redact, ActKind.POLICY_OK, "identity_service", Treatment.REDACT)
        retain = classify(
            "RETAIN_RECORD", "deletion_worker", "legal_service", "legal_hold_2",
            "Policy action completed for legal_hold_2.",
        )
        self.check(retain, ActKind.POLICY_OK, "legal_service", Treatment.RETAIN)

    def test_violation_treatment_follows_event_type(self) -> None:
        for event, treatment in (
            ("DELETE_RECORD", Treatment.DELETE),
            ("REDACT_RECORD", Treatment.REDACT),
            ("ANONYMIZE_RECORD", Treatment.ANONYMIZE),
        ):
            act = classify(
                event, "deletion_worker", "support_platform", "support_9",
                "Deletion worker received the final result for support_9 from support_platform.",
            )
            self.check(act, ActKind.VIOLATION, "support_platform", treatment)

    def test_flow_and_restore_checks(self) -> None:
        flow = classify(
            "CHECK_DATA_FLOW", "deletion_worker", "integration_service", "data_flow_4",
            "Connector status check confirmed that data flow data_flow_4 remains enabled.",
        )
        self.check(flow, ActKind.FLOW_ENABLED, "integration_service", Treatment.FLOW)
        restore = classify(
            "CHECK_RESTORE_ACCESS", "deletion_worker", "backup_service", "backup_5",
            "Restore-access check confirmed that archive backup_5 can still be restored.",
        )
        self.check(restore, ActKind.RESTORE_ALLOWED, "backup_service", Treatment.RESTORE)

    def test_replication_checkpoint_is_account_service(self) -> None:
        act = classify(
            "SYNC_RECORD", "account_service", "account_replication_cluster", "account_6",
            "Replication worker reported its final checkpoint for account_6.",
        )
        self.check(act, ActKind.REPLICATION_CHECKPOINT, "account_service", None)

    def test_repopulated_names_search_resource(self) -> None:
        act = classify(
            "SYNC_RECORD", "integration_service", "search_service", "data_flow_7",
            "Active connector repopulated downstream resource search_8.",
        )
        self.check(act, ActKind.REPOPULATED, "integration_service", None, "search_8")
        self.assertEqual(act.resource_id, "data_flow_7")

    def test_restore_repopulated_is_backup_service(self) -> None:
        act = classify(
            "RESTORE_BACKUP", "backup_service", "search_service", "backup_9",
            "Restore job repopulated downstream resource search_10.",
        )
        self.check(act, ActKind.RESTORE_REPOPULATED, "backup_service", None, "search_10")

    def test_non_deletion_is_account_service(self) -> None:
        act = classify(
            "CLASSIFY_REQUEST", "privacy_intake", "privacy_case_management", "account_11",
            "Privacy intake classified request for account_11 as non-deletion; "
            "no destructive action was authorized.",
        )
        self.check(act, ActKind.NON_DELETION, "account_service", None)

    def test_link_rows_parse_alias_email_and_user(self) -> None:
        catalog = classify(
            "LINK_RESOURCE_IDENTITY", "data_catalog", "export_service", "export_1",
            "Data catalog linked export_1 (NST-2026-0718-1) to a.b@example.com and user_9001.",
        )
        self.check(catalog, ActKind.LINK, "export_service", None)
        self.assertEqual(
            (catalog.alias, catalog.linked_email, catalog.linked_user),
            ("NST-2026-0718-1", "a.b@example.com", "user_9001"),
        )
        attachment = classify(
            "LINK_RESOURCE_IDENTITY", "data_catalog", "object_storage", "object_19",
            "Attachment catalog confirmed object_19 (note.pdf) belongs only to "
            "a.b@example.com and user_9002; no other subject is linked.",
        )
        self.assertEqual(
            (attachment.alias, attachment.linked_email, attachment.linked_user),
            ("note.pdf", "a.b@example.com", "user_9002"),
        )

    def test_sample_target_resource_lines(self) -> None:
        for details in (
            "Deletion worker reported the requested operation as completed. "
            "Target resource: account_1.",
            "Deletion worker stopped after the target system returned an error. "
            "Target resource: account_1.",
        ):
            act = classify(
                "DELETE_RECORD", "deletion_worker", "account_service", "account_1", details
            )
            self.check(act, ActKind.TARGET_RESOURCE, "account_service", Treatment.DELETE)

    def test_replication_target_resource_is_account_service(self) -> None:
        act = classify(
            "SYNC_RECORD", "account_service", "account_failover_replica", "account_1",
            "Replication worker reported its final checkpoint. Target resource: account_1.",
        )
        self.check(act, ActKind.TARGET_RESOURCE, "account_service", None)

    def test_noise_comes_first_and_has_no_treatment(self) -> None:
        act = classify(
            "RETAIN_RECORD", "security_service", "archive_service", "audit_record_5",
            "Security-event archival processed audit_record_5.",
        )
        self.check(act, ActKind.NOISE, "archive_service", None)

    def test_unknown_template_raises(self) -> None:
        with self.assertRaises(UnclassifiedActivityError):
            classify(
                "DELETE_RECORD", "deletion_worker", "account_service", "account_1",
                "Something new.",
            )

    def test_resource_id_disagreeing_with_details_raises(self) -> None:
        with self.assertRaises(UnclassifiedActivityError):
            classify(
                "DELETE_RECORD", "deletion_worker", "account_service", "account_2",
                "Deletion worker submitted primary profile account_1 to account_service.",
            )


def activity_row(activity_id: str, resource: str, details: str, event: str = "DELETE_RECORD") -> ActivityRow:
    return ActivityRow(activity_id, 0, event, "deletion_worker", "account_service", resource, "SUCCESS", details)


class UnclassifiedRowTests(unittest.TestCase):
    """A row that fits no template is reported and inert; it never aborts a run."""

    UNKNOWN = "Deletion worker invented a new sentence for account_1."

    def rows(self):
        return [
            activity_row("activity_1", "account_1", "Policy action completed for account_1.", "REDACT_RECORD"),
            activity_row("activity_2", "account_1", self.UNKNOWN),
            activity_row("activity_3", "account_2", "Deletion worker invented a new sentence for account_2."),
            activity_row("activity_4", "account_3", "Another unknown shape, record 3."),
        ]

    def test_unknown_rows_are_classified_unclassified_and_inert(self) -> None:
        acts = classify_activity(self.rows())
        self.assertEqual([act.kind for act in acts],
                         [ActKind.POLICY_OK, ActKind.UNCLASSIFIED, ActKind.UNCLASSIFIED, ActKind.UNCLASSIFIED])
        self.assertEqual(unclassified_ids(acts), ("activity_2", "activity_3", "activity_4"))
        for act in acts[1:]:
            self.assertEqual((act.treatment, act.related_rid, act.linked_user), (None, None, None))

    def test_one_warning_per_template_shape(self) -> None:
        with self.assertLogs("ghostaudit.activity", level="WARNING") as logs:
            classify_activity(self.rows())
        self.assertEqual(len(logs.output), 2)  # activities 2 and 3 share a shape, 4 has its own

    def test_a_resource_id_that_disagrees_with_the_details_is_unclassified(self) -> None:
        row = activity_row("activity_5", "account_2",
                           "Deletion worker submitted primary profile account_1 to account_service.")
        with self.assertLogs("ghostaudit.activity", level="WARNING"):
            self.assertEqual(unclassified_ids(classify_activity([row])), ("activity_5",))

    def test_strict_mode_raises(self) -> None:
        with self.assertRaises(UnclassifiedActivityError):
            classify_activity(self.rows(), strict=True)

    def test_a_clean_stream_has_no_unclassified_rows(self) -> None:
        self.assertEqual(unclassified_ids(classify_activity(self.rows()[:1])), ())


@needs_dataset
class DatasetClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.acts = classify_activity(DatasetReader(config.Config().dataset_dir).activity())

    def test_kind_counts(self) -> None:
        counts = collections.Counter(act.kind for act in self.acts)
        self.assertEqual(dict(counts), EXPECTED_KIND_COUNTS)
        self.assertEqual(len(self.acts), TOTAL_ROWS)

    def test_no_row_is_unclassified(self) -> None:
        self.assertEqual(unclassified_ids(self.acts), ())

    def test_sorted_by_time_then_id(self) -> None:
        keys = [(act.t, act.activity_id) for act in self.acts]
        self.assertEqual(keys, sorted(keys))

    def test_all_twelve_link_rows_parse(self) -> None:
        links = [act for act in self.acts if act.kind is ActKind.LINK]
        self.assertEqual(len(links), 12)
        for link in links:
            self.assertTrue(link.alias and link.linked_email)
            self.assertTrue(link.linked_user.startswith("user_"))

    def test_export_link_example(self) -> None:
        link = next(act for act in self.acts if act.activity_id == "activity_4009")
        self.assertEqual(
            (link.resource_id, link.alias, link.linked_user),
            ("export_1842", "NST-2026-0718-1842", "user_18"),
        )

    def test_system_id_agrees_with_resource_prefix(self) -> None:
        """SPEC 4: every non-noise row's system_id is the owner from SYSTEM_BY_PREFIX."""
        mismatched = [
            (act.activity_id, act.system_id, system_for(act.resource_id))
            for act in self.acts
            if act.kind is not ActKind.NOISE and act.system_id != system_for(act.resource_id)
        ]
        self.assertEqual(mismatched, [])

    def test_out_of_order_tail_is_resorted(self) -> None:
        position = {act.activity_id: index for index, act in enumerate(self.acts)}
        self.assertLess(position["activity_4009"], position["activity_4000"])


if __name__ == "__main__":
    unittest.main()
