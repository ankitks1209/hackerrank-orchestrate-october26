# T09 — Log trace join → Observations

| Field | Value |
|---|---|
| ID | T09 |
| Milestone | M2 |
| Depends on | T08 |
| Size | M |
| SPEC refs | F9 |

## Files
- `code/ghostaudit/evidence/logs.py`
- `code/tests/test_log_observations.py`

## Description
Turn LogRecords into Observations: join subject keys on trace_id, decode state and category, and drop noise.

## Implementation notes
- Pass 1: collect `*_started` keys into `trace_keys[trace]`. Key fields: `lookup_key`, `match_key`, `subject_ref`, `subject_key`, `scan_key`, `owner_key`.
- Pass 2: build Observations from state events (the SPEC F9 table). `keys = trace_keys[trace] ∪ inline keys`, with every key normalized through `keys.py`.
- The event table is a frozen constant, and so is the enumerated noise set. Any event in neither set is recorded as `unknown_event` in notes.
- Drop the evidence_53 `profile_service` 5-digit decoys. `entry_time` = the line ts.

## Acceptance criteria
- [ ] evidence_01:
  - L92 `contact_lookup_completed` carries the old-email hash key of sample case_12's subject;
  - data_flow_9846 ACTIVE;
  - backup_3245 ACTIVE.
- [ ] evidence_94: search_4013 PRESENT, analytics_037 EXPOSED, support_5569 EXPOSED, data_flow_4890 ACTIVE.
- [ ] evidence_61: support_002 PRESENT, keyed `e:nadia.ionescu@yahoo.com`. The `nadia.popescu` line resolves to no subject.
- [ ] Every event is in the state table, a `*_started` line, framing, or the noise set. `unknown_event` count = 0.

## Tests
- Interleaved noise between started and completed lines.
- A completed line without a started line.

## Risks
- Joining by adjacency is the classic bug. The interleaving fixture catches it.

## Definition of Done
See `README.md` § Definition of Done.
