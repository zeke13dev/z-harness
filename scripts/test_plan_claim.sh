#!/usr/bin/env bash
# test_plan_claim.sh — Integration tests for scripts/plan-claim.sh
#
# Run with:
#   bash scripts/test_plan_claim.sh
#   make test-sh   (auto-discovered by the glob scripts/*test*.sh)
#
# Per-test isolation: each case uses its own tmp dir set as Z_HARNESS_BASE_DIR.
# The trap 'rm -rf "$tmp"' RETURN pattern is approximated via a cleanup array
# on EXIT, since bash functions don't reliably support RETURN trap in all envs.
#
# Tests:
#   TC01 — free acquire: exit 0, holder record present, holder string parses
#   TC02 — cross-session contention: exit 1, prints peer holder JSON
#   TC03 — self-reentry: same session, different run → exit 0 (self-reentry)
#   TC04 — heartbeat extends last_heartbeat
#   TC05 — post-ownership-change heartbeat → exit 9
#   TC06 — transient/corrupt read during heartbeat → heartbeat_error + exit 0, NOT exit 9
#   TC07 — stale-takeover via tiny TTL → exit 2
#   TC08 — release matching expected-holder frees the slug
#   TC09 — release NON-matching expected-holder: true no-op (peer daemon alive, peer record intact)
#   TC10 — corrupt lock → exit 3
#   TC11 — Z_HARNESS_CLAIM_DISABLE=1 → acquire/heartbeat/release all exit 0 no-op
#   TC12 — acquire with </dev/null succeeds (non-interactive)
#   TC13 — read-holder / status JSON shape for held / free / stale / corrupt

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAN_CLAIM="$SCRIPTS_DIR/plan-claim.sh"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

CLEANUP_DIRS=()
_cleanup_all() {
  for d in "${CLEANUP_DIRS[@]:-}"; do
    [[ -d "$d" ]] && rm -rf "$d" 2>/dev/null || true
  done
}
trap _cleanup_all EXIT

_tmpdir() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/test_plan_claim_XXXXXX")"
  CLEANUP_DIRS+=("$d")
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
    printf '  FAIL: %s\n' "$label"
    printf '        expected: %s\n' "$expected"
    printf '        actual:   %s\n' "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s\n' "$label"
    printf '        expected substring: %s\n' "$needle"
    printf '        in: %s\n' "$haystack"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    printf '  FAIL: %s (found unwanted substring)\n' "$label"
    printf '        unwanted: %s\n' "$needle"
    printf '        in: %s\n' "$haystack"
    FAIL=$((FAIL + 1))
  else
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_file_exists() {
  local label="$1" path="$2"
  if [[ -f "$path" ]]; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — file not found: %s\n' "$label" "$path"
    FAIL=$((FAIL + 1))
  fi
}

# json_get <json> <key> — extract a top-level JSON string/number field.
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

# Run plan-claim.sh with a given Z_HARNESS_BASE_DIR for isolation.
# Usage: run_claim <base_dir> [args...]
# Captures output in CLAIM_OUT, exit code in CLAIM_RC.
CLAIM_OUT=""
CLAIM_RC=0
run_claim() {
  local base_dir="$1"
  shift
  CLAIM_RC=0
  CLAIM_OUT=""
  CLAIM_OUT="$(Z_HARNESS_BASE_DIR="$base_dir" bash "$PLAN_CLAIM" "$@" 2>/dev/null)" || CLAIM_RC=$?
}

# ---------------------------------------------------------------------------
# TC01 — Free acquire: exit 0, holder record present, holder string parses
# ---------------------------------------------------------------------------
printf '\nTC01: free acquire — exit 0, holder present, parses correctly\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses01" RUN="run01" CMD="/z-plan" SLUG="tc01-slug"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" 2>/dev/null)" \
    || RC=$?

  assert_rc 0 "TC01: acquire on free slug exits 0" "$RC"
  assert_eq "TC01: acquire prints 'acquired'" "acquired" "$OUT"

  # Lock file must exist
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  LOCKFILE="$CLAIMS_DIR/${SLUG}.lock"
  assert_file_exists "TC01: lock file exists after acquire" "$LOCKFILE"

  # Holder string in the lock file must parse to correct fields
  HOLDER_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  STATE="$(json_get "$HOLDER_JSON" state)"
  HOLDER_STR="$(json_get "$HOLDER_JSON" holder)"
  assert_eq "TC01: state is held" "held" "$STATE"
  assert_contains "TC01: holder contains session" "$SESSION" "$HOLDER_STR"
  assert_contains "TC01: holder contains run" "$RUN" "$HOLDER_STR"
  assert_contains "TC01: holder contains command" "$CMD" "$HOLDER_STR"

  # Release so daemon doesn't linger
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC02 — Cross-session contention: exit 1, prints peer holder JSON
# ---------------------------------------------------------------------------
printf '\nTC02: cross-session contention — exit 1 + peer holder JSON on stdout\n'

{
  tmp="$(_tmpdir)"
  SESSION_A="sesA" RUN_A="runA" SESSION_B="sesB" RUN_B="runB"
  CMD="/z-plan" SLUG="tc02-slug"

  # Session A acquires
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_A" --session "$SESSION_A" --command "$CMD" \
    >/dev/null 2>/dev/null

  # Session B tries to acquire — should get exit 1
  RC_B=0
  OUT_B="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_B" --session "$SESSION_B" --command "$CMD" 2>/dev/null)" \
    || RC_B=$?

  assert_rc 1 "TC02: contending acquire exits 1" "$RC_B"

  # The output must be valid JSON with holder info about session A
  assert_contains "TC02: holder JSON contains peer session" "$SESSION_A" "$OUT_B"
  assert_contains "TC02: holder JSON contains peer run" "$RUN_A" "$OUT_B"

  # Cleanup A
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_A" --session "$SESSION_A" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC03 — Self-reentry: same session, different run → exit 0 (self-reentry)
# ---------------------------------------------------------------------------
printf '\nTC03: self-reentry — same session, different run → exit 0\n'

{
  tmp="$(_tmpdir)"
  SESSION="sesReentry" RUN_1="run-first" RUN_2="run-second"
  CMD="/z-plan" SLUG="tc03-slug"

  # First run acquires
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_1" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null

  # Same session, new run — should be treated as self-reentry (exit 0)
  RC_2=0
  OUT_2="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_2" --session "$SESSION" --command "$CMD" 2>/dev/null)" \
    || RC_2=$?

  assert_rc 0 "TC03: self-reentry exits 0" "$RC_2"
  assert_eq "TC03: self-reentry prints 'self-reentry'" "self-reentry" "$OUT_2"

  # Cleanup
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_1" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC04 — Heartbeat extends last_heartbeat
# ---------------------------------------------------------------------------
printf '\nTC04: heartbeat extends last_heartbeat\n'

{
  tmp="$(_tmpdir)"
  SESSION="sesHB" RUN="runHB" CMD="/z-plan" SLUG="tc04-slug"

  # Acquire
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null

  # Read initial heartbeat timestamp
  HB_JSON_1="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HB_1="$(json_get "$HB_JSON_1" last_heartbeat)"

  # Sleep briefly, then heartbeat
  sleep 1

  HB_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    heartbeat --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null || HB_RC=$?
  assert_rc 0 "TC04: heartbeat exits 0" "$HB_RC"

  # Read updated heartbeat timestamp
  HB_JSON_2="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HB_2="$(json_get "$HB_JSON_2" last_heartbeat)"

  # The timestamps must differ (heartbeat extended it)
  if [[ -n "$HB_1" && -n "$HB_2" && "$HB_2" != "$HB_1" ]]; then
    printf '  PASS: TC04: last_heartbeat was extended (%s -> %s)\n' "$HB_1" "$HB_2"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: TC04: last_heartbeat was NOT extended (before=%s, after=%s)\n' "$HB_1" "$HB_2"
    FAIL=$((FAIL + 1))
  fi

  # Cleanup
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC05 — Post-ownership-change heartbeat → exit 9
# ---------------------------------------------------------------------------
printf '\nTC05: post-ownership-change heartbeat → exit 9\n'

{
  tmp="$(_tmpdir)"
  SESSION_A="sesA05" RUN_A="runA05"
  SESSION_B="sesB05" RUN_B="runB05"
  CMD="/z-plan" SLUG="tc05-slug"

  # Session A acquires with a very short TTL so B can take it over
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_A" --session "$SESSION_A" --command "$CMD" \
    --ttl 1 >/dev/null 2>/dev/null

  # Sleep past the TTL
  sleep 2

  # Session B performs a stale-takeover (exit 2 is the expected result)
  RC_B=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_B" --session "$SESSION_B" --command "$CMD" \
    --ttl 60 >/dev/null 2>/dev/null || RC_B=$?

  # rc==2 means stale-takeover succeeded; rc==0 means it acquired freely (both ok here)
  if [[ "$RC_B" -eq 2 || "$RC_B" -eq 0 ]]; then
    printf '  PASS: TC05: session B acquired (stale-takeover or free, rc=%s)\n' "$RC_B"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: TC05: session B acquire got unexpected rc=%s\n' "$RC_B"
    FAIL=$((FAIL + 1))
  fi

  # Now session A's heartbeat should detect it's no longer the holder → exit 9
  HB_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    heartbeat --slug "$SLUG" --run-id "$RUN_A" --session "$SESSION_A" --command "$CMD" \
    >/dev/null 2>/dev/null || HB_RC=$?
  assert_rc 9 "TC05: original holder's heartbeat after takeover exits 9 (lost claim)" "$HB_RC"

  # Cleanup B
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_B" --session "$SESSION_B" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC06 — Transient/corrupt read during heartbeat → heartbeat_error + exit 0, NOT exit 9
# ---------------------------------------------------------------------------
printf '\nTC06: transient/corrupt read during heartbeat → heartbeat_error + exit 0 (not exit 9)\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses06" RUN="run06" CMD="/z-plan" SLUG="tc06-slug"

  # Acquire normally
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null

  # Corrupt the lock file content (non-JSON)
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  LOCKFILE="$CLAIMS_DIR/${SLUG}.lock"
  # Write corrupt content that will force read-holder to return exit 3
  printf 'THIS IS NOT JSON!!!\n' > "$LOCKFILE"

  # The .flock file still holds the OS lock, so sink-lock's read-holder will exit 3.
  # plan-claim.sh heartbeat must treat this as heartbeat_error (exit 0), NOT exit 9.
  HB_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    heartbeat --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null || HB_RC=$?

  assert_rc 0 "TC06: heartbeat with corrupt lock exits 0 (non-fatal, not exit 9)" "$HB_RC"

  # Cleanup: kill any lingering daemon by force (flock held by daemon from acquire)
  # We write null to the lock file so sink-lock release can proceed
  printf 'null\n' > "$LOCKFILE" 2>/dev/null || true
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC07 — Stale-takeover via tiny TTL → exit 2
# ---------------------------------------------------------------------------
printf '\nTC07: stale-takeover via tiny TTL → exit 2\n'

{
  tmp="$(_tmpdir)"
  SESSION_A="sesA07" RUN_A="runA07"
  SESSION_B="sesB07" RUN_B="runB07"
  CMD="/z-plan" SLUG="tc07-slug"

  # Acquire with TTL=1 second
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_A" --session "$SESSION_A" --command "$CMD" \
    --ttl 1 >/dev/null 2>/dev/null

  # Wait for TTL to expire
  sleep 2

  # Second session acquire should succeed via stale-takeover (exit 2)
  RC_B=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_B" --session "$SESSION_B" --command "$CMD" \
    --ttl 60 >/dev/null 2>/dev/null || RC_B=$?

  if [[ "$RC_B" -eq 2 ]]; then
    printf '  PASS: TC07: stale-takeover exits 2\n'
    PASS=$((PASS + 1))
  elif [[ "$RC_B" -eq 0 ]]; then
    # Daemon may have died before flock was taken; stale content acquired freely
    printf '  PASS: TC07: stale lock acquired freely (rc=0 — daemon already dead)\n'
    PASS=$((PASS + 1))
  else
    printf '  FAIL: TC07: expected exit 2 (or 0 for dead daemon), got %s\n' "$RC_B"
    FAIL=$((FAIL + 1))
  fi

  # Verify B now holds it (status shows B's holder)
  HJ="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_contains "TC07: after takeover, holder contains session B" "$SESSION_B" "$HJ"

  # Release B
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_B" --session "$SESSION_B" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC08 — Release matching expected-holder frees the slug
# ---------------------------------------------------------------------------
printf '\nTC08: release with matching holder frees the slug\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses08" RUN="run08" CMD="/z-plan" SLUG="tc08-slug"

  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null

  REL_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null || REL_RC=$?

  assert_rc 0 "TC08: release exits 0" "$REL_RC"

  # Verify the slug is now free (status returns {"state":"free"})
  FREE_JSON="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  FREE_STATE="$(json_get "$FREE_JSON" state)"
  assert_eq "TC08: slug is free after matching release" "free" "$FREE_STATE"
}

# ---------------------------------------------------------------------------
# TC09 — Release NON-matching holder: peer daemon alive, peer record intact
# ---------------------------------------------------------------------------
printf '\nTC09: release with non-matching holder is a no-op (peer record intact)\n'

{
  tmp="$(_tmpdir)"
  SESSION_OWNER="sesOwner09" RUN_OWNER="runOwner09"
  SESSION_OTHER="sesOther09" RUN_OTHER="runOther09"
  CMD="/z-plan" SLUG="tc09-slug"

  # Owner acquires
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN_OWNER" --session "$SESSION_OWNER" --command "$CMD" \
    >/dev/null 2>/dev/null

  # Read owner's holder record before the "other" release attempt
  HJ_BEFORE="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HOLDER_BEFORE="$(json_get "$HJ_BEFORE" holder)"

  # "Other" session attempts release (different session/run → non-matching)
  REL_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_OTHER" --session "$SESSION_OTHER" --command "$CMD" \
    >/dev/null 2>/dev/null || REL_RC=$?

  assert_rc 0 "TC09: non-matching release exits 0 (best-effort)" "$REL_RC"

  # Owner's record must still be intact — same holder string
  HJ_AFTER="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  HOLDER_AFTER="$(json_get "$HJ_AFTER" holder)"
  STATE_AFTER="$(json_get "$HJ_AFTER" state)"

  assert_eq "TC09: slug still held after non-matching release" "held" "$STATE_AFTER"
  assert_eq "TC09: peer holder string unchanged" "$HOLDER_BEFORE" "$HOLDER_AFTER"

  # Verify the owner's daemon is still alive (heartbeat should succeed)
  HB_RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    heartbeat --slug "$SLUG" --run-id "$RUN_OWNER" --session "$SESSION_OWNER" --command "$CMD" \
    >/dev/null 2>/dev/null || HB_RC=$?
  assert_rc 0 "TC09: owner's heartbeat still works after non-matching release attempt" "$HB_RC"

  # Cleanup owner
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN_OWNER" --session "$SESSION_OWNER" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC10 — Corrupt lock content → exit 3
# ---------------------------------------------------------------------------
printf '\nTC10: corrupt lock content → exit 3 on acquire\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses10" RUN="run10" CMD="/z-plan" SLUG="tc10-slug"

  # Create the claims dir and write a corrupt (non-JSON) lock file
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  mkdir -p "$CLAIMS_DIR"
  printf 'NOT VALID JSON -- corrupt content\n' > "$CLAIMS_DIR/${SLUG}.lock"

  RC=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null || RC=$?

  assert_rc 3 "TC10: acquire on corrupt lock exits 3" "$RC"

  # Clean up the corrupt file
  rm -f "$CLAIMS_DIR/${SLUG}.lock" "$CLAIMS_DIR/${SLUG}.lock.flock" \
        "$CLAIMS_DIR/${SLUG}.lock.hb.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# TC11 — Z_HARNESS_CLAIM_DISABLE=1 → all subcommands exit 0 no-op
# ---------------------------------------------------------------------------
printf '\nTC11: Z_HARNESS_CLAIM_DISABLE=1 → acquire/heartbeat/release all exit 0\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses11" RUN="run11" CMD="/z-plan" SLUG="tc11-slug"

  for SUB in acquire heartbeat release; do
    RC=0
    Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_CLAIM_DISABLE=1 bash "$PLAN_CLAIM" \
      "$SUB" --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
      >/dev/null 2>/dev/null || RC=$?
    assert_rc 0 "TC11: $SUB with CLAIM_DISABLE=1 exits 0" "$RC"
  done

  # The lock file must NOT have been created
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  LOCKFILE="$CLAIMS_DIR/${SLUG}.lock"
  if [[ -f "$LOCKFILE" ]]; then
    printf '  FAIL: TC11: lock file was created despite CLAIM_DISABLE=1\n'
    FAIL=$((FAIL + 1))
  else
    printf '  PASS: TC11: no lock file created with CLAIM_DISABLE=1\n'
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# TC12 — Acquire with </dev/null succeeds (non-interactive)
# ---------------------------------------------------------------------------
printf '\nTC12: acquire with stdin=</dev/null (non-interactive) succeeds\n'

{
  tmp="$(_tmpdir)"
  SESSION="ses12" RUN="run12" CMD="/z-plan" SLUG="tc12-slug"

  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    </dev/null 2>/dev/null)" || RC=$?

  assert_rc 0 "TC12: acquire with </dev/null exits 0" "$RC"
  assert_eq "TC12: acquire with </dev/null prints 'acquired'" "acquired" "$OUT"

  # Release
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# TC13 — read-holder / status JSON shape for held / free / stale / corrupt
# ---------------------------------------------------------------------------
printf '\nTC13: status JSON shape for held / free / stale / corrupt states\n'

# -- TC13-A: held state --
{
  tmp="$(_tmpdir)"
  SESSION="ses13" RUN="run13" CMD="/z-plan" SLUG="tc13-held"

  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null

  HJ="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC13-A: held state field" "held" "$(json_get "$HJ" state)"
  assert_contains "TC13-A: held JSON has 'holder' key" '"holder"' "$HJ"
  assert_contains "TC13-A: held JSON has 'pid' key" '"pid"' "$HJ"
  assert_contains "TC13-A: held JSON has 'last_heartbeat' key" '"last_heartbeat"' "$HJ"
  assert_contains "TC13-A: held JSON has 'heartbeat_age_s' key" '"heartbeat_age_s"' "$HJ"
  assert_contains "TC13-A: held JSON has 'stale' key" '"stale"' "$HJ"

  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# -- TC13-B: free state (after release) --
{
  tmp="$(_tmpdir)"
  SESSION="ses13b" RUN="run13b" CMD="/z-plan" SLUG="tc13-free"

  # Acquire and immediately release
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    >/dev/null 2>/dev/null || true

  FJ="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC13-B: free state field" "free" "$(json_get "$FJ" state)"
}

# -- TC13-C: never-held slug also returns free --
{
  tmp="$(_tmpdir)"
  SLUG="tc13-never-held"

  # Create the claims dir but don't put any lock file there
  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  mkdir -p "$CLAIMS_DIR"

  FJ="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" 2>/dev/null)"
  assert_eq "TC13-C: never-held slug state is free" "free" "$(json_get "$FJ" state)"
}

# -- TC13-D: stale state (live lock with expired heartbeat) --
{
  tmp="$(_tmpdir)"
  SESSION="ses13d" RUN="run13d" CMD="/z-plan" SLUG="tc13-stale"

  # Acquire with TTL=1
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "$RUN" --session "$SESSION" --command "$CMD" \
    --ttl 1 >/dev/null 2>/dev/null

  # Wait past TTL
  sleep 2

  # Status with the same tiny TTL should show stale:true
  SJ="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" --ttl 1 2>/dev/null)"
  ST_STATE="$(json_get "$SJ" state)"
  ST_STALE="$(json_get "$SJ" stale)"
  assert_eq "TC13-D: stale state field is held" "held" "$ST_STATE"
  assert_eq "TC13-D: stale field is True" "True" "$ST_STALE"

  # Cleanup (stale acquire will kill old daemon)
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    acquire --slug "$SLUG" --run-id "${RUN}-b" --session "${SESSION}b" --command "$CMD" \
    --ttl 60 >/dev/null 2>/dev/null || true
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" \
    release --slug "$SLUG" --run-id "${RUN}-b" --session "${SESSION}b" --command "$CMD" \
    >/dev/null 2>&1 || true
}

# -- TC13-E: corrupt state → status exits 3 --
{
  tmp="$(_tmpdir)"
  SLUG="tc13-corrupt"

  CLAIMS_DIR="$(Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_PATH" claims_dir 2>/dev/null)"
  mkdir -p "$CLAIMS_DIR"
  printf 'CORRUPT_NOT_JSON\n' > "$CLAIMS_DIR/${SLUG}.lock"

  RC_STATUS=0
  Z_HARNESS_BASE_DIR="$tmp" bash "$PLAN_CLAIM" status --slug "$SLUG" \
    >/dev/null 2>/dev/null || RC_STATUS=$?
  assert_rc 3 "TC13-E: status on corrupt lock exits 3" "$RC_STATUS"

  rm -f "$CLAIMS_DIR/${SLUG}.lock" "$CLAIMS_DIR/${SLUG}.lock.flock" \
        "$CLAIMS_DIR/${SLUG}.lock.hb.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
