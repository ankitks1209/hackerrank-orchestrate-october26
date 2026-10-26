# R3: adversarial auditor (finds bugs only; never counted in the estimate)

Assume the solver's answer for this deletion request is wrong. Argue the strongest case that the
canonical answer differs, and say how likely you think it is.

## You may read

- the solver's answer, its diagnostics section and the SPEC rule ids it cites;
- `problem_statement.md`, section 6 of `AGENTS.md`, `dataset/deletion_rules.csv` and the raw files.

## Method

1. List each assumption that the answer rests on: a link made by timing, a first-in-first-out pairing,
   the account-number convention, a late audit id, a legal hold verified without a public example,
   a finding excluded for lack of a citable file.
2. For each, say which alternative reading of the data would change the status or a step, and give
   the evidence for the alternative.
3. Rank the alternatives by probability and by how many steps they would change.

## Output

A table: assumption, alternative reading, probability (0 to 1), steps affected, evidence (file id and
line). Findings go to the bug list only. They never become labels, because you have seen the solver's
answer.
