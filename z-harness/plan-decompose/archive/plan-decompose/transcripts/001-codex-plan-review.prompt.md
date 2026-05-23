MODE: plan-review

TOPIC: /z-plan-split (plan-decompose)

SPEC EXCERPT (core contracts):
- cluster-planner phases: Phase 0 premise check, Phase 1 exploration (doc-fetcher or read ≤10 files), Phase 2 identify decisions (≤3 expected; ≥4 → return decision_needed), Phase 3 resolve decisions (conservative-flagging if borderline-non-obvious), Phases 4-5 write outputs, Phase 6 return status
- FILES_TOUCHED returned by cluster-planner for reconciliation hook
- SHARED-CONCERNS.md severity heuristics: high = schema/config/migration extensions, medium = code extension + ≥3 clusters, low = code extension + 2 clusters
- One-level recursion hard rule (no nested MANIFESTs)
- /z-implement-all discovery validates: all clusters have finalized TASKS.md (parsed, ≥1 task), no cluster is planning/failed, shared-concerns ack-gate (acknowledged: true or overlap_count: 0)

PLAN EXCERPT (implementation shape):
- 4 tasks: T001 cluster-planner agent def, T002 /z-plan-split command, T003 /z-implement-all extension, T004 docs
- Risks identified: R1 conservative-flagging underestimation, R2 mirror-pair drift, R3 /z-implement-all complexity, R4 ack-gate UX, R5 cluster proposal accuracy, R6 re-entrancy (cluster-planner → doc-fetcher nesting), R7 SHARED-CONCERNS noise

DECISIONS LOCKED:
- D2: B (premise + decision gate, no per-leaf consult) — accepted cross-LLM consensus
- D3: A + ack-gate — passive SHARED-CONCERNS with hard halt on acknowledged: false
- D7: A + one-level cap — extend existing slug-discovery logic, one-level recursion only

CRITIQUE ANGLES — for each, provide 2-4 sentence finding with severity and "one reason this might be wrong" upstream:

1. **Cluster-planner contract gap: undetectable bad decision escalation.** The conservative-flagging rule (Phase 3) says "if unsure whether a decision is non-obvious, escalate." But cluster-planner has no mechanism to detect when it *is* wrong about a decision even after making the call. If a leaf resolves a borderline decision poorly and doesn't flag it, the main thread's Phase 4 reconciliation (file-path overlap only) won't catch a semantic error — only a file collision. Severity?

2. **SHARED-CONCERNS schema: overlaps from cluster-planner FILES_TOUCHED vs parsed TASKS.md.** SPEC Phase 4 says "main thread reads each cluster's TASKS.md and SPEC.md, extracts file paths from each task's `**Files:**` line." But the return value from cluster-planner Phase 6 includes `FILES_TOUCHED: [list of paths...]` as the reconciliation hook. Which is source of truth — re-parse TASKS.md or trust FILES_TOUCHED? If FILES_TOUCHED is a deduplicated summary vs. TASKS.md's per-task file list, a missing file in FILES_TOUCHED means zero overlap detection. Severity?

3. **Conservative-flagging operationalization: no examples or heuristics in agent spec.** The SPEC says cluster-planner should "over-escalate rather than under-escalate" and provides one marker style (`**consult-flagged:**`), but gives no concrete heuristics (e.g., "any decision touching ≥3 files, or involving architectural choice, or breaking compatibility" → escalate). Without examples, T001's acceptance criteria "explicitly require the conservative-flagging rule with examples" is under-specified. Severity?

4. **Ack-gate silent-pass on overlap_count: 0.** SPEC says if `overlap_count: 0`, SHARED-CONCERNS.md is written with `acknowledged: true` (auto-passes). But if a cluster-planner crashed mid-run and produced a partial TASKS.md with only 1 task, FILES_TOUCHED might spuriously show zero overlaps. The ack-gate auto-pass would hide a cluster-failure. Is the assumption that Phase 4 reconciliation can only run if all clusters returned STATUS: ok? Severity?

5. **Phase 4 reconciliation timing: when does it read FILES_TOUCHED?** SPEC Phase 3 says "For each cluster-planner return: STATUS: ok → mark cluster ready." Then Phase 4 reads each cluster's outputs. But Phase 3 also handles decision_needed → re-spawn leaf, unable_to_complete → mark failed. If a leaf is re-spawned (decision gate resolved), Phase 4 must read the *second* return's FILES_TOUCHED, not the first. How does main thread track which return to read — archive/RUN/ glob pattern? Severity?

6. **No path-normalization in overlap detection.** If one cluster's FILES_TOUCHED lists `src/utils.ts` and another lists `./src/utils.ts`, are they detected as the same file? The heuristics depend on exact path matching (e.g., `.*\\.sql` regex). No mention of normalization. Severity?

7. **Decision escalation to main thread but no user-resolution callback contract.** When a leaf returns `STATUS: decision_needed`, SPEC says "main thread surfaces to user via AskUserQuestion and re-spawns the affected leaf when resolved." But there's no spec for: (a) the format of the decision_needed payload (is it free text? structured?), (b) how main thread determines whether to consult Codex or resolve directly on the escalated decision, (c) how the resolution is passed back to the re-spawn prompt. Severity?

8. **One-level cap is enforced at discovery time, not file schema time.** SPEC says /z-implement-all validates "every nested cluster does NOT contain a MANIFEST.md of its own" and halts with tree_depth_exceeded. But a user could manually create a nested MANIFEST.md after /z-plan-split completes. There's no write-time protection (e.g., cluster-planner refuses to write if parent is already nested). Should this be a Phase 0 check by cluster-planner? Severity?

9. **Cluster-proposal seeding skips doc-fetcher only if --clusters= passed.** SPEC Setup step 10 says "if --clusters= passed, skip Phase 1; otherwise dispatch doc-fetcher (iff docs/llm/INDEX.json exists)." If docs don't exist and user passes a topic, /z-plan-split proposes clusters in-context only. This is already noted as R5 (cluster naming may be off for undocumented repos). But SPEC says /z-plan-split "skips the docs-freshness gate (this command doesn't itself touch INDEX.json)" — implying it's intentionally not calling /z-plan Phase 0. Is the assumption that cluster proposal doesn't need INDEX.json freshness validation? Severity?

10. **Task-count explosion in overlapping clusters.** If two clusters both touch `utils.ts` and user runs /z-implement-all, the same file is edited twice in sequence. /z-implement-all's existing task-executor assumes a linear task order; two tasks from different clusters touching the same file could create rebase conflicts in archives. The MANIFEST run-order is sequential, but no "cluster 2 waits for cluster 1 to complete locally before starting" gate. Is this a known limitation or a blocker? Severity?

CONSTRAINTS:
- Decisions D2, D3, D7 are locked and cannot be revisited.
- v1 limitations are acknowledged.
- The critique should identify only genuine gaps, inconsistencies, or risks, not feature requests.

RECOMMENDATION TEMPLATE:
For each finding: severity (blocker / major / minor), one-sentence "why this might be wrong", and concise mitigation/clarification needed.
