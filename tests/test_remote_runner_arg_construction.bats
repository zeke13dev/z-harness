#!/usr/bin/env bats
# tests/test_remote_runner_arg_construction.bats
#
# Local-only arg-construction tests for the remote-runner wrapper pattern.
# No live remote connection is needed — all remote calls are stubbed.
#
# Verifies:
#   1. remote-confined-run.sh emits "[confined-run] UNIT=<name>" to stderr
#      before the remote ssh is executed (so the caller can extract it even
#      when local ssh is killed by a timeout).
#   2. The remote-runner rsync routing pattern produces a supervised-run.sh
#      invocation with --type rsync and the expected script as the command.
#   3. The remote-runner cargo routing pattern produces a supervised-run.sh
#      invocation with --type cargo (best-effort) and the confined-run script.
#   4. The remote-runner direct ssh (read-only + cleanup) routing pattern
#      produces a supervised-run.sh invocation with --type ssh.
#
# Usage: bats tests/test_remote_runner_arg_construction.bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
CONFINED_RUN="$REPO_ROOT/scripts/remote-confined-run.sh"

setup() {
  STUBS="$(mktemp -d)"

  # Stub the supervised-run.sh: record all arguments so we can inspect them,
  # then simulate success.
  mkdir -p "$STUBS/scripts"
  cat > "$STUBS/scripts/supervised-run.sh" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${SUPERVISED_RUN_ARGV_LOG:-/dev/null}"
exit 0
EOS
  chmod +x "$STUBS/scripts/supervised-run.sh"

  ARGV_LOG="$STUBS/supervised-run.argv"

  # ssh stub for remote-confined-run.sh tests: run the heredoc locally.
  cat > "$STUBS/ssh" <<EOS
#!/usr/bin/env bash
exec /bin/sh -s
EOS

  # systemctl stub (liveness probe).
  cat > "$STUBS/systemctl" <<EOS
#!/usr/bin/env bash
exit 0
EOS

  # systemd-run stub: just exit 0 without executing the payload.
  cat > "$STUBS/systemd-run" <<EOS
#!/usr/bin/env bash
exit 0
EOS

  chmod +x "$STUBS"/ssh "$STUBS"/systemctl "$STUBS"/systemd-run

  EXECDIR="$(mktemp -d)"
  export PATH="$STUBS:$PATH"
  export Z_HARNESS_REMOTE_SSH="$STUBS/ssh"
}

teardown() {
  rm -rf "$STUBS" "$EXECDIR"
}

# ---------------------------------------------------------------------------
# 1. remote-confined-run.sh emits [confined-run] UNIT=<name> to stderr
#    before any remote execution — so it survives a local ssh kill.
# ---------------------------------------------------------------------------
@test "remote-confined-run.sh emits [confined-run] UNIT= to stderr before ssh executes" {
  run bash "$CONFINED_RUN" zeke-pc "$EXECDIR" "echo hello"
  # The UNIT= line must appear in stderr (captured as $output by bats).
  [[ "$output" == *"[confined-run] UNIT=z-harness-build-"* ]]
}

@test "remote-confined-run.sh UNIT name is extractable from stderr via grep" {
  run bash "$CONFINED_RUN" zeke-pc "$EXECDIR" "echo hello"
  unit="$(printf '%s\n' "$output" | grep '\[confined-run\] UNIT=' | sed 's/.*UNIT=//' | head -1)"
  [[ -n "$unit" ]]
  [[ "$unit" == z-harness-build-* ]]
}

# ---------------------------------------------------------------------------
# 2. rsync routing: supervised-run.sh called with --type rsync
#    Simulates the agent-doc pattern from step 3 (needs-sandbox rsync):
#      bash supervised-run.sh --run R --type rsync --timeout 0 -- bash remote-sandbox-sync.sh ...
# ---------------------------------------------------------------------------
@test "rsync routing pattern invokes supervised-run.sh with --type rsync" {
  PLUGIN_ROOT="$STUBS"
  SUPERVISED_RUN_ARGV_LOG="$ARGV_LOG"
  export SUPERVISED_RUN_ARGV_LOG

  # Stub remote-sandbox-sync.sh to exit 0 without any ssh.
  cat > "$STUBS/scripts/remote-sandbox-sync.sh" <<EOS
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$STUBS/scripts/remote-sandbox-sync.sh"

  run bash -c "
    PLUGIN_ROOT='$STUBS'
    SUPERVISED_RUN_ARGV_LOG='$ARGV_LOG'
    export SUPERVISED_RUN_ARGV_LOG
    RUN='test-run-001'
    bash \"\${PLUGIN_ROOT}/scripts/supervised-run.sh\" \
      --run \"\$RUN\" --type rsync --timeout 0 -- \
      bash \"\${PLUGIN_ROOT}/scripts/remote-sandbox-sync.sh\" 'zeke-pc' 'test-slug' 'T011'
  "
  [ "$status" -eq 0 ]

  # supervised-run.sh stub recorded its own argv: first arg should be --run, etc.
  argv="$(cat "$ARGV_LOG" 2>/dev/null || true)"
  [[ "$argv" == *"--type"* ]]
  [[ "$argv" == *"rsync"* ]]
}

# ---------------------------------------------------------------------------
# 3. cargo routing: supervised-run.sh called with --type cargo
#    Simulates the agent-doc pattern from step 4 (needs-sandbox cargo):
#      bash supervised-run.sh --run R --type cargo --timeout 0 -- bash remote-confined-run.sh ...
# ---------------------------------------------------------------------------
@test "cargo routing pattern invokes supervised-run.sh with --type cargo" {
  PLUGIN_ROOT="$STUBS"

  run bash -c "
    PLUGIN_ROOT='$STUBS'
    SUPERVISED_RUN_ARGV_LOG='$ARGV_LOG'
    export SUPERVISED_RUN_ARGV_LOG
    RUN='test-run-002'
    CONFINED_STDERR=\$(mktemp)
    bash \"\${PLUGIN_ROOT}/scripts/supervised-run.sh\" \
      --run \"\$RUN\" --type cargo --timeout 0 -- \
      bash '$CONFINED_RUN' 'zeke-pc' '$EXECDIR' 'cargo check -p mylib' \
      2>\"\$CONFINED_STDERR\"
    rm -f \"\$CONFINED_STDERR\"
  "
  [ "$status" -eq 0 ]

  argv="$(cat "$ARGV_LOG" 2>/dev/null || true)"
  [[ "$argv" == *"--type"* ]]
  [[ "$argv" == *"cargo"* ]]
}

# ---------------------------------------------------------------------------
# 4. direct-ssh routing: supervised-run.sh called with --type ssh
#    Simulates both the read-only ssh (step 4) and cleanup ssh (step 7)
#    patterns from the agent doc.
# ---------------------------------------------------------------------------
@test "direct ssh routing pattern invokes supervised-run.sh with --type ssh" {
  # Stub ssh to exit 0 without connecting anywhere.
  cat > "$STUBS/ssh" <<EOS
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$STUBS/ssh"

  run bash -c "
    PLUGIN_ROOT='$STUBS'
    SUPERVISED_RUN_ARGV_LOG='$ARGV_LOG'
    export SUPERVISED_RUN_ARGV_LOG
    RUN='test-run-003'
    bash \"\${PLUGIN_ROOT}/scripts/supervised-run.sh\" \
      --run \"\$RUN\" --type ssh --timeout 0 -- \
      ssh 'zeke-pc' 'ls /tmp'
  "
  [ "$status" -eq 0 ]

  argv="$(cat "$ARGV_LOG" 2>/dev/null || true)"
  [[ "$argv" == *"--type"* ]]
  [[ "$argv" == *"ssh"* ]]
}

@test "cleanup rm ssh routing pattern invokes supervised-run.sh with --type ssh" {
  cat > "$STUBS/ssh" <<EOS
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$STUBS/ssh"

  run bash -c "
    PLUGIN_ROOT='$STUBS'
    SUPERVISED_RUN_ARGV_LOG='$ARGV_LOG'
    export SUPERVISED_RUN_ARGV_LOG
    RUN='test-run-004'
    bash \"\${PLUGIN_ROOT}/scripts/supervised-run.sh\" \
      --run \"\$RUN\" --type ssh --timeout 0 -- \
      ssh 'zeke-pc' 'rm -rf ~/dev/qt-bot-sandbox/sandbox/test-slug/T011/'
  "
  [ "$status" -eq 0 ]

  argv="$(cat "$ARGV_LOG" 2>/dev/null || true)"
  [[ "$argv" == *"--type"* ]]
  [[ "$argv" == *"ssh"* ]]
}

# ---------------------------------------------------------------------------
# 5. orphan-possible flag: on exit 124, the agent doc pattern emits
#    watchdog_timeout{remote_orphan_possible:true}. Verify the UNIT name
#    extracted from confined-run stderr is non-empty when ssh stub exits 0
#    (i.e., the stderr line was emitted and is capturable).
# ---------------------------------------------------------------------------
@test "confined-run UNIT line is capturable from stderr via temp file" {
  CONFINED_STDERR="$(mktemp)"
  bash "$CONFINED_RUN" zeke-pc "$EXECDIR" "echo ok" 2>"$CONFINED_STDERR" || true
  REMOTE_UNIT="$(grep '\[confined-run\] UNIT=' "$CONFINED_STDERR" | sed 's/.*UNIT=//' | head -1)"
  rm -f "$CONFINED_STDERR"

  # The unit name must be extractable and must start with the expected prefix.
  [[ -n "$REMOTE_UNIT" ]]
  [[ "$REMOTE_UNIT" == z-harness-build-* ]]
}

# ---------------------------------------------------------------------------
# 6. remote-sandbox-sync.sh --sandbox-key override (T002 — per-level sandbox
#    keying for coalesced BFS level-boundary REMOTE_VERIFY dispatch).
#
#    All network calls are stubbed: `ssh` logs the remote command it was asked
#    to run and returns canned answers; `rsync` logs its argv and no-ops. This
#    lets us assert on the REMOTE_TASK_ABS / REMOTE_BASE_ABS paths the script
#    computes without touching a real host.
# ---------------------------------------------------------------------------
SYNC_SCRIPT_REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SYNC_SCRIPT="$SYNC_SCRIPT_REPO_ROOT/scripts/remote-sandbox-sync.sh"

setup_sync_stubs() {
  SYNC_STUBS="$(mktemp -d)"
  SSH_LOG="$SYNC_STUBS/ssh.log"
  RSYNC_LOG="$SYNC_STUBS/rsync.log"
  : > "$SSH_LOG"
  : > "$RSYNC_LOG"

  cat > "$SYNC_STUBS/ssh" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$SSH_LOG"
case "\$*" in
  *'printf %s "\$HOME"'*) printf '%s' "/home/tester" ;;
  *'.base-ready'*'[ -f'*) exit 0 ;;   # base already ready; skip seed step
  *) exit 0 ;;
esac
EOS
  chmod +x "$SYNC_STUBS/ssh"

  cat > "$SYNC_STUBS/rsync" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$RSYNC_LOG"
exit 0
EOS
  chmod +x "$SYNC_STUBS/rsync"
}

teardown_sync_stubs() {
  rm -rf "$SYNC_STUBS"
}

@test "remote-sandbox-sync.sh legacy path derives <slug>/<task-id> when --sandbox-key omitted" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude
  [ "$status" -eq 0 ]

  mkdir_line="$(grep 'mkdir -p --' "$SSH_LOG" | head -1)"
  [[ "$mkdir_line" == *"/dev/qt-bot-sandbox/sandbox/test-slug/T099"* ]]

  overlay_line="$(tail -1 "$RSYNC_LOG")"
  [[ "$overlay_line" == *"test-host:/home/tester/dev/qt-bot-sandbox/sandbox/test-slug/T099/"* ]]
  teardown_sync_stubs
}

@test "remote-sandbox-sync.sh --sandbox-key overrides the per-task overlay path" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key test-slug/level-2
  [ "$status" -eq 0 ]

  mkdir_line="$(grep 'mkdir -p --' "$SSH_LOG" | head -1)"
  [[ "$mkdir_line" == *"/dev/qt-bot-sandbox/sandbox/test-slug/level-2"* ]]
  [[ "$mkdir_line" != *"/T099"* ]]

  overlay_line="$(tail -1 "$RSYNC_LOG")"
  [[ "$overlay_line" == *"test-host:/home/tester/dev/qt-bot-sandbox/sandbox/test-slug/level-2/"* ]]
  teardown_sync_stubs
}

@test "remote-sandbox-sync.sh --sandbox-key still keys the warm base by slug alone" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key test-slug/level-2
  [ "$status" -eq 0 ]

  ready_check_line="$(grep '.base-ready' "$SSH_LOG" | head -1)"
  [[ "$ready_check_line" == *"/dev/qt-bot-sandbox/sandbox/test-slug/base/.base-ready"* ]]
}

@test "remote-sandbox-sync.sh rejects a --sandbox-key with path traversal" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key '../etc'
  [ "$status" -eq 2 ]
  [[ "$output" == *"invalid --sandbox-key"* ]]
  teardown_sync_stubs
}

@test "remote-sandbox-sync.sh rejects a --sandbox-key without exactly one path segment" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key 'noslash'
  [ "$status" -eq 2 ]
  [[ "$output" == *"must be exactly"* ]]

  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key 'a/b/c'
  [ "$status" -eq 2 ]
  [[ "$output" == *"must be exactly"* ]]
  teardown_sync_stubs
}

@test "remote-sandbox-sync.sh rejects --sandbox-key ending in the reserved 'base' segment" {
  setup_sync_stubs
  PATH="$SYNC_STUBS:$PATH" run bash "$SYNC_SCRIPT" test-host test-slug T099 --allow-no-exclude --sandbox-key 'test-slug/base'
  [ "$status" -eq 2 ]
  [[ "$output" == *"reserved for warm base"* ]]
  teardown_sync_stubs
}
