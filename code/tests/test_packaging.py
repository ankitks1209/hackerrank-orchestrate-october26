"""Tests for the packaging metadata and the entry points (`pyproject.toml`, `main.py`, `ghostaudit.cli`)."""
from __future__ import annotations

import importlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict

import ghostaudit

CODE_DIR = Path(__file__).resolve().parents[1]
PYPROJECT = CODE_DIR / "pyproject.toml"
SCRIPT_LINE = re.compile(r'^(?P<name>[\w-]+)\s*=\s*"(?P<module>[\w.]+):(?P<function>\w+)"\s*$')


def table(name: str) -> str:
    """The text of one `[name]` table of pyproject.toml (the file is small and flat)."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"^\[%s\]\s*\n(.*?)(?=^\[|\Z)" % re.escape(name), text, re.S | re.M)
    if match is None:
        raise AssertionError("no [%s] table in pyproject.toml" % name)
    return match.group(1)


def scripts() -> Dict[str, str]:
    found = {}
    for line in table("project.scripts").splitlines():
        match = SCRIPT_LINE.match(line.strip())
        if match:
            found[match.group("name")] = "%s:%s" % (match.group("module"), match.group("function"))
    return found


class PyprojectTests(unittest.TestCase):
    def test_the_build_backend_is_setuptools(self) -> None:
        build = table("build-system")
        self.assertIn("setuptools", build)
        self.assertIn("setuptools.build_meta", build)

    def test_the_project_needs_nothing_at_run_time_and_python_39(self) -> None:
        project = table("project")
        self.assertIn('requires-python = ">=3.9"', project)
        self.assertIn("dependencies = []", project)

    def test_the_version_matches_the_package(self) -> None:
        self.assertIn('version = "%s"' % ghostaudit.__version__, table("project"))

    def test_package_discovery_names_the_solver_and_the_evaluation_package(self) -> None:
        find = table("tool.setuptools.packages.find")
        self.assertIn('"ghostaudit*"', find)
        self.assertIn('"evaluation*"', find)

    def test_prompts_and_the_cache_are_package_data(self) -> None:
        data = table("tool.setuptools.package-data")
        self.assertIn("llm/prompts/*.md", data)
        self.assertIn("cache/*.json", data)
        self.assertTrue(list((CODE_DIR / "ghostaudit" / "llm" / "prompts").glob("*.md")))

    def test_the_live_sdk_is_an_optional_extra(self) -> None:
        extras = table("project.optional-dependencies")
        self.assertIn("live", extras)
        self.assertIn("anthropic==", extras)


class EntryPointTests(unittest.TestCase):
    def test_the_two_commands_are_declared(self) -> None:
        self.assertEqual(sorted(scripts()), ["ghostaudit", "ghostaudit-eval"])

    def test_every_script_target_is_an_importable_callable(self) -> None:
        for name, target in sorted(scripts().items()):
            module, function = target.split(":")
            self.assertTrue(callable(getattr(importlib.import_module(module), function)), name)

    def test_the_main_shim_is_three_lines_of_code_and_adds_no_path(self) -> None:
        source = (CODE_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn("from ghostaudit.cli import main", source)
        self.assertNotIn("sys.path", source)

    def test_the_shim_runs_from_any_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as elsewhere:
            done = subprocess.run(
                [sys.executable, str(CODE_DIR / "main.py"), "--out", str(Path(elsewhere) / "o.csv"),
                 "--diag", str(Path(elsewhere) / "diag"), "--help"], cwd=elsewhere,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--agent", done.stdout)
        self.assertIn("--agent-max-usd", done.stdout)

    def test_the_evaluation_package_runs_as_a_module_from_the_code_directory(self) -> None:
        done = subprocess.run(
            [sys.executable, "-m", "evaluation"], cwd=str(CODE_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        self.assertEqual(done.returncode, 2)
        self.assertIn("check", done.stderr)


if __name__ == "__main__":
    unittest.main()
