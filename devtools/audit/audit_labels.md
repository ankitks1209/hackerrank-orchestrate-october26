# Audit labels

Labels written by auditors for the blind audit (T39). They are evaluation-only data: the pipeline
never reads this file (`code/tests/test_audit.py` scans the shipped source for any reference to it).
`audit_score.py` reads it. Fenced blocks such as the example below are ignored by the parser.

## Format

One block per audited case. The `###` line holds the case id, the `status:` line the status, and each
step is a line `- phase | system | resource | operation | state | evidence`, in array order. Use an
empty last field for an empty `evidence_id`. Write `EXPECTED_UNKNOWN` as the resource when the id
cannot be found in any participant file (for example an audit record that only a later file names):
the scorer counts such a step as a structural miss of the output, never as a visible error, so the
estimate is not biased upward.

```text
### case_12
status: INCOMPLETE
- FINDING | search_service | search_7 | REPORT_REMAINING_RECORD | PRESENT | evidence_01
- REMEDIATION | search_service | search_7 | DELETE_RECORD | ABSENT |
- VERIFICATION | search_service | search_7 | VERIFY_RECORD_ABSENT | ABSENT |
- VERIFICATION | security_service | EXPECTED_UNKNOWN | VERIFY_RECORD_PRESENT | PRESENT |
```

## Rules for auditors

1. Label from the raw participant files and the task statement only (see the prompts in `prompts/`).
2. Cite only evidence captured at or before the case's `audit_at`; remediation and verification steps
   to be done later carry an empty evidence id.
3. Two independent R2 auditors label each case. A third arbitrates a disagreement with line citations.
4. Calibrate first: label the public sample cases blind and score them with
   `audit_score.py --pred dataset/sample_output.csv --title Calibration`.

## Labels

No labels are stored here until the audit is run (after the code freeze for the estimation sample).
Append each case block below this line.
