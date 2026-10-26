"""Reproducible `code.zip` packager with listing and content checks.

Builds the submission archive with the standard library only: entries sorted by path, fixed
1980 timestamps, fixed Unix permissions, fixed compression, no directory entries. Two builds of
the same tree are byte-identical. The archive holds the root files the README refers to
(`README.md`, `requirements.txt` with the live SDK pin, `.env.example` when present), the whole
`code/` tree without caches, and a zip-root `evaluation/` copy of the two reports. The checks
read the built archive, not the source tree:

* presence of the README, the requirements pin, the entry point, the solver, scorer, custom cases, report renderer and packager, the docs, the prompts, the
  response cache and both reports in both places (the two copies must be byte-identical);
* absence of `dataset/`, `solution/`, `plan/`, `devtools/` (release tooling), `log.txt`, `.env`, bytecode, pickles, virtual
  environments, caches, `.DS_Store` and any nested archive;
* a scan of the shipped text for absolute home paths, caller-supplied forbidden strings,
  dataset emails and phones in Markdown, and API-key shapes.

    python3 -m tools.build_zip --root .. --out ../code.zip [--manifest manifest.json]   (run from code/)
        [--dataset ../dataset] [--forbid TEXT ...] [--metrics-dir DIR]

With `--metrics-dir` the packager also runs `python -m tools.render_reports --check` on that directory, so an
archive whose report tables have drifted from a fresh run is never built (the zip is removed).
The response cache holds the media facts the model read from the 15 images and PDFs. They are stored
redacted (emails and phones as sha256 digests, no names; DECISIONS D25), so with `--dataset` the build fails
when any cache file still holds a dataset email or phone.

Exit codes: 0 built and clean; 1 built but a check failed (the zip is removed); 2 unusable input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_INPUT = 2

README = "README.md"
REQUIREMENTS = "requirements.txt"
ENV_EXAMPLE = ".env.example"
ROOT_FILES = (README, REQUIREMENTS, ENV_EXAMPLE)  # shipped when present; README and pin are required
CODE_DIR = "code"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16  # regular file, rw-r--r--
UNIX = 3
COMPRESS_LEVEL = 9
EVALUATION_REPORTS = ("evaluation_report.md", "usage_report.md")
REPORT_DIR = "evaluation"
JUNK_DIRS = frozenset({
    "__pycache__", ".venv", "venv", ".venv-live", "node_modules", ".git", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", "diagnostics",
})
JUNK_SUFFIXES = frozenset({".pyc", ".pyo", ".pkl"})
JUNK_NAMES = frozenset({".DS_Store"})
FORBIDDEN_DIRS = frozenset({"dataset", "solution", "plan", "devtools"})
# Release-process tooling lives in the unshipped repo-root `devtools/`; none of it may reappear under `code/`.
RELEASE_TOOLING = (
    "code/evaluation/audit/", "code/evaluation/confidence.py", "code/evaluation/RELEASE_",
    "code/tools/clean_room.py", "code/tools/release_gate.py", "code/tools/append_log.py", "code/tools/check_log.py",
)
FORBIDDEN_NAMES = frozenset({"log.txt", ".env"})
ARCHIVE_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz")
TEXT_SUFFIXES = frozenset({".md", ".py", ".txt", ".toml", ".cfg", ".json", ".csv", ".ini", ".yml", ".yaml"})
HOME_PATH = "/" + "Users" + "/"  # built from parts: this file must pass its own scan
KEY_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)api[_-]?key[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']"),
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+[\d ()\-]{8,}\d")
NON_DIGIT = re.compile(r"\D")
MIN_PHONE_DIGITS = 8
# (description, matcher over the sorted archive names)
REQUIRED = (
    ("README.md", lambda names: README in names),
    ("requirements.txt", lambda names: REQUIREMENTS in names),
    ("code/main.py", lambda names: "code/main.py" in names),
    ("code/ghostaudit/pipeline.py", lambda names: "code/ghostaudit/pipeline.py" in names),
    ("code/evaluation/scoring.py", lambda names: "code/evaluation/scoring.py" in names),
    ("code/evaluation/custom_cases.py", lambda names: "code/evaluation/custom_cases.py" in names),
    ("code/tools/render_reports.py", lambda names: "code/tools/render_reports.py" in names),
    ("code/tools/build_zip.py", lambda names: "code/tools/build_zip.py" in names),
    ("code/evaluation/evaluation_report.md", lambda names: "code/evaluation/evaluation_report.md" in names),
    ("code/evaluation/usage_report.md", lambda names: "code/evaluation/usage_report.md" in names),
    ("evaluation/evaluation_report.md", lambda names: "evaluation/evaluation_report.md" in names),
    ("evaluation/usage_report.md", lambda names: "evaluation/usage_report.md" in names),
    ("code/docs/*.md", lambda names: any(re.fullmatch(r"code/docs/[^/]+\.md", n) for n in names)),
    ("code/ghostaudit/llm/prompts/*.md",
     lambda names: any(re.fullmatch(r"code/ghostaudit/llm/prompts/[^/]+\.md", n) for n in names)),
    ("code/ghostaudit/cache/*.json",
     lambda names: any(re.fullmatch(r"code/ghostaudit/cache/[^/]+\.json", n) for n in names)),
)


def _is_junk(parts: Sequence[str]) -> bool:
    name = parts[-1]
    return (any(part in JUNK_DIRS for part in parts[:-1]) or name in JUNK_NAMES
            or Path(name).suffix in JUNK_SUFFIXES)


def collect(root: Path) -> Dict[str, bytes]:
    """Archive path -> bytes for the root files, the `code/` tree and the zip-root report copies."""
    files: Dict[str, bytes] = {}
    sources = [root / name for name in ROOT_FILES]
    if (root / CODE_DIR).is_dir():
        sources += sorted((root / CODE_DIR).rglob("*"))
    for path in sources:
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if not _is_junk(relative.parts):
            files[relative.as_posix()] = path.read_bytes()
    for name in EVALUATION_REPORTS:
        source = "%s/%s/%s" % (CODE_DIR, REPORT_DIR, name)
        if source in files:
            files["%s/%s" % (REPORT_DIR, name)] = files[source]
    return files


def write_zip(files: Dict[str, bytes], target: Path) -> None:
    """Write `files` as a deterministic archive: sorted, fixed time, fixed mode and compression."""
    with zipfile.ZipFile(str(target), "w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.create_system = UNIX
            info.external_attr = FILE_MODE
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=COMPRESS_LEVEL)


def manifest(files: Dict[str, bytes]) -> List[Tuple[str, str]]:
    """(path, sha256) for every entry, sorted by path."""
    return [(name, hashlib.sha256(files[name]).hexdigest()) for name in sorted(files)]


def content_hash(entries: Sequence[Tuple[str, str]]) -> str:
    """One hash over the manifest; equal trees give equal hashes."""
    text = "".join("%s\0%s\n" % entry for entry in entries)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_listing(names: Sequence[str]) -> List[str]:
    """Presence and absence problems of an archive listing."""
    problems = ["missing: %s" % label for label, present in REQUIRED if not present(frozenset(names))]
    for name in names:
        parts = name.split("/")
        base = parts[-1]
        if any(part in FORBIDDEN_DIRS for part in parts[:-1]):
            problems.append("forbidden directory: %s" % name)
        if name.startswith(RELEASE_TOOLING):
            problems.append("release tooling must not ship: %s" % name)
        if base in FORBIDDEN_NAMES or (base.startswith(".env") and base != ".env.example"):
            problems.append("forbidden file: %s" % name)
        if _is_junk(parts):
            problems.append("build junk: %s" % name)
        if base.lower().endswith(ARCHIVE_SUFFIXES):
            problems.append("nested archive: %s" % name)
    return problems


def check_reports(files: Dict[str, bytes]) -> List[str]:
    """The zip-root report copies equal the ones under `code/evaluation/`, byte for byte."""
    problems = []
    for name in EVALUATION_REPORTS:
        inner, outer = files.get("%s/%s/%s" % (CODE_DIR, REPORT_DIR, name)), files.get("%s/%s" % (REPORT_DIR, name))
        if inner is None or outer is None:
            continue
        if inner != outer:
            problems.append("report copies differ: %s" % name)
        if not inner.strip():
            problems.append("empty report: %s" % name)
    return problems


def dataset_identifiers(dataset: Optional[Path]) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(emails, phone digit strings) of the identity snapshot; empty when no dataset is given."""
    if dataset is None or not (dataset / "user_identities.csv").is_file():
        return frozenset(), frozenset()
    with (dataset / "user_identities.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    emails = frozenset(row["email"].lower() for row in rows)
    phones = frozenset(NON_DIGIT.sub("", row["phone"]) for row in rows if row["phone"])
    return emails, phones


def check_text(
    files: Dict[str, bytes], forbidden: Sequence[str], emails: FrozenSet[str], phones: FrozenSet[str]
) -> List[str]:
    """Home paths, forbidden strings and key shapes in shipped text; dataset identifiers in Markdown."""
    problems: List[str] = []
    for name in sorted(files):
        if Path(name).suffix not in TEXT_SUFFIXES:
            continue
        text = files[name].decode("utf-8", errors="replace")
        if HOME_PATH in text:
            problems.append("%s: absolute home path" % name)
        problems += ["%s: forbidden string %r" % (name, item) for item in forbidden if item.lower() in text.lower()]
        problems += ["%s: API key shape" % name for pattern in KEY_PATTERNS if pattern.search(text)]
        if name.endswith(".md"):
            problems += ["%s: dataset email" % name for mail in sorted(set(m.lower() for m in EMAIL.findall(text)) & emails)]
            found = {NON_DIGIT.sub("", p) for p in PHONE.findall(text)}
            problems += ["%s: dataset phone" % name for digits in sorted(found & phones)
                         if len(digits) >= MIN_PHONE_DIGITS]
    return problems


def check_reports_current(metrics_dir: Optional[Path]) -> List[str]:
    """Run `python -m tools.render_reports --check` on `metrics_dir`; a drifted report table is a build problem."""
    if metrics_dir is None:
        return []
    code_dir = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-m", "tools.render_reports", "--metrics-dir", str(metrics_dir.resolve()), "--check"],
                          cwd=str(code_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    if done.returncode == 0:
        return []
    first = [line.strip() for line in done.stdout.splitlines() if line.strip()][:4]
    return ["reports drifted from a fresh run (render_reports --check exited %d): %s" % (done.returncode, " | ".join(first))]


def check_cache_identifiers(files: Dict[str, bytes], emails: FrozenSet[str], phones: FrozenSet[str]) -> List[str]:
    """Dataset emails and phones inside the shipped response cache; the cache holds digests only (D25)."""
    problems: List[str] = []
    for name in sorted(files):
        if not name.startswith("%s/ghostaudit/cache/" % CODE_DIR):
            continue
        text = files[name].decode("utf-8", errors="replace")
        found = {mail.lower() for mail in EMAIL.findall(text)} & emails
        digits = {NON_DIGIT.sub("", number) for number in PHONE.findall(text)} & phones
        if found or digits:
            problems.append("%s: dataset email or phone in the response cache" % name)
    return problems


def build(root: Path, out: Path, forbidden: Sequence[str] = (), dataset: Optional[Path] = None,
          metrics_dir: Optional[Path] = None) -> Tuple[List[str], str]:
    """Build `out` from `root`; returns (problems, content hash). The archive is removed on problems."""
    files = collect(root)
    write_zip(files, out)
    with zipfile.ZipFile(str(out)) as archive:
        names = archive.namelist()
    emails, phones = dataset_identifiers(dataset)
    problems = (check_listing(names) + check_reports(files) + check_text(files, forbidden, emails, phones)
                + check_cache_identifiers(files, emails, phones) + check_reports_current(metrics_dir))
    if problems:
        out.unlink()
    return problems, content_hash(manifest(files))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: .)")
    parser.add_argument("--out", type=Path, default=Path("code.zip"), help="archive to write")
    parser.add_argument("--manifest", type=Path, help="write the (path, sha256) manifest and content hash here")
    parser.add_argument("--dataset", type=Path, help="dataset/ directory whose emails and phones must not ship in Markdown")
    parser.add_argument("--forbid", action="append", default=[], metavar="TEXT",
                        help="string that must not appear in shipped text (repeatable)")
    parser.add_argument("--metrics-dir", type=Path,
                        help="metrics directory of render_reports.py; the build fails when its --check fails")
    args = parser.parse_args(argv)
    if not (args.root / README).is_file():
        sys.stderr.write("cannot build: %s has no %s\n" % (args.root, README))
        return EXIT_INPUT
    problems, digest = build(args.root, args.out, args.forbid, args.dataset, args.metrics_dir)
    for problem in problems:
        sys.stderr.write("check failed: %s\n" % problem)
    if problems:
        return EXIT_CHECK_FAILED
    if args.manifest:
        entries = manifest(collect(args.root))
        args.manifest.write_text(json.dumps({"content_hash": digest, "files": entries}, indent=2) + "\n",
                                 encoding="utf-8")
    sys.stdout.write("built %s: content hash %s\n" % (args.out, digest))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
