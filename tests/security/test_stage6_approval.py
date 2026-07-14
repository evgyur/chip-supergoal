from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.approval import ApprovalError, approval_ready_for_dispatch


class Stage6ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "spec").mkdir()
        shutil.copy2(ROOT / "spec/stage6-approval.schema.json", self.root / "spec/stage6-approval.schema.json")
        self.key = self.root / "operator"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)], check=True)
        public = (self.key.with_suffix(".pub")).read_text(encoding="utf-8").strip()
        self.trust = self.root / "spec/stage6-allowed-signers"
        self.trust.write_text(f"chip {public}\n", encoding="utf-8")
        self.revoked = self.root / "spec/stage6-revoked-fingerprints.txt"
        self.revoked.write_text("", encoding="utf-8")
        fingerprint = subprocess.run(["ssh-keygen", "-lf", str(self.key.with_suffix('.pub')), "-E", "sha256"], text=True, stdout=subprocess.PIPE, check=True).stdout.split()[1]
        self.receipt = self.root / "approval.json"
        self.value = {
            "schema_version": "stage6-approval-v1", "receipt_id": "APPROVAL-test",
            "signer_identity": "chip", "key_fingerprint": fingerprint,
            "namespace": "supergoal-stage6", "issued_at": "2026-07-14T00:00:00Z",
            "expires_at": "2026-07-15T00:00:00Z", "plan_subject_sha256": "1" * 64,
            "quality_report_sha256": "2" * 64, "event_sha256": "3" * 64,
            "trust_root_sha256": hashlib.sha256(self.trust.read_bytes()).hexdigest(),
            "nonce": "abcdefghijklmnop",
        }
        self._sign()

    def tearDown(self): self.tmp.cleanup()

    def _sign(self):
        self.receipt.write_text(json.dumps(self.value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        signature = self.receipt.with_suffix(self.receipt.suffix + ".sig")
        if signature.exists(): signature.unlink()
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(self.key), "-n", "supergoal-stage6", str(self.receipt)], check=True)
        self.signature = signature

    def _verify(self):
        return approval_ready_for_dispatch(
            self.root, self.receipt, self.signature,
            expected_plan_subject_sha256="1" * 64,
            expected_quality_report_sha256="2" * 64,
            expected_event_sha256="3" * 64,
            now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
        )

    def test_valid_offline_sshsig_is_ready(self): self.assertTrue(self._verify()["ready"])

    def test_forged_receipt_fails(self):
        self.value["event_sha256"] = "4" * 64
        self.receipt.write_text(json.dumps(self.value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        with self.assertRaises(ApprovalError): self._verify()

    def test_stale_receipt_fails(self):
        self.value["expires_at"] = "2026-07-14T01:00:00Z"; self._sign()
        with self.assertRaises(ApprovalError): self._verify()

    def test_mismatched_binding_fails(self):
        with self.assertRaises(ApprovalError):
            approval_ready_for_dispatch(self.root, self.receipt, self.signature, expected_plan_subject_sha256="9" * 64, expected_quality_report_sha256="2" * 64, expected_event_sha256="3" * 64, now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc))

    def test_revoked_signer_fails(self):
        self.revoked.write_text(self.value["key_fingerprint"] + "\n", encoding="utf-8")
        with self.assertRaises(ApprovalError): self._verify()

    def test_trust_root_swap_fails(self):
        self.trust.write_text("# swapped\n" + self.trust.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(ApprovalError): self._verify()

    @unittest.skipIf(not hasattr(Path, "symlink_to"), "symlink support unavailable")
    def test_signature_symlink_fails_closed(self):
        target = self.root / "real.sig"
        self.signature.replace(target)
        self.signature.symlink_to(target)
        with self.assertRaises(ApprovalError): self._verify()

    @unittest.skipUnless(sys.platform != "win32", "POSIX mode check")
    def test_world_writable_trust_fails_closed(self):
        self.trust.chmod(0o666)
        with self.assertRaises(ApprovalError): self._verify()


if __name__ == "__main__": unittest.main()
