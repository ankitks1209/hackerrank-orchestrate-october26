# T12 — EvidenceIndex + ScopeAssertion store

| Field | Value |
|---|---|
| ID | T12 |
| Milestone | M2 |
| Depends on | T05, T06, T07, T09, T11a, T03 |
| Size | M |
| SPEC refs | §3, T1–T3 |

## Files
- `code/ghostaudit/evidence/index.py`
- `code/tests/test_index.py`

## Description
Run every parser once in manifest order and build immutable lookup indexes.

## Implementation notes
- `build_index(reader, manifest, identity, media_facts: Mapping[str, MediaFacts]) -> EvidenceIndex`. Media facts are precomputed by T11b, or `{}`.
- Indexes are dicts of tuples, sorted by `(entry_time, captured_at, order)`:
  - `by_rid`;
  - `users_by_rid`;
  - `rids_by_user`;
  - `mentions[rid] -> file_ids` (manifest order);
  - `scopes_by_file`;
  - `files_sorted` (for bisect);
  - `pointers` (`source_resource_id`).
- `files_in_window(lo, hi)` is inclusive on both ends.
- No parity check against `solution/` in shipped code. An optional manual dev script may live outside `code/`.

## Acceptance criteria
- [ ] All 79 text files are claimed by exactly one parser. The 15 media files are handled via `media_facts`.
- [ ] `users_by_rid['search_8168']` is empty (the `.jr` decoy).
- [ ] `users_by_rid['tombstone_9178']` == `('user_542',)`, the subject of sample case_32.
- [ ] Build time is under 1 s (measured in T27).

## Tests
- A synthetic 3-file manifest.
- Window inclusivity.
- Tie ordering.

## Risks
- Prefer clarity over micro-optimization at this scale.

## Definition of Done
See `README.md` § Definition of Done.
