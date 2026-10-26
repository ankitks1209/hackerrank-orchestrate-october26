"""Evidence parsers (SPEC 3). Each parser task adds its parser to the REGISTRY tuple here."""
from __future__ import annotations

from typing import Tuple

from ghostaudit.evidence.base import EvidenceParser, ParseError, ParseOutput, select_parser
from ghostaudit.evidence.handover import HandoverParser
from ghostaudit.evidence.logs import LogParser
from ghostaudit.evidence.records import RecordsParser
from ghostaudit.evidence.sql import SqlParser

REGISTRY: Tuple[EvidenceParser, ...] = (
    HandoverParser(),
    LogParser(),
    RecordsParser(),
    SqlParser(),
)

__all__ = ["REGISTRY", "EvidenceParser", "ParseError", "ParseOutput", "select_parser"]
