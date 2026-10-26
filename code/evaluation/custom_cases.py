"""Custom synthetic evaluation cases C1-C7 (AGENTS 6.8 report requirement; SPEC I1-I4, T1-T5, 6, 8, 9).

Each case writes a mini `dataset/` (the CSVs plus one to three evidence files in the real
formats) into a temporary directory and runs the real pipeline over it. The truth of a case
is written down here, from the SPEC and from the file contents, before the pipeline runs:

* C1 historical, upper-case request email with failover drift (SPEC I1, I2, F3);
* C2 non-English negated request, answered by the lexicon and by a scripted model (SPEC 9);
* C3 time travel: later files and a later tail line must not change the state (SPEC T1, T3);
* C4 exposed tombstone, legal hold, audit record: ordering and empty evidence ids (SPEC 8.2-8.4);
* C5 an active connector repopulated a search document, with no connector status row (SPEC L9);
* C6 a `.jr` look-alike and a same-name user must not add findings (SPEC I4);
* C7 one user, two requests with disjoint windows (SPEC T5).

Every id, email and name is synthetic; none occurs in `dataset/`. `--llm off` runs go through
`ghostaudit.cli.main` with `--out` and `--diag` under the temporary directory, so the submission
`output.csv` is never touched. The scripted-model run calls `pipeline.run` with a fake client
and never reaches the network.

    python3 -m evaluation custom [--json PATH]      # from code/, or `ghostaudit-eval custom`

prints a Markdown summary and optionally writes the rows `tools/render_reports.py` reads.
Exit codes: 0 every case reproduces its expected output; 1 a case differs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ghostaudit import cli
from ghostaudit.config import Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.llm.cache import CachingClient, DiskCache
from ghostaudit.llm.client import LLMRequest, LLMResponse
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import CaseResult, Phase, state_of
from ghostaudit.pipeline import LLMServices, RunResult, run
from ghostaudit.timeutil import iso, to_epoch

LOG = logging.getLogger("ghostaudit.evaluation.custom")

HOUR = 3600
DAY = 24 * HOUR
EXIT_OK = 0
EXIT_DIFFERS = 1
RUN_OFF = "off"  # `ghostaudit --llm off`: the lexicon decides intent
RUN_SCRIPTED = "scripted"  # a fake model client answers intent, in live mode, without a network
SCRIPTED_CONFIDENCE = 0.95
INTENT_ID_PREFIX = '<request id="'
OUTPUT_NAME = "output.csv"
DIAG_NAME = "diag"

REQUEST_HEADER = "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text"
IDENTITY_HEADER = "user_id,name,email,phone,email_hash,updated_at"
AUDIT_HEADER = "audit_id,user_id,event_time,field_name,old_value,new_value"
ACTIVITY_HEADER = (
    "activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details"
)
MANIFEST_HEADER = "file_id,file_path,origin,captured_at"
RULES_HEADER = "rule_id,data_category,condition,required_action"
# deletion_rules.csv of the challenge, row for row (the test compares it with the dataset copy).
RULES: Tuple[Tuple[str, str, str, str], ...] = (
    ("rule_01", "USER_PROFILE", "Always", "DELETE"),
    ("rule_02", "SECONDARY_IDENTIFIER", "Always", "DELETE"),
    ("rule_03", "SEARCH_INDEX_ENTRY", "Always", "DELETE"),
    ("rule_04", "CACHE_ENTRY", "Always", "DELETE"),
    ("rule_05", "SUPPORT_MESSAGE",
     "Conversation contains shared customer, agent, or order context that must be retained", "REDACT"),
    ("rule_06", "SUPPORT_ATTACHMENT", "Attachment belongs only to the deletion subject", "DELETE"),
    ("rule_07", "ANALYTICS_PROFILE", "Record is still attributable to a user", "ANONYMIZE"),
    ("rule_08", "PRODUCT_TELEMETRY", "Record is still attributable to a user", "ANONYMIZE"),
    ("rule_09", "USER_EXPORT", "Always", "DELETE"),
    ("rule_10", "MARKETING_PROFILE", "Always", "DELETE"),
    ("rule_11", "EMAIL_DELIVERY_LOG", "Log contains a user email address", "REDACT"),
    ("rule_12", "SECURITY_AUDIT_LOG", "Record is within the supplied retention period", "RETAIN"),
    ("rule_13", "LEGAL_HOLD_RECORD", "A supplied legal hold is active", "RETAIN"),
    ("rule_14", "BACKUP_ARCHIVE", "Restore access can be blocked", "RETAIN"),
    ("rule_15", "ACCOUNT_TOMBSTONE",
     "Account is deleted and only a stable internal user_id is needed to preserve references "
     "to retained records", "REDACT"),
)

DELETE_TEXT = "Please erase my account and every personal detail attached to it."
DELETE_SUFFIX = " Please also handle the copies that fall within the scope of this request."
PHONE_A = "+44 7700 900101"
PHONE_B = "+44 7700 900202"
PHONE_C = "+44 7700 900303"
USER_UPDATED = "2026-01-01T00:00:00Z"

Step6 = Tuple[str, str, str, str, str, str]  # phase, system, resource, operation, state, evidence
Projection = Tuple[str, Tuple[Step6, ...]]  # deletion_status, steps


# -- time windows ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """The times of one request; `shift` moves the whole window by whole days (SPEC T5)."""

    reported: int
    requested: int
    audit: int

    @classmethod
    def starting(cls, date: str, shift_days: int = 0) -> "Window":
        base = to_epoch(date + "T00:00:00Z") + shift_days * DAY
        return cls(reported=base + 2 * HOUR, requested=base - 2 * DAY + 8 * HOUR, audit=base + DAY + 13 * HOUR)

    @property
    def account_row_at(self) -> int:
        """The account worker row sits an hour before the report (SPEC L2)."""
        return self.reported - HOUR

    @property
    def proof_at(self) -> int:
        """A capture time inside `[reported, audit]` (SPEC T3)."""
        return self.reported + 18 * HOUR

    @property
    def late_at(self) -> int:
        """A capture time after `audit_at` (SPEC T1, T4)."""
        return self.audit + 2 * DAY

    @property
    def tail_at(self) -> int:
        """A log line time after `audit_at`, in a file captured inside the window."""
        return self.audit + 20 * HOUR


WINDOW = Window.starting("2026-05-06")


# -- the mini dataset ------------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    email: str
    phone: str


@dataclass(frozen=True)
class Req:
    case_id: str
    email: str
    text: str
    window: Window = WINDOW
    status: str = "COMPLETE"


@dataclass(frozen=True)
class Evidence:
    file_id: str
    path: str
    origin: str
    captured_at: int
    text: str


@dataclass(frozen=True)
class Dataset:
    """Everything one case writes to its temporary `dataset/` directory."""

    users: Tuple[User, ...]
    requests: Tuple[Req, ...]
    audit_rows: Tuple[Tuple[str, ...], ...] = ()
    activity: Tuple[Tuple[str, ...], ...] = ()
    evidence: Tuple[Evidence, ...] = ()


def _csv(header: str, rows: Sequence[Sequence[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header.split(","))
    writer.writerows(rows)
    return out.getvalue()


def _sha256(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def write_dataset(dataset: Dataset, root: Path) -> None:
    """Write the CSVs and evidence files of `dataset` under `root` in the participant layout."""
    evidence_root = root / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    requests = [
        [r.case_id, r.email, iso(r.window.requested), r.status, iso(r.window.reported),
         iso(r.window.audit), r.text]
        for r in dataset.requests
    ]
    files = {
        "deletion_requests.csv": _csv(REQUEST_HEADER, requests),
        "sample_deletion_requests.csv": _csv(REQUEST_HEADER, []),
        "user_identities.csv": _csv(IDENTITY_HEADER, [
            [u.user_id, u.name, u.email, u.phone, _sha256(u.email), USER_UPDATED] for u in dataset.users]),
        "user_audit_log.csv": _csv(AUDIT_HEADER, dataset.audit_rows),
        "system_activity.csv": _csv(ACTIVITY_HEADER, dataset.activity),
        "deletion_rules.csv": _csv(RULES_HEADER, RULES),
        "evidence_files.csv": _csv(MANIFEST_HEADER, [
            [e.file_id, e.path, e.origin, iso(e.captured_at)] for e in dataset.evidence]),
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    for item in dataset.evidence:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text, encoding="utf-8")


# -- activity rows (SPEC 4 templates) --------------------------------------------------------


def account_submit(activity_id: str, account: str, at: int, result: str = "SUCCESS") -> Tuple[str, ...]:
    """Template A: the deletion worker submitted the case account."""
    return (activity_id, iso(at), "DELETE_RECORD", "deletion_worker", "account_service", account, result,
            "Deletion worker submitted primary profile %s to account_service." % account)


def final_result(
    activity_id: str, at: int, event: str, system: str, rid: str, result: str = "FAILED"
) -> Tuple[str, ...]:
    """Template V: the worker received a final result for a resource."""
    return (activity_id, iso(at), event, "deletion_worker", system, rid, result,
            "Deletion worker received the final result for %s from %s." % (rid, system))


def repopulated(activity_id: str, at: int, flow: str, search: str) -> Tuple[str, ...]:
    """Template RP: an active connector repopulated a search document."""
    return (activity_id, iso(at), "SYNC_RECORD", "integration_service", "search_service", flow, "SUCCESS",
            "Active connector repopulated downstream resource %s." % search)


def non_deletion_intake(activity_id: str, at: int, account: str) -> Tuple[str, ...]:
    """Template N: privacy intake classified the request as non-deletion (a claim only)."""
    return (activity_id, iso(at), "CLASSIFY_REQUEST", "privacy_intake", "privacy_case_management", account,
            "SUCCESS", "Privacy intake classified request for %s as non-deletion; "
                       "no destructive action was authorized." % account)


# -- evidence files in the real formats ------------------------------------------------------

_PROFILE_COLUMNS = (
    "resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,\n"
    "                full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,\n"
    "                account_status TEXT NOT NULL, updated_at TEXT NOT NULL"
)
ProfileRow = Tuple[str, str, str, str, str]  # resource_id, user_id, full_name, email, phone


def _sql_inserts(table: str, rows: Sequence[ProfileRow], at: int) -> List[str]:
    return [
        'INSERT INTO "%s" VALUES(%s);' % (
            table, ",".join("'%s'" % value.replace("'", "''") for value in (*row, "ACTIVE", iso(at))))
        for row in rows
    ]


def failover_sql(captured_at: int, primary: Sequence[ProfileRow], replica: Sequence[ProfileRow]) -> str:
    """A profile primary/failover pair snapshot (SPEC F3); a replica-only row is drift."""
    lines = [
        "-- Ghost Data Still Exists: point-in-time database snapshot",
        "-- Dialect: SQLite-compatible SQL",
        "-- Captured at: %s" % iso(captured_at),
        "-- Database topology: failover_replica",
        "-- Compare the primary and any replica tables for replication drift.",
        "",
        "BEGIN TRANSACTION;",
        "CREATE TABLE customer_profiles_failover_replica (\n                %s\n            );" % _PROFILE_COLUMNS,
        *_sql_inserts("customer_profiles_failover_replica", replica, captured_at - 900),
        "CREATE TABLE customer_profiles_primary (\n                %s\n            );" % _PROFILE_COLUMNS,
        *_sql_inserts("customer_profiles_primary", primary, captured_at - 900),
        "COMMIT;",
        "",
    ]
    return "\n".join(lines)


def snapshot(captured_at: int, data_store: str, collection: str, records: Sequence[dict]) -> dict:
    """One snapshot of a records bundle (SPEC F5); empty `records` is an absence scope."""
    return {"captured_at": iso(captured_at), "data_store": data_store, "collection": collection,
            "records": list(records)}


def bundle(exported_at: int, snapshots: Sequence[dict]) -> str:
    """A records-assurance snapshot bundle (SPEC F5)."""
    document = {"exported_at": iso(exported_at), "source": "records_assurance_service",
                "snapshots": list(snapshots)}
    return json.dumps(document, indent=2) + "\n"


def profile_record(rid: str, user_id: str, name: str, email: str, phone: str) -> dict:
    return {"resource_id": rid, "customer_reference": user_id, "full_name": name, "email": email,
            "phone": phone, "account_status": "ACTIVE", "signup_channel": "mobile_app"}


def diag_log(lines: Sequence[Tuple[int, str, str, str, str, str]]) -> str:
    """A diag `record_lookup` log (SPEC F6, F9): (time, system, resource, record_type, result, subject)."""
    return "".join(
        '%s INFO service=search_index_service event=record_lookup seq=%d system="%s" resource_id="%s" '
        'record_type="%s" result="%s" subject_reference="%s"\n'
        % (iso(at), number, system, rid, record_type, result, subject)
        for number, (at, system, rid, record_type, result, subject) in enumerate(lines, start=1)
    )


# -- expected outputs ------------------------------------------------------------------------


def step(phase: Phase, system: str, rid: str, operation: str, evidence: str = "") -> Step6:
    """An expected step; the state is the one AGENTS 6.4 fixes for the operation."""
    return (phase.name, system, rid, operation, state_of(operation), evidence)


def finding(system: str, rid: str, operation: str, evidence: str) -> Step6:
    return step(Phase.FINDING, system, rid, operation, evidence)


def remediation(system: str, rid: str, operation: str) -> Step6:
    return step(Phase.REMEDIATION, system, rid, operation)


def verification(system: str, rid: str, operation: str, evidence: str = "") -> Step6:
    return step(Phase.VERIFICATION, system, rid, operation, evidence)


def render(projection: Projection) -> str:
    """One line per case outcome: the status and the steps, in order."""
    status, steps = projection
    shown = " ".join(
        "%s:%s:%s/%s@%s" % (phase[0], operation, system, rid, evidence or "-")
        for phase, system, rid, operation, _state, evidence in steps
    )
    return "%s [%s]" % (status, shown)


@dataclass(frozen=True)
class CustomCase:
    """One custom case: its mini dataset, the runs it needs and the written-down truth."""

    case_id: str
    title: str
    rationale: str
    dataset: Dataset
    expected: Dict[str, Projection]
    runs: Tuple[str, ...] = (RUN_OFF,)


@dataclass(frozen=True)
class Outcome:
    """What the pipeline produced for a case, next to the expected text (render_reports rows)."""

    case_id: str
    title: str
    rationale: str
    input_text: str
    expected: str
    actual: str

    @property
    def passed(self) -> bool:
        return self.expected == self.actual

    def as_row(self) -> Dict[str, str]:
        return {"id": self.case_id, "title": self.title, "rationale": self.rationale,
                "input": self.input_text, "expected": self.expected, "actual": self.actual}


# -- running a case --------------------------------------------------------------------------


class ScriptedIntentClient:
    """A fake model: answers every intent batch with one fixed verdict and never leaves the process."""

    def __init__(self, deletion: bool, confidence: float) -> None:
        self._deletion = deletion
        self._confidence = confidence
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        ids = [line.split('"')[1] for line in request.messages[0][1].splitlines()
               if line.startswith(INTENT_ID_PREFIX)]
        verdicts = [{"case_id": rid, "deletion": self._deletion, "confidence": self._confidence,
                     "language": "scripted", "reason": "scripted verdict"} for rid in ids]
        return LLMResponse(json.dumps({"verdicts": verdicts}), 1, 1, request.model, False)


def _project(result: CaseResult) -> Projection:
    return result.deletion_status, tuple(
        (s.phase, s.system_id, s.resource_id, s.operation, s.state, s.evidence_id) for s in result.steps
    )


def _row_projection(row: Sequence[str]) -> Projection:
    steps = tuple(
        (s["phase"], s["system_id"], s["resource_id"], s["operation"], s["state"], s["evidence_id"])
        for s in json.loads(row[2])
    )
    return row[1], steps


def run_cli(dataset_dir: Path, scratch: Path) -> Dict[str, Projection]:
    """`ghostaudit --llm off` over a mini dataset; the projections are read back from the written CSV."""
    out = scratch / OUTPUT_NAME
    args = ["--dataset", str(dataset_dir), "--llm", RUN_OFF, "--out", str(out), "--diag", str(scratch / DIAG_NAME)]
    with redirect_stdout(io.StringIO()):
        code = cli.main(args)
    if code != cli.EXIT_OK:
        raise RuntimeError("main.py exited %d on %s" % (code, dataset_dir))
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))[1:]
    return {row[0]: _row_projection(row) for row in rows}


def run_scripted(dataset_dir: Path, scratch: Path, client: ScriptedIntentClient) -> RunResult:
    """The pipeline in live mode with a fake model client, a throw-away cache and no network."""
    config = replace(Config(), dataset_dir=dataset_dir, llm_mode="live", cache_dir=scratch / "cache",
                     diag_dir=scratch / DIAG_NAME)
    cache = DiskCache(config.cache_dir)
    meter = UsageMeter(config.prices)
    services = LLMServices(CachingClient(client, cache, meter, "live"), cache, meter)
    return run(config, DatasetReader(dataset_dir), services)


def projections_of(result: RunResult) -> Dict[str, Projection]:
    """Evaluation-request projections of a pipeline run."""
    return {case.case_id: _project(case) for case in result.eval_results}


def run_case(case: CustomCase, work_dir: Path) -> Outcome:
    """Run every run of `case` and compare each with the expected projections."""
    expected = "; ".join("%s: %s" % (rid, render(case.expected[rid])) for rid in sorted(case.expected))
    seen: List[str] = []
    for label in case.runs:
        scratch = work_dir / case.case_id / label
        dataset_dir = scratch / "dataset"
        write_dataset(case.dataset, dataset_dir)
        if label == RUN_OFF:
            found = run_cli(dataset_dir, scratch)
        else:
            found = projections_of(run_scripted(dataset_dir, scratch, ScriptedIntentClient(False, SCRIPTED_CONFIDENCE)))
        seen.append("; ".join("%s: %s" % (rid, render(found[rid])) for rid in sorted(found)))
    actual = seen[0] if len(set(seen)) == 1 else " || ".join("%s -> %s" % item for item in zip(case.runs, seen))
    text = " | ".join("%s <%s> %s" % (r.case_id, r.email, r.text) for r in case.dataset.requests)
    return Outcome(case.case_id, case.title, case.rationale, "runs=%s; %s" % ("+".join(case.runs), text),
                   expected, actual)


# -- the cases -------------------------------------------------------------------------------

ACCOUNT_A = "account_7000101"
USER_A = "user_7000101"


def case_c1() -> CustomCase:
    """C1: the request carries an old address in capitals; the failover replica still holds the profile."""
    old, current = "sasha.marlow@example.com", "sasha.new@example.com"
    other = ("account_7000102", "user_7000102", "Imani Quill", "imani.quill@example.com", PHONE_C)
    mine = (ACCOUNT_A, USER_A, "Sasha Marlow", old, PHONE_A)
    captured = WINDOW.proof_at
    dataset = Dataset(
        users=(User(USER_A, "Sasha Marlow", current, PHONE_A),
               User("user_7000102", "Imani Quill", other[3], PHONE_C)),
        requests=(Req("synth_c1", old.upper(), DELETE_TEXT),),
        audit_rows=(("audit_c1_1", USER_A, "2026-02-01T09:00:00Z", "email", old, current),
                    ("audit_c1_2", USER_A, "2026-02-01T09:00:00Z", "email_hash", _sha256(old), _sha256(current))),
        activity=(account_submit("activity_c1_1", ACCOUNT_A, WINDOW.account_row_at),),
        evidence=(Evidence(
            "evidence_c1a", "evidence/databases/customer_accounts_failover_replica_20260506.sql",
            "customer_account_failover_replica_capture", captured,
            failover_sql(captured, primary=[other], replica=[mine, other])),),
    )
    expected = {"synth_c1": ("INCOMPLETE", (
        finding("account_service", ACCOUNT_A, "REPORT_REMAINING_RECORD", "evidence_c1a"),
        remediation("account_service", ACCOUNT_A, "DELETE_RECORD"),
        verification("account_service", ACCOUNT_A, "VERIFY_RECORD_ABSENT"),
    ))}
    return CustomCase(
        "C1", "Historical upper-case email with failover drift",
        "The request email is the user's previous address written in capitals (SPEC I1 lower-cases, I2 follows "
        "the audit history), so it must resolve to the user. The profile is absent from the primary but still in "
        "the failover replica, which is replication drift (SPEC F3): the account is a REPORT_REMAINING_RECORD "
        "finding even though the worker reported success. Another person's profile that sits in both tables must "
        "not appear.", dataset, expected)


def case_c2() -> CustomCase:
    """C2: a Portuguese request that refuses deletion, with an account that is still present."""
    email = "tomas.reid@example.com"
    text = "Por favor, não apague a minha conta; preciso apenas de uma cópia dos meus dados."
    mine = (ACCOUNT_A, USER_A, "Tomas Reid", email, PHONE_A)
    captured = WINDOW.proof_at
    dataset = Dataset(
        users=(User(USER_A, "Tomas Reid", email, PHONE_A),),
        requests=(Req("synth_c2", email, text),),
        activity=(account_submit("activity_c2_1", ACCOUNT_A, WINDOW.account_row_at),
                  non_deletion_intake("activity_c2_2", WINDOW.account_row_at + HOUR, ACCOUNT_A)),
        evidence=(Evidence(
            "evidence_c2a", "evidence/databases/customer_accounts_failover_replica_20260506.sql",
            "customer_account_failover_replica_capture", captured,
            failover_sql(captured, primary=[mine], replica=[mine])),),
    )
    return CustomCase(
        "C2", "Non-English negated request",
        "The text refuses deletion in Portuguese (negation before the verb 'apague', and an access request). "
        "SPEC 9 and AGENTS 6.5 make the case NOT_APPLICABLE with no steps, although the account is still present "
        "and the worker rows look like a deletion case. It runs twice, and both runs must agree: with `--llm off` "
        "the lexicon decides, and with a scripted model that answers deletion=false at confidence 0.95 the model "
        "decides. Both are hermetic.", dataset, {"synth_c2": ("NOT_APPLICABLE", ())},
        runs=(RUN_OFF, RUN_SCRIPTED))


def case_c3() -> CustomCase:
    """C3: the in-window file says ABSENT; a later file and a later tail line say PRESENT."""
    email = "wren.castle@example.com"
    in_window = diag_log([
        (WINDOW.proof_at - HOUR, "account_service", ACCOUNT_A, "USER_PROFILE", "NOT_FOUND", email),
        (WINDOW.tail_at, "account_service", ACCOUNT_A, "USER_PROFILE", "FOUND", email),
    ])
    later = bundle(WINDOW.late_at, [snapshot(WINDOW.late_at, "account_service", "customer_profiles", [
        profile_record(ACCOUNT_A, USER_A, "Wren Castle", email, PHONE_A)])])
    dataset = Dataset(
        users=(User(USER_A, "Wren Castle", email, PHONE_A),),
        requests=(Req("synth_c3", email, DELETE_TEXT),),
        activity=(account_submit("activity_c3_1", ACCOUNT_A, WINDOW.account_row_at),),
        evidence=(
            Evidence("evidence_c3a", "evidence/logs/search_index_diagnostic_20260506.log",
                     "search_index_service", WINDOW.proof_at, in_window),
            Evidence("evidence_c3b", "evidence/records/customer_data_snapshot_bundle_20260509.json",
                     "records_assurance_snapshot_bundle", WINDOW.late_at, later),
        ),
    )
    expected = {"synth_c3": ("COMPLETE", (
        verification("account_service", ACCOUNT_A, "VERIFY_RECORD_ABSENT", "evidence_c3a"),
    ))}
    return CustomCase(
        "C3", "Time travel: later evidence must not change the answer",
        "Only information available at audit_at counts (AGENTS 6.2, SPEC T1). The file captured inside the window "
        "says NOT_FOUND. Its own last line is stamped after audit_at and says FOUND, and a second file captured "
        "two days after audit_at lists the profile. Both are inadmissible (T1) and the later file is not citable "
        "(T3), so the case is COMPLETE and cites the in-window file.", dataset, expected)


def case_c4() -> CustomCase:
    """C4: exposed tombstone, a legal hold and an audit record in one in-window bundle."""
    email = "odette.finch@example.com"
    tomb, hold, audit = "tombstone_7000103", "legal_hold_7000104", "audit_record_7000105"
    records = bundle(WINDOW.proof_at, [
        snapshot(WINDOW.proof_at, "account_service", "customer_profiles", []),
        snapshot(WINDOW.proof_at, "identity_service", "deleted_customer_references", [
            {"resource_id": tomb, "subject_reference": USER_A, "name": "Odette Finch", "email": email,
             "phone": PHONE_A, "email_hash": _sha256(email), "account_status": "DELETED"}]),
        snapshot(WINDOW.proof_at, "legal_service", "retained_order_records", [
            {"resource_id": hold, "subject_reference": USER_A, "order_reference": "ORD-70001",
             "retention_reason": "payment_dispute_and_tax_record", "retained_until": "2033-12-31T23:59:59Z"}]),
        snapshot(WINDOW.proof_at, "security_service", "security_audit_events", [
            {"resource_id": audit, "subject_reference": USER_A, "event_name": "account_deletion_reviewed",
             "actor_type": "automated_privacy_workflow",
             "integrity_seal": "sha256:" + "0" * 64}]),
    ])
    dataset = Dataset(
        users=(User(USER_A, "Odette Finch", email, PHONE_A),),
        requests=(Req("synth_c4", email, DELETE_TEXT + DELETE_SUFFIX),),
        activity=(account_submit("activity_c4_1", ACCOUNT_A, WINDOW.account_row_at),),
        evidence=(Evidence("evidence_c4a", "evidence/records/customer_data_snapshot_bundle_20260506.json",
                           "records_assurance_snapshot_bundle", WINDOW.proof_at, records),),
    )
    expected = {"synth_c4": ("INCOMPLETE", (
        finding("identity_service", tomb, "REPORT_EXPOSED_PII", "evidence_c4a"),
        remediation("identity_service", tomb, "REDACT_RECORD"),
        verification("account_service", ACCOUNT_A, "VERIFY_RECORD_ABSENT"),
        verification("legal_service", hold, "VERIFY_RECORD_PRESENT"),
        verification("security_service", audit, "VERIFY_RECORD_PRESENT"),
        verification("identity_service", tomb, "VERIFY_RECORD_REDACTED"),
    ))}
    return CustomCase(
        "C4", "Exposed tombstone with a legal hold and an audit record",
        "The tombstone keeps name, email, phone and hash, so rule 15 requires REDACT and never DELETE (SPEC 6): one "
        "REPORT_EXPOSED_PII finding, one REDACT_RECORD, one VERIFY_RECORD_REDACTED. The legal hold and the audit "
        "record are retained records, never findings, and are verified as present. The case is INCOMPLETE, so "
        "every compliant resource keeps an empty evidence_id (SPEC 8.2), and the steps follow the AGENTS 6.4 "
        "operation order, then system and resource (SPEC 8.4).", dataset, expected)


def case_c5() -> CustomCase:
    """C5: an active connector recreated a search document; no connector status row exists."""
    email = "rhea.lorne@example.com"
    flow, search = "data_flow_7000106", "search_7000107"
    records = bundle(WINDOW.proof_at, [
        snapshot(WINDOW.proof_at, "account_service", "customer_profiles", []),
        snapshot(WINDOW.proof_at, "search_service", "customer_search_documents", [
            {"resource_id": search, "index_name": "customer_directory_v3",
             "document": {"display_name": "Rhea Lorne", "email": email, "customer_reference": USER_A}}]),
        snapshot(WINDOW.proof_at, "integration_service", "connector_configurations", [
            {"resource_id": flow, "connector_name": "customer-events-to-warehouse-9",
             "destination": "customer_analytics_warehouse", "subject_selector": "segment:all_customers",
             "enabled": True, "mode": "continuous_sync"}]),
    ])
    dataset = Dataset(
        users=(User(USER_A, "Rhea Lorne", email, PHONE_A),),
        requests=(Req("synth_c5", email, DELETE_TEXT),),
        activity=(account_submit("activity_c5_1", ACCOUNT_A, WINDOW.account_row_at),
                  repopulated("activity_c5_2", WINDOW.reported + 4 * HOUR, flow, search)),
        evidence=(Evidence("evidence_c5a", "evidence/records/customer_data_snapshot_bundle_20260506.json",
                           "records_assurance_snapshot_bundle", WINDOW.proof_at, records),),
    )
    expected = {"synth_c5": ("INCOMPLETE", (
        finding("search_service", search, "REPORT_REMAINING_RECORD", "evidence_c5a"),
        finding("integration_service", flow, "REPORT_ACTIVE_DATA_FLOW", "evidence_c5a"),
        remediation("integration_service", flow, "DISABLE_DATA_FLOW"),
        remediation("search_service", search, "DELETE_RECORD"),
        verification("account_service", ACCOUNT_A, "VERIFY_RECORD_ABSENT"),
        verification("search_service", search, "VERIFY_RECORD_ABSENT"),
        verification("integration_service", flow, "VERIFY_DATA_FLOW_DISABLED"),
    ))}
    return CustomCase(
        "C5", "Active connector repopulated a search document",
        "The only link between the user and the connector is the activity row 'Active connector repopulated "
        "downstream resource search_N' (SPEC L9): the connector configuration names no user, and no 'Connector "
        "status check' row exists. The snapshot shows the connector enabled and the search document present, so the "
        "case reports the document, reports the active data flow, disables the flow before deleting the "
        "document (table order, SPEC 8.4), and verifies both. The connector is not a deletion target by itself.",
        dataset, expected)


def case_c6() -> CustomCase:
    """C6: a `.jr` look-alike and a same-name user own resources that must not reach the case."""
    mail = "dana.okafor@example.com"
    jr, third = "dana.okafor.jr@example.com", "d.okafor@example.org"
    account_jr, account_third = "account_7000109", "account_7000110"
    search_jr = "search_7000111"
    lines = diag_log([
        (WINDOW.proof_at, "account_service", ACCOUNT_A, "USER_PROFILE", "NOT_FOUND", mail),
        (WINDOW.proof_at, "account_service", account_jr, "USER_PROFILE", "FOUND", jr),
        (WINDOW.proof_at, "search_service", search_jr, "SEARCH_INDEX_ENTRY", "FOUND", jr),
        (WINDOW.proof_at, "account_service", account_third, "USER_PROFILE", "FOUND", third),
    ])
    dataset = Dataset(
        users=(User(USER_A, "Dana Okafor", mail, PHONE_A),
               User("user_7000108", "Dana Okafor", jr, PHONE_B),
               User("user_7000112", "Dana Okafor", third, PHONE_C)),
        requests=(Req("synth_c6", mail, DELETE_TEXT),),
        activity=(
            account_submit("activity_c6_1", ACCOUNT_A, WINDOW.account_row_at),
            account_submit("activity_c6_2", account_jr, WINDOW.account_row_at + 5 * 60),
            final_result("activity_c6_3", WINDOW.reported + HOUR, "DELETE_RECORD", "search_service", search_jr),
        ),
        evidence=(Evidence("evidence_c6a", "evidence/logs/search_index_diagnostic_20260506.log",
                           "search_index_service", WINDOW.proof_at, lines),),
    )
    expected = {"synth_c6": ("COMPLETE", (
        verification("account_service", ACCOUNT_A, "VERIFY_RECORD_ABSENT", "evidence_c6a"),
    ))}
    return CustomCase(
        "C6", "Look-alike email and same-name user add no findings",
        "Three users share the name Dana Okafor; one email differs only by '.jr' and one by domain. Identity "
        "matching is exact (SPEC I1, I4), so their account, search document and worker rows belong to other "
        "subjects (owner filter L4a) and must not become findings of the requester, whose own account is absent. "
        "The case is COMPLETE with the single cited account check.", dataset, expected)


def case_c7() -> CustomCase:
    """C7: one user files two requests whose windows do not overlap."""
    email = "jules.verne.test@example.com"
    first = Window.starting("2026-05-06")
    second = Window.starting("2026-05-06", shift_days=20)
    account_x, account_y, search_x = "account_7000113", "account_7000114", "search_7000115"
    file_x = bundle(first.proof_at, [
        snapshot(first.proof_at, "account_service", "customer_profiles", [
            profile_record(account_x, USER_A, "Jules Verne Test", email, PHONE_A)]),
        snapshot(first.proof_at, "search_service", "customer_search_documents", [
            {"resource_id": search_x, "index_name": "customer_directory_v3",
             "document": {"display_name": "Jules Verne Test", "email": email, "customer_reference": USER_A}}]),
    ])
    file_y = bundle(second.proof_at, [snapshot(second.proof_at, "account_service", "customer_profiles", [])])
    dataset = Dataset(
        users=(User(USER_A, "Jules Verne Test", email, PHONE_A),),
        requests=(Req("synth_c7a", email, DELETE_TEXT, first, "PARTIALLY_COMPLETE"),
                  Req("synth_c7b", email, DELETE_TEXT, second, "COMPLETE")),
        activity=(account_submit("activity_c7_1", account_x, first.account_row_at, "PARTIAL"),
                  account_submit("activity_c7_2", account_y, second.account_row_at)),
        evidence=(
            Evidence("evidence_c7a", "evidence/records/customer_data_snapshot_bundle_20260506.json",
                     "records_assurance_snapshot_bundle", first.proof_at, file_x),
            Evidence("evidence_c7b", "evidence/records/customer_data_snapshot_bundle_20260526.json",
                     "records_assurance_snapshot_bundle", second.proof_at, file_y),
        ),
    )
    expected = {
        "synth_c7a": ("INCOMPLETE", (
            finding("account_service", account_x, "REPORT_REMAINING_RECORD", "evidence_c7a"),
            finding("search_service", search_x, "REPORT_REMAINING_RECORD", "evidence_c7a"),
            remediation("account_service", account_x, "DELETE_RECORD"),
            remediation("search_service", search_x, "DELETE_RECORD"),
            verification("account_service", account_x, "VERIFY_RECORD_ABSENT"),
            verification("search_service", search_x, "VERIFY_RECORD_ABSENT"),
        )),
        "synth_c7b": ("COMPLETE", (
            verification("account_service", account_y, "VERIFY_RECORD_ABSENT", "evidence_c7b"),
        )),
    }
    return CustomCase(
        "C7", "One user, two requests with disjoint windows",
        "Each case is scoped by its own times (SPEC T5). The first request ends before the second begins. The first "
        "file shows the first account and a search document, so the first case is INCOMPLETE. The second case "
        "starts after that file was captured: it must not inherit the first case's resources (L10 floor) or cite "
        "its file (T3), and the first case must not see the later file (T1). The second case is COMPLETE with its "
        "own account and file.", dataset, expected)


def all_cases() -> Tuple[CustomCase, ...]:
    """C1-C7 in id order."""
    return tuple(build() for build in (case_c1, case_c2, case_c3, case_c4, case_c5, case_c6, case_c7))


def run_all(work_dir: Path) -> Tuple[Outcome, ...]:
    """Run every case under `work_dir`; each case gets its own sub-directories."""
    return tuple(run_case(case, work_dir) for case in all_cases())


# -- command line ----------------------------------------------------------------------------


def to_markdown(outcomes: Sequence[Outcome]) -> str:
    lines = ["| Case | Title | Result |", "|---|---|---|"]
    lines.extend("| %s | %s | %s |" % (o.case_id, o.title, "pass" if o.passed else "FAIL") for o in outcomes)
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="write the rows read by tools/render_reports.py")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    with tempfile.TemporaryDirectory() as scratch:
        outcomes = run_all(Path(scratch))
    sys.stdout.write(to_markdown(outcomes))
    for outcome in outcomes:
        if not outcome.passed:
            sys.stdout.write("\n%s expected: %s\n%s actual:   %s\n" % (
                outcome.case_id, outcome.expected, outcome.case_id, outcome.actual))
    if args.json:
        args.json.write_text(json.dumps([o.as_row() for o in outcomes], indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return EXIT_OK if all(o.passed for o in outcomes) else EXIT_DIFFERS


if __name__ == "__main__":
    sys.exit(main())
