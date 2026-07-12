from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import chip_supergoal.archive as archive_module
from chip_supergoal.archive import ArchiveSecurityError
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.portable import (
    UnsafeFileError,
    capture_root_identity,
    package_operation_lock_path,
    read_regular_file_no_follow,
    unlink_regular_file_no_follow,
    write_bytes_atomic,
)
from chip_supergoal.state import StateStore
from chip_supergoal.validate import validate_package


def _physical_path_key(path: str | Path) -> str:
    resolved = Path(path).resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _same_physical_path(left: str | Path, right: str | Path) -> bool:
    return _physical_path_key(left) == _physical_path_key(right)


class ArchiveResourceLimitTest(unittest.TestCase):
    def root_with(self, parent: Path, **files: bytes) -> Path:
        root = parent / "package"
        root.mkdir(parents=True)
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return root

    def test_entry_cap_exact_and_plus_one_preflight_before_reader(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            exact = self.root_with(parent / "exact", **{"MANIFEST.json": b"{}", "a": b"x"})
            with mock.patch.object(archive_module, "MAX_SOURCE_ENTRIES", 2):
                captures, _ = archive_module._capture_snapshot(exact)
            self.assertEqual([item.path for item in captures], ["MANIFEST.json", "a"])

            over = self.root_with(
                parent / "over",
                **{"MANIFEST.json": b"{}", "a": b"x", "b": b"y"},
            )
            with mock.patch.object(archive_module, "MAX_SOURCE_ENTRIES", 2), mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=AssertionError("reader must not run after over-limit stat preflight"),
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
            ):
                archive_module._capture_snapshot(over)

    def test_file_cap_exact_and_plus_one_preflight_before_reader(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            exact = self.root_with(parent / "exact", **{"MANIFEST.json": b"{}", "a": b"1234"})
            with mock.patch.object(archive_module, "MAX_SOURCE_FILE_BYTES", 4):
                captures, _ = archive_module._capture_snapshot(exact)
            self.assertEqual({item.path: len(item.data) for item in captures}["a"], 4)

            over = self.root_with(parent / "over", **{"MANIFEST.json": b"{}", "a": b"12345"})
            with mock.patch.object(archive_module, "MAX_SOURCE_FILE_BYTES", 4), mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=AssertionError("reader must not run after over-limit stat preflight"),
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
            ):
                archive_module._capture_snapshot(over)

    def test_aggregate_cap_exact_and_plus_one_preflight_before_reader(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            exact = self.root_with(parent / "exact", **{"MANIFEST.json": b"{}", "a": b"1234"})
            with mock.patch.object(archive_module, "MAX_SOURCE_AGGREGATE_BYTES", 6):
                captures, _ = archive_module._capture_snapshot(exact)
            self.assertEqual(sum(len(item.data) for item in captures), 6)

            over = self.root_with(parent / "over", **{"MANIFEST.json": b"{}", "a": b"12345"})
            with mock.patch.object(archive_module, "MAX_SOURCE_AGGREGATE_BYTES", 6), mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=AssertionError("reader must not run after over-limit stat preflight"),
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
            ):
                archive_module._capture_snapshot(over)

    def test_external_archive_cap_rejects_from_stat_before_reader(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "archive.zip"
            path.write_bytes(b"12345")
            with mock.patch.object(archive_module, "MAX_ARCHIVE_BYTES", 4), mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=AssertionError("oversized archive must not be read"),
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
            ):
                archive_module._safe_external_bytes(path)

    def test_zip32_name_projection_runs_before_first_source_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root_with(
                Path(td), **{"MANIFEST.json": b"{}", "a.txt": b"x"}
            )
            with mock.patch.object(
                archive_module, "ZIP32_MAX_NAME_BYTES", 0
            ), mock.patch.object(
                archive_module,
                "read_regular_file_no_follow",
                side_effect=AssertionError("ZIP32 preflight must precede reads"),
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
            ):
                archive_module._capture_snapshot(root)

    def test_zip32_projection_rejects_name_size_and_offset_overflow(self):
        capture = archive_module.CapturedFile("a", b"x", "0644", (0, 0, 1, 0))
        archive_module._assert_zip32_projection([capture], b"{}\n")
        with mock.patch.object(archive_module, "ZIP32_MAX_NAME_BYTES", 0), self.assertRaisesRegex(
            ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
        ):
            archive_module._assert_zip32_projection([capture], b"{}\n")
        with mock.patch.object(archive_module, "ZIP32_MAX_OFFSET", 32), self.assertRaisesRegex(
            ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-LIMIT"
        ):
            archive_module._assert_zip32_projection([capture], b"{}\n")


class ArchivePortableGrammarTest(unittest.TestCase):
    def test_windows_invalid_and_ascii_control_characters_are_rejected_per_component(self):
        invalid = [
            "bad<name.txt",
            "bad>name.txt",
            'bad"name.txt',
            "bad|name.txt",
            "bad?name.txt",
            "bad*name.txt",
            "dir/bad\x7fname.txt",
        ] + [f"dir/bad{chr(code)}name.txt" for code in range(0x20)]
        for path in invalid:
            with self.subTest(path=path):
                self.assertFalse(archive_module._is_portable_archive_path(path))
        for path in ("documents/Пример file.txt", "日本語/space name.md"):
            with self.subTest(path=path):
                self.assertTrue(archive_module._is_portable_archive_path(path))

    def test_unicode_surrogates_are_rejected_as_nonportable(self):
        for path in ("bad-\ud800.txt", "bad-\udfff.txt", "dir/\udc80"):
            with self.subTest(path=repr(path)):
                self.assertFalse(archive_module._is_portable_archive_path(path))

    @unittest.skipUnless(os.name == "posix", "raw byte filenames are POSIX-only")
    def test_raw_non_utf8_filename_fails_with_archive_security_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            (root / "MANIFEST.json").write_bytes(b"{}")
            descriptor = os.open(
                os.fsencode(root) + b"/bad-\xff.txt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.close(descriptor)
            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-TRAVERSAL"
            ):
                archive_module._capture_snapshot(root)


class ZipfileCompatibilityGuardTest(unittest.TestCase):
    def test_supported_zipfile_private_hook_contract_is_checked(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 11))
        archive_module._assert_zipfile_compatibility()

        def incompatible(self, unexpected):
            return b"wrong", 0

        with mock.patch.object(
            archive_module.zipfile.ZipInfo,
            "_encodeFilenameFlags",
            incompatible,
        ), self.assertRaisesRegex(
            ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
        ):
            archive_module._assert_zipfile_compatibility()

    def test_cp437_base_hook_is_safe_when_custom_writer_stays_utf8(self):
        def cp437_hook(self):
            try:
                return self.filename.encode("ascii"), self.flag_bits
            except UnicodeEncodeError:
                return self.filename.encode("cp437"), self.flag_bits

        with mock.patch.object(
            archive_module.zipfile.ZipInfo,
            "_encodeFilenameFlags",
            cp437_hook,
        ):
            archive_module._assert_zipfile_compatibility()

    def test_writer_probe_rejects_subclass_hook_that_drops_utf8_flag(self):
        capture = archive_module.CapturedFile("a.txt", b"x", "0644", (0, 0, 1, 0))
        manifest = archive_module._canonical_json_bytes(
            archive_module._manifest_for([capture])
        )

        def broken(self):
            return self.filename.encode("utf-8"), self.flag_bits & ~0x800

        with mock.patch.object(
            archive_module._Utf8ZipInfo,
            "_encodeFilenameFlags",
            broken,
        ), self.assertRaisesRegex(
            ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
        ):
            archive_module._write_archive(__import__("io").BytesIO(), [capture], manifest)


class RootIdentityRaceTest(unittest.TestCase):
    def test_namespace_parent_swap_before_lock_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            trusted_parent = base / "trusted"
            attacker_parent = base / "attacker"
            parked_parent = base / "trusted-parked"
            trusted_parent.mkdir()
            attacker_parent.mkdir()
            package = compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                trusted_parent / "package",
            )
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                attacker_parent / "package",
            )
            trusted_namespace_lock = package_operation_lock_path(package)
            attacker_namespace_lock = (
                attacker_parent / trusted_namespace_lock.name
            )
            if trusted_namespace_lock.exists():
                trusted_namespace_lock.unlink()
            if attacker_namespace_lock.exists():
                attacker_namespace_lock.unlink()
            destination = base / "archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            original_lock = archive_module.package_operation_lock
            swapped = False

            def swap_then_lock(*args, **kwargs):
                nonlocal swapped
                if not swapped:
                    trusted_parent.rename(parked_parent)
                    if os.name == "nt":
                        linked = subprocess.run(
                            [
                                "cmd",
                                "/d",
                                "/c",
                                "mklink",
                                "/J",
                                str(trusted_parent),
                                str(attacker_parent),
                            ],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            check=False,
                        )
                        if linked.returncode != 0:
                            parked_parent.rename(trusted_parent)
                            self.skipTest(
                                f"junction creation unavailable: {linked.stderr}"
                            )
                    else:
                        trusted_parent.symlink_to(
                            attacker_parent, target_is_directory=True
                        )
                    swapped = True
                return original_lock(*args, **kwargs)

            try:
                with mock.patch.object(
                    archive_module,
                    "package_operation_lock",
                    side_effect=swap_then_lock,
                ), self.assertRaisesRegex(
                    ArchiveSecurityError,
                    "SGV-PACKAGE-(?:PATH-ESCAPE|SYMLINK)",
                ):
                    archive_module.deterministic_zip(
                        package,
                        destination,
                        result_path,
                    )
            finally:
                if swapped and os.path.lexists(trusted_parent):
                    if os.name == "nt":
                        os.rmdir(trusted_parent)
                    else:
                        trusted_parent.unlink()

            self.assertTrue(swapped)
            self.assertFalse(attacker_namespace_lock.exists())
            self.assertFalse(destination.exists())
            self.assertFalse(
                (attacker_parent / "package" / archive_module.ARCHIVE_RESULT_PATH).exists()
            )
            self.assertFalse(
                (parked_parent / "package" / archive_module.ARCHIVE_RESULT_PATH).exists()
            )

    @unittest.skipIf(os.name == "nt", "POSIX permits renaming an open locked tree")
    def test_package_swap_after_first_bind_is_rejected_by_original_identity(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                base / "package",
            )
            replacement = compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                base / "replacement",
            )
            parked = base / "package-parked"
            destination = base / "archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            original_prepare = archive_module._prepare_paths
            prepare_calls = 0

            def swap_before_second_bind(*args, **kwargs):
                nonlocal prepare_calls
                prepare_calls += 1
                if prepare_calls == 2:
                    package.rename(parked)
                    replacement.rename(package)
                return original_prepare(*args, **kwargs)

            with mock.patch.object(
                archive_module,
                "_prepare_paths",
                side_effect=swap_before_second_bind,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-PATH-ESCAPE"
            ):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    result_path,
                )

            self.assertEqual(prepare_calls, 2)
            self.assertFalse(destination.exists())
            self.assertFalse(
                (package / archive_module.ARCHIVE_RESULT_PATH).exists()
            )
            self.assertFalse(
                (parked / archive_module.ARCHIVE_RESULT_PATH).exists()
            )

    @unittest.skipUnless(os.name == "nt", "native Windows SUBST alias regression")
    def test_subst_alias_cannot_hide_reserved_namespace_lock_destination(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            trusted = base / "trusted"
            trusted.mkdir()
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                trusted / "package",
            )
            drive = None
            for letter in reversed("PQRSTUVWXYZ"):
                candidate = f"{letter}:"
                if Path(candidate + "\\").exists():
                    continue
                mapped = subprocess.run(
                    ["subst", candidate, str(trusted)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if mapped.returncode == 0:
                    drive = candidate
                    break
            if drive is None:
                self.skipTest("no drive letter is available for a SUBST fixture")

            alias_package = Path(f"{drive}/package")
            reserved = alias_package.parent / f".{alias_package.name}.operation.lock"
            try:
                with self.assertRaisesRegex(
                    ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT"
                ):
                    archive_module._prepare_paths(
                        alias_package,
                        reserved,
                        alias_package / archive_module.ARCHIVE_RESULT_PATH,
                    )
            finally:
                subprocess.run(
                    ["subst", drive, "/D"],
                    capture_output=True,
                    check=False,
                )

    @unittest.skipUnless(os.name == "nt", "native Windows SUBST remap regression")
    def test_archive_binds_subst_namespace_before_lock_and_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            trusted = base / "trusted"
            attacker = base / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                trusted / "package",
            )
            compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                attacker / "package",
            )
            drive = None
            for letter in reversed("PQRSTUVWXYZ"):
                candidate = f"{letter}:"
                if Path(candidate + "\\").exists():
                    continue
                mapped = subprocess.run(
                    ["subst", candidate, str(trusted)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if mapped.returncode == 0:
                    drive = candidate
                    break
            if drive is None:
                self.skipTest("no drive letter is available for a SUBST fixture")

            alias_package = Path(f"{drive}/package")
            alias_destination = Path(f"{drive}/archive.zip")
            alias_result = alias_package / archive_module.ARCHIVE_RESULT_PATH
            original_recover = archive_module._recover_publication_locked
            remapped = False

            def remap_then_recover(*args, **kwargs):
                nonlocal remapped
                if not remapped:
                    subprocess.run(
                        ["subst", drive, "/D"],
                        capture_output=True,
                        check=True,
                    )
                    subprocess.run(
                        ["subst", drive, str(attacker)],
                        capture_output=True,
                        check=True,
                    )
                    remapped = True
                return original_recover(*args, **kwargs)

            try:
                with mock.patch.object(
                    archive_module,
                    "_recover_publication_locked",
                    side_effect=remap_then_recover,
                ):
                    archive_module.deterministic_zip(
                        alias_package,
                        alias_destination,
                        alias_result,
                    )
            finally:
                subprocess.run(
                    ["subst", drive, "/D"],
                    capture_output=True,
                    check=False,
                )

            self.assertTrue(remapped)
            self.assertTrue((trusted / "archive.zip").is_file())
            self.assertTrue(
                (trusted / "package" / archive_module.ARCHIVE_RESULT_PATH).is_file()
            )
            self.assertFalse((attacker / "archive.zip").exists())
            self.assertFalse(
                (attacker / "package" / archive_module.ARCHIVE_RESULT_PATH).exists()
            )

    def test_rooted_read_write_delete_reject_nonleaf_ancestor_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ancestor = base / "trusted"
            root = ancestor / "publish"
            root.mkdir(parents=True)
            target = root / "archive.zip"
            target.write_bytes(b"trusted-old")
            identity = capture_root_identity(root)

            parked = base / "trusted-parked"
            ancestor.rename(parked)
            replacement = ancestor / "publish"
            replacement.mkdir(parents=True)
            attacker = replacement / "archive.zip"
            attacker.write_bytes(b"attacker-foreign")

            operations = (
                lambda: read_regular_file_no_follow(
                    target, root, root_identity=identity
                ),
                lambda: write_bytes_atomic(
                    target, b"new", root=root, root_identity=identity
                ),
                lambda: unlink_regular_file_no_follow(
                    target, root, root_identity=identity
                ),
            )
            for operation in operations:
                with self.assertRaises(UnsafeFileError):
                    operation()
                self.assertEqual(attacker.read_bytes(), b"attacker-foreign")
            self.assertEqual(
                (parked / "publish/archive.zip").read_bytes(), b"trusted-old"
            )

    def test_archive_parent_replacement_cannot_publish_into_attacker_tree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = compile_contract_file(
                ROOT / "examples/brownfield-feature/CONTRACT.json",
                base / "package",
            )
            ancestor = base / "trusted"
            publish = ancestor / "publish"
            publish.mkdir(parents=True)
            destination = publish / "archive.zip"
            destination.write_bytes(b"trusted-prior")
            parked = base / "trusted-parked"
            swapped = False
            original = archive_module.write_bytes_atomic

            def swap_nonleaf_then_write(path, content, *, root=None, **kwargs):
                nonlocal swapped
                if _same_physical_path(path, destination) and not swapped:
                    ancestor.rename(parked)
                    replacement = ancestor / "publish"
                    replacement.mkdir(parents=True)
                    (replacement / "archive.zip").write_bytes(b"attacker-foreign")
                    swapped = True
                return original(path, content, root=root, **kwargs)

            with mock.patch.object(
                archive_module,
                "write_bytes_atomic",
                side_effect=swap_nonleaf_then_write,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-PATH-ESCAPE"
            ):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    package / "out/final-artifacts-manifest.json",
                )
            self.assertTrue(swapped)
            self.assertEqual(
                (ancestor / "publish/archive.zip").read_bytes(), b"attacker-foreign"
            )
            self.assertEqual(
                (parked / "publish/archive.zip").read_bytes(), b"trusted-prior"
            )


class SimulatedPublicationCrash(BaseException):
    pass


class PublicationRecoveryTest(unittest.TestCase):
    CHECKPOINTS = ("intent", "stage", "destination", "result", "cleanup")

    def package(self, base: Path) -> Path:
        return compile_contract_file(
            ROOT / "examples/brownfield-feature/CONTRACT.json",
            base / "package",
        )

    def crash_at(self, checkpoint: str):
        fired = False

        def inject(current: str) -> None:
            nonlocal fired
            if not fired and current == checkpoint:
                fired = True
                raise SimulatedPublicationCrash(checkpoint)

        return inject

    def test_fault_checkpoints_recover_one_valid_generation_with_and_without_prior(self):
        for has_prior in (False, True):
            for checkpoint in self.CHECKPOINTS:
                with self.subTest(has_prior=has_prior, checkpoint=checkpoint), tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    package = self.package(base)
                    destination = base / "publish/archive.zip"
                    result_path = package / archive_module.ARCHIVE_RESULT_PATH
                    prior_archive = None
                    if has_prior:
                        archive_module.deterministic_zip(
                            package, destination, result_path
                        )
                        prior_archive = destination.read_bytes()
                        StateStore(package).update(
                            expected_revision=1,
                            blocker={"publication_generation": checkpoint},
                        )

                    with mock.patch.object(
                        archive_module,
                        "_publication_checkpoint",
                        side_effect=self.crash_at(checkpoint),
                    ), self.assertRaises(SimulatedPublicationCrash):
                        archive_module.deterministic_zip(
                            package, destination, result_path
                        )

                    intent = archive_module.archive_publication_intent_path(package)
                    stage = archive_module._archive_stage_path(destination)
                    backup = archive_module._archive_backup_path(destination)
                    if checkpoint == "intent":
                        self.assertTrue(intent.exists())
                        self.assertFalse(stage.exists())
                        self.assertFalse(backup.exists())
                    elif checkpoint == "stage":
                        self.assertTrue(intent.exists())
                        self.assertTrue(stage.exists())
                        self.assertEqual(backup.exists(), has_prior)
                    elif checkpoint != "cleanup":
                        self.assertTrue(intent.exists())
                    else:
                        self.assertFalse(intent.exists())
                        self.assertFalse(stage.exists())
                        self.assertFalse(backup.exists())

                    recovered = archive_module.deterministic_zip(
                        package, destination, result_path
                    )
                    self.assertEqual(
                        archive_module.load_archive_result(package), recovered
                    )
                    self.assertEqual(
                        archive_module.sha256_bytes(destination.read_bytes()),
                        recovered["archive_sha256"],
                    )
                    self.assertFalse(intent.exists())
                    self.assertFalse(stage.exists())
                    self.assertFalse(backup.exists())
                    if prior_archive is not None:
                        self.assertNotEqual(destination.read_bytes(), prior_archive)

    def test_publication_intent_survives_package_rename_and_recovers(self):
        for checkpoint in ("intent", "stage", "destination", "result"):
            for cross_parent in (False, True):
                with self.subTest(
                    checkpoint=checkpoint, cross_parent=cross_parent
                ), tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    package = self.package(base)
                    destination = base / "publish/archive.zip"
                    result_path = package / archive_module.ARCHIVE_RESULT_PATH

                    with mock.patch.object(
                        archive_module,
                        "_publication_checkpoint",
                        side_effect=self.crash_at(checkpoint),
                    ), self.assertRaises(SimulatedPublicationCrash):
                        archive_module.deterministic_zip(
                            package, destination, result_path
                        )

                    moved_parent = base
                    if cross_parent:
                        moved_parent = base / "moved-parent"
                        moved_parent.mkdir()
                    moved_package = moved_parent / "renamed-package"
                    package.rename(moved_package)

                    intent_path = archive_module.archive_publication_intent_path(
                        moved_package
                    )
                    self.assertTrue(intent_path.is_file())
                    with self.assertRaisesRegex(
                        ArchiveSecurityError,
                        "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                    ):
                        archive_module.assert_no_archive_recovery_required(
                            moved_package
                        )

                    recovered = archive_module.recover_archive_publication(
                        moved_package
                    )
                    self.assertEqual(
                        recovered["status"],
                        "clean" if checkpoint == "intent" else "recovered",
                    )
                    self.assertFalse(intent_path.exists())
                    self.assertFalse(
                        archive_module._archive_stage_path(destination).exists()
                    )
                    self.assertFalse(
                        archive_module._archive_backup_path(destination).exists()
                    )
                    if checkpoint == "intent":
                        self.assertFalse(destination.exists())
                        self.assertFalse(
                            (
                                moved_package
                                / archive_module.ARCHIVE_RESULT_PATH
                            ).exists()
                        )
                    else:
                        result = archive_module.load_archive_result(moved_package)
                        self.assertEqual(recovered["result"], result)
                        self.assertEqual(
                            archive_module.sha256_bytes(destination.read_bytes()),
                            result["archive_sha256"],
                        )
                    self.assertEqual(validate_package(moved_package), [])

    def test_orphan_initial_intent_temp_survives_package_rename_and_quarantine(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            generation = "a" * 32
            temporary = archive_module._publication_atomic_temp_path(
                archive_module.archive_publication_intent_path(package),
                generation,
            )
            temporary.write_bytes(b"partial-initial-intent")

            moved_parent = base / "moved-parent"
            moved_parent.mkdir()
            moved_package = moved_parent / "renamed-package"
            package.rename(moved_package)

            candidates = archive_module._intent_atomic_temp_candidates(
                moved_package
            )
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].read_bytes(), b"partial-initial-intent")
            with self.assertRaisesRegex(
                ArchiveSecurityError,
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
            ):
                archive_module.recover_archive_publication(moved_package)

            quarantined = archive_module.quarantine_archive_transaction_temps(
                moved_package, confirm_aborted=True
            )
            self.assertEqual(quarantined["status"], "quarantined")
            self.assertEqual(len(quarantined["quarantined"]), 1)
            preserved = Path(quarantined["quarantined"][0])
            self.assertEqual(preserved.read_bytes(), b"partial-initial-intent")
            self.assertFalse(
                archive_module._intent_atomic_temp_candidates(moved_package)
            )
            self.assertEqual(validate_package(moved_package), [])

    def test_renamed_publication_recovers_against_prior_generation(self):
        for checkpoint in ("intent", "stage"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = base / "publish/archive.zip"
                result_path = package / archive_module.ARCHIVE_RESULT_PATH
                archive_module.deterministic_zip(package, destination, result_path)
                prior_archive = destination.read_bytes()
                prior_result = result_path.read_bytes()
                StateStore(package).update(
                    expected_revision=1,
                    blocker={"rename_recovery": checkpoint},
                )

                with mock.patch.object(
                    archive_module,
                    "_publication_checkpoint",
                    side_effect=self.crash_at(checkpoint),
                ), self.assertRaises(SimulatedPublicationCrash):
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )

                moved_parent = base / "moved-parent"
                moved_parent.mkdir()
                moved_package = moved_parent / "renamed-package"
                package.rename(moved_package)
                archive_module.recover_archive_publication(moved_package)

                if checkpoint == "intent":
                    self.assertEqual(destination.read_bytes(), prior_archive)
                    self.assertEqual(
                        (
                            moved_package / archive_module.ARCHIVE_RESULT_PATH
                        ).read_bytes(),
                        prior_result,
                    )
                else:
                    current = archive_module.load_archive_result(moved_package)
                    self.assertNotEqual(destination.read_bytes(), prior_archive)
                    self.assertEqual(
                        archive_module.sha256_bytes(destination.read_bytes()),
                        current["archive_sha256"],
                    )
                self.assertEqual(validate_package(moved_package), [])

    def test_fault_checkpoints_recover_from_empty_existing_destination(self):
        for checkpoint in self.CHECKPOINTS:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = base / "publish/archive.zip"
                destination.parent.mkdir(parents=True)
                destination.write_bytes(b"")
                result_path = package / archive_module.ARCHIVE_RESULT_PATH

                with mock.patch.object(
                    archive_module,
                    "_publication_checkpoint",
                    side_effect=self.crash_at(checkpoint),
                ), self.assertRaises(SimulatedPublicationCrash):
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )

                recovered = archive_module.deterministic_zip(
                    package, destination, result_path
                )
                self.assertEqual(
                    archive_module.load_archive_result(package), recovered
                )
                self.assertEqual(
                    archive_module.sha256_bytes(destination.read_bytes()),
                    recovered["archive_sha256"],
                )
                self.assertFalse(
                    archive_module.archive_publication_intent_path(package).exists()
                )
                self.assertFalse(
                    archive_module._archive_stage_path(destination).exists()
                )
                self.assertFalse(
                    archive_module._archive_backup_path(destination).exists()
                )

    def test_reserved_sibling_control_paths_cannot_be_archive_destinations(self):
        for destination_factory in (
            archive_module.archive_publication_intent_path,
            package_operation_lock_path,
        ):
            with self.subTest(destination=destination_factory.__name__), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = destination_factory(package)
                with self.assertRaisesRegex(
                    ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT"
                ):
                    archive_module.deterministic_zip(
                        package,
                        destination,
                        package / archive_module.ARCHIVE_RESULT_PATH,
                    )
                self.assertFalse(
                    archive_module.archive_publication_intent_path(package).exists()
                )
                self.assertEqual(validate_package(package), [])

    def test_process_death_inside_atomic_write_recovers_generation_owned_temps(self):
        child = r'''
import os
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
sys.path.insert(0, str(source_root / "lib"))
import chip_supergoal.archive as archive
import chip_supergoal.portable as portable

package = Path(sys.argv[2])
destination = Path(sys.argv[3])
result_path = package / archive.ARCHIVE_RESULT_PATH
mode = sys.argv[4]
intent_path = archive.archive_publication_intent_path(package)
stage_path = archive._archive_stage_path(destination)
backup_path = archive._archive_backup_path(destination)
intent_writes = 0

def same_path(left, right):
    left = os.path.normcase(
        os.path.normpath(str(Path(left).resolve(strict=False)))
    )
    right = os.path.normcase(
        os.path.normpath(str(Path(right).resolve(strict=False)))
    )
    return left == right

def checkpoint(target, temporary):
    global intent_writes
    target = Path(target)
    if same_path(target, intent_path):
        intent_writes += 1
    should_kill = (
        (mode == "stage" and same_path(target, stage_path))
        or (mode == "backup" and same_path(target, backup_path))
        or (mode == "destination" and same_path(target, destination))
        or (mode == "result" and same_path(target, result_path))
        or (mode == "intent-initial" and same_path(target, intent_path) and intent_writes == 1)
        or (mode == "intent-update" and same_path(target, intent_path) and intent_writes == 2)
    )
    if should_kill:
        os._exit(91)

def progress_checkpoint(target, temporary, written, total):
    del temporary
    if (
        mode == "stage-midwrite"
        and same_path(target, stage_path)
        and 0 < written < total
    ):
        os._exit(91)

portable._atomic_write_checkpoint = checkpoint
portable._atomic_write_progress_checkpoint = progress_checkpoint
archive.deterministic_zip(package, destination, result_path)
'''
        for mode in (
            "intent-initial",
            "stage",
            "stage-midwrite",
            "backup",
            "destination",
            "result",
            "intent-update",
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = base / "publish/archive.zip"
                destination.parent.mkdir(parents=True)
                if mode == "backup":
                    destination.write_bytes(b"trusted-prior")
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        child,
                        str(ROOT),
                        str(package),
                        str(destination),
                        mode,
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
                intent_path = archive_module.archive_publication_intent_path(
                    package
                )
                if mode == "intent-initial":
                    self.assertFalse(intent_path.exists())
                    candidates = archive_module._intent_atomic_temp_candidates(
                        package
                    )
                    self.assertEqual(len(candidates), 1)
                    with self.assertRaisesRegex(
                        ArchiveSecurityError,
                        "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                    ):
                        archive_module.recover_archive_publication(package)
                    self.assertIn(
                        "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                        {item.code for item in validate_package(package)},
                    )
                    quarantined = archive_module.quarantine_archive_transaction_temps(
                        package, confirm_aborted=True
                    )
                    self.assertEqual(quarantined["status"], "quarantined")
                    self.assertEqual(len(quarantined["quarantined"]), 1)
                    self.assertTrue(
                        Path(quarantined["quarantined"][0]).is_file()
                    )
                    self.assertFalse(
                        archive_module._intent_atomic_temp_candidates(package)
                    )
                    result = archive_module.deterministic_zip(
                        package,
                        destination,
                        package / archive_module.ARCHIVE_RESULT_PATH,
                    )
                    self.assertEqual(
                        archive_module.load_archive_result(package), result
                    )
                    self.assertEqual(validate_package(package), [])
                    continue
                self.assertTrue(intent_path.exists())
                intent = json.loads(intent_path.read_text(encoding="utf-8"))
                generation = intent["generation"]
                owned_targets = (
                    intent_path,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                    destination,
                    archive_module._archive_stage_path(destination),
                    archive_module._archive_backup_path(destination),
                )
                temporaries = [
                    archive_module._publication_atomic_temp_path(
                        target, generation
                    )
                    for target in owned_targets
                ]
                self.assertTrue(
                    any(path.exists() for path in temporaries), temporaries
                )

                if mode == "stage-midwrite":
                    with self.assertRaisesRegex(
                        ArchiveSecurityError,
                        "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                    ):
                        archive_module.recover_archive_publication(package)
                    quarantine = archive_module.quarantine_archive_transaction_temps(
                        package, confirm_aborted=True
                    )
                    self.assertEqual(quarantine["status"], "quarantined")
                archive_module.recover_archive_publication(package)
                self.assertFalse(
                    any(path.exists() for path in temporaries), temporaries
                )
                result = archive_module.deterministic_zip(
                    package,
                    destination,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                )
                self.assertEqual(
                    archive_module.load_archive_result(package), result
                )
                self.assertEqual(validate_package(package), [])

    def test_foreign_generation_named_atomic_temps_are_preserved_fail_closed(self):
        target_names = ("intent", "result", "destination", "stage", "backup")
        for target_name in target_names:
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = base / "publish/archive.zip"
                result_path = package / archive_module.ARCHIVE_RESULT_PATH
                with mock.patch.object(
                    archive_module,
                    "_publication_checkpoint",
                    side_effect=self.crash_at("intent"),
                ), self.assertRaises(SimulatedPublicationCrash):
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )
                intent_path = archive_module.archive_publication_intent_path(
                    package
                )
                intent = json.loads(intent_path.read_text(encoding="utf-8"))
                targets = {
                    "intent": intent_path,
                    "result": result_path,
                    "destination": destination,
                    "stage": archive_module._archive_stage_path(destination),
                    "backup": archive_module._archive_backup_path(destination),
                }
                foreign_temp = archive_module._publication_atomic_temp_path(
                    targets[target_name], intent["generation"]
                )
                foreign_temp.parent.mkdir(parents=True, exist_ok=True)
                foreign_temp.write_bytes(b"attacker-foreign")

                with self.assertRaisesRegex(
                    ArchiveSecurityError,
                    "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                ):
                    archive_module.recover_archive_publication(package)
                self.assertEqual(
                    foreign_temp.read_bytes(), b"attacker-foreign"
                )
                self.assertTrue(intent_path.exists())

    def test_partial_generation_temp_requires_explicit_quarantine_then_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=self.crash_at("intent"),
            ), self.assertRaises(SimulatedPublicationCrash):
                archive_module.deterministic_zip(
                    package, destination, result_path
                )
            intent = json.loads(
                archive_module.archive_publication_intent_path(package).read_text(
                    encoding="utf-8"
                )
            )
            partial = archive_module._publication_atomic_temp_path(
                archive_module._archive_stage_path(destination),
                intent["generation"],
            )
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"partial-generation-bytes")
            with self.assertRaisesRegex(
                ArchiveSecurityError,
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
            ):
                archive_module.recover_archive_publication(package)
            self.assertEqual(partial.read_bytes(), b"partial-generation-bytes")

            quarantined = archive_module.quarantine_archive_transaction_temps(
                package, confirm_aborted=True
            )
            self.assertEqual(quarantined["status"], "quarantined")
            self.assertFalse(partial.exists())
            preserved = [Path(path) for path in quarantined["quarantined"]]
            self.assertIn(
                b"partial-generation-bytes",
                [path.read_bytes() for path in preserved],
            )
            archive_module.recover_archive_publication(package)
            result = archive_module.deterministic_zip(
                package, destination, result_path
            )
            self.assertEqual(archive_module.load_archive_result(package), result)
            self.assertEqual(validate_package(package), [])

    def test_validation_is_linearized_against_publication_intent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            validator_checked = threading.Event()
            release_validator = threading.Event()
            publisher_entered = threading.Event()
            intent_reached = threading.Event()
            validator_result: list[list[object]] = []
            thread_errors: list[BaseException] = []
            original_check = archive_module.assert_no_archive_recovery_required
            original_capture = archive_module._capture_snapshot

            def pause_after_clean_check(root: str | Path) -> None:
                original_check(root)
                if Path(root).resolve() == package.resolve() and not validator_checked.is_set():
                    validator_checked.set()
                    if not release_validator.wait(10):
                        raise AssertionError("validator race fixture timed out")

            def crash_after_intent(checkpoint: str) -> None:
                if checkpoint == "intent":
                    intent_reached.set()
                    raise SimulatedPublicationCrash(checkpoint)

            def observe_capture(root: str | Path, *args, **kwargs):
                if Path(root).resolve() == package.resolve():
                    publisher_entered.set()
                return original_capture(root, *args, **kwargs)

            def run_validator() -> None:
                try:
                    validator_result.append(validate_package(package))
                except BaseException as exc:
                    thread_errors.append(exc)

            def run_archive() -> None:
                try:
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )
                except SimulatedPublicationCrash:
                    return
                except BaseException as exc:
                    thread_errors.append(exc)

            validator = threading.Thread(target=run_validator, daemon=True)
            publisher = threading.Thread(target=run_archive, daemon=True)
            with mock.patch.object(
                archive_module,
                "assert_no_archive_recovery_required",
                side_effect=pause_after_clean_check,
            ), mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=crash_after_intent,
            ), mock.patch.object(
                archive_module,
                "_capture_snapshot",
                side_effect=observe_capture,
            ):
                validator.start()
                self.assertTrue(validator_checked.wait(10))
                publisher.start()
                try:
                    self.assertFalse(
                        publisher_entered.wait(1),
                        "publication crossed the validation linearization boundary",
                    )
                finally:
                    release_validator.set()
                validator.join(30)
                publisher.join(30)

            self.assertFalse(validator.is_alive())
            self.assertFalse(publisher.is_alive())
            self.assertFalse(thread_errors, thread_errors)
            self.assertEqual(validator_result, [[]])
            self.assertTrue(publisher_entered.is_set())
            self.assertTrue(intent_reached.is_set())
            self.assertTrue(
                archive_module.archive_publication_intent_path(package).exists()
            )
            self.assertIn(
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                {item.code for item in validate_package(package)},
            )

    def test_intent_precedes_external_material_and_recover_aborts_after_snapshot_change(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            archive_module.deterministic_zip(package, destination, result_path)
            prior_archive = destination.read_bytes()
            prior_result = result_path.read_bytes()
            StateStore(package).update(
                expected_revision=1,
                blocker={"generation": "prepared-before-crash"},
            )

            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=self.crash_at("intent"),
            ), self.assertRaises(SimulatedPublicationCrash):
                archive_module.deterministic_zip(package, destination, result_path)

            intent = archive_module.archive_publication_intent_path(package)
            stage = archive_module._archive_stage_path(destination)
            backup = archive_module._archive_backup_path(destination)
            self.assertTrue(intent.exists())
            self.assertFalse(stage.exists())
            self.assertFalse(backup.exists())
            self.assertEqual(destination.read_bytes(), prior_archive)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertIn(
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
                {item.code for item in validate_package(package)},
            )
            from chip_supergoal.terminal import finalize_package

            with self.assertRaisesRegex(
                Exception, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                finalize_package(package)
            from chip_supergoal.audit import audit_package

            with self.assertRaisesRegex(
                Exception, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                audit_package(package)

            StateStore(package).update(
                expected_revision=2,
                blocker={"generation": "mutated-after-intent"},
            )
            archive_module.recover_archive_publication(package)
            self.assertEqual(destination.read_bytes(), prior_archive)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertFalse(intent.exists())
            self.assertFalse(stage.exists())
            self.assertFalse(backup.exists())

    def test_recovery_aborts_partial_stage_backup_before_staged_phase(self):
        for has_prior in (False, True):
            with self.subTest(has_prior=has_prior), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                package = self.package(base)
                destination = base / "publish/archive.zip"
                result_path = package / archive_module.ARCHIVE_RESULT_PATH
                prior_archive = None
                prior_result = None
                if has_prior:
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )
                    prior_archive = destination.read_bytes()
                    prior_result = result_path.read_bytes()
                    StateStore(package).update(
                        expected_revision=1,
                        blocker={"partial": "stage-backup"},
                    )
                original_writer = archive_module._write_publication_intent
                calls = 0

                def crash_before_staged_phase(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise SimulatedPublicationCrash("before-staged-phase")
                    return original_writer(*args, **kwargs)

                with mock.patch.object(
                    archive_module,
                    "_write_publication_intent",
                    side_effect=crash_before_staged_phase,
                ), self.assertRaises(SimulatedPublicationCrash):
                    archive_module.deterministic_zip(
                        package, destination, result_path
                    )

                intent = archive_module.archive_publication_intent_path(package)
                stage = archive_module._archive_stage_path(destination)
                backup = archive_module._archive_backup_path(destination)
                self.assertTrue(intent.exists())
                self.assertTrue(stage.exists())
                self.assertEqual(backup.exists(), has_prior)
                archive_module.recover_archive_publication(package)
                self.assertFalse(intent.exists())
                self.assertFalse(stage.exists())
                self.assertFalse(backup.exists())
                if has_prior:
                    self.assertEqual(destination.read_bytes(), prior_archive)
                    self.assertEqual(result_path.read_bytes(), prior_result)
                else:
                    self.assertFalse(destination.exists())
                    self.assertFalse(result_path.exists())

    def test_foreign_destination_during_recovery_is_preserved_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            result_path = package / archive_module.ARCHIVE_RESULT_PATH
            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=self.crash_at("intent"),
            ), self.assertRaises(SimulatedPublicationCrash):
                archive_module.deterministic_zip(package, destination, result_path)
            destination.write_bytes(b"foreign-concurrent-bytes")
            intent = archive_module.archive_publication_intent_path(package)
            self.assertTrue(intent.exists())

            with self.assertRaisesRegex(
                ArchiveSecurityError,
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
            ):
                archive_module.deterministic_zip(package, destination, result_path)
            self.assertEqual(destination.read_bytes(), b"foreign-concurrent-bytes")
            self.assertTrue(intent.exists())

    def test_concurrent_leaf_replacement_before_publish_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            destination.parent.mkdir()
            destination.write_bytes(b"trusted-prior")
            replaced = False

            def replace_at_checkpoint(checkpoint: str) -> None:
                nonlocal replaced
                if checkpoint == "before_destination" and not replaced:
                    destination.write_bytes(b"foreign-concurrent-bytes")
                    replaced = True

            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=replace_at_checkpoint,
            ), self.assertRaisesRegex(
                ArchiveSecurityError,
                "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED",
            ):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                )
            self.assertTrue(replaced)
            self.assertEqual(destination.read_bytes(), b"foreign-concurrent-bytes")
            self.assertTrue(
                archive_module.archive_publication_intent_path(package).exists()
            )

    def test_pending_intent_blocks_validation_and_finalize(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=self.crash_at("intent"),
            ), self.assertRaises(SimulatedPublicationCrash):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                )
            codes = {item.code for item in validate_package(package)}
            self.assertIn("SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED", codes)
            self.assertNotIn("SGV-PACKAGE-MANIFEST-FILESET", codes)
            from chip_supergoal.terminal import finalize_package

            with self.assertRaisesRegex(
                Exception, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                finalize_package(package)

    def test_tampered_intent_is_strictly_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            package = self.package(base)
            destination = base / "publish/archive.zip"
            with mock.patch.object(
                archive_module,
                "_publication_checkpoint",
                side_effect=self.crash_at("intent"),
            ), self.assertRaises(SimulatedPublicationCrash):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                )
            intent_path = archive_module.archive_publication_intent_path(package)
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            intent["unexpected"] = "foreign"
            tampered = archive_module._canonical_json_bytes(intent)
            intent_path.write_bytes(tampered)
            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                archive_module.deterministic_zip(
                    package,
                    destination,
                    package / archive_module.ARCHIVE_RESULT_PATH,
                )
            self.assertEqual(intent_path.read_bytes(), tampered)


if __name__ == "__main__":
    unittest.main()
