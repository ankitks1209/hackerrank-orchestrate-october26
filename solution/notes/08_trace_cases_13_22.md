# 08 — Full trace of sample cases case_13 .. case_22

Scripts (read-only, stdlib):
- `solution/notes/scripts/trace_cases.py case_13 ...`: resolves the identity, greps every text evidence file (logs/json/sql/txt) for every identifier and gold resource_id, follows `trace_id` siblings in logs, and lists matching `system_activity` rows. Rows captured after audit_at are flagged `LATE`.
- `solution/notes/scripts/gold_resource_presence.py`: for every sample gold resource, lists which files and activities mention it.
- `solution/notes/scripts/check_order.py`: checks the step-ordering rule against all 32 sample golds.
- `solution/notes/scripts/near_dupes.py`: lists near-duplicate decoy emails and phones in the evidence.

PNG and PDF facts come from `04_images_pdfs.md`; I re-checked evidence_04 visually.

---

## 0. Headline findings

1. **One proof file per case.** In every case, all evidence-bearing steps cite a single file. It is the batch snapshot captured at or just before `audit_at`, and after `reported_at`:
   - evidence_03 (`customer_account_handover_20261001.txt`, captured 10-01T12:00:00Z, which is exactly audit_at): case_13, case_14.
   - evidence_01 (`service_events_ap_south_20260915.log`, captured 09-15T11:59:39Z): case_15, case_17, case_19.
   - evidence_05 (`customer_data_read_replica_20260921.sql`, captured 09-21T10:00:00Z, exactly audit_at): case_16, case_22.
   - evidence_94 (`resource_lookup_trace_20260926_103856.log`, captured 09-26T10:38:56Z): case_18, case_20.
   - evidence_92 (`service_resource_export_20260915_114455.json`, captured 09-15T11:44:55Z): case_21.

   For case_21, evidence_01 (11:59:39) is also before audit_at but holds nothing about user_21, so evidence_92 is chosen. The cutoff is **inclusive** (`captured_at <= audit_at`): evidence_03 and evidence_05 equal audit_at exactly.
2. **The audit_record verification can be unobservable.**
   - Gold `VERIFY_RECORD_PRESENT security_service audit_record_6645` (case_18) and `audit_record_5569` (case_20) appear in **no participant file at all**. The only match is in `sample_output.csv`. `grep -r 6645` finds only `account_6645` in unrelated places, and `5569` occurs only as `support_5569` in case_18.
   - evidence_94 logs audit-record reads only for user_42, 43 and 49, which are COMPLETE-type cases.
   - So INCOMPLETE cases in the readback families may need an audit_record id that cannot be derived. Expect to lose that step, or drop it.
   - The same happens for case_23/24/29/30, whose audit records appear only in the LATE evidence_02. The earlier note 07 reports the same for case_09 (only in LATE evidence_06).
3. **The account_service resource is often visible only in `system_activity`.**
   - case_18 `account_5521`, case_20 `account_5037` and case_22 `account_4990` appear in no evidence file. They appear only as `DELETE_RECORD deletion_worker->account_service ... "submitted primary profile account_X"`.
   - Linking rule, validated on samples 09..32:
     - The account-delete activity falls **45–75 min before `reported_at`**.
     - Its `reported_result` mirrors `reported_status`: COMPLETE→SUCCESS, NOT_STARTED→FAILED, PARTIALLY_COMPLETE→PARTIAL.
     - 29 of 31 sample cases fit both. The two exceptions are hand-crafted case_06 and case_08, which are PARTIALLY_COMPLETE→SUCCESS.
   - The time window alone usually leaves 2–3 candidate accounts. Adding the result filter and removing accounts that some evidence ties to another email resolves them. Example: in the 09-09T11:00 group, account_3610 is n.masuku60 (case_51) per evidence_94, so account_5521 (SUCCESS) goes to case_18 and account_5037 (FAILED) goes to case_20.
   - Within a group of cases with the same `reported_at`, the account deletes are spaced about 11 min apart. In 2 of 3 groups that order followed requested_at, but this is not reliable (the 09-09T12:00 group breaks it).
4. **Activity `event_type` tells you the policy action.** The deletion_worker row for each resource uses the remediation the policy needs:
   - `DELETE_RECORD`: search, support attachment, export, marketing-like analytics.
   - `REDACT_RECORD`: support message, tombstone.
   - `ANONYMIZE_RECORD`: analytics profile.
   - `CHECK_DATA_FLOW` ("remains enabled"): data flow.
   - `CHECK_RESTORE_ACCESS` ("can still be restored"): backup.

   The `reported_result` (SUCCESS/FAILED/PARTIAL) is only a claim and never decides the state. Examples:
   - case_16: search_1007 "SUCCESS", yet it is present in evidence_05.
   - case_13: account_9335 "FAILED", yet evidence_03 shows NOT_FOUND.
   - case_19: account_9102 "PARTIAL", yet evidence_01 shows 404.
5. **Timing pattern of deletion-worker rows relative to `reported_at`:**
   - Account delete: −45 to −75 min.
   - Already-successful policy actions (ANONYMIZE/REDACT/DISABLE/BLOCK SUCCESS): −7 to −30 min.
   - Failed actions and CHECK_* rows: +39 to +114 min.

   This lets you cluster activity rows per case even when the resource has no identifiers. For example, case_21's analytics_5335 is all-null in evidence_92 and is linked only by activity_3665 at −28 min.
6. **Ordering rule confirmed exactly.** All 32 samples match sort key `(phase, operation index in the problem's table, system_id, resource_id)`. There are 0 mismatches, and lexical vs numeric resource sort gives the same result because no sample has two resources tied on phase+op+system.
   - Deviation from the prose guidance: AGENTS.md says "process downstream copies before their source records". Gold ignores this. In case_16 it deletes `account_service account_994` (the source) **before** `search_service search_1007` (the downstream copy), because the sort is alphabetical.
   - The only dependency ordering that holds is the one built into the operation table: DISABLE_DATA_FLOW and BLOCK_RESTORE come before DELETE, REDACT and ANONYMIZE.
7. **Shape of an INCOMPLETE case:**
   - FINDINGs, each citing the proof file.
   - One REMEDIATION per finding, with `evidence_id ""`.
   - VERIFICATION steps, all with `""`: `VERIFY_RECORD_ABSENT account_service <acct>` **always**, `VERIFY_RECORD_PRESENT security_service <audit_record>` **always**, and one verify per remediated resource.
   - The account verify is present even when the account was already absent, as in case_13/14/15/17/18/19/20/22.
   - Already-compliant facts in an INCOMPLETE case get no evidence id. For example, evidence_03 proves account_9335 NOT_FOUND, yet the case_13 verify is `""`.
8. **Shape of a COMPLETE case (case_21):** VERIFICATION steps only, every one citing the proof file: account ABSENT, audit PRESENT, and one per already-treated resource (analytics ANONYMIZED, and so on).
9. **Earlier evidence for the same user belongs to an earlier case.** For user_17, evidence_67 (03-10: account_6523 404 by leonie's email) and activity_4011 / evidence_42 (tombstone_17) belong to eval **case_46** (audit 03-11). Sample case_17 (request 08-19) **excludes** them. Safe scope for a case is evidence with `reported_at <= captured_at <= audit_at`, and every sample citation satisfies it. The resource universe should also be limited to resources whose activity cluster or proof file belongs to this request.
10. **Legal hold (evidence_27) produces no steps.** It lists ORD-20264319 for user_17 and ORD-20264402 for user_21. Case_21 is still COMPLETE, with only 3 steps.

---

## 1. Identity resolution (cases 13–22)

All 10 request emails are **current** emails. None of these users has a historical email. user_15 and user_50 have only historical **phones**, and those phones appear nowhere in the evidence. `email_hash = sha256(lower(email))` (verified for noor-khalil@proton.me → d0a2e554…).

| case | email | user | name | phone (old) | hits outside proof file |
|---|---|---|---|---|---|
| 13 | noor-khalil@proton.me | user_33 | Noor Khalil | +971 54 271 5338 | none |
| 14 | y.tanaka32@gmail.com | user_37 | Yuki Tanaka | +81 90 0802 6399 | none |
| 15 | lucia-torres@gmail.com | user_15 | Lucía Torres | +34 715 351 235 (old +34 728 875 900) | evidence_14 PNG 08-07 (data_flow_9846 selector), pre-request |
| 16 | diya.k4436@outlook.com | user_53 | Diya Kapoor | +91 96023 32879 | none |
| 17 | leonie.g9352@outlook.com | user_17 | Léonie Girard | +33 6 50 56 17 06 | evidence_67 (03-10 account_6523), evidence_42 / activity_4011 tombstone_17, evidence_27 legal register |
| 18 | mori.ren@gmail.com | user_50 | Ren Mori | +81 90 6947 3342 (old +81 90 2367 3149) | none |
| 19 | e.varga90@yahoo.com | user_19 | Elena Varga | +48 625 215 867 | none |
| 20 | akosua.gyasi@gmail.com | user_48 | Akosua Gyasi | +233 24 014 4504 | none |
| 21 | amara-okeke@proton.me | user_21 | Amara Okeke | +234 803 344 7640 | evidence_02 (LATE, 09-17), evidence_27 legal register |
| 22 | seoyeon-han@gmail.com | user_51 | Seo-yeon Han | +82 10 8943 9310 | none |

Near-duplicate check (`near_dupes.py`): the only look-alikes are different people in other files. Examples are farah-khalil@proton.me (user_657), mei-tanaka@gmail.com (user_219), diya.n1256@outlook.com (user_833), and +234 803 344 0634, which is user_125's phone in evidence_12 and resembles Amara's +234 803 344 7640. None of them appear in the proof files for these cases, so there is no decoy trap here.

---

## 2. Per-case traces

Notation: `L<n>` is a line number in the file.

### case_13: noor-khalil@proton.me, NOT_STARTED, audit 10-01T12:00. Gold INCOMPLETE, 8 steps

Text: "close my account and process the associated personal-data deletion". This authorizes deletion.

Proof file: evidence_03, the handover TXT. Its format is `- ts | system | resource | DATA_CATEGORY | STATE | identifier`.
- L15 `account_service | account_9335 | USER_PROFILE | NOT_FOUND | noor-khalil@proton.me`: the account is already absent, so it gets a verify only.
- L27 `search_service | search_1308 | SEARCH_INDEX_ENTRY | FOUND | noor-khalil@proton.me`: rule_03 DELETE, so REPORT_REMAINING_RECORD → DELETE_RECORD → VERIFY_RECORD_ABSENT.
- L43 `support_platform | support_4218 | SUPPORT_ATTACHMENT | FOUND | noor-khalil@proton.me`: rule_06 (an attachment that belongs only to the subject) requires DELETE. So it is **REMAINING_RECORD + DELETE**, not EXPOSED_PII/REDACT. Compare evidence_03 L44–46, where `SUPPORT_MESSAGE | IDENTIFIABLE` rows for other users map to rule_05 REDACT.
- L34 `security_service | audit_record_4816 | SECURITY_AUDIT_LOG | FOUND | user_33`: rule_12 RETAIN, so VERIFY_RECORD_PRESENT. It is matched by the stable user_id, not by email.

Activity claims:
- activity_3739 account_9335 DELETE **FAILED**. This is false; the account is NOT_FOUND.
- activity_3752 support_4218 DELETE FAILED.
- activity_3756 search_1308 DELETE FAILED.

The event_type DELETE_RECORD on support_4218 confirms the attachment category.

The steps match gold exactly. Verify order is account ABSENT, search ABSENT, security PRESENT. support ABSENT is placed **before** security PRESENT because VERIFY_RECORD_ABSENT comes before VERIFY_RECORD_PRESENT in the table.

### case_14: y.tanaka32@gmail.com, COMPLETE, audit 10-01T12:00. Gold INCOMPLETE, 5 steps

Text (Japanese): "完全な削除を依頼します" means "I request complete deletion". This authorizes deletion.

Proof file: evidence_03.
- L9 account_3677 USER_PROFILE NOT_FOUND: absent, so it gets a verify only.
- L19 `backup_service | backup_3870 | BACKUP_ARCHIVE | ACTIVE | y.tanaka32@gmail.com`: a restore path is still open. rule_14 says RETAIN the archive but block restore, so REPORT_RESTORE_RISK ACTIVE → BLOCK_RESTORE → VERIFY_RESTORE_BLOCKED. The backup is **not deleted**.
- L41 audit_record_987 FOUND user_37: VERIFY_RECORD_PRESENT.

activity_3690 CHECK_RESTORE_ACCESS SUCCESS reads "confirmed that archive backup_3870 can still be restored", which agrees with the evidence. The reported status COMPLETE is wrong, because the restore risk makes the case INCOMPLETE. Contrast this with evidence_03 L20 `backup_706 | BACKUP_ARCHIVE | BLOCKED | user_39`, which is the compliant form.

### case_15: lucia-torres@gmail.com, COMPLETE, audit 09-15T12:00. Gold INCOMPLETE, 5 steps

Proof file: evidence_01 (log). Logs split a lookup across two lines that share a `trace_id`: the *started* line has the key, and the *completed* line has the resource_id. You must join on trace_id.
- L22 `resource_id=account_4745 event=profile_lookup_completed rows=0 http_status=404 correlation_key="lucia-torres@gmail.com"`: absent (inline-key variant).
- L85 `trace_id=tr-9750867 event=connector_config_read_started subject_key="lucia-torres@gmail.com"`, then L88 `tr-9750867 resource_id=data_flow_9846 event=connector_heartbeat enabled=true scheduler_registered=true last_run=success` (WARN): an **ACTIVE data flow**. So REPORT_ACTIVE_DATA_FLOW → DISABLE_DATA_FLOW → VERIFY_DATA_FLOW_DISABLED.
- L101 `tr-4314388 audit_record_query_started subject_ref="user_15"`, then L103 `resource_id=audit_record_1596 audit_record_read_completed integrity_check=passed rows=1`: PRESENT.

activity_3386 CHECK_DATA_FLOW reads "remains enabled". Excluded and not cited: evidence_14 (connector console PNG, 08-07) also shows data_flow_9846 with selector lucia-torres. It was captured **before requested_at (08-21)**, and gold cites the later evidence_01 instead.

### case_16: diya.k4436@outlook.com, NOT_STARTED, audit 09-21T10:00. Gold INCOMPLETE, 7 steps

Proof file: evidence_05 (SQL). It has tables `customer_data_primary` and `customer_data_read_replica` with columns (resource_id, origin_system, collection_name, record_json, updated_at).
- **Replication drift:** `account_994` is **missing from primary** but present in **read_replica** (L52): `{"customer_reference":"user_53","full_name":"Diya Kapoor","email":"diya.k4436@outlook.com","phone":"+91 96023 32879","account_status":"ACTIVE"}`. That gives REPORT_REMAINING_RECORD **account_service** account_994. The system_id comes from the `origin_system` column, not the replica name.
- `search_1007` is in both tables (L37, L75) with the email and display_name: REMAINING → DELETE.
- `audit_record_9528` (subject_reference user_53, `account_deletion_reviewed`): PRESENT.

Activity claims:
- activity_3571 account_994 DELETE FAILED.
- activity_3577 `SYNC_RECORD account_service->account_replication_cluster account_994 SUCCESS "final checkpoint"`. This hints that the replica copy was resynced.
- activity_3580 search_1007 DELETE **SUCCESS**, which is false.

Order: REMEDIATION deletes account_994 before search_1007 (alphabetical). See headline 6.

### case_17: leonie.g9352@outlook.com, NOT_STARTED, audit 09-15T12:00. Gold INCOMPLETE, 5 steps

Text: "You may retain backups if required, but they must not be able to restore my personal profile." This is exactly rule_14 (RETAIN plus block restore).

Proof file: evidence_01.
- L16 `tr-4708586 profile_lookup_started lookup_key="leonie.g9352@outlook.com"`, then L21 `account_4092 rows=0 http_status=404`: absent.
- L33 `audit_record_1797 audit_record_read_completed integrity_check=passed rows=1 correlation_key="user_17"`: PRESENT.
- L43 `tr-8210651 restore_policy_check_started subject_key="leonie.g9352@outlook.com"`, then L53 (ERROR) `backup_3245 event=restore_candidate_evaluated eligible=true deletion_block=false`: **restore risk**.

Activity: activity_3383 account_4092 DELETE FAILED (false; the account is 404). activity_3385 CHECK_RESTORE_ACCESS reads "can still be restored".

Excluded:
- evidence_67 (03-10, `account_6523` 404 by the same email).
- activity_4011 / evidence_42 `identity_service tombstone_17` (user_17).
- evidence_27 ORD-20264319 legal hold.

All three belong to eval case_46 (audit 03-11) or to the legal-hold no-op. A different account id (6523 vs 4092) for the same user shows that each request has its own resource universe.

### case_18: mori.ren@gmail.com, COMPLETE, audit 09-26T11:00. Gold INCOMPLETE, 14 steps

Proof file: evidence_94 (readback log). Each record has a started/completed pair with the same `trace_id`, and the completed line carries the field values.
- L10/11 `support_5569 support_ticket_read_completed customer_reference=null requester_name=null requester_email=mori.ren@gmail.com requester_phone=null`. This is a support **ticket/message**, so rule_05 applies: REDACT. That gives **REPORT_EXPOSED_PII → REDACT_RECORD → VERIFY_RECORD_REDACTED**.
- L22/23 `analytics_037 analytics_profile_read_completed email=mori.ren@gmail.com audience_cohort=general_shopper`: an analytics profile still attributable to the user, so rule_07 applies: ANONYMIZE. That gives **REPORT_EXPOSED_PII → ANONYMIZE_RECORD → VERIFY_RECORD_ANONYMIZED**. One remaining identifier is enough.
- L24/25 `data_flow_4890 connector_config_read_completed enabled=true last_delivery_status=delivered connector_name=analytics_identity_bridge customer_email=mori.ren@gmail.com`: ACTIVE flow.
- L52/53 `search_4013 index_query_completed result=hit total_hits=1 email=mori.ren@gmail.com`: REMAINING.

Not in any evidence:
- `account_5521`: only activity_3732 (DELETE SUCCESS, −68 min). It is assigned to this case by elimination (headline 3).
- `audit_record_6645`: in **no participant file at all**.

Activity event types (3744 REDACT, 3747 DELETE, 3751 ANONYMIZE, 3753 CHECK_DATA_FLOW) match the gold remediation ops one-to-one.

Order:
- FINDING: REMAINING(search), EXPOSED(analytics, then support), ACTIVE_FLOW.
- REMEDIATION: DISABLE, DELETE, REDACT, ANONYMIZE.
- VERIFY: ABSENT(account, search), PRESENT(security), REDACTED(support), ANONYMIZED(analytics), DISABLED(flow).

### case_19: e.varga90@yahoo.com, PARTIALLY_COMPLETE, audit 09-15T12:00. Gold INCOMPLETE, 8 steps

Text: "clean my personal details out of earlier support conversations… the conversation itself may need to stay". This is a hint for rule_05 (REDACT, not delete).

Proof file: evidence_01.
- L11 `tr-8896806 message_scan_started subject_key="e.varga90@yahoo.com"`, then L15 (WARN) `support_9553 event=message_pii_scan matched_value="e.varga90@yahoo.com" detector=direct_identifier`. A **message** scan gives rule_05 REDACT, so EXPOSED_PII. Compare L25 `support_9538 event=attachment_pii_scan file=delivery_confirmation_32.pdf`, where an **attachment** scan gives rule_06 DELETE / REMAINING (another user, case_34).
- L36 `search_6083 index_query_completed result=hit correlation_key="e.varga90@yahoo.com"`: REMAINING.
- L37 → L44 `audit_record_6793` (subject_ref user_19): PRESENT.
- L70 → L72 `account_9102 rows=0 http_status=404`: absent.

Activity: activity_3323 account DELETE PARTIAL (a claim), activity_3329 REDACT FAILED, activity_3332 DELETE FAILED.

### case_20: akosua.gyasi@gmail.com, NOT_STARTED, audit 09-26T11:00. Gold INCOMPLETE, 8 steps

Proof file: evidence_94.
- L8/9 `search_4262 result=hit email=akosua.gyasi@gmail.com`: REMAINING.
- L40/41 `data_flow_1770 enabled=true last_delivery_status=delivered connector_name=customer_events_connector customer_email=akosua.gyasi@gmail.com`: ACTIVE.

Not in evidence:
- `account_5037`: only activity_3734 (DELETE FAILED, −45 min).
- `audit_record_5569`: in no participant file. Do not confuse it with `support_5569` of case_18.

Remediation order: DISABLE data_flow_1770 first, then DELETE search_4262. Verify order: account ABSENT, search ABSENT, security PRESENT, flow DISABLED.

### case_21: amara-okeke@proton.me, COMPLETE, audit 09-15T12:00. Gold COMPLETE, 3 steps, all citing evidence_92

Proof file: evidence_92 (service export JSON, `service_exports.<system>.<collection>[]`).
- `account_service.profile_lookups`: `{"resource_id":"account_6440","status_code":404,"profile":null}`. ABSENT. There is no identifier in the row, so the link comes from activity_3661 (DELETE SUCCESS at −58 min).
- `security_service.audit_records`: `{"resource_id":"audit_record_3737","subject_reference":"user_21","event_code":"IDENTITY_CHANGE_RECORDED","retention_until":"2034-09-30T23:59:59Z"}`. Within retention, so rule_12 RETAIN and VERIFY_RECORD_PRESENT.
- `analytics_platform.profiles`: `{"resource_id":"analytics_5335", customer_reference/email/phone/email_hash all null}`. Already anonymized, so VERIFY_RECORD_ANONYMIZED. The link is only via activity_3665 `ANONYMIZE_RECORD SUCCESS "Policy action completed"` at −28 min.

Not cited: evidence_02 (snapshot bundle, captured 09-17, **after** audit) also shows analytics_5335 and audit_record_3737. evidence_01 (11:59:39) has nothing for user_21. The legal-hold order ORD-20264402 (evidence_27) gives no step.

Note that the account was not in the request's "found" list, yet a VERIFY_RECORD_ABSENT for it is required.

### case_22: seoyeon-han@gmail.com, COMPLETE, audit 09-21T10:00. Gold INCOMPLETE, 8 steps

Proof file: evidence_05.
- `analytics_4440` (primary L17 and replica L55): `user_id user_51, email, phone, email_hash` all still populated. rule_07 gives ANONYMIZE: EXPOSED_PII → ANONYMIZE_RECORD → VERIFY_RECORD_ANONYMIZED. Contrast this with analytics_2572/8858/9069, whose user_id/email/phone/hash are null; those are compliant rows for other cases.
- `search_8911` (L41, L79) display_name "Seo-yeon Han", email: REMAINING → DELETE.
- `audit_record_3482` (subject_reference user_51): PRESENT.
- `account_4990` is **absent from both tables**. That proves absence by omission. The id comes from activity_3573 (DELETE SUCCESS at −48 min).

Activity: activity_3578 ANONYMIZE FAILED, activity_3581 DELETE FAILED.

---

## 3. Answers to the specific questions

- **Why evidence_03/05/01/94/92 is cited.** It is the single batch capture, at or before audit_at, that holds the case's resources. It is the latest admissible observation, and every gold step of the case cites that same id. Earlier files that show the same resource, such as evidence_14 for data_flow_9846, are not used. Files captured later, such as evidence_02, are never cited.
- **Analytics: EXPOSED_PII→ANONYMIZE vs REMAINING→DELETE.**
  - ANALYTICS_PROFILE (rule_07) is ANONYMIZE whenever any direct identifier remains (email, phone, user_id or hash), as in analytics_4440 and analytics_037. Under the operation table, ANONYMIZE/REDACT targets are reported as `REPORT_EXPOSED_PII`, and DELETE targets as `REPORT_REMAINING_RECORD`.
  - Sample case_12 analytics_9914 is a *marketing contact* (`contact_lookup_completed email_opt_in=true`, keyed by the old email hash). That is rule_10 MARKETING_PROFILE, so DELETE and REMAINING. The deletion_worker row type (DELETE_RECORD vs ANONYMIZE_RECORD) confirms this.
  - An analytics row with all identifiers null is compliant. It gets VERIFY_RECORD_ANONYMIZED, and only in COMPLETE cases.
- **Support: REDACT (rule_05) vs DELETE (rule_06).**
  - Message or ticket content gives REDACT and EXPOSED_PII. Signals: `SUPPORT_MESSAGE` in evidence_03, `message_pii_scan` in evidence_01, `support_ticket_read_completed requester_email=` in evidence_94, `message_text` in SQL, `tickets.message_excerpt` in evidence_92.
  - An attachment owned only by the subject gives DELETE and REMAINING. Signals: `SUPPORT_ATTACHMENT` in evidence_03, `attachment_pii_scan file=*.pdf` in evidence_01.
  - Activity event_type REDACT_RECORD vs DELETE_RECORD confirms the category.
  - A compliant redacted message looks like `customer_reference=user_X` with requester fields null, or `"message_text":"[REDACTED]"`, or `SUPPORT_MESSAGE | REDACTED | user_X`.
- **Data flow ACTIVE detection:**
  - evidence_01: `connector_heartbeat enabled=true scheduler_registered=true`.
  - evidence_94/92: `enabled=true last_delivery_status=delivered`.
  - evidence_03: `DATA_FLOW | ACTIVE`.
  - SQL: `"enabled":true,"mode":"continuous_sync","subject_selector":<email>`.
  - The flow is linked to the user by the subject key or selector email. The disabled form is `enabled=false last_delivery_status=stopped customer_reference=user_X` (compliant).
  - Corroborating activity: `CHECK_DATA_FLOW … remains enabled`. Recreation evidence: `SYNC_RECORD integration_service->search_service data_flow_2528 "Active connector repopulated downstream resource search_1934"` (activity_3755, eval case_37).
- **Backup restore risk:**
  - evidence_01: `restore_candidate_evaluated eligible=true deletion_block=false` (ERROR level).
  - evidence_03: `BACKUP_ARCHIVE | ACTIVE`.
  - SQL: `"restore_allowed":true`.
  - The compliant form is `restore_allowed=false` or `BLOCKED`.
  - Corroborating activity: `CHECK_RESTORE_ACCESS … can still be restored`. The remediation is BLOCK_RESTORE, never DELETE (rule_14 RETAIN).
- **Security audit_record PRESENT:**
  - It is matched by **user_id / subject_reference** and never by email: evidence_01 `subject_ref="user_X"`/`correlation_key="user_X"` plus `audit_record_read_completed integrity_check=passed rows=1`; evidence_03 `SECURITY_AUDIT_LOG | FOUND | user_X`; SQL `security_audit_events.subject_reference`; evidence_92/94 `retention_until` (2031–2034, all after audit).
  - It appears exactly once per case in every generated sample case, as VERIFY_RECORD_PRESENT. Hand-crafted cases 01–08 and 10 lack it (see note 07).
  - It can be unobservable (case_18, case_20).
- **Excluded items:**
  - Earlier-case resources for the same user (case_17: account_6523, tombstone_17).
  - Pre-request duplicate observations (evidence_14).
  - Post-audit files (evidence_02 for case_21).
  - Legal-hold orders (evidence_27).
  - Records of other users in the same batch file (all of evidence_03, 05 and 94 are multi-case batches).
  - Look-alike emails of different users.

---

## 4. Candidate general algorithm

1. **Intent.** Classify request_text as deletion or not; otherwise return `NOT_APPLICABLE, []`. See 06_requests_text.md.
2. **Identity.** Match the request email case-insensitively against current emails and audit-log historical emails to get the user_id. Collect all current and historical emails, phones and names, plus sha256 hashes of every email.
3. **Admissible window.** Use evidence with `captured_at <= audit_at` (inclusive), preferably `>= reported_at`. Use activity with `event_time <= audit_at`.
4. **Resource universe.**
   - (a) Search every admissible file for identifiers and join log lines on `trace_id`. Started lines carry the key, completed lines carry the resource_id and state. Some lines put `correlation_key` inline.
   - (b) Take deletion_worker activity rows in the case's time cluster around `reported_at` (account delete at −75..−45 min with result matching reported_status; other actions at −30..+115 min). Then resolve which case each row belongs to by elimination against evidence-linked resources of the other cases in the same `reported_at` group.
   - (c) Always include the `account_service` resource and the `security_service` audit_record.
5. **State at audit.** For each resource, take its state from the latest admissible observation; claims from activity_result are ignored. If any replica table shows the account (primary-vs-replica drift), the account is PRESENT.
6. **Policy.** Map the data category from the evidence wording or the activity event_type, using rules 01–15. Then derive the treatment:
   - DELETE + present → REMAINING / DELETE / VERIFY_ABSENT.
   - REDACT/ANONYMIZE + identifiers present → EXPOSED_PII / REDACT|ANONYMIZE / VERIFY_REDACTED|ANONYMIZED.
   - Flow enabled → ACTIVE_FLOW / DISABLE / VERIFY_DISABLED.
   - Restore allowed → RESTORE_RISK / BLOCK / VERIFY_BLOCKED.
   - Security audit → VERIFY_PRESENT.
   - Legal hold → no step.
7. **Status.** INCOMPLETE if there is any finding, otherwise COMPLETE. reported_status is ignored, except as the tie-breaker in 4(b).
8. **Emit the steps.**
   - INCOMPLETE: findings citing the proof file; remediations and verifications with `""`. Verifications = account ABSENT + audit PRESENT + one per remediated resource.
   - COMPLETE: verifications for account, audit and every compliant treated resource, each citing the proof file.
   - Sort by (phase, operation-table index, system_id, resource_id) and renumber from 1.
