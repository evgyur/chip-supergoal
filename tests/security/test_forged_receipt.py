from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.archive import deterministic_zip
from chip_supergoal.compile import compile_contract_file


SOURCE = ROOT / "examples/brownfield-feature/CONTRACT.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash"),
    "real POSIX wrapper integration unavailable",
)
class ForgedReceiptSecurity(unittest.TestCase):
    def package(
        self,
        parent: Path,
        *,
        final: bool,
        review_files: list[str] | None = None,
        retain_research: bool = False,
    ) -> Path:
        data = json.loads(SOURCE.read_text(encoding="utf-8"))
        data["profile"] = "chip-private"
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        if not retain_research:
            data["compatibility"].pop("research_gate", None)
        data["delivery"] = {
            "items": ["artifact.zip"] if final else [],
            "receipt_policy": {"required": True},
            "review_pack_required": not final,
            "target": "current-thread",
            "transport": "telegram",
        }
        if not final:
            data["delivery"]["files"] = review_files or [
                "LAUNCH_GOAL.md",
                "LOOP_DESIGN.md",
                "ROADMAP.md",
                "THINKING.md",
            ]
        source = parent / "CONTRACT.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        return compile_contract_file(source, parent / "package")

    def transport_environment(self, parent: Path, package: Path) -> tuple[dict[str, str], Path]:
        counter = parent / "transport-count.txt"
        transport = parent / "fake-transport.sh"
        transport.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf 'sent\\n' >> {str(counter)!r}\n"
            "printf 'message-id\\n'\n",
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
        return env, counter

    def test_review_md_files_rejects_minimal_forged_receipt_without_send(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent, final=False)
            out = package / "out"
            out.mkdir(exist_ok=True)
            names = [
                "LAUNCH_GOAL.md",
                "LOOP_DESIGN.md",
                "ROADMAP.md",
                "THINKING.md",
            ]
            hashes = {name: sha256(package / name) for name in names}
            (out / "review-md-files-delivery-receipt.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "sent": True,
                        "target": "current-thread",
                        "hashes": hashes,
                    }
                ),
                encoding="utf-8",
            )
            env, counter = self.transport_environment(parent, package)
            wrapper = package / "templates/delivery/send-review-md-files.sh"
            result = subprocess.run(
                ["bash", str(wrapper)],
                cwd=parent,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SGV-DELIVERY-RECEIPT-INVALID", result.stderr)
            self.assertFalse(counter.exists())

    def test_final_artifacts_rejects_minimal_forged_receipt_without_send(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent, final=True)
            out = package / "out"
            archive = parent / "final-artifacts.zip"
            deterministic_zip(
                package,
                archive,
                out / "final-artifacts-manifest.json",
            )
            (out / "final-artifacts-delivery-receipt.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "sent": True,
                        "target": "current-thread",
                        "hash": sha256(archive),
                    }
                ),
                encoding="utf-8",
            )
            env, counter = self.transport_environment(parent, package)
            wrapper = package / "templates/delivery/send-final-artifacts.sh"
            result = subprocess.run(
                ["bash", str(wrapper), str(archive)],
                cwd=parent,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SGV-DELIVERY-RECEIPT-INVALID", result.stderr)
            self.assertFalse(counter.exists())

    def test_forced_final_resend_preflights_before_transport(self):
        scenarios = (
            "wrong-target",
            "wrong-archive",
            "terminal-frozen",
            "unsafe-receipt",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.package(parent, final=True)
                archive = parent / "final-artifacts.zip"
                deterministic_zip(
                    package,
                    archive,
                    package / "out/final-artifacts-manifest.json",
                )
                requested_archive = archive
                env, counter = self.transport_environment(parent, package)
                env["SUPERGOAL_FORCE_RESEND"] = "1"
                expected = "SGV-STATE-TERMINAL-FROZEN"
                if scenario == "wrong-target":
                    env["SUPERGOAL_DELIVERY_TARGET"] = "wrong-thread"
                    expected = "SGV-DELIVERY-TARGET-MISMATCH"
                elif scenario == "wrong-archive":
                    requested_archive = parent / "foreign.zip"
                    requested_archive.write_bytes(b"not-the-canonical-archive")
                    expected = "SGV-DELIVERY-ARCHIVE-MISSING"
                elif scenario == "terminal-frozen":
                    (package / "reports").mkdir(exist_ok=True)
                    (package / "reports/terminal-record.txt").write_text(
                        "frozen\n", encoding="utf-8"
                    )
                else:
                    (package / "out").mkdir(exist_ok=True)
                    (
                        package
                        / "out/final-artifacts-delivery-receipt.json"
                    ).mkdir()
                    expected = "SGV-DELIVERY-RECEIPT-INVALID"

                result = subprocess.run(
                    [
                        "bash",
                        str(package / "templates/delivery/send-final-artifacts.sh"),
                        str(requested_archive),
                    ],
                    cwd=parent,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertIn(expected, result.stderr)
                self.assertFalse(counter.exists(), "transport ran before authorization")

    def test_forced_review_resend_preflights_before_transport(self):
        for scenario in ("wrong-target", "terminal-frozen", "unsafe-receipt"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.package(parent, final=False)
                env, counter = self.transport_environment(parent, package)
                env["SUPERGOAL_FORCE_RESEND"] = "1"
                expected = "SGV-STATE-TERMINAL-FROZEN"
                if scenario == "wrong-target":
                    env["SUPERGOAL_DELIVERY_TARGET"] = "wrong-thread"
                    expected = "SGV-DELIVERY-TARGET-MISMATCH"
                elif scenario == "terminal-frozen":
                    (package / "reports").mkdir(exist_ok=True)
                    (package / "reports/terminal-record.txt").write_text(
                        "frozen\n", encoding="utf-8"
                    )
                else:
                    (package / "out").mkdir(exist_ok=True)
                    (
                        package
                        / "out/review-md-files-delivery-receipt.json"
                    ).mkdir()
                    expected = "SGV-DELIVERY-RECEIPT-INVALID"

                result = subprocess.run(
                    [
                        "bash",
                        str(package / "templates/delivery/send-review-md-files.sh"),
                    ],
                    cwd=parent,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertIn(expected, result.stderr)
                self.assertFalse(counter.exists(), "transport ran before authorization")

    def test_review_send_rejects_sealed_drift_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            package = self.package(parent, final=False)
            (package / "THINKING.md").write_text(
                "FORGED OR SECRET CONTENT\n", encoding="utf-8"
            )
            env, counter = self.transport_environment(parent, package)
            result = subprocess.run(
                [
                    "bash",
                    str(package / "templates/delivery/send-review-md-files.sh"),
                ],
                cwd=parent,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SGV-DELIVERY-FILE-SET-MISMATCH", result.stderr)
            self.assertFalse(counter.exists())

    def test_review_wrapper_sends_exact_authorized_file_set(self):
        core = [
            "LAUNCH_GOAL.md",
            "LOOP_DESIGN.md",
            "ROADMAP.md",
            "THINKING.md",
        ]
        scenarios = (
            ("extra-contract", [*core, "CONTRACT.json"], False),
            ("undeclared-research", core, True),
        )
        for name, declared, retain_research in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                package = self.package(
                    parent,
                    final=False,
                    review_files=declared,
                    retain_research=retain_research,
                )
                if retain_research:
                    self.assertTrue((package / "RESEARCH.md").is_file())
                    self.assertNotIn("RESEARCH.md", declared)
                env, counter = self.transport_environment(parent, package)
                wrapper = package / "templates/delivery/send-review-md-files.sh"
                result = subprocess.run(
                    ["bash", str(wrapper)],
                    cwd=parent,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertEqual(
                    counter.read_text(encoding="utf-8").splitlines(),
                    ["sent"] * len(declared),
                )
                receipt = json.loads(
                    (
                        package
                        / "out/review-md-files-delivery-receipt.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(receipt["files"], sorted(declared))


if __name__ == "__main__":
    unittest.main()
