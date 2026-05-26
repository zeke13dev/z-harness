# Fix: subagent-liveness

**Run:** 20260524T203829Z-subagent-liveness
**Status:** shipped
**Plugin version:** 380aca6 (dirty, main)

## Problem
The orchestrator sometimes cannot tell whether a foreground subagent (implementer, consultant, reviewer) is still working or has silently failed. The user wanted "orchestrator polls every 5-10m" but foreground Agent calls block the orchestrator — there's nothing to poll *from*. Three real failure modes remain: (a) external CLI consultants hang silently when `timeout(1)`/`gtimeout` is missing (current code only stderr-warns once per shell); (b) implementer emits `implement_start` but never `implement_end`; (c) the user has no signal of progress while the Agent call is in flight.

## Root cause
The harness has the primitive (`events.jsonl` with `*_start`/`*_end` brackets, written via `scripts/log-phase.sh` and `scripts/log-event.sh`) but no consumer of it for liveness. Additionally, the missing-`timeout` failure mode is invisible in `events.jsonl` — only a once-per-shell stderr warning fires.

## Approach
Option B (both consultants converged): post-hoc inspector + structured `timeout_availability` event. No polling, no orchestrator-flow changes, no LLM token cost.

1. **New `scripts/check-timeout.sh`** — sourceable helper. Probes PATH for `timeout`/`gtimeout`, sets `TIMEOUT_CMD` env var, and emits one `timeout_availability` event per run (idempotent via `.timeout-logged` marker file under the run dir, mirroring the `.providers-logged` pattern). Replaces the inline detection block currently duplicated in three agent files.
2. **New `scripts/liveness.sh`** — scans `events.jsonl` for `*_start` events without a matching `*_end`. Defaults to the latest run; flags `--run`, `--slug`, `--stale-seconds`. Output is a short table with subagent kind + elapsed wall time. Supports `watch scripts/liveness.sh` for live tailing from a second terminal.
3. **Update three agent files** (`agents/consultant-primary.md`, `agents/consultant-secondary.md`, `agents/reviewer.md`) — replace the duplicated 5-line `TIMEOUT_CMD` detection block with a `source "$PLUGIN_ROOT/scripts/check-timeout.sh" "$RUN"` call. Mechanically identical change in 3 places.
4. **New `docs/human/LIVENESS.md`** — short one-page on how to use the inspector. Skip `docs/llm/liveness.json` + INDEX.json update for now — `/z-maintain-docs --audit` can backfill later (this keeps the fix at 6 files instead of 8).

## Files to change
- `/Users/zeke/dev/z-harness/scripts/check-timeout.sh` (new)
- `/Users/zeke/dev/z-harness/scripts/liveness.sh` (new)
- `/Users/zeke/dev/z-harness/agents/consultant-primary.md` (edit)
- `/Users/zeke/dev/z-harness/agents/consultant-secondary.md` (edit)
- `/Users/zeke/dev/z-harness/agents/reviewer.md` (edit)
- `/Users/zeke/dev/z-harness/docs/human/LIVENESS.md` (new)

## Acceptance
- [x] `scripts/liveness.sh` runs against an existing `events.jsonl` and reports any `*_start` with no `*_end` plus elapsed seconds; exits 0 (no stuck) or 1 (stuck found).
- [x] `scripts/check-timeout.sh` when sourced sets `TIMEOUT_CMD` (empty if neither `timeout` nor `gtimeout` available) and emits exactly one `timeout_availability` event per run.
- [x] Each of the three agent files calls `check-timeout.sh` instead of detecting inline; the `TIMEOUT_CMD` variable is still referenced by the subsequent CLI-call block (no behavior change to provider invocation).
- [x] `docs/human/LIVENESS.md` documents the inspector with one usage example.
- [x] No regression: a normal `/z-plan` or `/z-implement-next` run still works (verified by syntax-checking the scripts and reviewing the agent diffs — no e2e test in light mode).

## Cross-LLM consensus
- Gemini: Option B. Flagged that fail-fast on missing `timeout` is a follow-up; suggested `watch scripts/liveness.sh` pattern.
- Codex:  Option B. Flagged that "no `*_end`" is "possibly stuck" not "dead" — script must label accordingly.
- Synthesized call: ship Option B. Script labels output as "possibly stuck" with elapsed time. Defer fail-fast.

## Approved shortcuts
- Skip `docs/llm/liveness.json` + INDEX.json registration in this fix; flag for `/z-maintain-docs --audit` follow-up. (User approved "minimal" docs option.)
- Keep current "warn + disable" behavior when `timeout(1)` is missing rather than hard-erroring (user rejected Gemini's fail-fast shortcut).

## Review history
- v1 review: 6 majors, all fixed (RUN setup, lifecycle deny-list, find maxdepth, --slug latest, warning-before-marker, atomic mkdir marker).
- v2 review: degraded — Codex timed out per the reviewer wrapper; findings were largely spurious. One legitimate doc clarification applied (implementer doesn't source check-timeout.sh).
- v3 review: real Codex review. 1 blocker (no consult_start before CLI) + 4 majors (task lifecycle alt-end markers; retry/cycle in match key; marker created before event; JSON escaping). All applied.
- v4 review: 2 follow-on blockers from the v3 changes (tuple-unpack mismatch in row loop; role missing from match_key). Both fixed.
- v5 review: 2 blockers + 2 majors. v5 Blocker 1 was a re-occurrence of the spurious "RUN placeholder" misread from v2; rejected. v5 Blocker 2 (consult_start JSON escaping for bounded-enum values) and both majors were theoretical defensiveness; explicitly skipped per user decision to ship.

## Docs touched
- `docs/human/LIVENESS.md` (new — concept doesn't exist in INDEX.json yet; suggest `/z-maintain-docs --audit` to register)
