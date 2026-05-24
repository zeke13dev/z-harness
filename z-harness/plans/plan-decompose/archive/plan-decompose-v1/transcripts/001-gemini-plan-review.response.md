Ripgrep is not available. Falling back to GrepTool.
Here is a detailed review of the critical gaps and fragile points in the `z-plan-split` SPEC and PLAN, with recommendations for how to address each one to ensure robustness for the v1 release.

### 1. cluster-planner contract holes (Premise check)
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** "Concerns surface" is too subjective, and discoveries made during Phase 1 (exploration) might invalidate Phase 0.
*   **Fix:** Define a strict rubric for premise failure (e.g., "target files do not exist", "requested architecture contradicts existing codebase patterns"). Add an explicit "Phase 1.5: Premise Re-evaluation" step where the agent must halt and return `STATUS: premise_invalid` if the exploration contradicts the initial premise.

### 2. Conservative-flagging ambiguity
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** "Unsure" is not a programmable directive.
*   **Fix:** Provide a concrete rubric for conservative flagging. Escalation is REQUIRED if a decision involves:
    1. Modifying a public API or interface.
    2. Adding a new external dependency.
    3. Modifying shared configuration/schema files (`*.toml`, `*.json`, `*.sql`).
    4. Structural changes outside the cluster's designated subdirectory.

### 3. FILES_TOUCHED extraction
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** The format and relativity of paths are unspecified, risking silent reconciliation failures.
*   **Fix:** Strictly define the output format. `FILES_TOUCHED` must be a JSON array of string paths, and all paths MUST be absolute relative to the workspace root (e.g., `["src/api/routes.ts", "package.json"]`). The main thread must strictly validate this schema.

### 4. Overlap severity heuristic edge cases
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** Overlapping conditions (e.g., high severity extension + single cluster).
*   **Fix:**
    *   **Precedence:** High > Medium > Low. The highest matching severity wins.
    *   **Baseline:** If a file appears in only 1 cluster, `overlap_count = 0` and severity is `none` (it is not included in `SHARED-CONCERNS.md`).
    *   Update the SPEC to reflect this strict cascading logic.

### 5. MANIFEST run-order stability
**Recommendation: (a) Accept as v1 limitation with user docs.**
*   **Gap:** Run-order might change if the user aborts, edits, and re-runs.
*   **Fix:** Document that `/z-plan-split` is a destructive generation command for the MANIFEST. If the user drops a cluster and re-runs, the MANIFEST is completely overwritten, and a new deterministic run-order is established.

### 6. Ack-gate and partial trees
**Recommendation: (c) Requires rethinking part of the design.**
*   **Gap:** Reconciling overlaps on partial trees gives a false sense of security; missing clusters might contain critical overlaps.
*   **Fix:** Do not treat partial trees as fully valid. If a tree completes partially, `SHARED-CONCERNS.md` must include a top-level field `partial_tree_warning: true`. The `/z-implement-all` command must hard-halt if `partial_tree_warning: true` is present, requiring the user to explicitly pass a `--force-partial` flag or re-run the missing clusters.

### 7. Decision-gate escalation + late changes
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** Agent respawn state is undefined.
*   **Fix:** When the main thread respawns the cluster-planner after resolving a decision, it passes the context as "Resolved Decisions" injected into the prompt. The agent technically runs from Phase 0, but the prompt instructs it to fast-track exploration based on the resolved decisions.

### 8. Telemetry event gaps
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** Event schemas are missing.
*   **Fix:** Explicitly define the required fields in the SPEC.
    *   `cluster_decision_escalated`: `{ cluster_id, decision_summary, flagged_reason }`
    *   `overlap_detected`: `{ file_path, overlapping_clusters: [], severity }`
    *   `shared_concerns_acknowledged`: `{ total_overlaps, highest_severity }`

### 9. Two-level subagent nesting (R6)
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** Unclear condition for `doc-fetcher` dispatch.
*   **Fix:** Clarify that the dispatch is strictly conditional. The `cluster-planner` may ONLY invoke the `doc-fetcher` if it explicitly identifies a need for documentation AND a known documentation index (like `docs/llm/INDEX.json`) is present.

### 10. Nested MANIFEST detection (one-level cap)
**Recommendation: (b) Add a validation/check in the spec.**
*   **Gap:** Definition of "nested".
*   **Fix:** Define nested as: "A recursive glob search for `**/MANIFEST.md` starting from the directory of any cluster defined in the root MANIFEST."
