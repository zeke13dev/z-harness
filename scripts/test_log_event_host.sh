#!/usr/bin/env bash
# test_log_event_host.sh — T002 focused attribution tests
#
# Verifies that log-event.sh stamps authoritative host/surface fields and that
# payloads cannot override the resolved attribution.
#
# Run with:
#   bash scripts/test_log_event_host.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_EVENT="$SCRIPTS_DIR/log-event.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_log_event_host_XXXXXX"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected: $expected"
    echo "        actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected substring: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $label (found unwanted substring)"
    echo "        unwanted: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  fi
}

assert_nonempty() {
  local label="$1" value="$2"
  if [[ -n "$value" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — value was empty"
    FAIL=$((FAIL + 1))
  fi
}

# ---------------------------------------------------------------------------
# T002-A: every emitted event carries authoritative host/surface fields
#
# Invariant: log-event.sh stamps `host` on every event envelope.
# Failure class: events lack host field — host telemetry absent from metrics.jsonl
# ---------------------------------------------------------------------------

echo ""
echo "T002-A: every emitted event carries authoritative host/surface fields"

REPO_A="$(_tmpdir)"
BASE_A="$(_tmpdir)"
git -C "$REPO_A" init -q
git -C "$REPO_A" config user.email "test@test.local"
git -C "$REPO_A" config user.name "Test"

RUN_A="t004-a-run"

(
  cd "$REPO_A"
  Z_HARNESS_BASE_DIR="$BASE_A" CODEX_THREAD_ID="app-thread" \
    bash "$LOG_EVENT" "$RUN_A" "t002_event_a" '{"payload":"test","host":"claude","surface":"cli"}' 2>/dev/null
)

METRICS_A="$(cat "$BASE_A/metrics.jsonl" 2>/dev/null || echo "")"
assert_contains "T002-A: metrics host is resolved" '"host":"codex"' "$METRICS_A"
assert_contains "T002-A: metrics surface is resolved" '"surface":"app"' "$METRICS_A"

EVENTS_A="$(cat "$BASE_A/archive/$RUN_A/events.jsonl" 2>/dev/null || echo "")"
assert_contains "T002-A: events host is resolved" '"host":"codex"' "$EVENTS_A"
assert_contains "T002-A: events surface is resolved" '"surface":"app"' "$EVENTS_A"

# Verify that the existing payload fields are not corrupted
assert_contains "T002-A: payload field preserved in event" \
  '"payload":"test"' "$EVENTS_A"

assert_contains "T002-A: kind field preserved in event" \
  '"kind":"t002_event_a"' "$EVENTS_A"
assert_not_contains "T002-A: payload cannot override host" '"host":"claude"' "$EVENTS_A"
assert_not_contains "T002-A: payload cannot override surface" '"surface":"cli"' "$EVENTS_A"

rm -rf "$REPO_A" "$BASE_A"

# ---------------------------------------------------------------------------
# T002-B: explicit Codex CLI attribution is honored
#
# Invariant: the explicit pair is recorded instead of inferred evidence.
# Failure class: explicit surface is lost or host is misattributed.
# ---------------------------------------------------------------------------

echo ""
echo "T002-B: explicit Codex CLI attribution is honored"

REPO_B="$(_tmpdir)"
BASE_B="$(_tmpdir)"
git -C "$REPO_B" init -q
git -C "$REPO_B" config user.email "test@test.local"
git -C "$REPO_B" config user.name "Test"

RUN_B="t004-b-run"

(
  cd "$REPO_B"
  env -u CODEX_THREAD_ID \
    Z_HARNESS_BASE_DIR="$BASE_B" Z_HARNESS_HOST="codex" Z_HARNESS_SURFACE="cli" \
    bash "$LOG_EVENT" "$RUN_B" "t004_event_b" '{}' 2>/dev/null
)

METRICS_B="$(cat "$BASE_B/metrics.jsonl" 2>/dev/null || echo "")"
assert_contains "T002-B: host field equals explicit host" '"host":"codex"' "$METRICS_B"
assert_contains "T002-B: surface field equals explicit surface" '"surface":"cli"' "$METRICS_B"

# Verify multiple events in the same run also carry the override
(
  cd "$REPO_B"
  env -u CODEX_THREAD_ID \
    Z_HARNESS_BASE_DIR="$BASE_B" Z_HARNESS_HOST="codex" Z_HARNESS_SURFACE="cli" \
    bash "$LOG_EVENT" "$RUN_B" "t004_event_b2" '{}' 2>/dev/null
)

EVENTS_B="$(cat "$BASE_B/archive/$RUN_B/events.jsonl" 2>/dev/null || echo "")"
# Both events must carry the same explicit pair.
SECOND_LINE_B="$(printf '%s' "$EVENTS_B" | tail -1)"
assert_contains "T002-B: second event retains explicit host" '"host":"codex"' "$SECOND_LINE_B"
assert_contains "T002-B: second event retains explicit surface" '"surface":"cli"' "$SECOND_LINE_B"

rm -rf "$REPO_B" "$BASE_B"

# ---------------------------------------------------------------------------
# T002-C: missing attribution is explicitly unknown, never Claude
#
# Invariant: absent evidence remains explicitly unknown.
# Failure class: missing evidence is silently attributed to Claude.
# ---------------------------------------------------------------------------

echo ""
echo "T002-C: missing attribution is explicitly unknown"

REPO_C="$(_tmpdir)"
BASE_C="$(_tmpdir)"
git -C "$REPO_C" init -q
git -C "$REPO_C" config user.email "test@test.local"
git -C "$REPO_C" config user.name "Test"

RUN_C="t004-c-run"

# Clear all positive evidence so attribution cannot be guessed.
(
  cd "$REPO_C"
  Z_HARNESS_BASE_DIR="$BASE_C" \
    env -u Z_HARNESS_HOST \
        -u ANTIGRAVITY_PLUGIN_ROOT \
        -u PI_TOKEN \
        -u CODEX_API_KEY \
        -u CODEX_EXEC \
        -u CURSOR_API_KEY -u CLAUDE_PLUGIN_ROOT -u CODEX_THREAD_ID \
    bash "$LOG_EVENT" "$RUN_C" "t004_event_c" '{}' 2>/dev/null
)

METRICS_C="$(cat "$BASE_C/metrics.jsonl" 2>/dev/null || echo "")"
assert_contains "T002-C: host is unknown without evidence" '"host":"unknown"' "$METRICS_C"
assert_contains "T002-C: surface is unknown without evidence" '"surface":"unknown"' "$METRICS_C"

rm -rf "$REPO_C" "$BASE_C"

# ---------------------------------------------------------------------------
# T002-D: per-process sentinel cache is written and reused
#
# Invariant: a /tmp/zh-host-<PPID> sentinel is written on first call;
#   subsequent calls with the same parent PID read it without re-invoking
#   detect-host.sh. This avoids repeated shell-outs on the hot logging path.
#
# Failure class: sentinel not written, or sentinel not read on subsequent calls —
#   detect-host.sh shelled out on every log-event.sh invocation (performance regression).
#
# Strategy: we verify the sentinel mechanism by:
#   (1) cleaning all sentinels, running log-event.sh, confirming a sentinel exists
#       with a valid host value.
#   (2) writing a wrapper script that seeds a sentinel keyed on its own $$ (which
#       becomes the $PPID seen by the log-event.sh child it invokes), then confirms
#       the seeded value is used rather than the detect-host.sh default.
# ---------------------------------------------------------------------------

echo ""
echo "T002-D: per-process sentinel cache is written and reused"

REPO_D="$(_tmpdir)"
BASE_D="$(_tmpdir)"
git -C "$REPO_D" init -q
git -C "$REPO_D" config user.email "test@test.local"
git -C "$REPO_D" config user.name "Test"

RUN_D="t004-d-run"

# Resolve the real /tmp path (macOS uses /tmp -> /private/tmp symlink; find
# on the symlink path returns no results on macOS, so use the canonical path).
TMP_REAL="$(cd /tmp && pwd -P)"

# Remove any pre-existing sentinels to get a clean count.
find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -exec rm -f {} + 2>/dev/null || true

# First call — should write exactly one sentinel keyed on $PPID of the log-event.sh
# child (which equals $$ of the parent subshell that runs the call).
(
  cd "$REPO_D"
  env -u Z_HARNESS_HOST \
      -u ANTIGRAVITY_PLUGIN_ROOT \
      -u PI_TOKEN \
      -u CODEX_API_KEY \
      -u CODEX_EXEC \
      -u CURSOR_API_KEY -u CLAUDE_PLUGIN_ROOT -u CODEX_THREAD_ID \
    Z_HARNESS_BASE_DIR="$BASE_D" \
    bash "$LOG_EVENT" "$RUN_D" "t004_event_d1" '{}' 2>/dev/null
)

# Collect sentinel files written.
SENTINELS_D=()
while IFS= read -r -d '' f; do
  SENTINELS_D+=("$f")
done < <(find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -print0 2>/dev/null)

SENTINEL_COUNT_D="${#SENTINELS_D[@]}"
if [[ "$SENTINEL_COUNT_D" -ge 1 ]]; then
  echo "  PASS: T002-D: at least one sentinel written after first call ($SENTINEL_COUNT_D found)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T002-D: no sentinel written after first call"
  FAIL=$((FAIL + 1))
fi

# Verify sentinel content is a known valid host.
FIRST_SENTINEL_D="${SENTINELS_D[0]:-}"
SENTINEL_CONTENT_D=""
if [[ -n "$FIRST_SENTINEL_D" && -s "$FIRST_SENTINEL_D" ]]; then
  SENTINEL_CONTENT_D="$(cat "$FIRST_SENTINEL_D")"
fi

case "${SENTINEL_CONTENT_D:-}" in
  '{"host":"unknown","surface":"unknown"}')
    echo "  PASS: T002-D: sentinel contains canonical attribution"
    PASS=$((PASS + 1))
    ;;
  *)
    echo "  FAIL: T002-D: sentinel content '${SENTINEL_CONTENT_D:-<empty>}' is not canonical attribution"
    FAIL=$((FAIL + 1))
    ;;
esac

# Second part: verify that a pre-seeded sentinel is used instead of detect-host.sh.
# Strategy: write a wrapper script that (a) seeds a sentinel keyed on its own $$
# then (b) calls `bash log-event.sh` (NOT exec — we need the wrapper to remain
# alive so that $PPID of the child log-event.sh process = wrapper $$). If the
# sentinel is read, the host in the event will be "codex" (our seeded value) not
# the detect-host.sh default ("claude" in a clean env).
find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -exec rm -f {} + 2>/dev/null || true

WRAPPER_D="$BASE_D/wrapper.sh"
cat > "$WRAPPER_D" <<'WRAPPER_EOF'
#!/usr/bin/env bash
set -euo pipefail
# Seed a sentinel for our own PID.  When we call bash "$@" (without exec),
# the child bash process sees $PPID = our $$ and will find this sentinel.
printf '%s' '{"host":"codex","surface":"cli"}' > "/tmp/zh-host-$$"
bash "$@"
WRAPPER_EOF
chmod +x "$WRAPPER_D"

(
  cd "$REPO_D"
  env -u Z_HARNESS_HOST \
      -u ANTIGRAVITY_PLUGIN_ROOT \
      -u PI_TOKEN \
      -u CODEX_API_KEY \
      -u CODEX_EXEC \
      -u CURSOR_API_KEY -u CLAUDE_PLUGIN_ROOT -u CODEX_THREAD_ID \
    Z_HARNESS_BASE_DIR="$BASE_D" \
    bash "$WRAPPER_D" "$LOG_EVENT" "$RUN_D" "t004_event_d2" '{}' 2>/dev/null
)

# The second event should carry the complete pair from the pre-seeded sentinel.
EVENTS_D="$(cat "$BASE_D/archive/$RUN_D/events.jsonl" 2>/dev/null || echo "")"
SECOND_EVENT_D="$(printf '%s' "$EVENTS_D" | tail -1)"
assert_contains "T002-D: cached sentinel host used" \
  '"host":"codex"' "$SECOND_EVENT_D"
assert_contains "T002-D: cached sentinel surface used" \
  '"surface":"cli"' "$SECOND_EVENT_D"

# Clean up sentinels.
find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -exec rm -f {} + 2>/dev/null || true
rm -rf "$REPO_D" "$BASE_D"

# ---------------------------------------------------------------------------
# T002-E: explicit attribution is cached through the normal sentinel path
#
# Invariant: explicit pairs use the same $PPID sentinel as inferred evidence.
# Failure class: explicit attribution bypasses the cache and resolves on every
# event, increasing work on the logging path.
# ---------------------------------------------------------------------------

echo ""
echo "T002-E: explicit attribution is cached"

REPO_E="$(_tmpdir)"
BASE_E="$(_tmpdir)"
git -C "$REPO_E" init -q
git -C "$REPO_E" config user.email "test@test.local"
git -C "$REPO_E" config user.name "Test"

find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -exec rm -f {} + 2>/dev/null || true
(
  cd "$REPO_E"
  Z_HARNESS_BASE_DIR="$BASE_E" Z_HARNESS_HOST="codex" Z_HARNESS_SURFACE="cli" \
    bash "$LOG_EVENT" "t002-e-run" "t002_event_e" '{}' 2>/dev/null
)

SENTINEL_E="$(find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -print -quit 2>/dev/null)"
SENTINEL_CONTENT_E=""
if [[ -n "$SENTINEL_E" && -s "$SENTINEL_E" ]]; then
  SENTINEL_CONTENT_E="$(cat "$SENTINEL_E")"
fi
assert_eq 'T002-E: explicit pair is stored in sentinel' \
  '{"host":"codex","surface":"cli"}' "$SENTINEL_CONTENT_E"

find "$TMP_REAL" -maxdepth 1 -name 'zh-host-*' -exec rm -f {} + 2>/dev/null || true
rm -rf "$REPO_E" "$BASE_E"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
