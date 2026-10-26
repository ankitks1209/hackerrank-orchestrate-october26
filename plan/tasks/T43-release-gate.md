# T43 — Release gate and freeze manifest

| Field | Value |
|---|---|
| ID | T43 |
| Milestone | M7 |
| Depends on | T32, T33, T34, T35, T37, T38, T39, T40, T42, T24 |
| Size | S |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §8 R1–R12 |

## Files
- `code/tools/release_gate.py`
- `code/evaluation/RELEASE_CHECKLIST.md`
- `code/evaluation/RELEASE_MANIFEST.md`

## Description
Run every automated gate in under 2 minutes, record the agent-panel results, and freeze the single submission.

## Implementation notes
- `release_gate.py` runs R1–R3, R6–R8, R10 and R11, then reads the R4/R5/R9 panel results from their Markdown records. It writes a JSON summary and exits non-zero on any failure.
- Pareto comparison against the previous rc (T23 `compare`).
- Freeze: `RELEASE_MANIFEST.md` holds the sha256 of `output.csv`, the zip content hash and the dataset hash. The final log entry cites them. Git commits and tags happen **only with the user's consent**; otherwise the manifest is the freeze.
- Before upload, verify that the files actually chosen for upload match the manifest.

## Acceptance criteria
- [ ] All R1–R12 pass for `rc-final`. The manifest is written and the final log entry is appended.

## Tests
- Dry run on rc1.

## Risks
- Gate fatigue near the deadline. The automated gates are fast, and the panels run only at rc milestones.

## Definition of Done
See `README.md` § Definition of Done.
