#!/usr/bin/env bash
# lint-run-brief.sh — schema, registry, and fixture checks for run-brief subsystem
#
# Usage:
#   scripts/lint-run-brief.sh [--registry-only]
#
# Default mode:
#   - Validates docs/llm/run-brief-contract.json is valid JSON Schema (draft 2020-12)
#   - Validates docs/llm/run-brief-registry.json against #/$defs/run_brief_registry
#   - Runs scripts/render-run-brief.py --self-test on tests/run-brief-fixtures/
#
# With --registry-only:
#   - Greps every command in run-brief-registry.json for a run-brief-finalize
#     fragment/include reference in skills/z-<name>/SKILL.md (strip /z- prefix from key)
#   - Verifies implement-family commands include halt-finalize sub-fragments
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed
#   2 — usage/argument error or missing dependency

set -euo pipefail

REGISTRY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --registry-only) REGISTRY_ONLY=1 ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: scripts/lint-run-brief.sh [--registry-only]" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTRACT="$REPO_ROOT/docs/llm/run-brief-contract.json"
REGISTRY="$REPO_ROOT/docs/llm/run-brief-registry.json"
SKILLS_DIR="$REPO_ROOT/skills"
RENDER_PY="$REPO_ROOT/scripts/render-run-brief.py"

FAIL=0

_fail() {
  FAIL=1
  echo "FAIL: $*" >&2
}

_pass() {
  echo "PASS: $*"
}

_check_deps() {
  if ! python3 -c "import jsonschema, referencing" 2>/dev/null; then
    echo "ERROR: Python jsonschema and referencing required (pip install jsonschema referencing)" >&2
    exit 2
  fi
}

_validate_contract_schema() {
  if [[ ! -f "$CONTRACT" ]]; then
    _fail "missing contract file: $CONTRACT"
    return
  fi
  if python3 - "$CONTRACT" <<'PY'; then
import json
import sys
from jsonschema import Draft202012Validator

with open(sys.argv[1], encoding="utf-8") as fh:
    contract = json.load(fh)
Draft202012Validator.check_schema(contract)
PY
    _pass "run-brief-contract.json is valid JSON Schema"
  else
    _fail "run-brief-contract.json is not valid JSON Schema"
  fi
}

_validate_registry_json() {
  if [[ ! -f "$REGISTRY" ]]; then
    _fail "missing registry file: $REGISTRY"
    return
  fi
  local cmd_count
  if cmd_count="$(python3 - "$CONTRACT" "$REGISTRY" <<'PY'
import json
import sys
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

contract_path, registry_path = sys.argv[1], sys.argv[2]
with open(contract_path, encoding="utf-8") as fh:
    contract = json.load(fh)
with open(registry_path, encoding="utf-8") as fh:
    registry_doc = json.load(fh)

cid = contract["$id"]
registry = Registry().with_resources([(cid, Resource.from_contents(contract))])
validator = Draft202012Validator(
    {"$ref": f"{cid}#/$defs/run_brief_registry"},
    registry=registry,
)
validator.validate(registry_doc)
print(len(registry_doc.get("commands") or {}))
PY
)"; then
    _pass "run-brief-registry.json validates against contract (${cmd_count} commands)"
  else
    _fail "run-brief-registry.json failed schema validation"
  fi
}

_run_renderer_self_test() {
  if [[ ! -f "$RENDER_PY" ]]; then
    _fail "missing renderer: $RENDER_PY"
    return
  fi
  if python3 "$RENDER_PY" --self-test; then
    _pass "render-run-brief.py --self-test"
  else
    _fail "render-run-brief.py --self-test"
  fi
}

_test_finalize_preserves_decisions() {
  local rb_sh="$REPO_ROOT/scripts/run-brief.sh"
  local tmp run_id plan_dir run_dir
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/rb-lint.XXXXXX")"
  run_id="lint-prose-decisions"
  plan_dir="$tmp/plans/lint-test"
  run_dir="$plan_dir/archive/$run_id"
  mkdir -p "$run_dir"
  printf '%s\n' '# Prose-only report' 'No list bullets here.' > "$run_dir/REPORT.md"
  local env_prefix=(env Z_HARNESS_BASE_DIR="$tmp" Z_HARNESS_SLUG=lint-test)
  "${env_prefix[@]}" bash "$rb_sh" init --run "$run_id" --command /z-audit --slug lint-test --profile full --intent "lint test" >/dev/null
  "${env_prefix[@]}" bash "$rb_sh" append-decision --run "$run_id" --question-id q1 --chosen yes --source event >/dev/null
  "${env_prefix[@]}" bash "$rb_sh" set-section --run "$run_id" --section status --value complete >/dev/null
  "${env_prefix[@]}" bash "$rb_sh" set-section --run "$run_id" --section outcome --value "Audit complete with prose report." >/dev/null
  run_dir="$("${env_prefix[@]}" bash "$REPO_ROOT/scripts/log-event.sh" resolve-run-dir "$run_id")"
  RUN_BRIEF_ARTIFACT="$run_dir/REPORT.md" RUN_BRIEF_ARTIFACT_FALLBACKS="" \
    "${env_prefix[@]}" bash "$rb_sh" finalize --run "$run_id" >/dev/null
  if python3 - "$run_dir/run-brief.json" <<'PY'; then
import json, sys
brief = json.load(open(sys.argv[1]))
decisions = brief.get("decisions") or []
if len(decisions) != 1:
    raise SystemExit(f"expected 1 decision, got {len(decisions)}")
if brief.get("profile") != "full":
    raise SystemExit(f"expected full profile on complete path, got {brief.get('profile')}")
PY
    _pass "finalize preserves decisions on prose-only complete path"
  else
    _fail "finalize dropped decisions on prose-only complete path"
  fi
  rm -rf "$tmp"
}

_check_registry_command_includes() {
  if [[ ! -f "$REGISTRY" ]]; then
    _fail "missing registry file: $REGISTRY"
    return
  fi
  if [[ ! -d "$SKILLS_DIR" ]]; then
    _fail "missing skills directory: $SKILLS_DIR"
    return
  fi

  while IFS= read -r cmd; do
    [[ -z "$cmd" ]] && continue
    name="${cmd#/z-}"
    cmd_file="$SKILLS_DIR/z-${name}/SKILL.md"
    if [[ ! -f "$cmd_file" ]]; then
      _fail "$cmd — missing skill file $cmd_file"
      continue
    fi
    grep_ec=0
    grep -q 'run-brief-finalize' "$cmd_file" || grep_ec=$?
    case "$grep_ec" in
      0) _pass "$cmd includes run-brief-finalize in skills/z-${name}/SKILL.md" ;;
      1) _fail "$cmd — no run-brief-finalize reference in skills/z-${name}/SKILL.md" ;;
      *) _fail "$cmd — grep error reading skills/z-${name}/SKILL.md (exit $grep_ec)" ;;
    esac
  done < <(python3 - "$REGISTRY" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    doc = json.load(fh)
commands = sorted((doc.get("commands") or {}).keys())
for cmd in commands:
    print(cmd)
PY
)
}

_check_implement_halt_includes() {
  local spec frag cmd_file grep_ec
  for spec in \
    "z-execute:run-brief-halt-finalize-execute.md"
  do
    cmd_file="$SKILLS_DIR/${spec%%:*}/SKILL.md"
    frag="${spec#*:}"
    if [[ ! -f "$cmd_file" ]]; then
      _fail "${spec%%:*} — missing skill file $cmd_file"
      continue
    fi
    grep_ec=0
    grep -q "$frag" "$cmd_file" || grep_ec=$?
    case "$grep_ec" in
      0) _pass "${spec%%:*} includes $frag in skills/${spec%%:*}/SKILL.md" ;;
      1) _fail "${spec%%:*} — no $frag reference in skills/${spec%%:*}/SKILL.md" ;;
      *) _fail "${spec%%:*} — grep error reading skills/${spec%%:*}/SKILL.md (exit $grep_ec)" ;;
    esac
  done
}

echo "=== lint-run-brief.sh ==="
echo "Repo: $REPO_ROOT"
if [[ "$REGISTRY_ONLY" -eq 1 ]]; then
  echo "Mode: --registry-only"
else
  echo "Mode: full (schema + registry + self-test)"
fi
echo ""

_check_deps

if [[ "$REGISTRY_ONLY" -eq 1 ]]; then
  _check_registry_command_includes
  _check_implement_halt_includes
else
  _validate_contract_schema
  _validate_registry_json
  _run_renderer_self_test
  _test_finalize_preserves_decisions
fi

echo ""
if [[ "$FAIL" -ne 0 ]]; then
  echo "=== lint-run-brief: FAILED ===" >&2
  exit 1
fi

echo "=== lint-run-brief: all checks passed ==="
exit 0
