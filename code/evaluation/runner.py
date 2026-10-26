"""Run the solver CLI into a scratch directory, for the evaluation tools (SPEC A2).

The scorer and the label-free verifier both need fresh predictions, never a file left
over from an earlier run, so each runs `code/main.py` itself, offline unless told otherwise.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

CODE_DIR = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("ghostaudit.evaluation")
STDERR_TAIL_CHARS = 2000


def run_pipeline(scratch: Path, llm_mode: Optional[str] = None) -> Tuple[Path, Path, Path]:
    """Run `code/main.py --include-samples` into `scratch`; return (output, samples, diagnostics) paths."""
    out, samples, diag = scratch / "output.csv", scratch / "samples.csv", scratch / "diag"
    command = [sys.executable, str(CODE_DIR / "main.py"), "--include-samples", "--samples-out",
               str(samples), "--out", str(out), "--diag", str(diag)]
    if llm_mode:
        command += ["--llm", llm_mode]
    LOG.info("running the pipeline: %s", " ".join(command))
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        LOG.error("pipeline failed (exit %d): %s", error.returncode, (error.stderr or "")[-STDERR_TAIL_CHARS:])
        raise
    return out, samples, diag / "diagnostics.md"
