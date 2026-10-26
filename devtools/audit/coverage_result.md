# Coverage audit record (R5)

Targeted coverage audit of the evaluation output, run before the close-out fixes of this record's date.
This is a record of the audit as it was relayed to the close-out engineer; where the relay was cut off,
the text says so instead of filling the gap.

Unresolved defects: 0

## What was audited

| Item | Value |
|---|---|
| Evaluation cases audited | 61 |
| Of which media (image or PDF) cases | 13 |
| Of which first-in-first-out cases | 26 |
| Of which timing-linked cases | 12 |
| Of which high-confidence controls | 10 |
| R2 calibration cases (public samples, labelled blind) | 6 planned; labels for 3 reached this record |
| R3 adversarial disputes raised | 14 |
| Defects confirmed by the arbiter | 12 |
| Defects fixed by a general rule and verified | 12 |

Method: independent auditors labelled each case from the raw participant files and the task statement
only (`devtools/audit/prompts/`), an adversarial pass disputed the labels against the output, and an
arbiter confirmed or rejected each dispute with line citations. A confirmed defect was fixed by a rule
that is stated for the whole data family, never for one case, then re-verified.

## Defects and their general rules

The relayed list of confirmed defects names these fixes (each applied once, `n = 1`):

- Topology snapshot as a cite-only account proof (case_59, case_60; DECISIONS D22). A primary-plus-replica
  snapshot that lists at least one `account_service` row enumerates the account table. It may be cited
  for an account's absence when the case already cites that file, and it is kept out of the window
  fallback and out of state resolution, so the public samples keep their citations.
- Compliant worker rows that follow their account row are not dropped for a short latency (case_225,
  case_239, case_345; DECISIONS D23). The learned lower offset bound is a sampling artifact for these rows;
  the residue test and the learned upper bound stay.

The relayed list is cut off after case_345. The remaining confirmed defects are covered by the same two
rules according to the verification summary below; their individual entries did not reach this record.

## Verification of the fixes

The independent re-check relayed to the close-out engineer reported: a fresh run is byte-identical to the
root `output.csv` (sha256 `d533d1f1253b912fe7da8f4c61a054a3253ceaced665c00f81ec16ffc865086d`); 49 rows
changed against the baseline and no status changed (all COMPLETE to COMPLETE). Root cause A (topology
snapshot as a cite-only account proof) explains 33 rows (21 re-cite the account step, 12 gain an account
step); root cause B (relaxed floor for compliant rows) explains 21 rows, each gaining one
`VERIFY_RECORD_ANONYMIZED` step; 5 rows carry both, so 33 + 21 - 5 = 49 and nothing is unexplained. Every
confirmed defect was reported fixed as specified.

Caveat recorded by the close-out engineer: after that verification, the close-out changed the signature
fit to be strictly causal per case (DECISIONS D24). That moves 20 evaluation rows (18 COMPLETE, 0 statuses)
that were not re-audited. The rows named above (case_59, 60, 225, 239, 345) are not among them. A
fresh audit of those 20 rows is open work; this record's `Unresolved defects` counts only defects found by
the audit that was run.

## R2 calibration on public samples

Three of the six calibration label sets reached this record (case_09, case_11, case_26); the labels are
below. Scoring: `python3 devtools/audit/audit_score.py --labels <labels> --pred dataset/sample_output.csv`.

| Set | Audited cases | Status errors | Visible step errors / steps | Structural misses (EXPECTED_UNKNOWN) |
|---|---|---|---|---|
| All three | 3 | 0 | 1 / 24 | 1 |
| Without case_09 | 2 | 0 | 1 / 20 | 0 |

The one visible error is a missed step in case_26 (an analytics record the labeller did not list). The
structural miss is the audit-record id of case_09, which no participant file captured by `audit_at`
contains. The calibration gate row prints FAIL because 20 to 24 steps cannot support the 1.3 % bound
(upper bounds 0.18 and 0.22); calibration here shows that statuses agree and step labels agree except for
the cases named, not that the bound is met.

Contamination notice from the auditor of case_09: a search over `dataset/` for two ids accidentally
printed one truncated line of the public gold row for case_09, showing its first step (a
`REPORT_RESTORE_RISK` finding on `backup_4978` citing `evidence_93`). The auditor had already reached that
finding from `evidence_93` line 24 before the search, saw no other gold step and no gold for case_11 or
case_26, and excluded `sample_output.csv` from every later search. The auditor read nothing under
`code/`, `plan/` or `solution/`. The "without case_09" row above is the fully blind figure.

### Calibration labels as relayed

```text
### case_09
status: INCOMPLETE
- FINDING | backup_service | backup_4978 | REPORT_RESTORE_RISK | ACTIVE | evidence_93
- REMEDIATION | backup_service | backup_4978 | BLOCK_RESTORE | BLOCKED |
- VERIFICATION | account_service | account_3960 | VERIFY_RECORD_ABSENT | ABSENT |
- VERIFICATION | security_service | EXPECTED_UNKNOWN | VERIFY_RECORD_PRESENT | PRESENT |
- VERIFICATION | backup_service | backup_4978 | VERIFY_RESTORE_BLOCKED | BLOCKED |

### case_11
status: INCOMPLETE
- FINDING | search_service | search_052 | REPORT_REMAINING_RECORD | PRESENT | evidence_03
- FINDING | analytics_platform | analytics_2034 | REPORT_EXPOSED_PII | PRESENT | evidence_03
- FINDING | support_platform | support_864 | REPORT_EXPOSED_PII | PRESENT | evidence_03
- FINDING | integration_service | data_flow_9522 | REPORT_ACTIVE_DATA_FLOW | ACTIVE | evidence_03
- REMEDIATION | integration_service | data_flow_9522 | DISABLE_DATA_FLOW | DISABLED |
- REMEDIATION | search_service | search_052 | DELETE_RECORD | ABSENT |
- REMEDIATION | support_platform | support_864 | REDACT_RECORD | REDACTED |
- REMEDIATION | analytics_platform | analytics_2034 | ANONYMIZE_RECORD | ANONYMIZED |
- VERIFICATION | account_service | account_4248 | VERIFY_RECORD_ABSENT | ABSENT |
- VERIFICATION | search_service | search_052 | VERIFY_RECORD_ABSENT | ABSENT |
- VERIFICATION | security_service | audit_record_9394 | VERIFY_RECORD_PRESENT | PRESENT |
- VERIFICATION | support_platform | support_864 | VERIFY_RECORD_REDACTED | REDACTED |
- VERIFICATION | analytics_platform | analytics_2034 | VERIFY_RECORD_ANONYMIZED | ANONYMIZED |
- VERIFICATION | integration_service | data_flow_9522 | VERIFY_DATA_FLOW_DISABLED | DISABLED |

### case_26
status: COMPLETE
- VERIFICATION | account_service | account_5684 | VERIFY_RECORD_ABSENT | ABSENT | evidence_92
- VERIFICATION | security_service | audit_record_5416 | VERIFY_RECORD_PRESENT | PRESENT | evidence_92
- VERIFICATION | support_platform | support_4715 | VERIFY_RECORD_REDACTED | REDACTED | evidence_92
- VERIFICATION | integration_service | data_flow_6244 | VERIFY_DATA_FLOW_DISABLED | DISABLED | evidence_92
- VERIFICATION | backup_service | backup_3120 | VERIFY_RESTORE_BLOCKED | BLOCKED | evidence_92
```

The relayed text for case_26 was cut off after the list of steps (its justification, which names
`evidence_92` and `evidence_02`, is incomplete) and the three other calibration label sets did not
arrive.
