# Implementation Plan Review: Critical Assessment of `IMPLEMENTATION_PLAN.md` v1.0

Each finding records what was wrong or risky, how severe it is, and how v1.1 or the tasks address it. Severity is **H**, **M** or **L**.

## 1. Findings and adjustments

| # | Sev | Finding | Adjustment | Where |
|---|---|---|---|---|
| P1 | H | v1.0 proposed a "parity check against the notes TSV/JSON" inside T12. That would make shipped code read `solution/`, which breaks N3 isolation and the static test. | Parity checks become a **manual dev script kept outside `code/`** (e.g. `plan/tools/` or the scratchpad), never shipped. T12's acceptance uses dataset-derived counts instead. | T12 |
| P2 | H | Turning the fingerprint off weakens worker-row linking as well as account linking: compliant-row windows of neighbouring accounts overlap inside a batch. | ⟲ Worker rows are anchored on `reported_at` (SPEC L3). Never-mix runs before FIFO. The count of unresolved ambiguous rows is a tracked KPI, target ≤ 20 in eval. | T13, T14, T26 |
| P3 | M | It was unclear whether linking may use sample requests. | ⟲ Stated explicitly: sample **requests** are participant inputs and improve elimination. Sample **outputs** are read only by `evaluation/` and `tests/`, enforced by the DatasetReader allowlist. | T02, T13 |
| P4 | M | The intake N rows are activity claims, so using them to decide NOT_APPLICABLE would contradict SPEC §4. | ⟲ The text decides (guard + LLM). N rows corroborate only and are logged. | T19 |
| P5 | M | The live LLM path had no resilience: no timeouts, retries or back-pressure, and a crash mid-write could corrupt the cache. | ⟲ 60 s timeout, 3 retries with backoff on 429/5xx, ≤ 8 workers, atomic cache writes (temp file + `os.replace`). | T10 |
| P6 | M | The model ids and prices would have been typed from memory. | ⟲ They live in `Config`. T10 and T28 require verifying them via the `claude-api` skill and recording the source in `usage_report.md`. | T10, T28 |
| P7 | M | Media relied on timing (LINK row = captured_at + 7m01s), which is a generator artifact. | ⟲ The join uses the **alias** in the LINK details plus the extracted display id. Timing is never used. | T11a |
| P8 | M | A golden test that reads `sample_output.csv` sitting next to pipeline code risks gold leaking into logic. | The round-trip and golden tests live only in `tests/` and `evaluation/`. The pipeline cannot open gold (`ForbiddenInputError`), and a static test checks imports. | T02, T24, T27 |
| P9 | M | "Sorted by case_id" was ambiguous. | ⟲ Natural numeric order, matching the input file (verified). | T20 |
| P10 | L | Per-case diagnostics could grow large and slow down the run. | Diagnostics are written once at the end with a buffered writer, and are optional (`--diag`). | T21 |
| P11 | L | Without a `.gitignore`, `.env` and caches might be committed by accident. | Add `.gitignore` entries for `.env`, `__pycache__/` and `*.pyc`. The LLM cache is intentionally committed and contains no secrets. | T30 |
| P12 | L | Packaging could pull in `solution/` or `plan/`. | The zip command includes only `README.md` and `code/`. A checklist script verifies the zip contents. | T30 |
| P13 | L | 30+ tasks may be too many for a hackathon pace. | Tasks are sized S/M/L and ordered by critical path. M5 and M6 can shrink if time runs short, but T22 (validator) and T28/T29 (reports) are mandatory. | tasks/README |

## 2. Risk register (owner task and measurement)

| Risk | Description | Owner | Measured by |
|---|---|---|---|
| R1 | Fingerprint off reduces linking | T14 | Ablation: unique links, sample exact count, eval status flips |
| R2 | `account_00N` convention | T18b | Diagnostics count (expected 1 sample + 3 eval) |
| R3 | Legal-hold verify | T18a | Ablation row (expected ~10 steps) |
| R4 | Missing audit ids | T15/T18a | Coverage buckets: in-window / late / none |
| R5 | Media extraction | T11a/T11b | 12/12 alias validations; per-case predictions |
| R6 | Template vs evidence disagreement | T17 | Disagreement counter (expected ~0) |
| R7 | Window constants overfit | T13/T26 | ±10 min sensitivity sweep |
| R8 | Same user in several cases | T18a/T18b/T25 | Custom case C7 |
| R9 | Absence-by-omission file choice | T17 | Count of `basis=omission` (expected ~57) |
| R10 | Timestamp parsing | T02 | Fixtures for every format |
| R11 | Usage report for a cached run | T10/T28 | Live and replayed tokens shown separately |
| R12 | Packaging and leakage | T27/T30 | Static test plus zip checklist |
| R13 | Intent misclassification | T19 | Agreement matrix of guard vs LLM vs N rows |

## 3. Verdict
Approved for implementation with the adjustments above. Four things stand out:

- **Strongest parts:** grounded data model, pure core, DI'd LLM layer, contract validator, and the ablation harness. Together these make the AI-interview story easy to defend.
- **Weakest part:** worker-row linking without the fingerprint (R1). It is isolated in one module with a KPI and an ablation, so the trade-off can be revisited with data.
- **Explicitly not done:** tuning against eval outputs, inventing ids, and any reliance on `solution/` at runtime.
- **Scope cut:** the plan does not require cosmetic artifacts such as HTML reports or dashboards.

---

# Round 2: independent adversarial review (design reviewer + contract auditor)

Every finding below was verified against the plan text, the tasks and the local toolchain. Fixed in IMPLEMENTATION_PLAN v1.2 and the regenerated tasks (marked ⟲).

| # | Sev | Finding | Adjustment |
|---|---|---|---|
| P14 | H | The toolchain mismatch: 3.11 syntax (`slots`, PEP 604 at runtime) against the local `python3` 3.9.6. `anthropic` is not installed. | Target 3.9. T01 enforces the 3.9-compatible idioms. T10 lists `pip install anthropic==<pinned>` as an explicit prerequisite, needed only for `--llm live`. |
| P15 | M | The import path was undefined: `unittest discover -s code/tests` cannot import `ghostaudit`, and `code/evaluation/main.py` cannot either. | `__init__.py` files in `tests/` and `evaluation/`. The test command is `python3 -m unittest discover -s code/tests -t code`. `evaluation/main.py` inserts `code/` into `sys.path`. T01 smoke-tests both CLIs with `--help`. |
| P16 | M | The LLM sat on the core critical path: T12 depended on T11, which depended on T10. `media.py` imported `llm` (a layering break) and `build_index` did network I/O (a purity break). | T11 is split. **T11a** is a pure `map_facts` over `MediaFacts` with fixtures. **T11b** is the LLM `extract_media_facts` pre-pass run by the pipeline. T12 depends only on T11a. The live cache fill is an explicit scheduled step. |
| P17 | M | `evidence/base.py` and the key normalizer were hidden inside T05, which serialized all parsers behind the SQL work. No task owned the `keyer`, so normalization could diverge from IdentityIndex. | New **T02b**: `keys.py` and `evidence/base.py`. T03 and all parsers import it, and a parity test checks IdentityIndex keys against `keys_from_record`. T05–T08 then run in parallel. |
| P18 | M | V5 (omission citation) needs case-level information, which `StateResolver.resolve(rid, …)` cannot see. | Pure `choose_omission_cite(...)`, called by CaseBuilder after the other verdicts. The interface table is updated. |
| P19 | M | T18 was too large, and its acceptance could only be checked through T24. | Split into **T18a** (generated family; checked via the gold-abstraction helper on 24 samples, with 2 pinned misses) and **T18b** (hand-crafted and media family; 8 samples plus the eval image table). |
| P20 | M | Per-batch intent caching made each decision depend on its 24 batch neighbours: re-batching caused misses, C2 could not pass offline, and dropped ids and prompt injection were not handled. | Per-item cache key, id-set validation, delimiter wrapping, and a FakeLLM in C2 so the test is hermetic. |
| P21 | M | M4 required "validator clean", yet T22 sat in M5, and pipeline would have imported `evaluation` (an upward import). | The validator is now `ghostaudit/contract.py` (T22, moved to M4). T21 depends on T22, and `evaluation/validator.py` re-exports it. |
| P22 | M | The determinism test and others would overwrite the submission `output.csv`. | Every test passes `--out`/`--diag` into temp dirs, and a static check enforces it. |
| P23 | M | The API key in a frozen Config could leak through `repr`, tracebacks or diagnostics. | `Secret` wrapper / `field(repr=False)`, held only by `AnthropicClient`. Tests assert the key is absent from repr, diagnostics, the usage report and logs. |
| P24 | L | The T27 static rules contradicted package_check, the tests and provenance comments. | Static checks are scoped to `ghostaudit/**` and `main.py`, using usage-pattern regexes. |
| P25 | L | Hidden dependencies: GoldReader was needed by T20 before T23 created it; `use_late_audit_ids` and the window offset had no flags. | `tests/gold.py` is created in T20 and reused by T23. Flags are added in T01. |
| P26 | L | package_check only checked absence. The `--include-samples` CLI option, `ablation.py` and `package_check.py` were missing from the tree. | The presence checks (README, main, both reports with their required headings, prompts, ≥ 1 cache file) are in T30 acceptance. The CLI and tree are updated. |
| P27 | L | The critical paths in the plan and the README disagreed and included non-edges. | A single critical path in both documents (plan §9 and tasks/README). |
| P28 | L | Custom case coverage gap: no case for the same user in several cases. | **C7** added to T25. SPEC_REVIEW S15 and R8 now point to it. |
| P29 | L | Wrong facts in task acceptance criteria: tombstone_9178 is **user_542**, not user_32. The evidence_02 description for case_26 was wrong. The intent call count was 22, not ~21. | Corrected in T12, T17 and plan §6. |

Verdict after round 2: approved. The task count goes from 30 to 33 (T02b, T11a/T11b, T18a/T18b replace T11 and T18). No open H items remain.


---

# Round 3: score-maximization pass (`SCORING_STRATEGY.md`)

| # | Sev | Finding | Adjustment (⟲³) |
|---|---|---|---|
| P30 | H | The code judge cannot see `plan/`. Docstrings cite SPEC ids that the zip doesn't contain. | New **T30b**: `code/docs/{SPEC,ARCHITECTURE,DECISIONS}.md`, required by package_check. |
| P31 | H | Shipped code had no strategy comparison or operational analysis; the June edition required both. | T21 adds `--intent-model`, `--media-model` and `--signature`. T26 compares S0/S1/S2 plus signature variants. T10/T28 add cache, image, thinking, RPM/TPM and runtime metrics. |
| P32 | H | The transcript has no tooling. Sub-agent entries are missing (§5.3), and nothing enforces one entry per turn. | New **T31**: `code/tools/append_log.py` and `check_log.py` (with `--trace`, `--baseline-ref`). DoD and Conventions are updated. |
| P33 | M | Prompt caching would silently not apply to prompts under 512 tokens, and no warm-up call was planned. | T19/T11b: system prompts ≥ 600 tokens with `cache_control` and a serial warm-up. Acceptance: cache reads > 0. |
| P34 | M | AGENTS names zip-root `evaluation/`, while README names `code/evaluation/`. | package_check writes and verifies byte-identical copies in both. |
| P35 | M | README quality drives the judge's first impression. | T30: 3-command quickstart, Mermaid diagram, results table, capability map, limitations. |
| P36 | L | A `--llm batch` mode would halve the cost. | Optional; cut first. Considered in DECISIONS.md with the cost math. |

Task count: 33 → 35 (T30b, T31). An execution-priority order (P0–P3) has been added to plan §9.


---

# Round 4: local-evaluation stress test

| # | Sev | Finding | Adjustment (⟲⁴) |
|---|---|---|---|
| P37 | H | The single submission needs measurable, automated gates. | New milestone **M7**: T32–T35, T37–T40, T42, T43 (release gate R1–R12, freeze manifest). |
| P38 | H | No live toolchain: Python 3.9.6 only, and `anthropic` 2.x needs ≥ 3.10. | **T36** in P1: uv-installed Python 3.12, `anthropic==2.3.0` pinned. Remains an SDK path per the claude-api skill. |
| P39 | H | Dual-pipeline agreement would pass trivially: A and B share the linker. | Replaced by T32 label-free verification of every step (locator precision, recall sweep, proof-file coverage, redundancy matrix). |
| P40 | H | A 20-case held-out audit is statistically meaningless. | T39: post-freeze estimation sample of ≥ 100 cases, Clopper–Pearson bound, spec-free calibrated auditors. |
| P41 | M | The regex override ban is too weak. | T42: relabeling, late-evidence injection and narrow-rule review. |
| P42 | M | The zip is non-reproducible; nested archives and `.pyc` files could slip in. | T33 reproducible packager; zip-listing checks. |
| P43 | M | Hand-typed report numbers drift. | T35 `render_reports --check`. |
| P44 | M | README command 2 fails standalone. | T23: the scorer runs the sample pipeline itself. |
| P45 | L | The prototype linker takes 9 s. | Indexed implementation; gate < 30 s, target < 5 s. |

Task count: 35 → 46 (T41 reserved for the mock interview).
