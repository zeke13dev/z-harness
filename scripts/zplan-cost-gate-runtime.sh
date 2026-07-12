#!/usr/bin/env bash
# zplan-cost-gate-runtime.sh — mechanical plumbing for /z-plan's pre-subagent
# hard cost gate (skills/z-plan/SKILL.md "## Pre-subagent cost gate (hard)").
#
# Extracted at T113 (skill-overhaul-phase1, criterion #9 extraction-first
# remedy per SKILL-STYLE.md's size tripwire). NO logic is reimplemented here
# beyond what skills/z-plan/SKILL.md already documented inline: this script
# is the same bash/python moved verbatim into subcommands, called from a
# short delegation block in the skill. The judgment-dense prose (the
# Intent-vs-Full mode gate narrative, the user-facing "Choose a cost-gate
# action" menu copy, the interactive AskUserQuestion loop, and the L3/L2/L1
# downgrade semantics) stays in SKILL.md — only mechanical computation moved.
#
# Behavioral invariants preserved verbatim (do not regress):
#   - `cost_gate_decision` is emitted exactly once per run (guard stays in
#     SKILL.md's thin `emit_zplan_cost_gate_decision_once` wrapper).
#   - `cost_gate_reestimate_attempt` is nonterminal (SKILL.md still owns that
#     emission; this script only re-runs the gate helper + normalizes).
#   - Raw helper JSON from pre-run-cost-gate.sh is NEVER logged anywhere.
#   - Release-before-deregister ordering in halt-finalize is unchanged: this
#     script's `halt-finalize` subcommand calls scripts/z-teardown.sh, which
#     itself performs release (step 2) before deregister (step 3).
#
# Subcommands:
#   compute-dispatch --planning-mode M --intent-level-config L --docs-index-exists B
#     Prints `export ZPLAN_DISPATCH_*` / `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`
#     lines (printf %q-escaped) — eval-clean stdout, diagnostics on stderr.
#
#   call-gate --run RUN --dispatch KEY=VAL [--dispatch KEY=VAL ...]
#     Calls scripts/pre-run-cost-gate.sh, normalizes the single JSON envelope,
#     and applies the sanitized-error degrade (Z_HARNESS_NO_ASK -> halt,
#     else -> ask). Prints `export GATE_*` lines (eval-clean stdout).
#     Reused for BOTH the initial gate call and every re-estimate — the
#     normalize/sanitize logic is identical in both cases.
#
#   apply-reduction <force_l2_standard|force_l1_quick>
#     Prints the authoritative-state export lines for one cost-gate driver
#     reduction. Exit 2 on an unrecognized reduction token (same contract as
#     the prior inline `zplan_apply_cost_reduction`'s `return 2`).
#
#   build-decision-json CHOICE EST CONFIDENCE BASIS DISPOSITION RULE_ID \
#       RANGE_HIGH SOURCE ATTEMPTS REASON GATE_ID
#     Prints the single-line `cost_gate_decision` JSON payload to stdout.
#     SKILL.md's thin wrapper still owns the exactly-once guard and the
#     actual `log-event.sh` call (unchanged, so the guard stays inspectable
#     in the skill file itself).
#
#   halt-finalize --run RUN --slug SLUG --reason REASON
#     Sets the run-brief outcome/next sections for a cost-gate halt, then
#     calls scripts/z-teardown.sh --status aborted (which itself does
#     release-before-deregister). Equivalent to the prior inline
#     `zplan_cost_gate_halt_finalize` function body.
#
# Usage (all subcommands): eval "$(bash zplan-cost-gate-runtime.sh <subcommand> ...)"
# except build-decision-json (prints raw JSON, not exports) and halt-finalize
# (a terminal action with no state to hand back).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PY="$SCRIPT_DIR/config.py"
COST_GATE_SH="$SCRIPT_DIR/pre-run-cost-gate.sh"
RUN_BRIEF_SH="$SCRIPT_DIR/run-brief.sh"
TEARDOWN_SH="$SCRIPT_DIR/z-teardown.sh"

usage() {
  cat >&2 <<'EOF'
usage:
  zplan-cost-gate-runtime.sh compute-dispatch --planning-mode M --intent-level-config L --docs-index-exists B
  zplan-cost-gate-runtime.sh call-gate --run RUN --dispatch KEY=VAL [...]
  zplan-cost-gate-runtime.sh apply-reduction <force_l2_standard|force_l1_quick>
  zplan-cost-gate-runtime.sh build-decision-json CHOICE EST CONFIDENCE BASIS DISPOSITION RULE_ID RANGE_HIGH SOURCE ATTEMPTS REASON GATE_ID
  zplan-cost-gate-runtime.sh halt-finalize --run RUN --slug SLUG --reason REASON
EOF
  exit 2
}

[[ $# -ge 1 ]] || usage
SUBCOMMAND="$1"; shift

case "$SUBCOMMAND" in
# ---------------------------------------------------------------------------
# compute-dispatch — explicit z-plan dispatch counts (replaces profile
# defaults for these keys). Keep this key list in sync with
# scripts/token-cost-profiles.json profiles["z-plan"].dispatch_contract.accepted_keys.
# ---------------------------------------------------------------------------
compute-dispatch)
  PLANNING_MODE=""
  INTENT_LEVEL_CONFIG="auto"
  DOCS_LLM_INDEX_EXISTS="unknown"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --planning-mode) PLANNING_MODE="${2:?}"; shift 2 ;;
      --planning-mode=*) PLANNING_MODE="${1#*=}"; shift ;;
      --intent-level-config) INTENT_LEVEL_CONFIG="${2:?}"; shift 2 ;;
      --intent-level-config=*) INTENT_LEVEL_CONFIG="${1#*=}"; shift ;;
      --docs-index-exists) DOCS_LLM_INDEX_EXISTS="${2:?}"; shift 2 ;;
      --docs-index-exists=*) DOCS_LLM_INDEX_EXISTS="${1#*=}"; shift ;;
      *) printf 'zplan-cost-gate-runtime.sh: unknown argument: %s\n' "$1" >&2; usage ;;
    esac
  done

  ZPLAN_DISPATCH_PLANNING_MODE_FULL=0
  if [[ "$PLANNING_MODE" == "full" ]]; then
    ZPLAN_DISPATCH_PLANNING_MODE_FULL=1
  fi

  # intent_level_depth: 0=quick, 1=standard, 2=deep. Forced config/flag levels
  # are known before the gate; charge their exact depth. Only auto/unknown
  # charges deep conservatively (classifier/level override has not run yet).
  ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0
  if [[ "$PLANNING_MODE" == "intent" ]]; then
    case "$INTENT_LEVEL_CONFIG" in
      quick)    ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0 ;;
      standard) ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=1 ;;
      deep)     ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=2 ;;
      *)        ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=2 ;;
    esac
  fi
  ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH"

  # Setup step 8 records whether docs/llm/INDEX.json exists; use that cheap
  # signal only. Unset/unknown fails closed with 1 because docs may exist.
  case "$DOCS_LLM_INDEX_EXISTS" in
    0|false|False|no|No) ZPLAN_DISPATCH_DOC_FETCHER=0 ;;
    *)                   ZPLAN_DISPATCH_DOC_FETCHER=1 ;;
  esac

  # Explore is capped by workflow.max_explore (default 3). Use the configured
  # cap because Phase 1 skip conditions are not guaranteed until after the gate.
  ZPLAN_DISPATCH_EXPLORE="$(python3 "$CONFIG_PY" get workflow.max_explore 2>/dev/null || echo 3)"
  case "$ZPLAN_DISPATCH_EXPLORE" in
    ''|*[!0-9]*) ZPLAN_DISPATCH_EXPLORE=3 ;;
  esac

  # Phase 3 may still run unless a later, post-gate level decision/user choice
  # skips it. Charge the full panel conservatively except when a pre-known
  # L1 Quick level makes Phase 3 structurally unreachable before the gate.
  ZPLAN_DISPATCH_PHASE3_CONSULTANTS=5
  if [[ "$PLANNING_MODE" == "intent" && "$INTENT_LEVEL_CONFIG" == "quick" ]]; then
    ZPLAN_DISPATCH_PHASE3_CONSULTANTS=0
  fi

  # Phase 7 remains a possible final-review panel before the gate; keep the
  # conservative panel count.
  ZPLAN_DISPATCH_PHASE7_CONSULTANTS=5

  ZPLAN_DISPATCH_TASK_TREE_GENERATOR=0
  if [[ "$PLANNING_MODE" == "intent" ]]; then
    ZPLAN_DISPATCH_TASK_TREE_GENERATOR=1
  fi

  printf 'export ZPLAN_DISPATCH_PLANNING_MODE_FULL=%q\n' "$ZPLAN_DISPATCH_PLANNING_MODE_FULL"
  printf 'export ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=%q\n' "$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH"
  printf 'export ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=%q\n' "$ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX"
  printf 'export ZPLAN_DISPATCH_DOC_FETCHER=%q\n' "$ZPLAN_DISPATCH_DOC_FETCHER"
  printf 'export ZPLAN_DISPATCH_EXPLORE=%q\n' "$ZPLAN_DISPATCH_EXPLORE"
  printf 'export ZPLAN_DISPATCH_PHASE3_CONSULTANTS=%q\n' "$ZPLAN_DISPATCH_PHASE3_CONSULTANTS"
  printf 'export ZPLAN_DISPATCH_PHASE7_CONSULTANTS=%q\n' "$ZPLAN_DISPATCH_PHASE7_CONSULTANTS"
  printf 'export ZPLAN_DISPATCH_TASK_TREE_GENERATOR=%q\n' "$ZPLAN_DISPATCH_TASK_TREE_GENERATOR"
  ;;

# ---------------------------------------------------------------------------
# call-gate — invoke pre-run-cost-gate.sh, normalize its single JSON object,
# and apply the sanitized-error degrade. Reused for the initial gate call AND
# every reduction re-estimate (identical normalize/sanitize logic).
# ---------------------------------------------------------------------------
call-gate)
  RUN=""
  DISPATCH_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) RUN="${2:?}"; shift 2 ;;
      --run=*) RUN="${1#*=}"; shift ;;
      --dispatch) DISPATCH_ARGS+=("$2"); shift 2 ;;
      --dispatch=*) DISPATCH_ARGS+=("${1#*=}"); shift ;;
      *) printf 'zplan-cost-gate-runtime.sh: unknown argument: %s\n' "$1" >&2; usage ;;
    esac
  done
  [[ -n "$RUN" ]] || usage

  DISPATCH_FLAGS=()
  for kv in "${DISPATCH_ARGS[@]:-}"; do
    [[ -n "$kv" ]] && DISPATCH_FLAGS+=("$kv")
  done

  GATE_JSON="$(bash "$COST_GATE_SH" z-plan hard "$RUN" --dispatch "${DISPATCH_FLAGS[@]}" 2>/dev/null)" || GATE_JSON=""

  # Parse and normalize the helper's single JSON object. The raw helper
  # output is never logged. If the helper invocation failed, the JSON is
  # malformed, or required estimate fields are missing, convert that
  # condition into a sanitized ask/halt branch rather than emitting the raw
  # payload.
  GATE_HELPER_STATUS=ok
  GATE_PARSE_STATUS=ok
  GATE_FIELDS_STATUS=ok
  GATE_SANITIZED_ERROR=""
  GATE_NORMALIZED_JSON="$(python3 - "$GATE_JSON" <<'PY'
import json, sys
raw = sys.argv[1]
try:
    d = json.loads(raw)
except Exception:
    print(json.dumps({"ok": False, "error": "malformed_helper_json"}))
    raise SystemExit(0)

def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

est = d.get("estimate")
missing = []
if not isinstance(est, dict):
    est = {}
    missing.extend(["estimated_tokens", "confidence", "basis", "range_high"])
for key in ("estimated_tokens", "confidence", "basis"):
    if key not in est or est.get(key) in (None, ""):
        missing.append(key)
if "range_high" not in est and "range_high" not in d:
    missing.append("range_high")
invalid = []
for key in ("estimated_tokens", "range_high"):
    value = est.get(key, d.get(key))
    if value not in (None, "") and as_int(value, None) is None:
        invalid.append(key)

out = {
    "ok": True,
    "disposition": d.get("disposition") or "ask",
    "human_block": d.get("human_block") or "Token estimate unavailable.",
    "estimated_tokens": as_int(est.get("estimated_tokens"), 0),
    "confidence": est.get("confidence") or "low",
    "basis": est.get("basis") or "unknown",
    "rule_id": d.get("rule_id") or d.get("rule", {}).get("id"),
    "range_high": est.get("range_high", d.get("range_high")),
    "missing_fields": sorted(set(missing + invalid)),
}
print(json.dumps(out, separators=(",", ":")))
PY
)"
  if [[ -z "$GATE_JSON" ]]; then
    GATE_HELPER_STATUS=failed
    GATE_SANITIZED_ERROR="helper_invocation_failure"
  fi
  if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("ok"))' "$GATE_NORMALIZED_JSON" 2>/dev/null)" != "True" ]]; then
    GATE_PARSE_STATUS=malformed
    GATE_SANITIZED_ERROR="${GATE_SANITIZED_ERROR:-malformed_helper_json}"
  fi

  GATE_DISPOSITION="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("disposition","ask"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo ask)"
  GATE_HUMAN_BLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("human_block","Token estimate unavailable."))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo "Token estimate unavailable.")"
  GATE_EST_TOKENS="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("estimated_tokens",0))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo 0)"
  GATE_CONFIDENCE="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("confidence","low"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo low)"
  GATE_BASIS="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("basis","unknown"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo unknown)"
  GATE_RULE_ID="$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get("rule_id"); print("" if v is None else v)' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
  GATE_RANGE_HIGH="$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get("range_high"); print("" if v is None else v)' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
  GATE_MISSING_FIELDS="$(python3 -c 'import json,sys; print(",".join(json.loads(sys.argv[1]).get("missing_fields",[])))' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
  if [[ -n "$GATE_MISSING_FIELDS" ]]; then
    GATE_FIELDS_STATUS=missing
    GATE_SANITIZED_ERROR="${GATE_SANITIZED_ERROR:-missing_estimate_fields}"
  fi

  # Helper problems degrade to the ask path when a user can decide. In
  # no-ask/non-interactive drivers they are terminal halts: do not proceed
  # after an untrusted or incomplete estimate.
  if [[ "$GATE_HELPER_STATUS" != ok || "$GATE_PARSE_STATUS" != ok || "$GATE_FIELDS_STATUS" != ok ]]; then
    if [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
      GATE_DISPOSITION="halt"
    else
      GATE_DISPOSITION="ask"
      GATE_HUMAN_BLOCK="Token estimate unavailable or incomplete (${GATE_SANITIZED_ERROR}). Proceed with /z-plan, or abandon before any expensive planning subagents run?"
    fi
  fi

  printf 'export GATE_HELPER_STATUS=%q\n' "$GATE_HELPER_STATUS"
  printf 'export GATE_PARSE_STATUS=%q\n' "$GATE_PARSE_STATUS"
  printf 'export GATE_FIELDS_STATUS=%q\n' "$GATE_FIELDS_STATUS"
  printf 'export GATE_SANITIZED_ERROR=%q\n' "$GATE_SANITIZED_ERROR"
  printf 'export GATE_DISPOSITION=%q\n' "$GATE_DISPOSITION"
  printf 'export GATE_HUMAN_BLOCK=%q\n' "$GATE_HUMAN_BLOCK"
  printf 'export GATE_EST_TOKENS=%q\n' "$GATE_EST_TOKENS"
  printf 'export GATE_CONFIDENCE=%q\n' "$GATE_CONFIDENCE"
  printf 'export GATE_BASIS=%q\n' "$GATE_BASIS"
  printf 'export GATE_RULE_ID=%q\n' "$GATE_RULE_ID"
  printf 'export GATE_RANGE_HIGH=%q\n' "$GATE_RANGE_HIGH"
  printf 'export GATE_MISSING_FIELDS=%q\n' "$GATE_MISSING_FIELDS"
  ;;

# ---------------------------------------------------------------------------
# apply-reduction — mutate the authoritative intent/dispatch state for one
# bounded cost-gate driver reduction. Exit 2 on an unrecognized token.
# ---------------------------------------------------------------------------
apply-reduction)
  [[ $# -eq 1 ]] || usage
  REDUCTION="$1"

  case "$REDUCTION" in
    force_l2_standard)
      # Explicit L3/auto -> L2 downgrade. This is the only way the cost gate
      # may reduce deep semantics to standard semantics.
      OUT_PLANNING_MODE="intent"
      OUT_INTENT_LEVEL="standard"
      OUT_INTENT_LEVEL_CONFIG="standard"   # Step 1 skips intent-classifier later.
      OUT_INTENT_LEVEL_SOURCE="user-cost-reduction"
      OUT_INTENT_LEVEL_REASON="cost gate reduction: user forced L2 Standard"
      OUT_INTENT_CONSULT_POLICY="optional" # Step 3/Phase 3 later read the same policy.
      OUT_ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=1
      OUT_ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=1
      # L2 consult is optional later, but the pre-gate estimate stays
      # conservative and keeps charging the Phase-3 panel until the user
      # explicitly skips it there.
      OUT_ZPLAN_DISPATCH_PHASE3_CONSULTANTS=5
      OUT_ZPLAN_COST_CHANGED_DRIVERS_JSON='["intent_level_depth","intent_level","intent_consult_policy"]'
      ;;

    force_l1_quick)
      # Explicit downgrade to L1 Quick. This is the only cost-gate path that
      # changes Phase-3 consult dispatch to zero before Phase 3.
      OUT_PLANNING_MODE="intent"
      OUT_INTENT_LEVEL="quick"
      OUT_INTENT_LEVEL_CONFIG="quick"      # Step 1 skips intent-classifier later.
      OUT_INTENT_LEVEL_SOURCE="user-cost-reduction"
      OUT_INTENT_LEVEL_REASON="cost gate reduction: user forced L1 Quick"
      OUT_INTENT_CONSULT_POLICY="skip"     # Phase 3 structural guard consumes this.
      OUT_ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0
      OUT_ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=0
      OUT_ZPLAN_DISPATCH_PHASE3_CONSULTANTS=0
      OUT_ZPLAN_COST_CHANGED_DRIVERS_JSON='["intent_level_depth","intent_level","intent_consult_policy","phase3_consultants"]'
      ;;

    *)
      printf 'zplan-cost-gate-runtime.sh: unrecognized reduction: %s\n' "$REDUCTION" >&2
      exit 2
      ;;
  esac

  printf 'export PLANNING_MODE=%q\n' "$OUT_PLANNING_MODE"
  printf 'export INTENT_LEVEL=%q\n' "$OUT_INTENT_LEVEL"
  printf 'export INTENT_LEVEL_CONFIG=%q\n' "$OUT_INTENT_LEVEL_CONFIG"
  printf 'export INTENT_LEVEL_SOURCE=%q\n' "$OUT_INTENT_LEVEL_SOURCE"
  printf 'export INTENT_LEVEL_REASON=%q\n' "$OUT_INTENT_LEVEL_REASON"
  printf 'export INTENT_CONSULT_POLICY=%q\n' "$OUT_INTENT_CONSULT_POLICY"
  printf 'export ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=%q\n' "$OUT_ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH"
  printf 'export ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=%q\n' "$OUT_ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX"
  printf 'export ZPLAN_DISPATCH_PHASE3_CONSULTANTS=%q\n' "$OUT_ZPLAN_DISPATCH_PHASE3_CONSULTANTS"
  printf 'export ZPLAN_COST_CHANGED_DRIVERS_JSON=%q\n' "$OUT_ZPLAN_COST_CHANGED_DRIVERS_JSON"
  ;;

# ---------------------------------------------------------------------------
# build-decision-json — render the single-line cost_gate_decision payload.
# SKILL.md's emit_zplan_cost_gate_decision_once wrapper still owns the
# exactly-once guard and the actual log-event.sh call (unchanged in-file, so
# the "exactly once" contract stays directly inspectable in the skill).
# ---------------------------------------------------------------------------
build-decision-json)
  [[ $# -eq 11 ]] || usage
  python3 - "$@" <<'PY'
import json, sys
def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

choice, est, confidence, basis, disposition, rule_id, range_high, source, attempts, reason, gate_id = sys.argv[1:12]
payload = {
    "command": "z-plan",
    "choice": choice,
    "estimated_tokens": as_int(est, 0),
    "confidence": confidence,
    "basis": basis,
    "disposition": disposition,
    "choice_source": source,
    "gate_id": gate_id,
}
if rule_id:
    payload["rule_id"] = rule_id
if range_high:
    payload["range_high"] = as_int(range_high, 0)
if attempts:
    payload["attempt_count"] = as_int(attempts, 0)
if reason:
    payload["reason"] = reason
print(json.dumps(payload, separators=(",", ":")))
PY
  ;;

# ---------------------------------------------------------------------------
# halt-finalize — set the run-brief outcome/next sections for a cost-gate
# halt, then release/deregister/run_end via the one-funnel z-teardown.sh
# (release-before-deregister ordering is z-teardown.sh's own contract).
# ---------------------------------------------------------------------------
halt-finalize)
  RUN=""
  SLUG=""
  REASON=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) RUN="${2:?}"; shift 2 ;;
      --run=*) RUN="${1#*=}"; shift ;;
      --slug) SLUG="${2:?}"; shift 2 ;;
      --slug=*) SLUG="${1#*=}"; shift ;;
      --reason) REASON="${2:?}"; shift 2 ;;
      --reason=*) REASON="${1#*=}"; shift ;;
      *) printf 'zplan-cost-gate-runtime.sh: unknown argument: %s\n' "$1" >&2; usage ;;
    esac
  done
  [[ -n "$RUN" && -n "$SLUG" && -n "$REASON" ]] || usage

  export RUN_BRIEF_PROFILE=full
  export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
  export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-PLAN.md:SPEC.md}"
  bash "$RUN_BRIEF_SH" set-section --run "$RUN" --section outcome --value "Halted: ${REASON}"
  bash "$RUN_BRIEF_SH" set-section --run "$RUN" --section next --json /dev/stdin <<JSON
{"label": "Review plan status and retry or escalate", "command": null}
JSON
  bash "$TEARDOWN_SH" --run "$RUN" --slug "$SLUG" --command /z-plan --status aborted
  ;;

*)
  printf 'zplan-cost-gate-runtime.sh: unknown subcommand: %s\n' "$SUBCOMMAND" >&2
  usage
  ;;
esac
