"""Model-driven routing: which cases need an investigation (SPEC 12.5).

A deterministic pre-analysis summarises every case that has something contested; a batched
router call (at most `ROUTER_BATCH` cases) returns `investigate` or `accept` for each. A case
with nothing contested is accepted without a call. If a router call fails (error, cache miss,
reply that does not match the schema or the case ids), every case of that batch is routed to
investigation: spending a call is safer than accepting a case that needed work.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from ghostaudit.agent import prompts, schema
from ghostaudit.agent.model import ROUTE_ACCEPT, ROUTE_INVESTIGATE
from ghostaudit.llm.client import LLMClient, LLMError, LLMRequest

LOGGER = logging.getLogger(__name__)

ROUTER_BATCH = 25  # cases per router call
ROUTER_MAX_TOKENS = 8192
ROUTER_EFFORT = "low"
ROUTER_TIMEOUT_S = 90.0

ROUTE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "routes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "route": {"type": "string", "enum": [ROUTE_INVESTIGATE, ROUTE_ACCEPT]},
                    "reason": {"type": "string"},
                },
                "required": ["case_id", "reason", "route"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["routes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RouteResult:
    """Route of every case, the number of router calls and whether any batch failed."""

    routes: Mapping[str, str]
    calls: int
    failed: bool


def route_cases(
    summaries: Sequence[Mapping[str, Any]], client: LLMClient, model: str
) -> RouteResult:
    """Route the summarised cases; a failed batch routes all its cases to investigation."""
    system = prompts.load_prompt(prompts.ROUTER_PROMPT)
    ordered = sorted(summaries, key=lambda item: item["case_id"])
    routes: Dict[str, str] = {}
    calls = 0
    failed = False
    for start in range(0, len(ordered), ROUTER_BATCH):
        batch = ordered[start : start + ROUTER_BATCH]
        calls += 1
        verdict = _ask(batch, system, client, model)
        if verdict is None:
            failed = True
            routes.update({item["case_id"]: ROUTE_INVESTIGATE for item in batch})
        else:
            routes.update(verdict)
    return RouteResult(routes, calls, failed)


def _ask(
    batch: Sequence[Mapping[str, Any]], system: str, client: LLMClient, model: str
) -> Optional[Dict[str, str]]:
    payload = json.dumps({"cases": list(batch)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request = LLMRequest(
        model=model,
        system=system,
        messages=(("user", payload),),
        max_tokens=ROUTER_MAX_TOKENS,
        prompt_version=prompts.ROUTER_PROMPT,
        schema=ROUTE_SCHEMA,
        effort=ROUTER_EFFORT,
        timeout_s=ROUTER_TIMEOUT_S,
    )
    try:
        text = client.complete(request).text
    except LLMError as error:
        LOGGER.warning("router call failed: %s", error)
        return None
    return parse_routes(text, [item["case_id"] for item in batch])


def parse_routes(text: str, expected: Sequence[str]) -> Optional[Dict[str, str]]:
    """The routes of a reply, or None when it is not valid JSON of the schema naming exactly `expected`."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if schema.validate(data, ROUTE_SCHEMA):
        return None
    found: Dict[str, str] = {}
    for item in data["routes"]:
        if item["case_id"] in found:
            return None
        found[item["case_id"]] = item["route"]
    return found if sorted(found) == sorted(expected) else None


def summarize(
    case_id: str,
    contested_rows: int,
    contested_accounts: int,
    account_state: str,
    competing: int,
    unread_media: int,
    conflicts: int,
    status: str,
) -> Dict[str, Any]:
    """The router's view of one case (the fields the router prompt documents)."""
    return {
        "case_id": case_id,
        "contested_rows": contested_rows,
        "contested_accounts": contested_accounts,
        "account_state": account_state,
        "competing_cases": competing,
        "unread_media": unread_media,
        "conflicts": conflicts,
        "preliminary_status": status,
    }


def default_routes(case_ids: Sequence[str]) -> Dict[str, str]:
    """The routing when the router is not used: investigate every case given."""
    return {case_id: ROUTE_INVESTIGATE for case_id in case_ids}

