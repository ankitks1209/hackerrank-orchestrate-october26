# SPEC — Ghost Data Still Exists: Deletion-Audit Agent

Status: v1.4 (three review rounds, score-maximization pass and local-evaluation stress test; see `SCORING_STRATEGY.md` and `LOCAL_EVALUATION_STRATEGY.md`. Changes marked ⟲, v1.3 changes ⟲³, v1.4 changes ⟲⁴)
Scope: **what** the solver must do. **How** it is built is in `IMPLEMENTATION_PLAN.md`.

---

## 1. Purpose and scope

The solver reads `dataset/deletion_requests.csv` (518 cases, `case_33..case_550`). For each case it decides:

1. Does the request text authorize deletion?
2. If yes, at `audit_at`, does every relevant copy of the subject's data have the treatment that `deletion_rules.csv` requires, and is there no active path that can recreate it?
3. It emits an ordered, evidence-backed list of steps: findings, then remediation, then verification.

The result is written to `<repo>/output.csv`.

The solver is an **AI-powered agent with a deterministic core**:
- Decisions are made by explicit, testable rules over parsed evidence.
- An LLM is used where natural-language or visual understanding is needed: request intent (multilingual) and image/PDF fact extraction.
- Every LLM interaction is cached and metered.

### 1.1 Glossary
| Term | Meaning |
|---|---|
| Case | One row of `deletion_requests.csv`. |
| Subject | The `user_id` that the request email resolves to. |
| Resource | `(system_id, resource_id)`, e.g. `(search_service, search_898)`. |
| Observation | One statement from one evidence file about one resource's state at one time. |
| Scope assertion | A file states that it fully enumerated system S, so a missing row means ABSENT. |
| Proof file | The evidence file cited for a step. |
| Window | `[reported_at, audit_at]`, inclusive. A citable file has `captured_at` inside it. |
| Compliant / violating | The resource already has / does not have its required final state. |
| Treatment | The required policy action: DELETE, REDACT, ANONYMIZE, RETAIN, FLOW (disable), RESTORE (block). |
| Drift | A record that is absent from the primary but still present in a replica. |
| Tombstone | `identity_service/tombstone_N`. Keeps only the stable `user_id`. |
| Cohort | About 10 cases that share one `audit_at` and one primary proof file. |

### 1.2 Out of scope
- Using `sample_output.csv`, `solution/`, or any organizer-only data at inference time.
- Inventing resource ids that appear in no participant-visible source.

---

## 2. Inputs

All paths are relative to the repo root. They are read via `dataset/`.

| File | Columns | Use |
|---|---|---|
| `deletion_requests.csv` | case_id, email, requested_at, reported_status, reported_at, audit_at, request_text | The cases to answer (518) |
| `sample_deletion_requests.csv` | same | Also participant input; used for joint linking and the dev evaluation |
| `sample_output.csv` | case_id, deletion_status, steps_json | **Evaluation only.** Never readable by the inference pipeline |
| `user_identities.csv` | user_id, name, email, phone, email_hash, updated_at | Current identity (850 users) |
| `user_audit_log.csv` | audit_id, user_id, event_time, field_name, old_value, new_value | Historical email, email_hash and phone values (306 rows) |
| `system_activity.csv` | activity_id, event_time, event_type, source_system, target_system, resource_id, reported_result, details | Global event stream (4011 rows) |
| `deletion_rules.csv` | rule_id, data_category, condition, required_action | Policy (15 rules) |
| `evidence_files.csv` | file_id, file_path, origin, captured_at | Manifest (94 files). `captured_at` is the admissibility clock |
| `evidence/**` | 24 `.sql`, 28 `.json`, 1 `.txt`, 26 `.log`, 11 `.png`, 4 `.pdf` | Evidence |

### 2.1 Identity rules (normative)
- **I1.** Normalize emails with `strip().lower()`. Match exactly. Never use prefix, substring, fuzzy or name matching.
- **I2.** A subject's keys are:
  - the current email, plus every `old_value` and `new_value` of `field_name=email` audit rows, following multi-hop chains (user_35 has three emails);
  - for every email, `sha256(lower(email))` (verified 850/850 for current emails), plus the `email_hash` audit values;
  - the current phone and old phones (exact string, plus a digits-only form);
  - `user_N`.
- **I3.** A request email resolves to exactly one subject. All 518 resolve: 418 current, 100 historical, 20 uppercase. An unresolved email is a hard error, logged; the case is emitted as INCOMPLETE with no steps only as a last resort.
- **I4.** Decoys must never match: `.jr` look-alikes, near-names, names shared by different users (Mateo Ríos, Thandiwe Ndlovu, Gabriel Costa ×2 each), staff and business emails.

---

## 3. Evidence model

### 3.1 Normalized records
```
Observation(file_id, captured_at, entry_time|None, system_id, resource_id,
            category|None, state, subject_keys:frozenset, locator)
ScopeAssertion(file_id, captured_at, system_id, present_ids:frozenset)
state ∈ {PRESENT, ABSENT, EXPOSED, REDACTED, ANONYMIZED, ACTIVE, DISABLED, BLOCKED}
subject_keys ∈ {'e:<email>', 'h:<sha256>', 'p:<digits>', 'u:user_N'}
```
- `entry_time` is the line, record or snapshot timestamp. When it is missing, use `captured_at`.
- The parser that handles a file is chosen by **content and structure**, never by `file_id`.

### 3.2 Per-family decoding (normative)

**F1. SQL topology files** (read, regional, reporting and failover replicas). Each file has a `customer_data_primary` table plus one or more `*_replica*` tables, with columns `resource_id, origin_system, collection_name, record_json, updated_at`.
- `system_id` = `origin_system`.
- A row present in **any** table means the resource is present. Drift is a row in a replica table but not in primary. Check every replica table: regional drift can be in only one of them.
- Subject keys come from these `record_json` fields: email, phone, email_hash, user_id, `document.email`, `document.customer_reference`, subject_reference, subject_selector, owner_email, uploaded_by, and emails inside `message_text`.

| collection_name | Category | State rule |
|---|---|---|
| customer_profiles | USER_PROFILE | PRESENT |
| customer_search_documents | SEARCH_INDEX_ENTRY | PRESENT |
| customer_analytics_reports | ANALYTICS_PROFILE | user_id, email, phone and email_hash all null → ANONYMIZED, else EXPOSED |
| support_conversations | SUPPORT_MESSAGE | `message_text=="[REDACTED]"` → REDACTED, else EXPOSED |
| ticket_attachments | SUPPORT_ATTACHMENT | PRESENT |
| customer_export_jobs | USER_EXPORT | PRESENT |
| connector_configurations | DATA_FLOW | `enabled` → ACTIVE / DISABLED |
| backup_catalog | BACKUP_ARCHIVE | `restore_allowed` → ACTIVE / BLOCKED |
| security_audit_events | SECURITY_AUDIT_LOG | PRESENT |
| retained_order_records | LEGAL_HOLD_RECORD | PRESENT |
| deleted_customer_references | ACCOUNT_TOMBSTONE | name, email, phone and email_hash all null → REDACTED, else EXPOSED |

**F2. SQL inventory files.** Typed tables:

| Table | system_id |
|---|---|
| customer_profiles | account_service |
| customer_search_documents | search_service |
| customer_analytics_profiles | analytics_platform |
| support_records | support_platform |
| customer_exports | export_service |
| connector_subscriptions | integration_service |
| backup_restore_entries | backup_service |
| security_audit_records | security_service |

Rules:
- `snapshot_scope(origin_system, captured_at)` gives one ScopeAssertion per in-scope system. A system **in** scope with no matching row is ABSENT; a system **not** in scope is *unobserved*.
- `account_status=DELETION_PENDING` is PRESENT. On support records, `requester_email` set → EXPOSED, and only `customer_reference` set → REDACTED.
- Inventory files cannot tell a support message from an attachment.

**F3. SQL special schemas** (detected by table names):
- `customer_profiles_primary` + `customer_profiles_failover_replica`: profile drift. This is also the absence proof for profiles not listed.
- `search_documents_primary` (with `source_resource_id`, `indexed_at`).

**F4. JSON service exports.** Structure is `service_exports.<system_id>.<list>[]`, and `entry_time = observed_at`.

| List | State rule |
|---|---|
| profile_lookups | `status_code 404` or `profile:null` → ABSENT (no keys); 200 → PRESENT (even if only the email is left) |
| analytics `profiles` | all identifiers null → ANONYMIZED, else EXPOSED |
| restore_entries | `restore_allowed` → ACTIVE / BLOCKED |
| exports | PRESENT |
| connectors | `enabled` → ACTIVE / DISABLED |
| index_queries | `hits.total>0` → PRESENT; keys from `hits.documents[].email` |
| audit_records | PRESENT |
| support tickets | any `requester_*` set → EXPOSED; all null with `customer_reference` → REDACTED |

**F5. JSON snapshot bundles.** Structure is `snapshots[{captured_at, data_store, collection, records[]}]`.
- `system_id` = `data_store`, `entry_time` = the snapshot's `captured_at`. Collections decode as in F1.
- An empty `records` list for a collection is a ScopeAssertion with no ids. Example: an empty `customer_profiles` collection proves the account is absent.
- ⟲ Rows in `operational_record_history` use the F6 states, with `system_id` = the row's `system`. The subject key comes from **`lookup_value`**, not `subject_reference`: 124 rows in ev22/31/45, 118 of them resolvable. The bundle's `data_store` (e.g. `privacy_treatment_service`) is **not** the system.
- A single bundle can contain layers at several times: one stale, one at audit, one recreated after audit.

**F6. Flat ledgers and diag logs.** Structure is `records[{recorded_at, system, resource_id, record_type, result, subject_reference}]`, plus the `record_lookup` log lines.
- `category = record_type`, `system_id = system`, `entry_time = recorded_at`.
- `result` maps to state: FOUND → PRESENT, NOT_FOUND → ABSENT, IDENTIFIABLE → EXPOSED, ANONYMIZED, REDACTED, ACTIVE, DISABLED, BLOCKED.

**F7. JSON collections** (`{captured_at, source, collection, records}`). `source` is not the system_id; map the collection to analytics_platform or export_service.

**F8. TXT handover.** Lines match `^- ts | system | resource_id | category | result | key$`. A key of `no direct identifier` means no key.

**F9. Logs.** Every line is `<ISO-ts> <body>`, where the body is one of 8 formats:
1. logfmt
2. readback logfmt (literal `null`)
3. ts + JSON
4. RFC5424 syslog
5. bracketed `[LVL] [svc] [trace] event:`
6. pipe-delimited
7. cloud nested (`message="…"`, needs a second key=value parse)
8. diag `record_lookup` (F6 vocabulary). ⟲ It can start with any level: `^(DEBUG|INFO|WARN|ERROR) service=\S+ event=record_lookup`. WARN lines carry the IDENTIFIABLE rows in ev08 and ev41.

Subject keys come from `*_started` lines (`lookup_key`, `match_key`, `subject_ref`, `subject_key`, `scan_key`, `owner_key`) **joined by trace_id, never by adjacency**, and from inline keys (`correlation_key`, `matched_value`, `customer_email`, `email`, `requester_email`, `owner_email`, `customer_reference`, `subject_reference`). A line with no trace_id gets only its inline keys (⟲ do not fall back to `instance`).

| Event | State | Category |
|---|---|---|
| profile_lookup_completed | rows=0/404 → ABSENT, rows=1/200 → PRESENT | USER_PROFILE |
| index_query_completed `result=hit` | PRESENT | SEARCH |
| audit_record_read_completed | PRESENT | SECURITY_AUDIT_LOG |
| analytics_identity_scan | EXPOSED | ANALYTICS |
| analytics_profile_read `direct_identifiers=0` | ANONYMIZED | ANALYTICS |
| analytics_profile_read_completed | all-null → ANONYMIZED, else EXPOSED | ANALYTICS |
| contact_lookup_completed `email_opt_in=true` | PRESENT | SECONDARY_IDENTIFIER (DELETE) |
| message_pii_scan | EXPOSED | SUPPORT_MESSAGE |
| attachment_pii_scan | PRESENT | SUPPORT_ATTACHMENT |
| message_read `[REDACTED]` | REDACTED | SUPPORT_MESSAGE |
| support_ticket_read_completed | requester null → REDACTED, else EXPOSED | SUPPORT_MESSAGE |
| connector_heartbeat / connector_config_loaded / _read_completed | enabled → ACTIVE, else DISABLED | DATA_FLOW |
| restore_candidate_evaluated `eligible=true deletion_block=false` | ACTIVE | BACKUP |
| restore_authorization_completed `decision=deny` | BLOCKED | BACKUP |
| restore_policy_read_completed | restore_allowed → ACTIVE / BLOCKED | BACKUP |
| export_download_check / export_metadata_read_completed `available=true` | PRESENT | USER_EXPORT |
| retained_order_loaded | PRESENT | LEGAL_HOLD |
| contact_query_completed rows=1 + deletion_marker_check marker_found=false | PRESENT | support_platform |

Drop entirely:
- the `profile_service` 5-digit decoys (evidence_53);
- `log_router` and `readback_collector` framing lines;
- ⟲ noise: **every event that is not in the state table above and is not a `*_started` key line or framing**. The known noise set (cache_lookup, connection_acquired, dependency_retry/recovered, webhook, thumbnail_failed, queue_consumer and similar) is enumerated in code, and anything outside it and the state table is reported in diagnostics as `unknown_event`.

Log level carries no state meaning.

**F10. Media (PNG/PDF).**
- Facts are extracted by an LLM vision call (cached).
- ⟲ An image or PDF maps to a resource in one of two ways:
  - **(a) LINK join.** A `LINK_RESOURCE_IDENTITY` activity row has an alias (the parenthesised display id, or the resource id) equal to an extracted display id. The LINK row supplies `system_id`, `resource_id`, `user_id` and `email`.
  - **(b) Literal id + identifier.** The extracted text contains a literal resource id with a known `SYSTEM_BY_PREFIX` prefix (e.g. `support_001`, `audit_record_003`), **and** an extracted email, phone or `user_N` resolves to a subject key (L1). The prompt also returns a category (attachment, message, profile, …), so the treatment can be decided.
- Display labels (CS-*, NST-*, file names) are never resource ids by themselves.
- Facts are never mapped by timing (the `+7m01s` LINK offset is a generator artifact).
- `entry_time` = the manifest `captured_at`.
- If the alias doesn't validate, or extraction is missing, drop the observation and log it.

| file | resource | state |
|---|---|---|
| ev04 | account_5762 | PRESENT |
| ev09 | search_428 | PRESENT |
| ev14 | data_flow_1121 | ACTIVE |
| ev18 | export_1842 | PRESENT |
| ev19 | analytics_7438 | EXPOSED |
| ev23 | export_1260 | PRESENT |
| ev28 | support_1034 | EXPOSED (message) |
| ev32 | backup_9287 | ACTIVE |
| ev37 | audit_record_003 | PRESENT |
| ev42 | tombstone_17 | REDACTED |
| ev46 | object_storage/object_19 | PRESENT (attachment) |
| ev60 | marketing_001 | PRESENT |

| ev58 | support_platform/support_001 (path b; key `e:priya.raman@gmail.com`) | PRESENT (SUPPORT_ATTACHMENT) |
| ev55 | security_service/audit_record_003 (path b; key `u:user_03`) | PRESENT |

These values are the expected extraction targets used in tests, not hard-coded answers. ⟲ ev58 is needed by sample case_07: it is that case's only finding. ev27 (legal register) has only `user_N` and order ids, no resource ids; it is logged and produces no observation. ev04 also displays the reference `support_9538` but no attachment state (see Q1).

---

## 4. Activity semantics

`reported_result` is **never** evidence of state. The `details` template and `event_type` are interpreted as follows (counts are verified):

| Code | `details` pattern | n | Meaning |
|---|---|---|---|
| A | `Deletion worker submitted primary profile (account_\d+) to account_service.` | 532 | Candidate case account. Its `reported_result` mirrors `reported_status` (used **only** as a linking constraint) |
| P | `Policy action completed for (X).` | 248 | X compliant → verification |
| V | `Deletion worker received the final result for (X) from (S).` | 558 | X violating (even when SUCCESS) |
| CF | `Connector status check confirmed that data flow (data_flow_N) remains enabled.` | 89 | Active flow |
| CR | `Restore-access check confirmed that archive (backup_N) can still be restored.` | 28 | Restore risk |
| R | `Replication worker reported its final checkpoint for (account_N).` | 55 | Account still present (drift) |
| RP | `Active connector repopulated downstream resource (search_N).` (`resource_id`=data_flow) | 31 | Flow is active for the owner of search_N |
| RB | `Restore job repopulated downstream resource (search_N).` | 1 | Restore path (post-audit in eval) |
| N | `Privacy intake classified request for (account_N) as non-deletion` | 10 | Corroborates NOT_APPLICABLE |
| L | `Data catalog linked X (alias) to email and user_N` / `Attachment catalog confirmed X (alias) belongs only to …` | 12 | Media decoding |
| T | `… Target resource: (X).` | 12 | Sample-only resource pointer. **Not** truth |
| noise | `… processed <prefix>_N.` | 2435 | Ignore (⟲ exact count) |

**Treatment comes from the activity `event_type`.**

| event_type | Treatment |
|---|---|
| DELETE_RECORD | DELETE |
| REDACT_RECORD | REDACT |
| ANONYMIZE_RECORD | ANONYMIZE |
| CHECK_DATA_FLOW / DISABLE_DATA_FLOW | FLOW |
| CHECK_RESTORE_ACCESS / BLOCK_RESTORE | RESTORE |
| RETAIN_RECORD | RETAIN |

⟲ **system_id per row kind:**

| Row kind | system_id |
|---|---|
| A, P, V, CF, CR, T, L | `target_system` |
| RP | `integration_service` (`resource_id` is the data_flow; `related_rid` = search_N; `target_system` is search_service) |
| RB | `backup_service` |
| R, N | `account_service` (`target_system` is account_replication_cluster / privacy_case_management) |

A test asserts that every non-noise row's system_id agrees with `SYSTEM_BY_PREFIX`. The `object_store` target appears only on noise rows and needs no remap.

**Precedence (⟲).** For **state**, evidence observations in the window win over everything else. Activity templates are used for:
1. discovering resources and linking them to cases;
2. treatment;
3. state only when no admissible observation exists.

Every disagreement between evidence and template is logged.

---

## 5. Time rules (normative)

- **T1.** An observation counts toward a case's state only if both of these hold:
  - its file has `captured_at ≤ audit_at`, and
  - its `entry_time ≤ audit_at`.
- **T2.** A resource's state is the admissible observation with the greatest `(entry_time, captured_at)`. Ties are broken by manifest order.
- **T3.** A step may cite a file only if `reported_at ≤ captured_at ≤ audit_at`. All bounds are inclusive and use the manifest clock.
- **T4.** Files and entries after `audit_at`, and activity rows after `audit_at`, must not change state or status. They may supply resource **ids** for future verification steps in INCOMPLETE cases (`evidence_id=""`). Example: audit record ids that appear only in a later file.
- **T5.** Each case is scoped by its own times. A user with several cases (user_07, user_17, user_18) never shares state across cases.
- **T6.** All times are parsed once into integer UTC epoch seconds.

---

## 6. Policy mapping

| Rule | Category | Resource (system) | Violating state | Finding → Remediation → Verification | Compliant → Verification |
|---|---|---|---|---|---|
| 01 | USER_PROFILE | account_N (account_service) | PRESENT | REMAINING → DELETE → ABSENT | ABSENT |
| 02/10 | SECONDARY_IDENTIFIER / MARKETING_PROFILE | analytics contact (opt-in), marketing_N (marketing_platform) | PRESENT | REMAINING → DELETE → ABSENT | ABSENT |
| 03 | SEARCH_INDEX_ENTRY | search_N | PRESENT | REMAINING → DELETE → ABSENT | ABSENT |
| 05 | SUPPORT_MESSAGE | support_N | EXPOSED | EXPOSED_PII → REDACT → REDACTED | REDACTED |
| 06 | SUPPORT_ATTACHMENT | support_N, object_N (object_storage) | PRESENT | REMAINING → DELETE → ABSENT | ABSENT |
| 07/08 | ANALYTICS_PROFILE / PRODUCT_TELEMETRY | analytics_N | EXPOSED | EXPOSED_PII → ANONYMIZE → ANONYMIZED | ANONYMIZED |
| 09 | USER_EXPORT | export_N (export_service) | PRESENT | REMAINING → DELETE → ABSENT | ABSENT |
| 11 | EMAIL_DELIVERY_LOG | — | — | (no evidence in dataset) | — |
| 12 | SECURITY_AUDIT_LOG | audit_record_N (security_service) | never | — | PRESENT |
| 13 | LEGAL_HOLD_RECORD | legal_hold_N (legal_service) | never | — | PRESENT |
| 14 | BACKUP_ARCHIVE | backup_N | ACTIVE (restorable) | RESTORE_RISK → BLOCK_RESTORE → RESTORE_BLOCKED | RESTORE_BLOCKED |
| 15 | ACCOUNT_TOMBSTONE | tombstone_N (identity_service) | EXPOSED | EXPOSED_PII → REDACT → REDACTED | REDACTED |
| — | (connector) | data_flow_N (integration_service) | ACTIVE | ACTIVE_DATA_FLOW → DISABLE → DISABLED | DISABLED |

**Discriminators**
- **Message vs attachment:** decided by evidence category when present (F1/F6/F8/F9). Otherwise use the activity event_type: REDACT_RECORD means a message, DELETE_RECORD means an attachment.
- **Analytics profile vs secondary contact:** a `contact_lookup … email_opt_in` record is DELETE / REMAINING (sample case_12). Any analytics record with a direct identifier is ANONYMIZE / EXPOSED_PII.
- **Drift:** drift on an account is an account REMAINING finding. The replication sync itself is **not** a data flow.
- **Backups are never deleted.** **Tombstones are never deleted.** Redacting a tombstone does not re-delete the account.
- Rules 04 (CACHE), 08 (TELEMETRY) and 11 (EMAIL_DELIVERY_LOG) have no matching evidence. The engine supports them generically but must not fabricate them.

---

## 7. Case linking

**Goal:** for each authorized case, find the set of resources that belong to it. This means the case account, worker-handled resources, evidence-discovered resources, audit records, legal holds and tombstones.

**L1. Identifier links (strongest).** Any observation whose `subject_keys` intersect the subject's keys belongs to the subject. It is attached to a case only if T1 holds for that case and the file is within that case's lifetime (T5).

**L2. Account candidates.** An A row is a candidate for case c when both hold:
- `reported_at(c) − 1.3h ≤ t(A) ≤ reported_at(c) − 0.7h`, and
- `result(A) == mirror(reported_status(c))`.

**L3. Worker-row windows, anchored on `reported_at`** (⟲ replaces the fingerprint as the primary signal):

| Row | Window |
|---|---|
| P | `[reported_at − 30 min, reported_at − 2 min]` |
| V, CF, CR | `[reported_at + 30 min, reported_at + 135 min]`, and `≤ audit_at` |

⟲ Widened after review: the earlier `−7 min` / `+130 min` bounds missed real rows activity_1124 (P at −2.9 min), activity_438 (+130.02 min) and activity_147 (+132.97 min). The observed spans are −28.98…−2.9 min (P) and ≤ 132.97 min (V/CF/CR). `Config.window_offset_s` shifts all bounds for the T26 sensitivity sweep.

All window constants live in `Config`.

**L4. Global fixed-point elimination**, repeated until nothing changes:
- (a) keep only cases whose subject owns the resource, when the resource has evidence owners;
- (b) one account per case and one case per account;
- (c) a case with one candidate fixes that candidate, and the fixed candidate is removed from all other cases;
- (d) drop rows whose evidence owner matches no candidate case (decoy rows).

**L5. Never-mix tie-break.** Except for legal holds, a case contains either compliant P rows or violating rows, never both. Ambiguous rows go to the case that is consistent with this.

**L6. FIFO pairing fallback.** Leftover ambiguous groups are paired in ascending time order (rows) or ascending id (accounts) against ascending case_id. Each such link is labelled `basis=fifo_pairing` in diagnostics. ⟲³ Rule: when a step's *existence* is certain and only its id is uncertain, emit the most likely id rather than omitting the step. This is measured: FIFO's expected loss is about 13 steps, while omission loses 26 or more and shifts later step order.

**L6b. FIFO coupling (⟲⁴).** An ambiguous worker row follows its signature-matched account's case assignment, rather than being paired independently, which would give it to the earliest case. Expected step-F1 is unchanged, and case-exact rises by ≈ 5 cases.

**L7. Learned link signature (⟲³ default ON; `--signature off` is an ablation).** After identifier links (L1) and owner filters, ambiguous edges are scored by a worker-latency signature that is **learned at runtime without gold**:
- Take all (account row, worker row) pairs where evidence ties both sides to the same subject.
- For compliant (P) and violating (V/CF/CR) rows separately, fit the set of offsets mod 60 (keep residues with support ≥ 2) and the offset range.
- On this dataset the fit gives {9,10,11,39,40,41} over 1000–4200 s (73/73 rows) and {20,21,22,50,51,52} over 4800–11100 s (296/296 rows).
- An edge is kept only if it matches the learned signature. The upper range is capped at the learned maximum: a ±25 % widening swaps two accounts 510 s apart.
- The fit is validated on held-out evidence owners (279 of 280 non-decoy rows) and reported in diagnostics.
- Compliance: this is a timing regularity in participant data, likely a generation artifact. It is disclosed in `code/docs/DECISIONS.md` and the report, which shows the OFF ablation next to it (OFF: 14/24 sample exact vs 22/24; 95 eval cases differ).

**L7b. Typed residue classes (⟲⁴ ablation only, flag `typed_residues=False`).** Residue classes conditioned on resource type are learned the same way: high class for analytics, data_flow and legal_hold; low class for backup and support. They would resolve 5 of the 6 signature-ambiguous rows (+2 steps), but they lean further on a generation artifact. They are reported only, never on by default.

**L8. Never use `case_N → user_(N−2)` or other id-arithmetic artifacts.

**L9. Repopulation.**
- An RP row for `search_N` owned by the case adds `integration_service/data_flow_X` as ACTIVE (if `t ≤ audit_at`).
- An RB row adds a restore path.
- The rows activity_3448 (no requesting user), activity_3434 and activity_3387 (both post-audit) fall out naturally.

**L9b. Orphan policy rows (⟲⁴).** Exclude "Policy action completed" rows whose offset from every candidate account is the uniform 941 s pattern and whose only signature-compatible account is a non-requesting decoy (e.g. account_146 / user_31). P(real) ≈ 0.25, so excluding them has the higher expected value. Flag `exclude_orphan_policy_rows=True`; reported in the ablation.

**L10. Evidence-only union.** Violating observations linked by L1 are added even when no activity row links them (e.g. analytics_5959, data_flow_3064/6090/3250). ⟲ Compliant observations linked by L1 in an admissible window file are added too, as verification-only resources (e.g. backup_5165 BLOCKED for case_390).

**L11. Audit records.**
- `security_service/audit_record_N` is found by subject `u:user_N` in **any** file, at any time.
- If it is cited in the window, the case may use it as COMPLETE proof.
- If it is found only in a later file, it is used only in INCOMPLETE cases with `""`.
- It is never invented. ⟲⁴ **No placeholder audit steps**: emitting one for the 81 cases without a discoverable id would cost ≈ 81 FP and count as invented ids.
- ⟲ The late-only use is behind the flag `use_late_audit_ids` (default ON).

**L12. Hand-crafted / media family** (no A row):
- Resources come from LINK rows (eval) or T rows (samples) plus L1 evidence.
- The account id comes from:
  1. evidence linked by L1 (any time, for ids only);
  2. ⟲ else the account named by the case's T row (samples) or LINK row (eval), basis `activity_pointer`. For samples, `search_documents_primary.source_resource_id` (ev57: search_001 → account_006) also counts as a pointer;
  3. else the `account_00N` convention when the subject is `user_0N` / `user_10` and the case belongs to the hand-crafted family. This is flagged `account_basis=convention`;
  4. else no account step.

---

## 8. Decision and emission

### 8.1 Status
- `NOT_APPLICABLE` if intent ≠ deletion (§9). Steps are `[]`.
- `INCOMPLETE` if any linked resource is violating at `audit_at`.
- `COMPLETE` otherwise.

### 8.2 Steps per resource
| Resource | Steps |
|---|---|
| Violating | FINDING(op_f, state, cite), REMEDIATION(op_r, state, `""`), VERIFICATION(op_v, state, `""`) |
| Compliant, in a COMPLETE case | VERIFICATION(op_v, state, cite). The cite is mandatory; a compliant resource with no citable proof is omitted |
| Compliant, in an INCOMPLETE case | VERIFICATION(op_v, state, `""`) |

⟲ **Activity-basis findings.** When a violating resource's state has `basis=activity` (no admissible observation), the FINDING cites the `activity_id` of the V/CF/CR row that established it, if that row's time is in `[reported_at, audit_at]`; the contract allows activity ids. Otherwise the resource is dropped and logged.

### 8.3 Verification-set rules
- **V1.** The case account always gets `account_service VERIFY_RECORD_ABSENT`, even when it is not a finding. ⟲ The exceptions are V5.3 and L12.4. All 32 gold rows contain this step, so omissions are counted in diagnostics, and a COMPLETE row with `[]` raises a validator warning.
- **V2.** Audit record: `VERIFY_RECORD_PRESENT`, subject to L11.
- **V3.** Legal hold: `legal_service VERIFY_RECORD_PRESENT` (⟲ default ON, flag `verify_legal_holds`).
- **V4.** Tombstone: `VERIFY_RECORD_REDACTED`.
- **V5.** Absence by omission. If the account id is mentioned in no window file, cite one of these, in order:
  1. the file that proves the case's other steps, if it has a scope covering account_service;
  2. else the latest window file with a scope covering account_service;
  3. else omit the step if the case is COMPLETE.

### 8.3b Proof-file coverage (⟲⁴)
Every worker-row resource id named in a cited, in-window proof file must be assigned to some case, or carry an explicit exclusion reason: decoy, sample-only, post-audit, out-of-window or wrong-category. Unassigned ids are a linking defect. The 8 zero-candidate violating rows (+24 steps) found by the stress test must be recovered by the learned upper bound plus L10.

### 8.4 Ordering and serialization
- Sort key: `(phase index, operation index in the §6.4 table of its phase, system_id, resource_id)` with plain string comparison. Renumber `step_no` from 1. ⟲³ The `resource_sort` flag was removed: string and natural order differ in 0 eval and 0 sample cases.

| Phase | Operation order |
|---|---|
| FINDING | REMAINING < EXPOSED_PII < ACTIVE_DATA_FLOW < RESTORE_RISK |
| REMEDIATION | DISABLE < BLOCK < DELETE < REDACT < ANONYMIZE |
| VERIFICATION | ABSENT < PRESENT < REDACTED < ANONYMIZED < DISABLED < BLOCKED |

- This order reproduces 32/32 samples. Where AGENTS §6.5's "downstream before source" prose conflicts with it, the table sort wins, because gold follows it (case_16).
- `steps_json` = `json.dumps(steps, sort_keys=True, separators=(',',':'), ensure_ascii=False)`.
- Each step has exactly 7 keys.
- `output.csv`:
  - header `case_id,deletion_status,steps_json`;
  - 518 rows sorted by `case_id` in **natural numeric order** (⟲ `deletion_requests.csv` is itself in numeric order: case_33, case_34, …, case_550; plain string sort would put case_100 before case_33);
  - written with `csv.writer(..., lineterminator="\n")` (QUOTE_MINIMAL), UTF-8. ⟲⁴ `sample_output.csv` uses LF with a final newline, so re-serializing it must be byte-identical (round-trip gate).

---

## 9. Intent classification

⟲ This section was rewritten after review. The v1.1 guard was a list of 10 literal phrases that each matched exactly one eval NOT_APPLICABLE text, i.e. it was fitted to eval inputs. That breaches AGENTS §6.7 and does not generalize.

1. **LLM classifier (primary when available).** Every request is classified as `{case_id, deletion: bool, confidence, language, reason}`. ⟲³ Default model `claude-opus-5-5` at `effort=low`. Strategy S2 evaluates `claude-haiku-5-5`; changing the default is the user's decision. The system prompt is at least 600 tokens (definitions plus synthetic few-shot examples, **no eval text**) so that prompt caching (minimum 512 tokens) applies.
   - Requests travel in batches of ≤ 25, but **the cache is per item**: key = sha256(model, prompt_hash, normalized text). A decision therefore never depends on batch composition, and batches are formed only from cache misses.
   - Each text is wrapped in delimiters, and the system prompt tells the model to treat it as data (prompt-injection hygiene).
   - The response's case_id set must equal the batch set, with no duplicates. Missing items are retried singly, then fall back to the lexicon.
   - Instructions in the prompt: retention permissions ("keep anonymous statistics", "retain backups", "security records can stay") are **not** negations. A request to verify or complete a deletion **is** a deletion.
2. **Principled lexicon (fallback and disagreement detector).** A documented, language-aware rule set **not** copied from eval texts. A text is NON_DELETION if any of these holds:
   - (a) a negation within 6 tokens before a deletion verb, e.g. `do not|don't|not|never|without` + `delete|erase|remove|close|cancel`, or the FR/ES/PT/JA/KO equivalents (`ne … pas supprimer`, `no borrar/eliminar`, `não excluir/apagar`, `削除しないで`, `삭제하지`);
   - (b) a keep-active construction such as `keep|leave|continue … (account|profile) … (active|open|as it is|using)`;
   - (c) the primary intent is access, correction, export, copy, invoice or opt-out (`send me a copy|what (data|information) you hold|update|change|correct|fix|unsubscribe|stop (promotional|marketing)|portable|invoices`) **and** there is no unnegated deletion verb.
   - Retention-permission phrases are explicitly excluded from (a) and (b).
3. **Corroboration.** The activity row N for the case's account is logged only; it is an activity claim.
4. **Resolution.**
   - LLM available (live or cache hit): the LLM decides, unless its confidence < 0.6, in which case the lexicon decides.
   - `--llm off` or a cache miss: the lexicon decides.
   - Every lexicon/LLM disagreement is written to diagnostics, and the evaluation report includes the agreement matrix (lexicon × LLM × N rows) over all 550 texts.
5. **Expected result on this dataset:** NOT_APPLICABLE = {case_533 … case_542}; no sample case. This is used as a check, never as an input. The lexicon is also tested on paraphrases and multilingual negations that do not occur in the dataset (custom case C2).

---

## 10. Non-functional requirements

| ID | Requirement |
|---|---|
| N1 Determinism | Byte-identical `output.csv` across runs and `PYTHONHASHSEED` values. No unordered iteration. ⟲³ **No sampling parameters**: `temperature`/`top_p`/`top_k` are rejected (400) since API version 2026-10-21. LLM determinism comes from the per-item cache, structured outputs (`output_config.format`), a fixed `max_tokens` and an explicit `output_config.effort` |
| N2 Latency | Under 5 s wall time for the full run from cache (target under 1.5 s). The live LLM run is bounded by a thread pool (≤ 8 concurrent calls) |
| N3 Isolation | The pipeline never reads `sample_output.csv` or `solution/`. A static test enforces this |
| N4 Security | API key only from `ANTHROPIC_API_KEY`. Nothing secret is logged, cached or written |
| N5 Portability | `pathlib`, paths relative to the repo root, UTF-8. ⟲ **Python ≥ 3.9**: the system `python3` here is 3.9.6, and the README and AGENTS name `python3 code/main.py`. So: `from __future__ import annotations`, no `slots=True`, no `match`, no `zip(strict=)`. Stdlib plus an optional, pinned `anthropic`. ⟲³ Split: the core plus `--llm cache`/`off` need Python ≥ 3.9 and the stdlib only; `--llm live` needs Python ≥ 3.10 and `anthropic>=2.0.0` (1.x+ requires 3.10; 2.0.0 sends API version 2026-10-21 by default) |
| N6 Observability | `diagnostics.md` per run: per-case reasons, link basis, assumption flags fired, evidence/template disagreements, cache misses |
| N7 Graceful degradation | If the LLM is unavailable or the cache misses, the deterministic fallbacks apply and the run still completes with 518 valid rows |
| N8 Contract | The output validator passes with 0 violations |

---

## 11. Acceptance criteria

- **A1.** `python3 code/main.py` (default `--llm cache`) writes `output.csv`: 518 rows, header exact, sorted, validator clean.
- **A0** (⟲⁴). The local evaluation release gate R1–R12 in `LOCAL_EVALUATION_STRATEGY.md` §8 passes.
- **A2.** Samples (dev scorer, a *fit* set, not held-out):
  - status 32/32;
  - exact arrays ≥ 30/32, where the only allowed misses are case_18 and case_20 (their audit ids exist in no participant file);
  - ⟲³ learned signature ON (default). The OFF result is reported as an ablation.
- **A3.** NOT_APPLICABLE set equals case_533..case_542. ⟲³ This is checked in diagnostics and the evaluation report only. It is **never** a code or test assertion: no eval case ids appear in shipped code or tests (SCORING_STRATEGY C3).
- **A4.** Every finding cites an admissible file (T3). Every COMPLETE step cites one. Every remediation step, and every INCOMPLETE-case verification step, has `""`.
- **A5.** `code/evaluation/evaluation_report.md` and `usage_report.md` contain all the required sections.
- **A6.** Determinism and latency tests pass.

---

## 12. Open questions and default decisions

| # | Question | Default |
|---|---|---|
| Q1 | case_34 support_9538: the state evidence exists only in evidence_01, captured before the request; ev04 shows the reference only | ⟲³ **EXCLUDE**. The same 'target + one extra pre-request resource' pattern for other image-family users is never in-window, P(gold includes it) ≈ 0.4, so expected value < 0. Flag `allow_pre_request_findings=False` |
| Q2 | Is the `account_00N` convention valid in eval (case_45/61/63)? | ON as a flagged fallback (L12) |
| Q3 | Do legal holds get VERIFY_RECORD_PRESENT? | Yes (V3), flag |
| Q4 | Ambiguous account swap groups | FIFO pairing (L6) |
| Q5 | Choosing the absence-by-omission file | V5 order |
| Q6 | Compliant non-account resources inside an INCOMPLETE case | VERIFICATION with `""` (8.2) |
| Q7 | The case_63 screenshot shows a different person | Trust the LINK row; log the mismatch |
| Q8 | Compare `resource_id` as a string or naturally? | ⟲³ Resolved: string. 0 cases differ; flag removed |
