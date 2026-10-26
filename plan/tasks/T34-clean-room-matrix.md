# T34 — Clean-room reproduction matrix

| Field | Value |
|---|---|
| ID | T34 |
| Milestone | M7 |
| Depends on | T33, T21, T24, T36 |
| Size | M |
| SPEC refs | LOCAL_EVALUATION_STRATEGY §5, R8 |

## Files
- `code/tools/clean_room.py`

## Description
Run the submission the way a judge would, across an environment matrix, and prove the output is byte-identical.

## Implementation notes
- Unzip at a different absolute path. Extract the README's commands **literally** from a marked block. Run under `env -i` (no API key) and `sandbox-exec` with network denied.
- Matrix:
  - `PYTHONHASHSEED` ∈ {0, 4242};
  - `TZ` ∈ {UTC, Pacific/Kiritimati};
  - cwd ∈ {root, code/};
  - Python ∈ {system 3.9, uv 3.12}.
- Run without `dataset/`: expect a clear exit, and dataset tests skip. Gate on `cache_misses == 0` and wall time (target < 5 s, gate < 30 s).

## Acceptance criteria
- [ ] Every matrix cell gives a byte-identical `output.csv`. No tracebacks.

## Tests
- This task is the test.

## Risks
- `sandbox-exec` is macOS-only. Fall back to env-only isolation elsewhere and note it.

## Definition of Done
See `README.md` § Definition of Done.
