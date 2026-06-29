---
name: z-clear-checkpoint
disable-model-invocation: true
description: Write a watcher-readable clear checkpoint. Produces handoff.json plus telemetry so Oh My Pi, Hermes, MCP, or any future watcher can clear and resume from a fresh session.
argument-hint: "[continuation prompt — optional override for next_step]"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-clear-checkpoint`** — the generic clear/yield checkpoint producer.

Continuation prompt (from `$ARGUMENTS`, optional):

$ARGUMENTS

## Purpose

This command is not Hermes-specific. It writes the same artifacts any watcher can consume:

- `handoff.json` in `$Z_HARNESS_PLAN_DIR` — machine-readable resume token.
- `SESSION.md` if it already exists — human/orchestrator re-seed context for `/z-execute`.
- `clear_checkpoint_written` telemetry event — stable watcher signal.

The command does **not** perform `/clear` itself. Drivers that support automatic clearing (for example a future Oh My Pi watcher) can watch for the event or the `handoff.json` file, clear the session, then resume with the handoff's `next_step` and `context_files`.

## Shared hook/checkpoint contract

Workflow skills use this command as the single explicit `/clear` checkpoint hook at durable phase seams. The caller may set these env vars before invocation instead of writing local ack/fast-forward shell snippets:

| Env var | Meaning |
|---|---|
| `Z_HARNESS_CHECKPOINT_STATUS` | Handoff status: `context_pressure`, `clean_break`, `complete`, or `blocked`. Defaults to `context_pressure`. |
| `Z_HARNESS_CHECKPOINT_NEXT_STEP` | `handoff.json.next_step` override. `$ARGUMENTS` maps here when present. |
| `Z_HARNESS_CHECKPOINT_RESUME_COMMAND` | Command a watcher/operator should run after `/clear`; defaults to `/z-execute <slug>` when a slug exists. |
| `Z_HARNESS_CHECKPOINT_PHASE_NAME` / `Z_HARNESS_CHECKPOINT_PHASE_ID` | Human label and stable id for the durable seam. `PHASE_ID` enables a default fast-forward state file. |
| `Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT` | Path to the artifact that proves the pre-checkpoint phase completed; must exist and is rechecked on fast-forward. |
| `Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD` | Caller-computed freshness token such as HEAD SHA, input-set hash, or artifact digest. |
| `Z_HARNESS_CHECKPOINT_STATE_FILE` | Optional explicit state file path; relative paths live under `$Z_HARNESS_PLAN_DIR`. |
| `Z_HARNESS_CHECKPOINT_STALE_MODE` | Existing stale state behavior: `reject` (default), `refresh`, or `ignore`. |
| `Z_HARNESS_CHECKPOINT_PRODUCER` / `Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON` | Logical workflow producer and JSON-object metadata for telemetry/state. |

On first invocation at a seam, the script writes `handoff.json`, emits `clear_checkpoint_written`, writes checkpoint state when phase/state/guard/artifact metadata is present, and prints `STATUS: clear_checkpoint ...`. On the next invocation with the same fresh state, it emits `clear_checkpoint_fast_forward` and prints `STATUS: clear_checkpoint_fast_forward ...`; the workflow continues to the post-checkpoint phase. If state exists but the guard/artifact/phase is stale, the default is fail-closed rejection.

## Procedure

1. Require `Z_HARNESS_PLAN_DIR`. If absent, stop with the script error.
2. If `$ARGUMENTS` is non-empty, export it as `Z_HARNESS_CHECKPOINT_NEXT_STEP`.
3. Set any seam metadata (`PHASE_ID`, `COMPLETED_ARTIFACT`, guard, resume command, producer metadata) before calling the script.
4. Call the script:

```bash
export Z_HARNESS_CHECKPOINT_STATUS="${Z_HARNESS_CHECKPOINT_STATUS:-context_pressure}"
if [ -n "$ARGUMENTS" ]; then
  export Z_HARNESS_CHECKPOINT_NEXT_STEP="$ARGUMENTS"
fi
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-clear-checkpoint.sh"
```

5. If stdout starts with `STATUS: clear_checkpoint_fast_forward`, continue past the checkpointed seam.
6. If stdout starts with `STATUS: clear_checkpoint`, return that line verbatim, notify the operator/watcher to `/clear`, and stop the current workflow before high-context work.

## Consumer contract

A watcher may treat `clear_checkpoint_written` as a clear-safe yield signal when:

- `handoff.json` exists at the emitted `handoff_path`.
- The handoff validates against `docs/schemas/handoff.schema.json`.
- The watcher can load every file in `context_files` or can surface a precise missing-file error.
- Optional phase metadata (`phase_id`, `phase_name`, `checkpoint_state_path`, `completed_artifact`, `fast_forward_guard`) is treated as resume/fast-forward guidance, not as part of the `handoff.json` schema.

After consuming a token, the watcher owns session creation and may delete or archive `handoff.json`. The producer never assumes a specific watcher implementation.

## Hard rules

- No Hermes-specific branching. `consumer: "watcher"` in telemetry means any orchestrator.
- Do not inline plan artifacts into `next_step`; point at files through `context_files`.
- Do not mutate `TASKS.md`, `SESSION.md`, `LEDGER.md`, or source files.
- No emojis.
