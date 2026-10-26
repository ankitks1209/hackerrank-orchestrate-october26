# T10 — LLM layer: client Protocol, Anthropic client, disk cache, usage meter

| Field | Value |
|---|---|
| ID | T10 |
| Milestone | M2 |
| Depends on | T01 |
| Size | M |
| SPEC refs | §9, N1, N2, N4, N7 |

## Files
- `code/ghostaudit/llm/__init__.py`
- `code/ghostaudit/llm/client.py`
- `code/ghostaudit/llm/cache.py`
- `code/ghostaudit/llm/usage.py`
- `requirements.txt`
- `code/tests/test_llm_cache.py`

## Description
Provide a deterministic, metered and resilient LLM access layer that every AI feature goes through.

## Implementation notes
- **Prerequisites:**
  - the model ids and prices were verified with the `claude-api` skill on 2026-10-24: `claude-opus-5-5` costs $4 / $20 per MTok (cache read $0.20) and is the default for both roles; `claude-haiku-5-5` costs $0.10 / $0.50 and is evaluated as strategy S2; Batches are 50 % off. Re-check at T28;
  - `requirements.txt` holds `anthropic>=2.0.0; python_version >= "3.10"`, because SDK 1.x+ needs Python 3.10 and 2.0.0 sends API version 2026-10-21 by default. Run `pip index versions anthropic` before pinning;
  - ship a `.env.example` containing `ANTHROPIC_API_KEY=`;
  - the core never imports the SDK eagerly. Live mode on Python 3.9 raises `LLMUnavailable` with a clear message.
- Request/response types: `LLMRequest(model, system, messages, attachments: tuple[(bytes, mime)], max_tokens, prompt_version)` and `LLMResponse(text, input_tokens, output_tokens, model, cached)`.
- `AnthropicClient`:
  - lazy import; **no `temperature`/`top_p`/`top_k`** (a 400 since API 2026-10-21); explicit `output_config.effort="low"`; structured outputs via `output_config.format` (json_schema); fixed `max_tokens`; no prefill; 60 s timeout;
  - `stop_reason` `refusal` or `max_tokens` raises `LLMBadOutput`, so the caller falls back deterministically;
  - `cache_control` on the system block; `warm_up()` sends one serial call before the fan-out;
  - ≤ 3 retries with backoff and jitter, on 429/5xx only;
  - images as image blocks, PDFs as document blocks;
  - holds the `Secret` key.
- `DiskCache(dir)`: key = sha256 of the canonical request JSON (including attachment and prompt hashes). Writes are atomic: temp file + `os.replace`. Each entry stores text, usage and model; never the key.
- `CachingClient(inner, cache, meter, mode)`:
  - `off`: `LLMDisabled`;
  - `cache`: hit, or `CacheMiss`;
  - `live`: hit, or call and store.
  `complete_many(requests)` uses a bounded `ThreadPoolExecutor` (≤ 8 workers) in live mode only and returns results in input order.
- `UsageMeter`: per model, records calls, input/output tokens (output includes thinking), `cache_creation_input_tokens`/`cache_read_input_tokens`, images with estimated image tokens (≈ w×h/750), PDF pages, stop reasons, wall time, peak RPM/TPM, live vs replayed, and cost. `render_usage_report(meter, n_requests) -> str` produces per-model and overall totals, averages per request (518 and 550), batch vs sync cost, and cold run vs cached rerun.
- Optional (cut first): `--llm batch` through Message Batches, which only fills the cache; results are keyed by `custom_id`.

## Acceptance criteria
- [ ] The cache key is stable across processes and changes when the prompt version or an attachment changes.
- [ ] `cache` mode on an empty cache raises `CacheMiss`. `live` mode with a fake inner client stores the result and replays it with `cached=True`.
- [ ] The meter separates live and replayed tokens. The report has per-model and overall totals.
- [ ] The key value and `sk-` appear nowhere in the cache dir, `repr(config)`, captured logs or the rendered report.
- [ ] No outgoing request body contains `temperature`, `top_p` or `top_k` (asserted with the fake client).
- [ ] With a live key, `cache_read_input_tokens > 0` on calls 2..N of one prompt family. This is checked at T28.

## Tests
- Fake inner client.
- Atomic write: simulate a crash before `os.replace`.
- Key determinism.
- Secret-leak assertions.

## Risks
- SDK API drift. Confine the SDK to one class and verify the call shape with the skill.

## Definition of Done
See `README.md` § Definition of Done.
