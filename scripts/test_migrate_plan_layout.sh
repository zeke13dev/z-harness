#!/usr/bin/env bash
# test_migrate_plan_layout.sh — Integration tests for migrate-plan-layout.sh
#
# Run with:
#   bash scripts/test_migrate_plan_layout.sh
#
# Hermetic: every test creates a fresh tmp git repo for the SOURCE (its in-repo
# z-harness/ holds the legacy artifacts) and a separate tmp dir for the external
# TARGET base, passed via Z_HARNESS_BASE_DIR. Because Z_HARNESS_BASE_DIR is a
# tier-1 escape hatch it bypasses the .z-harness-base anchor entirely, so these
# tests never read/write the real anchor and never touch real data.
#
# Tests:
#   1. dry-run prints a manifest and changes nothing.
#   2. live-run barrier: a status:running record refuses migration (non-zero) and
#      moves nothing.
#   3. full scope: plans + archive + metrics.jsonl move to the external base;
#      followups skipped without --with-followups, moved with it.
#   4. refuse-on-conflict: a pre-existing non-empty target leaves the source
#      intact and warns.
#   5. safe-move: source changes mid-copy → that item aborts, source intact.
#   6. flat-TASKS without --slug → skipped with warning.
#   7. idempotent re-run → no-op (no errors, target unchanged).
#   8. empty z-harness/ removed only when empty.
#   9. metrics merge is crash-safe: re-running after a simulated crash (source not
#      removed) does NOT duplicate lines in the target.
#  10. dry-run --all manifest is COMPLETE: lists each plan slug, each archive run,
#      metrics.jsonl, and the followups skip note.
#  11. canonicalize guard: source==target (via symlink asymmetry) is detected as a
#      no-op; an unresolvable base aborts loudly.

set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATE="$SCRIPTS_DIR/migrate-plan-layout.sh"

PASS=0
FAIL=0

_tmpdir() { mktemp -d "/tmp/test_migrate_XXXXXX"; }

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"; echo "        expected: $expected"; echo "        actual:   $actual"; FAIL=$((FAIL + 1))
  fi
}
assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $label"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"; echo "        expected substring: $needle"; echo "        in: $haystack"; FAIL=$((FAIL + 1))
  fi
}
assert_file_exists() {
  local label="$1" path="$2"
  if [[ -f "$path" ]]; then echo "  PASS: $label"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — file not found: $path"; FAIL=$((FAIL + 1)); fi
}
assert_file_not_exists() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then echo "  PASS: $label"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — file unexpectedly exists: $path"; FAIL=$((FAIL + 1)); fi
}
assert_dir_exists() {
  local label="$1" path="$2"
  if [[ -d "$path" ]]; then echo "  PASS: $label"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — dir not found: $path"; FAIL=$((FAIL + 1)); fi
}
assert_dir_not_exists() {
  local label="$1" path="$2"
  if [[ ! -d "$path" ]]; then echo "  PASS: $label"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — dir unexpectedly exists: $path"; FAIL=$((FAIL + 1)); fi
}
assert_exit_nonzero() {
  local label="$1" code="$2"
  if [[ "$code" -ne 0 ]]; then echo "  PASS: $label (exit $code)"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — expected non-zero exit, got 0"; FAIL=$((FAIL + 1)); fi
}
assert_exit_zero() {
  local label="$1" code="$2"
  if [[ "$code" -eq 0 ]]; then echo "  PASS: $label"; PASS=$((PASS + 1));
  else echo "  FAIL: $label — expected exit 0, got $code"; FAIL=$((FAIL + 1)); fi
}

# new_repo: a fresh hermetic git repo (the SOURCE). Echoes its path.
new_repo() {
  local r; r="$(_tmpdir)"
  git -C "$r" init -q
  git -C "$r" config user.email "test@test.local"
  git -C "$r" config user.name "Test"
  echo "$r"
}

# seed_plan <repo> <slug> — create an in-repo legacy plan under z-harness/plans/<slug>.
seed_plan() {
  local repo="$1" slug="$2"
  mkdir -p "$repo/z-harness/plans/$slug"
  printf 'spec for %s\n' "$slug" > "$repo/z-harness/plans/$slug/SPEC.md"
  printf 'tasks for %s\n' "$slug" > "$repo/z-harness/plans/$slug/TASKS.md"
}

# run_migrate <repo> <base> -- <args...> : run migrate with cwd=repo and BASE_DIR=base.
# Writes combined stdout+stderr to global OUT and the exit code to global RC.
# (Must NOT be called inside $(...) — that would trap the RC assignment in a
# subshell and leave the parent's RC stale.)
RC=0
OUT=""
run_migrate() {
  local repo="$1" base="$2"; shift 2
  [[ "${1:-}" == "--" ]] && shift
  OUT="$(
    cd "$repo"
    Z_HARNESS_BASE_DIR="$base" bash "$MIGRATE" "$@" 2>&1
  )"
  RC=$?
}

# ---------------------------------------------------------------------------
# TEST-1: dry-run prints manifest, changes nothing.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-1: dry-run prints manifest, changes nothing"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
printf 'm1\n' > "$REPO/z-harness/metrics.jsonl"
run_migrate "$REPO" "$BASE" -- --dry-run --all
assert_exit_zero "TEST-1: dry-run exits 0" "$RC"
assert_contains "TEST-1: manifest mentions plan slug" "plan:alpha" "$OUT"
assert_contains "TEST-1: manifest mentions metrics.jsonl" "metrics.jsonl" "$OUT"
# Nothing moved: source intact, target empty.
assert_dir_exists "TEST-1: source plan dir still present" "$REPO/z-harness/plans/alpha"
assert_dir_not_exists "TEST-1: target plans dir NOT created" "$BASE/plans"
assert_file_not_exists "TEST-1: target metrics NOT created" "$BASE/metrics.jsonl"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-2: live-run barrier refuses migration and moves nothing.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-2: live-run barrier (status:running) refuses migration, moves nothing"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
# Plant a status:running registry record at <base>/active-plans/<run>.json.
mkdir -p "$BASE/active-plans"
cat > "$BASE/active-plans/live-run.json" <<'JSON'
{"schema_version":1,"run_id":"live-run","slug":"alpha","command":"/z-execute","phase":"implement","status":"running","last_heartbeat":"2026-06-01T00:00:00Z"}
JSON
run_migrate "$REPO" "$BASE" -- --all
assert_exit_nonzero "TEST-2: barrier causes non-zero exit" "$RC"
assert_contains "TEST-2: message names the live run" "live-run" "$OUT"
assert_contains "TEST-2: message mentions REFUSED/invariant 8" "REFUSED" "$OUT"
# Nothing moved.
assert_dir_exists "TEST-2: source plan dir intact" "$REPO/z-harness/plans/alpha"
assert_dir_not_exists "TEST-2: target plans dir NOT created" "$BASE/plans"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-3: full scope — plans + archive + metrics move; followups gated.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-3: full scope move; followups skipped without flag, moved with it"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
seed_plan "$REPO" "beta"
mkdir -p "$REPO/z-harness/archive/run-001"
printf 'evt\n' > "$REPO/z-harness/archive/run-001/events.jsonl"
printf 'mline\n' > "$REPO/z-harness/metrics.jsonl"
mkdir -p "$REPO/z-harness/followups"
printf 'fu\n' > "$REPO/z-harness/followups/queue.jsonl"

# First run WITHOUT --with-followups.
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-3: migration exits 0" "$RC"
assert_dir_exists "TEST-3: alpha moved to base" "$BASE/plans/alpha"
assert_dir_exists "TEST-3: beta moved to base" "$BASE/plans/beta"
assert_file_exists "TEST-3: alpha SPEC.md at target" "$BASE/plans/alpha/SPEC.md"
assert_dir_exists "TEST-3: archive run moved" "$BASE/archive/run-001"
assert_file_exists "TEST-3: archive events at target" "$BASE/archive/run-001/events.jsonl"
assert_file_exists "TEST-3: metrics moved to base" "$BASE/metrics.jsonl"
assert_dir_not_exists "TEST-3: source plans/alpha removed" "$REPO/z-harness/plans/alpha"
# followups skipped → source still there, target absent.
assert_dir_exists "TEST-3: followups NOT moved (source intact)" "$REPO/z-harness/followups"
assert_dir_not_exists "TEST-3: followups target NOT created" "$BASE/followups"
assert_contains "TEST-3: followups skip warned" "SKIP (followups)" "$OUT"

# Now migrate followups explicitly.
run_migrate "$REPO" "$BASE" -- --all --with-followups; OUT2="$OUT"
assert_exit_zero "TEST-3: followups migration exits 0" "$RC"
assert_dir_exists "TEST-3: followups moved with flag" "$BASE/followups"
assert_file_exists "TEST-3: followups queue at target" "$BASE/followups/queue.jsonl"
assert_dir_not_exists "TEST-3: source followups removed" "$REPO/z-harness/followups"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-4: refuse-on-conflict — pre-existing non-empty target left intact + warn.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-4: refuse-on-conflict leaves source intact and warns"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
# Pre-create a non-empty target for alpha.
mkdir -p "$BASE/plans/alpha"
printf 'pre-existing\n' > "$BASE/plans/alpha/EXISTING.md"
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-4: migration still exits 0 (skip, not fatal)" "$RC"
assert_contains "TEST-4: conflict warned (SKIP)" "SKIP (plan:alpha)" "$OUT"
assert_dir_exists "TEST-4: source plan dir left intact" "$REPO/z-harness/plans/alpha"
assert_file_exists "TEST-4: source SPEC.md intact" "$REPO/z-harness/plans/alpha/SPEC.md"
# Target NOT overwritten.
assert_file_exists "TEST-4: pre-existing target file untouched" "$BASE/plans/alpha/EXISTING.md"
assert_file_not_exists "TEST-4: source SPEC NOT copied over conflict" "$BASE/plans/alpha/SPEC.md"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-5: safe-move — source changes mid-copy → abort that item, source intact.
# ---------------------------------------------------------------------------
# We inject a fake `cp` early on PATH that performs the real copy and THEN mutates
# the source (touch + append), simulating a live writer appending during the copy
# window. The verify step must detect the source-mtime change and abort the item.
echo ""
echo "TEST-5: source changes mid-copy → item aborts, source intact"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
FAKEBIN="$(_tmpdir)"
REAL_CP="$(command -v cp)"
cat > "$FAKEBIN/cp" <<CPEOF
#!/usr/bin/env bash
# Fake cp: do the real copy, then mutate the SOURCE to simulate a mid-copy write.
"$REAL_CP" "\$@"
rc=\$?
# Last non-flag arg before the destination is the source for our 'cp -Rp SRC DST' call.
src=""
for a in "\$@"; do
  case "\$a" in -*) ;; *) prev="\$src"; src="\$a" ;; esac
done
# In 'cp -Rp SRC DST', the loop leaves src=DST; prev=SRC.
if [[ -d "\$prev" ]]; then
  # Bump the source tree mtime far into the future so the verify mismatch is unambiguous.
  find "\$prev" -type f -exec touch -t 203001010101 {} + 2>/dev/null || true
  touch -t 203001010101 "\$prev" 2>/dev/null || true
fi
exit \$rc
CPEOF
chmod +x "$FAKEBIN/cp"
OUT="$(
  cd "$REPO"
  PATH="$FAKEBIN:$PATH" Z_HARNESS_BASE_DIR="$BASE" bash "$MIGRATE" alpha 2>&1
)"
RC5=$?
assert_contains "TEST-5: item aborts on mid-copy change" "ABORT (plan:alpha)" "$OUT"
assert_contains "TEST-5: abort cites source changed mid-copy" "source changed mid-copy" "$OUT"
assert_dir_exists "TEST-5: source left intact after abort" "$REPO/z-harness/plans/alpha"
assert_file_exists "TEST-5: source SPEC intact after abort" "$REPO/z-harness/plans/alpha/SPEC.md"
assert_dir_not_exists "TEST-5: target NOT populated after abort" "$BASE/plans/alpha"
rm -rf "$REPO" "$BASE" "$FAKEBIN"

# ---------------------------------------------------------------------------
# TEST-6: flat TASKS.md without --slug → skipped with warning.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-6: flat TASKS.md without --slug skipped with warning"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
mkdir -p "$REPO/z-harness"
printf 'flat tasks\n' > "$REPO/z-harness/TASKS.md"
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-6: exits 0" "$RC"
assert_contains "TEST-6: flat-TASKS skip warned" "SKIP (flat-TASKS)" "$OUT"
assert_file_exists "TEST-6: flat TASKS.md left intact" "$REPO/z-harness/TASKS.md"
# With --slug it moves.
run_migrate "$REPO" "$BASE" -- --all --slug recovered; OUT2="$OUT"
assert_exit_zero "TEST-6: with --slug exits 0" "$RC"
assert_file_exists "TEST-6: flat TASKS migrated under slug" "$BASE/plans/recovered/TASKS.md"
assert_file_not_exists "TEST-6: source flat TASKS removed" "$REPO/z-harness/TASKS.md"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-7: idempotent re-run → no-op.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-7: idempotent re-run is a no-op"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
printf 'mline\n' > "$REPO/z-harness/metrics.jsonl"
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-7: first run exits 0" "$RC"
assert_dir_exists "TEST-7: alpha migrated" "$BASE/plans/alpha"
# Capture target metrics content after first run.
METRICS_AFTER_1="$(cat "$BASE/metrics.jsonl" 2>/dev/null || true)"
# Second run: nothing left in source → no-op.
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-7: re-run exits 0 (no-op)" "$RC"
assert_dir_exists "TEST-7: target still present after re-run" "$BASE/plans/alpha"
METRICS_AFTER_2="$(cat "$BASE/metrics.jsonl" 2>/dev/null || true)"
assert_eq "TEST-7: metrics not duplicated on re-run" "$METRICS_AFTER_1" "$METRICS_AFTER_2"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-8: empty z-harness/ removed only when empty.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-8: empty z-harness/ removed; residue keeps it"
# 8a: clean migration → source z-harness/ becomes empty → removed.
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
printf 'mline\n' > "$REPO/z-harness/metrics.jsonl"
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-8a: exits 0" "$RC"
assert_dir_not_exists "TEST-8a: empty z-harness/ removed" "$REPO/z-harness"
rm -rf "$REPO" "$BASE"

# 8b: residue (an un-migrated file) → z-harness/ kept + warned.
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
printf 'stray\n' > "$REPO/z-harness/UNRELATED.txt"   # not in migration scope
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-8b: exits 0" "$RC"
assert_dir_exists "TEST-8b: z-harness/ kept due to residue" "$REPO/z-harness"
assert_contains "TEST-8b: residue warned" "not empty after migration" "$OUT"
assert_file_exists "TEST-8b: residue file intact" "$REPO/z-harness/UNRELATED.txt"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-9: metrics merge is crash-safe — re-run after simulated crash (source not
#         removed) does NOT duplicate lines in the target.
# ---------------------------------------------------------------------------
# We simulate the crash window between the atomic mv-into-place and the rm of the
# source by running the merge once, then RESTORING the source file (as if the rm
# never happened) and running the merge again. A correct, idempotent merge must
# leave the target unchanged on the second run.
echo ""
echo "TEST-9: metrics merge crash-idempotency (no duplicate lines on re-run)"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
# Pre-existing target metrics so merge takes the append/dedup path (not fresh-move).
printf 'base-line-1\nbase-line-2\n' > "$BASE/metrics.jsonl"
mkdir -p "$REPO/z-harness"
printf 'src-line-A\nsrc-line-B\n' > "$REPO/z-harness/metrics.jsonl"
SRC_CONTENT="$(cat "$REPO/z-harness/metrics.jsonl")"
# First merge: source lines appended to target, source removed.
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-9: first merge exits 0" "$RC"
assert_file_not_exists "TEST-9: source metrics removed after merge" "$REPO/z-harness/metrics.jsonl"
MERGED_1="$(cat "$BASE/metrics.jsonl")"   # snapshot for the contains-checks below
assert_contains "TEST-9: target has base line after merge" "base-line-1" "$MERGED_1"
assert_contains "TEST-9: target has src line after merge" "src-line-A" "$MERGED_1"
# Count occurrences of a source line — must be exactly 1.
CNT_A_1="$(grep -cxF 'src-line-A' "$BASE/metrics.jsonl")"
assert_eq "TEST-9: src-line-A appears once after first merge" "1" "$CNT_A_1"
# Simulate the crash: source survived (rm never ran). Restore it verbatim. The
# first run's cleanup may have removed the now-empty in-repo z-harness/ dir, so
# recreate the parent before restoring the source file.
mkdir -p "$REPO/z-harness"
printf '%s\n' "$SRC_CONTENT" > "$REPO/z-harness/metrics.jsonl"
assert_file_exists "TEST-9: source restored for crash simulation" "$REPO/z-harness/metrics.jsonl"
# Re-run the merge — the source exists again, but the dedup must make it a no-op
# against the already-merged target (this is the real crash-recovery path).
run_migrate "$REPO" "$BASE" -- --all
assert_exit_zero "TEST-9: re-run merge exits 0" "$RC"
# The merge re-appends NOTHING from the source (dedup makes it a no-op): each
# source line — and each pre-existing base line — must still appear exactly once.
# (We assert per-line counts rather than full-file equality because the migration
# itself emits a plan_migrated event into the same base log on each run, which is
# expected churn unrelated to the metrics-merge idempotency under test.)
CNT_A_2="$(grep -cxF 'src-line-A' "$BASE/metrics.jsonl")"
assert_eq "TEST-9: src-line-A STILL appears once after crash re-run" "1" "$CNT_A_2"
CNT_B_2="$(grep -cxF 'src-line-B' "$BASE/metrics.jsonl")"
assert_eq "TEST-9: src-line-B appears once after crash re-run" "1" "$CNT_B_2"
CNT_BASE1="$(grep -cxF 'base-line-1' "$BASE/metrics.jsonl")"
assert_eq "TEST-9: base-line-1 still appears once (target not duplicated)" "1" "$CNT_BASE1"
CNT_BASE2="$(grep -cxF 'base-line-2' "$BASE/metrics.jsonl")"
assert_eq "TEST-9: base-line-2 still appears once (target not duplicated)" "1" "$CNT_BASE2"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-10: dry-run --all manifest completeness — lists every expected item.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-10: dry-run --all manifest lists all expected items"
REPO="$(new_repo)"; BASE="$(_tmpdir)"
seed_plan "$REPO" "alpha"
seed_plan "$REPO" "beta"
seed_plan "$REPO" "gamma"
mkdir -p "$REPO/z-harness/archive/run-001"
printf 'evt\n' > "$REPO/z-harness/archive/run-001/events.jsonl"
mkdir -p "$REPO/z-harness/archive/run-002"
printf 'evt\n' > "$REPO/z-harness/archive/run-002/events.jsonl"
printf 'mline\n' > "$REPO/z-harness/metrics.jsonl"
mkdir -p "$REPO/z-harness/followups"
printf 'fu\n' > "$REPO/z-harness/followups/queue.jsonl"
run_migrate "$REPO" "$BASE" -- --dry-run --all
assert_exit_zero "TEST-10: dry-run exits 0" "$RC"
# Each plan slug listed.
assert_contains "TEST-10: manifest lists plan:alpha" "plan:alpha" "$OUT"
assert_contains "TEST-10: manifest lists plan:beta" "plan:beta" "$OUT"
assert_contains "TEST-10: manifest lists plan:gamma" "plan:gamma" "$OUT"
# Plan slug count: exactly 3 distinct slugs present in the manifest.
SLUG_COUNT="$(printf '%s\n' "$OUT" | grep -oE 'plan:[a-z]+' | sort -u | wc -l | tr -d ' ')"
assert_eq "TEST-10: manifest lists exactly 3 distinct plan slugs" "3" "$SLUG_COUNT"
# Each archive run listed.
assert_contains "TEST-10: manifest lists archive:run-001" "archive:run-001" "$OUT"
assert_contains "TEST-10: manifest lists archive:run-002" "archive:run-002" "$OUT"
# metrics.jsonl presence.
assert_contains "TEST-10: manifest lists metrics.jsonl" "metrics.jsonl" "$OUT"
# followups skip note.
assert_contains "TEST-10: manifest notes followups skip" "followups" "$OUT"
assert_contains "TEST-10: manifest followups SKIP note" "SKIP: default" "$OUT"
# Nothing actually moved.
assert_dir_exists "TEST-10: source alpha intact" "$REPO/z-harness/plans/alpha"
assert_dir_not_exists "TEST-10: target plans NOT created" "$BASE/plans"
rm -rf "$REPO" "$BASE"

# ---------------------------------------------------------------------------
# TEST-11: canonicalize guard.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-11: canonicalize guard (symlink self-migration no-op; unresolvable base aborts)"
# 11a: base is a SYMLINK pointing at the in-repo z-harness/ dir. realpath asymmetry
#      (symlink base resolves to the literal source) must still be caught as
#      source==target → clean no-op, NOT a real migration.
REPO="$(new_repo)"; LINKDIR="$(_tmpdir)"
seed_plan "$REPO" "alpha"
SRC_REAL="$(cd "$REPO/z-harness" && pwd -P)"
ln -s "$SRC_REAL" "$LINKDIR/zlink"
OUT="$(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$LINKDIR/zlink" bash "$MIGRATE" --all 2>&1
)"
RC=$?
assert_exit_zero "TEST-11a: symlink-to-self exits 0 (no-op)" "$RC"
assert_contains "TEST-11a: reports nothing to migrate (no-op)" "nothing to migrate" "$OUT"
assert_dir_exists "TEST-11a: source plan untouched (no self-migration)" "$REPO/z-harness/plans/alpha"
rm -rf "$REPO" "$LINKDIR"

# 11b: base path is unresolvable (its parent does not exist) → abort loudly,
#      non-zero, without migrating.
REPO="$(new_repo)"
seed_plan "$REPO" "alpha"
BOGUS="/tmp/test_migrate_nope_$$/does/not/exist/base"
OUT="$(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BOGUS" bash "$MIGRATE" --all 2>&1
)"
RC=$?
assert_exit_nonzero "TEST-11b: unresolvable base aborts non-zero" "$RC"
assert_contains "TEST-11b: abort cites canonicalize failure" "could not canonicalize" "$OUT"
assert_dir_exists "TEST-11b: source plan untouched after abort" "$REPO/z-harness/plans/alpha"
rm -rf "$REPO"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -gt 0 ]] && exit 1
exit 0
