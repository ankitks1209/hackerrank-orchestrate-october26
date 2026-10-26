"""Tests for ghostaudit.evidence.base (SPEC 3.1 single-claim parser selection)."""
from __future__ import annotations

import unittest
from pathlib import Path

from ghostaudit import evidence
from ghostaudit.evidence.base import EvidenceParser, ParseError, ParseOutput, select_parser
from ghostaudit.model import ManifestEntry

ENTRY = ManifestEntry("evidence_01", Path("evidence/logs/a.log"), "origin", 0, 0)


class DummyParser:
    def __init__(self, name: str, prefix: bytes) -> None:
        self.name = name
        self._prefix = prefix

    def detect(self, entry: ManifestEntry, head: bytes) -> bool:
        return head.startswith(self._prefix)

    def parse(self, entry: ManifestEntry, data: bytes) -> ParseOutput:
        return ParseOutput(notes=(self.name,))


class SelectParserTests(unittest.TestCase):
    def test_single_claim_returns_that_parser(self) -> None:
        parsers = [DummyParser("sql", b"--"), DummyParser("json", b"{")]
        self.assertIs(select_parser(ENTRY, b"{}", parsers), parsers[1])

    def test_no_claim_raises(self) -> None:
        with self.assertRaisesRegex(ParseError, "evidence_01.*none"):
            select_parser(ENTRY, b"???", [DummyParser("sql", b"--")])

    def test_two_claims_raise_and_name_both(self) -> None:
        parsers = [DummyParser("a", b"{"), DummyParser("b", b"{\"")]
        with self.assertRaisesRegex(ParseError, "a, b"):
            select_parser(ENTRY, b'{"x"', parsers)

    def test_registry_claims_nothing_for_an_unknown_file_type(self) -> None:
        unknown = ManifestEntry("evidence_01", Path("evidence/other/a.bin"), "origin", 0, 0)
        with self.assertRaises(ParseError):
            select_parser(unknown, b"{}", evidence.REGISTRY)


class ParseOutputTests(unittest.TestCase):
    def test_defaults_are_empty_tuples(self) -> None:
        output = ParseOutput()
        self.assertEqual((output.observations, output.scopes, output.notes), ((), (), ()))

    def test_dummy_satisfies_protocol_shape(self) -> None:
        parser: EvidenceParser = DummyParser("x", b"")
        self.assertEqual(parser.parse(ENTRY, b"").notes, ("x",))


if __name__ == "__main__":
    unittest.main()
