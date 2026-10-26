# ARCHITECTURE.md: Agentic architecture that scores

Owner of: the shape of the product agent, design patterns, repo layout.
Not here: what the agent must do (REQUIREMENTS.md), what it must never do and the caps (GUARDRAILS_AND_EDGE_CASES.md), the build process (DEVELOPMENT_STRATEGY.md), model tiers and budgets (SUBAGENT_DELEGATION.md, TOKEN_COST_EFFICIENCY.md), hard rules (RULES.md).
Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

## 0. Why this file exists

The Code Zip judge asks one question first: "Is this an agent, or a hardcoded workflow with LLM calls?" (30% of the code score). Only what is observable in source counts. README claims do not.

What happened last time (Ghost Data):
- We built a deterministic evidence pipeline. The LLM did two narrow jobs (intent, image/PDF transcription). It never chose a step, a status, or the next action.
- Three code judges put it in the "deterministic rule pipeline / no explicit agent" bucket. Agent architecture scored 25-30 out of 100. Prompt and tool craft ~70. Robustness ~80. Rigor ~90. Code total ~61-64.
- Edition 1 data: that bucket averaged rank ~933. "Single agent with tools or RAG" averaged ~592 and held 7 of the Top 10.
- Evidence: NOTES section 8; BENCH section 2 (code judges); DECISIONS D1, D2.

The lesson is not "drop determinism". Edition 1 says the best systems "combined those rules with LLM reasoning". The lesson is: put a real agent loop in the source, and keep the rules as the guardrail layer around it.

## 1. The target pattern (MUST)

**One investigator agent with typed tools, a bounded loop, and a deterministic validator that can veto it.**

```
request row
   |
   v
[1] Cheap deterministic triage        (parse, normalize, hard gates)
   |
   v
[2] Router (model-driven)             decides: fast path | investigate | abstain
   |
   +--> fast path: deterministic solver result
   |
   +--> investigate: Investigator agent  <---- tools (typed, read-only)
   |         loop: think -> tool call -> observation -> ... (max N turns)
   |         final: schema-validated Proposal
   |
   v
[3] Deterministic validator / guardrail (can reject or repair the Proposal)
   |
   v
[4] Fallback if rejected/failed: deterministic result or safe abstain
   |
   v
[5] Emitter (canonical serialization) + contract check -> output file
```

Rules:
- MUST have a tool-calling loop that actually runs in the shipped code path for at least the hard cases. A loop that is never reached scores nothing.
- MUST cap iterations (turns), tool calls per case, tokens per case, and total spend per run. The numbers are in GUARDRAILS_AND_EDGE_CASES.md section 1.1.
- MUST validate the final answer against a schema, then against domain rules the model cannot override.
- MUST keep a deterministic fallback so a model outage still gives a valid output file.
- SHOULD let the model do the part rules do badly: fuzzy linking, ambiguous text, conflicting evidence, free-form documents.
- SHOULD let rules do the part models do badly: time-window checks, ordering, canonical serialization, counting, allowlists.
- AVOID the model making the final safety decision. It proposes. The gate decides.

Why: the rubric looks for "tool-calling loops, model-driven routing, and multi-agent handoffs", and rewards "bounded tool calls, fixed output schemas, deterministic safety checks, citation validation, retries, fallbacks".

Evidence: NOTES sections 3 and 8; all three code judges' "improve" lists in BENCH section 2 ask for exactly this ("bounded tool-calling investigator ... keep the deterministic resolver as the guardrail and fallback ... could move Agent architecture from about 25 to about 60-70").

## 2. Make the agent behaviour observable in source

Judges grep the code. If it is not there, it does not exist. Checklist (each item is a thing a grep can find):

- [ ] A `tools/` module with one function per tool and a JSON-schema description for each (name, purpose, args, when to use, when NOT to use, failure result).
- [ ] An `agent/loop.py` with an explicit `for turn in range(MAX_TURNS)` and a stop condition.
- [ ] A `router.py` where a model call returns a typed route (`FAST | INVESTIGATE | ABSTAIN`) and the code branches on it.
- [ ] A `Proposal` schema (dataclass or pydantic) with an explicit `abstain` / `needs_review` option and a `reason`.
- [ ] A `validator.py` that rejects a Proposal and the code path that handles the rejection (retry once with the error text, then fall back).
- [ ] `prompts/` as files with a version in the name (`router.v1.md`). Role, constraints, output schema, refusal conditions in each.
- [ ] A per-run budget object (max calls, max tokens, max dollars) that the client checks before every call.
- [ ] A trace record per case: route taken, tools called, turns used, validator verdict, fallback used. Written to a diagnostics file.
- [ ] No dead config. Every flag in config is read somewhere. (Last time: an unused `batch` LLM mode cost points in all three judge reports.)

AVOID: comments or README sections that describe agent behaviour the code does not have. The interview penalises fabrication harder than a missing feature.

Evidence: judges' gaps "No tool definitions or tool descriptions exist at all", "no explicit abstain output", "no per-run cap on total LLM calls and spend", "dead path batch" (BENCH section 2).

## 3. Model-driven routing

Two kinds of routing exist. Only one counts as "model-driven".

| Kind | Example | Counts? |
|---|---|---|
| Confidence-gate routing | "if score < 0.6, use fallback" | No. It is plain control flow. |
| Model chooses the route | Router prompt returns `INVESTIGATE` because two candidates conflict | Yes. |

Pattern:
1. The deterministic pass computes features: number of candidate matches, conflicting evidence flag, missing-data flag, text language, parse confidence.
2. The router model sees the features and a short case summary (not raw files). It returns `{route, reason}`.
3. Code enforces hard overrides: a gate can force `ABSTAIN` or force `FAST`; the model cannot lift a hard gate.
4. Routing decision and reason go into the trace.

Token rule: route on summaries. Never send raw files to the router.

Cost rule: most rows should take the fast path. Target: investigator runs on a minority of rows (decide the number from sample data, then state it in the evaluation report).

## 4. Architecture options, and when multi-agent helps

Edition-1 leaderboard by architecture bucket (NOTES section 8; a lower rank is better):

| Bucket | Share of entries | Avg rank | Best rank | Top 10 | Top 50 |
|---|---|---|---|---|---|
| Single agent with tools or RAG | 53.0% | 592 | 1 | 7 | 27 |
| Graph or state-machine workflow | 1.9% | 351 | 2 | 1 | 5 |
| Explicit multi-stage or multi-agent pipeline | 10.9% | 468 | 3 | 2 | 16 |
| Single prompt or single model | 3.9% | 872 | 77 | 0 | 0 |
| ML models / trained classifiers | 0.8% | 877 | 46 | 0 | 1 |
| Deterministic rule pipeline / no explicit agent | 29.4% | 933 | 17 | 0 | 1 |

How to read it:
- Single agent with tools is the default: most Top-10 entries, and the pattern all three BENCH code judges (section 2) asked for. Section 1 is this pattern.
- A graph or state-machine workflow had the best average rank, but it is a small bucket (1.9% of entries), so that average is noisy. It is a valid option when the problem has clear states. Nodes are steps; the model chooses the transition at each node (for example "evidence sufficient -> verify" or "conflict -> investigate more"); code enforces the allowed transitions and the caps. It counts as agentic only if the model really picks transitions. A fixed graph with LLM calls at the nodes is still a pipeline.
- Multi-agent helped only "when the extra agents created a real separation of responsibility", with narrow jobs and tightly controlled handoffs (NOTES section 8).
- AVOID trained ML classifiers when labels are few. About 15 edition-1 submissions used them and they overfit "because there was too little labelled data" (NOTES section 8). Ghost Data had 32 labelled samples: the same situation.
- AVOID a pure rule pipeline: "safe and deterministic, but brittle". Keep the rules as the guardrail layer instead (section 0).

Use multiple agents only if ALL are true:
- [ ] Each agent has a different job, different tools, and a different output schema.
- [ ] The handoff is a typed object, not free text.
- [ ] One of them is a checker whose job is to find faults in another's output (critic / verifier), not to repeat the work.
- [ ] You can explain in one sentence why one agent with more tools would be worse.

Default recommendation for a new problem:
- Agent A: Investigator (tools, loop, proposes).
- Agent B: Verifier (reads the Proposal and the cited evidence only; returns `ACCEPT | REJECT(reason)`), run only on cases where the investigator was used or the route was uncertain.
- Everything else is plain code.

AVOID: a swarm of agents that all see all data. It multiplies tokens and makes the interview story harder to defend.

## 5. Retrieval patterns

Pick retrieval by data shape. State the reason in the README and be ready to defend it in the interview ("We used BM25 because the corpus was small and keyword-heavy, then added a reranker only after seeing misses on specific sample rows").

| Data shape | Pattern | Notes |
|---|---|---|
| Records keyed by ids, emails, hashes | Exact-key index (dict of normalized key -> records) | Normalize once (lowercase, strip, hash). One normalizer function used everywhere. |
| Small keyword-heavy text corpus | BM25 / TF-IDF (stdlib or `rank_bm25`) | Cheap, deterministic, explainable. |
| Large or paraphrased text | Embeddings + BM25 hybrid, rerank only if sample misses justify | Add only with measured gain. |
| Images / PDFs | Vision extraction once, cache result, then treat as text records | Extract facts, not verdicts. |
| Logs with many formats | One parser per format behind a common `Parser` protocol; pick by content sniffing | Join on stable ids (trace ids), not on line adjacency. |
| SQL snapshots | Load into in-memory SQLite and query | Compare replicas/tables explicitly. |

Retrieval rules:
- MUST apply the time filter (as-of cutoff) at retrieval time, not afterwards. See GUARDRAILS_AND_EDGE_CASES.md section 1.5.
- MUST return provenance with every hit (`file_id`, `line`, `captured_at`). Citations come from provenance, never from model memory.
- SHOULD cap results per tool call (e.g. top 10) and tell the model when results were truncated.
- SHOULD give the model summaries first and the full record on a second call (`get_record(id)`), to save tokens.

Evidence: judges noted "retrieval is purely lexical and identifier-based, no semantic retrieval for evidence whose identifiers fail to parse" (BENCH). The lexical/exact approach was right for the data, but a fallback search tool for unparsed evidence gives the agent something to do.

## 6. Design patterns to use (and keep simple)

| Pattern | Use it for | Rule |
|---|---|---|
| Pipeline | Fixed stages (load -> normalize -> solve -> validate -> emit) | Each stage is a function `State -> State`. Orchestration only in `pipeline.py`. |
| Strategy | Swappable behaviours: intent classifier (LLM vs lexicon), linker, retriever | One protocol, several implementations, chosen in one place. |
| Registry | Parsers, tools, policy rules | Decorator or dict registration. Adding a parser must not touch the core. |
| Adapter | Each evidence format -> one common `Observation` type | Parsers return the common type. Core never sees raw formats. |
| Pure core + IO shell | All decisions | Core is pure functions on typed data. IO only in `dataset`, `cache`, `emit`, `diagnostics`. |
| Dependency injection of the LLM client | Testability, offline replay | `run(config, reader, llm)`. Tests pass a fake client. |
| Content-addressed cache | Reproducibility, cost | Key = sha256 of canonical JSON (model, prompt version, messages, schema, attachment hashes). Atomic writes. |
| Typed errors | Failure handling | `LLMUnavailable`, `SchemaViolation`, `BudgetExceeded`, `ForbiddenInput`. No bare `except`. |
| Frozen dataclasses | Data between stages | Immutable. No global mutable state. |

AVOID: patterns for their own sake. If a pattern adds a file but no testability or swap point, drop it.

Simplicity budget (SHOULD):
- Function size: R40. Flag count: R38.
- 100% type hints on public functions.
- One concept per module. A module that imports from more than ~6 siblings needs splitting.
- Remove code that only tests keep alive. Delete flags nobody uses.
- Config holds runtime settings only. No task-tracker ids (T14, T26) in source.

Evidence: judges scored rigor ~90 for this style; deductions were `sys.path` hacks, dead `batch` mode, process scaffolding constants in `config.py` (BENCH). DECISIONS D13 and the "dead code kept alive by tests" item in EVR section 7 show the clean-up cost.

## 7. Content-addressed cache and offline replay

This is what makes an LLM-using system deterministic and cheap.

This section owns the response cache. Provider-side prompt caching is in `TOKEN_COST_EFFICIENCY.md` section 6.

- Modes: `off` (no model), `cache` (replay; miss = fallback), `live` (call API; store result). Default `cache`.
- Per-item key, so one verdict never depends on batch composition; a prompt edit changes the key of exactly the entries it affects.
- Atomic writes (temp file then rename). Cache only valid, schema-checked responses, never failures.
- Key includes: model id, prompt file version, system prompt, messages, max_tokens, effort, output schema, attachment hashes.
- Store only: response text, token usage, model name, stop reason. Never the request, never a key.
- Redact personal data at rest in stored responses (emails/phones as digests, names dropped), at write time. Last time ten of 843 cached responses held names and emails transcribed from images and PDFs (PANEL, rules persona); all 15 media entries were then redacted at rest (DECISIONS D25; MANIFEST).
- Meter two buckets: `live` and `replayed`. A cached final run makes zero live calls, so the usage report must show replayed usage or it looks empty (R16).
- Cache hit rate and miss count go into diagnostics. A final run with misses is a failed run.
- Do not ship the cache inside the source package if it is bulk (843 files was flagged as bulk). Ship it in a clearly named `data/` or `cache/` folder, redacted, and say so in the README.
- A tool-calling loop is harder to cache than single calls. Cache each model turn by (prompt, tool results so far). If the loop cannot replay exactly, cache the final Proposal per case with the full trace and key it on case input + prompt versions.

See REQUIREMENTS.md NFR table for the targets (cached rerun byte-identical, zero live calls).

## 8. Reference skeleton for a fresh repo

```
repo/
  README.md                 setup, run, offline replay, limits, honest scope
  AGENTS.md                 (given) logging contract
  requirements.txt          pinned; SDK lazy-imported
  .env.example              names only, no values
  .gitignore                .env, caches of PII, __pycache__
  code/                     the zipped solution
    main.py                 thin CLI: parse args, call run(), set exit code
    pyproject.toml          package + entry point (no sys.path edits)
    <pkg>/
      config.py             runtime settings only; the only reader of os.environ
      model.py              dataclasses, enums, operation table
      timeutil.py           one time parser, integer epoch
      keys.py               one normalizer for identifiers
      dataset.py            allowlisted reader (IO), typed loaders
      evidence/             one parser per format + index + provenance
      policy.py             rules as data, not as if-chains
      solver/               deterministic solver (fast path + fallback)
      agent/
        router.py           model-driven route
        loop.py             bounded tool-calling loop
        tools.py            typed read-only tools + JSON schemas
        verifier.py         optional critic
        proposal.py         Proposal schema
      guards/               validator, gates, time-cutoff, injection screens
      llm/
        client.py           protocol + live implementation (lazy SDK import)
        cache.py            content-addressed cache
        usage.py            meter + budget
        prompts/            router.v1.md, investigator.v1.md, verifier.v1.md ...
      emit.py               canonical ordering + serialization
      contract.py           output validator (exit code on violation)
      diagnostics.py        per-case trace report
    evaluation/
      main.py               scorer vs sample answers
      custom_cases/         3+ hand-made cases (decoy, late evidence, non-actionable)
      evaluation_report.md
      usage_report.md
    tests/                  unit + golden + determinism + static scans
  output.csv                final answer (root)
```

Layering rule (MUST): imports flow downward only. No module holds mutable global state. A static test enforces it.

Split rule (MUST): organizer-only or answer files are read only by `evaluation/` and `tests/`, never by the solver. A static test scans shipped code for those paths.

Release tooling (gate scripts, judge-panel runners, manifests) lives outside the zip (`devtools/`). Last time about 2.4k lines of release tooling (about 4.3k with tests) sat in the zipped tree and had to be moved out late (LOG 23:05; ARCH layer table note on `devtools/`).

## 9. Example (Ghost Data): the same problem as an investigator agent

Problem: for each deletion request, find every copy of a person's data across systems at `audit_at`, apply policy, output ordered steps.

What we built: deterministic linking + state + policy + emit, LLM for intent and image facts. What we should have built: keep that as the fast path and validator, add this agent for hard cases.

Tools (all read-only, all take the case's `audit_at` implicitly so late evidence cannot be returned):

| Tool | Args | Returns | Use when | Do NOT use when |
|---|---|---|---|---|
| `resolve_identity` | `email_or_hash_or_phone` | `user_id`, all current and historical identifiers, confidence | First call on every investigation | Identity already resolved in context |
| `search_evidence` | `query` (id, email, hash, phrase), `limit` | list of `{file_id, captured_at, snippet, resource_id, system_id}` admissible at `audit_at` | Looking for a copy of the user's data | You already have the record id; use `get_resource_state` |
| `get_resource_state` | `system_id`, `resource_id` | latest state at `audit_at` (`PRESENT/ABSENT/REDACTED/ANONYMIZED/DISABLED/BLOCKED`), with `evidence_id` | Confirming a candidate's state | The resource id is a guess |
| `list_activity` | `user_id` or `resource_id`, `window` | activity rows at or before `audit_at` | Looking for active sync/restore paths, or reading what a worker claimed | Treating a row's result as proof (it is a claim) |
| `read_evidence_file` | `file_id`, `range` | text of a bounded range | A snippet is ambiguous | The file is after `audit_at` (tool refuses) |
| `submit_proposal` | `Proposal` | validator verdict | Final answer | Before at least one `get_resource_state` call per cited record |

Loop contract:
- Caps from GUARDRAILS_AND_EDGE_CASES.md section 1.1: 8 turns, 20 tool calls, and a token cap per case set from sample measurements.
- The final `Proposal` lists records with state and `evidence_id` from tool results.
- Validator checks: every cited `evidence_id` was returned by a tool this case; its `captured_at <= audit_at`; operations and states come from the allowed table; step order obeys phase order; status matches the steps; retained records are not deleted.
- If rejected: one retry with the validator's error text. If rejected again: use the deterministic result and record `fallback=validator`.
- Deterministic solver result and agent Proposal are compared. A disagreement is logged and, for status, the more conservative rule in GUARDRAILS_AND_EDGE_CASES.md decides.

Router for this problem: send to the investigator when the solver reports a tie between candidate accounts, no proof file in the window, conflicting evidence, or an identity with a historical-only match. Everything else takes the fast path.

Honest scope (interview): say which cases the agent handled, what it changed vs the solver on the sample set, and what it cost. If it changed nothing on the samples, say so and explain why it still earns its place (robustness on unseen data).

## 10. Checklist: architecture ready to ship

- [ ] Loop, tools, router, verifier (if any) exist and run on at least one real sample case.
- [ ] Every tool has a description with "when to use" and "when not to".
- [ ] Caps exist for turns, tool calls, tokens, dollars (GUARDRAILS_AND_EDGE_CASES.md section 1.1).
- [ ] Validator can veto; fallback path tested.
- [ ] LLM client is injected; a fake client runs the whole suite offline.
- [ ] Cache replay gives byte-identical output.
- [ ] No dataset-fitted magic constants. Any learned constant has a source, a fit procedure, and a switch (see GUARDRAILS_AND_EDGE_CASES.md section 4).
- [ ] Layering and isolation tests pass.
- [ ] Trace file shows per-case route, tool calls, verdict.
