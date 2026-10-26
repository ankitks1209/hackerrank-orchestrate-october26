# T25 — Custom synthetic evaluation cases C1–C7

| Field | Value |
|---|---|
| ID | T25 |
| Milestone | M5 |
| Depends on | T21 |
| Size | M |
| SPEC refs | Report requirement (≥ 3 custom cases), R8 |

## Files
- `code/evaluation/custom_cases.py`
- `code/tests/test_custom_cases.py`

## Description
Build small synthetic datasets that exercise the rules outside the sample distribution.

## Implementation notes
- Each case writes a mini `dataset/` (CSVs plus 1–3 evidence files in real formats) into a temp dir and runs the pipeline. Every invocation of `main.py` in a test passes `--out` and `--diag` under `tempfile.mkdtemp()`, so the submission `output.csv` is never overwritten.
- **C1:** historical, uppercase email with failover drift ⇒ INCOMPLETE, account finding.
- **C2:** non-English negated request ⇒ NOT_APPLICABLE. Run it twice: with a FakeLLM (deletion=false, confidence 0.95) and with `--llm off` (lexicon). Both must pass hermetically.
- **C3:** time travel. An in-window file says ABSENT; a later file and an in-file tail line say PRESENT ⇒ COMPLETE citing the in-window file.
- **C4:** exposed tombstone plus legal hold plus audit record ⇒ ordering and `""` rules.
- **C5:** active connector repopulated a search doc, with no CF row ⇒ REPORT_ACTIVE_DATA_FLOW.
- **C6:** `.jr` decoy plus a same-name different user ⇒ no extra findings.
- **C7:** same user, two requests with disjoint windows ⇒ neither case contains the other's evidence. Synthetic ids only: no eval case or user ids.
- Write a rationale for each case for the report.

## Acceptance criteria
- [ ] All 7 pass without network access.

## Tests
- `test_custom_cases.py`.

## Risks
- Synthetic files must follow real formats exactly. Copy templates from the T05–T09 fixtures.

## Definition of Done
See `README.md` § Definition of Done.
