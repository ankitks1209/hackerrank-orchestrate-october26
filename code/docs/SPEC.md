# SPEC: Ghost Data Still Exists deletion-audit solver

This is the condensed, normative rule set that the source code implements. Docstrings and
comments cite it as `SPEC <id>` (for example `SPEC L7`, `SPEC 8.4`, `SPEC F9`). Every id that
code cites is defined here, and a test (`code/tests/test_design_docs.py`) enforces that.
The document contains no evaluation case ids, user ids or dataset resource ids. Counts are
dataset-wide facts that the code reproduces. They are never inputs to a decision.

Reading guide: sections are numbered `1`..`12`. Rules carry a bold id (`**I1**`, `**F4**`,
`**L7**`). A reference such as `V5.2` means the second item of rule V5, and `L4a` means item (a)
of L4. `ARCHITECTURE.md` shows how the rules are laid out in modules and `DECISIONS.md` records why
the non-obvious ones look the way they do.

## 1. Purpose and scope

For every request in `dataset/deletion_requests.csv` (518 rows) the solver decides:

1. Does the request text authorize deletion? If not, the case is `NOT_APPLICABLE` with `[]` steps.
2. If yes, at `audit_at` does every relevant copy of the subject's data have the treatment that
   `deletion_rules.csv` requires, and is there no active path that can recreate it?
3. It emits an ordered, evidence-backed list of steps: findings, then remediation, then verification.

The result is written to `output.csv` at the repository root. The solver has a deterministic
core: explicit, testable rules over parsed evidence. A language model is used only for request
intent (multilingual text) and for fact extraction from images and PDFs. Every model interaction
is cached and metered.

### 1.1 Glossary

| Term | Meaning |
|---|---|
| Case | One row of the requests file. |
| Subject | The `user_id` that the request email resolves to. |
| Resource | `(system_id, resource_id)`, for example `(search_service, search_<n>)`. |
| Observation | One statement from one evidence file about one resource's state at one time. |
| Scope assertion | A file states that it fully enumerated system S, so a missing row means ABSENT. |
| Proof file | The evidence file cited for a step. |
| Window | `[reported_at, audit_at]`, inclusive. A citable file has `captured_at` inside it. |
| Compliant / violating | The resource already has / does not have its required final state. |
| Treatment | The required policy action: DELETE, REDACT, ANONYMIZE, RETAIN, FLOW (disable), RESTORE (block). |
| Drift | A record that is absent from the primary store but present in a replica. |
| Tombstone | `identity_service/tombstone_<n>`: keeps only the stable `user_id`. |

### 1.2 Out of scope

- Reading `sample_output.csv`, the organizer-only `solution/` tree or any golden label at inference time.
- Inventing resource ids that appear in no participant-visible source. No id is derived from another
  (the `account_00N` convention of an earlier version was withdrawn, L12.3, Q2, D11): a case with no
  account source simply has no account step.

## 2. Inputs

All paths are relative to the repository root and are read only through the `dataset/` allowlist.

| File | Columns | Use |
|---|---|---|
| `deletion_requests.csv` | case_id, email, requested_at, reported_status, reported_at, audit_at, request_text | The 518 cases to answer |
| `sample_deletion_requests.csv` | same | Public samples: joint linking and the development score |
| `sample_output.csv` | case_id, deletion_status, steps_json | **Evaluation only.** Never read by the pipeline |
| `user_identities.csv` | user_id, name, email, phone, email_hash, updated_at | Current identity (850 users) |
| `user_audit_log.csv` | audit_id, user_id, event_time, field_name, old_value, new_value | Historical email, email_hash and phone values (306 rows) |
| `system_activity.csv` | activity_id, event_time, event_type, source_system, target_system, resource_id, reported_result, details | Global event stream (4011 rows) |
| `deletion_rules.csv` | rule_id, data_category, condition, required_action | Policy (15 rules) |
| `evidence_files.csv` | file_id, file_path, origin, captured_at | Manifest (94 files). `captured_at` is the admissibility clock |
| `evidence/**` | 24 `.sql`, 28 `.json`, 1 `.txt`, 26 `.log`, 11 `.png`, 4 `.pdf` | Evidence |

### 2.1 Identity rules

- **I1** Normalize emails with `strip().lower()` and match exactly. Never use prefix, substring,
  fuzzy or name matching.
- **I2** A subject's keys are:
  - the current email, plus every `old_value` and `new_value` of `field_name=email` audit rows,
    following multi-hop chains (the longest chain in the data has three emails);
  - for every email, `sha256(lower(email))` (this reproduces the stored hash for 850 of 850 current
    emails), plus the `email_hash` audit values;
  - the current phone and the old phones (exact string, plus a digits-only form, plus `sha256(digits)`
    as `hp:`, the key of a phone stored only as a digest in a redacted media reply, D25);
  - the `user_<n>` reference.
- **I3** A request email resolves to exactly one subject. All 518 do: 418 match a current email,
  100 a historical one, and 20 are written in upper or mixed case. An unresolved email is a hard
  error that is logged.
- **I4** Decoys never match: look-alike addresses, near-names, names shared by different users,
  staff and business emails.

## 3. Evidence model

### 3.1 Normalized records

```
Observation(file_id, captured_at, entry_time, system_id, resource_id,
            category|None, state, subject_keys:frozenset, locator)
ScopeAssertion(file_id, captured_at, system_id, present_ids:frozenset)
state in {PRESENT, ABSENT, EXPOSED, REDACTED, ANONYMIZED, ACTIVE, DISABLED, BLOCKED}
subject_keys in {'e:<email>', 'h:<sha256>', 'p:<digits>', 'hp:<sha256>', 'u:user_<n>'}
```

`entry_time` is the line, record or snapshot timestamp. When it is missing, `captured_at` is used.
The parser for a file is chosen by **content and structure**, never by `file_id`. Exactly one
parser must claim each file.

### 3.2 Per-family decoding

**F1** SQL topology files (read, regional, reporting and failover replicas). Each file has a
`customer_data_primary` table plus one or more `*_replica*` tables with columns
`resource_id, origin_system, collection_name, record_json, updated_at`.

- `system_id` is `origin_system`.
- A row present in **any** table means the resource is present. Drift is a row in a replica table
  but not in primary. Every replica table is checked, because regional drift can sit in only one.
- Subject keys come from these `record_json` fields: email, phone, email_hash, user_id,
  `document.email`, `document.customer_reference`, subject_reference, subject_selector,
  owner_email, uploaded_by, and emails inside `message_text`.

| collection_name | Category | State rule |
|---|---|---|
| customer_profiles | USER_PROFILE | PRESENT |
| customer_search_documents | SEARCH_INDEX_ENTRY | PRESENT |
| customer_analytics_reports | ANALYTICS_PROFILE | user_id, email, phone and email_hash all null: ANONYMIZED, else EXPOSED |
| support_conversations | SUPPORT_MESSAGE | `message_text == "[REDACTED]"`: REDACTED, else EXPOSED |
| ticket_attachments | SUPPORT_ATTACHMENT | PRESENT |
| customer_export_jobs | USER_EXPORT | PRESENT |
| connector_configurations | DATA_FLOW | `enabled`: ACTIVE, else DISABLED |
| backup_catalog | BACKUP_ARCHIVE | `restore_allowed`: ACTIVE, else BLOCKED |
| security_audit_events | SECURITY_AUDIT_LOG | PRESENT |
| retained_order_records | LEGAL_HOLD_RECORD | PRESENT |
| deleted_customer_references | ACCOUNT_TOMBSTONE | name, email, phone and email_hash all null: REDACTED, else EXPOSED |

**F2** SQL inventory files. Typed tables, each owned by one system:

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

- `snapshot_scope(origin_system, captured_at)` gives one scope assertion per in-scope system. A system
  that is **in** scope with no matching row is ABSENT. A system **not** in scope is *unobserved*.
- `account_status = DELETION_PENDING` is PRESENT.
- On support records, a set `requester_email` means EXPOSED, and only a `customer_reference` means REDACTED.
- Inventory files cannot tell a support message from an attachment.

**F3** SQL special schemas, detected by table names:

- `customer_profiles_primary` with `customer_profiles_failover_replica`: profile drift. The pair is
  also the absence proof for profiles that are not listed.
- `search_documents_primary` (with `source_resource_id` and `indexed_at`). `source_resource_id` is kept
  as an account pointer (see L12.2).

**F4** JSON service exports. Structure `service_exports.<system_id>.<list>[]`, `entry_time = observed_at`.

| List | State rule |
|---|---|
| profile_lookups | `status_code 404` or `profile: null`: ABSENT (no keys). 200: PRESENT, even if only the email is left |
| analytics `profiles` | all identifiers null: ANONYMIZED, else EXPOSED |
| restore_entries | `restore_allowed`: ACTIVE, else BLOCKED |
| exports | PRESENT |
| connectors | `enabled`: ACTIVE, else DISABLED |
| index_queries | `hits.total > 0`: PRESENT, keys from `hits.documents[].email` |
| audit_records | PRESENT |
| support tickets | any `requester_*` set: EXPOSED. All null with a `customer_reference`: REDACTED. No category (message or attachment is left to the activity event type) |

**F5** JSON snapshot bundles. Structure `snapshots[{captured_at, data_store, collection, records[]}]`.

- `system_id` is `data_store` and `entry_time` is the snapshot's `captured_at`. Collections decode as in F1.
- An empty `records` list for a collection is a scope assertion with no ids. An empty profiles
  collection therefore proves that the account is absent.
- Rows of `operational_record_history` use the F6 states, with `system_id` taken from the row's own
  `system` field. The subject key comes from `lookup_value`, not from `subject_reference`. The bundle's
  `data_store` is **not** the system for these rows.
- A snapshot's `entry_time` is the snapshot time, not a row's own `updated_at`.
- One bundle can contain layers at several times: one stale, one at audit and one recreated after audit.

**F6** Flat ledgers and diag logs. Structure
`records[{recorded_at, system, resource_id, record_type, result, subject_reference}]`, plus the
`record_lookup` log lines. `category = record_type`, `system_id = system`, `entry_time = recorded_at`.
`result` maps to a state: FOUND to PRESENT, NOT_FOUND to ABSENT, IDENTIFIABLE to EXPOSED, and
ANONYMIZED, REDACTED, ACTIVE, DISABLED, BLOCKED to themselves.

**F7** JSON collections `{captured_at, source, collection, records}`. `source` is not the system id.
The collection maps to `analytics_platform` or `export_service`.

**F8** TXT handover. Lines match `- ts | system | resource_id | category | result | key`. A key of
`no direct identifier` means no key. The result column uses the F6 vocabulary.

**F9** Logs. Every line is `<ISO-ts> <body>` and the body is one of 8 formats:

1. logfmt
2. readback logfmt (literal `null`)
3. timestamp plus JSON
4. RFC 5424 syslog
5. bracketed `[LVL] [svc] [trace] event:`
6. pipe-delimited
7. cloud nested (`message="..."`, needs a second key=value parse)
8. diag `record_lookup` (F6 vocabulary). It can start with any level, and warning lines carry
   IDENTIFIABLE rows.

Subject keys come from `*_started` lines (`lookup_key`, `match_key`, `subject_ref`, `subject_key`,
`scan_key`, `owner_key`), **joined by trace id and never by adjacency**, and from inline keys
(`correlation_key`, `matched_value`, `customer_email`, `email`, `requester_email`, `owner_email`,
`customer_reference`, `subject_reference`). A line with no trace id gets only its inline keys; it
does not fall back to the instance name.

| Event | State | Category |
|---|---|---|
| profile_lookup_completed | rows=0 or 404: ABSENT; rows=1 or 200: PRESENT | USER_PROFILE |
| index_query_completed `result=hit` | PRESENT | SEARCH |
| audit_record_read_completed | PRESENT | SECURITY_AUDIT_LOG |
| analytics_identity_scan | EXPOSED | ANALYTICS |
| analytics_profile_read `direct_identifiers=0` | ANONYMIZED | ANALYTICS |
| analytics_profile_read_completed | all null: ANONYMIZED, else EXPOSED | ANALYTICS |
| contact_lookup_completed `email_opt_in=true` | PRESENT | SECONDARY_IDENTIFIER (DELETE) |
| message_pii_scan | EXPOSED | SUPPORT_MESSAGE |
| attachment_pii_scan | PRESENT | SUPPORT_ATTACHMENT |
| message_read `[REDACTED]` | REDACTED | SUPPORT_MESSAGE |
| support_ticket_read_completed | requester null: REDACTED, else EXPOSED | none (activity event type decides) |
| connector_heartbeat, connector_config_loaded, `_read_completed` | enabled: ACTIVE, else DISABLED | DATA_FLOW |
| restore_candidate_evaluated `eligible=true deletion_block=false` | ACTIVE | BACKUP |
| restore_authorization_completed `decision=deny` | BLOCKED | BACKUP |
| restore_policy_read_completed | restore_allowed: ACTIVE, else BLOCKED | BACKUP |
| export_download_check, export_metadata_read_completed `available=true` | PRESENT | USER_EXPORT |
| retained_order_loaded | PRESENT | LEGAL_HOLD |
| contact_query_completed rows=1 with deletion_marker_check `marker_found=false` | PRESENT | support_platform |

Dropped entirely: decoy lines of a profile service that uses five-digit resource ids, router and
collector framing lines, and noise. Noise is **every event that is neither in the state table nor a
`*_started` key line nor framing**. The known noise set (cache lookups, connection handling,
dependency retries, webhooks, thumbnail failures, queue consumers and similar) is enumerated in
code. Anything outside the state table and the noise set is reported in the diagnostics as an
`unknown_event`. The log level carries no state meaning.

**F10** Media (PNG and PDF).

- Facts are extracted by a vision call (cached). A file maps to a resource in one of two ways.
  - **(a) LINK join.** A `LINK_RESOURCE_IDENTITY` activity row has an alias (the parenthesised display
    id, or the resource id) equal to an extracted display id. The LINK row supplies `system_id`,
    `resource_id`, `user_id` and `email`.
  - **(b) Literal id plus identifier.** The extracted text contains a literal resource id with a known
    prefix (see `SYSTEM_BY_PREFIX`), **and** an extracted email, phone or `user_<n>` resolves to a
    subject key (L1). The extraction also returns a category (attachment, message, profile and so on),
    so the treatment can be decided. In a file where some record joins a LINK row, a bare `user_<n>`
    is not enough: such a screen repeats its subject filter on every row, so only a LINK row, a shown
    email or a shown phone ties a record to the subject (D18).
- Display labels (ticket numbers, product labels, file names) are never resource ids by themselves.
- Facts are never mapped by timing; the small offset between a LINK row and its screenshot is a
  generation artifact.
- `entry_time` is the manifest `captured_at`.
- If the alias does not validate, or the extraction is missing, the observation is dropped and logged.
- A legal register that names only `user_<n>` and order ids yields no observation; it is logged.

## 4. Activity semantics

`reported_result` is **never** evidence of state. The `details` template and `event_type` are
interpreted as follows. The counts are those of the dataset and are verified by the activity tests.

| Code | `details` pattern | n | Meaning |
|---|---|---|---|
| A | `Deletion worker submitted primary profile (account_<n>) to account_service.` | 532 | Candidate case account. Its `reported_result` mirrors `reported_status` and is used **only** as a linking constraint |
| P | `Policy action completed for (X).` | 248 | X is compliant: a verification step |
| V | `Deletion worker received the final result for (X) from (S).` | 558 | X is violating, even when the result says SUCCESS |
| CF | `Connector status check confirmed that data flow (data_flow_<n>) remains enabled.` | 89 | Active flow |
| CR | `Restore-access check confirmed that archive (backup_<n>) can still be restored.` | 28 | Restore risk |
| R | `Replication worker reported its final checkpoint for (account_<n>).` | 55 | Account still present (drift) |
| RP | `Active connector repopulated downstream resource (search_<n>).` (`resource_id` is the data flow) | 31 | The flow is active for the owner of that search document |
| RB | `Restore job repopulated downstream resource (search_<n>).` | 1 | Restore path |
| N | `Privacy intake classified request for (account_<n>) as non-deletion` | 10 | Corroborates NOT_APPLICABLE |
| L | `Data catalog linked X (alias) to email and user_<n>` or `Attachment catalog confirmed X (alias) belongs only to ...` | 12 | Media decoding |
| T | `... Target resource: (X).` | 12 | Sample-only resource pointer. **Not** truth |
| noise | `... processed <prefix>_<n>.` | 2435 | Ignored |

**Treatment comes from the activity `event_type`.**

| event_type | Treatment |
|---|---|
| DELETE_RECORD | DELETE |
| REDACT_RECORD | REDACT |
| ANONYMIZE_RECORD | ANONYMIZE |
| CHECK_DATA_FLOW, DISABLE_DATA_FLOW | FLOW |
| CHECK_RESTORE_ACCESS, BLOCK_RESTORE | RESTORE |
| RETAIN_RECORD | RETAIN |

System id per row kind:

| Row kind | system_id |
|---|---|
| A, P, V, CF, CR, T, L | `target_system` |
| RP | `integration_service` (`resource_id` is the data flow, `related_rid` is the search document, `target_system` is the search service) |
| RB | `backup_service` |
| R, N | `account_service` (`target_system` is the replication cluster or the intake system) |

A test asserts that every non-noise row's system id agrees with `SYSTEM_BY_PREFIX`.

**Precedence.** For **state**, evidence observations inside the window win over everything else.
Activity templates are used for (1) discovering resources and linking them to cases, (2) treatment and
(3) state only when no admissible observation exists. Every disagreement between evidence and a
template is logged.

## 5. Time rules

- **T1** An observation counts toward a case's state only if both its file has
  `captured_at <= audit_at` and its `entry_time <= audit_at`.
- **T2** A resource's state is the admissible observation with the greatest `(entry_time, captured_at)`.
  Ties are broken by manifest order.
- **T3** A step may cite a file only if `reported_at <= captured_at <= audit_at`. All bounds are
  inclusive and use the manifest clock.
- **T4** Nothing after `audit_at` influences a case: no file, entry or activity row later than the case's
  `audit_at` changes a state, a status, a link, an owner or a resource **id**. An evidence owner counts for a
  case only when a file admissible at that case's `audit_at` ties it (T1), and an audit-record id found only
  in a later file is not emitted. Every tool the agent calls enforces the same cutoff (12.2).
- **T5** Each case is scoped by its own times. A user with several cases never shares state across them.
- **T6** All times are parsed once into integer UTC epoch seconds.

## 6. Policy mapping

| Rule | Category | Resource (system) | Violating state | Finding, remediation, verification | Compliant verification |
|---|---|---|---|---|---|
| 01 | USER_PROFILE | account_<n> (account_service) | PRESENT | REMAINING, DELETE, ABSENT | ABSENT |
| 02, 10 | SECONDARY_IDENTIFIER, MARKETING_PROFILE | analytics contact (opt-in), marketing_<n> (marketing_platform) | PRESENT | REMAINING, DELETE, ABSENT | ABSENT |
| 03 | SEARCH_INDEX_ENTRY | search_<n> | PRESENT | REMAINING, DELETE, ABSENT | ABSENT |
| 05 | SUPPORT_MESSAGE | support_<n> | EXPOSED | EXPOSED_PII, REDACT, REDACTED | REDACTED |
| 06 | SUPPORT_ATTACHMENT | support_<n>, object_<n> (object_storage) | PRESENT | REMAINING, DELETE, ABSENT | ABSENT |
| 07, 08 | ANALYTICS_PROFILE, PRODUCT_TELEMETRY | analytics_<n> | EXPOSED | EXPOSED_PII, ANONYMIZE, ANONYMIZED | ANONYMIZED |
| 09 | USER_EXPORT | export_<n> (export_service) | PRESENT | REMAINING, DELETE, ABSENT | ABSENT |
| 11 | EMAIL_DELIVERY_LOG | none | none | no evidence in the dataset | none |
| 12 | SECURITY_AUDIT_LOG | audit_record_<n> (security_service) | never | none | PRESENT |
| 13 | LEGAL_HOLD_RECORD | legal_hold_<n> (legal_service) | never | none | PRESENT |
| 14 | BACKUP_ARCHIVE | backup_<n> | ACTIVE (restorable) | RESTORE_RISK, BLOCK_RESTORE, RESTORE_BLOCKED | RESTORE_BLOCKED |
| 15 | ACCOUNT_TOMBSTONE | tombstone_<n> (identity_service) | EXPOSED | EXPOSED_PII, REDACT, REDACTED | REDACTED |
| none | connector | data_flow_<n> (integration_service) | ACTIVE | ACTIVE_DATA_FLOW, DISABLE, DISABLED | DISABLED |

Discriminators:

- **Message versus attachment.** The evidence category decides when present (F1, F6, F8, F9).
  Otherwise the activity event type decides: REDACT_RECORD means a message and DELETE_RECORD means an
  attachment.
- **Analytics profile versus secondary contact.** A `contact_lookup ... email_opt_in` record is DELETE
  with a REMAINING finding. Any analytics record with a direct identifier is ANONYMIZE with an
  EXPOSED_PII finding.
- **Drift.** Drift on an account is an account REMAINING finding. The replication sync itself is **not**
  a data flow.
- Backups are never deleted. Tombstones are never deleted. Redacting a tombstone does not delete the
  account again.
- Rules 04 (cache), 08 (telemetry) and 11 (email delivery log) have no matching evidence. The engine
  supports them generically but never fabricates them.

## 7. Case linking

Goal: for each authorized case, find the resources that belong to it: the case account,
worker-handled resources, evidence-discovered resources, audit records, legal holds and tombstones.
Only requests whose intent is deletion take part: a request that does not authorize deletion owns no
deletion-worker run, so it must not take a worker row from a case that does (D19).

- **L1** Identifier links (strongest). An observation whose `subject_keys` intersect the subject's keys
  belongs to the subject. It attaches to a case only if T1 holds for that case and the file is within
  that case's lifetime (T5).
- **L2** Account candidates, from the order of the process. The deletion worker acts after the request is
  submitted and submits the account before the workflow reports, so an A row (ACCOUNT_SUBMIT) is a candidate
  for a case when `requested_at < t(A) <= reported_at` and `result(A)` equals the mirror of the case's
  `reported_status`. No latency from `reported_at` is assumed.
- **L3** Worker-row candidates, from the same order. A P row (policy action completed) is a candidate when
  `requested_at < t <= reported_at`; V, CF and CR rows (violation, data flow, restore) are observed after the
  report and before the audit, so they are candidates when `reported_at < t <= audit_at`. Inside the graph a
  worker row must also follow its case's account row (L4d). Nothing here is a fitted constant: measured on
  the participant files, the rows that evidence ties to a subject lie 0.73-1.25 h before the report (account),
  0.05-0.48 h before it (policy) and 0.63-2.22 h after it (violation side), but those spreads are not used,
  so a row that a longer or shorter delay would have hidden is a candidate too and is separated by evidence,
  by the agent or by the fallback.
- **L4** Global fixed-point elimination, repeated until nothing changes:
  - **L4a** keep only cases whose subject owns the resource, when the resource has evidence owners
    admissible at that case's `audit_at` (T1, T4). Of a case's account candidates, the ones that evidence
    ties to its own subject replace the ownerless ones: an identifier link (L1) outranks timing;
  - **L4b** one account per case and one case per account;
  - **L4c** a case with one candidate fixes that candidate, and the fixed candidate is removed from all
    other cases;
  - **L4d** drop rows whose evidence owner matches no candidate case (decoy rows).
- **L5** Never-mix tie-break. Except for legal holds, a case contains either compliant P rows or
  violating rows, never both. Ambiguous rows go to the case that is consistent with this.
- **L6** Deterministic fallback. What the fixed point leaves contested, and the agent (12) does not decide,
  is paired in ascending id order: accounts by ascending id against ascending case id, tied rows by the
  report nearest in process order (L6b). Each such link is labelled `basis=fifo_pairing` or `coupling`
  and counted as an assumption in the diagnostics. When a step's *existence* is certain and only its id is
  uncertain, the most likely id is emitted instead of omitting the step: the expected loss from a wrong id
  is smaller than from a missing step that also shifts the order of later steps.
- **L6b** Nearest report. A still-tied P row goes to the candidate case with the earliest `reported_at`
  after it; a still-tied V, CF or CR row goes to the one with the latest `reported_at` before it; ties go to
  the lower case id. A row also follows the case assignment of its account, which pairing may have settled
  (`coupling`).
- **L7** Withdrawn. The learned worker-latency signature (offsets modulo 60 s) fitted a regularity of the
  generated data, not a property of the process, and is gone with its flags (`signature`,
  `strict_signature_time`); the agent receives timing as data (offsets), never as a filter. See D3.
- **L8** Never use id arithmetic such as `case_N` to `user_(N-2)`, or any other id artifact.
- **L9** Repopulation. An RP row for a search document owned by the case adds
  `integration_service/data_flow_<n>` as ACTIVE (if `t <= audit_at`). An RB row adds a restore path.
  Rows with no requesting user, or dated after `audit_at`, fall out naturally.
- **L9b** Withdrawn. The orphan-policy-row exclusion depended on the learned signature and is gone.
- **L10** Evidence-only union. Violating observations linked by L1 are added even when no activity row
  links them. Compliant observations linked by L1 in an admissible window file are added too, as
  verification-only resources.
- **L11** Audit records. `security_service/audit_record_<n>` is emitted for a case when the subject's key is
  tied to it by evidence admissible at `audit_at` (T1) and a file captured in `[reported_at, audit_at]`
  names it, so a COMPLETE case can cite that file. An id found only in a file captured before the report or
  after the audit is not emitted (T4). It is never invented: there are **no placeholder audit steps**.
- **L12** Hand-crafted and media family (no A row). Resources come from LINK rows (evaluation) or T
  rows (samples) plus L1 evidence. The account id comes from, in order:
  - **L12.1** evidence linked by L1 and admissible at the case's `audit_at` (T1); among several accounts,
    the ones a window file names;
  - **L12.2** else the account named by the case's T row (samples) or LINK row (evaluation), basis
    `activity_pointer`. For the samples, `source_resource_id` of a search document (F3) also counts as a
    pointer;
  - **L12.3** withdrawn: the `account_00N` convention is gone, no account id is guessed (Q2);
  - **L12.4** else no account step.

## 8. Decision and emission

### 8.1 Status

- `NOT_APPLICABLE` if intent is not deletion (section 9). Steps are `[]`.
- `INCOMPLETE` if any linked resource is violating at `audit_at`.
- `COMPLETE` otherwise.

### 8.2 Steps per resource

| Resource | Steps |
|---|---|
| Violating | FINDING(op_f, state, cite), REMEDIATION(op_r, state, empty), VERIFICATION(op_v, state, empty) |
| Compliant, in a COMPLETE case | VERIFICATION(op_v, state, cite). The cite is mandatory; a compliant resource with no citable proof is omitted |
| Compliant, in an INCOMPLETE case | VERIFICATION(op_v, state, empty) |

**Absent under a keep-the-record treatment.** A resource whose treatment is REDACT or ANONYMIZE but
whose state at `audit_at` is ABSENT (an absence-proving scope, a 404 or a NOT_FOUND) is neither
violating (the violating state of section 6 is EXPOSED, and nothing is exposed) nor compliant (no
redaction or anonymization can be verified on a record that is gone). It is dropped and logged: an
absence proof can back neither an EXPOSED_PII finding nor a REDACTED or ANONYMIZED verification.

**Activity-basis findings.** When a violating resource's state has `basis=activity` (no admissible
observation), the FINDING cites the `activity_id` of the V, CF or CR row that established it, if that
row's time is inside `[reported_at, audit_at]`. The contract allows activity ids. Otherwise the resource
is dropped and logged.

### 8.3 Verification-set rules

- **V1** The case account always gets `account_service VERIFY_RECORD_ABSENT`, even when it is not a
  finding. The exceptions are V5.3 and L12.4. Omissions are counted in the diagnostics, and a COMPLETE
  row with `[]` raises a validator warning.
- **V2** Audit record: `VERIFY_RECORD_PRESENT`, subject to L11.
- **V3** Legal hold: `legal_service VERIFY_RECORD_PRESENT` (flag `verify_legal_holds`, default on).
- **V4** Tombstone: `VERIFY_RECORD_REDACTED`.
- **V5** Absence by omission. If the account id is mentioned in no window file, cite one of these, in order:
  - **V5.1** the file that proves the case's other steps, if it has a scope covering `account_service`;
  - **V5.2** else the latest window file with a scope covering `account_service`;
  - **V5.3** else omit the step if the case is COMPLETE.

### 8.3b Proof-file coverage

Every worker-row resource id named in a cited, in-window proof file must be assigned to some case or
carry an explicit exclusion reason: decoy, sample-only, post-audit, out-of-window or wrong-category.
An unassigned id is a linking defect and is reported in the diagnostics.

### 8.4 Ordering and serialization

The sort key is `(phase index, operation index in the operation table of its phase, system_id,
resource_id)` with plain string comparison. `step_no` is renumbered from 1.

| Phase | Operation order |
|---|---|
| FINDING | REMAINING, EXPOSED_PII, ACTIVE_DATA_FLOW, RESTORE_RISK |
| REMEDIATION | DISABLE, BLOCK, DELETE, REDACT, ANONYMIZE |
| VERIFICATION | ABSENT, PRESENT, REDACTED, ANONYMIZED, DISABLED, BLOCKED |

- This order reproduces the public samples. Where the challenge prose ("downstream before source")
  conflicts with it, the table sort wins, because the sample answers follow the table.
- `steps_json = json.dumps(steps, sort_keys=True, separators=(',', ':'), ensure_ascii=False)`.
- Each step has exactly seven keys.
- `output.csv` has the header `case_id,deletion_status,steps_json`, 518 rows sorted by `case_id` in
  **natural numeric order**, written with `csv.writer(..., lineterminator="\n")` in UTF-8. The requests
  file is itself in numeric order, so plain string order would be wrong.

## 9. Intent classification

1. **LLM classifier (primary when available).** Every request is classified as
   `{case_id, deletion: bool, confidence, language, reason}`.
   - Requests travel in batches of at most 25, but **the cache is per item**: the key is
     `sha256(model, prompt hash, normalized text)`. A decision therefore never depends on batch
     composition, and batches are formed only from cache misses.
   - Each text is wrapped in delimiters, and the system prompt tells the model to treat it as data.
   - The response's case id set must equal the batch set, without duplicates. Missing items are retried
     singly and then fall back to the lexicon.
   - Retention permissions ("keep anonymous statistics", "retain backups") are **not** negations. A
     request to verify or complete a deletion **is** a deletion.
   - The system prompt is large enough for prompt caching, uses synthetic examples and contains no
     evaluation text.
2. **Principled lexicon (fallback and disagreement detector).** A documented, language-aware rule set
   that is not derived from evaluation texts. A text is NON_DELETION if any of these holds:
   - **9.2a** a negation within six tokens before a deletion verb, for example `do not`, `never`,
     `without` before `delete`, `erase`, `remove`, `close`, `cancel`, or the French, Spanish,
     Portuguese, Japanese and Korean equivalents;
   - **9.2b** a keep-active construction such as `keep` or `leave` ... account or profile ... `active`,
     `open`, `as it is`, `using`;
   - **9.2c** the primary intent is access, correction, export, copy, invoice or opt-out **and** there
     is no unnegated deletion verb.
   Retention-permission clauses never count for 9.2a or 9.2b.
3. **Corroboration.** The activity row N for the case's account is logged only; it is an activity claim.
4. **Resolution.**
   - LLM available (live or cache hit): the LLM decides, unless its confidence is below the configured
     floor, in which case the lexicon decides.
   - `--llm off` or a cache miss: the lexicon decides.
   - Every lexicon and LLM disagreement is written to the diagnostics, and the evaluation report
     includes the agreement matrix.
5. The expected NOT_APPLICABLE set is a check made in the diagnostics and the evaluation report. It is
   never an input, a code assertion or a test assertion. The lexicon is also exercised on paraphrases
   and multilingual negations that do not occur in the dataset.

## 10. Non-functional requirements

| Id | Requirement |
|---|---|
| **N1** | **Determinism.** Byte-identical `output.csv` across runs and hash seeds. There are **no sampling parameters** (`temperature`, `top_p`, `top_k`): the API rejects them. Model determinism comes from the per-item cache, structured outputs, a fixed `max_tokens` and an explicit `effort` |
| **N2** | **Latency.** Under 5 s wall time for a full run from cache. Live model calls run one at a time |
| **N3** | **Isolation.** The pipeline never reads `sample_output.csv` or `solution/`. A static test enforces it |
| **N4** | **Security.** The API key comes only from the environment. Nothing secret is logged, cached or written |
| **N5** | **Portability.** `pathlib`, paths relative to the repository root, UTF-8. The core and `--llm off` or `cache` need Python 3.9 and the standard library only. `--llm live` needs Python 3.10 and the pinned SDK |
| **N6** | **Observability.** `diagnostics.md` per run: per-case reasons, link basis, assumption flags fired, evidence and template disagreements, cache misses |
| **N7** | **Graceful degradation.** If the model is unavailable or the cache misses, the deterministic fallbacks apply and the run still completes with 518 valid rows |
| **N8** | **Contract.** The output validator reports 0 violations |

## 11. Acceptance criteria

- **A1** `python3 code/main.py` (default `--llm cache`) writes `output.csv`: 518 rows, exact header, sorted,
  validator clean.
- **A2** On the public samples (a development set, not held out) the statuses and the exact arrays are
  reported with the agent off (the deterministic fallback) and on, and the agent run may not score below the
  fallback. The measured fallback floor is pinned in `tests/test_golden.py`.
- **A3** The NOT_APPLICABLE set is checked in the diagnostics and the evaluation report only.
- **A4** Every finding cites an admissible file (T3). Every COMPLETE step cites one. Every remediation
  step, and every verification step of an INCOMPLETE case, has an empty `evidence_id`.
- **A5** `evaluation/evaluation_report.md` and `evaluation/usage_report.md` contain the required sections.
- **A6** Determinism and latency tests pass, and `python3 -m evaluation check` (format, contract,
  byte-identical reruns under two hash seeds, label-free invariants, sample score) exits 0.

## 12. The agent stage

Contested links are the part of case linking that rules cannot settle: after L1-L6b, a worker row or an
account row is still a candidate of several cases. The agent stage decides them with evidence; whatever it
leaves open is decided by the deterministic fallback (L6). It runs only with `--agent on` and a model
(`--llm cache` or `live`); with the agent off the fallback decides everything.

### 12.1 Units

A **contest** lists the rows and accounts that the fixed point left open and the cases still competing for
each. The router (12.5) sends cases to `investigate` or `accept`. A **unit** is a connected component of
the cases that compete for the same targets and contains at least one case routed `investigate`; a
component of more than 8 cases is cut into chunks in order of `reported_at`. A contested target is offered
to exactly one unit, the one holding the case the fallback would pick, and the model sees only the
candidates inside the unit.

### 12.2 Tools

One `ToolRegistry` serves the units. Each tool has a documentation-style description (purpose, when to use,
when not to, arguments, return shape, limits, errors), a strict JSON schema (`additionalProperties: false`,
every property required, enums for finite values, `strict: true` on the definition) and a handler over the
unit's `Workspace`.

| Tool | Answers |
|---|---|
| `resolve_identity(case_id, email)` | the subject and the identifiers it had at the case's `audit_at` |
| `search_evidence(case_id, mode, resource_id)` | admissible observations of a resource or of the subject (at most 25, `truncated` flagged) |
| `read_evidence(case_id, file_id)` | at most 4000 characters of the file's records that carry the subject's keys |
| `get_activity(case_id, kind)` | candidate rows with offsets from `requested_at` and `reported_at`, the claimed result and the competing cases |
| `check_policy(system_id, resource_id, state)` | the treatment and the finding, remediation and verification operations from `PolicyEngine` |
| `submit_answer(decisions, summary)` | the model's decisions, checked by the gate (12.3) |

### 12.3 Guardrails

They sit inside the tools and the gate, not in the prompt.

- **Cutoff.** A handler reads evidence and activity only through the workspace, which cuts every answer at
  the case's `audit_at` (T1, T4); `read_evidence` is an error for a file captured later.
- **Policy.** The model never picks operations: `check_policy` reports them and `CaseBuilder` and `emit`
  derive the steps.
- **Citations.** A `CitationLedger` records every id a tool returned (file, activity and audit ids) with the
  moment it came into existence. `submit_answer` is rejected, with an error result the model can fix, when it
  cites an id that is not in the ledger or is newer than the case's `audit_at`, assigns a case outside the unit
  or one that is not a candidate of the target, assigns a target twice, offers a target the unit lacks, or gives
  no rationale.
- **Output.** The final steps come from `CaseBuilder` and `emit` and pass `contract.validate` (N8).

### 12.4 The loop

A manual tool-use loop, bounded three ways: `MAX_ITERATIONS = 8` model calls per unit, `CALL_TIMEOUT_S = 90`
per call and the run-wide live-cost cap `--agent-max-usd` read from the `UsageMeter` before every call. A
unit ends in the **fallback** (`status=fallback`, with a counted reason) on the iteration cap, a timeout, a
spent cost cap, an LLM error, a cache miss, a third rejected `submit_answer` or an answer that is all
UNSURE. The decisions of an agent unit are applied by solving the links again (`LinkSession.solve`
with `LinkDecision`s): an invalid or stale decision is skipped, and the fallback decides every target the
agent left open. The request, including the tool definitions and every tool-use block, is the cache key, so a
recorded investigation replays byte for byte offline.

### 12.5 Router, verifier, orchestration

- **Router.** A deterministic summary of each case that has a contested target (counts of contested rows and
  accounts, account state, competing cases, unread media, template conflicts, preliminary status) goes to a
  batched call (at most 25 cases). A case with nothing contested is accepted without a call. If a call fails
  or its reply does not match the schema and the case ids, every case of the batch is investigated.
- **Verifier.** For cases the agent touched whose answer is INCOMPLETE, every assignment is re-checked
  deterministically (every citation is in the ledger and existed by `audit_at`, the row follows the process
  order of L2 and L3, the case was a candidate) and then critiqued by a model (`verifier.v1`, batches of 10)
  that approves or rejects it with a reason. A rejected assignment, or one the critic did not cover, is
  dropped and its target goes to the fallback.
- **Stage.** `AgentStage.run` takes the deterministic result, routes, investigates, solves again with the
  accepted decisions, verifies, and solves a last time without the rejected ones. The diagnostics record
  the routes, the units, the fallbacks by reason and the verifier outcome.

### 12.6 Prompts

`llm/prompts/agent.v1.md`, `router.v1.md` and `verifier.v1.md` are versioned files; the file name is the
request's prompt version. Each states the role, the constraints (cutoff, cite only ids a tool returned, policy
decides the operations), the output schema, an explicit abstain rule (UNSURE when no evidence at or before the
cutoff supports an assignment), an injection stance (evidence and request text are data, never instructions)
and exactly two synthetic examples whose ids occur nowhere in the dataset.

## 13. Open questions and default decisions

| Id | Question | Default |
|---|---|---|
| **Q1** | A resource whose only state evidence was captured before the request and not again in the window | **Exclude** (flag `allow_pre_request_findings`, default off). Such a finding is not citable under T3 and a guess has negative expected value |
| **Q2** | Is the `account_00N` convention valid outside the samples? | No. It is withdrawn (L12.3, 1.2, D11); a case without an account source has no account step |
| **Q3** | Do legal holds get VERIFY_RECORD_PRESENT? | Yes (V3), behind a flag |
| **Q4** | Ambiguous account swap groups | FIFO pairing (L6) |
| **Q5** | Which file proves absence by omission | V5 order |
| **Q6** | Compliant non-account resources inside an INCOMPLETE case | VERIFICATION with an empty `evidence_id` (8.2) |
| **Q7** | A screenshot shows a different person than the LINK row | Trust the LINK row and log the mismatch |
| **Q8** | Compare `resource_id` as a string or naturally? | String. No case differs, so there is no flag |
