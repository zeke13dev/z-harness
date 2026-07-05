#!/usr/bin/env bash
# omp-consult.sh — stdin→arg adapter for the oh-my-pi `omp` binary, with native-CLI fallback.
#
# Why this exists: the z-harness provider registry dispatches a consult by piping the
# prompt to the provider command's STDIN (every entry is `stdin: true`). The `omp` binary
# (oh-my-pi / @earendil-works/pi-coding-agent) ignores piped stdin in print mode and takes
# the prompt as a POSITIONAL ARGUMENT instead. This shim bridges the two: it reads the
# prompt from stdin and re-invokes omp with the prompt as an arg, so the registry contract
# stays unchanged.
#
# It also drives `omp` rather than `pi`: the OAuth credentials live in omp's auth-broker
# vault, which the `pi` node-CLI (reads ~/.pi/agent/auth.json) cannot see.
#
# Fallback (explicit only): if omp is authenticated but the model call still
# fails (non-zero exit or empty output), and a `--fallback <cmd...>` clause was
# supplied, the same prompt is piped to that native vendor CLI instead. Auth
# failures never degrade to fallback; they fail loud so the caller can re-auth
# the OMP OAuth backend. A telemetry event records explicit fallback use.
#
# Usage:  printf '%s' "$PROMPT" | omp-consult.sh <provider/model> [--fallback <cmd> [args...]]
#   e.g.  ... | omp-consult.sh openai-codex/gpt-5.5 --fallback codex exec -
#         ... | omp-consult.sh google-antigravity/gemini-3.1-pro --fallback gemini -p -
#
# Exit codes: 0 ok (omp or fallback); 2 bad invocation / empty prompt; 3 omp failed and no
# fallback configured (or the fallback command is not on PATH).
set -uo pipefail

model="${1:?omp-consult.sh: missing <provider/model> argument}"
shift

fallback=()
if [[ "${1:-}" == "--fallback" ]]; then
  shift
  fallback=("$@")
fi

prompt="$(cat)"
if [[ -z "${prompt//[[:space:]]/}" ]]; then
  echo "omp-consult.sh: empty prompt on stdin" >&2
  exit 2
fi

omp_provider="${model%%/*}"
provider="omp"
auth_backend="OMP OAuth"
case "$omp_provider" in
  openai-codex)
    provider="omp-codex"
    auth_backend="OMP OAuth / Codex"
    ;;
  google-antigravity)
    provider="omp-antigravity-pro"
    auth_backend="OMP OAuth / Antigravity"
    ;;
  *)
    if [[ -n "$omp_provider" ]]; then
      auth_backend="OMP OAuth / $omp_provider"
    fi
    ;;
esac

_emit_provider_fallback_used() {
  local fallback_provider="${fallback[0]:-}"
  local role="${Z_HARNESS_PROVIDER_ROLE:-unknown}"
  local run="${Z_HARNESS_RUN_ID:-unknown-run}"
  local log_event
  log_event="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/log-event.sh"
  [[ -x "$log_event" ]] || return 0
  local payload
  payload="$(python3 -c 'import json,sys
role, provider, model, auth_backend, fallback_provider = sys.argv[1:6]
print(json.dumps({
    "role": role,
    "provider": provider,
    "attempted_model": model,
    "auth_backend": auth_backend,
    "fallback_provider": fallback_provider,
}))' "$role" "$provider" "$model" "$auth_backend" "$fallback_provider" 2>/dev/null)" || return 0
  bash "$log_event" "$run" provider_fallback_used "$payload" >/dev/null 2>&1 || true
}

_emit_provider_preflight_failed() {
  local reason="$1"
  local role="${Z_HARNESS_PROVIDER_ROLE:-unknown}"
  local run="${Z_HARNESS_RUN_ID:-unknown-run}"
  local log_event
  log_event="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/log-event.sh"
  [[ -x "$log_event" ]] || return 0
  local payload
  payload="$(python3 -c 'import json,sys
role, provider, model, auth_backend, reason = sys.argv[1:6]
print(json.dumps({
    "role": role,
    "provider": provider,
    "attempted_model": model,
    "auth_backend": auth_backend,
    "auth_ready": False,
    "reason": reason,
}))' "$role" "$provider" "$model" "$auth_backend" "$reason" 2>/dev/null)" || return 0
  bash "$log_event" "$run" provider_preflight_failed "$payload" >/dev/null 2>&1 || true
}

_is_omp_auth_or_session_failure() {
  local text="$1"
  local lower
  lower="$(printf '%s' "$text" | tr '[:upper:]' '[:lower:]')"
  [[ "$lower" =~ auth|oauth|login|unauthorized|unauthorised|forbidden|credential|token|expired ]] && return 0
  [[ "$lower" =~ not[[:space:]_-]+authenticated ]] && return 0
  [[ "$lower" =~ session ]] && [[ "$lower" =~ not[[:space:]_-]+found|expired|invalid|missing ]] && return 0
  [[ "$lower" =~ requested[[:space:]_-]+entity[[:space:]_-]+was[[:space:]_-]+not[[:space:]_-]+found ]] && return 0
  [[ "$lower" =~ cloud[[:space:]_-]+code[[:space:]_-]+assist ]] && [[ "$lower" =~ 404 ]] && return 0
  return 1
}

_fail_omp_auth_or_session() {
  local reason="auth/session not ready; run 'omp', then '/login' for $omp_provider before retrying"
  _emit_provider_preflight_failed "$reason"
  echo "omp-consult.sh: provider_preflight_failed role=${Z_HARNESS_PROVIDER_ROLE:-unknown} provider=$provider model=$model auth_backend=$auth_backend — $reason" >&2
  exit 3
}


if ! command -v omp >/dev/null 2>&1; then
  reason="'omp' is not on PATH"
  _emit_provider_preflight_failed "$reason"
  echo "omp-consult.sh: provider_preflight_failed role=${Z_HARNESS_PROVIDER_ROLE:-unknown} provider=$provider model=$model auth_backend=$auth_backend — $reason" >&2
  exit 3
fi

if ! omp token "$omp_provider" >/dev/null 2>&1; then
  reason="auth not ready; run 'omp', then '/login' for $omp_provider before retrying"
  _emit_provider_preflight_failed "$reason"
  echo "omp-consult.sh: provider_preflight_failed role=${Z_HARNESS_PROVIDER_ROLE:-unknown} provider=$provider model=$model auth_backend=$auth_backend — $reason" >&2
  exit 3
fi

# Primary: omp v16 print mode, ephemeral session, prompt as positional arg.
# --no-rules is intentional: when invoked from the z-harness repo, omp otherwise
# auto-loads the root AGENTS.md rule file, which is a large Codex export and
# can add ~90K tokens of irrelevant system context to every consult.
err_file="$(mktemp "${TMPDIR:-/tmp}/omp-consult-stderr.XXXXXX")"
out="$(omp -p --no-session --no-rules --model "$model" "$prompt" 2>"$err_file")"
rc=$?
err="$(cat "$err_file" 2>/dev/null || true)"
rm -f "$err_file"
if [[ "$rc" -eq 0 && -n "${out//[[:space:]]/}" ]]; then
  printf '%s\n' "$out"
  exit 0
fi
if _is_omp_auth_or_session_failure "$err"; then
  _fail_omp_auth_or_session
fi

# Primary failed (non-zero or empty). Degrade to the native fallback only when
# it was explicitly configured and the auth preflight above passed.
if [[ "${#fallback[@]}" -gt 0 ]]; then
  if ! command -v "${fallback[0]}" >/dev/null 2>&1; then
    echo "omp-consult.sh: omp failed (rc=$rc/empty) for model=$model and fallback '${fallback[0]}' is not on PATH" >&2
    exit 3
  fi
  _emit_provider_fallback_used
  echo "omp-consult.sh: DEGRADED — omp failed (rc=$rc/empty) for model=$model auth_backend=$auth_backend; falling back to native: ${fallback[*]}" >&2
  printf '%s' "$prompt" | "${fallback[@]}"
  exit $?
fi

echo "omp-consult.sh: omp produced no usable output for model=$model and no --fallback configured" >&2
exit 3
