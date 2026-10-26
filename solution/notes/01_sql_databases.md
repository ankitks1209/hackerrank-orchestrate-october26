# 01 - SQL database evidence (dataset/evidence/databases/, 24 files)

Companion files in this folder:
- `01_sql_rows_annotated.txt`: every row of every SQL file, one line each, with the tables it appears in
  (P=primary, RR=read replica, REP=reporting replica, FO=failover, AP/EU=regional replicas), the populated
  PII fields, the resolved `user_id`(s), how it was linked (email / hist_email / user_id / phone / hash / name),
  and the cases whose user it is (`case_X@audit_at`). Decoys show `UNKNOWN=<email>` and `no-case`.
- `01_sql_case_derivations.txt`: for each of the 209 cases (sample + eval) that have SQL rows, the rows
  classified by policy state (REMAINING / EXPOSED_PII / ACTIVE_DATA_FLOW / RESTORE_RISK / ok states).
- Scripts (scratchpad, not in repo): load.py, annot.py, compact.py, derive.py. Each loads every `.sql` into
  in-memory sqlite with `executescript` (all files are valid SQLite; `json_valid` CHECK is used).

## 1. File inventory

| file_id | file | captured_at (manifest) | topology | tables (rows) |
|---|---|---|---|---|
| evidence_47 | customer_data_reporting_replica_20260208.sql | 2026-02-08T07:00:00Z | reporting_replica | customer_data_primary 24, customer_data_reporting_replica 25 |
| evidence_43 | customer_data_reporting_replica_20260305.sql | 2026-03-05T12:00:00Z | reporting_replica | primary 25, reporting_replica 26 |
| evidence_38 | customer_data_regional_replicas_20260330.sql | 2026-03-30T10:00:00Z | regional_replicas | primary 28, replica_ap_south 29, replica_eu_west 28 |
| evidence_33 | customer_data_regional_replicas_20260424.sql | 2026-04-24T08:00:00Z | regional_replicas | primary 29, ap_south 29, eu_west 31 |
| evidence_29 | customer_data_regional_replicas_20260519.sql | 2026-05-19T06:00:00Z | regional_replicas | primary 28, ap_south 29, eu_west 28 |
| evidence_24 | customer_data_read_replica_20260613.sql | 2026-06-13T11:00:00Z | read_replica | primary 24, read_replica 26 |
| evidence_20 | customer_data_read_replica_20260708.sql | 2026-07-08T09:00:00Z | read_replica | primary 31, read_replica 32 |
| evidence_15 | customer_data_read_replica_20260802.sql | 2026-08-02T07:00:00Z | read_replica | primary 24, read_replica 25 |
| evidence_10 | customer_data_read_replica_20260827.sql | 2026-08-27T12:00:00Z | read_replica | primary 29, read_replica 30 |
| evidence_05 | customer_data_read_replica_20260921.sql | 2026-09-21T10:00:00Z | read_replica | primary 30, read_replica 31 |
| evidence_52 | customer_data_failover_replica_20260920.sql | 2026-09-20T12:00:00Z | failover_replica | primary 16, failover_replica 16 (identical) |
| evidence_54 | customer_accounts_failover_replica_20260902.sql | 2026-09-02T23:00:00Z | failover_replica | customer_profiles_primary 3, customer_profiles_failover_replica 4 |
| evidence_57 | customer_search_primary_20260910.sql | 2026-09-10T08:45:00Z | primary_only | search_documents_primary 3 |
| evidence_63,66,69,72,75,78,81,84,87,90,93 | customer_data_inventory_YYYYMMDD.sql (11 files) | 2026-02-13 ... 2026-09-16 (odd seconds, e.g. 07:43:27Z) | (no header) | 9 tables, 0-7 rows each (see section 4) |

Header comments in the replica/topology files: `-- Captured at: <ts>`, `-- Database topology: <x>`,
`-- Compare the primary and any replica tables for replication drift.` Inventory files have NO header; their
time is in table `snapshot_scope.captured_at` and a trailing comment `-- snapshot_completed_at=<ts>`,
both equal to the manifest `captured_at`.

## 2. Schema family A: generic JSON document tables (replica files, 10 files + evidence_52)

All `customer_data_*` tables share one schema:
`resource_id TEXT PK, origin_system TEXT, collection_name TEXT, record_json TEXT CHECK(json_valid), updated_at TEXT`.
`origin_system` IS the output `system_id`; `resource_id` IS the output `resource_id`. Map:

| origin_system (system_id) | collection_name | resource_id prefix | record_json keys | PII fields | compliant-state marker |
|---|---|---|---|---|---|
| account_service | customer_profiles | account_NNN | customer_reference, full_name, email, phone, account_status (ACTIVE), signup_channel | all | row should not exist (USER_PROFILE -> DELETE) |
| search_service | customer_search_documents | search_NNN | index_name (customer_directory_v3), document{display_name,email,customer_reference} | display_name, email, customer_reference | row should not exist (SEARCH_INDEX_ENTRY -> DELETE) |
| analytics_platform | customer_analytics_reports | analytics_NNN | user_id, email, phone, email_hash, reporting_window, metrics{}, recent_activity[] | user_id,email,phone,email_hash | all 4 null = ANONYMIZED (62 rows); all 4 set = exposed (31 rows). Never partial. |
| support_platform | support_conversations | support_NNN | ticket_id (CS-xxxx), subject_reference (user_id), channel, message_text | subject_reference + email inside message_text | message_text == "[REDACTED]" = REDACTED (11). Else text "Please send the delivery update to <email>. The affected order includes: <product>." (50) = exposed, shared order context -> REDACT (rule_05) |
| support_platform | ticket_attachments | support_NNN | ticket_id, file_name (delivery_confirmation_NN.pdf), uploaded_by (email), storage_class | uploaded_by | present = remaining (SUPPORT_ATTACHMENT -> DELETE) |
| export_service | customer_export_jobs | export_NNN | owner_email, file_name, created_at, expires_at, download_available(true), included_sections | owner_email | present = remaining (USER_EXPORT -> DELETE). All 5 distinct exports have expires_at AFTER capture, download_available=true |
| integration_service | connector_configurations | data_flow_NNN | connector_name (customer-events-to-warehouse-N), destination customer_analytics_warehouse, subject_selector, enabled, mode continuous_sync | subject_selector | enabled=false -> DISABLED; enabled=true -> ACTIVE_DATA_FLOW |
| backup_service | backup_catalog | backup_NNN | archive_path (s3://customer-backups/weekly/segment-NN.tar.zst), subject_reference, restore_allowed, encryption | subject_reference | restore_allowed=false -> BLOCKED; true -> RESTORE_RISK (BACKUP_ARCHIVE -> RETAIN + BLOCK_RESTORE) |
| identity_service | deleted_customer_references | tombstone_NNN | subject_reference (user_id), name, email, phone, email_hash, account_status DELETED | name,email,phone,email_hash | all 4 null = correctly REDACTED tombstone; any non-null = REPORT_EXPOSED_PII -> REDACT_RECORD (rule_15). Only in evidence_52 |
| security_service | security_audit_events | audit_record_NNN | subject_reference (user_id), event_name account_deletion_reviewed, actor_type, integrity_seal | subject_reference (allowed) | always RETAIN -> VERIFY_RECORD_PRESENT |
| legal_service | retained_order_records | legal_hold_NNN | subject_reference, order_reference ORD-2026NNNN, retention_reason payment_dispute_and_tax_record, retained_until 2033-12-31 | subject_reference | RETAIN (rule_13) -> VERIFY_RECORD_PRESENT. 4 distinct: legal_hold_8017 (user_259, ev_24), legal_hold_2227 (user_503), legal_hold_4887 (user_509) (ev_47), legal_hold_5622 (user_458, ev_43) |

Strong generator correlation: the reference type predicts compliance.
- connector subject_selector = `user_NN` -> enabled=false (11/11); = email -> enabled=true (43/43, incl. 2 UPPERCASE emails).
- backup subject_reference = `user_NN` -> restore_allowed=false (11/11); = email -> true (13/13).
- Same in inventory (see section 4). So a remediated record is pseudonymised to the user_id; a live one still carries the email.

Every row `updated_at` equals the capture time, EXCEPT one decoy search doc per file (section 6), whose `updated_at` is
capture minus 3h. No row anywhere has updated_at > captured_at.

## 3. Replication drift (the core trick of the replica files)

Computed primary-vs-replica set differences and JSON diffs for every file. Result: no field-level differences ever;
drift is only "row present in replica, missing in primary", and it is always an `account_service` customer profile
(full PII, account_status ACTIVE). The primary is clean, so a naive primary-only check says COMPLETE.

| file | replica table | replica-only row | user | case |
|---|---|---|---|---|
| evidence_47 | reporting_replica | account_1035 Nicolas Fernandez nicolas.f550081@outlook.com | user_509 | case_511 |
| evidence_43 | reporting_replica | account_3183 Kojo Gyasi k.gyasi98@yahoo.com | user_451 | case_453 |
| evidence_38 | replica_ap_south | account_5389 Gabriel Pereira g.pereira86@yahoo.com | user_403 | case_405 |
| evidence_33 | replica_eu_west | account_6539 Andres Rodriguez andres.r136@outlook.com | user_353 | case_355 |
| evidence_33 | replica_eu_west | account_8105 Arthur Lefevre a.lefevre74@yahoo.com | user_355 | case_357 |
| evidence_29 | replica_ap_south | account_585 Zofia Zielinski zofia.z024@outlook.com | user_305 | case_307 |
| evidence_24 | read_replica | account_3150 Yu-na Park y.park50@yahoo.com | user_259 | case_261 (also has legal_hold_8017) |
| evidence_24 | read_replica | account_9608 Sibusiso Nkosi sibusiso.n9912@outlook.com | user_257 | case_259 |
| evidence_20 | read_replica | account_4348 Kavya Nair kavya.n9800@outlook.com | user_209 | case_211 |
| evidence_15 | read_replica | account_8023 Amara Adeyemi a.adeyemi9897@yahoo.com | user_151 | case_153 |
| evidence_10 | read_replica | account_6345 Ha-eun Kang h.kang86@yahoo.com | user_103 | case_105 |
| evidence_05 | read_replica | account_994 Diya Kapoor diya.k4436@outlook.com | user_53 | case_16 (sample, gold confirms) |
| evidence_54 | customer_profiles_failover_replica | account_005 Leila Haddad | user_05 | case_05 (sample, gold confirms) |
| evidence_52 | failover_replica | none (primary == failover, 16 rows) | - | - |

Regional files: a drifted row can be in only ONE of the two regional replicas (ap_south or eu_west), so every
replica table must be checked, not just the first one.
system_activity shows the matching false claims, e.g. activity_3571 DELETE account_994 FAILED then activity_3577
SYNC_RECORD account_service->account_replication_cluster "final checkpoint" SUCCESS; activity_3482 DELETE
account_005 SUCCESS + activity_3483 SYNC to account_failover_replica SUCCESS, but the failover still has the row.

## 4. Schema family B: customer_data_inventory_* (11 files)

Tables (always all 9 are created, possibly empty):
- `snapshot_scope(origin_system PK, captured_at)`: which systems the capture covered.
- `customer_profiles(resource_id, customer_reference, full_name, email, phone, email_hash, account_status, updated_at)` -> account_service
- `customer_search_documents(resource_id, customer_reference, display_name, email, phone, email_hash, index_name, updated_at)` -> search_service
- `customer_analytics_profiles(resource_id, customer_reference, email, phone, email_hash, audience_cohort, updated_at)` -> analytics_platform
- `support_records(resource_id, customer_reference, requester_name, requester_email, requester_phone, message_excerpt, updated_at)` -> support_platform
- `customer_exports(resource_id, customer_reference, owner_email, owner_phone, object_key exports/export_N/customer_data.zip, updated_at)` -> export_service
- `connector_subscriptions(resource_id data_flow_N, customer_reference, customer_email, connector_name customer_events_connector, enabled 0/1, last_delivery_status delivered|stopped, updated_at)` -> integration_service
- `backup_restore_entries(resource_id backup_N, customer_reference, customer_email, archive_key, restore_allowed 0/1, updated_at)` -> backup_service
- `security_audit_records(resource_id audit_record_N, subject_reference, event_code, retention_until, updated_at)` -> security_service
  (event_code ACCOUNT_DELETION_RECORDED->2031-12-31, PRIVACY_REQUEST_ACCEPTED->2032-06-30, SUBJECT_REQUEST_AUDITED->2033-12-31, IDENTITY_CHANGE_RECORDED->2034-09-30; all in the future, so RETAIN)
- Indexes on the email columns only (hint: the intended join key is email).

Field-population rule: every inventory row carries exactly ONE identifier: either an email (current, historical,
or UPPERCASE) or `customer_reference` = user_id. Name, phone and email_hash columns are always NULL. Counts:
analytics 24 all-null (anonymized, unlinkable) / 17 email-only; search 53 email-only; profiles 8 email-only, all
`account_status=DELETION_PENDING` (=> remaining record despite the "pending" status); exports 8 email-only;
connectors 20 email (enabled=1, delivered) / 5 ref (enabled=0, stopped); backups 5 email (restore 1) / 5 ref (restore 0);
support 28 email / 5 ref-only.

Inventory support_records are ambiguous from SQL alone: no "[REDACTED]" marker and no shared-context flag. Email-bearing
ones = remaining or exposed (DELETE vs REDACT must come from other evidence or request text); ref-only ones look like
already-redacted records (VERIFY_RECORD_REDACTED?). message_excerpt values: "Customer asked support to correct delivery
details." (10), "Customer supplied contact details for a delivery query." (9), "Customer contacted support about account
access." (8), "Customer followed up about an order update." (6).

snapshot_scope semantics: a system missing from scope always has 0 rows (ev_63 and ev_72 lack export_service; ev_78
lacks backup_service). A system IN scope with 0 rows (e.g. customer_profiles empty in ev_66/69/75/81, while account_service
is in scope) can be read as proof of absence at capture time. Treat a missing scope as "not observed", not "absent".
evidence_90 (2026-09-05T07:18:01Z) has scope = account_service only and ZERO rows in every table. Its batch (audit
2026-09-06T07:00, cases 83-92) is otherwise covered only by logs/search_index_diagnostic_20260906.log, so evidence_90 is
probably the account-absence proof (VERIFY_RECORD_ABSENT) for those cases, like evidence_54 for case_01/02/04.

## 5. Small special files

evidence_54 customer_accounts_failover_replica_20260902 (flat columns resource_id,user_id,full_name,email,phone,account_status,updated_at):
- primary: account_8741 Karim El-Masri karim.elmasri@gmail.com, account_9116 Mateo Rios Gil m.rios.gil@outlook.com,
  account_7204 Priya Ramanathan p.ramanathan@gmail.com (user_8741/9116/7204 do NOT exist in user_identities: decoys
  shaped like user_01 Amina El-Masri, user_02 Mateo Rios, user_07 Priya Raman).
- failover adds account_005 Leila Haddad (user_05).
- Gold: case_01 account_001, case_02 account_002, case_04 account_004 VERIFY_RECORD_ABSENT citing evidence_54 (absent
  from BOTH tables; the account ids come from system_activity: activity_3342 account_001, activity_3376 account_002 PARTIAL;
  account_004 appears in no text file, so it must come from an image/PDF or the account_00N convention).
  case_05: REPORT_REMAINING_RECORD account_005 evidence_54. The decoys are never findings.

evidence_57 customer_search_primary_20260910 (resource_id, display_name, email, source_resource_id, indexed_at):
- search_001 Jonas Berg jonas.berg@outlook.com source account_006, indexed_at 2026-09-09T22:12 (re-indexed AFTER
  activity_3546 DELETE search_001 FAILED on 08-30), so case_06 gets FINDING search_001 evidence_57.
- Decoys: search_8814 Jonas Berglund jonas.berglund@outlook.com and search_4203 Joana Berg joana.berg@outlook.com.
- `source_resource_id` is the only SQL row that links search to account explicitly (account_006 = verification target).

evidence_52 customer_data_failover_replica_20260920 (cases 543-550, all audit 2026-09-20T12:00):
- Only audit_record_* and tombstone_*. Tombstones with PII: tombstone_8648 (user_544 name+email+hash), tombstone_8095
  (user_546 name+phone+hash, no email), tombstone_3745 (user_548 all four), tombstone_7389 (user_550 name+email+hash).
  Clean tombstones: tombstone_205 (543), 946 (545), 8774 (547), 3963 (549). Note tombstone_8095 is linked by phone/hash/user_id, not by email.

## 6. Decoys and traps found

1. ".jr" search docs: one per replica file, display_name=null, customer_reference=null, email = a case user's email
   with ".jr" inserted, updated_at = capture-3h, unknown to user_identities:
   search_4725 hannah.carter.jr@outlook.com (ev_47, shadows case_512), search_8371 hhan9955.jr@fastmail.com (ev_43, case_456),
   search_5582 abennett9843.jr@fastmail.com (ev_38, case_408), search_6505 walker.charlotte.jr@gmail.com (ev_29, case_304),
   search_4300 ionescu.pavel.jr@gmail.com (ev_10, case_112). Substring or fuzzy matching would wrongly mark these cases INCOMPLETE.
   Use exact, case-insensitive matches. Sample case_28's text describes this trap.
2. Near-name decoys in evidence_54 / evidence_57 (section 5). Names are not unique even among real users: "Mateo Rios"
   (user_02, user_262), "Thandiwe Ndlovu" (user_04, user_413), "Gabriel Costa" (user_08, user_143). Never link by name alone.
3. Orphan user: user_59 Karim Hamdan (karim.h1950@zoho.com) has search_7455, data_flow_4218 (enabled) and audit_record_4316
   in evidence_05 but NO request. activity_3448 says "Active connector repopulated downstream resource search_7455". Don't
   attach these to any case.
4. Case variants: 20 request emails are UPPERCASE (e.g. BCARVALHO6517@GMAIL.COM, O.ERIKSEN10@YAHOO.COM, JULES-LAURENT@PROTON.ME),
   and SQL rows store emails in either case (data_flow_5080 selector BCARVALHO6517@GMAIL.COM). Lowercase everything.
   email_hash = sha256(lowercase email) for all 850 identities, so a hash-only row can be resolved.
5. Historical emails: 68 row-links go through a user_audit_log old_value (e.g. data_flow_108 / search_5960 use
   emeka.ogunleye94@gmail.com while analytics_5715 holds the current emeka.ogunleye@gmail.com, case_62; support_4249
   hcho154598@gmail.com for case_66). The request email itself is sometimes the historical one. Resolve both directions.
6. Multi-case users: user_07 (case_61 audit 2026-02-14 and case_07 audit 2026-09-12), user_17 (case_46, case_17),
   user_18 (case_52, case_33). Choose the evidence by each case's audit_at.
7. "Primary clean, replica dirty" (section 3), and activity SUCCESS claims that the snapshots contradict
   (activity_3580 DELETE search_1007 SUCCESS, but search_1007 is still in evidence_05).
8. Inventory account rows say DELETION_PENDING, but a pending row is still present, so report it as remaining.

## 7. Timing

- Every SQL file is a batch snapshot for ~8-10 consecutive cases whose audit_at is the same. Replica files are captured
  exactly AT audit_at (e.g. evidence_05 = 2026-09-21T10:00 = audit of case_16,22,54,56-60,62). Inventory files are captured
  17-60 min BEFORE the batch audit_at (ev_63 07:43:27 vs audit 08:00). evidence_54/57 are hours or days before.
  Batch map: ev_47->503-512, ev_63->493-502, ev_43->453-462, ev_66->443-452, ev_38->403-412, ev_69->393-402,
  ev_33->353-362, ev_72->333-342, ev_29->303-312, ev_75->293-302, ev_24->253-262, ev_78->243-252, ev_81->213-222,
  ev_20->203-212, ev_84->173-182, ev_15->153-162, ev_87->123-132, ev_10->103-112, ev_54->case_01/02/04/05,
  ev_90->(83-92?), ev_57->case_06, ev_93->case_09 + 64-72, ev_52->543-550, ev_05->16,22,54,56-60,62.
- Checked all user/file pairs: no SQL file is captured after the audit_at of any case it mentions, and no identity
  change (user_audit_log) for these users happens after their case's audit_at. The post-audit trap is in other
  evidence types (e.g. evidence_03 2026-10-01, evidence_94 2026-09-26, evidence_50 2026-10-01): check them per case.
- Activity-stream linking heuristic (anonymized analytics rows carry no identifier): per-case policy activities sit just
  before the case's `reported_at` at fixed offsets (sample case_26, reported 09-02T12:00: account -51:17, analytics -28:36,
  support -21:07, data_flow -14:37, backup -07:08; case_27 analytics -28:51). Example: analytics_8858 (activity_3504
  2026-08-29T09:31:24) fits case_57 (reported 08-29T10:00), together with support_7479, data_flow_1368 and backup_7711.
  analytics_2572 (09:31:09) is probably case_56 or case_58, and analytics_9069 (08-26 09:31:12) case_59 or case_60.

## 8. Sample cross-check (gold vs SQL rows)

- case_16 (diya.k4436@outlook.com, user_53, audit 09-21T10:00) / evidence_05: account_994 only in customer_data_read_replica
  -> FINDING REPORT_REMAINING_RECORD; search_1007 in primary+replica {display_name Diya Kapoor, customer_reference user_53}
  -> REMAINING; audit_record_9528 subject user_53 -> VERIFY_RECORD_PRESENT. Matches gold exactly (7 steps).
- case_22 (seoyeon-han@gmail.com, user_51) / evidence_05: search_8911 -> REMAINING; analytics_4440 {user_id user_51, email,
  phone, email_hash bbd5522c...} -> REPORT_EXPOSED_PII + ANONYMIZE; audit_record_3482 present; account_4990 absent from both
  tables (activity_3573 claimed SUCCESS) -> VERIFY_RECORD_ABSENT (empty evidence, since the case is INCOMPLETE). Matches gold.
- case_05 / evidence_54: account_005 failover-only. case_01/02/04: absence in evidence_54. case_06 / evidence_57: search_001.
- case_09 (k.appiah88@gmail.com, user_61) / evidence_93: backup_4978 {customer_email k.appiah88@gmail.com, restore_allowed 1}
  -> REPORT_RESTORE_RISK + BLOCK_RESTORE. The gold's account_3960 and audit_record_4902 are NOT in evidence_93 (they are in
  logs/structured_service_events_eu_west_20260918.log), so the inventory is not the full set of records for a case.
  Combine evidence sources.
- My SQL-only derivation reproduces every SQL-cited sample finding (case_05, 06, 09, 16, 22) with no false positives.

## 9. Implications for the solver

1. Parse every table in a file; build the union of primary + all replicas; a row in ANY replica = present.
2. Resolve identities with lowercase exact matching over current email, historical emails, sha256(email), phone, user_id.
   Never match by name alone. Never use substring/fuzzy matching.
3. Classify each row by its own state fields (section 2 and 4 tables) and map it to deletion_rules.
4. Cite the SQL file_id for findings, and for COMPLETE-case verifications whose state the snapshot shows
   (absent account, null analytics, [REDACTED] support, disabled flow, blocked backup, clean tombstone, audit present).
5. Only use files with captured_at <= audit_at. For each system, prefer the latest snapshot that is still at or before audit_at.
