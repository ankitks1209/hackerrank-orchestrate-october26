# T32 — Label-free verification suite (P2a–d, P5)

| Field | Value |
|---|---|
| ID | T32 |
| Milestone | M7 |
| Depends on | T21 |
| Size | M |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §2 P2, P5; SPEC §8.3b |

## Files
- `code/evaluation/verify_steps.py`
- `code/evaluation/invariants.py`
- `code/tests/test_verify_steps.py`

## Description
Check every emitted eval step without labels: precision via locators, recall via sweep, proof-file coverage, component redundancy and invariants.

## Implementation notes
- **P2a locator verification:** an independent verifier that does **not** import `linking`, re-opens each step's locator and confirms the claimed state plus one of the subject's keys (or the anchored account).
- **P2b recall sweep:** for each case, every resource id next to a subject key in an admissible file must be emitted or excluded with a reason code.
- **P2c proof-file coverage:** every worker-row id named in a cited in-window proof file must be assigned or excluded.
- **P2d redundancy matrix:**
  - linker: timing vs owner;
  - state: template vs evidence;
  - intent: LLM vs lexicon vs intake;
  - citation: grep vs locator.
  Also report the single-signal fraction.
- **P5 invariants:**
  - account verify on every deletion case;
  - finding/remediation/verification pairing;
  - COMPLETE steps all cited;
  - citation window;
  - ids exist;
  - legal operation↔system pairs;
  - cohort all-or-nothing audit discovery;
  - distributions (status mirror confusion, steps per case).

## Acceptance criteria
- [ ] P2a: 0 failures. P2b and P2c: 0 unexplained. The P5 hard checks pass, and every warning is explained.
- [ ] The report is Markdown, consumed by T35 and T44.

## Tests
- Synthetic fixtures that trigger each check.

## Risks
- Verifier shares code with the solver, so errors correlate. Keep it import-isolated (test enforced).

## Definition of Done
See `README.md` § Definition of Done.
