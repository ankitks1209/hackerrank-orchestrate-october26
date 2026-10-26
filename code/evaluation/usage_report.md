# Usage report

The submitted `output.csv` was produced by the earlier deterministic pipeline run; the figures below are for the shipped agent version.

Model usage of the final full-dataset run: provider, models, calls, input and
output tokens, total and average tokens per request, and estimated total and per-request cost, per model
and overall. The tables are filled by `python3 -m tools.render_reports` (from `code/`) from `meter.json`, which
`python3 code/main.py` writes next to the diagnostics; `--check` recomputes every total, average and cost
from the tokens and the prices.

## 1. What the model does

The solver is deterministic Python. A model is used for five jobs (DECISIONS D1, D2, D26):

| Use | Calls | Prompt |
|---|---|---|
| Intent: does the request text authorize deletion? (many languages) | requests are sent in batches, and each request has its own cache entry so a verdict never depends on its batch | `code/ghostaudit/llm/prompts/intent.v1.md` |
| Media facts: what do the 15 images and PDFs show? (records, keys, states) | one call per file | `code/ghostaudit/llm/prompts/media_extract.v2.md` |
| Router: which cases with a contested row or account need an investigation? | one call per batch of at most 25 cases (about 21 for the full dataset) | `code/ghostaudit/llm/prompts/router.v1.md` |
| Agent: which case does each contested target belong to? | at most 8 calls per unit (64 units for the full dataset), each a turn of a tool-use loop | `code/ghostaudit/llm/prompts/agent.v1.md` |
| Verifier: is each assignment of an INCOMPLETE answer supported? | one call per batch of at most 10 assignments | `code/ghostaudit/llm/prompts/verifier.v1.md` |

The router, agent and verifier use `claude-opus-5-5` and are bounded by `--agent-max-usd`. Their responses come
from two live runs (the first stopped at the default $5 cap after 28 of 64 units; the second, with
`--agent-max-usd 15`, finished the rest and replayed the first from the cache); the tables below are the
meter of a full `--llm cache` run that replays all of them, so every call is counted as `replayed`.

Requests carry no sampling parameters. Each sets a fixed `max_tokens`, an explicit effort level and a
JSON-schema output format, and the system prompt is marked for prompt caching. Output tokens include the
model's thinking. The model never emits a status or a step.

## 2. How the final run was made

The default run (`python3 code/main.py`, `--llm cache`) replays model responses stored in
`code/ghostaudit/cache/`; those responses were produced by live runs (`--llm live`, see the README) and
each stores the token usage the API reported. **The final full-dataset run therefore replays the committed
cache: it makes no live call and used 0 live tokens.** The usage of the original live run that filled the
cache is what the API reported for those calls; the meter counts it as `replayed`, so the `replayed` tables
below are the billed usage behind the shipped agent version and the amount a run from an empty cache would spend again.
Costs are estimates computed from those tokens and the listed prices, not an invoice. New live spend, if any
run made some, is the `live` bucket (a cache miss in `--llm live` mode).

The stored responses of the 15 media calls are redacted copies of the original model output: emails and
phones are kept only as sha256 digests, names are removed and the original text is not retained
(`"redacted_at_rest"` in each entry; DECISIONS D25). The token counts are those the API reported for the
original calls and are unchanged. The intent responses hold request texts only and are stored as received.

Averages divide by the 518 evaluation requests. The intent step also classifies the 32 public samples, whose
usage is included in the totals.

## 3. Usage and cost

Prices are USD per million tokens and live in `Config.prices` (`code/ghostaudit/config.py`): cache writes
cost 1.25 times the input price, cache reads use the published cache-read price (or the input price when
none is published), and the batch column is only an estimate: it applies the 50 % Message Batches discount to show what
the same tokens would cost through that API, which this solver does not call (it makes synchronous calls
only). A model without a price is reported as unpriced, never guessed.

<!-- BEGIN:usage -->
Provider: Anthropic Messages API, Python SDK `anthropic==2.3.0` for live calls. Models: claude-opus-5-5.

The final run (`--llm cache`, the default) replays model responses stored in `code/ghostaudit/cache/`. Replayed usage is the usage recorded when those responses were produced, so it is what a run from an empty cache spends again. Live usage is what the final run itself spent on the API: it is zero while every response is cached. The stored media replies are redacted copies of the original model output (emails and phones as sha256 digests, names removed, original text not retained; DECISIONS D25); the token counts are those of the original calls.

- The final run made 0 live API call(s) and used 0 live tokens ($0.0000).
- The live run that filled the cache billed 398 calls and 4744213 tokens (259274 input, 1043623 cache write, 3103304 cache read, 338012 output), $13.6361 at synchronous prices or $6.8181 at batch prices; that is 9158.7 tokens and $0.026325 per request over 518 requests.

### Model usage behind the final output.csv (replayed from the response cache)

| Model | Calls | Input tokens | Cache write | Cache read | Output tokens | Total tokens | Cost (sync) | Cost (batch) |
|---|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 398 | 259274 | 1043623 | 3103304 | 338012 | 4744213 | $13.6361 | $6.8181 |
| **overall** | 398 | 259274 | 1043623 | 3103304 | 338012 | 4744213 | $13.6361 | $6.8181 |

### New API spend of the final run (live calls)

| Model | Calls | Input tokens | Cache write | Cache read | Output tokens | Total tokens | Cost (sync) | Cost (batch) |
|---|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | $0.0000 |
| **overall** | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | $0.0000 |

### Per request

| Basis | Requests | Tokens per request | Cost per request (sync) |
|---|---|---|---|
| replayed | 518 | 9158.7 | $0.026325 |
| live | 518 | 0.0 | $0.000000 |
<!-- END -->

## 4. Operational notes

- The provider is Anthropic; live calls go through the official Python SDK, pinned in `requirements.txt`
  and needing Python 3.10 or newer. The offline modes (`--llm off`, `--llm cache`) need only the standard
  library.
- `--llm off` skips every call: intent falls back to the keyword lexicon and the images and PDFs yield no
  observation, which the diagnostics list. The strategy table in `evaluation_report.md` shows the effect on
  accuracy and the cold-run cost of each choice.
- The API key is read only from the environment (or a git-ignored `.env`) and appears nowhere in the
  cache, the meter, the logs or the reports.
