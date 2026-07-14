"""Native Windows Hyper-V capability receipt loader.

The local Linux controller never claims synthetic Hyper-V containment. A Windows
probe must create an immutable receipt after using an ephemeral Generation-2 VM.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any

from .sandbox_podman import ESCAPE_CLASSES


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _base(status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "sandbox-capability-v1",
        "backend": "native-windows-hyperv-gen2",
        "platform": "windows",
        "status": status,
        "authoritative": status == "pass",
        "reason": reason,
        "escape_classes": list(ESCAPE_CLASSES),
        "probes": [],
        "findings": [],
    }


def _load_attestation(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if value.get("backend") != "native-windows-hyperv-gen2" or value.get("status") != "pass":
        raise ValueError("Hyper-V attestation is not a passing native receipt")
    if value.get("generation") != 2 or value.get("ephemeral_reset_verified") is not True:
        raise ValueError("Hyper-V attestation lacks Generation-2/reset evidence")
    observed = {item.get("escape_class") for item in value.get("probes", []) if item.get("denied") is True}
    if observed != set(ESCAPE_CLASSES):
        raise ValueError("Hyper-V attestation does not deny the complete escape taxonomy")
    declared = value.pop("receipt_sha256", None)
    actual = hashlib.sha256(_canonical(value)).hexdigest()
    if declared != actual:
        raise ValueError("Hyper-V attestation commitment mismatch")
    value["receipt_sha256"] = declared
    value["authoritative"] = True
    return value


def probe_hyperv() -> dict[str, Any]:
    imported = os.environ.get("SUPERGOAL_HYPERV_ATTESTATION")
    if imported:
        try:
            return _load_attestation(Path(imported))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report = _base("fail", "invalid_imported_attestation")
            report["findings"].append(type(exc).__name__)
            return report
    if platform.system() != "Windows":
        return _base("import_only", "native_windows_unavailable")
    # Running New-VM is an effectful operation and requires an explicitly provisioned
    # image/controller. Without its immutable receipt, stay non-authoritative.
    return _base("import_only", "ephemeral_gen2_controller_receipt_required")
