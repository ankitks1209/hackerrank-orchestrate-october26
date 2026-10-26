# T31 — Transcript tooling: append_log.py and check_log.py

| Field | Value |
|---|---|
| ID | T31 |
| Milestone | M0 |
| Depends on | — |
| Size | S |
| SPEC refs | AGENTS §2, §5; SCORING_STRATEGY X1–X6 |

## Files
- `code/tools/__init__.py`
- `code/tools/append_log.py`
- `code/tools/check_log.py`
- `code/tests/test_check_log.py`

## Description
Make every log.txt entry well-formed, append-only and verified, so the Chat Transcript score is not lost on format.

## Implementation notes
- `append_log.py --kind {session,turn} --title ... --prompt-file F --summary ... --action ... [--action ...] --tool T --model M [--parent-agent P] [--branch B]`.
  - `--tool` and `--model` are required with no defaults, so nothing is guessed.
  - The UTC ISO timestamp comes from `datetime.now(timezone.utc)`.
  - The file is opened with `O_APPEND` and locked with `fcntl.flock` where available, so parallel sub-agents never interleave.
  - After writing, it re-reads the new entry and lints it (the §5.2 re-read requirement).
- `check_log.py log.txt [--trace session.jsonl] [--baseline-ref REF]`.
  - **Errors:**
    - the first entry is SESSION START with all 8 keys exactly once;
    - turn sections in order, with a non-empty prompt;
    - Actions written as `* ` bullets;
    - all 6 Context keys exactly once;
    - `tool=` on an allowlist, and `model=` matching an id regex (blank, unknown, generic or placeholder values rejected);
    - ISO timestamps with timezone that never go backwards;
    - titles of 80 characters or fewer;
    - no CR characters;
    - secret patterns (`sk-ant-`, `sk-`, `AKIA`, `PRIVATE KEY`, bearer tokens, `api_key=`).
  - **Warnings:** a summary that isn't 2–5 sentences; email-like strings.
  - `--trace` lists user prompts from the session JSONL that are missing from the log. It skips slash commands, `!` shell lines and notifications, and collapses `/rewind` resends.
  - `--baseline-ref` asserts that the committed log.txt is a prefix of the current one, proving append-only.
- Port the tested prototype linter logic (about 150 lines, Python 3.9). Tests use string fixtures only.

## Acceptance criteria
- [ ] `check_log.py log.txt` exits 0 on the current log.
- [ ] Every error class has a negative fixture that triggers it.
- [ ] append_log.py output always passes check_log.

## Tests
- `test_check_log.py`.

## Risks
- Hand-editing log.txt breaks the append-only property. The convention is append_log.py only; never use sed or Write on log.txt.

## Definition of Done
See `README.md` § Definition of Done.
