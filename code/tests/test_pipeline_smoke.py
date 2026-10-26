"""Smoke tests for the pipeline, the CLI and the diagnostics (SPEC A1, N6, N7).

A tiny synthetic dataset with fictional ids is written to a temporary directory: one
user, one account, one evidence file that still shows the account, and three evaluation
requests (a deletion, a data-access request, a deletion by an unknown address) plus one
sample. A second class runs the real dataset with `--llm off` in a temporary output
directory and checks the structure of the answer, never an evaluation case id.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import List
from unittest import mock

from ghostaudit import cli
from ghostaudit.config import API_KEY_ENV, REPO_ROOT, Config
from ghostaudit.dataset import DatasetError, DatasetReader
from ghostaudit.diagnostics import DIAGNOSTICS_NAME, step_provenance
from ghostaudit.llm.cache import CachingClient, DiskCache
from ghostaudit.llm.client import LLMUnavailable, NullClient
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import STATUS_INCOMPLETE, STATUS_NOT_APPLICABLE, Step
from ghostaudit.pipeline import LLMServices, run
from tests.dataset_guard import needs_dataset

EMAIL = "pat.example@example.com"
UNKNOWN_EMAIL = "nobody@example.com"
ACCOUNT = "account_90017"
DELETE_TEXT = "Please delete my account and all personal data."
ACCESS_TEXT = "Please send me a copy of the personal data you hold about me."
REPORTED = "2026-03-10T10:00:00Z"
AUDIT = "2026-03-12T10:00:00Z"
SUBMITTED = "2026-03-10T09:00:00Z"  # one hour before the report: the account worker row
CAPTURED = "2026-03-11T12:00:00Z"
EVIDENCE_PATH = "evidence/records/customer_data_snapshot_bundle_20260311.json"
SAMPLE_ID = "synth_s01"
EVAL_IDS = ("synth_001", "synth_002", "synth_003")
REQUEST_HEADER = "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text"


def csv_text(header: str, rows: List[List[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header.split(","))
    writer.writerows(rows)
    return out.getvalue()


def request_row(case_id: str, email: str, text: str) -> List[str]:
    return [case_id, email, "2026-03-09T08:00:00Z", "COMPLETE", REPORTED, AUDIT, text]


def write_dataset(root: Path) -> None:
    """A minimal valid dataset: the account of `EMAIL` is still present at audit time."""
    (root / "evidence" / "records").mkdir(parents=True)
    sha = hashlib.sha256(EMAIL.encode("utf-8")).hexdigest()
    files = {
        "deletion_requests.csv": csv_text(REQUEST_HEADER, [
            request_row(EVAL_IDS[0], EMAIL, DELETE_TEXT),
            request_row(EVAL_IDS[1], EMAIL, ACCESS_TEXT),
            request_row(EVAL_IDS[2], UNKNOWN_EMAIL, DELETE_TEXT),
        ]),
        "sample_deletion_requests.csv": csv_text(REQUEST_HEADER, [request_row(SAMPLE_ID, EMAIL, DELETE_TEXT)]),
        "user_identities.csv": csv_text("user_id,name,email,phone,email_hash,updated_at", [
            ["user_90177", "Pat Example", EMAIL, "+1 555 010 0199", sha, "2026-01-01T00:00:00Z"]]),
        "user_audit_log.csv": csv_text("audit_id,user_id,event_time,field_name,old_value,new_value", []),
        "system_activity.csv": csv_text(
            "activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details",
            [["activity_90017", SUBMITTED, "DELETE_RECORD", "deletion_worker", "account_service", ACCOUNT, "SUCCESS",
              "Deletion worker submitted primary profile %s to account_service." % ACCOUNT]]),
        "deletion_rules.csv": csv_text("rule_id,data_category,condition,required_action", [
            ["rule_1", "USER_PROFILE", "Always", "DELETE"],
            ["rule_2", "SECURITY_AUDIT_LOG", "Always", "RETAIN"]]),
        "evidence_files.csv": csv_text("file_id,file_path,origin,captured_at", [
            ["evidence_901", EVIDENCE_PATH, "records_assurance_snapshot_bundle", CAPTURED]]),
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    bundle = {
        "exported_at": CAPTURED,
        "source": "records_assurance_service",
        "snapshots": [{
            "captured_at": CAPTURED,
            "data_store": "account_service",
            "collection": "customer_profiles",
            "records": [{"resource_id": ACCOUNT, "customer_reference": "user_90177", "full_name": "Pat Example",
                         "email": EMAIL, "phone": "+1 555 010 0199", "account_status": "ACTIVE"}],
        }],
    }
    (root / EVIDENCE_PATH).write_text(json.dumps(bundle), encoding="utf-8")


def services() -> LLMServices:
    """A client stack that never calls a model: every request is refused (`--llm off`)."""
    cache = DiskCache(Path(tempfile.gettempdir()) / "ghostaudit-no-cache")
    meter = UsageMeter(Config().prices)
    return LLMServices(CachingClient(NullClient(), cache, meter, "off"), cache, meter)


def run_cli(*args: str) -> int:
    """Run the CLI with its expected-error logging muted, so a passing run prints no ERROR lines."""
    cli_logger = logging.getLogger("ghostaudit.cli")
    previous = cli_logger.level
    cli_logger.setLevel(logging.CRITICAL)
    try:
        with redirect_stdout(io.StringIO()):
            return cli.main(list(args))
    finally:
        cli_logger.setLevel(previous)


class SyntheticDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.dataset = self.tmp / "dataset"
        write_dataset(self.dataset)
        self.out = self.tmp / "out" / "output.csv"
        self.diag = self.tmp / "diag"

    def cli_args(self, *extra: str) -> List[str]:
        return ["--dataset", str(self.dataset), "--llm", "off", "--out", str(self.out),
                "--diag", str(self.diag)] + list(extra)

    def test_pipeline_answers_every_request(self) -> None:
        config = replace(Config(), dataset_dir=self.dataset, llm_mode="off")
        result = run(config, DatasetReader(self.dataset), services())
        by_id = {case.request.case_id: case for case in result.cases}
        self.assertEqual(sorted(by_id), sorted(EVAL_IDS + (SAMPLE_ID,)))
        self.assertEqual(by_id[EVAL_IDS[0]].result.deletion_status, STATUS_INCOMPLETE)
        self.assertEqual(by_id[EVAL_IDS[1]].result.deletion_status, STATUS_NOT_APPLICABLE)
        self.assertEqual(by_id[EVAL_IDS[1]].result.steps, ())
        self.assertEqual([r.case_id for r in result.eval_results], list(EVAL_IDS))
        self.assertEqual([r.case_id for r in result.sample_results], [SAMPLE_ID])
        self.assertTrue(result.eval_validation.ok and result.sample_validation.ok)

    def test_incomplete_case_reports_the_remaining_account_with_its_evidence(self) -> None:
        config = replace(Config(), dataset_dir=self.dataset, llm_mode="off")
        result = run(config, DatasetReader(self.dataset), services())
        case = next(c for c in result.cases if c.request.case_id == EVAL_IDS[0])
        findings = [s for s in case.result.steps if s.phase == "FINDING"]
        self.assertEqual([(s.resource_id, s.operation, s.evidence_id) for s in findings],
                         [(ACCOUNT, "REPORT_REMAINING_RECORD", "evidence_901")])
        self.assertEqual([s.evidence_id for s in case.result.steps if s.phase != "FINDING"], ["", ""])
        self.assertEqual([name for name, _seconds in result.timings][0], "media extraction")

    def test_cli_writes_output_and_diagnostics_but_no_samples_by_default(self) -> None:
        self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_OK)
        with self.out.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["case_id", "deletion_status", "steps_json"])
        self.assertEqual([row[0] for row in rows[1:]], list(EVAL_IDS))
        self.assertEqual(json.loads(rows[2][2]), [])
        text = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        for heading in ("## Stage timings", "## LLM degradations", "## Intent", "## Links",
                        "## Evidence", "## Contract validation", "### %s" % EVAL_IDS[0]):
            self.assertIn(heading, text)
        self.assertIn("evidence_901", text)
        self.assertFalse((self.diag / cli.SAMPLE_PREDICTIONS_NAME).exists())

    def test_unclassified_activity_row_is_reported_and_does_not_stop_the_run(self) -> None:
        with (self.dataset / "system_activity.csv").open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerow(
                ["activity_90018", SUBMITTED, "DELETE_RECORD", "deletion_worker", "account_service", ACCOUNT,
                 "SUCCESS", "Deletion worker did something no template describes."])
        with self.assertLogs("ghostaudit.activity", level="WARNING"):
            self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_OK)
        text = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        self.assertIn("- Unclassified activity rows (inert, never used for a decision): 1\n  - activity_90018", text)
        with self.out.open(encoding="utf-8", newline="") as handle:
            statuses = {row[0]: row[1] for row in list(csv.reader(handle))[1:]}
        self.assertEqual(statuses[EVAL_IDS[0]], STATUS_INCOMPLETE)  # the unknown row decided nothing

    def test_clean_activity_reports_zero_unclassified_rows(self) -> None:
        self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_OK)
        text = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        self.assertIn("- Unclassified activity rows (inert, never used for a decision): 0\n", text)

    def test_include_samples_writes_them_beside_the_diagnostics(self) -> None:
        self.assertEqual(run_cli(*self.cli_args("--include-samples")), cli.EXIT_OK)
        with (self.diag / cli.SAMPLE_PREDICTIONS_NAME).open(encoding="utf-8", newline="") as handle:
            ids = [row[0] for row in list(csv.reader(handle))[1:]]
        self.assertEqual(ids, [SAMPLE_ID])

    def test_output_is_byte_identical_across_runs(self) -> None:
        run_cli(*self.cli_args())
        first = self.out.read_bytes()
        run_cli(*self.cli_args())
        self.assertEqual(self.out.read_bytes(), first)

    def test_flags_reach_the_run(self) -> None:
        self.assertEqual(run_cli(*self.cli_args("--agent", "off", "--flags", "fifo_pairing=off")), cli.EXIT_OK)
        text = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        self.assertIn("fifo_pairing=False", text)
        self.assertIn("Agent: `off`", text)

    def test_missing_input_file_exits_2_naming_the_file(self) -> None:
        (self.dataset / "deletion_rules.csv").unlink()
        self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_INPUT)
        self.assertFalse(self.out.exists())
        with self.assertRaises(DatasetError) as caught:
            DatasetReader(self.dataset).check_complete()
        self.assertIn("deletion_rules.csv", str(caught.exception))

    def test_missing_dataset_directory_exits_2(self) -> None:
        self.assertEqual(run_cli("--dataset", str(self.tmp / "absent"), "--llm", "off",
                                 "--out", str(self.out), "--diag", str(self.diag)), cli.EXIT_INPUT)

    def test_unwritable_output_path_exits_2_with_one_line_and_runs_nothing(self) -> None:
        blocker = self.tmp / "a_file"
        blocker.write_text("not a directory", encoding="utf-8")
        for option, value in (("--out", blocker / "x" / "output.csv"), ("--diag", blocker / "diag")):
            with self.subTest(option=option):
                args = self.cli_args(option, str(value))
                with self.assertLogs("ghostaudit.cli", level="ERROR") as logs, redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(args), cli.EXIT_INPUT)
                self.assertEqual(len(logs.output), 1)
                self.assertIn("cannot run: cannot create output directory", logs.output[0])

    def test_bad_flag_exits_2(self) -> None:
        for bad in ("nonsense=on", "fifo_pairing", "fifo_pairing=maybe"):
            with self.subTest(flags=bad):
                self.assertEqual(run_cli(*self.cli_args("--flags", bad)), cli.EXIT_INPUT)

    def test_live_mode_without_a_usable_client_exits_2_and_calls_nothing(self) -> None:
        # No key in the environment and none in a `.env` (the repo-root one is masked).
        with mock.patch.dict(os.environ), \
                mock.patch("ghostaudit.config.DOTENV_PATH", self.dataset / ".env"):
            os.environ.pop(API_KEY_ENV, None)
            args = self.cli_args()
            args[args.index("off")] = "live"
            self.assertEqual(run_cli(*args), cli.EXIT_INPUT)
        with self.assertRaises(LLMUnavailable):
            cli.build_services(replace(Config(), llm_mode="live", api_key=None))

    def test_contract_violation_exits_1_but_still_writes_the_output(self) -> None:
        with mock.patch("ghostaudit.cli.run", side_effect=self.broken_run):
            self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_CONTRACT)
        self.assertTrue(self.out.exists())

    def broken_run(self, config, reader, llm):
        """The real run, with the evaluation validation replaced by a failing one."""
        from ghostaudit.contract import ValidationResult, Violation
        result = run(config, reader, llm)
        failing = ValidationResult((Violation(EVAL_IDS[0], "forced", "test"),), ())
        return replace(result, eval_validation=failing)

    def test_unread_media_in_the_window_is_listed_per_case(self) -> None:
        """SPEC N7: an image the run could not read is named in every case whose window holds it."""
        image = "evidence/images/console_20260311.png"
        (self.dataset / "evidence" / "images").mkdir(parents=True)
        (self.dataset / image).write_bytes(b"not read under --llm off")
        with (self.dataset / "evidence_files.csv").open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerow(["evidence_903", image, "console", CAPTURED])
        self.assertEqual(run_cli(*self.cli_args()), cli.EXIT_OK)
        text = (self.diag / DIAGNOSTICS_NAME).read_text(encoding="utf-8")
        section = text.split("### %s " % EVAL_IDS[0], 1)[1].split("### ", 1)[0]
        self.assertIn("- Unread in-window media: evidence_903", section)

    def test_step_provenance_names_file_activity_audit_and_future_work(self) -> None:
        config = replace(Config(), dataset_dir=self.dataset, llm_mode="off")
        result = run(config, DatasetReader(self.dataset), services())

        def step(cite: str) -> Step:
            return Step(1, "FINDING", "account_service", ACCOUNT, "REPORT_REMAINING_RECORD", "PRESENT", cite)

        def where(cite: str) -> str:
            return step_provenance(step(cite), result.index, result.citations)

        self.assertEqual(where("evidence_901"),
                         "records/customer_data_snapshot_bundle_20260311.json @ snapshots[0].records[0]")
        self.assertEqual(where("activity_90017"), "system_activity.csv:activity_90017")
        self.assertTrue(where("").startswith("none"))
        self.assertEqual(where("evidence_902"), "unknown citation")


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    """`--llm off` on the real dataset (SPEC N7): 518 valid rows, deterministic."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.out = cls.tmp / "output.csv"
        cls.code = run_cli("--llm", "off", "--out", str(cls.out), "--diag", str(cls.tmp / "diag"))
        cls.reader = DatasetReader(REPO_ROOT / "dataset")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_exit_code_and_row_count(self) -> None:
        expected = [r.case_id for r in self.reader.requests() if not r.is_sample]
        self.assertEqual(self.code, cli.EXIT_OK)
        with self.out.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(expected), 518)
        self.assertEqual(len(rows) - 1, 518)
        self.assertEqual(len({row[0] for row in rows[1:]}), 518)

    def test_every_status_is_valid_and_not_applicable_rows_are_empty(self) -> None:
        with self.out.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))[1:]
        for case_id, status, steps_json in rows:
            self.assertIn(status, ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"), case_id)
            if status == "NOT_APPLICABLE":
                self.assertEqual(steps_json, "[]", case_id)

    def test_default_output_path_is_the_repo_root_file(self) -> None:
        self.assertEqual(cli.build_parser().get_default("out"), REPO_ROOT / "output.csv")
        self.assertEqual(cli.build_parser().get_default("llm"), "cache")


if __name__ == "__main__":
    unittest.main()
