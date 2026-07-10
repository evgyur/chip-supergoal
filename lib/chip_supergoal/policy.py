from __future__ import annotations

import json
from pathlib import Path
from .model import Contract


def load_risk_policy(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _nonempty_declaration(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return bool(value)


def risk_policy_errors(contract: Contract, policy: dict) -> list[str]:
    errors: list[str] = []
    tags = policy.get("risk_tags", {})
    known = set(tags)
    declared: set[str] = set()
    for risk in contract.risks:
        if risk.tag not in known:
            errors.append(f"contract risk {risk.id} uses unknown risk tag {risk.tag}")
        else:
            declared.add(risk.tag)

    has_rollback = _nonempty_declaration(contract.architecture.data.get("rollback")) or _nonempty_declaration(
        contract.loop.data.get("rollback")
    )
    for phase in contract.phases:
        for tag in dict.fromkeys(phase.risk_tags):
            if tag not in known:
                errors.append(f"{phase.id} uses unknown risk tag {tag}")
                continue
            if tag not in declared:
                errors.append(f"{phase.id} risk {tag} is not declared in contract risks")

            rule = tags[tag]
            required = set(rule.get("required_rpd_focus", []))
            if required and not phase.rpd.required:
                errors.append(f"{phase.id} risk {tag} requires RPD")
            missing = sorted(required - set(phase.rpd.focus))
            if missing:
                errors.append(f"{phase.id} risk {tag} missing RPD focus: {', '.join(missing)}")

            approval_class = rule.get("approval_class", "none")
            if approval_class != "none":
                allowed_scopes = {phase.id, tag, "all"}
                approved = any(
                    approval.required
                    and approval.class_name == approval_class
                    and approval.scope in allowed_scopes
                    for approval in contract.approvals
                )
                if not approved:
                    errors.append(
                        f"{phase.id} risk {tag} requires required {approval_class} approval "
                        f"scoped to {phase.id}, {tag}, or all"
                    )

            if rule.get("rollback_required") and not has_rollback:
                errors.append(
                    f"{phase.id} risk {tag} requires a nonempty architecture.rollback "
                    "or loop.rollback declaration"
                )
    return errors


def mandatory_evidence_requirements(contract: Contract, policy: dict) -> dict[str, list[str]]:
    tags = policy.get("risk_tags", {})
    requirements: dict[str, list[str]] = {}
    for phase in sorted(contract.phases, key=lambda item: (item.ordinal, item.id)):
        labels: set[str] = set()
        for tag in set(phase.risk_tags):
            rule = tags.get(tag)
            if not isinstance(rule, dict):
                continue
            labels.update(
                label
                for label in rule.get("mandatory_evidence", [])
                if isinstance(label, str)
            )
        requirements[phase.id] = sorted(labels)
    return requirements
