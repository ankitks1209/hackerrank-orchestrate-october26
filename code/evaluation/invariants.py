"""Invariants and distributions over every emitted row, label-free (check P5).

Implements the P5 checks of the strategy: structure of the three phases, pairing of findings
with remediation and verification, citation rules, legal operation-system pairs, existence of
every resource id, and audit-record discovery parity. Each check is `hard` (a failure blocks the
release gate) or `warn` (reported and explained, never silent). The module reads `output.csv`
rows and the participant files through `evaluation.verify_steps` and `evaluation.raw_units`; it
imports nothing from `ghostaudit`.

Audit-record parity replaces the strategy's "cohort all-or-nothing" wording: cohorts cannot be
derived from participant data, so the check compares, per case, whether an audit record id is
discoverable beside the subject's key in a file captured inside the case window, or tied to the subject by a catalog LINK
row (an image or PDF cannot be grepped; this only excuses an emitted record), with whether
the case emits one.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

from evaluation.raw_dataset import RESOURCE_ID_PATTERN, RawDataset, Req, system_of
from evaluation.raw_units import Unit
from evaluation.verify_steps import ACCOUNT_SYSTEM, NOT_APPLICABLE, Case, Evidence

HARD = "hard"
WARN = "warn"
PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
SECURITY_SYSTEM = "security_service"
AUDIT_PREFIX = "audit_record_"
ACTIVITY_PREFIX = "activity_"
LINK_EVENT = "LINK_RESOURCE_IDENTITY"
# Systems each operation may name (AGENTS 6.4 and deletion_rules.csv: backups, tombstones, legal
# holds and audit records are never deleted; only analytics is anonymized; and so on).
LEGAL_SYSTEMS: Dict[str, FrozenSet[str]] = {
    "REPORT_ACTIVE_DATA_FLOW": frozenset({"integration_service"}),
    "DISABLE_DATA_FLOW": frozenset({"integration_service"}),
    "VERIFY_DATA_FLOW_DISABLED": frozenset({"integration_service"}),
    "REPORT_RESTORE_RISK": frozenset({"backup_service"}),
    "BLOCK_RESTORE": frozenset({"backup_service"}),
    "VERIFY_RESTORE_BLOCKED": frozenset({"backup_service"}),
    "REPORT_EXPOSED_PII": frozenset({"analytics_platform", "support_platform", "identity_service"}),
    "REDACT_RECORD": frozenset({"support_platform", "identity_service"}),
    "VERIFY_RECORD_REDACTED": frozenset({"support_platform", "identity_service"}),
    "ANONYMIZE_RECORD": frozenset({"analytics_platform"}),
    "VERIFY_RECORD_ANONYMIZED": frozenset({"analytics_platform"}),
    "VERIFY_RECORD_PRESENT": frozenset({"security_service", "legal_service"}),
}
UNEXPLAINED_EMPTY = "no reason in the diagnostics"
NEVER_DELETED = frozenset({"backup_service", "identity_service", "legal_service", "security_service",
                           "integration_service"})


@dataclass(frozen=True)
class Check:
    """One invariant: its severity, the failures found (empty means it holds) and a note."""

    name: str
    severity: str
    failures: Tuple[str, ...]
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.failures


def _evaluation_cases(dataset: RawDataset, cases: Mapping[str, Case]) -> List[Tuple[object, Case]]:
    return [(req, cases[req.case_id]) for req in sorted(dataset.requests, key=lambda r: r.case_id)
            if not req.is_sample]


def structure(cases: Mapping[str, Case]) -> Check:
    """Numbering, phase order, status shape and the empty-evidence rule for future work."""
    bad: List[str] = []
    for case in sorted(cases.values(), key=lambda item: item.case_id):
        steps = case.steps
        if [step.step_no for step in steps] != list(range(1, len(steps) + 1)):
            bad.append("%s: step numbers are not consecutive from 1" % case.case_id)
        order = [PHASES.index(step.phase) for step in steps]
        if order != sorted(order):
            bad.append("%s: phases are out of order" % case.case_id)
        if case.status == NOT_APPLICABLE and steps:
            bad.append("%s: NOT_APPLICABLE has steps" % case.case_id)
        if case.status == COMPLETE and any(step.phase != "VERIFICATION" or not step.evidence_id for step in steps):
            bad.append("%s: COMPLETE row has a step that is not a cited verification" % case.case_id)
        if case.status == INCOMPLETE:
            bad += _incomplete_shape(case)
    return Check("structure", HARD, tuple(bad))


def _incomplete_shape(case: Case) -> List[str]:
    bad = []
    if not any(step.phase == "FINDING" for step in case.steps):
        bad.append("%s: INCOMPLETE without a finding" % case.case_id)
    for step in case.steps:
        cited = bool(step.evidence_id)
        if (step.phase == "FINDING") != cited:
            bad.append("%s step %d: %s %s a citation" % (
                case.case_id, step.step_no, step.phase, "lacks" if step.phase == "FINDING" else "carries"))
    return bad


def pairing(cases: Mapping[str, Case]) -> Check:
    """Every finding has one remediation and one verification; none exists without a finding."""
    bad: List[str] = []
    for case in sorted(cases.values(), key=lambda item: item.case_id):
        if case.status != INCOMPLETE:
            continue
        counts: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        for step in case.steps:
            counts[(step.system_id, step.resource_id)][step.phase] += 1
        for (system, rid), phases in sorted(counts.items()):
            if phases["FINDING"]:
                if phases["FINDING"] != 1 or phases["REMEDIATION"] != 1 or phases["VERIFICATION"] != 1:
                    bad.append("%s %s/%s: finding/remediation/verification = %d/%d/%d" % (
                        case.case_id, system, rid, phases["FINDING"], phases["REMEDIATION"],
                        phases["VERIFICATION"]))
            elif phases["REMEDIATION"]:
                bad.append("%s %s/%s: remediation without a finding" % (case.case_id, system, rid))
    return Check("pairing", HARD, tuple(bad))


def legal_pairs(cases: Mapping[str, Case]) -> Check:
    """Operations name only systems that policy allows, and the id prefix agrees with the system."""
    bad: List[str] = []
    for case in sorted(cases.values(), key=lambda item: item.case_id):
        for step in case.steps:
            allowed = LEGAL_SYSTEMS.get(step.operation)
            if allowed is not None and step.system_id not in allowed:
                bad.append("%s step %d: %s on %s" % (case.case_id, step.step_no, step.operation, step.system_id))
            if step.operation in ("DELETE_RECORD", "VERIFY_RECORD_ABSENT") and step.system_id in NEVER_DELETED:
                bad.append("%s step %d: %s on %s" % (case.case_id, step.step_no, step.operation, step.system_id))
            if system_of(step.resource_id) not in (step.system_id, None):
                bad.append("%s step %d: %s does not belong to %s" % (
                    case.case_id, step.step_no, step.resource_id, step.system_id))
    return Check("legal operation-system pairs", HARD, tuple(bad))


def citation_window(dataset: RawDataset, cases: Mapping[str, Case]) -> Check:
    """Cited files lie in [reported_at, audit_at]; cited rows exist and are not later than audit_at."""
    bad: List[str] = []
    rows = {act.activity_id: act.t for act in dataset.activity}
    audits = {row_id: row.t for row_id, row in dataset.audit.items()}
    for req, case in _evaluation_cases(dataset, cases):
        for step in case.steps:
            cite = step.evidence_id
            if not cite:
                continue
            if cite in dataset.files:
                at = dataset.files[cite].captured_at
                ok = req.reported_at <= at <= req.audit_at
            else:
                at = rows.get(cite, audits.get(cite))
                ok = at is not None and at <= req.audit_at
            if not ok:
                bad.append("%s step %d: %s is not citable at audit_at" % (case.case_id, step.step_no, cite))
    return Check("citation window", HARD, tuple(bad))


def known_ids(dataset: RawDataset, evidence: Evidence) -> FrozenSet[str]:
    """Every resource id that the activity stream or a text evidence file names."""
    found: Set[str] = {act.resource_id for act in dataset.activity}
    for act in dataset.activity:
        found.update(RESOURCE_ID_PATTERN.findall(act.details))
    for file_id in dataset.files:
        for unit in evidence.units(file_id):
            found.update(unit.ids)
    return frozenset(found)


def ids_exist(dataset: RawDataset, evidence: Evidence, cases: Mapping[str, Case]) -> Check:
    """Every resource id of every step occurs in the participant data (media-only ids are reported)."""
    known = known_ids(dataset, evidence)
    bad = sorted({"%s: %s" % (case.case_id, step.resource_id) for case in cases.values()
                  for step in case.steps if step.resource_id not in known})
    return Check("resource ids exist", WARN, tuple(bad),
                 "ids found only in images or PDFs cannot be grepped; each listed id must be explained")


def account_step(dataset: RawDataset, cases: Mapping[str, Case]) -> Check:
    """Every deletion case verifies its account's absence (true in every public sample)."""
    missing = [case.case_id for _req, case in _evaluation_cases(dataset, cases)
               if case.status != NOT_APPLICABLE
               and not any(s.system_id == ACCOUNT_SYSTEM and s.operation == "VERIFY_RECORD_ABSENT"
                           for s in case.steps)]
    return Check("account verification step", WARN, tuple(missing),
                 "cases whose account has no proof file are omitted by rule V5; compare with the diagnostics count")


def empty_complete(
    dataset: RawDataset, cases: Mapping[str, Case], unread_media: Mapping[str, Sequence[str]]
) -> Check:
    """A COMPLETE row with no step proves nothing; list each one with its diagnostics reason.

    The reason the run records is the media it could not read inside the case window
    (`unread_media`, parsed from the diagnostics); a row without one is unexplained.
    """
    empty = [case.case_id for _req, case in _evaluation_cases(dataset, cases)
             if case.status == COMPLETE and not case.steps]
    listed = tuple("%s: %s" % (case_id, "unread in-window media " + ", ".join(unread_media[case_id])
                               if unread_media.get(case_id) else UNEXPLAINED_EMPTY) for case_id in empty)
    unexplained = sum(1 for text in listed if text.endswith(UNEXPLAINED_EMPTY))
    return Check("COMPLETE rows without steps", WARN, listed,
                 "the answer is COMPLETE but cites nothing; %d of %d have a reason in the diagnostics"
                 % (len(listed) - unexplained, len(listed)))


def _usable(dataset: RawDataset, req: Req, case: Case, file_id: str, unit: Unit) -> bool:
    """A row may rest only on evidence that exists inside its window; nothing later supplies an id (SPEC T4)."""
    at = dataset.files[file_id].captured_at
    return req.reported_at <= at <= req.audit_at and (unit.time is None or unit.time <= req.audit_at)


def _link_tied_audit_ids(dataset: RawDataset, req: Req, case: Case, subject: str) -> FrozenSet[str]:
    """Audit records a catalog LINK row ties to the subject; a screenshot may be their only proof.

    A LINK row names the resource, an email and a user id. An image or PDF cannot be grepped
    for ids, so the activity stream is the only text that can show such a record belongs to
    the subject. The row is admissible as `_usable` admits evidence.
    """
    emails = {key for key in dataset.keys_by_user.get(subject, ()) if "@" in key}
    user = re.compile(r"(?<!\w)%s(?!\w)" % re.escape(subject))
    found: Set[str] = set()
    for act in dataset.activity:
        if act.event_type != LINK_EVENT or not act.resource_id.startswith(AUDIT_PREFIX):
            continue
        text = act.details.lower()
        if not (user.search(text) or any(email in text for email in emails)):
            continue
        if req.reported_at <= act.t <= req.audit_at:
            found.add(act.resource_id)
    return frozenset(found)


def audit_parity(dataset: RawDataset, evidence: Evidence, cases: Mapping[str, Case]) -> Check:
    """Cases that emit an audit-record step are exactly those with a discoverable audit record.

    Discoverable means beside a subject key in a text evidence file. An emitted record may
    also be tied to the subject by a catalog LINK row, the only text trace of a record that a
    screenshot proves; such a record is excused when emitted but never demanded.
    """
    bad: List[str] = []
    for req, case in _evaluation_cases(dataset, cases):
        subject = dataset.subject_of(req)
        if case.status == NOT_APPLICABLE or subject is None:
            continue
        found = {rid for file_id, unit in evidence.units_of_user(subject) for rid in unit.ids
                 if rid.startswith(AUDIT_PREFIX) and _usable(dataset, req, case, file_id, unit)}
        linked = _link_tied_audit_ids(dataset, req, case, subject)
        emitted = {step.resource_id for step in case.steps if step.system_id == SECURITY_SYSTEM}
        if emitted - found - linked:
            bad.append("%s: emits %s with no audit record beside the subject key" % (
                case.case_id, ", ".join(sorted(emitted - found - linked))))
        if found - emitted:
            bad.append("%s: audit record %s is discoverable but not emitted" % (
                case.case_id, ", ".join(sorted(found - emitted))))
    return Check("audit-record discovery parity", HARD, tuple(bad))


def run_checks(
    dataset: RawDataset, cases: Mapping[str, Case],
    unread_media: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Check]:
    """All P5 invariants for the evaluation cases; `unread_media` explains empty COMPLETE rows."""
    evidence = Evidence(dataset)
    return [
        structure(cases), pairing(cases), legal_pairs(cases), citation_window(dataset, cases),
        audit_parity(dataset, evidence, cases), ids_exist(dataset, evidence, cases),
        account_step(dataset, cases), empty_complete(dataset, cases, unread_media or {}),
    ]


def distributions(dataset: RawDataset, cases: Mapping[str, Case]) -> Dict[str, object]:
    """Status counts, reported-versus-predicted confusion and steps per case."""
    confusion: Counter = Counter()
    sizes: List[int] = []
    for req, case in _evaluation_cases(dataset, cases):
        confusion[(req.reported_status, case.status)] += 1
        sizes.append(len(case.steps))
    ordered = sorted(sizes)
    return {
        "confusion": dict(sorted(confusion.items())),
        "steps": {"total": sum(sizes), "cases": len(sizes), "min": ordered[0] if ordered else 0,
                  "median": ordered[len(ordered) // 2] if ordered else 0, "max": ordered[-1] if ordered else 0},
    }


def failed_hard(checks: Sequence[Check]) -> List[Check]:
    return [check for check in checks if check.severity == HARD and not check.ok]
