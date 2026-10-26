"""Workspace: the read-only world one investigation sees (SPEC 12.1, 12.2).

A workspace is built per investigation unit. It exposes only what exists at each case's
`audit_at`: every accessor takes the case and applies its cutoff, so a tool cannot return
evidence captured or activity recorded afterwards, whatever arguments the model passes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

from ghostaudit.agent.identity_view import IdentityView
from ghostaudit.agent.ledger import CitationLedger
from ghostaudit.agent.model import UnitSpec
from ghostaudit.evidence.index import EvidenceIndex
from ghostaudit.identity import IdentityIndex
from ghostaudit.linking import Candidates
from ghostaudit.model import ClassifiedActivity, Observation, Request
from ghostaudit.policy import PolicyEngine


class ToolError(Exception):
    """A tool call that cannot be answered; the message goes back to the model as an error result."""


@dataclass(frozen=True)
class WorldView:
    """The run-wide, immutable inputs shared by every workspace."""

    index: EvidenceIndex
    identity: IdentityIndex
    identity_view: IdentityView
    policy: PolicyEngine
    base: Candidates
    requests: Mapping[str, Request]
    subjects: Mapping[str, Optional[str]]


class Workspace:
    """One unit's cases, the contested targets, the world and the citation ledger."""

    def __init__(self, unit: UnitSpec, world: WorldView) -> None:
        self.unit = unit
        self.world = world
        self.ledger = CitationLedger()
        self._case_ids = frozenset(unit.case_ids)
        self._by_file: Dict[str, List[Observation]] = {}
        for obs in world.index.observations:
            self._by_file.setdefault(obs.file_id, []).append(obs)

    # -- cases ----------------------------------------------------------------

    def request(self, case_id: str) -> Request:
        """The request of a case in this unit; anything else is an error for the model."""
        if case_id not in self._case_ids:
            raise ToolError("case %r is not part of this investigation unit" % case_id)
        return self.world.requests[case_id]

    def subject(self, case_id: str) -> Optional[str]:
        self.request(case_id)
        return self.world.subjects[case_id]

    def audit_at(self, case_id: str) -> int:
        return self.request(case_id).audit_at

    def targets(self) -> FrozenSet[str]:
        """Every activity id the model is asked to decide."""
        return frozenset(self.unit.rows) | frozenset(self.unit.accounts)

    def activity(self, activity_id: str) -> ClassifiedActivity:
        return self.world.base.activities[activity_id]

    # -- admissible evidence --------------------------------------------------

    @staticmethod
    def admissible(obs: Observation, audit_at: int) -> bool:
        """An observation exists for a case only if captured and entered by its `audit_at` (SPEC T1)."""
        return max(obs.captured_at, obs.effective_entry_time) <= audit_at

    def observations_of(self, case_id: str, resource_id: str) -> Tuple[Observation, ...]:
        audit_at = self.audit_at(case_id)
        return tuple(
            obs for obs in self.world.index.by_rid.get(resource_id, ()) if self.admissible(obs, audit_at)
        )

    def observations_of_subject(self, case_id: str) -> Tuple[Observation, ...]:
        """Admissible observations whose keys belong to the case's subject, in evidence order."""
        subject = self.subject(case_id)
        if subject is None:
            return ()
        keys = self.world.identity.keys_for(subject)
        audit_at = self.audit_at(case_id)
        return tuple(
            obs for obs in self.world.index.observations
            if self.admissible(obs, audit_at) and not obs.subject_keys.isdisjoint(keys)
        )

    def file_observations(self, case_id: str, file_id: str) -> Tuple[Observation, ...]:
        """Admissible records of a file that carry the subject's keys; an error past the cutoff or for an unknown file."""
        entry = self.world.index.entries.get(file_id)
        if entry is None:
            raise ToolError("unknown file %r" % file_id)
        audit_at = self.audit_at(case_id)
        if entry.captured_at > audit_at:
            raise ToolError("file %r was captured after the audit time of case %s" % (file_id, case_id))
        subject = self.subject(case_id)
        if subject is None:
            return ()
        keys = self.world.identity.keys_for(subject)
        return tuple(
            obs for obs in self._by_file.get(file_id, ())
            if self.admissible(obs, audit_at) and not obs.subject_keys.isdisjoint(keys)
        )

    # -- candidate activity ----------------------------------------------------

    def candidate_rows(self, case_id: str) -> Tuple[ClassifiedActivity, ...]:
        """Account and worker rows that are candidates of the case, up to its `audit_at`, in stream order."""
        audit_at = self.audit_at(case_id)
        ids = tuple(self.world.base.accounts_of_case.get(case_id, ())) + tuple(
            self.world.base.rows_of_case.get(case_id, ())
        )
        rows = [self.world.base.activities[i] for i in ids]
        return tuple(sorted((r for r in rows if r.t <= audit_at), key=lambda r: r.order_key))

    def competitors(self, activity_id: str) -> Tuple[str, ...]:
        """Cases that still compete for a contested target (every case, in or out of the unit)."""
        base = self.world.base
        return tuple(base.cases_of_row.get(activity_id) or base.cases_of_account.get(activity_id, ()))
