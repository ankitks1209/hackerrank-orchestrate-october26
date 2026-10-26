# 03 — Log evidence (`dataset/evidence/logs/`, 26 files)

Scope: every file under `dataset/evidence/logs/`. All counts below come from the scripts in
`solution/notes/scripts/` (stdlib only):

| Script | Purpose |
|---|---|
| `logparse.py` | Universal line parser for all 7 line formats. It returns `ts, level, service, trace, event, kv`. |
| `observe.py` | Pulls out every line that has a `resource_id`. It attaches subject keys from the same trace plus inline keys, then resolves them against `user_identities.csv` and `user_audit_log.csv`. The result goes to `log_observations.json` (1336 observations). |
| `classify.py` | Maps each observation to a normalized state, such as ABSENT, PRESENT, EXPOSED, ANONYMIZED, REDACTED, ACTIVE, DISABLED, RESTORE_ACTIVE or BLOCKED. |
| `percase.py` | Groups the log observations by case and marks each one OK or LATE (`captured_at` vs `audit_at`). Its output is in `03_logs_percase_sample.txt` and `03_logs_percase_eval.txt` (203 eval cases have at least one log hit). |

---

## 1. Inventory: manifest, origin and capture time

| file_id | file | origin | captured_at | lines | format |
|---|---|---|---|---|---|
| evidence_48 | operations_stream_me_central_20260203.log | central_observability_export | 2026-02-03T05:59:42Z | 103 | pipe |
| evidence_64 | resource_lookup_trace_20260218_083911.log | service_readback_logs | 2026-02-18T08:39:11Z | 54 | logfmt-readback |
| evidence_44 | application_trace_eu_north_20260302.log | central_observability_export | 2026-03-02T10:59:23Z | 125 | bracket |
| evidence_67 | resource_lookup_trace_20260310_061801.log | service_readback_logs | 2026-03-10T06:18:01Z | 4 | logfmt-readback |
| evidence_41 | notification_delivery_20260315.log | downstream_delivery_service | 2026-03-15T07:00:00Z | 39 | diag |
| evidence_39 | syslog_archive_ap_southeast_20260325.log | central_observability_export | 2026-03-25T08:59:44Z | 114 | RFC5424 syslog |
| evidence_70 | resource_lookup_trace_20260414_054007.log | service_readback_logs | 2026-04-14T05:40:07Z | 50 | logfmt-readback |
| evidence_34 | structured_service_events_ca_central_20260419.log | central_observability_export | 2026-04-19T06:59:43Z | 136 | ts + JSON |
| evidence_73 | resource_lookup_trace_20260509_104353.log | service_readback_logs | 2026-05-09T10:43:53Z | 68 | logfmt-readback |
| evidence_30 | service_events_sa_east_20260516.log | central_observability_export | 2026-05-16T11:58:25Z | 110 | logfmt |
| evidence_76 | resource_lookup_trace_20260529_074313.log | service_readback_logs | 2026-05-29T07:43:13Z | 48 | logfmt-readback |
| evidence_25 | cloud_runtime_export_us_west_20260608.log | central_observability_export | 2026-06-08T09:58:28Z | 128 | cloud (nested message) |
| evidence_79 | resource_lookup_trace_20260623_053726.log | service_readback_logs | 2026-06-23T05:37:26Z | 60 | logfmt-readback |
| evidence_21 | operations_stream_eu_central_20260705.log | central_observability_export | 2026-07-05T07:54:27Z | 128 | pipe |
| evidence_82 | resource_lookup_trace_20260713_093359.log | service_readback_logs | 2026-07-13T09:33:59Z | 54 | logfmt-readback |
| evidence_85 | resource_lookup_trace_20260728_054417.log | service_readback_logs | 2026-07-28T05:44:17Z | 46 | logfmt-readback |
| evidence_16 | application_trace_ap_northeast_20260730.log | central_observability_export | 2026-07-30T08:53:12Z | 93 | bracket |
| evidence_88 | resource_lookup_trace_20260822_103910.log | service_readback_logs | 2026-08-22T10:39:10Z | 46 | logfmt-readback |
| evidence_11 | syslog_archive_us_east_20260824.log | central_observability_export | 2026-08-24T13:56:43Z | 118 | RFC5424 syslog |
| evidence_08 | search_index_diagnostic_20260906.log | search_index_service | 2026-09-06T07:00:00Z | 36 | diag |
| evidence_91 | resource_lookup_trace_20260911_074253.log | service_readback_logs | 2026-09-11T07:42:53Z | 62 | logfmt-readback |
| evidence_01 | service_events_ap_south_20260915.log | central_observability_export | 2026-09-15T11:59:39Z | 104 | logfmt |
| evidence_61 | support_replica.log | support_platform | 2026-09-17T22:00:19Z | 10 | logfmt (+variant) |
| evidence_06 | structured_service_events_eu_west_20260918.log | central_observability_export | 2026-09-18T11:55:24Z | 112 | ts + JSON |
| evidence_94 | resource_lookup_trace_20260926_103856.log | service_readback_logs | 2026-09-26T10:38:56Z | 58 | logfmt-readback |
| evidence_53 | cloud_runtime_export_af_south_20260930.log | central_observability_export | 2026-09-30T11:59:44Z | 305 | cloud (nested message) |

`captured_at` always equals the timestamp of the last line in the file. No line is dated after `captured_at`.
Line timestamps can be up to 8 days earlier than `captured_at`; see §5.

---

## 2. Line formats: a parser must handle 7 variants

Every line starts with an ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` followed by one space. After that:

1. **logfmt** (`service_events_*`, `support_replica.log`): `level=DEBUG service=search_service instance=search-2 pod=… region=… trace_id=tr-5887496 event=index_query_started match_key="g.silva76.jr@gmail.com" attempt=1`
   - Values are usually unquoted. Values containing `@`, spaces or `+` are double-quoted (`correlation_key="…"`, `matched_value="+81 90 6156 0005"`).
   - `support_replica.log` line 8 has no `trace_id`. Its `lookup_key` sits on the *completed* line itself, plus `source=case_archive`.
2. **logfmt-readback** (`resource_lookup_trace_*`): `level=INFO service=account_service trace_id=rb-074950-001 event=profile_lookup_completed resource_id=account_2064 rows=0 http_status=404`
   - Never quoted. `null` is a literal string.
   - `trace_id=rb-HHMMSS-NNN` encodes the time and a sequence number.
   - The `export_started target_count=N mode=point_in_time` line is matched by `export_completed queries=N dropped=0`.
3. **ts + JSON** (`structured_service_events_*`): `{"severity":"WARN","logger":"…","service":"…","instance":"…","trace_id":"tr-…","resource_id":"…","event":"…",…}`. Every value is a JSON string, including `"rows":"1"` and `"enabled":"false"`.
4. **RFC5424 syslog** (`syslog_archive_*`): `<15>1 node-1 account_service tr-4973247 - - level=DEBUG instance="account-2" … event="profile_lookup_completed" rows="1" http_status="200"`
   - Field order: PRI/version, host, **app = service**, **procid = trace id**, `- -`, then key="value" pairs.
   - PRI maps to level: `<15>` DEBUG, `<14>` INFO, `<12>` WARN.
5. **bracket** (`application_trace_*`): `[INFO] [account_service] [tr-6074163] profile_lookup_completed: instance="account-5" … resource_id="account_7947" rows="0" http_status="404"`. The event name is the token before `:`.
6. **pipe** (`operations_stream_*`): `| DEBUG | security_service | tr-5156005 | audit_record_read_completed | instance="security-6" … correlation_key="user_211"`. The columns are level, service, trace, event and a kv body.
7. **cloud nested** (`cloud_runtime_export_*`): `requestId=tr-2263120 level=DEBUG function=profile_service message="instance=\"profile-3\" … event=\"profile_lookup_completed\" rows=\"1\" … correlation_key=\"a.watanabe06@yahoo.com\""`. Service is `function`, the trace is `requestId`, and the real kv pairs are inside the escaped `message` string, which needs a second parsing pass.
8. **diag** (`search_index_diagnostic_*`, `notification_delivery_*`): `INFO service=search_index_service event=record_lookup seq=3 system="account_service" resource_id="account_2449" record_type="USER_PROFILE" result="NOT_FOUND" subject_reference="liam-walker@proton.me"`. The level is a bare word.

Header and trailer lines:
- **Central exports** open with `log_router export_started expected_source_events=N`. They close with `export_completed source_events=N auxiliary_events=4 [dropped_auxiliary=k]`.
- **Missing header/trailer** (export truncated at the edges): evidence_48 and evidence_30 have no `export_started`. evidence_53, evidence_25 and evidence_39 have no `export_completed`. evidence_11 has neither.
- **Event counts still match:** source-event counts equal `expected_source_events` in every case. The headers are cosmetic and no rows are lost.

---

## 3. How lines link to a person (two linking styles plus pseudonymous ids)

**A. Trace-joined (most common).** A `*_started` line carries the subject key. The `*_completed` or `*_scan` line with the same trace id carries the `resource_id`. Key names vary by service:

| service | started event | key name | completed / state event |
|---|---|---|---|
| account_service | profile_lookup_started | `lookup_key` (email) | profile_lookup_completed |
| search_service | index_query_started | `match_key` (email) | index_query_completed |
| security_service | audit_record_query_started | `subject_ref` (user_id) | audit_record_read_completed |
| analytics_platform | analytics_profile_scan_started | `lookup_key` (email, **or the analytics id itself**) | analytics_identity_scan / analytics_profile_read / contact_lookup_completed |
| support_platform | message_scan_started / attachment_scan_started | `subject_key` (email or user_id) / `scan_key` (email or phone) | message_pii_scan / attachment_pii_scan / message_read |
| integration_service | connector_config_read_started | `subject_key` (email or user_id) | connector_heartbeat / connector_config_loaded |
| backup_service | restore_policy_check_started | `subject_key` (email or user_id) | restore_candidate_evaluated / restore_authorization_completed |
| export_service | export_download_check_started | `owner_key` (email) | export_download_check_completed |
| legal_service | retained_order_query_started | `subject_ref` (user_id) | retained_order_loaded |
| readback (all) | `*_read_started` / `*_lookup_started` | `lookup_key` (email, user_id or `null`) | `*_completed`. This style also carries inline `email=` / `customer_email=` / `requester_email=` / `owner_email=` / `customer_reference=` / `subject_reference=`. |

- **Traces interleave.** In evidence_01, for example, L16 `lookup_key=leonie…` is followed by L17–L20 and L18 is a different trace (darwish). The account result arrives at L21. Join on the trace id, not on adjacency. 17 started lines in evidence_01 are not followed directly by their own trace.
- **Trace ids are unique per lookup.** No trace carries two resource_ids. No trace's started key conflicts with an inline key on the same trace (0 conflicts).
- **Where the trace id lives:** bracket `[tr-…]`, pipe column 3, syslog procid, JSON `trace_id`, cloud `requestId`, logfmt `trace_id`.

**B. Inline single line.** The completed line carries `correlation_key="<email | user_N | sha256>"`. There is no started line. Example (evidence_01 L22): `resource_id=account_4745 event=profile_lookup_completed rows=0 http_status=404 correlation_key="lucia-torres@gmail.com"`.

**C. Diag files.** These use `subject_reference="<email>"` or `"user_N"`. One line has `subject_reference=""` (evidence_08 seq=15 analytics_9500 ANONYMIZED, unlinkable).

Link kinds resolved over all 1336 observations:
- current email: 922
- user_id: 361
- **historical (old) email: 202**
- **old phone: 2**: evidence_01 L23/L25 `scan_key/matched_value="+81 90 6156 0005"`, the old phone of user_11 (audit_279)
- **old email hash: 1**: evidence_01 L92 `correlation_key="44a65154…f10e"` = sha256("minjun.kim90@gmail.com"), the old email of user_12 (audit_283)
- unresolved: 21

Rules that follow from this:
- **`email_hash` = sha256 of the lowercased email** (verified). Hash every historical email from `user_audit_log.csv` as well.
- **Emails appear in UPPERCASE** in 8 files, e.g. `OBI.ADAEZE@ICLOUD.COM`, `NILS.L200695@ZOHO.COM`, `JULES-LAURENT@PROTON.ME`. 20 eval request emails are uppercase too. Compare case-insensitively.
- **Request emails can be historical.** 95+5 of the 518 eval request emails are historical rather than current (sample: 3 of 32). Example: case_43 `javier.r940897@outlook.com` gives account_8681 PRESENT via the old email in evidence_94.
- **Compliant records link only by user_id.** A redacted support ticket, a disabled data flow and a blocked backup in readback files have `lookup_key=user_N` and `customer_reference=user_N`, with the email set to `null`. Index `user_id` as a key.
- **Anonymized analytics are not linkable inside the logs.** Readback lines have `lookup_key=null` and every field null (30 lines). Central `analytics_profile_read direct_identifiers=0` lines are joined to a scan whose `lookup_key` is the analytics id itself, e.g. `lookup_key="analytics_257"` (21 lines).
  - Gold case_03 still credits `analytics_9406` (evidence_94 L42–43, every field null) as VERIFY_RECORD_ANONYMIZED. The link must come from elsewhere.
  - `system_activity.csv` has `ANONYMIZE_RECORD … analytics_9406` (activity_3852, 2026-09-15T10:31:16Z). That row comes 24 minutes after `DELETE_RECORD account_7566` (activity_3851; account_7566 belongs to user_43).
  - Batch timing is ambiguous, though. analytics_5589 was anonymized 15 seconds later in the same batch, which also deleted account_2064 (user_42) and account_6523 (user_17).
  - The deletion_worker pattern: account deletes run at HH:4x–HH+1:1x and anonymizations at **HH:31:ss**. That gives 1–3 candidate accounts per anonymized record (table in §8).
  - **Open question:** an analytics-to-user mapping may exist in a non-log artifact, such as images or `analytics_profile_view_*.png`. No `.sql`, `.json` or `.txt` file contains `9406`.

---

## 4. Event vocabulary and resource-state semantics

All event types (central exports, 1576 lines). Noise events are marked `[noise]`.

| service | event | state meaning |
|---|---|---|
| account_service | profile_lookup_completed | `rows=0 http_status=404` → ABSENT (100 lines); `rows=1 http_status=200` → PRESENT (16 lines) |
| profile_service | profile_lookup_completed | **Decoy, 300 lines, evidence_53 only.** Always `rows=1 200` and 5-digit `account_NNNNN`, for 300 distinct current users. **None of those users has any request** (sample or eval). The service is not `account_service`; ignore it. |
| search_service | index_query_completed | always `result=hit index=customer_directory_v3` → PRESENT (REPORT_REMAINING_RECORD → DELETE). The logs never record a miss. |
| security_service | audit_record_read_completed | always `rows=1 integrity_check=passed` → RETAIN / VERIFY_RECORD_PRESENT |
| analytics_platform | analytics_identity_scan | `matched_value=<email> direct_identifiers=1 detector=direct_identifier` → REPORT_EXPOSED_PII → ANONYMIZE |
| analytics_platform | analytics_profile_read | `direct_identifiers=0 email=null phone=null` → ANONYMIZED (but unlinked) |
| analytics_platform | contact_lookup_completed | **one line only** (evidence_01 L92): `rows=1 email_opt_in=true correlation_key=<old hash>`. Gold treats it as REPORT_REMAINING_RECORD → **DELETE_RECORD** (marketing-contact style; rule_10), not ANONYMIZE. |
| support_platform | message_pii_scan | `matched_value=<email> detector=direct_identifier` → REPORT_EXPOSED_PII → REDACT (rule_05) |
| support_platform | attachment_pii_scan | `matched_value=<email/phone> file=delivery_confirmation_NN.pdf` → attachment present (7 lines). Activity always shows `DELETE_RECORD` targeting these support ids, often `FAILED`. So: REPORT_REMAINING_RECORD → DELETE (rule_06). |
| support_platform | message_read | `message_text="[REDACTED]"` with `subject_ref=user_N` → REDACTED |
| integration_service | connector_heartbeat | `enabled=true scheduler_registered=true last_run=success` (WARN) → REPORT_ACTIVE_DATA_FLOW |
| integration_service | connector_config_loaded | `enabled=false scheduler_registered=false` → DISABLED |
| backup_service | restore_candidate_evaluated | `eligible=true deletion_block=false` (level ERROR) → REPORT_RESTORE_RISK |
| backup_service | restore_authorization_completed | `decision=deny policy=privacy_deletion` → BLOCKED |
| export_service | export_download_check_completed | `file=customer_export_N.zip available=true` → PRESENT (DELETE) |
| legal_service | retained_order_loaded | `resource_id=legal_hold_4961 reason=payment_dispute_and_tax_record access=allowed` → RETAIN (1 line, evidence_21; links via subject_ref=user_218) |
| log_router | export_started / export_completed | header and trailer only |
| `[noise]` | cache_lookup (always `result=miss`), connection_acquired (pool `*_primary`/`*_replica`), dependency_retry (`reason=read_timeout`) → dependency_recovered (`route=primary`) | per-trace chatter; it does not change state |
| `[noise]` | dns_cache, queue_consumer, secret_agent, webhook_delivery (`delivery_abandoned http_status=503`, level ERROR), cert_agent, checkpoint_writer, circuit_breaker, feature_flags, http_client, kernel_monitor, lambda_extension, runtime_config, scheduler, systemd, thread_pool | auxiliary; exactly 4 per central file |

Readback traces (`resource_lookup_trace_*`, 550 lines) have clean binary signatures:

| event | non-compliant | compliant |
|---|---|---|
| profile_lookup_completed | `rows=1 http_status=200 email=<x> phone=null customer_reference=null` (12) | `rows=0 http_status=404` (38) |
| index_query_completed | `result=hit total_hits=1 email=<x>` (50, always non-compliant) | – |
| analytics_profile_read_completed | `email=<x>` (9) → EXPOSED | all of `customer_reference/email/phone/email_hash` = null (30) → ANONYMIZED |
| support_ticket_read_completed | `requester_email=<x>`, name and phone null (23) → EXPOSED → REDACT | all requester_* null, `customer_reference=user_N` (11) → REDACTED |
| connector_config_read_completed | `enabled=true last_delivery_status=delivered customer_email=<x>` (23) → ACTIVE | `enabled=false last_delivery_status=stopped customer_reference=user_N` (11) → DISABLED |
| restore_policy_read_completed | `archive_present=true restore_allowed=true customer_email=<x>` (4) → RESTORE RISK | `restore_allowed=false customer_reference=user_N` (11) → BLOCKED |
| export_metadata_read_completed | `available=true owner_email=<x> object_key=…` (5) → PRESENT | – |
| audit_record_read_completed | `rows=1 subject_reference=user_N event_code=… retention_until=2031..2034` (37) → RETAIN | – |

- `connector_name` values: analytics_identity_bridge, search_profile_indexer, support_profile_sync, customer_events_connector.
- `event_code` values: ACCOUNT_DELETION_RECORDED, SUBJECT_REQUEST_AUDITED, IDENTITY_CHANGE_RECORDED, PRIVACY_REQUEST_ACCEPTED.

Diag files (evidence_08, evidence_41):
- `record_type` maps directly to the `deletion_rules.csv` category: USER_PROFILE, SEARCH_INDEX_ENTRY, SECURITY_AUDIT_LOG, ANALYTICS_PROFILE, SUPPORT_MESSAGE, DATA_FLOW, BACKUP_ARCHIVE.
- `result` values: FOUND (present, or retained for audit), NOT_FOUND (absent), IDENTIFIABLE (exposed PII), ACTIVE (data-flow or restore risk), ANONYMIZED.
- `system_id` comes from the `system=` field, not from the file's origin. For example, a "search_index_service" file reports on account_service and others.
- **A stale line in the same file:** evidence_08 seq=1 is dated 2026-08-31 (`account_8473 FOUND marek.zielinski`). seq=8 at 2026-09-06 has `account_8473 NOT_FOUND`. The latest line per resource wins (case_86, audit 2026-09-06T07:00).

`support_replica.log` (evidence_61):
- `contact_query_completed rows=1` → PRESENT.
- `deletion_marker_check marker_found=false last_write=…` → still present, no deletion marker. Gold: REPORT_REMAINING_RECORD → DELETE.

**Log level is not a state signal.** ERROR is used both for real restore risks and for webhook noise, and WARN covers heartbeats, PII scans and retries.

---

## 5. Time traps (most important)

1. **Use the manifest `captured_at`, not the line timestamp.** Proof from sample case_09 (audit 2026-09-16T09:00):
   - evidence_06 L83 (`2026-09-16T08:57:31Z backup_4978 restore_candidate_evaluated eligible=true deletion_block=false`) is dated before audit_at, but the file was **captured 2026-09-18**.
   - Gold cites **evidence_93** (inventory SQL captured 2026-09-16T08:37:39Z) for the same finding, not evidence_06.
   - `captured_at == audit_at` is allowed: evidence_03, captured 2026-10-01T12:00:00Z, is cited for cases with audit 2026-10-01T12:00:00Z.
2. **Cohort structure.** Each log file serves one cohort of about 10 consecutive cases that share one `audit_at`. The file is captured 0–20 minutes before that audit. Mapping (cohort audit → files):

   | cohort | audit_at | on-time log | late log (captured after audit, do NOT cite) |
   |---|---|---|---|
   | case_513–522 | 02-03T06:00 | evidence_48 | |
   | case_483–492 | 02-18T09:00 | evidence_64 | |
   | case_463–472 | 02-28T11:00 | – | **evidence_44** (cap 03-02) |
   | case_46 | 03-11T08:00 | evidence_67 | evidence_01 |
   | case_433–442 | 03-15T07:00 | evidence_41 | |
   | case_413–422 | 03-25T09:00 | evidence_39 | |
   | case_373–382 | 04-14T06:00 | evidence_70 | |
   | case_363–372 | 04-19T07:00 | evidence_34 | |
   | case_323–332 | 05-09T11:00 | evidence_73 | |
   | case_313–322 | 05-14T12:00 | – | **evidence_30** (cap 05-16) |
   | case_283–292 | 05-29T08:00 | evidence_76 | |
   | case_263–272 | 06-08T10:00 | evidence_25 | |
   | case_233–242 | 06-23T06:00 | evidence_79 | |
   | case_213–222 | 07-03T08:00 | – | **evidence_21** (cap 07-05) |
   | case_193–202 | 07-13T10:00 | evidence_82 | |
   | case_163–172 | 07-28T06:00 | evidence_85 | **evidence_16** (cap 07-30) |
   | case_113–122 | 08-22T11:00 | evidence_88 | **evidence_11** (cap 08-24) |
   | case_83–92 | 09-06T07:00 | evidence_08 | |
   | case_73–82 | 09-11T08:00 | evidence_91 | |
   | case_12,15,17,19 (sample) | 09-15T12:00 | evidence_01 | |
   | case_10 (sample) | 09-18T12:25 | evidence_61 | |
   | case_09 (sample), case_64–72 | 09-16T09:00 | – | **evidence_06** (cap 09-18) |
   | case_03,18,20 (sample) + case_43,44,47,48,49,51 | 09-26T11:00 | evidence_94 | |
   | singles case_33,35,39,50,52,55 | various | – | evidence_01 (decoy for earlier audits) |
   | case_34 | 09-27T13:00 | evidence_01 (dated *before* requested_at 09-24) | evidence_53 |

   Cohorts with no on-time log must be solved from DB, record or image evidence: 463–472, 313–322, 213–222 and 64–72.
3. **Late exports include "after-audit" tail lines that flip state.** The main batch sits minutes before the cohort audit. A few lines sit near the later `captured_at` and show the state changing, i.e. recreation:
   - evidence_44: account_1698 (case_463) ABSENT 02-28T10:59:43, then **PRESENT 03-02T10:59:21**.
   - evidence_21: account_1956 (case_215) ABSENT 07-03, then PRESENT 07-05.
   - evidence_30: account_2088 (case_319) ABSENT 05-14, then PRESENT 05-16.
   - evidence_16: account_5284 (case_167) ABSENT 07-28, then PRESENT 07-30.
   - evidence_06/16/11 also end with extra `search … hit` lines for cohort users (case_67/72/170/121).

   Head lines can also be stale: evidence_44 L3 has account_7023 PRESENT on 02-22, then ABSENT on 02-28; evidence_06 L4 has account_6633 PRESENT on 09-10, then ABSENT on 09-16.
4. **Decoy users with earlier audits.** evidence_01 includes complete trace sets for users 11, 13, 14, 16, 18 and 20. Their eval cases (case_34/35/39/55/33+52/50) have earlier audits, except case_34.
   - Data-catalog rows `LINK_RESOURCE_IDENTITY` (activity_4000–4011) tie those resources to the users. Examples: search_428↔g.silva76, export_1260↔ingrid.dahl, backup_9287↔areed1433.
   - For audits before 2026-09-15T11:59:39Z, evidence_01 is unusable.
   - ingrid.dahl has **two** eval cases (case_33 with audit 07-19, case_52 with audit 06-19).
5. **Pre-request evidence.** leonie.g9352 (user_17) has two account generations:
   - evidence_67 (2026-03-10) gives account_6523 404, which serves case_46 (audit 03-11).
   - Sample case_17 (requested 2026-08-19) has gold `account_4092`, and the evidence is evidence_01 L21, not account_6523.
   - Prefer observations of the request's own account generation. Treat earlier-generation resources as stale.

---

## 6. Decoys and near-duplicates inside the logs

- **`.jr` suffix search hits** (an unknown email that differs from a real user only by `.jr`):
  - `g.silva76.jr@gmail.com` → search_1874 (evidence_01 L2–6) vs the real `g.silva76@gmail.com` → search_428 (L98–100)
  - `salma.hamdan.jr@outlook.com` → search_2843 (evidence_44)
  - `mrios9507.jr@fastmail.com` → search_021 (evidence_25)
  - `zulu.lindiwe.jr@gmail.com` → search_5252 (evidence_06)
  - This matches sample case_28's request text: "a search result with a similar email belongs to someone else".
- **support_replica (evidence_61):** `nadia.popescu@yahoo.com` → support_5914 (source=case_archive) is a near-duplicate of `nadia.petrescu@yahoo.com`, the *intermediate* email of user_10. `customer4104@yahoo.com` → support_4104 is unknown. `attachment_preview thumbnail_failed support_7731` is noise.
- **evidence_53** consists of 300 `profile_service` rows (`rows=1`, 5-digit account ids) for people with no requests. A naive "any account row=1 means INCOMPLETE" rule could be fooled by it, but no case matches.
- There are 21 unresolvable keys in total: the 4 `.jr` emails, 2 replica decoys, and 15 analytics ids used as their own lookup key.
- No observation links to two different users.

---

## 7. Sample cross-check: lines proving each gold step

### evidence_01 (service_events_ap_south_20260915.log, cap 2026-09-15T11:59:39Z; audits 2026-09-15T12:00Z)

**case_12 minjun.kim@gmail.com (user_12; old email minjun.kim90@gmail.com):** INCOMPLETE
- F1 `REPORT_REMAINING_RECORD analytics_9914 evidence_01` ← **L92** `resource_id=analytics_9914 event=contact_lookup_completed rows=1 email_opt_in=true correlation_key="44a65154…f10e"`. That key is sha256 of the *old* email (audit_283). The lookup reaches the user only through the hash ("systems that do not display the email"). Remediation is DELETE_RECORD, not ANONYMIZE.
- V `account_9797 ABSENT` ← L73 `lookup_key="minjun.kim@gmail.com"` → L76 `rows=0 http_status=404`.
- V `audit_record_2945 PRESENT` ← L63 `correlation_key="user_12"`.

**case_15 lucia-torres@gmail.com (user_15):** INCOMPLETE
- F1 `REPORT_ACTIVE_DATA_FLOW data_flow_9846 evidence_01` ← L85 `connector_config_read_started subject_key="lucia-torres@gmail.com"` (tr-9750867) → **L88** `connector_heartbeat enabled=true scheduler_registered=true last_run=success`.
- V `account_4745 ABSENT` ← L22, inline `correlation_key="lucia-torres@gmail.com"` with `rows=0 404`.
- V `audit_record_1596 PRESENT` ← L101 `subject_ref="user_15"` → L103.

**case_17 leonie.g9352@outlook.com (user_17):** INCOMPLETE
- F1 `REPORT_RESTORE_RISK backup_3245 evidence_01` ← L43 `restore_policy_check_started subject_key="leonie.g9352@outlook.com"` (tr-8210651; retry L50 and recover L52) → **L53** `restore_candidate_evaluated eligible=true deletion_block=false`.
- V `account_4092 ABSENT` ← L16 → **L21** `rows=0 404`. The traces interleave with L18.
- V `audit_record_1797 PRESENT` ← L33 `correlation_key="user_17"`.
- Ignore evidence_67's account_6523 (a previous account generation).

**case_19 e.varga90@yahoo.com (user_19):** INCOMPLETE
- F1 `REPORT_REMAINING_RECORD search_6083 evidence_01` ← **L36** `index_query_completed result=hit correlation_key="e.varga90@yahoo.com"`.
- F2 `REPORT_EXPOSED_PII support_9553 evidence_01` ← L11 `message_scan_started subject_key=…` → **L15** `message_pii_scan matched_value="e.varga90@yahoo.com" detector=direct_identifier`. Remediation is REDACT, because the conversation is shared (request text).
- V `account_9102 ABSENT` ← L70 → L72. V `audit_record_6793 PRESENT` ← L37 `subject_ref="user_19"` → L44.

Other user lines in evidence_01 that are **not** in any sample gold:
- haruka: support_9538 attachment via old phone, account_5762, audit_3753
- g.silva: account_8491, search_428, audit_8925
- jain.aditi: account_8926, search_4801, data_flow_1121 ACTIVE, audit_7301
- areed: account_9494, search_4882, backup_9287 RESTORE_ACTIVE, audit_2857
- ingrid: account_2373, search_2352, export_1260 available, audit_8486
- darwish: account_3270, search_4639, analytics_7438 EXPOSED, audit_5080

All of these are for eval cases whose audits fall before the capture (except case_34).

### evidence_94 (resource_lookup_trace_20260926_103856.log, cap 2026-09-26T10:38:56Z; audits 2026-09-26T11:00Z)

**case_03 l.fontaine46@yahoo.com (user_43):** COMPLETE
- V1 `account_7566 ABSENT evidence_94` ← L18 `lookup_key=l.fontaine46@yahoo.com` / **L19** `rows=0 http_status=404`.
- V2 `audit_record_2016 PRESENT evidence_94` ← L34 `lookup_key=user_43` / **L35** `rows=1 subject_reference=user_43 event_code=IDENTITY_CHANGE_RECORDED retention_until=2034-09-30T23:59:59Z`.
- V3 `analytics_9406 ANONYMIZED evidence_94` ← L42 `lookup_key=null` / **L43** `customer_reference=null email=null phone=null email_hash=null audience_cohort=general_shopper`. Nothing in the file links it to the user; see §3.
- Decoy: analytics_5589 (L20–21) is adjacent to the account lookup in time (08:57:38) but is **not** the gold record.

**case_18 mori.ren@gmail.com (user_50):** INCOMPLETE
- F1 `search_4013 REMAINING` ← L52–53 `result=hit email=mori.ren@gmail.com`.
- F2 `analytics_037 EXPOSED_PII` ← L22–23 `email=mori.ren@gmail.com` → ANONYMIZE.
- F3 `support_5569 EXPOSED_PII` ← L10–11 `support_ticket_read_completed requester_name=null requester_email=mori.ren@gmail.com requester_phone=null` → REDACT.
- F4 `data_flow_4890 ACTIVE` ← L24–25 `enabled=true last_delivery_status=delivered connector_name=analytics_identity_bridge customer_email=mori.ren@gmail.com`.
- account_5521 and audit_record_6645 are not in the logs; they come from other sources and appear in verification with empty evidence.

**case_20 akosua.gyasi@gmail.com (user_48):** INCOMPLETE
- F1 `search_4262` ← L8–9 `result=hit`.
- F2 `data_flow_1770 ACTIVE` ← L40–41 `enabled=true … connector_name=customer_events_connector`.
- account_5037 (activity says DELETE FAILED on 09-09) and audit_record_5569 come from non-log evidence.

Eval cohort users in the same file:
- case_44 charlotte (user_42): account_2064 404, audit_1105, data_flow_223 DISABLED, support_1066 REDACTED, backup_6266 BLOCKED, all keyed by user_42. This looks COMPLETE-like.
- case_51 masuku (user_49): account_3610 404, data_flow_4713 DISABLED, backup_7809 BLOCKED, support_1097 REDACTED, audit_3308. Also COMPLETE-like.
- case_43 / 47 / 48 / 49: residue found via **old emails**.

### evidence_61 (support_replica.log, cap 2026-09-17T22:00:19Z)

**case_10 nadia.ionescu@yahoo.com (user_10).** The email chain is nadia.ionescu → nadia.petrescu (2025-12-13) → n.petrescu (2026-04-12); the request email is the oldest one.
- F1 `REPORT_REMAINING_RECORD support_002 evidence_61` ← L4 `trace_id=tr-rp-002 event=contact_query_started lookup_key=nadia.ionescu@yahoo.com source=legacy_contact_index` → **L5** `contact_query_completed resource_id=support_002 rows=1` → **L6** `deletion_marker_check resource_id=support_002 marker_found=false last_write=2026-09-07T10:01:00Z`. That last write comes after requested_at 2026-08-31.
- Decoys: L2–3, L7, L8 and L9.

---

## 8. Anonymized analytics vs deletion-worker batches (linking aid, not proof)

For each anonymized analytics resource, these are the account `DELETE_RECORD` rows in the 60 minutes before its `ANONYMIZE_RECORD`. Owners are resolved from log account lookups.

- **Unambiguous:** analytics_689→user_461, analytics_7277→user_519, analytics_8408→user_281, analytics_8037→user_191, analytics_349→user_200, analytics_2176→user_80, analytics_1161→user_71, analytics_4229→user_320, analytics_6099→user_311.
- **Ambiguous:** the remaining records have 2–3 candidates, e.g. analytics_9406/5589 → {user_42, user_17, user_43}. Gold says 9406→user_43.
- Full list: rerun the snippet in this notes session, or adapt `percase.py`.

---

## 9. Remediation, verification and order patterns seen in samples (for the planner)

- **Findings order:** REPORT_REMAINING_RECORD, then REPORT_EXPOSED_PII, then REPORT_ACTIVE_DATA_FLOW / REPORT_RESTORE_RISK. Within one operation, sort alphabetically by system (analytics < support; export < search).
- **Remediation:** DISABLE_DATA_FLOW / BLOCK_RESTORE first, then DELETE_RECORD, then REDACT_RECORD, then ANONYMIZE_RECORD.
- **Verification (INCOMPLETE):** account_service VERIFY_RECORD_ABSENT is always included, even when compliant. security_service audit VERIFY_RECORD_PRESENT is always included. Order: ABSENT (account first, then others alphabetically) < PRESENT < REDACTED < ANONYMIZED < DISABLED < BLOCKED. Every remediation/verification step uses `evidence_id=""`.
- **COMPLETE:** verification steps only, each citing the log file_id that proves the state.

## 10. Parser checklist

- Handle the 7 formats (§2), including the double-parse of the cloud `message`, JSON string values, syslog procid as trace, and pipe columns.
- Join `*_started` to `*_completed` by trace id, then take inline keys as well.
- Key index: lowercase current and historical emails; sha256 of every email; current and old phones (exact string with spaces); user_id.
- Filter files by manifest `captured_at <= audit_at`. Within a file, keep the latest line per resource_id.
- Drop `profile_service`, auxiliary services, cache, connection and retry chatter, and log_router lines.
- Do not trust `level`. Do not trust adjacency in time. Do not match `.jr` or near-duplicate emails; only exact (case-insensitive) identifier matches count.
