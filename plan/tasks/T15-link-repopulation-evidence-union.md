# T15 — Linking: repopulation flows, evidence-only union, audit records

| Field | Value |
|---|---|
| ID | T15 |
| Milestone | M3 |
| Depends on | T14 |
| Size | M |
| SPEC refs | L9–L11 |

## Files
- `code/ghostaudit/linking.py`
- `code/tests/test_link_extras.py`

## Description
Add the resources that the worker-row graph misses, and exclude post-audit and ownerless ones.

## Implementation notes
- **RP rows:** when the case owns `search_N` and `t ≤ audit_at`, add `integration_service/data_flow_X` as a violating FLOW. RB rows give a RESTORE path.
- **Evidence-only union (L10):**
  - violating observations owned by the subject, from a file admissible for the case;
  - compliant observations from an in-window file, added as verification-only resources (e.g. backup_5165 BLOCKED → case_390).
- **Audit records (L11):** `audit_record_N` found by `u:user_N` in any file. Mark it `late_only` when no window file mentions it. The late-only use is gated by `flags.use_late_audit_ids`.
- Deduplicate by `(system, rid)`.
- Exclusions come from the general rules: no owner (activity_3448) and post-audit (activity_3434, activity_3387).
- **Orphan policy rows (L9b):** exclude uniform-941 s P rows whose only compatible account is a non-requesting decoy (flag `exclude_orphan_policy_rows=True`).
- **Proof-file coverage (§8.3b):** every worker-row id named in a cited in-window proof file is assigned or carries an exclusion reason. The verifier lives in T32.

## Acceptance criteria
- [ ] 29 eval cases gain a repopulation-only flow.
- [ ] The 8 zero-candidate violating rows found by the stress test are recovered by the learned upper bound plus L10 (≈ +24 steps). This is asserted by the T32 coverage report (a count), not by ids in tests.
- [ ] analytics_5959 and data_flow_3064/6090/3250 are added through L10.
- [ ] activity_3448, activity_3434 and activity_3387 add nothing.
- [ ] Audit coverage buckets are reported (analysis: 300 in-window, 134 late-only, 84 none).

## Tests
- Synthetic RP chain.
- Post-audit RP.
- Ownerless RP.
- Compliant-union case.

## Risks
- Double counting flows. Dedup handles it.

## Definition of Done
See `README.md` § Definition of Done.
