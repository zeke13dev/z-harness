# Phase 0 — Premise check

## What I take the goal to be

Build a two-tier "lookup" subagent infrastructure that lets the main thread delegate noisy external retrieval (web HTML, paginated API JSON, repo-external doc lookups) to a fresh-context worker and get back a tight, cited synthesis. Concretely:

1. **z-harness side (`external-lookup`)** — a generic, repo-agnostic Haiku subagent declared in `agents/external-lookup.md`. Owns:
   - The output **contract** (provenance fields: query, sources, commands/endpoints, answer, confidence, freshness ts, unresolved ambiguity, raw-artifact pointer).
   - Generic tools: WebFetch / WebSearch / Bash (with a verb-blocklist for shell calls).
   - The hard rule "no mutation, no raw dumps."
   - A global instruction (in `agents/external-lookup.md` and surfaced via CLAUDE.md export) that main-thread WebFetch should be delegated here.

2. **qt-bot side (`qt-market-lookup`)** — a domain-specific subagent declared in qt-bot's agents dir. Owns:
   - Kalshi/weather market semantics (ticker formats, expirations, payout schemas).
   - A narrow tool whitelist (Kalshi client + Bash with grep-blocked verbs; no generic WebFetch needed since the domain client returns structured data).
   - The same z-harness output contract, so the main thread consumes both agents identically.
   - Model tier: probably Sonnet (per Codex's "what would change my mind" — Haiku may miss market specifics).

## Premise challenges considered

- **Is "save tokens" really the problem?** Gemini's framing said context *pollution* is the deeper cost — main loses structural focus when parsing JSON. The fix addresses both; not a problem with the goal.
- **Is a generic primitive over-engineering?** Defensible because there are ≥2 distinct use cases (web doc fetching for libraries outside training, AND domain APIs). A second consumer beyond qt-bot will likely follow.
- **Will Haiku be enough for market lookups?** Probably not consistently — that's exactly why the domain agent is separate and can pick its own model tier.
- **Could WebFetch from main suffice?** No — WebFetch dumps results into main context, which is the friction. Subagent isolation is the point.
- **Cross-repo coordination?** z-harness exports its `agents/` via the plugin mechanism (already loaded in qt-bot). qt-bot's `qt-market-lookup` would be declared locally in qt-bot's own agents dir or as a skill — no z-harness import needed.
- **The "main-thread fetch ban" rule (Gemini's contract layer).** Borderline. It's powerful but only as enforceable as the global instruction the model honors — there's no hard runtime guard. Worth including in CLAUDE.md export, but flag as best-effort.

## Premise accepted

Proceeding with the two-tier design. The plan must explicitly resolve:
- where the contract is documented (so qt-bot can target it without coupling to z-harness internals);
- model tier per agent (Haiku for generic, likely Sonnet for market);
- tool whitelist details (especially the verb-blocklist mechanism that already exists for `remote-runner`);
- whether to enforce the "no main-thread WebFetch" rule via CLAUDE.md export only, or also via a hook.
