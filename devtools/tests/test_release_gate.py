"""Tests for the release gate (T43; LOCAL_EVALUATION_STRATEGY 8).

Gates run through an injected command runner, so no gate starts a real pipeline here. Panel records
and the manifest live in a temporary directory.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
from unittest import mock

from devtools import release_gate as rg
from tools import build_zip

OUTPUT_ROWS = 518


def output_csv(rows: int = OUTPUT_ROWS, header: str = rg.OUTPUT_HEADER, newline: str = "\n") -> str:
    ids = ["case_%d" % number for number in range(33, 33 + rows)]
    return newline.join([header] + ["%s,COMPLETE,[]" % case_id for case_id in ids]) + newline


class FakeRunner:
    """Answers commands by a substring of their text; records every call."""

    def __init__(self, answers: Optional[Dict[str, rg.Completed]] = None,
                 on_call: Optional[Callable[[Sequence[str]], None]] = None) -> None:
        self.answers = answers or {}
        self.on_call = on_call
        self.calls: List[List[str]] = []

    def __call__(self, arguments: Sequence[str]) -> rg.Completed:
        self.calls.append(list(arguments))
        if self.on_call:
            self.on_call(arguments)
        text = " ".join(arguments)
        for key, answer in self.answers.items():
            if key in text:
                return answer
        return rg.Completed(0, "")


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        (self.root / "dataset").mkdir()
        (self.root / "dataset" / "a.csv").write_text("x\n", encoding="utf-8")
        self.output = self.root / "output.csv"
        self.output.write_text(output_csv(), encoding="utf-8")
        self.archive = self.root / "code.zip"
        build_zip.write_zip({"README.md": b"r\n", "code/main.py": b"m\n"}, self.archive)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()

    def tearDown(self) -> None:
        self._dir.cleanup()

    def context(self, runner: Optional[Callable[[Sequence[str]], rg.Completed]] = None, **options: object) -> rg.Context:
        return rg.Context("rc1", runner or FakeRunner(), "python3", self.root, self.output, self.archive,
                          self.root / "dataset", self.scratch, **options)  # type: ignore[arg-type]


class HelperTests(Scratch):
    def test_record_values(self) -> None:
        values = rg.record_values("# Title\nCalibration: pass\n**Lowest code score:** 29.1\n- Blockers: 0\nno colon\n")
        self.assertEqual(values, {"calibration": "pass", "lowest code score": "29.1", "blockers": "0"})

    def test_natural_order_and_format_problems(self) -> None:
        self.assertEqual(rg.output_format_problems(self.output), [])
        self.output.write_text(output_csv(rows=3), encoding="utf-8")
        self.assertEqual(rg.output_format_problems(self.output), ["3 rows, expected 518"])
        self.output.write_bytes(output_csv(newline="\r\n").encode("utf-8"))
        self.assertIn("CR in output.csv", rg.output_format_problems(self.output))
        self.output.write_text(output_csv(header="a,b,c"), encoding="utf-8")
        self.assertIn("header is not %s" % rg.OUTPUT_HEADER, rg.output_format_problems(self.output))
        lines = output_csv().split("\n")
        lines[1], lines[2] = lines[2], lines[1]
        self.output.write_text("\n".join(lines), encoding="utf-8")
        self.assertIn("rows are not in natural case order", rg.output_format_problems(self.output))

    def test_dataset_hash_follows_content_and_names(self) -> None:
        before = rg.dataset_hash(self.root / "dataset")
        self.assertEqual(before, rg.dataset_hash(self.root / "dataset"))
        (self.root / "dataset" / "a.csv").write_text("y\n", encoding="utf-8")
        self.assertNotEqual(before, rg.dataset_hash(self.root / "dataset"))

    def test_zip_content_hash_equals_the_packagers(self) -> None:
        files = {"README.md": b"r\n", "code/main.py": b"m\n"}
        self.assertEqual(rg.zip_content_hash(self.archive), build_zip.content_hash(build_zip.manifest(files)))


class AutoGateTests(Scratch):
    def fresh_output(self, content: str) -> Callable[[Sequence[str]], None]:
        def write(arguments: Sequence[str]) -> None:
            target = Path(arguments[arguments.index("--out") + 1])
            target.write_text(content, encoding="utf-8")
        return write

    def test_r1_passes_when_the_rerun_is_identical(self) -> None:
        ctx = self.context(FakeRunner(on_call=self.fresh_output(output_csv())))
        self.assertEqual(rg.gate_r1(ctx).status, rg.PASS)

    def test_r1_fails_on_a_differing_rerun_or_a_failing_pipeline(self) -> None:
        differing = self.context(FakeRunner(on_call=self.fresh_output(output_csv(rows=517))))
        gate = rg.gate_r1(differing)
        self.assertEqual(gate.status, rg.FAIL)
        self.assertIn("differs from a fresh run", gate.detail)
        broken = self.context(FakeRunner({"main.py": rg.Completed(1, "boom")}))
        self.assertEqual(rg.gate_r1(broken).status, rg.FAIL)

    def test_r2_pass_pending_fail(self) -> None:
        for answer, status in ((rg.Completed(0, "test_x ... ok"), rg.PASS),
                               (rg.Completed(0, "test_x ... skipped 'media'"), rg.PENDING),
                               (rg.Completed(1, "FAIL"), rg.FAIL)):
            self.assertEqual(rg.gate_r2(self.context(FakeRunner({"test_golden": answer}))).status, status)

    def test_r3_and_r6_read_the_verification_report(self) -> None:
        clean = rg.Completed(0, "- Failures: 0\n- Unexplained: 0\n- Unexplained: 0\n"
                                "| structure | hard | 0 |\n| pairing | hard | 0 |\n| ids | warn | 2 |\n")
        self.assertEqual(rg.gate_r3(clean).status, rg.PASS)
        self.assertEqual(rg.gate_r6(clean), rg.Gate("R6", "P5 invariants", rg.PASS, "2 hard invariants hold"))
        bad = rg.Completed(1, "- Failures: 2\n- Unexplained: 0\n- Unexplained: 1\n| pairing | hard | 3 |\n")
        gate = rg.gate_r3(bad)
        self.assertEqual((gate.status, gate.detail), (rg.FAIL, "2 locator failures; 1 unexplained sweep items"))
        self.assertEqual(rg.gate_r6(bad).status, rg.FAIL)
        self.assertEqual(rg.gate_r3(rg.Completed(1, "garbage")).status, rg.FAIL)
        self.assertEqual(rg.gate_r6(rg.Completed(1, "garbage")).status, rg.FAIL)

    def test_r7_compares_with_the_previous_candidate(self) -> None:
        scores = {"G%d" % n: 0.9 for n in range(1, 9)}
        runner = FakeRunner({"evaluation score": rg.Completed(0, json.dumps({"normalized": scores}))})
        out = self.root / "scores.json"
        self.assertEqual(rg.gate_r7(self.context(runner, scores_out=out)).status, rg.PENDING)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), scores)
        previous = self.root / "previous.json"
        previous.write_text(json.dumps(scores), encoding="utf-8")
        self.assertEqual(rg.gate_r7(self.context(runner, previous_scores=previous)).status, rg.PASS)
        previous.write_text(json.dumps({**scores, "G3": 0.99}), encoding="utf-8")
        gate = rg.gate_r7(self.context(runner, previous_scores=previous))
        self.assertEqual((gate.status, gate.detail), (rg.FAIL, "regressed: G3"))

    def test_r8_r10_r11_follow_the_exit_codes(self) -> None:
        for gate_function, key in ((rg.gate_r8, "clean_room"), (rg.gate_r10, "-p test_"), (rg.gate_r11, "build_zip")):
            self.assertIn(gate_function(self.context(FakeRunner())).status, (rg.PASS, rg.PENDING))
            failed = FakeRunner({key: rg.Completed(1, "check failed: x\n- cell failed")})
            self.assertEqual(gate_function(self.context(failed)).status, rg.FAIL)

    def test_r10_runs_every_override_ban_module(self) -> None:
        runner = FakeRunner()
        rg.gate_r10(self.context(runner))
        text = " ".join(" ".join(call) for call in runner.calls)
        for module in rg.OVERRIDE_BAN_TESTS:
            self.assertIn(module, text)

    def test_r11_fails_on_a_stale_provenance_ledger(self) -> None:
        stale = FakeRunner({"confidence.py": rg.Completed(1, "the ledger in DECISIONS.md is stale")})
        gate = rg.gate_r11(self.context(stale, metrics_dir=self.root))
        self.assertEqual(gate.status, rg.FAIL)
        self.assertIn("ledger", gate.detail)

    def test_r11_is_pending_without_metrics_and_checks_them_when_given(self) -> None:
        self.assertEqual(rg.gate_r11(self.context()).status, rg.PENDING)
        runner = FakeRunner({"render_reports": rg.Completed(1, "drift")})
        self.assertEqual(rg.gate_r11(self.context(runner, metrics_dir=self.root)).status, rg.FAIL)
        self.assertEqual(rg.gate_r11(self.context(FakeRunner(), metrics_dir=self.root)).status, rg.PASS)


class RecordGateTests(Scratch):
    def with_record(self, name: str, text: Optional[str]):
        path = self.root / "record.md"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        return mock.patch.object(rg, name, path)

    def test_r4_needs_a_passing_gate_row_and_no_status_error(self) -> None:
        with self.with_record("ESTIMATION_RECORD", None):
            self.assertEqual(rg.gate_r4(self.context()).status, rg.PENDING)
        with self.with_record("ESTIMATION_RECORD", "| Status errors | 0 |\n| Gate | pass |\n"):
            self.assertEqual(rg.gate_r4(self.context()).status, rg.PASS)
        with self.with_record("ESTIMATION_RECORD", "| Status errors | 1 |\n| Gate | FAIL |\n"):
            self.assertEqual(rg.gate_r4(self.context()).status, rg.FAIL)

    def test_r5_needs_zero_unresolved_defects(self) -> None:
        for text, status in ((None, rg.PENDING), ("Unresolved defects: 0\n", rg.PASS),
                             ("Unresolved defects: 2\n", rg.FAIL), ("nothing\n", rg.FAIL)):
            with self.with_record("COVERAGE_RECORD", text):
                self.assertEqual(rg.gate_r5(self.context()).status, status, text)

    def test_r9_needs_lint_and_calibrated_panels(self) -> None:
        good = "Calibration: pass\nLowest code score: 29.0\nBlockers: 0\nTranscript score: 9.6\n"
        with self.with_record("PANEL_RECORD", None):
            self.assertEqual(rg.gate_r9(self.context()).status, rg.PENDING)
        with self.with_record("PANEL_RECORD", good):
            self.assertEqual(rg.gate_r9(self.context()).status, rg.PASS)
            self.assertEqual(rg.gate_r9(self.context(FakeRunner({"check_log": rg.Completed(1, "x")}))).status, rg.FAIL)
        for bad in ("Calibration: fail\n", "Lowest code score: 28.0\n", "Blockers: 1\n", "Transcript score: 9.0\n"):
            with self.with_record("PANEL_RECORD", good + bad):
                self.assertEqual(rg.gate_r9(self.context()).status, rg.FAIL, bad)


class FreezeTests(Scratch):
    def test_manifest_round_trip_and_drift(self) -> None:
        ctx = self.context()
        manifest = self.root / rg.MANIFEST_NAME
        self.assertEqual(rg.gate_r12(ctx, manifest).status, rg.PENDING)
        manifest.write_text("# Release manifest\n\nNot frozen.\n", encoding="utf-8")
        self.assertEqual(rg.gate_r12(ctx, manifest).status, rg.PENDING)
        gates = [rg.Gate("R1", "x", rg.PASS, "ok | with bar")]
        manifest.write_text(rg.render_manifest(ctx, gates), encoding="utf-8")
        self.assertEqual(rg.manifest_values(manifest.read_text(encoding="utf-8"))["output.csv sha256"],
                         rg.sha256_file(self.output))
        self.assertEqual(rg.gate_r12(ctx, manifest).status, rg.PASS)
        self.output.write_text(output_csv(rows=5), encoding="utf-8")
        gate = rg.gate_r12(ctx, manifest)
        self.assertEqual((gate.status, "output.csv sha256" in gate.detail), (rg.FAIL, True))

    def test_another_candidate_name_is_drift(self) -> None:
        manifest = self.root / rg.MANIFEST_NAME
        manifest.write_text(rg.render_manifest(self.context(), []), encoding="utf-8")
        other = rg.Context("rc2", FakeRunner(), "python3", self.root, self.output, self.archive,
                           self.root / "dataset", self.scratch)
        self.assertIn("release candidate", rg.gate_r12(other, manifest).detail)

    def test_upload_verification(self) -> None:
        ctx = self.context()
        manifest = self.root / rg.MANIFEST_NAME
        manifest.write_text(rg.render_manifest(ctx, []), encoding="utf-8")
        self.assertEqual(rg.verify_upload(manifest, [self.output, self.archive]), [])
        other = self.root / "other.zip"
        build_zip.write_zip({"README.md": b"changed\n"}, other)
        self.assertEqual(len(rg.verify_upload(manifest, [other])), 1)

    def test_summary_counts_and_readiness(self) -> None:
        gates = [rg.Gate("R1", "a", rg.PASS), rg.Gate("R2", "b", rg.PENDING), rg.Gate("R3", "c", rg.FAIL)]
        result = rg.summary("rc1", gates)
        self.assertEqual(result["counts"], {"pass": 1, "fail": 1, "pending": 1, "waived": 0})
        self.assertFalse(result["ready"])
        self.assertTrue(rg.summary("rc1", [rg.Gate("R1", "a", rg.PASS)])["ready"])

    def test_run_gates_returns_every_gate_in_order(self) -> None:
        def write(arguments: Sequence[str]) -> None:
            if "--out" in arguments and "main.py" in " ".join(arguments):
                Path(arguments[arguments.index("--out") + 1]).write_text(output_csv(), encoding="utf-8")
        runner = FakeRunner({"evaluation score --pred": rg.Completed(0, json.dumps({"normalized": {}}))}, on_call=write)
        with mock.patch.object(rg, "gate_r7", return_value=rg.Gate("R7", "p", rg.PENDING)):
            gates = rg.run_gates(self.context(runner), self.root / rg.MANIFEST_NAME)
        self.assertEqual([g.gate_id for g in gates], ["R%d" % n for n in range(1, 13)])


class WaiverTests(Scratch):
    GATES = [rg.Gate("R1", "a", rg.PASS, "ok"), rg.Gate("R4", "b", rg.FAIL, "not drawn | x"),
             rg.Gate("R9", "c", rg.PENDING, "no record"), rg.Gate("R12", "d", rg.PENDING, "not frozen")]

    def test_parse_waivers_needs_a_reason_for_every_waiver(self) -> None:
        self.assertEqual(rg.parse_waivers(["r4", "R9"], ["R4=sample not drawn", "R9 = scores below"]),
                         {"R4": "sample not drawn", "R9": "scores below"})
        for ids, reasons in ((["R4"], []), ([], ["R4=why"]), (["R4"], ["R4="]), (["R4"], ["R4 why"]),
                              (["R12"], ["R12=why"]), (["R13"], ["R13=why"]), (["x"], ["x=why"])):
            with self.assertRaises(ValueError, msg=(ids, reasons)):
                rg.parse_waivers(ids, reasons)

    def test_a_waived_gate_is_waived_never_pass(self) -> None:
        gates = rg.apply_waivers(self.GATES, {"R1": "not needed", "R4": "owner decision"})
        self.assertEqual([g.status for g in gates], [rg.PASS, rg.WAIVED, rg.PENDING, rg.PENDING])
        self.assertIn("owner decision", gates[1].detail)
        self.assertIn("underlying fail", gates[1].detail)
        self.assertEqual(rg.summary("rc4", gates)["counts"], {"pass": 1, "fail": 0, "pending": 2, "waived": 1})

    def test_only_unwaived_non_passing_gates_block_a_freeze(self) -> None:
        self.assertEqual([g.gate_id for g in rg.blocking_gates(self.GATES)], ["R4", "R9"])
        waived = rg.apply_waivers(self.GATES, {"R4": "a"})
        self.assertEqual([g.gate_id for g in rg.blocking_gates(waived)], ["R9"])
        waived = rg.apply_waivers(self.GATES, {"R4": "a", "R9": "b"})
        self.assertEqual(rg.blocking_gates(waived), [])
        self.assertTrue(rg.summary("rc4", [g for g in waived if g.gate_id != "R12"])["ready"])

    def test_manifest_lists_waivers_changes_and_hashes(self) -> None:
        ctx = self.context()
        gates = rg.apply_waivers(self.GATES[:3], {"R4": "owner decision"})
        text = rg.render_manifest(ctx, gates, {"R4": "owner decision"}, "- fixed x\n", "2026-10-25")
        self.assertIn("| R4 | b | waived |", text)
        self.assertNotIn("| R4 | b | pass |", text)
        self.assertIn("- R4: owner decision", text)
        self.assertIn("- fixed x", text)
        recorded = rg.manifest_values(text)
        self.assertEqual(recorded["date"], "2026-10-25")
        self.assertEqual(recorded["zip file sha256"], rg.sha256_file(self.archive))
        self.assertEqual(recorded["zip content hash"], rg.zip_content_hash(self.archive))
        self.assertNotIn("## Waivers", rg.render_manifest(ctx, gates))


class CommandLineTests(Scratch):
    def run_cli(self, *arguments: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rg.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_missing_inputs_are_an_input_error(self) -> None:
        code, _out, err = self.run_cli("--output", str(self.root / "nope.csv"), "--zip", str(self.archive),
                                       "--dataset", str(self.root / "dataset"))
        self.assertEqual(code, rg.EXIT_INPUT)
        self.assertIn("does not exist", err)

    def freeze_args(self, *extra: str):
        manifest = self.root / rg.MANIFEST_NAME
        return manifest, self.run_cli("--rc", "rc1", "--output", str(self.output), "--zip", str(self.archive),
                                      "--dataset", str(self.root / "dataset"), "--manifest", str(manifest),
                                      "--freeze", *extra)

    def gates(self, statuses: Dict[str, str]) -> List[rg.Gate]:
        return [rg.Gate("R%d" % n, "g", statuses.get("R%d" % n, rg.PASS), "d") for n in range(1, 13)]

    def test_freeze_needs_every_unwaived_gate_to_pass(self) -> None:
        gates = self.gates({"R4": rg.FAIL, "R9": rg.PENDING, "R12": rg.PENDING})
        with mock.patch.object(rg, "run_gates", return_value=gates):
            manifest, (code, out, err) = self.freeze_args()
            self.assertEqual(code, rg.EXIT_NOT_READY)
            self.assertIn("not frozen: R4 fail, R9 pending", err)
            self.assertFalse(manifest.exists())
            manifest, (code, _out, err) = self.freeze_args("--waive", "R4", "--waiver-reason", "R4=why")
            self.assertEqual(code, rg.EXIT_NOT_READY)
            self.assertIn("R9 pending", err)
            self.assertFalse(manifest.exists())

    def test_freeze_with_waivers_writes_the_reasons_and_keeps_them_waived(self) -> None:
        gates = self.gates({"R4": rg.FAIL, "R9": rg.FAIL, "R12": rg.PENDING})
        changes = self.root / "changes.md"
        changes.write_text("- fixed x\n", encoding="utf-8")
        with mock.patch.object(rg, "run_gates", return_value=gates):
            manifest, (code, out, _err) = self.freeze_args(
                "--waive", "R4", "--waive", "R9", "--waiver-reason", "R4=sample not drawn",
                "--waiver-reason", "R9=scores below the bar", "--changes-file", str(changes))
        self.assertEqual(code, rg.EXIT_OK)
        counts = json.loads(out)["counts"]
        self.assertEqual(counts, {"pass": 10, "fail": 0, "pending": 0, "waived": 2})
        text = manifest.read_text(encoding="utf-8")
        self.assertIn("| R4 | g | waived |", text)
        self.assertIn("| R12 | Freeze manifest | pass |", text)
        self.assertIn("- R4: sample not drawn", text)
        self.assertIn("- R9: scores below the bar", text)
        self.assertIn("- fixed x", text)
        self.assertEqual(rg.verify_upload(manifest, [self.output, self.archive]), [])

    def test_bad_waivers_are_an_input_error(self) -> None:
        code, _out, err = self.run_cli("--waive", "R4")
        self.assertEqual(code, rg.EXIT_INPUT)
        self.assertIn("needs --waiver-reason", err)
        self.assertEqual(self.run_cli("--waive", "R12", "--waiver-reason", "R12=x")[0], rg.EXIT_INPUT)

    def test_verify_upload_mode(self) -> None:
        manifest = self.root / rg.MANIFEST_NAME
        manifest.write_text(rg.render_manifest(self.context(), []), encoding="utf-8")
        code, out, _err = self.run_cli("--manifest", str(manifest), "--verify-upload", str(self.output), str(self.archive))
        self.assertEqual((code, "match" in out), (rg.EXIT_OK, True))
        self.output.write_text("changed", encoding="utf-8")
        self.assertEqual(self.run_cli("--manifest", str(manifest), "--verify-upload", str(self.output))[0], rg.EXIT_NOT_READY)


if __name__ == "__main__":
    unittest.main()
