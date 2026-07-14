from __future__ import annotations

import unittest
from unittest import mock

from evals.harness.sandbox_hyperv import probe_hyperv
from evals.harness.sandbox_podman import ESCAPE_CLASSES, probe_podman


class SandboxBackendTests(unittest.TestCase):
    @mock.patch("evals.harness.sandbox_podman.shutil.which", return_value=None)
    def test_missing_podman_is_import_only_not_synthetic_pass(self, _which):
        report = probe_podman()
        self.assertEqual(report["status"], "import_only")
        self.assertFalse(report["authoritative"])
        self.assertEqual(report["probes"], [])

    @mock.patch("evals.harness.sandbox_hyperv.platform.system", return_value="Linux")
    def test_non_windows_hyperv_is_import_only(self, _system):
        report = probe_hyperv()
        self.assertEqual(report["status"], "import_only")
        self.assertFalse(report["authoritative"])

    @mock.patch("evals.harness.sandbox_podman.shutil.which", return_value="/usr/bin/podman")
    @mock.patch("evals.harness.sandbox_podman.subprocess.run")
    def test_rootful_podman_fails_closed(self, run, _which):
        run.return_value = mock.Mock(returncode=0, stdout='{"host":{"security":{"rootless":false}}}', stderr="")
        report = probe_podman()
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["authoritative"])
        self.assertIn("rootless_required", report["findings"])

    def test_escape_taxonomy_is_complete(self):
        self.assertEqual(
            set(ESCAPE_CLASSES),
            {"host", "input", "sibling", "env", "network", "process", "resource", "output"},
        )


if __name__ == "__main__":
    unittest.main()
