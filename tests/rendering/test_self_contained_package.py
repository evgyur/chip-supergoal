import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import CompileSafetyError, compile_contract_file
import chip_supergoal.compile as compile_module
import chip_supergoal.portable as portable_module
import chip_supergoal.state as state_module
import chip_supergoal.validate as validate_module
from chip_supergoal.diagnostics import Diagnostic
from chip_supergoal.events import append_event, read_events, verify_event_chain
from chip_supergoal.state import State, StateStore, read_state, recover_from_events, render_state_md, write_state_atomic
from chip_supergoal.validate import validate_package


CONTRACT = ROOT / "examples" / "brownfield-feature" / "CONTRACT.json"


def package_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


EXPECTED_MUTABLE_PATHS = [
    {"path": "STATE.md", "required": True, "validation": "state_projection"},
    {"path": "runtime/STATE.json", "required": True, "validation": "state_schema_identity"},
    {"path": "runtime/events.jsonl", "required": True, "validation": "event_chain_identity_revision"},
    {"path": "runtime/evidence.json", "required": True, "validation": "evidence_json_array"},
    {"path": "runtime/state.lock", "required": False, "validation": "one_byte_lock"},
    {"path": "reports/final-audit.json", "required": False, "validation": "final_audit_json"},
    {"path": "reports/final-audit.md", "required": False, "validation": "final_audit_projection"},
    {"path": "reports/terminal-record.txt", "required": False, "validation": "terminal_record"},
    {"path": "out/review-md-files-delivery-receipt.json", "required": False, "validation": "review_delivery_receipt"},
    {"path": "out/final-artifacts-delivery-receipt.json", "required": False, "validation": "final_delivery_receipt"},
    {"path": "out/final-artifacts-manifest.json", "required": False, "validation": "archive_result"},
]


def diagnostic_codes(root: Path) -> set[str]:
    return {diagnostic.code for diagnostic in validate_package(root)}


def reseal_artifact(package: Path, relative: str) -> None:
    manifest_path = package / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = (package / relative).read_bytes()
    record = next(item for item in manifest["artifacts"] if item["path"] == relative)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    record["bytes"] = len(data)
    joined = "\n".join(
        f"{item['path']} {item['sha256']} {item['bytes']} {item['mode']}"
        for item in manifest["artifacts"]
    )
    manifest["package_fingerprint"] = hashlib.sha256(joined.encode()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class SelfContainedPackageTest(unittest.TestCase):
    def compile_package(self, parent: Path) -> Path:
        return compile_contract_file(CONTRACT, parent / "package")

    def test_compiler_resource_copy_does_not_reopen_verified_source_by_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_text("verified source\n", encoding="utf-8")
            with mock.patch.object(Path, "read_text", return_value="swapped outside\n"):
                compile_module._copy_text(source, destination, source_root=root)
            self.assertEqual(destination.read_text(encoding="utf-8"), "verified source\n")

    def test_validator_consumes_sealed_file_from_verified_handle(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            target = package / "THINKING.md"
            original_read_bytes = Path.read_bytes

            def swapped_path_read(path: Path) -> bytes:
                if path == target:
                    return b"swapped outside bytes\n"
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", swapped_path_read):
                diagnostics = validate_package(package)

            self.assertEqual(diagnostics, [])

    def test_validator_resolves_package_local_profile_and_policy_from_verified_handles(self):
        targets = ("profiles/base.json", "spec/risk-policy.json")
        for relative in targets:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                package = self.compile_package(Path(td))
                target = package / relative
                original_read_text = Path.read_text

                def swapped_path_read(path: Path, *args, **kwargs) -> str:
                    if path == target:
                        return "{}\n"
                    return original_read_text(path, *args, **kwargs)

                with mock.patch.object(Path, "read_text", swapped_path_read):
                    diagnostics = validate_package(package)

                self.assertEqual(diagnostics, [])

    def test_validator_fails_closed_when_verified_handle_open_detects_swap(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            target = package / "THINKING.md"
            original_reader = validate_module.read_regular_file_no_follow

            def reject_swapped_file(path: Path, root: Path) -> bytes:
                if Path(path) == target:
                    raise portable_module.UnsafeFileError(
                        path,
                        "symlink swapped before handle open",
                        kind="symlink",
                    )
                return original_reader(path, root)

            with mock.patch(
                "chip_supergoal.validate.read_regular_file_no_follow",
                side_effect=reject_swapped_file,
            ):
                try:
                    diagnostics = validate_package(package)
                except portable_module.UnsafeFileError as exc:
                    self.fail(f"validator leaked unsafe handle-open failure: {exc}")

            self.assertTrue(
                any(
                    item.code == "SGV-PACKAGE-SYMLINK"
                    and item.pointer == "/THINKING.md"
                    for item in diagnostics
                ),
                diagnostics,
            )

    def test_explicit_runtime_inventory_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))

            required = {
                "scripts/sgctl.py",
                "lib/chip_supergoal/__init__.py",
                "lib/chip_supergoal/compile.py",
                "lib/chip_supergoal/audit.py",
                "lib/chip_supergoal/delivery.py",
                "lib/chip_supergoal/evidence.py",
                "lib/chip_supergoal/events.py",
                "lib/chip_supergoal/state.py",
                "lib/chip_supergoal/terminal.py",
                "lib/chip_supergoal/validate.py",
                "templates/PROTOCOL.md",
                "spec/risk-policy.json",
                "spec/diagnostic-catalog.json",
                "spec/state.schema.json",
                "spec/evidence.schema.json",
                "spec/final-audit.schema.json",
                "spec/marker-contract.json",
                "spec/state-machine.json",
                "templates/delivery/final-artifacts-delivery-receipt.schema.json",
                "templates/delivery/review-md-files-delivery-receipt.schema.json",
                "profiles/base.json",
                "profiles/public-clean.json",
                "profiles/chip-private.json",
                "scripts/validate-phase.sh",
                "scripts/validate-loop-design.sh",
                "scripts/repo-state.sh",
                "scripts/detect-stack.sh",
                "scripts/summarize-repo.sh",
            }
            self.assertTrue(required <= package_files(package))

    def test_library_compile_uses_canonical_protocol_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))

            canonical = (ROOT / "templates" / "PROTOCOL.md").read_bytes().replace(
                b"\r\n", b"\n"
            )
            self.assertEqual((package / "PROTOCOL.md").read_bytes(), canonical)
            self.assertEqual((package / "templates" / "PROTOCOL.md").read_bytes(), canonical)

    def test_manifest_1_1_records_source_and_emitted_contract_identity(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source_data = json.loads(CONTRACT.read_text(encoding="utf-8"))
            source_data["profile"] = "public-clean"
            source = parent / "public-clean.json"
            source.write_text(
                json.dumps(source_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            package = compile_contract_file(source, parent / "package")
            manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["manifest_version"], "1.1")
            self.assertEqual(
                manifest["source_contract_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["contract_sha256"],
                hashlib.sha256((package / "CONTRACT.json").read_bytes()).hexdigest(),
            )
            self.assertNotEqual(
                manifest["source_contract_sha256"], manifest["contract_sha256"]
            )
            self.assertIn("mutable_paths", manifest)

    def test_custom_valid_risk_policy_becomes_package_local_authority(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            policy = json.loads((ROOT / "spec" / "risk-policy.json").read_text(encoding="utf-8"))
            policy["policy_test_marker"] = "package-local"
            custom_policy = parent / "custom-risk-policy.json"
            custom_policy.write_text(
                json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            package = compile_contract_file(
                CONTRACT,
                parent / "package",
                risk_policy_path=custom_policy,
            )

            self.assertEqual(
                (package / "spec" / "risk-policy.json").read_bytes(),
                custom_policy.read_bytes(),
            )
            self.assertEqual(validate_package(package), [])

    def test_manifest_has_exact_mutable_registry_and_excludes_mutable_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))

            self.assertEqual(
                set(manifest),
                {
                    "manifest_version",
                    "source_contract_sha256",
                    "contract_sha256",
                    "artifacts",
                    "mutable_paths",
                    "package_fingerprint",
                },
            )
            self.assertEqual(manifest["mutable_paths"], EXPECTED_MUTABLE_PATHS)
            sealed = {item["path"] for item in manifest["artifacts"]}
            self.assertTrue({item["path"] for item in EXPECTED_MUTABLE_PATHS}.isdisjoint(sealed))
            for item in EXPECTED_MUTABLE_PATHS:
                if item["required"]:
                    self.assertTrue((package / item["path"]).is_file(), item["path"])

    def test_initial_mutable_plane_uses_lowest_ready_phase_and_emitted_identity(self):
        source_data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        original = source_data["phases"][0]

        def phase(phase_id: str, ordinal: int, dependencies: list[str]) -> dict:
            value = json.loads(json.dumps(original))
            value["id"] = phase_id
            value["ordinal"] = ordinal
            value["name"] = f"Phase {phase_id}"
            value["depends_on"] = dependencies
            for index, criterion in enumerate(value["criteria"], 1):
                criterion["id"] = f"{phase_id}-C{index:02d}"
                criterion["verifier"]["command_id"] = f"{phase_id}-CMD01"
            for index, command in enumerate(value["commands"], 1):
                command["id"] = f"{phase_id}-CMD{index:02d}"
            for index, deliverable in enumerate(value["deliverables"], 1):
                deliverable["id"] = f"{phase_id}-D{index:02d}"
            for index, work_item in enumerate(value["work_items"], 1):
                work_item["id"] = f"{phase_id}-W{index:02d}"
            return value

        source_data["phases"] = [
            phase("P03", 3, ["P02"]),
            phase("P01", 1, ["P02"]),
            phase("P02", 2, []),
        ]
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            source = parent / "CONTRACT.json"
            source.write_text(json.dumps(source_data), encoding="utf-8")
            package = compile_contract_file(source, parent / "package")

            state_path = package / "runtime" / "STATE.json"
            state = read_state(state_path)
            contract_hash = hashlib.sha256((package / "CONTRACT.json").read_bytes()).hexdigest()
            self.assertEqual(state.schema_version, "3.0")
            self.assertEqual(state.contract_revision, 1)
            self.assertEqual(state.lifecycle, "COMPILED")
            self.assertEqual(state.state_revision, 1)
            self.assertEqual(state.current_phase_id, "P02")
            self.assertEqual(state.phase_status, "PENDING")
            self.assertEqual((state.attempt, state.audit_round), (0, 0))
            self.assertEqual(state.contract_sha256, contract_hash)
            self.assertEqual((package / "STATE.md").read_text(encoding="utf-8"), render_state_md(state))
            self.assertEqual((package / "runtime" / "evidence.json").read_bytes(), b"[]\n")

            events = read_events(package / "runtime" / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(verify_event_chain(events), [])
            event = events[0]
            self.assertEqual(event["event_type"], "state_initialized")
            self.assertEqual(event["prev_event_sha256"], None)
            self.assertEqual(event["state_revision"], 1)
            self.assertEqual(event["goal_id"], state.goal_id)
            self.assertEqual(event["contract_sha256"], contract_hash)
            self.assertEqual(event["contract_revision"], state.contract_revision)
            self.assertEqual(event["state"], state.to_dict())
            self.assertEqual(event["state_sha256"], hashlib.sha256(state_path.read_bytes()).hexdigest())

    def test_validator_requires_recovery_when_journal_tail_is_ahead_of_projections(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            store = StateStore(package)
            current = read_state(store.state_json)

            with mock.patch.object(
                state_module,
                "write_state_atomic",
                side_effect=OSError("injected projection crash"),
            ):
                with self.assertRaisesRegex(OSError, "projection crash"):
                    store.transition(
                        "PLAN_REVIEWED",
                        expected_revision=current.state_revision,
                    )

            diagnostics = validate_package(package)
            recovery = [
                item
                for item in diagnostics
                if item.code == "SGV-PACKAGE-STATE-RECOVERY-REQUIRED"
            ]
            self.assertEqual(len(recovery), 1, diagnostics)
            self.assertNotIn(
                "SGV-PACKAGE-EVENTS-MALFORMED",
                {item.code for item in diagnostics},
            )

            recovered = recover_from_events(package)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.state.state_revision, current.state_revision + 1)
            self.assertEqual(validate_package(package), [])

    def test_recovery_rejects_valid_journal_from_a_different_package(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package_a = self.compile_package(parent / "a")
            source_data = json.loads(CONTRACT.read_text(encoding="utf-8"))
            source_data["goal"]["id"] = "sg-20260711-recovery-package-b"
            source_b = parent / "CONTRACT-B.json"
            source_b.write_text(json.dumps(source_data), encoding="utf-8")
            package_b = compile_contract_file(source_b, parent / "package-b")

            state_a = read_state(package_a / "runtime/STATE.json")
            StateStore(package_a).transition(
                "PLAN_REVIEWED",
                expected_revision=state_a.state_revision,
            )
            shutil.copyfile(
                package_a / "runtime/events.jsonl",
                package_b / "runtime/events.jsonl",
            )
            state_before = (package_b / "runtime/STATE.json").read_bytes()
            markdown_before = (package_b / "STATE.md").read_bytes()

            with self.assertRaisesRegex(
                ValueError,
                "SGV-STATE-JOURNAL-CORRUPT",
            ):
                recover_from_events(package_b)

            self.assertEqual(
                (package_b / "runtime/STATE.json").read_bytes(),
                state_before,
            )
            self.assertEqual((package_b / "STATE.md").read_bytes(), markdown_before)

    def test_relocated_package_validates_with_scrubbed_python_environment(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            moved = parent / "outside source" / ".supergoal" / "slug"
            moved.parent.mkdir(parents=True)
            shutil.move(package, moved)
            clean_cwd = parent / "clean cwd"
            clean_cwd.mkdir()
            env = os.environ.copy()
            env["PYTHONPATH"] = ""
            env["PYTHONNOUSERSITE"] = "1"
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            env["PYTHONUTF8"] = "1"

            result = subprocess.run(
                [
                    sys.executable,
                    str(moved / "scripts" / "sgctl.py"),
                    "validate-package",
                    str(moved),
                    "--strict",
                ],
                cwd=clean_cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn(str(ROOT), result.stdout + result.stderr)

    def test_package_local_protocol_mutation_is_detected_after_resealing(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            local_template = package / "templates" / "PROTOCOL.md"
            local_template.write_text("# mutated package protocol\n", encoding="utf-8")
            reseal_artifact(package, "templates/PROTOCOL.md")

            diagnostics = validate_package(package)

            drift = [item for item in diagnostics if item.code == "SGV-PACKAGE-GENERATED-DRIFT"]
            self.assertTrue(any(item.pointer == "/PROTOCOL.md" for item in drift), diagnostics)
            self.assertNotIn("SGV-PACKAGE-MANIFEST-HASH", {item.code for item in diagnostics})

    def test_runtime_mutation_does_not_change_sealed_fingerprint_or_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            manifest_before = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
            state_path = package / "runtime" / "STATE.json"
            state = read_state(state_path)
            updated = replace(state, state_revision=2, lifecycle="PLAN_REVIEWED")
            write_state_atomic(state_path, updated)
            (package / "STATE.md").write_text(render_state_md(updated), encoding="utf-8", newline="\n")
            append_event(
                package / "runtime" / "events.jsonl",
                state=updated.to_dict(),
                event_type="transition:COMPILED->PLAN_REVIEWED",
            )
            evidence = [{
                "evidence_id": "EV-001",
                "goal_id": updated.goal_id,
                "contract_sha256": updated.contract_sha256,
                "contract_revision": 1,
                "phase_id": updated.current_phase_id,
                "criterion_id": "P01-C01",
                "type": "command_result",
                "producer": "test",
                "captured_at": "2026-07-11T00:00:00Z",
                "fresh_until": "audit_end",
                "replayable": True,
                "result": "unverified",
                "redaction": "passed",
                "command": "python3 -m unittest",
                "exit_code": 1,
                "assertion": "test passes",
            }]
            (package / "runtime" / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            diagnostics = validate_package(package)
            manifest_after = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest_after["package_fingerprint"], manifest_before["package_fingerprint"])
            self.assertNotIn(
                {"SGV-PACKAGE-MANIFEST-HASH", "SGV-PACKAGE-FINGERPRINT-MISMATCH"},
                {item.code for item in diagnostics},
            )
            self.assertEqual(diagnostics, [])

    def test_malformed_mutable_files_have_targeted_diagnostics(self):
        mutations = {
            "state": ("runtime/STATE.json", b"{broken", "SGV-PACKAGE-STATE-MALFORMED"),
            "events": ("runtime/events.jsonl", b"{broken\n", "SGV-PACKAGE-EVENTS-MALFORMED"),
            "evidence": ("runtime/evidence.json", b"{}\n", "SGV-PACKAGE-EVIDENCE-MALFORMED"),
        }
        for label, (relative, content, expected_code) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                package = self.compile_package(Path(td))
                (package / relative).write_bytes(content)
                self.assertIn(expected_code, diagnostic_codes(package))

    def test_optional_mutable_outputs_use_their_semantic_validators(self):
        cases = {
            "final_audit_json": ("reports/final-audit.json", b"{}\n", "SGV-PACKAGE-MUTABLE-MALFORMED", "/reports/final-audit.json"),
            "final_audit_markdown": ("reports/final-audit.md", b"# forged audit\n", "SGV-PACKAGE-MUTABLE-MALFORMED", "/reports/final-audit.json"),
            "terminal_record": ("reports/terminal-record.txt", b"AUDIT_COMPLETE\n", "SGV-PACKAGE-MUTABLE-MALFORMED", "/reports/terminal-record.txt"),
            "review_receipt": ("out/review-md-files-delivery-receipt.json", b"{}\n", "SGV-PACKAGE-MUTABLE-MALFORMED", "/out/review-md-files-delivery-receipt.json"),
            "final_receipt": ("out/final-artifacts-delivery-receipt.json", b"{}\n", "SGV-PACKAGE-MUTABLE-MALFORMED", "/out/final-artifacts-delivery-receipt.json"),
            "archive_result": ("out/final-artifacts-manifest.json", b"{}\n", "SGV-PACKAGE-MUTABLE-UNSUPPORTED", "/out/final-artifacts-manifest.json"),
        }
        for label, (relative, content, expected_code, expected_pointer) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                package = self.compile_package(Path(td))
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

                diagnostics = validate_package(package)
                targeted = [
                    item
                    for item in diagnostics
                    if item.code == expected_code
                    and item.pointer == expected_pointer
                ]

                self.assertEqual(len(targeted), 1, diagnostics)

    def test_missing_state_projection_is_reported_once(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            (package / "STATE.md").unlink()

            diagnostics = validate_package(package)
            missing = [
                item
                for item in diagnostics
                if item.code == "SGV-PACKAGE-MISSING-FILE"
                and item.pointer == "/STATE.md"
            ]

            self.assertEqual(len(missing), 1, diagnostics)

    def test_unknown_files_and_nested_manifest_are_blocked(self):
        for relative in ("UNSEALED.md", "out/evil.json", "nested/MANIFEST.json"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                package = self.compile_package(Path(td))
                extra = package / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text("unsealed\n", encoding="utf-8")
                self.assertIn("SGV-PACKAGE-MANIFEST-FILESET", diagnostic_codes(package))

    def test_unknown_empty_directory_fails_exact_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            (package / "unknown-empty-directory").mkdir()

            self.assertIn("SGV-PACKAGE-MANIFEST-FILESET", diagnostic_codes(package))

    def test_optional_mutable_directory_is_not_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            path = package / "reports" / "final-audit.json"
            path.mkdir(parents=True)

            diagnostics = validate_package(package)

            self.assertTrue(
                any(
                    item.code == "SGV-PACKAGE-SPECIAL-FILE"
                    and item.pointer == "/reports/final-audit.json"
                    for item in diagnostics
                ),
                diagnostics,
            )

    def test_validator_rejects_sealed_and_mutable_file_symlinks(self):
        cases = {
            "sealed": "THINKING.md",
            "mutable": "runtime/evidence.json",
        }
        for label, relative in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.compile_package(parent)
                path = package / relative
                outside = parent / f"outside-{label}.txt"
                outside.write_bytes(path.read_bytes())
                path.unlink()
                try:
                    path.symlink_to(outside)
                except OSError as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")

                diagnostics = validate_package(package)

                self.assertIn("SGV-PACKAGE-SYMLINK", {item.code for item in diagnostics})
                self.assertTrue(
                    any(item.pointer == f"/{relative}" for item in diagnostics),
                    diagnostics,
                )

    def test_validator_rejects_unknown_symlink_directory_without_following_it(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            outside = parent / "outside-directory"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside\n", encoding="utf-8")
            linked = package / "linked-directory"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")

            diagnostics = validate_package(package)

            self.assertIn("SGV-PACKAGE-SYMLINK", {item.code for item in diagnostics})
            self.assertTrue(
                any(item.pointer == "/linked-directory" for item in diagnostics),
                diagnostics,
            )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unsupported")
    def test_validator_rejects_special_file_without_opening_it(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            fifo = package / "runtime" / "unexpected.fifo"
            os.mkfifo(fifo)

            diagnostics = validate_package(package)

            self.assertIn("SGV-PACKAGE-SPECIAL-FILE", {item.code for item in diagnostics})
            self.assertTrue(
                any(item.pointer == "/runtime/unexpected.fifo" for item in diagnostics),
                diagnostics,
            )

    def test_manifest_rejects_drive_qualified_and_absolute_paths(self):
        unsafe_paths = ("C:/escape", "//server/share/escape", "/absolute", "../escape")
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as td:
                package = self.compile_package(Path(td))
                manifest_path = package / "MANIFEST.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["artifacts"][0]["path"] = unsafe
                joined = "\n".join(
                    f"{item['path']} {item['sha256']} {item['bytes']} {item['mode']}"
                    for item in manifest["artifacts"]
                )
                manifest["package_fingerprint"] = hashlib.sha256(joined.encode()).hexdigest()
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

                diagnostics = validate_package(package)

                self.assertIn("SGV-PACKAGE-MANIFEST-PATH", {item.code for item in diagnostics})

    def test_runtime_inventory_copy_rejects_symlinked_source_resource(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            resources = parent / "resources"
            for directory in ("profiles", "spec", "templates"):
                shutil.copytree(ROOT / directory, resources / directory)
            outside = parent / "outside-state-template.md"
            outside.write_text("outside resource\n", encoding="utf-8")
            source = resources / "templates" / "STATE.md"
            source.unlink()
            try:
                source.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaisesRegex(CompileSafetyError, "resource"):
                compile_contract_file(
                    CONTRACT,
                    parent / "package",
                    resource_root=resources,
                )

            self.assertFalse((parent / "package").exists())

    def test_compile_rejects_broken_output_symlink_without_creating_its_target(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            output = parent / "package"
            outside = parent / "missing-outside-target"
            try:
                output.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(CompileSafetyError):
                compile_contract_file(CONTRACT, output)

            self.assertTrue(output.is_symlink())
            self.assertFalse(outside.exists())

    def test_old_manifest_gets_one_actionable_recompile_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            manifest_path = package / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["manifest_version"] = "1.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            for relative in ("runtime", "scripts", "lib", "templates", "spec", "profiles"):
                shutil.rmtree(package / relative)

            diagnostics = validate_package(package)
            shape = [item for item in diagnostics if item.code == "SGV-PACKAGE-MANIFEST-SHAPE"]

            self.assertEqual(len(diagnostics), 1, diagnostics)
            self.assertEqual(len(shape), 1, diagnostics)
            self.assertIn("recompil", shape[0].remediation.lower())

    def test_staging_validation_failure_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            before = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            diagnostic = Diagnostic(
                code="SGV-PACKAGE-MANIFEST-HASH",
                severity="error",
                blocking_stage="preflight",
                invariant_id="INV-VALIDATOR-001",
                artifact=str(package),
                pointer="/MANIFEST.json",
                message="injected staging validation failure",
                remediation="Recompile the package.",
            )
            with mock.patch(
                "chip_supergoal.compile.validate_package",
                side_effect=[[], [diagnostic]],
            ):
                with self.assertRaises(CompileSafetyError):
                    compile_contract_file(CONTRACT, package)
            after = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_backup_rename_failure_preserves_existing_target_without_residue(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            before = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            original_rename = Path.rename
            injected = False

            def fail_first_target_rename(path: Path, target: Path) -> Path:
                nonlocal injected
                if not injected and path == package:
                    injected = True
                    raise OSError("injected backup rename failure")
                return original_rename(path, target)

            with mock.patch.object(Path, "rename", fail_first_target_rename):
                with self.assertRaisesRegex(OSError, "injected backup rename failure"):
                    compile_contract_file(CONTRACT, package)

            self.assertTrue(injected)
            self.assertTrue(package.is_dir())
            after = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            residue = sorted(
                path.name
                for path in parent.iterdir()
                if path.name.startswith(".package.backup-")
                or path.name.startswith(".package.tmp-")
            )
            self.assertEqual(residue, [])

    def test_target_mutation_after_precheck_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            original_validate = compile_module.validate_package
            mutated_snapshot: dict[str, bytes] = {}
            injected = False

            def validate_with_concurrent_transition(root: Path):
                nonlocal injected, mutated_snapshot
                diagnostics = original_validate(root)
                if Path(root) != package and not injected:
                    injected = True
                    store = StateStore(package)
                    state = read_state(store.state_json)
                    store.transition("PLAN_REVIEWED", expected_revision=state.state_revision)
                    mutated_snapshot = {
                        path.relative_to(package).as_posix(): path.read_bytes()
                        for path in package.rglob("*")
                        if path.is_file()
                    }
                return diagnostics

            with mock.patch(
                "chip_supergoal.compile.validate_package",
                side_effect=validate_with_concurrent_transition,
            ):
                with self.assertRaises(CompileSafetyError):
                    compile_contract_file(CONTRACT, package)

            self.assertTrue(injected)
            after = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, mutated_snapshot)
            self.assertEqual(read_state(package / "runtime/STATE.json").state_revision, 2)

    def test_double_fault_preserves_backup_and_reports_recovery_path(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            before = {
                path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*")
                if path.is_file()
            }
            original_rename = Path.rename
            backup: Path | None = None

            def fail_swap_and_restore(path: Path, target: Path) -> Path:
                nonlocal backup
                if path == package:
                    backup = Path(target)
                    return original_rename(path, target)
                if path.name.startswith(".package.tmp-") and target == package:
                    raise OSError("injected staging swap failure")
                if backup is not None and path == backup and target == package:
                    raise OSError("injected backup restore failure")
                return original_rename(path, target)

            with mock.patch.object(Path, "rename", fail_swap_and_restore):
                with self.assertRaises(CompileSafetyError) as raised:
                    compile_contract_file(CONTRACT, package)

            self.assertIsNotNone(backup)
            self.assertIn(str(backup), str(raised.exception))
            self.assertFalse(package.exists())
            self.assertTrue(backup.is_dir())
            backup_snapshot = {
                path.relative_to(backup).as_posix(): path.read_bytes()
                for path in backup.rglob("*")
                if path.is_file()
            }
            self.assertEqual(backup_snapshot, before)
            self.assertEqual(
                [path for path in parent.iterdir() if path.name.startswith(".package.tmp-")],
                [],
            )

    def test_pristine_recompile_is_allowed_but_started_runtime_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            compile_contract_file(CONTRACT, package)
            state_path = package / "runtime" / "STATE.json"
            state = read_state(state_path)
            updated = replace(state, state_revision=2, lifecycle="PLAN_REVIEWED")
            write_state_atomic(state_path, updated)
            (package / "STATE.md").write_text(render_state_md(updated), encoding="utf-8", newline="\n")
            append_event(
                package / "runtime" / "events.jsonl",
                state=updated.to_dict(),
                event_type="transition:COMPILED->PLAN_REVIEWED",
            )
            before = state_path.read_bytes()

            with self.assertRaisesRegex(CompileSafetyError, "started runtime"):
                compile_contract_file(CONTRACT, package)

            self.assertEqual(state_path.read_bytes(), before)

    def test_inventory_has_canonical_lf_and_exact_logical_modes(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.compile_package(Path(td))
            manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
            modes = {item["path"]: item["mode"] for item in manifest["artifacts"]}
            wrappers = {
                "scripts/validate-phase.sh",
                "scripts/validate-loop-design.sh",
                "scripts/repo-state.sh",
                "scripts/detect-stack.sh",
                "scripts/summarize-repo.sh",
            }
            self.assertEqual({path for path, mode in modes.items() if mode == "0755"}, wrappers)
            for path, mode in modes.items():
                self.assertEqual(mode, "0755" if path in wrappers else "0644", path)
                self.assertNotIn(b"\r", (package / path).read_bytes(), path)


if __name__ == "__main__":
    unittest.main()
