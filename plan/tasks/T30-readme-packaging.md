# T30 — README, packaging check and dual report placement

| Field | Value |
|---|---|
| ID | T30 |
| Milestone | M6 |
| Depends on | T28, T29, T30b, T31, T33 |
| Size | S |
| SPEC refs | §6.7, §6.9, README packaging, SCORING_STRATEGY C2/C5/C9 |

## Files
- `README.md`
- `.gitignore`
- `.env.example`
- `requirements.txt`
- `code/package_check.py`

## Description
Make the submission reproducible, judge-friendly and safe to package.

## Implementation notes
- README sections:
  - **3-command quickstart**: `python3 code/main.py`, `python3 code/evaluation/main.py`, `python3 -m unittest discover -s code/tests -t code`;
  - setup split: core needs Python ≥ 3.9 and the stdlib; `--llm live` needs Python ≥ 3.10 plus `pip install -r requirements.txt` and `ANTHROPIC_API_KEY`;
  - a Mermaid pipeline diagram plus an ASCII fallback;
  - a **results table**: sample status accuracy, step F1, sequence, runtime, cost;
  - an **encouraged-capability map** (where each is implemented): retrieval → EvidenceIndex; multimodal → media_extract/map_facts; identity reconstruction → IdentityIndex; deletion-state reconstruction → StateResolver; remediation planning → emit ordering; deterministic verification → contract.py; batching, caching and token efficiency → llm/;
  - safety: no secrets, prompt-injection delimiters;
  - limitations; the learned-signature disclosure;
  - links to `code/docs/` and both reports; test count and runtime.
- `.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `diagnostics/`. Ship `.env.example`.
- `package_check.py` delegates zip building to the reproducible packager (T33). It:
  - copies `code/evaluation/{evaluation_report,usage_report}.md` to zip-root `evaluation/` and asserts both copies are byte-identical;
  - builds the zip with `zip -r code.zip README.md code evaluation -x ...`;
  - **presence**: README.md, code/main.py, both reports in both places (non-empty, with the AGENTS §6.8 headings), `code/docs/*.md`, `code/ghostaudit/llm/prompts/*.md`, ≥ 1 `code/ghostaudit/cache/*.json`;
  - **absence**: `dataset/`, `solution/`, `plan/`, nested archives, `.env`, `__pycache__`, `.venv`, key patterns;
  - runs `code/tools/check_log.py log.txt`, which must exit 0.

## Acceptance criteria
- [ ] A clean checkout runs with the 3 README commands on Python 3.9. The package check passes.

## Tests
- Run the package check.

## Risks
- A missing cache degrades reviewers' runs. The presence check prevents it.

## Definition of Done
See `README.md` § Definition of Done.
