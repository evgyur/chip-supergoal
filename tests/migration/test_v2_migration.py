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

from chip_supergoal.migrate import MigrationError, migrate_v2_package, read_v2_state_md
import chip_supergoal.migrate as migrate_module
from chip_supergoal.model import load_contract

class V2MigrationTest(unittest.TestCase):
    def test_migration_rejects_symlinked_phase_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "ROADMAP.md").write_text("# Symlink source\n", encoding="utf-8")
            outside = ROOT / "tests/fixtures/v2-valid/package-minimal/phases"
            try:
                (source / "phases").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")

            with self.assertRaisesRegex(MigrationError, "symlink or reparse"):
                migrate_v2_package(source, root / "output")

    @unittest.skipUnless(os.name == "nt", "native Windows junction regression")
    def test_migration_rejects_junctioned_phase_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "ROADMAP.md").write_text("# Junction source\n", encoding="utf-8")
            outside = ROOT / "tests/fixtures/v2-valid/package-minimal/phases"
            junction = source / "phases"
            linked = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if linked.returncode != 0:
                self.skipTest(f"junction creation unavailable: {linked.stderr}")
            self.addCleanup(lambda: os.rmdir(junction) if os.path.lexists(junction) else None)

            output = root / "output"
            with self.assertRaisesRegex(MigrationError, "symlink or reparse"):
                migrate_v2_package(source, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "native Windows junction race regression")
    def test_migration_rejects_phase_junction_swap_after_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            shutil.copytree(
                ROOT / "tests/fixtures/v2-valid/package-minimal", source
            )
            phases = source / "phases"
            original_phases = source / "phases-original"
            outside = ROOT / "tests/fixtures/v2-valid/package-minimal/phases"
            real_snapshot = migrate_module._snapshot_v2_source

            def swap_then_snapshot(*args, **kwargs):
                phases.rename(original_phases)
                linked = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(phases), str(outside)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if linked.returncode != 0:
                    raise unittest.SkipTest(
                        f"junction creation unavailable: {linked.stderr}"
                    )
                return real_snapshot(*args, **kwargs)

            try:
                with mock.patch.object(
                    migrate_module,
                    "_snapshot_v2_source",
                    side_effect=swap_then_snapshot,
                ):
                    with self.assertRaisesRegex(MigrationError, "identity changed"):
                        migrate_v2_package(source, root / "output")
            finally:
                if os.path.lexists(phases):
                    os.rmdir(phases)

    @unittest.skipUnless(os.name == "nt", "native Windows snapshot junction race")
    def test_migration_rejects_snapshot_junction_swap_during_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "output"
            outside = ROOT / "tests/fixtures/v2-valid/package-minimal/phases"
            real_copy = migrate_module._copy_snapshot_to_publication
            swapped_path = None

            def swap_snapshot_then_copy(source, publication):
                nonlocal swapped_path
                phases = source / "phases"
                phases.rename(source / "phases-real")
                linked = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(phases), str(outside)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if linked.returncode != 0:
                    raise unittest.SkipTest(
                        f"junction creation unavailable: {linked.stderr}"
                    )
                swapped_path = phases
                return real_copy(source, publication)

            try:
                with mock.patch.object(
                    migrate_module,
                    "_copy_snapshot_to_publication",
                    side_effect=swap_snapshot_then_copy,
                ):
                    with self.assertRaisesRegex(
                        MigrationError, "symlink or reparse"
                    ):
                        migrate_v2_package(
                            ROOT / "tests/fixtures/v2-valid/package-minimal",
                            output,
                        )
            finally:
                if swapped_path is not None and os.path.lexists(swapped_path):
                    os.rmdir(swapped_path)

            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX snapshot symlink race")
    def test_migration_rejects_snapshot_symlink_swap_during_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "output"
            outside = ROOT / "tests/fixtures/v2-valid/package-minimal/phases"
            real_copy = migrate_module._copy_snapshot_to_publication

            def swap_snapshot_then_copy(source, publication):
                phases = source / "phases"
                phases.rename(source / "phases-real")
                phases.symlink_to(outside, target_is_directory=True)
                return real_copy(source, publication)

            with mock.patch.object(
                migrate_module,
                "_copy_snapshot_to_publication",
                side_effect=swap_snapshot_then_copy,
            ):
                with self.assertRaisesRegex(MigrationError, "symlink or reparse"):
                    migrate_v2_package(
                        ROOT / "tests/fixtures/v2-valid/package-minimal",
                        output,
                    )

            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "native Windows junction race regression")
    def test_migration_never_publishes_through_output_junction_swap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            shutil.copytree(
                ROOT / "tests/fixtures/v2-valid/package-minimal", source
            )
            output = root / "output"
            outside = root / "outside"
            outside.mkdir()
            attacked = False

            def swap_output(_output):
                nonlocal attacked
                attacked = True
                linked = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(output), str(outside)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if linked.returncode != 0:
                    raise unittest.SkipTest(
                        f"junction creation unavailable: {linked.stderr}"
                    )

            try:
                with mock.patch.object(
                    migrate_module,
                    "_migration_publication_checkpoint",
                    side_effect=swap_output,
                ):
                    with self.assertRaisesRegex(
                        MigrationError, "output path already exists"
                    ):
                        migrate_v2_package(source, output)
            finally:
                if os.path.lexists(output):
                    os.rmdir(output)

            self.assertTrue(attacked)
            self.assertEqual(list(outside.iterdir()), [])

    def test_migration_never_publishes_through_output_symlink_swap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            shutil.copytree(
                ROOT / "tests/fixtures/v2-valid/package-minimal", source
            )
            output = root / "output"
            outside = root / "outside"
            outside.mkdir()
            attacked = False

            def swap_output(_output):
                nonlocal attacked
                attacked = True
                try:
                    output.symlink_to(outside, target_is_directory=True)
                except OSError as exc:
                    raise unittest.SkipTest(
                        f"directory symlink creation unavailable: {exc}"
                    ) from exc

            try:
                with mock.patch.object(
                    migrate_module,
                    "_migration_publication_checkpoint",
                    side_effect=swap_output,
                ):
                    with self.assertRaisesRegex(
                        MigrationError, "output path already exists"
                    ):
                        migrate_v2_package(source, output)
            finally:
                if os.path.lexists(output):
                    output.unlink()

            self.assertTrue(attacked)
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "native Windows parent guard regression")
    def test_migration_holds_output_parent_against_junction_swap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = root / "publish-parent"
            parent.mkdir()
            output = parent / "output"
            displaced = root / "displaced-parent"
            outside = root / "outside"
            outside.mkdir()
            attack_blocked = False

            def attempt_parent_swap(_output):
                nonlocal attack_blocked
                try:
                    parent.rename(displaced)
                except OSError:
                    attack_blocked = True
                    return
                raise AssertionError("publication parent rename was not blocked")

            with mock.patch.object(
                migrate_module,
                "_migration_publication_checkpoint",
                side_effect=attempt_parent_swap,
            ):
                report = migrate_v2_package(
                    ROOT / "tests/fixtures/v2-valid/package-minimal", output
                )

            self.assertTrue(attack_blocked)
            self.assertTrue(report["ok"])
            self.assertTrue((output / "CONTRACT.json").is_file())
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "POSIX parent descriptor regression")
    def test_migration_fails_closed_when_output_parent_is_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = root / "publish-parent"
            parent.mkdir()
            output = parent / "output"
            displaced = root / "displaced-parent"
            outside = root / "outside"
            outside.mkdir()

            def swap_parent(_output):
                parent.rename(displaced)
                parent.symlink_to(outside, target_is_directory=True)

            try:
                with mock.patch.object(
                    migrate_module,
                    "_migration_publication_checkpoint",
                    side_effect=swap_parent,
                ):
                    with self.assertRaisesRegex(
                        MigrationError, "output path changed"
                    ):
                        migrate_v2_package(
                            ROOT / "tests/fixtures/v2-valid/package-minimal",
                            output,
                        )
            finally:
                if os.path.lexists(parent):
                    parent.unlink()

            self.assertFalse((displaced / "output").exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_valid_v2_package_migrates_to_valid_v3_contract_with_backup(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "migrated"
            report = migrate_v2_package(ROOT / "tests/fixtures/v2-valid/package-minimal", out)
            self.assertTrue(report["ok"])
            self.assertTrue((out / "v2-backup/ROADMAP.md").is_file())
            contract = load_contract(out / "CONTRACT.json")
            self.assertEqual(contract.schema_version, "3.0")
            self.assertEqual(contract.phases[0].id, "P01")

    def test_existing_output_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "existing"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("preserve", encoding="utf-8")

            with self.assertRaisesRegex(MigrationError, "output path already exists"):
                migrate_v2_package(
                    ROOT / "tests/fixtures/v2-valid/package-minimal", output
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_migration_cli_reports_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "existing"
            output.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    ROOT / "scripts/sgctl.py",
                    "migrate-v2",
                    ROOT / "tests/fixtures/v2-valid/package-minimal",
                    "--out",
                    output,
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("migration error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_v2_package_fails_with_unresolved_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bad"
            (src / "phases").mkdir(parents=True)
            (src / "ROADMAP.md").write_text("# Bad\n", encoding="utf-8")
            (src / "phases/phase-01.md").write_text((ROOT / "tests/fixtures/v2-invalid/phase-99-of-1-rpd-mismatch.md").read_text(), encoding="utf-8")
            with self.assertRaises(MigrationError) as ctx:
                migrate_v2_package(src, Path(td) / "out")
            self.assertIn("migration_unresolved", str(ctx.exception))
            self.assertIn("SGV-PHASE-ORDINAL-OUT-OF-RANGE", str(ctx.exception))

    def test_v2_state_md_read_only_fallback(self):
        state = read_v2_state_md(ROOT / "tests/fixtures/v2-valid/package-minimal/STATE.md")
        self.assertEqual(state["compatibility_mode"], "v2-read-only")
        self.assertEqual(state["current_phase"], "1")

if __name__ == "__main__":
    unittest.main()
