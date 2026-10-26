"""LLM request/response types, the client Protocol and the Anthropic client.

Implements SPEC 10 N1 (no sampling parameters; explicit effort, structured
outputs, fixed max_tokens), N2 (retries on 429, 5xx and connection errors such as
a dropped TLS session or a timeout, which the live fill met in practice), N4 (the key lives only in `Secret`, never in an
error text) and N7 (refusal/max_tokens raise `LLMBadOutput` so the caller
falls back deterministically). The SDK is imported lazily and only here.

Tool use (SPEC 12): a request may carry `tools` and structured message content (the
assistant's `tool_use` blocks and the user's `tool_result` blocks), and a response keeps the
assistant's content blocks so a caller can replay the turn. `tool_choice` is left at its default
(`auto`): the target models reject forced tool use.
"""
from __future__ import annotations

import base64
import importlib
import logging
import random
import sys
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple, Union

from ghostaudit.config import LLM_EFFORT, MIN_LIVE_PYTHON, Config, Secret

LOGGER = logging.getLogger("ghostaudit.llm")

RATE_LIMITED = 429
SERVER_ERROR_FROM = 500
BAD_STOP_REASONS = ("refusal", "max_tokens")
IMAGE_MIME_PREFIX = "image/"
PDF_MIME = "application/pdf"
CACHE_CONTROL = {"type": "ephemeral"}


class LLMError(Exception):
    """Base class for every LLM-layer failure the callers may fall back from."""


class LLMTimeout(LLMError):
    """A model call did not finish inside its time limit, after the retries."""


class LLMUnavailable(LLMError):
    """Live mode cannot run: wrong Python, missing SDK or missing key."""


class LLMDisabled(LLMError):
    """The run was started with `--llm off`."""


class CacheMiss(LLMError):
    """`--llm cache` found no stored response for the request."""


class LLMBadOutput(LLMError):
    """The model refused or hit max_tokens; `response` still carries its usage."""

    def __init__(self, message: str, response: "LLMResponse") -> None:
        super().__init__(message)
        self.response = response


Block = Mapping[str, Any]  # one API content block: text, tool_use or tool_result
MessageContent = Union[str, Tuple[Block, ...]]


@dataclass(frozen=True)
class LLMRequest:
    """One model call; `messages` are (role, content) pairs, attachments are (bytes, mime).

    `content` is plain text or a tuple of API content blocks (tool use). `tools` are API
    tool definitions. `timeout_s` bounds this call and is not part of the cache key.
    """

    model: str
    system: str
    messages: Tuple[Tuple[str, MessageContent], ...]
    max_tokens: int
    prompt_version: str
    attachments: Tuple[Tuple[bytes, str], ...] = ()
    schema: Optional[Mapping[str, Any]] = None
    effort: str = LLM_EFFORT
    tools: Tuple[Block, ...] = ()
    timeout_s: Optional[float] = None


@dataclass(frozen=True)
class LLMResponse:
    """Model output with the usage the API reported (output tokens include thinking)."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    cached: bool
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    stop_reason: str = "end_turn"
    content: Tuple[Block, ...] = ()  # the assistant's blocks, kept only for tool-use requests

    @property
    def total_tokens(self) -> int:
        """All tokens billed for the call, cached or not."""
        return (
            self.input_tokens + self.output_tokens
            + self.cache_creation_tokens + self.cache_read_tokens
        )


class LLMClient(Protocol):
    """Anything that turns an `LLMRequest` into an `LLMResponse`."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one request or raise an `LLMError`."""


class NullClient:
    """Stand-in client for runs that must not call a model."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMDisabled("LLM calls are disabled")


def _attachment_block(data: bytes, mime: str) -> Dict[str, Any]:
    kind = "image" if mime.startswith(IMAGE_MIME_PREFIX) else "document"
    encoded = base64.standard_b64encode(data).decode("ascii")
    return {"type": kind, "source": {"type": "base64", "media_type": mime, "data": encoded}}


def _build_messages(request: LLMRequest) -> List[Dict[str, Any]]:
    """Messages as API dicts; attachments precede the text of the last message."""
    last = len(request.messages) - 1
    built: List[Dict[str, Any]] = []
    for index, (role, content) in enumerate(request.messages):
        if not isinstance(content, str):
            built.append({"role": role, "content": [dict(block) for block in content]})
        elif index == last and request.attachments:
            blocks = [_attachment_block(data, mime) for data, mime in request.attachments]
            built.append({"role": role, "content": blocks + [{"type": "text", "text": content}]})
        else:
            built.append({"role": role, "content": content})
    return built


def _mark_last_block(messages: List[Dict[str, Any]]) -> None:
    """Put the prompt-cache breakpoint on the last block of the last message (multi-turn caching)."""
    last = messages[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = CACHE_CONTROL


def build_params(request: LLMRequest) -> Dict[str, Any]:
    """Keyword arguments for `messages.create`; never sampling parameters (SPEC N1)."""
    output_config: Dict[str, Any] = {"effort": request.effort}
    if request.schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": dict(request.schema)}
    params: Dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": [{"type": "text", "text": request.system, "cache_control": CACHE_CONTROL}],
        "messages": _build_messages(request),
        "output_config": output_config,
    }
    if request.tools:
        params["tools"] = [dict(tool) for tool in request.tools]
        _mark_last_block(params["messages"])
    if request.timeout_s is not None:
        params["timeout"] = request.timeout_s
    return params


def _is_retryable(status: Optional[int]) -> bool:
    return status is not None and (status == RATE_LIMITED or status >= SERVER_ERROR_FROM)


def _load_sdk() -> ModuleType:
    if sys.version_info < MIN_LIVE_PYTHON:
        have = sys.version_info
        raise LLMUnavailable(
            "live LLM mode needs Python >= %d.%d (this is %d.%d); use --llm cache or off"
            % (MIN_LIVE_PYTHON[0], MIN_LIVE_PYTHON[1], have[0], have[1])
        )
    try:
        return importlib.import_module("anthropic")
    except ImportError as exc:
        raise LLMUnavailable("anthropic is not installed; see requirements.txt") from exc


def _block_dict(block: Any) -> Dict[str, Any]:
    """An SDK content block as a plain, JSON-ready dict."""
    dump = getattr(block, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_none=True))
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
    return {"type": "text", "text": getattr(block, "text", "")}


def _to_response(request: LLMRequest, raw: Any) -> LLMResponse:
    usage = raw.usage
    text = "".join(block.text for block in raw.content if block.type == "text")
    content = tuple(_block_dict(block) for block in raw.content) if request.tools else ()
    response = LLMResponse(
        text=text,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        model=request.model,
        cached=False,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        stop_reason=raw.stop_reason or "",
        content=content,
    )
    if response.stop_reason in BAD_STOP_REASONS:
        raise LLMBadOutput("model stopped with %s" % response.stop_reason, response)
    return response


class AnthropicClient:
    """Calls the Messages API; holds the only copy of the key as a `Secret`."""

    def __init__(
        self,
        api_key: Optional[Secret],
        timeout_s: float,
        retries: int,
        backoff_base_s: float,
        sdk: Optional[ModuleType] = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Optional[random.Random] = None,
    ) -> None:
        sdk = sdk if sdk is not None else _load_sdk()
        if api_key is None:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        # max_retries=0: this class owns the retry policy (429/5xx only).
        self._client = sdk.Anthropic(api_key=api_key.reveal(), timeout=timeout_s, max_retries=0)
        self._api_error = sdk.APIError
        self._connection_error = sdk.APIConnectionError
        self._timeout_error = getattr(sdk, "APITimeoutError", None)
        self._retries = retries
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()

    @classmethod
    def from_config(cls, config: Config) -> "AnthropicClient":
        """Build the client from a `Config` (the key comes from `Config.from_env`)."""
        return cls(config.api_key, config.timeout_s, config.retries, config.backoff_base_s)

    def _backoff(self, attempt: int) -> float:
        return self._backoff_base_s * 2 ** attempt + self._rng.uniform(0, self._backoff_base_s)

    def complete(self, request: LLMRequest) -> LLMResponse:
        params = build_params(request)
        attempt = 0
        while True:
            try:
                raw = self._client.messages.create(**params)
            except self._api_error as exc:
                status = getattr(exc, "status_code", None)
                transient = isinstance(exc, self._connection_error) or _is_retryable(status)
                if attempt >= self._retries or not transient:
                    timed_out = self._timeout_error is not None and isinstance(exc, self._timeout_error)
                    if timed_out:
                        raise LLMTimeout("Anthropic API call timed out after %d retries" % attempt) from exc
                    raise LLMError(
                        "Anthropic API call failed (%s, status %s)" % (type(exc).__name__, status)
                    ) from exc
                LOGGER.warning(
                    "LLM call failed (%s, status %s); retry %d",
                    type(exc).__name__, status, attempt + 1,
                )
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            return _to_response(request, raw)
