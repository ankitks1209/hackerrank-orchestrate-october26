# 10 — Completeness critic and reconciler

Scope: I read notes 00–09, re-checked the disputed claims against the raw `dataset/` files, and wrote stdlib prototypes in `solution/notes/proto/`. The prototypes read only participant files. `sample_output.csv` is used only to score them.

---

## 0. Headline findings

1. **The activity stream's template text, not `reported_result`, carries the per-resource truth for the generated family.** This covers samples 03, 09 and 11–32, and about 496 of 508 eval deletion cases.
   - Rows starting "Deletion worker received the final result for X", "Connector status check confirmed … remains enabled", or "Restore-access check confirmed … can still be restored" mark a **violation**.
   - Rows starting "Policy action completed for X" mark a **compliant** resource.
   - The row's `event_type` names the treatment: DELETE_RECORD, REDACT_RECORD, ANONYMIZE_RECORD, CHECK_DATA_FLOW / DISABLE_DATA_FLOW, CHECK_RESTORE_ACCESS / BLOCK_RESTORE, or RETAIN_RECORD.
   - A "Replication worker reported its final checkpoint for account_N" row means **the account still exists** (replica drift).
   - Validation results:
     - Samples: 49 of 49 linked rows agree with gold on finding versus compliant and on treatment. This includes case_12's analytics DELETE.
     - Eval vs SQL: 274 agree, 0 disagree (`proto/cross_sql.py`).
     - Eval vs log and JSON observations (latest in-window observation): 520 agree, 1 disagrees, and that one is a legal hold where PRESENT is the compliant state (`proto/cross_all.py`).
     - Accounts: a replication row means PRESENT in 52 of 52 cases. With no replication row the account was never observed PRESENT; 135 were ABSENT and 304 unobserved (`proto/acct_check.py`).
   - **The evidence is still required for citations.** Use the activity stream for discovery and classification, and evidence for the `evidence_id`. The two never disagreed.
2. **Linking rows to cases is solvable, refuting notes 09 and 03's "coin flip".** Three signals combine:
   - **Account row timing:** the "submitted primary profile" row falls 0.7–1.3 h before `reported_at`, and its result mirrors `reported_status` (COMPLETE→SUCCESS, PARTIALLY_COMPLETE→PARTIAL, NOT_STARTED→FAILED).
   - **Seconds fingerprint:** take each worker row's time minus its account row's time, in seconds, mod 60.
     - Compliant rows give a value in {9, 10, 39, 40, 41}, within 1000–4200 s.
     - Violation rows give a value in {20, 21, 22, 51, 52}, within 4800–10800 s.
     - This held for 100% of the sample rows (`proto/fingerprint.py`).
   - **Evidence elimination:** a row whose resource evidence names a different user is dropped, and propagation continues until stable.
   - **One extra tie-break:** apart from legal holds, the truth never mixes compliant "Policy action" rows with violations in one case.
   - `proto/solve_links.py` results:
     - All 24 of 24 generated-family sample accounts are correct, including case_23's three-way tie and the 25/26 and 28/29 pairs that note 09 called unresolvable.
     - Worker resources: 50 of 50 recovered with 0 false positives after the tie-break.
     - Eval accounts: 470 unique, 26 ambiguous (13 swap pairs or triples), 22 with no account row (10 NOT_APPLICABLE and 12 image-family cases).
3. **End-to-end prototype on the generated samples (`proto/e2e_samples.py`): 22 of 24 exact, 24 of 24 status.** It combines the activity oracle, the security audit id found by user in any evidence file, and citation to the in-window file. The 2 misses are case_18 `audit_record_6645` and case_20 `audit_record_5569`, which appear in no participant file and cannot be reached. The 8 hand-crafted samples (01, 02, 04–08, 10) need the family-specific handling in note 07.
4. **The citation rule is unique in practice.**
   - The cited file is the one with `reported_at <= captured_at <= audit_at` that mentions the resource id. All 32 samples' citations fall inside this window.
   - In eval, every resource has at most one such file (1,009 have exactly one; 0 have two or more).
   - All 674 violating resources in linked eval cases have an in-window file (`proto/cite_cov.py`).
   - For COMPLETE cases where the account id is mentioned nowhere (57 eval cases), cite the same proof file as the case's other steps. That is usually the SQL replica or inventory snapshot, absent by omission, like case_01/02/04 with ev54 and case_31 with ev51.
5. **Projected eval status:** about 334 INCOMPLETE, 136 COMPLETE, 10 NOT_APPLICABLE, and 38 still to decide. The 38 are the 12 image-family cases and 26 cases with an ambiguous account. Most of the 26 can still get a status, because their violating rows carry identifiers.

---

## 1. Contradictions between notes, resolved against the raw data

| # | Claim A | Claim B | Resolution |
|---|---|---|---|
| C1 | 09: system rank account<export<search<analytics<support<integration<backup<identity | 02/03/07/08: alphabetical `system_id` within each operation | Both reproduce all 32 samples. Alphabetical is simpler and is grounded in the spec. They would differ only for the same operation on search versus analytics, which never happens in the samples. `proto/emit_check.py` uses **(phase, operation's position in the §6.4 table, system_id, resource_id)** and reproduces 32 of 32. Numeric versus string `resource_id` order never matters in eval (checked: 0 cases). |
| C2 | 09/03: case_23 three-way tie, 25-vs-26 and 27-vs-28 analytics "coin flip", case_03 analytics_9406 unresolved | 02/07: ascending pairing or batch position resolves them | **Resolved exactly by fingerprint plus propagation** (§0.2). No heuristic is needed for the samples. Ascending pairing remains a fallback for the 26 ambiguous eval cases. |
| C3 | 04: "LEGAL_HOLD_RECORD produces no output steps" (from ev27) | 01/05: legal_hold_* must be retained | ev27 is a PDF of order numbers with **no resource ids** and no activity rows, so it says nothing about `legal_hold_N`. Eval has **10 `legal_hold_N` resources** with "Policy action completed … RETAIN_RECORD" worker rows (activity_264, 336, 410, 478, 801, 1120, 1902, 1942, 2264, 3138). Every linked one falls in an INCOMPLETE case (case_511, 505, 473, 460, 432, 261, 220, …). This mirrors the security audit pattern. **Recommendation:** emit `VERIFY_RECORD_PRESENT legal_service legal_hold_N PRESENT ''`. It sorts before security_service. It is untested by the samples (see open question Q3). |
| C4 | 01: inventory support rows cannot decide delete versus redact | 02/07: activity `event_type` decides | The activity `event_type` decides: REDACT_RECORD means a message (redact) and DELETE_RECORD means an attachment (delete). It agreed in every check. |
| C5 | 01: evidence_90 is the account-absence proof for cases 83–92 | (new) | Cohort 83–92 also has ev08, which lists accounts by id. ev90 has 0 rows and is captured at 09-05T07:18:01, which is 11 minutes after LINK activity_4010 (07:07:01). ev67 (03-10T06:18:01) follows the same "+18:01" pattern and is case_46's one-target account proof. So **ev90 is most likely the account-absent proof for case_45**, with id `account_003` by the hand-crafted `account_00N` convention, as in case_04/ev54. It may also serve cohort 83–92 when an account id is mentioned nowhere. |
| C6 | 08: "account delete result mirrors status, 29 of 31" | 09: "21 of 21" | Both are counts over different subsets. The mirror rule is used only as a candidate filter. Propagation does the rest, and none of the 24 is wrong. |
| C7 | 04: case_34's support_9538 is a "probable second finding" | 03: evidence_01 lines before the request are "preReq" | ev01 (09-15) is **before case_34's `requested_at` (09-24)**, outside the [reported, audit] window that every sample citation respects. But the old-phone link (`+81 90 6156 0005`, user_11) is the **only old-phone link** in the logs. It mirrors the case_12 old-hash link, which gold did use. See open question Q1. |
| C8 | 04: case_33 could include export_1260 (ev23) | — | ev23 (06-18) is before case_33's `reported_at` (07-18), so it cannot be cited under the window rule. I predict only export_1842 (ev18) for case_33, and export_1260 (ev23) for case_52. |

---

## 2. Gaps nobody covered

### 2.1 Discovery paths the worker-row approach misses

- **Flows that only show up as repopulation events:** "Active connector repopulated downstream resource search_N" (SYNC_RECORD, `resource_id = data_flow_X`) appears in 32 rows. **29 eval cases have a flow that has no CHECK_DATA_FLOW worker row:**
  - 517, 529, 481, 505, 469, 433, 421, 445, 397, 373, 361, 385, 337, 349, 301, 325, 289, 241, 217, 229
  - 181, 205, 169, 133, 145, 109, 85, 37, 49
  - In each case the evidence shows the flow enabled (SQL "sql-only" flows, ev94 data_flow_1043, …).
  - **Report them as REPORT_ACTIVE_DATA_FLOW.** The repopulation row ties the flow to the case through the search record.
  - Exclude these three:
    - activity_3448: data_flow_4218 → search_7455 belongs to user_59, who has no request.
    - activity_3434: data_flow_1121 repopulated search_4801 on 08-25, after case_39's audit.
    - activity_3387: backup_9287 restored search_4882 on 08-22, after case_55's audit.
- **Rows the fingerprint links to no case** (`proto/evidence_only.py`): 578 of 586 user-linked in-window violating observations are explained by activity.
  - Not explained: analytics_5959 (case_278), data_flow_3064 (case_317), data_flow_6090 (case_382) and data_flow_3250 (case_388).
  - These do have worker rows; the fingerprint linked them to 0 cases. **Use the union of activity-linked and evidence-linked resources.**
  - export_001 and support_002 are hand-crafted samples. account_1733 belongs to the evidence_50 NOT_APPLICABLE decoy.
- **Decoy worker rows:** activity_3669 (support_1034, 09-05) and search_2912 fall inside the case_546 batch but belong to user_22, whose only case is case_53 in May. Drop a row when its evidence owner matches no candidate case.

### 2.2 Rule coverage (`deletion_rules.csv`) versus the evidence

| Rule | Seen in eval evidence? | Handling |
|---|---|---|
| 01 USER_PROFILE | yes | Always verify absent. A replication row or PRESENT means remaining → DELETE. |
| 02 SECONDARY_IDENTIFIER / 10 MARKETING_PROFILE | Only case_12 (sample, analytics `contact_lookup email_opt_in`) and case_63 marketing_001 (ev60) | DELETE. Use REPORT_REMAINING_RECORD, not EXPOSED_PII. |
| 03 SEARCH | yes (~105 rows in SQL alone) | delete |
| 04 CACHE_ENTRY | **no**; only `cache_lookup` noise and REFRESH_CACHE noise rows | ignore (decoy rule) |
| 05 SUPPORT_MESSAGE / 06 ATTACHMENT | yes | Decide by activity `event_type`. Also object_storage/object_19 (case_61). |
| 07 ANALYTICS / 08 PRODUCT_TELEMETRY | analytics yes; telemetry **no** (only `telemetry_flushed` noise) | anonymize |
| 09 USER_EXPORT | yes (~12 SQL rows, ev59, ev18/ev23) | delete. Activity says `object_store`; use export_service. |
| 11 EMAIL_DELIVERY_LOG | **no**. evidence_41 is named notification_delivery but is an ordinary flat ledger. SEND_EMAIL rows are noise. | ignore (decoy rule) |
| 12 SECURITY_AUDIT | yes | VERIFY_RECORD_PRESENT. There are no worker rows for it; find it by `user_id` in any file. |
| 13 LEGAL_HOLD | 8 resources in evidence, 10 in activity | See C3: VERIFY_RECORD_PRESENT (open question). |
| 14 BACKUP | yes | BLOCK_RESTORE. Never delete a backup. |
| 15 TOMBSTONE | yes: case_543–550 (ev52) and case_46 (ev42) | REDACT; verify REDACTED. 5 compliant and 5 violation identity_service rows: 31 and 32 in the samples, 4 and 4 in eval. |

### 2.3 Security audit record coverage (`proto/audit_cov.py`)

- 300 eval cases have an audit id citable in-window, 134 only in a late file, and **84 nowhere**.
- The 84 cluster in cohorts whose proof file is a JSON export or readback that lists audit records only for compliant users. This is the case_18/20 situation: about 70 INCOMPLETE eval cases will each lose one VERIFY_RECORD_PRESENT step, and nothing can recover it. **Do not invent ids.**
- An audit id found only in a late file is still used for INCOMPLETE verification with `evidence_id=''`, as in samples 09, 23, 24, 29 and 30.

### 2.4 The image family (12 eval cases, no worker rows)

LINK rows activity_4000–4011 give the resource ids. evidence_01, which is late for every case except case_34, holds each user's account and audit ids. Following the sample 09/23/29 precedent, use those ids only for INCOMPLETE verification, with an empty evidence id.

| Case | Prediction |
|---|---|
| 33 | INCOMPLETE. export_1842 (ev18). Verify account_2373 and audit_record_8486, both found only in ev01. |
| 34 | INCOMPLETE. account_5762 PRESENT (ev04 overrides ev01's 404). Possibly support_9538 (Q1). Verify audit_record_3753. |
| 35 | INCOMPLETE. search_428 (ev09). Verify account_8491 and audit_record_8925. The ev09 decoy is `g.silva76.jr`. |
| 39 | INCOMPLETE. data_flow_1121 (ev14). Verify account_8926 and audit_record_7301. Do not report search_4801, which was repopulated on 08-25, after the audit. |
| 45 | COMPLETE. account_003 ABSENT (ev90, by convention) and audit_record_003 PRESENT (ev37). |
| 46 | COMPLETE. account_6523 ABSENT (ev67) and tombstone_17 REDACTED (ev42). Do not use account_4092 or backup_3245, which belong to case_17. |
| 50 | INCOMPLETE. analytics_7438 EXPOSED (ev19). Verify account_3270 and audit_record_5080. |
| 52 | INCOMPLETE. export_1260 (ev23). Verify account_2373 and audit_record_8486. |
| 53 | INCOMPLETE. support_1034 EXPOSED→REDACT (ev28). Verify audit_record_9644 (ev02); the account id is unknown. |
| 55 | INCOMPLETE. backup_9287 RESTORE_RISK (ev32). Verify account_9494 and audit_record_2857. |
| 61 | INCOMPLETE. object_storage/object_19 REMAINING (ev46). Verify account_007 by convention (Q2). |
| 63 | INCOMPLETE. marketing_platform/marketing_001 REMAINING (ev60; the identity shown on screen mismatches). Verify account_009 by convention (Q2). |

### 2.5 Other checked items

- **NOT_APPLICABLE:** exactly cases 533–542. Each has one CLASSIFY_REQUEST "non-deletion" row, and evidence_50 is their decoy ledger with accounts FOUND.
- **"Target resource" templates:** these 12 rows exist only for the hand-crafted samples and do **not** encode truth (support_002 is "completed" but remains). Eval has none.
- **Timestamps inside files:** entries timestamped after `audit_at` inside an in-window file (ev13 account_1417, ev36 account_5043, ev44/30/21/16/11/06 tail flips) must be filtered by entry time as well as by file capture time.

---

## 3. Algorithm verified

1. Classify the request text. 533–542 are NOT_APPLICABLE with `[]`; the guard-phrase classifier from note 06 also works.
2. Resolve the user from the current or any historical email, lowercased and exact. Email hash is sha256 of the lowercased email; also use old phone and old hash.
3. **Resources:**
   - Start with the account row (timing, status mirror and propagation).
   - Add fingerprint-linked worker rows with `event_time <= audit_at`.
   - Add flows that repopulated those searches.
   - Add evidence identifier matches.
   - Add audit records by user_id from any file.
   - For the hand-crafted and image families, use LINK rows and the `account_00N` convention.
4. **State:** use the template class, confirmed by the latest in-window observation. They never conflicted.
5. **Cite:** the in-window file ([reported_at, audit_at], inclusive) that mentions the resource, or the case's proof file for absence by omission.
6. **Emit:**
   - A violating resource gets a FINDING (with evidence), a REMEDIATION (empty evidence) and a VERIFICATION.
   - A compliant resource gets only a VERIFICATION.
   - In an INCOMPLETE case, every verification has an empty evidence id.
   - Sort by (phase, operation's position in the table, system_id, resource_id).
   - In the samples, compliant and violating resources never mix in one case except the account and audit record; the legal hold exception applies in eval.
   - Result: `proto/emit_check.py` reproduces 32 of 32 and `proto/e2e_samples.py` 22 of 24 generated samples, with both misses unreachable.

---

## 4. Open questions

- **Q1.** Should case_34 include support_9538? It is linked through an old phone in ev01, which was captured before the request. Including it fits the case_12 trap precedent; excluding it fits the citation window.
- **Q2.** Hand-crafted accounts (account_003, 007, 009) appear in no file. Is the `account_00N` convention also valid in eval? It is needed for case_45, 61 and 63. For case_61, does it reuse account_007 from sample case_07?
- **Q3.** Do legal holds get VERIFY_RECORD_PRESENT? Recommended yes; untested.
- **Q4.** Which account goes with which case in the 13 swap groups (case_56/58, 59/60, 104/106, 203/205, 225/226, 243/244, 294/295, 345/346, 347/349, 404/406, 408/409, 410/411/412, plus case_546)? Ascending pairing is a fallback; at most one step is lost per case.
- **Q5.** For the 57 COMPLETE cases where the account is absent by omission, which file to cite when the window holds several? Prefer the file that proves the other steps and whose scope covers account_service.
- **Q6.** Should compliant resources inside an INCOMPLETE case be verified? Only legal holds occur in eval; the recommendation is VERIFY with an empty evidence id.
- **Q7.** case_63: the marketing screenshot shows Soo-jin Park. Trust the catalog link (user_09); it is correct for the other 11 files.

## 5. Prototype files (`solution/notes/proto/`)

- `emit_check.py`: emitter round-trip.
- `link_check.py` and `fingerprint.py`: timing study.
- `link_fp.py`: fingerprint only.
- `solve_links.py`: global linker; writes `case_account_candidates.json` and `case_worker_resources.json`.
- `cross_sql.py`, `cross_all.py`, `acct_check.py`: oracle validation.
- `evidence_only.py`, `audit_cov.py`, `cite_cov.py`: coverage checks.
- `e2e_samples.py`: end-to-end check on the samples, plus eval projections.
