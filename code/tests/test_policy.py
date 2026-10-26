"""Tests for ghostaudit.policy (SPEC 6).

Expected tables are written out literally from SPEC 6 and AGENTS 6.4, independent of
the code. The rules file test reads the participant deletion_rules.csv.
"""
from __future__ import annotations

import unittest

from ghostaudit import config
from ghostaudit.dataset import DatasetReader, Rule
from ghostaudit.model import ObsState, Treatment
from ghostaudit.policy import PolicyEngine, PolicyError, system_for
from tests.dataset_guard import needs_dataset

# SPEC 6 prefix table, written out literally.
PREFIX_CASES = [
    ("account_", "account_service"),
    ("search_", "search_service"),
    ("analytics_", "analytics_platform"),
    ("support_", "support_platform"),
    ("export_", "export_service"),
    ("data_flow_", "integration_service"),
    ("backup_", "backup_service"),
    ("audit_record_", "security_service"),
    ("legal_hold_", "legal_service"),
    ("tombstone_", "identity_service"),
    ("object_", "object_storage"),
    ("marketing_", "marketing_platform"),
]

# The 15 deletion_rules.csv rows as (category, required_action), written out literally.
RULES = [
    ("USER_PROFILE", "DELETE"),
    ("SECONDARY_IDENTIFIER", "DELETE"),
    ("SEARCH_INDEX_ENTRY", "DELETE"),
    ("CACHE_ENTRY", "DELETE"),
    ("SUPPORT_MESSAGE", "REDACT"),
    ("SUPPORT_ATTACHMENT", "DELETE"),
    ("ANALYTICS_PROFILE", "ANONYMIZE"),
    ("PRODUCT_TELEMETRY", "ANONYMIZE"),
    ("USER_EXPORT", "DELETE"),
    ("MARKETING_PROFILE", "DELETE"),
    ("EMAIL_DELIVERY_LOG", "REDACT"),
    ("SECURITY_AUDIT_LOG", "RETAIN"),
    ("LEGAL_HOLD_RECORD", "RETAIN"),
    ("BACKUP_ARCHIVE", "RETAIN"),
    ("ACCOUNT_TOMBSTONE", "REDACT"),
]

# Required treatment per category: SPEC 6 table, where rule 14 (BACKUP_ARCHIVE) is RESTORE.
RULE_TREATMENTS = {
    "USER_PROFILE": Treatment.DELETE,
    "SECONDARY_IDENTIFIER": Treatment.DELETE,
    "SEARCH_INDEX_ENTRY": Treatment.DELETE,
    "CACHE_ENTRY": Treatment.DELETE,
    "SUPPORT_MESSAGE": Treatment.REDACT,
    "SUPPORT_ATTACHMENT": Treatment.DELETE,
    "ANALYTICS_PROFILE": Treatment.ANONYMIZE,
    "PRODUCT_TELEMETRY": Treatment.ANONYMIZE,
    "USER_EXPORT": Treatment.DELETE,
    "MARKETING_PROFILE": Treatment.DELETE,
    "EMAIL_DELIVERY_LOG": Treatment.REDACT,
    "SECURITY_AUDIT_LOG": Treatment.RETAIN,
    "LEGAL_HOLD_RECORD": Treatment.RETAIN,
    "BACKUP_ARCHIVE": Treatment.RESTORE,
    "ACCOUNT_TOMBSTONE": Treatment.REDACT,
}

# AGENTS 6.4 verification state for each treatment, written out literally.
COMPLIANT_STATE = {
    Treatment.DELETE: ObsState.ABSENT,
    Treatment.REDACT: ObsState.REDACTED,
    Treatment.ANONYMIZE: ObsState.ANONYMIZED,
    Treatment.FLOW: ObsState.DISABLED,
    Treatment.RESTORE: ObsState.BLOCKED,
    Treatment.RETAIN: ObsState.PRESENT,
}

# Default treatment for each system when a row has no category and no event_type.
SYSTEM_DEFAULTS = {
    "account_service": Treatment.DELETE,
    "search_service": Treatment.DELETE,
    "analytics_platform": Treatment.ANONYMIZE,
    "support_platform": Treatment.REDACT,
    "export_service": Treatment.DELETE,
    "integration_service": Treatment.FLOW,
    "backup_service": Treatment.RESTORE,
    "security_service": Treatment.RETAIN,
    "legal_service": Treatment.RETAIN,
    "identity_service": Treatment.REDACT,
    "object_storage": Treatment.DELETE,
    "marketing_platform": Treatment.DELETE,
}


def _rule(category: str, action: str, index: int = 1) -> Rule:
    return Rule("rule_%02d" % index, category, "Always", action)


def _engine() -> PolicyEngine:
    return PolicyEngine.from_rules(
        _rule(category, action, index) for index, (category, action) in enumerate(RULES, start=1)
    )


@needs_dataset
class RulesFileTest(unittest.TestCase):
    """All 15 rows of the participant deletion_rules.csv load and map as SPEC 6 states."""

    def test_fifteen_rules_map_to_expected_treatments(self) -> None:
        rules = DatasetReader(config.REPO_ROOT / "dataset").rules()
        engine = PolicyEngine.from_rules(rules)
        self.assertEqual(len(rules), 15)
        for category, expected in RULE_TREATMENTS.items():
            self.assertIs(engine.treatment("unused_service", category), expected, category)


class PrefixTableTest(unittest.TestCase):
    """SYSTEM_BY_PREFIX covers the 12 prefixes of SPEC 6."""

    def test_all_twelve_prefixes(self) -> None:
        self.assertEqual(len(PREFIX_CASES), 12)
        for prefix, system in PREFIX_CASES:
            with self.subTest(prefix=prefix):
                self.assertEqual(system_for(prefix + "001"), system)

    def test_unknown_prefix_has_no_system(self) -> None:
        for resource_id in ("ledger_001", "widget_001", "subject_01", ""):
            with self.subTest(resource_id=resource_id):
                self.assertIsNone(system_for(resource_id))

    def test_system_default_treatments(self) -> None:
        engine = _engine()
        self.assertEqual(set(SYSTEM_DEFAULTS), {system for _prefix, system in PREFIX_CASES})
        for system, expected in SYSTEM_DEFAULTS.items():
            with self.subTest(system=system):
                self.assertIs(engine.treatment(system, None), expected)


class TreatmentPrecedenceTest(unittest.TestCase):
    """Evidence category wins, then the system default."""

    def test_message_vs_attachment_by_category(self) -> None:
        engine = _engine()
        self.assertIs(engine.treatment("support_platform", "SUPPORT_MESSAGE"), Treatment.REDACT)
        self.assertIs(engine.treatment("support_platform", "SUPPORT_ATTACHMENT"), Treatment.DELETE)

    def test_profile_vs_secondary_contact(self) -> None:
        engine = _engine()
        self.assertIs(engine.treatment("analytics_platform", "ANALYTICS_PROFILE"), Treatment.ANONYMIZE)
        self.assertIs(engine.treatment("analytics_platform", "SECONDARY_IDENTIFIER"), Treatment.DELETE)

    def test_unknown_category_falls_through_to_system_default(self) -> None:
        engine = _engine()
        self.assertIs(engine.treatment("search_service", "NOT_A_CATEGORY"), Treatment.DELETE)

    def test_connector_flow_and_restore_defaults(self) -> None:
        engine = _engine()
        self.assertIs(engine.treatment("integration_service", "DATA_FLOW"), Treatment.FLOW)
        self.assertIs(engine.treatment("backup_service", None), Treatment.RESTORE)
        self.assertIs(engine.treatment("security_service", None), Treatment.RETAIN)


class IsCompliantTest(unittest.TestCase):
    """Truth table: only the AGENTS 6.4 verification state is compliant."""

    def test_truth_table(self) -> None:
        for treatment, required in COMPLIANT_STATE.items():
            for state in ObsState:
                with self.subTest(treatment=treatment, state=state):
                    expected = state is required
                    self.assertIs(PolicyEngine.is_compliant(treatment, state), expected)


class RuleErrorTest(unittest.TestCase):
    """Bad rule rows and unknown systems raise PolicyError instead of guessing."""

    def test_unknown_action_is_refused(self) -> None:
        with self.assertRaises(PolicyError):
            PolicyEngine.from_rules([_rule("USER_PROFILE", "SHRED")])

    def test_duplicate_category_is_refused(self) -> None:
        with self.assertRaises(PolicyError):
            PolicyEngine.from_rules([_rule("USER_PROFILE", "DELETE"), _rule("USER_PROFILE", "REDACT", 2)])

    def test_unknown_system_is_refused(self) -> None:
        with self.assertRaises(PolicyError):
            _engine().treatment("cache_service", None)

    def test_missing_default_category_is_refused(self) -> None:
        engine = PolicyEngine.from_rules([_rule("USER_PROFILE", "DELETE")])
        with self.assertRaises(PolicyError):
            engine.treatment("search_service", None)


if __name__ == "__main__":
    unittest.main()
