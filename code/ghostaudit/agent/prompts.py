"""Versioned prompt files of the agent stage (SPEC 12.6)."""
from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
AGENT_PROMPT = "agent.v1"
ROUTER_PROMPT = "router.v1"
VERIFIER_PROMPT = "verifier.v1"


def load_prompt(name: str) -> str:
    """The text of `llm/prompts/<name>.md`; the name is also the request's prompt version."""
    return (PROMPT_DIR / (name + ".md")).read_text(encoding="utf-8")
