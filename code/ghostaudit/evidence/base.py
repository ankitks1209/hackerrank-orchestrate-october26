"""Evidence parser protocol, parse result and single-claim parser selection.

Implements SPEC 3.1: the parser for a file is chosen by content and structure
(never by file_id), and exactly one parser may claim each file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, Tuple

from ghostaudit.model import ManifestEntry, Observation, ScopeAssertion


class ParseError(Exception):
    """An evidence file or line cannot be decoded or claimed."""


@dataclass(frozen=True)
class ParseOutput:
    """Normalized records of one file plus human-readable parser notes."""

    observations: Tuple[Observation, ...] = ()
    scopes: Tuple[ScopeAssertion, ...] = ()
    notes: Tuple[str, ...] = ()


class EvidenceParser(Protocol):
    """Decodes one evidence family into Observations and ScopeAssertions."""

    name: str

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        """True when this parser recognises the file from its leading bytes."""
        ...

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        """Decode the whole file; raise ParseError on malformed content."""
        ...


def select_parser(
    entry: ManifestEntry, head: bytes, parsers: Sequence[EvidenceParser]
) -> EvidenceParser:
    """Return the one parser that claims the file; ParseError for zero or several."""
    claimed = [parser for parser in parsers if parser.detect(entry, head)]
    if len(claimed) != 1:
        names = ", ".join(parser.name for parser in claimed) or "none"
        raise ParseError(
            "%s must be claimed by exactly one parser, got: %s" % (entry.file_id, names)
        )
    return claimed[0]
