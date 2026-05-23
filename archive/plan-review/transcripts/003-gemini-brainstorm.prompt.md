MODE: brainstorm

TOPIC: Enrich the two-tier docs system so docs/llm/ carries curated "memories" — anti-patterns, paths tried and abandoned, invariants, gotchas — alongside the current structural concept→file:line pointers. Also explore whether to add a faster lookup layer (ripgrep-friendly reverse index, embedding search, richer INDEX.json keywords) so doc-fetcher / a new docs-search agent can locate relevant concepts more reliably.

GOAL: when an orchestrator would normally spawn Explore, it instead consults a docs layer that returns both (a) exact files of interest and (b) curated context/memories that aren't derivable from the code itself.

## Current LLM-tier JSON shape

```json
{
  "concept": "<kebab-case-name>",
  "last_updated": "YYYY-MM-DD",
  "covers_spec": "<slug>/<run-id> or 'none'",
  "source_file": ["<paths>"],
  "confidence": "high|medium|low",
  "entry_points": [
    {"file": "<path>", "line": <int>, "symbol": "<name>", "kind": "fn|struct|const|module", "summary": "<=80 chars>"}
  ],
  "depends_on": ["<other-concept-slugs>"],
  "consumed_by": ["<other-concept-slugs>"],
  "invariants": ["<short statements>"],
  "gotchas": ["<short statements>"]
}
```

`invariants` and `gotchas` already exist but are short statements. No field for "things we tried and dropped", "open questions", "performance traps", "decision rationale", or provenance ("this came from incident X, date Y").

## INDEX.json shape

```json
{ "slug": "...", "source_file": [...], "last_updated": "...", "confidence": "...", "depends_on": [...], "consumed_by": [...], "summary": "<=120 chars" }
```

Search today: doc-fetcher (Haiku) reads INDEX.json, picks 1-3 entries by case-insensitive substring match on slug/summary. No keyword list, no tags, no full-text index.

## doc-fetcher contract

- Inputs: query, repo_root, depth (summary/standard/deep), optional relevant_concepts
- Reads INDEX.json, picks 1-3 concepts, reads their JSONs, returns ≤2 KB synthesis with file:line
- Cap: 8 Reads total. Never greps the codebase.
- Returns STATUS: no_match if INDEX has no concept matching the query.

## Where doc-fetcher fits

Global rule: dispatch doc-fetcher BEFORE Explore. Use its return to constrain Explore (or skip Explore entirely). User is proposing inserting a faster/richer doc-search step before/in-place-of Explore.

## Two halves of the ask

1. **Content enrichment** — LLM tier should carry curated memories not derivable from code: paths tried and abandoned, anti-patterns, decision rationale, incident-driven gotchas.
2. **Lookup-layer upgrade** — replace/augment doc-fetcher's substring match with ripgrep over a flattened searchable file, embedding search, richer keyword/tag taxonomy, or a dedicated docs-search subagent.

## Open questions

- Index format — flat ripgrep target / embedding store / enriched INDEX.json tags / hybrid?
- Authoring path — who writes memories? /z-improve retros? /z-debug post-mortems? inline during /z-plan? human-edited docs/human/ that doc-updater extracts?
- Decay / staleness — provenance + date on each memory so future readers can judge relevance?
- Replace vs augment doc-fetcher — new agent type (docs-search) or enrich the existing index doc-fetcher reads?
- Two-tier sync — memories in LLM tier only are invisible to humans; in human tier they need reliable extraction.
- Cost — doc-fetcher caps at 2 KB synthesis and 8 Reads. How big can memories grow before that binds?

---

TASK: Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
