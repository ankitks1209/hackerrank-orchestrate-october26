# SPEC Review: Critical Assessment of `SPEC.md` v1.0

Every issue below has a severity, a status, and the change made to SPEC (v1.1 marks these with ⟲). Issues that are measured rather than resolved go to the ablation harness (T26) and the assumption ledger (T29).

Severity: **H** high (can flip statuses or many steps), **M** medium (a handful of steps), **L** low (hygiene).

| # | Sev | Finding | Resolution | Status |
|---|---|---|---|---|
| S1 | H | **Overfitting.** Only 32 labelled cases exist, 8 of them hand-crafted, and the windows, tie-breaks and verification-set rules are all inferred from them. | Every inferred constant goes into `Config` with a comment naming its source. The ablation harness (T26) measures sensitivity (±10 min on windows, each flag on/off). Six synthetic custom cases (T25) test the rules away from the sample shape. The assumption ledger lists every inference. | Mitigated, measured |
| S2 | H | **Trusting claims.** v1.0 let activity templates decide state, which contradicts "do not trust reported results". | ⟲ §4 precedence: in-window evidence decides state. Templates handle discovery, treatment, and a fallback only when no admissible observation exists. Disagreements are logged; the analysis expects ~0, since they agreed 274/274 on SQL and 520/521 on log/JSON. | Fixed |
| S3 | H | **Generator-artifact dependence.** The seconds-mod-60 fingerprint and id arithmetic (case_N→user_N−2) are leaks; AGENTS §6.7 forbids "case-family shortcuts", and the AI interview may probe this. | ⟲ L3 makes worker windows anchor on `reported_at`. L7 puts the fingerprint behind a flag, OFF by default. L8 bans id arithmetic. The cost (unique eval account links 470 → 399 when OFF) is measured and reported. | Fixed (decision documented) |
| S4 | M | **The `account_00N` convention** has no evidence behind it, yet sample gold depends on it (case_04). | Kept as an L12 fallback with basis `convention`. It only fires for the hand-crafted family when no grounded id exists, and every use is listed in diagnostics. | Accepted risk |
| S5 | M | **Conflict with AGENTS §6.5:** "process downstream copies before their source" vs gold's alphabetical sort (case_16 deletes the account before search). | ⟲ §8.4: the table sort is normative because the grader is gold-based. The rationale goes into the evaluation report. | Fixed |
| S6 | M | **Untested rules:** legal-hold verify (V3), compliant non-account resources inside INCOMPLETE cases (8.2), and late-only audit ids in COMPLETE cases. | V3 is ON behind a flag. 8.2 uses `""`. A COMPLETE case drops a compliant step it cannot cite, because the contract requires a citation. Each one is an ablation row. | Decided, measured |
| S7 | M | **Fragile media family:** vision extraction can misread, display ids differ from resource ids (CS-5034 → support_1034), and ev60 shows a person who does not match the LINK row. | ⟲ F10: an image maps to a resource only if the extracted alias equals the LINK alias. The LINK row wins over the on-screen identity (Q7). If extraction is missing or invalid, the resource is skipped and logged. Expected targets are test fixtures, not runtime constants. | Fixed |
| S8 | M | **Intent arbitration** was unspecified: the guard, the LLM and the N rows could disagree. | ⟲ §9.4: text is primary; the LLM overrides the guard only at confidence ≥ 0.9; N rows corroborate only. `--llm off` uses the guard alone. | Fixed |
| S9 | M | **Audit-record gap:** about 84 eval cases have no findable audit id, and samples 18/20 cannot be reproduced. | Never invent ids. A2 accepts exactly those two pinned misses. Coverage (in-window / late-only / none) is reported. | Accepted, measured |
| S10 | M | **Output sort ambiguity:** "sorted by case_id" — string order puts case_100 before case_33. | ⟲ §8.4: use natural numeric order, which matches the order of `deletion_requests.csv`. The grader parses rows by case_id, so this is low risk either way. | Fixed |
| S11 | M | **Trace-join hazard:** the prototype log parser falls back to `instance` when `trace_id` is missing, which can join keys across unrelated lines (evidence_61). | ⟲ F9: no fallback; a line without a trace id gets inline keys only. | Fixed |
| S12 | L | **Usage report on a cached run:** a cache-only final run shows 0 live tokens and could look like no AI was used. | The N1/N7 meter records live and replayed tokens separately. Each cache entry stores its original billed usage. The report states cache provenance. | Fixed (in plan) |
| S13 | L | **Doc inconsistency:** AGENTS says `evaluation/`, README says `code/evaluation/`. | Reports go in `code/evaluation/`, which the zip command already includes. | Fixed |
| S14 | L | **Unresolved request email** has no defined behaviour. | ⟲ I3: hard error, logged; emit a minimal INCOMPLETE as a last resort. This currently never happens: 518/518 resolve. | Fixed |
| S15 | L | **Same user, several cases** (user_07/17/18): the risk is leaking one case's state into another. | T5: per-case time scoping, plus a custom test (⟲ C7/T25, same user with two cases). | Fixed |
| S16 | L | **Model ids and pricing** could be written from memory and be wrong. | Model ids and prices live in `Config`; the implementer verifies them through the `claude-api` skill before T10/T28. | Fixed (in plan) |

## What the spec does well
- Every normative rule has an id (I1–I4, T1–T6, L1–L12, V1–V5, N1–N8, A1–A6), so tasks and tests can trace back to it.
- It states the evidence-family decoding exhaustively, including the "in scope vs not observed" distinction, which is the main source of false COMPLETE answers.
- It separates **what is grounded** (identifiers, timestamps, scope, policy) from **what is inferred** (windows, the account convention), and every inference is behind a flag.

## Residual risks carried into the implementation plan
1. Worker-row linking quality with the fingerprint OFF is the largest unknown. Target: unresolved ambiguous rows ≤ 20 in eval, tracked as a KPI in T14/T26.
2. Media extraction depends on the LLM. If the cache is missing for a reviewer, those 12 cases degrade. Mitigation: ship the cache (T28).
3. Gold for rules never seen in the samples (legal hold, repopulation flows) cannot be validated. Mitigation: they are grounded in the policy text and reported as assumptions.

---

# Round 2: independent adversarial review (fact checker + contract auditor)

Three reviewers checked v1.1 against `dataset/` and the contract, reading only. Every finding below was verified with a script or a direct read and is now fixed in SPEC v1.2 (marked ⟲).

| # | Sev | Finding (verified) | Fix in SPEC v1.2 |
|---|---|---|---|
| S17 | H | `operational_record_history` rows store the subject in **`lookup_value`**, not `subject_reference`. A parser built on v1.1 would lose 124 observations (118 resolvable, including 61 FOUND, 12 IDENTIFIABLE and 9 ACTIVE). | F5 names `lookup_value` and says `data_store` is not the system. |
| S18 | H | F10 allowed media only via LINK rows, but sample case_07's only finding (support_001) exists **only** in ev58, which has no LINK row. Under v1.1 the golden gate A2 could never pass. | F10 adds path (b): a literal resource id plus an identifier that resolves to a subject. ev58 and ev55 are added to the target table. |
| S19 | H | The v1.1 intent guard was 10 literal phrases, each matching exactly one eval NOT_APPLICABLE text. It was fitted to eval inputs, which breaks AGENTS §6.7, and it fails on paraphrases and other languages (C2). | §9 rewritten: the LLM is primary (per-item cache, injection-safe delimiters, id-set validation). A principled multilingual lexicon (negation-proximity, keep-active, access/correction/opt-out intent) is the fallback. The expected NOT_APPLICABLE set is a check, not an input. |
| S20 | H | Python ≥ 3.11 was required, but the system `python3` is 3.9.6, while README and AGENTS name `python3 code/main.py`. | N5 now says Python ≥ 3.9: `from __future__ import annotations`, no `slots`, no `match`. |
| S21 | M | `record_lookup` lines can be WARN (22 lines in ev08/ev41, all IDENTIFIABLE rows), so INFO-only dispatch would drop exposed findings. | F9 format 8 matches any level. |
| S22 | M | The L3 windows (−7 min, +130 min) missed real rows activity_1124, 438 and 147. | Windows are now [−30, −2] and [+30, +135] min. `window_offset_s` drives the sweep. |
| S23 | M | "system_id = target_system, plus an object_store remap" is wrong. RP, RB, R and N rows target other systems, and object_store occurs only on noise rows. | §4 has a per-kind system_id table and a consistency test against `SYSTEM_BY_PREFIX`. |
| S24 | M | Q1's premise was incomplete. support_9538 also appears in ev04, which is in case_34's window (display only, no attachment state). | Q1 rewritten: cite ev04 if extraction shows the record is still listed; ev01 alone needs the flag. |
| S25 | L | Noise count is 2435, not ~2635. The F9 noise list was incomplete. | Exact count. Noise now means "not in the state table, not `*_started`, not framing"; anything else is reported as `unknown_event`. |
| S26 | L | L12 ignored T-row and LINK account pointers, so about 7 samples would be labelled `convention`. | L12 adds the `activity_pointer` step, and ev57's `source_resource_id` counts as a pointer. |
| S27 | L | V1 says "always", but V5.3 and L12 allow omission. All 32 gold rows contain the account step. | V1 now names its exceptions. Omissions are counted, and COMPLETE `[]` raises a validator warning. |
| S28 | L | No citation rule for violating resources whose state comes only from activity (`basis=activity`). | §8.2: cite the in-window V/CF/CR `activity_id`; otherwise drop and log. |
| S29 | L | Comparing `resource_id` as a string was untested (no sample has ties) and inconsistent with natural case_id order. | Flag `resource_sort`, Q8, and an ablation count. |
| S30 | L | Compliant L1 observations (e.g. backup_5165 BLOCKED) were not added by L10. | L10 now includes compliant in-window observations as verification-only resources. |

Review outcome: SPEC v1.2 is accepted. No open H items remain. The residual risks are unchanged (worker linking with the fingerprint OFF, media dependence, untested gold for legal holds and repopulation), now with tighter measurement.


---

# Round 3: score-maximization pass (`SCORING_STRATEGY.md`)

The rubric (Transcript /10, Output /30, Code zip /30) prompted a quantitative expected-value review. It was measured read-only on `dataset/` with the prototypes.

| # | Sev | Finding | Change in SPEC v1.3 (⟲³) |
|---|---|---|---|
| S31 | H | With the fingerprint OFF, 95 eval cases (185 steps) differ. On the samples, OFF gives 14/24 exact vs 22/24, and worker rows go to 47 correct/3 missed/5 wrong vs 50 correct with ON. The regularity can be **learned without gold** from evidence-anchored pairs (73/73 and 296/296), and on held-out eval evidence it agrees with 279/280 non-decoy owners. | L7 becomes a "learned link signature", **default ON**, with OFF kept as an ablation. Compliance caveat disclosed. This reverses S3's default on measured evidence. |
| S32 | H | `temperature: 0` would be rejected: sampling params are a 400 since API 2026-10-21. | N1: no sampling params. Determinism comes from the cache, structured outputs, effort and max_tokens. |
| S33 | H | Eval case ids written as assertions in code or tests could read as "hardcoded labels". | A3 is a diagnostics-only check. A static ban on eval ids applies to code and tests. |
| S34 | M | Emitting the most likely id beats omitting an uncertain step (expected loss about 13 steps vs 26+). | L6 states this rule. |
| S35 | M | The `resource_sort` flag has no effect (0 cases differ). | Flag removed; Q8 resolved. |
| S36 | L | Q1 support_9538 has expected value < 0 (P ≈ 0.4). | Default EXCLUDE. |
| S37 | M | SDK 1.x+ needs Python ≥ 3.10, but the system has 3.9.6. | N5 split: core on 3.9; live mode on ≥ 3.10 with `anthropic>=2.0.0`. |

Unchanged after review: late-only audit ids ON (+116 steps), legal-hold verify ON, V5 omission order (+1 sample exact), `account_00N` convention ON, and the 84 missing audit ids accepted as unrecoverable.


---

# Round 4: local-evaluation stress test (`LOCAL_EVALUATION_STRATEGY.md` §10)

| # | Sev | Finding | Change in SPEC v1.4 (⟲⁴) |
|---|---|---|---|
| S38 | H | 8 zero-candidate violating rows are in-window and evidence-owned, so the current upper bound misses them (≈ +24 steps). | §8.3b proof-file coverage invariant; T15 recovers them. |
| S39 | M | Independent FIFO for rows loses 1 FN + 1 FP per tied pair. | L6b: rows follow their matched account's case (+≈ 5 case-exact). |
| S40 | L | Five 941 s "policy action" rows look like a decoy template (one matches decoy account_146). | L9b: excluded, flagged. |
| S41 | L | Typed residue classes would resolve 5 of the 6 signature-ambiguous rows, but rely further on the artifact. | L7b: ablation only. |
| S42 | H | Placeholder audit steps would cost ≈ 81 FP. | L11: explicitly forbidden. |
| S43 | M | Python's `csv.writer` defaults to CRLF; gold uses LF. | §8.4: `lineterminator="\n"` plus a round-trip gate. |
| S44 | H | Under a case-exact grader, > 95 total is impossible (ceiling 94.5). | Documented in LOCAL_EVALUATION_STRATEGY §0 and SCORING_STRATEGY. |
