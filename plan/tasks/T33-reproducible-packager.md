# T33 — Reproducible packager and zip-listing checks

| Field | Value |
|---|---|
| ID | T33 |
| Milestone | M7 |
| Depends on | T20, T30b |
| Size | S |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §5 |

## Files
- `code/tools/build_zip.py`
- `code/tests/test_build_zip.py`

## Description
Build `code.zip` deterministically and check what is actually inside it.

## Implementation notes
- Build with stdlib `zipfile`: sorted entries, fixed 1980 timestamps, fixed permissions. Write a content manifest of (path, sha256) and a content hash.
- Checks on the **zip listing**:
  - presence: README, main, docs, prompts, cache, both report copies;
  - absence: `dataset/`, `solution/`, `plan/`, `log.txt`, `*.pyc`, `*.pkl`, `.DS_Store`, `.env`, `__pycache__`, `.venv`, nested archives of any extension;
  - a grep of shipped text for `/Users/`, the user's email, dataset emails or phones in Markdown, and key patterns.
- Round-trip gate: re-serializing `sample_output.csv` with the T20 writer is byte-identical.

## Acceptance criteria
- [ ] Two builds give identical bytes. All listing checks pass.

## Tests
- Build twice and compare.
- Negative fixtures for each forbidden pattern.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
