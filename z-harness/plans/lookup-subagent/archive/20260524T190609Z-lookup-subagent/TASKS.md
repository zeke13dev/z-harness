# TASKS — lookup-subagent

Plan: see `SPEC.md` and `PLAN.md` in this directory.

Order: tasks generally proceed top-down, but T001-T003 are independent and can be implemented in any order. T004 depends on T001-T003. T005-T006 depend on T002. T007-T009 depend on T002+T005. T010-T012 are deposit/verification and must be last.

---

## T001 — Author canonical lookup contract (docs/llm/lookup-contract.json)

**Files touched:** `docs/llm/lookup-contract.json` (NEW)
**Depends on:** none
**Acceptance criteria:**
- File is valid JSON.
- Schema matches the existing `docs/llm/<slug>.json` shape (read one existing concept JSON like `docs/llm/providers-registry.json` to confirm fields).
- Contains: `slug=lookup-contract`, `title`, `summary`, `key_concepts` (list including STATUS values, mandatory provenance fields, body cap, raw-artifact rule), `invariants` (STATUS first line, fixed section order, no raw dumps in Answer, refused MUST give reason), `gotchas`.
- `source_files`: `["agents/external-lookup.md", "docs/llm/lookup-contract.json"]`.
- `last_updated`: today's UTC date (`YYYY-MM-DD`).
- File ends with newline; no trailing comma issues.

**Status:** [ ]
**DOCS:** lookup-contract
**Complexity:** low

---

## T002 — Author external-lookup agent file (agents/external-lookup.md)

**Files touched:** `agents/external-lookup.md` (NEW)
**Depends on:** none (but in practice authored alongside T001's contract)
**Acceptance criteria:**
- YAML frontmatter has `name: external-lookup`, `description: <one-line per SPEC>`, `model: haiku`, `tools: WebFetch, WebSearch, Bash, Read, Grep, Glob`.
- Body has the sections specified in SPEC §File 2: Mission, Output contract (with both inline structure AND citation of `docs/llm/lookup-contract.json`), Tool guidance, **Verb-blocklist** (full regex block in a fenced code block, exactly as SPEC §File 2 step 4 enumerates — DB, git, gh, HTTP, eval-pipe, filesystem destructive), Budget, Freshness, Refusal modes, Provenance section format, Confidence scale, Edge cases, Invariants.
- All regex patterns appear inside fenced code blocks (no rendering glitches with backticks).
- File ends with newline.

**Status:** [ ]
**DOCS:** external-lookup-agent
**Complexity:** medium

---

## T003 — Author human-tier contract doc (docs/human/lookup-contract.md)

**Files touched:** `docs/human/lookup-contract.md` (NEW)
**Depends on:** none (but should align with T001's content)
**Acceptance criteria:**
- ~1 page Markdown. Sections: Motivation, Envelope structure, STATUS values (when each applies), Provenance fields, Confidence scale, Examples (one for a web-doc lookup, one for a Kalshi ticker lookup — both showing the full STATUS + sections + ≤3 KB output).
- Examples are realistic (real-looking URLs, plausible Kalshi tickers like `KXHIGHCHI-26MAY24-T70`).
- File ends with newline.

**Status:** [ ]
**DOCS:** lookup-contract
**Complexity:** low

---

## T004 — Wire new concepts into docs/llm/INDEX.json

**Files touched:** `docs/llm/INDEX.json` (MODIFIED)
**Depends on:** T001, T002 (and T005 for the body file)
**Acceptance criteria:**
- Read INDEX.json first to confirm exact schema (key names, nesting under `concepts:` or top-level, `source_file` vs `source_files`).
- Add entry for `lookup-contract` with the SPEC's metadata.
- Add entry for `external-lookup-agent` with the SPEC's metadata.
- Both entries use today's UTC date for `last_updated`.
- JSON still validates (no trailing commas, balanced braces).
- No existing entries modified beyond what's required to maintain valid JSON ordering.

**Status:** [ ]
**DOCS:** lookup-contract, external-lookup-agent
**Complexity:** low

---

## T005 — Author per-concept JSON body for external-lookup agent

**Files touched:** `docs/llm/external-lookup-agent.json` (NEW)
**Depends on:** T002
**Acceptance criteria:**
- File is valid JSON.
- Schema matches existing per-concept JSONs (read `docs/llm/providers-registry.json` or similar to confirm).
- Required fields per SPEC §File 4b: slug=`external-lookup-agent`, title, summary, key_concepts (model tier, tool whitelist, output envelope, verb-blocklist categories), invariants (≤3 KB, STATUS first line, no raw HTML/JSON, verbatim commands), gotchas (prompt-injection risk, link-depth cap, cache dir gitignored), source_files=`["agents/external-lookup.md"]`.
- `last_updated`: today.

**Status:** [ ]
**DOCS:** external-lookup-agent
**Complexity:** low

---

## T006 — Update docs/llm/agents.json if it exists as an agent registry

**Files touched:** `docs/llm/agents.json` (MODIFIED, conditional)
**Depends on:** T002
**Acceptance criteria:**
- Read `docs/llm/agents.json` first. If it is an agent registry (lists existing agents by name with model + tools), append a row for `external-lookup` matching the frontmatter of T002.
- If `agents.json` is NOT an agent registry (e.g. it's about the agents.json concept itself rather than a registry), skip this task and document the skip in the implementer's return.
- If modified, JSON still validates.

**Status:** [ ]
**DOCS:** external-lookup-agent
**Complexity:** low

---

## T007 — Add external-lookup row to README.md agents table

**Files touched:** `README.md` (MODIFIED)
**Depends on:** T002
**Acceptance criteria:**
- Read `README.md` and locate the existing agents table/list.
- Insert a row for `external-lookup` matching the column structure of existing rows.
- One-line description matches T002's frontmatter `description:` field.
- No other README sections modified.

**Status:** [ ]
**Complexity:** low

---

## T008 — Cache dir scaffolding

**Files touched:** `z-harness/lookup-cache/.gitignore` (NEW)
**Depends on:** none
**Acceptance criteria:**
- Directory `z-harness/lookup-cache/` exists.
- `.gitignore` content is exactly:
  ```
  *
  !.gitignore
  ```
- File ends with newline.

**Status:** [ ]
**Complexity:** low

---

## T009 — Static verification of external-lookup agent (mechanical smoke test)

**Files touched:** none (verification only — no code changes if everything passes)
**Depends on:** T001, T002, T004, T005, T008
**Acceptance criteria:**
- `agents/external-lookup.md` frontmatter parses as YAML.
- Frontmatter has `name`, `description`, `model`, `tools` keys with the values from T002.
- Body contains a fenced code block with the verb-blocklist regex patterns.
- Each regex pattern in that block compiles as a Python `re` pattern with `re.IGNORECASE` (run a small Python check).
- `docs/llm/lookup-contract.json`, `docs/llm/external-lookup-agent.json`, and `docs/llm/INDEX.json` all parse as JSON.
- `docs/llm/INDEX.json` contains the `lookup-contract` and `external-lookup-agent` slugs.
- `z-harness/lookup-cache/.gitignore` exists with the expected content.
- Returns a structured pass/fail summary.

**Status:** [ ]
**Complexity:** medium

---

## T010 — Author staged qt-market-lookup agent file

**Files touched:** `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md` (NEW)
**Depends on:** T001, T002 (so the contract and the generic agent precedent both exist)
**Acceptance criteria:**
- File created at the staging path (NOT in z-harness's `agents/` dir — qt-bot agents do not live in z-harness).
- YAML frontmatter has `name: qt-market-lookup`, `description: <one-line per SPEC>`, `model: sonnet`, `tools: Bash, Read, Grep, Glob`.
- Body has the sections specified in SPEC §File 3: Mission, Contract reference (cites canonical contract slug), Tool guidance with `<KALSHI_CLIENT>` placeholder, **Verb-blocklist** (inherits external-lookup's full block PLUS qt-bot-specific trading verbs and `<PAPER_ENV_VAR>` placeholder), Domain enrichment, Budget, Refusal modes, Invariants, Edge cases.
- Placeholders `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` appear in the body — they will be substituted at deposit time in T011.

**Status:** [ ]
**DOCS:** qt-market-lookup (target repo: qt-bot)
**Complexity:** medium

---

## T011 — Discover qt-bot remote layout + resolve placeholders + deposit qt-market-lookup

**Files touched:** `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md` (READ + transformed); deposits to qt-bot remote `<qt-bot-agents-dir>/qt-market-lookup.md`
**Depends on:** T010
**Acceptance criteria:** uses the `qt-bot-remote` skill end-to-end:
- Discover on remote `zeke-pc`: (a) qt-bot agents directory path (try `~/dev/qt-bot/.claude/agents/`, then `~/dev/qt-bot/agents/`; if neither exists, halt and surface to user); (b) Kalshi client invocation (search `~/dev/qt-bot/scripts/kalshi*`, `cargo run -p kalshi*`, `python -m qt_bot.kalshi*`; record exact invocation discovered); (c) paper-vs-real env var name (search for `KALSHI_ENV|KALSHI_MODE|KALSHI_NETWORK|TRADING_ENV` in qt-bot's source/config).
- Take the staging file, substitute `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` with discovered values. Substitution happens on a local copy in the staging dir, not in-place on the original.
- scp the substituted file to the discovered remote agents dir.
- Verify on remote: file exists, `name:` line matches `qt-market-lookup`, YAML frontmatter parses cleanly.
- If any discovery step fails or yields ambiguous results, **halt deposit, do NOT improvise, surface findings to user**.
- Implementer returns: discovery results (paths + invocation + env var), deposit confirmation, verify outcome.

**REMOTE_VERIFY:** ssh zeke-pc 'test -f <agents-dir>/qt-market-lookup.md && head -10 <agents-dir>/qt-market-lookup.md'

**Status:** [ ]
**Complexity:** high

---

## T012 — Static verification of deposited qt-market-lookup (remote)

**Files touched:** none (verification only)
**Depends on:** T011
**Acceptance criteria:**
- Via `qt-bot-remote` skill, on `zeke-pc`:
  - Deposited file exists at the path T011 reported.
  - Frontmatter parses as YAML.
  - `name:` value is exactly `qt-market-lookup`.
  - `model:` value is `sonnet`.
  - Body contains the verb-blocklist fenced block AND the trading-verb extensions.
  - Placeholders `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` no longer appear in the deposited file (substitution worked).
- Returns structured pass/fail.

**REMOTE_VERIFY:** ssh zeke-pc 'cd ~/dev/qt-bot && grep -c "<KALSHI_CLIENT>\|<PAPER_ENV_VAR>" <agents-dir>/qt-market-lookup.md'  # must return 0

**Status:** [ ]
**Complexity:** low

---

## Summary

12 tasks total. T001-T008 are pure-local file operations (low/medium complexity). T009 is local static verification. T010 stages the qt-bot agent locally. T011-T012 are the only remote operations (highest risk; gated on T011's discovery success).

**Test-case planning:** this plan does NOT touch money, signal generation, or financial computation — it's pure agent/docs infrastructure. **Running `/z-test` is not recommended for this plan.** Static verification in T009 + T012 is sufficient.

**Docs-touched flags:** T001, T003 → `lookup-contract`. T002, T005, T006 → `external-lookup-agent`. T010 → `qt-market-lookup` (qt-bot side, not tracked by z-harness's docs/llm).
