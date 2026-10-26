# solutionv2: playbook for the next HackerRank Orchestrate

This folder is a reusable playbook. It is written for a fresh project in a new repo, probably with a NEW problem and the SAME four judged signals.

It is built from what the Ghost Data Still Exists build (October 2026) missed, measured against the edition-1 rubric.
Generic rules come first. Each rule has a concrete "Example (Ghost Data)" you can replace.

Short on time? Read `GUIDELINES.md` (one page) and follow its links.

## What the score is

`Final = 0.10 chat + 0.30 interview + 0.30 output + 0.30 code`

Tie-break order: interview, then code, then output, then chat.
Every Top-10 submission in edition 1 was top-quartile on all four signals, so a balanced build wins.
(Source: NOTES sections 2 and 7.)

Where Ghost Data stood when benchmarked against the edition-1 rubric (scores from our own judge runs, not official):

| Signal | Weight | Our benchmark | Biggest gap |
|---|---|---|---|
| Code zip | 30% | about 62 / 100 | Agent architecture 25 to 30 of 100: "deterministic rule pipeline" |
| Output CSV | 30% | about 89 / 100 | Missing ids that no file contained; untested rule families |
| Interview | 30% | readiness about 80 / 100 | "Agent or pipeline?" and code familiarity |
| Chat transcript | 10% | about 59 / 100 | Format perfect; direction and technical specificity low |
| Weighted | | about 75 / 100 | |

Source: BENCH section 1.

## Files in this folder

Read in this order on hour 0: `GUIDELINES.md`, `CONSTITUTION.md`, `RULES.md`, `RUBRIC_PLAYBOOK.md`, then the rest as needed.

| File | Owns | Read when |
|---|---|---|
| `README.md` | Index, source legend, glossary, the 10 lessons in one line each | First |
| `GUIDELINES.md` | One-page quickstart: hour-by-hour must-dos, each linked to a rule id | Hour 0, then at each phase change |
| `CONSTITUTION.md` | 12 non-negotiable principles (P1 to P12) and the order of authority | Hour 0, and before any big decision |
| `RULES.md` | 91 numbered hard rules (R1 to R91) in groups A to J, every numeric target, and the final gate (section K) | Hour 0, and at every freeze |
| `RUBRIC_PLAYBOOK.md` | How each of the four signals is judged, what to build for it, interview prep content | Hour 0 |
| `REQUIREMENTS.md` | Functional requirement template, NFR targets, compliance checklist | Hour 0 to 1 |
| `ARCHITECTURE.md` | Agent shape, patterns, architecture options, repo skeleton, cache design | Hour 1 to 2 |
| `GUARDRAILS_AND_EDGE_CASES.md` | The cap-and-budget table, gates, error handling, edge cases (E-ids), loopholes | Hour 1, and before coding each stage |
| `PROMPTING_STRATEGY.md` | Part A: how you prompt the coding agent. Part B: prompts and tools inside the product | Hour 0 (A), hour 2 (B) |
| `EVALUATION_STRATEGY.md` | Local evaluation: validator, scorer, small-sample policy, custom cases, ablations, audit, judge-panel policy | Hour 1, and at every measured change |
| `DEVELOPMENT_STRATEGY.md` | 24-hour timeline, scope, planning size, decision-log template, when to ask the user | Hour 0 |
| `SUBAGENT_DELEGATION.md` | Sub-agent roles, model tiers, briefs, verification policy, guards against agents changing decisions | Before the first workflow |
| `TOKEN_COST_EFFICIENCY.md` | Token and money budgets for the product and the build, model choice by measured equality | Before the first workflow |
| `LESSONS_LEARNED.md` | Gap table: what we missed, what worked, what it cost (the story behind each rule) | When a rule needs its story |
| `evidence/BENCHMARK_SUMMARY.md` | Copy of our rubric benchmark (per-judge scores and quotes) | When you need a BENCH number |

Ownership rule: each topic lives in one file. Other files link to it. Rule ids (`R27`), principle ids (`P2`), gap ids (`G1`) and edge-case ids (`E-12`) are the stable links.
Every numeric target (task count, custom-case count, release checks, function size, flag count) is set once in `RULES.md`. Other files cite the rule id.

## Source legend

Every playbook file uses these tags. Paths are in the Ghost Data repo; they are references, not dependencies. Copy `evidence/` and `solution/past_evaluation_notes.md` with this folder; the rest stays behind.

| Tag | Source |
|---|---|
| NOTES | `solution/past_evaluation_notes.md`: the edition-1 official rubric, extracted from a public article |
| BENCH | `evidence/BENCHMARK_SUMMARY.md`: 7 Opus judges scored the frozen rc1 against NOTES |
| PANEL | `devtools/JUDGE_PANEL.md`: our own judge personas (rules, quality, newcomer, transcript) at rc2 and rc3 |
| MANIFEST | `devtools/RELEASE_MANIFEST.md`: rc4 gates, waivers, changes |
| AUDIT | `devtools/audit/coverage_result.md`: the targeted 61-case blind audit |
| DECISIONS | `code/docs/DECISIONS.md`: decision records D1 to D25 |
| ARCH | `code/docs/ARCHITECTURE.md`: the shipped architecture document |
| EVR | `code/evaluation/evaluation_report.md` |
| USAGE | `code/evaluation/usage_report.md` |
| SCORING | `plan/SCORING_STRATEGY.md` (planning-time numbers) |
| LES | `plan/LOCAL_EVALUATION_STRATEGY.md` (planning-time numbers) |
| PLAN | the `plan/` folder (spec, plan, reviews, task files) |
| LOG | `log.txt`; times are UTC, for example `LOG 17:08` or `LOG 2026-10-24T17:08Z`; a bare number is a line number |
| ANALYSIS | `solution/ANALYSIS.md`: the first data and problem analysis |

## Glossary (Ghost Data terms used in examples)

- **Ghost Data**: the October 2026 problem. For each deletion request, decide COMPLETE, INCOMPLETE or NOT_APPLICABLE at the case's `audit_at` and list ordered steps with citations.
- **`audit_at` / cutoff**: the time after which no evidence may change or support an answer.
- **Signature**: a learned "worker latency" pattern (seconds-of-minute residues) used to link activity rows to resources. It was a regularity of the data generator (DECISIONS D3).
- **FIFO**: first-in-first-out pairing used to break ties when two links were equally likely.
- **`account_00N` convention**: a shortcut that mapped `user_01..user_10` to `account_001..account_010`. No file supported it; judges called it a case-family shortcut.
- **Late ids**: audit-record ids found only in files captured after `audit_at` (`use_late_audit_ids`).
- **D-numbers**: DECISIONS entries. **T-numbers**: plan task ids. **rc1 to rc4**: release candidates.
- **G1 to G8**: our grader emulations (EVR section 1). **S0/S1/S2**: model strategies (no model, strong model, cheap model).
- **Persona**: one judge role in PANEL (rules, quality, newcomer, transcript).
- **H0 to H24**: hours from the event start. **M1 to M3**: milestones (first output, agent layer done, feature complete).

## How to use this playbook in a 24-hour hackathon

1. Before the event: copy this folder into the new repo as `playbook/` (read-only reference), with `solution/past_evaluation_notes.md` beside it.
2. Hour 0, first 30 minutes (the user does this, not the agent): read the problem statement and `AGENTS.md`, run the hour-0 checklist (R77), paste or link `CONSTITUTION.md` and `RULES.md` from the new repo's `AGENTS.md` or `CLAUDE.md`, write `CONTRACT.md` (R1).
3. Then follow `GUIDELINES.md` hour by hour. The full timeline is in `DEVELOPMENT_STRATEGY.md` section 1.
4. Last hour: run the final gate in `RULES.md` section K. Verify hashes, upload.

If time is very short, do these four, in this order: R77 (hour 0), R27 to R28 (a small real agent loop with gates), R47 and R48 (scorer and the small-sample policy), R55 to R56 (logging done right).

## The 10 most important lessons (one line each; the evidence is in the linked files)

| # | Lesson | Story | Rules |
|---|---|---|---|
| 1 | Read the real rubric before choosing the architecture. Build for all four signals from hour 0. | LESSONS G12, G13 | P1, R77 |
| 2 | Build a real agent with deterministic guardrails, not a rule pipeline with LLM calls on the side. | LESSONS G1, I2 | P2, R27 to R29 |
| 3 | The user must own and write the decisions. "Go ahead" and "(Recommended)" score low. | LESSONS T1, T2 | P6, R62 to R65, R69 |
| 4 | The problem contract beats score hacks. Judges read the contract too. | LESSONS G3 to G5 | P4, R2 to R9 |
| 5 | In-sample numbers are not accuracy. Write cases for untested families; hold out only when the sample is big enough. | LESSONS G6 | P7, R48 to R50 |
| 6 | Sub-agents must never change defaults, models or decisions. Pin decisions in a test. | LESSONS P8, P9 | P6, R66 to R68 |
| 7 | Do the hour-0 setup first. The API key came late (LOG 18:54, 1h46 after implementation began). Python 3.9.6 vs SDK 3.10 and "no sampling parameters" were known in planning (LOG 15:39, 16:19) but still cost a two-toolchain design: check them at hour 0 and choose the toolchain then. | LESSONS P5 to P7 | P11, R12, R18, R19, R26, R77 |
| 8 | Spend time and tokens where the score is. Keep plans small and verify cheaply first. | LESSONS P1 to P4, P11 | P11, R73 to R76, R79, R81 |
| 9 | Treat personal data and secrets as hazards everywhere, including caches, logs and test fixtures. Never crash on unknown input. | LESSONS G7, G9 | P9, P10, R11 to R17, R33 to R35 |
| 10 | Keep the code small, honest and explainable. Say what is weak. | LESSONS G8, G15 | P3, P8, P12, R36 to R40, R45, R46 |

## How reliable is this evidence

- The edition-1 rubric comes from a public article by the HackerRank co-founder, extracted in NOTES. It covers a different problem. NOTES section 9 marks which parts are our inference. The October rubric dimensions may differ.
- BENCH numbers come from judge sub-agents we ran against that rubric, on rc1. They are estimates, not official scores. BENCH section 6 lists numbers that changed after rc1; the playbook uses the final numbers unless it says otherwise.
- PANEL scores (26 to 27.5 of 30, transcript 9 of 10) come from our own personas and our own categories.
- Every rule cites its source. Where a number is a team convention, the rule says so (for example R38, R40, R79).

## Rule of thumb for reuse

Keep the rule. Change the example. If the next problem has a different grader, re-read `RUBRIC_PLAYBOOK.md` and update the weights in P1 before anything else.
