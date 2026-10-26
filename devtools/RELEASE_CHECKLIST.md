# Release checklist

One submission, no feedback afterwards. `python3 devtools/release_gate.py --rc <name> --output output.csv
--zip code.zip` runs the automated gates in about 30 seconds and prints a JSON summary; it exits 0 only
when every gate passes (`--allow-pending` accepts the gates that wait for a panel or a user decision).
A gate is `pass`, `fail`, `pending` or `waived`.

A waiver is the repository owner's explicit decision to freeze although a gate does not pass:
`--waive R4 --waiver-reason "R4=<why>"`, one reason per waived gate. A waived gate is reported as `waived`, never as
`pass`; its reason and the underlying result go into `RELEASE_MANIFEST.md`. Only a failed or pending gate can be
waived, and R12 cannot. `--freeze` writes the manifest only when every gate other than R12 is `pass` or `waived`;
`--changes-file` adds what changed since the previous candidate.

| Gate | What it checks | How it is decided |
|---|---|---|
| R1 | A fresh run is contract-clean and byte-identical to the submitted `output.csv`; header, LF, 518 rows, natural order | automatic |
| R2 | Golden sample gate (`tests/test_golden.py`): status 32/32, row-exact at least 30/32, pinned misses only | automatic; pending while the media cache is empty (the strict regime is skipped) |
| R3 | Label-free P2a-c: no locator failure, nothing unexplained in the recall and coverage sweeps | automatic (`code/evaluation/verify_report.py`) |
| R4 | Blind-audit estimation sample (at least 100 cases drawn after the freeze): visible step-error upper bound at most 1.3 %, no status error | record `devtools/audit/estimation_result.md` |
| R5 | Blind-audit coverage set and the image family adjudicated, every defect fixed by a general rule | record `devtools/audit/coverage_result.md` |
| R6 | P5 invariants (structure, pairing, legal pairs, citation window, audit-record parity) | automatic |
| R7 | Pareto no-regression of the ceiling-normalized graders against the previous candidate | automatic with `--previous scores.json`; `--scores-out` records this candidate's scores |
| R8 | Clean-room matrix: byte-identical output in every cell, no cache miss, clean run without `dataset/`, wall-time gate | automatic (`devtools/clean_room.py`) |
| R9 | Code panel (lowest persona at least 28.5, no blocker, calibrated), transcript panel at least 9.5, `check_log.py` clean | record `devtools/JUDGE_PANEL.md` plus the linter |
| R10 | Override ban: static scan, relabeling test, late-evidence test, narrow-rule review | automatic (four test modules) |
| R11 | Package listing and text checks on the built zip; reports consistent with the scorer and meter; provenance ledger in `DECISIONS.md` current | automatic (`code/tools/build_zip.py`, `code/tools/render_reports.py --check` with `--metrics-dir`, `evaluation/confidence.py --check`) |
| R12 | Freeze manifest matches `output.csv`, the zip content hash and the dataset hash; files chosen for upload verified | `--freeze` writes `RELEASE_MANIFEST.md`; commits and tags only with the user's consent |

## Record formats

Records are Markdown files with `Key: value` lines (keys are case-insensitive, `**bold**` and list dashes are ignored).

- `devtools/audit/estimation_result.md`: the output of `devtools/audit/audit_score.py` for the estimation sample. R4 passes when it holds the rows `| Gate | pass |` and `| Status errors | 0 |`.
- `devtools/audit/coverage_result.md`: `Unresolved defects: <n>`; R5 passes at 0.
- `devtools/JUDGE_PANEL.md`: `Calibration: pass`, `Lowest code score: <n>`, `Blockers: <n>`, `Transcript score: <n>`.

## Order of work

1. Fill the response cache (live run), then regenerate `output.csv` and the reports.
2. Run the gate; fix every `fail` with a general rule, never a per-case override.
3. Run the panels and the audit at the release-candidate milestone, then freeze.
4. After the freeze draw the estimation sample once, score it once, and record R4.
5. `release_gate.py --freeze`, then `--verify-upload output.csv code.zip` right before uploading.
