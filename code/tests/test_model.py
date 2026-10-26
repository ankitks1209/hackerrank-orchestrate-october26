"""Tests for ghostaudit.model and ghostaudit.config (SPEC 3.1, 8.4, N4, N5)."""
from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

from ghostaudit import config, model

# AGENTS 6.4 written out literally, independent of model.OPERATION_TABLE.
AGENTS_FINDING = [
    ("REPORT_REMAINING_RECORD", "PRESENT"),
    ("REPORT_EXPOSED_PII", "PRESENT"),
    ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("REPORT_RESTORE_RISK", "ACTIVE"),
]
AGENTS_REMEDIATION = [
    ("DISABLE_DATA_FLOW", "DISABLED"),
    ("BLOCK_RESTORE", "BLOCKED"),
    ("DELETE_RECORD", "ABSENT"),
    ("REDACT_RECORD", "REDACTED"),
    ("ANONYMIZE_RECORD", "ANONYMIZED"),
]
AGENTS_VERIFICATION = [
    ("VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
]
AGENTS_TABLE = {
    model.Phase.FINDING: AGENTS_FINDING,
    model.Phase.REMEDIATION: AGENTS_REMEDIATION,
    model.Phase.VERIFICATION: AGENTS_VERIFICATION,
}
FAKE_KEY = "unit-test-key-0123456789"


class OperationTableTests(unittest.TestCase):
    def test_counts_and_order_match_agents_table(self) -> None:
        self.assertEqual([len(model.OPERATION_TABLE[p]) for p in model.Phase], [4, 5, 6])
        for phase, expected in AGENTS_TABLE.items():
            self.assertEqual(list(model.OPERATION_TABLE[phase]), expected)

    def test_phase_order(self) -> None:
        self.assertEqual([p.name for p in sorted(model.Phase)],
                         ["FINDING", "REMEDIATION", "VERIFICATION"])

    def test_op_index_and_state_of_for_all_operations(self) -> None:
        seen = 0
        for phase, pairs in AGENTS_TABLE.items():
            for index, (operation, state) in enumerate(pairs):
                self.assertEqual(model.op_index(phase, operation), index)
                self.assertEqual(model.state_of(operation), state)
                seen += 1
        self.assertEqual(seen, 15)

    def test_unknown_operation_raises(self) -> None:
        with self.assertRaises(KeyError):
            model.state_of("NOPE")
        with self.assertRaises(KeyError):
            model.op_index(model.Phase.FINDING, "DELETE_RECORD")

    def test_treatment_ops_use_table_operations(self) -> None:
        self.assertEqual(set(model.TREATMENT_OPS), set(model.Treatment))
        finding_ops = {op for op, _ in AGENTS_FINDING}
        remediation_ops = {op for op, _ in AGENTS_REMEDIATION}
        verify_ops = {op for op, _ in AGENTS_VERIFICATION}
        for treatment, (finding, remediation, verify) in model.TREATMENT_OPS.items():
            self.assertIn(verify, verify_ops)
            if treatment is model.Treatment.RETAIN:
                self.assertEqual((finding, remediation), (None, None))
            else:
                self.assertIn(finding, finding_ops)
                self.assertIn(remediation, remediation_ops)

    def test_treatment_verify_states_match_compliant_state(self) -> None:
        expected = {
            model.Treatment.DELETE: "ABSENT",
            model.Treatment.REDACT: "REDACTED",
            model.Treatment.ANONYMIZE: "ANONYMIZED",
            model.Treatment.FLOW: "DISABLED",
            model.Treatment.RESTORE: "BLOCKED",
            model.Treatment.RETAIN: "PRESENT",
        }
        for treatment, state in expected.items():
            self.assertEqual(model.state_of(model.TREATMENT_OPS[treatment][2]), state)

    def test_obs_states_match_spec(self) -> None:
        self.assertEqual({s.value for s in model.ObsState},
                         {"PRESENT", "ABSENT", "EXPOSED", "REDACTED", "ANONYMIZED",
                          "ACTIVE", "DISABLED", "BLOCKED"})


class FrozenTests(unittest.TestCase):
    def test_all_model_dataclasses_are_frozen(self) -> None:
        classes = [model.Request, model.ManifestEntry, model.Observation,
                   model.ScopeAssertion, model.MediaFacts, model.ClassifiedActivity,
                   model.LinkedResource, model.CaseLinks, model.ResourceVerdict,
                   model.Step, model.CaseResult, config.Config, config.Flags,
                   config.ModelPrice]
        for cls in classes:
            self.assertTrue(dataclasses.is_dataclass(cls), cls.__name__)
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)  # type: ignore[attr-defined]

    def test_assignment_raises(self) -> None:
        step = model.Step(1, "FINDING", "account_service", "account_005",
                          "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            step.step_no = 2  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.Flags().never_mix = False  # type: ignore[misc]

    def test_step_has_exactly_the_seven_contract_fields(self) -> None:
        self.assertEqual([f.name for f in dataclasses.fields(model.Step)],
                         ["step_no", "phase", "system_id", "resource_id",
                          "operation", "state", "evidence_id"])


class ConfigTests(unittest.TestCase):
    def test_secret_never_reveals_value(self) -> None:
        secret = config.Secret(FAKE_KEY)
        self.assertEqual(repr(secret), "***")
        self.assertEqual(str(secret), "***")
        self.assertEqual("%s|%r|%s" % (secret, secret, "{}".format(secret)), "***|***|***")
        self.assertEqual(secret.reveal(), FAKE_KEY)

    def test_repr_of_config_hides_key(self) -> None:
        cfg = config.Config.from_env({config.API_KEY_ENV: FAKE_KEY})
        self.assertIsNotNone(cfg.api_key)
        self.assertNotIn(FAKE_KEY, repr(cfg))
        self.assertNotIn(FAKE_KEY, str(cfg))
        self.assertNotIn("api_key", repr(cfg))
        self.assertEqual(cfg.api_key.reveal(), FAKE_KEY)  # type: ignore[union-attr]

    def test_missing_key_gives_none(self) -> None:
        self.assertIsNone(config.Config.from_env({}).api_key)

    def test_key_excluded_from_equality(self) -> None:
        self.assertEqual(config.Config.from_env({config.API_KEY_ENV: "a"}),
                         config.Config.from_env({config.API_KEY_ENV: "b"}))

    def test_flags_defaults(self) -> None:
        flags = config.Flags()
        self.assertEqual(
            dataclasses.asdict(flags),
            {"verify_legal_holds": True, "allow_pre_request_findings": False,
             "fifo_pairing": True, "never_mix": True})

    def test_agent_defaults(self) -> None:
        cfg = config.Config()
        self.assertEqual(cfg.agent, "on")
        self.assertEqual((cfg.agent_model, cfg.router_model, cfg.verifier_model), ("claude-opus-5-5",) * 3)
        self.assertGreater(cfg.agent_max_usd, 0)

    def test_invalid_agent_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            config.Config(agent="maybe")

    def test_no_fitted_window_fields_remain(self) -> None:
        names = {field.name for field in dataclasses.fields(config.Config)}
        self.assertFalse({"account_window", "policy_window", "violation_window", "pointer_window",
                          "window_offset_s"} & names)

    def test_other_defaults(self) -> None:
        cfg = config.Config()
        self.assertEqual((cfg.intent_batch_size, cfg.timeout_s, cfg.retries), (25, 60, 3))
        self.assertEqual(cfg.intent_model, "claude-opus-5-5")
        self.assertEqual(cfg.media_model, "claude-opus-5-5")
        prices = {p.model: p for p in cfg.prices}
        self.assertEqual((prices["claude-opus-5-5"].input_per_mtok,
                          prices["claude-opus-5-5"].output_per_mtok,
                          prices["claude-opus-5-5"].cache_read_per_mtok), (4.0, 20.0, 0.20))
        self.assertEqual((prices["claude-haiku-5-5"].input_per_mtok,
                          prices["claude-haiku-5-5"].output_per_mtok), (0.10, 0.50))

    def test_invalid_llm_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            config.Config(llm_mode="bogus")

    def test_repo_root_is_independent_of_cwd(self) -> None:
        self.assertTrue((config.REPO_ROOT / "code" / "main.py").is_file())
        self.assertEqual(config.Config().dataset_dir, config.REPO_ROOT / "dataset")


class ImportTests(unittest.TestCase):
    def test_python_version_floor(self) -> None:
        self.assertGreaterEqual(sys.version_info[:2], (3, 9))

    def test_package_imports(self) -> None:
        import ghostaudit
        self.assertTrue(Path(ghostaudit.__file__).name == "__init__.py")


if __name__ == "__main__":
    unittest.main()
