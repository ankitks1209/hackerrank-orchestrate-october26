# EVALUATION_STRATEGY.md: lean local evaluation for the next hackathon

Goal: know early, cheaply and honestly how the submission will score, and spend the least time doing it.

What this file covers: how to test the output, the code, the transcript and the interview prep; what to cut; and how much time each activity gets.

What it does not cover: architecture (`ARCHITECTURE.md`), principles (`CONSTITUTION.md`), requirements (`REQUIREMENTS.md`), what the judges reward (`RUBRIC_PLAYBOOK.md`), what went wrong (`LESSONS_LEARNED.md`).

Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

Time budgets in this file are recommendations (our inference). Only the counts and scores are measured, and each has a source.

---

## 1. Principles

1. MUST evaluate what the graders evaluate. The Output has a hidden golden set with partial credit and a safety score. The code has four official dimensions. The transcript has four. The interview has four. (NOTES sections 3 to 6)
2. MUST separate "does the output follow the contract" (cheap, exact) from "is the output right" (needs labels or audits) and from "will the judges like the code" (needs a judge panel).
3. MUST report in-sample numbers as in-sample. In Ghost Data the 32 public samples were also the tuning set. All three panel personas flagged this. (PANEL; EVR section 1)
4. MUST NOT read hidden or organizer files for predictions. Evaluation code may read the public sample answers; the solver must never read them. In Ghost Data only the tests and the `evaluation/` package read the sample answers (`code/docs/ARCHITECTURE.md` section 2, rule N3); a static check should enforce this (`AGENTS.md` 6.1).
5. SHOULD make every report number machine-filled from a run, with a `--check` that fails on drift. Hand-typed numbers drifted in our reports and the panel found it. (`code/tools/render_reports.py`)
6. SHOULD keep the evaluation code small. We wrote about 8k lines of non-solver tooling for about 8k lines of solver. That was too much. See section 8.

---

## 2. The lean loop (what to build, in order)

| # | Activity | What it gives | Cost | When | Keep or cut |
|---|---|---|---|---|---|
| E0 | Contract validator | Exact format and rule check on every row | 20 to 30 min | Hour 1 | KEEP |
| E1 | Sample scorer with grader emulations | Status, step, field, sequence scores and a diff by case | 45 to 60 min | Hour 2 | KEEP |
| E2 | Label-free invariants | Finds wrong output without labels | 45 to 60 min | When first full output exists | KEEP (small) |
| E3 | Custom cases (count: R49) | Covers families the samples miss; required by the task | 20 min each | Written before the code that they test | KEEP |
| E4 | Ablations (at least 2 strategies) | Shows the value of each model call and heuristic | 30 to 45 min | After the full pipeline works | KEEP (small) |
| E5 | Targeted audit with arbiters | Finds real defects by blind labelling | 1.5 to 2 h plus agent time | Once, after features are done | KEEP, once |
| E6 | Judge panels with the official dimensions | Predicts the code and chat scores | 30 min per run | Single judges at M1 and M2, full panel at M3 (section 6) | KEEP, early |
| E7 | Package check and clean-room run | Proves the zip runs from the README | 30 to 45 min | Before submit | KEEP (the three checks of R81) |
| E8 | Interview rehearsal | Prepares the 30 percent signal | 2 h | Last 2 hours (R82) | KEEP |
| X1 | Release gate R1 to R12 with waivers | Gate on gates | many hours | - | CUT |
| X2 | Estimation sample with statistical bound | Unbiased error rate | many agent hours | - | CUT |
| X3 | Clean-room matrix over many cells | Reproduction in many modes | 1 to 2 h | - | CUT (one cell is enough) |
| X4 | Confidence-tier ledger and fragility tables | Ranking of risky cases | 1 h | - | CUT (use ablations) |

Evidence for the cut rows:
- R4 (estimation sample) was never drawn and R9 (panel thresholds) was not met. Both were waived in the final freeze. (MANIFEST)
- A 20-case audit cannot certify anything: with 0 errors, the 95 percent upper bound on the step-error rate is 2.3 percent (about 129 steps in 20 cases). About 100 cases (about 644 steps) are needed for 0.46 percent. These are step-error rates, not case rates. (LES section 3)
- Our own gate design needed 12 gates, a manifest with hashes, a waiver mechanism and a `--verify-upload` mode. That tooling is in `devtools/` and it holds about 4.3k lines including tests (`wc -l`).

---

## 3. E0 and E1: validator and sample scorer

### 3.1 E0 Contract validator

MUST check, for every output row:
- exact header and column order;
- one row per input id, no duplicates, no missing ids;
- valid enum values for status, phase, operation and state;
- valid JSON in every structured cell;
- step numbering starts at 1 and is consecutive;
- phase order is respected;
- the allowed (operation, state, phase) table is respected;
- rules tied to status (for example: a COMPLETE row has only verification steps; a not-applicable row is empty);
- every cited id exists in the manifest and is not later than the cutoff.

Example (Ghost Data): `code/ghostaudit/contract.py` checked all of these. Result: 0 violations on 518 rows. (BENCH)

The validator runs inside the pipeline before the file is written, and again in tests.

### 3.2 E1 Sample scorer with grader emulations

The hidden grader is unknown. Emulate several plausible graders and require no regression on any.

| Grader | What it compares |
|---|---|
| G1 | Status per case |
| G2 | Whole-row exact match |
| G3 | Step F1 (multiset of steps) |
| G4 | Step F1 ignoring the evidence id |
| G5 | Field-level accuracy after aligning steps by key |
| G6 | Sequence accuracy (longest common subsequence ratio) |
| G7 | Weighted composite |
| G8 | Positional accuracy aligned by step number |

Source: EVR section 1. Final sample result: status 1.0000, row-exact 0.9375 (30 of 32), step F1 0.9948, sequence 0.9896.

MUST also print an error taxonomy (missing step, extra step, wrong operation or state, wrong evidence id, wrong order, wrong status) and a per-case diff. A diff you can read is the main debugging tool.

SHOULD use a Pareto rule: keep a change only if its target metric improves and no grader regresses beyond a stated tolerance. (LES principle 4)

MUST NOT call the sample score "accuracy" when the samples were used to fit rules. Say "development-set score".

### 3.3 Small labelled sets: when a hold-out is meaningful

A hold-out set only tells you something if the rules can still be fitted without it. Decide this before tuning (R48).

| Labelled rows | Policy |
|---|---|
| Enough that 20 to 25 percent can be set aside and every rule family still has fit examples (roughly 100 or more rows with each family present at least a few times; our inference) | Freeze a hold-out by a fixed rule (for example every 4th id) before tuning. Look at it only at phase ends. Report it separately. |
| Small or uneven (Ghost Data: 32 samples; no NOT_APPLICABLE, legal-hold or object-storage sample) | Do not hold out. Fit on all samples and call the numbers "development-set". Measure generalisation with custom cases written before the code (section 5), label-free invariants on the unlabeled rows (section 4) and one blind audit by independent labellers (section 7). |

Evidence: EVR section 1: "No held-out split exists, because 32 cases leave nothing to hold out once the rules are fitted". All three PANEL personas still deducted "in-sample only", so say plainly which policy you used and why.

A leave-one-group-out run (fit without one family, test on it) is a cheap middle path when families have several samples each. Report it as a robustness check, not as accuracy.

### 3.4 Structural ceiling

Compute early (hour 1 to 2) the share of rows that cannot be right from the participant data, for example ids that appear in no allowed file. Report it, and stop spending effort on it. Ghost Data: about 81 to 83 cases miss an audit id that no admissible file contains; under a case-exact grader the maximum total was 94.5 (LES section 0; BENCH section 3).

---

## 4. E2: label-free invariants

Cheap checks that need no gold answers. Run them on all rows.

Core invariants (generic):
- time: no citation is later than the case cutoff, and none is earlier than the request;
- ids exist: every resource id in the output appears in a participant file;
- status shape: a COMPLETE row has no remediation; an INCOMPLETE row has at least one finding, and every finding has one remediation and one verification;
- empty-cite rule: future steps carry an empty evidence id;
- legal pairs: no step uses an operation that policy forbids on that system;
- cohort parity: if an id family is found for all rows of a cohort or none, a partial cohort means a parser gap.

Optional (use only when citations are graded and time allows): an independent locator verifier. It re-opens each cited file with its own parser and checks that the file shows the claimed state next to a key of the subject. In Ghost Data this was `verify_steps.py` and `verify_report.py`; they re-read the files without importing the solver and found 0 hard failures on the final run. (EVR section 5)

Cost note: the independent verifier plus the redundancy matrix was a large piece of work. For a new problem, start with invariants only, and add the locator verifier if the first audit shows citation errors.

---

## 5. E3: custom cases

The task requires at least three extra cases written by the participant. (`AGENTS.md` 6.8)

How to write them (as we did):
- Write each case from the spec before the code that handles it.
- Build a mini dataset in the real file formats. Use synthetic ids that do not appear in the real data.
- Pair every case with an expected output and an explanation of the rule it tests.
- Run them in the test suite and render them into the evaluation report with input, expected and actual output.

Choose cases by failure class. These are the classes we used; a new problem will have its own:

| Class | Example (Ghost Data) |
|---|---|
| Identity variant | Historical email written in capitals, with replica drift (C1) |
| Non-actionable or negated request in another language | Portuguese "do not delete, send me a copy" (C2); both lexicon and model paths |
| Time trap | A file or a log line stamped after the cutoff says the opposite (C3) |
| Policy edge | Tombstone with legal hold and audit record; REDACT not DELETE (C4) |
| Active process | Connector repopulates a search document; disable before delete (C5) |
| Decoy | Look-alike emails and same-name users add nothing (C6) |
| Overlap | One user, two requests with disjoint windows (C7) |

Add at least these three that we did not have:
- an injection case (instruction text inside the request and inside an evidence file);
- an input row of an unknown shape (must degrade, not crash);
- a missing-evidence case (must abstain or omit, not invent an id).

Evidence: EVR section 6 lists C1 to C7. All seven passed. (BENCH: "all 7 custom cases pass")

Budget: the R49 target (8 cases) at 20 minutes each is under 3 hours with the runner. Reuse the runner for the unit tests.

---

## 6. E6: judge panels with the official rubric (the one policy)

This is the only judge-panel policy in the playbook. `DEVELOPMENT_STRATEGY.md`, `SUBAGENT_DELEGATION.md`, `TOKEN_COST_EFFICIENCY.md` and `PROMPTING_STRATEGY.md` link here.

| Milestone | When | Judges | Purpose |
|---|---|---|---|
| M1 | First valid end-to-end output (end of phase 3, about H7) | 1 code judge (A.1) + 1 transcript judge (A.3) | Catch architecture and transcript gaps while they are cheap to fix |
| M2 | Agent layer done (end of phase 4, about H11) | The same two single judges | Confirm the loop is visible in source and the user's direction shows in the log |
| M3 | Feature complete (phase 7, H19-21) | 3 code judges (take the median) + 1 transcript judge + 1 output judge (A.2), calibrated once with seeded defects (A.5) | The final ranked fix list; the user chooses what to fix |

Why this shape: our own panel ran at the end with our own personas and scored the code 26 to 27.5 of 30 and the transcript 9 of 10 (PANEL). The official-dimension benchmark, run after freeze, scored the code about 62 of 100 and the transcript about 59 of 100 (BENCH sections 2 and 4). By then the largest fix (a tool-calling agent) was too big to add (`RUBRIC_PLAYBOOK.md` section 0.2). Our three code judges scored 61.2, 64 and 62 and named the same top gaps, so one judge is enough until M3 (BENCH section 2).

MUST:
- write judge prompts with the four official dimensions and weights verbatim (Appendix A);
- ask each judge for scores per dimension, gaps with file and line, and a ranked fix list;
- calibrate once, before M3, with seeded defects. We seeded two (a wrong README command, missing token totals) and the panel caught both, so it was trusted (PANEL "Panel calibration");
- tell judges to count only what is observable in source, as the real rubric does;
- run judges on a read-only snapshot (an unzipped copy of the zip); no writes, no `.env`, no network.

SHOULD:
- run the log linter before the transcript judge;
- give the fix list to the human, not to an agent that can change defaults (`LESSONS_LEARNED.md` P8);
- not set a score bar you will later waive (MANIFEST R9).

Cost: about 100k tokens per judge (BENCH: 82k to 178k each; 778,155 for 7 judges).

---

## 7. E4 and E5: ablations and the targeted audit

### 7.1 E4 Ablations that compare at least two strategies

The June edition asked for a comparison of at least two strategies and a stated final strategy (SCORING header). The strategy table (S0 no model, S1 strong model, S2 cheap model, plus agent loop on/off) and the rule for choosing a model are owned by `TOKEN_COST_EFFICIENCY.md` section 5. Put that table in the evaluation report.

Then flip each remaining heuristic once and report rows changed (signature off: 85 rows; late audit ids off: 124; FIFO off: 28; shift windows by 10 minutes: 163 and 116). Remove any flag that changes 0 rows. (EVR section 4)

### 7.2 E5 Cheap targeted audit with arbiters

What we did (AUDIT):
- 61 evaluation cases picked by a fixed seed from strata: 13 media or hand-crafted, 26 first-in-first-out ties, 12 timing-linked, 10 high-confidence controls.
- Independent auditors labelled each case from raw files and the task statement only. They did not see solver output or the solver spec.
- An adversarial pass disputed labels against the output (14 disputes).
- An arbiter confirmed or rejected each dispute with line citations (12 confirmed).
- Every confirmed defect was fixed by a general rule, never a per-case patch. Two root causes explained 49 changed rows and 0 status changes.
- Calibration: auditors first labelled sample cases blind. Contamination (one public gold line printed by a search) was disclosed in the record.

Lean version for next time:
- run it once, when features are complete, with 30 to 60 cases;
- use it as a bug hunt, never as an accuracy estimate;
- state the contamination rules for auditors (no gold, no solver output);
- check that fixes do not move the sample scores;
- re-audit any rows moved by a late change (20 rows moved after our last audit were not re-audited. AUDIT).

---

## 8. What was overkill in evaluation (cut list) and what to do instead

Planning, release-gate and verification overkill is listed once in `DEVELOPMENT_STRATEGY.md` section 3 and `SUBAGENT_DELEGATION.md` section 5. This table covers evaluation only.

| Overkill | Evidence it did not pay | Do instead |
|---|---|---|
| Estimation sample protocol with statistics | Never drawn; cannot be unbiased with 32 labels; certifying needs about 100 cases (LES; AUDIT; MANIFEST R4 waived) | Report in-sample scores honestly; use the audit for bugs (section 7) |
| Clean-room matrix over many cells | Single cell finds the same README errors | One clean directory, run the README quickstart verbatim (R81 check 3) |
| Ten inference flags and 13 ablation variants | One flag changed 0 rows (DECISIONS D16); `batch` mode was dead config (BENCH section 2) | Cap flags (R38); delete flags that change 0 rows |
| Custom log lint rules beyond the AGENTS.md format | Still left warnings (PANEL) | One append-and-lint script (R56); match the format exactly |
| Judge panel with our own personas | Scores did not match official dimensions (PANEL versus BENCH) | Official dimensions (section 6, Appendix A) |

Size rule: non-solver tooling should stay under about 25 percent of solver size (our inference). Ours was about 100 percent (about 8.0k lines of evaluation, tools and devtools, tests included, against about 8.0k lines of solver; `wc -l`).

---

## 9. Definition of done

Use the one final gate in `RULES.md` section K. Its Evaluation lines cover E0 to E8. If a line cannot be ticked, fix it or write the reason in the report. Do not build a waiver mechanism.

---

## 10. Time budget (recommended, for a 24-hour event; scale if shorter)

Share of total time (our inference). Our actual build took about 11 hours with tooling at about the size of the solver, so the target share is smaller.

| Activity | Budget | Exit rule |
|---|---|---|
| E0 validator | 0.5 h | Passes on the blank template and on the samples |
| E1 sample scorer | 1 h | Prints G1 to G8 and a diff |
| E2 invariants | 1 h | Runs over all rows in under 10 s |
| E3 custom cases | 2.5 h | The R49 target passes, rendered into the report |
| E4 ablations | 1 h | Table filled from a script |
| E5 targeted audit | 2 h | Disputes closed; samples unchanged |
| E6 judge panels (M1, M2 single judges; M3 full panel) | 1.5 h | Each run produces a ranked fix list; top gaps handled |
| E7 package check | 1 h | Clean directory run works |
| E8 interview rehearsal | 2 h | Walk-through of one case, spoken answers to all probes |
| Report writing | 1 h | Auto-filled; `--check` passes |
| **Total** | **about 13.5 h of attention** | Spread across the build, not stacked at the end |

Order of work (fixed): E0, E1, E3 drafted, build, E2, E6 at M1, fix, E4, E6 at M2, E5, fix, E7, E6 at M3, E8.

Rule: run a panel run whenever a milestone completes. Do not wait for "done".

---

## 11. Reporting requirements (from the task)

`evaluation_report.md` MUST have (`AGENTS.md` 6.8):
- case-level status accuracy;
- step-level and field-level accuracy;
- sequence accuracy;
- at least three extra cases created by the participant;
- failures found and improvements made.

`usage_report.md` MUST have: providers and models; call counts; input and output tokens; total and per-request tokens; estimated total and per-request cost; per-model and overall totals.

SHOULD add:
- the strategy comparison (E4);
- a short honest section "what these numbers do not show" (in-sample, structural losses);
- the cold-run cost and the cached-rerun cost, both. Ours: $0.8563 cold, $0 cached rerun. (usage report)

MUST NOT include keys, credentials or real personal data in either report.

---

## Appendix A: official-dimension judge prompts (reusable)

Use one prompt per signal. Replace the bracketed parts. How many judges to run at each milestone: section 6.

### A.1 Code zip judge

```
You are a strict judge of a HackerRank Orchestrate code zip. Score 0-100.
You see only the unzipped folder. Score only what is observable in source.
README claims, comments about intent, and unused imports count for nothing.

Dimensions (weights):
1. Agent architecture (30%): Is this an agent or a hardcoded workflow with LLM
   calls? Look for tool-calling loops, model-driven routing, multi-agent handoffs.
2. Prompt and tool craft (30%): role assignment, constraints, structured output,
   refusal conditions, tool descriptions.
3. Agent robustness (25%): guardrails, retries, max-iteration caps, output
   validation, retrieval quality.
4. Engineering rigor (15%): modularity, type hints, secrets via env, function size.

For each dimension give: a score, the file and line evidence, and the gaps.
Also name the architecture bucket (single agent with tools, multi-stage,
graph, single prompt, deterministic rule pipeline, other).
Finish with the five highest-value fixes, ranked.
```

### A.2 Output judge

```
Score this output file 0-100 against the problem statement. Use only the
statement, the input files and the sample answers. Do not read solver code.
Give: per-item accuracy estimate on a stratified sample you label yourself,
a safety score (injection, multilingual, decoys, non-actionable requests),
and a list of rule violations of the problem contract. Flag any generic or
contradictory justification text (capped near 70).
```

### A.3 Transcript judge

```
Judge only how the participant directed the coding agent. Score 0-100.
1. Direction and architecture ownership (35%): defines architecture, chooses
   tradeoffs, pushes back.
2. Technical specificity and constraint (25%): models, libraries, schemas,
   paths, thresholds, formats, API limits.
3. Iteration and verification (25%): runs tests, shares errors, reviews rows,
   measures regressions, directs targeted fixes.
4. Safety, edge cases, quality (15%): injection, ambiguity, multilingual,
   out-of-scope, response quality.
Count user turns that only approve ("go ahead", "recommended") as zero direction.
Check the Context block of every entry. Cite log line numbers.
```

### A.4 Interview rehearsal prompt

```
Act as a 30-minute voice AI judge. Probe in this order: pitch, retrieval and
architecture, safety and failure modes, implementation and code familiarity,
evaluation, production monitoring, novelty, and how I used AI tools.
Score: technical depth and ownership 40, problem understanding and judgment 25,
communication 20, honesty 15. Penalize any claim not backed by the code.
Ask one follow-up on every answer that lacks a number, a tradeoff or a failure mode.
```

### A.5 Seeded-defect calibration

Before trusting a panel, copy the project and seed two defects that the rubric should catch (for example a wrong command in the README quickstart, and missing token totals in the usage report). If the panel does not name both as its first deductions, fix the prompt. (PANEL "Panel calibration")
