"""Map extracted media facts onto resources, deterministically (SPEC F10, Q1, Q7).

Pure mapping: it receives the validated `MediaFacts` of one image or PDF and never
imports the LLM layer. A record becomes an Observation by one of two paths:

  (a) LINK join: a LINK activity row whose alias or resource_id equals the record's
      `display_id` or `resource_hint`. System, resource, user and email come from the
      LINK row, which wins over what the screen shows (SPEC Q7).
  (b) Literal id plus identifier: `resource_hint` or `display_id` is a resource id with
      a known prefix, and the record names at least one email, phone or user_N key. In a
      file where some record joins a LINK row, a bare user_N key is not enough: the screen
      repeats its subject filter on every row, so only a LINK row (or a shown email or
      phone) ties a record to that subject.

Timing is never used to join. `entry_time` is the manifest `captured_at`. A record that
validates on neither path, or shows no state, yields no Observation, only a note; a
display-only reference such as a support id on an account screen is such a note (SPEC Q1).

Extraction contract for `state_facts` (the prompt of the extraction layer must follow it):
a mapping of fact name to boolean, each fact a literal reading of the screen:
  restore_blocked           the archive shows a restore block
  connector_enabled         the data flow or connector is enabled
  pii_fields_shown          a support message or analytics profile shows direct identifiers
  only_stable_reference_shown  only the stable user reference is shown, no direct identifier
  record_shown              the record itself is shown
"""
from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple

from ghostaudit.evidence.base import ParseOutput
from ghostaudit.keys import (
    HASH_PREFIX,
    USER_PREFIX,
    email_digest,
    email_key,
    keys_from_record,
    redacted_email_key,
    redacted_phone_key,
    user_key,
)
from ghostaudit.model import (
    ActKind,
    ClassifiedActivity,
    ManifestEntry,
    MediaFacts,
    ObsState,
    Observation,
)
from ghostaudit.policy import system_for

# (fact, value, state), first match wins: the specific states precede `record_shown`.
# Restore and connector facts mirror SPEC F9 (restore_allowed / enabled -> ACTIVE).
STATE_RULES: Tuple[Tuple[str, bool, ObsState], ...] = (
    ("restore_blocked", False, ObsState.ACTIVE),
    ("restore_blocked", True, ObsState.BLOCKED),
    ("connector_enabled", True, ObsState.ACTIVE),
    ("connector_enabled", False, ObsState.DISABLED),
    ("pii_fields_shown", True, ObsState.EXPOSED),
    ("only_stable_reference_shown", True, ObsState.REDACTED),
    ("record_shown", True, ObsState.PRESENT),
)

_RESOURCE_ID_RE = re.compile(r"[a-z_]+_\d+")


def map_facts(
    entry: ManifestEntry,
    facts: MediaFacts,
    link_rows: Iterable[ClassifiedActivity],
) -> ParseOutput:
    """Observations and notes for one media file; only the LINK rows of `link_rows` join."""
    links = tuple(row for row in link_rows if row.kind is ActKind.LINK)
    observations: List[Observation] = []
    notes: List[str] = []
    seen: Set[Tuple[str, str]] = set()
    linked_file = any(_matching_links(_labels(record), links) for record in facts.records)
    for index, record in enumerate(facts.records):
        locator = "%s:record[%d]" % (entry.file_id, index)
        target = _target(record, links, linked_file, locator, notes)
        if target is None:
            continue
        system_id, resource_id, keys = target
        state = _state(record.get("state_facts"))
        if state is None:
            notes.append("%s: reference %s shown without state" % (locator, resource_id))
        elif (system_id, resource_id) in seen:
            notes.append("%s: duplicate record for %s ignored" % (locator, resource_id))
        else:
            seen.add((system_id, resource_id))
            observations.append(
                Observation(
                    file_id=entry.file_id,
                    captured_at=entry.captured_at,
                    entry_time=entry.captured_at,
                    system_id=system_id,
                    resource_id=resource_id,
                    category=_text(record.get("category")).upper() or None,
                    state=state,
                    subject_keys=keys,
                    locator=locator,
                )
            )
    return ParseOutput(observations=tuple(observations), notes=tuple(notes))


def _target(
    record: Mapping[str, Any],
    links: Tuple[ClassifiedActivity, ...],
    linked_file: bool,
    locator: str,
    notes: List[str],
) -> Optional[Tuple[str, str, FrozenSet[str]]]:
    """(system_id, resource_id, subject_keys) by path (a) then (b); None with a note otherwise."""
    labels = _labels(record)
    shown = _shown_keys(record)
    matched = _matching_links(labels, links)
    if len(matched) > 1:
        notes.append("%s: %s match %d LINK rows, ambiguous" % (locator, labels, len(matched)))
        return None
    if matched:
        return _link_target(matched[0], labels, shown, locator, notes)
    for label in labels:
        system_id = _system_for(label)
        if system_id is None:
            continue
        if not shown:
            notes.append("%s: reference %s shown without identifier" % (locator, label))
            return None
        if linked_file and all(key.startswith(USER_PREFIX) for key in shown):
            notes.append("%s: %s shows only a user reference; no LINK row ties it" % (locator, label))
            return None
        return system_id, label, shown
    notes.append("%s: %s has no LINK row and no resource id" % (locator, labels))
    return None


def _shown_keys(record: Mapping[str, Any]) -> FrozenSet[str]:
    """Subject keys of the identifiers a record lists.

    Plain emails, phones and user references give their usual keys. An email or phone stored
    only as `sha256:<hex>` (a response redacted at rest) gives the key of that digest, which an
    identity holds for each of its emails and phones, so a hashed record matches like a plain one.
    """
    emails = [item for item in record.get("emails") or [] if isinstance(item, str)]
    phones = [item for item in record.get("phones") or [] if isinstance(item, str)]
    found = set(keys_from_record([emails, phones, record.get("user_refs") or []]))
    found.update(key for key in map(redacted_email_key, emails) if key)
    found.update(key for key in map(redacted_phone_key, phones) if key)
    return frozenset(found)


def _labels(record: Mapping[str, Any]) -> Tuple[str, ...]:
    """The non-empty resource hint and display id of a record, in that order."""
    labels = (_text(record.get("resource_hint")), _text(record.get("display_id")))
    return tuple(label for label in labels if label)


def _link_target(
    link: ClassifiedActivity,
    labels: Tuple[str, ...],
    shown: FrozenSet[str],
    locator: str,
    notes: List[str],
) -> Optional[Tuple[str, str, FrozenSet[str]]]:
    """Path (a): the LINK row decides system, resource and keys; shown identity only adds keys."""
    named = [label for label in labels if _system_for(label)]
    if any(label != link.resource_id for label in named):
        notes.append("%s: %s differs from LINK %s" % (locator, named, link.activity_id))
        return None
    keys = _link_keys(link)
    if shown and not shown & (keys | _link_digest_keys(link)):
        notes.append("%s: identity contradicts LINK %s; LINK wins" % (locator, link.activity_id))
        return link.system_id, link.resource_id, keys
    return link.system_id, link.resource_id, keys | shown


def _matching_links(
    labels: Tuple[str, ...], links: Tuple[ClassifiedActivity, ...]
) -> List[ClassifiedActivity]:
    """LINK rows whose alias or resource_id equals a label, one per distinct target."""
    found: Dict[Tuple[str, str, Optional[str], Optional[str]], ClassifiedActivity] = {}
    for link in links:
        if link.alias in labels or link.resource_id in labels:
            target = (link.system_id, link.resource_id, link.linked_email, link.linked_user)
            found.setdefault(target, link)
    return list(found.values())


def _link_keys(link: ClassifiedActivity) -> FrozenSet[str]:
    """Subject keys a LINK row asserts: its email and its user_N."""
    keys: Set[str] = set()
    if link.linked_email:
        keys.add(email_key(link.linked_email))
    user = user_key(link.linked_user) if link.linked_user else None
    if user:
        keys.add(user)
    return frozenset(keys)


def _link_digest_keys(link: ClassifiedActivity) -> FrozenSet[str]:
    """The key of a LINK row's email as a digest, so a `sha256:` record agrees with its LINK row."""
    return frozenset({HASH_PREFIX + email_digest(link.linked_email)} if link.linked_email else ())


def _system_for(label: str) -> Optional[str]:
    """System that owns a literal resource id such as `support_<digits>`; None for any other text."""
    return system_for(label) if _RESOURCE_ID_RE.fullmatch(label) else None


def _state(state_facts: Any) -> Optional[ObsState]:
    """State from the extracted state_facts through STATE_RULES; None when no rule fires."""
    if not isinstance(state_facts, Mapping):
        return None
    for fact, value, state in STATE_RULES:
        if state_facts.get(fact) is value:
            return state
    return None


def _text(value: Any) -> str:
    """Stripped text of an extracted field; empty for anything that is not a string."""
    return value.strip() if isinstance(value, str) else ""
