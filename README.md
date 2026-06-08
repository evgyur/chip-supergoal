# chip-supergoal

Public-safe Hermes skill for plan-only autonomous software delivery planning.

`chip-supergoal` writes:
- `.supergoal/THINKING.md`
- `.supergoal/RESEARCH.md` when current research is required
- `.supergoal/ROADMAP.md`
- `.supergoal/STATE.md`
- `.supergoal/phases/phase-N.md`
- `.supergoal/PROTOCOL.md`
- one CLI/client-safe `/goal` handoff

The skill is independent from `/rpd`: the RPD review pattern is embedded directly in `references/rpd-review-gates.md` and in the generated execution protocol.

## Install

This is a multi-file skill. Do **not** install from a raw `SKILL.md` URL; that would omit required `scripts/`, `templates/`, and `references/` assets.

Use a full-directory install method supported by your Hermes setup, or clone/copy this directory into `$HERMES_HOME/skills/chip-supergoal`:

```bash
git clone <public-repo-url> "$HERMES_HOME/skills/chip-supergoal"
```

Then reload skills if your runtime caches slash commands.

## Use

```text
/chip-supergoal Build or refactor X end-to-end
```

The skill does not execute the project work itself. It creates the plan and prints a `/goal` handoff. The future `/goal` session executes from the generated files.

## Verify

```bash
bash scripts/test.sh
```

## Privacy

This repository intentionally contains no operator secrets, chat IDs, local runtime state, credentials, or private infrastructure details.
