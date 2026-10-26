# T16 — PolicyEngine and system/category mapping

| Field | Value |
|---|---|
| ID | T16 |
| Milestone | M4 |
| Depends on | T02 |
| Size | S |
| SPEC refs | §6 |

## Files
- `code/ghostaudit/policy.py`
- `code/tests/test_policy.py`

## Description
Make treatment and compliance decisions data-driven from `deletion_rules.csv`.

## Implementation notes
- `PolicyEngine.from_rules(rows)` maps category → required_action.
- `SYSTEM_BY_PREFIX`:
  - account_ → account_service
  - search_ → search_service
  - analytics_ → analytics_platform
  - support_ → support_platform
  - export_ → export_service
  - data_flow_ → integration_service
  - backup_ → backup_service
  - audit_record_ → security_service
  - legal_hold_ → legal_service
  - tombstone_ → identity_service
  - object_ → object_storage
  - marketing_ → marketing_platform
- `treatment(system_id, category, event_type)`: evidence category first, then activity `event_type`, then the prefix default.
- `is_compliant(treatment, state)`:
  - DELETE requires ABSENT
  - REDACT requires REDACTED
  - ANONYMIZE requires ANONYMIZED
  - FLOW requires DISABLED
  - RESTORE requires BLOCKED
  - RETAIN requires PRESENT
- `ops(treatment)` comes from `model.TREATMENT_OPS`.

## Acceptance criteria
- [ ] All 15 rules load. Rules 04, 08 and 11 never fire on the dataset (checked via diagnostics in T21).
- [ ] Prefix-table unit tests for all 12 prefixes. The dataset-wide consistency check (activity rows and parsed evidence vs `SYSTEM_BY_PREFIX`) lives in T27, which runs after everything is built.

## Tests
- `is_compliant` truth table.
- Discriminator precedence (message vs attachment; profile vs secondary contact).

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
