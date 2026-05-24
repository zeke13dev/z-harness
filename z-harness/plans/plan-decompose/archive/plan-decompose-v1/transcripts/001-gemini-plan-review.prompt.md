MODE: plan-review for `/z-plan-split` (plan-decompose v1)

CONTEXT:
- Earlier bundled-decisions consult locked: D2=B (cluster-planner = premise + decision gate, no per-leaf consult), D3=A+ack-gate, D7=A+one-level-cap
- Mitigations from that consult are now in the SPEC
- This is the full SPEC + PLAN review for correctness/completeness/risk before implementation

SPEC & PLAN SUMMARY:
- `/z-plan-split <topic>` is a pre-emptive scope splitter that fans N clusters to parallel `cluster-planner` subagents, each producing 5-15-task focused plan
- cluster-planner is a Sonnet subagent running 6 phases: premise-check, exploration, identify-decisions (≤3 expected), decision-resolution, write SPEC/PLAN/TASKS, return with FILES_TOUCHED list
- Reconciliation Phase 4 detects file-path overlaps, applies deterministic severity heuristics, writes SHARED-CONCERNS.md with `acknowledged: false` default
- `/z-implement-all` is extended to discover MANIFEST.md, validate cluster-ready, validate ack-gate (hard halt if `acknowledged: false` and `overlap_count > 0`), walk clusters in sequence
- Hard rule: one-level recursion only; nested MANIFEST → `tree_depth_exceeded` error
- Hard rule: cluster-planner conservative-flagging on borderline decisions (over-escalate, return STATUS: decision_needed)
- v1 limitations: no cross-cluster task parallelism, path-only overlap detection, no semantic analysis, no auto-detection of when to use /z-plan-split

QUESTIONS FOR GEMINI (critical gaps + fragile points):

1. **cluster-planner contract holes:** The spec says cluster-planner does "Phase 0 — Premise check (lightweight)" and returns STATUS: decision_needed if concerns surface. But SPEC doesn't define what "concerns surface" means operationally. How does a cluster-planner *recognize* that a premise is unsound *before* exploring? What if exploration reveals premise is wrong? Does cluster-planner re-check? Risk: a leaf could write SPEC/PLAN/TASKS on a malformed premise and return STATUS: ok because it didn't detect the premise was bad until Phase 4 (too late).

2. **Conservative-flagging ambiguity:** SPEC says "**Conservative-flagging rule:** Better to over-escalate than under-escalate. If unsure whether a decision is non-obvious, escalate." But what does "unsure" mean? Does cluster-planner have a rubric (e.g., "any decision touching >3 files, or any architectural choice" = non-obvious)? Or is this left to Sonnet's judgment? If Sonnet misjudges, no reconciliation step catches it — the leaf's wrong call ships into the tree. Risk: actual under-flagging that looks like compliance.

3. **FILES_TOUCHED extraction:** SPEC says cluster-planner returns `FILES_TOUCHED: [list of paths from TASKS.md]` and "main thread extracts paths from this rather than re-parsing TASKS.md." But what format? JSON list? Newline-separated? Are relative paths (e.g., `src/foo.rs`) or absolute (e.g., `z-harness/root/src/foo.rs`)? Inconsistency here breaks reconciliation silently. Risk: missing overlaps or false overlaps if format is ambiguous.

4. **Overlap severity heuristic edge cases:** SHARED-CONCERNS.md schema defines severity as:
   - **high**: matches `.*\.(sql|migration|schema|toml|yaml|yml|proto|json)` or `Dockerfile|Makefile`
   - **medium**: code extension AND appears in ≥3 clusters
   - **low**: code extension, exactly 2 clusters
   
   But what if a file matches *both* a high-severity pattern *and* a low-severity pattern? E.g., `config.ts` (code + config)? What if a file is `package.json` (high-severity schema) but appears in only 1 cluster — does it still flag as high? Risk: ambiguous heuristic applies inconsistently. Recommend: explicitly define precedence and boundary cases.

5. **MANIFEST run-order stability:** SPEC says "Run order: Clusters execute sequentially in this order." Default is "order of cluster confirmation." But if a user drops a cluster and re-runs /z-plan-split, does the MANIFEST get overwritten? Does run-order change? PLAN says "overwrite / abort (drop append)" but doesn't say whether run-order is stable across re-runs. Risk: user re-runs cluster proposal, changes order accidentally, /z-implement-all picks up the new order silently.

6. **Ack-gate and partial trees:** SPEC says "If `overlap_count: 0`, SHARED-CONCERNS.md is still written (for audit/log consistency) but ack-gate auto-passes." And "/z-implement-all discovery refuses to start the tree if `SHARED-CONCERNS.md` exists with `acknowledged: false`." But what if only 1 of 3 clusters completed? Is SHARED-CONCERNS.md written for the 2 completed clusters only? Or do we wait for all? PLAN says "If ≥1 cluster succeeds, proceed to Phase 4 — partial trees are valid." So partial trees should still get reconciliation. But reconciliation on incomplete data: what if the 3rd cluster (never started) would have touched the same files? Risk: ack-gate is based on stale overlap data. Recommend: SHARED-CONCERNS.md mark `partial: true` if not all clusters finished, and warn user that re-running cluster 3 later might update overlaps.

7. **Decision-gate escalation + late changes:** SPEC says "If a decision is borderline-non-obvious (any decision tagged with a `**consult-flagged:**` style marker), return `STATUS: decision_needed` — escalate to main thread." But in Phase 3, main thread does "AskUserQuestion to resolve, then re-spawn the cluster-planner." Does re-spawned cluster-planner start from Phase 1 or Phase 2? If Phase 1 (exploration), does it re-read the same files? If Phase 2 (decisions), does it just re-check the borderline decision? Risk: re-spawn behavior is underspecified; could lead to wasted file-reads or missed dependencies on earlier phases.

8. **Telemetry event gaps:** SPEC lists events like `cluster_decision_escalated`, `overlap_detected`, `shared_concerns_acknowledged`. But what fields? E.g., `cluster_decision_escalated` should include `cluster_id`, `decision_id`, `concern_summary`, right? `overlap_detected` should include `file_path`, `cluster_ids`, `severity`? Risk: implementer adds fields ad-hoc; future queries break.

9. **Two-level subagent nesting (R6):** PLAN says "cluster-planner subagent dispatches `doc-fetcher` subagent in its Phase 1." Does this mean `Agent(subagent_type="doc-fetcher")` from within the cluster-planner subagent? The SPEC says "cluster-planner runs... if docs/llm/INDEX.json exists, dispatch `doc-fetcher` (Haiku)." So doc-fetcher is always dispatched, not just when docs exist — or only when docs exist? Risk: unclear whether cluster-planner calls doc-fetcher unconditionally or conditionally.

10. **Nested MANIFEST detection (one-level cap):** SPEC says "/z-implement-all discovery refuses to start the tree if it discovers nested MANIFESTs (`tree_depth_exceeded` event)." But what counts as "nested"? Does it mean: every cluster in MANIFEST must NOT contain a MANIFEST.md of its own? Or does it mean the cluster dirs are recursively searched and any MANIFEST at any depth is an error? Risk: implementer could miss nested MANIFESTs in subdirs and ship a tree-of-trees bug.

---

CRITICAL QUESTIONS:

For each gap, recommend (a) accept as v1 limitation with user docs, (b) add a validation/check in the spec, or (c) requires rethinking part of the design.

Also flag: any interactions between gaps? E.g., does unclear FILES_TOUCHED format interact with partial-tree overlap recalculation?
