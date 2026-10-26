# BENCHMARK_SUMMARY.md: our rubric benchmark of the Ghost Data submission

This file is the tag `BENCH` used in every playbook file. It copies the numbers and the most-cited quotes from
a temporary workflow output file that will not exist in a new repo.

- What was judged: the frozen **rc1** submission (unzipped `code.zip`, `output.csv`, `log.txt`), read-only.
- Who judged: 7 judge agents, all `claude-opus-5-5`, applying the edition-1 rubric from `solution/past_evaluation_notes.md` (NOTES).
- When: LOG entry `2026-10-24T23:52:57Z` (launch) and `23:59:26Z` (result, "~75/100").
- Cost: 778,155 tokens and 140 tool calls in total (82k to 178k tokens per judge).
- Status: these are **our estimates**, not official scores. Some numbers changed after rc1 (see "Later changes" below).

## 1. Weighted result

| Signal | Weight | Score | Weighted points |
|---|---|---|---|
| Code zip (median of 3 judges) | 0.30 | 62 (judges 61.2, 64, 62) | 18.6 |
| Output CSV | 0.30 | 89 (likely range 80 to 94) | 26.7 |
| Interview readiness (no real interview) | 0.30 | 80 (80.5 weighted) | 24.0 |
| Chat transcript | 0.10 | 58.6 (judges 58.6, 60; the run used the lower one) | 5.86 |
| **Sum** | | | **75.16** |

## 2. Code zip judges (dimension scores are 0 to 100; the weight is in brackets)

| Dimension (weight) | Judge 1 | Judge 2 | Judge 3 |
|---|---|---|---|
| Agent architecture (30%) | 25 | 30 | 25 |
| Prompt and tool craft (30%) | 68 | 72 | 70 |
| Agent robustness (25%) | 78 | 80 | 80 |
| Engineering rigor (15%) | 92 | 90 | 90 |
| Weighted total | 61.2 | 64 | 62 |

Judge 1 formula: `0.30*25 + 0.30*68 + 0.25*78 + 0.15*92 = 61.2`.

Architecture bucket (all three): "Deterministic rule pipeline / no explicit agent", the edition-1 bucket with average rank about 933.

Most-cited gaps (quotes, shortened):
- "No tool-calling loop: the model is never given tools such as search_evidence, resolve_identity or get_resource_state" (all three).
- "No model-driven routing: the control flow in pipeline.py:154-184 is fixed" (judge 1); "No multi-agent handoffs and no LLM planner, critic or verifier stage" (judges 1 and 3).
- "No tool definitions or tool descriptions exist at all" (judge 1); "half of 'prompt and tool craft' has nothing to score" (judges 2 and 3).
- "There is no explicit abstain or 'cannot determine' output, so the lexicon fallback is triggered only by numeric confidence" (judge 2).
- "Linking relies on dataset-fitted time windows, a user_01-10 to account_00N convention and generator-latency residues, which is brittle outside this dataset" (all three name the windows and the convention).
- "No max-iteration cap is needed because no agent loop exists. The rubric item is effectively unaddressed" (judge 3).
- "Retrieval is purely lexical and identifier-based. There is no semantic retrieval for evidence whose identifiers fail to parse" (judge 3).
- "Config.LLM_MODES includes 'batch' ... no batch client exists, so it is a dead path" (all three).
- "main.py:18-20 changes sys.path instead of being installed as a package" (judges 1 and 2).
- "config.py mixes run-time configuration with many SPEC/task-tracking constants (T14, T26, T35)" (judges 1 and 3).
- "843 cached response JSON files sit inside the source package ... it adds bulk" (judge 2).

Shared top fix (all three `improve[0]`): "add a real bounded tool-calling investigator for ambiguous or low-confidence cases ... typed tools ... a max-iteration cap, and schema-validated final output. Keep the deterministic resolver as the guardrail and fallback". Judge 1 adds: "Alone, this could move Agent architecture from about 25 to about 60-70." Judge 3 adds: "Add a per-run cap on total LLM calls and spend, alongside the per-call retry cap."

## 3. Output judge

| Dimension | Score | Note |
|---|---|---|
| Sample accuracy (32 public samples, in-sample) | 99.7 | 30 of 32 exact; case_18 and case_20 miss an audit step whose id is in no participant file |
| Estimated eval accuracy | 89 | contract check: 518 rows, 0 violations |
| Safety and adversarial handling | 90 | 10 NOT_APPLICABLE rows correct; 365 distinct deletion texts in 6 languages, no misclassification; 0 citations after `audit_at` |

Formula: about 0.85 x accuracy + 0.15 x safety. "If the hidden grader rewards row-exact matches heavily ... the score falls toward 70."

Gaps: about 83 INCOMPLETE cases miss one audit verification step (about 80 steps); 12 COMPLETE rows miss the account step ("on 1-3 step rows this is a heavy penalty per item"); about 26 FIFO-tied cases; no sample covers NOT_APPLICABLE, legal hold, object storage or marketing data; about 140 "untested rules fired"; "99.7 overstates hidden accuracy"; natural vs lexicographic `case_id` order.

## 4. Chat transcript judges

| Dimension (weight) | Judge 1 | Judge 2 |
|---|---|---|
| Direction and architecture ownership (35%) | 61 | 62 |
| Technical specificity and constraint (25%) | 47 | 50 |
| Iteration and verification (25%) | 69 | 70 |
| Safety, edge case and quality awareness (15%) | 55 | 55 |
| Total | 58.6 | 60 |

Format: "fully valid". 183 entries (1 session start, 22 user turns, 160 sub-agent entries), each with exactly one `tool=` and one `model=` line. Model mix in entries: Opus 112, Sonnet 57, Haiku 13.

Quotes (shortened):
- "The SOLUTION architecture is fully delegated ... the deterministic pipeline, LLM use only for intent and media, the learned link signature ON (log.txt:103), and FIFO coupling" (judge 2).
- "Several decisions select the AI's '(Recommended)' options verbatim (line 3859) ... line 4044 is just 'Go ahead' after asking 'what is your recommended next step?'" (judge 1).
- "About 7 of 22 turns are status or progress checks or acknowledgements" (judge 1); "4 of 22 turns are status or progress queries" (judge 2).
- "No user prompt specifies algorithms, schemas, thresholds, libraries, the output format ... or the identity-linking method" (judge 1).
- "The user never personally shares an error, pastes a failing row or inspects sample output" (judge 2).
- "log.txt:3259 and :3373 deliberately weaken verification ... The combined check then rejected 6 of 15 tasks (log.txt:3660)" (judge 2).
- "T02b, T20, T02, T10 and others are each logged 3-4 times (e.g. T02b at log.txt:366, 457, 1159, 1272, 1969)" (judge 2).
- "The last workflow (line 4041 ...) has no logged result" (judge 1).
- "No user prompt raises the task's adversarial or edge-case dimensions ... they come from the AI or sub-agents" (judge 1).

## 5. Interview readiness judge

| Dimension (weight) | Score |
|---|---|
| Technical depth and ownership (40%) | 78 |
| Problem understanding and judgment (25%) | 82 |
| Communication clarity (20%) | 80 |
| Honesty and self-awareness (15%) | 85 |
| Weighted | 80.5 |

Facts it re-checked: byte-identical rerun in 0.53 s; 883 tests pass (5 skipped); all 7 custom cases pass; label-free verifier 0 hard failures; 31 calls, 196,870 tokens, $0.8563.

Risks it named: "(a) Ownership and code familiarity: almost all the code came from orchestrated sub-agents. (b) 'Agent or pipeline?': it is a deterministic pipeline, and the LLM changes 0 intent decisions. (c) The generator-artifact latency signature. (d) Sample scores are presented as accuracy."

Advice (shortened): rehearse a candid "agent vs pipeline" answer; concede the signature is a generator regularity; call sample metrics development-set performance; "walk link_graph.py, link_solver.py, linking.py, state.py and emit.py by hand until one eval case ... can be traced end to end without notes. Code familiarity is the weakest ownership signal"; state the AI-assistance story plainly.

## 6. Later changes (why some playbook numbers differ from rc1)

| Item | At rc1 (this benchmark) | Final (rc4) | Source of the final number |
|---|---|---|---|
| Rows changed by `--signature off` | 95 (interview judge, from `plan/SCORING_STRATEGY.md` O1) | 85 | `code/evaluation/evaluation_report.md` section 4 |
| Late audit ids off | 116 steps (planning estimate, SCORING O4) | 124 rows, one step each; sample exact 30 to 25 | evaluation report section 4 |
| 12 COMPLETE rows without the account step | open | fixed by D22 | `code/docs/DECISIONS.md` D22 |
| Unknown activity row aborts the run | present | fixed (UNCLASSIFIED, counted) | `devtools/RELEASE_MANIFEST.md` |
| PII in cached media replies | present | redacted at rest (D25) | RELEASE_MANIFEST |
| Tests | 883 | 925 code tests | LOG `2026-10-25T01:17:54Z` |

The playbook uses the final numbers unless it says "rc1" or "planning estimate".
