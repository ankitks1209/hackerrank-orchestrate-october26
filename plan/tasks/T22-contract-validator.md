# T22 — Output contract validator (`ghostaudit/contract.py`)

| Field | Value |
|---|---|
| ID | T22 |
| Milestone | M4 |
| Depends on | T20 |
| Size | S |
| SPEC refs | §8, A1, A4, N8 |

## Files
- `code/ghostaudit/contract.py`
- `code/evaluation/validator.py`
- `code/tests/test_validator.py`

## Description
Implement every contract check once, inside the package, so main.py can call it without importing `evaluation`.

## Implementation notes
- Structural checks:
  - exact header;
  - 518 unique case_ids equal to the request set, in natural order;
  - status in the allowed set;
  - valid JSON;
  - 7 keys per step;
  - `step_no` = 1..n;
  - (phase, op, state) ∈ `OPERATION_TABLE`;
  - sort key respected;
  - no duplicates.
- Status rules:
  - NOT_APPLICABLE ⇒ `[]`;
  - COMPLETE ⇒ VERIFICATION steps only, each citing a known file_id, activity_id or audit_id;
  - INCOMPLETE ⇒ ≥ 1 finding, every finding cited, all REMEDIATION and VERIFICATION steps `""`;
  - a cited file must satisfy `reported_at ≤ captured_at ≤ audit_at`.
- Warnings (not failures): a COMPLETE row with `[]`; a deletion case with no account step.
- `evaluation/validator.py` re-exports it.

## Acceptance criteria
- [ ] 0 violations on the eval output. Each rule has a negative test.

## Tests
- One negative fixture per rule.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
