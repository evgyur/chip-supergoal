import json
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.diagnostics import Diagnostic, has_blocking
from chip_supergoal.invariants import load_catalog, validate_catalog, invariant_ids
from chip_supergoal.pipeline import validate_contract_source
import chip_supergoal.diagnostics as diagnostics_module

class DiagnosticsAndInvariantsTest(unittest.TestCase):
    def test_diagnostic_renders_human_and_json(self):
        d = Diagnostic(
            code="SGV-PHASE-COUNT-MISMATCH",
            severity="error",
            blocking_stage="preflight",
            invariant_id="INV-VALIDATOR-001",
            artifact="CONTRACT.json",
            pointer="/phases/0",
            message="Declared phase count does not match phases[] length",
            remediation="Regenerate counts from phases[]",
        )
        encoded = json.loads(d.to_json())
        self.assertEqual(encoded["code"], "SGV-PHASE-COUNT-MISMATCH")
        self.assertIn("INV-VALIDATOR-001", d.render_human())
        self.assertTrue(has_blocking([d]))

    def test_invalid_diagnostic_is_rejected(self):
        with self.assertRaises(ValueError):
            Diagnostic(
                code="BAD",
                severity="error",
                blocking_stage="preflight",
                invariant_id="INV-VALIDATOR-001",
                artifact="CONTRACT.json",
                pointer="/",
                message="bad",
                remediation="fix",
            )

    def test_invariant_catalog_is_complete_for_p1_hard_invariants(self):
        catalog = load_catalog(ROOT / "spec/invariant-catalog.json")
        errors = validate_catalog(catalog)
        self.assertEqual(errors, [])
        ids = invariant_ids(catalog)
        required = {
            "INV-BOUNDARY-001", "INV-GOAL-001", "INV-LAUNCH-001", "INV-CONTINUE-001",
            "INV-AUDIT-001", "INV-RPD-001", "INV-DELIVERY-001", "INV-RECOVERY-001",
            "INV-BLOCKER-001", "INV-REFERENCE-001", "INV-VALIDATOR-001", "INV-ARCHIVE-001",
        }
        self.assertTrue(required <= ids)
        for item in catalog["invariants"]:
            if item["severity_if_broken"] == "P1":
                self.assertTrue(item["tests"], item["id"])

    def test_diagnostic_catalog_matches_every_production_python_literal(self):
        catalog_path = ROOT / "spec/diagnostic-catalog.json"
        self.assertTrue(catalog_path.is_file(), "diagnostic catalog is required")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(set(catalog), {"catalog_version", "expected_code_count", "diagnostics"})
        self.assertEqual(catalog["catalog_version"], "1.0")
        self.assertEqual(catalog["expected_code_count"], 71)
        entries = catalog.get("diagnostics", [])
        self.assertEqual(len(entries), catalog["expected_code_count"])
        catalog_codes = [entry.get("code") for entry in entries]
        self.assertEqual(len(catalog_codes), len(set(catalog_codes)))
        for entry in entries:
            self.assertEqual(
                set(entry),
                {"code", "invariant", "stage", "remediation_class"},
            )
            self.assertRegex(entry["code"], r"^SGV-[A-Z0-9-]+$")
            self.assertTrue(entry["invariant"].startswith("INV-"))
            self.assertTrue(entry["stage"])
            self.assertTrue(entry["remediation_class"])

        pattern = re.compile(r"\bSGV-[A-Z0-9-]+\b")
        emitted = set()
        paths = sorted((ROOT / "lib").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    emitted.update(pattern.findall(node.value))

        self.assertEqual(set(catalog_codes), emitted)

    def test_pipeline_diagnostic_metadata_matches_catalog(self):
        catalog = json.loads(
            (ROOT / "spec/diagnostic-catalog.json").read_text(encoding="utf-8")
        )
        catalog_by_code = {item["code"]: item for item in catalog["diagnostics"]}
        fixture = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        cases = [("SGV-CONTRACT-MALFORMED", b"{}")]

        semantic = json.loads(json.dumps(fixture))
        semantic["phases"][0]["depends_on"] = ["P99"]
        cases.append(("SGV-CONTRACT-SEMANTIC", json.dumps(semantic).encode()))

        profile = json.loads(json.dumps(fixture))
        profile["profile"] = "does-not-exist"
        cases.append(("SGV-PROFILE-NOT-FOUND", json.dumps(profile).encode()))

        risk = json.loads(json.dumps(fixture))
        risk["risks"][0]["tag"] = "invented"
        risk["phases"][0]["risk_tags"] = ["invented"]
        cases.append(("SGV-RISK-UNKNOWN", json.dumps(risk).encode()))

        research = json.loads(json.dumps(fixture))
        research["compatibility"]["research_gate"]["status"] = "blocked"
        cases.append(("SGV-RESEARCH-REQUIRED", json.dumps(research).encode()))

        for code, source in cases:
            with self.subTest(code=code):
                result = validate_contract_source(source, resource_root=ROOT)
                diagnostic = next(item for item in result.diagnostics if item.code == code)
                expected = catalog_by_code[code]
                self.assertEqual(diagnostic.invariant_id, expected["invariant"])
                self.assertEqual(diagnostic.blocking_stage, expected["stage"])

    def test_diagnostic_metadata_registry_matches_catalog(self):
        self.assertTrue(
            hasattr(diagnostics_module, "diagnostic_metadata"),
            "diagnostic metadata registry is required",
        )
        catalog = json.loads(
            (ROOT / "spec/diagnostic-catalog.json").read_text(encoding="utf-8")
        )
        for entry in catalog["diagnostics"]:
            with self.subTest(code=entry["code"]):
                metadata = diagnostics_module.diagnostic_metadata(entry["code"])
                self.assertEqual(metadata.invariant, entry["invariant"])
                self.assertEqual(metadata.stage, entry["stage"])

    def test_unknown_catalog_codes_and_metadata_mismatches_are_rejected(self):
        with self.assertRaises(ValueError):
            diagnostics_module.diagnostic_metadata("SGV-TYPO-NOT-CATALOGED")
        with self.assertRaises(ValueError):
            Diagnostic(code="SGV-TYPO-NOT-CATALOGED", severity="error", blocking_stage="preflight", invariant_id="INV-VALIDATOR-001", artifact="x", pointer="/", message="x", remediation="x")
        with self.assertRaises(ValueError):
            Diagnostic(code="SGV-CONTRACT-MALFORMED", severity="error", blocking_stage="semantic", invariant_id="INV-VALIDATOR-001", artifact="x", pointer="/", message="x", remediation="x")

    def test_catalog_loader_rejects_invalid_invariant_shape(self):
        catalog = json.loads((ROOT / "spec/diagnostic-catalog.json").read_text(encoding="utf-8"))
        catalog["diagnostics"][0]["invariant"] = "INV-BOGUS"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaises(ValueError):
                diagnostics_module.load_diagnostic_catalog(path)

if __name__ == "__main__":
    unittest.main()
