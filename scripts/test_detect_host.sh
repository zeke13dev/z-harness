#!/usr/bin/env bash
# test_detect_host.sh — Unit tests for scripts/detect-host.sh
#
# Run with:
#   bash scripts/test_detect_host.sh
#
# Tests:
#   T003-A: Bare env (no markers) → "claude"
#   T003-B: ANTIGRAVITY_PLUGIN_ROOT set → "antigravity"
#   T003-C: PI_* variable set → "pi"
#   T003-D: CODEX_API_KEY set → "codex"
#   T003-E: CODEX_EXEC set → "codex"
#   T003-F: CURSOR_API_KEY set → "cursor"
#   T003-G: Never-empty invariant (every branch produces non-empty output)
#   T003-H: Never-unknown invariant (every branch produces a legal host value)
#   T003-I: antigravity wins over pi (priority order)
#   T003-J: pi wins over codex (priority order)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT="$SCRIPTS_DIR/detect-host.sh"

PASS=0
FAIL=0

LEGAL_HOSTS=(claude pi codex cursor antigravity)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — expected "%s", got "%s"\n' "$label" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_empty() {
  local label="$1" actual="$2"
  if [[ -n "$actual" ]]; then
    printf '  PASS: %s (non-empty: "%s")\n' "$label" "$actual"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — output was empty\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_legal_host() {
  local label="$1" actual="$2"
  local found=0
  local h
  for h in "${LEGAL_HOSTS[@]}"; do
    if [[ "$actual" == "$h" ]]; then
      found=1
      break
    fi
  done
  if [[ "$found" -eq 1 ]]; then
    printf '  PASS: %s (legal host: "%s")\n' "$label" "$actual"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — illegal host value "%s" (must be one of: %s)\n' \
      "$label" "$actual" "$(IFS='|'; echo "${LEGAL_HOSTS[*]}")"
    FAIL=$((FAIL + 1))
  fi
}

# Run detect-host.sh in a clean env with only the specified vars.
# Usage: run_detect [VAR=value ...]
run_detect() {
  env -i HOME="${HOME:-}" PATH="${PATH:-}" "$@" bash "$DETECT"
}

# ---------------------------------------------------------------------------
# T003-A: Bare env → "claude"
# ---------------------------------------------------------------------------

printf '\nT003-A: Bare env → claude\n'
RESULT="$(run_detect)"
assert_eq "bare env returns claude" "claude" "$RESULT"

# ---------------------------------------------------------------------------
# T003-B: ANTIGRAVITY_PLUGIN_ROOT set → "antigravity"
# ---------------------------------------------------------------------------

printf '\nT003-B: ANTIGRAVITY_PLUGIN_ROOT set → antigravity\n'
RESULT="$(run_detect ANTIGRAVITY_PLUGIN_ROOT=/some/path)"
assert_eq "ANTIGRAVITY_PLUGIN_ROOT → antigravity" "antigravity" "$RESULT"

# ---------------------------------------------------------------------------
# T003-C: PI_* variable set → "pi"
# ---------------------------------------------------------------------------

printf '\nT003-C: PI_HOSTNAME set → pi\n'
RESULT="$(run_detect PI_HOSTNAME=raspberrypi)"
assert_eq "PI_HOSTNAME → pi" "pi" "$RESULT"

printf '\nT003-C2: PI_USER set → pi\n'
RESULT="$(run_detect PI_USER=pi)"
assert_eq "PI_USER → pi" "pi" "$RESULT"

# ---------------------------------------------------------------------------
# T003-D: CODEX_API_KEY set → "codex"
# ---------------------------------------------------------------------------

printf '\nT003-D: CODEX_API_KEY set → codex\n'
RESULT="$(run_detect CODEX_API_KEY=sk-test-123)"
assert_eq "CODEX_API_KEY → codex" "codex" "$RESULT"

# ---------------------------------------------------------------------------
# T003-E: CODEX_EXEC set → "codex"
# ---------------------------------------------------------------------------

printf '\nT003-E: CODEX_EXEC set → codex\n'
RESULT="$(run_detect CODEX_EXEC=/usr/bin/codex)"
assert_eq "CODEX_EXEC → codex" "codex" "$RESULT"

# ---------------------------------------------------------------------------
# T003-F: CURSOR_API_KEY set → "cursor"
# ---------------------------------------------------------------------------

printf '\nT003-F: CURSOR_API_KEY set → cursor\n'
RESULT="$(run_detect CURSOR_API_KEY=cursor-key-abc)"
assert_eq "CURSOR_API_KEY → cursor" "cursor" "$RESULT"

# ---------------------------------------------------------------------------
# T003-G: Never-empty invariant — all branches produce non-empty output
# ---------------------------------------------------------------------------

printf '\nT003-G: Never-empty invariant\n'

RESULT="$(run_detect)"
assert_not_empty "bare env non-empty" "$RESULT"

RESULT="$(run_detect ANTIGRAVITY_PLUGIN_ROOT=/path)"
assert_not_empty "antigravity non-empty" "$RESULT"

RESULT="$(run_detect PI_HOST=pi-host)"
assert_not_empty "pi non-empty" "$RESULT"

RESULT="$(run_detect CODEX_API_KEY=key)"
assert_not_empty "codex non-empty" "$RESULT"

RESULT="$(run_detect CURSOR_API_KEY=key)"
assert_not_empty "cursor non-empty" "$RESULT"

# ---------------------------------------------------------------------------
# T003-H: Never-unknown invariant — all branches produce a legal host value
# ---------------------------------------------------------------------------

printf '\nT003-H: Never-unknown invariant\n'

RESULT="$(run_detect)"
assert_legal_host "bare env legal host" "$RESULT"

RESULT="$(run_detect ANTIGRAVITY_PLUGIN_ROOT=/path)"
assert_legal_host "antigravity legal host" "$RESULT"

RESULT="$(run_detect PI_HOST=pi-host)"
assert_legal_host "pi legal host" "$RESULT"

RESULT="$(run_detect CODEX_API_KEY=key)"
assert_legal_host "codex legal host" "$RESULT"

RESULT="$(run_detect CURSOR_API_KEY=key)"
assert_legal_host "cursor legal host" "$RESULT"

# ---------------------------------------------------------------------------
# T003-I: Priority — antigravity wins over pi
# ---------------------------------------------------------------------------

printf '\nT003-I: antigravity wins over pi when both set\n'
RESULT="$(run_detect ANTIGRAVITY_PLUGIN_ROOT=/path PI_HOSTNAME=pi)"
assert_eq "antigravity beats pi" "antigravity" "$RESULT"

# ---------------------------------------------------------------------------
# T003-J: Priority — pi wins over codex
# ---------------------------------------------------------------------------

printf '\nT003-J: pi wins over codex when both set\n'
RESULT="$(run_detect PI_HOSTNAME=pi CODEX_API_KEY=key)"
assert_eq "pi beats codex" "pi" "$RESULT"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\nResults: %d passed, %d failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
