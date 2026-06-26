# impl-pre-review

> Last updated: 2026-06-24
> Covers source: skills/z-execute/SKILL.md, skills/z-review-all/SKILL.md, scripts/audit-preview-misses.sh, agents/pre-reviewer.md, agents/complexity-classifier.md

## Overview

`impl-pre-review` documents the z-harness cheap pre-review layer. There are two related but separate knobs:

- `runtime.impl_pre_review` controls the per-task `/z-execute` gate-down path. When enabled for cycle 1, `/z-execute` re-checks task complexity, uses the cheap `pre-reviewer` only on eligible low-tier work, and skips the codex reviewer only when Flash returns `CLEAN`.
- `runtime.pre_review` controls `/z-review-all` Phase 3.6. That path runs three cheap pre-review prongs before the production Gemini/Codex final-review consultants, but it never skips the production consultants.

Both knobs default to `false`. The legacy env aliases (`Z_HARNESS_IMPL_PRE_REVIEW`, `Z_HARNESS_PRE_REVIEW`) may still be transliterated by config export, but TOML config is the canonical surface.

## Cost-inversion caveat

Running a cheap reviewer on every task plus codex on the subset that escalates can cost more than running codex directly when most tasks are medium/high or when Flash flags many lows. Treat `scripts/audit-preview-misses.sh` as the evidence gate before recommending `runtime.impl_pre_review=true`.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-execute/SKILL.md:2082` — `runtime.impl_pre_review` block — opt-in, default-off per-task gate-down; documents the cost-inversion caveat and no-op fallthrough.
- `skills/z-execute/SKILL.md:2100` — outer knob gate — requires `runtime.impl_pre_review == true` and `CYCLE == 1`.
- `skills/z-execute/SKILL.md:2105` — Step 6.P1 tier-drift re-check — strips cached `**Complexity:**` before dispatching `complexity-classifier`.
- `skills/z-execute/SKILL.md:2150` — Step 6.P2 low-tier gate-down — dispatches `pre-reviewer` and gates codex only on `CLEAN`.
- `skills/z-execute/SKILL.md:2229` — Step 6.P3 medium/high advisory — Flash may prepend findings but cannot gate codex.
- `skills/z-execute/SKILL.md:2255` — downstream skip guard — all codex/self-review/advisory reviewer dispatches are inside `PRE_REVIEW_GATED_DOWN != 1`.
- `skills/z-review-all/SKILL.md:269` — Phase 3.6 pre-review cycle — `runtime.pre_review` opt-in, separate from impl gate-down.
- `scripts/audit-preview-misses.sh:1` — offline false-negative audit — samples `review_gated_down` events and re-runs codex on archived diffs.
- `agents/pre-reviewer.md:18` — pre-reviewer modes — `final-review-prong-a`, `final-review-prong-b`, `final-review-quality`, `plan-audit`.
- `agents/complexity-classifier.md:24` — cached-tier heuristic — returns user-authored `**Complexity:**` unless the caller strips it.
<!-- AUTO-END: entry-points -->

## Per-task gate-down flow

1. Initialize `PRE_REVIEW_GATED_DOWN=0` and `FLASH_PREPEND=""` before the knob block.
2. If the knob is on and this is cycle 1, strip the cached complexity stamp and re-classify the live task.
3. Drift-up forces codex (`PRE_REVIEW_GATE_DOWN=0`). No drift keeps the task eligible.
4. Only eligible low-tier tasks can be gated down. Provider unavailable, malformed verdict, or `MAJORS_FOUND`/`BLOCKERS_FOUND` all fall through to codex.
5. Only `CLEAN` sets `PRE_REVIEW_GATED_DOWN=1`, emits `review_gated_down`, and skips codex.
6. Medium/high tasks are advisory-only; Flash findings may be prepended to codex but cannot decide the outcome.

## Invariants

- `runtime.impl_pre_review=false` is a no-op: codex behavior is unchanged.
- Gate-down runs only on cycle 1; retry cycles use the full reviewer.
- Provider unavailable or malformed Flash output fails safe to codex.
- `PRE_REVIEW_GATE_DOWN` (eligibility) and `PRE_REVIEW_GATED_DOWN` (actual skip decision) are distinct variables and must not be unified.
- `/z-review-all` `runtime.pre_review` is a context-prep cycle only; it never skips Gemini/Codex consultants.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/impl-pre-review.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
