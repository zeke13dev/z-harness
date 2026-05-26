## 1. Framing

The real problem is not "we need another agent." It is that the main orchestration thread is being used as a disposable scratchpad for noisy, repetitive, time-sensitive lookup work.

The people served are:

- The main agent, which needs compact facts, not raw HTTP sludge.
- The user, who wants faster, cheaper iterations without watching context get polluted.
- Future z-harness workflows, which need a repeatable pattern for "go inspect the outside world and return only the useful answer."

This is the external analogue of `doc-fetcher`: isolate high-noise retrieval in a fresh, bounded context, then return a cited synthesis small enough for the main thread to reason over.

The key distinction is that internal docs are stable and controlled; external/domain lookup is live, lossy, schema-prone, and often repo-specific.

## 2. Core hypothesis

The strongest thesis is: build a generalized z-harness lookup primitive, but keep domain-specific lookup implementations outside z-harness.

That means z-harness should define the contract:

- explicit dispatch only
- cheap model by default
- tight output budget
- required citations / commands / URLs
- freshness metadata
- no mutation
- no long raw dumps
- clear failure modes

But qt-bot should own Kalshi/weather lookup logic, because ticker formats, market semantics, payout schemas, and repo-local clients are domain knowledge. A generic z-harness subagent should be able to do web/API/doc lookup with shell/network tools where available, but it should not pretend to know Kalshi as a core primitive.

The shape is probably two-tier:

- `external-lookup`: repo-agnostic z-harness subagent for web/API/doc retrieval and compact synthesis.
- `qt-market-lookup`: qt-bot-specific wrapper/skill/subagent that uses repo-local Kalshi/weather tools and returns the same lookup contract.

The important primitive is the output interface, not the implementation.

## 3. Risks

The biggest failure mode is turning "lookup" into an under-specified mini-research agent that returns confident but shallow summaries. Haiku is good for Bash-fu and extraction, but weak when the lookup requires semantic judgment about market rules, schema changes, or subtle API behavior.

Other risks:

- Tool drift: z-harness cannot assume repo-local clients, credentials, or network affordances.
- False freshness: cached or stale ticker data could be worse than no lookup.
- Citation theater: URLs and snippets may look grounded while omitting the exact fields needed for trading decisions.
- Scope creep: every domain wants special parsing, and the generic primitive becomes a junk drawer.
- Hidden dispatch cost: if auto-routing is too eager, main agents may over-delegate simple lookups and create latency without much token savings.
- Security boundary fuzziness: read-only external lookup must not become "run arbitrary domain scripts that might trade, write, or mutate state."

## 4. Plan Implications

In z-harness, this would add a new subagent contract rather than a Kalshi-aware agent. The contract should specify input shape, allowed tools, model tier, output budget, citation requirements, and staleness labeling. It should probably mirror `doc-fetcher` discipline, but with stronger provenance fields:

- query/task
- sources consulted
- commands or endpoints used
- answer
- confidence
- freshness timestamp
- unresolved ambiguity
- raw artifact pointer only if needed, not pasted output

In qt-bot, domain lookup should live near existing repo-specific skills or scripts. Kalshi/weather lookup can use repo-local clients, schemas, auth conventions, and market vocabulary. The qt-bot wrapper should emit the z-harness lookup response format so orchestrators can consume it without caring whether the source was Kalshi, NOAA, live docs, or a website.

In workflows, dispatch should stay explicit. A main agent or skill says: "delegate this lookup," then receives a tight result. Auto-routing can come later only after repeated stable patterns exist. For now, explicit calls preserve auditability and avoid surprising tool use.

Caching should be opt-in and domain-aware. Library docs can tolerate longer cache windows. Kalshi tickers and prices should default to live lookup, with any cache marked aggressively by timestamp. Contract metadata matters more than clever caching.

## 5. What Would Change My Mind

I would lean away from a generalized z-harness primitive if most real lookup requests are Kalshi/weather-specific and depend on qt-bot credentials, clients, or market semantics. In that case, a qt-bot-only lookup subagent with a reusable output format is cleaner.

I would lean away from Haiku-first lookup if examples show frequent subtle misses: wrong contract expiration, confused strike units, stale market series, or misread payout rules. That would argue for Sonnet on market/domain lookup and Haiku only for raw fetch/extract.

I would lean away from subagents entirely if measured runs show token savings are modest compared with added latency and orchestration complexity.

I would split the design differently if live docs lookup and market lookup diverge sharply: docs need browsing/summarization and version comparison, while markets need structured API querying, freshness, and exact field extraction.

I would add caching only after seeing repeated identical lookups with stable answers. If the common case is "today's ticker/current price/current expiration," caching should be treated as a footgun unless the result visibly carries its timestamp and validity window.
