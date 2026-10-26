# T19 — IntentClassifier (LLM primary + principled lexicon)

| Field | Value |
|---|---|
| ID | T19 |
| Milestone | M4 |
| Depends on | T10, T04 |
| Size | M |
| SPEC refs | §9 |

## Files
- `code/ghostaudit/intent.py`
- `code/ghostaudit/llm/prompts/intent.v1.md`
- `code/tests/test_intent.py`

## Description
Decide whether each request authorizes deletion, robustly across languages and phrasings, without fitting to eval texts.

## Implementation notes
- **Lexicon** (SPEC §9.2), written from general linguistic patterns and documented in the module docstring; no eval sentences are copied:
  - (a) negation within 6 tokens before a deletion verb, in EN, FR, ES, PT, JA and KO;
  - (b) keep-active constructions;
  - (c) access/correction/export/copy/opt-out primary intent with no unnegated deletion verb.
  Retention permissions are excluded.
- **LLM** (`intent.v1.md`, `--intent-model`, default `claude-opus-5-5`, effort `low`, structured outputs): the system prompt is ≥ 600 tokens, covering definitions, multilingual guidance and about 6 **synthetic** few-shot examples with no eval text, so prompt caching applies (minimum 512) via `cache_control`. Strict JSON `[{case_id, deletion, confidence, language, reason}]`.
  - Each text is wrapped in delimiters and treated as data.
  - The **per-item** cache key is sha256(model, prompt_hash, normalized text); only misses are batched (≤ 25).
  - The returned id set must equal the batch set; otherwise retry the missing items singly, then fall back.
- **Resolution:**
  - the LLM decides when available, unless its confidence is < 0.6, in which case the lexicon decides;
  - `off` or a miss → lexicon;
  - N rows are logged only.
  Write the agreement matrix (lexicon × LLM × N) to diagnostics.

## Acceptance criteria
- [ ] **Diagnostics check, not a test assertion:** the eval NOT_APPLICABLE set equals the 10 intake-corroborated cases under both the LLM path and the lexicon. No eval case id appears in code or tests. Tests assert on synthetic phrasings and on the 32 samples, where no case is NOT_APPLICABLE.
- [ ] The lexicon correctly handles paraphrases that do not occur in the dataset: 'please don't remove my account', 'ne supprimez pas mon compte', 'アカウントを削除しないでください', 'I only want a copy of my data'.
- [ ] 'You can keep anonymous statistics', 'retain backups if required' and 'security records can stay' are **not** flagged.

## Tests
- Lexicon unit tests with ≥ 20 phrasings across languages.
- Fake-LLM arbitration at confidence 0.95 and 0.4.
- Dropped-id retry.

## Risks
- Lexicon over-reach. Keep its patterns narrow and test them for both precision and recall.

## Definition of Done
See `README.md` § Definition of Done.
