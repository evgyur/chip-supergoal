import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.goalmanager_sim import GoalManagerSimulator


class RelocatedRuntimeCliE2ETest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["profile"] = "public-clean"
        data["risks"] = []
        data["delivery"] = {}
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["compatibility"].pop("research_gate", None)
        source = self.parent / "source.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        compiled = self.parent / "compiled"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/sgctl.py"),
                "compile",
                str(source),
                "--out",
                str(compiled),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.package = self.parent / "relocated path" / ".supergoal" / "slug"
        self.package.parent.mkdir(parents=True)
        shutil.move(compiled, self.package)
        self.script = self.package / "scripts/sgctl.py"
        self.env = os.environ.copy()
        self.env.pop("PYTHONPATH", None)
        self.env["PYTHONUTF8"] = "1"

    def run_cli(self, *args, input=None, expected=0):
        result = subprocess.run(
            [sys.executable, str(self.script), *map(str, args)],
            cwd=self.parent,
            env=self.env,
            text=True,
            input=input,
            capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        return result

    def transition(self, lifecycle, revision, *, phase_status=None):
        args = [
            "state-transition",
            "--to",
            lifecycle,
            "--expected-revision",
            str(revision),
        ]
        if phase_status is not None:
            args += ["--phase-status", phase_status]
        return json.loads(self.run_cli(*args).stdout)

    def progress_to_auditing(self):
        revision = 1
        for lifecycle in (
            "PLAN_REVIEWED",
            "PREFLIGHT_GREEN",
            "READY_TO_DISPATCH",
            "RUNNING",
            "AUDITING",
        ):
            state = self.transition(
                lifecycle,
                revision,
                phase_status="EXECUTING" if lifecycle == "RUNNING" else None,
            )
            revision = state["state_revision"]
            if lifecycle == "RUNNING":
                state = json.loads(
                    self.run_cli(
                        "state-transition",
                        "--expected-revision",
                        str(revision),
                        "--phase-status",
                        "COMPLETE",
                    ).stdout
                )
                revision = state["state_revision"]
        return state

    def compile_delivery_package(self, *, final=False, max_age=None):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["profile"] = "chip-private"
        data["risks"] = []
        data["delivery"] = {
            "items": ["artifact.zip"] if final else [],
            "receipt_policy": {"required": True},
            "review_pack_required": not final,
            "target": "current-thread",
            "transport": "telegram",
        }
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["compatibility"].pop("research_gate", None)
        if max_age is not None:
            data["loop"]["evidence_max_age_by_type"] = {
                "delivery_ack": max_age
            }
        label = "final" if final else "review"
        source = self.parent / f"{label}-delivery-source.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        compiled = self.parent / f"{label}-delivery-compiled"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/sgctl.py"),
                "compile",
                str(source),
                "--out",
                str(compiled),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.package = (
            self.parent / f"{label} delivery relocated path" / ".supergoal" / "slug"
        )
        self.package.parent.mkdir(parents=True)
        shutil.move(compiled, self.package)
        self.script = self.package / "scripts/sgctl.py"

    def evidence_payload(self):
        contract_bytes = (self.package / "CONTRACT.json").read_bytes()
        contract = json.loads(contract_bytes)
        anchor = json.loads(
            (self.package / "runtime/events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[-1]
        )["timestamp"]
        criterion = contract["phases"][0]["criteria"][0]
        command = contract["phases"][0]["commands"][0]
        return {
            "evidence_id": "EVD-000001",
            "goal_id": contract["goal"]["id"],
            "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
            "contract_revision": contract["contract_revision"],
            "phase_id": contract["phases"][0]["id"],
            "criterion_id": criterion["id"],
            "type": "command_result",
            "producer": "e2e",
            "captured_at": anchor,
            "fresh_until": "audit_end",
            "replayable": True,
            "result": "pass",
            "command": command["command"],
            "exit_code": criterion["verifier"]["expected_exit"],
            "assertion": criterion["verifier"]["expected_assertion"],
            "redaction": "passed",
            "metadata": {},
        }

    def test_relocated_package_completes_full_python_authoritative_lifecycle(self):
        state = json.loads(self.run_cli("state-show").stdout)
        self.assertEqual(state["lifecycle"], "COMPILED")
        auditing = self.progress_to_auditing()

        payload = self.evidence_payload()
        recorded = json.loads(
            self.run_cli(
                "record-evidence", "--input", "-", input=json.dumps(payload)
            ).stdout
        )
        self.assertEqual(recorded["evidence_id"], payload["evidence_id"])

        report = json.loads(self.run_cli("audit").stdout)
        self.assertTrue(report["can_complete"], report["issues"])
        done = self.transition("DONE", auditing["state_revision"])
        self.assertEqual(done["lifecycle"], "DONE")
        self.assertEqual(done["current_phase_id"], "P01")

        first = self.run_cli("finalize").stdout.encode("utf-8")
        second = self.run_cli("finalize").stdout.encode("utf-8")
        self.assertEqual(first, second)
        self.assertEqual(
            first, (self.package / "reports/terminal-record.txt").read_bytes()
        )
        self.assertEqual(len(first.decode("utf-8").splitlines()), 5)

        self.run_cli("validate-terminal")
        self.run_cli("validate-package", str(self.package), "--strict")
        self.assertEqual(GoalManagerSimulator().classify_package(self.package), "done")

    def test_explicit_recovery_repairs_projection_and_reports_result(self):
        expected = json.loads(self.run_cli("state-show").stdout)
        (self.package / "runtime/STATE.json").write_text("{broken", encoding="utf-8")
        recovered = json.loads(self.run_cli("state-recover").stdout)
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(recovered["state"], expected)
        self.run_cli("validate-package", str(self.package), "--strict")

    def test_runtime_errors_are_structured_and_never_print_tracebacks(self):
        result = self.run_cli(
            "record-evidence",
            "--input",
            "-",
            input="{}",
            expected=1,
        )
        error = json.loads(result.stderr)
        self.assertEqual(error["ok"], False)
        self.assertTrue(error["code"].startswith("SGV-"))

    def test_nonfinite_blocker_json_is_rejected_without_runtime_mutation(self):
        events = self.package / "runtime/events.jsonl"
        state = self.package / "runtime/STATE.json"
        before_events = events.read_bytes()
        before_state = state.read_bytes()
        result = self.run_cli(
            "state-transition",
            "--expected-revision",
            "1",
            "--blocker-json",
            '{"value":NaN}',
            expected=1,
        )
        self.assertIn("SGV-STATE-ILLEGAL-UPDATE", result.stderr)
        self.assertEqual(events.read_bytes(), before_events)
        self.assertEqual(state.read_bytes(), before_state)

    def test_relocated_review_receipt_producer_is_canonical_and_reuse_rejects_forgery(self):
        self.compile_delivery_package()
        missing = self.run_cli(
            "delivery-review-check",
            "--target",
            "current-thread",
            expected=10,
        )
        self.assertEqual(json.loads(missing.stdout)["status"], "missing")

        auditing = self.progress_to_auditing()
        payload = self.evidence_payload()
        self.run_cli(
            "record-evidence", "--input", "-", input=json.dumps(payload)
        )
        contract = json.loads((self.package / "CONTRACT.json").read_text("utf-8"))
        active_files = sorted(
            name
            for name in contract["delivery"]["files"]
            if name != "RESEARCH.md" or (self.package / name).exists()
        )
        args = ["delivery-review-record", "--target", "current-thread"]
        for name in active_files:
            args.extend(["--message-id", f"msg-{name}"])
        receipt = json.loads(self.run_cli(*args).stdout)
        self.assertEqual(receipt["goal_id"], contract["goal"]["id"])
        self.assertEqual(receipt["files"], sorted(active_files))
        self.assertEqual(
            receipt["message_ids"], [f"msg-{name}" for name in active_files]
        )
        self.assertRegex(
            receipt["sent_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        report = json.loads(self.run_cli("audit").stdout)
        self.assertTrue(report["can_complete"], report["issues"])
        self.assertEqual(report["delivery_status"], "verified")

        receipt_path = self.package / "out/review-md-files-delivery-receipt.json"
        receipt["goal_id"] = "forged-goal"
        forged_bytes = (
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        receipt_path.write_bytes(forged_bytes)
        rejected = self.run_cli(
            "delivery-review-check",
            "--target",
            "current-thread",
            expected=1,
        )
        self.assertIn("SGV-DELIVERY-RECEIPT-INVALID", rejected.stderr)
        self.run_cli(*args, expected=1)
        self.assertEqual(receipt_path.read_bytes(), forged_bytes)

    def test_final_delivery_producer_fails_closed_without_task6_result_authority(self):
        self.compile_delivery_package(final=True)
        archive = self.parent / "external-artifact.zip"
        archive.write_bytes(b"not a Task 6 canonical archive")
        result = self.run_cli(
            "delivery-final-check",
            "--target",
            "current-thread",
            "--archive",
            str(archive),
            expected=1,
        )
        self.assertIn(
            "SGV-DELIVERY-ARCHIVE-AUTHORITY-UNAVAILABLE", result.stderr
        )
        self.assertFalse(
            (self.package / "out/final-artifacts-delivery-receipt.json").exists()
        )

    def test_package_audit_honors_delivery_ack_freshness_override_boundary(self):
        self.compile_delivery_package(max_age=60)
        self.progress_to_auditing()
        payload = self.evidence_payload()
        self.run_cli(
            "record-evidence", "--input", "-", input=json.dumps(payload)
        )
        contract = json.loads((self.package / "CONTRACT.json").read_text("utf-8"))
        active_files = sorted(
            name
            for name in contract["delivery"]["files"]
            if name != "RESEARCH.md" or (self.package / name).exists()
        )
        args = ["delivery-review-record", "--target", "current-thread"]
        for name in active_files:
            args.extend(["--message-id", f"msg-{name}"])
        receipt = json.loads(self.run_cli(*args).stdout)
        receipt_path = self.package / "out/review-md-files-delivery-receipt.json"
        anchor = datetime.strptime(
            json.loads(
                (self.package / "runtime/events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )["timestamp"],
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)

        for age, expected_complete in ((60, True), (61, False)):
            receipt["sent_at"] = (anchor - timedelta(seconds=age)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            report = json.loads(self.run_cli("audit").stdout)
            self.run_cli("validate-package", self.package, "--strict")
            self.assertEqual(report["can_complete"], expected_complete, report)
            self.assertEqual(
                report["delivery_status"],
                "verified" if expected_complete else "invalid",
            )


if __name__ == "__main__":
    unittest.main()
