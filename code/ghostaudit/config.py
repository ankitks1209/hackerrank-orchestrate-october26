"""Configuration, feature flags and the only environment reader.

Implements SPEC 10 N4 (the API key comes only from the environment, or from the
git-ignored repo-root `.env` when the environment lacks it, and is never printed),
N5 (repo root resolved from this file, never the CWD), the agent settings of SPEC 12
and the inference flags of SPEC 10.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
API_KEY_ENV = "ANTHROPIC_API_KEY"
DOTENV_PATH = REPO_ROOT / ".env"  # SPEC N4: git-ignored, never packaged, never logged
DOTENV_EXPORT = "export "
DOTENV_QUOTES = "\"'"
LLM_MODES = ("off", "cache", "live")
LLM_EFFORT = "low"  # SPEC N1: explicit output_config.effort (models default to "medium")
MIN_LIVE_PYTHON = (3, 10)  # anthropic>=2.0.0 requires Python 3.10 (PyPI requires_python)
LLM_PROVIDER = "Anthropic"  # AGENTS 6.8: the usage report names the model provider
LIVE_SDK_REQUIREMENT = "anthropic==2.3.0"  # must match the pin in requirements.txt
CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute cache write vs base input price (claude-api skill)
BATCH_DISCOUNT = 0.5  # Message Batches bill 50 % of standard prices (claude-api skill)
IMAGE_PIXELS_PER_TOKEN = 750  # image tokens ~ width * height / 750 (estimate)
INTENT_CONFIDENCE_FLOOR = 0.6  # SPEC 9.4: below this the lexicon decides instead of the LLM
INTENT_MAX_TOKENS = 8192  # one batch of <= 25 verdicts plus thinking (SPEC N1: fixed max_tokens)
INTENT_NEGATION_WINDOW = 6  # SPEC 9.2a: a negation reaches at most 6 tokens forward
MIN_PROMPT_TOKENS = 600  # SPEC 9.1: system prompt size that makes prompt caching apply
EVAL_REQUEST_COUNT = 518  # rows of dataset/deletion_requests.csv (AGENTS 6.1; the per-request average = total / 518)
MIN_CUSTOM_CASES = 3  # AGENTS 6.8: at least three participant-created evaluation cases
COST_TOLERANCE_USD = 1e-9  # allowed float drift when recomputing a cost
RATIO_TOLERANCE = 1e-9  # allowed float drift when recomputing a ratio, average or normalized score
# scorer: G7 weights, Pareto slack.
COMPOSITE_WEIGHTS: Mapping[str, float] = {"G1": 0.30, "G3": 0.40, "G5": 0.15, "G6": 0.15}
DEFAULT_INTENT_MODEL = "claude-opus-5-5"  # the quality-first intent classifier (D5)
CHEAP_INTENT_MODEL = "claude-haiku-5-5"  # strategy S2: the cheaper intent classifier, compared but not the default
DEFAULT_MEDIA_MODEL = "claude-opus-5-5"  # images and PDFs need the stronger vision model (D5)
AGENT_MODES = ("on", "off")
DEFAULT_AGENT_MODEL = "claude-opus-5-5"  # the investigation loop (user decision: Opus for loop, router and verifier)
DEFAULT_ROUTER_MODEL = "claude-opus-5-5"  # the model-driven triage call
DEFAULT_VERIFIER_MODEL = "claude-opus-5-5"  # the second-stage critic
DEFAULT_AGENT_MAX_USD = 5.0  # modest per-run ceiling for live agent calls; checked with UsageMeter
COMPARE_TOLERANCE = 0.005  # normalized score units a grader may drop before it counts as a regression

PARSE_HEAD_BYTES = 4096  # leading bytes shown to EvidenceParser.detect (families are told apart by their first keys)
MEDIA_SUFFIXES = (".png", ".pdf")  # manifest files read as media (SPEC F10), never by a text parser
MEDIA_MAX_TOKENS = 16384  # one file's records plus thinking (SPEC N1: fixed max_tokens)
MEDIA_SCHEMA_RETRIES = 1  # one corrective retry when the extraction fails the schema check

MINUTE = 60
HOUR = 60 * MINUTE


class Secret:
    """Holds a credential; repr and str never reveal it."""

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the wrapped value; call only when sending the request."""
        return self._value

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens. cache_read is None when no price is published
    in the claude-api model table (re-verify all prices before a live run)."""

    model: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: Optional[float]


# Verified with the claude-api skill model table (cached 2026-10-06) and
# Opus 5.5 $4/$20 with cache reads $0.20; Haiku 5.5
# $0.10/$0.50 for prompts up to 100K tokens (no cache-read price listed).
DEFAULT_PRICES: Tuple[ModelPrice, ...] = (
    ModelPrice("claude-opus-5-5", 4.0, 20.0, 0.20),
    ModelPrice("claude-haiku-5-5", 0.10, 0.50, None),
)


@dataclass(frozen=True)
class Flags:
    """Named inference switches; every inference sits behind one (SPEC 10).

    Time is always causal: owners, links and ids use only what exists at a case's
    `audit_at` (SPEC T1), so there is no switch for it.
    """

    verify_legal_holds: bool = True  # SPEC V3
    allow_pre_request_findings: bool = False  # SPEC Q1: exclude
    fifo_pairing: bool = True  # SPEC L6, the low-confidence fallback of the linker
    never_mix: bool = True  # SPEC L5


@dataclass(frozen=True)
class Config:
    """Run configuration; build with `Config.from_env()` and `dataclasses.replace`."""

    dataset_dir: Path = REPO_ROOT / "dataset"
    out_path: Path = REPO_ROOT / "output.csv"
    llm_mode: str = "cache"
    diag_dir: Path = REPO_ROOT / "diagnostics"
    intent_model: str = DEFAULT_INTENT_MODEL
    media_model: str = DEFAULT_MEDIA_MODEL
    prices: Tuple[ModelPrice, ...] = DEFAULT_PRICES
    intent_batch_size: int = 25  # 22 calls for 550 texts
    timeout_s: int = 60
    retries: int = 3
    backoff_base_s: float = 1.0  # retry n sleeps backoff_base_s * 2**n plus jitter
    cache_dir: Path = REPO_ROOT / "code" / "ghostaudit" / "cache"  # committed LLM responses
    agent: str = "on"  # "on": the bounded tool-calling agent resolves contested links; "off": deterministic fallback only
    agent_model: str = DEFAULT_AGENT_MODEL
    router_model: str = DEFAULT_ROUTER_MODEL
    verifier_model: str = DEFAULT_VERIFIER_MODEL
    agent_max_usd: float = DEFAULT_AGENT_MAX_USD  # per-run cap on live agent spend (UsageMeter)
    flags: Flags = field(default_factory=Flags)
    api_key: Optional[Secret] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.llm_mode not in LLM_MODES:
            raise ValueError("llm_mode must be one of %s" % (LLM_MODES,))
        if self.agent not in AGENT_MODES:
            raise ValueError("agent must be one of %s" % (AGENT_MODES,))

    @classmethod
    def from_env(
        cls, environ: Optional[Mapping[str, str]] = None, dotenv: Optional[Path] = None
    ) -> "Config":
        """Build a Config; the only place the environment is read (SPEC N4).

        With no `environ` it reads `os.environ` and, for a variable the environment
        lacks, the repo-root `.env`. An explicit `environ` is the whole environment
        unless a `dotenv` file is passed as well.
        """
        if environ is None:
            environ = os.environ
            dotenv = DOTENV_PATH if dotenv is None else dotenv
        values = read_dotenv(dotenv) if dotenv is not None else {}
        values.update(environ)
        key = values.get(API_KEY_ENV)
        return cls(api_key=Secret(key) if key else None)


def read_dotenv(path: Path) -> Dict[str, str]:
    """`KEY=VALUE` lines of a `.env` file; {} when it is missing. Values are never logged.

    Blank lines and `#` comments are skipped, an `export ` prefix is allowed and one
    pair of matching surrounding quotes is removed from a value.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(DOTENV_EXPORT):
            line = line[len(DOTENV_EXPORT):].lstrip()
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in DOTENV_QUOTES:
            value = value[1:-1]
        values[name.strip()] = value
    return values
