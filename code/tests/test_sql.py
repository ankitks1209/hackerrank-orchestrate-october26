"""Tests for ghostaudit.evidence.sql (SPEC F1-F3, L12.2, I1).

Fixtures are SQL written in the dataset's own layout. Resource ids follow the
shapes the task file names (account_994, account_005, search_4725 ...); the
dataset-backed tests parse the real files and are skipped when `dataset/` is absent.
"""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from ghostaudit import config, evidence
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.base import ParseError, ParseOutput, select_parser
from ghostaudit.evidence.sql import SqlParser, account_pointer
from ghostaudit.model import ManifestEntry, ObsState, Observation

CAPTURED_AT = 1000
ENTRY = ManifestEntry("evidence_00", Path("evidence/databases/x.sql"), "origin", CAPTURED_AT, 0)
PARSER = SqlParser()

TOPOLOGY_DDL = (
    "CREATE TABLE %s (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, "
    "collection_name TEXT NOT NULL, record_json TEXT NOT NULL CHECK (json_valid(record_json)), "
    "updated_at TEXT NOT NULL);\n"
)
INVENTORY_DDL = """
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_exports (resource_id TEXT PRIMARY KEY, customer_reference TEXT, owner_email TEXT, owner_phone TEXT, object_key TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, connector_name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK (enabled IN (0,1)), last_delivery_status TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, archive_key TEXT NOT NULL, restore_allowed INTEGER NOT NULL CHECK (restore_allowed IN (0,1)), updated_at TEXT NOT NULL);
CREATE TABLE security_audit_records (resource_id TEXT PRIMARY KEY, subject_reference TEXT NOT NULL, event_code TEXT NOT NULL, retention_until TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
PROFILE_DDL = (
    "CREATE TABLE %s (resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, full_name TEXT NOT NULL, "
    "email TEXT NOT NULL, phone TEXT NOT NULL, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);\n"
)
SEARCH_DDL = (
    "CREATE TABLE search_documents_primary (resource_id TEXT PRIMARY KEY, display_name TEXT, "
    "email TEXT, source_resource_id TEXT, indexed_at TEXT);\n"
)
HEADER = "-- Ghost Data Still Exists: point-in-time database snapshot\n-- Dialect: SQLite-compatible SQL\n"
AUDIT_SEAL = "sha256:" + "0" * 64


def topology_row(table: str, rid: str, system: str, collection: str, record: Dict[str, Any]) -> str:
    payload = json.dumps(dict(record, resource_id=rid)).replace("'", "''")
    return "INSERT INTO \"%s\" VALUES('%s','%s','%s','%s','2026-09-21T10:00:00Z');\n" % (
        table, rid, system, collection, payload,
    )


def topology(tables: Dict[str, List[str]]) -> bytes:
    """A topology snapshot: `tables` maps each table name to its INSERT statements."""
    parts = [HEADER, "BEGIN TRANSACTION;\n"]
    for name in sorted(tables):
        parts.append(TOPOLOGY_DDL % name)
        parts.extend(tables[name])
    parts.append("COMMIT;\n")
    return "".join(parts).encode("utf-8")


def parse(sql: bytes) -> ParseOutput:
    return PARSER.parse(ENTRY, sql)


def observation(output: ParseOutput, resource_id: str) -> Observation:
    found = [o for o in output.observations if o.resource_id == resource_id]
    assert len(found) == 1, "expected one observation for %s, got %d" % (resource_id, len(found))
    return found[0]


class DetectTests(unittest.TestCase):
    def test_header_and_bare_statements_are_claimed(self) -> None:
        self.assertTrue(PARSER.detect(ENTRY, HEADER.encode()))
        self.assertTrue(PARSER.detect(ENTRY, b"PRAGMA foreign_keys=ON;\nBEGIN TRANSACTION;\n"))

    def test_json_log_and_text_are_not_claimed(self) -> None:
        for head in (b'{"records": []}', b"2026-09-21T10:00:00Z level=INFO event=x", b"- 2026-09-21 | a | b"):
            self.assertFalse(PARSER.detect(ENTRY, head))

    def test_registry_selects_sql_for_a_sql_head(self) -> None:
        self.assertIsInstance(select_parser(ENTRY, HEADER.encode(), evidence.REGISTRY), SqlParser)


class TopologyTests(unittest.TestCase):
    def build(self, **tables: List[str]) -> ParseOutput:
        return parse(topology(tables))

    def test_row_only_in_read_replica_is_present_with_replica_locator(self) -> None:
        drift = topology_row(
            "customer_data_read_replica", "account_994", "account_service", "customer_profiles",
            {"customer_reference": "user_53", "email": "diya.k4436@outlook.com", "phone": "+91 98765 43210"},
        )
        output = self.build(customer_data_primary=[], customer_data_read_replica=[drift])
        found = observation(output, "account_994")
        self.assertEqual((found.state, found.category), (ObsState.PRESENT, "USER_PROFILE"))
        self.assertEqual(found.locator, "customer_data_read_replica")
        self.assertEqual(found.subject_keys, frozenset({"e:diya.k4436@outlook.com", "u:user_53", "p:919876543210"}))
        self.assertEqual((found.captured_at, found.entry_time, found.system_id), (CAPTURED_AT, CAPTURED_AT, "account_service"))

    def test_row_held_by_one_regional_replica_only_is_present(self) -> None:
        row = topology_row("customer_data_replica_eu_west", "account_6539", "account_service", "customer_profiles", {})
        output = self.build(
            customer_data_primary=[],
            customer_data_replica_ap_south=[],
            customer_data_replica_eu_west=[row],
        )
        self.assertEqual(observation(output, "account_6539").locator, "customer_data_replica_eu_west")

    def test_row_in_every_table_is_one_observation_naming_all_tables(self) -> None:
        sql = {
            name: [topology_row(name, "search_1007", "search_service", "customer_search_documents",
                                {"document": {"email": "diya.k4436@outlook.com", "customer_reference": "user_53"}})]
            for name in ("customer_data_primary", "customer_data_read_replica")
        }
        found = observation(parse(topology(sql)), "search_1007")
        self.assertEqual(found.locator, "customer_data_primary,customer_data_read_replica")
        self.assertEqual(found.subject_keys, frozenset({"e:diya.k4436@outlook.com", "u:user_53"}))

    def test_account_rows_make_a_cite_only_account_scope_over_every_table(self) -> None:
        primary = topology_row("customer_data_primary", "account_1", "account_service", "customer_profiles", {})
        replica = topology_row("customer_data_read_replica", "account_2", "account_service", "customer_profiles", {})
        search = topology_row("customer_data_primary", "search_9", "search_service", "customer_search_documents", {})
        output = self.build(customer_data_primary=[primary, search], customer_data_read_replica=[replica])
        self.assertEqual(
            [(s.system_id, s.present_ids, s.cite_only) for s in output.scopes],
            [("account_service", frozenset({"account_1", "account_2"}), True)],
        )

    def test_no_account_row_means_no_scope(self) -> None:
        search = topology_row("customer_data_primary", "search_9", "search_service", "customer_search_documents", {})
        self.assertEqual(self.build(customer_data_primary=[search]).scopes, ())
        self.assertEqual(self.build(customer_data_primary=[]).scopes, ())

    def test_jr_decoy_keeps_its_own_key(self) -> None:
        decoy = topology_row(
            "customer_data_primary", "search_4725", "search_service", "customer_search_documents",
            {"document": {"display_name": None, "email": "hannah.carter.jr@outlook.com", "customer_reference": None}},
        )
        found = observation(self.build(customer_data_primary=[decoy]), "search_4725")
        self.assertEqual(found.subject_keys, frozenset({"e:hannah.carter.jr@outlook.com"}))

    def test_state_rules_per_collection(self) -> None:
        def row(rid: str, system: str, collection: str, **record: Any) -> str:
            return topology_row("customer_data_primary", rid, system, collection, record)

        rows = [
            row("analytics_1", "analytics_platform", "customer_analytics_reports",
                user_id=None, email=None, phone=None, email_hash=None),
            row("analytics_2", "analytics_platform", "customer_analytics_reports",
                user_id="user_51", email=None, phone=None, email_hash=None),
            row("support_1", "support_platform", "support_conversations", message_text="[REDACTED]"),
            row("support_2", "support_platform", "support_conversations", message_text="Send it to a@b.co please"),
            row("data_flow_1", "integration_service", "connector_configurations", enabled=False, subject_selector="user_51"),
            row("data_flow_2", "integration_service", "connector_configurations", enabled=True, subject_selector="A@B.CO"),
            row("backup_1", "backup_service", "backup_catalog", restore_allowed=False, subject_reference="user_51"),
            row("backup_2", "backup_service", "backup_catalog", restore_allowed=True, subject_reference="a@b.co"),
            row("tombstone_1", "identity_service", "deleted_customer_references",
                subject_reference="user_51", name=None, email=None, phone=None, email_hash=None),
            row("tombstone_2", "identity_service", "deleted_customer_references",
                subject_reference="user_51", name="A B", email=None, phone=None, email_hash=None),
            row("audit_record_1", "security_service", "security_audit_events",
                subject_reference="user_51", integrity_seal=AUDIT_SEAL),
            row("legal_hold_1", "legal_service", "retained_order_records", subject_reference="user_51"),
            row("support_3", "support_platform", "ticket_attachments", uploaded_by="a@b.co"),
            row("export_1", "export_service", "customer_export_jobs", owner_email="a@b.co"),
        ]
        output = self.build(customer_data_primary=rows)
        states = {o.resource_id: (o.category, o.state) for o in output.observations}
        self.assertEqual(states, {
            "analytics_1": ("ANALYTICS_PROFILE", ObsState.ANONYMIZED),
            "analytics_2": ("ANALYTICS_PROFILE", ObsState.EXPOSED),
            "support_1": ("SUPPORT_MESSAGE", ObsState.REDACTED),
            "support_2": ("SUPPORT_MESSAGE", ObsState.EXPOSED),
            "data_flow_1": ("DATA_FLOW", ObsState.DISABLED),
            "data_flow_2": ("DATA_FLOW", ObsState.ACTIVE),
            "backup_1": ("BACKUP_ARCHIVE", ObsState.BLOCKED),
            "backup_2": ("BACKUP_ARCHIVE", ObsState.ACTIVE),
            "tombstone_1": ("ACCOUNT_TOMBSTONE", ObsState.REDACTED),
            "tombstone_2": ("ACCOUNT_TOMBSTONE", ObsState.EXPOSED),
            "audit_record_1": ("SECURITY_AUDIT_LOG", ObsState.PRESENT),
            "legal_hold_1": ("LEGAL_HOLD_RECORD", ObsState.PRESENT),
            "support_3": ("SUPPORT_ATTACHMENT", ObsState.PRESENT),
            "export_1": ("USER_EXPORT", ObsState.PRESENT),
        })
        self.assertEqual(observation(output, "support_2").subject_keys, frozenset({"e:a@b.co"}))
        self.assertEqual(observation(output, "data_flow_2").subject_keys, frozenset({"e:a@b.co"}))
        self.assertEqual(observation(output, "audit_record_1").subject_keys, frozenset({"u:user_51"}))
        self.assertEqual(output.scopes, ())

    def test_unknown_collection_is_a_parse_error(self) -> None:
        row = topology_row("customer_data_primary", "x_1", "x_service", "mystery", {})
        with self.assertRaisesRegex(ParseError, "unknown collection"):
            self.build(customer_data_primary=[row])

    def test_output_order_is_by_resource_id_and_repeatable(self) -> None:
        rows = [
            topology_row("customer_data_primary", rid, "search_service", "customer_search_documents", {})
            for rid in ("search_9", "search_2", "search_5")
        ]
        first = self.build(customer_data_primary=rows)
        self.assertEqual([o.resource_id for o in first.observations], ["search_2", "search_5", "search_9"])
        self.assertEqual(first, self.build(customer_data_primary=rows))


def inventory(scopes: List[str], inserts: List[str]) -> bytes:
    scope_rows = ["INSERT INTO snapshot_scope VALUES ('%s', '2026-09-05T07:18:01Z');" % s for s in scopes]
    return ("PRAGMA foreign_keys=ON;\nBEGIN TRANSACTION;\n" + INVENTORY_DDL + "\n".join(scope_rows + inserts)
            + "\nCOMMIT;\n-- snapshot_completed_at=2026-09-05T07:18:01Z\n").encode("utf-8")


class InventoryTests(unittest.TestCase):
    def test_scope_assertion_per_system_with_its_rows(self) -> None:
        output = parse(inventory(
            ["account_service", "search_service", "export_service"],
            [
                "INSERT INTO customer_profiles VALUES ('account_9079', NULL, NULL, 'Rafael.R9464@outlook.com', NULL, NULL, 'DELETION_PENDING', '2026-09-16T08:22:10Z');",
                "INSERT INTO customer_search_documents VALUES ('search_2568', NULL, NULL, 'ishaan.iyer@outlook.com', NULL, NULL, 'customer_directory_v3', '2026-09-16T08:20:22Z');",
            ],
        ))
        scopes = {s.system_id: (s.present_ids, s.file_id, s.captured_at) for s in output.scopes}
        self.assertEqual(scopes, {
            "account_service": (frozenset({"account_9079"}), "evidence_00", CAPTURED_AT),
            "export_service": (frozenset(), "evidence_00", CAPTURED_AT),
            "search_service": (frozenset({"search_2568"}), "evidence_00", CAPTURED_AT),
        })
        pending = observation(output, "account_9079")
        self.assertEqual((pending.state, pending.subject_keys), (ObsState.PRESENT, frozenset({"e:rafael.r9464@outlook.com"})))

    def test_scope_with_no_rows_yields_one_empty_assertion(self) -> None:
        output = parse(inventory(["account_service"], []))
        self.assertEqual(output.observations, ())
        self.assertEqual([(s.system_id, s.present_ids) for s in output.scopes], [("account_service", frozenset())])

    def test_system_outside_the_scope_has_no_assertion(self) -> None:
        output = parse(inventory(["account_service", "backup_service"], []))
        self.assertNotIn("export_service", {s.system_id for s in output.scopes})

    def test_scope_system_without_a_table_is_noted_not_asserted(self) -> None:
        output = parse(inventory(["account_service", "legal_service"], []))
        self.assertEqual([s.system_id for s in output.scopes], ["account_service"])
        self.assertEqual(len(output.notes), 1)
        self.assertIn("legal_service", output.notes[0])

    def test_typed_tables_map_to_state(self) -> None:
        output = parse(inventory([], [
            "INSERT INTO customer_analytics_profiles VALUES ('analytics_1', NULL, NULL, NULL, NULL, 'general_shopper', '2026-09-16T06:15:41Z');",
            "INSERT INTO customer_analytics_profiles VALUES ('analytics_2', NULL, 'a@b.co', NULL, NULL, 'general_shopper', '2026-09-16T06:15:41Z');",
            "INSERT INTO support_records VALUES ('support_1', NULL, NULL, 'a@b.co', NULL, 'Customer asked.', '2026-09-16T06:07:44Z');",
            "INSERT INTO support_records VALUES ('support_2', 'user_62', NULL, NULL, NULL, 'Customer asked.', '2026-09-16T07:51:34Z');",
            "INSERT INTO connector_subscriptions VALUES ('data_flow_1', NULL, 'a@b.co', 'customer_events_connector', '1', 'delivered', '2026-09-16T07:04:46Z');",
            "INSERT INTO connector_subscriptions VALUES ('data_flow_2', 'user_62', NULL, 'customer_events_connector', '0', 'stopped', '2026-09-16T06:26:33Z');",
            "INSERT INTO backup_restore_entries VALUES ('backup_1', NULL, 'a@b.co', 'archive/b.tar.zst', '1', '2026-09-16T07:59:54Z');",
            "INSERT INTO backup_restore_entries VALUES ('backup_2', 'user_62', NULL, 'archive/c.tar.zst', '0', '2026-09-16T07:33:52Z');",
            "INSERT INTO customer_exports VALUES ('export_1', NULL, 'a@b.co', NULL, 'exports/export_1/customer_data.zip', '2026-09-16T08:14:31Z');",
            "INSERT INTO security_audit_records VALUES ('audit_record_1', 'user_68', 'ACCOUNT_DELETION_RECORDED', '2031-12-31T23:59:59Z', '2026-09-16T06:06:38Z');",
        ]))
        states = {o.resource_id: (o.category, o.state) for o in output.observations}
        self.assertEqual(states, {
            "analytics_1": ("ANALYTICS_PROFILE", ObsState.ANONYMIZED),
            "analytics_2": ("ANALYTICS_PROFILE", ObsState.EXPOSED),
            "support_1": (None, ObsState.EXPOSED),
            "support_2": (None, ObsState.REDACTED),
            "data_flow_1": ("DATA_FLOW", ObsState.ACTIVE),
            "data_flow_2": ("DATA_FLOW", ObsState.DISABLED),
            "backup_1": ("BACKUP_ARCHIVE", ObsState.ACTIVE),
            "backup_2": ("BACKUP_ARCHIVE", ObsState.BLOCKED),
            "export_1": ("USER_EXPORT", ObsState.PRESENT),
            "audit_record_1": ("SECURITY_AUDIT_LOG", ObsState.PRESENT),
        })
        self.assertEqual(observation(output, "backup_2").subject_keys, frozenset({"u:user_62"}))
        self.assertEqual(observation(output, "audit_record_1").locator, "security_audit_records")


class SpecialTests(unittest.TestCase):
    PROFILES = (
        HEADER + "BEGIN TRANSACTION;\n" + PROFILE_DDL % "customer_profiles_failover_replica"
        + "INSERT INTO customer_profiles_failover_replica VALUES('account_005','user_05','Leila Haddad','leila.haddad@yahoo.com','+212 6 48 27 15 93','ACTIVE','2026-09-02T22:45:00Z');\n"
        + "INSERT INTO customer_profiles_failover_replica VALUES('account_8741','user_8741','Karim El-Masri','karim.elmasri@gmail.com','+971 50 731 6284','ACTIVE','2026-09-02T22:45:00Z');\n"
        + PROFILE_DDL % "customer_profiles_primary"
        + "INSERT INTO customer_profiles_primary VALUES('account_8741','user_8741','Karim El-Masri','karim.elmasri@gmail.com','+971 50 731 6284','ACTIVE','2026-09-02T22:45:00Z');\n"
        + "COMMIT;\n"
    ).encode()
    SEARCH = (
        HEADER + "BEGIN TRANSACTION;\n" + SEARCH_DDL
        + "INSERT INTO search_documents_primary VALUES('search_001','Jonas Berg','jonas.berg@outlook.com','account_006','2026-09-09T22:12:00Z');\n"
        + "INSERT INTO search_documents_primary VALUES('search_8814','Jonas Berglund','jonas.berglund@outlook.com','account_8814','2026-09-09T22:13:00Z');\n"
        + "COMMIT;\n"
    ).encode()

    def test_failover_only_profile_is_present(self) -> None:
        found = observation(parse(self.PROFILES), "account_005")
        self.assertEqual((found.state, found.locator), (ObsState.PRESENT, "customer_profiles_failover_replica"))
        self.assertIn("u:user_05", found.subject_keys)
        shared = observation(parse(self.PROFILES), "account_8741")
        self.assertEqual(shared.locator, "customer_profiles_failover_replica,customer_profiles_primary")

    def test_profile_pair_is_an_account_scope_listing_every_row(self) -> None:
        scopes = parse(self.PROFILES).scopes
        self.assertEqual([(s.system_id, s.present_ids) for s in scopes],
                         [("account_service", frozenset({"account_005", "account_8741"}))])

    def test_search_document_keeps_its_account_pointer(self) -> None:
        output = parse(self.SEARCH)
        found = observation(output, "search_001")
        self.assertEqual((found.system_id, found.state, found.subject_keys),
                         ("search_service", ObsState.PRESENT, frozenset({"e:jonas.berg@outlook.com"})))
        self.assertEqual(account_pointer(found.locator), "account_006")
        self.assertEqual(output.scopes, ())

    def test_locator_without_pointer_has_none(self) -> None:
        self.assertIsNone(account_pointer("customer_data_primary"))


class ErrorTests(unittest.TestCase):
    def test_invalid_sql_is_a_parse_error(self) -> None:
        with self.assertRaisesRegex(ParseError, "evidence_00"):
            parse(b"CREATE TABLE ((;")

    def test_undecodable_bytes_are_a_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            parse(b"\xff\xfe CREATE TABLE a (b);")

    def test_unrecognised_schema_is_a_parse_error(self) -> None:
        with self.assertRaisesRegex(ParseError, "no recognised SQL schema"):
            parse(b"CREATE TABLE other (resource_id TEXT);")

    def test_unknown_special_table_is_a_parse_error(self) -> None:
        sql = SEARCH_DDL + "CREATE TABLE stray (resource_id TEXT);"
        with self.assertRaisesRegex(ParseError, "stray"):
            parse(sql.encode())

    def test_row_missing_a_column_is_a_parse_error(self) -> None:
        sql = "CREATE TABLE customer_data_primary (resource_id TEXT); INSERT INTO customer_data_primary VALUES ('a_1');"
        with self.assertRaisesRegex(ParseError, "malformed"):
            parse(sql.encode())


DATASET = config.Config().dataset_dir


@unittest.skipUnless((DATASET / "evidence_files.csv").exists(), "dataset/ is not present")
class DatasetTests(unittest.TestCase):
    """Acceptance numbers against the real participant files."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(DATASET)
        cls.outputs: Dict[str, ParseOutput] = {}
        for entry in reader.manifest():
            if entry.path.suffix == ".sql":
                cls.outputs[entry.file_id] = PARSER.parse(entry, entry.path.read_bytes())

    def state_of(self, file_id: str, resource_id: str) -> Optional[ObsState]:
        found = [o.state for o in self.outputs[file_id].observations if o.resource_id == resource_id]
        return found[0] if found else None

    def test_all_24_files_parse_into_the_three_families(self) -> None:
        self.assertEqual(len(self.outputs), 24)
        deciding = [fid for fid, out in self.outputs.items() if any(not s.cite_only for s in out.scopes)]
        self.assertEqual(len(deciding), 12)  # 11 inventory files + the account failover file
        cite_only = [fid for fid, out in self.outputs.items() if any(s.cite_only for s in out.scopes)]
        self.assertEqual(len(cite_only), 10)  # topology files that list account rows
        self.assertEqual(set(deciding) & set(cite_only), set())

    def test_drift_is_present(self) -> None:
        self.assertEqual(self.state_of("evidence_05", "account_994"), ObsState.PRESENT)
        self.assertEqual(self.state_of("evidence_54", "account_005"), ObsState.PRESENT)

    def test_account_failover_file_proves_absence_of_unlisted_accounts(self) -> None:
        scope = self.outputs["evidence_54"].scopes[0]
        self.assertEqual(scope.system_id, "account_service")
        self.assertIn("account_005", scope.present_ids)
        self.assertNotIn("account_001", scope.present_ids)

    def test_empty_inventory_yields_one_scope_without_ids(self) -> None:
        output = self.outputs["evidence_90"]
        self.assertEqual([(s.system_id, s.present_ids) for s in output.scopes], [("account_service", frozenset())])
        self.assertEqual(output.observations, ())

    def test_missing_scope_systems(self) -> None:
        systems = {fid: {s.system_id for s in self.outputs[fid].scopes} for fid in ("evidence_63", "evidence_72", "evidence_78")}
        self.assertNotIn("export_service", systems["evidence_63"])
        self.assertNotIn("export_service", systems["evidence_72"])
        self.assertNotIn("backup_service", systems["evidence_78"])
        self.assertIn("backup_service", systems["evidence_63"])

    def test_search_pointer_in_special_file(self) -> None:
        found = [o for o in self.outputs["evidence_57"].observations if o.resource_id == "search_001"]
        self.assertEqual(account_pointer(found[0].locator), "account_006")

    def test_anonymized_analytics_and_clean_tombstones_exist(self) -> None:
        counts = Counter((o.category, o.state) for out in self.outputs.values() for o in out.observations)
        self.assertGreater(counts[("ANALYTICS_PROFILE", ObsState.ANONYMIZED)], 0)
        self.assertEqual(counts[("ACCOUNT_TOMBSTONE", ObsState.REDACTED)], 4)
        self.assertEqual(counts[("ACCOUNT_TOMBSTONE", ObsState.EXPOSED)], 4)

    def test_jr_decoy_does_not_carry_the_real_email_key(self) -> None:
        found = [o for o in self.outputs["evidence_47"].observations if o.resource_id == "search_4725"]
        self.assertEqual(found[0].subject_keys, frozenset({"e:hannah.carter.jr@outlook.com"}))


if __name__ == "__main__":
    unittest.main()
