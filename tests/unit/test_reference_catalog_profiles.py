import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.references import generate_dispatch, generate_index, load_reference_catalog, validate_reference_catalog

class ReferenceCatalogProfilesTest(unittest.TestCase):
    def test_reference_catalog_covers_all_current_reference_files(self):
        catalog = load_reference_catalog(ROOT / "spec/reference-catalog.json")
        self.assertEqual(validate_reference_catalog(ROOT, catalog), [])

    def test_generated_index_and_dispatch_match_catalog(self):
        catalog = load_reference_catalog(ROOT / "spec/reference-catalog.json")
        self.assertEqual(
            (ROOT / "references/INDEX.generated.md").read_text(encoding="utf-8"),
            generate_index(catalog),
        )
        self.assertEqual(
            (ROOT / "references/dispatch.generated.md").read_text(encoding="utf-8"),
            generate_dispatch(catalog),
        )

    def test_profiles_split_private_policy_from_public_clean(self):
        base = json.loads((ROOT / "profiles/base.json").read_text(encoding="utf-8"))
        private = json.loads(
            (ROOT / "profiles/chip-private.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "profiles/public-clean.json").read_text(encoding="utf-8")
        )
        self.assertFalse(base["privacy"]["private_operator_rules"])
        self.assertTrue(private["delivery"]["review_pack_required"])
        public_text = json.dumps(public, ensure_ascii=False).lower()
        self.assertNotIn("chip", public_text)
        self.assertNotIn("telegram", public_text)
        self.assertTrue(public["privacy"]["strip_private_references"])

if __name__ == "__main__":
    unittest.main()
