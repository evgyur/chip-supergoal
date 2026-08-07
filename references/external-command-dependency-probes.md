# External command dependency probes

Use this before sealing any SuperGoal command that reads files outside the compiled package, especially across Unix users/home directories or from mutable JSON preflight artifacts.

## Why

A command can be syntactically valid and still be non-executable because:

- its declared runtime user cannot traverse a parent directory or read the file;
- the real JSON shape differs from the embedded key path;
- its `cwd` is inaccessible before the command body starts;
- a future deliverable masks an already-testable external dependency;
- a one-off root wrapper, ACL, compatibility alias, or content shim makes one run pass but leaves the declared command non-replayable.

## Pre-seal probe

For every mandatory command:

1. Resolve the exact declared `cwd`, user, shell and interpreter.
2. Inventory every external path read before or during the verifier.
3. Under the declared user, test parent traversal, file readability and regular-file/no-symlink expectations.
4. Parse the real source bytes and evaluate every referenced key path exactly. Do not infer shape from a nearby report or planner object.
5. If the final verifier needs a future-created deliverable, replace only that deliverable with a schema-valid fixture while keeping all current external inputs real. Record the fixture boundary explicitly.
6. Run the exact safe command form from the declared context and capture exit/output.
7. Reject the package when execution requires a temporary privilege elevation, source rewrite, alias field, bind mount, or undeclared wrapper.

## Failure handling

Before `/goal` launch: fix the source/contract boundary, regenerate the command, compile fresh, rerun semantic review, and redeliver.

After `/goal` launch: do not mutate the bound source to manufacture replayability and do not record the shimmed run as replayable evidence. Transition the old runtime to an exact blocker/handoff, compile a fresh sibling package with new identity, and require a revised launch approval.

## Evidence receipt

Record at minimum:

- command ID and exact command hash;
- declared user/cwd/interpreter;
- external path list with access result;
- source-file SHA-256 and evaluated key paths;
- fixture boundary, if any;
- exact exit code and bounded output hash;
- verdict: `executable`, `future-deliverable-only`, or `package-red`.

Never include credentials, raw private messages, tokens, or unredacted config values in the receipt.
