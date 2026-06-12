#!/usr/bin/env bats
# tests/test_chain_runner_characterization.bats
#
# Bats companion to test_chain_runner_characterization.py.
# Runs when `bats` is available (it is not in the standard CI image —
# Python tests in the .py file are the authoritative suite).
#
# These tests re-assert the same four characterization properties against
# the overnight command's documented CLI/bash surface. After T003/T004,
# they pin chain-runner.sh's subcommands instead.
#
# Usage: bats tests/test_chain_runner_characterization.bats
#
# Dependencies: bash, python3 (inline logic only — no subprocesses calling
#               z-harness scripts that do not exist yet).

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"

# ---------------------------------------------------------------------------
# Helper: inline preset expansion (mirrors Phase 0 in z-overnight.md)
# ---------------------------------------------------------------------------
_expand_preset() {
  case "$1" in
    full-build)     echo "plan,test,implement-all,review-all" ;;
    research-build) echo "research,plan,test,implement-all,review-all" ;;
    quick-build)    echo "plan,implement-all" ;;
    attend-full)    echo "plan,audit,test,implement-all,review-all" ;;
    *)              return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# 1. test_chain_steps_ordering
# ---------------------------------------------------------------------------
@test "test_chain_steps_ordering: full-build" {
  run _expand_preset full-build
  [ "$status" -eq 0 ]
  [ "$output" = "plan,test,implement-all,review-all" ]
}

@test "test_chain_steps_ordering: research-build" {
  run _expand_preset research-build
  [ "$status" -eq 0 ]
  [ "$output" = "research,plan,test,implement-all,review-all" ]
}

@test "test_chain_steps_ordering: quick-build" {
  run _expand_preset quick-build
  [ "$status" -eq 0 ]
  [ "$output" = "plan,implement-all" ]
}

@test "test_chain_steps_ordering: attend-full = plan,audit,test,implement-all,review-all (SPEC B3)" {
  run _expand_preset attend-full
  [ "$status" -eq 0 ]
  [ "$output" = "plan,audit,test,implement-all,review-all" ]
}

@test "test_chain_steps_ordering: unknown preset exits nonzero" {
  run _expand_preset no-such-preset
  [ "$status" -ne 0 ]
}

# ---------------------------------------------------------------------------
# 2. test_state_json_shape
# ---------------------------------------------------------------------------
@test "test_state_json_shape: initial state has required keys with correct types" {
  result="$(python3 - <<'EOF'
import json, sys

def build_initial_state(chain, preset=None):
    return {
        "chain": chain, "preset_used": preset,
        "started_at": "2025-01-01T00:00:00Z", "ended_at": None,
        "status": "running", "head_sha_at_start": "abc1234",
        "z_harness_version": "unknown", "git_diff_stat_at_end": None,
        "step_runs": [
            {"step": s, "position": i, "run_id": None, "status": "queued",
             "head_sha_before": None, "head_sha_after": None,
             "started_at": None, "ended_at": None, "wall_ms": None,
             "terminal_event_kind": None, "artifact_paths": [],
             "exit_event": None, "error_event": None}
            for i, s in enumerate(chain)
        ],
    }

state = build_initial_state(["plan", "implement-all"], preset="quick-build")
assert state["status"] == "running"
assert state["ended_at"] is None
assert len(state["step_runs"]) == 2
assert all(sr["status"] == "queued" for sr in state["step_runs"])
assert state["step_runs"][0]["position"] == 0
assert state["step_runs"][1]["position"] == 1
print("ok")
EOF
)"
  [ "$result" = "ok" ]
}

# ---------------------------------------------------------------------------
# 3. test_cursor_first_non_complete
# ---------------------------------------------------------------------------
@test "test_cursor_first_non_complete: all queued -> cursor=0" {
  result="$(python3 - <<'EOF'
runs = [{"status": "queued"}, {"status": "queued"}]
cursor = next((i for i, r in enumerate(runs) if r["status"] != "complete"), len(runs))
print(cursor)
EOF
)"
  [ "$result" = "0" ]
}

@test "test_cursor_first_non_complete: first two complete, third queued -> cursor=2" {
  result="$(python3 - <<'EOF'
runs = [{"status": "complete"}, {"status": "complete"}, {"status": "queued"}]
cursor = next((i for i, r in enumerate(runs) if r["status"] != "complete"), len(runs))
print(cursor)
EOF
)"
  [ "$result" = "2" ]
}

@test "test_cursor_first_non_complete: all complete -> cursor=length" {
  result="$(python3 - <<'EOF'
runs = [{"status": "complete"}, {"status": "complete"}]
cursor = next((i for i, r in enumerate(runs) if r["status"] != "complete"), len(runs))
print(cursor)
EOF
)"
  [ "$result" = "2" ]
}

# ---------------------------------------------------------------------------
# 4. test_new_run_id_set_difference
# ---------------------------------------------------------------------------
@test "test_new_run_id_set_difference: single new dir -> unambiguous" {
  result="$(python3 - <<'EOF'
before = {"20250101T000000Z-plan-feat"}
after  = {"20250101T000000Z-plan-feat", "20250101T000100Z-impl-feat"}
def filter_overnight(s): return {n for n in s if "-overnight-" not in n}
new = sorted(filter_overnight(after) - filter_overnight(before))
print(len(new), new[0] if new else "")
EOF
)"
  count="${result%% *}"
  [ "$count" = "1" ]
}

@test "test_new_run_id_set_difference: overnight dirs excluded" {
  result="$(python3 - <<'EOF'
before = {"plan-feat"}
after  = {"plan-feat", "20250101T000000Z-overnight-feat", "20250101T000100Z-impl-feat"}
def filter_overnight(s): return {n for n in s if "-overnight-" not in n}
new = sorted(filter_overnight(after) - filter_overnight(before))
print(len(new))
EOF
)"
  [ "$result" = "1" ]
}

@test "test_new_run_id_set_difference: no new dirs -> empty (ambiguous)" {
  result="$(python3 - <<'EOF'
before = {"plan-feat"}
after  = {"plan-feat"}
def filter_overnight(s): return {n for n in s if "-overnight-" not in n}
new = sorted(filter_overnight(after) - filter_overnight(before))
print(len(new))
EOF
)"
  [ "$result" = "0" ]
}
