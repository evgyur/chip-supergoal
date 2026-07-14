from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RuntimeBoundaryTests(unittest.TestCase):
    def test_runtime_package_never_imports_evals_or_provider_sdks(self):
        forbidden = {"evals", "openai", "anthropic", "google.generativeai", "litellm"}
        findings = []
        for path in (ROOT / "lib/chip_supergoal").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if any(name == item or name.startswith(item + ".") for item in forbidden):
                        findings.append(f"{path.name}:{name}")
        self.assertEqual(findings, [])

    def test_public_requirements_do_not_contain_eval_providers(self):
        text = (ROOT / "requirements-test.txt").read_text(encoding="utf-8").lower()
        for forbidden in ("openai", "anthropic", "litellm", "podman-py"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
