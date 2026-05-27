You are reviewing code that Claude just wrote for task T010 (RESUME, post-amend): Insert Phase 0 into /z-brainstorm per AMENDED SPEC.

Spec (excerpt from fanout-escalate-primitive SPEC.md — commands/z-brainstorm section):
- Phase 0 runs immediately after Setup — BEFORE Plan Route Check, BEFORE Phase 1 scaffolding begins
- Dispatches scope-probe with host_command, topic, axis_taxonomy, repo_root, run_id
- Parses hybrid return (line-prefix headers + fenced JSON)
- Writes SCOPE artifacts archive-first, then live (with fallback on archive failure)
- Parser failure: emit scope_probe_malformed, treat as refused + MEDIUM
- Low-confidence: emit scope_probe_low_confidence, downgrade to MEDIUM
- HEAVY branch: N parallel sub-flows with $Z_HARNESS_PARENT_RUN_ID, skip Phase 0 + Plan Route Check, run Phase 1+2+3
- Dispatch scope-reconciler-brainstorm to merge per-chunk BRAINSTORM.md files
- Phase 4 chunk-selection is TBD (T016)
- LIGHT/MEDIUM: pass through unchanged

Acceptance criteria:
1. Phase 0 inserted as LITERAL FIRST action after Setup — BEFORE Plan Route Check, BEFORE Phase 1
2. AXIS_TAXONOMY=["per_vendor","per_framing"]
3. Dispatches scope-probe, parses hybrid return per SPEC parser safety rule, writes SCOPE archive + live
4. scope-probe dispatches doc-fetcher internally
5. HEAVY branch: N parallel sub-flows pass $Z_HARNESS_PARENT_RUN_ID; skip Phase 0 + Plan Route Check, run Phase 1+2+3
6. After sub-flows return: dispatch scope-reconciler-brainstorm to merge per-chunk BRAINSTORM.md
7. HEAVY parent-level Phase 4 chunk-selection is TBD (T016)
8. LIGHT/MEDIUM: pass through unchanged (proceed to Plan Route Check then Phase 1)

Focus on prior cycle-1 review blockers:
- Phase order contradiction (should be resolved by Phase 0 BEFORE Plan Route Check)
- HEAVY sub-flow artifact production (should be addressed by running through Phase 3)
- Phase 4 chunk-selection missing (should be delegated to T016)
- Unreachable refused/bad_input event logging (check if still present)
