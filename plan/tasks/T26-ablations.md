# T26 — Strategy comparison, ablation harness and assumption ledger

| Field | Value |
|---|---|
| ID | T26 |
| Milestone | M5 |
| Depends on | T24 |
| Size | M |
| SPEC refs | S1, S3, S6, S19, R1–R4, R7, Q8 |

## Files
- `code/evaluation/ablation.py`
- `code/evaluation/main.py`

## Description
Measure the effect of every inference so that decisions are made with data.

## Implementation notes
- **Strategies** (the report must compare ≥ 2), all into temp paths (Every invocation of `main.py` in a test passes `--out` and `--diag` under `tempfile.mkdtemp()`, so the submission `output.csv` is never overwritten.):
  - S0 deterministic-only (`--llm off`);
  - S1 Opus 5.5 intent + Opus 5.5 media (default);
  - S2 Haiku 5.5 intent + Opus 5.5 media.
  Cache entries for every strategy are committed, so the table reproduces offline. Columns: sample status, step P/R/F1, field accuracy, sequence (exact and LCS), eval status distribution, rows that differ from the final strategy, calls, tokens, cost, wall time.
- **Ablations** via `--flags`:
  - signature on / off / ranges-only;
  - never_mix on/off;
  - fifo_pairing on/off;
  - handcrafted_account_convention on/off;
  - verify_legal_holds on/off;
  - use_late_audit_ids on/off;
  - window_offset_s ±600.
- For each variant report:
  - sample metrics;
  - eval unique-link counts;
  - eval status distribution;
  - number of eval rows that differ from the default.
- Generate the assumption ledger from diagnostics: each flag fired, with counts.

## Acceptance criteria
- [ ] `--ablate` prints a Markdown table of all variants with the default named.

## Tests
- Ablation smoke test on the custom cases.

## Risks
- Runtime: each variant runs in under 2 s, so the whole ablation takes under 30 s.

## Definition of Done
See `README.md` § Definition of Done.
