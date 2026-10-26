# T37 — Code-judge simulation panel (calibrated)

| Field | Value |
|---|---|
| ID | T37 |
| Milestone | M7 |
| Depends on | T34, T35, T30b, T30 |
| Size | M |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §5, R9 |

## Files
- `code/evaluation/JUDGE_PANEL.md (rubric and results; agent run via workflow)`

## Description
Estimate the Code zip score before the single submission, and turn every deduction into a fix.

## Implementation notes
- Three personas review the **unzipped** submission (which excludes `plan/`, `solution/` and raw data):
  1. a strict rules-compliance judge (AGENTS §6.7 shortcuts and hard-coded labels; learned-signature disclosure);
  2. a senior code-quality reviewer;
  3. a README-literal newcomer who runs the clean room.
- Rubric: runnability 6, architecture 6, safeguards 4, AI usage 5, evaluation report 5, usage report 2, hygiene 2. Extras:
  - tests run without data;
  - `--help` on every CLI;
  - error paths;
  - ruff clean (run from scratch, not shipped);
  - tests pass under `-W error::DeprecationWarning`;
  - no commented-out code;
  - read budget (README ≤ 15 KB, non-raw text ≤ 400 KB).
- **Calibrate first:** give the panel a seeded-defect zip with a broken README command and missing usage fields. The rubric prompt is adjusted until all three personas catch both defects.
- At most 3 fix rounds. Each deduction becomes a task.

## Acceptance criteria
- [ ] The lowest persona score is ≥ 28.5 and 0 blocker/major deductions remain.
- [ ] The calibration run caught both seeded defects.

## Tests
- Panel run results recorded in JUDGE_PANEL.md.

## Risks
- LLM score variance (±1–2). Gate on blockers as well as the score.

## Definition of Done
See `README.md` § Definition of Done.
