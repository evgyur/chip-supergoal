import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract, terminal_markers_allowed, write_final_audit
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.events import append_event, read_events
from chip_supergoal.model import canonical_json, contract_from_dict
from chip_supergoal.state import State, StateStore


class AuditEngineTest(unittest.TestCase):
    def contract(self, *, final_delivery=False, review_delivery=False):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["loop"] = {}
        if final_delivery:
            data["delivery"] = {
                "items": ["artifact.zip"],
                "target": "current-thread",
            }
        elif review_delivery:
            data["delivery"] = {
                "files": [
                    "THINKING.md",
                    "LOOP_DESIGN.md",
                    "ROADMAP.md",
                    "LAUNCH_GOAL.md",
                ],
                "items": [],
                "review_pack_required": True,
                "target": "current-thread",
            }
        else:
            data["delivery"] = {}
        return contract_from_dict(data)

    def authority(self, contract):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        digest = hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()
        store = StateStore(root)
        store.initialize(
            State(
                goal_id=contract.goal.id,
                contract_sha256=digest,
                contract_revision=contract.contract_revision,
                state_revision=1,
                lifecycle="COMPILED",
                current_phase_id="P01",
                phase_status="PENDING",
            )
        )
        revision = 1
        for lifecycle in (
            "PLAN_REVIEWED",
            "PREFLIGHT_GREEN",
            "READY_TO_DISPATCH",
            "RUNNING",
        ):
            state = store.transition(
                lifecycle,
                expected_revision=revision,
                phase_status="EXECUTING" if lifecycle == "RUNNING" else None,
            )
            revision = state.state_revision
        state = store.update(expected_revision=revision, phase_status="COMPLETE")
        revision = state.state_revision
        state = store.transition("AUDITING", expected_revision=revision)
        events = read_events(store.events)
        return root, store, state, events

    def evidence(self, contract, state, events):
        criterion = contract.phases[0].criteria[0]
        command = contract.phases[0].commands[0]
        return [
            EvidenceRecord.pass_record(
                evidence_id="EVD-000001",
                goal_id=contract.goal.id,
                contract_sha256=state.contract_sha256,
                contract_revision=contract.contract_revision,
                phase_id="P01",
                criterion_id="P01-C01",
                command=command.command,
                exit_code=criterion.verifier.expected_exit,
                assertion=criterion.verifier.expected_assertion,
                captured_at=events[-1]["timestamp"],
            )
        ]

    def report(self, contract, records, *, package_root=None):
        _, _, state, events = self.authority(contract)
        return audit_contract(
            contract,
            records(state, events) if callable(records) else records,
            state=state,
            events=events,
            package_root=package_root,
        )

    def test_blocking_criterion_without_evidence_is_gap(self):
        report = self.report(self.contract(), [])
        self.assertFalse(report.can_complete)
        self.assertIn("AUDIT_GAP", {issue.issue_type for issue in report.issues})
        self.assertEqual(report.coverage["unverified"], 1)

    def test_caller_controlled_delivery_booleans_are_not_an_api(self):
        with self.assertRaises(TypeError):
            audit_contract(
                self.contract(), [], final_delivery_required=True, delivery_verified=True
            )

    def test_required_delivery_is_derived_and_missing_receipt_blocks(self):
        contract = self.contract(final_delivery=True)
        root, _, state, events = self.authority(contract)
        report = audit_contract(
            contract,
            self.evidence(contract, state, events),
            state=state,
            events=events,
            package_root=root,
        )
        self.assertFalse(report.can_complete)
        self.assertEqual(report.delivery_status, "missing")

    def test_required_delivery_receipt_is_identity_bound(self):
        contract = self.contract(final_delivery=True)
        root, _, state, events = self.authority(contract)
        receipt_path = root / "out/final-artifacts-delivery-receipt.json"
        receipt_path.parent.mkdir(parents=True)
        receipt = {
            "archive": "external-artifact.zip",
            "contract_revision": state.contract_revision,
            "contract_sha256": state.contract_sha256,
            "goal_id": state.goal_id,
            "hash": "d" * 64,
            "kind": "final-artifacts",
            "message_id": "msg-1",
            "ok": True,
            "sent": True,
            "sent_at": events[-1]["timestamp"],
            "target": "current-thread",
        }
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        valid = audit_contract(
            contract,
            self.evidence(contract, state, events),
            state=state,
            events=events,
            package_root=root,
        )
        self.assertTrue(valid.can_complete, valid.issues)
        self.assertEqual(valid.delivery_status, "verified")

        receipt["goal_id"] = "wrong-goal"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        forged = audit_contract(
            contract,
            self.evidence(contract, state, events),
            state=state,
            events=events,
            package_root=root,
        )
        self.assertFalse(forged.can_complete)
        self.assertEqual(forged.delivery_status, "invalid")

    def test_review_delivery_rejects_receipt_for_only_existing_subset(self):
        contract = self.contract(review_delivery=True)
        root, _, state, events = self.authority(contract)
        declared = contract.delivery.data["files"]
        present = declared[:-1]
        for name in present:
            (root / name).write_text(name + "\n", encoding="utf-8", newline="\n")
        hashes = {
            name: hashlib.sha256((name + "\n").encode("utf-8")).hexdigest()
            for name in present
        }
        receipt = {
            "contract_revision": state.contract_revision,
            "contract_sha256": state.contract_sha256,
            "files": present,
            "goal_id": state.goal_id,
            "hashes": hashes,
            "kind": "review-md-files",
            "message_ids": [f"msg-{index}" for index, _ in enumerate(present, 1)],
            "ok": True,
            "pack_version": "review_pack_v2",
            "sent": True,
            "sent_at": events[-1]["timestamp"],
            "target": "current-thread",
        }
        receipt_path = root / "out/review-md-files-delivery-receipt.json"
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        report = audit_contract(
            contract,
            self.evidence(contract, state, events),
            state=state,
            events=events,
            package_root=root,
        )
        self.assertFalse(report.can_complete)
        self.assertEqual(report.delivery_status, "invalid")

    def test_terminal_markers_require_done_state_and_clean_current_report(self):
        contract = self.contract()
        _, store, auditing, events = self.authority(contract)
        records = self.evidence(contract, auditing, events)
        auditing_report = audit_contract(
            contract, records, state=auditing, events=events
        )
        self.assertFalse(terminal_markers_allowed(auditing, auditing_report))

        done = auditing.transition("DONE")
        append_event(
            store.events,
            state=done.to_dict(),
            event_type="transition:AUDITING->DONE",
        )
        done_events = read_events(store.events)
        done_report = audit_contract(contract, records, state=done, events=done_events)
        self.assertTrue(terminal_markers_allowed(done, done_report))

    def test_final_audit_files_are_canonical_projections(self):
        contract = self.contract()
        _, _, state, events = self.authority(contract)
        report = audit_contract(
            contract,
            self.evidence(contract, state, events),
            state=state,
            events=events,
        )
        with tempfile.TemporaryDirectory() as td:
            json_path, md_path = write_final_audit(report, td)
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            self.assertEqual(json.loads(json_path.read_text())["goal_id"], contract.goal.id)
            self.assertIn("# Final audit", md_path.read_text())


if __name__ == "__main__":
    unittest.main()
