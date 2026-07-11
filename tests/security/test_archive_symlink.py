from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import chip_supergoal.archive as archive_module
from chip_supergoal.archive import ArchiveSecurityError, deterministic_zip
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.portable import UnsafeFileError


SOURCE = ROOT / "examples" / "brownfield-feature" / "CONTRACT.json"


class ArchiveSymlinkSecurity(unittest.TestCase):
    def test_archive_rejects_real_symlink_escape_when_fixture_is_available(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = compile_contract_file(SOURCE, parent / "package")
            outside = parent / "outside-secret.txt"
            outside.write_text("outside-content\n", encoding="utf-8")
            link = package / "escape.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows account cannot create symlink fixture")
                raise
            destination = parent / "archive.zip"
            with self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-SYMLINK"):
                deterministic_zip(
                    package,
                    destination,
                    package / "out/final-artifacts-manifest.json",
                )
            self.assertFalse(destination.exists())

    def test_handle_open_swap_rejection_always_executes_without_symlink_privilege(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = compile_contract_file(SOURCE, parent / "package")
            original = archive_module.read_regular_file_no_follow

            def reject_one(path: Path, root: Path, **kwargs) -> bytes:
                if Path(path).name == "THINKING.md":
                    raise UnsafeFileError(path, "reparse swap", kind="symlink")
                return original(path, root, **kwargs)

            with mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=reject_one,
            ), self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-SYMLINK"):
                deterministic_zip(
                    package,
                    parent / "archive.zip",
                    package / "out/final-artifacts-manifest.json",
                )

    @unittest.skipUnless(os.name == "nt", "Windows reparse policy")
    def test_archive_rejects_junction_in_source_tree(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = compile_contract_file(SOURCE, parent / "package")
            outside = parent / "outside"
            outside.mkdir()
            junction = package / "junction"
            completed = __import__("subprocess").run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            try:
                with self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-SYMLINK"):
                    deterministic_zip(
                        package,
                        parent / "archive.zip",
                        package / "out/final-artifacts-manifest.json",
                    )
            finally:
                junction.rmdir()

    @unittest.skipIf(os.name == "nt", "POSIX symlink parent race")
    def test_archive_rejects_destination_parent_symlink_swap_at_publication(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = compile_contract_file(SOURCE, parent / "package")
            publish = parent / "publish"
            publish.mkdir()
            trusted = parent / "publish-trusted"
            attacker = parent / "attacker"
            attacker.mkdir()
            destination = publish / "archive.zip"
            original_atomic = archive_module.write_bytes_atomic
            swapped = False

            def swap_parent(path, content, *, root=None, **kwargs):
                nonlocal swapped
                if Path(path) == destination and not swapped:
                    publish.rename(trusted)
                    publish.symlink_to(attacker, target_is_directory=True)
                    swapped = True
                return original_atomic(path, content, root=root, **kwargs)

            try:
                with mock.patch.object(
                    archive_module,
                    "write_bytes_atomic",
                    side_effect=swap_parent,
                ), self.assertRaisesRegex(
                    ArchiveSecurityError, "SGV-PACKAGE-(?:SYMLINK|PATH-ESCAPE)"
                ):
                    deterministic_zip(
                        package,
                        destination,
                        package / "out/final-artifacts-manifest.json",
                    )
                self.assertTrue(swapped)
                self.assertFalse((attacker / "archive.zip").exists())
            finally:
                if publish.is_symlink():
                    publish.unlink()
                if trusted.exists():
                    trusted.rename(publish)

    @unittest.skipUnless(os.name == "nt", "Windows junction parent race")
    def test_archive_rejects_destination_parent_junction_swap_at_publication(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = compile_contract_file(SOURCE, parent / "package")
            publish = parent / "publish"
            publish.mkdir()
            trusted = parent / "publish-trusted"
            attacker = parent / "attacker"
            attacker.mkdir()
            destination = publish / "archive.zip"
            original_atomic = archive_module.write_bytes_atomic
            swapped = False

            def swap_parent(path, content, *, root=None, **kwargs):
                nonlocal swapped
                if Path(path) == destination and not swapped:
                    publish.rename(trusted)
                    completed = __import__("subprocess").run(
                        ["cmd", "/c", "mklink", "/J", str(publish), str(attacker)],
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stdout + completed.stderr,
                    )
                    swapped = True
                return original_atomic(path, content, root=root, **kwargs)

            try:
                with mock.patch.object(
                    archive_module,
                    "write_bytes_atomic",
                    side_effect=swap_parent,
                ), self.assertRaisesRegex(
                    ArchiveSecurityError, "SGV-PACKAGE-(?:SYMLINK|PATH-ESCAPE)"
                ):
                    deterministic_zip(
                        package,
                        destination,
                        package / "out/final-artifacts-manifest.json",
                    )
                self.assertTrue(swapped)
                self.assertFalse((attacker / "archive.zip").exists())
            finally:
                if os.path.lexists(publish):
                    publish.rmdir()
                if trusted.exists():
                    trusted.rename(publish)


if __name__ == "__main__":
    unittest.main()
