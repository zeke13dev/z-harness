MODE: brainstorm

TOPIC:
Should we build a "lookup subagent" that handles repetitive external/domain information retrieval (e.g. querying Kalshi for tickers, exploring weather markets, fetching live web docs for libraries outside training cutoff) so the main agent thread doesn't burn tokens on HTTP responses, paginated API output, HTML, and irrelevant fields? Should it be qt-bot-specific or generalized as a z-harness primitive? What shape should it take?

SCAFFOLDING / CONTEXT:

Problem:
- User constantly needs to look up repetitive external/domain information from the main agent thread
- Examples: querying Kalshi for a new ticker ("what is the ticker for Chicago daily high temperature?"); exploring a weather-market series; fetching docs / understanding tools or APIs outside training cutoff that need web
- Each task, run from main, burns tokens on HTTP responses, paginated API output, web HTML, irrelevant fields
- User wants a dedicated lookup subagent that does the exploration in fresh context and returns a tight synthesis (e.g. "ticker is KXHIGHCHI-26MAY24-T70, expires Fri 4pm CT, payout schema binary")
- Could be qt-bot-specific OR generalized as a z-harness primitive

Existing z-harness subagent landscape:
- doc-fetcher (Haiku): reads internal docs/llm/ JSON, ≤8 Reads, ≤2 KB synthesis. INTERNAL ONLY — never network.
- remote-runner (Haiku): read-only DB/log queries over SSH; refuses write verbs; returns raw stdout for orchestrator to interpret.
- consultant-primary/secondary (Sonnet): proxy to Gemini/Codex LLMs. No domain APIs.

Gap: no external-lookup / web-fetch / domain-API-query subagent exists. Domain tools (kalshi, weather APIs) live in target repos (qt-bot) as skills, not in z-harness.

Architectural facts:
- qt-bot is a separate repo (~/dev/qt-bot/). z-harness is repo-agnostic, gets exported into target repos.
- Model tier rules: Haiku = cheap CLI/lookup wrappers; Sonnet = implementation; Opus = retries only.
- Two-tier docs precedent: never read INDEX.json from main thread, always dispatch doc-fetcher. The user is implicitly extending the same principle to external lookup.
- Constraints: subagents declare explicit model + tool whitelist; z-harness stays repo-agnostic; output small + cited; dispatch explicit (no auto-routing).

TASK:
Return exactly five sections: 
1. Framing
2. Core hypothesis
3. Risks
4. Plan implications
5. What would change my mind

Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
