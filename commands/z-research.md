---
name: z-research
description: Higher-order meta-orchestrator. Composes /z-map (terrain) and /z-brainstorm (framings), then runs adversarial synthesis panel (3 perspectives + judge) producing RESEARCH.md with 10-section schema including approach decision matrix. Cost 3–6M tokens; AskUser cost gate at invocation.
argument-hint: <research-topic> [--slug=<kebab>]
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-research`** meta-orchestrator pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

Strict, multi-phase. Do not skip phases. `/z-research` orchestrates sub-commands and an adversarial synthesis panel — it does **not** write MAP.md or BRAINSTORM.md content directly. Those artifacts are exclusively owned by `/z-map` and `/z-brainstorm` respectively.

**Cost warning:** this pipeline runs up to 3M tokens for sub-commands + 3M tokens for the synthesis panel (3 perspectives @ ~1M each) + 0.5M for the judge. Total: 3–6M tokens. The cost gate in Phase 0.5 always runs before dispatch.

---

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

```bash
TOPIC=""
SLUG_OVERRIDE=""
_args=($ARGUMENTS)
_i=0
while [ $_i -lt ${#_args[@]} ]; do
  _arg="${_args[$_i]}"
  case "$_arg" in
    --slug=*) SLUG_OVERRIDE="${_arg#--slug=}" ;;
    *)        TOPIC="$TOPIC $_arg" ;;
  esac
  _i=$((_i+1))
done
TOPIC="$(echo "$TOPIC" | xargs)"  # trim leading/trailing whitespace
```

---

## Setup

### Step 1 — Topic gate

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question "What research topic should I synthesize?" via their native channel. Silent omission is forbidden. -->
If `$TOPIC` is empty or whitespace, do NOT auto-invent a topic. Use `AskUserQuestion` to ask: "What research topic should I synthesize? (question or technical area)" Wait for the reply. Treat the reply as `$TOPIC` and continue.

### Step 2 — Derive slug

If `--slug=` was provided, use `$SLUG_OVERRIDE` as the slug. Otherwise derive a short kebab-case slug (2–4 words) from `$TOPIC`. Example: "how does retry interact with token limits?" → `retry-token-limits`.

```bash
SLUG="<derived-or-overridden-kebab-slug>"
export Z_HARNESS_SLUG="$SLUG"
```

### Step 3 — Resolve plan dir and RUN id

```bash
Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
export Z_HARNESS_PLAN_DIR
RUN="$(date -u +%Y%m%dT%H%M%SZ)-$SLUG"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns"
export RUN
```

### Step 4 — Log run start + providers

```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]; v["arguments"] = sys.argv[3]
print(json.dumps(v))
' "$VERSION_BLOB" "$TOPIC" "$ARGUMENTS")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
```

Log provider resolution once:

```bash
if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
  touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
fi
```

### Step 5 — Notification policy

See [docs/human/config.md](docs/human/config.md) (notify.level key). Check via `config.py should-notify` before each push-notify call.

---

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 4), record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, log `user_wait_start` / `user_wait_end` events bracketing the wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":<n>,"reason":"<short>"}'
_WAIT_T0=$(date +%s%3N)
# AskUserQuestion(...)
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":<n>,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

---

## Phase 0 — Dispatch decision (intelligent, user-driven)

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Read slug dir state

Compute `MAP_STATE` and `BRAINSTORM_STATE` for the existing artifacts in `$Z_HARNESS_PLAN_DIR`.

**MAP_STATE algorithm:**

```bash
MAP_STATE="absent"
if [ -f "$Z_HARNESS_PLAN_DIR/MAP.md" ]; then
  # Read generated_at from MAP.md frontmatter
  MAP_GENERATED_AT="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(r'^generated_at:\s*(.+)$', content, re.MULTILINE)
print(m.group(1).strip() if m else '')
" "$Z_HARNESS_PLAN_DIR/MAP.md")"

  if [ -z "$MAP_GENERATED_AT" ]; then
    # No frontmatter generated_at — treat as stale
    MAP_STATE="stale"
  else
    # Check if any source file cited in MAP.md has a commit more recent than generated_at
    # Extract source files from MAP.md frontmatter source_files field
    SOURCE_FILES="$(python3 -c "
import sys, re, json
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(r'^source_files:\s*\n((?:\s+-[^\n]+\n)*)', content, re.MULTILINE)
if not m:
    print('')
    sys.exit(0)
files = re.findall(r'-\s+(.+)', m.group(1))
print('\n'.join(f.strip() for f in files))
" "$Z_HARNESS_PLAN_DIR/MAP.md")"

    MAP_STATE="fresh"
    if [ -n "$SOURCE_FILES" ]; then
      while IFS= read -r src_file; do
        [ -z "$src_file" ] && continue
        # Get most recent tracked commit timestamp on this file
        COMMIT_TS="$(git log -1 --format=%cI -- "$src_file" 2>/dev/null || true)"
        if [ -n "$COMMIT_TS" ] && [ "$COMMIT_TS" \> "$MAP_GENERATED_AT" ]; then
          MAP_STATE="stale"
          break
        fi
      done <<< "$SOURCE_FILES"
    fi
  fi
fi
```

Note: untracked uncommitted changes in cited files are NOT counted as stale (avoids spurious staleness from in-flight work).

**BRAINSTORM_STATE algorithm:**

```bash
BRAINSTORM_STATE="absent"
if [ -f "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" ]; then
  # Parse status: field from BRAINSTORM.md frontmatter
  BRAINSTORM_STATUS="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f:
    content = f.read()
status_m = re.search(r'^status:\s*(.+)$', content, re.MULTILINE)
chosen_m = re.search(r'^chosen_(?:framing|pair):\s*(.+)$', content, re.MULTILINE)
status = status_m.group(1).strip() if status_m else ''
chosen = chosen_m.group(1).strip() if chosen_m else ''
print(status + '|' + chosen)
" "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md")"

  STATUS_PART="$(echo "$BRAINSTORM_STATUS" | cut -d'|' -f1)"
  CHOSEN_PART="$(echo "$BRAINSTORM_STATUS" | cut -d'|' -f2)"

  if [ "$STATUS_PART" = "complete" ] && [ -n "$CHOSEN_PART" ] && [ "$CHOSEN_PART" != "abandoned" ]; then
    BRAINSTORM_STATE="complete"
  else
    BRAINSTORM_STATE="incomplete"
  fi
fi
```

### Step 2 — Dispatch decision matrix (4-bucket)

Determine the suggested dispatch action based on the 4-bucket matrix:

| MAP_STATE | BRAINSTORM_STATE | Suggested dispatch |
|---|---|---|
| `absent` or `stale` | `absent` or `incomplete` | **Run both** |
| `absent` or `stale` | `complete` | **Run /z-map, reuse BRAINSTORM** |
| `fresh` | `absent` or `incomplete` | **Reuse MAP, run /z-brainstorm** |
| `fresh` | `complete` | **Reuse both, synthesize directly** |

```bash
# Determine dispatch bucket
if [ "$MAP_STATE" = "absent" ] || [ "$MAP_STATE" = "stale" ]; then
  if [ "$BRAINSTORM_STATE" = "absent" ] || [ "$BRAINSTORM_STATE" = "incomplete" ]; then
    DISPATCH_SUGGESTION="run_both"
    DISPATCH_LABEL="Run both /z-map and /z-brainstorm"
  else
    DISPATCH_SUGGESTION="run_map_reuse_brainstorm"
    DISPATCH_LABEL="Run /z-map (MAP is ${MAP_STATE}), reuse existing BRAINSTORM"
  fi
else
  # MAP_STATE = fresh
  if [ "$BRAINSTORM_STATE" = "absent" ] || [ "$BRAINSTORM_STATE" = "incomplete" ]; then
    DISPATCH_SUGGESTION="reuse_map_run_brainstorm"
    DISPATCH_LABEL="Reuse existing MAP, run /z-brainstorm"
  else
    DISPATCH_SUGGESTION="reuse_both"
    DISPATCH_LABEL="Reuse both artifacts, go directly to synthesis panel"
  fi
fi
```

### Step 3 — AskUser dispatch gate

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the dispatch decision (confirm / override / abandon) via their native channel. Silent omission is forbidden. -->
Present the suggested dispatch via `AskUserQuestion` with three options:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":0,"reason":"dispatch_decision"}'
_WAIT_T0=$(date +%s%3N)
```

> **Dispatch decision for `/z-research $TOPIC`**
>
> Current artifact state:
> - MAP.md: `$MAP_STATE` (path: `$Z_HARNESS_PLAN_DIR/MAP.md`)
> - BRAINSTORM.md: `$BRAINSTORM_STATE` (path: `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`)
>
> Suggested dispatch: **$DISPATCH_LABEL**
>
> Options:
> 1. **Confirm suggested** (default — proceed with the suggestion above)
> 2. **Override** (specify which sub-commands to run or skip — free text)
> 3. **Abandon** — exit without running anything

After the user responds, set `DISPATCH_MAP` and `DISPATCH_BRAINSTORM` to one of `ran|reused|skipped|abandoned`:

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":0,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

- **Option 1 (confirm):** Resolve `DISPATCH_MAP` and `DISPATCH_BRAINSTORM` from `DISPATCH_SUGGESTION`:
  - `run_both` → `DISPATCH_MAP=ran DISPATCH_BRAINSTORM=ran`
  - `run_map_reuse_brainstorm` → `DISPATCH_MAP=ran DISPATCH_BRAINSTORM=reused`
  - `reuse_map_run_brainstorm` → `DISPATCH_MAP=reused DISPATCH_BRAINSTORM=ran`
  - `reuse_both` → `DISPATCH_MAP=reused DISPATCH_BRAINSTORM=reused`
- **Option 2 (override):** Parse the user's free-text override. Accept inputs like "skip map", "run both", "force brainstorm only", "skip both". Set `DISPATCH_MAP` and `DISPATCH_BRAINSTORM` accordingly. If the override is ambiguous, AskUser again with clarifying options.
- **Option 3 (abandon):** Set `DISPATCH_MAP=abandoned DISPATCH_BRAINSTORM=abandoned`. Log `research_dispatch_decision` with abandoned status, emit `run_end status: aborted_by_user`, and exit.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_dispatch_decision \
  "$(printf '{"map":"%s","brainstorm":"%s","map_state":"%s","brainstorm_state":"%s","suggestion":"%s"}' \
     "$DISPATCH_MAP" "$DISPATCH_BRAINSTORM" "$MAP_STATE" "$BRAINSTORM_STATE" "$DISPATCH_SUGGESTION")"
```

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":0,"name":"dispatch-decision","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 0.5 — Cost gate

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Estimate cost

Compute the estimated token cost from the dispatch decision:

```bash
COST_MAP=0
COST_BRAINSTORM=0
COST_PANEL=3000000   # 3 perspectives @ ~1M each
COST_JUDGE=500000    # judge @ ~0.5M

[ "$DISPATCH_MAP" = "ran" ] && COST_MAP=2000000
[ "$DISPATCH_BRAINSTORM" = "ran" ] && COST_BRAINSTORM=200000

COST_TOTAL=$(( COST_MAP + COST_BRAINSTORM + COST_PANEL + COST_JUDGE ))

# Format as human-readable
COST_TOTAL_M="$(python3 -c "print(f'{$COST_TOTAL / 1_000_000:.1f}M')")"
```

Build cost breakdown line:

```bash
COST_BREAKDOWN=""
[ "$DISPATCH_MAP" = "ran" ]        && COST_BREAKDOWN="$COST_BREAKDOWN /z-map: ~2M tokens |"
[ "$DISPATCH_BRAINSTORM" = "ran" ] && COST_BREAKDOWN="$COST_BREAKDOWN /z-brainstorm: ~200K tokens |"
COST_BREAKDOWN="$COST_BREAKDOWN synthesis panel (3 perspectives): ~3M tokens | judge: ~0.5M tokens"
```

### Step 2 — AskUser cost gate

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the cost gate (proceed / change dispatch / abandon) via their native channel. Silent omission is forbidden. -->
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":"0.5","reason":"cost_gate"}'
_WAIT_T0=$(date +%s%3N)
```

> **Cost estimate for `/z-research $TOPIC`**
>
> Breakdown: $COST_BREAKDOWN
> **Total estimated: ~$COST_TOTAL_M tokens**
>
> Options:
> 1. **Proceed** — run as planned
> 2. **Change dispatch** — go back to Phase 0 to adjust which sub-commands to run
> 3. **Abandon** — exit cleanly, write nothing

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":"0.5","wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

Handle response:
- **Proceed:** log `research_cost_gate_decision {choice: proceed, estimated_tokens: $COST_TOTAL}` and continue.
- **Change dispatch:** log `research_cost_gate_decision {choice: change_dispatch, estimated_tokens: $COST_TOTAL}`, then loop back to Phase 0 (re-run the dispatch decision, then return here). Cap at 3 loop-backs before falling through to Abandon.
- **Abandon:** log `research_cost_gate_decision {choice: abandon}`, emit `run_end status: aborted_by_user`, exit.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_cost_gate_decision \
  "$(printf '{"choice":"%s","estimated_tokens":%d}' "<proceed|change_dispatch|abandon>" "$COST_TOTAL")"
```

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"0.5","name":"cost-gate","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 1 — Subcommand dispatch (inline, with audit contract)

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Sub-run audit contract

The orchestrator cannot mutate a sub-command's internal RUN id — each sub-command derives its own from `date -u +%Y%m%dT%H%M%SZ`. Audit attribution uses the **child-emits-event-with-parent-attribution** pattern:

1. Orchestrator exports `Z_HARNESS_PARENT_RUN_ID=$RUN` and `Z_HARNESS_PARENT_COMMAND=/z-research` into the Agent() dispatch environment.
2. Sub-command's Setup detects `$Z_HARNESS_PARENT_RUN_ID` and includes `parent_run_id` in every `log-event.sh` payload it emits (this is already handled by the sub-commands' Setup step 6 — see /z-map Setup step 6 and /z-brainstorm equivalent).
3. After the sub-command completes, orchestrator extracts the sub-run id from the sub-command's emitted `run_start` event in its events.jsonl.
4. Orchestrator creates a symlink `archive/$RUN/subruns/<sub-command>` → `archive/<sub-run>/`.
5. Orchestrator emits `research_subcommand_complete`.

### Step 1 — Mkdir subruns parent

```bash
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns"
```

### Step 2 — Dispatch /z-map (if `DISPATCH_MAP=ran`)

**When both `DISPATCH_MAP=ran` AND `DISPATCH_BRAINSTORM=ran`, skip this step and go directly to Step 2+3 (parallel dispatch) below.**

If `DISPATCH_MAP=ran` (and `DISPATCH_BRAINSTORM != ran`):

1. Dispatch `/z-map` via Agent():

   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The /z-map sub-command produces the terrain MAP.md used in synthesis; drivers that skip it must warn the user that terrain mapping is unavailable. -->
   ```
   Agent(
     subagent_type="z-map",
     description="Terrain mapping for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   ```

2. After Agent() returns, extract the sub-run id:

   ```bash
   # Find the most recent archive dir under $Z_HARNESS_PLAN_DIR/archive/ that matches the slug pattern
   # and is NOT our own RUN (sub-command creates its own archive dir during its Setup)
   MAP_SUB_RUN="$(ls -1t "$Z_HARNESS_PLAN_DIR/archive/" | grep -v "^${RUN}$" | grep "$SLUG" | head -1 || true)"
   ```

   If `MAP_SUB_RUN` is empty, search for any events.jsonl with a `research_run_start` event (the event type emitted by /z-map):

   ```bash
   MAP_ARCHIVE_PATH="$Z_HARNESS_PLAN_DIR/archive/$MAP_SUB_RUN"
   ```

3. Verify MAP.md was written by the sub-command:

   ```bash
   python3 -c "
   import sys, os, re
   path = sys.argv[1]
   if not os.path.isfile(path):
       print('MISSING'); sys.exit(1)
   if os.path.getsize(path) < 100:
       print('TOO_SMALL'); sys.exit(1)
   with open(path) as f:
       content = f.read()
   if not re.search(r'^artifact:', content, re.MULTILINE):
       print('NO_ARTIFACT_FIELD'); sys.exit(1)
   print('OK')
   " "$Z_HARNESS_PLAN_DIR/MAP.md"
   MAP_VERIFY_STATUS=$?
   ```

   If MAP.md verification fails: abort the current run, log `research_subcommand_failed {sub: z-map, reason: artifact_missing_or_malformed}`, push-notify, surface to user. Do NOT attempt to fix the sub-command's output.

4. Create symlink:

   ```bash
   ln -sfn "$MAP_ARCHIVE_PATH" "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns/z-map"
   ```

5. Emit:

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
     "$(printf '{"sub":"z-map","status":"complete","sub_run_id":"%s","sub_archive_path":"%s"}' \
        "$MAP_SUB_RUN" "$MAP_ARCHIVE_PATH")"
   ```

If `DISPATCH_MAP=reused`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
  "$(printf '{"sub":"z-map","status":"reused","sub_run_id":null,"sub_archive_path":null}')"
```

If `DISPATCH_MAP=skipped`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
  "$(printf '{"sub":"z-map","status":"skipped","sub_run_id":null,"sub_archive_path":null}')"
```

### Step 3 — Dispatch /z-brainstorm (if `DISPATCH_BRAINSTORM=ran`)

**When both `DISPATCH_MAP=ran` AND `DISPATCH_BRAINSTORM=ran`, skip this step — it was already handled in Step 2+3 (parallel dispatch) below.**

If `DISPATCH_BRAINSTORM=ran` (and `DISPATCH_MAP != ran`):

1. Dispatch `/z-brainstorm` via Agent():

   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The /z-brainstorm sub-command produces the framings BRAINSTORM.md used in synthesis; drivers that skip it must warn the user that brainstorm is unavailable. -->
   ```
   Agent(
     subagent_type="z-brainstorm",
     description="Brainstorm framings for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   ```

2. After Agent() returns, extract the sub-run id:

   ```bash
   BRAINSTORM_SUB_RUN="$(ls -1t "$Z_HARNESS_PLAN_DIR/archive/" | grep -v "^${RUN}$" | grep "$SLUG" | head -1 || true)"
   BRAINSTORM_ARCHIVE_PATH="$Z_HARNESS_PLAN_DIR/archive/$BRAINSTORM_SUB_RUN"
   ```

3. Verify BRAINSTORM.md was written:

   ```bash
   python3 -c "
   import sys, os, re
   path = sys.argv[1]
   if not os.path.isfile(path):
       print('MISSING'); sys.exit(1)
   if os.path.getsize(path) < 100:
       print('TOO_SMALL'); sys.exit(1)
   with open(path) as f:
       content = f.read()
   if not re.search(r'^artifact:', content, re.MULTILINE):
       print('NO_ARTIFACT_FIELD'); sys.exit(1)
   print('OK')
   " "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"
   BRAINSTORM_VERIFY_STATUS=$?
   ```

   If BRAINSTORM.md verification fails: abort, log `research_subcommand_failed {sub: z-brainstorm, reason: artifact_missing_or_malformed}`, push-notify, surface to user. Preserve the partial artifacts already written.

4. Create symlink:

   ```bash
   ln -sfn "$BRAINSTORM_ARCHIVE_PATH" "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns/z-brainstorm"
   ```

5. Emit:

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
     "$(printf '{"sub":"z-brainstorm","status":"complete","sub_run_id":"%s","sub_archive_path":"%s"}' \
        "$BRAINSTORM_SUB_RUN" "$BRAINSTORM_ARCHIVE_PATH")"
   ```

If `DISPATCH_BRAINSTORM=reused` or `DISPATCH_BRAINSTORM=skipped`, emit accordingly (same pattern as /z-map above).

### Step 2+3 — Parallel dispatch (when `DISPATCH_MAP=ran` AND `DISPATCH_BRAINSTORM=ran`)

This step fires only when both sub-commands need to run (i.e., `DISPATCH_MAP=ran` AND `DISPATCH_BRAINSTORM=ran`). Both Agent() calls are issued in a **single message** so they execute in parallel.

1. Snapshot existing archive entries before dispatch:

   ```bash
   PRE_DISPATCH_ARCHIVE="$(ls -1 "$Z_HARNESS_PLAN_DIR/archive/" | grep -v "^${RUN}$" | grep "$SLUG" || true)"
   ```

2. Dispatch **both** sub-commands in one message:

   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() calls. Both sub-commands must be dispatched; drivers that skip either must warn the user that the corresponding artifact is unavailable. -->
   ```
   Agent(
     subagent_type="z-map",
     description="Terrain mapping for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   Agent(
     subagent_type="z-brainstorm",
     description="Brainstorm framings for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   ```

   Both agents run in parallel and both must complete before continuing.

3. After both Agent() calls return, identify the two new archive directories by diffing against the pre-dispatch snapshot. Distinguish MAP from BRAINSTORM by reading the first event in each new archive's `events.jsonl` and checking its `kind` field — `/z-map` emits `kind: "map_run_start"` and `/z-brainstorm` emits `kind: "brainstorm_run_start"`. This is robust against RUN-ID timestamp collisions (both commands derive RUN from the same second-precision timestamp) because the `kind` field is set by the command itself, not by the directory name.

   ```bash
   POST_DISPATCH_ARCHIVE="$(ls -1 "$Z_HARNESS_PLAN_DIR/archive/" | grep -v "^${RUN}$" | grep "$SLUG" || true)"
   NEW_ARCHIVE_DIRS="$(comm -13 <(echo "$PRE_DISPATCH_ARCHIVE" | sort) <(echo "$POST_DISPATCH_ARCHIVE" | sort))"

   # Abort if we don't have exactly two new archive directories
   NEW_COUNT="$(echo "$NEW_ARCHIVE_DIRS" | grep -c '[^[:space:]]' || true)"
   if [ "$NEW_COUNT" -ne 2 ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
       "$(printf '{"status":"error","reason":"parallel_dispatch_archive_count_unexpected","expected":2,"actual":%d}' "$NEW_COUNT")"
     echo "ERROR: expected exactly 2 new archive directories after parallel dispatch, found $NEW_COUNT. Cannot identify sub-run archives. Aborting." >&2
     exit 1
   fi

   MAP_SUB_RUN=""
   BRAINSTORM_SUB_RUN=""

   while IFS= read -r dir; do
     [ -z "$dir" ] && continue
     events_file="$Z_HARNESS_PLAN_DIR/archive/$dir/events.jsonl"
     if [ -f "$events_file" ]; then
       first_kind="$(python3 -c "import sys,json
line=open(sys.argv[1]).readline().strip()
if line: print(json.loads(line).get('kind',''))
" "$events_file" 2>/dev/null || true)"
       case "$first_kind" in
         map_run_start)        MAP_SUB_RUN="$dir" ;;
         brainstorm_run_start) BRAINSTORM_SUB_RUN="$dir" ;;
       esac
     fi
   done <<< "$NEW_ARCHIVE_DIRS"

   # No fallback: if identification failed, abort with a clear error rather than guess
   if [ -z "$MAP_SUB_RUN" ] || [ -z "$BRAINSTORM_SUB_RUN" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
       "$(printf '{"status":"error","reason":"parallel_dispatch_archive_identification_failed","map_found":"%s","brainstorm_found":"%s"}' \
          "${MAP_SUB_RUN:-none}" "${BRAINSTORM_SUB_RUN:-none}")"
     echo "ERROR: could not positively identify both sub-run archives from events.jsonl kind fields. map='${MAP_SUB_RUN:-not found}' brainstorm='${BRAINSTORM_SUB_RUN:-not found}'. Aborting." >&2
     exit 1
   fi

   if [ "$MAP_SUB_RUN" = "$BRAINSTORM_SUB_RUN" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
       "$(printf '{"status":"error","reason":"parallel_dispatch_archive_collision","map_sub_run":"%s","brainstorm_sub_run":"%s"}' \
          "$MAP_SUB_RUN" "$BRAINSTORM_SUB_RUN")"
     echo "ERROR: MAP and BRAINSTORM sub-runs resolved to the same archive directory '$MAP_SUB_RUN'. Aborting." >&2
     exit 1
   fi

   MAP_ARCHIVE_PATH="$Z_HARNESS_PLAN_DIR/archive/$MAP_SUB_RUN"
   BRAINSTORM_ARCHIVE_PATH="$Z_HARNESS_PLAN_DIR/archive/$BRAINSTORM_SUB_RUN"
   ```

4. Verify MAP.md was written:

   ```bash
   python3 -c "
   import sys, os, re
   path = sys.argv[1]
   if not os.path.isfile(path):
       print('MISSING'); sys.exit(1)
   if os.path.getsize(path) < 100:
       print('TOO_SMALL'); sys.exit(1)
   with open(path) as f:
       content = f.read()
   if not re.search(r'^artifact:', content, re.MULTILINE):
       print('NO_ARTIFACT_FIELD'); sys.exit(1)
   print('OK')
   " "$Z_HARNESS_PLAN_DIR/MAP.md"
   MAP_VERIFY_STATUS=$?
   ```

   If MAP.md verification fails: abort the current run, log `research_subcommand_failed {sub: z-map, reason: artifact_missing_or_malformed}`, push-notify, surface to user. Do NOT attempt to fix the sub-command's output.

5. Verify BRAINSTORM.md was written:

   ```bash
   python3 -c "
   import sys, os, re
   path = sys.argv[1]
   if not os.path.isfile(path):
       print('MISSING'); sys.exit(1)
   if os.path.getsize(path) < 100:
       print('TOO_SMALL'); sys.exit(1)
   with open(path) as f:
       content = f.read()
   if not re.search(r'^artifact:', content, re.MULTILINE):
       print('NO_ARTIFACT_FIELD'); sys.exit(1)
   print('OK')
   " "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"
   BRAINSTORM_VERIFY_STATUS=$?
   ```

   If BRAINSTORM.md verification fails: abort, log `research_subcommand_failed {sub: z-brainstorm, reason: artifact_missing_or_malformed}`, push-notify, surface to user. Preserve the partial artifacts already written.

6. Create symlinks (gated on directory existence and non-collision):

   ```bash
   if [ -d "$MAP_ARCHIVE_PATH" ] && [ -d "$BRAINSTORM_ARCHIVE_PATH" ] && [ "$MAP_SUB_RUN" != "$BRAINSTORM_SUB_RUN" ]; then
     ln -sfn "$MAP_ARCHIVE_PATH"        "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns/z-map"
     ln -sfn "$BRAINSTORM_ARCHIVE_PATH" "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns/z-brainstorm"
   else
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
       "$(printf '{"status":"error","reason":"symlink_precondition_failed","map_dir_exists":%s,"brainstorm_dir_exists":%s,"collision":%s}' \
          "$([ -d "$MAP_ARCHIVE_PATH" ] && echo true || echo false)" \
          "$([ -d "$BRAINSTORM_ARCHIVE_PATH" ] && echo true || echo false)" \
          "$([ "$MAP_SUB_RUN" = "$BRAINSTORM_SUB_RUN" ] && echo true || echo false)")"
     echo "ERROR: symlink precondition failed — archive directories must exist and must differ. Aborting." >&2
     exit 1
   fi
   ```

7. Emit completion events for both (only reached if symlinks were created successfully):

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
     "$(printf '{"sub":"z-map","status":"complete","sub_run_id":"%s","sub_archive_path":"%s"}' \
        "$MAP_SUB_RUN" "$MAP_ARCHIVE_PATH")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_subcommand_complete \
     "$(printf '{"sub":"z-brainstorm","status":"complete","sub_run_id":"%s","sub_archive_path":"%s"}' \
        "$BRAINSTORM_SUB_RUN" "$BRAINSTORM_ARCHIVE_PATH")"
   ```

### Step 4 — Final artifact readiness check

Before proceeding to Phase 2, both MAP.md and BRAINSTORM.md must exist and be readable:

```bash
ARTIFACTS_READY=true
[ ! -f "$Z_HARNESS_PLAN_DIR/MAP.md" ]        && ARTIFACTS_READY=false
[ ! -f "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" ] && ARTIFACTS_READY=false

if [ "$ARTIFACTS_READY" = "false" ]; then
  # Surface to user which artifact is missing; halt with clear message.
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
    "$(printf '{"slug":"%s","status":"aborted","reason":"required_artifacts_missing"}' "$SLUG")"
  exit 1
fi
```

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":1,"name":"subcommand-dispatch","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 2 — Adversarial synthesis panel

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Panel composition

Three perspectives are dispatched in parallel via a **single message** (all three Agent() calls at once):

- **architecture-conservative** → `Agent(subagent_type="general-purpose", model="opus", ...)` — the Anthropic/Claude perspective.
- **product-expansive** → `Agent(subagent_type="consultant-primary", ...)` — resolves to whichever provider the user has bound to `consultant_primary` in `providers.json` (typically Codex).
- **failure-mode-adversarial** → `Agent(subagent_type="consultant-secondary", ...)` — resolves to whichever provider the user has bound to `consultant_secondary` in `providers.json` (typically Gemini).

**Invariant:** these vendor assignments are static for vendor diversity. Do NOT substitute a hard-coded Opus call for a consultant that is unavailable — the vendor diversity is the point of the panel. If a consultant is unavailable, log it as a panel failure (see failure semantics below).

### Step 1 — Build shared panel prompt body

```bash
MAP_PATH="$Z_HARNESS_PLAN_DIR/MAP.md"
BRAINSTORM_PATH="$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"

PANEL_BASE_PROMPT="MODE: research-synthesis

host_run_id: $RUN
slug: $SLUG
topic: $TOPIC
map_path: $MAP_PATH
brainstorm_path: $BRAINSTORM_PATH

You are one perspective in an adversarial synthesis panel for /z-research. Your job is to analyze the approaches in BRAINSTORM.md against the terrain constraints in MAP.md from your assigned perspective lens.

HARD INVARIANTS (same as research-judge):
- FORBIDDEN: proposing new design recommendations, new approaches, or new architectural patterns not already in BRAINSTORM.md.
- ALLOWED: scoring approaches against constraints, emphasizing constraints, noting contradictions, ranking by constraint-fit.
- Every claim must cite MAP.md or BRAINSTORM.md. Uncited claims are marked UNVERIFIED.
- NO recommendation language ('I recommend...', 'the best approach...', 'we should...').

Read MAP.md at: $MAP_PATH
Read BRAINSTORM.md at: $BRAINSTORM_PATH

Your return MUST contain exactly these 4 sections:

## Approach scoring
(For each approach in BRAINSTORM.md: score against constraints from your perspective. Format: Approach name: verdict per constraint class. Cite source per verdict.)

## Constraint emphasis
(Which MAP.md constraints does your perspective consider load-bearing? Cite MAP.md:<section> per constraint listed.)

## Contradictions noticed
(Where does MAP.md evidence contradict BRAINSTORM.md assumptions? Where does this perspective disagree with what another perspective might emphasize? Cite both sides.)

## Citations
(Exhaustive list of file:section references used above. Format: - file:section — brief description)"
```

### Step 2 — Per-perspective prompt addenda

```bash
CONSERVATIVE_ADDENDUM="ASSIGNED PERSPECTIVE: architecture-conservative

Lens: Which framings are most compatible with existing patterns documented in MAP.md? What is the lowest-risk implementation path given MAP.md constraints? Identify approaches that minimize MAP.md constraint violations. Cite MAP.md or BRAINSTORM.md per claim. Do not recommend — score and emphasize only."

EXPANSIVE_ADDENDUM="ASSIGNED PERSPECTIVE: product-expansive

Lens: Which framings open the most user-facing capability? What does each framing enable that others do not (per BRAINSTORM.md)? Identify which MAP.md constraints are most important to relax or satisfy for user-facing wins. Cite both artifacts per claim. Do not recommend — score and emphasize only."

ADVERSARIAL_ADDENDUM="ASSIGNED PERSPECTIVE: failure-mode-adversarial

Lens: What fails first in each framing (per BRAINSTORM.md approaches)? Where does each approach accumulate hidden coupling, debt, or fragility (per MAP.md constraints)? Identify approaches whose MAP.md constraint profile reveals the most risk. Cite both artifacts per claim. Do not recommend — score and emphasize only."
```

### Step 3 — Parallel dispatch (single message)

Dispatch all three in **one message**:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip all three Agent() calls. The panel perspectives feed into the research judge; drivers that skip them must warn the user that the adversarial synthesis panel is unavailable. -->
```
Agent(
  subagent_type="general-purpose",
  model="opus",
  description="Panel perspective: architecture-conservative for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT

$CONSERVATIVE_ADDENDUM"
)

Agent(
  subagent_type="consultant-primary",
  description="Panel perspective: product-expansive for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT

$EXPANSIVE_ADDENDUM"
)

Agent(
  subagent_type="consultant-secondary",
  description="Panel perspective: failure-mode-adversarial for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT

$ADVERSARIAL_ADDENDUM"
)
```

Wait for all three to return before proceeding.

### Step 4 — Capture returns and handle failures

For each perspective that returns successfully, write its output to the panel archive:

```bash
echo "$CONSERVATIVE_RETURN" > "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel/architecture-conservative.md"
echo "$EXPANSIVE_RETURN"    > "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel/product-expansive.md"
echo "$ADVERSARIAL_RETURN"  > "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel/failure-mode-adversarial.md"
```

**Failure semantics (matching /z-brainstorm 1/3, 2/3, 3/3 pattern):**

A perspective is counted as **failed** if it returns an error, returns `bad_input` (provider CLI unavailable), times out, or returns a response missing all four required sections. Log each failure:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_panel_provider_unavailable \
  "$(printf '{"perspective":"%s","provider":"%s","reason":"%s"}' \
     "<perspective>" "<provider>" "<reason>")"
```

**1/3 fail:** proceed with the surviving two perspectives. Record the failed perspective (its panel file will be absent). The judge handles `N=2` by emitting the matrix with 2-perspective citations and setting `panel_degraded: true` in its return notes.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the 2/3 panel failure decision (retry / proceed-with-1 / abandon) via their native channel. Silent omission is forbidden. -->
**2/3 fail:** halt and present `AskUserQuestion`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":2,"reason":"panel_2_of_3_failed"}'
_WAIT_T0=$(date +%s%3N)
```

> 2 of 3 panel perspectives failed. Options:
> 1. **Retry** (default) — re-dispatch the failed perspectives once
> 2. **Proceed-with-1** — continue to the judge with the single surviving perspective (synthesis quality will be significantly degraded; `panel_degraded: true` will be set)
> 3. **Abandon** — exit; panel outputs archived but RESEARCH.md not written

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":2,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

On retry: re-dispatch only the failed perspectives (not all three) in a single message. Apply the same 1/3 / 2/3 / 3/3 check to the retry results.

On abandon: log `run_end status: aborted_by_user`, exit. Do not delete any panel outputs already written.

**3/3 fail:** hard halt. Log `total_panel_failure`, push-notify the user, exit. Do not write RESEARCH.md.

### Step 5 — Build perspectives array for judge

Build the `PERSPECTIVES_JSON` array for the judge, containing only the perspectives that succeeded:

```bash
PERSPECTIVES_JSON="$(python3 -c "
import json, os, sys

panel_dir = sys.argv[1]
perspectives = [
    ('architecture-conservative', 'architecture-conservative.md'),
    ('product-expansive',         'product-expansive.md'),
    ('failure-mode-adversarial',  'failure-mode-adversarial.md'),
]
result = []
for name, fname in perspectives:
    path = os.path.join(panel_dir, fname)
    if os.path.isfile(path) and os.path.getsize(path) > 50:
        result.append({'name': name, 'return_path': path})
print(json.dumps(result))
" "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel")"

PANEL_PERSPECTIVE_COUNT="$(echo "$PERSPECTIVES_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")"
```

### Step 6 — Emit per-perspective telemetry

For each perspective that completed, emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_panel_lane_complete \
  "$(printf '{"perspective":"%s","output_path":"%s"}' "<perspective>" "<path>")"
```

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":2,"name":"adversarial-panel","wall_ms":%d,"user_wait_ms":%d,"perspective_count":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE" "$PANEL_PERSPECTIVE_COUNT")"
```

---

## Phase 3 — Judge synthesis

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Dispatch research-judge

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The research-judge synthesizes panel perspectives into RESEARCH.md; drivers that skip it must warn the user that final synthesis is unavailable. -->
```
Agent(
  subagent_type="research-judge",
  description="Final synthesis judge for /z-research $SLUG",
  prompt="host_run_id: $RUN
slug: $SLUG
perspectives: $PERSPECTIVES_JSON
map_path: $Z_HARNESS_PLAN_DIR/MAP.md
brainstorm_path: $Z_HARNESS_PLAN_DIR/BRAINSTORM.md
output_schema_version: 1

Follow your agent definition. Return the full RESEARCH.md content in your STATUS/RESEARCH_CONTENT block."
)
```

### Step 2 — Parse judge return

Parse the structured return from research-judge:

```bash
JUDGE_STATUS="$(echo "$JUDGE_RETURN" | grep '^STATUS:' | head -1 | cut -d: -f2- | xargs)"
JUDGE_PERSPECTIVE_COUNT="$(echo "$JUDGE_RETURN" | grep '^PANEL_PERSPECTIVE_COUNT:' | head -1 | cut -d: -f2- | xargs)"
JUDGE_DEGRADED="$(echo "$JUDGE_RETURN" | grep '^PANEL_DEGRADED:' | head -1 | cut -d: -f2- | xargs)"
JUDGE_TEMPTATION="$(echo "$JUDGE_RETURN" | grep '^RESEARCH_JUDGE_TEMPTATION:' | head -1 | cut -d: -f2- | xargs)"
JUDGE_CONTENT="$(echo "$JUDGE_RETURN" | python3 -c "
import sys
content = sys.stdin.read()
start = content.find('RESEARCH_CONTENT:')
if start == -1:
    sys.exit(1)
# Everything after 'RESEARCH_CONTENT:\n'
body = content[start + len('RESEARCH_CONTENT:\n'):]
# Strip leading/trailing fenced code block markers if present
import re
body = re.sub(r'^```[^\n]*\n', '', body.strip())
body = re.sub(r'\n```$', '', body)
print(body)
")"
```

**Judge failure handling:**

If `JUDGE_STATUS=unable_to_complete` or `JUDGE_RETURN` is empty or malformed:
- Log `research_judge_failed`.
- Preserve all panel outputs at `archive/$RUN/panel/`.
- Push-notify the user with the failure reason.
- Surface to the user: "Judge synthesis failed. Panel outputs are preserved at `$Z_HARNESS_PLAN_DIR/archive/$RUN/panel/`. Re-invoke `/z-research` to retry, or inspect the panel outputs manually."
- Emit `run_end status: judge_failed` and exit.

### Step 3 — Compute source artifact metadata

```bash
MAP_SHA="$(git log -1 --format=%H -- "$Z_HARNESS_PLAN_DIR/MAP.md" 2>/dev/null || sha256sum "$Z_HARNESS_PLAN_DIR/MAP.md" | cut -d' ' -f1)"
MAP_GENERATED_AT="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f: content = f.read()
m = re.search(r'^generated_at:\s*(.+)$', content, re.MULTILINE)
print(m.group(1).strip() if m else '')
" "$Z_HARNESS_PLAN_DIR/MAP.md")"

BRAINSTORM_SHA="$(git log -1 --format=%H -- "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" 2>/dev/null || sha256sum "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" | cut -d' ' -f1)"
BRAINSTORM_GENERATED_AT="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f: content = f.read()
m = re.search(r'^generated_at:\s*(.+)$', content, re.MULTILINE)
print(m.group(1).strip() if m else '')
" "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md")"

GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Step 4 — Write RESEARCH.md atomically (tmp + rename)

Construct the frontmatter:

```bash
python3 - <<PYEOF
import json, os, sys

plan_dir          = os.environ['Z_HARNESS_PLAN_DIR']
slug              = os.environ['SLUG']
run               = os.environ['RUN']
topic             = os.environ['TOPIC']
arguments         = os.environ.get('ARGUMENTS', '')
dispatch_map      = os.environ['DISPATCH_MAP']
dispatch_brainstorm = os.environ['DISPATCH_BRAINSTORM']
map_sha           = os.environ['MAP_SHA']
map_generated_at  = os.environ['MAP_GENERATED_AT']
brainstorm_sha    = os.environ['BRAINSTORM_SHA']
brainstorm_generated_at = os.environ['BRAINSTORM_GENERATED_AT']
generated_at      = os.environ['GENERATED_AT']
judge_degraded    = os.environ.get('JUDGE_DEGRADED', 'false').lower() == 'true'
judge_temptation  = os.environ['JUDGE_TEMPTATION']
panel_perspective_count = int(os.environ.get('PANEL_PERSPECTIVE_COUNT', '3'))
judge_content     = os.environ['JUDGE_CONTENT']

# Build tripwires_fired list — populated in Phase 4; empty for now
tripwires_fired = []
if judge_degraded:
    tripwires_fired.append('research_panel_degraded')  # placeholder; Phase 4 finalizes

frontmatter = f"""---
artifact: research
artifact_kind: approach_synthesis
schema_version: 1
slug: {slug}
generated_at: {generated_at}
command: /z-research {arguments}
dispatch_decision:
  map: {dispatch_map}
  brainstorm: {dispatch_brainstorm}
source_artifacts:
  - path: MAP.md
    sha: {map_sha}
    generated_at: {map_generated_at}
  - path: BRAINSTORM.md
    sha: {brainstorm_sha}
    generated_at: {brainstorm_generated_at}
synthesizer_models:
  conservative: claude-opus
  expansive: codex (provider-resolved)
  adversarial: gemini (provider-resolved)
  judge: opus
panel_perspective_count: {panel_perspective_count}
panel_degraded: {str(judge_degraded).lower()}
status: complete
tripwires_fired: {json.dumps(tripwires_fired)}
---
"""

full_content = frontmatter + "\n" + judge_content + "\n"

# Atomic write: tmp then rename
tmp_path = os.path.join(plan_dir, "RESEARCH.md.tmp")
final_path = os.path.join(plan_dir, "RESEARCH.md")
with open(tmp_path, "w") as f:
    f.write(full_content)
os.replace(tmp_path, final_path)
print(f"wrote {final_path}")
PYEOF
```

### Step 5 — Emit research_judge_complete

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_judge_complete \
  "$(printf '{"slug":"%s","output_path":"%s","panel_perspective_count":%d,"panel_degraded":%s,"judge_temptation":"%s"}' \
     "$SLUG" "$Z_HARNESS_PLAN_DIR/RESEARCH.md" "$PANEL_PERSPECTIVE_COUNT" \
     "$([ "$JUDGE_DEGRADED" = "true" ] && echo "true" || echo "false")" \
     "$JUDGE_TEMPTATION")"
```

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":3,"name":"judge-synthesis","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 4 — Finalize

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Self-check RESEARCH.md

Validate that RESEARCH.md contains the required fields and sections:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/RESEARCH.md" <<'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    content = f.read()

errors = []

# Check frontmatter fields
required_frontmatter = [
    'artifact:', 'artifact_kind:', 'schema_version:', 'slug:',
    'generated_at:', 'command:', 'dispatch_decision:', 'source_artifacts:',
    'synthesizer_models:', 'status:',
]
for field in required_frontmatter:
    if not re.search(rf'^{re.escape(field)}', content, re.MULTILINE):
        errors.append(f"Missing frontmatter field: {field}")

# Check 10 required body sections
required_sections = [
    '## Approach decision matrix',
    '## Cross-artifact contradictions',
    '## Design axes',
    '## Terrain summary',
    '## Brainstorm frame space',
    '## High-leverage options',
    '## Rejected / weak framings',
    '## Evidence gaps',
    '## Adversarial perspectives summary',
    '## Mechanical rank-ordering',
]
for section in required_sections:
    if section not in content:
        errors.append(f"Missing section: {section}")

# Count matrix cells (rows × columns) — at least 1 non-header row required
matrix_section = re.search(
    r'## Approach decision matrix\n(.*?)(?=\n## |\Z)', content, re.DOTALL
)
if matrix_section:
    matrix_rows = [line for line in matrix_section.group(1).splitlines()
                   if line.strip().startswith('|') and '---' not in line
                   and not re.match(r'\|\s*Approach', line.strip())]
    if len(matrix_rows) == 0:
        errors.append("Approach decision matrix has no data rows")
    else:
        # Count UNVERIFIED cells vs total cells for tripwire
        all_cells = re.findall(r'\|\s*([^|\n]+)\s*(?=\|)', '\n'.join(matrix_rows))
        cell_verdicts = [c.strip() for c in all_cells if c.strip() and c.strip() != 'Approach']
        unverified_count = sum(1 for c in cell_verdicts if c.startswith('UNVERIFIED'))
        total_cells = len(cell_verdicts)
        print(f"matrix_rows={len(matrix_rows)} total_cells={total_cells} unverified={unverified_count}")

if errors:
    print("ERRORS: " + "; ".join(errors))
    sys.exit(1)
else:
    print("OK")
PYEOF
SELF_CHECK_STATUS=$?
```

If self-check exits nonzero: log `research_self_check_failed` with the errors, push-notify, surface to user. Do not delete RESEARCH.md — preserve it for debugging. Halt run.

### Step 2 — Automated tripwires

Parse matrix stats from the self-check output and fire tripwires as needed. Tripwires are advisory — they do NOT halt the run. They log events and surface warnings to the user.

**Tripwire 1: `research_high_unverified_rate`**

```bash
MATRIX_STATS="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(r'total_cells=(\d+) unverified=(\d+)', content)
if m:
    total = int(m.group(1))
    unverified = int(m.group(2))
    if total > 0 and (unverified / total) > 0.5:
        print('HIGH')
    else:
        print('OK')
else:
    print('UNKNOWN')
" "$Z_HARNESS_PLAN_DIR/RESEARCH.md")"

if [ "$MATRIX_STATS" = "HIGH" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_high_unverified_rate \
    "$(printf '{"slug":"%s","advisory":"over 50 percent of matrix cells are UNVERIFIED; consider re-running /z-map with a more refined topic"}' "$SLUG")"
  TRIPWIRES_FIRED="$TRIPWIRES_FIRED research_high_unverified_rate"
fi
```

**Tripwire 2: `research_panel_degraded`**

```bash
if [ "$PANEL_PERSPECTIVE_COUNT" -lt 3 ] 2>/dev/null; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_panel_degraded \
    "$(printf '{"slug":"%s","panel_perspective_count":%d,"advisory":"fewer than 3 perspectives available; inspect synthesis quality before consuming"}' \
       "$SLUG" "$PANEL_PERSPECTIVE_COUNT")"
  TRIPWIRES_FIRED="$TRIPWIRES_FIRED research_panel_degraded"
fi
```

**Tripwire 3: `research_judge_temptation`**

```bash
if [ -n "$JUDGE_TEMPTATION" ] && [ "$JUDGE_TEMPTATION" != "none" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_judge_temptation \
    "$(printf '{"slug":"%s","stripped_content":"%s","advisory":"synthesis layer attempted to add design recommendations; judge self-check stripped them; quality concern"}' \
       "$SLUG" "$(echo "$JUDGE_TEMPTATION" | head -c 200 | tr '"' "'")")"
  TRIPWIRES_FIRED="$TRIPWIRES_FIRED research_judge_temptation"
fi
```

### Step 3 — Update RESEARCH.md frontmatter with fired tripwires

If any tripwires fired, update the `tripwires_fired:` list in RESEARCH.md atomically:

```bash
if [ -n "$TRIPWIRES_FIRED" ]; then
  python3 - "$Z_HARNESS_PLAN_DIR/RESEARCH.md" "$TRIPWIRES_FIRED" <<'PYEOF'
import sys, re, os, json

path     = sys.argv[1]
fired    = sys.argv[2].strip().split()

with open(path) as f:
    content = f.read()

# Build the JSON array string
fired_json = json.dumps(fired)

# Replace the tripwires_fired: [] line
updated = re.sub(
    r'^tripwires_fired:.*$',
    f'tripwires_fired: {fired_json}',
    content,
    flags=re.MULTILINE
)

tmp = path + ".tmp"
with open(tmp, "w") as f:
    f.write(updated)
os.replace(tmp, path)
print(f"updated tripwires_fired: {fired_json}")
PYEOF
fi
```

### Step 4 — Post-launch tripwire notes

The following tripwires require N>1 production runs to evaluate (telemetry only; no automated action in v1):

- **T1:** `/z-plan` ignores constraint columns — manual review post-3-runs.
- **T2:** users expect code sketches — manual review post-feedback.
- **T3:** panel output redundant — manual review of first 3 panel outputs.
- **T4:** trivial synthesis — manual review of first 3 RESEARCH.md outputs.

If any of T1–T4 are observed post-run, a follow-up `/z-amend` proposes adjustments per PLAN.md Phase F.

### Step 5 — Push-notify + final message

```bash
if bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event run_complete | grep -q yes; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify.sh" \
    "/z-research complete: $SLUG" \
    "RESEARCH.md written to $Z_HARNESS_PLAN_DIR/RESEARCH.md. Panel: $PANEL_PERSPECTIVE_COUNT/3 perspectives. Tripwires: ${TRIPWIRES_FIRED:-none}."
fi
```

Output a final summary to the user:

```
/z-research complete — $SLUG

RESEARCH.md: $Z_HARNESS_PLAN_DIR/RESEARCH.md
Panel perspectives: $PANEL_PERSPECTIVE_COUNT / 3
Dispatch: MAP=$DISPATCH_MAP, BRAINSTORM=$DISPATCH_BRAINSTORM
Tripwires fired: ${TRIPWIRES_FIRED:-none}

Recommended next: /z-plan <task> — RESEARCH.md will be consumed as canonical precontext (one-way gate active when artifact_kind: approach_synthesis + status: complete).
```

### Step 6 — Emit run_end

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":4,"name":"finalize","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  "$(printf '{"slug":"%s","status":"complete","research_md_path":"%s","panel_perspective_count":%d,"tripwires_fired":%s}' \
     "$SLUG" "$Z_HARNESS_PLAN_DIR/RESEARCH.md" "$PANEL_PERSPECTIVE_COUNT" \
     "$(echo "$TRIPWIRES_FIRED" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read().split()))' || echo '[]')")"
```

---

## Invariants

1. New `/z-research` produces ONLY `artifact_kind: approach_synthesis`. Never writes MAP.md or BRAINSTORM.md content directly — sub-commands own those artifacts.
2. Synthesis (research-judge AND panel perspectives) FORBIDDEN from proposing new design recommendations. Only collision-flagging, rank-ordering by matrix counts, and evidence-gap surfacing are allowed.
3. Every approach decision matrix cell MUST have either a citation OR be marked `UNVERIFIED`. No silent gaps.
4. Cost gate (Phase 0.5) ALWAYS runs before Phase 1 dispatch. No silent execution at 3–6M token scale.
5. Sub-command dispatch in Phase 1 is inline (via Agent()) but each sub-run gets its own `archive/$RUN/subruns/<sub>/` symlink for the audit trail.
6. Adversarial synthesis panel = 3 vendor-diverse perspectives. Vendor assignment static: `general-purpose` (Opus) = conservative, `consultant-primary` = expansive, `consultant-secondary` = adversarial. Judge always Opus.
7. Tripwires (Phase 4) are advisory only — they log events and surface warnings but do NOT halt the run.
8. If MAP.md or BRAINSTORM.md is missing at Phase 2 start, halt immediately. Do not attempt synthesis without both source artifacts.
9. RESEARCH.md is written atomically (tmp + rename). A partial RESEARCH.md must never be left on disk.
10. Sub-command failure (Phase 1): abort current run; preserve partial artifacts; recommend user inspect + re-invoke. Do NOT attempt to fix the sub-command's failure inline.

## Error handling / edge cases

- **`/z-research` invoked with no topic:** AskUser gate in Setup Step 1. Never auto-invent a topic.
- **MAP.md exists but `artifact_kind` field missing** (pre-rename legacy file): treat as `artifact_kind: map` (old terrain map behavior). Log `legacy_map_artifact_detected`. This is relevant to MAP_STATE computation — a legacy file without frontmatter is treated as stale.
- **Sub-command failure mid-dispatch:** abort Phase 1; preserve partial artifacts; surface to user; do not retry inline.
- **Panel returns fewer than 3 perspectives (1/3 or 2/3 fail):** see Phase 2 failure semantics. Judge handles N<3 with `panel_degraded: true` in its return.
- **Judge failure or empty return:** halt Phase 3; preserve all panel outputs; surface to user.
- **`/z-plan` finds RESEARCH.md with corrupt frontmatter:** /z-plan falls back to component-file injection + warns user. This is /z-plan's responsibility; /z-research has no action.
- **Phase 0 loop-back from cost gate:** capped at 3 iterations before falling through to Abandon to prevent infinite dispatch/cost-gate cycling.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 1 Step 2 z-map; Phase 1 Step 3 z-brainstorm; Phase 2 Step 3 general-purpose + consultant-primary + consultant-secondary (panel, parallel); Phase 3 Step 1 research-judge |
| `ask_user` | yes | Setup Step 1 empty-topic question; Phase 0 Step 3 dispatch decision; Phase 0.5 Step 2 cost gate; Phase 2 Step 4 panel 2/3 failure decision |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
