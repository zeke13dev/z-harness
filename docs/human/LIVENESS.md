# Subagent liveness inspector

## What it is

`scripts/liveness.sh` is a post-hoc reader for `events.jsonl`. It scans a run's
event log for `*_start` events that have no matching `*_end` and reports them
as "possibly stuck" with their elapsed wall time.

It emits no events of its own, makes no LLM calls, and is safe to run any
number of times from a second terminal while a `/z-plan` or `/z-implement-all`
run is in flight.

## Why it exists

Foreground subagents (implementer, consultant, reviewer) are dispatched
synchronously via the Agent tool — while one is in flight, the orchestrator
itself is blocked and cannot poll. From the user's terminal, that looks
identical to a hang. `liveness.sh` gives you a way to disambiguate without
adding heartbeats, polling loops, or any per-subagent LLM cost.

The companion script `scripts/check-timeout.sh` is sourced by the
consultant/reviewer agents at dispatch time. It detects whether `timeout(1)`
or `gtimeout` is on PATH, sets the `TIMEOUT_CMD` variable used by the
dispatch wrappers, and emits a `timeout_availability` event once per run.
This makes the silent-disable failure mode (no `timeout` on PATH, provider
CLI hangs indefinitely) post-hoc debuggable in `events.jsonl`.

The implementer does *not* source `check-timeout.sh` because it doesn't
invoke external CLIs — its hangs are caught by the `implement_start` /
`implement_end` bracket detection in `liveness.sh` directly, which needs no
auxiliary event.

## Usage

```bash
# Most-recently-modified run across all plans + legacy archive
scripts/liveness.sh

# A specific run
scripts/liveness.sh --run 20260524T203829Z-subagent-liveness

# Latest run for a specific slug
scripts/liveness.sh --slug subagent-liveness

# Lower the staleness threshold to 60 seconds (default 300)
scripts/liveness.sh --stale-seconds 60

# Include just-started entries (no staleness filter)
scripts/liveness.sh --all

# Live tail from a second terminal
watch -n 5 scripts/liveness.sh
```

Exit code is 1 if any subagent is flagged, 0 otherwise — usable from another
script if you want to wire up paging.

## What "possibly stuck" means

A `*_start` event with no matching `*_end` is a hint, not proof. Possible
causes, in rough order of likelihood:

1. The subagent is genuinely still working (long implementer task, slow CLI
   consultant). Re-run in a minute; elapsed should still grow but the entry
   may close.
2. The subagent crashed before emitting its `*_end` event.
3. The external provider CLI hung — most likely when
   `timeout_availability.available == false` for this run.

If you see a stuck `consult_*_start` AND `timeout_availability.available
== false` in the same run, the external CLI almost certainly hung silently;
install GNU coreutils (`brew install coreutils`) and re-run.
