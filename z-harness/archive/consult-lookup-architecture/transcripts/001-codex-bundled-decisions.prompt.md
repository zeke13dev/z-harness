MODE: bundled-decisions

Context: planning a two-tier "lookup subagent" infrastructure for z-harness (a portable agent harness) + qt-bot (a trading repo on a remote host). Goal: stop main-thread token waste on noisy external retrieval (web docs, paginated APIs like Kalshi, weather markets) by routing through a fresh-context subagent that returns a tight cited synthesis.

Prior brainstorm picked a two-agent framing as the architecture (generic `external-lookup` in z-harness, repo-specific `qt-market-lookup` in qt-bot, each owning its own model + tools).

Five consult-flagged decisions follow. For each: (1) name one concrete way it could be wrong, (2) accept/modify/reject the tentative, (3) flag any cross-decision interaction.

---

## D1 — Agent topology

**Options:**
- A. Two agents: `external-lookup` (z-harness, generic) + `qt-market-lookup` (qt-bot, domain-specific). Each declares own model + tool whitelist.
- B. One agent + per-repo scripts: single `external-investigator` in z-harness; qt-bot exposes shell scripts.
- C. Three agents: split z-harness into `web-lookup` (docs) + `api-lookup` (structured APIs); qt-bot gets its own.

**Tentative: A** (your framing).

## D2 — Tool whitelist for `external-lookup`

**Options:**
- A. `WebFetch, WebSearch, Read, Grep, Glob` (no shell)
- B. `Bash, Read, Grep, Glob` with verb-blocklist (no WebFetch/WebSearch)
- C. `WebFetch, WebSearch, Bash, Read, Grep, Glob` with verb-blocklist on Bash

**Context:** z-harness already uses a `remote-runner` (Haiku agent) that sandboxes Bash with verb-blocking (e.g. refusal checks for write verbs in DB queries, no rm -rf outside sandbox, no interpretive analysis — these are delegated to Sonnet/Opus). The pattern is: Bash unlocks gh api, jq, curl for endpoints WebFetch cannot hit; mirror grep-before-exec safety checks.

**Tentative: B with Bash verb-blocklist.** Bash unlocks `gh api`, `jq`, `curl` for endpoints WebFetch can't hit.

## D3 — Output contract surface

**Options:**
- A. Document the contract in prose inside `agents/external-lookup.md`.
- B. Extract `docs/llm/lookup-contract.json` as a first-class doc concept.
- C. Loose contract in both agent files.

**Tentative: B.** Versioned, doc-fetcher-discoverable artifact. Matches two-tier docs convention.

## D5 — Model tier for `qt-market-lookup`

**Options:** Haiku / Sonnet / Opus.

**Tentative: Sonnet.** Your "change my mind" #2 flagged Haiku as likely insufficient for subtle market specifics (expiry, strike units, payout schemas). Financial-data path is higher-stakes than generic web lookup.

## D8 — Output token budget + structure

**Options:**
- A. ≤2 KB free-text synthesis (mirror doc-fetcher).
- B. ≤4 KB.
- C. Structured envelope (provenance fields as YAML/JSON header) + free-text body, total ≤3 KB.

**Tentative: C.** Your plan-implications demanded the provenance fields (query, sources, commands, freshness ts, confidence, unresolved ambiguity). Structured envelope lets main thread parse without regex.

---

Ask: For each consult-flagged decision (D1, D2, D3, D5, D8):
(1) Name one concrete failure mode for the tentative choice.
(2) Accept, modify, or reject the tentative.
(3) Flag any cross-decision interactions.

Be terse and concrete — no more than 2-3 sentences per decision.
