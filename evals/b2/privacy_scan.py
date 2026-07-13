from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


SECRET_PATTERNS = (
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("telegram_bot_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    ("generic_secret", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{24,}")),
)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def scan_files(root: Path, paths: Iterable[Path]) -> list[str]:
    violations: list[str] = []
    for path in sorted({item.resolve() for item in paths}):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = _relative(path, root)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relative}:{line_number}:{name}")
    return sorted(set(violations))


def changed_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    fields = result.stdout.split(b"\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        decoded = field.decode("utf-8", errors="surrogateescape")
        status = decoded[:2]
        raw_path = decoded[3:]
        if status[0] in {"R", "C"}:
            if index >= len(fields):
                break
            raw_path = fields[index].decode("utf-8", errors="surrogateescape")
            index += 1
        candidate = root / raw_path
        if candidate.is_dir():
            paths.extend(path for path in candidate.rglob("*") if path.is_file())
        elif candidate.is_file():
            paths.append(candidate)
    return sorted(set(paths))


def main() -> int:
    parser = argparse.ArgumentParser(description="Redacting privacy scan for B2 evidence")
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.changed_only:
        paths = changed_paths(root)
    elif args.paths:
        paths = [root / item for item in args.paths]
    else:
        paths = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    violations = scan_files(root, paths)
    print(json.dumps({"ok": not violations, "violations": violations}, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
