"""Intent classification: does a request authorize deletion? (SPEC 9).

Implements SPEC 9.1 (LLM classifier with per-item cache keys), 9.2 (the lexicon
in `intent_lexicon`), 9.3 (intake `non-deletion` rows are corroboration only)
and 9.4 (resolution and the agreement matrix).

* Per-item cache: the key is sha256(model, prompt hash, normalized text), so a
  verdict never depends on batch composition. Identical texts share one entry
  and only cache misses travel to the model, in batches of at most
  `Config.intent_batch_size`. Each item remembers the key of the batch response
  that produced it, so a replay can be metered once per batch. Item entries are
  written whenever a batch answers, even from the disk cache, so an interrupted
  fill is completed by the next live run.
* Resolution: the model decides when it answered with confidence at or above
  `INTENT_CONFIDENCE_FLOOR`; otherwise (no answer, cache miss, `--llm off`, low
  confidence) the lexicon decides.
* Intake rows never change a decision. `intake_rows` only lists the activity
  rows that fall into a request's account window, to fill the third axis of
  the agreement matrix. The window is an over-approximation: it cannot tell
  two requests with the same report time apart, because attributing an account
  to a user is the job of linking, which runs after intent.
"""
from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ghostaudit.config import INTENT_CONFIDENCE_FLOOR, INTENT_MAX_TOKENS, Config
from ghostaudit.intent_lexicon import classify_text
from ghostaudit.llm.cache import DiskCache, request_key
from ghostaudit.llm.client import LLMClient, LLMError, LLMRequest, LLMResponse
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import ActKind, ClassifiedActivity, Request

LOGGER = logging.getLogger("ghostaudit.intent")

PROMPT_VERSION = "intent.v1"
PROMPT_PATH = Path(__file__).resolve().parent / "llm" / "prompts" / (PROMPT_VERSION + ".md")
ITEM_STOP_REASON = "intent_item"
SOURCE_LLM = "llm"
SOURCE_LEXICON = "lexicon"
FALLBACK_NONE = ""
FALLBACK_NO_VERDICT = "no_llm_verdict"
FALLBACK_LOW_CONFIDENCE = "low_confidence"
LABEL_DELETION = "DELETION"
LABEL_NON_DELETION = "NON_DELETION"
LABEL_NO_LLM = "NO_LLM"
LABEL_INTAKE = "N_ROW"
LABEL_NO_INTAKE = "NO_N_ROW"
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0
LEXICON_ONLY_MODE = "off"
LIVE_MODE = "live"

VERDICT_KEYS = ("case_id", "deletion", "confidence", "language", "reason")
VERDICT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "deletion": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "language": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": list(VERDICT_KEYS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LLMVerdict:
    """One model answer for one distinct request text."""

    deletion: bool
    confidence: float
    language: str
    reason: str


@dataclass(frozen=True)
class IntentDecision:
    """Resolved intent of one request with the evidence behind it (SPEC 9.4)."""

    case_id: str
    deletion: bool
    source: str
    fallback_reason: str
    lexicon_deletion: bool
    lexicon_signal: str
    llm: Optional[LLMVerdict]
    intake_rows: Tuple[str, ...]


@dataclass(frozen=True)
class IntentResult:
    """Decisions by case id, the cases that lacked a model verdict, and run notes."""

    decisions: Mapping[str, IntentDecision]
    missing_llm: Tuple[str, ...]
    notes: Tuple[str, ...]


def normalize_text(text: str) -> str:
    """NFC with whitespace collapsed: the form that is hashed and sent."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def load_prompt(path: Path = PROMPT_PATH) -> str:
    """The versioned system prompt (SPEC 9.1)."""
    return path.read_text(encoding="utf-8")


def prompt_hash(prompt: str) -> str:
    """SHA-256 of the system prompt; editing the prompt changes every item key."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def item_key(model: str, hashed_prompt: str, text: str) -> str:
    """Per-item cache key: sha256(model, prompt hash, normalized text) (SPEC 9.1)."""
    canonical = json.dumps([model, hashed_prompt, normalize_text(text)], ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_payload(items: Sequence[Tuple[str, str]]) -> str:
    """User message: each (id, text) wrapped in a delimiter block, escaped as data."""
    blocks = ['<request id="%s">\n%s\n</request>' % (_escape(rid), _escape(text)) for rid, text in items]
    return "\n\n".join(blocks)


def _verdict_from_item(item: Any) -> Optional[Tuple[str, LLMVerdict]]:
    """(case_id, verdict) for a well-formed model item, else None."""
    if not isinstance(item, dict) or set(item) != set(VERDICT_KEYS):
        return None
    confidence = item["confidence"]
    valid = (
        isinstance(item["case_id"], str)
        and isinstance(item["deletion"], bool)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and CONFIDENCE_MIN <= confidence <= CONFIDENCE_MAX
        and isinstance(item["language"], str)
        and isinstance(item["reason"], str)
    )
    if not valid:
        return None
    verdict = LLMVerdict(item["deletion"], float(confidence), item["language"], item["reason"])
    return item["case_id"], verdict


def parse_verdicts(text: str, expected: Iterable[str]) -> Dict[str, LLMVerdict]:
    """Valid verdicts for ids in `expected`; an id answered twice or badly is dropped."""
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    items = payload.get("verdicts") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    wanted = set(expected)
    found: Dict[str, LLMVerdict] = {}
    seen: Counter = Counter()
    for item in items:
        parsed = _verdict_from_item(item)
        if parsed is None:
            continue
        seen[parsed[0]] += 1
        found[parsed[0]] = parsed[1]
    return {rid: found[rid] for rid in sorted(wanted) if seen[rid] == 1}


def _entry_text(verdict: LLMVerdict, batch_key: str) -> str:
    return json.dumps(
        {
            "batch": batch_key,
            "confidence": verdict.confidence,
            "deletion": verdict.deletion,
            "language": verdict.language,
            "reason": verdict.reason,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _read_entry(response: LLMResponse) -> Optional[Tuple[LLMVerdict, str]]:
    """(verdict, batch key) from a stored item entry; None if it is damaged."""
    try:
        entry = json.loads(response.text)
        batch_key = entry["batch"]
        parsed = _verdict_from_item({**{k: v for k, v in entry.items() if k != "batch"}, "case_id": ""})
    except (ValueError, KeyError, TypeError):
        return None
    if parsed is None or not isinstance(batch_key, str):
        return None
    return parsed[1], batch_key


def _lexicon_label(deletion: bool) -> str:
    return LABEL_DELETION if deletion else LABEL_NON_DELETION


def intake_rows(
    requests: Sequence[Request],
    acts: Iterable[ClassifiedActivity],
) -> Dict[str, Tuple[str, ...]]:
    """Intake `non-deletion` activity ids between each request and its report (SPEC 9.3).

    Intake classifies a request after it is submitted and before the workflow reports,
    so a row counts for a request when `requested_at < t <= reported_at`. A row may be
    listed for several requests; the matrix treats it as a candidate only.
    """
    rows = sorted((act.t, act.activity_id) for act in acts if act.kind is ActKind.NON_DELETION)
    found: Dict[str, Tuple[str, ...]] = {}
    for request in requests:
        ids = tuple(
            rid for moment, rid in rows if request.requested_at < moment <= request.reported_at
        )
        if ids:
            found[request.case_id] = ids
    return found


class IntentClassifier:
    """Resolves the intent of every request from the model and the lexicon."""

    def __init__(
        self, config: Config, client: LLMClient, cache: DiskCache, meter: UsageMeter
    ) -> None:
        self._config = config
        self._client = client
        self._cache = cache
        self._meter = meter
        self._prompt = load_prompt()
        self._prompt_hash = prompt_hash(self._prompt)
        self._notes: List[str] = []

    def _key(self, text: str) -> str:
        return item_key(self._config.intent_model, self._prompt_hash, text)

    def _note(self, message: str) -> None:
        """Record a run note for the diagnostics and log it."""
        LOGGER.warning(message)
        self._notes.append(message)

    def build_request(self, items: Sequence[Tuple[str, str]]) -> LLMRequest:
        return LLMRequest(
            model=self._config.intent_model,
            system=self._prompt,
            messages=(("user", build_payload(items)),),
            max_tokens=INTENT_MAX_TOKENS,
            prompt_version=PROMPT_VERSION,
            schema=VERDICT_SCHEMA,
        )

    def _replay_batches(self, batch_keys: Iterable[str]) -> None:
        """Meter each replayed batch once, at the spend a cold run would incur."""
        for batch_key in sorted(set(batch_keys)):
            response = self._cache.get(batch_key)
            if response is not None:
                self._meter.record_replay(self.build_request(()), response)

    def _lookup(self, keys: Iterable[str]) -> Dict[str, LLMVerdict]:
        """Stored verdicts by item key; replayed usage is metered here."""
        found: Dict[str, LLMVerdict] = {}
        batch_keys: List[str] = []
        for key in sorted(set(keys)):
            stored = self._cache.get(key)
            entry = None if stored is None else _read_entry(stored)
            if entry is not None:
                found[key] = entry[0]
                batch_keys.append(entry[1])
        self._replay_batches(batch_keys)
        return found

    def _ask(self, items: Sequence[Tuple[str, str]]) -> Optional[Dict[str, LLMVerdict]]:
        """One model call for (id, text) items; None when the call failed.

        Each valid verdict is stored per item for later runs, also when the batch
        itself was replayed from the disk cache.
        """
        request = self.build_request(items)
        try:
            response = self._client.complete(request)
        except LLMError as exc:
            self._note("intent batch of %d failed: %s" % (len(items), exc))
            return None
        verdicts = parse_verdicts(response.text, [rid for rid, _ in items])
        batch_key = request_key(request)
        for rid, text in items:
            if rid in verdicts:
                self._store(self._key(text), verdicts[rid], batch_key)
        return verdicts

    def _store(self, key: str, verdict: LLMVerdict, batch_key: str) -> None:
        self._cache.put(
            key,
            LLMResponse(
                text=_entry_text(verdict, batch_key),
                input_tokens=0,
                output_tokens=0,
                model=self._config.intent_model,
                cached=False,
                stop_reason=ITEM_STOP_REASON,
            ),
        )

    def _classify_misses(self, units: Sequence[Tuple[str, str]]) -> Dict[str, LLMVerdict]:
        """Verdicts by unit id: batches first, then the dropped ids one by one."""
        size = self._config.intent_batch_size
        answered: Dict[str, LLMVerdict] = {}
        for start in range(0, len(units), size):
            batch = units[start:start + size]
            verdicts = self._ask(batch)
            if verdicts is None:
                continue
            answered.update(verdicts)
            for unit in batch:
                if unit[0] not in verdicts:
                    self._note("intent id %s missing from the batch answer; retried alone" % unit[0])
                    answered.update(self._ask([unit]) or {})
        return answered

    def _llm_verdicts(self, requests: Sequence[Request]) -> Dict[str, LLMVerdict]:
        """Model verdicts by case id for every request that has one."""
        if self._config.llm_mode == LEXICON_ONLY_MODE:
            return {}
        keys = {request.case_id: self._key(request.text) for request in requests}
        by_key = self._lookup(keys.values())
        if self._config.llm_mode == LIVE_MODE:
            by_key.update(self._classify_missing_keys(requests, keys, by_key))
        return {rid: by_key[key] for rid, key in keys.items() if key in by_key}

    def _classify_missing_keys(
        self, requests: Sequence[Request], keys: Mapping[str, str], known: Mapping[str, LLMVerdict]
    ) -> Dict[str, LLMVerdict]:
        """Ask the model once per distinct uncached text; return verdicts by item key."""
        units: List[Tuple[str, str]] = []
        unit_key: Dict[str, str] = {}
        queued = set(known)
        for request in requests:
            key = keys[request.case_id]
            if key in queued:
                continue
            queued.add(key)
            units.append((request.case_id, normalize_text(request.text)))
            unit_key[request.case_id] = key
        answered = self._classify_misses(units)
        return {unit_key[rid]: verdict for rid, verdict in answered.items()}

    def classify(
        self, requests: Sequence[Request], intake: Optional[Mapping[str, Tuple[str, ...]]] = None
    ) -> IntentResult:
        """Resolve every request (SPEC 9.4); `intake` only feeds the diagnostics matrix."""
        self._notes = []
        intake = intake or {}
        verdicts = self._llm_verdicts(requests)
        decisions: Dict[str, IntentDecision] = {}
        for request in requests:
            decisions[request.case_id] = _resolve(
                request, verdicts.get(request.case_id), intake.get(request.case_id, ())
            )
        missing = tuple(
            sorted(rid for rid, d in decisions.items() if d.llm is None and self._config.llm_mode != LEXICON_ONLY_MODE)
        )
        return IntentResult(decisions, missing, tuple(self._notes))


def _resolve(
    request: Request, llm: Optional[LLMVerdict], intake: Tuple[str, ...]
) -> IntentDecision:
    lexicon = classify_text(request.text)
    if llm is None:
        reason, source, deletion = FALLBACK_NO_VERDICT, SOURCE_LEXICON, lexicon.deletion
    elif llm.confidence < INTENT_CONFIDENCE_FLOOR:
        reason, source, deletion = FALLBACK_LOW_CONFIDENCE, SOURCE_LEXICON, lexicon.deletion
    else:
        reason, source, deletion = FALLBACK_NONE, SOURCE_LLM, llm.deletion
    return IntentDecision(
        case_id=request.case_id,
        deletion=deletion,
        source=source,
        fallback_reason=reason,
        lexicon_deletion=lexicon.deletion,
        lexicon_signal=lexicon.signal,
        llm=llm,
        intake_rows=intake,
    )


def agreement_matrix(decisions: Iterable[IntentDecision]) -> Dict[Tuple[str, str, str], int]:
    """Counts by (lexicon label, model label, intake label) (SPEC 9.4)."""
    counts: Counter = Counter()
    for decision in decisions:
        model = LABEL_NO_LLM if decision.llm is None else _lexicon_label(decision.llm.deletion)
        intake = LABEL_INTAKE if decision.intake_rows else LABEL_NO_INTAKE
        counts[(_lexicon_label(decision.lexicon_deletion), model, intake)] += 1
    return dict(counts)


def disagreements(decisions: Iterable[IntentDecision]) -> Tuple[IntentDecision, ...]:
    """Decisions where the lexicon and a model verdict differ, in case-id order (SPEC 9.4)."""
    return tuple(
        sorted(
            (d for d in decisions if d.llm is not None and d.llm.deletion != d.lexicon_deletion),
            key=lambda d: d.case_id,
        )
    )


def render_matrix(decisions: Iterable[IntentDecision]) -> List[str]:
    """Markdown table of the agreement matrix, rows in sorted label order."""
    matrix = agreement_matrix(decisions)
    lines = ["| lexicon | model | intake row | requests |", "|---|---|---|---|"]
    for (lexicon, model, intake), count in sorted(matrix.items()):
        lines.append("| %s | %s | %s | %d |" % (lexicon, model, intake, count))
    return lines
