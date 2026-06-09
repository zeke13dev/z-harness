# /z-implement-next

You are running the **z-harness `/z-implement-next`** pipeline.

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 0 — Lock check + Discover plan slug

### Phase 0.0 — Active-plan registration + cross-session overlap scan

Register this run in the shared active-plan registry, seed its file scope, and surface overlap
with any concurrent session. This is advisory by design (registry invariant 1: lockless is safe
ONLY because overlap is advisory) except under `Z_HARNESS_STRICT_OVERLAP`, which adds a single
hard gate. This command never mutates the base or migrates anything (registry invariant 8); it
only register/heartbeat/deregisters its own record (single-writer, invariant 6).

**ORDERING (mandatory).** This phase needs `$BASE` bound (Phase 0.2 slug discovery) and must not
create a record before any structural-validation halt. Therefore run this phase **after Phase 0.2
(slug discovery, which exports `$Z_HARNESS_SLUG` and sets `$BASE`) and BEFORE Phase 0.1
(follow-up lock check)** — so that if Phase 0.1 halts, a record already exists and can be
deregistered. Phase 0.2 must run first even though it appears later in this document; the
execution order is 0.2 → 0.0 → 0.1, mirroring z-implement-all where Setup slug-discovery
runs before Phase 0.0 registration.

**Bind the run id and session id (the two values this phase introduces).** `$Z_HARNESS_SLUG`
and `$BASE` are already bound by Phase 0.2 above; only `RUN` and the session id are
established here:

```bash
# Run id — canonical variable for this command. Every register / heartbeat / overlaps /
# deregister call in this file uses $RUN (never any other variable).
RUN="$(date -u +%Y%m%dT%H%M%SZ)-implement-next"

# Session id (same value Phase 1 stamps onto task_start).
export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"

# Sanity-guard: $BASE must be a real path here. If $BASE is unset, Phase 0.2 did not run yet
# — STOP; this phase is mis-ordered.
: "${BASE:?Phase 0.0 ran before Phase 0.2 bound \$BASE — fix ordering}"
```

**1. Register the run.** Graduated failure policy (registry SPEC): a silent register failure
defeats the whole mechanism, so NEVER silent-continue. Spell out every exit code:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
  --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-implement-next --phase implement \
  --session "$Z_HARNESS_SESSION_ID"
REG_RC=$?
```

- `REG_RC == 0` → registered; a record now exists; proceed to step 2.
- `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event
  (the register subcommand does NOT self-log its own failure; it returns 3 loudly, so the
  orchestrator logs it here), then branch:
  - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* /
    *abort*.
    - **proceed without coordination** → continue WITHOUT a record. Skip step 2 (scope seed) and
      step 3 (overlap scan) entirely — there is no record to scope or scan against — and fall
      through to Phase 1. (No heartbeat/deregister later either; there is nothing to update.)
    - **abort** → because register FAILED there is **NO record**, so do **NOT** call deregister
      (deregistering a nonexistent record is a no-op at best and misleading at worst). Just
      push-notify and `exit 1`.
  - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination (as the interactive
    *proceed* branch above) and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1`, in which
    case **halt**: push-notify (this is the only register-failure hard stop) and `exit 1`. Again,
    do **NOT** deregister — register failed, so no record exists.
- **Any OTHER nonzero `REG_RC`** (not 0, not 3 — should not happen, but be defensive) → treat it
  exactly as `REG_RC == 3` (loud `registry_error`, same graduated proceed/abort policy, same
  "no record exists → no deregister" rule).

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
  "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the register-failure proceed/abort question via their native channel. Silent omission is forbidden. -->

**2. Seed scope (best-effort, non-fatal).** Dispatch the `scope-extractor` (Haiku) subagent with
`repo_root` + `base` to produce a scope JSON array, write it to a temp file, and feed it to
`update-scope`. Failure here is non-fatal — overlap detection just runs with an empty/own-record
scope. The `update-scope` subcommand returns 0 by design and **self-logs** a `registry_error`
event (op:`update-scope`) internally on any failure, so the orchestrator calls it best-effort
with `|| true` and does NOT add a misleading `|| log` (that would be dead code, since the
subcommand returns 0 by design).

```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="scope-extractor",
  description="Scope for /z-implement-next overlap scan",
  prompt="repo_root: <repo root abs path>\nbase: $BASE"
)
```

Write the returned JSON array to `"$(mktemp -t z-scope.XXXXXX.json)"`, then:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope \
  --run-id "$RUN" --scope-json "$SCOPE_JSON" || true   # CLI self-logs registry_error on failure
```

**3. Overlap scan (graduated advisory).** Add `--strict` when `Z_HARNESS_STRICT_OVERLAP=1`.

```bash
OVL_ARGS=(--run-id "$RUN")
[ "${Z_HARNESS_STRICT_OVERLAP:-}" = "1" ] && OVL_ARGS+=(--strict)
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" overlaps "${OVL_ARGS[@]}"
OVL_RC=$?
```

Handle the exit code (the registry self-emits `active_plan_scan_complete` /
`scope_overlap_detected`, so absence of overlap is observable without an extra event here).
Spell out every code:

- `OVL_RC == 0` (no overlap) → proceed silently (the registry already self-emitted
  `active_plan_scan_complete`).
- `OVL_RC == 10` (advisory overlap) → present the overlapping peers (each peer's `slug`,
  `branch`, `current_task`, `host`, and the shared paths — re-run with `--json` to render them)
  via `AskUserQuestion`: **proceed** / **wait** (re-scan after the peer finishes) / **abort**.
  Under `Z_HARNESS_NO_ASK` → proceed and log (advisory is non-blocking unattended).
  On **abort** → a record EXISTS; run:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # push-notify + exit 1
  ```
- `OVL_RC == 20` (blocking overlap — only under strict mode AND an `explicit`×`explicit` exact
  path match with a live peer) → **HALT**: a record EXISTS; push-notify (hard pause, fires
  regardless of notify level), then run:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # exit 1 without dispatching any task
  ```
  This is the one hard gate (registry invariant 1 permits it only under strict mode).
- **Any OTHER nonzero `OVL_RC` (including `4` — overlaps could not resolve the registry)** → this
  is NOT a hard block and NOT a silent "no overlap". Log a `registry_error` event (op:`overlaps`)
  and **PROCEED** (the scan was inconclusive; overlap is advisory, so an inconclusive scan
  degrades to "ran without coordination" rather than halting):
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
    "$(printf '{"op":"overlaps","run_id":"%s","rc":%d}' "$RUN" "$OVL_RC")"
  ```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the overlap proceed/wait/abort question via their native channel. Silent omission is forbidden. -->

### FINALIZE_STATUS / deregister rule (single source of truth)

One rule governs the record's lifecycle for the entire run:

> **On any abort/halt that ENDS the run AND occurs after a record exists (i.e. after a `REG_RC == 0`
> register), set `FINALIZE_STATUS=aborted` and `deregister --status aborted` before exiting. On a
> normal completion (Phase 5), deregister with the default `complete`. On register failure (no
> record), do NOT deregister.**

Concretely, the run-ending halt paths that MUST set `FINALIZE_STATUS=aborted` and deregister
(each is reached only after `REG_RC == 0`, so a record exists):

- Phase 0.0 overlap abort (`OVL_RC == 10` → abort) and overlap block (`OVL_RC == 20`) — handled inline above.
- Phase 0.1 follow-up-running halt — handled inline below.
- Any other run-ending halt after registration (implementer returns `unable_to_complete` etc. and
  the orchestrator decides to stop entirely) — set `FINALIZE_STATUS=aborted` + deregister.

Paths that must NOT deregister:

- **Register-failure abort/halt (`REG_RC == 3` or other nonzero)** — no record was ever written,
  so there is nothing to deregister; just `exit 1`.

### Phase 0.1 — Global cross-tool lock check

After Phase 0.0 registers the run (or skips on register failure), check for concurrent follow-up
consumer activity in this repo:

```bash
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
    # Run-ending halt after a record exists → FINALIZE_STATUS=aborted + deregister (the
    # single FINALIZE_STATUS rule from Phase 0.0). If register failed earlier (no record),
    # deregister is a harmless no-op (the CLI self-logs nothing and returns 0). The CLI
    # self-logs any internal deregister failure, so this is best-effort `|| true`.
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status "$FINALIZE_STATUS" || true
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
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
   - **Zero candidates** → tell the user there's no plan; suggest `/z-plan`. Stop.
3. From here on, **`BASE`** refers to `$Z_HARNESS_PLAN_DIR` (or `z-harness` if legacy). Paths below use `$BASE`.

## Phase 1 — Load context

1. Read `$BASE/TASKS.md`. Find the first task with status `[ ]`.
2. **Do NOT pre-extract SPEC/PLAN slices in main thread.** Pass `$BASE` to the implementer; the implementer subagent reads `$BASE/SPEC.md` and `$BASE/PLAN.md` itself with its Read tool. Saves main-thread context.
3. (Skip — implementer reads the files it touches.)
4. Create task archive dir: `mkdir -p $BASE/archive/tasks/<task-id>`
5. **Version stamp + task_start:** (`Z_HARNESS_SESSION_ID` was already exported in Phase 0.0; the
   `:-` default below leaves it alone if set.)
   ```bash
   export Z_HARNESS_SESSION_ID="${Z_HARNESS_SESSION_ID:-$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)}"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["id"] = sys.argv[2]; v["session_id"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<task-id>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
   ```

   Write `session-status.json` — status `"running"`, `current_task: "<task-id>"`,
   `tasks_done: 0`, `tasks_total: 1`. Use the atomic write pattern from the
   "Session status file" section above.

6. **Kernel path resolution (once per invocation, immediately after task_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   > [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).

If TASKS.md is missing or has no pending tasks, tell the user and stop.

## Session status file (session-status.json)

Write `$BASE/session-status.json` at each state transition so the Hermes
orchestrator can monitor this session. Use atomic writes (temp + rename).

The file is a best-effort log — if the write fails, log a warning and continue.

**Write helper (use at each state transition below):**

```bash
python3 -c "
import json, os, datetime
status = {
    'status': '<running|halted|done|paused>',
    'halt_reason': '<reason or null>',
    'halt_description': '<free-text or null>',
    'tasks_done': <count>,
    'tasks_total': 1,
    'current_task': '<task-id or null>',
    'updated_at': datetime.datetime.utcnow().isoformat() + 'Z'
}
path = os.path.join(os.environ.get('BASE', '.'), 'session-status.json')
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(status, f, indent=2)
os.rename(tmp, path)
" 2>/dev/null || echo "WARNING: session-status.json write failed" >&2
```

**Write sites:**
- **Task_start event**: write status `"running"`, `tasks_done: 0`
- **Task halted** (any halt reason): write status `"halted"` with halt_reason
- **Task done**: write status `"done"`, `tasks_done: 1`
- **Compaction pause**: write status `"paused"`

## Phase 2 — Implement

**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.

**Heartbeat the registry at task-dispatch boundary** (best-effort, non-fatal — never block dispatch
on a registry error). The `heartbeat` subcommand returns 0 by design and **self-logs** a
`registry_error` event (op:`heartbeat`) internally on any failure, so call it with `|| true` and
do NOT add a misleading `|| log` (that would be dead code since the subcommand returns 0 by
design):

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat \
  --run-id "$RUN" --phase implement --current-task "<task-id>" || true   # CLI self-logs registry_error on failure
```

### Phase 2.5 — Per-task lease lifecycle

After the heartbeat and before implementer dispatch, claim the task's explicit-confidence paths,
resolve any concessions via `wait-for` or an interactive menu, then dispatch the implementer.
Release the lease on clean success; on halt mid-task, rely on `deregister`/`reap` to clean up.

**Claim the task's explicit-confidence paths (conservative — explicit only, per SPEC D3).**
`CLAIM` is the `explicit`-confidence entries from the scope-extractor's task-level output
(same extractor invoked in Phase 0.0 but scoped to this task via `task_id`). If the
scope-extractor is unavailable or returns no explicit paths, `CLAIM` is empty — proceed
directly to implementer dispatch (no-op claim).

```bash
# CLAIM = explicit-confidence paths from the task block's Files: list + scope-extractor(task=<id>)
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" claim \
  --run-id "$RUN" --paths "$CLAIM"   # comma-separated repo-relative paths
CLAIM_OUT="$?"   # claim exits 0 always; parse stdout JSON for conceded list
# stdout: {"claimed":[...], "conceded":[{"path":"...","holder_run_id":"..."}]}
```

**Handle each `conceded` entry (senior peer holds the path; eldest-senior = lowest run_id).**
When `conceded` is non-empty, pick the eldest senior (`holder_run_id` from the entry — this
is the lowest run_id among all seniors on that path as returned by `claim`):

**If `Z_HARNESS_AUTO_WAIT=1` (default):**

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" wait-for \
  --run-id "$RUN" --on "$HOLDER_RUN_ID" --paths "$CONCEDED_PATH"
WAIT_RC=$?
```

- `WAIT_RC == 0` (peer cleared / nothing-to-wait-on) → **re-`claim` the freed path** — this
  is a GENUINE acquisition, not a dedup no-op, because the loser never persisted the conceded
  path (claim persists only the won set per SPEC F-claim-wonset). Re-run `claim` with the
  conceded path(s) and add any newly-won paths to `CLAIM`. Then continue to implementer dispatch.
- `WAIT_RC == 10` (wait timeout — LOUD, per SPEC F1):
  <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this timeout decision (proceed/abort) via their native channel. Silent omission is forbidden. -->
  - **Interactive (not `Z_HARNESS_NO_ASK`):** present `AskUserQuestion`: **proceed anyway** /
    **abort task**. If proceed → continue to dispatch (the contended path is not leased; the
    post-dispatch write-set validation in Phase 2.5 will catch any actual collision). If abort →
    flip `[~]` back to `[ ]`, log `task_halt {reason:"wait_timeout_abort"}`, apply the
    FINALIZE_STATUS rule (deregister with `aborted`), and exit. *(Intentional divergence from
    /z-implement-all: a single-task run has no outer loop, so aborting the task aborts the run
    and deregisters; the batch command keeps the run registered to continue other tasks.)*
  - **Unattended (`Z_HARNESS_NO_ASK`) — ABORT TASK (MAJOR-4).** A held-path `wait-for` exit 10
    in unattended mode MUST abort the current task. It MUST NOT silently proceed (that recreates
    the collision) and MUST NOT automatically re-enter `wait-for` on the same blocker (a re-wait
    is only legitimate after the user re-queues the task). Emit a loud log, flip `[~]` back to
    `[ ]`, apply the FINALIZE_STATUS rule (deregister with `aborted`), and exit:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_halt \
      "$(printf '{"id":"%s","reason":"wait_timeout_unattended","holder_run_id":"%s","path":"%s"}' \
         "<task-id>" "$HOLDER_RUN_ID" "$CONCEDED_PATH")"
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status "$FINALIZE_STATUS" || true
    # flip [~] → [ ]; exit 1
    ```
    Cross-link: see Phase 0.0 SPEC F1 — this is the same loud-abort-on-timeout invariant.
- `WAIT_RC == 130` (SIGINT during park) → abort the task (same as unattended exit 10: apply the
  FINALIZE_STATUS rule, deregister with `aborted`, propagate the SIGINT to the outer shell).

**If `Z_HARNESS_AUTO_WAIT=0` (interactive wait mode):**

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the conceded-path proceed/wait/abort question via their native channel. Silent omission is forbidden. -->
Present `AskUserQuestion`: **proceed anyway** / **wait** / **abort task**.
- **proceed** → continue to implementer dispatch (the path is not leased; the F5 write-set
  validation below applies as a backstop).
- **wait** → call `wait-for --run-id $RUN --on $HOLDER_RUN_ID --paths $CONCEDED_PATH` (same
  `WAIT_RC` handling as the auto-wait path above).
- **abort task** → flip `[~]` back to `[ ]`, log `task_halt {reason:"user_aborted_lease"}`,
  apply the FINALIZE_STATUS rule (deregister with `aborted`), and exit. *(Intentional
  divergence from /z-implement-all: same reason — aborting this single-task run means the
  run is done, so deregister; the batch command's outer loop continues instead.)*

**Dispatch implementer** (Phase 2 implementer dispatch below) with the claimed paths in scope.

**Lease release and halt semantics.**

- **On clean task success (before marking `[x]` in Phase 5):** release the lease:
  ```bash
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" release \
    --run-id "$RUN" --paths "$CLAIM"   # CLI self-logs registry_error on failure; exits 0 always
  ```
- **On review-fail with "patch manually" (user takes over within the same invocation):** KEEP the
  existing lease. Do NOT release until the user signals completion and Phase 5 runs. If the user
  subsequently asks the orchestrator to re-dispatch the implementer (e.g. after patching), expand
  `CLAIM` with any newly-touched paths before re-dispatch. Release only on clean final success.
- **On halt mid-task** (`unable_to_complete` or other terminal halt after implementer dispatch):
  do NOT release. Rely on `deregister` (from the FINALIZE_STATUS rule) or `reap` (stale-timeout)
  to clean up `held_paths`. A partially-applied edit must not release the lease before the task
  resolves.

  When the task halts for ANY reason (wait timeout, spec_problem, decision_needed,
  needs_clarification, unable_to_complete), write `session-status.json` with
  status `"halted"`, the halt reason, and the halt description before surfacing
  the question to the user. Use the atomic write pattern from the
  "Session status file" section above.
- **On re-invocation** (user runs `/z-implement-next` again for the same task after a prior attempt
  ended without `[x]`): the previous run's lease was cleaned up by its `deregister`; the new
  invocation runs a fresh `claim` in Phase 2.5 as usual.

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
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to $Z_HARNESS_PLAN_DIR>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

**Parse the implementer's return.** Handle every STATUS before proceeding to Phase 3:

- `STATUS: ok` → continue to Phase 3 (review).
- `STATUS: unable_to_complete` → a record EXISTS (registered in Phase 0.0), so apply the
  FINALIZE_STATUS rule: deregister with `aborted`, push-notify with the reason, and stop:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status "$FINALIZE_STATUS" || true   # CLI self-logs registry_error on failure
  # push-notify + exit 1
  ```
- `STATUS: needs_clarification` / `STATUS: spec_problem` / `STATUS: decision_needed` → halt,
  push-notify, escalate to the user. If the orchestrator decides to stop entirely (not re-spawn),
  apply the FINALIZE_STATUS rule (deregister with `aborted`) before exit. If the user resolves
  the issue and the orchestrator re-spawns the implementer, keep the existing record alive (no
  deregister); deregister only on the final terminal exit.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. Spawn the reviewer with the diff, not just file contents:

```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

Apply findings that hold up. Push back on those that don't and document the pushback.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

## Phase 5 — Mark done + notify

1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. **Release the lease** (best-effort, non-fatal) before marking `[x]`. This unblocks any junior
   peer waiting on a path this task held. The `release` subcommand returns 0 by design and
   self-logs a `registry_error` on internal failure. If `CLAIM` is empty (no paths were claimed),
   this is a harmless no-op.
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" release \
     --run-id "$RUN" --paths "$CLAIM" || true   # CLI self-logs registry_error on failure

   Write `session-status.json` — status `"done"`, `tasks_done: 1`,
   `tasks_total: 1`, `current_task: null`. Use the atomic write
   pattern from the "Session status file" section above.

   ```
4. **Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the single
   FINALIZE_STATUS rule (Phase 0.0): normal completion deregisters with `complete`. The
   `deregister` subcommand returns 0 by design and self-logs a `registry_error` on internal
   failure, so call it with `|| true` (not `|| log`). If register failed earlier (no record was
   ever written), this is a harmless no-op.
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
     --run-id "$RUN" --status "complete" || true   # CLI self-logs registry_error on failure
   ```
5. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
6. Brief user summary: what changed, what the reviewer flagged, what's next.

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.
