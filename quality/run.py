#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import lint_false_green_fragment

EXPECTED = {
    "B2-FG-01": "QG-MISSING-TRACE",
    "B2-FG-02": "QG-UNBOUND-SOURCE",
    "B2-FG-03": "QG-FUTURE-DEPENDENCY",
    "B2-FG-04": "QG-APPROVAL-SCOPE",
    "B2-FG-05": "QG-RUNTIME-AUTHORITY",
}


def lint_fixtures() -> int:
    records = []
    unexpected_passes = []
    fixtures = ROOT / "evals/b2/fixtures"
    for case_id, expected_code in EXPECTED.items():
        path = next(fixtures.glob(f"{case_id}-*.json"))
        fixture = json.loads(path.read_text(encoding="utf-8"))
        codes = sorted({item.code for item in lint_false_green_fragment(fixture["plan_fragment"])})
        rejected = expected_code in codes
        if not rejected:
            unexpected_passes.append(case_id)
        records.append({"id": case_id, "expected_code": expected_code, "codes": codes, "rejected": rejected})
    report = {
        "schema_version": "quality-fixture-lint-v1",
        "fixtures": len(records),
        "rejected": sum(item["rejected"] for item in records),
        "unexpected_passes": unexpected_passes,
        "records": records,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if unexpected_passes else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["lint-fixtures"]:
        print("usage: quality/run.py lint-fixtures", file=sys.stderr)
        return 2
    return lint_fixtures()


if __name__ == "__main__":
    raise SystemExit(main())
