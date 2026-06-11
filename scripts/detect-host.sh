#!/usr/bin/env bash
# detect-host.sh — Detect the current z-harness host environment.
#
# Prints exactly one of: claude | pi | codex | cursor | antigravity
# Defaults to "claude" when no positive marker is present.
#
# Detection rules (first match wins):
#   antigravity  — ANTIGRAVITY_PLUGIN_ROOT is set and non-empty
#   pi           — any PI_* environment variable is set and non-empty
#   codex        — CODEX_API_KEY or CODEX_EXEC is set and non-empty
#   cursor       — CURSOR_API_KEY is set and non-empty
#   claude       — (default, always reachable)
#
# Invariants:
#   - Never prints "unknown" or empty string.
#   - Idempotent; no side effects.
#   - Only a POSITIVE env marker triggers an override.

set -euo pipefail

detect_host() {
  # antigravity — presence of ANTIGRAVITY_PLUGIN_ROOT
  if [[ -n "${ANTIGRAVITY_PLUGIN_ROOT:-}" ]]; then
    printf 'antigravity'
    return 0
  fi

  # pi — any PI_* variable set and non-empty
  # Use compgen to list env vars matching PI_* pattern (bash built-in, no external dep).
  local pi_var
  while IFS= read -r pi_var; do
    if [[ -n "${!pi_var:-}" ]]; then
      printf 'pi'
      return 0
    fi
  done < <(compgen -v PI_ 2>/dev/null || true)

  # codex — CODEX_API_KEY or CODEX_EXEC
  if [[ -n "${CODEX_API_KEY:-}" ]] || [[ -n "${CODEX_EXEC:-}" ]]; then
    printf 'codex'
    return 0
  fi

  # cursor — CURSOR_API_KEY
  if [[ -n "${CURSOR_API_KEY:-}" ]]; then
    printf 'cursor'
    return 0
  fi

  # Default: claude
  printf 'claude'
  return 0
}

# CLI: when executed directly, print the detected host.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  detect_host
fi
