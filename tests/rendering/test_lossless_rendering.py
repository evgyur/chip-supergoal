from __future__ import annotations

from copy import deepcopy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import compile_contract_file
from chip_supergoal.model import canonical_json, contract_from_dict
from chip_supergoal.render import (
    render_launch_goal,
    render_loop_design,
    render_phase,
    render_roadmap,
    render_state,
    render_thinking,
)
from chip_supergoal.research import (
    render_research_markdown,
    research_gate,
    research_report,
    research_required,
)
from chip_supergoal.validate import validate_package, validate_phase_markdown


def rich_contract_data() -> dict:
    return {
        "schema_version": "3.0",
        "protocol_version": "3.0",
        "contract_revision": 7,
        "profile": "public-clean",
        "goal": {
            "id": "sg-20260711-lossless-rendering",
            "title": "Lossless rendering fixture",
            "objective": "Render every execution contract field without information loss",
            "request_digest": "1" * 64,
            "workspace_root": "workspace/project",
            "owner": "fixture-owner",
            "non_goals": ["Do not deploy", "Do not publish"],
            "done_condition": "Every declared verifier passes with direct evidence",
            "created_at": "2026-07-11T00:00:00Z",
        },
        "source_set": [
            {
                "id": "SRC-001",
                "kind": "user_brief",
                "locator": "briefs/fixture.md",
                "authority": "user_request",
                "freshness": "2026-07-11",
                "sensitivity": "public",
                "sha256": "2" * 64,
                "used_by": ["P01", "P02"],
            }
        ],
        "decisions": [
            {
                "id": "DEC-001",
                "summary": "Preserve declared structure",
                "rationale": {"rank": 1, "alternatives": ["lossy", "manual"]},
            }
        ],
        "architecture": {
            "source_of_truth": ["CONTRACT.json"],
            "components": {"renderer": {"language": "python", "mode": "deterministic"}},
            "assumptions": ["The package is read from disk"],
            "baseline": {"kind": "git_ref", "ref": "fixture-baseline-abc123"},
            "rollback": {
                "method": "restore_git_ref",
                "target": "fixture-baseline-abc123",
            },
        },
        "loop": {
            "host_model": "declared host",
            "reviewer": "declared reviewer",
            "judge": "declared judge",
            "verification_gates": ["run declared command verifiers"],
            "state_checkpoints": ["use the authoritative runtime state"],
            "stop_conditions": ["stop after 4 declared repair attempts"],
            "max_iterations": 4,
            "audit_rounds": 2,
            "boundaries": ["stay inside the declared workspace"],
            "failure_recovery": [{"mode": "retry", "limit": 4}],
            "extension": {"z": [3, 2, 1], "a": True},
        },
        "risks": [
            {
                "id": "RISK-001",
                "tag": "archive",
                "severity": "P2",
                "mitigation": "Run path-safety tests",
            }
        ],
        "approvals": [
            {
                "id": "APR-001",
                "class_name": "fixture-review",
                "scope": "P02",
                "required": True,
            },
            {
                "id": "APR-002",
                "class_name": "informational",
                "scope": "report-only",
                "required": False,
            },
        ],
        "phases": [
            {
                "id": "P01",
                "ordinal": 1,
                "name": "Render contract",
                "task": "Emit a lossless executor view",
                "depends_on": [],
                "work_items": [
                    {
                        "id": "P01-W01",
                        "text": "Render nested structures",
                        "details": {"order": ["sources", "phases"]},
                    }
                ],
                "deliverables": [
                    {
                        "id": "P01-D01",
                        "kind": "file",
                        "path": "out/executor-view.md",
                        "change_expectation": "created_or_modified",
                        "verification": "sha256_and_semantic_parse",
                    }
                ],
                "criteria": [
                    {
                        "id": "P01-C01",
                        "statement": "The executor view contains every declared field",
                        "verifier": {
                            "type": "test",
                            "command_id": "P01-CMD01",
                            "expected_exit": 0,
                            "expected_assertion": "mutation table passes",
                        },
                        "evidence_tier": "direct_artifact",
                        "blocking": True,
                    }
                ],
                "commands": [
                    {
                        "id": "P01-CMD01",
                        "command": "python -m unittest tests.rendering.test_lossless_rendering",
                        "purpose": "prove lossless rendering",
                        "safety": "local_read_only",
                        "timeout_seconds": 41,
                    },
                    {
                        "id": "P01-CMD02",
                        "command": "python scripts/sgctl.py validate-package . --strict",
                        "purpose": "prove package consistency",
                        "safety": "local_read_only",
                        "timeout_seconds": 42,
                    },
                ],
                "risk_tags": ["archive"],
                "rpd": {
                    "required": True,
                    "focus": [
                        "security",
                        "integration",
                        "ux",
                        "migration",
                        "data-loss",
                        "gateway",
                        "payments",
                    ],
                },
            },
            {
                "id": "P02",
                "ordinal": 2,
                "name": "Audit rendered contract",
                "task": "Audit every declared deliverable and verifier",
                "depends_on": ["P01"],
                "work_items": [{"id": "P02-W01", "text": "Audit the rendered bytes"}],
                "deliverables": [
                    {
                        "id": "P02-D01",
                        "kind": "report",
                        "path": "reports/render-audit.json",
                        "change_expectation": "created",
                        "verification": "json_schema",
                    }
                ],
                "criteria": [
                    {
                        "id": "P02-C01",
                        "statement": "The final audit identifies every blocking criterion",
                        "verifier": {
                            "type": "assertion",
                            "expected_assertion": "all blocking criteria are present",
                        },
                        "evidence_tier": "direct_artifact",
                        "blocking": True,
                    }
                ],
                "commands": [
                    {
                        "id": "P02-CMD01",
                        "command": "python scripts/sgctl.py validate-package . --strict",
                        "purpose": "validate the final package",
                        "safety": "local_read_only",
                        "timeout_seconds": 43,
                    }
                ],
                "risk_tags": [],
                "rpd": {"required": False, "focus": []},
            },
        ],
        "delivery": {
            "items": [{"id": "DEL-001", "path": "out/executor-view.md"}],
            "transport": "none",
            "review_pack_required": False,
            "receipt_policy": {"required": False, "format": "json"},
        },
        "compatibility": {
            "goalmanager_contract": ">=documented-v3",
            "extension": {"nested": ["alpha", {"beta": 2}]},
            "research_gate": {
                "required": False,
                "status": "not_required",
                "provider": "manual",
                "query": "lossless rendering fixture research",
                "summary": "Research is included only to exercise deterministic rendering of the declared record.",
                "sources": [
                    {
                        "provider": "manual",
                        "title": "Fixture source",
                        "locator": "notes/research.txt",
                        "extra": {"rank": 1},
                    }
                ],
                "planning_implications": ["Preserve the entire research object"],
                "skipped_reason": "The fixture declares that external research is unnecessary",
            },
        },
    }


def rendered_views(data: dict) -> dict[str, bytes]:
    contract = contract_from_dict(data)
    views = {
        "THINKING.md": render_thinking(contract).encode("utf-8"),
        "LOOP_DESIGN.md": render_loop_design(contract).encode("utf-8"),
        "ROADMAP.md": render_roadmap(contract).encode("utf-8"),
        "LAUNCH_GOAL.md": render_launch_goal(contract).encode("utf-8"),
    }
    for index in range(len(contract.phases)):
        views[f"phases/phase-{index + 1:02d}.md"] = render_phase(contract, index).encode(
            "utf-8"
        )
    if research_required(contract) or research_gate(contract):
        views["RESEARCH.md"] = render_research_markdown(contract).encode("utf-8")
    return views


def set_path(data: dict, path: tuple[object, ...], value: object) -> None:
    target: object = data
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]


class LosslessRenderingTest(unittest.TestCase):
    def test_each_execution_significant_mutation_changes_a_generated_view(self):
        baseline_data = rich_contract_data()
        baseline = rendered_views(baseline_data)
        cases = [
            ("contract revision", ("contract_revision",), 71),
            ("profile", ("profile",), "MUTATED-profile"),
            ("goal id", ("goal", "id"), "MUTATED-goal-id"),
            ("goal title", ("goal", "title"), "MUTATED goal title"),
            ("goal objective", ("goal", "objective"), "MUTATED objective"),
            ("goal digest", ("goal", "request_digest"), "4" * 64),
            ("goal workspace", ("goal", "workspace_root"), "MUTATED/workspace"),
            ("goal owner", ("goal", "owner"), "MUTATED-owner"),
            ("goal non-goals", ("goal", "non_goals"), ["MUTATED non-goal"]),
            ("goal done condition", ("goal", "done_condition"), "MUTATED done condition"),
            ("goal created at", ("goal", "created_at"), "MUTATED-created-at"),
            ("source id", ("source_set", 0, "id"), "SRC-MUTATED"),
            ("source kind", ("source_set", 0, "kind"), "MUTATED-kind"),
            ("source locator", ("source_set", 0, "locator"), "MUTATED/locator"),
            ("source authority", ("source_set", 0, "authority"), "MUTATED-authority"),
            ("source freshness", ("source_set", 0, "freshness"), "MUTATED-freshness"),
            ("source sensitivity", ("source_set", 0, "sensitivity"), "MUTATED-sensitivity"),
            ("source hash", ("source_set", 0, "sha256"), "3" * 64),
            ("source used-by", ("source_set", 0, "used_by"), ["MUTATED-used-by"]),
            ("decisions", ("decisions",), [{"id": "MUTATED-decision", "arbitrary": [3, 1]}]),
            ("architecture", ("architecture",), {"MUTATED-architecture": {"z": 9}}),
            ("baseline", ("architecture", "baseline", "ref"), "MUTATED-baseline-ref"),
            ("rollback", ("architecture", "rollback", "method"), "MUTATED-rollback-method"),
            ("loop", ("loop", "extension"), {"MUTATED-loop": [False, 8]}),
            ("risk id", ("risks", 0, "id"), "MUTATED-risk-id"),
            ("risk", ("risks", 0, "tag"), "MUTATED-risk-tag"),
            ("risk severity", ("risks", 0, "severity"), "MUTATED-risk-severity"),
            ("risk mitigation", ("risks", 0, "mitigation"), "MUTATED-risk-mitigation"),
            ("phase id", ("phases", 0, "id"), "MUTATED-phase-id"),
            ("phase ordinal", ("phases", 0, "ordinal"), 17),
            ("phase name", ("phases", 0, "name"), "MUTATED phase name"),
            ("phase task", ("phases", 0, "task"), "MUTATED phase task"),
            ("phase risk tags", ("phases", 0, "risk_tags"), ["MUTATED-phase-risk"]),
            ("dependency", ("phases", 1, "depends_on"), ["MUTATED-dependency"]),
            ("work item", ("phases", 0, "work_items"), [{"id": "MUTATED-work", "nested": [1, 2]}]),
            ("deliverable id", ("phases", 0, "deliverables", 0, "id"), "MUTATED-deliverable-id"),
            ("deliverable kind", ("phases", 0, "deliverables", 0, "kind"), "MUTATED-deliverable-kind"),
            ("deliverable path", ("phases", 0, "deliverables", 0, "path"), "MUTATED/deliverable"),
            ("deliverable expectation", ("phases", 0, "deliverables", 0, "change_expectation"), "MUTATED-expectation"),
            ("deliverable verification", ("phases", 0, "deliverables", 0, "verification"), "MUTATED-verification"),
            ("criterion blocking", ("phases", 0, "criteria", 0, "blocking"), False),
            ("criterion id", ("phases", 0, "criteria", 0, "id"), "MUTATED-criterion-id"),
            ("criterion statement", ("phases", 0, "criteria", 0, "statement"), "MUTATED criterion statement"),
            ("criterion tier", ("phases", 0, "criteria", 0, "evidence_tier"), "MUTATED-tier"),
            ("verifier type", ("phases", 0, "criteria", 0, "verifier", "type"), "MUTATED-verifier-type"),
            ("verifier command", ("phases", 0, "criteria", 0, "verifier", "command_id"), "P01-CMD02"),
            ("verifier exit", ("phases", 0, "criteria", 0, "verifier", "expected_exit"), 17),
            ("verifier assertion", ("phases", 0, "criteria", 0, "verifier", "expected_assertion"), "MUTATED-assertion"),
            ("command text", ("phases", 0, "commands", 0, "command"), "MUTATED command text"),
            ("command id", ("phases", 0, "commands", 0, "id"), "MUTATED-command-id"),
            ("command purpose", ("phases", 0, "commands", 0, "purpose"), "MUTATED-purpose"),
            ("command safety", ("phases", 0, "commands", 0, "safety"), "MUTATED-safety"),
            ("command timeout", ("phases", 0, "commands", 0, "timeout_seconds"), 99),
            ("RPD focuses", ("phases", 0, "rpd", "focus"), ["MUTATED-focus-a", "MUTATED-focus-b"]),
            ("RPD required", ("phases", 0, "rpd", "required"), False),
            ("approval id", ("approvals", 0, "id"), "MUTATED-approval-id"),
            ("approval class", ("approvals", 0, "class_name"), "MUTATED-approval-class"),
            ("approval scope", ("approvals", 0, "scope"), "MUTATED-approval-scope"),
            ("approval required", ("approvals", 0, "required"), False),
            ("delivery", ("delivery", "receipt_policy"), {"MUTATED-delivery": [1, 2]}),
            ("compatibility", ("compatibility", "extension"), {"MUTATED-compatibility": True}),
            ("research", ("compatibility", "research_gate", "summary"), "MUTATED research summary"),
        ]

        for label, path, value in cases:
            with self.subTest(label=label):
                mutated_data = deepcopy(baseline_data)
                set_path(mutated_data, path, value)
                mutated = rendered_views(mutated_data)
                changed = {name for name in baseline if baseline[name] != mutated.get(name)}
                self.assertTrue(changed, f"{label} did not affect generated executor bytes")
                rendered = b"\n".join(mutated.values()).decode("utf-8")
                semantic_values = value if isinstance(value, list) else [value]
                for semantic_value in semantic_values:
                    if isinstance(semantic_value, bool):
                        self.assertIn(json.dumps(semantic_value), rendered, label)
                    elif isinstance(semantic_value, (str, int)):
                        self.assertIn(str(semantic_value), rendered, label)
                    elif isinstance(semantic_value, dict):
                        for key in semantic_value:
                            self.assertIn(str(key), rendered, label)

    def test_phase_and_roadmap_expose_full_audit_contract(self):
        contract = contract_from_dict(rich_contract_data())
        phase = render_phase(contract, 0)
        roadmap = render_roadmap(contract)

        for value in [
            "P01-D01",
            "out/executor-view.md",
            "created_or_modified",
            "sha256_and_semantic_parse",
            "P01-C01",
            "direct_artifact",
            "P01-CMD01",
            "expected_exit",
            "expected_assertion",
            "prove lossless rendering",
            "local_read_only",
            "timeout_seconds",
        ]:
            self.assertIn(value, phase)
            self.assertIn(value, roadmap)

        for focus in rich_contract_data()["phases"][0]["rpd"]["focus"]:
            self.assertIn(focus, phase)
            self.assertIn(focus, roadmap)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "phase.md"
            path.write_text(phase, encoding="utf-8")
            self.assertEqual(validate_phase_markdown(path), [])

    def test_declared_baseline_and_rollback_are_lossless_not_defaults(self):
        contract = contract_from_dict(rich_contract_data())
        thinking = render_thinking(contract)
        roadmap = render_roadmap(contract)
        for value in [
            '"kind": "git_ref"',
            '"ref": "fixture-baseline-abc123"',
            '"method": "restore_git_ref"',
            '"target": "fixture-baseline-abc123"',
        ]:
            self.assertIn(value, thinking)
            self.assertIn(value, roadmap)

    def test_phase_with_no_declared_criteria_keeps_zero_count_semantics(self):
        data = rich_contract_data()
        data["phases"][0]["criteria"] = []
        phase = render_phase(contract_from_dict(data), 0)
        self.assertIn("Acceptance criteria: 0", phase)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "phase.md"
            path.write_text(phase, encoding="utf-8")
            self.assertEqual(validate_phase_markdown(path), [])

    def test_optional_execution_fields_render_as_explicit_null_when_absent(self):
        data = rich_contract_data()
        data["goal"].pop("created_at")
        data["source_set"][0].pop("sha256")
        contract = contract_from_dict(data)

        self.assertIn('"created_at": null', render_thinking(contract))
        self.assertIn('"sha256": null', render_thinking(contract))
        second_phase = render_phase(contract, 1)
        self.assertIn('"command_id": null', second_phase)
        self.assertIn('"expected_exit": null', second_phase)

    def test_package_validator_detects_contract_to_view_drift(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = parent / "contract.json"
            source.write_text(json.dumps(rich_contract_data()), encoding="utf-8")
            package = compile_contract_file(source, parent / "package")

            mutated = json.loads((package / "CONTRACT.json").read_text(encoding="utf-8"))
            mutated["phases"][0]["deliverables"][0]["path"] = "MUTATED/drift.txt"
            (package / "CONTRACT.json").write_text(
                canonical_json(contract_from_dict(mutated)), encoding="utf-8", newline="\n"
            )

            drift = [
                item
                for item in validate_package(package)
                if item.code == "SGV-PACKAGE-GENERATED-DRIFT"
            ]
            self.assertTrue(drift)
            self.assertTrue(
                any(item.pointer in {"/ROADMAP.md", "/phases/phase-01.md"} for item in drift),
                [item.pointer for item in drift],
            )

    def test_public_clean_views_have_no_undeclared_operator_fallbacks(self):
        data = rich_contract_data()
        data["compatibility"] = {}
        rendered = b"\n".join(rendered_views(data).values()).decode("utf-8").lower()
        rendered += (ROOT / "templates" / "PROTOCOL.md").read_text(encoding="utf-8").lower()
        for forbidden in [
            "telegram",
            "cron",
            "historical eval before recurring rollout",
            "reversible production activation",
            "workspace is non-git",
            "private data and secrets stay out",
            "memory_saved",
            "chat memory",
        ]:
            self.assertNotIn(forbidden, rendered)

    def test_research_view_does_not_invent_tool_fallbacks(self):
        research = render_research_markdown(contract_from_dict(rich_contract_data()))
        self.assertIn("manual", research)
        self.assertIn("notes/research.txt", research)
        for forbidden in ["Skill `perplex`", "Official docs / Context7", "Generic web search"]:
            self.assertNotIn(forbidden, research)

    def test_optional_research_record_does_not_invent_provider_or_query(self):
        data = rich_contract_data()
        data["compatibility"]["research_gate"] = {
            "required": False,
            "status": "not_required",
        }
        report = research_report(contract_from_dict(data))
        self.assertEqual(report["provider"], "")
        self.assertEqual(report["query"], "")

    def test_launch_is_relocatable_and_research_context_is_conditional(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = parent / "contract.json"
            source.write_text(json.dumps(rich_contract_data()), encoding="utf-8")
            original = compile_contract_file(source, parent / "nested" / "first" / "package")
            launch = (original / "LAUNCH_GOAL.md").read_text(encoding="utf-8")

            self.assertNotIn(str(original.resolve()), launch)
            self.assertNotIn(".supergoal", launch)
            self.assertIn("parent directory of the LAUNCH_GOAL.md being executed", launch)
            for required in [
                "CONTRACT.json",
                "RESEARCH.md",
                "python scripts/sgctl.py validate-package . --strict",
                "python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated",
                "python scripts/sgctl.py validate-phase-markdown phases/phase-01.md",
                "python scripts/sgctl.py validate-phase-markdown phases/phase-02.md",
                "Delivery boundary",
                "Approval boundary",
                "AUDIT_COMPLETE",
                "SUPERGOAL_RUN_COMPLETE",
                "Goal complete: yes",
            ]:
                self.assertIn(required, launch)
            self.assertEqual(launch.count("SUPERGOAL_GOAL_BODY:"), 1)

            relocated = parent / "elsewhere" / "renamed-package"
            shutil.copytree(original, relocated)
            self.assertEqual(validate_package(relocated), [])
            self.assertEqual(
                (relocated / "LAUNCH_GOAL.md").read_bytes(),
                (original / "LAUNCH_GOAL.md").read_bytes(),
            )

            without_research = rich_contract_data()
            without_research["compatibility"] = {"goalmanager_contract": ">=documented-v3"}
            contract = contract_from_dict(without_research)
            self.assertNotIn("RESEARCH.md", render_launch_goal(contract))

    def test_protocol_is_python_authoritative_and_state_is_a_projection(self):
        protocol = (ROOT / "templates" / "PROTOCOL.md").read_text(encoding="utf-8")
        state_template = (ROOT / "templates" / "STATE.md").read_text(encoding="utf-8")
        executor_templates = "\n".join(
            (ROOT / "templates" / name).read_text(encoding="utf-8")
            for name in ["PROTOCOL.md", "LAUNCH_GOAL.md", "STATE.md", "phase-goal.txt"]
        )

        for command in [
            "python scripts/sgctl.py validate-package . --strict",
            "python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md",
            "python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md",
            "python scripts/sgctl.py state-show",
            "python scripts/sgctl.py state-transition",
            "python scripts/sgctl.py state-recover",
            "python scripts/sgctl.py record-evidence",
            "python scripts/sgctl.py audit",
            "python scripts/sgctl.py finalize",
            "python scripts/sgctl.py validate-terminal",
        ]:
            self.assertIn(command, protocol)
        self.assertIn("## Optional Unix compatibility notes", protocol)
        self.assertIn(
            "bash scripts/validate-loop-design.sh --instantiated LOOP_DESIGN.md",
            protocol,
        )
        self.assertIn("bash scripts/validate-phase.sh phases/phase-NN.md", protocol)
        self.assertNotIn("bash .supergoal", protocol)
        self.assertNotIn(".supergoal/", protocol)
        self.assertNotIn(".supergoal/", executor_templates)
        self.assertIn("runtime/STATE.json", protocol)
        self.assertIn("authoritative runtime state", protocol)
        self.assertIn("projection", protocol)
        self.assertIn("protocol prose is not authority", protocol.lower())
        self.assertNotIn("not-yet-implemented Task 5", protocol)

        self.assertIn("runtime/STATE.json", state_template)
        self.assertIn("authority", state_template.lower())
        self.assertIn("projection", state_template.lower())
        self.assertNotIn("append", state_template.lower())
        rendered_state = render_state(contract_from_dict(rich_contract_data()))
        self.assertIn("runtime/STATE.json", rendered_state)
        self.assertNotIn("non-git", rendered_state.lower())


if __name__ == "__main__":
    unittest.main()
