#!/usr/bin/env bash
# run-brief.sh — create and finalize archive/$RUN/run-brief.json
#
# Subcommands:
#   init --run RUN --command CMD --slug SLUG --profile full|lite --intent TEXT
#   set-section --run RUN --section approach|outcome|next|status --value TEXT|--json FILE|--file PATH
#   append-decision --run RUN --question-id ID --chosen LABEL [--why TEXT] [--source event|artifact]
#   finalize --run RUN
#
# Run directory resolution uses log-event.sh resolve-run-dir (slug-aware).
# finalize emits run_brief_end via log-event.sh after JSON Schema validation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
LOG_EVENT="$SCRIPT_DIR/log-event.sh"
RUN_STATUS="$SCRIPT_DIR/run-status.sh"
CONTRACT="$REPO_ROOT/docs/llm/run-brief-contract.json"
REGISTRY="$REPO_ROOT/docs/llm/run-brief-registry.json"

usage() {
  cat >&2 <<'EOF'
usage:
  run-brief.sh init --run RUN --command CMD --slug SLUG --profile full|lite --intent TEXT
  run-brief.sh set-section --run RUN --section approach|outcome|next|status --value TEXT|--json FILE|--file PATH
  run-brief.sh append-decision --run RUN --question-id ID --chosen LABEL [--why TEXT] [--source event|artifact]
  run-brief.sh finalize --run RUN
EOF
  exit 2
}

resolve_run_dir() {
  local run="$1"
  if [[ ! -x "$LOG_EVENT" ]]; then
    echo "run-brief.sh: log-event.sh not found at $LOG_EVENT" >&2
    exit 2
  fi
  bash "$LOG_EVENT" resolve-run-dir "$run"
}

brief_path() {
  local run_dir="$1"
  printf '%s/run-brief.json' "$run_dir"
}

plan_base_from_run_dir() {
  local run_dir="$1"
  dirname "$(dirname "$run_dir")"
}

# Resolve artifact via env, registry primary/fallbacks, or RUN_BRIEF_ARTIFACT_FALLBACKS.
# Prints absolute path to first existing file, or empty string.
resolve_artifact_chain() {
  local run="$1"
  local run_dir="$2"
  local command="$3"
  local base
  base="$(plan_base_from_run_dir "$run_dir")"

  python3 - "$run" "$run_dir" "$base" "$command" "$REGISTRY" <<'PY'
import json, os, sys
from pathlib import Path

run, run_dir, base, command, registry_path = sys.argv[1:6]

def exists(path: str) -> str:
    p = Path(path)
    return str(p) if p.is_file() else ""

# 1. Explicit env override
env_artifact = os.environ.get("RUN_BRIEF_ARTIFACT", "").strip()
if env_artifact:
    for candidate in (env_artifact, str(Path(base) / env_artifact)):
        hit = exists(candidate)
        if hit:
            print(hit)
            raise SystemExit(0)

registry = {}
if Path(registry_path).is_file():
    registry = json.loads(Path(registry_path).read_text())
entry = registry.get("commands", {}).get(command, {})

# 2. Registry artifact_env
artifact_env = entry.get("artifact_env") or ""
if artifact_env:
    val = os.environ.get(artifact_env, "").strip()
    if val:
        for candidate in (val, str(Path(base) / val)):
            hit = exists(candidate)
            if hit:
                print(hit)
                raise SystemExit(0)

def try_template(template: str) -> str:
    expanded = template.replace("$RUN", run)
    if expanded.startswith("/"):
        return exists(expanded)
    return exists(str(Path(base) / expanded))

# 3. primary_artifact (may be event name — skip if not a file)
primary = entry.get("primary_artifact") or ""
if primary and not primary.endswith("_end"):
    hit = try_template(primary)
    if hit:
        print(hit)
        raise SystemExit(0)

# 4. Env fallbacks colon list, then registry fallbacks
fb_env = os.environ.get("RUN_BRIEF_ARTIFACT_FALLBACKS", "").strip()
fallbacks = [p for p in fb_env.split(":") if p] if fb_env else list(entry.get("fallbacks") or [])
for template in fallbacks:
    hit = try_template(template)
    if hit:
        print(hit)
        raise SystemExit(0)

print("")
PY
}

extract_approach_bullets() {
  local file="$1"
  python3 - "$file" <<'PY'
import re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
bullets = []
for line in text.splitlines():
    stripped = line.strip()
    if re.match(r"^[-*]\s+", stripped):
        item = re.sub(r"^[-*]\s+", "", stripped).strip()
        if item:
            bullets.append(item)
    elif re.match(r"^\d+[.)]\s+", stripped):
        item = re.sub(r"^\d+[.)]\s+", "", stripped).strip()
        if item:
            bullets.append(item)
    if len(bullets) >= 4:
        break
print("\n".join(bullets))
PY
}

cmd_init() {
  local run="" command="" slug="" profile="" intent=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) run="${2:?}"; shift 2 ;;
      --command) command="${2:?}"; shift 2 ;;
      --slug) slug="${2:?}"; shift 2 ;;
      --profile) profile="${2:?}"; shift 2 ;;
      --intent) intent="${2:?}"; shift 2 ;;
      *) echo "run-brief.sh init: unknown argument: $1" >&2; usage ;;
    esac
  done
  [[ -n "$run" && -n "$command" && -n "$slug" && -n "$profile" && -n "$intent" ]] || usage

  case "$profile" in
    full|lite) ;;
    *) echo "run-brief.sh init: profile must be full or lite" >&2; exit 2 ;;
  esac

  local run_dir brief
  run_dir="$(resolve_run_dir "$run")"
  brief="$(brief_path "$run_dir")"
  mkdir -p "$run_dir"

  if [[ -f "$brief" ]]; then
    local existing_run_id
    existing_run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("run_id",""))' "$brief" 2>/dev/null || echo "")"
    if [[ -n "$existing_run_id" && "$existing_run_id" != "$run" ]]; then
      echo "run-brief.sh init: run-brief.json exists for conflicting run_id $existing_run_id (expected $run)" >&2
      exit 3
    fi
    if [[ "$existing_run_id" == "$run" ]]; then
      exit 0
    fi
  fi

  python3 - "$brief" "$run" "$command" "$slug" "$profile" "$intent" <<'PY'
import json, sys, datetime

path, run_id, command, slug, profile, intent = sys.argv[1:7]
obj = {
    "artifact": "run_brief",
    "schema_version": 1,
    "run_id": run_id,
    "command": command,
    "slug": slug,
    "profile": profile,
    "status": "awaiting_approval",
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "intent": intent[:240],
    "outcome": "Pending finalize",
    "next": {"label": "Pending", "command": None},
}
if profile == "full":
    obj["approach"] = []
    obj["decisions"] = []
with open(path, "w", encoding="utf-8") as f:
    json.dump(obj, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
}

cmd_set_section() {
  local run="" section="" value="" json_file="" file_path=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) run="${2:?}"; shift 2 ;;
      --section) section="${2:?}"; shift 2 ;;
      --value) value="${2:?}"; shift 2 ;;
      --json) json_file="${2:?}"; shift 2 ;;
      --file) file_path="${2:?}"; shift 2 ;;
      *) echo "run-brief.sh set-section: unknown argument: $1" >&2; usage ;;
    esac
  done
  [[ -n "$run" && -n "$section" ]] || usage

  case "$section" in
    approach|outcome|next|status) ;;
    *) echo "run-brief.sh set-section: invalid section: $section" >&2; exit 2 ;;
  esac

  local run_dir brief
  run_dir="$(resolve_run_dir "$run")"
  brief="$(brief_path "$run_dir")"
  [[ -f "$brief" ]] || { echo "run-brief.sh set-section: missing $brief" >&2; exit 2; }

  if [[ "$section" == "approach" && -n "$file_path" ]]; then
    if [[ ! -f "$file_path" ]]; then
      echo "run-brief.sh set-section: file not found: $file_path" >&2
      exit 2
    fi
    value="$(extract_approach_bullets "$file_path")"
  fi

  python3 - "$brief" "$section" "$value" "$json_file" "$file_path" <<'PY'
import json, re, sys
from pathlib import Path

path, section, value, json_file, file_path = sys.argv[1:6]
obj = json.loads(Path(path).read_text(encoding="utf-8"))

APPROACH_BULLET_BAD = re.compile(r"(\.[A-Za-z0-9]{1,5}:|/)")

def reject_invalid_approach_bullets(bullets):
    for bullet in bullets:
        if APPROACH_BULLET_BAD.search(bullet):
            print(
                "run-brief.sh set-section: invalid approach bullet "
                "(file paths and file.ext: tokens not allowed): "
                + bullet,
                file=sys.stderr,
            )
            raise SystemExit(2)

if section == "approach":
    if obj.get("profile") == "lite":
        print("run-brief.sh set-section: approach not allowed for lite profile", file=sys.stderr)
        raise SystemExit(2)
    if file_path:
        bullets = [ln for ln in value.splitlines() if ln.strip()]
    elif value:
        bullets = [value]
    else:
        print("run-brief.sh set-section: approach requires --value or --file", file=sys.stderr)
        raise SystemExit(2)
    reject_invalid_approach_bullets(bullets)
    obj["approach"] = bullets[:4]
elif section == "outcome":
    if not value:
        print("run-brief.sh set-section: outcome requires --value", file=sys.stderr)
        raise SystemExit(2)
    obj["outcome"] = value[:400]
elif section == "next":
    if json_file:
        nxt = json.loads(Path(json_file).read_text(encoding="utf-8"))
    elif value:
        nxt = {"label": value, "command": None}
    else:
        print("run-brief.sh set-section: next requires --value or --json", file=sys.stderr)
        raise SystemExit(2)
    obj["next"] = nxt
elif section == "status":
    if not value:
        print("run-brief.sh set-section: status requires --value", file=sys.stderr)
        raise SystemExit(2)
    obj["status"] = value

Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

cmd_append_decision() {
  local run="" question_id="" chosen="" why="" source=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) run="${2:?}"; shift 2 ;;
      --question-id) question_id="${2:?}"; shift 2 ;;
      --chosen) chosen="${2:?}"; shift 2 ;;
      --why) why="${2:?}"; shift 2 ;;
      --source) source="${2:?}"; shift 2 ;;
      *) echo "run-brief.sh append-decision: unknown argument: $1" >&2; usage ;;
    esac
  done
  [[ -n "$run" && -n "$question_id" && -n "$chosen" ]] || usage

  local run_dir brief
  run_dir="$(resolve_run_dir "$run")"
  brief="$(brief_path "$run_dir")"
  [[ -f "$brief" ]] || { echo "run-brief.sh append-decision: missing $brief" >&2; exit 2; }

  python3 - "$brief" "$question_id" "$chosen" "$why" "$source" <<'PY'
import json, sys
from pathlib import Path

path, qid, chosen, why, source = sys.argv[1:6]
obj = json.loads(Path(path).read_text(encoding="utf-8"))
if obj.get("profile") == "lite":
    print("run-brief.sh append-decision: decisions not allowed for lite profile", file=sys.stderr)
    raise SystemExit(2)

decisions = list(obj.get("decisions") or [])
entry = {"question_id": qid, "chosen": chosen}
if why:
    entry["why"] = why
if source in ("event", "artifact"):
    entry["source"] = source

decisions = [d for d in decisions if d.get("question_id") != qid]
decisions.append(entry)
obj["decisions"] = decisions
Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

classify_command_arg() {
  local command="$1"
  case "$command" in
    /z-implement-all) printf '%s' "implement-all" ;;
    *) printf '%s' "" ;;
  esac
}

validate_brief() {
  local brief="$1"
  python3 - "$brief" "$CONTRACT" <<'PY'
import json, sys
from pathlib import Path

brief_path, contract_path = sys.argv[1:3]
try:
    import jsonschema
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:
    print("run-brief.sh: jsonschema package required (pip install jsonschema)", file=sys.stderr)
    raise SystemExit(2)

contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
instance = json.loads(Path(brief_path).read_text(encoding="utf-8"))
cid = contract["$id"]
registry = Registry().with_resources([(cid, Resource.from_contents(contract))])
validator = Draft202012Validator({"$ref": f"{cid}#/$defs/run_brief"}, registry=registry)
errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
if errors:
    for err in errors:
        loc = ".".join(str(p) for p in err.path) or "(root)"
        print(f"{loc}: {err.message}", file=sys.stderr)
    raise SystemExit(2)
print("ok")
PY
}

write_debug_mirror() {
  local brief="$1"
  [[ "${Z_HARNESS_RUN_BRIEF_DEBUG:-}" == "1" ]] || return 0
  local mirror="${brief%.json}.md"
  python3 - "$brief" "$mirror" <<'PY'
import json, sys
from pathlib import Path

brief = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mirror = Path(sys.argv[2])
lines = [
    "# Run Brief (debug mirror)",
    "",
    f"**Run:** {brief.get('run_id')}",
    f"**Command:** {brief.get('command')}",
    f"**Status:** {brief.get('status')}",
    "",
    "## Intent",
    brief.get("intent", ""),
    "",
]
if brief.get("approach"):
    lines += ["## Approach", *[f"- {b}" for b in brief["approach"]], ""]
if brief.get("decisions") is not None:
    lines.append("## Decisions")
    for d in brief.get("decisions") or []:
        lines.append(f"- {d.get('question_id')}: {d.get('chosen')}")
    lines.append("")
lines += [
    "## Outcome",
    brief.get("outcome", ""),
    "",
    "## Next",
    brief.get("next", {}).get("label", ""),
    "",
]
mirror.write_text("\n".join(lines), encoding="utf-8")
PY
}

cmd_finalize() {
  local run=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run) run="${2:?}"; shift 2 ;;
      *) echo "run-brief.sh finalize: unknown argument: $1" >&2; usage ;;
    esac
  done
  [[ -n "$run" ]] || usage

  local run_dir brief
  run_dir="$(resolve_run_dir "$run")"
  brief="$(brief_path "$run_dir")"
  [[ -f "$brief" ]] || { echo "run-brief.sh finalize: missing $brief" >&2; exit 2; }

  local cmd_name artifact_path classify_arg
  cmd_name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("command",""))' "$brief")"
  artifact_path="$(resolve_artifact_chain "$run" "$run_dir" "$cmd_name")"
  classify_arg="$(classify_command_arg "$cmd_name")"

  local classify_result=""
  if [[ -x "$RUN_STATUS" ]]; then
    if [[ -n "$classify_arg" ]]; then
      classify_result="$(bash "$RUN_STATUS" classify "$run_dir" --command "$classify_arg" 2>/dev/null || echo unknown)"
    else
      classify_result="$(bash "$RUN_STATUS" classify "$run_dir" 2>/dev/null || echo unknown)"
    fi
  else
    classify_result="unknown"
  fi

  python3 - "$brief" "$artifact_path" "$classify_result" <<'PY'
import json, sys, datetime, re
from pathlib import Path

path, artifact_path, classify_result = sys.argv[1:4]
obj = json.loads(Path(path).read_text(encoding="utf-8"))

status = obj.get("status")
if not status or status == "awaiting_approval":
    mapping = {"clean": "complete", "halted": "halted", "errored": "aborted"}
    if classify_result in mapping:
        obj["status"] = mapping[classify_result]
    elif classify_result == "unknown":
        # Conservative: never assume success when classify is inconclusive.
        if not status:
            obj["status"] = "awaiting_approval"
    else:
        if not status:
            obj["status"] = "awaiting_approval"

profile = obj.get("profile", "full")

def is_success_terminal(st):
    return st in ("complete", "shipped")

def apply_lite_downgrade(obj):
    obj["profile"] = "lite"
    obj.pop("approach", None)
    obj.pop("decisions", None)

def ensure_approach_for_full(obj, artifact_path=None):
    if obj.get("approach"):
        return
    outcome = (obj.get("outcome") or "").strip()
    if outcome and outcome != "Pending finalize":
        bullet = outcome[:240]
    elif artifact_path:
        bullet = f"Delivered per {Path(artifact_path).name}"
    else:
        bullet = "Completed run"
    obj["approach"] = [bullet]
    if "decisions" not in obj:
        obj["decisions"] = []

status = obj.get("status") or ""
success = is_success_terminal(status)

if not artifact_path and profile == "full":
    if success:
        ensure_approach_for_full(obj)
    else:
        apply_lite_downgrade(obj)
        profile = "lite"
elif artifact_path and profile == "full":
    approach = obj.get("approach") or []
    if not approach:
        text = Path(artifact_path).read_text(encoding="utf-8", errors="replace")
        bullets = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^[-*]\s+", stripped):
                item = re.sub(r"^[-*]\s+", "", stripped).strip()
                if item and not re.search(r"(\.[A-Za-z0-9]{1,5}:|/)", item):
                    bullets.append(item)
            elif re.match(r"^\d+[.)]\s+", stripped):
                item = re.sub(r"^\d+[.)]\s+", "", stripped).strip()
                if item and not re.search(r"(\.[A-Za-z0-9]{1,5}:|/)", item):
                    bullets.append(item)
            if len(bullets) >= 4:
                break
        if bullets:
            obj["approach"] = bullets[:4]
        elif not obj.get("approach"):
            if success:
                ensure_approach_for_full(obj, artifact_path)
            else:
                apply_lite_downgrade(obj)
                profile = "lite"
    if profile == "full":
        sources = dict(obj.get("sources") or {})
        sources["approach"] = Path(artifact_path).name
        obj["sources"] = sources

if obj.get("outcome") == "Pending finalize" and classify_result == "halted":
    obj["outcome"] = "Halted before completion"

sources = dict(obj.get("sources") or {})
if "outcome" not in sources:
    sources["outcome"] = "run-status"
obj["sources"] = sources

obj["generated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

  validate_brief "$brief" >/dev/null
  write_debug_mirror "$brief"

  local profile decision_count validation payload
  profile="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("profile",""))' "$brief")"
  decision_count="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d.get("decisions") or []))' "$brief")"
  validation="ok"
  payload="$(python3 -c 'import json,sys; print(json.dumps({"profile":sys.argv[1],"decision_count":int(sys.argv[2]),"validation":sys.argv[3],"path":sys.argv[4]}))' \
    "$profile" "$decision_count" "$validation" "$brief")"

  bash "$LOG_EVENT" "$run" "run_brief_end" "$payload"
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  exit 0
fi

[[ $# -ge 1 ]] || usage
subcmd="$1"
shift

case "$subcmd" in
  init) cmd_init "$@" ;;
  set-section) cmd_set_section "$@" ;;
  append-decision) cmd_append_decision "$@" ;;
  finalize) cmd_finalize "$@" ;;
  *)
    echo "run-brief.sh: unknown subcommand: $subcmd" >&2
    usage
    ;;
esac
