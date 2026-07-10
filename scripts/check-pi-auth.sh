#!/usr/bin/env bash
# check-pi-auth.sh — read-only report of which oh-my-pi (omp) providers are authenticated.
#
# The OAuth credentials live in omp's auth-broker vault, NOT in ~/.pi/agent/auth.json
# (which only holds API-key entries). So this checker probes `omp token <provider>` by
# EXIT STATUS — a 0 means a credential resolves. It never prints token values.
#
# Required = the providers the z-harness omp consult/reviewer arms are actually bound to by
# default role (see .z-harness/providers.json "roles" + provider entries):
#   consultant_primary   -> omp-antigravity-pro -> google-antigravity/gemini-3.1-pro
#   consultant_secondary -> omp-cursor-sol      -> cursor/gpt-5.6-sol-medium
#   reviewer             -> omp-cursor-terra    -> cursor/gpt-5.6-terra-medium
# Optional = arms that are feasible but not bound to any default role.
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
  "google-antigravity|1|omp-antigravity-pro consultant_primary arm (Gemini 3.1 Pro, Antigravity OAuth)"
  "cursor|1|omp-cursor-sol/omp-cursor-terra consultant_secondary+reviewer arms (Cursor OAuth)"
  "openai-codex|0|omp-codex arm (GPT-5.5, ChatGPT sub) — not bound to any default role"
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
