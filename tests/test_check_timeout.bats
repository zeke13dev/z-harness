#!/usr/bin/env bats
# tests/test_check_timeout.bats
#
# Tests for scripts/check-timeout.sh:
#   1. timeout_backend() returns "timeout" when timeout is on PATH.
#   2. timeout_backend() returns "gtimeout" when only gtimeout is on PATH.
#   3. timeout_backend() returns "bash_fallback" when neither binary is on PATH.
#   4. Re-sourcing twice in one run emits timeout_availability exactly once.
#   5. TIMEOUT_CMD is exported after sourcing (existing behaviour unaffected).
#   6. timeout_backend produces a valid value on any PATH.
#
# Usage: bats tests/test_check_timeout.bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/check-timeout.sh"

setup() {
  STUBS="$(mktemp -d)"
  RUN_DIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$STUBS" "$RUN_DIR"
}

# ---------------------------------------------------------------------------
# 1. timeout_backend: returns "timeout" when timeout is on PATH
# ---------------------------------------------------------------------------
@test "timeout_backend returns 'timeout' when timeout is on PATH" {
  cat > "$STUBS/timeout" <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$STUBS/timeout"

  run bash -c "
    PATH=\"$STUBS:\$PATH\"
    source \"$SCRIPT\" 2>/dev/null
    timeout_backend
  "
  [ "$status" -eq 0 ]
  [ "$output" = "timeout" ]
}

# ---------------------------------------------------------------------------
# 2. timeout_backend: returns "gtimeout" when only gtimeout is on PATH
# ---------------------------------------------------------------------------
@test "timeout_backend returns 'gtimeout' when only gtimeout is on PATH" {
  cat > "$STUBS/gtimeout" <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$STUBS/gtimeout"

  # Use a minimal PATH that has our stub dir but no real 'timeout'.
  NOBIN="$(mktemp -d)"
  run bash -c "
    export PATH=\"$NOBIN:$STUBS\"
    command -v timeout >/dev/null 2>&1 && exit 99
    source \"$SCRIPT\" 2>/dev/null
    timeout_backend
  "
  rm -rf "$NOBIN"
  if [ "$status" -eq 99 ]; then
    skip "system has timeout in a PATH slot that cannot be masked by stub"
  fi
  [ "$status" -eq 0 ]
  [ "$output" = "gtimeout" ]
}

# ---------------------------------------------------------------------------
# 3. timeout_backend: returns "bash_fallback" when neither binary is on PATH
# ---------------------------------------------------------------------------
@test "timeout_backend returns 'bash_fallback' when neither timeout nor gtimeout is on PATH" {
  run bash -c "
    export PATH=\"$STUBS:/usr/bin:/bin\"
    command -v timeout  >/dev/null 2>&1 && exit 98
    command -v gtimeout >/dev/null 2>&1 && exit 97
    source \"$SCRIPT\" 2>/dev/null
    timeout_backend
  "
  if [ "$status" -eq 98 ] || [ "$status" -eq 97 ]; then
    skip "cannot mask system timeout/gtimeout from PATH in this environment"
  fi
  [ "$status" -eq 0 ]
  [ "$output" = "bash_fallback" ]
}

# ---------------------------------------------------------------------------
# 4. Re-sourcing twice emits timeout_availability exactly once
# ---------------------------------------------------------------------------
@test "re-sourcing twice emits timeout_availability exactly once" {
  CALL_LOG="$STUBS/calls.log"
  # check-timeout.sh calls: bash "$_CT_PLUGIN_ROOT/scripts/log-event.sh"
  # so the stub must live at $STUBS/scripts/log-event.sh.
  mkdir -p "$STUBS/scripts"
  # Use printf to expand CALL_LOG at stub-write time (double-quoted heredoc).
  printf '#!/usr/bin/env bash\necho "called:$2" >> "%s"\nexit 0\n' "$CALL_LOG" \
    > "$STUBS/scripts/log-event.sh"
  chmod +x "$STUBS/scripts/log-event.sh"

  RUN_ID="test-run-$$"
  mkdir -p "$RUN_DIR/plans/test-slug/archive/$RUN_ID"

  run bash -c "
    export ANTIGRAVITY_PLUGIN_ROOT=\"$STUBS\"
    export Z_HARNESS_BASE_DIR=\"$RUN_DIR\"
    export Z_HARNESS_SLUG=\"test-slug\"
    export Z_HARNESS_PLANS_DIR=\"$RUN_DIR/plans\"
    source \"$SCRIPT\" \"$RUN_ID\" 2>/dev/null
    source \"$SCRIPT\" \"$RUN_ID\" 2>/dev/null
    exit 0
  "
  [ "$status" -eq 0 ]

  count=0
  if [ -f "$CALL_LOG" ]; then
    count="$(grep -c "called:timeout_availability" "$CALL_LOG" || true)"
  fi
  [ "$count" -eq 1 ]
}

# ---------------------------------------------------------------------------
# 5. Existing TIMEOUT_CMD detection: variable is exported after sourcing
# ---------------------------------------------------------------------------
@test "TIMEOUT_CMD is exported after sourcing" {
  run bash -c "
    source \"$SCRIPT\" 2>/dev/null
    [ \"\${TIMEOUT_CMD+set}\" = \"set\" ] && echo \"defined\"
  "
  [ "$status" -eq 0 ]
  [ "$output" = "defined" ]
}

# ---------------------------------------------------------------------------
# 6. timeout_backend always produces one of the three valid values
# ---------------------------------------------------------------------------
@test "timeout_backend produces a valid value on any PATH" {
  run bash -c "
    source \"$SCRIPT\" 2>/dev/null
    result=\"\$(timeout_backend)\"
    case \"\$result\" in
      timeout|gtimeout|bash_fallback) echo ok ;;
      *) echo \"unexpected: \$result\"; exit 1 ;;
    esac
  "
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}
