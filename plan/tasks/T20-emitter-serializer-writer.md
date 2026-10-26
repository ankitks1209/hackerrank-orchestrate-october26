# T20 — Emitter, serializer, output writer, gold helper

| Field | Value |
|---|---|
| ID | T20 |
| Milestone | M4 |
| Depends on | T01 |
| Size | S |
| SPEC refs | §8.1, §8.2, §8.4 |

## Files
- `code/ghostaudit/emit.py`
- `code/tests/gold.py`
- `code/tests/test_emit.py`

## Description
Turn verdicts into ordered steps, write `output.csv`, and provide the tests-only gold reader and abstraction helper.

## Implementation notes
- `emit(verdicts) -> (status, steps)`:
  - violating → FINDING (cite), REMEDIATION (""), VERIFICATION ("");
  - compliant → VERIFICATION (cite in a COMPLETE case, "" in an INCOMPLETE one).
  Sort key `(Phase, op_index, system_id, resource_id)` with plain string comparison (the `resource_sort` flag was removed: 0 cases differ). Deduplicate, then renumber.
- `serialize(steps)`: `json.dumps([...], sort_keys=True, separators=(',',':'), ensure_ascii=False)`. `write_output(results, path)`: exact header; natural numeric case order; `csv.writer` QUOTE_MINIMAL; UTF-8; `lineterminator='\n'`.
- `tests/gold.py`:
  - `GoldReader`, the only code that opens `sample_output.csv`;
  - `abstract_verdicts(gold_steps)`: the inverse of `emit`, used by T18a/T18b/T23/T24.
- Port `emit` and OPS/TREAT/STATE from `solution/notes/proto/emit_check.py`, built on `OPERATION_TABLE`.

## Acceptance criteria
- [ ] Round trip: abstracting and re-emitting all 32 gold arrays gives equal JSON (32/32).
- [ ] NOT_APPLICABLE gives `[]`. Every step has exactly 7 keys.

## Tests
- Round trip.
- Dedup.
- Phase ordering of the analytics/support pair (sample case_11).

## Risks
- None significant; the prototype already proves the logic.

## Definition of Done
See `README.md` § Definition of Done.
