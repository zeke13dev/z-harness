# Phase 1 — Context

## Problem
The orchestrator sometimes can't tell whether a foreground subagent (implementer, consultant, reviewer) is still working or has silently failed. The original ask was a 5–10 minute polling loop; the premise check rejected that (foreground Agent calls block the orchestrator — nothing to poll *from*). The real failure modes are: (a) hung external CLI consultant when `timeout(1)` isn't on PATH; (b) long-running implementer that produced an `implement_start` but no `implement_end`; (c) the user staring at the CLI with no signal of whether progress is happening.

## Context
The harness already emits `*_start`/`*_end` event pairs to `events.jsonl` via `scripts/log-phase.sh` (used by implementers per `agents/implementer.md:22-31`). External consultants already wrap CLI calls in `timeout $TIMEOUT_CMD` using `timeout_s` from the provider descriptor (`agents/consultant-primary.md:28-46`), but if neither `timeout` nor `gtimeout` is on PATH the timeout silently disables — only a stderr warning fires, guarded by `Z_HARNESS_TIMEOUT_WARNED` so it doesn't even repeat. There is no consumer of `events.jsonl` that surfaces "started but never ended" rows. No heartbeats between `_start` and `_end`.

## Likely-touched files
1. `scripts/liveness.sh` (NEW) — scan `events.jsonl` for unclosed `_start` events, report stuck subagents with elapsed time.
2. `scripts/log-providers.sh` OR a new run-start hook — emit a structured `timeout_availability` event so post-hoc analysis sees when timeouts were silently disabled.
3. `agents/consultant-primary.md` + `agents/consultant-secondary.md` + `agents/reviewer.md` — replace the env-var-guarded one-shot stderr warning with a `log-event.sh ... timeout_disabled` call (or move detection to a shared run-start hook).
4. `docs/human/<new>.md` + `docs/llm/<new>.json` — document the liveness inspector.

Scope: 2–4 files. Well within light-mode.
