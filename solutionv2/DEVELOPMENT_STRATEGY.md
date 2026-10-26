# DEVELOPMENT_STRATEGY.md: how to spend 24 hours

This file owns the build process: timeline, scope, planning artifacts, decision log and when to ask the user.
Principles are in `CONSTITUTION.md` (P6, P7, P11). Hard rules are in `RULES.md`.
How to talk to the coding agent is in `PROMPTING_STRATEGY.md`. How to run sub-agents is in `SUBAGENT_DELEGATION.md`.
Token and money budgets are in `TOKEN_COST_EFFICIENCY.md`.

Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

---

## 0. What went wrong last time (process only)

The product was good (output about 89/100 in BENCH). The process was heavy. The score lost points where the process was not aimed at the rubric.

| What happened | Cost | Evidence |
|---|---|---|
| About 3 hours (14:12Z to 17:08Z) of analysis, spec, reviews and planning before the implementation prompt. Before that prompt the plan had 46 task files (2,242 lines), a 38 KB spec, four recorded review rounds and two strategy documents (3,653 lines in all). | Time. The agent architecture was fixed by AI-written specs, not by the user. | LOG first prompt 14:12Z, implementation prompt 17:08Z; PLAN (files last changed 16:39Z); BENCH section 4 |
| `code/main.py` was still empty about 45 to 60 minutes into implementation (about 4 hours after the first prompt), while many tasks were already "verified". | No end-to-end output to look at. Defects showed late. | LOG verifier notes 17:52Z to 18:07Z: "code/main.py is still empty" (T21 pending) |
| The LLM was bolted on for two narrow jobs. No tool loop. | Agent architecture 25-30 of 100 (30% weight). Code judges 61-64. | BENCH section 2 |
| The API key came late (18:54Z, 1h46 after implementation began). The 3.9 vs 3.10 split (system Python 3.9.6, SDK needs 3.10) was known in planning and forced a two-toolchain design. "No sampling parameters" was found in the docs at planning time. | Live checks and the cache fill waited for the key. A second toolchain (uv, Python 3.12) and a 3.9-safe stdlib core. | LOG 15:39Z, 16:19Z, 18:54Z; DECISIONS D6, D7 |
| Policy changes (rework model, verify model) needed stop-and-resume of a running workflow. | The same task was implemented and verified 3-4 times in the log. | LOG 17:48Z, 17:56Z, 17:58Z; BENCH section 4 |
| One combined verification at the end instead of per-task checks. | It rejected 6 of 15 tasks. Defects were found late. | BENCH section 4 (LOG line 3660) |
| About 2.4k lines of release tooling in `devtools/` (about 4.3k with tests): 12 gates, clean-room matrix, blind audit, panels. Moved out of the zip late (LOG 23:05Z). | Hours of work. R4 and R9 were still waived at the freeze. | MANIFEST waivers; devtools/ |
| Accuracy was measured only on the 32 public samples that were also used to tune the rules. | "In-sample" deduction on every judge. No honest held-out estimate. | PANEL deductions; MANIFEST R4 waived |
| A close-out agent changed defaults (model, signature) without approval. | Rework, and a weak "who decided" story. | LOG 00:37Z group entry |
| The user's turns: 22 of 183 log entries. 4-7 of them were status checks. | Transcript 58-60 of 100. | BENCH section 4 |

Lesson in one line: **get a thin working agent early, aim every hour at a rubric dimension, and keep the process light.**

---

## 1. The 24-hour timeline

Times are hours from the event start (H0). Every phase has a time box, an output and an exit test.
If a box is over by 25%, stop and cut scope (section 3). Do not borrow time from phases 3 and 4.

| Phase | Hours | Goal | Output (files) | Exit test |
|---|---|---|---|---|
| 0. Preflight | H0-1 | Remove all blockers | `.env` with key, toolchain note, `log.txt` SESSION START, first log entry | One real model call works. Python and SDK versions match. Log tool appends a valid entry. |
| 1. Contract and data | H1-3 | Know exactly what is graded | `CONTRACT.md` (1 page), `DATA_FACTS.md` (generated), `LOOPHOLES.md` | You can state the output schema, the ordering rules, the time rules and the 5 hardest traps in your own words. |
| 2. Architecture decision | H3-4 | Choose the agent shape and the guardrails | `DECISIONS.md` first 5 entries, `AGENT_POLICY.md` (1 page), `TASKS.md` (one checklist) | The user has written the architecture in a prompt (see `PROMPTING_STRATEGY.md` A1). |
| 3. Thin end-to-end slice | H4-7 | A valid `output.csv` for every request | Runnable CLI, validator, scorer, baseline decision logic, tests for the validator | `output.csv` has the right header and row count. Validator is clean. Sample score is printed. Tag `v0`. |
| 4. Agent layer | H7-11 | The model is a real agent in code | Tool loop (3-5 typed tools), step cap, schema-validated final answer, deterministic veto, fallback, versioned prompts | A trace shows model-chosen tool calls on an ambiguous case. Cap and fallback tests pass. |
| 5. Accuracy loop | H11-17 | Raise accuracy with measured, targeted fixes | Failure list, one ablation table, updated `DECISIONS.md` | Sample status accuracy is stable. No change is kept without before/after numbers. |
| 6. Evidence docs and packaging | H17-19 | Reports that match the run | `evaluation_report.md`, `usage_report.md`, `README.md`, zip script | Reports are generated from run output. A clean-room run reproduces `output.csv`. |
| 7. Independent review | H19-21 | Find the top deductions | The M3 judge panel (`EVALUATION_STRATEGY.md` section 6), fix list | Top 5 deductions fixed or disclosed. |
| 8. Freeze and submit | H21-22 | One clean final run and upload | Final `output.csv`, `code.zip`, `log.txt`, hashes | Validator clean. Rerun is byte-identical. Zip has no dataset, no secrets, no PII. |
| 9. Interview prep | H22-24 | Be able to explain every part | Code walk-through and one timed rehearsal (R82; content in `RUBRIC_PLAYBOOK.md` section 4.2) | You can trace one case end to end without notes. |

Notes:

- Phase 3 target is H5. H7 is the hard limit. If there is no valid output by H7, drop every plan except the baseline.
- Phase 4 starts before accuracy work. Reason: Agent architecture (30%) and Prompt/tool craft (30%) are 60% of the code score, and changing the architecture late is expensive. Evidence: BENCH section 2, all three: "No tool-calling loop" is the first gap.
- Put the interview in the plan. It is 30% of the final score (NOTES section 2) and last time it was an afterthought. Follow the one schedule in R82: decision ledger from H3, prep guide drafted at the freeze, walk-through and rehearsal in H22-24.
- Run a single official-dimension judge at the end of phase 3 (M1) and phase 4 (M2), and the full panel in phase 7 (M3). The policy is in `EVALUATION_STRATEGY.md` section 6.
- Submit early. Do not use the last hour for features. Use it for a clean rerun and a checklist.
- Keep a 2-3 hour buffer in the plan: phases 0-9 above sum to 24 hours only if nothing slips; treat phase 5 as the shock absorber.

### 1.1 Phase details

**Phase 0. Preflight (H0-1). Do these in order.**

1. Read the problem statement and the repo contract file (`AGENTS.md` style) fully. Write down every MUST in `CONTRACT.md`.
2. Put the API key in `.env` before the first build prompt and say "the key is in .env". Never paste a key into the chat. Last time the key arrived at 18:54Z, 1h46 after implementation began (LOG), and live checks waited for it.
3. Check versions: `python3 --version`, SDK minimum Python, `pip index versions` or the package page. Pick one toolchain now (for example `uv` with a pinned Python). Evidence: Python 3.9.6 vs SDK 3.10 was known in planning (LOG 15:39, 16:19) but the plan kept 3.9 for the core, which cost a second toolchain (DECISIONS D7).
4. Make one live call with the real model, with `max_tokens` small. Note which parameters are rejected (last time: `temperature`, `top_p`, `top_k`; DECISIONS D6), the cheap model IDs, and whether prompt caching reports `cache_read_input_tokens`.
5. Install the log-append helper (a 100-line script that writes the exact entry format and re-reads it). Evidence: all 183 entries of the last log were format-valid (BENCH section 4), which is why Context-block failure (half of edition-1 transcripts) did not hit.
6. Write the agent policy (`AGENT_POLICY.md`): models per role, verification mode, rework rule, token budget. See `SUBAGENT_DELEGATION.md` section 2.

**Phase 1. Contract and data (H1-3).**

- Profile every input file with a script, not by hand: row counts, key uniqueness, null rates, date ranges, value histograms. Write the output to `DATA_FACTS.md`. Sub-agents read this file instead of re-profiling (saves tokens; see `TOKEN_COST_EFFICIENCY.md` section 9).
- Study the public sample answers first. They are the only labelled data. Find the rules that reproduce them.
- Hunt for traps: claims that are wrong, decoys, later-dated evidence, near-duplicate identities, non-actionable requests, multilingual text, injected text inside data. Write each as a one-line loophole with a test idea in `LOOPHOLES.md`.
- Decide the small-sample policy (`EVALUATION_STRATEGY.md` section 3.3; R48) before looking at errors.
- Example (Ghost Data): the analysis found that `reported_status` lies, that evidence after `audit_at` is a trap, that 10 requests were not deletions, and that some evidence is only in images and PDFs (ANALYSIS section 1). That one page drove the whole build.

**Phase 2. Architecture decision (H3-4).**

- The user decides the shape and writes it in their own words. The AI proposes two or three options with costs. See `ARCHITECTURE.md` for the target pattern.
- Fix these six choices now: (1) which parts are model-driven, (2) which tools the model gets, (3) which checks are deterministic and can veto the model, (4) the step and token caps, (5) fallback behaviour when the model fails, (6) the default model per role.
- Write each as a `DECISIONS.md` entry (section 4) before coding.
- One critical review of the plan, not four. Evidence: four recorded review rounds produced a 13 KB spec review and a 13 KB plan review, and the final judges' top gaps were still architecture-level (PLAN; BENCH section 2).

**Phase 3. Thin slice (H4-7).**

- Build in this order: dataset reader (read-only, allowlist), types, output writer, output validator, scorer, then the simplest decision logic that produces a legal row for every request.
- The first output may be wrong. It must be valid. Wrong-but-valid output gets partial credit and shows where the problems are (NOTES section 4: per-item 0-100 scoring).
- Run the scorer on the samples after every change from now on. The loop must take under one minute (section 6).
- Commit/tag `v0` only if the user asks (repository rule); otherwise write the sha256 of `output.csv` in `PROGRESS.md`.

**Phase 4. Agent layer (H7-11).**

- Add the tool loop on the ambiguous path first, then widen. Tools are thin wrappers over the deterministic functions you already wrote in phase 3.
- Required in code, not in the README: max iterations, per-call token cap, schema validation of the final answer, a deterministic veto the model cannot override, a fallback to the baseline when the loop fails. Evidence: all three BENCH code judges wrote the same fix (section 2): "add a real bounded tool-calling investigator ... max-iteration cap ... deterministic resolver as guardrail". One judge estimated +35 to +45 on that dimension.
- Do not claim an agent you did not build. Evidence: NOTES section 6 (fabrication is penalized).
- Prompts live in versioned files. See `PROMPTING_STRATEGY.md` part B.

**Phase 5. Accuracy loop (H11-17).** The loop is the same every time:

1. Run the scorer. List the failing rows grouped by cause.
2. Pick the biggest group. Write the suspected cause in one line.
3. Make the smallest general fix. No per-case override (a rule that names a case id or a dataset-fitted constant is a deduction).
4. Re-run everything. Compare before and after, including rows that were right.
5. Keep the change only if nothing else regressed. Add one line to `DECISIONS.md` with the numbers. Revert otherwise and say so.
6. Time box: 45 minutes per failure group. If not solved, record it as a known limit and move on.

Stop rule: when two iterations in a row gain less than 0.5 points of the sample metric (or fewer than 1 case), stop and go to phase 6. Evidence: the last build kept tuning till the freeze and two waivers were still needed (MANIFEST).

**Phase 6. Evidence docs (H17-19).** Generate numbers from the run (a 100-line renderer with a `--check` flag). Last time reports drifted from the code and a judge caught it (BENCH rc1 fixes; LOG 00:31Z "report drift"). Include in the evaluation report: status accuracy, step and field accuracy, sequence accuracy, at least three custom cases you wrote, failures and fixes (the problem statement lists these; check the new one).

**Phase 7. Review (H19-21).** The M3 panel: `EVALUATION_STRATEGY.md` section 6.

**Phase 8. Freeze.** Run the final gate in `RULES.md` section K.

---

## 2. Keep scope small

Use MoSCoW (see `REQUIREMENTS.md` section 4). In addition:

- **MUST for scoring:** valid output for every request; a real agent loop with guardrails; versioned prompts with refusal conditions; evaluation report with held-out and custom cases; usage report; README with setup and run commands; a complete, honest log.
- **SHOULD:** a small set of ablations (agent on/off, cheap vs strong model); per-case diagnostics file; cache and offline replay.
- **COULD:** extra parsers for rare formats, clean-room matrix, multiple review panels.
- **WON'T (unless 8+ hours are left after the accuracy goal is met):** release gates beyond the three checks of R81, estimation-sample protocols, confidence ledgers, log lint v2, judge panels beyond the policy in `EVALUATION_STRATEGY.md` section 6.

Scope rules:

1. Every module must map to a rubric dimension or a problem-statement MUST. If you cannot name which, do not build it. Evidence: about 2.4k lines of `devtools/` Python (about 4.3k with tests) did not appear in the zip and did not move the judged scores.
2. Do not list or ship a mode you do not support. Evidence: the unwired `batch` LLM mode cost points on three code judges (BENCH: "dead configuration").
3. One way to run. One `python3 code/main.py` style entry with flags. No second pipeline.
4. Prefer 200 lines that run over 1,000 lines of plan. A plan line should save at least a line of rework.
5. Cap the number of toggles. Ten inference flags and a fixed-point solver were called "a lot of moving parts" with constants "without a stated source" (PANEL, quality persona). Every flag needs a measured reason in `DECISIONS.md` or it is removed.
6. Cut by the rubric weights: Output 30, Code 30, Interview 30, Chat 10 (NOTES section 2). A feature that helps only the 15% sub-dimension of one signal comes last.
7. If a required input family is rare (for example 15 of 94 evidence files were images/PDFs), handle it in a separate, cached pass so it cannot block the main path. Evidence: DECISIONS D2.

---

## 3. Planning artifacts: worth it or overkill

Test for any document: does a **sub-agent consume it as a brief**, does a **judge or interview probe use it**, or does a **test derive from it**? If none, skip it.

| Artifact | Verdict | Size to aim for | Why / evidence |
|---|---|---|---|
| `CONTRACT.md` (the problem's MUSTs, output schema, ordering, time rules, forbidden inputs) | Worth it | 1-2 pages | Every brief and every validator test points to it. |
| `DATA_FACTS.md` generated by script | Worth it | auto | Stops each agent re-profiling the data. |
| `LOOPHOLES.md` (traps and their tests) | Worth it | 1 page | Feeds custom cases and the safety score. The last build had 7 custom cases; judges still said edge classes were AI-originated (BENCH section 4). |
| `DECISIONS.md` (ADR-lite: context, decision, alternatives, evidence, who decided) | Worth it | 8-15 entries | Code judges and the interview used it (BENCH section 5: answers cite D1, D3, D5). |
| `AGENT_POLICY.md` (models, verify mode, caps, forbidden changes) | Worth it | 1 page | Prevents stop/resume and silent default changes. |
| `TASKS.md` single checklist with owner, files, acceptance command | Worth it | 1 page, at most 15 tasks (R79) | Replaces 46 task files. |
| `PROGRESS.md` updated by the orchestrator | Worth it | 20 lines | Replaces status-only user turns. The last user asked "what's the status" in 4 turns (LOG 17:59Z, 18:57Z, 19:06Z, 20:42Z). |
| Detailed spec with rule IDs (36-38 KB) | Overkill | at most 4 pages | Long specs were the AI's, not the user's; the user's direction score suffered (BENCH section 4). Put rule IDs in code docstrings only when tests cite them. |
| Spec review + plan review rounds (13 KB each) | Overkill | one 1-page review | The final judges' main gaps were not found by these reviews. |
| Scoring strategy and local evaluation strategy docs (13 KB and 22 KB) | Overkill | fold into the decision log | Useful ideas (honest ceiling, Pareto no-regression, pre-registered threshold) fit in 15 lines. |
| 46 task files (2,242 lines) | Overkill | one checklist | Each task was briefed, implemented, verified, and often re-verified. |
| Release gate with 12 gates, clean-room matrix, blind audit, confidence ledger | Overkill | the 3 checks of R81 | Two gates ended waived (MANIFEST R4, R9). |
| Judge panels with the official dimensions | Worth it, at milestones | single judge at M1 and M2, full panel at M3 (`EVALUATION_STRATEGY.md` section 6) | The calibration seeded 2 defects and both were caught (PANEL calibration). Our own personas scored far above the official-dimension judges (`RUBRIC_PLAYBOOK.md` section 0.2). |
| Interview prep guide | Worth it | 1-2 pages, drafted at the freeze (R82) | Interview is 30%. Write it from the final code and the decision ledger, not from the plan. |

Rules for planning:

- **Plan the next 3 hours in detail, the rest in headlines.** Plans beyond that change.
- **One review per plan, by a different model or a different persona**, with a 20-minute limit.
- **Plans live in files that agents read.** Do not paste them into briefs (`TOKEN_COST_EFFICIENCY.md` section 9).
- **A plan item has an acceptance command.** If you cannot write the command, the item is too vague.

---

## 4. The decision log

Why: judges ask "why this and not that", the interview asks what you chose and rejected (NOTES section 6, pattern 4), and the transcript scores direction. A decision log makes all three cheap.

Write an entry when you (a) choose between real options, (b) reverse something, (c) keep a measured regression or a disclosed limit, (d) set a default model, flag or threshold.

Template (copy it):

```text
## D<n>. <decision in one line>
- Date/time (UTC) and phase:
- Decided by: USER | AI proposed, USER approved | AI (within delegated scope)
- Context: what forced the choice (1-3 lines)
- Decision: what we do
- Alternatives: what we rejected and why (at least one)
- Evidence: measured numbers with the command or file that produced them
- Reversal: how to undo, and what it costs
- Risk / known limit: honest, one line
```

Rules:

1. **Numbers, not adjectives.** "S2 matches S1 on 32/32 samples and 518/518 rows, $0.34 vs $0.86 cold run" beats "Haiku is fine" (DECISIONS D5, evaluation report strategy table).
2. **Record the reverts.** A measured regression you reverted is the strongest interview answer (NOTES section 6, pattern 2). Example: "signature OFF 29/32 vs ON 32/32; late audit ids OFF -124 steps" (NOTES section 9).
3. **Record who decided.** The last panel could not tell human from AI decisions. Put the user's turn timestamp in "Decided by".
4. **Every constant has a source.** A constant needs one of: the problem statement, the data (with the command that derived it), or a decision entry. Evidence: "unexplained constants" and "dataset-fitted windows" were the top code deduction in PANEL (rules 1 point, quality 1.5 points).
5. **Contract deviations are user decisions with a flag.** If the data or samples suggest the grader deviates from the written contract (for example using evidence after the cutoff), do not decide alone. Measure the effect with the flag on and off, show both numbers to the user, default to the contract-compliant setting unless the user decides otherwise, and disclose the choice in README. Evidence: PANEL "late evidence" deductions (0.5 each from the rules and newcomer personas) and BENCH section 4 on the accepted deviation.
6. **Pin defaults in a test.** A test asserts the default model, flags and thresholds listed in `DECISIONS.md`. Changing a default then needs a decision entry in the same change. Evidence: LOG 00:37Z, a close-out agent changed two defaults without approval.
7. **Keep decisions in the repo (shipped)**, short, and without task IDs or internal tags. Judges said planning tags in source read as scaffolding (BENCH: "process scaffolding inside source").

---

## 5. Evaluation inside the development loop

The evaluation design is owned by `EVALUATION_STRATEGY.md`. The development habits are only these:

1. Build the validator and the scorer before the solver (R47), and run them after every change (section 6).
2. Decide the small-sample policy before tuning (`EVALUATION_STRATEGY.md` section 3.3; R48). Do not hold out samples you need to fit the rules.
3. Write custom cases from `LOOPHOLES.md` before the code they test, up to the target in R49.
4. Call sample numbers "development-set" numbers, and state the structural ceiling when you can compute one (`EVALUATION_STRATEGY.md` section 3.4).

---

## 6. Faster development and verification loops

1. **One fast gate, under 60 seconds.** Unit tests of the changed module, validator, sample scorer, determinism check. Run it after every change. Run the full suite at phase ends. (Last build: offline run of all 518 requests took about 0.9 s; `code/docs/ARCHITECTURE.md` section 5.)
2. **Offline mode first.** Every LLM call goes through one client with `off | cache | live` modes. Develop with `cache`; use `live` only to fill misses. Same cache gives byte-identical reruns. See `ARCHITECTURE.md` section 7.
3. **Fake client for tests.** Unit tests never call the network.
4. **Typed boundaries first.** Write dataclasses and the output schema before logic. Sub-agents then work in parallel with fewer merge errors.
5. **Acceptance commands in the brief.** The implementer runs them. The verifier only needs to re-run them. See `SUBAGENT_DELEGATION.md` section 4.
6. **Look at output, not only tests.** Print 5 random rows and the 5 lowest-scoring rows after each phase. Paste them into your next prompt (this is also what the transcript rubric wants; `PROMPTING_STRATEGY.md` A4).
7. **Small commits to the working tree are not needed; small checkpoints are.** After each phase write the output hash and the sample score into `PROGRESS.md`.
8. **Kill criteria.** If a feature has not produced a measurable gain in its time box, remove it. Example: a learned timing signature gave a large gain but was a generator artifact; it needed a long defense and was still a top deduction (PANEL). If the only justification is "it raises the sample score", ask the user first (section 7).

---

## 7. When to ask the user

The user owns decisions (CONSTITUTION P6). Ask early, in batches, with numbers. Do not ask about things the agent can decide.

**Ask when:**

- A choice changes the architecture, a default model, a threshold, or the scope.
- A choice deviates from the written contract or the time rule (section 4, rule 5).
- A choice spends money above the budget (`TOKEN_COST_EFFICIENCY.md` section 1).
- A rubric trade-off exists (for example, a measured score gain vs a likely code-judge deduction).
- A destructive or irreversible action is needed (delete files, force push, drop cache).
- Something needed is missing (API key, a file, a tool version).
- Two attempts at the same fix failed.

**Do not ask when:** naming, file layout, formatting, which test to run, how to word a doc, or anything already in `DECISIONS.md` or `AGENT_POLICY.md`.

**How to ask:**

1. Ask all open questions in one message at the end of phases 0, 2, 5 and 7. Not one by one.
2. Each question: two or three options, one line each, with a measured effect and a cost. State the tradeoff. Do not label an option "(Recommended)" for architecture or contract choices (R69); a recommendation is fine for routine choices.
3. Tell the user: "Answer in your own words, with the constraint you want." Evidence: the last user's replies to option lists were "(Recommended)" and "Go ahead" (LOG 22:33Z, 23:21Z), which the transcript judges counted as weak direction (BENCH section 4).
4. After the user replies, write the decision entry (section 4) with the user's wording.
5. Never block on an answer. Continue with the contract-compliant default and mark the work "pending decision".

**Questions to batch in phase 0:** key and budget; model policy; verify policy; time rule if unclear; whether to commit; who writes the architecture prompt.

---

## 8. Freeze and submit checklist

Use the one final gate in `RULES.md` section K. Do not keep a second checklist here.

---

## 9. Quick reference: the five rules that would have saved the most time

1. Preflight in hour 1: key, versions, one live call, log tool, agent policy.
2. Valid `output.csv` by H5, from a baseline, before any polish.
3. Put the agent layer in at H7-11, not after accuracy work.
4. One fast gate, one honest held-out set, one decision log.
5. Cut the release machinery down to the three checks of R81; spend the hours on the agent, the prompts and the interview.
