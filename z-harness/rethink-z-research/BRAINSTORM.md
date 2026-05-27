---
artifact: brainstorm
slug: rethink-z-research
generated_at: 2026-05-27T21:52:22Z
command: /z-brainstorm rethink-z-research (round 2 — refined topic)
input_hash: 9a4b2c8e7f3d1e5a
depends_on: [BRAINSTORM.md.previous-1]
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

### Framing
`/z-research` should be a **conditional pipeline orchestrator** that reads existing artifacts before dispatching anything. The core insight: the command is expensive precisely because it goes deeper — so it must earn that depth by building on what already exists rather than regenerating. The dispatch graph: check for MAP.md → check for BRAINSTORM.md → dispatch only missing stages → run a structured cross-artifact synthesis that produces something neither artifact alone contains: an **approach decision matrix** with explicit trade-off rows.

### Core hypothesis
The meta-synthesis layer's unique value is **forcing consistency between the empirical map and the ideation space**. MAP.md says "here is what exists and why it's hard." BRAINSTORM.md says "here are framings." Neither answers: "which framings are actually viable given the constraints the map surfaced?" A single Opus synthesis agent reads both and produces a ranked approach matrix — rows = approaches from BRAINSTORM, columns = constraint classes from MAP — filling a gap no amount of parallel voting would. Output is `RESEARCH.md`. It's **narrowing**, not expanding.

### Risks
- **Opus hallucination in the matrix.** Stale or partial MAP.md = false constraint cells. Mitigation: require synthesis to cite MAP.md section+line per cell; unfilled citations = `UNVERIFIED`, triggering targeted re-map on that subtopic.
- **Cost runaway.** Dynamic dispatch means unpredictable cost. Mandatory cost-gate at invocation ("this will cost ~4M tokens, continue?").
- **Artifact proliferation.** MAP.md + BRAINSTORM.md + RESEARCH.md = 3 files. `/z-plan` MUST consume RESEARCH.md as canonical input, deprecating individual intakes — otherwise the pipeline branches non-deterministically.
- **Always-fresh vs incremental tension.** Stale MAP + fresh BRAINSTORM → solved only if freshness is checksummed (git SHA stored in frontmatter).

### Plan implications
- `/z-plan` intake contract changes: reads RESEARCH.md if present; falls back to MAP.md + BRAINSTORM.md individually if not. **One-way gate** — once RESEARCH.md exists, /z-plan ignores component files.
- `/z-map` (renamed) gets machine-readable frontmatter (run SHA, timestamp, codebase hash) for staleness detection.
- No spike/probe phase inside `/z-research`. Spikes are implementation-tier; /z-research stays planning-tier. Spikes belong in `/z-plan`.
- RESEARCH.md must inherit `## No-recommendation invariant` from MAP.md discipline — matrix ranks by constraint-fit, does not pick winner. `/z-plan` picks.

### What would change my mind
If the approach matrix turns out empirically to be noise (`/z-plan` ignores constraint columns, just reads approach names), the synthesis layer is over-engineered. Collapse RESEARCH.md back to an enriched BRAINSTORM.md with `## Constraint audit` appended. But need 2–3 /z-plan runs demonstrably using the matrix before concluding it's valuable.

---

## Framing: codex

### Framing
`/z-research` should be a **research compiler**, not a bigger brainstorm. Key distinction: `/z-map` discovers terrain, `/z-brainstorm` generates candidate framings, `/z-research` transforms both into a higher-order option space with explicit tensions, missing evidence, decision axes, and next-plan leverage. It should NOT feel like "run map, run brainstorm, concatenate" — it should feel like a command that creates the artifact you wish you had before writing SPEC/PLAN.

### Core hypothesis
**Dynamic-but-biased-toward-freshness** default dispatch:
- Always run `/z-map` unless fresh MAP.md exists for same topic + code state.
- Run `/z-brainstorm` when topic has meaningful design uncertainty.
- Reuse BRAINSTORM.md only if explicitly tied to refined topic AND not invalidated by newer map evidence.
- Always run a new meta-synthesis layer.

Meta-synthesis adds three things: **conflict extraction** (map evidence vs ideator assumptions), **design-axis construction** (few dimensions organizing the solution space), **plan-shaping output** (what /z-plan should decide, defer, test, or forbid). Use **parallel meta-synthesizers**: one "architecture conservative", one "product/workflow expansive", one "failure-mode adversarial", then final judge produces the artifact.

### Risks
- **Recursive ceremony.** `/z-research` becomes expensive theater producing more words but not more planning leverage.
- **Stale artifact reuse.** Old BRAINSTORM.md silently anchors research around rejected framings.
- **Output naming confusion.** If old `/z-research` → `/z-map`, new `/z-research` needs clearly different schema — not "old RESEARCH.md 2.0."
- **Boundary blur.** Deeper probes blur into `/z-plan-light` or `/z-debug` territory unless strictly triggered.

### Plan implications
- Rename `/z-research` → `/z-map`, artifact `MAP.md`. New `/z-research` writes RESEARCH.md with NEW schema (10 sections):
  - source artifacts consumed
  - freshness decisions
  - terrain summary
  - brainstorm frame space
  - cross-artifact contradictions
  - decision axes
  - high-leverage options
  - rejected/weak framings
  - evidence gaps
  - recommended next-command inputs for /z-plan
- **Do NOT name output `MEGA-BRAINSTORM.md`** — that undersells the role.
- Approach probes optional, narrowly scoped, default-off. Add a "probe eligibility" phase but only dispatch when map+brainstorm identify a specific empirical question answerable cheaply.

### What would change my mind
- Move to "always map → always brainstorm → synthesize" if reproducibility matters more than cost, or if users get confused by dynamic reuse.
- Accept `MEGA-BRAINSTORM.md` naming if command is mainly for ideation-heavy greenfield work.
- Prefer single Opus meta-synthesizer if parallel synthesizers produce duplicated abstraction.
- Include deeper probes by default only if early use shows /z-research frequently hands /z-plan unresolved questions that a 10-min spike could settle.

---

## Framing: gemini

### Framing
`/z-research` becomes a **meta-orchestrator command**, not a sibling. It sequences and composes existing weapons: dispatch `/z-map` (renamed) for constraints → dispatch `/z-brainstorm` for framings within those constraints → run a single unified meta-synthesis pass (Opus or high-context Sonnet) that reads both MAP.md + BRAINSTORM.md as co-inputs and produces RESEARCH.md — a deeper artifact that doesn't exist in isolation but only as the synthesis of the two. Output is one RESEARCH.md, not five separate framing blocks. Answers: "given terrain constraints AND ideated framings, what does the design space actually look like?" Cost ≤6M tokens (2M + 200K + 3.8M).

### Core hypothesis
Real value between "what does the codebase look like?" (map) and "how could we think about this?" (brainstorm) is **the intersection**: which framings are actually feasible within terrain constraints, and which constraints force reframing? A meta-synthesizer reading both can flag framings that collide with architecture, reveal constraints that collapse entire approaches, recommend which framing-plus-terrain pairing is most robust. Fundamentally different from a /z-spike bake-off (which requires PoC code); pure analytical synthesis. By composing tools rather than introducing new agents, `/z-research` stays cheap-ish, avoids naming churn, leverages mature/tested /z-map and /z-brainstorm. Orchestrator-only code — no new LLM modes, no new consultant roles, just sequencing + synthesis dispatch.

### Risks
- **Sequence brittleness.** /z-map first returns confusing constraints → /z-brainstorm wastes budget inside an ill-defined box.
- **Dynamic dispatch complexity.** "Always map → brainstorm → synthesize vs skip brainstorm if fresh BRAINSTORM.md exists" is a hidden fork that confuses users and fragments mental model.
- **Synthesis inflation.** Third Opus pass adds cost + new failure mode (mis-reads prior artifacts, conflates constraints with design, over-prescribes).
- **User expectation mismatch.** Calling it "research" but not offering /z-spike-style proof-of-concept may disappoint users who want code validation; they bypass to /z-plan anyway.

### Plan implications
- Rename `/z-research` → `/z-map` in all config/routes/docs (one-time propagation tax ~5 files).
- New `/z-research` as pure orchestrator: Phase 1 invokes /z-map, Phase 2 invokes /z-brainstorm (unless `--skip-brainstorm` flag + existing BRAINSTORM.md), Phase 3 dispatches single Opus synthesizer.
- Synthesis constraints: **read MAP.md + BRAINSTORM.md; flag design-terrain collisions; recommend which framing is most resilient; do NOT propose new architectures.**
- Output: RESEARCH.md with `Viable framings / Terrain-constrained risks / Synthesis recommendation / Open questions for /z-plan`.
- Synthesis agent FORBIDS new design recommendations; ALLOWS only collision-flagging and framing rank-ordering.

### What would change my mind
- Users reach for /z-research expecting code sketches and prototypes (/z-spike mental model), get frustrated by "pure synthesis" output.
- MAP.md + BRAINSTORM.md synthesis turns out trivial (10s of human reading) → orchestration adds no value; collapse to a `--show-terrain-constraints` flag on /z-brainstorm.
- Three-phase wall-clock dominated by meta-synthesis pass and users report "synthesis took too long for too little insight" → downgrade model or drop entirely.
- /z-map rename causes upstream breakage in user scripts/docs that audit can't find → revert to in-place redesign.

---

## Anti-bias check

**Framing — *Codex wins.*** "Research compiler" is the sharpest, most evocative reframe. It cleanly signals "this command TRANSFORMS prior artifacts into a new tier" — not "bigger brainstorm" (Gemini's framing slips toward this) and not just "conditional dispatcher" (Claude's mechanical description). Codex's articulation "it should feel like a command that creates the artifact you wish you had before writing SPEC/PLAN" is the design-intent sentence the whole proposal hinges on.

**Core hypothesis — *Split: Codex spine + Claude matrix concept + Gemini invariant.*** All three agree the synthesis layer adds something neither input has. Codex provides the most actionable enumeration of what it adds (conflict extraction + design-axis construction + plan-shaping output). Claude provides the cleanest single-artifact concept (the approach matrix: rows × columns from BRAINSTORM × MAP). Gemini provides the cleanest hard invariant (FORBIDS new design; ALLOWS only collision-flagging + framing rank-ordering — preserves the No-recommendation lineage from current /z-research). All three are complementary; merge. *Claude-favoring justification for keeping the matrix: Codex's 10-section schema is comprehensive but flat (a checklist of sections); Claude's matrix gives the artifact a memorable structural shape (rows × columns) that's easier for users to parse at a glance and forces consistency between framings and constraints. Both fit.*

**Risks — *Codex wins.*** "Recursive ceremony" (expensive theater producing more words but not more planning leverage) is the sharpest risk articulation of all three. "Stale artifact reuse silently anchors research around rejected framings" is concrete and operationally specific. "Output naming confusion — if /z-research's new schema is just RESEARCH.md 2.0, users won't perceive the upgrade" is real and only Codex flagged it. Claude's "Opus hallucination in the matrix" + "artifact proliferation" + "freshness checksumming" are also strong and complementary. Gemini's "user expectation mismatch — they expected /z-spike, got synthesis" is real but already addressed by Codex framing the new command as a compiler not a prototype-generator.

**Plan implications — *Codex schema + Claude integration rule + Gemini invariant.*** Codex provides the most detailed schema (10 sections enumerated). Claude provides the cleanest /z-plan integration rule (one-way gate: if RESEARCH.md exists, /z-plan reads it; otherwise falls back to component files — non-deterministic branching solved). Gemini provides the hard synthesis invariant (FORBIDS new design recommendations; ALLOWS only collision-flagging and rank-ordering). Each fills a hole the others left.

**What would change my mind — *Codex wins on adversarial-synthesizer fallback; Claude wins on concrete metric; Gemini wins on whole-design falsifier.*** Codex's "if parallel synthesizers produce duplicated abstraction, drop to single Opus" is the cleanest design-tradeoff escape hatch. Claude's "if /z-plan ignores constraint columns, collapse back" is concrete and measurable from /z-plan logs. Gemini's "if MAP+BRAINSTORM synthesis is trivial in 10s of human reading, collapse to a flag" is the cleanest "is this command worth existing at all" falsifier.

**Net:** Codex wins framing + risks + schema (3/5). Claude wins matrix concept + /z-plan integration rule (1/5). Gemini wins synthesis hard invariant + whole-design falsifier (1/5). Healthy split with high complementarity.

## Orchestrator recommendation

**Codex framing as the spine: `/z-research` is a research compiler, not a bigger brainstorm.** It transforms /z-map + /z-brainstorm artifacts into a higher-order option space.

Concrete shape (merging the three):

**Naming + artifacts:**
- Current `/z-research` → renamed to `/z-map`, artifact `MAP.md`. Preserves existing No-recommendation invariant.
- New `/z-research` → orchestrator command. Artifact `RESEARCH.md` (new schema, NOT "MAP.md 2.0" — explicitly different sections so users perceive the upgrade).

**Dispatch policy (Codex's dynamic-biased-toward-freshness):**
- Always dispatch `/z-map` unless a fresh `MAP.md` exists for the same topic + code state (freshness = git SHA stored in MAP.md frontmatter per Claude graft).
- Dispatch `/z-brainstorm` when topic has meaningful design uncertainty; reuse existing BRAINSTORM.md only if explicitly tied to refined topic AND not invalidated by newer map evidence.
- Always run new meta-synthesis layer.

**Meta-synthesis (start adversarial-panel, fall back to single Opus per Codex falsifier):**
- v1 design: parallel meta-synthesizers (architecture-conservative + product/workflow-expansive + failure-mode-adversarial) + final judge.
- If v1 telemetry shows panel output is redundant or coherence-lacking, collapse to single Opus pass over both artifacts.

**RESEARCH.md schema (Codex 10 sections + Claude matrix):**
- Source artifacts consumed (with freshness decision per artifact)
- Terrain summary (extractive from MAP.md)
- Brainstorm frame space (extractive from BRAINSTORM.md)
- **Approach decision matrix** (Claude graft: rows = approaches, columns = constraint classes, cells cite source with file:section)
- Cross-artifact contradictions (where map evidence contradicts ideator assumptions)
- Design axes (the few dimensions organizing the solution space)
- High-leverage options
- Rejected/weak framings (with WHY)
- Evidence gaps
- Recommended next-command inputs for /z-plan

**Hard invariants (Gemini graft):**
- Synthesis layer FORBIDS new design recommendations.
- ALLOWS only collision-flagging and rank-ordering.
- Cite MAP.md and BRAINSTORM.md per claim — unfilled citations = `UNVERIFIED` cell, may trigger targeted re-map on that subtopic (Claude graft).

**`/z-plan` integration (Claude's one-way gate):**
- If RESEARCH.md exists in `$Z_HARNESS_PLAN_DIR/`, /z-plan reads it as canonical precontext. Component files (MAP.md, BRAINSTORM.md) are ignored.
- If only MAP.md + BRAINSTORM.md exist, /z-plan reads both per existing rules.
- This is a one-way gate: once RESEARCH.md exists for a slug, it's the authority.

**Cost gate:**
- Estimated 3–6M tokens. Mandatory user-facing cost estimate at invocation ("this run will cost ~5M tokens; continue?") via AskUserQuestion.
- Cost decomposes: /z-map ≤2M + /z-brainstorm ≤200K + meta-synthesis 1–4M depending on adversarial-panel vs single-Opus.

**Out of scope (rejected unanimously):**
- No spike/probe phase by default. Spikes are implementation-tier; /z-research stays planning-tier. If `/z-plan` later wants spike-style validation, it dispatches spike work itself — that's a different command (which we explicitly rejected in round 1 — there is no `/z-spike` in this design).

**Out of scope (deferred per Codex):**
- Approach probes as optional default-off `--probe` flag — only dispatch when synthesis identifies a specific empirical question cheaply answerable. v2 feature, not v1.

**The 3-stage pipeline post-rename:**
```
/z-brainstorm → BRAINSTORM.md  (cheap framings, ≤200K)
/z-map        → MAP.md         (terrain + constraints, ≤2M, no-recommendation)
/z-research   → RESEARCH.md    (research compiler: synthesizes both, 3-6M, no new design but rank-orders)
/z-plan       → SPEC/PLAN/TASKS (reads RESEARCH.md as canonical if present)
```

Naming migration is bounded: ~5 files (skill spec, command spec, /z-plan precontext rules, docs/human/commands.md, docs/llm/commands.json). Codex's earlier concern that this could break external automation is mitigated by /z-plan's fallback to component files — old behavior continues to work; new RESEARCH.md is purely additive.


## User choice

**Chosen: Codex (research compiler) — with grafts.**

`/z-research` becomes a higher-order meta-orchestrator that COMPOSES `/z-map` (current /z-research, renamed) and/or `/z-brainstorm` as sub-steps, then runs an adversarial meta-synthesis panel to produce a richer RESEARCH.md artifact that does NOT exist in isolation but only as the synthesis of its inputs.

**Locked-in design (merge of all three framings):**

1. **Rename:** current `/z-research` → `/z-map`, artifact `MAP.md`. Preserves the No-recommendation invariant inside /z-map. ~5 files to update; bounded migration.
2. **New `/z-research`** = orchestrator-only code. No new LLM modes, no new consultant roles. Composes existing tools.
3. **Dispatch policy:** dynamic-biased-toward-freshness. Always dispatch `/z-map` unless a fresh MAP.md exists for the same topic + code state (freshness check = git SHA in MAP.md frontmatter). Dispatch `/z-brainstorm` when topic has meaningful design uncertainty; reuse existing BRAINSTORM.md only if explicitly tied to refined topic AND not invalidated by newer map evidence. Always run new meta-synthesis layer.
4. **Meta-synthesis = adversarial panel** by default: three parallel synthesizers (architecture-conservative + product/workflow-expansive + failure-mode-adversarial) + final judge produces RESEARCH.md. Fallback to single Opus if v1 telemetry shows panel output is redundant.
5. **RESEARCH.md schema (10 sections):**
   - Source artifacts consumed (with freshness decision per artifact)
   - Terrain summary (extractive from MAP.md)
   - Brainstorm frame space (extractive from BRAINSTORM.md)
   - **Approach decision matrix** — rows = approaches from BRAINSTORM, columns = constraint classes from MAP, cells cite source with file:section. Unfilled citations = `UNVERIFIED` (may trigger targeted re-map).
   - Cross-artifact contradictions (where map evidence contradicts ideator assumptions)
   - Design axes (the few dimensions organizing the solution space)
   - High-leverage options
   - Rejected/weak framings (with WHY)
   - Evidence gaps
   - Recommended next-command inputs for /z-plan
6. **Hard invariants:**
   - Synthesis layer FORBIDS new design recommendations.
   - ALLOWS only collision-flagging and framing rank-ordering.
   - Every claim in the matrix must cite MAP.md or BRAINSTORM.md; uncited cells get `UNVERIFIED`.
7. **/z-plan integration (one-way gate):** if RESEARCH.md exists in `$Z_HARNESS_PLAN_DIR/`, /z-plan reads it as canonical precontext; component files (MAP.md, BRAINSTORM.md) are ignored. If only MAP.md + BRAINSTORM.md exist, /z-plan reads both per existing rules. Old behavior continues to work; new RESEARCH.md is purely additive.
8. **Cost gate:** mandatory user-facing AskUserQuestion at invocation showing estimated tokens (3–6M typical, decomposed as /z-map ≤2M + /z-brainstorm ≤200K + meta-synthesis 1–4M).

**Out of scope (v1):**
- No spike/probe phase. Spikes are implementation-tier; /z-research stays planning-tier.
- No /z-spike sibling command (the round-1 framing the user rejected).
- Approach probes deferred to v2 as opt-in `--probe` flag.

**Falsifiability tripwires (must NOT fire post-launch):**
1. If `/z-plan` ignores RESEARCH.md's constraint columns and just reads approach names → synthesis layer is over-engineered; collapse to enriched BRAINSTORM.md with appended constraint audit.
2. If users repeatedly reach for /z-research expecting code sketches/prototypes → naming or framing is wrong.
3. If adversarial-panel output is consistently duplicated abstraction → drop to single Opus synthesizer.
4. If MAP.md + BRAINSTORM.md synthesis is trivial in human 10s of reading → the command isn't earning its existence; collapse to a flag on /z-brainstorm.

**Recommended next:** `/z-plan rethink-z-research` to produce SPEC/PLAN/TASKS. Suggested first targets:
- Rename migration (all references to current /z-research → /z-map)
- New /z-research command spec (commands/z-research.md, skills/z-research/SKILL.md)
- RESEARCH.md schema definition
- /z-plan precontext rule update (one-way gate on RESEARCH.md)
- Adversarial-synthesizer agent definitions OR single-Opus fallback
