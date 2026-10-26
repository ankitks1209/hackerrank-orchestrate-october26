"""Pipe-delimited TXT handover parser (SPEC F8, with the F6 result vocabulary).

Implements SPEC F8: each line matching
`- <ts> | <system> | <resource_id> | <category> | <result> | <key>` is one
observation. The key `no direct identifier` carries no subject key, and the
result words use the SPEC F6 vocabulary. Other lines are framing text and are
ignored. A matching line with an unknown result or timestamp is skipped and
recorded in the parse notes.
"""
from __future__ import annotations

import re
from typing import List, Sequence

from ghostaudit.evidence.base import ParseError, ParseOutput
from ghostaudit.keys import keys_from_record
from ghostaudit.model import RESULT_STATES, ManifestEntry, Observation
from ghostaudit.timeutil import to_epoch

HANDOVER_SUFFIX = ".txt"
_LINE_PATTERN = r"^- (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (.*)$"
_LINE_RE = re.compile(_LINE_PATTERN)
_CLAIM_RE = re.compile(_LINE_PATTERN, re.MULTILINE)


class HandoverParser:
    """Claims .txt evidence that holds at least one handover line (SPEC F8)."""

    name = "handover_txt"

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        """True for a .txt file whose leading bytes contain a handover line."""
        if entry.path.suffix != HANDOVER_SUFFIX:
            return False
        return _CLAIM_RE.search(head.decode("utf-8", errors="replace")) is not None

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        """Decode every handover line into one Observation (SPEC F8)."""
        text = _decode(entry, data)
        observations: List[Observation] = []
        notes: List[str] = []
        for number, line in enumerate(text.splitlines(), start=1):
            match = _LINE_RE.match(line)
            if match is None:
                continue
            locator = "%s:L%d" % (entry.file_id, number)
            try:
                observations.append(_observation(entry, locator, match.groups()))
            except ValueError as error:
                notes.append("%s skipped: %s" % (locator, error))
        return ParseOutput(observations=tuple(observations), notes=tuple(notes))


def _decode(entry: ManifestEntry, data: bytes) -> str:
    """Decode the whole file as UTF-8; ParseError when it is not text."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ParseError("%s is not UTF-8 text: %s" % (entry.file_id, error)) from error


def _observation(
    entry: ManifestEntry, locator: str, fields: Sequence[str]
) -> Observation:
    """Build one observation; ValueError for an unknown result or a bad timestamp."""
    ts, system_id, resource_id, category, result, key = fields
    state = RESULT_STATES.get(result)
    if state is None:
        raise ValueError("unknown result %r" % result)
    return Observation(
        file_id=entry.file_id,
        captured_at=entry.captured_at,
        entry_time=to_epoch(ts),
        system_id=system_id,
        resource_id=resource_id,
        category=category,
        state=state,
        # "no direct identifier" matches no key shape, so it yields no keys (SPEC F8).
        subject_keys=keys_from_record(key),
        locator=locator,
    )
