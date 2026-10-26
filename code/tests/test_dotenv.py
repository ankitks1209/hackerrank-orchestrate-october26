"""Tests for the `.env` fallback of `Config.from_env` (SPEC N4).

Every test uses a temporary `.env` with a fake key; none reads the repo-root `.env`.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ghostaudit import config
from ghostaudit.config import API_KEY_ENV, DOTENV_PATH, REPO_ROOT, Config, read_dotenv

FAKE_KEY = "test-key-not-real"
OTHER_KEY = "other-key-not-real"


class DotenvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / ".env"

    def write(self, text: str) -> Path:
        self.path.write_text(text, encoding="utf-8")
        return self.path

    def test_key_is_read_from_the_file_when_the_environment_lacks_it(self) -> None:
        cfg = Config.from_env({}, dotenv=self.write("%s=%s\n" % (API_KEY_ENV, FAKE_KEY)))
        self.assertEqual(cfg.api_key.reveal(), FAKE_KEY)  # type: ignore[union-attr]

    def test_environment_wins_over_the_file(self) -> None:
        path = self.write("%s=%s\n" % (API_KEY_ENV, FAKE_KEY))
        cfg = Config.from_env({API_KEY_ENV: OTHER_KEY}, dotenv=path)
        self.assertEqual(cfg.api_key.reveal(), OTHER_KEY)  # type: ignore[union-attr]

    def test_missing_file_gives_no_key(self) -> None:
        self.assertIsNone(Config.from_env({}, dotenv=self.path).api_key)

    def test_explicit_environment_ignores_the_repo_dotenv(self) -> None:
        self.assertIsNone(Config.from_env({}).api_key)

    def test_comments_export_prefix_and_quotes(self) -> None:
        path = self.write(
            "# comment\n\nexport A = 'one'\nB=\"two\"\nC=three=3\nnot a pair\n=empty\n"
        )
        self.assertEqual(read_dotenv(path), {"A": "one", "B": "two", "C": "three=3"})

    def test_key_never_appears_in_repr(self) -> None:
        cfg = Config.from_env({}, dotenv=self.write("export %s=\"%s\"\n" % (API_KEY_ENV, FAKE_KEY)))
        self.assertNotIn(FAKE_KEY, repr(cfg))
        self.assertNotIn(FAKE_KEY, repr(cfg.api_key))

    def test_default_path_is_the_repo_root(self) -> None:
        self.assertEqual(DOTENV_PATH, REPO_ROOT / ".env")
        self.assertIs(config.DOTENV_PATH, DOTENV_PATH)

    def test_repo_dotenv_is_git_ignored(self) -> None:
        if not (REPO_ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(DOTENV_PATH)], cwd=str(REPO_ROOT),
            capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
