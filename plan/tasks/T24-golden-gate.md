# T24 — Golden sample regression gate

| Field | Value |
|---|---|
| ID | T24 |
| Milestone | M5 |
| Depends on | T21, T23 |
| Size | S |
| SPEC refs | A2 |

## Files
- `code/tests/test_golden.py`

## Description
Fail the build if sample performance regresses.

## Implementation notes
- Run the pipeline with `--include-samples` and the default learned signature ON, into temp paths. Also run with `--signature off` and record its numbers without gating on them. Every invocation of `main.py` in a test passes `--out` and `--diag` under `tempfile.mkdtemp()`, so the submission `output.csv` is never overwritten.
- Pin the allowed misses to case_18 and case_20, whose audit ids are absent from every participant file. Any other mismatch fails and prints a diff.

## Acceptance criteria
- [ ] Status 32/32. Exact ≥ 30/32. The pinned misses are exactly {case_18, case_20}.

## Tests
- This task is the test.

## Risks
- Overfitting pressure. Fixes must cite a SPEC rule, never a case id.

## Definition of Done
See `README.md` § Definition of Done.
