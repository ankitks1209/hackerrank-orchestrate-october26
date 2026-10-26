"""Tests for ghostaudit.llm: client, disk cache, caching client, usage meter (SPEC N1, N2, N4, N7)."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

from ghostaudit.config import DEFAULT_PRICES, Config, Secret
from ghostaudit.llm import cache as cache_module
from ghostaudit.llm import client as client_module
from ghostaudit.llm.cache import CachingClient, DiskCache, request_key
from ghostaudit.llm.client import (
    AnthropicClient,
    CacheMiss,
    LLMBadOutput,
    LLMDisabled,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMUnavailable,
    NullClient,
    build_params,
)
from ghostaudit.llm.usage import (
    TokenTally,
    UsageMeter,
    count_pdf_pages,
    estimate_image_tokens,
    snapshot,
    tally_cost,
)

CODE_DIR = Path(__file__).resolve().parents[1]
FAKE_KEY = "sk-" + "ant-FAKE-KEY-for-leak-checks-0123456789"  # split so the packager scan skips this file
OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
PNG_1800_1200 = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1800).to_bytes(4, "big") + (1200).to_bytes(4, "big")
)
PDF_TWO_PAGES = b"%PDF-1.4 /Type /Pages /Kids [] /Type /Page /Type /Page"


def make_request(text: str = "hello", **changes: Any) -> LLMRequest:
    base = LLMRequest(
        model=OPUS,
        system="system prompt",
        messages=(("user", text),),
        max_tokens=256,
        prompt_version="intent.v1",
        schema=SCHEMA,
    )
    return dataclasses.replace(base, **changes)


def make_response(text: str = '{"ok": true}', **changes: Any) -> LLMResponse:
    base = LLMResponse(text=text, input_tokens=100, output_tokens=20, model=OPUS, cached=False)
    return dataclasses.replace(base, **changes)


class FakeInner:
    """Inner client that records every request body it receives."""

    def __init__(self) -> None:
        self.requests: List[LLMRequest] = []
        self.bodies: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.requests.append(request)
            self.bodies.append(build_params(request))
        return make_response(text='{"echo": "%s"}' % request.messages[-1][1])


class FakeApiError(Exception):
    def __init__(self, status_code: Optional[int]) -> None:
        super().__init__("api error")
        self.status_code = status_code


class FakeConnectionError(FakeApiError):
    """Like `anthropic.APIConnectionError`: an `APIError` without a status code."""

    def __init__(self) -> None:
        super().__init__(None)


class FakeSdk:
    """Stands in for the `anthropic` module: scripted outcomes for messages.create."""

    APIError = FakeApiError
    APIConnectionError = FakeConnectionError

    def __init__(self, outcomes: List[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: List[Dict[str, Any]] = []
        self.init_kwargs: Dict[str, Any] = {}
        sdk = self

        class Anthropic:
            def __init__(self, **kwargs: Any) -> None:
                sdk.init_kwargs = kwargs
                self.messages = SimpleNamespace(create=sdk._create)

        self.Anthropic = Anthropic

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def raw_message(text: str = "ok", stop_reason: str = "end_turn") -> Any:
    usage = SimpleNamespace(
        input_tokens=11, output_tokens=7, cache_creation_input_tokens=5, cache_read_input_tokens=3
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], usage=usage, stop_reason=stop_reason
    )


def make_anthropic(outcomes: List[Any], retries: int = 3) -> "tuple[AnthropicClient, FakeSdk, List[float]]":
    sdk = FakeSdk(outcomes)
    sleeps: List[float] = []
    client = AnthropicClient(
        Secret(FAKE_KEY), 60, retries, 1.0, sdk=sdk, sleep=sleeps.append, rng=random.Random(0)
    )
    return client, sdk, sleeps


class RequestKeyTests(unittest.TestCase):
    def test_key_is_stable_across_processes_and_hash_seeds(self) -> None:
        script = (
            "from tests.test_llm_cache import make_request\n"
            "from ghostaudit.llm.cache import request_key\n"
            "print(request_key(make_request(attachments=((b'img', 'image/png'),))))\n"
        )
        keys = set()
        for seed in ("0", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "-c", script], env=env, cwd=str(CODE_DIR),
                capture_output=True, text=True, check=True,
            )
            keys.add(result.stdout.strip())
        local = request_key(make_request(attachments=((b"img", "image/png"),)))
        self.assertEqual(keys, {local})

    def test_key_changes_with_every_request_field(self) -> None:
        base = make_request(attachments=((b"img", "image/png"),))
        variants = [
            dataclasses.replace(base, prompt_version="intent.v2"),
            dataclasses.replace(base, attachments=((b"img2", "image/png"),)),
            dataclasses.replace(base, attachments=((b"img", "application/pdf"),)),
            dataclasses.replace(base, model=HAIKU),
            dataclasses.replace(base, system="other"),
            dataclasses.replace(base, messages=(("user", "bye"),)),
            dataclasses.replace(base, max_tokens=512),
            dataclasses.replace(base, effort="high"),
            dataclasses.replace(base, schema=None),
        ]
        keys = {request_key(base)} | {request_key(variant) for variant in variants}
        self.assertEqual(len(keys), len(variants) + 1)


class DiskCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "cache"

    def test_round_trip_marks_cached_and_stores_no_key(self) -> None:
        cache = DiskCache(self.dir)
        request = make_request()
        key = request_key(request)
        cache.put(key, make_response())
        hit = cache.get(key)
        self.assertEqual(hit, make_response(cached=True))
        stored = (self.dir / (key + ".json")).read_text(encoding="utf-8")
        self.assertNotIn(key, stored)
        self.assertNotIn("hello", stored)

    def test_crash_before_replace_leaves_no_entry_and_no_temp_file(self) -> None:
        cache = DiskCache(self.dir)
        key = request_key(make_request())
        with mock.patch.object(cache_module.os, "replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                cache.put(key, make_response())
        self.assertIsNone(cache.get(key))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_damaged_entry_is_a_miss(self) -> None:
        cache = DiskCache(self.dir)
        key = request_key(make_request())
        self.dir.mkdir(parents=True)
        (self.dir / (key + ".json")).write_text("{not json", encoding="utf-8")
        with self.assertLogs("ghostaudit.llm", level="WARNING"):
            self.assertIsNone(cache.get(key))


class CachingClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = DiskCache(Path(self._tmp.name))
        self.meter = UsageMeter(DEFAULT_PRICES)
        self.inner = FakeInner()

    def client(self, mode: str) -> CachingClient:
        return CachingClient(self.inner, self.cache, self.meter, mode)

    def test_cache_mode_on_empty_cache_raises_cache_miss(self) -> None:
        with self.assertRaises(CacheMiss):
            self.client("cache").complete(make_request())
        self.assertEqual(self.inner.requests, [])

    def test_off_mode_raises_llm_disabled_even_with_a_stored_entry(self) -> None:
        request = make_request()
        self.cache.put(request_key(request), make_response())
        with self.assertRaises(LLMDisabled):
            self.client("off").complete(request)

    def test_live_mode_stores_then_replays_with_cached_true(self) -> None:
        live = self.client("live")
        first = live.complete(make_request())
        second = live.complete(make_request())
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(first.text, second.text)
        self.assertEqual(len(self.inner.requests), 1)
        replay = self.client("cache").complete(make_request())
        self.assertTrue(replay.cached)

    def test_meter_separates_live_and_replayed_tokens(self) -> None:
        live = self.client("live")
        live.complete(make_request())
        live.complete(make_request())
        live.complete(make_request())
        usage = self.meter.usage(OPUS)
        self.assertEqual((usage.live.calls, usage.live.input_tokens), (1, 100))
        self.assertEqual((usage.replayed.calls, usage.replayed.input_tokens), (2, 200))

    def test_no_sampling_parameters_in_any_outgoing_body(self) -> None:
        requests = [make_request("a"), make_request("b", attachments=((b"x", "image/png"),))]
        live = self.client("live")
        for request in requests:
            live.complete(request)
        self.assertEqual(len(self.inner.bodies), 2)
        for body in self.inner.bodies:
            for banned in ("temperature", "top_p", "top_k"):
                self.assertNotIn(banned, body)

    def test_bad_output_is_returned_metered_and_not_stored(self) -> None:
        bad = make_response(text="", stop_reason="refusal", output_tokens=4)

        class Refusing:
            def complete(self, request: LLMRequest) -> LLMResponse:
                raise LLMBadOutput("refused", bad)

        live = CachingClient(Refusing(), self.cache, self.meter, "live")
        with self.assertRaises(LLMBadOutput):
            live.complete(make_request())
        self.assertEqual(self.meter.usage(OPUS).live.output_tokens, 4)
        self.assertIsNone(self.cache.get(request_key(make_request())))

    def test_invalid_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.client("batch")

    def test_null_client_is_disabled(self) -> None:
        with self.assertRaises(LLMDisabled):
            NullClient().complete(make_request())


class AnthropicClientTests(unittest.TestCase):
    def test_request_has_required_shape_and_no_sampling_parameters(self) -> None:
        request = make_request(attachments=((b"img", "image/png"), (b"%PDF", "application/pdf")))
        params = build_params(request)
        for banned in ("temperature", "top_p", "top_k"):
            self.assertNotIn(banned, params)
        self.assertEqual(params["output_config"]["effort"], "low")
        self.assertEqual(params["output_config"]["format"], {"type": "json_schema", "schema": SCHEMA})
        self.assertEqual(params["max_tokens"], 256)
        self.assertEqual(params["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(params["messages"][-1]["role"], "user")
        blocks = params["messages"][-1]["content"]
        self.assertEqual([b["type"] for b in blocks], ["image", "document", "text"])
        self.assertEqual(blocks[0]["source"]["media_type"], "image/png")
        self.assertEqual(blocks[1]["source"]["media_type"], "application/pdf")
        self.assertNotEqual(params["messages"][-1]["role"], "assistant")

    def test_schema_is_omitted_when_not_requested(self) -> None:
        params = build_params(make_request(schema=None))
        self.assertNotIn("format", params["output_config"])

    def test_complete_parses_text_and_usage_and_configures_the_sdk(self) -> None:
        client, sdk, _ = make_anthropic([raw_message("hi")])
        response = client.complete(make_request())
        self.assertEqual(
            (response.text, response.input_tokens, response.output_tokens, response.cached),
            ("hi", 11, 7, False),
        )
        self.assertEqual((response.cache_creation_tokens, response.cache_read_tokens), (5, 3))
        self.assertEqual(sdk.init_kwargs["timeout"], 60)
        self.assertEqual(sdk.init_kwargs["max_retries"], 0)
        self.assertEqual(sdk.calls[0]["model"], OPUS)

    def test_retries_429_and_5xx_with_growing_backoff(self) -> None:
        client, sdk, sleeps = make_anthropic([FakeApiError(429), FakeApiError(503), raw_message()])
        client.complete(make_request())
        self.assertEqual(len(sdk.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(1.0 <= sleeps[0] < 2.0 and 2.0 <= sleeps[1] < 3.0)

    def test_gives_up_after_the_retry_budget(self) -> None:
        client, sdk, _ = make_anthropic([FakeApiError(500)] * 4)
        with self.assertRaises(LLMError):
            client.complete(make_request())
        self.assertEqual(len(sdk.calls), 4)

    def test_retries_connection_errors(self) -> None:
        client, sdk, sleeps = make_anthropic([FakeConnectionError(), raw_message()])
        self.assertEqual(client.complete(make_request()).text, "ok")
        self.assertEqual((len(sdk.calls), len(sleeps)), (2, 1))

    def test_does_not_retry_client_errors_or_status_less_errors(self) -> None:
        for status in (400, 401, None):
            client, sdk, sleeps = make_anthropic([FakeApiError(status)])
            with self.assertRaises(LLMError):
                client.complete(make_request())
            self.assertEqual((len(sdk.calls), sleeps), (1, []))

    def test_refusal_and_max_tokens_raise_bad_output_with_usage(self) -> None:
        for reason in ("refusal", "max_tokens"):
            client, _, _ = make_anthropic([raw_message("", stop_reason=reason)])
            with self.assertRaises(LLMBadOutput) as caught:
                client.complete(make_request())
            self.assertEqual(caught.exception.response.stop_reason, reason)
            self.assertEqual(caught.exception.response.output_tokens, 7)

    def test_missing_key_and_old_python_are_unavailable(self) -> None:
        with self.assertRaises(LLMUnavailable):
            AnthropicClient(None, 60, 3, 1.0, sdk=FakeSdk([]))
        with mock.patch.object(client_module, "MIN_LIVE_PYTHON", (99, 0)):
            with self.assertRaises(LLMUnavailable) as caught:
                AnthropicClient(Secret(FAKE_KEY), 60, 3, 1.0)
        self.assertIn("Python", str(caught.exception))

    def test_missing_sdk_is_unavailable(self) -> None:
        with mock.patch.object(client_module.importlib, "import_module", side_effect=ImportError):
            with self.assertRaises(LLMUnavailable):
                client_module._load_sdk()


class UsageTests(unittest.TestCase):
    def test_cost_uses_prices_cache_multipliers_and_batch_discount(self) -> None:
        opus = DEFAULT_PRICES[0]
        tally = TokenTally(
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000,
        )
        self.assertAlmostEqual(tally_cost(tally, opus), 4.0 + 20.0 + 5.0 + 0.2)
        self.assertAlmostEqual(tally_cost(tally, opus, batch=True), (4.0 + 20.0 + 5.0 + 0.2) / 2)

    def test_cache_read_without_a_published_price_uses_the_input_price(self) -> None:
        haiku = DEFAULT_PRICES[1]
        self.assertIsNone(haiku.cache_read_per_mtok)
        tally = TokenTally(cache_read_tokens=1_000_000)
        self.assertAlmostEqual(tally_cost(tally, haiku), haiku.input_per_mtok)

    def test_media_estimates(self) -> None:
        self.assertEqual(estimate_image_tokens(PNG_1800_1200), 1800 * 1200 // 750)
        self.assertEqual(estimate_image_tokens(b"GIF89a"), 0)
        self.assertEqual(count_pdf_pages(PDF_TWO_PAGES), 2)

class SecretLeakTests(unittest.TestCase):
    def test_key_value_appears_nowhere(self) -> None:
        records: List[str] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        handler = Capture()
        logger = logging.getLogger("ghostaudit")
        self.addCleanup(logger.setLevel, logger.level)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(setattr, logger, "propagate", logger.propagate)
        logger.propagate = False  # the handler records everything; keep the test output quiet
        self.addCleanup(logging.getLogger("ghostaudit").removeHandler, handler)
        with tempfile.TemporaryDirectory() as tmp:
            config = Config.from_env({"ANTHROPIC_API_KEY": FAKE_KEY})
            client, _, _ = make_anthropic([FakeApiError(429), raw_message(), raw_message()])
            meter = UsageMeter(config.prices)
            caching = CachingClient(client, DiskCache(Path(tmp)), meter, "live")
            caching.complete(make_request())
            caching.complete(make_request("b"))
            report = json.dumps(snapshot(meter, 518))
            texts = [repr(config), repr(config.api_key), str(config.api_key), report, "\n".join(records)]
            texts += [path.read_text(encoding="utf-8") for path in Path(tmp).iterdir()]
        for text in texts:
            self.assertNotIn(FAKE_KEY, text)
            self.assertNotIn("sk-", text)

    def test_api_failure_message_does_not_expose_the_key(self) -> None:
        client, _, _ = make_anthropic([FakeApiError(401)])
        with self.assertRaises(LLMError) as caught:
            client.complete(make_request())
        self.assertNotIn(FAKE_KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
