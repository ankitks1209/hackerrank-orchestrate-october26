# 07 — Full trace of sample gold answers, case_01 .. case_12

Sources: `dataset/sample_deletion_requests.csv`, `dataset/sample_output.csv` (via `00_sample_dump.txt`),
`user_identities.csv`, `user_audit_log.csv`, `system_activity.csv`, `deletion_rules.csv`,
`evidence_files.csv`, and every evidence file that mentions the subjects. Everything below comes from
participant-facing data only.

---------------------------------------------------------------------------------------------------

## 0. Global facts these 12 cases establish

1. **Two case families exist.**
   * **Hand-crafted family (case_01, 02, 04–08, 10):** user ids `user_0N`/`user_10`. Resource ids use a 3-digit
     convention (`account_00N`, `search_001`, `support_001`, `support_002`, `export_001`, `analytics_901`).
     The activity rows use the distinctive template text "Deletion worker reported the requested operation as
     completed. **Target resource: X.**" (only 12 rows use it: activity_3342, 3376, 3463, 3482, 3483, 3545,
     3546, 3554, 3555, 3590, 3595, 3596). Evidence comes from a dedicated set of files, evidence_54..61
     (`customer_accounts_failover_replica_20260902.sql`, `security_retention_extract.pdf`,
     `customer_analytics_report_20260907.json`, `customer_search_primary_20260910.sql`,
     `delivery_correction_attachment.pdf`, `customer_export_jobs_20260914.json`, `marketing_profile_console.png`,
     `support_replica.log`). These cases have **no security audit record**, so there is no
     `VERIFY_RECORD_PRESENT` for security_service (this explains case_06).
     Other hand-crafted subjects are in the **eval** set: user_03 Oliver Bennett → case_45 (audit_record_003,
     evidence_55 PDF + evidence_37 PNG + activity_4010); user_09 Kwame Mensah → case_63 (marketing_001,
     evidence_60 PNG + activity_4008). (The original hand-crafted case_09 was apparently Kwame/marketing. The
     sample case_09 is now a generated case.)
   * **Generated family (case_03, 09, 11, 12, and 13–32):** user ids do NOT match the case number
     (case_03→user_43, case_09→user_61, case_11→user_32, case_12→user_12). The activity template text is
     "Deletion worker submitted primary profile account_X …", "Policy action completed for X.",
     "Deletion worker received the final result for X from Y.", "Connector status check confirmed that data
     flow X remains enabled.", "Restore-access check confirmed that archive X can still be restored."
     Evidence is the batch files evidence_01..53 and evidence_62..94. **Each batch file serves every case
     that shares its audit_at**. For example, evidence_94 (captured 2026-09-26T10:38:56Z) serves every case
     with audit_at 2026-09-26T11:00Z: case_03, 18, 20, 43, 44, 47, 48, 49, 51.

2. **email_hash = sha256(lowercase email)** (verified: amina.elmasri@gmail.com → d4e1f59a…; the historical
   hash for minjun.kim90@gmail.com is 44a65154…, which matches audit_283.old_value). You can compute the
   historical hashes yourself, but the audit log also stores them as `email_hash` rows.

3. **Citation rule:** a finding or COMPLETE-case verification cites the evidence **file whose `captured_at` ≤
   `audit_at`** and that shows the resource's state. When several qualify, the gold picks the file that names
   the resource and is closest to audit_at. Gold prefers an evidence file over a system_activity row, even
   when an activity row states the same thing (case_09 cites evidence_93, not activity_3709; case_11 cites
   evidence_03, not activity_3817). The comparison is inclusive: case_11 evidence_03 was captured at
   2026-10-01T12:00:00Z, the same instant as audit_at.

4. **A file captured after audit_at cannot be cited, even when its individual log lines are timestamped
   before audit_at** (case_09: evidence_06 is captured 2026-09-18T11:55:24Z, but its lines about user_61 are
   at 2026-09-16T08:52–08:57, before the 09:00 audit). However, **resources discovered only in such a file
   still appear in gold as future verification steps with empty evidence_id**. Case_09's `audit_record_4902`
   appears only in evidence_06, and gold still includes `VERIFY_RECORD_PRESENT audit_record_4902`. So
   discovery may use lines with ts ≤ audit_at, but citation must use files with captured_at ≤ audit_at.

5. **Mapping from required action to step ops (confirmed across the 12 cases):**

   | category / evidence state | finding | remediation | verification |
   |---|---|---|---|
   | DELETE category still present (account, search, export, support attachment, hash-only contact record) | REPORT_REMAINING_RECORD / PRESENT | DELETE_RECORD / ABSENT | VERIFY_RECORD_ABSENT |
   | REDACT category (support message) with identifiers | REPORT_EXPOSED_PII / PRESENT | REDACT_RECORD / REDACTED | VERIFY_RECORD_REDACTED |
   | ANONYMIZE category (analytics profile) with identifiers | REPORT_EXPOSED_PII / PRESENT | ANONYMIZE_RECORD / ANONYMIZED | VERIFY_RECORD_ANONYMIZED |
   | connector enabled | REPORT_ACTIVE_DATA_FLOW / ACTIVE | DISABLE_DATA_FLOW / DISABLED | VERIFY_DATA_FLOW_DISABLED |
   | backup restore_allowed / eligible | REPORT_RESTORE_RISK / ACTIVE | BLOCK_RESTORE / BLOCKED | VERIFY_RESTORE_BLOCKED |
   | security audit record (RETAIN) | none | none | VERIFY_RECORD_PRESENT |
   | account already absent | none | none | VERIFY_RECORD_ABSENT (always included) |
   | analytics already anonymized (all ids null) | none | none | VERIFY_RECORD_ANONYMIZED |

6. **The deletion worker's attempted operation type tells you the policy category, even though its result
   is only a claim.** Across cases 11 and 12 the worker op equals the gold remediation op:
   search_052 DELETE_RECORD, support_864 REDACT_RECORD, analytics_2034 ANONYMIZE_RECORD, and
   **analytics_9914 DELETE_RECORD (case_12)**. CHECK_DATA_FLOW / CHECK_RESTORE_ACCESS rows mean "still
   enabled" / "can still be restored". The `reported_result` (SUCCESS/FAILED/PARTIAL) is uncorrelated with
   truth:
   * account_3960 FAILED → actually absent (case_09).
   * account_002 PARTIAL → absent (case_02).
   * account_005 SUCCESS → still present in the failover replica (case_05).
   * support_002 SUCCESS → still present in the support replica (case_10).
   * search_001 FAILED → present (case_06).
   * export_001 FAILED → present (case_08).
   * analytics_9914 FAILED → present (case_12).

7. **Ordering** follows the problem statement exactly (confirmed in case_11 and case_12):
   phase (FINDING < REMEDIATION < VERIFICATION). Within a phase, sort by the operation's position in the
   table, then by system_id, then by resource_id.
   * Finding op order: REMAINING_RECORD, EXPOSED_PII, ACTIVE_DATA_FLOW, RESTORE_RISK.
   * Remediation op order: DISABLE_DATA_FLOW, BLOCK_RESTORE, DELETE, REDACT, ANONYMIZE. Flows and restores
     come first, which satisfies "disable flows before changing records".
   * Verification op order: ABSENT, PRESENT, REDACTED, ANONYMIZED, DISABLED, BLOCKED.
   * Case_12 check: VERIFY_ABSENT account_service < VERIFY_ABSENT analytics_platform (string compare
     "account" < "analytics"), then VERIFY_PRESENT security.
   * Case_11 check: EXPOSED_PII analytics_platform before support_platform. VERIFY_ABSENT account_service
     before search_service.

8. **INCOMPLETE verification set** = the account (always VERIFY_RECORD_ABSENT, even if it is already absent),
   plus the security audit record (VERIFY_RECORD_PRESENT, if one exists for the subject), plus every
   remediated resource with its target state. All of these use `evidence_id=""`, including resources that
   are already compliant. **COMPLETE verification** = the same set (account, audit record, plus
   already-compliant analytics/support/flow/backup/tombstone), each with its own citing file.

9. **Data in the account's failover replica counts as account_service/account_X** (case_05). The
   system_id is the logical service, not the replica. The replication SYNC row (activity_3483, "final
   checkpoint") is not treated as an active data flow.

---------------------------------------------------------------------------------------------------

## 1. Per-case traces

### case_01 — amina.elmasri@gmail.com → COMPLETE (1 step)
* Request (EN): "would like it closed… remove the profile and the personal details". This is a deletion
  request.
* Identity: user_01 Amina El-Masri, +971 50 482 7316, hash d4e1f59a…. No audit_log rows.
* Activity: activity_3342 2026-08-20T16:41:43Z DELETE_RECORD account_001 SUCCESS. No other rows.
* Evidence: evidence_54 `customer_accounts_failover_replica_20260902.sql`, captured 2026-09-02T23:00Z ≤
  audit 2026-09-03T11:30Z. It has tables `customer_profiles_primary` and `customer_profiles_failover_replica`.
  account_001 is in **neither**, so it is ABSENT.
* Gold: `VERIFY_RECORD_ABSENT account_service/account_001 evidence_54`.
* Decoy: account_8741 **Karim El-Masri** karim.elmasri@gmail.com (same surname, different email and user).
* Why there is no security audit verify: this is a hand-crafted case and no audit record exists for user_01
  anywhere.
* The resource id account_001 comes only from activity_3342 (user_01 ↔ account_001 by convention). Nothing
  in the evidence names it; it is proven absent because it is missing from the snapshot.

### case_02 — mateo.rios@outlook.com → COMPLETE (1 step)
* Request (ES): "tried to delete my account yesterday, error page… check if any data remains and complete
  the deletion". This is a deletion request.
* Identity: user_02 Mateo Ríos (note the accent), +34 612 847 593.
* Activity: activity_3376 DELETE account_002 **PARTIAL** ("could not confirm the final state"). This is a
  claim only.
* Evidence: evidence_54 (captured 09-02T23:00 ≤ audit 09-04T15:00). account_002 is absent from both
  primary and failover → COMPLETE.
* Trap: reported_status PARTIALLY_COMPLETE plus PARTIAL activity, but the truth is COMPLETE.
* Decoy: account_9116 **Mateo Rios Gil** m.rios.gil@outlook.com (a fuzzy name match). Do not report it.

### case_03 — l.fontaine46@yahoo.com → COMPLETE (3 steps, all evidence_94)
* Request (FR): "suppression définitive… examine current and former identifiers". This is a deletion
  request.
* Identity: **user_43** Louis Fontaine, +33 6 80 08 96 38. No audit_log rows.
* Activity (batch 2026-09-15 09:47–10:53Z, just before reported_at 2026-09-15T11:00Z):
  * activity_3851 DELETE account_7566 SUCCESS.
  * activity_3852 ANONYMIZE analytics_9406 SUCCESS.
* Evidence: evidence_94 `resource_lookup_trace_20260926_103856.log` (captured 2026-09-26T10:38:56Z ≤ audit
  2026-09-26T11:00Z):
  * L18–19: `account_7566 lookup_key=l.fontaine46@yahoo.com rows=0 http_status=404` → ABSENT.
  * L34–35: `audit_record_2016 lookup_key=user_43 rows=1 subject_reference=user_43
    event_code=IDENTITY_CHANGE_RECORDED retention_until=2034-09-30` → PRESENT (rule_12 RETAIN).
  * L42–43: `analytics_9406 lookup_key=null customer_reference=null email=null phone=null email_hash=null
    audience_cohort=general_shopper` → ANONYMIZED.
* Gold: VERIFY_ABSENT account_7566, VERIFY_PRESENT audit_record_2016, VERIFY_ANONYMIZED analytics_9406, all
  citing evidence_94.
* **Hard part: linking analytics_9406 to user_43.** No identifier links it (every field is null). The only
  link is the deletion-worker batch. The same file holds other null analytics records: **analytics_5589**
  (L20–21, read one second after account_7566, which is a misleading adjacency) and analytics_2265. Batch
  rows:
  * activity_3849 account_2064 (charlotte.wright, user_42, case_44)
  * activity_3850 account_6523 (leonie's March account, a re-submission decoy)
  * activity_3851 account_7566 (case_03)
  * activity_3852 analytics_9406
  * activity_3853 analytics_5589
  * then user_42's support_1066 REDACT, data_flow_223 DISABLE and backup_6266 BLOCK

  Inside a batch the worker emits account deletes first, then policy actions grouped by op type. Within an
  op type the order follows **case order** (case_03 before case_44), not resource id order. The same
  pattern holds in batch 3597–3607: accounts 3136 (case_25), 4842, 5334 (case_24), 5684 (case_26), 7225,
  then analytics_1895 → case_25 and analytics_4566 → case_26, both matching gold. Heuristic: the Nth
  ANONYMIZE in a batch belongs to the Nth case (by case_id) in that batch that needs analytics. A simpler
  heuristic, "the ANONYMIZE row immediately after this case's account DELETE row" (3851 → 3852), also gives
  9406 here. Use the batch as the link, together with the null-identifier readback in a file ≤ audit.
* Decoys: l.fontaine02@yahoo.com (account_11973), jules-fontaine@proton.me and ifontaine7861@gmail.com in
  evidence_53 (captured 09-30, after audit anyway). Also hugo.fontaine@gmail.com, arthur-fontaine83@proton.me
  and fontaine.manon@gmail.com, which are other eval subjects.

### case_04 — thandiwe.n@gmail.com → COMPLETE (2 steps)
* Request: "deleting my account. You can keep anonymous statistics, but nothing in analytics should still
  point back to me". This is a deletion request with an analytics focus.
* Identity: user_04 Thandiwe Ndlovu. Decoy subject: **thandiwe.m6866@zoho.com** (a different user, case_23).
* Activity: **no row for account_004 at all.** activity_3463 2026-08-27T08:47:41Z ANONYMIZE analytics_901
  SUCCESS (between requested 08-25 and reported 08-27T08:54). It is a hand-crafted row.
* Evidence:
  * evidence_54 (09-02T23:00 ≤ audit 09-07T10:20): account_004 is in neither table → ABSENT.
  * evidence_56 `customer_analytics_report_20260907.json` (captured 09-07T09:45 ≤ audit 10:20):
    analytics_901 has user_id/email/phone/email_hash all null → ANONYMIZED.
* Gold: VERIFY_ABSENT account_004 evidence_54, and VERIFY_ANONYMIZED analytics_901 evidence_56. The
  citation is **per resource**, choosing the file that shows that resource's state.
* Decoy: analytics_824 in the same JSON is still identifiable (dahl.freja@icloud.com, user_824). It belongs
  to someone else, so do not report it.
* Trap: the account_004 id appears in no participant file. It can only be produced by the user_0N ↔
  account_00N convention of the hand-crafted family. Linking analytics_901 is possible only through
  activity_3463, since the record is all-null.

### case_05 — leila.haddad@yahoo.com → INCOMPLETE (3 steps)
* Request: "deleted… received a confirmation, but the same email address is still recognized. Remove any
  remaining copy of my profile."
* Identity: user_05 Leila Haddad, +212 6 48 27 15 93.
* Activity: activity_3482 DELETE account_005 SUCCESS (08-28T09:11:01). activity_3483 SYNC_RECORD
  account_service→account_failover_replica account_005 SUCCESS ("final checkpoint").
* Evidence: evidence_54 (09-02T23:00 ≤ audit 09-08T13:40). account_005 is **present in
  `customer_profiles_failover_replica`** (ACTIVE, full PII, updated 09-02T22:45) and **absent from
  `customer_profiles_primary`**. This is replication drift.
* Gold:
  * FINDING REPORT_REMAINING_RECORD account_service/account_005 evidence_54.
  * REMEDIATION DELETE_RECORD account_005.
  * VERIFICATION VERIFY_RECORD_ABSENT account_005.
* Notes:
  * system_id stays `account_service` even though the copy lives in the replica table.
  * Only one resource is reported: replica rows are not separate resources.
  * The SYNC to the failover replica is NOT reported as REPORT_ACTIVE_DATA_FLOW (it is not a connector
    data_flow_ resource).
  * Rule_01 USER_PROFILE → DELETE.

### case_06 — jonas.berg@outlook.com → INCOMPLETE (4 steps)
* Request: "account page is gone, but my old profile still appears when I search… remove that search
  result".
* Identity: user_06 Jonas Berg.
* Activity: activity_3545 DELETE account_006 SUCCESS. activity_3546 DELETE search_001 **FAILED**.
* Evidence: evidence_57 `customer_search_primary_20260910.sql` (captured 09-10T08:45 ≤ audit 09-10T09:15):
  `search_001 'Jonas Berg' jonas.berg@outlook.com source_resource_id=account_006 indexed 09-09T22:12` →
  PRESENT. Account absence comes from evidence_54 (account_006 is not in either table).
* Gold:
  * FINDING REMAINING search_001 evidence_57.
  * REMEDIATION DELETE search_001.
  * VERIFICATION VERIFY_ABSENT account_006, then VERIFY_ABSENT search_001 (account_service <
    search_service).
* **Why there is no security audit verify:** hand-crafted family, and no audit record exists for user_06
  in any file. Include VERIFY_RECORD_PRESENT only when an audit record for the subject is actually found.
* Decoys in the same table: search_8814 **Jonas Berglund** jonas.berglund@outlook.com, and search_4203
  **Joana Berg** joana.berg@outlook.com. Use exact email matching; prefix or fuzzy name matching would
  produce false findings.
* Rule_03 SEARCH_INDEX_ENTRY → DELETE.

### case_07 — priya.raman@gmail.com → INCOMPLETE (4 steps)
* Request: "delete my account and the identity document I sent to support while resolving a delivery
  issue".
* Identity: user_07 Priya Raman, +91 98765 73142.
* Activity: activity_3590 DELETE account_007 SUCCESS. **No activity for support_001**: the workflow never
  touched it.
* Evidence: evidence_58 `delivery_correction_attachment.pdf` (captured 2026-09-12T07:30 ≤ audit 08:00). It
  is a "DELIVERY ADDRESS CORRECTION REQUEST", support reference **CS-4827 / support_001**, received
  18 Jun 2026. It contains Priya Raman, priya.raman@gmail.com, +91 98765 73142, order ORD-20264827, file
  delivery_address_correction.pdf, uploader customer. So the attachment belongs only to the subject →
  rule_06 SUPPORT_ATTACHMENT → DELETE.
* Gold:
  * FINDING REMAINING support_platform/support_001 evidence_58.
  * REMEDIATION DELETE support_001.
  * VERIFICATION VERIFY_ABSENT account_007, then VERIFY_ABSENT support_001.
* Decoys / time traps:
  * activity_4007 (2026-02-13) LINK_RESOURCE_IDENTITY says object_19 (delivery_confirmation_19.pdf)
    "belongs only to priya.raman@gmail.com and user_07". That belongs to eval **case_61** (same email,
    audit 2026-02-14). It is not in case_07's gold. The same user appears in several cases, so scope by
    audit time window.
  * support_3802 in evidence_38 has the same file name delivery_confirmation_19.pdf but was uploaded by
    lucia-garcia@proton.me.
  * account_7204 **Priya Ramanathan** p.ramanathan@gmail.com in evidence_54.
* The PDF text cannot be extracted with zlib (fonts are embedded). Read it visually or OCR it. The
  resource id is printed in the header.

### case_08 — gabriel.costa@proton.me → INCOMPLETE (4 steps)
* Request: "closed my account, but an old 'download your data' link still works. Delete that export file".
* Identity: user_08 Gabriel Costa.
* Activity: activity_3554 DELETE account_008 SUCCESS. activity_3555 DELETE export_001 **FAILED**.
* Evidence: evidence_59 `customer_export_jobs_20260914.json` (captured 09-14T15:40 ≤ audit 16:10):
  export_001 owner_email=gabriel.costa@proton.me, created 08-04, **expires_at 2026-10-04** (after audit),
  `download_available: true` → PRESENT.
* Gold:
  * FINDING REMAINING export_service/export_001 evidence_59.
  * REMEDIATION DELETE.
  * VERIFICATION VERIFY_ABSENT account_008, then VERIFY_ABSENT export_001.
  * Rule_09 USER_EXPORT → DELETE.
* Decoy: export_843 aoi-tanaka@gmail.com (expired, download_available false, another user).
* Note: an export counts as live when download_available=true and expires_at > audit_at.

### case_09 — k.appiah88@gmail.com → INCOMPLETE (5 steps)
* Request: generic permanent-deletion template.
* Identity: **user_61** Kojo Appiah, +233 24 468 1056. No audit_log rows.
* Activity:
  * activity_3703 2026-09-07T07:55 DELETE account_3960 **FAILED** (a claim).
  * activity_3709 2026-09-07T09:51 CHECK_RESTORE_ACCESS backup_4978 SUCCESS, "can still be restored".
  * The rest of that batch (analytics_5718, support_6334, data_flow_6846, backup_3933) belongs to
    **user_62** (another case). account_565 PARTIAL is also another case.
* Evidence:
  * evidence_93 `customer_data_inventory_20260916.sql`, captured 2026-09-16T08:37:39Z ≤ audit 09:00.
    `snapshot_scope` covers all 8 services.
    * `backup_restore_entries('backup_4978', NULL, 'k.appiah88@gmail.com', …, restore_allowed='1',
      '2026-09-16T07:59:54Z')` → restore risk.
    * account_3960 is not in `customer_profiles` → absent.
    * No security_audit_records row for user_61 in this file.
  * evidence_06 `structured_service_events_eu_west_20260918.log`, captured **2026-09-18T11:55:24Z > audit**,
    so it cannot be cited. Its lines from 2026-09-16 08:52–08:57 show:
    * audit_record_4902 (subject_ref user_61, rows=1, integrity passed);
    * backup_4978 restore_candidate_evaluated eligible=true deletion_block=false;
    * account_3960 lookup with k.appiah88 rows=0, 404.
* Gold:
  * FINDING REPORT_RESTORE_RISK backup_service/backup_4978 **evidence_93**. Not activity_3709 (older) and not
    evidence_06 (captured after audit).
  * REMEDIATION BLOCK_RESTORE backup_4978.
  * VERIFICATION VERIFY_ABSENT account_3960, VERIFY_PRESENT audit_record_4902, VERIFY_RESTORE_BLOCKED
    backup_4978, all with empty evidence.
* Why BLOCK and not DELETE: rule_14 BACKUP_ARCHIVE "Restore access can be blocked" → RETAIN the archive and
  block the restore.
* **Key trap:** audit_record_4902 is discoverable **only** in the post-audit file evidence_06, yet it is in
  gold. Discovery must not throw away post-capture files entirely. At minimum, use lines with
  ts ≤ audit_at from them, or at worst include them for future-verification resource ids. They must never
  be cited.
* Also: reported NOT_STARTED and the account delete FAILED, yet the account is actually absent, so there is
  no account finding.

### case_10 — nadia.ionescu@yahoo.com → INCOMPLETE (4 steps)
* Request: "I used this Yahoo address before changing the email… remove records linked to both old and
  current addresses".
* Identity: the request email is **historical**, not current. Chain from user_audit_log:
  * audit_121 (2025-12-13): nadia.ionescu@yahoo.com → nadia.petrescu@yahoo.com. audit_122 records the hash
    change 708ef564… → e407f542….
  * audit_238 (2026-04-12): → n.petrescu@yahoo.com. audit_239 records the hash change → 6385b5b5….
  * Current: user_10 **Nadia Petrescu**, n.petrescu@yahoo.com, +40 723 481 638.

  That makes three emails and three hashes, plus the name and phone.
* Activity: activity_3595 DELETE account_010 SUCCESS (09-02T10:08:37). activity_3596 DELETE support_002
  **SUCCESS** (09-02T10:09:01). Both are claims.
* Evidence: evidence_61 `support_replica.log` (captured 2026-09-17T22:00:19Z ≤ audit 2026-09-18T12:25Z).
  * L4–6: `lookup_key=nadia.ionescu@yahoo.com source=legacy_contact_index` → `resource_id=support_002
    rows=1`.
  * `deletion_marker_check resource_id=support_002 marker_found=false last_write=2026-09-07T10:01:00Z`. The
    record was still being written after the SUCCESS "delete".
* Gold:
  * FINDING REMAINING support_platform/support_002 evidence_61.
  * REMEDIATION DELETE.
  * VERIFICATION VERIFY_ABSENT account_010, then VERIFY_ABSENT support_002.
  * Treatment is DELETE, matching the worker's DELETE_RECORD op. It is a contact-index copy keyed by the
    historical email, not a shared conversation, so there is no REDACT.
* Decoys in the same file: support_5914 **nadia.popescu@yahoo.com**, support_4104 customer4104@yahoo.com.
  Elsewhere: a.ionescu1879@yahoo.com, katarina-ionescu@proton.me, nadia.popescu@gmail.com (case_398),
  dvorak.nadia@gmail.com.
* No data-flow finding, even though the record was rewritten on 09-07: no data_flow_ resource is
  evidenced.

### case_11 — novak.tomasz@icloud.com → INCOMPLETE (14 steps, findings cite evidence_03)
* Request: generic erase template.
* Identity: **user_32** Tomasz Novak, +48 601 623 422. No audit_log rows.
* Activity (batch 2026-09-12, before reported_at 09-12T12:00):
  * 3801 DELETE account_4248 SUCCESS.
  * 3814 DELETE search_052 FAILED.
  * 3815 REDACT support_864 FAILED.
  * 3816 ANONYMIZE analytics_2034 FAILED.
  * 3817 CHECK_DATA_FLOW data_flow_9522 "remains enabled".
* Evidence: evidence_03 `customer_account_handover_20261001.txt` (captured 2026-10-01T12:00:00Z ==
  audit_at; the inclusive rule applies). Lines have the form `ts | system | resource | CATEGORY | STATE |
  identifier`. Relevant lines:
  * account_4248 USER_PROFILE NOT_FOUND
  * analytics_2034 ANALYTICS_PROFILE IDENTIFIABLE
  * data_flow_9522 DATA_FLOW ACTIVE
  * search_052 SEARCH_INDEX_ENTRY FOUND
  * audit_record_9394 SECURITY_AUDIT_LOG FOUND user_32
  * support_864 SUPPORT_MESSAGE IDENTIFIABLE
* Gold:
  * Findings: REMAINING search_052; EXPOSED_PII analytics_2034; EXPOSED_PII support_864; ACTIVE_DATA_FLOW
    data_flow_9522. All cite evidence_03, not the activity rows.
  * Remediation: DISABLE data_flow_9522, DELETE search_052, REDACT support_864, ANONYMIZE analytics_2034.
  * Verification: ABSENT account_4248, ABSENT search_052, PRESENT audit_record_9394, REDACTED support_864,
    ANONYMIZED analytics_2034, DISABLED data_flow_9522.
* Rules applied:
  * rule_03 search → DELETE.
  * rule_05 support message → REDACT, so the finding is EXPOSED_PII, not REMAINING.
  * rule_07 analytics → ANONYMIZE, so the finding is EXPOSED_PII.
  * Connector enabled → disable.
  * rule_12 audit → RETAIN, so verify PRESENT.
* The handover file also contains other subjects' lines (case_13 noor-khalil, case_14 y.tanaka32, and
  case_38 with an **uppercase** SIPHO.MOKOENA@GMAIL.COM). Matching must be case-insensitive.
* Decoys: mnovak939594@fastmail.com (case_216), zofia-novak@gmail.com (case_437).

### case_12 — minjun.kim@gmail.com → INCOMPLETE (5 steps)
* Request: "I changed the email on this account before deleting it. Check that nothing tied to the **old
  address** was left behind, **even in systems that do not display the email**." This hints that the match
  is by hash.
* Identity: user_12 Min-jun Kim, current email minjun.kim@gmail.com (the request email is current).
  audit_282/283 (2026-05-18): the old email was **minjun.kim90@gmail.com** with old hash
  **44a65154bfd8e408852578fbd76813d094d1944f255ac1769ee81ba90492f10e**. The current hash is 6e34ae57….
* Activity:
  * 3432 DELETE account_9797 SUCCESS (08-25T11:07:59).
  * 3435 **DELETE_RECORD** analytics_9914 FAILED (08-25T12:53:51).
  * The neighbouring rows search_428 and search_4801 belong to case_35 / data_flow_1121 (user_13 / user_14).
* Evidence: evidence_01 `service_events_ap_south_20260915.log`, captured 2026-09-15T11:59:39Z ≤ audit
  12:00:00Z (21 seconds before):
  * L63: `audit_record_2945 … rows=1 correlation_key="user_12"` → PRESENT.
  * L73/76: lookup minjun.kim@gmail.com → `account_9797 rows=0 http_status=404` → ABSENT.
  * L92: `analytics_9914 event=contact_lookup_completed rows=1 email_opt_in=true
    correlation_key="44a65154…"`. This is the **old-email hash**. It is the only hash-keyed line in all
    logs, and `contact_lookup_completed` occurs exactly once in the corpus.
* Gold:
  * FINDING **REPORT_REMAINING_RECORD** analytics_9914 evidence_01.
  * REMEDIATION **DELETE_RECORD**.
  * VERIFICATION ABSENT account_9797, ABSENT analytics_9914, PRESENT audit_record_2945.
* **Why DELETE and not ANONYMIZE:** this is not an analytics *profile* (ANALYTICS_PROFILE → rule_07
  ANONYMIZE). It is a contact-lookup record keyed only by a hashed historical identifier, with an
  email_opt_in flag. That is a **SECONDARY_IDENTIFIER** (rule_02 Always DELETE), or a contact/marketing
  style record (rule_10 MARKETING_PROFILE Always DELETE). Either way the action is DELETE. Since the
  category is DELETE, the finding is REMAINING_RECORD rather than EXPOSED_PII. The worker's own attempted op
  (activity_3435 DELETE_RECORD) confirms the category. Contrast case_11 analytics_2034: ANONYMIZE op,
  IDENTIFIABLE profile → EXPOSED_PII + ANONYMIZE.
* Decoys: minjun.jung@outlook.com (user_402 in evidence_38; case_404), han.minjun86@icloud.com (case_274).

---------------------------------------------------------------------------------------------------

## 2. Things deliberately NOT in gold, and why

| Item | Case | Reason excluded |
|---|---|---|
| Karim El-Masri account_8741, Mateo Rios Gil account_9116, Priya Ramanathan account_7204 | 01/02/07 | Other users (different email, user_id). Name-similarity decoys in evidence_54 |
| search_8814 Jonas Berglund, search_4203 Joana Berg | 06 | Different emails. Prefix/fuzzy decoys |
| analytics_824 dahl.freja (identifiable) | 04 | Another user's record in the same JSON |
| export_843 aoi-tanaka | 08 | Another user's export, already unavailable |
| support_5914 nadia.popescu, support_4104 | 10 | Other users in the same log |
| object_19 / activity_4007 | 07 | Same subject but belongs to case_61 (Feb 2026). Out of this case's scope |
| support_3802 delivery_confirmation_19.pdf | 07 | Same file name, uploaded by lucia-garcia |
| activity_3709 CHECK_RESTORE_ACCESS | 09 | An evidence file (evidence_93) is closer to audit and is preferred |
| evidence_06 (all lines) as citation | 09 | captured_at 09-18 > audit 09-16 |
| account_3960 FAILED delete → finding | 09 | The snapshot shows it absent. FAILED is only a claim |
| SYNC_RECORD to account_failover_replica as ACTIVE_DATA_FLOW | 05 | Replication is not a connector flow resource. Only data_flow_* count |
| analytics_5589 / analytics_2265 (null) | 03 | Belong to other cases' batches (case_44, …) |
| l.fontaine02@yahoo.com etc. | 03 | Near-duplicate emails, and the file (evidence_53) is captured after audit |
| user_62 resources in the case_09 batch (backup_3933, data_flow_6846, support_6334, analytics_5718) | 09 | Different subject (customer_reference=user_62) |
| Security audit VERIFY | 01,02,04–08,10 | Hand-crafted family has no audit record for the subject |

---------------------------------------------------------------------------------------------------

## 3. Candidate general algorithm (derived from these 12 cases)

1. **Classify the request text** (multilingual). Non-deletion requests → NOT_APPLICABLE `[]`. All 12 cases
   here are deletion requests, including the ES, FR and "verify my deletion" phrasings.
2. **Resolve identity:** find the user whose current or any historical email matches the request email
   (case-insensitive). Collect the user_id, every email ever held (audit_log email rows, old and new),
   every hash (audit_log email_hash rows plus sha256 of each email), phone(s), and name(s).
3. **Gather candidate resources** for the subject:
   * (a) evidence rows, lines and records whose identifiers match exactly. Match on email (lowercased),
     hash, user_id as customer_reference/subject_reference/correlation_key/lookup_key, phone, or
     source_resource_id equal to the subject's account.
   * (b) system_activity deletion-worker rows in the batch window [requested_at, reported_at] that name
     resources already linked to the subject, and positional linking for null-identifier analytics
     records (see case_03).
   * (c) LINK_RESOURCE_IDENTITY rows, only when they are within the case's time scope.
   * (d) For the hand-crafted family, the account_00N convention.

   Use log lines with ts ≤ audit_at for discovery, even from files captured later (case_09
   audit_record_4902). Never use content timestamped after audit_at.
4. **Determine the state at audit_at** for each resource, from the latest evidence file with captured_at ≤
   audit_at that mentions it (or that proves absence by snapshot scope). Ignore reported_result.
   * Account: 404 / rows=0 / NOT_FOUND / missing from snapshot → absent. A row in ANY replica table →
     present (system_id account_service).
   * Search / export / attachment / contact copy: hit / FOUND / rows=1 / download_available → present.
   * Support message / analytics: any non-null direct identifier → exposed. All null → compliant.
   * Data flow: enabled=1/true/ACTIVE → active. Backup: restore_allowed=1 / eligible=true / ACTIVE →
     restore risk.
   * Audit record: rows=1 / FOUND → retained.
5. **Choose the category and action** from the record type: the table name / CATEGORY column, the event
   type (contact_lookup ⇒ secondary identifier), and the deletion worker's attempted op as a strong hint.
   Then apply deletion_rules.csv.
6. **Emit steps:**
   * If there are no violations → COMPLETE with verification steps (account ABSENT, audit PRESENT,
     compliant analytics/support/flow/backup/tombstone), each citing its proving file.
   * Otherwise → INCOMPLETE:
     * findings (with evidence ids);
     * remediation (flows/restores first);
     * verification of the account, the audit record (if any), and every remediated resource, all with
       empty evidence.
   * Sort by phase → operation order in the spec table → system_id → resource_id. Number from 1.
