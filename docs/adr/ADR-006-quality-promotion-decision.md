# ADR-006 — quality promotion decision

## Decision

`no-go`. No candidate is promoted and the pinned P02 baseline remains authoritative.

## Immutable evidence

- Promotion study SHA-256: `345f8f1c8cd78e77fad34c30b8ea6864cffae246f6e879aaebbe61fd2f38e200`
- Live-veto SHA-256: `030a1bd8460ab76afd533abfa115a8a50357dce36c95d98bc84f14855df8905a`
- Frozen promotion policy SHA-256: `7e844af095633d2201d314071a3dfd056c3830a3284eaa0c393f16d3cddc4a95`
- Promotion gates SHA-256: `16567cdc37334f2d24c166afe69318a99f54e792a2e37bafcae3d9d09877ed1f`
- Decision SHA-256: `02700bc347fa51f9c36d700b499d9d91c1b18b05bb7704e2e1adc688176a3c9d`

## Gate result

P08 selected `no_candidate`; P10 therefore remained `not_applicable`, did not unblind sealed tasks, and created no live exposure. Thresholds were not changed and no aggregate or secondary endpoint was used as rescue evidence.

## Consequence

Keep independently valuable deterministic checks and developer-only benchmark evidence. Keep `quality-canary` disabled, retain the exact P02 baseline authority, and perform no merge, release, or live installed-skill mutation.
