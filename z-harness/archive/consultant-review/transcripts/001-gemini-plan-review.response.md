Ripgrep is not available. Falling back to GrepTool.
Here is the critique of the proposed plan:

**1. Invariant 2 Violation (Memory Loss on Pause)**
The orchestrator currently "collects questions" from `spec_problem` or `decision_needed` in memory, presenting them "only after the batch completes." If a compaction pause triggers at batch-settle, this volatile memory is cleared, and the pending questions are permanently lost. 
*Fix:* Flush all blocked states to `TASKS.md` immediately upon track halt (e.g., `[?] T004 - Needs clarification on X`). Do not hold halts in orchestrator memory.

**2. Batch-Settle Fragility (The Prompt Collision)**
There is a procedural collision at batch-settle. If the orchestrator reaches the 30-minute/5-task limit and halted tracks exist, does it prompt the user for decisions, or does it trigger the compaction pause? If it clears context/pauses first, the user is never prompted for the blocking decisions.
*Fix:* Establish strict batch-settle synchronization. The order must be: 1) Settle batch, 2) Persist all track states/halts to `TASKS.md`, 3) Output decision prompts to the user, 4) Execute compaction pause.

**3. Marker-File Semantics (`/z-review-all`)**
Relying on `archive/<run>/.pre_consult_acknowledged` is highly fragile and violates the spirit of Invariant 2:
*   **Run ID Instability:** If a resume operation after a compaction pause instantiates a *new* `<run>` ID, the system will not find the previous run's marker, breaking idempotence and forcing redundant user prompts.
*   **State Fragmentation:** State is now split between `TASKS.md` and a hidden side-channel file, creating an invisible dependency.
*Fix:* Abandon hidden marker files. Embed the phase progression state directly into `TASKS.md` (e.g., appending a `Note: Phase 3.7 Approved` line to the task block) so standard task parsing handles the resume state entirely.
