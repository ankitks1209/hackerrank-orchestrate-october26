# 04 — Images (11 PNG) and PDFs (4) — full transcription + analysis

All 15 binary evidence files were read visually (PNG via Read; PDFs via Read without `pages`, which returns the
text layer + page render; `pages=` fails because pdftoppm is missing). All participant-visible only.

## 0. Headline findings (read this first)

1. **Hidden grounding channel: `LINK_RESOURCE_IDENTITY` events in `system_activity.csv` (activity_4000–4011).**
   There are exactly 12 rows with `event_type=LINK_RESOURCE_IDENTITY`, `source_system=data_catalog`. Each one is
   timestamped **exactly `captured_at + 7m01s`** of one image/PDF and gives the canonical `system_id`,
   `resource_id`, email and `user_id` of what the screenshot shows. This is how image evidence is wired to
   resources/cases. Table:

   | activity | time | target_system | resource_id (display) | user | evidence |
   |---|---|---|---|---|---|
   | activity_4000 | 2026-09-26T11:07:01Z | account_service | account_5762 | haruka.s1838@zoho.com / user_11 | evidence_04 |
   | activity_4001 | 2026-09-01T06:07:01Z | search_service | search_428 | g.silva76@gmail.com / user_13 | evidence_09 |
   | activity_4002 | 2026-08-07T08:07:01Z | integration_service | data_flow_1121 | jain.aditi@gmail.com / user_14 | evidence_14 |
   | activity_4003 | 2026-07-13T10:07:01Z | analytics_platform | analytics_7438 | darwish.omar@icloud.com / user_20 | evidence_19 |
   | activity_4004 | 2026-06-18T12:07:01Z | export_service | export_1260 | ingrid.dahl@outlook.com / user_18 | evidence_23 |
   | activity_4005 | 2026-05-24T07:07:01Z | support_platform | support_1034 | kagyeman8947@fastmail.com / user_22 | evidence_28 |
   | activity_4006 | 2026-04-29T09:07:01Z | backup_service | backup_9287 | areed1433@gmail.com / user_16 | evidence_32 |
   | activity_4007 | 2026-02-13T08:07:01Z | object_storage | object_19 (delivery_confirmation_19.pdf) | priya.raman@gmail.com / user_07 — "belongs only to … no other subject is linked" | evidence_46 |
   | activity_4008 | 2026-09-16T07:27:01Z | marketing_platform | marketing_001 | kwame-mensah@proton.me / user_09 | evidence_60 |
   | activity_4009 | 2026-07-18T11:07:01Z | export_service | export_1842 (NST-2026-0718-1842) | ingrid.dahl@outlook.com / user_18 | evidence_18 |
   | activity_4010 | 2026-09-05T07:07:01Z | security_service | audit_record_003 | oliver-bennett@gmail.com / user_03 | evidence_37 |
   | activity_4011 | 2026-03-10T06:07:01Z | identity_service | tombstone_17 (user_17) | leonie.g9352@outlook.com / user_17 | evidence_42 |

   No catalog link exists for evidence_27 (legal register), evidence_55 (security retention extract) or
   evidence_58 (delivery correction attachment = sample case_07 `support_001`).

2. **One "image case" per file, a "single-evidence" eval case family.** Each image/PDF has exactly one case whose
   `audit_at` is about 1–2 days after `captured_at`, with requested ≈ capture−2d, reported ≈ capture−9h:
   case_33, 34, 35, 39, 45, 46, 50, 52, 53, 55, 61, 63 (+ sample case_07 for evidence_58). For these cases, the
   **only other evidence naming their resources is `evidence_01` (service_events_ap_south_20260915.log, captured
   2026-09-15T11:59:39Z)**, which is AFTER audit_at for all of them except case_34 and case_63. So the image/PDF
   is the only admissible proof. That's the temporal trap: a solver that greps all evidence will cite evidence_01
   (post-audit, forbidden) or use states from it.

3. **Resource IDs are not always visible in the image.** object_19, tombstone_17, export_1842, marketing_001 come
   from the catalog link (the image shows "delivery_confirmation_19.pdf", "user_17", "NST-2026-0718-1842",
   "marketing_001"). Use the catalog's `resource_id` and `target_system` as system_id/resource_id. Do not use
   `user_17` as the resource_id. Do not use ticket numbers (CS-5034, CS-8538, CS-4827) or order numbers as
   resource ids.

4. **Marketing anomaly (evidence_60).** The screenshot shows **Soo-jin Park, sj.park@naver.com, +82 10-5837-9451**.
   That person is NOT in user_identities.csv or user_audit_log.csv, but activity_4008 links marketing_001 to
   **kwame-mensah@proton.me / user_09** (case_63, which is built on the same "+20 min" time pattern:
   requested 09-14T04:20, reported 09-15T22:20, audit 09-17T09:20; capture 09-16T07:20, link 07:27:01).
   kwame-mensah appears in no other evidence. Most likely intended answer: case_63 INCOMPLETE with
   `REPORT_REMAINING_RECORD marketing_platform marketing_001 evidence_60` → DELETE (rule_10 MARKETING_PROFILE
   Always DELETE). Risk: it could be a deliberate identity-mismatch decoy. Recommendation: trust the catalog link
   (it is truthful for all 11 other files), but keep this as a known uncertainty.

5. **Legal register (evidence_27) covers only sample users** (user_08, 12, 17, 21, 24, 29). None of the 32 sample
   gold answers contains any legal-hold / order step, even though the register was captured (2026-05-29) before
   their audit_at (Sept). **So LEGAL_HOLD_RECORD retention produces NO steps.** Its only effect is "don't report
   ORD-… order records as remaining". Sample case_21 (user_21, legal hold on ORD-20264402) is still COMPLETE.

6. **Security retention (evidence_55)**: audit_record_003 (user_03) retain until 2027-08-25T04:03Z → within
   retention at the case_45 audit (2026-09-06) → rule_12 RETAIN → `VERIFY_RECORD_PRESENT security_service
   audit_record_003 PRESENT`. Cite evidence_37 (catalog-linked screenshot; evidence_55 is the supporting
   retention document; either is pre-audit).

7. **Sample gold cites the latest pre-audit evidence, not the image.** Sample case_15 (data_flow_9846, lucia-torres)
   is also visible in evidence_14 (2026-08-07), but gold cites evidence_01 (2026-09-15T11:59:39Z, 21 s before
   audit 12:00:00). So when several admissible evidence items show the same state, prefer the **latest one at or
   before audit_at**.

8. **Manifest vs filename dates.** For 12 of the 15 files, the filename date = `captured_at` date. Three files have
   no date in their name and odd capture minutes: `security_retention_extract.pdf` (evidence_55, 2026-09-05T06:30Z),
   `delivery_correction_attachment.pdf` (evidence_58, 2026-09-12T07:30Z, only 30 min before sample case_07's audit
   08:00), `marketing_profile_console.png` (evidence_60, 2026-09-16T07:20Z). The in-document dates agree with the
   manifest (legal register "generated 29 May 2026 08:00 UTC"; retention extract "issued 05 Sep 2026 06:30 UTC";
   delivery attachment "captured 12 Sep 2026 07:30 UTC" although "submitted/received 18 Jun 2026"). **Use
   `captured_at` from the manifest for the audit cutoff, not dates inside the document (e.g. 18 Jun submission).**

---

## 1. Per-file transcription

### evidence_04 — images/account_admin_console_20260926.png (origin account_admin_portal, captured 2026-09-26T11:00:00Z)
"Northstar Shop / Customer Operations / Customers". Header: **Haruka Sato** [Silver], `user_11 · account_5762`.
Tabs Overview/Orders/Addresses/Support history. Tiles: Email **haruka.s1838@zoho.com**; Phone **+81 90 7610 2507**;
Signup channel mobile_app; Market JP; Preferred language Japanese; Last contact 24 Sep 2026 09:14 JST.
Orders (2 records): ORD-20265762, 12 Sep 2026, Ceramic coffee set, qty 1, JPY 8,900, Delivered · 18 Sep;
ORD-20265518, 28 Aug 2026, Travel backpack, 1, JPY 12,400, Returned · 03 Sep.
Customer details: Default address 2-18-4 Kichijoji, Musashino, Tokyo 180-0004; Loyalty Silver;
Support **CS-8538 · support_9538**; Member since 12 Jan 2024.
Activity: 24 Sep customer replied to CS-8538; 22 Sep support agent responded; 18 Sep ORD-20265762 delivered;
03 Sep ORD-20265518 returned; 28 Aug support_9538 created.
- Identity: user_11 Haruka Sato, current email/phone (changed 2026-05-17 per audit_277/279; old email
  haruka.s183889@zoho.com, old phone +81 90 6156 0005).
- Case: **case_34** (haruka.s1838@zoho.com, req 09-24T08, reported COMPLETE 09-26T02:00, audit 09-27T13:00).
  Account profile still live 9 h after the COMPLETE claim → `REPORT_REMAINING_RECORD account_service account_5762
  PRESENT evidence_04`, DELETE, VERIFY_RECORD_ABSENT.
- Trap: evidence_01 (09-15) line 40 shows `account_5762 profile_lookup_completed rows=0 http_status=404` (absent).
  The later evidence_04 (09-26) shows it present → the latest pre-audit state wins (PRESENT).
- Related: support_9538. evidence_01 line 25 (09-15, admissible for case_34): `support_9538
  event=attachment_pii_scan matched_value="+81 90 6156 0005" file=delivery_confirmation_32.pdf` → Haruka's
  **historical** phone in a support attachment. By the sample pattern (attachment FOUND → REPORT_REMAINING_RECORD
  + DELETE, e.g. case_13 support_4218), this is a probable second finding for case_34. activity_3485/3489 (08-28)
  show earlier FAILED deletes of account_5762 and support_9538.
- Haruka is also a name decoy: 7 other "Haruka …" users (user_141 Ito, 271 Mori, 401 Watanabe, 531 Kato, 661 Tanaka,
  791 Kobayashi).

### evidence_09 — images/search_index_inspector_20260901.png (search_index_admin, 2026-09-01T06:00:00Z)
"Search Console / Customer Search", query box `email:g.silva76@gmail.com`, 2 hits, index customer_directory_v3 / prod-eu.
Executed 01 Sep 2026 06:00:14 UTC; latency 184 ms.
Results: **search_428 | Gabriel Silva | g.silva76@gmail.com | customer_reference user_13 | score 9.84 | 05:58:21 UTC**;
search_1874 | — | **g.silva76.jr@gmail.com** | — | 4.12 | 05:55:03 UTC.
Raw doc search_428: _index customer_directory_v3, display_name Gabriel Silva, email g.silva76@gmail.com,
customer_reference user_13, indexed_at 2026-09-01T05:58:21Z.
Activity: 06:00:14 email:g.silva76@gmail.com · 2 hits; 05:42:03 customer_reference:user_9842 · 1 hit;
05:31:18 display_name:"Aditi Jain" · 1 hit.
- Case: **case_35** (g.silva76@gmail.com, NOT_STARTED, audit 09-02T08:00) → `REPORT_REMAINING_RECORD search_service
  search_428 PRESENT evidence_09` → DELETE → VERIFY_RECORD_ABSENT.
- **Decoy**: search_1874 / g.silva76.jr@gmail.com is a near-duplicate email with no customer reference and is in no
  identity or audit row. Do NOT report. (Substring matching on "g.silva76" would wrongly catch it.)
- Noise: user_9842 does not exist (only user_01..user_850); "Aditi Jain" = user_14 (case_39), just query history.
- activity_3436 (08-25) DELETE search_428 FAILED. evidence_01 (09-15, after audit) also shows the search_428 hit: inadmissible.

### evidence_14 — images/connector_management_console_20260807.png (integration_admin, 2026-08-07T08:00:00Z)
"BridgeOps / Connections", 12 connectors, PRODUCTION · eu-west · 07 Aug 2026 08:00 UTC. Healthy 12, Events/hour
4,113, Delivery p95 1.8 s, Backlog 18, Destination health Healthy.
Topology: **data_flow_1121 → customer_analytics_warehouse, selector jain.aditi@gmail.com, Continuous, 1,284/h, last 07:59:42**;
**data_flow_9846 → customer_analytics_warehouse, selector lucia-torres@gmail.com, Continuous, 842/h, 07:59:36**;
Order notifications → notification_service, order events, Continuous, 650, 07:59:28;
Delivery tracking → logistics_warehouse, shipment events, Continuous, 420, 07:59:13.
Detail data_flow_1121: Status Healthy; Owner Data Platform; Destination customer_analytics_warehouse; Selector
jain.aditi@gmail.com; Sync mode Continuous sync; Last response 200 OK · 1.8 s. Activity 07:59:42 124 events
delivered; 07:58:10 checkpoint committed; 07:56:44 18 events retried; 07:55:02 destination acknowledged batch.
- Case: **case_39** (jain.aditi@gmail.com, user_14, reported COMPLETE, audit 08-08T10:00) → `REPORT_ACTIVE_DATA_FLOW
  integration_service data_flow_1121 ACTIVE evidence_14` → DISABLE_DATA_FLOW first → VERIFY_DATA_FLOW_DISABLED.
  activity_3434 (08-25, after audit) shows data_flow_1121 later repopulating search_4801: ignore for case_39.
- data_flow_9846 = sample case_15 (lucia-torres, user_15). Gold cites evidence_01, not evidence_14 (see headline 7).
- Order notifications / Delivery tracking are not user-scoped: decoys.

### evidence_18 — documents/account_history_report_20260718.pdf (account_history_service, 2026-07-18T11:00:00Z)
2 pages. "NORTHSTAR SHOP - CUSTOMER STATEMENT, Statement NST-2026-0718-1842". Customer Ingrid Dahl; user_18;
ingrid.dahl@outlook.com; statement NST-2026-0718-1842; order ORD-20261260. Item: Smart desk lamp, SKU LAMP-SD-04,
qty 1, subtotal EUR 54.95, shipping EUR 4.99, tax EUR 11.99, total EUR 71.93. Payment Visa ending 4821; billing
status paid; order date 08 Jul 2026; dispatched 10 Jul; delivered 14 Jul. Page 2: Delivery address 24 Fjordgata,
7010 Trondheim, Norway; Timeline: order placed, payment authorised, warehouse packed, carrier collected, delivered.
- Catalog activity_4009: this is **export_service / export_1842** (NST-2026-0718-1842), user_18.
- Case: **case_33** (ingrid.dahl@outlook.com, reported COMPLETE 07-18T02:00, audit 07-19T13:00). The document is a
  generated customer statement/export containing name, email, address, card last4. As USER_EXPORT (rule_09 DELETE)
  → `REPORT_REMAINING_RECORD export_service export_1842 PRESENT evidence_18` → DELETE → VERIFY_RECORD_ABSENT.
- Trap: the origin label says account_history_service and the title says "statement", but the catalog says
  export_service. Use the catalog's system.
- Ambiguity: export_1260 (evidence_23, 06-18, "Expires 25 Jun") is also pre-audit for case_33. Expiry is a claim.
  evidence_01 (09-15, inadmissible for case_33) shows export_1260 still `available=true`. The generator probably
  assigns export_1260 to case_52 only. Consider whether case_33 should also carry export_1260 (from evidence_23).
- Interesting: Ingrid's phone in identities is +46 (Sweden) while the address is in Norway. "Visa ending 4821"
  collides with object name return_label_4821.pdf in evidence_46: coincidence or decoy.

### evidence_19 — images/analytics_profile_view_20260713.png (analytics_platform, 2026-07-13T10:00:00Z)
"Pulse Analytics / Users", **Omar Darwish** [Last 90 days], `user_20 · analytics_7438 · darwish.omar@icloud.com`.
Tabs: Event timeline, Sessions (12), Orders (2), Products viewed (19). Tiles: Sessions 12; Products viewed 19;
Completed orders 2; Revenue USD 167.42; Mobile/Desktop 67%/33%; Acquisition Organic search.
Timeline (5): 14:22 Order completed, Ceramic coffee set, USD 84.21, Mobile; 14:20 Checkout started, 2 items, 84.21,
Mobile; 14:17 Product viewed, Ceramic coffee set, —, Mobile; 14:16 Added to cart, Ceramic coffee set, USD 42.00,
Mobile; 14:12 Product viewed, Stoneware mug, USD 18.00, Desktop.
Profile attributes: Market AE; Audience Returning shopper; Interest Coffee & dining; Last activity 13 Jul 2026
14:22 UTC; First seen 21 Apr 2026 09:14 UTC. Activity: 13 Jul 6 events in active session; 08 Jul Order completed ·
USD 83.21; 30 Jun Product search · coffee set; 22 Jun Campaign opened. (84.21 + 83.21 = 167.42, consistent.)
- Case: **case_50** (darwish.omar@icloud.com, NOT_STARTED, audit 07-14T12:00). Analytics profile directly shows
  name + email → ANALYTICS_PROFILE rule_07 ANONYMIZE → `REPORT_EXPOSED_PII analytics_platform analytics_7438 PRESENT
  evidence_19` → ANONYMIZE_RECORD → VERIFY_RECORD_ANONYMIZED (like sample case_22 analytics_4440).
- Note: user_20 phone changed 2025-07-01 (audit_34). 6 other Darwish users are name decoys (user_202, 384, 423, 605, 826).
  activity_3723 (09-08) ANONYMIZE analytics_7438 FAILED; evidence_01 (09-15) shows direct_identifiers=1. Both after audit.

### evidence_23 — images/customer_export_console_20260618.png (export_service, 2026-06-18T12:00:00Z)
"Customer Download Center / Data exports", 4 jobs. Ready 2, Processing 2, Created today 1, Downloads today 0.
Rows: export_1261, customer_export_1261.zip, marcus.lee@northstar.shop, Collecting, 20 Jun 14:18 UTC;
**export_1260, customer_export_1260.zip, ingrid.dahl@outlook.com, Ready, 18 Jun 06:42 UTC**;
export_1259, customer_export_1259.zip, sara.kim@northstar.shop, Packaging, 17 Jun 11:03 UTC;
export_1258, customer_export_1258.zip, daniel.park@northstar.shop, Ready, 16 Jun 09:27 UTC.
Detail export_1260: Owner ingrid.dahl@outlook.com; Created 18 Jun 2026 06:42 UTC; Expires 25 Jun 2026 06:42 UTC;
Size 18.4 MB; Checksum SHA-256 · 41ca09…; Download count 0; Included Profile · Orders · Saved addresses.
Activity 06:42 Export requested; 06:43 Collecting customer records; 06:45 Package created; 06:46 Ready for download.
- Case: **case_52** (ingrid.dahl@outlook.com, req 06-16, reported COMPLETE **06-18T03:00**, audit 06-19T14:00).
  The export was created at 06:42, AFTER the completion claim → `REPORT_REMAINING_RECORD export_service export_1260
  PRESENT evidence_23` → DELETE → VERIFY_RECORD_ABSENT.
- Oddity: export_1261 shows created "20 Jun 14:18", which is after the capture time (06-18 12:00). Irrelevant
  (staff owner), but it shows that screen content can include future-dated rows.
- Decoys: @northstar.shop staff owners (not in identities). daniel.park ≠ user_237 daniel-parker@proton.me.

### evidence_27 — documents/legal_retention_register_20260529.pdf (legal_retention_service, 2026-05-29T08:00:00Z)
"DISPUTED ORDERS AND TAX RECORDS REGISTER, Finance Operations | May 2026". Page 1 register details: Register month
May 2026; owner Finance Records; classification Internal; generated 29 May 2026 08:00 UTC; "For each row add
invoice date, finance owner, retain-until date, and case/reference number" (a template note, not an instruction).
Page 2 "Disputed order entries":
1. ORD-20264118 | user_08 | Card dispute | 04 May 2026 | USD 184.20 | Retain until 04 May 2033 | AR
2. ORD-20264207 | user_12 | Tax correction | 09 May 2026 | EUR 72.40 | Retain until 09 May 2033 | ML
3. ORD-20264319 | user_17 | Chargeback | 14 May 2026 | GBP 219.00 | Retain until 14 May 2033 | SK
4. ORD-20264402 | user_21 | Invoice inquiry | 18 May 2026 | CAD 96.55 | Retain until 18 May 2033 | AR
5. ORD-20264511 | user_24 | Card dispute | 23 May 2026 | AUD 311.80 | Retain until 23 May 2033 | ML
6. ORD-20264600 | user_29 | Tax record | 28 May 2026 | USD 48.75 | Retain until 28 May 2033 | SK
- Users map to sample cases 08 (Gabriel Costa), 12 (Min-jun Kim), 17 (Léonie Girard), 21 (Amara Okeke),
  24 (Keiko Nakamura), 29 (Noah Foster). None of their gold answers has a legal-hold step → LEGAL_HOLD_RECORD
  (rule_13 RETAIN) produces **no output step**. Just don't flag these orders as remaining.
- No resource_id, no catalog link, and the order IDs appear in no other evidence file.
- Trap: user_17 also has eval case_46 (audit 2026-03-11), but this register was captured 2026-05-29 and the
  chargeback is dated 14 May → inadmissible for case_46.
- The 10 eval cases whose audit_at is exactly 2026-05-29T08:00:00Z (case_283..292) are batch cases with
  audit_at = capture time ("at or before" is inclusive). They are not related to these users.

### evidence_28 — images/support_ticket_console_20260524.png (support_platform, 2026-05-24T07:00:00Z)
"Helpline Console / Inbox". **CS-5034 · Where is my delivery?** [SLA 01:42], `support_1034 · Kofi Agyeman · Normal
priority`. Customer Kofi Agyeman; Email **kagyeman8947@fastmail.com**; Assigned Maya Chen; Tags Delivery · Tracking ·
Order update. Conversation: 09:12 Kofi Agyeman "Could you let me know where my order is and when it is expected to
arrive?"; 09:13 Northstar Bot "We received your message and are checking the order details."; 09:28 Maya Chen "The
parcel reached the regional hub and is on track for delivery on 26 May."; 09:35 Kofi Agyeman "Thanks for the update."
Order ORD-20265034: Running shoes; In transit; Carrier SwiftShip; Tracking SWF-884103; Expected 26 May 2026; agent
Maya Chen. Activity: 22 May order confirmed; 23 May dispatched; 24 May 07:46 reached regional hub; 24 May 08:15 in
transit; 26 May delivery expected.
- Case: **case_53** (kagyeman8947@fastmail.com / user_22, reported COMPLETE, audit 05-25T09:00). The conversation
  includes agent and order context → SUPPORT_MESSAGE rule_05 REDACT → `REPORT_EXPOSED_PII support_platform
  support_1034 PRESENT evidence_28` → REDACT_RECORD → VERIFY_RECORD_REDACTED.
- Small inconsistency: the timeline shows "24 May 07:46 / 08:15" events after the 07:00 capture. Ignore it.
- Resource id is support_1034 (not CS-5034). The only other mentions (snapshot 20260917, activity_3669 09-05
  REDACT FAILED) are after the audit. Name decoys: 7 "Kofi" users (sample case_32 is Kofi Addo).

### evidence_32 — images/backup_restore_console_20260429.png (backup_service, 2026-04-29T09:00:00Z)
"Vault Recovery Manager / Recovery Manager". Customer-platform archives [Healthy], Northstar Production · weekly
snapshots. Service health Healthy; Storage growth +12.4%; Restore success 99.6%; Stored 1.35 PB.
Archives (4): backup_9291 bluepeakco@outlook.com ap-southeast-1 26 Apr 02:00 102.3 GB AES-256 Archive;
backup_9288 miller.logistics@company.com us-west-2 67.1 GB; **backup_9287 areed1433@gmail.com eu-west-1 84.7 GB**;
backup_9286 summit-retail@company.com us-east-1 91.4 GB.
Detail backup_9287: Account areed1433@gmail.com; Path s3://northstar-backups/customer-platform/weekly/segment-42-20260426.tar.zst;
Region eu-west-1; Created 26 Apr 2026 02:00 UTC; Encryption AES-256; Checksum Verified; Last drill 29 Mar 2026;
**Retention end 26 Jul 2026**. Activity: 25 Apr backup_9286 restored · Completed; 24 Apr backup_9281 restored ·
Completed; 22 Apr checksum verification · Completed. There is **no restore-block flag**.
- Case: **case_55** (areed1433@gmail.com = user_16 Amelia Reed, NOT_STARTED, audit 04-30T11:00). BACKUP_ARCHIVE
  rule_14 RETAIN but restore must be blocked → `REPORT_RESTORE_RISK backup_service backup_9287 ACTIVE evidence_32` →
  BLOCK_RESTORE (before any record changes) → VERIFY_RESTORE_BLOCKED.
- Later corroboration (inadmissible): activity_3387 (08-22) RESTORE_BACKUP backup_9287 repopulated search_4882;
  evidence_01 `restore_candidate_evaluated eligible=true deletion_block=false`.
- Decoys: business accounts bluepeakco / miller.logistics / summit-retail (not in identities); backup_9286/9281
  restore activity is unrelated. 6 "Reed" users exist (user_198 Grace, case_200, etc.).

### evidence_37 — images/security_audit_explorer_20260905.png (security_service, 2026-09-05T07:00:00Z)
"Sentinel / Account events" (dark theme), 6 signed events, Subject filter: user_03 · 18–26 Aug 2026 UTC. Events 6,
Categories 5, Integrity failures 0, Partition 2026-Q3.
Events: 25 Aug 04:03 Account closure recorded | Account lifecycle | user_03 | Automated workflow | Valid |
**audit_record_003**; 25 Aug 03:21 Session revoked | Session management | Security system | audit_record_002;
24 Aug 16:14 Recovery challenge completed | Authentication | User (self) | audit_record_001; 22 Aug 11:27 Email
change confirmed | Profile update | User (self) | audit_record_006; 20 Aug 09:42 Login from new device |
audit_record_005; 18 Aug 14:05 Password changed | audit_record_004.
Raw event audit_record_003: event_type account_closure_recorded; subject user_03; actor automated account workflow;
recorded_at 2026-08-25T04:03:00Z; fingerprint 8f0c…31ad; signature Valid; journal 2026-Q3.
- Case: **case_45** (oliver-bennett@gmail.com = user_03 Oliver Bennett, reported COMPLETE, audit 09-06T09:00) →
  SECURITY_AUDIT_LOG within retention (see evidence_55) → `VERIFY_RECORD_PRESENT security_service audit_record_003
  PRESENT evidence_37`.
- Only audit_record_003 is catalog-linked. audit_record_001/002/004/005/006 are visible but not linked. Sample gold
  always has exactly one security audit_record per case → cite only 003.
- Oddity: "Email change confirmed 22 Aug" for user_03, but user_audit_log has no entry for user_03 and the snapshot
  updated_at is 2026-03-14. It may hint at an unlisted historical email, or it is just noise.

### evidence_42 — images/deleted_account_reference_20260310.png (identity_service, 2026-03-10T06:00:00Z)
"Customer Reference Registry / Customer references". **user_17** [Retained reference], Customer key · Account
Platform · eu-west. Reference type Customer key; Created 11 Jan 2024 08:42 UTC; Most recent update 10 Mar 2026
07:18 UTC; Owner team Account Platform.
Linked records (4, all Active, "Linked to customer"): Orders ORD-20263245 (11 Jan 2024 08:45); Support CS-3245
(14 Feb 2024 12:16); Support CS-3378 (03 Jun 2024 09:27); Finance FIN-7742 (22 Aug 2024 15:03).
History: 10 Mar 2026 Metadata reviewed; 22 Aug 2024 Finance link added; 03 Jun 2024 Support link added;
14 Feb 2024 Support link added; 11 Jan 2024 Reference created.
**No name, email, phone or hash is displayed**, only the stable user_17 reference.
- Catalog activity_4011: **identity_service / tombstone_17** (display "user_17") ↔ leonie.g9352@outlook.com / user_17.
- Case: **case_46** (leonie.g9352@outlook.com, req 03-08, reported COMPLETE 03-09T21:00, audit 03-11T08:00).
  ACCOUNT_TOMBSTONE rule_15 REDACT. The tombstone shows only the stable reference → compliant →
  `VERIFY_RECORD_REDACTED identity_service tombstone_17 REDACTED evidence_42` (pattern = sample case_31
  tombstone_440). Contrast with sample case_32 (tombstone_9178 still shows PII → REPORT_EXPOSED_PII + REDACT).
- Traps: resource_id is tombstone_17, not user_17. Its "most recent update 10 Mar 07:18" is after the 06:00 capture
  (minor inconsistency). Numbers 3245 are reused: ORD-20263245/CS-3245 vs backup_3245 in sample case_17 (same user,
  Aug request, audit 09-15). evidence_01's backup_3245 restore risk is after case_46's audit → inadmissible.
  The legal register (May) is also inadmissible for case_46.

### evidence_46 — images/object_storage_browser_20260213.png (object_storage, 2026-02-13T08:00:00Z)
"Nimbus Object Storage / northstar-customer-data" [8 objects], eu-west-1 / support-attachments / 2026 / 02.
Account Northstar Production; Region eu-west-1; Captured 13 Feb 2026 08:00 UTC; Storage class All.
Objects: **delivery_confirmation_19.pdf 684 KB 12 Feb 18:42 Standard v3**; delivery_confirmation_20.pdf 712 KB
11 Feb 14:17 v1; return_label_4821.pdf 203 KB 10 Feb 09:33 v1; return_label_4876.pdf 198 KB 11 Feb 16:05 v2;
invoice_NS-10493.pdf 318 KB 10 Feb 11:21 v1; parcel_damage_7713.jpg 2.4 MB 12 Feb 10:08 v1;
customer_export_2026-02-10.zip 128 MB 10 Feb 23:14 v1; customer_export_2026-02-12.zip 131 MB 12 Feb 21:56 v1.
Detail delivery_confirmation_19.pdf: 684 KB; v3; application/pdf; AES-256; checksum e71b6d…; Uploader
support-service; Modified 12 Feb 2026 18:42 UTC. Versions: v3 12 Feb 18:42 metadata update; v2 18:39 upload
complete; v1 18:38 object created.
- **No personal identifier in the image.** The link comes only from activity_4007: object_storage / **object_19**
  "belongs only to priya.raman@gmail.com and user_07; no other subject is linked" (this satisfies the rule_06
  condition).
- Case: **case_61** (priya.raman@gmail.com, PARTIALLY_COMPLETE, audit 02-14T10:00) → SUPPORT_ATTACHMENT DELETE →
  `REPORT_REMAINING_RECORD object_storage object_19 PRESENT evidence_46` → DELETE → VERIFY_RECORD_ABSENT.
- **Filename decoy**: evidence_38 (customer_data_regional_replicas_20260330.sql) has support_3802 with
  file_name "delivery_confirmation_19.pdf" uploaded_by lucia-garcia@proton.me. The same filename belongs to a
  different user. Never match on filename alone.
- The other 7 objects are unlinked (no other evidence names them) → do not report.

### evidence_55 — documents/security_retention_extract.pdf (security_service, 2026-09-05T06:30:00Z)
"COMPLIANCE JOURNAL - SIGNED RECORD EXTRACT, Reference CJX-20260905-0630". Product Northstar Shop Compliance
Journal; classification Internal Restricted; issued 05 Sep 2026 06:30 UTC. Event reference audit_record_003;
subject reference user_03; event Account closure recorded; actor automated account workflow; recorded 25 Aug 2026
04:03 UTC; **retain until 25 Aug 2027 04:03 UTC** (1-year retention). Journal partition 2026-Q3; record version 1;
storage class compliance-ledger; integrity seal valid; short fingerprint 8f0c…31ad (same as evidence_37).
- Supplies the "supplied retention period" for rule_12 → audit_record_003 must be RETAINED (VERIFY_RECORD_PRESENT),
  never deleted. Relevant to case_45. It is captured 30 min before evidence_37, and both are pre-audit.
- Implication: if a case's audit_at were after 2027-08-25, retention would lapse. No case is that late (max ~Oct 2026).

### evidence_58 — documents/delivery_correction_attachment.pdf (support_platform, 2026-09-12T07:30:00Z)
"DELIVERY ADDRESS CORRECTION REQUEST, Support reference CS-4827 / support_001". Page 1: Northstar Shop Delivery
Address Correction Request; reference CS-4827 / support_001; received 18 Jun 2026; **Priya Raman;
priya.raman@gmail.com; +91 98765 73142**; order ORD-20264827; preferred contact SMS; submitted 18 Jun 2026 10:24 UTC.
Customer request: change apartment number from 14B to 18B and call before delivery. Product: Stainless steel water
bottle, qty 2; carrier SwiftShip. Page 2 (attachment properties): file delivery_address_correction.pdf; 312 KB;
ticket CS-4827; region ap-south; uploader customer; captured 12 Sep 2026 07:30 UTC; checksum prefix c90a42.
- Sample **case_07** gold: `FINDING support_platform support_001 REPORT_REMAINING_RECORD PRESENT evidence_58` →
  DELETE_RECORD → VERIFY account_007 absent + support_001 absent. So a customer-uploaded attachment that belongs
  only to the subject = SUPPORT_ATTACHMENT → DELETE (not REDACT). The request text calls it an "identity document"
  but the PDF is an address correction. Don't require semantic match.
- Trap: eval **case_61** (same Priya, audit 2026-02-14) must NOT use evidence_58 (captured 09-12), and the content
  date (18 Jun) is also after Feb.
- support_001, CS-4827 and ORD-20264827 appear in no other evidence or activity.

### evidence_60 — images/marketing_profile_console.png (marketing_platform, 2026-09-16T07:20:00Z)
"Audience Operations". **Soo-jin Park** [Live], `marketing_001 · sj.park@naver.com · +82 10-5837-9451`.
Market South Korea; Language Korean; Email opt-in Yes; SMS opt-in No; Last refreshed 15 Sep 2026 23:40 UTC.
Profile activity: 23:40 Product-category update (Desk accessories · Drinkware); 23:38 Campaign eligibility check
(Autumn offers · Eligible); 23:35 Profile refresh (Live profile fields updated); 23:32 Audience evaluation (Returning
customers — East Asia). Audience membership: Returning customers — East Asia; Segments Repeat customer · Home &
lifestyle · Mobile shopper; Preferred categories Desk accessories · Drinkware; Last campaign Autumn offers; Open
rate 32.4%; Click rate 6.8%. Activity: Autumn offers 32.4% open; Home & Lifestyle Picks 28.7% open; Profile
refreshed from live data.
- The displayed identity is NOT in identities or the audit log (7 "Soo-jin" users exist: Yoon, Lee, Cho, Kim, Kang,
  Han, Jung; none is Park). The catalog links marketing_001 to **kwame-mensah@proton.me / user_09** (Kwame Mensah,
  +233 24 456 1267). See headline 4.
- Case: **case_63** (kwame-mensah, NOT_STARTED, audit 09-17T09:20). Probable answer: `REPORT_REMAINING_RECORD
  marketing_platform marketing_001 PRESENT evidence_60` → DELETE → VERIFY_RECORD_ABSENT. "Profile refreshed from
  live data" also suggests a live sync may be recreating it, but no data_flow id is given, so don't invent one.

---

## 2. Case → image/PDF quick map (eval unless marked)

| case | email (user) | audit_at | evidence (captured) | likely step(s) from this file |
|---|---|---|---|---|
| case_33 | ingrid.dahl (user_18) | 07-19T13:00 | evidence_18 (07-18T11:00) | REPORT_REMAINING_RECORD export_service export_1842 (maybe also export_1260 via evidence_23) |
| case_34 | haruka.s1838 (user_11) | 09-27T13:00 | evidence_04 (09-26T11:00) | REPORT_REMAINING_RECORD account_service account_5762; also support_9538 attachment (old phone) via evidence_01 |
| case_35 | g.silva76 (user_13) | 09-02T08:00 | evidence_09 (09-01T06:00) | REPORT_REMAINING_RECORD search_service search_428 (NOT search_1874) |
| case_39 | jain.aditi (user_14) | 08-08T10:00 | evidence_14 (08-07T08:00) | REPORT_ACTIVE_DATA_FLOW integration_service data_flow_1121 |
| case_45 | oliver-bennett (user_03) | 09-06T09:00 | evidence_37 (09-05T07:00) + evidence_55 (09-05T06:30) | VERIFY_RECORD_PRESENT security_service audit_record_003 |
| case_46 | leonie.g9352 (user_17) | 03-11T08:00 | evidence_42 (03-10T06:00) | VERIFY_RECORD_REDACTED identity_service tombstone_17 |
| case_50 | darwish.omar (user_20) | 07-14T12:00 | evidence_19 (07-13T10:00) | REPORT_EXPOSED_PII analytics_platform analytics_7438 → ANONYMIZE |
| case_52 | ingrid.dahl (user_18) | 06-19T14:00 | evidence_23 (06-18T12:00) | REPORT_REMAINING_RECORD export_service export_1260 |
| case_53 | kagyeman8947 (user_22) | 05-25T09:00 | evidence_28 (05-24T07:00) | REPORT_EXPOSED_PII support_platform support_1034 → REDACT |
| case_55 | areed1433 (user_16) | 04-30T11:00 | evidence_32 (04-29T09:00) | REPORT_RESTORE_RISK backup_service backup_9287 → BLOCK_RESTORE |
| case_61 | priya.raman (user_07) | 02-14T10:00 | evidence_46 (02-13T08:00) | REPORT_REMAINING_RECORD object_storage object_19 |
| case_63 | kwame-mensah (user_09) | 09-17T09:20 | evidence_60 (09-16T07:20) | REPORT_REMAINING_RECORD marketing_platform marketing_001 (identity mismatch, see above) |
| sample case_07 | priya.raman (user_07) | 09-12T08:00 | evidence_58 (09-12T07:30) | gold: REPORT_REMAINING_RECORD support_platform support_001 |
| sample case_15 | lucia-torres (user_15) | 09-15T12:00 | evidence_14 shows data_flow_9846 | gold cites evidence_01 instead (latest) |
| sample 08/12/17/21/24/29 | — | 09-14/15 | evidence_27 legal register | gold: no legal-hold steps |

These cases still need the account_service account_XXXX VERIFY_RECORD_ABSENT step and the security audit_record
VERIFY_RECORD_PRESENT step that almost every sample answer has. Those IDs must come from other evidence: SQL, JSON,
logs (not from images). Several "image cases" may lack a pre-audit source for the account ID, which is a risk to
investigate.

## 3. Traps checklist (images/PDFs)
- Evidence captured after audit_at: evidence_01 (09-15) for cases 33/35/39/50/52/53/55/61/46. evidence_58 for case_61.
  evidence_27 for case_46.
- Batch cases with audit_at == captured_at exactly (case_93–102 at 09-01T06:00, 143–152 at 08-07T08:00,
  183–192 at 07-18T11:00, 193–202, 243–252, 283–292, 293–302, 343–352, 83–92 at 09-06T07:00, 443–452, 493–502,
  64–72 at 09-16T09:00 …). The cutoff must be inclusive (`<=`).
- Near-duplicate email: g.silva76.jr@gmail.com vs g.silva76@gmail.com.
- Same filename for different owners: delivery_confirmation_19.pdf (object_19 Priya vs support_3802 lucia-garcia).
- Staff/business emails (@northstar.shop, @company.com, bluepeakco@outlook.com) as decoys in list views.
- Non-subject rows in multi-row consoles: exports 1258/1259/1261, backups 9286/9288/9291, data_flow_9846
  (belongs to another case), connectors "Order notifications" and "Delivery tracking", audit_record_001/002/004–006,
  and 7 unlinked objects.
- The display label is not the resource id: user_17 → tombstone_17; NST-2026-0718-1842 → export_1842;
  CS-5034 → support_1034; CS-8538 → support_9538; CS-4827 → support_001.
- Origin label vs system: evidence_18 origin account_history_service, but system_id is export_service (from the
  catalog). evidence_46 system is `object_storage` (activity target_system), not `object_store` (used by
  CREATE_EXPORT rows).
- Historical identifiers in content: Haruka's old phone +81 90 6156 0005 appears in support_9538's attachment
  (evidence_01).
- Retention dates in documents: backup_9287 retention end 26 Jul 2026 (still retained at the 04-30 audit);
  audit_record_003 retain until 2027-08-25; legal holds until 2033; export_1260 "expires 25 Jun" (a claim only).
