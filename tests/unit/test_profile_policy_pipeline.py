import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.model import canonical_json, contract_from_dict, to_plain
from chip_supergoal.normalize import semantic_errors
from chip_supergoal.policy import load_risk_policy, mandatory_evidence_requirements, risk_policy_errors
from chip_supergoal.profiles import ProfileError, resolve_contract, resolve_profile


class ProfilePolicyPipelineTest(unittest.TestCase):
    def fixture_data(self):
        return json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(encoding="utf-8"))

    def fixture_contract(self):
        return contract_from_dict(self.fixture_data())

    def risk_policy(self):
        return load_risk_policy(ROOT / "spec/risk-policy.json")

    def write_profiles(self, directory, profiles):
        root = Path(directory)
        for name, profile in profiles.items():
            (root / f"{name}.json").write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
        return root

    def base_profile(self, **overrides):
        profile = {
            "name": "base",
            "profile_version": "1.0",
            "approvals": {},
            "delivery": {},
            "privacy": {"private_operator_rules": False},
            "public_clean": False,
        }
        profile.update(overrides)
        return profile

    def public_profiles(self):
        return {
            "base": self.base_profile(),
            "public-clean": {
                "name": "public-clean",
                "extends": "base",
                "profile_version": "1.0",
                "delivery": {"review_pack_required": False, "transport": "none"},
                "privacy": {
                    "private_operator_rules": False,
                    "strip_private_references": True,
                },
                "public_clean": True,
            },
        }

    def contract_for_risk(self, tag):
        data = self.fixture_data()
        rule = self.risk_policy()["risk_tags"][tag]
        data["risks"] = [
            {"id": "RISK-001", "tag": tag, "severity": "P1", "mitigation": "bounded"}
        ]
        data["phases"][0]["risk_tags"] = [tag]
        data["phases"][0]["rpd"] = {
            "required": True,
            "focus": list(rule["required_rpd_focus"]),
        }
        return data

    def second_phase(self, data, *, ordinal=2):
        phase = deepcopy(data["phases"][0])
        phase["id"] = "P02"
        phase["ordinal"] = ordinal
        phase["depends_on"] = ["P01"]
        phase["criteria"][0]["id"] = "P02-C01"
        phase["criteria"][0]["verifier"]["command_id"] = "P02-CMD01"
        phase["commands"][0]["id"] = "P02-CMD01"
        phase["deliverables"][0]["id"] = "P02-D01"
        phase["work_items"][0]["id"] = "P02-W01"
        return phase

    def test_profile_inheritance_recursively_deep_merges_base(self):
        profiles = {
            "base": self.base_profile(
                delivery={
                    "transport": "none",
                    "nested": {"from_base": True, "winner": "base"},
                },
                privacy={"private_operator_rules": False, "base_only": True},
            ),
            "middle": {
                "name": "middle",
                "extends": "base",
                "profile_version": "1.0",
                "delivery": {"nested": {"from_middle": True}},
            },
            "selected": {
                "name": "selected",
                "extends": "middle",
                "profile_version": "1.0",
                "delivery": {"nested": {"winner": "selected"}},
                "privacy": {"selected_only": True},
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_profile("selected", self.write_profiles(temp, profiles))

        self.assertEqual(resolved["name"], "selected")
        self.assertEqual(resolved["delivery"]["transport"], "none")
        self.assertEqual(
            resolved["delivery"]["nested"],
            {"from_base": True, "from_middle": True, "winner": "selected"},
        )
        self.assertEqual(
            resolved["privacy"],
            {
                "private_operator_rules": False,
                "base_only": True,
                "selected_only": True,
            },
        )

    def test_resolve_contract_deep_merges_defaults_without_mutating_source(self):
        profiles = {
            "base": self.base_profile(
                delivery={
                    "transport": "none",
                    "nested": {"base": True, "winner": "base"},
                }
            ),
            "chip-private": {
                "name": "chip-private",
                "extends": "base",
                "profile_version": "1.0",
                "delivery": {
                    "review_pack_required": True,
                    "nested": {"private": True, "winner": "profile"},
                },
                "operator": "Chip",
            },
        }
        data = self.fixture_data()
        data["delivery"] = {
            "transport": "contract",
            "items": [],
            "nested": {"contract": True, "winner": "contract"},
        }
        source = contract_from_dict(data)
        before = deepcopy(to_plain(source))
        source_bytes = b'{"source":"original"}\r\n'

        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_contract(
                source, self.write_profiles(temp, profiles), source_bytes
            )

        self.assertEqual(to_plain(source), before)
        self.assertIsNot(resolved.contract, source)
        self.assertEqual(
            resolved.contract.delivery.data,
            {
                "transport": "contract",
                "review_pack_required": True,
                "items": [],
                "nested": {
                    "base": True,
                    "private": True,
                    "contract": True,
                    "winner": "contract",
                },
            },
        )
        self.assertEqual(resolved.source_sha256, hashlib.sha256(source_bytes).hexdigest())
        emitted = canonical_json(resolved.contract).encode("utf-8")
        self.assertEqual(resolved.contract_sha256, hashlib.sha256(emitted).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            resolved.contract_sha256 = "mutated"

    def test_missing_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ProfileError, "profile.*not found"):
                resolve_profile("missing", Path(temp))

    def test_profile_inheritance_cycle_is_rejected(self):
        profiles = {
            "a": {
                "name": "a",
                "extends": "b",
                "profile_version": "1.0",
            },
            "b": {
                "name": "b",
                "extends": "a",
                "profile_version": "1.0",
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            root = self.write_profiles(temp, profiles)
            with self.assertRaisesRegex(ProfileError, "cycle"):
                resolve_profile("a", root)

    def test_profile_name_version_and_unknown_keys_are_rejected(self):
        cases = {
            "mismatched name": (
                "selected",
                {"name": "other", "profile_version": "1.0"},
                "name.*does not match",
            ),
            "unsupported version": (
                "selected",
                {"name": "selected", "profile_version": "2.0"},
                "unsupported profile_version",
            ),
            "unknown key": (
                "selected",
                {
                    "name": "selected",
                    "profile_version": "1.0",
                    "risk_policy": {"allow": "everything"},
                },
                "unknown profile field",
            ),
        }
        for label, (name, profile, pattern) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                root = self.write_profiles(temp, {name: profile})
                with self.assertRaisesRegex(ProfileError, pattern):
                    resolve_profile(name, root)

    def test_public_clean_redacts_private_sources_and_strips_private_defaults(self):
        profiles = {
            "private-base": {
                "name": "private-base",
                "profile_version": "1.0",
                "delivery": {
                    "files": ["PRIVATE.md"],
                    "review_pack_required": True,
                    "target": "private-thread",
                    "transport": "telegram",
                },
                "operator": "Private Operator",
                "privacy": {"private_operator_rules": True},
                "public_clean": False,
            },
            "public-clean": {
                "name": "public-clean",
                "extends": "private-base",
                "profile_version": "1.0",
                "delivery": {"review_pack_required": False, "transport": "none"},
                "privacy": {
                    "private_operator_rules": False,
                    "strip_private_references": True,
                },
                "public_clean": True,
            },
        }
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "url",
                "locator": "https://example.com/public",
                "authority": "publisher",
                "freshness": "current",
                "sensitivity": "public",
            },
            {
                "id": "SRC-002",
                "kind": "file",
                "locator": "C:/private/input.txt",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "internal",
            },
            {
                "id": "SRC-003",
                "kind": "secret",
                "locator": "secret://token",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "secret",
            },
        ]
        source = contract_from_dict(data)

        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_contract(
                source, self.write_profiles(temp, profiles), b"source bytes"
            )

        self.assertEqual(resolved.contract.source_set[0].locator, "https://example.com/public")
        self.assertEqual(resolved.contract.source_set[1].locator, "[redacted]")
        self.assertEqual(resolved.contract.source_set[2].locator, "[redacted]")
        self.assertEqual(source.source_set[1].locator, "C:/private/input.txt")
        self.assertNotIn("operator", resolved.profile)
        self.assertNotIn("files", resolved.profile["delivery"])
        self.assertNotIn("target", resolved.profile["delivery"])
        self.assertNotIn("files", resolved.contract.delivery.data)
        self.assertNotIn("target", resolved.contract.delivery.data)
        self.assertEqual(resolved.contract.delivery.data["transport"], "none")
        self.assertFalse(resolved.contract.delivery.data["review_pack_required"])

    def test_public_clean_rejects_ambiguous_locator_references(self):
        locator = "C:/private/token.txt"
        cases = {
            "phase command": lambda data: data["phases"][0]["commands"][0].update(
                command=f'python read.py "{locator}"'
            ),
            "deliverable path": lambda data: data["phases"][0]["deliverables"][0].update(
                path=f"reports/{locator}"
            ),
            "required approval scope": lambda data: data["approvals"].append(
                {
                    "id": "APP-001",
                    "class_name": "privacy",
                    "scope": locator,
                    "required": True,
                }
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                data = self.fixture_data()
                data["profile"] = "public-clean"
                data["source_set"] = [
                    {
                        "id": "SRC-001",
                        "kind": "file",
                        "locator": locator,
                        "authority": "operator",
                        "freshness": "current",
                        "sensitivity": "private",
                    }
                ]
                mutate(data)
                source = contract_from_dict(data)
                profiles_dir = self.write_profiles(temp, self.public_profiles())
                with self.assertRaisesRegex(ProfileError, "redaction.*ambiguous"):
                    resolve_contract(source, profiles_dir, b"source")

    def test_chip_private_delivery_defaults_are_applied(self):
        data = self.fixture_data()
        source = contract_from_dict(data)
        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_contract(source, ROOT / "profiles", b"source")

        self.assertEqual(resolved.contract.delivery.data["items"], [])
        self.assertEqual(resolved.contract.delivery.data["transport"], "telegram")
        self.assertEqual(resolved.contract.delivery.data["target"], "current-thread")
        self.assertTrue(resolved.contract.delivery.data["review_pack_required"])
        self.assertIn("THINKING.md", resolved.contract.delivery.data["files"])

    def test_unknown_contract_and_phase_risk_tags_are_rejected(self):
        data = self.fixture_data()
        data["risks"][0]["tag"] = "invented"
        data["phases"][0]["risk_tags"] = []
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertTrue(any("unknown risk tag invented" in error for error in errors))

        data = self.fixture_data()
        data["phases"][0]["risk_tags"] = ["invented"]
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertTrue(any("P01 uses unknown risk tag invented" in error for error in errors))

    def test_phase_risk_must_be_declared_by_contract(self):
        data = self.fixture_data()
        data["risks"] = []
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertIn("P01 risk auth is not declared in contract risks", errors)

    def test_risk_requiring_approval_rejects_missing_approval(self):
        data = self.contract_for_risk("production")
        data["architecture"]["rollback"] = "restore the previous release"
        data["approvals"] = []
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertTrue(any("production approval" in error and "P01" in error for error in errors))

    def test_risk_accepts_required_approval_with_exact_allowed_scope(self):
        for scope in ("P01", "production", "all"):
            with self.subTest(scope=scope):
                data = self.contract_for_risk("production")
                data["architecture"]["rollback"] = "restore the previous release"
                data["approvals"] = [
                    {
                        "id": "APP-001",
                        "class_name": "production",
                        "scope": scope,
                        "required": True,
                    }
                ]
                errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
                self.assertEqual(errors, [])

    def test_risk_requiring_rollback_rejects_missing_declaration(self):
        data = self.contract_for_risk("production")
        data["approvals"] = [
            {
                "id": "APP-001",
                "class_name": "production",
                "scope": "P01",
                "required": True,
            }
        ]
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertTrue(any("production" in error and "rollback" in error for error in errors))

    def test_risk_accepts_architecture_or_loop_rollback(self):
        for section in ("architecture", "loop"):
            with self.subTest(section=section):
                data = self.contract_for_risk("production")
                data[section]["rollback"] = {"command": "restore previous release"}
                data["approvals"] = [
                    {
                        "id": "APP-001",
                        "class_name": "production",
                        "scope": "production",
                        "required": True,
                    }
                ]
                errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
                self.assertEqual(errors, [])

    def test_risk_requires_rpd_and_every_required_focus(self):
        data = self.contract_for_risk("gateway")
        data["architecture"]["rollback"] = "restore gateway config"
        data["approvals"] = [
            {
                "id": "APP-001",
                "class_name": "production",
                "scope": "gateway",
                "required": True,
            }
        ]
        data["phases"][0]["rpd"] = {"required": True, "focus": ["gateway"]}
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertIn("P01 risk gateway missing RPD focus: integration", errors)

        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        errors = risk_policy_errors(contract_from_dict(data), self.risk_policy())
        self.assertIn("P01 risk gateway requires RPD", errors)
        self.assertTrue(any("gateway, integration" in error for error in errors))

    def test_mandatory_evidence_mapping_is_sorted_unique_and_deterministic(self):
        data = self.fixture_data()
        data["risks"] = [
            {"id": "RISK-001", "tag": "production", "severity": "P1", "mitigation": "x"},
            {"id": "RISK-002", "tag": "auth", "severity": "P1", "mitigation": "x"},
            {"id": "RISK-003", "tag": "archive", "severity": "P2", "mitigation": "x"},
        ]
        data["phases"][0]["risk_tags"] = ["production", "auth", "production"]
        second = self.second_phase(data)
        second["risk_tags"] = ["archive", "auth"]
        data["phases"] = [second, data["phases"][0]]
        requirements = mandatory_evidence_requirements(
            contract_from_dict(data), self.risk_policy()
        )

        self.assertEqual(list(requirements), ["P01", "P02"])
        self.assertEqual(
            requirements,
            {
                "P01": ["deploy_status", "logs", "negative_authorization_fixture", "smoke"],
                "P02": ["negative_authorization_fixture", "path_safety_tests"],
            },
        )

    def test_semantic_errors_reject_zero_phases(self):
        data = self.fixture_data()
        data["phases"] = []
        errors = semantic_errors(contract_from_dict(data))
        self.assertTrue(any("at least one phase" in error for error in errors))

    def test_semantic_errors_reject_invalid_ordinals(self):
        cases = {
            "non-positive": ([0], "positive"),
            "duplicate": ([1, 1], "duplicate phase ordinal"),
            "non-contiguous": ([1, 3], "contiguous"),
        }
        for label, (ordinals, expected) in cases.items():
            with self.subTest(label=label):
                data = self.fixture_data()
                data["phases"][0]["ordinal"] = ordinals[0]
                if len(ordinals) == 2:
                    data["phases"].append(self.second_phase(data, ordinal=ordinals[1]))
                errors = semantic_errors(contract_from_dict(data))
                self.assertTrue(any(expected in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
