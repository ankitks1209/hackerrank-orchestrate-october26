"""Tests for the hand-crafted and media families (SPEC L12, Q1, Q2, Q7, T5).

The synthetic classes build one case from a hand-made EvidenceIndex with fictional ids and
plain integer times, one rule at a time. The real-dataset class runs the eight hand-crafted
samples against the tests-only gold abstraction and checks the evaluation family
structurally: no case id or resource id of the evaluation set appears here, and the media
files are not read, so their LINK-row resources degrade and the diagnostics say so.
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ghostaudit.activity import classify_activity
from ghostaudit.casebuilder import CaseBuilder
from ghostaudit.config import HOUR, MINUTE, REPO_ROOT, Config
from ghostaudit.dataset import DatasetReader, Rule
from ghostaudit.emit import emit
from ghostaudit.evidence.index import EvidenceIndex, build_index
from ghostaudit.handcrafted import (
    AccountChoice,
    BASIS_CATALOG_LINK,
    BASIS_EVIDENCE,
    BASIS_NONE,
    BASIS_POINTER,
    BASIS_TARGET_ROW,
    HandcraftedSources,
)
from ghostaudit.identity import IdentityIndex
from ghostaudit.intent_lexicon import classify_text
from ghostaudit.keys import email_key, user_key
from ghostaudit.link_solver import link_cases
from ghostaudit.linking import add_extras
from ghostaudit.model import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    ActKind,
    CaseLinks,
    ClassifiedActivity,
    LinkedResource,
    MediaFacts,
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

ACCOUNT_SERVICE = "account_service"
EXPORT_SERVICE = "export_service"
OBJECT_STORAGE = "object_storage"
SECURITY_SERVICE = "security_service"
SUPPORT_PLATFORM = "support_platform"
SEARCH_SERVICE = "search_service"
SUBJECT = "user_91"
EMAIL = "pat@example.com"
OTHER_EMAIL = "sam@example.com"
OTHER = "user_92"
REPORTED = 100 * HOUR
AUDIT = 200 * HOUR
INSIDE = 150 * HOUR  # a file captured inside the case window
BEFORE = 50 * HOUR  # a file captured before the report
RULE_ROWS = (
    ("USER_PROFILE", "DELETE"),
    ("SEARCH_INDEX_ENTRY", "DELETE"),
    ("SUPPORT_ATTACHMENT", "DELETE"),
    ("USER_EXPORT", "DELETE"),
    ("SECURITY_AUDIT_LOG", "RETAIN"),
)
AUDIT_RECORD = LinkedResource(SECURITY_SERVICE, "audit_record_9", Treatment.RETAIN, "audit_id")
# Samples that no deletion-worker account row reaches (measured, agent off). case_01, 04, 06, 07 and
# 10 once belonged here; with process-order windows alone a rival's account row also falls in their
# period, so they take the generated path; case_26 joins them because its account row went to a rival.
HANDCRAFTED_SAMPLES = ("case_02", "case_05", "case_08", "case_22", "case_26")
ACCOUNT_STEP_MISSING = frozenset({"case_02", "case_08", "case_22"})  # no account id is guessed any more
# case_26 also loses its account row to a case that the evidence cannot yet separate from it at either audit time.


def policy() -> PolicyEngine:
    rows = [Rule("rule_%d" % n, cat, "Always", action) for n, (cat, action) in enumerate(RULE_ROWS)]
    return PolicyEngine.from_rules(rows)


def identity() -> IdentityIndex:
    return IdentityIndex(
        {
            SUBJECT: frozenset({email_key(EMAIL), user_key(SUBJECT)}),
            OTHER: frozenset({email_key(OTHER_EMAIL), user_key(OTHER)}),
        }
    )


def request(
    case_id: str = "case_t", reported_at: int = REPORTED, audit_at: int = AUDIT, email: str = EMAIL
) -> Request:
    return Request(case_id, email, 0, "COMPLETE", reported_at, audit_at, "delete", True)


def bare_links(case_id: str = "case_t", *resources: LinkedResource) -> CaseLinks:
    return CaseLinks(case_id, None, "none", tuple(resources), ())


def row(
    activity_id: str, t: int, kind: ActKind, system_id: str, rid: str, user: Optional[str] = None,
    treatment: Optional[Treatment] = None,
) -> ClassifiedActivity:
    base = activity(activity_id, t, kind, system_id, rid, treatment)
    return replace(base, linked_user=user)


def link_row(
    activity_id: str, t: int, system_id: str, rid: str, user: str = SUBJECT
) -> ClassifiedActivity:
    return row(activity_id, t, ActKind.LINK, system_id, rid, user)


def target_row(
    activity_id: str, t: int, system_id: str, rid: str, treatment: Optional[Treatment] = None
) -> ClassifiedActivity:
    return row(activity_id, t, ActKind.TARGET_RESOURCE, system_id, rid, None, treatment)


def index_with(
    captured: Dict[str, int],
    observations: Iterable = (),
    scopes: Iterable = (),
    users: Optional[Dict[str, Sequence[str]]] = None,
    pointers: Optional[Dict[str, Sequence[str]]] = None,
    mentions: Optional[Dict[str, Sequence[str]]] = None,
) -> EvidenceIndex:
    """make_index plus the lookups of the hand-crafted rules; `users` maps a user to its rids."""
    users = users or {}
    owners: Dict[str, List[str]] = {}
    for user, rids in users.items():
        for rid in rids:
            owners.setdefault(rid, []).append(user)
    return replace(
        make_index(captured, observations, scopes),
        rids_by_user={user: tuple(rids) for user, rids in users.items()},
        users_by_rid={rid: tuple(sorted(found)) for rid, found in owners.items()},
        pointers={rid: tuple(found) for rid, found in (pointers or {}).items()},
        mentions={rid: tuple(found) for rid, found in (mentions or {}).items()},
    )


def sources(index: EvidenceIndex, acts: Iterable[ClassifiedActivity] = ()) -> HandcraftedSources:
    return HandcraftedSources(tuple(acts), index, policy(), identity())


def builder(index: EvidenceIndex, acts: Iterable[ClassifiedActivity] = ()) -> CaseBuilder:
    acts = tuple(acts)
    pol = policy()
    handcrafted = HandcraftedSources(acts, index, pol, identity())
    return CaseBuilder(StateResolver(index, pol, acts), pol, index, Config(), handcrafted)


def by_key(verdicts: Sequence[ResourceVerdict]) -> Dict[Tuple[str, str], ResourceVerdict]:
    return {(verdict.system_id, verdict.resource_id): verdict for verdict in verdicts}


class AccountRuleTests(unittest.TestCase):
    """SPEC L12: the case account comes from the first unambiguous rule."""

    def choose(
        self,
        index: EvidenceIndex,
        acts: Iterable[ClassifiedActivity] = (),
        subject: str = SUBJECT,
        resources: Sequence[LinkedResource] = (),
    ) -> AccountChoice:
        return sources(index, acts).account(request(), subject, resources)

    def test_evidence_account_wins_over_an_activity_pointer(self) -> None:
        index = index_with({"f1": INSIDE}, users={SUBJECT: ["account_501"]})
        acts = [target_row("t1", REPORTED + MINUTE, ACCOUNT_SERVICE, "account_502")]
        choice = self.choose(index, acts)
        self.assertEqual((choice.account_id, choice.basis), ("account_501", BASIS_EVIDENCE))

    def test_several_evidence_accounts_take_the_one_a_window_file_names(self) -> None:
        index = index_with(
            {"early": BEFORE, "inside": INSIDE},
            users={SUBJECT: ["account_501", "account_502"]},
            mentions={"account_501": ["early"], "account_502": ["inside"]},
        )
        self.assertEqual(self.choose(index).account_id, "account_502")

    def test_one_subject_with_two_cases_gets_each_cases_own_account(self) -> None:
        index = index_with(
            {"older": INSIDE, "newer": AUDIT + 150 * HOUR},
            users={SUBJECT: ["account_501", "account_502"]},
            mentions={"account_501": ["older"], "account_502": ["newer"]},
        )
        src = sources(index)
        later = request("case_b", reported_at=AUDIT + 100 * HOUR, audit_at=AUDIT + 200 * HOUR)
        self.assertEqual(src.account(request(), SUBJECT, ()).account_id, "account_501")
        self.assertEqual(src.account(later, SUBJECT, ()).account_id, "account_502")

    def test_several_evidence_accounts_outside_the_window_are_ambiguous(self) -> None:
        index = index_with(
            {"early": BEFORE}, users={SUBJECT: ["account_501", "account_502"]},
            mentions={"account_501": ["early"], "account_502": ["early"]},
        )
        choice = self.choose(index)
        self.assertEqual((choice.account_id, choice.basis), (None, BASIS_NONE))
        self.assertIn("account_501", choice.note)

    def test_account_t_row_inside_the_case_period_is_a_pointer(self) -> None:
        acts = [target_row("t1", REPORTED + 5 * MINUTE, ACCOUNT_SERVICE, "account_501")]
        choice = self.choose(index_with({"f1": INSIDE}), acts)
        self.assertEqual((choice.account_id, choice.basis), ("account_501", BASIS_POINTER))

    def test_account_t_row_outside_the_case_period_is_ignored(self) -> None:
        acts = [target_row("t1", AUDIT + HOUR, ACCOUNT_SERVICE, "account_501")]
        choice = self.choose(index_with({"f1": INSIDE}), acts)
        self.assertEqual(choice.basis, BASIS_NONE)

    def test_account_t_row_owned_by_another_subject_is_ignored(self) -> None:
        index = index_with({"f1": INSIDE}, users={OTHER: ["account_501"]})
        acts = [target_row("t1", REPORTED + MINUTE, ACCOUNT_SERVICE, "account_501")]
        choice = self.choose(index, acts)
        self.assertEqual(choice.basis, BASIS_NONE)

    def test_link_row_account_is_a_pointer_only_for_its_user_and_window(self) -> None:
        acts = [
            link_row("l1", INSIDE, ACCOUNT_SERVICE, "account_501"),
            link_row("l2", INSIDE, ACCOUNT_SERVICE, "account_502", user=OTHER),
            link_row("l3", BEFORE, ACCOUNT_SERVICE, "account_503"),
        ]
        choice = self.choose(index_with({"f1": INSIDE}), acts)
        self.assertEqual((choice.account_id, choice.basis), ("account_501", BASIS_POINTER))

    def test_search_document_source_is_a_pointer(self) -> None:
        index = index_with({"f1": INSIDE}, pointers={"search_77": ["account_501"]})
        found = (LinkedResource(SEARCH_SERVICE, "search_77", Treatment.DELETE, "test"),)
        choice = self.choose(index, resources=found)
        self.assertEqual((choice.account_id, choice.basis), ("account_501", BASIS_POINTER))

    def test_two_different_pointers_are_ambiguous(self) -> None:
        acts = [
            target_row("t1", REPORTED, ACCOUNT_SERVICE, "account_501"),
            link_row("l1", INSIDE, ACCOUNT_SERVICE, "account_502"),
        ]
        choice = self.choose(index_with({"f1": INSIDE}), acts)
        self.assertEqual(choice.basis, BASIS_NONE)
        self.assertIn("ambiguous", choice.note)

    def test_no_account_is_guessed_from_the_user_number(self) -> None:
        for subject in ("user_03", "user_10"):
            choice = self.choose(index_with({"f1": INSIDE}), subject=subject)
            self.assertEqual((choice.account_id, choice.basis), (None, BASIS_NONE))

    def test_an_unknown_subject_has_no_account(self) -> None:
        choice = sources(index_with({"f1": INSIDE})).account(request(), None, ())
        self.assertEqual((choice.account_id, choice.basis), (None, BASIS_NONE))


class ResourceSourceTests(unittest.TestCase):
    """T rows and LINK rows name the resources of a case, scoped by its own window (T5)."""

    def test_target_row_resource_takes_its_event_treatment(self) -> None:
        acts = [target_row("t1", REPORTED + MINUTE, SEARCH_SERVICE, "search_77", Treatment.DELETE)]
        found = sources(index_with({"f1": INSIDE}), acts).resources(request(), SUBJECT)
        self.assertEqual(
            [(r.system_id, r.resource_id, r.treatment, r.basis) for r in found],
            [(SEARCH_SERVICE, "search_77", Treatment.DELETE, BASIS_TARGET_ROW)],
        )

    def test_target_row_of_another_owner_or_after_the_audit_is_not_linked(self) -> None:
        index = index_with({"f1": INSIDE}, users={OTHER: ["search_78"]})
        acts = [
            target_row("t1", REPORTED + MINUTE, SEARCH_SERVICE, "search_78", Treatment.DELETE),
            target_row("t2", AUDIT + HOUR, SEARCH_SERVICE, "search_79", Treatment.DELETE),
        ]
        self.assertEqual(sources(index, acts).resources(request(), SUBJECT), ())

    def test_link_row_resource_takes_the_system_default_treatment(self) -> None:
        acts = [
            link_row("l1", INSIDE, OBJECT_STORAGE, "object_55"),
            link_row("l2", INSIDE, EXPORT_SERVICE, "export_56"),
        ]
        found = sources(index_with({"f1": INSIDE}), acts).resources(request(), SUBJECT)
        self.assertEqual(
            [(r.resource_id, r.treatment, r.basis) for r in found],
            [
                ("object_55", Treatment.DELETE, BASIS_CATALOG_LINK),
                ("export_56", Treatment.DELETE, BASIS_CATALOG_LINK),
            ],
        )

    def test_one_user_with_two_cases_keeps_each_cases_own_link_rows(self) -> None:
        early = request("case_a", reported_at=REPORTED, audit_at=AUDIT)
        late = request("case_b", reported_at=AUDIT + 100 * HOUR, audit_at=AUDIT + 200 * HOUR)
        acts = [
            link_row("l1", INSIDE, EXPORT_SERVICE, "export_61"),
            link_row("l2", AUDIT + 150 * HOUR, EXPORT_SERVICE, "export_62"),
        ]
        src = sources(index_with({"f1": INSIDE}), acts)
        self.assertEqual([r.resource_id for r in src.resources(early, SUBJECT)], ["export_61"])
        self.assertEqual([r.resource_id for r in src.resources(late, SUBJECT)], ["export_62"])

    def test_link_row_after_audit_or_of_another_user_is_not_linked(self) -> None:
        acts = [
            link_row("l1", AUDIT + HOUR, EXPORT_SERVICE, "export_61"),
            link_row("l2", INSIDE, EXPORT_SERVICE, "export_62", user=OTHER),
        ]
        found = sources(index_with({"f1": INSIDE}), acts).resources(request(), SUBJECT)
        self.assertEqual(found, ())

    def test_account_rows_are_pointers_not_resources(self) -> None:
        acts = [link_row("l1", INSIDE, ACCOUNT_SERVICE, "account_501")]
        found = sources(index_with({"f1": INSIDE}), acts).resources(request(), SUBJECT)
        self.assertEqual(found, ())

    def test_a_subject_unknown_to_identity_gets_no_resources(self) -> None:
        acts = [link_row("l1", INSIDE, EXPORT_SERVICE, "export_61")]
        self.assertEqual(sources(index_with({"f1": INSIDE}), acts).resources(request(), None), ())


class HandcraftedBuildTests(unittest.TestCase):
    """The verdicts of a case without an A-row account."""

    def test_observed_link_resource_is_a_finding_and_no_account_is_guessed(self) -> None:
        index = index_with(
            {"f1": INSIDE},
            [obs("f1", "export_61", ObsState.PRESENT, EXPORT_SERVICE, INSIDE)],
        )
        acts = [link_row("l1", INSIDE, EXPORT_SERVICE, "export_61", user="user_03")]
        email = "kim@example.com"
        ident = IdentityIndex({"user_03": frozenset({email_key(email), user_key("user_03")})})
        pol = policy()
        handcrafted = HandcraftedSources(acts, index, pol, ident)
        build = CaseBuilder(StateResolver(index, pol, acts), pol, index, Config(), handcrafted)
        verdicts = build.build(request(email=email), bare_links())
        status, steps = emit(verdicts)
        self.assertEqual(status, STATUS_INCOMPLETE)
        self.assertEqual(
            [(s.phase, s.system_id, s.resource_id, s.evidence_id) for s in steps],
            [
                ("FINDING", EXPORT_SERVICE, "export_61", "f1"),
                ("REMEDIATION", EXPORT_SERVICE, "export_61", ""),
                ("VERIFICATION", EXPORT_SERVICE, "export_61", ""),
            ],
        )
        stats = build.stats()
        self.assertEqual(stats.handcrafted_cases, 1)
        self.assertEqual(stats.account_basis, ((BASIS_NONE, 1),))

    def test_complete_case_cites_the_account_absence_by_omission(self) -> None:
        index = index_with(
            {"f1": INSIDE},
            scopes=[scope("f1", ACCOUNT_SERVICE, INSIDE)],
            users={SUBJECT: ["account_501"]},
        )
        verdicts = builder(index).build(request(), bare_links())
        self.assertEqual(
            [(v.resource_id, v.cite, v.basis) for v in verdicts], [("account_501", "f1", "account")]
        )
        self.assertEqual(emit(verdicts)[0], STATUS_COMPLETE)

    def test_link_resource_without_evidence_is_dropped_and_listed(self) -> None:
        index = index_with({"f1": INSIDE}, users={SUBJECT: ["account_501"]})
        acts = [link_row("l1", INSIDE, OBJECT_STORAGE, "object_55")]
        build = builder(index, acts)
        verdicts = build.build(request(), bare_links())
        self.assertNotIn(OBJECT_STORAGE, {v.system_id for v in verdicts})
        notes = build.stats().handcrafted_notes
        self.assertEqual(len(notes), 1)
        self.assertIn("object_55", notes[0])
        self.assertIn("media facts missing", notes[0])

    def test_absent_record_to_be_redacted_is_dropped_not_reported_exposed(self) -> None:
        """SPEC 8.2: an absence proof backs neither EXPOSED_PII nor a REDACTED check."""
        index = index_with({"f1": INSIDE}, scopes=[scope("f1", SUPPORT_PLATFORM, INSIDE)])
        message = LinkedResource(SUPPORT_PLATFORM, "support_77", Treatment.REDACT, BASIS_CATALOG_LINK)
        build = builder(index)
        verdicts = build.build(request(), bare_links("case_t", message))
        self.assertEqual(verdicts, ())
        stats = build.stats()
        self.assertEqual((stats.dropped_absent, stats.dropped_violating), (1, 0))
        self.assertIn("support_77 dropped, ABSENT via scope under REDACT", stats.handcrafted_notes[0])

    def test_exposed_record_to_be_redacted_is_still_a_finding(self) -> None:
        shown = obs("f1", "support_77", ObsState.EXPOSED, SUPPORT_PLATFORM, INSIDE)
        index = index_with({"f1": INSIDE}, [shown], scopes=[scope("f1", SUPPORT_PLATFORM, INSIDE)])
        message = LinkedResource(SUPPORT_PLATFORM, "support_77", Treatment.REDACT, BASIS_CATALOG_LINK)
        verdicts = builder(index).build(request(), bare_links("case_t", message))
        self.assertEqual([(v.resource_id, v.violating, v.cite) for v in verdicts], [("support_77", True, "f1")])

    def test_link_resource_without_window_proof_in_a_complete_case_is_listed(self) -> None:
        index = index_with({"early": BEFORE}, scopes=[scope("early", EXPORT_SERVICE, BEFORE)])
        export = LinkedResource(EXPORT_SERVICE, "export_61", Treatment.DELETE, BASIS_CATALOG_LINK)
        build = builder(index)
        verdicts = build.build(request(), bare_links("case_t", export))
        self.assertEqual(verdicts, ())
        notes = build.stats().handcrafted_notes
        self.assertEqual(len(notes), 1)
        self.assertIn("export_61 has no step, ABSENT via scope as DELETE with no in-window proof", notes[0])

    def test_a_case_without_account_has_resource_steps_and_no_account_step(self) -> None:
        shown = obs("f1", "export_61", ObsState.PRESENT, EXPORT_SERVICE, INSIDE)
        index = index_with({"f1": INSIDE}, [shown])
        acts = [link_row("l1", INSIDE, EXPORT_SERVICE, "export_61")]
        verdicts = builder(index, acts).build(request(), bare_links())
        self.assertEqual([(v.system_id, v.violating) for v in verdicts], [(EXPORT_SERVICE, True)])
        self.assertEqual(emit(verdicts)[0], STATUS_INCOMPLETE)

    def test_a_pre_request_observation_is_not_a_citable_finding(self) -> None:
        shown = obs("early", "export_61", ObsState.PRESENT, EXPORT_SERVICE, BEFORE)
        index = index_with({"early": BEFORE}, [shown])
        acts = [link_row("l1", INSIDE, EXPORT_SERVICE, "export_61")]
        verdicts = builder(index, acts).build(request(), bare_links())
        self.assertEqual(verdicts, ())

    def test_audit_record_is_never_proved_by_an_absence_scope(self) -> None:
        index = index_with(
            {"f1": INSIDE},
            scopes=[scope("f1", SECURITY_SERVICE, INSIDE)],
            users={SUBJECT: ["account_501"]},
        )
        verdicts = by_key(builder(index).build(request(), bare_links("case_t", AUDIT_RECORD)))
        self.assertNotIn((SECURITY_SERVICE, "audit_record_9"), verdicts)

    def test_audit_record_in_an_incomplete_case_is_verified_uncited(self) -> None:
        index = index_with(
            {"f1": INSIDE},
            [obs("f1", "account_501", ObsState.PRESENT, ACCOUNT_SERVICE, INSIDE)],
            scopes=[scope("f1", SECURITY_SERVICE, INSIDE)],
            users={SUBJECT: ["account_501"]},
        )
        verdicts = by_key(builder(index).build(request(), bare_links("case_t", AUDIT_RECORD)))
        self.assertEqual(verdicts[(SECURITY_SERVICE, "audit_record_9")].cite, "")
        self.assertTrue(verdicts[(ACCOUNT_SERVICE, "account_501")].violating)

    def test_build_dispatches_on_the_account_row(self) -> None:
        present = obs("f1", "account_9", ObsState.PRESENT, ACCOUNT_SERVICE, INSIDE)
        index = index_with({"f1": INSIDE}, [present])
        with_account = CaseLinks("case_t", "account_9", "unique", (), ())
        verdicts = builder(index).build(request(), with_account)
        self.assertEqual([v.basis for v in verdicts], ["account"])
        self.assertEqual(builder(index).stats().handcrafted_cases, 0)


@needs_dataset
class RealDatasetTests(unittest.TestCase):
    """The eight hand-crafted samples against the gold; the evaluation family by structure."""

    @classmethod
    def setUpClass(cls) -> None:
        reader = DatasetReader(REPO_ROOT / "dataset")
        cls.identity = IdentityIndex.build(reader.identities(), reader.audit_log())
        cls.facts = cls.sample_pdf_facts({entry.file_id: entry for entry in reader.manifest()})
        cls.index = build_index(reader.manifest(), cls.identity, cls.facts, classify_activity(reader.activity()))
        cls.requests = reader.requests()
        cls.acts = classify_activity(reader.activity())
        policy_engine = PolicyEngine.from_rules(reader.rules())
        config = Config()
        solved = link_cases(cls.requests, cls.acts, cls.index, cls.identity, config)
        extras = add_extras(
            solved.links, cls.requests, cls.acts, cls.index, cls.identity, policy_engine, config
        )
        cls.links = extras.links
        cls.sources = HandcraftedSources(cls.acts, cls.index, policy_engine, cls.identity)
        resolver = StateResolver(cls.index, policy_engine, cls.acts)
        cls.builder = CaseBuilder(resolver, policy_engine, cls.index, config, cls.sources)
        cls.verdicts = {
            req.case_id: cls.builder.build(req, cls.links[req.case_id])
            for req in cls.requests
            if cls.links[req.case_id].account_id is None and cls.authorizes_deletion(req)
        }
        cls.gold = GoldReader().cases()

    @staticmethod
    def sample_pdf_facts(manifest: Dict[str, object]) -> Dict[str, MediaFacts]:
        """The one sample PDF a hand-crafted sample cites, transcribed from the document itself.

        The support attachment `delivery_correction_attachment.pdf` shows the record
        `CS-4827 / support_001`, the customer's name, email and phone, and the properties of
        an uploaded file. The extraction layer returns the same record from the PDF.
        """
        name = "delivery_correction_attachment.pdf"
        entry = next(e for e in manifest.values() if e.path.name == name)
        record = {
            "display_id": "CS-4827 / support_001",
            "resource_hint": "support_001",
            "system_hint": "Northstar Shop",
            "category": "SUPPORT_ATTACHMENT",
            "emails": ["priya.raman@gmail.com"],
            "phones": ["+91 98765 73142"],
            "user_refs": [],
            "names": ["Priya Raman"],
            "state_facts": {"record_shown": True},
            "dates": ["18 Jun 2026"],
        }
        return {entry.file_id: MediaFacts(entry.file_id, (record,))}

    @staticmethod
    def authorizes_deletion(req: Request) -> bool:
        """Only deletion requests reach the builder (SPEC 8.1); the lexicon stands in for the model."""
        return classify_text(req.text).deletion

    def samples(self) -> List[Request]:
        return [req for req in self.requests if req.is_sample and req.case_id in self.verdicts]

    @staticmethod
    def signature(verdicts: Iterable[ResourceVerdict]):
        return {
            (v.system_id, v.resource_id, v.treatment.value, v.violating, v.cite) for v in verdicts
        }

    def test_the_handcrafted_samples_are_those_without_a_worker_account_row(self) -> None:
        self.assertEqual(tuple(req.case_id for req in self.samples()), HANDCRAFTED_SAMPLES)

    def test_sample_statuses_equal_the_gold(self) -> None:
        for req in self.samples():
            status, _steps = emit(self.verdicts[req.case_id])
            self.assertEqual(status, self.gold[req.case_id].deletion_status, req.case_id)

    def test_only_the_guessed_account_step_is_missing_from_the_sample_verdicts(self) -> None:
        for req in self.samples():
            if req.case_id == "case_26":
                continue  # its account row and one more resource went to a rival, see above
            expected = self.signature(abstract_verdicts(self.gold[req.case_id].steps))
            missing = expected - self.signature(self.verdicts[req.case_id])
            accounts = {item for item in missing if item[0] == ACCOUNT_SERVICE}
            if req.case_id in ACCOUNT_STEP_MISSING:
                self.assertTrue(accounts, req.case_id)
            self.assertEqual(missing, accounts, req.case_id)

    def test_account_basis_counts_cover_every_handcrafted_case(self) -> None:
        stats = self.builder.stats()
        counted = sum(count for _basis, count in stats.account_basis)
        self.assertEqual(counted, stats.handcrafted_cases)
        self.assertEqual(stats.handcrafted_cases, len(self.verdicts))
        known = {BASIS_EVIDENCE, BASIS_POINTER, BASIS_NONE}
        self.assertTrue(set(dict(stats.account_basis)) <= known)

    def test_a_sample_never_takes_another_cases_link_rows(self) -> None:
        """The subject's LINK rows outside the sample's window are not its resources (T5)."""
        for req in self.samples():
            subject = self.identity.resolve(req.email)
            elsewhere = {
                act.resource_id
                for act in self.acts
                if act.kind is ActKind.LINK
                and act.linked_user == subject
                and not req.reported_at <= act.t <= req.audit_at
            }
            built = {v.resource_id for v in self.verdicts[req.case_id]}
            self.assertFalse(elsewhere & built, req.case_id)

    def test_link_row_resources_without_media_facts_are_reported_not_invented(self) -> None:
        notes = self.builder.stats().handcrafted_notes
        self.assertTrue(any("media facts missing" in note for note in notes))
        for verdicts in self.verdicts.values():
            for verdict in verdicts:
                if verdict.basis == BASIS_CATALOG_LINK:
                    self.assertNotIn("unobserved", verdict.reason)

    def test_every_cite_is_a_window_file(self) -> None:
        entries = self.index.entries
        for req in self.requests:
            for verdict in self.verdicts.get(req.case_id, ()):
                if verdict.cite and verdict.cite in entries:
                    self.assertTrue(
                        req.reported_at <= entries[verdict.cite].captured_at <= req.audit_at,
                        "%s cites %s" % (req.case_id, verdict.cite),
                    )

    def test_building_twice_gives_the_same_verdicts(self) -> None:
        req = self.samples()[0]
        again = self.builder.build(req, self.links[req.case_id])
        self.assertEqual(again, self.verdicts[req.case_id])


if __name__ == "__main__":
    unittest.main()
