# Decisions — rethink-z-research v1

## D1: Two-step handoff vs inline dispatch for /z-map and /z-brainstorm sub-commands
- **Decision:** How does the new /z-research invoke /z-map and /z-brainstorm?
- **Options:**
  - (a) **Two-step handoff** (/z-uplift precedent): orchestrator prints `/z-map ...` command + state-marker, exits. User re-invokes /z-research; resume detects state and continues with /z-brainstorm. Repeat for synthesis. Multi-invocation user journey.
  - (b) **Inline dispatch via Agent()**: orchestrator dispatches the underlying skill code directly inside its own Phase, never exits until done. Single-invocation user journey.
  - (c) **Hybrid:** inline for /z-brainstorm (cheap, ≤200K); two-step handoff for /z-map (heavy, ≤2M) and the synthesis panel.
- **Tentative call:** (b) inline dispatch via Agent(). The user said "more / extra brainstorming capabilities" — one command, one user click. Two-step handoff adds ceremony the user explicitly hasn't asked for. The cost gate at invocation already addresses the "too expensive to run accidentally" concern.
- **Consult? yes**
- **Trigger:** affects user-visible command pipeline; cross-module impact (changes /z-research's nature vs /z-uplift's precedent); hard to reverse if we get it wrong.

## D2: Dispatch decision mechanism (the "highly suggested" decision)
- **Decision:** How does Phase 0.5 of /z-research decide whether to dispatch /z-map and/or /z-brainstorm?
- **Options:**
  - (a) **Deterministic heuristic**: if MAP.md absent → suggest /z-map; if BRAINSTORM.md absent → suggest /z-brainstorm; if both present + fresh + topic-aligned → suggest skip both. Pure shell logic, no LLM call.
  - (b) **Haiku dispatcher agent**: a new sibling to planning-router. Reads slug state + topic + freshness, returns parseable `RUN_MAP: yes|no`, `RUN_BRAINSTORM: yes|no`, with reasons. Single Haiku call, ~10K tokens.
  - (c) **User-driven**: AskUserQuestion with options derived from state ("MAP.md exists from 3 days ago and looks aligned — skip /z-map?"). Defaults to "run both" if no clear skip signal.
- **Tentative call:** (c) user-driven with state-aware defaults. The user said "orchestrator decides... but highly suggested" — that's exactly AskUser-with-strong-default. Heuristic (a) is too rigid; Haiku dispatcher (b) is over-engineering for a yes/no/skip decision the user wants visibility into.
- **Consult? yes**
- **Trigger:** core mechanism of the new command; user-visible; affects how often each sub-command runs.

## D3: Adversarial synthesis panel — exact composition
- **Decision:** What are the three synthesizer "perspectives"?
- **Options:**
  - (a) Per BRAINSTORM: architecture-conservative + product/workflow-expansive + failure-mode-adversarial + final judge.
  - (b) Same three + skip the final-judge step (judge replaced by deterministic concatenation under structured headings).
  - (c) Reduce to two perspectives + judge.
- **Tentative call:** (a) BRAINSTORM literal. Three perspectives is the right diversity floor — fewer collapses to single-Opus equivalent, more wastes tokens.
- **Consult? yes**
- **Trigger:** new external dependency (3 vendor-diverse LLM calls + judge); algorithm-with-tradeoffs; affects ≥1 module.

## D4: Synthesizer LLM assignment per perspective
- **Decision:** Which LLM runs which perspective?
- **Options:**
  - (a) Round-robin: Claude=conservative, Codex=expansive, Gemini=adversarial (then judge=Opus).
  - (b) All three perspectives use Opus from one vendor (e.g. Claude Opus × 3 with different prompts).
  - (c) Vendor-diverse but rotated per run (avoid Claude-bias by varying which vendor is "conservative").
- **Tentative call:** (a) static round-robin. Three vendors × three perspectives = diversity baked in. Rotation (c) adds run-to-run variance with marginal benefit. Single-vendor (b) loses the anti-bias property we just shipped in /z-brainstorm.
- **Consult? yes**
- **Trigger:** new external dependency (per-vendor LLM); affects diversity properties; reversibility = trivial but the contract goes into RESEARCH.md frontmatter.

## D5: RESEARCH.md schema — exact section order + frontmatter
- **Decision:** What is the canonical schema?
- **Options:**
  - (a) BRAINSTORM literal 10 sections in order listed.
  - (b) Same sections, different order (e.g. lead with approach matrix as the headline finding).
  - (c) Compress to fewer sections (e.g. merge "rejected/weak framings" into approach matrix as a column).
- **Tentative call:** (b) reordered: lead with `## Approach decision matrix` (the headline value-add), follow with `## Cross-artifact contradictions` (the second value-add), then the supporting context sections (terrain summary, brainstorm frame space, design axes, etc.), end with `## Recommended next-command inputs for /z-plan` (the actionable handoff). Frontmatter: `artifact: research`, `slug`, `generated_at`, `command`, `dispatch_decision: {map: <ran|reused|skipped>, brainstorm: <ran|reused|skipped>}`, `source_artifacts: [MAP.md@<sha>, BRAINSTORM.md@<sha>]`, `synthesizer_models: {conservative: claude-opus, expansive: codex, adversarial: gemini, judge: opus}`, `status: complete|abandoned`, `tripwires_fired: []`.
- **Consult? yes**
- **Trigger:** defines public API (downstream /z-plan parser); hard to rename later; affects ≥1 reader.

## D6: Approach decision matrix — rows × columns specification
- **Decision:** How is the matrix structured exactly?
- **Options:**
  - (a) Rows = approaches from BRAINSTORM (one per ideator's "Plan implications" + any from "Core hypothesis"); columns = constraint classes from MAP (e.g. "API surface", "concurrency", "persistence", "performance"). Cells = compatibility flag + 1-line citation.
  - (b) Same rows; columns = SEVERITY of impact on each approach (low/medium/high). Cells = rationale + citation.
  - (c) Markdown table with structured cells: `<verdict>: <citation>` (e.g. `BLOCKS: MAP.md §3.2 line 47`, `OK: <citation>`, `UNVERIFIED: <gap>`).
- **Tentative call:** (c) verdict + citation per cell. Verdict enum: `OK`, `BLOCKS`, `RISKY`, `UNVERIFIED`. Each cell MUST include a citation OR be marked UNVERIFIED. Aligned with Codex schema's emphasis on planner leverage.
- **Consult? yes**
- **Trigger:** defines artifact structure /z-plan will parse; hard to retrofit; "approach matrix" is the headline feature.

## D7: Cost gate — exact AskUserQuestion shape + budget tiers
- **Decision:** How does the cost gate behave?
- **Options:**
  - (a) Model current /z-research literally — 3 options: proceed / reduce / abandon.
  - (b) 4 options including a `--standard` mid-tier: proceed-full (5–6M) / standard (3–4M, e.g. skip /z-map if MAP.md fresh) / minimal (~1.5M, reuse both artifacts + synthesis only) / abandon.
  - (c) Show estimated cost based on dispatch decision from D2 (i.e. "you chose to run /z-map + /z-brainstorm + synthesis → ~5M tokens, proceed?").
- **Tentative call:** (c) compute estimate from D2's dispatch decision. The dispatch decision already encodes whether /z-map and /z-brainstorm will run; cost gate just confirms the resulting estimate. Three options: proceed / change dispatch (loops back to D2) / abandon.
- **Consult? no**
- **Trigger:** none — follows existing /z-research convention with one improvement (cost reflects actual planned work).

## D8: /z-plan one-way gate — exact integration point
- **Decision:** How does /z-plan detect and prefer RESEARCH.md over component files?
- **Options:**
  - (a) Setup step 9 amendment: if RESEARCH.md exists + fresh + valid frontmatter (`artifact: research`, `status: complete`), inject ONLY RESEARCH.md into premise check; ignore MAP.md + BRAINSTORM.md component files for that run.
  - (b) Same detection, but always inject all three artifacts; /z-plan downstream logic decides which to use per phase.
  - (c) New Setup step 9.5 between BRAINSTORM-check and RESEARCH-check that explicitly handles the new RESEARCH.md schema (vs old "RESEARCH.md = map" schema).
- **Tentative call:** (a) — one-way gate. The whole point is to provide a richer single-input. Old behavior (read MAP.md + BRAINSTORM.md separately) becomes a fallback ONLY when RESEARCH.md is missing. This means /z-plan's Setup step 9 needs to distinguish OLD RESEARCH.md (which is now MAP.md) from NEW RESEARCH.md (the meta-orchestrator output) — done via `artifact:` frontmatter field.
- **Consult? yes**
- **Trigger:** changes /z-plan's public intake contract; affects how all future plans read precontext; hard to reverse.

## D9: Rename strategy — atomic vs phased
- **Decision:** How does the rename land?
- **Options:**
  - (a) Atomic: all rename touches (commands/z-research.md → commands/z-map.md, skill rename, planning-router enum, /z-plan precontext rules, docs, exports) land in one task.
  - (b) Phased: rename command file first; update routers/docs in a follow-up task; old name kept as alias for one release.
- **Tentative call:** (a) atomic. Aliases add complexity for users (which name is canonical?). Rename is bounded (~12 files); single task with all edits.
- **Consult? no**
- **Trigger:** following existing convention (no aliases elsewhere in z-harness).

## D10: planning-router routing rule for new /z-research
- **Decision:** When should planning-router recommend the new /z-research?
- **Options:**
  - (a) Replace the existing recommendation of /z-research (now /z-map) with new /z-research when the topic has BOTH terrain uncertainty AND approach uncertainty.
  - (b) Keep /z-map (old /z-research) recommendation; add new /z-research only when explicitly requested by the user.
  - (c) Recommend /z-map when terrain unclear; recommend /z-research when approach-space unclear (orthogonal axes).
- **Tentative call:** (c). The two commands serve different epistemic needs. Reason codes: `needs_terrain_map` → /z-map; `needs_approach_synthesis` → /z-research.
- **Consult? yes**
- **Trigger:** affects planning-router public contract; public surface (route recommendations to users); hard to reverse.

## D11: Adversarial-panel parallel dispatch + failure semantics
- **Decision:** How does the synthesis layer handle subagent failure?
- **Options:**
  - (a) Match /z-brainstorm pattern: 1/3 fail → proceed with 2 + judge; 2/3 fail → ask user; 3/3 fail → halt.
  - (b) Stricter: any synthesizer failure → halt + ask user (research is expensive enough that partial-result risk isn't worth it).
  - (c) Retry-once each, then fall back to single-Opus for failed perspectives (3 attempts max per perspective).
- **Tentative call:** (a) match /z-brainstorm. Consistency across z-harness; users already know this pattern.
- **Consult? no**
- **Trigger:** none — follows established pattern from /z-brainstorm.

## D12: Synthesis judge — separate agent or part of orchestrator?
- **Decision:** Where does the final-judge synthesis live?
- **Options:**
  - (a) Separate `research-judge` agent (Opus, new file `agents/research-judge.md`).
  - (b) Inline Opus call from orchestrator main thread (no separate agent file).
  - (c) Reuse `general-purpose` subagent with `model: opus` and a tight prompt.
- **Tentative call:** (a) separate agent. Cleanest separation of responsibility; agent file documents the judge's contract (read the 3 panel outputs, write final RESEARCH.md content, never propose new design). Matches pattern of scope-reconciler-audit and scope-reconciler-brainstorm.
- **Consult? no**
- **Trigger:** none — convention match.

## D13: Telemetry event names for new /z-research
- **Decision:** What events does the new command emit?
- **Tentative call:** `research_run_start`, `research_dispatch_decision {map: <action>, brainstorm: <action>}`, `research_cost_gate_decision`, `research_subcommand_complete {sub: map|brainstorm, status}`, `research_panel_start`, `research_panel_lane_complete {perspective}`, `research_judge_complete`, `research_run_end {status, tripwires_fired}`.
- **Consult? no**
- **Trigger:** none — naming follows conventions.

---

## Consult-flagged decisions (5/13 — at the cap)
1. **D1** — two-step handoff vs inline dispatch
2. **D2** — dispatch decision mechanism (heuristic / Haiku agent / AskUser)
3. **D5** — RESEARCH.md schema (section order + frontmatter)
4. **D8** — /z-plan one-way gate integration point
5. **D10** — planning-router routing rule (which command for which uncertainty)

D3 (panel composition), D4 (LLM assignment), D6 (matrix structure) all touch tradeoffs but I'm holding to my tentative calls and not consulting given the 5-cap. They can be raised in Phase 5 if consultants surface tension.
