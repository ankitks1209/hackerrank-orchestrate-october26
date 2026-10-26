"""Label-free verification of every emitted step: P2a locator check, P2b recall sweep, P2c coverage.

Implements checks P2a-c and SPEC 8.3b (proof-file coverage). The verifier
re-reads the raw participant files with its own cutter (`raw_units`) and its own subject keys
(`raw_dataset`); it imports nothing from `ghostaudit` (a test enforces this), so an error in the
solver's parsers or linker is not repeated here. It reads no label: only `output.csv`, the
participant data and, for P2d, the diagnostics of the run that wrote the output.

* P2a: every step that cites a file, an activity row or an audit row is re-opened. The cited
  source must be admissible at `audit_at`, must name the resource, must show the claimed state, and
  its unit must carry one of the subject's keys (or the case account). A unit that names only
  another user fails. A unit with no key at all is `unkeyed`: state verified, ownership rests on
  the solver's timing signals, which P2d reports.
* P2b: every resource id next to a subject key in a file captured by `audit_at` is emitted, or has
  an independently computed exclusion reason.
* P2c: every resource id named in a cited in-window file is assigned to some case, or has a reason.

`evaluation.verify_report` composes these checks into the CLI report.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

from evaluation.raw_dataset import RawDataset, Req
from evaluation.raw_units import Unit, file_units

ACTIVITY_PREFIX = "activity_"
AUDIT_PREFIX = "audit_"
NOT_APPLICABLE = "NOT_APPLICABLE"
ACCOUNT_SYSTEM = "account_service"
DECOY_SERVICE = "profile_service"
WORKER_SOURCE = "deletion_worker"
POLICY_DONE = "Policy action completed"
ABSENT_OPERATIONS = frozenset({"VERIFY_RECORD_ABSENT"})
CLEAN_OPERATIONS = frozenset({"VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED"})
ABSENT_MARKER = re.compile(
    r'not_found|http_status\W{0,3}404|status_code\W{0,3}404|\brows\W{0,3}0\b|"profile": null'
)
# Words that show a file enumerates a system (table, snapshot or scope names of the F2/F3 layouts).
SCOPE_WORDS: Dict[str, Tuple[str, ...]] = {
    "account_service": ("account_service", "customer_profiles", "customer_accounts"),
    "search_service": ("search_service", "customer_search_documents", "search_documents"),
    "analytics_platform": ("analytics_platform", "customer_analytics_profiles"),
    "support_platform": ("support_platform", "support_records", "support_conversations"),
    "export_service": ("export_service", "customer_exports"),
    "integration_service": ("integration_service", "connector_subscriptions"),
    "backup_service": ("backup_service", "backup_restore_entries"),
    "security_service": ("security_service", "security_audit_records"),
}
EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
HASH = re.compile(r"\b[0-9a-f]{64}\b")
USER = re.compile(r"\buser_\d+\b")
PHONE = re.compile(r"\+[\d ()\-]{8,}")
NON_DIGIT = re.compile(r"\D")

# Result codes of P2a.
KEYED = "keyed"
UNKEYED = "unkeyed"
OMISSION = "omission"
MEDIA = "media"
SOURCE_ROW = "source_row"
FAILED = "failed"
# Exclusion reasons of P2b and P2c.
POST_AUDIT = "post_audit"
PRE_REQUEST = "pre_request"
DECOY = "decoy"
SHARED_UNIT = "shared_unit"
OWNERLESS = "ownerless_policy_row"
UNEXPLAINED = "unexplained"


@dataclass(frozen=True)
class Step:
    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str


@dataclass(frozen=True)
class Case:
    case_id: str
    status: str
    steps: Tuple[Step, ...]


@dataclass(frozen=True)
class Finding:
    """One verifier result about a step or a resource of a case."""

    case_id: str
    resource_id: str
    code: str
    detail: str = ""


def read_output(path: Path) -> Dict[str, Case]:
    """Cases of an `output.csv`-shaped file, keyed by case id."""
    cases: Dict[str, Case] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            steps = tuple(Step(int(s["step_no"]), s["phase"], s["system_id"], s["resource_id"],
                               s["operation"], s["state"], s["evidence_id"])
                          for s in json.loads(row["steps_json"]))
            cases[row["case_id"]] = Case(row["case_id"], row["deletion_status"], steps)
    return cases


class Evidence:
    """Lazy per-file units of the raw evidence, shared by every check."""

    def __init__(self, dataset: RawDataset) -> None:
        self._dataset = dataset
        self._cache: Dict[str, Tuple[Unit, ...]] = {}
        self._owned: Dict[str, Tuple[Tuple[Unit, FrozenSet[str]], ...]] = {}
        self._by_user: Optional[Dict[str, List[Tuple[str, Unit]]]] = None
        self.phones = {
            re.sub(NON_DIGIT, "", key): user
            for user, keys in dataset.keys_by_user.items() for key in keys if key.startswith("+")
        }

    def units(self, file_id: str) -> Tuple[Unit, ...]:
        if file_id not in self._cache:
            self._cache[file_id] = file_units(self._dataset.files[file_id].path)
        return self._cache[file_id]

    def owned_units(self, file_id: str) -> Tuple[Tuple[Unit, FrozenSet[str]], ...]:
        """Units of a file with the users each one names, computed once."""
        if file_id not in self._owned:
            self._owned[file_id] = tuple((unit, self.owners(unit.text)) for unit in self.units(file_id))
        return self._owned[file_id]

    def units_of_user(self, user: str) -> Tuple[Tuple[str, Unit], ...]:
        """Every (file id, unit) that names `user`, in manifest order."""
        if self._by_user is None:
            self._by_user = defaultdict(list)
            for entry in sorted(self._dataset.files.values(), key=lambda item: item.order):
                for unit, found in self.owned_units(entry.file_id):
                    for owner in found:
                        self._by_user[owner].append((entry.file_id, unit))
        return tuple(self._by_user.get(user, ()))

    def owners(self, text: str, direct_only: bool = False) -> FrozenSet[str]:
        """Users whose email, hash, phone (and, unless `direct_only`, user id) appear in lower-case `text`."""
        by_key = self._dataset.user_by_key
        patterns = (EMAIL, HASH) if direct_only else (EMAIL, HASH, USER)
        found = {by_key[token] for pattern in patterns for token in pattern.findall(text) if token in by_key}
        found |= {self.phones[digits] for digits in
                  (re.sub(NON_DIGIT, "", token) for token in PHONE.findall(text)) if digits in self.phones}
        return frozenset(found)


def _case_accounts(case: Case) -> FrozenSet[str]:
    return frozenset(step.resource_id for step in case.steps if step.system_id == ACCOUNT_SYSTEM)


def _source_row_check(dataset: RawDataset, req: Req, subject: Optional[str], step: Step) -> Optional[str]:
    """Failure detail for an activity or audit citation, or None when it holds."""
    cite = step.evidence_id
    if cite.startswith(ACTIVITY_PREFIX):
        acts = [act for act in dataset.activity if act.activity_id == cite]
        if not acts:
            return "activity row does not exist"
        act = acts[0]
        if act.t > req.audit_at:
            return "activity row is after audit_at"
        if step.resource_id not in (act.resource_id, act.target) and step.resource_id not in act.details:
            return "activity row does not name the resource"
        return None
    row = dataset.audit.get(cite)
    if row is None:
        return "audit row does not exist"
    if row.t > req.audit_at:
        return "audit row is after audit_at"
    if subject is not None and row.user_id != subject:
        return "audit row belongs to another user"
    return None


def check_step(
    dataset: RawDataset, evidence: Evidence, case: Case, req: Req, subject: Optional[str], step: Step
) -> Finding:
    """P2a result for one cited step."""
    cite = step.evidence_id
    base = (case.case_id, step.resource_id)
    if cite.startswith((ACTIVITY_PREFIX, AUDIT_PREFIX)):
        problem = _source_row_check(dataset, req, subject, step)
        return Finding(*base, FAILED, problem) if problem else Finding(*base, SOURCE_ROW)
    entry = dataset.files.get(cite)
    if entry is None:
        return Finding(*base, FAILED, "cited file is not in the manifest")
    if not req.reported_at <= entry.captured_at <= req.audit_at:
        return Finding(*base, FAILED, "file captured outside [reported_at, audit_at]")
    units = evidence.units(cite)
    if not units:
        return Finding(*base, MEDIA)
    hits = latest_state(units, step.resource_id, req.audit_at, entry.captured_at)
    if step.operation in ABSENT_OPERATIONS:
        return _absence(base, hits, units, step)
    return _presence(evidence, base, hits, case, subject, step)


def latest_state(units: Sequence[Unit], rid: str, audit_at: int, captured_at: int) -> List[Unit]:
    """Units about `rid` at the latest admissible time (SPEC T1, T2); replicas tie and all count."""
    admissible = [(unit.time if unit.time is not None else captured_at, unit)
                  for unit in units if rid in unit.ids and (unit.time or 0) <= audit_at]
    latest = max((time for time, _unit in admissible), default=None)
    return [unit for time, unit in admissible if time == latest]


def lists_system(units: Sequence[Unit], system_id: str) -> bool:
    """True when the file enumerates `system_id`: a scope header, a table or an id of that system."""
    words = SCOPE_WORDS[system_id]
    prefix = {"account_service": "account_"}.get(system_id, system_id.split("_")[0] + "_")
    return any(any(word in unit.group.lower() or word in unit.text for word in words)
               or any(rid.startswith(prefix) for rid in unit.ids) for unit in units)


def _absence(base: Tuple[str, str], hits: Sequence[Unit], units: Sequence[Unit], step: Step) -> Finding:
    if hits:
        shown = [unit for unit in hits if not ABSENT_MARKER.search(unit.text)]
        return Finding(*base, FAILED, "file still shows the record at %s" % shown[0].locator) if shown \
            else Finding(*base, KEYED)
    if lists_system(units, step.system_id):
        return Finding(*base, OMISSION)
    return Finding(*base, FAILED, "file lists no %s record, so omission proves nothing" % step.system_id)


def _presence(
    evidence: Evidence, base: Tuple[str, str], hits: Sequence[Unit], case: Case, subject: Optional[str],
    step: Step,
) -> Finding:
    if not hits:
        return Finding(*base, FAILED, "file does not name the resource")
    if step.operation in CLEAN_OPERATIONS:
        if subject and any(subject in evidence.owners(unit.text, direct_only=True) for unit in hits):
            return Finding(*base, FAILED, "identifying keys are still in the record")
        return Finding(*base, UNKEYED)
    live = [unit for unit in hits if not ABSENT_MARKER.search(unit.text)]
    if not live:
        return Finding(*base, FAILED, "file shows the record as absent")
    accounts = _case_accounts(case)
    owners = [evidence.owners(unit.text) for unit in live]
    if any(subject in found or accounts & unit.ids for found, unit in zip(owners, live)):
        return Finding(*base, KEYED)
    if all(found for found in owners):
        return Finding(*base, FAILED, "record names only other users")
    return Finding(*base, UNKEYED)


def locator_check(dataset: RawDataset, cases: Mapping[str, Case]) -> List[Finding]:
    """P2a over every cited step of the evaluation cases."""
    evidence = Evidence(dataset)
    requests = {req.case_id: req for req in dataset.requests if not req.is_sample}
    results: List[Finding] = []
    for case_id in sorted(cases):
        case, req = cases[case_id], requests[case_id]
        subject = dataset.subject_of(req)
        results += [check_step(dataset, evidence, case, req, subject, step)
                    for step in case.steps if step.evidence_id]
    return results


def _file_reason(unit: Unit, captured_at: int, req: Req, subject: str, evidence: Evidence) -> str:
    if unit.time is not None and unit.time > req.audit_at:
        return POST_AUDIT
    if captured_at < req.reported_at:
        return PRE_REQUEST
    if DECOY_SERVICE in unit.text:
        return DECOY
    if evidence.owners(unit.text) - {subject}:
        return SHARED_UNIT
    return UNEXPLAINED


def recall_sweep(dataset: RawDataset, cases: Mapping[str, Case]) -> List[Finding]:
    """P2b: ids beside a subject key that the case does not emit, each with an independent reason."""
    evidence = Evidence(dataset)
    found: List[Finding] = []
    for req in sorted((r for r in dataset.requests if not r.is_sample), key=lambda r: r.case_id):
        case, subject = cases[req.case_id], dataset.subject_of(req)
        if case.status == NOT_APPLICABLE or subject is None:
            continue
        emitted = {step.resource_id for step in case.steps}
        seen: Dict[str, str] = {}
        for file_id, unit in evidence.units_of_user(subject):
            captured_at = dataset.files[file_id].captured_at
            if captured_at > req.audit_at:
                continue
            for rid in sorted(unit.ids - emitted):
                reason = _file_reason(unit, captured_at, req, subject, evidence)
                if seen.get(rid) in (None, UNEXPLAINED):
                    seen[rid] = reason
        found += [Finding(req.case_id, rid, reason, "") for rid, reason in sorted(seen.items())]
    return found


def worker_row_ids(dataset: RawDataset) -> FrozenSet[str]:
    """Resource ids that a deletion-worker activity row names (the rows the solver must place)."""
    return frozenset(act.resource_id for act in dataset.activity if act.source == WORKER_SOURCE)


def policy_only_ids(dataset: RawDataset) -> FrozenSet[str]:
    """Worker-row ids whose every activity row only says that a policy action completed."""
    rows: Dict[str, List[bool]] = defaultdict(list)
    for act in dataset.activity:
        if act.source == WORKER_SOURCE:
            rows[act.resource_id].append(act.details.startswith(POLICY_DONE))
    return frozenset(rid for rid, flags in rows.items() if all(flags))


def _coverage_reason(
    unit: Unit, owners: FrozenSet[str], policy_only: bool, req: Req, requested: "Set[Optional[str]]"
) -> str:
    if unit.time is not None and unit.time > req.audit_at:
        return POST_AUDIT
    if DECOY_SERVICE in unit.text or (owners and not owners & requested):
        return DECOY
    if not owners and policy_only:
        return OWNERLESS
    return UNEXPLAINED


def coverage_sweep(
    dataset: RawDataset, cases: Mapping[str, Case], samples: Mapping[str, Case]
) -> List[Finding]:
    """P2c: worker-row ids named in a cited in-window proof file that no case emits, with a reason."""
    evidence = Evidence(dataset)
    workers, policy_only = worker_row_ids(dataset), policy_only_ids(dataset)
    assigned = {step.resource_id for group in (cases, samples) for case in group.values() for step in case.steps}
    requested = {dataset.subject_of(req) for req in dataset.requests}
    found: List[Finding] = []
    for req in sorted((r for r in dataset.requests if not r.is_sample), key=lambda r: r.case_id):
        cited = sorted({s.evidence_id for s in cases[req.case_id].steps
                        if s.evidence_id in dataset.files and
                        req.reported_at <= dataset.files[s.evidence_id].captured_at <= req.audit_at})
        reasons: Dict[str, str] = {}
        for file_id in cited:
            for unit, owners in evidence.owned_units(file_id):
                for rid in sorted((unit.ids & workers) - assigned):
                    reason = _coverage_reason(unit, owners, rid in policy_only, req, requested)
                    if reasons.get(rid) in (None, UNEXPLAINED):
                        reasons[rid] = reason
        found += [Finding(req.case_id, rid, reason, "") for rid, reason in sorted(reasons.items())]
    return found
