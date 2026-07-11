import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract
from chip_supergoal.events import read_events
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.model import canonical_json, contract_from_dict
from chip_supergoal.state import State, StateStore


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class AuditBoundaryRegressionTest(unittest.TestCase):
    def contract(self, *, expected_exit=0, loop=None, policy=False):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["loop"] = dict(loop or {})
        data["phases"][0]["criteria"][0]["verifier"]["expected_exit"] = expected_exit
        if not policy:
            data["risks"] = []
            data["phases"][0]["risk_tags"] = []
            data["phases"][0]["rpd"] = {"required": False, "focus": []}
        return contract_from_dict(data)

    def auditing_journal(self, contract):
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
        anchor = datetime.strptime(
            events[-1]["timestamp"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        return state, events, anchor

    def evidence(
        self,
        contract,
        state,
        captured_at,
        *,
        fresh_until="audit_end",
        exit_code=None,
        metadata=None,
        type="command_result",
        artifact_sha256=None,
        redaction="passed",
    ):
        command = contract.phases[0].commands[0].command
        expected = contract.phases[0].criteria[0].verifier.expected_exit
        return EvidenceRecord(
            evidence_id="EVD-000001",
            goal_id=state.goal_id,
            contract_sha256=state.contract_sha256,
            contract_revision=state.contract_revision,
            phase_id="P01",
            criterion_id="P01-C01",
            type=type,
            producer="test",
            captured_at=_stamp(captured_at),
            fresh_until=fresh_until,
            replayable=type == "command_result",
            result="pass",
            command=command if type == "command_result" else None,
            exit_code=(
                (expected if exit_code is None else exit_code)
                if type == "command_result"
                else None
            ),
            assertion=(
                contract.phases[0].criteria[0].verifier.expected_assertion
                if type == "command_result"
                else None
            ),
            artifact_sha256=artifact_sha256,
            redaction=redaction,
            metadata=dict(metadata or {}),
        )

    def audit(self, contract, state, events, records, *, policy=None):
        return audit_contract(
            contract,
            records,
            state=state,
            events=events,
            risk_policy=policy,
        )

    def test_future_skew_plus_300_is_accepted_and_plus_301_is_gap(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        accepted = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor + timedelta(seconds=300))],
        )
        rejected = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor + timedelta(seconds=301))],
        )
        self.assertTrue(accepted.can_complete, accepted.issues)
        self.assertFalse(rejected.can_complete)

    def test_default_age_86400_boundary_is_inclusive(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        accepted = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor - timedelta(seconds=86400))],
        )
        rejected = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor - timedelta(seconds=86401))],
        )
        self.assertTrue(accepted.can_complete, accepted.issues)
        self.assertFalse(rejected.can_complete)

    def test_absolute_fresh_until_must_reach_audit_anchor(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        accepted = self.audit(
            contract,
            state,
            events,
            [
                self.evidence(
                    contract,
                    state,
                    anchor,
                    fresh_until=_stamp(anchor),
                )
            ],
        )
        rejected = self.audit(
            contract,
            state,
            events,
            [
                self.evidence(
                    contract,
                    state,
                    anchor,
                    fresh_until=_stamp(anchor - timedelta(seconds=1)),
                )
            ],
        )
        self.assertTrue(accepted.can_complete, accepted.issues)
        self.assertFalse(rejected.can_complete)

    def test_bool_and_unknown_per_type_freshness_policy_fail_closed(self):
        bad_loops = (
            {"evidence_max_age_seconds": True},
            {"evidence_max_age_by_type": {"invented": 1}},
        )
        for loop in bad_loops:
            with self.subTest(loop=loop):
                contract = self.contract(loop=loop)
                state, events, anchor = self.auditing_journal(contract)
                report = self.audit(
                    contract,
                    state,
                    events,
                    [self.evidence(contract, state, anchor)],
                )
                self.assertFalse(report.can_complete)
                self.assertIn(
                    "AUDIT_CORRUPTION", {issue.issue_type for issue in report.issues}
                )

    def test_exact_declared_nonzero_exit_is_valid(self):
        contract = self.contract(expected_exit=7)
        state, events, anchor = self.auditing_journal(contract)
        report = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor, exit_code=7)],
        )
        self.assertTrue(report.can_complete, report.issues)

    def test_duplicate_ids_are_corruption_and_invalid_redaction_is_rejected(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        record = self.evidence(contract, state, anchor)
        duplicate = self.audit(contract, state, events, [record, record])
        self.assertFalse(duplicate.can_complete)
        self.assertIn(
            "AUDIT_CORRUPTION", {issue.issue_type for issue in duplicate.issues}
        )
        with self.assertRaisesRegex(ValueError, "redaction"):
            self.evidence(contract, state, anchor, redaction="unchecked")

    def test_file_hash_requires_artifact_hash(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        with self.assertRaisesRegex(ValueError, "artifact_sha256"):
            self.evidence(
                contract,
                state,
                anchor,
                type="file_hash",
                artifact_sha256=None,
            )

    def test_command_backed_criterion_rejects_manual_observation_bypass(self):
        contract = self.contract()
        state, events, anchor = self.auditing_journal(contract)
        forged = self.evidence(
            contract,
            state,
            anchor,
            type="manual_observation",
        )
        report = self.audit(contract, state, events, [forged])
        self.assertFalse(report.can_complete)
        self.assertIn(
            "AUDIT_CORRUPTION", {issue.issue_type for issue in report.issues}
        )

    def test_assertion_verifier_requires_matching_manual_evidence(self):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["phases"][0]["criteria"][0]["verifier"] = {
            "expected_assertion": "signed independent proof",
            "type": "assertion",
        }
        contract = contract_from_dict(data)
        state, events, anchor = self.auditing_journal(contract)
        forged = self.evidence(
            contract,
            state,
            anchor,
            type="manual_observation",
        )
        rejected = self.audit(contract, state, events, [forged])
        self.assertFalse(rejected.can_complete)

        valid = EvidenceRecord.from_dict(
            {
                **forged.to_dict(),
                "assertion": "signed independent proof",
                "evidence_id": "EVD-000002",
            }
        )
        accepted = self.audit(contract, state, events, [valid])
        self.assertTrue(accepted.can_complete, accepted.issues)

    def test_approval_manifest_is_auxiliary_and_does_not_replace_command_proof(self):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["approvals"] = [
            {
                "class_name": "release",
                "id": "APP-001",
                "required": True,
                "scope": "final release",
            }
        ]
        contract = contract_from_dict(data)
        state, events, anchor = self.auditing_journal(contract)
        command_proof = self.evidence(contract, state, anchor)
        approval = EvidenceRecord(
            evidence_id="EVD-APPROVAL",
            goal_id=state.goal_id,
            contract_sha256=state.contract_sha256,
            contract_revision=state.contract_revision,
            phase_id="P01",
            criterion_id="__phase__",
            type="approval_manifest",
            producer="approval-gate",
            captured_at=_stamp(anchor),
            fresh_until="audit_end",
            replayable=False,
            result="pass",
            redaction="passed",
            artifact_sha256="e" * 64,
            metadata={"approval_ids": ["APP-001"]},
        )
        auxiliary_only = self.audit(contract, state, events, [approval])
        self.assertFalse(auxiliary_only.can_complete)
        accepted = self.audit(
            contract, state, events, [command_proof, approval]
        )
        self.assertTrue(accepted.can_complete, accepted.issues)

    def test_phase_scoped_approval_works_when_phase_has_no_criteria(self):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["phases"][0]["criteria"] = []
        data["approvals"] = [
            {
                "class_name": "release",
                "id": "APP-001",
                "required": True,
                "scope": "final release",
            }
        ]
        contract = contract_from_dict(data)
        state, events, anchor = self.auditing_journal(contract)
        approval = EvidenceRecord(
            evidence_id="EVD-PHASE-APPROVAL",
            goal_id=state.goal_id,
            contract_sha256=state.contract_sha256,
            contract_revision=state.contract_revision,
            phase_id="P01",
            criterion_id="__phase__",
            type="approval_manifest",
            producer="approval-gate",
            captured_at=_stamp(anchor),
            fresh_until="audit_end",
            replayable=False,
            result="pass",
            redaction="passed",
            artifact_sha256="f" * 64,
            metadata={"approval_ids": ["APP-001"]},
        )
        report = self.audit(contract, state, events, [approval])
        self.assertTrue(report.can_complete, report.issues)

    def test_policy_and_rpd_evidence_are_derived_from_metadata(self):
        contract = self.contract(policy=True)
        state, events, anchor = self.auditing_journal(contract)
        policy = json.loads((ROOT / "spec/risk-policy.json").read_text(encoding="utf-8"))
        missing = self.audit(
            contract,
            state,
            events,
            [self.evidence(contract, state, anchor)],
            policy=policy,
        )
        present = self.audit(
            contract,
            state,
            events,
            [
                self.evidence(
                    contract,
                    state,
                    anchor,
                    metadata={
                        "policy_evidence": ["negative_authorization_fixture"],
                        "rpd_focus": ["security", "integration"],
                    },
                )
            ],
            policy=policy,
        )
        self.assertFalse(missing.can_complete)
        self.assertTrue(present.can_complete, present.issues)


if __name__ == "__main__":
    unittest.main()
