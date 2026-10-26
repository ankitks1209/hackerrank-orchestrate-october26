# T06 — JSON records parser (exports, bundles, ledgers, collections)

| Field | Value |
|---|---|
| ID | T06 |
| Milestone | M2 |
| Depends on | T02b |
| Size | M |
| SPEC refs | F4–F7 |

## Files
- `code/ghostaudit/evidence/records.py`
- `code/tests/test_records.py`

## Description
Parse the four JSON families into Observations and ScopeAssertions, each with a per-entry `entry_time`.

## Implementation notes
- Detect by top-level keys:
  - `service_exports` → exports;
  - `snapshots` → bundle;
  - `records` with `record_type` → ledger;
  - `collection` + `records` → collection.
- Exports: `entry_time = observed_at`. Use the F4 table. A 404 or null profile is ABSENT with no keys.
- Bundles: `entry_time` = the snapshot `captured_at`. An empty `records` list gives a ScopeAssertion with no ids.
- **`operational_record_history`** rows:
  - subject key from **`lookup_value`**;
  - system from the row's `system`, never `data_store`;
  - F6 states.
- Ledgers: `result` → state (F6); `record_type` is the category. Collections: map to analytics_platform or export_service.
- Port the logic of `solution/notes/records_normalize.py` without importing it. Drop name keys and rename IDENTIFIABLE to EXPOSED.

## Acceptance criteria
- [ ] All 28 JSON files parse.
- [ ] evidence_92: `account_5334` PRESENT (200, email only); `account_6440` ABSENT.
- [ ] evidence_51: empty `customer_profiles` (scope with no ids); `tombstone_9178` EXPOSED.
- [ ] evidence_22: `account_945` PRESENT with key `e:romero.valeria94@icloud.com`. All 124 history rows (ev22, ev31, ev45) carry a key.
- [ ] evidence_13: `account_1417` keeps its post-capture entry_time, so T17 can filter it.

## Tests
- One fixture per family, plus the history-row case, an empty collection, a null profile and a tail entry.

## Risks
- File names do not describe content, so detect by keys.

## Definition of Done
See `README.md` § Definition of Done.
