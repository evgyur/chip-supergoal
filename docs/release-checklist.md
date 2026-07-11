# Release checklist — chip-supergoal Architect+ v3

## Mandatory local gates

- [ ] CPython 3.11.9 or newer; CI matrix pins 3.11.9 and 3.13.14
- [ ] pinned test dependency: `python -m pip install --disable-pip-version-check -r requirements-test.txt`
- [ ] native Windows: `python scripts/test.py`
- [ ] Ubuntu: `python scripts/test.py`
- [ ] Ubuntu shell quality (Unix-only): `bash scripts/test.sh`
- [ ] `python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict`
- [ ] `python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../sg-build-a`
- [ ] `python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../sg-build-b`
- [ ] compare deterministic immutable outputs from both builds
- [ ] verify secure archive tests and receipt tampering tests pass
- [ ] verify reference catalog/generated index are consistent
- [ ] verify v2 migration fixtures pass

## Release metadata

- [ ] `VERSION` matches the top `CHANGELOG.md` heading
- [ ] generated package manifest has stable fingerprint
- [ ] CI uses least permissions (`contents: read`)
- [ ] GitHub actions are pinned by full SHA
- [ ] checkout uses the approved v7 full SHA (Node.js 24 runtime)
- [ ] setup-python uses the approved v6 full SHA and the explicit Python matrix
- [ ] fail-closed CI requires successful Ubuntu, native Windows, and shell-quality results
- [ ] public-clean build/profile contains no private operator defaults
- [ ] old generated packages are documented as requiring recompile
- [ ] external archive, terminal authority, and exact privacy scan scope are documented
- [ ] reserved live Hermes hook is documented as unavailable and prohibited as release evidence

## Graduation blockers

Do not label the release Architect+ while any P0/P1 finding, strict semantic failure, security failure, E2E failure, reproducibility failure, migration failure, or reference/invariant traceability gap remains open.

## Alpha.4 release evidence

- [ ] Record exact native Windows and Ubuntu aggregate summaries.
- [ ] Record deterministic compile/archive comparison and strict validation.
- [ ] Record user-story, skill-guard, privacy/secret-scan, and reserved-hook skip status.
- [ ] Record independent spec and quality review verdicts.
