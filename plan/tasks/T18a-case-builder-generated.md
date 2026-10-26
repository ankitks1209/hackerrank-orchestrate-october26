# T18a — CaseBuilder: generated family (verdict assembly)

| Field | Value |
|---|---|
| ID | T18a |
| Milestone | M4 |
| Depends on | T15, T17 |
| Size | M |
| SPEC refs | §8.2, §8.3 V1–V5, L11 |

## Files
- `code/ghostaudit/casebuilder.py`
- `code/tests/test_casebuilder_generated.py`

## Description
Assemble ResourceVerdicts for cases that have an A-row account (the generated family).

## Implementation notes
- For each case:
  - the account (V1);
  - the linked resources (T15);
  - the audit record (V2, subject to `use_late_audit_ids`);
  - legal holds (V3, `verify_legal_holds`);
  - tombstones (V4).
- State and cite come from T17; treatment from T16. The omission cite is resolved last via `choose_omission_cite`.
- Compliant resources: in a COMPLETE case, keep only those that have a cite. In an INCOMPLETE case, keep all with `""`.
- Each verdict carries a `reason` for diagnostics. Never invent an id.

## Acceptance criteria
- [ ] For the 24 generated-family samples, the verdict set equals the verdicts abstracted from gold by the `tests/gold.py` helper (T20), except the pinned misses case_18 and case_20.
- [ ] Every output resource_id occurs somewhere in the dataset.
- [ ] The count of omitted account steps is reported.

## Tests
- Per-rule fixtures (V1–V5).
- The gold-abstraction comparison.

## Risks
- The verification-set rules for INCOMPLETE cases are only partly covered by samples. Diagnostics list every untested-rule firing.

## Definition of Done
See `README.md` § Definition of Done.
