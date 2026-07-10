from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .model import Contract, canonical_json, contract_from_dict, to_plain


SUPPORTED_PROFILE_VERSION = "1.0"
ALLOWED_PROFILE_KEYS = {
    "name",
    "extends",
    "profile_version",
    "approvals",
    "delivery",
    "privacy",
    "public_clean",
    "operator",
}
_PRIVATE_DELIVERY_KEYS = {"files", "target"}


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedContract:
    contract: Contract
    source_sha256: str
    contract_sha256: str
    profile: dict[str, Any]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _profile_path(name: str, profiles_dir: Path) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ProfileError(f"invalid profile name: {name!r}")
    return profiles_dir / f"{name}.json"


def _load_profile(name: str, profiles_dir: Path) -> dict[str, Any]:
    path = _profile_path(name, profiles_dir)
    if not path.is_file():
        raise ProfileError(f"profile {name!r} not found in {profiles_dir}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot load profile {name!r}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ProfileError(f"profile {name!r} must be a JSON object")

    unknown = sorted(set(loaded) - ALLOWED_PROFILE_KEYS)
    if unknown:
        raise ProfileError(
            f"unknown profile field(s) in {name!r}: {', '.join(unknown)}"
        )
    declared_name = loaded.get("name")
    if declared_name != name:
        raise ProfileError(
            f"profile name {declared_name!r} does not match requested profile {name!r}"
        )
    version = loaded.get("profile_version")
    if version != SUPPORTED_PROFILE_VERSION:
        raise ProfileError(
            f"unsupported profile_version {version!r} in {name!r}; "
            f"expected {SUPPORTED_PROFILE_VERSION!r}"
        )
    parent = loaded.get("extends")
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise ProfileError(f"profile {name!r} extends must be a nonempty profile name")
    return loaded


def resolve_profile(name: str, profiles_dir: str | Path) -> dict[str, Any]:
    root = Path(profiles_dir)

    def resolve(current: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if current in stack:
            chain = " -> ".join((*stack, current))
            raise ProfileError(f"profile inheritance cycle: {chain}")
        profile = _load_profile(current, root)
        parent = profile.get("extends")
        if parent is None:
            return deepcopy(profile)
        inherited = resolve(parent, (*stack, current))
        return _deep_merge(inherited, profile)

    return resolve(name, ())


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(profile)
    sanitized.pop("operator", None)
    privacy = sanitized.get("privacy")
    if isinstance(privacy, dict):
        privacy["private_operator_rules"] = False

    delivery = sanitized.get("delivery")
    if isinstance(delivery, dict):
        for key in _PRIVATE_DELIVERY_KEYS:
            delivery.pop(key, None)
        if delivery.get("transport") != "none":
            delivery.pop("transport", None)
        if delivery.get("review_pack_required") is not False:
            delivery.pop("review_pack_required", None)
    return sanitized


def _ambiguous_redaction_reference(
    plain: dict[str, Any], locator: str
) -> str | None:
    for phase in plain.get("phases", []):
        phase_id = phase.get("id", "<unknown>")
        for command in phase.get("commands", []):
            value = command.get("command")
            if isinstance(value, str) and locator in value:
                return f"phase {phase_id} command {command.get('id', '<unknown>')}"
        for deliverable in phase.get("deliverables", []):
            value = deliverable.get("path")
            if isinstance(value, str) and locator in value:
                return (
                    f"phase {phase_id} deliverable "
                    f"{deliverable.get('id', '<unknown>')} path"
                )
    for approval in plain.get("approvals", []):
        value = approval.get("scope")
        if approval.get("required", True) and isinstance(value, str) and locator in value:
            return f"required approval {approval.get('id', '<unknown>')} scope"
    return None


def _redact_public_contract(
    plain: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    if not profile.get("public_clean"):
        return plain
    for source in plain.get("source_set", []):
        if source.get("sensitivity", "internal") == "public":
            continue
        locator = source.get("locator")
        if isinstance(locator, str) and locator:
            reference = _ambiguous_redaction_reference(plain, locator)
            if reference is not None:
                raise ProfileError(
                    "public-clean redaction is ambiguous: "
                    f"source {source.get('id', '<unknown>')} locator is embedded in {reference}"
                )
        source["locator"] = "[redacted]"
    return plain


def resolve_contract(
    source: Contract, profiles_dir: str | Path, source_bytes: bytes
) -> ResolvedContract:
    profile = resolve_profile(source.profile, profiles_dir)
    if profile.get("public_clean"):
        profile = _public_profile(profile)

    plain = deepcopy(to_plain(source))
    profile_delivery = profile.get("delivery", {})
    if not isinstance(profile_delivery, dict):
        raise ProfileError(f"profile {source.profile!r} delivery must be an object")
    source_delivery = plain.get("delivery", {})
    if not isinstance(source_delivery, dict):
        raise ProfileError("contract delivery must be an object")
    plain["delivery"] = _deep_merge(profile_delivery, source_delivery)
    plain = _redact_public_contract(plain, profile)

    contract = contract_from_dict(plain)
    emitted = canonical_json(contract).encode("utf-8")
    return ResolvedContract(
        contract=contract,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        contract_sha256=hashlib.sha256(emitted).hexdigest(),
        profile=profile,
    )
