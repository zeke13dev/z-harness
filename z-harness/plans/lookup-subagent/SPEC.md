# SPEC — lookup-subagent

Two-tier "lookup" subagent infrastructure: generic `external-lookup` lives in z-harness; domain-specific `qt-market-lookup` lives in qt-bot. Both target a shared output contract published as `docs/llm/lookup-contract.json` (z-harness). Main thread delegates noisy external retrieval (web docs outside training cutoff, paginated APIs, market discovery) to either agent and gets back a ≤3 KB STATUS-headed Markdown synthesis.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/plans/lookup-subagent/BRAINSTORM.md | 2026-05-24T18:41:04Z |
| RESEARCH.md | n/a | n/a |

---

## File 1: `docs/llm/lookup-contract.json` (z-harness — NEW)

**Purpose:** Canonical machine-readable description of the lookup output contract that both agents emit and that any future consumer can target.

**Frontmatter / schema** (matches existing two-tier docs concept format):

> **SCHEMA NOTE (post-review amendment 2026-05-24):** The repo's actual concept-JSON convention is `key_invariants` (string array), `key_files` (array of `{path, why}` objects), `related_concepts`, `last_updated` — confirmed against `docs/llm/providers-registry.json` during T001 retry. The illustrative shape below uses the canonical fields. Do **not** use `title`, `key_concepts`, `invariants`, `gotchas`, or `source_files` — those names were authored against an incorrect assumption about repo convention and are non-canonical.

```json
{
  "slug": "lookup-contract",
  "summary": "Output envelope all lookup subagents emit. STATUS-line + Markdown sections (## Answer / ## Provenance / ## Unresolved). ≤3 KB.",
  "key_invariants": [
    "First line is exactly `STATUS: <token>` where token in {ok,refused,partial}",
    "All headed sections appear in fixed order: Answer, Provenance, Unresolved, [Raw artifact pointer]",
    "No raw HTML/JSON dumped into Answer; cite + summarize",
    "Refused responses MUST have first `## Answer` line in the form `Refused: <category> — <detail>` (category ∈ {mutation_blocked, out_of_scope, auth_missing})",
    "Body cap is total: header + all sections combined ≤3 KB"
  ],
  "key_files": [
    { "path": "agents/external-lookup.md", "why": "Agent prompt that implements the contract." },
    { "path": "docs/llm/lookup-contract.json", "why": "This canonical contract file." },
    { "path": "docs/human/lookup-contract.md", "why": "Human-readable explanation + examples." }
  ],
  "related_concepts": ["agents"],
  "last_updated": "<run-date>"
}
```

**Behavior:** read-only doc concept consumed by `doc-fetcher` like any other; surfaces when a query mentions "lookup" / "contract" / "external".

**Invariant:** updating this file MUST bump `last_updated` and trigger /z-maintain-docs awareness for both downstream agents.

---

## File 2: `agents/external-lookup.md` (z-harness — NEW)

**Purpose:** Generic, repo-agnostic Haiku subagent that handles external retrieval — web docs, public APIs, structured fetches — and returns the lookup-contract envelope.

**Frontmatter:**

```yaml
---
name: external-lookup
description: Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist.
model: haiku
tools: WebFetch, WebSearch, Bash, Read, Grep, Glob
---
```

**Body sections (prose):**

1. **Mission.** One paragraph: "You are a fresh-context lookup worker. Main thread delegates noisy retrieval to you so it doesn't pollute its context. Return ≤3 KB STATUS-headed Markdown per `docs/llm/lookup-contract.json`."
2. **Output contract.** Reproduce the contract structure inline (STATUS line + the four Markdown sections) AND cite `docs/llm/lookup-contract.json` as the canonical version. If conflict, contract.json wins.
3. **Tool guidance.**
   - Prefer `WebFetch` for known URLs of public docs/pages.
   - Prefer `WebSearch` to discover URLs when only a topic is given.
   - Use `Bash` for endpoints WebFetch can't handle: `gh api`, `curl` with custom headers / query params / auth, `jq` filtering of returned JSON.
4. **Verb-blocklist (mandatory before any Bash exec).** Before running any Bash command, grep the literal command string (case-insensitive) against the patterns below. Any match → emit `STATUS: refused` with `## Answer` body `Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'`. Do not execute.

   ```
   # DB writes (verb anywhere AND via -f / redirect)
   INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
   psql\s+[^|]*\s-f\s|sqlite3\s+[^|]*\s*<|>\s*[^|>\s]+\.(db|sqlite|sqlite3)\b

   # Git mutations
   git\s+push|git\s+commit|git\s+reset\s+--hard|git\s+rebase\s+--|git\s+stash\s+drop|git\s+branch\s+-D|git\s+checkout\s+--

   # GitHub mutations (including gh api with mutating methods)
   gh\s+pr\s+(create|merge|close|edit)|gh\s+issue\s+(create|close|edit)|gh\s+release\s+create|gh\s+api\s+[^|]*--method\s+(POST|PUT|PATCH|DELETE)

   # HTTP mutations
   curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
   curl[^|]*(-d|--data|--data-raw|--data-binary|-F|--form)\b
   wget\s+[^|]*--(post-data|method)\b
   \bhttpie\s+(POST|PUT|DELETE|PATCH)\b
   \bhttp\s+(POST|PUT|DELETE|PATCH)\b

   # Eval / piped interpreters (NOTE: bare $(...) and backticks NOT blocked — too disruptive; rely on pipe-to-interpreter detection)
   \beval\b|\bsh\s+-c\b|\bbash\s+-c\b
   \|\s*(sh|bash|zsh|python|python3|perl|ruby|node)\b
   <\s*\(.*\)\s*\|\s*(sh|bash|python|perl|ruby|node)\b
   \b(perl|ruby|node|python|python3)\s+-e\b

   # Filesystem destructive
   rm\s+-(rf|fr|Rf|fR)\b|>\s*/dev/(sd|nvme|disk)
   ```

   Implementation note: each pattern is a Python regex tested with `re.IGNORECASE` against the joined argv string. Compile once; test before every `Bash` invocation.
5. **Budget.** Total response (STATUS line + all sections + whitespace) ≤3 KB. Aim for ≤2 KB synthesis inside `## Answer` so Provenance + Unresolved have headroom. If raw artifact exceeds budget, write it to `z-harness/lookup-cache/<sha256-of-normalized-query>.raw` and point at it in `## Raw artifact pointer`. The cache dir is gitignored; mkdir if missing. **Normalized query** = lowercase + collapse all internal whitespace runs to one space + strip leading/trailing whitespace.
6. **Freshness discipline.** `freshness_ts` is the **retrieval timestamp** in UTC ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) — not the source document's own last-modified date. If a source was loaded from cache and the cache is >24h old, mark `confidence: low` and call it out in `## Unresolved`.
7. **Refusal modes.** STATUS values, mutually exclusive:
   - `ok` — answer believed reliable.
   - `partial` — retrieval completed but incomplete OR ambiguous. Includes: 4xx (incl. 429 rate-limit), 5xx, no-results-found, pagination-truncation, source-cache-stale. Body explains gaps in `## Unresolved`.
   - `refused` — verb-blocklist matched OR explicit mission-scope violation (e.g. user asked to place a trade). Body's first `## Answer` line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
8. **Provenance section format.** Markdown bullet list, fields in fixed order, each on its own line:

   ```markdown
   ## Provenance
   - query: <normalized query string>
   - tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
   - sources: <bulleted sub-list of url:section or path:line>
   - freshness_ts: <ISO 8601 UTC>
   - confidence: <high | medium | low>
   - commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
   ```

   `commands:` entries are **verbatim** — never truncated in provenance. Display-side truncation may happen in `## Answer` (with `…`) but only there. If verbatim commands push the response over 3 KB, drop the response into the raw artifact pointer file and synthesize down.

9. **Confidence scale.** Three-value enum `{high, medium, low}`. Use `high` only when ≥1 authoritative source was directly retrieved AND the answer requires no interpolation. Use `low` for cached/stale-source answers or single-source answers where corroboration was attempted but failed.
9. **Never paste raw HTML, JSON, or YAML dumps into `## Answer`.** Cite + summarize. Use the raw-artifact pointer.

**Invariants:**
- First output line is exactly `STATUS: <token>`.
- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
- No tool dispatch other than the whitelist.

**Edge cases:**
- WebFetch returns 4xx/5xx → log in provenance, mark `STATUS: partial`, try **one** fallback (WebSearch or Bash `gh api`) before giving up.
- WebSearch returns nothing → `STATUS: partial`, `## Unresolved` notes "no results for query terms; suggest broader search".
- Pagination: WebSearch results ≤10 entries returned. WebFetch link-follow depth ≤2 (the original URL + at most one followed link per source). If more pages exist, note in `## Unresolved` that results are truncated and suggest a narrower query.
- Authenticated endpoints requiring secrets the agent doesn't have → `STATUS: refused`, category `auth_missing`. Do not attempt env-var sniffing.

---

## File 3: `agents/qt-market-lookup.md` (qt-bot — NEW, authored locally, then deposited via `qt-bot-remote` skill)

**Deposit procedure (load-bearing — implementer follows this exactly):**

1. Author the file locally first under `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md`. Do NOT commit it to z-harness's `agents/` (it does not belong there).
2. Use the `qt-bot-remote` skill to inspect qt-bot's tree on remote host `zeke-pc`:
   - Confirm the agents directory path: most likely `~/dev/qt-bot/.claude/agents/` or `~/dev/qt-bot/agents/`. If neither exists, ask the user.
   - Confirm the Kalshi client invocation path. Search for known patterns: `~/dev/qt-bot/scripts/kalshi*`, `cargo run -p kalshi*`, `python -m qt_bot.kalshi*`. Record the exact invocation discovered.
   - Confirm the env var(s) that gate paper vs. real-money mode. Likely `KALSHI_ENV`, `KALSHI_MODE`, or similar. Required for the trading verb-blocklist.
3. Substitute the discovered Kalshi client invocation and env-var name into the agent file's prose (the body has explicit `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` placeholders).
4. Use the `qt-bot-remote` skill to scp the finalized file to the discovered agents dir on remote. No restart needed (agent files are read on dispatch).
5. Static-verify on remote: file exists at the deposited path; frontmatter parses; `name:` field equals `qt-market-lookup`.

**If qt-bot's tree lacks any of the above (no agents dir, no Kalshi client, no env var)** → halt deposit, surface findings to user, do NOT improvise.



**Purpose:** Domain-specific Sonnet subagent in qt-bot that handles Kalshi / weather-market lookup using repo-local clients. Emits the same `lookup-contract` envelope.

**Frontmatter:**

```yaml
---
name: qt-market-lookup
description: Discover and inspect Kalshi tickers, weather markets, and related domain entities. Returns the STATUS-headed Markdown envelope from z-harness's docs/llm/lookup-contract.json. Read-only against the Kalshi API; refuses any order/trade verbs.
model: sonnet
tools: Bash, Read, Grep, Glob
---
```

**Body sections (prose):**

1. **Mission.** Resolve domain-specific lookups: "what is the ticker for Chicago daily high temperature?", "what weather markets are open for NYC next week?", "what's the payout schema for KXHIGHCHI-26MAY24-T70?". Return the lookup-contract envelope.
2. **Contract reference.** Cite the canonical contract at `<z-harness-plugin>/docs/llm/lookup-contract.json` (path resolved at deposit time; documented as an env var or known relative path). If the plugin path can't be resolved, fall back to the embedded contract description here.
3. **Tool guidance.** Use the qt-bot repo's existing Kalshi client (path resolved at deposit time — examples: `./scripts/kalshi-cli/...`, `cargo run -p kalshi-client --`, or `python -m qt_bot.kalshi`). The implementer determines the exact invocation when the agent is deposited.
4. **Verb-blocklist (mandatory before any Bash exec).** Same DB / git / gh / HTTP / eval / filesystem rules as `external-lookup`, PLUS qt-bot-specific:
   - **Trading mutations:** `place_order|cancel_order|trade|sell|buy(?!_?info)|withdraw|deposit|--execute|--submit`
   - **Real-money operations:** any command containing `--real|--live|--mainnet` while `KALSHI_ENV` ≠ `paper`/`demo`.
5. **Domain enrichment.** When returning ticker info, always include if available: contract symbol, market title, expiration timestamp, payout/strike schema, last price, current open interest. Mark `confidence: low` if any field came from a stale cache (>5 min for prices, >24h for static schema).
6. **Budget.** Same ≤3 KB total cap. Raw paginated API responses → cache pointer.
7. **Refusal modes.** Same `ok | refused | partial` semantics. Bias toward `partial` over confident `ok` when payout schema or expiry is ambiguous.

**Invariants:**
- Same output structure as `external-lookup` — orchestrator parses both identically.
- No order placement, ever. The verb-blocklist is hard.
- Sonnet tier; do not invoke unless main thread genuinely needs domain reasoning.

**Edge cases:**
- Kalshi API rate-limit hit → `STATUS: partial`, retry policy documented in `## Unresolved`.
- Market not yet listed → `STATUS: partial`, suggest re-querying after expected listing time (if known).
- Stale cache → degrade to `confidence: low` rather than refusing.

---

## File 4: `docs/llm/INDEX.json` (z-harness — MODIFIED)

Add two entries. Match the existing schema **exactly** by inspecting the current INDEX.json first (key names: confirm singular `source_file` vs plural `source_files`; confirm whether INDEX entries are nested inside a `concepts:` key or are top-level). The implementer reads the existing INDEX before editing.

Entries to add (schema may vary based on existing file):

```json
{
  "slug": "lookup-contract",
  "title": "External lookup output contract",
  "summary": "Envelope all lookup subagents emit. STATUS-line + Markdown sections. ≤3 KB.",
  "last_updated": "<run-date>",
  "source_files": ["agents/external-lookup.md", "docs/llm/lookup-contract.json"]
}
```

```json
{
  "slug": "external-lookup-agent",
  "title": "external-lookup subagent",
  "summary": "Generic Haiku subagent for external retrieval (web docs, public APIs, paginated JSON). Returns lookup-contract envelope.",
  "last_updated": "<run-date>",
  "source_files": ["agents/external-lookup.md"]
}
```

**Invariant:** INDEX.json remains the only main-thread-readable doc index. Per existing convention, each INDEX entry MUST have a paired `docs/llm/<slug>.json` body file. The `lookup-contract` entry's body is File 1. The `external-lookup-agent` entry's body is File 4b below.

## File 4b: `docs/llm/external-lookup-agent.json` (z-harness — NEW)

Token-compacted concept JSON for the `external-lookup` agent. Format mirrors existing concept JSONs (read `docs/llm/providers-registry.json` to confirm the schema). Canonical fields: `slug`, `summary`, `key_invariants` (string array), `key_files` (array of `{path, why}` objects), `related_concepts`, `last_updated`. Content:

- `summary`: one-sentence purpose.
- `key_invariants`: total response ≤3 KB; first line STATUS; no raw HTML/JSON in Answer; commands recorded verbatim; verb-blocklist enforced via grep-before-exec; model tier = haiku; output structure cited from lookup-contract.
- `key_files`: `[{path: "agents/external-lookup.md", why: "the agent file itself"}, {path: "docs/llm/lookup-contract.json", why: "canonical output contract the agent must follow"}]`.
- `related_concepts`: `["lookup-contract", "agents"]`.

> **SCHEMA NOTE (post-review amendment 2026-05-24):** Earlier drafts of this section listed `title`, `key_concepts`, `invariants`, `gotchas`, and `source_files` as required fields. Those names are NOT in the repo's actual convention. Use the canonical field set above. Prompt-injection / link-depth / cache-dir-gitignored notes go into `key_invariants` or `summary` prose, not into a `gotchas` array.

## File 4c: `docs/llm/agents.json` (z-harness — MODIFIED, if it exists and lists agents)

If `docs/llm/agents.json` exists as a registry of agents (read first to confirm schema), append an entry for `external-lookup` with model tier and tool whitelist matching File 2's frontmatter. If `agents.json` is not an agent registry, skip this file.

---

## File 5: `docs/human/lookup-contract.md` (z-harness — NEW)

Human-tier description of the contract. Mirrors `docs/llm/lookup-contract.json` semantics. ~1 page Markdown: motivation, the envelope structure, when to use `STATUS: partial` vs `refused`, examples of well-formed responses (one for a doc lookup, one for a Kalshi ticker lookup).

**Purpose:** the human readable companion to the LLM tier. Onboarding/reference for the user when authoring new lookup-tier agents.

---

## File 6: `z-harness/lookup-cache/.gitignore` (z-harness — NEW)

```
*
!.gitignore
```

Implicit: `lookup-cache/` exists for raw-artifact pointer overflow per the contract. Gitignored by default.

---

## File 7: `README.md` (z-harness — MODIFIED)

Add `external-lookup` to the agents table near the existing agent list. One row, one-line description matching the agent frontmatter.

---

## Cross-cutting invariants

- **No agent emits raw HTML/JSON dumps.** Every dump goes via the raw-artifact pointer.
- **No agent runs mutating commands.** Verb-blocklists are mandatory.
- **All agents emit the contract envelope** identically. Orchestrator parses without per-agent branching.
- **Main thread never reads `docs/llm/lookup-contract.json` directly.** Always via `doc-fetcher`.

## DRY / KISS / SOLID

- **DRY:** the contract lives once in `docs/llm/lookup-contract.json`; both agents reference it instead of duplicating prose. Verb-blocklist patterns are mostly shared (`external-lookup` defines the core; `qt-market-lookup` extends with trading verbs).
- **KISS:** no new transport layer, no new export mechanism. Reuse existing agent file convention, existing two-tier docs convention, existing `qt-bot-remote` skill for deposit. No hooks, no runtime guards beyond the model-honored verb-blocklist.
- **SOLID — Single Responsibility:** `external-lookup` does generic web/API; `qt-market-lookup` does Kalshi/weather. No overlap.
- **SOLID — Open/Closed:** the contract is the closed interface; the implementation set is open (a future `weather-noaa-lookup` agent can be added without touching the contract).
- **SOLID — Interface Segregation:** small contract with mandatory + optional fields. Consumers only parse what they need.
