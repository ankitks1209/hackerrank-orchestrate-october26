"""Tests for the link solver (SPEC L2-L8): process-order candidates, the fixed point and the fallback.

Synthetic worlds use fictional ids and an EvidenceIndex whose owners are set directly. The
real-dataset class checks the acceptance numbers against the participant files (no media facts
are supplied, as in the index and candidate tests); the sample answers are read only through the
tests-only GoldReader.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import unittest
from dataclasses import replace
from types import MappingProxyType
from typing import Dict, List, Optional, Sequence, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.config import HOUR, REPO_ROOT, Config, Flags
from ghostaudit.dataset import DatasetReader, Identity
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_graph import (
    ACCOUNT_AGENT,
    ACCOUNT_FIFO,
    ACCOUNT_NONE,
    ACCOUNT_UNIQUE,
    ACTION_ASSIGN,
    ACTION_REJECT,
    ROW_AGENT,
    ROW_FIFO,
    ROW_NEVER_MIX,
    ROW_OWNER,
    TARGET_ACCOUNT,
    TARGET_ROW,
    LinkDecision,
)
from ghostaudit.link_solver import LinkSession, LinkSolution, link_cases
from ghostaudit.linking import generate_candidates
from ghostaudit.model import ActKind, ClassifiedActivity, Request, Treatment
from ghostaudit.timeutil import to_epoch
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

BASE = to_epoch("2026-03-01T12:00:00Z")
DAY = 24 * HOUR
AUDIT_DELTA = 6 * HOUR
REQUEST_LEAD = 2 * HOUR  # requested_at = reported_at - 2 h in the fixtures
USER_COUNT = 6
SOURCES = ("linking.py", "link_graph.py", "link_solver.py")
GHOSTAUDIT = REPO_ROOT / "code" / "ghostaudit"


def email_of(user: int) -> str:
    return "person.%d@example.com" % user


def identity_index() -> IdentityIndex:
    people = [
        Identity("user_%d" % n, "Person %d" % n, email_of(n), "+1555000%04d" % n, "%064x" % n, 0)
        for n in range(1, USER_COUNT + 1)
    ]
    return IdentityIndex.build(people, [])


def make_index(owners: Optional[Dict[str, Tuple[str, ...]]] = None) -> EvidenceIndex:
    empty = build_index((), identity_index(), {}, ())
    return replace(empty, users_by_rid=MappingProxyType(dict(owners or {})))


def request(
    case_id: str, user: int, reported_at: int = BASE, status: str = "COMPLETE"
) -> Request:
    return Request(
        case_id, email_of(user), reported_at - REQUEST_LEAD, status, reported_at,
        reported_at + AUDIT_DELTA, "please delete my data", False,
    )


def activity(
    activity_id: str,
    t: int,
    kind: ActKind,
    rid: str,
    treatment: Optional[Treatment] = None,
    system_id: str = "support_platform",
    result: str = "SUCCESS",
) -> ClassifiedActivity:
    return ClassifiedActivity(
        activity_id, t, kind, system_id, rid, treatment, result, None, None, None, None
    )


def account(activity_id: str, t: int, rid: str, result: str = "SUCCESS") -> ClassifiedActivity:
    return activity(
        activity_id, t, ActKind.ACCOUNT_SUBMIT, rid, Treatment.DELETE, "account_service", result
    )


def violating(activity_id: str, t: int, rid: str) -> ClassifiedActivity:
    return activity(activity_id, t, ActKind.VIOLATION, rid, Treatment.DELETE)


def compliant(
    activity_id: str, t: int, rid: str, treatment: Treatment = Treatment.ANONYMIZE
) -> ClassifiedActivity:
    return activity(activity_id, t, ActKind.POLICY_OK, rid, treatment)


def session(
    cases: Sequence[Request],
    acts: Sequence[ClassifiedActivity],
    owners: Optional[Dict[str, Tuple[str, ...]]] = None,
    **flags: bool,
) -> LinkSession:
    config = replace(Config(), flags=Flags(**flags))
    return LinkSession(cases, acts, make_index(owners), identity_index(), config)


def solve(
    cases: Sequence[Request],
    acts: Sequence[ClassifiedActivity],
    owners: Optional[Dict[str, Tuple[str, ...]]] = None,
    **flags: bool,
) -> LinkSolution:
    return session(cases, acts, owners, **flags).solve()


def resource_ids(solution: LinkSolution, case_id: str) -> List[str]:
    return [res.resource_id for res in solution.links[case_id].resources]


def basis_of(solution: LinkSolution, case_id: str, resource_id: str) -> str:
    for res in solution.links[case_id].resources:
        if res.resource_id == resource_id:
            return res.basis
    raise AssertionError("%s not linked to %s" % (resource_id, case_id))


class UniqueLinkTests(unittest.TestCase):
    def test_single_candidates_link_with_unique_basis(self) -> None:
        acts = [
            account("acc_1", BASE - 3000, "account_1"),
            violating("w_1", BASE + 3000, "support_1"),
            compliant("p_1", BASE - 900, "analytics_1"),
        ]
        found = solve([request("case_1", 1)], acts)
        links = found.links["case_1"]
        self.assertEqual((links.account_id, links.account_basis), ("account_1", ACCOUNT_UNIQUE))
        self.assertEqual(resource_ids(found, "case_1"), ["analytics_1", "support_1"])
        self.assertEqual(basis_of(found, "case_1", "support_1"), "unique")
        self.assertIn("account_row=acc_1", links.notes)

    def test_resource_carries_system_and_treatment_of_its_row(self) -> None:
        acts = [account("acc_1", BASE - 3000, "account_1"), violating("w_1", BASE + 3000, "support_1")]
        (resource,) = solve([request("case_1", 1)], acts).links["case_1"].resources
        self.assertEqual((resource.system_id, resource.treatment), ("support_platform", Treatment.DELETE))

    def test_case_without_account_candidates_has_none(self) -> None:
        found = solve([request("case_1", 1, status="NOT_STARTED")], [])
        self.assertEqual(
            (found.links["case_1"].account_id, found.links["case_1"].account_basis),
            (None, ACCOUNT_NONE),
        )

    def test_every_request_gets_links_in_natural_order(self) -> None:
        cases = [request("case_10", 1), request("case_9", 2)]
        self.assertEqual(list(solve(cases, []).links), ["case_9", "case_10"])


class ProcessOrderTests(unittest.TestCase):
    """SPEC L2, L3: candidates follow the order of the process and carry no fitted latency."""

    def candidates(self, acts: Sequence[ClassifiedActivity], case: Optional[Request] = None):
        return generate_candidates([case or request("case_1", 1)], acts, make_index(), identity_index())

    def test_account_rows_lie_after_the_request_and_up_to_the_report(self) -> None:
        requested = BASE - REQUEST_LEAD
        acts = [
            account("at_request", requested, "account_1"),
            account("just_after", requested + 1, "account_2"),
            account("at_report", BASE, "account_3"),
            account("after_report", BASE + 1, "account_4"),
        ]
        self.assertEqual(
            self.candidates(acts).accounts_of_case["case_1"], ("just_after", "at_report")
        )

    def test_account_row_must_mirror_the_reported_status(self) -> None:
        acts = [account("ok", BASE - 600, "account_1"), account("failed", BASE - 500, "account_2", "FAILED")]
        self.assertEqual(self.candidates(acts).accounts_of_case["case_1"], ("ok",))

    def test_a_long_gap_between_request_and_report_is_not_cut_by_a_constant(self) -> None:
        long_case = Request(
            "case_1", email_of(1), BASE - 40 * HOUR, "COMPLETE", BASE, BASE + AUDIT_DELTA, "delete", False
        )
        acts = [account("early", BASE - 39 * HOUR, "account_1"), account("late", BASE - 60, "account_2")]
        self.assertEqual(self.candidates(acts, long_case).accounts_of_case["case_1"], ("early", "late"))

    def test_policy_rows_precede_the_report_and_violation_rows_follow_it(self) -> None:
        requested = BASE - REQUEST_LEAD
        acts = [
            compliant("p_before", requested, "analytics_1"),
            compliant("p_ok", BASE - 1, "analytics_2"),
            compliant("p_at_report", BASE, "analytics_3"),
            compliant("p_after", BASE + 1, "analytics_4"),
            violating("v_before", BASE - 1, "support_1"),
            violating("v_at_report", BASE, "support_2"),
            violating("v_ok", BASE + 1, "support_3"),
            violating("v_at_audit", BASE + AUDIT_DELTA, "support_4"),
            violating("v_after_audit", BASE + AUDIT_DELTA + 1, "support_5"),
        ]
        self.assertEqual(
            self.candidates(acts).rows_of_case["case_1"],
            ("p_ok", "p_at_report", "v_ok", "v_at_audit"),
        )

    def test_the_sources_hold_no_fitted_latency_constants(self) -> None:
        for name in SOURCES:
            text = (GHOSTAUDIT / name).read_text(encoding="utf-8")
            for word in ("% 60", "window_offset", "account_window", "violation_window", "Signature"):
                self.assertNotIn(word, text, "%s mentions %s" % (name, word))


class EvidenceOwnerTests(unittest.TestCase):
    """SPEC L1, L4a: evidence that ties a resource to a subject pins it to that subject's case."""

    def test_owned_account_rows_pin_their_cases(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        acts = [account("acc_a", BASE - 3600, "account_9"), account("acc_b", BASE - 3000, "account_2")]
        owners = {"account_9": ("user_1",), "account_2": ("user_2",)}
        found = solve(cases, acts, owners)
        self.assertEqual(found.links["case_1"].account_id, "account_9")
        self.assertEqual(found.links["case_2"].account_id, "account_2")
        self.assertEqual(found.links["case_1"].account_basis, ACCOUNT_UNIQUE)

    def test_an_account_the_subject_owns_replaces_ownerless_candidates(self) -> None:
        acts = [account("acc_a", BASE - 3600, "account_9"), account("acc_b", BASE - 3000, "account_2")]
        found = solve([request("case_1", 1)], acts, {"account_2": ("user_1",)})
        self.assertEqual(found.links["case_1"].account_id, "account_2")
        self.assertEqual(found.links["case_1"].account_basis, ACCOUNT_UNIQUE)

    def test_owned_worker_row_is_tied_to_its_owner_by_identifier(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        acts = [
            account("acc_a", BASE - 3600, "account_9"),
            account("acc_b", BASE - 3000, "account_2"),
            violating("w_1", BASE + 1820, "support_1"),
        ]
        owners = {"account_9": ("user_1",), "account_2": ("user_2",), "support_1": ("user_1",)}
        found = solve(cases, acts, owners)
        self.assertEqual(resource_ids(found, "case_1"), ["support_1"])
        self.assertEqual(basis_of(found, "case_1", "support_1"), ROW_OWNER)
        self.assertEqual(resource_ids(found, "case_2"), [])


class FifoTests(unittest.TestCase):
    """The low-confidence fallback: ascending account ids to ascending case ids, nearest report for rows."""

    def test_tied_accounts_are_paired_in_id_order(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        acts = [account("acc_7", BASE - 3000, "account_7"), account("acc_5", BASE - 3625, "account_5")]
        found = solve(cases, acts)
        self.assertEqual(found.links["case_1"].account_id, "account_5")
        self.assertEqual(found.links["case_2"].account_id, "account_7")
        self.assertEqual(found.links["case_1"].account_basis, ACCOUNT_FIFO)

    def test_flag_off_leaves_accounts_and_rows_tied(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2)]
        acts = [
            account("acc_5", BASE - 3625, "account_5"),
            account("acc_7", BASE - 3000, "account_7"),
            compliant("p_1", BASE - 1550, "analytics_1"),
        ]
        found = solve(cases, acts, fifo_pairing=False)
        self.assertIsNone(found.links["case_1"].account_id)
        self.assertEqual(found.links["case_1"].account_basis, ACCOUNT_NONE)
        self.assertIn("account tied between acc_5, acc_7", found.links["case_1"].notes)
        self.assertEqual(resource_ids(found, "case_1") + resource_ids(found, "case_2"), [])
        self.assertEqual(found.stats.rows_unresolved, 1)

    def test_a_tied_policy_row_goes_to_the_case_that_reports_first(self) -> None:
        cases = [request("case_1", 1, reported_at=BASE + HOUR), request("case_2", 2, reported_at=BASE)]
        acts = [
            account("acc_1", BASE - 3000, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            compliant("p_1", BASE - 900, "analytics_1"),
        ]
        owners = {"account_1": ("user_1",), "account_2": ("user_2",)}
        found = solve(cases, acts, owners)
        self.assertEqual(resource_ids(found, "case_2"), ["analytics_1"])
        self.assertEqual(basis_of(found, "case_2", "analytics_1"), ROW_FIFO)

    def test_a_tied_violation_row_goes_to_the_latest_report_before_it(self) -> None:
        cases = [request("case_1", 1, reported_at=BASE), request("case_2", 2, reported_at=BASE + HOUR)]
        acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE + 100, "account_2"),
            violating("v_1", BASE + HOUR + 600, "support_9"),
        ]
        owners = {"account_1": ("user_1",), "account_2": ("user_2",)}
        found = solve(cases, acts, owners)
        self.assertEqual(resource_ids(found, "case_2"), ["support_9"])

    def test_pairing_serves_cases_that_share_a_subset_of_accounts(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2), request("case_3", 3)]
        acts = [
            account("acc_a", BASE - 3600, "account_3"),
            account("acc_b", BASE - 3500, "account_4"),
            account("acc_c", BASE - 3400, "account_5"),
        ]
        found = solve(cases, acts)
        self.assertEqual(
            [found.links[c].account_id for c in ("case_1", "case_2", "case_3")],
            ["account_3", "account_4", "account_5"],
        )

    def test_unmatched_surplus_case_keeps_no_account(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2), request("case_3", 3)]
        acts = [account("acc_a", BASE - 3600, "account_3"), account("acc_b", BASE - 3500, "account_4")]
        found = solve(cases, acts)
        self.assertEqual(found.links["case_3"].account_basis, ACCOUNT_NONE)
        self.assertEqual(found.stats.account_basis, {ACCOUNT_FIFO: 2, ACCOUNT_NONE: 1})


class OneCasePerAccountTests(unittest.TestCase):
    """SPEC L4b: an account claimed by an evidence-pinned case leaves the other cases."""

    def setUp(self) -> None:
        self.acts = [
            account("acc_a", BASE - 3600, "account_3"),
            account("acc_b", BASE - 3000, "account_4"),
        ]
        self.owners = {"account_3": ("user_1",), "account_4": ("user_2",)}

    def account_rows(self, found: LinkSolution) -> List[str]:
        return [
            note for links in found.links.values() for note in links.notes
            if note.startswith("account_row=")
        ]

    def test_case_whose_accounts_belong_to_other_subjects_is_left_with_none(self) -> None:
        cases = [request("case_1", 1), request("case_2", 2), request("case_3", 3)]
        found = solve(cases, self.acts, self.owners)
        self.assertEqual(found.links["case_1"].account_id, "account_3")
        self.assertEqual(found.links["case_2"].account_id, "account_4")
        self.assertEqual(found.links["case_3"].account_basis, ACCOUNT_NONE)
        rows = self.account_rows(found)
        self.assertEqual(len(rows), len(set(rows)))
        self.assertEqual(found.stats.account_basis, {ACCOUNT_NONE: 1, ACCOUNT_UNIQUE: 2})

    def test_cases_left_sharing_one_account_are_paired_not_unique(self) -> None:
        cases = [request("case_%d" % n, n) for n in (3, 4)]
        acts = [account("acc_c", BASE - 3610, "account_5")]
        found = solve(cases, acts)
        self.assertEqual(found.links["case_3"].account_id, "account_5")
        self.assertEqual(found.links["case_3"].account_basis, ACCOUNT_FIFO)
        self.assertEqual(found.links["case_4"].account_basis, ACCOUNT_NONE)
        rows = self.account_rows(found)
        self.assertEqual(len(rows), len(set(rows)))

    def test_without_fifo_a_shared_account_stays_tied(self) -> None:
        cases = [request("case_%d" % n, n) for n in (3, 4)]
        acts = [account("acc_c", BASE - 3610, "account_5")]
        found = solve(cases, acts, fifo_pairing=False)
        for case_id in ("case_3", "case_4"):
            self.assertEqual(found.links[case_id].account_basis, ACCOUNT_NONE)
            self.assertIn("account tied between acc_c", found.links[case_id].notes)


class NeverMixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = [request("case_1", 1), request("case_2", 2)]
        self.owners = {
            "account_1": ("user_1",),
            "account_2": ("user_2",),
            "support_1": ("user_1",),
        }
        self.acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            violating("v_1", BASE + 2000, "support_1"),
            compliant("p_1", BASE - 900, "analytics_1"),
            compliant("lh_1", BASE - 600, "legal_hold_1", Treatment.RETAIN),
        ]

    def test_compliant_row_avoids_the_violating_case_and_legal_hold_is_exempt(self) -> None:
        found = solve(self.cases, self.acts, self.owners)
        self.assertEqual(basis_of(found, "case_2", "analytics_1"), ROW_NEVER_MIX)
        self.assertEqual(basis_of(found, "case_1", "legal_hold_1"), ROW_FIFO)
        self.assertEqual(resource_ids(found, "case_1"), ["legal_hold_1", "support_1"])

    def test_flag_off_pairs_by_report_order_alone(self) -> None:
        found = solve(self.cases, self.acts, self.owners, never_mix=False)
        self.assertEqual(basis_of(found, "case_1", "analytics_1"), ROW_FIFO)
        self.assertEqual(basis_of(found, "case_1", "legal_hold_1"), ROW_FIFO)

    def test_violating_row_avoids_the_compliant_case(self) -> None:
        owners = {"account_1": ("user_1",), "account_2": ("user_2",), "analytics_1": ("user_1",)}
        acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            compliant("p_1", BASE - 900, "analytics_1"),
            violating("v_x", BASE + 2000, "support_9"),
        ]
        found = solve(self.cases, acts, owners)
        self.assertEqual(basis_of(found, "case_2", "support_9"), ROW_NEVER_MIX)

    def test_replication_checkpoint_marks_the_case_violating(self) -> None:
        checkpoint = activity(
            "r_1", BASE + HOUR, ActKind.REPLICATION_CHECKPOINT, "account_1", None, "account_service"
        )
        owners = {"account_1": ("user_1",), "account_2": ("user_2",)}
        acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            checkpoint,
            compliant("p_1", BASE - 900, "analytics_1"),
        ]
        found = solve(self.cases, acts, owners)
        self.assertEqual(resource_ids(found, "case_2"), ["analytics_1"])
        self.assertEqual(resource_ids(found, "case_1"), [])

    def test_checkpoint_after_audit_is_not_used(self) -> None:
        late = activity(
            "r_1", BASE + AUDIT_DELTA + 1, ActKind.REPLICATION_CHECKPOINT, "account_1", None,
            "account_service",
        )
        owners = {"account_1": ("user_1",), "account_2": ("user_2",)}
        acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            late,
            compliant("p_1", BASE - 900, "analytics_1"),
        ]
        found = solve(self.cases, acts, owners)
        self.assertEqual(basis_of(found, "case_1", "analytics_1"), ROW_FIFO)


class DecoyTests(unittest.TestCase):
    def test_row_owned_by_a_user_without_a_case_is_dropped(self) -> None:
        acts = [
            account("acc_1", BASE - 3000, "account_1"),
            violating("w_x", BASE + 3000, "support_5"),
        ]
        found = solve([request("case_1", 1)], acts, {"support_5": ("user_5",)})
        self.assertEqual(resource_ids(found, "case_1"), [])

    def test_ownerless_row_that_precedes_the_account_of_its_case_is_dropped(self) -> None:
        acts = [
            account("acc_1", BASE - 1000, "account_1"),
            compliant("before", BASE - 2000, "analytics_1"),
            compliant("after", BASE - 500, "analytics_2"),
        ]
        found = solve([request("case_1", 1)], acts)
        self.assertEqual(resource_ids(found, "case_1"), ["analytics_2"])

    def test_owned_row_is_kept_although_it_precedes_the_account(self) -> None:
        acts = [
            account("acc_1", BASE - 1000, "account_1"),
            compliant("before", BASE - 2000, "analytics_1"),
        ]
        found = solve([request("case_1", 1)], acts, {"analytics_1": ("user_1",)})
        self.assertEqual(basis_of(found, "case_1", "analytics_1"), ROW_OWNER)

    def test_case_without_an_account_links_only_owned_rows(self) -> None:
        cases = [request("case_1", 1, status="NOT_STARTED")]
        acts = [violating("w_1", BASE + 3000, "support_1"), violating("w_2", BASE + 3100, "support_2")]
        found = solve(cases, acts, {"support_1": ("user_1",)})
        self.assertEqual(resource_ids(found, "case_1"), ["support_1"])

    def test_duplicate_resource_rows_collapse_to_one_resource(self) -> None:
        acts = [
            account("acc_1", BASE - 3000, "account_1"),
            violating("w_1", BASE + 3000, "support_1"),
            violating("w_2", BASE + 3100, "support_1"),
        ]
        found = solve([request("case_1", 1)], acts)
        self.assertEqual(resource_ids(found, "case_1"), ["support_1"])


class DecisionTests(unittest.TestCase):
    """SPEC 12.4: agent decisions are applied between the fixed point and the fallback."""

    def setUp(self) -> None:
        self.cases = [request("case_1", 1), request("case_2", 2)]
        self.acts = [
            account("acc_1", BASE - 3600, "account_1"),
            account("acc_2", BASE - 3300, "account_2"),
            violating("v_x", BASE + 2000, "support_9"),
        ]
        self.owners = {"account_1": ("user_1",), "account_2": ("user_2",)}
        self.session = session(self.cases, self.acts, self.owners)

    def test_the_contest_names_the_row_and_its_competing_cases(self) -> None:
        self.assertEqual(dict(self.session.contest().rows), {"v_x": ("case_1", "case_2")})

    def test_an_assignment_gives_the_row_to_the_chosen_case(self) -> None:
        decision = LinkDecision(TARGET_ROW, "v_x", ACTION_ASSIGN, "case_2")
        found = self.session.solve([decision])
        self.assertEqual(found.applied, 1)
        self.assertEqual(resource_ids(found, "case_2"), ["support_9"])
        self.assertEqual(basis_of(found, "case_2", "support_9"), ROW_AGENT)
        self.assertEqual(resource_ids(found, "case_1"), [])

    def test_a_rejection_drops_the_row_as_a_decoy(self) -> None:
        found = self.session.solve([LinkDecision(TARGET_ROW, "v_x", ACTION_REJECT)])
        self.assertEqual(resource_ids(found, "case_1") + resource_ids(found, "case_2"), [])

    def test_a_decision_for_a_non_candidate_is_skipped_and_the_fallback_decides(self) -> None:
        found = self.session.solve([LinkDecision(TARGET_ROW, "v_x", ACTION_ASSIGN, "case_9")])
        self.assertEqual(found.applied, 0)
        self.assertEqual(basis_of(found, "case_1", "support_9"), ROW_FIFO)  # equal reports: the lower id

    def test_an_account_assignment_resolves_a_tied_pair(self) -> None:
        tied = session([request("case_1", 1), request("case_2", 2)],
                       [account("acc_a", BASE - 3600, "account_3"), account("acc_b", BASE - 3000, "account_4")])
        self.assertEqual(sorted(tied.contest().accounts), ["acc_a", "acc_b"])
        found = tied.solve([LinkDecision(TARGET_ACCOUNT, "acc_b", ACTION_ASSIGN, "case_1")])
        self.assertEqual(found.links["case_1"].account_id, "account_4")
        self.assertEqual(found.links["case_1"].account_basis, ACCOUNT_AGENT)

    def test_solving_twice_with_the_same_decisions_is_identical(self) -> None:
        decision = LinkDecision(TARGET_ROW, "v_x", ACTION_ASSIGN, "case_1")
        self.assertEqual(self.session.solve([decision]).links, self.session.solve([decision]).links)

    def test_link_cases_is_the_one_shot_form(self) -> None:
        config = replace(Config(), flags=Flags())
        once = link_cases(self.cases, self.acts, make_index(self.owners), identity_index(), config)
        self.assertEqual(once.links, self.session.solve().links)


class StaticTests(unittest.TestCase):
    def test_sources_use_no_dataset_ids_and_no_id_arithmetic(self) -> None:
        literal = re.compile(r"\b(?:case|user|account|activity|search|support|analytics)_\d+")
        parsed = re.compile(r"int\([^)]*(?:_id|\bid\b)[^)]*\)|\.split\(\"_\"\)")
        for name in SOURCES:
            for number, line in enumerate((GHOSTAUDIT / name).read_text(encoding="utf-8").splitlines(), 1):
                self.assertIsNone(literal.search(line), "%s:%d %s" % (name, number, line))
                self.assertIsNone(parsed.search(line), "%s:%d %s" % (name, number, line))

    def test_no_print_and_no_solution_folder(self) -> None:
        for name in SOURCES:
            text = (GHOSTAUDIT / name).read_text(encoding="utf-8")
            self.assertNotIn("print(", text)
            self.assertNotIn("solution/", text)
            self.assertNotIn("sample_output", text)


FINGERPRINT_SCRIPT = """
import hashlib
from ghostaudit.activity import classify_activity
from ghostaudit.config import Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.index import build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_solver import link_cases
reader = DatasetReader(%r)
identity = IdentityIndex.build(reader.identities(), reader.audit_log())
index = build_index(reader.manifest(), identity, {}, classify_activity(reader.activity()))
solution = link_cases(reader.requests(), classify_activity(reader.activity()), index, identity, Config())
print(hashlib.sha256(repr((list(solution.links.items()), solution.stats, solution.contest)).encode()).hexdigest())
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
        cls.solution = link_cases(cls.requests, cls.acts, cls.index, cls.identity, Config())
        cls.gold = GoldReader().cases()
        cls.submitted = {a.resource_id for a in cls.acts if a.kind is ActKind.ACCOUNT_SUBMIT}

    def gold_account(self, case_id: str) -> Optional[str]:
        found = {s.resource_id for s in self.gold[case_id].steps if s.system_id == "account_service"}
        return next(iter(found)) if found & self.submitted else None

    def test_every_sample_with_a_worker_account_row_is_checked(self) -> None:
        checked = [case_id for case_id in sorted(self.gold) if self.gold_account(case_id) is not None]
        self.assertEqual(len(checked), 24)

    def test_the_fixed_point_never_links_a_wrong_account_to_a_sample_when_it_is_unique(self) -> None:
        """Unique means the evidence or process order left one candidate; it must then be the gold account."""
        wrong = [
            case_id for case_id in sorted(self.gold)
            if self.gold_account(case_id) is not None
            and self.solution.links[case_id].account_basis == ACCOUNT_UNIQUE
            and self.solution.links[case_id].account_id != self.gold_account(case_id)
        ]
        self.assertEqual(wrong, [])

    def test_no_account_row_is_linked_to_two_cases(self) -> None:
        rows = [
            note for links in self.solution.links.values() for note in links.notes
            if note.startswith("account_row=")
        ]
        self.assertEqual(len(rows), len(set(rows)))
        linked = sum(links.account_id is not None for links in self.solution.links.values())
        self.assertEqual(len(rows), linked)

    def test_the_contest_is_what_the_fallback_decides(self) -> None:
        stats = self.solution.stats
        self.assertGreater(stats.rows_ambiguous, 0)
        self.assertLessEqual(stats.rows_unresolved, stats.rows_ambiguous)
        self.assertEqual(sorted(self.solution.contest.rows), sorted(set(self.solution.contest.rows)))
        for cases in self.solution.contest.rows.values():
            self.assertGreater(len(cases), 1)

    def test_a_subject_owning_exactly_one_window_account_by_evidence_mostly_gets_it(self) -> None:
        """Evidence ownership (L1) decides most cases; the exceptions are a rival's claim or the fallback.

        The case's own evidence-owned account rows replace its ownerless candidates, so every single-case
        subject that owns exactly one window account gets it unless a rival's claim on the same row
        removes it (the tie is admissible for the owner only just before its audit, not for the rival).
        """
        cases_of: Dict[Optional[str], List[str]] = {}
        for req in self.requests:
            cases_of.setdefault(self.identity.resolve(req.email), []).append(req.case_id)
        agree = wrong_unique = checked = 0
        for req in self.requests:
            subject = self.identity.resolve(req.email)
            if len(cases_of[subject]) != 1:
                continue  # a subject with several cases owns the same account in each window
            owned = [
                a.resource_id for a in self.acts
                if a.kind is ActKind.ACCOUNT_SUBMIT
                and req.requested_at < a.t <= req.reported_at
                and subject in self.index.users_by_rid.get(a.resource_id, ())
                and self.index.tied_by(a.resource_id, subject, req.audit_at)
            ]
            if len(owned) != 1:
                continue
            checked += 1
            links = self.solution.links[req.case_id]
            agree += links.account_id == owned[0]
            wrong_unique += links.account_id != owned[0] and links.account_basis == ACCOUNT_UNIQUE
        self.assertGreater(checked, 100)
        self.assertGreaterEqual(agree / checked, 0.99)
        self.assertLessEqual(wrong_unique, 0)

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
