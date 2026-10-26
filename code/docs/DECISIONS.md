# Design decisions

Short records (context, decision, alternatives, evidence) for the choices a reviewer is most likely to
question. Rule ids refer to [SPEC.md](SPEC.md) and the module map is in
[ARCHITECTURE.md](ARCHITECTURE.md).

**How the evidence was measured.** Every number below was produced by running the shipped code on the
participant data. Comparisons toggle one flag at a time with `python3 code/main.py --llm off --flags name=off`
and diff the 518 evaluation rows against the default run; the public samples are scored with
`python3 -m evaluation score` (from `code/`). The records D3, D9, D11, D15, D16, D23 and D24 describe rules
that were **withdrawn** when the linker moved to process-order rules and an agent (D26 to D29); they keep
their numbers as history and say so. Figures in the other records were measured on the earlier linker unless
a record names the current run. The authoritative, regenerated numbers live in
`code/evaluation/evaluation_report.md`.

| Id | Decision | Flag or switch |
|---|---|---|
| D1 | Deterministic core with a narrow model role | none |
| D2 | The model reads text and images, and decides only contested links | `--llm`, `--agent` |
| D3 | Withdrawn: the worker-latency signature learned at runtime | none (was `--signature`) |
| D4 | Per-item content-addressed cache | `--llm cache` |
| D5 | Default models and the cheaper-intent comparison (Opus stays the default) | `--intent-model`, `--media-model` |
| D6 | No sampling parameters | none |
| D7 | Python 3.9 core, Python 3.10 for live calls | `requirements.txt` marker |
| D8 | Verify legal holds | `verify_legal_holds` |
| D9 | Withdrawn: late audit-record ids, and no placeholders | none (was `use_late_audit_ids`) |
| D10 | FIFO pairing for unresolvable ties | `fifo_pairing` |
| D11 | Withdrawn: the `account_00N` convention | none (was `handcrafted_account_convention`) |
| D12 | Exclude findings backed only by pre-request evidence | `allow_pre_request_findings` |
| D13 | `--llm batch` considered and not built | none |
| D14 | The operation table decides step order | none |
| D15 | Withdrawn: late evidence and the learned signature | none (was `strict_signature_time`) |
| D16 | Withdrawn: orphan policy rows are excluded | none (was `exclude_orphan_policy_rows`) |
| D17 | An ABSENT record to be redacted or anonymized gets no step | none |
| D18 | A bare user reference ties no record in a LINK-joined screen | none |
| D19 | Only deletion requests are linked | none |
| D20 | A generic support ticket takes its treatment from the activity event type | none |
| D21 | Known limitations kept on purpose | none |
| D22 | A topology snapshot that lists accounts proves account absence, for citing only | none |
| D23 | Withdrawn: a compliant worker row is not dropped for a short latency | none (was `signature`) |
| D24 | Withdrawn: strictly causal readings, which were on and what the others cost | none (every reading is now causal) |
| D25 | Stored media replies are redacted copies | `code/tools/redact_cache.py` |
| D26 | A bounded tool-calling agent decides contested links | `--agent`, `--agent-max-usd`, `--router-model`, `--agent-model`, `--verifier-model` |
| D27 | Process-order candidate rules replace the fitted windows | none |
| D28 | Evidence-owned accounts replace ownerless candidates | none |
| D29 | Every time rule is causal | none |
| D30 | The quality checks ship in `code/` | `python3 -m evaluation check`, `ghostaudit-eval` |

---

## D1. Deterministic core with a narrow model role

- **Context.** The task is graded on exact steps. A model that reasons freely about retention policy,
  ordering and citations would be hard to test, would drift between runs and would cost tokens on every
  one of the 518 cases.
- **Decision.** Decisions are explicit rules over parsed evidence: identity resolution, evidence parsing,
  linking, state at `audit_at`, policy mapping and step emission are plain, testable Python. The model
  never emits a status or a step.
- **Alternatives.** (1) Give an agent the raw files and ask for steps. It cannot be tested per rule and
  cannot guarantee that a cited file lies inside the time window. (2) Retrieval over the evidence with a
  model-written answer. It has the same problems and adds a retrieval error source.
- **Evidence.** The full 518-row output is produced offline in about 0.9 s wall time with `--llm off`
  (status counts 163 COMPLETE, 345 INCOMPLETE, 10 NOT_APPLICABLE), and two runs under different
  `PYTHONHASHSEED` values are byte-identical. Every step carries a recorded reason in `diagnostics.md`.

## D2. The model reads text and images, and decides only contested links

- **Context.** Two inputs are not machine-readable by rule: request text in many languages (does it
  authorize deletion?), and 15 images and PDFs (invoices, support records, internal screens). A third
  problem is not machine-readable by rule either once the fitted windows are gone (D27): which of several
  cases a worker row or an account row belongs to.
- **Decision.** The model handles those three jobs and never emits a step or a status. Intent and media
  output is schema-checked and enters the deterministic core as an `IntentDecision` or as `MediaFacts`
  mapped to observations through grounded links (a LINK activity row, or a literal id plus a resolvable
  identifier); display labels are never promoted to resource ids. The contested-link decisions are made by
  the bounded agent of D26 and enter the linker as `LinkDecision`s.
- **Alternatives.** Rules only for intent (a lexicon is kept as the fallback and as a disagreement
  detector). Rules only for media (impossible for images without OCR). Rules only for contested links (the
  fallback; D26 measures what it costs).
- **Evidence.** With `--llm off`, the lexicon alone classifies 10 of 550 texts as non-deletion, and all
  10 sit next to an intake "non-deletion" activity row. All 32 public samples are authorized
  deletions. Without a model the run degrades but never fails (N7): `--llm off` writes 518 valid rows
  (163 COMPLETE, 345 INCOMPLETE, 10 NOT_APPLICABLE) in about 0.6 s.

## D3. Withdrawn: a worker-latency signature learned at runtime

- **Context.** The activity stream holds roughly 4,000 rows, and many "worker" rows cannot be tied to a
  case by an identifier. The earlier linker fitted, from evidence-anchored pairs, the offsets modulo 60 s
  and the offset range between an account row and its worker rows, and kept only the edges that matched.
- **Decision.** Removed, with its flags (`signature`, `strict_signature_time`), its `--signature` option, the
  held-out validation in the diagnostics and the orphan rule that depended on it (D16, D23). The regularity is
  a property of how the dataset was generated, not of the business process, so it is not a rule a deletion
  audit can defend; the fitted offset windows of the same origin went with it (D27).
- **Alternatives.** Keep it as a low-confidence fallback (it would still be a fitted filter, and the agent
  makes it unnecessary where evidence exists); keep only the offsets as data the agent may read (done: the
  tools show `offset_from_requested_s` and `offset_from_reported_s`, never a filter).
- **Evidence.** Before the removal the signature changed 85 of 518 evaluation rows and no status, and the
  public samples scored 32 of 32 status and 30 of 32 row-exact. After D27 to D29 with the agent off the
  samples score 31 of 32 status and 6 of 32 row-exact (step F1 0.9948 to 0.8471), and 264 evaluation rows
  differ from the earlier `output.csv`, none by status. The drop is the price of rules that need no fitted
  constant; the agent exists to win it back.

## D4. Per-item content-addressed cache

- **Context.** A rerun must reproduce a live run exactly, must not cost tokens, and must not depend on
  how requests were grouped into a batch.
- **Decision.** Each model request is keyed by the SHA-256 of its canonical content (model, system
  prompt, messages, `max_tokens`, prompt version, effort, schema, attachment hashes). Intent uses one key
  per text, so a decision does not depend on batch composition and batches are formed only from misses.
  Entries are single JSON files written atomically (temp file plus `os.replace`) and hold no request and
  no credential. The cache directory (`code/ghostaudit/cache`) is meant to be committed, so a reviewer can
  run `--llm cache` without an API key.
- **Alternatives.** Cache by batch (changes when one text changes); store full requests (leaks text and
  size); no cache (cost and nondeterminism on every run).
- **Evidence.** `--llm cache` with an empty cache directory writes a byte-identical `output.csv` to
  `--llm off` (the miss path falls back to the lexicon and skips media). Editing a prompt changes the
  prompt text inside the key, so only the entries it affects are invalidated.

## D5. Default models and the cheaper-intent comparison (Opus stays the default)

- **Context.** Intent is a short classification and media extraction reads images, so they may not need
  the same model.
- **Decision.** The default intent model and the default media model are both `claude-opus-5-5`; the
  repository owner chose the quality-first intent classifier. Strategy S2 evaluates the cheaper
  `claude-haiku-5-5` for intent (media stays Opus). Measured: on every sample and evaluation row the two
  intent models give the same answers, and the cold-run cost of S2 is well under half of S1's. That gap is
  the price of the default, accepted on purpose and not an accuracy gain. Models and prices live in
  `config.py` (`DEFAULT_PRICES`: Opus $4 input and $20 output per million tokens with $0.20 cache reads;
  Haiku $0.10 and $0.50) and can be overridden with `--intent-model` and `--media-model`. The intent step has
  a safety net the media step lacks: a verdict below the confidence floor, or a cache miss, falls back to
  the keyword lexicon (D4).
- **Alternatives.** Haiku for intent (S2: identical answers on the measured rows at a fraction of the cost,
  one flag away: `--intent-model claude-haiku-5-5`; not the default because the owner prefers the
  stronger classifier on rows that no measurement covers, such as a new language or a subtle negation).
  Haiku for both roles (media needs the stronger vision model, and a wrong `resource_id` costs more than the
  saved tokens).
- **Evidence.** Both strategies are scored with the same code (`evaluation/`), and their accuracy, token
  use and cost are reported in `evaluation/evaluation_report.md` and `evaluation/usage_report.md`. This
  record states the decision rule and does not duplicate those numbers, so it cannot drift from them.

## D6. No sampling parameters

- **Context.** Current API versions reject `temperature`, `top_p` and `top_k`, and the newest models
  default to a medium reasoning effort.
- **Decision.** No request carries a sampling parameter. Determinism comes from the cache (D4), from
  structured outputs (`output_config.format` with a JSON schema, checked again by a stdlib validator), a
  fixed `max_tokens`, an explicit `output_config.effort="low"` and a system prompt with `cache_control`.
  `refusal` and `max_tokens` stop reasons raise a typed error and the caller falls back to the rules.
- **Alternatives.** `temperature=0` (rejected by the API and not deterministic anyway); prefilled assistant
  turns (rejected by these models).
- **Evidence.** Unit tests assert that no built request body contains `temperature`, `top_p` or `top_k`
  (`test_llm_cache`, `test_intent`, `test_media_extract`, `test_live_toolchain`), and `test_static` scans
  the shipped source for them.

## D7. Python 3.9 core, Python 3.10 for live calls

- **Context.** The review machine's `python3` is 3.9.6, but the current SDK needs 3.10.
- **Decision.** The core, `--llm off` and `--llm cache` use the standard library only and run on
  3.9: `from __future__ import annotations`, frozen dataclasses without `slots`, no `match`, no
  `zip(strict=)`. `--llm live` needs 3.10 and `anthropic==2.3.0`, pinned in `requirements.txt` with the
  marker `; python_version >= "3.10"`. The SDK is imported lazily, and an unmet requirement raises
  `LLMUnavailable` with a message that says what to install (N5, N7).
- **Alternatives.** Require 3.10 everywhere (breaks the default offline run on the review machine); vendor
  an HTTP client (more code to review for no gain).
- **Evidence.** The whole unit suite and the offline run pass on Python 3.9.6.

## D8. Verify legal holds

- **Context.** Rule 13 retains legal-hold records, but the challenge text only demands verification of
  records "required by policy". The samples contain no legal hold, so nothing public confirms the step.
- **Decision.** A legal hold linked to the subject gets `legal_service VERIFY_RECORD_PRESENT` (V3),
  behind `verify_legal_holds` (default on). Retained records are never findings and never remediated.
- **Alternatives.** Omit them (risks missing a required "retained record remains available" check).
- **Evidence.** Turning it off changes 10 evaluation cases, one step each (3258 to 3248 steps in the default run) and no status.
  The diagnostics list each case as a rule that fired without a public sample to test it.

## D9. Withdrawn: late audit-record ids, and no placeholders

- **Context.** Security audit records are retained (rule 12). The case needs a `VERIFY_RECORD_PRESENT`
  step, but the id is often only visible in a file captured after `audit_at`.
- **Decision.** The earlier linker emitted an id found only in a later file as a future verification step
  of an INCOMPLETE case (`use_late_audit_ids`). That reads evidence that did not exist at `audit_at` and is
  gone (D29): an audit record is emitted only when a file captured in `[reported_at, audit_at]` names it
  (L11). A placeholder id is still never invented.
- **Alternatives.** Keep late ids (they match five public sample answers); emit placeholder ids (an invented
  id is a wrong record).
- **Evidence.** Under the earlier linker 124 evaluation cases carried one late-only audit step and five
  public samples (09, 23, 24, 29, 30) depended on it. Now the evaluation cases split into 300 with an audit
  record named inside their window and 218 without; the label-free audit-record parity check, which uses the
  same causal definition, reports 0 failures.

## D10. FIFO pairing for unresolvable ties

- **Context.** After identifiers, process order, ownership and the agent, groups of accounts or worker
  rows can remain symmetric: the data cannot say which belongs to which case.
- **Decision.** Pair them in ascending id order (accounts) or by the report nearest in process order (rows)
  against ascending case id (L6, L6b), mark every such link `basis=fifo_pairing` or `coupling`, and let a
  worker row follow its matched account's case. This is the deterministic fallback of the agent stage and it
  is low confidence: the diagnostics count every case that carries it.
- **Alternatives.** Omit the ambiguous steps, which loses the step with certainty and shifts the order of
  the steps after it; assign randomly, which is not deterministic.
- **Evidence.** With the process-order candidates the contest is large: 784 evaluation worker rows are shared
  by several cases after the fixed point, and 401 evaluation cases carry a fallback link. Switching the
  fallback off changes 220 evaluation rows and no status, and the **public samples score better without
  it**: 32 of 32 status, 8 of 32 row-exact and step F1 0.8937 against 31, 6 and 0.8471 with it, because a
  wrong pairing adds findings that do not belong to the case while a missing pairing only omits steps. It is
  still on by default because the agent is meant to decide these links first; whether the fallback should
  be off is the repository owner's decision (`--flags fifo_pairing=off`).

## D11. Withdrawn: the `account_00N` convention

- **Context.** A few hand-crafted cases have no deletion-worker row, and no activity row or evidence names
  their account. The public samples show that these subjects (`user_0N` and `user_10`) own `account_00N`.
  The earlier solver derived the account id from that convention (L12.3), flagged `account_basis=convention`.
- **Decision.** Removed with its flag `handcrafted_account_convention`, its constants and its diagnostics.
  An id that no participant-visible file contains is never emitted (SPEC 1.2): such a case now has no account
  step unless evidence (L12.1) or an activity pointer (L12.2) names the account.
- **Alternatives.** Keep it as a flagged fallback (the earlier state; it rests on the public samples alone and
  is the one derived id of the solver).
- **Evidence.** The convention touched three evaluation cases, one step each, and one public sample. Now the
  public samples without a worker account row (02, 05, 08, 22 and 26) lack that step in 02, 08, 22 and 26;
  the status of all five is right. The static test rejects any id parse (`tests/test_static.py`).

## D12. Exclude findings backed only by pre-request evidence

- **Context.** For a few image-family subjects, the only evidence of a resource's state was captured before
  the request, so it cannot be cited under T3 (`reported_at <= captured_at <= audit_at`), while the later
  file only shows a reference to the resource.
- **Decision.** Do not emit a finding for such a resource (Q1). The flag `allow_pre_request_findings`
  (default off) is the only switch.
- **Alternatives.** Emit the finding with the early file as its citation (violates T3 and risks citing an
  inadmissible file), or emit it uncited (a finding must cite).
- **Evidence.** The affected resources need image facts, so toggling the flag with `--llm off` changes 0
  rows. The measured effect belongs to the live run and is reported in the evaluation report.

## D13. `--llm batch` considered and not built

- **Context.** The Message Batches API costs 50 % less than synchronous calls (`BATCH_DISCOUNT` in
  `config.py`).
- **Decision.** Not implemented. `Config` reserves the mode name, and the CLI offers `off`, `cache` and
  `live`.
- **Reasoning.** The workload is one full run: 550 request texts in batches of 25, which is 22 calls, plus
  15 media files, one call each. Batches are asynchronous, so they would add polling and result matching
  to a code path that the per-item cache (D4) already makes free on every rerun. The saving applies to one
  cold run only.
- **Alternatives.** Build it for cost. It stays a documented option if the cold-run cost grows.
- **Evidence.** The cold-run cost is reported in `evaluation/usage_report.md`.

## D14. The operation table decides step order

- **Context.** The challenge prose says to process downstream copies before source records, but the public
  answers follow a fixed order inside each phase.
- **Decision.** Steps are sorted by `(phase, operation index in the operation table, system_id,
  resource_id)` with plain string comparison (8.4). Where the prose and the table disagree, the table wins.
- **Alternatives.** Dependency-graph ordering of resources; natural sort of ids. Neither changes any
  sample or evaluation case, so the extra code was not kept.
- **Evidence.** The order metric on the public samples is 1.0 (`exact_order` in the scorer). Every
  emitted row is checked by the contract validator.

## D15. Withdrawn: late evidence and the learned signature

- **Context.** Evidence that did not exist at `audit_at` must not change a case (T1, T4). The
  override-ban test `test_late_evidence` adds, to a copy of the dataset, a file captured after every
  `audit_at` and tail lines stamped after every `audit_at` that list every case account as present,
  once without and once with the person's email.
- **Decision.** The signature this record fitted per case is gone with D3. The other late readings it
  disclosed are gone too (D29): the owner filter cuts at each case's own `audit_at`, and a later file
  supplies no id.
- **Alternatives.** Keep the disclosed late readings because the public gold uses them (D9, D24).
- **Evidence.** `test_late_evidence` still holds: both injected variants leave the 518 evaluation rows
  byte-identical, and a control that backdates the same content into the windows changes answers, so the
  test can fail.

## D16. Withdrawn: orphan policy rows are excluded

- **Context.** Some "policy action completed" worker rows fit only accounts that no request owns. Linking
  them to a requesting case would add a compliant step for a person who has none of that data.
- **Decision.** The exclusion (`exclude_orphan_policy_rows`) depended on the learned signature and changed 0
  of 518 rows; it is removed with it. A row that follows no account of its case is still dropped as a decoy
  by the process-order rule of the fixed point (L4d), and a row owned by a user without a case is dropped by
  the owner filter (L4a).
- **Alternatives.** Keep the rule without the signature (nothing to base it on).
- **Evidence.** `test_link_solver` (decoy tests) covers both remaining drops.

## D17. An ABSENT record to be redacted or anonymized gets no step

- **Context.** A support message (REDACT) or analytics record (ANONYMIZE) can resolve to ABSENT, most
  often because an inventory scope captured before the record appeared lists its system without it. The
  earlier builder treated "not REDACTED" as violating and emitted `REPORT_EXPOSED_PII` citing that
  scope, a finding whose own proof file shows the record is not there (caught by the P2a locator check).
- **Decision.** Such a resource is neither violating (the violating state of section 6 is EXPOSED) nor
  compliant (no redaction can be verified on a record that is gone): it is dropped, counted as
  `ABSENT under REDACT or ANONYMIZE` in the diagnostics and, for a LINK-row resource, listed with the
  hand-crafted notes (SPEC 8.2).
- **Alternatives.** Keep the finding (self-contradictory citation); verify it as REDACTED (the proof shows
  absence, not redaction); report it as REMAINING (wrong operation for its category).
- **Evidence.** A narrow rule: offline it fires on 2 evaluation resources, both of image-family cases,
  and no public sample. It changes one evaluation row, from INCOMPLETE with a scope-cited finding to
  COMPLETE with no step; that case's diagnostics list the unread support screen captured in its window.
  The other resource was already dropped, now with this reason. With the media facts filled, the
  screen's EXPOSED observation is later than the scope and decides the state, so the rule should not
  fire there; this is to be re-checked on the cache-filled run.

## D18. A bare user reference ties no record in a LINK-joined screen

- **Context.** A security audit screen lists several signed events under one subject filter and shows
  the same `user_<n>` on every row. Only one of its events has a catalog LINK row (and a retention
  extract). The extraction copies the filter into every record, so the literal-id path (F10 b) tied all
  of them to the subject and one case cited six audit records. No other case has more than one, and
  the public samples have at most one.
- **Decision.** In a file where some record joins a LINK row, a record that reaches the subject only
  through a bare `user_<n>` (no email, no phone) is not mapped; the diagnostics note says why. A record
  that shows an email or a phone, or joins a LINK row, is unchanged.
- **Alternatives.** Keep all six (five citations rest on a repeated filter); drop every user-only record
  (a file with no LINK row, such as a retention extract, would lose its only key).
- **Evidence.** On the cache-filled run the rule fires on exactly one file and changes one evaluation row, from seven
  steps to two (the account step and the one linked audit record). The label-free invariant on
  audit-record discovery, which cannot read images, now excuses an emitted record that a LINK row ties
  to the subject, so the shipped output passes it.

## D19. Only deletion requests are linked

- **Context.** Linking pairs deletion-worker account rows with requests. A request that does not
  authorize deletion took part in that pairing, and one of them took the account row of a deletion
  case whose rows then had no free account, so that case lost its account verification step.
- **Decision.** The pipeline passes only the requests whose intent is deletion to linking and to the
  extras. A request that is not a deletion gets empty links and the row `[]`.
- **Alternatives.** Keep every request in the pairing (a non-deletion request cannot own a worker run);
  drop only the first-in-first-out pairing for such requests (a partial fix).
- **Evidence.** Exactly one of 518 evaluation rows changes: a COMPLETE case gains its account
  verification step. No status changes and the public samples keep their scores.

## D20. A generic support ticket takes its treatment from the activity event type

- **Context.** A support record is either a message (REDACT) or an attachment (DELETE), but service
  exports (`tickets`) and the `support_ticket_read_completed` log event look the same for both. The
  earlier code labelled every such observation SUPPORT_MESSAGE, which overrode the worker's own
  activity event and redacted ten attachments.
- **Decision.** Those two observations carry no category, so the treatment follows the worker's activity
  event type (`DELETE_RECORD` means an attachment: delete; `REDACT_RECORD` means a message: redact).
  Specific evidence still wins: a `SUPPORT_ATTACHMENT` or `SUPPORT_MESSAGE` record type, an
  `attachment_pii_scan` or `message_pii_scan` event, a `message_read` with `[REDACTED]` text, an
  attachments collection or a conversations collection.
- **Alternatives.** Keep SUPPORT_MESSAGE as the default for generic tickets (the common kind, 163
  REDACT_RECORD rows against 29 DELETE_RECORD, but wrong whenever the worker ran a delete).
- **Evidence.** Ten evaluation rows change, three steps each (30 steps): the finding becomes
  `REPORT_REMAINING_RECORD`, the remediation `DELETE_RECORD` and the check `VERIFY_RECORD_ABSENT`. No
  status changes and the public samples keep their scores (32 of 32 status, 30 of 32 row-exact).

## D21. Known limitations kept on purpose

- **Context.** Three behaviours are visible in the output and are not fixed, because each fix would cite
  or assert something the evidence does not prove.
- **Decision.** (1) A COMPLETE row has no `account_service` step when no file inside the case
  window proves the account absent and the omission rule finds no admissible proof (the run logs each as
  "account step omitted (no proof file)"); citing a file that does not prove the state would be a wrong
  citation. After D22 no evaluation row is in this state (it was 12 of 153 before). (2) Three evaluation cases take the account id from the hand-crafted sample convention
  (`user_0N` owns `account_00N`, L12.3) when no other evidence supplies it. (3) One audit screenshot lists
  six signed events for one subject; the solver emits the one that a catalog LINK row ties to the subject
  (D18), because every public sample has at most one audit step per case.
- **Alternatives.** Cite the nearest file for (1); drop the convention for (2), which is inferred from the
  public samples (`handcrafted_account_convention` off changes those 3 rows); emit all six records for (3).
- **Evidence.** The counts above come from the shipped run; nothing here changes a status.

## D22. A topology snapshot that lists accounts proves account absence, for citing only

- **Context.** A COMPLETE case proves its account absent by omission (V5): some in-window file enumerates
  `account_service` and does not list the account. Topology SQL snapshots (a primary plus replica tables)
  carried no scope, so a case whose other steps cite such a snapshot could not cite it for the account.
  The rule fell back to the earliest unrelated inventory or failover file, or dropped the account step.
  Every generated COMPLETE sample cites one family snapshot for all of its steps, the account step included.
- **Decision.** A topology snapshot holding at least one `account_service` row yields an `account_service`
  scope marked `cite_only` whose present ids are the union over its tables. Omission rule V5.1 (a file
  the case already cites) may use it. The window fallback V5.2 and state resolution ignore it, because it
  would otherwise outrank the gold failover file of three public samples and would add a state proof that
  the other scopes do not give.
- **Alternatives.** A full scope (rejected: it changes samples 01, 02 and 04); keep the fallback to an
  unrelated file (a cite from another cohort); keep dropping the step (a lost step).
- **Evidence.** 33 evaluation rows change, all COMPLETE and staying COMPLETE: 21 cite their own cohort's
  snapshot instead of an unrelated file and 12 gain the account step. No omitted account step remains.
  The public samples are unchanged (32 of 32 status, 30 of 32 row-exact). Tests: `test_sql`, `test_state`.

## D23. Withdrawn: a compliant worker row is not dropped for a short latency

- **Context.** The learned compliant offset range started at 1330 s, so a policy row 941 to 1301 s after
  its account fitted no account and was dropped as a decoy; the earlier fix retried with a lowered bound.
- **Decision.** Moot: there is no learned range, so a row is dropped only when it precedes every account of
  its case (L4d).
- **Alternatives.** None needed.
- **Evidence.** `test_link_solver`: the ownerless row that precedes the account is dropped, the owned one
  is kept.

## D24. Withdrawn: strictly causal readings, which were on and what the others cost

- **Context.** The challenge rule is to use only information available at or before `audit_at`. The earlier
  solver kept three readings of later evidence on because the public answers use them: the owner filter, late
  audit ids and the `account_00N` convention.
- **Decision.** All three are off, and the signature fit is gone: nothing reads evidence after a case's
  `audit_at` (D29).
- **Alternatives.** Keep the three flags (the earlier state, where each was disclosed and measured).
- **Evidence.** Under the earlier linker the strict readings moved 11, 124 and 3 evaluation rows and cost the
  public samples two, five and one exact matches (table in the git history of this file). The current run
  has no such flags; the combined effect of D27 to D29 is in D3.

## D25. Stored media replies are redacted copies

- **Context.** The response cache replays what the vision model transcribed from the 15 images and PDFs, and
  the transcription lists the emails, phones and names those fictional artifacts show. Shipping them in
  `code.zip` put personal-looking data into the archive although the solver only needs a way to match them.
- **Decision.** A stored media reply keeps an email only as `sha256:` + sha256(lower-cased email) and a phone
  only as `sha256:` + sha256(its digits); names are dropped, because names are never matching keys (I4).
  Each redacted entry has the top-level field `"redacted_at_rest": "emails/phones hashed (sha256), names
  removed; original model text not retained"`. `evidence/media.py` turns a digest into the key an identity
  already holds (`h:` for emails; the new `hp:` for phones, the sha256 of the identity's phone digits, added in
  `identity.py`), and a LINK row's email also agrees with a digest. A reply is canonicalised before the names
  go (`parse_records`), so a fact that was derived from a listed name (`pii_fields_shown`) is stored as a
  fact. Future live writes are redacted by the same function (`redact_reply`) before they reach the
  disk cache; the live caller still sees the reply as sent. A reply that fails the schema is stored as an
  empty string. The intent entries hold request texts only; none contains an email, so they are unchanged.
- **Alternatives.** Keep the plain text (the earlier state, a build note only); delete the media entries
  (the offline replay then reads no image or PDF and loses the media-backed steps); encrypt them (a key to
  manage for no gain, since only matching is needed).
- **Evidence.** One run of `python3 code/tools/redact_cache.py` rewrote the 15 media entries (18 emails and
  3 phones hashed, 7 names dropped). `output.csv` is byte-identical (sha256 23eacbff...), the 22 media
  observations resolve to the same subjects, and the media notes stay at 0. Tests: `test_redaction` (key forms,
  redaction, mapping equivalence, live write, tool, committed cache), `test_media_mapping`, `test_build_zip`.
  The usage figures are those of the original calls; the stored text is a redacted copy of their output.

## D26. A bounded tool-calling agent decides contested links

- **Context.** After process order, ownership and the fixed point, hundreds of worker rows and accounts are
  still candidates of several cases (784 evaluation rows are contested). The data does not separate them by a
  rule that a deletion audit can defend; the evidence sometimes does (a record that names an identifier of the
  subject), and a person reading it would use the evidence.
- **Decision.** A router (model) chooses which cases need an investigation; the cases that compete for the
  same targets form a unit; one bounded tool-use loop per unit lets the model call six typed tools
  (`resolve_identity`, `search_evidence`, `read_evidence`, `get_activity`, `check_policy`, `submit_answer`) and
  assign, reject or answer UNSURE for each target; a verifier re-checks every assignment of an INCOMPLETE
  answer and a critic model approves or rejects it. The guardrails sit in the tools and the submit gate, not
  in the prompt: the cutoff, the policy mapping, the citation ledger and the output schema (SPEC 12.3). The
  loop is capped at `MAX_ITERATIONS = 8` calls per unit, `CALL_TIMEOUT_S = 90` per call and `--agent-max-usd` per
  run; a cap, a timeout, an LLM error, a cache miss, three rejected submits or an all-UNSURE answer end the
  unit in the deterministic fallback, counted by reason. Router, agent and verifier use `claude-opus-5-5`.
- **Alternatives.** A fixed stage sequence with a model only in the intent and media steps (the earlier
  design; the contested links then fall to FIFO, D10). One free-form agent over all the files (untestable per
  rule and unable to guarantee the cutoff). A router written as rules (the user chose model-driven routing).
- **Evidence.** `test_agent_loop` (iteration cap, timeout, cost cap, cache miss, LLM error, invalid submit,
  UNSURE), `test_agent_tools` (post-cutoff evidence never returned, invalid and future citations rejected,
  every tool schema strict) and `test_agent_stage` (router failure investigates everything, a verifier
  rejection falls back, a recorded run replays byte for byte). With no cached agent response every unit falls
  back and `--agent on` equals `--agent off`. Two live Opus 5.5 runs then filled the cache (the first stopped at
  the $5 cap after 28 of 64 units, the second at a $15 cap finished the rest): `python3 -m evaluation score
  --agent-ablation` now shows 63 of 64 units decided by the agent, 73 evaluation rows changed, and samples
  31/32 to 32/32 status, 6/32 to 8/32 row-exact, step F1 0.8471 to 0.8958.

## D27. Process-order candidate rules replace the fitted windows

- **Context.** The earlier candidate windows (`reported_at - 1.3 h` to `- 0.7 h` for accounts, `-30 min` to
  `-2 min` for policy rows, `+30 min` to `+135 min` for violation rows) were widened by hand while looking
  at the data. Measured on the participant files, the rows that evidence ties to a subject lie 0.73-1.25 h
  before the report (account), 0.05-0.48 h before it (policy) and 0.63-2.22 h after it (violation, flow,
  restore): the windows are the observed spread.
- **Decision.** Candidates follow the order of the process only: work for a request happens after
  `requested_at`; an account row and a policy row are recorded at or before `reported_at`; a violation, flow
  or restore row is recorded after `reported_at` and at or before `audit_at` (L2, L3). No constant, offset or
  residue is used; the agent is shown the offsets as data.
- **Alternatives.** Keep the fitted windows as a clearly named low-confidence fallback (not done: they are
  the dataset-fitted values the change set out to remove, and the measured spread above is available to the
  owner if the fallback is wanted back); nearest-preceding-row as a tie-break (checked on the samples: it picks
  the gold account for 17 of 28 cases that have candidates, so it is not a rule).
- **Evidence.** The grounded bounds admit every row the windows admitted and many more: the contest grows to
  784 evaluation rows shared by several cases and 401 evaluation cases carry a fallback link. With the agent
  off the samples go from 32 of 32 status, 30 of 32 row-exact, F1 0.9948 to 31 of 32, 6 of 32, 0.8471; the
  status mix of the 518 rows is unchanged except 10 COMPLETE cases that become INCOMPLETE (163 to 153), and 264
  rows differ from the earlier `output.csv`. Tests: `test_link_candidates`, `test_link_solver`.

## D28. Evidence-owned accounts replace ownerless candidates

- **Context.** L1 (an identifier link) is the strongest link in the specification, but the fixed point kept a
  case's ownerless account candidates next to the one that evidence ties to its own subject, so a rival's
  claim could remove the owned account from the case that owned it.
- **Decision.** Of a case's account candidates, the ones that evidence admissible at its `audit_at` ties to
  its own subject replace the ownerless ones before the fixed point (`LinkGraph._pin_owned_accounts`). The
  claim propagation of L4c is unchanged. The label of a row decided by the fallback or the agent is never
  shown as `evidence_owner`.
- **Alternatives.** Leave the pool as it was (the label-free recall sweep found nine evaluation cases whose own
  evidence-tied account was linked to another case); prefer the owner over a rival's claim without pinning (a
  second rule with the same effect and more code).
- **Evidence.** Before the change the label-free checks reported 9 unexplained recall items and 10 unexplained
  coverage items, and the samples scored 5 of 32 row-exact and F1 0.8350; after it 0 and 0, 6 of 32 and
  0.8471. The check `python3 -m evaluation check` reports 0 hard failures. Tests: `test_link_solver`.

## D29. Every time rule is causal

- **Context.** The earlier solver read later files in three places: the owner filter (a resource's evidence
  owners from every file), late audit ids (D9) and the signature fit (D15, D24).
- **Decision.** Nothing after a case's `audit_at` influences its links, owners or ids (SPEC T4). An evidence
  owner counts for a case only when a file admissible at that case's `audit_at` ties it; an audit record is
  emitted only when a file captured inside the case window names it; the agent's tools cut every answer at the
  case's `audit_at`. The flags `strict_owner_time`, `use_late_audit_ids` and `strict_signature_time` are gone;
  the strict behaviour is the only behaviour.
- **Alternatives.** Keep the three flags, on or off (D24).
- **Evidence.** `test_late_evidence` (a file and log lines after every `audit_at` change no row, a backdated
  control does), `test_link_extras` (an audit id found only before the report or after the audit is not
  emitted), `test_agent_tools` (the cutoff and the ledger), and the label-free invariants of
  `python3 -m evaluation verify`, whose audit-record parity now uses the same window.

## D30. The quality checks ship in `code/`

- **Context.** The contract validator, the invariants, the determinism check and the scorer were reachable only
  through `devtools/` and the documentation, which the submission archive does not contain.
- **Decision.** `python3 -m evaluation check` (from `code/`, or `ghostaudit-eval check` after `pip install -e
  code`) runs the solver twice under `PYTHONHASHSEED=0` and `4242` and verifies the exact header, LF endings and
  518 rows; `ghostaudit.contract.validate_file` on the written file; byte-identical output and sample
  predictions; the label-free invariants of `evaluation.verify_report`; and the sample score. `score`, `verify`
  and `custom` are subcommands of the same entry point. The CLI lives in `ghostaudit/cli.py`; `code/main.py` is a
  three-line shim; no module edits `sys.path`; `pyproject.toml` declares the build backend, the package
  discovery and the `ghostaudit` and `ghostaudit-eval` scripts.
- **Alternatives.** Keep the checks in `devtools/` (outside the archive); add a standalone script per check
  (five commands to remember).
- **Evidence.** `test_check` (format problems, thresholds, dispatch, a full run), `test_packaging` (script
  targets resolve, no `sys.path` edit, build metadata), `test_static` (no `sys.path` edit under `code/`).

---

## Rule provenance ledger

Every switch in `Config.flags`, classed by how much public evidence supports its default. The class follows
the sample support: `evidenced` when the default keeps two or more of the 32 public sample cases row-exact,
`weak` for one, `inferred` for none. For a switch whose default is off, the support counts the samples that
the off setting keeps exact. The table is regenerated by `python3 devtools/confidence.py --ledger` (every
variant runs offline in the default `--llm cache` mode, replaying the stored model responses) and `--check`
fails when it has drifted. `devtools/` holds the release-process tooling and is not part of the submitted
archive, so the "class" and sample-support columns cannot be regenerated from the archive. The "Eval rows
changed" column can: it is the last column of the assumption ledger printed by `python3 -m evaluation score
--ablate`. The figures describe the code at the time of writing, with the agent off or replaying an empty
agent cache.

<!-- BEGIN:ledger -->
| Flag | Default | Class | Sample cases it keeps exact | Sample cases it breaks | Eval rows changed when flipped | Relied on |
|---|---|---|---|---|---|---|
| `verify_legal_holds` | True | inferred | 0 | 0 | off: 9 | - |
| `allow_pre_request_findings` | False | weak | 1 | 0 | on: 0 | - |
| `fifo_pairing` | True | inferred | 0 | 2 | off: 220 | 401 eval cases |
| `never_mix` | True | inferred | 0 | 0 | off: 7 | 1 eval cases |
<!-- END:ledger -->

Reading the table: the legal-hold verification and never-mix have no public sample that exercises them: they
are inferred, switchable, and their evaluation exposure is the column to read (D8). The pairing fallback
(`fifo_pairing`) is the rule the agent is meant to make rare: switching it off keeps two more public samples
exact (D10).
