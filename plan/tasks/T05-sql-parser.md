# T05 — SQL evidence parser (topology, inventory, special schemas)

| Field | Value |
|---|---|
| ID | T05 |
| Milestone | M2 |
| Depends on | T02b |
| Size | M |
| SPEC refs | F1–F3 |

## Files
- `code/ghostaudit/evidence/sql.py`
- `code/tests/test_sql.py`

## Description
Load each `.sql` into sqlite3 `:memory:` and emit Observations plus ScopeAssertions.

## Implementation notes
- Detect the family from the `sqlite_master` schema:
  - `customer_data_primary` → topology;
  - `snapshot_scope` → inventory;
  - `customer_profiles_primary` / `search_documents_primary` → special.
- Topology: take the union over every table and record the table name in `locator`. Use the SPEC F1 collection table. A row in any table means PRESENT.
- Inventory: one ScopeAssertion per `snapshot_scope` system, with `present_ids` = the rows for that system. Use the F2 typed tables.
- Special files: `source_resource_id` in `search_documents_primary` is kept as an account pointer (SPEC L12.2).
- Keys come from `keys.keys_from_record`. Every query uses `ORDER BY resource_id`. Close each connection.

## Acceptance criteria
- [ ] 24 SQL files parse: 11 topology, 11 inventory, 2 special.
- [ ] Drift: `account_994` (evidence_05) and `account_005` (evidence_54, failover table only) are PRESENT, including when only one regional replica holds the row.
- [ ] evidence_90 yields one ScopeAssertion (account_service) with no ids. evidence_63/72 have no export_service scope; evidence_78 has no backup_service scope.
- [ ] All-null analytics and tombstone rows give ANONYMIZED and REDACTED.

## Tests
- Fixture SQL strings for each family.
- Drift test.
- Scope vs no-scope test.
- A `.jr` decoy row keeps its own key.

## Risks
- Insert syntax differs across families. Rely on `executescript`.

## Definition of Done
See `README.md` § Definition of Done.
