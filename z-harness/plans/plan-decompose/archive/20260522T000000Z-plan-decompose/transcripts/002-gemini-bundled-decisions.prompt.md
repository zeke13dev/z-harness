# MODE: bundled-decisions consultation

**FEATURE**: /z-plan-split (plan-decompose command) — pre-emptive scope splitter for "topic is too big for one /z-plan"

**SHAPE**: Main thread proposes 2-6 narrow scopes via AskUserQuestion → user confirms → N parallel `cluster-planner` subagents each produce SPEC/PLAN/TASKS for one narrow scope at `z-harness/<root>/<cluster>/` → main thread reconciliation (file-overlap detection) → writes MANIFEST → exits.

**ARCHITECTURAL CONTEXT**:

Existing /z-plan (10-phase full planning: Setup → Premise → Exploration → Decisions → Consult → SPEC/PLAN → Review → TASKS → Finalize):
- Phases 0–2: premise check, exploration, batch decisions doc
- Phase 2.5: user gate (approve decisions)
- Phase 3: bundled cross-LLM consult on *all* consult-flagged decisions (Gemini + Codex in one call each)
- Phases 6–9: SPEC/PLAN writing, final review, TASKS, archive

Existing /z-brainstorm (cheap 4-phase parallel ideation):
- Spawns 3 ideators (Claude Sonnet, Codex, Gemini) in parallel in Phase 2
- Anti-bias check (mandatory) in Phase 3
- User gate in Phase 3
- Phase 4 finalizes

Existing /z-implement-all (orchestration of task queue):
- Discovers plan slug, reads TASKS.md
- N=3 parallel task tracks per batch (file-overlap dedup)
- Per-track phases: spec-precheck → implement → review (with retry logic)
- Halt gates on spec_problem / decision_needed / needs_clarification
- Uses complexity-classifier to pick Sonnet (low/medium) or Opus (high) per task
- Hard caps: MAX_ATTEMPTS=2, MAX_TASK_WALL_MS=45min, MAX_BATCH_STALL_MS=30min

**THREE CONSULT-FLAGGED DECISIONS**:

---

## D2. `cluster-planner` agent — what phases does it run?

- **A.** Premise check + write SPEC/PLAN/TASKS only. No decision gate, no consult, no plan review. Fastest, weakest.
- **B.** A + light decision gate: if a non-obvious decision surfaces, return `STATUS: decision_needed` and let main thread handle sequentially. No per-leaf consult. *(tentative)*
- **C.** B + per-leaf cross-LLM consult on consult-flagged decisions.
- **D.** Mirror full /z-plan phases.

**Lean:** **B**. **Why consult?** Narrow scope = typically 0–1 non-obvious decisions. Cross-LLM consult per leaf multiplies cost (N leaves × 2 LLMs per decision). Concern: a leaf might unilaterally make a wrong call on a borderline-non-obvious decision that root reconciliation won't catch. **Ask Gemini:** Is B safe enough for narrow scopes (typical 0–1 non-obvious decisions), or should we pay for per-leaf consult on borderline-complex leaves? What's the cost/benefit tradeoff?

---

## D3. Reconciliation depth — what does main thread produce after leaves complete?

- **A.** File-path overlap only → write `SHARED-CONCERNS.md` listing detected overlaps as observations; do not auto-write a `shared/` plan. User can run `/z-plan --slug=<root>/shared/` manually if needed. *(tentative — keeps reconciliation passive)*
- **B.** File-overlap → auto-generate `shared/SPEC.md + shared/TASKS.md` scaffold (empty acceptance criteria); user fills via /z-plan later or marks acceptable as-is.
- **C.** File-overlap + cross-LLM semantic pass on all leaf SPECs.

**Lean:** **A**. **Why consult?** Risk: if shared concerns are real and substantial, a passive note may not be enough. User has to know to act on it, or shared concerns get forgotten. **Ask Gemini:** Should we push reconciliation toward active rewrites (B/C), or is passive observation (A) + user agency sufficient? What signals should prompt active reconciliation?

---

## D7. `/z-implement-all` extension — how does it walk the nested tree?

- **A.** Existing slug-discovery extended: when /z-implement-all sees `z-harness/<slug>/MANIFEST.md`, recurse one level and walk clusters in MANIFEST run-order. *(tentative)*
- **B.** New `/z-implement-tree` command; /z-implement-all unchanged.
- **C.** Don't extend; user runs /z-implement-all per-cluster manually.

**Lean:** **A**. **Why consult?** Risk: /z-implement-all is already complex (skip markers, parallel batching, MAX_ATTEMPTS caps, halt taxonomy). One more discovery rule adds cognitive load + potential new failure modes. **/z-implement-all's hard rules** (skip markers match static text in task block; can't catch novel runtime failures; MAX_ATTEMPTS=2 per task ID; MAX_TASK_WALL_MS=45min; MAX_BATCH_STALL_MS=30min; halt taxonomy with no-retry-cost branches). **Ask Gemini:** Does adding MANIFEST discovery + cluster run-order walking fit cleanly into /z-implement-all's existing architecture, or should the complexity live in a separate /z-implement-tree command?

---

## INTERACTION FLAGS TO RAISE

- **D2 ↔ D3:** If D2 = B (light decision gate per leaf, no consult), does D3 have to be ≥B (active reconciliation)? A passive note won't catch if one leaf made a wrong call on a borderline decision and it affects shared concerns.
- **D2 ↔ D7:** If D2 = C (per-leaf consult per decision), how does that scale with /z-implement-all's MAX_ATTEMPTS caps? A leaf that burns consult cycles early could hit retry limits later.
- **D3 ↔ D7:** If D3 = A (passive), and a cluster plan surfaces a critical shared concern too late, does /z-implement-all's per-cluster run-order flag it in time? Or does the user need D3 ≥ B to catch these before implementation starts?

---

## CONSTRAINTS & GUARDRAILS

- **Narrow scopes:** each cluster expected to have 0–1 non-obvious decisions (vs /z-plan's 5-decision hard cap)
- **Cost discipline:** /z-plan-split targets cheap v1 ("pre-emptive scope split only"); v2 can add smarts (cross-cluster constraint detection, etc.)
- **Matching existing patterns:** /z-brainstorm parallelism (3 ideators), /z-implement-all's halt taxonomy, /z-plan's Gemini + Codex consult pattern
- **User agency:** D3 = A preserves user choice to manage shared concerns manually; D3 ≥ B partially automates
- **Simplicity pressure:** every new discovery rule / decision gate / reconciliation pass adds main-thread complexity; Haiku vs Sonnet tradeoff not on the table here

---

## REQUEST TO GEMINI

For each of the three consult-flagged decisions (D2, D3, D7):

1. **Recommend an option** (A, B, C, or D) with clear reasoning
2. **Articulate the tradeoff(s)** — what you're paying for, what you're saving
3. **Flag anything missed** — edge cases, hidden assumptions, fragile points
4. **Interactions:** at the end, note any cross-decision dependencies or conflicts that could bite us

Keep each recommendation to 2–4 sentences of reasoning. This is input to the main thread's Phase 5 (present + approve) — the user will see your picks alongside existing tentative leans.