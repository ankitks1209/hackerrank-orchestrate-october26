"""Tests for the versioned prompt files of the agent stage (SPEC 12.6)."""
from __future__ import annotations

import re
import unittest
from typing import Set

from ghostaudit.agent import prompts
from ghostaudit.dataset import DatasetReader
from ghostaudit.config import Config
from tests.dataset_guard import needs_dataset

NAMES = (prompts.AGENT_PROMPT, prompts.ROUTER_PROMPT, prompts.VERIFIER_PROMPT)
IDENTIFIER = re.compile(r"\b(?:activity|evidence|audit|case|user|search|support|analytics|account|export|backup)_(?:[0-9]+|x[0-9]+)\b")


class PromptShapeTests(unittest.TestCase):
    def test_each_prompt_has_exactly_two_synthetic_examples(self) -> None:
        for name in NAMES:
            self.assertEqual(len(re.findall(r"^# Example \d", prompts.load_prompt(name), re.M)), 2, name)

    def test_each_prompt_states_an_injection_stance(self) -> None:
        for name in NAMES:
            text = prompts.load_prompt(name).lower()
            self.assertRegex(text, r"ignore any instruction|never follow instructions", name)
            self.assertIn("data", text, name)

    def test_each_prompt_names_its_output(self) -> None:
        self.assertIn("submit_answer", prompts.load_prompt(prompts.AGENT_PROMPT))
        self.assertIn('"routes"', prompts.load_prompt(prompts.ROUTER_PROMPT))
        self.assertIn('"verdicts"', prompts.load_prompt(prompts.VERIFIER_PROMPT))

    def test_the_agent_prompt_states_the_cutoff_the_abstain_rule_and_the_citation_rule(self) -> None:
        text = prompts.load_prompt(prompts.AGENT_PROMPT)
        self.assertIn("audit_at", text)
        self.assertIn("UNSURE", text)
        self.assertIn("no evidence at or before the cutoff supports an assignment", text)
        self.assertIn("Never invent an id", text)
        self.assertIn("You never choose the operations", text)

    def test_the_agent_prompt_has_no_fitted_delay(self) -> None:
        text = prompts.load_prompt(prompts.AGENT_PROMPT)
        self.assertIn("Do not assume a fixed delay", text)
        self.assertNotRegex(text, r"\b\d+\s*(?:min|minutes|hours|h)\b.*(?:before|after) (?:the )?report")

    def test_the_verifier_prompt_can_approve_and_reject(self) -> None:
        text = prompts.load_prompt(prompts.VERIFIER_PROMPT)
        self.assertIn("approve", text)
        self.assertIn("reject", text)

    def test_the_prompt_name_is_the_file_name(self) -> None:
        for name in NAMES:
            self.assertTrue((prompts.PROMPT_DIR / (name + ".md")).is_file(), name)


@needs_dataset
class ExampleIdentifierTests(unittest.TestCase):
    """The examples use fictional ids: none occurs anywhere in the participant files."""

    @classmethod
    def setUpClass(cls) -> None:
        directory = Config().dataset_dir
        reader = DatasetReader(directory)
        parts = [(directory / name).read_text(encoding="utf-8", errors="ignore") for name in (
            "system_activity.csv", "deletion_requests.csv", "sample_deletion_requests.csv")]
        for entry in reader.manifest():
            if entry.path.suffix not in (".png", ".pdf"):
                parts.append(entry.path.read_text(encoding="utf-8", errors="ignore"))
        cls.dataset_ids: Set[str] = set(IDENTIFIER.findall("\n".join(parts)))

    def test_no_example_identifier_occurs_in_the_dataset(self) -> None:
        for name in NAMES:
            found = set(IDENTIFIER.findall(prompts.load_prompt(name)))
            self.assertEqual(found & self.dataset_ids, set(), name)


if __name__ == "__main__":
    unittest.main()
