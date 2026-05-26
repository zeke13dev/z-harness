## Mode
light-fix

## Problem
In z-harness orchestrator, users cannot tell whether a foreground subagent (implementer, consultant, reviewer) is still working or has silently failed. Real failure modes:
- External CLI consultants hang when timeout(1)/gtimeout not on PATH — one-shot stderr warning only, no structured event
- Implementers emit `implement_start` but never `implement_end` when they die — events.jsonl has no consumer surfacing stuck tasks
- User stares at CLI with no progress signal

Execution constraint: Agent calls are synchronous from orchestrator's perspective — no mid-call polling possible.

## Key decision: minimum-viable liveness mechanism

**Option A: Post-hoc inspector only**
- New `scripts/liveness.sh` scans events.jsonl for unclosed `*_start` events, prints stuck subagents with elapsed wall time
- User runs it from second terminal when uncertain
- Zero new events; zero LLM token cost; no orchestrator-flow changes

**Option B: A + timeout_availability event**
- Same post-hoc inspector as A
- Emit structured `timeout_availability` event once per run (replaces silent stderr warning in consultant/reviewer agents)
- Captures silent-disable failure mode in events.jsonl for post-hoc analysis
- Minimal cost: one extra event per run

**Option C: B + task_progress heartbeats**
- Same A and B
- Add `task_progress` heartbeat events in implementer at natural checkpoints (post-file-read, post-edit, post-test)
- Mid-task visibility from second terminal via events.jsonl
- Adds noise to events.jsonl, increases agents/implementer.md change-surface
- BUT: orchestrator itself cannot read these while blocked on synchronous Agent call — only user with separate terminal can see them

## Constraints
- User explicitly raised "will this just burn tokens?" so cost matters
- z-harness already brackets work with `*_start`/`*_end` via scripts/log-phase.sh
- External consultants already wrap in `timeout $TIMEOUT_CMD` but disable silently if command not found
- Foreground subagents dispatched synchronously — no interleaving possible

## Ask
Which option (A, B, or C) should we ship? Be brief. Flag anything we haven't considered.
