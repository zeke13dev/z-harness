# Decisions — lookup-subagent

Five consult-flagged decisions (D1, D2, D3, D5, D8). Hard cap = 5. The other five are obvious-skip-consult.

---

## D1 — Agent topology: how many subagents, where?

- **Options:**
  - **A. Two agents (Codex framing):** `external-lookup` in z-harness + `qt-market-lookup` in qt-bot. Each declares its own model + tools.
  - **B. One agent + per-repo scripts (Gemini framing):** single `external-investigator` in z-harness; qt-bot exposes shell scripts the agent invokes.
  - **C. Three agents:** split z-harness side into `web-lookup` (docs/web) and `api-lookup` (structured APIs). qt-bot still gets its own `qt-market-lookup`.
- **Tentative call:** A — matches user's Phase 3 brainstorm choice; cleanest security boundary.
- **Consult? yes**
- **Trigger:** module boundary, naming on public surface, reversibility (renaming an agent that's already in use across plugin consumers is painful).

## D2 — Tool whitelist for `external-lookup`

- **Options:**
  - **A.** `WebFetch, WebSearch, Read, Grep, Glob` — no shell. Pure managed-tool fetch + filesystem read for caching/citations.
  - **B.** `WebFetch, WebSearch, Bash, Read, Grep, Glob` — add Bash for `curl`/`jq`/`gh` repo-API queries that WebFetch can't handle.
  - **C.** `Bash, Read, Grep, Glob` — shell only; WebFetch left to main thread.
- **Tentative call:** B with a Bash verb-blocklist mirroring `remote-runner` (no INSERT/UPDATE/DELETE/git-push/gh-pr-create/curl-with-X-method=POST/PUT/DELETE/PATCH). Bash unlocks `gh api`, `jq`, simple `curl` for endpoints WebFetch can't hit (auth headers, query params past WebFetch's quirks).
- **Consult? yes**
- **Trigger:** security boundary, hard-to-reverse (broadening tools later is fine; narrowing after consumers depend on Bash is breakage).

## D3 — Output contract surface

- **Options:**
  - **A.** Document the contract in `agents/external-lookup.md` prose only. qt-bot's `qt-market-lookup` reads that file to learn the format.
  - **B.** Extract a `docs/llm/lookup-contract.json` two-tier doc concept that both agents (and any other consumer) target. Treat the contract as a first-class artifact.
  - **C.** Loose contract: just say "return cited summary" in both agent files; let each agent's prose drift.
- **Tentative call:** B — promotes the contract to a versioned, doc-fetcher-discoverable artifact. Matches z-harness's two-tier docs precedent. Adds one INDEX.json entry; modest cost.
- **Consult? yes**
- **Trigger:** wire format / public API; naming hard to rename; reversibility (changing the contract shape after qt-bot+others adopt it = N consumer migrations).

## D4 — Model tier for `external-lookup`

- **Options:** Haiku / Sonnet / Opus
- **Tentative call:** Haiku. Matches z-harness's "cheap for lookup, declared per agent" convention. If results are consistently shallow we upgrade later — single-line frontmatter change.
- **Consult? no**
- **Trigger:** clearly obvious; matches existing convention (doc-fetcher, remote-runner are both Haiku).

## D5 — Model tier for `qt-market-lookup`

- **Options:** Haiku / Sonnet / Opus
- **Tentative call:** Sonnet. Codex's "what would change my mind" #2 flagged Haiku as likely insufficient for market specifics (expiry, strike units, payout schemas). qt-bot's market lookups are higher-stakes than generic web lookup.
- **Consult? yes**
- **Trigger:** affects cost + correctness on a financial-data path; one of the rare cases where Sonnet (vs. Haiku default for lookups) is genuinely justified — worth a sanity-check.

## D6 — Main-thread WebFetch ban: how strict?

- **Options:**
  - **A.** Documentation only in `agents/external-lookup.md` ("you should delegate WebFetch from main"). No enforcement.
  - **B.** Add a `~/.claude/CLAUDE.md` global rule (next to the existing doc-fetcher rule). User does this manually after deploy.
  - **C.** Build a hook in z-harness that intercepts WebFetch from main and redirects. Significant new infrastructure.
- **Tentative call:** A — best-effort docs. The doc-fetcher rule precedent IS already in user's CLAUDE.md, so the user can add a parallel WebFetch rule themselves if desired (mention in PLAN.md). B and C are out of scope.
- **Consult? no**
- **Trigger:** obvious. C is over-engineering; B is user-side, not z-harness-side; A is the minimum that works.

## D7 — Verb-blocklist details for `external-lookup` Bash

- **Options:** mirror `remote-runner` exactly / extend with web-specific bans / minimal (no DB writes only)
- **Tentative call:** Extend with web/git-push verbs. Block list: `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM` (DB writes) + `git push|git commit|git reset --hard|gh pr create|gh pr merge|gh issue close` (mutating git/GH) + `curl.*(-X|--request)\s*(POST|PUT|DELETE|PATCH)` (mutating HTTP). All grep-enforced before Bash execution; refuse with `STATUS: refused`, reason `mutation_blocked`.
- **Consult? no**
- **Trigger:** mechanical extension of an existing pattern.

## D8 — Output token budget + structure

- **Options:**
  - **A.** ≤2 KB synthesis (mirror doc-fetcher).
  - **B.** ≤4 KB to accommodate richer external-data citations (URL+excerpt+commands).
  - **C.** Hard structured JSON envelope (provenance fields as YAML/JSON) + free-text body, total ≤3 KB.
- **Tentative call:** C — structured envelope. Codex's plan-implications list demanded provenance fields anyway. Structured fields let main thread parse without regex; ≤3 KB cap balances richness vs. context savings.
- **Consult? yes**
- **Trigger:** wire format on a contract that consumers will parse; reversibility (loosening later is fine, tightening after adoption breaks consumers).

## D9 — Caching

- **Options:** opt-in per-domain / disabled / always-on with TTL
- **Tentative call:** disabled. Codex's risk #3 + "what would change my mind" #5 both warn caching adds footguns before usage data justifies it. Re-evaluate after N runs.
- **Consult? no**
- **Trigger:** clearly defer; not a wire-format decision.

## D10 — Deposit mechanism for `qt-market-lookup`

- **Options:**
  - **A.** Manual SSH/rsync into qt-bot's `.claude/agents/` once; documented in PLAN.md.
  - **B.** Extend `z-export` to also push to a configured remote target.
  - **C.** Have the qt-bot side be a *skill* (in `.claude/skills/`) rather than an agent, since skills are already user-deposited per-repo.
- **Tentative call:** A — one-time manual deposit, documented as a TASKS.md task that uses the `qt-bot-remote` skill to scp the file. Extending z-export (B) is real scope; C reframes the boundary unnecessarily.
- **Consult? no**
- **Trigger:** mechanical; one-time op.

---

## Summary

| ID  | Decision                              | Tentative                   | Consult |
|-----|---------------------------------------|-----------------------------|---------|
| D1  | Agent topology                        | Two agents (Codex framing)  | ✅ yes  |
| D2  | `external-lookup` tool whitelist      | WebFetch+WebSearch+Bash+RGG | ✅ yes  |
| D3  | Output contract surface               | `docs/llm/lookup-contract.json` | ✅ yes |
| D4  | `external-lookup` model               | Haiku                       | no      |
| D5  | `qt-market-lookup` model              | Sonnet                      | ✅ yes  |
| D6  | Main-thread WebFetch ban              | docs-only (best effort)     | no      |
| D7  | Bash verb-blocklist                   | DB + git/gh + curl-mutate   | no      |
| D8  | Output budget + structure             | Structured envelope ≤3 KB   | ✅ yes  |
| D9  | Caching                               | disabled                    | no      |
| D10 | qt-bot deposit mechanism              | manual via qt-bot-remote    | no      |

**Consult bundle: 5 of 5 cap.** D1, D2, D3, D5, D8 → Gemini + Codex parallel call in Phase 3.
