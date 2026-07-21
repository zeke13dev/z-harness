#!/usr/bin/env bash
# test_z_preflight.sh — Tests for scripts/z-preflight.sh
#
# Run with:
#   bash scripts/test_z_preflight.sh
#   make test-sh   (auto-discovered by the glob scripts/*test*.sh)
#
# Per-test isolation: every case pins Z_HARNESS_BASE_DIR to its own tmp dir
# so nothing here ever touches real user state.
#
# Tests:
#   TC01 — header documents env-var outputs and exit-code contract
#   TC02 — usage error: missing --command exits 2
#   TC03 — usage error: missing --slug exits 2
#   TC04 — success: stdout is eval-clean (every line is `export NAME=...`)
#   TC05 — success: exported vars RUN, Z_HARNESS_PLAN_DIR, CLAIM_HELD, REG_RC
#          (+ Z_HARNESS_SLUG, Z_HARNESS_SESSION_ID, KERNEL_PATH) are all set
#   TC06 — corrupt lock file → exit 11 (documented hard-stop code)
#   TC07 — Z_HARNESS_CLAIM_DISABLE=1 → CLAIM_HELD=0, no lock file created
#   TC08 — INTEGRATION (mandatory, acceptance-cited): fresh-shell eval sets
#          the documented env vars, exercises the slug-collision non-zero
#          branch (exit 10), then runs z-teardown.sh and asserts run-brief
#          finalize + claim release + deregister occurred (registry `list`
#          no longer shows the run; lock file gone).
#   TC09 — --no-claim (read-only commands, SKILL-STYLE.md §2): CLAIM_HELD=0,
#          no lock file created, registry still registers the run (REG_RC=0),
#          and a live writer holding the SAME slug does NOT block a --no-claim
#          run (proves plan-claim.sh acquire was never invoked for it).
#
# TC08's final free-state assertion is deterministic: z-teardown returns 0 only
# after plan-claim confirms the primitive release. An unconfirmed release is an
# operational nonzero and retains the registry record for a later retry.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
Z_PREFLIGHT="$SCRIPTS_DIR/z-preflight.sh"
Z_TEARDOWN="$SCRIPTS_DIR/z-teardown.sh"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"
PLAN_CLAIM="$SCRIPTS_DIR/plan-claim.sh"
REGISTRY_PY="$SCRIPTS_DIR/active-plan-registry.py"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Cleanup (file-based registry — command substitution subshells lose bash
# arrays, so we use a file the parent's EXIT trap can always see).
# ---------------------------------------------------------------------------
CLEANUP_REGISTRY="$(mktemp "${TMPDIR:-/tmp}/test_z_preflight_registry_XXXXXX")"
DAEMONS_AT_START="$(ps axww -o pid=,command= 2>/dev/null | grep 'signal.pause()' | awk '{print $1}' | sort -u)"
_cleanup_all() {
  [[ -f "$CLEANUP_REGISTRY" ]] || return 0
  while IFS= read -r d; do
    [[ -n "$d" ]] || continue
    while IFS= read -r lockf; do
      [[ -s "$lockf" ]] || continue
      pid="$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$lockf" 2>/dev/null | head -1)"
      [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
    done < <(find "$d" -type f -name '*.lock' ! -name '*.flock' ! -name '*.hb.lock' 2>/dev/null)
    [[ -d "$d" ]] && rm -rf "$d" 2>/dev/null || true
  done < "$CLEANUP_REGISTRY"
  rm -f "$CLEANUP_REGISTRY" 2>/dev/null || true

  while read -r pid _; do
    [[ -n "$pid" ]] || continue
    printf '%s\n' "$DAEMONS_AT_START" | grep -qx "$pid" && continue
    kill -KILL "$pid" 2>/dev/null || true
  done < <(ps axww -o pid=,command= 2>/dev/null \
            | grep 'signal.pause()' | grep -F 'test_z_preflight_' | awk '{print $1, $0}')
}
trap _cleanup_all EXIT

_tmpdir() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/test_z_preflight_XXXXXX")"
  printf '%s\n' "$d" >> "$CLEANUP_REGISTRY"
  printf '%s' "$d"
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
assert_rc() {
  local expected="$1" description="$2" actual="$3"
  if [[ "$actual" -eq "$expected" ]]; then
    printf '  PASS: %s (exit %s)\n' "$description" "$actual"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — expected exit %s, got %s\n' "$description" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s\n        expected: %s\n        actual:   %s\n' "$label" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s\n        expected substring: %s\n        in: %s\n' "$label" "$needle" "$haystack"
    FAIL=$((FAIL + 1))
  fi
}

assert_true() {
  local label="$1" cond="$2"
  if [[ "$cond" -eq 0 ]]; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

json_get() {
  python3 -c "
import json, sys
try:
    obj = json.loads(sys.argv[1])
    val = obj.get(sys.argv[2], '') if isinstance(obj, dict) else ''
    print(val if val is not None else '')
except Exception:
    print('')
" "$1" "$2" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# TC01 — header documents env-var outputs and exit-code contract
# ---------------------------------------------------------------------------
printf '\nTC01: header documents env-var outputs and exit-code contract\n'
HEADER="$(head -n 90 "$Z_PREFLIGHT")"
assert_contains "TC01: header mentions RUN" "RUN " "$HEADER"
assert_contains "TC01: header mentions Z_HARNESS_PLAN_DIR" "Z_HARNESS_PLAN_DIR" "$HEADER"
assert_contains "TC01: header mentions CLAIM_HELD" "CLAIM_HELD" "$HEADER"
assert_contains "TC01: header mentions REG_RC" "REG_RC" "$HEADER"
assert_contains "TC01: header documents 'Exit codes:'" "Exit codes:" "$HEADER"

# ---------------------------------------------------------------------------
# TC02 — usage error: missing --command exits 2
# ---------------------------------------------------------------------------
printf '\nTC02: missing --command exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --slug some-slug >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC02: missing --command" "$RC"
}

# ---------------------------------------------------------------------------
# TC03 — usage error: missing --slug exits 2
# ---------------------------------------------------------------------------
printf '\nTC03: missing --slug exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC03: missing --slug" "$RC"
}

# ---------------------------------------------------------------------------
# TC04 — success: stdout is eval-clean (every non-empty line is `export `)
# ---------------------------------------------------------------------------
printf '\nTC04: stdout is eval-clean on success\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc04-slug"
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$SLUG" 2>/dev/null)"
  BAD_LINES="$(printf '%s\n' "$OUT" | grep -v '^export ' | grep -v '^$' || true)"
  assert_eq "TC04: no non-export lines on stdout" "" "$BAD_LINES"

  # Cleanup: extract RUN from the output and release/deregister.
  RUN_LINE="$(printf '%s\n' "$OUT" | grep '^export RUN=')"
  eval "$RUN_LINE"
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC05 — success: documented env vars are all set
# ---------------------------------------------------------------------------
printf '\nTC05: exported vars RUN/Z_HARNESS_PLAN_DIR/CLAIM_HELD/REG_RC/... are all set\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc05-slug"
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$SLUG" 2>/dev/null)"

  assert_contains "TC05: RUN exported" "export RUN=" "$OUT"
  assert_contains "TC05: Z_HARNESS_SLUG exported" "export Z_HARNESS_SLUG=" "$OUT"
  assert_contains "TC05: Z_HARNESS_PLAN_DIR exported" "export Z_HARNESS_PLAN_DIR=" "$OUT"
  assert_contains "TC05: Z_HARNESS_SESSION_ID exported" "export Z_HARNESS_SESSION_ID=" "$OUT"
  assert_contains "TC05: CLAIM_HELD exported" "export CLAIM_HELD=" "$OUT"
  assert_contains "TC05: REG_RC exported" "export REG_RC=" "$OUT"
  assert_contains "TC05: KERNEL_PATH exported" "export KERNEL_PATH=" "$OUT"

  RUN_LINE="$(printf '%s\n' "$OUT" | grep '^export RUN=')"
  eval "$RUN_LINE"
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC06 — corrupt lock file → exit 11
# ---------------------------------------------------------------------------
printf '\nTC06: corrupt lock file causes hard-stop exit 11\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc06-slug"
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  mkdir -p "$CLAIMS_DIR"
  printf 'NOT VALID JSON\n' > "$CLAIMS_DIR/${SLUG}.lock"

  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$SLUG" >/dev/null 2>/dev/null || RC=$?
  assert_rc 11 "TC06: corrupt lock hard-stop" "$RC"

  rm -f "$CLAIMS_DIR/${SLUG}.lock" "$CLAIMS_DIR/${SLUG}.lock.flock" "$CLAIMS_DIR/${SLUG}.lock.hb.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# TC07 — Z_HARNESS_CLAIM_DISABLE=1 → CLAIM_HELD=0, no lock file created
# ---------------------------------------------------------------------------
printf '\nTC07: Z_HARNESS_CLAIM_DISABLE=1 -> CLAIM_HELD=0, no lock file\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc07-slug"
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_CLAIM_DISABLE=1 bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$SLUG" 2>/dev/null)"
  assert_contains "TC07: CLAIM_HELD=0" "export CLAIM_HELD=0" "$OUT"

  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  if [[ -f "$CLAIMS_DIR/${SLUG}.lock" ]]; then
    printf '  FAIL: TC07: lock file was created despite CLAIM_DISABLE=1\n'
    FAIL=$((FAIL + 1))
  else
    printf '  PASS: TC07: no lock file created with CLAIM_DISABLE=1\n'
    PASS=$((PASS + 1))
  fi

  RUN_LINE="$(printf '%s\n' "$OUT" | grep '^export RUN=')"
  eval "$RUN_LINE"
  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_CLAIM_DISABLE=1 bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC08 — MANDATORY end-to-end integration fixture (acceptance-cited).
#
# Fresh-shell eval of z-preflight.sh output, asserts the documented env
# vars, exercises the slug-collision non-zero exit branch, then runs
# z-teardown.sh and asserts run-brief finalize + claim release + deregister
# occurred (registry list no longer shows the run; lock file gone).
# ---------------------------------------------------------------------------
printf '\nTC08: INTEGRATION — preflight eval + slug-collision branch + teardown cleanup\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc08-integration-slug"

  # --- Step 1: fresh-shell eval; assert documented env vars are set ---
  # BSD mktemp (macOS) only substitutes a trailing XXXXXX sequence; a suffix
  # leaves the template literal and makes repeated runs collide.
  EVAL_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/test_z_preflight_eval_XXXXXX")"
  cat > "$EVAL_SCRIPT" <<EOF
set -euo pipefail
export Z_HARNESS_BASE_DIR="$tmp"
eval "\$(bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$SLUG")"
printf 'RUN=%s\n' "\$RUN"
printf 'Z_HARNESS_PLAN_DIR=%s\n' "\$Z_HARNESS_PLAN_DIR"
printf 'CLAIM_HELD=%s\n' "\$CLAIM_HELD"
printf 'REG_RC=%s\n' "\$REG_RC"
EOF
  FRESH_OUT="$(bash "$EVAL_SCRIPT" 2>&1)"
  rm -f "$EVAL_SCRIPT"

  RUN_VAL="$(printf '%s\n' "$FRESH_OUT" | sed -n 's/^RUN=//p')"
  PLAN_DIR_VAL="$(printf '%s\n' "$FRESH_OUT" | sed -n 's/^Z_HARNESS_PLAN_DIR=//p')"
  CLAIM_HELD_VAL="$(printf '%s\n' "$FRESH_OUT" | sed -n 's/^CLAIM_HELD=//p')"
  REG_RC_VAL="$(printf '%s\n' "$FRESH_OUT" | sed -n 's/^REG_RC=//p')"

  if [[ -n "$RUN_VAL" ]]; then
    printf '  PASS: TC08: fresh-shell eval set RUN=%s\n' "$RUN_VAL"; PASS=$((PASS + 1))
  else
    printf '  FAIL: TC08: fresh-shell eval did not set RUN (output: %s)\n' "$FRESH_OUT"; FAIL=$((FAIL + 1))
  fi
  if [[ -n "$PLAN_DIR_VAL" ]]; then
    printf '  PASS: TC08: fresh-shell eval set Z_HARNESS_PLAN_DIR=%s\n' "$PLAN_DIR_VAL"; PASS=$((PASS + 1))
  else
    printf '  FAIL: TC08: fresh-shell eval did not set Z_HARNESS_PLAN_DIR\n'; FAIL=$((FAIL + 1))
  fi
  assert_eq "TC08: CLAIM_HELD is 1 (free acquire)" "1" "$CLAIM_HELD_VAL"
  assert_eq "TC08: REG_RC is 0 (register succeeded)" "0" "$REG_RC_VAL"

  # --- Step 2: exercise the slug-collision non-zero branch ---
  # A peer holds the SAME slug under a different run-id; a second preflight
  # for that slug must hard-stop with the documented contention exit code.
  #
  # Precondition check (attributability, not a race workaround): confirm the
  # daemon plan-claim.sh acquire spawned for the first call is still alive
  # and its lock record is still the valid holder record it wrote, so that
  # IF the collision assertion below ever fails, the failure is immediately
  # attributable to plan-claim.sh's collision-detection branch rather than
  # to the daemon's own lifetime (a `bash scripts/sink-lock.sh acquire`
  # background-daemon primitive this test does not own or modify).
  LOCKF="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)/${SLUG}.lock"
  RAW_LOCK="$(cat "$LOCKF" 2>/dev/null || echo '')"
  LOCK_PID="$(json_get "$RAW_LOCK" pid)"
  PID_ALIVE_RC=1
  [[ -n "$LOCK_PID" ]] && { kill -0 "$LOCK_PID" 2>/dev/null; PID_ALIVE_RC=$?; }
  if [[ "$PID_ALIVE_RC" -ne 0 ]]; then
    printf '  NOTE: TC08 precondition: holder daemon (pid=%s) is not alive ahead of the ' "$LOCK_PID" >&2
    printf 'collision attempt; lock content=%s — the collision assertion below is expected ' "$RAW_LOCK" >&2
    printf 'to fail for an out-of-scope reason (sink-lock.sh daemon lifetime), not a ' >&2
    printf 'plan-claim.sh/z-preflight.sh defect.\n' >&2
  fi

  RC_COLLISION=0
  COLLISION_ERR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture-b --slug "$SLUG" --session "different-session" 2>&1 >/dev/null)" || RC_COLLISION=$?
  if [[ "$RC_COLLISION" -ne 10 ]]; then
    printf '  NOTE: TC08 collision call stderr: %s\n' "$COLLISION_ERR" >&2
  fi
  assert_rc 10 "TC08: second preflight on the same live slug hard-stops (collision)" "$RC_COLLISION"

  # --- Step 3: run z-teardown.sh for the original run and assert cleanup ---
  RC_TEARDOWN=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN_VAL" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>/dev/null || RC_TEARDOWN=$?
  assert_rc 0 "TC08: teardown exits 0" "$RC_TEARDOWN"

  # run-brief finalize occurred: finalize unconditionally emits a
  # `run_brief_end` event (regardless of what run-status.sh classifies the
  # run as), so that event's presence is the reliable finalize-occurred
  # signal — more robust than asserting a specific status transition, since
  # a fixture command with only run_start/run_end events classifies as
  # "unknown" and run-brief.sh intentionally leaves status unchanged in
  # that case (existing, out-of-scope behavior of run-brief.sh finalize).
  BRIEF_PATH="$PLAN_DIR_VAL/archive/$RUN_VAL/run-brief.json"
  EVENTS_PATH="$PLAN_DIR_VAL/archive/$RUN_VAL/events.jsonl"
  if [[ -f "$BRIEF_PATH" ]]; then
    printf '  PASS: TC08: run-brief.json exists after teardown\n'
    PASS=$((PASS + 1))
  else
    printf '  FAIL: TC08: run-brief.json missing at %s\n' "$BRIEF_PATH"
    FAIL=$((FAIL + 1))
  fi
  if [[ -f "$EVENTS_PATH" ]] && grep -q '"kind":"run_brief_end"' "$EVENTS_PATH"; then
    printf '  PASS: TC08: run_brief_end event present (finalize occurred)\n'
    PASS=$((PASS + 1))
  else
    printf '  FAIL: TC08: run_brief_end event missing from %s\n' "$EVENTS_PATH"
    FAIL=$((FAIL + 1))
  fi

  # registry list no longer shows the run.
  LIST_OUT="$(Z_HARNESS_BASE_DIR="$tmp" python3 "$REGISTRY_PY" list --json 2>/dev/null)"
  RUN_STILL_PRESENT="$(printf '%s' "$LIST_OUT" | grep -c "\"$RUN_VAL\"" || true)"
  assert_eq "TC08: registry list no longer shows the run" "0" "$RUN_STILL_PRESENT"

  # lock file gone (claim released).
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  STATUS_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC08: slug lock is free after teardown" "free" "$(json_get "$STATUS_JSON" state)"

  # Cleanup: release the collision-attempt-b's contender identity if it
  # somehow ended up holding anything (best-effort; b never acquired since
  # it hard-stopped at RC 10, so this is a defensive no-op).
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" release \
    --slug "$SLUG" --run-id "does-not-matter" --session "different-session" --command "/z-test-fixture-b" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC09 — --no-claim: CLAIM_HELD=0, no lock file, still registers, and does
# NOT contend with a live peer holding the same slug (acquire never called).
# ---------------------------------------------------------------------------
printf '\nTC09: --no-claim -> CLAIM_HELD=0, no lock file, registers, never contends\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc09-slug"

  # A live writer holds the slug first.
  RC_WRITER=0
  WRITER_OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture-writer --slug "$SLUG" 2>/dev/null)" || RC_WRITER=$?
  assert_rc 0 "TC09: writer preflight acquires the slug" "$RC_WRITER"
  WRITER_RUN_LINE="$(printf '%s\n' "$WRITER_OUT" | grep '^export RUN=')"
  eval "$WRITER_RUN_LINE"
  WRITER_RUN="$RUN"

  # A --no-claim (read-only) preflight for the SAME slug must NOT hard-stop
  # on collision, because it never calls plan-claim.sh acquire at all.
  RC_NOCLAIM=0
  NOCLAIM_OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_PREFLIGHT" --command /z-test-fixture-ro --slug "$SLUG" --no-claim 2>/dev/null)" || RC_NOCLAIM=$?
  assert_rc 0 "TC09: --no-claim does not contend with a live writer on the same slug" "$RC_NOCLAIM"
  assert_contains "TC09: CLAIM_HELD=0" "export CLAIM_HELD=0" "$NOCLAIM_OUT"
  assert_contains "TC09: REG_RC=0 (still registers)" "export REG_RC=0" "$NOCLAIM_OUT"

  NOCLAIM_RUN_LINE="$(printf '%s\n' "$NOCLAIM_OUT" | grep '^export RUN=')"
  eval "$NOCLAIM_RUN_LINE"
  NOCLAIM_RUN="$RUN"

  # The writer's lock file exists (writer holds it); it must be UNCHANGED by
  # the --no-claim run (still shows the writer as holder, not overwritten).
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  STATUS_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC09: slug lock still held by the writer (untouched)" "held" "$(json_get "$STATUS_JSON" state)"

  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$NOCLAIM_RUN" --slug "$SLUG" --command /z-test-fixture-ro >/dev/null 2>&1 || true
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$WRITER_RUN" --slug "$SLUG" --command /z-test-fixture-writer >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
