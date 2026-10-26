"""Tests for ghostaudit.linking candidate generation (SPEC L2, L3, L4a): process order, no fitted window.

Synthetic timelines use fictional ids and an EvidenceIndex whose owners are set
directly. The real-dataset class checks the acceptance facts against the
participant files (no media facts are supplied, as in the index tests).
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.config import HOUR, MINUTE, REPO_ROOT
from ghostaudit.dataset import DatasetReader, Identity
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.identity import IdentityIndex
from ghostaudit.linking import (
    Candidates,
    generate_candidates,
)
from ghostaudit.model import ActKind, ClassifiedActivity, Request
from ghostaudit.timeutil import to_epoch
from evaluation.gold import GoldReader
from tests.dataset_guard import needs_dataset

BASE = to_epoch("2026-03-01T12:00:00Z")
AUDIT_DELTA = 4 * HOUR
HASH_A = "a" * 64
HASH_B = "b" * 64


def identity_index() -> IdentityIndex:
    ann = Identity("user_1", "Ann Test", "ann.test@example.com", "+15550000001", HASH_A, 0)
    bob = Identity("user_2", "Bob Test", "bob.test@example.com", "+15550000002", HASH_B, 0)
    return IdentityIndex.build([ann, bob], [])


def make_index(owners: Optional[Dict[str, Tuple[str, ...]]] = None) -> EvidenceIndex:
    """An empty EvidenceIndex whose `users_by_rid` is `owners`."""
    empty = build_index((), identity_index(), {}, ())
    return replace(empty, users_by_rid=owners or {})


def request(
    case_id: str,
    email: str = "ann.test@example.com",
    status: str = "COMPLETE",
    reported_at: int = BASE,
    audit_delta: int = AUDIT_DELTA,
) -> Request:
    return Request(
        case_id, email, reported_at - HOUR, status, reported_at, reported_at + audit_delta,
        "please delete my data", False,
    )


def activity(
    activity_id: str, t: int, kind: ActKind, rid: str, result: str = "SUCCESS"
) -> ClassifiedActivity:
    return ClassifiedActivity(
        activity_id, t, kind, "account_service", rid, None, result, None, None, None, None
    )


def account(activity_id: str, offset: int, rid: str = "account_1", result: str = "SUCCESS"):
    """An ACCOUNT_SUBMIT row `offset` seconds after BASE."""
    return activity(activity_id, BASE + offset, ActKind.ACCOUNT_SUBMIT, rid, result)


def worker(activity_id: str, offset: int, kind: ActKind, rid: str = "support_1"):
    return activity(activity_id, BASE + offset, kind, rid)


def generate(
    requests: Sequence[Request],
    acts: Sequence[ClassifiedActivity],
    owners: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> Candidates:
    return generate_candidates(requests, acts, make_index(owners), identity_index())


class AccountWindowTests(unittest.TestCase):
    def test_account_rows_follow_the_request_and_end_at_the_report(self) -> None:
        acts = [
            account("a_at_request", -HOUR),
            account("a_just_after", -HOUR + 1),
            account("a_mid", -30 * MINUTE),
            account("a_at_report", 0),
            account("a_after", 1),
        ]
        found = generate([request("case_1")], acts)
        self.assertEqual(found.accounts_of_case["case_1"], ("a_just_after", "a_mid", "a_at_report"))

    def test_mirror_filter_per_reported_status(self) -> None:
        acts = [
            account("a_ok", -30 * MINUTE, result="SUCCESS"),
            account("a_part", -30 * MINUTE, result="PARTIAL"),
            account("a_fail", -30 * MINUTE, result="FAILED"),
        ]
        expected = {"COMPLETE": "a_ok", "PARTIALLY_COMPLETE": "a_part", "NOT_STARTED": "a_fail"}
        for status, account_id in expected.items():
            found = generate([request("case_1", status=status)], acts)
            self.assertEqual(found.accounts_of_case["case_1"], (account_id,), status)

    def test_unknown_status_has_no_account(self) -> None:
        found = generate([request("case_1", status="UNKNOWN")], [account("a_ok", -30 * MINUTE)])
        self.assertEqual(dict(found.accounts_of_case), {})

    def test_overlapping_timelines_share_an_account(self) -> None:
        near = request("case_1", reported_at=BASE)
        shifted = request("case_2", email="bob.test@example.com", reported_at=BASE + 20 * MINUTE)
        far = request("case_3", reported_at=BASE + 3 * HOUR)
        acts = [account("a_shared", -30 * MINUTE), account("a_late", 10 * MINUTE)]
        found = generate([far, shifted, near], acts)
        self.assertEqual(found.cases_of_account["a_shared"], ("case_1", "case_2"))
        self.assertEqual(found.cases_of_account["a_late"], ("case_2",))
        self.assertEqual(found.accounts_of_case["case_2"], ("a_shared", "a_late"))
        self.assertNotIn("case_3", found.accounts_of_case)

    def test_cases_are_ordered_naturally(self) -> None:
        requests = [request("case_10"), request("case_9"), request("case_32")]
        found = generate(requests, [account("a_1", -30 * MINUTE)])
        self.assertEqual(found.cases_of_account["a_1"], ("case_9", "case_10", "case_32"))
        self.assertEqual(list(found.accounts_of_case), ["case_9", "case_10", "case_32"])


class OwnerFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = [request("case_1"), request("case_2", email="bob.test@example.com")]
        self.acts = [account("a_1", -30 * MINUTE, rid="account_9")]

    def test_ownerless_resource_stays_a_candidate_of_every_case(self) -> None:
        found = generate(self.cases, self.acts)
        self.assertEqual(found.cases_of_account["a_1"], ("case_1", "case_2"))

    def test_owned_resource_keeps_only_its_owner(self) -> None:
        found = generate(self.cases, self.acts, owners={"account_9": ("user_2",)})
        self.assertEqual(found.cases_of_account["a_1"], ("case_2",))

    def test_email_match_ignores_case(self) -> None:
        cases = [request("case_1", email="ANN.TEST@example.com")]
        found = generate(cases, self.acts, owners={"account_9": ("user_1",)})
        self.assertEqual(found.cases_of_account["a_1"], ("case_1",))

    def test_unresolved_subject_cannot_own_an_owned_resource(self) -> None:
        cases = [request("case_1", email="nobody@example.com")]
        found = generate(cases, self.acts, owners={"account_9": ("user_1",)})
        self.assertNotIn("a_1", found.cases_of_account)

    def test_owner_filter_applies_to_worker_rows(self) -> None:
        rows = [worker("w_1", 60 * MINUTE, ActKind.VIOLATION, rid="support_7")]
        found = generate(self.cases, rows, owners={"support_7": ("user_1",)})
        self.assertEqual(found.cases_of_row["w_1"], ("case_1",))


class WorkerRowOrderTests(unittest.TestCase):
    """Policy rows are applied between the request and the report; the rest is observed until the audit."""

    def test_policy_rows_lie_after_the_request_and_end_at_the_report(self) -> None:
        rows = [
            worker("p_at_request", -HOUR, ActKind.POLICY_OK),
            worker("p_low", -HOUR + 1, ActKind.POLICY_OK),
            worker("p_high", 0, ActKind.POLICY_OK),
            worker("p_late", 1, ActKind.POLICY_OK),
        ]
        found = generate([request("case_1")], rows)
        self.assertEqual(found.rows_of_case["case_1"], ("p_low", "p_high"))

    def test_violation_side_rows_cover_all_three_kinds_after_the_report(self) -> None:
        kinds = (ActKind.VIOLATION, ActKind.FLOW_ENABLED, ActKind.RESTORE_ALLOWED)
        rows = [worker("in_%s" % kind.name, 31 * MINUTE, kind) for kind in kinds]
        rows += [worker("at_report_%s" % kind.name, 0, kind) for kind in kinds]
        rows += [worker("late_%s" % kind.name, 13 * HOUR, kind) for kind in kinds]
        found = generate([request("case_1", audit_delta=12 * HOUR)], rows)
        self.assertEqual(
            set(found.rows_of_case["case_1"]), {"in_%s" % kind.name for kind in kinds}
        )

    def test_violation_rows_start_after_the_report_and_end_at_audit_at(self) -> None:
        rows = [
            worker("v_at_report", 0, ActKind.VIOLATION),
            worker("v_first", 1, ActKind.VIOLATION),
            worker("v_at", 60 * MINUTE, ActKind.VIOLATION),
            worker("v_after", 60 * MINUTE + 1, ActKind.VIOLATION),
        ]
        found = generate([request("case_1", audit_delta=HOUR)], rows)
        self.assertEqual(found.rows_of_case["case_1"], ("v_first", "v_at"))

    def test_a_violation_row_far_after_the_report_is_not_cut_by_a_constant(self) -> None:
        rows = [worker("v_far", 11 * HOUR, ActKind.VIOLATION)]
        found = generate([request("case_1", audit_delta=12 * HOUR)], rows)
        self.assertEqual(found.rows_of_case["case_1"], ("v_far",))

    def test_policy_row_is_not_matched_after_the_report_nor_violation_row_before_it(self) -> None:
        rows = [
            worker("p_after", 60 * MINUTE, ActKind.POLICY_OK),
            worker("v_before", -10 * MINUTE, ActKind.VIOLATION),
        ]
        self.assertEqual(dict(generate([request("case_1")], rows).rows_of_case), {})

    def test_rows_of_a_case_are_in_time_order(self) -> None:
        rows = [
            worker("v_2", 90 * MINUTE, ActKind.VIOLATION),
            worker("p_1", -10 * MINUTE, ActKind.POLICY_OK),
            worker("v_1", 40 * MINUTE, ActKind.VIOLATION),
        ]
        found = generate([request("case_1", audit_delta=12 * HOUR)], rows)
        self.assertEqual(found.rows_of_case["case_1"], ("p_1", "v_1", "v_2"))

    def test_overlapping_cases_share_a_row(self) -> None:
        cases = [request("case_1"), request("case_2", reported_at=BASE + 30 * MINUTE)]
        rows = [worker("v_1", 70 * MINUTE, ActKind.VIOLATION)]
        found = generate(cases, rows)
        self.assertEqual(found.cases_of_row["v_1"], ("case_1", "case_2"))


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    """Acceptance facts on the participant files; media facts are not supplied."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        cls.identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(reader.manifest(), cls.identity, {}, classify_activity(reader.activity()))
        cls.requests = reader.requests()
        cls.acts = classify_activity(reader.activity())
        cls.by_id = {act.activity_id: act for act in cls.acts}
        cls.found = generate_candidates(cls.requests, cls.acts, cls.index, cls.identity)

    def test_every_sample_account_row_is_a_candidate(self) -> None:
        gold = GoldReader().cases()
        submitted = {
            act.resource_id for act in self.acts if act.kind is ActKind.ACCOUNT_SUBMIT
        }
        hits = 0
        for req in self.requests:
            if not req.is_sample:
                continue
            true_accounts = {
                step.resource_id
                for step in gold[req.case_id].steps
                if step.system_id == "account_service"
            }
            if not true_accounts & submitted:
                continue
            candidates = {
                self.by_id[a].resource_id for a in self.found.accounts_of_case.get(req.case_id, ())
            }
            self.assertTrue(true_accounts & candidates, req.case_id)
            hits += 1
        self.assertEqual(hits, 24)

    def test_edges_follow_process_order_and_stop_at_audit_at(self) -> None:
        requests = {req.case_id: req for req in self.requests}
        for row_id, case_ids in self.found.cases_of_row.items():
            act = self.by_id[row_id]
            for case_id in case_ids:
                req = requests[case_id]
                if act.kind is ActKind.POLICY_OK:
                    self.assertTrue(req.requested_at < act.t <= req.reported_at, row_id)
                else:
                    self.assertTrue(req.reported_at < act.t <= req.audit_at, row_id)
        for account_id, case_ids in self.found.cases_of_account.items():
            act = self.by_id[account_id]
            for case_id in case_ids:
                self.assertTrue(requests[case_id].requested_at < act.t <= requests[case_id].reported_at)

    def test_evidence_owned_rows_obey_the_process_order_the_bounds_assume(self) -> None:
        """The grounding of the bounds, checked on all rows rather than on the candidates.

        A worker row whose resource identifiers tie to a single-case subject lies on the expected side of
        that case's report: policy rows no later than it, violation, flow and restore rows after it. This
        is the only fact the bounds rest on; no offset in seconds is used.
        """
        cases_of: Dict[str, List[Request]] = {}
        for req in self.requests:
            cases_of.setdefault(self.identity.resolve(req.email), []).append(req)
        checked = {"policy": 0, "violation": 0}
        for act in self.acts:
            if act.kind not in (ActKind.POLICY_OK, ActKind.VIOLATION, ActKind.FLOW_ENABLED, ActKind.RESTORE_ALLOWED):
                continue
            for owner in self.index.users_by_rid.get(act.resource_id, ()):
                owner_cases = cases_of.get(owner, [])
                if len(owner_cases) != 1 or not self.index.tied_by(act.resource_id, owner, owner_cases[0].audit_at):
                    continue
                req = owner_cases[0]
                if act.t > req.audit_at or act.t <= req.requested_at:
                    continue  # the row belongs to some other period of the owner, not to this request
                if act.kind is ActKind.POLICY_OK:
                    checked["policy"] += 1
                    self.assertLessEqual(act.t, req.reported_at, act.activity_id)
                else:
                    checked["violation"] += 1
                    self.assertGreater(act.t, req.reported_at, act.activity_id)
        self.assertGreater(checked["policy"], 0)
        self.assertGreater(checked["violation"], 0)

    def test_generation_is_deterministic(self) -> None:
        again = generate_candidates(
            tuple(reversed(self.requests)), self.acts, self.index, self.identity
        )
        self.assertEqual(dict(again.cases_of_row), dict(self.found.cases_of_row))
        self.assertEqual(dict(again.accounts_of_case), dict(self.found.accounts_of_case))
        self.assertEqual(list(again.rows_of_case), list(self.found.rows_of_case))


if __name__ == "__main__":
    unittest.main()
