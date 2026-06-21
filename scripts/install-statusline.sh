#!/usr/bin/env bash
# install-statusline.sh — opt-in installer for the z-harness statusLine HUD.
#
# Wires `scripts/zh-statusline.py` into a Claude Code settings.json as the
# `statusLine` command with `refreshInterval: 2`. Writes NOTHING unless you run
# it; idempotent (re-running with the same target is a no-op). Merges into the
# existing settings JSON, preserving all other keys.
#
# Usage:
#   scripts/install-statusline.sh [--target <settings.json>] [--interval N] [--print]
#
#   --target   settings file to modify (default: ~/.claude/settings.json)
#   --interval refreshInterval seconds (default: 2; min 1)
#   --print    print the statusLine block and exit — write nothing
#
# Exit codes: 0 ok / 2 bad args / 3 write error.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUD="$SCRIPT_DIR/zh-statusline.py"

TARGET="$HOME/.claude/settings.json"
INTERVAL=2
PRINT_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)   TARGET="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --print)    PRINT_ONLY=1; shift ;;
    -h|--help)  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install-statusline.sh: unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ! "$INTERVAL" =~ ^[0-9]+$ ]] || [[ "$INTERVAL" -lt 1 ]]; then
  echo "install-statusline.sh: --interval must be a positive integer" >&2
  exit 2
fi

if [[ "$PRINT_ONLY" -eq 1 ]]; then
  cat <<EOF
Add this to your Claude Code settings.json:

  "statusLine": {
    "type": "command",
    "command": "$HUD",
    "refreshInterval": $INTERVAL
  }
EOF
  exit 0
fi

python3 - "$TARGET" "$HUD" "$INTERVAL" <<'PY'
import json, os, sys

target, hud, interval = sys.argv[1], sys.argv[2], int(sys.argv[3])

data = {}
if os.path.exists(target):
    try:
        with open(target) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"install-statusline.sh: cannot parse {target}: {e}", file=sys.stderr)
        sys.exit(3)

desired = {"type": "command", "command": hud, "refreshInterval": interval}
if data.get("statusLine") == desired:
    print(f"statusLine already installed in {target} (no change).")
    sys.exit(0)

prev = data.get("statusLine")
data["statusLine"] = desired

os.makedirs(os.path.dirname(target), exist_ok=True)
tmp = target + ".tmp"
try:
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, target)
except Exception as e:
    print(f"install-statusline.sh: write failed: {e}", file=sys.stderr)
    sys.exit(3)

if prev:
    print(f"Updated statusLine in {target} (previous: {json.dumps(prev)}).")
else:
    print(f"Installed statusLine in {target}.")
print("Restart Claude Code (or it will pick up on next render).")
PY
