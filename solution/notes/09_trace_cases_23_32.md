# 09 — Full trace of sample gold for case_23 … case_32 (plus case_21 for context)

All findings come only from participant-facing files under `dataset/`. Search helper:
`solution/notes/scripts/trace_23_32.py <term...>`. It does a word-boundary search of every text evidence file
(json/sql/log/txt, plus PDF zlib streams) and `system_activity.csv`.

---

## 0. Headline findings

1. **This sample family is self-contained.** Cases 21 and 23–30 are users `user_21`…`user_30`. Cases 31 and 32 are
   `user_541` and `user_542`. All of them have `audit_at = 2026-09-15T12:00:00Z` and `requested_at`/`reported_at`
   at exactly `T12:00:00Z`. Only three evidence files touch them:
   | file | manifest captured_at | role |
   |---|---|---|
   | `evidence_92` `records/service_resource_export_20260915_114455.json` | 2026-09-15T11:44:55Z (≤ audit) | **the only citable file for cases 21, 23–30** |
   | `evidence_51` `records/customer_data_snapshot_bundle_20260915.json` | 2026-09-15T12:00:00Z (**= audit_at**, inclusive) | the only citable file for cases 31/32 |
   | `evidence_02` `records/customer_data_snapshot_bundle_20260917.json` | 2026-09-17T12:00:00Z (**> audit**) | never cited. Holds the decoys and traps. It is the only place the INCOMPLETE cases' security records appear |
   Nothing else in `evidence/**` mentions these users' emails, phones, hashes or resource IDs. The same-name hits
   (for example 8 different "Thandiwe" users and 7 "Mthembu" emails) are all other people.
2. **evidence_92 holds exactly the gold-cited resources.** For COMPLETE cases (21, 25–28) it holds every verified
   resource. For INCOMPLETE cases (23, 24, 29, 30) it holds only the FINDING resources. The INCOMPLETE cases'
   accounts (`account_410`, `account_7012`, `account_4163`) and security records (`audit_record_4128/7095/3954/1707`)
   are deliberately missing from it. Those verification targets have to be discovered elsewhere:
   - **accounts**: only in `system_activity.csv` (the deletion_worker "submitted primary profile" row). No evidence file has them.
   - **security audit records**: only in `evidence_02` (file captured after audit_at, but the internal snapshot
     `captured_at` is `2026-09-15T12:00:00Z` = audit_at). The gold still lists them as VERIFY_RECORD_PRESENT with
     `evidence_id=""`. **So a later file can be used to discover a resource for a future verification step, but it
     can never be cited and can never create or reverse a finding.** The sibling trace of cases 01–12 found the same
     thing (case_09 `audit_record_4902`).
3. **Account linkage goes through the activity stream.** Every deletion case has one
   `DELETE_RECORD deletion_worker→account_service "Deletion worker submitted primary profile account_X"` row:
   - It falls **0.75–1.25 h before `reported_at`**, on the same day. Measured: 0.82, 1.01, 1.19, 0.85, 1.04, 1.23,
     0.88, 1.07, 1.23 and 0.91 h for cases 23–32.
   - Its `reported_result` mirrors `reported_status`: COMPLETE→SUCCESS, PARTIALLY_COMPLETE→PARTIAL, NOT_STARTED→FAILED.
     This held for all 21 sample cases that have such a row.
   - Within that window, the number of candidates with a matching result equals the number of deletion cases that share the
     same `reported_at` and `reported_status`. Non-deletion cases (case_536, case_539) get a `CLASSIFY_REQUEST` row instead.
   - Ties have to be broken by direct evidence or by cross-case elimination. Several remain unresolvable (see §3).
4. **The activity rows are claims, not truth. The evidence state wins in both directions:**
   - case_25, 26 and 28 have account DELETE `FAILED` (reported NOT_STARTED), but evidence_92 shows `404` → **COMPLETE**.
   - case_24's account and search DELETE are `SUCCESS` (reported COMPLETE). A later
     `SYNC_RECORD account_service→account_replication_cluster account_5334` row ("final checkpoint") recreated the account,
     and evidence_92 shows `200` with an email plus a search hit → **INCOMPLETE**.
   - case_30's account DELETE is `SUCCESS` (reported COMPLETE), but search, support and analytics are still identifying and
     a flow is enabled → INCOMPLETE.
5. **Step ordering** fits every one of the 32 samples. Sort by phase, then by the rank of the operation in the AGENTS §6.4
   tables, then by the system rank `account < export < search < analytics < support < integration < backup < identity`:
   - FINDING: REMAINING_RECORD < EXPOSED_PII < ACTIVE_DATA_FLOW < RESTORE_RISK
   - REMEDIATION: DISABLE_DATA_FLOW < BLOCK_RESTORE < DELETE_RECORD < REDACT_RECORD < ANONYMIZE_RECORD
   - VERIFICATION: ABSENT < PRESENT (security) < REDACTED < ANONYMIZED < DISABLED < BLOCKED

   This is why the FINDING order is analytics → support (both EXPOSED_PII, analytics ranks first), while the
   REMEDIATION and VERIFICATION order is support → analytics (REDACT before ANONYMIZE).
6. **The verification set is the same for COMPLETE and INCOMPLETE cases:** the account (ABSENT), every retained
   security record (PRESENT), and every other relevant resource in its required final state. Only `evidence_id` differs:
   it is the proving file for COMPLETE cases and `""` for INCOMPLETE cases.

---

## 1. Identity resolution (user_identities.csv + user_audit_log.csv)

| case | request email | user | current identity | history (audit_log) |
|---|---|---|---|---|
| 23 | thandiwe.m6866@zoho.com | user_23 Thandiwe Mthembu | +27 72 861 6082, hash 5a2cb16d… | none |
| 24 | keiko.nakamura@gmail.com | user_24 Keiko Nakamura | +81 90 2669 6684, hash dcbef21c… | none |
| 25 | s.yoon04@gmail.com | user_25 Soo-jin Yoon | +82 10 0616 2075 | audit_220: phone +82 10 6662 4968 → current (2026-03-29) |
| 26 | almeida.mariana@gmail.com | user_26 Mariana Almeida | +55 21 90180-9087 | none |
| 27 | ananya-nair@gmail.com | user_27 Ananya Nair | +91 97441 66195 | none |
| 28 | smartinez6461@gmail.com | user_28 Sofía Martínez | +34 744 502 860 | none |
| 29 | noah.f438085@outlook.com (**historical**) | user_29 Noah Foster | current **noah.f4380@outlook.com**, +1 (312) 555-0129, hash b1d07882… | audit_284 email noah.f438085→noah.f4380, audit_285 hash f377ccb4…→b1d07882… (2026-05-18) |
| 30 | camille.bernard86@outlook.com (**historical**) | user_30 Camille Bernard | current **camille.bernard@outlook.com**, +33 6 57 32 62 06, hash 81310fd2… | audit_280 email, audit_281 hash b891c158…→81310fd2… (2026-05-17) |
| 31 | a.eze08@gmail.com | user_541 Amara Eze | +234 803 052 7943 | none |
| 32 | addo.kofi@gmail.com | user_542 Kofi Addo | +233 24 991 1328, hash 4f4b9c98… | none |

Traps:
- For 29 and 30 the request email is the **old** email. `user_identities.csv` will not match it on the email column;
  you have to look it up through `user_audit_log.old_value`.
- In evidence_92 every live record for 29 and 30 is keyed by the **old** email. In evidence_02 the analytics rows for
  29 and 30 use the **current** email, phone and hash together with `user_id`.
- Several records carry only `customer_reference` / `subject_reference` = `user_NN` and no email at all (security,
  support, backup and connector rows). The internal user_id is therefore a primary join key.

---

## 2. Per-case trace

Notation: e92 = evidence_92, e51 = evidence_51, e02 = evidence_02 (later file, never cited).

### case_23: INCOMPLETE (reported NOT_STARTED). Remaining export and search records
Text: "delete this account, including the **downloadable archive** I requested earlier and any search result … Security
records can stay." The word "archive" here means the USER_EXPORT. **It is not a BACKUP_ARCHIVE.**
- e92 `export_service.exports`: `export_7364`, `owner_email=thandiwe.m6866@zoho.com`,
  `object_key=exports/export_7364/customer_data.zip`, observed 09:39:19Z. rule_09 USER_EXPORT=DELETE → **F1 REPORT_REMAINING_RECORD**.
- e92 `search_service.index_queries`: query thandiwe.m6866@zoho.com → hit `search_898`, observed 10:08:28Z. rule_03 → **F2 REPORT_REMAINING_RECORD**.
- Activity: activity_3667 export DELETE FAILED (12:38:47) and activity_3671 search DELETE FAILED (12:57:17), both on
  09-05 and both *after* reported_at 12:00. They agree with the evidence.
- R3/R4 DELETE export then search (both DELETE, so system rank decides: export < search).
- V5 `account_410` ABSENT. No evidence anywhere. The id comes only from activity_3662
  (`submitted primary profile account_410`, FAILED, 09-05T11:10:55Z, 0.82 h before reported_at).
  **There is no finding for it:** no evidence shows it present, and a FAILED claim alone is not a finding.
- V6/V7 export and search ABSENT. V8 `audit_record_4128` PRESENT. This record appears only in e02 (subject_reference
  user_23, `account_deletion_reviewed`). rule_12 RETAIN.
- Ambiguity: activity has three FAILED primary-profile candidates in the window: account_7015, account_410 and
  account_9155. They correspond to cases 23, 547 and 548, and no evidence anywhere links any of the three. Gold
  picked account_410 (the middle one by time). **This cannot be resolved from participant data.**

### case_24: INCOMPLETE (reported COMPLETE). The account was recreated by replication
- e92 account lookup `account_5334`: `status_code 200`, profile `{email: keiko.nakamura@gmail.com, others null}`.
  The account is present even though most fields are null. rule_01 → **F1 REMAINING account**.
- e92 search query keiko.nakamura@gmail.com → `search_5577` → **F2 REMAINING search**.
- Activity: activity_3599 account DELETE SUCCESS (10:59), then activity_3608 `SYNC_RECORD account_service→account_replication_cluster
  account_5334` ("Replication worker reported its final checkpoint", 12:45, after the delete), then activity_3610 search DELETE SUCCESS.
  The SUCCESS rows are false claims. Replication brought the account back.
  **Gold does NOT emit REPORT_ACTIVE_DATA_FLOW for the replication cluster**, because no `data_flow_*` resource or
  connector evidence exists. Only report flows that have a data_flow resource with enabled/active evidence.
- R: DELETE account then search, so the account goes first even though search is downstream. No dependency reordering was applied.
- V: account ABSENT, search ABSENT, `audit_record_7095` PRESENT (found only in e02, subject user_24, so its evidence is "").
- e02 also shows account_5334 ACTIVE at 09-15T12:00. It is consistent, but not citable.

### case_25: COMPLETE (reported NOT_STARTED, "privacy page still says my request failed")
- V1 `account_3136` ABSENT ← e92 lookup `status_code 404, profile null` (09:31:40Z). Activity_3597 says account DELETE **FAILED**.
  This is a false negative claim and the evidence wins.
- V2 `audit_record_451` PRESENT ← e92 security `subject_reference user_25`, `ACCOUNT_DELETION_RECORDED`,
  `retention_until 2031-12-31` (> audit_at, so within retention, rule_12).
- V3 `analytics_1895` ANONYMIZED ← e92 analytics row with `email/email_hash/phone/customer_reference` all null
  (cohort home_lifestyle). Activity_3602 ANONYMIZE SUCCESS 09-02T11:31:08.
- Linkage problem: nothing in any evidence ties account_3136 or analytics_1895 to user_25. It is time-window activity only.
  For 09-02, the candidates are accounts {3136, 5684} and analytics {1895, 4566}, shared with case_26. Gold assigns the
  earlier one in each pair to case_25. account_5684 links to user_26 through the e02 09-09 snapshot, which leaves 3136
  by elimination. The analytics pair stays a coin flip.

### case_26: COMPLETE (reported NOT_STARTED). "Old report said my account still existed"
- The "old report" is `e02` snapshot `captured_at 2026-09-09T12:00:00Z`, which shows `account_5684` customer_reference user_26,
  Mariana Almeida, `account_status ACTIVE`. It is superseded by e92 `account_5684 404` observed 2026-09-15T09:01:48Z, which is
  newer and still ≤ audit. The e02 file is also post-audit (captured 09-17), so it cannot be cited.
  **Rule: per resource, take the latest observation ≤ audit_at.**
- V1 account_5684 ABSENT (e92 404). V2 audit_record_5416 PRESENT (e92 user_26, PRIVACY_REQUEST_ACCEPTED, retain to 2032-06-30).
- V3 support_4715 REDACTED ← e92 ticket `customer_reference user_26`, `requester_email/name/phone null`, excerpt
  "Customer followed up about an order update." The order context is retained, so this is SUPPORT_MESSAGE rule_05 REDACT and the record is already compliant.
- V4 analytics_4566 ANONYMIZED (e92, all identifiers null). The link is by activity_3603 only.
- V5 data_flow_6244 DISABLED ← e92 connector `customer_events_connector`, `customer_reference user_26`, `enabled false`,
  `last_delivery_status stopped`.
- V6 backup_3120 BLOCKED ← e92 restore entry `customer_reference user_26`, `restore_allowed false`. rule_14 BACKUP_ARCHIVE is
  RETAIN, which means "keep but block": **a BACKUP is never deleted; its required state is BLOCKED.**

### case_27: COMPLETE (reported COMPLETE). "Audit the deletion as it stood when my request was reviewed"
- e92 account_3866 404 (09:59:48Z) → ABSENT. **Trap:** e02 has a snapshot `captured_at 2026-09-17T12:00:00Z`
  showing account_3866 / Ananya Nair **ACTIVE** again. That is after audit_at, so ignore it. The answer stays COMPLETE.
  The text explicitly asks for the state at review time (audit_at).
- audit_record_3830 PRESENT (user_27, IDENTITY_CHANGE_RECORDED, retain to 2034). support_4707 REDACTED (user_27, nulls).
  analytics_4574 ANONYMIZED. data_flow_2295 DISABLED (`analytics_identity_bridge`, user_27, enabled false).
  backup_5970 BLOCKED (user_27, restore_allowed false). All cite e92.
- The analytics_4574 vs analytics_6077 assignment between case 27 and case 28 is not determinable. Both are null-identity
  ANONYMIZE SUCCESS rows on 08-30, at 11:31:09 and 11:31:53. Gold gives 4574 to 27 and 6077 to 28. Time order does not help:
  case_28's account came first (10:46) but its analytics came second.

### case_28: COMPLETE (reported NOT_STARTED). The decoy search result with a similar email
- Decoy: e02 snapshot `captured_at 2026-09-15T09:00:00Z`, `search_service` `search_8168`, document `email
  smartinez6461.jr@gmail.com`, `display_name null`, `customer_reference null`. `smartinez6461.jr@gmail.com` is **not**
  in user_identities or the audit log. The subject is `smartinez6461@gmail.com`. This is a prefix or near-duplicate email
  that belongs to someone else, so it must be excluded. It also lives in a post-audit file, which is a second reason.
  Emails must match exactly (case-insensitively); substring or prefix matches are not enough. The e92 search
  section has no query for smartinez at all.
- V: account_5482 ABSENT (e92 404; activity_3529 FAILED was a false claim). audit_record_9265 PRESENT (SUBJECT_REQUEST_AUDITED,
  retain to 2033). support_2351 REDACTED (user_28, excerpt "Customer supplied contact details for a delivery query.", nulls).
  analytics_6077 ANONYMIZED. data_flow_2337 DISABLED (`support_profile_sync`). backup_838 BLOCKED. All cite e92.
- There is no search step and no NOT_APPLICABLE. The request text is a verification request, but it does authorize the
  deletion audit ("verify that my account was deleted").

### case_29: INCOMPLETE (reported NOT_STARTED). Historical email, active connector
Everything in e92 is keyed by the **old** email `noah.f438085@outlook.com`:
- F1 search_1993 REMAINING (query old email → hit). rule_03 DELETE.
- F2 analytics_5208 EXPOSED_PII (`email` = old email). rule_07 ANONYMIZE.
- F3 support_5281 EXPOSED_PII (`requester_email` = old email; excerpt order context). rule_05 REDACT.
- F4 data_flow_3827 ACTIVE (`analytics_identity_bridge`, `customer_email` old email, `enabled true`,
  `last_delivery_status delivered`). Activity_3541 CHECK_DATA_FLOW "remains enabled" confirms it.
- R5 DISABLE flow first (it can repopulate search and analytics), then R6 DELETE search, R7 REDACT support, R8 ANONYMIZE analytics.
- V9 account_7012 ABSENT. The id comes from activity_3532 only (FAILED, 08-30T11:06:57). It is not in any evidence and has no finding.
  V10 search ABSENT. V11 audit_record_3954 PRESENT (e02 only). V12 support REDACTED. V13 analytics ANONYMIZED. V14 flow DISABLED.
- The failed policy chain is CHECK_DATA_FLOW 12:57:49 → search 13:16:19 → support 13:35:48 → analytics 13:54:18,
  a constant step of about 18.5 min. Every one of those rows comes after reported_at.

### case_30: INCOMPLETE (reported COMPLETE). Same shape as 29, old email camille.bernard86@outlook.com
- F: search_9359 REMAINING, analytics_3697 EXPOSED_PII, support_6477 EXPOSED_PII (excerpt "Customer supplied contact
  details for a delivery query."), data_flow_8524 ACTIVE (`customer_events_connector`, enabled, delivered). All cite e92.
- R: DISABLE 8524, then DELETE 9359, REDACT 6477, ANONYMIZE 3697.
- V: account_4163 ABSENT (activity_3465 SUCCESS is the only source), search, audit_record_1707 PRESENT (e02 only), support, analytics, flow.
- The account DELETE was reported SUCCESS and is not contradicted, so there is no account finding. That still does not make the case complete.

### case_31: COMPLETE (reported COMPLETE). Tombstone already compliant
e51 (captured 2026-09-15T12:00:00Z, equal to audit_at, which counts as included):
- `account_service/customer_profiles` `records: []`. **An empty collection snapshot proves ABSENT** for account_4857,
  even though that id never appears in e51. The id comes from activity_3682 (SUCCESS 09-06T10:45:58). The other
  candidates in the window are eliminated by the post-audit evidence_03 handover: account_1810 → CHOI.JIHOON94 (case_40)
  and account_3677 → y.tanaka32 (case_14).
- `security_service` audit_record_6909, subject user_541, account_deletion_reviewed → PRESENT.
- `identity_service/deleted_customer_references` `tombstone_440`, subject_reference user_541, `name/email/phone/email_hash
  all null`, `account_status DELETED`. rule_15 ACCOUNT_TOMBSTONE REDACT, and it is already compliant → **VERIFY_RECORD_REDACTED**.
  The state is REDACTED, not ABSENT, because the tombstone keeps the stable `subject_reference`.
- Activity_3687 REDACT tombstone_440 SUCCESS agrees.
- Verification order: account ABSENT, security PRESENT, identity REDACTED. The tombstone comes after security because REDACTED ranks below PRESENT.

### case_32: INCOMPLETE (reported PARTIALLY_COMPLETE). Tombstone exposes PII
- e51 `tombstone_9178` subject_reference user_542 still has `name "Kofi Addo"`, `email addo.kofi@gmail.com`, `phone +233 24 991
  1328`, `email_hash 4f4b9c98…` (exactly the identity values). rule_15 → **F1 REPORT_EXPOSED_PII** (the record should remain,
  so this is not REMAINING_RECORD) → **R2 REDACT_RECORD** → V5 VERIFY_RECORD_REDACTED.
- Activity_3692 REDACT tombstone_9178 FAILED (13:00:07) agrees.
- V3 account_8858 ABSENT. The e51 profiles collection is empty, but the evidence is "" because the case is INCOMPLETE.
  The id comes from activity_3685 (PARTIAL, mirroring PARTIALLY_COMPLETE). Its rival account_2381 (also PARTIAL) is
  eliminated through evidence_03 → SIPHO.MOKOENA (case_38). V4 audit_record_7068 PRESENT (in e51).
- **The account is NOT deleted again and the tombstone is NOT deleted.** Only the tombstone is redacted.

### case_21 (context): COMPLETE
e92: account_6440 404 → ABSENT; audit_record_3737 (user_21, retain to 2034) → PRESENT; analytics_5335 null identifiers → ANONYMIZED.
The only analytics ANONYMIZE on 09-05 is 5335 (11:31:34), so the link is unambiguous.

---

## 3. Linkage feasibility table (what a solver can and cannot ground)

| resource class | how it links to the user | ambiguous? |
|---|---|---|
| search / export / support / connector carrying an email | exact email (current **or historical**) | no |
| security / support / backup / connector carrying `customer_reference`/`subject_reference=user_NN` | user_id | no |
| tombstone | subject_reference + identity fields | no |
| account (404 / empty-collection) | activity primary-profile row on reported_at day, 0.75–1.25 h before, result↔reported_status, then elimination | 23 (3-way), 28/29 (2-way), 25/26 (resolved only through e02's 09-09 snapshot) |
| analytics with all-null identifiers | activity `ANONYMIZE_RECORD … SUCCESS` around 11:31 on reported_at day | 25/26 and 27/28 coin flips |

The policy-action timing on the reported_at day looks clock-based:
- SUCCESS chain: ANONYMIZE / tombstone REDACT ~11:31, support REDACT ~11:38, DISABLE_DATA_FLOW ~11:45, BLOCK_RESTORE ~11:52.
- FAILED chain: starts ~12:38–13:00 and advances ~18.5 min per resource.
- Account primary profile: ~10:45–11:12.

These windows are useful features for clustering activity rows into a case.

Eval mirror: the tombstone family case_543 … case_550 (users 543–550, audit 2026-09-20T12:00:00Z) is the eval
analogue of 31/32. `evidence_52` (failover replica, captured 2026-09-20T12:00:00Z = audit) lists their
tombstones and security records. Some tombstones still hold PII (3745 user_548, 7389 user_550, 8095 user_546,
8648 user_544); 205, 946, 3963 and 8774 are clean. The same activity-based account linkage problem applies there.

---

## 4. Why each evidence_id

- Findings and COMPLETE verifications cite the **single file whose manifest `captured_at` ≤ audit_at and which
  contains the state-proving observation**. For this family that file is e92 (11:44:55Z) or e51 (12:00:00Z exactly).
  e02 is excluded by its manifest time (09-17), even though some internal snapshots inside it are dated ≤ audit.
  **Use the manifest `captured_at` for citability.**
- e51 cites an account as ABSENT through an empty collection, without naming the id.
- INCOMPLETE remediation and verification steps always have `""`. This includes already-compliant ones such as the
  account in case 23, 29 and 30, which have no citable evidence, and the account in case_32, which does have citable e51 evidence but still gets `""`.

---

## 5. Candidate general algorithm (consistent with all 32 samples)

1. **Intent.** Decide whether the text authorizes deletion. A request to verify or audit a deletion (cases 25–28) is still a deletion case.
2. **Identity.** Find the user by current or historical email, using a case-insensitive exact match. Collect all current and
   historical emails, phones and hashes, the name, and the user_id. Never match on a substring or prefix (`smartinez6461.jr`),
   and never match on name alone.
3. **Collect candidate resources:**
   - (a) Any evidence record (any capture time) whose identifiers or `*_reference` match.
   - (b) Activity rows: the primary-profile DELETE in [reported_at−1.3h, reported_at−0.7h] whose result matches
     reported_status, plus the policy-action rows on the reported_at day. Disambiguate with (a) and cross-case elimination.
4. **State at audit_at.** For each resource, take the latest observation with manifest `captured_at` ≤ audit_at. That
   observation sets the state and the citation. Later files may only *add* resources with an unknown state; they become
   future verification targets in INCOMPLETE cases. Activity results never set state, except as a weak fallback.
5. **Policy target per category:**

   | category | target state |
   |---|---|
   | USER_PROFILE / SEARCH / EXPORT / attachment / cache / marketing / secondary identifier | ABSENT |
   | SUPPORT_MESSAGE / EMAIL_DELIVERY_LOG / ACCOUNT_TOMBSTONE | REDACTED |
   | ANALYTICS / TELEMETRY | ANONYMIZED |
   | SECURITY_AUDIT (in retention) / LEGAL_HOLD | PRESENT |
   | DATA_FLOW | DISABLED |
   | BACKUP | BLOCKED |

6. **Violations:**
   - present where ABSENT is required → REPORT_REMAINING_RECORD
   - identifiers exposed where REDACTED or ANONYMIZED is required → REPORT_EXPOSED_PII
   - an enabled or delivered connector → REPORT_ACTIVE_DATA_FLOW
   - `restore_allowed true` → REPORT_RESTORE_RISK

   Only report violations that a citable observation proves. A FAILED activity claim with no evidence (account_410 /
   7012) is not a finding.
7. **Status.** Any violation → INCOMPLETE. Otherwise → COMPLETE, and every verify step must cite a proving file.
8. **Steps.**
   - FINDING: one per violation.
   - REMEDIATION: one per violation, mapped REMAINING→DELETE, EXPOSED→REDACT or ANONYMIZE (by category),
     ACTIVE→DISABLE, RESTORE→BLOCK.
   - VERIFICATION: **all relevant resources** in their target state. That always means the account ABSENT and every
     retained security record PRESENT, plus every remediated or already-compliant resource.
   - Sort by (phase, operation rank from the §6.4 tables, system rank account < export < search < analytics <
     support < integration < backup < identity).
   - evidence_id: the citing file for FINDINGs and for COMPLETE verifications; `""` otherwise.

### When does an INCOMPLETE verification list include already-compliant records?
- **The account (USER_PROFILE ABSENT) is always included.** That holds in all 32 samples, including INCOMPLETE cases
  where the account is not a finding (23, 29, 30, 32; also 06–10 and 12–15).
- **Retained security records are always included** when the user has one in any evidence file, even if that file is
  post-audit (23, 24, 29, 30). They are omitted only when no security record exists for the user anywhere, as with the
  hand-crafted cases 05–08 and 10.
- **The tombstone** is included (32).
- **No sample INCOMPLETE case has an already-compliant analytics, support, flow or backup record**, so the samples never test this.
  The COMPLETE and INCOMPLETE lists use an identical formula, and the generator plainly verifies compliant account and
  security records in INCOMPLETE cases. The most consistent guess is therefore **include them** (state = target,
  evidence ""). Treat this as an unverified rule.

### Exclusions recap
- `search_8168` (smartinez6461.jr, a near-duplicate email, in a post-audit file).
- e02's 09-17 account_3866 ACTIVE (after audit_at).
- e02's 09-09 account_5684 ACTIVE (superseded by the newer e92 404).
- The replication cluster in case_24 is not a data_flow resource, so it gets no flow finding.
- No remediation for accounts that are ABSENT, for already-REDACTED tombstones, or for retained security records.
- Backups are never deleted.
- Same-name other users (Thandiwe ×8, Mthembu ×7, "Camila Martínez" search_2274) are ignored.
