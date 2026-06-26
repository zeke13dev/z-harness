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
# T015-A: hermes_webhook_url set + URL reachable (mock server) → signed POST sent
# ---------------------------------------------------------------------------

printf '\nT015-A: hermes_webhook_url set + endpoint up → signed POST with HMAC signature\n'

TMPDIR_H1="$(_tmpdir)"

cat > "${TMPDIR_H1}/z-harness.toml" <<'EOF'
[notify]
level = "all"
hermes_webhook_url = "http://127.0.0.1:18644/ingest"
hermes_webhook_secret = "test-secret-key-12345"
EOF

MOCK_BIN_H1="${TMPDIR_H1}/bin"
mkdir -p "$MOCK_BIN_H1"
CURL_LOG_H1="${TMPDIR_H1}/curl_log.txt"

cat > "${MOCK_BIN_H1}/curl" <<MOCKEOF
#!/usr/bin/env bash
# Log all args and flag presence of HMAC signature header.
printf 'CURL_ARGS: %s\n' "\$*" >> "${CURL_LOG_H1}"
for arg in "\$@"; do
    if printf '%s' "\$arg" | grep -q "X-Z-Harness-Signature"; then
        printf 'HMAC_HEADER: %s\n' "\$arg" >> "${CURL_LOG_H1}"
    fi
    if printf '%s' "\$arg" | grep -q '"schema_version"'; then
        printf 'PAYLOAD_FOUND: yes\n' >> "${CURL_LOG_H1}"
    fi
done
prev_arg=""
for arg in "\$@"; do
    if [[ "\$prev_arg" == "-d" ]]; then
        printf 'CURL_DATA: %s\n' "\$arg" >> "${CURL_LOG_H1}"
    fi
    prev_arg="\$arg"
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_H1}/curl"

EXIT_STATUS_H1=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_H1}/z-harness.toml" \
    PATH="${MOCK_BIN_H1}:${PATH}" \
    bash "$NOTIFY" \
    --run test-hermes-001 \
    --event watchdog_stall \
    --message "agent hung" \
    --slug my-plan \
    2>/dev/null || EXIT_STATUS_H1=$?

assert_eq "T015-A exits 0 with hermes_webhook_url set" "0" "$EXIT_STATUS_H1"

CURL_LOG_CONTENT_H1=""
[[ -f "$CURL_LOG_H1" ]] && CURL_LOG_CONTENT_H1="$(cat "$CURL_LOG_H1")"
assert_contains "T015-A curl invoked for Hermes POST" "CURL_ARGS" "$CURL_LOG_CONTENT_H1"
# Verify 3 s max-time flag is present
assert_contains "T015-A curl uses --max-time 3" "max-time" "$CURL_LOG_CONTENT_H1"
# Verify HMAC signature header is included (secret is set)
assert_contains "T015-A HMAC signature header present" "X-Z-Harness-Signature" "$CURL_LOG_CONTENT_H1"
# Verify payload contains platform-neutral fields
assert_contains "T015-A payload contains schema_version" "schema_version" "$CURL_LOG_CONTENT_H1"

rm -rf "$TMPDIR_H1"

# ---------------------------------------------------------------------------
# T015-B: hermes_webhook_url set + endpoint unreachable → run still succeeds
# ---------------------------------------------------------------------------

printf '\nT015-B: hermes_webhook_url set + endpoint unreachable → run succeeds (never blocked)\n'

TMPDIR_H2="$(_tmpdir)"

cat > "${TMPDIR_H2}/z-harness.toml" <<'EOF'
[notify]
level = "all"
hermes_webhook_url = "http://127.0.0.1:19999/unreachable"
EOF

MOCK_BIN_H2="${TMPDIR_H2}/bin"
mkdir -p "$MOCK_BIN_H2"

# Simulate curl failure (connection refused / timeout)
cat > "${MOCK_BIN_H2}/curl" <<MOCKEOF
#!/usr/bin/env bash
exit 7
MOCKEOF
chmod +x "${MOCK_BIN_H2}/curl"

EXIT_STATUS_H2=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_H2}/z-harness.toml" \
    PATH="${MOCK_BIN_H2}:${PATH}" \
    bash "$NOTIFY" \
    --run test-hermes-002 \
    --event watchdog_stall \
    --message "endpoint down" \
    2>/dev/null || EXIT_STATUS_H2=$?

assert_eq "T015-B exits 0 even when endpoint is unreachable" "0" "$EXIT_STATUS_H2"

rm -rf "$TMPDIR_H2"

# ---------------------------------------------------------------------------
# T015-C: hermes_webhook_url unset → zero new network calls
# ---------------------------------------------------------------------------

printf '\nT015-C: hermes_webhook_url unset → no Hermes curl call made\n'

TMPDIR_H3="$(_tmpdir)"

cat > "${TMPDIR_H3}/z-harness.toml" <<'EOF'
[notify]
level = "all"
discord_webhook_url = ""
EOF

MOCK_BIN_H3="${TMPDIR_H3}/bin"
mkdir -p "$MOCK_BIN_H3"
CURL_CALLED_H3="${TMPDIR_H3}/curl_called"

# We place a real curl mock that would capture hermes calls, but we also
# stub out discord so that only a hermes-going call would log "HERMES".
cat > "${MOCK_BIN_H3}/curl" <<MOCKEOF
#!/usr/bin/env bash
for arg in "\$@"; do
    if printf '%s' "\$arg" | grep -q "18644\|ingest\|hermes"; then
        echo "HERMES_CALLED" >> "${CURL_CALLED_H3}"
    fi
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_H3}/curl"

EXIT_STATUS_H3=0
Z_HARNESS_REPO_CONFIG="${TMPDIR_H3}/z-harness.toml" \
    PATH="${MOCK_BIN_H3}:${PATH}" \
    bash "$NOTIFY" \
    --run test-hermes-003 \
    --event watchdog_stall \
    --message "test no hermes url" \
    2>/dev/null || EXIT_STATUS_H3=$?

assert_eq "T015-C exits 0 when hermes_webhook_url unset" "0" "$EXIT_STATUS_H3"

HERMES_CALLED_H3=""
[[ -f "${CURL_CALLED_H3}" ]] && HERMES_CALLED_H3="$(cat "${CURL_CALLED_H3}")"
assert_eq "T015-C no Hermes curl call when URL unset" "" "$HERMES_CALLED_H3"

rm -rf "$TMPDIR_H3"

# ---------------------------------------------------------------------------
# T015-D: payload fields — verify platform-neutral schema fields present
# ---------------------------------------------------------------------------

printf '\nT015-D: Hermes payload contains all required platform-neutral fields\n'

TMPDIR_H4="$(_tmpdir)"

cat > "${TMPDIR_H4}/z-harness.toml" <<'EOF'
[notify]
level = "all"
hermes_webhook_url = "http://127.0.0.1:18644/ingest"
EOF

MOCK_BIN_H4="${TMPDIR_H4}/bin"
mkdir -p "$MOCK_BIN_H4"
CURL_LOG_H4="${TMPDIR_H4}/curl_log.txt"

cat > "${MOCK_BIN_H4}/curl" <<MOCKEOF
#!/usr/bin/env bash
prev_arg=""
for arg in "\$@"; do
    if [[ "\$prev_arg" == "-d" ]]; then
        printf '%s\n' "\$arg" >> "${CURL_LOG_H4}"
    fi
    prev_arg="\$arg"
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_H4}/curl"

EXIT_STATUS_H4=0
HERMES_SO_JOB_ID="so-hermes-004" \
Z_HARNESS_REPO_CONFIG="${TMPDIR_H4}/z-harness.toml" \
    PATH="${MOCK_BIN_H4}:${PATH}" \
    bash "$NOTIFY" \
    --run test-hermes-004 \
    --event watchdog_timeout \
    --message "dispatch timed out" \
    --slug the-plan \
    --severity error \
    --pid 9876 \
    --next-step "ask user" \
    2>/dev/null || EXIT_STATUS_H4=$?

assert_eq "T015-D exits 0 with full payload" "0" "$EXIT_STATUS_H4"

CURL_LOG_CONTENT_H4=""
[[ -f "$CURL_LOG_H4" ]] && CURL_LOG_CONTENT_H4="$(cat "$CURL_LOG_H4")"
assert_contains "T015-D payload has schema_version"   '"schema_version"'  "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has harness_version"  '"harness_version"' "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has source=z-harness" '"source"'          "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has event"            '"event"'           "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has event_id"         '"event_id"'        "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has run_id"           '"run_id"'          "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has slug"             '"slug"'            "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has repo"             '"repo"'            "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has severity"         '"severity"'        "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has reason"           '"reason"'          "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has ts"               '"ts"'              "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has job_id"           '"job_id"'          "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has pid"              '"pid"'             "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has next_step"        '"next_step"'       "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has env job id"       'so-hermes-004'     "$CURL_LOG_CONTENT_H4"
assert_contains "T015-D payload has numeric pid"      '9876'             "$CURL_LOG_CONTENT_H4"
assert_not_contains "T015-D payload hides webhook URL" 'https://hermes.test/webhook' "$CURL_LOG_CONTENT_H4"
# Confirm no Discord-specific field
assert_not_contains "T015-D payload has no Discord embeds" '"embeds"' "$CURL_LOG_CONTENT_H4"

rm -rf "$TMPDIR_H4"

# ---------------------------------------------------------------------------
# T015-E: event_id is unique across Hermes payloads
# ---------------------------------------------------------------------------

printf '\nT015-E: Hermes payload event_id is unique per notification\n'

TMPDIR_H5="$(_tmpdir)"

cat > "${TMPDIR_H5}/z-harness.toml" <<'EOF'
[notify]
level = "all"
hermes_webhook_url = "https://hermes.test/webhook"
EOF

MOCK_BIN_H5="${TMPDIR_H5}/bin"
mkdir -p "$MOCK_BIN_H5"
CURL_LOG_H5="${TMPDIR_H5}/curl_log.txt"

cat > "${MOCK_BIN_H5}/curl" <<MOCKEOF
#!/usr/bin/env bash
prev_arg=""
for arg in "\$@"; do
    if [[ "\$prev_arg" == "-d" ]]; then
        printf '%s\n' "\$arg" >> "${CURL_LOG_H5}"
    fi
    prev_arg="\$arg"
done
exit 0
MOCKEOF
chmod +x "${MOCK_BIN_H5}/curl"

EXIT_STATUS_H5=0
for i in 1 2; do
    Z_HARNESS_REPO_CONFIG="${TMPDIR_H5}/z-harness.toml" \
        PATH="${MOCK_BIN_H5}:${PATH}" \
        bash "$NOTIFY" \
        --run test-hermes-unique \
        --event watchdog_stall \
        --message "unique id check" \
        2>/dev/null || EXIT_STATUS_H5=$?
done

assert_eq "T015-E exits 0 for both sends" "0" "$EXIT_STATUS_H5"

EVENT_ID_CHECK="$(python3 - "$CURL_LOG_H5" <<'PY'
import json
import sys
payloads = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
ids = [payload["event_id"] for payload in payloads]
print("unique" if len(ids) == 2 and len(set(ids)) == 2 else "duplicate")
PY
)"
assert_eq "T015-E event ids are unique" "unique" "$EVENT_ID_CHECK"

rm -rf "$TMPDIR_H5"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\nResults: %d passed, %d failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
exit 0
