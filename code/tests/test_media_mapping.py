"""Tests for ghostaudit.evidence.media (SPEC F10, Q1, Q7).

The MediaFacts fixtures are transcriptions of what the 15 images and PDFs show, never
of any answer file. LINK rows are read from the real system_activity.csv.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ghostaudit.activity import classify_activity, classify_row
from ghostaudit.config import Config
from ghostaudit.dataset import ActivityRow, DatasetReader
from ghostaudit.evidence import media
from ghostaudit.evidence.media import STATE_RULES, map_facts
from ghostaudit.model import ActKind, ClassifiedActivity, ManifestEntry, MediaFacts, ObsState
from ghostaudit.timeutil import to_epoch
from tests.dataset_guard import needs_dataset

Record = Dict[str, Any]


def rec(
    display_id: str = "",
    hint: str = "",
    category: str = "",
    emails: Tuple[str, ...] = (),
    phones: Tuple[str, ...] = (),
    users: Tuple[str, ...] = (),
    **state: bool,
) -> Record:
    """One extracted record in the shape the extraction layer returns."""
    return {
        "display_id": display_id,
        "resource_hint": hint,
        "category": category,
        "emails": list(emails),
        "phones": list(phones),
        "user_refs": list(users),
        "state_facts": dict(state),
    }


# What each file shows; decoy rows (other customers, staff owners) are included where listed.
FILES: Dict[str, List[Record]] = {
    "evidence_04": [
        rec("account_5762", category="USER_PROFILE", emails=("haruka.s1838@zoho.com",),
            phones=("+81 90 7610 2507",), users=("user_11",), record_shown=True),
        rec("CS-8538", hint="support_9538"),
    ],
    "evidence_09": [
        rec("search_428", category="SEARCH_INDEX_ENTRY", emails=("g.silva76@gmail.com",),
            users=("user_13",), record_shown=True),
        rec("search_1874", category="SEARCH_INDEX_ENTRY", emails=("g.silva76.jr@gmail.com",),
            record_shown=True),
    ],
    "evidence_14": [
        rec("data_flow_1121", category="DATA_FLOW", emails=("jain.aditi@gmail.com",),
            connector_enabled=True, record_shown=True),
    ],
    "evidence_18": [
        rec("NST-2026-0718-1842", category="USER_EXPORT", emails=("ingrid.dahl@outlook.com",),
            users=("user_18",), record_shown=True),
    ],
    "evidence_19": [
        rec("analytics_7438", category="ANALYTICS_PROFILE", emails=("darwish.omar@icloud.com",),
            users=("user_20",), pii_fields_shown=True, record_shown=True),
    ],
    "evidence_23": [
        rec("export_1260", category="USER_EXPORT", emails=("ingrid.dahl@outlook.com",),
            record_shown=True),
        rec("export_1261", category="USER_EXPORT", emails=("marcus.lee@northstar.shop",),
            record_shown=True),
    ],
    "evidence_27": [
        rec("ORD-20264118", users=("user_08",), record_shown=True),
        rec("ORD-20264207", users=("user_12",), record_shown=True),
    ],
    "evidence_28": [
        rec("support_1034", category="SUPPORT_MESSAGE", emails=("kagyeman8947@fastmail.com",),
            pii_fields_shown=True, record_shown=True),
    ],
    "evidence_32": [
        rec("backup_9287", category="BACKUP_ARCHIVE", emails=("areed1433@gmail.com",),
            restore_blocked=False, record_shown=True),
    ],
    # Six signed events of user_03 in table order (checked by viewing the PNG); only
    # audit_record_003 has a LINK row. The screen repeats its subject filter on every row,
    # so the other five are tied to nobody.
    "evidence_37": [
        rec(record_id, category="SECURITY_AUDIT_LOG", users=("user_03",), record_shown=True)
        for record_id in ("audit_record_003", "audit_record_002", "audit_record_001",
                          "audit_record_006", "audit_record_005", "audit_record_004")
    ],
    "evidence_42": [
        rec("user_17", category="ACCOUNT_TOMBSTONE", users=("user_17",),
            only_stable_reference_shown=True),
    ],
    "evidence_46": [
        rec("delivery_confirmation_19.pdf", category="SUPPORT_ATTACHMENT", record_shown=True),
    ],
    "evidence_55": [
        rec("CJX-20260905-0630", hint="audit_record_003", category="SECURITY_AUDIT_LOG",
            users=("user_03",), record_shown=True),
    ],
    "evidence_58": [
        rec("CS-4827", hint="support_001", category="SUPPORT_ATTACHMENT",
            emails=("priya.raman@gmail.com",), phones=("+91 98765 73142",), record_shown=True),
    ],
    "evidence_60": [
        rec("marketing_001", category="MARKETING_PROFILE", emails=("sj.park@naver.com",),
            phones=("+82 10-5837-9451",), record_shown=True),
    ],
}

# SPEC F10 table (12 LINK targets) plus the two path (b) files: file -> (system, resource, state).
TARGETS: Dict[str, Tuple[str, str, ObsState]] = {
    "evidence_04": ("account_service", "account_5762", ObsState.PRESENT),
    "evidence_09": ("search_service", "search_428", ObsState.PRESENT),
    "evidence_14": ("integration_service", "data_flow_1121", ObsState.ACTIVE),
    "evidence_18": ("export_service", "export_1842", ObsState.PRESENT),
    "evidence_19": ("analytics_platform", "analytics_7438", ObsState.EXPOSED),
    "evidence_23": ("export_service", "export_1260", ObsState.PRESENT),
    "evidence_28": ("support_platform", "support_1034", ObsState.EXPOSED),
    "evidence_32": ("backup_service", "backup_9287", ObsState.ACTIVE),
    "evidence_37": ("security_service", "audit_record_003", ObsState.PRESENT),
    "evidence_42": ("identity_service", "tombstone_17", ObsState.REDACTED),
    "evidence_46": ("object_storage", "object_19", ObsState.PRESENT),
    "evidence_60": ("marketing_platform", "marketing_001", ObsState.PRESENT),
    "evidence_55": ("security_service", "audit_record_003", ObsState.PRESENT),
    "evidence_58": ("support_platform", "support_001", ObsState.PRESENT),
}
# Other listed records that validate by path (b) because they show a literal id and an
# identifier: decoys of other customers.
EXTRAS: Dict[str, Tuple[Tuple[str, str, ObsState], ...]] = {
    "evidence_09": (("search_service", "search_1874", ObsState.PRESENT),),
    "evidence_23": (("export_service", "export_1261", ObsState.PRESENT),),
}
LINK_FILE_COUNT = 12


def _synthetic_link(
    activity_id: str, system: str, resource: str, alias: str, email: str, user: str
) -> ClassifiedActivity:
    """A LINK row in the real wording of system_activity.csv."""
    details = "Data catalog linked %s (%s) to %s and %s." % (resource, alias, email, user)
    row = ActivityRow(
        activity_id, 0, "LINK_RESOURCE_IDENTITY", "data_catalog", system, resource,
        "SUCCESS", details,
    )
    return classify_row(row)


@needs_dataset
class MediaMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(Config().dataset_dir)
        cls.manifest = {entry.file_id: entry for entry in reader.manifest()}
        acts = classify_activity(reader.activity())
        cls.links = tuple(act for act in acts if act.kind is ActKind.LINK)
        cls.outputs = {
            file_id: map_facts(
                cls.manifest[file_id], MediaFacts(file_id, tuple(records)), cls.links
            )
            for file_id, records in FILES.items()
        }

    def mapped(self, file_id: str) -> Dict[str, Tuple[str, str, ObsState]]:
        return {
            obs.resource_id: (obs.system_id, obs.resource_id, obs.state)
            for obs in self.outputs[file_id].observations
        }

    def test_fixtures_cover_all_fifteen_media_files(self) -> None:
        self.assertEqual(len(FILES), 15)
        suffixes = {self.manifest[file_id].path.suffix for file_id in FILES}
        self.assertEqual(suffixes, {".png", ".pdf"})
        self.assertEqual(len(self.links), LINK_FILE_COUNT)

    def test_each_file_maps_to_its_target(self) -> None:
        for file_id, target in TARGETS.items():
            with self.subTest(file_id=file_id):
                expected = {target[1]: target}
                expected.update((extra[1], extra) for extra in EXTRAS.get(file_id, ()))
                self.assertEqual(self.mapped(file_id), expected)

    def test_legal_register_yields_no_observation(self) -> None:
        output = self.outputs["evidence_27"]
        self.assertEqual(output.observations, ())
        self.assertEqual(len(output.notes), len(FILES["evidence_27"]))

    def test_link_row_supplies_keys_and_manifest_supplies_time(self) -> None:
        obs = self.outputs["evidence_28"].observations[0]
        self.assertEqual(obs.subject_keys, frozenset({"e:kagyeman8947@fastmail.com", "u:user_22"}))
        self.assertEqual(obs.category, "SUPPORT_MESSAGE")
        entry = self.manifest["evidence_28"]
        self.assertEqual(
            (obs.file_id, obs.captured_at, obs.entry_time),
            ("evidence_28", entry.captured_at, entry.captured_at),
        )

    def test_path_b_keys_come_from_the_extracted_identifiers(self) -> None:
        support = self.outputs["evidence_58"].observations[0]
        self.assertEqual(support.category, "SUPPORT_ATTACHMENT")
        self.assertEqual(
            support.subject_keys, frozenset({"e:priya.raman@gmail.com", "p:919876573142"})
        )
        entry = self.manifest["evidence_55"]
        facts = MediaFacts("evidence_55", tuple(FILES["evidence_55"]))
        audit = map_facts(entry, facts, ()).observations[0]
        self.assertEqual(
            (audit.system_id, audit.resource_id, audit.subject_keys),
            ("security_service", "audit_record_003", frozenset({"u:user_03"})),
        )

    def test_retention_extract_also_joins_the_link_row_of_its_resource(self) -> None:
        # The LINK row of audit_record_003 matches by resource_id, so path (a) adds its email.
        audit = self.outputs["evidence_55"].observations[0]
        self.assertEqual(audit.subject_keys, frozenset({"u:user_03", "e:oliver-bennett@gmail.com"}))

    def test_decoy_keeps_its_own_near_duplicate_email(self) -> None:
        decoy = self.outputs["evidence_09"].observations[1]
        self.assertEqual(decoy.resource_id, "search_1874")
        self.assertEqual(decoy.subject_keys, frozenset({"e:g.silva76.jr@gmail.com"}))

    def test_display_only_reference_is_a_note_not_an_observation(self) -> None:
        output = self.outputs["evidence_04"]
        self.assertNotIn("support_9538", [obs.resource_id for obs in output.observations])
        self.assertEqual(
            output.notes,
            ("evidence_04:record[1]: reference support_9538 shown without identifier",),
        )

    def test_contradicting_identity_keeps_the_link_row(self) -> None:
        output = self.outputs["evidence_60"]
        obs = output.observations[0]
        self.assertEqual(obs.subject_keys, frozenset({"e:kwame-mensah@proton.me", "u:user_09"}))
        self.assertEqual(len(output.notes), 1)
        self.assertIn("contradicts LINK activity_4008", output.notes[0])

    def test_consistent_identity_adds_the_shown_phone(self) -> None:
        obs = self.outputs["evidence_04"].observations[0]
        self.assertEqual(
            obs.subject_keys, frozenset({"e:haruka.s1838@zoho.com", "u:user_11", "p:819076102507"})
        )

    def test_mapping_is_deterministic(self) -> None:
        entry = self.manifest["evidence_09"]
        facts = MediaFacts("evidence_09", tuple(FILES["evidence_09"]))
        first = map_facts(entry, facts, self.links)
        self.assertEqual(first, map_facts(entry, facts, reversed(self.links)))


class MismatchTests(unittest.TestCase):
    ENTRY = ManifestEntry(
        "evidence_x", Path("evidence/images/x.png"), "origin", to_epoch("2026-01-01T00:00:00Z"), 0
    )
    LINKS = (
        _synthetic_link("activity_a", "export_service", "export_1", "NST-1", "a@x.org", "user_1"),
        _synthetic_link("activity_b", "export_service", "export_2", "NST-2", "b@x.org", "user_2"),
    )

    def run_records(self, *records: Record, links: Tuple[ClassifiedActivity, ...] = LINKS):
        return map_facts(self.ENTRY, MediaFacts("evidence_x", records), links)

    def test_alias_mismatch_yields_a_note_only(self) -> None:
        output = self.run_records(rec("NST-9", category="USER_EXPORT", record_shown=True))
        self.assertEqual(output.observations, ())
        self.assertEqual(len(output.notes), 1)

    def test_label_naming_another_resource_is_dropped(self) -> None:
        output = self.run_records(rec("NST-1", hint="export_9", record_shown=True))
        self.assertEqual(output.observations, ())
        self.assertIn("differs from LINK activity_a", output.notes[0])

    def test_labels_matching_two_links_are_ambiguous(self) -> None:
        output = self.run_records(rec("NST-1", hint="export_2", record_shown=True))
        self.assertEqual(output.observations, ())
        self.assertIn("ambiguous", output.notes[0])

    def test_literal_id_without_identifier_is_a_reference(self) -> None:
        output = self.run_records(rec("support_77", category="SUPPORT_MESSAGE", record_shown=True))
        self.assertEqual(output.observations, ())
        self.assertIn("reference support_77", output.notes[0])

    def test_unknown_prefix_is_not_a_resource_id(self) -> None:
        output = self.run_records(rec("ticket_77", emails=("c@example.org",), record_shown=True))
        self.assertEqual(output.observations, ())

    def test_bare_user_reference_is_not_enough_in_a_file_with_a_link_row(self) -> None:
        output = self.run_records(
            rec("NST-1", record_shown=True),
            rec("audit_record_8", users=("user_1",), record_shown=True),
            rec("audit_record_9", emails=("a@x.org",), record_shown=True),
        )
        self.assertEqual([obs.resource_id for obs in output.observations], ["export_1", "audit_record_9"])
        self.assertIn("no LINK row ties it", output.notes[0])

    def test_bare_user_reference_is_enough_in_a_file_without_a_link_row(self) -> None:
        output = self.run_records(rec("audit_record_8", users=("user_1",), record_shown=True))
        self.assertEqual([obs.resource_id for obs in output.observations], ["audit_record_8"])

    def test_link_without_a_readable_state_is_a_reference(self) -> None:
        output = self.run_records(rec("NST-1", state_unknown=True))
        self.assertEqual(output.observations, ())
        self.assertIn("reference export_1 shown without state", output.notes[0])

    def test_duplicate_record_for_one_resource_keeps_the_first(self) -> None:
        output = self.run_records(
            rec("NST-1", record_shown=True), rec("export_1", pii_fields_shown=True)
        )
        self.assertEqual([obs.state for obs in output.observations], [ObsState.PRESENT])
        self.assertIn("duplicate", output.notes[0])

    def test_only_link_kind_rows_join(self) -> None:
        policy_row = classify_row(
            ActivityRow(
                "activity_p", 0, "DELETE_RECORD", "deletion_worker", "export_service", "export_5",
                "SUCCESS", "Policy action completed for export_5.",
            )
        )
        output = self.run_records(rec("export_5", record_shown=True), links=(policy_row,))
        self.assertEqual(output.observations, ())


class StateRuleTests(unittest.TestCase):
    ENTRY = MismatchTests.ENTRY

    def state_for(self, **facts: bool):
        record = rec("export_1", emails=("a@example.org",), **facts)
        output = map_facts(self.ENTRY, MediaFacts("evidence_x", (record,)), ())
        return output.observations[0].state if output.observations else None

    def test_every_rule_fires_on_its_own_fact(self) -> None:
        for fact, value, state in STATE_RULES:
            with self.subTest(fact=fact, value=value):
                self.assertEqual(self.state_for(**{fact: value}), state)

    def test_specific_state_wins_over_record_shown(self) -> None:
        self.assertEqual(self.state_for(record_shown=True, restore_blocked=False), ObsState.ACTIVE)
        self.assertEqual(self.state_for(record_shown=True, restore_blocked=True), ObsState.BLOCKED)
        self.assertEqual(self.state_for(record_shown=True, pii_fields_shown=True), ObsState.EXPOSED)

    def test_negative_or_missing_facts_give_no_state(self) -> None:
        self.assertIsNone(self.state_for(record_shown=False))
        self.assertIsNone(self.state_for())


class PurityTests(unittest.TestCase):
    def test_module_never_imports_the_llm_layer(self) -> None:
        source = Path(media.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ghostaudit.llm", source)
        self.assertNotIn("anthropic", source)


if __name__ == "__main__":
    unittest.main()
