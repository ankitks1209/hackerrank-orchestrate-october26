# RULES

Hard, numbered rules for the next HackerRank Orchestrate build. Cite them as `R7`, `R42`, and so on.

- MUST = a violation is a defect. SHOULD = do it unless you can state a better reason. AVOID = do not, unless the user decides otherwise.
- The principles behind the rules are in `CONSTITUTION.md` (P1 to P12). If a rule and the problem statement or `AGENTS.md` conflict, the statement and `AGENTS.md` win.
- Every rule has a one-line Why. Evidence points to the Ghost Data repo. Source tags (NOTES, BENCH, PANEL, LOG and the rest) are defined once in `README.md`, section "Source legend".
- "Example (Ghost Data)" shows the rule on the October 2026 problem. The next problem will differ; keep the rule, change the example.

| Group | Rules | Topic |
|---|---|---|
| A | R1 to R10 | Compliance with the problem statement and the AGENTS contract |
| B | R11 to R17 | Secrets and PII (including caches) |
| C | R18 to R26 | API and model usage |
| D | R27 to R40 | Agent core, robustness, code quality |
| E | R41 to R46 | Evidence and honesty |
| F | R47 to R54 | Evaluation |
| G | R55 to R65 | Logging and transcript |
| H | R66 to R76 | Agent governance and sub-agent delegation |
| I | R77 to R82 | Time and workflow |
| J | R83 to R91 | Packaging and release |
| K | | Final gate checklist |

---

## A. Compliance with the problem statement and the AGENTS contract

**R1. MUST turn the problem statement and `AGENTS.md` into a one-page `CONTRACT.md` in the first hour.**
List: output columns and order, row count, sort order, allowed enums, time cutoffs, banned data sources, required files, exact strings, logging format, deliverables, packaging limits.
- Why: every later check (validator, packager, reviewer) reads from this list. Contract misses are the cheapest points to lose.
- Evidence: ANALYSIS section 9 found several contract oddities only after analysis: reports path differed between `AGENTS.md` and the README; the submission URL had four `w`; the end time was "not configured".

**R2. MUST obey every time cutoff. Nothing dated or captured after the cutoff may change a decision or be cited.**
Strict mode is the default. If a value exists only after the cutoff, omit it.
- Why: the statement said "use only information available at or before `audit_at`". Judges read that line too.
- Evidence: PANEL: two on-by-default inference paths read later evidence (one is `use_late_audit_ids`); the rules and newcomer personas each deducted 0.5 point. The user chose "Keep + disclose" (LOG 22:33 entry) and the transcript judge scored safety ownership 55 for it (BENCH section 4). Turning the option off removes one step from each of 124 rows and drops sample exact matches from 30 to 25 of 32 (EVR section 4), so this was a real trade, and still a net code-score cost.
- Example (Ghost Data): an audit-record id that appears only in a file captured after `audit_at` is not added to a verification step.

**R3. MUST NOT read organizer-only files, golden labels or the sample answers at run time.**
Samples are for scoring and tests only. Put the reader behind an allowlist of participant files and test it.
- Why: `AGENTS.md` bans it, and it is easy for a judge to check.
- Evidence: `DatasetReader` allowlist of 8 CSVs plus `evidence/**` (LOG T02 entries); gold reading was confined to `tests/gold.py`.

**R4. MUST NOT hardcode case ids, user ids, resource ids, id ranges, or naming conventions that map one id to another.**
Add a "relabel test": rename ids consistently in a copy of the inputs and check that the output changes only by the renaming.
- Why: this is a "case-family shortcut". It breaks on any hidden row that does not follow the pattern.
- Evidence: PANEL (all three personas: rules major 0.5, quality major 1, newcomer minor 0.25; all three BENCH code judges (section 2) also named it): `_convention_account` mapped `user_01..user_10` to `account_00N`, producing an id no file supported. ANALYSIS section 9 listed `case_N` to `user_(N-2)` (498 of 518) as "do not use".

**R5. MUST NOT fit constants to how the dataset was generated.**
Time windows, latency residues and offsets fitted by looking at samples are forbidden. If a number is needed, take it from the statement, or compute it from the case's own data at run time using only data available at that case's cutoff, and write its source next to it.
- Why: judges call it "dataset-fitted constants"; it also fails on unseen data.
- Evidence: PANEL: fixed link windows in `config.py` (for example `account_window -78..-42 min`). Shifting every window by +10 minutes cost 8 of 30 exact matches (EVR section 1), which proves the fit was brittle. DECISIONS D24 had to make the fit strictly causal late in the build.

**R6. AVOID generator-artifact exploits (fingerprints, row order, id sequences, formatting leaks).**
If the user still decides to use one, it MUST be: off by default, measured on and off, disclosed in README, evaluation report and DECISIONS, and explainable in the interview.
- Why: it raises the score on samples but lowers code and interview scores, and the AI should not make this call alone.
- Evidence: the learned latency signature changes 85 eval rows when off, and 0 statuses (EVR section 4; the rc1 planning estimate was 95, SCORING O1); it was made default ON by the AI as "the key decision" (BENCH section 4, LOG line 103); the interview guide had to defend it as "a generator regularity" (DECISIONS D3 caveat).

**R7. MUST resolve an unclear instruction in this order: literal text, then sample outputs, then ask the user. Record the choice and the cost of the alternative in DECISIONS.**
- Why: guesses made silently turn into hidden deductions.
- Evidence: "Sort rows by `case_id`" was ambiguous: natural order puts `case_99` before `case_100`, text sort does the reverse. The newcomer panel deducted 0.25; BENCH asked to confirm the grader joins on `case_id`. Check the sample file's order at hour 1 and state the choice in the README.

**R8. MUST copy exact required strings verbatim: submission URLs, column headers, file names, enum values, labels.**
- Why: `AGENTS.md` required the URL "exactly" even though it looked mistyped.
- Evidence: `AGENTS.md` section 4.1 (four `w` in the host).

**R9. MUST ask the user before any deliberate deviation from the contract. Show the cost in score units (steps, points) and the compliant alternative.**
After approval: record the user's words in the log, DECISIONS and README. Look for the compliant alternative first; often the honest loss is small.
- Why: P4 and P6. A deviation without user approval is a governance failure, and with approval it is still a visible deduction.
- Evidence: LOG 22:33: the user picked the AI-labelled "(Recommended)" option; PANEL still deducted.

**R10. MUST put a scope gate first: decide whether the input is in scope before any other work.**
Handle other languages, negation ("do not delete my account"), and requests for access, correction, export or opt-out. Treat text inside inputs and evidence as data, never as instructions.
- Why: out-of-scope rows are a safety test; one wrong action there is expensive. Prompt injection is part of edition-1 test data.
- Evidence: NOTES section 1 (tickets "curated with edge cases, prompt injection, and jailbreaking attempts"); ANALYSIS section 7: 10 non-deletion requests, 6 contained negated "delete/erase/remove/close", so a keyword classifier fails; BENCH section 3 safety 90.
- Example (Ghost Data): `NOT_APPLICABLE` with `steps_json=[]` for a non-deletion request.

---

## B. Secrets and PII (including caches)

**R11. MUST load secrets from environment variables or an uncommitted `.env`. Create `.gitignore` (with `.env`) and `.env.example` (names only) before the first commit.**
- Why: `AGENTS.md` and the code rubric ("secrets handled via env").
- Evidence: NOTES section 3 (engineering rigor); LOG 3157 (key checked without printing it, file permissions set to 600).

**R12. MUST validate the key and model access in hour 0 with a free call (list models) and one tiny test call.**
- Why: last time the key arrived about 1h45 after implementation began (LOG 17:08 start, user note 18:54), which blocked every live check.
- Evidence: LOG 18:54 and 3157 entries.

**R13. MUST NOT print, log, commit, zip or paste secrets into any prompt. Add a secret-pattern scan to the log linter and the packager.**
- Why: a leaked key can disqualify. A scan is cheap.
- Evidence: `check_log.py` linted secrets (LOG T31 entries).

**R14. MUST treat anything the task calls personal data as PII in every artefact: logs, caches, diagnostics, reports, test fixtures.**
Use ids (`case_12`) or hashes in text, never the raw identifier. Never write an identifier inside a note, even as an argument of a hash.
- Why: a deletion-audit product that leaks personal data in its own files contradicts itself.
- Evidence: PANEL (transcript): the `verify:T03` log entry contained a full dataset email inside `sha256(...)`. The rc4 verifier also found dataset-derived emails or phones in 10 shipped test files (LOG 2026-10-25T01:17Z); use synthetic identifiers in fixtures.

**R15. MUST redact a model cache at write time, not later, whenever the model reads PII (images, PDFs, request text). Test that no email or phone pattern remains in anything that will be zipped, including `tests/` fixtures.**
- Why: a cache is a data store.
- Evidence: PANEL (rules, minor 0.25): the zip shipped 843 cached responses and ten held names and emails taken from images and PDFs. Fixed late: all 15 media entries were redacted at rest and live writes too (DECISIONS D25; MANIFEST).

**R16. SHOULD decide at hour 0 whether a cache ships in the zip.**
A shipped cache makes the final run replayable (0 live tokens) but hides real spend. The usage report MUST then say which tokens were live and which were replayed.
- Why: the usage report must describe "the final full-dataset run".
- Evidence: our `usage_report.md` section 2: the final run replayed the cache and used 0 live tokens; the billed usage was reported as "replayed".

**R17. SHOULD send only the fields the model call needs (for example the request text, not the whole identity row).**
- Why: less PII exposure, fewer tokens, less prompt-injection surface.
- Evidence: usage report: intent calls held request texts only.

---

## C. API and model usage

**R18. MUST check the current model list, prices, removed parameters, limits and SDK requirements at hour 0 (use the `claude-api` skill or the official docs). Do not trust memory.**
- Why: the API changed between editions; wrong assumptions cost hours.
- Evidence: LOG 103 (facts verified: model ids, prices, "no sampling params since 2026-10-21", SDK needs Python 3.10, structured outputs, caching minimum, batch discount).

**R19. MUST NOT send `temperature`, `top_p` or `top_k` to a model that rejects them.**
For the models used in October 2026 the API returned an error. Get stable output from structured outputs, a fixed `max_tokens`, an explicit effort level, a cache, and a validator. Add a unit test on the built request body and a static scan of the source. Re-check this rule against the docs at hour 0.
- Why: it breaks every live call at once.
- Evidence: DECISIONS D6; tests in `test_llm_cache`, `test_live_toolchain`, `test_static`.

**R20. MUST read model ids and prices from one config module, with a command-line or env override. No model id inside a call site or a prompt.**
- Why: models change, and the user may ban or choose models mid-build.
- Evidence: DECISIONS D5 (`DEFAULT_PRICES`, `--intent-model`, `--media-model`); LOG 1141-1144 (a model the user banned had to be removed from a running workflow).

**R21. MUST use structured output (JSON schema in the request) and validate the reply again in code. On refusal, `max_tokens` stop, bad JSON or schema failure: raise a typed error, retry within a limit, then use the rule-based fallback.**
- Why: robustness is 25% of the code score and "output validation" is named in the rubric.
- Evidence: DECISIONS D6; NOTES section 8 ("fixed output schemas, citation validation, retries, fallbacks").

**R22. MUST set `max_tokens`, a timeout, a retry limit with backoff for 429 and 5xx, and a bounded concurrency pool on every model client. The numbers live in one table: `GUARDRAILS_AND_EDGE_CASES.md` section 1.1.**
- Why: unbounded retries and calls are a robustness defect and a cost risk.
- Evidence: LOG T10 entry (429/5xx retries, serial warm-up then bounded pool).

**R23. SHOULD cache the static system prompt and tool definitions (prompt caching), and keep the variable part last. Check the minimum cacheable length in the docs.**
- Why: lower input cost on repeated calls.
- Evidence: DECISIONS D6 (system prompt with `cache_control`); LOG 103 recorded a 512-token minimum for that setup.

**R24. SHOULD choose the cheapest model that passes the same evaluation, per role. A more expensive default needs a recorded user decision.**
- Why: three code-panel personas questioned an expensive default.
- Evidence: PANEL: Haiku for intent matched Opus on all 32 samples and all 518 rows at under half the cold cost (DECISIONS D5), but Opus stayed the default. About 0.25 to 0.5 point was deducted by each persona.

**R25. MUST count tokens and cost in the model client from day 1 (calls, input, output, cache read and write tokens, per role, live vs replayed). Generate `usage_report.md` from that meter. Never type a number by hand.**
- Why: `AGENTS.md` requires per-model and per-request totals and cost.
- Evidence: `meter.json` fed `render_reports.py`, whose `--check` recomputes totals, averages and cost from tokens and prices. A seeded defect in the usage tables was caught by the panel (PANEL calibration).

**R26. MUST check the language runtime against the SDK requirement in hour 0, pin versions, and make the offline path work without the SDK.**
- Why: the machine had Python 3.9.6 while the SDK needed 3.10. Both facts were known in planning (LOG 15:39, 16:19), and the plan chose a 3.9 stdlib core plus a separate 3.12 live toolchain: a split design and an extra task (T36).
- Evidence: DECISIONS D7; LOG 167 and T36 entries (installed `uv` and Python 3.12 in a venv; `requirements.txt` with a version marker).

---

## D. Agent core, robustness, code quality

**R27. MUST include a model-driven loop for the hard, ambiguous decisions.**
The model chooses which tool to call next. The loop has: tool schemas, a maximum number of iterations, a token or step budget, a deterministic stop, and a log line per tool call.
- Why: "Agent architecture" is 30% of the code score: "Is this an agent, or a hardcoded workflow with LLM calls?"
- Evidence: BENCH code: agent architecture 25 to 30 of 100 ("no tool-calling loop, no model-driven routing, no multi-agent handoffs, no planner or critic"). NOTES section 8: single agent with tools or RAG led the leaderboard.
- Example (Ghost Data): tools `resolve_identity`, `search_evidence`, `list_activity`, `get_resource_state`; the model investigates ambiguous or low-confidence cases; code builds the final rows.

**R28. MUST keep a deterministic gate that the model cannot override.**
Gate checks: schema, allowed values, time cutoff, citation exists and is admissible, status consistent with steps. The model may abstain or escalate, never downgrade a hard-rule result. Abstain and fallback are not a blanket policy: their rates have a cap and a test (`GUARDRAILS_AND_EDGE_CASES.md` section 1.3).
- Why: top systems "combined rules with LLM reasoning"; the safe pattern is "the LLM cannot downgrade a high-risk case".
- Evidence: NOTES sections 6 and 8.

**R29. MUST give the model a real, measurable job and prove it with an ablation (model on vs off).**
If the model changes nothing, the "AI" part looks cosmetic to the judge.
- Why: interview question 1 is "what is AI about this, and what does the model decide?"
- Evidence: BENCH section 5: the model changed 0 intent decisions (lexicon and model disagreed on 0 of 550 texts); its measurable value was on 15 images and PDFs only. Ablation S0 vs S1 was in the evaluation report.

**R30. MUST write each prompt as a versioned file with: role, task, input description, constraints, output schema, refusal and abstain conditions, an injection warning (inputs are untrusted data), and 2 to 3 short examples when they are cheap.**
- Why: "Prompt and tool craft" is 30% of the code score ("role assignment, constraint setting, structured output, refusal conditions").
- Evidence: NOTES section 3. BENCH prompt craft about 70: only two narrow prompts, thin abstention rules, no policy for adversarial media, no reasoning or verification prompt.

**R31. MUST write each tool description like documentation: what it does, when to use it, when not to, argument meanings, return shape, size limits, error cases.**
- Why: tool descriptions are scored with the prompts, and good ones cut wasted calls and tokens.
- Evidence: BENCH: "no tool definitions or tool descriptions exist at all".

**R32. SHOULD add a separate verifier or critic step only if it has a distinct job (for example re-check citations and time rules on an INCOMPLETE answer). Keep handoffs narrow and typed.**
- Why: multi-agent helped in edition 1 only "when the extra agents created a real separation of responsibility".
- Evidence: NOTES section 8; BENCH gap "no planner, critic or verifier stage".

**R33. MUST validate the whole output with a contract validator before writing a file. A case that fails still gets a valid fallback row. Never write a partly invalid file.**
- Why: `AGENTS.md` requires exactly one valid row per case.
- Evidence: contract validator exited clean on the final file (MANIFEST gate R1).

**R34. MUST NOT abort the run on an unknown row, file, language or shape. Classify it as UNKNOWN, count it, warn once per shape, and continue.**
- Why: hidden data will contain shapes the samples do not.
- Evidence: PANEL (quality, minor 0.5): one unmatched activity row raised `UnclassifiedActivityError`; fixed in rc4 (MANIFEST).

**R35. MUST make the run deterministic: sorted iteration, fixed JSON separators and key order, no clock, no random value, no set-order dependence. Test a rerun under different `PYTHONHASHSEED` values for byte equality.**
- Why: reproducibility is checked by judges and by your own release gate.
- Evidence: DECISIONS D1 (two runs under different seeds were byte-identical).

**R36. MUST install the code as a package (`pyproject.toml`) or give a single documented entry point. No `sys.path` edits.**
- Why: engineering rigor is 15% and looks at structure.
- Evidence: BENCH code gap: `main.py` lines 18-20 changed `sys.path`.

**R37. MUST have no dead code or unused modes. A flag in config needs a code path, a test and a measured effect.**
- Why: the rubric says "unused imports don't count"; dead options look like invented features.
- Evidence: BENCH: `Config.LLM_MODES` listed `batch`, the CLI never exposed it and no client existed (DECISIONS D13 said "considered and not built").

**R38. SHOULD keep the number of behaviour flags at five or fewer. Every flag needs a one-line reason and its measured effect in the evaluation report.**
(Five is a team convention, not a measured number.)
- Why: more flags mean more interview risk and more panel deductions.
- Evidence: PANEL (quality): "ten inference flags, a fixed-point link solver, a handcrafted-sources path".

**R39. MUST give every constant a name, one home (`config.py`) and a source comment (statement line, run-time statistic, or user decision id).**
- Why: unexplained constants are a named panel deduction.
- Evidence: PANEL (quality): "some constants have no stated source".

**R40. SHOULD use type hints everywhere, one concern per module, functions short enough to read in one screen, and tests beside each module. Target: no function over 40 lines, median about 10 lines. (Convention; this is the one function-size number for the whole playbook.)**
- Why: "multi-file modularity, type hints, function size" is the engineering-rigor rubric.
- Evidence: NOTES section 3; BENCH rigor about 90 (this part was already good: 883 tests).

---

## E. Evidence and honesty

**R41. MUST cite only inputs that exist, are allowed at that time, and prove the fact. A citation validator checks existence and time window for every row.**
- Why: "a finding must use the participant-visible id that proves it".
- Evidence: BENCH section 3: 1,215 citations, 0 after `audit_at`.

**R42. MUST omit a fact whose evidence is missing. Never output a placeholder id or guess.**
Count the omissions in a diagnostics file.
- Why: a wrong id counts as a wrong record and looks like fabrication.
- Evidence: SCORING O10 and ANALYSIS section 7: about 84 eval cases had no findable audit id; "accept the loss; never invent ids".

**R43. MUST NOT accept a status, log message or earlier answer as proof of a state. Reconstruct state from primary evidence.**
- Why: the whole task family tests "claims versus evidence".
- Evidence: ANALYSIS section 1 (`reported_status` and activity results were deliberately wrong in samples).

**R44. MUST generate every number and table in README and reports from run artefacts by script, with a `--check` mode that fails on drift.**
- Why: hand-typed numbers drift and are a fabrication risk.
- Evidence: `render_reports.py --check` (LOG T35 entry); the PANEL seeded-defect test showed that wrong numbers are caught only when a check exists.

**R45. MUST write a DECISIONS file as you go, from H3, using the template in `DEVELOPMENT_STRATEGY.md` section 4. Use "I chose / I rejected / we measured and reverted".**
- Why: this file is your interview script. Pattern 4 in the interview rubric: speak in your own decisions.
- Evidence: NOTES section 6; DECISIONS D1 to D25 became the interview source.

**R46. MUST list limitations and open risks in the README in plain words, including AI assistance and what was only tested in-sample.**
- Why: honesty and self-awareness is 15% of the interview; fabrication is penalised.
- Evidence: README sections "Limitations and disclosures" and EVR section 8.

---

## F. Evaluation

**R47. MUST build the contract validator and the scorer before the solver (first 3 hours), using the sample answers. Report all metrics the statement asks for: case-level status accuracy, step-level, field-level and sequence accuracy.**
- Why: iteration against samples is what top Claude Code users did; `AGENTS.md` also requires these metrics in the report.
- Evidence: NOTES section 8; our graders G1 to G8 (EVR section 1).

**R48. MUST decide the small-sample policy before tuning (`EVALUATION_STRATEGY.md` section 3.3). Hold out labelled samples only if enough remain to fit the rules; otherwise use hand-written custom cases plus an independent labeller (a fresh agent that sees only the statement and raw inputs) on a random sample of unlabeled rows.**
Report development numbers and held-out numbers separately. Never call development numbers "accuracy".
- Why: all three code personas deducted "in-sample only".
- Evidence: PANEL (all three); EVR section 1 ("32 cases leave nothing to hold out once the rules are fitted"). The targeted blind audit of 61 cases confirmed 12 real defects (AUDIT), proving the method finds errors, but no unbiased sample of 100 was drawn and the gate was waived (MANIFEST R4).

**R49. MUST write at least one custom case per edge class, run them in the test suite, and describe them in the evaluation report.**
`AGENTS.md` asks for at least three. Target: 8 (our 7 classes plus injection, unknown row and missing evidence, merged where one case covers two). This is the one custom-case number for the whole playbook.
- Why: required by the statement, and edge-class awareness is 15% of the transcript score.
- Evidence: EVR section 6, cases C1 to C7 (historical email in upper case, non-English negated request, time travel, tombstone with legal hold, active connector, look-alike email, one user with two requests).

**R50. MUST test every rule family that no sample covers, with a hand-made case that includes a decoy and a post-cutoff trap.**
- Why: untested families can flip statuses silently.
- Evidence: BENCH section 3 gaps: no sample covered NOT_APPLICABLE, legal hold, object storage or marketing data; about 140 "untested rules fired" in diagnostics.

**R51. MUST run label-free invariant checks on the unlabeled set: every citation inside its window, every operation and state pair allowed, status consistent with steps, counts per status, byte-identical rerun.**
- Why: they catch most structural bugs without labels.
- Evidence: label-free verifier reported 0 hard failures (BENCH section 5).

**R52. MUST ablate every flag and every model role (on vs off, with rows changed, steps changed, statuses changed).**
- Why: ablations produce the best interview answers and the best report.
- Evidence: final ablations (EVR section 4): signature off changes 85 rows; late ids off removes one step from each of 124 rows (sample exact 30 to 25); FIFO off 28 rows. NOTES section 9 item 7. (Planning estimates were 95 rows and 116 steps, SCORING O1 and O4.)

**R53. SHOULD rank remaining losses by points per item and fix the biggest first.**
- Why: short answers carry the largest loss per missing step.
- Evidence: BENCH `improve`: 12 short COMPLETE rows lacked the account step ("biggest loss per item"); about 83 INCOMPLETE rows lacked one audit step.

**R54. MUST keep the evaluation report's failures-and-fixes section honest and specific: name the failing case, the cause, the fix, the number before and after.**
- Why: the same text proves "iteration and verification" in the interview.
- Evidence: EVR section 7.
- If the new problem has a free-text justification field: make it specific and consistent with the status; edition 1 capped a correct answer with a generic or contradictory justification at about 70 (NOTES section 4).

---

## G. Logging and transcript

**R55. MUST follow the logging format in `AGENTS.md` exactly: session-start entry and greeting, then one entry per user turn with verbatim prompt, 2 to 5 sentence summary, actions, and a complete Context block (`tool=`, `model=`, branch, repo root, worktree, parent agent).**
- Why: half of the edition-1 transcripts failed on the Context block and chat is 10% of the score.
- Evidence: NOTES section 5 (658 of 1,349 clean); BENCH section 4: format was perfect (183 entries, all valid).

**R56. MUST build the log tools in the first hour, before solver code: `append_log` (lock, append-only, lint before and after) and `check_log` (format, summary length, secrets, timestamps, sub-agent coverage).**
- Why: manual logging fails under pressure; a linter keeps every entry valid.
- Evidence: LOG 185-255 (built and tested early).

**R57. MUST NOT rewrite, delete, back-date or reconstruct log entries. Write each entry at the time of the turn, through the script (R56). If the user asks to keep a prompt out of the log, record only its hash in an exclusions list and say so in the next entry.**
- Why: `AGENTS.md` says append-only; the user's own instruction wins, but it must stay traceable. Edition 1 cut the chat weight to 10% partly because of "signs of manipulation on the chat transcript", so a log that looks edited after the fact is a risk.
- Evidence: NOTES section 2; `devtools/log_exclusions.txt` (six prompts kept out at the user's request, hashes only, no reason recorded).

**R58. MUST log every sub-agent run, and the parent MUST have a turn entry for the user prompt that launched it. Group many sub-agent runs under one index entry per workflow (run id, task ids, models, agent count, outcome). Keep every summary to five sentences. A sub-agent entry starts its prompt block with "Task relayed by orchestrator (not typed by the user):". Never paste agent output into the log as if it were conversation.**
- Why: broken traceability and long summaries were the remaining transcript deductions.
- Evidence: PANEL (transcript 9 of 10): rc3 apply and verify entries had no matching main-session turn entry; one summary had six sentences. 13 index entries had to be added late to cover every id (LOG 00:40). BENCH section 4: abridged sub-agent task text sat under "User Prompt (verbatim)". NOTES section 5: pasted outputs are the weakest transcript pattern.

**R59. MUST log the result of every workflow (numbers, decisions, failures, and any change nobody asked for) in the same turn that reads it.**
- Why: an unlogged result leaves the loop open.
- Evidence: BENCH section 4: the final audit/freeze workflow "has no logged result". The good pattern: LOG 00:37 reported a close-out step's unrequested changes, and the user decided at 00:54.

**R60. SHOULD keep status questions out of the log: write `PROGRESS.md` (task, state, next step) and point to it.**
- Why: 4 to 7 of 22 user turns were status checks; they add no direction.
- Evidence: BENCH section 4 (lines 1886, 1952, 3154, 3198, 3240, 3528, 4044).

**R61. SHOULD NOT re-log a verification that did not change. After a stop and resume, reuse cached results and do not run the same check again.**
- Why: T02b, T20, T02 and T10 were each logged three or four times, which hid the real story.
- Evidence: BENCH section 4 (T02b at log lines 366, 457, 1159, 1272, 1969).

**R62. MUST write user prompts as specific engineering instructions. Include: file paths, schema names, thresholds, model names, exact failing case ids, metric before and after, constraints, and a regression check.**
- Why: technical specificity is 25% of the transcript score; direction is 35%.
- Evidence: BENCH section 4: no user prompt named a schema, threshold, library or failing row. Weak examples: "Simplify the code as much as possible", "THINK AND SEE IF YOU COULD ENHANCE", "Go ahead".
- Example (Ghost Data) of a strong prompt: "case_18 misses `VERIFY_RECORD_PRESENT` for the audit record. Search all files captured at or before `audit_at` for `user_18` and the old email hash. Do not use later files. Re-run the 32 samples and show exact-match before and after; any status change is a regression."

**R63. MUST state architecture and tradeoffs in the user's own words before the build starts: what is deterministic, what the model decides, how the loop is bounded, what the failure fallbacks are. The agent may draft; the user must edit and approve in writing.**
- Why: "the SOLUTION architecture is fully delegated" was the first transcript gap.
- Evidence: BENCH section 4 (direction 61/62): the deterministic pipeline, linking and signature all came from AI-written specs.

**R64. MUST raise edge cases in the user's own prompts: other languages, non-actionable requests, prompt injection in inputs, decoys, late evidence, ambiguous data, sensitive records.**
- Why: safety and edge-case awareness is 15% of the transcript score.
- Evidence: BENCH section 4 (score 55): edge cases came from the AI, none from the user.

**R65. MUST show the user inspecting results: paste an error, name a failing row, quote a metric, ask for a targeted fix. Do not delegate all inspection to sub-agents.**
- Why: "iteration and verification" is 25%.
- Evidence: BENCH section 4: "the user never personally shares an error, pastes a failing row or inspects sample output".

---

## H. Agent governance and sub-agent delegation

**R66. MUST NOT let a sub-agent or workflow step change a default, flag, model, threshold, scope item, gate or user decision without the user's approval. It reports a proposal instead.**
Put this sentence in every sub-agent prompt. After each sub-agent, diff the defaults.
- Why: a close-out step silently changed two defaults and contradicted the user's decision; the user had to decide again and a fix run was needed.
- Evidence: LOG 00:37:29 entry ("The close-out step made two changes without user approval"); LOG 00:54 user decisions; rc3 apply entry.

**R67. MUST pin all user decisions in a test (a "defaults ledger"): the test fails if a default differs from the recorded decision.**
- Why: turns R66 from a promise into a check.
- Evidence: the override-ban gate (static scan, relabeling test, late-evidence test; release gate R10) was the heavy version; a short test of pinned defaults is enough.

**R68. MUST encode the user's model policy as an allowlist in the workflow script. A banned model must not appear anywhere in the script.**
- Why: a running workflow was still using a model the user had banned until the script was edited.
- Evidence: LOG 17:48 (user: "do not use fable model; use only Opus 5.5 for rework").

**R69. MUST ask decisions as short questions with a number for each option's cost (steps, points, minutes, dollars). One decision per question. Do not label an option "(Recommended)" for architecture or contract decisions; state the tradeoff and ask the user to answer in their own words.**
- Why: "(Recommended)" invites rubber-stamping, which the transcript judge scored as no direction.
- Evidence: BENCH section 4: two decisions picked "(Recommended)" options verbatim.

**R70. MUST write each sub-agent task with: goal, files it owns (no overlap), inputs, acceptance command, forbidden actions, output format, size limit.**
- Why: ownership and clear acceptance avoid rework and merge conflicts.
- Evidence: LOG 578 ("own only `records.py` and `test_records.py`").

**R71. MUST require short structured returns from sub-agents (status, files changed, test result, one-line risks). Do not paste file contents back.**
- Why: return text is parent context; long returns waste tokens.
- Evidence: LOG: sub-agent runs totalled about 9.5M tokens across finished workflows (`/usage` entry), so return size and re-reads matter.

**R72. MUST verify a sub-agent's claim with a command (tests, grep, a diff). Do not trust the report.**
- Why: reports were wrong at times.
- Evidence: LOG 210: a verifier "found `code/tools/__init__.py` missing despite the implementer report".

**R73. SHOULD pick the model tier by task: a small model for mechanical tasks (boilerplate, parsers with tests), a mid model for implementation, the strongest model for ambiguous design, rework and final review. A script (tests) verifies first; a model verifies only what tests cannot.**
- Why: the same verification was paid for several times.
- Evidence: user instruction at LOG 17:08 (Sonnet implement, Haiku simple, Opus verify and rework); later the user asked for one combined verification for speed (LOG 19:10), which then rejected 6 of 15 tasks. So: run cheap per-task tests first, one strong review per batch.

**R74. MUST set the model policy and verify policy BEFORE launching a long workflow. Stopping and resuming to change them re-runs and re-verifies tasks.**
- Why: stop and resume was used at least twice.
- Evidence: LOG 17:48, 17:56, 17:58 entries.

**R75. MUST run independent tasks in parallel and give each shared file one owner.**
- Why: faster build with fewer conflicts.
- Evidence: plan DAG of 46 tasks (`plan/tasks/README.md`).

**R76. MUST report the token spend of each workflow when it finishes and compare it with a budget set at launch.**
- Why: build cost far exceeded run cost; nobody was watching.
- Evidence: LOG `/usage` entry: about 9.5M sub-agent tokens at that point, with stopped runs uncounted; the product run itself was 31 calls and 196,870 tokens (BENCH section 5).

---

## I. Time and workflow

**R77. MUST run the hour-0 checklist before any design work:**
read the statement and `AGENTS.md` (R1); session-start log entry and greeting (R55); log tools (R56); key and model access (R12); runtime vs SDK versions (R26); API facts (R18); repo skeleton with `.gitignore` (R11); contract validator and scorer skeleton (R47).
- Why: last time the key came 1h46 after implementation began, and the version and API checks happened during planning (after the spec was drafted), so the plan had to absorb them.
- Evidence: LOG 15:39 (Python 3.9.6 noted while writing the plan), 16:19 (API facts), 17:08 (environment check: no key), 18:54 (key).

**R78. MUST have a valid, submittable `output.csv` from the first end-to-end run (hour 3 to 4) and update it after each measured gain.**
- Why: with a single submission and no feedback, an early valid file is insurance.
- Evidence: single-submission rule in the user's prompt (LOG 16:39).

**R79. SHOULD keep the plan small: one spec page, one task checklist of at most 15 tasks, each with one owner directory and an acceptance command. (Convention; this is the one task-count number for the whole playbook.)**
- Why: last time the plan was 3,653 lines with 46 task files (2,242 lines) and four recorded review rounds, all written before the implementation prompt.
- Evidence: PLAN (files last changed at 16:39 UTC); LOG 15:39 (33 tasks), 16:19 (35), 16:39 (46), 17:08 (implementation starts, 42 tasks in the first workflow, 4 deferred).

**R80. MUST freeze features about four hours before the deadline. After the freeze: only measured defect fixes, report generation, packaging, clean-room run, interview prep.**
- Why: late default changes produced the rc2 to rc4 churn.
- Evidence: MANIFEST (rc4); PANEL (rc2 to rc3 changes).

**R81. SHOULD keep release tooling to one script with exactly three automated checks, outside the zip: (1) contract validator plus a byte-identical rerun under two hash seeds; (2) zip scan for forbidden files, secret patterns and PII patterns, including `tests/`; (3) clean-room run of the README commands in an empty folder. Everything else is a manual line in section K. Record any skipped check with a reason. (This is the one release-check number for the whole playbook.)**
- Why: heavy gates (twelve gates, judge panels, a clean-room matrix; one audit and panel workflow ran 49 agents) still ended with two gates waived.
- Evidence: MANIFEST (R4 and R9 waived); `devtools/` holds about 2.4k lines of Python, about 4.3k with tests (`wc -l`).

**R82. MUST protect the interview with one schedule: keep the first-person decision ledger (R45) from H3; draft the prep guide at the freeze (about H21) from DECISIONS and the evaluation report; spend the last 2 hours on a code walk-through and one timed spoken rehearsal. Be able to trace one case end to end by hand. Content to prepare: `RUBRIC_PLAYBOOK.md` section 4.2.**
The interview weighs more than output or code alone in the tie-break order (interview, then code, then output, then chat).
- Why: code familiarity was the weakest ownership signal when sub-agents wrote most code.
- Evidence: NOTES section 2 (tie-break) and section 6; BENCH section 5 `improve`.

---

## J. Packaging and release

**R83. MUST ship in `code.zip` only: source, prompts, config, README, tests, and `evaluation/evaluation_report.md` and `evaluation/usage_report.md`. Exclude: the dataset, virtual environments, caches containing PII, nested archives, keys, dev tooling, planning folders.**
- Why: `AGENTS.md` section 6.9; extra bulk also dilutes the code review.
- Evidence: SCORING: the judge reads README, source, prompts and Markdown; `plan/` is not in the zip. Release tooling was moved out of the zip.

**R84. MUST build the zip by script with a fixed file order and a package listing check. Fail the build on a forbidden file, a secret pattern or a PII pattern anywhere in the zip, `tests/` included.**
- Why: reproducible archive, no manual mistakes.
- Evidence: `code/tools/build_zip.py`; manifest hashes (MANIFEST).

**R85. MUST run a clean-room check: unzip into an empty folder, follow only the README commands, run on the full dataset, and compare `output.csv` byte for byte. Also run once without the dataset folder and confirm a clear error, not a crash trace.**
- Why: "a clean run can process all rows" is a stated requirement.
- Evidence: gate R8 passed (MANIFEST).

**R86. MUST test every command written in the README (setup, run, evaluate). The README MUST state Python and package versions, environment variables, and expected run time.**
- Why: the panel seeded a wrong command and a missing-numbers defect; both were found, which proves reviewers try the commands.
- Evidence: PANEL calibration.

**R87. MUST write the deliverable files where the statement says, and if two documents disagree, satisfy both when it is cheap (for example keep the reports under the zip's `evaluation/` and say so in the README).**
- Why: path mismatches can fail automatic checks.
- Evidence: ANALYSIS section 9 (`evaluation/…` in `AGENTS.md` vs `code/evaluation/…` in the README).

**R88. MUST create `output.csv` at the repo root, with exact header, sorted rows, valid serialisation, and run the validator immediately before submission.**
- Why: format errors forfeit output points.
- Evidence: MANIFEST gate R1.

**R89. MUST record the final `output.csv` hash, zip hash and dataset hash in a manifest, and verify the chosen files against it just before upload.**
- Why: one submission only; a stale file is unrecoverable.
- Evidence: MANIFEST; `release_gate.py --verify-upload`.

**R90. MUST NOT commit, tag or push without the user's consent. A waived check needs a written reason that is shown to the user.**
- Why: governance (P6).
- Evidence: MANIFEST ("commits and tags only with the user's consent").

**R91. MUST include the chat transcript (`log.txt`) and any extra trace the event requires, and run the log linter on the exact file being submitted.**
- Why: transcript is a graded signal and half the edition-1 files were invalid.
- Evidence: NOTES section 5; the repo's git history shows the organisers added instructions for trace submission from unlisted harnesses (commit "docs: explain trace submission for unlisted harnesses").

---

## K. Final gate checklist

This is the one release checklist for the whole playbook (the other files link here). Tick every line before upload. Any unticked line needs a written reason shown to the user. The three automated checks of R81 cover the lines marked (auto).

Contract
- [ ] `CONTRACT.md` items all verified (R1). Exact strings copied (R8). Sort order confirmed against the statement and the sample file, and stated in the README (R7).
- [ ] No later-than-cutoff evidence used (R2). No organizer data, no gold at run time (R3).
- [ ] No hardcoded ids, no fitted constants, no artifact exploit, or the user approved and it is disclosed (R4 to R6, R9).
Code
- [ ] A bounded model-driven loop exists and is exercised on real cases (R27). The gate cannot be overridden (R28).
- [ ] Prompts and tool descriptions meet R30 and R31. No dead modes (R37). Constants sourced (R39).
- [ ] No sampling parameters (R19). Model ids from config (R20). Structured output plus validation (R21).
Safety
- [ ] No secrets or PII in log, cache, reports, test fixtures or zip (R11 to R15), scanned by script (auto, R81 check 2).
- [ ] Unknown inputs are counted, not fatal (R34). Output is byte-identical on rerun (R35; auto, R81 check 1).
- [ ] Abstain and fallback rates are under their caps (`GUARDRAILS_AND_EDGE_CASES.md` section 1.3).
Evaluation
- [ ] Validator clean (auto). Report numbers generated with `--check` (R44). Sample scores not below the last run, no grader regressed, and called development-set numbers (R47, R48).
- [ ] Label-free invariants: 0 hard failures, every warning explained (R51).
- [ ] Custom cases pass, including injection, unknown row and missing evidence (R49, R50). Ablations current (R52). One targeted audit run, fixes general (`EVALUATION_STRATEGY.md` section 7).
- [ ] The M3 judge panel ran and every top gap is fixed or written in the report (`EVALUATION_STRATEGY.md` section 6).
- [ ] Usage report generated from the meter and describes the final full-dataset run; live vs replayed stated (R16, R25).
Process
- [ ] Log valid (linter on the exact file to submit), sub-agents traced, results logged (R55 to R59, R91). User prompts specific (R62 to R65).
- [ ] No sub-agent changed a default; defaults ledger test passes (R66, R67).
Release
- [ ] Zip contents checked (R83, R84). Clean-room run identical (R85; auto, R81 check 3). README commands tested (R86).
- [ ] Manifest hashes of `output.csv` and the zip verified against the files to upload (R89).
- [ ] Interview prep guide drafted, one case traced by hand, one spoken rehearsal done (R82).
