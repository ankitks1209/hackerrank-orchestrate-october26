"""Static-isolation and data-consistency checks (SPEC N1, N3, N4, N5, L8).

The source checks read `code/ghostaudit/**` and `code/main.py` with `ast` and `tokenize`
(tests and tools are exempt) and cover:

* no path to `solution/` and no mention of `sample_output` in executable code;
* the environment is read only in `config.py`;
* no numeric time-window literal outside `config.py`;
* no `print(` calls (the package logs);
* no id arithmetic on `user_` / `case_` numbers (SPEC L8);
* no literal evaluation case id (`case_33` and above), user id or resource id;
* no sampling parameters (`temperature`, `top_p`, `top_k`; SPEC N1);
* no dataset email address anywhere in a source file, and no ISO timestamp literal in an
  executable string; resource id literals include the
  `activity_`, `evidence_` and `audit_` prefixes.

Docstrings and comments may cite SPEC conventions such as `user_01..user_10`, so the
user and resource id checks look at executable string constants only; the case id check
reads the whole file. Each checker has a negative fixture built from fragments, so this
file itself carries no evaluation id. Repo-wide checks: tests never run `main.py`
without `--out` and `--diag` and never name an evaluation case id. Data checks: activity
and evidence agree with `policy.SYSTEM_BY_PREFIX` and the policy rules 04, 08 and 11 can
never fire.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import FrozenSet, Iterator, List, Set, Tuple

from ghostaudit.activity import ActKind, classify_activity
from ghostaudit.config import REPO_ROOT, Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.index import build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.policy import DEFAULT_CATEGORY_BY_SYSTEM, SYSTEM_BY_PREFIX, system_for
from tests.dataset_guard import needs_dataset

CODE_DIR = REPO_ROOT / "code"
PACKAGE_DIR = CODE_DIR / "ghostaudit"
TESTS_DIR = CODE_DIR / "tests"

CONFIG_NAME = "config.py"
FIRST_EVAL_CASE = 33  # sample ids are case_1..case_32 (AGENTS 6.1: 32 public requests)
ENV_NAMES = frozenset({"environ", "environb", "getenv"})
TIME_UNIT_NAMES = frozenset({"MINUTE", "HOUR"})
TIME_LITERALS = frozenset({60, 3600, 86400})
SAMPLING_PARAMS = frozenset({"temperature", "top_p", "top_k"})
UNSAMPLED_CATEGORIES = {  # policy rules that no resource can reach (rule_04, rule_08, rule_11)
    "rule_04": "CACHE_ENTRY",
    "rule_08": "PRODUCT_TELEMETRY",
    "rule_11": "EMAIL_DELIVERY_LOG",
}

SOLUTION_PATH = re.compile(r"(^|[\\/])solution([\\/]|$)")
CASE_ID = re.compile(r"case_(\d+)")
USER_ID = re.compile(r"\buser_\d+")
LOG_ID_PREFIXES = ("activity_", "evidence_", "audit_", "cache_")  # activity, manifest, audit-log, cache ids
RESOURCE_ID = re.compile(
    r"\b(?:%s)\d+" % "|".join(re.escape(prefix) for prefix in tuple(SYSTEM_BY_PREFIX) + LOG_ID_PREFIXES)
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ISO_TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d")
ID_NUMBER_CAPTURE = re.compile(r"\b(?:user|case)_\(")
# No id is parsed or derived from another: the `account_00N` fallback (SPEC L12.3, Q2) was withdrawn.
ID_NUMBER_ALLOWED: Set[Tuple[str, str]] = set()


def source_files() -> List[Path]:
    """Every checked source file, in a fixed order."""
    files = sorted(path for path in PACKAGE_DIR.rglob("*.py") if "__pycache__" not in path.parts)
    return files + [CODE_DIR / "main.py"]


def _docstring_nodes(tree: ast.AST) -> Set[int]:
    """`id()` of every docstring constant, so executable strings can be told apart."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _executable_strings(tree: ast.AST) -> Iterator[str]:
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.value


def _identifiers(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.alias):
            yield node.name
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg


def _is_number(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
        and not isinstance(node.value, bool)


def _is_int_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "int"


def dataset_emails() -> FrozenSet[str]:
    """Every email address in the identity snapshot, the audit log and the requests (lower case)."""
    reader = DatasetReader(Config().dataset_dir)
    found = {identity.email.lower() for identity in reader.identities()}
    for row in reader.audit_log():
        found.update(value.lower() for value in (row.old_value, row.new_value) if "@" in value)
    found.update(request.email.lower() for request in reader.requests())
    return frozenset(found)


def violations(source: str, name: str, emails: FrozenSet[str] = frozenset()) -> List[str]:
    """Rule violations of one source file; `name` is its file name (`config.py` is the exempt home).

    `emails` are the dataset addresses that must not occur anywhere in the file, comments included.
    """
    tree = ast.parse(source)
    strings = list(_executable_strings(tree))
    found: List[str] = []
    if any(SOLUTION_PATH.search(text) for text in strings) or "solution" in set(_module_names(tree)):
        found.append("solution/ is referenced")
    if any("sample_output" in text for text in strings) or any("sample_output" in n for n in _identifiers(tree)):
        found.append("sample_output is referenced")
    if name != CONFIG_NAME and ENV_NAMES & set(_identifiers(tree)):
        found.append("environment read outside config.py")
    if name != CONFIG_NAME:
        found += _window_literals(tree)
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
           for n in ast.walk(tree)):
        found.append("print() call")
    found += _id_arithmetic(tree, strings, name)
    found += _literal_ids(source, strings)
    found += ["dataset email %r" % mail for mail in sorted({m.lower() for m in EMAIL.findall(source)} & emails)]
    found += ["ISO timestamp literal %r" % text for text in strings if ISO_TIMESTAMP.search(text)]
    if SAMPLING_PARAMS & (set(_identifiers(tree)) | set(strings)):
        found.append("sampling parameter")
    return found


def _module_names(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0]


def _window_literals(tree: ast.AST) -> List[str]:
    found: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            pair = (node.left, node.right)
            if any(_is_number(a) and isinstance(b, ast.Name) and b.id in TIME_UNIT_NAMES
                   for a, b in (pair, pair[::-1])):
                found.append("numeric window literal")
        elif _is_number(node) and node.value in TIME_LITERALS:
            found.append("time constant %s" % node.value)
        elif isinstance(node, ast.Call) and any(_is_number(a) for a in node.args + [k.value for k in node.keywords]) \
                and isinstance(node.func, ast.Name) and node.func.id == "timedelta":
            found.append("timedelta literal")
    return found


def _id_arithmetic(tree: ast.AST, strings: List[str], name: str) -> List[str]:
    found: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)) \
                and (_is_int_call(node.left) or _is_int_call(node.right)):
            found.append("arithmetic on an int() value")
    for text in strings:
        if ID_NUMBER_CAPTURE.search(text) and (name, text) not in ID_NUMBER_ALLOWED:
            found.append("id number captured from %r" % text)
    return found


def _literal_ids(source: str, strings: List[str]) -> List[str]:
    found = ["eval case id case_%s" % number for number in CASE_ID.findall(source)
             if int(number) >= FIRST_EVAL_CASE]
    for text in strings:
        if USER_ID.search(text):
            found.append("user id literal %r" % text)
        if RESOURCE_ID.search(text):
            found.append("resource id literal %r" % text)
    return found


def main_calls_without_out(source: str) -> bool:
    """True when a test source runs the CLI (`main.py`, `import main`, `ghostaudit.cli`) without both paths."""
    runs_cli = bool(re.search(r"(?m)^\s*(import main\b|from main import|from ghostaudit import cli\b|from ghostaudit.cli import)", source)) \
        or ("main.py" in source and "subprocess" in source)
    return runs_cli and not ("--out" in source and "--diag" in source)


class SourceRuleTests(unittest.TestCase):
    """The real package and CLI satisfy every rule."""

    @needs_dataset
    def test_package_and_cli_have_no_violations(self) -> None:
        files = source_files()
        self.assertGreater(len(files), 20)
        emails = dataset_emails()
        self.assertGreater(len(emails), 800)
        report = {path.relative_to(CODE_DIR).as_posix(): violations(path.read_text(encoding="utf-8"), path.name, emails)
                  for path in files}
        self.assertEqual({key: found for key, found in report.items() if found}, {})

    def test_environment_is_read_in_config_only(self) -> None:
        readers = [path.name for path in source_files()
                   if ENV_NAMES & set(_identifiers(ast.parse(path.read_text(encoding="utf-8"))))]
        self.assertEqual(readers, [CONFIG_NAME])


class CheckerNegativeTests(unittest.TestCase):
    """Each rule fires on a synthetic offender, so the clean result above is meaningful."""

    ID_NUMBER = 99  # built at run time: this file carries no evaluation id literal

    def check(self, source: str, name: str = "module.py") -> List[str]:
        return violations(source, name)

    def test_solution_reference(self) -> None:
        self.assertTrue(self.check('p = root / "solution" / "x"\n'))
        self.assertTrue(self.check("import solution\n"))
        self.assertTrue(self.check("open('solution/notes.md')\n"))
        self.assertEqual(self.check('"""Never reads solution/ files."""\n'), [])

    def test_sample_output_reference(self) -> None:
        self.assertTrue(self.check('NAME = "sample_output.csv"\n'))
        self.assertTrue(self.check("sample_output = 1\n"))

    def test_environment_outside_config(self) -> None:
        self.assertTrue(self.check("import os\nx = os.environ['A']\n"))
        self.assertTrue(self.check("import os\nx = os.getenv('A')\n"))
        self.assertTrue(self.check("from os import environ\n"))
        self.assertEqual(self.check("import os\nx = os.environ['A']\n", CONFIG_NAME), [])

    def test_window_literals(self) -> None:
        self.assertTrue(self.check("w = (-30 * MINUTE, 5 * HOUR)\n"))
        self.assertTrue(self.check("w = 3600\n"))
        self.assertTrue(self.check("w = timedelta(minutes=5)\n"))
        self.assertEqual(self.check("w = (-30 * MINUTE, 5 * HOUR)\n", CONFIG_NAME), [])
        self.assertEqual(self.check("w = a * MINUTE\n"), [])

    def test_print_call(self) -> None:
        self.assertTrue(self.check("print('x')\n"))
        self.assertEqual(self.check("log.info('x')\n"), [])

    def test_id_arithmetic(self) -> None:
        self.assertTrue(self.check("n = int(m.group(1)) - 2\n"))
        self.assertTrue(self.check("p = re.compile(r'case_(\\d+)')\n"))
        self.assertTrue(self.check("p = re.compile(r'user_(\\d+)')\n", "handcrafted.py"))
        self.assertTrue(self.check("p = re.compile(r'user_(\\d+)')\n", "other.py"))

    def test_literal_eval_case_id(self) -> None:
        self.assertTrue(self.check("# see case_%d\n" % self.ID_NUMBER))
        self.assertTrue(self.check("x = 'case_%d'\n" % FIRST_EVAL_CASE))
        self.assertEqual(self.check("# sample case_%d\n" % (FIRST_EVAL_CASE - 1)), [])

    def test_literal_user_and_resource_ids(self) -> None:
        self.assertTrue(self.check("u = 'user_%d'\n" % self.ID_NUMBER))
        self.assertTrue(self.check("r = 'account_%d'\n" % self.ID_NUMBER))
        self.assertTrue(self.check("r = 'data_flow_%d'\n" % self.ID_NUMBER))
        self.assertEqual(self.check('"""Convention user_%02d."""\n' % 1), [])
        self.assertEqual(self.check("r = 'account_'\nu = 'user_'\n"), [])

    def test_log_and_manifest_id_literals(self) -> None:
        self.assertTrue(self.check("a = 'activity_%d'\n" % self.ID_NUMBER))
        self.assertTrue(self.check("f = 'evidence_%d'\n" % self.ID_NUMBER))
        self.assertTrue(self.check("r = 'audit_%d'\n" % self.ID_NUMBER))
        self.assertEqual(self.check("pattern = 'evidence_'\n"), [])

    def test_dataset_email_and_timestamp_literals(self) -> None:
        mail = "someone.synthetic@example.test"
        self.assertTrue(violations("# written by %s\n" % mail.upper(), "module.py", frozenset({mail})))
        self.assertEqual(violations("# written by %s\n" % mail, "module.py"), [])
        self.assertTrue(violations("t = '2026-01-02T03:04:05Z'\n", "module.py"))
        self.assertEqual(violations('"""Example 2026-01-02T03:04:05Z."""\n', "module.py"), [])
        self.assertEqual(violations("fmt = '%Y-%m-%dT%H:%M:%SZ'\n", "module.py"), [])

    def test_sampling_parameters(self) -> None:
        self.assertTrue(self.check("client.create(temperature=0)\n"))
        self.assertTrue(self.check("body = {'top_p': 1}\n"))

    def test_main_without_out(self) -> None:
        self.assertTrue(main_calls_without_out("import main\nmain.main(['--llm', 'off'])\n"))
        self.assertTrue(main_calls_without_out("from ghostaudit import cli\ncli.main(['--llm', 'off'])\n"))
        self.assertTrue(main_calls_without_out("import subprocess\nsubprocess.run(['code/main.py'])\n"))
        self.assertFalse(main_calls_without_out("import main\nargs = ['--out', 'a', '--diag', 'b']\n"))
        self.assertFalse(main_calls_without_out("x = 1\n"))


class ImportPathRuleTests(unittest.TestCase):
    """Nothing under `code/` edits `sys.path`: the package is found as a script directory or an install."""

    def test_no_module_edits_the_import_path(self) -> None:
        own = Path(__file__).resolve()
        offenders = []
        for path in sorted(CODE_DIR.rglob("*.py")):
            if path.resolve() == own or ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "path" \
                        and isinstance(node.value, ast.Name) and node.value.id == "sys":
                    offenders.append("%s:%d" % (path.relative_to(CODE_DIR).as_posix(), node.lineno))
        self.assertEqual(offenders, [])


class TestSuiteRuleTests(unittest.TestCase):
    def test_every_test_that_runs_main_passes_out_and_diag(self) -> None:
        own = Path(__file__).resolve()
        offenders = [path.name for path in sorted(TESTS_DIR.glob("*.py"))
                     if path.resolve() != own and main_calls_without_out(path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_tests_name_only_sample_case_ids(self) -> None:
        offenders = sorted({
            "%s:case_%s" % (path.name, number)
            for path in TESTS_DIR.glob("*.py") if path.resolve() != Path(__file__).resolve()
            for number in CASE_ID.findall(path.read_text(encoding="utf-8"))
            if int(number) >= FIRST_EVAL_CASE
        })
        self.assertEqual(offenders, [])


@needs_dataset
class DataConsistencyTests(unittest.TestCase):
    """The participant data agrees with the system table, and unreachable rules stay unreachable."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(Config().dataset_dir)
        cls.rules = reader.rules()
        cls.acts = classify_activity(reader.activity())
        identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(reader.manifest(), identity, {}, cls.acts)

    def test_activity_system_ids_agree_with_prefixes(self) -> None:
        conflicts = [act.activity_id for act in self.acts
                     if act.kind is not ActKind.NOISE and act.system_id != system_for(act.resource_id)]
        self.assertEqual(conflicts, [])

    def test_evidence_system_ids_agree_with_prefixes(self) -> None:
        self.assertGreater(len(self.index.observations), 0)
        conflicts = sorted({(obs.file_id, obs.resource_id) for obs in self.index.observations
                            if obs.system_id != system_for(obs.resource_id)})
        self.assertEqual(conflicts, [])

    def test_unreachable_rules_never_fire(self) -> None:
        by_id = {row.rule_id: row.data_category for row in self.rules}
        self.assertEqual({rid: by_id.get(rid) for rid in UNSAMPLED_CATEGORIES}, UNSAMPLED_CATEGORIES)
        dead = set(UNSAMPLED_CATEGORIES.values())
        self.assertFalse(dead & set(DEFAULT_CATEGORY_BY_SYSTEM.values()))
        self.assertFalse(dead & {obs.category for obs in self.index.observations})


if __name__ == "__main__":
    unittest.main()
