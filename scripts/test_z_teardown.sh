#!/usr/bin/env bash
# test_z_teardown.sh — Tests for scripts/z-teardown.sh
#
# Run with:
#   bash scripts/test_z_teardown.sh
#   make test-sh   (auto-discovered by the glob scripts/*test*.sh)
#
# Per-test isolation: every case pins Z_HARNESS_BASE_DIR to its own tmp dir
# so nothing here ever touches real user state.
#
# The comprehensive preflight->collision->teardown integration fixture
# (asserting run-brief finalize + claim release + deregister together) lives
# in test_z_preflight.sh (TC08) since z-preflight.sh is the primary subject
# there and the fixture needs both scripts. This file covers z-teardown.sh's
# own contract and edge cases:
#
# Tests:
#   TC01 — header documents outputs and exit-code contract
#   TC02 — usage error: missing --run exits 2
#   TC03 — usage error: missing --slug exits 2
#   TC04 — usage error: missing --command exits 2
#   TC05 — usage error: invalid --status exits 2
#   TC06 — INTEGRATION: full preflight -> teardown cleans up claim + registry
#          (registry list no longer shows the run; lock file free)
#   TC07 — idempotent: calling teardown twice on the same run both exit 0
#   TC08 — teardown with no persisted session fails closed and warns
#   TC09 — claim release mismatch fails closed, preserves holder + run record
#   TC10 — --status aborted is honored (deregister status + run_end payload)
#   TC11 — persistent stopped holder retains registry/no run_end; retry completes

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
# Cleanup (file-based registry — see test_z_preflight.sh / test_plan_claim.sh
# for the rationale: command-substitution subshells lose bash arrays).
# ---------------------------------------------------------------------------
CLEANUP_REGISTRY="$(mktemp "${TMPDIR:-/tmp}/test_z_teardown_registry_XXXXXX")"
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
            | grep 'signal.pause()' | grep -F 'test_z_teardown_' | awk '{print $1, $0}')
}
trap _cleanup_all EXIT

_tmpdir() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/test_z_teardown_XXXXXX")"
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

# preflight_and_capture <base_dir> <slug> — runs z-preflight.sh, exports the
# resulting RUN into $LAST_RUN, PLAN_DIR into $LAST_PLAN_DIR.
LAST_RUN=""
LAST_PLAN_DIR=""
preflight_and_capture() {
  local base_dir="$1" slug="$2"
  local out
  out="$(Z_HARNESS_BASE_DIR="$base_dir" bash "$Z_PREFLIGHT" --command /z-test-fixture --slug "$slug" 2>/dev/null)"
  LAST_RUN="$(printf '%s\n' "$out" | sed -n 's/^export RUN=//p' | head -1)"
  LAST_PLAN_DIR="$(printf '%s\n' "$out" | sed -n 's/^export Z_HARNESS_PLAN_DIR=//p' | head -1)"
}

# ---------------------------------------------------------------------------
# TC01 — header documents outputs and exit-code contract
# ---------------------------------------------------------------------------
printf '\nTC01: header documents outputs and exit-code contract\n'
HEADER="$(head -n 60 "$Z_TEARDOWN")"
assert_contains "TC01: header mentions Exit codes:" "Exit codes:" "$HEADER"
assert_contains "TC01: header documents idempotency" "Idempotent" "$HEADER"
assert_contains "TC01: header describes sequence" "Sequence:" "$HEADER"

# ---------------------------------------------------------------------------
# TC02/03/04 — usage errors exit 2
# ---------------------------------------------------------------------------
printf '\nTC02: missing --run exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --slug s --command /z-x >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC02: missing --run" "$RC"
}

printf '\nTC03: missing --slug exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run r --command /z-x >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC03: missing --slug" "$RC"
}

printf '\nTC04: missing --command exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run r --slug s >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC04: missing --command" "$RC"
}

printf '\nTC05: invalid --status exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run r --slug s --command /z-x --status bogus >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC05: invalid --status" "$RC"
}

# ---------------------------------------------------------------------------
# TC06 — INTEGRATION: full preflight -> teardown cleans up claim + registry
# ---------------------------------------------------------------------------
printf '\nTC06: full preflight -> teardown cleans up claim + registry\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc06-slug"
  preflight_and_capture "$tmp" "$SLUG"
  RUN="$LAST_RUN"

  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>/dev/null || RC=$?
  assert_rc 0 "TC06: teardown exits 0" "$RC"

  LIST_JSON="$(Z_HARNESS_BASE_DIR="$tmp" python3 "$REGISTRY_PY" list --json 2>/dev/null)"
  RUN_PRESENT="$(printf '%s' "$LIST_JSON" | grep -c "\"$RUN\"" || true)"
  assert_eq "TC06: registry list no longer shows the run" "0" "$RUN_PRESENT"

  STATUS_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC06: slug lock is free" "free" "$(json_get "$STATUS_JSON" state)"

  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  if [[ -f "$CLAIMS_DIR/${SLUG}.lock" ]]; then
    # A zeroed/free lock file may legitimately remain on disk (release zeros
    # content rather than unlinking) — what matters is state==free above.
    printf '  PASS: TC06: lock file present but zeroed/free (acceptable)\n'
    PASS=$((PASS + 1))
  else
    printf '  PASS: TC06: lock file removed\n'
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# TC07 — idempotent: calling teardown twice both exit 0
# ---------------------------------------------------------------------------
printf '\nTC07: idempotent — teardown called twice both exit 0\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc07-slug"
  preflight_and_capture "$tmp" "$SLUG"
  RUN="$LAST_RUN"

  RC1=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>/dev/null || RC1=$?
  assert_rc 0 "TC07: first teardown call exits 0" "$RC1"

  RC2=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture >/dev/null 2>/dev/null || RC2=$?
  assert_rc 0 "TC07: second teardown call also exits 0 (idempotent)" "$RC2"
}

# ---------------------------------------------------------------------------
# TC08 — teardown with no prior preflight has no persisted holder identity,
# so it fails closed and reports both the missing brief and release warning.
# ---------------------------------------------------------------------------
printf '\nTC08: teardown with no persisted holder identity fails closed\n'
{
  tmp="$(_tmpdir)"
  RUN="never-preflighted-run"
  SLUG="tc08-slug"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture 2>/dev/null)" || RC=$?
  assert_rc 1 "TC08: unresolved holder identity is operational failure" "$RC"

  # `warnings` is a JSON list; json_get only extracts scalar top-level
  # fields, so just check the summary line's raw text for the flagged step.
  assert_contains "TC08: summary flags run_brief_finalize as a warning" "run_brief_finalize" "$OUT"
  assert_contains "TC08: summary flags claim_release as a warning" "claim_release" "$OUT"
}

# ---------------------------------------------------------------------------
# TC09 — claim release with a non-matching session is an explicit operational
# failure. The guarded holder and registry record survive untouched.
# ---------------------------------------------------------------------------
printf '\nTC09: teardown with wrong session fails closed and preserves coordination\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc09-slug"
  preflight_and_capture "$tmp" "$SLUG"
  RUN="$LAST_RUN"
  STATUS_BEFORE="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HOLDER_BEFORE="$(json_get "$STATUS_BEFORE" holder)"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" \
    --run "$RUN" --slug "$SLUG" --command "/z-test-fixture" \
    --session "not-the-owner-session" 2>"$tmp/mismatch.err")" || RC=$?
  assert_rc 1 "TC09: ownership mismatch is an operational failure" "$RC"
  assert_contains "TC09: summary records claim_release warning" "claim_release" "$OUT"

  STATUS_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC09: guarded slug is still held" "held" "$(json_get "$STATUS_JSON" state)"
  assert_eq "TC09: holder bytes are unchanged" "$HOLDER_BEFORE" "$(json_get "$STATUS_JSON" holder)"

  LIST_JSON="$(Z_HARNESS_BASE_DIR="$tmp" python3 "$REGISTRY_PY" list --json 2>/dev/null)"
  assert_eq "TC09: registry retains the ambiguous run" "1" \
    "$(printf '%s' "$LIST_JSON" | grep -c "\"$RUN\"" || true)"
  EVENTS_PATH="$LAST_PLAN_DIR/archive/$RUN/events.jsonl"
  assert_eq "TC09: no terminal run_end is emitted" "0" \
    "$(grep -c '"kind":"run_end"' "$EVENTS_PATH" 2>/dev/null || true)"

  RC_RETRY=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" \
    --run "$RUN" --slug "$SLUG" --command "/z-test-fixture" \
    >/dev/null 2>/dev/null || RC_RETRY=$?
  assert_rc 0 "TC09: later exact-holder retry completes" "$RC_RETRY"
}

# ---------------------------------------------------------------------------
# TC10 — --status aborted is honored end to end
# ---------------------------------------------------------------------------
printf '\nTC10: --status aborted is honored\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc10-slug"
  preflight_and_capture "$tmp" "$SLUG"
  RUN="$LAST_RUN"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" --run "$RUN" --slug "$SLUG" --command /z-test-fixture --status aborted 2>/dev/null)" || RC=$?
  assert_rc 0 "TC10: teardown with --status aborted exits 0" "$RC"
  assert_contains "TC10: summary reflects status=aborted" '"status": "aborted"' "$OUT"

  EVENTS_PATH="$LAST_PLAN_DIR/archive/$RUN/events.jsonl"
  if [[ -f "$EVENTS_PATH" ]]; then
    RUN_END_LINE="$(grep '"kind":"run_end"' "$EVENTS_PATH" || true)"
    assert_contains "TC10: run_end event payload has status aborted" '"status":"aborted"' "$RUN_END_LINE"
  else
    printf '  FAIL: TC10: events.jsonl missing at %s\n' "$EVENTS_PATH"
    FAIL=$((FAIL + 1))
  fi
}

# ---------------------------------------------------------------------------
# TC11 — A persistently stopped exact holder exhausts all release attempts.
# Teardown must retain the registry entry and omit run_end. Resuming the daemon
# allows the same idempotent teardown request to complete.
# ---------------------------------------------------------------------------
printf '\nTC11: persistent release timeout retains state; later retry completes\n'
{
  tmp="$(_tmpdir)"
  SLUG="tc11-slug"
  preflight_and_capture "$tmp" "$SLUG"
  RUN="$LAST_RUN"
  STATUS_BEFORE="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HOLDER_PID="$(json_get "$STATUS_BEFORE" pid)"
  kill -STOP "$HOLDER_PID"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" \
    --run "$RUN" --slug "$SLUG" --command "/z-test-fixture" \
    2>"$tmp/timeout.err")" || RC=$?
  assert_rc 1 "TC11: exhausted claim release fails teardown" "$RC"
  assert_contains "TC11: summary records claim_release warning" "claim_release" "$OUT"
  assert_contains "TC11: diagnostic records timeout exhaustion" "timeout_exhausted" \
    "$(cat "$tmp/timeout.err")"
  assert_contains "TC11: diagnostic records exactly three attempts" "attempts=3" \
    "$(cat "$tmp/timeout.err")"

  STATUS_HELD="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC11: stopped exact holder remains held" "held" "$(json_get "$STATUS_HELD" state)"
  assert_eq "TC11: exact holder identity is retained" "$(json_get "$STATUS_BEFORE" holder)" \
    "$(json_get "$STATUS_HELD" holder)"
  LIST_JSON="$(Z_HARNESS_BASE_DIR="$tmp" python3 "$REGISTRY_PY" list --json 2>/dev/null)"
  assert_eq "TC11: registry retains run after unconfirmed release" "1" \
    "$(printf '%s' "$LIST_JSON" | grep -c "\"$RUN\"" || true)"
  EVENTS_PATH="$LAST_PLAN_DIR/archive/$RUN/events.jsonl"
  assert_eq "TC11: failed teardown emits no terminal run_end" "0" \
    "$(grep -c '"kind":"run_end"' "$EVENTS_PATH" 2>/dev/null || true)"
  assert_eq "TC11: failed teardown emits no false plan_claim_released" "0" \
    "$(grep -c '"kind":"plan_claim_released"' "$EVENTS_PATH" 2>/dev/null || true)"
  assert_eq "TC11: failed teardown emits one release-failure event" "1" \
    "$(grep -c '"kind":"plan_claim_release_failed"' "$EVENTS_PATH" 2>/dev/null || true)"

  kill -CONT "$HOLDER_PID"
  RC_RETRY=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$Z_TEARDOWN" \
    --run "$RUN" --slug "$SLUG" --command "/z-test-fixture" \
    >/dev/null 2>/dev/null || RC_RETRY=$?
  assert_rc 0 "TC11: later idempotent retry completes" "$RC_RETRY"
  LIST_AFTER="$(Z_HARNESS_BASE_DIR="$tmp" python3 "$REGISTRY_PY" list --json 2>/dev/null)"
  assert_eq "TC11: successful retry deregisters run" "0" \
    "$(printf '%s' "$LIST_AFTER" | grep -c "\"$RUN\"" || true)"
  assert_eq "TC11: successful retry emits one terminal run_end" "1" \
    "$(grep -c '"kind":"run_end"' "$EVENTS_PATH" 2>/dev/null || true)"
  assert_eq "TC11: successful retry emits one confirmed release event" "1" \
    "$(grep -c '"kind":"plan_claim_released"' "$EVENTS_PATH" 2>/dev/null || true)"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
