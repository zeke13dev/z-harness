#!/bin/bash
# migrate-plan-layout.sh — migrate in-repo z-harness/ artifacts to the resolved
# external artifact base (the directory returned by plan-path.sh base_dir).
#
# Usage:
#   migrate-plan-layout.sh [--dry-run] [--with-followups] [--slug NAME] <slug> | --all
#
# Modes:
#   <slug>            Migrate a single plan slug (legacy z-harness/<slug>/ and/or
#                     z-harness/plans/<slug>/ → <base>/plans/<slug>).
#   --all             Migrate the FULL artifact set: every plan slug, the global
#                     archive/ runs, metrics.jsonl, (optionally) followups/, and
#                     the flat TASKS.md (only with --slug). Removes the in-repo
#                     z-harness/ dir if it is empty afterwards.
#
# Flags:
#   --dry-run         Print the manifest of what WOULD move; change nothing.
#   --with-followups  Include z-harness/followups/ in the migration. DEFAULT: SKIP.
#                     Rationale: follow-up lock paths resolve dynamically via
#                     followups_dir(), so an in-repo followups/ keeps working until
#                     it is explicitly migrated. Migrating it while a queue is in
#                     use could strand locks, so it is opt-in.
#   --slug NAME       Provide the slug for the flat (no-slug) z-harness/TASKS.md so
#                     it can be migrated to <base>/plans/NAME. Without it, a flat
#                     TASKS.md is SKIPPED with a loud warning.
#
# LIVE-RUN BARRIER (SPEC invariant 8): BEFORE any move, this script calls
#   active-plan-registry.py list --json and REFUSES the entire migration (exit
#   non-zero) if ANY record has status:running. This prevents the TOCTOU where a
#   live run appends to a source file after copy-verify but before rm, and prevents
#   stranding in-flight followup locks.
#
# SAFE MOVE = copy -> verify -> rm, where verify = byte-for-byte equality AND the
#   source mtime is UNCHANGED since the copy started. If the source changed
#   mid-copy, the item is ABORTED (source left intact) and reported. The source is
#   only removed after verify passes.
#
# REFUSE-ON-CONFLICT: if a target path already exists and is non-empty, that item
#   is SKIPPED with a warning; the script NEVER overwrites. (metrics.jsonl is the
#   one exception: its lines are appended/merged into an existing target.)
#
# Idempotent: re-running is a no-op for items already migrated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/plan-path.sh
source "$SCRIPT_DIR/plan-path.sh"

DRY_RUN=0
WITH_FOLLOWUPS=0
ALL=0
FLAT_SLUG=""
POSITIONAL=()

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --with-followups) WITH_FOLLOWUPS=1; shift ;;
    --all) ALL=1; shift ;;
    --slug)
      if [[ $# -lt 2 ]]; then
        echo "Error: --slug requires an argument." >&2
        exit 2
      fi
      FLAT_SLUG="$2"; shift 2 ;;
    --slug=*) FLAT_SLUG="${1#--slug=}"; shift ;;
    --) shift; while [[ $# -gt 0 ]]; do POSITIONAL+=("$1"); shift; done ;;
    -*)
      echo "Error: unknown flag '$1'." >&2
      echo "Usage: $0 [--dry-run] [--with-followups] [--slug NAME] <slug> | --all" >&2
      exit 2 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done
set -- "${POSITIONAL[@]+"${POSITIONAL[@]}"}"

# ---------------------------------------------------------------------------
# Repo + base resolution
# ---------------------------------------------------------------------------
# Sources always live under the in-repo z-harness/ directory (the legacy layout),
# regardless of where the external base now resolves.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SRC_ROOT="$REPO_ROOT/z-harness"

# Resolve the external base (target). base_dir() may exit non-zero on anchor
# mismatch (invariant 7); guard against an empty/wrong base so we never migrate
# user data into the wrong place.
BASE=""
if ! BASE="$(base_dir 2>/dev/null)"; then
  echo "FATAL: could not resolve the external artifact base (plan-path.sh base_dir failed)." >&2
  echo "       Refusing to migrate — resolve the base anchor mismatch first." >&2
  exit 1
fi
if [[ -z "$BASE" ]]; then
  echo "FATAL: resolved external base is empty. Refusing to migrate." >&2
  exit 1
fi
if [[ "$BASE" != /* ]]; then
  echo "FATAL: resolved external base '$BASE' is not absolute. Refusing to migrate." >&2
  exit 1
fi

# canonicalize_path <path> <label> — forcibly resolve a path to its canonical
# absolute form. EXITS WITH ERROR (non-zero) if the path cannot be resolved; it
# never silently falls back to the literal path. This is load-bearing for the
# self-migration guard below: a silent fallback could make two equal paths look
# different (e.g. one resolves through a symlink and the other does not) and let
# the script migrate the in-repo z-harness/ onto itself.
#
# Resolution rule: if the path itself exists, realpath it directly (fully resolving
# symlinks). Otherwise the path's PARENT directory must exist — we realpath the
# parent (resolving symlinks there) and re-attach the leaf. If the parent does not
# exist, the path is unresolvable → abort. This means a fresh (not-yet-created)
# target base is fine (its parent exists) but a base under a missing parent dir
# aborts loudly instead of silently comparing literal strings.
canonicalize_path() {
  local path="$1" label="$2" resolved
  resolved="$(python3 - "$path" <<'PY' 2>/dev/null
import os, sys
p = os.path.abspath(sys.argv[1])
if os.path.exists(p):
    r = os.path.realpath(p)
else:
    parent = os.path.dirname(p)
    if not parent or not os.path.isdir(parent):
        sys.exit(1)
    r = os.path.join(os.path.realpath(parent), os.path.basename(p))
if not r or not os.path.isabs(r):
    sys.exit(1)
print(r)
PY
)" || resolved=""
  if [[ -z "$resolved" ]]; then
    echo "FATAL: could not canonicalize $label path: '$path'." >&2
    echo "       Refusing to migrate — cannot safely compare source and target" >&2
    echo "       (a silent fallback could mask a source==target self-migration)." >&2
    exit 1
  fi
  printf '%s\n' "$resolved"
}

# Refuse to migrate onto ourselves: if the resolved base IS the in-repo z-harness/
# directory, there is nothing to move (source == target). This is the stage-1
# default before the external-default flip; treat it as a clean no-op.
# Canonicalize BOTH paths (aborting loudly if either cannot resolve) so symlink /
# missing-dir asymmetry can never defeat the equality check.
SRC_ROOT_REAL="$(canonicalize_path "$SRC_ROOT" "source-root")"
BASE_REAL="$(canonicalize_path "$BASE" "external-base")"
if [[ "$SRC_ROOT_REAL" == "$BASE_REAL" ]]; then
  echo "Note: external base resolves to the in-repo z-harness/ dir ($BASE)."
  echo "      Source and target are identical — nothing to migrate (no-op)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Live-run barrier (invariant 8) — FIRST, before any move.
# ---------------------------------------------------------------------------
# detect_live_runs — echo a (possibly empty) list of LIVE (status:running) runs,
# one per line. EXITS WITH ERROR if liveness cannot be determined (a real move
# must not proceed under unknown liveness). The caller decides whether a non-empty
# result is a hard refusal (real move) or a warning (--dry-run).
detect_live_runs() {
  local list_json
  if ! list_json="$(python3 "$SCRIPT_DIR/active-plan-registry.py" list --json 2>/dev/null)"; then
    echo "FATAL: could not query the active-plan registry (live-run barrier)." >&2
    echo "       Refusing to migrate while liveness is unknown." >&2
    exit 1
  fi
  printf '%s' "$list_json" | python3 -c '
import json, sys
try:
    recs = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
if not isinstance(recs, list):
    sys.exit(0)
for r in recs:
    if isinstance(r, dict) and r.get("status") == "running":
        run_id = r.get("run_id", "?")
        slug = r.get("slug", "?")
        cmd = r.get("command", "?")
        print(f"  - run_id={run_id} slug={slug} cmd={cmd}")
' 2>/dev/null || true
}

# The barrier CHECK always runs (even on --dry-run) so previews are accurate.
# On a real move, a live run is a HARD REFUSAL (exit non-zero). On --dry-run, a
# live run is a WARNING printed alongside the preview, and the preview still runs
# (exit 0) — so users see exactly what a real migration WOULD refuse.
LIVE_RUNS="$(detect_live_runs)"
if [[ -n "$LIVE_RUNS" ]]; then
  if [[ "$DRY_RUN" -eq 0 ]]; then
    echo "REFUSED: a plan run is LIVE (status:running). Migration is blocked by invariant 8" >&2
    echo "         (no mutation of the base while a run is live). Live runs:" >&2
    echo "$LIVE_RUNS" >&2
    echo "         Wait for these runs to finish (or deregister stale ones) and retry." >&2
    exit 1
  fi
  # Dry-run: warn but continue to produce the preview.
  echo "NOTE: a plan run is LIVE (status:running) — a real migration would REFUSE"
  echo "      (invariant 8: no mutation of the base while a run is live). Live runs:"
  echo "$LIVE_RUNS"
  echo "      This is a dry-run, so the preview below is produced anyway."
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Portable max-mtime of a path (file or directory tree). Echoes an integer epoch.
# Walks the whole tree so any change to any descendant bumps the value.
_tree_mtime() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "0"
    return 0
  fi
  python3 - "$path" <<'PY'
import os, sys
p = sys.argv[1]
mx = 0
if os.path.isdir(p):
    for root, dirs, files in os.walk(p):
        for name in (root, *(os.path.join(root, d) for d in dirs), *(os.path.join(root, f) for f in files)):
            try:
                m = int(os.lstat(name).st_mtime)
            except OSError:
                continue
            if m > mx:
                mx = m
    try:
        m = int(os.lstat(p).st_mtime)
        if m > mx:
            mx = m
    except OSError:
        pass
else:
    try:
        mx = int(os.lstat(p).st_mtime)
    except OSError:
        mx = 0
print(mx)
PY
}

# Byte-for-byte equality of two paths (file or directory tree).
# Returns 0 if equal, 1 otherwise.
_byte_equal() {
  local a="$1" b="$2"
  if [[ -d "$a" || -d "$b" ]]; then
    diff -r "$a" "$b" >/dev/null 2>&1
  else
    cmp -s "$a" "$b"
  fi
}

# Is a directory empty (no entries, including hidden)? Returns 0 if empty.
_dir_empty() {
  local d="$1"
  [[ -d "$d" ]] || return 0
  local n
  n="$(find "$d" -mindepth 1 -maxdepth 1 2>/dev/null | head -1)"
  [[ -z "$n" ]]
}

# Does a target path exist and is non-empty (a file with content, or a non-empty dir)?
_target_occupied() {
  local t="$1"
  if [[ -d "$t" ]]; then
    ! _dir_empty "$t"
  elif [[ -f "$t" ]]; then
    [[ -s "$t" ]]
  else
    return 1
  fi
}

emit_event() {
  # emit_event <kind> <json-payload> [slug]
  local kind="$1" payload="$2" slug="${3:-}"
  [[ -x "$SCRIPT_DIR/log-event.sh" ]] || return 0
  local run_id="${Z_HARNESS_RUN_ID:-migration}"
  if [[ -n "$slug" ]]; then
    Z_HARNESS_SLUG="$slug" "$SCRIPT_DIR/log-event.sh" "$run_id" "$kind" "$payload" >/dev/null 2>&1 || true
  else
    "$SCRIPT_DIR/log-event.sh" "$run_id" "$kind" "$payload" >/dev/null 2>&1 || true
  fi
}

# safe_move <src> <dst> <slug-or-empty> <kind-label>
# copy -> verify(byte-equal AND src mtime unchanged) -> rm. Refuse-on-conflict.
# Idempotent: if src is absent, no-op. Returns 0 on success/skip/no-op,
# non-zero only on a hard error (never partial).
safe_move() {
  local src="$1" dst="$2" slug="$3" label="$4"

  # Idempotent: nothing to move.
  if [[ ! -e "$src" ]]; then
    return 0
  fi

  # Refuse-on-conflict.
  if _target_occupied "$dst"; then
    echo "SKIP ($label): target exists and is non-empty: $dst — leaving source intact: $src" >&2
    return 0
  fi

  # Capture source mtime BEFORE the copy starts.
  local mtime_before
  mtime_before="$(_tree_mtime "$src")"

  # Stage the copy next to the destination so a partial copy never lands at $dst.
  local dst_parent
  dst_parent="$(dirname "$dst")"
  mkdir -p "$dst_parent"
  local staging
  staging="$(mktemp -d "$dst_parent/.migrate-stage.XXXXXX")"
  local staged="$staging/payload"

  # Copy preserving timestamps/perms (-p) and recursively (-R).
  if ! cp -Rp "$src" "$staged" 2>/dev/null; then
    rm -rf "$staging"
    echo "ABORT ($label): copy failed for $src — source left intact." >&2
    return 0
  fi

  # Verify byte-equality of staged copy vs source.
  if ! _byte_equal "$src" "$staged"; then
    rm -rf "$staging"
    echo "ABORT ($label): byte-equality verify failed for $src — source left intact." >&2
    return 0
  fi

  # Verify source mtime is UNCHANGED since the copy started. If it changed, the
  # source was mutated mid-copy (e.g. a live run appended) — abort this item.
  local mtime_after
  mtime_after="$(_tree_mtime "$src")"
  if [[ "$mtime_before" != "$mtime_after" ]]; then
    rm -rf "$staging"
    echo "ABORT ($label): source changed mid-copy ($src; mtime $mtime_before -> $mtime_after) — source left intact." >&2
    return 0
  fi

  # Verify passed. Move staged payload into final place, then rm source.
  if ! mv "$staged" "$dst" 2>/dev/null; then
    rm -rf "$staging"
    echo "ABORT ($label): could not place staged copy at $dst — source left intact." >&2
    return 0
  fi
  rmdir "$staging" 2>/dev/null || rm -rf "$staging"

  rm -rf "$src"

  echo "MOVED ($label): $src -> $dst"
  emit_event "plan_migrated" \
    "$(printf '{"item":"%s","from":"%s","to":"%s"}' "$label" "$src" "$dst")" \
    "$slug"
  return 0
}

# merge_metrics <src-file> <dst-file>
# metrics.jsonl special case: append/merge lines if target exists; otherwise
# behave like safe_move for a fresh target. Always verifies the source mtime did
# not change while reading, and only removes the source after the merge is durable.
merge_metrics() {
  local src="$1" dst="$2"
  [[ -f "$src" ]] || return 0

  if [[ ! -e "$dst" ]]; then
    # Fresh target — same safe-move semantics as any file.
    safe_move "$src" "$dst" "" "metrics.jsonl"
    return 0
  fi

  # Target exists: append source lines. Capture mtime, append, re-check mtime.
  local mtime_before
  mtime_before="$(_tree_mtime "$src")"

  mkdir -p "$(dirname "$dst")"
  local tmp
  tmp="$(mktemp "$(dirname "$dst")/.metrics-merge.XXXXXX")"
  # Crash-safe / idempotent merge. The naive "cat dst src" duplicates the source
  # lines if a previous run crashed AFTER the atomic mv-into-place but BEFORE the
  # rm of the source (the source survives, so a re-run would append it again).
  # Instead we keep the existing target lines verbatim and append ONLY the source
  # lines that are NOT already present in the target. A second append therefore
  # contributes nothing — the merge becomes a no-op on re-run.
  if ! python3 - "$dst" "$src" "$tmp" <<'PY' 2>/dev/null
import sys
dst_path, src_path, tmp_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(dst_path, "r", encoding="utf-8", errors="surrogateescape") as f:
    dst_lines = f.readlines()
# Dedup is ONLY against the lines already present in the target. We do NOT dedup
# source lines against each other, so legitimate within-source repeats survive;
# we only suppress source lines that the target already contains (the crash /
# re-run case where the source was appended once and not yet removed).
present = set(dst_lines)
with open(src_path, "r", encoding="utf-8", errors="surrogateescape") as f:
    src_lines = f.readlines()
with open(tmp_path, "w", encoding="utf-8", errors="surrogateescape") as out:
    out.writelines(dst_lines)
    for line in src_lines:
        if line in present:
            continue  # already merged (crash-recovery / re-run): skip duplicate
        out.write(line)
PY
  then
    rm -f "$tmp"
    echo "ABORT (metrics.jsonl): merge dedup failed — source left intact." >&2
    return 0
  fi

  local mtime_after
  mtime_after="$(_tree_mtime "$src")"
  if [[ "$mtime_before" != "$mtime_after" ]]; then
    rm -f "$tmp"
    echo "ABORT (metrics.jsonl): source changed mid-merge ($src) — source left intact." >&2
    return 0
  fi

  if ! mv -f "$tmp" "$dst" 2>/dev/null; then
    rm -f "$tmp"
    echo "ABORT (metrics.jsonl): could not write merged target — source left intact." >&2
    return 0
  fi

  rm -f "$src"
  echo "MERGED (metrics.jsonl): $src -> $dst (appended)"
  emit_event "plan_migrated" \
    "$(printf '{"item":"metrics.jsonl","from":"%s","to":"%s","mode":"append"}' "$src" "$dst")"
  return 0
}

# Manifest line for dry-run.
manifest() {
  # manifest <label> <src> <dst>
  local label="$1" src="$2" dst="$3"
  [[ -e "$src" ]] || return 0
  local note=""
  if [[ "$label" == "metrics.jsonl" && -e "$dst" ]]; then
    note="  [append/merge into existing target]"
  elif _target_occupied "$dst"; then
    note="  [SKIP: target non-empty]"
  fi
  echo "  [$label] $src -> $dst$note"
}

# ---------------------------------------------------------------------------
# Item collectors — return source/target pairs for the chosen scope.
# ---------------------------------------------------------------------------

# Enumerate plan slugs present in the in-repo source tree (both layouts):
#   $SRC_ROOT/plans/<slug>/   and   $SRC_ROOT/<slug>/
# Excludes infrastructure names.
src_plan_slugs() {
  local -a INFRA=(plans archive adhoc followups improvements active-plans bench)
  _is_infra() {
    local name="$1" e
    for e in "${INFRA[@]}"; do [[ "$name" == "$e" ]] && return 0; done
    return 1
  }
  {
    if [[ -d "$SRC_ROOT/plans" ]]; then
      for d in "$SRC_ROOT/plans"/*/; do
        [[ -d "$d" ]] || continue
        local s; s="$(basename "$d")"
        _is_infra "$s" || printf '%s\n' "$s"
      done
    fi
    for d in "$SRC_ROOT"/*/; do
      [[ -d "$d" ]] || continue
      local s; s="$(basename "$d")"
      _is_infra "$s" || printf '%s\n' "$s"
    done
  } | sort -u
}

# Migrate a single plan slug (both legacy-flat and in-repo-plans sources collapse
# to the same canonical target <base>/plans/<slug>).
migrate_plan_slug() {
  local slug="$1"
  local target="$BASE/plans/$slug"
  local src_flat="$SRC_ROOT/$slug"
  local src_plans="$SRC_ROOT/plans/$slug"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    manifest "plan:$slug" "$src_plans" "$target"
    manifest "plan:$slug" "$src_flat" "$target"
    return 0
  fi

  # Prefer the in-repo plans/ layout if present; otherwise the flat one.
  if [[ -d "$src_plans" ]]; then
    safe_move "$src_plans" "$target" "$slug" "plan:$slug"
  fi
  # Only move the flat source if the canonical target is still free (i.e. the
  # plans/ source did not already populate it). safe_move's refuse-on-conflict
  # handles the case where both exist.
  if [[ -d "$src_flat" ]]; then
    safe_move "$src_flat" "$target" "$slug" "plan:$slug"
  fi
}

# Migrate the global archive runs: $SRC_ROOT/archive/<run>/ -> <base>/archive/<run>
migrate_archive() {
  [[ -d "$SRC_ROOT/archive" ]] || return 0
  for d in "$SRC_ROOT/archive"/*/; do
    [[ -d "$d" ]] || continue
    local run; run="$(basename "${d%/}")"
    local src="$SRC_ROOT/archive/$run"
    local dst="$BASE/archive/$run"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      manifest "archive:$run" "$src" "$dst"
    else
      safe_move "$src" "$dst" "" "archive:$run"
    fi
  done
}

# Migrate metrics.jsonl: $SRC_ROOT/metrics.jsonl -> <base>/metrics.jsonl (merge).
migrate_metrics() {
  local src="$SRC_ROOT/metrics.jsonl"
  local dst="$BASE/metrics.jsonl"
  [[ -f "$src" ]] || return 0
  if [[ "$DRY_RUN" -eq 1 ]]; then
    manifest "metrics.jsonl" "$src" "$dst"
  else
    merge_metrics "$src" "$dst"
  fi
}

# Migrate followups/ — ONLY with --with-followups.
migrate_followups() {
  local src="$SRC_ROOT/followups"
  local dst="$BASE/followups"
  [[ -d "$src" ]] || return 0
  if [[ "$WITH_FOLLOWUPS" -eq 0 ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "  [followups] $src -> $dst  [SKIP: default; pass --with-followups to include]"
    else
      echo "SKIP (followups): $src not migrated (default). Pass --with-followups to include." >&2
      echo "      Rationale: follow-up lock paths resolve dynamically via followups_dir();" >&2
      echo "      an in-repo followups/ keeps working until explicitly migrated." >&2
    fi
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    manifest "followups" "$src" "$dst"
  else
    safe_move "$src" "$dst" "" "followups"
  fi
}

# Migrate flat TASKS.md (no slug) — requires --slug NAME.
migrate_flat_tasks() {
  local src="$SRC_ROOT/TASKS.md"
  [[ -f "$src" ]] || return 0
  if [[ -z "$FLAT_SLUG" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "  [flat-TASKS] $src -> ???  [SKIP: needs --slug NAME]"
    else
      echo "SKIP (flat-TASKS): $src has no slug. Re-run with --slug NAME to migrate it." >&2
    fi
    return 0
  fi
  local dst="$BASE/plans/$FLAT_SLUG/TASKS.md"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    manifest "flat-TASKS" "$src" "$dst"
  else
    safe_move "$src" "$dst" "$FLAT_SLUG" "flat-TASKS"
  fi
}

# Remove the in-repo z-harness/ dir if empty after moves; warn on residue.
cleanup_src_root() {
  [[ -d "$SRC_ROOT" ]] || return 0
  if [[ "$DRY_RUN" -eq 1 ]]; then
    if _dir_empty "$SRC_ROOT"; then
      echo "  [cleanup] $SRC_ROOT would be removed (empty after moves)"
    else
      echo "  [cleanup] $SRC_ROOT would remain (residue present)"
    fi
    return 0
  fi
  # Prune now-empty intermediate dirs created by the legacy layout (plans/,
  # archive/) so an otherwise-empty z-harness/ can be removed. Only removes them
  # if they are empty; never recursive-deletes content.
  local sub
  for sub in plans archive followups; do
    if [[ -d "$SRC_ROOT/$sub" ]] && _dir_empty "$SRC_ROOT/$sub"; then
      rmdir "$SRC_ROOT/$sub" 2>/dev/null || true
    fi
  done

  if _dir_empty "$SRC_ROOT"; then
    rmdir "$SRC_ROOT" 2>/dev/null && echo "REMOVED: empty $SRC_ROOT" || true
  else
    echo "WARN: $SRC_ROOT not empty after migration — leaving in place. Residue:" >&2
    find "$SRC_ROOT" -mindepth 1 -maxdepth 2 2>/dev/null | sed 's/^/      /' >&2 || true
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

migrate_full() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== Migration manifest (dry-run) ==="
    echo "Source: $SRC_ROOT"
    echo "Target base: $BASE"
    echo ""
  fi

  local slug
  while IFS= read -r slug; do
    [[ -n "$slug" ]] || continue
    migrate_plan_slug "$slug"
  done < <(src_plan_slugs)

  migrate_archive
  migrate_metrics
  migrate_followups
  migrate_flat_tasks
  cleanup_src_root

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "=== End manifest (nothing changed) ==="
  fi
}

if [[ "$ALL" -eq 1 ]]; then
  migrate_full
elif [[ -n "${1:-}" ]]; then
  SLUG_ARG="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== Migration manifest (dry-run) ==="
    echo "Source: $SRC_ROOT"
    echo "Target base: $BASE"
    echo ""
  fi
  migrate_plan_slug "$SLUG_ARG"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "=== End manifest (nothing changed) ==="
  fi
else
  echo "Usage: $0 [--dry-run] [--with-followups] [--slug NAME] <slug> | --all" >&2
  exit 1
fi
