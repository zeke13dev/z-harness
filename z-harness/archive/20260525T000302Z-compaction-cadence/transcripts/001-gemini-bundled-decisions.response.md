### D2: Primary breakpoint trigger in `/z-implement-all`
**Recommend: (c) Cumulative implementer-subagent count.**
*   **Reasoning:** Context bloat is driven by payload exchanges, not conceptual "tasks". Counting sub-agent spawns (including retries) is the most accurate proxy for actual token burn. 
*   **Tradeoffs:** Less predictable timing for the user compared to a flat task count.
*   **Edge Case:** Under option (a), a single complex task failing and retrying 6 times will silently exhaust context before the `N=5` task breakpoint triggers. Option (c) safely catches this retry doom loop.

### D3: Breakpoint in `/z-review-all` before Phase 4?
**Recommend: (a) Yes.**
*   **Reasoning:** `/z-review-all` is frequently invoked *after* a heavy implementation phase. Launching multiple consultants (the heaviest single burn) on an already-degraded context window invites catastrophic failure (`unable_to_complete`). 
*   **Tradeoffs:** Introduces manual friction into a nominally "one-shot" workflow.
*   **Missed Consideration:** The pause might feel annoying if the user *just* cleared context. To mitigate, frame the prompt as a strong recommendation rather than a hard blocker: *"Ready for Phase 4. Highly recommend /clear before continuing if you haven't recently."*

### D6: Recommend `/clear` or `/compact`?
**Recommend: (b) `/clear`.**
*   **Reasoning:** Because the orchestrator's resume sequence is fully idempotent via `TASKS.md`, `/clear` maximizes token reclamation. `/compact` retains a rolling summary that degrades strict prompt adherence over time and still consumes valuable context overhead.
*   **Interaction (D2+D6):** Using `/clear` wipes the orchestrator's implicit working memory. 
*   **Edge Case Mitigation:** Before the orchestrator pauses and recommends `/clear`, it *must* persist any critical cross-task realizations (e.g., "Library X actually requires flag Y on this OS") into `TASKS.md` metadata or `MEMORY.md`. Otherwise, post-`/clear`, the agent will repeat identical mistakes on subsequent tasks.
