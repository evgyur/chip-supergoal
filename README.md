# chip-supergoal

**chip-supergoal** is a Hermes skill that turns a non-trivial engineering request into a disk-backed, reviewable **SuperGoal package** and one standard Hermes `/goal` handoff.

It is designed for work that should not be handled as a loose chat plan: production-adjacent changes, risky refactors, multi-phase implementation, migrations, security-sensitive work, and long-running agent execution that needs state, evidence, and a final audit.

Русская документация: [`docs/README.ru.md`](docs/README.ru.md)

## What it does

`chip-supergoal` is a **planner/compiler**, not the executor.

It creates a `.supergoal/` package containing:

- `THINKING.md` — goals, assumptions, constraints, risk notes, context used.
- `RESEARCH.md` — generated research gate record when current facts or external context matter.
- `reports/research.json` — machine-readable research provider/status/sources report when the gate is active.
- `LOOP_DESIGN.md` — execution loop design: host, reviewer/judge, gates, stop conditions, recovery, boundaries.
- `ROADMAP.md` — phase map, acceptance criteria, required commands, evidence contract.
- `runtime/STATE.json` — authoritative execution state; `STATE.md` is its checked human projection.
- `PROTOCOL.md` — self-contained executor protocol for a later `/goal` run.
- `LAUNCH_GOAL.md` — the only file containing the launch body line beginning with `SUPERGOAL_GOAL_BODY:`.
- `phases/phase-N.md` — strict phase specifications.
- helper scripts and delivery receipts when the workflow requires them.

The later Hermes `/goal` session reads those files and executes the work. Final
completion is valid only when `python scripts/sgctl.py validate-terminal`
accepts the exact package-bound `reports/terminal-record.txt`; transcript
markers such as `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` are compatibility
output, not completion authority by themselves.

## Why it exists

Agentic engineering often fails in predictable ways:

1. The assistant starts implementing before understanding the real target.
2. Long tasks lose state between turns.
3. “Done” is reported before tests, deployment, or audit evidence exists.
4. Risky work skips review because it looks like routine implementation.
5. Generated plans are not executable by a separate agent.

`chip-supergoal` addresses those failure modes by compiling the task into a package with:

- explicit phase boundaries;
- mandatory verification commands;
- evidence requirements;
- risk/RPD review gates;
- state and recovery rules;
- strict launch-marker placement;
- package validation and manifest integrity checks.

## Quick start

Install or clone this repository as a Hermes skill directory, then load it through Hermes.

Typical usage in Hermes:

```text
/chip-supergoal Build or refactor X end-to-end
```

For direct CLI validation of this repository:

Requires CPython 3.11.9 or newer. CI verifies 3.11.9 and 3.13.14 on both
native Windows and Ubuntu.

```console
python -m pip install --disable-pip-version-check -r requirements-test.txt
python scripts/test.py
```

The same aggregate command is supported on native Windows and Ubuntu. The
Unix-only `bash scripts/test.sh` entrypoint additionally enforces shell syntax
and style before it delegates to the Python runner.

Compile the example contract to a fresh sibling directory outside the skill
tree (move or remove an older target first):

```console
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-example
python scripts/sgctl.py validate-package ../chip-supergoal-example --strict
```

Then inspect the launch file with the same Python installation:

```console
python -c "from pathlib import Path; print((Path('../chip-supergoal-example') / 'LAUNCH_GOAL.md').read_text(encoding='utf-8'))"
```

## CLI: `sgctl.py`

The repository includes `scripts/sgctl.py`, a small control utility used by tests and by generated packages.

### Research provider gate

For plans where current facts matter, set `compatibility.research_gate` in `CONTRACT.json`. The preferred provider is `perplex`; official docs, Context7, generic web search, or manual research must include `provider_unavailable_reason` when Perplex was not used.

Minimal satisfied gate:

```json
{
  "compatibility": {
    "research_gate": {
      "required": true,
      "status": "satisfied",
      "provider": "perplex",
      "query": "current facts needed before planning",
      "summary": "Research summary explaining what changed in the plan.",
      "sources": [{"title": "Source", "url": "https://example.com", "provider": "perplex"}],
      "planning_implications": ["Specific phase/spec/acceptance change caused by research"]
    }
  }
}
```

Validate and inspect it:

```console
python scripts/sgctl.py research-gate examples/brownfield-feature/CONTRACT.json --format json
python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict
```

Compile writes `RESEARCH.md` and `reports/research.json`; `validate-package` detects drift in both.

Common commands:

```console
# Validate a v3 contract
python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict

# Compile a contract into a sealed SuperGoal package
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-example

# Validate a generated package
python scripts/sgctl.py validate-package ../chip-supergoal-example --strict

# Migrate an older v2-style package when supported
python scripts/sgctl.py migrate-v2 <old-package-root> --out <new-contract-or-package>
```

## Safety model

### Supported runtime planes

The compiler, validator, state journal, audit, archive, delivery receipts, and
terminal authority are package-local Python authority. They run directly on
native Windows and Ubuntu; Bash files are optional Unix compatibility wrappers,
not a second policy implementation. Packages compiled by an older alpha must be
recompiled before use so they contain the current runtime and schemas.

Only `python scripts/sgctl.py finalize` may create
`reports/terminal-record.txt`, and completion remains unauthorized until
`python scripts/sgctl.py validate-terminal` succeeds against the current sealed
package, authoritative state, recomputed audit, inventory, and delivery state.

Archives must be published to an absolute external archive path outside the
package. Delivery sends only a verified reservation snapshot, with a read-only
Windows handle or anonymous POSIX copy held through transport startup. The
native delivery flow writes multiline authorization JSON with
`--authorization-out` and consumes it with `--authorization-file`, avoiding
PowerShell pipeline/string coercion. The
privacy scan covers all tracked files, including force-tracked runtime paths,
plus untracked working-tree files outside runtime/private state directories. It
does not scan unrelated user directories or serve as a credential manager. No
genuine external Hermes GoalManager probe ships in this repository: the reserved
integration hook is always skipped and must not be counted as release evidence.
Hermetic GoalManager simulation is always part of the aggregate suite.

### Planner/executor boundary

This skill plans and compiles. It does **not** execute implementation phases itself. That boundary is deliberate: the package must be readable, reviewable, and executable by a later standard `/goal` session.

### One launch body

Exactly one actual launch body is allowed, and it belongs in `LAUNCH_GOAL.md`.

Other files may explain the launch process, but they must not contain another real line starting with:

`SUPERGOAL_GOAL_BODY:`

This prevents accidental duplicate goal launches and stale package execution.

### Package sealing

Generated packages include `MANIFEST.json` records with file paths, sha256 hashes, byte counts, modes, and a package fingerprint. `validate-package` detects:

- generated Markdown drift from canonical `CONTRACT.json` rendering;
- manifest hash/size/mode drift;
- extra unsealed files;
- missing required files;
- duplicate or unsafe manifest paths;
- wrong launch-marker placement.

### Compile overwrite protection

The compiler refuses unsafe output targets, including:

- arbitrary existing directories that are not sealed SuperGoal packages;
- packages for a different goal ID;
- changed contracts without the required `contract_revision` advance;
- source-container targets;
- started/runtime packages containing runtime state or delivery output.

## Repository layout

```text
.
├── SKILL.md                      # Hermes skill entrypoint and operating contract
├── README.md                     # English documentation
├── docs/README.ru.md             # Russian documentation
├── lib/chip_supergoal/           # Contract, compiler, validator, state, audit logic
├── scripts/                      # sgctl and verification/probe scripts
├── spec/                         # JSON schemas and policy catalogs
├── templates/                    # Generated package templates
├── references/                   # Detailed workflow and invariant references
├── examples/                     # Example contracts
└── tests/                        # Unit, semantic, rendering, security, migration, e2e tests
```

## Test suite

Run the full local gate:

```console
python -m pip install --disable-pip-version-check -r requirements-test.txt
python scripts/test.py
```

Unix-only shell checks plus the same Python gate:

```bash
bash scripts/test.sh
```

Run Python tests directly:

```console
python -m unittest discover -s tests
```

Focused useful tests:

```console
python -m unittest tests.rendering.test_compile_determinism
python -m unittest tests.semantic.test_sgctl_semantic_validation
python -m unittest tests.security.test_archive_symlink tests.security.test_forged_receipt
```

## Development workflow

1. Change code, templates, references, or tests.
2. Run focused tests for the changed area.
3. Run `python scripts/test.py` on Windows or Ubuntu.
4. On Unix-only development environments, also run `bash scripts/test.sh`.
5. Compile the example package and validate it strictly.
6. Check that only `templates/LAUNCH_GOAL.md` contains a real `SUPERGOAL_GOAL_BODY:` marker.

Suggested final gate:

```console
python scripts/test.py
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-final
python scripts/sgctl.py validate-package ../chip-supergoal-final --strict
```

On Unix-only hosts, run `bash scripts/test.sh` as the additional shell-quality
gate before release.

## Public-use notes

This repository contains the public-safe source of the skill and its validation harness. Runtime state, generated local `.supergoal/` packages, credentials, receipts, caches, and local deployment artifacts should stay outside git.

If you adapt this for another agent runtime, keep the invariants intact:

- one launch surface;
- explicit planner/executor boundary;
- generated package validation;
- no false completion without final audit;
- risk-aware review gates;
- state recovery and blocker semantics.

## License

MIT. See [`LICENSE`](LICENSE).
