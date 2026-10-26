"""Release gate R1-R12 and the freeze manifest (T43; LOCAL_EVALUATION_STRATEGY 8).

Runs every automated gate against one release candidate and writes a JSON summary. Each gate ends
`pass`, `fail`, `pending` (an agent panel or a user decision has not produced its record yet, or the
strict regime of a test cannot run) or `waived`. The exit code is 0 only when nothing failed and nothing
is pending; `--allow-pending` accepts pending gates for a dry run.

A waiver is an explicit, recorded decision of the repository owner to ship although a gate does not pass:
`--waive R4 --waiver-reason "R4=why"`. A waived gate is reported as `waived`, never as `pass`, keeps the
underlying result in its detail, and its reason is written into the manifest. Only a gate that failed or
is pending can be waived (a passing gate stays `pass`), every waiver needs a reason, and R12 cannot be
waived. `--freeze` is allowed only when every gate other than R12 is `pass` or `waived`.

    R1  fresh pipeline run: contract-clean, byte-identical to the submitted output.csv, exact format
    R2  golden sample gate (tests.test_golden)
    R3  label-free P2a-c: no failure, nothing unexplained          (python -m evaluation verify)
    R4  blind-audit estimation record                                (audit/estimation_result.md)
    R5  blind-audit coverage record                                  (audit/coverage_result.md)
    R6  P5 invariants                                                (python -m evaluation verify)
    R7  Pareto no-regression against the previous candidate         (python -m evaluation score --json)
    R8  clean-room matrix                                            (devtools/clean_room.py)
    R9  code and transcript panels and the transcript linter         (JUDGE_PANEL.md, check_log.py)
    R10 override ban: static scan, relabeling, late evidence, narrow rules
    R11 package listing and text checks, report and ledger consistency  (python -m tools.build_zip, python -m tools.render_reports, devtools/confidence.py)
    R12 freeze manifest and upload verification                      (RELEASE_MANIFEST.md)

Panel records are Markdown files with `Key: value` lines (see `devtools/RELEASE_CHECKLIST.md`).
`--freeze` writes `RELEASE_MANIFEST.md` (date, sha256 of `output.csv`, the zip file sha256 and content
hash, the dataset hash, the gate table, the waivers and the changes since the previous candidate). Git commits and tags are not made here: they need the user's consent.

    python3 devtools/release_gate.py --rc rc1 --zip code.zip [--allow-pending] [--summary gate.json]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

DEVTOOLS_DIR = Path(__file__).resolve().parent
CODE_DIR = DEVTOOLS_DIR.parent / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from evaluation.scoring import compare  # noqa: E402
from ghostaudit.config import COMPARE_TOLERANCE, EVAL_REQUEST_COUNT  # noqa: E402
from tools import build_zip  # noqa: E402

REPO_ROOT = CODE_DIR.parent
PASS, FAIL, PENDING, WAIVED = "pass", "fail", "pending", "waived"
UNWAIVABLE = ("R12",)
EXIT_OK = 0
EXIT_NOT_READY = 1
EXIT_INPUT = 2
OUTPUT_HEADER = "case_id,deletion_status,steps_json"
MANIFEST_NAME = "RELEASE_MANIFEST.md"
ESTIMATION_RECORD = DEVTOOLS_DIR / "audit" / "estimation_result.md"
COVERAGE_RECORD = DEVTOOLS_DIR / "audit" / "coverage_result.md"
PANEL_RECORD = DEVTOOLS_DIR / "JUDGE_PANEL.md"
MIN_CODE_SCORE = 28.5
MIN_TRANSCRIPT_SCORE = 9.5
OVERRIDE_BAN_TESTS = ("test_static.py", "test_relabel.py", "test_late_evidence.py", "test_narrow_rules.py")
SKIPPED_MARK = "skipped"

Runner = Callable[[Sequence[str]], "Completed"]


@dataclass(frozen=True)
class Completed:
    returncode: int
    output: str


@dataclass(frozen=True)
class Gate:
    gate_id: str
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Context:
    """Everything the gates need, with the command runner injected."""

    rc: str
    run: Runner
    python: str
    root: Path
    output: Path
    archive: Path
    dataset: Path
    scratch: Path
    previous_scores: Optional[Path] = None
    scores_out: Optional[Path] = None
    metrics_dir: Optional[Path] = None
    clean_room_pythons: Tuple[str, ...] = ()
    forbidden: Tuple[str, ...] = ()


def shell_runner(arguments: Sequence[str]) -> Completed:
    """Run a command with `code/` on PYTHONPATH, so `python -m evaluation` and `python -m tools.*` resolve."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(CODE_DIR), environment.get("PYTHONPATH", "")]))
    done = subprocess.run(list(arguments), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, env=environment)
    return Completed(done.returncode, done.stdout)


def record_values(text: str) -> Dict[str, str]:
    """`Key: value` lines of a panel record, keys lower-cased; the last occurrence wins."""
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip("*- "):
            values[key.strip("*- ").lower()] = value.strip("* ")
    return values


def _number(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_hash(dataset: Path) -> str:
    """One hash over every dataset file (relative path and content hash), in sorted order."""
    lines = ["%s\0%s\n" % (path.relative_to(dataset).as_posix(), sha256_file(path))
             for path in sorted(dataset.rglob("*")) if path.is_file()]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def zip_content_hash(archive: Path) -> str:
    """The content hash `build_zip` reports, recomputed from the archive itself."""
    with zipfile.ZipFile(str(archive)) as bundle:
        files = {name: bundle.read(name) for name in bundle.namelist()}
    return build_zip.content_hash(build_zip.manifest(files))


def natural_key(case_id: str) -> Tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", case_id))


def output_format_problems(path: Path) -> List[str]:
    """Header, line endings, row count and natural order of the submitted output.csv."""
    raw = path.read_bytes()
    problems = []
    if b"\r" in raw:
        problems.append("CR in output.csv")
    lines = raw.decode("utf-8").split("\n")
    if lines[0] != OUTPUT_HEADER:
        problems.append("header is not %s" % OUTPUT_HEADER)
    ids = [line.split(",", 1)[0] for line in lines[1:] if line]
    if len(ids) != EVAL_REQUEST_COUNT:
        problems.append("%d rows, expected %d" % (len(ids), EVAL_REQUEST_COUNT))
    if ids != sorted(ids, key=natural_key):
        problems.append("rows are not in natural case order")
    return problems


def gate_r1(ctx: Context) -> Gate:
    name = "Validator and byte-identical rerun"
    fresh, samples, diag = ctx.scratch / "output.csv", ctx.scratch / "samples.csv", ctx.scratch / "diag"
    done = ctx.run([ctx.python, str(CODE_DIR / "main.py"), "--include-samples", "--samples-out", str(samples),
                    "--out", str(fresh), "--diag", str(diag)])
    if done.returncode != 0:
        return Gate("R1", name, FAIL, "pipeline exited %d: %s" % (done.returncode, done.output.strip()[-200:]))
    problems = output_format_problems(ctx.output)
    if ctx.output.read_bytes() != fresh.read_bytes():
        problems.append("submitted output.csv differs from a fresh run")
    return Gate("R1", name, FAIL if problems else PASS, "; ".join(problems) or "contract clean, bytes identical")


def gate_r2(ctx: Context) -> Gate:
    name = "Golden sample gate"
    done = ctx.run([ctx.python, "-m", "unittest", "discover", "-s", str(CODE_DIR / "tests"), "-t", str(CODE_DIR),
                    "-p", "test_golden.py", "-v"])
    if done.returncode != 0:
        return Gate("R2", name, FAIL, done.output.strip()[-300:])
    if SKIPPED_MARK in done.output:
        return Gate("R2", name, PENDING, "the strict regime is skipped until the media cache is complete")
    return Gate("R2", name, PASS, "status 32/32 and exact >= 30/32 with the pinned misses")


def run_verification(ctx: Context) -> Completed:
    return ctx.run([ctx.python, "-m", "evaluation", "verify", "--pred", str(ctx.scratch / "output.csv"),
                    "--samples-pred", str(ctx.scratch / "samples.csv"),
                    "--diag", str(ctx.scratch / "diag" / "diagnostics.md")])


def _integers(lines: Sequence[str], prefix: str) -> List[int]:
    """The integers that follow `prefix` on the lines that start with it."""
    return [int(line[len(prefix):]) for line in lines if line.startswith(prefix) and line[len(prefix):].isdigit()]


def gate_r3(report: Completed) -> Gate:
    name = "Label-free P2a-c"
    lines = report.output.splitlines()
    failures, unexplained = _integers(lines, "- Failures: "), _integers(lines, "- Unexplained: ")
    if not failures or not unexplained:
        return Gate("R3", name, FAIL, "verification report unreadable (exit %d)" % report.returncode)
    problems = []
    if failures[0]:
        problems.append("%d locator failures" % failures[0])
    if sum(unexplained):
        problems.append("%d unexplained sweep items" % sum(unexplained))
    return Gate("R3", name, FAIL if problems else PASS, "; ".join(problems) or "no failure, nothing unexplained")


def gate_r6(report: Completed) -> Gate:
    name = "P5 invariants"
    rows = [line.split("|") for line in report.output.splitlines() if line.startswith("| ") and " | hard | " in line]
    if not rows:
        return Gate("R6", name, FAIL, "no invariant table in the verification report")
    failed = [cells[1].strip() for cells in rows if cells[3].strip() != "0"]
    return Gate("R6", name, FAIL if failed else PASS, ("failed: " + ", ".join(failed)) if failed else
                "%d hard invariants hold" % len(rows))


def gate_record(gate_id: str, name: str, path: Path, check: Callable[[Mapping[str, str]], Optional[str]]) -> Gate:
    """A gate decided by a Markdown record; a missing record leaves it pending."""
    if not path.is_file():
        return Gate(gate_id, name, PENDING, "no record at %s" % path.name)
    problem = check(record_values(path.read_text(encoding="utf-8")))
    return Gate(gate_id, name, FAIL if problem else PASS, problem or "record accepted")


def check_coverage(values: Mapping[str, str]) -> Optional[str]:
    unresolved = _number(values.get("unresolved defects"))
    if unresolved is None:
        return "no 'Unresolved defects' line"
    return None if unresolved == 0 else "%d unresolved defects" % unresolved


def gate_r4(ctx: Context) -> Gate:
    name = "Blind-audit estimation sample"
    if not ESTIMATION_RECORD.is_file():
        return Gate("R4", name, PENDING, "no record at estimation_result.md")
    text = ESTIMATION_RECORD.read_text(encoding="utf-8")
    ok = "| Gate | pass |" in text and "| Status errors | 0 |" in text
    return Gate("R4", name, PASS if ok else FAIL, "record accepted" if ok else "gate row is not pass or status errors exist")


def gate_r5(ctx: Context) -> Gate:
    return gate_record("R5", "Blind-audit coverage set", COVERAGE_RECORD, check_coverage)


def gate_r7(ctx: Context) -> Gate:
    name = "Pareto no-regression"
    done = ctx.run([ctx.python, "-m", "evaluation", "score", "--pred", str(ctx.scratch / "samples.csv"), "--json"])
    if done.returncode != 0:
        return Gate("R7", name, FAIL, "scorer exited %d" % done.returncode)
    current = json.loads(done.output)["normalized"]
    if ctx.scores_out is not None:
        ctx.scores_out.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if ctx.previous_scores is None or not ctx.previous_scores.is_file():
        return Gate("R7", name, PENDING, "no previous candidate to compare with; scores recorded")
    verdict = compare(json.loads(ctx.previous_scores.read_text(encoding="utf-8")), current, COMPARE_TOLERANCE)
    return Gate("R7", name, PASS if verdict.ok else FAIL,
                "no grader regressed" if verdict.ok else "regressed: " + ", ".join(verdict.regressions))


def gate_r8(ctx: Context) -> Gate:
    name = "Clean-room matrix"
    command = [ctx.python, str(DEVTOOLS_DIR / "clean_room.py"), "--zip", str(ctx.archive),
               "--dataset", str(ctx.dataset)]
    for interpreter in ctx.clean_room_pythons:
        command += ["--python", interpreter]
    done = ctx.run(command)
    if done.returncode == 0:
        return Gate("R8", name, PASS, "every cell byte-identical, no cache miss, no-dataset run clean")
    problems = [line for line in done.output.splitlines() if line.startswith("- ")]
    return Gate("R8", name, FAIL, "; ".join(problems[:3]) or "exit %d" % done.returncode)


def gate_r9(ctx: Context) -> Gate:
    name = "Code and transcript panels"
    lint = ctx.run([ctx.python, str(DEVTOOLS_DIR / "check_log.py"), str(ctx.root / "log.txt")])
    if lint.returncode != 0:
        return Gate("R9", name, FAIL, "check_log.py exited %d" % lint.returncode)
    if not PANEL_RECORD.is_file():
        return Gate("R9", name, PENDING, "no record at JUDGE_PANEL.md (linter clean)")
    values = record_values(PANEL_RECORD.read_text(encoding="utf-8"))
    code, transcript = _number(values.get("lowest code score")), _number(values.get("transcript score"))
    blockers = _number(values.get("blockers"))
    problems = []
    if values.get("calibration", "").lower() != "pass":
        problems.append("panel not calibrated")
    if code is None or code < MIN_CODE_SCORE:
        problems.append("lowest code score %s < %.1f" % (code, MIN_CODE_SCORE))
    if blockers != 0:
        problems.append("blockers: %s" % blockers)
    if transcript is None or transcript < MIN_TRANSCRIPT_SCORE:
        problems.append("transcript score %s < %.1f" % (transcript, MIN_TRANSCRIPT_SCORE))
    return Gate("R9", name, FAIL if problems else PASS, "; ".join(problems) or "panels accepted, linter clean")


def gate_r10(ctx: Context) -> Gate:
    name = "Override ban"
    failed = []
    for module in OVERRIDE_BAN_TESTS:
        done = ctx.run([ctx.python, "-m", "unittest", "discover", "-s", str(CODE_DIR / "tests"), "-t", str(CODE_DIR),
                        "-p", module])
        if done.returncode != 0:
            failed.append(module)
    return Gate("R10", name, FAIL if failed else PASS, ("failed: " + ", ".join(failed)) if failed else
                "static scan, relabeling, late evidence and narrow-rule review pass")


def gate_r11(ctx: Context) -> Gate:
    name = "Package checks"
    command = [ctx.python, "-m", "tools.build_zip", "--root", str(ctx.root), "--out",
               str(ctx.scratch / "check.zip"), "--dataset", str(ctx.dataset)]
    for text in ctx.forbidden:
        command += ["--forbid", text]
    done = ctx.run(command)
    problems = [line for line in done.output.splitlines() if line.startswith("check failed")]
    if done.returncode != 0:
        return Gate("R11", name, FAIL, "; ".join(problems[:4]) or "build_zip exited %d" % done.returncode)
    ledger = ctx.run([ctx.python, str(DEVTOOLS_DIR / "confidence.py"), "--check"])
    if ledger.returncode != 0:
        return Gate("R11", name, FAIL, "the provenance ledger in DECISIONS.md is stale (confidence.py --check)")
    if ctx.metrics_dir is None:
        return Gate("R11", name, PENDING, "archive checks pass; no metrics directory for render_reports --check")
    check = ctx.run([ctx.python, "-m", "tools.render_reports", "--metrics-dir", str(ctx.metrics_dir),
                     "--check"])
    return Gate("R11", name, PASS if check.returncode == 0 else FAIL,
                "archive and reports consistent" if check.returncode == 0 else "render_reports --check exited %d" % check.returncode)


def freeze_values(ctx: Context) -> Dict[str, str]:
    return {"output.csv sha256": sha256_file(ctx.output), "zip file sha256": sha256_file(ctx.archive),
            "zip content hash": zip_content_hash(ctx.archive), "dataset hash": dataset_hash(ctx.dataset)}


def gate_r12(ctx: Context, manifest: Path) -> Gate:
    name = "Freeze manifest"
    recorded = manifest_values(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    if "release candidate" not in recorded:
        return Gate("R12", name, PENDING, "not frozen: %s holds no release candidate" % MANIFEST_NAME)
    current = freeze_values(ctx)
    drift = [key for key, value in current.items() if recorded.get(key) != value]
    if recorded.get("release candidate") != ctx.rc:
        drift.append("release candidate")
    return Gate("R12", name, FAIL if drift else PASS, ("changed since the freeze: " + ", ".join(drift)) if drift
                else "manifest matches output, archive and dataset")


def manifest_values(text: str) -> Dict[str, str]:
    """`| key | value |` rows of the manifest table (value without backticks)."""
    values = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 2 and cells[0] not in ("Field", "---"):
            values[cells[0]] = cells[1].strip("`")
    return values


def parse_waivers(ids: Sequence[str], reasons: Sequence[str]) -> Dict[str, str]:
    """`--waive` ids and `--waiver-reason ID=text` pairs as {gate id: reason}; ValueError on a bad waiver."""
    reason_by_id = {}
    for entry in reasons:
        gate_id, separator, text = entry.partition("=")
        if not separator or not text.strip():
            raise ValueError("--waiver-reason needs the form ID=reason, got %r" % entry)
        reason_by_id[gate_id.strip().upper()] = text.strip()
    waivers = {}
    for raw in ids:
        gate_id = raw.strip().upper()
        if not re.fullmatch(r"R(?:[1-9]|1[0-2])", gate_id):
            raise ValueError("cannot waive %r: not a gate id R1-R12" % raw)
        if gate_id in UNWAIVABLE:
            raise ValueError("%s cannot be waived" % gate_id)
        if gate_id not in reason_by_id:
            raise ValueError("waiving %s needs --waiver-reason %s=<reason>" % (gate_id, gate_id))
        waivers[gate_id] = reason_by_id[gate_id]
    for gate_id in reason_by_id:
        if gate_id not in waivers:
            raise ValueError("--waiver-reason for %s without --waive %s" % (gate_id, gate_id))
    return waivers


def apply_waivers(gates: Sequence[Gate], waivers: Mapping[str, str]) -> List[Gate]:
    """Gates with every failed or pending waived gate marked `waived`; a passing gate stays `pass`."""
    result = []
    for gate in gates:
        if gate.gate_id in waivers and gate.status in (FAIL, PENDING):
            detail = "WAIVED (%s): %s [underlying %s: %s]" % (gate.gate_id, waivers[gate.gate_id], gate.status, gate.detail)
            gate = Gate(gate.gate_id, gate.name, WAIVED, detail)
        result.append(gate)
    return result


def blocking_gates(gates: Sequence[Gate]) -> List[Gate]:
    """Gates that stop a freeze: everything except R12 that is neither `pass` nor `waived`."""
    return [g for g in gates if g.gate_id not in UNWAIVABLE and g.status not in (PASS, WAIVED)]


def render_manifest(ctx: Context, gates: Sequence[Gate], waivers: Optional[Mapping[str, str]] = None,
                    changes: str = "", frozen_on: Optional[str] = None) -> str:
    rows = [("release candidate", ctx.rc), ("date", frozen_on or datetime.date.today().isoformat())]
    rows += list(freeze_values(ctx).items())
    lines = ["# Release manifest", "", "| Field | Value |", "|---|---|"]
    lines += ["| %s | `%s` |" % row for row in rows]
    lines += ["", "## Gates at the freeze", "", "| Gate | Name | Status | Detail |", "|---|---|---|---|"]
    lines += ["| %s | %s | %s | %s |" % (g.gate_id, g.name, g.status, g.detail.replace("|", "/")) for g in gates]
    if waivers:
        lines += ["", "## Waivers", "", "Recorded decisions to freeze although these gates do not pass. A waived gate is not a pass.", ""]
        lines += ["- %s: %s" % (gate_id, waivers[gate_id]) for gate_id in sorted(waivers, key=lambda g: int(g[1:]))]
    if changes.strip():
        lines += ["", "## Changes since the previous candidate", "", changes.strip()]
    lines += ["", "Commits and tags are made only with the user's consent. Before upload, run "
              "`release_gate.py --verify-upload <output.csv> <code.zip>` to compare the chosen files with this manifest.", ""]
    return "\n".join(lines)


def verify_upload(manifest: Path, files: Sequence[Path]) -> List[str]:
    """Problems when the files chosen for upload do not match the manifest."""
    recorded = manifest_values(manifest.read_text(encoding="utf-8"))
    problems = []
    for path in files:
        if path.suffix == ".zip":
            actual, key = zip_content_hash(path), "zip content hash"
        else:
            actual, key = sha256_file(path), "output.csv sha256"
        if recorded.get(key) != actual:
            problems.append("%s does not match the manifest (%s)" % (path.name, key))
    return problems


def run_gates(ctx: Context, manifest: Path) -> List[Gate]:
    gates = [gate_r1(ctx), gate_r2(ctx)]
    verification = run_verification(ctx) if gates[0].status != FAIL else Completed(1, "")
    gates += [gate_r3(verification), gate_r4(ctx), gate_r5(ctx), gate_r6(verification), gate_r7(ctx),
              gate_r8(ctx), gate_r9(ctx), gate_r10(ctx), gate_r11(ctx), gate_r12(ctx, manifest)]
    return sorted(gates, key=lambda gate: int(gate.gate_id[1:]))


def summary(rc: str, gates: Sequence[Gate]) -> Dict[str, object]:
    return {"release_candidate": rc, "ready": all(g.status in (PASS, WAIVED) for g in gates),
            "counts": {status: sum(1 for g in gates if g.status == status) for status in (PASS, FAIL, PENDING, WAIVED)},
            "gates": [{"id": g.gate_id, "name": g.name, "status": g.status, "detail": g.detail} for g in gates]}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rc", default="rc", help="release candidate name")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--zip", type=Path, default=REPO_ROOT / "code.zip", dest="archive")
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "dataset")
    parser.add_argument("--manifest", type=Path, default=DEVTOOLS_DIR / MANIFEST_NAME)
    parser.add_argument("--previous", type=Path, help="normalized scores of the previous candidate (JSON)")
    parser.add_argument("--scores-out", type=Path, help="write this candidate's normalized scores here")
    parser.add_argument("--metrics-dir", type=Path, help="directory for render_reports --check")
    parser.add_argument("--python", action="append", default=[], dest="pythons", help="interpreter for the clean room")
    parser.add_argument("--forbid", action="append", default=[], help="string that must not ship (repeatable)")
    parser.add_argument("--summary", type=Path, help="write the JSON summary here")
    parser.add_argument("--allow-pending", action="store_true", help="accept pending gates (dry run)")
    parser.add_argument("--freeze", action="store_true", help="write the manifest when every gate but R12 passes or is waived")
    parser.add_argument("--waive", action="append", default=[], metavar="GATE", help="waive a failed or pending gate (repeatable)")
    parser.add_argument("--waiver-reason", action="append", default=[], metavar="GATE=TEXT",
                        help="reason for a waived gate (one per --waive)")
    parser.add_argument("--changes-file", type=Path, help="Markdown text for the manifest: what changed since the previous candidate")
    parser.add_argument("--verify-upload", nargs="+", type=Path, metavar="FILE", help="compare files with the manifest and exit")
    args = parser.parse_args(argv)
    if args.verify_upload:
        problems = verify_upload(args.manifest, args.verify_upload)
        sys.stdout.write("\n".join(problems) + ("\n" if problems else "upload files match the manifest\n"))
        return EXIT_NOT_READY if problems else EXIT_OK
    try:
        waivers = parse_waivers(args.waive, args.waiver_reason)
    except ValueError as problem:
        sys.stderr.write("%s\n" % problem)
        return EXIT_INPUT
    for required in (args.output, args.archive, args.dataset):
        if not required.exists():
            sys.stderr.write("cannot gate: %s does not exist\n" % required)
            return EXIT_INPUT
    with tempfile.TemporaryDirectory() as scratch:
        ctx = Context(args.rc, shell_runner, sys.executable, REPO_ROOT, args.output, args.archive, args.dataset,
                      Path(scratch), args.previous, args.scores_out, args.metrics_dir,
                      tuple(args.pythons), tuple(args.forbid))
        gates = apply_waivers(run_gates(ctx, args.manifest), waivers)
        freeze_blocked = bool(args.freeze and blocking_gates(gates))
        if freeze_blocked:
            sys.stderr.write("not frozen: %s\n" % ", ".join("%s %s" % (g.gate_id, g.status) for g in blocking_gates(gates)))
        elif args.freeze:
            changes = args.changes_file.read_text(encoding="utf-8") if args.changes_file else ""
            frozen_on = datetime.date.today().isoformat()
            others = [g for g in gates if g.gate_id != "R12"]
            args.manifest.write_text(render_manifest(ctx, others, waivers, changes, frozen_on), encoding="utf-8")
            gates = [g if g.gate_id != "R12" else gate_r12(ctx, args.manifest) for g in gates]
            if [g.status for g in gates if g.gate_id == "R12"] == [PASS]:
                args.manifest.write_text(render_manifest(ctx, gates, waivers, changes, frozen_on), encoding="utf-8")
    result = summary(args.rc, gates)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    counts = result["counts"]
    blocked = freeze_blocked or counts[FAIL] or (counts[PENDING] and not args.allow_pending)  # type: ignore[index]
    return EXIT_NOT_READY if blocked else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
