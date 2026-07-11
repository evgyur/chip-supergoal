from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import build_manifest, compile_contract, compile_contract_file
from chip_supergoal.diagnostics import ContractValidationError
from chip_supergoal.model import contract_from_dict
from chip_supergoal.pipeline import validate_contract_source
from chip_supergoal.validate import validate_contract_file


class CompileFailClosedTest(unittest.TestCase):
    def fixture(self) -> dict:
        return json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )

    def run_sgctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/sgctl.py", *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write_contract(self, root: Path, data: dict) -> Path:
        path = root / "CONTRACT.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def cli_validation_codes(self, source: Path) -> set[str]:
        result = self.run_sgctl(
            "validate-contract", str(source), "--format", "json"
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return {item["code"] for item in json.loads(result.stdout)}

    def cli_compile_codes(self, source: Path, output: Path) -> set[str]:
        result = self.run_sgctl("compile", str(source), "--out", str(output))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())
        return set(re.findall(r"SGV-[A-Z0-9-]+", result.stderr))

    def test_cli_compile_rejects_missing_dependency_without_output_or_traceback(self):
        data = self.fixture()
        data["phases"][0]["depends_on"] = ["P99"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            output = root / "package"

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-CONTRACT-SEMANTIC", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_compile_rejects_missing_profile_without_output_or_traceback(self):
        data = self.fixture()
        data["profile"] = "does-not-exist"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            output = root / "package"

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-PROFILE-NOT-FOUND", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_public_clean_compile_writes_sanitized_contract(self):
        data = self.fixture()
        private_locator = "C:/private/operator-notes.txt"
        data["profile"] = "public-clean"
        data["source_set"] = [
            {
                "id": "SRC-001",
                "kind": "file",
                "locator": private_locator,
                "authority": "operator",
                "freshness": "current",
                "sensitivity": "private",
            }
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            output = root / "package"

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            emitted = (output / "CONTRACT.json").read_text(encoding="utf-8")
            self.assertNotIn(private_locator, emitted)
            self.assertIn("[redacted]", emitted)

    def test_validate_and_compile_have_diagnostic_parity_for_every_gate(self):
        cases = {}

        zero_phases = self.fixture()
        zero_phases["phases"] = []
        cases["zero phases"] = (zero_phases, {"SGV-CONTRACT-SEMANTIC"})

        unknown_risk = self.fixture()
        unknown_risk["risks"][0]["tag"] = "invented"
        unknown_risk["phases"][0]["risk_tags"] = ["invented"]
        cases["unknown risk"] = (unknown_risk, {"SGV-RISK-UNKNOWN"})

        undeclared_risk = self.fixture()
        undeclared_risk["risks"] = []
        cases["undeclared risk"] = (
            undeclared_risk,
            {"SGV-RISK-UNDECLARED"},
        )

        unsafe = self.fixture()
        unsafe["risks"] = [
            {
                "id": "RISK-001",
                "tag": "production",
                "severity": "P1",
                "mitigation": "controlled release",
            }
        ]
        unsafe["phases"][0]["risk_tags"] = ["production"]
        unsafe["phases"][0]["rpd"] = {
            "required": True,
            "focus": ["integration"],
        }
        unsafe["approvals"] = []
        cases["approval and rollback"] = (
            unsafe,
            {"SGV-RISK-APPROVAL-MISSING", "SGV-RISK-ROLLBACK-MISSING"},
        )

        missing_focus = self.fixture()
        missing_focus["risks"] = [
            {
                "id": "RISK-001",
                "tag": "gateway",
                "severity": "P1",
                "mitigation": "bounded gateway change",
            }
        ]
        missing_focus["phases"][0]["risk_tags"] = ["gateway"]
        missing_focus["phases"][0]["rpd"] = {
            "required": True,
            "focus": ["gateway"],
        }
        missing_focus["architecture"]["rollback"] = "restore gateway config"
        missing_focus["approvals"] = [
            {
                "id": "APP-001",
                "class_name": "production",
                "scope": "gateway",
                "required": True,
            }
        ]
        cases["RPD focus"] = (
            missing_focus,
            {"SGV-RISK-RPD-FOCUS-MISSING"},
        )

        blocked_research = self.fixture()
        blocked_research["compatibility"]["research_gate"] = {
            "required": True,
            "status": "blocked",
            "provider": "perplex",
            "sources": [],
        }
        cases["research"] = (
            blocked_research,
            {"SGV-RESEARCH-REQUIRED", "SGV-RESEARCH-SOURCES"},
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, (label, (data, expected)) in enumerate(cases.items()):
                with self.subTest(label=label):
                    case_root = root / str(index)
                    case_root.mkdir()
                    source = self.write_contract(case_root, data)
                    validation_codes = self.cli_validation_codes(source)
                    compile_codes = self.cli_compile_codes(
                        source, case_root / "package"
                    )
                    self.assertTrue(expected <= validation_codes, validation_codes)
                    self.assertEqual(compile_codes, validation_codes)

    def test_invalid_compile_preserves_existing_valid_target_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "package"
            valid = self.write_contract(root, self.fixture())
            initial = self.run_sgctl("compile", str(valid), "--out", str(output))
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            before = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }

            invalid_data = self.fixture()
            invalid_data["phases"][0]["depends_on"] = ["P99"]
            invalid = root / "INVALID.json"
            invalid.write_text(json.dumps(invalid_data), encoding="utf-8")
            result = self.run_sgctl(
                "compile", str(invalid), "--out", str(output)
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-CONTRACT-SEMANTIC", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            after = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_direct_compile_raises_structured_diagnostics(self):
        data = self.fixture()
        data["phases"][0]["depends_on"] = ["P99"]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "package"
            with self.assertRaises(ContractValidationError) as raised:
                compile_contract(contract_from_dict(data), output)

            diagnostics = getattr(raised.exception, "diagnostics", ())
            self.assertIn(
                "SGV-CONTRACT-SEMANTIC", {item.code for item in diagnostics}
            )
            self.assertFalse(output.exists())

    def test_profile_cycle_blocks_validation_and_compile_with_same_code(self):
        data = self.fixture()
        data["profile"] = "cycle-a"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profiles = root / "profiles"
            policy = root / "spec"
            profiles.mkdir()
            policy.mkdir()
            for name, parent in (("cycle-a", "cycle-b"), ("cycle-b", "cycle-a")):
                (profiles / f"{name}.json").write_text(
                    json.dumps(
                        {
                            "name": name,
                            "extends": parent,
                            "profile_version": "1.0",
                        }
                    ),
                    encoding="utf-8",
                )
            (policy / "risk-policy.json").write_bytes(
                (ROOT / "spec/risk-policy.json").read_bytes()
            )
            source = self.write_contract(root, data)
            output = root / "package"

            validation = validate_contract_file(source, resource_root=root)
            self.assertEqual({item.code for item in validation}, {"SGV-PROFILE-CYCLE"})
            with self.assertRaises(ContractValidationError) as raised:
                compile_contract_file(source, output, resource_root=root)
            self.assertEqual(
                {item.code for item in getattr(raised.exception, "diagnostics", ())},
                {"SGV-PROFILE-CYCLE"},
            )
            self.assertFalse(output.exists())

    def test_malformed_contract_is_concise_and_fail_closed(self):
        data = self.fixture()
        data["unknown_enforcement_field"] = True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            output = root / "package"

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertEqual(result.returncode, 1)
            self.assertIn("SGV-CONTRACT-MALFORMED", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_nested_wrong_type_is_malformed_without_traceback(self):
        data = self.fixture()
        data["phases"][0]["id"] = None
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            output = root / "package"

            validation_codes = self.cli_validation_codes(source)
            compile_codes = self.cli_compile_codes(source, output)

            self.assertEqual(validation_codes, {"SGV-CONTRACT-MALFORMED"})
            self.assertEqual(compile_codes, validation_codes)

    def test_malformed_risk_policy_fails_closed_without_cascade(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
            (root / "spec").mkdir()
            (root / "profiles/chip-private.json").write_text(
                json.dumps(
                    {"name": "chip-private", "profile_version": "1.0"}
                ),
                encoding="utf-8",
            )
            (root / "spec/risk-policy.json").write_text(
                json.dumps({"risk_tags": {"auth": "not-a-rule"}}),
                encoding="utf-8",
            )
            source = self.write_contract(root, self.fixture())

            diagnostics = validate_contract_file(source, resource_root=root)

            self.assertEqual(
                {item.code for item in diagnostics},
                {"SGV-RISK-POLICY-MALFORMED"},
            )

    def test_cli_compile_safety_error_is_concise(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, self.fixture())
            output = root / "package"
            first = self.run_sgctl("compile", str(source), "--out", str(output))
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            (output / "runtime").mkdir()
            (output / "runtime" / "STATE.json").write_text("{}\n", encoding="utf-8")

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertEqual(result.returncode, 1)
            self.assertIn("refusing to overwrite", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn(str(output) + "\n", result.stdout)

    def test_cli_compile_output_parent_error_is_concise(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, self.fixture())
            parent_file = root / "not-a-directory"
            parent_file.write_text("occupied\n", encoding="utf-8")

            result = self.run_sgctl(
                "compile", str(source), "--out", str(parent_file / "package")
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("compile error:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_malformed_sealed_target_is_preserved_and_sanitized(self):
        secret = "existing-private-token"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, self.fixture())
            output = root / "package"
            output.mkdir()
            malformed = self.fixture()
            malformed["contract_revision"] = secret
            (output / "CONTRACT.json").write_text(json.dumps(malformed), encoding="utf-8")
            manifest = build_manifest(output)
            (output / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn(secret, result.stdout + result.stderr)
            after = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertEqual(after, before)

    def test_deeply_malformed_sealed_target_is_preserved_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, self.fixture())
            output = root / "package"
            output.mkdir()
            (output / "CONTRACT.json").write_text("[" * 1100 + "0" + "]" * 1100, encoding="utf-8")
            (output / "MANIFEST.json").write_text(json.dumps(build_manifest(output)), encoding="utf-8")
            before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}

            result = self.run_sgctl("compile", str(source), "--out", str(output))

            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
            after = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertEqual(after, before)

    def test_secret_bearing_contract_error_uses_stable_message(self):
        secret = "contract-private-token"
        data = self.fixture()
        data["contract_revision"] = secret
        result = validate_contract_source(json.dumps(data).encode(), resource_root=ROOT)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.message, "contract JSON or v3 model is malformed")
        self.assertNotIn(secret, diagnostic.to_json() + diagnostic.render_human())

    def test_profile_and_policy_parse_errors_use_stable_private_messages(self):
        secret = "resource-private-token"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
            (root / "spec").mkdir()
            source = self.write_contract(root, self.fixture())
            (root / "profiles/chip-private.json").write_text('{"' + secret, encoding="utf-8")
            (root / "spec/risk-policy.json").write_text("{}", encoding="utf-8")
            profile_diag = validate_contract_file(source, resource_root=root)[0]
            self.assertEqual(profile_diag.message, "profile resolution failed")
            self.assertNotIn(secret, profile_diag.to_json())

            (root / "profiles/chip-private.json").write_text(json.dumps({"name": "chip-private", "profile_version": "1.0"}), encoding="utf-8")
            (root / "spec/risk-policy.json").write_text('{"' + secret, encoding="utf-8")
            policy_diag = validate_contract_file(source, resource_root=root)[0]
            self.assertEqual(policy_diag.message, "risk policy is malformed")
            self.assertNotIn(secret, policy_diag.to_json())

    def test_custom_risk_policy_path_is_loaded_exactly(self):
        data = self.fixture()
        tag = "custom_unique_tag"
        data["risks"][0]["tag"] = tag
        data["phases"][0]["risk_tags"] = [tag]
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.write_contract(root, data)
            policy = json.loads((ROOT / "spec/risk-policy.json").read_text(encoding="utf-8"))
            policy["risk_tags"][tag] = {"approval_class": "none", "mandatory_evidence": [], "required_rpd_focus": [], "rollback_required": False}
            custom = root / "custom-policy.json"
            custom.write_text(json.dumps(policy), encoding="utf-8")

            self.assertIn("SGV-RISK-UNKNOWN", {d.code for d in validate_contract_file(source)})
            self.assertEqual(validate_contract_file(source, custom), [])

    def test_pipeline_result_requires_attribute_access(self):
        result = validate_contract_source(json.dumps(self.fixture()).encode(), resource_root=ROOT)
        self.assertFalse(hasattr(type(result), "__iter__"))


if __name__ == "__main__":
    unittest.main()
