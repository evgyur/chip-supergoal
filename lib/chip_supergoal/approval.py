"""Offline SSHSIG Stage-6 authority with package-canonical trust files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

TRUST_RELATIVE = Path("spec/stage6-allowed-signers")
REVOCATIONS_RELATIVE = Path("spec/stage6-revoked-fingerprints.txt")
SCHEMA_RELATIVE = Path("spec/stage6-approval.schema.json")
NAMESPACE = "supergoal-stage6"


class ApprovalError(ValueError):
    pass


_WINDOWS_UNTRUSTED_SIDS = {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"}
_WINDOWS_WRITE_MASK = 2 | 4 | 16 | 64 | 256 | 65536 | 262144 | 524288


def _check_windows_acl(path: Path) -> None:
    if os.name != "nt":
        return
    script = (
        "$a=Get-Acl -LiteralPath $env:SUPERGOAL_ACL_PATH; "
        "$a.Access | ForEach-Object { "
        "$sid=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; "
        "Write-Output ($sid+'|'+[int]$_.FileSystemRights+'|'+$_.AccessControlType) }"
    )
    environment = dict(os.environ)
    environment["SUPERGOAL_ACL_PATH"] = str(path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise ApprovalError(f"authority ACL could not be verified: {path.name}")
    for line in result.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) == 3 and fields[0] in _WINDOWS_UNTRUSTED_SIDS and fields[2].lower() == "allow":
            try:
                rights = int(fields[1])
            except ValueError as exc:
                raise ApprovalError(f"authority ACL is malformed: {path.name}") from exc
            if rights & _WINDOWS_WRITE_MASK:
                raise ApprovalError(f"authority ACL grants write access to an untrusted principal: {path.name}")


def _canonical(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_stable(path: Path) -> bytes:
    _check_windows_acl(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ApprovalError(f"authority path is not a regular file: {path.name}")
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise ApprovalError(f"authority path is a reparse point: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApprovalError(f"authority path could not be opened safely: {path.name}") from exc
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ApprovalError(f"authority handle is not a regular file: {path.name}")
        if getattr(opened, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ApprovalError(f"authority handle is a reparse point: {path.name}")
        if os.name == "posix" and opened.st_mode & 0o022:
            raise ApprovalError(f"authority path is group/world writable: {path.name}")
        return stream.read()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ApprovalError("approval timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _fingerprint_for_identity(trust_bytes: bytes, identity: str) -> str:
    try:
        text = trust_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApprovalError("trusted signer file is not UTF-8") from exc
    matches = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 3 and identity in fields[0].split(","):
            matches.append(f"{fields[1]} {fields[2]}\n")
    if len(matches) != 1:
        raise ApprovalError("signer identity must resolve to exactly one trusted key")
    result = subprocess.run(
        ["ssh-keygen", "-lf", "-", "-E", "sha256"], input=matches[0], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise ApprovalError("trusted signer key is not a valid OpenSSH key")
    parts = result.stdout.split()
    if len(parts) < 2 or not parts[1].startswith("SHA256:"):
        raise ApprovalError("could not derive trusted signer fingerprint")
    return parts[1]


def approval_ready_for_dispatch(
    package_root: str | Path,
    receipt_path: str | Path,
    signature_path: str | Path,
    *,
    expected_plan_subject_sha256: str,
    expected_quality_report_sha256: str,
    expected_event_sha256: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure readiness validation; performs no dispatch or state mutation."""
    root = Path(package_root).resolve()
    receipt_file = Path(receipt_path).absolute()
    signature_file = Path(signature_path).absolute()
    trust = root / TRUST_RELATIVE
    revocations = root / REVOCATIONS_RELATIVE
    schema_file = root / SCHEMA_RELATIVE
    raw = _read_stable(receipt_file)
    signature_bytes = _read_stable(signature_file)
    trust_bytes = _read_stable(trust)
    revocation_bytes = _read_stable(revocations)
    schema_bytes = _read_stable(schema_file)
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovalError("approval receipt is not strict UTF-8 JSON") from exc
    if raw != _canonical(receipt):
        raise ApprovalError("approval receipt bytes are not canonical")
    try:
        jsonschema.Draft202012Validator(json.loads(schema_bytes), format_checker=jsonschema.FormatChecker()).validate(receipt)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovalError("approval schema is not strict UTF-8 JSON") from exc
    except jsonschema.ValidationError as exc:
        raise ApprovalError(f"approval receipt schema mismatch: {exc.message}") from exc
    expected = {
        "plan_subject_sha256": expected_plan_subject_sha256,
        "quality_report_sha256": expected_quality_report_sha256,
        "event_sha256": expected_event_sha256,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ApprovalError("approval binding mismatch")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not (_timestamp(receipt["issued_at"]) <= current < _timestamp(receipt["expires_at"])):
        raise ApprovalError("approval is stale or not yet valid")
    if receipt["trust_root_sha256"] != hashlib.sha256(trust_bytes).hexdigest():
        raise ApprovalError("approval trust root was swapped")
    fingerprint = _fingerprint_for_identity(trust_bytes, receipt["signer_identity"])
    if receipt["key_fingerprint"] != fingerprint:
        raise ApprovalError("approval signer fingerprint mismatch")
    try:
        revocation_text = revocation_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApprovalError("revocation file is not UTF-8") from exc
    revoked = {line.strip() for line in revocation_text.splitlines() if line.strip() and not line.lstrip().startswith("#")}
    if fingerprint in revoked:
        raise ApprovalError("approval signer is revoked")
    with tempfile.TemporaryDirectory(prefix="stage6-verify-") as temporary:
        stable_trust = Path(temporary) / "allowed_signers"
        stable_signature = Path(temporary) / "approval.sig"
        stable_trust.write_bytes(trust_bytes)
        stable_signature.write_bytes(signature_bytes)
        os.chmod(stable_trust, 0o600)
        os.chmod(stable_signature, 0o600)
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(stable_trust), "-I", receipt["signer_identity"], "-n", NAMESPACE, "-s", str(stable_signature)],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    if result.returncode != 0:
        raise ApprovalError("approval SSHSIG verification failed")
    return {
        "ready": True,
        "receipt_id": receipt["receipt_id"],
        "signer_identity": receipt["signer_identity"],
        "key_fingerprint": fingerprint,
        "event_sha256": receipt["event_sha256"],
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "trust_root_sha256": receipt["trust_root_sha256"],
    }
