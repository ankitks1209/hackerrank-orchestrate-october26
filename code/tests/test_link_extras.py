"""Tests for the linking extras (SPEC L9, L9b, L10, L11).

Synthetic worlds use fictional ids, an EvidenceIndex whose observations are set directly
and a PolicyEngine built from literal rules. The real-dataset class checks the
acceptance numbers against the participant files (no media facts are supplied, as in the
earlier link tests); the sample answers are read only through the tests-only GoldReader.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Dict, List, Optional, Sequence

from ghostaudit import linking
from ghostaudit.activity import classify_activity
from ghostaudit.config import HOUR, REPO_ROOT, Config, Flags
from ghostaudit.dataset import DatasetReader, Identity, Rule
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_solver import link_cases
from ghostaudit.linking import (
    AUDIT_IN_WINDOW,
    AUDIT_NONE,
    BASIS_AUDIT_ID,
    BASIS_COMPLIANT_UNION,
    BASIS_EVIDENCE_UNION,
    BASIS_REPOPULATION,
    ROW_ADDED,
    ROW_ALREADY_LINKED,
    ROW_NOT_OWNED,
    ROW_POST_AUDIT,
    ExtraLinks,
    add_extras,
)
from ghostaudit.model import (
    ActKind,
    CaseLinks,
    ClassifiedActivity,
    LinkedResource,
    ManifestEntry,
    Observation,
    ObsState,
    Request,
    Treatment,
)
from ghostaudit.policy import PolicyEngine
from ghostaudit.timeutil import to_epoch
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

BASE = to_epoch("2026-03-01T12:00:00Z")
AUDIT_DELTA = 6 * HOUR
USER_COUNT = 4
RULES = (
    Rule("r1", "USER_PROFILE", "any", "DELETE"),
    Rule("r2", "SEARCH_INDEX_ENTRY", "any", "DELETE"),
    Rule("r3", "SUPPORT_MESSAGE", "any", "REDACT"),
    Rule("r4", "ANALYTICS_PROFILE", "any", "ANONYMIZE"),
    Rule("r5", "SECURITY_AUDIT_LOG", "any", "RETAIN"),
    Rule("r6", "LEGAL_HOLD_RECORD", "any", "RETAIN"),
    Rule("r7", "BACKUP_ARCHIVE", "any", "RETAIN"),
)
POLICY = PolicyEngine.from_rules(RULES)


def email_of(user: int) -> str:
    return "person.%d@example.com" % user


def user_key(user: int) -> str:
    return "u:user_%d" % user


IDENTITY = IdentityIndex.build(
    [
        Identity("user_%d" % n, "Person %d" % n, email_of(n), "+1555000%04d" % n, "%064x" % n, 0)
        for n in range(1, USER_COUNT + 1)
    ],
    [],
)


def request(case_id: str, user: int, reported_at: int = BASE, is_sample: bool = False) -> Request:
    return Request(
        case_id, email_of(user), reported_at - HOUR, "COMPLETE", reported_at,
        reported_at + AUDIT_DELTA, "please delete my data", is_sample,
    )


def observation(
    file_id: str,
    captured_at: int,
    system_id: str,
    rid: str,
    state: ObsState,
    category: Optional[str],
    user: Optional[int],
    entry_time: Optional[int] = None,
) -> Observation:
    keys = frozenset() if user is None else frozenset({user_key(user)})
    return Observation(
        file_id, captured_at, entry_time, system_id, rid, category, state, keys, "row"
    )


def search_doc(rid: str, user: int) -> Observation:
    return observation("f1", BASE, "search_service", rid, ObsState.PRESENT, None, user)


def make_index(observations: Sequence[Observation]) -> EvidenceIndex:
    """An index over `observations`; every file of an observation is in the manifest."""
    empty = build_index((), IDENTITY, {}, ())
    times = {obs.file_id: obs.captured_at for obs in observations}
    entries = {
        file_id: ManifestEntry(file_id, Path(file_id), "test", times[file_id], order)
        for order, file_id in enumerate(sorted(times))
    }
    ordered = sorted(
        observations,
        key=lambda o: (o.entry_time or o.captured_at, o.captured_at, o.file_id),
    )
    by_rid: Dict[str, List[Observation]] = defaultdict(list)
    mentions: Dict[str, List[str]] = defaultdict(list)
    for obs in ordered:
        by_rid[obs.resource_id].append(obs)
        if obs.file_id not in mentions[obs.resource_id]:
            mentions[obs.resource_id].append(obs.file_id)
    users_by_rid = {
        rid: IDENTITY.users_for(key for o in rows for key in o.subject_keys)
        for rid, rows in by_rid.items()
    }
    rids_by_user: Dict[str, List[str]] = defaultdict(list)
    for rid, users in users_by_rid.items():
        for user in users:
            rids_by_user[user].append(rid)
    return replace(
        empty,
        observations=tuple(ordered),
        by_rid=MappingProxyType({rid: tuple(rows) for rid, rows in by_rid.items()}),
        users_by_rid=MappingProxyType(users_by_rid),
        rids_by_user=MappingProxyType({u: tuple(r) for u, r in rids_by_user.items()}),
        mentions=MappingProxyType({rid: tuple(files) for rid, files in mentions.items()}),
        entries=MappingProxyType(entries),
    )


def act(
    activity_id: str,
    t: int,
    kind: ActKind,
    system_id: str,
    rid: str,
    treatment: Optional[Treatment] = None,
    related: Optional[str] = None,
) -> ClassifiedActivity:
    return ClassifiedActivity(
        activity_id, t, kind, system_id, rid, treatment, "SUCCESS", related, None, None, None
    )


def repopulation(activity_id: str, t: int, flow: str, search: str) -> ClassifiedActivity:
    return act(activity_id, t, ActKind.REPOPULATED, "integration_service", flow, None, search)


def restore_repopulation(activity_id: str, t: int, backup: str, search: str) -> ClassifiedActivity:
    return act(activity_id, t, ActKind.RESTORE_REPOPULATED, "backup_service", backup, None, search)


def links_of(case_id: str, *resources: LinkedResource) -> CaseLinks:
    return CaseLinks(case_id, None, "none", tuple(resources), ())


def linked(system_id: str, rid: str, treatment: Treatment) -> LinkedResource:
    return LinkedResource(system_id, rid, treatment, "unique")


def extend(
    cases: Sequence[Request],
    acts: Sequence[ClassifiedActivity],
    observations: Sequence[Observation],
    solved: Optional[Dict[str, CaseLinks]] = None,
    **flags: bool,
) -> ExtraLinks:
    base = {req.case_id: links_of(req.case_id) for req in cases}
    base.update(solved or {})
    config = replace(Config(), flags=Flags(**flags))
    index = make_index(observations)
    return add_extras(base, cases, acts, index, IDENTITY, POLICY, config)


def added(result: ExtraLinks, case_id: str, basis: str) -> List[str]:
    return [res.resource_id for res in result.links[case_id].resources if res.basis == basis]


class RepopulationTests(unittest.TestCase):
    """SPEC L9: a flow that repopulated a search document the case owns."""

    def setUp(self) -> None:
        self.cases = [request("case_1", 1)]
        self.search = linked("search_service", "search_1", Treatment.DELETE)
        self.solved = {"case_1": links_of("case_1", self.search)}

    def run_rows(
        self, *rows: ClassifiedActivity, solved: Optional[Dict[str, CaseLinks]] = None
    ) -> ExtraLinks:
        return extend(self.cases, rows, [], self.solved if solved is None else solved)

    def test_chain_from_a_linked_search_adds_a_violating_flow(self) -> None:
        result = self.run_rows(repopulation("a1", BASE + HOUR, "data_flow_1", "search_1"))
        flow = result.links["case_1"].resources[-1]
        self.assertEqual(
            (flow.system_id, flow.resource_id, flow.treatment, flow.basis),
            ("integration_service", "data_flow_1", Treatment.FLOW, BASIS_REPOPULATION),
        )
        self.assertIn("a1", result.links["case_1"].notes[-1])
        self.assertEqual(result.stats.repopulation_rows, {ROW_ADDED: 1})
        self.assertEqual(result.stats.eval_cases_gaining, {BASIS_REPOPULATION: 1})

    def test_restore_row_adds_a_restore_path(self) -> None:
        result = self.run_rows(restore_repopulation("a1", BASE + HOUR, "backup_1", "search_1"))
        backup = result.links["case_1"].resources[-1]
        self.assertEqual(
            (backup.system_id, backup.resource_id, backup.treatment),
            ("backup_service", "backup_1", Treatment.RESTORE),
        )

    def test_row_after_audit_adds_nothing(self) -> None:
        late = BASE + AUDIT_DELTA + HOUR
        result = self.run_rows(repopulation("a1", late, "data_flow_1", "search_1"))
        self.assertEqual(result.links["case_1"], self.solved["case_1"])
        self.assertEqual(result.stats.repopulation_rows, {ROW_POST_AUDIT: 1})

    def test_row_at_audit_is_included(self) -> None:
        result = self.run_rows(repopulation("a1", BASE + AUDIT_DELTA, "data_flow_1", "search_1"))
        self.assertEqual(added(result, "case_1", BASIS_REPOPULATION), ["data_flow_1"])

    def test_search_without_a_requesting_owner_adds_nothing(self) -> None:
        searched = [search_doc("search_9", 3)]
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_9")
        result = extend(self.cases, [row], searched, self.solved)
        self.assertEqual(result.links["case_1"], self.solved["case_1"])
        self.assertEqual(result.stats.repopulation_rows, {ROW_NOT_OWNED: 1})

    def test_search_of_another_case_adds_nothing_here(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        solved = {"case_1": self.solved["case_1"], "case_2": links_of("case_2")}
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_1")
        result = extend(cases, [row], [], solved)
        self.assertEqual(added(result, "case_1", BASIS_REPOPULATION), ["data_flow_1"])
        self.assertEqual(added(result, "case_2", BASIS_REPOPULATION), [])

    def test_evidence_owned_search_counts_after_the_report_only(self) -> None:
        searched = [search_doc("search_5", 1)]
        before = repopulation("a1", BASE - HOUR, "data_flow_1", "search_5")
        after = repopulation("a2", BASE + HOUR, "data_flow_2", "search_5")
        result = extend(self.cases, [before, after], searched)
        self.assertEqual(added(result, "case_1", BASIS_REPOPULATION), ["data_flow_2"])

    def test_flow_owned_by_someone_else_is_not_linked(self) -> None:
        flows = [
            observation("f1", BASE, "integration_service", "data_flow_1", ObsState.ACTIVE, None, 2)
        ]
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_1")
        result = extend(self.cases, [row], flows, self.solved)
        self.assertEqual(result.links["case_1"], self.solved["case_1"])
        self.assertEqual(result.stats.repopulation_rows, {ROW_NOT_OWNED: 1})

    def test_flow_already_linked_is_not_duplicated(self) -> None:
        flow = linked("integration_service", "data_flow_1", Treatment.FLOW)
        solved = {"case_1": links_of("case_1", self.search, flow)}
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_1")
        result = self.run_rows(row, solved=solved)
        self.assertEqual(result.links["case_1"], solved["case_1"])
        self.assertEqual(result.stats.repopulation_rows, {ROW_ALREADY_LINKED: 1})

    def test_two_rows_naming_one_flow_link_it_once(self) -> None:
        rows = [
            repopulation("a1", BASE + HOUR, "data_flow_1", "search_1"),
            repopulation("a2", BASE + 2 * HOUR, "data_flow_1", "search_1"),
        ]
        result = self.run_rows(*rows)
        self.assertEqual(added(result, "case_1", BASIS_REPOPULATION), ["data_flow_1"])

    def test_sample_cases_are_kept_out_of_the_evaluation_counts(self) -> None:
        cases = [request("case_1", 1, is_sample=True)]
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_1")
        result = extend(cases, [row], [], self.solved)
        self.assertEqual(result.stats.added, {BASIS_REPOPULATION: 1})
        self.assertEqual(result.stats.eval_added, {})
        self.assertEqual(result.stats.eval_cases_gaining, {})


class EvidenceUnionTests(unittest.TestCase):
    """SPEC L10: resources the evidence ties to the subject, whatever the activity says."""

    def setUp(self) -> None:
        self.cases = [request("case_1", 1)]
        self.in_window = BASE + HOUR

    def union(self, *observations: Observation, **flags: bool) -> ExtraLinks:
        return extend(self.cases, [], observations, **flags)

    def test_violating_observation_is_added_with_its_treatment(self) -> None:
        obs = observation("f1", self.in_window, "analytics_platform", "analytics_1",
                          ObsState.EXPOSED, "ANALYTICS_PROFILE", 1)
        result = self.union(obs)
        resource = result.links["case_1"].resources[0]
        self.assertEqual(
            (resource.system_id, resource.resource_id, resource.treatment, resource.basis),
            ("analytics_platform", "analytics_1", Treatment.ANONYMIZE, BASIS_EVIDENCE_UNION),
        )

    def test_compliant_observation_is_added_as_verification_only(self) -> None:
        obs = observation("f1", self.in_window, "backup_service", "backup_1",
                          ObsState.BLOCKED, "BACKUP_ARCHIVE", 1)
        result = self.union(obs)
        resource = result.links["case_1"].resources[0]
        self.assertEqual(
            (resource.treatment, resource.basis), (Treatment.RESTORE, BASIS_COMPLIANT_UNION)
        )

    def test_latest_window_observation_decides_the_class(self) -> None:
        first = observation("f1", self.in_window, "search_service", "search_1",
                            ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
        second = observation("f2", self.in_window + HOUR, "search_service", "search_1",
                             ObsState.ABSENT, "SEARCH_INDEX_ENTRY", 1)
        both = self.union(first, second)
        self.assertEqual(added(both, "case_1", BASIS_COMPLIANT_UNION), ["search_1"])
        self.assertEqual(added(self.union(first), "case_1", BASIS_EVIDENCE_UNION), ["search_1"])

    def test_inadmissible_observations_add_nothing(self) -> None:
        def search(
            file_id: str, captured: int, user: Optional[int], entry: Optional[int] = None
        ) -> Observation:
            return observation(file_id, captured, "search_service", "search_1",
                               ObsState.PRESENT, "SEARCH_INDEX_ENTRY", user, entry)

        for label, obs in {
            "file before the report": search("f1", BASE - HOUR, 1),
            "file after the audit": search("f2", BASE + AUDIT_DELTA + 1, 1),
            "entry after the audit": search("f3", self.in_window, 1, BASE + AUDIT_DELTA + 1),
            "another subject": search("f4", self.in_window, 2),
            "no subject key": search("f5", self.in_window, None),
        }.items():
            with self.subTest(label):
                self.assertEqual(self.union(obs).links["case_1"].resources, ())

    def test_window_edges_are_inclusive(self) -> None:
        for moment in (BASE, BASE + AUDIT_DELTA):
            obs = observation("f1", moment, "search_service", "search_1",
                              ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
            self.assertEqual(added(self.union(obs), "case_1", BASIS_EVIDENCE_UNION), ["search_1"])

    def test_pre_request_flag_admits_earlier_files(self) -> None:
        obs = observation("f1", BASE - 5 * HOUR, "search_service", "search_1",
                          ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
        self.assertEqual(self.union(obs).links["case_1"].resources, ())
        on = self.union(obs, allow_pre_request_findings=True)
        self.assertEqual(added(on, "case_1", BASIS_EVIDENCE_UNION), ["search_1"])

    def test_accounts_and_audit_records_are_not_union_resources(self) -> None:
        account = observation("f1", self.in_window, "account_service", "account_1",
                              ObsState.PRESENT, "USER_PROFILE", 1)
        audit = observation("f2", self.in_window, "security_service", "audit_record_1",
                            ObsState.PRESENT, "SECURITY_AUDIT_LOG", 1)
        resources = self.union(account, audit).links["case_1"].resources
        self.assertEqual([res.basis for res in resources], [BASIS_AUDIT_ID])

    def test_already_linked_resource_is_not_added_again(self) -> None:
        obs = observation("f1", self.in_window, "search_service", "search_1",
                          ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
        search = linked("search_service", "search_1", Treatment.DELETE)
        solved = {"case_1": links_of("case_1", search)}
        result = extend(self.cases, [], [obs], solved)
        self.assertEqual(result.links["case_1"], solved["case_1"])

    def test_missing_category_falls_back_to_the_activity_treatment(self) -> None:
        obs = observation("f1", self.in_window, "support_platform", "support_1",
                          ObsState.PRESENT, None, 1)
        row = act(
            "a1", BASE - HOUR, ActKind.VIOLATION, "support_platform", "support_1", Treatment.DELETE
        )
        result = extend(self.cases, [row], [obs])
        self.assertEqual(result.links["case_1"].resources[0].treatment, Treatment.DELETE)

    def test_missing_category_without_activity_uses_the_system_default(self) -> None:
        obs = observation("f1", self.in_window, "support_platform", "support_1",
                          ObsState.PRESENT, None, 1)
        result = self.union(obs)
        self.assertEqual(result.links["case_1"].resources[0].treatment, Treatment.REDACT)

    def test_unknown_system_is_skipped_not_fatal(self) -> None:
        obs = observation(
            "f1", self.in_window, "mystery_service", "mystery_1", ObsState.PRESENT, None, 1
        )
        with self.assertLogs(linking.LOGGER, level="WARNING"):
            result = self.union(obs)
        self.assertEqual(result.links["case_1"].resources, ())

    def test_each_case_of_a_user_uses_its_own_window(self) -> None:
        later = BASE + 100 * HOUR
        cases = [request("case_1", 1), request("case_2", 1, reported_at=later)]
        obs = observation("f1", later + HOUR, "search_service", "search_1",
                          ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
        result = extend(cases, [], [obs])
        self.assertEqual(added(result, "case_1", BASIS_EVIDENCE_UNION), [])
        self.assertEqual(added(result, "case_2", BASIS_EVIDENCE_UNION), ["search_1"])

    def test_unresolved_email_gets_no_extras(self) -> None:
        stranger = replace(request("case_1", 1), email="nobody@example.com")
        obs = observation("f1", self.in_window, "search_service", "search_1",
                          ObsState.PRESENT, "SEARCH_INDEX_ENTRY", 1)
        result = extend([stranger], [], [obs])
        self.assertEqual(result.links["case_1"].resources, ())


class AuditRecordTests(unittest.TestCase):
    """SPEC L11: audit records found by the subject in any file."""

    def setUp(self) -> None:
        self.cases = [request("case_1", 1)]

    def audit(
        self, captured: int, rid: str = "audit_record_1", file_id: str = "f1", user: int = 1
    ) -> Observation:
        return observation(file_id, captured, "security_service", rid, ObsState.PRESENT,
                           "SECURITY_AUDIT_LOG", user)

    def records(self, result: ExtraLinks) -> List[str]:
        return [res.resource_id for res in result.links["case_1"].resources]

    def test_record_named_in_the_window_is_emitted(self) -> None:
        result = extend(self.cases, [], [self.audit(BASE + HOUR)])
        self.assertEqual(self.records(result), ["audit_record_1"])
        resource = result.links["case_1"].resources[0]
        self.assertEqual(
            (resource.system_id, resource.treatment), ("security_service", Treatment.RETAIN)
        )
        self.assertEqual(result.stats.audit, {AUDIT_IN_WINDOW: 1})

    def test_record_found_only_after_the_audit_is_not_emitted(self) -> None:
        result = extend(self.cases, [], [self.audit(BASE + AUDIT_DELTA + 10 * HOUR)])
        self.assertEqual(self.records(result), [])
        self.assertEqual(result.stats.eval_audit, {AUDIT_NONE: 1})

    def test_record_found_only_before_the_report_is_not_emitted(self) -> None:
        result = extend(self.cases, [], [self.audit(BASE - 10 * HOUR)])
        self.assertEqual(self.records(result), [])

    def test_a_window_file_anywhere_among_several_makes_the_record_citable(self) -> None:
        files = [self.audit(BASE - HOUR, file_id="f1"), self.audit(BASE + HOUR, file_id="f2"),
                 self.audit(BASE + 50 * HOUR, file_id="f3")]
        self.assertEqual(self.records(extend(self.cases, [], files)), ["audit_record_1"])

    def test_case_without_a_record_is_counted_and_nothing_is_invented(self) -> None:
        result = extend(self.cases, [], [self.audit(BASE + HOUR, user=2)])
        self.assertEqual(self.records(result), [])
        self.assertEqual(result.stats.audit, {AUDIT_NONE: 1})

    def test_other_subjects_record_is_not_taken(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        result = extend(cases, [], [self.audit(BASE + HOUR, user=2)])
        self.assertEqual(result.links["case_1"].resources, ())
        ids = [r.resource_id for r in result.links["case_2"].resources]
        self.assertEqual(ids, ["audit_record_1"])
        self.assertEqual(result.stats.audit, {AUDIT_IN_WINDOW: 1, AUDIT_NONE: 1})

    def test_record_is_not_added_twice(self) -> None:
        record = linked("security_service", "audit_record_1", Treatment.RETAIN)
        solved = {"case_1": links_of("case_1", record)}
        result = extend(self.cases, [], [self.audit(BASE + HOUR)], solved)
        self.assertEqual(result.links["case_1"], solved["case_1"])


class StructureTests(unittest.TestCase):
    def test_result_covers_every_request_in_natural_order(self) -> None:
        cases = [request("case_10", 1), request("case_2", 2)]
        result = extend(cases, [], [])
        self.assertEqual(list(result.links), ["case_2", "case_10"])

    def test_existing_resources_and_account_are_kept_first(self) -> None:
        search = linked("search_service", "search_1", Treatment.DELETE)
        base = CaseLinks("case_1", "account_1", "unique", (search,), ("account_row=acc_1",))
        row = repopulation("a1", BASE + HOUR, "data_flow_1", "search_1")
        config = Config()
        index = make_index([])
        result = add_extras(
            {"case_1": base}, [request("case_1", 1)], [row], index, IDENTITY, POLICY, config
        )
        links = result.links["case_1"]
        self.assertEqual((links.account_id, links.account_basis), ("account_1", "unique"))
        self.assertEqual(links.resources[0], search)
        self.assertEqual(links.notes[0], "account_row=acc_1")


class StaticTests(unittest.TestCase):
    def test_linking_uses_no_flag_literals_or_sample_answers(self) -> None:
        text = (REPO_ROOT / "code" / "ghostaudit" / "linking.py").read_text(encoding="utf-8")
        self.assertNotIn("print(", text)
        self.assertNotIn("sample_output", text)
        self.assertNotIn("solution/", text)

    def test_the_default_flag_excludes_pre_request_findings(self) -> None:
        self.assertFalse(Flags().allow_pre_request_findings)


# Measured on the participant files: evaluation cases per audit coverage bucket, and public samples whose
# gold names an audit record that no file of their own window names (a late-only id is not emitted).
IN_WINDOW_EVAL = 300
NONE_EVAL = 218
SAMPLES_WITHOUT_WINDOW_AUDIT_ID = 7

FINGERPRINT_SCRIPT = """
import hashlib
from ghostaudit.activity import classify_activity
from ghostaudit.config import Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.index import build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_solver import link_cases
from ghostaudit.linking import add_extras
from ghostaudit.policy import PolicyEngine
reader = DatasetReader(%r)
identity = IdentityIndex.build(reader.identities(), reader.audit_log())
index = build_index(reader.manifest(), identity, {}, classify_activity(reader.activity()))
acts = classify_activity(reader.activity())
solution = link_cases(reader.requests(), acts, index, identity, Config())
policy = PolicyEngine.from_rules(reader.rules())
result = add_extras(
    solution.links, reader.requests(), acts, index, identity, policy, Config()
)
print(hashlib.sha256(repr((list(result.links.items()), result.stats)).encode()).hexdigest())
"""


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    """Acceptance on the participant files; media facts are not supplied."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        cls.identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(reader.manifest(), cls.identity, {}, classify_activity(reader.activity()))
        cls.requests = reader.requests()
        cls.acts = classify_activity(reader.activity())
        cls.policy = PolicyEngine.from_rules(reader.rules())
        cls.solution = link_cases(cls.requests, cls.acts, cls.index, cls.identity, Config())
        cls.result = cls.extras(Config())
        cls.eval_cases = [req for req in cls.requests if not req.is_sample]

    @classmethod
    def extras(cls, config: Config) -> ExtraLinks:
        return add_extras(
            cls.solution.links, cls.requests, cls.acts, cls.index, cls.identity,
            cls.policy, config,
        )

    def test_every_evaluation_case_with_an_owned_search_gains_its_repopulation_flow(self) -> None:
        owners = self.index.users_by_rid
        expected = 0
        for req in self.eval_cases:
            subject = self.identity.resolve(req.email)
            expected += any(
                row.kind is ActKind.REPOPULATED
                and row.t <= req.audit_at
                and subject in owners.get(row.related_rid, ())
                and (not owners.get(row.resource_id) or subject in owners[row.resource_id])
                for row in self.acts
            )
        self.assertGreater(expected, 0)
        # The ownership route above is a subset: a flow also reaches a case through a search
        # document the case is already linked to.
        self.assertGreaterEqual(self.result.stats.eval_cases_gaining[BASIS_REPOPULATION], expected)

    def test_repopulation_rows_are_added_only_up_to_the_audit_of_the_case(self) -> None:
        outcomes = self.result.stats.repopulation_rows
        self.assertEqual(sum(outcomes.values()), sum(1 for r in self.acts if r.kind in linking.REPOPULATION_TREATMENT))
        self.assertGreater(outcomes[ROW_ADDED], 0)
        by_flow = {
            row.resource_id: row for row in self.acts if row.kind in linking.REPOPULATION_TREATMENT
        }
        for req in self.requests:
            subject = self.identity.resolve(req.email)
            for res in self.result.links[req.case_id].resources:
                if res.basis != BASIS_REPOPULATION:
                    continue
                row = by_flow[res.resource_id]
                self.assertLessEqual(row.t, req.audit_at)
                linked_search = {
                    r.resource_id for r in self.result.links[req.case_id].resources
                    if r.basis != BASIS_REPOPULATION
                }
                self.assertTrue(
                    subject in self.index.users_by_rid.get(row.related_rid, ())
                    or row.related_rid in linked_search,
                    (req.case_id, res.resource_id),
                )

    def test_audit_coverage_buckets_of_the_evaluation_cases(self) -> None:
        self.assertEqual(
            self.result.stats.eval_audit,
            {AUDIT_IN_WINDOW: IN_WINDOW_EVAL, AUDIT_NONE: NONE_EVAL},
        )
        self.assertEqual(sum(self.result.stats.eval_audit.values()), len(self.eval_cases))

    def test_every_emitted_audit_record_is_named_by_a_window_file(self) -> None:
        emitted = 0
        for req in self.requests:
            for res in self.result.links[req.case_id].resources:
                if res.basis != BASIS_AUDIT_ID:
                    continue
                emitted += 1
                self.assertTrue(any(
                    req.reported_at <= self.index.entries[f].captured_at <= req.audit_at
                    for f in self.index.mentions[res.resource_id]
                ), (req.case_id, res.resource_id))
        self.assertGreater(emitted, 0)

    def test_every_window_violating_observation_of_the_subject_is_linked(self) -> None:
        """Recall invariant (SPEC 8.3b): no in-window violating evidence is left unassigned."""
        missing = []
        for req in self.requests:
            subject = self.identity.resolve(req.email)
            have = {r.resource_id for r in self.result.links[req.case_id].resources}
            keys = self.identity.keys_for(subject)
            for rid in self.index.rids_by_user.get(subject, ()):
                for obs in self.index.by_rid[rid]:
                    entry = obs.captured_at if obs.entry_time is None else obs.entry_time
                    if (
                        req.reported_at <= obs.captured_at <= req.audit_at
                        and entry <= req.audit_at
                        and not obs.subject_keys.isdisjoint(keys)
                        and obs.system_id not in (linking.ACCOUNT_SERVICE, linking.SECURITY_SERVICE)
                        and rid not in have
                    ):
                        missing.append((req.case_id, rid))
        self.assertEqual(missing, [])

    def test_union_adds_only_what_the_gold_samples_contain(self) -> None:
        gold = GoldReader().cases()
        for req in self.requests:
            if not req.is_sample:
                continue
            truth = {step.resource_id for step in gold[req.case_id].steps}
            for res in self.result.links[req.case_id].resources:
                if res.basis in (BASIS_EVIDENCE_UNION, BASIS_COMPLIANT_UNION):
                    self.assertIn(res.resource_id, truth, req.case_id)

    def test_sample_audit_records_agree_with_the_gold_except_the_unknowable(self) -> None:
        gold = GoldReader().cases()
        known = {req.case_id for req in self.requests if req.is_sample}
        missing = []
        for case_id in sorted(known):
            truth = {
                s.resource_id for s in gold[case_id].steps if s.system_id == "security_service"
            }
            found = {r.resource_id for r in self.result.links[case_id].resources
                     if r.system_id == "security_service"}
            self.assertLessEqual(found, truth, case_id)
            if truth - found:
                missing.append(case_id)
        self.assertEqual(len(missing), SAMPLES_WITHOUT_WINDOW_AUDIT_ID)

    def test_links_never_lose_a_resource_the_solver_found(self) -> None:
        for case_id, links in self.solution.links.items():
            kept = {(r.system_id, r.resource_id) for r in self.result.links[case_id].resources}
            self.assertLessEqual({(r.system_id, r.resource_id) for r in links.resources}, kept)

    def test_output_is_identical_under_two_hash_seeds(self) -> None:
        script = FINGERPRINT_SCRIPT % str(REPO_ROOT / "dataset")
        digests = set()
        for seed in ("0", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            done = subprocess.run(
                [sys.executable, "-c", script], env=env, cwd=str(REPO_ROOT / "code"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True,
            )
            digests.add(done.stdout.strip())
        self.assertEqual(len(digests), 1)
        self.assertEqual(len(next(iter(digests))), len(hashlib.sha256().hexdigest()))


if __name__ == "__main__":
    unittest.main()
