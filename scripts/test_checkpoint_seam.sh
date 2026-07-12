#!/usr/bin/env bash
# test_checkpoint_seam.sh — Tests for scripts/checkpoint-seam.sh
#
# Run with:
#   bash scripts/test_checkpoint_seam.sh
#   make test-sh   (auto-discovered by the glob scripts/*test*.sh)
#
# Per-test isolation: every case pins Z_HARNESS_BASE_DIR / Z_HARNESS_PLAN_DIR
# to its own tmp dir so nothing here ever touches real user state.
#
# Tests:
#   TC01 — usage error: fewer than 3 positional args exits 2
#   TC02 — usage error: Z_HARNESS_PLAN_DIR unset exits 2
#   TC03 — below threshold (no TASKS.md, pressure disabled): exit 0, no
#          handoff.json written
#   TC04 — legacy task-count trigger fires: exit 1, handoff.json written with
#          the exact resume-cmd, and STATUS: clear_checkpoint on stdout
#   TC05 — second call against the SAME durable artifact/hash fast-forwards:
#          exit 0, STATUS: clear_checkpoint_fast_forward on stdout
#   TC06 — --hash includes a second file in the fast-forward guard: changing
#          that file's content busts the fast-forward (state now stale ->
#          rejected per default --stale-mode reject, non-zero from
#          write-clear-checkpoint.sh surfaces as checkpoint-seam.sh exit 1)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SEAM_SH="$SCRIPTS_DIR/checkpoint-seam.sh"

PASS=0
FAIL=0

CLEANUP_DIRS=()
_cleanup() {
  for d in "${CLEANUP_DIRS[@]:-}"; do
    [[ -n "$d" && -d "$d" ]] && rm -rf "$d" 2>/dev/null || true
  done
}
trap _cleanup EXIT

_tmpdir() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/test_checkpoint_seam_XXXXXX")"
  CLEANUP_DIRS+=("$d")
  printf '%s' "$d"
}

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

# ---------------------------------------------------------------------------
# TC01 — usage error: fewer than 3 positional args exits 2
# ---------------------------------------------------------------------------
printf '\nTC01: fewer than 3 positional args exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$tmp" \
    bash "$SEAM_SH" only-seam-id only-artifact >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC01: missing resume-cmd arg" "$RC"
}

# ---------------------------------------------------------------------------
# TC02 — usage error: Z_HARNESS_PLAN_DIR unset exits 2
# ---------------------------------------------------------------------------
printf '\nTC02: Z_HARNESS_PLAN_DIR unset exits 2\n'
{
  tmp="$(_tmpdir)"
  RC=0
  env -u Z_HARNESS_PLAN_DIR Z_HARNESS_BASE_DIR="$tmp" \
    bash "$SEAM_SH" seam-a "$tmp/artifact.md" "/z-explore --resume-phase=seam-a" \
    >/dev/null 2>/dev/null || RC=$?
  assert_rc 2 "TC02: Z_HARNESS_PLAN_DIR unset" "$RC"
}

# ---------------------------------------------------------------------------
# TC03 — below threshold (no TASKS.md, pressure disabled): exit 0, no
# handoff.json written
# ---------------------------------------------------------------------------
printf '\nTC03: below threshold -> exit 0, no handoff.json written\n'
{
  tmp="$(_tmpdir)"
  plan_dir="$tmp/plan"
  mkdir -p "$plan_dir"
  artifact="$plan_dir/research-draft.md"
  printf 'draft v1\n' > "$artifact"

  RC=0
  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    bash "$SEAM_SH" tc03-seam "$artifact" "/z-explore --resume-phase=tc03-seam" \
    >/dev/null 2>/dev/null || RC=$?
  assert_rc 0 "TC03: below threshold continues normally" "$RC"

  if [[ -f "$plan_dir/handoff.json" ]]; then
    printf '  FAIL: TC03: handoff.json was written despite no trigger\n'
    FAIL=$((FAIL + 1))
  else
    printf '  PASS: TC03: no handoff.json written\n'
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# TC04 — legacy task-count trigger fires: exit 1, handoff.json written with
# the exact resume-cmd, STATUS: clear_checkpoint on stdout
# ---------------------------------------------------------------------------
printf '\nTC04: legacy task-count trigger -> exit 1, handoff.json written\n'
{
  tmp="$(_tmpdir)"
  plan_dir="$tmp/plan"
  mkdir -p "$plan_dir"
  artifact="$plan_dir/research-draft.md"
  printf 'draft v1\n' > "$artifact"
  printf '## T001 -- sample task `[x]`\n' > "$plan_dir/TASKS.md"

  RESUME_CMD="/z-explore --depth=deep tc04-topic --resume-phase=tc04-seam --resume-run=20260710T000000Z-tc04"

  OUT=""
  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    Z_IMPLEMENT_PAUSE_TASKS=1 Z_IMPLEMENT_PAUSE_MINUTES=0 \
    bash "$SEAM_SH" tc04-seam "$artifact" "$RESUME_CMD" 2>&1)" || RC=$?
  assert_rc 1 "TC04: task-count trigger pauses" "$RC"
  assert_contains "TC04: stdout carries STATUS: clear_checkpoint" "STATUS: clear_checkpoint" "$OUT"

  assert_true "TC04: handoff.json exists" "$([[ -f "$plan_dir/handoff.json" ]]; echo $?)"

  RESUME_IN_HANDOFF="$(python3 -c "
import json
d = json.load(open('$plan_dir/handoff.json'))
print(d.get('next_step',''))
" 2>/dev/null || true)"
  assert_contains "TC04: handoff.json next_step mentions the seam's resume command" "$RESUME_CMD" "$RESUME_IN_HANDOFF"
}

# ---------------------------------------------------------------------------
# TC05 — second call against the SAME durable artifact/hash fast-forwards:
# exit 0, STATUS: clear_checkpoint_fast_forward on stdout
# ---------------------------------------------------------------------------
printf '\nTC05: second call with unchanged artifact fast-forwards\n'
{
  tmp="$(_tmpdir)"
  plan_dir="$tmp/plan"
  mkdir -p "$plan_dir"
  artifact="$plan_dir/research-draft.md"
  printf 'draft v1\n' > "$artifact"
  printf '## T001 -- sample task `[x]`\n' > "$plan_dir/TASKS.md"

  RESUME_CMD="/z-explore --depth=deep tc05-topic --resume-phase=tc05-seam --resume-run=20260710T000000Z-tc05"

  # First call: trigger + write the checkpoint state file.
  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    Z_IMPLEMENT_PAUSE_TASKS=1 Z_IMPLEMENT_PAUSE_MINUTES=0 \
    bash "$SEAM_SH" tc05-seam "$artifact" "$RESUME_CMD" >/dev/null 2>&1 || true

  # Force a second trigger window (bump the pending-task delta again) but the
  # ARTIFACT CONTENT is unchanged, so the fast-forward guard hash matches the
  # state file written by the first call.
  printf '## T001 -- sample task `[x]`\n## T002 -- sample task 2 `[x]`\n' > "$plan_dir/TASKS.md"

  OUT=""
  RC=0
  OUT="$(Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    Z_IMPLEMENT_PAUSE_TASKS=1 Z_IMPLEMENT_PAUSE_MINUTES=0 \
    bash "$SEAM_SH" tc05-seam "$artifact" "$RESUME_CMD" 2>&1)" || RC=$?
  assert_rc 0 "TC05: fast-forward continues normally (exit 0)" "$RC"
  assert_contains "TC05: stdout carries STATUS: clear_checkpoint_fast_forward" "STATUS: clear_checkpoint_fast_forward" "$OUT"
}

# ---------------------------------------------------------------------------
# TC06 — --hash includes a second file; changing it busts the fast-forward
# (reject stale-mode default -> non-zero from write-clear-checkpoint.sh ->
# checkpoint-seam.sh surfaces exit 1)
# ---------------------------------------------------------------------------
printf '\nTC06: --hash file change busts fast-forward (stale rejected)\n'
{
  tmp="$(_tmpdir)"
  plan_dir="$tmp/plan"
  mkdir -p "$plan_dir"
  artifact="$plan_dir/MAP.md"
  extra="$plan_dir/critique-manifest.json"
  printf 'map v1\n' > "$artifact"
  printf '{"v":1}\n' > "$extra"
  printf '## T001 -- sample task `[x]`\n' > "$plan_dir/TASKS.md"

  RESUME_CMD="/z-explore --depth=deep tc06-topic --resume-phase=tc06-seam --resume-run=20260710T000000Z-tc06"

  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    Z_IMPLEMENT_PAUSE_TASKS=1 Z_IMPLEMENT_PAUSE_MINUTES=0 \
    bash "$SEAM_SH" tc06-seam "$artifact" "$RESUME_CMD" --hash "$extra" >/dev/null 2>&1 || true

  # Mutate the extra hashed file — the guard hash now differs from the
  # persisted state file, so the next call must NOT fast-forward.
  printf '{"v":2}\n' > "$extra"
  printf '## T001 -- sample task `[x]`\n## T002 -- sample task 2 `[x]`\n' > "$plan_dir/TASKS.md"

  RC=0
  Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_PLAN_DIR="$plan_dir" \
    Z_HARNESS_CONTEXT_PRESSURE_ENABLED=false \
    Z_IMPLEMENT_PAUSE_TASKS=1 Z_IMPLEMENT_PAUSE_MINUTES=0 \
    bash "$SEAM_SH" tc06-seam "$artifact" "$RESUME_CMD" --hash "$extra" \
    >/dev/null 2>/dev/null || RC=$?
  assert_rc 1 "TC06: stale fast-forward guard rejected -> non-fast-forward pause" "$RC"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
