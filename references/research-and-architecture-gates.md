# Research and architecture gates

Use these gates before writing phase specs when external facts or architectural choices materially shape the plan.

## Research trigger

Run research for greenfield systems, unfamiliar domains, current SDK/API behavior, auth/payments/security/compliance, major migrations/refactors, build-vs-buy uncertainty, or explicit requests for best practice/current practice.

Use skill-first research when available. Prefer the `perplex` skill/provider first for broad current research, then official docs/current source for SDK facts. Generic web search is fallback, not equivalent to dedicated research skills.

## Executable research provider gate

Contracts may set `compatibility.research_gate`:

```json
{
  "required": true,
  "status": "satisfied",
  "provider": "perplex",
  "query": "current facts needed before planning",
  "summary": "What the research changed in the plan.",
  "sources": [{"title": "Source title", "url": "https://example.com", "provider": "perplex"}],
  "planning_implications": ["Phase/spec/acceptance change caused by research"]
}
```

Strict validation blocks required research unless:

- `status` is `satisfied`;
- `provider` is supported (`perplex`, `official-docs`, `context7`, `web`, `manual`);
- non-Perplex providers include `provider_unavailable_reason`;
- at least one source has `title` and `url`/`locator`;
- `summary` is substantive.

Compile emits both `RESEARCH.md` and `reports/research.json`; `validate-package` treats both as generated artifacts and detects drift.

### Grounding integrity for routed research

Requesting `model=sonar` is not proof that Perplexity research actually ran. Inspect the returned route/model, structured citations, and source URLs before setting `provider: perplex`:

- if the gateway routes to a generic/non-search model, says it lacks live search, or returns unsupported prose without grounded citations, do **not** mint a fake `perplex` source merely to satisfy validation;
- record the Perplex attempt as unavailable/ungrounded, switch the contract provider to `official-docs`, `context7`, `web`, or `manual`, and include `provider_unavailable_reason`;
- directly extract the authoritative URLs and let those sources—not the search prose—drive planning implications;
- when search prose and the official page disagree, the official endpoint contract wins and the discrepancy becomes a phase/test mutation.

A research gate that passes schema by mislabeling an ungrounded gateway fallback is red, even if the final recommendation happens to be correct.

## Existing-solutions gate

Search libraries, SaaS, OSS repos, package registries, or reference implementations when build-vs-buy matters. Decide one of:

- `buy`
- `wrap`
- `fork`
- `copy_pattern`
- `build_fresh`
- `defer`

Record rationale in `RESEARCH.md` and `ROADMAP.md`.

## Architect+ lite

For substantial or risky work, name:

- source of truth boundaries
- permissions matrix
- failure modes and rollback/recovery
- verification strategy
- overengineering budget for new layers/fallbacks/shims/agents

A plan is not approval-ready if missing facts materially affect security, payments, auth, compliance, SDK choice, or build-vs-buy, unless the user explicitly accepts the assumption.
