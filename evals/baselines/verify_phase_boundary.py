#!/usr/bin/env python3
"""Verify P02 closure before admitting the immutable QL-00 baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def compile_fingerprint(repo: Path, contract: Path, output: Path) -> str:
    if output.exists():
        shutil.rmtree(output)
    run(["python", "scripts/sgctl.py", "compile", str(contract), "--out", str(output)], cwd=repo)
    run(["python", "scripts/sgctl.py", "validate-package", str(output), "--strict"], cwd=repo)
    return str(load_json(output / "MANIFEST.json")["package_fingerprint"])


def resolve_record_path(repo: Path, record: dict[str, Any]) -> Path:
    path = Path(str(record["path"]))
    if not path.is_absolute():
        path = repo / path
    return path


def verify_boundary(
    repo: Path,
    *,
    foundation_closeout_path: Path,
    baseline_path: Path,
    require_profile_off: bool,
) -> dict[str, Any]:
    closeout = load_json(foundation_closeout_path)
    baseline = load_json(baseline_path)
    if closeout.get("status") != "pass" or not closeout.get("runtime_advance_authorized"):
        raise ValueError("P02 foundation closeout does not authorize runtime advance")
    if baseline.get("status") != "frozen":
        raise ValueError("baseline is not frozen")
    selected = str(closeout["selected_foundation_sha"])
    rollback = str(closeout["rollback_sha"])
    if selected == rollback or baseline["foundation"]["selected_sha"] != selected:
        raise ValueError("P02 closeout and P03 baseline foundation mismatch")
    if baseline["foundation"]["rollback_sha"] != rollback:
        raise ValueError("P02 closeout and P03 rollback mismatch")

    for key in ("capabilities", "provenance", "rpd_review"):
        record = closeout[key]
        path = resolve_record_path(repo, record)
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise ValueError(f"P02 closeout artifact hash mismatch: {key}")
    plan_record = closeout["plan"]
    plan_path = resolve_record_path(repo, plan_record)
    if not plan_path.is_file() or sha256(plan_path) != plan_record["sha256"]:
        raise ValueError("P02 closeout plan hash mismatch")
    if baseline["quality_authority"]["plan_sha256"] != plan_record["sha256"]:
        raise ValueError("baseline plan hash is not the P02 reviewed plan")

    capabilities_path = repo / baseline["foundation"]["capabilities_path"]
    if sha256(capabilities_path) != baseline["foundation"]["capabilities_sha256"]:
        raise ValueError("baseline foundation capability hash mismatch")

    current_compiler_hashes: list[dict[str, str]] = []
    for record in baseline["compiler_adapter"]:
        path = repo / record["path"]
        actual = sha256(path)
        if actual != record["sha256"]:
            raise ValueError(f"profile-off compiler drift before P03: {record['path']}")
        current_compiler_hashes.append({"path": record["path"], "sha256": actual})

    replay_records: list[dict[str, Any]] = []
    if require_profile_off:
        if baseline.get("profile_off", {}).get("status") != "pass":
            raise ValueError("baseline did not freeze profile-off compatibility")
        with tempfile.TemporaryDirectory(prefix="p03-profile-off-") as temporary:
            for record in baseline["representative_packages"]:
                contract = repo / record["contract_path"]
                actual = compile_fingerprint(repo, contract, Path(temporary) / record["id"])
                if actual != record["package_fingerprint"]:
                    raise ValueError(f"profile-off byte compatibility failed: {record['id']}")
                replay_records.append(
                    {
                        "id": record["id"],
                        "expected_package_fingerprint": record["package_fingerprint"],
                        "actual_package_fingerprint": actual,
                        "status": "pass",
                    }
                )

    return {
        "schema_version": "p03-quality-leap-start-v1",
        "status": "pass",
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "foundation_closeout": {
            "path": foundation_closeout_path.relative_to(repo).as_posix(),
            "sha256": sha256(foundation_closeout_path),
        },
        "baseline": {
            "path": baseline_path.relative_to(repo).as_posix(),
            "sha256": sha256(baseline_path),
        },
        "selected_foundation_sha": selected,
        "rollback_sha": rollback,
        "p02_closed_before_p03": True,
        "profile_off_byte_compatibility": {
            "required": require_profile_off,
            "status": "pass",
            "compiler_files": current_compiler_hashes,
            "representative_packages": replay_records,
        },
        "default_planner_behavior_changed": False,
        "runtime_advance_to_p03_authorized": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--foundation-closeout", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--require-profile-off-byte-compatibility", action="store_true")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo).resolve()
    output = (repo / args.output).resolve()
    value = verify_boundary(
        repo,
        foundation_closeout_path=(repo / args.foundation_closeout).resolve(),
        baseline_path=(repo / args.baseline).resolve(),
        require_profile_off=args.require_profile_off_byte_compatibility,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(value))
    print(
        json.dumps(
            {
                "ok": True,
                "output": output.as_posix(),
                "selected_foundation_sha": value["selected_foundation_sha"],
                "profile_off_byte_compatibility": value["profile_off_byte_compatibility"]["status"],
                "p02_closed_before_p03": value["p02_closed_before_p03"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
