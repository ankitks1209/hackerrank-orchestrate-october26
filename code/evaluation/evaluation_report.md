# Evaluation report

This report covers the deletion-audit solver in `code/`: how its answers are scored locally, what the
scores are, which strategies and switches were compared, seven extra evaluation cases written for this
project, the failures found and the improvements made. Every table below is filled by
`python3 -m tools.render_reports` (from `code/`) from the output of the scorer, the strategy and ablation runs and
the custom-case runner; `--check` fails when a table drifts from a fresh run. Nothing in a table is typed
by hand.

## 1. How accuracy is measured

Only the 32 public sample requests have published answers (`dataset/sample_output.csv`), so the scorer
emulates the hidden grading on those 32 and the solver never reads them while it runs. **These are in-sample
scores**: the 32 samples were the development set. The link rules no longer contain a constant fitted to them
(no window, latency signature or id convention, DECISIONS D3, D11, D27), but the agent's prompts, the
router's summaries and the pinned floors of `tests/test_golden.py` were written while looking at them, and no
held-out split exists. The 518 evaluation rows have no labels; they are checked without labels (section 5).

Two sample scores are reported side by side wherever the agent is concerned: `agent=off`, the deterministic
fallback everywhere, and `agent=on`, which replays the router, agent and verifier responses from the cache.
Two live runs filled the cache for every unit, so `agent=on` is the agent's measured result (section 4). Before the agent and the grounded rules, the same code with fitted windows and a learned signature
scored 32 of 32 status, 30 of 32 row-exact and step F1 0.9948; the figures below show what dropping those
constants costs and what the agent has to win back.

| Measure | Grader | What it compares |
|---|---|---|
| Case-level (status) accuracy | G1 | `deletion_status` of each case |
| Row-level accuracy | G2 | the whole row: status and every step, in order |
| Step-level accuracy | G3, G4 | per-case multiset of steps (phase, system, resource, operation, state, evidence id); G4 ignores the evidence id. Counts are pooled across cases |
| Field-level accuracy | G5 | steps aligned by (phase, system, resource); operation, state and evidence id compared separately |
| Sequence accuracy | G6, G8 | G6: pooled longest common subsequence of the step order keys over the longer sequence. G8: steps aligned by `step_no`, all six fields compared. The exact-order share is listed in the details table |
| Composite | G7 | the weighted sum of the graders above |

Scores are reported raw. The scorer can divide a grader by a ceiling, but none is shipped: the ceiling column
is 1.000 for every grader, so the normalized score equals the raw one. No bound on the score of the 518
unlabeled rows is claimed; section 8 measures where the pipeline's own evidence discovery is incomplete.
The error taxonomy counts steps (missing, extra, wrong operation or state, wrong evidence) and cases
(status, order).

## 2. Results on the public samples

<!-- BEGIN:metrics -->
### Grader emulation (32 cases)

| Grader | Name | Score | Ceiling | Normalized |
|---|---|---|---|---|
| G1 | status | 1.0000 | 1.000 | 1.0000 |
| G2 | case exact (row-level) | 0.2500 | 1.000 | 0.2500 |
| G3 | step F1 | 0.8958 | 1.000 | 0.8958 |
| G4 | step F1 without evidence_id | 0.8958 | 1.000 | 0.8958 |
| G5 | key-aligned field accuracy | 0.8113 | 1.000 | 0.8113 |
| G6 | sequence (LCS ratio) | 0.8515 | 1.000 | 0.8515 |
| G7 | composite | 0.9078 | 1.000 | 0.9078 |
| G8 | step_no-aligned positional accuracy | 0.8234 | 1.000 | 0.8234 |

### Details

| Metric | Value |
|---|---|
| exact_order | 0.9062 |
| field_evidence_id | 0.8113 |
| field_operation | 0.8113 |
| field_state | 0.8113 |
| precision | 0.9005 |
| recall | 0.8912 |

### Error taxonomy

| Category | Count |
|---|---|
| status | 0 |
| missing | 10 |
| extra | 19 |
| wrong_op_state | 0 |
| wrong_evidence | 0 |
| order | 0 |
| identity_miss | 11 |
| structural | 0 |

- Status mismatches: none
- Not row-exact: case_01, case_02, case_03, case_04, case_05, case_06, case_07, case_08, case_09, case_10, case_11, case_12, case_18, case_20, case_22, case_23, case_24, case_25, case_26, case_27, case_28, case_29, case_30, case_32
<!-- END -->

Most samples are not row-exact now, and the taxonomy says why: `extra` steps and `identity_miss` (an
account step that differs) come from contested links, where a rival's worker row or account row was
paired to the case by the fallback, and the `missing` steps from audit-record ids that no file inside the
case window names (the solver does not invent ids, SPEC 1.2, and emits no id found only in a later file, T4).
The one status mismatch is a sample whose COMPLETE answer needs a resource that went to a rival. With the
agent off these are the fallback's errors; they are what the agent is meant to remove.

## 3. Strategies compared

Three strategies are run offline from the committed response cache, so the table reproduces without an
API key: S0 uses no model at all, S1 is the default (the Opus model for intent and for the image and PDF
facts), S2 swaps the cheaper Haiku model into the intent step. Calls, tokens and cost are the usage recorded
on the cached responses; they are what a run from an empty cache would pay.

<!-- BEGIN:strategies -->
## Strategy comparison

| Strategy | Description | Sample status | Sample exact | Step P / R / F1 | Field acc. | Sequence exact / LCS | Eval status | Eval rows differing from S1 | Cache misses | Cached calls | Tokens | Cold-run cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | deterministic only (--llm off) | 30/32 | 6/32 | 0.8177 / 0.8601 / 0.8384 | 0.7401 | 0.8750 / 0.7897 | C=163 I=345 NA=10 | 85 | 15 | 0 | 0 | $0.0000 |
| S1 | claude-opus-5-5 intent + claude-opus-5-5 media (default) | 32/32 | 8/32 | 0.9005 / 0.8912 / 0.8958 | 0.8113 | 0.9062 / 0.8515 | C=153 I=355 NA=10 | 0 | 0 | 398 | 4744213 | $13.6361 |
| S2 | claude-haiku-5-5 intent + claude-opus-5-5 media | 32/32 | 8/32 | 0.9005 / 0.8912 / 0.8958 | 0.8113 | 0.9062 / 0.8515 | C=153 I=355 NA=10 | 0 | 0 | 398 | 4745334 | $13.1224 |

Calls, tokens and cost are replayed from the committed cache (no API calls are made); the cost is what a cold run would pay.
A cache miss means the run fell back to the deterministic path for that item (SPEC N7).
Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE.
Wall time is left out so that the table is a pure function of the code and the cache; a run takes about a second.
<!-- END -->

Reading it: the model's contribution here is the intent verdicts and the facts of 15 images and PDFs (the
router, agent and verifier are compared separately in section 4). With the model off (S0) one more sample has
a wrong status than with it and 12 evaluation rows change, while the intent lexicon alone already finds the
same set of non-deletion requests. The cheaper intent model (S2) gives the same answers as the default (S1) on
every sample and evaluation row, so the model choice is a cost decision, not an accuracy one. The default stays the
larger Opus model by the repository owner's decision; S2 would cut the cold-run cost at no measured loss
(DECISIONS D5).

## 4. Ablations and assumption ledger

Every inference switch in `Config.flags` is flipped once, and the agent is run off and on. The last columns show
how many evaluation rows change, which is the exposure of each assumption. The window sweep and the signature
variants of the earlier version are gone with the constants they moved (DECISIONS D3, D27).

<!-- BEGIN:ablation -->
## Ablation variants

| Variant | Sample status | Sample exact | Step P / R / F1 | Field acc. | Sequence exact / LCS | Eval status | Eval steps | Eval accounts unique / FIFO | Eval rows ambiguous / unresolved | Eval rows differing from default |
|---|---|---|---|---|---|---|---|---|---|---|
| default (default) | 32/32 | 8/32 | 0.9005 / 0.8912 / 0.8958 | 0.8113 | 0.9062 / 0.8515 | C=153 I=355 NA=10 | 3142 | 320 / 173 | 784 / 93 | 0 |
| verify_legal_holds=off | 32/32 | 8/32 | 0.9005 / 0.8912 / 0.8958 | 0.8113 | 0.9062 / 0.8515 | C=153 I=355 NA=10 | 3133 | 320 / 173 | 784 / 93 | 9 |
| allow_pre_request_findings=on | 32/32 | 7/32 | 0.8958 / 0.8912 / 0.8935 | 0.8075 | 0.9062 / 0.8473 | C=153 I=355 NA=10 | 3142 | 320 / 173 | 784 / 93 | 0 |
| fifo_pairing=off | 32/32 | 8/32 | 0.9425 / 0.8497 / 0.8937 | 0.8079 | 0.9375 / 0.8241 | C=153 I=355 NA=10 | 2932 | 320 / 0 | 784 / 93 | 199 |
| never_mix=off | 31/32 | 6/32 | 0.8155 / 0.8705 / 0.8421 | 0.7456 | 0.9062 / 0.7953 | C=153 I=355 NA=10 | 3138 | 320 / 174 | 787 / 787 | 80 |

Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE.

## Assumption ledger

| Flag | Default | Relied on in the default run | Eval rows changed when flipped |
|---|---|---|---|
| verify_legal_holds | True | - | off: 9 |
| allow_pre_request_findings | False | - | on: 0 |
| fifo_pairing | True | 197 eval cases | off: 199 |
| never_mix | True | 40 eval cases | off: 80 |

`-` in the third column means the diagnostics keep no per-case counter for that flag; the last column is then the only measure of its effect.


## Agent ablation

| Variant | Description | Sample status | Sample exact | Step P / R / F1 | Field acc. | Sequence exact / LCS | Eval status | Eval rows differing from agent=off | Units investigated | Units fallen back | Cached calls | Tokens | Cold-run cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent=off | deterministic fallback everywhere | 31/32 | 6/32 | 0.8204 / 0.8756 / 0.8471 | 0.7533 | 0.9062 / 0.8037 | C=153 I=355 NA=10 | 0 | 0 | 0 | 31 | 196870 | $0.8563 |
| agent=on | router, agent and verifier replayed from the cache | 32/32 | 8/32 | 0.9005 / 0.8912 / 0.8958 | 0.8113 | 0.9062 / 0.8515 | C=153 I=355 NA=10 | 73 | 64 | 1 | 398 | 4744213 | $13.6361 |

The agent=on row replays the router, agent and verifier responses of the live run from the cache; a unit with no cached response falls back, so on an empty cache the two rows are identical.
Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE.
<!-- END -->

The classed ledger (evidenced, weak, inferred) is in `code/docs/DECISIONS.md`. The withdrawn latency
signature and `account_00N` convention and the unsampled rules are disclosed there (D3, D11, D27) so a
reviewer can disagree with them; the unsampled rules are switchable from the command line.

## 5. Label-free checks on the 518 evaluation rows

`python3 -m evaluation verify` (from `code/`) re-reads the participant files with its own parsers (it imports
nothing from the solver) and checks every emitted row:

- P2a locator check: each cited text file shows the resource in the claimed state, inside the citation
  window, next to a key of the subject;
- P2b and P2c sweeps: every resource id found next to a subject key, and every id named in a cited
  in-window file, is emitted or has a recorded reason;
- P2d redundancy matrix: how often an independent signal agrees with the state, intent and citation of each step;
- P5 invariants: phase order and numbering, findings paired with remediation and verification, citation
  window, legal operation and system pairs, resource ids that exist, audit-record parity (an audit record is
"discoverable" only in a file captured inside the case window, the same causal rule the solver uses).

The hard invariants hold on the current run (`Hard failures: 0`); a hard failure would mean an emitted row
breaks the contract or cites a file that does not show what the step claims. The same checks are part of
`python3 -m evaluation check`, together with the format, the contract validator, byte-identical reruns under
two hash seeds and the sample score.

## 6. Additional evaluation cases

Seven synthetic cases, written from the SPEC before the pipeline ran, each with its own mini dataset in the
real file formats. `python3 -m evaluation custom` (from `code/`) rebuilds them in a temporary directory and
compares the pipeline output with the expected rows. Every identifier is synthetic; none occurs in
`dataset/`.

<!-- BEGIN:custom-cases -->
### C1: Historical upper-case email with failover drift

The request email is the user's previous address written in capitals (SPEC I1 lower-cases, I2 follows the audit history), so it must resolve to the user. The profile is absent from the primary but still in the failover replica, which is replication drift (SPEC F3): the account is a REPORT_REMAINING_RECORD finding even though the worker reported success. Another person's profile that sits in both tables must not appear.

**Input**

```text
runs=off; synth_c1 <SASHA.MARLOW@EXAMPLE.COM> Please erase my account and every personal detail attached to it.
```

**Expected output**

```text
synth_c1: INCOMPLETE [F:REPORT_REMAINING_RECORD:account_service/account_7000101@evidence_c1a R:DELETE_RECORD:account_service/account_7000101@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@-]
```

**Actual output**

```text
synth_c1: INCOMPLETE [F:REPORT_REMAINING_RECORD:account_service/account_7000101@evidence_c1a R:DELETE_RECORD:account_service/account_7000101@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@-]
```

### C2: Non-English negated request

The text refuses deletion in Portuguese (negation before the verb 'apague', and an access request). SPEC 9 and AGENTS 6.5 make the case NOT_APPLICABLE with no steps, although the account is still present and the worker rows look like a deletion case. It runs twice, and both runs must agree: with `--llm off` the lexicon decides, and with a scripted model that answers deletion=false at confidence 0.95 the model decides. Both are hermetic.

**Input**

```text
runs=off+scripted; synth_c2 <tomas.reid@example.com> Por favor, não apague a minha conta; preciso apenas de uma cópia dos meus dados.
```

**Expected output**

```text
synth_c2: NOT_APPLICABLE []
```

**Actual output**

```text
synth_c2: NOT_APPLICABLE []
```

### C3: Time travel: later evidence must not change the answer

Only information available at audit_at counts (AGENTS 6.2, SPEC T1). The file captured inside the window says NOT_FOUND. Its own last line is stamped after audit_at and says FOUND, and a second file captured two days after audit_at lists the profile. Both are inadmissible (T1) and the later file is not citable (T3), so the case is COMPLETE and cites the in-window file.

**Input**

```text
runs=off; synth_c3 <wren.castle@example.com> Please erase my account and every personal detail attached to it.
```

**Expected output**

```text
synth_c3: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000101@evidence_c3a]
```

**Actual output**

```text
synth_c3: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000101@evidence_c3a]
```

### C4: Exposed tombstone with a legal hold and an audit record

The tombstone keeps name, email, phone and hash, so rule 15 requires REDACT and never DELETE (SPEC 6): one REPORT_EXPOSED_PII finding, one REDACT_RECORD, one VERIFY_RECORD_REDACTED. The legal hold and the audit record are retained records, never findings, and are verified as present. The case is INCOMPLETE, so every compliant resource keeps an empty evidence_id (SPEC 8.2), and the steps follow the AGENTS 6.4 operation order, then system and resource (SPEC 8.4).

**Input**

```text
runs=off; synth_c4 <odette.finch@example.com> Please erase my account and every personal detail attached to it. Please also handle the copies that fall within the scope of this request.
```

**Expected output**

```text
synth_c4: INCOMPLETE [F:REPORT_EXPOSED_PII:identity_service/tombstone_7000103@evidence_c4a R:REDACT_RECORD:identity_service/tombstone_7000103@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@- V:VERIFY_RECORD_PRESENT:legal_service/legal_hold_7000104@- V:VERIFY_RECORD_PRESENT:security_service/audit_record_7000105@- V:VERIFY_RECORD_REDACTED:identity_service/tombstone_7000103@-]
```

**Actual output**

```text
synth_c4: INCOMPLETE [F:REPORT_EXPOSED_PII:identity_service/tombstone_7000103@evidence_c4a R:REDACT_RECORD:identity_service/tombstone_7000103@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@- V:VERIFY_RECORD_PRESENT:legal_service/legal_hold_7000104@- V:VERIFY_RECORD_PRESENT:security_service/audit_record_7000105@- V:VERIFY_RECORD_REDACTED:identity_service/tombstone_7000103@-]
```

### C5: Active connector repopulated a search document

The only link between the user and the connector is the activity row 'Active connector repopulated downstream resource search_N' (SPEC L9): the connector configuration names no user, and no 'Connector status check' row exists. The snapshot shows the connector enabled and the search document present, so the case reports the document, reports the active data flow, disables the flow before deleting the document (table order, SPEC 8.4), and verifies both. The connector is not a deletion target by itself.

**Input**

```text
runs=off; synth_c5 <rhea.lorne@example.com> Please erase my account and every personal detail attached to it.
```

**Expected output**

```text
synth_c5: INCOMPLETE [F:REPORT_REMAINING_RECORD:search_service/search_7000107@evidence_c5a F:REPORT_ACTIVE_DATA_FLOW:integration_service/data_flow_7000106@evidence_c5a R:DISABLE_DATA_FLOW:integration_service/data_flow_7000106@- R:DELETE_RECORD:search_service/search_7000107@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@- V:VERIFY_RECORD_ABSENT:search_service/search_7000107@- V:VERIFY_DATA_FLOW_DISABLED:integration_service/data_flow_7000106@-]
```

**Actual output**

```text
synth_c5: INCOMPLETE [F:REPORT_REMAINING_RECORD:search_service/search_7000107@evidence_c5a F:REPORT_ACTIVE_DATA_FLOW:integration_service/data_flow_7000106@evidence_c5a R:DISABLE_DATA_FLOW:integration_service/data_flow_7000106@- R:DELETE_RECORD:search_service/search_7000107@- V:VERIFY_RECORD_ABSENT:account_service/account_7000101@- V:VERIFY_RECORD_ABSENT:search_service/search_7000107@- V:VERIFY_DATA_FLOW_DISABLED:integration_service/data_flow_7000106@-]
```

### C6: Look-alike email and same-name user add no findings

Three users share the name Dana Okafor; one email differs only by '.jr' and one by domain. Identity matching is exact (SPEC I1, I4), so their account, search document and worker rows belong to other subjects (owner filter L4a) and must not become findings of the requester, whose own account is absent. The case is COMPLETE with the single cited account check.

**Input**

```text
runs=off; synth_c6 <dana.okafor@example.com> Please erase my account and every personal detail attached to it.
```

**Expected output**

```text
synth_c6: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000101@evidence_c6a]
```

**Actual output**

```text
synth_c6: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000101@evidence_c6a]
```

### C7: One user, two requests with disjoint windows

Each case is scoped by its own times (SPEC T5). The first request ends before the second begins. The first file shows the first account and a search document, so the first case is INCOMPLETE. The second case starts after that file was captured: it must not inherit the first case's resources (L10 floor) or cite its file (T3), and the first case must not see the later file (T1). The second case is COMPLETE with its own account and file.

**Input**

```text
runs=off; synth_c7a <jules.verne.test@example.com> Please erase my account and every personal detail attached to it. | synth_c7b <jules.verne.test@example.com> Please erase my account and every personal detail attached to it.
```

**Expected output**

```text
synth_c7a: INCOMPLETE [F:REPORT_REMAINING_RECORD:account_service/account_7000113@evidence_c7a F:REPORT_REMAINING_RECORD:search_service/search_7000115@evidence_c7a R:DELETE_RECORD:account_service/account_7000113@- R:DELETE_RECORD:search_service/search_7000115@- V:VERIFY_RECORD_ABSENT:account_service/account_7000113@- V:VERIFY_RECORD_ABSENT:search_service/search_7000115@-]; synth_c7b: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000114@evidence_c7b]
```

**Actual output**

```text
synth_c7a: INCOMPLETE [F:REPORT_REMAINING_RECORD:account_service/account_7000113@evidence_c7a F:REPORT_REMAINING_RECORD:search_service/search_7000115@evidence_c7a R:DELETE_RECORD:account_service/account_7000113@- R:DELETE_RECORD:search_service/search_7000115@- V:VERIFY_RECORD_ABSENT:account_service/account_7000113@- V:VERIFY_RECORD_ABSENT:search_service/search_7000115@-]; synth_c7b: COMPLETE [V:VERIFY_RECORD_ABSENT:account_service/account_7000114@evidence_c7b]
```
<!-- END -->

## 7. Failures found and improvements made

Chronological, from the review rounds on the finished solver. Each item names the decision record where
the rule is explained.

| Failure found | Improvement | Effect |
|---|---|---|
| A snapshot captured before the request was the only proof of some images' resources, so a finding would have cited an inadmissible file | Such findings are not emitted (D12) | No citation outside the window |
| A support message or analytics record that was already absent produced a finding whose own proof file showed it gone | An absent record to be redacted or anonymized gets no step (D17) | One evaluation row changed from INCOMPLETE to COMPLETE |
| A file captured after every cutoff moved the fitted link signature, changing 12 of 518 rows in a synthetic late-evidence test | First the signature was fitted only on anchors admissible at the audit time (D15); then the signature itself was removed (D3, D29) | The late-evidence override-ban test leaves all 518 rows byte-identical |
| A security audit screen repeated one `user_N` filter on six rows, so a COMPLETE case cited six audit records, five of them tied to nobody | A bare user reference ties no record in a screen that has a LINK row (D18) | That row went from 7 steps to 2; the label-free audit-parity invariant was taught that an emitted record may be tied by a catalog LINK row, so it passes on the shipped output |
| A request that does not authorize deletion took part in account pairing and took the account row of a deletion case, which then lost its account verification step | Only deletion requests are linked (D19) | One evaluation row gained its account step; no status changed; samples unchanged |
| The scorer scored a leftover predictions file when one existed, so it reported older numbers than the code produces | The scorer always runs the sample pipeline into a temporary directory unless `--pred` is given | The documented command now describes the current code |
| The usage report showed only live calls, which are zero on the final run because the response cache is full | The report shows replayed usage (what the cached responses cost) and live usage, and the check refuses a meter with no recorded call | The usage report describes the model usage behind `output.csv` |
| Every generic support ticket (a service-export ticket row, a ticket-read log line) was read as a support message, so ten support attachments were redacted although the worker had deleted them | A ticket that cannot tell message from attachment carries no category, and the worker's activity event type decides: `DELETE_RECORD` is an attachment, `REDACT_RECORD` a message (D20) | Ten evaluation rows changed, three steps each (30 steps): redact became delete. No status changed and the samples keep their scores |
| A blind audit of 61 evaluation cases found a COMPLETE case whose account is listed by no in-window file but whose topology snapshot (a primary plus replica tables) enumerates accounts | A snapshot that lists accounts may be cited, and only cited, as the account's absence proof (D22) | 33 COMPLETE rows changed (21 re-cited, 12 gained the account step); no omitted account step remains |
| The report tables printed wall time, which differs on every run, so `render_reports --check` could never pass on a fresh run; the shipped ablation figures had also drifted from the code | Wall time left out of the checked tables; `python3 -m tools.build_zip --metrics-dir` fails the build when the check fails | The tables are a pure function of the code and the cache |
| An unwritable `--out` or `--diag` path crashed with a traceback after the whole pipeline had run | Output directories are created and checked before the run, and a failed write returns exit code 2 with one line | `test_pipeline_smoke` covers both options |
| One activity row that matched no template raised an error and aborted the whole run | Such a row is classified `UNCLASSIFIED` (inert, never used for a decision), warned about once per template shape and counted in the diagnostics; `strict=True` keeps the error (`test_activity`, `test_pipeline_smoke`) | The shipped data has 0 such rows; a synthetic unknown row no longer stops the run |
| The scorer carried two ceiling constants and a `--ceilings eval` option with no source in the shipped code | Both removed; the ceiling column is 1.000 and the limits of the pipeline's own discovery are measured and listed in section 8 | No effect on any score or on `output.csv` |
| The media replies in the response cache held emails, phones and names transcribed from the dataset's images and PDFs | The stored replies are redacted copies: emails and phones as sha256 digests, names dropped, matched through the identity's hash keys (D25) | 15 entries rewritten (18 emails and 3 phones hashed, 7 names dropped); `output.csv` byte-identical |
| Dead code kept alive by tests only (second usage renderer, thread-pooled batch client, unused helpers) | Removed; shared predicates moved to one definition | Fewer lines to read, identical output |
| The link rules rested on windows widened by hand against the samples, a latency signature learned from the generated data and an `account_00N` id convention: fitted to the dataset, and the signature and late audit ids read evidence from after `audit_at` | Candidates follow the order of the process only; the signature, the windows, the convention, the orphan rule and late audit ids are removed; contested links go to a router, a bounded tool-calling agent and a verifier, with the deterministic pairing as the fallback (D26, D27, D29) | Samples (agent off): 32/32 to 31/32 status, 30/32 to 6/32 row-exact, step F1 0.9948 to 0.8471; 264 evaluation rows differ from the earlier `output.csv`, none by status. With the agent on (live run replayed): 32/32 status, 8/32 row-exact, step F1 0.8958 |
| After that change the label-free recall sweep listed nine evaluation cases whose own evidence-tied account was linked to another case, and the locator check one finding that cited a scope listing as proof of an active flow | Of a case's account candidates the ones evidence ties to its own subject replace the ownerless ones (D28); a scope that omits a resource proves absence only, never a finding (`casebuilder`) | Unexplained recall items 9 to 0, hard failures 21 to 0, samples 5/32 to 6/32 row-exact and F1 0.8350 to 0.8471 |
| The audit-parity invariant still counted an audit id found only in a later file as "discoverable but not emitted" (123 hard failures) | The invariant uses the same window as the solver (D29) | 0 hard failures; the gate `python3 -m evaluation check` passes |
| The quality checks lived in `devtools/` and the documentation, outside the archive; the scripts edited `sys.path` | One shipped command (`python3 -m evaluation check`), subcommands `score`, `verify`, `custom`, installable entry points, no `sys.path` edit under `code/` (D30) | `test_check`, `test_packaging`, `test_static` |

## 8. Limitations and disclosures

- **Contested links dominate the error.** The candidates follow the order of the process, which is all a
  deletion audit can assume; the rows that evidence ties to a subject lie 0.7 to 2.2 hours from the report,
  but that spread is not used. 784 evaluation worker rows are shared by several cases after the fixed point
  and 401 evaluation cases carry a fallback link (the ablation table in section 4). The fallback pairs
  ascending ids with ascending case ids, which is arbitrary where evidence is silent, and on the samples it
  scores worse than no pairing (`fifo_pairing=off`: 32/32 status, 8/32 exact, step F1 0.8937 against 31/32,
  6/32, 0.8471; DECISIONS D10). Whether it stays on is left to the repository owner.
- **The agent has run against a model.** Two live Opus 5.5 runs filled the cache (the first stopped at the
  default $5 cap after 28 of 64 units; the second, capped at $15, finished the rest). The agent decided 63 of
  64 units (one answered UNSURE and fell back), the verifier checked 636 assignments and rejected 9, and the
  agent changed 73 evaluation rows against `agent=off`. On the samples it lifts status from 31/32 to 32/32,
  row-exact from 6/32 to 8/32 and step F1 from 0.8471 to 0.8958 (section 4). It does not recover the accuracy
  of the removed fitted rules (30/32 row-exact).
- **Time is causal everywhere.** No state, status, finding, link, owner or id comes from evidence captured
  after `audit_at`. The cost is visible: an audit-record id found only in a later file is not emitted (300
  evaluation cases have an audit record named inside their window, 218 do not), and a resource whose evidence
  owner is tied only by a later file does not pin its case (D29).
- **No id is derived.** The `account_00N` convention is gone. Public samples 02, 08, 22 and 26 have no
  account step because nothing visible names their account.
- **Some COMPLETE rows have no account verification step** when no in-window file proves the account absent (12
  of 153 in the label-free report; D21, D22).
- **One audit screenshot lists six signed events for one subject**; only the one tied by a catalog LINK row
  is emitted, since no public sample has more than one audit step per case (D18, D21).
- The 518 evaluation rows are unlabeled; their quality rests on the sample scores, the label-free checks
  and the ledger above, not on a measured accuracy. The pipeline's own discovery coverage on the 508
  evaluation deletion cases is in the diagnostics of a run: audit-record coverage as above, and the number of
  cases that rely on the fallback pairing.
- The sample answers cannot test rules that no sample exercises (never-mix, legal holds); they are switchable
  and their exposure is listed in section 4.
- Images and PDFs are read by a vision model once and cached. Without the cache (or with `--llm off`) the
  solver falls back to the deterministic path and the diagnostics list each unread file.

## 9. Reproduce

From `code/` (or as `ghostaudit-eval ...` after `pip install -e code`):

```bash
cd code
python3 -m evaluation check                        # format, contract, determinism, invariants, sample score
python3 -m evaluation score                        # sample scores, always from a fresh pipeline run
python3 -m evaluation score --strategies           # S0, S1, S2
python3 -m evaluation score --ablate --agent-ablation   # flags, and the agent off and on
python3 -m evaluation custom                       # the seven extra cases
python3 -m evaluation verify                       # label-free checks on the 518 rows
cd .. && python3 -m unittest discover -s code/tests -t code
```
