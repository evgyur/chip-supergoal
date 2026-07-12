from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.archive import ArchiveSecurityError, deterministic_zip
import chip_supergoal.archive as archive_module
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.state import StateStore


SOURCE = ROOT / "examples" / "brownfield-feature" / "CONTRACT.json"


def _physical_path_key(path: str | Path) -> str:
    resolved = Path(path).resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _same_physical_path(left: str | Path, right: str | Path) -> bool:
    return _physical_path_key(left) == _physical_path_key(right)


class ArchiveDeterminismTest(unittest.TestCase):
    def compile_package(self, parent: Path) -> Path:
        return compile_contract_file(SOURCE, parent / "compiled")

    def archive(self, package: Path, destination: Path | None = None):
        destination = destination or package.parent / "final artifacts ü.zip"
        result_path = package / "out/final-artifacts-manifest.json"
        result = deterministic_zip(package, destination, result_path)
        return destination, result_path, result

    def test_archive_is_byte_deterministic_with_exact_portable_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            first = parent / "first.zip"
            second = parent / "second.zip"
            self.archive(package, first)
            # The prior result is an exact exclusion and cannot perturb a rerun.
            self.archive(package, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

            with __import__("zipfile").ZipFile(first) as zipped:
                infos = zipped.infolist()
                names = [info.filename for info in infos]
                self.assertEqual(names[:-1], sorted(names[:-1]))
                self.assertEqual(names[-1], "ARCHIVE-MANIFEST.json")
                self.assertEqual(len(names), len(set(names)))
                self.assertFalse(any(name.endswith("/") for name in names))
                for info in infos:
                    self.assertEqual(info.compress_type, 0)
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.create_version, 20)
                    self.assertEqual(info.extract_version, 20)
                    self.assertEqual(info.flag_bits & 0x800, 0x800, info.filename)
                    self.assertEqual(info.extra, b"")
                    self.assertEqual(info.comment, b"")
                    expected_mode = 0o100755 if info.filename in {
                        "scripts/detect-stack.sh",
                        "scripts/repo-state.sh",
                        "scripts/summarize-repo.sh",
                        "scripts/validate-loop-design.sh",
                        "scripts/validate-phase.sh",
                        "templates/delivery/package-final-artifacts.sh",
                        "templates/delivery/send-final-artifacts.sh",
                        "templates/delivery/send-review-md-files.sh",
                    } else 0o100644
                    self.assertEqual(info.external_attr >> 16, expected_mode)

    def test_synthetic_archive_has_cross_platform_golden_sha256(self):
        captures = [
            archive_module.CapturedFile(
                "a.txt", b"alpha\n", "0644", (0, 0, 0, 0)
            ),
            archive_module.CapturedFile(
                "scripts/repo-state.sh", b"#!/bin/sh\n", "0755", (0, 0, 0, 0)
            ),
            archive_module.CapturedFile(
                "ünicode.txt", "snow\n".encode(), "0644", (0, 0, 0, 0)
            ),
        ]
        manifest = archive_module._canonical_json_bytes(
            archive_module._manifest_for(captures)
        )
        stream = io.BytesIO()
        archive_module._write_archive(stream, captures, manifest)
        self.assertEqual(
            hashlib.sha256(stream.getvalue()).hexdigest(),
            "069f88529e052da345cb8d6f4b1475842508a4f5eae07c7e5bdb4676196b6185",
        )

    def test_archive_works_from_relocated_package_without_source_pythonpath(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            relocated = parent / "relocated ü" / "nested" / "package"
            relocated.parent.mkdir(parents=True)
            shutil.move(package, relocated)
            destination = parent / "outside ü" / "result.zip"
            destination.parent.mkdir()
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["PYTHONUTF8"] = "1"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(relocated / "scripts/sgctl.py"),
                    "archive",
                    str(relocated),
                    "--out",
                    str(destination),
                    "--manifest",
                    str(relocated / "out/final-artifacts-manifest.json"),
                ],
                cwd=parent,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["archive_sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())

    def test_secret_scan_fails_before_publishing_or_replacing_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            destination = parent / "good.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            prior_destination = destination.read_bytes()
            prior_result = result_path.read_bytes()
            marker = "-----BEGIN " + "PRIVATE KEY-----"
            StateStore(package).update(
                expected_revision=1,
                blocker={"secret": marker + "\nnot-a-real-key"},
            )

            with self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-SECRET"):
                deterministic_zip(package, destination, result_path)

            self.assertEqual(destination.read_bytes(), prior_destination)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertEqual(list(parent.glob(".*.tmp-*")), [])

    def test_in_place_concurrent_mutation_is_rejected_after_single_capture(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            original_reader = archive_module.read_regular_file_no_follow
            mutated = False

            def mutate_after_read(path: Path, root: Path, **kwargs) -> bytes:
                nonlocal mutated
                data = original_reader(path, root, **kwargs)
                if not mutated and Path(path).name == "THINKING.md":
                    target = package / "ROADMAP.md"
                    target.write_bytes(target.read_bytes() + b"concurrent-change\n")
                    mutated = True
                return data

            with mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=mutate_after_read,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
            ):
                deterministic_zip(package, destination, result_path)
            self.assertTrue(mutated)
            self.assertFalse(destination.exists())

    def test_mutation_after_bounded_inventory_before_capture_is_rejected(self):
        """The bounded stat inventory must still bind every subsequent read."""

        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            original_inventory = archive_module._bounded_snapshot_inventory
            mutated = False

            def inventory_then_mutate(root: Path, **kwargs):
                nonlocal mutated
                inventory = original_inventory(root, **kwargs)
                thinking = package / "THINKING.md"
                thinking.write_bytes(thinking.read_bytes() + b"post-validation-forgery\n")
                mutated = True
                return inventory

            with mock.patch.object(
                archive_module,
                "_bounded_snapshot_inventory",
                side_effect=inventory_then_mutate,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
            ):
                deterministic_zip(package, destination, result_path)
            self.assertTrue(mutated)
            self.assertFalse(destination.exists())
            self.assertFalse(result_path.exists())

    def test_external_archive_uses_rooted_atomic_publication_without_move_away(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            destination.write_bytes(b"prior-good-destination")
            atomic_calls: list[tuple[Path, Path | None]] = []
            move_away: list[tuple[Path, Path]] = []
            original_atomic = archive_module.write_bytes_atomic
            original_replace = archive_module.os.replace

            def observe_atomic(path, content, *, root=None, **kwargs):
                atomic_calls.append(
                    (Path(path), Path(root) if root is not None else None)
                )
                return original_atomic(path, content, root=root, **kwargs)

            def observe_replace(source, target, *args, **kwargs):
                if _same_physical_path(source, destination):
                    move_away.append((Path(source), Path(target)))
                return original_replace(source, target, *args, **kwargs)

            with mock.patch.object(
                archive_module, "write_bytes_atomic", side_effect=observe_atomic
            ), mock.patch.object(
                archive_module.os, "replace", side_effect=observe_replace
            ):
                deterministic_zip(package, destination, result_path)

            self.assertTrue(
                any(
                    _same_physical_path(path, destination)
                    and root is not None
                    and _same_physical_path(root, destination.parent)
                    for path, root in atomic_calls
                ),
                atomic_calls,
            )
            self.assertEqual(move_away, [])

    def test_captured_mutable_semantics_are_revalidated_from_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.compile_package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            original_capture = archive_module._capture_snapshot

            def capture_then_corrupt(root: Path, **kwargs):
                from dataclasses import replace

                captures, observed = original_capture(root, **kwargs)
                captures = [
                    replace(item, data=b"{not-json\n")
                    if item.path == "runtime/evidence.json"
                    else item
                    for item in captures
                ]
                return captures, observed

            with mock.patch.object(
                archive_module,
                "_capture_snapshot",
                side_effect=capture_then_corrupt,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-MANIFEST-HASH"
            ):
                deterministic_zip(package, destination, result_path)
            self.assertFalse(destination.exists())
            self.assertFalse(result_path.exists())


if __name__ == "__main__":
    unittest.main()
