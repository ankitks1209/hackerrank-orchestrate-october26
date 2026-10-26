# LESSONS_LEARNED.md: what we missed, what worked, what it cost

Project: Ghost Data Still Exists (October 2026). Result: frozen release rc4. Benchmark against the edition-1 rubric: about 75 out of 100 (code about 62, output about 89, chat about 59, interview readiness about 80). See `RUBRIC_PLAYBOOK.md` section 0.1.

How to read this file:
- Section 1 is the gap table. It is the main output.
- Section 2 covers process and cost.
- Section 3 covers what worked and must be repeated.
- Section 4 is a short "do differently" list that points to the file that owns each fix.

Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

---

## 1. Gap table

### 1.1 Product gaps (what the judges found)

| # | Gap | Evidence (score or deduction) | Root cause | Fix for next time |
|---|---|---|---|---|
| G1 | No real agent. Fixed pipeline, LLM only for intent and image reading. | Agent architecture 25, 30, 25 of 100, dimension weight 30% (BENCH section 2). Total code 61.2, 64, 62. Edition-1 "deterministic rule pipeline" bucket averaged rank about 933 (NOTES section 8). | Decision D1 chose a deterministic core "for testability" (DECISIONS D1). It was made in planning, before the rubric was read (see G12). | Read the rubric first. Make a bounded tool-calling investigator the core and keep rules as validator and veto. See `ARCHITECTURE.md`. |
| G2 | Thin prompt and tool craft. Two prompts, no tool descriptions, no abstain option. | Prompt craft 68, 72, 70 (BENCH). Judges: "no tool definitions", "refusal conditions only implicit". | LLM scope was kept narrow on purpose. No prompt existed for reasoning, planning or verification. | Write prompts and tool descriptions as first-class artifacts with role, rules, schema, abstain. See `RUBRIC_PLAYBOOK.md` 1.2. |
| G3 | Constants fitted to this dataset. Link windows from "observed spread". Learned latency signature. | Panel majors: 1 and 1.5 points (PANEL). Judges: "brittle outside this dataset" (BENCH). Shifting every window by +10 min costs 8 of 30 exact matches (EVR section 4). | Reverse-engineering how the data was generated, then encoding it. The 32 samples were also the tuning set. | Link by identifiers in the files. Any learned parameter is fitted at runtime, gated by confidence, switchable, and reported. Never ship a number without its source. |
| G4 | Case-family shortcut: `user_01..10` maps to `account_00N`, an id no file contains. | All three panel personas: quality major 1, rules major 0.5, newcomer minor 0.25; `AGENTS.md` 6.7 forbids shortcuts (PANEL). Affects 3 eval rows (DECISIONS D11). | One sample showed the pattern, so it was generalized. | Rule: never derive an id that no file shows. If the step cannot be grounded, omit it. |
| G5 | Used evidence captured after the cutoff (ids only) by default. | `use_late_audit_ids` changes 124 rows; sample exact falls 30 to 25 when off (DECISIONS D9). Panel major 0.5 (PANEL). Chat judge: "knowingly accepts a deviation from the contract" (BENCH). | The public gold answers appear to need it, so contract and gold conflicted. The user chose "Keep + disclose" (LOG 22:33Z). | Decide contract-versus-gold conflicts at hour 2, in the user's own words, with numbers. Prefer the contract. Keep a one-flag switch and disclose. |
| G6 | All accuracy figures in-sample. | Flagged by all three panel personas (PANEL). 32 samples, no held-out split (EVR section 1). | Rules were tuned while looking at the only labelled rows. | Build custom cases early for uncovered families. Hold out part of the samples if there are enough. Name the number "development-set score". |
| G7 | One unknown input row aborted the whole run. | Panel minor 0.5 from the quality persona only (PANEL): `UnclassifiedActivityError`. Fixed in rc4 (MANIFEST: now classified UNCLASSIFIED, inert, warned once). | Strict parsing was treated as a virtue. | Never let one bad row stop a batch. Degrade, count, report. |
| G8 | Too many moving parts. Ten inference flags and several constants with no stated source. | Panel minor 0.5 (PANEL). One flag (`exclude_orphan_policy_rows`) changed 0 of 518 rows (DECISIONS D16). `batch` LLM mode was dead config (BENCH). | Each uncertain choice was hidden behind a flag instead of being decided or cut. | Cap flags at about 5. Remove any flag that changes 0 rows. No dead modes. |
| G9 | PII in the shipped cache. | 843 cached responses; ten had names and emails from images and PDFs (PANEL). Fixed in rc4 by redaction at write (DECISIONS D25). | Cache stored raw model output. | Redact before write. Check the zip with a PII scan. |
| G10 | Structural output loss: audit-record ids not findable. | About 83 INCOMPLETE rows lacked one step (about 80 steps). Sample misses: case_18 and case_20 (BENCH; EVR section 2). | The id existed only in later files or in no file. | Measure the ceiling in hour 1 to 2 (we did; `plan/LOCAL_EVALUATION_STRATEGY.md` section 0). Accept it, disclose it, spend no more time. |
| G11 | 12 COMPLETE rows lacked the account verification step. | BENCH section 3 gaps. Fixed later by D22 (topology snapshot as cite-only proof, 33 rows; AUDIT). | Citation rule was too strict for a snapshot type. | Run a targeted audit earlier, once features are done (AUDIT found 12 confirmed defects with 2 root causes). |
| G12 | The official rubric was read after the architecture was frozen. | `plan/SCORING_STRATEGY.md` (16:19Z) said "No official Orchestrate rubric is published" and used the June README. The edition-1 rubric notes were extracted at 23:44Z (LOG), after code was built (alignment audit at 22:15Z). | The rubric article was not searched for at the start. | Hour 0: find and read every past rubric. Write the rubric-to-build map before choosing an architecture. |
| G13 | Our own judge panel measured the wrong thing. | Panel: code 26 to 27.5 of 30, transcript 9 of 10 (PANEL). Official-dimension judges: code about 62 of 100, transcript about 59 of 100 (BENCH). | Personas used our own categories, not the four official dimensions. The panel ran at the end. | Use the official dimensions and weights verbatim. Run at milestones. See `EVALUATION_STRATEGY.md` section 6. |
| G14 | Output order was numeric-aware (`case_99` before `case_100`). | Panel minor 0.25 (PANEL); BENCH section 3 note. | The contract said "Sort rows by case_id" and we picked the natural reading. | Pick the literal reading (plain string sort) unless the sample file shows otherwise. Write the decision down. |
| G15 | Engineering untidiness. | `sys.path` edit in `main.py`; task tags (T14, T26, T35) inside config; unwired `batch` mode (BENCH). | Process scaffolding leaked into source. | Keep planning tags in `plan/`. Use `pyproject.toml` entry point. Lint for dead config. |

### 1.2 Transcript and interview gaps

| # | Gap | Evidence | Root cause | Fix for next time |
|---|---|---|---|---|
| T1 | Transcript scored about 59 although format was perfect. | Chat 58.6 and 60 (BENCH). All 183 entries were valid. | The AI wrote specs and the user mostly approved. Direction and technical specificity were low (61 and 47 to 50). | The user writes architecture, constraints and verification turns. See `CONSTITUTION.md` P6 and `RUBRIC_PLAYBOOK.md` 3.2. |
| T2 | Many "approve the recommended option" turns. | LOG 22:33Z "Time rule: Keep + disclose (Recommended)"; 23:21Z "Go ahead"; 23:18Z "what is your recommended next step?". About 7 of 22 turns were status or acknowledgement (BENCH). | Agent asked choice questions. Reading the options and picking was fast. | Answer with a reason and one constraint. Do not ask the AI what to do next. |
| T3 | The user's voice was a small share of the log. | 22 user turns, 160 sub-agent entries, 1 session start (BENCH). | Every sub-agent wrote its own entry. Stop and resume re-logged tasks: T02b appears at log.txt 366, 457, 1159, 1272, 1969 (BENCH). | Log only per milestone for sub-agents (a group entry), not per task. Do not re-run finished tasks. |
| T4 | Trace gaps and format warnings. | rc3 sub-agent entries with no main-session turn (major 0.5); a 6-sentence summary where 2 to 5 is allowed; a dataset email inside a logged call (PANEL). | Sub-agent entries were not tied to a main-session turn; LOG line 1144 mentions "removed turns" and tells the linter to treat trace gaps as warnings. | Use one append-and-lint script from the start. Never delete entries. Never log dataset identifiers. |
| I1 | Interview ownership risk. | Technical depth and ownership 78 (BENCH). "Code familiarity is the weakest ownership signal, given the sub-agent build." | Sub-agents wrote and verified the code. | Reserve time to read the core modules. Keep a decision ledger in first person. See `RUBRIC_PLAYBOOK.md` 4.2. |
| I2 | "Agent or pipeline?" is hard to answer well. | BENCH probe 2: honest answer is "deterministic core by choice". LLM changed 0 intent decisions: lexicon and model disagree on 0 of 550 texts. | Same root cause as G1. | Make the model decide something that matters, measure it with an ablation, and be able to quote it. |
| I3 | Model choice not justified by data. | Haiku intent matched Opus on every sample and eval row at about 40 percent of the cost ($0.3426 vs $0.8563 cold run), yet Opus stayed default (EVR section 3; DECISIONS D5). Panel: "questionable" (PANEL). | The owner preferred the stronger model on unmeasured rows. | Choose the cheaper model when the ablation shows a tie, or write one sentence of risk reasoning. |

---

## 2. Process lessons (time, cost, control)

### 2.1 Timeline (from LOG, UTC, 24-25 October)

| Time | Event |
|---|---|
| 14:12 | Session start. Problem explained. |
| 15:39 | Spec, plan, two review rounds, 33 task files written (docs only). Python 3.9.6 noted. |
| 16:19 to 16:39 | API facts checked (no sampling params, SDK needs 3.10). Scoring strategy and local evaluation strategy added. Task files grow to 35, then 46. |
| 17:08 | Implementation workflow starts (42 tasks). About 3 hours after session start. |
| 17:48 to 17:58 | Two stop-and-resume cycles to change models. |
| 18:54 | API key added by the user. Live check done. About 1h46 after implementation start. |
| 19:10 and 20:11 | Two workflows stopped and replaced to cut verification. |
| 22:15 | First alignment audit versus problem statement. |
| 23:21 | Targeted audit, judge panels, freeze workflow. |
| 23:44 and 23:52 | Past rubric extracted. Benchmark run. About 9.5 hours after start. |
| 00:54 to 00:59 | rc3 decisions. rc4 freeze with two waivers. |

Total: about 11 hours from session start to the rc4 freeze command. The edition-1 article describes a 24-hour event; the October length is not confirmed in the repo (`AGENTS.md` section 3).

### 2.2 Process gaps

| # | Process gap | Evidence | Why it hurt | Do next time |
|---|---|---|---|---|
| P1 | Heavy planning before code | `plan/` holds 3,653 lines in the planning files and task cards: spec, plan, two reviews, scoring strategy, local evaluation strategy and 46 tasks (`wc -l`). All of it existed before the implementation prompt (PLAN files last changed 16:39). About 3 hours passed before the first implementation workflow (LOG 14:12 to 17:08). Four review rounds are recorded in the review docs: two at 15:39 (the second found 38 issues), a score pass at 16:19 and a stress test at 16:39. | Hours spent on documents the judges never see (`plan/` is not in the zip: `SCORING_STRATEGY.md` section 2). | Cap planning at about 60 to 90 minutes. One spec page, one task list. Review once. |
| P2 | Tooling as large as the product | Solver `ghostaudit/` about 8.0k lines. Non-solver code: `code/evaluation` about 2.8k, `code/tools` about 0.9k, `devtools/` about 2.4k, or about 4.3k including tests (`wc -l`). | Release gate R1 to R12, clean-room matrix, confidence ledger, packager and log tools took build time and review time. R4 and R9 were waived in the end (MANIFEST). | Cap tooling at about 25 percent of solver size. See `EVALUATION_STRATEGY.md` section 8. |
| P3 | Workflow restarts | Run wf_173ce708 stopped at 25 of 42 tasks. Batch 2 (wf_4b3dc680) stopped after 4 of 14. Batch 3 (wf_dff0c4b0) used one Sonnet agent for the rest (LOG 19:10, 20:11). Two more stop-resume cycles at 17:48 and 17:58. | Each restart replayed or re-verified work. Tasks were logged 3 to 5 times (BENCH). | Fix the model plan and verify policy before launching. Do not change them mid-run. |
| P4 | Verification overhead and a speed trade-off | A strict Opus verifier ran per task (42 tasks). The user then asked for one combined verification for speed. The combined check rejected 6 of 15 tasks (BENCH, citing LOG 3660). | Per-task checks were expensive. Batching found problems late and forced rework in dependency order. | Cheap automated gates per task (tests plus contract). One LLM verifier per milestone, with a short failing-case list. |
| P5 | API key arrived late | Implementation began 17:08 with no key (LOG 17:08). Key validated 18:54. The live-API tasks T11b and T36 were left to a final step (LOG 19:10). | Workflows were split. The cache fill and live checks happened after most code existed. | Ask for the key in the first 15 minutes. Run one smoke call. Check which models and parameters the API accepts. |
| P6 | Toolchain mismatch | System `python3` was 3.9.6 and the SDK needs 3.10 or newer. Both were known in planning (LOG 15:39, 16:19; LES G1), and the plan chose a 3.9 stdlib core plus a separate `.venv-live` with Python 3.12 (DECISIONS D7; task T36). | Core had to stay stdlib and 3.9-safe. Extra markers, lazy imports and a split run mode. | Check Python and SDK versions at hour 0. Create the right venv before planning. |
| P7 | API rejected sampling parameters | `temperature`, `top_p`, `top_k` give HTTP 400 on the target models (`SCORING_STRATEGY.md` C1; DECISIONS D6). | Caught early in research, so it cost little. | Test one real call per model at hour 0. Keep a tested "API facts" note. |
| P8 | A close-out agent changed defaults without approval | LOG 00:37Z: the close-out step turned on the strict per-case signature fit (contradicting the user's earlier "keep" decision) and switched the default intent model to Haiku. At 00:54Z the user decided: keep the strict fit, revert the intent model to Opus. | The strict fit moved 20 rows (18 COMPLETE, no status change). The owner learned of both changes only when the main session read the workflow result. | Keep a decision register. Verify step diffs `config.py` defaults against the register and fails on any change. Agents may propose, not flip. |
| P9 | A banned model sat in the rework path | LOG 17:48Z: the user banned a rework model; a run was stopped to remove it. | Restart cost. | Put the allowed-model table in the workflow config before the first run. |
| P10 | Release tooling lived in the zipped tree first | It was moved to `devtools/` at 23:05Z (LOG: "Moved release tooling, tests and the audit sampler to devtools/"). | A judge reads everything in the zip; tooling that is not part of the solution is noise and a risk (`AGENTS.md` 6.9 asks for the runnable solution, prompts, config, README and reports). | Put non-judged tooling outside the zipped tree from day one. |
| P11 | Large sub-agent token spend | About 9.5 million sub-agent tokens in finished runs by 00:12Z (LOG). Runs launched later added more; no total was logged. The final model run used 196,870 tokens and about $0.86 over 31 calls (usage report). | Build spend was far above run spend: roughly 48 times in tokens, from the logged numbers. | Track sub-agent tokens per run in the log. Set a budget per milestone. |
| P12 | Decisions asked as multiple-choice | LOG 22:33Z, 22:34Z, 22:51Z. | Gave the transcript little direction (T2). | Decide first, then tell the agent. |

### 2.3 What the cost numbers say

- Runtime LLM cost was tiny: 31 calls, 196,870 tokens, $0.8563 sync price, $0.4282 at batch price, 380 tokens and $0.001653 per request (usage report).
- A rerun used the cache and cost $0 live tokens (0 calls, usage report section 3).
- The cost that mattered was build cost: at least about 9.5M sub-agent tokens in finished runs (LOG 00:12; later runs were not totalled) and about 11 hours of wall-clock time. Optimise the build, not the runtime.

---

## 3. What worked (repeat it)

| Practice | Evidence | Why it worked | Keep as |
|---|---|---|---|
| Analysis first | `solution/ANALYSIS.md` with prototypes reverse-engineered the data before any spec. Final output scored 32 of 32 status on samples (EVR section 2). | The spec rested on measured facts, not guesses. | Spend the first 2 to 3 hours on a data and problem analysis with runnable prototypes. |
| Evidence-first output | Every finding cites a file. 0 of 1,215 citations pointed to a file captured after the cutoff, before the request, or before the report (BENCH section 3). | Graders check citations and the time contract. | Every claim in the output carries a locator. |
| Contract validator | 0 violations on 518 rows (BENCH). | One cheap check catches format loss. | Write it in hour 1 (see `REQUIREMENTS.md`). |
| Per-item content-addressed cache | Rerun is byte-identical in about 0.5 s, 0 live calls, 0 cache misses (BENCH; DECISIONS D4; MANIFEST). | Cheap, reproducible, no key needed for review. | Cache every model call by content hash. See `ARCHITECTURE.md` section 7. |
| Label-free verification | An independent verifier re-reads files with its own parsers: 0 hard failures on the final run (EVR section 5). | Finds wrong citations without gold labels. | Keep a small independent verifier for the top-risk claims. |
| Ablations with rows-changed counts | Signature off: 85 rows. Late ids off: 124 rows. FIFO off: 28 rows. Window shift: 163 and 116 rows (EVR section 4). | Exposes how much each assumption matters, and gives interview numbers. | Keep a short ablation table. Cap flags. |
| Targeted audit with arbiters | 61 cases audited, 14 disputes, 12 confirmed defects, 2 root causes, 49 rows changed, 0 status changes (AUDIT). | High yield for low cost, and fixes were general rules. | Run once, after features are done. |
| Honest disclosure | `DECISIONS.md` has 25 records with alternatives and evidence. Interview honesty readiness 85 (BENCH). | Matches the 15 percent honesty dimension. | Write the weak points into the repo yourself. |
| Ceiling analysis early | `plan/LOCAL_EVALUATION_STRATEGY.md` section 0: about 81 structural misses and about 26 FIFO ties, so under a case-exact grader the maximum total is 94.5. | Stopped wasted effort on unreachable rows. | Compute the ceiling in hour 1 to 2. |
| API research up front | No sampling parameters, structured outputs, explicit effort, prompt-cache control (`SCORING_STRATEGY.md` C1, C2, C8). | Avoided 400 errors and wasted calls. | One "API facts" note, tested with real calls. |
| Model tiering for build | Sonnet for implementation, Haiku for 7 simple tasks, Opus for verify and rework (LOG 17:08). | Matches cost to task difficulty. | Keep the tiering. Fix it before launch. |
| Log tooling | An append-and-lint script kept all 183 entries valid, with a full Context block each (BENCH). | Half of edition-1 transcripts failed on format (NOTES section 5). | Use a script for every log entry from the start. |
| Determinism | Two runs under different `PYTHONHASHSEED` values were byte-identical (DECISIONS D1). | Graders and reviewers can reproduce. | Sort everything; fixed JSON serialization. |

---

## 4. Do differently next time (short list; owners are other files)

1. Hour 0: read all past rubrics and the problem statement; check Python, SDK, API key and API parameters. Owner: `CONSTITUTION.md` P1, P11.
2. Hour 1: write the rubric-to-build map and the FR/NFR list. Owner: `REQUIREMENTS.md`.
3. Hour 1 to 3: data analysis with prototypes, plus a ceiling estimate. Owner: this file section 3.
4. Choose an agentic core with deterministic veto. Owner: `ARCHITECTURE.md`.
5. User writes decisions, constraints and verification turns. Owner: `CONSTITUTION.md` P6.
6. Lean evaluation with early official-dimension judge runs. Owner: `EVALUATION_STRATEGY.md`.
7. Keep a decision register that agents cannot change. Owner: `CONSTITUTION.md` P6.
8. Reserve time before the deadline for the interview walk-through. Owner: `RULES.md` R82 (schedule) and `RUBRIC_PLAYBOOK.md` 4.2 (content).
