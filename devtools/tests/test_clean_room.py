"""Tests for the clean-room matrix runner (T34; LOCAL_EVALUATION_STRATEGY 5).

The archive under test is a tiny synthetic project whose `code/main.py` mimics the CLI contract:
it reads `dataset/`, writes `output.csv` and `diagnostics/diagnostics.md` at the root, and exits 2
with a message when the dataset is missing. A second variant leaks the hash seed into its output to
prove that a non-reproducible run is caught. The archive also ships a one-module test suite whose
dataset test skips without `dataset/` (or, in a third variant, fails without it).
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from devtools import clean_room

README = """# Demo

<!-- clean-room:commands -->
```bash
# build the answer
python3 code/main.py
python3 code/check.py
```
"""
MAIN = '''import os, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
data = root / "dataset" / "data.txt"
if not data.is_file():
    sys.stderr.write("cannot run: dataset is missing\\n")
    sys.exit(2)
extra = os.environ.get("PYTHONHASHSEED", "") if LEAK else ""
(root / "output.csv").write_text(data.read_text() + extra, encoding="utf-8")
(root / "diagnostics").mkdir(exist_ok=True)
(root / "diagnostics" / "diagnostics.md").write_text(
    "- Intent requests without a model verdict: MISSES\\n- Media extraction notes: 0\\n", encoding="utf-8")
'''
CHECK = "import sys\nsys.exit(0)\n"
SUITE = '''import unittest
from pathlib import Path
DATA = Path(__file__).resolve().parents[2] / "dataset" / "data.txt"
GUARD = unittest.skipUnless(DATA.is_file() or not SKIPS, "dataset/ is not present")


class DemoTests(unittest.TestCase):
    @GUARD
    def test_reads_the_dataset(self):
        self.assertEqual(DATA.read_text(encoding="utf-8"), "answer\\n")

    def test_runs_everywhere(self):
        self.assertTrue(True)
'''


def make_zip(path: Path, leak: bool = False, misses: int = 0, check: str = CHECK, readme: str = README,
             skips: bool = True) -> None:
    main = MAIN.replace("LEAK", str(leak)).replace("MISSES", str(misses))
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("README.md", readme)
        archive.writestr("code/main.py", main)
        archive.writestr("code/check.py", check)
        archive.writestr("code/tests/__init__.py", "")
        archive.writestr("code/tests/test_demo.py", SUITE.replace("SKIPS", str(skips)))


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        (self.dataset / "data.txt").write_text("answer\n", encoding="utf-8")
        self.archive = self.root / "code.zip"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def run_cli(self, *extra: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = clean_room.main(["--zip", str(self.archive), "--dataset", str(self.dataset), *extra])
        return code, out.getvalue(), err.getvalue()


class PureFunctionTests(unittest.TestCase):
    def test_commands_come_from_the_marked_block(self) -> None:
        self.assertEqual(clean_room.readme_commands(README), ["python3 code/main.py", "python3 code/check.py"])

    def test_missing_marker_block_or_commands_are_rejected(self) -> None:
        for text in ("# no marker\n", "<!-- clean-room:commands -->\nno fence\n",
                     "<!-- clean-room:commands -->\n```bash\n# only a comment\n```\n"):
            with self.assertRaises(clean_room.CleanRoomError):
                clean_room.readme_commands(text)

    def test_paths_are_relocated_for_the_code_directory(self) -> None:
        args = ["python3", "-m", "unittest", "discover", "-s", "code/tests", "-t", "code"]
        self.assertEqual(clean_room.relocate(args, "code"), ["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."])
        self.assertEqual(clean_room.relocate(args, ""), args)

    def test_interpreter_substitution_only_touches_the_first_word(self) -> None:
        self.assertEqual(clean_room.with_python(["python3", "code/main.py", "python3"], "/py"), ["/py", "code/main.py", "python3"])
        self.assertEqual(clean_room.with_python(["ls"], "/py"), ["ls"])

    def test_sandbox_wrapper(self) -> None:
        wrapped = clean_room.sandboxed(["python3", "x"], True)
        self.assertEqual(wrapped[:3], [clean_room.SANDBOX_TOOL, "-p", clean_room.SANDBOX_PROFILE])
        self.assertIn("deny network*", clean_room.SANDBOX_PROFILE)
        self.assertEqual(clean_room.sandboxed(["python3", "x"], False), ["python3", "x"])

    def test_matrix_is_the_product_of_the_axes(self) -> None:
        cells = clean_room.matrix(["a", "b"])
        self.assertEqual(len(cells), 2 * 2 * 2 * 2)
        self.assertEqual(len(set(cells)), len(cells))
        self.assertEqual({c.hash_seed for c in cells}, {"0", "4242"})
        self.assertEqual({c.time_zone for c in cells}, {"UTC", "Pacific/Kiritimati"})
        self.assertEqual({c.working_dir for c in cells}, {"", "code"})

    def test_gate_reports_each_kind_of_failure(self) -> None:
        cell = clean_room.Cell("py", "0", "UTC", "")
        good = clean_room.CellResult(cell, 0, 1.0, "aa", 0, False)
        self.assertEqual(clean_room.gate_problems([good, good]), [])
        for bad, text in ((clean_room.CellResult(cell, 1, 1.0, "aa", 0, False), "exit 1"),
                          (clean_room.CellResult(cell, 0, 1.0, "aa", 0, True), "traceback"),
                          (clean_room.CellResult(cell, 0, 1.0, "aa", 3, False), "3 cache misses"),
                          (clean_room.CellResult(cell, 0, 99.0, "aa", 0, False), "over the 30 s gate"),
                          (clean_room.CellResult(cell, 0, 1.0, "bb", 0, False), "differs")):
            self.assertTrue(any(text in p for p in clean_room.gate_problems([good, bad])), text)


class MatrixRunTests(Scratch):
    def test_a_reproducible_project_passes_every_cell(self) -> None:
        make_zip(self.archive)
        code, report, _err = self.run_cli()
        self.assertEqual((code, "Problems: 0" in report), (0, True), report)
        rows = [line for line in report.splitlines() if line.startswith("| ") and ("UTC" in line or "Kiritimati" in line)]
        self.assertEqual(len(rows), 8)

    def test_the_suite_runs_with_and_without_the_dataset(self) -> None:
        make_zip(self.archive)
        code, report, _err = self.run_cli()
        self.assertEqual(code, 0, report)
        self.assertIn("with dataset/: exit 0", report)
        self.assertIn("without dataset/: exit 0", report)
        self.assertIn("skipped=1", report)

    def test_a_suite_that_fails_without_the_dataset_is_caught(self) -> None:
        make_zip(self.archive, skips=False)
        code, report, _err = self.run_cli()
        self.assertEqual(code, clean_room.EXIT_GATE)
        self.assertIn("test suite without dataset/: exit 1", report)
        self.assertNotIn("test suite with dataset/", report)

    def test_a_run_that_leaks_the_hash_seed_is_caught(self) -> None:
        make_zip(self.archive, leak=True)
        code, report, _err = self.run_cli()
        self.assertEqual(code, clean_room.EXIT_GATE)
        self.assertIn("output.csv differs between cells", report)

    def test_cache_misses_fail_the_gate(self) -> None:
        make_zip(self.archive, misses=4)
        code, report, _err = self.run_cli()
        self.assertEqual(code, clean_room.EXIT_GATE)
        self.assertIn("4 cache misses", report)

    def test_a_failing_readme_command_fails_the_gate(self) -> None:
        make_zip(self.archive, check="import sys\nsys.exit(3)\n")
        code, report, _err = self.run_cli()
        self.assertEqual(code, clean_room.EXIT_GATE)
        self.assertIn("README command failed (exit 3)", report)

    def test_the_dataset_is_hidden_for_the_missing_dataset_check_and_restored(self) -> None:
        make_zip(self.archive)
        with tempfile.TemporaryDirectory() as scratch:
            unpacked = Path(scratch) / "tree"
            clean_room.unzip(self.archive, unpacked)
            unpacked.joinpath("dataset").mkdir()
            (unpacked / "dataset" / "data.txt").write_text("answer\n", encoding="utf-8")
            problems = clean_room.check_without_dataset(unpacked, ["python3", "code/main.py"], sys.executable, False)
            self.assertEqual(problems, [])
            self.assertTrue((unpacked / "dataset" / "data.txt").is_file())

    def test_a_pipeline_that_ignores_a_missing_dataset_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            unpacked = Path(scratch)
            (unpacked / "code").mkdir()
            (unpacked / "code" / "main.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            problems = clean_room.check_without_dataset(unpacked, ["python3", "code/main.py"], sys.executable, False)
        self.assertEqual(len(problems), 2)  # wrong exit code and a traceback

    def test_unusable_archive_or_readme_is_an_input_error(self) -> None:
        self.archive.write_bytes(b"not a zip")
        self.assertEqual(self.run_cli()[0], clean_room.EXIT_INPUT)
        make_zip(self.archive, readme="# nothing\n")
        self.assertEqual(self.run_cli()[0], clean_room.EXIT_INPUT)

    def test_another_interpreter_can_be_added(self) -> None:
        make_zip(self.archive)
        code, report, _err = self.run_cli("--python", sys.executable)
        self.assertEqual(code, 0, report)

    def test_cache_misses_are_read_from_the_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root: Path = Path(scratch)
            self.assertIsNone(clean_room.cache_misses(root))
            (root / "diagnostics").mkdir()
            (root / "diagnostics" / "diagnostics.md").write_text(
                "- Media extraction notes: 15\n- Intent requests without a model verdict: 550\n", encoding="utf-8")
            self.assertEqual(clean_room.cache_misses(root), 565)


if __name__ == "__main__":
    unittest.main()
