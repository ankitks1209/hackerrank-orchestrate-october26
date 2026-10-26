# TOKEN_COST_EFFICIENCY.md: spend tokens where they buy score

Part 1 is the product (the agent that runs on the dataset). Part 2 is development (the coding agent and its sub-agents).
Principles: `CONSTITUTION.md` P8, P11. Timeline: `DEVELOPMENT_STRATEGY.md`. Delegation: `SUBAGENT_DELEGATION.md`.
Prompts: `PROMPTING_STRATEGY.md`. Runtime architecture and cache design: `ARCHITECTURE.md` section 7.

Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

The problem statement requires a usage report (models, calls, input/output tokens, total and per-request tokens, estimated cost per model and overall).
Check the new problem statement for the same. Cost efficiency is also read as engineering judgement (PANEL "AI usage quality" deductions).

---

# PART 1. PRODUCT SIDE

## 1. Principles and a budget

1. **Set a budget before you build the agent.** Write three numbers in `DECISIONS.md`: max tokens per request, max dollars per full run, max live calls per request. Enforce them in code with the cap-and-budget table in `GUARDRAILS_AND_EDGE_CASES.md` section 1.1.
   Why: an agent loop makes several calls per case where a classifier makes one; how much more it costs is not measured in our data, so measure tokens per investigated case at phase 4 and set the cap from that. Judges asked for "a per-run cap on total LLM calls and spend, alongside the per-call retry cap" (BENCH section 2, judge 3).
2. **Use the model only where code cannot decide.** Code is free, exact and testable. The model handles ambiguity.
3. **Route by difficulty.** Cheap deterministic checks first, cheap model second, strong model last (section 5).
4. **Measure, then choose.** Every model and prompt choice has a measured comparison in the evaluation report.
5. **Keep the answer path short.** Ask for ids and enums, not essays (section 4).
6. **Never ship a mode you did not build.** The unwired `batch` mode in config was a deduction on all three code judges (BENCH).

Reference numbers from the last product (what "cheap" looked like):

| Measure | Value | Source |
|---|---|---|
| Model calls | 31 (398 distinct request texts in 16 batched calls, 15 media files, one call each) | BENCH section 5; USAGE |
| Tokens | 196,870 total (67,269 input, 6,670 cache write, 96,198 cache read, 26,733 output) | USAGE |
| Cost | $0.8563 sync, $0.4282 at batch prices | USAGE |
| Per request | 380 tokens, $0.001653 | USAGE |
| Wall time offline | about 0.9 s for all 518 requests | `code/docs/ARCHITECTURE.md` section 5 |

This was cheap because the model had two small jobs. An investigator loop on ambiguous cases will cost more. Plan for it; do not run it on every case (section 5).

---

## 2. Where tokens go: map your own pipeline first

Before optimizing, list every model call site in a table. Fill it from the usage meter.

| Call site | Calls | Input | Cache read | Output | $ | Needed? | Cheaper option |
|---|---|---|---|---|---|---|---|
| intent / triage | | | | | | | smaller model, lexicon first |
| media extraction (images, PDFs) | | | | | | | cache by file hash, one call per file |
| investigator loop | | | | | | | only on ambiguous cases |
| verifier / critic | | | | | | | only on disagreement |

Rule: **a call site with no measured accuracy effect gets removed or downgraded.** Evidence: the keyword lexicon and the strong model disagreed on 0 of 550 request texts, and the cheap model matched the strong one on every row (BENCH section 5; EVR strategy table).

---

## 3. The final run and the usage report

1. **Make the final full-dataset run a live (or cold-cache) run.** The usage report must describe the run that produced `output.csv`. Last time the final run replayed a stored cache: 0 live calls, 0 live tokens. The report had to explain "replayed vs live" with two tables (USAGE section 2). That is correct but confusing.
   Fix: do one clean cold-cache run at the end, record its meter, then ship the cache so judges can replay without a key. State both facts in one sentence.
2. **Generate the usage report from the meter.** A small renderer reads `meter.json` and writes the tables. A `--check` mode recomputes every total, average and cost from tokens and prices. Last time report drift was a judge finding (LOG 00:31Z).
3. **Report per model and overall**, including calls, input, cache write, cache read, output, total, cost, per-request tokens and cost.
4. **Prices live in config** with a comment on source and date. An unpriced model is reported as unpriced, never guessed. Cache writes are 1.25x input price. Cache reads use the published read price.
5. **Include dev-time spend separately and honestly** if you want to mention it (sub-agent tokens are not part of the product run). Do not mix them.
6. **Cache location and redaction** follow `ARCHITECTURE.md` section 7 (last time 843 cached files sat inside the package; BENCH section 2: "adds bulk").

---

## 4. Keep prompts and outputs small

Input side:

- **Send only what the decision needs.** Case facts and a handful of evidence snippets, not whole files. A tool returns ids plus the few fields asked for, with a row limit.
- **Truncate with a marker** (`...[+37 rows]`) and let the model ask for more.
- **Fixed prefix, variable suffix.** The stable block goes first so caching works (section 6).
- **Short examples.** 3 to 6 synthetic examples (`PROMPTING_STRATEGY.md` B5).
- **Dedupe inputs.** 550 request texts were 398 distinct texts. Classify each distinct text once and map back.
- **Pre-filter images and PDFs.** Run the vision call once per file, cache by file hash, and never re-send a file already transcribed. Last time a PNG estimate was about 2,880 tokens per image (LOG T10 verifier note), so image calls are the expensive ones per item.

Output side:

- **Enums and ids, not prose.** The product never asked the model to emit steps or statuses; code did. Result: 380 tokens per request.
- **Short `reason` with a character limit**, used for diagnostics only.
- **Fixed `max_tokens`** per call site. Output tokens include thinking (USAGE section 1), so set effort low for classification (section 8).
- **Ask the model for the delta.** For a verifier: `supported | unsupported | missing_evidence` per claim, not a rewrite of the answer.
- **Let code build the final rows.** The model returns structured facts; a deterministic emitter builds the output.

Agent-loop side:

- **Cap tool calls per case** and **cap rows per tool result**.
- **Do not repeat tool results** in the context; keep a compact working summary after each step if the loop is long.
- **Stop early:** if every candidate has a state, finish. Do not force the budget.

---

## 5. Choose the model by measured equality

Method:

This section owns the strategy table; the evaluation report copies it (`EVALUATION_STRATEGY.md` section 7.1).

1. Define the strategies: S0 no model, S1 strong model, S2 cheap model, and agent loop on vs off. Add S3 cascade (cheap first, strong on low confidence) if an agent loop exists.
2. Run all on the labelled samples (under the small-sample policy, `EVALUATION_STRATEGY.md` section 3.3) and on the custom cases, and count rows that differ on the unlabeled set.
3. Report accuracy and cold-run cost side by side.
4. **Default to the cheapest strategy that ties within noise on every set.** If you choose a more expensive default, write the measured reason and what would change your mind.

Last time (EVR strategy table):

| Strategy | Sample status | Eval rows differing from S1 | Tokens | Cold-run cost |
|---|---|---|---|---|
| S0 deterministic only | 31/32 | 12 | 0 | $0.0000 |
| S1 Opus intent + Opus media (default) | 32/32 | 0 | 196,870 | $0.8563 |
| S2 Haiku intent + Opus media | 32/32 | 0 | 197,991 | $0.3426 |

S2 gave the same answers as S1 on every sample and on every one of 518 rows at 40% of the cost. The owner kept S1 by choice. All three code personas deducted for it (PANEL "AI usage quality", 0.25-0.5 each). The decision record said the strong model was preferred "on rows that no measurement covers, such as a new language" (DECISIONS D5).

Rules:

- **SHOULD** use the cheap model as default when it ties, and add a **cascade**: if confidence is below a floor, or the cheap model abstains, rerun with the strong model. That covers the unmeasured-row worry at low cost.
- **MUST** give the media/vision step the stronger model if a wrong id costs more than the tokens saved (DECISIONS D5). Measure it the same way.
- **SHOULD** use a small model for triage routing, and a strong model for the investigator only on the cases triage marks ambiguous.
- **AVOID** a model for a decision that a rule gets right on all measured rows. Keep the rule as a fallback and a cross-check.
- Record the S0/S1/S2 table in the evaluation report and the decision in `DECISIONS.md` with "Decided by".
- Do not claim a "cost saving" that you did not run.

---

## 6. Caching: two different caches

**Prompt caching (provider side).**

- Stable prefix first: system prompt, rules, schema, tools, examples. Mark it with the provider's cache control.
- Make the stable prefix long enough to be cacheable (working target at least 512 tokens; check the real minimum for the model in the API docs during preflight).
- Verify with a real call: the second call must report cache-read tokens above zero.
- Cache writes cost more (1.25x input) and reads cost much less (Opus price in config: $0.20 per million vs $4 for input). Expect a win only when the same prefix is reused many times within the cache lifetime. Batch your calls close in time.
- Last run: 96,198 of 196,870 tokens (49%) were cache reads (USAGE).

**Response cache (your side).** Owned by `ARCHITECTURE.md` section 7 (per-item key, modes, atomic writes, redaction, hit rate). Its cost effect: a prompt edit re-calls only the changed entries, and a cached rerun costs 0 live tokens (USAGE section 3).

---

## 7. Batching and the Batches API

Two different things:

1. **Many items in one request** (for example 25 request texts per call). Saves per-call overhead and repeats of the stable prefix. Keep the per-item cache key (section 6) and order-independent verdicts. Last time: 398 distinct texts in 16 calls.
2. **The provider's batch API** (asynchronous, 50% cheaper; $0.4282 vs $0.8563 for the same tokens, USAGE). Good when: the job is large, not interactive, and cold. Bad when: you iterate often (each rerun costs polling and result matching), or the response cache already makes reruns free.

Rules:

- **Decide at preflight** and record it. Last time the decision was "considered, not built" because the per-item cache made reruns free (DECISIONS D13). That reasoning is fine for 31 calls; it is weak for 2,000+ calls.
- If you build it, make it a real mode with a test and a cost line in the report. If you do not, remove the name from config (BENCH: dead-mode deduction).
- Use the batch API for the one cold final run only if the run is large and you have time (it can take minutes to hours). Otherwise do the final run synchronously.
- Group items by prompt so the cached prefix is reused.

---

## 8. Effort, retries, caps and guards

1. **Set effort explicitly** per call site. Low for classification and extraction (used `low` last time); higher only for the investigator. Output tokens include thinking, so effort is a direct cost knob.
2. **Fixed `max_tokens`** per call site. Treat `max_tokens` stop reason as an error with a fallback.
3. **No sampling parameters** on models that reject them (current models do; DECISIONS D6; R19).
4. **Retries, timeouts, per-case and per-run caps:** the numbers and the on-breach behaviour are in `GUARDRAILS_AND_EDGE_CASES.md` section 1.1. Last build: 60 s timeout, SDK `max_retries=0` because the app handled retries; never retry a 400 or a refusal.
5. **Dry-run estimate:** before a live run, print the number of cache misses and the estimated cost, and ask for confirmation in interactive mode.
6. **Kill switch:** one flag (`--llm off`) must still produce a valid `output.csv`. That also covers the "no key" case for judges.
7. **Do not cache failures** as successes (`ARCHITECTURE.md` section 7).

---

# PART 2. DEVELOPMENT SIDE

## 9. Fewer, bigger agents and shared context files

Last time: about 9.5M tokens in finished sub-agent runs; one workflow had 140 agents; a 49-agent audit covered 61 cases; many tasks were implemented and verified more than once (LOG, BENCH). The wasted share is not measured. The patterns below are the main places it came from.

Rules:

1. **Group work into at most 15 cohesive tasks (R79)**, not 46. Fewer briefs, fewer verifiers, fewer log entries. A task should be 1-3 hours of agent work with one owner directory.
2. **Shared context lives in files.** `CONTRACT.md`, `DATA_FACTS.md`, `DECISIONS.md`, `AGENT_POLICY.md`, `TASKS.md`. Briefs link to them (section references). Never paste the problem statement or past reports into each brief.
3. **Generate facts once.** A script writes `DATA_FACTS.md` (schemas, counts, formats, enum values). Sub-agents read it instead of re-profiling the dataset. This also keeps them consistent.
4. **Tell agents what not to read.** Large files (`log.txt` at 350+ KB, old plans, notes folders) are off-limits unless named. Prevents silent token drain and context contamination.
5. **Write once, reference many.** A decision is written in `DECISIONS.md` once; briefs cite `D3`.
6. **Return short reports.** A brief caps the report at about 150 words and asks for numbers and file paths. Long free-form reports are re-read by the orchestrator and by later agents.
7. **Do not stop running workflows.** Stopped or partly run workflows have no final token totals (LOG `/usage` entry), and in-flight agents rerun on resume. Stop only at phase boundaries.
8. **Do not re-verify unchanged work.** Track a hash per task; skip the verifier if hash and tests are unchanged.
9. **Read-only snapshots for reviewers.** Build the unzipped candidate once and point every reviewer at it. Do not let each reviewer rebuild the zip or crawl the repo.
10. **Scripts before LLMs.** Linting, format checks, schema checks, numbers-vs-report checks, packaging checks: write scripts. They cost no tokens and run in seconds. Keep the set small (the three release checks of R81).

## 10. Avoid redundant reviewers

- Seven benchmark agents (3 code, 2 chat, 1 output, 1 interview) cost 778,155 tokens and 140 tool calls (BENCH). Each judge used 82k-178k tokens.
- The three code judges named the same gaps: no tool loop, dataset-fitted constants, a dead config mode (BENCH). Three runs gave one list.
- Rule: follow the panel policy in `EVALUATION_STRATEGY.md` section 6: single judges at M1 and M2, one calibrated full panel at M3, then re-run only the dimension that changed, with one judge.
- Keep personas different (rules, quality, newcomer) rather than three copies of the same prompt. Different views find different problems (PANEL rules vs newcomer deductions differed).
- A self-set score bar that you later waive wastes the panel. If the bar is not a gate you will enforce, do not set it.
- Use the cheaper model for transcript and README checks; use the strongest for code judging only.

## 11. Budget per phase (targets, not measured)

Set an overall development token budget at kickoff (ask the user: "what is the budget?"). Then allocate shares. These shares are a proposal; adjust at phase 2.

| Phase | Share | Notes |
|---|---|---|
| 0-1 Preflight, contract, data facts | 8% | Mostly Haiku/Sonnet analysts writing files |
| 2 Architecture | 2% | Orchestrator only |
| 3 Thin slice | 14% | Sonnet implementers, script gates |
| 4 Agent layer | 16% | Opus for loop and veto logic; Sonnet for tools |
| 5 Accuracy loop | 30% | Largest. Failure-driven; capped per failure group |
| 6 Reports and packaging | 8% | Mostly scripts; Haiku for doc sync |
| 7 Review | 8% | The M3 panel (M1 and M2 single judges come from phases 3 and 4) |
| 8-9 Freeze, interview prep | 4% | Quiz mode |
| Reserve | 10% | Surprises |

Rules:

- **Estimate before launching a workflow:** agents x average tokens per agent (use measured numbers from earlier workflows; for example about 100k per judge-sized review) and write it in `PROGRESS.md`.
- **Hard stop at 90% of a phase's share** unless the user approves more.
- Spend from the accuracy-loop share on failure groups in order of rows affected, with a 45-minute time box each.

## 12. Measure tokens per workflow

1. **Record at the end of each workflow:** agents, models, total tokens, wall time, outcome, files changed. Put it in the log index entry and in `PROGRESS.md`.
2. **Do not rely on the harness total alone.** Stopped runs have no final totals. Keep your own count by agent where the harness exposes it.
3. **Track tokens per accepted change.** A change that cost 400k tokens and moved one sample is a candidate for the "stop rule" (`DEVELOPMENT_STRATEGY.md` phase 5).
4. **Keep one line per workflow** in the final interview notes: what it bought. Honest answer to "what did the AI spend on your behalf".
5. **Show model mix.** Last time: 112 Opus, 57 Sonnet, 13 Haiku entries (BENCH section 4). Opus was the majority of entries. A target for the next build is Opus for orchestration, core verification and rework only (`SUBAGENT_DELEGATION.md` section 3).

## 13. Quick wins ranked by saving per effort

1. Cheap model as default where measured equal, with a confidence cascade (section 5): about 60% off the model line last time.
2. Per-item response cache with replay mode (section 6): reruns cost zero.
3. Stable-prefix prompt caching, verified (section 6).
4. Group 25 inputs per call and dedupe identical inputs (section 4).
5. Fewer, bigger dev tasks and no repeat verification of unchanged work (section 9).
6. Shared context files and `DATA_FACTS.md` instead of pasted context (section 9).
7. Scripts instead of LLM reviewers for format and consistency checks.
8. Judge panels per `EVALUATION_STRATEGY.md` section 6 (section 10).
9. Batch API for a large cold run only (section 7).
10. Caps on calls, dollars and wall time, with fallbacks (`GUARDRAILS_AND_EDGE_CASES.md` section 1.1).

## 14. Checklist

- [ ] Budget numbers written (tokens per request, dollars per run, calls per request) and enforced in code.
- [ ] Meter records calls, input, cache write, cache read, output per model.
- [ ] Strategy table S0/S1/S2 (and cascade, loop on/off) with accuracy and cost on the labelled samples and custom cases.
- [ ] Default model is the cheapest that ties, or the reason is measured and written.
- [ ] Prompt caching verified with a real call; response cache has per-item keys, atomic writes, redaction.
- [ ] Final run is cold-cache or live; usage report generated from the meter; `--check` passes.
- [ ] No dead modes in config. Batch decided and recorded.
- [ ] Per-case and per-run caps from `GUARDRAILS_AND_EDGE_CASES.md` section 1.1 exist with tests.
- [ ] Dev: shared context files exist; briefs link, not paste; reviewers use a snapshot; panels follow `EVALUATION_STRATEGY.md` section 6.
- [ ] `PROGRESS.md` has tokens per workflow.
