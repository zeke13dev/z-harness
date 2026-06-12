#!/usr/bin/env bats
# tests/test_remote_confined_run.bats
#
# Characterizes scripts/remote-confined-run.sh — the fail-closed cgroup
# confinement wrapper for heavy remote commands.
#
# Strategy: mock `ssh` so the "remote" program runs locally under `/bin/sh -s`
# with stubbed `systemd-run` / `systemctl` on PATH. For the in-unit memory.max
# assertion, the systemd-run stub re-execs the inner payload with scoped `awk` /
# `cat` stubs so we can force the cgroup read to "max" (refuse) or a number (run)
# without a real Linux cgroup.
#
# Usage: bats tests/test_remote_confined_run.bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/remote-confined-run.sh"

setup() {
  STUBS="$(mktemp -d)"
  ARGV_LOG="$STUBS/systemd-run.argv"
  EXECDIR="$(mktemp -d)"        # a real dir the inner `cd` can enter
  export Z_HARNESS_REMOTE_SSH="$STUBS/ssh"

  # ssh stub: ignore the host arg, run the heredoc program on stdin locally,
  # inheriting PATH (which has our systemd-run / systemctl stubs first).
  cat > "$STUBS/ssh" <<EOS
#!/usr/bin/env bash
# args: <host> /bin/sh -s   (program arrives on stdin)
exec /bin/sh -s
EOS

  # systemctl stub: only the `--user show-environment` liveness probe matters.
  cat > "$STUBS/systemctl" <<EOS
#!/usr/bin/env bash
if [ "\$1" = "--user" ] && [ "\$2" = "show-environment" ]; then
  exit "\${FAKE_USERMGR_RC:-0}"
fi
exit 0
EOS

  # systemd-run stub: record argv; either exit a fixed code (default) or, when
  # FAKE_PASSTHROUGH=1, parse --setenv vars and exec the trailing `/bin/sh -c
  # <inner>` with INNERBIN prepended to PATH so awk/cat are stubbed.
  cat > "$STUBS/systemd-run" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" > "$ARGV_LOG"
if [ "\${FAKE_PASSTHROUGH:-0}" = "1" ]; then
  args=("\$@"); i=0
  while [ \$i -lt \${#args[@]} ]; do
    case "\${args[\$i]}" in
      --setenv=*) export "\${args[\$i]#--setenv=}";;
      /bin/sh) sh_idx=\$i;;
    esac
    i=\$((i+1))
  done
  PATH="$STUBS/innerbin:\$PATH" exec /bin/sh "\${args[@]:\$((sh_idx+1))}"
fi
exit "\${FAKE_CMD_RC:-0}"
EOS

  # Inner-payload stubs (only consulted when FAKE_PASSTHROUGH=1).
  mkdir -p "$STUBS/innerbin"
  cat > "$STUBS/innerbin/awk" <<EOS
#!/usr/bin/env bash
# inner does: awk -F: '/^0::/{print \$3}' /proc/self/cgroup
printf '%s\n' "/user.slice/test.scope"
EOS
  cat > "$STUBS/innerbin/cat" <<EOS
#!/usr/bin/env bash
# inner does: cat "\$cg/memory.max"
case "\$1" in
  */memory.max) printf '%s\n' "\${FAKE_MEMMAX:-max}";;
  *) exec /bin/cat "\$@";;
esac
EOS

  chmod +x "$STUBS"/ssh "$STUBS"/systemctl "$STUBS"/systemd-run "$STUBS"/innerbin/*
  export PATH="$STUBS:$PATH"
}

teardown() {
  rm -rf "$STUBS" "$EXECDIR"
}

@test "usage: missing args exits 2" {
  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  run bash "$SCRIPT" host
  [ "$status" -eq 2 ]
}

@test "preflight: systemd-run absent -> refuse 97" {
  # Empty PATH for the remote shell: ssh stub runs /bin/sh -s, but the program
  # checks `command -v systemd-run`. Hide it by giving the ssh stub a bare PATH.
  cat > "$STUBS/ssh" <<EOS
#!/usr/bin/env bash
exec env PATH=/nonexistent /bin/sh -s
EOS
  chmod +x "$STUBS/ssh"
  run bash "$SCRIPT" zeke-pc "$EXECDIR" "echo hi"
  [ "$status" -eq 97 ]
  [[ "$output" == *"systemd-run not found"* ]]
}

@test "preflight: user systemd manager unreachable -> refuse 97" {
  FAKE_USERMGR_RC=1 run bash "$SCRIPT" zeke-pc "$EXECDIR" "echo hi"
  [ "$status" -eq 97 ]
  [[ "$output" == *"user systemd manager unreachable"* ]]
}

@test "wrapper carries default caps and unit" {
  FAKE_CMD_RC=0 run bash "$SCRIPT" zeke-pc "$EXECDIR" "cargo build"
  [ "$status" -eq 0 ]
  argv="$(cat "$ARGV_LOG")"
  [[ "$argv" == *"MemoryMax=10G"* ]]
  [[ "$argv" == *"MemorySwapMax=0"* ]]
  [[ "$argv" == *"CPUQuota=400%"* ]]
  [[ "$argv" == *"Nice=10"* ]]
  [[ "$argv" == *"--unit=z-harness-build-"* ]]
}

@test "env overrides flow into the wrapper" {
  Z_HARNESS_REMOTE_MEMMAX=4G Z_HARNESS_REMOTE_CPUQUOTA=200% FAKE_CMD_RC=0 \
    run bash "$SCRIPT" zeke-pc "$EXECDIR" "cargo build"
  [ "$status" -eq 0 ]
  argv="$(cat "$ARGV_LOG")"
  [[ "$argv" == *"MemoryMax=4G"* ]]
  [[ "$argv" == *"CPUQuota=200%"* ]]
}

@test "command exit code propagates on confined run" {
  FAKE_CMD_RC=7 run bash "$SCRIPT" zeke-pc "$EXECDIR" "false"
  [ "$status" -eq 7 ]
}

@test "in-unit assertion: memory.max=max -> refuse 97" {
  FAKE_PASSTHROUGH=1 FAKE_MEMMAX=max \
    run bash "$SCRIPT" zeke-pc "$EXECDIR" "echo should-not-run"
  [ "$status" -eq 97 ]
  [[ "$output" == *"memory.max=max"* ]]
  [[ "$output" != *"should-not-run"* ]]
}

@test "in-unit assertion: numeric memory.max -> command runs and propagates output" {
  FAKE_PASSTHROUGH=1 FAKE_MEMMAX=10737418240 \
    run bash "$SCRIPT" zeke-pc "$EXECDIR" "echo confined-ok"
  [ "$status" -eq 0 ]
  [[ "$output" == *"confined-ok"* ]]
}

@test "execdir with spaces survives transport: cd succeeds inside the unit" {
  # Quote-removal must keep a spaced path as ONE argv element through the
  # ssh -> systemd-run --setenv -> sh hops. The inner `cd "$Z_EXECDIR"` then
  # `pwd` proves the value arrived intact (no literal quotes, no word-split).
  SPACED="$(mktemp -d -t 'test dir.XXXX')"
  FAKE_PASSTHROUGH=1 FAKE_MEMMAX=10737418240 \
    run bash "$SCRIPT" zeke-pc "$SPACED" "pwd"
  rm -rf "$SPACED"
  [ "$status" -eq 0 ]
  [[ "$output" == *"$SPACED"* ]]
}

@test "command with shell metacharacters survives transport intact" {
  # base64 transport must preserve quotes, $ and spaces in <cmd> verbatim.
  FAKE_PASSTHROUGH=1 FAKE_MEMMAX=10737418240 \
    run bash "$SCRIPT" zeke-pc "$EXECDIR" 'echo "a b"; echo $((1+1))'
  [ "$status" -eq 0 ]
  [[ "$output" == *"a b"* ]]
  [[ "$output" == *"2"* ]]
}
