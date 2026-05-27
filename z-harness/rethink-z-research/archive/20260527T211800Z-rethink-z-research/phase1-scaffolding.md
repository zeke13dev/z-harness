# Phase 1 scaffolding — rethink-z-research

## Topic
Redesign /z-research. Current /z-research = surface-level terrain map (parallel Explores + cross-LLM critique). User wanted "/z-brainstorm on steroids" — deep dive on HOW to do a topic, multiple agents doing parallel exploratory design/impl investigations, then synthesized. Brainstorm the right shape: (a) rename current /z-research → /z-map and free /z-research for deep-dive; (b) keep current /z-research, add new command (/z-deepdive? /z-investigate?); (c) make this a --deep mode on /z-brainstorm. Cover: naming, scope, relationship to existing /z-brainstorm + /z-research, what parallel deep-dive agents produce, where it fits between /z-brainstorm (framings) and /z-plan (SPEC).

## Doc-fetcher synthesis: current state

### /z-brainstorm (cheap, ≤200K tokens)
- 3 vendor-diverse ideators (Claude+Codex+Gemini) in parallel, identical scaffolding.
- Returns 5-section framing per ideator: Framing / Core hypothesis / Risks / Plan implications / What would change my mind.
- Mandatory anti-bias check, mandatory Claude-favoring justification.
- Emits BRAINSTORM.md with `chosen_framing` (LIGHT/MEDIUM) or `chosen_pair` (HEAVY).
- Phase 0 scope-probe with axis taxonomy `[per_vendor, per_framing]`.
- HEAVY mode: per-chunk sub-flows + scope-reconciler → unified BRAINSTORM.md + (chunk × framing) selection matrix.

### /z-research (terrain map, ≤2M tokens with cost gate)
- Up to 3 parallel Explore subagents (Haiku) on distinct facets. EXPLORE_BUDGET user-gated (1 or 3).
- Bundled Gemini+Codex critique (parallel) — emit only Gaps / Errors / Missing constraints. **Forbidden from recommending an approach.**
- Emits RESEARCH.md with `## No-recommendation` section (mandatory, non-deletable). `research_temptation` event fires if a recommendation slips in during drafting.
- `explore_calls: 0-3` + `explore_failures` + `status: complete|complete_no_critique` in frontmatter.

### /z-plan auto-detection
- Reads BRAINSTORM.md and RESEARCH.md as precontext.
- Conflict-checks the two against each other.
- Uses RESEARCH.md for skip conditions (skip doc-fetcher if findings cite touched files; skip Explore if no open questions).
- Refuses to proceed past Phase 0 if BRAINSTORM.md is unfinalized.

### Key flow
Full depth: /z-research → /z-brainstorm → /z-plan
Common: /z-brainstorm → /z-plan
Tiny: /z-plan alone

### The gap the user is pointing at
- /z-research today is TERRAIN: where things are, what constraints exist, what's unknown. Citations + open questions.
- User wants something that ASKS HOW — multiple parallel agents each spike a different design/impl approach, return memos with prototypes/sketches, get synthesized.
- That's structurally closer to /z-brainstorm (parallel ideation) than /z-research (parallel mapping). But deeper than brainstorm — each agent actually investigates, not just frames.
- Naming options on the table: (a) rename current to /z-map + free /z-research for deep-dive; (b) new command /z-deepdive or /z-investigate or /z-explore-approaches; (c) /z-brainstorm --deep add-on.

### Constraints to respect
- The ≤200K tokens budget on /z-brainstorm vs ≤2M tokens on /z-research suggests cost-tier separation matters. A "deep dive" command will likely sit in the 2-5M range — heavier than both.
- Naming: existing /z-research has user-visible artifacts (RESEARCH.md), event names (precontext_source_deleted), skip-condition logic in /z-plan. Renaming has propagation cost.
- /z-plan's Phase 0 / Phase 1 doc-fetcher skip rules assume a specific RESEARCH.md shape (Findings: + Open questions:). A different artifact shape may need its own skip rules.
- The `## No-recommendation` invariant in /z-research is intentional — research SHOULD NOT recommend. A "deep dive that proposes approaches" must NOT inherit that constraint; it must do the opposite (each agent proposes ONE concrete approach).

## Explore synthesis
(skipped — Z_HARNESS_BRAINSTORM_EXPLORE unset)

## RESEARCH.md
(none for this slug)
