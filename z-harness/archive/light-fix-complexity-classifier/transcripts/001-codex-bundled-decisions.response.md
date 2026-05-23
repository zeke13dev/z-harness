Recommend **Option A: plan-time stamping**, with a narrow mitigation: `/z-amend` should preserve existing `**Complexity:**` stamps for unchanged tasks and classify only new or materially rewritten task blocks.

Why A fits this as a light fix:

- It is the simplest operational model: `TASKS.md` becomes the source of truth, and implementers just read `low|medium|high`.
- It gives the user a visible, hand-editable override, which matters because model choice is partly judgment.
- It avoids adding dispatch-time state, retry caches, task hashes, or hidden orchestration behavior.
- It integrates cleanly with the current pattern that already checks `**Complexity:** high`.

I would not pick B. Dispatch-time classification is cheap per call, but it adds latency and failure surface exactly when the user expects implementation to start. More importantly, it hides the decision. If the classifier is wrong, the only override path is code/config instead of editing `TASKS.md`.

I would not pick full C. Hash-based edit detection is cleaner in theory, but it is extra mechanism for a light fix. You get most of C's benefit by making `/z-amend` conservative: preserve stamps unless the task text is newly created or deliberately rewritten.

The `/z-amend churn` risk is real but manageable. LLM classifiers are not reliably deterministic unless you force very tight prompting, low temperature, stable input ordering, and stable surrounding context. Even then, model/provider changes can drift. Mitigation for Option A:

- Classify only tasks missing `**Complexity:**`.
- Preserve user-edited stamps.
- On `/z-amend`, do not reclassify unchanged task blocks.
- If a task is materially rewritten, either remove/recreate its stamp or explicitly ask the classifier only for that task.
- Log the classifier rationale briefly somewhere internal if useful, but keep `TASKS.md` clean.

Retry interaction: dispatch should compute model from complexity plus retry bump directly, using the new `Agent(..., model=...)` override. For today:

- `low` -> `sonnet`
- `medium` -> `sonnet`
- `high` -> `opus`
- retry bump: `medium` -> `high` -> `opus`; `high` stays `opus`

One subtle issue: `low` bumped to `medium` still maps to Sonnet today, so the retry bump has no practical effect for low tasks. That is fine if `low` is truly reserved, but if you expect every failed review to receive a stronger model next attempt, then retry logic should map 'failed once' to Opus regardless of low/medium.

Future outcome-learning does not justify B now. You can add outcome-aware behavior later from `events.jsonl` without changing the visible complexity stamp model. Treat the stamp as the initial prior; future logic can override at dispatch only when there is explicit evidence.

Assessment on dispatch-time cost: Haiku cost is probably negligible in dollars and usually small in latency, but it adds up in orchestration friction: task count × retries × resumed runs × classifier failures. The bigger cost is invisible nondeterminism during implementation. For this fix, plan-time visible stamping is simpler-right.
