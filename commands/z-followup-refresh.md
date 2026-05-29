---
description: Refresh a blocked (staleness) follow-up entry — re-stamps capture_head and file_blob_hashes, then transitions back to open.
argument-hint: "<entry-id>"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-followup-refresh`**. Re-stamps a `blocked` follow-up entry with the current `capture_head` and re-computed `file_blob_hashes`, then transitions it back to `open`.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Nest guard

Before doing anything else, check the caller-depth env var:

```bash
if [[ "${Z_HARNESS_FOLLOWUP_CALLER_DEPTH:-0}" -ge 1 ]]; then
  echo "Error: /z-followup-refresh cannot be invoked from within a running follow-up command." >&2
  echo "       (Z_HARNESS_FOLLOWUP_CALLER_DEPTH=${Z_HARNESS_FOLLOWUP_CALLER_DEPTH})" >&2
  exit 1
fi
```

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- Positional `<entry-id>` — required. The follow-up entry ID to refresh.

If `<entry-id>` is missing:

```
Error: entry-id is required.
Usage: /z-followup-refresh <entry-id>
```

If an unrecognized flag is present:

```
Error: unknown flag '<flag>'.
Usage: /z-followup-refresh <entry-id>
```

Store: `ENTRY_ID`.

## Phase 1 — Resolve sink paths

```bash
PROJECT_SINK="$PWD/z-harness/followups"
PROJECT_VIEW="$PROJECT_SINK/index.view.json"
PROJECT_JSONL="$PROJECT_SINK/index.jsonl"

GLOBAL_SINK="${HOME}/.z-harness/followups"
GLOBAL_VIEW="$GLOBAL_SINK/index.view.json"
GLOBAL_JSONL="$GLOBAL_SINK/index.jsonl"

GLOBAL_CROSS_TOOL_LOCK="${HOME}/.z-harness/.followup-vs-implement.lock"
```

## Phase 2 — Locate the entry

Find which sink the entry lives in by searching both materialized views:

```bash
LOCATE_RESULT="$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/followup-view-lookup.py" \
  --mode=find \
  --id="$ENTRY_ID" \
  --project-view="$PROJECT_VIEW" \
  --global-view="$GLOBAL_VIEW")"
```

The result is stored in `LOCATE_RESULT`. If `found == false`:

```
Error: entry '<entry-id>' not found in project or global sink.
```

Exit 1.

Extract `ENTRY_STATUS`, `ENTRY_SINK`, and the full entry object.

## Phase 3 — State check

Verify the entry is in `blocked` state:

```bash
if [[ "$ENTRY_STATUS" != "blocked" ]]; then
  echo "Error: entry '$ENTRY_ID' is in status '$ENTRY_STATUS', not 'blocked'."
  echo "       /z-followup-refresh is only valid for entries blocked due to staleness."
  exit 1
fi
```

## Phase 4 — Resolve sink root and JSONL path

```bash
if [[ "$ENTRY_SINK" == "project" ]]; then
  SINK_ROOT="$PWD/z-harness/followups"
  SINK_JSONL="$PROJECT_JSONL"
else
  SINK_ROOT="${HOME}/.z-harness/followups"
  SINK_JSONL="$GLOBAL_JSONL"
fi
```

## Phase 5 — Re-compute capture_head and file_blob_hashes

Compute the new staleness metadata:

```bash
NEW_CAPTURE_HEAD="$(git rev-parse HEAD)"
```

Re-hash each file in the entry's `cited_paths`:

```bash
python3 - "$ENTRY_ID" "$SINK_ROOT/index.view.json" "$PWD" <<'PYEOF'
import hashlib, json, os, sys

entry_id, view_path, repo_root = sys.argv[1], sys.argv[2], sys.argv[3]

# Load entry to get cited_paths and existing hash type
try:
    with open(view_path) as f:
        data = json.load(f)
    entry = data.get("entries", {}).get(entry_id, {}) if isinstance(data, dict) else {}
except (json.JSONDecodeError, OSError, TypeError):
    entry = {}

# Determine which hash type was used: file_blob_hashes or dir_blob_hashes
uses_dir_hashes = bool(entry.get("dir_blob_hashes"))
cited_paths = entry.get("cited_paths", [])

if uses_dir_hashes:
    # Re-compute tree_hash for the stored ancestor directory
    ancestor = list(entry["dir_blob_hashes"].keys())[0] if entry.get("dir_blob_hashes") else ""
    if not ancestor:
        print(json.dumps({"error": "dir_blob_hashes has no ancestor key"}))
        sys.exit(0)
    import subprocess
    result = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD", ancestor + "/"],
        capture_output=True, text=True, cwd=repo_root
    )
    tree_text = result.stdout.encode()
    tree_hash = "sha256:" + hashlib.sha256(tree_text).hexdigest()
    print(json.dumps({
        "hash_type": "dir",
        "dir_blob_hashes": {ancestor: tree_hash},
        "file_blob_hashes": None,
    }))
else:
    # Re-hash each cited_path file
    new_hashes = {}
    errors = []
    for rel_path in cited_paths:
        abs_path = os.path.join(repo_root, rel_path)
        try:
            with open(abs_path, "rb") as f:
                content = f.read()
            new_hashes[rel_path] = "sha256:" + hashlib.sha256(content).hexdigest()
        except OSError as e:
            errors.append(f"{rel_path}: {e}")
    if errors:
        print(json.dumps({"error": "failed to hash cited_paths: " + "; ".join(errors)}))
    else:
        print(json.dumps({
            "hash_type": "file",
            "file_blob_hashes": new_hashes,
            "dir_blob_hashes": None,
        }))
PYEOF
```

Store in `REHASH_RESULT`. If `error` is present:

```
Error: could not re-compute file hashes: <error>
```

Exit 1.

## Phase 6 — Append entry_refreshed event and transition to open

Append an `entry_refreshed` event to the sink's `index.jsonl`, then invoke the status-set primitive to transition `blocked → open`.

**Lock-ordering invariant (MANDATORY):** acquire the per-entry lock FIRST, then the global cross-tool lock. This matches the ordering used everywhere else (`sink-claim.sh`, `sink-status-set.sh`) and prevents deadlock.

```bash
ENTRY_LOCK_PATH="$SINK_ROOT/pages/$ENTRY_ID.lock"
```

Step 1 — acquire the per-entry lock:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/sink-lock.sh" \
  acquire "$ENTRY_LOCK_PATH" "followup-refresh-$$"
ENTRY_LOCK_RC=$?
if [[ "$ENTRY_LOCK_RC" != "0" && "$ENTRY_LOCK_RC" != "2" ]]; then
  echo "Error: could not acquire per-entry lock for '$ENTRY_ID' (exit $ENTRY_LOCK_RC)." >&2
  exit 1
fi
```

Step 2 — under the per-entry lock, acquire the global lock and append the event:

The global cross-tool lock is acquired through the ONE shared helper in
`scripts/followup_common.py` (`acquire_global_lock` / `release_global_lock`) —
do NOT reimplement flock/holder/`.hb.lock` logic inline. Pass the scripts dir so
the helper is importable when this command runs from any cwd.

```bash
SCRIPTS_DIR="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts"
python3 - "$ENTRY_ID" "$SINK_ROOT" "$NEW_CAPTURE_HEAD" "$REHASH_RESULT" "$SCRIPTS_DIR" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

entry_id, sink_root, new_capture_head, rehash_json, scripts_dir = (
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
)
rehash = json.loads(rehash_json)

sys.path.insert(0, scripts_dir)
from followup_common import acquire_global_lock, release_global_lock  # noqa: E402

GLOBAL_LOCK_FILE = Path(os.environ.get(
    "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK",
    str(Path.home() / ".z-harness" / ".followup-vs-implement.lock"),
))
JSONL_PATH = os.path.join(sink_root, "index.jsonl")

# Acquire global cross-tool lock (per-entry lock already held by caller).
try:
    lock_fd = acquire_global_lock(GLOBAL_LOCK_FILE, f"followup-refresh-{os.getpid()}")
except TimeoutError:
    print(json.dumps({"error": "global cross-tool lock timeout (30s); try again"}))
    sys.exit(1)

try:
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = {
        "kind": "entry_refreshed",
        "ts": now_ts,
        "entry_id": entry_id,
        "new_capture_head": new_capture_head,
    }
    if rehash.get("hash_type") == "dir":
        event["new_dir_blob_hashes"] = rehash["dir_blob_hashes"]
    else:
        event["new_file_blob_hashes"] = rehash["file_blob_hashes"]

    # Append event atomically
    with open(JSONL_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")

    print(json.dumps({"ok": True, "ts": now_ts}))
finally:
    release_global_lock(lock_fd, GLOBAL_LOCK_FILE)
PYEOF
```

Store in `APPEND_RESULT`. If `error` is present, print it and release the per-entry lock, then exit 1:

```bash
if echo "$APPEND_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if not d.get('error') else 1)"; then
  : # success — continue to Phase 7
else
  echo "$APPEND_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error','unknown error'))" >&2
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/sink-lock.sh" release "$ENTRY_LOCK_PATH"
  exit 1
fi
```

## Phase 7 — Transition blocked → open

Invoke the status-set primitive (per-entry lock is still held from Phase 6; `sink-status-set.sh` will re-verify it before acquiring its own global lock):

```bash
bash "${PWD}/scripts/sink-status-set.sh" \
  --entry="$ENTRY_ID" \
  --to=open \
  --by=followup-refresh \
  --sink-root="$SINK_ROOT"
STATUS_SET_RC=$?
```

Release the per-entry lock (best-effort, regardless of status-set outcome):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/sink-lock.sh" release "$ENTRY_LOCK_PATH"
```

If `STATUS_SET_RC` is non-zero, print the error output and exit with that code.

## Phase 8 — Rebuild materialized view

The view rebuild is triggered internally by `sink-status-set.sh`. No additional rebuild is needed here.

## Phase 9 — Log and report

Log the event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "${Z_HARNESS_RUN:-followup-refresh}" \
  followup_status_changed \
  "$(python3 -c "
import json, sys
payload = {
    'entry_id': sys.argv[1],
    'from': 'blocked',
    'to': 'open',
    'by': 'followup-refresh',
    'new_capture_head': sys.argv[2],
}
print(json.dumps(payload))
" "$ENTRY_ID" "$NEW_CAPTURE_HEAD")"
```

Print:

```
Entry '<entry-id>' refreshed and returned to 'open'.
  New capture_head: <new-capture-head>
  Re-hashed <N> file(s).
```

(Use `N` = number of keys in `file_blob_hashes`, or `1 dir_blob_hash` if using directory hashes.)

---

## Invariants

- Only entries in `blocked` state may be refreshed by this command.
- `capture_head` is re-set to current `git rev-parse HEAD`.
- `file_blob_hashes` (or `dir_blob_hashes` for entries using directory-level hashing) is fully re-computed from the files' current content on disk.
- The `entry_refreshed` event is appended to `index.jsonl` **before** the `blocked → open` status transition.
- **Lock-ordering invariant:** the per-entry lock is acquired BEFORE the global cross-tool lock (same ordering as `sink-claim.sh` and `sink-status-set.sh`). The per-entry lock is held for the full duration of Phase 6 and Phase 7 and released after `sink-status-set.sh` completes.
- Nest guard fires before any other logic.

## Reference

- SPEC §commands/z-followup-refresh.md → `z-harness/notion-followup-sink/SPEC.md`
- SPEC §Staleness check → `z-harness/notion-followup-sink/SPEC.md` §Staleness check (at claim time)
- SPEC §State machine → `z-harness/notion-followup-sink/SPEC.md` §State machine (blocked → open)
- SPEC §Entry schema → `z-harness/notion-followup-sink/SPEC.md` §Entry schema (capture_head, file_blob_hashes)

---

## Runtime contract conformance

| Feature        | Used | Gates |
|----------------|------|-------|
| `subagent`     | no   | —     |
| `ask_user`     | no   | —     |
| `skill_invoke` | no   | —     |

Driver support requirements: see frontmatter `driver_features_required`.
