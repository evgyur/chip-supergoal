# Reply-to-MD Goal launch pattern

Use this when Chip wants a SuperGoal plan to be launchable by replying to an assistant Markdown message.

## Durable lesson

Chip does not want a SuperGoal handoff that merely says “copy this `/goal ...` command” or asks whether to send it. He wants the assistant’s Markdown reply itself to be a launch manifest that can be replied to with `/goal` / GoalManager flow.

## Correct handoff shape

After writing `.supergoal/THINKING.md`, `.supergoal/ROADMAP.md`, `.supergoal/LAUNCH_GOAL.md`, phase specs, and package artifacts, the visible final message should include:

```text
Goal: Implement `.supergoal/ROADMAP.md` in `<workdir>` from phase 0 through final audit. Use `.supergoal/PROTOCOL.md` and `.supergoal/phases/phase-*.md`.
...
Completion requires successful python scripts/sgctl.py validate-terminal against reports/terminal-record.txt; the finalized record supplies AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE for host compatibility.
```

Do not wrap this in “if you want, send this”, and do not make Chip copy a command manually. Keep any status/attachments compact, then provide the raw `Goal:` manifest as the launchable Markdown body or attached `LAUNCH_GOAL.md`.

## If Chip replies “?” / “Жду supergoal” after `No active goal`

Treat it as a failed handoff UX, not as confusion from Chip.

1. Re-read the current `.supergoal/LAUNCH_GOAL.md` and run package-local `state-show` if needed.
2. Emit or continue the launch manifest/phase execution directly.
3. Do not ask for another confirmation unless the next step is money/DNS/secrets/grants/destructive prod/mass post.

## Pitfall

A fenced code block containing `/goal ...` is useful for humans, but it is not the preferred final handoff for Chip. The preferred object is a clean Markdown `Goal:` manifest that can itself become the replied-to goal content.
