**D2 Recommendation: (d) Multi-trigger, but make it cheap: 5 completed tasks OR 30 minutes**

Best default: pause after `completed_task_count_since_pause >= 5 || elapsed_since_pause >= 30m`.

Why:
- Fast tasks: 5 × 2 min = pause around 10 min, maybe conservative but acceptable.
- Slow tasks: wall-time prevents 5 × 10 min = 50 min uninterrupted drift.
- Parallelism: count completed tasks, not batches. A 3-track batch that finishes 3 tasks counts as 3. This maps to durable progress in `TASKS.md`.
- Retry-heavy tasks: retries should not count as completed tasks, but wall-time catches them. A task retrying for 35 min pauses after the current retry/batch boundary.
- Subagent count is tempting, but harder to explain and reviewers/consultants distort the cost model. Completed tasks plus wall-time is more operationally predictable.

Use envs like:

```text
Z_IMPLEMENT_PAUSE_TASKS=5
Z_IMPLEMENT_PAUSE_MINUTES=30
```

Pause only at clean sync boundaries: after a task finishes, after review retry resolves, or after a batch settles. Never pause mid-subagent.

**D3 Recommendation: Yes, pre-Phase-4 pause**

Worth the UX friction. Phase 4 is a known context spike: two consultants each reading `SPEC.md`, `PLAN.md`, `TASKS.md`, `cumulative.diff`, and `docs/llm/*.json`. If `cumulative.diff` is huge, this is exactly where quality collapses.

Make it conditional rather than unconditional:

```text
if cumulative.diff > 100k lines OR estimated context > 60%
```

For `>500k` lines, do not just pause; also warn that consultants may need diff slicing or scoped review.

Message:

```text
Review is about to spawn high-context consultants. Run /clear or /compact first, then re-invoke /z-review-all to resume Phase 4.
```

**D6 Recommendation: Prefer `/clear`, mention `/compact` as debugging fallback**

Default message should recommend `/clear`:

```text
Usage at ~87%; pausing at a durable checkpoint. Run /clear, then re-invoke /z-implement-all to resume from TASKS.md. Use /compact instead if you need this chat history for debugging.
```

Edge cases:
- Manual `TASKS.md` edits are fine; resume re-reads disk, so `/clear` does not hide them from the orchestrator.
- Mid-batch crash recovery is cleaner with `/clear` if task state is durable and incomplete tasks remain pending.
- `/compact` is useful only when diagnosing orchestrator behavior from chat history.

Interaction: D2 must pause only after durable writes. That is what makes `/clear` safe.
