"""Rootless Podman containment capability probe."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ESCAPE_CLASSES = ("host", "input", "sibling", "env", "network", "process", "resource", "output")


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _base(status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "sandbox-capability-v1",
        "backend": "rootless-podman",
        "platform": "linux",
        "status": status,
        "authoritative": status == "pass",
        "reason": reason,
        "escape_classes": list(ESCAPE_CLASSES),
        "probes": [],
        "findings": [],
    }


def _load_attestation(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if value.get("backend") != "rootless-podman" or value.get("status") != "pass":
        raise ValueError("Podman attestation is not a passing rootless-podman receipt")
    probes = value.get("probes", [])
    observed = {item.get("escape_class") for item in probes if item.get("denied") is True}
    if observed != set(ESCAPE_CLASSES):
        raise ValueError("Podman attestation does not deny the complete escape taxonomy")
    declared = value.pop("receipt_sha256", None)
    actual = hashlib.sha256(_canonical(value)).hexdigest()
    if declared != actual:
        raise ValueError("Podman attestation commitment mismatch")
    value["receipt_sha256"] = declared
    value["authoritative"] = True
    return value


def probe_podman() -> dict[str, Any]:
    imported = os.environ.get("SUPERGOAL_PODMAN_ATTESTATION")
    if imported:
        try:
            return _load_attestation(Path(imported))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report = _base("fail", "invalid_imported_attestation")
            report["findings"].append(type(exc).__name__)
            return report
    executable = shutil.which("podman")
    if executable is None:
        return _base("import_only", "podman_unavailable")
    info = subprocess.run([executable, "info", "--format", "json"], capture_output=True, text=True, timeout=30)
    if info.returncode != 0:
        report = _base("fail", "podman_info_failed")
        report["findings"].append("capability_query_failed")
        return report
    try:
        rootless = json.loads(info.stdout).get("host", {}).get("security", {}).get("rootless") is True
    except json.JSONDecodeError:
        rootless = False
    if not rootless:
        report = _base("fail", "podman_is_not_rootless")
        report["findings"].append("rootless_required")
        return report
    image = os.environ.get("SUPERGOAL_PODMAN_IMAGE")
    if not image:
        return _base("import_only", "preinstalled_image_commitment_required")
    inspect = subprocess.run([executable, "image", "inspect", image, "--format", "{{.Digest}}"], capture_output=True, text=True, timeout=30)
    if inspect.returncode != 0 or "sha256:" not in inspect.stdout:
        return _base("import_only", "committed_image_unavailable")
    # A live adversarial probe is deliberately not synthesized here. An isolated controller
    # must run all eight checks and import the immutable receipt through the path above.
    return _base("import_only", "external_adversarial_probe_required")
