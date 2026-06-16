---
description: "Read-only diagnostic summary of the follow-up sink — counts per status, lock state, oldest open entry, and last sync failure."
role: workflow
---

You are running **z-harness `/z-followup-status`**. Read-only diagnostic. Reports entry counts per status, per-entry and global lock state, oldest open entry age, and the most recent Notion sync failure.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Nest guard

Before doing anything else, check the caller-depth env var:

```bash
if [[ "${Z_HARNESS_FOLLOWUP_CALLER_DEPTH:-0}" -ge 1 ]]; then
  echo "Error: /z-followup-status cannot be invoked from within a running follow-up command." >&2
  echo "       (Z_HARNESS_FOLLOWUP_CALLER_DEPTH=${Z_HARNESS_FOLLOWUP_CALLER_DEPTH})" >&2
  exit 1
fi
```

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- `--sink=<value>` — restrict reporting to one sink. Valid values: `project`, `global`, `both` (default `both`).

If an unrecognized flag is present:

```
Error: unknown flag '<flag>'.
Usage: /z-followup-status [--sink=<project|global|both>]
```

Store in `FILTER_SINK` (default `both`).

## Phase 1 — Resolve sink paths

```bash
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)"
PROJECT_VIEW="$PROJECT_SINK/index.view.json"
PROJECT_JSONL="$PROJECT_SINK/index.jsonl"
PROJECT_PAGES_DIR="$PROJECT_SINK/pages"

GLOBAL_SINK="${HOME}/.z-harness/followups"
GLOBAL_VIEW="$GLOBAL_SINK/index.view.json"
GLOBAL_JSONL="$GLOBAL_SINK/index.jsonl"
GLOBAL_PAGES_DIR="$GLOBAL_SINK/pages"

GLOBAL_CROSS_TOOL_LOCK="${HOME}/.z-harness/.followup-vs-implement.lock"
```

For each sink in scope (`FILTER_SINK`), check whether `index.view.json` exists. Absent or malformed views produce a warning rather than an error — the status command must always return some output.

## Phase 2 — Count entries per status

For each sink in scope, read `index.view.json` and tally entries by status:

```bash
python3 - "$PROJECT_VIEW" "$GLOBAL_VIEW" "$FILTER_SINK" <<'PYEOF'
import json, sys, os
from collections import Counter

project_path, global_path, filter_sink = sys.argv[1], sys.argv[2], sys.argv[3]

ALL_STATUSES = ["open", "running", "verify", "done", "failed", "blocked", "dismissed"]

def load_entries(path):
    if not os.path.exists(path):
        return None, "(view absent — run sink-view-rebuild.sh to materialise)"
    try:
        with open(path) as f:
            data = json.load(f)
        # index.view.json contains an "entries" dict keyed by entry-id
        # (see sink-view-reducer.py write_view — entries is a dict, not a list)
        if isinstance(data, dict):
            entries_obj = data.get("entries", {})
            entries = list(entries_obj.values()) if isinstance(entries_obj, dict) else entries_obj
        else:
            entries = data
        return entries, None
    except (json.JSONDecodeError, OSError, TypeError, AttributeError) as ex:
        return None, f"(view unreadable: {ex})"

results = {}

for label, path in [("project", project_path), ("global", global_path)]:
    if filter_sink not in ("both", label):
        continue
    entries, err = load_entries(path)
    if err:
        results[label] = {"error": err}
        continue
    counts = Counter(e.get("status", "unknown") for e in entries)
    results[label] = {
        "total": len(entries),
        "counts": {s: counts.get(s, 0) for s in ALL_STATUSES},
        "entries": entries,
    }

# Emit for later phases
print(json.dumps(results))
PYEOF
```

Store in `STATUS_DATA`.

## Phase 3 — Lock state

Check both lock files:

### Per-entry locks

Scan `pages/` directories for `*.lock` files. For each `.lock` file found, ALSO probe its corresponding `.lock.flock` sentinel with a non-blocking `LOCK_EX` attempt to determine whether the lock is actually held at the OS level:

```bash
python3 - "$PROJECT_PAGES_DIR" "$GLOBAL_PAGES_DIR" "$FILTER_SINK" <<'PYEOF'
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone

project_pages, global_pages, filter_sink = sys.argv[1], sys.argv[2], sys.argv[3]
held = []


def _iso_to_epoch(ts: str) -> int:
    """Parse ISO 8601 timestamp string (e.g. '2026-05-28T12:34:56Z') to epoch int."""
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def _probe_flock(flock_path: str) -> bool:
    """Return True if flock sentinel is held (non-blocking LOCK_EX fails).

    Returns False if the sentinel file does not exist (lock was never created
    or was cleaned up) or if acquisition succeeds (lock is free).
    """
    try:
        fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Acquired — lock is free; release immediately
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


for label, pages_dir in [("project", project_pages), ("global", global_pages)]:
    if filter_sink not in ("both", label):
        continue
    if not os.path.isdir(pages_dir):
        continue
    for fname in os.listdir(pages_dir):
        if not fname.endswith(".lock"):
            continue
        if fname.endswith(".flock"):
            continue  # skip the flock sentinel files themselves
        lock_path = os.path.join(pages_dir, fname)
        flock_path = lock_path + ".flock"

        # Determine actual OS-level held state via flock probe
        flock_held = _probe_flock(flock_path)

        try:
            with open(lock_path) as f:
                content = f.read().strip()
        except OSError:
            content = ""

        if not flock_held and not content:
            continue  # Definitively free

        lock_data = {}
        if content:
            try:
                lock_data = json.loads(content)
            except json.JSONDecodeError:
                pass

        # Determine effective held state: flock probe is authoritative; JSON body
        # may be absent/empty transiently even while flock is held.
        if not flock_held and not lock_data:
            continue

        entry_id = fname[:-5]  # strip .lock
        hb = lock_data.get("last_heartbeat", "") if lock_data else ""
        age_s = None
        stale = None
        if hb:
            try:
                age_s = int(time.time()) - _iso_to_epoch(hb)
                stale = age_s > 7200
            except (ValueError, TypeError, AttributeError, OverflowError):
                age_s = None
                stale = True  # unknown heartbeat → treat as potentially stale
        held.append({
            "sink": label,
            "entry_id": entry_id,
            "holder": lock_data.get("holder", "unknown") if lock_data else "unknown",
            "pid": lock_data.get("pid") if lock_data else None,
            "started_at": lock_data.get("started_at") if lock_data else None,
            "last_heartbeat_age_s": age_s,
            "stale": stale,
            "flock_held": flock_held,
        })

print(json.dumps(held))
PYEOF
```

Store in `PER_ENTRY_LOCKS`.

### Global cross-tool lock

Probe `$GLOBAL_CROSS_TOOL_LOCK.flock` with a non-blocking `LOCK_EX` attempt to determine the true OS-level lock state. The JSON body (`$GLOBAL_CROSS_TOOL_LOCK`) provides holder metadata when available but may be empty/absent transiently even while the flock is held:

```bash
python3 - "$GLOBAL_CROSS_TOOL_LOCK" <<'PYEOF'
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone

lock_path = sys.argv[1]
flock_path = lock_path + ".flock"


def _iso_to_epoch(ts: str) -> int:
    """Parse ISO 8601 timestamp string (e.g. '2026-05-28T12:34:56Z') to epoch int."""
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def _probe_flock(path: str) -> bool:
    """Return True if flock sentinel is held (non-blocking LOCK_EX fails).

    Returns False if the sentinel does not exist or acquisition succeeds.
    """
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


flock_held = _probe_flock(flock_path)

# Read JSON body for holder metadata (best-effort; may be empty/absent transiently)
lock_data = None
lock_file_exists = os.path.exists(lock_path) or os.path.exists(flock_path)
if os.path.exists(lock_path):
    try:
        with open(lock_path) as f:
            content = f.read().strip()
        if content:
            lock_data = json.loads(content)
    except (json.JSONDecodeError, OSError):
        pass

if not flock_held and not lock_file_exists:
    # Neither sentinel held nor any lock file present — lock was never created
    print(json.dumps({"state": "absent"}))
    sys.exit(0)

if not flock_held:
    # flock is free (JSON body may be empty or contain stale metadata)
    print(json.dumps({"state": "free"}))
    sys.exit(0)

# flock IS held — report as held, using JSON body for metadata when available
hb = lock_data.get("last_heartbeat", "") if lock_data else ""
age_s = None
stale = None
if hb:
    try:
        age_s = int(time.time()) - _iso_to_epoch(hb)
        stale = age_s > 7200
    except (ValueError, TypeError, AttributeError, OverflowError):
        age_s = None
        stale = True  # unknown heartbeat → treat as potentially stale

print(json.dumps({
    "state": "held",
    "holder": lock_data.get("holder", "unknown") if lock_data else "unknown",
    "pid": lock_data.get("pid") if lock_data else None,
    "started_at": lock_data.get("started_at") if lock_data else None,
    "last_heartbeat_age_s": age_s,
    "stale": stale,
}))
PYEOF
```

Store in `GLOBAL_LOCK_STATE`.

## Phase 4 — Oldest open entry

From the loaded entries in `STATUS_DATA`, find the oldest entry with `status == "open"` across all in-scope sinks:

```bash
python3 - "$STATUS_DATA" <<'PYEOF'
import json, sys
from datetime import datetime, timezone

data = json.loads(sys.argv[1])
oldest = None

for label, info in data.items():
    if "entries" not in info:
        continue
    for e in info["entries"]:
        if e.get("status") != "open":
            continue
        created_at = e.get("created_at", "")
        if not created_at:
            continue
        if oldest is None or created_at < oldest["created_at"]:
            oldest = {"id": e.get("id"), "name": e.get("name"), "created_at": created_at, "sink": label}

if oldest:
    try:
        ts = datetime.fromisoformat(oldest["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - ts).days
        oldest["age_days"] = age_days
    except (ValueError, AttributeError, TypeError, KeyError):
        oldest["age_days"] = None

print(json.dumps(oldest))
PYEOF
```

Store in `OLDEST_OPEN`.

## Phase 5 — Last sync failure

Read the last `followup_notion_sync_failure` event from `index.jsonl` for each in-scope sink:

```bash
python3 - "$PROJECT_JSONL" "$GLOBAL_JSONL" "$FILTER_SINK" <<'PYEOF'
import json, sys, os

project_jsonl, global_jsonl, filter_sink = sys.argv[1], sys.argv[2], sys.argv[3]

last_failures = {}

for label, jsonl_path in [("project", project_jsonl), ("global", global_jsonl)]:
    if filter_sink not in ("both", label):
        continue
    if not os.path.exists(jsonl_path):
        continue
    last_failure = None
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") == "followup_notion_sync_failure":
                    last_failure = event
    except OSError:
        pass
    if last_failure:
        last_failures[label] = last_failure

print(json.dumps(last_failures))
PYEOF
```

Store in `LAST_SYNC_FAILURES`.

## Phase 6 — Render report

Print a structured diagnostic report to stdout:

```
/z-followup-status
==================

Sinks in scope: project, global

## Entry counts

### project sink  (z-harness/followups/)
  open         3
  running      1
  verify       0
  done        12
  failed       0
  blocked      1
  dismissed    2
  ─────────────
  total       19
  ─────────────
  Notion sync pending: 1

### global sink  (~/.z-harness/followups/)
  (view absent — run sink-view-rebuild.sh to materialise)

## Lock state

Global cross-tool lock (~/.z-harness/.followup-vs-implement.lock):
  State: free

Per-entry locks held:
  20260528T123456Z-fix-stale-readme  [project]
    holder: z-followup-next / pid 12345
    started_at: 2026-05-28T12:34:56Z
    last heartbeat: 42s ago
    stale: no

## Oldest open entry

  ID:         20260101T000000Z-some-old-item
  Name:       Some old item
  Sink:       project
  Created:    2026-01-01T00:00:00Z
  Age:        147 days

## Last sync failure

  project: [none]
  global:  2026-05-27T08:00:00Z — entry 20260527T... (HTTP 502 Bad Gateway)
```

### Render logic

Use Python to format the above from the collected data variables. Each section is printed in order. If a section has no data (e.g., no per-entry locks held, no sync failures), print `(none)` rather than omitting the section.

```bash
python3 - "$STATUS_DATA" "$PER_ENTRY_LOCKS" "$GLOBAL_LOCK_STATE" "$OLDEST_OPEN" "$LAST_SYNC_FAILURES" "$FILTER_SINK" <<'PYEOF'
import json, sys

status_data    = json.loads(sys.argv[1])
per_entry      = json.loads(sys.argv[2])
global_lock    = json.loads(sys.argv[3])
oldest_open    = json.loads(sys.argv[4]) if sys.argv[4] != "null" else None
last_failures  = json.loads(sys.argv[5])
filter_sink    = sys.argv[6]

import os
from pathlib import Path

print("/z-followup-status")
print("==================")
sinks_shown = [s for s in ["project", "global"] if filter_sink in ("both", s)]
print(f"\nSinks in scope: {', '.join(sinks_shown)}")

# Entry counts
print("\n## Entry counts\n")
ALL_STATUSES = ["open", "running", "verify", "done", "failed", "blocked", "dismissed"]
for label in sinks_shown:
    if label == "project":
        path_hint = "z-harness/followups/"
    else:
        home = os.path.expanduser("~")
        path_hint = "~/.z-harness/followups/"
    print(f"### {label} sink  ({path_hint})")
    info = status_data.get(label, {})
    if "error" in info:
        print(f"  {info['error']}")
    else:
        counts = info.get("counts", {})
        for s in ALL_STATUSES:
            print(f"  {s:<12} {counts.get(s, 0)}")
        print(f"  {'─'*13}")
        print(f"  {'total':<12} {info.get('total', 0)}")
        notion_pending = sum(
            1 for e in info.get("entries", [])
            if e.get("notion_sync_pending", False)
        )
        print(f"  {'─'*13}")
        print(f"  Notion sync pending: {notion_pending}")
    print()

# Lock state
print("## Lock state\n")
gl = global_lock
gl_state = gl.get("state", "unknown")
print("Global cross-tool lock (~/.z-harness/.followup-vs-implement.lock):")
if gl_state == "absent":
    print("  State: absent (lock file never created — no followup activity yet)")
elif gl_state == "free":
    print("  State: free")
elif gl_state == "held":
    stale_val = gl.get("stale")
    if stale_val is True:
        stale_note = "  [STALE]"
    elif stale_val is None:
        stale_note = "  [STALE — heartbeat unknown]"
    else:
        stale_note = ""
    age_raw = gl.get("last_heartbeat_age_s")
    age_str = f"{age_raw}s ago" if age_raw is not None else "unknown"
    print(f"  State: held{stale_note}")
    print(f"  Holder: {gl.get('holder','?')} / pid {gl.get('pid','?')}")
    print(f"  Started: {gl.get('started_at','?')}")
    print(f"  Last heartbeat: {age_str}")
else:
    print(f"  State: {gl_state}  error={gl.get('error','?')}")
print()

print("Per-entry locks held:")
held = [e for e in per_entry if filter_sink in ("both", e.get("sink"))]
if not held:
    print("  (none)")
else:
    for lock in held:
        stale_val = lock.get("stale")
        if stale_val is True:
            stale_note = "  [STALE — possible dead holder]"
        elif stale_val is None:
            stale_note = "  [STALE — heartbeat unknown]"
        else:
            stale_note = ""
        age_raw = lock.get("last_heartbeat_age_s")
        age_str = f"{age_raw}s ago" if age_raw is not None else "unknown"
        print(f"  {lock['entry_id']}  [{lock['sink']}]{stale_note}")
        print(f"    holder: {lock.get('holder','?')} / pid {lock.get('pid','?')}")
        print(f"    started_at: {lock.get('started_at','?')}")
        print(f"    last heartbeat: {age_str}")
print()

# Oldest open entry
print("## Oldest open entry\n")
if oldest_open:
    age_str = f"{oldest_open['age_days']} days" if oldest_open.get("age_days") is not None else "unknown"
    print(f"  ID:      {oldest_open.get('id','?')}")
    print(f"  Name:    {oldest_open.get('name','?')}")
    print(f"  Sink:    {oldest_open.get('sink','?')}")
    print(f"  Created: {oldest_open.get('created_at','?')}")
    print(f"  Age:     {age_str}")
else:
    print("  (no open entries)")
print()

# Last sync failure
print("## Last sync failure\n")
for label in sinks_shown:
    failure = last_failures.get(label)
    if failure:
        ts = failure.get("ts", "?")
        entry_id = failure.get("entry_id", failure.get("payload", {}).get("entry_id", "?"))
        msg = failure.get("payload", {}).get("error", failure.get("error", "?"))
        print(f"  {label}: {ts} — entry {entry_id} ({msg})")
    else:
        print(f"  {label}: (none)")
PYEOF
```

---

## Invariants

- **Read-only.** Never writes to any file. Never acquires or modifies any lock.
- **No view rebuild.** Reports the current on-disk state. Stale or absent views produce a warning in the counts section, not an error exit.
- **No subagent dispatch.**
- Nest guard fires before any other logic (SPEC §Depth-cap / `Z_HARNESS_FOLLOWUP_CALLER_DEPTH`).
- Lock-file reads are best-effort: parse failure → report `unreadable` rather than crash.
- The report always completes all sections; missing data is noted inline as `(none)` or a warning.

## Reference

- SPEC §Persistence layout → `z-harness/notion-followup-sink/SPEC.md`
- SPEC §Concurrency model → `z-harness/notion-followup-sink/SPEC.md` §Concurrency model
- SPEC §Depth cap → `z-harness/notion-followup-sink/SPEC.md` §Depth cap

---

## Runtime contract conformance

| Feature        | Used | Gates |
|----------------|------|-------|
| `subagent`     | no   | —     |
| `ask_user`     | no   | —     |
| `skill_invoke` | no   | —     |

Driver support requirements: see frontmatter `driver_features_required`.
