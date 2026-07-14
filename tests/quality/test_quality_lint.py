import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import (
    lint_false_green_fragment,
    lint_quality_gate,
    plan_subject_projection,
    quality_status,
    seal_quality_attestation,
)
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.model import contract_from_dict, to_plain
from chip_supergoal.profiles import resolve_contract
from chip_supergoal.pipeline import validate_contract_source
from chip_supergoal.profiles import resolve_profile

FIXTURES = ROOT / "evals/b2/fixtures"


def valid_quality_contract():
    contract = {
        "compatibility": {
            "quality_gate_v1": {
                "subject": {
                    "source_set": [{
                        "id": "SRC-001",
                        "locator": "git+https://example.invalid/repo.git@" + "a" * 40 + ":facts.txt",
                        "freshness": "2026-07-14", "sha256": "b" * 64,
                        "used_by": ["REQ-001"],
                    }],
                    "intent": {"objective": "Improve the class-level planner", "architecture_affecting": True, "request_class": "class_level"},
                    "requirements": [{"id": "REQ-001", "priority": "must", "statement": "Preserve runtime authority", "criterion_ids": ["P01-C01"], "non_goal": False}],
                    "constraints": {"non_goals": ["Do not create a second runtime"], "source_of_truth": "runtime/STATE.json"},
                    "assumptions": [{"id": "ASM-001", "statement": "The selected source is current", "critical": True, "evidence_source_id": "SRC-001", "falsifier_command_id": None}],
                    "options": [
                        {"id": "OPT-001", "statement": "Add a narrow deterministic linter", "selected": True, "rejection_reason": None},
                        {"id": "OPT-002", "statement": "Replace the compiler", "selected": False, "rejection_reason": "Wider than the demonstrated defect"},
                    ],
                    "traceability": [{"requirement_id": "REQ-001", "criterion_id": "P01-C01", "verifier_command_id": "P01-CMD01", "evidence_tier": "programmatic"}],
                    "failure_modes": [{"id": "FM-001", "severity": "P1", "statement": "False block", "mitigation": "Report stable diagnostics", "rollback": "Disable the canary profile", "verifier_command_id": "P01-CMD01"}],
                    "permissions": {"runtime_authority": "runtime/STATE.json", "approval_boundaries": ["local-read-write"], "source_authorities": ["SRC-001"]},
                    "overengineering": [{"layer": "deterministic-linter", "necessity": "Closes reproduced false greens", "simpler_alternative": "Existing structural validator was disproved", "removal_condition": "Remove if benchmark gain is below MCID"}],
                    "budgets": {"max_repair_cycles": 2, "planner_tokens": 8000, "time_seconds": 900},
                },
                "attestation": {
                    "quality_contract_version": "1.0",
                    "quality_policy_version": "plan-quality-policy-v1",
                    "rubric_version": "quality-rubric-v1",
                    "status": "required",
                    "semantic_review_lane": "b_plus_c",
                    "semantic_review_lane_reason": "QG-LANE-HIGH-RISK",
                    "plan_subject_sha256": "c" * 64,
                    "report_path": "reports/plan-quality.json",
                    "report_sha256": "d" * 64,
                    "semantic_judge_required": True,
                    "semantic_judge_status": "passed",
                    "semantic_judge_reason": "QG-JUDGE-HIGH-RISK",
                },
            }
        },
    }
    return seal_quality_attestation(
        contract,
        {"schema_version": "plan-quality-policy-v1"},
        {"schema_version": "quality-rubric-v1"},
    )


class QualityLintTests(unittest.TestCase):
    def test_all_frozen_false_green_fragments_fail_with_stable_codes(self):
        expected = {
            "B2-FG-01": "QG-MISSING-TRACE",
            "B2-FG-02": "QG-UNBOUND-SOURCE",
            "B2-FG-03": "QG-FUTURE-DEPENDENCY",
            "B2-FG-04": "QG-APPROVAL-SCOPE",
            "B2-FG-05": "QG-RUNTIME-AUTHORITY",
        }
        for case_id, code in expected.items():
            path = next(FIXTURES.glob(f"{case_id}-*.json"))
            fixture = json.loads(path.read_text(encoding="utf-8"))
            findings = lint_false_green_fragment(fixture["plan_fragment"])
            self.assertIn(code, [finding.code for finding in findings], case_id)
            self.assertTrue(all(finding.blocking for finding in findings), case_id)

    def test_absent_quality_overlay_is_not_applicable(self):
        self.assertEqual(quality_status({"compatibility": {}}), "not_applicable")

    def test_plan_subject_projection_removes_only_attestation(self):
        contract = {
            "goal": {"id": "sg-20260714-example"},
            "compatibility": {
                "legacy": {"keep": True},
                "quality_gate_v1": {
                    "subject": {"requirements": []},
                    "attestation": {"status": "required"},
                },
            },
        }
        projected = plan_subject_projection(contract)
        self.assertNotIn("attestation", projected["compatibility"]["quality_gate_v1"])
        self.assertEqual(projected["compatibility"]["legacy"], {"keep": True})
        self.assertIn("attestation", contract["compatibility"]["quality_gate_v1"])

    def test_valid_quality_overlay_is_green_for_deterministic_lint(self):
        self.assertEqual(lint_quality_gate(valid_quality_contract()), [])

    def test_quality_overlay_is_closed_and_rejects_unknown_subject_fields(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["shadow_authority"] = {}
        self.assertIn("QG-SCHEMA", [item.code for item in lint_quality_gate(contract)])

    def test_must_requirement_without_trace_is_blocked(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["traceability"] = []
        self.assertIn("QG-MISSING-TRACE", [item.code for item in lint_quality_gate(contract)])

    def test_critical_assumption_without_evidence_or_falsifier_is_blocked(self):
        contract = valid_quality_contract()
        assumption = contract["compatibility"]["quality_gate_v1"]["subject"]["assumptions"][0]
        assumption["evidence_source_id"] = None
        assumption["falsifier_command_id"] = None
        self.assertIn("QG-UNBOUND-ASSUMPTION", [item.code for item in lint_quality_gate(contract)])

    def test_assumption_source_links_must_resolve_to_hash_bound_sources(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["assumptions"][0]["evidence_source_id"] = "SRC-MISSING"
        self.assertIn("QG-UNBOUND-SOURCE", [item.code for item in lint_quality_gate(contract)])

        contract["compatibility"]["quality_gate_v1"]["subject"]["source_set"] = [{
            "id": "SRC-MISSING", "kind": "document", "locator": "urn:test:source",
            "used_by": ["REQ-MISSING"], "sha256": "short", "freshness": "current",
        }]
        self.assertIn("QG-UNBOUND-SOURCE", [item.code for item in lint_quality_gate(contract)])

    def test_rollback_must_be_concrete_not_one_character(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["failure_modes"][0]["rollback"] = "x"
        self.assertIn("QG-RISK-NO-ROLLBACK", [item.code for item in lint_quality_gate(contract)])

    def test_architecture_change_without_alternative_is_blocked(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["options"] = contract["compatibility"]["quality_gate_v1"]["subject"]["options"][:1]
        self.assertIn("QG-NO-ALTERNATIVE", [item.code for item in lint_quality_gate(contract)])

    def test_p1_failure_without_rollback_is_blocked(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["failure_modes"][0]["rollback"] = ""
        self.assertIn("QG-RISK-NO-ROLLBACK", [item.code for item in lint_quality_gate(contract)])

    def test_new_layer_without_removal_condition_is_blocked(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["overengineering"][0]["removal_condition"] = ""
        self.assertIn("QG-LAYER-NO-REMOVAL", [item.code for item in lint_quality_gate(contract)])

    def test_quality_canary_profile_enables_gate_without_changing_base(self):
        base = resolve_profile("base", ROOT / "profiles")
        canary = resolve_profile("quality-canary", ROOT / "profiles")
        self.assertNotIn("quality", base)
        self.assertTrue(canary["quality"]["required"])
        self.assertEqual(canary["quality"]["quality_contract_version"], "1.0")
        self.assertEqual(canary["quality"]["planning_canary"]["max_repair_rounds"], 2)
        self.assertEqual(canary["quality"]["planning_canary"]["b_only_semantic_calls"], 0)

    def test_quality_canary_compiler_pipeline_blocks_quality_findings(self):
        data = json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(encoding="utf-8"))
        data["profile"] = "quality-canary"
        gate = valid_quality_contract()["compatibility"]["quality_gate_v1"]
        gate["subject"]["assumptions"][0]["evidence_source_id"] = None
        gate["subject"]["assumptions"][0]["falsifier_command_id"] = "P01-CMD01"
        gate["subject"]["permissions"]["source_authorities"] = []
        gate["subject"]["traceability"] = []
        data.setdefault("compatibility", {})["quality_gate_v1"] = gate
        result = validate_contract_source(json.dumps(data).encode(), resource_root=ROOT)
        self.assertFalse(result.ok)
        self.assertTrue(any(item.code == "QG-MISSING-TRACE" for item in result.diagnostics))

    def test_valid_quality_canary_compiles_without_changing_legacy_profiles(self):
        data = json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(encoding="utf-8"))
        data["profile"] = "quality-canary"
        data.setdefault("compatibility", {})["quality_gate_v1"] = valid_quality_contract()["compatibility"]["quality_gate_v1"]
        for phase in data["phases"]:
            for command in phase["commands"]:
                command.update({
                    "cwd": ".", "mutation_class": "local_read_write",
                    "availability_dependencies": ["python3"],
                    "expected_output": {"kind": "exit_code", "value": 0},
                    "risk_tags": [], "risk_waiver": None,
                })
        normalized = resolve_contract(
            contract_from_dict(data), ROOT / "profiles", json.dumps(data).encode("utf-8")
        )
        data = json.loads(normalized.canonical_bytes)
        data = seal_quality_attestation(
            data,
            json.loads((ROOT / "spec/plan-quality-policy.json").read_text(encoding="utf-8")),
            json.loads((ROOT / "spec/quality-rubric.json").read_text(encoding="utf-8")),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "CONTRACT.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            out = compile_contract_file(source, Path(tmp) / "package", resource_root=ROOT)
            self.assertTrue((out / "LAUNCH_GOAL.md").is_file())
            report_path = out / "reports/plan-quality.json"
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
            self.assertEqual(report["status"], "green")
            self.assertEqual(report["findings"], [])
            compiled = json.loads((out / "CONTRACT.json").read_text(encoding="utf-8"))
            self.assertEqual(compiled["profile"], "quality-canary")
            self.assertEqual(
                compiled["compatibility"]["quality_gate_v1"]["attestation"]["report_sha256"],
                hashlib.sha256(report_bytes).hexdigest(),
            )

    def test_command_quality_fields_are_additive_and_round_trip(self):
        data = json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(encoding="utf-8"))
        command = data["phases"][0]["commands"][0]
        command.update({
            "cwd": ".",
            "mutation_class": "local_read_write",
            "availability_dependencies": ["python3"],
            "expected_output": {"kind": "exit_code", "value": 0},
            "risk_tags": [],
            "risk_waiver": None,
        })
        round_tripped = to_plain(contract_from_dict(data, strict=True))
        for key in ("cwd", "mutation_class", "availability_dependencies", "expected_output", "risk_tags", "risk_waiver"):
            self.assertEqual(round_tripped["phases"][0]["commands"][0][key], command[key])

    def test_dedicated_quality_gate_schema_is_closed(self):
        schema = json.loads((ROOT / "spec/quality-gate.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        gate = valid_quality_contract()["compatibility"]["quality_gate_v1"]
        validator = Draft202012Validator(schema)
        self.assertEqual(list(validator.iter_errors(gate)), [])
        gate["shadow_authority"] = {}
        self.assertTrue(list(validator.iter_errors(gate)))

    def test_frozen_fixture_cli_rejects_every_false_green(self):
        result = subprocess.run(
            [sys.executable, "quality/run.py", "lint-fixtures"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["fixtures"], 5)
        self.assertEqual(report["rejected"], 5)
        self.assertEqual(report["unexpected_passes"], [])

    def test_quality_lint_cli_is_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            path.write_text(json.dumps(valid_quality_contract()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/sgctl.py", "quality-lint", str(path), "--format", "json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "plan-quality-lint-v1")
        self.assertEqual(payload["status"], "green")
        self.assertEqual(payload["findings"], [])

    def test_projection_rejects_missing_attestation(self):
        contract = {
            "compatibility": {
                "quality_gate_v1": {"subject": {"requirements": []}}
            }
        }
        with self.assertRaisesRegex(ValueError, "attestation"):
            plan_subject_projection(copy.deepcopy(contract))


if __name__ == "__main__":
    unittest.main()
