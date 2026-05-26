---
name: z-implement-next
description: Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff.
---

You are running the **z-harness `/z-implement-next`** pipeline.

Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 0 — Discover plan slug

Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to operate on:

1. Enumerate candidates:
   - List immediate subdirs of `z-harness/` that contain a `TASKS.md`.
   - Also check for legacy flat layout: a `TASKS.md` directly under `z-harness/` (no slug).
2. Choose:
   - **One candidate** → use it. If slug-namespaced, `export Z_HARNESS_SLUG=<slug>`. If legacy flat, leave `Z_HARNESS_SLUG` unset.
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
   - **Zero candidates** → tell the user there's no plan; suggest `/z-plan`. Stop.
3. From here on, **`BASE`** refers to `$Z_HARNESS_PLAN_DIR` (or `z-harness` if legacy). Paths below use `$BASE`.

## Phase 1 — Load context

1. Read `$BASE/TASKS.md`. Find the first task with status `[ ]`.
2. **Do NOT pre-extract SPEC/PLAN slices in main thread.** Pass `$BASE` to the implementer; the implementer subagent reads `$BASE/SPEC.md` and `$BASE/PLAN.md` itself with its Read tool. Saves main-thread context.
3. (Skip — implementer reads the files it touches.)
4. Create task archive dir: `mkdir -p $BASE/archive/tasks/<task-id>`
5. **Version stamp + task_start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["id"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<task-id>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
   ```

If TASKS.md is missing or has no pending tasks, tell the user and stop.

## Phase 2 — Implement

**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.

Spawn the implementer subagent (fresh context).

**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to $Z_HARNESS_PLAN_DIR>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
)
```

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. Spawn the reviewer with the diff, not just file contents:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
)
```

Apply findings that hold up. Push back on those that don't and document the pushback.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

## Phase 5 — Mark done + notify

1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
4. Brief user summary: what changed, what the reviewer flagged, what's next.

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.
