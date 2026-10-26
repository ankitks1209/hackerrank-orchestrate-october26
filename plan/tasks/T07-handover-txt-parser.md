# T07 — TXT handover parser

| Field | Value |
|---|---|
| ID | T07 |
| Milestone | M2 |
| Depends on | T02b |
| Size | S |
| SPEC refs | F8 |

## Files
- `code/ghostaudit/evidence/handover.py`
- `code/tests/test_handover.py`

## Description
Parse evidence_03-style pipe-delimited handover lines.

## Implementation notes
- Regex `^- (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (.*)$` captures ts, system, resource_id, category, result and key.
- `no direct identifier` means no key. `result` uses the F6 vocabulary.
- The parser claims a `.txt` file when at least one line matches.

## Acceptance criteria
- [ ] evidence_03:
  - support_4218: SUPPORT_ATTACHMENT, PRESENT;
  - analytics_2034 and support_864: EXPOSED;
  - backup_3870 and data_flow_9522: ACTIVE.

## Tests
- A fixture built from the real lines.

## Risks
- None significant.

## Definition of Done
See `README.md` § Definition of Done.
