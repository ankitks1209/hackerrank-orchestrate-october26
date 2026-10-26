# T11a — Media facts → Observations (pure mapping, path a/b)

| Field | Value |
|---|---|
| ID | T11a |
| Milestone | M2 |
| Depends on | T04, T02b |
| Size | M |
| SPEC refs | F10, Q1, Q7 |

## Files
- `code/ghostaudit/evidence/media.py`
- `code/tests/test_media_mapping.py`

## Description
Map extracted media facts onto resources deterministically. This module never imports the LLM layer.

## Implementation notes
- `map_facts(entry, facts: MediaFacts, link_rows, prefixes) -> ParseOutput`.
- **Path (a), LINK join:** a LINK row whose alias or resource_id equals an extracted `display_id`/`resource_hint`. System, resource, user and email come from the LINK row.
- **Path (b), literal id + identifier:** an extracted literal resource id with a known prefix, plus at least one extracted email, phone or `user_N` key.
- State: map `state_facts` through a small frozen table, e.g. 'restore blocked: no' → ACTIVE, 'connector enabled' → ACTIVE, PII fields shown → EXPOSED, only the stable reference shown → REDACTED. The category comes from the extracted `category`.
- `entry_time` = the manifest `captured_at`. Timing is never used to join.
- If the extracted identity contradicts the LINK row (ev60), the LINK row wins and a note is recorded. A display-only reference with no state (ev04 → support_9538) is recorded as a `reference` note for Q1, not as an Observation.

## Acceptance criteria
- [ ] With fixture `MediaFacts` for all 15 files:
  - the 12 LINK targets map as in the SPEC F10 table;
  - ev58 → support_platform/support_001, PRESENT, SUPPORT_ATTACHMENT;
  - ev55 → security_service/audit_record_003, PRESENT;
  - ev27 → no Observation.
- [ ] An alias mismatch produces no Observation, only a note.

## Tests
- Fixture facts for ev32, ev28, ev58, ev60 and ev04.
- A mismatch path.

## Risks
- The fixtures encode expected extraction. They must be written from the images, never from gold.

## Definition of Done
See `README.md` § Definition of Done.
