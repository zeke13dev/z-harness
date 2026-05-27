---
artifact: fix
slug: z-audit-plan-style
run_id: 20260527T034427Z-z-audit-plan-style
status: shipped
---

# Fix: z-audit-plan-style

**Status:** shipped — reviewer cleared after 1 retry (1 blocker fixed: undefined `findings` var in Step 4c)

## Problem

The z-harness toolchain has two adjacent capabilities that don't overlap:

- `/z-audit-plan` — pre-implementation audit of plan artifacts (SPEC/PLAN/TASKS), but focused on **correctness** (reference reality-check, logic flaws, race conditions, missing tests).
- `/z-mr-review` — post-implementation review of a git diff, focused on **code quality** (defensive bloat, premature abstraction, DRY/KISS/SOLID, STYLE.md drift, AI-shaped slop).

There is no command that audits a **plan** for the same kind of code-quality issues `/z-mr-review` catches. So if a plan proposes a premature abstraction or a defensive try/except wrapping infallible code, the issue isn't caught until after the code is written and a diff exists. The user wants to catch these at plan-time, before any implementation, when they can be fixed cheaply via `/z-amend`.

## Root cause

Quality-of-design feedback is currently coupled to diff existence. The mr-reviewer agent reads `.patch` files; the plan-audit command treats style as a one-bullet side concern in its design pass. There is no first-class "audit a plan for mr-reviewer-style issues" workflow.

## Approach

Add a new command `/z-audit-plan-style` modeled on `/z-audit-plan`'s plan-discovery and read-only contract, but emitting mr-reviewer-style findings:

1. **New command** `commands/z-audit-plan-style.md`:
   - Discover plan slug under `z-harness/plans/` or `z-harness/` (same logic as `/z-audit-plan`).
   - Hard gate on `STYLE.md` at repo root (same as `/z-mr-review` — no STYLE.md → refuse with pointer to `/z-style-init`).
   - Voice availability pre-check (claude always, codex if available, gemini if available; warn on degraded single-voice).
   - Archive any prior `PLAN_STYLE_AUDIT.md` before overwriting.
   - Run dismissal-signature extraction over prior `PLAN_STYLE_AUDIT.md` snapshots in `archive/`.
   - Concatenate SPEC.md + PLAN.md + TASKS.md into a single `archive/$RUN/plan_artifacts.md` input.
   - Dispatch a new `plan-style-reviewer` agent (sonnet) with the artifacts, STYLE.md, dismissed_signatures, and voices_available.
   - Parse the agent's fenced JSON + Summary, write `PLAN_STYLE_AUDIT.md` to `$BASE/` (canonical) and `$BASE/archive/$RUN/` (snapshot).
   - Per-finding telemetry (`plan_style_finding_emitted`); run-level telemetry (`plan_style_run_start`, `plan_style_run_end`).
   - Final user message points to `/z-amend --from z-harness/<SLUG>/PLAN_STYLE_AUDIT.md` for promotion.

2. **New agent** `agents/plan-style-reviewer.md` (sonnet, ~200 lines):
   - Input contract: `slug, run_id, slug_dir, plan_artifacts_path, style_path, dismissed_signatures_path, voices_available`.
   - Active categories (plan-flavored): `defensive-bloat`, `premature-abstraction`, `dry-kiss-violation`, `solid-violation`, `over-engineering`, `style-drift`, `test-noise`.
   - Severity model: **BLOCKER / MAJOR / MINOR** (matches `/z-audit-plan` family, consumer is `/z-amend`).
   - Step 1: read STYLE.md, plan_artifacts.md, dismissed_signatures.
   - Step 2: inline Claude review across all categories — flag *proposed* patterns (proposed abstractions, planned error-handling, named symbols in code blocks). For style-drift cite `STYLE.md:<rule-id>`. For premature-abstraction cite the existing duplicate by `file:line` (Grep the repo).
   - Step 3: multi-voice dispatch (parallel `Agent()` to `consultant-secondary` (Codex) and `consultant-primary` (Gemini) with same prompt, identical JSON schema requested). Track `voices_succeeded` / `voices_failed` on malformed JSON.
   - Step 4: dedup `(source_file, category, normalized_text)`; consensus tier-bump (all voices agree → promote; single-voice in multi-voice mode → demote; never demote BLOCKER); dismissal-pattern match via Jaccard ≥ 0.6 → tag `[previously-dismissed-pattern]` + demote one tier (BLOCKER stays).
   - Step 5: return fenced JSON `{"findings": [...], "voices_used": [...]}` + `## Summary` block.
   - Finding JSON shape: `severity, category, source_file (SPEC.md|PLAN.md|TASKS.md), line_start, line_end, task_id (null or T-NNN), proposed_symbol (null or string), title, detail, recommendation, citation (null|STYLE.md:rule|file:line), voices`.

3. **Edit** `scripts/extract-dismissals.py`: add `--filename <name>` arg (default `MR-REVIEW.md`) so the same extractor can scan archived `PLAN_STYLE_AUDIT.md` snapshots. Wire-up in command uses `--filename PLAN_STYLE_AUDIT.md`.

4. **New skill alias** `skills/z-audit-plan-style/SKILL.md` (mirrors command, short frontmatter — same pattern as `skills/z-audit-plan/`).

## Files to change

- `/Users/zeke/dev/z-harness/commands/z-audit-plan-style.md` (new)
- `/Users/zeke/dev/z-harness/agents/plan-style-reviewer.md` (new)
- `/Users/zeke/dev/z-harness/skills/z-audit-plan-style/SKILL.md` (new)
- `/Users/zeke/dev/z-harness/scripts/extract-dismissals.py` (edit — add --filename arg)

## Acceptance

- [x] `commands/z-audit-plan-style.md` exists with hard STYLE.md gate, slug discovery mirroring `/z-audit-plan`, dispatch of new `plan-style-reviewer` agent, output to `$BASE/PLAN_STYLE_AUDIT.md`.
- [x] `agents/plan-style-reviewer.md` exists with plan-flavored 7-category taxonomy, BLOCKER/MAJOR/MINOR severities, multi-voice fanout + dedup + tier-bump, dismissal-pattern matching with Jaccard ≥ 0.6.
- [x] `skills/z-audit-plan-style/SKILL.md` exists, mirrors the command (autoload alias).
- [x] `scripts/extract-dismissals.py` accepts `--filename <name>` (default `MR-REVIEW.md`); existing call sites continue to work unchanged.
- [x] No edits to `mr-reviewer.md` or `/z-mr-review` or `/z-audit-plan`.
- [x] `python3 scripts/extract-dismissals.py /tmp/non-existent-slug --filename PLAN_STYLE_AUDIT.md` exits 0 with empty signatures list.

## Cross-LLM consensus
- Gemini: Option B — extend mr-reviewer with `mode: plan` for dismissal continuity.
- Codex:  Hybrid — new agent + extract shared orchestration.
- Synthesized call: new agent (Codex's separation argument) + 3-voice fanout + dismissal extraction (user explicitly chose robust path). Skip Codex's "extract shared orchestration" — out of scope for v1; accept duplication of voice-dispatch/dedup/dismissal-match logic across mr-reviewer and plan-style-reviewer.

## Approved shortcuts
None — user chose robust path including dismissal handling and 3-voice fanout.

## Docs touched
None — z-harness repo has no `docs/llm/`.
