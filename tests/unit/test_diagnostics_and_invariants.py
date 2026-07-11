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


_SGV_PATTERN = re.compile(r"\bSGV-[A-Z0-9-]+\b")
_DIAGNOSTIC_FACTORIES = {
    "Diagnostic",
    "_diag",
    "_diagnostic",
    "_mutable_diagnostic",
    "_research_diag",
}


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _codes_in(node: ast.AST) -> set[str]:
    codes: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            codes.update(_SGV_PATTERN.findall(child.value))
    return codes


def _factory_code_expression(call: ast.Call) -> ast.AST | None:
    name = _call_name(call)
    if name not in _DIAGNOSTIC_FACTORIES:
        return None
    for keyword in call.keywords:
        if keyword.arg == "code":
            return keyword.value
    return call.args[0] if call.args else None


def _tuple_position(target: ast.AST, name: str) -> int | None:
    if isinstance(target, (ast.Tuple, ast.List)):
        for index, item in enumerate(target.elts):
            if isinstance(item, ast.Name) and item.id == name:
                return index
    return None


def _assigned_name_codes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    function_defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> set[str]:
    codes: set[str] = set()
    assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)]
    for assignment in assignments:
        for target in assignment.targets:
            if isinstance(target, ast.Name) and target.id == name:
                codes.update(_codes_in(assignment.value))
            position = _tuple_position(target, name)
            if position is not None and isinstance(assignment.value, ast.Call):
                producer = function_defs.get(_call_name(assignment.value) or "")
                if producer is not None:
                    for returned in (
                        node for node in ast.walk(producer) if isinstance(node, ast.Return)
                    ):
                        if isinstance(returned.value, (ast.Tuple, ast.List)) and len(returned.value.elts) > position:
                            codes.update(_codes_in(returned.value.elts[position]))

    for loop in (node for node in ast.walk(function) if isinstance(node, ast.For)):
        position = _tuple_position(loop.target, name)
        if position is None or not isinstance(loop.iter, ast.Name):
            continue
        for assignment in assignments:
            if not any(
                isinstance(target, ast.Name) and target.id == loop.iter.id
                for target in assignment.targets
            ) or not isinstance(assignment.value, (ast.List, ast.Tuple)):
                continue
            for row in assignment.value.elts:
                if isinstance(row, (ast.List, ast.Tuple)) and len(row.elts) > position:
                    codes.update(_codes_in(row.elts[position]))
    return codes


def emitted_diagnostic_codes(paths: list[Path]) -> set[str]:
    emitted: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function in functions.values():
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                expression = _factory_code_expression(call)
                if expression is None:
                    continue
                emitted.update(_codes_in(expression))
                if isinstance(expression, ast.Name):
                    emitted.update(_assigned_name_codes(function, expression.id, functions))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                emitted.update(_codes_in(node.exc))
    return emitted


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
        self.assertEqual(catalog["expected_code_count"], 102)
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

        paths = sorted((ROOT / "lib").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))
        self.assertEqual(set(catalog_codes), emitted_diagnostic_codes(paths))

    def test_emitter_scanner_ignores_dead_sgv_literals(self):
        source = """
def emit_diagnostic():
    DEAD = 'SGV-DEAD-CODE'
    _diag('SGV-REAL-CODE', 'INV-REAL-001', 'x', '/', 'x', 'x')

def emit_error():
    raise ValueError(f'SGV-RAISE-CODE: failed')
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "emitter.py"
            path.write_text(source, encoding="utf-8")
            self.assertEqual(
                emitted_diagnostic_codes([path]),
                {"SGV-REAL-CODE", "SGV-RAISE-CODE"},
            )

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
