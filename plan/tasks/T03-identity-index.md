# T03 — IdentityIndex (current + historical identifiers)

| Field | Value |
|---|---|
| ID | T03 |
| Milestone | M1 |
| Depends on | T02, T02b |
| Size | S |
| SPEC refs | I1–I4 |

## Files
- `code/ghostaudit/identity.py`
- `code/tests/test_identity.py`

## Description
Resolve request emails to subjects and give every subject the full set of match keys, built from `keys.py`.

## Implementation notes
- Email chains: repeat over `field_name=email` old/new values until nothing changes (user_35 has three emails).
- Hashes: `sha256(lower(email))` for every email, plus the `email_hash` audit values. Phones: the current phone plus `field_name=phone` old/new values.
- `resolve(email)`: an exact lookup through `keys.email_key`. If two users share any key, raise `DatasetError` (expected count: 0).
- `users_for(keys)`: reverse index; returns a sorted tuple.

## Acceptance criteria
- [ ] All 550 request emails resolve: eval 418 current, 100 historical, 20 uppercase.
- [ ] user_35 resolves from `abena.o189491@zoho.com`.
- [ ] `sha256('minjun.kim90@gmail.com')` maps to the subject of sample case_12.
- [ ] Decoys resolve to `None`: `smartinez6461.jr@gmail.com`, `g.silva76.jr@gmail.com`, `nadia.popescu@yahoo.com`.
- [ ] Parity: `keys_for(u)` equals `keys_from_record` applied to the same raw values.

## Tests
- Table-driven tests.
- Name-collision test: the two Mateo Ríos users stay distinct.

## Risks
- Phone formats vary. Use the digits form only, with at least 8 digits.

## Definition of Done
See `README.md` § Definition of Done.
