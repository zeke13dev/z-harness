Ripgrep is not available. Falling back to GrepTool.
### 1. Framing

Shift the paradigm from "Memory as an Active Interruption" to "Memory as Continuous Reinforcement Learning (RL)." Instead of relying on the user to manually invoke `/z-improve` or `/z-suggest-memory` when they feel a lesson was learned, the harness should treat the execution lifecycle—specifically review rejections and implementation retries—as an RL environment. By monitoring negative reward signals (errors, linters, rejected MRs), the harness can passively formulate policy updates (draft memories) in the background and present them as a low-friction "Commit these lessons?" summary at the end of the run.

### 2. Core hypothesis

If we hook into the existing telemetry (`events.jsonl`) to detect friction (e.g., `task_review_retry`, test failures in `z-implement-all`), we can mimic an RL update phase by automatically spinning off a background task to draft a structured memory. Surfacing these pre-computed, high-context drafts at the very end of a `/z-review-all` or `/z-implement-all` run as a simple "Approve/Reject" batch will drastically increase the capture rate of long-term behavioral fixes without annoying the user with mid-task prompts.

### 3. Risks

*   **Alert/Review Fatigue:** If the system attempts to synthesize a memory for every trivial syntax error or minor linter fix, the user will develop muscle memory to blindly reject the post-run memory batch, defeating the purpose.
*   **Misattribution of Root Cause (Hallucinated Lessons):** The LLM drafting the memory might incorrectly correlate a fix to the wrong architectural rule, polluting `docs/llm/*.json` with actively harmful constraints that will derail future `doc-fetcher` runs.
*   **Tag Dilution:** Auto-generated drafts might overuse or incorrectly apply the controlled tag seed (`docs/llm/TAGS.txt`), making downstream retrieval by `doc-fetcher` less precise.

### 4. Plan implications

*   **Workflow Updates:** Modify `commands/z-implement-all.md` and `commands/z-review-all.md`. At the completion of their respective loops, evaluate the telemetry for the run. If friction thresholds are met (e.g., `retry_count > 0`), invoke a new post-run phase: `Phase X: Auto-Retro`.
*   **Agent Capabilities:** Introduce a `--draft-batch` or `--auto-retro` flag to `/z-suggest-memory`. This allows it to run non-interactively based on the run's event log, compiling a proposed list of memories.
*   **User Experience:** The final output of a complex run becomes a reviewable diff of proposed memories. The default action remains "Cancel/Reject" to ensure quality, but the cognitive load is reduced to just reading and approving.
*   **z-debug Spec:** Formally specify the missing Phase 9 in `commands/z-debug.md` to ensure it pushes its post-mortem context into this exact same drafting pipeline.

### 5. What would change my mind

If early adoption or telemetry shows that users are rejecting >80% of the auto-drafted memories, or if the background synthesis adds more than 15-20 seconds to the end of a run. If the signal-to-noise ratio is that poor, we should abandon the RL-mimicry of "auto-drafting policies from failures" and instead enforce a hard, manual prompt like: *"You had 3 retries. What did we learn? (Leave blank to skip)"* to force human synthesis.
