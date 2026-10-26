# T36 — Live LLM toolchain (uv Python 3.12 + pinned SDK)

| Field | Value |
|---|---|
| ID | T36 |
| Milestone | M2 |
| Depends on | T10 |
| Size | S |
| SPEC refs | SPEC N5; LOCAL_EVALUATION_STRATEGY G1 |

## Files
- `requirements.txt`
- `README.md (live section)`

## Description
Make `--llm live` runnable on this machine, which has only Python 3.9.6 while `anthropic` 2.x needs ≥ 3.10. **Scheduled in P1**, before the cache fill.

## Implementation notes
- Toolchain: `python3 -m pip install --user uv` (the wheel supports 3.8+), then `uv python install 3.12`, then `uv venv .venv-live --python 3.12`, then `uv pip install -r requirements.txt`. `.venv-live` goes in `.gitignore`.
- Pin exactly: `anthropic==2.3.0; python_version >= "3.10"`, verified on PyPI. Record the version in usage_report.md.
- Determinism: the same cached run on 3.9 and 3.12 gives byte-identical output (`fromisoformat` differences are handled by `timeutil`).
- Per the claude-api skill, use the SDK, not a hand-written HTTP client.

## Acceptance criteria
- [ ] A live smoke call succeeds from `.venv-live` with structured output and no sampling params.
- [ ] The 3.9 and 3.12 cached outputs are identical.

## Tests
- Smoke test, skipped without a key.

## Risks
- The network or PyPI may be unavailable. Install early, in P1.

## Definition of Done
See `README.md` § Definition of Done.
