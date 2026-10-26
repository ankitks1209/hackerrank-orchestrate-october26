# T04 — Activity template classifier

| Field | Value |
|---|---|
| ID | T04 |
| Milestone | M1 |
| Depends on | T02 |
| Size | M |
| SPEC refs | §4 |

## Files
- `code/ghostaudit/activity.py`
- `code/tests/test_activity.py`

## Description
Turn each `system_activity.csv` row into a typed `ClassifiedActivity`. `reported_result` is carried along but never used as state.

## Implementation notes
- Precompile one regex per template: A, P, V, CF, CR, R, RP, RB, N, L, T. Check noise first (`… processed <prefix>_N.` from a non-worker source).
- Treatment comes from `event_type`:
  - DELETE_RECORD → DELETE
  - REDACT_RECORD → REDACT
  - ANONYMIZE_RECORD → ANONYMIZE
  - CHECK_DATA_FLOW / DISABLE_DATA_FLOW → FLOW
  - CHECK_RESTORE_ACCESS / BLOCK_RESTORE → RESTORE
  - RETAIN_RECORD → RETAIN
- system_id by kind (SPEC §4):
  - A, P, V, CF, CR, T, L → `target_system`;
  - RP → `integration_service`, with `related_rid=search_N`;
  - RB → `backup_service`;
  - R, N → `account_service`.
- LINK rows: parse `resource_id`, alias (in parentheses), email and `user_N`.
- Return rows sorted by `(t, activity_id)`. activity_4000–4011 are appended out of time order.

## Acceptance criteria
- [ ] Kind counts: A=532, P=248, V=558, CF=89, CR=28, R=55, RP=31, RB=1, N=10, L=12, T=12, NOISE=2435 (total 4011).
- [ ] No unclassified row.
- [ ] All 12 LINK rows parse. Example: activity_4009 gives export_1842 / `NST-2026-0718-1842` / user_18.

## Tests
- One fixture row per template.
- A count test over the full CSV.

## Risks
- Template text drift. The counts test pins every template.

## Definition of Done
See `README.md` § Definition of Done.
