# chip-supergoal

Public-safe Hermes skill for plan-only autonomous software delivery planning.

`chip-supergoal` writes:
- `.supergoal/ROADMAP.md`
- `.supergoal/STATE.md`
- `.supergoal/phases/phase-N.md`
- `.supergoal/PROTOCOL.md`
- one Telegram/CLI-safe `/goal` handoff

The skill is independent from `/rpd`: the RPD review pattern is embedded directly in `references/rpd-review-gates.md` and in the generated execution protocol.

## Install

```bash
hermes skills install https://raw.githubusercontent.com/evgyur/chip-supergoal/main/SKILL.md --name chip-supergoal
```

Or clone/copy this directory into `$HERMES_HOME/skills/chip-supergoal`.

## Use

```text
/chip-supergoal Build or refactor X end-to-end
```

The skill does not execute the project work itself. It creates the plan and prints a `/goal` handoff. The future `/goal` session executes from the generated files.

## Privacy

This repository intentionally contains no operator secrets, chat IDs, local runtime state, credentials, or private infrastructure details.
