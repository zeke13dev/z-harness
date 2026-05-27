# v1a shipped

Run: 20260527T201122Z-review
Verdict from final review: SHIP with 2 amendments (both applied inline post-review).

## Amendments applied
1. **Atomic live SCOPE-audit.json write** in `commands/z-audit.md` — changed simple redirect to tmp+rename to match archive-first invariant; prevents partial-overwrite on parallel runs sharing a slug.
2. **Sub-flow prompt clarity** in `commands/z-brainstorm.md` HEAVY Phase 0 — replaced "Write the BRAINSTORM.md at path" (sub-agent has no Write tool) with "produce content; orchestrator writes". Also added explicit parent-orchestrator-writes-per-chunk-files step to make the contract uniform with the reconciler.

## Acknowledged deferrals (noted in findings.md, accepted)
- `/z-plan` integration with `chosen_pair` frontmatter — v1b follow-up (PLAN.md non-goal).
- v1a calibration stub limits Tripwires 3/4 to manual gates — CALIBRATION-EPOCH-1-SIGNOFF.md correctly framed.
- Live SCOPE-*.json garbage collection — deferred per SPEC.

## v1b gates (per CALIBRATION-EPOCH-1-SIGNOFF.md)
- First real-world HEAVY trigger needed before deletions of existing mid-flight escalation chains are validated.
- Then re-run scope-probe-calibrate.py epoch 2 with real Haiku-dispatched data.
- Then `/z-amend` SPEC.md to lift v1b from "deferred" to active scope.

## Cumulative diff stats
- 16 v1a files
- +2622 / -100 lines
- Bundled into mega-commit 4cba78e (along with unrelated TOML config slice — keep aware on git log inspection).
