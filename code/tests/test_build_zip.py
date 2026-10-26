"""Tests for the reproducible packager.

Fixtures are tiny synthetic repositories in a temporary directory. The real repository is built
once to prove that nothing but the not-yet-written reports and response cache is missing.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from ghostaudit.config import REPO_ROOT
from ghostaudit.emit import write_output
from tests.dataset_guard import needs_dataset
from evaluation.gold import SAMPLE_OUTPUT, GoldReader
from tools import build_zip

FILES: Dict[str, str] = {
    "README.md": "# Readme\n",
    "requirements.txt": "sdk==1.0; python_version >= \"3.10\"\n",
    "code/main.py": "print('x')\n",
    "code/ghostaudit/pipeline.py": "x = 1\n",
    "code/evaluation/scoring.py": "x = 1\n",
    "code/evaluation/custom_cases.py": "x = 1\n",
    "code/tools/render_reports.py": "x = 1\n",
    "code/tools/build_zip.py": "x = 1\n",
    "code/evaluation/evaluation_report.md": "# Evaluation\n",
    "code/evaluation/usage_report.md": "# Usage\n",
    "code/docs/SPEC.md": "# Spec\n",
    "code/ghostaudit/llm/prompts/intent.v1.md": "prompt\n",
    "code/ghostaudit/cache/abc.json": "{}\n",
}
SYNTHETIC_EMAIL = "someone.synthetic@example.test"
SYNTHETIC_PHONE = "+00 111 222 3333"


def write_repo(root: Path, extra: Optional[Dict[str, str]] = None) -> Path:
    for name, text in {**FILES, **(extra or {})}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name) / "repo"
        self.out = Path(self._dir.name) / "code.zip"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def build(self, extra: Optional[Dict[str, str]] = None, **options: object):
        shutil.rmtree(str(self.root), ignore_errors=True)
        write_repo(self.root, extra)
        return build_zip.build(self.root, self.out, **options)


class ReproducibilityTests(Scratch):
    def test_two_builds_give_identical_bytes(self) -> None:
        problems, digest = self.build()
        self.assertEqual(problems, [])
        first = self.out.read_bytes()
        os.utime(str(self.root / "README.md"), (time.time() + 99, time.time() + 99))  # timestamps must not matter
        problems, again = build_zip.build(self.root, self.out)
        self.assertEqual((problems, again, self.out.read_bytes()), ([], digest, first))

    def test_entries_are_sorted_with_fixed_time_and_mode(self) -> None:
        self.build()
        with zipfile.ZipFile(str(self.out)) as archive:
            infos = archive.infolist()
        self.assertEqual([i.filename for i in infos], sorted(i.filename for i in infos))
        for info in infos:
            self.assertEqual(info.date_time, build_zip.ZIP_DATE)
            self.assertEqual(info.external_attr, build_zip.FILE_MODE)
            self.assertFalse(info.filename.endswith("/"))

    def test_report_copies_sit_at_the_zip_root(self) -> None:
        self.build()
        with zipfile.ZipFile(str(self.out)) as archive:
            for name in build_zip.EVALUATION_REPORTS:
                self.assertEqual(archive.read("evaluation/" + name),
                                 archive.read("code/evaluation/" + name))

    def test_content_hash_follows_content(self) -> None:
        _problems, before = self.build()
        (self.root / "code/main.py").write_text("print('y')\n", encoding="utf-8")
        _problems, after = build_zip.build(self.root, self.out)
        self.assertNotEqual(before, after)

    def test_junk_is_left_out(self) -> None:
        junk = {"code/ghostaudit/__pycache__/a.cpython-39.pyc": "x", "code/.DS_Store": "x",
                "code/.venv/lib/x.py": "x", "code/diagnostics/diagnostics.md": "x", "code/a.pkl": "x"}
        problems, _digest = self.build(junk)
        self.assertEqual(problems, [])
        with zipfile.ZipFile(str(self.out)) as archive:
            self.assertEqual([n for n in archive.namelist() if n.split("/")[-1] in
                              {"a.cpython-39.pyc", ".DS_Store", "x.py", "diagnostics.md", "a.pkl"}], [])

    def test_root_files_the_readme_names_are_shipped(self) -> None:
        problems, _digest = self.build({".env.example": "ANTHROPIC_API_KEY=\n", "notes.txt": "x"})
        self.assertEqual(problems, [])
        with zipfile.ZipFile(str(self.out)) as archive:
            names = set(archive.namelist())
        self.assertTrue({"README.md", "requirements.txt", ".env.example"} <= names)
        self.assertNotIn("notes.txt", names)

    def test_dataset_at_the_repository_root_is_never_collected(self) -> None:
        self.build({"dataset/user_identities.csv": "x"})
        with zipfile.ZipFile(str(self.out)) as archive:
            self.assertFalse([n for n in archive.namelist() if n.startswith("dataset")])


class ListingCheckTests(unittest.TestCase):
    def names(self, *extra: str):
        return sorted(set(FILES) | {"evaluation/evaluation_report.md", "evaluation/usage_report.md"} | set(extra))

    def test_a_complete_listing_is_clean(self) -> None:
        self.assertEqual(build_zip.check_listing(self.names()), [])

    def test_each_missing_item_is_named(self) -> None:
        for name in ("README.md", "requirements.txt", "code/main.py", "code/docs/SPEC.md", "code/ghostaudit/pipeline.py", "code/evaluation/scoring.py",
                     "code/evaluation/custom_cases.py", "code/tools/render_reports.py", "code/tools/build_zip.py", "code/ghostaudit/cache/abc.json",
                     "code/ghostaudit/llm/prompts/intent.v1.md", "evaluation/usage_report.md"):
            listing = [n for n in self.names() if n != name]
            self.assertEqual(len(build_zip.check_listing(listing)), 1, name)

    def test_forbidden_content_is_named(self) -> None:
        for offender in ("code/dataset/x.csv", "code/solution/notes.md", "code/plan/p.md", "log.txt",
                         "code/log.txt", ".env", "code/.env", "code/x/nested.zip", "code/x/a.tar.gz",
                         "code/x/a.7z", "devtools/check_log.py", "code/devtools/x.py", "code/evaluation/audit/sampler.py",
                         "code/evaluation/confidence.py", "code/evaluation/RELEASE_CHECKLIST.md",
                         "code/tools/release_gate.py", "code/tools/clean_room.py", "code/tools/append_log.py",
                         "code/tools/check_log.py", "code/__pycache__/a.pyc", "code/.venv/x.py", "code/a.pkl", "code/.DS_Store"):
            self.assertTrue(build_zip.check_listing(self.names(offender)), offender)

    def test_env_example_is_allowed(self) -> None:
        self.assertEqual(build_zip.check_listing(self.names(".env.example")), [])


class TextCheckTests(Scratch):
    def problems(self, text: str, name: str = "code/notes.md", **options: object) -> List[str]:
        return self.build({name: text}, **options)[0]

    def test_home_paths_are_found(self) -> None:
        self.assertTrue(self.problems("see " + "/" + "Users" + "/someone/x"))

    def test_caller_supplied_strings_are_found(self) -> None:
        self.assertTrue(self.problems("contact " + SYNTHETIC_EMAIL, forbidden=[SYNTHETIC_EMAIL]))
        self.assertEqual(self.problems("clean", forbidden=[SYNTHETIC_EMAIL]), [])

    def test_key_shapes_are_found(self) -> None:
        for text in ("key = sk-" + "ant-abcdefghijklmnop", "ANTHROPIC_API_KEY" + "=abcdefghijklmnop0123",
                     'api_key = "' + 'abcdefghijklmnopqrstuvwx"'):
            self.assertTrue(self.problems(text, "code/config.py"), text)
        self.assertEqual(self.problems("os.environ['ANTHROPIC_API_KEY']", "code/config.py"), [])

    def test_dataset_identifiers_in_markdown_are_found_but_not_in_code(self) -> None:
        dataset = Path(self._dir.name) / "dataset"
        dataset.mkdir()
        (dataset / "user_identities.csv").write_text(
            "user_id,name,email,phone,email_hash,updated_at\nuser_0,N,%s,%s,h,t\n" % (SYNTHETIC_EMAIL, SYNTHETIC_PHONE),
            encoding="utf-8")
        self.assertTrue(self.problems("mail " + SYNTHETIC_EMAIL.upper(), dataset=dataset))
        self.assertTrue(self.problems("call " + SYNTHETIC_PHONE.replace(" ", "-"), dataset=dataset))
        self.assertEqual(self.problems("e = '%s'" % SYNTHETIC_EMAIL, "code/fixture.py", dataset=dataset), [])


class ReportCheckTests(Scratch):
    def test_diverging_copies_are_reported(self) -> None:
        files = {name: text.encode("utf-8") for name, text in FILES.items()}
        files["evaluation/usage_report.md"] = b"# Other\n"
        files["evaluation/evaluation_report.md"] = files["code/evaluation/evaluation_report.md"]
        self.assertEqual(build_zip.check_reports(files), ["report copies differ: usage_report.md"])

    def test_empty_reports_are_reported(self) -> None:
        files = {"code/evaluation/usage_report.md": b" \n", "evaluation/usage_report.md": b" \n"}
        self.assertEqual(build_zip.check_reports(files), ["empty report: usage_report.md"])


class CommandLineTests(Scratch):
    def run_cli(self, *arguments: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return build_zip.main(list(arguments))

    def test_success_writes_the_zip_and_manifest(self) -> None:
        write_repo(self.root)
        manifest = Path(self._dir.name) / "manifest.json"
        code = self.run_cli("--root", str(self.root), "--out", str(self.out), "--manifest", str(manifest))
        self.assertEqual(code, build_zip.EXIT_OK)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual([path for path, _digest in data["files"]], sorted(path for path, _digest in data["files"]))
        self.assertEqual(len(data["content_hash"]), 64)

    def test_failed_check_removes_the_zip(self) -> None:
        write_repo(self.root, {"code/x/nested.zip": "x"})
        code = self.run_cli("--root", str(self.root), "--out", str(self.out))
        self.assertEqual((code, self.out.exists()), (build_zip.EXIT_CHECK_FAILED, False))

    def test_failing_report_check_removes_the_zip(self) -> None:
        """`--metrics-dir` makes a drifted or unreadable report check a build failure."""
        write_repo(self.root)
        empty = Path(self._dir.name) / "metrics"
        empty.mkdir()
        code = self.run_cli("--root", str(self.root), "--out", str(self.out), "--metrics-dir", str(empty))
        self.assertEqual((code, self.out.exists()), (build_zip.EXIT_CHECK_FAILED, False))

    def test_cache_files_with_dataset_identifiers_fail_the_check(self) -> None:
        files = {"code/ghostaudit/cache/a.json": '{"email": "%s"}' % SYNTHETIC_EMAIL,
                 "code/ghostaudit/cache/b.json": '{"phone": "+1 555 010 0199"}',
                 "code/ghostaudit/cache/c.json": '{"email": "sha256:%s"}' % ("0" * 64)}
        data = {name: text.encode("utf-8") for name, text in files.items()}
        problems = build_zip.check_cache_identifiers(data, frozenset({SYNTHETIC_EMAIL}), frozenset({"15550100199"}))
        self.assertEqual([p.split(":")[0] for p in problems],
                         ["code/ghostaudit/cache/a.json", "code/ghostaudit/cache/b.json"])
        self.assertEqual(build_zip.check_cache_identifiers(data, frozenset(), frozenset()), [])

    def test_missing_readme_is_an_input_error(self) -> None:
        self.root.mkdir()
        self.assertEqual(self.run_cli("--root", str(self.root), "--out", str(self.out)), build_zip.EXIT_INPUT)


class RealRepositoryTests(unittest.TestCase):
    def test_nothing_is_wrong_except_what_later_tasks_deliver(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            problems, _digest = build_zip.build(REPO_ROOT, Path(scratch) / "code.zip")
        self.assertEqual([p for p in problems if not p.startswith("missing:")], [])


@needs_dataset
class RoundTripTests(unittest.TestCase):
    """The writer reproduces the public answers. The plan expected byte identity, which cannot hold:
    the public file mixes two key orders (8 rows list sorted keys, 24 put `step_no` first) while the
    writer always sorts keys (SPEC 8.4); the grader ignores key order, so equality is checked after
    parsing each `steps_json`."""

    @staticmethod
    def rows(path: Path) -> list:
        with path.open(encoding="utf-8", newline="") as handle:
            return [(row[0], row[1], json.loads(row[2]) if row[2].startswith("[") else row[2])
                    for row in csv.reader(handle)]

    def test_public_answers_survive_the_writer(self) -> None:
        cases = GoldReader().cases()
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "output.csv"
            write_output(cases.values(), target)
            self.assertEqual(self.rows(target), self.rows(SAMPLE_OUTPUT))
            written = target.read_text(encoding="utf-8")
        self.assertNotIn("\r", written)
        self.assertEqual(written.splitlines()[0], "case_id,deletion_status,steps_json")


if __name__ == "__main__":
    unittest.main()
