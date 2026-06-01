---
description: Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff.
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-implement-next`** pipeline.

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 0 — Lock check + Discover plan slug

### Phase 0.1 — Global cross-tool lock check

Before doing any work, check for concurrent follow-up consumer activity in this repo:

```bash
SINK_LOCK="$HOME/.z-harness/.followup-vs-implement.lock"
mkdir -p "$(dirname "$SINK_LOCK")"
# Try-acquire with timeout=5s (non-blocking check first, then brief wait)
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)/index.view.json"
if [ -f "$PROJECT_SINK" ]; then
  RUNNING_COUNT="$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    entries_obj = data.get('entries', {})
    entries = list(entries_obj.values())
    running = [e for e in entries if e.get('status') == 'running']
    print(len(running))
except (json.JSONDecodeError, OSError, KeyError, AttributeError):
    print(0)
" "$PROJECT_SINK" 2>/dev/null || echo 0)"
  if [ "${RUNNING_COUNT:-0}" -gt 0 ]; then
    echo "halt: follow-up consumer is active ($RUNNING_COUNT running entry/entries in project sink)" >&2
    echo "Run /z-followup-status to see what is running. Wait for it to complete or dismiss before implementing." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" implement_halted_followup_running \
      "$(printf '{"running_count":%d,"sink_path":"%s"}' "$RUNNING_COUNT" "$PROJECT_SINK")" 2>/dev/null || true
    exit 1
  fi
fi
```

If there are running follow-up consumer entries, **halt** — do not proceed. Tell the user to check `/z-followup-status` before retrying.

### Phase 0.2 — Discover plan slug

Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to operate on:

1. Enumerate candidates:
   - List immediate subdirs of `z-harness/` that contain a `TASKS.md`.
   - Also check for legacy flat layout: a `TASKS.md` directly under `z-harness/` (no slug).
2. Choose:
   - **One candidate** → use it. If slug-namespaced, `export Z_HARNESS_SLUG=<slug>`. If legacy flat, leave `Z_HARNESS_SLUG` unset.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
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
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["id"] = sys.argv[2]; v["session_id"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<task-id>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
   ```

6. **Kernel path resolution (once per invocation, immediately after task_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   Resolve the kernel path exactly once here. When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every behavioral-agent dispatch in this run (implementer, reviewer). Omit the line entirely when `KERNEL_PATH` is empty — the agent's static fallback handles self-resolution in that case. Do NOT inject kernel content — inject the path string only.

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

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The implementer subagent performs all code edits; drivers that skip it must warn the user that task implementation has been bypassed. -->
```
Agent(
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to $Z_HARNESS_PLAN_DIR>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. Spawn the reviewer with the diff, not just file contents:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The reviewer is the correctness gate; drivers that skip it must warn the user that Codex review has been bypassed. -->
```
Agent(
  subagent_type="reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

Apply findings that hold up. Push back on those that don't and document the pushback.

## Phase 3.5 — Parse FOLLOWUPS block and route to sink

After the reviewer returns, parse the `**FOLLOWUPS:**` block from `$RETURN` and route each entry to the follow-up sink:

```bash
FOLLOWUPS_JSON="$(printf '%s' "$RETURN" | python3 scripts/parse-followups-block.py 2>/dev/null || echo '[]')"
FOLLOWUP_COUNT="$(printf '%s' "$FOLLOWUPS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"

if [ "${FOLLOWUP_COUNT:-0}" -gt 0 ]; then
  printf '%s' "$FOLLOWUPS_JSON" | python3 -c "
import json, subprocess, sys

entries = json.load(sys.stdin)
task_id = sys.argv[1]
source_artifact = sys.argv[2]
script = sys.argv[3]

for i, e in enumerate(entries):
    cited = ','.join(e.get('cited_paths', []))
    args = [
        'bash', script,
        '--sink=project',
        f'--priority={e[\"priority\"]}',
        f'--name={e[\"name\"]}',
        f'--recommended-command={e[\"recommended_command\"]}',
        f'--source-artifact={source_artifact}',
        f'--cited-paths={cited}',
    ]
    if e.get('auto_close_eligible'):
        args.append('--auto-close-eligible')
    if e.get('recommended_command_safe_to_retry'):
        args.append('--safe-to-retry')
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 3):  # 3 = dedup-skip (ok)
        print(f'warn: sink-add.sh exit {result.returncode} for entry {i}: {result.stderr[:200]}', file=sys.stderr)
" "$TASK_ID" "$BASE/archive/tasks/$TASK_ID/diff.patch" "scripts/sink-add.sh" 2>/dev/null || true
fi
```

Per-entry errors are logged + skipped. This step never blocks the reviewer return path. If `scripts/sink-add.sh` is not yet present (deps not implemented), this step is silently skipped.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

### Defer-to-sink branch

If the implementer's return flags an **out-of-current-SPEC discovery** (a finding that is real but out of scope for this task), consult the resolver before editing SPEC.md inline:

```bash
RESOLVED="$(python3 scripts/config.py resolve-question workflow.spec_retro_discovery 2>/dev/null)"
RESOLVE_EXIT=$?
RESULT="$(printf '%s' "$RESOLVED" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result","ask"))' 2>/dev/null || echo ask)"
```

- **`result == "defer-to-sink"`**: do NOT edit SPEC.md mid-run. Instead, call `scripts/sink-add.sh` to park the finding as a P2 follow-up:

  ```bash
  bash scripts/sink-add.sh \
    --sink=project \
    --priority=P2 \
    --name='<short title from discovery>' \
    --recommended-command='/z-do "amend SPEC.md: <discovery summary>"' \
    --source-artifact="$BASE/archive/tasks/<task-id>/diff.patch" \
    --cited-paths='<affected file paths, comma-separated>' \
    --prompt-body='<implementer discovery text verbatim>'
  ```

  Then log the deferral event and continue to Phase 5 without modifying SPEC.md:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "tasks/<task-id>" followup_deferred_from_resolver \
    "$(printf '{"question_id":"workflow.spec_retro_discovery","task":"<task-id>","summary":"<one-line>"}' )"
  ```

  If `sink-add.sh` exits non-zero, surface the error to the user and fall back to asking interactively — the discovery must not be silently dropped.

- **`result == "ask"` (or resolver error)**: present the discovery to the user with `AskUserQuestion`. If user confirms it needs a spec fix, update `$BASE/SPEC.md` now. If user says it's deferred, call `sink-add.sh` manually.

## Phase 5 — Mark done + notify

1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
4. Brief user summary: what changed, what the reviewer flagged, what's next.

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

## Decision emission (standing instruction)

After **any** `AskUserQuestion` resolves, emit a normalized decision event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-decision.sh" \
  "$RUN" "<question_id>" "<chosen_label>" \
  --options '["<opt1>","<opt2>",...]' \
  [--tentative "<recommended_option>"]
```

- `<question_id>` — stable kebab-case identifier for this decision point (e.g. `workflow.implement_all_proceed`, `workflow.slug_confirm`).
- `<chosen_label>` — the option label the user selected, verbatim.
- `--options` — full list of offered option labels as a JSON array.
- `--tentative` — the orchestrator's recommended option label; omit when the orchestrator had no recommendation.

Emission is gated by `Z_HARNESS_AXIOM_EXTRACT` (default on); when set to `"0"`, the script exits silently — no guard is needed here. Do **not** modify existing structured gate events (`cost_gate_decision`, `critique_failure_decision`, `map_collision_decision`, `shared_concerns_ack_override`); those are normalized separately by the extractor. This emission **records signal only** — it never approves, overrides, or influences any decision (proposes-only invariant).

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 implementer; Phase 3 reviewer |
| `ask_user` | yes | Phase 0 slug selection (multiple candidates) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
