# Phase 3 — Final decisions after cross-LLM consult

Both consultants returned. They agreed on D5's shape (d) and broadly on D3's per-line format. They diverged substantively on D1 expires field, D2 strict-vs-hybrid taxonomy, D3 inclusion of source in the line format, and D4 tags-param-vs-memory_query.

For each accepted recommendation below: one reason it might be wrong, then my synthesis.

## D1 — Memory JSON schema: **(a) + (d)** [tentative call kept]

- **Gemini:** drop (d) — "don't build GC before shipping".
- **Codex:** keep (d) — backward-compatible insurance.
- **One reason Gemini might be wrong:** `expires` isn't GC. The 18-month auto-flag (D7) is the GC; `expires` is an author override on individual memories the author *knows* will rot (e.g. "this anti-pattern only applies pre-v2 migration"). Near-zero cost to keep; meaningful win when used.

**Final:** (a) + (d). Schema:
```json
{
  "type": "anti_pattern | abandoned_path | incident | performance_trap | decision_rationale | open_question",
  "text": "<=200 chars",
  "source": "incident:<slug> | spec:<plan-slug>/<run-id> | debug:<run-id> | human_review:<name>",
  "date": "YYYY-MM-DD",
  "tags": ["<kebab>"],
  "expires": "YYYY-MM-DD"   // optional
}
```

## D2 — Tag taxonomy: **(c) Hybrid + dedup pass** [tentative call kept, mitigation adopted]

- **Gemini:** (a) strict controlled set — protects ripgrep precision.
- **Codex:** (c) hybrid + doc-updater dedup/alias pass during /z-maintain-docs.
- **One reason Gemini might be wrong:** the seed controlled list is z-harness-author guesses. A real target repo (e.g. qt-bot) needs domain-specific tags like `bar-boundary`, `notional-sign`, `kalshi-trades` that I cannot pre-enumerate from inside z-harness.
- **One reason Codex might be wrong:** hybrid without enforcement drifts toward `perf` / `performance` / `speed` for the same concept. **Mitigation (from Codex):** doc-updater runs a normalize-and-deduplicate pass during /z-maintain-docs Phase 3. Adopt this — adds one task to TASKS.md.

**Final:** (c) hybrid. JSON schema validates `tags` items as kebab-case strings. `/z-suggest-memory` presents the recommended controlled set (~15 tags) as pre-selectable chips, allows free-form additions. doc-updater Phase 3 runs a dedup/alias pass that flags `perf` ↔ `performance` collisions for human review (does not auto-merge).

## D3 — MEMORIES-FLAT.md line format: **(d) + Gemini's source amendment**

- **Gemini:** modify (d) to include `[<source>]` — source is load-bearing provenance, stripping it loses critical context.
- **Codex:** keep (d) as-is.
- **One reason Codex might be wrong (i.e. Gemini's right):** ripgrep filtering by source kind (`-w "incident:"`) is a real use case — orchestrator searches for "all incident-derived memories on cache invalidation" using `rg '\[incident:.*\].*cache'`. Without source in the line, this requires re-Reading the per-concept JSON to filter.

**Final:** `[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)`. Example:
```
[strategy-router] [incident 2026-04-12] [incident:slippage-spike] cache invalidated on rebal so first 3 bars use stale spreads (tags: correctness, time-window)
[strategy-router] [abandoned_path 2026-02-08] [spec:rebalance-v2/run-3] tried sliding-window EMA, killed because regime detection lagged 4 bars (tags: signal, perf)
```

## D4 — doc-fetcher second-phase contract: **(d) + taxonomy-validated tags**

- **Gemini:** (b) separate `memory_query` — avoids LLM tag hallucination.
- **Codex:** (d) reuse query + optional tags.
- **One reason Gemini might be wrong:** raw `memory_query` pushes regex syntax to the caller (itself an LLM); LLMs write worse regex than they pick tags from a known list. Tag hallucination is mitigated by D2's controlled-set chips: if the caller asks for a tag not in the taxonomy, doc-fetcher logs `unknown_tag` and falls back to query-only — not a silent zero-hit failure.
- **One reason Codex might be wrong:** in the worst case, callers don't pass `tags` at all and we get noisy ripgrep results. Acceptable on day one — caller logging will reveal which queries miss, and we add tags incrementally.

**Final:** (d). doc-fetcher accepts `query` (reused) + optional `tags: [...]`. Tag values are validated against D2's controlled set; unknown tags emit `unknown_tag` log and are dropped (do not zero-hit the query). Defer `memory_query` and `memories_only` to a follow-up plan if logs show real need.

## D5 — /z-suggest-memory target-concept resolution: **(d) + Gemini's "create new concept" handoff**

- **Gemini:** (d) + escape hatch for cross-cutting / new-concept memories.
- **Codex:** (d) + concept_hints required from /z-debug + /z-improve return schema.
- **One reason Codex's "required hints" is right:** if /z-debug doesn't populate hints, /z-suggest-memory falls back to multi-select over all concepts — slow. Make `concept_hints` a required field in /z-debug PROBLEM.md and /z-improve return.
- **One reason Gemini's "GLOBAL" might be wrong:** a "GLOBAL" memories bucket becomes a junk drawer. **Counter:** Gemini's instinct is right but "GLOBAL" is the wrong solution — the right escape hatch is "create a new concept" via /z-init-docs handoff. That way cross-cutting concerns get their own concept (which they deserved anyway).

**Final:** (d). AskUserQuestion options when /z-suggest-memory is invoked:
1. Pre-selected concept from `concept_hints` (first hint, default)
2. Pick from other existing concepts (search-filtered list)
3. Create a new concept — hands off to `/z-init-docs --scope <new-slug>`, then resumes /z-suggest-memory with the new slug
4. Cancel — emits zero memories (allowed per the mandatory-call-not-mandatory-result rule)

`/z-debug` and `/z-improve` MUST populate `concept_hints` (add to their return schema as part of this plan).

---

## Cross-decision interactions confirmed

- **D1 ↔ D3.** Strict-prefix `source` requires the line-format to surface it (Gemini's D3 amendment makes this explicit). Both consultants flagged this.
- **D2 ↔ D4.** Hybrid taxonomy enables tag-filtered queries; controlled chips constrain LLM hallucination at the source.
- **D3 ↔ D4.** Per-line slug + source means ripgrep returns are self-contained; doc-fetcher post-processing is `rg | sort -u | head -3` for the concept-cap-at-3 budget.
- **D4 ↔ D5.** /z-suggest-memory can pass tag hints to doc-fetcher when invoked from retros to find prior similar memories (avoid duplicates). Soft dependency — defer concrete implementation.

## Shortcuts approved

**None.** All five decisions accept the robust long-lasting option. No Phase 5 shortcut approval needed.
