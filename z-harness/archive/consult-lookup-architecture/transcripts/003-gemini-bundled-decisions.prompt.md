MODE: bundled-decisions

CONTEXT:
Building a "lookup subagent" infrastructure for z-harness (portable agent harness) + qt-bot (trading repo on remote host) to prevent main-thread context pollution from noisy external retrieval (web docs, paginated APIs like Kalshi, weather markets).

Prior brainstorm (Codex) identified the diagnostic ("context pollution > token cost") and picked the Codex framing: two distinct agents — one generic in z-harness, one domain-specific in qt-bot.

ARCHITECTURAL PRECEDENTS IN Z-HARNESS:
- doc-fetcher (Haiku): reads internal docs/llm/ JSON, returns ≤2 KB synthesis. INTERNAL ONLY.
- remote-runner (Haiku): read-only queries over SSH, refuses write verbs (regex-blocked before execution), returns raw stdout for orchestrator interpretation.
- Both declare explicit model + tool whitelist; z-harness stays repo-agnostic.

FIVE CONSULT-FLAGGED DECISIONS:

---

## D1 — Agent topology

**Options:**
- A. Two agents: `external-lookup` (z-harness, generic) + `qt-market-lookup` (qt-bot, domain-specific). Each declares own model + tool whitelist.
- B. One agent + per-repo scripts: single `external-investigator` in z-harness; qt-bot exposes shell scripts the agent invokes.
- C. Three agents: split z-harness into `web-lookup` (docs) + `api-lookup` (structured APIs); qt-bot gets its own.

**Tentative: A.** Matches z-harness per-concern subagent precedent; cleanest security boundary (qt-bot agent can declare narrow Kalshi-client whitelist instead of importing risk into the generic).

---

## D2 — Tool whitelist for `external-lookup`

**Options:**
- A. `WebFetch, WebSearch, Read, Grep, Glob` (no shell)
- B. `Bash, Read, Grep, Glob` with verb-blocklist
- C. `Bash, Read, Grep, Glob` (shell only; no managed web tools)

**Tentative: B with Bash verb-blocklist.** Bash unlocks `gh api`, `jq`, `curl` for endpoints WebFetch can't hit (auth headers, query-string quirks). Mirror `remote-runner`'s grep-before-exec pattern for blocking mutating verbs.

---

## D3 — Output contract surface

**Options:**
- A. Document the contract in prose inside `agents/external-lookup.md`. qt-bot's agent reads that file to learn it.
- B. Extract `docs/llm/lookup-contract.json` as a two-tier doc concept. Both agents target it; doc-fetcher can surface it.
- C. Loose contract (just "cited summary") in both agent files; tolerate drift.

**Tentative: B.** Promotes the contract to a versioned, discoverable artifact. Matches z-harness's two-tier docs convention. Small INDEX.json addition.

---

## D5 — Model tier for `qt-market-lookup`

**Options:** Haiku / Sonnet / Opus.

**Tentative: Sonnet.** Your own "what would change my mind" flagged Haiku as likely insufficient for market specifics (expiry, strike units, payout schemas). qt-bot lookups are higher-stakes (financial-data path) than generic web lookup.

---

## D8 — Output token budget + structure

**Options:**
- A. ≤2 KB free-text synthesis (mirror doc-fetcher).
- B. ≤4 KB to accommodate richer citations.
- C. Structured envelope (provenance fields as YAML/JSON header) + free-text body, total ≤3 KB.

**Tentative: C.** Codex's plan-implications demanded provenance fields (query, sources, commands, freshness ts, confidence, unresolved). Structured envelope lets main thread parse without regex. ≤3 KB cap balances richness vs. context savings.

---

TASK:
For each decision (D1, D2, D3, D5, D8):
1. Name ONE concrete failure mode for the tentative option.
2. Give a clear recommendation: accept / modify / reject the tentative.
3. Flag any cross-decision interaction.

Be terse and concrete. No long narratives.
