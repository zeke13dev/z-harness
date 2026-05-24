Ripgrep is not available. Falling back to GrepTool.
Here is the consultation on the three architectural decisions for the `/z-plan-split` feature, based on the constraints of keeping v1 cheap, simple, and aligned with existing patterns.

### D2. `cluster-planner` agent — what phases does it run?
**Recommendation: B (Premise + Write + Light decision gate)**
For narrow scopes, the likelihood of a high-stakes, non-obvious decision is low. If a leaf encounters a complex decision, it often indicates either a poorly drawn boundary or a hidden shared concern. Halting and bubbling `STATUS: decision_needed` back to the main thread is much safer than blindly proceeding or silently racking up costs with automated cross-LLM consultations.
*   **Tradeoffs:** You save significant token costs and latency by bypassing the consult phase for the 90% of leaves that are straightforward. The cost is that if a leaf does hit a snag, it requires synchronous user intervention to unblock it.
*   **Missed / Edge Cases:** How does a user resume a halted leaf? If a cluster planner halts with `decision_needed`, the system needs a clean resumption path (e.g., a way to inject the user's decision and restart the leaf without re-running the entire cluster).

### D3. Reconciliation depth — what does main thread produce?
**Recommendation: A (Passive file-path overlap → `SHARED-CONCERNS.md`)**
Active reconciliation (B or C) across parallel agent outputs is notoriously fragile and prone to hallucinated merges or dropped context. For a "cheap v1," identifying file-path overlaps and documenting them passively gives the user the necessary visibility without introducing brittle auto-merge logic.
*   **Tradeoffs:** You save massive engineering complexity by avoiding automated scaffolding of shared concerns. The tradeoff is entirely on the user: they must read the passive note and take manual action before implementation begins.
*   **Missed / Edge Cases:** File-level overlap is a blunt instrument. Two clusters adding independent functions to `utils.ts` will trigger a shared concern flag, even if there is no functional conflict. The passive note might become "boy who cried wolf" if false positives are high.

### D7. `/z-implement-all` extension — how does it walk the tree?
**Recommendation: A (Extend existing `/z-implement-all` discovery)**
Users view `/z-implement-all` as the universal "execute the plan" command. Extending its initial discovery phase to parse `MANIFEST.md` and queue clusters is far superior to duplicating the already complex execution, batching, and retry logic into a new `/z-implement-tree` command. The discovery logic changes, but the core execution engine remains unified.
*   **Tradeoffs:** You pay a small complexity tax in the initialization phase of `/z-implement-all`. You save the immense long-term burden of maintaining two identical task-runner state machines.
*   **Missed / Edge Cases:** How does cluster run-order interact with the existing N=3 parallel tracks? If `/z-implement-all` strictly waits for Cluster 1 to finish before starting Cluster 2, and Cluster 1 only has 1 task, you are starving your concurrency.

### INTERACTION WARNINGS

*   **D3 (A) ↔ D7 (A) [The Blind Execution Risk]:** If reconciliation purely generates a passive `SHARED-CONCERNS.md` (D3=A), and `/z-implement-all` automatically discovers and executes the tree (D7=A), a user might just blindly run `/z-implement-all` immediately after planning. **Mitigation:** `/z-implement-all` must check for `SHARED-CONCERNS.md` during its discovery phase. If the file exists and is not explicitly acknowledged or resolved by the user, `/z-implement-all` should hard-halt before execution to prevent race conditions on shared files.
*   **D2 (B) ↔ D7 (A) [Incomplete Tree Risk]:** If a leaf halts with `decision_needed` (D2=B) and the user forgets to resolve it, the `MANIFEST.md` might be left in a partial state. `/z-implement-all` must rigorously validate that all clusters listed in the manifest have a finalized, valid `TASKS.md` before starting the overarching run.