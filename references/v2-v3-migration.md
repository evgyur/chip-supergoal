# v2 → v3 migration

`python scripts/sgctl.py migrate-v2 <source> --out <dir>` reads a legacy Markdown package, writes a draft v3 `CONTRACT.json`, copies a read-only `v2-backup/`, and writes `migration-report.json`.

Rules:

- do not invent missing v2 semantics; unresolved fields fail with `migration_unresolved`;
- `STATE.md` fallback is read-only compatibility data;
- rollback is restoring the byte-for-byte `v2-backup/`;
- strict v3 validation is required before seal.
