# Executable preflight: live input shape and process classification

Use this when a SuperGoal embeds mandatory commands that read mutable operator state such as scheduler registries, process tables, service metadata, or dirty-worktree boundaries.

## Seal-time rule

Run the **exact rendered command** against the current environment before sealing. Shell syntax, `--help`, and structural validation are insufficient. A command that fails on the real input shape is a package defect; amend the contract, recompile, and review the new immutable package. Never record a hand-written equivalent command as evidence for the declared command.

## Collection-shape tolerance

Operator registries may expose a top-level list, an object containing a list, or an ID-keyed mapping. Normalize once, then apply policy:

```python
payload = raw if isinstance(raw, list) else (raw.get("items") or [])
rows = list(payload.values()) if isinstance(payload, dict) else list(payload)
```

Validate required records explicitly after normalization. Do not infer absence from a parser exception.

## Process classes

Separate at least these classes:

1. **Source-checkout writer** — agent/editor/test harness with mutation authority over the target checkout. This can violate one-writer rules.
2. **Live runtime service** — process executing an installed immutable release such as an `/opt/.../current` target. Inventory it, but do not call it a checkout writer merely because its name contains `worker`.
3. **Read-only observer** — diagnostics/reporting process with no checkout or live-authority mutation.
4. **Self/ancestor chain** — the preflight shell, Python process, and tool host. Exclude by walking PPIDs; substring filtering alone produces false positives because the command text can contain its own markers.

Prefer cwd, executable path, cgroup/unit, and installed-release root over loose command-name substrings. Emit privacy-safe hashes, class labels, and required booleans rather than raw command lines.

## Approval boundary

A safe-lane source reconciliation must not stop or restart live services simply to make a preflight assertion green. If live runtime retirement is genuinely required, place it in the production-authorized phase with rollback and readback evidence. Keep source-writer exclusion and production-authority cutover as separate criteria.
