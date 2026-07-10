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
import chip_supergoal.profiles as profiles_module
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
                    "review_pack_required": False,
                },
                privacy={
                    "private_operator_rules": False,
                    "public_export_allowed": False,
                },
            ),
            "middle": {
                "name": "middle",
                "extends": "base",
                "profile_version": "1.0",
                "delivery": {"target": "current-thread"},
                "privacy": {"public_export_allowed": True},
            },
            "selected": {
                "name": "selected",
                "extends": "middle",
                "profile_version": "1.0",
                "delivery": {"transport": "telegram"},
                "privacy": {"strip_private_references": True},
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_profile("selected", self.write_profiles(temp, profiles))

        self.assertEqual(resolved["name"], "selected")
        self.assertEqual(resolved["delivery"]["transport"], "telegram")
        self.assertEqual(
            resolved["delivery"],
            {
                "transport": "telegram",
                "review_pack_required": False,
                "target": "current-thread",
            },
        )
        self.assertEqual(
            resolved["privacy"],
            {
                "private_operator_rules": False,
                "public_export_allowed": True,
                "strip_private_references": True,
            },
        )

    def test_resolve_contract_deep_merges_defaults_without_mutating_source(self):
        profiles = {
            "base": self.base_profile(
                delivery={
                    "transport": "none",
                    "review_pack_required": False,
                }
            ),
            "chip-private": {
                "name": "chip-private",
                "extends": "base",
                "profile_version": "1.0",
                "delivery": {
                    "review_pack_required": True,
                    "files": ["THINKING.md"],
                    "target": "current-thread",
                },
                "operator": "Chip",
            },
        }
        data = self.fixture_data()
        data["delivery"] = {
            "transport": "contract",
            "items": [],
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
                "files": ["THINKING.md"],
                "target": "current-thread",
                "items": [],
            },
        )
        self.assertEqual(resolved.source_sha256, hashlib.sha256(source_bytes).hexdigest())
        emitted = canonical_json(resolved.contract).encode("utf-8")
        self.assertEqual(resolved.contract_sha256, hashlib.sha256(emitted).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            resolved.contract_sha256 = "mutated"

    def test_resolved_contract_returns_fresh_contract_copies(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles_dir = self.write_profiles(
                temp,
                {
                    "base": self.base_profile(),
                    "chip-private": {
                        "name": "chip-private",
                        "extends": "base",
                        "profile_version": "1.0",
                        "delivery": {"transport": "telegram"},
                    },
                },
            )
            resolved = resolve_contract(
                self.fixture_contract(), profiles_dir, b"source bytes"
            )

        escaped = resolved.contract
        escaped.delivery.data["tampered"] = True
        escaped.architecture.data["tampered"] = True
        escaped.phases[0].work_items[0]["text"] = "tampered"

        fresh = resolved.contract
        self.assertNotIn("tampered", fresh.delivery.data)
        self.assertNotIn("tampered", fresh.architecture.data)
        self.assertNotEqual(fresh.phases[0].work_items[0]["text"], "tampered")
        self.assertEqual(
            hashlib.sha256(canonical_json(fresh).encode("utf-8")).hexdigest(),
            resolved.contract_sha256,
        )

    def test_resolved_contract_profile_access_is_non_aliasing(self):
        resolved = resolve_contract(
            self.fixture_contract(), ROOT / "profiles", b"source bytes"
        )
        escaped = resolved.profile
        escaped["delivery"]["transport"] = "tampered"
        escaped["new"] = "tampered"

        fresh = resolved.profile
        self.assertEqual(fresh["delivery"]["transport"], "telegram")
        self.assertNotIn("new", fresh)

    def test_resolved_contract_exposes_canonical_identity_authority(self):
        resolved = resolve_contract(
            self.fixture_contract(), ROOT / "profiles", b"source bytes"
        )
        self.assertTrue(
            hasattr(resolved, "canonical_bytes"),
            "resolved contract must expose immutable canonical bytes",
        )
        self.assertTrue(
            hasattr(resolved, "assert_identity"),
            "resolved contract must expose an identity assertion",
        )
        self.assertIsInstance(resolved.canonical_bytes, bytes)
        self.assertEqual(
            resolved.contract_sha256,
            hashlib.sha256(resolved.canonical_bytes).hexdigest(),
        )
        self.assertEqual(
            resolved.canonical_bytes,
            canonical_json(resolved.contract).encode("utf-8"),
        )
        self.assertIsNone(resolved.assert_identity())

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

    def test_profile_nested_schema_rejects_wrong_shapes_keys_and_types(self):
        cases = {
            "public clean string": (
                {"public_clean": "true"},
                "public_clean.*boolean",
            ),
            "privacy list": (
                {"privacy": []},
                "privacy.*object",
            ),
            "privacy null": (
                {"privacy": None},
                "privacy.*object",
            ),
            "privacy unknown key": (
                {"privacy": {"private_operator_rules": False, "unknown": True}},
                "unknown privacy field",
            ),
            "privacy wrong bool": (
                {"privacy": {"private_operator_rules": "false"}},
                "privacy.private_operator_rules.*boolean",
            ),
            "approvals list": (
                {"approvals": []},
                "approvals.*object",
            ),
            "approvals null": (
                {"approvals": None},
                "approvals.*object",
            ),
            "approvals unknown key": (
                {"approvals": {"unknown": []}},
                "unknown approvals field",
            ),
            "dangerous actions not list": (
                {"approvals": {"dangerous_actions": "money"}},
                "approvals.dangerous_actions.*list",
            ),
            "dangerous actions null": (
                {"approvals": {"dangerous_actions": None}},
                "approvals.dangerous_actions.*list",
            ),
            "dangerous actions non-string item": (
                {"approvals": {"dangerous_actions": ["money", 1]}},
                "approvals.dangerous_actions.*strings",
            ),
            "delivery list": (
                {"delivery": []},
                "delivery.*object",
            ),
            "delivery null": (
                {"delivery": None},
                "delivery.*object",
            ),
            "delivery unknown key": (
                {"delivery": {"unknown": True}},
                "unknown delivery field",
            ),
            "review pack wrong bool": (
                {"delivery": {"review_pack_required": "false"}},
                "delivery.review_pack_required.*boolean",
            ),
            "transport wrong type": (
                {"delivery": {"transport": 1}},
                "delivery.transport.*string",
            ),
            "files not list": (
                {"delivery": {"files": "THINKING.md"}},
                "delivery.files.*list",
            ),
            "files null": (
                {"delivery": {"files": None}},
                "delivery.files.*list",
            ),
            "files non-string item": (
                {"delivery": {"files": ["THINKING.md", 1]}},
                "delivery.files.*strings",
            ),
            "target wrong type": (
                {"delivery": {"target": []}},
                "delivery.target.*string",
            ),
            "operator wrong type": (
                {"operator": 7},
                "operator.*string",
            ),
        }
        for label, (overrides, pattern) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                profile = self.base_profile(**overrides)
                root = self.write_profiles(temp, {"base": profile})
                with self.assertRaisesRegex(ProfileError, pattern):
                    resolve_profile("base", root)

    def test_current_repository_profiles_satisfy_nested_schema(self):
        for name in ("base", "chip-private", "public-clean"):
            with self.subTest(name=name):
                self.assertEqual(resolve_profile(name, ROOT / "profiles")["name"], name)

    def test_profile_inheritance_depth_is_bounded(self):
        self.assertTrue(
            hasattr(profiles_module, "MAX_PROFILE_DEPTH"),
            "profiles module must expose its inheritance depth bound",
        )
        depth = profiles_module.MAX_PROFILE_DEPTH + 1
        profiles = {}
        for index in range(depth):
            name = f"profile-{index:02d}"
            profile = {"name": name, "profile_version": "1.0"}
            if index + 1 < depth:
                profile["extends"] = f"profile-{index + 1:02d}"
            profiles[name] = profile
        with tempfile.TemporaryDirectory() as temp:
            root = self.write_profiles(temp, profiles)
            with self.assertRaisesRegex(ProfileError, "maximum.*depth"):
                resolve_profile("profile-00", root)

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
        data["delivery"].update(
            {
                "files": ["PRIVATE.md"],
                "operator": "Private Operator",
                "review_pack": {"target": "private-thread"},
                "review_pack_required": True,
                "target": "private-thread",
                "transport": "telegram",
            }
        )
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
        self.assertNotIn("operator", resolved.contract.delivery.data)
        self.assertNotIn("review_pack", resolved.contract.delivery.data)
        self.assertEqual(resolved.contract.delivery.data["transport"], "none")
        self.assertFalse(resolved.contract.delivery.data["review_pack_required"])

    def test_public_clean_recursively_redacts_descriptive_locator_occurrences(self):
        locator = "private://operator/source-record"
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["goal"]["objective"] = f"Plan from {locator} safely"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "file",
                "locator": locator,
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
                "used_by": ["P01"],
            }
        ]
        data["decisions"] = [{"reason": f"Evidence at {locator}"}]
        data["architecture"]["notes"] = [f"Derived from {locator}"]
        data["loop"]["notes"] = {"source": locator}
        data["phases"][0]["task"] = f"Use findings from {locator}"
        data["phases"][0]["work_items"][0]["text"] = f"Read {locator}"
        data["phases"][0]["criteria"][0]["statement"] = f"No leak of {locator}"
        data["phases"][0]["criteria"][0]["verifier"][
            "expected_assertion"
        ] = f"Output omits {locator}"
        data["phases"][0]["commands"][0]["purpose"] = f"Verify {locator} input"
        data["phases"][0]["deliverables"][0][
            "verification"
        ] = f"Compare against {locator}"
        data["approvals"] = [
            {
                "id": "APP-OPTIONAL",
                "class_name": "privacy",
                "scope": f"Review notes from {locator}",
                "required": False,
            }
        ]
        data["delivery"]["items"] = [f"Summary of {locator}"]
        data["compatibility"]["private_note"] = locator

        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_contract(
                contract_from_dict(data),
                self.write_profiles(temp, self.public_profiles()),
                b"source",
            )

        encoded = canonical_json(resolved.contract).encode("utf-8")
        self.assertNotIn(locator.encode("utf-8"), encoded)
        self.assertEqual(resolved.contract.source_set[0].locator, "[redacted]")
        self.assertIn("[redacted]", resolved.contract.goal.objective)
        self.assertEqual(
            resolved.contract.phases[0].work_items[0]["text"], "Read [redacted]"
        )

    def test_public_clean_short_locator_fails_on_structural_key_without_corruption(self):
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["goal"]["objective"] = "Keep this valid identifier unchanged"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "note",
                "locator": "id",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
            }
        ]
        source = contract_from_dict(data)
        before = canonical_json(source)

        with tempfile.TemporaryDirectory() as temp:
            try:
                resolve_contract(
                    source,
                    self.write_profiles(temp, self.public_profiles()),
                    b"source",
                )
            except ProfileError as exc:
                self.assertIn("dictionary key", str(exc))
                self.assertIn("/goal/id", str(exc))
            except Exception as exc:
                self.fail(
                    f"structural-key conflict must raise ProfileError, got {type(exc).__name__}: {exc}"
                )
            else:
                self.fail("structural-key conflict must block public-clean resolution")

        self.assertEqual(canonical_json(source), before)
        self.assertIn("valid identifier", before)
        self.assertNotIn("val[redacted]", before)

    def test_public_clean_redacts_tokens_without_rewriting_incidental_substrings(self):
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["goal"]["objective"] = "The secret is private; secretive is ordinary"
        data["compatibility"]["secretive"] = "valid"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "note",
                "locator": "secret",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            resolved = resolve_contract(
                contract_from_dict(data),
                self.write_profiles(temp, self.public_profiles()),
                b"source",
            )

        self.assertEqual(
            resolved.contract.goal.objective,
            "The [redacted] is private; secretive is ordinary",
        )
        self.assertIn("secretive", resolved.contract.compatibility)
        self.assertEqual(resolved.contract.compatibility["secretive"], "valid")
        self.assertNotIn("[redacted]ive", canonical_json(resolved.contract))

    def test_public_clean_rejects_locator_token_in_dictionary_key_with_path(self):
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["compatibility"]["private-secret"] = "description"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "note",
                "locator": "secret",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            profiles_dir = self.write_profiles(temp, self.public_profiles())
            with self.assertRaisesRegex(
                ProfileError, r"dictionary key.*?/compatibility/private-secret"
            ):
                resolve_contract(contract_from_dict(data), profiles_dir, b"source")

    def test_public_clean_ambiguity_checks_ignore_incidental_substrings(self):
        data = self.fixture_data()
        data["profile"] = "public-clean"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "note",
                "locator": "token",
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
            }
        ]
        data["phases"][0]["commands"][0]["command"] = "python tokenize.py"
        data["phases"][0]["deliverables"][0]["path"] = "tokenized.txt"
        data["approvals"] = [
            {
                "id": "APP-001",
                "class_name": "privacy",
                "scope": "token_group",
                "required": True,
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            try:
                resolved = resolve_contract(
                    contract_from_dict(data),
                    self.write_profiles(temp, self.public_profiles()),
                    b"source",
                )
            except Exception as exc:
                self.fail(
                    f"incidental substrings must not create redaction ambiguity: {exc}"
                )

        phase = resolved.contract.phases[0]
        self.assertEqual(phase.commands[0].command, "python tokenize.py")
        self.assertEqual(phase.deliverables[0].path, "tokenized.txt")
        self.assertEqual(resolved.contract.approvals[0].scope, "token_group")
        self.assertEqual(resolved.contract.source_set[0].locator, "[redacted]")

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

    def test_rollback_requires_a_nonblank_string_leaf(self):
        invalid_declarations = {
            "boolean": True,
            "number": 1,
            "empty list": [],
            "empty dict": {},
            "nested empty containers": {"steps": [[], {"command": "  "}]},
            "non-string leaves": {"enabled": True, "attempts": 2},
        }
        for label, declaration in invalid_declarations.items():
            for section in ("architecture", "loop"):
                with self.subTest(label=label, section=section):
                    data = self.contract_for_risk("production")
                    data[section]["rollback"] = declaration
                    data["approvals"] = [
                        {
                            "id": "APP-001",
                            "class_name": "production",
                            "scope": "P01",
                            "required": True,
                        }
                    ]
                    errors = risk_policy_errors(
                        contract_from_dict(data), self.risk_policy()
                    )
                    self.assertTrue(
                        any("production" in error and "rollback" in error for error in errors),
                        errors,
                    )

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

    def test_semantic_errors_allow_phase_array_order_independent_of_ordinals(self):
        data = self.fixture_data()
        second = self.second_phase(data)
        data["phases"] = [second, data["phases"][0]]
        errors = semantic_errors(contract_from_dict(data))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
