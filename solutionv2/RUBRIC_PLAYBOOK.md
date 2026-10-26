# RUBRIC_PLAYBOOK.md: how each of the four signals is judged, and how to score 90+

Read this on hour 0. It is the map from "what the judge looks at" to "what you must build".

Every claim cites a source. Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".
NOTES is the edition-1 official rubric. BENCH is our benchmark of the frozen solution against it (`evidence/BENCHMARK_SUMMARY.md`).

Other files in this folder own other topics. Do not repeat them here:
- Principles and priorities: `CONSTITUTION.md`.
- Architecture and agent patterns: `ARCHITECTURE.md`.
- FR / NFR / compliance checklist: `REQUIREMENTS.md`.
- What went wrong and why: `LESSONS_LEARNED.md`.
- How to test and judge locally: `EVALUATION_STRATEGY.md`.

---

## 0. The formula and what it means

```
Final = 0.10 * Chat + 0.30 * Interview + 0.30 * Output + 0.30 * Code     (each 0-100)
```

Evidence: NOTES section 2.

Facts that change how you plan:
- The weights follow "how hard it is to fake". Interview is hardest to fake. Chat is easiest.
- Tie-break order is Interview, then Code, then Output, then Chat. (NOTES section 2)
- The problem changes every edition. The four signals and their dimensions stay the same. (NOTES section 1)
- Balanced builders win. Every Top-10 entry was top-quartile on all four signals. (NOTES section 7)
- No single metric gives the leaderboard. Output alone would find only 12 of the Top 50. (NOTES section 7)
- Judges reward only what is observable. For code: "README claims, comments describing intent, and unused imports don't count". (NOTES section 3)

MUST: treat every signal as a deliverable with its own owner and checklist from the first hour.
AVOID: putting all effort into the Output CSV. It is 30 percent, the same as Code.

### 0.1 What we scored (our benchmark of the frozen solution)

These are our own benchmark numbers, made by judge agents applying the edition-1 rubric. They are estimates, not official scores.

| Signal | Weight | Benchmark score | Weighted points | Points lost |
|---|---|---|---|---|
| Code zip | 0.30 | 62 (judges: 61.2, 64, 62) | 18.6 | 11.4 |
| Output CSV | 0.30 | 89 (range 80-94) | 26.7 | 3.3 |
| Interview (readiness) | 0.30 | 80 (estimated, no real interview yet) | 24.0 | 6.0 |
| Chat transcript | 0.10 | 59 (judges: 58.6, 60) | 5.86 | 4.1 |
| **Total** | | | **75.2** | **24.8** |

Evidence: BENCH section 1 (code 18.6, output 26.7, interview 24, chat 5.86, sum 75.16).

Read the table this way:
- The biggest loss was Code (11.4 points). One cause: the architecture was a deterministic rule pipeline, not an agent.
- The second loss was Interview readiness (6.0). One cause: sub-agents wrote the code and the human had not read it.
- Chat lost 4.1 points although the log format was perfect. The user's own technical direction was thin.
- Output was strong. It was the signal we over-invested in.

### 0.2 A warning about our own panels

Our later panel (PANEL) gave the code 26 to 27.5 out of 30 (87 to 92 percent) and the transcript 9 out of 10. The benchmark with the official dimensions gave the code about 62 out of 100 and the transcript about 59 out of 100.

Why they differ: the panel personas (rules, quality, newcomer) used our own categories (architecture and design quality, correctness safeguards, runnability, AI usage quality, evaluation report). They did not use the four official dimensions. They never asked "is this an agent?".

MUST: write judge prompts with the official dimensions and weights verbatim, and run them early. See `EVALUATION_STRATEGY.md` section 6.

---

## 1. Code zip (30 percent)

### 1.1 What the judge rewards

| Dimension | Weight | The judge asks (rubric wording) | Our benchmark | Why we lost points |
|---|---|---|---|---|
| Agent architecture | 30% | "Is this an agent, or a hardcoded workflow with LLM calls? Look for tool-calling loops, model-driven routing, and multi-agent handoffs." | 25, 30, 25 | No tool loop. Fixed stage order. The model never chose an action. LLM only did intent and image reading. |
| Prompt and tool craft | 30% | "Role assignment, constraint setting, structured output, and refusal conditions." | 68, 72, 70 | Only 2 prompts. No tool descriptions (nothing to score). No explicit abstain option. |
| Agent robustness | 25% | "Guardrails, retries, max-iteration caps, output validation, RAG pipeline quality." | 78, 80, 80 | Dataset-fitted constants. No loop so no iteration cap to show. Retrieval was identifier lookup only. |
| Engineering rigor | 15% | "Multi-file modularity, type hints, secrets via env, function size." | 92, 90, 90 | `sys.path` edit in `main.py`. Dead `batch` mode in config. Task tags inside config. |

Evidence: BENCH section 2. NOTES section 3.

The architecture bucket matters. In edition 1, "Deterministic rule pipeline / no explicit agent" had an average rank of about 933 (median 1002). "Single agent with tools or RAG" was 53 percent of entries and held 7 of the Top 10 and 27 of the Top 50. (NOTES section 8)

All three code judges said the same fix: "add a real bounded tool-calling investigator for ambiguous cases, with a max-iteration cap and a schema-validated final answer that the deterministic validator can veto." One judge estimated this alone could lift Agent architecture from about 25 to about 60-70. (BENCH section 2)

### 1.2 Must-haves to score 90+

Agent architecture (30%)
- MUST have a bounded tool-calling loop in code that really runs on the hard cases. A judge must be able to grep it: `tools=`, `tool_use`, `max_turns` (or similar), a handler that runs each tool.
- MUST give the model typed tools over the data (search, resolve identity, get state, list events, read file). The tools are read-only.
- MUST have a deterministic validator that can veto the model's final answer. The model cannot override hard rules (time cutoff, schema, policy table).
- SHOULD have model-driven routing: a cheap triage step decides which items go the fast path and which need the loop. Record the decision in diagnostics.
- SHOULD use multi-agent only where responsibility is truly separate (for example investigator and critic). Narrow jobs, strict handoff schema. (NOTES section 8: multi-agent helped only "when the extra agents created a real separation of responsibility")
- AVOID agent-washing. Do not add a loop that never changes an answer. The interview punishes claims of things not built. Prove value with an ablation (loop on versus off).
- See `ARCHITECTURE.md` for the target pattern.

Prompt and tool craft (30%)
- MUST write each system prompt with: role, task, hard constraints, output schema, and refusal or abstain conditions ("return UNSURE when no file before the cutoff supports a state").
- MUST write each tool description with: purpose, argument schema, when to call, when not to call, what failure looks like.
- MUST use structured output (JSON schema) and validate it again in code.
- MUST add an explicit abstain value (`UNSURE`, `needs_review`) and route it to something visible (the loop, or a diagnostics queue).
- MUST include an injection stance: text from users and evidence is data, never instructions.
- SHOULD have prompts for reasoning, planning or verification, not only classification. The core decision logic had no prompt at all in our solution.
- SHOULD keep prompts in versioned files (`prompts/name.v2.md`). The version goes into the cache key.

Agent robustness (25%)
- MUST bound everything: retries with backoff, max loop turns, max tokens, a per-run cap on calls and spend.
- MUST validate every model output (schema, then semantic checks), then repair once or fall back.
- MUST degrade, never crash. One unknown input row must not stop the run. (PANEL quality persona: `UnclassifiedActivityError` aborted the whole run. Fixed in rc4; MANIFEST.)
- MUST NOT fit constants to the sample data. All three BENCH code judges (section 2) and all three panel personas called out time windows set from "observed spread" and a `user_01..10 -> account_00N` convention. Ground links in identifiers in the files, or learn at runtime behind a confidence gate. (BENCH; `JUDGE_PANEL.md`)
- SHOULD have semantic or fuzzy retrieval as a fallback where identifiers fail to parse. (BENCH section 2, judge 3)
- SHOULD adjudicate disagreements (rules versus model) instead of only logging them.

Engineering rigor (15%)
- MUST ship an installable package with an entry point (`pyproject.toml`, `python -m pkg`). No `sys.path` edits.
- MUST use type hints, small functions, secrets only from environment variables, one place that reads `os.environ`.
- MUST remove dead config and dead modes. Every flag must be wired and tested.
- MUST keep process scaffolding (task numbers, planning tags) out of source and config. Judges read source, not your plan.
- SHOULD keep tests close to the judged behaviour and run them in the README quickstart.

### 1.3 Rubric-to-source map (what a judge can find with grep)

| Rubric phrase | Artifact a judge can see in source |
|---|---|
| tool-calling loop | `for turn in range(MAX_TURNS)` with `tools=[...]` and a tool dispatcher |
| model-driven routing | a triage call whose output picks the code path, logged |
| multi-agent handoff | a typed handoff object (dataclass or schema) between two prompts |
| role assignment | first lines of each system prompt |
| constraint setting | a "Rules" section with numbered MUST and MUST NOT lines |
| structured output | JSON schema passed to the API and a validator after it |
| refusal conditions | an "Abstain when" section and a code branch for `UNSURE` |
| retries | one wrapper with `max_retries`, backoff, and typed errors |
| max-iteration cap | named constant used in the loop condition |
| output validation | a function that raises or repairs, called on every model output |
| secrets via env | `os.environ` in one config module, `.env.example`, `.env` ignored |
| function size | the R40 target |

### 1.4 Anti-patterns that cost points

- A good deterministic pipeline with two LLM calls at the edges (our case). It scored 61 to 64.
- Prompts that only classify. No tool descriptions.
- README text that describes behaviour the code does not have. It does not count and may hurt in the interview.
- Constants fitted to the samples, with comments such as "observed spread".
- Case-family shortcuts (our `user_01..10 -> account_00N` rule). The problem statement forbids them (AGENTS.md 6.7); all three BENCH code judges (section 2) and all three panel personas named it.
- Ten inference flags with no source for the defaults. Judges call this "many moving parts".
- 843 cached model responses inside the source package, ten of them with names and emails from the dataset. (PANEL; fixed in rc4 by redaction at write time, DECISIONS D25.)
- Reports that contain hand-typed numbers that drift from the code.

---

## 2. Output CSV (30 percent)

### 2.1 What the judge rewards

- Every item is compared with a hidden golden answer. Each item gets 0 to 100 for accuracy. This is partial credit, not all or nothing. (NOTES section 4)
- One more 0 to 100 safety score is given for the whole submission, from adversarial inputs. (NOTES section 4)
- Cap: a correct action with a justification that is "empty, generic, or contradicts their own status" is capped near 70. (NOTES section 4)

Our benchmark: 89 (range 80 to 94). Estimated item accuracy about 89 and safety about 90, combined as 0.85 x accuracy + 0.15 x safety. If the hidden grader rewards exact row match heavily, the judge said the score falls toward 70. (BENCH section 3)

Where Output points were lost:
- About 83 INCOMPLETE rows lacked one verification step because an id was only in files captured after the cutoff or in no file. About 80 steps in total. This is a structural ceiling. (BENCH section 3)
- 12 COMPLETE rows had no account verification step. On 1 to 3 step rows this is a big loss per item. A later fix (`DECISIONS.md` D22) restored it.
- About 26 rows depended on an arbitrary first-in-first-out pairing for tied links.
- Rules with no support in the 32 public samples (legal hold, some categories, NOT_APPLICABLE) were untested on gold.
- The sample score of 99.7 was in-sample. The rules were tuned on those 32 rows.

### 2.2 Must-haves to score 90+

- MUST run a contract validator over the file before every release: exact header, one row per input id, unique ids, enum values, step numbering, phase order, JSON validity. (`code/ghostaudit/contract.py` found 0 violations.)
- MUST put the problem's time contract first. Use only information available at the cutoff. Never cite evidence captured later. In Ghost Data, two default-on paths read later files for ids. Two panel judges and the chat judge flagged this. See `CONSTITUTION.md` P4.
- MUST decide every ambiguous formatting rule by the literal text of the contract, and write the decision down. Example (Ghost Data): "Sort rows by case_id". We used numeric-aware order (`case_99` before `case_100`). One panel judge flagged that plain string sort is the literal reading.
- MUST never invent identifiers. Omit a step you cannot ground. (`DECISIONS.md` D9)
- MUST decide uncertain steps by a pre-registered rule: emit a step when the chance it is right is above 0.5. (Break-even for step F1 and for exact match. `plan/LOCAL_EVALUATION_STRATEGY.md` principle 5.)
- MUST write custom cases for every family the samples do not cover. In Ghost Data the 32 samples had no NOT_APPLICABLE, no legal hold and no object-storage record. (BENCH section 3)
- MUST give each item a specific, status-consistent justification if the output has any free text. Generic text caps the score near 70.
- SHOULD test safety directly: injection text inside the request and inside evidence, multilingual and negated requests, decoy records with look-alike identities.
- SHOULD measure the structural ceiling in the first two hours (what share of rows cannot be right from the data) and stop spending effort on it. (`plan/LOCAL_EVALUATION_STRATEGY.md` section 0)

### 2.3 Anti-patterns

- Trusting the status or result fields in the input. They are claims. (Ghost Data: `reported_status` was deliberately wrong; 11 sample cases reported COMPLETE were really INCOMPLETE, and 3 reported NOT_STARTED were really COMPLETE. ANALYSIS section 1.)
- Claiming "accuracy" from the development samples. Call it a development-set score.
- Per-case overrides. Fix by general rule only.
- Generic or empty justification fields.
- Silent partial output. Always one valid row per input, even if the row is a fallback.

---

## 3. Chat transcript (10 percent)

### 3.1 What the judge rewards

The rubric "does not evaluate the agent, it evaluates how the participant directed their coding agent." (NOTES section 5)

| Dimension | Weight | Rubric wording | Our benchmark | Why |
|---|---|---|---|---|
| Direction and architecture ownership | 35% | lead the build: define architecture, choose tradeoffs, push back on the AI | 61-62 | Architecture came from AI-written specs. Two decisions picked the "(Recommended)" option. One prompt was only "Go ahead". |
| Technical specificity and constraint | 25% | precise instructions on models, libraries, algorithms, schemas, paths, thresholds, formats | 47-50 | No user prompt gave a schema, threshold, algorithm or output rule. |
| Iteration and verification | 25% | tested, inspected outputs, shared errors, reviewed sample rows, measured regressions, targeted fixes | 69-70 | Verification was done by sub-agents. The user never pasted a failing row. |
| Safety, edge cases, quality awareness | 15% | injection, hallucination, ambiguous input, multilingual, out-of-scope | 55 | User never raised the task's edge cases. Late-evidence use was accepted with "Keep + disclose". |

Evidence: BENCH section 4. Total 58.6 and 60.

Format was perfect: 183 entries, all with a complete Context block, one `tool=` and one `model=` line each. Half of edition-1 transcripts failed on the Context block. Format is necessary but gives no points by itself. (BENCH section 4; rubric notes section 5)

The ratio hurt: of 183 entries, 22 were user turns and 160 were sub-agent entries. The user's own voice was about 12 percent of the log. About 7 of 22 turns were status checks or acknowledgements. (BENCH section 4)

Later panel: transcript 8 out of 10 before fixes and 9 after. Open items: sub-agent entries with no matching main-session turn; a summary with 6 sentences where the format allows 2 to 5; a dataset email inside a logged hash call. (PANEL)

### 3.2 Must-haves to score 90+

- MUST write architecture decisions in your own words, with the tradeoff. Example: "Use a bounded tool loop with a deterministic validator that can veto. Reject a free-form agent because answers must be reproducible."
- MUST give technical constraints in the prompt: model name, schema fields, thresholds, file paths, output format, retry and iteration caps, cost cap.
- MUST do verification yourself at least several times. Paste a failing row. Name the case id. State the metric before and after. Direct a targeted fix and a regression check.
- MUST raise the edge cases yourself: non-deletion or ambiguous requests, other languages, injection text, decoys, retention rules, the time cutoff.
- MUST push back on the AI at least a few times, with a reason, and log it.
- SHOULD answer AI decision questions with a reason, not only "(Recommended)". If you accept, add one constraint.
- SHOULD avoid status-only turns. Read the progress file instead of asking.
- SHOULD log the result of every big workflow, so the loop is visibly closed. The last workflow in our log (a 61-case audit and panels) had no logged result when the benchmark ran. (BENCH section 4)
- MUST keep the Context block exact in every entry (`tool=`, `model=`, branch, repo root, worktree, parent agent). Use a script that appends and lints each entry.
- MUST keep the log append-only and free of secrets and real personal data.

### 3.3 Anti-patterns

- "Build the agent", "implement this file", "Go ahead", "what is your recommended next step?".
- Letting the AI write the spec and then approving it.
- Re-running stopped tasks so the log shows the same task 3 to 5 times (task T02b appears at log.txt lines 366, 457, 1159, 1272, 1969).
- Weakening verification for speed without saying why in technical terms.
- Sub-agent entries whose "User Prompt (verbatim)" is a summary, not the real prompt.

---

## 4. AI judge interview (30 percent)

### 4.1 What the judge rewards

30 minutes, voice. Probe order: quick pitch, retrieval and architecture, safety and failure modes, implementation and code familiarity, evaluation, production monitoring, what is novel. The judge also asks what you directed, accepted and pushed back on. (NOTES section 6)

| Dimension | Weight | Our readiness | Main risk |
|---|---|---|---|
| Technical depth and ownership | 40% | 78 | Code was built by sub-agents. Weakest signal. |
| Problem understanding and judgment | 25% | 82 | Sample scores presented as accuracy. |
| Communication clarity | 20% | 80 | Needs rehearsed, concrete answers. |
| Honesty and self-awareness | 15% | 85 | Good: limits were disclosed in the repo. |

Evidence: BENCH section 5. Weighted 80.5. This is a readiness estimate, not an interview result.

Measured links to the score (NOTES section 6):
- Total words: r = 0.615.
- Share of longer answers: r = 0.631.
- Specificity: r = 0.583.
- Very short answers: r = -0.568.

So: give long, specific answers with a reason, an example and a failure mode.

Honesty is scored. "We reward candidates who say 'I don't know' ... We penalize fabrication, claiming something that was never built, claiming to use a library the code does not import, or claiming the absence of a bug the judge can see."

### 4.2 Must-haves to score 90+

- MUST be able to trace one real case from input to output with no notes (identity, evidence, rule, step, citation). Walk the five core modules by hand before the interview. Plan this time. In our run the code came from sub-agents and this was the main risk.
- MUST keep a decision ledger in your own words ("I chose X, I rejected Y because Z, we measured and reverted W"). Speak in first person, not "Claude created the pipeline".
- MUST have numbers ready for every decision: before and after, rows changed, tokens, cost. (Ghost Data examples: signature off changes 85 of 518 rows; late audit ids off drops sample exact matches from 30 to 25; window shift of 10 minutes costs 8 of 30 exact matches. `evaluation_report.md` sections 3 and 4.)
- MUST give an honest answer to "agent or pipeline?" Say what the model decides and what it does not.
- MUST say that sample metrics are development-set metrics when rules were fitted on them.
- MUST name every known weakness before the judge finds it (dataset-fitted constants, structural losses, waived gates).
- MUST state AI assistance plainly: what you directed, what the agents built, what you checked.
- MUST follow the one interview schedule in R82: decision ledger from H3, prep guide drafted at the freeze, code walk-through and one timed spoken rehearsal in the last 2 hours.
- MUST prepare an answer for every probe in the order above, including the two we had no material for last time (section 4.3).

### 4.3 Prepared answers for every probe

Prepare one answer per probe, in the judge's order (NOTES section 6). Each answer: the decision, the reason, a number, a failure mode.

| Probe | What to have ready | Example (Ghost Data) |
|---|---|---|
| Quick pitch | 60 seconds: the problem, what the model decides, what code decides, one number | "The model reads request text and 15 images or PDFs; code emits every step; 380 tokens per request" (BENCH section 5) |
| Retrieval and architecture (pattern 1) | Why this retrieval, and how it fails, in the shape "We used X because Y, then added Z only after seeing misses on rows W" | Exact-key index on normalized ids and hashes, because the evidence is identifier-heavy; it fails on evidence whose ids do not parse (BENCH section 2, judge 3). An honest answer to "agent or pipeline?" |
| Safety and failure modes (pattern 3) | The gates in order, and why the model cannot override them | Time gate in every tool; status gate after the model; abstain cap so the agent cannot dodge decisions |
| Implementation and code familiarity | Trace one case end to end; name the files and functions | One eval case traced through the linking, state and emit modules without notes (BENCH section 5) |
| Evaluation (pattern 2) | Development-set numbers, the small-sample policy, custom cases, one measured revert | Signature off changes 85 rows; late ids off drops sample exact 30 to 25; a 10-minute window shift costs 8 of 30 exact (EVR section 4) |
| Production monitoring | What you would watch, with a threshold and an action for each | The list below |
| What is novel | One honest sentence on what is new and what is standard | The note below |
| Working with AI tools | What you directed, accepted and pushed back on, with log times | The model ban (LOG 17:48); reverting a default an agent changed (LOG 00:54) |

Production monitoring (our inference; tie each item to a counter the code already writes to diagnostics):
- Input drift: new request languages, unknown row shapes (E-26), unknown file types, counted per run against a baseline.
- Abstain rate and fallback rate against their caps (`GUARDRAILS_AND_EDGE_CASES.md` section 1.1). A jump means drift or a model regression.
- Gate overrides and validator rejections. Each one is a model error that the gate caught.
- Late-evidence rejections at the time gate.
- Cost and latency per request, live calls, cache hit rate, retries and 429 responses.
- Disagreement rate between the model path and the rule path.
- A small human review sample each period, stratified by route (fast path, investigator, abstain).

Novelty: say which parts are standard (tool loop, schema output, retries, cache) and which part is specific to this problem (for example, reconstructing state from evidence with the cutoff applied inside every tool). If nothing is new, say so and name the part you executed best. The interview penalises claims the code does not support (NOTES section 6).

Answer style: long, specific answers score better (total words r = 0.615, share of longer answers r = 0.631, very short answers r = -0.568), and the number of turns is a weak negative (NOTES section 6). So answer fully in one turn rather than in many short exchanges. Rehearse with the prompt in `EVALUATION_STRATEGY.md` Appendix A.4.

### 4.4 Anti-patterns

- Fabrication: claiming a library, test or feature not in the code.
- Claiming no bug when the judge can see one.
- Short answers.
- Tool narration instead of decisions.
- Calling 0.9948 step F1 "accuracy".

Recommended time for interview prep (our inference, not measured): 90 minutes of code walk-through plus 30 minutes of spoken rehearsal, inside the last 2 hours of R82.

---

## 5. Cross-signal view

One investment can pay in several signals. Do these first.

| Investment | Code | Output | Chat | Interview |
|---|---|---|---|---|
| Read the official rubric in hour 0 and write a rubric-to-build map | yes | yes | yes | yes |
| Bounded tool-calling investigator with deterministic veto | high | medium | high (architecture talk) | high ("agent?" answer) |
| Explicit abstain path with routing | medium | medium | medium | high |
| User-authored decisions and own verification turns | none | none | high | high |
| Held-out or custom cases for uncovered families | medium | high | high | high |
| Time contract and no case-family shortcuts | high | high | medium | medium |
| Honest disclosure of limits | low | none | medium | high |

Priority order for the next build (our inference from the points lost in section 0.1):
1. Code architecture and prompt craft (up to about 11 points to gain).
2. Interview ownership (up to about 6 points).
3. Chat direction (up to about 4 points; cheap if you start right).
4. Output safety and uncovered families (up to about 3 points).

### 5.1 One-page 90+ checklist

Code
- [ ] A real tool loop with max turns, typed tools, tool descriptions, validated final answer, deterministic veto
- [ ] Triage routing that is logged
- [ ] Prompts with role, rules, schema, abstain
- [ ] Bounded retries, per-run cost cap, no crash on unknown input
- [ ] No fitted constants, no case-family shortcuts
- [ ] Installable package, type hints, env secrets, no dead config

Output
- [ ] Contract validator clean, byte-identical rerun
- [ ] Time contract respected strictly
- [ ] Custom cases for every family the samples miss, plus injection and decoys
- [ ] Specific justifications if the format has text

Chat
- [ ] Architecture and tradeoffs written by the user
- [ ] Specific constraints in prompts
- [ ] User-led verification turns with real rows and metrics
- [ ] Edge cases raised by the user
- [ ] Context block valid in every entry; closed loops logged

Interview
- [ ] One case traced end to end without notes
- [ ] Decision ledger in first person with numbers
- [ ] Honest "agent or pipeline" and "what is weak" answers
- [ ] Spoken rehearsal done
