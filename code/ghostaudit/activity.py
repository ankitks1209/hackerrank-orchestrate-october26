"""Classify system_activity.csv rows by details template (SPEC 4).

Implements SPEC 4: one compiled regex per template (A, P, V, CF, CR, R, RP, RB,
N, L, T), the treatment taken from `event_type`, and the system_id per row kind.
Replication rows (R, and the replication form of T) belong to account_service,
the owner of the replicated account, so every non-noise system_id agrees with
the resource-prefix owner (policy.SYSTEM_BY_PREFIX).

`reported_result` is carried along as a claim and never read as state. A row that
matches no template is classified UNCLASSIFIED: inert like noise, never used for a
decision, warned about once per template shape and listed in the diagnostics, so
template drift cannot pass silently and cannot abort a run either. `strict=True`
raises `UnclassifiedActivityError` instead.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Pattern, Set, Tuple

from ghostaudit.dataset import ActivityRow
from ghostaudit.model import ACCOUNT_SERVICE, ActKind, ClassifiedActivity, Treatment

LOGGER = logging.getLogger(__name__)

DELETION_WORKER = "deletion_worker"
INTEGRATION_SERVICE = "integration_service"
BACKUP_SERVICE = "backup_service"

TREATMENT_BY_EVENT = {
    "DELETE_RECORD": Treatment.DELETE,
    "REDACT_RECORD": Treatment.REDACT,
    "ANONYMIZE_RECORD": Treatment.ANONYMIZE,
    "CHECK_DATA_FLOW": Treatment.FLOW,
    "DISABLE_DATA_FLOW": Treatment.FLOW,
    "CHECK_RESTORE_ACCESS": Treatment.RESTORE,
    "BLOCK_RESTORE": Treatment.RESTORE,
    "RETAIN_RECORD": Treatment.RETAIN,
}

_ID = r"(?P<rid>[a-z_]+_\d+)"
_NOISE_RE = re.compile(r"^.+ processed [a-z_]+_\d+\.$")


class UnclassifiedActivityError(ValueError):
    """A system_activity.csv row matches no known template (SPEC 4)."""


@dataclass(frozen=True)
class _Template:
    """One SPEC 4 template.

    `system_id` is None when the row's target_system is the resource's system.
    `names_related` marks templates whose details name a downstream resource
    (RP, RB) instead of the row's own resource_id.
    """

    kind: ActKind
    pattern: Pattern[str]
    system_id: Optional[str] = None
    names_related: bool = False


def _template(
    kind: ActKind, regex: str, system_id: Optional[str] = None, names_related: bool = False
) -> _Template:
    """Template whose regex must match the whole details text."""
    return _Template(kind, re.compile("^" + regex + "$"), system_id, names_related)


# Tried in order of frequency in system_activity.csv. The
# patterns are anchored and disjoint, so the order never changes a result.
# Replication rows target a replica cluster (account_replication_cluster,
# account_failover_replica); their system is the owning account_service.
_TEMPLATES: Tuple[_Template, ...] = (
    _template(
        ActKind.VIOLATION,
        r"Deletion worker received the final result for " + _ID + r" from \w+\.",
    ),
    _template(
        ActKind.ACCOUNT_SUBMIT,
        r"Deletion worker submitted primary profile " + _ID + r" to account_service\.",
    ),
    _template(ActKind.POLICY_OK, r"Policy action completed for " + _ID + r"\."),
    _template(
        ActKind.FLOW_ENABLED,
        r"Connector status check confirmed that data flow " + _ID + r" remains enabled\.",
    ),
    _template(
        ActKind.REPLICATION_CHECKPOINT,
        r"Replication worker reported its final checkpoint for " + _ID + r"\.",
        ACCOUNT_SERVICE,
    ),
    _template(
        ActKind.REPOPULATED,
        r"Active connector repopulated downstream resource " + _ID + r"\.",
        INTEGRATION_SERVICE,
        names_related=True,
    ),
    _template(
        ActKind.RESTORE_ALLOWED,
        r"Restore-access check confirmed that archive " + _ID + r" can still be restored\.",
    ),
    _template(
        ActKind.LINK,
        r"(?:Data catalog linked|Attachment catalog confirmed) " + _ID
        + r" \((?P<alias>[^)]+)\) (?:to|belongs only to) (?P<email>\S+)"
        + r" and (?P<user>user_\d+)[.;].*",
    ),
    _template(ActKind.TARGET_RESOURCE, r"Deletion worker .*\. Target resource: " + _ID + r"\."),
    _template(
        ActKind.NON_DELETION,
        r"Privacy intake classified request for " + _ID
        + r" as non-deletion; no destructive action was authorized\.",
        ACCOUNT_SERVICE,
    ),
    _template(
        ActKind.TARGET_RESOURCE,
        r"Replication worker .*\. Target resource: " + _ID + r"\.",
        ACCOUNT_SERVICE,
    ),
    _template(
        ActKind.RESTORE_REPOPULATED,
        r"Restore job repopulated downstream resource " + _ID + r"\.",
        BACKUP_SERVICE,
        names_related=True,
    ),
)


def _treatment(kind: ActKind, event_type: str) -> Optional[Treatment]:
    """Treatment from event_type (SPEC 4).

    Noise carries none, although archival noise rows are RETAIN_RECORD.
    """
    return None if kind in (ActKind.NOISE, ActKind.UNCLASSIFIED) else TREATMENT_BY_EVENT.get(event_type)


def classify_row(row: ActivityRow) -> ClassifiedActivity:
    """Classify one activity row; raises UnclassifiedActivityError when no template fits."""
    if row.source_system != DELETION_WORKER and _NOISE_RE.match(row.details):
        return _build(row, ActKind.NOISE, row.target_system)
    for template in _TEMPLATES:
        match = template.pattern.match(row.details)
        if match is None:
            continue
        named = match.group("rid")
        if not template.names_related and named != row.resource_id:
            raise UnclassifiedActivityError(
                "%s names %s but its resource_id is %s" % (row.activity_id, named, row.resource_id)
            )
        groups = match.groupdict()
        return _build(
            row,
            template.kind,
            template.system_id or row.target_system,
            related_rid=named if template.names_related else None,
            alias=groups.get("alias"),
            linked_user=groups.get("user"),
            linked_email=groups.get("email"),
        )
    raise UnclassifiedActivityError("%s matches no template: %s" % (row.activity_id, row.details))


def _build(
    row: ActivityRow,
    kind: ActKind,
    system_id: str,
    related_rid: Optional[str] = None,
    alias: Optional[str] = None,
    linked_user: Optional[str] = None,
    linked_email: Optional[str] = None,
) -> ClassifiedActivity:
    """ClassifiedActivity for one row; the treatment comes from its event_type (SPEC 4)."""
    return ClassifiedActivity(
        activity_id=row.activity_id,
        t=row.event_time,
        kind=kind,
        system_id=system_id,
        resource_id=row.resource_id,
        treatment=_treatment(kind, row.event_type),
        reported_result=row.reported_result,
        related_rid=related_rid,
        alias=alias,
        linked_user=linked_user,
        linked_email=linked_email,
    )


def _shape(details: str) -> str:
    """The template shape of a details text: every number replaced by '#'."""
    return re.sub(r"\d+", "#", details)


def _unclassified(row: ActivityRow) -> ClassifiedActivity:
    """An inert placeholder for a row that fits no template: no treatment, no related resource."""
    return _build(row, ActKind.UNCLASSIFIED, row.target_system)


def classify_activity(rows: Iterable[ActivityRow], strict: bool = False) -> Tuple[ClassifiedActivity, ...]:
    """Classify every row; the result is sorted by (t, activity_id) (SPEC 4).

    An unrecognised row becomes UNCLASSIFIED (one warning per template shape) unless
    `strict`, which raises UnclassifiedActivityError.
    """
    acts: List[ClassifiedActivity] = []
    warned: Set[str] = set()
    for row in rows:
        try:
            acts.append(classify_row(row))
        except UnclassifiedActivityError as error:
            if strict:
                raise
            shape = _shape(row.details)
            if shape not in warned:
                warned.add(shape)
                LOGGER.warning("unclassified activity row (reported, not used): %s", error)
            acts.append(_unclassified(row))
    return tuple(sorted(acts, key=lambda act: act.order_key))


def unclassified_ids(acts: Iterable[ClassifiedActivity]) -> Tuple[str, ...]:
    """Activity ids of the rows that matched no template, in stream order."""
    return tuple(act.activity_id for act in acts if act.kind is ActKind.UNCLASSIFIED)
