# T01 — Package skeleton, Config, core model types (Python 3.9+)

| Field | Value |
|---|---|
| ID | T01 |
| Milestone | M0 |
| Depends on | — |
| Size | S |
| SPEC refs | §3.1, §8.4, N1, N4, N5 |

## Files
- `code/ghostaudit/__init__.py`
- `code/ghostaudit/config.py`
- `code/ghostaudit/model.py`
- `code/tests/__init__.py`
- `code/evaluation/__init__.py`
- `code/tests/test_model.py`

## Description
Create the `ghostaudit` package, the immutable domain vocabulary and the configuration that every later task depends on. The code must run on the system `python3` 3.9.6.

## Implementation notes
- **Python 3.9 idioms:**
  - `from __future__ import annotations` in every module;
  - `@dataclass(frozen=True)` without `slots`;
  - `typing.Optional`/`Tuple` wherever an annotation is evaluated at runtime;
  - no `match` statements, no `zip(strict=)`.
- `model.py`:
  - enums `Phase`, `Treatment`, `ObsState`, `ActKind`;
  - frozen dataclasses `Request`, `ManifestEntry`, `Observation`, `ScopeAssertion`, `MediaFacts`, `ClassifiedActivity`, `LinkedResource`, `CaseLinks`, `ResourceVerdict`, `Step`, `CaseResult` (IMPLEMENTATION_PLAN §2.2).
- `OPERATION_TABLE`: AGENTS §6.4 as `{phase: ((operation, state), ...)}` in table order. Expose `op_index(phase, op)` and `state_of(op)`. `TREATMENT_OPS` maps Treatment → (finding_op | None, remediation_op | None, verify_op).
- `config.py`:
  - frozen `Config`: dataset_dir, out_path, llm_mode, diag_dir, model ids, price table, intent batch size 25, max_workers 8, timeout 60 s, retries 3, and window constants with derivation comments: account [−1.3 h, −0.7 h]; P [−30 min, −2 min]; V/CF/CR [+30 min, +135 min]; `window_offset_s=0`;
  - frozen `Flags`: signature=True (learned link signature, SPEC L7), verify_legal_holds=True, handcrafted_account_convention=True, allow_pre_request_findings=False, fifo_pairing=True, never_mix=True, use_late_audit_ids=True;
  - `Secret` wrapper whose `__repr__`/`__str__` return `***`. The API key field is `field(repr=False, compare=False)`;
  - `Config.from_env()` is the only reader of `os.environ`.
- Resolve the repo root via `Path(__file__).resolve().parents[2]`, never the CWD.
- Create empty `__init__.py` files in `code/tests/` and `code/evaluation/`. The test command is `python3 -m unittest discover -s code/tests -t code`.
- Add `code/pyproject.toml` with `requires-python = ">=3.9"` and a ruff config, which is optional tooling. Every module starts with a docstring that cites its SPEC ids.

## Acceptance criteria
- [ ] The phase tuples match AGENTS §6.4 exactly: 4 finding, 5 remediation and 6 verification operations, each with its state.
- [ ] All dataclasses are frozen.
- [ ] `repr(Config.from_env())` never contains the key value.
- [ ] `python3 --version` is 3.9.x on this machine, and `python3 -c 'import sys; sys.path.insert(0,"code"); import ghostaudit'` succeeds.
- [ ] The test command above discovers and runs `test_model.py`.

## Tests
- `test_model.py`:
  - op table counts and order;
  - `op_index` and `state_of` for all 15 operations;
  - frozen-ness;
  - `Secret` repr;
  - Flags defaults.

## Risks
- Operation or state spelling errors break everything downstream, so test against the literal AGENTS table.

## Definition of Done
See `README.md` § Definition of Done.
