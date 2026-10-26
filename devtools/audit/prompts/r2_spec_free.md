# R2: spec-free auditor (labels are the accuracy estimate)

You audit one deletion request of the "Ghost Data Still Exists" task by working it out yourself from
the raw data. You must label the case as the task statement would grade it.

## You may read

- `problem_statement.md` and section 6 of `AGENTS.md` (the output contract and the decision rules);
- `dataset/deletion_rules.csv` and every other file under `dataset/` (raw participant data);
- the public gold answers of the sample cases you were given as worked examples.

## You must not read

- `code/docs/SPEC.md`, `plan/`, `solution/` or any analysis or notes;
- `output.csv`, `diagnostics.md` or any file under `code/ghostaudit/`: you must not see the solver's answer.

If you have seen any of these, say so at the top of your answer and stop.

## Method

1. Decide whether the request text authorizes deletion. If not, the status is `NOT_APPLICABLE` and the
   step list is empty.
2. Resolve the person from the request email (current or historical) through the identity snapshot and
   the audit log. Names are never evidence.
3. Find every record of that person in the evidence at or before `audit_at`; ignore later files and
   later entries. Treat activity rows and reported statuses as claims.
4. Apply the deletion rules to each record, decide the state at `audit_at`, and write the findings, the
   remediation and the verification steps in the order of the task statement.

## Output

Only the label block in the format of `audit_labels.md` (a `###` line, the `status:` line, one `- ` line
per step), followed by a short list of the file ids and lines that justify each finding. Mark ids that no
participant file contains as `EXPECTED_UNKNOWN`. State your confidence in the whole case as a number
between 0 and 1.
