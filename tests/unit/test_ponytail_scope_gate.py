from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PonytailScopeGateTest(unittest.TestCase):
    def test_preplan_gate_precedes_loop_and_roadmap(self):
        text = (ROOT / "references/core-planning-contract.md").read_text()
        self.assertLess(text.index("Stage 2.5 — Ponytail scope gate"), text.index("Stage 3.5 — loop design gate"))
        self.assertLess(text.index("Stage 3.5 — loop design gate"), text.index("Stage 4 — decompose"))

    def test_postplan_check_reuses_rpd_review_seat(self):
        text = (ROOT / "references/ponytail-scope-gate.md").read_text()
        self.assertIn("PONYTAIL_FINAL_CHECK", text)
        self.assertIn("not another agent, reviewer", text)
        self.assertIn("review round", text)

    def test_root_routes_to_canonical_gate(self):
        text = (ROOT / "SKILL.md").read_text()
        self.assertIn("references/ponytail-scope-gate.md", text)
        self.assertIn("never in another review", text)

    def test_upstream_ssot_is_explicit(self):
        text = (ROOT / "references/ponytail-scope-gate.md").read_text()
        self.assertIn("DietrichGebert/ponytail", text)
        self.assertIn("skills/ponytail/SKILL.md", text)
        self.assertIn("skills/ponytail-review/SKILL.md", text)
        self.assertIn("advance the gitlink", text)


if __name__ == "__main__":
    unittest.main()
