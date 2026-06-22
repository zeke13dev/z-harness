#!/usr/bin/env bash
# scripts/lint-halt-categories.sh
#
# Scan skills/*/SKILL.md for <!-- RUNTIME-GATE: ask_user ... --> comments.
# Exit non-zero if any present category=<x> token is outside the enum.
# Warn (exit 0 by default, exit 1 under --strict) on ask_user gates
# with no category= token at all.
#
# --strict                  : turn missing-category warnings into hard failures
# --check-chain <preset>    : list uncategorized gates reachable on that chain
# --skills-dir <dir>        : override the default skills/ directory (for tests)
# --commands-dir <dir>      : deprecated alias for --skills-dir (backward compat)
#
# Source of truth for the enum: scripts/config.py HALT_CATEGORY_ENUM
# {decision, risk, shortcut, archiving, mechanical_proceed}

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
STRICT=0
CHECK_CHAIN=""
SKILLS_DIR="$REPO_ROOT/skills"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict)
      STRICT=1
      shift
      ;;
    --check-chain)
      if [[ $# -lt 2 ]]; then
        echo "lint-halt-categories.sh: --check-chain requires a preset name" >&2
        exit 2
      fi
      CHECK_CHAIN="$2"
      shift 2
      ;;
    --skills-dir)
      if [[ $# -lt 2 ]]; then
        echo "lint-halt-categories.sh: --skills-dir requires a directory" >&2
        exit 2
      fi
      SKILLS_DIR="$2"
      shift 2
      ;;
    --commands-dir)
      # Deprecated alias for --skills-dir (backward compat for tests)
      if [[ $# -lt 2 ]]; then
        echo "lint-halt-categories.sh: --commands-dir requires a directory" >&2
        exit 2
      fi
      SKILLS_DIR="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: lint-halt-categories.sh [--strict] [--check-chain <preset>] [--skills-dir <dir>]

Scan skills/*/SKILL.md for RUNTIME-GATE ask_user comments and validate halt categories.

Options:
  --strict              Treat missing category= tokens as hard failures (exit 1)
  --check-chain <name>  List uncategorized gates reachable on a given chain preset
  --skills-dir <dir>    Use a different skills directory (useful in tests)
  --commands-dir <dir>  Deprecated alias for --skills-dir
EOF
      exit 0
      ;;
    *)
      echo "lint-halt-categories.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# The halt_category enum.
# SOURCE OF TRUTH: scripts/config.py HALT_CATEGORY_ENUM
# If this enum drifts from config.py, the startup guard in config.py will
# catch it on any config.py invocation. Keep in sync manually.
# ---------------------------------------------------------------------------
HALT_CATEGORIES="decision risk shortcut archiving mechanical_proceed"

_is_valid_category() {
  local cat="$1"
  for valid in $HALT_CATEGORIES; do
    [[ "$cat" == "$valid" ]] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_warn()  { echo "WARN: $*" >&2; }
_error() { echo "ERROR: $*" >&2; }
_info()  { echo "INFO: $*"; }

# ---------------------------------------------------------------------------
# Core scan: emit lines like "<file>:<lineno>:<type>:<detail>"
# type = "bad_category" | "missing_category"
# Returns 0; callers decide on exit code.
#
# SINGLE-LINE-COMMENT REQUIREMENT (intentional, documented):
#   The scanner inspects one physical line at a time. A RUNTIME-GATE comment
#   and its category= token MUST live on the SAME physical line:
#       <!-- RUNTIME-GATE: ask_user; category=decision -->
#   A gate whose category= token is wrapped onto a second physical line will
#   be reported as missing_category. This is a deliberate, cheap constraint:
#   keep each RUNTIME-GATE comment on one line. (See MAJOR 3 in T006 review.)
#
# Category validation is two distinct checks:
#   (a) PRESENCE  — is a `category=<token>` token present at all? Done
#                   case-insensitively so `category=Risk` still counts as
#                   "present" (it is NOT a missing-category warning).
#   (b) VALIDITY  — is the token a COMPLETE, lowercase enum member? The token
#                   is anchored so it must be terminated by whitespace, `-->`,
#                   `;`, or end-of-line. A prefix like `risk-foo` does NOT
#                   match the enum (the `-foo` suffix breaks the boundary), so
#                   it is reported as bad_category, not silently accepted.
# A present-but-invalid token (wrong case, out-of-enum, or malformed) is a
# hard enum violation (bad_category), never a missing-category warning.
# ---------------------------------------------------------------------------
_scan_file() {
  local file="$1"
  local lineno=0
  while IFS= read -r line; do
    lineno=$(( lineno + 1 ))
    # Only process ask_user RUNTIME-GATE lines
    if [[ "$line" =~ \<\!--\ RUNTIME-GATE:\ ask_user ]]; then
      # (a) PRESENCE check — case-INSENSITIVE. We only ask "is a category=
      #     token present at all?" here. A present-but-malformed/wrong-case
      #     token (e.g. `category=Risk`) MUST fall into the validity branch
      #     as a bad_category, NOT into the missing-category branch.
      if [[ "$line" =~ [Cc][Aa][Tt][Ee][Gg][Oo][Rr][Yy]= ]]; then
        # (b) VALIDITY check. Extract the FULL token: everything after the
        #     first `category=` up to its terminating boundary (whitespace,
        #     ';', '-->', or end-of-line), INCLUDING any internal hyphens.
        #     Keeping internal hyphens is what anchors the enum match: a
        #     malformed token like `risk-foo` is extracted whole and then
        #     fails the exact-match enum test below (it does not get
        #     truncated to a valid `risk` prefix).
        local full_cat
        full_cat="${line#*[Cc][Aa][Tt][Ee][Gg][Oo][Rr][Yy]=}"  # strip up to first category=
        full_cat="${full_cat%%[[:space:]]*}"  # cut at first whitespace
        full_cat="${full_cat%%;*}"            # cut at first ';'
        full_cat="${full_cat%%--\>*}"         # cut at first '-->'
        # _is_valid_category does an EXACT, case-sensitive match against the
        # lowercase enum, so `Risk`, `escalate`, and `risk-foo` all fail.
        if ! _is_valid_category "$full_cat"; then
          # Present but invalid: wrong case, out-of-enum, or malformed.
          echo "${file}:${lineno}:bad_category:${full_cat}"
        fi
      else
        echo "${file}:${lineno}:missing_category:"
      fi
    fi
  done < "$file"
}

# ---------------------------------------------------------------------------
# --check-chain mode: resolve preset to steps, then show uncategorized gates
# in the command files that correspond to those steps.
# ---------------------------------------------------------------------------
_check_chain() {
  local preset="$1"
  local steps=""

  # Try chain-runner.sh first; degrade gracefully if absent.
  # chain-runner.sh steps emits newline-separated "step:yield_after_flag" lines,
  # e.g. "plan:true\naudit:false\n..." — strip the :flag suffix to get bare step names.
  local chain_runner="$REPO_ROOT/scripts/chain-runner.sh"
  local raw_steps=""
  if [[ -x "$chain_runner" ]]; then
    raw_steps="$(bash "$chain_runner" steps "$preset" 2>/dev/null)" || true
  fi

  # Normalize: if chain-runner.sh returned something, extract step names (strip :flag).
  # If nothing returned, fall back to the inline preset map.
  local steps_array=()
  if [[ -n "$raw_steps" ]]; then
    while IFS= read -r line; do
      # Strip optional :true/:false yield_after flag
      local step_name="${line%%:*}"
      [[ -n "$step_name" ]] && steps_array+=("$step_name")
    done <<< "$raw_steps"
  fi

  local use_fallback=0
  if [[ ${#steps_array[@]} -eq 0 ]]; then
    use_fallback=1
    # chain-runner.sh absent or returned nothing — fall back to inline preset map.
    # This map must stay in sync with chain-runner.sh when it exists.
    case "$preset" in
      full-build)     IFS=',' read -ra steps_array <<< "plan,test,implement-all,review-all" ;;
      research-build) IFS=',' read -ra steps_array <<< "research,plan,test,implement-all,review-all" ;;
      quick-build)    IFS=',' read -ra steps_array <<< "plan,implement-all" ;;
      attend-full)    IFS=',' read -ra steps_array <<< "plan,audit,test,implement-all,review-all" ;;
      *)
        echo "lint-halt-categories.sh: unknown preset '$preset' and chain-runner.sh is absent." >&2
        echo "Cannot enumerate chain gates. Install chain-runner.sh or use a known preset." >&2
        # Degrade gracefully: list ALL uncategorized gates
        steps_array=("__ALL__")
        ;;
    esac
    if [[ "${steps_array[*]}" != "__ALL__" ]]; then
      echo "INFO: chain-runner.sh absent; using inline preset map for '$preset'" >&2
    fi
  fi

  # Map step names to skill file paths.
  # Step names like "implement-all" map to skills/z-execute/SKILL.md.
  _step_to_skill() {
    local step="$1"
    echo "z-${step}/SKILL.md"
  }

  local found_any=0
  echo "Uncategorized ask_user gates reachable on chain '$preset':"

  if [[ "${steps_array[0]:-}" == "__ALL__" ]]; then
    # Fallback: scan all skills
    for f in "$SKILLS_DIR"/*/SKILL.md; do
      [[ -f "$f" ]] || continue
      while IFS= read -r entry; do
        [[ "$entry" =~ :missing_category: ]] || continue
        local file lineno
        file="$(echo "$entry" | cut -d: -f1)"
        lineno="$(echo "$entry" | cut -d: -f2)"
        echo "  $(basename "$(dirname "$file")")/SKILL.md:$lineno  (no category= token)"
        found_any=1
      done < <(_scan_file "$f")
    done
  else
    for step in "${steps_array[@]}"; do
      local cmd_file
      cmd_file="$SKILLS_DIR/$(_step_to_skill "$step")"
      if [[ ! -f "$cmd_file" ]]; then
        echo "  [step '$step': skill file not found at $cmd_file]"
        continue
      fi
      while IFS= read -r entry; do
        [[ "$entry" =~ :missing_category: ]] || continue
        local lineno
        lineno="$(echo "$entry" | cut -d: -f2)"
        echo "  $(_step_to_skill "$step"):$lineno  (no category= token)"
        found_any=1
      done < <(_scan_file "$cmd_file")
    done
  fi

  if [[ $found_any -eq 0 ]]; then
    echo "  (none found)"
  fi
}

# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

if [[ -n "$CHECK_CHAIN" ]]; then
  _check_chain "$CHECK_CHAIN"
  exit 0
fi

# Full scan of all skills/*/SKILL.md
EXIT_CODE=0
BAD_COUNT=0
WARN_COUNT=0

for f in "$SKILLS_DIR"/*/SKILL.md; do
  [[ -f "$f" ]] || continue
  while IFS= read -r entry; do
    file="$(echo "$entry" | cut -d: -f1)"
    lineno="$(echo "$entry" | cut -d: -f2)"
    kind="$(echo "$entry" | cut -d: -f3)"
    detail="$(echo "$entry" | cut -d: -f4)"
    rel_file="$(basename "$file")"

    case "$kind" in
      bad_category)
        _error "${rel_file}:${lineno}: category='${detail}' is not in the halt_category enum {${HALT_CATEGORIES// /, }}"
        BAD_COUNT=$(( BAD_COUNT + 1 ))
        EXIT_CODE=1
        ;;
      missing_category)
        if [[ $STRICT -eq 1 ]]; then
          _error "${rel_file}:${lineno}: ask_user gate has no category= token (--strict mode)"
          BAD_COUNT=$(( BAD_COUNT + 1 ))
          EXIT_CODE=1
        else
          _warn "${rel_file}:${lineno}: ask_user gate has no category= token (will fall back to 'ask' at runtime)"
          WARN_COUNT=$(( WARN_COUNT + 1 ))
        fi
        ;;
    esac
  done < <(_scan_file "$f")
done

# Summary
if [[ $BAD_COUNT -gt 0 ]]; then
  echo "lint-halt-categories: $BAD_COUNT error(s), $WARN_COUNT warning(s)" >&2
elif [[ $WARN_COUNT -gt 0 ]]; then
  echo "lint-halt-categories: 0 errors, $WARN_COUNT warning(s) (add category= tokens to suppress)" >&2
else
  echo "lint-halt-categories: ok (no RUNTIME-GATE ask_user issues found)"
fi

exit $EXIT_CODE
