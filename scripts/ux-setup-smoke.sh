#!/usr/bin/env bash
# ux-setup-smoke.sh — hermetic first-run UX smoke for setup/download paths.
# Uses a temp HOME and mocked host/provider binaries. It must not touch the
# maintainer's real ~/.claude, ~/.codex, ~/.cursor, ~/.agents, or ~/plugins.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORK_DIR="${TMPDIR:-/tmp}/z-harness-ux-setup-smoke"
export Z_HARNESS_UX_SMOKE_HOME="$WORK_DIR/home"
MOCK_BIN="$WORK_DIR/bin"
OUT_DIR="$REPO_ROOT/temp/ux-setup-smoke"

rm -rf "$WORK_DIR" "$OUT_DIR"
cleanup() {
  rm -rf "$OUT_DIR"
}
trap cleanup EXIT
mkdir -p "$Z_HARNESS_UX_SMOKE_HOME" "$MOCK_BIN" "$OUT_DIR"

make_mock() {
  local name="$1"
  local body="$2"
  cat > "$MOCK_BIN/$name" <<EOF
#!/usr/bin/env bash
$body
EOF
  chmod +x "$MOCK_BIN/$name"
}

make_mock claude 'printf "claude mock 1.0\\n"'
make_mock cursor-agent 'printf "cursor-agent mock 1.0\\n"'
make_mock codex 'if [ "${1:-}" = "--version" ]; then printf "codex mock 1.0\\n"; exit 0; fi; printf "codex mock\\n"'
make_mock omp 'printf "omp mock 1.0\\n"'
make_mock gemini 'printf "gemini mock 1.0\\n"'

export HOME="$Z_HARNESS_UX_SMOKE_HOME"
export PATH="$MOCK_BIN:$PATH"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

printf 'ux-smoke: setup dry-run for all harnesses\n'
python3 -m z_harness_cli setup --target all --dry-run

printf '\nux-smoke: prod export filter for codex\n'
python3 -m z_harness_cli export --host codex --surface prod --out "$OUT_DIR/codex" --force
if [ -d "$OUT_DIR/codex/skills/z-research" ]; then
  echo 'ux-smoke: ERROR z-research leaked into prod codex export' >&2
  exit 1
fi
if [ ! -d "$OUT_DIR/codex/skills/z-brainstorm" ]; then
  echo 'ux-smoke: ERROR z-brainstorm missing from prod codex export' >&2
  exit 1
fi

printf '\nux-smoke: prod export filter for cursor\n'
python3 -m z_harness_cli export --host cursor --surface prod --out "$OUT_DIR/cursor" --force
if [ -d "$OUT_DIR/cursor/.cursor/skills/z-map" ]; then
  echo 'ux-smoke: ERROR z-map leaked into prod cursor export' >&2
  exit 1
fi
if [ -d "$OUT_DIR/cursor/.cursor/skills/z-explore" ]; then
  echo 'ux-smoke: ERROR z-explore leaked into prod cursor export' >&2
  exit 1
fi
if [ ! -d "$OUT_DIR/cursor/.cursor/skills/z-learn" ]; then
  echo 'ux-smoke: ERROR z-learn missing from prod cursor export' >&2
  exit 1
fi

printf '\nux-smoke: OK\n'
printf '  work_dir=%s\n' "$WORK_DIR"
printf '  isolated_home=%s\n' "$Z_HARNESS_UX_SMOKE_HOME"
