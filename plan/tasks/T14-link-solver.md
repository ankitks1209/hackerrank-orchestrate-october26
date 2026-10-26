# T14 — Linking: fixed-point solver, learned signature and tie-breaks

| Field | Value |
|---|---|
| ID | T14 |
| Milestone | M3 |
| Depends on | T13 |
| Size | L |
| SPEC refs | L4–L8 |

## Files
- `code/ghostaudit/linking.py`
- `code/tests/test_link_solver.py`

## Description
Resolve the candidate graph to one account per case and one resource set per case, with a basis label for every link.

## Implementation notes
- **Fixed point (L4)**, iterating over sorted keys only:
  - (a) owner filter;
  - (b) one-to-one account↔case;
  - (c) a singleton fixes the link and is removed from other cases;
  - (d) drop ownerless decoy rows.
- **Never-mix (L5):** a case does not mix compliant and violating rows. Legal holds are excepted.
- **FIFO pairing (L6):** ascending accounts (by numeric id) are paired with ascending case ids. These links get `basis='fifo_pairing'`.
  - **Coupling (L6b):** an ambiguous worker row follows its signature-matched account's case, so it is never paired independently.
- **Typed residues (L7b):** `flags.typed_residues=False`; an ablation only.
- **Learned link signature (L7, default ON):** `fit_signature(anchored_pairs) -> Signature(ok_residues, viol_residues, ok_range, viol_range)`.
  - It is fitted at runtime from (account row, worker row) pairs whose subjects evidence ties on both sides; a residue needs support ≥ 2.
  - The upper range is capped at the learned maximum; widening past ≈ 11,180 s swaps two accounts.
  - It is applied only after L1 and the owner filters.
  - It is validated against held-out evidence owners, and the agreement is reported.
  - `--signature off` is the ablation.
- **Id arithmetic (L8):** never used. A static test greps for it.
- Output: `dict[case_id, CaseLinks]`. `account_basis` ∈ {unique, fifo_pairing, activity_pointer, convention, none}.

## Acceptance criteria
- [ ] Signature ON (default): sample accounts 24/24 and worker rows 50/50 with 0 false positives. Unique eval account links ≈ 470. The fitted residues equal {9,10,11,39,40,41} / {20,21,22,50,51,52}. Agreement with held-out evidence owners ≥ 279/280 non-decoy rows.
- [ ] Signature OFF (ablation): the numbers are recorded, with ≈ 14/24 sample exact and 95 eval cases differing.
- [ ] FIFO rule: when a step's existence is certain, its most likely id is always emitted.
- [ ] KPI: unresolved ambiguous worker rows in eval ≤ 20, logged.
- [ ] Output is identical under two hash seeds.

## Tests
- Scenarios (synthetic):
  - unique;
  - evidence swap;
  - FIFO;
  - never-mix with a legal hold;
  - decoy row;
  - signature fit from anchored pairs (residues and range recovered);
  - range cap prevents a swap;
  - flag on/off.

## Risks
- This is the largest risk (R1). Keep it isolated and let the ablation data drive changes.

## Definition of Done
See `README.md` § Definition of Done.
