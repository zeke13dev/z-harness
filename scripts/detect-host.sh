#!/usr/bin/env bash
# detect-host.sh — Resolve the current z-harness host and execution surface.
#
# Usage:
#   detect-host.sh              # prints the host for legacy callers
#   detect-host.sh --json       # prints {"host":"...","surface":"..."}
#
# A result is accepted only when all positive markers identify the same pair.
# Missing evidence is reported as unknown rather than guessed as Claude.

set -euo pipefail

HOST="unknown"
SURFACE="unknown"

add_evidence() {
  local host="$1" surface="$2" source="$3"

  if [[ "$HOST" == "unknown" ]]; then
    HOST="$host"
    SURFACE="$surface"
    return 0
  fi
  if [[ "$HOST" != "$host" || "$SURFACE" != "$surface" ]]; then
    printf 'conflicting host/surface evidence: %s=%s/%s conflicts with %s/%s\n' \
      "$source" "$host" "$surface" "$HOST" "$SURFACE" >&2
    return 2
  fi
}

detect_host_surface() {
  HOST="unknown"
  SURFACE="unknown"

  # Keep the existing host-only override usable for legacy callers. It has no
  # surface evidence, so surface remains explicitly unknown. New pair overrides
  # must name and validate both dimensions.
  if [[ -n "${Z_HARNESS_HOST:-}" && -z "${Z_HARNESS_SURFACE:-}" ]]; then
    HOST="$Z_HARNESS_HOST"
    return 0
  fi
  if [[ -n "${Z_HARNESS_HOST:-}" || -n "${Z_HARNESS_SURFACE:-}" ]]; then
    case "${Z_HARNESS_HOST:-}" in
      claude|pi|codex|cursor|antigravity) ;;
      *) printf 'invalid Z_HARNESS_HOST: %s\n' "${Z_HARNESS_HOST:-<missing>}" >&2; return 2 ;;
    esac
    case "${Z_HARNESS_SURFACE:-}" in
      app|cli) ;;
      *) printf 'invalid Z_HARNESS_SURFACE: %s\n' "${Z_HARNESS_SURFACE:-<missing>}" >&2; return 2 ;;
    esac
    # An explicit, validated pair is authoritative. Ambient host markers are
    # useful only when no caller has supplied that pair.
    HOST="$Z_HARNESS_HOST"
    SURFACE="$Z_HARNESS_SURFACE"
    return 0
  fi

  [[ -z "${ANTIGRAVITY_PLUGIN_ROOT:-}" ]] || add_evidence antigravity app ANTIGRAVITY_PLUGIN_ROOT || return

  local pi_var
  while IFS= read -r pi_var; do
    [[ -z "${!pi_var:-}" ]] || add_evidence pi cli "$pi_var" || return
  done < <(compgen -v PI_ 2>/dev/null || true)

  # CODEX_THREAD_ID is supplied by the direct Codex App; it must not fall
  # through to the historical Claude default.
  [[ -z "${CODEX_THREAD_ID:-}" ]] || add_evidence codex app CODEX_THREAD_ID || return
  if [[ -n "${CODEX_API_KEY:-}" ]] || [[ -n "${CODEX_EXEC:-}" ]]; then
    add_evidence codex cli CODEX_API_KEY/CODEX_EXEC || return
  fi

  [[ -z "${CURSOR_API_KEY:-}" ]] || add_evidence cursor app CURSOR_API_KEY || return
  [[ -z "${CLAUDE_PLUGIN_ROOT:-}" ]] || add_evidence claude cli CLAUDE_PLUGIN_ROOT || return
}

detect_host_surface

case "${1:-}" in
  "") printf '%s' "$HOST" ;;
  --json) printf '{"host":"%s","surface":"%s"}\n' "$HOST" "$SURFACE" ;;
  *) echo "usage: $0 [--json]" >&2; exit 2 ;;
esac
