# T38 — check_log v2 and transcript panel

| Field | Value |
|---|---|
| ID | T38 |
| Milestone | M7 |
| Depends on | T31 |
| Size | S |
| SPEC refs | AGENTS §5; LOCAL_EVALUATION_STRATEGY §7 |

## Files
- `code/tools/check_log.py`
- `code/tests/test_check_log.py`

## Description
Make the transcript gate strict and complete, then estimate the transcript score.

## Implementation notes
- `check_log` v2:
  - `--trace` accepts multiple JSONLs;
  - a SESSION START is required before each session's first turn;
  - verbatim-prompt check (normalized whitespace, `[REDACTED]` wildcard);
  - more than 5 sentences is an error for new entries, a warning for entries before a cutoff timestamp;
  - every sub-agent id and workflow run id appears in some Actions line;
  - `--baseline-ref` **fails closed** when the ref has no log.txt.
- Sub-agent group entries from now on quote the task text verbatim (or the first N lines plus a sha256) and list the agent and run ids.
- Transcript panel: 1 agent, once at release, against a §5-weighted rubric (format 4, completeness 3, metrics-backed iteration 2, hygiene 1).
- `agent-trace.zip` is **optional**: the user declined it. Build it only if the user asks.

## Acceptance criteria
- [ ] Linter: 0 errors. Panel score ≥ 9.5.

## Tests
- Negative fixtures for each new check.

## Risks
- Past entries cannot be edited (append-only). The cutoff handles legacy warnings.

## Definition of Done
See `README.md` § Definition of Done.
