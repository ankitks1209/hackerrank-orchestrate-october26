"""Usage meter and its JSON snapshot for the usage report (SPEC 11 A5, AGENTS 6.8).

Tokens are metered per model and split into live calls (real API spend) and
replayed cache hits (the spend a cold run would incur). Output tokens include
thinking. Prices come from `Config.prices`; a model without a price is reported
as unpriced, never guessed. `tools/render_reports.py` renders the Markdown report from
`snapshot`.
"""
from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Sequence

from ghostaudit.config import (
    BATCH_DISCOUNT,
    CACHE_WRITE_MULTIPLIER,
    IMAGE_PIXELS_PER_TOKEN,
    ModelPrice,
)
from ghostaudit.llm.client import IMAGE_MIME_PREFIX, PDF_MIME, LLMRequest, LLMResponse

TOKENS_PER_MTOK = 1_000_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_SIZE_OFFSET = 16  # signature (8) + IHDR length (4) + "IHDR" (4)
PDF_PAGE_PATTERN = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


@dataclass
class TokenTally:
    """Counters for one (model, live-or-replayed) bucket."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    images: int = 0
    image_tokens: int = 0
    pdf_pages: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens
            + self.cache_creation_tokens + self.cache_read_tokens
        )

    def add(self, request: LLMRequest, response: LLMResponse) -> None:
        """Count one call and the media its request carried."""
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.cache_creation_tokens += response.cache_creation_tokens
        self.cache_read_tokens += response.cache_read_tokens
        for data, mime in request.attachments:
            if mime.startswith(IMAGE_MIME_PREFIX):
                self.images += 1
                self.image_tokens += estimate_image_tokens(data)
            elif mime == PDF_MIME:
                self.pdf_pages += count_pdf_pages(data)

    def merge(self, other: "TokenTally") -> None:
        """Add another tally's counters into this one."""
        for name in TALLY_FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))


TALLY_FIELDS = tuple(f.name for f in fields(TokenTally))


@dataclass
class ModelUsage:
    """Everything metered for one model."""

    live: TokenTally = field(default_factory=TokenTally)
    replayed: TokenTally = field(default_factory=TokenTally)


def estimate_image_tokens(data: bytes) -> int:
    """Estimate image tokens as width * height / 750 for PNG; 0 for other formats."""
    if not data.startswith(PNG_SIGNATURE):
        return 0
    width, height = struct.unpack(">II", data[PNG_SIZE_OFFSET:PNG_SIZE_OFFSET + 8])
    return width * height // IMAGE_PIXELS_PER_TOKEN


def count_pdf_pages(data: bytes) -> int:
    """Count `/Type /Page` objects (not `/Pages`) in an uncompressed page tree."""
    return len(PDF_PAGE_PATTERN.findall(data))


def tally_cost(tally: TokenTally, price: ModelPrice, batch: bool = False) -> float:
    """USD for a tally. Cache reads use the input price when none is published."""
    read_price = price.cache_read_per_mtok
    if read_price is None:
        read_price = price.input_per_mtok
    usd = (
        tally.input_tokens * price.input_per_mtok
        + tally.cache_creation_tokens * price.input_per_mtok * CACHE_WRITE_MULTIPLIER
        + tally.cache_read_tokens * read_price
        + tally.output_tokens * price.output_per_mtok
    ) / TOKENS_PER_MTOK
    return usd * BATCH_DISCOUNT if batch else usd


class UsageMeter:
    """Recorder of live and replayed LLM usage."""

    def __init__(self, prices: Sequence[ModelPrice]) -> None:
        self._prices = {price.model: price for price in prices}
        self._usage: Dict[str, ModelUsage] = {}

    def _entry(self, model: str) -> ModelUsage:
        return self._usage.setdefault(model, ModelUsage())

    def record_live(self, request: LLMRequest, response: LLMResponse) -> None:
        """Record a real API call that has finished."""
        self._entry(response.model).live.add(request, response)

    def record_replay(self, request: LLMRequest, response: LLMResponse) -> None:
        """Record a response served from the disk cache."""
        self._entry(response.model).replayed.add(request, response)

    def models(self) -> List[str]:
        return sorted(self._usage)

    def usage(self, model: str) -> ModelUsage:
        return self._usage[model]

    def price(self, model: str) -> Optional[ModelPrice]:
        return self._prices.get(model)

    def live_cost_usd(self) -> float:
        """USD spent so far on real API calls, over all priced models (the agent's cost cap reads it)."""
        return sum(self.cost(model) or 0.0 for model in self.models())

    def cost(self, model: str, replayed: bool = False, batch: bool = False) -> Optional[float]:
        """USD for the live (or replayed) bucket of a model; None when unpriced."""
        price = self._prices.get(model)
        if price is None:
            return None
        usage = self._usage[model]
        return tally_cost(usage.replayed if replayed else usage.live, price, batch)


def _sum_costs(costs: Sequence[Optional[float]]) -> Optional[float]:
    known = [cost for cost in costs if cost is not None]
    return sum(known) if len(known) == len(costs) else None


def _bucket(
    tally: TokenTally, sync: Optional[float], batch: Optional[float], requests: int
) -> Dict[str, Any]:
    """One live-or-replayed bucket: raw counters, total tokens, costs and per-request averages."""
    return {
        **{name: getattr(tally, name) for name in TALLY_FIELDS},
        "total_tokens": tally.total_tokens,
        "cost_sync": sync,
        "cost_batch": batch,
        "tokens_per_request": tally.total_tokens / requests,
        "cost_per_request": None if sync is None else sync / requests,
    }


def snapshot(meter: UsageMeter, requests: int) -> Dict[str, Any]:
    """JSON-ready meter state for the report checks: raw tallies, prices, totals and averages.

    Each model and the overall entry hold two buckets. `live` is new API spend. `replayed` is
    the usage recorded on the cached responses a run served; it is what a run from an empty
    cache would spend. `requests` is the number of cases processed; averages divide by it.
    """
    if requests < 1:
        raise ValueError("requests must be positive")
    models: Dict[str, Any] = {}
    totals = {"live": TokenTally(), "replayed": TokenTally()}
    costs: Dict[str, Dict[str, List[Optional[float]]]] = {
        kind: {"sync": [], "batch": []} for kind in totals
    }
    for model in meter.models():
        usage = meter.usage(model)
        price = meter.price(model)
        entry: Dict[str, Any] = {"price": None if price is None else asdict(price)}
        for kind, replayed in (("live", False), ("replayed", True)):
            tally = usage.replayed if replayed else usage.live
            sync, batch = meter.cost(model, replayed), meter.cost(model, replayed, batch=True)
            costs[kind]["sync"].append(sync)
            costs[kind]["batch"].append(batch)
            totals[kind].merge(tally)
            entry[kind] = _bucket(tally, sync, batch, requests)
        models[model] = entry
    return {
        "requests": requests,
        "models": models,
        "overall": {
            kind: _bucket(
                totals[kind], _sum_costs(costs[kind]["sync"]), _sum_costs(costs[kind]["batch"]), requests
            )
            for kind in totals
        },
    }
