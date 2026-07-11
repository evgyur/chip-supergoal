import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_package
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.evidence import (
    EvidenceRecord,
    EvidenceStore,
    evidence_json_bytes,
    read_evidence,
)
from chip_supergoal.events import (
    append_event,
    canonical_state_bytes,
    event_hash,
    read_events,
    verify_event_chain,
)
from chip_supergoal.state import State, StateStore, read_state, render_state_md, write_state_atomic
from chip_supergoal.terminal import finalize_package, validate_terminal_package
from chip_supergoal.validate import validate_package


class RuntimeMutationSafetyTest(unittest.TestCase):
    def directory_link(self, link: Path, target: Path) -> None:
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: {result.stderr}")
        else:
            link.symlink_to(target, target_is_directory=True)

    def remove_directory_link(self, link: Path) -> None:
        if not os.path.lexists(link):
            return
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()

    def package(self, *, two_phases=False, policy=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["profile"] = "chip-private" if policy else "public-clean"
        if not policy:
            data["risks"] = []
        data["delivery"] = {}
        if not policy:
            data["compatibility"].pop("research_gate", None)
        phase = data["phases"][0]
        if not policy:
            phase["risk_tags"] = []
            phase["rpd"] = {"required": False, "focus": []}
        if two_phases:
            second = deepcopy(phase)
            second.update(
                {
                    "id": "P02",
                    "ordinal": 2,
                    "name": "Second phase",
                    "depends_on": ["P01"],
                }
            )
            second["commands"][0]["id"] = "P02-CMD01"
            second["criteria"][0]["id"] = "P02-C01"
            second["criteria"][0]["verifier"]["command_id"] = "P02-CMD01"
            second["deliverables"][0]["id"] = "P02-D01"
            second["deliverables"][0]["path"] = "fixture-2.txt"
            second["work_items"][0]["id"] = "P02-W01"
            data["phases"].append(second)
        source = parent / "contract.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        root = parent / "package"
        compile_contract_file(
            source,
            root,
            template_protocol=ROOT / "templates/PROTOCOL.md",
            resource_root=ROOT,
        )
        return root

    def progress(self, root, *, auditing=False):
        store = StateStore(root)
        revision = 1
        lifecycles = [
            "PLAN_REVIEWED",
            "PREFLIGHT_GREEN",
            "READY_TO_DISPATCH",
            "RUNNING",
        ]
        if auditing:
            lifecycles.append("AUDITING")
        for lifecycle in lifecycles:
            state = store.transition(
                lifecycle,
                expected_revision=revision,
                phase_status="EXECUTING" if lifecycle == "RUNNING" else None,
            )
            revision = state.state_revision
            if lifecycle == "RUNNING" and auditing:
                state = store.update(
                    expected_revision=revision, phase_status="COMPLETE"
                )
                revision = state.state_revision
        return state

    def record(self, root, evidence_id, *, result="pass"):
        contract_bytes = (root / "CONTRACT.json").read_bytes()
        contract = json.loads(contract_bytes)
        state = read_state(root / "runtime/STATE.json", root=root)
        command = contract["phases"][0]["commands"][0]
        criterion = contract["phases"][0]["criteria"][0]
        timestamp = read_events(root / "runtime/events.jsonl", root=root)[-1][
            "timestamp"
        ]
        return EvidenceRecord(
            evidence_id=evidence_id,
            goal_id=state.goal_id,
            contract_sha256=hashlib.sha256(contract_bytes).hexdigest(),
            contract_revision=state.contract_revision,
            phase_id="P01",
            criterion_id="P01-C01",
            type="command_result",
            producer="concurrency-test",
            captured_at=timestamp,
            fresh_until="audit_end",
            replayable=True,
            result=result,
            redaction="passed",
            command=command["command"],
            exit_code=(criterion["verifier"]["expected_exit"] if result == "pass" else 1),
            assertion=criterion["verifier"]["expected_assertion"],
        )

    def test_concurrent_unique_appends_are_lossless_and_canonical(self):
        root = self.package()
        self.progress(root)
        records = [self.record(root, f"EVD-{index:06d}") for index in range(1, 17)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(EvidenceStore(root).append, records))
        self.assertEqual(len(results), 16)
        stored = read_evidence(root / "runtime/evidence.json", root=root)
        self.assertEqual(
            [item.evidence_id for item in stored],
            sorted(item.evidence_id for item in records),
        )

    def test_duplicate_id_race_accepts_exactly_one_writer(self):
        root = self.package()
        self.progress(root)
        record = self.record(root, "EVD-DUPLICATE")

        def append():
            try:
                EvidenceStore(root).append(record)
                return "accepted"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: append(), range(2)))
        self.assertEqual(sorted(outcomes), ["accepted", "rejected"])
        self.assertEqual(len(read_evidence(root / "runtime/evidence.json", root=root)), 1)

    def test_evidence_mutation_invalidates_derived_audit(self):
        root = self.package()
        self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        report = audit_package(root)
        self.assertTrue(report.can_complete, report.issues)
        self.assertTrue((root / "reports/final-audit.json").is_file())
        EvidenceStore(root).append(
            self.record(root, "EVD-000002", result="fail")
        )
        self.assertFalse((root / "reports/final-audit.json").exists())
        self.assertFalse((root / "reports/final-audit.md").exists())

    def test_auditing_state_cannot_regress_completed_phase_or_add_blocker(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        self.assertTrue(audit_package(root).can_complete)
        store = StateStore(root)
        with self.assertRaisesRegex(ValueError, "ILLEGAL-UPDATE|JOURNAL-CORRUPT"):
            store.update(
                expected_revision=auditing.state_revision,
                phase_status="PENDING",
            )
        with self.assertRaisesRegex(ValueError, "ILLEGAL-UPDATE|JOURNAL-CORRUPT"):
            store.update(
                expected_revision=auditing.state_revision,
                blocker={"reason": "forged"},
            )
        current = read_state(root / "runtime/STATE.json", root=root)
        self.assertEqual(current.phase_status, "COMPLETE")
        self.assertIsNone(current.blocker)
        self.assertTrue((root / "reports/final-audit.json").is_file())

    def test_dependency_ready_phase_advance_is_journalled_and_fail_closed(self):
        root = self.package(two_phases=True)
        running = self.progress(root)
        store = StateStore(root)
        with self.assertRaisesRegex(ValueError, "dependencies"):
            store.update(
                expected_revision=running.state_revision,
                phase_id="P02",
                phase_status="PENDING",
            )
        completed = store.update(
            expected_revision=running.state_revision,
            phase_status="COMPLETE",
        )
        advanced = store.update(
            expected_revision=completed.state_revision,
            phase_id="P02",
            phase_status="PENDING",
            attempt=1,
        )
        self.assertEqual(advanced.current_phase_id, "P02")
        self.assertEqual(advanced.attempt, 1)
        self.assertEqual(read_events(store.events, root=root)[-1]["event_type"], "state_update")

    def test_audit_transition_requires_every_phase_complete(self):
        root = self.package()
        running = self.progress(root)
        with self.assertRaisesRegex(ValueError, "phase.*complete"):
            StateStore(root).transition(
                "AUDITING", expected_revision=running.state_revision
            )

    def test_audit_remediation_can_reopen_any_completed_phase(self):
        root = self.package(two_phases=True)
        store = StateStore(root)
        running = self.progress(root)
        phase_one = store.update(
            expected_revision=running.state_revision,
            phase_status="COMPLETE",
        )
        phase_two = store.update(
            expected_revision=phase_one.state_revision,
            phase_id="P02",
            phase_status="EXECUTING",
        )
        phase_two = store.update(
            expected_revision=phase_two.state_revision,
            phase_status="COMPLETE",
        )
        with self.assertRaisesRegex(ValueError, "already complete|advance"):
            store.update(
                expected_revision=phase_two.state_revision,
                phase_id="P01",
                phase_status="EXECUTING",
            )
        auditing = store.transition(
            "AUDITING", expected_revision=phase_two.state_revision
        )
        reopened = store.transition(
            "RUNNING",
            expected_revision=auditing.state_revision,
            phase_id="P01",
            phase_status="EXECUTING",
        )
        self.assertEqual(reopened.current_phase_id, "P01")
        self.assertEqual(reopened.phase_status, "EXECUTING")
        phase_one_redone = store.update(
            expected_revision=reopened.state_revision,
            phase_status="COMPLETE",
        )
        with self.assertRaisesRegex(ValueError, "all declared phases"):
            store.transition(
                "AUDITING", expected_revision=phase_one_redone.state_revision
            )
        phase_two_redone = store.update(
            expected_revision=phase_one_redone.state_revision,
            phase_id="P02",
            phase_status="EXECUTING",
        )
        phase_two_redone = store.update(
            expected_revision=phase_two_redone.state_revision,
            phase_status="COMPLETE",
        )
        auditing_again = store.transition(
            "AUDITING", expected_revision=phase_two_redone.state_revision
        )
        self.assertEqual(auditing_again.audit_round, 2)

    def test_contract_bound_genesis_requires_lowest_ordinal_ready_phase(self):
        root = self.package(two_phases=True)
        initial = read_state(root / "runtime/STATE.json", root=root)
        for path in (
            root / "runtime/events.jsonl",
            root / "runtime/STATE.json",
            root / "STATE.md",
        ):
            path.unlink()
        forged = State.from_dict(
            {**initial.to_dict(), "current_phase_id": "P02"}
        )
        with self.assertRaisesRegex(ValueError, "GENESIS-INVALID"):
            StateStore(root).initialize(forged)

    def test_rehashed_noncanonical_genesis_and_noop_update_are_rejected(self):
        root = self.package(two_phases=True)
        genesis = deepcopy(read_events(root / "runtime/events.jsonl", root=root)[0])
        genesis["phase_id"] = "P02"
        genesis["state"]["current_phase_id"] = "P02"
        genesis["state_sha256"] = hashlib.sha256(
            canonical_state_bytes(genesis["state"])
        ).hexdigest()
        genesis["event_sha256"] = event_hash(genesis)
        genesis_errors = verify_event_chain(
            [genesis],
            phase_ids={"P01", "P02"},
            phase_dependencies={"P01": set(), "P02": {"P01"}},
            phase_ordinals={"P01": 1, "P02": 2},
        )
        self.assertTrue(
            any("canonical genesis" in error for error in genesis_errors),
            genesis_errors,
        )

        running = self.progress(root)
        events = read_events(root / "runtime/events.jsonl", root=root)
        forged_update = deepcopy(events[-1])
        forged_update["event_id"] = f"EVT-{len(events) + 1:06d}"
        forged_update["prev_event_sha256"] = events[-1]["event_sha256"]
        forged_update["state_revision"] += 1
        forged_update["state"]["state_revision"] += 1
        forged_update["event_type"] = "state_update"
        forged_update["state_sha256"] = hashlib.sha256(
            canonical_state_bytes(forged_update["state"])
        ).hexdigest()
        forged_update["event_sha256"] = event_hash(forged_update)
        noop_errors = verify_event_chain([*events, forged_update])
        self.assertTrue(
            any("no-op" in error for error in noop_errors),
            noop_errors,
        )

    def test_state_store_rejects_same_valued_semantic_noop(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        before = (root / "runtime/events.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "ILLEGAL-UPDATE|NOOP"):
            StateStore(root).update(
                expected_revision=auditing.state_revision,
                phase_id=auditing.current_phase_id,
                phase_status=auditing.phase_status,
                blocker=auditing.blocker,
                attempt=auditing.attempt,
            )
        self.assertEqual((root / "runtime/events.jsonl").read_bytes(), before)

    def test_validator_uses_strict_json_types_for_state_projection_identity(self):
        root = self.package()
        running = self.progress(root)
        authoritative = StateStore(root).update(
            expected_revision=running.state_revision,
            blocker={"retryable": 1},
        )
        forged = State.from_dict(
            {**authoritative.to_dict(), "blocker": {"retryable": True}}
        )
        (root / "runtime/STATE.json").write_bytes(
            canonical_state_bytes(forged.to_dict())
        )
        (root / "STATE.md").write_text(
            render_state_md(forged), encoding="utf-8", newline="\n"
        )
        diagnostics = validate_package(root)
        self.assertTrue(
            any(
                item.code == "SGV-PACKAGE-STATE-RECOVERY-REQUIRED"
                for item in diagnostics
            ),
            diagnostics,
        )

    def test_package_validator_rejects_invented_policy_evidence_metadata(self):
        root = self.package()
        self.progress(root)
        forged = EvidenceRecord.from_dict(
            {
                **self.record(root, "EVD-INVENTED-POLICY").to_dict(),
                "metadata": {"policy_evidence": ["invented-policy-label"]},
            }
        )
        (root / "runtime/evidence.json").write_bytes(
            evidence_json_bytes([forged])
        )
        diagnostics = validate_package(root)
        self.assertTrue(
            any(
                item.code == "SGV-PACKAGE-EVIDENCE-MALFORMED"
                for item in diagnostics
            ),
            diagnostics,
        )

    def test_terminal_freezes_mutations_and_concurrent_finalize_is_identical(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        self.assertTrue(audit_package(root).can_complete)
        done = StateStore(root).transition(
            "DONE", expected_revision=auditing.state_revision
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(lambda _: finalize_package(root), range(2)))
        self.assertEqual(records[0], records[1])
        with self.assertRaisesRegex(ValueError, "TERMINAL-FROZEN"):
            StateStore(root).update(
                expected_revision=done.state_revision,
                phase_status="MUTATED",
            )
        with self.assertRaisesRegex(ValueError, "TERMINAL-FROZEN"):
            EvidenceStore(root).append(self.record(root, "EVD-000002"))
        with self.assertRaisesRegex(ValueError, "TERMINAL-FROZEN"):
            audit_package(root)

    def test_audit_rejects_tampered_sealed_risk_policy(self):
        root = self.package(policy=True)
        self.progress(root, auditing=True)
        record = self.record(root, "EVD-000001")
        record = EvidenceRecord.from_dict(
            {
                **record.to_dict(),
                "metadata": {"rpd_focus": ["security", "integration"]},
            }
        )
        EvidenceStore(root).append(record)
        policy_path = root / "spec/risk-policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["risk_tags"]["auth"]["mandatory_evidence"] = []
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaisesRegex(ValueError, "sealed artifact"):
            audit_package(root)

    def test_sealed_drift_blocks_done_and_invalidates_existing_terminal(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        self.assertTrue(audit_package(root).can_complete)
        original = (root / "THINKING.md").read_bytes()
        (root / "THINKING.md").write_bytes(original + b"tampered\n")
        drifted = audit_package(root)
        self.assertFalse(drifted.can_complete)
        self.assertIn(
            "AUDIT_CORRUPTION", {issue.issue_type for issue in drifted.issues}
        )
        with self.assertRaisesRegex(ValueError, "DONE-REQUIRES-AUDIT"):
            StateStore(root).transition(
                "DONE", expected_revision=auditing.state_revision
            )

        (root / "THINKING.md").write_bytes(original)
        self.assertTrue(audit_package(root).can_complete)
        done = StateStore(root).transition(
            "DONE", expected_revision=auditing.state_revision
        )
        finalize_package(root)
        (root / "THINKING.md").write_bytes(original + b"tampered-after-finalize\n")
        with self.assertRaises(Exception):
            validate_terminal_package(root)
        self.assertEqual(done.phase_status, "COMPLETE")

    def test_missing_manifest_fails_closed_for_runtime_authority(self):
        root = self.package()
        self.progress(root, auditing=True)
        (root / "MANIFEST.json").unlink()
        with self.assertRaisesRegex(ValueError, "MANIFEST|manifest"):
            audit_package(root)

    def test_audit_write_rejects_symlink_or_junction_parent_escape(self):
        root = self.package()
        self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        reports = root / "reports"
        if reports.exists():
            shutil.rmtree(reports)
        outside = root.parent / "outside-reports"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("untouched", encoding="utf-8")
        self.directory_link(reports, outside)
        try:
            with self.assertRaises(Exception):
                audit_package(root)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
            self.assertFalse((outside / "final-audit.json").exists())
            self.assertFalse((outside / "final-audit.md").exists())
        finally:
            self.remove_directory_link(reports)

    def test_audit_invalidation_cannot_unlink_through_junction(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        EvidenceStore(root).append(self.record(root, "EVD-000001"))
        self.assertTrue(audit_package(root).can_complete)
        reports = root / "reports"
        outside = root.parent / "outside-audit"
        shutil.copytree(reports, outside)
        outside_json = (outside / "final-audit.json").read_bytes()
        outside_markdown = (outside / "final-audit.md").read_bytes()
        shutil.rmtree(reports)
        self.directory_link(reports, outside)
        try:
            with self.assertRaises(Exception):
                StateStore(root).transition(
                    "RUNNING",
                    expected_revision=auditing.state_revision,
                    phase_status="EXECUTING",
                )
            self.assertEqual(
                (outside / "final-audit.json").read_bytes(), outside_json
            )
            self.assertEqual(
                (outside / "final-audit.md").read_bytes(), outside_markdown
            )
        finally:
            self.remove_directory_link(reports)

    def test_state_lock_and_write_reject_runtime_junction_escape(self):
        root = self.package()
        runtime = root / "runtime"
        outside = root.parent / "outside-runtime"
        shutil.copytree(runtime, outside)
        original_events = (outside / "events.jsonl").read_bytes()
        shutil.rmtree(runtime)
        self.directory_link(runtime, outside)
        try:
            with self.assertRaises(Exception):
                StateStore(root).transition(
                    "PLAN_REVIEWED", expected_revision=1
                )
            self.assertEqual(
                (outside / "events.jsonl").read_bytes(), original_events
            )
            self.assertFalse((outside / "escaped.txt").exists())
        finally:
            self.remove_directory_link(runtime)

    def test_validator_rejects_manual_done_event_without_clean_audit(self):
        root = self.package()
        auditing = self.progress(root, auditing=True)
        done = auditing.transition("DONE")
        append_event(
            root / "runtime/events.jsonl",
            state=done.to_dict(),
            event_type="transition:AUDITING->DONE",
        )
        write_state_atomic(root / "runtime/STATE.json", done)
        (root / "STATE.md").write_text(
            render_state_md(done), encoding="utf-8", newline="\n"
        )
        report = audit_package(root)
        self.assertFalse(report.can_complete)
        diagnostics = validate_package(root)
        self.assertTrue(
            any(
                item.code == "SGV-PACKAGE-MUTABLE-MALFORMED"
                and item.pointer == "/reports/final-audit.json"
                for item in diagnostics
            ),
            diagnostics,
        )


if __name__ == "__main__":
    unittest.main()
