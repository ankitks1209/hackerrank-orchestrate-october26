# 05 — system_activity / identities / audit log / rules: deep analysis

Scope: `dataset/system_activity.csv`, `dataset/user_identities.csv`, `dataset/user_audit_log.csv`,
`dataset/deletion_rules.csv`, cross-checked against `sample_output.csv` (32 gold cases) and the text evidence
(SQL / JSON / LOG / TXT; PNG/PDF not parsed here). Analysis scripts live in the session scratchpad
(`ident.py`, `act.py`, `link.py`, `runs.py`, `caseact.py`, `samp.py`, `secs.py`, `fp.py`, `goldlink.py`).

---

## 1. Identity layer

### 1.1 user_identities.csv
- 850 rows, `user_01`..`user_850`, columns `user_id,name,email,phone,email_hash,updated_at`. No blanks.
- All 850 emails are already lowercase/trimmed and unique; all 850 phones unique.
- **email_hash = sha256(email) hex (64 chars) of the CURRENT email, 850/850.** (no salt, no md5, no lowercasing needed
  because emails are lowercase.) Historical hashes are in the audit log (`field_name=email_hash`) and every
  audit email change has a paired email_hash row with sha256(old)/sha256(new) — 0 mismatches.
- `updated_at` range 2023-06-22 .. 2026-08-30. For the 196 users with audit history, `updated_at` == time of the
  last audit change. No user's `updated_at` is after any request's `requested_at`.
- Domains: gmail 354, outlook 142, yahoo 72, proton.me 72, zoho 70, icloud 70, fastmail 70.
- **Duplicate NAMES (trap: never match by name):**
  - `Mateo Ríos` = user_02 (mateo.rios@outlook.com, sample case_02) and user_262 (mrios9507@fastmail.com; eval case_264 uses its old email `mrios950798@fastmail.com`).
  - `Thandiwe Ndlovu` = user_04 (sample case_04) and user_413.
  - `Gabriel Costa` = user_08 (sample case_08) and user_143.
- Phone formats are country-specific with spaces/dashes/parentheses (`+1 (312) 555-0129`, `+55 11 97284-3165`). In
  text evidence, 72 of 76 phone strings match a current phone exactly; 1 matches an OLD phone; 3 are unknown decoys.

### 1.2 user_audit_log.csv
- 306 rows `audit_01..audit_306`, sorted by time, 2024-12-14 .. 2026-06-03 (all before every requested_at; 0 changes
  after any case's requested_at or audit_at).
- field_name vocabulary: `email` 107, `email_hash` 107 (always paired with an email change, same timestamp), `phone` 92.
  No name changes.
- 196 users have history: 91 users 1 row (phone-only), 102 users 2 rows (email+hash), 2 users 4 rows, 1 user 3 rows.
- **Multi-hop email chains (2 users):**
  - user_10: `nadia.ionescu@yahoo.com` (audit_121, 2025-12-13) -> `nadia.petrescu@yahoo.com` (audit_238, 2026-04-12) -> `n.petrescu@yahoo.com` (current). Sample case_10 uses the OLDEST address.
  - user_35: `abena.o189491@zoho.com` -> `abena.o189466@zoho.com` (audit_179, 2026-02-03) -> `abena.o1894@zoho.com` (audit_305, 2026-06-03). Eval case_37 uses the OLDEST address. Note the near-identical digit strings.
- Chains are consistent (each new_value == next old_value; last new_value == current snapshot).
- No old email is reused by another user; no old phone equals someone's current phone.
- The resolver MUST collect for each user: current email/phone/hash + every historical email, email_hash and phone.
  Evidence uses all of these (see §1.4).

### 1.3 Request email resolution
| set | current email | historical email | no match | needs `.lower()` |
|---|---|---|---|---|
| sample (32) | 29 | 3 (case_10, case_29, case_30) | 0 | 0 |
| eval (518) | 418 | **100** | 0 | **20** (ALL-CAPS, e.g. case_40 `CHOI.JIHOON94@GMAIL.COM`, case_85, case_148, case_326, case_427 are caps AND historical) |

- Every eval email resolves to exactly one user after lowercasing. Only user_18 gets 2 eval cases.
- Case->user numbering (artifact, do not rely on it): eval case_N -> user_(N-2) for 498 cases; case_543..550 -> user_543..550;
  12 "special" eval cases map to low user ids (see §4). Sample: case_N -> user_N for 21 cases; others user_43, 61, 32, 33, 37, 53, 50, 48, 51, 541, 542.
- Historical match examples (eval): case_37 abena.o189491@zoho.com->user_35, case_43 javier.r940897@outlook.com->user_41, case_264 mrios950798@fastmail.com->user_262 ... (full list in scratch output of ident.py).

### 1.4 How identifiers appear in evidence (important for linking)
- `correlation_key`, `lookup_key`, `subject_key`, `match_key`, `scan_key`, `subject_ref`, `subject_reference`,
  `customer_reference`, `customer_email`, `owner_email`, `requester_email`, `email`, `email_hash`, `matched_value`.
- **Old email HASH is used as a link**: sample case_12 (user_12) analytics_9914 is found in evidence_01 only via
  `correlation_key="44a65154...f10e"` = sha256 of the OLD email `minjun.kim90@gmail.com` (audit_283 old_value). Gold: REPORT_REMAINING_RECORD -> DELETE (it is an opted-in marketing contact `email_opt_in=true`, not an anonymize case).
- **Old PHONE is used as a link**: evidence_01 line 23/25 `scan_key="+81 90 6156 0005"` / `matched_value=` on support_9538 (`delivery_confirmation_32.pdf`) = user_11's OLD phone (audit_279). user_11 = eval case_34.
- Logs split identity and resource across lines of the same `trace_id` (e.g. `profile_lookup_started lookup_key=<email>` then `profile_lookup_completed resource_id=account_X rows=0 http_status=404`). Group by trace_id/requestId before linking.
- Text evidence contains 257 64-hex strings: 36 current hashes, 1 old hash, 220 are `integrity_seal: sha256:000...NNNN` pseudo-seals (NOT email hashes — ignore).
- **Decoy look-alike emails in evidence (22 not in identities):** a `.jr` family — `g.silva76.jr@gmail.com` (evidence_01, vs real g.silva76@gmail.com = case_35), `smartinez6461.jr@gmail.com` (evidence_02), `mrios9507.jr@fastmail.com`, `abennett9843.jr@`, `aboateng9675.jr@`, `camila.almeida.jr@`, `hannah.carter.jr@`, `hhan9955.jr@`, `ionescu.pavel.jr@`, `isabela.oliveira.jr@`, `salma.hamdan.jr@`, `varga.tomasz.jr@`, `walker.charlotte.jr@`, `znkosi0011.jr@`, `zulu.lindiwe.jr@`; plus near-names `joana.berg@outlook.com`, `jonas.berglund@outlook.com` (vs jonas.berg, sample case_06 evidence_57), `karim.elmasri@gmail.com` (vs amina.elmasri), `m.rios.gil@outlook.com` (vs mateo.rios), `p.ramanathan@gmail.com` (vs priya.raman), `nadia.popescu@yahoo.com` (vs nadia.ionescu), `customer4104@yahoo.com`. Plus 3 unknown phones in evidence_54. **Use exact (lowercased) equality only — never fuzzy/substring/name matching.** Prefix or local-part checks (for example `"g.silva76" in text`) would wrongly match `g.silva76.jr@gmail.com`, so extract full email tokens with a regex and compare them exactly.

---

## 2. system_activity.csv

### 2.1 Shape
- 4011 rows, `activity_01..activity_4011`, cols `activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details`.
- Time range 2026-01-04T14:56:29Z .. 2026-10-01T10:18:34Z. Sorted by time EXCEPT the last 12 rows (activity_4000..4011, LINK_RESOURCE_IDENTITY) which are appended out of order (times 2026-02-13 .. 2026-09-26).
- reported_result: SUCCESS 2914, FAILED 721, PARTIAL 376.
- 3948 distinct resource_ids; 3885 appear once, 63 appear twice (account DELETE + replication SYNC pairs, and LINK rows). Resource numbers are NOT user numbers (account_4857 belongs to user_541).

### 2.2 event_type x result
| event_type | n | results |
|---|---|---|
| DELETE_RECORD | 890 | FAILED 368 / SUCCESS 302 / PARTIAL 220 |
| UPDATE_RECORD | 672 | background noise |
| SYNC_RECORD | 447 | 360 analytics sync (noise), 56 account replication checkpoint, 31 connector repopulation |
| INDEX_RECORD | 400 | noise |
| SEND_EMAIL | 368 | noise |
| REFRESH_CACHE | 284 | noise |
| RETAIN_RECORD | 206 | 196 security archival (noise), 10 legal_hold "Policy action completed" |
| ANONYMIZE_RECORD | 204 | |
| REDACT_RECORD | 173 | |
| CREATE_EXPORT | 155 | noise |
| CHECK_DATA_FLOW | 89 | all SUCCESS |
| DISABLE_DATA_FLOW | 36 | all SUCCESS |
| BLOCK_RESTORE | 36 | all SUCCESS |
| CHECK_RESTORE_ACCESS | 28 | all SUCCESS |
| LINK_RESOURCE_IDENTITY | 12 | all SUCCESS |
| CLASSIFY_REQUEST | 10 | all SUCCESS |
| RESTORE_BACKUP | 1 | SUCCESS |

### 2.3 source->target and resource prefixes
- deletion_worker->account_service 539, profile_service->account_service 440, account_service->search_service 400, notification_service->email_delivery_service 368, account_service->analytics_platform 360, deletion_worker->search_service 289, account_service->cache_service 284, support_platform->search_service 232 (resource `support_N`!), deletion_worker->analytics_platform 205, security_service->archive_service 196, deletion_worker->support_platform 192, export_service->object_store 155, deletion_worker->integration_service 125, deletion_worker->backup_service 64, account_service->account_replication_cluster 55, deletion_worker->export_service 32, integration_service->search_service 31 (resource `data_flow_N`, details name a `search_N`), deletion_worker->legal_service 10, privacy_intake->privacy_case_management 10, deletion_worker->identity_service 10, data_catalog->* 12, backup_service->search_service 1, account_service->account_failover_replica 1.
- Prefixes: account 1046, search 690, analytics 566, support 425, email_delivery 368, cache 284, audit_record 197, export 189, data_flow 157, backup 66, tombstone 11, legal_hold 10, object 1, marketing 1.
- NOTE system-name mismatches vs gold system_id: activity uses `object_store` (export files), `archive_service` (audit records), `account_replication_cluster`/`account_failover_replica`; gold uses `export_service`, `security_service`, `account_service`. Gold system_id comes from the owning service, not the activity target.

### 2.4 details templates (47 clusters; ids normalised)
Background / noise (resource ids NEVER appear in any text evidence -> pure decoys):
- `Customer search-index refresh processed search_N.` (INDEX_RECORD 400)
- `Profile preference update processed account_N.` (UPDATE 440)
- `Support-case index update processed support_N.` (UPDATE 232)
- `Transactional email delivery processed email_delivery_N.` (SEND_EMAIL 368)
- `Profile cache refresh processed cache_N.` (REFRESH_CACHE 284)
- `Scheduled account export processed export_N.` (CREATE_EXPORT 155)
- `Customer profile synchronization processed analytics_N.` (SYNC 360)
- `Security-event archival processed audit_record_N.` (RETAIN 196)
=> 2,635 rows (~66%) are unrelated noise; their results (incl. FAILED/PARTIAL) mean nothing.

Deletion-worker run rows (resource ids DO appear in evidence):
- `Deletion worker submitted primary profile account_N to account_service.` (532; SUCCESS 264/PARTIAL 157/FAILED 111) — one per authorized case = the case's primary account id. **Result is noise** (sample case_25/26/28: FAILED but gold VERIFY_RECORD_ABSENT; case_24: SUCCESS but gold REPORT_REMAINING_RECORD).
- `Policy action completed for X.` (ANONYMIZE 125, REDACT support 36 + tombstone 5, DISABLE_DATA_FLOW 36, BLOCK_RESTORE 36, RETAIN legal_hold 10). Always SUCCESS. **In gold these resources are compliant** -> VERIFICATION with evidence (COMPLETE cases 21, 25–28, 31, 03).
- `Deletion worker received the final result for X from <system>.` (DELETE search 288, support 28, export 31, analytics 1; REDACT support 127, tombstone 5; ANONYMIZE 78). Mostly FAILED but some SUCCESS. **In every sample these resources are violations (FINDING) regardless of reported_result** (case_16 search_1007 SUCCESS -> REPORT_REMAINING_RECORD; case_24 search_5577 SUCCESS -> REPORT_REMAINING_RECORD).
- `Connector status check confirmed that data flow data_flow_N remains enabled.` (89) -> REPORT_ACTIVE_DATA_FLOW (cases 11, 15, 18, 20, 29, 30).
- `Restore-access check confirmed that archive backup_N can still be restored.` (28) -> REPORT_RESTORE_RISK (cases 09, 14, 17).
- `Replication worker reported its final checkpoint for account_N.` (55, SUCCESS 30/PARTIAL 25; source account_service->account_replication_cluster) — always 1h30–2h after the same account's DELETE; **the account was re-replicated / remains** -> REPORT_REMAINING_RECORD account (case_16 account_994, case_24 account_5334). These 55 + 1 are exactly the 63 "resource seen twice" pairs.
- `Active connector repopulated downstream resource search_N.` (31, integration_service->search_service, resource_id = data_flow_N, the search id only in details) — always ~19.5 min before a `received the final result for search_N` FAILED delete. Recreation path: expect REPORT_REMAINING_RECORD search + REPORT_ACTIVE_DATA_FLOW data_flow; remediate DISABLE flow first, then DELETE search. (No sample covers this family.)
- `Restore job repopulated downstream resource search_4882.` (activity_3387, RESTORE_BACKUP, resource backup_9287, 2026-08-22) — single backup-restore recreation; backup_9287 is user_16 (areed1433@gmail.com, eval case_55) per activity_4006 — but case_55 audit_at = 2026-04-30, so this Aug row is AFTER audit and must be ignored for case_55.
- `Privacy intake classified request for account_N as non-deletion; no destructive action was authorized.` (10) -> exactly the NOT_APPLICABLE cases case_533..542 (users 531..540): account_1733, 5835, 7821, 5605, 7452, 6486, 9321, 2176, 2461, 228.
- Hand-written sample rows (case_01..10 only): `reported the requested operation as completed` (7), `stopped after the target system returned an error` (2), `completed some internal work but could not confirm the final state` (1), `Replication worker reported its final checkpoint. Target resource: account_005` (1, to account_failover_replica).

`LINK_RESOURCE_IDENTITY` (12, data_catalog) — the ONLY activity rows naming emails/user_ids. They decode the image/PDF evidence:
| activity | time | resource | user/email | matching evidence (captured) | eval case (audit_at) |
|---|---|---|---|---|---|
| 4000 | 09-26 11:07 | account_5762 | user_11 haruka.s1838@zoho.com | evidence_04 account_admin_console png (09-26 11:00) | case_34 (09-27 13:00) |
| 4001 | 09-01 06:07 | search_428 | user_13 g.silva76@gmail.com | evidence_09 search_index_inspector png (09-01 06:00) | case_35 (09-02 08:00) |
| 4002 | 08-07 08:07 | data_flow_1121 | user_14 jain.aditi@gmail.com | evidence_14 connector_management_console png | case_39 (08-08 10:00) |
| 4003 | 07-13 10:07 | analytics_7438 | user_20 darwish.omar@icloud.com | evidence_19 analytics_profile_view png | case_50 (07-14 12:00) |
| 4004 | 06-18 12:07 | export_1260 | user_18 ingrid.dahl@outlook.com | evidence_23 customer_export_console png | case_52 (06-19 14:00) |
| 4005 | 05-24 07:07 | support_1034 | user_22 kagyeman8947@fastmail.com | evidence_28 support_ticket_console png | case_53 (05-25 09:00) |
| 4006 | 04-29 09:07 | backup_9287 | user_16 areed1433@gmail.com | evidence_32 backup_restore_console png | case_55 (04-30 11:00) |
| 4007 | 02-13 08:07 | object_19 (delivery_confirmation_19.pdf, "belongs only to" -> SUPPORT_ATTACHMENT DELETE) | user_07 priya.raman@gmail.com | evidence_46 object_storage_browser png | case_61 (02-14 10:00) |
| 4008 | 09-16 07:27 | marketing_001 | user_09 kwame-mensah@proton.me | evidence_60 marketing_profile_console png (07:20) | case_63 (09-17 09:20) |
| 4009 | 07-18 11:07 | export_1842 (`NST-2026-0718-1842`) | user_18 ingrid.dahl@outlook.com | evidence_18 account_history_report pdf | case_33 (07-19 13:00) |
| 4010 | 09-05 07:07 | audit_record_003 | user_03 oliver-bennett@gmail.com | evidence_37 security_audit_explorer png | case_45 (09-06 09:00) |
| 4011 | 03-10 06:07 | tombstone_17 (subject user_17) | user_17 leonie.g9352@outlook.com | evidence_42 deleted_account_reference png | case_46 (03-11 08:00) |
Each LINK row = evidence capture + 7 min, ~26 h before the case's audit_at (valid, pre-audit). New system ids appear only here: `object_storage`, `marketing_platform` (+ `legal_service`).

### 2.5 Temporal structure of a deletion run
- A case's primary-profile DELETE row is 0–2 days after `requested_at` and 0–2 h (typically 45–75 min) BEFORE `reported_at` (sample deltas -17 s .. -4442 s; hand-made samples slightly after).
- "Policy action completed" rows sit at reported_hour -29/-22/-15/-8 min (minute :31/:38/:45/:52, sequence analytics/tombstone/legal -> support -> data_flow -> backup) with gaps 7:29, 6:30, 7:29.
- Violating rows ("received the final result", checks, replication, repopulation) start ~1h28–2h04 after the account row and step by 18:30 / 19:29 (often after reported_at, still before audit_at).
- Seconds fingerprint (generator artifact): (first compliant row - account row) ends in :40/:41 s; (first violating row - account row) ends in :51/:52 s. Works for all samples, but global test is ambiguous for ~25% rows; usable only as a tie-breaker.
- reported_at - requested_at ∈ {24, 42, 48, 72} h. Cases share reported_at (12:00Z etc.), so many runs interleave (e.g. 2026-09-05 10:50–13:13 holds runs for case_21, case_23, case_536, case_546–548, case_53-ish rows) => **time-window linking alone is ambiguous** (2–7 candidate primary rows per case).

### 2.6 Why activity still matters (linking compliant resources)
Deleted/anonymized resources often carry NO identifier in evidence (by design: identifiers were removed). Example sample case_21 (user_21, COMPLETE):
- evidence_92 has `account_6440 {profile:null, status_code:404}` and `analytics_5335 {all identifiers null}`; only `audit_record_3737` carries `subject_reference: user_21`.
- account_6440/analytics_5335 are tied to the case only by activity_3661 (primary profile, 11:01:53) and activity_3665 (Policy action completed, 11:31:34 = +29m41s).
Of 111 distinct gold resource ids, ~29 had no identifier link in text evidence (my crude linker); 24 of those are reachable only through activity rows (primary account rows; anonymized analytics). Recommended linker: (1) evidence identity links, (2) trace-id grouping in logs, (3) activity run grouping by time window [requested_at, reported_at+3h] + elimination across all cases sharing the window (each case has exactly one primary account row; 539 DELETE-account rows + 10 CLASSIFY = 549 ≈ 550 cases), (4) seconds-fingerprint as tie-break.
~249 primary account ids appear in NO text evidence at all — their absence proof must come from 404/empty-snapshot evidence or images/PDFs; gold still cites an evidence_NN for the verification.

### 2.7 Traps in activity
- **reported_result is unreliable** both ways (see 2.4). Gold never follows it.
- **Activity after audit_at**: the 12 special eval cases reuse users whose deletion runs are in Aug/Sep, but audit_at is months earlier: case_46 (user_17, audit 03-11) vs activity_3383/3385 (08-22) and 3850 (09-15); case_55 (user_16, audit 04-30) vs RESTORE_BACKUP activity_3387 (08-22); case_53 (user_22, audit 05-25) vs activity_3669/3672 (09-05); case_50 (user_20, audit 07-14) vs 3719/3723/3725 (09-08); case_39 (user_14, audit 08-08) vs 3430/3434/3437 (08-25); case_33/52 (user_18, audit 07-19 / 06-19) vs 3324/3328/3331 (08-19). Filter `event_time <= audit_at`.
- **Activity before requested_at** for the same user: case_34 (user_11, req 09-24) has account_5762 DELETE FAILED on 08-28 (activity_3485); case_35 (user_13, req 08-30) has account_8491 / search_428 rows on 08-25. These belong to an earlier run, not this request — treat as history only (the resource still exists/needs evaluation by evidence).
- **Same user, multiple cases**: user_18 (case_33 & case_52), user_17 (sample case_17 & eval case_46), user_07 (sample case_07 & eval case_61). Answers differ per audit_at. Sample gold for user_17/user_07 is NOT transferable.
- **Name duplicates** (§1.1) and **look-alike emails** (§1.4).
- Background rows for `audit_record_N` (security archival) and `export_N` (scheduled export) are not the user's records; the real audit_record/export ids come only from evidence.
- `support_N` also appears as resource of support_platform->search_service UPDATE rows (noise).
- The 4 sample-only templates ("reported the requested operation as completed" etc.) do not occur in eval runs.

---

## 3. deletion_rules.csv -> systems / prefixes / step ops
| rule | category | action | system_id / prefix (gold or evidence) | typical steps | seen in samples |
|---|---|---|---|---|---|
| rule_01 | USER_PROFILE | DELETE | account_service / account_N (incl. read/regional/reporting/failover replicas in SQL) | VERIFY_RECORD_ABSENT always (32/32 cases); FINDING+DELETE when present | yes |
| rule_02 | SECONDARY_IDENTIFIER | DELETE | (not observed; possibly old email/phone rows) | — | no |
| rule_03 | SEARCH_INDEX_ENTRY | DELETE | search_service / search_N | REPORT_REMAINING_RECORD, DELETE, VERIFY_ABSENT | 12 |
| rule_04 | CACHE_ENTRY | DELETE | cache_service / cache_N — only in noise activity, never in text evidence | — | no (decoy) |
| rule_05 | SUPPORT_MESSAGE (shared context) | REDACT | support_platform / support_N | REPORT_EXPOSED_PII, REDACT, VERIFY_REDACTED | 5+3 |
| rule_06 | SUPPORT_ATTACHMENT (only subject) | DELETE | support_platform / support_N (attachments), object_storage / object_N | REPORT_REMAINING_RECORD, DELETE, VERIFY_ABSENT | 3 (case_07 support_001, case_10 support_002) |
| rule_07 | ANALYTICS_PROFILE (attributable) | ANONYMIZE | analytics_platform / analytics_N | REPORT_EXPOSED_PII, ANONYMIZE, VERIFY_ANONYMIZED | 5+12 |
| rule_08 | PRODUCT_TELEMETRY | ANONYMIZE | analytics_platform? | — | no |
| rule_09 | USER_EXPORT | DELETE | export_service / export_N (activity target object_store) | REPORT_REMAINING_RECORD, DELETE, VERIFY_ABSENT | 2 |
| rule_10 | MARKETING_PROFILE | DELETE | marketing_platform / marketing_N (only marketing_001, evidence_60); case_12 shows an analytics_platform contact with `email_opt_in=true` treated as DELETE | REPORT_REMAINING_RECORD, DELETE | 1 (case_12) |
| rule_11 | EMAIL_DELIVERY_LOG | REDACT | email_delivery_service / email_delivery_N — only noise activity; never in text evidence | — | no (decoy) |
| rule_12 | SECURITY_AUDIT_LOG (in retention) | RETAIN | security_service / audit_record_N (`retention_until` in evidence) | VERIFY_RECORD_PRESENT (24/32 cases) | yes |
| rule_13 | LEGAL_HOLD_RECORD (active hold) | RETAIN | legal_service / legal_hold_N (10 activity rows, evidence `retained_order_records`, legal_retention_register pdf) | VERIFY_RECORD_PRESENT | no |
| rule_14 | BACKUP_ARCHIVE (restore blockable) | RETAIN + block | backup_service / backup_N (`restore_allowed`, `eligible`, `deletion_block`) | REPORT_RESTORE_RISK, BLOCK_RESTORE, VERIFY_RESTORE_BLOCKED | 3+6 |
| rule_15 | ACCOUNT_TOMBSTONE | REDACT (keep user_id) | identity_service / tombstone_N (`deleted_customer_references`, subject_reference=user_id) | REPORT_EXPOSED_PII, REDACT, VERIFY_REDACTED | case_31/32 |
| — | (data flow, not a rule) | disable | integration_service / data_flow_N (`connector_subscriptions.enabled`, connector heartbeat) | REPORT_ACTIVE_DATA_FLOW, DISABLE, VERIFY_DISABLED | 6+9 |
Evidence explicitly labels categories: `record_type` values USER_PROFILE, SECURITY_AUDIT_LOG, SEARCH_INDEX_ENTRY, SUPPORT_MESSAGE, DATA_FLOW, ANALYTICS_PROFILE, BACKUP_ARCHIVE, USER_EXPORT, LEGAL_HOLD_RECORD (in logs like notification_delivery_20260315.log and JSON).

---

## 4. Eval request population (from these tables)
- reported_status: COMPLETE 254, PARTIALLY_COMPLETE 152, NOT_STARTED 112.
- requested_at 2026-01-05..2026-09-24; audit_at 2026-01-29..2026-10-01; audit_at - requested_at 10–29 days.
- Request texts are 3-sentence templates (65 distinct sentences, 375 distinct texts) in EN/FR/ES/PT/KO/JA. **Exactly 10 non-deletion texts: case_533..542** (phone update, stop promo emails, portability download, login reset "Do not close", surname fix, "remove me from marketing lists only", access request, invoice copy, change email, copy of info "don't delete"). They match the 10 CLASSIFY_REQUEST rows. All other 508 are deletion requests (beware "remove me from marketing lists only" contains "remove").
- **audit_at cohorts**: 46 groups of 10 cases share audit_at == capture time of one evidence file (gap 0 h for evidence_08/09/10/13…/48, ~0.3–0.9 h for service_readback/inventory series 62–93). The 12 image/PDF cases have audit_at = capture + 26 h. => each cohort's "key" evidence is the newest file at/just before audit_at; later files must be ignored (e.g. evidence_02 captured 09-17 shows account_5684 ACTIVE with full PII for user_26, but sample case_26 (audit 09-15) is COMPLETE).
- case_543..550 (users 543..550) look like the tombstone family (like sample case_31/32; tombstone_3963/7389/8774/8095/3745/205/946/8648 have activity rows 09-02..09-08; 4 policy-completed, 4 failed).

---

## 5. Sample gold cases — users, identifiers, activity (evidence never = activity)
**Gold evidence_id values are ONLY `evidence_NN` (75 non-empty) or '' (118). No activity_id or audit_id is ever cited**, even where activity is the only link. Findings cite the evidence file; verification in COMPLETE cases cites evidence; remediation + post-remediation verification use ''.

| case | user | identifiers of note | gold status | activity rows on gold resources (result) |
|---|---|---|---|---|
| 01 | user_01 Amina El-Masri | — | COMPLETE | 3342 account_001 DELETE SUCCESS "reported…completed" |
| 02 | user_02 Mateo Ríos (dup name user_262) | — | COMPLETE | 3376 account_002 PARTIAL "could not confirm" (still ABSENT) |
| 03 | user_43 Louis Fontaine | — | COMPLETE | 3851 account_7566 SUCCESS; 3852 analytics_9406 Policy SUCCESS |
| 04 | user_04 Thandiwe Ndlovu (dup name) | — | COMPLETE | 3463 analytics_901 SUCCESS (account_004 no row) |
| 05 | user_05 | — | INCOMPLETE | 3482 account_005 SUCCESS + 3483 failover-replica checkpoint -> remains |
| 06 | user_06 Jonas Berg | decoys joana.berg/jonas.berglund | INCOMPLETE | 3545 account SUCCESS; 3546 search_001 FAILED |
| 07 | user_07 Priya Raman | decoy p.ramanathan | INCOMPLETE | 3590 account SUCCESS; support_001 no row; 4007 LINK object_19 (Feb, for eval case_61) |
| 08 | user_08 Gabriel Costa (dup) | — | INCOMPLETE | 3554 account SUCCESS; 3555 export_001 FAILED |
| 09 | user_61 Kojo Appiah | — | INCOMPLETE | 3703 account_3960 FAILED (ABSENT anyway); 3709 CHECK_RESTORE backup_4978 |
| 10 | user_10 | old: nadia.ionescu (request), nadia.petrescu | INCOMPLETE | 3595 account SUCCESS; 3596 support_002 SUCCESS (yet PRESENT) |
| 11 | user_32 Tomasz Novak | — | INCOMPLETE (14 steps) | 3801 acct; 3814 search FAILED; 3815 support REDACT FAILED; 3816 analytics FAILED; 3817 CHECK flow |
| 12 | user_12 Min-jun Kim | old email minjun.kim90 + OLD HASH used in evidence | INCOMPLETE | 3432 acct SUCCESS; 3435 analytics_9914 DELETE FAILED |
| 13 | user_33 | — | INCOMPLETE | 3739 acct FAILED; 3752 support DELETE FAILED; 3756 search FAILED |
| 14 | user_37 | — | INCOMPLETE | 3686 acct; 3690 CHECK_RESTORE backup_3870 |
| 15 | user_15 | old phone | INCOMPLETE | 3382 acct; 3386 CHECK flow data_flow_9846 |
| 16 | user_53 | — | INCOMPLETE | 3571 acct_994 FAILED; 3577 replication checkpoint; 3580 search_1007 SUCCESS (still PRESENT) |
| 17 | user_17 | (also eval case_46) | INCOMPLETE | 3383 acct FAILED; 3385 CHECK_RESTORE backup_3245 |
| 18 | user_50 | old phone | INCOMPLETE (14) | 3732; 3744; 3747; 3751; 3753 |
| 19 | user_19 | — | INCOMPLETE | 3323 acct PARTIAL; 3329 support REDACT FAILED; 3332 search FAILED |
| 20 | user_48 | — | INCOMPLETE | 3734 acct FAILED; 3745 CHECK flow; 3750 search FAILED |
| 21 | user_21 | — | COMPLETE | 3661 acct SUCCESS; 3665 analytics Policy |
| 22 | user_51 | — | INCOMPLETE | 3573 acct; 3578 analytics FAILED; 3581 search FAILED |
| 23 | user_23 | — | INCOMPLETE | 3662 acct FAILED; 3667 export FAILED; 3671 search FAILED |
| 24 | user_24 | — | INCOMPLETE | 3599 acct SUCCESS; 3608 replication checkpoint (account REMAINS); 3610 search SUCCESS (REMAINS) |
| 25 | user_25 | old phone | COMPLETE | 3597 acct FAILED (ABSENT); 3602 analytics Policy |
| 26 | user_26 | — | COMPLETE (6 verify) | 3600 acct FAILED; 3603/3605/3606/3607 Policy (analytics, support redact, flow disable, block restore) |
| 27 | user_27 | — | COMPLETE | 3530; 3533/3536/3537/3540 Policy |
| 28 | user_28 | decoy smartinez6461.jr | COMPLETE | 3529 acct FAILED; 3534/3535/3538/3539 Policy |
| 29 | user_29 | old email noah.f438085 (request) | INCOMPLETE (14) | 3532; 3541 CHECK; 3542; 3543; 3544 |
| 30 | user_30 | old email camille.bernard86 (request) | INCOMPLETE (14) | 3465; 3467 CHECK; 3468; 3469; 3470 |
| 31 | user_541 | tombstone_440 redacted | COMPLETE | 3682 acct; 3687 tombstone Policy |
| 32 | user_542 | tombstone_9178 still has PII | INCOMPLETE | 3685 acct PARTIAL; 3692 tombstone REDACT FAILED |

Gold structure invariants (from samples): every authorized case ends with VERIFY_RECORD_ABSENT on the primary account; audit_record VERIFY_RECORD_PRESENT appears in 24/32 (whenever a security audit record exists for the user); verification order = account, search/export/support-delete, audit_record PRESENT, REDACTED, ANONYMIZED, DATA_FLOW_DISABLED, RESTORE_BLOCKED; remediation order = DISABLE_DATA_FLOW / BLOCK_RESTORE first, then DELETE (account, search, support, export), then REDACT, then ANONYMIZE; findings order ≈ REMAINING (account, search…), EXPOSED_PII (analytics, then support), ACTIVE_DATA_FLOW / RESTORE_RISK last. Compliant resources in an INCOMPLETE case still get a post-remediation VERIFY step with '' (e.g. case_06 account_006, case_09 audit_record_4902) — note samples 01–10 omit audit_record (no audit record in their evidence).

---

## 6. Practical checklist for the solver
1. Normalise request email (`strip().lower()`), resolve against current + all historical emails; collect all historical hashes/phones.
2. Link evidence only through exact full-token identifiers (emails, sha256 hashes incl. old ones, phones incl. old ones, `user_NN` refs, resource ids), grouping log lines by trace_id/requestId.
3. Use LINK_RESOURCE_IDENTITY rows to decode the 12 image/PDF evidence files.
4. From activity, take only deletion-worker run rows with `event_time <= audit_at` (and normally >= requested_at): primary account id, Policy-completed (compliant), received-final-result/check/replication/repopulate (violations), CLASSIFY (NOT_APPLICABLE).
5. Decide state from evidence captured `<= audit_at`; ignore reported_status/reported_result; ignore evidence & activity after audit_at.
6. Cite evidence_NN only (never activity_id/audit_id, matching gold), '' for remediation/post-remediation verification.
