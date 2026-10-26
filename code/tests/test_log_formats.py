"""Tests for ghostaudit.evidence.logs (SPEC F9 log line formats).

Fixtures are real dataset lines; the cloud escaping cases are synthetic.
"""
from __future__ import annotations

import collections
import unittest

from ghostaudit import config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.base import ParseError
from ghostaudit.evidence.logs import (
    FMT_BRACKET,
    FMT_CLOUD,
    FMT_DIAG,
    FMT_JSON,
    FMT_LOGFMT,
    FMT_PIPE,
    FMT_READBACK,
    FMT_SYSLOG,
    parse_line,
    parse_log,
)
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

DATASET = config.Config().dataset_dir

LOGFMT = (
    '2026-09-15T11:51:46Z level=WARN service=support_platform instance=support-1 pod=support-63b9 '
    "region=eu-west-1 trace_id=tr-5845609 resource_id=support_9538 event=attachment_pii_scan "
    'matched_value="+81 90 6156 0005" file=delivery_confirmation_32.pdf detector=direct_identifier'
)
LOGFMT_NO_TRACE = (
    "2026-09-17T22:00:11Z level=INFO service=support_replica instance=support-eu-03 pod=replica-7c9f "
    "event=contact_query_completed resource_id=support_5914 lookup_key=nadia.popescu@yahoo.com rows=1 "
    "source=case_archive latency_ms=31"
)
READBACK = (
    "2026-02-18T05:47:12Z level=INFO service=integration_service trace_id=rb-054712-001 "
    "event=connector_config_read_completed resource_id=data_flow_3669 enabled=true "
    "last_delivery_status=delivered connector_name=analytics_identity_bridge "
    "customer_email=t.oliveira6897@gmail.com customer_reference=null"
)
JSON_LINE = (
    '2026-04-19T06:51:20Z {"severity":"INFO","logger":"search_service","service":"search_service",'
    '"instance":"search-6","pod":"search-56f3","region":"eu-central-1","trace_id":"tr-7722221",'
    '"event":"dependency_recovered","attempt":"2","route":"primary"}'
)
JSON_NO_TRACE = (
    '2026-04-19T06:56:17Z {"severity":"DEBUG","logger":"dns_cache","service":"dns_cache",'
    '"instance":"resolver-3","event":"cache_refresh","entries":"120"}'
)
SYSLOG = (
    "2026-08-22T10:51:17Z <15>1 node-1 account_service tr-4973247 - - level=DEBUG instance=\"account-2\" "
    'pod="account-0525" region="eu-west-1" resource_id="account_1785" event="profile_lookup_completed" '
    'rows="1" http_status="200" duration_ms="50"'
)
BRACKET = (
    '2026-07-28T05:51:18Z [DEBUG] [account_service] [tr-6074163] profile_lookup_started: '
    'instance="account-5" pod="account-886d" region="eu-west-1" lookup_key="l.nascimento40@gmail.com" '
    'attempt="1"'
)
PIPE = (
    '2026-07-03T07:51:49Z | DEBUG | analytics_platform | tr-4862866 | analytics_profile_scan_started | '
    'instance="analytics-5" pod="analytics-2fcc" region="ap-south-1" lookup_key="analytics_257" attempt="1"'
)
CLOUD = (
    '2026-06-08T06:52:09Z requestId=tr-1108860 level=INFO function=search_service message="instance=\\"search-3\\" '
    'pod=\\"search-0696\\" region=\\"us-east-2\\" resource_id=\\"search_021\\" event=\\"index_query_completed\\" '
    'index=\\"customer_directory_v3\\" result=\\"hit\\" shard=\\"9\\" took_ms=\\"24\\" '
    'correlation_key=\\"mrios9507.jr@fastmail.com\\""'
)
DIAG_WARN = (
    '2026-09-06T07:00:00Z WARN service=search_index_service event=record_lookup seq=12 '
    'system="analytics_platform" resource_id="analytics_3181" record_type="ANALYTICS_PROFILE" '
    'result="IDENTIFIABLE" subject_reference="zmahlangu160178@gmail.com"'
)
DIAG_INFO = (
    '2026-03-15T07:00:00Z INFO service=downstream_delivery_service event=record_lookup seq=1 '
    'system="account_service" resource_id="account_022" record_type="USER_PROFILE" result="NOT_FOUND" '
    'subject_reference="zofia-novak@gmail.com"'
)
# Pre-computed with grep over the 26 logs: raw lines per body format, minus the framing lines.
CORPUS_FILES = 26
CORPUS_LINES = 2211
CORPUS_FRAMING = 39
CORPUS_COUNTS = {
    FMT_LOGFMT: 221,
    FMT_READBACK: 528,
    FMT_JSON: 244,
    FMT_SYSLOG: 231,
    FMT_BRACKET: 214,
    FMT_PIPE: 228,
    FMT_CLOUD: 431,
    FMT_DIAG: 75,
}


class FormatFixtureTests(unittest.TestCase):
    def test_logfmt_quoted_phone_and_trace(self) -> None:
        record = parse_line(LOGFMT)
        self.assertEqual(record.ts, to_epoch("2026-09-15T11:51:46Z"))
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_LOGFMT, "WARN", "support_platform", "tr-5845609", "attachment_pii_scan"),
        )
        self.assertEqual(record.kv["matched_value"], "+81 90 6156 0005")
        self.assertEqual(record.kv["resource_id"], "support_9538")

    def test_logfmt_without_trace_does_not_fall_back_to_instance(self) -> None:
        record = parse_line(LOGFMT_NO_TRACE)
        self.assertEqual(record.fmt, FMT_LOGFMT)
        self.assertIsNone(record.trace)
        self.assertEqual(record.kv["instance"], "support-eu-03")
        self.assertEqual(record.kv["lookup_key"], "nadia.popescu@yahoo.com")

    def test_readback_literal_null_becomes_none(self) -> None:
        record = parse_line(READBACK)
        self.assertEqual(record.fmt, FMT_READBACK)
        self.assertEqual(record.trace, "rb-054712-001")
        self.assertIsNone(record.kv["customer_reference"])
        self.assertEqual(record.kv["customer_email"], "t.oliveira6897@gmail.com")
        self.assertEqual(record.kv["enabled"], "true")

    def test_json(self) -> None:
        record = parse_line(JSON_LINE)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_JSON, "INFO", "search_service", "tr-7722221", "dependency_recovered"),
        )
        self.assertEqual(record.kv["attempt"], "2")

    def test_json_without_trace_has_none(self) -> None:
        record = parse_line(JSON_NO_TRACE)
        self.assertIsNone(record.trace)
        self.assertEqual(record.service, "dns_cache")

    def test_json_null_values_and_non_string_values(self) -> None:
        record = parse_line('2026-04-19T06:56:17Z {"severity":"INFO","email":null,"phone":"null"}')
        self.assertIsNone(record.kv["email"])
        self.assertIsNone(record.kv["phone"])
        with self.assertRaisesRegex(ParseError, "not a string"):
            parse_line('2026-04-19T06:56:17Z {"severity":"INFO","rows":1}')

    def test_syslog_service_and_trace_come_from_header(self) -> None:
        record = parse_line(SYSLOG)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_SYSLOG, "DEBUG", "account_service", "tr-4973247", "profile_lookup_completed"),
        )
        self.assertEqual(record.kv["resource_id"], "account_1785")
        self.assertEqual(record.kv["rows"], "1")

    def test_bracket_event_precedes_colon(self) -> None:
        record = parse_line(BRACKET)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_BRACKET, "DEBUG", "account_service", "tr-6074163", "profile_lookup_started"),
        )
        self.assertEqual(record.kv["lookup_key"], "l.nascimento40@gmail.com")

    def test_pipe_columns(self) -> None:
        record = parse_line(PIPE)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_PIPE, "DEBUG", "analytics_platform", "tr-4862866", "analytics_profile_scan_started"),
        )
        self.assertEqual(record.kv["lookup_key"], "analytics_257")

    def test_cloud_message_is_parsed_a_second_time(self) -> None:
        record = parse_line(CLOUD)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.trace, record.event),
            (FMT_CLOUD, "INFO", "search_service", "tr-1108860", "index_query_completed"),
        )
        self.assertEqual(record.kv["correlation_key"], "mrios9507.jr@fastmail.com")
        self.assertEqual(record.kv["result"], "hit")
        self.assertNotIn("message", record.kv)

    def test_cloud_embedded_quotes_and_at_sign(self) -> None:
        line = (
            '2026-06-08T06:52:09Z requestId=tr-1 level=WARN function=support_platform '
            'message="event=\\"message_pii_scan\\" note=\\"said \\\\\\"hi\\\\\\" to a@b.org\\" '
            'matched_value=\\"o\'brien+x@mail.example\\" email=\\"null\\""'
        )
        record = parse_line(line)
        self.assertEqual(record.event, "message_pii_scan")
        self.assertEqual(record.kv["note"], 'said "hi" to a@b.org')
        self.assertEqual(record.kv["matched_value"], "o'brien+x@mail.example")
        self.assertIsNone(record.kv["email"])

    def test_diag_warn_record_lookup_identifiable(self) -> None:
        record = parse_line(DIAG_WARN)
        self.assertEqual(
            (record.fmt, record.level, record.service, record.event),
            (FMT_DIAG, "WARN", "search_index_service", "record_lookup"),
        )
        self.assertIsNone(record.trace)
        self.assertEqual(record.kv["resource_id"], "analytics_3181")
        self.assertEqual(record.kv["result"], "IDENTIFIABLE")

    def test_diag_info_record_lookup(self) -> None:
        record = parse_line(DIAG_INFO)
        self.assertEqual((record.fmt, record.level), (FMT_DIAG, "INFO"))
        self.assertEqual(record.kv["result"], "NOT_FOUND")

    def test_unrecognised_body_raises(self) -> None:
        with self.assertRaises(ParseError):
            parse_line("2026-04-19T06:56:17Z free text without structure")
        with self.assertRaises(ParseError):
            parse_line("not-a-timestamp level=INFO")
        with self.assertRaises(ParseError):
            parse_line("2026-04-19T06:56:17Z [INFO] malformed bracket")


class ParseLogTests(unittest.TestCase):
    def test_framing_and_blank_lines_are_dropped(self) -> None:
        text = "\n".join(
            [
                "2026-03-10T06:18:01Z level=INFO service=readback_collector event=export_started "
                "target_count=1 mode=point_in_time",
                "",
                READBACK,
                "2026-09-30T11:51:01Z requestId=collector-4 level=DEBUG function=log_router "
                'message="instance=\\"collector-4\\" event=\\"export_started\\""',
                "2026-04-19T06:51:11Z "
                '{"severity":"DEBUG","logger":"log_router","service":"log_router","event":"export_started"}',
            ]
        )
        records = parse_log(text)
        self.assertEqual([record.fmt for record in records], [FMT_READBACK])

    def test_error_names_the_line_number(self) -> None:
        with self.assertRaisesRegex(ParseError, "line 2"):
            parse_log(READBACK + "\n2026-04-19T06:56:17Z garbage\n")


@needs_dataset
class CorpusTests(unittest.TestCase):
    def test_every_line_of_all_logs_parses_with_expected_format_counts(self) -> None:
        reader = DatasetReader(DATASET)
        paths = [entry.path for entry in reader.manifest() if entry.path.parent.name == "logs"]
        self.assertEqual(len(paths), CORPUS_FILES)
        lines = 0
        counts = collections.Counter()
        for path in paths:
            text = path.read_text(encoding="utf-8")
            lines += len([line for line in text.splitlines() if line.strip()])
            counts.update(record.fmt for record in parse_log(text))
        self.assertEqual(dict(counts), CORPUS_COUNTS)
        self.assertEqual(lines - sum(counts.values()), CORPUS_FRAMING)
        self.assertEqual(lines, CORPUS_LINES)


if __name__ == "__main__":
    unittest.main()
