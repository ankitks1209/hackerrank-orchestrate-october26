# Tasks: Ghost Data Still Exists Solver (v1.4)

These are granular, independently verifiable tasks derived from `../IMPLEMENTATION_PLAN.md` v1.4, which implements `../SPEC.md` v1.4. Both have been through three review rounds, the score-maximization pass (`../SCORING_STRATEGY.md`) and the local-evaluation stress test (`../LOCAL_EVALUATION_STRATEGY.md`) (`../SPEC_REVIEW.md`, `../IMPLEMENTATION_PLAN_REVIEW.md`). There is one file per task, all on the template below.

Size: **S** ≤ 1 h · **M** 1–3 h · **L** > 3 h. Total: 46 tasks (21 S, 23 M, 2 L). T41 is reserved for the mock AI-judge interview, planned later.

## Index
| Task | Title | Milestone | Depends on | Size |
|---|---|---|---|---|
| [T01](T01-package-skeleton-config-model.md) | Package skeleton, Config, core model types (Python 3.9+) | M0 | — | S |
| [T02](T02-timeutil-datasetreader-csv-loaders.md) | timeutil, allowlisted DatasetReader, typed CSV loaders | M0 | T01 | S |
| [T02b](T02b-keys-normalizer-evidence-base.md) | Key normalizer (`keys.py`) and evidence parser base | M0 | T01 | S |
| [T03](T03-identity-index.md) | IdentityIndex (current + historical identifiers) | M1 | T02, T02b | S |
| [T04](T04-activity-classifier.md) | Activity template classifier | M1 | T02 | M |
| [T05](T05-sql-parser.md) | SQL evidence parser (topology, inventory, special schemas) | M2 | T02b | M |
| [T06](T06-json-records-parser.md) | JSON records parser (exports, bundles, ledgers, collections) | M2 | T02b | M |
| [T07](T07-handover-txt-parser.md) | TXT handover parser | M2 | T02b | S |
| [T08](T08-log-line-parsers.md) | Log line parsers (8 formats) | M2 | T02b | M |
| [T09](T09-log-trace-join.md) | Log trace join → Observations | M2 | T08 | M |
| [T10](T10-llm-infrastructure.md) | LLM layer: client Protocol, Anthropic client, disk cache, usage meter | M2 | T01 | M |
| [T11a](T11a-media-fact-mapping.md) | Media facts → Observations (pure mapping, path a/b) | M2 | T04, T02b | M |
| [T11b](T11b-media-extraction-llm.md) | Media extraction via LLM vision (pipeline pre-pass) | M2 | T10, T11a, T36 | M |
| [T12](T12-evidence-index.md) | EvidenceIndex + ScopeAssertion store | M2 | T05, T06, T07, T09, T11a, T03 | M |
| [T13](T13-link-candidates.md) | Linking: candidate generation | M3 | T04, T12 | M |
| [T14](T14-link-solver.md) | Linking: fixed-point solver, learned signature and tie-breaks | M3 | T13 | L |
| [T15](T15-link-repopulation-evidence-union.md) | Linking: repopulation flows, evidence-only union, audit records | M3 | T14 | M |
| [T16](T16-policy-engine.md) | PolicyEngine and system/category mapping | M4 | T02 | S |
| [T17](T17-state-resolver-citation.md) | StateResolver, citation and omission citation | M4 | T12, T16 | M |
| [T18a](T18a-case-builder-generated.md) | CaseBuilder: generated family (verdict assembly) | M4 | T15, T17 | M |
| [T18b](T18b-case-builder-handcrafted-media.md) | CaseBuilder: hand-crafted and media families | M4 | T18a, T11a | M |
| [T19](T19-intent-classifier.md) | IntentClassifier (LLM primary + principled lexicon) | M4 | T10, T04 | M |
| [T20](T20-emitter-serializer-writer.md) | Emitter, serializer, output writer, gold helper | M4 | T01 | S |
| [T21](T21-pipeline-cli-diagnostics.md) | Pipeline orchestration, CLI, diagnostics | M4 | T18b, T19, T20, T22, T11b | S |
| [T22](T22-contract-validator.md) | Output contract validator (`ghostaudit/contract.py`) | M4 | T20 | S |
| [T23](T23-scorer.md) | Scorer metrics and evaluation CLI | M5 | T22, T20 | M |
| [T24](T24-golden-gate.md) | Golden sample regression gate | M5 | T21, T23 | S |
| [T25](T25-custom-cases.md) | Custom synthetic evaluation cases C1–C7 | M5 | T21 | M |
| [T26](T26-ablations.md) | Strategy comparison, ablation harness and assumption ledger | M5 | T24 | M |
| [T27](T27-determinism-performance-static.md) | Determinism, performance and static-isolation tests | M5 | T21 | S |
| [T28](T28-final-run-usage-report.md) | Final live run, offline rerun, usage_report.md | M6 | T21, T19, T11b, T36, T35 | S |
| [T29](T29-evaluation-report.md) | evaluation_report.md | M6 | T23, T24, T25, T26, T35, T39, T40 | M |
| [T30](T30-readme-packaging.md) | README, packaging check and dual report placement | M6 | T28, T29, T30b, T31, T33 | S |
| [T30b](T30b-shipped-design-docs.md) | Shipped design docs: SPEC, ARCHITECTURE, DECISIONS | M6 | T21 | S |
| [T31](T31-log-tooling.md) | Transcript tooling: append_log.py and check_log.py | M0 | — | S |
| [T32](T32-label-free-verification.md) | Label-free verification suite (P2a–d, P5) | M7 | T21 | M |
| [T33](T33-reproducible-packager.md) | Reproducible packager and zip-listing checks | M7 | T20, T30b | S |
| [T34](T34-clean-room-matrix.md) | Clean-room reproduction matrix | M7 | T33, T21, T24, T36 | M |
| [T35](T35-render-reports.md) | Report generation and consistency check | M7 | T23, T10 | S |
| [T36](T36-live-toolchain.md) | Live LLM toolchain (uv Python 3.12 + pinned SDK) | M2 | T10 | S |
| [T37](T37-code-judge-panel.md) | Code-judge simulation panel (calibrated) | M7 | T34, T35, T30b, T30 | M |
| [T38](T38-check-log-v2-transcript-panel.md) | check_log v2 and transcript panel | M7 | T31 | S |
| [T39](T39-blind-audit.md) | Blind audit: coverage set, estimation sample, auditor protocol | M7 | T23, T32 | L |
| [T40](T40-confidence-fragility-ledger.md) | Confidence tiers, fragility and rule provenance ledger | M7 | T26, T21 | S |
| [T42](T42-override-ban-enforcement.md) | Override-ban enforcement: relabeling, late-evidence, narrow-rule checks | M7 | T21, T27 | M |
| [T43](T43-release-gate.md) | Release gate and freeze manifest | M7 | T32, T33, T34, T35, T37, T38, T39, T40, T42, T24 | S |

## Dependency graph
```
M0  T31 (log tooling, no deps; do first)
    T01 ──┬── T02 ──┬── T03 (also T02b)
          │         ├── T04
          │         └── T16
          ├── T02b ─┬── T05 ─┐
          │         ├── T06 ─┤
          │         ├── T07 ─┤      (T05–T08 run in parallel)
          │         ├── T08 ── T09 ─┤
          │         └── T11a (also T04) ─┤
          ├── T10 ──┬── T11b (also T11a)
          │         └── T19 (also T04)
          └── T20 ──── T22
M2  T05,T06,T07,T09,T11a,T03 ──► T12
M3  T12,T04 ──► T13 ──► T14 ──► T15
M4  T12,T16 ──► T17 ;  T15,T17 ──► T18a ──► T18b (also T11a)
    T18b,T19,T20,T22,T11b ──► T21
M5  T21,T23 ──► T24 ──► T26 ;  T22,T20 ──► T23 ;  T21 ──► T25, T27
M2  T10 ──► T36 (live toolchain, P1) ──► T11b
M6  T21,T19,T11b,T36,T35 ──► T28 ;  T23,T24,T25,T26 ──► T29 ;  T21 ──► T30b ;  T28,T29,T30b,T31,T33 ──► T30
M7  T21 ──► T32 ──► T39 ;  T20,T30b ──► T33 ──► T34 (also T21,T24,T36) ;  T23,T10 ──► T35
    T26,T21 ──► T40 ;  T21,T27 ──► T42 ;  T31 ──► T38 ;  T34,T35,T30b,T30 ──► T37
    T32,T33,T34,T35,T37,T38,T39,T40,T42,T24 ──► T43 (release gate + freeze)
```
- **Critical path (weighted, computed):** T01 → T02b → T08 → T09 → T12 → T13 → T14 → T15 → T18a → T18b → T21 → T32 → T39 → T29 → T30 → T37 → T43.
- **Co-critical branch (LLM):** T01 → T10 → T11b → *scheduled live cache fill (needs `ANTHROPIC_API_KEY`)* → the T18b image-family check and T21.
- **Off-path:** T21 → T28 → T30; T21 → T30b → T30; T31 → T30.
- **Execution priority (24 h):** P0 output-critical → P1 LLM/media → P2 code-zip docs, reports and strategy table → P3 polish (see `../SCORING_STRATEGY.md` §5). Produce a first `output.csv` with `--llm off` as early as possible.
- **Parallel tracks:**
  - parsers T05/T06/T07/T08 after T02b;
  - identity and activity T03/T04 after T02;
  - LLM T10 → T11b, T19;
  - output T20 → T22 → T23;
  - policy T16.
- **If time runs short:**
  - cut T26 to S0/S1 plus signature ON/OFF and `use_late_audit_ids` rows;
  - cut T25 to C1, C2 and C3.

  T22, T24, T28, T29, T30, T30b, T31, T32, T33, T34 and T43 are mandatory. T39 can shrink to the post-freeze estimation sample of ≥ 100 cases plus the image family. T37 can shrink to 2 personas plus calibration.

## Task template
Each task file has these sections:
- **Field table:** ID, Milestone, Depends on, Size, SPEC refs.
- **Files:** exact paths created or modified.
- **Description:** one-paragraph outcome.
- **Implementation notes:** concrete steps, the prototype logic to *port* (never import), and the constants that belong in `Config`.
- **Acceptance criteria:** testable checkboxes with the expected numbers from the verified analysis.
- **Tests:** unit, scenario or data tests that prove the criteria.
- **Risks:** what could go wrong and how it is contained.

## Definition of Done (every task)
1. All acceptance criteria are checked. `python3 -m unittest discover -s code/tests -t code` passes on the system **Python 3.9**.
2. Every module has a docstring citing its SPEC ids, which must exist in `code/docs/SPEC.md`. Public functions have type hints. No magic numbers appear outside `config.py`.
3. Deterministic: no unordered iteration; the T27 checks pass where they apply. No LLM request carries sampling parameters.
4. Isolation: nothing reads `solution/`; nothing reads `sample_output.csv` outside `tests/gold.py`; **no eval case or user ids appear in code or tests**; no secrets in code, cache, diagnostics or logs.
5. Any test that runs `main.py` writes into temp `--out`/`--diag` paths, never into the root `output.csv`.
6. Diagnostics are updated whenever the task adds an inference, a flag or a degraded path.
7. **Transcript:**
   - exactly one §5.2 entry per user turn, appended with `python3 code/tools/append_log.py …`;
   - `python3 code/tools/check_log.py log.txt` exits 0 before the turn ends;
   - the summary states the decision made, why, and the before/after metrics when scores changed (e.g. "golden 30/32 → 32/32, step-F1 0.91 → 0.96");
   - Actions list task ids, files, the test command with its pass count, the commit, and any ablation kept or dropped.

## Conventions
- **Log hygiene:** write log.txt only through `append_log.py`, never with sed or Write. Commit log.txt at each milestone, and `check_log.py --baseline-ref` proves it is append-only. Never paste dataset PII; cite case ids or paths instead.
- **Sub-agent traceability (AGENTS §5.3):** sub-agents that can write append their own entry (`parent_agent=<parent>`, title prefix `[subagent <name>]`). For read-only workers (Explore, Plan, workflow reviewers), the parent appends one entry per worker group, with `parent_agent`, the worker list and the result (e.g. "3 reviewers, 38 verified issues, all fixed").
- One branch per milestone, `feat/m<N>-<slug>`. Small commits that reference task ids (e.g. `T09: trace-join log observations`).
- Tests use stdlib `unittest`. Fixtures are real dataset lines kept as Python string constants. Never put fixtures in `.json` or `.csv` under `code/`: the code judge ignores raw data files.
- `solution/notes/*` prototypes are references only. Port their logic and cite the prototype name in a comment, not its path.
- Model ids and prices are confirmed through the `claude-api` skill (T10, T28), not from memory.

## Traceability: SPEC → tasks
| SPEC area | Tasks |
|---|---|
| §2 inputs; I1–I4 identity | T02, T02b, T03 |
| §3 evidence F1–F9 | T02b, T05, T06, T07, T08, T09, T12 |
| §3 F10 media | T11a, T11b |
| §4 activity | T04 |
| §5 time T1–T6 | T02, T12, T17 |
| §6 policy | T16, T18a |
| §7 linking L1–L11 | T13, T14, T15 |
| §7 L12 hand-crafted/media | T18b |
| §8 emission V1–V5 | T17, T18a, T20, T22 |
| §9 intent | T19 |
| §10 N1–N8 | T01, T10, T21, T27, T30 |
| §11 A1–A6 | T21, T22, T24, T28, T29 |
| SCORING_STRATEGY Output O1–O11 | T13, T14, T15, T17, T18a, T18b |
| SCORING_STRATEGY Code zip C1–C12 | T01, T10, T11b, T19, T21, T26, T28, T29, T30, T30b |
| SCORING_STRATEGY Transcript X1–X6 | T31, DoD 7, Conventions |

## Traceability: risks → tasks
| Risk (IMPLEMENTATION_PLAN_REVIEW) | Owner task(s) |
|---|---|
| R1 learned-signature validity / compliance | T14, T26, T30b |
| R2 account_00N convention | T18b, T26 |
| R3 legal-hold verify | T18a, T26 |
| R4 missing audit ids | T15, T18a, T26 |
| R5 media extraction | T11a, T11b |
| R6 evidence/template disagreement | T17 |
| R7 window overfit | T13, T26 |
| R8 same user, several cases | T18b, T25 (C7) |
| R9 omission citation | T17, T18a |
| R10 time parsing | T02 |
| R11 cached-run usage | T10, T28 |
| R12 packaging and leakage | T27, T30 |
| R13 intent | T19, T25 (C2) |

## Traceability: local evaluation → tasks
| LOCAL_EVALUATION_STRATEGY item | Tasks |
|---|---|
| P1 gold samples | T24 |
| P2a–d label-free verification, P5 invariants | T32 |
| P3 blind audit (coverage + estimation, R1/R2/R3) | T39 |
| P4 tiers and fragility, P6 provenance ledger | T40 |
| §3 graders G1–G8, Pareto | T23 |
| §4 output fixes (+24 steps, FIFO coupling, orphans) | T14, T15 |
| §5 clean room, packager, reports, judge panel | T33, T34, T35, T37 |
| §6 override ban | T27, T42 |
| §7 transcript | T31, T38 |
| §8 release gate R1–R12 | T43 |
