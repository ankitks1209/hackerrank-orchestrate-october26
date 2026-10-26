"""Tests for ghostaudit.state (SPEC T1-T4, V5, 4, 8.2).

The synthetic class builds an EvidenceIndex by hand from fictional ids and plain
integer times. The real-dataset class checks the acceptance facts against the
participant files, with no media facts supplied.
"""
from __future__ import annotations

import logging
import unittest
from typing import Dict, Iterable, List, Optional, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.config import HOUR, Config
from ghostaudit.dataset import DatasetReader, Rule
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.model import (
    ActKind,
    ClassifiedActivity,
    ManifestEntry,
    ObsState,
    Observation,
    Request,
    ScopeAssertion,
    Treatment,
)
from ghostaudit.policy import PolicyEngine
from ghostaudit.state import (
    BASIS_ACTIVITY,
    BASIS_EVIDENCE,
    BASIS_SCOPE,
    BASIS_UNOBSERVED,
    StateResolver,
    choose_omission_cite,
)
from tests.dataset_guard import needs_dataset

ACCOUNT_SERVICE = "account_service"
SEARCH_SERVICE = "search_service"
SUPPORT_PLATFORM = "support_platform"
INTEGRATION_SERVICE = "integration_service"
LEGAL_SERVICE = "legal_service"
REPORTED = 100 * HOUR
AUDIT = 200 * HOUR

RULE_ROWS = (
    ("USER_PROFILE", "DELETE"),
    ("SEARCH_INDEX_ENTRY", "DELETE"),
    ("SUPPORT_MESSAGE", "REDACT"),
    ("SUPPORT_ATTACHMENT", "DELETE"),
    ("ANALYTICS_PROFILE", "ANONYMIZE"),
    ("LEGAL_HOLD_RECORD", "RETAIN"),
    ("BACKUP_ARCHIVE", "RETAIN"),
)


def request(reported_at: int = REPORTED, audit_at: int = AUDIT) -> Request:
    return Request("case_t", "x@example.com", 0, "COMPLETE", reported_at, audit_at, "delete", True)


def policy() -> PolicyEngine:
    rows = [Rule("rule_%d" % n, cat, "Always", action) for n, (cat, action) in enumerate(RULE_ROWS)]
    return PolicyEngine.from_rules(rows)


def obs(
    file_id: str,
    rid: str,
    state: ObsState,
    system_id: str,
    captured_at: int,
    entry_time: Optional[int] = None,
    category: Optional[str] = None,
) -> Observation:
    return Observation(
        file_id, captured_at, entry_time, system_id, rid, category, state, frozenset(), "loc"
    )


def scope(file_id: str, system_id: str, captured_at: int, present: Iterable[str] = ()) -> ScopeAssertion:
    return ScopeAssertion(file_id, captured_at, system_id, frozenset(present))


def activity(
    activity_id: str,
    t: int,
    kind: ActKind,
    system_id: str,
    rid: str,
    treatment: Optional[Treatment],
) -> ClassifiedActivity:
    return ClassifiedActivity(
        activity_id, t, kind, system_id, rid, treatment, "SUCCESS", None, None, None, None
    )


def make_index(
    captured: Dict[str, int],
    observations: Iterable[Observation] = (),
    scopes: Iterable[ScopeAssertion] = (),
) -> EvidenceIndex:
    """Hand-built index; `captured` lists the files in manifest order."""
    entries = {
        file_id: ManifestEntry(file_id, None, "test", at, order)  # type: ignore[arg-type]
        for order, (file_id, at) in enumerate(captured.items())
    }
    ordered = sorted(
        observations,
        key=lambda o: (
            o.captured_at if o.entry_time is None else o.entry_time,
            o.captured_at,
            entries[o.file_id].order,
        ),
    )
    by_rid: Dict[str, List[Observation]] = {}
    for item in ordered:
        by_rid.setdefault(item.resource_id, []).append(item)
    by_file: Dict[str, List[ScopeAssertion]] = {}
    for item in scopes:
        by_file.setdefault(item.file_id, []).append(item)
    return EvidenceIndex(
        observations=tuple(ordered),
        by_rid={rid: tuple(rows) for rid, rows in by_rid.items()},
        users_by_rid={},
        rids_by_user={},
        mentions={},
        scopes_by_file={fid: tuple(rows) for fid, rows in by_file.items()},
        pointers={},
        entries=entries,
        claimed_by={},
        notes=(),
    )


def resolver(index: EvidenceIndex, acts: Iterable[ClassifiedActivity] = ()) -> StateResolver:
    return StateResolver(index, policy(), acts)


class TimeTravelTests(unittest.TestCase):
    def test_entry_after_audit_is_ignored_and_the_earlier_state_stands(self) -> None:
        index = make_index(
            {"f1": 150 * HOUR},
            [
                obs("f1", "account_1", ObsState.ABSENT, ACCOUNT_SERVICE, 150 * HOUR, 150 * HOUR),
                obs("f1", "account_1", ObsState.PRESENT, ACCOUNT_SERVICE, 150 * HOUR, AUDIT + HOUR),
            ],
        )
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "f1", BASIS_EVIDENCE))

    def test_file_captured_after_audit_is_ignored(self) -> None:
        index = make_index(
            {"early": 150 * HOUR, "late": AUDIT + 1},
            [
                obs("early", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 150 * HOUR),
                obs("late", "search_1", ObsState.ABSENT, SEARCH_SERVICE, AUDIT + 1),
            ],
        )
        got = resolver(index).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite), (ObsState.PRESENT, "early"))

    def test_file_captured_exactly_at_audit_is_admissible(self) -> None:
        index = make_index({"f": AUDIT}, [obs("f", "search_1", ObsState.PRESENT, SEARCH_SERVICE, AUDIT)])
        got = resolver(index).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite), (ObsState.PRESENT, "f"))

    def test_greatest_entry_time_beats_a_later_captured_file(self) -> None:
        index = make_index(
            {"a": 150 * HOUR, "b": 180 * HOUR},
            [
                obs("a", "search_1", ObsState.ABSENT, SEARCH_SERVICE, 150 * HOUR, 149 * HOUR),
                obs("b", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 180 * HOUR, 120 * HOUR),
            ],
        )
        got = resolver(index).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite), (ObsState.ABSENT, "a"))

    def test_missing_entry_time_falls_back_to_captured_at(self) -> None:
        index = make_index(
            {"a": 150 * HOUR, "b": 160 * HOUR},
            [
                obs("a", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 150 * HOUR, None),
                obs("b", "search_1", ObsState.ABSENT, SEARCH_SERVICE, 160 * HOUR, None),
            ],
        )
        got = resolver(index).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite), (ObsState.ABSENT, "b"))

    def test_same_resource_in_another_system_is_not_confused(self) -> None:
        index = make_index({"f": 150 * HOUR}, [obs("f", "x_1", ObsState.PRESENT, SUPPORT_PLATFORM, 150 * HOUR)])
        got = resolver(index).resolve("x_1", SEARCH_SERVICE, request())
        self.assertEqual(got.basis, BASIS_UNOBSERVED)


class CiteTests(unittest.TestCase):
    def test_file_before_reported_at_gives_state_without_cite(self) -> None:
        index = make_index({"old": REPORTED - 1}, [obs("old", "search_1", ObsState.PRESENT, SEARCH_SERVICE, REPORTED - 1)])
        got = resolver(index).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.PRESENT, "", BASIS_EVIDENCE))

    def test_window_bounds_are_inclusive(self) -> None:
        index = make_index(
            {"lo": REPORTED, "hi": AUDIT},
            [
                obs("lo", "search_1", ObsState.PRESENT, SEARCH_SERVICE, REPORTED),
                obs("hi", "search_2", ObsState.PRESENT, SEARCH_SERVICE, AUDIT),
            ],
        )
        state = resolver(index)
        self.assertEqual(state.resolve("search_1", SEARCH_SERVICE, request()).cite, "lo")
        self.assertEqual(state.resolve("search_2", SEARCH_SERVICE, request()).cite, "hi")

    def test_latest_window_file_with_the_resolved_state_is_cited(self) -> None:
        index = make_index(
            {"a": 120 * HOUR, "b": 130 * HOUR, "c": 140 * HOUR},
            [
                obs("a", "support_1", ObsState.EXPOSED, SUPPORT_PLATFORM, 120 * HOUR),
                obs("b", "support_1", ObsState.EXPOSED, SUPPORT_PLATFORM, 130 * HOUR),
                obs("c", "support_1", ObsState.REDACTED, SUPPORT_PLATFORM, 140 * HOUR),
            ],
        )
        state = resolver(index)
        self.assertEqual(state.resolve("support_1", SUPPORT_PLATFORM, request()).cite, "c")
        earlier = state.resolve("support_1", SUPPORT_PLATFORM, request(audit_at=135 * HOUR))
        self.assertEqual((earlier.state, earlier.cite), (ObsState.EXPOSED, "b"))

    def test_manifest_order_breaks_a_capture_tie(self) -> None:
        index = make_index(
            {"first": 150 * HOUR, "second": 150 * HOUR},
            [
                obs("first", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 150 * HOUR),
                obs("second", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 150 * HOUR),
            ],
        )
        self.assertEqual(resolver(index).resolve("search_1", SEARCH_SERVICE, request()).cite, "second")


class ScopeTests(unittest.TestCase):
    def test_scope_omitting_the_resource_proves_absence(self) -> None:
        index = make_index({"inv": 150 * HOUR}, scopes=[scope("inv", ACCOUNT_SERVICE, 150 * HOUR, ["account_9"])])
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "inv", BASIS_SCOPE))

    def test_scope_listing_the_resource_is_no_absence(self) -> None:
        index = make_index({"inv": 150 * HOUR}, scopes=[scope("inv", ACCOUNT_SERVICE, 150 * HOUR, ["account_1"])])
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual(got.basis, BASIS_UNOBSERVED)

    def test_scope_of_another_system_leaves_the_resource_unobserved(self) -> None:
        index = make_index({"inv": 150 * HOUR}, scopes=[scope("inv", SEARCH_SERVICE, 150 * HOUR)])
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (None, "", BASIS_UNOBSERVED))

    def test_scope_after_audit_is_ignored(self) -> None:
        index = make_index({"inv": AUDIT + 1}, scopes=[scope("inv", ACCOUNT_SERVICE, AUDIT + 1)])
        self.assertEqual(resolver(index).resolve("account_1", ACCOUNT_SERVICE, request()).basis, BASIS_UNOBSERVED)

    def test_scope_snapshot_after_audit_in_an_earlier_file_is_ignored(self) -> None:
        index = make_index({"inv": 150 * HOUR}, scopes=[scope("inv", ACCOUNT_SERVICE, AUDIT + 1)])
        self.assertEqual(resolver(index).resolve("account_1", ACCOUNT_SERVICE, request()).basis, BASIS_UNOBSERVED)

    def test_scope_never_overrides_an_observation(self) -> None:
        index = make_index(
            {"obs": 140 * HOUR, "inv": 150 * HOUR},
            [obs("obs", "account_1", ObsState.PRESENT, ACCOUNT_SERVICE, 140 * HOUR)],
            [scope("inv", ACCOUNT_SERVICE, 150 * HOUR)],
        )
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.PRESENT, "obs", BASIS_EVIDENCE))

    def test_absence_observation_without_window_proof_cites_a_window_scope(self) -> None:
        index = make_index(
            {"old": REPORTED - HOUR, "inv": 150 * HOUR},
            [obs("old", "account_1", ObsState.ABSENT, ACCOUNT_SERVICE, REPORTED - HOUR)],
            [scope("inv", ACCOUNT_SERVICE, 150 * HOUR)],
        )
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "inv", BASIS_EVIDENCE))

    def test_absence_observation_in_window_is_cited_over_a_later_scope(self) -> None:
        index = make_index(
            {"lookup": 140 * HOUR, "inv": 150 * HOUR},
            [obs("lookup", "account_1", ObsState.ABSENT, ACCOUNT_SERVICE, 140 * HOUR)],
            [scope("inv", ACCOUNT_SERVICE, 150 * HOUR)],
        )
        self.assertEqual(resolver(index).resolve("account_1", ACCOUNT_SERVICE, request()).cite, "lookup")

    def test_scope_cite_outside_the_window_is_empty(self) -> None:
        index = make_index({"inv": REPORTED - 1}, scopes=[scope("inv", ACCOUNT_SERVICE, REPORTED - 1)])
        got = resolver(index).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "", BASIS_SCOPE))


class ActivityFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.empty = make_index({})

    def resolve(self, act: ClassifiedActivity, system_id: str, req: Optional[Request] = None):
        return resolver(self.empty, [act]).resolve(act.resource_id, system_id, req or request())

    def test_violation_state_follows_the_treatment_and_cites_the_activity(self) -> None:
        cases = (
            (SEARCH_SERVICE, "search_1", Treatment.DELETE, ObsState.PRESENT),
            (SUPPORT_PLATFORM, "support_1", Treatment.REDACT, ObsState.EXPOSED),
            ("analytics_platform", "analytics_1", Treatment.ANONYMIZE, ObsState.EXPOSED),
        )
        for system_id, rid, treatment, expected in cases:
            act = activity("a1", 150 * HOUR, ActKind.VIOLATION, system_id, rid, treatment)
            got = self.resolve(act, system_id)
            self.assertEqual((got.state, got.cite, got.basis), (expected, "a1", BASIS_ACTIVITY), rid)

    def test_flow_and_restore_rows_are_active_and_citable(self) -> None:
        flow = activity("cf", 150 * HOUR, ActKind.FLOW_ENABLED, INTEGRATION_SERVICE, "data_flow_1", Treatment.FLOW)
        restore = activity("cr", 150 * HOUR, ActKind.RESTORE_ALLOWED, "backup_service", "backup_1", Treatment.RESTORE)
        self.assertEqual(self.resolve(flow, INTEGRATION_SERVICE).state, ObsState.ACTIVE)
        got = self.resolve(restore, "backup_service")
        self.assertEqual((got.state, got.cite), (ObsState.ACTIVE, "cr"))

    def test_violation_outside_the_window_keeps_state_but_drops_cite(self) -> None:
        act = activity("a1", REPORTED - 1, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE)
        got = self.resolve(act, SEARCH_SERVICE)
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.PRESENT, "", BASIS_ACTIVITY))

    def test_policy_row_gives_the_compliant_state_without_a_cite(self) -> None:
        cases = (
            (SUPPORT_PLATFORM, "support_1", Treatment.REDACT, ObsState.REDACTED),
            (LEGAL_SERVICE, "legal_hold_1", Treatment.RETAIN, ObsState.PRESENT),
            (INTEGRATION_SERVICE, "data_flow_1", Treatment.FLOW, ObsState.DISABLED),
            ("backup_service", "backup_1", Treatment.RESTORE, ObsState.BLOCKED),
        )
        for system_id, rid, treatment, expected in cases:
            got = self.resolve(activity("p1", 150 * HOUR, ActKind.POLICY_OK, system_id, rid, treatment), system_id)
            self.assertEqual((got.state, got.cite, got.basis), (expected, "", BASIS_ACTIVITY), rid)

    def test_replication_checkpoint_means_the_account_is_present_and_has_no_cite(self) -> None:
        act = activity("r1", 150 * HOUR, ActKind.REPLICATION_CHECKPOINT, ACCOUNT_SERVICE, "account_1", None)
        got = self.resolve(act, ACCOUNT_SERVICE)
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.PRESENT, "", BASIS_ACTIVITY))

    def test_repopulated_flow_is_active(self) -> None:
        act = activity("rp", 150 * HOUR, ActKind.REPOPULATED, INTEGRATION_SERVICE, "data_flow_1", None)
        self.assertEqual(self.resolve(act, INTEGRATION_SERVICE).state, ObsState.ACTIVE)

    def test_activity_after_audit_is_ignored(self) -> None:
        act = activity("a1", AUDIT + 1, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE)
        got = self.resolve(act, SEARCH_SERVICE)
        self.assertEqual((got.state, got.cite, got.basis), (None, "", BASIS_UNOBSERVED))

    def test_latest_template_at_audit_wins(self) -> None:
        acts = [
            activity("p1", 120 * HOUR, ActKind.POLICY_OK, SEARCH_SERVICE, "search_1", Treatment.DELETE),
            activity("v1", 130 * HOUR, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE),
        ]
        got = resolver(self.empty, acts).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.cite), (ObsState.PRESENT, "v1"))

    def test_non_state_rows_are_not_templates(self) -> None:
        act = activity("s1", 150 * HOUR, ActKind.ACCOUNT_SUBMIT, ACCOUNT_SERVICE, "account_1", Treatment.DELETE)
        self.assertEqual(self.resolve(act, ACCOUNT_SERVICE).basis, BASIS_UNOBSERVED)

    def test_evidence_wins_over_the_template(self) -> None:
        index = make_index({"f": 150 * HOUR}, [obs("f", "search_1", ObsState.ABSENT, SEARCH_SERVICE, 150 * HOUR)])
        act = activity("v1", 140 * HOUR, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE)
        with self.assertLogs("ghostaudit.state", level="WARNING"):
            got = resolver(index, [act]).resolve("search_1", SEARCH_SERVICE, request())
        self.assertEqual((got.state, got.basis), (ObsState.ABSENT, BASIS_EVIDENCE))


class DisagreementTests(unittest.TestCase):
    def test_violation_row_against_absent_evidence_is_logged_and_noted(self) -> None:
        index = make_index({"f": 150 * HOUR}, [obs("f", "search_1", ObsState.ABSENT, SEARCH_SERVICE, 150 * HOUR)])
        act = activity("v1", 140 * HOUR, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE)
        with self.assertLogs("ghostaudit.state", level="WARNING") as logs:
            got = resolver(index, [act]).resolve("search_1", SEARCH_SERVICE, request())
        self.assertIn("v1", got.note)
        self.assertIn("search_1", logs.output[0])

    def test_policy_row_against_exposed_evidence_is_a_disagreement(self) -> None:
        index = make_index(
            {"f": 150 * HOUR},
            [obs("f", "support_1", ObsState.EXPOSED, SUPPORT_PLATFORM, 150 * HOUR, category="SUPPORT_MESSAGE")],
        )
        act = activity("p1", 140 * HOUR, ActKind.POLICY_OK, SUPPORT_PLATFORM, "support_1", Treatment.REDACT)
        with self.assertLogs("ghostaudit.state", level="WARNING"):
            got = resolver(index, [act]).resolve("support_1", SUPPORT_PLATFORM, request())
        self.assertTrue(got.note)

    def test_agreement_has_no_note(self) -> None:
        index = make_index({"f": 150 * HOUR}, [obs("f", "search_1", ObsState.PRESENT, SEARCH_SERVICE, 150 * HOUR)])
        act = activity("v1", 140 * HOUR, ActKind.VIOLATION, SEARCH_SERVICE, "search_1", Treatment.DELETE)
        self.assertEqual(resolver(index, [act]).resolve("search_1", SEARCH_SERVICE, request()).note, "")

    def test_retained_legal_hold_present_agrees_with_a_policy_row(self) -> None:
        index = make_index({"f": 150 * HOUR}, [obs("f", "legal_hold_1", ObsState.PRESENT, LEGAL_SERVICE, 150 * HOUR)])
        act = activity("p1", 140 * HOUR, ActKind.POLICY_OK, LEGAL_SERVICE, "legal_hold_1", Treatment.RETAIN)
        self.assertEqual(resolver(index, [act]).resolve("legal_hold_1", LEGAL_SERVICE, request()).note, "")

    def test_evidence_category_overrides_the_activity_treatment(self) -> None:
        # The activity says DELETE (attachment) but the evidence category is a message:
        # EXPOSED is a violation of REDACT, so a violation row agrees.
        index = make_index(
            {"f": 150 * HOUR},
            [obs("f", "support_1", ObsState.EXPOSED, SUPPORT_PLATFORM, 150 * HOUR, category="SUPPORT_MESSAGE")],
        )
        act = activity("v1", 140 * HOUR, ActKind.VIOLATION, SUPPORT_PLATFORM, "support_1", Treatment.DELETE)
        self.assertEqual(resolver(index, [act]).resolve("support_1", SUPPORT_PLATFORM, request()).note, "")


class OmissionCiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = make_index(
            {"before": REPORTED - HOUR, "s1": 120 * HOUR, "s2": 140 * HOUR, "plain": 150 * HOUR, "after": AUDIT + 1},
            scopes=[
                scope("before", ACCOUNT_SERVICE, REPORTED - HOUR),
                scope("s1", ACCOUNT_SERVICE, 120 * HOUR),
                scope("s2", ACCOUNT_SERVICE, 140 * HOUR),
                scope("after", ACCOUNT_SERVICE, AUDIT + 1),
            ],
        )

    def choose(self, cites: Iterable[str], index: Optional[EvidenceIndex] = None) -> Optional[str]:
        return choose_omission_cite("account_1", cites, request(), index or self.index)

    def test_case_cite_with_a_scope_comes_first(self) -> None:
        self.assertEqual(self.choose(["s2", "plain"]), "s2")

    def test_case_cite_without_a_scope_falls_to_the_window_scopes(self) -> None:
        self.assertEqual(self.choose(["plain"]), "s1")

    def test_no_case_cites_uses_the_window_scopes(self) -> None:
        self.assertEqual(self.choose([]), "s1")

    def test_several_preferred_cites_resolve_to_the_earliest(self) -> None:
        self.assertEqual(self.choose(["s2", "s1"]), "s1")

    def test_cites_outside_the_window_are_not_preferred(self) -> None:
        self.assertEqual(self.choose(["before", "after"]), "s1")

    def test_activity_ids_and_empty_cites_are_ignored(self) -> None:
        self.assertEqual(self.choose(["activity_5", ""]), "s1")

    def test_cite_only_scope_counts_for_a_cited_file_only(self) -> None:
        index = make_index(
            {"topo": 130 * HOUR, "s1": 120 * HOUR},
            scopes=[
                ScopeAssertion("topo", 130 * HOUR, ACCOUNT_SERVICE, frozenset({"account_9"}), True),
                scope("s1", ACCOUNT_SERVICE, 120 * HOUR),
            ],
        )
        self.assertEqual(self.choose(["topo"], index), "topo")
        self.assertEqual(self.choose(["plain"], index), "s1")
        self.assertEqual(self.choose([], index), "s1")

    def test_cite_only_scope_is_never_the_window_fallback_or_a_state_proof(self) -> None:
        index = make_index(
            {"topo": 130 * HOUR},
            scopes=[ScopeAssertion("topo", 130 * HOUR, ACCOUNT_SERVICE, frozenset(), True)],
        )
        self.assertIsNone(self.choose(["plain"], index))
        self.assertIsNone(self.choose([], index))
        got = resolver(index, []).resolve("account_1", ACCOUNT_SERVICE, request())
        self.assertEqual(got.basis, BASIS_UNOBSERVED)

    def test_cite_only_scope_listing_the_account_is_no_proof(self) -> None:
        index = make_index(
            {"topo": 130 * HOUR},
            scopes=[ScopeAssertion("topo", 130 * HOUR, ACCOUNT_SERVICE, frozenset({"account_1"}), True)],
        )
        self.assertIsNone(self.choose(["topo"], index))

    def test_none_when_no_window_scope_omits_the_account(self) -> None:
        index = make_index(
            {"s1": 120 * HOUR, "after": AUDIT + 1},
            scopes=[scope("s1", ACCOUNT_SERVICE, 120 * HOUR, ["account_1"]), scope("after", ACCOUNT_SERVICE, AUDIT + 1)],
        )
        self.assertIsNone(self.choose(["s1"], index))

    def test_scope_of_another_system_does_not_count(self) -> None:
        index = make_index({"s1": 120 * HOUR}, scopes=[scope("s1", SEARCH_SERVICE, 120 * HOUR)])
        self.assertIsNone(self.choose([], index))


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(Config().dataset_dir)
        identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(reader.manifest(), identity, {}, classify_activity(reader.activity()))
        acts = classify_activity(reader.activity())
        cls.resolver = StateResolver(cls.index, PolicyEngine.from_rules(reader.rules()), acts)
        cls.requests = {req.case_id: req for req in reader.requests()}

    def setUp(self) -> None:
        # Blind scans resolve resources against requests that do not own them, which
        # logs expected disagreements; real runs resolve linked resources only.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def around(self, file_id: str, lead: int = HOUR, lag: int = 0) -> Request:
        """A request whose window ends `lag` seconds after the file's capture."""
        captured = self.index.entries[file_id].captured_at
        return request(captured - lead, captured + lag)

    def test_case_26_account_is_absent_from_the_404_lookup(self) -> None:
        got = self.resolver.resolve("account_5684", ACCOUNT_SERVICE, self.requests["case_26"])
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "evidence_92", BASIS_EVIDENCE))

    def test_evidence_after_audit_is_not_used_for_case_26(self) -> None:
        req = self.requests["case_26"]
        self.assertGreater(self.index.entries["evidence_02"].captured_at, req.audit_at)
        got = self.resolver.resolve("account_3866", ACCOUNT_SERVICE, req)
        self.assertEqual((got.state, got.cite), (ObsState.ABSENT, "evidence_92"))

    def test_post_audit_entries_in_an_in_window_file_are_ignored(self) -> None:
        for file_id, rid in (("evidence_13", "account_1417"), ("evidence_36", "account_5043")):
            got = self.resolver.resolve(rid, ACCOUNT_SERVICE, self.around(file_id))
            self.assertEqual((got.state, got.cite), (ObsState.ABSENT, file_id), rid)

    def test_post_audit_entry_counts_once_the_audit_moves_past_it(self) -> None:
        got = self.resolver.resolve("account_1417", ACCOUNT_SERVICE, self.around("evidence_13", lag=3 * 24 * HOUR))
        self.assertEqual((got.state, got.basis), (ObsState.PRESENT, BASIS_EVIDENCE))

    def test_drift_account_stays_present_despite_an_empty_primary_snapshot(self) -> None:
        got = self.resolver.resolve("account_5334", ACCOUNT_SERVICE, self.requests["case_24"])
        self.assertEqual((got.state, got.cite, got.note), (ObsState.PRESENT, "evidence_92", ""))

    def test_hand_crafted_account_is_absent_by_scope_and_the_omission_prefers_the_case_proof(self) -> None:
        req = self.requests["case_04"]
        got = self.resolver.resolve("account_004", ACCOUNT_SERVICE, req)
        self.assertEqual((got.state, got.cite, got.basis), (ObsState.ABSENT, "evidence_54", BASIS_SCOPE))
        self.assertEqual(choose_omission_cite("account_004", ["evidence_56"], req, self.index), "evidence_54")
        self.assertEqual(choose_omission_cite("account_4857", ["evidence_51"], self.requests["case_31"], self.index), "evidence_51")

    def test_no_cite_falls_outside_its_window(self) -> None:
        checked = 0
        rids = sorted(self.index.by_rid)
        for req in self.requests.values():
            if not req.is_sample:
                continue
            for rid in rids:
                system_id = self.index.by_rid[rid][0].system_id
                cite = self.resolver.resolve(rid, system_id, req).cite
                if cite in self.index.entries:
                    checked += 1
                    captured = self.index.entries[cite].captured_at
                    self.assertTrue(req.reported_at <= captured <= req.audit_at, (req.case_id, rid, cite))
        self.assertGreater(checked, 0)

    def test_legal_hold_policy_rows_do_not_disagree_with_evidence(self) -> None:
        notes: List[Tuple[str, str]] = []
        for req in self.requests.values():
            for rid in sorted(rid for rid in self.index.by_rid if rid.startswith("legal_hold_")):
                got = self.resolver.resolve(rid, LEGAL_SERVICE, req)
                if got.note:
                    notes.append((req.case_id, got.note))
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
