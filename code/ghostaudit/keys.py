"""The single identifier normalizer shared by IdentityIndex and every parser.

Implements SPEC I1 (exact lower-cased email matching, no fuzzy or name
matching), I2 (key forms e:/h:/p:/u:) and the 3.1 subject_keys vocabulary.
Names are never keys. Ported from the ident_keys classifier of the analysis
prototype records_normalize, minus its name keys and with a stricter phone shape.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, FrozenSet, Optional, Set

EMAIL_PREFIX = "e:"
HASH_PREFIX = "h:"
PHONE_PREFIX = "p:"
PHONE_HASH_PREFIX = "hp:"  # sha256 of a phone's digits, the key of a phone that was redacted at rest
USER_PREFIX = "u:"
REDACTED_PREFIX = "sha256:"  # an email or phone stored only as its digest (see llm.media_extract.redact_reply)

MIN_PHONE_DIGITS = 8  # shorter digit runs are not phones (dataset phones have >= 11 digits)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_USER_RE = re.compile(r"user_\d+")
# Every phone in identities, audit log and evidence starts with "+"; requiring
# it keeps dates such as 2026-05-28 from being read as phone numbers.
_PHONE_SHAPE_RE = re.compile(r"\+[\d ()\-]+")
_NON_DIGIT_RE = re.compile(r"\D")
_REDACTED_RE = re.compile(REDACTED_PREFIX + r"([0-9a-f]{64})")


def email_key(value: str) -> str:
    """Key for an email address: strip, lower-case, exact (SPEC I1)."""
    return EMAIL_PREFIX + value.strip().lower()


def hash_key(value: str) -> Optional[str]:
    """Key for a bare 64-hex digest; None for anything else, e.g. `sha256:`-prefixed seals."""
    text = value.strip().lower()
    return HASH_PREFIX + text if _HASH_RE.fullmatch(text) else None


def phone_key(value: str) -> Optional[str]:
    """Key from the digits of a phone number; None below MIN_PHONE_DIGITS digits."""
    digits = _NON_DIGIT_RE.sub("", value)
    return PHONE_PREFIX + digits if len(digits) >= MIN_PHONE_DIGITS else None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def email_digest(value: str) -> str:
    """sha256 of an email address, stripped and lower-cased like `email_key`."""
    return _sha256(value.strip().lower())


def _phone_digits(value: str) -> str:
    return _NON_DIGIT_RE.sub("", value)


def phone_hash_key(value: str) -> Optional[str]:
    """Key from the sha256 of a phone's digits; None below MIN_PHONE_DIGITS digits."""
    digits = _phone_digits(value)
    return PHONE_HASH_PREFIX + _sha256(digits) if len(digits) >= MIN_PHONE_DIGITS else None


def redacted_email(value: str) -> Optional[str]:
    """`sha256:` form of the first email address in `value`; an existing digest form is kept.

    None when the text holds neither, so a caller drops the entry.
    """
    text = value.strip()
    if _REDACTED_RE.fullmatch(text):
        return text
    match = _EMAIL_RE.search(text)
    return REDACTED_PREFIX + email_digest(match.group(0)) if match else None


def redacted_phone(value: str) -> Optional[str]:
    """`sha256:` form of a phone (same shape rule as `_keys_from_text`); an existing digest form is kept."""
    text = value.strip()
    if _REDACTED_RE.fullmatch(text):
        return text
    if _PHONE_SHAPE_RE.fullmatch(text) and len(_phone_digits(text)) >= MIN_PHONE_DIGITS:
        return REDACTED_PREFIX + _sha256(_phone_digits(text))
    return None


def redacted_email_key(value: str) -> Optional[str]:
    """Key of an email stored as `sha256:<hex>`; equals the identity's `h:` key of that address."""
    match = _REDACTED_RE.fullmatch(value.strip())
    return HASH_PREFIX + match.group(1) if match else None


def redacted_phone_key(value: str) -> Optional[str]:
    """Key of a phone stored as `sha256:<hex>`; equals the identity's `hp:` key of that number."""
    match = _REDACTED_RE.fullmatch(value.strip())
    return PHONE_HASH_PREFIX + match.group(1) if match else None


def user_key(value: str) -> Optional[str]:
    """Key for a stable user reference such as `user_N`; None for other text."""
    text = value.strip()
    return USER_PREFIX + text if _USER_RE.fullmatch(text) else None


def _keys_from_text(value: str) -> Set[str]:
    """Classify one string by shape; free text yields every email token it contains."""
    text = value.strip()
    found = {email_key(match) for match in _EMAIL_RE.findall(text)}
    if "@" in text:
        return found
    for key in (user_key(text), hash_key(text)):
        if key:
            found.add(key)
    if _PHONE_SHAPE_RE.fullmatch(text):
        phone = phone_key(text)
        if phone:
            found.add(phone)
    return found


def keys_from_record(fields: Any) -> FrozenSet[str]:
    """All subject keys in a record's values; nested mappings and lists are walked.

    Field names are ignored: a value is classified by its shape alone.
    """
    found: Set[str] = set()
    pending = [fields]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            found |= _keys_from_text(item)
        elif hasattr(item, "values"):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return frozenset(found)
