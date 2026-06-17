---
inclusion: manual
description: Claim and execute the next pending follow-up entry from the project or global sink, with staleness check, lock management, and status writeback.
---

You are running **z-harness `/z-followup-next`**. Interactive consumer for one follow-up entry. Claims the highest-priority open entry (P0→P3, then oldest first), executes its recommended command, and writes back status.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Nest guard

Before doing anything else, check the caller-depth env var:

```bash
if [[ "${Z_HARNESS_FOLLOWUP_CALLER_DEPTH:-0}" -ge 1 ]]; then
  echo "Error: /z-followup-next cannot be invoked from within a running follow-up command." >&2
  echo "       (Z_HARNESS_FOLLOWUP_CALLER_DEPTH=${Z_HARNESS_FOLLOWUP_CALLER_DEPTH})" >&2
  exit 1
fi
```

This prevents recursive consumer nesting. Depth-1 entries (spawned by a consumer run) are intentionally excluded from the claimable set — they require human review.

## Phase 0 — Setup + lock check

Parse `$ARGUMENTS` first. Extract:

- `--sink=<project|global|both>` → `SINK_FILTER` (default `both`)
- `--force-dirty` → `FORCE_DIRTY` (default `false`)
- `--non-interactive` → `NON_INTERACTIVE` (default `false`)

If an unrecognized flag is present:

```
Error: unknown flag '<flag>'.
Usage: /z-followup-next [--sink=<project|global|both>] [--force-dirty] [--non-interactive]
```

Resolve canonical paths:

```bash
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)"
GLOBAL_SINK="${HOME}/.z-harness/followups"
GLOBAL_CROSS_TOOL_LOCK="${HOME}/.z-harness/.followup-vs-implement.lock"
mkdir -p "${HOME}/.z-harness"
```

### Phase 0.1 — Global cross-tool lock pre-check (heuristic only — NOT mutual-exclusion)

<!-- NOTE: This acquire-and-release probe is a HEURISTIC early-exit, NOT a mutual-exclusion
     guarantee. Acquiring and immediately releasing the lock proves nothing about concurrent
     access: a `/z-implement-*` process could acquire it immediately after we release it, and
     vice versa. The real mutual-exclusion guard for a claim is Phase 0.2 (running-entry check)
     combined with the atomic open → running transition in Phase 5 (sink-claim.sh). This probe
     exists only to give a fast, human-friendly error when /z-implement-* is actively running
     and has been holding the lock for several seconds. -->

Probe the global cross-tool lock to check if `/z-implement-*` is currently holding it. This is a try-acquire with immediate release, retried up to 5 s to tolerate brief contention from concurrent `sink-add` or `sink-claim` calls. We do NOT hold it after the probe succeeds; full acquire happens in Phase 5 (Claim).

```bash
GLOBAL_LOCK="$GLOBAL_CROSS_TOOL_LOCK"
LOCK_TIMEOUT_S=5
LOCK_RETRY_MS=200
ELAPSED_MS=0
HOLDER_ID="followup-next-$$"
while true; do
  if bash "$CLAUDE_PLUGIN_ROOT/scripts/sink-lock.sh" acquire "$GLOBAL_LOCK" "$HOLDER_ID" 2>/dev/null; then
    # Got it — release immediately; we only needed to confirm no /z-implement-* holds it
    bash "$CLAUDE_PLUGIN_ROOT/scripts/sink-lock.sh" release "$GLOBAL_LOCK" 2>/dev/null
    break
  fi
  if [ "$ELAPSED_MS" -ge $((LOCK_TIMEOUT_S * 1000)) ]; then
    echo "halt: global cross-tool lock held for >${LOCK_TIMEOUT_S}s; /z-implement-* may be running" >&2
    echo "Run /z-followup-status to inspect; retry later." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" followup_next_global_lock_timeout \
      "$(printf '{"timeout_s":%d}' "$LOCK_TIMEOUT_S")"
    exit 1
  fi
  sleep 0.2
  ELAPSED_MS=$((ELAPSED_MS + LOCK_RETRY_MS))
done
```

### Phase 0.2 — Check for running entries (project sink)

Even if the global lock is free, a running entry means another consumer is executing and may produce conflicting diffs:

```bash
PROJECT_VIEW="$PROJECT_SINK/index.view.json"
if [[ -f "$PROJECT_VIEW" ]]; then
  RUNNING_COUNT="$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    entries = data.get('entries', {})
    if isinstance(entries, dict):
        entries = list(entries.values())
    running = [e for e in entries if e.get('status') == 'running']
    print(len(running))
except Exception:
    print(0)
" "$PROJECT_VIEW" 2>/dev/null || echo 0)"
  if [[ "${RUNNING_COUNT:-0}" -gt 0 ]]; then
    echo "Error: $RUNNING_COUNT follow-up entr$([ "$RUNNING_COUNT" -eq 1 ] && echo y || echo ies) already running in project sink." >&2
    echo "Run /z-followup-status to see what is running. Wait for it to complete or dismiss it before retrying." >&2
    exit 1
  fi
fi
```

## Phase 1 — Enumerate + merge entries

Load entries from all in-scope sinks, merge, sort, and exclude non-claimable entries:

```bash
PROJECT_ENTRIES="$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/followup-view-lookup.py" \
  --mode=load \
  --view="$PROJECT_SINK/index.view.json" \
  --sink-label=project 2>/dev/null || echo '[]')"
GLOBAL_ENTRIES="$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/followup-view-lookup.py" \
  --mode=load \
  --view="$GLOBAL_SINK/index.view.json" \
  --sink-label=global 2>/dev/null || echo '[]')"

CLAIMABLE_JSON="$(python3 - "$PROJECT_ENTRIES" "$GLOBAL_ENTRIES" "$SINK_FILTER" <<'PYEOF'
import json, sys

project_entries = json.loads(sys.argv[1])
global_entries = json.loads(sys.argv[2])
sink_filter = sys.argv[3]

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

entries = []
if sink_filter in ("", "both", "project"):
    entries.extend(project_entries)
if sink_filter in ("", "both", "global"):
    entries.extend(global_entries)

# Claimable: status=open AND depth < 1 (depth==0 only; depth==1 entries stay inert)
claimable = [
    e for e in entries
    if e.get("status") == "open" and int(e.get("depth", 0)) < 1
]

# Sort: P0 first, then oldest created_at
claimable.sort(key=lambda e: (
    PRIORITY_ORDER.get(e.get("priority", "P3"), 99),
    e.get("created_at", "")
))

print(json.dumps(claimable))
PYEOF
)"
```

Extract count: `CLAIMABLE_COUNT`.

If `CLAIMABLE_COUNT == 0`:

```
No claimable follow-up entries found.
(Entries at depth=1 are excluded — they require human review via /z-followup-confirm.)
Run /z-followup-list to see all entries including non-claimable ones.
```

Exit cleanly (exit 0).

## Phase 2 — Present + select

Derive top-N list for display. `TOP_N` = configurable default 10:

```bash
TOP_N="${Z_HARNESS_FOLLOWUP_TOP_N:-10}"
```

Render a numbered summary of the top-N entries:

```bash
python3 - "$CLAIMABLE_JSON" "$TOP_N" <<'PYEOF'
import json, sys

entries = json.loads(sys.argv[1])
top_n = int(sys.argv[2])
shown = entries[:top_n]

print(f"\nClaimable follow-up entries ({len(entries)} total, showing top {min(top_n, len(entries))}):\n")
for i, e in enumerate(shown, 1):
    entry_id = e.get("id", "?")
    truncated_id = (entry_id[:40] + "...") if len(entry_id) > 43 else entry_id
    name = e.get("name", "?")
    truncated_name = (name[:60] + "...") if len(name) > 63 else name
    cmd = e.get("recommended_command", "?")
    truncated_cmd = (cmd[:60] + "...") if len(cmd) > 63 else cmd
    print(f"  [{i}] {e.get('priority','?')}  {truncated_name}")
    print(f"       ID: {truncated_id}")
    print(f"       sink={e.get('sink','?')}  created={e.get('created_at','?')[:10]}")
    print(f"       cmd: {truncated_cmd}")
    print()
PYEOF
```

If `NON_INTERACTIVE == true`, skip the AskUserQuestion gate — claim entry `[1]` (highest priority) automatically:

```bash
SELECTED_INDEX=1
```

Log the auto-selection:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_auto_selected \
  "$(printf '{"entry_id":"%s","mode":"non_interactive"}' "$SELECTED_ENTRY_ID")" 2>/dev/null || true
```

Otherwise, if `NON_INTERACTIVE == false`:

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the entry selection to the user via their native channel. Silent omission is forbidden. -->

Use `AskUserQuestion` with prompt:

```
Which follow-up entry would you like to work on?
Enter a number [1–N] to select, or 0 to exit.
```

Options: `"1"` through `"<N>"` (string labels from the numbered list above), plus `"0 — exit (do nothing)"`.

If user selects `0` (exit): print "Exiting — no entry claimed." and stop (exit 0).

Extract the selected entry from `CLAIMABLE_JSON` at index `SELECTED_INDEX - 1`. Store as `SELECTED_ENTRY` (full JSON object) and `SELECTED_ENTRY_ID`.

Also extract:
- `ENTRY_SINK_ROOT` = `$PROJECT_SINK` if `entry.sink == "project"` else `$GLOBAL_SINK`
- `ENTRY_LOCK_PATH` = `$ENTRY_SINK_ROOT/pages/$SELECTED_ENTRY_ID.lock`
- `ENTRY_RECOMMENDED_CMD` = entry's `recommended_command`
- `ENTRY_AUTO_CLOSE_ELIGIBLE` = entry's `auto_close_eligible` (true/false)
- `ENTRY_SAFE_TO_RETRY` = entry's `recommended_command_safe_to_retry` (true/false)
- `ENTRY_ATTEMPT_COUNT` = entry's `attempt_count` (integer)
- `ENTRY_CITED_PATHS` = entry's `cited_paths` (JSON array)
- `ENTRY_FILE_BLOB_HASHES` = entry's `file_blob_hashes` (JSON object, may be null)
- `ENTRY_DIR_BLOB_HASHES` = entry's `dir_blob_hashes` (JSON object, may be null)
- `ENTRY_CAPTURE_HEAD` = entry's `capture_head`

Generate run ID:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-followup-$(printf '%s' "$SELECTED_ENTRY_ID" | head -c 32)"
```

Create archive dir:

```bash
ARCHIVE_DIR="$ENTRY_SINK_ROOT/audit_evidence/$SELECTED_ENTRY_ID/$RUN_ID"
mkdir -p "$ARCHIVE_DIR"
```

## Phase 3 — Worktree check

```bash
GIT_PORCELAIN="$(git status --porcelain 2>/dev/null || echo "")"
```

If `GIT_PORCELAIN` is non-empty AND `FORCE_DIRTY == false`:

```
Error: working tree is dirty. Commit or stash changes before running /z-followup-next.
Use --force-dirty to proceed anyway (the diff will be captured for traceability).

Dirty files:
<GIT_PORCELAIN output>
```

Exit 1.

If `GIT_PORCELAIN` is non-empty AND `FORCE_DIRTY == true`:

Capture the pre-run diff:

```bash
git diff > "$ARCHIVE_DIR/pre-run.diff" 2>/dev/null || true
echo "Warning: --force-dirty set; pre-run diff captured to $ARCHIVE_DIR/pre-run.diff" >&2
```

## Phase 4 — Staleness check

Compute staleness drift for the selected entry's cited paths:

```bash
python3 - "$SELECTED_ENTRY" <<'PYEOF'
import hashlib, json, subprocess, sys, time, os
from datetime import datetime, timezone

entry = json.loads(sys.argv[1])
capture_head = entry.get("capture_head", "")
cited_paths = entry.get("cited_paths", [])
file_blob_hashes = entry.get("file_blob_hashes") or {}
dir_blob_hashes = entry.get("dir_blob_hashes") or {}
created_at = entry.get("created_at", "")

# Config: staleness thresholds (read from env or use defaults)
staleness_commit_window = int(os.environ.get("FOLLOWUP_STALENESS_COMMIT_WINDOW", "50"))
staleness_warn_days = int(os.environ.get("FOLLOWUP_STALENESS_WARN_DAYS", "30"))
staleness_hard_dismiss_days = int(os.environ.get("FOLLOWUP_STALENESS_HARD_DISMISS_DAYS", "0"))

drift_reasons = []
warn_reasons = []

# Commit distance check
if capture_head:
    result = subprocess.run(
        ["git", "rev-list", "--count", f"{capture_head}..HEAD"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        commit_dist = int(result.stdout.strip() or "0")
        if commit_dist > staleness_commit_window:
            drift_reasons.append(f"commit distance {commit_dist} > window {staleness_commit_window}")
    else:
        drift_reasons.append(f"capture_head {capture_head[:8]}.. not found in history")

# File blob hash check — recompute sha256: content hash and compare exactly
for path, expected_hash in file_blob_hashes.items():
    try:
        with open(path, "rb") as _fh:
            _file_bytes = _fh.read()
        current_hash = "sha256:" + hashlib.sha256(_file_bytes).hexdigest()
        # Unconditional: an empty/missing expected_hash is itself a mismatch (stale),
        # not a pass. Every captured entry must have a valid sha256: hash.
        if current_hash != expected_hash:
            drift_reasons.append(f"{path}: blob hash changed")
    except OSError:
        if path in cited_paths:
            drift_reasons.append(f"{path}: file not found or unreadable")

# Dir tree hash check — recompute sha256: tree hash and compare exactly
for ancestor, expected_tree_hash in dir_blob_hashes.items():
    result = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD", f"{ancestor}/"],
        capture_output=True, text=True
    )
    current_tree_hash = "sha256:" + hashlib.sha256(result.stdout.encode()).hexdigest()
    # Unconditional: an empty/missing expected_tree_hash is itself a mismatch (stale),
    # not a pass. Every captured entry must have a valid sha256: hash.
    if current_tree_hash != expected_tree_hash:
        drift_reasons.append(f"{ancestor}/: directory tree hash changed")

# Age warning
if created_at:
    try:
        ts = datetime.fromisoformat(created_at.rstrip("Z")).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - ts).days
        if staleness_hard_dismiss_days > 0 and age_days >= staleness_hard_dismiss_days:
            drift_reasons.append(f"entry age {age_days}d >= hard_dismiss_days {staleness_hard_dismiss_days}")
        elif age_days >= staleness_warn_days:
            warn_reasons.append(f"entry age {age_days}d >= warn_days {staleness_warn_days}")
    except (ValueError, AttributeError, TypeError):
        pass

result = {
    "drift": bool(drift_reasons),
    "drift_reasons": drift_reasons,
    "warn": bool(warn_reasons),
    "warn_reasons": warn_reasons,
}
print(json.dumps(result))
PYEOF
```

Store in `STALENESS_RESULT`. Extract `STALENESS_DRIFT` (true/false) and `STALENESS_WARN` (true/false).

If `STALENESS_WARN == true` AND `STALENESS_DRIFT == false`:

Print a soft warning to the conversation: "Note: this entry is older than the staleness warning threshold. Cited files may have changed context." Continue.

If `STALENESS_DRIFT == true`:

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the staleness prompt via their native channel. Silent omission is forbidden. -->

Use `AskUserQuestion` to prompt:

```
Staleness drift detected for entry '<SELECTED_ENTRY_ID>':

<drift_reasons joined by newline>

How would you like to proceed?
```

Options:
- `proceed — claim entry despite drift`
- `refresh — re-stamp capture_head and file_blob_hashes to current HEAD (entry stays open, you re-run /z-followup-next after)`
- `dismiss — dismiss this entry`

If user selects `refresh`:
- Call `scripts/sink-add.sh` is not the right tool here — instead, call `sink-status-set.sh` to transition to `blocked` with `reason=staleness_drift`, then advise user to run `/z-followup-refresh <entry-id>` to re-stamp hashes and reopen. Exit 0.

If user selects `dismiss`:
- Call `sink-status-set.sh --entry=$SELECTED_ENTRY_ID --to=dismissed --by=z-followup-next --reason=staleness_drift`.
- Print "Entry dismissed." and exit 0.

If user selects `proceed`:
- Set `ALLOW_STALE=true`. Continue.

Log the staleness event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_staleness_drift \
  "$(printf '{"entry_id":"%s","drift_reasons":%s,"action":"%s"}' \
     "$SELECTED_ENTRY_ID" "$DRIFT_REASONS_JSON" "$STALENESS_ACTION")" 2>/dev/null || true
```

## Phase 5 — Claim

Call `scripts/sink-claim.sh` to atomically transition the entry from `open → running`:

```bash
CLAIM_ARGS=(
  --entry="$SELECTED_ENTRY_ID"
  --run="$RUN_ID"
  --sink-root="$ENTRY_SINK_ROOT"
)
if [[ "${ALLOW_STALE:-false}" == "true" ]]; then
  CLAIM_ARGS+=(--allow-stale)
fi

CLAIM_TICKET="$(bash scripts/sink-claim.sh "${CLAIM_ARGS[@]}" 2>&1)"
CLAIM_EXIT=$?
```

Exit code handling:
- `0` → success. Parse `CLAIM_TICKET` as JSON; store `claim_ts` and `lock_path`.
- `3` → entry not claimable (status changed under us). Print "Entry is no longer open (status changed). Run /z-followup-list to see current state." and exit 1.
- `4` → staleness check failed inside claim script (edge case). Print the claim script's error and exit 1.
- `5` → lock timeout (contention). Print "Could not acquire lock — another process may be claiming this entry. Try again in a moment." and exit 1.
- any other non-zero → print `CLAIM_TICKET` (contains the error) and exit 1.

Log the claim:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_status_changed \
  "$(printf '{"entry_id":"%s","from":"open","to":"running","run_id":"%s"}' \
     "$SELECTED_ENTRY_ID" "$RUN_ID")" 2>/dev/null || true
```

### Spawn heartbeat loop

After a successful claim (exit 0 from sink-claim.sh), spawn a background heartbeat loop that refreshes the per-entry lock every 30 seconds so that stale-takeover logic does not reclaim the entry while the Skill is executing:

```bash
PER_ENTRY_LOCK="$ENTRY_LOCK_PATH"
(
  while true; do
    sleep 30
    bash "$CLAUDE_PLUGIN_ROOT/scripts/sink-lock.sh" heartbeat "$PER_ENTRY_LOCK" >/dev/null 2>&1 || break
  done
) &
HEARTBEAT_PID=$!
```

Install a trap so the heartbeat is killed and the lock is released on any abnormal exit (INT, TERM, or unexpected EXIT):

```bash
cleanup() {
  kill "$HEARTBEAT_PID" 2>/dev/null
  bash scripts/sink-lock.sh release "$ENTRY_LOCK_PATH" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
```

> **Invariant:** `HEARTBEAT_PID` must be captured before Phase 6 begins. The trap guarantees the heartbeat subprocess is always terminated — even if Phase 7 or Phase 8 raises an error — and the per-entry lock is always released.

## Phase 6 — Execute

Validate the `recommended_command` before executing. Structural parse per SPEC §Command allowlist:

```bash
python3 - "$ENTRY_RECOMMENDED_CMD" <<'PYEOF'
import re, shlex, sys

cmd = sys.argv[1]

# Rule 1: must start with /z- followed by kebab-case word
if not re.match(r'^/z-[a-z][a-z-]*[a-z](\s|$)', cmd) and not re.match(r'^/z-[a-z]{2}(\s|$)', cmd):
    print(json.dumps({"ok": False, "rule": 1, "reason": "command must start with /z-<kebab-case>"}))
    sys.exit(0)

# Rule 3: total length ≤ 2048
if len(cmd) > 2048:
    import json
    print(json.dumps({"ok": False, "rule": 3, "reason": "command length exceeds 2048 chars"}))
    sys.exit(0)

# Rule 4: no control characters (< 0x20 except space, or 0x7F)
import json
for ch in cmd:
    cp = ord(ch)
    if (cp < 0x20 and cp != 0x20) or cp == 0x7F:
        print(json.dumps({"ok": False, "rule": 4, "reason": f"control character U+{cp:04X} found"}))
        sys.exit(0)

# Rule 5: no NUL bytes
if '\x00' in cmd:
    print(json.dumps({"ok": False, "rule": 5, "reason": "NUL byte found"}))
    sys.exit(0)

# Rule 6: args with shell metacharacters must be quoted (parse via shlex)
try:
    tokens = shlex.split(cmd)
except ValueError as e:
    print(json.dumps({"ok": False, "rule": 6, "reason": f"shlex parse error: {e}"}))
    sys.exit(0)

SHELL_META = set(';|&`$>< \t\n')
for tok in tokens[1:]:  # skip the command name itself
    for ch in tok:
        if ch in SHELL_META:
            # This token has metacharacters but was returned as a single token by shlex,
            # meaning it was properly quoted.
            break

print(json.dumps({"ok": True}))
PYEOF
```

If validation fails, log `followup_unsafe_command` and halt:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_unsafe_command \
  "$(printf '{"entry_id":"%s","rejected_rule":%d,"reason":"%s"}' \
     "$SELECTED_ENTRY_ID" "$REJECTED_RULE" "$REJECTED_REASON")" 2>/dev/null || true
```

Then transition to `failed`:

```bash
bash scripts/sink-status-set.sh \
  --entry="$SELECTED_ENTRY_ID" \
  --to=failed \
  --by=z-followup-next \
  --reason="unsafe_command_rejected:rule_$REJECTED_RULE" \
  --via-claim-ticket="$CLAIM_TICKET" 2>/dev/null || true
```

Exit 1 with message: "Entry command failed safety validation (rule $REJECTED_RULE). Entry marked failed."

### Execute the command

The heartbeat loop (started in Phase 5) is alive and refreshing the per-entry lock every 30 seconds while execution proceeds. Set the depth env var and invoke the command via Skill tool. Parse out the skill name and args from `recommended_command` (strip the leading `/z-` prefix to get the skill ID `z-harness:z-<rest>`):

```bash
export Z_HARNESS_FOLLOWUP_CALLER_DEPTH=1
```

Map the command to a Skill invocation:
- Parse `ENTRY_RECOMMENDED_CMD`: first token is the command (e.g. `/z-do`), remainder is args.
- Map to `SKILL_ID = "z-harness:<command without leading />"` (e.g. `z-harness:z-do`).
- `SKILL_ARGS` = everything after the command token (the args string).

<!-- RUNTIME-GATE: skill_invoke; non-supporting drivers must surface this dispatch requirement to the user. The Skill call is the core execution step; drivers that skip it must warn that the follow-up command was not executed. -->

```
<!-- agent dispatch / skill invocation not supported in Kiro; see CAPABILITIES.md -->
```

After the Skill call returns (or raises), capture the diff:

```bash
unset Z_HARNESS_FOLLOWUP_CALLER_DEPTH
git diff > "$ARCHIVE_DIR/cumulative.diff" 2>/dev/null || true
DIFF_IS_EMPTY=false
if [[ ! -s "$ARCHIVE_DIR/cumulative.diff" ]]; then
  DIFF_IS_EMPTY=true
fi
```

If the Skill call raised an exception, capture `SKILL_EXIT_CODE=1` and `SKILL_ERROR_MSG`.

Otherwise `SKILL_EXIT_CODE=0`.

## Phase 7 — Status writeback

Determine the new status and write it back via `sink-status-set.sh`:

### exit == 0

Transition to `verify` regardless of diff size (true no-ops still verify):

```bash
bash scripts/sink-status-set.sh \
  --entry="$SELECTED_ENTRY_ID" \
  --to=verify \
  --by=z-followup-next \
  --via-claim-ticket="$CLAIM_TICKET"
```

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_status_changed \
  "$(printf '{"entry_id":"%s","from":"running","to":"verify","run_id":"%s","diff_empty":%s}' \
     "$SELECTED_ENTRY_ID" "$RUN_ID" "$DIFF_IS_EMPTY")" 2>/dev/null || true
```

Set `CURRENT_STATUS=verify`.

### exit != 0

Compute retry eligibility:

```bash
NEW_ATTEMPT_COUNT=$((ENTRY_ATTEMPT_COUNT + 1))
```

- If `ENTRY_SAFE_TO_RETRY == true` AND `NEW_ATTEMPT_COUNT < 3`:

  ```bash
  bash scripts/sink-status-set.sh \
    --entry="$SELECTED_ENTRY_ID" \
    --to=failed \
    --by=z-followup-next \
    --reason="command_exit_nonzero:retry_pending" \
    --via-claim-ticket="$CLAIM_TICKET"
  ```

  Print: "Entry marked failed (attempt $NEW_ATTEMPT_COUNT/3). safe_to_retry=true — you may re-run /z-followup-next to retry it."

- Otherwise (not retryable or attempt limit reached):

  ```bash
  bash scripts/sink-status-set.sh \
    --entry="$SELECTED_ENTRY_ID" \
    --to=failed \
    --by=z-followup-next \
    --reason="command_exit_nonzero:terminal" \
    --via-claim-ticket="$CLAIM_TICKET"
  ```

  Print: "Entry marked failed (terminal — needs human review). Run /z-followup-confirm or /z-followup-dismiss <entry-id>."

Set `CURRENT_STATUS=failed`.

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_status_changed \
  "$(printf '{"entry_id":"%s","from":"running","to":"failed","run_id":"%s","exit_code":%d,"attempt_count":%d}' \
     "$SELECTED_ENTRY_ID" "$RUN_ID" "$SKILL_EXIT_CODE" "$NEW_ATTEMPT_COUNT")" 2>/dev/null || true
```

## Phase 8 — Auto-close attempt

Only run if ALL of the following are true:
- `CURRENT_STATUS == verify`
- `ENTRY_AUTO_CLOSE_ELIGIBLE == true`
- `SKILL_EXIT_CODE == 0`

Invoke `scripts/sink-auto-close-check.py`:

```bash
ENTRY_TMP="$(mktemp /tmp/followup-entry-XXXXXX.json)"
printf '%s' "$SELECTED_ENTRY" > "$ENTRY_TMP"
AUTO_CLOSE_RESULT="$(python3 scripts/sink-auto-close-check.py \
  --entry="$ENTRY_TMP" \
  --diff="$ARCHIVE_DIR/cumulative.diff" \
  --test-exit="$SKILL_EXIT_CODE" \
  2>&1)"
AUTO_CLOSE_EXIT=$?
rm -f "$ENTRY_TMP"
```

If `AUTO_CLOSE_EXIT == 0` (auto-close ceiling passes):

```bash
bash scripts/sink-status-set.sh \
  --entry="$SELECTED_ENTRY_ID" \
  --to=done \
  --by=z-followup-next \
  --completion-mode=auto_closed_low_risk \
  --diff="$ARCHIVE_DIR/cumulative.diff" \
  --via-claim-ticket="$CLAIM_TICKET"
```

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_status_changed \
  "$(printf '{"entry_id":"%s","from":"verify","to":"done","completion_mode":"auto_closed_low_risk","run_id":"%s"}' \
     "$SELECTED_ENTRY_ID" "$RUN_ID")" 2>/dev/null || true
```

Print: "Entry auto-closed (auto_closed_low_risk). No human review required."

Set `CURRENT_STATUS=done`.

If `AUTO_CLOSE_EXIT != 0` (ceiling did not pass):

Print: "Auto-close ceiling not met. Entry remains at 'verify'. Run /z-followup-confirm <entry-id> --via=human to confirm manually."

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_auto_close_skipped \
  "$(printf '{"entry_id":"%s","reason":"%s"}' \
     "$SELECTED_ENTRY_ID" "$(printf '%s' "$AUTO_CLOSE_RESULT" | head -c 200)")" 2>/dev/null || true
```

## Phase 9 — Heartbeat thread shutdown + lock release

**Kill the heartbeat subprocess BEFORE releasing the per-entry lock.** This ordering ensures no heartbeat attempt races against a lock that has already been reclaimed by another process:

```bash
kill "$HEARTBEAT_PID" 2>/dev/null
```

Disable the EXIT trap that was installed in Phase 5 (we are doing the teardown explicitly now — the trap must not fire a second time at process exit):

```bash
trap - EXIT INT TERM
```

Release the per-entry lock:

```bash
bash scripts/sink-lock.sh release "$ENTRY_LOCK_PATH" 2>/dev/null || true
```

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "followup" followup_lock_released \
  "$(printf '{"entry_id":"%s","run_id":"%s","heartbeat_pid":%d}' "$SELECTED_ENTRY_ID" "$RUN_ID" "$HEARTBEAT_PID")" 2>/dev/null || true
```

## Phase 10 — Push-notify

Notify per policy:

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ] && \
  <PushNotification: "/z-followup-next: entry '$SELECTED_ENTRY_ID' → $CURRENT_STATUS. $([ "$CURRENT_STATUS" = "verify" ] && echo "Run /z-followup-confirm to finalize." || true)">
```

Print a brief summary to the conversation:

```
/z-followup-next complete
=========================
Entry:   <SELECTED_ENTRY_ID>
Name:    <entry name>
Sink:    <project|global>
Command: <ENTRY_RECOMMENDED_CMD>
Status:  <CURRENT_STATUS>
Run ID:  <RUN_ID>
Archive: <ARCHIVE_DIR>
```

If `CURRENT_STATUS == verify`:
```
Next step: run /z-followup-confirm <entry-id> --via=human  (or --via=audit with --evidence=<path>)
```

If `CURRENT_STATUS == failed`:
```
Next step: run /z-followup-status to inspect, or /z-followup-dismiss <entry-id> if no longer relevant.
```

---

## Invariants

- Nest guard fires before any other logic (`Z_HARNESS_FOLLOWUP_CALLER_DEPTH` check).
- Phase 0.1 lock probe is a **heuristic pre-check only** — it is NOT a mutual-exclusion guarantee. Acquire-and-release proves nothing about concurrent access. The real guard is Phase 0.2 (running-entry check) + the atomic `open → running` claim in Phase 5 (`sink-claim.sh`). The probe exists only for a fast user-facing error when `/z-implement-*` is actively holding the lock for multiple seconds.
- Global cross-tool lock is **not** held during command execution (Phase 6). It is held briefly only during `sink-claim.sh` (Phase 5) and `sink-status-set.sh` (Phases 7, 8).
- Per-entry lock is acquired by `sink-claim.sh` and held for the full duration of execution. Released in Phase 9 even if Phases 7 or 8 fail (best-effort release).
- **Heartbeat lifecycle:**
  - Spawned immediately after a successful `sink-claim.sh` acquire in Phase 5 as a bash background subprocess (`&`).
  - Calls `scripts/sink-lock.sh heartbeat <per-entry-lock>` every 30 seconds.
  - `HEARTBEAT_PID` is captured immediately; a `trap cleanup EXIT INT TERM` ensures the heartbeat is killed and the lock is released on any abnormal termination path.
  - Phase 6 (Skill execution) runs while the heartbeat subprocess is alive.
  - Phase 9 explicitly calls `kill $HEARTBEAT_PID 2>/dev/null` BEFORE the lock release call, then disables the trap. This ordering prevents a race between a stale heartbeat attempt and a newly-claimed lock.
  - If the heartbeat loop exits on its own (e.g. lock file removed externally), Phase 6 execution continues — it means the lock was already lost and Phase 9 will attempt a best-effort release.
- `Z_HARNESS_FOLLOWUP_CALLER_DEPTH=1` is set immediately before the Skill call and unset immediately after.
- Depth-1 entries (spawned during this command's execution) are excluded from the claimable set at Phase 1 (`depth < 1` filter).
- `recommended_command` structural validation runs before execution. Invalid commands transition to `failed` without execution.
- Auto-close (Phase 8) only fires when `auto_close_eligible == true` AND status is `verify` AND exit code was 0. Consumer cannot self-promote `verify → done` by any other path.
- Phase 9 (lock release) is always executed — even if Phases 7 or 8 produce errors.
- The `--non-interactive` flag skips Phase 2 user prompt; all other gates (worktree check, staleness prompt) still fire unless the `stdin` is absent, in which case `proceed` is the default for the staleness prompt in non-interactive mode. Hard-dismiss staleness fires regardless.
- Lock-ordering invariant: per-entry lock is acquired by `sink-claim.sh` before the global lock is briefly taken inside it. No code path inverts this order.

## Reference

- SPEC §commands/z-followup-next.md → `z-harness/notion-followup-sink/SPEC.md`
- SPEC §Concurrency model → `z-harness/notion-followup-sink/SPEC.md` §Concurrency model
- SPEC §State machine → `z-harness/notion-followup-sink/SPEC.md` §State machine
- SPEC §Command allowlist → `z-harness/notion-followup-sink/SPEC.md` §Command allowlist
- SPEC §Staleness check → `z-harness/notion-followup-sink/SPEC.md` §Staleness check
- SPEC §Auto-close consumer ceiling → `z-harness/notion-followup-sink/SPEC.md` §Auto-close consumer ceiling
- SPEC §Depth cap → `z-harness/notion-followup-sink/SPEC.md` §Depth cap

---

## Runtime contract conformance

| Feature        | Used | Gates                                                       |
|----------------|------|-------------------------------------------------------------|
| `subagent`     | no   | —                                                           |
| `ask_user`     | yes  | Phase 2 entry selection; Phase 4 staleness prompt           |
| `skill_invoke` | yes  | Phase 6 recommended_command execution                       |

Driver support requirements: see frontmatter `driver_features_required`.
