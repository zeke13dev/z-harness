# PLAN — rethink-z-research v1

## Goal

Rename `/z-research` → `/z-map` (atomic, no aliases). Build new `/z-research` as a meta-orchestrator that intelligently dispatches `/z-map` and/or `/z-brainstorm`, then runs an adversarial synthesis panel (3 vendor-diverse perspectives + Opus judge) producing RESEARCH.md with a lead-with-matrix 10-section schema. `/z-plan` gets a one-way gate on RESEARCH.md when `artifact_kind: approach_synthesis` is present.

## Decisions

| # | Call | Rationale |
|---|---|---|
| D1 | **Inline dispatch + audit grafts** | Gemini won the consult on UX (single command click matches user's stated goal); Codex's audit-trail concern grafted in via explicit `research_dispatch_decision` events + `archive/$RUN/subruns/<sub>/` sub-folder structure. /z-uplift's two-step precedent applies to implementation-tier work, not planning-tier composition. |
| D2 | **User-driven AskUser w/ state-aware defaults** | Both consultants endorsed. User said "orchestrator decides but highly suggested" = AskUser-with-strong-default. Defaults computed deterministically from MAP/BRAINSTORM freshness. |
| D3 | **3 perspectives + judge** (BRAINSTORM literal) | Fewer collapses to single-Opus equivalent; more wastes tokens. Architecture-conservative + product-expansive + failure-mode-adversarial + Opus judge. |
| D4 | **Real vendor diversity via existing proxy agents** (Phase 7 fix) | Phase 7 review caught: a single `research-synthesizer` agent with `model: opus` is NOT vendor-diverse. Replaced with: `general-purpose` (Opus) for architecture-conservative; `consultant-primary` for product-expansive; `consultant-secondary` for failure-mode-adversarial. Real vendor diversity via existing provider-resolution. Provider-unavailable fallback per perspective treats it as 1/3 fail. |
| D5 | **Lead-with-matrix schema + schema_version: 1 + artifact_kind: approach_synthesis** | Codex graft on versioning + kind fields for future-proofing. Matrix is the headline output; comes first. |
| D6 | **Verdict + citation per matrix cell** | Verdict enum: `OK | BLOCKS | RISKY | UNVERIFIED`. Every cell MUST have a citation OR be marked UNVERIFIED. Enforces the No-new-design + cite-or-mark-uncertain invariant. |
| D7 | **Cost gate computed from dispatch decision** | Estimated tokens = f(dispatch_decision). Three options: proceed / change dispatch (loop) / abandon. Models current /z-research Phase 0 pattern. |
| D8 | **One-way gate + explicit legacy fallback** | `/z-plan` Setup step 9 distinguishes by `artifact_kind`. New RESEARCH.md (`approach_synthesis`) = canonical; legacy or missing → component-file injection. Codex graft on fallback. |
| D9 | **Atomic rename** | No alias period. 12 files; one task. Aliases add user confusion. |
| D10 | **Orthogonal axes + `needs_research` deprecated alias for one cycle** | `needs_terrain_map` → /z-map; `needs_approach_synthesis` → /z-research. Old `needs_research` keeps alive as deprecated for migration. |
| D11 | **/z-brainstorm 1/2/3-fail pattern for panel** | Consistency with existing harness pattern. |
| D12 | **Separate `research-judge` agent** + **`research-synthesizer` parameterized by perspective** | Matches scope-reconciler-audit/scope-reconciler-brainstorm convention. Clean responsibility separation. |
| D13 | **Event taxonomy:** `research_run_start`, `research_dispatch_decision`, `research_cost_gate_decision`, `research_subcommand_complete`, `research_panel_lane_complete`, `research_judge_complete`, `research_judge_temptation`, `research_run_end`, `research_high_unverified_rate` (tripwire) | Convention match. |

## Non-goals

- No spike/probe phase (rejected unanimously in BRAINSTORM).
- No two-step handoff for sub-command dispatch.
- No automatic chaining to `/z-plan` after /z-research completes.
- No backward-compat alias for `/z-research` command name pointing to old behavior.
- No retry-once + fallback for synthesizer perspectives (use /z-brainstorm 1/2/3-fail pattern instead).

## Approved shortcuts

None. All decisions land on the robust path. The only "degradation" is the explicit legacy-file fallback in D8, which is required for the rename to be non-breaking — not a shortcut.

## Ordered phases

### Phase A — Agents + RESEARCH.md schema
1. Write `agents/research-synthesizer.md` (parameterized by `perspective`).
2. Write `agents/research-judge.md`.
3. Document RESEARCH.md schema (lead with matrix; 10 sections; frontmatter with `schema_version: 1` + `artifact_kind: approach_synthesis`).
4. Update INDEX.json `agents` entry.

### Phase B — Atomic rename
5. Rename `commands/z-research.md` → `commands/z-map.md` (content unchanged except header + artifact name + description).
6. Rename `skills/z-research/SKILL.md` → `skills/z-map/SKILL.md`.
7. Update planning-router reason codes (add `needs_terrain_map` + `needs_approach_synthesis`; deprecate-alias `needs_research`).
8. Update references in `/z-uplift`, `/z-do`, `/z-brainstorm`, `/z-plan-light`, `/z-plan-split` from old name to `/z-map` where applicable.

### Phase C — New /z-research orchestrator
9. Write `commands/z-research.md` (NEW — orchestrator spec with Phase 0 dispatch, 0.5 cost gate, 1 inline subdispatch, 2 panel, 3 judge, 4 finalize).
10. Write `skills/z-research/SKILL.md` (mirror).
11. Implement inline-dispatch + audit grafts: `archive/$RUN/subruns/<sub>/` structure + `research_dispatch_decision` event.

### Phase D — /z-plan one-way gate
12. Edit `commands/z-plan.md` Setup step 9: detect `artifact_kind: approach_synthesis` + status; switch to one-way gate behavior; preserve legacy fallback.

### Phase E — Docs refresh
13. Update `docs/llm/INDEX.json` (agents + commands + skills source_files).
14. Run `/z-maintain-docs --apply` on the touched concepts (agents, commands, skills).
15. Regenerate `docs/llm/MEMORIES-FLAT.md`.
16. Update `README.md` command catalogue.
17. Regenerate `exports/{cursor,codex,agy}/*`.

### Phase F — Calibration (no v1 implementation)
The 4 BRAINSTORM tripwires are evaluated by post-launch usage telemetry, not at planning time:
- T1: /z-plan consumes constraint columns (check by inspecting downstream task acceptance criteria after first 3 /z-research runs)
- T2: users get the value (check by tracking /z-research → /z-plan handoff success rate)
- T3: panel output redundancy (check by manual inspection of first 3 panel outputs)
- T4: synthesis triviality (check by inspecting whether matrix verdicts inform user decisions)

If any tripwire fires post-launch, follow-up `/z-amend` proposes adjustments.

## DRY / KISS / SOLID

- **DRY:** RESEARCH.md schema defined once (SPEC.md + research-judge.md prompt template). Inline-dispatch reuses /z-map and /z-brainstorm skill code unchanged. Cost-gate pattern reused from current /z-research (now /z-map).
- **KISS:** v1 ships exactly the BRAINSTORM-locked design — no v1.5 punts. Single command click, AskUser strong-default, deterministic dispatch math, standard /z-brainstorm-style failure semantics.
- **SOLID:** clean responsibility separation (synthesizer = perspective; judge = merge; orchestrator = dispatch); perspective parameter is open/closed; /z-plan depends on RESEARCH.md schema not on /z-research implementation.

## Amendments

- **Phase 7 review (this run):** Applied 11 findings inline to SPEC + PLAN.
  - **3 blockers fixed:** (a) /z-plan precontext detection now includes MAP.md alongside RESEARCH.md + BRAINSTORM.md; (b) /z-plan Phase 1 skip rules rewritten for new RESEARCH.md schema (use matrix cells + Evidence gaps section, not legacy Findings/Open questions); (c) vendor diversity made real by dispatching panel via existing `general-purpose` + `consultant-primary` + `consultant-secondary` instead of a single Opus-only agent.
  - **8 smaller fixes applied:** sub-run audit contract via child-emits-parent-attribution + symlinks; "Mechanical rank-ordering" section renamed (no recommendation language); panel-degraded handling for N<3 perspectives; /z-brainstorm Phase 1c ingestion points at MAP.md; rename surface verification grep step added; freshness algorithm codified (mtime-vs-git-commit, untracked excluded); 4-bucket dispatch matrix; tripwires separated automated (3 in v1) vs post-launch telemetry (T1–T4).
  - **D4 amended:** static round-robin via single Opus agent → real vendor diversity via provider-resolution proxies.
