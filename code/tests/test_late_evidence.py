"""Override-ban late-evidence injection test (SPEC T1, T4).

Evidence that did not exist at `audit_at` must not change an answer. The test adds, to a copy of
the dataset, (a) a snapshot bundle captured after every case's `audit_at` that lists every case
account as present, and (b) tail lines stamped after every `audit_at` in an in-window diagnostic
log that look up the same accounts as FOUND. The evaluation output must be byte-identical.
A control copy that backdates the same bundle into every window must change the answer, so the
injection is known to be visible to the pipeline.

Two variants are run. The keyless variant names the accounts but no person. The keyed variant names
the person, so every account would become an ownership anchor of the learned link signature if the
fit could see it; the fit reads ownership only up to the batch's audit horizon (docs/DECISIONS.md,
D15), so both variants must leave the output byte-identical.
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from tests import datacopy
from tests.dataset_guard import needs_dataset

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
LATE_DELTA = timedelta(days=2)
INJECTED_FILE_ID = "evidence_late_injection"
INJECTED_PATH = "evidence/records/customer_data_snapshot_bundle_injected.json"
INJECTED_ORIGIN = "records_assurance_snapshot_bundle"
DIAGNOSTIC_LOG_MARKER = "event=record_lookup seq="
ACCOUNT_SYSTEM = "account_service"

Account = Tuple[str, str]  # (resource id, email the case was filed with)


def _latest_audit(dataset_dir: Path) -> datetime:
    with (dataset_dir / "deletion_requests.csv").open(encoding="utf-8", newline="") as handle:
        stamps = [datetime.strptime(row["audit_at"], TIME_FORMAT) for row in csv.DictReader(handle)]
    return max(stamps).replace(tzinfo=timezone.utc)


def case_accounts(dataset_dir: Path, rows: Dict[str, Tuple[str, str]]) -> List[Account]:
    """The account each case verifies or deletes, with the email of its request."""
    with (dataset_dir / "deletion_requests.csv").open(encoding="utf-8", newline="") as handle:
        emails = {row["case_id"]: row["email"] for row in csv.DictReader(handle)}
    found = []
    for case_id, (_status, steps_json) in sorted(rows.items()):
        for step in json.loads(steps_json):
            if step["system_id"] == ACCOUNT_SYSTEM:
                found.append((step["resource_id"], emails[case_id]))
                break
    return found


def injected_bundle(accounts: List[Account], captured_at: datetime, keyed: bool = True) -> str:
    """A bundle that lists every account as ACTIVE, with the person's email when `keyed`."""
    stamp = captured_at.strftime(TIME_FORMAT)
    records = [{"resource_id": rid, "account_status": "ACTIVE", **({"email": email} if keyed else {})}
               for rid, email in accounts]
    snapshot = {"captured_at": stamp, "data_store": ACCOUNT_SYSTEM, "collection": "customer_profiles",
                "records": records}
    return json.dumps({"exported_at": stamp, "source": "records_assurance_service", "snapshots": [snapshot]},
                      indent=2) + "\n"


def tail_lines(accounts: List[Account], at: datetime, first_seq: int, keyed: bool = True) -> str:
    stamp = at.strftime(TIME_FORMAT)
    return "".join(
        '%s INFO service=search_index_service event=record_lookup seq=%d system="%s" resource_id="%s" '
        'record_type="USER_PROFILE" result="FOUND" subject_reference="%s"\n'
        % (stamp, first_seq + number, ACCOUNT_SYSTEM, rid, email if keyed else "null")
        for number, (rid, email) in enumerate(accounts, start=1))


def _diagnostic_log(dataset_dir: Path) -> Path:
    for path in sorted((dataset_dir / "evidence" / "logs").glob("*.log")):
        if DIAGNOSTIC_LOG_MARKER in path.read_text(encoding="utf-8"):
            return path
    raise AssertionError("no diagnostic log in the dataset")


def inject(
    dataset_dir: Path, accounts: List[Account], bundle_at: datetime, tail_at: datetime, keyed: bool = True
) -> None:
    """Add the bundle (as a new manifest file captured at `bundle_at`) and the tail lines."""
    target = dataset_dir / INJECTED_PATH
    target.write_text(injected_bundle(accounts, bundle_at, keyed), encoding="utf-8")
    with (dataset_dir / "evidence_files.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerow(
            [INJECTED_FILE_ID, INJECTED_PATH, INJECTED_ORIGIN, bundle_at.strftime(TIME_FORMAT)])
    log = _diagnostic_log(dataset_dir)
    text = log.read_text(encoding="utf-8")
    with log.open("a", encoding="utf-8", newline="") as handle:
        if not text.endswith("\n"):
            handle.write("\n")
        handle.write(tail_lines(accounts, tail_at, text.count(DIAGNOSTIC_LOG_MARKER), keyed))


@needs_dataset
class LateEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        root = Path(cls._scratch.name)
        source = datacopy.default_dataset()
        cls.baseline, _diag = datacopy.run_offline(source, root / "base")
        cls.accounts = case_accounts(source, cls.baseline)
        latest = _latest_audit(source)
        late, early = latest + LATE_DELTA, latest - timedelta(days=200)
        runs = (("keyless", late, False), ("keyed", late, True), ("control", early, True))
        for name, at, keyed in runs:
            datacopy.copy_dataset(source, root / name, lambda text: text)
            inject(root / name, cls.accounts, at, at, keyed)
            rows, _ = datacopy.run_offline(root / name, root / (name + "_run"), tolerate_violations=name == "control")
            setattr(cls, name, rows)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def changed(self, rows: Dict[str, Tuple[str, str]]) -> List[str]:
        return [case_id for case_id in sorted(self.baseline) if self.baseline[case_id] != rows[case_id]]

    def test_every_case_has_an_account_to_contradict(self) -> None:
        self.assertGreater(len(self.accounts), 400)

    def test_keyless_late_evidence_changes_nothing(self) -> None:
        self.assertEqual(self.changed(self.keyless), [])

    def test_keyed_late_evidence_changes_nothing(self) -> None:
        """The person's identifiers in late files reach neither the state nor the signature fit."""
        self.assertEqual(self.changed(self.keyed), [])

    def test_the_same_content_inside_a_window_is_visible(self) -> None:
        """Control: backdated into the windows the injection does change answers, so the test can fail."""
        self.assertGreater(len(self.changed(self.control)), 0)


if __name__ == "__main__":
    unittest.main()
