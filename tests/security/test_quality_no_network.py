import ast
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import quality_report_bytes
from tests.quality.test_quality_lint import valid_quality_contract


class QualityNoNetworkTests(unittest.TestCase):
    def test_quality_module_has_no_provider_or_network_imports(self):
        source = (ROOT / "lib/chip_supergoal/quality.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({"socket", "urllib", "http", "requests", "httpx", "openai", "anthropic"}))

    def test_lint_report_does_not_open_a_socket(self):
        policy = json.loads((ROOT / "spec/plan-quality-policy.json").read_text(encoding="utf-8"))
        rubric = json.loads((ROOT / "spec/quality-rubric.json").read_text(encoding="utf-8"))
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            payload = quality_report_bytes(valid_quality_contract(), policy, rubric)
        self.assertEqual(json.loads(payload)["schema_version"], "plan-quality-lint-v1")


if __name__ == "__main__":
    unittest.main()
