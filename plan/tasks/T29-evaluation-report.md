# T29 — evaluation_report.md

| Field | Value |
|---|---|
| ID | T29 |
| Milestone | M6 |
| Depends on | T23, T24, T25, T26, T35, T39, T40 |
| Size | M |
| SPEC refs | Evaluation report requirement |

## Files
- `code/evaluation/evaluation_report.md`

## Description
Write the required evaluation report with real numbers.

## Implementation notes
- All numbers come from `render_reports.py` (T35), never typed by hand. The report also includes the local-evaluation results: P2 verification counts, the P3 audit estimate with its upper bound, the P4 tiers, the P6 provenance ledger, and the ceiling and structural-loss statement.
- Sections:
  - **final strategy and why** (S0/S1/S2 comparison table from T26);
  - learned-signature disclosure: how it was fitted without gold, held-out agreement, OFF ablation, compliance caveat;
  - case-level status accuracy;
  - step-level and field-level accuracy;
  - sequence accuracy, with metric definitions;
  - custom cases C1–C7, with rationale and results;
  - ablation table;
  - assumption ledger;
  - intent agreement matrix (lexicon × LLM × N);
  - failures found and improvements made, chronologically, with before/after numbers;
  - known limitations (pinned misses, missing audit ids, the learned-signature decision and its OFF result, the account_00N convention, legal holds);
  - open questions Q1–Q8 with decisions.
- State explicitly:
  - the intent lexicon was not derived by copying eval texts;
  - the learned link signature is ON by default, was fitted without gold, is validated on held-out evidence, and its OFF ablation is shown.
- Reference prompts by path.
- Also write `code/evaluation/case_explanations.md` for about 6 cases (samples and custom cases). For each step it shows the identity chain, the evidence id with its locator, the policy rule row, the ordering reason and the citation basis.

## Acceptance criteria
- [ ] Every bullet required by problem_statement.md and AGENTS §6.8 is present. Numbers match a fresh scorer run.

## Tests
- Manual checklist review.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
