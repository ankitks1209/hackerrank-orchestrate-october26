"""Tests for ghostaudit.evidence.logs Observations (SPEC F9 trace join and event table).

Unit cases use synthetic lines in the real formats. Acceptance cases read the real logs
through the manifest; they cite evidence ids and sample case_12 only.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Dict, Iterable

from ghostaudit.config import REPO_ROOT
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence import REGISTRY
from ghostaudit.evidence.base import ParseError, ParseOutput, select_parser
from ghostaudit.evidence.logs import LogParser, parse_log
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import ManifestEntry, ObsState, Observation
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

CAPTURED = "2026-09-15T12:00:00Z"
ENTRY = ManifestEntry("evidence_99", Path("evidence/logs/x.log"), "origin", to_epoch(CAPTURED), 0)
CORPUS_LOGS = 26
CORPUS_OBSERVATIONS = 771  # sum of the per-event line counts of the 26 logs, minus the decoys
CORPUS_DECOYS = 300  # evidence_53 profile_service lines


def line(second: int, service: str, trace: str, event: str, **fields: str) -> str:
    """A logfmt line `second` seconds into the hour; quoting keeps emails and phones intact."""
    body = " ".join('%s="%s"' % item for item in fields.items())
    stamp = "2026-09-15T11:00:%02dZ" % second
    return "%s level=INFO service=%s trace_id=%s event=%s %s" % (stamp, service, trace, event, body)


def parse(*lines: str) -> ParseOutput:
    return LogParser().parse(ENTRY, "\n".join(lines).encode("utf-8"))


def by_resource(observations: Iterable[Observation]) -> Dict[str, Observation]:
    return {obs.resource_id: obs for obs in observations}


def lookup(second: int, trace: str, **fields: str) -> str:
    """An account_service `profile_lookup_completed` line."""
    return line(second, "account_service", trace, "profile_lookup_completed", **fields)


def started(second: int, trace: str, **fields: str) -> str:
    return line(second, "account_service", trace, "profile_lookup_started", **fields)


class TraceJoinTests(unittest.TestCase):
    def test_interleaved_traces_join_by_trace_id_not_adjacency(self) -> None:
        output = parse(
            started(1, "tr-1", lookup_key="a@x.org"),
            started(2, "tr-2", lookup_key="b@x.org"),
            line(3, "account_service", "tr-1", "cache_lookup", result="miss"),
            line(4, "account_service", "tr-2", "dependency_retry", reason="read_timeout"),
            lookup(5, "tr-2", resource_id="account_2", rows="0"),
            line(6, "account_service", "tr-3", "connection_acquired", pool="x_primary"),
            lookup(7, "tr-1", resource_id="account_1", rows="1"),
        )
        found = by_resource(output.observations)
        self.assertEqual(found["account_1"].subject_keys, frozenset({"e:a@x.org"}))
        self.assertEqual(found["account_2"].subject_keys, frozenset({"e:b@x.org"}))
        self.assertEqual(output.notes, ())

    def test_completed_line_without_started_line_keeps_only_inline_keys(self) -> None:
        output = parse(
            lookup(1, "tr-9", resource_id="account_5", rows="0", correlation_key="C@X.org"),
            lookup(2, "tr-8", resource_id="account_6", rows="1"),
        )
        found = by_resource(output.observations)
        self.assertEqual(found["account_5"].subject_keys, frozenset({"e:c@x.org"}))
        self.assertEqual(found["account_6"].subject_keys, frozenset())

    def test_line_without_trace_never_borrows_the_instance_as_trace(self) -> None:
        no_trace = (
            "2026-09-15T11:00:05Z level=INFO service=account_service instance=account-1 "
            "event=profile_lookup_completed resource_id=account_7 rows=1"
        )
        output = parse(started(1, "account-1", lookup_key="a@x.org"), no_trace)
        self.assertEqual(output.observations[0].subject_keys, frozenset())

    def test_every_started_key_field_is_normalized(self) -> None:
        pairs = (
            ("lookup_key", "A@X.org", "e:a@x.org"),
            ("match_key", "u@x.org", "e:u@x.org"),
            ("subject_ref", "user_3", "u:user_3"),
            ("subject_key", "+81 90 6156 0005", "p:819061560005"),
            ("scan_key", "user_4", "u:user_4"),
            ("owner_key", "b@x.org", "e:b@x.org"),
        )
        lines = []
        for number, (field, value, _key) in enumerate(pairs, start=1):
            trace = "tr-%d" % number
            lines.append(line(number, "support_platform", trace, "scan_started", **{field: value}))
            lines.append(line(10 + number, "support_platform", trace, "message_pii_scan",
                              resource_id="support_%d" % number))
        found = by_resource(parse(*lines).observations)
        for number, (_field, _value, key) in enumerate(pairs, start=1):
            self.assertEqual(found["support_%d" % number].subject_keys, frozenset({key}))

    def test_a_line_may_carry_its_own_start_key(self) -> None:
        output = parse(line(1, "support_platform", "tr-1", "message_read", resource_id="support_1",
                            subject_ref="user_8", message_text="[REDACTED]"))
        self.assertEqual(output.observations[0].subject_keys, frozenset({"u:user_8"}))


class EventTableTests(unittest.TestCase):
    CASES = (
        ("account_service", "profile_lookup_completed", {"rows": "0"}, "ABSENT", "USER_PROFILE"),
        ("account_service", "profile_lookup_completed", {"rows": "1"}, "PRESENT", "USER_PROFILE"),
        ("search_service", "index_query_completed", {"result": "hit"}, "PRESENT",
         "SEARCH_INDEX_ENTRY"),
        ("security_service", "audit_record_read_completed", {"rows": "1"}, "PRESENT",
         "SECURITY_AUDIT_LOG"),
        ("analytics_platform", "analytics_identity_scan", {"matched_value": "a@x.org"},
         "EXPOSED", "ANALYTICS_PROFILE"),
        ("analytics_platform", "analytics_profile_read", {"direct_identifiers": "0"},
         "ANONYMIZED", "ANALYTICS_PROFILE"),
        ("analytics_platform", "analytics_profile_read", {"direct_identifiers": "2"},
         "EXPOSED", "ANALYTICS_PROFILE"),
        ("analytics_platform", "analytics_profile_read_completed", {"email": "a@x.org"},
         "EXPOSED", "ANALYTICS_PROFILE"),
        ("analytics_platform", "analytics_profile_read_completed",
         {"email": "null", "phone": "null"}, "ANONYMIZED", "ANALYTICS_PROFILE"),
        ("analytics_platform", "contact_lookup_completed", {"email_opt_in": "true"},
         "PRESENT", "SECONDARY_IDENTIFIER"),
        ("support_platform", "message_pii_scan", {"matched_value": "a@x.org"},
         "EXPOSED", "SUPPORT_MESSAGE"),
        ("support_platform", "attachment_pii_scan", {"matched_value": "a@x.org"},
         "PRESENT", "SUPPORT_ATTACHMENT"),
        ("support_platform", "message_read", {"message_text": "[REDACTED]"},
         "REDACTED", "SUPPORT_MESSAGE"),
        ("support_platform", "support_ticket_read_completed", {"requester_email": "a@x.org"},
         "EXPOSED", None),
        ("support_platform", "support_ticket_read_completed",
         {"requester_email": "null", "requester_name": "null", "requester_phone": "null",
          "customer_reference": "user_2"}, "REDACTED", None),
        ("integration_service", "connector_heartbeat", {"enabled": "true"}, "ACTIVE", "DATA_FLOW"),
        ("integration_service", "connector_config_loaded", {"enabled": "false"},
         "DISABLED", "DATA_FLOW"),
        ("integration_service", "connector_config_read_completed", {"enabled": "true"},
         "ACTIVE", "DATA_FLOW"),
        ("backup_service", "restore_candidate_evaluated",
         {"eligible": "true", "deletion_block": "false"}, "ACTIVE", "BACKUP_ARCHIVE"),
        ("backup_service", "restore_candidate_evaluated",
         {"eligible": "true", "deletion_block": "true"}, "BLOCKED", "BACKUP_ARCHIVE"),
        ("backup_service", "restore_candidate_evaluated",
         {"eligible": "false", "deletion_block": "false"}, "BLOCKED", "BACKUP_ARCHIVE"),
        ("backup_service", "restore_authorization_completed", {"decision": "deny"},
         "BLOCKED", "BACKUP_ARCHIVE"),
        ("backup_service", "restore_policy_read_completed", {"restore_allowed": "true"},
         "ACTIVE", "BACKUP_ARCHIVE"),
        ("backup_service", "restore_policy_read_completed", {"restore_allowed": "false"},
         "BLOCKED", "BACKUP_ARCHIVE"),
        ("export_service", "export_download_check_completed", {"available": "true"},
         "PRESENT", "USER_EXPORT"),
        ("export_service", "export_metadata_read_completed", {"available": "true"},
         "PRESENT", "USER_EXPORT"),
        ("legal_service", "retained_order_loaded", {"access": "allowed"},
         "PRESENT", "LEGAL_HOLD_RECORD"),
    )

    def test_states_categories_and_system(self) -> None:
        for service, event, fields, state, category in self.CASES:
            with self.subTest(event=event, fields=fields):
                output = parse(line(1, service, "tr-1", event, resource_id="r_1", **fields))
                self.assertEqual(output.notes, ())
                (obs,) = output.observations
                self.assertEqual(
                    (obs.state.value, obs.category, obs.system_id), (state, category, service)
                )

    def test_support_replica_lines_belong_to_support_platform_without_category(self) -> None:
        output = parse(
            line(1, "support_replica", "tr-1", "contact_query_completed",
                 resource_id="support_1", rows="1"),
            line(2, "support_replica", "tr-1", "deletion_marker_check",
                 resource_id="support_1", marker_found="false"),
        )
        self.assertEqual(
            [(o.system_id, o.category, o.state) for o in output.observations],
            [("support_platform", None, ObsState.PRESENT)] * 2,
        )

    def test_diag_record_lookup_uses_system_type_and_result_vocabulary(self) -> None:
        text = (
            '2026-09-06T07:00:00Z WARN service=search_index_service event=record_lookup seq=12 '
            'system="analytics_platform" resource_id="analytics_3181" '
            'record_type="ANALYTICS_PROFILE" result="IDENTIFIABLE" subject_reference="Z.M@x.org"'
        )
        (obs,) = parse(text).observations
        self.assertEqual(
            (obs.system_id, obs.resource_id, obs.category, obs.state, obs.subject_keys),
            ("analytics_platform", "analytics_3181", "ANALYTICS_PROFILE", ObsState.EXPOSED,
             frozenset({"e:z.m@x.org"})),
        )

    def test_entry_time_is_the_line_time_and_locator_the_line_number(self) -> None:
        output = parse(
            line(1, "account_service", "tr-1", "cache_lookup", result="miss"),
            lookup(2, "tr-1", resource_id="account_1", rows="1"),
        )
        (obs,) = output.observations
        self.assertEqual(obs.entry_time, to_epoch("2026-09-15T11:00:02Z"))
        self.assertEqual(obs.captured_at, ENTRY.captured_at)
        self.assertEqual((obs.file_id, obs.locator), ("evidence_99", "evidence_99:L2"))


class DroppedLineTests(unittest.TestCase):
    def test_noise_and_started_lines_yield_nothing_and_no_note(self) -> None:
        output = parse(
            started(1, "tr-1", lookup_key="a@x.org"),
            line(2, "account_service", "tr-1", "cache_lookup", resource_id="account_1"),
            line(3, "attachment_preview", "tr-2", "thumbnail_failed", resource_id="support_7"),
        )
        self.assertEqual((output.observations, output.notes), ((), ()))

    def test_profile_service_decoys_are_dropped_and_counted_in_one_note(self) -> None:
        output = parse(*[
            line(i, "profile_service", "tr-%d" % i, "profile_lookup_completed",
                 resource_id="account_1000%d" % i, rows="1", correlation_key="a%d@x.org" % i)
            for i in range(3)
        ])
        self.assertEqual(output.observations, ())
        self.assertEqual(
            output.notes,
            ("dropped 3 profile_service/profile_lookup_completed lines "
             "from an unexpected service",),
        )

    def test_unknown_event_is_reported_with_its_locator(self) -> None:
        output = parse(line(1, "account_service", "tr-1", "profile_wiped", resource_id="account_1"))
        self.assertEqual(output.observations, ())
        self.assertEqual(
            output.notes, ("evidence_99:L1 unknown_event account_service/profile_wiped",)
        )

    def test_unsupported_value_or_missing_resource_is_skipped_with_note(self) -> None:
        output = parse(
            lookup(1, "tr-1", resource_id="account_1", rows="2"),
            lookup(2, "tr-2", rows="1"),
            line(3, "support_platform", "tr-3", "message_read", resource_id="support_1",
                 message_text="hello"),
        )
        self.assertEqual(output.observations, ())
        self.assertEqual(len(output.notes), 3)
        self.assertTrue(all("skipped" in note for note in output.notes))
        self.assertIn("evidence_99:L2", output.notes[1])

    def test_non_utf8_file_raises_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            LogParser().parse(ENTRY, b"\xff\xfe2026-09-15T11:00:00Z")

    def test_malformed_line_raises_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            parse("not a log line")


@needs_dataset
class CorpusAcceptanceTests(unittest.TestCase):
    """Parses the 26 real logs through the manifest (SPEC F9)."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        cls.entries = tuple(e for e in reader.manifest() if e.path.suffix == ".log")
        cls.outputs = {e.file_id: LogParser().parse(e, e.path.read_bytes()) for e in cls.entries}
        cls.index = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.requests = {r.case_id: r for r in reader.requests()}

    def resource(self, file_id: str, resource_id: str) -> Observation:
        return by_resource(self.outputs[file_id].observations)[resource_id]

    def test_all_26_logs_are_claimed_by_the_log_parser_alone(self) -> None:
        self.assertEqual(len(self.entries), CORPUS_LOGS)
        for entry in self.entries:
            with self.subTest(file_id=entry.file_id):
                head = entry.path.read_bytes()[:512]
                self.assertIsInstance(select_parser(entry, head, REGISTRY), LogParser)

    def test_no_unknown_events_and_only_the_decoy_note(self) -> None:
        notes = [n for out in self.outputs.values() for n in out.notes]
        self.assertEqual([n for n in notes if "unknown_event" in n], [])
        self.assertEqual(notes, ["dropped %d profile_service/profile_lookup_completed lines "
                                 "from an unexpected service" % CORPUS_DECOYS])
        total = sum(len(out.observations) for out in self.outputs.values())
        self.assertEqual(total, CORPUS_OBSERVATIONS)

    def test_evidence_01_flows_and_the_old_email_hash(self) -> None:
        self.assertEqual(self.resource("evidence_01", "data_flow_9846").state, ObsState.ACTIVE)
        self.assertEqual(self.resource("evidence_01", "backup_3245").state, ObsState.ACTIVE)
        contact = next(o for o in self.outputs["evidence_01"].observations
                       if o.category == "SECONDARY_IDENTIFIER")
        self.assertEqual(contact.locator, "evidence_01:L92")
        owner = self.index.resolve(self.requests["case_12"].email)
        self.assertEqual(self.index.users_for(contact.subject_keys), (owner,))
        self.assertTrue(all(key.startswith("h:") for key in contact.subject_keys))

    def test_evidence_94_states(self) -> None:
        expected = {
            "search_4013": ObsState.PRESENT,
            "analytics_037": ObsState.EXPOSED,
            "support_5569": ObsState.EXPOSED,
            "data_flow_4890": ObsState.ACTIVE,
        }
        for resource_id, state in expected.items():
            with self.subTest(resource_id=resource_id):
                self.assertEqual(self.resource("evidence_94", resource_id).state, state)

    def test_evidence_61_replica_lines(self) -> None:
        found = self.resource("evidence_61", "support_002")
        self.assertEqual(found.state, ObsState.PRESENT)
        self.assertEqual(found.subject_keys, frozenset({"e:nadia.ionescu@yahoo.com"}))
        stray = self.resource("evidence_61", "support_5914")
        self.assertEqual(stray.subject_keys, frozenset({"e:nadia.popescu@yahoo.com"}))
        self.assertEqual(self.index.users_for(stray.subject_keys), ())

    def test_parse_log_numbers_lines_from_one(self) -> None:
        entry = next(e for e in self.entries if e.file_id == "evidence_61")
        records = parse_log(entry.path.read_text(encoding="utf-8"))
        self.assertEqual(records[0].line, 1)
        self.assertEqual([r.line for r in records], sorted(r.line for r in records))


if __name__ == "__main__":
    unittest.main()
