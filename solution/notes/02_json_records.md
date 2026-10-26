# 02 — `dataset/evidence/records/` (28 JSON + 1 TXT) — reverse-engineering notes

Scope: every file in `dataset/evidence/records/`. Helper artefacts (all in `solution/notes/`):

* `records_normalize.py` → `records_observations.tsv` (934 flat observations: file_id, file captured_at, per-entry time, system, collection, resource_id, category, normalized state, identifiers, matched user_ids, unmatched identifiers).
* `records_case_view.py` → `records_case_view.txt` (242 sample+eval cases touched by these files; each observation tagged `CITABLE` (file captured_at <= audit_at AND entry time <= audit_at) or `LATER`).

Run: `python3 -I solution/notes/records_normalize.py && python3 -I solution/notes/records_case_view.py`

---

## 0. Ten headline findings

1. **Each file covers one cohort of 10 consecutive users.** A cohort is 10 consecutive cases sharing one `audit_at`. In the eval set, case_N usually maps to user_(N-2). Each cohort has exactly one primary evidence file captured 0–60 min before (or exactly at) the cohort's `audit_at`. Records files are either the primary file or a later mirror (table in section 1).
2. **Snapshot bundles (`customer_data_snapshot_bundle_*`) are mostly post-audit mirrors.** Their file `captured_at` is 2 days after the cohort's audit, but their main inner snapshot is stamped exactly at `audit_at`. Sample proof: for cohort users 21–30 (audit 2026-09-15T12:00), gold always cites `evidence_92` (service export, 11:44:55) and never `evidence_02` (bundle captured 09-17). The only bundles citable for their own cohort are `evidence_45` (captured == audit 02-23T10:00, users 471–480) and `evidence_51` (== audit 09-15T12:00, cases 31/32).
3. **Each bundle is built from the same template of traps:**
   * one *older* account snapshot (before audit, `ACTIVE`; a stale "old report");
   * the main snapshot at `audit_at`;
   * one *later* snapshot after audit (account re-created / search entry re-indexed);
   * one *decoy* search document with a `.jr` look-alike email and no `display_name` or `customer_reference`;
   * sometimes an `operational_record_history` sub-collection for a second cohort, with its own older and later entries.
4. **Linking tell in service exports.**
   * Compliant records (security audit, blocked backup, disabled connector, redacted ticket) carry `customer_reference`/`subject_reference = user_XX`.
   * Violating records carry the subject's email (current OR historical). A record never has both.
   * 404 accounts and anonymized analytics carry no identifier at all.
5. **In every service export a security `audit_record` is listed only for users with zero violations** (the COMPLETE cases). Each such user also has exactly one unlinked 404 account in the same file (counts match in all 11 exports). Users with violations have no audit record in the export. Gold still needs their audit_record id for `VERIFY_RECORD_PRESENT`; for the 09-15 cohort those ids (4128, 7095, 3954, 1707) appear only in the later `evidence_02`. So later files may be used to **enumerate** resource ids for future-verification steps (evidence_id ""), never to set state or to cite.
6. **Unlinked 404 accounts and anonymized analytics are resolved by activity.** Take each resource's `system_activity` event inside some case's [requested_at, reported_at], and keep only "clean" users.
   * This always gives either a unique match or a group of equal size (no mismatches in any export).
   * Equal groups: sort resource numbers ascending and match them to ascending case/user numbers. This reproduces all 10 gold links for evidence_92: 3136→25, 5684→26, 3866→27, 5482→28, 6440→21, 1895→25, 4566→26, 4574→27, 6077→28, 5335→21. It also agrees with a bundle-only link (account_2420→user_421).
7. **Attachment vs message is invisible in service exports.** `support_platform.tickets` looks the same for SUPPORT_MESSAGE (REDACT) and SUPPORT_ATTACHMENT (DELETE). Two signals separate them:
   * the bundles' `ticket_attachments` collection;
   * the activity `event_type` for that resource: `DELETE_RECORD` means attachment, `REDACT_RECORD` means message. This held for all 8 known attachments, plus support_9474 / 6560 / 5750, which are attachments the exports show only as tickets.
8. **`reported_result` in activity is noise.** Examples: USER_PROFILE ABSENT with result FAILED (21 rows); PRESENT with SUCCESS (12+); search PRESENT with SUCCESS (16). Use the evidence state only. The activity *event_type* is still useful as a category hint.
9. **Per-entry times can exceed the file time.**
   * `connector_configurations_20260812` (captured 08-12T09:00) has account_1417 FOUND at **08-14**.
   * `customer_export_manifest_20260409` (captured 04-09T12:00) has account_5043 FOUND at **04-11**.
   * Both are after `audit_at` → ignore them (the account is NOT_FOUND at audit).
   * The same files have stale earlier entries, e.g. account_7618 FOUND 04-03 then NOT_FOUND 04-09. Take the latest entry at or before audit.
10. **Pure decoy files and users.**
    * `security_audit_ledger_20261001` (evidence_50) covers the 10 NOT_APPLICABLE cases 533–542: phone change, marketing opt-out, export, login help, name fix, "remove me from marketing lists only", info request, invoices, email change, copy request. Every account is FOUND; that is correct and must not trigger INCOMPLETE. The file is captured after audit for 534–542 anyway.
    * user_31 (handover), user_824 (analytics_824) and user_843 (export_843) have no request.
    * user_22 (`evidence_02`: search_2912, audit_record_9644, support_1034) belongs to case_53, whose audit is 2026-05-25, so all of it is later.

---

## 1. File inventory, cohorts and timing role

`cap` = manifest `captured_at`. "Primary" = citable for that cohort.

| file_id | file | cap | cohort users → cases (audit_at) | role |
|---|---|---|---|---|
| evidence_62 | service_resource_export_20260129_114459 | 01-29 11:44:59 | 521–530 → case_523–532 (01-29 12:00) | PRIMARY |
| evidence_49 | snapshot_bundle_20260131 | 01-31 15:00 | same 521–530 | later mirror (main snap 01-29 12:00) |
| evidence_45 | snapshot_bundle_20260223 | 02-23 10:00 | 471–480 → 473–482 (02-23 10:00) **+** 481–490 → 483–492 (02-18 09:00, via `operational_record_history@backup_restore_service`) | PRIMARY for 471–480 (cap == audit); later for 481–490 (that cohort's primary = evidence_64 log 02-18 08:39) |
| evidence_65 | service_resource_export_20260228_103637 | 02-28 10:36:37 | 461–470 → 463–472 (02-28 11:00) | PRIMARY (no bundle mirror) |
| evidence_68 | service_resource_export_20260320_072349 | 03-20 07:23:49 | 421–430 → 423–432 (03-20 08:00) | PRIMARY |
| evidence_40 | snapshot_bundle_20260322 | 03-22 08:00 | same 421–430 | later mirror |
| evidence_36 | customer_export_manifest_20260409 | 04-09 12:00 | 381–390 → 383–392 (04-09 12:00) | PRIMARY (cap == audit) |
| evidence_35 | snapshot_bundle_20260416 | 04-16 06:00 | 371–380 → 373–382 (04-14 06:00) | later (primary = evidence_70 log 04-14 05:40) |
| evidence_71 | service_resource_export_20260429_083222 | 04-29 08:32:22 | 341–350 → 343–352 (04-29 09:00) | PRIMARY |
| evidence_31 | snapshot_bundle_20260511 | 05-11 11:00 | 321–330 → 323–332 (05-09 11:00) **+** 331–340 → 333–342 (05-04 10:00, `operational_record_history@support_storage_service`) | later for both (primaries evidence_73 log 05-09 10:43, evidence_72 sql 05-04 09:41) |
| evidence_74 | service_resource_export_20260514_114454 | 05-14 11:44:54 | 311–320 → 313–322 (05-14 12:00) | PRIMARY |
| evidence_77 | service_resource_export_20260603_083457 | 06-03 08:34:57 | 271–280 → 273–282 (06-03 09:00) | PRIMARY |
| evidence_26 | snapshot_bundle_20260605 | 06-05 12:00 | same 271–280 | later mirror |
| evidence_80 | service_resource_export_20260628_062556 | 06-28 06:25:56 | 221–230 → 223–232 (06-28 07:00) | PRIMARY |
| evidence_22 | snapshot_bundle_20260630 | 06-30 07:00 | 221–230 **+** 231–240 → 233–242 (06-23 06:00, `operational_record_history@privacy_treatment_service`) | later for both (231–240 primary = evidence_79 log 06-23 05:37) |
| evidence_83 | service_resource_export_20260718_104335 | 07-18 10:43:35 | 181–190 → 183–192 (07-18 11:00) | PRIMARY |
| evidence_17 | snapshot_bundle_20260725 | 07-25 15:00 | 171–180 → 173–182 (07-23 12:00) | later (primary = evidence_84 sql 07-23 11:43) |
| evidence_86 | service_resource_export_20260807_074104 | 08-07 07:41:04 | 141–150 → 143–152 (08-07 08:00) | PRIMARY |
| evidence_13 | connector_configurations_20260812 | 08-12 09:00 | 131–140 → 133–142 (08-12 09:00) | PRIMARY (cap == audit) |
| evidence_12 | snapshot_bundle_20260819 | 08-19 10:00 | 121–130 → 123–132 (08-17 10:00) | later (primary = evidence_87 sql 08-17 09:42) |
| evidence_89 | service_resource_export_20260901_053316 | 09-01 05:33:16 | 91–100 → 93–102 (09-01 06:00) | PRIMARY |
| evidence_56 | customer_analytics_report_20260907 | 09-07 09:45 | sample case_04 only (audit 09-07 10:20) | PRIMARY for case_04; analytics_824 is a decoy |
| evidence_07 | snapshot_bundle_20260913 | 09-13 08:00 | 71–80 → 73–82 (09-11 08:00) | later (primary = evidence_91 log 09-11 07:42) |
| evidence_59 | customer_export_jobs_20260914 | 09-14 15:40 | sample case_08 (audit 09-14 16:10) | PRIMARY; export_843 decoy |
| evidence_92 | service_resource_export_20260915_114455 | 09-15 11:44:55 | 21,23–30 → sample case_21,23–30 (09-15 12:00) | PRIMARY (gold-confirmed) |
| evidence_51 | snapshot_bundle_20260915 | 09-15 12:00 | user_541/542 → case_31/32 (09-15 12:00) | PRIMARY (gold-confirmed) |
| evidence_02 | snapshot_bundle_20260917 | 09-17 12:00 | 21–30 (+user_22 = case_53) | later mirror (gold never cites it) |
| evidence_03 | customer_account_handover_20261001.txt | 10-01 12:00 | 31–40 → case_11,13,36,37,38,14,40,41,42 (10-01 12:00); user_31 has no case | PRIMARY (gold-confirmed) |
| evidence_50 | security_audit_ledger_20261001 | 10-01 12:00 | 531–540 → case_533–542 (audit 10-01 … 09-22, one per day) | PRIMARY only for case_533; later for 534–542; all NOT_APPLICABLE |

Coverage: these files touch 242 cases (sample + eval).

* 152 cases have a citable records file.
* 90 cases see records only in later mirrors: evidence_07/12/17/31/35/45(481–490)/22(231–240)/50(534–542)/02(case_53). Their real proof is a log or SQL file captured just before the audit.

---

## 2. Schemas and state decoding, by family

### 2.1 `service_resource_export_*` (11 files, evidence_62…92; `source=records_assurance_gateway`, `region=global`)

Top level: `{exported_at, region, service_exports:{<system>:{<list>:[...]}}, source}`. Every entry has `observed_at <= exported_at`, and `exported_at` is 15–35 min before the cohort `audit_at`, so there is no per-entry timing trap.

| system.list | fields | state rule | link field |
|---|---|---|---|
| `account_service.profile_lookups` | resource_id, status_code, profile{customer_reference,email,email_hash,full_name,phone}, observed_at | 404 + `profile:null` → **ABSENT** (37 rows, no identifiers). 200 → **PRESENT** (10 rows; profile partly nulled, only `email` set, e.g. account_5334 keiko) → REPORT_REMAINING_RECORD/DELETE | `profile.email` (current or old) |
| `analytics_platform.profiles` | audience_cohort, customer_reference, email, email_hash, phone | all null → **ANONYMIZED** (32). `email` set → **IDENTIFIABLE** (16) → REPORT_EXPOSED_PII/ANONYMIZE | email only |
| `backup_service.restore_entries` | archive_key, customer_email, customer_reference, restore_allowed | `false` → **BLOCKED** (11, always via customer_reference). `true` → **ACTIVE** → REPORT_RESTORE_RISK/BLOCK_RESTORE (6, always via customer_email) | |
| `export_service.exports` | customer_reference, object_key, owner_email, owner_phone | listed → **PRESENT** (9, always via owner_email) → REMAINING/DELETE | owner_email |
| `integration_service.connectors` | connector_name ∈ {analytics_identity_bridge, customer_events_connector, search_profile_indexer, support_profile_sync}, customer_email, customer_reference, enabled, last_delivery_status | `enabled:true, delivered` → **ACTIVE** (24, via email) → REPORT_ACTIVE_DATA_FLOW/DISABLE. `enabled:false, stopped` → **DISABLED** (11, via user ref) | |
| `search_service.index_queries` | query, hits{total, documents[{customer_reference,display_name,email,email_hash,phone,resource_id}]}, resource_id | in all 58 rows `total=1`, the doc email equals the query and doc id equals the row id → **PRESENT** → REMAINING/DELETE. No `total:0` rows exist. | query / doc email |
| `security_service.audit_records` | event_code ∈ {ACCOUNT_DELETION_RECORDED, IDENTITY_CHANGE_RECORDED, PRIVACY_REQUEST_ACCEPTED, SUBJECT_REQUEST_AUDITED}, retention_until (2031–2034, never expired), subject_reference | **PRESENT/retain** → VERIFY_RECORD_PRESENT (rule_12) | subject_reference user_XX |
| `support_platform.tickets` | customer_reference, message_excerpt (generic: "account access", "order update", "delivery query", "correct delivery details"), requester_email/name/phone | requester_email set → **IDENTIFIABLE** (REDACT if message, DELETE if attachment, see 0.7). All requester_* null + customer_reference → **REDACTED** | requester_email or user ref |

Uppercase emails appear (e.g. `CARTER.AMELIA92@GMAIL.COM` support_5716 in evidence_86), so match case-insensitively. 60 of the 215 email identifiers in exports are historical emails from `user_audit_log.csv`.

### 2.2 `customer_data_snapshot_bundle_*` (13 files; `source=records_assurance_service`)

Top level: `{exported_at, source, snapshots:[{captured_at, data_store, collection, records:[...]}]}`. **Per-snapshot `captured_at` differs inside one file** (older / at-audit / later layers).

| data_store / collection | fields | state |
|---|---|---|
| account_service / customer_profiles | resource_id, customer_reference, full_name, email, phone, account_status (always ACTIVE), signup_channel | listed → PRESENT. **Empty `records:[]` → proof that the profile is ABSENT** (evidence_51 for case_31 account_4857; also evidence_31 05-09 and evidence_07 09-11) |
| analytics_platform / customer_analytics_reports | user_id, email, phone, email_hash, reporting_window=last_90_days, metrics{sessions_30d, products_viewed_30d, orders_completed_90d, revenue_90d_usd}, recent_activity[] | all 4 PII null → ANONYMIZED (34). All 4 set (current identifiers) → IDENTIFIABLE (18). The metrics/products are not linking keys. |
| backup_service / backup_catalog | archive_path s3://customer-backups/weekly/segment-NN.tar.zst, subject_reference, restore_allowed, encryption AES-256 | restore_allowed true → ACTIVE (subject_reference = email); false → BLOCKED (user ref) |
| export_service / customer_export_jobs | owner_email, file_name, created_at, expires_at, download_available (always true here), included_sections | PRESENT |
| integration_service / connector_configurations | connector_name customer-events-to-warehouse-N, destination customer_analytics_warehouse, subject_selector, enabled, mode continuous_sync | enabled → ACTIVE (selector = email); else DISABLED (selector = user_XX) |
| search_service / customer_search_documents | index_name customer_directory_v3, document{display_name,email,customer_reference} | PRESENT. A genuine doc has all three fields set. **A decoy doc has email only (a `.jr` variant).** |
| security_service / security_audit_events | subject_reference, event_name=account_deletion_reviewed, actor_type=automated_privacy_workflow, integrity_seal sha256:000…hex | retain → PRESENT. **Lists all 10 cohort users**, unlike exports. |
| support_platform / support_conversations | ticket_id CS-####, subject_reference, channel email, message_text | `"[REDACTED]"` → REDACTED. "Please send the delivery update to <email>. The affected order includes: <product>." → IDENTIFIABLE (email may be old) |
| support_platform / ticket_attachments | ticket_id, file_name delivery_confirmation_NN.pdf, uploaded_by (email), storage_class ticket_attachment | SUPPORT_ATTACHMENT PRESENT → REMAINING/DELETE (rule_06). IDs: support_3896, 3615, 3684, 5830, 4665, 2283, 2315 |
| legal_service / retained_order_records | order_reference ORD-2026####, retention_reason payment_dispute_and_tax_record, retained_until 2033-12-31 | LEGAL_HOLD_RECORD → retain (rule_13) → VERIFY_RECORD_PRESENT. legal_hold_4743 (user_471), legal_hold_438 (user_430) |
| identity_service / deleted_customer_references (evidence_51 only) | subject_reference, name, email, phone, email_hash, account_status=DELETED | all PII null → tombstone REDACTED (tombstone_440). PII present → EXPOSED_PII → REDACT (tombstone_9178) |
| `<x>_service` / operational_record_history (evidence_45, 31, 22) | flat rows {recorded_at, system, resource_id, record_type, result, lookup_value} | same vocabulary as 2.3 |

### 2.3 Flat ledgers: `connector_configurations_20260812` (evidence_13), `customer_export_manifest_20260409` (evidence_36), `security_audit_ledger_20261001` (evidence_50), and the operational_record_history inside bundles

The file names are misleading: `connector_configurations` is a generic ledger, not just connectors. Shape: `{exported_at, origin, record_count, records:[{recorded_at, system, resource_id, record_type, result, subject_reference|lookup_value}]}`.

* `record_type` gives the policy data_category directly: USER_PROFILE, ANALYTICS_PROFILE, BACKUP_ARCHIVE, USER_EXPORT, DATA_FLOW, SEARCH_INDEX_ENTRY, SECURITY_AUDIT_LOG, SUPPORT_MESSAGE, LEGAL_HOLD_RECORD (legal_hold_8049).
* `result` mapping: FOUND→PRESENT, NOT_FOUND→ABSENT, IDENTIFIABLE→exposed PII, ANONYMIZED, ACTIVE (flow running or restore allowed), DISABLED, BLOCKED, REDACTED.
* Subject keys:
  * NOT_FOUND accounts **do** carry the email, unlike export 404s.
  * Anonymized analytics have `subject_reference:""`.
  * Compliant items (security, BLOCKED, DISABLED, REDACTED, legal) carry `user_XX`.
  * Violations carry an email (historical in 9 of 67, uppercase `LDAHL9787@FASTMAIL.COM`).
* Multiple entries can exist for the same resource at different times, so pick the latest with recorded_at <= audit_at:
  * account_7618: FOUND 04-03, then NOT_FOUND 04-09 (stale-positive trap).
  * account_5043: NOT_FOUND 04-09, then FOUND 04-11 (after audit; ignore).
  * account_1417: NOT_FOUND 08-12, then FOUND 08-14 (after audit; ignore).

### 2.4 `customer_account_handover_20261001.txt` (evidence_03)

The header "CUSTOMER PLATFORM - SHIFT HANDOVER / Snapshot: 2026-10-01T12:00:00Z" is followed by 41 lines like `- <ts> | <system> | <resource_id> | <DATA_CATEGORY> | <RESULT> | <identifier>`.

* Regex: `- (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (.*)`.
* Identifier is an email (mixed case: `CHOI.JIHOON94@GMAIL.COM` and `SIPHO.MOKOENA@GMAIL.COM` are uppercase), a `user_XX`, or `no direct identifier` (anonymized analytics).
* Category column distinguishes `SUPPORT_ATTACHMENT` (support_4218) from `SUPPORT_MESSAGE`.
* Historical emails used: choi.jihoon94 (user_38), lucas-souza95 (user_39), abena.o189491 (user_35, the *oldest* of two successive changes).

### 2.5 `customer_analytics_report_20260907` (evidence_56) and `customer_export_jobs_20260914` (evidence_59)

Shape: `{captured_at, source, collection, records}`. The source names differ: `analytics_identity_store`, `user_export_store`. The system_id to emit is still `analytics_platform` / `export_service`.

* evidence_56:
  * analytics_901: all PII null → ANONYMIZED. This is case_04's gold VERIFY_RECORD_ANONYMIZED. The link exists only via activity_3463 ANONYMIZE analytics_901 at 08-27T08:47, inside case_04's window 08-25T12:32..08-27T08:54.
  * analytics_824 (user_824 Freja Dahl, current identifiers, no request) is a decoy.
* evidence_59:
  * export_001 (gabriel.costa, download_available true, expires 10-04) → case_08 finding.
  * export_843 (user_843 Aoi Tanaka, download_available false, expired 06-10, no request) is a decoy.

---

## 3. Gold cross-check: exact proving entries

**evidence_92 (cases 21, 23–30; audit 09-15T12:00; file 11:44:55)**

| case | gold step | proving entry in evidence_92 |
|---|---|---|
| 21 COMPLETE | VERIFY_ABSENT account_6440 | profile_lookups `{account_6440, status_code 404, profile null, observed 09:31:19}` |
| | VERIFY_PRESENT audit_record_3737 | audit_records `{subject_reference user_21, IDENTITY_CHANGE_RECORDED, retention_until 2034-09-30}` |
| | VERIFY_ANONYMIZED analytics_5335 | profiles `{analytics_5335, all PII null, returning_customer}` |
| 23 INCOMPLETE | REMAINING export_7364 | exports `{owner_email thandiwe.m6866@zoho.com}` |
| | REMAINING search_898 | index_queries query thandiwe.m6866 total 1 |
| | verify audit_record_4128 (evidence "") | id only in evidence_02 (later) |
| 24 INCOMPLETE | REMAINING account_5334 | `{status_code 200, profile.email keiko.nakamura@gmail.com, other fields null}`. A partially blanked profile is still PRESENT. |
| | REMAINING search_5577 | query keiko.nakamura |
| 25 COMPLETE | account_3136 404 / audit_record_451 (user_25, ACCOUNT_DELETION_RECORDED) / analytics_1895 null | "privacy page says failed" + activity_3597 FAILED: a reported failure that the evidence overrides |
| 26 COMPLETE | account_5684 404, audit_record_5416 (user_26), support_4715 (user_26, requester_* null), analytics_4566 null, data_flow_6244 (user_26, enabled false), backup_3120 (user_26, restore_allowed false) | trap: evidence_02 has account_5684 ACTIVE at **09-09** (the "old report") |
| 27 COMPLETE | account_3866 404, audit_record_3830, support_4707, analytics_4574, data_flow_2295, backup_5970 | trap: evidence_02 has account_3866 ACTIVE at **09-17** (after audit; "as it stood when reviewed") |
| 28 COMPLETE | account_5482 404, audit_record_9265, support_2351, analytics_6077, data_flow_2337, backup_838 | trap: evidence_02 search_8168 `smartinez6461.jr@gmail.com` (09-15T09:00), not this user |
| 29 INCOMPLETE | search_1993, analytics_5208 (EXPOSED), support_5281 (EXPOSED), data_flow_3827 (ACTIVE) | all via **old** email noah.f438085 (current noah.f4380, near-duplicate). evidence_02 shows analytics_5208 with the current email and hash. |
| 30 INCOMPLETE | search_9359, analytics_3697, support_6477, data_flow_8524 | via old email camille.bernard86 (current camille.bernard) |

Gold findings order: REMAINING, then EXPOSED, then ACTIVE_DATA_FLOW, then RESTORE_RISK; within the same operation, alphabetical by system (analytics < support). Remediation order: DISABLE_DATA_FLOW, BLOCK_RESTORE, DELETE, REDACT, ANONYMIZE. Verification order: ABSENT (account, export, search, …, system alphabetical), then PRESENT (security), REDACTED, ANONYMIZED, DATA_FLOW_DISABLED, RESTORE_BLOCKED. An INCOMPLETE case always verifies account ABSENT and its security audit record PRESENT, both with evidence "".

**evidence_51 (case_31 / case_32):**

* case_31:
  * account_4857 ABSENT is proven by the **empty** `account_service/customer_profiles` snapshot. The id comes from activity_3682 DELETE account_4857 at 09-06T10:45 inside the case window.
  * audit_record_6909 (user_541) → PRESENT.
  * tombstone_440 has subject_reference user_541 and name/email/phone/email_hash all null → REDACTED.
* case_32:
  * tombstone_9178 has name "Kofi Addo", email addo.kofi@gmail.com, phone, hash 4f4b9c98… → REPORT_EXPOSED_PII → REDACT.
  * account_8858 (activity_3685 PARTIAL) and audit_record_7068 are verified with evidence "".

**evidence_03:**

* case_11 (user_32):
  * account_4248 NOT_FOUND → verify.
  * search_052 FOUND → REMAINING.
  * analytics_2034 IDENTIFIABLE → EXPOSED.
  * support_864 SUPPORT_MESSAGE IDENTIFIABLE → EXPOSED/REDACT.
  * data_flow_9522 ACTIVE.
  * audit_record_9394 user_32.
* case_13 (user_33): search_1308 FOUND; support_4218 **SUPPORT_ATTACHMENT** FOUND → REMAINING/DELETE (not REDACT); account_9335; audit_record_4816.
* case_14 (user_37): backup_3870 BACKUP_ARCHIVE ACTIVE → RESTORE_RISK/BLOCK; account_3677; audit_record_987.

**evidence_56 / evidence_59:** see 2.5.

---

## 4. Decoys and traps (complete list from these files)

* **`.jr` look-alike search docs (never matched to any user):**
  * search_5192 `znkosi0011.jr@fastmail.com` (e45, 02-23T07:00)
  * search_9094 `varga.tomasz.jr@gmail.com` (e40, 03-20T05:00)
  * search_9252 `aboateng9675.jr@fastmail.com` (e31 flat, 05-04T07:00)
  * search_5349 `isabela.oliveira.jr@outlook.com` (e07, 09-11T05:00)
  * search_8168 `smartinez6461.jr@gmail.com` (e02, 09-15T09:00)
  * search_9606 `camila.almeida.jr@outlook.com` (e36, 04-09T09:00; the real account is camila.almeida@outlook.com)
  * They have no activity and no display_name/customer_reference. Use exact (case-insensitive) email equality; never fuzzy or substring matching.
* **Stale pre-audit positives:** account_9031 (02-12), 6006 (03-14), 8598 (04-08), 3785 (05-03), 945 (06-17), 8819 (08-11), 5684 (09-09), 7618 (04-03). Each is ACTIVE/FOUND in an older layer and superseded by ABSENT at audit.
* **Post-audit recreations / re-indexes:** search_2979 (01-31T15), search_8332 / 8910 (02-20), account_2420 (03-22), account_2854 (04-16), account_8892 (05-06), account_4606 (05-11), search_9526 (06-05), account_2838 (06-25), account_7324 (06-30), account_246 + search_2597 (07-25), account_6805 (08-19), account_5186 (09-13), account_3866 (09-17), account_1417 (08-14), account_5043 (04-11), plus 9 ledger rows (evidence_50, cases 534–542). Ignore them all for state; they may still reveal resource↔user links.
* **Non-requesting users:** user_31 (account_146, audit_record_5307 in the handover), user_824, user_843, and user_22 (whose case_53 audit is 05-25).
* **NOT_APPLICABLE cohort** in evidence_50: request texts contain "remove", "change", "copy", "download" but are not deletions.
* **Near-duplicate and historical identities:** noah.f438085 vs noah.f4380; camille.bernard86 vs camille.bernard; abena.o189491 → abena.o189466 → abena.o1894 (two hops; the evidence uses the oldest); choi.jihoon94 (uppercased in the evidence); lucas-souza95. The email_hash in bundles is always the current hash; no historical hash appears in records.
* **Source names differ from system_id:** analytics_identity_store / user_export_store / records_assurance_*. Emit `analytics_platform`, `export_service`, `identity_service`, `legal_service`, etc.

---

## 5. Practical algorithm for these files

1. Normalize every file into (time, system, resource_id, category, state, identifiers) using `records_normalize.py`.
2. Resolve identifiers against the current snapshot plus every audit-log old/new value (lower-cased), and `user_XX` directly.
3. For a case, keep observations with file captured_at <= audit_at and entry time <= audit_at. Take the latest per resource. Cite the file_id that holds that observation.
4. Link unlinked 404 accounts and anonymized analytics by activity window plus the clean-user set plus the ascending tie-break (0.6). Also use later files purely for links and resource enumeration.
5. Category from the `record_type` column / collection name. Otherwise use the activity event_type (DELETE vs REDACT on support; ANONYMIZE on analytics).
6. Map states to steps: PRESENT (profile/search/export/attachment) → REMAINING + DELETE; IDENTIFIABLE (analytics) → EXPOSED + ANONYMIZE; IDENTIFIABLE (support message / tombstone) → EXPOSED + REDACT; ACTIVE flow → ACTIVE_DATA_FLOW + DISABLE; ACTIVE backup → RESTORE_RISK + BLOCK; security / legal → VERIFY_PRESENT.
