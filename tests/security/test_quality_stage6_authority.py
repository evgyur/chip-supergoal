from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.harness.canary import stage6_dispatch_authorized


def digest(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()


class QualityStage6AuthorityTests(unittest.TestCase):
    def test_quality_green_alone_never_authorizes_dispatch(self):
        report = {"status": "green", "plan_subject_sha256": "a" * 64, "report_sha256": "b" * 64}
        self.assertFalse(stage6_dispatch_authorized(report, None))

    def test_current_exact_human_approval_is_required(self):
        report = {"status": "green", "plan_subject_sha256": "a" * 64, "report_sha256": "b" * 64}
        approval = {
            "schema_version": "stage6-approval-v1", "human_approved": True, "current": True,
            "plan_subject_sha256": "a" * 64, "report_sha256": "b" * 64,
        }
        approval["approval_sha256"] = digest(approval)
        self.assertTrue(stage6_dispatch_authorized(report, approval))
        approval["report_sha256"] = "c" * 64
        self.assertFalse(stage6_dispatch_authorized(report, approval))


if __name__ == "__main__":
    unittest.main()
