# Human20 SEO/AEO/GEO SuperGoal planning

Use when Chip asks for SEO, AEO, GEO, AI-search readiness, citation readiness, or a SuperGoal for `human20.app` discoverability.

Load `human20-app`, `human20-prod-verification`, `chip-url-first` when a benchmark URL is supplied, and this SuperGoal skill. The Human20 policy sources are:

- `human20-app/references/ai-native-seo-aeo.md`
- `human20-app/references/ai-native-seo-audit.md`
- `human20-prod-verification/references/seo-aeo-geo-phased-upgrade-verification.md`

## Class-level workflow

1. Treat the mission as a live readiness audit and evidence-backed upgrade, not a generic SEO explainer or post draft unless Chip asks for copy.
2. If Chip supplies a GEO guide, open it first, extract its claims, then verify crawler/schema/measurement behavior against current official provider and Search docs. Do not copy a third-party robots block blindly.
3. Start with public evidence from `https://human20.app`: `/`, `/about`, `/faq`, `/articles`, representative article, `/skills`, `/lessons`, `/agent`, `/launch`, `/sitemap.xml`, `/robots.txt`, `/llms.txt`, discovery endpoints, and `/release.json`.
4. Extract status/final URL, title, description, canonical, H1/H2, internal links, OG/Twitter media, rendered JSON-LD types/ids/references, visible/schema/sitemap dates, text/citation blocks, private-path leaks, and route weight/performance flags.
5. Run a crawler-purpose matrix against root, robots, representative article, and asset:
   - Search: `Googlebot`, `OAI-SearchBot`, `Claude-SearchBot`, `PerplexityBot`
   - Training policy: `GPTBot`, `ClaudeBot`
   - User fetch: `ChatGPT-User`, `Claude-User`, `Perplexity-User`
   - Treat spoofed UA curl as a WAF/header test; production attribution/allowlisting requires official current IP ranges plus logs.
6. Score separately:
   - classic SEO: crawl/index eligibility, canonicals, internal links, helpful content, page experience, sitemap;
   - AEO: direct-first answers, self-contained snippets, factual/command/comparison extractability, intent coverage;
   - GEO: coherent entity/author graph, public authority, non-commodity/original evidence, external mentions, citation sampling;
   - measurement confidence: GSC/Yandex/log/analytics/citation baseline availability.
7. Correct common myths in the package:
   - Google AI Overviews/AI Mode use ordinary Search eligibility and `Googlebot`; `Google-Extended` is not their inclusion control.
   - `GPTBot`/`ClaudeBot` are training crawlers, not search crawlers.
   - `Content-Signal` has limited adoption and is not a ranking/access guarantee.
   - Google says `llms.txt` has no positive or negative Search effect.
   - FAQ rich results were removed in 2026; How-To rich results are no longer shown. Semantic Schema.org markup may remain, but never promise those SERP features.
   - Schema, crawler access, IndexNow receipt, and manual AI citation samples do not guarantee ranking or citation.
8. If a Telegram source supplies author/profile facts, fetch the exact message first. If inaccessible, mark a source-lock and use only public-safe facts with provenance.

## Required SuperGoal phases

Compile enough phases to cover:

1. **Source lock + direct baseline** — official docs, live release, route crawl, crawler matrix, sitemap/private leak, current measurement access.
2. **Deterministic audit tooling** — rendered crawl, recursive JSON-LD graph/reference check, date mismatch test, citation-ready content checklist, crawler matrix output.
3. **Crawler/WAF/robots policy** — explicit search/training/user-fetch decisions; UA+IP/log verification; no blanket AI-bot rule.
4. **Entity/schema foundation** — stable `@id` graph, author/publisher/page links, visible-content parity, supported validator flow.
5. **Date integrity** — immutable published date, material-only modified date, visible/schema/sitemap consistency.
6. **Homepage/about AEO/entity pass** — direct answers and visible evidence backing Organization/Person graph.
7. **Pillar/knowledge and comparison/use-case pages** — only query-supported pages; citation-ready facts, original evidence, no thin-page factory.
8. **Article/skills/agent hardening** — answer-first blocks, authorship, internal links, metadata/previews, content-specific dates.
9. **Discovery/submission** — sitemap, robots, optional agent-readable `llms.txt` as navigation only, safe IndexNow changed-URL flow.
10. **Measurement baseline** — GSC/Yandex when accessible, verified bot logs, analytics/referrers, fixed monthly citation sample.
11. **Local gates** — lint/test/build, local production server, full rendered audit, representative external schema validation.
12. **Fresh prod integration + RF deploy + live smoke** — exact SHA, canonical deploy, public crawl, crawler matrix, graph/date/private-boundary proof, final report.

Merge phases only when the resulting acceptance criteria remain independently provable. Do not hide account/WAF/production work inside a generic “SEO polish” phase.

## Acceptance rules

- Broad edits start with a representative slice and scale only after gates pass.
- Schema uses stable connected ids and matches visible public text. One graph is preferred; coherent multiple blocks are acceptable.
- `datePublished` remains the first-publication timestamp; `dateModified` moves only for material visible content changes. Build time or metadata touch is not freshness.
- Priority pages contain at least one self-contained, sourceable answer block; volatile claims have source/owner/review date.
- `llms.txt`, FAQ/HowTo schema, IndexNow response, and crawler `200` are reported with their exact limited meaning.
- Production deploys use the RF SEO/AEO deploy reference: fresh `origin/prod`, preserve prod-only fixes, full local gates, canonical deploy, `/release.json` SHA, live evidence.
- Preserve visible `Человек 2.0`, exact `Среда внедрения ИИ`, and existing hero/features unless explicitly changed.

## Output shape for Chip

Lead with a short evidence-based scorecard:

```text
SEO: x/10
AEO: x/10
GEO: x/10
Measurement confidence: x/10

➊ что уже готово
➋ что реально мешает
➌ какие советы из источника не переносим
➍ что делать первым
```

For a SuperGoal, state explicitly that the planner wrote files but did not change/deploy the site. The later `/goal` executor must earn completion through local gates, exact RF SHA, live crawl/crawler/schema/date/private-boundary proof, and final audit.
