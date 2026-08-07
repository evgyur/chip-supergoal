from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("runtime-init.py")
REQUIRED = ("PLAN.md", "TODO.md", "MEMORY.md", "STATUS.md", "RUN_LOG.md", "CHECKS.md", "REVIEW.md")


class RuntimeInitTests(unittest.TestCase):
    def make_root(self, base: Path) -> Path:
        root = base / "package"
        seed = root / "runtime-seed"
        seed.mkdir(parents=True)
        os.chmod(root, 0o755)
        os.chmod(seed, 0o755)
        for name in REQUIRED:
            (seed / name).write_text(f"seed {name}\n")
        return root

    def run_init(self, root: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        p = subprocess.run(["python3", str(SCRIPT), str(root)], text=True, capture_output=True)
        if check and p.returncode != 0:
            self.fail(f"runtime init failed: {p.returncode} {p.stdout!r} {p.stderr!r}")
        return p

    def test_owner_only_idempotent_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.make_root(Path(td))
            self.run_init(root)
            self.run_init(root)
            for name in REQUIRED:
                p = root / "out" / "runtime" / name
                self.assertEqual(p.read_text(), f"seed {name}\n")
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / "out").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "out" / "runtime").stat().st_mode), 0o700)

    def test_concurrent_initialization_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.make_root(Path(td))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.run_init(root, check=False), range(2)))
            self.assertEqual([p.returncode for p in results], [0, 0])
            self.assertEqual(sorted(p.name for p in (root / "out" / "runtime").glob("*.md")), sorted(REQUIRED))

    def test_out_symlink_is_rejected_without_escape_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = self.make_root(base)
            outside = base / "outside"
            outside.mkdir()
            (root / "out").symlink_to(outside, target_is_directory=True)
            p = self.run_init(root, check=False)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])

    def test_broad_out_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.make_root(Path(td))
            (root / "out").mkdir(mode=0o777)
            os.chmod(root / "out", 0o777)
            p = self.run_init(root, check=False)
            self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
