from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any


class ApprovalDenied(ValueError):
    """The approval exists but cannot authorize this event."""


class ArchitectureBlocker(RuntimeError):
    """Canonical Telegram metadata is unavailable; do not guess."""


AFFIRMATIVE = frozenset({"го", "да", "делай", "апрув", "approve", "aprove"})
CARD_FIELDS = (
    "actor_id",
    "bot_id",
    "chat_id",
    "thread_id",
    "request_message_id",
    "goal_id",
    "package_id",
    "action",
    "target",
    "candidate_sha",
    "tree_sha",
    "manifest_sha256",
    "packet_sha256",
    "installed_generation_sha256",
    "reviewed_generation",
)
EVENT_FIELDS = CARD_FIELDS + (
    "reply_message_id",
    "reply_to_message_id",
    "nonce",
    "observed_at",
    "text",
)
_NONCE = re.compile(r"\A[A-Za-z0-9._-]{8,128}\Z")


def _normalize_reply(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _safe_nonce(value: Any) -> str:
    nonce = str(value or "")
    if not _NONCE.fullmatch(nonce):
        raise ApprovalDenied("invalid approval nonce")
    return nonce


def _canonical_context(data: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    missing: list[str] = []
    for field in CARD_FIELDS:
        value = data.get(field)
        if value is None or not str(value).strip():
            missing.append(field)
        else:
            result[field] = str(value)
    if missing:
        raise ArchitectureBlocker(
            "canonical Telegram/approval metadata missing: " + ", ".join(missing)
        )
    return result


def _context_fingerprint(context: dict[str, str]) -> str:
    raw = json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ApprovalStore:
    """Small local one-shot approval ledger with exact direct-reply binding."""

    def __init__(self, root: str | Path):
        self.root = Path(os.path.abspath(root))
        try:
            if self.root.parent.resolve(strict=True) != self.root.parent:
                raise ApprovalDenied("approval ledger parent must not traverse symlinks")
        except OSError as exc:
            raise ApprovalDenied("approval ledger parent is unavailable") from exc
        if self.root.is_symlink():
            raise ApprovalDenied("approval ledger root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._require_directory(self.root)
        os.chmod(self.root, 0o700)
        for name in ("pending", "consumed", "revoked", "receipts", "effects"):
            path = self.root / name
            if path.is_symlink():
                raise ApprovalDenied(f"approval ledger directory is a symlink: {name}")
            path.mkdir(exist_ok=True, mode=0o700)
            self._require_directory(path)
            os.chmod(path, 0o700)

    @staticmethod
    def _require_directory(path: Path) -> None:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise ApprovalDenied(f"unsafe approval ledger directory: {path}")
        if st.st_mode & 0o077:
            raise ApprovalDenied(f"approval ledger directory mode is too broad: {path}")

    @staticmethod
    def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _read_regular(path: Path) -> dict[str, Any]:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except (FileNotFoundError, OSError) as exc:
            raise ApprovalDenied(f"approval card unavailable: {path.name}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
                raise ApprovalDenied("approval card is not an owned regular file")
            if stat.S_IMODE(st.st_mode) & 0o077:
                raise ApprovalDenied("approval card mode is too broad")
            chunks = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > 262144:
                    raise ApprovalDenied("approval card is too large")
        finally:
            os.close(fd)
        try:
            data = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApprovalDenied("approval card is malformed") from exc
        if not isinstance(data, dict):
            raise ApprovalDenied("approval card must be an object")
        return data

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def issue(
        self,
        *,
        context: dict[str, Any],
        nonce: str,
        issued_at: int,
        expires_at: int,
    ) -> dict[str, Any]:
        nonce = _safe_nonce(nonce)
        canonical = _canonical_context(context)
        if int(expires_at) <= int(issued_at):
            raise ApprovalDenied("approval expiry must follow issue time")
        for directory in ("consumed", "revoked"):
            if (self.root / directory / f"{nonce}.json").exists():
                raise ApprovalDenied("approval nonce was already finalized")
        card = {
            "schema": "chip-supergoal.natural-approval-card.v1",
            "state": "pending",
            "nonce": nonce,
            "issued_at": int(issued_at),
            "expires_at": int(expires_at),
            "context": canonical,
            "context_sha256": _context_fingerprint(canonical),
        }
        path = self.root / "pending" / f"{nonce}.json"
        try:
            self._write_exclusive(path, card)
        except FileExistsError as exc:
            raise ApprovalDenied("approval nonce is already pending") from exc
        self._fsync_directory(path.parent)
        return card

    def _pending_cards_for(self, fingerprint: str) -> list[str]:
        matches: list[str] = []
        for path in (self.root / "pending").iterdir():
            if path.suffix != ".json" or path.is_symlink():
                continue
            card = self._read_regular(path)
            if card.get("context_sha256") == fingerprint:
                matches.append(path.name)
        return sorted(matches)

    def _finalize_link(self, nonce: str, destination: str) -> Path:
        source_dir = self.root / "pending"
        destination_dir = self.root / destination
        name = f"{nonce}.json"
        src_fd = os.open(source_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        dst_fd = os.open(destination_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            try:
                os.link(
                    name,
                    name,
                    src_dir_fd=src_fd,
                    dst_dir_fd=dst_fd,
                    follow_symlinks=False,
                )
            except (FileExistsError, FileNotFoundError, OSError) as exc:
                raise ApprovalDenied("approval was already consumed, revoked, or changed") from exc
            try:
                os.unlink(name, dir_fd=src_fd)
            except FileNotFoundError:
                pass
            os.fsync(src_fd)
            os.fsync(dst_fd)
        finally:
            os.close(src_fd)
            os.close(dst_fd)
        return destination_dir / name

    def consume(self, event: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
        missing = [field for field in EVENT_FIELDS if event.get(field) is None]
        if missing:
            raise ArchitectureBlocker(
                "canonical Telegram reply metadata missing: " + ", ".join(missing)
            )
        nonce = _safe_nonce(event["nonce"])
        if (self.root / "consumed" / f"{nonce}.json").exists():
            raise ApprovalDenied("approval replay denied")
        if (self.root / "revoked" / f"{nonce}.json").exists():
            raise ApprovalDenied("approval was revoked")
        card = self._read_regular(self.root / "pending" / f"{nonce}.json")
        if card.get("schema") != "chip-supergoal.natural-approval-card.v1":
            raise ApprovalDenied("approval card schema mismatch")
        context = _canonical_context(event)
        if card.get("context") != context:
            raise ApprovalDenied("approval context mismatch")
        if str(event["reply_to_message_id"]) != context["request_message_id"]:
            raise ApprovalDenied("approval is not a direct reply to the exact card")
        observed_at = int(event["observed_at"])
        consumed_at = int(time.time()) if now is None else int(now)
        if (
            observed_at < int(card["issued_at"])
            or observed_at > int(card["expires_at"])
            or consumed_at > int(card["expires_at"])
        ):
            raise ApprovalDenied("approval is expired or predates the card")
        text = event["text"]
        if not isinstance(text, str) or _normalize_reply(text) not in AFFIRMATIVE:
            raise ApprovalDenied("reply is not an accepted affirmative")
        fingerprint = str(card.get("context_sha256") or "")
        if self._pending_cards_for(fingerprint) != [f"{nonce}.json"]:
            raise ApprovalDenied("approval context is ambiguous")

        self._finalize_link(nonce, "consumed")
        receipt = {
            "schema": "chip-supergoal.natural-approval-receipt.v1",
            "state": "consumed",
            "nonce": nonce,
            "context": context,
            "context_sha256": fingerprint,
            "reply_message_id": str(event["reply_message_id"]),
            "reply_to_message_id": str(event["reply_to_message_id"]),
            "observed_at": observed_at,
            "consumed_at": consumed_at,
            "expires_at": int(card["expires_at"]),
            "raw_text_persisted": False,
        }
        receipt_path = self.root / "receipts" / f"{nonce}.json"
        try:
            self._write_exclusive(receipt_path, receipt)
        except FileExistsError as exc:
            raise ApprovalDenied("approval receipt already exists") from exc
        self._fsync_directory(receipt_path.parent)
        return receipt

    def revoke(self, nonce: str, *, reason: str, revoked_at: int) -> dict[str, Any]:
        nonce = _safe_nonce(nonce)
        if not reason.strip():
            raise ApprovalDenied("revocation reason is required")
        card = self._read_regular(self.root / "pending" / f"{nonce}.json")
        self._finalize_link(nonce, "revoked")
        receipt = {
            "schema": "chip-supergoal.natural-approval-revocation.v1",
            "state": "revoked",
            "nonce": nonce,
            "context_sha256": card.get("context_sha256"),
            "revoked_at": int(revoked_at),
            "reason": reason,
        }
        path = self.root / "receipts" / f"{nonce}.revoked.json"
        self._write_exclusive(path, receipt)
        self._fsync_directory(path.parent)
        return receipt

    def claim_effect(self, receipt: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
        if receipt.get("schema") != "chip-supergoal.natural-approval-receipt.v1" or receipt.get("state") != "consumed":
            raise ApprovalDenied("effect claim requires a consumed natural approval")
        nonce = _safe_nonce(receipt.get("nonce"))
        consumed = self._read_regular(self.root / "consumed" / f"{nonce}.json")
        ledger_receipt = self._read_regular(self.root / "receipts" / f"{nonce}.json")
        if ledger_receipt != receipt or consumed.get("context_sha256") != receipt.get("context_sha256"):
            raise ApprovalDenied("approval ledger does not match effect claim")
        claimed_at = int(time.time()) if now is None else int(now)
        if claimed_at > int(receipt.get("expires_at") or 0):
            raise ApprovalDenied("consumed approval expired before effect claim")
        context = receipt.get("context")
        if not isinstance(context, dict):
            raise ApprovalDenied("effect claim context is missing")
        claim = {
            "schema": "chip-supergoal.approved-effect-claim.v1",
            "state": "claimed",
            "nonce": nonce,
            "claimed_at": claimed_at,
            "context_sha256": receipt.get("context_sha256"),
            "packet_sha256": context.get("packet_sha256"),
            "candidate_sha": context.get("candidate_sha"),
        }
        path = self.root / "effects" / f"{nonce}.json"
        try:
            self._write_exclusive(path, claim)
        except FileExistsError as exc:
            raise ApprovalDenied("approved effect was already claimed") from exc
        self._fsync_directory(path.parent)
        return claim


class PinnedHelperRail:
    """Approval-gated, hash-pinned delegate for the existing rollout helpers."""

    _ALLOWED = {
        "registry_guard": "scripts/hermes-private-patch-registry-guard.py",
        "private_update": "scripts/hermes-private-update.py",
    }

    def __init__(self, *, packet_path: Path, packet: dict[str, Any]):
        self.packet_path = packet_path
        self.packet = packet
        self.server_doctor_root = Path(packet["server_doctor_root"])

    @staticmethod
    def _load_json(path: str | Path) -> tuple[Path, dict[str, Any], str]:
        raw_path = Path(path)
        if raw_path.is_symlink():
            raise ApprovalDenied(f"receipt path must not be a symlink: {raw_path}")
        try:
            resolved = raw_path.resolve(strict=True)
            st = os.lstat(resolved)
        except (FileNotFoundError, OSError) as exc:
            raise ApprovalDenied(f"receipt path unavailable: {raw_path}") from exc
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise ApprovalDenied("receipt must be an owned regular file")
        if st.st_mode & 0o022:
            raise ApprovalDenied("receipt must not be group/world writable")
        raw = resolved.read_bytes()
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApprovalDenied("receipt is malformed") from exc
        if not isinstance(data, dict):
            raise ApprovalDenied("receipt must be an object")
        return resolved, data, hashlib.sha256(raw).hexdigest()

    @classmethod
    def from_files(
        cls,
        packet_path: str | Path,
        approval_path: str | Path,
    ) -> "PinnedHelperRail":
        packet_file, packet, packet_sha = cls._load_json(packet_path)
        _, approval, _ = cls._load_json(approval_path)
        if packet.get("schema") != "chip-supergoal.reviewed-rail-packet.v1":
            raise ApprovalDenied("reviewed rail packet schema mismatch")
        if approval.get("schema") != "chip-supergoal.natural-approval-receipt.v1":
            raise ApprovalDenied("natural approval receipt schema mismatch")
        if approval.get("state") != "consumed" or approval.get("raw_text_persisted") is not False:
            raise ApprovalDenied("natural approval is not safely consumed")
        context = approval.get("context")
        if not isinstance(context, dict) or context.get("packet_sha256") != packet_sha:
            raise ApprovalDenied("natural approval is not bound to this exact packet")
        root = Path(str(packet.get("server_doctor_root") or ""))
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ApprovalDenied("server-doctor root is unsafe")
        helpers = packet.get("helpers")
        if not isinstance(helpers, dict) or set(helpers) != set(cls._ALLOWED):
            raise ApprovalDenied("packet helper inventory must be exact")
        for name, relative in cls._ALLOWED.items():
            spec = helpers.get(name)
            if not isinstance(spec, dict) or spec.get("path") != relative:
                raise ApprovalDenied(f"helper path is not allowlisted: {name}")
            if not isinstance(spec.get("argv"), list) or not all(
                isinstance(item, str) and "\x00" not in item for item in spec["argv"]
            ):
                raise ApprovalDenied(f"helper argv is malformed: {name}")
            helper = root / relative
            if helper.is_symlink():
                raise ApprovalDenied(f"helper must not be a symlink: {name}")
            try:
                resolved = helper.resolve(strict=True)
            except FileNotFoundError as exc:
                raise ApprovalDenied(f"helper is missing: {name}") from exc
            if not resolved.is_relative_to(root.resolve(strict=True)):
                raise ApprovalDenied(f"helper escapes server-doctor root: {name}")
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual != spec.get("sha256"):
                raise ApprovalDenied(f"helper hash mismatch: {name}")
        return cls(packet_path=packet_file, packet=packet)

    def run_step(self, name: str, *, runner=subprocess.run):
        if name not in self._ALLOWED:
            raise ApprovalDenied("unlisted reviewed rail step")
        spec = self.packet["helpers"][name]
        helper = (self.server_doctor_root / self._ALLOWED[name]).resolve(strict=True)
        actual = hashlib.sha256(helper.read_bytes()).hexdigest()
        if actual != spec["sha256"]:
            raise ApprovalDenied(f"helper changed after packet review: {name}")
        return runner(
            [sys.executable, str(helper), *spec["argv"]],
            cwd=str(self.server_doctor_root),
            text=True,
            capture_output=True,
            check=False,
        )


def verify_installed_generation(candidate: dict[str, Any]) -> str:
    generation = candidate.get("chip_supergoal")
    if not isinstance(generation, dict):
        raise ApprovalDenied("candidate lacks chip-supergoal generation")
    root_value = generation.get("installed_root")
    expected_files = generation.get("generation_files")
    expected_digest = generation.get("installed_generation_sha256")
    if not isinstance(root_value, str) or not isinstance(expected_files, dict) or not isinstance(expected_digest, str):
        raise ApprovalDenied("candidate generation binding is incomplete")
    root = Path(root_value)
    if not root.is_absolute():
        raise ApprovalDenied("installed generation root must be absolute")
    try:
        if root.resolve(strict=True) != root:
            raise ApprovalDenied("installed generation path must not traverse symlinks")
        root_lstat = root.lstat()
    except OSError as exc:
        raise ApprovalDenied("installed generation is unavailable") from exc
    if stat.S_ISLNK(root_lstat.st_mode) or not stat.S_ISDIR(root_lstat.st_mode):
        raise ApprovalDenied("installed generation root must be a real directory")
    if root_lstat.st_uid != os.getuid() or root_lstat.st_mode & 0o222:
        raise ApprovalDenied("installed generation root must be owner-owned and read-only")
    actual_files: dict[str, str] = {}
    for relative, expected_hash in expected_files.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise ApprovalDenied("generation manifest entry is malformed")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or not relative:
            raise ApprovalDenied("generation manifest path escapes root")
        path = root / rel
        try:
            file_lstat = path.lstat()
        except OSError as exc:
            raise ApprovalDenied(f"installed generation file missing: {relative}") from exc
        if stat.S_ISLNK(file_lstat.st_mode) or not stat.S_ISREG(file_lstat.st_mode):
            raise ApprovalDenied(f"installed generation file is unsafe: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_hash:
            raise ApprovalDenied(f"installed generation hash mismatch: {relative}")
        actual_files[relative] = actual
    extra_python = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.relative_to(root).as_posix() not in expected_files
    }
    if extra_python:
        raise ApprovalDenied("installed generation has unreviewed Python files")
    actual_digest = hashlib.sha256(
        json.dumps(actual_files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual_digest != expected_digest:
        raise ApprovalDenied("installed generation digest mismatch")
    return actual_digest


def _load_regular_json(path: Path) -> dict[str, Any]:
    return ApprovalStore._read_regular(path)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    if proc.returncode != 0:
        raise ApprovalDenied(f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _remote_head(root: Path, remote: str, branch: str) -> str:
    proc = subprocess.run(
        ["git", "ls-remote", "--exit-code", remote, f"refs/heads/{branch}"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    if proc.returncode not in (0, 2):
        raise ApprovalDenied(f"remote readback from {remote} failed")
    if proc.returncode == 2 or not proc.stdout.strip():
        return ""
    return proc.stdout.split()[0]


def _push_exact(
    root: Path,
    remote: str,
    branch: str,
    sha: str,
    *,
    expected_remote_sha: str,
) -> None:
    if expected_remote_sha and not re.fullmatch(r"[0-9a-f]{40}", expected_remote_sha):
        raise ApprovalDenied("expected remote lease is malformed")
    lease = f"--force-with-lease=refs/heads/{branch}:{expected_remote_sha}"
    proc = subprocess.run(
        ["git", "push", lease, remote, f"{sha}:refs/heads/{branch}"], cwd=root, text=True,
        capture_output=True, check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    if proc.returncode != 0:
        raise ApprovalDenied(f"exact push to {remote} failed")
    if _remote_head(root, remote, branch) != sha:
        raise ApprovalDenied(f"exact push to {remote} failed readback")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    if path.parent.is_symlink():
        raise ApprovalDenied("receipt directory must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    ApprovalStore._require_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ApprovalDenied(f"refusing to overwrite receipt: {path}") from exc
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    ApprovalStore._fsync_directory(path.parent)


def build_rollout_packet(candidate_path: Path, server_doctor_root: Path) -> dict[str, Any]:
    candidate = _load_regular_json(candidate_path)
    generation_digest = verify_installed_generation(candidate)
    if _git(server_doctor_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ApprovalDenied("server-doctor candidate must be clean")
    server_head = _git(server_doctor_root, "rev-parse", "HEAD^{commit}")
    server_tree = _git(server_doctor_root, "rev-parse", "HEAD^{tree}")
    expected_server = candidate.get("server_doctor")
    if not isinstance(expected_server, dict) or (server_head, server_tree) != (
        expected_server.get("sha"), expected_server.get("tree")
    ):
        raise ApprovalDenied("server-doctor candidate identity mismatch")
    helper_specs: dict[str, dict[str, Any]] = {}
    helpers = candidate.get("helpers")
    if not isinstance(helpers, dict):
        raise ApprovalDenied("candidate helper binding is missing")
    for name, relative in PinnedHelperRail._ALLOWED.items():
        helper = server_doctor_root / relative
        expected = helpers.get(name)
        if not isinstance(expected, dict) or expected.get("path") != str(helper) or expected.get("sha256") != _file_hash(helper):
            raise ApprovalDenied(f"candidate helper binding mismatch: {name}")
        helper_specs[name] = {"path": relative, "sha256": expected["sha256"], "argv": []}
    hermes = candidate.get("hermes")
    if not isinstance(hermes, dict):
        raise ApprovalDenied("Hermes candidate binding is missing")
    helper_specs["registry_guard"]["argv"] = [
        "--hermes-root", str(hermes["root"]), "--server-doctor-root", str(server_doctor_root),
        "--candidate-ref", str(hermes["sha"]), "--json",
    ]
    helper_specs["private_update"]["argv"] = [
        "--mode", "apply", "--systemd-run", "--live-root", "/opt/hermes-agent",
        "--server-doctor-root", str(server_doctor_root), "--restart", "opt-units",
        "--restart-unit", "hermes-gateway.service", "--json",
    ]
    live_root = Path("/opt/hermes-agent")
    live_status = _git(live_root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    server_remote_head = _remote_head(server_doctor_root, "origin", "main")
    hermes_remote_head = _remote_head(Path(hermes["root"]), "private", "main")
    packet = {
        "schema": "chip-supergoal.reviewed-rail-packet.v1",
        "created_at": int(time.time()),
        "read_only_construction": True,
        "candidate_path": str(candidate_path.resolve()),
        "candidate_sha256": _file_hash(candidate_path),
        "candidate_identity": {
            "goal_id": candidate.get("goal_id"),
            "package_id": candidate.get("package_id"),
            "hermes_sha": hermes.get("sha"),
            "hermes_tree": hermes.get("tree"),
            "manifest_sha256": candidate.get("manifest_sha256"),
            "chip_supergoal_sha": candidate.get("chip_supergoal", {}).get("sha"),
            "installed_generation_sha256": generation_digest,
        },
        "server_doctor_root": str(server_doctor_root.resolve()),
        "server_doctor": {
            "sha": server_head,
            "tree": server_tree,
            "remote_main_at_packet": server_remote_head,
            "prepublished_metadata": server_remote_head == server_head,
        },
        "hermes_private_main_at_packet": hermes_remote_head,
        "helpers": helper_specs,
        "live_prestate": {
            "root": str(live_root),
            "head": _git(live_root, "rev-parse", "HEAD^{commit}"),
            "tree": _git(live_root, "rev-parse", "HEAD^{tree}"),
            "status": live_status,
        },
        "approval_required_before_effects": True,
        "live_blocked_by_unrelated_overlay": bool(live_status),
        "normal_restart_budget": 1,
        "emergency_rollback_restart_budget": 1,
    }
    return packet


def _expected_approval_context(candidate: dict[str, Any], packet_path: Path) -> dict[str, str]:
    hermes = candidate["hermes"]
    chip = candidate["chip_supergoal"]
    return {
        "goal_id": str(candidate["goal_id"]),
        "package_id": str(candidate["package_id"]),
        "action": "private-rollout",
        "target": "/opt/hermes-agent",
        "candidate_sha": str(hermes["sha"]),
        "tree_sha": str(hermes["tree"]),
        "manifest_sha256": str(candidate["manifest_sha256"]),
        "packet_sha256": _file_hash(packet_path),
        "installed_generation_sha256": str(chip["installed_generation_sha256"]),
        "reviewed_generation": str(chip["sha"]),
    }


def consume_approval_bundle(
    candidate_path: Path,
    packet_path: Path,
    output: Path,
    *,
    origin: str,
) -> dict[str, Any]:
    candidate = _load_regular_json(candidate_path)
    packet = _load_regular_json(packet_path)
    if packet.get("live_blocked_by_unrelated_overlay"):
        raise ArchitectureBlocker("live checkout has a separately owned overlay; rebuild packet after handoff")
    verify_installed_generation(candidate)
    if packet.get("candidate_sha256") != _file_hash(candidate_path):
        raise ApprovalDenied("packet is not bound to the candidate")
    bundle_value = os.environ.get("CHIP_SUPERGOAL_APPROVAL_EVENT_JSON")
    if not bundle_value:
        raise ArchitectureBlocker("canonical Telegram approval event metadata is unavailable")
    bundle_path = Path(bundle_value)
    bundle = _load_regular_json(bundle_path)
    try:
        card = bundle.get("card")
        event = bundle.get("event")
        if not isinstance(card, dict) or not isinstance(event, dict):
            raise ArchitectureBlocker("canonical Telegram approval bundle is incomplete")
        missing_card = [field for field in (*CARD_FIELDS, "nonce", "issued_at", "expires_at") if card.get(field) is None]
        missing_event = [field for field in EVENT_FIELDS if event.get(field) is None]
        if missing_card or missing_event:
            raise ArchitectureBlocker("canonical Telegram approval bundle metadata is incomplete")
        expected = _expected_approval_context(candidate, packet_path)
        for field, value in expected.items():
            if card.get(field) != value or event.get(field) != value:
                raise ApprovalDenied(f"approval bundle candidate mismatch: {field}")
        try:
            platform, chat_id, thread_id = origin.split(":", 2)
        except ValueError as exc:
            raise ArchitectureBlocker("approval origin is not canonical") from exc
        if platform != "telegram" or card.get("chat_id") != chat_id or card.get("thread_id") != thread_id:
            raise ApprovalDenied("approval origin mismatch")
        ledger = output.parent / "approval-ledger"
        store = ApprovalStore(ledger)
        store.issue(
            context={field: card[field] for field in CARD_FIELDS},
            nonce=str(card["nonce"]),
            issued_at=int(card["issued_at"]),
            expires_at=int(card["expires_at"]),
        )
        receipt = store.consume(event)
    finally:
        try:
            bundle_path.unlink()
            ApprovalStore._fsync_directory(bundle_path.parent)
        except OSError as exc:
            raise ArchitectureBlocker("canonical approval event bundle could not be removed") from exc
    _write_output(output, receipt)
    return receipt


def _verify_approval_binding(candidate_path: Path, packet_path: Path, approval_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = _load_regular_json(candidate_path)
    packet = _load_regular_json(packet_path)
    approval = _load_regular_json(approval_path)
    if approval.get("state") != "consumed" or approval.get("raw_text_persisted") is not False:
        raise ApprovalDenied("approval is not a consumed no-raw-text receipt")
    expected = _expected_approval_context(candidate, packet_path)
    context = approval.get("context")
    if not isinstance(context, dict) or any(context.get(field) != value for field, value in expected.items()):
        raise ApprovalDenied("approval does not bind exact candidate and packet")
    ledger_receipt = approval_path.parent / "approval-ledger" / "receipts" / f"{approval.get('nonce')}.json"
    if _load_regular_json(ledger_receipt) != approval:
        raise ApprovalDenied("approval output does not match atomic ledger receipt")
    verify_installed_generation(candidate)
    return candidate, packet, approval


def apply_reviewed_rollout(candidate_path: Path, packet_path: Path, approval_path: Path, output: Path) -> dict[str, Any]:
    candidate, packet, approval = _verify_approval_binding(candidate_path, packet_path, approval_path)
    if packet.get("live_blocked_by_unrelated_overlay"):
        raise ArchitectureBlocker("rollout packet is blocked by a separately owned live overlay")
    ledger = ApprovalStore(approval_path.parent / "approval-ledger")
    effect_claim = ledger.claim_effect(approval)
    live_root = Path(packet["live_prestate"]["root"])
    if _git(live_root, "status", "--porcelain=v1", "--untracked-files=all").splitlines() != packet["live_prestate"]["status"]:
        raise ApprovalDenied("live prestate changed after approval")
    server_root = Path(packet["server_doctor_root"])
    server_head = packet["server_doctor"]["sha"]
    server_remote = _remote_head(server_root, "origin", "main")
    if packet["server_doctor"].get("prepublished_metadata"):
        if server_remote != server_head:
            raise ApprovalDenied("prepublished server-doctor metadata drifted")
        server_publication = "prepublished_metadata_verified"
    else:
        if server_remote != packet["server_doctor"].get("remote_main_at_packet"):
            raise ApprovalDenied("server-doctor remote drifted after approval")
        _push_exact(
            server_root,
            "origin",
            "main",
            server_head,
            expected_remote_sha=str(packet["server_doctor"].get("remote_main_at_packet") or ""),
        )
        server_publication = "published_after_approval"
    hermes = candidate["hermes"]
    rail = PinnedHelperRail.from_files(packet_path, approval_path)
    guard = rail.run_step("registry_guard")
    if guard.returncode != 0:
        raise ApprovalDenied("authoritative registry guard denied candidate")
    hermes_root = Path(hermes["root"])
    if _remote_head(hermes_root, "private", "main") != packet.get("hermes_private_main_at_packet"):
        raise ApprovalDenied("private remote drifted after approval")
    _push_exact(
        hermes_root,
        "private",
        "main",
        hermes["sha"],
        expected_remote_sha=str(packet.get("hermes_private_main_at_packet") or ""),
    )
    update = rail.run_step("private_update")
    if update.returncode != 0:
        raise ApprovalDenied("authoritative private update helper failed")
    result = {
        "schema": "chip-supergoal.reviewed-rollout-result.v1",
        "ok": True,
        "candidate_sha256": _file_hash(candidate_path),
        "packet_sha256": _file_hash(packet_path),
        "approval_nonce": approval["nonce"],
        "effect_claim_sha256": _context_fingerprint(
            {key: str(value) for key, value in effect_claim.items()}
        ),
        "server_doctor_published": True,
        "server_doctor_publication": server_publication,
        "registry_guard_passed": True,
        "private_ref_published": True,
        "private_update_scheduled": True,
        "normal_restart_budget": 1,
        "emergency_rollback_restart_budget": 1,
    }
    _write_output(output, result)
    return result


def audit_reviewed_rollout(candidate_path: Path, packet_path: Path, approval_path: Path, output: Path) -> dict[str, Any]:
    candidate, packet, approval = _verify_approval_binding(candidate_path, packet_path, approval_path)
    rollout = _load_regular_json(output.parent / "rollout-result.json")
    telegram = _load_regular_json(output.parent / "telegram-e2e.json")
    required_rollout = (
        "ok", "server_doctor_published", "registry_guard_passed",
        "private_ref_published", "private_update_scheduled",
    )
    required_telegram = (
        "ok", "live_readback", "backup_present", "restart_count_one",
        "telegram_e2e", "checkpoint_recovery", "context_lean_invariants", "rollback_ready",
    )
    if any(rollout.get(field) is not True for field in required_rollout):
        raise ApprovalDenied("rollout result is incomplete")
    if any(telegram.get(field) is not True for field in required_telegram):
        raise ApprovalDenied("Telegram/live audit result is incomplete")
    audit = {
        "schema": "chip-supergoal.reviewed-rollout-audit.v1",
        "ok": True,
        "candidate_sha256": _file_hash(candidate_path),
        "packet_sha256": _file_hash(packet_path),
        "approval_nonce": approval["nonce"],
        "installed_generation_sha256": verify_installed_generation(candidate),
        "rollout_result_sha256": _file_hash(output.parent / "rollout-result.json"),
        "telegram_e2e_sha256": _file_hash(output.parent / "telegram-e2e.json"),
    }
    _write_output(output, audit)
    return audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exact reviewed SuperGoal production rail")
    sub = parser.add_subparsers(dest="command", required=True)
    packet = sub.add_parser("packet")
    packet.add_argument("--candidate", required=True)
    packet.add_argument("--server-doctor", required=True)
    packet.add_argument("--output", required=True)
    for flag in ("require-clean", "require-installed-generation-hash", "backup", "one-rollout-restart", "emergency-rollback-restart-max-one"):
        packet.add_argument("--" + flag, action="store_true")
    packet.add_argument("--registry-guard")
    packet.add_argument("--private-update")
    approve = sub.add_parser("approve")
    approve.add_argument("--candidate", required=True)
    approve.add_argument("--packet", required=True)
    approve.add_argument("--origin", required=True)
    approve.add_argument("--owner", required=True)
    approve.add_argument("--output", required=True)
    for flag in ("require-installed-generation-hash", "direct-reply-only", "require-atomic-consume", "require-expiry", "require-revocation-check", "require-replay-denial"):
        approve.add_argument("--" + flag, action="store_true")
    apply = sub.add_parser("apply")
    apply.add_argument("--candidate", required=True)
    apply.add_argument("--packet", required=True)
    apply.add_argument("--approval", required=True)
    apply.add_argument("--output", default="rollout-result.json")
    for flag in ("require-installed-generation-hash", "publish-server-doctor-first", "run-registry-guard", "publish-private-after-guard", "invoke-private-update", "single-command-backup-readback-rollback", "one-controlled-rollout-restart", "live"):
        apply.add_argument("--" + flag, action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--candidate", required=True)
    audit.add_argument("--packet", required=True)
    audit.add_argument("--approval", required=True)
    audit.add_argument("--output", required=True)
    for flag in ("require-installed-generation-hash", "require-consumed-approval", "require-registry-guard", "require-private-ref-readback", "require-live-readback", "require-backup", "require-restart-count-one", "require-telegram-e2e", "require-checkpoint-recovery", "require-context-lean-invariants", "require-rollback-ready"):
        audit.add_argument("--" + flag, action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "packet":
            required = (
                "require_clean", "require_installed_generation_hash", "backup",
                "one_rollout_restart", "emergency_rollback_restart_max_one",
            )
            if not all(getattr(args, name) for name in required):
                raise ApprovalDenied("packet safety flags are incomplete")
            root = Path(args.server_doctor)
            if Path(args.registry_guard) != root / PinnedHelperRail._ALLOWED["registry_guard"]:
                raise ApprovalDenied("registry guard path is not authoritative")
            if Path(args.private_update) != root / PinnedHelperRail._ALLOWED["private_update"]:
                raise ApprovalDenied("private update path is not authoritative")
            payload = build_rollout_packet(Path(args.candidate), Path(args.server_doctor))
            _write_output(Path(args.output), payload)
        elif args.command == "approve":
            required = (
                "require_installed_generation_hash", "direct_reply_only", "require_atomic_consume",
                "require_expiry", "require_revocation_check", "require_replay_denial",
            )
            if not all(getattr(args, name) for name in required) or args.owner != args.origin:
                raise ApprovalDenied("approval safety flags or owner binding are incomplete")
            payload = consume_approval_bundle(Path(args.candidate), Path(args.packet), Path(args.output), origin=args.origin)
        elif args.command == "apply":
            required = (
                "require_installed_generation_hash", "publish_server_doctor_first", "run_registry_guard",
                "publish_private_after_guard", "invoke_private_update", "single_command_backup_readback_rollback",
                "one_controlled_rollout_restart", "live",
            )
            if not all(getattr(args, name) for name in required):
                raise ApprovalDenied("apply safety flags are incomplete")
            payload = apply_reviewed_rollout(Path(args.candidate), Path(args.packet), Path(args.approval), Path(args.output))
        else:
            required = (
                "require_installed_generation_hash", "require_consumed_approval", "require_registry_guard",
                "require_private_ref_readback", "require_live_readback", "require_backup",
                "require_restart_count_one", "require_telegram_e2e", "require_checkpoint_recovery",
                "require_context_lean_invariants", "require_rollback_ready",
            )
            if not all(getattr(args, name) for name in required):
                raise ApprovalDenied("audit safety flags are incomplete")
            payload = audit_reviewed_rollout(Path(args.candidate), Path(args.packet), Path(args.approval), Path(args.output))
    except (ApprovalDenied, ArchitectureBlocker, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "schema": payload.get("schema")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
