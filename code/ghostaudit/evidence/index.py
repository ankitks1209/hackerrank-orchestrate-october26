"""EvidenceIndex: every parser run once, then immutable lookups (SPEC 3.1, T1-T3).

`build_index` visits the manifest in order. A text file is claimed by exactly one
parser (SPEC 3.1); a media file is mapped from its precomputed `MediaFacts` through
`media.map_facts` with the LINK rows of the activity stream (SPEC F10). A file that
cannot be claimed or decoded is skipped with a note; the run continues.

The index holds no case logic. It orders observations by `(entry_time, captured_at,
manifest order)` so that a resolver reading T2 takes the last admissible one, and it
leaves every T1/T3 time filter to the caller.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from ghostaudit.config import MEDIA_SUFFIXES, PARSE_HEAD_BYTES
from ghostaudit.evidence import REGISTRY
from ghostaudit.evidence.base import ParseError, ParseOutput, select_parser
from ghostaudit.evidence.media import map_facts
from ghostaudit.evidence.sql import account_pointer
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import (
    ActKind,
    ClassifiedActivity,
    ManifestEntry,
    MediaFacts,
    Observation,
    ScopeAssertion,
)

LOGGER = logging.getLogger(__name__)
MEDIA_PARSER = "media"

Key = TypeVar("Key")
Value = TypeVar("Value")


@dataclass(frozen=True)
class EvidenceIndex:
    """Read-only lookups over all parsed evidence; times are integer epochs (SPEC T6)."""

    observations: Tuple[Observation, ...]
    by_rid: Mapping[str, Tuple[Observation, ...]]
    users_by_rid: Mapping[str, Tuple[str, ...]]
    rids_by_user: Mapping[str, Tuple[str, ...]]
    mentions: Mapping[str, Tuple[str, ...]]
    scopes_by_file: Mapping[str, Tuple[ScopeAssertion, ...]]
    pointers: Mapping[str, Tuple[str, ...]]
    entries: Mapping[str, ManifestEntry]
    claimed_by: Mapping[str, str]
    notes: Tuple[str, ...]
    tied_since: Mapping[Tuple[str, str], int] = field(default_factory=dict)

    def tied_by(self, rid: str, user: str, hi: int) -> bool:
        """True when evidence admissible at `hi` ties `rid` to `user` (SPEC L1 under T1).

        `tied_since` holds, for every (resource, user) pair of `users_by_rid`, the
        earliest moment an observation making that tie is admissible. An index built by
        hand without it treats its ties as timeless.
        """
        if user not in self.users_by_rid.get(rid, ()):
            return False
        return self.tied_since.get((rid, user), hi) <= hi

    def owned_by(self, rid: str, subject: Optional[str], hi: Optional[int] = None) -> bool:
        """Owner filter (SPEC L4a): a resource with evidence owners belongs to those subjects only.

        With `hi`, an owner counts only when evidence admissible at `hi` ties it (SPEC T1).
        """
        owners = self.users_by_rid.get(rid, ())
        if hi is not None:
            owners = tuple(user for user in owners if self.tied_by(rid, user, hi))
        return not owners or (subject is not None and subject in owners)

    def named_between(self, rid: str, lo: int, hi: int) -> bool:
        """True when a file captured in `[lo, hi]` names `rid` (SPEC T3, both ends inclusive)."""
        files = self.mentions.get(rid, ())
        return any(lo <= self.entries[file_id].captured_at <= hi for file_id in files)



def build_index(
    manifest: Sequence[ManifestEntry],
    identity: IdentityIndex,
    media_facts: Mapping[str, MediaFacts],
    activities: Iterable[ClassifiedActivity],
) -> EvidenceIndex:
    """Parse every manifest file once, in manifest order, and index the result.

    `activities` are the classified activity rows; their LINK rows join media records.
    """
    links = tuple(act for act in activities if act.kind is ActKind.LINK)
    outputs: List[Tuple[ManifestEntry, ParseOutput]] = []
    claimed_by: Dict[str, str] = {}
    notes: List[str] = []
    for entry in manifest:
        try:
            parser_name, output = _parse_entry(entry, media_facts, links)
        except ParseError as error:
            LOGGER.warning("skipping %s: %s", entry.file_id, error)
            notes.append("%s skipped: %s" % (entry.file_id, error))
            continue
        claimed_by[entry.file_id] = parser_name
        outputs.append((entry, output))
        notes.extend(output.notes)
    order_of = {entry.file_id: entry.order for entry in manifest}
    observations = tuple(
        sorted(
            (obs for _entry, output in outputs for obs in output.observations),
            key=lambda obs: _sort_key(obs, order_of),
        )
    )
    by_rid = _group(observations, lambda obs: obs.resource_id)
    users_by_rid = {rid: _users(identity, rows) for rid, rows in by_rid.items()}
    return EvidenceIndex(
        observations=observations,
        by_rid=_freeze(by_rid),
        users_by_rid=_freeze(users_by_rid),
        rids_by_user=_freeze(_invert(users_by_rid)),
        mentions=_freeze(_mentions(outputs)),
        scopes_by_file=_freeze(
            {entry.file_id: output.scopes for entry, output in outputs if output.scopes}
        ),
        pointers=_freeze(_pointers(observations)),
        entries=_freeze({entry.file_id: entry for entry in manifest}),
        claimed_by=_freeze(claimed_by),
        notes=tuple(notes),
        tied_since=_freeze(_tie_times(identity, observations)),
    )


def _parse_entry(
    entry: ManifestEntry,
    media_facts: Mapping[str, MediaFacts],
    links: Sequence[ClassifiedActivity],
) -> Tuple[str, ParseOutput]:
    """(parser name, output) of one file; a media file without facts yields only a note."""
    if entry.path.suffix.lower() in MEDIA_SUFFIXES:
        facts = media_facts.get(entry.file_id)
        if facts is None:
            return MEDIA_PARSER, ParseOutput(notes=("%s: no media facts" % entry.file_id,))
        return MEDIA_PARSER, map_facts(entry, facts, links)
    data = entry.path.read_bytes()
    parser = select_parser(entry, data[:PARSE_HEAD_BYTES], REGISTRY)
    return parser.name, parser.parse(entry, data)


def _sort_key(obs: Observation, order_of: Mapping[str, int]) -> Tuple[int, int, int]:
    """SPEC T2 order: entry_time (captured_at when absent), captured_at, manifest order."""
    return obs.effective_entry_time, obs.captured_at, order_of[obs.file_id]


def _group(
    rows: Sequence[Observation], key: Callable[[Observation], str]
) -> Dict[str, Tuple[Observation, ...]]:
    grouped: Dict[str, List[Observation]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return {name: tuple(group) for name, group in grouped.items()}


def _users(identity: IdentityIndex, rows: Sequence[Observation]) -> Tuple[str, ...]:
    """Subjects owning any key of the resource's observations (SPEC L1)."""
    found = {key for row in rows for key in row.subject_keys}
    return identity.users_for(found)


def _tie_times(
    identity: IdentityIndex, observations: Sequence[Observation]
) -> Dict[Tuple[str, str], int]:
    """(resource, user) to the earliest moment an observation tying them is admissible (T1)."""
    found: Dict[Tuple[str, str], int] = {}
    for obs in observations:
        moment = max(obs.captured_at, obs.effective_entry_time)
        for user in identity.users_for(obs.subject_keys):
            key = (obs.resource_id, user)
            found[key] = min(found.get(key, moment), moment)
    return found


def _invert(users_by_rid: Mapping[str, Tuple[str, ...]]) -> Dict[str, Tuple[str, ...]]:
    """User to resources, in the order each resource first appears in the sorted evidence."""
    inverted: Dict[str, List[str]] = defaultdict(list)
    for rid, users in users_by_rid.items():
        for user in users:
            inverted[user].append(rid)
    return {user: tuple(rids) for user, rids in inverted.items()}


def _mentions(outputs: Sequence[Tuple[ManifestEntry, ParseOutput]]) -> Dict[str, Tuple[str, ...]]:
    """Resource to the files that observe it or list it in a scope, in manifest order."""
    found: Dict[str, List[str]] = defaultdict(list)
    for entry, output in outputs:
        named = {obs.resource_id for obs in output.observations}
        for scope in output.scopes:
            named |= scope.present_ids
        for rid in sorted(named):
            found[rid].append(entry.file_id)
    return {rid: tuple(file_ids) for rid, file_ids in found.items()}


def _pointers(observations: Sequence[Observation]) -> Dict[str, Tuple[str, ...]]:
    """Search document to the account ids it names as its source (SPEC L12.2)."""
    found: Dict[str, Set[str]] = defaultdict(set)
    for obs in observations:
        account = account_pointer(obs.locator)
        if account is not None:
            found[obs.resource_id].add(account)
    return {rid: tuple(sorted(accounts)) for rid, accounts in found.items()}


def _freeze(mapping: Mapping[Key, Value]) -> Mapping[Key, Value]:
    return MappingProxyType(dict(mapping))
