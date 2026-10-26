# T02b — Key normalizer (`keys.py`) and evidence parser base

| Field | Value |
|---|---|
| ID | T02b |
| Milestone | M0 |
| Depends on | T01 |
| Size | S |
| SPEC refs | I1–I4, §3.1 |

## Files
- `code/ghostaudit/keys.py`
- `code/ghostaudit/evidence/__init__.py`
- `code/ghostaudit/evidence/base.py`
- `code/tests/test_keys.py`

## Description
Provide the single identifier normalizer and the parser protocol, so all evidence parsers can be built in parallel and always agree with IdentityIndex.

## Implementation notes
- `keys.py` (pure):
  - `email_key(v) -> 'e:'+v.strip().lower()`;
  - `hash_key(v) -> 'h:'+v.lower()`, only for 64-hex values;
  - `phone_key(v) -> 'p:'+digits`, only when there are ≥ 8 digits;
  - `user_key(v) -> 'u:user_N'`;
  - `keys_from_record(fields: Mapping) -> frozenset[str]`: classifies each value by shape and extracts emails from free text (e.g. `message_text`) with a precompiled regex;
  - names are never keys.
- `evidence/base.py`:
  - `EvidenceParser` Protocol (`name`, `detect(entry, head: bytes) -> bool`, `parse(entry, data: bytes) -> ParseOutput`);
  - `ParseOutput(observations, scopes, notes)`;
  - `REGISTRY` tuple;
  - `select_parser(entry, head)`: exactly one parser must claim each file, otherwise `ParseError`.

## Acceptance criteria
- [ ] The same raw value always gives the same key, whichever function produced it.
- [ ] `'+81 90 6156 0005'` gives `p:819061560005`.
- [ ] `'SIPHO.MOKOENA@GMAIL.COM'` gives `e:sipho.mokoena@gmail.com`.
- [ ] `'0000…'` integrity-seal strings that are not email hashes are **not** treated as hashes when prefixed by `sha256:`.
- [ ] `select_parser` raises when zero or two parsers claim a file.

## Tests
- Table-driven key tests.
- Registry ambiguity tests with dummy parsers.

## Risks
- Divergent normalization silently breaks L1 linking. A parity test against IdentityIndex is added in T03.

## Definition of Done
See `README.md` § Definition of Done.
