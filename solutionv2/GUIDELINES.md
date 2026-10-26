# GUIDELINES.md: the one-page quickstart

Do these in order. Each line links to the rule (R) or principle (P) that holds the detail and the evidence. The full timeline is `DEVELOPMENT_STRATEGY.md` section 1. Hours are from the event start (H0).

## Before the event

- [ ] Copy this folder into the new repo as `playbook/`, with `solution/past_evaluation_notes.md` and `evidence/`.
- [ ] Find and read every published rubric for the event (LESSONS G12). Update the weights in P1 if they changed.

## H0 to H1: remove every blocker (R77)

- [ ] Read the problem statement and `AGENTS.md` in full. Write the one-page `CONTRACT.md` (R1). Copy exact strings verbatim (R8).
- [ ] Session-start log entry, greeting, and the append-and-lint log script working (R55, R56).
- [ ] API key in `.env`, `.gitignore` and `.env.example` created, one free call and one tiny live call made (R11, R12).
- [ ] Python version vs SDK minimum checked, one toolchain chosen and pinned (R26).
- [ ] Current model ids, prices and rejected parameters checked in the docs, not from memory (R18, R19).
- [ ] Write `AGENT_POLICY.md`: models per role, verify mode, rework rule, token budget, banned models (R68, R73, R74).

## H1 to H3: know exactly what is graded

- [ ] Profile the data by script into `DATA_FACTS.md`; list traps in `LOOPHOLES.md` (`DEVELOPMENT_STRATEGY.md` phase 1).
- [ ] Build the contract validator and the scorer before the solver (R47).
- [ ] Decide the small-sample policy and compute the structural ceiling (R48; `EVALUATION_STRATEGY.md` sections 3.3 and 3.4).
- [ ] Resolve unclear contract lines in this order: text, samples, ask the user (R7, R9).

## H3 to H4: the user decides the architecture

- [ ] The user writes, in their own words: what the model decides, what code decides and can veto, the tools, the caps, the fallbacks (R63; `PROMPTING_STRATEGY.md` T2).
- [ ] First `DECISIONS.md` entries with "Decided by: USER"; the decision ledger runs from here (R45).
- [ ] Task checklist of at most 15 tasks, each with an owner and an acceptance command (R79).

## H4 to H7: thin slice

- [ ] A valid `output.csv` for every input row from a simple baseline (R33, R78). Validator clean, sample score printed.
- [ ] M1: one official-dimension code judge and one transcript judge (`EVALUATION_STRATEGY.md` section 6).

## H7 to H11: the agent layer (before accuracy work)

- [ ] A bounded tool loop with typed tools, schema-checked output, a gate the model cannot override, and a fallback (R27, R28).
- [ ] Caps from the one cap table (`GUARDRAILS_AND_EDGE_CASES.md` section 1.1); abstain and fallback rates capped (section 1.3).
- [ ] Versioned prompts with role, rules, schema, abstain conditions and an injection stance; tool descriptions with when and when not (R30, R31).
- [ ] An ablation that shows what the model changes (R29). M2 judges (`EVALUATION_STRATEGY.md` section 6).

## H11 to H17: measured accuracy loop

- [ ] One failure group at a time, general fixes only, before/after numbers, revert on regression (R53, R54; `DEVELOPMENT_STRATEGY.md` phase 5).
- [ ] No fitted constants, no case-family rules, no cutoff breaks (R2, R4, R5). Every constant has a source (R39).
- [ ] The user pastes failing rows and metrics, raises edge cases and pushes back in their own prompts (R62, R64, R65).
- [ ] Custom cases up to the R49 target, including injection, unknown row and missing evidence (R49, R50).

## H17 to H21: reports, review, freeze

- [ ] Reports generated from the run with `--check`; usage report from the meter (R25, R44).
- [ ] M3 panel, calibrated; the user chooses which deductions to fix (`EVALUATION_STRATEGY.md` section 6).
- [ ] Freeze features about four hours before the end (R80). Draft the interview prep guide at the freeze (R82).

## H21 to H24: submit and prepare

- [ ] The three release checks (R81) and the final gate (`RULES.md` section K). Hashes recorded and verified (R89).
- [ ] Code walk-through, one case traced by hand, one timed spoken rehearsal (R82; `RUBRIC_PLAYBOOK.md` section 4.3).

## All the time

- [ ] Sub-agents propose; only the user changes defaults, models, thresholds or scope (P6, R66, R67).
- [ ] No secrets or personal data in logs, caches, reports, test fixtures or the zip (R13 to R15).
- [ ] Never crash on unknown input; count it (R34). Never invent an id (R42).
- [ ] Log every turn through the script; never edit the log afterwards (R57, R58).
