# 06 — Request text, intent classification, timestamps, identity linkage

Scope: `dataset/deletion_requests.csv` (518 eval rows, case_33..case_550) and `dataset/sample_deletion_requests.csv` (32 rows, case_01..case_32).
Scripts used (stdlib Python, not part of the repo): built in the scratchpad; all numbers below were recomputed from the CSVs.

## 1. Headline results

* **Exactly 10 eval cases do NOT authorize deletion -> `NOT_APPLICABLE`, `steps_json=[]`: case_533 .. case_542** (a contiguous block).
* The other **508 eval cases are unambiguous deletion requests**. None contains a negation, condition, third-party request, or cancellation.
* Sample set: all 32 are deletion requests (gold = 22 INCOMPLETE, 10 COMPLETE, **0 NOT_APPLICABLE**). NOT_APPLICABLE behaviour can only be learned from the text itself.
* Eval request text is **pure templating with zero scenario signal**: the sentence choices are uniformly distributed against reported_status and against current/historical email. Everything about COMPLETE vs INCOMPLETE must come from evidence/activity, never from text.
* The 10 NON_DELETION cases are all `reported_status=NOT_STARTED`, but status is not proof (112 eval cases are NOT_STARTED; sample case_25/26/28 are NOT_STARTED and gold COMPLETE).

## 2. Templated sentence structure (eval)

Eval texts: 518 rows, 375 distinct texts, 67 distinct sentences in total:
* 32 English template sentences (in 3 slot pools; no sentence ever appears in more than one slot position).
* 15 multilingual sentences = 5 fixed 3-sentence triples (pt x14, es x12, fr x12, ja x12, ko x12). They are always the full triple in one language, never mixed.
* 20 non-deletion sentences (2 per NON_DELETION case, each used exactly once).

Language distribution (eval): en 456, pt 14, es 12, fr 12, ja 12, ko 12.

### Slot 1 — intent (all mean "delete my account / personal data")
| count | sentence |
|---|---|
| 52 | Please treat this message as a request for permanent account deletion. |
| 49 | I would like to submit a request to delete this account and its personal data. |
| 46 | I am requesting deletion of the account registered to this email address. |
| 45 | Please erase the account linked to this email address. |
| 39 | I am asking you to remove my account and the personal information linked to it. |
| 37 | I no longer use this account and would like it permanently deleted. |
| 37 | Please permanently delete the account associated with this email address. |
| 31 | Please process a permanent account-deletion request for this email address. |
| 29 | Please close my account and process the associated personal-data deletion. |
| 29 | I would like the account associated with this address to be erased. |
| 29 | Please begin the deletion process for the account using this email address. |
| 23 | I want to close this account and have its associated personal data deleted. |

### Slot 2 — scope (boilerplate; does NOT indicate case family)
Please review any identifiers connected to this account as part of the request. / Please review the account data that is eligible for deletion or de-identification. / Please check the records connected to the account before confirming completion. / Please follow the applicable retention and deletion requirements for the account. / Please apply the request across the systems covered by your deletion policy. / Please ensure the request is applied to the relevant account records. / Please apply the correct treatment to records covered by the request. / Please include information linked through current or earlier account identifiers. / Please process this under the standard personal-data deletion procedure. / Please complete the normal identity and data review for this request. / Please handle any copies that fall within the scope of the deletion request. / Please include records associated with the account under your privacy process.

Checked: "Please include information linked through current or earlier account identifiers." is used by 34 cases of which only 10 have a historical request email — same ratio as every other slot-2 sentence. No correlation with reported_status either.

### Slot 3 — confirmation (boilerplate)
Please contact me if you need information to verify the request. / Please send a confirmation after the process finishes. / Let me know when the request has been completed. / A short confirmation when the process is complete is sufficient. / Please let me know once the request has been reviewed. / I would appreciate confirmation of the final outcome. / Please confirm when the review is complete. / Please confirm the result after completing the required checks.

### Multilingual triples (translations)
| lang | n | S1 (intent) | S2 (scope) | S3 (confirm) |
|---|---|---|---|---|
| pt | 14 | "Solicito a exclusão permanente da conta associada a este e-mail." = I request permanent deletion of the account associated with this e-mail. | "Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade." = Check current and previous identifiers per the privacy process. | "Por favor, confirmem o resultado quando a análise terminar." = Please confirm the result when the review ends. |
| es | 12 | "Solicito la eliminación permanente de la cuenta asociada a este correo." = I request permanent deletion of the account associated with this email. | "Revisen los identificadores actuales y anteriores según su política de privacidad." = Review current and previous identifiers per your privacy policy. | "Por favor, confirmen el resultado cuando termine la revisión." = Please confirm the result when the review finishes. |
| fr | 12 | "Je demande la suppression définitive du compte associé à cette adresse e-mail." = I request permanent deletion of the account associated with this e-mail address. | "Veuillez examiner les identifiants actuels et antérieurs conformément à votre procédure de confidentialité." = Please examine current and previous identifiers per your privacy procedure. | "Merci de confirmer le résultat une fois la vérification terminée." = Please confirm the result once verification is done. |
| ja | 12 | "このメールアドレスに関連するアカウントの完全な削除を依頼します。" = I request complete deletion of the account related to this email address. | "プライバシー手続きに従い、現在および過去の識別情報を確認してください。" = Per the privacy procedure, check current and past identifying information. | "確認が完了したら結果をお知らせください。" = Tell me the result when the check is complete. |
| ko | 12 | "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다." = I request permanent deletion of the account linked to this email address. | "개인정보 처리 절차에 따라 현재 및 이전 식별자를 검토해 주세요." = Per the personal-data procedure, please review current and previous identifiers. | "검토가 완료되면 결과를 확인해 주세요." = Please confirm the result when the review is complete. |

All 62 multilingual eval cases = DELETION. Split sentences on `[.!?。]` followed by optional whitespace (JA uses 。).

## 3. The 10 NON_DELETION eval cases (-> NOT_APPLICABLE, steps_json=[])

| case_id | email | text | intent | trap |
|---|---|---|---|---|
| case_533 | haruka-kato@gmail.com | The mobile number on my profile is out of date. Please replace it with the new one and leave the account active. | correction (phone) | "replace" |
| case_534 | mlim7637@gmail.com | Please stop the promotional emails. I still need the account and my order history, so I am not asking for deletion. | marketing opt-out | contains the word "deletion" (negated) |
| case_535 | gabriel.l5556@outlook.com | I'd like to download my account information in a portable format. Please keep the account as it is. | access / portability | "download" (sample case_08 mentions a "download your data" export but IS a deletion) |
| case_536 | aditi.mehta@outlook.com | I can't access my profile and need help resetting the login. Do not close the account. | login support | contains "close the account" (negated) |
| case_537 | l.alvarez94@yahoo.com | My surname is misspelled on the account. Can you correct it without removing any of my records? | correction (name) | contains "removing" (negated) |
| case_538 | morgan.amelia@icloud.com | Please remove me from marketing lists only. I still want receipts and service messages for this account. | marketing opt-out | starts "Please remove me" — keyword classifiers will say DELETE |
| case_539 | leonie-rousseau@proton.me | Can you tell me what personal information you hold about me? This is an information request, not a request to erase it. | access (DSAR) | contains "erase" (negated) |
| case_540 | ieriksen5151@fastmail.com | I need a copy of last year's invoices for my records. Please leave my profile and purchase history in place. | document copy | — |
| case_541 | elena.h3070@zoho.com | Please change the email address used for this account. I want to continue using the service. | correction (email) | — |
| case_542 | omar.nasser@gmail.com | Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything. | access | contains "delete" (negated, apostrophe "don't") |

Structural tells (useful as a sanity cross-check, never as the classifier): the NON_DELETION texts are the only 2-sentence eval texts, all NOT_STARTED, requested_at at 12:00Z, case ids contiguous 533..542, user ids user_531..user_540 (all current-email, none historical). A keyword classifier ("delete|erase|remove|close") would misfire on 6 of the 10 (534, 536, 537, 538, 539, 542). Use an LLM or negation-aware rules: intent = deletion only if a deletion verb is not negated and no "only"/"not asking"/"keep the account"/"continue using" constraint appears.

Recommended deterministic rule (validated on all 550 rows): **DELETION unless the text matches a non-deletion guard**: `not asking for deletion|do not close|don't delete|not a request to erase|marketing lists only|without removing|leave the account active|keep the account as it is|leave my profile|continue using` -> eval 508 DELETION / 10 NON_DELETION (exactly case_533..542), sample 32/32 DELETION. A positive-keyword requirement (delet|eras|remov|close|exclus|eliminaci|suppression|削除|삭제) is NOT safe on its own: sample case_26 ("Please check the latest state and confirm that the profile is gone...") contains no deletion verb yet is a deletion case. For robustness on hidden variants, use an LLM classifier with these 10 + 32 as few-shot anchors and keep the guard as a deterministic override. (Sample free-form texts like "I'm deleting my account" (case_04) and "I want to close this account permanently" (case_17), "I no longer need this account. Please remove my name..." (case_31) must stay DELETION — "You can keep anonymous statistics", "You may retain backups", "Security records can stay", "keeping an internal deleted-account reference is fine" are retention allowances, NOT negations.)

## 4. Sample request texts (scenario hints the eval texts do not carry)

Sample texts are free-form for 23/32 cases and each describes the scenario family the gold answer tests; 9 use eval templates (case_03 FR -> COMPLETE; case_09, 11, 13, 14(JA), 16, 18, 20, 22 -> all INCOMPLETE). So templated text != COMPLETE.

| case | gold | reported | email | hint in text |
|---|---|---|---|---|
| 01 | COMPLETE | COMPLETE | CUR | plain closure |
| 02 | COMPLETE | PARTIALLY_COMPLETE | CUR | ES: "I tried to delete my account yesterday but the page showed an error. Can you check whether any data remains and complete the deletion if needed?" |
| 03 | COMPLETE | COMPLETE | CUR | FR template |
| 04 | COMPLETE | COMPLETE | CUR | analytics may stay anonymized |
| 05 | INCOMPLETE | COMPLETE | CUR | "same email still recognized" (ghost account) |
| 06 | INCOMPLETE | PARTIALLY_COMPLETE | CUR | search result remains |
| 07 | INCOMPLETE | COMPLETE | CUR | ID document in support attachment |
| 08 | INCOMPLETE | PARTIALLY_COMPLETE | CUR | export "download your data" link still works |
| 10 | INCOMPLETE | COMPLETE | HIST | old Yahoo address (user_10 has 2 email changes; request uses the OLDEST) |
| 12 | INCOMPLETE | COMPLETE | CUR (has history) | old address in systems that don't display email (hash) |
| 15 | INCOMPLETE | COMPLETE | CUR | integration/data flow still active |
| 17 | INCOMPLETE | NOT_STARTED | CUR | backups may stay but must not restore |
| 19 | INCOMPLETE | PARTIALLY_COMPLETE | CUR | support conversation shared with another customer -> redact, not delete |
| 21 | COMPLETE | COMPLETE | CUR | security retention limited to required |
| 23 | INCOMPLETE | NOT_STARTED | CUR | export + search, security records may stay |
| 24 | INCOMPLETE | COMPLETE | CUR | account and search still found |
| 25 | COMPLETE | NOT_STARTED | CUR | privacy page says failed, but actually done |
| 26 | COMPLETE | NOT_STARTED | CUR | old report says still exists -> check latest state |
| 27 | COMPLETE | COMPLETE | CUR | "audit the deletion as it stood when my request was reviewed" (audit_at cutoff) |
| 28 | COMPLETE | NOT_STARTED | CUR | similar-email search record belongs to someone else (decoy) |
| 29 | INCOMPLETE | NOT_STARTED | HIST | both addresses + switch off integration |
| 30 | INCOMPLETE | COMPLETE | HIST | search/support/analytics + sync recreation |
| 31 | COMPLETE | COMPLETE | CUR | tombstone keep internal reference |
| 32 | INCOMPLETE | PARTIALLY_COMPLETE | CUR | tombstone still shows PII |

reported_status vs gold (sample): COMPLETE->INCOMPLETE 11, COMPLETE->COMPLETE 6, NOT_STARTED->INCOMPLETE 7, NOT_STARTED->COMPLETE 3, PARTIALLY->INCOMPLETE 4, PARTIALLY->COMPLETE 1. reported_status is noise.

## 5. reported_status distribution
* Eval: COMPLETE 254, PARTIALLY_COMPLETE 152, NOT_STARTED 112.
* Sample: COMPLETE 17, NOT_STARTED 10, PARTIALLY_COMPLETE 5.
* Eval DELETION cases by request-email type: CUR+COMPLETE 206, CUR+PARTIAL 117, CUR+NOT_STARTED 84, HIST+COMPLETE 47, HIST+PARTIAL 35, HIST+NOT_STARTED 18, CUR(changed)+COMPLETE 1.

## 6. Timestamps
* No ordering anomalies: for all 550 rows requested_at <= reported_at <= audit_at. No audit_at before requested_at.
* No identity audit-log event (email/phone/hash change) occurs after its subject's requested_at (so the identity set at request time = current snapshot + all audit-log old values).
* Eval requested_at range 2026-01-05 .. 2026-09-24 (spread over Jan–Sep, ~60/month); audit_at range 2026-01-29 .. 2026-10-01. Sample range is only Aug–Sep 2026. evidence_files.csv captured_at is spread 2026-01..2026-10 (per month: 01:2, 02:7, 03:10, 04:8, 05:10, 06:9, 07:11, 08:9, 09:26, 10:2) => for early-2026 cases most evidence files are AFTER audit_at and must be ignored; per-case time filtering (captured_at <= audit_at, event_time <= audit_at) is critical.
* Times are on the hour (mostly 06:00–12:00Z); one exception: case_63 at :20 (04:20 / 22:20 / 09:20).
* reported_at - requested_at: 24h (170), 48h (169), 72h (167), 42h (12).
* audit_at - reported_at: 7–28 days in whole-day multiples, except the 12 short-window cases (35h).
* Many rows share audit_at (e.g. 2026-10-01T12:00Z, 2026-09-20T12:00Z for case_543..550, 2026-01-29T12:00Z for case_523..532), i.e. cases were generated in batches.

### 6.1 The 12 SHORT_WINDOW cases (reported +42h, audit +35h) — a special family
case_33, 34, 35, 39, 45, 46, 50, 52, 53, 55, 61, 63. They break the case_N -> user_(N-2) id pattern and map to low user ids (user_03..user_22), two of which are also sample subjects. Each one has a dedicated `LINK_RESOURCE_IDENTITY` row in system_activity.csv (activity_4000..activity_4011, source data_catalog, ~reported_at + 9h07m) that explicitly links one resource to the subject's email + user_id:

| case | user | linked resource (activity) | note |
|---|---|---|---|
| case_33 | user_18 | export_1260 (activity_4004, 2026-06-18, before this request) + export_1842 "NST-2026-0718-1842" (activity_4009, in window) | same user as case_52 |
| case_34 | user_11 | account_5762 (activity_4000) | request email is CURRENT; old email haruka.s183889@zoho.com exists |
| case_35 | user_13 | search_428 (activity_4001) | |
| case_39 | user_14 | data_flow_1121 (activity_4002) | |
| case_45 | user_03 | audit_record_003 (activity_4010) | security record -> likely RETAIN |
| case_46 | user_17 | tombstone_17 (activity_4011) | sample case_17 is same user (later, Aug 2026) |
| case_50 | user_20 | analytics_7438 (activity_4003) | |
| case_52 | user_18 | export_1260 (activity_4004, in window); export_1842 link is AFTER audit_at (2026-07-18 > 2026-06-19) -> ignore | |
| case_53 | user_22 | support_1034 (activity_4005) | |
| case_55 | user_16 | backup_9287 (activity_4006) | |
| case_61 | user_07 | object_19 "delivery_confirmation_19.pdf" (activity_4007: "belongs only to" the user) | sample case_07 is same user (Aug 2026, ID document in support) |
| case_63 | user_09 | marketing_001 (activity_4008) | |

These look like "one-resource probe" cases. Since their audit windows are early and short, nearly all evidence files will be after audit_at; the in-window activity rows are likely the decisive evidence.

## 7. Identity linkage traps (request email -> user_id)
* Every request email resolves to exactly one user: 418 eval emails are a current snapshot email, 100 are historical (old_value of an `email` row in user_audit_log.csv). 0 unresolved. Sample: 29 CUR, 3 HIST.
* **20 eval emails are UPPERCASE** (e.g. case_38 SIPHO.MOKOENA@GMAIL.COM, case_40 CHOI.JIHOON94@GMAIL.COM (historical), case_85, 148, 326, 427 also historical). Lowercase before matching; evidence uses lowercase.
* **Duplicate request email**: ingrid.dahl@outlook.com in case_52 (2026-06-16) and case_33 (2026-07-16), both user_18. Same subject, two audits at different times -> different correct answers possible.
* Same user across eval and sample: user_07 (sample case_07 Aug-2026, eval case_61 Feb-2026), user_17 (sample case_17 Aug-2026, eval case_46 Mar-2026). Sample gold for these users is for a LATER audit_at; do not copy it.
* Users with 2 email changes (3 emails): user_10 (sample case_10, uses oldest nadia.ionescu@yahoo.com -> nadia.petrescu -> n.petrescu) and user_35 (eval case_37, request uses oldest abena.o189491@zoho.com -> abena.o189466 -> current abena.o1894@zoho.com). Must chain all hops, also chain email_hash changes (audit_log has 107 email_hash rows paired with 107 email rows; 92 phone changes).
* Historical-email pattern: the old address is almost always current address + extra digits (e.g. case_43 javier.r940897@outlook.com -> current javier.r9408@outlook.com; case_56 elena.romero88 -> elena.romero). So substring/prefix matching of emails is dangerous; use exact match over the full identifier set.
* Cross-user near-duplicate emails (decoys, edit distance <=2, different user): case_183 s.jung68@gmail.com (user_181) vs s.jung24@gmail.com (user_805); case_221 mei-tanaka@gmail.com (user_219) vs aoi-tanaka@gmail.com (user_843).
* Duplicate names in identities (different people): Mateo Ríos (user_02, user_262), Thandiwe Ndlovu (user_04, user_413), Gabriel Costa (user_08, user_143). Never link by name alone.
* user_identities has 850 users; only 547 are subjects of any case (sample+eval). ~303 users (mostly user_551..user_850) are pure decoys.
* Case/user id pattern: eval case_N -> user_(N-2) for 498 cases; case_543..550 -> user_543..550; the 12 short-window cases map elsewhere. (Generator artifact, not something to rely on for predictions.)

## 8. Full eval classification table (518 rows)
Columns: lang; class; reason; reported_status; resolved user_id; email_match (CUR = current snapshot, HIST = historical email from audit log, CUR(changed) = current email that replaced an older one); rep_gap_h = reported-requested hours; audit_gap_h = audit-reported hours; flags.

| case_id | lang | class | reason | reported_status | user_id | email_match | rep_gap_h | audit_gap_h | flags |
|---|---|---|---|---|---|---|---|---|---|
| case_33 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_18 | CUR | 42 | 35 | SHORT_WINDOW,DUP_EMAIL |
| case_34 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_11 | CUR(changed) | 42 | 35 | SHORT_WINDOW |
| case_35 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_13 | CUR | 42 | 35 | SHORT_WINDOW |
| case_36 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_34 | CUR | 48 | 528 |  |
| case_37 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_35 | HIST | 72 | 528 |  |
| case_38 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_36 | CUR | 24 | 600 | UPPERCASE |
| case_39 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_14 | CUR | 42 | 35 | SHORT_WINDOW |
| case_40 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_38 | HIST | 72 | 600 | UPPERCASE |
| case_41 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_39 | HIST | 24 | 672 |  |
| case_42 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_40 | CUR | 48 | 192 |  |
| case_43 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_41 | HIST | 72 | 192 |  |
| case_44 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_42 | CUR | 24 | 264 |  |
| case_45 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_03 | CUR | 42 | 35 | SHORT_WINDOW |
| case_46 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_17 | CUR | 42 | 35 | SHORT_WINDOW |
| case_47 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_45 | HIST | 24 | 336 |  |
| case_48 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_46 | HIST | 48 | 336 |  |
| case_49 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_47 | HIST | 72 | 336 |  |
| case_50 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_20 | CUR | 42 | 35 | SHORT_WINDOW |
| case_51 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_49 | CUR | 48 | 408 |  |
| case_52 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_18 | CUR | 42 | 35 | SHORT_WINDOW,DUP_EMAIL |
| case_53 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_22 | CUR | 42 | 35 | SHORT_WINDOW |
| case_54 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_52 | CUR | 48 | 480 | UPPERCASE |
| case_55 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_16 | CUR | 42 | 35 | SHORT_WINDOW |
| case_56 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_54 | HIST | 24 | 552 |  |
| case_57 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_55 | CUR | 48 | 552 |  |
| case_58 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_56 | CUR | 72 | 552 |  |
| case_59 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_57 | CUR | 24 | 624 |  |
| case_60 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_58 | CUR | 48 | 624 |  |
| case_61 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_07 | CUR | 42 | 35 | SHORT_WINDOW |
| case_62 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_60 | HIST | 24 | 216 |  |
| case_63 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_09 | CUR | 42 | 35 | SHORT_WINDOW |
| case_64 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_62 | CUR | 72 | 216 |  |
| case_65 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_63 | CUR | 24 | 288 |  |
| case_66 | ko | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_64 | HIST | 48 | 288 |  |
| case_67 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_65 | CUR | 72 | 288 |  |
| case_68 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_66 | CUR | 24 | 360 |  |
| case_69 | es | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_67 | CUR | 48 | 360 |  |
| case_70 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_68 | CUR | 72 | 360 |  |
| case_71 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_69 | CUR | 24 | 432 | UPPERCASE |
| case_72 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_70 | CUR | 48 | 432 |  |
| case_73 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_71 | CUR | 72 | 432 |  |
| case_74 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_72 | CUR | 24 | 504 |  |
| case_75 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_73 | CUR | 48 | 504 |  |
| case_76 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_74 | CUR | 72 | 504 |  |
| case_77 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_75 | CUR | 24 | 576 |  |
| case_78 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_76 | CUR | 48 | 576 |  |
| case_79 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_77 | HIST | 72 | 576 |  |
| case_80 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_78 | HIST | 24 | 648 |  |
| case_81 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_79 | CUR | 48 | 648 |  |
| case_82 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_80 | CUR | 72 | 168 |  |
| case_83 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_81 | CUR | 24 | 240 |  |
| case_84 | fr | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_82 | HIST | 48 | 240 |  |
| case_85 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_83 | HIST | 72 | 240 | UPPERCASE |
| case_86 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_84 | CUR | 24 | 312 |  |
| case_87 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_85 | CUR | 48 | 312 |  |
| case_88 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_86 | HIST | 72 | 312 |  |
| case_89 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_87 | CUR | 24 | 384 |  |
| case_90 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_88 | HIST | 48 | 384 |  |
| case_91 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_89 | HIST | 72 | 384 |  |
| case_92 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_90 | CUR | 24 | 456 |  |
| case_93 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_91 | HIST | 48 | 456 |  |
| case_94 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_92 | HIST | 72 | 456 |  |
| case_95 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_93 | CUR | 24 | 528 |  |
| case_96 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_94 | CUR | 48 | 528 |  |
| case_97 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_95 | HIST | 72 | 528 |  |
| case_98 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_96 | HIST | 24 | 600 |  |
| case_99 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_97 | CUR | 48 | 600 |  |
| case_100 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_98 | HIST | 72 | 600 |  |
| case_101 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_99 | CUR | 24 | 672 |  |
| case_102 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_100 | CUR | 48 | 192 |  |
| case_103 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_101 | CUR | 72 | 192 |  |
| case_104 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_102 | CUR | 24 | 264 |  |
| case_105 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_103 | CUR | 48 | 264 |  |
| case_106 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_104 | CUR | 72 | 264 |  |
| case_107 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_105 | CUR | 24 | 336 |  |
| case_108 | es | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_106 | CUR | 48 | 336 |  |
| case_109 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_107 | CUR | 72 | 336 |  |
| case_110 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_108 | HIST | 24 | 408 |  |
| case_111 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_109 | CUR | 48 | 408 | UPPERCASE |
| case_112 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_110 | CUR | 72 | 408 |  |
| case_113 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_111 | CUR | 24 | 480 |  |
| case_114 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_112 | CUR | 48 | 480 |  |
| case_115 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_113 | CUR | 72 | 480 |  |
| case_116 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_114 | CUR | 24 | 552 |  |
| case_117 | ja | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_115 | CUR | 48 | 552 |  |
| case_118 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_116 | HIST | 72 | 552 |  |
| case_119 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_117 | CUR | 24 | 624 |  |
| case_120 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_118 | CUR | 48 | 624 |  |
| case_121 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_119 | CUR | 72 | 624 |  |
| case_122 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_120 | CUR | 24 | 216 |  |
| case_123 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_121 | CUR | 48 | 216 |  |
| case_124 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_122 | CUR | 72 | 216 |  |
| case_125 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_123 | HIST | 24 | 288 |  |
| case_126 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_124 | CUR | 48 | 288 |  |
| case_127 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_125 | CUR | 72 | 288 |  |
| case_128 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_126 | CUR | 24 | 360 |  |
| case_129 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_127 | CUR | 48 | 360 |  |
| case_130 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_128 | CUR | 72 | 360 |  |
| case_131 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_129 | CUR | 24 | 432 |  |
| case_132 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_130 | CUR | 48 | 432 |  |
| case_133 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_131 | CUR | 72 | 432 |  |
| case_134 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_132 | CUR | 24 | 504 |  |
| case_135 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_133 | CUR | 48 | 504 |  |
| case_136 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_134 | HIST | 72 | 504 |  |
| case_137 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_135 | CUR | 24 | 576 |  |
| case_138 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_136 | CUR | 48 | 576 |  |
| case_139 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_137 | HIST | 72 | 576 |  |
| case_140 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_138 | CUR | 24 | 648 |  |
| case_141 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_139 | HIST | 48 | 648 |  |
| case_142 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_140 | CUR | 72 | 168 |  |
| case_143 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_141 | HIST | 24 | 240 |  |
| case_144 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_142 | CUR | 48 | 240 |  |
| case_145 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_143 | CUR | 72 | 240 |  |
| case_146 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_144 | CUR | 24 | 312 |  |
| case_147 | es | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_145 | CUR | 48 | 312 |  |
| case_148 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_146 | HIST | 72 | 312 | UPPERCASE |
| case_149 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_147 | CUR | 24 | 384 |  |
| case_150 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_148 | CUR | 48 | 384 |  |
| case_151 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_149 | CUR | 72 | 384 |  |
| case_152 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_150 | HIST | 24 | 456 |  |
| case_153 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_151 | HIST | 48 | 456 |  |
| case_154 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_152 | CUR | 72 | 456 |  |
| case_155 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_153 | HIST | 24 | 528 |  |
| case_156 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_154 | CUR | 48 | 528 |  |
| case_157 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_155 | CUR | 72 | 528 |  |
| case_158 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_156 | CUR | 24 | 600 |  |
| case_159 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_157 | HIST | 48 | 600 |  |
| case_160 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_158 | HIST | 72 | 600 |  |
| case_161 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_159 | HIST | 24 | 672 |  |
| case_162 | fr | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_160 | CUR | 48 | 192 |  |
| case_163 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_161 | CUR | 72 | 192 |  |
| case_164 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_162 | CUR | 24 | 264 |  |
| case_165 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_163 | CUR | 48 | 264 |  |
| case_166 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_164 | CUR | 72 | 264 | UPPERCASE |
| case_167 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_165 | CUR | 24 | 336 |  |
| case_168 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_166 | CUR | 48 | 336 |  |
| case_169 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_167 | CUR | 72 | 336 |  |
| case_170 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_168 | CUR | 24 | 408 |  |
| case_171 | pt | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_169 | CUR | 48 | 408 |  |
| case_172 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_170 | CUR | 72 | 408 |  |
| case_173 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_171 | CUR | 24 | 480 |  |
| case_174 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_172 | CUR | 48 | 480 |  |
| case_175 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_173 | HIST | 72 | 480 |  |
| case_176 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_174 | CUR | 24 | 552 |  |
| case_177 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_175 | CUR | 48 | 552 |  |
| case_178 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_176 | CUR | 72 | 552 |  |
| case_179 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_177 | CUR | 24 | 624 |  |
| case_180 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_178 | CUR | 48 | 624 |  |
| case_181 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_179 | CUR | 72 | 624 |  |
| case_182 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_180 | CUR | 24 | 216 |  |
| case_183 | ko | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_181 | CUR | 48 | 216 |  |
| case_184 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_182 | CUR | 72 | 216 |  |
| case_185 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_183 | HIST | 24 | 288 |  |
| case_186 | es | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_184 | CUR | 48 | 288 |  |
| case_187 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_185 | CUR | 72 | 288 |  |
| case_188 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_186 | HIST | 24 | 360 |  |
| case_189 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_187 | CUR | 48 | 360 |  |
| case_190 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_188 | CUR | 72 | 360 | UPPERCASE |
| case_191 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_189 | CUR | 24 | 432 | UPPERCASE |
| case_192 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_190 | CUR | 48 | 432 |  |
| case_193 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_191 | CUR | 72 | 432 |  |
| case_194 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_192 | HIST | 24 | 504 |  |
| case_195 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_193 | CUR | 48 | 504 |  |
| case_196 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_194 | CUR | 72 | 504 |  |
| case_197 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_195 | CUR | 24 | 576 |  |
| case_198 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_196 | CUR | 48 | 576 |  |
| case_199 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_197 | HIST | 72 | 576 |  |
| case_200 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_198 | CUR | 24 | 648 |  |
| case_201 | fr | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_199 | HIST | 48 | 648 |  |
| case_202 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_200 | CUR | 72 | 168 |  |
| case_203 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_201 | CUR | 24 | 240 |  |
| case_204 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_202 | CUR | 48 | 240 |  |
| case_205 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_203 | CUR | 72 | 240 |  |
| case_206 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_204 | HIST | 24 | 312 |  |
| case_207 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_205 | CUR | 48 | 312 |  |
| case_208 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_206 | CUR | 72 | 312 |  |
| case_209 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_207 | CUR | 24 | 384 |  |
| case_210 | pt | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_208 | CUR | 48 | 384 |  |
| case_211 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_209 | CUR | 72 | 384 |  |
| case_212 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_210 | CUR | 24 | 456 |  |
| case_213 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_211 | CUR | 48 | 456 |  |
| case_214 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_212 | CUR | 72 | 456 |  |
| case_215 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_213 | CUR | 24 | 528 |  |
| case_216 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_214 | HIST | 48 | 528 |  |
| case_217 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_215 | CUR | 72 | 528 |  |
| case_218 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_216 | CUR | 24 | 600 |  |
| case_219 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_217 | CUR | 48 | 600 |  |
| case_220 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_218 | HIST | 72 | 600 |  |
| case_221 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_219 | CUR | 24 | 672 |  |
| case_222 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_220 | CUR | 48 | 192 |  |
| case_223 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_221 | CUR | 72 | 192 |  |
| case_224 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_222 | CUR | 24 | 264 |  |
| case_225 | es | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_223 | CUR | 48 | 264 |  |
| case_226 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_224 | CUR | 72 | 264 |  |
| case_227 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_225 | HIST | 24 | 336 |  |
| case_228 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_226 | CUR | 48 | 336 |  |
| case_229 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_227 | CUR | 72 | 336 |  |
| case_230 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_228 | CUR | 24 | 408 |  |
| case_231 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_229 | CUR | 48 | 408 |  |
| case_232 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_230 | CUR | 72 | 408 |  |
| case_233 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_231 | CUR | 24 | 480 |  |
| case_234 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_232 | CUR | 48 | 480 |  |
| case_235 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_233 | CUR | 72 | 480 |  |
| case_236 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_234 | CUR | 24 | 552 |  |
| case_237 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_235 | CUR | 48 | 552 |  |
| case_238 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_236 | HIST | 72 | 552 |  |
| case_239 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_237 | CUR | 24 | 624 |  |
| case_240 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_238 | HIST | 48 | 624 |  |
| case_241 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_239 | HIST | 72 | 624 |  |
| case_242 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_240 | HIST | 24 | 216 |  |
| case_243 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_241 | CUR | 48 | 216 |  |
| case_244 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_242 | CUR | 72 | 216 |  |
| case_245 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_243 | CUR | 24 | 288 |  |
| case_246 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_244 | CUR | 48 | 288 |  |
| case_247 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_245 | HIST | 72 | 288 |  |
| case_248 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_246 | CUR | 24 | 360 |  |
| case_249 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_247 | CUR | 48 | 360 |  |
| case_250 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_248 | CUR | 72 | 360 |  |
| case_251 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_249 | CUR | 24 | 432 |  |
| case_252 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_250 | HIST | 48 | 432 |  |
| case_253 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_251 | CUR | 72 | 432 |  |
| case_254 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_252 | CUR | 24 | 504 |  |
| case_255 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_253 | CUR | 48 | 504 | UPPERCASE |
| case_256 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_254 | CUR | 72 | 504 |  |
| case_257 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_255 | CUR | 24 | 576 |  |
| case_258 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_256 | CUR | 48 | 576 |  |
| case_259 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_257 | CUR | 72 | 576 |  |
| case_260 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_258 | CUR | 24 | 648 |  |
| case_261 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_259 | CUR | 48 | 648 |  |
| case_262 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_260 | CUR | 72 | 168 |  |
| case_263 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_261 | CUR | 24 | 240 |  |
| case_264 | es | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_262 | HIST | 48 | 240 |  |
| case_265 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_263 | CUR | 72 | 240 |  |
| case_266 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_264 | CUR | 24 | 312 |  |
| case_267 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_265 | CUR | 48 | 312 |  |
| case_268 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_266 | CUR | 72 | 312 |  |
| case_269 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_267 | CUR | 24 | 384 |  |
| case_270 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_268 | CUR | 48 | 384 |  |
| case_271 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_269 | CUR | 72 | 384 |  |
| case_272 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_270 | CUR | 24 | 456 |  |
| case_273 | ja | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_271 | CUR | 48 | 456 |  |
| case_274 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_272 | HIST | 72 | 456 |  |
| case_275 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_273 | HIST | 24 | 528 |  |
| case_276 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_274 | CUR | 48 | 528 |  |
| case_277 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_275 | CUR | 72 | 528 |  |
| case_278 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_276 | CUR | 24 | 600 |  |
| case_279 | fr | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_277 | CUR | 48 | 600 |  |
| case_280 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_278 | CUR | 72 | 600 |  |
| case_281 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_279 | CUR | 24 | 672 |  |
| case_282 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_280 | CUR | 48 | 192 |  |
| case_283 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_281 | CUR | 72 | 192 |  |
| case_284 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_282 | HIST | 24 | 264 |  |
| case_285 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_283 | HIST | 48 | 264 |  |
| case_286 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_284 | CUR | 72 | 264 |  |
| case_287 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_285 | CUR | 24 | 336 |  |
| case_288 | pt | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_286 | HIST | 48 | 336 |  |
| case_289 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_287 | CUR | 72 | 336 |  |
| case_290 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_288 | CUR | 24 | 408 |  |
| case_291 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_289 | CUR | 48 | 408 |  |
| case_292 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_290 | CUR | 72 | 408 |  |
| case_293 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_291 | CUR | 24 | 480 |  |
| case_294 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_292 | CUR | 48 | 480 |  |
| case_295 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_293 | CUR | 72 | 480 |  |
| case_296 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_294 | CUR | 24 | 552 |  |
| case_297 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_295 | CUR | 48 | 552 |  |
| case_298 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_296 | HIST | 72 | 552 |  |
| case_299 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_297 | CUR | 24 | 624 |  |
| case_300 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_298 | CUR | 48 | 624 |  |
| case_301 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_299 | CUR | 72 | 624 |  |
| case_302 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_300 | CUR | 24 | 216 |  |
| case_303 | es | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_301 | HIST | 48 | 216 |  |
| case_304 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_302 | CUR | 72 | 216 |  |
| case_305 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_303 | CUR | 24 | 288 |  |
| case_306 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_304 | CUR | 48 | 288 |  |
| case_307 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_305 | CUR | 72 | 288 |  |
| case_308 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_306 | CUR | 24 | 360 |  |
| case_309 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_307 | CUR | 48 | 360 |  |
| case_310 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_308 | CUR | 72 | 360 |  |
| case_311 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_309 | HIST | 24 | 432 |  |
| case_312 | ja | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_310 | CUR | 48 | 432 |  |
| case_313 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_311 | CUR | 72 | 432 |  |
| case_314 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_312 | CUR | 24 | 504 |  |
| case_315 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_313 | CUR | 48 | 504 |  |
| case_316 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_314 | CUR | 72 | 504 |  |
| case_317 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_315 | CUR | 24 | 576 |  |
| case_318 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_316 | CUR | 48 | 576 |  |
| case_319 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_317 | CUR | 72 | 576 |  |
| case_320 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_318 | CUR | 24 | 648 |  |
| case_321 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_319 | HIST | 48 | 648 |  |
| case_322 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_320 | CUR | 72 | 168 |  |
| case_323 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_321 | CUR | 24 | 240 |  |
| case_324 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_322 | CUR | 48 | 240 |  |
| case_325 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_323 | HIST | 72 | 240 |  |
| case_326 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_324 | HIST | 24 | 312 | UPPERCASE |
| case_327 | pt | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_325 | CUR | 48 | 312 | UPPERCASE |
| case_328 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_326 | CUR | 72 | 312 |  |
| case_329 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_327 | CUR | 24 | 384 |  |
| case_330 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_328 | HIST | 48 | 384 |  |
| case_331 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_329 | CUR | 72 | 384 |  |
| case_332 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_330 | CUR | 24 | 456 |  |
| case_333 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_331 | HIST | 48 | 456 |  |
| case_334 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_332 | CUR | 72 | 456 |  |
| case_335 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_333 | HIST | 24 | 528 |  |
| case_336 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_334 | CUR | 48 | 528 |  |
| case_337 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_335 | HIST | 72 | 528 |  |
| case_338 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_336 | CUR | 24 | 600 |  |
| case_339 | ko | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_337 | CUR | 48 | 600 |  |
| case_340 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_338 | CUR | 72 | 600 |  |
| case_341 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_339 | CUR | 24 | 672 |  |
| case_342 | es | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_340 | CUR | 48 | 192 |  |
| case_343 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_341 | CUR | 72 | 192 |  |
| case_344 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_342 | HIST | 24 | 264 |  |
| case_345 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_343 | CUR | 48 | 264 |  |
| case_346 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_344 | CUR | 72 | 264 |  |
| case_347 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_345 | CUR | 24 | 336 |  |
| case_348 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_346 | CUR | 48 | 336 |  |
| case_349 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_347 | CUR | 72 | 336 |  |
| case_350 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_348 | CUR | 24 | 408 |  |
| case_351 | ja | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_349 | CUR | 48 | 408 |  |
| case_352 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_350 | CUR | 72 | 408 |  |
| case_353 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_351 | CUR | 24 | 480 |  |
| case_354 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_352 | CUR | 48 | 480 |  |
| case_355 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_353 | CUR | 72 | 480 |  |
| case_356 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_354 | CUR | 24 | 552 |  |
| case_357 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_355 | CUR | 48 | 552 |  |
| case_358 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_356 | CUR | 72 | 552 |  |
| case_359 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_357 | CUR | 24 | 624 |  |
| case_360 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_358 | HIST | 48 | 624 |  |
| case_361 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_359 | CUR | 72 | 624 |  |
| case_362 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_360 | CUR | 24 | 216 |  |
| case_363 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_361 | CUR | 48 | 216 |  |
| case_364 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_362 | CUR | 72 | 216 |  |
| case_365 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_363 | CUR | 24 | 288 |  |
| case_366 | pt | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_364 | CUR | 48 | 288 |  |
| case_367 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_365 | CUR | 72 | 288 |  |
| case_368 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_366 | HIST | 24 | 360 |  |
| case_369 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_367 | CUR | 48 | 360 |  |
| case_370 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_368 | HIST | 72 | 360 |  |
| case_371 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_369 | CUR | 24 | 432 |  |
| case_372 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_370 | CUR | 48 | 432 |  |
| case_373 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_371 | HIST | 72 | 432 |  |
| case_374 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_372 | CUR | 24 | 504 |  |
| case_375 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_373 | CUR | 48 | 504 |  |
| case_376 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_374 | HIST | 72 | 504 |  |
| case_377 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_375 | CUR | 24 | 576 |  |
| case_378 | ko | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_376 | HIST | 48 | 576 |  |
| case_379 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_377 | CUR | 72 | 576 |  |
| case_380 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_378 | CUR | 24 | 648 |  |
| case_381 | es | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_379 | CUR | 48 | 648 |  |
| case_382 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_380 | CUR | 72 | 168 |  |
| case_383 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_381 | CUR | 24 | 240 |  |
| case_384 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_382 | CUR | 48 | 240 | UPPERCASE |
| case_385 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_383 | CUR | 72 | 240 |  |
| case_386 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_384 | CUR | 24 | 312 |  |
| case_387 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_385 | HIST | 48 | 312 |  |
| case_388 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_386 | CUR | 72 | 312 |  |
| case_389 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_387 | CUR | 24 | 384 |  |
| case_390 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_388 | CUR | 48 | 384 |  |
| case_391 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_389 | CUR | 72 | 384 |  |
| case_392 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_390 | CUR | 24 | 456 |  |
| case_393 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_391 | CUR | 48 | 456 |  |
| case_394 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_392 | CUR | 72 | 456 |  |
| case_395 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_393 | CUR | 24 | 528 |  |
| case_396 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_394 | CUR | 48 | 528 | UPPERCASE |
| case_397 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_395 | CUR | 72 | 528 |  |
| case_398 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_396 | CUR | 24 | 600 |  |
| case_399 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_397 | CUR | 48 | 600 |  |
| case_400 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_398 | CUR | 72 | 600 |  |
| case_401 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_399 | CUR | 24 | 672 |  |
| case_402 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_400 | CUR | 48 | 192 |  |
| case_403 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_401 | CUR | 72 | 192 |  |
| case_404 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_402 | CUR | 24 | 264 |  |
| case_405 | pt | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_403 | CUR | 48 | 264 |  |
| case_406 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_404 | HIST | 72 | 264 |  |
| case_407 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_405 | CUR | 24 | 336 |  |
| case_408 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_406 | CUR | 48 | 336 |  |
| case_409 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_407 | CUR | 72 | 336 |  |
| case_410 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_408 | CUR | 24 | 408 |  |
| case_411 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_409 | CUR | 48 | 408 |  |
| case_412 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_410 | CUR | 72 | 408 |  |
| case_413 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_411 | CUR | 24 | 480 |  |
| case_414 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_412 | HIST | 48 | 480 |  |
| case_415 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_413 | CUR | 72 | 480 |  |
| case_416 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_414 | CUR | 24 | 552 | UPPERCASE |
| case_417 | ko | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_415 | CUR | 48 | 552 |  |
| case_418 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_416 | CUR | 72 | 552 |  |
| case_419 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_417 | CUR | 24 | 624 |  |
| case_420 | es | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_418 | HIST | 48 | 624 |  |
| case_421 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_419 | CUR | 72 | 624 |  |
| case_422 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_420 | HIST | 24 | 216 |  |
| case_423 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_421 | CUR | 48 | 216 |  |
| case_424 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_422 | CUR | 72 | 216 |  |
| case_425 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_423 | HIST | 24 | 288 |  |
| case_426 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_424 | HIST | 48 | 288 |  |
| case_427 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_425 | HIST | 72 | 288 | UPPERCASE |
| case_428 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_426 | CUR | 24 | 360 |  |
| case_429 | ja | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_427 | CUR | 48 | 360 |  |
| case_430 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_428 | CUR | 72 | 360 |  |
| case_431 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_429 | CUR | 24 | 432 |  |
| case_432 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_430 | CUR | 48 | 432 |  |
| case_433 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_431 | CUR | 72 | 432 |  |
| case_434 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_432 | CUR | 24 | 504 |  |
| case_435 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_433 | CUR | 48 | 504 |  |
| case_436 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_434 | CUR | 72 | 504 |  |
| case_437 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_435 | CUR | 24 | 576 |  |
| case_438 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_436 | CUR | 48 | 576 |  |
| case_439 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_437 | HIST | 72 | 576 |  |
| case_440 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_438 | CUR | 24 | 648 |  |
| case_441 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_439 | CUR | 48 | 648 |  |
| case_442 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_440 | CUR | 72 | 168 |  |
| case_443 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_441 | CUR | 24 | 240 |  |
| case_444 | pt | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_442 | CUR | 48 | 240 |  |
| case_445 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_443 | HIST | 72 | 240 |  |
| case_446 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_444 | CUR | 24 | 312 |  |
| case_447 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_445 | HIST | 48 | 312 |  |
| case_448 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_446 | CUR | 72 | 312 |  |
| case_449 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_447 | CUR | 24 | 384 |  |
| case_450 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_448 | CUR | 48 | 384 |  |
| case_451 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_449 | HIST | 72 | 384 |  |
| case_452 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_450 | CUR | 24 | 456 |  |
| case_453 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_451 | CUR | 48 | 456 |  |
| case_454 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_452 | CUR | 72 | 456 |  |
| case_455 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_453 | CUR | 24 | 528 |  |
| case_456 | ko | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_454 | CUR | 48 | 528 |  |
| case_457 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_455 | CUR | 72 | 528 |  |
| case_458 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_456 | CUR | 24 | 600 |  |
| case_459 | es | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_457 | CUR | 48 | 600 |  |
| case_460 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_458 | CUR | 72 | 600 |  |
| case_461 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_459 | CUR | 24 | 672 |  |
| case_462 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_460 | CUR | 48 | 192 |  |
| case_463 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_461 | CUR | 72 | 192 |  |
| case_464 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_462 | CUR | 24 | 264 |  |
| case_465 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_463 | HIST | 48 | 264 |  |
| case_466 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_464 | HIST | 72 | 264 |  |
| case_467 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_465 | HIST | 24 | 336 |  |
| case_468 | ja | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_466 | CUR | 48 | 336 |  |
| case_469 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_467 | CUR | 72 | 336 |  |
| case_470 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_468 | CUR | 24 | 408 |  |
| case_471 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_469 | CUR | 48 | 408 |  |
| case_472 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_470 | CUR | 72 | 408 |  |
| case_473 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_471 | CUR | 24 | 480 |  |
| case_474 | fr | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_472 | CUR | 48 | 480 |  |
| case_475 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_473 | CUR | 72 | 480 |  |
| case_476 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_474 | CUR | 24 | 552 |  |
| case_477 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_475 | CUR | 48 | 552 |  |
| case_478 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_476 | CUR | 72 | 552 |  |
| case_479 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_477 | CUR | 24 | 624 |  |
| case_480 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_478 | CUR | 48 | 624 |  |
| case_481 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_479 | CUR | 72 | 624 |  |
| case_482 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_480 | CUR | 24 | 216 |  |
| case_483 | pt | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_481 | HIST | 48 | 216 |  |
| case_484 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_482 | CUR | 72 | 216 |  |
| case_485 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_483 | CUR | 24 | 288 |  |
| case_486 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_484 | HIST | 48 | 288 |  |
| case_487 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_485 | CUR | 72 | 288 |  |
| case_488 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_486 | CUR | 24 | 360 |  |
| case_489 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_487 | HIST | 48 | 360 |  |
| case_490 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_488 | CUR | 72 | 360 |  |
| case_491 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_489 | CUR | 24 | 432 |  |
| case_492 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_490 | CUR | 48 | 432 |  |
| case_493 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_491 | CUR | 72 | 432 |  |
| case_494 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_492 | CUR | 24 | 504 |  |
| case_495 | ko | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_493 | CUR | 48 | 504 | UPPERCASE |
| case_496 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_494 | CUR | 72 | 504 |  |
| case_497 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_495 | CUR | 24 | 576 |  |
| case_498 | es | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_496 | HIST | 48 | 576 |  |
| case_499 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_497 | HIST | 72 | 576 |  |
| case_500 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_498 | CUR | 24 | 648 | UPPERCASE |
| case_501 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_499 | CUR | 48 | 648 | UPPERCASE |
| case_502 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_500 | CUR | 72 | 168 |  |
| case_503 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_501 | CUR | 24 | 240 |  |
| case_504 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_502 | CUR | 48 | 240 |  |
| case_505 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_503 | CUR | 72 | 240 |  |
| case_506 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_504 | CUR | 24 | 312 |  |
| case_507 | ja | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_505 | CUR | 48 | 312 |  |
| case_508 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_506 | CUR | 72 | 312 |  |
| case_509 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_507 | CUR | 24 | 384 |  |
| case_510 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_508 | CUR | 48 | 384 |  |
| case_511 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_509 | HIST | 72 | 384 |  |
| case_512 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_510 | CUR | 24 | 456 |  |
| case_513 | fr | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_511 | CUR | 48 | 456 |  |
| case_514 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_512 | CUR | 72 | 456 |  |
| case_515 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_513 | CUR | 24 | 528 |  |
| case_516 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_514 | CUR | 48 | 528 |  |
| case_517 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_515 | CUR | 72 | 528 |  |
| case_518 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_516 | CUR | 24 | 600 |  |
| case_519 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_517 | CUR | 48 | 600 |  |
| case_520 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_518 | HIST | 72 | 600 |  |
| case_521 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_519 | CUR | 24 | 672 |  |
| case_522 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_520 | CUR | 48 | 192 |  |
| case_523 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_521 | CUR | 72 | 192 |  |
| case_524 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_522 | CUR | 24 | 264 |  |
| case_525 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_523 | HIST | 48 | 264 |  |
| case_526 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_524 | CUR | 72 | 264 |  |
| case_527 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_525 | CUR | 24 | 336 |  |
| case_528 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_526 | CUR | 48 | 336 |  |
| case_529 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_527 | CUR | 72 | 336 |  |
| case_530 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_528 | HIST | 24 | 408 |  |
| case_531 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_529 | CUR | 48 | 408 |  |
| case_532 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_530 | HIST | 72 | 408 |  |
| case_533 | en | NON_DELETION | CORRECTION (phone update); "leave the account active" | NOT_STARTED | user_531 | CUR | 24 | 480 |  |
| case_534 | en | NON_DELETION | MARKETING OPT-OUT; explicit "I am not asking for deletion" | NOT_STARTED | user_532 | CUR | 48 | 480 |  |
| case_535 | en | NON_DELETION | ACCESS / PORTABILITY export; "keep the account as it is" | NOT_STARTED | user_533 | CUR | 72 | 480 |  |
| case_536 | en | NON_DELETION | LOGIN / PASSWORD RESET support; "Do not close the account" | NOT_STARTED | user_534 | CUR | 24 | 552 |  |
| case_537 | en | NON_DELETION | CORRECTION (surname); "without removing any of my records" | NOT_STARTED | user_535 | CUR | 48 | 552 |  |
| case_538 | en | NON_DELETION | MARKETING OPT-OUT; "marketing lists only"; uses the word "remove" (trap) | NOT_STARTED | user_536 | CUR | 72 | 552 |  |
| case_539 | en | NON_DELETION | ACCESS (DSAR: what data do you hold); "not a request to erase it" | NOT_STARTED | user_537 | CUR | 24 | 624 |  |
| case_540 | en | NON_DELETION | DOCUMENT COPY (invoices); "leave my profile and purchase history in place" | NOT_STARTED | user_538 | CUR | 48 | 624 |  |
| case_541 | en | NON_DELETION | CORRECTION (change email); "I want to continue using the service" | NOT_STARTED | user_539 | CUR | 72 | 624 |  |
| case_542 | en | NON_DELETION | ACCESS (copy of info); "please don't delete or change anything" (contains "delete" — negated) | NOT_STARTED | user_540 | CUR | 24 | 216 |  |
| case_543 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_543 | CUR | 24 | 288 |  |
| case_544 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_544 | CUR | 48 | 288 |  |
| case_545 | en | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_545 | CUR | 72 | 288 |  |
| case_546 | pt | DELETION | templated deletion (S1 intent=delete) | PARTIALLY_COMPLETE | user_546 | CUR | 24 | 360 |  |
| case_547 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_547 | CUR | 48 | 360 |  |
| case_548 | en | DELETION | templated deletion (S1 intent=delete) | NOT_STARTED | user_548 | CUR | 72 | 360 |  |
| case_549 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_549 | CUR | 24 | 432 |  |
| case_550 | en | DELETION | templated deletion (S1 intent=delete) | COMPLETE | user_550 | CUR | 48 | 432 |  |

## 9. Sample table (32 rows) with raw text

| case_id | lang | gold status | reported_status | email_match | gist |
|---|---|---|---|---|---|
| case_01 | | COMPLETE | COMPLETE | CUR | Hi, I haven’t used this account in years and would like it closed. Please remove the profile and the personal details attached to it. |
| case_02 | | COMPLETE | PARTIALLY_COMPLETE | CUR | Intenté eliminar mi cuenta ayer, pero la página terminó mostrando un error. ¿Pueden comprobar si todavía queda algún dato y completar la eliminación si hace falta? |
| case_03 | | COMPLETE | COMPLETE | CUR | Je demande la suppression définitive du compte associé à cette adresse e-mail. Veuillez examiner les identifiants actuels et antérieurs conformément à votre procédure de confidentialité. Merci de confirmer le résultat une fois la vérification terminée. |
| case_04 | | COMPLETE | COMPLETE | CUR | I’m deleting my account. You can keep anonymous statistics, but nothing in analytics should still point back to me. |
| case_05 | | INCOMPLETE | COMPLETE | CUR | I deleted this account and received a confirmation, but the same email address is still recognized. Please remove any remaining copy of my profile. |
| case_06 | | INCOMPLETE | PARTIALLY_COMPLETE | CUR | My account page is gone, but my old profile still appears when I search for it. Can you remove that search result too? |
| case_07 | | INCOMPLETE | COMPLETE | CUR | Please delete my account and the identity document I sent to support while resolving a delivery issue. |
| case_08 | | INCOMPLETE | PARTIALLY_COMPLETE | CUR | I closed my account, but an old “download your data” link still works. Please delete that export file as well. |
| case_09 | | INCOMPLETE | NOT_STARTED | CUR | Please permanently delete the account associated with this email address. Please apply the correct treatment to records covered by the request. Please confirm when the review is complete. |
| case_10 | | INCOMPLETE | COMPLETE | HIST | I used this Yahoo address before changing the email on my account. Please remove records linked to both the old and current addresses. |
| case_11 | | INCOMPLETE | COMPLETE | CUR | I would like the account associated with this address to be erased. Please handle any copies that fall within the scope of the deletion request. Please contact me if you need information to verify the request. |
| case_12 | | INCOMPLETE | COMPLETE | CUR(changed) | I changed the email on this account before deleting it. Please check that nothing tied to the old address was left behind, even in systems that do not display the email. |
| case_13 | | INCOMPLETE | NOT_STARTED | CUR | Please close my account and process the associated personal-data deletion. Please check the records connected to the account before confirming completion. Please contact me if you need information to verify the request. |
| case_14 | | INCOMPLETE | COMPLETE | CUR | このメールアドレスに関連するアカウントの完全な削除を依頼します。 プライバシー手続きに従い、現在および過去の識別情報を確認してください。 確認が完了したら結果をお知らせください。 |
| case_15 | | INCOMPLETE | COMPLETE | CUR | I disconnected my account last week, but one of the integrations still seems active. Close the account completely and make sure it can no longer send my data to other systems. |
| case_16 | | INCOMPLETE | NOT_STARTED | CUR | Please treat this message as a request for permanent account deletion. Please include information linked through current or earlier account identifiers. A short confirmation when the process is complete is sufficient. |
| case_17 | | INCOMPLETE | NOT_STARTED | CUR | I want to close this account permanently. You may retain backups if required, but they must not be able to restore my personal profile. |
| case_18 | | INCOMPLETE | COMPLETE | CUR | I am asking you to remove my account and the personal information linked to it. Please review any identifiers connected to this account as part of the request. Please let me know once the request has been reviewed. |
| case_19 | | INCOMPLETE | PARTIALLY_COMPLETE | CUR | Please remove my profile and clean my personal details out of earlier support conversations. Some of those messages also relate to another customer, so the conversation itself may need to stay. |
| case_20 | | INCOMPLETE | NOT_STARTED | CUR | Please treat this message as a request for permanent account deletion. Please check the records connected to the account before confirming completion. Please send a confirmation after the process finishes. |
| case_21 | | COMPLETE | COMPLETE | CUR | I deleted my account and received the confirmation email. Could you verify that the profile is gone and that anything retained for security is limited to what is required? |
| case_22 | | INCOMPLETE | COMPLETE | CUR | Please erase the account linked to this email address. Please apply the correct treatment to records covered by the request. Please send a confirmation after the process finishes. |
| case_23 | | INCOMPLETE | NOT_STARTED | CUR | Please delete this account, including the downloadable archive I requested earlier and any search result that still points to me. Security records can stay if policy requires them. |
| case_24 | | INCOMPLETE | COMPLETE | CUR | I was told that deletion was complete, but the account and its search result can still be found. Please investigate and finish the deletion. |
| case_25 | | COMPLETE | NOT_STARTED | CUR | The privacy page still says my request failed. Please inspect the actual systems and tell me whether the account and identifiable analytics data have already been removed. |
| case_26 | | COMPLETE | NOT_STARTED | CUR | I found an old report saying my account still existed. Please check the latest state and confirm that the profile is gone and that remaining records cannot identify me. |
| case_27 | | COMPLETE | COMPLETE | CUR | Please audit the deletion as it stood when my request was reviewed. I want confirmation that the account was fully removed at that point. |
| case_28 | | COMPLETE | NOT_STARTED | CUR | Can you verify that my account was deleted? A search result with a similar email belongs to someone else, so please do not treat that record as mine. |
| case_29 | | INCOMPLETE | NOT_STARTED | HIST | I used a different email on this account before changing it. Please remove records under both addresses and switch off any integration that could copy them back into search or analytics. |
| case_30 | | INCOMPLETE | COMPLETE | HIST | I was told the account had been deleted, but I can still find traces in search, support, and analytics. Please handle them and disable any synchronization that could recreate them. |
| case_31 | | COMPLETE | COMPLETE | CUR | I no longer need this account. Please remove my name and contact details, but keeping an internal deleted-account reference is fine if other required records still depend on it. |
| case_32 | | INCOMPLETE | PARTIALLY_COMPLETE | CUR | The account itself is gone, but an internal deleted-account record still shows my personal details. Please keep only the reference needed for retained records and remove the rest. |
