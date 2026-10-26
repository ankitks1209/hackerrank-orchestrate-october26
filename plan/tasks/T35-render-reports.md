# T35 — Report generation and consistency check

| Field | Value |
|---|---|
| ID | T35 |
| Milestone | M7 |
| Depends on | T23, T10 |
| Size | S |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §5 |

## Files
- `code/tools/render_reports.py`

## Description
Fill every number in README, evaluation_report.md and usage_report.md from the scorer and meter outputs, and verify they stay in sync.

## Implementation notes
- Fill marked blocks (`<!-- BEGIN:metrics -->` … `<!-- END -->`) from the scorer, verifier, audit and meter JSON written to a temp dir.
- `--check` mode:
  - diffs the blocks against freshly generated values;
  - arithmetic checks: totals sum, average = total / 518, cost = tokens × prices, README test count = actual;
  - a required-term checklist (case-level, row-level, step-level, field-level and sequence accuracy; ≥ 3 custom cases; strategies compared; failures and improvements).
- Custom cases are rendered in Markdown as input, expected and actual.

## Acceptance criteria
- [ ] `--check` exits 0 on the release candidate.

## Tests
- Drift fixture: edit a number by hand → `--check` fails.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
