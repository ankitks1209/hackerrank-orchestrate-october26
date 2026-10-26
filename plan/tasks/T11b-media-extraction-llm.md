# T11b — Media extraction via LLM vision (pipeline pre-pass)

| Field | Value |
|---|---|
| ID | T11b |
| Milestone | M2 |
| Depends on | T10, T11a, T36 |
| Size | M |
| SPEC refs | F10, N7 |

## Files
- `code/ghostaudit/llm/media_extract.py`
- `code/ghostaudit/llm/prompts/media_extract.v1.md`
- `code/tests/test_media_extract.py`

## Description
Extract `MediaFacts` from the 11 PNGs and 4 PDFs with a cached, schema-validated vision call.

## Implementation notes
- Requests use structured outputs (`output_config.format` json_schema) at effort `low`, and `--media-model` selects the model (default `claude-opus-5-5`). Prompt `media_extract.v1.md` returns strict JSON `{records:[{display_id, resource_hint, system_hint, category, emails[], phones[], user_refs[], names[], state_facts{}, dates[]}]}`, and tells the model never to guess ids that are not shown.
- `extract_media_facts(entries, llm) -> dict[file_id, MediaFacts]`: one call per file. Run the schema check, retry once with an error hint, otherwise skip and add a note.
- **Scheduled cache-fill step:** with `ANTHROPIC_API_KEY` set, run `--llm live` once and commit `code/ghostaudit/cache/*.json`. Every later run uses `--llm cache`.
- Under `off`, or on a `CacheMiss`, return `{}` for that file and write a diagnostics note.

## Acceptance criteria
- [ ] After the cache fill, `map_facts` over the real extractions yields 12/12 LINK validations plus ev58 and ev55, matching the T11a fixtures.
- [ ] `--llm off` completes and logs 15 skips.

## Tests
- A fake LLM returning canned JSON.
- A schema-violation retry path.

## Risks
- Vision misreads. Alias/identifier validation in T11a bounds the damage, and the cache makes results reproducible.

## Definition of Done
See `README.md` § Definition of Done.
