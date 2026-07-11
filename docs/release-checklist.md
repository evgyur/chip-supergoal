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

- [x] Fresh native Windows clone: 9/9 gates; 426 tests passed, 27 expected
  platform/privilege skips; repository remained clean.
- [x] Fresh WSL Ubuntu clone: 9/9 gates; 426 tests passed, 22 expected
  platform skips; Unix shell-quality 7/7; repository remained clean.
- [x] Deterministic compile: 64 immutable artifacts matched byte-for-byte,
  manifest fingerprint `41f4ce1220d5a91a70c6222d747d8d3f8eaf9a143186d791691e275219232145`.
- [x] Deterministic archive: one unchanged snapshot produced identical 70-entry,
  764973-byte ZIPs; SHA-256
  `0cc461fcee2fc0e791cabca00a175b6a1efdaa5f68ff522c52fd379ef2db547f`;
  strict contract/package validation and ZIP readback passed.
- [x] User stories 55/55; create-skill guard passed; native privacy/secret gate
  reported zero violations; the reserved live Hermes hook remained skipped and
  excluded from release evidence.
- [x] Independent CI/documentation review and independent Windows/security
  review both returned `READY: YES` with no remaining findings.
