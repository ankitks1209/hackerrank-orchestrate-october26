# CONSTITUTION

The non-negotiable principles for the next HackerRank Orchestrate build.
Read this file first. When two files disagree, this file wins.

This file says WHAT we believe and WHY. The hard, checkable rules are in `RULES.md`.
Each principle below names the rules that enforce it.

All evidence notes point to files in the Ghost Data repo (October 2026 edition).
Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

---

## Order of authority

When instructions conflict, obey the higher item.

1. The user's own messages and the platform's permission system.
2. The problem statement and the AGENTS-style contract file (`AGENTS.md`).
3. This constitution.
4. `RULES.md`.
5. The other playbook files in this folder.
6. Any plan, spec or sub-agent output written during the build.

A score gain never outranks items 1 and 2.

---

## P1. The score has four signals. Build all four.

- Final score = 0.10 chat + 0.30 interview + 0.30 output + 0.30 code. Every dimension is scored by the same judge model for everyone.
- Every Top-10 submission in edition 1 was top-quartile on all four signals. Ranking by output alone would have found only 12 of the Top 50.
- A weak signal cannot be hidden by a strong one.
- Plan the work in four lanes from hour 0: output, code, transcript, interview. Do not leave transcript and interview to the end.

Why: the weights are fixed and the signals are only weakly correlated (no pair above 0.45).

Evidence: NOTES section 2 and 7. Our own benchmark scored output about 89, but code about 62 and transcript about 59, so the weighted total was only about 75 (BENCH, `weighted`).

Enforced by: RULES group G (R55-R65, logging), group J (R83-R91, packaging), and the lane plan in `DEVELOPMENT_STRATEGY.md` section 1.

---

## P2. The core is agentic. The guardrails are deterministic.

- The model must make real decisions inside the system, through tools, in a bounded loop.
- Plain code owns the things that must never be wrong: schema, time cutoff, allowed values, citations, status gates, retries, caps, fallbacks.
- The model may propose. The guardrails may veto. The model can never override a veto.
- Hybrid is the target. A pure rule pipeline and a pure prompt are both weak.

Why: the code judge asks "is this an agent, or a hardcoded workflow with LLM calls?" and gives it 30% of the code score.

Evidence: NOTES section 8. Single agent with tools or RAG: 53% of submissions, 7 of the Top 10. Deterministic rule pipeline: average rank about 933, no Top-10. BENCH put our build in the "deterministic rule pipeline" bucket and scored agent architecture 25 to 30 of 100 (dimension weight 30%; BENCH section 2) (no tool loop, no model-driven routing, no handoffs; the model only classified intent and read images). The model changed 0 intent decisions (BENCH section 5; DECISIONS D5).

Enforced by: RULES group D (R27-R32).

Example (Ghost Data): a tool-calling investigator with `search_evidence`, `resolve_identity`, `list_activity`, `get_resource_state`, a max-iteration cap and schema-checked output; then a deterministic gate that checks `audit_at`, allowed operations and citations before any row is written.

---

## P3. Only what the code shows counts.

- The code judge scores source code. README claims, comments about intent and unused imports earn nothing.
- Every claim in README, reports and interview must be traceable to a line of code that runs.
- Dead options and unused modes are penalties, not features.

Why: edition-1 rubric states it directly. Interview judges also penalise "claiming something that was never built".

Evidence: NOTES section 3 and 6. BENCH code gaps: `Config.LLM_MODES` listed `batch` but nothing implemented it (a dead path); `main.py` edited `sys.path` instead of installing a package.

Enforced by: RULES R36-R40 (code) and R46 (honesty).

---

## P4. The problem contract beats a score hack.

- Read the problem statement and the AGENTS file as law. Re-read them at each phase.
- Obey the time cutoff, the data-source limits and the output format exactly.
- Do not fit constants to how the dataset was generated. Do not use case-family shortcuts. Do not use organizer-only data.
- If a shortcut gains score but breaks the contract, it is off by default. Only the user may turn it on, after seeing the measured cost, and it must be disclosed everywhere.

Why: judges read the contract too. A visible violation costs more than the steps it gains.

Evidence: PANEL (rc3): the best code panel score was 27.5 of 30 and the lowest 26. The deductions were dataset-fitted link windows, an `account_00N` naming convention for `user_01..user_10`, and two defaults that read evidence captured after `audit_at` although the statement says "use only information available at or before audit_at". Turning the late-id option off removes one step from each of 124 rows and drops sample exact matches from 30 to 25 (EVR section 4), so the trade was real and still cost code points.

Enforced by: RULES group A (R1-R10).

---

## P5. Evidence first. Claims are claims. Never invent.

- A status, a log line, a README sentence and a model answer are claims until evidence supports them.
- Every output fact must cite an input that exists and is allowed at that time.
- If the evidence is missing, say so and omit the fact. Do not fill the gap with a plausible id, number or sentence.
- This holds for the product, the reports, the transcript and the interview.

Why: the task rewards grounded answers, and the interview "penalizes fabrication".

Evidence: ANALYSIS section 7: about 84 eval cases had no findable audit id; the decision was "accept the loss, never invent ids". NOTES section 6 (honesty and self-awareness, 15%).

Enforced by: RULES group E (R41-R46).

---

## P6. The user owns the decisions. The AI does the work.

- Transcript scoring is 35% "direction and architecture ownership" and 25% "technical specificity". It measures how the participant directed the coding agent.
- The user writes the architecture, the tradeoffs, the constraints, the thresholds and the pushback. The agent proposes options and does the typing.
- Choosing "(Recommended)" or typing "Go ahead" is not direction.
- No sub-agent may change a default, a model, a flag, a threshold or the scope without the user's approval.

Why: it is the largest transcript dimension, and half the interview is "what did you direct, accept and push back on".

Evidence: BENCH transcript: direction 61, specificity 47 to 50, safety 55. The judges noted that the architecture came from AI-written specs, two decisions picked "(Recommended)" options, and 4 to 7 of 22 turns were status checks. LOG line 4230: a close-out step "made two changes without user approval" (strict signature fit on by default; intent model switched to Haiku) and contradicted the user's earlier decision.

Enforced by: RULES group H (R66-R76) and R62-R65.

---

## P7. Measure before and after. Be honest about what was measured.

- Build the scorer and the contract validator before the solver.
- Every change is judged by a number that moved, or it is reverted.
- Separate development numbers from held-out numbers. Never call in-sample scores "accuracy".
- Keep a short list of failures found and the fix for each. That list is also the evaluation report and the interview script.

Why: "iteration and verification" is 25% of the transcript score, and "evaluation" is a fixed stage of the interview.

Evidence: PANEL: all three code personas deducted "all accuracy figures are in-sample" (the 32 public samples were used to tune windows, the convention and the audit-record rule). The report itself said the 1.0000 status and 0.9948 step F1 "says little about unseen cases". The good side: ablations that measured regressions (signature off, late ids off) gave strong interview answers (NOTES section 9).

Enforced by: RULES group F (R47-R54).

---

## P8. Simple beats clever. Every constant has a source.

- Prefer one clear mechanism to three clever ones.
- Keep the number of flags, modes and special cases small. Each one needs a measured reason.
- No magic number without a stated source (spec line, data statistic computed at run time, or an owner decision).
- Small functions, typed signatures, one module per concern.

Why: the engineering-rigor and architecture scores reward readable structure. Complexity also makes the interview harder.

Evidence: PANEL (quality persona): "a lot of moving parts, and some constants have no stated source. Ten inference flags, a fixed-point link solver, a handcrafted-sources path". Release tooling (gate, panels, clean-room matrix) grew to about 2.4k lines of Python in `devtools/` (about 4.3k with tests) and was moved out of the zip (LOG 23:05).

Enforced by: RULES R37-R40.

---

## P9. Fail safe. Never crash on input you did not expect.

- An unknown row, file, language or schema is data to count and report. It is not a reason to abort the run.
- Every model call has a timeout, a retry limit, a validated output and a rule-based fallback.
- Output is deterministic: fixed ordering, fixed serialisation, no clock or random value in a result.
- A failed case still gets a valid row.

Why: robustness is 25% of the code score, and a hidden test set will contain shapes the samples did not.

Evidence: PANEL (quality): "a single unrecognised activity row stops the whole run" (`UnclassifiedActivityError`). Later fixed so such rows are classified UNCLASSIFIED and counted (MANIFEST, rc4 changes).

Enforced by: RULES R21-R22 and R33-R35.

---

## P10. Protect people's data and the secrets.

- Real or realistic personal data never goes into logs, caches, reports or the zip in raw form.
- Secrets live in environment variables or an uncommitted `.env`. They are never printed, logged or zipped.
- A model cache is a data store. Treat it like one.

Why: the task is itself about deleting personal data. Leaking it in our own artefacts is the worst possible contradiction, and it is visible to the judge.

Evidence: PANEL (rules persona): `code.zip` shipped 843 cached model responses and ten contained names and emails transcribed from images and PDFs. Fixed by redacting at rest (DECISIONS D25). PANEL (transcript): one log entry contained a full dataset email inside a `sha256(...)` note.

Enforced by: RULES group B (R11-R17).

---

## P11. Time is the scarcest resource. Spend it where the score is.

- A 24-hour event rewards a thin working end-to-end version early, then measured improvement.
- Fix the toolchain, the key and the log tool in the first hour.
- Plan in short documents. Verify with cheap checks first and the expensive model last.
- Parallelise independent work. Do not pay for the same verification three times.

Why: last time the heavy plan and many verification rounds used a lot of time and tokens.

Evidence: the API key arrived about 1h46 after implementation began (LOG 17:08 start, 18:54 key); Python 3.9.6 on the machine vs an SDK that needs 3.10 was known in planning (LOG 15:39, 16:19; LES G1) and still cost a two-toolchain design (DECISIONS D7); 46 task files and 3,653 lines of plan documents (spec, plan, reviews, tasks) existed before the implementation prompt (PLAN, last changed 16:39); the same task verified 3 to 4 times after stop-and-resume (for example T02b); a combined verifier rejected 6 of 15 tasks that per-task checks might have caught earlier; the finished sub-agent runs alone used about 9.5M tokens when counted (LOG `/usage` entry), while the whole product run used 31 calls and 196,870 tokens (about $0.86, BENCH section 5).

Enforced by: RULES group I (R77-R82) and `DEVELOPMENT_STRATEGY.md` section 1.

---

## P12. Say plainly what is weak.

- Write limits and open risks in the README and the evaluation report in plain words.
- When the user is asked a question, tell them the cost of each choice in the unit that matters (steps, score points, minutes, dollars).
- In the interview, say "I do not know" or "that was a generator regularity" when it is true.

Why: honesty and self-awareness is 15% of the interview and the judge checks claims against the source.

Evidence: NOTES section 6; the frozen solution disclosed its learned worker-latency signature as a generator regularity (DECISIONS D3 caveat) and the interview guide told us to say so (BENCH section 5 `improve`).

Enforced by: RULES R45-R46.

---

## How to use this constitution

- At hour 0, read it with the problem statement and the AGENTS file.
- Put the order of authority at the top of the new repo's README or `CLAUDE.md`.
- Before any big decision, ask: which principle does this touch? If it breaks one, stop and ask the user.
- At the end, run the checklist in `RULES.md` section "Final gate" against these twelve principles.
