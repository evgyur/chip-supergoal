#!/usr/bin/env python3
"""Close P02 only when plan, capabilities, and provenance are cryptographically bound."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def build_closeout(
    *,
    plan: Path,
    expected_plan_sha256: str,
    capabilities_path: Path,
    provenance_path: Path,
) -> dict[str, Any]:
    actual_plan_sha = sha256(plan)
    if actual_plan_sha != expected_plan_sha256:
        raise ValueError("plan SHA-256 mismatch")
    capabilities = load_json(capabilities_path)
    provenance = load_json(provenance_path)
    selected = capabilities.get("selected_foundation_sha")
    rollback = capabilities.get("rollback_sha")
    if selected == rollback or selected != provenance.get("selected_foundation_sha"):
        raise ValueError("selected/rollback provenance binding mismatch")
    if rollback != provenance.get("rollback_sha"):
        raise ValueError("rollback provenance binding mismatch")
    if capabilities.get("plan_sha256") != actual_plan_sha or provenance.get("plan_sha256") != actual_plan_sha:
        raise ValueError("plan is not bound to both capability and provenance records")
    if capabilities.get("native_windows_v1", {}).get("status") != "pass":
        raise ValueError("native_windows_v1 is not green")
    if capabilities.get("linux_parity", {}).get("status") != "pass":
        raise ValueError("Linux parity is not green")
    if provenance.get("commit_count") != 29 or provenance.get("changed_file_count") != 151:
        raise ValueError("foundation provenance is incomplete")
    return {
        "schema_version": "p02-foundation-closeout-v1",
        "status": "pass",
        "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_foundation_sha": selected,
        "rollback_sha": rollback,
        "plan": {"path": plan.as_posix(), "sha256": actual_plan_sha},
        "capabilities": {"path": capabilities_path.as_posix(), "sha256": sha256(capabilities_path)},
        "provenance": {"path": provenance_path.as_posix(), "sha256": sha256(provenance_path)},
        "criteria": {
            "P02-C01": "pass",
            "P02-C02": "pass",
            "P02-C03": "pass",
            "P02-C04": "pass",
        },
        "runtime_advance_authorized": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--capabilities", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo).resolve()
    closeout = build_closeout(
        plan=(repo / args.plan).resolve(),
        expected_plan_sha256=args.plan_sha256,
        capabilities_path=(repo / args.capabilities).resolve(),
        provenance_path=(repo / args.provenance).resolve(),
    )
    rpd_review = repo / "evidence/supergoal/P02-rpd-review.json"
    if not rpd_review.is_file():
        raise ValueError("required P02 RPD review is missing")
    closeout["rpd_review"] = {"path": rpd_review.as_posix(), "sha256": sha256(rpd_review)}
    output = (repo / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(closeout))
    print(json.dumps({"ok": True, "output": output.as_posix(), "selected_foundation_sha": closeout["selected_foundation_sha"], "plan_sha256": closeout["plan"]["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
