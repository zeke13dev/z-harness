**Findings**

1. **Consultant return shape conflicts with brainstorm output.**  
   SPEC requires ideators to return exactly five sections for `/z-brainstorm` [SPEC.md:169](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:169), but later says both new consultant modes follow the existing consultant return shape with recommendation/reasoning/tradeoffs/etc. [SPEC.md:268](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:268). Existing consultants also hard-code that shape [agents/codex-consultant.md:49](/Users/zeke/dev/z-harness/agents/codex-consultant.md:49). An implementer could preserve consultant consistency and break brainstorm parsing, or preserve brainstorm parsing and violate the stated agent pattern.

2. **PLAN's R2 degradation contradicts SPEC acceptance and artifact schema.**  
   PLAN says if Codex or Gemini fails, brainstorm can yield only 2 framings [PLAN.md:60](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:60). SPEC schema and acceptance require three ideators and "3 framings" [SPEC.md:31](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:31), [SPEC.md:332](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:332). This leaves malformed-but-acceptable runs undefined: whether missing ideators become `<missing>`, failed framings, or fewer options.

3. **The "Restart" flow is inconsistent.**  
   Artifact invariant says selecting "Restart" moves `BRAINSTORM.md` to `archive/<run>/BRAINSTORM.md.abandoned` and starts fresh [SPEC.md:75](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:75). Phase 3 gate offers "Restart with different topic framing" plus "Abandon" [SPEC.md:187](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:187), but Phase 4 only describes saving the chosen framing and logging run end [SPEC.md:189](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:189). The state machine for restart/abandon is underspecified.

4. **Source freshness uses incompatible time representations.**  
   RESEARCH frontmatter stores `generated_at` as ISO 8601 UTC [SPEC.md:89](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:89), while the freshness check compares source `mtime` against that field [SPEC.md:284](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:284). The plan does not specify parsing, timezone normalization, symlink handling, deleted files, or citation ranges. R5 only covers tolerant citation regex and fail-open parsing [PLAN.md:63](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:63), not the actual comparison edge cases.

5. **Citation format is internally inconsistent.**  
   RESEARCH invariants require specific `file:line` ranges [SPEC.md:120](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:120), but R5's regex only clearly supports optional single-line `:\d+` and a narrow extension list [PLAN.md:63](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:63). It may miss range formats, extensionless files, shell scripts, lockfiles, config variants, or paths with punctuation/spaces.

6. **`/z-plan` "optional doc-fetcher and Explore" may conflict with current Phase 1 rule.**  
   Existing `/z-plan` says "doc-fetcher FIRST, Explore for gaps" and spawns doc-fetcher if docs exist [commands/z-plan.md:90](/Users/zeke/dev/z-harness/commands/z-plan.md:90). SPEC says if fresh `RESEARCH.md` exists, doc-fetcher and Explore are optional [SPEC.md:296](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:296). That is a behavioral change, not just scaffolding, and the boundary between "research is enough" and "Phase 1 must still run" is vague.

7. **Conflict detection is conceptually required but mechanically underspecified.**  
   `/z-plan` must detect contradictions between RESEARCH constraints and BRAINSTORM chosen framing [SPEC.md:286](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:286). No schema makes constraints machine-checkable, and no threshold distinguishes "potential conflict" from normal planning tension. This is likely to become subjective prose matching inside Setup.

8. **Task decomposition may waste review cycles through mirror-only tasks.**  
   PLAN splits command and skill mirrors into separate tasks T003/T004 and T005/T006 [PLAN.md:42](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:42), while R1 says pair them in the same implementer dispatch [PLAN.md:59](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:59). That conflicts with the stated "independently-implementable tasks" sizing [PLAN.md:35](/Users/zeke/dev/z-harness/brainstorm-and-research/PLAN.md:35). Separate review of mirrors invites drift and duplicate review findings.

9. **Acceptance lacks concrete validation for `/z-plan` integration.**  
   Acceptance tests cover a basic `/z-research` write and `/z-brainstorm` consuming existing research [SPEC.md:332](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:332), but not the highest-risk integration: precontext-only continuation, finished-plan collision, stale cited source warning, unfinalized brainstorm, both-artifact conflict, or Phase 6 `Planning Inputs`.

10. **Telemetry fields are specified without a source of truth.**  
    New logs include `tokens_spent`, `ideator_durations_ms`, `consultant_durations_ms`, and `findings_count` [SPEC.md:191](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:191), [SPEC.md:250](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:250). Existing consultant logging has prompt/response chars and wall time, not token counts [agents/codex-consultant.md:81](/Users/zeke/dev/z-harness/agents/codex-consultant.md:81). Implementers may invent incompatible approximations.

**Boundary Notes**

- `research_temptation` logging feels over-specified for v1 because no current telemetry consumer is identified [SPEC.md:121](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:121). It adds behavioral bookkeeping around an instruction that is already mandatory.
- The Claude ideator details are fragile: SPEC names `subagent_type="general-purpose"` and `model="sonnet"` [SPEC.md:179](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:179), but this repo's commands generally describe slash-command behavior for Claude Code, not portable subagent availability. That may be environment-specific command prose rather than durable framework behavior.
- In scope but thinly specified: slug parsing with quoted topics and `--slug=X`, overwrite/append semantics for existing `BRAINSTORM.md`, and archive naming for multiple abandoned runs.
