# Phase 1 scaffolding — doc-memories brainstorm

## Topic

Enrich the two-tier docs system so `docs/llm/` carries curated "memories" —
anti-patterns, paths we tried and abandoned, invariants, gotchas — alongside
the current structural concept→file:line pointers. Also explore whether to
add a faster lookup layer (ripgrep-friendly reverse index, embedding search,
richer INDEX.json keywords) so doc-fetcher / a new docs-search agent can
locate relevant concepts more reliably.

Goal: when an orchestrator would normally spawn Explore, it instead consults
a docs layer that returns both (a) exact files of interest and (b) curated
context/memories that aren't derivable from the code itself.

## Current state of the system (verbatim from agent files)

### LLM-tier JSON shape (from `agents/doc-updater.md`)

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

So `invariants` and `gotchas` fields already exist but are short statements,
not narrative memories. There is no field for "things we tried and dropped",
"open questions", "performance traps", "decision rationale", or
provenance/source ("this gotcha came from incident X on date Y").

### INDEX.json shape (from `skills/z-init-docs/SKILL.md`, Phase 3)

Each entry is:

```json
{
  "slug": "...",
  "source_file": [...],
  "last_updated": "...",
  "confidence": "...",
  "depends_on": [...],
  "consumed_by": [...],
  "summary": "<=120 chars — taken from first entry_point.summary>"
}
```

Search today: doc-fetcher (Haiku) reads INDEX.json and picks 1-3 entries by
case-insensitive substring match against `slug` and `summary`. No keyword
list, no tags, no full-text index over the per-concept JSONs.

### doc-fetcher contract (from `agents/doc-fetcher.md`)

- Inputs: `query`, `repo_root`, `depth` (summary | standard | deep),
  optional `relevant_concepts`.
- Reads INDEX.json, picks 1-3 matching concepts by slug/summary keyword
  match, reads their JSONs, returns ≤2 KB synthesis with file:line markers.
- Cap: 8 Reads total. Never greps the codebase ("that's the caller's job").
- Returns `STATUS: no_match` if INDEX has no concept matching the query.

### Where doc-fetcher fits in the orchestrator loop

From global `~/.claude/CLAUDE.md`:

> Before any Explore dispatch, spawn doc-fetcher with the task keywords.
> Use its return to constrain the subsequent Explore prompt (or skip Explore
> entirely if doc-fetcher already covered the question).

So today's flow is: doc-fetcher (cheap synthesis from curated docs) → Explore
(grep/read codebase to fill gaps). The user is proposing to insert a
faster/richer doc-search step before or in place of Explore.

### Two-tier human/LLM split

- `docs/human/<slug>.md` — narrative markdown for humans (Overview, Key
  entry points, Interactions, Edge cases, Examples).
- `docs/llm/<slug>.json` — token-compacted JSON above.
- They MUST stay in sync (same entry points, same dependency graph)
  per doc-updater hard rule.

The human tier already has free-form "Edge cases / gotchas" and "How it
interacts with others" prose. The LLM tier compacts that into short
`invariants` and `gotchas` strings.

## User's framing of the gap

Quoting the user directly:

> shouldn't the llm docs also have the "memories". i think we need to at
> least look into generating better / more rich docs that contain small
> "memories" / like paths we don't want to do.

And earlier:

> the docs also provide extra information / light memories too so it's
> stronger than just reverse indexed codebase.

So the ask has two distinguishable halves:

1. **Content enrichment** — LLM tier should carry curated memories that
   aren't derivable from the source code: paths tried and abandoned,
   anti-patterns, decision rationale, incident-driven gotchas.
2. **Lookup-layer upgrade** — replace or augment doc-fetcher's
   "Haiku reads INDEX.json and substring-matches" with something faster
   and/or more recall-friendly: ripgrep over a flattened searchable file,
   embedding search, richer keyword/tag taxonomy, or a dedicated
   docs-search subagent.

Both halves are in scope; ideators should consider their interaction
(e.g. if memories are well-tagged, lookup may be the easy part — or
the reverse).

## Open questions worth ideators' attention

- **Index format** — flat ripgrep target, embedding store, enriched
  INDEX.json keywords/tags, or hybrid?
- **Authoring path** — who writes memories? `/z-improve` retros?
  `/z-debug` post-mortems? Inline during `/z-plan`? Human edits to
  `docs/human/` that doc-updater extracts into the LLM tier?
- **Decay / staleness** — memories without provenance rot; how do we
  attach "from incident X, 2026-03-04" so future readers can judge
  relevance?
- **Replace vs augment doc-fetcher** — does this become a new agent
  type (`docs-search`), or does doc-fetcher get a richer index to read?
- **Two-tier sync** — if memories live only in `docs/llm/`, they're
  invisible to humans; if they live in `docs/human/`, doc-updater has
  to extract them reliably.
- **Cost** — the whole point of the LLM tier is staying cheap. How big
  can memories grow before doc-fetcher's 2 KB cap and 8-Read budget
  start to bind?

No `docs/llm/INDEX.json` exists in this repo (z-harness itself); no
`RESEARCH.md` exists for this slug. Scaffolding is the topic statement
+ verbatim quotes of the relevant agent contracts.
