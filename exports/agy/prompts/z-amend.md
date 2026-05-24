---
description: Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen...
role: workflow
---

You are running the **z-harness `/z-amend`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.

This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.

## Phase 0 — Discover plan slug

Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:

1. Enumerate candidates: immediate subdirs of `z-harness/` that contain **any** of `SPEC.md`, `PLAN.md`, `TASKS.md`, or `FIX.md`. Also check for legacy flat layout.
2. Choose:
   - **One candidate** → use it. `export Z_HARNESS_SLUG=<slug>` (or leave unset for legacy).
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
   - **Zero candidates** → tell the user there's no plan to amend; suggest `/z-plan` or `/z-plan-light`. Stop.
3. From here on, **`$BASE`** refers to `$Z_HARNESS_PLAN_DIR` (or `z-harness` if legacy).
4. Detect **mode**:
   - `full` if `$BASE/SPEC.md` exists.
   - `light` if only `$BASE/FIX.md` exists.

## Phase 1 — Setup + telemetry

1. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-amend-<slug>`
2. `mkdir -p $BASE/archive/$RUN/transcripts`
3. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["amendment"] = sys.argv[2]; v["mode"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "<full|light>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
   ```
4. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 2 — Read the current plan

Read every artifact that exists for this slug:

- **full mode:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
- **light mode:** `$BASE/FIX.md`

For **full mode**, also snapshot completed task state. Run:
```bash
grep -E '^\- \[x\] T[0-9]+' $BASE/TASKS.md > $BASE/archive/$RUN/completed-tasks.txt || true
```
This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.

## Phase 3 — Impact analysis

Articulate, in plain prose, what the amendment changes. Write `$BASE/archive/$RUN/amendment.md`:

```markdown
# Amendment: <one-line summary>

**Run:** <RUN>
**Mode:** <full|light>
**Requested change:** <verbatim $ARGUMENTS>

## What this affects

### SPEC.md   (full mode only)
- <bullet per section that changes; "no change" if none>

### PLAN.md   (full mode only)
- <decisions added/changed/removed; phases reordered; non-goals added/dropped>

### TASKS.md  (full mode only)
- **New tasks:** T0NN, T0NN+1, ... (next IDs after current max)
- **Modified tasks:** T0NN (status `[ ]` → still `[ ]`, but acceptance/files/deps changed)
- **Removed tasks:** T0NN (only if status `[ ]`; never remove `[x]`)
- **Touched-but-completed tasks:** T0NN (status `[x]` — flag for user decision)

### FIX.md    (light mode only)
- <which sections change: Problem / Root cause / Approach / Files / Acceptance>

## Risk
- Does this change cross any auto-bail threshold (new external dep, public API change, schema change, cross-module)? If yes → flag for consult in Phase 5.
```

**ID-allocation rule:** new tasks always take fresh IDs (max existing + 1, ...). Never reuse a deleted task's ID.

**Completed-task rule:** if a `[x]` task's behavior is contradicted by the amendment, do NOT edit it in place. Instead, add a new `[ ]` task whose description explicitly says "supersedes T0NN: <reason>". The user sees both in the archive trail.

## Phase 4 — User gate

Show `amendment.md` to the user via `AskUserQuestion`:

- **Approve as drafted** → proceed to Phase 5
- **Revise** (free-text) → loop back to Phase 3 with their tweak
- **Abandon** → log `amend_run_end` with `status: abandoned`; exit

If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
- "Add superseding task (recommended)"
- "Re-open T0NN (flip `[x]` → `[ ]`) — work needs to be redone"
- "Leave T0NN alone — amendment doesn't actually contradict it"

Block until answered. Send a `PushNotification` if policy ≠ `off`.

## Phase 5 — Optional cross-LLM consult (only if non-obvious)

If `amendment.md`'s Risk section flagged any of these triggers, run a **bundled** consult:

- New external dependency
- Public API / wire format / schema change
- Cross-module impact in full mode
- Algorithm swap with materially different Big-O / memory
- Persistence change (migration, retention, indexes)

Spawn both in parallel:
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      prompt="MODE: amend\n\nExisting plan: <inline brief — 2-3 paragraphs from SPEC/PLAN summary>\nAmendment: <amendment.md body>\nKey concern: <the risk trigger>\n\nAsk: is the amendment sound? what's likely to break? what did I miss?")
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      prompt="<same body>")
```

When both return: apply **one reason it might be wrong** to each recommendation. Synthesize. Update `amendment.md` with a `## Consult outcome` section.

If neither consult trigger fires, skip this phase entirely — the user already approved in Phase 4.

## Phase 6 — Propagate edits

Now apply the amendment to the actual artifacts. Use `Edit` (not `Write`) so diffs stay surgical and reviewable.

### Full mode
1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
3. **TASKS.md**:
   - Append new tasks with fresh IDs in the appropriate phase block.
   - Edit modified `[ ]` tasks in place.
   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.

### Light mode
1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.

### Both modes
After every file edit, run:
```bash
diff -u <(git show HEAD:$BASE/<file> 2>/dev/null || echo) $BASE/<file> > $BASE/archive/$RUN/<file>.diff
```
(If not under git, snapshot the pre-edit content into `$BASE/archive/$RUN/before/<file>` before editing — Read first, copy via Write.)

## Phase 7 — Validate consistency

Run a self-check. Read each amended file fresh and verify:

- Every task referenced in PLAN.md exists in TASKS.md (and vice versa for non-implicit refs).
- Every file path in TASKS.md "files touched" appears in SPEC.md.
- No `[x]` task was changed without an explicit user-approved supersede.
- No duplicate task IDs.
- For light mode: every file in FIX.md "Files to change" exists or has a clear creation directive.

If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").

## Phase 8 — Finalize

1. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
     "$(printf '{"status":"applied","mode":"%s","tasks_added":%d,"tasks_modified":%d,"tasks_removed":%d,"tasks_superseded":%d,"consulted":%s}' \
        "$MODE" "$N_ADDED" "$N_MOD" "$N_REM" "$N_SUP" "$CONSULTED")"
   ```
2. Push-notify (if policy ≠ `off`): "Amendment applied to `<slug>`. <N> tasks added, <M> modified, <K> removed, <S> superseded."
3. Brief summary to user (3-5 sentences): what changed, what's next.
4. Recommend next step:
   - **full mode with new/modified `[ ]` tasks** → `/z-implement-next` or `/z-implement-all`
   - **light mode** → `/z-plan-light` won't re-run; if the amendment is large enough to warrant re-implementation, suggest the user explicitly trigger that.

## Hard rules

- **Never delete or silently mutate a `[x]` task.** Supersede instead.
- **Never reuse a task ID.** New tasks always get fresh IDs.
- **Never rewrite an artifact wholesale with `Write`** when surgical `Edit` will do. Preserve byte-for-byte content outside the amendment scope.
- **Never skip Phase 4 (user gate).** The user always sees the impact analysis before edits land.
- **Cross-LLM consult only when triggered** — amendments are surgical; full consult is overkill for "rename this field".
- **If the amendment grows past ~30% of the plan** (e.g. >5 new tasks, or the core premise of SPEC.md changes), STOP and recommend `/z-plan` from scratch instead — at that point you're not amending, you're replanning.
- **No emojis** anywhere in artifacts.
