from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SCRIPT = Path(__file__).resolve().with_name("execution-lease.py")


class ExecutionLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "out" / "runtime").mkdir(parents=True, mode=0o700)
        (self.root / "out").chmod(0o700)
        (self.root / "out" / "runtime").chmod(0o700)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_lease(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["python3", str(SCRIPT), *args], text=True, capture_output=True, check=False)
        if check and proc.returncode != 0:
            self.fail(f"lease command failed: {proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}")
        return proc

    def test_acquire_check_refresh_release_and_no_token_egress(self) -> None:
        acquired = self.run_lease("acquire", str(self.root), "--owner", "test")
        token_path = self.root / "out" / "runtime" / ".execution-lease-token"
        owner_path = self.root / "out" / ".execution-lease" / "owner.json"
        token = token_path.read_text().strip()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)
        self.assertNotIn(token, acquired.stdout)
        self.assertNotIn(token, owner_path.read_text())
        wrong_owner = self.run_lease("check", str(self.root), "--owner", "rival", check=False)
        self.assertNotEqual(wrong_owner.returncode, 0)
        self.run_lease("check", str(self.root), "--owner", "test")
        self.run_lease("refresh", str(self.root), "--owner", "test")
        rival = self.run_lease("acquire", str(self.root), "--owner", "rival", check=False)
        self.assertNotEqual(rival.returncode, 0)
        self.run_lease("release", str(self.root), "--owner", "test")
        self.assertFalse((self.root / "out" / ".execution-lease").exists())
        self.assertFalse(token_path.exists())

    def test_atomic_race_has_exactly_one_winner(self) -> None:
        def attempt(owner: str) -> subprocess.CompletedProcess[str]:
            return self.run_lease("acquire", str(self.root), "--owner", owner, check=False)
        owners = ["one", "two"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, owners))
        self.assertEqual(sum(p.returncode == 0 for p in results), 1)
        winning_owner = owners[next(i for i, result in enumerate(results) if result.returncode == 0)]
        self.run_lease("release", str(self.root), "--owner", winning_owner)

    def test_stale_recovery_requires_reason_threshold_and_proven_owner_death(self) -> None:
        owner_proc = subprocess.Popen(["python3", "-c", "import time; time.sleep(60)"])
        try:
            self.run_lease("acquire", str(self.root), "--owner", "stale", "--owner-pid", str(owner_proc.pid))
            owner_path = self.root / "out" / ".execution-lease" / "owner.json"
            owner = json.loads(owner_path.read_text())
            owner["heartbeat_at"] = 1
            owner_path.write_text(json.dumps(owner) + "\n")
            no_reason = self.run_lease("recover", str(self.root), "--after-seconds", "300", check=False)
            self.assertNotEqual(no_reason.returncode, 0)
            live = self.run_lease("recover", str(self.root), "--after-seconds", "300", "--reason", "must not displace live owner", check=False)
            self.assertNotEqual(live.returncode, 0)
            owner_proc.terminate()
            owner_proc.wait(timeout=5)
            self.run_lease("recover", str(self.root), "--after-seconds", "300", "--reason", "owner process exited")
        finally:
            if owner_proc.poll() is None:
                owner_proc.kill()
                owner_proc.wait(timeout=5)
        self.assertFalse((self.root / "out" / ".execution-lease").exists())
        receipts = list((self.root / "out" / "runtime").glob("execution-lease-recovery-*.json"))
        self.assertEqual(len(receipts), 1)

    def test_token_path_escape_is_rejected(self) -> None:
        escaped = self.root / "outside-token"
        proc = self.run_lease("acquire", str(self.root), "--token-file", str(escaped), check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(escaped.exists())


if __name__ == "__main__":
    unittest.main()
