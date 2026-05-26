# MODE: bundled-decisions

## Context: z-harness token-overflow guard

The orchestrator (Claude Code session) cannot read its own token usage and cannot self-invoke /compact or /clear. The only lever: pause + push-notify the user to run /compact or /clear, then resume from durable state (TASKS.md).

**Background:** Usage-% guard was specced but never wired; zero usage_pause events in metrics across many runs; one long run failed with unable_to_complete after retry=4, suggesting context degradation under loops.

## Three decisions flagged for input:

### D2. Primary breakpoint trigger in /z-implement-all
Options:
(a) Every N completed tasks (default N=5). ← tentative
(b) Every N batches of up to 3 parallel tracks (default 2).
(c) Cumulative implementer-subagent count (default 8, retries count).
(d) Multi-trigger (a OR wall-time).

### D3. Add breakpoint in /z-review-all before Phase 4 (cumulative-diff consultant spawn — heaviest single context burn)?
(a) Yes — pre-Phase-4 push notification: "about to spawn consultants; /compact first if needed, then continue". ← tentative
(b) No — review-all is one-shot; user can manually /compact before invoking.

### D6. Recommend /clear or /compact in the resume message?
(a) /compact (preserves summary of prior work).
(b) /clear (orchestrator's resume is idempotent — re-reads TASKS.md, picks next pending — so clearing loses nothing; reclaims more context). ← tentative

## Ask
For each decision, recommend with reasoning, tradeoffs, missed considerations, and decision interactions. Be concrete about edge cases. Keep to ≤350 words total.
