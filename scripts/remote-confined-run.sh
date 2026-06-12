#!/usr/bin/env bash
# remote-confined-run.sh — run a heavy command on a remote host inside a
# memory-capped `systemd-run --user` transient unit.
#
# Fail-closed: if confinement cannot be guaranteed (systemd-run absent, user
# systemd manager unreachable, or the unit's own memory.max is still "max"),
# REFUSE with exit 97 instead of running the command unconfined. This exists
# because an unconfined `libduckdb-sys` build load-crushed zeke-pc for 3h on
# 2026-06-12 — the supposed `qt-batch.slice` confinement never existed, so the
# build ran with no memory cap. The same build confined finished in 7m35s.
#
# Usage:
#   remote-confined-run.sh <host> <execdir> <cmd>
#     <cmd> is run via `sh -c` after `cd <execdir>`, inside the transient unit.
#
# Env overrides (all optional):
#   Z_HARNESS_REMOTE_MEMMAX   memory ceiling   (default 10G)
#   Z_HARNESS_REMOTE_SWAPMAX  swap ceiling     (default 0)
#   Z_HARNESS_REMOTE_CPUQUOTA cpu quota        (default 400%)
#   Z_HARNESS_REMOTE_NICE     nice level       (default 10)
#   Z_HARNESS_REMOTE_SSH      ssh binary       (default ssh; override for tests)
#
# Exit codes:
#   97  REFUSED — confinement could not be guaranteed (the command never ran)
#   *   the wrapped command's own exit code on a confined run
set -eu

usage() {
  echo "usage: remote-confined-run.sh <host> <execdir> <cmd>" >&2
  exit 2
}

HOST="${1:-}"; [ -n "$HOST" ] || usage
EXECDIR="${2:-}"; [ -n "$EXECDIR" ] || usage
CMD="${3:-}"; [ -n "$CMD" ] || usage

MEMMAX="${Z_HARNESS_REMOTE_MEMMAX:-10G}"
SWAPMAX="${Z_HARNESS_REMOTE_SWAPMAX:-0}"
CPUQUOTA="${Z_HARNESS_REMOTE_CPUQUOTA:-400%}"
NICE="${Z_HARNESS_REMOTE_NICE:-10}"
SSH_BIN="${Z_HARNESS_REMOTE_SSH:-ssh}"

UNIT="z-harness-build-$$"

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# Fixed payload that runs INSIDE the transient unit. It asserts the unit's own
# effective cgroup memory.max is a real number (not "max") BEFORE running the
# command, so a silently-rejected MemoryMax property fails closed rather than
# running unconfined. cgroup v2: /proc/self/cgroup is a single `0::<path>` line;
# a v1 host (no `0::` line) yields an empty path -> memory.max missing -> refuse.
# EXECDIR and the real command arrive as env vars (Z_EXECDIR, Z_CMD_B64) so this
# script body needs no interpolation and survives quoting intact.
INNER_SCRIPT="$(cat <<'EOS'
cg="/sys/fs/cgroup$(awk -F: '/^0::/{print $3}' /proc/self/cgroup)"
mm="$(cat "$cg/memory.max" 2>/dev/null || echo missing)"
if [ "$mm" = max ] || [ "$mm" = missing ]; then
  echo "REFUSED confinement_unavailable: memory.max=$mm (cgroup=$cg)" >&2
  exit 97
fi
cd "$Z_EXECDIR" || { echo "REFUSED confinement_unavailable: cannot cd $Z_EXECDIR" >&2; exit 97; }
exec sh -c "$(printf %s "$Z_CMD_B64" | base64 -d)"
EOS
)"

INNER_B64="$(b64 "$INNER_SCRIPT")"
EXECDIR_B64="$(b64 "$EXECDIR")"
CMD_B64="$(b64 "$CMD")"

# Remote program fed over stdin (so nothing is quoted through argv). The only
# locally-expanded tokens are base64 blobs (no shell metacharacters) and the
# simple cap values; every remote-side `$` is escaped as `\$`.
"$SSH_BIN" "$HOST" /bin/sh -s <<EOF
set -u
command -v systemd-run >/dev/null 2>&1 || { echo "REFUSED confinement_unavailable: systemd-run not found" >&2; exit 97; }
systemctl --user show-environment >/dev/null 2>&1 || { echo "REFUSED confinement_unavailable: user systemd manager unreachable (try: loginctl enable-linger)" >&2; exit 97; }
exec systemd-run --user --pipe --wait --collect \\
  -p MemoryMax=$MEMMAX -p MemorySwapMax=$SWAPMAX -p CPUQuota=$CPUQUOTA -p Nice=$NICE \\
  --unit=$UNIT \\
  --setenv=Z_EXECDIR="\$(printf %s $EXECDIR_B64 | base64 -d)" \\
  --setenv=Z_CMD_B64=$CMD_B64 \\
  /bin/sh -c "\$(printf %s $INNER_B64 | base64 -d)"
EOF
