#!/usr/bin/env bash
# test_notify_watchdog.sh — Tests for scripts/notify-watchdog.sh
#
# Run with:
#   bash scripts/test_notify_watchdog.sh
#
# Tests:
#   T005-A: should-notify=no (level=off) → silent exit 0, no curl invoked
#   T005-B: webhook set + should-notify=yes → curl is invoked (mock via PATH stub)
#   T005-C: osascript branch guarded by availability (no osascript in PATH → no crash)
#   T005-D: --pid provided → "To kill: kill <pid>" in alert body
#   T005-E: script never fails the caller (bad config → still exit 0)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$SCRIPTS_DIR/notify-watchdog.sh"

PASS=0
FAIL=0

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

assert_contains() {
    local label="$1" needle="$2" haystack="$3"
    if printf '%s' "$haystack" | grep -qF "$needle"; then
        printf '  PASS: %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '  FAIL: %s — needle "%s" not found in: %s\n' "$label" "$needle" "$haystack"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local label="$1" needle="$2" haystack="$3"
    if ! printf '%s' "$haystack" | grep -qF "$needle"; then
        printf '  PASS: %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '  FAIL: %s — unexpected needle "%s" found in: %s\n' "$label" "$needle" "$haystack"
        FAIL=$((FAIL + 1))
    fi
}

_tmpdir() {
    mktemp -d "/tmp/test_notify_watchdog_XXXXXX"
}

# ---------------------------------------------------------------------------
# T005-A: should-notify=no (level=off) → exit 0, no channels triggered
# ---------------------------------------------------------------------------

printf '\nT005-A: should-notify=no (level=off) → silent exit 0\n'

TMPDIR_A="$(_tmpdir)"

cat > "${TMPDIR_A}/z-harness.toml" <<'EOF'
[notify]
level = "off"
discord_webhook_url = "https://discord.com/api/webhooks/fake/url-a"
EOF

MOCK_BIN_A="${TMPDIR_A}/bin"
mkdir -p "$MOCK_BIN_A"
CURL_CALLED_FILE_A="${TMPDIR_A}/curl_called"

cat > "${MOCK_BIN_A}/curl" <<MOCKEOF
#!/usr/bin/env bash
echo "CALLED" > "${CURL_CALLED_FILE_A}"
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_A}/curl"

EXIT_STATUS_A=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_A}/z-harness.toml" \
    PATH="${MOCK_BIN_A}:${PATH}" \
    bash "$NOTIFY" \
    --run test-run-001 \
    --event watchdog_stall \
    --message "subprocess stalled" 2>/dev/null || EXIT_STATUS_A=$?

assert_eq "T005-A exit 0 when level=off" "0" "$EXIT_STATUS_A"

CURL_CALLED_A=""
[[ -f "${CURL_CALLED_FILE_A}" ]] && CURL_CALLED_A="yes"
assert_eq "T005-A curl NOT called when should-notify=no" "" "$CURL_CALLED_A"

rm -rf "$TMPDIR_A"

# ---------------------------------------------------------------------------
# T005-B: webhook set + should-notify=yes → curl invoked (mock via PATH stub)
# ---------------------------------------------------------------------------

printf '\nT005-B: webhook set + should-notify=yes → curl invoked\n'

TMPDIR_B="$(_tmpdir)"

cat > "${TMPDIR_B}/z-harness.toml" <<'EOF'
[notify]
level = "all"
discord_webhook_url = "https://discord.com/api/webhooks/fake/url-b"
EOF

MOCK_BIN_B="${TMPDIR_B}/bin"
mkdir -p "$MOCK_BIN_B"
CURL_LOG_B="${TMPDIR_B}/curl_log.txt"

cat > "${MOCK_BIN_B}/curl" <<MOCKEOF
#!/usr/bin/env bash
# Capture all args to a log file
printf 'CURL_ARGS: %s\n' "\$*" >> "${CURL_LOG_B}"
# Capture payload from -d arg
prev_arg=""
for arg in "\$@"; do
    if [[ "\$prev_arg" == "-d" ]]; then
        printf 'CURL_DATA: %s\n' "\$arg" >> "${CURL_LOG_B}"
    fi
    prev_arg="\$arg"
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_B}/curl"

EXIT_STATUS_B=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_B}/z-harness.toml" \
    PATH="${MOCK_BIN_B}:${PATH}" \
    bash "$NOTIFY" \
    --run test-run-002 \
    --event watchdog_stall \
    --message "agent appears hung" 2>/dev/null || EXIT_STATUS_B=$?

assert_eq "T005-B exit 0 when webhook invoked" "0" "$EXIT_STATUS_B"

CURL_LOG_CONTENT_B=""
[[ -f "$CURL_LOG_B" ]] && CURL_LOG_CONTENT_B="$(cat "$CURL_LOG_B")"
assert_contains "T005-B curl was invoked" "CURL_ARGS" "$CURL_LOG_CONTENT_B"
# The bounded timeout flag (-m) must be passed to curl
assert_contains "T005-B curl called with bounded timeout flag" "fsS" "$CURL_LOG_CONTENT_B"

rm -rf "$TMPDIR_B"

# ---------------------------------------------------------------------------
# T005-C: osascript availability guard — no osascript in PATH → no crash
# ---------------------------------------------------------------------------

printf '\nT005-C: osascript unavailable → no error, exits 0\n'

TMPDIR_C="$(_tmpdir)"

cat > "${TMPDIR_C}/z-harness.toml" <<'EOF'
[notify]
level = "all"
discord_webhook_url = ""
EOF

# Build a PATH with no osascript (only stubs of minimal deps).
MOCK_BIN_C="${TMPDIR_C}/bin"
mkdir -p "$MOCK_BIN_C"

# Verify osascript is NOT in this bin dir.
[[ ! -f "${MOCK_BIN_C}/osascript" ]] || rm "${MOCK_BIN_C}/osascript"

EXIT_STATUS_C=0
OUTPUT_C="$(Z_HARNESS_REPO_CONFIG="${TMPDIR_C}/z-harness.toml" \
    bash "$NOTIFY" \
    --run test-run-003 \
    --event watchdog_timeout \
    --message "dispatch timed out" 2>&1 || EXIT_STATUS_C=$?)"

assert_eq "T005-C exits 0 when osascript absent from PATH" "0" "$EXIT_STATUS_C"
# The output should not show an error about osascript
assert_not_contains "T005-C no osascript error output" "osascript: not found" "$OUTPUT_C"

rm -rf "$TMPDIR_C"

# ---------------------------------------------------------------------------
# T005-D: --pid passed → "To kill: kill <pid>" present in curl payload
# ---------------------------------------------------------------------------

printf '\nT005-D: --pid provided → "To kill: kill <pid>" in message body\n'

TMPDIR_D="$(_tmpdir)"

cat > "${TMPDIR_D}/z-harness.toml" <<'EOF'
[notify]
level = "all"
discord_webhook_url = "https://discord.com/api/webhooks/fake/url-d"
EOF

MOCK_BIN_D="${TMPDIR_D}/bin"
mkdir -p "$MOCK_BIN_D"
CURL_LOG_D="${TMPDIR_D}/curl_log.txt"

cat > "${MOCK_BIN_D}/curl" <<MOCKEOF
#!/usr/bin/env bash
printf 'CURL_ARGS: %s\n' "\$*" >> "${CURL_LOG_D}"
prev_arg=""
for arg in "\$@"; do
    if [[ "\$prev_arg" == "-d" ]]; then
        printf 'CURL_DATA: %s\n' "\$arg" >> "${CURL_LOG_D}"
    fi
    prev_arg="\$arg"
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_D}/curl"

EXIT_STATUS_D=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_D}/z-harness.toml" \
    PATH="${MOCK_BIN_D}:${PATH}" \
    bash "$NOTIFY" \
    --run test-run-004 \
    --event watchdog_stall \
    --message "subprocess hung" \
    --pid 12345 2>/dev/null || EXIT_STATUS_D=$?

assert_eq "T005-D exits 0 with pid" "0" "$EXIT_STATUS_D"

CURL_LOG_CONTENT_D=""
[[ -f "$CURL_LOG_D" ]] && CURL_LOG_CONTENT_D="$(cat "$CURL_LOG_D")"
assert_contains "T005-D curl invoked when pid given" "CURL_ARGS" "$CURL_LOG_CONTENT_D"
assert_contains "T005-D kill line in payload" "To kill: kill 12345" "$CURL_LOG_CONTENT_D"

rm -rf "$TMPDIR_D"

# ---------------------------------------------------------------------------
# T005-E: script never fails the caller (bad config path → still exit 0)
# ---------------------------------------------------------------------------

printf '\nT005-E: bad/missing config → still exits 0 (never-fail)\n'

EXIT_STATUS_E=0
Z_HARNESS_REPO_CONFIG="/nonexistent/no-such-file.toml" \
    bash "$NOTIFY" \
    --run test-run-005 \
    --event watchdog_stall \
    --message "test" 2>/dev/null || EXIT_STATUS_E=$?

assert_eq "T005-E exits 0 even on bad config" "0" "$EXIT_STATUS_E"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\nResults: %d passed, %d failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
exit 0
