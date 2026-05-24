# PLAN — brainstorm-and-research

## Goal

Add two opt-in pre-plan slash commands — `/z-brainstorm` and `/z-research` — that separate exploration from plan-commitment. Both feed into `/z-plan` via the same slug dir using two distinct artifact files (`BRAINSTORM.md`, `RESEARCH.md`).

## Decisions (with rationale)

| ID | Decision | Pick | Rationale |
|----|---|---|---|
| D1 | Artifact contract | A (distinct files, YAML frontmatter) | Semantically clear schemas beat forced unification. Both consultants converged independently. Frontmatter handles metadata needs without a separate manifest. |
| D2 | Ideator composition | D (Claude + Codex + Gemini, anti-bias via structured returns) | Vendor diversity is the core value. Anti-bias guardrail is procedural (compare structured-return sections), not structural. Codex specifically argued against dropping Claude. |
| D3 | /z-research Explore cap | A (hard cap = 3) | Forcing focus is a feature. Chain `/z-research` runs for breadth. No env override in v1. |
| D4 | Slug derivation across chain | A (shared slug, `--slug` override) | Matches existing slug-as-task-identity pattern. `--slug` flag covers intentional chaining. `/z-plan` collision detection updated to distinguish precontext-only dirs from finished plans. |
| D5 | RESEARCH.md → ideator context | A with extractive-summary fallback >20 KB | Symmetric inline context to all 3 ideators (no Claude-read-by-reference asymmetry). Extractive summary preserves citations and constraints. Summary stored in archive for audit. |
| D6 | /z-plan seed-artifact detection placement | A (Setup step 10, before Phase 0) | Precontext informs the premise check itself; treating it as exploration-only scaffolding wastes prior work. |
| D7 | New `MODE: research-review` for /z-research critique | A (new mode, not reuse `light-fix`) | Consultant return shape differs: light-fix asks for a recommendation; research-review explicitly forbids one. Reusing modes invites prompt drift. |
| D8 | Orchestrator recommendation in /z-brainstorm | B (orchestrator recommends with one-line rationale) | Hiding the orchestrator's read isn't honest; state it explicitly, let user override. Skip cross-LLM vote (too expensive for the value). |

## Non-goals

- Pluggable ideator model list (default `[claude-sonnet, codex, gemini]`; future v2).
- Auto-detection of "this task needs precontext" inside `/z-plan` — keep opt-in per `feedback-explicit-commands`.
- `/z-brainstorm-light` or `/z-research-light` variants.
- Streaming / real-time ideator returns.
- Resolving `commands/` vs `skills/` mirror duplication (out-of-scope meta-concern).
- A `/z-precontext` umbrella command.

## Approved shortcuts

None. Every decision picked the robust option.

## Phases

The implementation is split into independently-implementable tasks (sized for `/z-implement-all`'s per-task fresh-context guarantee).

### Phase A — Foundations (artifact schemas + agent extensions)
Establishes the contracts everything else depends on.
- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.

### Phase B — `/z-brainstorm` command (collapsed mirror task)
- T003: Create both `commands/z-brainstorm.md` AND `skills/z-brainstorm/SKILL.md` in one dispatch. Acceptance includes byte-near-identity check.

### Phase C — `/z-research` command (collapsed mirror task)
- T004: Create both `commands/z-research.md` AND `skills/z-research/SKILL.md` in one dispatch.

### Phase D — `/z-plan` integration (collapsed mirror task)
- T005: Update both `commands/z-plan.md` AND `skills/z-plan/SKILL.md`. Note: Setup step 10 already pre-applied in the working tree; this task verifies and completes the remaining pieces (Phase 0 inject prose, Phase 1 boundary tightening, Phase 6 SPEC.md template `Planning Inputs` section, collision-handling rule).

### Phase E — Documentation
- T006: Update `README.md` with new commands, chain example, env vars.

**Total: 6 tasks** (was 9 before mirror collapse).

## Risks (carry-forward to implementation)

- **R1.** Each new command requires byte-near-identical authoring in two places (`commands/` and `skills/`). High risk of drift between the two. Mitigation: pair T003+T004 and T005+T006 in the same implementer dispatch so the same context produces both. /z-implement-all schedules these as sibling tasks.
- **R2.** Codex and Gemini consultants have rate limits (we hit Gemini's during the per-task-model-selection run). `/z-brainstorm` Phase 2 dispatches BOTH in parallel — if either fails, the brainstorm yields only 2 framings instead of 3. Mitigation: implementer handles graceful degradation, records `ideator_failed` event, and lets the user pick from the remaining framings.
- **R3.** `/z-research`'s 2M-token cost ceiling is aspirational; over-curious orchestrators can blow through it. Mitigation: cost-confirmation gate at Phase 0 + per-Explore wall-clock budget; halt and warn if a single Explore exceeds 5 minutes wall time.
- **R4.** `/z-plan` Setup step 10 changes Setup ordering — must not break existing slug dirs. Mitigation: precontext-only dirs are continuations (no prompt); finished plan dirs are collisions (prompt as today). Test with both shapes in T007's acceptance criteria.
- **R5.** Source-mtime freshness check on RESEARCH.md requires parsing `file:line` citations out of Markdown. Mitigation: tolerant regex (`/[^\s]+\.(rs|py|md|ts|json|toml|yaml|yml)(:\d+)?/`) + fail-open if parsing fails (log a `precontext_freshness_check_failed` event and continue).

## Consumed precontext

None (this `/z-plan` run was fresh; no `BRAINSTORM.md` or `RESEARCH.md` existed for the `brainstorm-and-research` slug).

## DRY / KISS / SOLID applied

- **DRY:** Single multi-mode pattern for consultants; YAML frontmatter shared across artifact types; `--slug` parsing shared across commands.
- **KISS:** Distinct artifacts (not unified schema); hard caps (no premature env-var configurability); no auto-detection.
- **SOLID:** Each command does one thing (`/z-brainstorm` = ideate; `/z-research` = map; `/z-plan` = plan). `/z-plan` is open for extension (precontext) but closed for modification (the rest of its phases are untouched).
