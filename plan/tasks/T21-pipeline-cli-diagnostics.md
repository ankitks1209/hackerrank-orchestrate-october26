# T21 — Pipeline orchestration, CLI, diagnostics

| Field | Value |
|---|---|
| ID | T21 |
| Milestone | M4 |
| Depends on | T18b, T19, T20, T22, T11b |
| Size | S |
| SPEC refs | A1, N6, N7 |

## Files
- `code/ghostaudit/pipeline.py`
- `code/main.py`
- `code/ghostaudit/diagnostics.py`
- `code/tests/test_pipeline_smoke.py`

## Description
Wire the whole system behind a thin CLI.

## Implementation notes
- `pipeline.run(config, reader, llm) -> RunResult`:
  1. media pre-pass (`extract_media_facts`);
  2. build the index;
  3. intent;
  4. links;
  5. per-case build and emit;
  6. inline contract validation.
  It is orchestration only.
- `main.py` flags:
  - `--dataset`;
  - `--out` (default `<repo>/output.csv`);
  - `--llm {off,cache,live}` (default `cache`);
  - `--signature {on,off}` (default on);
  - `--intent-model ID` and `--media-model ID` (strategy comparison);
  - `--llm batch` (optional);
  - `--flags k=v,...`;
  - `--diag DIR`;
  - `--include-samples`;
  - `--samples-out PATH` (default `<diag>/sample_predictions.csv`);
  - `--verbose`.
  Exit non-zero on a contract violation.
- Diagnostics Markdown:
  - per-case reasons;
  - link and account basis;
  - flags fired;
  - cache misses;
  - evidence/template disagreements;
  - unknown events;
  - intent agreement matrix;
  - stage timings.
- Only eval cases go to `--out`. Samples go to `--samples-out`.
- A missing or incomplete `dataset/` makes main exit with a clear message (exit code 2), not a traceback. Each emitted step carries its provenance locator (file plus row/line/snapshot) in diagnostics, for T32.

## Acceptance criteria
- [ ] `python3 code/main.py` writes 518 valid rows in under 5 s with a warm cache.
- [ ] `--llm off` also completes with 518 valid rows (N7).
- [ ] `python3 code/main.py --help` works from the repo root.

## Tests
- Smoke test on a tiny synthetic dataset, with temp `--out`/`--diag`.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
