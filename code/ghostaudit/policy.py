"""PolicyEngine: deletion_rules.csv as data, and the required treatment per resource (SPEC 6).

Implements SPEC 6: each deletion_rules.csv category maps to a treatment. A resource's
treatment comes from its evidence category first, then the default category of its
system (callers that hold an activity row apply its event_type themselves, see
activity.TREATMENT_BY_EVENT). Compliance is
the verification state of AGENTS 6.4 for that treatment (model.TREATMENT_OPS).
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

from ghostaudit.dataset import Rule
from ghostaudit.model import TREATMENT_OPS, ObsState, Treatment, state_of

# SPEC 6 table: resource-id prefix -> owning system.
SYSTEM_BY_PREFIX: Dict[str, str] = {
    "account_": "account_service",
    "search_": "search_service",
    "analytics_": "analytics_platform",
    "support_": "support_platform",
    "export_": "export_service",
    "data_flow_": "integration_service",
    "backup_": "backup_service",
    "audit_record_": "security_service",
    "legal_hold_": "legal_service",
    "tombstone_": "identity_service",
    "object_": "object_storage",
    "marketing_": "marketing_platform",
}

# Category used when neither evidence nor activity names a treatment. Support rows
# default to SUPPORT_MESSAGE: it is the common kind (activity: 163 REDACT_RECORD rows
# against 29 DELETE_RECORD rows on support_platform) and the non-destructive choice.
DEFAULT_CATEGORY_BY_SYSTEM: Dict[str, str] = {
    "account_service": "USER_PROFILE",
    "search_service": "SEARCH_INDEX_ENTRY",
    "analytics_platform": "ANALYTICS_PROFILE",
    "support_platform": "SUPPORT_MESSAGE",
    "export_service": "USER_EXPORT",
    "integration_service": "DATA_FLOW",
    "backup_service": "BACKUP_ARCHIVE",
    "security_service": "SECURITY_AUDIT_LOG",
    "legal_service": "LEGAL_HOLD_RECORD",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "object_storage": "SUPPORT_ATTACHMENT",
    "marketing_platform": "MARKETING_PROFILE",
}

# Connector data flows are not a deletion_rules.csv category (SPEC 6, connector row).
CONNECTOR_CATEGORY = "DATA_FLOW"
# SPEC 6 rule 14: a backup is retained in the rules file, but its restore must be blocked.
RESTORE_CATEGORIES = frozenset({"BACKUP_ARCHIVE"})

_RULE_ACTIONS: Dict[str, Treatment] = {
    "DELETE": Treatment.DELETE,
    "REDACT": Treatment.REDACT,
    "ANONYMIZE": Treatment.ANONYMIZE,
    "RETAIN": Treatment.RETAIN,
}


class PolicyError(ValueError):
    """The deletion policy cannot be applied: bad rule row, duplicate or unknown system."""


def system_for(resource_id: str) -> Optional[str]:
    """System that owns a resource id, from its prefix; None when no prefix matches (SPEC 6)."""
    for prefix, system_id in SYSTEM_BY_PREFIX.items():
        if resource_id.startswith(prefix):
            return system_id
    return None


def _treatment_for_rule(row: Rule) -> Treatment:
    """Treatment for one rules row; a retained backup becomes a restore block (SPEC 6 rule 14)."""
    action = _RULE_ACTIONS.get(row.required_action)
    if action is None:
        raise PolicyError("rule %s has unknown required_action %r" % (row.rule_id, row.required_action))
    if action is Treatment.RETAIN and row.data_category in RESTORE_CATEGORIES:
        return Treatment.RESTORE
    return action


class PolicyEngine:
    """Required treatment and compliance per resource, built from deletion_rules.csv (SPEC 6)."""

    def __init__(self, treatment_by_category: Mapping[str, Treatment]) -> None:
        self._by_category: Dict[str, Treatment] = dict(treatment_by_category)

    @classmethod
    def from_rules(cls, rows: Iterable[Rule]) -> "PolicyEngine":
        """Map each rules row's category to its treatment; a duplicate category is an error."""
        table: Dict[str, Treatment] = {CONNECTOR_CATEGORY: Treatment.FLOW}
        for row in rows:
            if row.data_category in table:
                raise PolicyError("duplicate deletion rule for category %s" % row.data_category)
            table[row.data_category] = _treatment_for_rule(row)
        return cls(table)

    def treatment(self, system_id: str, category: Optional[str]) -> Treatment:
        """Evidence category, then the system default (SPEC 6)."""
        if category is not None and category in self._by_category:
            return self._by_category[category]
        return self._category_treatment(system_id)

    def _category_treatment(self, system_id: str) -> Treatment:
        category = DEFAULT_CATEGORY_BY_SYSTEM.get(system_id)
        if category is None or category not in self._by_category:
            raise PolicyError("no default deletion rule for system %s" % system_id)
        return self._by_category[category]

    @staticmethod
    def is_compliant(treatment: Treatment, state: ObsState) -> bool:
        """True when the observed state is the verification state AGENTS 6.4 requires."""
        return state.value == state_of(TREATMENT_OPS[treatment][2])
