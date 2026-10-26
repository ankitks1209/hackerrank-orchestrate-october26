# T27 — Determinism, performance and static-isolation tests

| Field | Value |
|---|---|
| ID | T27 |
| Milestone | M5 |
| Depends on | T21 |
| Size | S |
| SPEC refs | N1–N5 |

## Files
- `code/tests/test_determinism.py`
- `code/tests/test_static.py`

## Description
Prove the non-functional requirements.

## Implementation notes
- Run `main.py` twice in subprocesses with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=4242` and compare the bytes. Every invocation of `main.py` in a test passes `--out` and `--diag` under `tempfile.mkdtemp()`, so the submission `output.csv` is never overwritten.
- Wall time with `--llm cache` must be under 5 s. Print stage timings.
- Static checks, scoped to `code/ghostaudit/**` and `code/main.py` (tests and package_check are exempt):
  - no import, open or Path use of `solution/` (usage regex);
  - no `sample_output`;
  - no `os.environ` outside `config.py`;
  - no numeric window literals outside `config.py`;
  - no `print(`;
  - no id arithmetic on `user_`/`case_` numbers;
  - **no literal eval ids**: the regex `case_(\d+)` with a number ≥ 33, or any `user_\d+` literal, is rejected in `ghostaudit/**`; tests may use only sample ids ≤ case_32.
- Run `python3 code/tools/check_log.py log.txt` (T31); it must exit 0.
- Repo-wide test check: no test calls `main.py` without `--out`.
- Data consistency: every non-noise activity row's system_id and every parsed evidence system_id agree with `policy.SYSTEM_BY_PREFIX` (0 conflicts); rules 04/08/11 never fire.
- Run the suite with the system `python3` (3.9).

## Acceptance criteria
- [ ] All checks pass on Python 3.9.6.

## Tests
- This task is the tests.

## Risks
- Timing flakiness. The 5 s gate is generous; report the actual time.

## Definition of Done
See `README.md` § Definition of Done.
