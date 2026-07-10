import multiprocessing
import os
import sys
import tempfile
import unittest
from pathlib import Path

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


DIGEST = "a" * 64


def _hold_package_lock(lock_path: str, ready, release) -> None:
    with package_lock(Path(lock_path), timeout=5.0, retry_interval=0.01):
        ready.set()
        release.wait(10.0)


class PortableRuntimeTest(unittest.TestCase):
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
                state_revision=0,
                lifecycle="DRAFT",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)

            updated = store.transition("COMPILED", expected_revision=0, phase_status="READY")

            self.assertEqual(updated.state_revision, 1)
            self.assertEqual(store.lock.read_bytes(), b"\0")
            self.assertNotIn(b"\r", store.state_json.read_bytes())
            self.assertNotIn(b"\r", store.state_md.read_bytes())


if __name__ == "__main__":
    unittest.main()
