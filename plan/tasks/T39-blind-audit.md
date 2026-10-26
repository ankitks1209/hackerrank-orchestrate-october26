# T39 — Blind audit: coverage set, estimation sample, auditor protocol

| Field | Value |
|---|---|
| ID | T39 |
| Milestone | M7 |
| Depends on | T23, T32 |
| Size | L |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §2 P3, R4, R5 |

## Files
- `code/evaluation/audit/sampler.py`
- `code/evaluation/audit/audit_score.py`
- `code/evaluation/audit/prompts/r1_conformance.md`
- `code/evaluation/audit/prompts/r2_spec_free.md`
- `code/evaluation/audit/prompts/r3_adversarial.md`
- `code/evaluation/audit/audit_labels.md`

## Description
Produce the best available estimate of eval accuracy without using labels as inputs.

## Implementation notes
- `sampler.py`:
  - (a) a greedy **coverage set** over (file family × system × operation × status) cells, plus P2 exceptions, low-confidence cases and all 13 image-family/case_546 cases;
  - (b) a post-freeze **estimation sample** of ≥ 100 (preferably 150) cases with a fixed seed, stratified by confidence tier with inverse-probability weights.
- Auditor setups:
  - **R1** spec-conformance: sees SPEC; finds bugs;
  - **R2** spec-free: sees problem_statement, AGENTS §6, rules, raw data and 16 sample golds; never SPEC or solver output; its labels are the estimate;
  - **R3** adversarial: finds bugs only.
  Two R2 auditors per case, with a third arbitrating with line citations.
- **Calibrate R2** on the other 16 gold samples (swap folds; 193 steps) before trusting it.
- Label format: Markdown with an `EXPECTED_UNKNOWN` placeholder for structurally unknowable ids. `audit_score.py` counts these as FN and reports the Clopper–Pearson one-sided 95 % upper bound on visible step error.
- Labels are **never** read by the pipeline (static test). Fixes found by the audit must be general rules.

## Acceptance criteria
- [ ] The coverage set is fully adjudicated and every bug found has a general fix.
- [ ] Estimation sample: visible step-error upper bound ≤ 1.3 % and 0 status errors.
- [ ] The R2 calibration error rate is reported.

## Tests
- `audit_score` unit tests (bounds, `EXPECTED_UNKNOWN` handling).

## Risks
- Auditor assumption leakage. Spec-free R2 plus calibration mitigate it, and any residual is reported.

## Definition of Done
See `README.md` § Definition of Done.
