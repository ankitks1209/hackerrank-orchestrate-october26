"""Tests for the shipped design docs.

* every `SPEC <id>` cited by a docstring or comment under `code/` is defined in `docs/SPEC.md`;
* the docs name no evaluation case, user or dataset resource id;
* the layering table of `docs/ARCHITECTURE.md` equals the real module-level import graph;
* `docs/DECISIONS.md` has its index, its records and the four labelled parts of each record.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import Dict, FrozenSet, List, Set

from ghostaudit.config import Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.identity import IdentityIndex
from ghostaudit.policy import SYSTEM_BY_PREFIX
from tests.dataset_guard import needs_dataset

CODE_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = CODE_DIR / "docs"
PACKAGE_DIR = CODE_DIR / "ghostaudit"
PACKAGE = "ghostaudit"
SAMPLE_CASE_LIMIT = 32
MIN_DECISIONS = 12
DECISION_PARTS = ("**Context.**", "**Decision.**", "**Alternatives.**", "**Evidence.**")
ID_TOKEN = r"(?:[A-Z]\d+[a-z]?(?:\.\d+)?|\d+(?:\.\d+)?[a-z]?)"
CITATION = re.compile(r"SPEC\s+(" + ID_TOKEN + r"(?:\s*(?:,|/|-|and|or|–)\s*" + ID_TOKEN + r")*)")
BOLD_ID = re.compile(r"\*\*((?:[A-Z]\d+[a-z]?)|(?:\d+\.\d+[a-z]?))\*\*")
HEADING_ID = re.compile(r"^#{2,3} (\d+(?:\.\d+)?[a-z]?)[ .]", re.MULTILINE)
RESOURCE_ID = re.compile(r"\b(?:%s)\d+\b" % "|".join(re.escape(prefix) for prefix in SYSTEM_BY_PREFIX))
CASE_ID = re.compile(r"\bcase_(\d+)\b")
USER_ID = re.compile(r"\buser_\d+\b")
LAYER_ROW = re.compile(r"^\| (\d+) \| (.+?) \|", re.MULTILINE)
BRACES = re.compile(r"^(.*)\{(.*)\}(.*)$")
PACKAGE_INITS = frozenset({PACKAGE, "llm", "evidence", "agent"})


def read_doc(name: str) -> str:
    return (DOCS_DIR / name).read_text(encoding="utf-8")


def defined_ids(spec_text: str) -> FrozenSet[str]:
    """Rule and section ids that SPEC.md defines (bold ids and numbered headings)."""
    return frozenset(BOLD_ID.findall(spec_text)) | frozenset(HEADING_ID.findall(spec_text))


def cited_ids(text: str) -> Set[str]:
    """Every id in a `SPEC ...` citation of `text`."""
    found: Set[str] = set()
    for match in CITATION.finditer(text):
        found.update(re.findall(ID_TOKEN, match.group(1)))
    return found


def is_defined(cited: str, defined: FrozenSet[str]) -> bool:
    """An id is defined when it, or the rule it is an item of, is defined (`V5.2` is an item of `V5`)."""
    parent = re.sub(r"\.\d+$", "", cited)
    return cited in defined or parent in defined or re.sub(r"[a-z]$", "", parent) in defined


def python_files() -> List[Path]:
    return sorted(path for path in CODE_DIR.rglob("*.py") if "__pycache__" not in path.parts)


def module_imports(path: Path, modules: Set[str]) -> Set[str]:
    """Package modules imported at module level by `path`."""
    found: Set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == PACKAGE:
            base = node.module[len(PACKAGE):].lstrip(".")
            for alias in node.names:
                candidate = ("%s.%s" % (base, alias.name)).strip(".")
                found.add(candidate if candidate in modules else base)
    return found & modules


def module_levels() -> Dict[str, int]:
    """Level of each module: one above the highest module it imports (0 when it imports none)."""
    paths = {}
    for path in PACKAGE_DIR.rglob("*.py"):
        name = ".".join(path.relative_to(PACKAGE_DIR).with_suffix("").parts)
        paths[PACKAGE if name == "__init__" else name.replace(".__init__", "")] = path
    imports = {name: module_imports(path, set(paths)) - {name} for name, path in paths.items()}
    levels: Dict[str, int] = {}

    def level(name: str) -> int:
        if name not in levels:
            levels[name] = 1 + max((level(dep) for dep in imports[name]), default=-1)
        return levels[name]

    for name in sorted(paths):
        level(name)
    return levels


def expand(cell: str) -> List[str]:
    """Module names of a table cell: backticked, `a/b` for `a.b`, one `{x,y}` group expanded."""
    names: List[str] = []
    for token in re.findall(r"`([^`]+)`", cell):
        group = BRACES.match(token)
        options = [group.group(1) + part + group.group(3) for part in group.group(2).split(",")] if group else [token]
        names.extend(option.replace("/", ".") for option in options)
    return names


def documented_levels() -> Dict[str, int]:
    table = read_doc("ARCHITECTURE.md").split("## 2. Module layering")[1].split("Rules of the layering")[0]
    documented: Dict[str, int] = {}
    for level, cell in LAYER_ROW.findall(table):
        for name in expand(cell):
            if name.startswith("code."):
                continue
            documented[name] = int(level)
    return documented


class SpecCitationTests(unittest.TestCase):
    def test_every_cited_id_is_defined(self) -> None:
        defined = defined_ids(read_doc("SPEC.md"))
        undefined = {}
        for path in python_files():
            for cited in sorted(cited_ids(path.read_text(encoding="utf-8"))):
                if not is_defined(cited, defined):
                    undefined.setdefault(cited, str(path.relative_to(CODE_DIR)))
        self.assertEqual(undefined, {})

    def test_the_extractor_finds_ranges_and_items(self) -> None:
        self.assertEqual(cited_ids("see SPEC L4-L8) and SPEC 8.4, V5.2"), {"L4", "L8", "8.4", "V5.2"})
        self.assertEqual(cited_ids("no citation here"), set())

    def test_an_unknown_id_is_reported(self) -> None:
        defined = defined_ids("**L7** rule\n\n## 8. Section\n\n### 8.4 Order\n")
        self.assertTrue(is_defined("L7", defined))
        self.assertTrue(is_defined("8.4", defined))
        self.assertFalse(is_defined("L99", defined))

    def test_the_spec_defines_the_rule_families(self) -> None:
        defined = defined_ids(read_doc("SPEC.md"))
        for family, last in (("I", 4), ("F", 10), ("T", 6), ("V", 5), ("N", 8), ("A", 6)):
            for number in range(1, last + 1):
                self.assertIn("%s%d" % (family, number), defined)
        for number in range(1, 13):
            self.assertIn("L%d" % number, defined)


class BannedLiteralTests(unittest.TestCase):
    def test_docs_name_no_evaluation_case_ids(self) -> None:
        for name in ("SPEC.md", "ARCHITECTURE.md", "DECISIONS.md"):
            numbers = [int(number) for number in CASE_ID.findall(read_doc(name))]
            self.assertEqual([n for n in numbers if n > SAMPLE_CASE_LIMIT], [], name)

    @needs_dataset
    def test_docs_name_no_evaluation_user_or_dataset_resource_ids(self) -> None:
        reader = DatasetReader(Config().dataset_dir)
        index = IdentityIndex.build(reader.identities(), reader.audit_log())
        evaluation_users = {index.resolve(request.email) for request in reader.requests() if not request.is_sample}
        self.assertTrue(evaluation_users)
        for name in ("SPEC.md", "ARCHITECTURE.md", "DECISIONS.md"):
            text = read_doc(name)
            self.assertEqual(set(USER_ID.findall(text)) & evaluation_users, set(), name)
            self.assertEqual(RESOURCE_ID.findall(text), [], name)


class LayeringTests(unittest.TestCase):
    def test_documented_levels_equal_the_import_graph(self) -> None:
        levels = module_levels()
        documented = documented_levels()
        self.assertTrue(documented)
        self.assertEqual({name: levels.get(name) for name in documented}, documented)

    def test_every_module_is_documented(self) -> None:
        missing = set(module_levels()) - PACKAGE_INITS - set(documented_levels())
        self.assertEqual(missing, set())


class DecisionRecordTests(unittest.TestCase):
    def test_records_have_the_four_parts(self) -> None:
        text = read_doc("DECISIONS.md")
        records = re.split(r"^## (?=D\d+\.)", text, flags=re.MULTILINE)[1:]
        self.assertGreaterEqual(len(records), MIN_DECISIONS)
        for record in records:
            for part in DECISION_PARTS:
                self.assertIn(part, record, record.splitlines()[0])

    def test_index_lists_every_record(self) -> None:
        text = read_doc("DECISIONS.md")
        indexed = re.findall(r"^\| (D\d+) \|", text, flags=re.MULTILINE)
        headed = re.findall(r"^## (D\d+)\.", text, flags=re.MULTILINE)
        self.assertEqual(indexed, headed)


class ArchitectureTests(unittest.TestCase):
    def test_pipeline_diagram_is_mermaid(self) -> None:
        text = read_doc("ARCHITECTURE.md")
        self.assertIn("```mermaid\nflowchart", text)

    def test_tests_named_as_evidence_exist(self) -> None:
        names = set(re.findall(r"`(test_[a-z_0-9]+)`", read_doc("DECISIONS.md")))
        self.assertTrue(names)
        for name in sorted(names):
            self.assertTrue((CODE_DIR / "tests" / (name + ".py")).exists(), name)


if __name__ == "__main__":
    unittest.main()
