#!/usr/bin/env bash
# Post-hoc liveness inspector. Scans a run's events.jsonl for `*_start` events
# that have no matching `*_end` event and reports them as "possibly stuck"
# subagents with elapsed wall time.
#
# Designed to be safe to run repeatedly from a second terminal while a /z-plan
# or /z-execute run is in flight. It is purely a reader — no events
# emitted, no orchestrator-flow changes, zero LLM token cost.
#
# Usage:
#   scripts/liveness.sh                       # latest run across all plans
#   scripts/liveness.sh --run RUN_ID          # specific run id
#   scripts/liveness.sh --slug SLUG           # latest run for a specific slug
#   scripts/liveness.sh --stale-seconds 600   # only flag entries older than N (default 300)
#   scripts/liveness.sh --all                 # include non-stale (just-started) entries
#
# Tail mode (from a second terminal): `watch -n 5 scripts/liveness.sh`
#
# Exit codes: 0 if no stuck subagents found; 1 if any flagged; 2 on usage error.

set -euo pipefail

STALE_SECONDS=300
SLUG=""
RUN=""
SHOW_ALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --run)            RUN="$2"; shift 2 ;;
    --slug)           SLUG="$2"; shift 2 ;;
    --stale-seconds)  STALE_SECONDS="$2"; shift 2 ;;
    --all)            SHOW_ALL=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "liveness.sh: unknown arg: $1" >&2
      exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Resolve base dir via plan-path.sh helper (DRY — no inline z-harness/ literals)
_ZH_PLAN_PATH_SH="$(dirname "$0")/plan-path.sh"
if [[ -f "$_ZH_PLAN_PATH_SH" ]]; then
  # shellcheck source=scripts/plan-path.sh
  source "$_ZH_PLAN_PATH_SH"
  _ZH_BASE="$(z_harness_base 2>/dev/null || echo "$REPO_ROOT/z-harness")"
else
  _ZH_BASE="${Z_HARNESS_BASE_DIR:-$REPO_ROOT/z-harness}"
fi
_ZH_ARCHIVE_DIR="$_ZH_BASE/archive"
PLANS_DIR="${Z_HARNESS_PLANS_DIR:-${_ZH_BASE}/plans}"
case "$PLANS_DIR" in
  /*) PLANS_ABS="$PLANS_DIR" ;;
  *)  PLANS_ABS="$REPO_ROOT/$PLANS_DIR" ;;
esac

# Collect candidate events.jsonl files based on flags. maxdepth 6 covers
# both run-scoped (plans/<slug>/archive/<run>/events.jsonl, depth 4 below
# PLANS_ABS) and task-scoped (plans/<slug>/archive/tasks/<task-id>/events.jsonl,
# depth 5) layouts.
CANDIDATES=()
if [ -n "$RUN" ]; then
  while IFS= read -r -d '' f; do CANDIDATES+=("$f"); done < <(
    find "$PLANS_ABS" "$_ZH_ARCHIVE_DIR" -maxdepth 6 -type f -name events.jsonl -path "*/$RUN/*" -print0 2>/dev/null
  )
elif [ -n "$SLUG" ]; then
  while IFS= read -r -d '' f; do CANDIDATES+=("$f"); done < <(
    find "$PLANS_ABS/$SLUG/archive" -maxdepth 5 -type f -name events.jsonl -print0 2>/dev/null
  )
else
  while IFS= read -r -d '' f; do CANDIDATES+=("$f"); done < <(
    find "$PLANS_ABS" "$_ZH_ARCHIVE_DIR" -maxdepth 6 -type f -name events.jsonl -print0 2>/dev/null
  )
fi

if [ ${#CANDIDATES[@]} -eq 0 ]; then
  echo "liveness.sh: no events.jsonl found under $PLANS_ABS or legacy archive" >&2
  exit 0
fi

# When no explicit --run was given, narrow to the single most-recently-modified
# events.jsonl. --slug also narrows so users don't see stale starts from old
# runs under the same slug.
if [ -z "$RUN" ]; then
  LATEST="$(ls -t "${CANDIDATES[@]}" 2>/dev/null | head -1)"
  CANDIDATES=("$LATEST")
fi

python3 - "$STALE_SECONDS" "$SHOW_ALL" "${CANDIDATES[@]}" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone

stale_seconds = int(sys.argv[1])
show_all = sys.argv[2] == "1"
files = sys.argv[3:]

# Lifecycle brackets — these always look "open" mid-run and are not signs of
# a stuck subagent. The subagent-level brackets we care about are implement,
# review, consult, audit, precheck, remote_verify, brainstorm, mr_review,
# doc_audit, etc. — anything not on this deny-list passes.
LIFECYCLE_BASES = {
    "run", "light_run", "user_wait", "phase",
    "brainstorm_run", "research_run", "debug_run",
}

# Some subagents emit a single post-call event (not a `*_end` pair) or use
# alternate end-markers. Map each non-standard end kind to the base whose
# `<base>_start` it closes. Standard `<base>_end` pairing is handled inline
# without needing an entry here.
END_KIND_TO_BASE = {
    "consult": "consult",            # consultant agents post-call summary
    "review": "review",              # reviewer agent post-call summary
    "task_done": "task",             # /z-execute task close
    "task_skip": "task",
    "task_halt": "task",
}

def parse_ts(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()

def match_key(base, ev):
    # Discriminators so distinct attempts/parallel calls don't close each other:
    #   - id      → per-task identifier
    #   - retry/cycle/attempt → distinct attempts at the same task
    #   - role    → consultant_primary vs consultant_secondary running in parallel
    tid = ev.get("id") or ""
    retry = ev.get("retry", ev.get("cycle", ev.get("attempt", "")))
    role = ev.get("role", "")
    return (base, tid, str(retry), role)

now = time.time()
any_flagged = False

for path in files:
    starts = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = ev.get("kind", "")
            base = None
            is_start = False
            if kind.endswith("_start"):
                base = kind[:-len("_start")]
                is_start = True
            elif kind.endswith("_end"):
                base = kind[:-len("_end")]
            elif kind in END_KIND_TO_BASE:
                base = END_KIND_TO_BASE[kind]
            else:
                continue

            if base in LIFECYCLE_BASES:
                continue

            if is_start:
                starts[match_key(base, ev)] = ev
            else:
                starts.pop(match_key(base, ev), None)

    if not starts:
        continue

    # Filter for stale (unless --all)
    rows = []
    for key, ev in starts.items():
        base, tid, _retry, role = key
        try:
            elapsed = int(now - parse_ts(ev["ts"]))
        except Exception:
            elapsed = -1
        if not show_all and (elapsed < stale_seconds or elapsed < 0):
            continue
        rows.append((base, tid, role, elapsed, ev))

    if not rows:
        continue

    any_flagged = True
    # Derive a friendly run label from the path
    parts = path.split(os.sep)
    try:
        run_label = parts[parts.index("archive") + 1]
    except (ValueError, IndexError):
        run_label = path
    print(f"\nRun: {run_label}")
    print(f"  events.jsonl: {path}")
    print(f"  possibly stuck (elapsed >= {stale_seconds}s):")
    for base, tid, role, elapsed, ev in sorted(rows, key=lambda r: -r[3]):
        tag = ""
        if tid:
            tag += f" [{tid}]"
        if role:
            tag += f" ({role})"
        print(f"    - {base}_start{tag}: {elapsed}s ago  (ts={ev['ts']})")

sys.exit(1 if any_flagged else 0)
PY
