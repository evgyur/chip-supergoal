import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.delivery import ReceiptValidationError, read_receipt


class DeliveryReceiptSchemaTest(unittest.TestCase):
    def test_sent_at_schema_requires_exact_rfc3339_utc_seconds(self):
        for name in (
            "review-md-files-delivery-receipt.schema.json",
            "final-artifacts-delivery-receipt.schema.json",
        ):
            with self.subTest(schema=name):
                schema = json.loads(
                    (ROOT / "templates/delivery" / name).read_text(encoding="utf-8")
                )
                pattern = schema["properties"]["sent_at"].get("pattern", "")
                self.assertIsNotNone(
                    re.fullmatch(pattern, "2026-07-11T12:34:56Z")
                )
                for invalid in (
                    "2026-07-11T12:34:56.123Z",
                    "2026-07-11T12:34:56+00:00",
                    "2026-07-11 12:34:56Z",
                ):
                    self.assertIsNone(re.fullmatch(pattern, invalid), invalid)

    def test_shell_receipt_producers_delegate_to_package_local_sgctl(self):
        expected = {
            "send-review-md-files.sh": (
                "delivery-review-check",
                "delivery-review-record",
            ),
            "send-final-artifacts.sh": (
                "delivery-final-check",
                "delivery-final-record",
            ),
        }
        for name, commands in expected.items():
            with self.subTest(script=name):
                script = (ROOT / "templates/delivery" / name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("$ROOT/scripts/sgctl.py", script)
                for command in commands:
                    self.assertIn(command, script)
                self.assertNotIn("json.dump", script)
                self.assertNotIn("<<'PY'", script)

    def test_receipt_reader_rejects_nonfinite_extension_values(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "receipt.json"
            path.write_text(
                json.dumps(
                    {"extensions": {"not_json": float("nan")}},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(ReceiptValidationError, "malformed"):
                read_receipt(path, root)


if __name__ == "__main__":
    unittest.main()
