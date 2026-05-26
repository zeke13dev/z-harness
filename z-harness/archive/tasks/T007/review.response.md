## Codex Review: T007

### Blockers
None identified by Codex.

### Major

1. **[commands/z-uplift.md:1788](/Users/zeke/dev/z-harness/commands/z-uplift.md:1788)** `auditor_failed` AskUserQuestion is prose-only. There is no concrete `log-event.sh "$RUN" user_wait_start`, `_WAIT_T0`, AskUserQuestion placeholder, `USER_WAIT_MS_PHASE3` accumulation, or `user_wait_end` code block.
   Suggested fix: add the same explicit bash wrapper pattern used elsewhere, with payload `{"phase":3,"reason":"auditor_failed","component":"...","dimension":"..."}` before the AskUserQuestion and `user_wait_end` after it.

2. **[commands/z-uplift.md:2099](/Users/zeke/dev/z-harness/commands/z-uplift.md:2099)** `reviewer_blocker` AskUserQuestion is also prose-only. This misses the acceptance criterion requiring every AskUserQuestion block to be wrapped by actual `user_wait_start` / `user_wait_end` logging.
   Suggested fix: add an explicit shell snippet around the reviewer-blocker halt path and accumulate into `USER_WAIT_MS_PHASE3`.

3. **[commands/z-uplift.md:2518](/Users/zeke/dev/z-harness/commands/z-uplift.md:2518)** `component_implement_start` payload does not match the spec. Spec requires `{component, task_count}`; current payload is `{component, tasks_md}`.
   Suggested fix: compute `TASK_COUNT` from `COMP_TASKS_MD` before logging and emit `{"component":"...","task_count":%d}`.

4. **[commands/z-uplift.md:2405](/Users/zeke/dev/z-harness/commands/z-uplift.md:2405), [commands/z-uplift.md:2665](/Users/zeke/dev/z-harness/commands/z-uplift.md:2665)** `component_implement_done` payload does not match the spec. Spec requires `{component, completed, halted}`; current payload uses `outcome` and omits both booleans.
   Suggested fix: emit `{"component":"...","completed":true,"halted":false}` for successful/auto/manual completion.
