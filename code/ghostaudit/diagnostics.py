"""Run diagnostics as Markdown: reasons, link basis, assumptions, disagreements (SPEC N6).

Implements SPEC N6 (per-case reasons, link basis, assumption flags fired, evidence and
template disagreements, cache misses), SPEC 3.1 (unknown events), SPEC 9.4 (intent
agreement matrix) and the stage timings. Every emitted step is
listed with the provenance locator of the evidence it cites (file plus row, line or
snapshot) so that it can be checked against the source.

Rendering is a pure function of a `RunResult`; `write_diagnostics` is the only I/O.
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path
from typing import List, Mapping, Sequence

from ghostaudit.config import Config
from ghostaudit.casebuilder import BASIS_ACCOUNT
from ghostaudit.contract import Citations, ValidationResult
from ghostaudit.emit import case_sort_key
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.intent import disagreements, render_matrix
from ghostaudit.link_graph import ACCOUNT_AGENT, ACCOUNT_FIFO, ROW_AGENT, ROW_FIFO
from ghostaudit.model import Step
from ghostaudit.pipeline import CaseRecord, RunResult

DIAGNOSTICS_NAME = "diagnostics.md"
UNKNOWN_EVENT = "unknown_event"
MAX_LISTED = 20  # ids shown inline before a list is cut with "..."
NO_CITE = "none (remediation or verification still to be done)"
AUDIT_SOURCE = "user_audit_log.csv"
ACTIVITY_SOURCE = "system_activity.csv"
ASSUMPTION_FIFO_ACCOUNT = "account by FIFO pairing"
ASSUMPTION_FIFO_ROWS = "worker rows by FIFO pairing"
ASSUMPTION_AGENT = "contested links decided by the agent"


def write_diagnostics(result: RunResult, config: Config, directory: Path) -> Path:
    """Write `diagnostics.md` into `directory` (created when missing) and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DIAGNOSTICS_NAME
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(result, config))
    return path


def render(result: RunResult, config: Config) -> str:
    """The whole report: run summary first, then one section per case."""
    lines: List[str] = ["# Run diagnostics", ""]
    for section in (
        _summary(result, config),
        _timings(result),
        _llm_section(result),
        _intent_section(result),
        _link_section(result),
        _agent_section(result),
        _build_section(result),
        _evidence_section(result),
        _validation_section(result),
        _case_sections(result),
    ):
        lines.extend(section)
    return "\n".join(lines) + "\n"


def step_provenance(step: Step, index: EvidenceIndex, citations: Citations) -> str:
    """Where in the participant data the step's cited evidence was read."""
    cite = step.evidence_id
    if not cite:
        return NO_CITE
    if cite in citations.activities:
        return "%s:%s" % (ACTIVITY_SOURCE, cite)
    if cite in citations.audits:
        return "%s:%s" % (AUDIT_SOURCE, cite)
    entry = index.entries.get(cite)
    if entry is None:
        return "unknown citation"
    where = "%s/%s" % (entry.path.parent.name, entry.path.name)
    locators = sorted(
        obs.locator
        for obs in index.by_rid.get(step.resource_id, ())
        if obs.file_id == cite and obs.system_id == step.system_id
    )
    if locators:
        return "%s @ %s" % (where, "; ".join(sorted(set(locators))))
    if any(scope.system_id == step.system_id for scope in index.scopes_by_file.get(cite, ())):
        return "%s @ scope listing of %s" % (where, step.system_id)
    return where


def _summary(result: RunResult, config: Config) -> List[str]:
    statuses = Counter(case.result.deletion_status for case in result.cases if not case.request.is_sample)
    sample_statuses = Counter(case.result.deletion_status for case in result.cases if case.request.is_sample)
    flags = dataclasses.asdict(config.flags)
    lines = [
        "## Run",
        "",
        "- LLM mode: `%s`; intent model `%s`; media model `%s`"
        % (config.llm_mode, config.intent_model, config.media_model),
        "- Agent: `%s`; agent model `%s`; router model `%s`; verifier model `%s`; live cost cap $%.2f"
        % (config.agent, config.agent_model, config.router_model, config.verifier_model, config.agent_max_usd),
        "- Flags: %s" % ", ".join("%s=%s" % item for item in sorted(flags.items())),
        "- Evaluation requests: %d (%s)" % (sum(statuses.values()), _counts(statuses)),
        "- Sample requests: %d (%s)" % (sum(sample_statuses.values()), _counts(sample_statuses)),
        "- Unclassified activity rows (inert, never used for a decision): %d"
        % len(result.unclassified_activity),
    ]
    if result.unclassified_activity:
        lines.append("  - %s" % _listing(result.unclassified_activity))
    return lines + [""]


def _timings(result: RunResult) -> List[str]:
    lines = ["## Stage timings", "", "| Stage | Seconds |", "|---|---|"]
    lines += ["| %s | %.3f |" % (name, seconds) for name, seconds in result.timings]
    return lines + [""]


def _llm_section(result: RunResult) -> List[str]:
    """Cache misses and disabled calls: every degraded LLM path (SPEC N7)."""
    lines = ["## LLM degradations and cache misses", ""]
    lines.append("- Media extraction notes: %d" % len(result.media_notes))
    lines += ["  - %s" % note for note in result.media_notes]
    lines.append("- Intent requests without a model verdict: %d" % len(result.intents.missing_llm))
    if result.intents.missing_llm:
        lines.append("  - %s" % _listing(sorted(result.intents.missing_llm, key=case_sort_key)))
    lines += ["- Intent note: %s" % note for note in result.intents.notes]
    return lines + [""]


def _intent_section(result: RunResult) -> List[str]:
    decisions = [case.decision for case in result.cases]
    sources = Counter(decision.source for decision in decisions)
    lines = ["## Intent", "", "- Decision source: %s" % _counts(sources), ""]
    lines += render_matrix(decisions)
    differing = disagreements(decisions)
    lines += ["", "Lexicon and model disagree on %d requests." % len(differing)]
    lines += [
        "- %s: lexicon %s, model %s (confidence %.2f), resolved %s"
        % (d.case_id, d.lexicon_deletion, d.llm.deletion, d.llm.confidence, d.deletion)
        for d in differing
        if d.llm is not None
    ]
    return lines + [""]


def _link_section(result: RunResult) -> List[str]:
    stats, extra = result.link_stats, result.extra_stats
    lines = [
        "## Links",
        "",
        "- Account basis (all / evaluation): %s / %s"
        % (_counts(stats.account_basis), _counts(stats.eval_account_basis)),
        "- Worker-row basis: %s" % _counts(stats.row_basis),
        "- Ambiguous worker rows before FIFO: %d (evaluation %d); unresolved before row FIFO: %d (evaluation %d)"
        % (stats.rows_ambiguous, stats.eval_rows_ambiguous, stats.rows_unresolved, stats.eval_rows_unresolved),
    ]
    lines += [
        "- Repopulation rows: %s" % _counts(extra.repopulation_rows),
        "- Resources added by basis (all / evaluation): %s / %s"
        % (_counts(extra.added), _counts(extra.eval_added)),
        "- Audit-record coverage (all / evaluation): %s / %s"
        % (_counts(extra.audit), _counts(extra.eval_audit)),
    ]
    return lines + [""]


def _agent_section(result: RunResult) -> List[str]:
    """The agent stage: routing, units, fallbacks by reason, verifier outcome (SPEC 12.5)."""
    stats = result.agent_stats
    lines = ["## Agent", ""]
    if not stats.enabled:
        reasons = ", ".join(name for name, _count in stats.reasons) or "off"
        return lines + ["- Agent stage not run (%s)." % reasons, ""]
    lines += [
        "- Routing: %d investigate, %d accept (router calls %d%s)"
        % (stats.routed_investigate, stats.routed_accept, stats.router_calls,
           ", router failed: every contested case investigated" if stats.router_failed else ""),
        "- Units: %d (decided by the agent %d, fallback %d); model calls in loops: %d"
        % (stats.units, stats.agent_units, stats.fallback_units, stats.iterations),
        "- Decisions applied to the link graph: %d" % stats.decisions_applied,
        "- Verifier: %d assignments checked, %d rejected" % (stats.verifier_checked, stats.verifier_rejected),
        "- Fallback reasons: %s" % (", ".join("%s=%d" % item for item in stats.reasons) or "none"),
    ]
    for outcome in result.agent_outcomes:
        lines.append(
            "  - %s (%s): %s%s after %d calls; %d decisions, %d left to the fallback"
            % (outcome.unit_id, _listing(outcome.case_ids), outcome.status,
               " (%s)" % outcome.reason if outcome.reason else "", outcome.iterations,
               len(outcome.decisions), len(outcome.unsure))
        )
    return lines + [""]


def _build_section(result: RunResult) -> List[str]:
    stats = result.build_stats
    lines = [
        "## Case building",
        "",
        "- Cases built: %d; hand-crafted family: %d (account basis %s)"
        % (stats.cases, stats.handcrafted_cases, _counts(dict(stats.account_basis))),
        "- Account step omitted (no proof file): %d; account cited by omission rule: %d"
        % (stats.omitted_account, stats.omission_cites),
        "- Resources dropped: %d violating without proof, %d compliant without cite, "
        "%d ABSENT under REDACT or ANONYMIZE"
        % (stats.dropped_violating, stats.dropped_compliant, stats.dropped_absent),
        "- Evidence category overrides: %d" % stats.category_overrides,
    ]
    lines += ["- Untested rules fired: %d" % len(stats.untested)]
    lines += ["  - %s" % item for item in stats.untested]
    lines += ["- Hand-crafted notes: %d" % len(stats.handcrafted_notes)]
    lines += ["  - %s" % item for item in stats.handcrafted_notes]
    blind = [
        "%s: %s with %d steps; unread in-window media %s"
        % (case.request.case_id, case.result.deletion_status, len(case.result.steps), ", ".join(unread))
        for case in result.cases
        if _is_handcrafted(case)
        for unread in (_unread_in_window(case, result),)
        if unread
    ]
    lines += ["- Hand-crafted cases with unread in-window media: %d" % len(blind)]
    lines += ["  - %s" % item for item in blind]
    return lines + [""]


def _is_handcrafted(case: CaseRecord) -> bool:
    """A deletion case without an account row, built by the L12 rules."""
    return case.decision.deletion and case.links.account_id is None


def _unread_in_window(case: CaseRecord, result: RunResult) -> List[str]:
    """Unread media files captured in the case's `[reported_at, audit_at]` window (SPEC T3, N7).

    The manifest does not say which person a file concerns, so this lists what the case
    could have cited, not what it needed; an image-family verdict is degraded exactly when
    its own screen or document is among them.
    """
    request, entries = case.request, result.index.entries
    return [
        file_id
        for file_id in result.unread_media
        if request.reported_at <= entries[file_id].captured_at <= request.audit_at
    ]


def _evidence_section(result: RunResult) -> List[str]:
    notes = result.index.notes
    unknown = [note for note in notes if UNKNOWN_EVENT in note]
    other = [note for note in notes if UNKNOWN_EVENT not in note]
    template = [
        (case.request.case_id, text) for case in result.cases for text in case.disagreements
    ]
    lines = [
        "## Evidence",
        "",
        "- Files parsed: %d of %d" % (len(result.index.claimed_by), len(result.index.entries)),
        "- Unknown events: %d" % len(unknown),
        "  - %s" % _counts(Counter(note.split(UNKNOWN_EVENT, 1)[1].strip() for note in unknown)),
        "- Other parser notes: %d" % len(other),
    ]
    lines += ["  - %s" % note for note in other]
    lines.append("- Evidence/template disagreements: %d" % len(template))
    lines += ["  - %s: %s" % item for item in template]
    return lines + [""]


def _validation_section(result: RunResult) -> List[str]:
    lines = ["## Contract validation", ""]
    for name, validation in (("Evaluation", result.eval_validation), ("Samples", result.sample_validation)):
        lines.append(
            "- %s: %s (%d violations, %d warnings)"
            % (name, "ok" if validation.ok else "FAILED", len(validation.violations), len(validation.warnings))
        )
        lines += _violation_lines(validation)
    return lines + [""]


def _violation_lines(validation: ValidationResult) -> List[str]:
    found = [("violation", item) for item in validation.violations]
    found += [("warning", item) for item in validation.warnings]
    return ["  - %s %s %s: %s" % (kind, item.case_id, item.rule, item.message) for kind, item in found]


def _case_sections(result: RunResult) -> List[str]:
    lines = ["## Cases", ""]
    for case in result.cases:
        lines.extend(_case_section(case, result))
    return lines


def _case_section(case: CaseRecord, result: RunResult) -> List[str]:
    request, decision = case.request, case.decision
    kind = "sample" if request.is_sample else "evaluation"
    lines = ["### %s (%s): %s" % (request.case_id, kind, case.result.deletion_status), ""]
    lines.append(
        "- Intent: %s via %s%s; lexicon signal `%s`"
        % ("deletion" if decision.deletion else "not a deletion", decision.source,
           " (%s)" % decision.fallback_reason if decision.fallback_reason else "", decision.lexicon_signal)
    )
    if not decision.deletion:
        return lines + [""]
    links = case.links
    lines.append("- Account: %s (link basis %s)" % (_account(case), links.account_basis))
    lines.append("- Linked resources: %s" % _counts(Counter(res.basis for res in links.resources)))
    assumptions = case_assumptions(case)
    lines.append("- Assumptions fired: %s" % (", ".join(assumptions) or "none"))
    lines += ["- Link note: %s" % note for note in links.notes]
    unread = _unread_in_window(case, result)
    if unread:
        lines.append("- Unread in-window media: %s" % ", ".join(unread))
    lines += ["- Disagreement: %s" % note for note in case.disagreements]
    lines += [
        "- Verdict %s/%s %s violating=%s basis=%s: %s"
        % (v.system_id, v.resource_id, v.treatment.value, v.violating, v.basis, v.reason)
        for v in case.verdicts
    ]
    lines += [
        "- Step %d %s %s %s/%s cite=%s [%s]"
        % (step.step_no, step.phase, step.operation, step.system_id, step.resource_id,
           step.evidence_id or "-", step_provenance(step, result.index, result.citations))
        for step in case.result.steps
    ]
    return lines + [""]


def _account(case: CaseRecord) -> str:
    """The case account: the linked one, else the one the hand-crafted rules chose (SPEC L12)."""
    if case.links.account_id is not None:
        return case.links.account_id
    for verdict in case.verdicts:
        if verdict.basis == BASIS_ACCOUNT:
            return "%s (hand-crafted rule)" % verdict.resource_id
    return "none"


def case_assumptions(case: CaseRecord) -> List[str]:
    """Inferences that decided this case and that the evidence alone does not settle."""
    found: List[str] = []
    if case.links.account_basis == ACCOUNT_FIFO:
        found.append(ASSUMPTION_FIFO_ACCOUNT)
    if any(res.basis == ROW_FIFO for res in case.links.resources):
        found.append(ASSUMPTION_FIFO_ROWS)
    if case.links.account_basis == ACCOUNT_AGENT or any(res.basis == ROW_AGENT for res in case.links.resources):
        found.append(ASSUMPTION_AGENT)
    return found


def _listing(items: Sequence[str]) -> str:
    """The first MAX_LISTED items, and how many more there are."""
    shown = ", ".join(items[:MAX_LISTED])
    return shown if len(items) <= MAX_LISTED else "%s, ... (%d more)" % (shown, len(items) - MAX_LISTED)


def _counts(counts: Mapping[str, int]) -> str:
    """`name=count` pairs in sorted name order, or `none`."""
    return ", ".join("%s=%d" % item for item in sorted(counts.items())) or "none"
