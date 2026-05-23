# Escalation: /z-brainstorm + /z-research design

**Triggered:** /z-plan-light auto-bail, Phase 0 (pre-Phase-1).

## What was requested
Design two new z-harness commands as a coherent pair:
- `/z-brainstorm <topic>` — cheap parallel idea generation, no plan commitment.
- `/z-research <question>` — heavier doc-fetcher + Explore + cross-LLM perspective dump, no plan commitment.

Both feed downstream into `/z-plan` (or one into the other).

## Why this is past /z-plan-light scope

**File count:** 2 commands + 2 skill mirrors + 1-2 new subagent defs + README updates ≈ 6-8 files. Light-mode threshold is >5.

**Decisions:** at least 5 non-obvious decisions surfaced before Phase 1:
1. Do brainstorm + research share a common subagent (e.g. an `ideator` agent) or have distinct ones?
2. What is the artifact contract that `/z-plan` Phase 0 reads (BRAINSTORM.md vs RESEARCH.md vs a unified PRECONTEXT.md)?
3. Does `/z-research` dispatch the existing capped `Explore` subagent, or a new uncapped one (and if uncapped, what's the cost guardrail)?
4. What model do the parallel brainstorm dispatches run on — same Sonnet, model-diverse (Sonnet + Opus + Haiku for framing diversity), or main thread plus N subagents?
5. Does `/z-plan` need a new flag / detection logic to recognize "I was seeded by brainstorm/research" and skip its own Phase 0 premise check accordingly?

Light-mode threshold is >2 decisions.

**Coupling:** the two commands aren't independent. Designing them in isolation risks artifact-shape mismatch where `/z-plan` can read one but not the other.

## Recommended paths

1. **`/z-plan brainstorm-and-research` (full plan).** Treat the two commands as one coherent feature — design both their artifacts, their shared subagent (if any), and the `/z-plan` Phase-0-seed integration as one SPEC. ~1 hour of planning; ships clean and consistent.
2. **Split into two separate `/z-plan-light` runs.** Pick the simpler one first (`/z-brainstorm` is lighter; ship it, learn from it, then design `/z-research` with that feedback). Accept that the artifact contract may not match perfectly and we'll harmonize later.
3. **Discuss conversationally first (no harness invocation), then pick a path.** Talk through the two designs in chat, sketch artifact shapes, then pick `/z-plan` or `/z-plan-light` once we know what we're building.

My recommendation: **option 3 → then option 1.** The artifact-contract question (#2 above) is the linchpin — if we design BRAINSTORM.md and RESEARCH.md so `/z-plan` reads them with one common parser, the two commands become orthogonal and could even be parallelized later. That design call deserves cross-LLM input from inside `/z-plan` (full mode), not a rushed light-mode pass on each command separately.
