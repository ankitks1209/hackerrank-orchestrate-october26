"""Strategy comparison, agent ablation, flag ablation and the assumption ledger (SPEC L4-L6, V3, V5, N7, 12).

Every inference sits behind a `Flags` field or the `agent` switch, so its effect is
measured by running the whole pipeline once per variant and comparing:

* sample metrics against the public gold (`evaluation.scoring`);
* the evaluation status distribution and the evaluation link counts of `LinkStats`;
* the number of evaluation rows (status plus steps) that differ from the default run.

Strategies (`strategy_variants`) change only the LLM stack: S0 deterministic only, S1 the
default models (the larger intent model), S2 the cheaper intent model. They replay the committed response cache
and never call the API, so a missing cache entry shows up as a cache miss and that run
degrades to the deterministic path (SPEC N7); the table counts those misses.
The agent ablation (`agent_variants`) runs the pipeline with the agent off (the deterministic
fallback everywhere) and on (replaying whatever agent responses the cache holds) and
reports the evaluation rows each changes. Ablations (`ablation_variants`) flip one flag at a time.
The ledger (`assumption_ledger`) lists, per flag, the assumption cases carrying it in the
default run and the evaluation rows that change when the flag is flipped.
"""
from __future__ import annotations

import dataclasses
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from evaluation.scoring import Report, score
from ghostaudit.config import CHEAP_INTENT_MODEL, Config, Flags
from ghostaudit.dataset import DatasetReader
from ghostaudit.diagnostics import ASSUMPTION_FIFO_ACCOUNT, ASSUMPTION_FIFO_ROWS, case_assumptions
from ghostaudit.link_graph import ACCOUNT_FIFO, ACCOUNT_UNIQUE, ROW_NEVER_MIX
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_NOT_APPLICABLE,
    CaseResult,
    Step,
)
from ghostaudit.pipeline import CaseRecord, RunResult, build_services, run

DEFAULT_NAME = "default"
STRATEGY_REFERENCE = "S1"
OFFLINE_MODES = ("off", "cache")  # an ablation never calls the API
STATUS_ABBREVIATIONS = (
    (STATUS_COMPLETE, "C"),
    (STATUS_INCOMPLETE, "I"),
    (STATUS_NOT_APPLICABLE, "NA"),
)
AGENT_REFERENCE = "agent=off"
NO_COUNT = "-"


@dataclass(frozen=True)
class Variant:
    """One pipeline configuration; `flag` and `setting` name what an ablation changed."""

    name: str
    description: str
    config: Config
    flag: Optional[str] = None
    setting: str = ""


@dataclass(frozen=True)
class Usage:
    """LLM usage of one run: calls and tokens served from the cache and their cold-run price."""

    calls: int
    tokens: int
    cost_usd: Optional[float]  # None when a model used has no price


@dataclass(frozen=True)
class Outcome:
    """A variant, its run, its sample score and what the run cost."""

    variant: Variant
    result: RunResult
    report: Report
    usage: Usage
    seconds: float

    @property
    def eval_rows(self) -> Dict[str, Tuple[str, Tuple[Step, ...]]]:
        """Status and steps of every evaluation case, the unit that `differing` compares."""
        return {case.case_id: (case.deletion_status, case.steps) for case in self.result.eval_results}


def strategy_variants(base: Config) -> List[Variant]:
    """S0 deterministic only, S1 default models, S2 the cheaper intent model."""
    cached = dataclasses.replace(base, llm_mode="cache")
    return [
        Variant("S0", "deterministic only (--llm off)", dataclasses.replace(base, llm_mode="off")),
        Variant("S1", "%s intent + %s media (default)" % (cached.intent_model, cached.media_model), cached),
        Variant(
            "S2",
            "%s intent + %s media" % (CHEAP_INTENT_MODEL, cached.media_model),
            dataclasses.replace(cached, intent_model=CHEAP_INTENT_MODEL),
        ),
    ]


def ablation_variants(base: Config) -> List[Variant]:
    """The default and every flag flipped once."""
    variants = [Variant(DEFAULT_NAME, "all flags at their defaults", base)]
    for field in dataclasses.fields(Flags):
        flipped = not getattr(base.flags, field.name)
        setting = "on" if flipped else "off"
        flags = dataclasses.replace(base.flags, **{field.name: flipped})
        variants.append(Variant(
            "%s=%s" % (field.name, setting), "%s flipped to %s" % (field.name, setting),
            dataclasses.replace(base, flags=flags), field.name, setting,
        ))
    return variants


def agent_variants(base: Config) -> List[Variant]:
    """The agent off (deterministic fallback everywhere, the reference) and on (cache replay)."""
    cached = dataclasses.replace(base, llm_mode="cache")
    return [
        Variant(AGENT_REFERENCE, "deterministic fallback everywhere", dataclasses.replace(cached, agent="off")),
        Variant("agent=on", "router, agent and verifier replayed from the cache", dataclasses.replace(cached, agent="on")),
    ]


def run_variant(variant: Variant, reader: DatasetReader, gold: Mapping[str, CaseResult]) -> Outcome:
    """Run the pipeline for `variant` offline and score its sample predictions."""
    config = variant.config
    if config.llm_mode not in OFFLINE_MODES:
        raise ValueError("ablations run offline, not with llm_mode %r" % config.llm_mode)
    services = build_services(config)
    started = time.perf_counter()
    result = run(config, reader, services)
    seconds = time.perf_counter() - started
    predictions = {case.case_id: case for case in result.sample_results}
    return Outcome(variant, result, score(gold, predictions), _usage(services.meter), seconds)


def run_variants(
    variants: Sequence[Variant], reader: DatasetReader, gold: Mapping[str, CaseResult]
) -> List[Outcome]:
    """Outcomes in the order of `variants`."""
    return [run_variant(variant, reader, gold) for variant in variants]


def differing(outcome: Outcome, reference: Outcome) -> int:
    """Evaluation cases whose status or steps differ from the reference run."""
    mine, other = outcome.eval_rows, reference.eval_rows
    return sum(1 for case_id in sorted(set(mine) | set(other)) if mine.get(case_id) != other.get(case_id))


def _usage(meter: UsageMeter) -> Usage:
    calls = tokens = 0
    costs: List[Optional[float]] = []
    for model in meter.models():
        usage = meter.usage(model)
        calls += usage.live.calls + usage.replayed.calls
        tokens += usage.live.total_tokens + usage.replayed.total_tokens
        costs += [meter.cost(model), meter.cost(model, replayed=True)]
    priced = all(cost is not None for cost in costs)
    return Usage(calls, tokens, sum(cost for cost in costs if cost is not None) if priced else None)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines + [""]


def _eval_steps(outcome: Outcome) -> int:
    return sum(len(case.steps) for case in outcome.result.eval_results)


def _status_mix(outcome: Outcome) -> str:
    counts = Counter(case.deletion_status for case in outcome.result.eval_results)
    return " ".join("%s=%d" % (short, counts[status]) for status, short in STATUS_ABBREVIATIONS)


def _sample_cells(outcome: Outcome) -> List[str]:
    report = outcome.report
    status_ok = report.cases - len(report.status_mismatches)
    exact = report.cases - len(report.inexact_cases)
    return [
        "%d/%d" % (status_ok, report.cases),
        "%d/%d" % (exact, report.cases),
        "%.4f / %.4f / %.4f" % (report.details["precision"], report.details["recall"], report.raw["G3"]),
        "%.4f" % report.raw["G5"],
        "%.4f / %.4f" % (report.details["exact_order"], report.raw["G6"]),
    ]


def _cache_misses(outcome: Outcome) -> int:
    result = outcome.result
    return len(result.intents.missing_llm) + len(result.media_notes)


def _cost(usage: Usage) -> str:
    return "unpriced" if usage.cost_usd is None else "$%.4f" % usage.cost_usd


def render_strategies(outcomes: Sequence[Outcome]) -> str:
    """Markdown table comparing the LLM strategies; the reference is S1."""
    reference = next(outcome for outcome in outcomes if outcome.variant.name == STRATEGY_REFERENCE)
    header = (
        "Strategy", "Description", "Sample status", "Sample exact", "Step P / R / F1", "Field acc.",
        "Sequence exact / LCS", "Eval status", "Eval rows differing from %s" % STRATEGY_REFERENCE,
        "Cache misses", "Cached calls", "Tokens", "Cold-run cost",
    )
    rows = [
        [outcome.variant.name, outcome.variant.description] + _sample_cells(outcome) + [
            _status_mix(outcome), str(differing(outcome, reference)), str(_cache_misses(outcome)),
            str(outcome.usage.calls), str(outcome.usage.tokens), _cost(outcome.usage),
        ]
        for outcome in outcomes
    ]
    notes = [
        "Calls, tokens and cost are replayed from the committed cache (no API calls are made); "
        "the cost is what a cold run would pay.",
        "A cache miss means the run fell back to the deterministic path for that item (SPEC N7).",
        "Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE.",
        "Wall time is left out so that the table is a pure function of the code and the cache; a run takes about a second.",
    ]
    return "\n".join(["## Strategy comparison", ""] + _table(header, rows) + notes) + "\n"


def render_agent(outcomes: Sequence[Outcome]) -> str:
    """Markdown table comparing the agent off and on; the reference is the agent off."""
    reference = outcomes[0]
    header = (
        "Variant", "Description", "Sample status", "Sample exact", "Step P / R / F1", "Field acc.",
        "Sequence exact / LCS", "Eval status", "Eval rows differing from %s" % AGENT_REFERENCE,
        "Units investigated", "Units fallen back", "Cached calls", "Tokens", "Cold-run cost",
    )
    rows = []
    for outcome in outcomes:
        stats = outcome.result.agent_stats
        rows.append(
            [outcome.variant.name, outcome.variant.description] + _sample_cells(outcome) + [
                _status_mix(outcome), str(differing(outcome, reference)), str(stats.units),
                str(stats.fallbacks), str(outcome.usage.calls), str(outcome.usage.tokens), _cost(outcome.usage),
            ]
        )
    notes = [
        "The agent=on row replays the router, agent and verifier responses of the live run from the cache; "
        "a unit with no cached response falls back, so on an empty cache the two rows are identical.",
        "Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE.",
    ]
    return "\n".join(["## Agent ablation", ""] + _table(header, rows) + notes) + "\n"


def _link_cells(outcome: Outcome) -> List[str]:
    stats = outcome.result.link_stats
    return [
        "%d / %d" % (stats.eval_account_basis.get(ACCOUNT_UNIQUE, 0), stats.eval_account_basis.get(ACCOUNT_FIFO, 0)),
        "%d / %d" % (stats.eval_rows_ambiguous, stats.eval_rows_unresolved),
    ]


def render_ablation(outcomes: Sequence[Outcome]) -> str:
    """Markdown table of all variants with the default named, then the assumption ledger."""
    reference = outcomes[0]
    header = (
        "Variant", "Sample status", "Sample exact", "Step P / R / F1", "Field acc.",
        "Sequence exact / LCS", "Eval status", "Eval steps", "Eval accounts unique / FIFO",
        "Eval rows ambiguous / unresolved", "Eval rows differing from default",
    )
    rows = [
        [outcome.variant.name + (" (default)" if outcome is reference else "")]
        + _sample_cells(outcome) + [_status_mix(outcome), str(_eval_steps(outcome))] + _link_cells(outcome)
        + [str(differing(outcome, reference))]
        for outcome in outcomes
    ]
    notes = ["Eval status: C=COMPLETE, I=INCOMPLETE, NA=NOT_APPLICABLE."]
    sections = ["## Ablation variants", ""] + _table(header, rows) + notes + [""]
    return "\n".join(sections + render_ledger(assumption_ledger(outcomes))) + "\n"


@dataclass(frozen=True)
class LedgerRow:
    """One flag: its default, where the default run relies on it and what flipping it changes."""

    flag: str
    default: str
    fired: str
    changed: str


def _eval_cases(result: RunResult) -> List[CaseRecord]:
    return [case for case in result.cases if not case.request.is_sample]


def _cases_with(result: RunResult, labels: Tuple[str, ...]) -> int:
    """Evaluation cases whose links carry at least one of the assumption `labels`."""
    return sum(1 for case in _eval_cases(result) if any(label in labels for label in case_assumptions(case)))


def _never_mix_cases(result: RunResult) -> int:
    return sum(
        any(res.basis == ROW_NEVER_MIX for res in case.links.resources) for case in _eval_cases(result)
    )


def _fired(flag: str, result: RunResult) -> str:
    """Eval cases that carry the assumption of `flag` in the default run."""
    if flag == "fifo_pairing":
        return "%d eval cases" % _cases_with(result, (ASSUMPTION_FIFO_ACCOUNT, ASSUMPTION_FIFO_ROWS))
    if flag == "never_mix":
        return "%d eval cases" % _never_mix_cases(result)
    return NO_COUNT


def assumption_ledger(outcomes: Sequence[Outcome]) -> List[LedgerRow]:
    """One row per flag, from the default run and its ablation variants."""
    reference = outcomes[0]
    rows: List[LedgerRow] = []
    names = [field.name for field in dataclasses.fields(Flags)]
    for name in names:
        varied = [outcome for outcome in outcomes if outcome.variant.flag == name]
        changed = ", ".join(
            "%s: %d" % (outcome.variant.setting, differing(outcome, reference)) for outcome in varied
        )
        default = getattr(reference.variant.config.flags, name, None)
        rows.append(LedgerRow(name, str(default), _fired(name, reference.result), changed or NO_COUNT))
    return rows


def render_ledger(rows: Sequence[LedgerRow]) -> List[str]:
    """Markdown lines of the assumption ledger."""
    header = ("Flag", "Default", "Relied on in the default run", "Eval rows changed when flipped")
    notes = [
        "`-` in the third column means the diagnostics keep no per-case counter for that flag; "
        "the last column is then the only measure of its effect.",
    ]
    table = _table(header, [[row.flag, row.default, row.fired, row.changed] for row in rows])
    return ["## Assumption ledger", ""] + table + notes + [""]
