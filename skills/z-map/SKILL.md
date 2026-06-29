---
name: z-map
disable-model-invocation: false
description: Legacy compatibility wrapper for obsolete `/z-map`; use `/z-explore --depth=deep` for terrain mapping.
argument-hint: <question or technical area to explore>
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

## STOP — LEGACY COMPATIBILITY WRAPPER

`/z-map` is obsolete. It is retained only as a legacy compatibility name for older docs, artifacts, and command references.

**Print to the user:** "Note: /z-map is obsolete and now routes to /z-explore --depth=deep."

STOP. Do not run a standalone `/z-map` pipeline. Do not present `/z-map` as the active terrain-mapping command. Immediately delegate to the current command, passing `$ARGUMENTS` verbatim, then terminate this command's execution:

```text
/z-explore --depth=deep $ARGUMENTS
```

Preserve the historical `MAP.md` artifact name when referring to legacy `/z-map` outputs or compatibility paths. New terrain-mapping instructions, examples, and handoffs MUST name `/z-explore --depth=deep` as canonical.

## Compatibility checkpoint delegation

`/z-map` has no standalone durable research-note, draft, critique, synthesis, promotion, final-review, or user-facing report seams. It must not create bespoke acknowledgement files or direct `handoff.json` writers here. Do not write `handoff.json` directly; the active terrain command must use `scripts/check-compaction.sh` before `scripts/write-clear-checkpoint.sh`.

All historical `/z-map` checkpoint obligations are inherited by the canonical `/z-explore --depth=deep` terrain flow that this wrapper delegates to. That canonical flow owns the shared `run_workflow_compaction_seam` calls and exports `Z_HARNESS_CHECKPOINT_PHASE_ID`, `Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT`, `Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD`, `Z_HARNESS_CHECKPOINT_STALE_MODE`, and `Z_HARNESS_CHECKPOINT_PRODUCER="z-map"` (or the canonical `z-explore` producer when running as `/z-explore --depth=deep`). The shared hook owns percentage-threshold evaluation, `compaction_pause`, checkpoint metadata, resume/fast-forward state, stale-state handling, and under-threshold fallthrough.

Registered historical map seams (compatibility names; executed by `/z-explore --depth=deep`, not by this wrapper):

| Seam id | When it runs | Durable artifact | Next step |
|---------|--------------|------------------|-----------|
| `map-phase4-pre-critique` | after `research-draft.md` is written, before bundled consultant critique dispatch | `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` | resume at critique dispatch |
| `map-phase4-post-critique` | after critique transcripts are archived, before revised-draft synthesis | `$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json` | resume at synthesis/revision |
| `map-phase4-pre-map-write` | after the revised draft is durable, before final `MAP.md` synthesis/write | `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` | resume at MAP.md synthesis |
| `map-phase5-pre-final-review` | after `MAP.md` is written and promotion/citation metadata is durable, before final review/finalize checks | `$Z_HARNESS_PLAN_DIR/MAP.md` | resume at final review |
| `map-phase5-pre-user-report` | after final review accepts `MAP.md`, before user-facing report generation | `$Z_HARNESS_PLAN_DIR/MAP.md` | resume at final user-facing report |

Skipped candidate seams: no local check in this wrapper before delegation because there is no durable artifact yet; no check while Explore or consultant workers are in flight; no check after a terminal halt because halt finalize owns that terminal state. This wrapper's only safe action is to route immediately to `/z-explore --depth=deep $ARGUMENTS` so resume/fast-forward state belongs to the active terrain command and cannot loop through the obsolete alias.

If the user asks what happened to `/z-map`, answer briefly: `/z-map` is a legacy alias/compatibility surface; `/z-explore --depth=deep` is the active deep terrain exploration flow.
