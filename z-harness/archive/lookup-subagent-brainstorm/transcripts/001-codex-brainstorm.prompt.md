MODE: brainstorm

TOPIC: Should we build a "lookup subagent" that handles repetitive external/domain information retrieval (e.g. querying Kalshi for tickers, exploring weather markets, fetching live web docs for libraries outside training cutoff) so the main agent thread doesn't burn tokens on HTTP responses, paginated API output, HTML, and irrelevant fields? Should it be qt-bot-specific or generalized as a z-harness primitive? What shape should it take?

## Scaffolding

The user constantly needs to look up repetitive external/domain information from the main agent thread. Examples:
- Querying Kalshi API for a new ticker ("what is the ticker for Chicago daily high temperature?")
- Exploring a weather-market series (current price, strike price, contract details, expiration)
- Fetching docs / understanding tools or APIs outside training cutoff that need web (live library API docs, changes since Feb 2025 cutoff)
Each task, run from main, burns tokens on HTTP, paginated API responses, web HTML, irrelevant fields. 

User wants a dedicated lookup subagent that does the exploration in fresh context and returns a tight synthesis (e.g. "ticker is KXHIGHCHI-26MAY24-T70, expires Fri 4pm CT, payout schema binary").

## Existing z-harness subagent landscape:
- **doc-fetcher** (Haiku): reads internal `docs/llm/` JSON, ≤8 Reads, ≤2 KB synthesis. INTERNAL ONLY — never network.
- **remote-runner** (Haiku): read-only DB/log queries over SSH; refuses write verbs; returns raw stdout for orchestrator to interpret.
- **consultant-primary/secondary** (Sonnet): proxy to Gemini/Codex LLMs. No domain APIs.

The gap: no external-lookup / web-fetch / domain-API-query subagent exists. Domain tools (kalshi client library, weather APIs) live in target repos (qt-bot) as skills, not in z-harness.

## Key architectural facts:
- **qt-bot is a separate repo** (`~/dev/qt-bot/`). z-harness is repo-agnostic, gets exported into target repos.
- **Model tier rules**: Haiku = cheap CLI/lookup wrappers; Sonnet = implementation; Opus = retries only.
- **Two-tier docs precedent**: never read `INDEX.json` from main thread, always dispatch doc-fetcher. User is implicitly extending the same principle to external lookup.
- **Subagent constraints**: declare explicit model + tool whitelist; z-harness stays repo-agnostic; output small + cited; dispatch explicit (no auto-routing).

## Specific tensions to surface:
1. **Repo ownership**: Domain APIs (Kalshi, weather) are qt-bot concepts. Should lookup subagent live in z-harness (generic) or qt-bot (domain-specific)? Or both?
2. **Tool whitelist**: If in z-harness, it can't assume Kalshi Python client is installed. If in qt-bot, it's qt-bot-only. How abstract?
3. **Synthesis quality vs cost**: Scraping HTML or parsing paginated JSON is cheaper in fresh context (Haiku Bash-fu) than main thread, but Haiku might miss subtle schema shifts. Trade off?
4. **Dispatch pattern**: explicit subagent call from main (like doc-fetcher) or auto-routing from a skill?
5. **Caching/staleness**: Does the lookup subagent cache results? Re-query Kalshi every time? How long are results valid (tickers change)?

## Return exactly five sections:

1. **Framing** — what is the actual problem this solves and for whom?
2. **Core hypothesis** — the single strongest thesis about whether/how to build this.
3. **Risks** — the main ways this could fail or become a burden.
4. **Plan implications** — if we build it, what changes in z-harness, qt-bot, and workflows?
5. **What would change my mind** — concrete signals that would argue against the approach or suggest a different split.

Do NOT add other sections. Do NOT recommend an approach. Mark sections `<missing>` only if you truly cannot produce them. Be bold and distinct.
