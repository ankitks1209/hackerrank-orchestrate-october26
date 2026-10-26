# SUBAGENT_DELEGATION.md: using sub-agents to build faster without losing control

This file owns how the DEVELOPMENT agents (the orchestrator and its sub-agents) are used.
The runtime agent inside the product is in `ARCHITECTURE.md`. Prompts for the product are in `PROMPTING_STRATEGY.md` part B.
Principles: `CONSTITUTION.md` P6 (user owns decisions), P11 (time). Budgets: `TOKEN_COST_EFFICIENCY.md` part 2.

Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

---

## 0. What happened last time

- Sub-agents wrote almost all the code. The user directed them with models, a verification rule and "do not assume anything" (LOG 17:08Z).
- Model policy: Sonnet 5.5 implements, a lighter model does simple tasks, Opus 5.5 orchestrates, verifies and does all rework. A different rework model was banned by the user (LOG 17:48Z). Later, Sonnet verified Haiku's work to save cost (LOG 17:56Z).
- The policy was changed twice while a workflow was running. Each change needed stop-and-resume. A running workflow does not reload its script, so the change only applied at the next resume (LOG 17:56Z entry). Result: the same task was implemented and verified 3 to 4 times in the log (T02b appears 5 times).
- The user then asked for one combined verification of the remaining tasks and, later, one Sonnet agent plus one Opus verifier (LOG 19:10Z, 20:11Z). The combined check rejected 6 of 15 tasks (BENCH section 4, LOG line 3660).
- Finished sub-agent runs used about 9.5M tokens (LOG `/usage` entry). One workflow had 140 agents (LOG index). A seven-agent benchmark cost 778,155 tokens (BENCH).
- A close-out agent changed two defaults without approval (intent model to Haiku, strict signature on). The orchestrator reported it. The user reverted one and kept one (LOG 00:37Z, 00:54Z). Nothing in the setup prevented it.
- 160 of 183 log entries were sub-agent entries. After many resumes they made the user's direction harder to see (BENCH section 4).
- The final score was lifted by quality of verification (898+ tests, byte-identical reruns) but sub-agent work does not show in the Code rubric: "only observable in source code counts" (NOTES section 3). The product itself had no agent loop.

Lesson: delegation is a speed tool. It needs a fixed policy before launch, clear file ownership, cheap checks first, and a rule that agents propose and the user decides.

---

## 1. Principles

1. **One orchestrator, narrow workers.** The orchestrator plans, briefs, integrates and verifies. Workers do one cohesive job each.
2. **Delegate work, not decisions.** Anything in section 10 goes back to the user.
3. **Check cheaply first.** Tests and scripts before an LLM verifier. An LLM verifier before a second LLM verifier.
4. **Few, bigger, well-briefed agents** beat many tiny ones (briefing and verification overhead is paid per agent). See `TOKEN_COST_EFFICIENCY.md` section 9.
5. **Disjoint write sets.** No two agents edit the same file at the same time.
6. **Everything an agent needs is in files.** The brief points to files; it does not paste them.
7. **Every agent is traceable.** One log entry per agent, plus one index entry per workflow (section 9).
8. **The product must contain the agent.** Dev-time sub-agents do not score on the code rubric. If you want agent credit, build the agent loop in the product (`ARCHITECTURE.md`).

---

## 2. Fix the policy before the first launch (`AGENT_POLICY.md`, 1 page)

Write it at H3 (phase 2 in `DEVELOPMENT_STRATEGY.md`) and have the user approve it. A workflow script reads from it. Do not edit it while a workflow is running unless you stop at a quiet point.

```text
MODELS
  orchestrator:        Opus-class (plans, briefs, integrates, verifies core logic)
  implementer:         Sonnet-class
  mechanical worker:   Haiku-class (see section 3)
  verifier:            per risk tier (section 5): script / Sonnet / Opus
  rework:              Opus-class only (name the banned models, if any)
VERIFICATION MODE:     risk-tiered (section 5)
REWORK:                max 2 rounds, then escalate to the user (section 6)
CONCURRENCY:           max <N> writing agents at once; read-only agents unlimited up to the token budget
BUDGET:                tokens per phase and per workflow (TOKEN_COST_EFFICIENCY.md section 11)
FORBIDDEN FOR AGENTS:  changing defaults, flags, thresholds, models, scope, dataset files, CONTRACT.md, DECISIONS.md decided-by-USER entries
LOGGING:               script only, labels, index entries (section 9)
STOP RULE:             do not stop a running workflow except at a phase boundary; stopped runs lose token totals
```

Why: policy edits during runs created stop/resume churn and duplicated work (LOG 17:48Z, 17:56Z, 17:58Z).
If the workflow engine can read a config file when each agent starts, keep model names and verify mode in that file, not in the script body. Check this in preflight. If it cannot, treat the policy as frozen after launch and apply changes between workflows.

---

## 3. Model tiering

Rule: pick the cheapest model whose miss would be caught before it matters. Cost of a miss times task difficulty decides.

| Role | Model class | Task types (examples) | Why |
|---|---|---|---|
| Orchestrator and final verifier | Opus | decomposing, writing briefs, integration decisions, verifying core-logic tasks (linking, state, policy, emitter), rework | Errors here move the score. It holds the whole picture. |
| Implementer | Sonnet | parsers, loaders, tools, tests, CLI, renderers, adapters, README sections from facts | Good code at moderate cost. Last time it did most of the work. |
| Mechanical worker | Haiku | renames, doc sync, formatting, fixture generation, run-and-summarize, log index entries, checking a list against files, simple parsers with tests | Fast and cheap. A miss is caught by tests. |
| Read-only analyst | Haiku or Sonnet | profile a file family, summarize formats, list traps | Parallel, no write risk. Output goes to a file. |
| Review judges | Opus | official-dimension code, transcript and output judges | Quality of the critique matters. Count and timing: `EVALUATION_STRATEGY.md` section 6. |

Rules:

- **MUST** write the tier next to every task in `TASKS.md`.
- **MUST** have Sonnet (not the same Haiku) verify Haiku's non-trivial work, or a script. Last time this saved Opus cost (LOG 17:56Z).
- **SHOULD** give the model that wrote a module the first rework attempt only if the verifier's failure list is specific. After that, go to Opus.
- **AVOID** Opus for boilerplate. **AVOID** Haiku for anything that sets a default, a rule, or a citation.
- **MUST** pass the model per call, never rely on the harness default. Record the exact model ID in each log entry (the repo logging contract needs it).
- Do not use a model the user banned. Put that into the policy file as a hard rule (LOG 17:48Z).
- Run the cheap-vs-strong comparison for the PRODUCT models too: see `TOKEN_COST_EFFICIENCY.md` section 5.

---

## 4. Briefing template

The brief is the main lever on quality and tokens. Keep it under about 60 lines. Link files; do not paste them.

```text
ROLE:        You are the implementer for <task id>: <one-line goal>. You do not make decisions listed under ESCALATE.
READ FIRST:  CONTRACT.md, DATA_FACTS.md (section <x>), DECISIONS.md D<a>-D<b>, <existing module paths>
WRITE:       <exact file paths you own>. Do not edit any other file. If you need a change elsewhere, say so in REPORT.
INTERFACES:  <function signatures / dataclass names from types.py you must satisfy; link to the file>
ACCEPTANCE:  commands that must pass, with expected output, for example
             pytest tests/test_<x>.py -q      -> all pass
             python3 -m code.check_<x> --dataset dataset/   -> 0 violations, <n> rows parsed
CONSTRAINTS: language/version, no third-party libs except <list>, no network, no print(), type hints, function size per R40,
             no constants without a source comment (problem statement / data command / DECISIONS id),
             deterministic ordering (sorted()), no reading organizer-only or gold files, secrets only from env
FORBIDDEN:   changing config defaults, model names, flags, thresholds; touching tests you did not write; weakening a check
ESCALATE:    if the data contradicts the contract, if a default must change, if you need a new dependency, if two designs are plausible
REPORT:      <= 150 words: files changed, commands run with results, open questions, anything surprising
LOG:         append one entry with the log script (label: "subagent impl:<task id>"); do not write log.txt by hand
```

Brief rules:

- **MUST** include acceptance commands. If you cannot write one, the task is too vague.
- **MUST** list the owned files. Missing ownership causes merge conflicts.
- **MUST** tell the agent what NOT to read (for example `log.txt`, `plan/`, `solution/` internals) to save tokens and to avoid contamination. Organizer-only or gold data must never be readable by workers.
- **SHOULD** tell the agent the running time budget (for example "30 minutes of work, stop and report if you exceed it").
- **SHOULD** ask the implementer to write the tests first for pure logic.
- **AVOID** pasting long context or previous agents' reports into the brief; point to the file.
- **AVOID** the phrase "implement per the plan" with no acceptance command.

Verifier brief (shorter):

```text
ROLE: independent verifier for <task id>. You did not write this code.
CHECK: run the acceptance commands; read the changed files; check the CONSTRAINTS list item by item;
       run the fast gate; check against the real data, not only fixtures.
DO NOT: fix code (except a one-line test typo); change files outside your log entry.
REPORT: PASS / FAIL, then a numbered failure list with file:line and the command output.
```

A verifier who also fixes things hides defects. Have the orchestrator route fixes.

---

## 5. Verification modes: trade-offs and the rule

| Mode | Cost | Speed | Risk | Last-time evidence |
|---|---|---|---|---|
| Per-task LLM verifier for every task | highest (roughly 2 agents per task) | slow | lowest late-defect risk | Used first; the log shows many re-verifications after resumes. |
| One combined LLM verification at the end | lowest | fast | defects found late; one big failure list; rework touches many modules | It rejected 6 of 15 tasks (BENCH section 4). |
| Script gates only | near zero | fastest | misses semantic errors | Tests and byte-identical reruns found most defects. |

Recommended rule: **risk-tiered, with milestone batches.**

1. **Every task: script gate.** The implementer runs the acceptance commands and the fast gate. The orchestrator re-runs them (no LLM).
2. **Low-risk tasks (loaders, formatters, renderers, tests):** no LLM verifier. Covered by the script gate and the milestone check.
3. **Milestone verifier (Sonnet or Opus) per group of 4 to 6 related tasks:** parsers as one group; identity plus index as one group; and so on. Group by dependency, so a defect cannot ripple unseen. The verifier checks the whole group against real data.
4. **Core-logic tasks (linking or resolution, state at the cutoff, policy mapping, emitter, validator, agent loop):** a per-task Opus verifier, because a miss changes the score.
5. **Combined verification is fine** when the tasks are independent, each has its own tests, and the combined verifier runs all acceptance commands. It is risky when tasks depend on each other. Do not defer verification of a task past the first task that imports it.
6. **Verify against real data.** Fixtures pass; data finds the surprises (for example 7 log formats). Every acceptance list has one data-level check.
7. **A verifier must be able to fail.** Seed one known defect in a calibration run and confirm it is caught. Last time the panel calibration caught both seeded defects (PANEL calibration, score 22).

---

## 6. Rework escalation

```text
Round 1  Same tier, same brief + verifier's numbered failure list only. Do not restart from scratch.
Round 2  Opus-class does the rework, reads only the failing files + the failure list.
Round 3  Stop. The orchestrator writes a 5-line summary for the user: what fails, options, cost, recommendation.
```

Rules:

- **MUST** cap rework at two rounds per task.
- **MUST** pass the failure list as numbered items with file:line and the command output.
- **MUST NOT** change the acceptance test to make a task pass. A changed acceptance needs the orchestrator and, if it affects the contract or a default, the user.
- **SHOULD** log each rework as a short entry that links to the task entry (not a full repeat).
- **AVOID** a stronger model for a weak brief. First check if the brief or the contract was unclear.

---

## 7. Review panels

The judge-panel policy (single judges at M1 and M2, a full calibrated panel at M3, read-only snapshot, no self-set score bar) is owned by `EVALUATION_STRATEGY.md` section 6. The orchestrator's part:

- Build the read-only snapshot once and point every judge at it (`TOKEN_COST_EFFICIENCY.md` section 9).
- Merge the judges' output into one list of deductions ranked by size, with effort for each.
- Give the list to the user. The user chooses what to fix. Re-run only the judge for the dimension that changed.

---

## 8. Parallelism and file ownership

1. **Write set per task.** In `TASKS.md`, list the files each task owns. Two tasks may run at once only if their write sets and their imports do not overlap.
2. **Spine first.** Build in order: types and config (orchestrator) -> readers and parsers (parallel) -> index -> linker or resolver -> case builder -> agent loop -> pipeline. Parallelize inside one layer, not across layers.
3. **Shared files have one owner.** `config`, `types`, `pipeline`, `README`, `DECISIONS.md` belong to the orchestrator. Workers request changes in their report.
4. **Pre-create the skeleton.** Empty modules with signatures and docstrings (dataclasses and Protocols) let parallel workers import without waiting.
5. **Read-only analysis in parallel** is free of conflict: data profiling, format studies, trap hunting. Their output is a file in `notes/`.
6. **Pipeline early.** Last time `main.py` was a stub for hours. Assign "thin end-to-end" before parsers are complete, using fakes (`DEVELOPMENT_STRATEGY.md` phase 3).
7. **Merge conflicts are a smell.** If two agents touched the same file, fix ownership, do not merge by hand again.
8. **Concurrency cap** from the policy file. Many parallel writers raise the verification load and the chance of broken builds. Pick a small number (for example 3 to 4) and raise it only if the fast gate stays green. This number is a suggestion, not a measured value.
9. **Append-only shared files** (the log, an index) are written only through the script. Use the script's append mode, never open the file for rewrite.

---

## 9. Logging and traceability

The log rules are owned by `RULES.md` group G (R55 to R61). What they mean for delegation:

1. Every sub-agent appends its entry through the log script, with `parent_agent=` set and the exact model id (R56, R58).
2. The orchestrator writes one index entry per workflow when it ends, and a main-session entry for the user turn that launched it (R58).
3. After a surprise (a worker changed a default or ignored a rule), the orchestrator writes one entry saying what happened and what the user decided (R59).
4. Sub-agents do not read `log.txt` (350+ KB at the end); give them their own task file (section 4).

---

## 10. Guard against agents changing decisions

What happened: a close-out agent set the strict signature fit on by default (20 more rows changed, contradicting the user's earlier "keep" decision) and switched the default intent model to Haiku. It was reported by the orchestrator and reverted by the user (LOG 00:37Z, 00:54Z).

Controls (use all):

1. **Pinned-defaults test.** A test lists every default model, flag, threshold and cap with the `DECISIONS.md` id that approved it. A change without a matching decision entry fails the test.
2. **Brief clause.** Every brief has FORBIDDEN and ESCALATE sections (section 4). The close-out brief says: "Apply only the changes in the approved list. Anything else becomes a proposal in `PROPOSALS.md`."
3. **Diff review.** The orchestrator reads the diff of `config` and prompt files after every workflow, before reporting success. A script prints only changes to config, prompts and DECISIONS.
4. **Approved-change list.** The user's approved fixes are written as a numbered list in the prompt; close-out agents apply those and nothing else.
5. **Report everything.** The orchestrator summary lists "changes not requested" explicitly. Empty list is a valid report.
6. **No final tidy-up agents with broad scope.** Close-out is a checklist with named files.
7. **Contract-related choices** (time rule, which evidence is allowed) are never delegated. See `DEVELOPMENT_STRATEGY.md` section 4 rule 5.

---

## 11. Anti-patterns seen last time (and the fix)

| Anti-pattern | Fix |
|---|---|
| Stop-and-resume to change models or verify mode | Policy file read per agent; no changes mid-workflow (section 2; R74) |
| Same task logged and re-verified 3-5 times after resumes | Idempotent steps; resume logs one line; verify only changed tasks (R61) |
| One huge combined verification at the end | Risk-tiered milestones (section 5) |
| 46 task files, each with its own agent and verifier | At most 15 cohesive tasks in one checklist (R79) |
| Repeated code-judge runs across release candidates | The panel policy in `EVALUATION_STRATEGY.md` section 6 |
| Release tooling built by agents (about 2.4k lines, 4.3k with tests) | The three checks of R81 |
| `main.py` empty while modules were verified | Thin slice first (section 8, item 6) |
| Workers reading big shared logs and plans | "Read first" lists, `DATA_FACTS.md` (section 4) |
| A tidy-up agent with write access to defaults | Section 10 |
| Status questions to the user | `PROGRESS.md` updated by the orchestrator after every workflow (R60) |

---

## 12. Orchestrator routine (copy into the first prompt to the orchestrator)

1. Read `CONTRACT.md`, `AGENT_POLICY.md`, `TASKS.md`, `DECISIONS.md`.
2. Pick the next batch of tasks with disjoint write sets and satisfied dependencies.
3. Write the briefs (section 4). Launch.
4. While running: do not poll. Update `PROGRESS.md` when it ends.
5. On finish: run the script gates yourself. Run the milestone verifier if due.
6. On failure: rework ladder (section 6).
7. Read the diff of config, prompts and DECISIONS. Report "changes not requested".
8. Append the index entry. Update `PROGRESS.md` with sample score, output hash, tokens used by the workflow.
9. Ask the user the batched questions at phase boundaries only (`DEVELOPMENT_STRATEGY.md` section 7).
