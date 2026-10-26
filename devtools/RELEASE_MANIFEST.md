# Release manifest

| Field | Value |
|---|---|
| release candidate | `rc4` |
| date | `2026-10-25` |
| output.csv sha256 | `23eacbffa4f02b9284eeb5e3f55c83973e5e9e04c8804f5e133c3727b0920310` |
| zip file sha256 | `cd125671c04430faae6dff582d15111e6021d08e9d0e1ef36774e2c8b65fab28` |
| zip content hash | `184afdf720b2530055745d9156f85d57af6d1f5462419b59f8faf6b9974b542a` |
| dataset hash | `7868d367b4084848d94a9bb3001c7d1d10026dbce9539a0f802fd4fcef8ee5df` |

## Gates at the freeze

| Gate | Name | Status | Detail |
|---|---|---|---|
| R1 | Validator and byte-identical rerun | pass | contract clean, bytes identical |
| R2 | Golden sample gate | pass | status 32/32 and exact >= 30/32 with the pinned misses |
| R3 | Label-free P2a-c | pass | no failure, nothing unexplained |
| R4 | Blind-audit estimation sample | waived | WAIVED (R4): post-freeze estimation sample of at least 100 cases was not drawn; a targeted 61-case audit was run instead (devtools/audit/coverage_result.md); no unbiased error-rate estimate is claimed (devtools/audit/estimation_result.md) [underlying fail: gate row is not pass or status errors exist] |
| R5 | Blind-audit coverage set | pass | record accepted |
| R6 | P5 invariants | pass | 5 hard invariants hold |
| R7 | Pareto no-regression | pass | no grader regressed |
| R8 | Clean-room matrix | pass | every cell byte-identical, no cache miss, no-dataset run clean |
| R9 | Code and transcript panels | waived | WAIVED (R9): self-imposed thresholds (code >= 28.5/30, transcript >= 9.5/10) not met: latest panel scores rules 26.75, quality 26, newcomer 27.5, transcript 9; no blockers; check_log.py clean [underlying fail: lowest code score 26.0 < 28.5; transcript score 9.0 < 9.5] |
| R10 | Override ban | pass | static scan, relabeling, late evidence and narrow-rule review pass |
| R11 | Package checks | pass | archive and reports consistent |
| R12 | Freeze manifest | pass | manifest matches output, archive and dataset |

## Waivers

Recorded decisions to freeze although these gates do not pass. A waived gate is not a pass.

- R4: post-freeze estimation sample of at least 100 cases was not drawn; a targeted 61-case audit was run instead (devtools/audit/coverage_result.md); no unbiased error-rate estimate is claimed (devtools/audit/estimation_result.md)
- R9: self-imposed thresholds (code >= 28.5/30, transcript >= 9.5/10) not met: latest panel scores rules 26.75, quality 26, newcomer 27.5, transcript 9; no blockers; check_log.py clean

## Changes since the previous candidate

Compared with the rc3 gate run (output.csv sha256 23eacbffa4f02b9284eeb5e3f55c83973e5e9e04c8804f5e133c3727b0920310, code.zip content hash 9d8ff460f6264d7ecaaf4e9c5c290df9dfc3b521d5d056de5ebbce80a43300a2, code.zip file sha256 906dbf0da090e6f1087102cf94632e49b7c766bdb600fdda21edc64c91c3e598):

- output.csv is unchanged: the sha256 is identical to rc3, and a fresh cached run makes 0 live calls (0 cache misses); samples stay 32/32 status and 30/32 exact.
- Activity rows of an unrecognised shape are classified UNCLASSIFIED (inert, one warning per shape, counted in diagnostics.md) instead of aborting the run; there are 0 such rows in the real data.
- The eval-cohort ceiling constants and the `--ceilings` option were removed; the evaluation report describes the structural loss as the pipeline's own discovery coverage.
- The 15 media cache entries are redacted at rest (emails and phones hashed, names dropped); hashed forms are matched through the new `hp:` and `h:` identity keys, and live cache writes are redacted too (DECISIONS D25).
- code.zip was rebuilt: content hash 184afdf7...542a (rc3: 9d8ff460...00a2), file sha256 cd125671...ab28 (rc3: 906dbf0d...c598). The dataset hash is unchanged.
- release_gate.py gained an explicit waiver mechanism (`--waive`, `--waiver-reason`, `--changes-file`). R4 and R9 are waived in this freeze by the repository owner's decision; the waiver reasons are listed above.

Commits and tags are made only with the user's consent. Before upload, run `release_gate.py --verify-upload <output.csv> <code.zip>` to compare the chosen files with this manifest.
