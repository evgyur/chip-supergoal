# ADR-005 — quality candidate selection

## Decision

`no_candidate` / `no-go`. No runtime quality candidate is promoted.

## Evidence

- Ablation report SHA-256: `099da7c928bcce568cf9da09a7c1dcaa5e5b4fd3747c23ecaac8ee2d38f5e29f`
- Promotion policy SHA-256: `440da57cc8006619ba17e6849e4b4224f671b73d56596647401bd716c2093e3a`
- Decision SHA-256: `5aa9c5f3e8d6be4901cd607620242d1f777172efb2ee986e16e971b3ca0145c6`
- Sealed holdout accessed: `false`

## Rationale

No variant has authoritative task-level observations, zero-P0/P1 proof, and attributable incremental gain. The P06 sandbox lanes remain `import_only` and judge calibration remains `non_authoritative`. Aggregate appearance cannot rescue missing authority.

## Consequence

The critic/repair layer is not retained in the runtime candidate. Later rollout phases must produce no-op/no-go receipts and cannot claim promotion or live exposure.
