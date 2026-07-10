from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .model import Contract, canonical_json, contract_from_dict, to_plain


SUPPORTED_PROFILE_VERSION = "1.0"
MAX_PROFILE_DEPTH = 32
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
_ALLOWED_APPROVAL_KEYS = {"dangerous_actions"}
_ALLOWED_DELIVERY_KEYS = {"files", "review_pack_required", "target", "transport"}
_ALLOWED_PRIVACY_KEYS = {
    "private_operator_rules",
    "public_export_allowed",
    "strip_private_references",
}
_PRIVATE_DELIVERY_KEYS = {"files", "operator", "review-pack", "review_pack", "target"}


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedContract:
    source_sha256: str
    _canonical_contract_bytes: bytes = field(repr=False)
    _profile_bytes: bytes = field(repr=False)

    @property
    def canonical_bytes(self) -> bytes:
        return self._canonical_contract_bytes

    @property
    def contract_sha256(self) -> str:
        return hashlib.sha256(self._canonical_contract_bytes).hexdigest()

    @property
    def contract(self) -> Contract:
        return contract_from_dict(json.loads(self._canonical_contract_bytes))

    @property
    def profile(self) -> dict[str, Any]:
        loaded = json.loads(self._profile_bytes)
        if not isinstance(loaded, dict):
            raise ProfileError("resolved profile identity is malformed")
        return loaded

    def assert_identity(self) -> None:
        try:
            canonical = canonical_json(self.contract).encode("utf-8")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProfileError(f"resolved contract identity is malformed: {exc}") from exc
        if canonical != self._canonical_contract_bytes:
            raise ProfileError("resolved contract bytes are not canonical")


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


def _unknown_nested_keys(
    name: str, label: str, value: dict[str, Any], allowed: set[str]
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProfileError(
            f"unknown {label} field(s) in profile {name!r}: {', '.join(unknown)}"
        )


def _validate_profile_fields(name: str, profile: dict[str, Any]) -> None:
    if "public_clean" in profile and type(profile["public_clean"]) is not bool:
        raise ProfileError(f"profile {name!r} public_clean must be a boolean")
    if "operator" in profile and not isinstance(profile["operator"], str):
        raise ProfileError(f"profile {name!r} operator must be a string")

    if "privacy" in profile:
        privacy = profile["privacy"]
        if not isinstance(privacy, dict):
            raise ProfileError(f"profile {name!r} privacy must be an object")
        _unknown_nested_keys(name, "privacy", privacy, _ALLOWED_PRIVACY_KEYS)
        for key, value in privacy.items():
            if type(value) is not bool:
                raise ProfileError(
                    f"profile {name!r} privacy.{key} must be a boolean"
                )

    if "approvals" in profile:
        approvals = profile["approvals"]
        if not isinstance(approvals, dict):
            raise ProfileError(f"profile {name!r} approvals must be an object")
        _unknown_nested_keys(name, "approvals", approvals, _ALLOWED_APPROVAL_KEYS)
        if "dangerous_actions" in approvals:
            dangerous_actions = approvals["dangerous_actions"]
            if not isinstance(dangerous_actions, list):
                raise ProfileError(
                    f"profile {name!r} approvals.dangerous_actions must be a list"
                )
            if not all(isinstance(item, str) for item in dangerous_actions):
                raise ProfileError(
                    f"profile {name!r} approvals.dangerous_actions must contain only strings"
                )

    if "delivery" in profile:
        delivery = profile["delivery"]
        if not isinstance(delivery, dict):
            raise ProfileError(f"profile {name!r} delivery must be an object")
        _unknown_nested_keys(name, "delivery", delivery, _ALLOWED_DELIVERY_KEYS)
        if "review_pack_required" in delivery and type(
            delivery["review_pack_required"]
        ) is not bool:
            raise ProfileError(
                f"profile {name!r} delivery.review_pack_required must be a boolean"
            )
        for key in ("target", "transport"):
            if key in delivery and not isinstance(delivery[key], str):
                raise ProfileError(
                    f"profile {name!r} delivery.{key} must be a string"
                )
        if "files" in delivery:
            files = delivery["files"]
            if not isinstance(files, list):
                raise ProfileError(f"profile {name!r} delivery.files must be a list")
            if not all(isinstance(item, str) for item in files):
                raise ProfileError(
                    f"profile {name!r} delivery.files must contain only strings"
                )


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
    _validate_profile_fields(name, loaded)
    return loaded


def resolve_profile(name: str, profiles_dir: str | Path) -> dict[str, Any]:
    root = Path(profiles_dir)

    def resolve(current: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if current in stack:
            chain = " -> ".join((*stack, current))
            raise ProfileError(f"profile inheritance cycle: {chain}")
        if len(stack) >= MAX_PROFILE_DEPTH:
            raise ProfileError(
                f"maximum profile inheritance depth ({MAX_PROFILE_DEPTH}) exceeded"
            )
        profile = _load_profile(current, root)
        parent = profile.get("extends")
        if parent is None:
            return deepcopy(profile)
        inherited = resolve(parent, (*stack, current))
        return _deep_merge(inherited, profile)

    return resolve(name, ())


def _sanitize_public_delivery(delivery: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(delivery)
    for key in _PRIVATE_DELIVERY_KEYS:
        sanitized.pop(key, None)
    sanitized["transport"] = "none"
    sanitized["review_pack_required"] = False
    return sanitized


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(profile)
    sanitized.pop("operator", None)
    privacy = sanitized.get("privacy")
    if isinstance(privacy, dict):
        privacy["private_operator_rules"] = False
    delivery = sanitized.get("delivery", {})
    if isinstance(delivery, dict):
        sanitized["delivery"] = _sanitize_public_delivery(delivery)
    return sanitized


def _locator_pattern(locator: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(locator)}(?![A-Za-z0-9_])"
    )


def _contains_locator_token(value: str, locator: str) -> bool:
    if not locator:
        return False
    if value == locator:
        return True
    return _locator_pattern(locator).search(value) is not None


def _replace_locator_token(value: str, locator: str) -> str:
    if not _contains_locator_token(value, locator):
        return value
    return _locator_pattern(locator).sub("[redacted]", value)


def _ambiguous_redaction_reference(
    plain: dict[str, Any], locator: str
) -> str | None:
    for phase in plain.get("phases", []):
        phase_id = phase.get("id", "<unknown>")
        for command in phase.get("commands", []):
            value = command.get("command")
            if isinstance(value, str) and _contains_locator_token(value, locator):
                return f"phase {phase_id} command {command.get('id', '<unknown>')}"
        for deliverable in phase.get("deliverables", []):
            value = deliverable.get("path")
            if isinstance(value, str) and _contains_locator_token(value, locator):
                return (
                    f"phase {phase_id} deliverable "
                    f"{deliverable.get('id', '<unknown>')} path"
                )
    for approval in plain.get("approvals", []):
        value = approval.get("scope")
        if (
            approval.get("required", True)
            and isinstance(value, str)
            and _contains_locator_token(value, locator)
        ):
            return f"required approval {approval.get('id', '<unknown>')} scope"
    return None


def _pointer_child(path: str, token: object) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _replace_private_locators(
    value: Any, locators: tuple[str, ...], path: str = ""
) -> Any:
    if isinstance(value, str):
        redacted = value
        for locator in locators:
            redacted = _replace_locator_token(redacted, locator)
        return redacted
    if isinstance(value, list):
        return [
            _replace_private_locators(item, locators, _pointer_child(path, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        redacted_dict: dict[Any, Any] = {}
        for key, item in value.items():
            child_path = _pointer_child(path, key)
            if isinstance(key, str):
                for locator in locators:
                    if _contains_locator_token(key, locator):
                        raise ProfileError(
                            "public-clean redaction cannot rewrite dictionary key at "
                            f"{child_path}: it contains private locator token {locator!r}"
                        )
            redacted_dict[key] = _replace_private_locators(
                item, locators, child_path
            )
        return redacted_dict
    return value


def _redact_public_contract(
    plain: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    if not profile.get("public_clean"):
        return plain
    private_source_indexes: list[int] = []
    locators: set[str] = set()
    for index, source in enumerate(plain.get("source_set", [])):
        if source.get("sensitivity", "internal") == "public":
            continue
        private_source_indexes.append(index)
        locator = source.get("locator")
        if isinstance(locator, str) and locator:
            reference = _ambiguous_redaction_reference(plain, locator)
            if reference is not None:
                raise ProfileError(
                    "public-clean redaction is ambiguous: "
                    f"source {source.get('id', '<unknown>')} locator is embedded in {reference}"
                )
            locators.add(locator)

    ordered_locators = tuple(sorted(locators, key=lambda item: (-len(item), item)))
    redacted = _replace_private_locators(plain, ordered_locators)
    for index in private_source_indexes:
        redacted["source_set"][index]["locator"] = "[redacted]"
    return redacted


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
    if profile.get("public_clean"):
        plain["delivery"] = _sanitize_public_delivery(plain["delivery"])
    plain = _redact_public_contract(plain, profile)

    contract = contract_from_dict(plain)
    emitted = canonical_json(contract).encode("utf-8")
    profile_bytes = json.dumps(
        profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    resolved = ResolvedContract(
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        _canonical_contract_bytes=emitted,
        _profile_bytes=profile_bytes,
    )
    resolved.assert_identity()
    return resolved
