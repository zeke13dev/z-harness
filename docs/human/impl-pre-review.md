# impl-pre-review

> Last updated: 2026-07-09
> Covers source: skills/z-execute/SKILL.md, scripts/audit-preview-misses.sh, agents/pre-reviewer.md, agents/complexity-classifier.md

## Overview

`impl-pre-review` documents the z-harness cheap pre-review layer built on the Haiku/Flash-tier `pre-reviewer` and `complexity-classifier` subagents. The primary surface this doc tracks is `runtime.impl_pre_review`, the per-task `/z-execute` gate-down path: when enabled for cycle 1, `/z-execute` re-checks task complexity, uses the cheap `pre-reviewer` only on eligible low-tier work, and skips the codex reviewer only when the pre-reviewer returns `CLEAN`. The knob defaults to `false` and is a byte-identical no-op when off.

A related but separate knob, `runtime.pre_review`, gates a pre-review cycle inside `/z-review-all` (Phase 3.6) and — newly discovered this refresh — inside `/z-audit-plan` (Phase 2.5). Both of those run three cheap pre-reviewer prongs before the production Gemini/Codex consultants, but neither ever skips the production consultants; they only feed extra context in. Those two skills are tracked by their own concept docs (`z-review-all`, `z-audit-plan`) and are out of this doc's `source_file` scope, but are noted here because they share the `pre-reviewer` and `runtime.pre_review` surface.

Legacy env aliases (`Z_HARNESS_IMPL_PRE_REVIEW`, `Z_HARNESS_PRE_REVIEW`) may still be transliterated by config export, but TOML `runtime.*` config is the canonical surface. `scripts/audit-preview-misses.sh` remains the offline evidence-gate harness: it samples `review_gated_down` events, re-runs codex on the archived diff, and reports a Flash false-negative (miss) rate.

## Cost-inversion caveat

Running a cheap reviewer on every task plus codex on the subset that escalates can cost more than running codex directly when most tasks are medium/high or when the pre-reviewer flags many lows. Treat `scripts/audit-preview-misses.sh` as the evidence gate before recommending `runtime.impl_pre_review=true`.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-execute/SKILL.md:2628` — `runtime.impl_pre_review` block header — opt-in, default-off per-task gate-down; documents the cost-inversion caveat and the unconditional-init requirement so the knob-off path stays byte-identical.
- `skills/z-execute/SKILL.md:2646` — outer knob gate — requires `runtime.impl_pre_review == true` and `CYCLE == 1`.
- `skills/z-execute/SKILL.md:2651` — Step 6.P1 tier-drift re-check — strips cached `**Complexity:**` before dispatching `complexity-classifier`; drift-up forces codex.
- `skills/z-execute/SKILL.md:2696` — Step 6.P2 low-tier gate-down — probes the pre-reviewer provider, dispatches `pre-reviewer`, and gates codex only on `CLEAN`.
- `skills/z-execute/SKILL.md:2775` — Step 6.P3 medium/high advisory — pre-reviewer may prepend findings via `FLASH_PREPEND` but cannot gate codex.
- `skills/z-execute/SKILL.md:2804` — downstream skip guard — all codex/self-review/advisory-random-arm reviewer dispatches are nested inside `PRE_REVIEW_GATED_DOWN != 1` (guard closes at line 2916).
- `scripts/audit-preview-misses.sh:1` — offline false-negative audit — samples `review_gated_down` events and re-runs codex on archived diffs; `--demo` mode exercises the flow before the knob has real data.
- `agents/pre-reviewer.md:18` — pre-reviewer modes — `final-review-prong-a`, `final-review-prong-b`, `final-review-quality`, `plan-audit`.
- `agents/complexity-classifier.md:24` — heuristics list — heuristic #1 (user-authored override) returns the cached `**Complexity:**` tier verbatim unless the caller strips it first.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `z-review-all` — Phase 3.6 (now at `skills/z-review-all/SKILL.md:379`, shifted from line 269 at last refresh) runs the same `pre-reviewer` subagent under the separate `runtime.pre_review` knob, but only as a context-prep cycle in front of the production consultants — it never skips them.
- `z-audit-plan` — Phase 2.5 (`skills/z-audit-plan/SKILL.md:397`) is a new consumer of `runtime.pre_review` and the `pre-reviewer` subagent discovered this refresh; same opt-in gate, same three-parallel-prong pattern, same non-gating behavior on plan artifacts.
- `agents` (complexity-classifier, pre-reviewer) — both subagents are shared infrastructure; this concept documents one specific call pattern (per-task gate-down), not the subagents themselves.
- `subagent-telemetry` — `review_gated_down`, `tier_drift_detected`, and `pre_review_skipped` events are the data `audit-preview-misses.sh` consumes.

## Edge cases / gotchas

- Cost inversion is possible; audit `review_gated_down` misses before recommending enablement.
- The cached `**Complexity:**` line must be stripped before the tier-drift re-check, or the classifier's heuristic #1 returns the stale user-authored tier and drift becomes undetectable.
- `pre-reviewer` is line-cited and noise-averse, not a final correctness oracle — it is designed to drop uncertain findings rather than flag them.
- Legacy env aliases (`Z_HARNESS_IMPL_PRE_REVIEW`, `Z_HARNESS_PRE_REVIEW`) exist for config export, but TOML `runtime.*` keys are canonical.
- A malformed or missing `VERDICT:` line is treated as empty and falls through to codex (fail-safe).
- Absolute line numbers in `skills/z-execute/SKILL.md` have shifted substantially since the last refresh (from ~2082-2255 to ~2628-2916) due to unrelated feature growth (intent parallelism, model routing, adaptive compaction) earlier in the file — re-verify line numbers on every refresh rather than assuming stability.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/impl-pre-review.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
