# Deterministic quality evaluation

The quality gate is an opt-in compiler profile named `quality-canary`. Legacy `base`, `public-clean`, and `chip-private` profiles keep their previous behavior and output when no quality overlay is present.

## Contract overlay

A canary contract declares `compatibility.quality_gate_v1` with exactly two records:

- `subject`: normalized intent, requirements, constraints, hash-bound sources, assumptions, alternatives, traceability, failure modes, permissions, overengineering checks, and budgets;
- `attestation`: quality/rubric versions, recomputable semantic lane, subject/report hashes, and semantic-judge state.

The closed schema is `spec/quality-gate.schema.json`. Quality source records must include a stable locator, freshness marker, SHA-256 digest, and `used_by` links to declared targets.

Phase commands remain backward compatible. Under `quality-canary`, each command additionally declares:

- `cwd`;
- `mutation_class`;
- `availability_dependencies`;
- `expected_output`;
- `risk_tags`;
- `risk_waiver` (nullable; an actual waiver requires an evidence source and reason).

Risky mutations require a matching declared risk or an evidence-backed waiver. Placeholder commands such as `echo ok` are rejected.

## Commands

```bash
python3 scripts/sgctl.py quality-lint CONTRACT.json --format json
python3 quality/run.py lint-fixtures
python3 -m unittest \
  tests.quality.test_quality_lint \
  tests.quality.test_quality_determinism \
  tests.security.test_quality_no_network \
  tests.mutation.test_quality_false_green_mutations
```

`quality-lint` writes canonical UTF-8 JSON with sorted keys and a trailing newline. Findings use cataloged `QG-*` diagnostic codes under `INV-QUALITY-001`. Quality-canary compilation emits the same deterministic report at `reports/plan-quality.json`; `MANIFEST.json` binds it against drift.

Before compiling a hand-authored canary contract, normalize it through `resolve_contract(...)` and call `seal_quality_attestation(...)`. The helper binds `plan_subject_sha256` to the normalized contract with only the attestation removed, then binds `report_sha256` to the deterministic report. Compilation rejects stale subject or report hashes.

## Determinism and security

The linter performs no network or model calls. It only reads the supplied contract and frozen local policy/rubric files. Identical inputs produce byte-identical reports. The compiler recomputes `b_only` versus `b_plus_c` and semantic-judge requirements from normalized risk, failure-mode, mutation, and profile inputs; a forged or stale attestation fails closed.

## Rollout and rollback

Enable only through `profiles/quality-canary.json`. Do not mutate the base profile. To roll back the canary, stop selecting `quality-canary`; no migration or legacy contract rewrite is required.
