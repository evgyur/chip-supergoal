import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import build_manifest, compile_contract_file
from chip_supergoal.portable import (
    StateLockTimeout,
    canonical_text_bytes,
    logical_mode,
    package_lock,
    write_bytes_atomic,
    write_utf8_lf,
)
from chip_supergoal.state import State, StateStore
from chip_supergoal.validate import validate_package
import chip_supergoal.portable as portable_module


DIGEST = "a" * 64


def _hold_package_lock(lock_path: str, ready, release) -> None:
    with package_lock(Path(lock_path), timeout=5.0, retry_interval=0.01):
        ready.set()
        release.wait(10.0)


class PortableRuntimeTest(unittest.TestCase):
    def _junction(self, link: Path, target: Path) -> None:
        result = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"junction creation unavailable: {result.stderr}")

    def _remove_junction(self, link: Path) -> None:
        if os.path.lexists(link):
            os.rmdir(link)

    @unittest.skipUnless(os.name == "nt", "native Windows junction race regression")
    def test_atomic_writer_cannot_publish_through_swapped_parent_junction(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            reports = root / "reports"
            reports.mkdir(parents=True)
            target = reports / "final-audit.json"
            target.write_bytes(b"trusted-old")
            outside = base / "outside"
            outside.mkdir()
            outside_target = outside / target.name
            outside_target.write_bytes(b"outside-original")
            parked = root / "reports-before-race"
            original_create = portable_module._create_windows_temp_descriptor
            swapped = False

            def swap_then_create(*args, **kwargs):
                nonlocal swapped
                reports.rename(parked)
                self._junction(reports, outside)
                swapped = True
                return original_create(*args, **kwargs)

            try:
                with mock.patch.object(
                    portable_module,
                    "_create_windows_temp_descriptor",
                    side_effect=swap_then_create,
                ):
                    with self.assertRaises(OSError):
                        write_bytes_atomic(target, b"trusted-new", root=root)
                self.assertTrue(swapped)
                self.assertEqual(outside_target.read_bytes(), b"outside-original")
                self.assertEqual(
                    (parked / target.name).read_bytes(), b"trusted-old"
                )
            finally:
                if swapped:
                    self._remove_junction(reports)

    @unittest.skipUnless(os.name == "nt", "native Windows atomic publish regression")
    def test_atomic_writer_does_not_delete_publish_after_post_rename_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reports = root / "reports"
            reports.mkdir()
            target = reports / "final-audit.json"
            target.write_bytes(b"trusted-old")
            original_rename = portable_module._rename_windows_descriptor

            def publish_then_fail(*args, **kwargs):
                original_rename(*args, **kwargs)
                raise OSError("injected immediately after native rename")

            with mock.patch.object(
                portable_module,
                "_rename_windows_descriptor",
                side_effect=publish_then_fail,
            ):
                with self.assertRaises(OSError):
                    write_bytes_atomic(target, b"trusted-new", root=root)
            self.assertEqual(target.read_bytes(), b"trusted-new")
            self.assertFalse(
                any(path.name.startswith(f".{target.name}.tmp-") for path in reports.iterdir())
            )

    @unittest.skipUnless(os.name == "nt", "native Windows handle leak regression")
    def test_relative_open_closes_child_when_parent_final_path_lookup_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "child.txt").write_bytes(b"trusted")
            parent_handle, _ = portable_module._open_windows_verified(
                root, directory=True
            )
            original_close = portable_module._CloseHandle
            try:
                with mock.patch.object(
                    portable_module,
                    "_windows_final_path",
                    side_effect=OSError("injected final-path failure"),
                ), mock.patch.object(
                    portable_module,
                    "_CloseHandle",
                    wraps=original_close,
                ) as close_handle:
                    with self.assertRaises(OSError):
                        portable_module._open_windows_relative_verified(
                            parent_handle,
                            "child.txt",
                            directory=False,
                        )
                    self.assertEqual(close_handle.call_count, 1)
            finally:
                original_close(parent_handle)

    @unittest.skipUnless(os.name == "nt", "native Windows junction race regression")
    def test_unlink_cannot_delete_through_swapped_parent_junction(self):
        unlinker = getattr(portable_module, "unlink_regular_file_no_follow")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            reports = root / "reports"
            reports.mkdir(parents=True)
            target = reports / "final-audit.json"
            target.write_bytes(b"trusted")
            outside = base / "outside"
            outside.mkdir()
            outside_target = outside / target.name
            outside_target.write_bytes(b"outside-original")
            parked = root / "reports-before-unlink-race"
            original_open = portable_module._open_windows_relative_verified
            swapped = False

            def swap_then_open(parent_handle, name, *args, **kwargs):
                nonlocal swapped
                if not swapped and not kwargs.get("directory", False):
                    reports.rename(parked)
                    self._junction(reports, outside)
                    swapped = True
                return original_open(parent_handle, name, *args, **kwargs)

            try:
                with mock.patch.object(
                    portable_module,
                    "_open_windows_relative_verified",
                    side_effect=swap_then_open,
                ):
                    with self.assertRaises(OSError):
                        unlinker(target, root)
                self.assertTrue(swapped)
                self.assertEqual(outside_target.read_bytes(), b"outside-original")
                self.assertTrue((parked / target.name).is_file())
            finally:
                if swapped:
                    self._remove_junction(reports)

    def test_regular_file_reader_consumes_verified_handle_not_path_reopen(self):
        reader = getattr(portable_module, "read_regular_file_no_follow", None)
        self.assertIsNotNone(reader)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            source.write_bytes(b"verified bytes")

            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("path-based reopen is forbidden"),
            ):
                self.assertEqual(reader(source, root), b"verified bytes")

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor-relative race regression")
    def test_regular_file_reader_rejects_symlink_swapped_before_final_open(self):
        reader = getattr(portable_module, "read_regular_file_no_follow", None)
        unsafe_error = getattr(portable_module, "UnsafeFileError", OSError)
        self.assertIsNotNone(reader)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            source.write_bytes(b"inside")
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_bytes(b"outside")
            original_open = os.open
            swapped = False

            def swap_before_final_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == source.name and kwargs.get("dir_fd") is not None and not swapped:
                    swapped = True
                    source.unlink()
                    source.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)

            try:
                with mock.patch(
                    "chip_supergoal.portable.os.open",
                    side_effect=swap_before_final_open,
                ):
                    with self.assertRaises(unsafe_error):
                        reader(source, root)
                self.assertTrue(swapped)
            finally:
                outside.unlink(missing_ok=True)

    def test_canonical_text_bytes_normalizes_all_newlines_and_uses_utf8(self):
        self.assertEqual(
            canonical_text_bytes("alpha\r\nbeta\rgamma\nД"),
            "alpha\nbeta\ngamma\nД".encode("utf-8"),
        )

    def test_write_utf8_lf_creates_parents_with_stable_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "artifact.md"

            write_utf8_lf(path, "a\r\nb\rc\n")

            self.assertEqual(path.read_bytes(), b"a\nb\nc\n")

    def test_atomic_byte_writer_overwrites_target(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "nested"
            path = parent / "artifact.bin"
            parent.mkdir()
            path.write_bytes(b"old bytes")

            write_bytes_atomic(path, b"new bytes")

            self.assertEqual(path.read_bytes(), b"new bytes")
            self.assertEqual([p.name for p in parent.iterdir()], ["artifact.bin"])

    def test_logical_modes_use_only_registered_executable_wrappers(self):
        self.assertEqual(logical_mode("scripts/validate-phase.sh"), "0755")
        self.assertEqual(logical_mode("scripts/validate-loop-design.sh"), "0755")
        self.assertEqual(logical_mode("scripts/not-registered.sh"), "0644")
        self.assertEqual(logical_mode("scripts/sgctl.py"), "0644")
        self.assertEqual(logical_mode("README.md"), "0644")

    def test_manifest_modes_do_not_follow_host_stat_bits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wrapper = root / "scripts" / "validate-phase.sh"
            document = root / "README.md"
            wrapper.parent.mkdir()
            wrapper.write_bytes(b"#!/bin/sh\n")
            document.write_bytes(b"read me\n")
            os.chmod(wrapper, 0o644)
            os.chmod(document, 0o755)

            modes = {item["path"]: item["mode"] for item in build_manifest(root)["artifacts"]}

            self.assertEqual(modes["scripts/validate-phase.sh"], "0755")
            self.assertEqual(modes["README.md"], "0644")

    @unittest.skipUnless(os.name == "nt", "native Windows regression")
    def test_validate_package_accepts_fresh_logical_modes_on_windows(self):
        with tempfile.TemporaryDirectory() as td:
            package = compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                Path(td) / "sg",
                template_protocol=ROOT / "templates/PROTOCOL.md",
            )

            mode_diagnostics = [
                diagnostic
                for diagnostic in validate_package(package)
                if diagnostic.code == "SGV-PACKAGE-MANIFEST-HASH"
            ]

            self.assertEqual(mode_diagnostics, [])

    def test_package_lock_creates_persistent_one_byte_file(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "nested" / "state.lock"

            with package_lock(lock_path):
                self.assertTrue(lock_path.is_file())
                self.assertEqual(lock_path.stat().st_size, 1)

            self.assertEqual(lock_path.read_bytes(), b"\0")
            with package_lock(lock_path):
                self.assertEqual(lock_path.stat().st_size, 1)

    def test_package_lock_rejects_symlink_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / "outside.bin"
            outside.write_bytes(b"")
            lock_path = root / "state.lock"
            try:
                lock_path.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(OSError):
                with package_lock(lock_path):
                    self.fail("symlinked lock was acquired")

            self.assertEqual(outside.read_bytes(), b"")

    def test_contended_lock_times_out_against_second_process(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "state.lock"
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            release = context.Event()
            process = context.Process(
                target=_hold_package_lock,
                args=(str(lock_path), ready, release),
            )
            process.start()
            try:
                self.assertTrue(ready.wait(10.0), "lock-holder process did not acquire the lock")
                with self.assertRaisesRegex(StateLockTimeout, "SGV-STATE-LOCK-TIMEOUT"):
                    with package_lock(lock_path, timeout=0.15, retry_interval=0.01):
                        self.fail("contended lock was acquired")
            finally:
                release.set()
                process.join(10.0)
                if process.is_alive():
                    process.terminate()
                    process.join(5.0)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(lock_path.read_bytes(), b"\0")

    def test_state_store_transition_uses_portable_lock_and_lf_writes(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(
                goal_id="sg-20260710-portable-state",
                contract_sha256=DIGEST,
                contract_revision=1,
                state_revision=1,
                lifecycle="COMPILED",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)

            updated = store.transition("PLAN_REVIEWED", expected_revision=1, phase_status="READY")

            self.assertEqual(updated.state_revision, 2)
            self.assertEqual(store.lock.read_bytes(), b"\0")
            self.assertNotIn(b"\r", store.state_json.read_bytes())
            self.assertNotIn(b"\r", store.state_md.read_bytes())

    def test_state_transition_uses_persistent_external_operation_lock(self):
        operation_lock = getattr(portable_module, "package_operation_lock", None)
        operation_lock_path = getattr(portable_module, "package_operation_lock_path", None)
        self.assertIsNotNone(operation_lock)
        self.assertIsNotNone(operation_lock_path)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            store = StateStore(root)
            store.initialize(
                State(
                    goal_id="sg-20260711-operation-lock",
                    contract_sha256=DIGEST,
                    contract_revision=1,
                    state_revision=1,
                    lifecycle="COMPILED",
                    current_phase_id="P01",
                    phase_status="PENDING",
                )
            )
            started = threading.Event()
            completed = threading.Event()

            def transition() -> None:
                started.set()
                store.transition("PLAN_REVIEWED", expected_revision=1)
                completed.set()

            with operation_lock(root):
                thread = threading.Thread(target=transition)
                thread.start()
                self.assertTrue(started.wait(2.0))
                self.assertFalse(completed.wait(0.2))
            self.assertTrue(completed.wait(5.0))
            thread.join(5.0)
            lock_path = operation_lock_path(root)
            self.assertEqual(lock_path.parent, root.parent.resolve())
            self.assertFalse(lock_path.is_relative_to(root.resolve()))
            self.assertEqual(lock_path.read_bytes(), b"\0")


if __name__ == "__main__":
    unittest.main()
