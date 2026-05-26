# Phase 1 Scaffolding — lookup-subagent

## Topic

The user constantly needs to look up repetitive external/domain information from the main agent thread. Examples:

- Querying Kalshi for a new ticker (e.g. "what is the ticker for Chicago daily high temperature?").
- Exploring a weather-market series to find the right contract.
- Fetching docs / understanding tools or APIs outside training-data cutoff that require web access.

Each of these tasks, run from the main thread, burns a lot of tokens on HTTP requests, paginated API responses, web page HTML, irrelevant fields, etc. The user wants a **dedicated lookup subagent** that does the exploration in fresh context and returns a tight synthesis (e.g. "ticker is `KXHIGHCHI-26MAY24-T70`, expires Friday 4pm CT, payout schema is binary"), saving main-thread tokens.

User notes:
- Could be qt-bot-specific OR generalized.
- Equally useful for external-API discovery AND for web-doc fetching (e.g. "how does library X's new v3 API differ from v2").

## Doc-fetcher synthesis (existing z-harness subagent landscape)

**Subagent pattern.** `agents/*.md` declares each: name, description, model (Haiku/Sonnet/Opus), explicit tool whitelist. Subagents are fresh-context, isolated, mostly read-only.

**Existing read-only / lookup subagents:**
- `doc-fetcher` (Haiku) — reads `docs/llm/INDEX.json` + per-concept JSONs, returns ≤2 KB synthesis with file:line markers. Hard-budget ≤8 Reads. Tools: Read/Grep/Glob/Bash. Internal-only — never hits external networks.
- `remote-runner` (Haiku) — executes read-only DB/log queries over SSH (`duckdb -readonly`, `psql SELECT`, `tail`, `ls`). Refuses write verbs (INSERT|UPDATE|DELETE|…) via grep. Returns raw stdout + exit code without interpretation; orchestrator interprets.
- `consultant-primary` / `consultant-secondary` (Sonnet) — proxy to Gemini/Codex/etc. via `resolve-provider.sh`. No domain APIs.

**Gap:** no "external lookup / web fetch / domain-API query" subagent exists in z-harness. Domain tools (kalshi, weather) live in the target repo (e.g. qt-bot) as skills, not z-harness agents.

**qt-bot is a separate repo** at `~/dev/qt-bot/`. z-harness is repo-agnostic and gets *exported* into target repos via providers/plugin paths. It does NOT bundle domain tools.

**Model tier rules (from MEMORY):** Haiku for CLI wrappers + cheap lookup; Sonnet for implementation/review; Opus only on retry.

**Two-tier docs pattern (CLAUDE.md global rule):** never read `docs/llm/INDEX.json` from main thread — always dispatch `doc-fetcher`. This is the precedent the user is implicitly extending: *anything repetitive and token-heavy should go through a fresh-context Haiku subagent that synthesizes a small return.*

## Key files

- `/Users/zeke/dev/z-harness/agents/doc-fetcher.md` — closest existing precedent (cheap Haiku lookup w/ budget cap).
- `/Users/zeke/dev/z-harness/agents/remote-runner.md` — precedent for read-only external-state queries.
- `/Users/zeke/dev/z-harness/docs/llm/agents.json` — invariants: subagents isolated, read-only by default.
- `/Users/zeke/dev/z-harness/scripts/resolve-provider.sh` — single LLM-dispatch entrypoint (NOT domain APIs).

## RESEARCH.md

None — no prior research run for this slug.

## Constraints / invariants

- Subagents must declare an explicit model and tool whitelist.
- z-harness stays repo-agnostic; domain-specific tools belong in target repos.
- Haiku is the right tier for read-only lookup + synthesis.
- Output should be small (≤2 KB synthesis with citations / IDs / source links), not raw dump.
- Dispatch should be explicit (no auto-routing) — see "explicit commands" feedback memory.
