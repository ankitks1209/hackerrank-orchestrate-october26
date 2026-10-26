"""Pipeline orchestration: dataset in, validated case results out (SPEC A1, N6, N7).

Implements the data flow of ARCHITECTURE.md and nothing else. Each stage is a
call into the module that owns it:

1. media pre-pass (`extract_media_facts`; no facts under `--llm off` or on a cache miss);
2. evidence index; 3. intent; 4. links (solver, then extras) and per-case build and emit, which is
   the deterministic result and the fallback of everything below;
5. the agent stage (router, investigation units, verifier; `--agent on` with a model) re-solves the
   contested links with the model's accepted decisions and rebuilds the cases (SPEC 12);
6. inline contract validation of every emitted set (SPEC 8.4, N8).

Intent, links and verdicts are computed for the samples as well as the evaluation
requests, because linking needs both (SPEC 7). The caller decides which set to write.
A degraded path (cache miss, disabled LLM, skipped evidence file) never stops the run
(SPEC N7); it is recorded in the result for `diagnostics`.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, List, Mapping, Sequence, Tuple

from ghostaudit.activity import classify_activity, unclassified_ids
from ghostaudit.agent.identity_view import IdentityView
from ghostaudit.agent.model import REASON_DISABLED, AgentStats, UnitOutcome
from ghostaudit.agent.stage import AgentRun, AgentStage, Solved, disabled_run
from ghostaudit.agent.workspace import WorldView
from ghostaudit.casebuilder import BuildStats, CaseBuilder
from ghostaudit.config import MEDIA_SUFFIXES, Config
from ghostaudit.contract import Citations, ValidationResult, validate
from ghostaudit.dataset import DatasetReader
from ghostaudit.emit import OUTPUT_COLUMNS, case_sort_key, emit, serialize
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.handcrafted import HandcraftedSources
from ghostaudit.identity import IdentityIndex
from ghostaudit.intent import IntentClassifier, IntentDecision, IntentResult, intake_rows
from ghostaudit.link_graph import ACCOUNT_NONE, LinkDecision, LinkStats
from ghostaudit.link_solver import LinkSession
from ghostaudit.linking import ExtraStats, add_extras
from ghostaudit.llm.cache import CachingClient, DiskCache, Redactor
from ghostaudit.llm.client import AnthropicClient, LLMClient, NullClient
from ghostaudit.llm.media_extract import (
    PROMPT_VERSION as MEDIA_PROMPT,
    REDACTION_NOTE,
    extract_media_facts,
    redact_reply,
)
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import (
    STATUS_NOT_APPLICABLE,
    CaseLinks,
    CaseResult,
    ClassifiedActivity,
    Request,
    ResourceVerdict,
)
from ghostaudit.policy import PolicyEngine
from ghostaudit.state import StateResolver

LOGGER = logging.getLogger(__name__)

STAGE_MEDIA = "media extraction"
STAGE_INDEX = "evidence index"
STAGE_INTENT = "intent"
STAGE_LINKS = "links"
STAGE_AGENT = "agent"
STAGE_VALIDATE = "contract validation"


@dataclass(frozen=True)
class LLMServices:
    """The LLM collaborators of a run: a (caching) client, its disk cache and the usage meter."""

    client: LLMClient
    cache: DiskCache
    meter: UsageMeter


def build_services(config: Config) -> LLMServices:
    """Client stack for the mode: nothing live unless `--llm live` (SPEC N7)."""
    cache = DiskCache(config.cache_dir)
    meter = UsageMeter(config.prices)
    inner: LLMClient = NullClient()
    if config.llm_mode == "live":
        inner = AnthropicClient.from_config(config)
    redactors = {MEDIA_PROMPT: Redactor(REDACTION_NOTE, redact_reply)}  # DECISIONS D25
    client = CachingClient(inner, cache, meter, config.llm_mode, redactors)
    return LLMServices(client, cache, meter)


@dataclass(frozen=True)
class CaseRecord:
    """Everything decided for one request: intent, links, verdicts and the emitted result.

    `disagreements` lists evidence/template conflicts the resolver saw for the case
    (SPEC 4); `verdicts` and `links` are empty for a request that is not a deletion.
    """

    request: Request
    decision: IntentDecision
    links: CaseLinks
    verdicts: Tuple[ResourceVerdict, ...]
    result: CaseResult
    disagreements: Tuple[str, ...]


@dataclass(frozen=True)
class RunResult:
    """Outcome of one pipeline run, in natural case order, with what the diagnostics need.

    `unread_media` lists the image and PDF files that yielded no facts (cache miss,
    `--llm off`, rejected extraction): evidence that the run could not read (SPEC N7).
    `unclassified_activity` lists the activity rows that matched no template; they are
    inert and never used for a decision.
    """

    cases: Tuple[CaseRecord, ...]
    intents: IntentResult
    media_notes: Tuple[str, ...]
    unread_media: Tuple[str, ...]
    unclassified_activity: Tuple[str, ...]
    index: EvidenceIndex
    citations: Citations
    agent_stats: AgentStats
    agent_outcomes: Tuple[UnitOutcome, ...]
    link_stats: LinkStats
    extra_stats: ExtraStats
    build_stats: BuildStats
    eval_validation: ValidationResult
    sample_validation: ValidationResult
    timings: Tuple[Tuple[str, float], ...]

    @property
    def eval_results(self) -> Tuple[CaseResult, ...]:
        """Results of the evaluation requests, which are the only rows of output.csv."""
        return tuple(case.result for case in self.cases if not case.request.is_sample)

    @property
    def sample_results(self) -> Tuple[CaseResult, ...]:
        """Results of the public sample requests."""
        return tuple(case.result for case in self.cases if case.request.is_sample)


class _StageTimer:
    """Collects (stage, seconds) in the order the stages ran."""

    def __init__(self) -> None:
        self.timings: List[Tuple[str, float]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.timings.append((name, elapsed))
            LOGGER.info("stage %s took %.2f s", name, elapsed)


def run(config: Config, reader: DatasetReader, llm: LLMServices) -> RunResult:
    """Run every stage over all requests of the dataset and validate what would be written."""
    timer = _StageTimer()
    requests = reader.requests()
    manifest = reader.manifest()
    media_entries = [entry for entry in manifest if entry.path.suffix.lower() in MEDIA_SUFFIXES]
    with timer.stage(STAGE_MEDIA):
        media = extract_media_facts(media_entries, llm.client, config.media_model)
    with timer.stage(STAGE_INDEX):
        identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        acts = classify_activity(reader.activity())
        index = build_index(manifest, identity, media.facts, acts)
        policy = PolicyEngine.from_rules(reader.rules())
    with timer.stage(STAGE_INTENT):
        classifier = IntentClassifier(config, llm.client, llm.cache, llm.meter)
        intents = classifier.classify(requests, intake_rows(requests, acts))
    with timer.stage(STAGE_LINKS):
        # A request that does not authorize deletion owns no deletion-worker run, so it
        # must not compete for one.
        deletions = [req for req in requests if intents.decisions[req.case_id].deletion]
        session = LinkSession(deletions, acts, index, identity, config)
        resolver = StateResolver(index, policy, acts)
        solver = _Solver(config, requests, intents, deletions, acts, index, identity, policy, resolver, session)
        deterministic = solver(()).cases
    unread = tuple(entry.file_id for entry in media_entries if entry.file_id not in media.facts)
    with timer.stage(STAGE_AGENT):
        agent = _run_agent(
            config, reader, llm, deletions, acts, index, identity, policy, session, solver, deterministic, unread
        )
    cases = agent.cases
    citations = Citations.from_reader(reader)
    with timer.stage(STAGE_VALIDATE):
        eval_validation = _validate(cases, requests, citations, is_sample=False)
        sample_validation = _validate(cases, requests, citations, is_sample=True)
    return RunResult(
        cases=cases,
        intents=intents,
        media_notes=media.notes,
        unread_media=unread,
        unclassified_activity=unclassified_ids(acts),
        index=index,
        citations=citations,
        agent_stats=agent.stats,
        agent_outcomes=agent.outcomes,
        link_stats=solver.link_stats,
        extra_stats=solver.extra_stats,
        build_stats=solver.build_stats,
        eval_validation=eval_validation,
        sample_validation=sample_validation,
        timings=tuple(timer.timings),
    )


class _Solver:
    """Links, extras and builds the cases for a set of agent decisions; remembers the last run's statistics.

    A fresh `CaseBuilder` serves every call, so its counters describe exactly one build.
    """

    def __init__(
        self,
        config: Config,
        requests: Sequence[Request],
        intents: IntentResult,
        deletions: Sequence[Request],
        acts: Sequence[ClassifiedActivity],
        index: EvidenceIndex,
        identity: IdentityIndex,
        policy: PolicyEngine,
        resolver: StateResolver,
        session: LinkSession,
    ) -> None:
        self._config = config
        self._requests = requests
        self._intents = intents
        self._deletions = deletions
        self._acts = acts
        self._index = index
        self._identity = identity
        self._policy = policy
        self._resolver = resolver
        self._session = session
        self.link_stats: LinkStats
        self.extra_stats: ExtraStats
        self.build_stats: BuildStats

    def __call__(self, decisions: Sequence[LinkDecision]) -> Solved:
        solved = self._session.solve(decisions)
        extras = add_extras(
            solved.links, self._deletions, self._acts, self._index, self._identity, self._policy, self._config
        )
        sources = HandcraftedSources(self._acts, self._index, self._policy, self._identity)
        builder = CaseBuilder(self._resolver, self._policy, self._index, self._config, sources)
        cases = tuple(
            _build_case(builder, req, self._intents.decisions[req.case_id], extras.links)
            for req in sorted(self._requests, key=lambda item: case_sort_key(item.case_id))
        )
        self.link_stats, self.extra_stats, self.build_stats = solved.stats, extras.stats, builder.stats()
        return Solved(cases, solved.applied)


def _run_agent(
    config: Config,
    reader: DatasetReader,
    llm: LLMServices,
    deletions: Sequence[Request],
    acts: Sequence[ClassifiedActivity],
    index: EvidenceIndex,
    identity: IdentityIndex,
    policy: PolicyEngine,
    session: LinkSession,
    solver: "_Solver",
    deterministic: Tuple[CaseRecord, ...],
    unread: Sequence[str],
) -> AgentRun:
    """The agent stage, or the deterministic cases when the agent is off or no model may be called."""
    if config.agent != "on" or config.llm_mode == "off":
        return disabled_run(deterministic, REASON_DISABLED)
    world = WorldView(
        index=index,
        identity=identity,
        identity_view=IdentityView(reader.identities(), reader.audit_log()),
        policy=policy,
        base=session.base,
        requests={req.case_id: req for req in deletions},
        subjects={req.case_id: identity.resolve(req.email) for req in deletions},
    )
    stage = AgentStage(config, llm.client, llm.meter, world, session.contest(), solver, unread)
    return stage.run(deterministic)


def _build_case(
    builder: CaseBuilder,
    req: Request,
    decision: IntentDecision,
    all_links: Mapping[str, CaseLinks],
) -> CaseRecord:
    """A request that does not authorize deletion is NOT_APPLICABLE with no steps (AGENTS 6.5)."""
    if not decision.deletion:
        result = CaseResult(req.case_id, STATUS_NOT_APPLICABLE, ())
        return CaseRecord(req, decision, CaseLinks(req.case_id, None, ACCOUNT_NONE, (), ()), (), result, ())
    links = all_links[req.case_id]
    verdicts = builder.build(req, links)
    status, steps = emit(verdicts)
    return CaseRecord(
        req, decision, links, verdicts, CaseResult(req.case_id, status, steps),
        _disagreements(verdicts),
    )


def _disagreements(verdicts: Sequence[ResourceVerdict]) -> Tuple[str, ...]:
    """Notes of the resolver where an activity template contradicts the evidence (SPEC 4)."""
    found = {(v.system_id, v.resource_id): v.note for v in verdicts if v.note}
    return tuple("%s/%s: %s" % (system, rid, note) for (system, rid), note in sorted(found.items()))


def _validate(
    cases: Sequence[CaseRecord],
    requests: Sequence[Request],
    citations: Citations,
    is_sample: bool,
) -> ValidationResult:
    """Validate the rows of one request set exactly as they would be written (SPEC 8.4)."""
    rows: List[Sequence[str]] = [list(OUTPUT_COLUMNS)]
    rows.extend(
        (case.result.case_id, case.result.deletion_status, serialize(case.result.steps))
        for case in cases
        if case.request.is_sample == is_sample
    )
    expected = [req for req in requests if req.is_sample == is_sample]
    return validate(rows, expected, citations)
