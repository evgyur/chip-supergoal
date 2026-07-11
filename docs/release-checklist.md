# Release checklist — chip-supergoal Architect+ v3

## Mandatory local gates

- [x] CPython 3.11.9 or newer; CI matrix pins 3.11.9 and 3.13.14
- [x] pinned test dependency: `python -m pip install --disable-pip-version-check -r requirements-test.txt`
- [x] native Windows: `python scripts/test.py`
- [x] Ubuntu: `python scripts/test.py`
- [x] Ubuntu shell quality (Unix-only): `bash scripts/test.sh --shell-only`
- [x] `python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict`
- [x] `python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../sg-build-a`
- [x] `python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../sg-build-b`
- [x] compare deterministic immutable outputs from both builds
- [x] archive the same unchanged package snapshot twice and compare exact ZIP bytes
- [x] verify secure archive tests and receipt tampering tests pass
- [x] verify reference catalog/generated index are consistent
- [x] verify v2 migration fixtures pass

## Release metadata

- [x] `VERSION` matches the top `CHANGELOG.md` heading
- [x] generated package manifest has stable fingerprint
- [x] CI uses least permissions (`contents: read`)
- [x] GitHub actions are pinned by full SHA
- [x] checkout uses the approved v7 full SHA (Node.js 24 runtime)
- [x] setup-python uses the approved v6 full SHA and the explicit Python matrix
- [x] fail-closed CI requires successful Ubuntu, native Windows, and shell-quality results
- [x] public-clean build/profile contains no private operator defaults
- [x] old generated packages are documented as requiring recompile
- [x] external archive, terminal authority, and exact privacy scan scope are documented
- [x] reserved live Hermes hook is documented as unavailable and prohibited as release evidence

## Graduation blockers

Do not label the release Architect+ while any P0/P1 finding, strict semantic failure, security failure, E2E failure, reproducibility failure, migration failure, or reference/invariant traceability gap remains open.

## Alpha.4 release evidence

- [x] Fresh native Windows clone: 9/9 gates; 415 tests passed, 26 expected
  platform/privilege skips; repository remained clean.
- [x] Fresh WSL Ubuntu clone: 9/9 gates; 415 tests passed, 17 expected
  platform skips; Unix shell-quality 7/7; repository remained clean.
- [x] Deterministic compile: 64 immutable artifacts matched byte-for-byte,
  manifest fingerprint `5b41052c7242a33f8230358fc6982ded4feb473de8d46ca7d89fce0bf855f416`.
- [x] Deterministic archive: one unchanged snapshot produced identical 70-entry,
  752166-byte ZIPs; SHA-256
  `3fec5e60673fc8d30b8ccea8f45bd2fa6e486afe2a5f42f6d0fadf3c2c8fd3ae`;
  strict contract/package validation and ZIP readback passed.
- [x] User stories 55/55; create-skill guard passed; native privacy/secret gate
  reported zero violations; the reserved live Hermes hook remained skipped and
  excluded from release evidence.
- [x] Independent CI/documentation review and independent Windows/security
  review both returned `READY: YES` with no remaining findings.
