import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.delivery import (
    MAX_DELIVERY_RECEIPT_BYTES,
    ReceiptValidationError,
    cancel_delivery_reservation,
    check_final_delivery,
    check_review_delivery,
    final_delivery_file,
    read_receipt,
    record_final_delivery,
    record_review_delivery,
    record_review_delivery_progress,
    review_delivery_files,
    send_final_delivery,
    show_delivery_reservation,
)
import chip_supergoal.delivery as delivery_module
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.archive import deterministic_zip
from chip_supergoal.state import StateStore
from chip_supergoal.validate import validate_package


class DeliveryReceiptSchemaTest(unittest.TestCase):
    def delivery_package(self, parent: Path, *, final: bool) -> Path:
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["profile"] = "chip-private"
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["compatibility"].pop("research_gate", None)
        data["delivery"] = {
            "items": ["artifact.zip"] if final else [],
            "receipt_policy": {"required": True},
            "review_pack_required": not final,
            "target": "current-thread",
            "transport": "telegram",
        }
        if not final:
            data["delivery"]["files"] = [
                "LAUNCH_GOAL.md",
                "LOOP_DESIGN.md",
                "ROADMAP.md",
                "THINKING.md",
            ]
        source = parent / "CONTRACT.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        return compile_contract_file(source, parent / "package")

    def test_sent_at_schema_requires_exact_rfc3339_utc_seconds(self):
        for name in (
            "review-md-files-delivery-receipt.schema.json",
            "final-artifacts-delivery-receipt.schema.json",
        ):
            with self.subTest(schema=name):
                schema = json.loads(
                    (ROOT / "templates/delivery" / name).read_text(encoding="utf-8")
                )
                pattern = schema["properties"]["sent_at"].get("pattern", "")
                self.assertIsNotNone(
                    re.fullmatch(pattern, "2026-07-11T12:34:56Z")
                )
                for invalid in (
                    "2026-07-11T12:34:56.123Z",
                    "2026-07-11T12:34:56+00:00",
                    "2026-07-11 12:34:56Z",
                ):
                    self.assertIsNone(re.fullmatch(pattern, invalid), invalid)

    def test_shell_receipt_producers_delegate_to_package_local_sgctl(self):
        expected = {
            "send-review-md-files.sh": (
                "delivery-review-check",
                "delivery-review-record",
            ),
            "send-final-artifacts.sh": (
                "delivery-final-check",
                "delivery-final-record",
            ),
        }
        for name, commands in expected.items():
            with self.subTest(script=name):
                script = (ROOT / "templates/delivery" / name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("$ROOT/scripts/sgctl.py", script)
                for command in commands:
                    self.assertIn(command, script)
                self.assertIn("--authorization-json", script)
                self.assertNotIn("json.dump", script)
                self.assertNotIn("<<'PY'", script)

    def test_final_wrapper_has_fail_closed_tristate_check_and_external_archive(self):
        script = (ROOT / "templates/delivery/send-final-artifacts.sh").read_text(
            encoding="utf-8"
        )
        self.assertRegex(script, r"case\s+\"?\$status\"?\s+in")
        self.assertRegex(script, r"0\)\s*[\s\S]*exit 0")
        self.assertRegex(script, r"10\)\s*;;")
        self.assertRegex(script, r"\*\)\s*exit")
        self.assertNotIn("$OUT/final-artifacts.zip", script)
        self.assertIn("${1:?", script)

    def test_forced_delivery_preflight_rejects_terminal_frozen_package(self):
        for final in (False, True):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.delivery_package(parent, final=final)
                archive = parent / "external.zip"
                if final:
                    deterministic_zip(
                        package,
                        archive,
                        package / "out/final-artifacts-manifest.json",
                    )
                (package / "reports").mkdir(exist_ok=True)
                (package / "reports/terminal-record.txt").write_text(
                    "frozen\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    ValueError, "SGV-STATE-TERMINAL-FROZEN"
                ):
                    if final:
                        check_final_delivery(
                            package,
                            target="current-thread",
                            archive=archive,
                            force=True,
                        )
                    else:
                        check_review_delivery(
                            package,
                            target="current-thread",
                            force=True,
                        )

    def test_forced_delivery_preflight_rejects_unsafe_receipt_leaf(self):
        for final in (False, True):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.delivery_package(parent, final=final)
                archive = parent / "external.zip"
                if final:
                    deterministic_zip(
                        package,
                        archive,
                        package / "out/final-artifacts-manifest.json",
                    )
                name = (
                    "final-artifacts-delivery-receipt.json"
                    if final
                    else "review-md-files-delivery-receipt.json"
                )
                (package / "out").mkdir(exist_ok=True)
                (package / "out" / name).mkdir()
                with self.assertRaisesRegex(
                    ReceiptValidationError, "SGV-DELIVERY-RECEIPT-INVALID"
                ):
                    if final:
                        check_final_delivery(
                            package,
                            target="current-thread",
                            archive=archive,
                            force=True,
                        )
                    else:
                        check_review_delivery(
                            package,
                            target="current-thread",
                            force=True,
                        )

    def test_final_authorization_cannot_rebind_sent_archive_to_new_generation(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.delivery_package(parent, final=True)
            archive = parent / "external.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            authorization = check_final_delivery(
                package,
                target="current-thread",
                archive=archive,
            ).authorization
            self.assertIsNotNone(authorization)
            with self.assertRaisesRegex(ValueError, "SGV-DELIVERY-SEND-PENDING"):
                StateStore(package).update(
                    expected_revision=1,
                    blocker={"archive_generation": "B"},
                )
            cancel_delivery_reservation(
                package,
                kind="final-artifacts",
                authorization=authorization,
                confirm_not_sent=True,
            )
            StateStore(package).update(
                expected_revision=1,
                blocker={"archive_generation": "B"},
            )
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            with self.assertRaisesRegex(
                ReceiptValidationError, "SGV-DELIVERY-SEND-PENDING"
            ):
                record_final_delivery(
                    package,
                    target="current-thread",
                    archive=archive,
                    message_id="transport-sent-generation-A",
                    authorization=authorization,
                )
            self.assertFalse(
                (package / "out/final-artifacts-delivery-receipt.json").exists()
            )

    def test_review_authorization_binds_state_and_ordered_file_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.delivery_package(parent, final=False)
            authorization = check_review_delivery(
                package, target="current-thread"
            ).authorization
            self.assertIsNotNone(authorization)
            with self.assertRaisesRegex(ValueError, "SGV-DELIVERY-SEND-PENDING"):
                StateStore(package).update(
                    expected_revision=1,
                    blocker={"review_generation": "B"},
                )
            cancel_delivery_reservation(
                package,
                kind="review-md-files",
                authorization=authorization,
                confirm_not_sent=True,
            )
            StateStore(package).update(
                expected_revision=1,
                blocker={"review_generation": "B"},
            )
            with self.assertRaisesRegex(
                ReceiptValidationError, "SGV-DELIVERY-SEND-PENDING"
            ):
                record_review_delivery(
                    package,
                    target="current-thread",
                    message_ids=[
                        f"sent-A-{name}" for name in authorization["files"]
                    ],
                    authorization=authorization,
                )
            self.assertFalse(
                (package / "out/review-md-files-delivery-receipt.json").exists()
            )

    def test_delivery_check_claim_is_single_consumer_until_recorded(self):
        for final in (False, True):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.delivery_package(parent, final=final)
                archive = parent / "external.zip"
                if final:
                    deterministic_zip(
                        package,
                        archive,
                        package / "out/final-artifacts-manifest.json",
                    )
                    first = check_final_delivery(
                        package,
                        target="current-thread",
                        archive=archive,
                    )
                    with self.assertRaisesRegex(
                        ReceiptValidationError, "SGV-DELIVERY-SEND-PENDING"
                    ):
                        check_final_delivery(
                            package,
                            target="current-thread",
                            archive=archive,
                        )
                    receipt = record_final_delivery(
                        package,
                        target="current-thread",
                        archive=archive,
                        message_id="only-transport-send",
                        authorization=first.authorization,
                    )
                    checked = check_final_delivery(
                        package,
                        target="current-thread",
                        archive=archive,
                    )
                else:
                    first = check_review_delivery(
                        package, target="current-thread"
                    )
                    with self.assertRaisesRegex(
                        ReceiptValidationError, "SGV-DELIVERY-SEND-PENDING"
                    ):
                        check_review_delivery(
                            package, target="current-thread"
                        )
                    receipt = record_review_delivery(
                        package,
                        target="current-thread",
                        message_ids=[
                            f"only-send-{name}"
                            for name in first.authorization["files"]
                        ],
                        authorization=first.authorization,
                    )
                    checked = check_review_delivery(
                        package, target="current-thread"
                    )
                self.assertEqual(checked.receipt, receipt)
                self.assertIsNone(checked.authorization)

    def test_review_preflight_rejects_sealed_review_file_drift(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.delivery_package(Path(td), final=False)
            (package / "THINKING.md").write_text(
                "FORGED OR SECRET CONTENT\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ReceiptValidationError, "SGV-DELIVERY-FILE-SET-MISMATCH"
            ):
                check_review_delivery(package, target="current-thread")

    def test_reservation_show_and_explicit_authorization_bound_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.delivery_package(Path(td), final=False)
            authorization = check_review_delivery(
                package, target="current-thread"
            ).authorization
            shown = show_delivery_reservation(
                package, kind="review-md-files"
            )
            self.assertEqual(shown["authorization"], authorization)
            self.assertEqual(shown["status"], "send_pending")
            with self.assertRaisesRegex(
                ReceiptValidationError, "explicit confirmation"
            ):
                cancel_delivery_reservation(
                    package,
                    kind="review-md-files",
                    authorization=authorization,
                    confirm_not_sent=False,
                )
            forged = json.loads(json.dumps(authorization))
            forged["target"] = "forged-target"
            with self.assertRaisesRegex(
                ReceiptValidationError, "stale or mismatched"
            ):
                cancel_delivery_reservation(
                    package,
                    kind="review-md-files",
                    authorization=forged,
                    confirm_not_sent=True,
                )
            result = cancel_delivery_reservation(
                package,
                kind="review-md-files",
                authorization=authorization,
                confirm_not_sent=True,
            )
            self.assertTrue(result["cancelled"])
            self.assertFalse(Path(authorization["stage"]["absolute_path"]).exists())
            with self.assertRaisesRegex(
                ReceiptValidationError, "no active delivery reservation"
            ):
                show_delivery_reservation(package, kind="review-md-files")

    def test_review_progress_resumes_only_unsent_staged_files(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.delivery_package(Path(td), final=False)
            authorization = check_review_delivery(
                package, target="current-thread"
            ).authorization
            staged = review_delivery_files(
                package,
                target="current-thread",
                authorization=authorization,
            )
            self.assertEqual(staged, authorization["files"])
            first = authorization["files"][0]
            record_review_delivery_progress(
                package,
                file=first,
                message_id="message-first",
                authorization=authorization,
            )
            with self.assertRaisesRegex(
                ReceiptValidationError, "durable transport progress"
            ):
                cancel_delivery_reservation(
                    package,
                    kind="review-md-files",
                    authorization=authorization,
                    confirm_not_sent=True,
                )
            # Recording the same transport result is idempotent.
            record_review_delivery_progress(
                package,
                file=first,
                message_id="message-first",
                authorization=authorization,
            )
            remaining = review_delivery_files(
                package,
                target="current-thread",
                authorization=authorization,
            )
            self.assertNotIn(first, remaining)
            for name in remaining:
                record_review_delivery_progress(
                    package,
                    file=name,
                    message_id=f"message-{name}",
                    authorization=authorization,
                )
            receipt = record_review_delivery(
                package,
                target="current-thread",
                message_ids=None,
                authorization=authorization,
            )
            expected = {
                first: "message-first",
                **{
                    name: f"message-{name}"
                    for name in remaining
                },
            }
            self.assertEqual(
                receipt["message_ids"],
                [expected[name] for name in authorization["files"]],
            )
            self.assertFalse(Path(authorization["stage"]["absolute_path"]).exists())

    def test_review_authorizes_and_stages_the_same_captured_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.delivery_package(Path(td), final=False)
            original_capture = delivery_module.capture_validated_package_snapshot

            def capture_then_mutate(root, **kwargs):
                captured = original_capture(root, **kwargs)
                (Path(root) / "THINKING.md").write_text(
                    "FORGED AFTER CAPTURE\n", encoding="utf-8"
                )
                return captured

            with mock.patch.object(
                delivery_module,
                "capture_validated_package_snapshot",
                side_effect=capture_then_mutate,
            ):
                authorization = check_review_delivery(
                    package, target="current-thread"
                ).authorization
            stage_root = Path(authorization["stage"]["absolute_path"])
            staged = {
                name: (stage_root / name).read_bytes()
                for name in authorization["files"]
            }
            self.assertNotEqual(staged["THINKING.md"], b"FORGED AFTER CAPTURE\n")
            self.assertEqual(
                hashlib.sha256(staged["THINKING.md"]).hexdigest(),
                authorization["hashes"]["THINKING.md"],
            )
            with self.assertRaisesRegex(
                ReceiptValidationError, "sealed review authority is invalid"
            ):
                review_delivery_files(
                    package,
                    target="current-thread",
                    authorization=authorization,
                )

    def test_final_transport_uses_captured_stage_not_mutable_archive_path(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.delivery_package(parent, final=True)
            archive = parent / "external.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            canonical = archive.read_bytes()
            authorization = check_final_delivery(
                package, target="current-thread", archive=archive
            ).authorization
            logical_name = final_delivery_file(
                package,
                target="current-thread",
                authorization=authorization,
            )
            staged = Path(authorization["stage"]["absolute_path"]) / logical_name
            archive.write_bytes(b"forged transport bytes")
            self.assertEqual(staged.read_bytes(), canonical)
            self.assertNotEqual(staged.read_bytes(), archive.read_bytes())
            archive.write_bytes(canonical)
            receipt = record_final_delivery(
                package,
                target="current-thread",
                archive=archive,
                message_id="transport-message",
                authorization=authorization,
            )
            self.assertEqual(receipt["hash"], hashlib.sha256(canonical).hexdigest())

    def test_final_send_keeps_verified_bytes_authoritative_through_popen(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.delivery_package(parent, final=True)
            archive = parent / "external.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            canonical = archive.read_bytes()
            authorization = check_final_delivery(
                package, target="current-thread", archive=archive
            ).authorization
            stage_file = (
                Path(authorization["stage"]["absolute_path"])
                / "final-artifacts.zip"
            )
            captured: list[bytes] = []

            class FakeProcess:
                def __init__(self):
                    self.stdout = io.BytesIO(b"transport-authority-id\n")

                def wait(self, timeout=None):
                    return 0

                def kill(self):
                    return None

            def fake_popen(arguments, **options):
                del arguments
                try:
                    stage_file.write_bytes(b"forged after verification")
                except OSError:
                    # Native Windows holds a read-only, no-write-share handle.
                    pass
                with open(options["env"]["SUPERGOAL_SEND_FILE"], "rb") as stream:
                    captured.append(stream.read())
                return FakeProcess()

            with mock.patch.dict(
                os.environ,
                {"SUPERGOAL_TRANSPORT_SEND_FILE_CMD": "configured-transport"},
            ), mock.patch.object(
                delivery_module.subprocess, "Popen", side_effect=fake_popen
            ):
                sent = send_final_delivery(
                    package,
                    target="current-thread",
                    authorization=authorization,
                )

            self.assertEqual(captured, [canonical])
            self.assertEqual(sent["status"], "record_required")
            self.assertEqual(
                sent["progress"]["archive"]["message_id"],
                "transport-authority-id",
            )
            # POSIX permits replacing the original stage after the anonymous
            # copy is made; restore it so the conservative record gate can
            # prove the reservation snapshot is still intact.
            if stage_file.read_bytes() != canonical:
                stage_file.write_bytes(canonical)
            receipt = record_final_delivery(
                package,
                target="current-thread",
                archive=archive,
                message_id=None,
                authorization=authorization,
            )
            self.assertEqual(receipt["message_id"], "transport-authority-id")

    @unittest.skipUnless(os.name == "nt", "native Windows transport only")
    def test_final_send_runs_real_transport_from_unicode_path_on_windows(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "transport path Ж 🚀"
            workspace.mkdir()
            package = self.delivery_package(workspace, final=True)
            archive = workspace / "final artifact 🚀.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            canonical = archive.read_bytes()
            authorization = check_final_delivery(
                package, target="current-thread", archive=archive
            ).authorization
            helper = workspace / "transport helper Ж.py"
            capture = workspace / "captured payload 🚀.bin"
            helper.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "source = Path(os.environ['SUPERGOAL_SEND_FILE'])\n"
                "capture = Path(os.environ['SUPERGOAL_TEST_CAPTURE'])\n"
                "capture.write_bytes(source.read_bytes())\n"
                "print('native-windows-transport-id')\n",
                encoding="utf-8",
                newline="\n",
            )
            command = subprocess.list2cmdline([sys.executable, str(helper)])

            with mock.patch.dict(
                os.environ,
                {
                    "SUPERGOAL_TRANSPORT_SEND_FILE_CMD": command,
                    "SUPERGOAL_TEST_CAPTURE": str(capture),
                },
            ):
                sent = send_final_delivery(
                    package,
                    target="current-thread",
                    authorization=authorization,
                )

            self.assertEqual(capture.read_bytes(), canonical)
            self.assertEqual(sent["status"], "record_required")
            self.assertEqual(
                sent["progress"]["archive"]["message_id"],
                "native-windows-transport-id",
            )

    def test_invalid_transport_timeout_and_target_fail_before_popen(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.delivery_package(parent, final=True)
            archive = parent / "external.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            authorization = check_final_delivery(
                package, target="current-thread", archive=archive
            ).authorization
            with mock.patch.dict(
                os.environ,
                {
                    "SUPERGOAL_TRANSPORT_SEND_FILE_CMD": "configured-transport",
                    "SUPERGOAL_TRANSPORT_TIMEOUT_SECONDS": "invalid",
                },
            ), mock.patch.object(delivery_module.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    ReceiptValidationError, "transport timeout is invalid"
                ):
                    send_final_delivery(
                        package,
                        target="current-thread",
                        authorization=authorization,
                    )
                popen.assert_not_called()
            with mock.patch.dict(
                os.environ,
                {"SUPERGOAL_TRANSPORT_SEND_FILE_CMD": "configured-transport"},
            ), mock.patch.object(delivery_module.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    ReceiptValidationError, "TARGET-MISMATCH"
                ):
                    send_final_delivery(
                        package,
                        target="wrong-thread",
                        authorization=authorization,
                    )
                popen.assert_not_called()

    def test_message_ids_are_bounded_single_line_values(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.delivery_package(Path(td), final=False)
            authorization = check_review_delivery(
                package, target="current-thread"
            ).authorization
            with self.assertRaisesRegex(
                ReceiptValidationError, "MESSAGE-ID-MISMATCH"
            ):
                record_review_delivery(
                    package,
                    target="current-thread",
                    message_ids=["bad\nmessage"] * len(authorization["files"]),
                    authorization=authorization,
                )

    def test_wrappers_preflight_static_transport_before_reserving(self):
        for name, check_command in (
            ("send-review-md-files.sh", "delivery-review-check"),
            ("send-final-artifacts.sh", "delivery-final-check"),
        ):
            with self.subTest(wrapper=name):
                script = (ROOT / "templates/delivery" / name).read_text(
                    encoding="utf-8"
                )
                self.assertLess(
                    script.index("SUPERGOAL_TRANSPORT_SEND_FILE_CMD"),
                    script.index(check_command),
                )

    def test_process_death_during_receipt_publish_retries_without_resend(self):
        child = r'''
import json
import os
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
sys.path.insert(0, str(source_root / "lib"))
import chip_supergoal.portable as portable
from chip_supergoal.delivery import record_final_delivery, record_review_delivery

kind = sys.argv[2]
package = Path(sys.argv[3])
archive = Path(sys.argv[4]) if sys.argv[4] != "-" else None
authorization = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
receipt_name = (
    "review-md-files-delivery-receipt.json"
    if kind == "review"
    else "final-artifacts-delivery-receipt.json"
)
receipt_path = package / "out" / receipt_name

def checkpoint(target, temporary):
    del temporary
    if Path(target) == receipt_path:
        os._exit(91)

portable._atomic_write_checkpoint = checkpoint
if kind == "review":
    record_review_delivery(
        package,
        target="current-thread",
        message_ids=[f"message-{name}" for name in authorization["files"]],
        authorization=authorization,
    )
else:
    record_final_delivery(
        package,
        target="current-thread",
        archive=archive,
        message_id="final-message",
        authorization=authorization,
    )
'''
        for final in (False, True):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.delivery_package(parent, final=final)
                archive = parent / "external.zip"
                if final:
                    deterministic_zip(
                        package,
                        archive,
                        package / "out/final-artifacts-manifest.json",
                    )
                    authorization = check_final_delivery(
                        package, target="current-thread", archive=archive
                    ).authorization
                else:
                    authorization = check_review_delivery(
                        package, target="current-thread"
                    ).authorization
                authorization_path = parent / "authorization.json"
                authorization_path.write_text(
                    json.dumps(authorization), encoding="utf-8"
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        child,
                        str(ROOT),
                        "final" if final else "review",
                        str(package),
                        str(archive) if final else "-",
                        str(authorization_path),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    completed.returncode,
                    91,
                    completed.stdout + completed.stderr,
                )
                if final:
                    receipt = record_final_delivery(
                        package,
                        target="current-thread",
                        archive=archive,
                        message_id="final-message",
                        authorization=authorization,
                    )
                    pending = package / "out/final-artifacts-delivery-receipt.pending.json"
                    reservation = package / "runtime/final-delivery-reservation.json"
                else:
                    ids = [
                        f"message-{name}" for name in authorization["files"]
                    ]
                    receipt = record_review_delivery(
                        package,
                        target="current-thread",
                        message_ids=ids,
                        authorization=authorization,
                    )
                    pending = package / "out/review-md-files-delivery-receipt.pending.json"
                    reservation = package / "runtime/review-delivery-reservation.json"
                self.assertTrue(receipt["sent"])
                self.assertFalse(pending.exists())
                self.assertFalse(reservation.exists())
                self.assertFalse(Path(authorization["stage"]["absolute_path"]).exists())

    def test_process_death_during_reservation_or_stage_has_supported_cleanup(self):
        child = r'''
import os
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
sys.path.insert(0, str(source_root / "lib"))
import chip_supergoal.portable as portable
from chip_supergoal.delivery import check_final_delivery, check_review_delivery

kind = sys.argv[2]
mode = sys.argv[3]
package = Path(sys.argv[4])
archive = Path(sys.argv[5]) if sys.argv[5] != "-" else None
reservation = package / "runtime" / (
    "final-delivery-reservation.json"
    if kind == "final"
    else "review-delivery-reservation.json"
)

def checkpoint(target, temporary):
    del temporary
    target = Path(target)
    if mode == "reservation" and target == reservation:
        os._exit(92)
    if mode == "stage" and ".review-delivery-" in target.parent.name and target.name != ".supergoal-delivery-stage.json":
        os._exit(92)
    if mode == "stage" and ".final-delivery-" in target.parent.name and target.name == "final-artifacts.zip":
        os._exit(92)

portable._atomic_write_checkpoint = checkpoint
if kind == "final":
    check_final_delivery(package, target="current-thread", archive=archive)
else:
    check_review_delivery(package, target="current-thread")
'''
        for final in (False, True):
            for mode in ("reservation", "stage"):
                with self.subTest(final=final, mode=mode), tempfile.TemporaryDirectory() as td:
                    parent = Path(td)
                    package = self.delivery_package(parent, final=final)
                    archive = parent / "external.zip"
                    if final:
                        deterministic_zip(
                            package,
                            archive,
                            package / "out/final-artifacts-manifest.json",
                        )
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            child,
                            str(ROOT),
                            "final" if final else "review",
                            mode,
                            str(package),
                            str(archive) if final else "-",
                        ],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(
                        completed.returncode,
                        92,
                        completed.stdout + completed.stderr,
                    )
                    kind = "final-artifacts" if final else "review-md-files"
                    if mode == "reservation":
                        with self.assertRaisesRegex(
                            ReceiptValidationError,
                            "no active delivery reservation",
                        ):
                            show_delivery_reservation(package, kind=kind)
                    else:
                        shown = show_delivery_reservation(package, kind=kind)
                        authorization = shown["authorization"]
                        cancel_delivery_reservation(
                            package,
                            kind=kind,
                            authorization=authorization,
                            confirm_not_sent=True,
                        )
                        self.assertFalse(
                            Path(authorization["stage"]["absolute_path"]).exists(),
                            f"stage remained for final={final}: {authorization['stage']['absolute_path']}",
                        )
                    self.assertEqual(validate_package(package), [])

    def test_process_death_after_stage_marker_cleanup_is_resumable(self):
        child = r'''
import json
import os
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
sys.path.insert(0, str(source_root / "lib"))
import chip_supergoal.delivery as delivery

kind = sys.argv[2]
package = Path(sys.argv[3])
archive = Path(sys.argv[4]) if sys.argv[4] != "-" else None
authorization = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
original_unlink = delivery.unlink_regular_file_no_follow

def unlink_then_die(path, *args, **kwargs):
    removed = original_unlink(path, *args, **kwargs)
    if removed and Path(path).name == ".supergoal-delivery-stage.json":
        os._exit(93)
    return removed

delivery.unlink_regular_file_no_follow = unlink_then_die
if kind == "review":
    delivery.record_review_delivery(
        package,
        target="current-thread",
        message_ids=[f"message-{name}" for name in authorization["files"]],
        authorization=authorization,
    )
else:
    delivery.record_final_delivery(
        package,
        target="current-thread",
        archive=archive,
        message_id="final-message",
        authorization=authorization,
    )
'''
        for final in (False, True):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.delivery_package(parent, final=final)
                archive = parent / "external.zip"
                if final:
                    deterministic_zip(
                        package,
                        archive,
                        package / "out/final-artifacts-manifest.json",
                    )
                    authorization = check_final_delivery(
                        package, target="current-thread", archive=archive
                    ).authorization
                else:
                    authorization = check_review_delivery(
                        package, target="current-thread"
                    ).authorization
                authorization_path = parent / "authorization.json"
                authorization_path.write_text(
                    json.dumps(authorization), encoding="utf-8"
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        child,
                        str(ROOT),
                        "final" if final else "review",
                        str(package),
                        str(archive) if final else "-",
                        str(authorization_path),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    completed.returncode,
                    93,
                    completed.stdout + completed.stderr,
                )
                if final:
                    receipt = record_final_delivery(
                        package,
                        target="current-thread",
                        archive=archive,
                        message_id="final-message",
                        authorization=authorization,
                    )
                else:
                    receipt = record_review_delivery(
                        package,
                        target="current-thread",
                        message_ids=[
                            f"message-{name}" for name in authorization["files"]
                        ],
                        authorization=authorization,
                    )
                self.assertTrue(receipt["sent"])
                self.assertFalse(
                    Path(authorization["stage"]["absolute_path"]).exists()
                )

    def test_receipt_reader_enforces_bounded_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "receipt.json"
            path.write_bytes(b"x" * (MAX_DELIVERY_RECEIPT_BYTES + 1))
            with self.assertRaisesRegex(ReceiptValidationError, "bounded"):
                read_receipt(path, root)

    @unittest.skipUnless(
        os.name == "posix" and shutil.which("bash"),
        "POSIX wrapper integration unavailable",
    )
    def test_final_wrapper_sends_once_then_retry_sends_zero(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            data = json.loads(
                (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                    encoding="utf-8"
                )
            )
            data["profile"] = "chip-private"
            data["risks"] = []
            data["phases"][0]["risk_tags"] = []
            data["phases"][0]["rpd"] = {"required": False, "focus": []}
            data["compatibility"].pop("research_gate", None)
            data["delivery"] = {
                "items": ["artifact.zip"],
                "receipt_policy": {"required": True},
                "review_pack_required": False,
                "target": "current-thread",
                "transport": "telegram",
            }
            source = parent / "CONTRACT.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            package = compile_contract_file(
                source,
                parent / "package",
            )
            archive = parent / "external.zip"
            deterministic_zip(
                package,
                archive,
                package / "out/final-artifacts-manifest.json",
            )
            wrapper = package / "templates/delivery/send-final-artifacts.sh"
            self.assertTrue(wrapper.is_file())
            counter = parent / "transport-count.txt"
            transport = parent / "fake-transport.sh"
            transport.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"counter={str(counter)!r}\n"
                "count=0\n"
                "[[ ! -f \"$counter\" ]] || count=$(cat \"$counter\")\n"
                "count=$((count + 1))\n"
                "printf '%s\\n' \"$count\" >\"$counter\"\n"
                "printf 'message-%s\\n' \"$count\"\n",
                encoding="utf-8",
                newline="\n",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PYTHON": sys.executable,
                    "SUPERGOAL_ROOT": str(package),
                    "SUPERGOAL_DELIVERY_TARGET": "current-thread",
                    "SUPERGOAL_TRANSPORT_SEND_FILE_CMD": f'bash "{transport}"',
                }
            )
            for expected_count in ("1", "1"):
                completed = subprocess.run(
                    ["bash", str(wrapper), str(archive)],
                    cwd=parent,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stdout + completed.stderr
                )
                self.assertEqual(counter.read_text(encoding="utf-8").strip(), expected_count)
            self.assertTrue(
                (package / "out/final-artifacts-delivery-receipt.json").is_file()
            )

    def test_receipt_reader_rejects_nonfinite_extension_values(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "receipt.json"
            path.write_text(
                json.dumps(
                    {"extensions": {"not_json": float("nan")}},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(ReceiptValidationError, "malformed"):
                read_receipt(path, root)


if __name__ == "__main__":
    unittest.main()
