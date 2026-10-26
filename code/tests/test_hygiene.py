"""Hygiene of the shipped text: no references a reader of `code.zip` cannot resolve.

Task tags and the names of planning documents mean nothing inside the archive, and a README
link to a file the archive does not hold is a dead link.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Iterator

from ghostaudit.config import REPO_ROOT
from tools.build_zip import CODE_DIR, ROOT_FILES

PLAN_NAMES = ("IMPLEMENTATION" + "_PLAN", "LOCAL_EVALUATION" + "_STRATEGY", "SCORING" + "_STRATEGY")
# T1-T6 are SPEC time rules, not task tags; a time such as "T00:00:00Z" is not a tag either.
TASK_TAG = re.compile(r"\bT(?:0[0-9]|[1-9][0-9])[a-z]?\b(?!:)")
LINK = re.compile(r"\]\((\./[^)#\s]+)")


def shipped_text_files() -> Iterator[Path]:
    for name in ROOT_FILES:
        path = REPO_ROOT / name
        if path.is_file():
            yield path
    for path in sorted((REPO_ROOT / CODE_DIR).rglob("*")):
        if path.suffix in (".py", ".md") and "__pycache__" not in path.parts and path.name != Path(__file__).name:
            yield path


class ShippedTextTests(unittest.TestCase):
    def test_no_planning_document_names_or_task_tags(self) -> None:
        problems = []
        for path in shipped_text_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(name in line for name in PLAN_NAMES) or TASK_TAG.search(line):
                    problems.append("%s:%d" % (path.relative_to(REPO_ROOT), number))
        self.assertEqual(problems, [])

    def test_readme_links_point_into_the_archive(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        shipped = {name for name in ROOT_FILES}
        for target in LINK.findall(text):
            relative = target[2:]
            with self.subTest(link=target):
                self.assertTrue(relative in shipped or relative.startswith(CODE_DIR + "/"), target)
                self.assertTrue((REPO_ROOT / relative).exists(), target)


if __name__ == "__main__":
    unittest.main()
