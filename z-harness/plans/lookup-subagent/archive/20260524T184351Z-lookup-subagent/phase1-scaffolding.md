# Phase 1 Scaffolding — lookup-subagent

## Topic

Should we build a lookup subagent that handles repetitive external/domain information retrieval (e.g. querying Kalshi for tickers, exploring weather markets, fetching live web docs for libraries outside training cutoff) so the main agent thread does not burn tokens on HTTP responses, paginated API output, HTML, and irrelevant fields? Should it be qt-bot-specific or generalized as a z-harness primitive? What shape should it take?

## User-provided context

The user constantly needs to look up repetitive external/domain information from the main agent thread. Examples: querying Kalshi for a new ticker ("what is the ticker for Chicago daily high temperature?"); exploring a weather-market series; fetching docs / understanding tools or APIs outside training cutoff that need web. Each task, run from main, burns tokens on HTTP, paginated API responses, web HTML, irrelevant fields. User wants a dedicated lookup subagent that does the exploration in fresh context and returns a tight synthesis (e.g. "ticker is KXHIGHCHI-26MAY24-T70, expires Fri 4pm CT, payout schema binary"). Could be qt-bot-specific OR generalized.

Existing z-harness landscape:
- doc-fetcher (Haiku): reads internal docs/llm/ JSON, ≤8 Reads, ≤2 KB synthesis. INTERNAL ONLY — never network.
- remote-runner (Haiku): read-only DB/log queries over SSH; refuses write verbs; returns raw stdout for orchestrator to interpret.
- consultant-primary/secondary (Sonnet): proxy to Gemini/Codex LLMs. No domain APIs.

Gap: no external-lookup / web-fetch / domain-API-query subagent exists. Domain tools (kalshi, weather APIs) live in target repos (qt-bot) as skills, not in z-harness.

qt-bot is a separate repo (~/dev/qt-bot/). z-harness is repo-agnostic, gets exported into target repos.

Model tier rules: Haiku = cheap CLI/lookup wrappers; Sonnet = implementation; Opus = retries only.

Two-tier docs precedent: never read INDEX.json from main thread, always dispatch doc-fetcher. The user is implicitly extending the same principle to external lookup.

Constraints: subagents declare explicit model + tool whitelist; z-harness stays repo-agnostic; output small + cited; dispatch explicit (no auto-routing).

## Doc-fetcher synthesis

### agents

The z-harness agent layer consists of doc-fetcher (Haiku, read-only internal docs), remote-runner (Haiku, read-only SSH DB/log queries), codex-consultant (Sonnet, Codex proxy), gemini-consultant (Sonnet, Gemini proxy), implementer (Sonnet, code generation), auditor, mr-reviewer, and supporting agents. Each agent declares an explicit model tier and tool whitelist.

**Key files:**
- agents/doc-fetcher.md:1 — Haiku; reads docs/llm/INDEX.json + per-concept JSONs; INTERNAL ONLY, no network; returns <=2KB synthesis
- agents/remote-runner.md:1 — Haiku; read-only SSH queries (DB, logs, state files); refuses write verbs
- agents/codex-consultant.md:1 — Sonnet proxy to Codex CLI; supports brainstorm, plan-review, debug, research-review modes
- agents/gemini-consultant.md:1 — Sonnet proxy to Gemini CLI; same mode set as codex-consultant

**Invariants / gotchas:** No agent reads INDEX.json from the main thread — always dispatch doc-fetcher. Model tiers: Haiku=cheap CLI wrappers, Sonnet=implementation, Opus=retries only. Every agent declares explicit tools and model.

**Depends on:** scripts (log-event.sh, version.sh)
**Consumed by:** all z-harness skills (z-plan, z-implement-next, z-implement-all, z-brainstorm, etc.)

### skills

Skills are slash commands exported into target repos. Each skill orchestrates subagents. The z-brainstorm skill dispatches three ideators (Claude/Codex/Gemini) in parallel. No skill currently dispatches an external-lookup subagent — the gap is acknowledged.

**Key files:**
- skills/z-brainstorm/SKILL.md:1 — orchestrates parallel ideator dispatch + anti-bias synthesis
- skills/z-plan/SKILL.md:1 — rigorous planning pipeline with Gemini+Codex cross-consult

**Invariants / gotchas:** z-harness must stay repo-agnostic; domain tools live in target repos (qt-bot), not z-harness core.

**Depends on:** agents, scripts
**Consumed by:** target repo exports (qt-bot, etc.)

## Explore synthesis

(skipped — Z_HARNESS_BRAINSTORM_EXPLORE not set)

## RESEARCH.md

(none found)

## Input hash

0cfbf3cfd75a2c4b
