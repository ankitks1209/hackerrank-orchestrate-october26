# T13 — Linking: candidate generation

| Field | Value |
|---|---|
| ID | T13 |
| Milestone | M3 |
| Depends on | T04, T12 |
| Size | M |
| SPEC refs | L1–L3 |

## Files
- `code/ghostaudit/linking.py`
- `code/tests/test_link_candidates.py`

## Description
Generate candidate case↔account and case↔worker-row edges from grounded signals only.

## Implementation notes
- Inputs: all requests (eval and sample are both participant inputs), the activity rows, EvidenceIndex and IdentityIndex.
- **Account edges (L2):**
  - window `[reported_at − 1.3 h, reported_at − 0.7 h]`, found by bisect;
  - status mirror `{COMPLETE: SUCCESS, PARTIALLY_COMPLETE: PARTIAL, NOT_STARTED: FAILED}`.
- **Worker edges (L3):**
  - P rows: `[reported_at − 30 min, reported_at − 2 min]`;
  - V/CF/CR rows: `[reported_at + 30 min, reported_at + 135 min]`, and `≤ audit_at`;
  - all bounds are shifted by `window_offset_s`.
- Owner filter: if `users_by_rid[rid]` is non-empty, keep only cases whose subject is in it.
- The learned-signature check `signature.matches(row, account_row)` (T14) is applied to edges only when `flags.signature` is set.

## Acceptance criteria
- [ ] Every generated-family sample's true account is among its candidates (24/24).
- [ ] activity_1124, activity_438 and activity_147 fall inside their owning cases' windows (case_390, case_461, case_527).
- [ ] Candidate-size histograms are reported with the signature on and off.

## Tests
- Synthetic overlapping timelines.
- Mirror filter.
- Owner filter.

## Risks
- Window constants come from the samples (R7). T26 sweeps them.

## Definition of Done
See `README.md` § Definition of Done.
