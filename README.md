# chip-supergoal

Public-safe skill for plan-only autonomous software delivery planning.

## Modes

- **Hermes mode** is the original behavior: write `.supergoal/*`, then print a client-safe `/goal` handoff for a Hermes/Claude-style slash-command host.
- **Codex mode** writes the same `.supergoal/*` artifacts, then starts or hands off to Codex's built-in goal mechanism. The Codex execution protocol requires coding phases to run through `shaw`.

`chip-supergoal` writes:
- `.supergoal/THINKING.md`
- `.supergoal/RESEARCH.md` when current research is required
- `.supergoal/ROADMAP.md`
- `.supergoal/STATE.md`
- `.supergoal/phases/phase-N.md`
- `.supergoal/PROTOCOL.md`
- one mode-appropriate goal handoff

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

The skill does not execute the project work itself. It creates the plan and dispatches by mode: Hermes prints a `/goal` handoff; Codex uses the built-in goal path when explicitly authorized, with `shaw` governing coding work.

## Verify

```bash
bash scripts/test.sh
```

## Privacy

This repository intentionally contains no operator secrets, chat IDs, local runtime state, credentials, or private infrastructure details.
