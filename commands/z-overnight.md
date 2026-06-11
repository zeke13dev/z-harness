---
description: Run a chain of z-harness workflows unattended overnight with halt-only user interaction. Chains existing sub-commands end-to-end, writes MORNING_REPORT.md, and push-notifies on halt or completion.
argument-hint: "<chain> [task-description] | preset:<name> [task-description] | resume <RUN_ID>"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are the **z-harness `/z-overnight`** orchestrator. Your job is to run a pipeline of z-harness sub-commands end-to-end with no interactive gates — AskUserQuestion calls that reach instrumented callsites are converted to halt events when `Z_HARNESS_NO_ASK=halt` is set. You do not implement, plan, or review code yourself — you delegate to sub-skills via the Skill tool.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Invocation forms

```
/z-overnight <chain> [task-description]
/z-overnight preset:<name> [task-description]
/z-overnight resume <RUN_ID>
```

- `<chain>` is comma- or arrow-separated sub-command names without the `/z-` prefix. Examples:
  - `plan,test,implement-all,review-all`
  - `plan → test → implement-all → review-all`
- Presets:
  - `full-build` = `plan,test,implement-all,review-all`
  - `research-build` = `research,plan,test,implement-all,review-all`
  - `quick-build` = `plan,implement-all`
- `resume <RUN_ID>` — re-enters at the first non-`complete` step of a prior run.

## Phase 0 — Parse arguments and validate

Parse `$ARGUMENTS` to determine the invocation form:

1. If `$ARGUMENTS` is empty or whitespace → emit a usage error, exit cleanly without acquiring any lock:
   ```
   Error: /z-overnight requires a chain, preset, or resume argument.
   Usage: /z-overnight <chain> [task-description]
          /z-overnight preset:<name> [task-description]
          /z-overnight resume <RUN_ID>
   ```

2. **Resume form:** if arguments start with `resume ` → extract `RESUME_RUN_ID` from the remainder; `TASK_DESCRIPTION=""`. Jump to Phase 2 (Resume) after Phase 1 setup.

3. **Preset form:** if arguments start with `preset:` → extract the preset name and optional task description:
   ```
   PRESET_NAME = second token (the part after "preset:")
   TASK_DESCRIPTION = remainder of $ARGUMENTS after the preset token
   ```
   Expand preset to chain string:
   - `full-build` → `plan,test,implement-all,review-all`
   - `research-build` → `research,plan,test,implement-all,review-all`
   - `quick-build` → `plan,implement-all`
   - Unknown preset → emit error, exit cleanly without acquiring any lock.

4. **Chain form:** first token is the chain string (comma/arrow-separated steps); everything after the first whitespace-delimited group is `TASK_DESCRIPTION`.

5. **Normalize chain:** replace all `→` and `->` with `,`; split on `,`; strip whitespace from each token. Store as `CHAIN_STEPS` array.

6. **Empty chain guard (M4):** if `CHAIN_STEPS` is empty after normalization → emit usage error, exit cleanly without acquiring any lock.

## Phase 1 — Setup (new run)

> Skip to Phase 2 for the resume form.

1. **Derive slug.** From `TASK_DESCRIPTION`, derive a 2-4 word kebab-case slug (e.g. "add rate limit middleware" → `add-rate-limit`). If `TASK_DESCRIPTION` is empty, use the chain as a stub (e.g. `overnight-full-build`).

2. **Resolve plan dir:**
   ```bash
   export Z_HARNESS_SLUG="<slug>"
   BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
   ```

3. **Preflight slug-collision check (SPEC C13).** Run BEFORE lock acquisition and BEFORE exporting `Z_HARNESS_NO_ASK`:
   ```bash
   # Compute comma-joined chain for the preflight script
   CHAIN_CSV="$(IFS=','; echo "${CHAIN_STEPS[*]}")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/overnight-preflight.sh" check-collisions \
     --chain "$CHAIN_CSV" \
     --base "$BASE"
   PREFLIGHT_EXIT=$?
   ```
   If `PREFLIGHT_EXIT != 0` → the preflight script already logged `slug_collision_halt` and emitted the remediation message. Exit cleanly here (do not acquire lock, do not set NO_ASK).

4. **Generate run ID and directories:**
   ```bash
   RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-overnight-${Z_HARNESS_SLUG}"
   export Z_HARNESS_OVERNIGHT_RUN_ID="$RUN_ID"
   mkdir -p "$BASE/archive/$RUN_ID"
   ```

5. **Acquire lock (SPEC C4).** The lock file is `$BASE/.overnight.lock` — a JSON file used for both concurrency enforcement and as the flock target for state writes. A separate flock file `$BASE/.overnight.flock` serializes the check-and-write sequence so two concurrent orchestrators cannot both observe an absent/stale lock and both take ownership:
   ```bash
   LOCK_FILE="$BASE/.overnight.lock"
   LOCK_FLOCK="$BASE/.overnight.flock"
   STALE_S="${Z_HARNESS_OVERNIGHT_LOCK_STALE_S:-7200}"
   NOW_TS="$(date -u +%s)"
   ```
   The entire parse-lock-state / decide-takeover-or-halt / write-new-lock-JSON sequence runs inside an exclusive flock on `$LOCK_FLOCK`:
   - If `$LOCK_FILE` exists:
     - Attempt to parse it as JSON. If parse fails → emit `overnight_lock_corrupt` event:
       ```bash
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_lock_corrupt \
         "$(printf '{"path":"%s","parse_error":"JSON parse failed"}' "$LOCK_FILE")"
       ```
       Hard-halt with message: "Delete `$BASE/.overnight.lock` manually after verifying no /z-overnight is in progress, then re-run." Exit nonzero.
     - Extract `last_heartbeat` from JSON. If `(NOW_TS - last_heartbeat) < STALE_S` → lock is live. Surface contention to user:
       <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the lock-contention question. -->
       Use `AskUserQuestion` to ask: "Another /z-overnight run appears to be in progress for `$Z_HARNESS_SLUG` (lock heartbeat age: `<age>` seconds, stale threshold: `$STALE_S`s). What would you like to do?" with options: `wait and retry` / `force-takeover` / `abort`. If user chooses `abort` → exit cleanly. If `force-takeover` → proceed to write lock below. If `wait and retry` → advise user to re-run /z-overnight after the active run ends; exit cleanly.
     - If lock is stale (`age >= STALE_S`) → allow takeover; log a warning.
   - Write lock file atomically using `flock` to serialize the check-and-write sequence (prevents two orchestrators from simultaneously observing no/stale lock and both taking ownership):
     ```bash
     LOCK_FLOCK="$BASE/.overnight.flock"
     LOCK_TMP="$LOCK_FILE.tmp.$$"
     (
       flock -x 9
       python3 -c "
import json, sys
obj = {
    'owner_run_id': sys.argv[1],
    'started_at': sys.argv[2],
    'last_heartbeat': int(sys.argv[3])
}
print(json.dumps(obj))
" "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$NOW_TS" > "$LOCK_TMP"
       mv "$LOCK_TMP" "$LOCK_FILE"
     ) 9>"$LOCK_FLOCK"
     ```

6. **Build the auto-decide allowlist (SPEC C7).** Merge defaults from `scripts/config.py` with the env override:
   ```bash
   # Default allowlist (hardcoded in scripts/config.py: OVERNIGHT_AUTODECIDE_QIDS_DEFAULT)
   # Env override (JSON string): Z_HARNESS_OVERNIGHT_AUTODECIDE
   AUTODECIDE_DEFAULT='{"workflow.slug_confirm":"recommend_derived","workflow.audit_to_amend":"amend"}'
   AUTODECIDE_ENV="${Z_HARNESS_OVERNIGHT_AUTODECIDE:-{}}"
   AUTODECIDE_EFFECTIVE="$(python3 -c "
import json, sys
defaults = json.loads(sys.argv[1])
overrides = json.loads(sys.argv[2])
merged = {**defaults, **overrides}
print(json.dumps(merged))
" "$AUTODECIDE_DEFAULT" "$AUTODECIDE_ENV")"
   export Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE="$AUTODECIDE_EFFECTIVE"
   ```

7. **Export env vars:**
   ```bash
   export Z_HARNESS_SLUG="<slug>"
   export Z_HARNESS_OVERNIGHT_RUN_ID="$RUN_ID"
   # Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE already exported above
   # DO NOT export Z_HARNESS_NO_ASK here — only set around Skill calls
   ```

8. **Capture git HEAD:**
   ```bash
   HEAD_SHA_AT_START="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
   ```

9. **Initialize `overnight-state.json` (SPEC C5 / C9).** Write atomically to `$BASE/archive/$RUN_ID/overnight-state.json`:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh" 2>/dev/null || echo '{}')"
   Z_HARNESS_VERSION="$(printf '%s' "$VERSION_BLOB" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("commit","unknown"))' 2>/dev/null || echo "unknown")"
   ```
   Build initial state:
   ```json
   {
     "chain": ["<step1>", "<step2>", ...],
     "preset_used": "<preset-name or null>",
     "started_at": "<ISO-UTC>",
     "ended_at": null,
     "status": "running",
     "head_sha_at_start": "<HEAD_SHA_AT_START>",
     "z_harness_version": "<Z_HARNESS_VERSION>",
     "git_diff_stat_at_end": null,
     "step_runs": [
       {
         "step": "<step-name>",
         "position": <index>,
         "run_id": null,
         "status": "queued",
         "head_sha_before": null,
         "head_sha_after": null,
         "started_at": null,
         "ended_at": null,
         "wall_ms": null,
         "terminal_event_kind": null,
         "artifact_paths": [],
         "exit_event": null,
         "error_event": null
       }
       ...
     ]
   }
   ```
   Write via flock-guarded tmp+rename using `$LOCK_FILE` as the flock target:
   ```bash
   STATE_FILE="$BASE/archive/$RUN_ID/overnight-state.json"
   STATE_TMP="${STATE_FILE}.tmp.$$"
   # Write STATE_TMP with the JSON above, then:
   (flock -x 200; mv "$STATE_TMP" "$STATE_FILE") 200>"$LOCK_FILE"
   ```

10. **Log `overnight_start`:**
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_start \
      "$(python3 -c "
import json, sys
print(json.dumps({
    'chain': sys.argv[1].split(','),
    'preset_used': sys.argv[2] if sys.argv[2] != 'null' else None,
    'slug': sys.argv[3],
    'head_sha_at_start': sys.argv[4],
}))
" "$CHAIN_CSV" "${PRESET_NAME:-null}" "$Z_HARNESS_SLUG" "$HEAD_SHA_AT_START")"
    ```

## Phase 2 — Resume setup

> Only entered when invocation form is `resume <RUN_ID>`.

1. **Locate state file.** Resolve `BASE` by searching for the run directory:
   ```bash
   # Attempt to find the run archive under canonical and legacy layout
   BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path \
     "$(printf '%s' "$RESUME_RUN_ID" | sed 's/^[0-9TZ-]*overnight-//')")"
   STATE_FILE="$BASE/archive/$RESUME_RUN_ID/overnight-state.json"
   ```
   If `$STATE_FILE` does not exist → emit error message and exit nonzero.

2. **Parse state file.** If JSON parse fails → emit `state_corrupt` event:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RESUME_RUN_ID" state_corrupt \
     "$(printf '{"path":"%s","error":"JSON parse failed"}' "$STATE_FILE")"
   ```
   Exit nonzero with remediation: "Delete `$STATE_FILE` and restart with a new /z-overnight run."

3. **Check if already complete (M4 edge case).** If top-level `status == "complete"`:
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this question. -->
   Use `AskUserQuestion` to inform the user: "This overnight run (`$RESUME_RUN_ID`) is already complete. No-op — nothing to resume." with option `ok`. Exit cleanly after user acknowledges.

4. **Compute resume cursor.** `CURSOR = index of first step_run where status != "complete"`. Extract `CHAIN_STEPS` and `PRESET_NAME` from the state file.

5. **HEAD SHA validation (SPEC C8).** Find the last completed step (highest index with `status == "complete"`). If one exists and has `head_sha_after`:
   ```bash
   EXPECTED_SHA="<last-completed-step.head_sha_after>"
   CURRENT_SHA="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
   ```
   - If `EXPECTED_SHA != CURRENT_SHA` → emit `head_sha_mismatch_at_resume` event:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RESUME_RUN_ID" head_sha_mismatch_at_resume \
       "$(printf '{"expected":"%s","actual":"%s","last_step":"%s"}' \
          "$EXPECTED_SHA" "$CURRENT_SHA" "<last-completed-step-name>")"
     ```
     Surface a **CRITICAL** warning to the user (print to stdout before continuing): "WARNING: Git HEAD has changed since the last completed step. Expected `$EXPECTED_SHA`, got `$CURRENT_SHA`. Proceeding anyway — verify this is intentional." Proceed.

6. **Re-export env vars:**
   ```bash
   export Z_HARNESS_SLUG="$(python3 -c 'import json; d=json.load(open("$STATE_FILE")); ...')"
   RUN_ID="$RESUME_RUN_ID"
   export Z_HARNESS_OVERNIGHT_RUN_ID="$RUN_ID"
   LOCK_FILE="$BASE/.overnight.lock"
   ```
   Rebuild `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` using the same merge logic as Phase 1 step 6.

7. **Acquire lock** — same algorithm as Phase 1 step 5.

8. **Update state: top-level `status = "running"`, refresh `started_at` if previously null.** Write atomically via flock.

## Phase 3 — Per-step loop

For each position `CURSOR` through `len(CHAIN_STEPS)-1`:

```
STEP_NAME = CHAIN_STEPS[CURSOR]
```

### Step 3.1 — Skip if already complete

Read `overnight-state.json`; if `step_runs[CURSOR].status == "complete"` → skip to next CURSOR. (This is the resume idempotency path.)

### Step 3.2 — Update step status to `running`

```bash
HEAD_SHA_BEFORE="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
STEP_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STEP_STARTED_MS="$(date -u +%s%3N 2>/dev/null || python3 -c 'import time; print(int(time.time()*1000))')"
```
Write state: `step_runs[CURSOR].status = "running"`, `.head_sha_before = HEAD_SHA_BEFORE`, `.started_at = STEP_STARTED_AT`. Flock-guarded tmp+rename.

### Step 3.3 — Log `overnight_step_start`

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_step_start \
  "$(printf '{"step":"%s","position":%d,"total_steps":%d}' \
     "$STEP_NAME" "$CURSOR" "${#CHAIN_STEPS[@]}")"
```

### Step 3.4 — Heartbeat refresh

Update `last_heartbeat` in `$LOCK_FILE`:
```bash
NOW_TS="$(date -u +%s)"
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lock = json.load(f)
lock['last_heartbeat'] = int(sys.argv[2])
import tempfile, os
tmp = sys.argv[1] + '.hb.tmp'
with open(tmp, 'w') as f:
    json.dump(lock, f)
os.rename(tmp, sys.argv[1])
" "$LOCK_FILE" "$NOW_TS" 2>/dev/null || true
```

### Step 3.5 — Snapshot existing archive dirs (SPEC C14)

```bash
ARCHIVE_DIR="$BASE/archive"
# Snapshot before Skill call — list only directories, exclude dirs whose basename matches *-overnight-*
ARCHIVE_DIRS_BEFORE="$(find "$ARCHIVE_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
  | while IFS= read -r d; do b="$(basename "$d")"; case "$b" in *-overnight-*) ;; *) printf '%s\n' "$b" ;; esac; done \
  | sort || true)"
```

### Step 3.6 — Invoke sub-skill via Skill tool (NO_ASK carve-out, SPEC C4)

**IMPORTANT — NO_ASK carve-out timing:** Set `Z_HARNESS_NO_ASK=halt` ONLY immediately before the Skill call, and `unset Z_HARNESS_NO_ASK` immediately after it returns or raises. The parent /z-overnight skill's own prompts (above and below this section) run with NO_ASK unset.

Map `STEP_NAME` to the skill ID **before** exporting `Z_HARNESS_NO_ASK`. Unknown step names must be handled here so that the error path never runs with NO_ASK set:
- `plan` → `SKILL_ID="z-harness:z-plan"`, `SKILL_ARGS=TASK_DESCRIPTION`
- `test` → `SKILL_ID="z-harness:z-test"`, `SKILL_ARGS=TASK_DESCRIPTION`
- `implement-all` → `SKILL_ID="z-harness:z-implement-all"`, `SKILL_ARGS=""`
- `review-all` → `SKILL_ID="z-harness:z-review-all"`, `SKILL_ARGS=""`
- `research` → `SKILL_ID="z-harness:z-research"`, `SKILL_ARGS=TASK_DESCRIPTION`
- Unknown step name → (Z_HARNESS_NO_ASK is still unset here) set step status to `error`, `error_event = {kind: "skill_tool_failure", message: "Unknown step name: <STEP_NAME>"}`, jump to terminal handling (Step 3.10).

```bash
export Z_HARNESS_NO_ASK=halt
```

Invoke the sub-skill using the resolved `SKILL_ID` and `SKILL_ARGS`:
```
Skill(skill=SKILL_ID, args=SKILL_ARGS)
```

```bash
unset Z_HARNESS_NO_ASK
```

> **If the Skill call raises an exception (SPEC C12):** capture `SKILL_FAILURE_MSG` from the exception text, then `unset Z_HARNESS_NO_ASK`. Proceed to step 3.7-error path below.

### Step 3.7 — Handle Skill-tool exception (SPEC C12)

If the Skill call above raised:

1. `unset Z_HARNESS_NO_ASK` (ensure cleared even on exception path).
2. Set `STEP_STATUS = "error"`.
3. Set `ERROR_EVENT = {kind: "skill_tool_failure", message: "<SKILL_FAILURE_MSG>", position: <CURSOR>, step: "<STEP_NAME>"}`.
4. Jump to Step 3.10 (terminal handling for this step). Step 3.11 is the single emission point for `overnight_step_error`.

**No retry on transient failure.** The user resumes via `/z-overnight resume <RUN_ID>`.

### Step 3.8 — Identify the sub-RUN archive dir (SPEC C14)

After a successful Skill call returns:

```bash
ARCHIVE_DIRS_AFTER="$(find "$ARCHIVE_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
  | while IFS= read -r d; do b="$(basename "$d")"; case "$b" in *-overnight-*) ;; *) printf '%s\n' "$b" ;; esac; done \
  | sort || true)"
# Compute set difference
NEW_DIRS="$(comm -13 <(printf '%s\n' "$ARCHIVE_DIRS_BEFORE" | sort) \
                      <(printf '%s\n' "$ARCHIVE_DIRS_AFTER" | sort))"
NEW_COUNT="$(printf '%s\n' "$NEW_DIRS" | grep -c '[^[:space:]]' || echo 0)"
```

- If `NEW_COUNT == 1` → `SUB_RUN_ID="$NEW_DIRS"`. Proceed to 3.9.
- If `NEW_COUNT == 0` → emit `run_id_ambiguous` as a top-level event, then set `STEP_STATUS` / `ERROR_EVENT`, and jump to 3.10:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" run_id_ambiguous \
    "$(printf '{"step":"%s","position":%d,"reason":"no new archive dir","new":[]}' \
       "$STEP_NAME" "$CURSOR")"
  STEP_STATUS="error"
  ERROR_EVENT="$(printf '{"kind":"run_id_ambiguous","reason":"no new archive dir","new":[]}' )"
  # Jump to Step 3.10
  ```
- If `NEW_COUNT > 1` → emit `run_id_ambiguous` as a top-level event, then set `STEP_STATUS` / `ERROR_EVENT`, and jump to 3.10:
  ```bash
  NEW_DIRS_JSON="$(printf '%s\n' "$NEW_DIRS" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().splitlines()))')"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" run_id_ambiguous \
    "$(printf '{"step":"%s","position":%d,"reason":"multiple new archive dirs","new":%s}' \
       "$STEP_NAME" "$CURSOR" "$NEW_DIRS_JSON")"
  STEP_STATUS="error"
  ERROR_EVENT="$(printf '{"kind":"run_id_ambiguous","reason":"multiple new archive dirs","new":%s}' "$NEW_DIRS_JSON")"
  # Jump to Step 3.10
  ```

### Step 3.9 — Classify the sub-run (SPEC C6)

```bash
CLASSIFY_RESULT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-status.sh" \
  classify "$SUB_RUN_ID" --command "$STEP_NAME" 2>/dev/null || echo "unknown")"
```

Map to step status:
- `clean` → `STEP_STATUS = "complete"`
- `halted` → `STEP_STATUS = "halt"`
- `errored` → `STEP_STATUS = "error"`
- `unknown` → `STEP_STATUS = "halt"` (fail-closed)

Get the last event for the terminal event kind:
```bash
LAST_EVENT_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-status.sh" \
  last-event "$SUB_RUN_ID" 2>/dev/null || echo "null")"
TERMINAL_EVENT_KIND="$(printf '%s' "$LAST_EVENT_JSON" | python3 -c \
  'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("kind","unknown") if isinstance(d,dict) else "unknown")' \
  2>/dev/null || echo "unknown")"
```

### Step 3.10 — Write updated state (SPEC C5 / C9)

Compute timing and diff:
```bash
STEP_ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STEP_ENDED_MS="$(date -u +%s%3N 2>/dev/null || python3 -c 'import time; print(int(time.time()*1000))')"
WALL_MS="$((STEP_ENDED_MS - STEP_STARTED_MS))"
HEAD_SHA_AFTER="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
GIT_DIFF_STAT="$(git diff --stat HEAD 2>/dev/null | tail -1 || echo "")"
```

Derive `ARTIFACT_PATHS` based on step name:
- `plan` → `["$BASE/SPEC.md", "$BASE/PLAN.md", "$BASE/TASKS.md"]` (include only those that exist)
- `research` → `["$BASE/RESEARCH.md"]` (if exists)
- `test` → `["$BASE/TESTS.md"]` (if exists)
- `implement-all` → list all files changed in git diff since `HEAD_SHA_BEFORE`
- `review-all` → list any `review-cycle*.md` files created in `$BASE/archive/tasks/*/`
- Other → `[]`

Update `step_runs[CURSOR]` in `overnight-state.json`. Also update top-level `git_diff_stat_at_end` at EVERY terminal transition (complete, halt, error). Write flock-guarded tmp+rename:

```python
# python3 snippet (inline or subprocess):
import json, os, fcntl

state_file = os.environ['STATE_FILE']
lock_file = os.environ['LOCK_FILE']

with open(lock_file, 'r+') as lf:
    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    with open(state_file) as sf:
        state = json.load(sf)

    cursor = int(os.environ['CURSOR'])
    step_run = state['step_runs'][cursor]
    step_run['status'] = os.environ['STEP_STATUS']
    step_run['head_sha_after'] = os.environ['HEAD_SHA_AFTER']
    step_run['ended_at'] = os.environ['STEP_ENDED_AT']
    step_run['wall_ms'] = int(os.environ['WALL_MS'])
    step_run['terminal_event_kind'] = os.environ.get('TERMINAL_EVENT_KIND', 'unknown')
    step_run['run_id'] = os.environ.get('SUB_RUN_ID', '')
    if os.environ.get('LAST_EVENT_JSON', 'null') != 'null':
        step_run['exit_event'] = json.loads(os.environ['LAST_EVENT_JSON'])
    if os.environ.get('ERROR_EVENT'):
        step_run['error_event'] = json.loads(os.environ['ERROR_EVENT'])
    artifact_paths_str = os.environ.get('ARTIFACT_PATHS_JSON', '[]')
    step_run['artifact_paths'] = json.loads(artifact_paths_str)

    state['git_diff_stat_at_end'] = os.environ.get('GIT_DIFF_STAT', '')

    tmp = state_file + '.tmp.' + str(os.getpid())
    with open(tmp, 'w') as tf:
        json.dump(state, tf, indent=2)
    os.rename(tmp, state_file)
    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
```

### Step 3.11 — Log the step terminal event

```bash
if [[ "$STEP_STATUS" == "complete" ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_step_complete \
    "$(printf '{"step":"%s","position":%d,"run_id":"%s","wall_ms":%d}' \
       "$STEP_NAME" "$CURSOR" "${SUB_RUN_ID:-}" "$WALL_MS")"
elif [[ "$STEP_STATUS" == "halt" ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_step_halt \
    "$(printf '{"step":"%s","position":%d,"run_id":"%s","halt_reason":"%s","halt_event":%s}' \
       "$STEP_NAME" "$CURSOR" "${SUB_RUN_ID:-}" "$TERMINAL_EVENT_KIND" \
       "${LAST_EVENT_JSON:-null}")"
else
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_step_error \
    "$(printf '{"step":"%s","position":%d,"run_id":"%s","error_event":%s}' \
       "$STEP_NAME" "$CURSOR" "${SUB_RUN_ID:-}" \
       "${ERROR_EVENT:-null}")"
fi
```

### Step 3.12 — Break on non-complete

If `STEP_STATUS != "complete"` → break the loop. Proceed to Phase 4 (terminal handling).

### Step 3.13 — Optional compact hint

If `STEP_STATUS == "complete"` AND `Z_HARNESS_OVERNIGHT_AUTO_COMPACT=1`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" compact_recommended \
  "{}"
```

Continue to next step.

## Phase 4 — Terminal handling

Executed unconditionally after the loop exits (whether complete, halt, or error). All sub-phases below are **best-effort**: if any sub-phase raises, log the failure and continue to the next sub-phase. The lock MUST be released even if MORNING_REPORT.md cannot be written.

### Step 4.1 — Determine overall run status

```bash
# If all steps are "complete" → OVERALL_STATUS = "complete"
# Otherwise find the step that stopped the chain
OVERALL_STATUS="complete"
HALTED_AT_STEP=""
for i in "${!CHAIN_STEPS[@]}"; do
  step_status = state.step_runs[i].status
  if step_status != "complete":
    OVERALL_STATUS = "halt" if step_status == "halt" else "error"
    HALTED_AT_STEP = "$i"  # 0-indexed position
    break
done
```

### Step 4.2 — Update top-level state to final status

Write the final top-level status **before** generating MORNING_REPORT.md so that the report reads current (not in-progress) values for `status` and `ended_at`.

```python
# flock-guarded: update state.status, state.ended_at, state.git_diff_stat_at_end
ended_at = datetime.utcnow().isoformat() + 'Z'
state['status'] = OVERALL_STATUS
state['ended_at'] = ended_at
if not state.get('git_diff_stat_at_end'):
    result = subprocess.run(
        ['git', 'diff', '--stat', 'HEAD'],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().splitlines()
    state['git_diff_stat_at_end'] = lines[-1] if lines else ''
```
Write flock-guarded tmp+rename.

### Step 4.3 — Write MORNING_REPORT.md

Write `$BASE/MORNING_REPORT.md`. This file is overwritten on every chain run. Because Step 4.2 has already committed the final state, `overnight-state.json` now contains the correct `status` and `ended_at` values.

Invoke the report generator directly:

```bash
MORNING_REPORT_EXIT=0
MORNING_REPORT_STDERR=""
MORNING_REPORT_STDERR="$(
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/morning-report.py" \
    "$Z_HARNESS_SLUG" 2>&1 >/dev/null
)" || MORNING_REPORT_EXIT=$?

if [[ "$MORNING_REPORT_EXIT" -ne 0 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" morning_report_failure \
    "$(printf '{"exit_code":%d,"stderr":"%s"}' \
       "$MORNING_REPORT_EXIT" \
       "$(printf '%s' "$MORNING_REPORT_STDERR" | head -c 200 | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))[1:-1]' 2>/dev/null || true)")"
  # Best-effort: proceed to lock release regardless of failure.
fi
```

### Step 4.4 — Log `overnight_end`

```bash
COMPLETED_STEPS="$(python3 -c "import json; s=json.load(open('$STATE_FILE')); print(sum(1 for r in s['step_runs'] if r['status']=='complete'))")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN_ID" overnight_end \
  "$(printf '{"status":"%s","total_steps":%d,"completed_steps":%d}' \
     "$OVERALL_STATUS" "${#CHAIN_STEPS[@]}" "$COMPLETED_STEPS")"
```

### Step 4.5 — Release lock

```bash
rm -f "$LOCK_FILE"
```

### Step 4.6 — Push-notify

```bash
if [[ "$OVERALL_STATUS" == "complete" ]]; then
  [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ] && \
    PushNotification("/z-overnight $Z_HARNESS_SLUG complete: all ${#CHAIN_STEPS[@]} steps finished. MORNING_REPORT.md written.")
else
  [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && \
    PushNotification("/z-overnight $Z_HARNESS_SLUG ${OVERALL_STATUS} at step ${HALTED_AT_STEP:-?}. Check MORNING_REPORT.md: $BASE/MORNING_REPORT.md")
fi
```

### Step 4.7 — Final summary to stdout

Print a brief summary to the conversation for the user:

```
/z-overnight <OVERALL_STATUS>: <slug> (<RUN_ID>)
Chain: <step1 → step2 → ...>
Status: <complete | halted at step N (<STEP_NAME>) | errored at step N (<STEP_NAME>)>
MORNING_REPORT.md: <BASE>/MORNING_REPORT.md
```

If halted or errored, also print the relevant section from MORNING_REPORT.md "Recommended next".

---

## Invariants

- `Z_HARNESS_NO_ASK=halt` is set ONLY around Skill tool calls (Phase 3.6) and unset immediately after. The parent orchestrator's own AskUserQuestion calls (lock contention, already-complete resume) run with NO_ASK unset.
- Hard halts (slug collision, lock corruption, state corruption) are NEVER bypassed by the overnight allowlist or halt-from-ask.
- `overnight-state.json` writes are always flock-guarded on `$BASE/.overnight.lock` using tmp+rename.
- Lock is released in Phase 4.5 even if MORNING_REPORT.md write fails (best-effort ordering).
- No retry on Skill-tool failure — the user resumes via `/z-overnight resume <RUN_ID>`.
- `git_diff_stat_at_end` is captured at EVERY terminal transition, not only on chain completion.
- Empty chain → usage error, no lock acquired (Phase 0 guard).
- Single-step chain → loop runs once, correct by the loop's structure.
- Resume-after-complete → no-op refresh with AskUserQuestion acknowledgement (Phase 2 step 3).

## Known v1 limits

- **Fail-OPEN for unregistered AskUserQuestion callsites.** Only 12 AskUserQuestion callsites participate in halt-from-ask (9 existing resolver sites + 3 new gates). Sub-commands that call `AskUserQuestion` outside this set will block the conversation until you respond, even with `Z_HARNESS_NO_ASK=halt`. Run `scripts/lint-askuser.sh --strict` before launching a long chain and instrument any callsites flagged as unregistered if they are on your chain's hot path. v2 will pursue runtime enforcement.
- **Linear chains only.** DAG / parallel-cluster overnight runs deferred to v2.
- **Skill-tool composition over subprocess.** Context accumulation risk for step 4+ on large implementations. Deferred to v2.
