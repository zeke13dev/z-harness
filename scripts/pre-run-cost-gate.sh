#!/usr/bin/env bash
# pre-run-cost-gate.sh — DRY gate driver for expensive z-harness commands.
#
# Usage: pre-run-cost-gate.sh <command> <hard|soft> <RUN> [--dispatch KEY=N ...]
#
# Encapsulates: estimate → resolve disposition → render human_block.
# Does NOT call AskUserQuestion (the calling command .md owns that).
# Does NOT log events (the caller logs cost_gate_decision).
#
# Stdout: a SINGLE JSON object:
#   {
#     "disposition": "ask|auto_proceed|halt|unhandled_gate",
#     "estimate":    <full envelope from estimate-tokens.py>,
#     "human_block": "<rendered multi-line estimate text>"
#   }
# All diagnostics/warnings go to stderr. Stdout must be parseable JSON only.
#
# GREP-DISCOVERABILITY: workflow.pre_run_cost_gate
# This script is the single gate helper for workflow.pre_run_cost_gate — see
# scripts/config.py QUESTION_IDS for the registered question_id and callsites.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESTIMATOR="$SCRIPT_DIR/estimate-tokens.py"
CONFIG_PY="$SCRIPT_DIR/config.py"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 3 ]]; then
    echo "usage: pre-run-cost-gate.sh <command> <hard|soft> <RUN> [--dispatch KEY=N ...]" >&2
    exit 2
fi

COMMAND="$1"
SEVERITY="$2"
# RUN captured for interface completeness; caller uses it for cost_gate_decision logging
RUN="$3"
shift 3

if [[ "$SEVERITY" != "hard" && "$SEVERITY" != "soft" ]]; then
    echo "pre-run-cost-gate: severity must be 'hard' or 'soft', got: $SEVERITY" >&2
    exit 2
fi

# Remaining args are --dispatch flags passed through to estimate-tokens.py
DISPATCH_ARGS=("$@")

# ---------------------------------------------------------------------------
# Temp file for passing envelope data safely between bash/python steps
# ---------------------------------------------------------------------------
TMPDIR_OWN="$(mktemp -d)"
ENVELOPE_FILE="$TMPDIR_OWN/envelope.json"
cleanup() { rm -rf "$TMPDIR_OWN"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Step 1: Run estimate-tokens.py; FAIL-OPEN on any error
# ---------------------------------------------------------------------------
ENVELOPE_OK=0

if [[ -f "$ESTIMATOR" ]]; then
    # Capture stdout to file; let stderr flow for diagnostics
    if python3 "$ESTIMATOR" "$COMMAND" "${DISPATCH_ARGS[@]}" > "$ENVELOPE_FILE" 2>/dev/null; then
        # Validate that output is JSON
        if python3 -c "import sys,json; json.load(open(sys.argv[1]))" "$ENVELOPE_FILE" 2>/dev/null; then
            ENVELOPE_OK=1
        else
            echo "pre-run-cost-gate: estimator output is not valid JSON; using fallback envelope" >&2
        fi
    else
        echo "pre-run-cost-gate: estimator exited non-zero; using fallback envelope" >&2
    fi
else
    echo "pre-run-cost-gate: estimate-tokens.py not found at $ESTIMATOR; using fallback envelope" >&2
fi

# Synthesize fallback envelope (fail-open: never hard-fail the caller)
if [[ $ENVELOPE_OK -eq 0 ]]; then
    cat > "$ENVELOPE_FILE" <<'EOF'
{
  "command": "unknown",
  "estimated_tokens": 0,
  "range_low": 0,
  "range_high": null,
  "confidence": "low",
  "basis": "estimator unavailable",
  "breakdown": [],
  "gate": null
}
EOF
fi

# ---------------------------------------------------------------------------
# Step 2: Extract range_high from envelope for delegation to config.py
# ---------------------------------------------------------------------------
RANGE_HIGH="$(python3 - "$ENVELOPE_FILE" <<'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        env = json.load(f)
    rh = env.get("range_high")
    print("" if rh is None else str(int(rh)))
except Exception:
    print("")
PYEOF
)" || RANGE_HIGH=""

# ---------------------------------------------------------------------------
# Step 3: DELEGATE disposition decision to config.py (single authority)
# Do NOT reimplement the budget rule in bash — config.py owns it.
# ---------------------------------------------------------------------------
CONFIG_ARGS=(check-no-ask --question-id workflow.pre_run_cost_gate --severity "$SEVERITY")
if [[ -n "$RANGE_HIGH" ]]; then
    CONFIG_ARGS+=(--range-high "$RANGE_HIGH")
fi

DISPOSITION_FILE="$TMPDIR_OWN/disposition.json"
CONFIG_OK=0

if [[ -f "$CONFIG_PY" ]]; then
    if python3 "$CONFIG_PY" "${CONFIG_ARGS[@]}" > "$DISPOSITION_FILE" 2>/dev/null; then
        if python3 -c "import sys,json; json.load(open(sys.argv[1]))" "$DISPOSITION_FILE" 2>/dev/null; then
            CONFIG_OK=1
        else
            echo "pre-run-cost-gate: config.py output is not valid JSON; using fallback disposition" >&2
        fi
    else
        echo "pre-run-cost-gate: config.py exited non-zero; using fallback disposition" >&2
    fi
else
    echo "pre-run-cost-gate: config.py not found at $CONFIG_PY; using fallback disposition" >&2
fi

# Fallback disposition when config.py is unavailable
if [[ $CONFIG_OK -eq 0 ]]; then
    if [[ "$SEVERITY" == "soft" ]]; then
        echo '{"result":"auto_proceed","rule_id":"soft_gate_fallback"}' > "$DISPOSITION_FILE"
    else
        echo '{"result":"ask","rule_id":"config_unavailable"}' > "$DISPOSITION_FILE"
    fi
fi

# Extract the result field and map to the gate disposition contract
RAW_RESULT="$(python3 - "$DISPOSITION_FILE" <<'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    print(d.get("result", "ask"))
except Exception:
    print("ask")
PYEOF
)" || RAW_RESULT="ask"

# Map config.py result-domain → gate disposition-domain:
#   skip / prefill / proceed  → auto_proceed  (generic check-no-ask paths)
#   ask                       → ask
#   halt                      → halt
#   unhandled_gate            → unhandled_gate
#   auto_proceed              → auto_proceed  (cost-gate path returns this directly)
case "$RAW_RESULT" in
    skip|prefill|proceed)
        DISPOSITION="auto_proceed"
        ;;
    ask|halt|unhandled_gate|auto_proceed)
        DISPOSITION="$RAW_RESULT"
        ;;
    *)
        echo "pre-run-cost-gate: unexpected result '$RAW_RESULT' from config.py; defaulting to ask" >&2
        DISPOSITION="ask"
        ;;
esac

# ---------------------------------------------------------------------------
# Step 4: Render human_block (only goes to the human_block field, not bare stdout)
# ---------------------------------------------------------------------------
HUMAN_BLOCK="$(python3 - "$ENVELOPE_FILE" <<'PYEOF'
import sys, json

try:
    with open(sys.argv[1]) as f:
        env = json.load(f)
except Exception:
    env = {}

command    = env.get("command", "unknown")
estimated  = env.get("estimated_tokens", 0)
range_low  = env.get("range_low", 0)
range_high = env.get("range_high")
confidence = env.get("confidence", "low")
basis      = env.get("basis", "unknown")


def fmt_tokens(n):
    """Format token count as compact string: ~5.2M, ~320K, etc."""
    if n is None:
        return "?"
    n = int(n)
    if n >= 1_000_000:
        return f"~{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"~{n / 1_000:.1f}K"
    return f"~{n}"


def fmt_range(lo, hi):
    """Format range band: '3.0M–6.2M' or '3.0M–?'"""
    def _fmt(n):
        if n is None:
            return "?"
        n = int(n)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
    return f"{_fmt(lo)}–{_fmt(hi)}"


lines = [
    f"Token estimate for /{command}:",
    f"  estimate  : {fmt_tokens(estimated)}",
    f"  range     : {fmt_range(range_low, range_high)}",
    f"  confidence: {confidence}",
    f"  basis     : {basis}",
]
print("\n".join(lines))
PYEOF
)" 2>/dev/null || HUMAN_BLOCK="Token estimate unavailable (render error)"

# ---------------------------------------------------------------------------
# Step 5: Emit SINGLE JSON object to stdout (machine contract — no bare text)
# ---------------------------------------------------------------------------
python3 - "$ENVELOPE_FILE" "$DISPOSITION" "$HUMAN_BLOCK" <<'PYEOF'
import sys, json

with open(sys.argv[1]) as f:
    envelope = json.load(f)

disposition = sys.argv[2]
human_block = sys.argv[3]

output = {
    "disposition": disposition,
    "estimate":    envelope,
    "human_block": human_block,
}
# Single JSON object, no trailing noise. Stdout is the machine contract.
print(json.dumps(output))
PYEOF
