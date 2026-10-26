# T42 — Override-ban enforcement: relabeling, late-evidence, narrow-rule checks

| Field | Value |
|---|---|
| ID | T42 |
| Milestone | M7 |
| Depends on | T21, T27 |
| Size | M |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §6, R10 |

## Files
- `code/tests/test_relabel.py`
- `code/tests/test_late_evidence.py`
- `code/tests/test_static.py`

## Description
Prove that no output depends on hard-coded ids, eval-specific constants or late evidence.

## Implementation notes
- **Extended static scan:** no dataset id pattern (account_/search_/support_/analytics_/export_/data_flow_/backup_/tombstone_/audit_record_/legal_hold_/activity_/evidence_ followed by digits), no dataset email and no ISO timestamp in `ghostaudit/**`. Tests may use sample-only ids.
- **Relabeling test:** relabel all ids monotonically, keep emails and sha256 consistent, shift all times by a constant, keep media facts fixed. The output must equal the relabeled baseline. A non-monotone relabel changes **only** the FIFO-flagged cases. The `account_00N` convention is exempt and disclosed.
- **Late-evidence injection:** add contradicting files captured after audit_at; the output is unchanged.
- **Narrow-rule review:** any change touching ≤ 2 eval rows and 0 sample rows needs a DECISIONS.md entry. Eval-tuned constants (e.g. the 11,100 s cap) are disclosed with their derivation.

## Acceptance criteria
- [ ] All three tests pass. The review list is empty or justified.

## Tests
- This task is the tests.

## Risks
- The relabel harness must also rewrite file names and manifest ids consistently. Build it on the T25 mini-dataset writer.

## Definition of Done
See `README.md` § Definition of Done.
