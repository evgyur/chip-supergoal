# Chip SuperGoal B2 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make contract-v3 compilation, execution evidence, archives, and the full test workflow fail-closed and natively portable across Windows and Linux.

**Architecture:** Preserve the public v3 model and CLI while routing all validity decisions through one canonical pipeline. Emit a self-contained package with a sealed immutable inventory and an exact mutable runtime registry; make Python the cross-platform authority and retain shell files as Unix wrappers.

**Tech Stack:** Python 3.11+ standard library, `unittest`, JSON/Markdown artifacts, GitHub Actions, Bash wrappers on Unix.

**Approved design:** `docs/superpowers/specs/2026-07-10-chip-supergoal-b2-hardening-design.md`

---

## File responsibility map

- `lib/chip_supergoal/portable.py`: canonical UTF-8/LF writes, atomic replacement, logical modes, cross-platform file lock.
- `lib/chip_supergoal/profiles.py`: profile loading, inheritance, resolved execution contract, public-clean redaction.
- `lib/chip_supergoal/pipeline.py`: one contract diagnostic service shared by validation and compilation.
- `lib/chip_supergoal/compile.py`: safe staging, runtime inventory, manifest 1.1, initial mutable plane.
- `lib/chip_supergoal/render.py`: lossless deterministic executor views.
- `lib/chip_supergoal/state.py`, `events.py`: journal-backed portable state authority and projection.
- `lib/chip_supergoal/evidence.py`, `audit.py`, `terminal.py`: identity/freshness validation, audit authority, terminal wire format.
- `lib/chip_supergoal/archive.py`: deterministic cross-platform ZIP and readback.
- `lib/chip_supergoal/validate.py`: package-local canonical validation and mutable-path checks.
- `scripts/sgctl.py`: stable CLI plus additive runtime/audit/archive commands.
- `scripts/test.py`: native aggregate runner; `scripts/test.sh` is its Unix wrapper plus shell gates.
- `spec/diagnostic-catalog.json`: stable diagnostic registry.
- `.github/workflows/ci.yml`: Ubuntu/Windows parity matrix and mandatory shell tools.

### Task 1: Portable bytes, logical modes, and locking

**Files:**

- Create: `lib/chip_supergoal/portable.py`
- Create: `tests/unit/test_portable_runtime.py`
- Modify: `lib/chip_supergoal/compile.py`
- Modify: `lib/chip_supergoal/state.py`

- [ ] **Step 1: Write failing canonical-byte and lock tests**

```python
class PortableRuntimeTest(unittest.TestCase):
    def test_write_utf8_lf_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifact.md"
            write_utf8_lf(path, "a\r\nb\n")
            self.assertEqual(path.read_bytes(), b"a\nb\n")

    def test_lock_serializes_two_writers(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "state.lock"
            entered = []
            with package_lock(lock):
                entered.append("first")
                with self.assertRaises(StateLockTimeout):
                    with package_lock(lock, timeout=0.05, retry_interval=0.01):
                        entered.append("second")
            self.assertEqual(entered, ["first"])
            self.assertEqual(lock.read_bytes(), b"\0")
```

- [ ] **Step 2: Run the focused tests and confirm missing interfaces**

Run: `python -m unittest tests.unit.test_portable_runtime -v`

Expected: import failure for `chip_supergoal.portable`.

- [ ] **Step 3: Implement the portable boundary**

```python
def canonical_text_bytes(content: str) -> bytes:
    return content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

def write_utf8_lf(path: Path, content: str) -> None:
    write_bytes_atomic(path, canonical_text_bytes(content))

def logical_mode(relative_path: str) -> str:
    return "0755" if relative_path in EXECUTABLE_WRAPPERS else "0644"
```

Implement `package_lock()` with non-blocking `fcntl.flock` on POSIX and byte-zero `msvcrt.locking` on Windows, a shared ten-second timeout, 50 ms default retry, persistent one-byte lock file, and `finally` unlock.

- [ ] **Step 4: Replace text writes and platform `stat` modes on touched paths**

Use `write_utf8_lf()` in compiler/state writes and `logical_mode()` for manifests. Do not reformat unrelated modules.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.unit.test_portable_runtime tests.semantic.test_state_machine -v`

Expected: all tests pass on native Windows.

Commit: `git add lib/chip_supergoal/portable.py lib/chip_supergoal/compile.py lib/chip_supergoal/state.py tests/unit/test_portable_runtime.py && git commit -m "fix: add portable artifact IO and state locking"`

### Task 2: Canonical contract, profile, and risk pipeline

**Files:**

- Create: `lib/chip_supergoal/profiles.py`
- Create: `lib/chip_supergoal/pipeline.py`
- Create: `spec/diagnostic-catalog.json`
- Create: `tests/semantic/test_compile_fail_closed.py`
- Create: `tests/unit/test_profile_policy_pipeline.py`
- Modify: `lib/chip_supergoal/model.py`
- Modify: `lib/chip_supergoal/normalize.py`
- Modify: `lib/chip_supergoal/policy.py`
- Modify: `lib/chip_supergoal/validate.py`
- Modify: `scripts/sgctl.py`

- [ ] **Step 1: Add negative tests for every bypass**

```python
def test_compile_rejects_missing_phase_dependency(self):
    data = fixture_contract()
    data["phases"][0]["depends_on"] = ["P99"]
    result = run_sgctl("compile", write_contract(data), "--out", self.out)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("SGV-CONTRACT-SEMANTIC", result.stderr)
    self.assertFalse(Path(self.out).exists())

def test_missing_profile_is_blocking(self):
    data = fixture_contract()
    data["profile"] = "does-not-exist"
    self.assertHasCode(validate(data), "SGV-PROFILE-NOT-FOUND")

def test_production_requires_approval_and_rollback(self):
    data = fixture_contract(risk_tag="production", approvals=[])
    codes = diagnostic_codes(data)
    self.assertIn("SGV-RISK-APPROVAL-MISSING", codes)
    self.assertIn("SGV-RISK-ROLLBACK-MISSING", codes)
```

Also cover zero phases through strict model/schema loading, duplicate ids, profile cycles, `public-clean` private execution ambiguity, and missing RPD focus.

- [ ] **Step 2: Run the focused failures**

Run: `python -m unittest tests.semantic.test_compile_fail_closed tests.unit.test_profile_policy_pipeline -v`

Expected: current compile succeeds for at least one invalid contract and profile tests fail.

- [ ] **Step 3: Implement profile resolution and execution-contract identity**

```python
@dataclass(frozen=True)
class ResolvedContract:
    contract: Contract
    source_sha256: str
    contract_sha256: str
    profile: dict[str, object]

def resolve_contract(source: Contract, *, root: Path, source_bytes: bytes) -> ResolvedContract:
    profile = resolve_profile(source.profile, root / "profiles")
    plain = apply_profile_defaults(to_plain(source), profile)
    plain = redact_public_contract(plain, profile)
    contract = contract_from_dict(plain)
    encoded = canonical_json(contract).encode("utf-8")
    return ResolvedContract(contract, sha256(source_bytes), sha256(encoded), profile)
```

Reject inheritance cycles, missing parents, unknown profile fields that affect enforcement, and public-clean ambiguity.

- [ ] **Step 4: Implement one diagnostic pipeline**

```python
def contract_diagnostics(path: Path, *, resource_root: Path) -> tuple[ResolvedContract | None, list[Diagnostic]]:
    try:
        source_bytes = path.read_bytes()
        source = load_contract(path)
        resolved = resolve_contract(source, root=resource_root, source_bytes=source_bytes)
    except (OSError, ValueError, ProfileError) as exc:
        return None, [contract_diagnostic(path, exc)]
    policy = load_risk_policy(resource_root / "spec/risk-policy.json")
    diagnostics = semantic_diagnostics(resolved.contract, policy, artifact=path)
    diagnostics.extend(validate_research_gate(resolved.contract, artifact=str(path)))
    return (resolved if not diagnostics else None), diagnostics
```

Load errors map to `SGV-CONTRACT-MALFORMED`; profile, semantic, policy, and research diagnostics are accumulated only when their prerequisites succeeded. `validate-contract` and `compile_contract_file()` call this function with the same package/repository resource root.

- [ ] **Step 5: Register and test diagnostic codes**

Populate `spec/diagnostic-catalog.json` with every emitted `SGV-*` code, invariant, stage, and remediation class. Add a test that scans Python string literals and ensures emitted codes and catalog entries match exactly.

- [ ] **Step 6: Verify and commit**

Run: `python -m unittest tests.unit.test_contract_model tests.unit.test_profile_policy_pipeline tests.semantic.test_compile_fail_closed tests.semantic.test_research_gate -v`

Expected: all pass; invalid compile creates no output.

Commit: `git add lib/chip_supergoal/profiles.py lib/chip_supergoal/pipeline.py lib/chip_supergoal/model.py lib/chip_supergoal/normalize.py lib/chip_supergoal/policy.py lib/chip_supergoal/validate.py scripts/sgctl.py spec/diagnostic-catalog.json tests/semantic/test_compile_fail_closed.py tests/unit/test_profile_policy_pipeline.py && git commit -m "fix: make contract compilation fail closed"`

### Task 3: Self-contained package and manifest 1.1

**Files:**

- Modify: `lib/chip_supergoal/compile.py`
- Modify: `lib/chip_supergoal/validate.py`
- Modify: `scripts/sgctl.py`
- Modify: `tests/rendering/test_compile_determinism.py`
- Create: `tests/rendering/test_self_contained_package.py`
- Create: `tests/fixtures/contracts/minimal-valid.json`

- [ ] **Step 1: Add failing inventory and relocation tests**

```python
def test_library_compile_is_self_contained_without_source_checkout(self):
    compile_contract_file(CONTRACT, self.package)
    required = {
        "scripts/sgctl.py", "lib/chip_supergoal/validate.py",
        "templates/PROTOCOL.md", "spec/risk-policy.json",
        "profiles/base.json", "profiles/chip-private.json",
    }
    self.assertTrue(required <= package_files(self.package))
    moved = Path(self.tempdir) / "nested path" / ".supergoal" / "slug"
    shutil.move(self.package, moved)
    result = subprocess.run([sys.executable, moved / "scripts/sgctl.py", "validate-package", moved, "--strict"], text=True, capture_output=True)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

Add a direct-library test proving `PROTOCOL.md` equals the package-local canonical template rather than the marker stub.

- [ ] **Step 2: Confirm the current 11-file package fails the new inventory test**

Run: `python -m unittest tests.rendering.test_self_contained_package -v`

Expected: missing `scripts/`, `lib/`, profiles, policy, and template.

- [ ] **Step 3: Implement explicit runtime inventory and manifest 1.1**

Define constant sealed runtime lists for scripts/modules/templates/spec/profile files. Copy only those files, normalize text bytes, and apply logical modes. Manifest shape:

```json
{
  "manifest_version": "1.1",
  "source_contract_sha256": "<64 hex>",
  "contract_sha256": "<64 hex>",
  "artifacts": [],
  "mutable_paths": [],
  "package_fingerprint": "<64 hex>"
}
```

The implementation writes real hashes and the exact mutable registry from the design. `STATE.md` and `runtime/**` are excluded from `artifacts` but validated separately.

- [ ] **Step 4: Initialize the mutable plane**

Create revision-1 `COMPILED` state for the lowest-ordinal ready phase, one journal event, `[]` evidence, and a canonical state projection. Add strict validation for unknown files and missing required mutable files.

- [ ] **Step 5: Restore atomic target replacement and validate staging before swap**

Call `validate_package(staging)` before renaming staging to the target. Preserve the prior package on any diagnostic or exception.

- [ ] **Step 6: Verify and commit**

Run: `python -m unittest tests.rendering.test_compile_determinism tests.rendering.test_self_contained_package tests.semantic.test_sgctl_semantic_validation -v`

Expected: byte-stable packages, relocation pass, mutable state changes do not alter sealed fingerprint.

Commit: `git add lib/chip_supergoal/compile.py lib/chip_supergoal/validate.py scripts/sgctl.py tests/rendering/test_compile_determinism.py tests/rendering/test_self_contained_package.py tests/fixtures/contracts/minimal-valid.json && git commit -m "fix: emit sealed self-contained SuperGoal packages"`

### Task 4: Lossless rendering and package-root protocol

**Files:**

- Modify: `lib/chip_supergoal/render.py`
- Modify: `templates/PROTOCOL.md`
- Modify: `templates/LAUNCH_GOAL.md`
- Modify: `templates/STATE.md`
- Modify: `tests/rendering/test_compile_determinism.py`
- Create: `tests/rendering/test_lossless_rendering.py`

- [ ] **Step 1: Add independent field-mutation tests**

```python
EXECUTION_MUTATIONS = {
    "deliverable": lambda d: d["phases"][0]["deliverables"][0].update(path="changed.txt"),
    "expected_exit": lambda d: d["phases"][0]["criteria"][0]["verifier"].update(expected_exit=7),
    "blocking": lambda d: d["phases"][0]["criteria"][0].update(blocking=False),
    "safety": lambda d: d["phases"][0]["commands"][0].update(safety="read_only"),
    "timeout": lambda d: d["phases"][0]["commands"][0].update(timeout_seconds=9),
}

def test_each_execution_field_changes_a_view(self):
    baseline = compile_views(fixture_contract())
    for name, mutate in EXECUTION_MUTATIONS.items():
        changed = fixture_contract(); mutate(changed)
        self.assertNotEqual(baseline, compile_views(changed), name)
```

Add assertions for sources, decisions, work items, approvals, delivery, research, compatibility, rollback, all RPD focus values, and absence of invented cron/Telegram/non-git prose.

- [ ] **Step 2: Run and observe identical-output failures**

Run: `python -m unittest tests.rendering.test_lossless_rendering -v`

Expected: deliverable/verifier/safety/timeout cases fail.

- [ ] **Step 3: Render complete phase and roadmap structures**

Use deterministic JSON-style key ordering for free-form architecture/loop/compatibility blocks. Render each deliverable and each verifier property explicitly. Render every RPD focus item, not only index zero.

- [ ] **Step 4: Make protocol commands relocatable and Python-authoritative**

Replace `.supergoal/scripts/*.sh` authority with explicit `python scripts/sgctl.py validate-package . --strict`, `state-transition`, `record-evidence`, `audit`, and `finalize` commands from the directory containing `LAUNCH_GOAL.md`. Keep shell wrapper examples in a Unix compatibility subsection. Do not embed compile-time paths.

- [ ] **Step 5: Verify canonical drift and commit**

Run: `python -m unittest tests.rendering tests.semantic.test_current_validator_escape_cases -v`

Expected: all pass on Windows and Linux; generated `PROTOCOL.md` is canonical-checked.

Commit: `git add lib/chip_supergoal/render.py templates/PROTOCOL.md templates/LAUNCH_GOAL.md templates/STATE.md tests/rendering/test_compile_determinism.py tests/rendering/test_lossless_rendering.py && git commit -m "fix: render execution contracts without information loss"`

### Task 5: Journal state, bound evidence, audit, and terminal records

**Files:**

- Create: `lib/chip_supergoal/terminal.py`
- Modify: `lib/chip_supergoal/state.py`
- Modify: `lib/chip_supergoal/events.py`
- Modify: `lib/chip_supergoal/evidence.py`
- Modify: `lib/chip_supergoal/audit.py`
- Modify: `lib/chip_supergoal/validate.py`
- Modify: `scripts/sgctl.py`
- Modify: `tests/semantic/test_state_machine.py`
- Modify: `tests/semantic/test_audit_engine.py`
- Create: `tests/security/test_terminal_authority.py`

- [x] **Step 1: Write forged-evidence and terminal-record failures**

```python
def test_wrong_identity_and_exit_cannot_complete(self):
    record = EvidenceRecord.pass_record(
        evidence_id="ev-1", goal_id="wrong", contract_revision=999,
        phase_id="P01", criterion_id="P01-C01", command="false", exit_code=17,
    )
    report = audit_contract(self.contract, [record], state=self.done_state, audit_started_at=self.anchor)
    self.assertFalse(report.can_complete)
    self.assertFalse(terminal_markers_allowed(self.done_state, report))

def test_terminal_parser_rejects_duplicate_and_crlf_records(self):
    valid = terminal_record(self.done_state, self.audit_path)
    self.assertTrue(validate_terminal_record(valid.encode()).ok)
    self.assertFalse(validate_terminal_record(valid.replace("\n", "\r\n").encode()).ok)
    self.assertFalse(validate_terminal_record((valid + valid).encode()).ok)
```

Add stale, future-skew, wrong-command, wrong-contract-hash, missing policy evidence, marker injection, marker negation, substring, audit-hash, and state-revision cases.

- [x] **Step 2: Run the focused security tests and confirm current false completion**

Run: `python -m unittest tests.semantic.test_audit_engine tests.security.test_terminal_authority -v`

Expected: wrong identity evidence currently yields completion and terminal module is absent.

- [x] **Step 3: Implement journal-backed transitions**

Journal events carry full target state, state hash, previous hash, timestamp, and event hash. Transition writes the fsynced event first, then atomically replaces JSON and Markdown. Recovery replays the last valid event. All mutations use `package_lock()`.

- [x] **Step 4: Implement deterministic evidence validation**

Parse RFC3339 `Z` timestamps, derive audit anchor from the current transition-to-auditing event, apply five-minute future skew and resolved max ages, compare declared command/exit, and require policy evidence tags in `metadata["policy_evidence"]`.

- [x] **Step 5: Add CLI runtime commands**

Add `state-show`, `state-transition`, `state-recover`, `record-evidence`, `audit`, `finalize`, and `validate-terminal`. Each command resolves the package root, uses package-local contract/resources, prints structured diagnostics on failure, and writes canonical artifacts atomically. Recovery is explicit and replays only a fully valid journal; corruption is never swallowed.

- [x] **Step 6: Verify and commit**

Run: `python -m unittest tests.semantic.test_state_machine tests.semantic.test_audit_engine tests.security.test_terminal_authority tests.e2e.test_full_run -v`

Expected: all pass; only `python scripts/sgctl.py finalize` can create the exact terminal record.

Commit: `git add lib/chip_supergoal/terminal.py lib/chip_supergoal/state.py lib/chip_supergoal/events.py lib/chip_supergoal/evidence.py lib/chip_supergoal/audit.py lib/chip_supergoal/validate.py scripts/sgctl.py tests/semantic/test_state_machine.py tests/semantic/test_audit_engine.py tests/security/test_terminal_authority.py && git commit -m "fix: bind SuperGoal completion to state and evidence"`

### Task 6: Deterministic archive authority

**Files:**

- Modify: `lib/chip_supergoal/archive.py`
- Modify: `templates/delivery/package-final-artifacts.sh`
- Modify: `scripts/sgctl.py`
- Modify: `tests/security/test_archive_determinism.py`
- Modify: `tests/security/test_archive_symlink.py`
- Create: `tests/security/test_archive_manifest_collision.py`

- [ ] **Step 1: Add collision and cross-platform metadata regressions**

```python
def test_package_manifest_occurs_once(self):
    result = deterministic_zip(self.package, self.external_zip, self.result_json)
    with zipfile.ZipFile(self.external_zip) as zf:
        self.assertEqual(zf.namelist().count("MANIFEST.json"), 1)
        self.assertEqual(zf.namelist().count("ARCHIVE-MANIFEST.json"), 1)
        self.assertEqual(len(zf.namelist()), len(set(zf.namelist())))

def test_archive_destination_inside_root_is_rejected(self):
    with self.assertRaisesRegex(ArchiveSecurityError, "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT"):
        deterministic_zip(self.package, self.package / "out.zip", self.result_json)
```

Assert `ZIP_STORED`, timestamps, creator version, UTF-8 flag, logical modes, no directory entries, identical bytes on two runs, and secret/symlink rejection.

- [ ] **Step 2: Confirm the current duplicate `MANIFEST.json` failure**

Run: `python -m unittest tests.security.test_archive_determinism tests.security.test_archive_manifest_collision -v`

Expected: hash mismatch or duplicate-name assertion.

- [ ] **Step 3: Implement one ZIP writer**

Write sorted source entries once, preserve package `MANIFEST.json`, append `ARCHIVE-MANIFEST.json`, use fixed `ZipInfo`, and read back every field/hash before `os.replace()` of the external destination. Exclude the persistent lock and prior delivery outputs.

- [ ] **Step 4: Route delivery shell through `python scripts/sgctl.py archive`**

The shell file only validates arguments and executes `python scripts/sgctl.py archive <package-root> --out <external-zip> --manifest <result-json>`; archive policy remains in Python.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.security -v`

Expected: all pass natively on Windows; symlink fixture may skip only when Windows denies fixture creation, while policy tests still execute.

Commit: `git add lib/chip_supergoal/archive.py templates/delivery/package-final-artifacts.sh scripts/sgctl.py tests/security/test_archive_determinism.py tests/security/test_archive_symlink.py tests/security/test_archive_manifest_collision.py && git commit -m "fix: make package archives deterministic and collision-free"`

### Task 7: Native aggregate runner and Windows path parity

**Files:**

- Create: `scripts/test.py`
- Modify: `scripts/test.sh`
- Modify: `scripts/test-user-stories.py`
- Modify: `tests/semantic/test_current_validator_escape_cases.py`
- Modify: `tests/security/test_archive_symlink.py`
- Modify: `.gitattributes`
- Create: `tests/ci/test_native_runner.py`

- [ ] **Step 1: Add native-runner and path tests**

```python
def test_user_story_paths_are_posix_serialized(self):
    result = subprocess.run([sys.executable, ROOT / "scripts/test-user-stories.py"], text=True, capture_output=True)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertIn("total=55 passed=55 failed=0", result.stdout)

def test_aggregate_runner_uses_current_interpreter(self):
    plan = build_test_plan(ROOT)
    self.assertTrue(all(command[0] == sys.executable for command in plan.python_commands))
```

- [ ] **Step 2: Capture current native failures**

Run: `$env:PYTHONUTF8='1'; python -m unittest discover -s tests`

Expected before fixes: `fcntl` imports, WSL Windows-path escaping, CRLF drift, Bash archive, and symlink privilege failures.

- [ ] **Step 3: Implement `scripts/test.py`**

Use `subprocess.run()` argument lists, `sys.executable`, UTF-8 environment, Python privacy/reference checks, user-story runner, `unittest discover`, and `git diff --check`. Print the same machine-readable summary on both platforms and return the first failing gate.

- [ ] **Step 4: Make shell and path tests portable**

`scripts/test.sh` runs Unix shell syntax/style gates and then `python3 scripts/test.py --skip-shell`. Tests pass `Path` values as subprocess argument-list elements; they do not interpolate Windows paths into Bash command strings. Symlink tests detect privilege absence and keep a separate mocked `lstat` rejection test.

- [ ] **Step 5: Normalize repository text policy**

Set LF for Python, Markdown, JSON, YAML, CSV, and shell sources in `.gitattributes`; reserve CRLF only for future `.cmd`/`.bat` files. Runtime comparisons remain byte-canonical and do not depend on checkout settings.

- [ ] **Step 6: Verify and commit**

Run on Windows: `$env:PYTHONUTF8='1'; python scripts/test.py`

Run on Linux: `python3 scripts/test.py`

Expected: user stories `55/55`, complete suite green with only the unavailable live GoalManager canary skipped.

Commit: `git add scripts/test.py scripts/test.sh scripts/test-user-stories.py tests/semantic/test_current_validator_escape_cases.py tests/security/test_archive_symlink.py tests/ci/test_native_runner.py .gitattributes && git commit -m "test: add native Windows aggregate parity"`

### Task 8: CI, documentation, and alpha.4 release metadata

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/README.ru.md`
- Modify: `docs/compatibility-matrix.md`
- Modify: `docs/release-checklist.md`
- Modify: `SKILL.md`
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `tests/ci/test_release_engineering.py`

- [ ] **Step 1: Add failing release-contract assertions**

Assert CI contains both `ubuntu-24.04` and `windows-latest`, calls `scripts/test.py`, pins the approved checkout v7 commit, installs mandatory `shellcheck`/`shfmt` on Ubuntu, documents Python-authoritative package execution, and reports version `3.0.0-alpha.4`.

- [ ] **Step 2: Run the release tests and confirm old metadata fails**

Run: `python -m unittest tests.ci.test_release_engineering -v`

Expected: missing Windows runner, stale checkout pin, optional shfmt, and old version failures.

- [ ] **Step 3: Update CI with a parity matrix**

Use a Python-test matrix for Ubuntu/Windows and a separate Ubuntu shell-quality job. Aggregate depends on both OS results plus shell quality. Install tools before invoking them and remove advisory `unavailable` branches.

- [ ] **Step 4: Update public contracts and release notes**

Document package planes, Python commands, Unix wrappers, recompile requirement for old packages, Windows/Ubuntu support, external archive destination, terminal authority, privacy scanner scope, and the optional live Hermes canary. Bump `VERSION` and prepend the alpha.4 changelog entry.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.ci.test_release_engineering tests.unit.test_reference_catalog_profiles -v`

Expected: all pass.

Commit: `git add .github/workflows/ci.yml README.md docs/README.ru.md docs/compatibility-matrix.md docs/release-checklist.md SKILL.md VERSION CHANGELOG.md tests/ci/test_release_engineering.py && git commit -m "release: prepare cross-platform v3 alpha.4"`

### Task 9: Full review, clean-clone verification, and publication

**Files:**

- Modify only files identified by review findings that reproduce against the approved design.

- [ ] **Step 1: Run spec-correctness review**

Compare every design acceptance criterion to code/tests. Any missing requirement becomes a failing focused test before a fix.

- [ ] **Step 2: Run independent quality review**

Review validation authority, archive path safety, lock/journal crash behavior, privacy redaction, duplicated logic, and Windows subprocess/path boundaries. Fix only evidence-backed findings.

- [ ] **Step 3: Run native Windows gates**

Run:

```powershell
$env:PYTHONUTF8='1'
python scripts/test.py
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out "$env:TEMP\chip-supergoal-alpha4"
python scripts/sgctl.py validate-package "$env:TEMP\chip-supergoal-alpha4" --strict
git diff --check
```

Expected: all exit `0`; one documented live-canary skip only.

- [ ] **Step 4: Run a true Linux fresh-clone gate**

Clone the current branch into the WSL/Linux filesystem, then run `python3 scripts/test.py`, compile, strict package validation, archive readback, and `git diff --check`. Expected: all exit `0` and the ZIP hash matches the Windows archive for identical package bytes.

- [ ] **Step 5: Run publication hygiene**

Run the unmasked skill workflow guard, user stories, repository privacy scan, high-confidence secret scan over tracked files and the branch diff, JSON parsing for every changed JSON file, `git status --short --branch`, and `git diff origin/main..HEAD --check`.

- [ ] **Step 6: Commit review repairs and push**

Commit any verified review repairs with a bounded message. Push the branch, fast-forward local `main` only after the branch is clean and verified, then push `main` to `origin`.

- [ ] **Step 7: Read back GitHub Actions**

Verify the remote SHA equals the local publication SHA and every required Ubuntu/Windows/shell/security/aggregate job is green. If a job fails, reproduce, fix, recommit, repush, and repeat until the pushed SHA is green.

## Plan self-review

- Spec coverage: all approved design sections map to Tasks 1-9.
- Placeholder scan: no deferred implementation steps are present; each code boundary, command, and expected result is explicit.
- Type consistency: `ResolvedContract`, manifest 1.1 fields, portable lock API, audit identity fields, and terminal grammar use the same names throughout.
- Safe stop: before publication, the branch can be abandoned without changing `origin/main`; after publication, bounded commits can be reverted.
