# T28 — Final live run, offline rerun, usage_report.md

| Field | Value |
|---|---|
| ID | T28 |
| Milestone | M6 |
| Depends on | T21, T19, T11b, T36, T35 |
| Size | S |
| SPEC refs | Usage report requirement, S12 |

## Files
- `code/ghostaudit/cache/*.json`
- `code/evaluation/usage_report.md`
- `output.csv`

## Description
Produce the submission `output.csv` from a full run and document its token and cost usage.

## Implementation notes
- Re-verify the model ids and prices with the `claude-api` skill. Run the live pass on Python ≥ 3.10 with `anthropic>=2.0.0`, for all strategies (S1 final, S2, and S0 needing no LLM), so the T26 table reproduces from the committed cache.
- Run `--llm live` once, which needs `ANTHROPIC_API_KEY` from the environment. Then run `--llm cache` and confirm the outputs are byte-identical.
- Render `usage_report.md` from the `UsageMeter`:
  - final strategy, plus a per-strategy cost table;
  - cache creation/read tokens, image count and image tokens, PDF pages, thinking-inclusive output, stop reasons, peak RPM/TPM, runtime per stage;
  - provider and models;
  - calls;
  - input and output tokens;
  - totals and per-request averages;
  - estimated total and per-request cost;
  - per-model and overall totals;
  - cache provenance: the final offline run replayed the cache, together with the originally billed tokens.
- No key material anywhere.

## Acceptance criteria
- [ ] Live and cached outputs are identical. The report has every required field. A secret grep is clean.

## Tests
- Validator on `output.csv`.
- Secret grep.

## Risks
- API outage. Earlier dev runs pre-fill most of the cache.

## Definition of Done
See `README.md` § Definition of Done.
