# Estimation sample record (R4)

Status: not run.

The blind-audit estimation sample (at least 100 evaluation cases drawn after the code freeze and scored
once, `devtools/RELEASE_CHECKLIST.md` gate R4) was NOT drawn. The decision taken was a targeted audit
instead: 61 hand-picked evaluation cases covering the media, first-in-first-out and timing-linked families
plus a high-confidence control set (`devtools/audit/coverage_result.md`, gate R5).

A targeted sample is chosen where the solver is least certain, so it cannot give an unbiased estimate of
the error rate over the 518 evaluation rows. No estimate is claimed here. The 518 evaluation rows remain
unlabeled; their quality rests on the sample scores (in-sample), the label-free checks and the targeted
audit, not on a measured accuracy.

| Field | Value |
|---|---|
| Gate | not run |
| Cases drawn | 0 |
| Status errors | not measured |
| Visible step error upper bound | not measured |

Gate R4 therefore does not pass. Drawing the sample after a freeze, labelling it blind and scoring it with
`python3 devtools/audit/audit_score.py --labels <labels> --pred output.csv --weights <draws.json>` is still open.
