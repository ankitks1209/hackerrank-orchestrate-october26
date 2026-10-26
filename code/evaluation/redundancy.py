"""Per-component redundancy matrix from a run's diagnostics (check P2d).

Each solver component is set against a second signal that the run itself recorded in
`diagnostics.md`: activity templates against evidence (state), the lexicon against the intake rows (intent) and the cited file against
the raw text (citation). The module reads text only and imports nothing from `ghostaudit`.
It also reports the single-signal fraction: emitted steps whose resource link rests on timing
alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

CASE_HEADING = re.compile(r"^### (case_\d+) \((evaluation|sample)\): (\w+)$", re.MULTILINE)
VERDICT = re.compile(r"^- Verdict (\S+)/(\S+) \w+ violating=\w+ basis=([a-z_\-]+): (\w+) via (\w+) as", re.MULTILINE)
TEMPLATE_DISAGREEMENTS = re.compile(r"Evidence/template disagreements: (\d+)")
INTENT_ROW = re.compile(r"^\| (\w+) \| (\w+) \| (\w+) \| (\d+) \|$", re.MULTILINE)
UNREAD_MEDIA = re.compile(r"^- Unread in-window media: (.+)$", re.MULTILINE)
TIMING_BASES = frozenset({"unique", "elimination", "coupling", "never_mix", "fifo_pairing"})
VIA_EVIDENCE = "evidence"
NON_DELETION = "NON_DELETION"
INTAKE_ROW = "N_ROW"


@dataclass(frozen=True)
class Diagnostics:
    """Numbers the matrix needs, parsed from `diagnostics.md`."""

    template_disagreements: int
    verdicts: Mapping[str, Mapping[str, Tuple[str, str]]]  # case -> rid -> (basis, state source)
    intent_rows: Tuple[Tuple[str, str, str, int], ...]  # lexicon, model, intake, requests
    unread_media: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)  # case -> media file ids


def parse_diagnostics(text: str) -> Diagnostics:
    """Parse the sections of `diagnostics.md` that P2d reads; missing sections give empty values."""
    template = TEMPLATE_DISAGREEMENTS.search(text)
    sections = CASE_HEADING.split(text)
    verdicts: Dict[str, Dict[str, Tuple[str, str]]] = {}
    unread: Dict[str, Tuple[str, ...]] = {}
    for index in range(1, len(sections) - 3, 4):
        case_id, kind, body = sections[index], sections[index + 1], sections[index + 3]
        if kind == "evaluation":
            verdicts[case_id] = {m.group(2): (m.group(3), m.group(5)) for m in VERDICT.finditer(body)}
            media = UNREAD_MEDIA.search(body)
            if media:
                unread[case_id] = tuple(media.group(1).split(", "))
    rows = tuple((m.group(1), m.group(2), m.group(3), int(m.group(4))) for m in INTENT_ROW.finditer(text))
    return Diagnostics(int(template.group(1)) if template else 0, verdicts, rows, unread)


def read_diagnostics(path: Path) -> Diagnostics:
    return parse_diagnostics(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Row:
    """One component of the matrix: how many items two signals could both judge, and how many agree."""

    component: str
    alternative: str
    comparable: int
    agree: int

    @property
    def rate(self) -> float:
        return self.agree / self.comparable if self.comparable else 1.0


def single_signal_fraction(diag: Diagnostics, steps_by_case: Mapping[str, Sequence[str]]) -> Tuple[int, int]:
    """(steps whose resource link rests on timing alone, all evaluation steps)."""
    timing = total = 0
    for case_id, rids in sorted(steps_by_case.items()):
        bases = diag.verdicts.get(case_id, {})
        for rid in rids:
            total += 1
            timing += bases.get(rid, ("", ""))[0] in TIMING_BASES
    return timing, total


def intent_row(diag: Diagnostics) -> Row:
    """Lexicon verdict against the privacy-intake rows: a non-deletion text should have an intake row."""
    comparable = agree = 0
    for lexicon, _model, intake, count in diag.intent_rows:
        comparable += count
        agree += count if (lexicon == NON_DELETION) == (intake == INTAKE_ROW) else 0
    return Row("intent", "lexicon vs intake row", comparable, agree)


def matrix(diag: Diagnostics, citation_agree: int, citation_total: int) -> List[Row]:
    """The three rows of P2d."""
    evidence_states = sum(1 for case in diag.verdicts.values() for _basis, via in case.values()
                          if via == VIA_EVIDENCE)
    return [
        Row("state", "activity template vs evidence", evidence_states,
            evidence_states - diag.template_disagreements),
        intent_row(diag),
        Row("citation", "grep of the cited file vs locator check", citation_total, citation_agree),
    ]
