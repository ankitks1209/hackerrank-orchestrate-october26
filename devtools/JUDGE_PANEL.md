# Judge panel record (R9)

Calibration: pass
Lowest code score: 26
Blockers: 0
Transcript score: 9

Record for rc3, POST-FIX panel scores (the panel run after the close-out fixes, with the default intent
model restored to claude-opus-5-5, the audit-backed account steps and the compliant-row floor kept, and
`strict_signature_time=True` kept as the default). The scores and deductions below are copied as given by
the panel; none was invented or adjusted. Deduction texts are shortened at the length the panel report
gave them. Calibration: the `Calibration: pass` line comes from the earlier calibration run (below); no
new calibration run was made for rc3.

Gate R9 needs a lowest code score of at least 28.5 and a transcript score of at least 9.5. The rc3 scores
(lowest code score 26, transcript score 9) are BELOW both thresholds, so R9 fails honestly. No deduction
is marked a blocker (the highest severity in any list is major).

## Panel calibration

Calibration run (claude-opus-5-5), score 22, made before rc3. The panel built the archive with
`code/tools/build_zip.py`, unzipped it, and made a seeded copy with two defects: (1) the README Quick start
command was changed to the nonexistent `python3 code/run_audit.py`; (2) per-request tokens and cost, the
Total tokens column and the overall token total were removed from both usage reports. Both seeded defects
were caught, as the first two deductions, so the panel counts as calibrated. The repository was not touched
by the calibration.

## Scores after the fixes (rc3)

| Persona | Score |
|---|---|
| rules | 26.75 |
| quality | 26 |
| newcomer | 27.5 |
| transcript | 9 |

## Deductions by persona

### rules (26.75)

  - major 1 architecture & design quality: Linking depends on constants fitted to this dataset's generator: fixed link windows in code/ghostaudit/config.py (account_window -78..-42 min, policy_window -30
  - major 0.5 correctness safeguards (AGENTS 6.2 time contract): Two inference paths read evidence captured after audit_at, and both are on by default. use_late_audit_ids=True turns audit-record ids found only in later files 
  - major 0.5 correctness safeguards (AGENTS 6.7 no case-family shortcuts): ghostaudit/handcrafted.py _convention_account derives account_00N for user_01..user_10 (CONFIG CONVENTION_MAX_USER=10, CONVENTION_ACCOUNT_FORMAT='account_%03d')
  - minor 0.5 AI usage quality: The model adds little to intent: S0 (lexicon only) finds the same 10 NOT_APPLICABLE cases, and S2 (Haiku intent) matches S1 on every sample and eval row at $0.3
  - minor 0.5 evaluation report: All accuracy figures are in-sample on the 32 public samples that were used to tune windows, conventions and the audit-record rule. The report discloses this. Se
  - minor 0.25 security & hygiene: code.zip ships 843 cached model responses in code/ghostaudit/cache/. Ten of them contain names and emails transcribed from dataset images and PDFs, such as addr

### quality (26)

  - major 1.5 architecture & design quality: The way cases are linked to resources depends on constants fitted to this one dataset's generator. Link windows are hard-coded from the 'observed spread' in cod
  - major 1 correctness safeguards: There is a case-family shortcut that produces an id no file supports. In code/ghostaudit/handcrafted.py, _convention_account maps user_01..user_10 to account_00
  - minor 0.5 correctness safeguards: A single unrecognised activity row stops the whole run. In code/ghostaudit/activity.py, classify_row raises UnclassifiedActivityError when no regex template mat
  - minor 0.5 architecture & design quality: There are a lot of moving parts, and some constants have no stated source. Ten inference flags, a fixed-point link solver, a handcrafted-sources path and severa
  - minor 0.5 AI usage quality: The model choice and one claim are questionable. The report's own strategy table shows the Haiku intent model (S2) matching Opus (S1) on every sample and every 
  - minor 0.5 evaluation report: All accuracy figures are in-sample. The 32 public samples were also used to fit the link windows, the account_00N convention and the audit-record rule. The repo

### newcomer (27.5)

  - minor 0.75 architecture & design quality: Linking depends on constants fitted to this dataset's generator. Link windows in code/ghostaudit/config.py (account_window -78..-42 min, violation_window 30..13
  - minor 0.25 architecture & design quality: The account_00N convention (handcrafted.py, CONVENTION_ACCOUNT_FORMAT='account_%03d', CONVENTION_MAX_USER=10) builds a resource id from user_01..user_10 instead
  - minor 0.5 correctness safeguards: Two defaults read evidence captured after audit_at, which goes against the time contract ('Use only information available at or before audit_at'). use_late_audit_ids
  - minor 0.25 runnability & reproducibility: output.csv is sorted by the numeric part of case_id (case_33, case_34, ..., case_100), not lexicographically. The contract only says 'Sort rows by case_id', and
  - minor 0.25 AI usage quality: Opus stays the default intent model even though the report measures S2 (Haiku for intent) as identical on all 32 samples and all 518 evaluation rows, at about 4
  - minor 0.5 evaluation report: All accuracy figures are in-sample. The 32 public samples were the development set used to fit windows and conventions, so the 1.0000 status and 0.9948 step F1 

### transcript (9)

  - major 0.5: The rc3 apply and verify sub-agent entries (00:42:56, 00:45:55) have no matching main-session turn entry. The user prompt that launched rc3, which restored the 
  - minor 0.25: check_log.py warns at log.txt:55: the '[subagent group] Planning research and plan-doc adversarial review' summary has 6 sentences, and §5.2 allows 2-5.
  - minor 0.25: check_log.py warns at log.txt:807: the verify:T03 entry logs a full dataset email address (inside sha256(...)). §5.4 asks that no personal or dataset identifier

## Scores before the fixes (rc2, kept for comparison)

| Persona | Score |
|---|---|
| rules | 23.5 |
| quality | 26 |
| newcomer | 25.25 |
| transcript | 8 |

## Open items

Not resolved by the rc3 freeze step: this step changes records only and does not touch code. The panel's
deductions about dataset-fitted link windows, the `account_00N` convention, and the late-evidence inference
defaults are measured and disclosed in the README and the evaluation report; changing them is a decision for
the repository owner.
