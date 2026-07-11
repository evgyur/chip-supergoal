# Skill feature audit via user-story spreadsheet

Use when Chip asks to audit a skill end-to-end, enumerate every feature, create user stories, test each behavior, fix gaps, and retest.

## Canonical artifact

Keep one CSV under the canonical skill repo/worktree, normally:

```text
docs/<skill-name>-user-stories.csv
```

Recommended columns:

```csv
id,feature,source_files,user_story,expected_behaviour,status,evidence,errors,fix_notes,retest_status
```

Rules:

- derive stories from the actual loaded skill files and support files, not from memory;
- include root behavior, references, templates, scripts, delivery contracts, validation scripts, and documented edge-case incidents;
- each row must point to concrete source files;
- statuses should be boring and machine-readable: `not_tested`, `passed`, `failed`, `fixed_verified`.

## Test loop

Add a deterministic harness when the audit has more than a few rows:

```text
scripts/test-user-stories.py
```

The harness should:

1. read the CSV;
2. verify unique IDs and existing `source_files`;
3. run targeted assertions against the source files for each expected behavior;
4. write updated `status`, `evidence`, `errors`, and `retest_status` back into the CSV;
5. exit non-zero on any failed story.

Use static/source assertions for skill-library behavior. Avoid brittle casing/exact-copy checks unless the exact string is part of the contract.

## Fix loop

When a row fails:

1. decide whether the failure is a real skill gap or a brittle test;
2. patch the smallest canonical source: SKILL.md for new public invariants/dispatch, references for durable detail, templates/scripts for executable contracts;
3. sync the live loaded skill and canonical repo copy if they differ;
4. rerun `python scripts/test-user-stories.py` and `python scripts/test.py`; on Unix-only hosts also run `bash scripts/test.sh`;
5. verify `skill_view` loads the changed live file before declaring completion.

## Pitfalls

- `git status` in a repo-backed copy does not prove the active loaded skill changed; verify the live `skill_dir` too.
- A CSV is not evidence by itself. Every passed row needs a reproducible assertion, command output, or direct source pointer.
- Do not hide session-specific audit results in SKILL.md. Keep the reusable method in this reference and the per-skill spreadsheet in `docs/`.
