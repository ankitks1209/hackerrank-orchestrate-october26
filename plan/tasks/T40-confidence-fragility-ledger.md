# T40 — Confidence tiers, fragility and rule provenance ledger

| Field | Value |
|---|---|
| ID | T40 |
| Milestone | M7 |
| Depends on | T26, T21 |
| Size | S |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §2 P4, P6 |

## Files
- `code/evaluation/confidence.py`
- `code/docs/DECISIONS.md (ledger section)`

## Description
Show where the remaining risk is, and route it to audit.

## Implementation notes
- Confidence tier per case:
  - **High:** unique link, owner-linked, audit present;
  - **Medium:** signature-dependent;
  - **Low:** missing audit, FIFO, image family.
  Measured reference: 267 / 134 / 117.
- Fragility: cases whose output flips under the T26 ablation variants.
- Provenance ledger: every reverse-engineered rule with its class (evidenced, weak or inferred), sample support and eval exposure, kept in DECISIONS.md.

## Acceptance criteria
- [ ] Tiers and fragile cases are exported to T39. The ledger is complete for every flag in Config.

## Tests
- Smoke test on the custom cases.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
