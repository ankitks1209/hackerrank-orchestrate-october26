"""Content-addressed disk cache and the caching client decorator.

Implements SPEC 10 N1 (determinism comes from replaying stored responses),
N4 (entries never hold the request or any credential) and N7
(`CacheMiss`/`LLMDisabled` let callers fall back). Requests run one at a time.

A live reply may be redacted before it is stored (`Redactor`, DECISIONS D25): the entry then
carries a `redacted_at_rest` field naming the redaction, and the original text is not kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from ghostaudit.llm.client import (
    CacheMiss,
    LLMBadOutput,
    LLMClient,
    LLMDisabled,
    LLMRequest,
    LLMResponse,
)
from ghostaudit.llm.usage import UsageMeter

LOGGER = logging.getLogger("ghostaudit.llm")

MODES = ("off", "cache", "live")
ENTRY_SUFFIX = ".json"
TEMP_PREFIX = ".tmp-"
KEY_PREFIX_CHARS = 12
CONTENT_FIELD = "content"  # assistant blocks of a tool-use response
REDACTED_FIELD = "redacted_at_rest"  # top-level field of an entry whose text was redacted before storing


def request_key(request: LLMRequest) -> str:
    """SHA-256 of the canonical request JSON, attachments hashed by content.

    The tool definitions are part of the key, and the call timeout is not.
    """
    payload: Dict[str, Any] = {
        "model": request.model,
        "system": request.system,
        "messages": [list(message) for message in request.messages],
        "max_tokens": request.max_tokens,
        "prompt_version": request.prompt_version,
        "effort": request.effort,
        "schema": request.schema,
        "attachments": [
            {"sha256": hashlib.sha256(data).hexdigest(), "mime": mime}
            for data, mime in request.attachments
        ],
    }
    if request.tools:  # absent for tool-free requests, so their keys are unchanged
        payload["tools"] = list(request.tools)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DiskCache:
    """One JSON file per request key holding text, usage and model."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, key: str) -> Path:
        return self._dir / (key + ENTRY_SUFFIX)

    def get(self, key: str) -> Optional[LLMResponse]:
        """The stored response marked `cached=True`, or None for a miss or damaged entry."""
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(
                text=entry["text"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                model=entry["model"],
                cached=True,
                cache_creation_tokens=entry["cache_creation_tokens"],
                cache_read_tokens=entry["cache_read_tokens"],
                stop_reason=entry["stop_reason"],
                content=tuple(entry.get(CONTENT_FIELD, ())),
            )
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as exc:
            LOGGER.warning("ignoring damaged cache entry %s: %s", path.name, exc)
            return None

    def put(self, key: str, response: LLMResponse, redaction: str = "") -> None:
        """Store atomically: write a temp file in the same directory, then `os.replace`.

        A non-empty `redaction` says how the text was redacted and is stored beside it.
        """
        entry = {
            "text": response.text,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_creation_tokens": response.cache_creation_tokens,
            "cache_read_tokens": response.cache_read_tokens,
            "model": response.model,
            "stop_reason": response.stop_reason,
        }
        if response.content:
            entry[CONTENT_FIELD] = list(response.content)
        if redaction:
            entry[REDACTED_FIELD] = redaction
        self._dir.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=TEMP_PREFIX, dir=str(self._dir))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(entry, stream, sort_keys=True, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temp_name, self._path(key))
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise


class Redactor:
    """How the replies to one prompt version are redacted before they are stored."""

    def __init__(self, description: str, redact: Callable[[str], str]) -> None:
        self.description = description
        self.redact = redact


class CachingClient:
    """Serves requests from the cache and, in live mode only, calls the inner client.

    `redactors` maps a prompt version to the redaction applied to its replies before they
    are stored; the caller of a live request still receives the reply as the model sent it.
    """

    def __init__(
        self,
        inner: LLMClient,
        cache: DiskCache,
        meter: UsageMeter,
        mode: str,
        redactors: Optional[Mapping[str, Redactor]] = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError("mode must be one of %s" % (MODES,))
        self._redactors = redactors or {}
        self._inner = inner
        self._cache = cache
        self._meter = meter
        self._mode = mode

    def _lookup(self, request: LLMRequest, key: str) -> Optional[LLMResponse]:
        """A replayed hit; None means a live call is needed; raises per mode otherwise."""
        if self._mode == "off":
            raise LLMDisabled("LLM calls are disabled (--llm off)")
        hit = self._cache.get(key)
        if hit is not None:
            self._meter.record_replay(request, hit)
            return hit
        if self._mode == "cache":
            raise CacheMiss(
                "no cached response for %s (prompt %s, key %s)"
                % (request.model, request.prompt_version, key[:KEY_PREFIX_CHARS])
            )
        return None

    def _call_live(self, request: LLMRequest, key: str) -> LLMResponse:
        try:
            response = self._inner.complete(request)
        except LLMBadOutput as exc:
            self._meter.record_live(request, exc.response)
            raise
        self._meter.record_live(request, response)
        redactor = self._redactors.get(request.prompt_version)
        if redactor is None:
            self._cache.put(key, response)
        else:
            self._cache.put(key, replace(response, text=redactor.redact(response.text)), redactor.description)
        return response

    def complete(self, request: LLMRequest) -> LLMResponse:
        """One request: hit, or (live mode) call and store."""
        key = request_key(request)
        hit = self._lookup(request, key)
        return hit if hit is not None else self._call_live(request, key)
