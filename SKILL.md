---
name: chip-supergoal
description: Plan-only autonomous software task planner that writes ROADMAP, phase specs, protocol, and one `/goal` handoff. Embeds RPD review gates directly; does not depend on an external `/rpd` skill. Use for `/chip-supergoal`, “plan and ship X”, autonomous build planning, or non-trivial feature/refactor/redesign that should be handed off to `/goal` for execution.
argument-hint: <describe what you want built, fixed, or shipped>
---

# chip-supergoal

You are running the chip-supergoal workflow. The user's task is:

$ARGUMENTS

Your job: **plan deeply, write execution artifacts, and hand off one `/goal`**. `/chip-supergoal` is plan-only; the future `/goal` session performs execution from the generated files.

## What "every aspect is perfect" means here

The user's bar is high. Translate it into measurable criteria, not vibes:

- **Functional** — the feature works for the golden path and the obvious edge cases
- **Engineering** — build, typecheck, lint, tests all pass; no new warnings
- **Polish** — UX/copy, error states, empty states, loading states are handled
- **Hardening** — security review, input validation, no obvious regressions
- **Verification** — every phase produces transcript evidence the evaluator can see

If a phase can't be measured, it isn't a phase. Rewrite it until it can.

## How this skill works (one-shot summary)

0. **Available context** — preload memory; detect available tools (Context7, WebSearch, MCPs, skills); resume any in-progress chip-supergoal state
1. **Intake** — restate, classify, ask enough questions to cover every material gap. Greenfield walks the full category checklist (platform, stack, design direction, integrations, scope, audience, perf, data model) in batches of up to 4 until everything material is filled in; brownfield asks 0–2 since recon answers most structural questions.
2. **Recon** — parallel codebase + environment scan
3. **Research-before-design + Architect+ lite** — if research is required, load/use skill `perplex` first when available; run fresh-docs/existing-solutions gates; for substantial risky plans add source-of-truth, permissions, failure modes, and verification strategy; then list top-3 risks + dependencies
4. **Decompose** — derive phase count from the task itself; no fixed cap
5. **Write phase specs** — one work-spec file per phase under `.supergoal/phases/phase-N.md` (any length, no char budget)
6. **Embedded RPD plan review** — run RPD_PLAN_REVIEW, mutate weak specs in place, then show summary + concrete revision menu; wait for explicit go/no-go
7. **Hand off one ready-to-paste `/goal`** with a short end-state condition; the user pastes once, and the agent inside that fresh `/goal` session executes phases sequentially with retry + fix-spec recovery + per-phase memory writeback, then runs a **final audit** that re-verifies the work against the original ROADMAP and self-heals any gaps before completion holds

Two human gates only: **clarifying questions for true gaps (Stage 1)** and **plan review (Stage 6)**. Everything else runs autonomously.

### Why one `/goal`, not a chain

`/goal` in both Claude Code and Codex takes a **short end-state condition**, not a long task body. A fast evaluator checks the condition against the transcript after each turn and auto-continues until it holds. chip-supergoal leverages this directly: one `/goal` covers the whole run; phase work lives in files the agent reads from disk; the condition is "all phases done, `SUPERGOAL_RUN_COMPLETE` printed." No char budget, no inter-session chain dispatch, no fragility.

## Locate the skill directory

```bash
SUPERGOAL_DIR=$(dirname "$(ls -1 \
  "$HOME/.hermes/skills/chip-supergoal/SKILL.md" \
  "$HOME/.claude/skills/chip-supergoal/SKILL.md" \
  "$PWD/.claude/skills/chip-supergoal/SKILL.md" \
  2>/dev/null | head -n1)")
export SUPERGOAL_DIR
export SUPERGOAL_ROOT="${SUPERGOAL_ROOT:-.supergoal}"
mkdir -p "$SUPERGOAL_ROOT/goals"
echo "SUPERGOAL_DIR=$SUPERGOAL_DIR"
echo "SUPERGOAL_ROOT=$SUPERGOAL_ROOT"
```

All artifacts live under `$SUPERGOAL_ROOT`. Skill assets (scripts, references, templates) live under `$SUPERGOAL_DIR`.

---

## Stage 0 — Available context (memory + tools)

Before doing anything else, sense what's available this session. This is what makes the run frictionless — if memory already knows the user's preferences, don't ask; if a tool isn't available, don't try to call it.

### Memory preload

```bash
# Detect a memory directory. Common locations:
MEM_DIR=""
for cand in \
  "$HOME/.claude/projects/-Users-$(whoami)/memory" \
  "$HOME/.claude/memory" \
  "$PWD/.claude/memory" \
  "$SUPERGOAL_ROOT/memory"; do
  [[ -d "$cand" ]] && MEM_DIR="$cand" && break
done
echo "MEM_DIR=$MEM_DIR"

if [[ -n "$MEM_DIR" && -f "$MEM_DIR/MEMORY.md" ]]; then
  echo "--- MEMORY INDEX ---"
  cat "$MEM_DIR/MEMORY.md"
fi
```

Read the index. Then **selectively** read individual memory files that look relevant to the task (feedback memories about the stack/domain, user role memories, related project memories). Don't dump them all into context — pull what matters.

Capture applicable memory hits in `$SUPERGOAL_ROOT/applied-memories.md` (one line per memory: name, why-applicable, what-it-changes). Surface them in Stage 1 as "Applied from memory: …" so the user can see what's being inherited and correct anything stale.

### Tool discovery

Tools differ between sessions and hosts (Claude Code vs Codex, different MCP server sets). Detect, don't assume:

- **Context7** — available if `mcp__claude_ai_Context7__resolve-library-id` or similar is in the tool list. If absent, skip it; rely on training-cutoff knowledge + WebSearch if that's present.
- **WebSearch / WebFetch** — available if listed. If neither, skip web research.
- **Project skills** — check the available-skills list for domain-relevant skills (e.g. `mobile-ios-design`, `clerk-auth`, `expo-dev-client`) and note them in `$SUPERGOAL_ROOT/applied-skills.md` to invoke from inside phase goals if relevant.
- **Prior chip-supergoal state** — if `$SUPERGOAL_ROOT/STATE.md` exists from a previous run, read it; resume rather than restart.

Write detected tools to `$SUPERGOAL_ROOT/tools.md`. Stage 3 and the phase goals reference this file when deciding what to invoke.

### Resume detection

If `STATE.md` exists and shows `Status: IN_PROGRESS` with a phase pending, **do not re-plan**. Print a one-line "Resuming chip-supergoal from phase N" and jump straight to Stage 6 (plan review) with the existing artifacts, or directly to Stage 7 (dispatch) if the user confirms resume.

---

## Stage 1 — Intake & clarifying questions

Echo the task back in **one sentence**. Then classify it (tags can combine):

| Tag | Trigger |
|---|---|
| `greenfield` | Request implies a new project; cwd has no `.git/` or empty tree |
| `brownfield` | Change in an existing repo |
| `bugfix` | Mentions "bug", "broken", "fails", "regression" |
| `refactor` | Mentions "refactor", "clean up", "restructure" |
| `ui` | Mentions "design", "polish", "UI", "UX", "responsive", "redesign" |

**Calibrate the question count to the context.** Greenfield has no codebase to scan, so it needs enough verbal context to plan well — never artificially limit questions when material info is missing. Brownfield runs lean on recon, so questions are sparse.

### Greenfield — gather enough context to plan well

A new project has no signal beyond the user's prompt + memory. The planner's job in Stage 1 is to **enumerate every category that meaningfully shapes the plan, eliminate the ones already answered by memory or prompt, and ask about every remaining one**. Don't stop until every material gap is filled.

**Category checklist — work through this for every greenfield run:**

| Category | Why it shapes the plan |
|---|---|
| **Target platform / surface** | iOS, Android, web, desktop, CLI, multi — the biggest fork. Different stacks, different phases. |
| **Stack / framework preference** | Next.js vs SvelteKit, Expo vs bare RN, FastAPI vs Django, Swift vs SwiftUI vs UIKit, etc. Affects every phase. |
| **Design direction / aesthetic** | Minimal-mono, brutalist, glass morphism, Apple-native, dashboardy-corporate, retro, etc. Determines tokens, component shapes, Polish phase content. |
| **Integration anchors** | Auth provider, database, payments, hosting, analytics, file storage, email — anything that locks in a vendor up front. |
| **Scope cut-line** | MVP-this-week vs full feature; what's explicitly out of scope vs deferred to v2. |
| **Primary use case / audience** | Solo-dev tool, team SaaS, public consumer app, internal admin — drives auth flow, onboarding shape, error tolerance. |
| **Performance / scale constraints** | "Realtime sub-100ms" vs "background batch ok"; expected traffic; offline-first or online-only. Only ask if non-trivial. |
| **Data model anchors** | If the prompt implies data, ask the shape ("users + posts? users + projects + tasks?"). Only if not obvious. |

**Process:**

1. For each category, ask: *did the user's prompt mention it? Does memory have a relevant preference?*
2. If yes → use that, surface as "Applied from memory: …" or "From your prompt: …"
3. If no → that category becomes a question.
4. Ask all remaining questions in **batches of up to 4** (the `AskUserQuestion` tool ceiling) until every material gap is filled. Two batches is fine for greenfield; three is rare but allowed if a complex task genuinely warrants it.
5. Within each batch, lead with the highest-leverage choices (the ones that change the phase shape most).

**Anti-patterns:**

- **Don't ask one batch and then plan around silent assumptions for the rest.** If you're about to assume the design direction, the auth provider, AND the scope cut-line, that's 3 assumptions and one batch of follow-up is cheaper than getting it wrong.
- **Don't pad questions when memory/prompt already covers them.** Reading "I want a SwiftUI iOS app with Liquid Glass" → don't ask "what platform?", "what stack?", or "what aesthetic?". Just ask about integrations, scope, and use case.
- **Don't ask micro-details** that belong in plan review: naming, file paths, copy wording, color palette specifics, library minor versions, default test framework if the stack has one. Those go into ROADMAP.md as assumptions and surface in Stage 6's revision menu.

### Brownfield — 0–2 questions, one batch

The codebase plus recon scripts already answer most structural questions (stack, package manager, build/test/lint, conventions, what exists). Ask only for **true gaps** memory + prompt + recon leave open:

- Scope cut-line ("just this surface, or also touch the related ones?")
- Compatibility surface ("backwards compat with the old API path, or break it?")
- Primary fork when ambiguous ("which of these two existing patterns do you want me to extend?")

Most well-described brownfield tasks ask **zero questions**.

### In both modes

1. Lead with "Applied from memory: …" and "From your prompt: …" so the user sees what's being inherited or read off before answering.
2. Each `AskUserQuestion` batch caps at 4 (tool limit). Greenfield can use multiple sequential batches; brownfield is one batch max.
3. If you genuinely need zero questions, say "No clarifying questions — proceeding from prompt + memory + recon." and move straight to Stage 2.
4. Never ask about anything you can responsibly assume — those go into the Stage 6 plan review for one-click correction.

---

## Stage 2 — Recon (parallel)

Run recon scripts in parallel. They populate context files under `$SUPERGOAL_ROOT/`.

### Brownfield path

```bash
bash "$SUPERGOAL_DIR/scripts/detect-stack.sh"   > "$SUPERGOAL_ROOT/context.md"
bash "$SUPERGOAL_DIR/scripts/summarize-repo.sh" > "$SUPERGOAL_ROOT/repo-map.md"
```

### Greenfield path

```bash
bash "$SUPERGOAL_DIR/scripts/detect-env.sh" > "$SUPERGOAL_ROOT/context.md"
```

Read the outputs. Then print a **5-line summary** to the user: stack, package manager, build/test/lint commands, notable modules (if any), risky areas. This is what tells them you've actually understood their codebase before planning.

---

## Stage 3 — Deep think

This is the difference between a generic plan and a strong chip-supergoal plan. Spend real cycles here — but use only what's available.

**Required regardless of tools:**
- Identify the **top 3 risks**: what's most likely to go wrong, what's hardest to undo, what's easy to miss until shipped.
- Identify **non-obvious dependencies**: things that have to happen in a specific order or block other work.
- Apply memory hits from `$SUPERGOAL_ROOT/applied-memories.md` — bake them into goals, constraints, or risk mitigations.

**Research-before-design gates** (use only when they materially shape the plan):

- **Research trigger check** — required for greenfield products/systems, unfamiliar domains, current SDK/API/framework behavior, auth/payments/security/compliance, major migration/refactor, build-vs-buy uncertainty, or when the user asks for best practices / world practice / not reinventing the wheel.
- **Skill-first Perplex gate** — if skill `perplex` exists in the available skills catalog, load/use that skill first for open-ended current web research. Do not treat generic `web_search` as equivalent just because a runtime backend might route through Perplexity.
- **Fresh-docs gate** — use Context7 or official docs for SDK/API/framework-specific facts; if unavailable, record the version assumption and add a phase-1 verification criterion.
- **Existing Solutions Gate** — search OSS, SaaS, package registries, libraries, and reference-code. Shortlist candidates, inspect top candidates statically only, and decide `buy | wrap | fork | copy_pattern | build_fresh | defer`.
- **Fallback search** — use generic `web_search` / `web_extract` only when no dedicated research skill/tool is available or when fetching known source URLs.
- **Fail-closed for critical facts** — if missing external facts materially affect architecture, security, compliance, payments, auth, SDK/API choice, or build-vs-buy, the plan is not approval-ready until research is completed or the user explicitly accepts the assumption.

**Write `$SUPERGOAL_ROOT/THINKING.md`** with sections: Goals, Constraints, Risks, Dependencies, Open Questions (already-assumed), Memory hits applied, Tools/skills relied on, Best Practices Applied. Keep it tight — 1–2 pages. This is the substrate the roadmap derives from. If any research gate ran, also write `$SUPERGOAL_ROOT/RESEARCH.md` from `$SUPERGOAL_DIR/templates/RESEARCH.md` and fill status, sources, existing-solution candidates, build-vs-buy verdict, planning implications, and unverified assumptions.

See `references/planning-depth.md` for the bar to clear here.

---

## Research tool priority — skill-first

When current research is required, prioritize the **`perplex` skill itself** if it exists in the available skills catalog. This means: load/use the `perplex` skill workflow first, before generic web search, because local installs may encode the operator's preferred Sonar routing, source mix, credentials, cost controls, and fallback rules.

Priority order:

1. **Skill `perplex`** — if available, load it and follow its workflow for open-ended web/current research.
2. Context7 / official docs — for SDK, framework, API, and version-specific planning facts.
3. GitHub/package/SaaS search — for existing solutions, libraries, products, and reference-code candidates.
4. Generic `web_search` / `web_extract` — fallback only when no dedicated research skill/tool is available or when fetching known source URLs.
5. If critical facts are unavailable, mark the plan `not approval-ready` unless the user explicitly accepts the assumption.

Do not collapse this into “use any Perplexity backend.” The trigger is the installed `perplex` skill and its local workflow, not merely a search provider name.

---

## Architect+ lite gate

For large, architecture-affecting, agent-native, security-sensitive, or production-facing plans, add an Architect+ lite block before decomposition. Do not drag in a full formal-contract system for small work; use this only when the plan would otherwise be easy to execute incorrectly.

Architect+ lite requires:

- **Source-of-truth boundary** — what owns truth, what is derived/cache/view state, and what must not become a second source of truth.
- **Permission matrix** — human, service, admin, and agent roles; what each can read/write/execute.
- **Failure-mode matrix** — top failure modes mapped to continue/degraded/fail-closed/human-gate behavior.
- **Verification strategy** — commands, tests, probes, smoke checks, logs, screenshots, or API checks that prove the riskiest behavior before implementation is considered done.

Write the result into `THINKING.md` and summarize it in `ROADMAP.md` / Stage 6 when applicable. If skipped, record a narrow reason.

---

## Embedded RPD review system

chip-supergoal is independent from any external `/rpd` skill. Do not load or invoke another RPD skill to run this workflow. Use the embedded contract in `references/rpd-review-gates.md`.

RPD is a mutation gate, not a commentary layer:

- Every RPD finding must either mutate `ROADMAP.md`, a phase spec, mandatory commands, acceptance criteria, or an audit-fix spec.
- Or it must be marked `checked-holds` with evidence.
- Free-floating concerns are invalid.

RPD runs in two places owned by this planner and one place delegated to the generated `/goal` protocol:

1. **Inside `/chip-supergoal`:** `RPD_PLAN_REVIEW` always runs after roadmap/phase specs are written and before the plan is shown to the user.
2. **Inside generated `/goal`:** `RPD_PHASE_REVIEW` runs only for phase specs marked `RPD required: yes` or risky phases.
3. **Inside generated `/goal`:** `RPD_FINAL_REVIEW` always runs after `AUDIT_VERIFY` and before `AUDIT_COMPLETE`.

Risky phases include auth, authorization, payments, secrets, private data, database migrations, destructive data changes, production infra, gateway/routing/cron, recurring bugs, baseline-red recovery, and public launches.

---

## Stage 4 — Decompose into phases

Break the work into **as many phases as the task actually needs** — no fixed count, no upper or lower cap. The right number falls out of the work itself: how many independently verifiable units exist between empty repo (or current state) and "done perfectly." A trivial change might need 2 phases; a typical feature 4–6; a full-stack greenfield app 8–12; a major migration 15+. Read `references/phase-design.md` for how to slice well — the short version:

- Each phase delivers something **verifiable on its own** (it builds, it passes its own tests, you could ship it as a partial increment)
- Phases have **explicit dependencies** (phase 3 depends on 1 and 2)
- The **last phase is always a "Polish & Harden" phase** covering edge cases, error states, security, accessibility, copy, perf — this is how "every aspect is perfect" gets enforced
- For UI work, include a dedicated **visual polish** phase with screenshot/visual evidence requirements
- For brownfield, include an early **safety net** phase if test coverage is thin (add characterization tests before changing behavior)

Each phase has:
- **Name** (5 words max, action-first: "Build auth foundation")
- **Why** (1 sentence)
- **Deliverables** (concrete files/features that will exist when done)
- **Acceptance criteria** (5–10 measurable items)
- **Mandatory commands** (build, typecheck, lint, test that must pass)
- **Evidence required** (what the agent must print into the transcript to prove completion)
- **Dependencies** (which prior phases must be done)

---

## Stage 5 — Write the roadmap and phase specs

Core files, all under `$SUPERGOAL_ROOT/`:

1. **`ROADMAP.md`** — the plan (template at `$SUPERGOAL_DIR/templates/ROADMAP.md`).
2. **`STATE.md`** — live progress file the executor updates per phase (template at `$SUPERGOAL_DIR/templates/STATE.md`).
3. **`RESEARCH.md`** — required when Stage 3 research gates run (template at `$SUPERGOAL_DIR/templates/RESEARCH.md`); omit only with a narrow skipped reason in `THINKING.md` and `ROADMAP.md`.
4. **`phases/phase-N.md`** — one work-spec file per phase (template at `$SUPERGOAL_DIR/templates/phase-goal.txt`, renamed conceptually to "phase spec"). **Any length** — these are read from disk by the executor, not passed to `/goal`, so no char budget.

Each phase spec must include these markers and sections so the agent and evaluator both have stable anchors. `scripts/validate-phase.sh` also requires a `## Work` section, so include it explicitly in every generated phase file:

```
SUPERGOAL_PHASE_START
Phase: <N> of <total> — <name>
Task: <one-line>
Mandatory commands: <list>
Acceptance criteria: <count>
Evidence required: <list>
Depends on phases: <list or "none">
RPD required: yes|no
RPD focus: <security|integration|ux|migration|data-loss|gateway|payments|none>

## Work
<exact execution instructions for this phase>

## Acceptance criteria
<measurable criteria>

## Mandatory commands
<commands>

## Evidence required
<evidence>

[Agent will print SUPERGOAL_PHASE_VERIFY and SUPERGOAL_PHASE_DONE here during execution]
```

Validate each spec with `bash $SUPERGOAL_DIR/scripts/validate-phase.sh .supergoal/phases/phase-N.md` — it confirms the required markers exist. No char budget.

---

## Stage 6 — Plan review & confirmation (hard gate)

Before any `/goal` is dispatched, show the user the full plan and **ask for explicit confirmation**. The chain runs unsupervised once it starts, so this is the last cheap moment to correct course. Skipping this step is a bug.

### Stage 6a — Embedded RPD plan review (runs once, mutates specs)

Plan-time is the cheapest moment to catch expensive bugs. Run one embedded `RPD_PLAN_REVIEW` using the contract in `references/rpd-review-gates.md`.

Use the four personas in sequence, inheriting findings:

1. **Pattern Hunter** — is this a known pattern or repeat failure class?
2. **Gonzo Truth-Seeker** — what unverified assumption is the plan treating as fact?
3. **Devil's Advocate** — how does this plan fail concretely?
4. **Integrator** — what files, services, configs, docs, and user-visible flows can go split-brain?

Mandatory checks:

- Every acceptance criterion must be falsifiable.
- Each phase must be independently verifiable.
- Risky phases must declare `RPD required: yes` and a focused `RPD focus` value.
- The weakest dependency chain must have a mitigation.
- Any unverified assumption that materially changes the plan must become either a user question, a mandatory command, or an acceptance criterion.

**Mutation rule:** every finding must either change `ROADMAP.md`, a `phase-N.md` file, mandatory commands, acceptance criteria, or be marked `checked-holds` with evidence. Do not print decorative concerns.

**Output:** record this block in `THINKING.md` and surface a compact version in the Stage 6 summary:

```text
RPD_PLAN_REVIEW
Pattern Hunter: <finding + evidence + mutation|checked-holds>
Gonzo: <assumption + true|false|unverified + mutation|checked-holds>
Devil's Advocate: <failure mode + mitigation mutation|checked-holds>
Integrator: <touchpoints + split-brain risk + mutation|checked-holds>
Mutations applied: <list or none — checked-holds>
Verdict: ready-for-review | revised-and-ready | blocked-needs-user-input
```


If the verdict is `blocked-needs-user-input`, the plan is **not approval-ready**. Do not offer "Start now" and do not proceed to Stage 7. Ask the blocking question or ask the user to explicitly accept the material assumption, then rerun the affected research/RPD checks and re-show the summary.

If files changed, re-run `validate-phase.sh` on every touched phase spec before showing the plan. Surface the post-RPD version, not the pre-RPD draft.

Honesty check: if `RPD_PLAN_REVIEW` never mutates real weak plans and never marks `checked-holds` with evidence, it is theater and must be tightened.

### Stage 6b — Summary print

Print a scannable summary in this exact shape:

```
✓ Plan ready for review. <N> phases.

Decision:
  - <selected direction>
Why this path:
  - <why this beats alternatives>
Non-goals:
  - <what is explicitly out of scope>
Build-vs-buy:
  - <buy|wrap|fork|copy_pattern|build_fresh|defer + rationale, or skipped with reason>
Research evidence:
  - <skill perplex / docs / GitHub / source evidence, or skipped with reason>
Architect+ lite:
  - <source-of-truth / permission / failure-mode / verification summary, or skipped with reason>

Applied from memory:
  - <memory hit 1>
  - <memory hit 2>
  (or: "none — clean run")

Phases:
  1. <name> — <one-line deliverable>
  2. <name> — <one-line deliverable>
  ...
  N. Polish & Harden — every aspect verified

Stack: <stack> · pkg: <pm> · build/test/lint: <commands>

Key assumptions (correct any that are wrong):
  - <assumption 1>
  - <assumption 2>
  - <assumption 3>

Top risks & mitigations:
  1. <risk> → <mitigation>
  2. <risk> → <mitigation>
  3. <risk> → <mitigation>

RPD_PLAN_REVIEW:
  - <finding/mutation 1, or "checked-holds">
  - <finding 2 (optional)>
  - <finding 3 (optional)>
  (mutations applied in-place if any were flagged)

Artifacts:
  Roadmap: .supergoal/ROADMAP.md
  Progress: .supergoal/STATE.md (auto-updates)
  Phase specs: .supergoal/phases/phase-1..N.md

Once you confirm, I'll print a ready-to-paste `/goal` line. Paste it
once and the chain runs through to completion, with auto-retry and
fix-spec recovery.
```

Then call `AskUserQuestion` with one question, header "Start chain?", offering **concrete revision modes** (not a vague "revise plan"):

- **Start now** — run pre-flight smoke check (Stage 6.5), then print the ready-to-paste `/goal` line; I paste it and the chain runs unsupervised
- **Adjust an assumption** — pick one to change (will re-show plan)
- **Tweak a phase** — change criteria, scope, or commands for a specific phase
- **Restructure phases** — merge, split, add, or remove a phase

Keep options at 4 max. If the user picks any revision option, follow up with a second `AskUserQuestion` to pin down exactly what (e.g., "Which assumption?" with the assumptions listed). Apply the change, update ROADMAP/THINKING/STATE and the affected phase specs, re-run `validate-phase.sh` on each touched spec, then re-show the Stage 6 summary and ask again. Loop until "Start now" or user aborts.

**Wait for the answer.** Do not dispatch `/goal` until the user picks "Start now". Never assume confirmation; never start the chain on silence.

---

## Stage 6.5 — Pre-flight smoke check

After Stage 6 returns "Start now" and **before** printing the `/goal` block, run a single pre-flight pass against the deduplicated mandatory commands. This catches the case where the baseline is already broken (e.g., `pnpm build` red before phase 1 ever ran) — without this, the 3-strike loop would thrash trying to "fix" phase 1 work that was never the cause.

**Procedure:**

1. Read every `phase-N.md` spec and union their `Mandatory commands:` lines into a deduplicated set.
2. Run only commands that are clearly safe pre-flight checks (build/test/lint/typecheck/static smoke). Do not run deploy, migration, write-heavy, network-mutating, payment, credential, destructive, or production commands in `/chip-supergoal`; move those to the future `/goal` phase or require explicit user approval. Capture exit code and last ~5 lines for every command that is run, and list skipped side-effectful commands separately.
3. **If all green:**
   - Append a `Notable events` line to `.supergoal/STATE.md`: `<DATE> — Pre-flight green: <N> commands clean.`
   - Print `PREFLIGHT_GREEN` with the per-command summary.
   - Proceed to Stage 7.
4. **If any red:**
   - Append `<DATE> — Pre-flight red: <cmd> exited <code>.` to `STATE.md`.
   - Print `PREFLIGHT_RED` with the failing command, exit code, last ~5 lines.
   - Re-show the Stage 6 summary with the failures surfaced and a revised menu (still 4 options to stay under the `AskUserQuestion` ceiling): **"Skip pre-flight, dispatch anyway"** (replaces "Start now" — the user might know the baseline is intentionally broken, e.g., phase 1's whole job is to fix it) / **"Adjust an assumption"** / **"Tweak a phase"** / **"Restructure phases"**. If "Skip pre-flight, dispatch anyway" → log `<DATE> — Pre-flight bypassed by user.` and proceed to Stage 7. Any other choice loops back through the normal Stage 6 revision flow; after the user finishes revising, Stage 6.5 re-runs.

**Honesty test:** real command run, real exit code. The "skip anyway" option keeps the user in control — no forced re-plan if the baseline being red is the point.

### Baseline-red triage pitfall

When the user asks to add a baseline-fix phase after `PREFLIGHT_RED`, do not patch only the first visible failing file and call the baseline fixed. Re-run the failing command and classify every remaining failure before dispatch:

- `phase-created-missing` — files expected to be created by later phases; OK to keep red until that phase.
- `unrelated-existing-baseline` — repo-wide historical failures outside the requested surface; record explicitly in `STATE.md` and avoid making them acceptance gates unless the user expands scope.
- `owned-baseline-regression` — failures inside the requested surface or required verifier; add/adjust Phase 0 until the verifier is green or the user explicitly approves bypass.

If direct `tsc --noEmit` is red but the project’s CI-equivalent `npm run build` is green, prefer the repo’s real CI/build gate for completion claims and state the residual direct-TS baseline separately.

When pre-flight is red on an owned baseline problem inside the requested surface, add an explicit baseline-repair phase before dispatch instead of burying the failure in Phase 1. Practical pattern: insert `Phase 0 — Baseline test repair`, shift existing phases forward, validate every `phase-N.md`, rerun the failing minimal command, then ask the user whether to bypass pre-flight because Phase 0 now owns the red baseline. Record the bypass in `STATE.md`. Do not claim pre-flight green unless the command actually passed.

---

## Stage 7 — Hand off the `/goal` dispatch (one paste)

Slash commands on both Claude Code and Codex fire **only from user input** — agent message text is never parsed as a command. So Stage 7 is not an automatic dispatch; it's an honest one-paste handoff. After explicit "Start now" in Stage 6:

**Dispatch path discipline:** default to repo-relative `.supergoal/...` paths and tell the user to start `/goal` from the project root. Do not print absolute local paths by default because they can leak workstation or account details. If the current client cannot run from the project root and absolute paths are genuinely required, ask for explicit confirmation before emitting them, then verify the target root exists and every phase spec validates.

**One confirmation means one confirmation:** if pre-flight is red and the user explicitly chooses "Skip pre-flight, dispatch anyway", do not ask the same question again. Log the bypass in `STATE.md`, prepare Stage 7 artifacts, and print the ready-to-paste `/goal` line immediately.

1. Update `STATE.md`: `Status: READY_TO_DISPATCH`, `Current phase: <first phase number>`, and **capture the baseline ref** — set `Baseline ref:` to the output of `git rev-parse HEAD 2>/dev/null || echo "no-git"`. Use whatever numbering the phase files actually use (`phase-0.md` starts at 0; `phase-1.md` starts at 1). Do not hard-code `Current phase: 1` when the plan is zero-indexed. The audit reads the baseline to diff deliverables against the working tree.
2. Copy `$SUPERGOAL_DIR/templates/PROTOCOL.md` to `.supergoal/PROTOCOL.md` (the operating manual the executing agent reads at the start of the `/goal` session), and copy `$SUPERGOAL_DIR/scripts/repo-state.sh` to `.supergoal/repo-state.sh` (the complete-working-tree comparison helper the cleanliness + deliverable checks invoke; strategy in `references/repo-state-comparison.md`).
3. Verify each `.supergoal/phases/phase-N.md` exists; run `bash $SUPERGOAL_DIR/scripts/validate-phase.sh .supergoal/phases/phase-<N>.md` on each.
4. **Client-safe dispatch UX:** do not put the `/goal` command in a fenced code block. Prefer this two-message shape when the client supports replies:

   a. Send the long goal body as a normal assistant message prefixed exactly with `SUPERGOAL_GOAL_BODY:` and no markdown fence.

   b. Immediately after it, send the instruction:

   > Reply to the `SUPERGOAL_GOAL_BODY` message with exactly `/goal`. Do not copy the long text.

   c. Also include a fallback plain-text one-liner for non-reply clients, outside code fences and labeled `Fallback plain-text line:`. The line must begin with `/goal "..."` and use repo-relative paths unless the user explicitly approved absolute paths.

5. If the user sends only the quoted body without `/goal`, treat it as a dispatch UX failure. Do not scold or make them copy the same long body again. Re-send the short reply method only: `Reply to the SUPERGOAL_GOAL_BODY message with /goal`.

6. If the user later pastes only the quoted condition body without the leading `/goal`, treat that as a failed dispatch UX, not as an automatic command. Reply briefly that the leading slash is required and re-print the one-line command unless the current platform has already started a goal/continuation wrapper.

7. **Copy formatting pitfall:** chat clients can copy the wrong region or omit the leading slash from long copied text. The primary mitigation is the reply shortcut. Only use the long plain-text `/goal "..."` fallback when reply mode is impossible. If a goal-wrapper is already active despite the formatting, continue executing instead of looping on paste instructions.

8. **Standing-goal continuation pitfall:** If the next user message arrives as a host-generated wrapper such as `[Continuing toward your standing goal]` or explicitly says `Continue working toward this goal`, the `/goal` wrapper is already active. Do not re-print paste instructions or ask for `/goal` again. Read `STATE.md`, continue from the current phase, run the mandatory commands, and emit the required `SUPERGOAL_PHASE_VERIFY`, `SUPERGOAL_PHASE_DONE`, `AUDIT_COMPLETE`, and `SUPERGOAL_RUN_COMPLETE` markers in the visible transcript when earned.

9. **Stop.** Do not generate any further output. The chip-supergoal invocation ends here. The user's paste begins the autonomous run under a fresh `/goal` session, which reads `PROTOCOL.md`, `ROADMAP.md`, `STATE.md`, and the phase specs from disk and runs the loop documented in the next sections.

Once `/goal` is active (you'll see the `◎ /goal active` indicator on Claude Code), the per-turn evaluator keeps the agent working until the end-state condition holds. On Codex, the auto-continuation loop does the same. The agent inside the `/goal` session has zero special context from the chip-supergoal invocation; everything it needs is in the files on disk — by design.

---

## Phase execution loop (inside the single `/goal` session)

The agent's loop, repeated until `SUPERGOAL_RUN_COMPLETE`:

1. Read `STATE.md` → find current phase N.
2. Read `.supergoal/phases/phase-N.md` → full work spec.
3. Print `SUPERGOAL_PHASE_START` block with values from the spec.
4. Do the work; run mandatory commands; surface evidence into the transcript.
5. Print `SUPERGOAL_PHASE_VERIFY` block (every criterion `pass|fail` + engineering checks + **cleanliness checks** — grep `bash .supergoal/repo-state.sh added-lines <Baseline ref>` (complete added/new lines since baseline, **including uncommitted and untracked work**) for stack-specific debug prints, session TODO/FIXME, dead imports; non-zero counts trigger 3-strike unless the phase spec declares `Cleanliness override:`).
6. **RPD phase review** — if the phase spec declares `RPD required: yes` or touches a risky area, run `RPD_PHASE_REVIEW` from `.supergoal/PROTOCOL.md`. Findings must mutate the work/spec or be marked `checked-holds` with evidence.
7. **Memory writeback check** — anything non-obvious learned? If yes, write a memory file under the detected MEM_DIR; print `MEMORY_SAVED: <name>` (or `MEMORY_SAVED: none`).
8. Print `SUPERGOAL_PHASE_DONE`, update `STATE.md` (mark phase N complete, set Current phase = N+1, append events line).
9. **User-interrupt check** — if a new user message has arrived since the last turn, pause and address it before continuing.
10. If N < total: loop to step 1 for phase N+1.
11. If N == total: do **not** print `SUPERGOAL_RUN_COMPLETE` yet. Run the **Final audit** (next section). Only after `AUDIT_COMPLETE`, print `SUPERGOAL_RUN_COMPLETE` with a 5-line summary. The `/goal` condition is now satisfied and clears.

### Final audit (Stage 10 of the loop — before completion)

Per-phase VERIFY blocks are self-reports. A phase can pass its own check while a later phase silently breaks it (a type added in phase 2 violated in phase 5; tests that passed mid-run break after refactor; etc.). The audit closes that loophole by re-validating against the **original** ROADMAP.md, not against the run's own self-reports.

The audit runs once after the final phase. If it finds gaps, it writes a focused fix spec and re-runs itself. Cap at 3 audit rounds; on the 3rd round's failure, `AUDIT_HANDOFF`.

**Audit steps:**

1. Print `AUDIT_START` with round number, total phase count, criteria count, and the deduplicated set of mandatory commands to re-run.
2. **Re-read `ROADMAP.md`** — pull every phase's acceptance criteria fresh from the original plan. Do not trust prior VERIFY summaries.
3. **Phase completeness check** — scan the transcript: does every phase 1..N have a `SUPERGOAL_PHASE_DONE` block? Surface any missing.
4. **Re-run aggregated mandatory commands** once each (build, typecheck, lint, full test suite). Surface last ~10 lines + exit code for each. Any non-zero exit → an `AUDIT_GAP`.
5. **Spot-check verifiable criteria** — for each acceptance criterion across all phases:
   - "File X exists" / "Function Y exported" / "Config key Z set" / "No `console.log` in app code" → re-check via `ls`/`grep`/`cat`.
   - "Screenshot showed X" / "Manual smoke test passed" / other non-deterministic checks → mark `trust-prior-verify`, do not re-run.
5b. **Deliverable check** — for each phase block in `ROADMAP.md`, parse the `**Deliverables:**` bullets. For each bullet that names a file path or glob, run `bash .supergoal/repo-state.sh deliverable <Baseline ref> "<path>"` — it checks the **complete working tree** (committed + staged + unstaged + deleted) against the baseline and detects untracked new files separately. `missing`/`deleted` (exit 1), invalid baseline (exit 2), or unchanged pre-existing (exit 3) → `AUDIT_GAP: phase <N> deliverable "<bullet>" not proven as delivered by this run`, unless the roadmap explicitly marks that deliverable as pre-existing / verification-only. Repository ground-truth — catches "agent said done but didn't ship," even when the run never committed. Strategy: `references/repo-state-comparison.md`.
6. Print `AUDIT_VERIFY` block:
   - Per-phase status (DONE present or missing)
   - Each mandatory command's exit code
   - Each criterion's `pass | fail | trust-prior-verify` with evidence
   - `Deliverables:` block from step 5b — `phase N / "<bullet>": present | missing`
7. **If any gaps:**
   - Print `AUDIT_GAPS` with the list.
   - Write `.supergoal/phases/audit-fix-<round>.md` — a focused fix spec targeting **only** the failing criteria, with the original phase's VERIFY as the success gate, scope creep forbidden.
   - Execute the fix spec inline (same agent, same `/goal`, same 3-strike per-criterion protocol from regular phases).
   - On fix success: loop back to step 1 (round + 1). On 3rd round's failure: print `AUDIT_HANDOFF` (full gap history + suggested next move), update `STATE.md` to `BLOCKED`, stop. Do not print `SUPERGOAL_RUN_COMPLETE`.
8. **If clean:**
   - Compute `audit coverage` = `re_verified / (re_verified + trust_prior)` as a percentage (where `re_verified` = criteria with `pass` + deliverables marked `present`; `trust_prior` = criteria marked `trust-prior-verify`).
   - Print `AUDIT_COMPLETE` with phases verified, commands re-run clean, criteria pass/trust-prior counts, deliverables present/missing counts, and the audit coverage %.
   - Print `SUPERGOAL_RUN_COMPLETE`. If `trust_prior / (re_verified + trust_prior)` > 30%, prepend an honesty banner: `⚠ Audit coverage: X re-verified, Y trust-prior (Z%). Eyeball UI/UX before merging.` Below 30%, print the plain coverage line without the warning prefix.

The audit is the difference between "every phase passed its own self-report" and "the final state matches the plan I originally approved." That is the bar.

### Failure recovery (3-strike, built into the protocol)

**First failure of any criterion:**
1. Print `FAILURE_PROBE` (what failed, what tried, root-cause hypothesis).
2. Append probe to `STATE.md` failure log.
3. **Auto-retry the same phase once** with the probe injected as feedback. Do not advance.

**Second failure (auto-retry also failed):**
1. Print `FAILURE_ESCALATE`.
2. Write a focused **fix spec** at `.supergoal/phases/phase-N.fix.md` (targets only the failing criterion, no scope creep).
3. Execute the fix spec inline (same agent, same `/goal` — no new dispatch). On success, re-run the original phase's VERIFY block; on pass, advance to N+1.

**Third failure (fix spec also failed):**
1. Print `FAILURE_HANDOFF` with: failing criterion, full probe history, three things tried, suggested next move.
2. Update `STATE.md`: `Status: BLOCKED`. The user takes the wheel.
3. The `/goal` condition will not be satisfied; the host's evaluator will keep evaluating but the agent should stop attempting and surface the handoff clearly.

This recovers from flaky envs, simple typos, and missed deps automatically. Only real blockers escalate.

### Mid-run interruption

If the user sends any message during the `/goal` run, the agent pauses at the next phase boundary, addresses the message, and asks before resuming. Phase boundaries are after `SUPERGOAL_PHASE_DONE` and before reading the next phase spec.

---

## Memory writeback rules (referenced by PROTOCOL.md)

Memory is load-bearing. Future runs start smarter because past runs wrote down what they learned. The phase execution loop's step 6 references these rules.

**At each phase boundary**, ask: "Did this phase surface anything a future chip-supergoal run on a similar task would benefit from knowing?"

Worth saving:
- A library API quirk that wasn't in the docs
- A user preference confirmed during this run ("user accepted dark-only UI without pushback")
- A project-level fact ("auth lives in `lib/auth/` not `app/api/auth/`")
- A failure pattern + fix ("X always fails on first build; second build works")

Write the memory file under the detected MEM_DIR using the standard `name` / `description` / `metadata.type` frontmatter. Link it from `MEMORY.md`. Print `MEMORY_SAVED: <name>` to the transcript. If nothing non-obvious this phase: print `MEMORY_SAVED: none`.

**At the final phase**, always write a `project_<slug>.md` memory pointing at the new/changed project (location, stack, status, ROADMAP link). Guarantees future chip-supergoal runs on the same project start from the latest state.

**Never save:** secrets, transient task details, ephemeral state. Bar is "useful to a future run." When in doubt, skip.

---

## Operating principles (read every run)

- **One `/goal`, short condition.** `/goal` takes an end-state, not a task body. Long content lives in files the agent reads from disk. This is the natural shape on both Claude Code and Codex.
- **Frictionless is the goal.** Memory + prompt + recon should answer most questions. Zero clarifying questions on well-described tasks is a win.
- **Adapt to available tools.** Detect what's there (Context7, WebSearch, MCPs, skills). Use what's available; degrade gracefully without it. Never hard-require a tool that might not be present.
- **Memory is load-bearing.** Preload at Stage 0, surface as "Applied from memory: …" in Stage 1, write back at every phase boundary.
- **"Perfect" is not a stopping condition — criteria are.** Translate every "perfect" into observable, falsifiable criteria.
- **Two human gates, no more.** Clarifying gaps (Stage 1 — walk the full category checklist for greenfield in batches of up to 4 until all material info is gathered; often zero for brownfield) and plan review (Stage 6). Between and after, autonomous.
- **The loop self-heals.** Auto-retry once, then write a fix spec and execute inline, then escalate. Don't stop on first failure.
- **The evaluator only sees the transcript.** Phase specs require the agent to surface their contract — START, commands, evidence, VERIFY, DONE — into the conversation, not just point at files.
- **Each phase is independently shippable** in spirit. If phase 3 can't build/test on its own, the slicing is wrong.
- **The Polish & Harden phase is mandatory.** It's how "every aspect is perfect" gets enforced.

---

## Hermes compatibility notes

- **Skill directory detection:** if the standard Claude/Codex snippet cannot find the skill directory, include the Hermes-native path too: `$HOME/.hermes/skills/chip-supergoal/SKILL.md`. The skill is multi-file; a single raw `SKILL.md` install is not enough.
- **Pre-flight interpretation:** chip-supergoal pre-flight can be red because a phase deliberately creates files referenced by later mandatory commands (for example a new `rentals-admin.test.ts` that Phase 1 will create). Classify these as expected phase-created-file failures, not baseline blockers. Separate them from unrelated baseline failures such as an existing TypeScript error elsewhere.
- **Baseline red handling:** if baseline is red on unrelated files, offer the user two concrete choices: add a Phase 0 to fix the baseline, or dispatch anyway and require later phases/final audit to prove the failure is pre-existing and unrelated. Do not silently start after a red pre-flight.

## When to deviate from the workflow

- **Very small task** (< 1 hour of work, single file): tell the user this doesn't need chip-supergoal, suggest just doing it. Don't force the machinery.
- **The user pushes back on a phase during intake**: collapse, re-plan, continue.
- **Mid-run interruption**: if the user stops the run and asks for a change, update the affected `.supergoal/phases/phase-N.md` spec, run `validate-phase.sh` on it, then ask the user to resume (they can re-dispatch the same `/goal` or just say "continue"). No need to restart phase 1.

---

## Output Contract

A successful `/chip-supergoal` planning run produces:

- `.supergoal/THINKING.md` with goals, constraints, risks, dependencies, applied memory, available tools, and `RPD_PLAN_REVIEW`.
- `.supergoal/RESEARCH.md` when research is required, recording skill `perplex` usage, queries, sources, existing-solution candidates, build-vs-buy verdict, planning implications, and unverified assumptions.
- `.supergoal/ROADMAP.md` with decision, why this path, non-goals, build-vs-buy verdict, research evidence, Architect+ lite summary when applicable, phases, dependencies, assumptions, mandatory commands, and risky-phase/RPD gate summary.
- `.supergoal/STATE.md` initialized for the future `/goal` session.
- `.supergoal/phases/phase-N.md` files with falsifiable criteria, mandatory commands, evidence requirements, dependencies, and `RPD required` / `RPD focus` metadata.
- `.supergoal/PROTOCOL.md` copied from `templates/PROTOCOL.md`, including embedded `RPD_PHASE_REVIEW` and `RPD_FINAL_REVIEW` gates for the future `/goal` runner.
- A CLI/client-safe `/goal` handoff using the `SUPERGOAL_GOAL_BODY:` reply shortcut when available.

The skill itself is plan-only. It must not claim that execution completed; only the later `/goal` session can earn `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE`.

## Quick Test Checklist

- [ ] `skill_view("chip-supergoal")` loads this skill and shows `references/rpd-review-gates.md`.
- [ ] A generated phase spec validates with `scripts/validate-phase.sh` and includes `RPD required:` plus `RPD focus:`.
- [ ] Stage 3 loads/uses skill `perplex` first when available for current research; generic `web_search` is only fallback.
- [ ] Stage 6 summary includes Decision / Why this path / Non-goals / Build-vs-buy / Research evidence / Architect+ lite.
- [ ] Stage 6 summary includes an `RPD_PLAN_REVIEW` block, not the old self-critique-only block.
- [ ] `.supergoal/PROTOCOL.md` includes `RPD_PHASE_REVIEW` and `RPD_FINAL_REVIEW` without requiring any external `/rpd` skill.
- [ ] Public package scan finds no secrets, credentials, chat IDs, local runtime state, or private infrastructure details.
- [ ] The handoff remains plan-only: `/chip-supergoal` prints a `/goal` body; it does not execute project phases itself.

## Done Criteria

- [ ] Frontmatter has `name: chip-supergoal` and a trigger-rich description.
- [ ] RPD behavior is embedded in this package via `references/rpd-review-gates.md` and `templates/PROTOCOL.md`.
- [ ] `SKILL.md` does not require loading `chip/rpd`, `/rpd`, or any private operator skill.
- [ ] All phase specs contain measurable acceptance criteria, mandatory commands, evidence requirements, and RPD metadata.
- [ ] Substantial/risky plans include source-of-truth boundary, permission matrix, failure-mode matrix, and verification strategy, or a narrow skip reason.
- [ ] Plan review mutates weak specs or records `checked-holds` with evidence.
- [ ] Public repo contents are sanitized and installable as a standalone Hermes skill.

---

## Reference files

- `references/architect-plus-lite.md` — lightweight contract-first planning gate for substantial/risky plans
- `references/research-before-design.md` — research-before-design gate with skill `perplex` priority, RESEARCH.md schema, and existing-solutions gate
- `references/rpd-review-gates.md` — embedded RPD mutation-gate contract used by plan review and generated `/goal` protocol
- `references/planning-depth.md` — what makes a plan deep enough to deserve "Super"
- `references/phase-design.md` — how to slice phases that auto-chain cleanly
- `references/goal-format.md` — what `/goal` is on Claude Code + Codex, chip-supergoal's single-`/goal` shape, required transcript blocks

## Scripts

- `scripts/detect-stack.sh` — identifies language, package manager, framework, build/test/lint commands (brownfield)
- `scripts/detect-env.sh` — greenfield environment recon
- `scripts/summarize-repo.sh` — compressed repo map (brownfield)
- `scripts/validate-phase.sh` — checks a phase spec has exact required sections, metadata, RPD fields, and non-placeholder content
- `scripts/test.sh` — public package regression suite for install layout, privacy scan, phase validation, and repo-state audit guards

## Templates

- `templates/ROADMAP.md` — phase plan with dependencies
- `templates/STATE.md` — live progress file
- `templates/RESEARCH.md` — research-before-design record schema
- `templates/phase-goal.txt` — phase spec skeleton (work, criteria, evidence, mandatory commands)
- `templates/PROTOCOL.md` — phase execution loop, failure recovery, memory writeback (copied to `.supergoal/PROTOCOL.md` at dispatch)
