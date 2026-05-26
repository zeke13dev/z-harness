MODE: final-review-2pronged

## Lookup-Subagent Implementation: Cross-Task Faithfulness & Spec Sufficiency

### Background

The lookup-subagent plan introduces two subagents sharing one published output contract:
- `external-lookup` (haiku, z-harness) — generic WebFetch/WebSearch/Bash lookup with verb-blocklist
- `qt-market-lookup` (sonnet, staged for qt-bot) — Kalshi/weather-market enrichment

**Approved decision D2:** user override on Bash inclusion despite exfiltration risk (verb-blocklist mitigation). **Tasks T011/T012 are REMOTE-SKIPPED** (require qt-bot-remote skill on zeke-pc); **they do NOT appear in the cumulative.diff** — only T001-T010 are implemented.

### Inputs

**SPEC.md** commits to:
- Verb-blocklist covering six categories: DB writes, git mutations, gh API mutations, HTTP mutations (curl-d/wget-postdata), eval/pipe, filesystem destructive
- Contract lives at `docs/llm/lookup-contract.json` (canonical)
- Two-tier docs: LLM JSON (`docs/llm/lookup-contract.json`, `docs/llm/external-lookup-agent.json`) + human (`docs/human/lookup-contract.md`)
- INDEX.json entries use schema with keys `source_files` (plural), `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary`
- Concept JSON schema (`docs/llm/*.json`) uses `key_invariants` / `key_files` instead of SPEC's literal `source_files`/`invariants` (T001 retry fixed this)

**cumulative.diff** (8 files, 580 insertions):
1. README.md — external-lookup row added ✓
2. agents/external-lookup.md — 151 lines (full agent) ✓
3. docs/human/lookup-contract.md — 183 lines (human tier) ✓
4. docs/llm/INDEX.json — two new entries (lookup-contract, external-lookup-agent) ✓
5. docs/llm/external-lookup-agent.json — 19 lines (LLM tier concept) ✓
6. docs/llm/lookup-contract.json — 18 lines (contract JSON) ✓
7. z-harness/lookup-cache/.gitignore — 2 lines ✓
8. z-harness/plans/lookup-subagent/staging/qt-market-lookup.md — 175 lines (staged, not deployed) ✓

### Questions for Codex

**Prong A — Faithfulness to SPEC.md:**

1. **Verb-blocklist completeness:** SPEC §File 2 step 4 enumerates six categories (DB, git, gh, HTTP, eval-pipe, filesystem destructive). In cumulative.diff `agents/external-lookup.md` L89-L114, are all six patterns present and correctly formed as Python regexes?

2. **INDEX.json schema:** SPEC §File 4 says to use the **existing** schema from INDEX.json. The diff shows:
   - lookup-contract entry has keys: `slug`, `source_files` (plural), `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary`
   - external-lookup-agent entry has same keys
   
   Does this match the **existing** INDEX schema shown in the INDEX.json snapshot, and are there any inconsistencies across the two new entries?

3. **Concept JSON schema drift:** The diff shows `docs/llm/lookup-contract.json` and `docs/llm/external-lookup-agent.json` use `key_invariants` / `key_files` (not `invariants` / `source_files`). Is this the corrected T001 retry schema that matches other existing concept JSONs like `providers-registry.json`? SPEC §File 4b says "matches existing concept JSONs" — confirm alignment.

4. **Contract reference consistency:** 
   - agents/external-lookup.md L65 cites `docs/llm/lookup-contract.json` ✓
   - docs/human/lookup-contract.md L366-369 cites it via doc-fetcher ✓
   - qt-market-lookup.md L508 cites `<z-harness-plugin>/docs/llm/lookup-contract.json` with fallback
   
   Any dangling references or paths that don't exist?

5. **README row faithfulness:** cumulative.diff shows README.md line 9 matches `agents/external-lookup.md` frontmatter description verbatim?

6. **qt-market-lookup verb-blocklist:** cumulative.diff staging/qt-market-lookup.md L536-L583 — does it inherit ALL of external-lookup's patterns (DB, git, gh, HTTP, eval) PLUS the trading-specific patterns (place_order, cancel_order, buy, sell, etc.)? Are the trading patterns correctly formed?

**Prong B — Spec Sufficiency & Gaps:**

1. **T001 Retry Schema Correction:** SPEC File 4 initially says `source_files`/`invariants` as literal JSON keys, but T001 implemented it using `key_invariants`/`key_files` (per existing JSONs). Should SPEC §File 4b be amended to call out this correction?

2. **Edge case — cache-key collision:** SPEC §File 2 step 5 says normalized query = lowercase + collapse whitespace + strip. Two distinct queries could hash to the same SHA256 after normalization (unlikely but possible). Should SPEC address cache-key format or versioning?

3. **Confidence degradation ambiguity:** SPEC §File 2 step 6 says "if cache is >24h old, mark confidence: low". But SPEC does not define what happens if:
   - A fresh fetch and a stale cache both exist (which one wins?)
   - Cache freshness conflicts with source freshness (e.g. a 1h-old cache of a 5-day-old web page)?
   
   Should SPEC clarify cache-vs-source precedence?

4. **qt-market-lookup paper-env-var enforcement:** SPEC §File 3 says the agent must reject commands that omit `<PAPER_ENV_VAR>=paper`. But cumulative.diff staging/qt-market-lookup.md L585-L589 references `<PAPER_ENV_VAR>` as a placeholder to be substituted at T011 deposit time. What prevents the Kalshi client from being invoked without the prefix if deposit never happens (T011/T012 are remote-skipped)?

5. **Provenance `commands:` truncation rule:** SPEC §File 2 step 8 says "verbatim" in provenance, "display-side truncation … only in Answer". But if a command is 2 KB long (e.g. a massive `jq` filter), recording it verbatim pushes the response over 3 KB. Should SPEC clarify the 3 KB cap rule: is it hard (reject, drop to raw-artifact), or soft (truncate commands)?

6. **No cache expiry policy:** SPEC does not address: how long should entries in `z-harness/lookup-cache/` be kept? Should implementers / users garbage-collect them? Should the agent refuse if cache is too old vs. just degrade confidence?

7. **Agent lifecycle gap:** SPEC defines contract + agent file + docs, but does not address:
   - How is the agent dispatched (Agent(...) call syntax, model tier, tool whitelist)?
   - What happens if main thread needs to force a fresh (non-cached) lookup?
   - What is the retry budget if WebFetch + WebSearch both fail?

---

**Output: For each finding, cite source (e.g. agents/external-lookup.md:L63 or SPEC.md §File 2) and severity (blocker | major | minor). Keep output <4 KB.**
