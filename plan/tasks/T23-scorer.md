# T23 — Scorer metrics and evaluation CLI

| Field | Value |
|---|---|
| ID | T23 |
| Milestone | M5 |
| Depends on | T22, T20 |
| Size | M |
| SPEC refs | IMPLEMENTATION_PLAN §8 metrics |

## Files
- `code/evaluation/scoring.py`
- `code/evaluation/main.py`
- `code/tests/test_scoring.py`

## Description
Score predictions against `sample_output.csv` using the metrics the report requires.

## Implementation notes
- Use `tests/gold.py` `GoldReader`. `evaluation/main.py` inserts `code/` into `sys.path`.
- Grader family G1–G8 (LOCAL_EVALUATION_STRATEGY §3):
  - G1 status;
  - G2 case-exact (**row-level**);
  - G3 step P/R/F1;
  - G4 step-F1 without evidence;
  - G5 key-aligned field accuracy;
  - G6 LCS plus exact order;
  - G7 composite;
  - G8 `step_no`-aligned positional accuracy.
  Each is also reported **normalized by its ceiling**. An error-taxonomy table covers status, missing, extra, wrong op/state, wrong evidence, order, identity miss and structural.
- `compare(prev_rc, cur_rc)` gives the Pareto no-regression verdict across the normalized graders, with a tolerance.
- `evaluation/main.py` runs the sample pipeline itself when no `--pred` file exists, so README command 2 works standalone.
- CLI: `python3 code/evaluation/main.py [--pred PATH (default: the --samples-out path)] [--ablate] [--custom]`. Prints Markdown tables.

## Acceptance criteria
- [ ] Gold scored against itself gives 1.0 on every metric.
- [ ] Each perturbation (swap, drop, wrong evidence_id) moves exactly the expected metrics.
- [ ] `--help` works from the repo root.

## Tests
- Perturbation tests per metric.

## Risks
- The alignment definition must be stated in the report so the numbers can be interpreted.

## Definition of Done
See `README.md` § Definition of Done.
