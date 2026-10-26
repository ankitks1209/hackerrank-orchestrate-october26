# Implementation Plan: Ghost Data Still Exists Deletion-Audit Agent

Status: v1.4 (three review rounds, the score-maximization pass in `SCORING_STRATEGY.md` (⟲³) and the local-evaluation strategy in `LOCAL_EVALUATION_STRATEGY.md` (⟲⁴); adjustments from `IMPLEMENTATION_PLAN_REVIEW.md` applied and marked ⟲)
Implements: `SPEC.md` v1.2. Tasks: `tasks/` (33 tasks, T01–T30 with T02b, T11a/b, T18a/b).

---

## 1. Goals and constraints
- Produce `output.csv` that satisfies SPEC §8 and A1–A6.
- Run fast and deterministically. An offline run (`--llm cache`) must finish in under 5 s; the target is under 1.5 s.
- ⟲⁴ **Single submission.** Nothing ships unless the release gate (`LOCAL_EVALUATION_STRATEGY.md` §8) passes.
- Use a stdlib core on **Python ≥ 3.9** (⟲ the system `python3` is 3.9.6). The only third-party dependency is `anthropic`, which is optional. ⟲³ It is needed only for `--llm live`, and that mode requires Python ≥ 3.10 and `anthropic>=2.0.0`: 1.x+ requires 3.10, and 2.0.0 sends API version 2026-10-21 by default. `requirements.txt` pins `anthropic==2.3.0; python_version >= "3.10"` (⟲⁴, verified on PyPI). This machine has only 3.9.6, so T36 installs Python 3.12 via `uv`.
- ⟲³ Maximize the three scored artifacts: Output CSV, Code zip and Chat Transcript (`SCORING_STRATEGY.md`).
- Keep the code reviewable and defensible for the AI interview. Every step must carry a recorded reason, and every inference must sit behind a flag.
- Do not import or read `solution/`. Prototype logic is **ported**, not imported.

## 2. Architecture

```
code/
├── main.py                    # CLI entry: python3 code/main.py [--dataset DIR] [--out PATH]
│                              #   [--llm off|cache|live|batch] [--signature on|off] [--diag DIR] [--flags k=v,...]
│                              #   [--intent-model ID] [--media-model ID]   (⟲³ strategy comparison; batch is optional)
│                              #   [--include-samples] [--samples-out PATH]   (⟲ dev output for the scorer)
├── package_check.py           # ⟲ zip content check: required items present, forbidden ones absent; writes zip-root evaluation/ copy (⟲³)
├── docs/                      # ⟲³ shipped design docs (the code judge sees these; plan/ is not zipped)
│   ├── SPEC.md                # rules I1–I4, F1–F10, T1–T6, L1–L12, V1–V5, §9 (no eval case ids)
│   ├── ARCHITECTURE.md        # Mermaid pipeline, layering, data flow, where the LLM sits
│   └── DECISIONS.md           # ADR-lite (~12): deterministic core, LLM scope, learned signature, cache, models, sampling params, Python split
├── tools/                     # ⟲³ transcript tooling (T31)
│   ├── append_log.py          # builds and appends §5.1/§5.2 entries (tool/model required), re-reads and lints
│   ├── check_log.py           # log.txt linter (--trace, --baseline-ref fail-closed; v2 in T38)
│   ├── build_zip.py           # ⟲⁴ reproducible zipfile packager + zip-listing checks (T33)
│   ├── clean_room.py          # ⟲⁴ judge-like reproduction matrix (T34)
│   ├── render_reports.py      # ⟲⁴ fills/checks report numbers from scorer+meter output (T35)
│   └── release_gate.py        # ⟲⁴ R1–R12 automated gates + freeze manifest (T43)
├── ghostaudit/
│   ├── __init__.py            # version, public run()
│   ├── config.py              # frozen Config + Flags; Config.from_env(); all tunables named
│   ├── model.py               # enums, frozen slotted dataclasses, OPERATION_TABLE
│   ├── timeutil.py            # to_epoch() (lru_cache), iso()
│   ├── keys.py                # ⟲ the single key normalizer: email_key/hash_key/phone_key/user_key/keys_from_record
│   ├── dataset.py             # DatasetReader (allowlist), typed CSV loaders, Manifest
│   ├── identity.py            # IdentityIndex
│   ├── activity.py            # template regexes → ClassifiedActivity
│   ├── evidence/
│   │   ├── base.py            # EvidenceParser Protocol, ParseOutput, registry, detect()
│   │   ├── sql.py             # topology / inventory / special (schema-detected)
│   │   ├── records.py         # service exports / bundles / ledgers / collections
│   │   ├── handover.py        # pipe-delimited TXT
│   │   ├── logs.py            # 8 line formats + trace-join
│   │   ├── media.py           # ⟲ PURE map_facts(file_id, MediaFacts, link_rows, keys) → ParseOutput (no LLM import)
│   │   └── index.py           # EvidenceIndex (immutable)
│   ├── linking.py             # candidates, fixed-point solver, tie-breaks
│   ├── policy.py              # PolicyEngine from deletion_rules.csv, SYSTEM_BY_PREFIX
│   ├── state.py               # StateResolver: state at audit_at + citation choice
│   ├── casebuilder.py         # ResourceVerdicts per case (generated / hand-crafted / media / tombstone)
│   ├── intent.py              # IntentClassifier (guard + LLM + corroboration)
│   ├── emit.py                # emit(), serialize(), write_output()
│   ├── contract.py            # ⟲ output-contract validator (layer 5; used by main.py, evaluation and tests)
│   ├── pipeline.py            # run(config, reader, llm) → RunResult (orchestration only)
│   ├── diagnostics.py         # per-case reasons, assumption ledger, disagreements → diagnostics.md
│   ├── llm/
│   │   ├── client.py          # LLMClient Protocol, AnthropicClient, NullClient
│   │   ├── media_extract.py   # ⟲ extract_media_facts(entries, llm) → dict[file_id, MediaFacts] (pipeline pre-pass)
│   │   ├── cache.py           # DiskCache (atomic writes), CachingClient decorator
│   │   ├── usage.py           # UsageMeter, PriceTable, render_usage_report()
│   │   └── prompts/           # intent.v1.md, media_extract.v1.md (versioned; hash in cache key)
│   └── cache/                 # committed LLM responses (*.json): request hash → response + usage
├── evaluation/
│   ├── __init__.py
│   ├── main.py                # scorer CLI: validate, score vs sample_output, custom cases, --ablate
│   │                          #   (⟲ puts code/ on sys.path; --pred defaults to the --samples-out path)
│   ├── ablation.py            # ⟲ variant runner
│   ├── verify_steps.py        # ⟲⁴ label-free P2a–d verifier (import-isolated from linking)
│   ├── invariants.py          # ⟲⁴ P5 invariants + distributions
│   ├── confidence.py          # ⟲⁴ tiers, fragility (P4)
│   ├── audit/                 # ⟲⁴ sampler, audit_score (Clopper–Pearson), R1/R2/R3 prompts, labels (.md, never read by pipeline)
│   ├── JUDGE_PANEL.md         # ⟲⁴ code-judge panel rubric + results
│   ├── RELEASE_CHECKLIST.md / RELEASE_MANIFEST.md
│   ├── scoring.py             # pure metric functions
│   ├── validator.py           # thin re-export of ghostaudit.contract
│   ├── custom_cases.py        # synthetic mini-datasets C1–C6 (built in a temp dir at runtime)
│   ├── evaluation_report.md
│   └── usage_report.md
├── pyproject.toml             # ⟲³ requires-python >= 3.9; ruff config (optional tooling)
└── tests/                     # stdlib unittest; fixtures as Python string constants
    ├── __init__.py
    └── gold.py                # ⟲ GoldReader: the only code allowed to open sample_output.csv (shared by tests and evaluation)
```

### 2.1 Responsibilities and dependency direction
Modules depend only on modules lower in this list. Dependencies flow inward toward the pure model.

1. `model`, `timeutil`, `config`, `keys`: no imports from the package
2. `dataset`, `identity`, `activity`, `policy`, `llm/*`
3. `evidence/*` (⟲ pure: media.py receives precomputed `MediaFacts` and never imports `llm`)
4. `linking`, `state`, `intent`
5. `casebuilder`, `emit`, `contract`
6. `pipeline`, `diagnostics`
7. `main.py`, `evaluation/*`

No module holds mutable global state. Compiled regexes and frozen lookup tables are module-level constants.

⟲ The LLM sits **off** the deterministic core's critical path. `pipeline` runs `extract_media_facts` (llm layer) as a pre-pass and passes the resulting `dict[file_id, MediaFacts]` into `build_index`. Under `--llm off`, the dict is empty.

### 2.2 Core types (`model.py`)
⟲ Python 3.9 form: `from __future__ import annotations`, `@dataclass(frozen=True)` (no `slots`), `Optional[...]` wherever annotations are evaluated at runtime. The sketch below uses the short notation for readability.
```python
class Phase(IntEnum): FINDING = 0; REMEDIATION = 1; VERIFICATION = 2
class Treatment(Enum): DELETE; REDACT; ANONYMIZE; RETAIN; FLOW; RESTORE
class ObsState(Enum): PRESENT; ABSENT; EXPOSED; REDACTED; ANONYMIZED; ACTIVE; DISABLED; BLOCKED
class ActKind(Enum): ACCOUNT_SUBMIT; POLICY_OK; VIOLATION; FLOW_ENABLED; RESTORE_ALLOWED;
                     REPLICATION_CHECKPOINT; REPOPULATED; RESTORE_REPOPULATED; NON_DELETION;
                     LINK; TARGET_RESOURCE; NOISE

@dataclass(frozen=True)
class MediaFacts: file_id: str; records: tuple[dict, ...]   # ⟲ validated LLM extraction (display_id, resource_hint, category, keys, state_facts)

@dataclass(frozen=True)
class Request: case_id: str; email: str; requested_at: int; reported_status: str
               reported_at: int; audit_at: int; text: str; is_sample: bool

@dataclass(frozen=True)
class ManifestEntry: file_id: str; path: Path; origin: str; captured_at: int; order: int

@dataclass(frozen=True)
class Observation: file_id: str; captured_at: int; entry_time: int; system_id: str
                   resource_id: str; category: str | None; state: ObsState
                   subject_keys: frozenset[str]; locator: str

@dataclass(frozen=True)
class ScopeAssertion: file_id: str; captured_at: int; system_id: str; present_ids: frozenset[str]

@dataclass(frozen=True)
class ClassifiedActivity: activity_id: str; t: int; kind: ActKind; system_id: str
                          resource_id: str; treatment: Treatment | None; reported_result: str
                          related_rid: str | None; alias: str | None
                          linked_user: str | None; linked_email: str | None

@dataclass(frozen=True)
class CaseLinks: case_id: str; account_id: str | None; account_basis: str
                 resources: tuple[LinkedResource, ...]; notes: tuple[str, ...]

@dataclass(frozen=True)
class ResourceVerdict: system_id: str; resource_id: str; treatment: Treatment
                       violating: bool; cite: str; basis: str; reason: str

@dataclass(frozen=True)
class Step: step_no: int; phase: str; system_id: str; resource_id: str
            operation: str; state: str; evidence_id: str
```
`OPERATION_TABLE` encodes AGENTS §6.4 as `{phase: ((op, state), …)}`. It is the single source of truth for operation names, states and ordering, and both emitter and validator use it.

### 2.3 Component interfaces
| Component | Interface | Notes |
|---|---|---|
| DatasetReader | `open(rel) -> Path`, `requests()`, `identities()`, `audit_log()`, `activity()`, `rules()`, `manifest()` | Reads only the allowlist. Raises `ForbiddenInputError` for `sample_output.csv`. The evaluation package has its own reader. |
| IdentityIndex | `build(identities, audit_log)`, `resolve(email) -> user_id`, `keys_for(user_id) -> frozenset`, `users_for(keys) -> frozenset` | Follows email chains to a fixed point. Computes sha256 for every email. |
| classify_activity | `(rows) -> tuple[ClassifiedActivity, ...]` | One compiled regex per template, tried in order of frequency. |
| EvidenceParser | `detect(entry, head: bytes) -> bool`, `parse(entry, data: bytes, keyer) -> ParseOutput` | Uses a registry. Exactly one parser must claim each file; zero or several raises an error. |
| EvidenceIndex | `build(outputs)`; `by_rid`, `rids_by_user`, `users_by_rid`, `mentions(rid)`, `scopes(file_id)`, `files_in_window(lo, hi)` | Built once and immutable. Tuples are sorted by `(entry_time, captured_at, order)`. |
| solve_links | `(requests, acts, ev_index, identity, cfg) -> dict[str, CaseLinks]` | Pure function. Uses sample ∪ eval requests (both participant inputs; gold is never read). |
| PolicyEngine | `from_rules(rows)`, `treatment(system_id, category, event_type)`, `is_compliant(treatment, state)`, `ops(treatment)` | The rule table is data-driven. |
| StateResolver | `resolve(rid, system_id, req) -> Resolved(state, cite, basis)` | Implements SPEC T1–T4, per resource. Returns `basis='unobserved'` when the rid is not mentioned. |
| choose_omission_cite | `(account_rid, case_cites, req, index) -> str | None` | ⟲ Pure V5, called by CaseBuilder **after** the other verdicts are resolved (no state→casebuilder cycle). |
| keys | `email_key`, `hash_key`, `phone_key` (digits, ≥ 8), `user_key`, `keys_from_record(fields)` | ⟲ The single normalizer, shared by IdentityIndex and all parsers. |
| contract.validate | `(rows, requests, manifest) -> list[Violation]` | ⟲ Used inline by main.py, and by evaluation and tests. |
| CaseBuilder | `build(req, links) -> tuple[ResourceVerdict, ...]` | Handles the four families (generated, hand-crafted, media, tombstone). |
| IntentClassifier | `classify(reqs) -> dict[str, IntentDecision]` | Guard + LLM + corroboration (SPEC §9). |
| emit / serialize / write_output | `emit(verdicts) -> (status, steps)`; `serialize(steps) -> str`; `write_output(results, path)` | Ported from `solution/notes/proto/emit_check.py`. |
| LLMClient | `complete(LLMRequest) -> LLMResponse(text, input_tokens, output_tokens, model, cached)` | `AnthropicClient` is the real client; `NullClient` is for tests and `--llm off`. ⟲ The API key is held only by `AnthropicClient`. The `Config` field is `field(repr=False, compare=False)`, wrapped in a `Secret` whose repr is `***`. |
| CachingClient | `(inner, cache, meter, mode)` | Raises `CacheMiss` in `cache` mode. Writes are atomic (temp file + `os.replace`). |

## 3. Data flow

```
DatasetReader
  ├─ CSVs ──► IdentityIndex ──────────────────────────────────────────────┐
  ├─ activity.csv ──► classify_activity ──► acts ──────────────┐          │
  └─ manifest ──► for each file (manifest order): detect → parse          │
                    (media.py ◄── CachingClient[vision])       │          │
                  ──► EvidenceIndex (+ScopeAssertions) ─────────┤          │
IntentClassifier(guard, CachingClient[text], N-rows) ─► intents │          │
solve_links(requests, acts, EvidenceIndex, identity) ─► CaseLinks ◄───────┘
for case in requests (eval only for output):
    CaseBuilder → StateResolver → PolicyEngine → ResourceVerdicts → emit → CaseResult
write_output(sorted naturally by case_id) ; diagnostics.md ; UsageMeter snapshot
```

## 4. Coding standards
- **Style:** PEP 8. Type hints on every public function. Docstrings on public classes and functions: one line on purpose, plus a note on SPEC rule ids where relevant (e.g. `"""Implements SPEC T1–T3."""`).
- **Size:** functions stay under ~40 lines; modules under ~400.
- **Naming:** `snake_case` for functions and variables, `PascalCase` for types, `UPPER_SNAKE` for constants. No single-letter names except loop indexes.
- **Errors:** custom exceptions (`DatasetError`, `ForbiddenInputError`, `ParseError`, `CacheMiss`). Never use a bare `except`. A parse error in one evidence file is logged with its locator and skips that file or line; the run continues and diagnostics records it.
- **I/O:** `pathlib.Path`; explicit `encoding="utf-8"`, `newline=""` for CSV; `\n` line endings.
- **Determinism:** never iterate a set without `sorted()`. Process files in manifest order. Store times as integer epochs. Use `json.dumps(sort_keys=True)` everywhere output is produced.
- **Magic numbers:** none in logic. Windows, thresholds and batch sizes live in `Config`, each with a comment citing its derivation.
- **No print debugging.** Use the `logging` module (`ghostaudit.*` loggers) at WARNING by default; `--verbose` switches to INFO.
- **Linting:** `python3 -m compileall`, plus `ruff`/`mypy` if available locally. Code must not depend on them.

## 5. Design principles applied
| Principle | Application |
|---|---|
| Single responsibility | Each parser handles one family. Linking, state, policy and emission are separate modules. |
| Open/closed | New evidence formats register a parser without editing the pipeline. Policy rows are data. |
| Liskov / interfaces | `EvidenceParser` and `LLMClient` Protocols. `NullClient` and fakes can stand in for the real client. |
| Dependency inversion | `pipeline.run` receives reader, config and LLM client as arguments. Nothing constructs its own collaborators. |
| Pure core, impure shell | Everything from `identity` to `emit` is a pure function of its inputs. I/O happens only in `dataset`, `llm/cache`, `emit.write_output` and `diagnostics`. |
| Explicit over implicit | Each verdict carries `basis` and `reason`. Each inference is a named flag. |
| Fail soft, report loud | Degraded paths (cache miss, invalid media extraction, ambiguous link) still produce valid output and appear in diagnostics. |

## 6. Agent-development practices (LLM layer)
- **Narrow LLM role.** The LLM handles only (a) intent classification and (b) media fact extraction. It never decides status or emits steps directly.
- **Versioned prompts** in `llm/prompts/*.vN.md`. The prompt's sha256 is part of the cache key, so editing a prompt invalidates exactly the affected entries.
- **Structured output.** Each response is a JSON object validated against a stdlib schema check (required keys and types). On failure: one retry with an error hint, then the deterministic fallback.
- **Determinism.** ⟲³ **No sampling parameters**: `temperature`, `top_p` and `top_k` are a 400 since API 2026-10-21. Use a fixed `max_tokens` and an explicit `output_config.effort="low"` (both models default to `medium`), plus **structured outputs** `output_config.format={type: json_schema, schema}`, with the stdlib schema check as defence in depth. Cache key = sha256(model, prompt_hash, system, messages, attachment sha256, params including effort).
- **Stop reasons** (⟲³): `refusal` or `max_tokens` falls back to the deterministic path and is recorded in diagnostics. No assistant prefill: these models return a 400 for it.
- **Prompt caching** (⟲³): the shared system prompt is ≥ 600 tokens (the minimum cacheable prefix is 512) and carries `cache_control`. One serial warm-up call precedes the parallel fan-out. Acceptance: `cache_read_input_tokens > 0` on calls 2..N.
- **Resilience.** Timeout of 60 s per call. Up to 3 retries with exponential backoff and jitter, on 429/5xx only. A bounded `ThreadPoolExecutor` (≤ 8 workers) runs in live mode only.
- **Cost and latency.** Intent requests are batched 25 per call: 22 calls for 550 texts, or 23 if eval and samples are batched separately. ⟲ The cache is **per item**, so only misses are batched. Media uses one call per file (15). Prompt caching of the shared system prompt is used where the SDK supports it.
- **Security.** The key is read only via `Config.from_env()` from `ANTHROPIC_API_KEY`. It is never logged, cached or written. Cache entries hold only request hashes, response text and usage.
- **Metering.** `UsageMeter` records per model: calls, input and output tokens (⟲³ output includes thinking, which cannot be disabled on Opus 5.5), cache creation and read tokens, images with estimated image tokens, PDF pages, stop reasons, wall time, peak RPM/TPM, live vs cache-replayed, and cost from `PriceTable`. Prices come from `Config` and are verified with the `claude-api` skill.
- **Evaluation-driven iteration.** Every change to linking or the rules is judged by the scorer on samples, the custom cases, and the ablation deltas. No change is tuned against eval outputs.
- **Model ids** (⟲³, verified with the `claude-api` skill on 2026-10-24) come from `Config`:
  - default `claude-opus-5-5` for both intent and media ($4 / $20 per MTok, cache reads $0.20);
  - strategy S2 evaluates `claude-haiku-5-5` for intent ($0.10 / $0.50);
  - Message Batches cost 50 % less (optional `--llm batch`).
  Changing the default model is the user's call.
- **Strategy comparison** (⟲³): S0 deterministic-only (`--llm off`), S1 Opus/Opus (default), S2 Haiku intent + Opus media, plus signature ON/OFF/ranges-only. All cache entries are committed, so the comparison table reproduces offline.

## 7. Performance plan
| Stage | Technique | Budget |
|---|---|---|
| CSV load (~6k rows) | `csv.DictReader`; epochs parsed once | 40 ms |
| SQL (24 files) | sqlite3 `:memory:` + `executescript`; `ORDER BY` in every query | 400 ms |
| JSON/TXT (29 files) | a single `json.loads` per file | 100 ms |
| Logs (26 files) | first-token dispatch to precompiled regexes; trace dict join | 300 ms |
| Media (15 files) | cache lookups only | 10 ms |
| Index build | dict-of-tuples; manifest sorted for `bisect` | 50 ms |
| Activity (4011 rows) | compiled regexes; noise check first | 30 ms |
| Linking | requests sorted by `reported_at`; `bisect` windows; fixed point O(iterations × edges) | 300 ms |
| Per-case build and emit (518) | O(resources) per case | 150 ms |
| **Total** | | **≈ 1.4 s target, 5 s gate** |

Optimizations are justified only by measurement: T27 times each stage, and diagnostics records the timings. No premature parallelism: the deterministic core is single-threaded, and only live LLM calls run concurrently.

## 8. Testing strategy
- **Unit tests (per module).** Parser fixtures are real lines copied from the dataset into Python constants, one per log format, SQL family and JSON family. Also covered: identity (2-hop chain, uppercase, old hash/phone, `.jr` rejection, same-name rejection), activity (one row per template, plus noise), and policy.
- **Scenario tests (linking).** Unique link; swap pair resolved by evidence; FIFO pairing; never-mix with the legal-hold exception; decoy row dropped; learned signature on/off.
- **Round trip.** Abstract every sample's gold into verdicts, then emit; expect 32/32. This test reads gold, so it lives under `tests/`, never under the pipeline.
- **Golden end-to-end gate.** The pipeline on the samples is scored by `evaluation/scoring.py`. Pass requires status 32/32 and exact ≥ 30/32, with pinned misses case_18 and case_20.
- **Contract property tests.** `validator.py` runs on `output.csv`. Its checks are listed in task T22.
- **Determinism.** Two subprocess runs, with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=4242`, must produce byte-identical output. ⟲ Every test that invokes main passes `--out` and `--diag` under `tempfile.mkdtemp()`, so the submission `output.csv` is never overwritten.
- **Performance.** Wall time under 5 s for `--llm cache`.
- **Static isolation.** ⟲ The scope is `code/ghostaudit/**` and `code/main.py`: no import, open or Path usage of `solution/` (regex on usage, not on the bare string), no `sample_output`, no `os.environ` outside `config.py`, no `print(`. `tests/` and `package_check.py` are exempt.
- **How tests are run** (⟲): `python3 -m unittest discover -s code/tests -t code`, from the repo root.
- **Custom cases C1–C6.** Synthetic mini-datasets in temp dirs (T25).
- **Ablation harness.** The flags and window sensitivities defined in T26.

**Scorer metrics** (`scoring.py`)
| Metric | Definition |
|---|---|
| Case accuracy | Fraction of cases whose `deletion_status` matches |
| Step-level | Multiset precision, recall and F1 over the tuple (phase, system_id, resource_id, operation, state, evidence_id); also the exact-array match rate |
| Field-level | Steps aligned by (phase, system_id, resource_id); accuracy per field over aligned pairs; unaligned steps count as misses |
| Sequence | Exact order match over the common steps, and the normalized LCS ratio of the step-key sequences |

## 9. Milestones
| Milestone | Tasks | Exit criterion |
|---|---|---|
| M0 Foundations | T01, T02, T02b, T31 (⟲³ log tooling, done first) | Package imports on Python 3.9; CSVs load; time fixtures pass; key normalizer shared |
| M1 Identity and activity | T03–T04 | 550/550 emails resolve; template counts match the spec |
| M2 Evidence | T05–T10, T11a, T11b, T12 | All 79 text files parse with 0 unclassified lines; media facts mapped from fixtures (live extraction is a scheduled cache-fill step that needs `ANTHROPIC_API_KEY`); index built |
| M3 Linking | T13–T15 | ⟲³ Learned signature ON: sample accounts 24/24 and worker rows 50/50; held-out evidence agreement ≥ 279/280; unresolved KPI recorded; OFF reported |
| M4 Decision | T16–T22 (⟲ T22 moved into M4) | End-to-end `output.csv`; validator clean |
| M5 Evaluation | T23–T27 | Golden gate, custom cases, ablations, determinism and performance all pass |
| M6 Deliverables | T28–T30, T30b (⟲³ docs) | Reports written, README updated, zip checklist passes |
| M7 Local evaluation and release (⟲⁴) | T32–T35, T37–T40, T42, T43 (T36 belongs to M2/P1) | All release gates R1–R12 in `LOCAL_EVALUATION_STRATEGY.md` §8 pass; `RELEASE_MANIFEST.md` frozen |

**Execution priority** (⟲³, under the 24 h assumption; see `SCORING_STRATEGY.md` §5):
1. **P0 output-critical:** T31 → T01 → T02/T02b → T03–T09 → T12–T17 → T18a → T20 → T22 → T21 (`--llm off`) → T23/T24. A first `output.csv` exists early, before any LLM work.
2. **P1:** T10 → **T36 live toolchain** (uv Python 3.12 + `anthropic==2.3.0`) → T11a/T11b plus the cache fill → T18b → T19 → regenerate the output.
3. **P2:** T30b → T30 → T28 → T26 (S0/S1/S2 plus signature ON/OFF) → T29.
4. **P3:** T25, T27, case explanations, the optional batch mode.
5. **P4, local evaluation and release (⟲⁴):** T32 (label-free verification) and T42 (override ban) as soon as T21 exists. Then T33 → T34 → T35, T40, the T39 coverage audit, and the T37 judge panel. **Freeze**, then the T39 estimation sample (≥ 100 cases, scored once), T38, and the **T43 release gate**. Submit exactly once.

**Critical path** (⟲ unified with `tasks/README.md`): T01 → T02b → T08 → T09 → T12 → T13 → T14 → T15 → T18a → T18b → T21 → T24 → T26 → T29 → T30. Co-critical branch: T01 → T10 → T11b → (live cache fill) → T18b image-family check. T28 is off-path (T21 → T28 → T30).

**Parallel tracks:**
- Evidence parsers after T02b: T05, T06, T07, T08 in parallel
- LLM: T10 → T11b, T19
- Output: T20 → T22 → T23
- Policy: T16

## 10. Porting map (prototype → production)
| Prototype (reference only; not shipped) | Production target | Change |
|---|---|---|
| `solution/notes/scripts/logparse.py` (`kvparse`, `parse_line`) | `evidence/logs.py` | Remove the `instance` trace fallback; return typed records |
| `solution/notes/scripts/classify.py` | `evidence/logs.py` event table | Normalize labels to `ObsState` |
| `solution/notes/records_normalize.py` | `evidence/records.py` | Wrap in functions; drop name keys; IDENTIFIABLE → EXPOSED |
| `solution/notes/proto/solve_links.py` | `linking.py` | Build from EvidenceIndex; replace the hard-coded fingerprint with the **learned** signature (fit from evidence-anchored pairs); add reported_at windows and FIFO |
| `solution/notes/proto/e2e_samples.py` (`cite`, `acite`) | `state.py`, `choose_omission_cite` (called by `casebuilder.py`) | Scope-aware omission citation (V5) |
| `solution/notes/proto/emit_check.py` (`emit`, OPS/TREAT/STATE) | `emit.py` | Use `OPERATION_TABLE`; typed steps |
| (none) | `evidence/sql.py`, `evidence/media.py`, `llm/*`, `evaluation/*` | New |
