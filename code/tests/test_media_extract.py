"""Tests for ghostaudit.llm.media_extract (SPEC F10, N1, N7).

A fake LLM returns canned JSON; no test calls a model. The canned answers are the
`FILES` transcriptions of test_media_mapping, so the whole path (request, reply,
validation, `map_facts`) is checked against the SPEC F10 targets. `CommittedCacheTests`
replays the committed cache (`--llm cache`) and checks the same targets on the real
model output; it is skipped until the live cache fill has been committed.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

from ghostaudit.activity import classify_activity
from ghostaudit.config import MEDIA_MAX_TOKENS, Config
from ghostaudit.dataset import DatasetReader
from ghostaudit.evidence.media import STATE_RULES, map_facts
from ghostaudit.llm import media_extract
from ghostaudit.llm.cache import CachingClient, DiskCache
from ghostaudit.llm.client import (
    LLMBadOutput,
    LLMError,
    LLMRequest,
    LLMResponse,
    NullClient,
    build_params,
)
from ghostaudit.llm.media_extract import (
    FACT_CATEGORIES,
    MEDIA_CATEGORIES,
    MEDIA_SCHEMA,
    PROMPT_VERSION,
    RECORD_FIELDS,
    STATE_FACT_NAMES,
    ExtractionInvalid,
    extract_media_facts,
    load_prompt,
    parse_records,
)
from ghostaudit.llm.usage import UsageMeter
from ghostaudit.model import ActKind, ObsState
from tests.test_media_mapping import FILES, TARGETS
from tests.dataset_guard import needs_dataset

MODEL = "claude-opus-5-5"
FILE_COUNT = 15
LINK_FILE_COUNT = 12
SAMPLING_PARAMS = ("temperature", "top_p", "top_k")

Reply = Union[str, LLMError]


def canonical(records: Sequence[Dict[str, Any]]) -> str:
    """Reply text for fixture records: every schema key present, as the model returns them."""
    full = [
        {**{"system_hint": "", "names": [], "dates": []}, **record} for record in records
    ]
    return json.dumps({"records": full}, sort_keys=True)


def literal(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The fixture records as an over-literal model reads them: every record that shows a
    direct identifier gets `pii_fields_shown`, every record that shows only a user_N
    reference gets `only_stable_reference_shown`, whatever its category."""
    read = []
    for record in records:
        facts = dict(record["state_facts"])
        if record["emails"] or record["phones"] or record.get("names"):
            facts["pii_fields_shown"] = True
        elif record["user_refs"]:
            facts["only_stable_reference_shown"] = True
        read.append({**record, "state_facts": facts})
    return read


def response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=5, model=MODEL, cached=False)


class FakeLLM:
    """Answers by attachment content: a queue of replies per file; records every request."""

    def __init__(self, replies: Dict[bytes, List[Reply]]) -> None:
        self.replies = {key: list(queue) for key, queue in replies.items()}
        self.requests: List[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        reply = self.replies[request.attachments[0][0]].pop(0)
        if isinstance(reply, LLMError):
            raise reply
        return response(reply)


@needs_dataset
class MediaFixture(unittest.TestCase):
    """Media entries of the real manifest, with the bytes of each file as its key."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = DatasetReader(Config().dataset_dir)
        cls.entries = tuple(
            entry for entry in cls.reader.manifest() if entry.path.suffix in (".png", ".pdf")
        )
        cls.data = {entry.file_id: entry.path.read_bytes() for entry in cls.entries}
        cls.links = tuple(
            act for act in classify_activity(cls.reader.activity()) if act.kind is ActKind.LINK
        )

    def fake_for_all(self, read: Any = list) -> FakeLLM:
        """A fake that answers each file with its fixture records, as `read` transforms them."""
        return FakeLLM(
            {self.data[file_id]: [canonical(read(FILES[file_id]))] for file_id in FILES}
        )

    def mapped_targets(self, llm: Any) -> Dict[str, Any]:
        """(system, resource, state) triples per file after extraction and `map_facts`."""
        return self.map_all(extract_media_facts(self.entries, llm, MODEL))

    def map_all(self, result: Any) -> Dict[str, Any]:
        """(system, resource, state) triples per file of an extraction result."""
        by_file = {entry.file_id: entry for entry in self.entries}
        mapped = {}
        for file_id, facts in result.facts.items():
            output = map_facts(by_file[file_id], facts, self.links)
            mapped[file_id] = {
                (obs.system_id, obs.resource_id, obs.state) for obs in output.observations
            }
        return mapped


class ExtractionTests(MediaFixture):
    def test_manifest_holds_the_fifteen_media_files(self) -> None:
        self.assertEqual(len(self.entries), FILE_COUNT)
        self.assertEqual(set(self.data), set(FILES))

    def test_one_call_per_file_yields_facts_for_each(self) -> None:
        llm = self.fake_for_all()
        result = extract_media_facts(self.entries, llm, MODEL)
        self.assertEqual(len(llm.requests), FILE_COUNT)
        self.assertEqual(set(result.facts), set(FILES))
        self.assertEqual(result.notes, ())
        for file_id, facts in result.facts.items():
            self.assertEqual(facts.file_id, file_id)
            self.assertEqual(len(facts.records), len(FILES[file_id]))

    def test_extracted_facts_map_to_the_spec_targets(self) -> None:
        mapped = self.mapped_targets(self.fake_for_all())
        for file_id, target in TARGETS.items():
            with self.subTest(file_id=file_id):
                self.assertIn(target, mapped[file_id])
        self.assertEqual(mapped["evidence_27"], set())
        self.assertEqual(len(self.links), LINK_FILE_COUNT)

    def test_over_literal_identifier_facts_still_map_to_the_spec_targets(self) -> None:
        # ev04/09/18/23/58/60 (DELETE) stay PRESENT and ev37/ev55 (RETAIN) are not REDACTED.
        mapped = self.mapped_targets(self.fake_for_all(literal))
        for file_id, target in TARGETS.items():
            with self.subTest(file_id=file_id):
                self.assertIn(target, mapped[file_id])

    def test_request_shape(self) -> None:
        llm = self.fake_for_all()
        extract_media_facts(self.entries, llm, MODEL)
        mimes = {
            request.attachments[0][1] for request in llm.requests
        }
        self.assertEqual(mimes, {"image/png", "application/pdf"})
        for request in llm.requests:
            params = build_params(request)
            for name in SAMPLING_PARAMS:
                self.assertNotIn(name, params)
            self.assertEqual(params["output_config"]["effort"], "low")
            self.assertEqual(params["output_config"]["format"]["schema"], MEDIA_SCHEMA)
            self.assertEqual(params["max_tokens"], MEDIA_MAX_TOKENS)
            self.assertEqual(params["model"], MODEL)
            self.assertEqual(request.prompt_version, PROMPT_VERSION)
            self.assertEqual(request.system, load_prompt())
            self.assertEqual(len(request.messages), 1)

    def test_miscategorised_tombstone_is_kept_as_a_shown_record(self) -> None:
        # Read as USER_PROFILE, ev42's only fact is out of scope: it is dropped with a
        # note and implies record_shown, so the observation is PRESENT, not lost.
        misread = [{**FILES["evidence_42"][0], "category": "USER_PROFILE"}]
        llm = FakeLLM({self.data["evidence_42"]: [canonical(misread)]})
        entry = next(e for e in self.entries if e.file_id == "evidence_42")
        result = extract_media_facts([entry], llm, MODEL)
        self.assertEqual(
            result.notes,
            ("evidence_42: records[0]: only_stable_reference_shown dropped, "
             "it does not apply to category 'USER_PROFILE'",),
        )
        mapped = self.map_all(result)
        self.assertEqual(
            mapped["evidence_42"], {("identity_service", "tombstone_17", ObsState.PRESENT)}
        )

    def test_faithful_ev37_reading_yields_only_the_linked_audit_event(self) -> None:
        # The six events repeat one subject filter (user_03); only audit_record_003 has a
        # LINK row, so the five others are tied to nobody and yield no observation.
        mapped = self.mapped_targets(self.fake_for_all())
        self.assertEqual(len(FILES["evidence_37"]), 6)
        self.assertEqual(mapped["evidence_37"], {TARGETS["evidence_37"]})

    def test_media_model_is_the_requested_model(self) -> None:
        llm = self.fake_for_all()
        extract_media_facts(self.entries[:1], llm, "claude-haiku-5-5")
        self.assertEqual(llm.requests[0].model, "claude-haiku-5-5")


class RetryTests(MediaFixture):
    def setUp(self) -> None:
        self.entry = next(e for e in self.entries if e.file_id == "evidence_32")
        self.key = self.data["evidence_32"]
        self.good = canonical(FILES["evidence_32"])

    def run_with(self, replies: List[Reply]) -> Any:
        llm = FakeLLM({self.key: replies})
        return llm, extract_media_facts([self.entry], llm, MODEL)

    def test_schema_violation_is_retried_once_with_the_error_hint(self) -> None:
        llm, result = self.run_with(['{"records": [{"display_id": "x"}]}', self.good])
        self.assertEqual(len(llm.requests), 2)
        first, second = llm.requests
        self.assertEqual(len(first.messages[-1][1].splitlines()), 1)
        self.assertIn("previous reply was rejected", second.messages[-1][1])
        self.assertIn("exactly the keys", second.messages[-1][1])
        self.assertEqual(first.attachments, second.attachments)
        self.assertEqual(set(result.facts), {"evidence_32"})
        self.assertEqual(len(result.notes), 1)
        self.assertIn("extraction rejected", result.notes[0])

    def test_two_rejections_skip_the_file_with_a_note(self) -> None:
        llm, result = self.run_with(["not json", '{"records": 3}'])
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(result.facts, {})
        self.assertEqual(len(result.notes), 3)
        self.assertIn("skipped after 2 rejected extractions", result.notes[-1])

    def test_refusal_is_not_retried(self) -> None:
        bad = LLMBadOutput("model stopped with refusal", response(""))
        with self.assertLogs("ghostaudit.llm", level="WARNING"):
            llm, result = self.run_with([bad])
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(result.facts, {})
        self.assertIn("refusal", result.notes[0])

    def test_unsupported_suffix_and_unreadable_file_are_noted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text_entry = dataclasses.replace(self.entry, file_id="ev_x1", path=folder / "a.txt")
            missing = dataclasses.replace(self.entry, file_id="ev_x2", path=folder / "gone.png")
            llm = FakeLLM({})
            result = extract_media_facts([text_entry, missing], llm, MODEL)
        self.assertEqual(llm.requests, [])
        self.assertEqual(result.facts, {})
        self.assertIn("unsupported media type", result.notes[0])
        self.assertIn("cannot read the file", result.notes[1])


class ModeTests(MediaFixture):
    def test_off_skips_every_file_and_logs_each_skip(self) -> None:
        with self.assertLogs("ghostaudit.llm", level="INFO") as logs:
            result = extract_media_facts(self.entries, NullClient(), MODEL)
        self.assertEqual(result.facts, {})
        self.assertEqual(len(result.notes), FILE_COUNT)
        self.assertEqual(len(logs.records), FILE_COUNT)
        self.assertTrue(all("disabled" in note for note in result.notes))

    def test_off_mode_of_the_caching_client_skips_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meter = UsageMeter(Config().prices)
            llm = CachingClient(NullClient(), DiskCache(Path(tmp)), meter, "off")
            with self.assertLogs("ghostaudit.llm", level="INFO") as logs:
                result = extract_media_facts(self.entries, llm, MODEL)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(result.facts, {})
        self.assertEqual(len(result.notes), FILE_COUNT)
        self.assertEqual(len(logs.records), FILE_COUNT)

    def test_cache_mode_on_an_empty_cache_skips_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meter = UsageMeter(Config().prices)
            llm = CachingClient(NullClient(), DiskCache(Path(tmp)), meter, "cache")
            with self.assertLogs("ghostaudit.llm", level="WARNING"):
                result = extract_media_facts(self.entries, llm, MODEL)
        self.assertEqual(result.facts, {})
        self.assertEqual(len(result.notes), FILE_COUNT)
        self.assertTrue(all("no cached response" in note for note in result.notes))

    def test_live_fill_then_cache_replay_gives_identical_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskCache(Path(tmp))
            meter = UsageMeter(Config().prices)
            inner = self.fake_for_all()
            live = CachingClient(inner, cache, meter, "live")
            first = extract_media_facts(self.entries, live, MODEL)
            replay_meter = UsageMeter(Config().prices)
            replay = CachingClient(inner, cache, replay_meter, "cache")
            second = extract_media_facts(self.entries, replay, MODEL)
        self.assertEqual(len(inner.requests), FILE_COUNT)
        self.assertEqual(first.facts, second.facts)
        self.assertEqual(replay_meter.usage(MODEL).replayed.calls, FILE_COUNT)
        self.assertEqual(replay_meter.usage(MODEL).live.calls, 0)


class CommittedCacheTests(MediaFixture):
    """Acceptance on the real extractions: replays the committed cache, never calls a model."""

    def test_committed_extractions_map_to_the_spec_targets(self) -> None:
        cache_dir = Config().cache_dir
        if not cache_dir.is_dir():
            self.skipTest("no committed cache at %s; run the --llm live fill first" % cache_dir)
        meter = UsageMeter(Config().prices)
        llm = CachingClient(NullClient(), DiskCache(cache_dir), meter, "cache")
        result = extract_media_facts(self.entries, llm, MODEL)
        if not result.facts:
            self.skipTest("the cache holds no media extraction for %s" % MODEL)
        self.assertEqual(set(result.facts), set(FILES), result.notes)
        mapped = self.map_all(result)
        for file_id, target in TARGETS.items():
            with self.subTest(file_id=file_id):
                self.assertIn(target, mapped[file_id])


class ValidationTests(unittest.TestCase):
    def record(self, **changes: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "display_id": " X-1 ", "resource_hint": "", "system_hint": "",
            "category": "USER_EXPORT",
            "emails": [" a@b.co "], "phones": [], "user_refs": [], "names": [], "dates": [],
            "state_facts": {"record_shown": True},
        }
        base.update(changes)
        return base

    def parse(self, record: Dict[str, Any]) -> Any:
        records, _notes = parse_records(json.dumps({"records": [record]}))
        return records

    def test_valid_record_is_stripped_and_canonical(self) -> None:
        (record,) = self.parse(self.record())
        self.assertEqual(record["display_id"], "X-1")
        self.assertEqual(record["emails"], ["a@b.co"])
        self.assertEqual(set(record), set(RECORD_FIELDS))

    def test_empty_records_are_valid(self) -> None:
        self.assertEqual(parse_records('{"records": []}'), ((), ()))

    def test_each_violation_is_rejected(self) -> None:
        bad_record = self.record()
        missing = {k: v for k, v in bad_record.items() if k != "dates"}
        cases = {
            "unknown category": self.record(category="ORDERS"),
            "text field not a string": self.record(display_id=3),
            "list not a list": self.record(emails="a@b.co"),
            "list item not a string": self.record(phones=[1]),
            "unknown state fact": self.record(state_facts={"restore_allowed": True}),
            "state fact not boolean": self.record(state_facts={"record_shown": "yes"}),
            "state_facts not an object": self.record(state_facts=[]),
            "missing key": missing,
            "extra key": self.record(extra=1),
        }
        for label, record in cases.items():
            with self.subTest(label), self.assertRaises(ExtractionInvalid):
                self.parse(record)

    def test_identifier_facts_are_dropped_outside_their_categories(self) -> None:
        both = {"record_shown": True, "pii_fields_shown": True, "only_stable_reference_shown": True}
        expected = {
            "USER_PROFILE": {"record_shown"},
            "SUPPORT_ATTACHMENT": {"record_shown"},
            "SECURITY_AUDIT_LOG": {"record_shown"},
            "": {"record_shown"},
            "ANALYTICS_PROFILE": {"record_shown", "pii_fields_shown"},
            "SUPPORT_MESSAGE": set(both),
            "ACCOUNT_TOMBSTONE": set(both),
        }
        for category, kept in expected.items():
            with self.subTest(category=category):
                (record,) = self.parse(self.record(category=category, state_facts=dict(both)))
                self.assertEqual(set(record["state_facts"]), kept)

    def test_a_dropped_true_fact_implies_the_record_is_shown(self) -> None:
        for fact in sorted(FACT_CATEGORIES):
            with self.subTest(fact=fact):
                text = json.dumps({"records": [self.record(state_facts={fact: True})]})
                (record,), notes = parse_records(text)
                self.assertEqual(record["state_facts"], {"record_shown": True})
                self.assertEqual(
                    notes,
                    ("records[0]: %s dropped, it does not apply to category 'USER_EXPORT'" % fact,),
                )

    def test_a_dropped_false_fact_adds_no_state(self) -> None:
        facts = {"pii_fields_shown": False, "only_stable_reference_shown": False}
        text = json.dumps({"records": [self.record(state_facts=facts)]})
        (record,), notes = parse_records(text)
        self.assertEqual(record["state_facts"], {})
        self.assertEqual(len(notes), 2)

    def test_in_scope_facts_leave_no_note(self) -> None:
        facts = {"record_shown": True, "pii_fields_shown": True}
        text = json.dumps({"records": [self.record(category="SUPPORT_MESSAGE", state_facts=facts)]})
        (record,), notes = parse_records(text)
        self.assertEqual(record["state_facts"], facts)
        self.assertEqual(notes, ())

    def test_restore_and_connector_facts_apply_to_their_categories_only(self) -> None:
        # The live model set restore_blocked=false on profiles, tickets and tombstones.
        facts = {"restore_blocked": False, "connector_enabled": True, "record_shown": True}
        expected = {
            "BACKUP_ARCHIVE": {"restore_blocked": False, "record_shown": True},
            "DATA_FLOW": {"connector_enabled": True, "record_shown": True},
            "USER_EXPORT": {"record_shown": True},
            "": {"record_shown": True},
        }
        for category, kept in expected.items():
            with self.subTest(category=category):
                (record,) = self.parse(self.record(category=category, state_facts=dict(facts)))
                self.assertEqual(record["state_facts"], kept)

    def test_identifier_facts_are_derived_from_the_transcribed_lists(self) -> None:
        shown = {"record_shown": True}
        cases = {
            ("ANALYTICS_PROFILE", "a@b.co", ""): {"pii_fields_shown": True, "record_shown": True},
            ("SUPPORT_MESSAGE", "a@b.co", "user_7"): {"pii_fields_shown": True, "record_shown": True},
            ("ACCOUNT_TOMBSTONE", "", "user_7"):
                {"only_stable_reference_shown": True, "record_shown": True},
            ("PRODUCT_TELEMETRY", "", "user_7"): shown,
            ("USER_PROFILE", "a@b.co", "user_7"): shown,
            ("SECURITY_AUDIT_LOG", "", "user_7"): shown,
        }
        for (category, email, user), expected in cases.items():
            with self.subTest(category=category, email=email, user=user):
                record = self.record(
                    category=category, emails=[email] if email else [],
                    user_refs=[user] if user else [], state_facts=dict(shown),
                )
                (parsed,), notes = parse_records(json.dumps({"records": [record]}))
                self.assertEqual(parsed["state_facts"], expected)
                self.assertEqual(len(notes), len(expected) - 1)

    def test_derivation_only_adds_to_the_model_facts(self) -> None:
        facts = {"pii_fields_shown": True, "record_shown": True}  # e.g. an email hash
        record = self.record(category="ACCOUNT_TOMBSTONE", emails=[], user_refs=["user_7"],
                             state_facts=dict(facts))
        (parsed,), notes = parse_records(json.dumps({"records": [record]}))
        self.assertEqual((parsed["state_facts"], notes), (facts, ()))

    def test_a_bare_reference_gets_no_derived_state(self) -> None:
        record = self.record(category="SUPPORT_MESSAGE", emails=[], state_facts={})
        (parsed,), notes = parse_records(json.dumps({"records": [record]}))
        self.assertEqual((parsed["state_facts"], notes), ({}, ()))

    def test_payload_shape_violations_are_rejected(self) -> None:
        texts = (
            "", "[]", "{}", '{"records": {}}', '{"records": [], "extra": 1}', '{"records": [3]}'
        )
        for text in texts:
            with self.subTest(text), self.assertRaises(ExtractionInvalid):
                parse_records(text)


class PromptAndSchemaTests(unittest.TestCase):
    def test_prompt_names_every_state_fact_and_category_and_field(self) -> None:
        prompt = load_prompt()
        for name in STATE_FACT_NAMES + MEDIA_CATEGORIES + RECORD_FIELDS:
            with self.subTest(name=name):
                self.assertIn(name, prompt)

    def test_state_facts_are_those_of_the_mapping_table(self) -> None:
        self.assertEqual(set(STATE_FACT_NAMES), {fact for fact, _v, _s in STATE_RULES})

    @needs_dataset
    def test_categories_are_the_rule_categories_plus_the_connector_category(self) -> None:
        rules = DatasetReader(Config().dataset_dir).rules()
        categories = {rule.data_category for rule in rules} | {"DATA_FLOW"}
        self.assertEqual(set(MEDIA_CATEGORIES), categories)

    @needs_dataset
    def test_fact_scopes_are_the_redact_and_anonymize_rule_categories(self) -> None:
        rules = DatasetReader(Config().dataset_dir).rules()
        by_action: Dict[str, set] = {}
        for rule in rules:
            by_action.setdefault(rule.required_action, set()).add(rule.data_category)
        self.assertEqual(
            set(FACT_CATEGORIES),
            {"restore_blocked", "connector_enabled", "pii_fields_shown",
             "only_stable_reference_shown"},
        )
        self.assertEqual(FACT_CATEGORIES["restore_blocked"], {"BACKUP_ARCHIVE"})
        self.assertEqual(FACT_CATEGORIES["connector_enabled"], {"DATA_FLOW"})
        self.assertEqual(FACT_CATEGORIES["only_stable_reference_shown"], by_action["REDACT"])
        self.assertEqual(
            FACT_CATEGORIES["pii_fields_shown"], by_action["REDACT"] | by_action["ANONYMIZE"]
        )

    def test_prompt_scopes_each_identifier_fact_to_its_categories(self) -> None:
        lines = {
            line.split(":", 1)[0][2:]: line
            for line in load_prompt().splitlines()
            if line.startswith("- ")
        }
        for fact, categories in FACT_CATEGORIES.items():
            with self.subTest(fact=fact):
                line = lines[fact]
                self.assertIn("only for", line)
                named = {category for category in MEDIA_CATEGORIES if category in line}
                self.assertEqual(named, set(categories))

    def test_prompt_keeps_bare_references_without_identifiers_or_state(self) -> None:
        prompt = load_prompt()
        self.assertIn("A bare reference to another entity", prompt)
        self.assertIn("no state_facts", prompt)

    def test_schema_lists_the_facts_in_rule_order_with_record_shown_last(self) -> None:
        # Structured outputs emit properties in schema order (see the module docstring).
        facts = MEDIA_SCHEMA["properties"]["records"]["items"]["properties"]["state_facts"]
        self.assertEqual(tuple(facts["properties"]), STATE_FACT_NAMES)
        self.assertEqual(STATE_FACT_NAMES[-1], "record_shown")
        prompt = load_prompt()
        positions = [prompt.index("- %s:" % fact) for fact in STATE_FACT_NAMES]
        self.assertEqual(positions, sorted(positions))

    def test_schema_is_strict_and_lists_every_record_field(self) -> None:
        items = MEDIA_SCHEMA["properties"]["records"]["items"]
        self.assertEqual(set(items["properties"]), set(RECORD_FIELDS))
        self.assertEqual(set(items["required"]), set(RECORD_FIELDS))
        self.assertFalse(items["additionalProperties"])
        self.assertFalse(MEDIA_SCHEMA["additionalProperties"])
        self.assertNotIn("required", items["properties"]["state_facts"])

    def test_prompt_forbids_guessing_and_ignores_embedded_instructions(self) -> None:
        prompt = load_prompt().lower()
        self.assertIn("never guess", prompt)
        self.assertIn("untrusted", prompt)

    def test_module_does_not_import_the_sdk(self) -> None:
        self.assertNotIn("anthropic", vars(media_extract))


if __name__ == "__main__":
    unittest.main()
