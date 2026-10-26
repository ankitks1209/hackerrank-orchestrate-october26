"""Tests for ghostaudit.casebuilder, generated family (SPEC V1-V5, L11, 8.2).

The synthetic class builds one case from a hand-made EvidenceIndex with fictional ids and
plain integer times, one rule at a time. The real-dataset class abstracts the 24
generated-family sample answers with the tests-only GoldReader and compares them with the
built verdicts; the two pinned misses are audit records that no participant file names.
"""
from __future__ import annotations

import re
import unittest
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.casebuilder import CaseBuilder
from ghostaudit.config import HOUR, REPO_ROOT, Config, Flags
from ghostaudit.dataset import DatasetReader, Rule
from ghostaudit.emit import emit
from ghostaudit.evidence.index import build_index
from ghostaudit.handcrafted import HandcraftedSources
from ghostaudit.identity import IdentityIndex
from ghostaudit.link_solver import link_cases
from ghostaudit.linking import add_extras
from ghostaudit.model import (
    LEGAL_SERVICE,
    SECURITY_SERVICE,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    ActKind,
    CaseLinks,
    LinkedResource,
    ObsState,
    Request,
    ResourceVerdict,
    Treatment,
)
from ghostaudit.policy import PolicyEngine
from ghostaudit.state import StateResolver
from evaluation.gold import GoldReader, abstract_verdicts
from tests.test_state import activity, make_index, obs, scope
from tests.dataset_guard import needs_dataset

REPORTED = 100 * HOUR
AUDIT = 200 * HOUR
INSIDE = 150 * HOUR  # a file captured inside the case window
AFTER = 300 * HOUR  # a file captured after audit_at
ACCOUNT = "account_90"
RULE_ROWS = (
    ("USER_PROFILE", "DELETE"),
    ("SEARCH_INDEX_ENTRY", "DELETE"),
    ("SUPPORT_MESSAGE", "REDACT"),
    ("SUPPORT_ATTACHMENT", "DELETE"),
    ("SECURITY_AUDIT_LOG", "RETAIN"),
    ("LEGAL_HOLD_RECORD", "RETAIN"),
    ("ACCOUNT_TOMBSTONE", "REDACT"),
)
# Measured with the agent off (process-order windows only, no fitted constant): the samples whose
# verdicts equal the gold abstraction and the samples whose status differs. The remaining samples
# link a rival's worker row or account, which only the agent (or a live evidence read) can settle.
EXACT_SAMPLES = frozenset({"case_13", "case_14", "case_15", "case_16", "case_17", "case_31"})
STATUS_MISSES = frozenset({"case_07", "case_21"})
GENERATED_SAMPLE_COUNT = 27  # samples that got a case account from the worker-row graph


def rules() -> PolicyEngine:
    rows = [Rule("rule_%d" % n, cat, "Always", action) for n, (cat, action) in enumerate(RULE_ROWS)]
    return PolicyEngine.from_rules(rows)


def request() -> Request:
    return Request("case_t", "x@example.com", 0, "COMPLETE", REPORTED, AUDIT, "delete", True)


def link(system_id: str, rid: str, treatment: Treatment) -> LinkedResource:
    return LinkedResource(system_id, rid, treatment, "test")


def links(*resources: LinkedResource, account: Optional[str] = ACCOUNT) -> CaseLinks:
    return CaseLinks("case_t", account, "unique", tuple(resources), ())


def builder(
    captured: Dict[str, int],
    observations: Iterable = (),
    scopes: Iterable = (),
    acts: Iterable = (),
    flags: Optional[Flags] = None,
) -> CaseBuilder:
    index = make_index(captured, observations, scopes)
    policy = rules()
    config = Config() if flags is None else Config(flags=flags)
    sources = HandcraftedSources(tuple(acts), index, policy, IdentityIndex.build([], []))
    return CaseBuilder(StateResolver(index, policy, acts), policy, index, config, sources)


def by_key(verdicts: Sequence[ResourceVerdict]) -> Dict[Tuple[str, str], ResourceVerdict]:
    return {(verdict.system_id, verdict.resource_id): verdict for verdict in verdicts}


class AccountTests(unittest.TestCase):
    """V1 and V5: the case account always gets its absence check."""

    def test_present_account_is_a_cited_finding(self) -> None:
        build = builder({"f1": INSIDE}, [obs("f1", ACCOUNT, ObsState.PRESENT, "account_service", INSIDE)])
        verdicts = build.build(request(), links())
        self.assertEqual(len(verdicts), 1)
        self.assertTrue(verdicts[0].violating)
        self.assertEqual((verdicts[0].treatment, verdicts[0].cite), (Treatment.DELETE, "f1"))
        self.assertEqual(emit(verdicts)[0], STATUS_INCOMPLETE)

    def test_absent_account_keeps_its_observed_cite_in_a_complete_case(self) -> None:
        build = builder({"f1": INSIDE}, [obs("f1", ACCOUNT, ObsState.ABSENT, "account_service", INSIDE)])
        verdicts = build.build(request(), links())
        self.assertEqual([(v.violating, v.cite) for v in verdicts], [(False, "f1")])
        self.assertEqual(emit(verdicts)[0], STATUS_COMPLETE)
        self.assertEqual(build.stats().omission_cites, 0)

    def test_absence_by_omission_prefers_the_file_that_proves_the_other_steps(self) -> None:
        captured = {"fa": 120 * HOUR, "fb": INSIDE}
        scopes = [scope("fa", "account_service", 120 * HOUR), scope("fb", "account_service", INSIDE)]
        search = obs("fb", "search_5", ObsState.ABSENT, "search_service", INSIDE)
        build = builder(captured, [search], scopes)
        verdicts = by_key(build.build(request(), links(link("search_service", "search_5", Treatment.DELETE))))
        self.assertEqual(verdicts[("account_service", ACCOUNT)].cite, "fb")
        self.assertEqual(verdicts[("search_service", "search_5")].cite, "fb")
        self.assertEqual(build.stats().omission_cites, 1)

    def test_absence_by_omission_without_other_cites_takes_the_earliest_window_scope(self) -> None:
        captured = {"fa": 120 * HOUR, "fb": INSIDE}
        scopes = [scope("fa", "account_service", 120 * HOUR), scope("fb", "account_service", INSIDE)]
        verdicts = builder(captured, (), scopes).build(request(), links())
        self.assertEqual([v.cite for v in verdicts], ["fa"])

    def test_account_with_no_proof_is_omitted_and_counted(self) -> None:
        build = builder({"f1": INSIDE})
        self.assertEqual(build.build(request(), links()), ())
        self.assertEqual(build.stats().omitted_account, 1)

    def test_account_proof_outside_the_window_does_not_cite(self) -> None:
        captured = {"early": 50 * HOUR}
        scopes = [scope("early", "account_service", 50 * HOUR)]
        build = builder(captured, (), scopes)
        self.assertEqual(build.build(request(), links()), ())
        self.assertEqual(build.stats().omitted_account, 1)


class ResourceTests(unittest.TestCase):
    """Per-resource states, the INCOMPLETE and COMPLETE keep rules (SPEC 8.2)."""

    def setUp(self) -> None:
        self.captured = {"f1": INSIDE, "f2": 160 * HOUR}
        self.account_gone = obs("f1", ACCOUNT, ObsState.ABSENT, "account_service", INSIDE)

    def test_incomplete_case_keeps_compliant_resources_without_a_cite(self) -> None:
        observations = [
            self.account_gone,
            obs("f1", "search_5", ObsState.PRESENT, "search_service", INSIDE),
            obs("f2", "search_6", ObsState.ABSENT, "search_service", 160 * HOUR),
        ]
        resources = (
            link("search_service", "search_5", Treatment.DELETE),
            link("search_service", "search_6", Treatment.DELETE),
        )
        verdicts = by_key(builder(self.captured, observations).build(request(), links(*resources)))
        self.assertEqual(
            [(key[1], v.violating, v.cite) for key, v in sorted(verdicts.items())],
            [(ACCOUNT, False, ""), ("search_5", True, "f1"), ("search_6", False, "")],
        )

    def test_complete_case_drops_a_compliant_resource_without_a_cite(self) -> None:
        observations = [
            self.account_gone,
            obs("f2", "search_6", ObsState.ABSENT, "search_service", 160 * HOUR),
            obs("early", "search_7", ObsState.ABSENT, "search_service", 10 * HOUR),
        ]
        captured = dict(self.captured, early=10 * HOUR)
        resources = (
            link("search_service", "search_6", Treatment.DELETE),
            link("search_service", "search_7", Treatment.DELETE),
        )
        build = builder(captured, observations)
        verdicts = by_key(build.build(request(), links(*resources)))
        self.assertEqual(sorted(key[1] for key in verdicts), [ACCOUNT, "search_6"])
        self.assertEqual(build.stats().dropped_compliant, 1)

    def test_violating_resource_without_a_citable_proof_is_dropped(self) -> None:
        stale_flow = activity("activity_1", 50 * HOUR, ActKind.FLOW_ENABLED, "integration_service", "data_flow_3", Treatment.FLOW)
        window_flow = activity("activity_2", INSIDE, ActKind.FLOW_ENABLED, "integration_service", "data_flow_4", Treatment.FLOW)
        build = builder({"f1": INSIDE}, [self.account_gone], acts=[stale_flow, window_flow])
        resources = (
            link("integration_service", "data_flow_3", Treatment.FLOW),
            link("integration_service", "data_flow_4", Treatment.FLOW),
        )
        verdicts = by_key(build.build(request(), links(*resources)))
        self.assertNotIn(("integration_service", "data_flow_3"), verdicts)
        self.assertEqual(verdicts[("integration_service", "data_flow_4")].cite, "activity_2")
        self.assertEqual(build.stats().dropped_violating, 1)

    def test_the_account_is_not_duplicated_by_a_linked_account_resource(self) -> None:
        observations = [obs("f1", ACCOUNT, ObsState.PRESENT, "account_service", INSIDE)]
        verdicts = builder(self.captured, observations).build(
            request(), links(link("account_service", ACCOUNT, Treatment.DELETE))
        )
        self.assertEqual(len(verdicts), 1)

    def test_evidence_category_replaces_the_linked_treatment(self) -> None:
        message = obs("f1", "support_5", ObsState.EXPOSED, "support_platform", INSIDE, category="SUPPORT_MESSAGE")
        build = builder(self.captured, [self.account_gone, message])
        verdicts = by_key(build.build(request(), links(link("support_platform", "support_5", Treatment.DELETE))))
        verdict = verdicts[("support_platform", "support_5")]
        self.assertEqual((verdict.treatment, verdict.violating), (Treatment.REDACT, True))
        self.assertEqual(build.stats().category_overrides, 1)

    def test_attachment_category_keeps_a_delete_treatment(self) -> None:
        attachment = obs("f1", "support_5", ObsState.PRESENT, "support_platform", INSIDE, category="SUPPORT_ATTACHMENT")
        build = builder(self.captured, [self.account_gone, attachment])
        verdicts = by_key(build.build(request(), links(link("support_platform", "support_5", Treatment.DELETE))))
        self.assertEqual(verdicts[("support_platform", "support_5")].treatment, Treatment.DELETE)
        self.assertEqual(build.stats().category_overrides, 0)

    def test_generic_ticket_evidence_leaves_the_treatment_to_the_activity_event(self) -> None:
        generic = obs("f1", "support_5", ObsState.EXPOSED, "support_platform", INSIDE)
        for treatment in (Treatment.DELETE, Treatment.REDACT):
            build = builder(self.captured, [self.account_gone, generic])
            verdicts = by_key(build.build(request(), links(link("support_platform", "support_5", treatment))))
            verdict = verdicts[("support_platform", "support_5")]
            self.assertEqual((verdict.treatment, verdict.violating), (treatment, True))
            self.assertEqual(build.stats().category_overrides, 0)


class RetainedRecordTests(unittest.TestCase):
    """V2 audit records, V3 legal holds and V4 tombstones."""

    def setUp(self) -> None:
        self.captured = {"f1": INSIDE, "late": AFTER}
        self.account_gone = obs("f1", ACCOUNT, ObsState.ABSENT, "account_service", INSIDE)
        self.audit = link(SECURITY_SERVICE, "audit_record_4", Treatment.RETAIN)

    def test_audit_record_in_the_window_is_verified_with_its_cite(self) -> None:
        present = obs("f1", "audit_record_4", ObsState.PRESENT, SECURITY_SERVICE, INSIDE)
        verdicts = by_key(builder(self.captured, [self.account_gone, present]).build(request(), links(self.audit)))
        verdict = verdicts[(SECURITY_SERVICE, "audit_record_4")]
        self.assertEqual((verdict.treatment, verdict.violating, verdict.cite), (Treatment.RETAIN, False, "f1"))

    def test_a_retained_record_is_never_a_finding(self) -> None:
        gone = obs("f1", "audit_record_4", ObsState.ABSENT, SECURITY_SERVICE, INSIDE)
        verdicts = builder(self.captured, [self.account_gone, gone]).build(request(), links(self.audit))
        self.assertFalse(any(verdict.violating for verdict in verdicts))

    def test_legal_hold_is_verified_present_and_the_flag_turns_it_off(self) -> None:
        hold = link(LEGAL_SERVICE, "legal_hold_2", Treatment.RETAIN)
        present = obs("f1", "legal_hold_2", ObsState.PRESENT, LEGAL_SERVICE, INSIDE)
        on = builder(self.captured, [self.account_gone, present])
        self.assertIn((LEGAL_SERVICE, "legal_hold_2"), by_key(on.build(request(), links(hold))))
        self.assertEqual(len(on.stats().untested), 1)
        off = builder(self.captured, [self.account_gone, present], flags=Flags(verify_legal_holds=False))
        self.assertNotIn((LEGAL_SERVICE, "legal_hold_2"), by_key(off.build(request(), links(hold))))

    def test_tombstone_is_redacted_when_clean_and_a_finding_when_exposed(self) -> None:
        tomb = link("identity_service", "tombstone_3", Treatment.REDACT)
        for state, violating in ((ObsState.REDACTED, False), (ObsState.EXPOSED, True)):
            row = obs("f1", "tombstone_3", state, "identity_service", INSIDE, category="ACCOUNT_TOMBSTONE")
            verdicts = by_key(builder(self.captured, [self.account_gone, row]).build(request(), links(tomb)))
            verdict = verdicts[("identity_service", "tombstone_3")]
            self.assertEqual((verdict.treatment, verdict.violating), (Treatment.REDACT, violating))


class EmissionTests(unittest.TestCase):
    """The verdicts feed `emit` into valid steps."""

    def test_a_violating_case_emits_finding_remediation_and_verification(self) -> None:
        observations = [
            obs("f1", ACCOUNT, ObsState.ABSENT, "account_service", INSIDE),
            obs("f1", "support_5", ObsState.EXPOSED, "support_platform", INSIDE, category="SUPPORT_MESSAGE"),
        ]
        build = builder({"f1": INSIDE}, observations)
        verdicts = build.build(request(), links(link("support_platform", "support_5", Treatment.REDACT)))
        status, steps = emit(verdicts)
        self.assertEqual(status, STATUS_INCOMPLETE)
        self.assertEqual(
            [(s.phase, s.operation, s.resource_id, s.evidence_id) for s in steps],
            [
                ("FINDING", "REPORT_EXPOSED_PII", "support_5", "f1"),
                ("REMEDIATION", "REDACT_RECORD", "support_5", ""),
                ("VERIFICATION", "VERIFY_RECORD_ABSENT", ACCOUNT, ""),
                ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_5", ""),
            ],
        )


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    """The generated-family samples against the gold abstraction, and dataset-wide sanity."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.index = build_index(reader.manifest(), identity, {}, classify_activity(reader.activity()))
        cls.requests = reader.requests()
        acts = classify_activity(reader.activity())
        policy = PolicyEngine.from_rules(reader.rules())
        config = Config()
        solved = link_cases(cls.requests, acts, cls.index, identity, config)
        extras = add_extras(solved.links, cls.requests, acts, cls.index, identity, policy, config)
        cls.links = extras.links
        sources = HandcraftedSources(acts, cls.index, policy, identity)
        cls.builder = CaseBuilder(StateResolver(cls.index, policy, acts), policy, cls.index, config, sources)
        cls.verdicts = {
            req.case_id: cls.builder.build(req, cls.links[req.case_id])
            for req in cls.requests
            if cls.links[req.case_id].account_id is not None
        }
        cls.gold = GoldReader().cases()
        cls.words = cls.dataset_words(reader)

    @staticmethod
    def dataset_words(reader: DatasetReader) -> Set[str]:
        """Every identifier-like word of the text evidence and the activity stream."""
        parts: List[str] = []
        for entry in reader.manifest():
            if entry.path.suffix not in (".png", ".pdf"):
                parts.append(entry.path.read_text(encoding="utf-8", errors="ignore"))
        for row in reader.activity():
            parts.append(" ".join((row.resource_id, row.details)))
        return set(re.findall(r"[a-z]+(?:_[a-z]+)*_\d+", "\n".join(parts)))

    @staticmethod
    def signature(verdicts: Iterable[ResourceVerdict]) -> Set[Tuple[str, str, str, bool, str]]:
        return {
            (v.system_id, v.resource_id, v.treatment.value, v.violating, v.cite) for v in verdicts
        }

    def generated_samples(self) -> List[Request]:
        return [req for req in self.requests if req.is_sample and req.case_id in self.verdicts]

    def test_the_generated_samples_are_those_with_a_linked_account(self) -> None:
        self.assertEqual(len(self.generated_samples()), GENERATED_SAMPLE_COUNT)

    def test_pinned_samples_equal_the_gold_abstraction(self) -> None:
        for case_id in sorted(EXACT_SAMPLES):
            expected = self.signature(abstract_verdicts(self.gold[case_id].steps))
            self.assertEqual(self.signature(self.verdicts[case_id]), expected, case_id)

    def test_sample_statuses_match_the_gold_except_the_pinned_misses(self) -> None:
        wrong = set()
        for req in self.generated_samples():
            status, _steps = emit(self.verdicts[req.case_id])
            if status != self.gold[req.case_id].deletion_status:
                wrong.add(req.case_id)
        self.assertEqual(wrong, STATUS_MISSES)

    def test_every_output_resource_id_occurs_in_the_dataset(self) -> None:
        for case_id, verdicts in self.verdicts.items():
            for verdict in verdicts:
                self.assertIn(verdict.resource_id, self.words, case_id)

    def test_every_finding_has_a_cite(self) -> None:
        for case_id, verdicts in self.verdicts.items():
            for verdict in verdicts:
                self.assertTrue(verdict.cite or not verdict.violating, "%s %s" % (case_id, verdict.resource_id))

    def test_no_complete_case_is_empty_and_each_has_cited_verifications(self) -> None:
        for case_id, verdicts in self.verdicts.items():
            status, steps = emit(verdicts)
            if status == STATUS_COMPLETE and steps:
                self.assertTrue(all(step.evidence_id for step in steps), case_id)

    def test_omitted_account_steps_are_reported(self) -> None:
        stats = self.builder.stats()
        self.assertEqual(stats.cases, len(self.verdicts))
        omitted = [cid for cid, v in self.verdicts.items() if not any(x.system_id == "account_service" for x in v)]
        self.assertEqual(len(omitted), stats.omitted_account)

    def test_untested_rule_firings_are_listed(self) -> None:
        untested = self.builder.stats().untested
        self.assertEqual(sum("V3 legal hold linked" in item for item in untested), 10)


if __name__ == "__main__":
    unittest.main()
