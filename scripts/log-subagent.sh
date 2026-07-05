#!/usr/bin/env bash
# Emit a `subagent_call` event for one subagent dispatch.
#
# Usage:
#   log-subagent.sh \
#     --run          <run-id>          \
#     --role         <role>            \
#     --subagent-type <type>           \
#     --subagent-model <model>         \
#     --prompt-chars  <int>            \
#     --response-chars <int>           \
#     [--model-source <source>]            \
#     [--model-route <route>]              \
#     [--model-route-kind <class|exact>]   \
#     [--model-override-applied <true|false>] \
#     [--model-override-support <applied|advisory|frontmatter>] \
#     [--provider-input-tokens  <int>] \
#     [--provider-output-tokens <int>]
#
# Fields:
#   host                   — stamped automatically by log-event.sh (no duplication here)
#   role                   — logical role name, e.g. "reviewer", "consultant-primary"
#   subagent_type          — e.g. "codex-reviewer", "consultant", "implementer"
#   subagent_model         — e.g. "haiku", "sonnet", "opus"
#   subagent_model_source  — (optional) config/frontmatter source of the effective model
#   subagent_model_route   — (optional) configured route before class expansion
#   subagent_model_route_kind — (optional) class|exact route discriminator
#   subagent_model_override_applied — (optional bool) host actually applied model transport
#   subagent_model_override_support — (optional) applied|advisory|frontmatter
#   prompt_chars           — RAW character count of the prompt; NEVER collapsed with response_chars
#   response_chars         — RAW character count of the response; kept separate (D9)
#   provider_input_tokens  — (optional) real token count from CLI usage line; omit for native Claude
#   provider_output_tokens — (optional) real token count from CLI usage line; omit for native Claude
#
# Design (D9): prompt_chars and response_chars are kept SEPARATE — never collapsed into a single
# est_tokens. Output is priced ~5x input; flat chars/4 proxy under-costs output-heavy calls.
# Price weighting belongs downstream in the cost model, not in telemetry.
#
# Non-fatal: this script ALWAYS exits 0. Callers may also invoke with `|| true`.
# It delegates the event write to scripts/log-event.sh, which stamps `host` automatically.
#
# Honors Z_HARNESS_SLUG just like log-event.sh.

# Self-guard: always exit 0 so callers are never blocked.
trap 'exit 0' ERR

set -uo pipefail

SCRIPTS_DIR="$(dirname "$0")"
LOG_EVENT="$SCRIPTS_DIR/log-event.sh"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

RUN=""
ROLE=""
SUBAGENT_TYPE=""
SUBAGENT_MODEL=""
PROMPT_CHARS=""
RESPONSE_CHARS=""
PROVIDER_INPUT_TOKENS=""
PROVIDER_OUTPUT_TOKENS=""
MODEL_SOURCE=""
MODEL_ROUTE=""
MODEL_ROUTE_KIND=""
MODEL_OVERRIDE_APPLIED=""
MODEL_OVERRIDE_SUPPORT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)              RUN="$2";                   shift 2 ;;
    --role)             ROLE="$2";                  shift 2 ;;
    --subagent-type)    SUBAGENT_TYPE="$2";         shift 2 ;;
    --subagent-model)   SUBAGENT_MODEL="$2";        shift 2 ;;
    --prompt-chars)     PROMPT_CHARS="$2";          shift 2 ;;
    --response-chars)   RESPONSE_CHARS="$2";        shift 2 ;;
    --model-source)     MODEL_SOURCE="$2";           shift 2 ;;
    --model-route)      MODEL_ROUTE="$2";            shift 2 ;;
    --model-route-kind) MODEL_ROUTE_KIND="$2";       shift 2 ;;
    --model-override-applied) MODEL_OVERRIDE_APPLIED="$2"; shift 2 ;;
    --model-override-support) MODEL_OVERRIDE_SUPPORT="$2"; shift 2 ;;
    --provider-input-tokens)  PROVIDER_INPUT_TOKENS="$2";  shift 2 ;;
    --provider-output-tokens) PROVIDER_OUTPUT_TOKENS="$2"; shift 2 ;;
    *)
      echo "log-subagent.sh: unknown argument: $1" >&2
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Validate required fields
# ---------------------------------------------------------------------------

if [[ -z "$RUN" || -z "$ROLE" || -z "$SUBAGENT_TYPE" || -z "$SUBAGENT_MODEL" \
      || -z "$PROMPT_CHARS" || -z "$RESPONSE_CHARS" ]]; then
  echo "log-subagent.sh: missing required argument(s)" >&2
  echo "  required: --run --role --subagent-type --subagent-model --prompt-chars --response-chars" >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Build payload
# ---------------------------------------------------------------------------

PAYLOAD="$(python3 -c '
import json, sys

role, subagent_type, subagent_model, prompt_chars, response_chars = sys.argv[1:6]
model_source, model_route, model_route_kind, model_applied, model_support = sys.argv[6:11]
provider_input  = sys.argv[11]
provider_output = sys.argv[12]

obj = {
    "role":            role,
    "subagent_type":   subagent_type,
    "subagent_model":  subagent_model,
    "prompt_chars":    int(prompt_chars),
    "response_chars":  int(response_chars),
}

if model_source:
    obj["subagent_model_source"] = model_source
if model_route:
    obj["subagent_model_route"] = model_route
if model_route_kind:
    obj["subagent_model_route_kind"] = model_route_kind
if model_applied:
    obj["subagent_model_override_applied"] = model_applied.lower() == "true"
if model_support:
    obj["subagent_model_override_support"] = model_support

# provider_*_tokens are optional — include only when a non-empty value was passed.
if provider_input:
    obj["provider_input_tokens"]  = int(provider_input)
if provider_output:
    obj["provider_output_tokens"] = int(provider_output)

print(json.dumps(obj, separators=(",", ":")))
' "$ROLE" "$SUBAGENT_TYPE" "$SUBAGENT_MODEL" \
  "$PROMPT_CHARS" "$RESPONSE_CHARS" \
  "$MODEL_SOURCE" "$MODEL_ROUTE" "$MODEL_ROUTE_KIND" \
  "$MODEL_OVERRIDE_APPLIED" "$MODEL_OVERRIDE_SUPPORT" \
  "$PROVIDER_INPUT_TOKENS" "$PROVIDER_OUTPUT_TOKENS")" || {
  echo "log-subagent.sh: failed to build payload" >&2
  exit 0
}

# ---------------------------------------------------------------------------
# Emit event via log-event.sh (which stamps host automatically)
# ---------------------------------------------------------------------------

bash "$LOG_EVENT" "$RUN" "subagent_call" "$PAYLOAD" 2>/dev/null || true

exit 0
