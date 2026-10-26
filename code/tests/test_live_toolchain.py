"""Live LLM toolchain checks (SPEC N1, N5).

The pin test runs everywhere: requirements.txt, the config constant and the
usage report must name the same SDK version. The request-construction test
runs the real SDK against an in-memory HTTP transport, so it needs Python >=
3.10 with `anthropic` installed (the `.venv-live` environment). The live smoke
call additionally needs ANTHROPIC_API_KEY. The cross-interpreter test runs the
full pipeline under the current interpreter and `.venv-live` and compares the
output bytes. It is slow, so it is opt-in (set GHOSTAUDIT_CROSS_INTERPRETER=1)
and also needs code/main.py; the clean-room matrix covers the same
comparison as part of its run.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from ghostaudit.config import (
    DEFAULT_PRICES,
    EVAL_REQUEST_COUNT,
    LIVE_SDK_REQUIREMENT,
    MIN_LIVE_PYTHON,
    REPO_ROOT,
    Config,
)
from ghostaudit.llm.client import AnthropicClient, LLMRequest, build_params
from ghostaudit.llm.usage import UsageMeter, snapshot
from tools import render_reports

SAMPLING_PARAMS = ("temperature", "top_p", "top_k")
SMOKE_MODEL = DEFAULT_PRICES[-1].model
SMOKE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
SDK_READY = sys.version_info >= MIN_LIVE_PYTHON and importlib.util.find_spec("anthropic") is not None
FAKE_KEY = "test-key-not-real"
REQUIREMENTS = REPO_ROOT / "requirements.txt"
SDK_PACKAGE = "anthropic"
LIVE_VENV = REPO_ROOT / ".venv-live"
LIVE_PYTHON = LIVE_VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
MAIN = REPO_ROOT / "code" / "main.py"
DATASET = REPO_ROOT / "dataset"
PIPELINE_TIMEOUT_S = 600
MAIN_BUILT = MAIN.is_file() and MAIN.stat().st_size > 0
IN_LIVE_VENV = Path(sys.prefix).resolve() == LIVE_VENV.resolve()
CROSS_INTERPRETER_ENV = "GHOSTAUDIT_CROSS_INTERPRETER"
CROSS_INTERPRETER_OPTED_IN = os.environ.get(CROSS_INTERPRETER_ENV) == "1"


def _sdk_requirement_line() -> str:
    """The single requirements.txt line that pins the SDK."""
    lines = [
        line.strip() for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(SDK_PACKAGE)
    ]
    if len(lines) != 1:
        raise AssertionError("expected one %s line in requirements.txt, got %r" % (SDK_PACKAGE, lines))
    return lines[0]


def _run_cached_pipeline(python: Path, workdir: Path) -> bytes:
    """Run main.py --llm cache with `python`; return the output.csv bytes."""
    out = workdir / "output.csv"
    command = [str(python), str(MAIN), "--llm", "cache", "--out", str(out), "--diag", str(workdir / "diag")]
    subprocess.run(command, cwd=str(REPO_ROOT), check=True, capture_output=True, timeout=PIPELINE_TIMEOUT_S)
    return out.read_bytes()


def _smoke_request() -> LLMRequest:
    return LLMRequest(
        model=SMOKE_MODEL,
        system="Reply with JSON only.",
        messages=(("user", 'Return {"answer": "ok"}.'),),
        max_tokens=64,
        prompt_version="smoke-v1",
        schema=SMOKE_SCHEMA,
    )


class SdkPinTest(unittest.TestCase):
    def test_requirements_pin_matches_config(self) -> None:
        marker = '; python_version >= "%d.%d"' % MIN_LIVE_PYTHON
        self.assertEqual(_sdk_requirement_line(), LIVE_SDK_REQUIREMENT + marker)

    def test_usage_report_records_the_pinned_sdk(self) -> None:
        meter = snapshot(UsageMeter(DEFAULT_PRICES), EVAL_REQUEST_COUNT)
        block = render_reports.usage_block(render_reports.Sources({}, meter, [], 0))
        self.assertIn("`%s`" % LIVE_SDK_REQUIREMENT, block)

    @unittest.skipUnless(SDK_READY, "needs Python >= 3.10 with anthropic installed (.venv-live)")
    def test_installed_sdk_matches_pin(self) -> None:
        from importlib.metadata import version

        self.assertEqual("%s==%s" % (SDK_PACKAGE, version(SDK_PACKAGE)), LIVE_SDK_REQUIREMENT)


@unittest.skipUnless(SDK_READY, "needs Python >= 3.10 with anthropic installed (.venv-live)")
class SdkRequestConstructionTest(unittest.TestCase):
    def test_sdk_sends_structured_output_without_sampling_params(self) -> None:
        import anthropic
        import httpx2  # anthropic 2.x depends on httpx2, not httpx

        bodies: List[Dict[str, Any]] = []

        def handler(http_request: "httpx2.Request") -> "httpx2.Response":
            bodies.append(json.loads(http_request.content))
            reply = {
                "id": "msg_test", "type": "message", "role": "assistant", "model": SMOKE_MODEL,
                "content": [{"type": "text", "text": '{"answer": "ok"}'}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 4},
            }
            return httpx2.Response(200, json=reply)

        client = anthropic.Anthropic(
            api_key=FAKE_KEY, max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        )
        raw = client.messages.create(**build_params(_smoke_request()))
        self.assertEqual(raw.stop_reason, "end_turn")
        body = bodies[0]
        for name in SAMPLING_PARAMS:
            self.assertNotIn(name, body)
        self.assertEqual(body["output_config"]["format"]["schema"], SMOKE_SCHEMA)
        self.assertEqual(body["output_config"]["effort"], _smoke_request().effort)


@unittest.skipUnless(SDK_READY and Config.from_env().api_key is not None,
                     "needs .venv-live and ANTHROPIC_API_KEY")
class LiveSmokeTest(unittest.TestCase):
    def test_live_structured_call(self) -> None:
        response = AnthropicClient.from_config(Config.from_env()).complete(_smoke_request())
        self.assertIn("answer", json.loads(response.text))
        self.assertGreater(response.output_tokens, 0)


@unittest.skipUnless(CROSS_INTERPRETER_OPTED_IN, "slow; set %s=1 to run" % CROSS_INTERPRETER_ENV)
@unittest.skipUnless(MAIN_BUILT, "code/main.py is not built yet")
@unittest.skipUnless(DATASET.is_dir(), "needs dataset/")
@unittest.skipUnless(LIVE_PYTHON.is_file(), "needs .venv-live (see README live section)")
@unittest.skipIf(IN_LIVE_VENV, "run from the system interpreter to compare it with .venv-live")
class CrossInterpreterOutputTest(unittest.TestCase):
    def test_cached_output_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as live:
            expected = _run_cached_pipeline(Path(sys.executable), Path(base))
            self.assertEqual(_run_cached_pipeline(LIVE_PYTHON, Path(live)), expected)


if __name__ == "__main__":
    unittest.main()
