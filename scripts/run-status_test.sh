#!/usr/bin/env bash
# run-status_test.sh — Fixture-driven tests for scripts/run-status.sh
#
# Run with:
#   bash scripts/run-status_test.sh
#
# Uses hermetic temp directories (no side-effects on the real z-harness archive).
# Covers:
#   - clean run
#   - halt-only run
#   - error run
#   - empty events.jsonl
#   - missing events.jsonl
#   - canonical layout (z-harness/plans/<slug>/archive/<run>/)
#   - legacy layout (z-harness/<slug>/archive/<run>/)
#   - malformed trailing JSON (truncated last line)
#   - /z-implement-all combined-state check with all-done TASKS.md
#   - /z-implement-all combined-state check with one-pending TASKS.md

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_STATUS="$SCRIPTS_DIR/run-status.sh"
REPO_ROOT="$(git -C "$SCRIPTS_DIR" rev-parse --show-toplevel 2>/dev/null || pwd)"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/run_status_test_XXXXXX"
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

assert_exit_ok() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "  PASS: $label (exit 0)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expected exit 0, got $exit_code)"
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

# Build a minimal events.jsonl file at a given path.
make_events() {
  local events_file="$1"
  shift
  mkdir -p "$(dirname "$events_file")"
  printf '' > "$events_file"
  for line in "$@"; do
    printf '%s\n' "$line" >> "$events_file"
  done
}

# Build a minimal TASKS.md at the given path.
make_tasks() {
  local tasks_file="$1"
  shift
  mkdir -p "$(dirname "$tasks_file")"
  printf '# TASKS\n' > "$tasks_file"
  for line in "$@"; do
    printf '%s\n' "$line" >> "$tasks_file"
  done
}

# Run run-status.sh with a temporary REPO_ROOT override.
# We pass an absolute events-file path so layout resolution is bypassed.
run_classify() {
  local events_file="$1"
  shift
  bash "$RUN_STATUS" classify "$events_file" "$@"
}

run_last_event() {
  local events_file="$1"
  bash "$RUN_STATUS" last-event "$events_file"
}

# Run run-status.sh with a fake REPO_ROOT (for layout-resolution tests by run-id).
run_classify_with_root() {
  local fake_root="$1"
  local run_id="$2"
  shift 2
  # Override REPO_ROOT by temporarily cd-ing so git rev-parse fails and falls
  # back to pwd — but run-status.sh uses git rev-parse --show-toplevel.
  # Instead we patch via a wrapper that sets GIT_DIR to point nowhere so
  # git rev-parse returns the fake root.
  (
    cd "$fake_root"
    GIT_DIR="$fake_root/.git_fake" \
    GIT_WORK_TREE="$fake_root" \
    bash -c "
      # Force git to think the repo root is fake_root
      mkdir -p '$fake_root/.git_fake'
      printf '%s' 'gitdir: $fake_root/.git_fake' > '$fake_root/.git_fake/HEAD' 2>/dev/null || true
      # Patch: override git rev-parse by prepending a fake git on PATH
      mkdir -p '$fake_root/bin'
      printf '#!/bin/bash\n[ \"\$1\" = \"rev-parse\" ] && echo \"$fake_root\" && exit 0\nexec /usr/bin/git \"\$@\"\n' > '$fake_root/bin/git'
      chmod +x '$fake_root/bin/git'
      # Pin the artifact base into the fake repo so plan-path.sh resolves the
      # in-tmp layout (<base>/plans/<slug>/archive and legacy <base>/<slug>/archive).
      # The default base is now external (XDG state), which never contains these fixtures.
      PATH='$fake_root/bin:$PATH' Z_HARNESS_BASE_DIR='$fake_root/z-harness' bash '$RUN_STATUS' classify '$run_id' \"\$@\"
    " -- "$@"
  )
}

# ---------------------------------------------------------------------------
# TEST-001: clean run — last event is run_end
# ---------------------------------------------------------------------------
echo ""
echo "TEST-001: clean run (run_end)"

TD1="$(_tmpdir)"
EF1="$TD1/archive/run-001/events.jsonl"
make_events "$EF1" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-001","kind":"plan_start"}' \
  '{"ts":"2026-01-01T00:10:00Z","run":"run-001","kind":"run_end","status":"complete"}'

EXIT1=0; RESULT1="$(run_classify "$EF1")" || EXIT1=$?
assert_exit_ok "classify exits 0" "$EXIT1"
assert_eq "classify returns clean" "clean" "$RESULT1"

# Also test last-event
EXIT1b=0; LAST1="$(run_last_event "$EF1")" || EXIT1b=$?
assert_exit_ok "last-event exits 0" "$EXIT1b"
assert_contains "last-event returns run_end" '"kind":"run_end"' "$LAST1"

rm -rf "$TD1"

# ---------------------------------------------------------------------------
# TEST-002: halt-only run — last event is task_halt
# ---------------------------------------------------------------------------
echo ""
echo "TEST-002: halt run (task_halt)"

TD2="$(_tmpdir)"
EF2="$TD2/archive/run-002/events.jsonl"
make_events "$EF2" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-002","kind":"implement_start"}' \
  '{"ts":"2026-01-01T00:05:00Z","run":"run-002","kind":"task_halt","reason":"user_requested"}'

EXIT2=0; RESULT2="$(run_classify "$EF2")" || EXIT2=$?
assert_exit_ok "classify exits 0" "$EXIT2"
assert_eq "classify returns halted" "halted" "$RESULT2"

rm -rf "$TD2"

# ---------------------------------------------------------------------------
# TEST-003: error run — last event is run_error
# ---------------------------------------------------------------------------
echo ""
echo "TEST-003: error run (run_error)"

TD3="$(_tmpdir)"
EF3="$TD3/archive/run-003/events.jsonl"
make_events "$EF3" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-003","kind":"plan_start"}' \
  '{"ts":"2026-01-01T00:05:00Z","run":"run-003","kind":"run_error","message":"unexpected failure"}'

EXIT3=0; RESULT3="$(run_classify "$EF3")" || EXIT3=$?
assert_exit_ok "classify exits 0" "$EXIT3"
assert_eq "classify returns errored" "errored" "$RESULT3"

rm -rf "$TD3"

# ---------------------------------------------------------------------------
# TEST-004: error run — last event is "fatal"
# ---------------------------------------------------------------------------
echo ""
echo "TEST-004: error run (fatal)"

TD4="$(_tmpdir)"
EF4="$TD4/archive/run-004/events.jsonl"
make_events "$EF4" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-004","kind":"run_start"}' \
  '{"ts":"2026-01-01T00:01:00Z","run":"run-004","kind":"fatal","message":"crash"}'

EXIT4=0; RESULT4="$(run_classify "$EF4")" || EXIT4=$?
assert_exit_ok "classify exits 0" "$EXIT4"
assert_eq "classify returns errored" "errored" "$RESULT4"

rm -rf "$TD4"

# ---------------------------------------------------------------------------
# TEST-005: empty events.jsonl → unknown
# ---------------------------------------------------------------------------
echo ""
echo "TEST-005: empty events.jsonl"

TD5="$(_tmpdir)"
EF5="$TD5/archive/run-005/events.jsonl"
mkdir -p "$(dirname "$EF5")"
touch "$EF5"

EXIT5=0; RESULT5="$(run_classify "$EF5")" || EXIT5=$?
assert_exit_ok "classify exits 0" "$EXIT5"
assert_eq "classify returns unknown for empty file" "unknown" "$RESULT5"

rm -rf "$TD5"

# ---------------------------------------------------------------------------
# TEST-006: missing events.jsonl → unknown
# ---------------------------------------------------------------------------
echo ""
echo "TEST-006: missing events.jsonl"

TD6="$(_tmpdir)"
EF6="$TD6/archive/run-006/events.jsonl"
# Do not create the file

EXIT6=0; RESULT6="$(run_classify "$EF6")" || EXIT6=$?
assert_exit_ok "classify exits 0 even for missing file" "$EXIT6"
assert_eq "classify returns unknown for missing file" "unknown" "$RESULT6"

rm -rf "$TD6"

# ---------------------------------------------------------------------------
# TEST-007: canonical layout resolution by run-id (not absolute path)
#   Structure: <tmpdir>/z-harness/plans/<slug>/archive/<run>/events.jsonl
#   We pass only the run-id; resolve_events_file must find it via plan-path.sh.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-007: canonical layout resolution by run-id"

TD7="$(_tmpdir)"
SLUG7="test-canonical-slug"
RUN7="20260101T000000Z-test-canonical"
RUN_DIR7="$TD7/z-harness/plans/$SLUG7/archive/$RUN7"
EF7="$RUN_DIR7/events.jsonl"
make_events "$EF7" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-007","kind":"review_all_end","status":"complete"}'

EXIT7=0; RESULT7="$(run_classify_with_root "$TD7" "$RUN7")" || EXIT7=$?
assert_exit_ok "classify exits 0 (canonical by run-id)" "$EXIT7"
assert_eq "classify clean via canonical run-id lookup" "clean" "$RESULT7"

rm -rf "$TD7"

# ---------------------------------------------------------------------------
# TEST-007b: Z_HARNESS_PLANS_DIR override — run-id lookup uses override
#   Plans placed at <tmpdir>/custom-plans/<slug>/archive/<run>/
#   Z_HARNESS_PLANS_DIR=<tmpdir>/custom-plans must redirect the search.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-007b: Z_HARNESS_PLANS_DIR override (run-id lookup)"

TD7b="$(_tmpdir)"
CUSTOM_PLANS="$TD7b/custom-plans"
SLUG7b="test-override-slug"
RUN7b="20260101T000000Z-test-override"
RUN_DIR7b="$CUSTOM_PLANS/$SLUG7b/archive/$RUN7b"
EF7b="$RUN_DIR7b/events.jsonl"
make_events "$EF7b" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-007b","kind":"run_end","status":"complete"}'

# With correct Z_HARNESS_PLANS_DIR, run-id should be found
EXIT7b=0
RESULT7b="$(
  mkdir -p "$TD7b/bin"
  printf '#!/bin/bash\n[ "$1" = "rev-parse" ] && echo "%s" && exit 0\nexec /usr/bin/git "$@"\n' "$TD7b" > "$TD7b/bin/git"
  chmod +x "$TD7b/bin/git"
  PATH="$TD7b/bin:$PATH" Z_HARNESS_PLANS_DIR="$CUSTOM_PLANS" bash "$RUN_STATUS" classify "$RUN7b"
)" || EXIT7b=$?
assert_exit_ok "classify exits 0 (Z_HARNESS_PLANS_DIR override)" "$EXIT7b"
assert_eq "classify clean via Z_HARNESS_PLANS_DIR override" "clean" "$RESULT7b"

# Without override, same run-id should NOT be found (returns unknown for missing file)
EXIT7b_no=0
RESULT7b_no="$(
  mkdir -p "$TD7b/bin"
  PATH="$TD7b/bin:$PATH" bash "$RUN_STATUS" classify "$RUN7b"
)" || EXIT7b_no=$?
assert_exit_ok "classify exits 0 without override" "$EXIT7b_no"
assert_eq "classify unknown when Z_HARNESS_PLANS_DIR not set (run not findable)" "unknown" "$RESULT7b_no"

rm -rf "$TD7b"

# ---------------------------------------------------------------------------
# TEST-008: legacy layout resolution by run-id (not absolute path)
#   Structure: <tmpdir>/z-harness/<slug>/archive/<run>/events.jsonl
#   We pass only the run-id; resolve_events_file must find it via plan-path.sh.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-008: legacy layout resolution by run-id"

TD8="$(_tmpdir)"
SLUG8="test-legacy-slug"
RUN8="20260101T000000Z-test-legacy"
RUN_DIR8="$TD8/z-harness/$SLUG8/archive/$RUN8"
EF8="$RUN_DIR8/events.jsonl"
make_events "$EF8" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-008","kind":"amend_run_end","status":"complete"}'

EXIT8=0; RESULT8="$(run_classify_with_root "$TD8" "$RUN8")" || EXIT8=$?
assert_exit_ok "classify exits 0 (legacy by run-id)" "$EXIT8"
assert_eq "classify clean via legacy run-id lookup" "clean" "$RESULT8"

rm -rf "$TD8"

# ---------------------------------------------------------------------------
# TEST-009: malformed trailing JSON — last line truncated but prior lines valid
# ---------------------------------------------------------------------------
echo ""
echo "TEST-009: malformed trailing JSON"

TD9="$(_tmpdir)"
EF9="$TD9/archive/run-009/events.jsonl"
make_events "$EF9" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-009","kind":"brainstorm_run_end","status":"complete"}' \
  '{"ts":"2026-01-01T00:01:00Z","kind":"truncated'
# The second line is intentionally truncated (no closing brace/quote)

EXIT9=0; RESULT9="$(run_classify "$EF9")" || EXIT9=$?
assert_exit_ok "classify exits 0 despite malformed trailing line" "$EXIT9"
assert_eq "classify uses last valid event (brainstorm_run_end → clean)" "clean" "$RESULT9"

rm -rf "$TD9"

# ---------------------------------------------------------------------------
# TEST-010: malformed JSON — all lines invalid → unknown
# ---------------------------------------------------------------------------
echo ""
echo "TEST-010: all lines invalid JSON"

TD10="$(_tmpdir)"
EF10="$TD10/archive/run-010/events.jsonl"
make_events "$EF10" \
  'not-json-at-all' \
  '{broken json'

EXIT10=0; RESULT10="$(run_classify "$EF10")" || EXIT10=$?
assert_exit_ok "classify exits 0 even with all invalid JSON" "$EXIT10"
assert_eq "classify returns unknown when no valid events" "unknown" "$RESULT10"

rm -rf "$TD10"

# ---------------------------------------------------------------------------
# TEST-011: /z-implement-all — all tasks done (TASKS.md all [x] or [~])
#           last event is implement_end → clean
# ---------------------------------------------------------------------------
echo ""
echo "TEST-011: implement-all, all tasks done → clean"

TD11="$(_tmpdir)"
RUN_DIR11="$TD11/archive/run-011"
EF11="$RUN_DIR11/events.jsonl"
TASKS11="$TD11/TASKS.md"

make_events "$EF11" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-011","kind":"implement_start"}' \
  '{"ts":"2026-01-01T00:10:00Z","run":"run-011","kind":"implement_end","task":"T001"}'
make_tasks "$TASKS11" \
  "- [x] T001 — task one" \
  "- [x] T002 — task two" \
  "- [~] T003 — task three (skipped)"

EXIT11=0; RESULT11="$(bash "$RUN_STATUS" classify "$EF11" --command implement-all)" || EXIT11=$?
assert_exit_ok "classify exits 0" "$EXIT11"
assert_eq "implement-all all-done → clean" "clean" "$RESULT11"

rm -rf "$TD11"

# ---------------------------------------------------------------------------
# TEST-012: /z-implement-all — one pending task → unknown
#           last event is implement_end but TASKS.md has pending task
# ---------------------------------------------------------------------------
echo ""
echo "TEST-012: implement-all, one-pending task → unknown"

TD12="$(_tmpdir)"
RUN_DIR12="$TD12/archive/run-012"
EF12="$RUN_DIR12/events.jsonl"
TASKS12="$TD12/TASKS.md"

make_events "$EF12" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-012","kind":"implement_start"}' \
  '{"ts":"2026-01-01T00:10:00Z","run":"run-012","kind":"implement_end","task":"T001"}'
make_tasks "$TASKS12" \
  "- [x] T001 — task one" \
  "- [ ] T002 — task two (still pending)"

EXIT12=0; RESULT12="$(bash "$RUN_STATUS" classify "$EF12" --command implement-all)" || EXIT12=$?
assert_exit_ok "classify exits 0" "$EXIT12"
assert_eq "implement-all one-pending → unknown" "unknown" "$RESULT12"

rm -rf "$TD12"

# ---------------------------------------------------------------------------
# TEST-013: /z-implement-all — last event is task_halt → halted
# ---------------------------------------------------------------------------
echo ""
echo "TEST-013: implement-all, task_halt → halted"

TD13="$(_tmpdir)"
RUN_DIR13="$TD13/archive/run-013"
EF13="$RUN_DIR13/events.jsonl"
TASKS13="$TD13/TASKS.md"

make_events "$EF13" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-013","kind":"implement_start"}' \
  '{"ts":"2026-01-01T00:05:00Z","run":"run-013","kind":"task_halt","reason":"spec_problem"}'
make_tasks "$TASKS13" \
  "- [x] T001 — task one" \
  "- [ ] T002 — task two"

EXIT13=0; RESULT13="$(bash "$RUN_STATUS" classify "$EF13" --command implement-all)" || EXIT13=$?
assert_exit_ok "classify exits 0" "$EXIT13"
assert_eq "implement-all task_halt → halted" "halted" "$RESULT13"

rm -rf "$TD13"

# ---------------------------------------------------------------------------
# TEST-014: /z-implement-all — compaction_pause + all tasks done → clean
# ---------------------------------------------------------------------------
echo ""
echo "TEST-014: implement-all, compaction_pause + all done → clean"

TD14="$(_tmpdir)"
RUN_DIR14="$TD14/archive/run-014"
EF14="$RUN_DIR14/events.jsonl"
TASKS14="$TD14/TASKS.md"

make_events "$EF14" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-014","kind":"implement_end","task":"T001"}' \
  '{"ts":"2026-01-01T00:01:00Z","run":"run-014","kind":"compaction_pause"}'
make_tasks "$TASKS14" \
  "- [x] T001 — task one" \
  "- [~] T002 — task two (removed)"

EXIT14=0; RESULT14="$(bash "$RUN_STATUS" classify "$EF14" --command implement-all)" || EXIT14=$?
assert_exit_ok "classify exits 0" "$EXIT14"
assert_eq "implement-all compaction_pause + all done → clean" "clean" "$RESULT14"

rm -rf "$TD14"

# ---------------------------------------------------------------------------
# TEST-014b: /z-implement-all — TASKS.md exists but has ZERO task checkboxes → unknown
#   Guards against malformed TASKS.md being silently treated as "all done".
# ---------------------------------------------------------------------------
echo ""
echo "TEST-014b: implement-all, TASKS.md with no checkboxes → unknown"

TD14b="$(_tmpdir)"
RUN_DIR14b="$TD14b/archive/run-014b"
EF14b="$RUN_DIR14b/events.jsonl"
TASKS14b="$TD14b/TASKS.md"

make_events "$EF14b" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-014b","kind":"implement_end","task":"T001"}'
# Write a TASKS.md with no checkbox lines at all (only a header)
mkdir -p "$(dirname "$TASKS14b")"
printf '# TASKS\n\nThis file has no task checkboxes.\n' > "$TASKS14b"

EXIT14b=0; RESULT14b="$(bash "$RUN_STATUS" classify "$EF14b" --command implement-all)" || EXIT14b=$?
assert_exit_ok "classify exits 0" "$EXIT14b"
assert_eq "implement-all empty-checkbox TASKS.md → unknown (not clean)" "unknown" "$RESULT14b"

rm -rf "$TD14b"

# ---------------------------------------------------------------------------
# TEST-015: all command-specific clean terminal event kinds
# ---------------------------------------------------------------------------
echo ""
echo "TEST-015: all clean terminal event kinds"

CLEAN_KINDS=(
  "run_end"
  "amend_run_end"
  "audit_run_end"
  "brainstorm_run_end"
  "debug_run_end"
  "light_run_end"
  "plan_audit_end"
  "plan_split_run_end"
  "research_run_end"
  "review_all_end"
  "review_end"
  "test_plan_end"
  "init_docs_end"
  "maintain_docs_end"
  "doc_update_end"
  "cluster_planner_end"
)

for kind in "${CLEAN_KINDS[@]}"; do
  TD="$(_tmpdir)"
  EF="$TD/archive/run-kind/events.jsonl"
  make_events "$EF" \
    "{\"ts\":\"2026-01-01T00:00:00Z\",\"run\":\"run-kind\",\"kind\":\"$kind\"}"
  RESULT="$(run_classify "$EF")"
  assert_eq "kind $kind → clean" "clean" "$RESULT"
  rm -rf "$TD"
done

# ---------------------------------------------------------------------------
# TEST-016: halt terminal event kinds
# ---------------------------------------------------------------------------
echo ""
echo "TEST-016: halt terminal event kinds"

HALT_KINDS=(
  "task_halt"
  "docs_freshness_halt"
  "docs_staleness_halt"
  "askuser_halted"
  "unknown_ask_blocked"
  "plan_halt"
  "review_halt"
  "implement_all_halt"
  "slug_collision_halt"
  "overnight_lock_corrupt"
)

for kind in "${HALT_KINDS[@]}"; do
  TD="$(_tmpdir)"
  EF="$TD/archive/run-kind/events.jsonl"
  make_events "$EF" \
    "{\"ts\":\"2026-01-01T00:00:00Z\",\"run\":\"run-kind\",\"kind\":\"$kind\"}"
  RESULT="$(run_classify "$EF")"
  assert_eq "kind $kind → halted" "halted" "$RESULT"
  rm -rf "$TD"
done

# ---------------------------------------------------------------------------
# TEST-017: error terminal — generic *_error pattern
# ---------------------------------------------------------------------------
echo ""
echo "TEST-017: error terminal (*_error pattern)"

ERROR_KINDS=(
  "run_error"
  "task_error"
  "skill_error"
  "overnight_error"
)

for kind in "${ERROR_KINDS[@]}"; do
  TD="$(_tmpdir)"
  EF="$TD/archive/run-kind/events.jsonl"
  make_events "$EF" \
    "{\"ts\":\"2026-01-01T00:00:00Z\",\"run\":\"run-kind\",\"kind\":\"$kind\"}"
  RESULT="$(run_classify "$EF")"
  assert_eq "kind $kind → errored" "errored" "$RESULT"
  rm -rf "$TD"
done

# ---------------------------------------------------------------------------
# TEST-018: unknown event kind → unknown classification
# ---------------------------------------------------------------------------
echo ""
echo "TEST-018: unknown event kind → unknown"

TD18="$(_tmpdir)"
EF18="$TD18/archive/run-018/events.jsonl"
make_events "$EF18" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-018","kind":"some_mid_stream_event"}'

EXIT18=0; RESULT18="$(run_classify "$EF18")" || EXIT18=$?
assert_exit_ok "classify exits 0" "$EXIT18"
assert_eq "unknown kind → unknown" "unknown" "$RESULT18"

rm -rf "$TD18"

# ---------------------------------------------------------------------------
# TEST-019: last-event skips malformed, returns last valid
# ---------------------------------------------------------------------------
echo ""
echo "TEST-019: last-event on malformed trailing line"

TD19="$(_tmpdir)"
EF19="$TD19/archive/run-019/events.jsonl"
make_events "$EF19" \
  '{"ts":"2026-01-01T00:00:00Z","run":"run-019","kind":"step_one"}' \
  '{"ts":"2026-01-01T00:01:00Z","run":"run-019","kind":"step_two"}' \
  '{"ts":"2026-01-01T00:02:00Z","kind":"truncated_line'

LAST19="$(run_last_event "$EF19")"
assert_contains "last-event returns step_two (last valid)" '"kind":"step_two"' "$LAST19"

rm -rf "$TD19"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
