#!/usr/bin/env bash
# check-pi-auth.sh — read-only report of which oh-my-pi (omp) providers are authenticated.
#
# The OAuth credentials live in omp's auth-broker vault, NOT in ~/.pi/agent/auth.json
# (which only holds API-key entries). So this checker probes `omp token <provider>` by
# EXIT STATUS — a 0 means a credential resolves. It never prints token values.
#
# Required = the providers the z-harness omp consult arms depend on (see .z-harness/providers.json:
#   omp-codex  -> openai-codex/gpt-5.5
#   omp-gemini -> google-antigravity/gemini-3.1-pro
# Optional = arms that are feasible but not wired by default.
#
# Always exits 0 (report, do not fail) unless a required provider is missing AND --strict is set.
set -uo pipefail

STRICT=0
[[ "${1:-}" == "--strict" ]] && STRICT=1

if ! command -v omp >/dev/null 2>&1; then
  echo "check-pi-auth: 'omp' not on PATH — install oh-my-pi first (~/.local/bin/omp)." >&2
  exit 0
fi

# provider | required(1/0) | what it powers
PROVIDERS=(
  "openai-codex|1|omp-codex consult arm (GPT-5.5, ChatGPT sub)"
  "google-antigravity|1|omp-gemini consult arm (Gemini 3.1 Pro, Antigravity OAuth)"
  "cursor|0|optional future Cursor arm"
)

missing_required=0
printf '%-22s %-10s %s\n' "PROVIDER" "STATUS" "POWERS"
printf '%-22s %-10s %s\n' "--------" "------" "------"
for row in "${PROVIDERS[@]}"; do
  IFS='|' read -r prov req powers <<<"$row"
  if timeout 25 omp token "$prov" >/dev/null 2>&1; then
    status="authed"
  else
    status="MISSING"
    [[ "$req" == "1" ]] && missing_required=1
  fi
  printf '%-22s %-10s %s\n' "$prov" "$status" "$powers"
done

# Gemini API-key fallback (the non-OAuth route to Google models).
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  printf '%-22s %-10s %s\n' "google (api-key)" "set" "GEMINI_API_KEY present (fallback for Gemini)"
else
  printf '%-22s %-10s %s\n' "google (api-key)" "unset" "GEMINI_API_KEY not in env (optional)"
fi

echo
if [[ "$missing_required" == "1" ]]; then
  echo "One or more REQUIRED providers are not authenticated. Run 'pi' (or 'omp'), then '/login'." >&2
  [[ "$STRICT" == "1" ]] && exit 1
fi
exit 0
