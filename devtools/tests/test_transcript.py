"""The root transcript (log.txt) passes the transcript linter (AGENTS section 5)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_LOG = REPO_ROOT / "devtools" / "check_log.py"
TRANSCRIPT = REPO_ROOT / "log.txt"


class TranscriptTests(unittest.TestCase):
    def test_transcript_lint_exits_zero(self) -> None:
        if not TRANSCRIPT.exists():
            self.skipTest("log.txt is not part of this checkout")
        done = subprocess.run([sys.executable, str(CHECK_LOG), str(TRANSCRIPT)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
