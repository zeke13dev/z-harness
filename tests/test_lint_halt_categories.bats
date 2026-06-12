#!/usr/bin/env bats
# tests/test_lint_halt_categories.bats
#
# Bats companion to tests/test_lint_halt_categories.py.
# Runs when `bats` is available.
#
# Usage: bats tests/test_lint_halt_categories.bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/lint-halt-categories.sh"

# Create a temp dir with a minimal commands/ layout for each test.
setup() {
  TMPDIR_CMD="$(mktemp -d)"
  mkdir -p "$TMPDIR_CMD/commands"
}

teardown() {
  rm -rf "$TMPDIR_CMD"
}

# Helper: write a one-liner RUNTIME-GATE comment into a fresh test command file.
_write_gate() {
  local line="$1"
  printf '%s\n' "$line" > "$TMPDIR_CMD/commands/cmd.md"
}

# ---------------------------------------------------------------------------
# 1. In-enum category -> exit 0, no ERROR on stdout/stderr
# ---------------------------------------------------------------------------
@test "in-enum category: exit 0" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=decision -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

@test "in-enum category 'risk': exit 0" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=risk -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

@test "in-enum category 'mechanical_proceed': exit 0" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

@test "in-enum category 'shortcut': exit 0" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=shortcut -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

@test "in-enum category 'archiving': exit 0" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=archiving -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# 2. Out-of-enum category -> exit non-zero + ERROR on stderr
# ---------------------------------------------------------------------------
@test "out-of-enum category: exit 1" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=bogus_value -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -ne 0 ]
}

@test "out-of-enum category: ERROR message on stderr" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=not_a_real_category -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -ne 0 ]
  # stderr is captured in $output by bats when run is used
  [[ "$output" =~ "not_a_real_category" ]]
}

# MAJOR 1: valid enum prefix + trailing junk after a hyphen must be rejected
# as a complete-token enum violation (no silent prefix acceptance).
@test "valid-prefix-with-junk (risk-foo): enum violation, exit 1" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=risk-foo -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -ne 0 ]
  [[ "$output" =~ "risk-foo" ]]
}

# MAJOR 2: wrong-case token is a hard enum violation, not a missing-category warn.
@test "wrong-case category (Risk): enum violation not warning, exit 1" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; category=Risk -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -ne 0 ]
  [[ "$output" =~ "ERROR" ]]
  [[ ! "$output" =~ "no category= token" ]]
}

# MAJOR 3: documented single-line requirement — a category= token wrapped onto
# a second physical line is reported as missing-category (warn, exit 0).
@test "category on second physical line: missing-category warn by design" {
  {
    printf '%s\n' "<!-- RUNTIME-GATE: ask_user; gate text wraps here"
    printf '%s\n' "     category=decision -->"
  } > "$TMPDIR_CMD/commands/cmd.md"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "WARN" ]]
}

# ---------------------------------------------------------------------------
# 3. Missing category -> exit 0 (warn) by default, exit 1 under --strict
# ---------------------------------------------------------------------------
@test "missing category: exit 0 by default (warn)" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

@test "missing category: WARN appears in output" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "WARN" ]]
}

@test "missing category --strict: exit 1" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; no category token here -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands" --strict
  [ "$status" -ne 0 ]
}

@test "missing category --strict: ERROR in output" {
  _write_gate "<!-- RUNTIME-GATE: ask_user; no category token here -->"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands" --strict
  [[ "$output" =~ "ERROR" ]]
}

# ---------------------------------------------------------------------------
# 4. Non-ask_user RUNTIME-GATE is ignored
# ---------------------------------------------------------------------------
@test "subagent RUNTIME-GATE gate is not flagged" {
  printf '%s\n' "<!-- RUNTIME-GATE: subagent; non-supporting drivers skip -->" \
    > "$TMPDIR_CMD/commands/cmd.md"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
  # No WARN lines for subagent-type gates
  [[ ! "$output" =~ "WARN" ]]
}

# ---------------------------------------------------------------------------
# 5. Empty commands dir -> clean exit 0
# ---------------------------------------------------------------------------
@test "empty commands dir: exit 0" {
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# 6. --check-chain with unknown preset degrades gracefully (exit 0)
# ---------------------------------------------------------------------------
@test "check-chain unknown preset: exit 0" {
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands" --check-chain unknown_preset_xyz
  [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# 7. --check-chain with known preset lists uncategorized gates
# ---------------------------------------------------------------------------
@test "check-chain attend-full: lists uncategorized gate" {
  # Write a fake z-plan.md with one uncategorized gate
  printf '%s\n' "<!-- RUNTIME-GATE: ask_user; some gate -->" \
    > "$TMPDIR_CMD/commands/z-plan.md"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands" --check-chain attend-full
  [ "$status" -eq 0 ]
  [[ "$output" =~ "z-plan.md" ]]
}

# ---------------------------------------------------------------------------
# 8. Mixed file: bad + missing in same file
# ---------------------------------------------------------------------------
@test "bad and missing in same file: exit 1" {
  {
    printf '%s\n' "<!-- RUNTIME-GATE: ask_user; category=bad_enum -->"
    printf '%s\n' "<!-- RUNTIME-GATE: ask_user; no category -->"
    printf '%s\n' "<!-- RUNTIME-GATE: ask_user; category=risk -->"
  } > "$TMPDIR_CMD/commands/cmd.md"
  run bash "$SCRIPT" --commands-dir "$TMPDIR_CMD/commands"
  [ "$status" -ne 0 ]
  [[ "$output" =~ "ERROR" ]]
  [[ "$output" =~ "WARN" ]]
}
