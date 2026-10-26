"""Tests of the release-process tooling; run from the repository root.

    python3 -m unittest discover -s devtools/tests -t .

The solver package lives in `code/`, so that directory joins `sys.path` here, before any test module imports it.
"""
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[2] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
