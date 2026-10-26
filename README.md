# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists: a deletion-audit solver

A deletion workflow may report **Complete** while a person's data still sits in databases, replicas, logs,
support attachments, exports, search indexes, archives or backups, and sync and restore processes can
bring deleted data back. This solver audits every request in `dataset/deletion_requests.csv`:

1. Does the request text actually authorize deletion? If not, the case is `NOT_APPLICABLE` with `[]` steps.
2. Which identifiers (current and historical) belong to the person, and which records carry them at the
   case's `audit_at`? Reported statuses and activity results are treated as claims, never as proof.
3. Applying `deletion_rules.csv`: is every copy treated as policy requires, is every required record
   retained, and can no sync or restore path recreate prohibited data? The answer is `COMPLETE` or
   `INCOMPLETE`.
4. For an incomplete case: the remaining records and recreation risks, an ordered remediation plan, and
   the checks that must pass afterwards. For a complete case: the evidence-backed verification checks.

The challenge contract (`problem_statement.md` and `AGENTS.md` in the challenge repository) is not part of `code.zip`;
the rules this solver implements are restated in [`code/docs/SPEC.md`](./code/docs/SPEC.md).

---

## Quick start

Python 3.9 or newer and the standard library are enough; there is nothing to install. Run everything from the
repository root, with the `dataset/` directory in place.

<!-- clean-room:commands -->

```bash
python3 code/main.py
```

1. `python3 code/main.py` writes `output.csv` (518 rows, sorted by `case_id`) at the repository root and
   `diagnostics/`. `code/main.py` is a three-line shim over `ghostaudit.cli`; the same command is installed
   as `ghostaudit` by `pip install -e code`.
2. The quality gate and the scorer run from `code/` (or as `ghostaudit-eval` after the install):

```bash
cd code
python3 -m evaluation check     # format, contract, byte-identical reruns, invariants, sample score; exit 0 if all pass
python3 -m evaluation score     # fresh run on the 32 public samples, scored against the public gold
python3 -m evaluation verify    # label-free verification of the 518 rows
python3 -m evaluation custom    # the seven extra evaluation cases
```

3. The unit tests run with:

```bash
python3 -m unittest discover -s code/tests -t code
```

Nothing under `code/` edits `sys.path`: `python3 code/main.py` finds the package because the script's
directory is on the path, `python3 -m evaluation` runs from `code/`, and the editable install
(`python3 -m venv .venv && .venv/bin/pip install -e code`) provides the `ghostaudit` and `ghostaudit-eval`
commands.

The default run replays model responses stored in `code/ghostaudit/cache/`, so it needs no API key and no
network, takes about a second, and is byte-identical across runs, hash seeds and time zones. It writes:

| Path | Contents |
| --- | --- |
| `output.csv` | one row per evaluation request: `case_id,deletion_status,steps_json`, sorted by `case_id` |
| `diagnostics/diagnostics.md` | per case: intent, link basis, flags fired, evidence and template disagreements, unread media, the agent stage (routes, units, fallbacks by reason), stage timings |
| `diagnostics/meter.json` | model usage of the run (read by `code/tools/render_reports.py`) |

Options of `code/main.py` (`--help` lists all):

| Option | Meaning |
| --- | --- |
| `--llm off` | no model: the keyword lexicon decides intent, images and PDFs yield no observation and the agent is off |
| `--llm cache` | replay stored model responses (default) |
| `--llm live` | call the Anthropic API for anything not cached (Python 3.10+, see "Live LLM mode") |
| `--agent on`, `--agent off` | the router, tool-calling agent and verifier resolve contested links (default `on`; needs `--llm cache` or `live`), or the deterministic fallback decides everything |
| `--agent-max-usd USD` | cap on the live spend of the agent stage; past it units fall back (default 5) |
| `--agent-model ID`, `--router-model ID`, `--verifier-model ID` | models of the three agent roles (default `claude-opus-5-5` each) |
| `--out PATH`, `--diag DIR` | where `output.csv` and the diagnostics go (defaults: `./output.csv`, `./diagnostics`) |
| `--dataset DIR` | dataset directory (default `./dataset`) |
| `--include-samples`, `--samples-out PATH` | also write predictions for the 32 public samples |
| `--flags name=off,...` | switch an inference flag: `verify_legal_holds`, `allow_pre_request_findings`, `fifo_pairing`, `never_mix` |
| `--intent-model ID`, `--media-model ID` | models used by `--llm live` (defaults: `claude-opus-5-5` for both; `--intent-model claude-haiku-5-5` is the cheaper strategy S2) |

A missing cache entry or a disabled model never stops a run: the deterministic fallback applies and the
diagnostics list what was skipped.

## How it works

The decisions are plain, testable Python over parsed evidence. A language model has five narrow jobs and never
emits a status or a step: the request text in many languages (does it authorize deletion?), the 15 images and
PDFs (what do these business artifacts show?), and, for the worker rows and account rows that more than one
case could own, a router that picks the cases worth an investigation, a bounded tool-calling agent that
decides each contested target from evidence, and a verifier that re-checks the agent's answers. Every output
is schema-checked and cached, and enters the deterministic core as an intent decision, media facts or a link
decision. The cutoff (`audit_at`), the policy mapping and the citation ledger are enforced inside the tools and
the submit gate, so the model cannot override them; when the agent hits a cap, a timeout, an error, a cache miss
or answers UNSURE, the unit falls back to the deterministic resolution and the diagnostics count the reason.

```text
dataset -> identity index ---------------------------------------------+
        -> activity classifier ----------------------------------------+-> candidates (process order,
        -> evidence parsers (sql, json, txt, log) + media facts (LLM) ---+   evidence owners) -> fixed point
        -> intent (LLM, lexicon fallback) -> not a deletion: NOT_APPLICABLE        |
                                                                  contested rows and accounts
                                            router (LLM) -> agent loop (LLM + tools) -> verifier (LLM)
                                                                       | falls back to FIFO pairing on any cap
        state at audit_at + policy treatment + citation -> ordered steps -> contract validation -> output.csv
```

| Document | What it holds |
| --- | --- |
| [`code/docs/SPEC.md`](./code/docs/SPEC.md) | the rules the code implements (identity, evidence, time, policy, linking, emission) |
| [`code/docs/ARCHITECTURE.md`](./code/docs/ARCHITECTURE.md) | pipeline diagram, module layering, where the model sits, performance, determinism |
| [`code/docs/DECISIONS.md`](./code/docs/DECISIONS.md) | the non-obvious choices with alternatives and evidence, and the rule provenance ledger |
| [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md) | accuracy, strategies, ablations, extra evaluation cases, failures and improvements |
| [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md) | model providers, calls, tokens and cost of the final run |

The prompts are in `code/ghostaudit/llm/prompts/`: `intent.v1.md`, `media_extract.v2.md`, `router.v1.md`, `agent.v1.md` and `verifier.v1.md`.

## Results

The 518 evaluation rows are unlabeled; the scores below are on the 32 public samples, whose answers the
solver never reads while it runs. They are a development set, not a held-out one. The link rules follow the
order of the process and evidence ownership only (no fitted window, latency signature or id convention, and no
evidence after `audit_at`), so contested links are decided by the agent where its responses are cached and by
the deterministic fallback everywhere else. Two live runs filled the cache for every unit; with the agent on the
samples score 32 of 32 status, 8 of 32 row-exact and step F1 0.8958. Before this change the same samples scored 32
of 32 status, 30 of 32 row-exact and step F1 0.9948 with fitted windows and a learned signature; with the
agent off they now score 31 of 32, 6 of 32 and 0.8471, and 264 evaluation rows differ from the earlier
`output.csv` (none by status). DECISIONS D27 and D10 give the measured cause and the effect of the fallback
pairing. The unit-test count is the number of tests unittest discovers.

<!-- BEGIN:results -->
| Measure | Value |
|---|---|
| Sample status accuracy, G1 (32 cases) | 1.0000 |
| Sample step F1, G3 | 0.8958 |
| Sample sequence LCS ratio, G6 | 0.8515 |
| Sample exact sequence order | 0.9062 |
| Final run: requests | 518 |
| Final run: model tokens behind the output (replayed) | 4744213 |
| Final run: cost of those tokens, sync | $13.6361 |
| Final run: new API spend (live) | $0.0000 |
<!-- END -->

<!-- BEGIN:tests -->
Unit tests: 1020 (`python3 -m unittest discover -s code/tests -t code`).
<!-- END -->

`python3 -m evaluation verify` (from `code/`) re-reads the participant files with independent parsers and checks
the 518 rows without labels (citation windows, resource ids, step pairing, audit-record parity).

## Limitations and disclosures

- **Contested links are the weak point.** With process-order candidates alone, 784 evaluation worker rows are
  shared by several cases after the fixed point and 401 evaluation cases carry a fallback link. The fallback
  pairs ascending account ids with ascending case ids and a tied row with the report nearest in process order.
  It is arbitrary where evidence is silent, and on the public samples it scores worse than no pairing
  (`--flags fifo_pairing=off`: 32 of 32 status, 8 of 32 exact, F1 0.8937; D10). The agent is meant to make it rare;
  until its responses are cached it is the whole story.
- **Time is causal everywhere.** No state, status, finding, link, owner or id comes from evidence captured
  after the case's `audit_at`. An audit-record id found only in a later file is therefore not emitted, which
  costs the public samples that carried one (D29).
- **No id is derived.** The `account_00N` convention is gone; a case with no account source has no account step.
- **The agent recovers only part of the accuracy.** Two live Opus 5.5 runs filled the cache: the agent decided
  63 of 64 units (one UNSURE fell back), the verifier rejected 9 of 636 assignments, and the agent changed 73
  evaluation rows. On the samples it lifts row-exact from 6/32 to 8/32 and step F1 from 0.8471 to 0.8958,
  well short of the removed fitted rules (30/32). Scripted-transcript tests cover its caps and fallbacks.
- **Some COMPLETE rows have no account verification step** when no file inside the case window proves the account
  absent (12 of 153 at the time of writing; the label-free report lists them; D21, D22).
- **The response cache holds redacted copies of the media replies.** The model transcribed emails, phones
  and names from the 15 images and PDFs. The stored replies keep an email or phone only as
  `sha256:<hex>` (of the lower-cased email, or of the phone's digits) and drop the names, which are never
  matching keys; each such entry has the top-level field `"redacted_at_rest"`. The original model text is not
  retained, so the cached text is not the raw model output. The evidence mapping matches the digests against
  the identity's hash keys (DECISIONS D25). A live write is redacted the same way before it is stored.
  `python3 -m tools.redact_cache --check` (from `code/`) verifies the shipped entries and `build_zip` fails
  when a cache file holds a dataset email or phone. The intent entries hold request texts only, with no email.
- **An activity row that matches no known template** is classified `UNCLASSIFIED`: inert, never used for a
  decision, warned about once per template shape and counted in `diagnostics.md` (0 on the shipped data).
- **No accuracy ceiling is shipped.** The evaluation rows are unlabeled, so the scorer's ceiling column is 1.000.
- **One audit screenshot lists six signed events** for one subject; the solver emits the single one tied by a
  catalog row (D18).
- Rules that no public sample exercises (never-mix, legal holds) are inferred; the ledger in `DECISIONS.md` lists
  each with the number of evaluation rows it moves.
- The 518 evaluation rows are unlabeled: their quality rests on the sample scores, the label-free checks and
  the ledger, not on a measured accuracy.

---

## Live LLM mode (optional)

The solver runs offline on the system Python (3.9+, standard library only) with `--llm off` or `--llm cache`. `--llm live` calls the Anthropic API through the official SDK, which needs Python 3.10 or newer. Set up a separate Python 3.12 environment with [uv](https://docs.astral.sh/uv/) from the repository root (`python3 -m uv` works even when the user scripts directory is not on `PATH`):

```bash
python3 -m pip install --user uv
python3 -m uv python install 3.12
python3 -m uv venv .venv-live --python 3.12
python3 -m uv pip install --python .venv-live/bin/python -r requirements.txt
```

`requirements.txt` pins `anthropic==2.3.0; python_version >= "3.10"`. On Windows use `.venv-live\Scripts\python.exe`. Provide the key through the environment, or put `ANTHROPIC_API_KEY=...` in a repo-root `.env` file (see `.env.example`); `.env` is git-ignored, never packaged, and read only for variables the environment does not already set:

```bash
export ANTHROPIC_API_KEY=...
.venv-live/bin/python code/main.py --llm live          # fills the intent, media, router, agent and verifier caches
```

Run the tests under both interpreters; the live smoke test is skipped without a key:

```bash
python3 -m unittest discover -s code/tests -t code
.venv-live/bin/python -m unittest discover -s code/tests -t code
```

The check that a cached run gives byte-identical `output.csv` on the system Python and on `.venv-live` runs the full pipeline twice, so it is opt-in. Run it from the system interpreter:

```bash
GHOSTAUDIT_CROSS_INTERPRETER=1 python3 -m unittest discover -s code/tests -t code -p test_live_toolchain.py -k CrossInterpreter -v
```

The live smoke call (one structured-output request, no sampling parameters) runs only from `.venv-live` with a key (from the environment or `.env`):

```bash
ANTHROPIC_API_KEY=... .venv-live/bin/python -m unittest discover -s code/tests -t code -p test_live_toolchain.py -k LiveSmoke -v
```

---

## Reports and packaging

The two reports under `code/evaluation/` are filled from measured output, not typed (a copy of each also goes
to `evaluation/` in the archive). Run from `code/`:

```bash
cd code
mkdir -p /tmp/metrics
python3 main.py --out /tmp/metrics/output.csv --diag /tmp/metrics/diag
cp /tmp/metrics/diag/meter.json /tmp/metrics/meter.json
python3 -m evaluation score --json > /tmp/metrics/scorer.json
python3 -m evaluation score --strategies > /tmp/metrics/strategies.md
python3 -m evaluation score --ablate --agent-ablation > /tmp/metrics/ablation.md
python3 -m evaluation custom --json /tmp/metrics/custom_cases.json
python3 -m tools.render_reports --metrics-dir /tmp/metrics           # fill the marked blocks
python3 -m tools.render_reports --metrics-dir /tmp/metrics --check   # exit 1 on any drift
```

Build `code.zip` (reproducible, no `dataset/`, no secrets, no release tooling) and check it. With `--metrics-dir`
the build also runs the `--check` above and fails when a report table is stale:

```bash
cd code
python3 -m tools.build_zip --root .. --out ../code.zip --dataset ../dataset --metrics-dir /tmp/metrics
```

In the full repository, `devtools/` (release-process tooling: audit sampler, confidence tiers, clean-room
matrix, release gate, log tools) sits beside `code/`. It is not part of `code.zip`, so nothing in the archive
depends on it; everything quoted in the reports can be regenerated with the commands above.

Before submitting, confirm that:

- `output.csv` has the exact header `case_id,deletion_status,steps_json` and contains all 518 data rows sorted by `case_id`
  (`python3 -m evaluation check` verifies this and more);
- every `steps_json` value is a valid JSON array with consecutive step numbers starting at `1`;
- findings cite valid evidence IDs, and `COMPLETE` verification steps cite evidence proving the current state;
- proposed remediation and future verification steps use an empty `evidence_id` (`""`);
- `code.zip` includes the runnable code, this `README.md`, `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md`;
- `log.txt` follows the `AGENTS.md` turn format and is uploaded as the `chat_transcript`; and
- no API keys, credentials, real personal data or sensitive configuration values are included.
