---
artifact: brainstorm
slug: lookup-subagent
generated_at: 2026-05-24T18:41:04Z
command: /z-brainstorm lookup subagent for repetitive external info (kalshi tickers, web docs)
input_hash: pending
depends_on: []
ideators:
  - claude:failed
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

`<missing>` — Claude ideator returned a framing-selection menu instead of a five-section block; logged as `claude:failed`. The hint it surfaced before going off-spec was "Who bears the context cost?" with a focus on a `STATUS:` output contract and explicit tool whitelist — directionally similar to Codex, so the failure doesn't appear to deprive us of a uniquely distinct viewpoint.

### Framing
`<missing>`

### Core hypothesis
`<missing>`

### Risks
`<missing>`

### Plan implications
`<missing>`

### What would change my mind
`<missing>`

## Framing: codex

### Framing
The real problem is not "we need another agent." The main orchestration thread is being used as a disposable scratchpad for noisy, repetitive, time-sensitive lookup work. People served: the main agent (needs compact facts, not raw HTTP sludge); the user (wants faster, cheaper iterations without watching context get polluted); future z-harness workflows (need a repeatable "inspect the outside world, return only the useful answer" pattern). This is the external analogue of `doc-fetcher`: isolate high-noise retrieval in a fresh, bounded context; return a cited synthesis small enough for the main thread. Key distinction: internal docs are stable; external/domain lookup is live, lossy, schema-prone, often repo-specific.

### Core hypothesis
**Build a generalized z-harness lookup primitive, but keep domain-specific lookup implementations outside z-harness.** Two-tier:

- `external-lookup` — repo-agnostic z-harness subagent for web/API/doc retrieval and compact synthesis.
- `qt-market-lookup` — qt-bot-specific wrapper/skill/subagent using repo-local Kalshi/weather tools, emitting the same output contract.

z-harness defines the **contract**: explicit dispatch only; cheap model by default; tight output budget; required citations / commands / URLs; freshness metadata; no mutation; no long raw dumps; clear failure modes. The important primitive is the output interface, not the implementation.

### Risks
- **Citation theater / shallow synthesis.** Haiku is good for Bash-fu + extraction, weak on semantic judgment about market rules or subtle API behavior.
- **Tool drift.** z-harness cannot assume repo-local clients, credentials, network affordances.
- **False freshness.** Cached/stale ticker data could be worse than no lookup.
- **Scope creep.** Every domain wants special parsing → generic primitive becomes a junk drawer.
- **Hidden dispatch cost.** Over-eager auto-routing trades token savings for latency.
- **Security boundary.** Read-only must not become "run arbitrary domain scripts that might trade or mutate."

### Plan implications
- z-harness: new subagent **contract** with provenance fields — query/task, sources consulted, commands/endpoints used, answer, confidence, freshness timestamp, unresolved ambiguity, raw-artifact pointer (not pasted). Mirror `doc-fetcher` discipline; stronger provenance.
- qt-bot: domain lookup lives near existing repo-specific skills; emits the z-harness lookup response format.
- Dispatch stays **explicit**; auto-routing only after stable patterns emerge.
- Caching opt-in and domain-aware. Docs tolerate longer cache; markets default to live with aggressive timestamp labeling.

### What would change my mind
- Most lookups are Kalshi/weather-only and depend on qt-bot credentials/clients → qt-bot-only agent with reusable output format is cleaner; skip the z-harness primitive.
- Haiku frequently misses subtle market specifics (wrong expiry, confused strike units, stale series) → Sonnet for market lookup, Haiku only for raw fetch/extract.
- Measured token savings are modest vs. added latency → don't subagent at all.
- Docs lookup and market lookup diverge sharply (browsing/summarizing vs. structured API querying) → split into two separate agents.
- Caching only justified after observing repeated stable answers; default off.

## Framing: gemini

### Framing
The problem is **context pollution, not just token economics**. The main thread is an orchestrator and synthesizer; when forced to act as a web scraper or JSON parser, it loses structural focus. Friction arises from mixing high-level reasoning with low-level data extraction. Just as `doc-fetcher` provides an "air gap" for internal documentation, we need an isolation layer for the outside world. But because external domains are repo-specific, a monolithic subagent cannot hold all API keys + schemas.

### Core hypothesis
Build `external-investigator` (Haiku) as a **generalized z-harness primitive** with native web capability (`google_web_search`, `curl`) that also acts as a **sandbox for executing the host repo's read-only CLI lookup scripts**. z-harness stays Kalshi-agnostic. qt-bot provides e.g. `./scripts/kalshi-lookup.sh`; the main thread dispatches `external-investigator` with instructions to run that script and synthesize raw paginated JSON into a strict <2KB summary. **Domain knowledge lives in the script the subagent invokes, not in the subagent itself.**

### Risks
- **Schema blindness.** If the main thread cannot see raw JSON schema, it may not know how to instruct the subagent to extract the right fields → multiple failed dispatch attempts.
- **Write-action bleed.** Using `run_shell_command` to execute repo-specific scripts means read-only guarantees rely on script naming/internal logic → risk of accidental mutation (e.g. executing a trade).
- **Haiku parsing failures.** May struggle with deeply-nested DOMs or dense financial JSON, hallucinating tickers or expiration dates.

### Plan implications
- Create `agents/external-investigator.md` (z-harness, Haiku-tier).
- Whitelist `google_web_search` + `run_shell_command` (or closest equivalents).
- Mandate rigid output format in system prompt: "<500 words; strip all markup; never return raw JSON/HTML blocks; cite the command or URL used."
- Update main z-harness instructions to **forbid direct external API curling or web fetching from the main thread** — mandatory delegation, just like the `doc-fetcher` rule.

### What would change my mind
- Subagent spin-up adds unbearable latency (30s for a basic ticker that inline would take 5s).
- Haiku consistently fails on pagination/schema density of standard domain APIs → Sonnet required.
- Provider context caching becomes so cheap that burning tokens on raw JSON is near-zero cost → architectural complexity not worth it.

## Anti-bias check

(Two-way; Claude failed and contributes nothing to the section-by-section vote.)

- **Framing.** Both agree this is `doc-fetcher`-for-the-outside-world. Gemini frames the cost as **context pollution** — main thread loses *structural focus* when parsing JSON. Codex frames it as token waste + repo-specificity ("live, lossy, schema-prone"). Slight edge to Gemini for naming the cognitive harm, not just the token cost.
- **Core hypothesis.** The real fork. Codex proposes **two agents** (generic + domain wrapper) so qt-bot can own ticker semantics. Gemini proposes **one generic agent + per-repo scripts** the agent invokes, keeping domain knowledge in scripts rather than in a second subagent. Both keep z-harness repo-agnostic. Trade: where does Kalshi-specific code live — in a qt-bot subagent or in a qt-bot script that any subagent can invoke? Gemini's design is simpler (1 agent, N scripts); Codex's has stronger boundaries (qt-bot's subagent owns its output contract end-to-end, can use Sonnet for hard market reasoning while the generic stays Haiku). Codex better matches z-harness's existing precedent of per-concern subagents declared in `agents/*.md`.
- **Risks.** Codex enumerates more (citation theater, scope creep, false freshness, security boundary). Gemini's three are punchier and address mechanism (schema blindness, write-action bleed, Haiku parsing). Slight edge to Codex for completeness.
- **Plan implications.** Codex specifies the output contract (provenance fields) concretely; Gemini specifies the file path, model tier, tool whitelist, and the global "main thread MUST NOT fetch" rule. Complementary, not competing — a real plan adopts both.
- **What would change my mind.** Both well-formed; Codex's more comprehensive, Gemini's crisper.

**No Claude-favoring picks to justify** — Claude failed; no Claude output to favor.

## Orchestrator recommendation

**Codex's framing** — primarily because the **two-agent split** (generic `external-lookup` in z-harness + repo-specific `qt-market-lookup` in qt-bot) matches the existing z-harness precedent that *every concern gets its own declared subagent with its own model tier and tool whitelist*. Gemini's "one generic agent runs repo scripts" is conceptually cleaner but blurs the security boundary (the generic agent's tool whitelist becomes "shell + anything the script does"), which is exactly the risk Gemini itself flagged ("write-action bleed"). Codex's design lets `qt-market-lookup` declare *its own* narrow tool whitelist (e.g. Kalshi client + Bash with verb-blocked grep) instead of importing that risk into the generic agent.

The two are not mutually exclusive: adopt **Codex's two-tier structure** as the architecture, and **Gemini's strict output-format mandate + main-thread-fetch ban** as the contract enforcement layer.

User is free to override.

## User choice

**Chosen framing: codex** — two-agent split.

Verbatim reproduction (so `/z-plan` can find it without re-parsing the ideator blocks):

### Framing
The real problem is not "we need another agent." The main orchestration thread is being used as a disposable scratchpad for noisy, repetitive, time-sensitive lookup work. People served: the main agent (needs compact facts, not raw HTTP sludge); the user (wants faster, cheaper iterations without watching context get polluted); future z-harness workflows (need a repeatable "inspect the outside world, return only the useful answer" pattern). This is the external analogue of `doc-fetcher`: isolate high-noise retrieval in a fresh, bounded context; return a cited synthesis small enough for the main thread. Key distinction: internal docs are stable; external/domain lookup is live, lossy, schema-prone, often repo-specific.

### Core hypothesis
**Build a generalized z-harness lookup primitive, but keep domain-specific lookup implementations outside z-harness.** Two-tier:

- `external-lookup` — repo-agnostic z-harness subagent for web/API/doc retrieval and compact synthesis.
- `qt-market-lookup` — qt-bot-specific wrapper/skill/subagent using repo-local Kalshi/weather tools, emitting the same output contract.

z-harness defines the **contract**: explicit dispatch only; cheap model by default; tight output budget; required citations / commands / URLs; freshness metadata; no mutation; no long raw dumps; clear failure modes. The important primitive is the output interface, not the implementation.

### Risks
- Citation theater / shallow synthesis (Haiku weak on semantic market judgment).
- Tool drift (z-harness can't assume repo-local clients/credentials).
- False freshness (stale cache worse than no lookup).
- Scope creep (generic primitive becomes a junk drawer).
- Hidden dispatch cost (auto-routing trades tokens for latency).
- Security boundary (read-only must not become "run arbitrary domain scripts").

### Plan implications
- z-harness: new subagent contract with provenance fields (query/task, sources, commands/endpoints, answer, confidence, freshness timestamp, unresolved ambiguity, raw-artifact pointer not pasted).
- qt-bot: domain lookup near existing repo skills, emitting the z-harness response format.
- Dispatch explicit; auto-routing only after stable patterns emerge.
- Caching opt-in + domain-aware (docs tolerate longer cache; markets default live with timestamps).

### What would change my mind
- Lookups dominated by Kalshi/weather → skip the z-harness primitive, qt-bot-only.
- Haiku frequently misses market specifics → Sonnet for market lookup.
- Token savings modest vs. added latency → don't subagent at all.
- Docs vs. markets diverge sharply → split into two distinct agents.
- Caching only justified after observing repeated stable answers.
