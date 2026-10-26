# Ghost Data Still Exists — Problem Analysis & Reverse Engineering

> Single consolidated brief. Deep-dive notes, per-case traces and runnable prototypes are in `solution/notes/` (index at the bottom).
> Nothing outside `solution/` was changed except the mandated append-only `log.txt`.

---

## 1. What the challenge really is

**Surface task:** for each of 518 deletion requests (`case_33..case_550`), output
`case_id, deletion_status ∈ {COMPLETE, INCOMPLETE, NOT_APPLICABLE}, steps_json` where steps are an ordered list of
FINDING → REMEDIATION → VERIFICATION objects `{step_no, phase, system_id, resource_id, operation, state, evidence_id}`.

**What is actually being tested (the "agenda"):**

| Skill under test | How the dataset tests it |
|---|---|
| Don't trust claims | `reported_status` and activity `reported_result` are deliberately wrong (SUCCESS-but-present, FAILED-but-absent). In samples, 11 "COMPLETE" claims are really INCOMPLETE; 3 "NOT_STARTED" are really COMPLETE. |
| Point-in-time reasoning | Every case has `audit_at`. Evidence files captured after it (and lines *inside* files timestamped after it) contain traps: recreated accounts, re-indexed search docs, "old report" snapshots. |
| Identity resolution | 100/518 request emails are historical (from `user_audit_log`), 20 are UPPERCASE, user_35 has a 2-hop email chain, hashes are sha256(lowercase email), one record links only via old-email hash, one via old phone. |
| Decoy rejection | `.jr` look-alike emails, near-name users (Karim El-Masri, Mateo Rios Gil, Joana Berg…), duplicate real names (Mateo Ríos ×2, Thandiwe Ndlovu ×2, Gabriel Costa ×2), 300-user noise log (evidence_53), ~66% noise activity rows, decoy policy rules. |
| Policy application | `deletion_rules.csv` maps category → DELETE/REDACT/ANONYMIZE/RETAIN. Support message (REDACT) vs attachment (DELETE); analytics profile (ANONYMIZE) vs marketing/secondary contact (DELETE); backups RETAIN + BLOCK_RESTORE; tombstones REDACT; security audit RETAIN. |
| Recreation risk | Active connectors (`data_flow_*`), restorable backups, replica drift (account alive in a replica but gone from primary), "active connector repopulated search_N". |
| Multimodal extraction | 11 PNG screens + 4 PDFs; the screen IDs differ from resource IDs (CS-5034 → support_1034, NST-…-1842 → export_1842). |
| Intent classification | Multilingual (EN/FR/ES/PT/JA/KO) requests; 10 non-deletion requests full of negated deletion keywords. |
| Engineering hygiene | Deterministic output, ordering, valid JSON, evaluation report, token/cost report, AGENTS.md logging (`log.txt` is the graded chat transcript). |

The scoring is against hidden canonical answers at case, step, field and sequence level, so **exact resource ids, the exact evidence_id, and the exact ordering all matter**.

---

## 2. Data map

| File | Rows | Role |
|---|---|---|
| `deletion_requests.csv` | 518 | Eval cases case_33..case_550. reported_status: 254 COMPLETE / 152 PARTIAL / 112 NOT_STARTED |
| `sample_deletion_requests.csv` + `sample_output.csv` | 32 | Gold examples (0 NOT_APPLICABLE, 9 COMPLETE, 23 INCOMPLETE) |
| `user_identities.csv` | 850 | user_id, name, email, phone, email_hash (= sha256(lower(email)), 850/850), updated_at. Only ~547 are case subjects; user_551..850 mostly decoys |
| `user_audit_log.csv` | 306 | email 107, email_hash 107 (paired), phone 92; names never change; all changes happen before the corresponding request |
| `system_activity.csv` | 4011 | Global event stream; ~2635 noise rows; worker rows carry the per-resource story; 12 `LINK_RESOURCE_IDENTITY` rows (activity_4000–4011) decode the image/PDF evidence; 10 `CLASSIFY_REQUEST … non-deletion` rows |
| `deletion_rules.csv` | 15 | Policy (see §5) |
| `evidence_files.csv` | 94 | file_id → path, origin, **captured_at** (the citation/admissibility clock) |
| `dataset/evidence/` | 94 files | 24 SQL, 28 JSON + 1 TXT, 26 logs, 11 PNG, 4 PDF |

### 2.1 Evidence families (details: notes 01–04)

- **SQL replica captures** (read / regional / reporting / failover, 11 files): every table is `resource_id, origin_system, collection_name, record_json, updated_at`. `origin_system` = output `system_id`. Drift = a row present in a replica table but missing from primary → account still exists. Must check *every* replica table (regional drift may be in only one of two).
- **SQL inventory captures** (`customer_data_inventory_*`, 11): 9 typed tables + `snapshot_scope`. A system in scope with 0 rows = proof of absence; a system not in scope = not observed.
- **JSON service exports** (`service_resource_export_*`, 11): per-system lookups (`status_code 404 + profile:null` = ABSENT; 200 = PRESENT even if only email left; analytics all-null = ANONYMIZED; `restore_allowed:false` = BLOCKED; `enabled:false/stopped` = DISABLED).
- **JSON snapshot bundles** (13): mostly captured ~2 days *after* their cohort's audit → mostly un-citable mirrors full of traps; `message_text:"[REDACTED]"`, `deleted_customer_references` (tombstones), `retained_order_records` (legal holds), empty `customer_profiles` = account absent.
- **Flat ledgers / handover TXT** (evidence_03, 13, 36, 50…): carry `record_type` (= policy category) and result FOUND/NOT_FOUND/IDENTIFIABLE/ANONYMIZED/ACTIVE/DISABLED/BLOCKED/REDACTED.
- **Logs** — 7 line formats (logfmt, unquoted logfmt with literal `null`, ts+JSON, syslog, bracketed app-trace, pipe-delimited, cloud-runtime with escaped nested `message="k=v…"`). Subject key sits on `*_started` line; resource + state on the `*_completed` line with same `trace_id` → **join on trace_id**, not adjacency.
- **Images/PDFs** — each is the only usable proof for one short-window eval case; linked by the `LINK_RESOURCE_IDENTITY` row timestamped exactly captured_at + 7m01s.

---

## 3. The structure the generator used (reverse engineered)

### 3.1 Two case families

1. **Hand-crafted "story" cases** — samples 01, 02, 04–08, 10 and eval **33, 34, 35, 39, 45, 46, 50, 52, 53, 55, 61, 63** (the "image family").
   - Ids like `account_00N`, `search_001`, `support_001/002`, `export_001`, `analytics_901`, `marketing_001`, `object_19`.
   - Short windows: reported 42 h after request, audited ~35 h later.
   - Proof is evidence_54..61 (samples) or one PNG/PDF (eval). The resource link comes from the LINK activity rows.
   - Samples in this family have **no security audit record**, so they have no VERIFY_RECORD_PRESENT step (e.g. case_06).
2. **Generated cohort cases** — everything else (samples 03, 09, 11–32 and ~496 eval cases).
   - Cohorts of ~10 consecutive cases share one `audit_at`.
   - Each cohort has **one primary proof file** captured just before or exactly at `audit_at`.
   - Each case has a full deletion-worker run in `system_activity.csv`.

### 3.2 The activity stream encodes per-resource truth (in its `details` templates, not in `reported_result`)

| `details` template | Meaning |
|---|---|
| "Deletion worker submitted primary profile account_N" | The case's account id. Exactly one per authorized case, about 0.7–1.3 h before `reported_at`. Its result mirrors `reported_status` (COMPLETE→SUCCESS, PARTIAL→PARTIAL, NOT_STARTED→FAILED). |
| "Policy action completed for X" | X is already compliant → verification only. |
| "Deletion worker received the final result for X from …" | X is a **violation** → finding. This holds even when the result says SUCCESS. |
| "Connector status check confirmed … remains enabled" | REPORT_ACTIVE_DATA_FLOW |
| "Restore-access check confirmed … can still be restored" | REPORT_RESTORE_RISK |
| "Replication worker reported its final checkpoint for account_N" | The account **still exists** (replica drift) → REPORT_REMAINING_RECORD on account_service. Matched 52/52. |
| "Active connector repopulated downstream resource search_N" | The flow recreated a search doc → report the flow as an active data flow. 29 eval cases have such a flow with no CHECK row. |
| "Privacy intake classified request … as non-deletion" | Exactly cases 533–542 → NOT_APPLICABLE |
| `event_type` of the worker row | The required treatment: DELETE_RECORD / REDACT_RECORD / ANONYMIZE_RECORD / CHECK_DATA_FLOW / CHECK_RESTORE_ACCESS / RETAIN_RECORD |

Cross-validation by the critic: activity truth vs SQL 274/274 agree; vs log + JSON observations 520/521 agree (the one "disagreement" is a legal hold where PRESENT is the compliant state). **Evidence is still required for the citation `evidence_id`.**

### 3.3 Linking identifier-free resources to cases (the hard part)

Compliant records often carry **no identifier at all**: 404 accounts, all-null analytics. Violating records carry the subject's email (current or historical). Redacted tickets, disabled flows, blocked backups and audit records carry `user_N`.

Linking strategy, from most to least defensible:

1. **Exact identifier match** in evidence: lowercase email (current + all historical), sha256 hash (current + old), phone (current + old), `user_id` / `customer_reference`.
2. **Timing window**: the account row sits in [reported_at − ~1.3 h, reported_at − ~0.7 h] and its result mirrors `reported_status`. Compliant "Policy action" rows come shortly after the account row; violation rows come about 1.5–3 h after it.
3. **Global elimination**: drop candidate rows whose evidence names another user, and propagate until stable.
4. **Ascending pairing tie-break** (account number order ↔ case number order) for leftover ties.
5. **Generator artifact (risky):** a seconds-mod-60 fingerprint relative to the account row. Compliant rows land on {9,10,39,40,41}, violation rows on {20,21,22,51,52}. It is 100% on the samples and resolves every sample tie, but it is a generator leak. See §9 for whether it is allowed.

With 1–3 (+fingerprint), the critic's prototype linked 470 eval accounts uniquely. 26 stay ambiguous (13 swap groups: 56/58, 59/60, 104/106, 203/205, 225/226, 243/244, 294/295, 345/346, 347/349, 404/406, 408/409, 410/411/412, 546), and 22 have no account row (10 NOT_APPLICABLE + 12 image family).

---

## 4. Time rules (critical)

- **Admissible for citation:** a file with `captured_at <= audit_at` (**inclusive**; many cohorts have `audit_at == captured_at`). In every sample the cited file also satisfies `captured_at >= reported_at`. In eval, each resource has **at most one** file in the [reported_at, audit_at] window (1009 exactly one, 0 with two or more). So the citation is effectively unique.
- **Use the manifest `captured_at`, not filename dates or document-internal dates.** Example: ev58 says "submitted 18 Jun" but its captured_at is 09-12.
- **Filter inside files by entry time too.** ev13, ev36, ev44/30/21/16/11/06 contain entries after `audit_at`, such as tail lines that flip an account back to present. Take the latest entry ≤ audit_at per resource.
- **Later files may supply ids, never state or citations.** Gold verifies audit records (case_09 audit_record_4902 from ev06; cases 23/24/29/30 from ev02) that appear only in post-audit files, with `evidence_id=""`.
- Activity after `audit_at` must be ignored (e.g. case_55's restore activity_3387 on 08-22; case_39's search_4801 repopulated 08-25).
- Same user, multiple cases with different audits: user_07 (case_07 / case_61), user_17 (case_17 / case_46), user_18 (case_33 / case_52). **Scope every case by its own time window.** Don't reuse the sample answers.

---

## 5. Policy mapping (`deletion_rules.csv` → steps)

| Rule / category | system_id / resource prefix | Violation → Finding | Remediation | Verification | Seen in eval? |
|---|---|---|---|---|---|
| 01 USER_PROFILE | account_service / account_N | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT | yes (always verified) |
| 02 SECONDARY_IDENTIFIER, 10 MARKETING_PROFILE | analytics (contact_lookup email_opt_in, case_12) / marketing_platform | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT | sample case_12; eval case_63 |
| 03 SEARCH_INDEX_ENTRY | search_service / search_N | REMAINING | DELETE | ABSENT | yes, many |
| 04 CACHE_ENTRY | — | — | — | — | **decoy rule** (noise only) |
| 05 SUPPORT_MESSAGE (shared context) | support_platform / support_N | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED | yes |
| 06 SUPPORT_ATTACHMENT (subject only) | support_platform / support_N, object_storage / object_N | REMAINING | DELETE | ABSENT | yes |
| 07 ANALYTICS_PROFILE | analytics_platform / analytics_N | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED | yes |
| 08 PRODUCT_TELEMETRY | — | — | — | — | **decoy rule** |
| 09 USER_EXPORT | export_service / export_N (activity says object_store; use export_service) | REMAINING | DELETE | ABSENT | yes |
| 11 EMAIL_DELIVERY_LOG | — | — | — | — | **decoy rule** (ev41 is a plain ledger) |
| 12 SECURITY_AUDIT_LOG | security_service / audit_record_N | (never a finding) | — | VERIFY_RECORD_PRESENT | yes, found by user_id |
| 13 LEGAL_HOLD_RECORD | legal_service / legal_hold_N | (never a finding) | — | VERIFY_RECORD_PRESENT (**untested by samples**) | 10 activity rows |
| 14 BACKUP_ARCHIVE | backup_service / backup_N | REPORT_RESTORE_RISK | BLOCK_RESTORE (never delete) | VERIFY_RESTORE_BLOCKED | yes |
| 15 ACCOUNT_TOMBSTONE | identity_service / tombstone_N | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED | case_543–550 (ev52), case_46 (ev42) |
| (connector, no rule) | integration_service / data_flow_N | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED | yes |

Discriminators:
- **Message vs attachment**: worker `event_type`: REDACT_RECORD means message, DELETE_RECORD means attachment. The evidence signals are `record_type`, `attachment_pii_scan file=*.pdf` vs `message_pii_scan`, and "[REDACTED]" text. Inventory SQL can't distinguish them.
- **Analytics profile vs marketing contact**: `contact_lookup … email_opt_in=true` is DELETE (case_12). Any direct identifier left on an analytics profile means ANONYMIZE.
- **Replica drift on the account** is reported as account REMAINING. The replication sync itself is **not** an active data flow (case_05).

---

## 6. Output construction rules (reproduce 32/32 samples — `proto/emit_check.py`)

1. Each violating resource gets FINDING (cites evidence), REMEDIATION (`""`) and VERIFICATION (`""`).
2. Each compliant resource gets VERIFICATION only.
3. **INCOMPLETE** (any finding exists):
   - Findings cite their proof file; all remediation and verification steps use `evidence_id=""`.
   - The verification list always includes `account_service/account_N VERIFY_RECORD_ABSENT`, even when the account was never a finding.
   - It also includes `security_service/audit_record_N VERIFY_RECORD_PRESENT` when an audit id exists in **any** file, even a post-audit one.
4. **COMPLETE**: verification steps only, each citing the in-window proof file. An account that is absent by omission (empty `customer_profiles`, 0 rows in an in-scope inventory, missing from all replica tables) cites that same file (case_01/02/04 → ev54, case_31 → ev51, case_22-style).
5. **NOT_APPLICABLE**: `[]`.
6. **Sort key** = (phase, operation's position in the §6.4 table, `system_id` ascending, `resource_id` ascending), then renumber from 1.
   - Finding order: REMAINING < EXPOSED_PII < ACTIVE_DATA_FLOW < RESTORE_RISK.
   - Remediation order: DISABLE < BLOCK < DELETE < REDACT < ANONYMIZE.
   - Verification order: ABSENT < PRESENT < REDACTED < ANONYMIZED < DISABLED < BLOCKED.
   - The apparent "analytics before support in findings, support before analytics in remediation" is just a side effect of the operation order.
   - ⚠ Gold **does not** apply the "downstream copies before source" instruction from AGENTS §6.5 beyond what the table order gives (case_16 deletes the account before the search entry). Follow the sort key, not that prose.
7. JSON: the sample uses compact separators with sorted keys. The grader ignores key order and whitespace.

---

## 7. Eval-set specifics already discovered

- **NOT_APPLICABLE = exactly case_533..case_542.** Corroborated by 10 CLASSIFY_REQUEST rows and by evidence_50, a decoy ledger whose accounts are all FOUND (correctly, since they weren't deleted). 6 of the 10 contain negated "delete/erase/remove/close", so a keyword classifier fails. Working guard regex: `not asking for deletion|do not close|don't delete|not a request to erase|marketing lists only|without removing|leave the account active|keep the account as it is|leave my profile|continue using`. "You can keep anonymous statistics / retain backups / security records can stay" are retention permissions, **not** negations.
- **The other 508 are deletion requests**, built from 3-slot templates (intent / scope / confirmation). The text carries no outcome signal.
- **Tombstone cohort** case_543–550 → evidence_52 (failover). Users 544, 546, 548 and 550 still expose PII; the other 4 are clean.
- **Replica drift** cases: 511, 453, 405, 355, 357, 307, 261, 259, 211, 153, 105 (+ samples 16, 05).
- **`.jr` decoy search docs** shadow cases 512, 456, 408, 304, 112, 35 and 28 (sample).
- **Projected distribution** (critic prototype): about 334 INCOMPLETE, 136 COMPLETE, 10 NOT_APPLICABLE and 38 needing extra handling (12 image family + 26 ambiguous account links).
- **Image-family predictions** (note 10 §2.4):

| Case | Status | Findings | Verify / notes |
|---|---|---|---|
| 33 | INCOMPLETE | export_1842 (ev18) | |
| 34 | INCOMPLETE | account_5762 PRESENT (ev04 overrides earlier ev01 404) | Open question: support_9538, linked by old phone |
| 35 | INCOMPLETE | search_428 (ev09) | Decoy: g.silva76.jr |
| 39 | INCOMPLETE | data_flow_1121 active (ev14) | Not search_4801, which comes after audit |
| 45 | COMPLETE | — | account_003 absent (ev90) and audit_record_003 present (ev37) |
| 46 | COMPLETE | — | account_6523 absent (ev67) and tombstone_17 redacted (ev42) |
| 50 | INCOMPLETE | analytics_7438 exposed (ev19) | |
| 52 | INCOMPLETE | export_1260 (ev23) | |
| 53 | INCOMPLETE | support_1034 exposed → redact (ev28) | |
| 55 | INCOMPLETE | backup_9287 restore risk (ev32) | |
| 61 | INCOMPLETE | object_storage/object_19 remaining (ev46) | |
| 63 | INCOMPLETE | marketing_platform/marketing_001 remaining (ev60) | The screenshot shows a different person (Soo-jin Park); the catalog links it to user_09 |

- **Unreachable gold bits:**
  - Sample case_18 `audit_record_6645` and case_20 `audit_record_5569` appear in no participant file.
  - About 84 eval cases have no findable audit id. Accept the loss and **don't invent ids**.

---

## 8. Recommended architecture

A deterministic evidence engine does the decisions; an LLM is used only where it adds value and can be metered.

```
code/main.py
 ├─ load: requests, identities, audit_log, activity, rules, manifest
 ├─ identity resolver: email → user_id; all historical emails/phones/hashes (sha256 lower)
 ├─ evidence normalizer → observations(file_id, captured_at, entry_time, system_id, resource_id,
 │                                      subject_keys[], state, category)
 │    ├─ SQL (sqlite3: replica tables, inventory + snapshot_scope)
 │    ├─ JSON (service exports, bundles, ledgers), TXT handover
 │    ├─ logs (7 parsers, trace_id join)
 │    └─ images/PDFs: LLM vision extraction, cached to a JSON sidecar (12+4 files, run once)
 ├─ activity interpreter: template classifier for details → (resource, violation|compliant, treatment)
 ├─ case linker: identifier match → timing window + status mirror → global elimination → tie-break
 ├─ intent classifier: rules/regex first, LLM fallback for multilingual or ambiguous text (cached)
 ├─ state resolver: latest observation with entry_time ≤ audit_at; cite file in [reported_at, audit_at]
 ├─ policy engine: category → rule → (finding, remediation, verification)
 └─ emitter: sort key, renumber, json.dumps(sort_keys=True, separators=(',',':')), sorted by case_id
code/evaluation/main.py  → score vs sample_output.csv (status, step, field, sequence accuracy) + custom cases
```

Why an LLM at all: the challenge is "AI-powered", and `usage_report.md` (tokens and cost) is mandatory. Natural places for it:
- Request-intent classification (multilingual)
- Image/PDF fact extraction (no OCR installed locally)
- An optional "explain this case" narrative

Cache every call so the deterministic core is reproducible. Read the key from env (`ANTHROPIC_API_KEY`), never commit it.

---

## 9. Risks, rule-compliance concerns and open questions

1. **Generator-artifact shortcuts.** Avoid these, or document them as tie-breakers only. AGENTS §6.7 forbids "case-family shortcuts", and the AI interview will probe the approach.
   - case_N → user_(N−2) (498/518): **do not use.**
   - The seconds-mod-60 fingerprint: a leak. Prefer the timing window, status mirror and elimination; use the fingerprint at most as a documented tie-breaker.
   - The `account_00N` naming convention for hand-crafted cases (needed for case_45/61/63, as gold did for sample case_04): a weak inference; flag it in the report.
2. **Q1:** should case_34 include support_9538, which links through an old phone in a file captured before the request? It fits the case_12 old-identifier trap, but it breaks the [reported_at, audit_at] window.
3. **Q2:** should legal holds get `VERIFY_RECORD_PRESENT legal_service/legal_hold_N`? This is recommended but untested. They sort before security_service.
4. **Q3:** should compliant non-account resources inside an INCOMPLETE case get VERIFICATION with `""`? Recommended yes; no sample covers it except account and audit.
5. **Q4:** 13 ambiguous account swap groups. Use ascending pairing; at worst one step is lost per case.
6. **Doc inconsistencies spotted:**
   - AGENTS.md says the reports go in `evaluation/…`; README says `code/evaluation/…`. Put them in `code/evaluation/` (zipped with `code`).
   - `code/main.py` and `code/evaluation/main.py` are empty stubs.
   - The official submission URL in AGENTS §4.1 is literally `https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists` (four w's). The rules say to reproduce it exactly.
   - The challenge end time is not configured.
7. **Deliverables checklist:**
   - `output.csv` at the repo root (518 rows, sorted)
   - `code.zip` (README + code + `code/evaluation/{evaluation_report,usage_report}.md`, no dataset, no nested archives)
   - `log.txt` as the chat transcript
   - the agent-trace zip (see `agent_trace_instructions.md`)
   - the AI interview

---

## 10. Notes index (`solution/notes/`)

| File | Content |
|---|---|
| 00_sample_dump.txt | All 32 sample requests with gold steps |
| 01_sql_databases.md (+ rows_annotated, case_derivations) | SQL schemas, drift, decoys, per-case SQL derivations |
| 02_json_records.md (+ records_*.py/.tsv/.txt) | JSON/TXT schemas, state decoding, cohort → proof-file map |
| 03_logs.md (+ percase files, scripts/logparse.py) | 7 log formats, trace joins, per-case log evidence |
| 04_images_pdfs.md | Full transcription of all PNG/PDF evidence + LINK mapping |
| 05_activity_identity.md | Activity templates, identity/hash/audit-log analysis, rule→system map |
| 06_requests_text.md | 518-row intent table with translations, template structure, timestamp checks |
| 07/08/09_trace_cases_*.md | Step-by-step justification of every sample gold step |
| 10_critic.md | Reconciliation of contradictions, gaps, verified algorithm, open questions |
| proto/*.py | Stdlib prototypes: emitter (32/32), linker, oracle cross-checks, coverage, e2e (22/24 generated samples exact; 2 misses unreachable) |
