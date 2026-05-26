Ripgrep is not available. Falling back to GrepTool.
1. Framing: Trajectory-as-Experience.
The current memory architecture treats documentation as a static library to be "pulled" by the agent (`doc-fetcher`). To move toward a Hermes-style long-term memory, we must treat every `/z-implement-all` and `/z-review-all` run as a training episode. In this frame, memory is not just "facts about the code," but "trajectories of the agent"—capturing where the plan diverged from reality (pivots), what reviews were rejected (failed paths), and which decisions were terminal. We are transitioning from a **Documentation Harness** to an **Experience Engine**.

2. Core hypothesis: Differential Trajectory Encoding.
We can significantly reduce decision re-litigation by implementing a **Shadow Memory** layer that automatically records "Differential Trajectories" (Plan vs. Outcome) without requiring immediate user approval. By automatically labeling every run with an **Outcome Tag** (e.g., `SUCCESS`, `FAIL:SPEC_DRIFT`, `FAIL:REVIEW_LOOP`) and caching the resulting "Reasoning Deltas" in a local `pending/` directory, we create a dense reinforcement signal. These pending memories can be injected into the `doc-fetcher` search space as "Experience Buffers," allowing the agent to "remember" why a specific architectural path was previously abandoned in an earlier session, even if a formal document hasn't been authored yet.

3. Risks.
- **Timid Agent Syndrome:** If the agent over-indexes on a single failure (e.g., a flaky test or transient environment issue), it may become "allergic" to valid paths, refusing to try complex implementations because a "Shadow Memory" suggests they are high-risk.
- **Trajectory Pollution:** Low-signal noise from trivial runs (e.g., small documentation fixes) could dilute high-signal "Differential Memories," causing `doc-fetcher` to waste context on irrelevant history.
- **Prompt Sensitivity to Failure:** Injecting "Negative Examples" (what *not* to do) can sometimes confuse LLMs, causing them to hallucinate the failure mode into the new implementation.

4. Plan implications.
- **Mandatory Outcome Hook:** Modify `/z-implement-all` and `/z-review-all` to execute a `trajectory-labeler.md` subagent upon completion (or halt). This agent compares the initial `SPEC.md` against the final `archive/events.jsonl` to generate a 1-paragraph "Differential Memory."
- **Soft-Auto-Retro:** Replace the generic "Do you want to run /z-improve?" prompt with a "Review Draft Memories" UI. The agent presents 2-3 pre-authored memories derived from the run's pivots; the user only needs to hit `Confirm` or `Edit`, reducing friction.
- **Experience-Aware Doc-Fetcher:** Update `doc-fetcher` to prioritize searching the `pending/` (Shadow Memory) directory when a query matches a previous plan's slug, effectively bridging the gap between sessions before formal `docs/llm/` promotion.
- **Hermes-style Reasoning Log:** Standardize the `cross_task_notes` and `decisions-late.md` to include "Reasoning traces" that are explicitly formatted for potential DPO (Direct Preference Optimization) training of future internal models.

5. What would change my mind.
If we observe that the "Experience Buffer" significantly increases token latency for `doc-fetcher` without a measurable decrease in "Plan Revision Cycles," the complexity is unjustified. Furthermore, if "Shadow Memories" lead to "Reasoning Inconsistency" (where the agent contradicts itself because it is over-weighting a specific previous failure over current code reality), we should revert to a strictly human-vetted documentation model.
