---
name: z-continue
disable-model-invocation: true
description: "Foreground continuation aid: inspect one handoff, render a bounded current-thread nudge, or authorize one exact read-only resume."
argument-hint: "--handoff <path> [--task TNNN] [--nudge|--continue --sha256 <digest> --select <token>|--write-handoff|--archive|--clean-locks|--prune-worktrees]"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-continue`**. This is a foreground,
host-agnostic continuation aid. It has no daemon, polling loop, process or
worktree ownership, durable approval record, or external notification channel.
All output belongs in the invoking task/thread.

## Arguments

Require exactly one action:

- default (no action): inspect `--handoff <path>`;
- `--nudge`: render one bounded nudge for an exact selected target;
- `--continue`: authorize and run exactly one read-only resume;
- `--write-handoff`: explicitly run `/z-handoff`, then stop;
- `--archive`, `--clean-locks`, or `--prune-worktrees`: render the matching
  `/z-reconcile` command only.

`--handoff <path>` is required for default, `--nudge`, and `--continue`.
`--task <TNNN>`, `--sha256 <digest>`, and `--select <token>` are required only
for `--continue`. Reject unknown flags, combined actions, or missing required
values. Never infer a path from a global scan.

## Inspection

Run the helper from the installed plugin root with the invoking workspace as
`--repo-root`:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/continuation-approval.py" inspect \
  --handoff "$HANDOFF_PATH" --repo-root "$PWD" ${TASK_ID:+--task "$TASK_ID"}
```

Render the returned JSON or a concise faithful summary. A refusal, ambiguous
target, stale/degraded evidence, or invalid handoff is attention information;
do not choose a target or run another command.

## Bounded nudge

When `--nudge` is selected, first complete Inspection. Only when `ok=true`,
render one message in this task/thread:

```
Nudge: a validated handoff is ready for the selected work item. Review the
reported `/z-resume --select ...` step or continue manually; no action ran.
```

Do not send the nudge to another task, desktop notification, webhook, chat,
email, process, or terminal. Do not persist a deduplication record.

## Explicit handoff

When `--write-handoff` is selected, run `/z-handoff` with the caller's optional
continuation prompt. Report its result and stop. Do not call `/z-continue
--continue` afterward; writing a handoff is an explicit mutation but not an
authorization to resume it.

## Cleanup recommendations

`--archive`, `--clean-locks`, and `--prune-worktrees` never mutate anything.
Render exactly one of these copyable commands and stop:

```
/z-reconcile --archive-plans
/z-reconcile --clean-locks
/z-reconcile --prune-worktrees
```

`/z-reconcile` owns classification and its per-item risk confirmations. Never
wrap, batch, pre-answer, or bypass those confirmations.

## One-shot continuation

When `--continue` is selected, run:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/continuation-approval.py" authorize \
  --handoff "$HANDOFF_PATH" --repo-root "$PWD" --task "$TASK_ID" \
  --sha256 "$HANDOFF_SHA256" --select "$SELECTION_TOKEN"
```

If `ok=false`, render the refusal and stop. If `ok=true`, read `command` from
the helper result and invoke exactly that `/z-resume --select <token>` command
in the invoking task. Do not append arguments, substitute a target, invoke
planning/implementation/attended/cleanup commands, or retain the approval.

## Hard rules

- The handoff SHA-256, task id, and selection token are a one-shot approval
  tuple. A changed handoff invalidates it.
- Only the helper may authorize continuation; never reconstruct its checks in
  this skill.
- No archive, lock removal, worktree removal, process termination, or external
  message is available from this command.
