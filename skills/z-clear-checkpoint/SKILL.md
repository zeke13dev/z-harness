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

## Procedure

1. Require `Z_HARNESS_PLAN_DIR`. If absent, stop with the script error.
2. If `$ARGUMENTS` is non-empty, export it as `Z_HARNESS_CHECKPOINT_NEXT_STEP`.
3. Default checkpoint status to `context_pressure` unless the caller set `Z_HARNESS_CHECKPOINT_STATUS`.
4. Call the script:

```bash
export Z_HARNESS_CHECKPOINT_STATUS="${Z_HARNESS_CHECKPOINT_STATUS:-context_pressure}"
if [ -n "$ARGUMENTS" ]; then
  export Z_HARNESS_CHECKPOINT_NEXT_STEP="$ARGUMENTS"
fi
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-clear-checkpoint.sh"
```

5. Return the script's `STATUS: clear_checkpoint ...` line to the user verbatim.

## Consumer contract

A watcher may treat `clear_checkpoint_written` as a clear-safe yield signal when:

- `handoff.json` exists at the emitted `handoff_path`.
- The handoff validates against `docs/schemas/handoff.schema.json`.
- The watcher can load every file in `context_files` or can surface a precise missing-file error.

After consuming a token, the watcher owns session creation and may delete or archive `handoff.json`. The producer never assumes a specific watcher implementation.

## Hard rules

- No Hermes-specific branching. `consumer: "watcher"` in telemetry means any orchestrator.
- Do not inline plan artifacts into `next_step`; point at files through `context_files`.
- Do not mutate `TASKS.md`, `SESSION.md`, `LEDGER.md`, or source files.
- No emojis.
