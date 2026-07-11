# Skill package sync for chip-supergoal

Use when modifying the `chip-supergoal` skill package itself and publishing the change.

## Durable pattern

1. Treat the live installed skill under `~/.hermes/skills/chip-supergoal` as the working source, but publish from clean clones/worktrees of the backing repositories.
2. Copy only focused changed files into the repo checkout. Avoid whole-directory `rsync` unless you first prove the install tree and repo tree are meant to be identical.
3. Validate the package before commit:
   - install `requirements-test.txt`, then run `python scripts/test.py`
   - run `python scripts/sgctl.py validate-phase-markdown <fixture phase spec>`
   - focused contract assertions for any new marker/reference/template
   - `git diff --check`
   - lightweight secret scan on changed/untracked files
   - on Unix-only hosts, additionally run `bash scripts/test.sh`; never weaken or bypass the privacy gate
4. Sync both private distribution surfaces when applicable:
   - `evgyur/chip-supergoal`
   - `human20team/hermes-agent-powerpack` nested path `skills/chip-supergoal/...`
5. Verify push with remote HEAD equality (`git ls-remote ... refs/heads/main`) and, for new support files, verify GitHub contents path exists.

## Public repo guard

Do not push the installed/live package to a public repo unless it has been explicitly sanitized for public distribution. The live package can contain operator-specific context, private chat/channel details, or internal Human20/Hermes operational notes. A focused private sync is not evidence that public distribution is safe.

## Submodule / nested-package pitfall

Powerpack may carry `skills/chip-supergoal` as a nested package/gitlink-style surface. Update the nested files directly in the powerpack checkout and commit from the powerpack root. Do not assume pushing `evgyur/chip-supergoal` alone updates the powerpack distribution.

## Reporting shape

Keep the final report short:

```text
➊ chip-supergoal
┈ commit: <sha> — <message>
┈ remote main verified

➋ hermes-agent-powerpack
┈ commit: <sha> — <message>
┈ nested path verified

➌ checks
┈ <focused checks>
┈ public repo: not pushed unless sanitized
```
