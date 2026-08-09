from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chip_supergoal.reviewed_rail import (
    AUDIT_DISABLED_ERROR,
    ROLLOUT_DISABLED_ERROR,
    ApprovalDenied,
    ApprovalStore,
    ArchitectureBlocker,
    PinnedHelperRail,
    _parser,
    _push_exact,
    apply_reviewed_rollout,
    audit_reviewed_rollout,
    consume_approval_bundle,
    main,
    verify_installed_generation,
)


class NaturalApprovalSecurityTests(unittest.TestCase):

    def test_exact_push_uses_atomic_remote_lease_and_readback(self):
        old = "1" * 40
        new = "2" * 40
        with patch("chip_supergoal.reviewed_rail.subprocess.run") as run, patch(
            "chip_supergoal.reviewed_rail._remote_head", return_value=new
        ):
            run.return_value = SimpleNamespace(returncode=0)
            _push_exact(Path("/repo"), "private", "main", new, expected_remote_sha=old)

        argv = run.call_args.args[0]
        self.assertIn(f"--force-with-lease=refs/heads/main:{old}", argv)
        self.assertEqual(argv[-2:], ["private", f"{new}:refs/heads/main"])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "approval-ledger"
        self.store = ApprovalStore(self.root)
        self.context = {
            "actor_id": "617744661",
            "bot_id": "8533179145",
            "chat_id": "-1003971448755",
            "thread_id": "28479",
            "request_message_id": "30001",
            "goal_id": "sg-20260809-goal-checkpoint-hardening-unified",
            "package_id": "goal-checkpoint-hardening-unified-20260809",
            "action": "private-rollout",
            "target": "/opt/hermes-agent",
            "candidate_sha": "a" * 40,
            "tree_sha": "b" * 40,
            "manifest_sha256": "c" * 64,
            "packet_sha256": "d" * 64,
            "installed_generation_sha256": "e" * 64,
            "reviewed_generation": "c1405384091f8273191c647c3e0bab2bdbdb6d47",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def issue(self, nonce: str = "nonce-0001", request: str | None = None, now: int = 1000):
        context = dict(self.context)
        if request is not None:
            context["request_message_id"] = request
        return self.store.issue(context=context, nonce=nonce, issued_at=now, expires_at=now + 60)

    def event(self, text: str = "го", nonce: str = "nonce-0001", request: str | None = None, now: int = 1010):
        context = dict(self.context)
        if request is not None:
            context["request_message_id"] = request
        return {
            **context,
            "nonce": nonce,
            "reply_message_id": "30002",
            "reply_to_message_id": context["request_message_id"],
            "observed_at": now,
            "text": text,
        }

    def test_supported_natural_replies_consume_once_without_raw_text(self):
        for index, text in enumerate(("го", "да", "делай", "апрув", "approve", "Aprove"), start=1):
            with self.subTest(text=text):
                nonce = f"nonce-{index:04d}"
                request = str(30000 + index)
                self.issue(nonce=nonce, request=request)
                receipt = self.store.consume(self.event(text=text, nonce=nonce, request=request), now=1012)
                self.assertEqual(receipt["state"], "consumed")
                self.assertEqual(receipt["reply_message_id"], "30002")
                persisted = b"".join(p.read_bytes() for p in self.root.rglob("*.json"))
                self.assertNotIn(text.encode("utf-8"), persisted)
                with self.assertRaises(ApprovalDenied):
                    self.store.consume(self.event(text=text, nonce=nonce, request=request), now=1012)

    def test_wrong_context_expiry_revocation_and_nonaffirmative_fail_closed(self):
        mutations = {
            "actor_id": "999",
            "bot_id": "999",
            "chat_id": "-1",
            "thread_id": "1",
            "reply_to_message_id": "999",
            "goal_id": "other",
            "package_id": "other",
            "action": "other",
            "target": "/tmp/other",
            "candidate_sha": "0" * 40,
            "tree_sha": "0" * 40,
            "manifest_sha256": "0" * 64,
            "packet_sha256": "0" * 64,
            "installed_generation_sha256": "0" * 64,
            "reviewed_generation": "0" * 40,
            "nonce": "wrong-nonce",
        }
        for index, (field, value) in enumerate(mutations.items(), start=1):
            with self.subTest(field=field):
                nonce = f"mismatch-{index:04d}"
                request = str(31000 + index)
                self.issue(nonce=nonce, request=request)
                event = self.event(nonce=nonce, request=request)
                event[field] = value
                with self.assertRaises(ApprovalDenied):
                    self.store.consume(event, now=1012)
        self.issue(nonce="expired-0001", request="32001")
        with self.assertRaises(ApprovalDenied):
            self.store.consume(self.event(nonce="expired-0001", request="32001", now=1061), now=1061)
        self.issue(nonce="stale-processing-0001", request="32004")
        with self.assertRaises(ApprovalDenied):
            self.store.consume(self.event(nonce="stale-processing-0001", request="32004", now=1010), now=1061)
        self.issue(nonce="revoked-0001", request="32002")
        self.store.revoke("revoked-0001", reason="candidate invalidated", revoked_at=1010)
        with self.assertRaises(ApprovalDenied):
            self.store.consume(self.event(nonce="revoked-0001", request="32002"), now=1012)
        self.issue(nonce="negative-0001", request="32003")
        with self.assertRaises(ApprovalDenied):
            self.store.consume(self.event(text="потом", nonce="negative-0001", request="32003"), now=1012)

    def test_missing_canonical_telegram_metadata_is_architecture_blocker(self):
        self.issue()
        for field in (
            "actor_id", "bot_id", "chat_id", "thread_id", "reply_message_id",
            "reply_to_message_id", "request_message_id", "goal_id", "package_id",
            "action", "target", "candidate_sha", "tree_sha", "manifest_sha256",
            "packet_sha256", "nonce", "observed_at", "text",
            "installed_generation_sha256", "reviewed_generation",
        ):
            with self.subTest(field=field):
                event = self.event()
                del event[field]
                with self.assertRaises(ArchitectureBlocker):
                    self.store.consume(event, now=1012)

    def test_bundle_owner_must_match_authorized_actor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate_path = root / "candidate.json"
            packet_path = root / "packet.json"
            bundle_path = root / "bundle.json"
            output = root / "approval.json"
            candidate = {
                "goal_id": self.context["goal_id"],
                "package_id": self.context["package_id"],
                "manifest_sha256": self.context["manifest_sha256"],
                "hermes": {
                    "sha": self.context["candidate_sha"],
                    "tree": self.context["tree_sha"],
                },
                "chip_supergoal": {
                    "sha": self.context["reviewed_generation"],
                    "installed_generation_sha256": self.context["installed_generation_sha256"],
                },
            }
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            candidate_path.chmod(0o600)
            packet = {
                "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "live_blocked_by_unrelated_overlay": False,
            }
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            packet_path.chmod(0o600)
            context = dict(self.context)
            context["packet_sha256"] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            context["actor_id"] = "999"
            card = {**context, "nonce": "owner-mismatch", "issued_at": 1000, "expires_at": 1060}
            event = {
                **context,
                "nonce": "owner-mismatch",
                "reply_message_id": "30002",
                "reply_to_message_id": context["request_message_id"],
                "observed_at": 1010,
                "text": "да",
            }
            bundle_path.write_text(json.dumps({"card": card, "event": event}), encoding="utf-8")
            bundle_path.chmod(0o600)
            with patch.dict("os.environ", {"CHIP_SUPERGOAL_APPROVAL_EVENT_JSON": str(bundle_path)}), patch(
                "chip_supergoal.reviewed_rail.verify_installed_generation",
                return_value=self.context["installed_generation_sha256"],
            ):
                with self.assertRaisesRegex(ApprovalDenied, "owner mismatch"):
                    consume_approval_bundle(
                        candidate_path,
                        packet_path,
                        output,
                        origin="telegram:-1003971448755:28479",
                        owner_id="617744661",
                    )
            self.assertFalse(output.exists())

    def test_ambiguous_pending_cards_fail_closed(self):
        self.issue(nonce="ambiguous-0001")
        self.issue(nonce="ambiguous-0002")
        with self.assertRaises(ApprovalDenied):
            self.store.consume(self.event(nonce="ambiguous-0001"), now=1012)

    def test_atomic_one_shot_consumption_under_race(self):
        self.issue(nonce="race-0001")
        barrier = threading.Barrier(3)
        results: list[str] = []

        def worker() -> None:
            barrier.wait()
            try:
                self.store.consume(self.event(nonce="race-0001"), now=1012)
            except ApprovalDenied:
                results.append("denied")
            else:
                results.append("consumed")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(results), ["consumed", "denied"])

    def test_effect_claim_is_atomic_one_shot_and_expiry_bound(self):
        self.issue(nonce="effect-0001")
        receipt = self.store.consume(self.event(nonce="effect-0001"), now=1012)
        claim = self.store.claim_effect(receipt, now=1013)
        self.assertEqual(claim["state"], "claimed")
        with self.assertRaises(ApprovalDenied):
            self.store.claim_effect(receipt, now=1014)

        self.issue(nonce="effect-expired-0001")
        expired = self.store.consume(self.event(nonce="effect-expired-0001"), now=1012)
        with self.assertRaises(ApprovalDenied):
            self.store.claim_effect(expired, now=1061)

    def test_symlink_ledger_root_is_rejected(self):
        target = Path(self.temp.name) / "real"
        target.mkdir(mode=0o700)
        link = Path(self.temp.name) / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ApprovalDenied):
            ApprovalStore(link)
        parent_link = Path(self.temp.name) / "parent-link"
        parent_link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ApprovalDenied):
            ApprovalStore(parent_link / "ledger")


class PinnedHelperRailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server_doctor = self.root / "server-doctor"
        scripts = self.server_doctor / "scripts"
        scripts.mkdir(parents=True)
        self.guard = scripts / "hermes-private-patch-registry-guard.py"
        self.update = scripts / "hermes-private-update.py"
        self.guard.write_text("print('guard')\n", encoding="utf-8")
        self.update.write_text("print('update')\n", encoding="utf-8")
        self.packet_path = self.root / "packet.json"
        self.packet = {
            "schema": "chip-supergoal.reviewed-rail-packet.v1",
            "server_doctor_root": str(self.server_doctor),
            "helpers": {
                "registry_guard": {
                    "path": "scripts/hermes-private-patch-registry-guard.py",
                    "sha256": hashlib.sha256(self.guard.read_bytes()).hexdigest(),
                    "argv": ["--hermes-root", "/candidate", "--candidate-ref", "HEAD", "--json"],
                },
                "private_update": {
                    "path": "scripts/hermes-private-update.py",
                    "sha256": hashlib.sha256(self.update.read_bytes()).hexdigest(),
                    "argv": ["--mode", "apply", "--live-root", "/opt/hermes-agent", "--restart", "none"],
                },
            },
        }
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        packet_sha = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
        self.approval_path = self.root / "approval.json"
        self.approval = {
            "schema": "chip-supergoal.natural-approval-receipt.v1",
            "state": "consumed",
            "context": {"packet_sha256": packet_sha},
            "raw_text_persisted": False,
        }
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_delegates_only_to_exact_pinned_existing_helpers(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        rail = PinnedHelperRail.from_files(self.packet_path, self.approval_path)
        result = rail.run_step("registry_guard", runner=runner)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(calls[0][0][1]), self.guard)
        self.assertEqual(calls[0][0][2:], self.packet["helpers"]["registry_guard"]["argv"])

    def test_rejects_unconsumed_or_packet_mismatched_approval(self):
        self.approval["state"] = "pending"
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        with self.assertRaises(ApprovalDenied):
            PinnedHelperRail.from_files(self.packet_path, self.approval_path)
        self.approval["state"] = "consumed"
        self.approval["context"]["packet_sha256"] = "0" * 64
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        with self.assertRaises(ApprovalDenied):
            PinnedHelperRail.from_files(self.packet_path, self.approval_path)

    def test_rejects_path_escape_hash_drift_and_unlisted_step(self):
        self.packet["helpers"]["registry_guard"]["path"] = "../evil.py"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.approval["context"]["packet_sha256"] = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        with self.assertRaises(ApprovalDenied):
            PinnedHelperRail.from_files(self.packet_path, self.approval_path)

        self.packet["helpers"]["registry_guard"]["path"] = "scripts/hermes-private-patch-registry-guard.py"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.approval["context"]["packet_sha256"] = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        rail = PinnedHelperRail.from_files(self.packet_path, self.approval_path)
        self.guard.write_text("print('changed')\n", encoding="utf-8")
        with self.assertRaises(ApprovalDenied):
            rail.run_step("registry_guard")
        with self.assertRaises(ApprovalDenied):
            rail.run_step("other")


class InstalledGenerationTests(unittest.TestCase):
    def _candidate(self, root: Path, hashes: dict[str, str]) -> dict[str, object]:
        digest = hashlib.sha256(
            json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "chip_supergoal": {
                "installed_root": str(root),
                "generation_files": hashes,
                "installed_generation_sha256": digest,
            }
        }

    def test_exact_read_only_generation_passes_and_tamper_denies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "chip_supergoal"
            root.mkdir(mode=0o755)
            files = {"__init__.py": b"", "reviewed_rail.py": b"VALUE = 1\n"}
            hashes: dict[str, str] = {}
            for name, content in files.items():
                path = root / name
                path.write_bytes(content)
                path.chmod(0o444)
                hashes[name] = hashlib.sha256(content).hexdigest()
            root.chmod(0o555)
            candidate = self._candidate(root, hashes)
            expected = hashlib.sha256(
                json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self.assertEqual(verify_installed_generation(candidate), expected)
            path = root / "reviewed_rail.py"
            path.chmod(0o644)
            path.write_text("VALUE = 2\n", encoding="utf-8")
            path.chmod(0o444)
            with self.assertRaises(ApprovalDenied):
                verify_installed_generation(candidate)

    def test_writable_root_or_extra_python_file_denies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "chip_supergoal"
            root.mkdir(mode=0o755)
            init = root / "__init__.py"
            init.write_bytes(b"")
            init.chmod(0o444)
            hashes = {"__init__.py": hashlib.sha256(b"").hexdigest()}
            candidate = self._candidate(root, hashes)
            with self.assertRaises(ApprovalDenied):
                verify_installed_generation(candidate)
            extra = root / "extra.py"
            extra.write_text("pass\n", encoding="utf-8")
            extra.chmod(0o444)
            root.chmod(0o555)
            with self.assertRaises(ApprovalDenied):
                verify_installed_generation(candidate)

    def test_cli_safety_flags_are_not_cosmetic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "packet.json"
            result = main([
                "packet", "--candidate", str(Path(td) / "candidate.json"),
                "--server-doctor", str(Path(td) / "server-doctor"),
                "--registry-guard", "scripts/hermes-private-patch-registry-guard.py",
                "--private-update", "scripts/hermes-private-update.py",
                "--live", "/opt/hermes-agent",
                "--output", str(output),
            ])
            self.assertEqual(result, 2)
            self.assertFalse(output.exists())

    def test_generated_phase_three_command_abi_parses(self) -> None:
        parser = _parser()
        commands = [
            [
                "packet", "--candidate", "c", "--require-installed-generation-hash",
                "--server-doctor", "/server-doctor", "--registry-guard",
                "scripts/hermes-private-patch-registry-guard.py", "--private-update",
                "scripts/hermes-private-update.py", "--live", "/opt/hermes-agent",
                "--output", "packet.json",
            ],
            [
                "approve", "--candidate", "c", "--packet", "p",
                "--require-installed-generation-hash", "--origin", "telegram:-1:2",
                "--owner-id", "617744661", "--direct-reply-only",
                "--consume-atomically", "--reject-replay", "--output", "approval.json",
            ],
            [
                "apply", "--candidate", "c", "--packet", "p", "--approval", "a",
                "--require-installed-generation-hash", "--server-doctor", "/server-doctor",
                "--publish-server-doctor-first", "--registry-guard", "scripts/hermes-private-patch-registry-guard.py",
                "--publish-private-after-guard", "--private-update", "scripts/hermes-private-update.py",
                "--live", "/opt/hermes-agent", "--backup", "--rollout-restart-one",
                "--emergency-rollback-restart-max-one", "--registry-receipt", "registry.json",
                "--output", "promotion.json",
            ],
            [
                "audit", "--candidate", "c", "--packet", "p", "--approval", "a",
                "--promotion", "promotion.json", "--require-installed-generation-hash",
                "--require-gateway-health", "--require-telegram", "--require-approval-replay-denial",
                "--require-native-goal-checkpoint", "--require-supergoal-checkpoint", "--rollback-on-red",
                "--emergency-rollback-restart-max-one", "--audit", "audit.json",
            ],
        ]
        for argv in commands:
            with self.subTest(command=argv[0]):
                self.assertEqual(parser.parse_args(argv).command, argv[0])

    def test_approve_cli_forwards_owner_id_separately_from_origin(self) -> None:
        with patch("chip_supergoal.reviewed_rail.consume_approval_bundle") as consume:
            consume.return_value = {"schema": "receipt"}
            result = main([
                "approve", "--candidate", "c", "--packet", "p",
                "--require-installed-generation-hash", "--origin", "telegram:-1:2",
                "--owner-id", "617744661", "--direct-reply-only",
                "--consume-atomically", "--reject-replay", "--output", "approval.json",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(consume.call_args.kwargs["origin"], "telegram:-1:2")
        self.assertEqual(consume.call_args.kwargs["owner_id"], "617744661")

    def test_rollout_and_audit_fail_closed_without_side_effects(self) -> None:
        with patch("chip_supergoal.reviewed_rail._verify_approval_binding") as verify, patch(
            "chip_supergoal.reviewed_rail.subprocess.run"
        ) as run:
            verify.return_value = ({}, {}, {})
            with self.assertRaisesRegex(ArchitectureBlocker, ROLLOUT_DISABLED_ERROR):
                apply_reviewed_rollout(Path("candidate"), Path("packet"), Path("approval"), Path("promotion"))
            with self.assertRaisesRegex(ArchitectureBlocker, AUDIT_DISABLED_ERROR):
                audit_reviewed_rollout(
                    Path("candidate"),
                    Path("packet"),
                    Path("approval"),
                    Path("audit"),
                    promotion_path=Path("promotion"),
                )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
