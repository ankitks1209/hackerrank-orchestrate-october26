# T17 — StateResolver, citation and omission citation

| Field | Value |
|---|---|
| ID | T17 |
| Milestone | M4 |
| Depends on | T12, T16 |
| Size | M |
| SPEC refs | T1–T4, V5, §4 precedence, §8.2 |

## Files
- `code/ghostaudit/state.py`
- `code/tests/test_state.py`

## Description
Compute each resource's state at `audit_at`, choose its citation, and provide the case-level omission-citation function.

## Implementation notes
- `StateResolver.resolve(rid, system_id, req) -> Resolved(state, cite, basis)`, per resource.
  - **State (T1/T2):** the latest observation with `captured_at ≤ audit_at` and `entry_time ≤ audit_at`. A scope assertion in an admissible file gives ABSENT when the rid is missing.
  - **Cite (T3):** a window file from `mentions[rid]` or an absence-proving scope file, choosing the latest `(captured_at, order)`.
  - Return `basis='unobserved'` when the rid is not mentioned anywhere admissible.
- `choose_omission_cite(account_rid, case_cites, req, index) -> Optional[str]` (pure V5), tried in this order:
  1. a case cite whose file has an account_service scope;
  2. the latest window file with that scope;
  3. `None`.
  It is called by T18a after the other verdicts are resolved.
- **Fallback (§4):** if no admissible observation exists, the state comes from the activity template with `basis='activity'`. The cite is the in-window V/CF/CR `activity_id`, or the resource is dropped (§8.2). Every evidence/template disagreement is logged.

## Acceptance criteria
- [ ] Every eval finding has a non-empty cite (analysis: all 674 violating resources are citable).
- [ ] No cite falls outside its case window. Post-audit entries (ev13 account_1417, ev36 account_5043) are ignored.
- [ ] Sample case_26 resolves to ABSENT from evidence_92 (404). evidence_02 is captured after audit_at; its stale 09-09 ACTIVE layer must be ignored.
- [ ] Evidence/template disagreements ≤ 1 (the legal-hold artifact).

## Tests
- Time-travel fixtures.
- Scope-absence and unobserved fixtures.
- `choose_omission_cite` order.

## Risks
- The omission choice moves evidence_id on about 57 COMPLETE cases (R9). Count it in diagnostics.

## Definition of Done
See `README.md` § Definition of Done.
