# T30b — Shipped design docs: SPEC, ARCHITECTURE, DECISIONS

| Field | Value |
|---|---|
| ID | T30b |
| Milestone | M6 |
| Depends on | T21 |
| Size | S |
| SPEC refs | SCORING_STRATEGY C4, §4 |

## Files
- `code/docs/SPEC.md`
- `code/docs/ARCHITECTURE.md`
- `code/docs/DECISIONS.md`

## Description
Give the code judge (which sees only the zip) the design rationale that docstrings refer to.

## Implementation notes
- `SPEC.md`: condensed normative rules (I1–I4, F1–F10, T1–T6, L1–L12, V1–V5, §8.4 ordering, §9 intent) with the same ids that docstrings cite. **Scrubbed of eval case and user ids.**
- `ARCHITECTURE.md`: a Mermaid pipeline diagram, module layering (dependency direction), data flow, where the LLM sits (off the deterministic critical path), performance budget, and the determinism guarantees.
- `DECISIONS.md`, ADR-lite (context / decision / alternatives / evidence), about 12 entries:
  - deterministic core plus a narrow LLM role;
  - LLM for intent and media only;
  - learned link signature (with the compliance caveat and the OFF numbers);
  - per-item cache, committed;
  - default models plus the S2 comparison;
  - sampling params removed;
  - Python 3.9 core vs 3.10 live;
  - legal-hold verify;
  - late audit ids;
  - FIFO ties;
  - the `account_00N` convention;
  - Q1 exclusion;
  - `--llm batch` considered.

## Acceptance criteria
- [ ] Every SPEC id cited in a docstring exists in `code/docs/SPEC.md` (checked by a T27-style grep).
- [ ] The docs contain no eval case or user ids.

## Tests
- A grep test for cited ids and banned literals.

## Risks
- Docs drifting from code. Write them last (after T21), and have T27 check the cited ids.

## Definition of Done
See `README.md` § Definition of Done.
