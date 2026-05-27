MODE: bundled-decisions

## Problem Statement

Planning v1 of /z-research as meta-orchestrator per BRAINSTORM.md chosen_framing: codex. The new /z-research will:
- Rename current /z-research → /z-map (artifact: MAP.md)
- Introduce new /z-research as orchestrator that dispatches /z-map and/or /z-brainstorm conditionally, then runs adversarial synthesis panel to produce RESEARCH.md with approach decision matrix

Current status: 5 consult-flagged decisions at the planning cap. All tentative calls need Codex validation against each other for interactions and cross-cutting concerns.

---

## Consult-Flagged Decisions

### D1: Two-step handoff vs inline dispatch
**Decision:** How does new /z-research invoke /z-map and /z-brainstorm sub-commands?

**Options:**
- (a) Two-step handoff (/z-uplift precedent): orchestrator prints `/z-map ...` command + state-marker, exits. User re-invokes /z-research; resume detects state and continues. Multi-invocation.
- (b) Inline dispatch via Agent(): orchestrator dispatches skill code directly inside its own Phase, never exits until done. Single-invocation.
- (c) Hybrid: inline for /z-brainstorm (cheap ≤200K); two-step for /z-map (heavy ≤2M) and synthesis panel.

**Tentative call:** (b) inline dispatch. User said "more / extra brainstorming" — one command, one click. Cost gate at invocation addresses "too expensive to run accidentally."

**Trigger:** affects user-visible command pipeline; cross-module impact vs /z-uplift precedent; hard to reverse.

---

### D2: Dispatch decision mechanism
**Decision:** How does Phase 0.5 of /z-research decide whether to dispatch /z-map and/or /z-brainstorm?

**Options:**
- (a) Deterministic heuristic: if MAP.md absent → suggest /z-map; if BRAINSTORM.md absent → suggest /z-brainstorm. Pure shell logic.
- (b) Haiku dispatcher agent: reads slug state + topic + freshness, returns `RUN_MAP: yes|no`, `RUN_BRAINSTORM: yes|no`. Single ~10K token call.
- (c) User-driven AskUserQuestion: with options derived from state ("MAP.md exists from 3 days ago and looks aligned — skip /z-map?"). Defaults to "run both" if no clear skip signal.

**Tentative call:** (c) user-driven with state-aware defaults. "Orchestrator decides... but highly suggested" = AskUser-with-strong-default. Heuristic (a) is too rigid; Haiku dispatcher (b) over-engineers a yes/no decision.

**Trigger:** core mechanism of the new command; user-visible; affects how often each sub-command runs.

---

### D5: RESEARCH.md schema — exact section order + frontmatter
**Decision:** What is the canonical schema?

**Options:**
- (a) BRAINSTORM literal 10 sections in order listed.
- (b) Same sections, different order (e.g. lead with approach matrix as headline finding).
- (c) Compress to fewer sections (e.g. merge "rejected/weak framings" into approach matrix as column).

**Tentative call:** (b) reordered: lead with `## Approach decision matrix` (headline value-add), follow with `## Cross-artifact contradictions` (second value-add), then supporting context (terrain summary, brainstorm frame space, design axes, etc.), end with `## Recommended next-command inputs for /z-plan` (actionable handoff).

**Frontmatter:** `artifact: research`, `slug`, `generated_at`, `command`, `dispatch_decision: {map: <ran|reused|skipped>, brainstorm: <ran|reused|skipped>}`, `source_artifacts: [MAP.md@<sha>, BRAINSTORM.md@<sha>]`, `synthesizer_models: {conservative: claude-opus, expansive: codex, adversarial: gemini, judge: opus}`, `status: complete|abandoned`, `tripwires_fired: []`.

**Trigger:** defines public API (downstream /z-plan parser); hard to rename later; affects ≥1 reader.

---

### D8: /z-plan one-way gate — exact integration point
**Decision:** How does /z-plan detect and prefer RESEARCH.md over component files?

**Options:**
- (a) Setup step 9 amendment: if RESEARCH.md exists + fresh + valid frontmatter (`artifact: research`, `status: complete`), inject ONLY RESEARCH.md into premise check; ignore MAP.md + BRAINSTORM.md.
- (b) Same detection, but always inject all three artifacts; /z-plan downstream logic decides which to use per phase.
- (c) New Setup step 9.5 between BRAINSTORM-check and RESEARCH-check explicitly handling new RESEARCH.md schema (vs old "RESEARCH.md = map" schema).

**Tentative call:** (a) — one-way gate. The whole point is to provide a richer single-input. Old behavior (read MAP.md + BRAINSTORM.md separately) becomes a fallback ONLY when RESEARCH.md missing. /z-plan's Setup step 9 needs to distinguish OLD RESEARCH.md (now MAP.md) from NEW RESEARCH.md via `artifact:` frontmatter field.

**Trigger:** changes /z-plan's public intake contract; affects how all future plans read precontext; hard to reverse.

---

### D10: planning-router routing rule for new /z-research
**Decision:** When should planning-router recommend the new /z-research?

**Options:**
- (a) Replace existing /z-research (now /z-map) recommendation with new /z-research when topic has BOTH terrain uncertainty AND approach uncertainty.
- (b) Keep /z-map (old /z-research) recommendation; add new /z-research only when explicitly requested.
- (c) Recommend /z-map when terrain unclear; recommend /z-research when approach-space unclear (orthogonal axes).

**Tentative call:** (c). The two commands serve different epistemic needs. Reason codes: `needs_terrain_map` → /z-map; `needs_approach_synthesis` → /z-research.

**Trigger:** affects planning-router public contract; public surface (route recommendations); hard to reverse.

---

## Context: /z-uplift Two-Step Handoff Precedent

From z-uplift.md:2430, the two-step handoff pattern is:
1. Orchestrator detects state (e.g., phase incomplete)
2. Prints user-facing command with state marker (e.g., `/z-implement-all --resume`)
3. Exits; user re-invokes
4. Resume-handler detects state marker and continues from checkpoint

This adds ~30s wall-time per handoff (user re-invocation + orchestrator state-recompute) but provides:
- Transparent cost control (user sees each invocation's cost upfront)
- Clear state mutation points (each invocation can be audited for changes)
- Single-phase-at-a-time determinism (subagent failures don't cascade)

Costs: ceremony for single-invocation workflows; requires resilient state files.

---

## Context: planning-router Routing Semantics

From agents/planning-router.md:
- `needs_research` → /z-research (NEW: terrain map)
- `needs_brainstorm` → /z-brainstorm (ideation under known terrain)
- `needs_terrain_map` → /z-map (current /z-research, renamed)
- `needs_approach_synthesis` → /z-research (NEW: approach decision matrix)

Current planning-router distinguishes `terrain_uncertain` (line 134) vs `approach_uncertain` (line 135). D10 proposes splitting the old single `/z-research` recommendation into two orthogonal reason codes.

---

## Cross-Cutting Concerns

1. **User mental model:** single-invocation (D1:b) makes /z-research feel like a "super-brainstorm" (Codex's framing warns against this). Two-step (D1:a) makes the dispatch logic visible but adds ceremony.

2. **Cost visibility:** D2:c (AskUser dispatch) gives users control at invocation time. If D1:b (inline), cost gate happens once at start; if D1:a (two-step), cost gate happens per sub-command. Different UX.

3. **State safety:** D2:c (user-driven dispatch) requires storing dispatch decision in RESEARCH.md frontmatter (D5's `dispatch_decision` field) so phase-resumption knows what ran. D1:b (inline) stores decision in process memory only.

4. **Schema forward-compatibility:** D5's frontmatter has `source_artifacts@sha` and `dispatch_decision`. If we later add an optional `--probe` flag (mentioned as v2 feature), the schema needs room. Current spec leaves room (frontmatter is extensible).

5. **/z-plan integration (D8):** The one-way gate (D8:a) requires /z-plan to distinguish `artifact: research` frontmatter value. Existing RESEARCH.md files in-the-wild don't have this field (they're old). D8:a needs a fallback: if RESEARCH.md lacks frontmatter, treat as old MAP.md semantics and fall back to reading MAP.md + BRAINSTORM.md separately. This is defensive and preserves backward compatibility but adds a validation step in /z-plan Setup.

---

## Ask Codex

For each consult-flagged decision, recommend with:
1. Reasoning (≤3 sentences)
2. Tradeoffs / risks flagged (bullets)
3. Interactions with other decisions (bullets)
4. Any missed considerations

Prioritize decision interactions and cross-cutting concerns. User said this is phase 3 of /z-plan workflow — final checkpoint before implementation.
