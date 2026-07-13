from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "b2-neutral-probe-v1"


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_fingerprint(root: Path) -> str:
    ignored = {
        "STATE.md",
        "runtime/STATE.json",
        "runtime/EVENTS.jsonl",
        "runtime/events.jsonl",
        "runtime/evidence.json",
        "runtime/operation.lock",
        "runtime/seal.json",
        "runtime/bindings.json",
    }
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in ignored or relative.startswith("out/"):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def summarize_measurements(values: Iterable[float], *, expected: int) -> dict[str, float | int]:
    samples = [float(value) for value in values]
    if len(samples) != expected:
        raise ValueError(f"measurement count {len(samples)} does not match frozen count {expected}")
    if not samples:
        raise ValueError("measurement count must be positive")
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "p50": float(statistics.median(ordered)),
        "p95": ordered[p95_index],
        "maximum": ordered[-1],
    }


def empty_capability_receipt_for_test(required: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "native-windows-v1-receipt",
        "status": "pass",
        "capabilities": {name: {"status": "pass", "evidence": ["neutral-probe"]} for name in required},
    }


def validate_capability_receipt(receipt: dict[str, Any], required: list[str]) -> bool:
    capabilities = receipt.get("capabilities", {})
    missing = sorted(set(required) - set(capabilities))
    if missing:
        raise ValueError(f"missing capabilities: {missing}")
    failing = sorted(
        name for name in required if capabilities.get(name, {}).get("status") != "pass"
    )
    if failing:
        raise ValueError(f"failing capabilities: {failing}")
    if receipt.get("status") != "pass":
        raise ValueError("capability receipt status is not pass")
    return True


def empty_probe_result_for_test() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "target_sha": "0" * 40,
        "environment": {},
        "command_records": [],
        "measurements": {},
        "capability_receipt": {},
        "findings": [],
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(result))


def _run(
    command: list[str],
    *,
    cwd: Path,
    records: list[dict[str, Any]],
    name: str,
    expected_returncodes: set[int] | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    duration = time.perf_counter() - started
    record = {
        "name": name,
        "argv": [str(item) for item in command],
        "cwd_role": "target-repository",
        "duration_seconds": round(duration, 6),
        "returncode": completed.returncode,
        "stdout_sha256": _sha256_bytes(completed.stdout),
        "stderr_sha256": _sha256_bytes(completed.stderr),
    }
    records.append(record)
    allowed = expected_returncodes if expected_returncodes is not None else {0}
    if completed.returncode not in allowed:
        raise RuntimeError(
            f"neutral probe {name} returned {completed.returncode}; "
            f"stdout_sha256={record['stdout_sha256']} stderr_sha256={record['stderr_sha256']}"
        )
    return completed


def _aggregate_command(repo: Path) -> list[str]:
    native_runner = repo / "scripts" / "test.py"
    if native_runner.is_file():
        return [sys.executable, str(native_runner)]
    if os.name == "nt":
        raise RuntimeError("target lacks a native Windows aggregate test runner")
    shell_runner = repo / "scripts" / "test.sh"
    if not shell_runner.is_file():
        raise RuntimeError("target lacks an aggregate test runner")
    return ["bash", str(shell_runner)]


def _fixture_contract(repo: Path) -> Path:
    candidates = (
        repo / "examples" / "brownfield-feature" / "CONTRACT.json",
        repo / "examples" / "minimal" / "CONTRACT.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    discovered = sorted((repo / "examples").glob("*/CONTRACT.json"))
    if not discovered:
        raise RuntimeError("target has no public example contract")
    return discovered[0]


def _directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def probe_repository(
    repo: Path,
    *,
    repetitions: int,
    warmups: int,
    required_capabilities: list[str],
    aggregate_mode: str = "smoke",
) -> dict[str, Any]:
    repo = repo.resolve()
    records: list[dict[str, Any]] = []
    sha_result = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        records=records,
        name="git-head",
    )
    target_sha = sha_result.stdout.decode("ascii", errors="strict").strip()
    _run(
        [sys.executable, str(repo / "scripts" / "sgctl.py"), "--help"],
        cwd=repo,
        records=records,
        name="public-cli-help",
    )
    if aggregate_mode == "full":
        _run(
            _aggregate_command(repo),
            cwd=repo,
            records=records,
            name="target-aggregate-suite",
        )
    elif aggregate_mode != "smoke":
        raise ValueError(f"unsupported aggregate mode: {aggregate_mode}")

    contract = _fixture_contract(repo)
    compile_seconds: list[float] = []
    fingerprints: list[str] = []
    package_sizes: list[int] = []
    with tempfile.TemporaryDirectory(prefix="b2-neutral-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        # The long, spaced, Unicode target is a neutral path portability probe.
        output_parent = temporary_root / ("path with space 🙂 " + ("long-" * 20))
        output_parent.mkdir(parents=True)
        total_runs = warmups + repetitions
        for index in range(total_runs):
            output = output_parent / f"package-{index}"
            started = time.perf_counter()
            _run(
                [
                    sys.executable,
                    str(repo / "scripts" / "sgctl.py"),
                    "compile",
                    str(contract),
                    "--out",
                    str(output),
                ],
                cwd=repo,
                records=records,
                name=f"compile-{index}",
            )
            elapsed = time.perf_counter() - started
            _run(
                [
                    sys.executable,
                    str(output / "scripts" / "sgctl.py"),
                    "validate-package",
                    str(output),
                    "--strict",
                ],
                cwd=output,
                records=records,
                name=f"self-contained-validate-{index}",
            )
            if index >= warmups:
                compile_seconds.append(elapsed)
                fingerprints.append(_tree_fingerprint(output))
                package_sizes.append(_directory_size(output))

        malformed = temporary_root / "malformed.CONTRACT.json"
        malformed.write_text("{}\n", encoding="utf-8")
        rejected = temporary_root / "malformed-output"
        _run(
            [
                sys.executable,
                str(repo / "scripts" / "sgctl.py"),
                "compile",
                str(malformed),
                "--out",
                str(rejected),
            ],
            cwd=repo,
            records=records,
            name="malformed-input-rejected",
            expected_returncodes=set(range(1, 256)),
        )
        if rejected.exists() and any(rejected.iterdir()):
            raise RuntimeError("malformed compile left a populated output target")

    deterministic = len(set(fingerprints)) == 1
    if not deterministic:
        raise RuntimeError("neutral repeated compiles are not deterministic")
    compile_summary = summarize_measurements(compile_seconds, expected=repetitions)
    size_summary = summarize_measurements(
        [float(value) for value in package_sizes],
        expected=repetitions,
    )

    capability_status = "pass" if aggregate_mode == "full" else "partial"
    capability_evidence = {
        name: {
            "status": capability_status,
            "evidence": [
                "self-contained-validate",
                "deterministic-long-unicode-path-compile",
            ] + (["target-aggregate-suite"] if aggregate_mode == "full" else []),
        }
        for name in required_capabilities
    }
    receipt = {
        "schema_version": "native-windows-v1-receipt",
        "status": capability_status,
        "platform": platform.system().lower(),
        "python": platform.python_version(),
        "target_sha": target_sha,
        "capabilities": capability_evidence,
    }
    if aggregate_mode == "full":
        validate_capability_receipt(receipt, required_capabilities)
    return {
        "schema_version": SCHEMA_VERSION,
        "probe_sha256": _sha256_bytes(Path(__file__).read_bytes()),
        "status": "pass",
        "target_sha": target_sha,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
        },
        "command_records": records,
        "measurements": {
            "compile_seconds": compile_summary,
            "package_bytes": size_summary,
            "warmup_repetitions": warmups,
            "measured_repetitions": repetitions,
            "deterministic_fingerprint": fingerprints[0],
        },
        "capability_receipt": receipt,
        "findings": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="External neutral black-box probe for B2")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--aggregate-mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--capabilities-json", required=True)
    args = parser.parse_args()
    try:
        required = json.loads(args.capabilities_json)
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError("--capabilities-json must be a JSON string array")
        result = probe_repository(
            Path(args.repo),
            repetitions=args.repetitions,
            warmups=args.warmups,
            required_capabilities=required,
            aggregate_mode=args.aggregate_mode,
        )
        write_result(Path(args.output), result)
        print(
            json.dumps(
                {
                    "ok": True,
                    "output": str(Path(args.output)),
                    "target_sha": result["target_sha"],
                    "status": result["status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        target_sha = "unknown"
        try:
            target_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(args.repo),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
        failure = {
            "schema_version": SCHEMA_VERSION,
            "probe_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "status": "fail",
            "target_sha": target_sha,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "machine": platform.machine(),
            },
            "command_records": [],
            "measurements": {},
            "capability_receipt": {"status": "fail", "capabilities": {}},
            "findings": [
                {
                    "id": "neutral-probe-failed",
                    "severity": "P1",
                    "summary": "neutral probe failed closed",
                    "error_class": type(exc).__name__,
                }
            ],
        }
        write_result(Path(args.output), failure)
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_class": type(exc).__name__,
                    "output": str(Path(args.output)),
                    "target_sha": target_sha,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
