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
# Fallback (T004): if omp fails (non-zero exit, or empty output — token-refresh failure,
# network, model-resolution miss), and a `--fallback <cmd...>` clause was supplied, the
# same prompt is piped to that native vendor CLI instead. The fallback owns the consult so
# the run degrades gracefully rather than hard-failing. A loud stderr marker records the
# degrade (the registry's blocking reviewer role does NOT use this adapter, so a degrade
# here is always advisory).
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

# Primary: omp v16 print mode, ephemeral session, prompt as positional arg.
out="$(omp -p --no-session --model "$model" "$prompt" 2>/dev/null)"
rc=$?
if [[ "$rc" -eq 0 && -n "${out//[[:space:]]/}" ]]; then
  printf '%s\n' "$out"
  exit 0
fi

# Primary failed (non-zero or empty). Degrade to the native fallback if one is configured.
if [[ "${#fallback[@]}" -gt 0 ]]; then
  if ! command -v "${fallback[0]}" >/dev/null 2>&1; then
    echo "omp-consult.sh: omp failed (rc=$rc/empty) for model=$model and fallback '${fallback[0]}' is not on PATH" >&2
    exit 3
  fi
  echo "omp-consult.sh: DEGRADED — omp failed (rc=$rc/empty) for model=$model; falling back to native: ${fallback[*]}" >&2
  printf '%s' "$prompt" | "${fallback[@]}"
  exit $?
fi

echo "omp-consult.sh: omp produced no usable output for model=$model and no --fallback configured" >&2
exit 3
