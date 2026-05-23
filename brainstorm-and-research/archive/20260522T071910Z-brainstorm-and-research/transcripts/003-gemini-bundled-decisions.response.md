Gemini consultation response on brainstorm-and-research decisions.

## Summary

Gemini reviewed all 4 consult-flagged decisions and provided explicit recommendations with reasoning and interaction analysis.

---

### D1. Artifact contract: distinct files vs unified PRECONTEXT.md

**Recommendation: A (Distinct artifacts: `BRAINSTORM.md`, `RESEARCH.md`)**

**Reasoning:** This aligns with the existing "slug-as-workspace" pattern where `FIX.md`, `SPEC.md`, and `PLAN.md` coexist. Phase 0 detection logic remains surgical: if a file exists, its context is loaded. Unified schemas (`PRECONTEXT.md`) tend to become "junk drawers" that require complex versioning and conditional parsing.

**Tradeoffs / risks:** 
- `/z-plan` Phase 0 must now be aware of two additional file patterns
- If a user runs both, the order of precedence or merging strategy needs to be defined (usually Brainstorm first, then Research as the "grounding" layer)

**Anything missed?** 
- Consider a "Source Attribution" section in the final `SPEC.md` that notes which artifacts (Brainstorm/Research) contributed to the requirements

**Interactions:** Enables the "A" choice in D4 (shared slug).

---

### D2. Should Claude be one of the 3 ideators in /z-brainstorm?

**Recommendation: D (Claude subagent + Codex + Gemini + Anti-bias guardrails)**

**Reasoning:** The primary value of the consult/ideate pattern is vendor diversity. Excluding Claude because the orchestrator is Claude loses a high-quality perspective. Invoking Claude as a *subagent* provides a clean slate (fresh context) which is often enough to break the "echo chamber" effect.

**Tradeoffs / risks:** 
- The orchestrator (Claude) may still find its own subagent's output more "agreeable" during synthesis despite anti-bias guardrails

**Anything missed?** 
- Option **B** (Claude-Haiku) is a strong alternative if latency/cost is a concern
- Haiku is often more "creative/lateral" while Sonnet is "logical/rigorous"

**Interactions:** Affects the synthesis logic in the `/z-brainstorm` skill; it must explicitly compare the three outputs rather than just merging them.

---

### D4. Slug derivation across the chain

**Recommendation: A (Shared slug by default)**

**Reasoning:** Ergonomics is king for CLI chaining. If I run `/z-brainstorm fix-auth`, I expect `/z-research fix-auth` and `/z-plan fix-auth` to "just work" by looking in the `z-harness/fix-auth/` directory. This treats the slug as a *Task Identity* rather than a *Command Identity*.

**Tradeoffs / risks:** 
- Collision risk if a user reuses a slug for a completely different task, but this is already a risk with `/z-plan-light` and `/z-plan`

**Anything missed?** 
- Ensure that `archive/<run-id>/` captures the specific command that created it so that a `BRAINSTORM` run doesn't overwrite a `RESEARCH` run's events/logs

**Interactions:** Directly supports D1 and D5 by ensuring artifacts are co-located.

---

### D5. How is RESEARCH.md incorporated into /z-brainstorm ideators?

**Recommendation: A + B Hybrid (Inline with size-based fallback to summary)**

**Reasoning:** Codex and Gemini consultants cannot read the repository. Inlining is the only viable path for them. For the Claude ideator, inlining is more reliable than "Read by reference" which can fail if pathing is ambiguous or depth is too high.

**Tradeoffs / risks:** 
- Large research notes will consume token budget
- The 20 KB cap is a sensible heuristic for "standard" tasks

**Anything missed?** 
- For the fallback (Option B), the summary should be "Extractive" (preserving specific names, paths, and constraints) rather than "Abstractive" (generalizing the problem), as brainstormers need the specific "terrain" to be useful

**Interactions:** Dependent on D1 (knowing to look for `RESEARCH.md`) and D4 (knowing it's in the same slug dir).

---

## Overall Interaction Analysis

Gemini flagged a cohesive "Work Unit" model: choosing **A** for D1/D4 and **A/B** for D5 creates a unified lifecycle where the slug directory becomes the source of truth for a single task's journey from ideation → research → planning. The recommendation for **D** on D2 (Claude + anti-bias guardrails) ensures model diversity at the ideation layer despite the same orchestrator.

---

### Wall time: ~36000ms (with Gemini rate-limit retries)

