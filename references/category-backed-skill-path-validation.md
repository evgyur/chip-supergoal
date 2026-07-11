# Category-backed skill path validation during SuperGoal execution

Use when a SuperGoal phase edits or validates a Hermes skill and the phase spec hard-codes a path such as `~/.hermes/skills/<name>`.

## Problem

Hermes user-local skills can be category-backed, for example:

```text
~/.hermes/skills/chip/chip-legal-acc-ops/
```

A phase file may become stale and point to:

```text
~/.hermes/skills/chip-legal-acc-ops/
```

If the executor blindly runs the stale mandatory command, validation falsely fails or the agent may create/update a duplicate skill.

## Rule

Before patching a skill path or declaring a missing skill, resolve the live path from `skill_view(name)` or by checking both canonical candidates:

```python
from pathlib import Path
candidates = [
    Path.home() / ".hermes/skills/<skill-name>",
    Path.home() / ".hermes/skills/<category>/<skill-name>",
]
base = next((p for p in candidates if (p / "SKILL.md").exists()), candidates[-1])
print(base)
```

Then patch the phase's mandatory command to use the resolved category-backed path and document the correction in the phase report.

## Acceptance evidence

A good phase report states:

```text
phase spec patched to resolve actual category-backed skill path
skill_dir: <skills-dir>/<category>/<skill-name>
no duplicate skill created
```

## Related cleanup

If script validation uses `py_compile`, remove generated caches before closing
the phase. This is a Unix-only shell example; native Windows may run the same
Python command and remove `__pycache__` with PowerShell or Python:

```bash
python -m py_compile "$skill_dir/scripts/name.py"
rm -rf "$skill_dir/scripts/__pycache__"
```

`__pycache__` is build residue, not a skill artifact.
