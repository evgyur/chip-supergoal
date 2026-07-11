from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import chip_supergoal.archive as archive_module
from chip_supergoal.archive import ArchiveSecurityError, deterministic_zip
from chip_supergoal.compile import compile_contract_file


SOURCE = ROOT / "examples" / "brownfield-feature" / "CONTRACT.json"


class ArchiveManifestCollisionTest(unittest.TestCase):
    def package(self, parent: Path) -> Path:
        return compile_contract_file(SOURCE, parent / "package")

    def rewrite_result_for_archive(
        self,
        result_path: Path,
        archive_bytes: bytes,
        *,
        records: list[dict] | None = None,
        archive_manifest_bytes: bytes | None = None,
    ) -> None:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["archive_bytes"] = len(archive_bytes)
        result["archive_sha256"] = hashlib.sha256(archive_bytes).hexdigest()
        if records is not None:
            result["snapshot_files"] = records
        if archive_manifest_bytes is not None:
            result["archive_manifest_sha256"] = hashlib.sha256(
                archive_manifest_bytes
            ).hexdigest()
        result_path.write_bytes(archive_module._canonical_json_bytes(result))

    def snapshot_records(self, *paths: str) -> list[dict]:
        return [
            {
                "bytes": 0,
                "mode": archive_module.logical_mode(path),
                "path": path,
                "sha256": hashlib.sha256(b"").hexdigest(),
            }
            for path in sorted({"MANIFEST.json", *paths})
        ]

    def forge_archive_members(
        self,
        destination: Path,
        result_path: Path,
        replacements: dict[str, bytes | None],
    ) -> bytes:
        with zipfile.ZipFile(destination) as zipped:
            source = {
                info.filename: zipped.read(info)
                for info in zipped.infolist()
                if info.filename != archive_module.ARCHIVE_MANIFEST_NAME
            }
        for path, content in replacements.items():
            if content is None:
                source.pop(path, None)
            else:
                source[path] = content
        captures = [
            archive_module.CapturedFile(
                path,
                data,
                archive_module.logical_mode(path),
                (0, 0, len(data), 0),
            )
            for path, data in sorted(source.items())
        ]
        records = [item.record() for item in captures]
        archive_manifest_bytes = archive_module._canonical_json_bytes(
            archive_module._manifest_for(captures)
        )
        stream = io.BytesIO()
        archive_module._write_archive(stream, captures, archive_manifest_bytes)
        forged = stream.getvalue()
        destination.write_bytes(forged)
        self.rewrite_result_for_archive(
            result_path,
            forged,
            records=records,
            archive_manifest_bytes=archive_manifest_bytes,
        )
        return forged

    def test_source_manifest_occurs_once_and_is_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            source_manifest = (package / "MANIFEST.json").read_bytes()
            destination = parent / "archive.zip"
            deterministic_zip(
                package,
                destination,
                package / "out/final-artifacts-manifest.json",
            )
            with zipfile.ZipFile(destination) as zipped:
                self.assertEqual(zipped.namelist().count("MANIFEST.json"), 1)
                self.assertEqual(zipped.namelist().count("ARCHIVE-MANIFEST.json"), 1)
                self.assertEqual(len(zipped.namelist()), len(set(zipped.namelist())))
                self.assertEqual(zipped.read("MANIFEST.json"), source_manifest)
                inventory = json.loads(zipped.read("ARCHIVE-MANIFEST.json"))
                self.assertNotIn("ARCHIVE-MANIFEST.json", [row["path"] for row in inventory["files"]])
                manifest_row = next(row for row in inventory["files"] if row["path"] == "MANIFEST.json")
                self.assertEqual(manifest_row["sha256"], hashlib.sha256(source_manifest).hexdigest())

    def test_inside_root_destination_is_rejected_through_relative_alias(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = package / "out" / "archive.zip"
            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT"
            ):
                deterministic_zip(
                    package,
                    destination,
                    package / "out/final-artifacts-manifest.json",
                )
            self.assertFalse(destination.exists())

    def test_result_path_cannot_overwrite_sealed_or_arbitrary_package_authority(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            authority = package / "CONTRACT.json"
            original = authority.read_bytes()
            with self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-PATH-ESCAPE"):
                deterministic_zip(package, parent / "archive.zip", authority)
            self.assertEqual(authority.read_bytes(), original)

    def test_readback_failure_preserves_prior_destination_and_result(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            prior_destination = destination.read_bytes()
            prior_result = result_path.read_bytes()
            original_readback = archive_module._verify_archive

            with mock.patch.object(
                archive_module,
                "_verify_archive",
                side_effect=ArchiveSecurityError("SGV-PACKAGE-ZIP-HASH-MISMATCH: forced"),
            ), self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"):
                deterministic_zip(package, destination, result_path)

            self.assertEqual(destination.read_bytes(), prior_destination)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertEqual(list(parent.glob(".archive.zip.tmp-*")), [])
            self.assertTrue(callable(original_readback))

    def test_result_publication_failure_rolls_back_destination_and_result(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            prior_destination = destination.read_bytes()
            prior_result = result_path.read_bytes()
            original_atomic = archive_module.write_bytes_atomic

            def fail_result(path, content, *, root=None, **kwargs):
                if Path(path) == result_path:
                    raise OSError("forced result publication failure")
                return original_atomic(path, content, root=root, **kwargs)

            with mock.patch.object(
                archive_module,
                "write_bytes_atomic",
                side_effect=fail_result,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                deterministic_zip(package, destination, result_path)

            self.assertEqual(destination.read_bytes(), prior_destination)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertEqual(list(parent.glob(".archive.zip.tmp-*")), [])
            self.assertEqual(list(parent.glob(".archive.zip.backup-*")), [])

    def test_failure_at_result_publication_restores_exact_prior_pair(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            prior_destination = destination.read_bytes()
            prior_result = result_path.read_bytes()
            original_atomic = archive_module.write_bytes_atomic
            failed = False

            def fail_result_only(path, content, *, root=None, **kwargs):
                nonlocal failed
                if Path(path) == result_path and not failed:
                    failed = True
                    raise OSError("forced result-only publication failure")
                return original_atomic(path, content, root=root, **kwargs)

            with mock.patch.object(
                archive_module,
                "write_bytes_atomic",
                side_effect=fail_result_only,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED"
            ):
                deterministic_zip(package, destination, result_path)

            self.assertTrue(failed)
            self.assertEqual(destination.read_bytes(), prior_destination)
            self.assertEqual(result_path.read_bytes(), prior_result)
            self.assertEqual(list(parent.glob(".archive.zip.tmp-*")), [])
            self.assertEqual(list(parent.glob(".archive.zip.backup-*")), [])

    def test_failure_after_result_write_restores_exact_prior_pair(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            prior_destination = destination.read_bytes()
            prior_result = result_path.read_bytes()
            original_load = archive_module.load_archive_result
            load_calls = 0

            def fail_persisted_pair(root, **kwargs):
                nonlocal load_calls
                loaded = original_load(root, **kwargs)
                load_calls += 1
                if load_calls >= 1:
                    raise ArchiveSecurityError(
                        "SGV-PACKAGE-ZIP-HASH-MISMATCH: forced persisted-pair failure"
                    )
                return loaded

            with mock.patch.object(
                archive_module,
                "load_archive_result",
                side_effect=fail_persisted_pair,
            ), self.assertRaisesRegex(
                ArchiveSecurityError, "forced persisted-pair failure"
            ):
                deterministic_zip(package, destination, result_path)

            self.assertEqual(load_calls, 1)
            self.assertEqual(destination.read_bytes(), prior_destination)
            self.assertEqual(result_path.read_bytes(), prior_result)

    def test_existing_destination_hardlink_to_package_authority_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "hardlink.zip"
            try:
                destination.hardlink_to(package / "CONTRACT.json")
            except OSError as exc:
                self.skipTest(f"hardlink fixture unavailable: {exc}")
            original = (package / "CONTRACT.json").read_bytes()
            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT"
            ):
                deterministic_zip(
                    package,
                    destination,
                    package / "out/final-artifacts-manifest.json",
                )
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual((package / "CONTRACT.json").read_bytes(), original)

    def test_tampered_archive_metadata_invalidates_canonical_result(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                zipped.writestr("MANIFEST.json", b"tampered")
            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
            ):
                archive_module.load_archive_result(package)

    def test_forged_archive_and_result_cannot_replace_a_sealed_artifact(self):
        """Archive/result self-consistency is not package authenticity."""

        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)

            self.forge_archive_members(
                destination,
                result_path,
                {
                    "THINKING.md": (package / "THINKING.md").read_bytes()
                    + b"forged-but-self-consistent\n"
                },
            )

            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-(?:MANIFEST-HASH|ZIP-HASH-MISMATCH)"
            ):
                archive_module.load_archive_result(package)

    def test_forged_archive_cannot_carry_malformed_registered_mutable_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            self.forge_archive_members(
                destination,
                result_path,
                {"runtime/evidence.json": b"{malformed\n"},
            )

            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-MANIFEST-HASH"
            ):
                archive_module.load_archive_result(package)

    def test_forged_archive_cannot_omit_a_required_mutable_path(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            self.forge_archive_members(
                destination,
                result_path,
                {"runtime/evidence.json": None},
            )

            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-MANIFEST-HASH"
            ):
                archive_module.load_archive_result(package)

    def test_archive_result_recomputes_secret_scan_over_source_members(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            contract_raw = (package / "CONTRACT.json").read_bytes()
            contract = json.loads(contract_raw)
            event = json.loads(
                (package / "runtime/events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )
            phase = contract["phases"][0]
            criterion = phase["criteria"][0]
            command = phase["commands"][0]
            evidence = [
                {
                    "assertion": criterion["verifier"]["expected_assertion"],
                    "captured_at": event["timestamp"],
                    "command": command["command"],
                    "contract_revision": contract["contract_revision"],
                    "contract_sha256": hashlib.sha256(contract_raw).hexdigest(),
                    "criterion_id": criterion["id"],
                    "evidence_id": "EVD-FORGED-SECRET",
                    "exit_code": criterion["verifier"]["expected_exit"],
                    "fresh_until": "audit_end",
                    "goal_id": contract["goal"]["id"],
                    "metadata": {
                        "notes": "-----BEGIN " + "PRIVATE KEY----- not-a-real-key"
                    },
                    "phase_id": phase["id"],
                    "producer": "archive-security-test",
                    "redaction": "passed",
                    "replayable": True,
                    "result": "pass",
                    "type": "command_result",
                }
            ]
            evidence_bytes = archive_module._canonical_json_bytes(evidence)
            self.forge_archive_members(
                destination,
                result_path,
                {"runtime/evidence.json": evidence_bytes},
            )

            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-SECRET"
            ):
                archive_module.load_archive_result(package)

    def test_archive_result_recomputes_canonical_path_format_label(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            canonical = archive_module._archive_identity(destination.resolve())
            result["archive_identity"]["path_format"] = (
                "posix" if canonical["path_format"] == "windows" else "windows"
            )
            result_path.write_bytes(archive_module._canonical_json_bytes(result))

            with self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
            ):
                archive_module.load_archive_result(package)

    def test_local_zip_header_tampering_invalidates_canonical_result(self):
        """Central-directory metadata cannot bless noncanonical local headers."""

        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent)
            destination = parent / "archive.zip"
            result_path = package / "out/final-artifacts-manifest.json"
            deterministic_zip(package, destination, result_path)
            canonical_archive = destination.read_bytes()
            canonical_result = result_path.read_bytes()
            first = canonical_archive.index(b"PK\x03\x04")

            def changed_word(offset: int) -> bytes:
                candidate = bytearray(canonical_archive)
                value = int.from_bytes(candidate[first + offset : first + offset + 2], "little")
                candidate[first + offset : first + offset + 2] = (value ^ 0x0002).to_bytes(
                    2, "little"
                )
                return bytes(candidate)

            def added_local_extra() -> bytes:
                candidate = bytearray(canonical_archive)
                name_length = int.from_bytes(
                    candidate[first + 26 : first + 28], "little"
                )
                insert_at = first + 30 + name_length
                candidate[first + 28 : first + 30] = (2).to_bytes(2, "little")
                candidate[insert_at:insert_at] = b"XY"
                central = candidate.index(b"PK\x01\x02")
                cursor = central
                while candidate[cursor : cursor + 4] == b"PK\x01\x02":
                    local_offset = int.from_bytes(
                        candidate[cursor + 42 : cursor + 46], "little"
                    )
                    if local_offset > first:
                        candidate[cursor + 42 : cursor + 46] = (
                            local_offset + 2
                        ).to_bytes(4, "little")
                    name_len = int.from_bytes(
                        candidate[cursor + 28 : cursor + 30], "little"
                    )
                    extra_len = int.from_bytes(
                        candidate[cursor + 30 : cursor + 32], "little"
                    )
                    comment_len = int.from_bytes(
                        candidate[cursor + 32 : cursor + 34], "little"
                    )
                    cursor += 46 + name_len + extra_len + comment_len
                eocd = candidate.index(b"PK\x05\x06", cursor)
                central_offset = int.from_bytes(
                    candidate[eocd + 16 : eocd + 20], "little"
                )
                candidate[eocd + 16 : eocd + 20] = (central_offset + 2).to_bytes(
                    4, "little"
                )
                return bytes(candidate)

            cases = {
                "local flag": changed_word(6),
                "local DOS time": changed_word(10),
                "local DOS date": changed_word(12),
                "local extra": added_local_extra(),
            }
            for label, tampered in cases.items():
                with self.subTest(label=label):
                    destination.write_bytes(tampered)
                    result_path.write_bytes(canonical_result)
                    self.rewrite_result_for_archive(result_path, tampered)
                    with self.assertRaisesRegex(
                        ArchiveSecurityError, "SGV-PACKAGE-ZIP-HASH-MISMATCH"
                    ):
                        archive_module.load_archive_result(package)

    def test_archive_paths_reject_windows_portability_hazards_on_every_os(self):
        forbidden = (
            "CON",
            "nul.txt",
            "dir/COM1.log",
            "dir/Lpt9.anything",
            "name:stream",
            "C:drive-like.txt",
            "trailing.",
            "trailing ",
            "dir/AUX.json",
            "CONIN$",
            "dir/com¹.txt",
        )
        for path in forbidden:
            with self.subTest(path=path), self.assertRaisesRegex(
                ArchiveSecurityError, "SGV-PACKAGE-ZIP-TRAVERSAL"
            ):
                archive_module._validate_record_list(self.snapshot_records(path))

        accepted = self.snapshot_records(
            "dir with spaces/файл ü.txt", "presentation.com10.txt"
        )
        self.assertEqual(archive_module._validate_record_list(accepted), accepted)


if __name__ == "__main__":
    unittest.main()
