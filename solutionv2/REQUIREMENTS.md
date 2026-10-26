# REQUIREMENTS.md: FR template, NFR targets, compliance checklist

Owner of: what the system must do and how well (functional and non-functional requirements), and the problem-compliance checklist.
Not here: how to structure the agent (ARCHITECTURE.md), safety and error behaviour (GUARDRAILS_AND_EDGE_CASES.md).
Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".

## 0. How to use this file

Day 0 (first 30 minutes of the new hackathon):
1. Copy section 1 (FR template) and fill it from the new problem statement. One row per sentence of the statement that says "must", "should", "never", or defines a field.
2. Copy section 2 (NFR table). Keep the targets, change only with a reason.
3. Copy section 3 (compliance checklist). Fill from the statement and from the repo's AGENTS.md.
4. Put the three into `docs/SPEC.md` of the new repo. Number every requirement. Tests and decisions cite these numbers.

Why: last time the spec was long (plan/SPEC.md ~38 KB, 46 task files) and still the first alignment audit came late ("did we digress from the problem statement?", log.txt 2026-10-24T22:15). A short numbered list checked at the start and the end is cheaper.

Evidence: plan/ directory sizes; log.txt user turn at 22:15:53Z; code/docs/SPEC.md rule ids.

## 1. Functional requirements (FR) template

Write each FR in this form. Keep to one line per field.

```
FR-<n>  <short title>
  Source:     <problem statement section / AGENTS.md section / dataset file>
  Statement:  The system MUST/SHOULD <behaviour> when <condition>.
  Input:      <files/fields used>
  Output:     <fields/format produced>
  Edge cases: <list of GUARDRAILS_AND_EDGE_CASES.md section 3 ids, e.g. E-7, E-15>
  Test:       <test id or sample case id that proves it>
  Status:     todo | done | waived(reason)
```

### 1.1 Always-present FRs (every Orchestrate problem so far)

| FR | Requirement | Why |
|---|---|---|
| FR-A1 | Read only participant-facing data. Never read organizer-only, golden, or sample-answer files from the solver. | Rules forbid it; a static scan is cheap proof. |
| FR-A2 | Produce exactly one output row per input case, in the required sort order, with the exact header. | Output file is auto-scored. A missing row is a zero for that item. |
| FR-A3 | Obey the output schema exactly (fields, allowed values, ordering rules, JSON validity). Validate before writing. | Format errors are the cheapest points to lose. |
| FR-A4 | Decide whether the request is actionable at all (non-actionable requests get the "not applicable" output). | Hidden golden set includes non-actionable and trap items. |
| FR-A5 | Use only information available at the cutoff time given per case. | Time-contract traps in the data. Judges check it. |
| FR-A6 | Treat reported statuses, logs and system messages as claims, not proof. | Data is built so claims are sometimes wrong. |
| FR-A7 | Cite participant-visible evidence ids for every finding or claim. | Citations are graded. |
| FR-A8 | Run from the terminal with one documented command and write the output at the repo root. | Evaluability. |
| FR-A9 | Write an evaluation report and a usage report with the required content. | Required by the submission. |
| FR-A10 | Write the chat log in the format AGENTS.md requires, every turn. | 10% of score; half of edition-1 logs failed on format. |

### 1.2 Example (Ghost Data): the domain FRs we derived

| FR | Requirement | Source |
|---|---|---|
| FR-G1 | Resolve the request email to one user through current and historical emails, phones, hashes. | problem_statement.md; AGENTS.md section 6.5 |
| FR-G2 | State of each record is "latest admissible observation at or before `audit_at`". | AGENTS.md section 6.2 |
| FR-G3 | Apply `deletion_rules.csv` per category: DELETE / REDACT / ANONYMIZE / RETAIN / TOMBSTONE. Do not delete retained records. | AGENTS.md section 6.5 |
| FR-G4 | `COMPLETE` only if every copy is compliant, every required retained record exists, and no active flow or restore path remains. | AGENTS.md section 6.5 |
| FR-G5 | `INCOMPLETE` output has findings, ordered remediation (flows and restores first), and verification. Remediation and verification use empty `evidence_id`. | AGENTS.md sections 6.3, 6.6 |
| FR-G6 | `COMPLETE` output has verification steps only, each with citation. | AGENTS.md section 6.3 |
| FR-G7 | Non-deletion requests (access, correction, export, marketing opt-out) get `NOT_APPLICABLE` and `[]`. | AGENTS.md section 6.5 |

## 2. Non-functional requirements (NFR) with measurable targets

Each NFR has a number or a yes/no check. "Fast" or "robust" without a number is not allowed.

| ID | NFR | Target | How to measure | Last time (reference) |
|---|---|---|---|---|
| N1 | Determinism | Two runs, different `PYTHONHASHSEED`, give byte-identical output | `sha256sum` of output after 2 runs; automated test | Met. Test over seeds 0 and 4242 (code/docs/ARCHITECTURE.md section 6). |
| N2 | Latency (offline/cached full run) | Under 5 s for the full dataset; aim under 1.5 s | Stage timings in diagnostics | ~0.9 s wall (ARCHITECTURE.md section 5). |
| N2b | Latency (live agent run) | Bounded: per-case turn cap; whole run under a stated limit; concurrency cap (e.g. 8) | Timing in diagnostics, `--max-turns` | Not built last time (no agent loop). |
| N3 | Cost per request | State a cap before building (e.g. under $0.01 per request average); hard per-run dollar cap enforced in code | `usage_report.md`, budget object | $0.0017 per request replayed, $0.86 total for 31 calls (code/evaluation/usage_report.md). |
| N4 | Token efficiency | Report tokens per request. Summaries to router, full records only on demand | Usage meter | 380 tokens per request average (replayed). |
| N5 | Offline replay | A clean checkout with the cache runs with zero live calls and zero cache misses; the output is identical to the live run | Run `--llm cache`; miss count in diagnostics | Met (R8 clean-room matrix, MANIFEST). |
| N6 | Python version support | Core and cache replay run on the system `python3` of the review machine (3.9 last time). Live mode may need newer, but must fail with a clear message | Run on the oldest target; lazy-import SDK | Core 3.9 stdlib only; live needed 3.10 (DECISIONS D7). Known in planning (LOG 15:39, 16:19); keeping 3.9 for the core forced a split toolchain. Check `python3 --version` on day 0. |
| N7 | Secrets | Keys only from environment or an uncommitted `.env`. Keys wrapped so `repr` shows `***`. Never logged, cached, or zipped. `.env.example` has names only | Static scan for key patterns; scan of zip and log | Met. |
| N8 | PII handling | No real or dataset personal data in logs, cache, reports, zip. Hash or drop in stored model replies. Log redaction rule for dataset identifiers | Scan zip and `log.txt` for emails and phones | Missed three times: cache held emails and names; one log entry held a dataset email (PANEL deductions); 10 shipped test files held dataset-derived emails or phones (LOG 2026-10-25T01:17Z). The first two were fixed late. |
| N9 | Observability | Per-case trace: route, tools called, evidence cited, validator verdict, fallback, flags fired. Per-run: counts by status, cache misses, warnings, stage timings | `diagnostics.md` | Met for the pipeline (diagnostics.md). Add agent trace. |
| N10 | Graceful degradation | If the model is down, over budget, or refuses: the run still finishes with a valid output for every row | Kill-switch test: `--llm off` gives full valid file | Met (SPEC N7). |
| N11 | Robustness to bad input | One bad row, file, or activity line never aborts the run | Test with injected malformed rows | Missed once: an unknown activity row aborted the whole run (PANEL quality judge). Fixed in rc4. |
| N12 | Contract validity | Output validator reports 0 violations; non-zero exit code if any | `contract.validate` in the run | Met. |
| N13 | Portability | `pathlib`, UTF-8, `\n` line endings, paths relative to repo root, no bash assumptions | Run on macOS and a Linux container if possible | Met. |
| N14 | Reproducible setup | One setup command and one run command in README; both tested from a fresh clone | Clean-room run | Met. |
| N15 | Test coverage | Unit tests per rule, golden test on samples, determinism, late-evidence, static isolation scans, custom cases | Test suite run | 883 tests passed (BENCH section 5); this was heavy. See section 4 for a lighter target. |
| N16 | Code size and simplicity | Median function under ~10 lines; type hints on public functions; no dead flags | Lint plus a small script | Met (median 8 lines). |
| N17 | Generalization | No constants fitted to the dataset generator without a documented fit procedure and an off switch; metrics reported on a held-out split too | Evaluation report section "held-out" | Missed. All metrics were in-sample (32 samples) and three judges flagged it. |

Notes:
- N3/N4: set the caps on day 0. If you add an agent loop, the cap must include all turns, not just the final call.
- N6: check the Python version of the machine that will run the code, and the SDK minimum, in the first hour, and choose the toolchain then. Last time both were known in planning, and the choice to keep a 3.9 core cost a second toolchain (DECISIONS D7).
- N8: dataset identifiers include emails and phones inside images and PDFs. Redact before caching.
- Sampling parameters: current models reject `temperature`, `top_p` and `top_k` (verified in the docs at planning time, LOG 16:19; DECISIONS D6). Do not rely on them for determinism. Use the cache and structured outputs.

## 3. Problem-compliance checklist template

Fill this from the new problem statement and AGENTS.md on day 0. Re-run at the half-way point and before submission. Tick only with evidence (a file path, a test, a command output).

### 3.1 Data and contract
- [ ] Every input file and field listed in the statement is loaded or consciously ignored (with reason).
- [ ] The solver reads only the allowed input folder. Static test proves no answer-file reads.
- [ ] Output file name, location, header, column order exact.
- [ ] Row count equals input row count. Ids unique and match one-to-one.
- [ ] Sort order is the one the statement says. If ambiguous (natural vs lexicographic), decide, document, and test both orders on the grader-join assumption. (Last time `case_99` vs `case_100` ordering was flagged by two judges.)
- [ ] Every enum value in output is in the allowed list. No invented operations, phases, states.
- [ ] Serialized JSON valid; step numbering consecutive from 1; phase order rule respected.
- [ ] Non-actionable requests produce the specified empty output.

### 3.2 Behaviour rules
- [ ] Time cutoff enforced for evidence, activity, and citation. Default is strict. See GUARDRAILS_AND_EDGE_CASES.md section 1.5.
- [ ] Claims (reported statuses) are never used as proof.
- [ ] Policy table is data driven. Retained records are never deleted.
- [ ] Citation ids always come from admissible, participant-visible files.
- [ ] Remediation ordering rule from the statement is implemented as stated (not as the sample answers suggest if they differ; if they differ, note it and decide with a measurement).
- [ ] No case-family shortcuts (rules keyed on case number, user number, or generator naming conventions).

### 3.3 Deliverables
- [ ] `code.zip` contents match the list in the statement; no dataset, no venv, no cache of PII, no nested archive, no keys.
- [ ] `README.md` has setup and run commands that were run from a clean checkout.
- [ ] `evaluation/evaluation_report.md`: case-level accuracy, step/field/sequence accuracy, at least three custom cases, failures and fixes.
- [ ] `evaluation/usage_report.md`: provider, models, calls, input/output tokens, total and per-request tokens and cost, per-model and overall.
- [ ] Output file at repo root.
- [ ] Chat log file at repo root in the exact required format.
- [ ] Agent trace archive if the platform asks for one.
- [ ] Interview prep done (R82; content in `RUBRIC_PLAYBOOK.md` section 4.2).

### 3.4 Honesty
- [ ] README and reports describe only what the code does.
- [ ] Sample accuracy is called "development-set performance", not "accuracy".
- [ ] Known limitations and tie-break guesses are listed in the evaluation report.

Evidence for 3.1 to 3.4: AGENTS.md sections 6.3, 6.6, 6.7, 6.9; PANEL deductions (sort order, in-sample metrics, time contract); BENCH sections 4 and 5.

## 4. Requirement priority (MoSCoW) for a time-boxed build

Last time the plan had 46 task files. Sub-agent usage was already about 9.5M tokens across finished workflow runs at the /usage check (log.txt, 2026-10-25T00:12) and kept growing with later audit, panel and release workflows. The score gain from the last 20% of effort was small compared with the gap in agent architecture.

The priorities follow the timeline in `DEVELOPMENT_STRATEGY.md` section 1. The agent layer comes straight after the thin slice, before accuracy work, because agent architecture and prompt craft are 60% of the code score and late architecture changes are expensive (BENCH section 2).

| Priority | Build | Phase (`DEVELOPMENT_STRATEGY.md` section 1) |
|---|---|---|
| MUST | Loader, identity/keys, evidence index, time cutoff, policy table, emitter, contract validator, scorer, CLI, logging, and a baseline that gives a valid row for every case | Phases 0 to 3 (H0 to H7) |
| MUST | Agent loop with tools, router, validator veto, fallback, caps (ARCHITECTURE.md; GUARDRAILS section 1.1) | Phase 4 (H7 to H11) |
| MUST | Accuracy loop on the fast path and the agent, by measured, general fixes | Phase 5 (H11 to H17) |
| MUST | Evaluation report (small-sample policy, custom cases per R49), usage report, README | Phase 6 (H17 to H19) |
| SHOULD | Ablations for each learned constant and each model role, decision ledger for the interview (R45, R82) | Phases 4 to 6 |
| COULD | Extra verifier agent, semantic retrieval | Only if ahead |
| WON'T | The overkill list in `DEVELOPMENT_STRATEGY.md` sections 2 and 3 | Never |
