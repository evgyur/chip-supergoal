# CHANGELOG

## 3.0.0-alpha.4 — Native Windows and B2 authority hardening

- Added one native Python aggregate runner and required Windows/Ubuntu CI parity.
- Pinned CPython 3.11.9/3.13.14 CI coverage through setup-python v6.
- Replaced path-based delivery handoff with reservation-owned, byte-stable transport and crash-resumable progress.
- Hardened package locking, atomic writes, state/audit/terminal authority, deterministic archives, and publication recovery across package relocation.
- Added canonical archive/result schemas, portable path checks, privacy gates, and adversarial crash/forgery regressions.
- Updated generated-package protocol and public documentation; older generated packages must be recompiled.

## 3.0.0-alpha.3 — Research provider gate

- Added executable `compatibility.research_gate` validation with Perplex-first policy for research-required plans.
- Compile now emits generated `RESEARCH.md` and machine-readable `reports/research.json` when research is required or declared.
- `validate-package` seals and drift-checks research artifacts alongside the generated package views.
- Added `sgctl research-gate` and regression tests for blocked research, non-Perplex fallback justification, and research artifact drift.

## 3.0.0-alpha.2 — Coffee-review hardening ZIP

- Made compiled packages byte-stable across output directories, including `LAUNCH_GOAL.md` and `MANIFEST.json`, by removing output-path-dependent launch rendering.
- Hardened compiler output replacement: existing targets must be sealed chip-supergoal packages, different goal IDs are refused, changed contracts must advance `contract_revision`, runtime/output artifacts are not overwritten, and source-container targets are blocked.
- Strengthened `validate-package` to verify generated Markdown views against canonical `CONTRACT.json`, enforce manifest file-set/hash/fingerprint integrity, and detect unsealed files or manual drift.
- Added regression tests for unsafe compile targets, full compile reproducibility, generated-view drift, and manifest file-set drift.

## 3.0.0-alpha.1 — Architect+ v3 workstream

- Added v3 contract model, semantic validators, deterministic compiler, state/event/evidence/audit primitives, secure delivery/archive handling, E2E simulator, reference catalog, profile split, and v2 migration adapter.
- Preserved the production executor boundary: standard Hermes `/goal` remains the only executor.
- Added CI split across unit, schema, semantic, rendering, E2E, security, migration, reference, and aggregate gates.
