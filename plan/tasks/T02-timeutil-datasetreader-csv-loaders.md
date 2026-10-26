# T02 — timeutil, allowlisted DatasetReader, typed CSV loaders

| Field | Value |
|---|---|
| ID | T02 |
| Milestone | M0 |
| Depends on | T01 |
| Size | S |
| SPEC refs | §2, T6, N3, N5 |

## Files
- `code/ghostaudit/timeutil.py`
- `code/ghostaudit/dataset.py`
- `code/tests/test_dataset.py`

## Description
Route all input access through one reader that loads typed records and refuses evaluation-only files.

## Implementation notes
- `to_epoch(s) -> int` with `lru_cache`. Handle `Z`, `+00:00`, fractional seconds and the `T` separator. Also provide `iso(epoch)`.
- `DatasetReader(root)` has an allowlist: the 8 participant CSVs plus `evidence/**`.
  - `open('sample_output.csv')`, or any path outside `dataset/`, raises `ForbiddenInputError`.
  - Gold is read only by `tests/gold.py` (T20).
- Loaders return tuples of dataclasses:
  - `requests()`: eval and sample, with `is_sample`;
  - `identities()`;
  - `audit_log()`;
  - `activity()`: raw rows;
  - `rules()`;
  - `manifest()`: `ManifestEntry` with `order`.
- Open files with `encoding='utf-8', newline=''`.

## Acceptance criteria
- [ ] Counts: 518 eval + 32 sample requests; 850 identities; 306 audit rows; 4011 activity rows; 15 rules; 94 manifest entries. Every manifest path exists.
- [ ] `ForbiddenInputError` is raised for `sample_output.csv` and for any path outside `dataset/`.
- [ ] Every timestamp style in the dataset parses.

## Tests
- Count assertions.
- Forbidden-path test.
- Timestamp fixture table.

## Risks
- Use `Path` joins only, so paths work on Windows.

## Definition of Done
See `README.md` § Definition of Done.
