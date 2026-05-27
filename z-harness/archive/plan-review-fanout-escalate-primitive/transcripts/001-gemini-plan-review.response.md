Warning: 256-color support not detected. Using a terminal with at least 256-color support is recommended for a better visual experience.
Ripgrep is not available. Falling back to GrepTool.
Here is a review of the `scope-probe` integration plan, focusing on architectural showstoppers and integration realities.

### 1. Internal Consistency Issues
*   **The Sonnet Bottleneck:** The primary value of using Haiku for `scope-probe` in a "Phase 0" is speed and low token cost. However, the SPEC introduces two Sonnet-based reconcilers (`scope-reconciler-audit` and `scope-reconciler-brainstorm`). If every fast Haiku probe must be parsed, validated, and routed by a slow, expensive Sonnet reconciler before Phase 1, you completely negate the performance benefits of using Haiku in the first place.
*   **Hybrid Output Fragility:** Demanding both "line-prefix routing fields" and "fenced JSON chunks" from Haiku in a single response is notoriously brittle. Haiku often places prefixes *inside* the JSON fence or hallucinates the formatting. A strict JSON-only schema is far more reliable for programmatic routing.
*   **Non-Destructive Overlap:** The SPEC mandates that "v1a is integration-only; deletions of existing escalation chains deferred to v1b." However, layering a new scoping abstraction on top of existing scoping/escalation abstractions without turning the old ones off will result in duplicate LLM calls, conflicting classifications, and severely degraded runtime performance.

### 2. Missing Edge Cases
*   **The `complexity-classifier` Collision (Showstopper):** The ecosystem currently has a Haiku `complexity-classifier` that classifies task complexity. The new `scope-probe` is a Haiku agent that classifies tasks as LIGHT/MEDIUM/HEAVY. This is functionally identical. The SPEC does not address why `scope-probe` is needed instead of refactoring/reusing `complexity-classifier`, nor how the two will coexist without confusing the system state.
*   **Fallback Behaviors:** The SPEC defines a 3-state degradation (high-confidence, low-confidence, refuse), but the PLAN lacks the routing logic for the degradation states. If the probe yields `refuse`, does the host command abort, default to HEAVY (safest/most expensive), or trigger a human-in-the-loop fallback?
*   **Target Scope Empty:** What happens if the target repository or the specified sub-path is empty? The "codebase structure" heuristic will fail.

### 3. Calibration Validation Concerns
*   **Measuring Escalations in a Vacuum:** The calibration harness is slated to run in Phase B (before host integration) and relies on validating 4 tripwires, including "escalation events." You cannot validate or measure host-level escalation events if the host commands haven't been integrated yet.
*   **Ground Truth Corpus:** The metric `tasks_complexity` implies the harness will test the probe against a known set of tasks. The PLAN does not define where this calibration dataset comes from. Without a benchmark of known LIGHT/MEDIUM/HEAVY codebase states, the thresholds are just guesses.

### 4. Phase Ordering Concerns
*   **Circular Dependency (Phase B/D vs. Phase C):** While you *can* build an agent-level unit test harness in Phase B, you cannot execute Phase D (Run calibration, tune thresholds, verify tripwires) in a meaningful way if it depends on end-to-end host metrics (like measuring escalations). 
*   **Corrected Order:** The harness framework can be built in Phase B, but threshold tuning (Phase D) must be done *alongside or after* Phase C (integration) against real host-command execution runs.

### 5. Integration-Point Reality Check (Showstoppers)
*   **`/z-audit` Phase Collision:** Inserting Phase 0 "between Setup and Phase 1" places it directly before `Phase 1: Pre-flight scoping`. You are adding a scoping phase immediately before an existing scoping phase. Since v1a defers deletion of old logic, the script will scope the task twice, almost certainly leading to state conflicts if Phase 0 says "LIGHT" but Phase 1 says "HEAVY".
*   **`/z-audit` Missing `--scope-from` Flag:** The HEAVY fanout relies on a `--scope-from <chunk-path>` flag that does not exist in `/z-audit`. The plan will hard-crash at runtime when the probe attempts to dispatch sub-flows to a flag the CLI parser rejects.
*   **`/z-brainstorm` Chronology Inversion:** Inserting Phase 0 "after Plan Route Check, before Phase 1" is logically backward. The `Plan Route Check` (which uses `planning-router`) relies on assessing the task to decide how to route the plan. The scope of the codebase (Phase 0) is a critical input to that routing decision. Phase 0 must happen *before* the Route Check, not after it.

### 6. Net Verdict
**Verdict: Restructure (Do not ship as-is).**

The plan introduces severe redundancies and structural contradictions. Before any code is written, the design must be revised to address:
1. **Consolidation:** Reconcile the overlap between the existing `complexity-classifier` and the new `scope-probe`.
2. **Flag Support:** Add the `--scope-from` flag to `/z-audit` (or redefine how HEAVY fanout works).
3. **Integration Logic:** Resolve the redundant "Pre-flight scoping" in `/z-audit` and fix the temporal ordering in `/z-brainstorm` (Probe must precede Route Check).
4. **Architectural Simplicity:** Remove the Sonnet reconcilers if this is truly meant to be a fast, lightweight Phase 0 probe. Handle the routing logic deterministically in the host scripts instead.
