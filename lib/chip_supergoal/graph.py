from __future__ import annotations

from .model import Contract


def phase_graph_errors(contract: Contract) -> list[str]:
    errors: list[str] = []
    phase_ids = [p.id for p in contract.phases]
    seen: set[str] = set()
    for pid in phase_ids:
        if pid in seen:
            errors.append(f"duplicate phase id: {pid}")
        seen.add(pid)
    valid = set(phase_ids)
    adjacency = {p.id: list(p.depends_on) for p in contract.phases}
    for p in contract.phases:
        for dep in p.depends_on:
            if dep not in valid:
                errors.append(f"{p.id} depends on missing phase {dep}")
            if dep == p.id:
                errors.append(f"{p.id} depends on itself")
    visiting: set[str] = set()
    visited: set[str] = set()
    def dfs(pid: str, stack: list[str]) -> None:
        if pid in visiting:
            errors.append("dependency cycle: " + " -> ".join(stack + [pid]))
            return
        if pid in visited or pid not in adjacency:
            return
        visiting.add(pid)
        for dep in adjacency[pid]:
            dfs(dep, stack + [pid])
        visiting.remove(pid)
        visited.add(pid)
    for pid in phase_ids:
        dfs(pid, [])
    return errors
