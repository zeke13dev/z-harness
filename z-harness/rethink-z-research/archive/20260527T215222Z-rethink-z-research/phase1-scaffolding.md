# Phase 1 scaffolding — rethink-z-research (RESTART)

## Topic (refined per user)

**/z-research is a HIGHER-ORDER ORCHESTRATOR**, not a sibling. It composes `/z-map` (current /z-research, renamed) and/or `/z-brainstorm` as sub-steps, then runs a deeper synthesis layer to produce a mega-brainstorm — richer than `/z-brainstorm` alone. The depth is achieved by sequencing/dispatching smaller tools + layered meta-synthesis.

Brainstorm:
1. What does `/z-research` dispatch and in what order? Always map → brainstorm → synthesize? Or dynamic dispatch based on topic state (e.g. skip /z-brainstorm if user already has one)?
2. Is the meta-synthesis layer a single Sonnet/Opus agent reasoning over both artifacts, or parallel synthesizers that vote?
3. Does it consume an existing BRAINSTORM.md (if present) or always generate fresh?
4. Output artifact: RESEARCH.md (rename'd from old), MEGA-BRAINSTORM.md, something new?
5. Cost tier: likely 3–6M tokens (nests other commands).
6. Naming impact: current /z-research becomes /z-map (rename accepted in this framing).

## Scaffolding (carried over from prior run + refined)

### Existing pieces this composes
- **/z-map** (rename of current /z-research): up to 3 parallel Explores (Haiku) on distinct facets, bundled Gemini+Codex critique, emits MAP.md (was RESEARCH.md) with `## No-recommendation` invariant. ≤2M tokens.
- **/z-brainstorm**: 3 vendor-diverse ideators, identical scaffolding, 5-section framings, mandatory anti-bias. Emits BRAINSTORM.md with chosen_framing. ≤200K tokens.

### Key shift from prior round
The prior brainstorm assumed /z-research would be a SIBLING command (parallel agents each doing one approach spike). The user is saying NO — /z-research should be a meta-orchestrator that INVOKES /z-map AND /z-brainstorm internally as sub-steps, then layers meta-synthesis. Different from /z-spike (which was a parallel-implementation-spike sibling).

### Implications to brainstorm
- Sub-step dispatch policy: serial (/z-map → /z-brainstorm → synthesize) vs conditional (skip map if MAP.md exists fresh; skip brainstorm if BRAINSTORM.md exists with chosen_framing) vs always-fresh.
- Meta-synthesis shape: what does it ADD beyond what /z-map + /z-brainstorm already produce? Concrete proposals: cross-artifact consistency checks; surface contradictions between framings and terrain constraints; identify approach axes implicit in the framings then probe-test them; produce a structured "decision tree" or "approach matrix" that's richer than either input alone.
- /z-plan integration: does /z-plan consume RESEARCH.md (the new mega artifact) as a single richer input, OR continue to consume MAP.md + BRAINSTORM.md separately?
- Cost gate: must be user-confirmed at invocation (3-6M tokens is real money).
- Re-entry: if a user runs /z-research, then /z-brainstorm separately later, does /z-research's output go stale? Versioning + freshness checks like /z-research currently does for citations.

### Hallucination-mitigation considerations (graft from prior round)
The user wanted depth. Depth tempts agents to fabricate. If /z-research orchestrates, the sub-tools (/z-map, /z-brainstorm) already have their own anti-hallucination guards. The meta-synthesis layer needs ITS OWN guard — e.g. mandatory citation-back to MAP.md findings or BRAINSTORM.md framings for every synthesis claim.

### Open design questions for ideators
- Is "mega brainstorm" a single artifact or a directory of artifacts? (e.g. RESEARCH.md + research/approach-matrix.md + research/contradictions.md)
- Does the synthesis layer pick a winner, or stay neutral like /z-research currently does?
- Should /z-research itself have a /z-spike-like phase where it dispatches deeper approach probes after the initial map+brainstorm?

## Explore synthesis
(skipped)

## RESEARCH.md
(none — this slug is the topic itself)
