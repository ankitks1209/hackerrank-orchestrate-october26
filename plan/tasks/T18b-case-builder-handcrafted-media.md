# T18b — CaseBuilder: hand-crafted and media families

| Field | Value |
|---|---|
| ID | T18b |
| Milestone | M4 |
| Depends on | T18a, T11a |
| Size | M |
| SPEC refs | L12, Q1, Q2, Q7 |

## Files
- `code/ghostaudit/casebuilder.py`
- `code/tests/test_casebuilder_handcrafted.py`

## Description
Build verdicts for cases without an A-row account: the sample hand-crafted cases and the eval media/image cases.

## Implementation notes
- **Resources:** T rows (samples) or LINK rows (eval), plus L1 evidence (including media observations) admissible for the case.
- **Account id (L12):**
  1. an evidence-linked id;
  2. else an activity pointer (T or LINK row, or ev57 `source_resource_id`);
  3. else the `account_00N` convention, if the flag is set and the subject is user_01..user_10;
  4. else no account step.
- **Q1:** `support_9538` for case_34 is cited to ev04 only if T11a recorded the reference as still listed; otherwise it is excluded unless `allow_pre_request_findings` is set.
- **Same user, several cases (user_07, user_17, user_18):** scope strictly by each case's own window (T5).

## Acceptance criteria
- [ ] The 8 hand-crafted samples match the gold abstraction.
- [ ] The eval image-family predictions match the SPEC/ANALYSIS table (cases 33, 34, 35, 39, 45, 46, 50, 52, 53, 55, 61, 63). Any deviation is explained in diagnostics.
- [ ] Account basis counts are reported. `convention` is expected for sample case_04 and at most 3 eval cases (45, 61, 63).

## Tests
- Per-family fixtures.
- user_17 scoping (case_17 vs case_46).

## Risks
- The media cases depend on the T11b cache fill. With an empty cache, they degrade and diagnostics say so.

## Definition of Done
See `README.md` § Definition of Done.
