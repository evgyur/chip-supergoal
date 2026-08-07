#!/usr/bin/env bash
# Build the complete manifest-exact SuperGoal package as a deterministic tar.gz.
set -euo pipefail
ROOT="${SUPERGOAL_ROOT:-$(pwd)/.supergoal}"
OUT="$ROOT/out"
mkdir -p "$OUT"
python3 - <<'PY' "$ROOT" "$OUT"
from __future__ import annotations
from pathlib import Path
import gzip
import hashlib
import io
import json
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
manifest_path = root / "MANIFEST.json"
contract_path = root / "CONTRACT.json"
if not manifest_path.is_file() or not contract_path.is_file():
    raise SystemExit("SGV-COMPLETE-PACKAGE-MISSING-SEAL: CONTRACT.json or MANIFEST.json missing")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
contract = json.loads(contract_path.read_text(encoding="utf-8"))
goal_id = contract["goal"]["id"]
records = manifest.get("artifacts")
mutable_records = manifest.get("mutable_paths", [])
if manifest.get("manifest_version") not in {"1.0", "1.1"} or not isinstance(records, list) or not isinstance(mutable_records, list):
    raise SystemExit("SGV-COMPLETE-PACKAGE-MANIFEST-SHAPE")

secret_patterns = [
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}"),
    re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

files: list[tuple[Path, str, bytes, int]] = []
seen: set[str] = set()
for record in records:
    rel = record.get("path")
    if not isinstance(rel, str) or rel.startswith("/") or ".." in Path(rel).parts or "\x00" in rel:
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-PATH: {rel!r}")
    low = rel.lower()
    if low in seen:
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-CASE-COLLISION: {rel}")
    seen.add(low)
    path = root / rel
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-MISSING: {rel}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or not path.resolve(strict=True).is_relative_to(root):
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-UNSAFE-FILE: {rel}")
    data = path.read_bytes()
    mode = stat.S_IMODE(st.st_mode)
    if sha(data) != record.get("sha256") or len(data) != record.get("bytes") or f"{mode:04o}" != record.get("mode"):
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-MANIFEST-DRIFT: {rel}")
    if any(pattern.search(data) for pattern in secret_patterns):
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-SECRET: {rel}")
    files.append((path, rel, data, mode))

# Mutable runtime files are intentionally not hash-bound in `artifacts`, but a
# portable strict package needs every required mutable path and every optional
# mutable path that currently exists.
for record in mutable_records:
    rel = record.get("path")
    required = record.get("required") is True
    if not isinstance(rel, str) or rel.startswith("/") or ".." in Path(rel).parts or "\x00" in rel:
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-MUTABLE-PATH: {rel!r}")
    low = rel.lower()
    if low in seen:
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-CASE-COLLISION: {rel}")
    path = root / rel
    if not path.exists():
        if required:
            raise SystemExit(f"SGV-COMPLETE-PACKAGE-MISSING-MUTABLE: {rel}")
        continue
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or not path.resolve(strict=True).is_relative_to(root):
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-UNSAFE-MUTABLE: {rel}")
    data = path.read_bytes()
    if any(pattern.search(data) for pattern in secret_patterns):
        raise SystemExit(f"SGV-COMPLETE-PACKAGE-SECRET: {rel}")
    seen.add(low)
    files.append((path, rel, data, stat.S_IMODE(st.st_mode)))

manifest_data = manifest_path.read_bytes()
if any(pattern.search(manifest_data) for pattern in secret_patterns):
    raise SystemExit("SGV-COMPLETE-PACKAGE-SECRET: MANIFEST.json")
files.append((manifest_path, "MANIFEST.json", manifest_data, stat.S_IMODE(manifest_path.stat().st_mode)))

expected = {rel for _, rel, _, _ in files}
actual = {
    str(path.relative_to(root))
    for path in root.rglob("*")
    if path.is_file()
    and not path.is_symlink()
    and not str(path.relative_to(root)).startswith("out/")
    and "__pycache__" not in path.parts
    and path.suffix != ".pyc"
}
if actual != expected:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    raise SystemExit(f"SGV-COMPLETE-PACKAGE-SOURCE-FILESET-DRIFT: missing={missing} extra={extra}")

files.sort(key=lambda item: item[1])

archive = out / f"{goal_id}.complete-supergoal.tar.gz"
receipt = out / f"{goal_id}.complete-supergoal-package-receipt.json"
with archive.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for _, rel, data, mode in files:
                info = tarfile.TarInfo(rel)
                info.size = len(data)
                info.mode = mode
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))

verify_root = Path(tempfile.mkdtemp(prefix=f"{goal_id}-verify-"))
try:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != {rel for _, rel, _, _ in files}:
            raise SystemExit("SGV-COMPLETE-PACKAGE-FILESET-DRIFT")
        tar.extractall(verify_root, filter="data")
    sgctl = verify_root / "scripts" / "sgctl.py"
    checks = [
        [sys.executable, str(sgctl), "validate-package", str(verify_root), "--strict", "--format", "json"],
        [sys.executable, str(sgctl), "validate-loop-design", str(verify_root / "LOOP_DESIGN.md"), "--instantiated", "--format", "json"],
    ]
    checks.extend(
        [sys.executable, str(sgctl), "validate-phase-markdown", str(phase), "--format", "json"]
        for phase in sorted((verify_root / "phases").glob("phase-*.md"))
    )
    for command in checks:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            raise SystemExit("SGV-COMPLETE-PACKAGE-EXTRACTED-VALIDATION")
finally:
    shutil.rmtree(verify_root, ignore_errors=True)

result = {
    "schema": "chip-supergoal.complete-package.v1",
    "ok": True,
    "goal_id": goal_id,
    "archive": str(archive),
    "sha256": sha(archive.read_bytes()),
    "entry_count": len(files),
    "fileset": "MANIFEST.json.artifacts + present MANIFEST.json.mutable_paths + MANIFEST.json",
    "modes_preserved": True,
    "secret_scan": "passed",
    "extracted_strict_validation": "passed",
}
receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(archive)
print(result["sha256"])
print(receipt)
PY
