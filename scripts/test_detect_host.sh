#!/usr/bin/env bash
# test_detect_host.sh — Regression tests for canonical host/surface resolution.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT="$SCRIPTS_DIR/detect-host.sh"
PASS=0
FAIL=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS: %s\n' "$label"; PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — expected %s, got %s\n' "$label" "$expected" "$actual"; FAIL=$((FAIL + 1))
  fi
}

run_detect() {
  env -i HOME="${HOME:-}" PATH="${PATH:-}" "$@" bash "$DETECT" --json
}

host_field() { python3 -c 'import json,sys; print(json.load(sys.stdin)["host"])'; }
surface_field() { python3 -c 'import json,sys; print(json.load(sys.stdin)["surface"])'; }

echo 'T002-A: direct Codex App evidence'
RESULT="$(run_detect CODEX_THREAD_ID=thread-123)"
assert_eq 'Codex App resolves host' codex "$(printf '%s' "$RESULT" | host_field)"
assert_eq 'Codex App resolves surface' app "$(printf '%s' "$RESULT" | surface_field)"

echo 'T002-B: explicit Codex CLI evidence'
RESULT="$(run_detect CODEX_EXEC=/usr/bin/codex)"
assert_eq 'Codex CLI resolves host' codex "$(printf '%s' "$RESULT" | host_field)"
assert_eq 'Codex CLI resolves surface' cli "$(printf '%s' "$RESULT" | surface_field)"

echo 'T002-C: explicit overrides are validated'
RESULT="$(run_detect Z_HARNESS_HOST=codex Z_HARNESS_SURFACE=app)"
assert_eq 'explicit pair is recorded' '{"host":"codex","surface":"app"}' "$RESULT"
RESULT="$(run_detect Z_HARNESS_HOST=codex Z_HARNESS_SURFACE=app CLAUDE_PLUGIN_ROOT=/tmp/claude)"
assert_eq 'explicit pair takes precedence over ambient markers' \
  '{"host":"codex","surface":"app"}' "$RESULT"
RESULT="$(run_detect Z_HARNESS_HOST=legacy-test-host)"
assert_eq 'legacy host-only override keeps surface unknown' \
  '{"host":"legacy-test-host","surface":"unknown"}' "$RESULT"
if run_detect Z_HARNESS_HOST=codex Z_HARNESS_SURFACE=not-a-surface >/dev/null 2>&1; then
  assert_eq 'invalid pair is rejected' rejected accepted
else
  assert_eq 'invalid pair is rejected' rejected rejected
fi

echo 'T002-D: conflicting evidence fails closed'
if run_detect CODEX_THREAD_ID=thread-123 CODEX_EXEC=/usr/bin/codex >/dev/null 2>&1; then
  assert_eq 'App and CLI markers conflict' rejected accepted
else
  assert_eq 'App and CLI markers conflict' rejected rejected
fi

echo 'T002-E: missing evidence is unknown, not Claude'
RESULT="$(run_detect)"
assert_eq 'missing host is unknown' unknown "$(printf '%s' "$RESULT" | host_field)"
assert_eq 'missing surface is unknown' unknown "$(printf '%s' "$RESULT" | surface_field)"

printf '\nResults: %d passed, %d failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
