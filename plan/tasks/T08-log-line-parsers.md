# T08 — Log line parsers (8 formats)

| Field | Value |
|---|---|
| ID | T08 |
| Milestone | M2 |
| Depends on | T02b |
| Size | M |
| SPEC refs | F9 |

## Files
- `code/ghostaudit/evidence/logs.py`
- `code/tests/test_log_formats.py`

## Description
Parse every log line into a uniform `LogRecord(ts, fmt, level, service, trace, event, kv)`.

## Implementation notes
- Dispatch on the first token after the timestamp:
  - `level=` → logfmt / readback;
  - `{` → JSON;
  - `<PRI>1` → syslog;
  - `[` → bracket;
  - `|` → pipe;
  - `requestId=` → cloud nested (parse `message=` a second time);
  - `^(DEBUG|INFO|WARN|ERROR) service=\S+ event=record_lookup` → diag. **Any level.**
- KV regex (precompiled): `([A-Za-z_][\w.]*)=("((?:[^"\\]|\\.)*)"|\S+)`. Unescape `\"`. The literal `null` becomes `None`.
- No `instance` fallback for a missing trace id. Port `kvparse`/`parse_line` from `solution/notes/scripts/logparse.py` without importing it.
- Drop `log_router` / `readback_collector` framing lines.

## Acceptance criteria
- [ ] Every non-empty line in all 26 logs parses, with zero `ParseError`.
- [ ] One fixture per format, including a **WARN** `record_lookup` line from evidence_08 (analytics_3181 IDENTIFIABLE).

## Tests
- 8+1 fixture tests.
- A full-corpus test that counts lines per format.

## Risks
- Cloud-nested escaping is the trickiest format. Test it with embedded quotes and `@`.

## Definition of Done
See `README.md` § Definition of Done.
