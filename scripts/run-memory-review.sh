#!/usr/bin/env bash
# Helper called by /z-execute, /z-review-all, and /z-debug.
# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
#
# Usage:
#   bash scripts/run-memory-review.sh <RUN> <parent_command>
#   bash scripts/run-memory-review.sh author <z-suggest-memory flags...>
# Example:
#   bash scripts/run-memory-review.sh author --from-candidate-json candidate.json
#   parent_command: implement-all | review-all | debug
#
# Review mode exits 0 always (skip is success). Author mode returns its
# structured memory mutation status and also uses exit 0 for handled input or
# transaction failures.
# In review mode stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md (or empty if missing), TAGS.txt
# Line 5 (debug parent only): absolute path to DEBUG.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# `author` is the deterministic backend for the retained z-suggest-memory
# surface.  Keeping it in this retained helper makes the public skill's
# mutation contract black-box testable in an installed tree.
if [[ "${1:-}" == "author" ]]; then
  shift
  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  python3 - "$REPO_ROOT" "$SCRIPT_DIR" "$@" <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SOURCE_RE = re.compile(
    r"^(incident:[A-Za-z0-9-]+|spec:[a-z0-9-]+/[A-Za-z0-9-]+|"
    r"debug:[A-Za-z0-9-]+|human_review:[A-Za-z0-9_@.-]+)$"
)
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
MEMORY_TYPES = {
    "anti_pattern", "abandoned_path", "incident", "performance_trap",
    "decision_rationale", "open_question",
}
TAG_SEED = "correctness\nperf\ndata-quality\nschema\ndependency\nobservability\n"


class BadInput(ValueError):
    pass


def parse(argv: list[str]) -> dict[str, object]:
    parsed: dict[str, object] = {"dry_run": False, "refresh": True}
    valued = {
        "--concept": "concept", "--source": "source",
        "--from-candidate-json": "candidate", "--kind": "kind",
        "--question-id": "question_id", "--value": "value",
        "--strength": "strength", "--scope": "scope", "--reason": "reason",
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in {"--dry-run", "--no-refresh-human"}:
            parsed["dry_run" if arg == "--dry-run" else "refresh"] = arg == "--dry-run"
            i += 1
            continue
        if arg in {"--edit", "--delete"}:
            if i + 2 >= len(argv):
                raise BadInput(f"missing value for {arg}")
            if "operation" in parsed:
                raise BadInput("exactly one mutation is allowed")
            try:
                index = int(argv[i + 2])
            except ValueError as exc:
                raise BadInput("memory index must be an integer") from exc
            parsed.update(operation=arg[2:], concept=argv[i + 1], index=index)
            i += 3
            continue
        key = valued.get(arg)
        if key is None:
            raise BadInput(f"unknown flag: {arg}")
        if i + 1 >= len(argv):
            raise BadInput(f"missing value for {arg}")
        parsed[key] = argv[i + 1]
        i += 2
    parsed.setdefault("operation", "append")
    if parsed["operation"] == "delete" and parsed.get("candidate"):
        raise BadInput("delete does not accept candidate JSON")
    return parsed


def load_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BadInput(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BadInput(f"invalid {label}: expected one JSON object")
    return value


def index_concepts(index: dict[str, object], label: str) -> list[dict[str, object]]:
    """Return structurally valid concept records from an index."""
    concepts = index.get("concepts")
    if not isinstance(concepts, list) or any(
        not isinstance(item, dict) for item in concepts
    ):
        raise BadInput(f"{label} concepts must be a list of objects")
    if any(
        not isinstance(item.get("slug"), str)
        or not SLUG_RE.fullmatch(item["slug"])
        for item in concepts
    ):
        raise BadInput(f"{label} concepts must contain valid slug objects")
    return concepts


def candidate_entry(args: dict[str, object]) -> tuple[dict[str, object], str]:
    candidate_arg = args.get("candidate")
    if not isinstance(candidate_arg, str):
        raise BadInput("append and edit require --from-candidate-json")
    if candidate_arg == "-":
        try:
            candidate = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            raise BadInput(f"malformed candidate JSON: {exc}") from exc
        if not isinstance(candidate, dict):
            raise BadInput("candidate JSON must be one object")
    else:
        candidate = load_json(Path(candidate_arg), "candidate JSON")
    if not candidate.get("type") or not candidate.get("text"):
        raise BadInput("candidate JSON is missing type/text")
    slug = str(args.get("concept") or candidate.get("suggested_concept_slug") or "")
    entry: dict[str, object] = {
        "type": candidate["type"],
        "text": candidate["text"],
        "source": args.get("source") or candidate.get("source") or "human_review:memory-review",
        "date": candidate.get("date") or dt.datetime.now(dt.UTC).date().isoformat(),
        "tags": candidate.get("tags", []),
    }
    for source_key, target_key in (
        ("evidence_citations", "evidence"),
        ("candidate_kind", "candidate_kind"),
        ("review_after", "expires"),
    ):
        if candidate.get(source_key):
            entry[target_key] = candidate[source_key]
    return entry, slug


def routing_entry(
    args: dict[str, object], repo_root: Path, script_dir: Path
) -> tuple[dict[str, object], str]:
    if args.get("operation") != "append" or args.get("candidate"):
        raise BadInput("routing-preference only supports append")
    missing = [name for name in ("question_id", "value", "strength", "scope") if not args.get(name)]
    if missing:
        raise BadInput(f"routing-preference missing {missing[0]}")
    if args["strength"] not in {"weak", "strong", "very_strong"}:
        raise BadInput("invalid routing-preference strength")
    if args["scope"] not in {"global", "project"}:
        raise BadInput("invalid routing-preference scope")
    registered = subprocess.run(
        [sys.executable, str(script_dir / "config.py"), "list-question-ids"],
        capture_output=True, text=True, check=False,
    )
    try:
        question_ids = json.loads(registered.stdout) if registered.returncode == 0 else []
    except json.JSONDecodeError as exc:
        raise BadInput("could not validate routing-preference question ID") from exc
    if args["question_id"] not in question_ids:
        raise BadInput("unregistered routing-preference question ID")
    reason = args.get("reason")
    if reason and (
        "\n" in str(reason) or len(str(reason)) > 200 or contains_emoji(str(reason))
    ):
        raise BadInput("routing-preference reason must be one line, emoji-free, and at most 200 characters")
    entry: dict[str, object] = {
        "type": "routing-preference", "question_id": args["question_id"],
        "value": args["value"], "scope": args["scope"],
        "strength": args["strength"], "date": dt.datetime.now(dt.UTC).date().isoformat(),
    }
    if reason:
        entry["reason"] = reason
    if args["scope"] == "project":
        entry["project_root"] = str(repo_root)
        slug = f"workflow-{re.sub(r'[^a-z0-9]+', '-', repo_root.name.lower()).strip('-')}"
    else:
        slug = "workflow"
    return entry, slug


def contains_emoji(value: str) -> bool:
    return any(
        "\U0001F000" <= character <= "\U0001FAFF"
        or "\u2600" <= character <= "\u27BF"
        for character in value
    )


def validate_entry(entry: dict[str, object], tags: set[str]) -> None:
    if entry.get("type") == "routing-preference":
        return
    if entry.get("type") not in MEMORY_TYPES:
        raise BadInput("invalid memory type")
    text = entry.get("text")
    if (
        not isinstance(text, str) or not text or "\n" in text
        or len(text) > 200 or contains_emoji(text)
    ):
        raise BadInput("text must be one non-empty, emoji-free line of at most 200 characters")
    if not SOURCE_RE.fullmatch(str(entry.get("source", ""))):
        raise BadInput("source does not match a supported citation prefix")
    try:
        dt.date.fromisoformat(str(entry.get("date", "")))
    except ValueError as exc:
        raise BadInput("date must be a real YYYY-MM-DD calendar date") from exc
    if entry.get("expires"):
        try:
            dt.date.fromisoformat(str(entry["expires"]))
        except ValueError as exc:
            raise BadInput("expires must be a real YYYY-MM-DD calendar date") from exc
    entry_tags = entry.get("tags", [])
    if not isinstance(entry_tags, list) or any(
        not isinstance(tag, str) or not SLUG_RE.fullmatch(tag) for tag in entry_tags
    ):
        raise BadInput("tags must be valid kebab-case strings")
    # Unknown well-formed tags are intentionally admitted; TAGS.txt is the
    # controlled seed and aliases, not a closed extension registry.
    _ = tags


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def snapshot_tree(root: Path) -> dict[Path, bytes]:
    """Capture every regular file under the managed memory tree."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def restore_tree(root: Path, snapshot: dict[Path, bytes]) -> None:
    """Restore a journal snapshot and remove files created by the transaction."""
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and path.relative_to(root) not in snapshot:
            path.unlink()
    for relative, content in snapshot.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.rollback.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def validate_prepared_tree(llm_dir: Path, slug: str) -> tuple[dict[str, object], int]:
    """Validate every prepared canonical output before publication."""
    tags_path = llm_dir / "TAGS.txt"
    if not tags_path.is_file() or not tags_path.read_text(encoding="utf-8").strip():
        raise BadInput("prepared TAGS.txt is empty or unreadable")
    index = load_json(llm_dir / "INDEX.json", "prepared INDEX.json")
    concepts = index_concepts(index, "prepared INDEX.json")
    matching = [item for item in concepts if item.get("slug") == slug]
    if len(matching) != 1:
        raise BadInput("prepared INDEX.json must register the target concept exactly once")
    concept = load_json(llm_dir / f"{slug}.json", "prepared concept JSON")
    if concept.get("concept") != slug:
        raise BadInput("prepared concept identity does not match its path")
    memories = concept.get("memories")
    if not isinstance(memories, list) or any(not isinstance(item, dict) for item in memories):
        raise BadInput("prepared concept memories must be a list of objects")
    flat_path = llm_dir / "MEMORIES-FLAT.md"
    if not flat_path.is_file() or not flat_path.read_text(encoding="utf-8").startswith(
        "# MEMORIES-FLAT.md"
    ):
        raise BadInput("prepared flat memory view is missing or malformed")
    return concept, len(memories)


def publish_prepared(
    prepared_llm: Path,
    llm_dir: Path,
    relative_paths: list[Path],
    snapshot: dict[Path, bytes],
) -> None:
    """Publish prepared files with logical rollback on a handled failure."""
    fail_at_raw = os.environ.get("Z_HARNESS_MEMORY_FAIL_REPLACE_AT", "")
    try:
        fail_at = int(fail_at_raw) if fail_at_raw else 0
    except ValueError as exc:
        raise BadInput("invalid memory publication failure injection") from exc
    try:
        for position, relative in enumerate(relative_paths, start=1):
            if fail_at == position:
                raise OSError(f"injected publication failure at replacement {position}")
            source = prepared_llm / relative
            destination = llm_dir / relative
            atomic_write(destination, source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        try:
            restore_tree(llm_dir, snapshot)
        except OSError as rollback_exc:
            raise BadInput(
                f"memory publication failed and rollback failed: {rollback_exc}"
            ) from rollback_exc
        raise BadInput(f"memory publication rolled back: {exc}") from exc


def refresh_human(
    repo_root: Path,
    slug: str,
    concept: dict[str, object],
    post_count: int,
) -> str:
    """Send one deterministic refresh request to an optional driver bridge."""
    source_files = concept.get("source_file", concept.get("source_files", []))
    if not isinstance(source_files, list) or any(
        not isinstance(path, str) for path in source_files
    ):
        return "skipped updater_failed"
    request = {
        "agent": "doc-updater",
        "concept": slug,
        "human_path": str(repo_root / "docs" / "human" / f"{slug}.md"),
        "llm_path": str(repo_root / "docs" / "llm" / f"{slug}.json"),
        "mode": "write",
        "post_count": post_count,
        "reason": "memory_write",
        "repository": str(repo_root),
        "source_files": source_files,
    }
    driver_raw = os.environ.get("Z_HARNESS_MEMORY_REFRESH_DRIVER", "")
    driver = shutil.which(driver_raw) if driver_raw else None
    if driver is None:
        return "skipped unsupported_driver"
    try:
        result = subprocess.run(
            [driver],
            input=json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "skipped unsupported_driver"
    if result.returncode != 0:
        return "skipped updater_failed"
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "skipped updater_failed"
    if not isinstance(response, dict):
        return "skipped updater_failed"
    preserved = response.get("memories_preserved")
    if (
        response.get("status") != "ok"
        or type(preserved) is not int
        or preserved != post_count
    ):
        return "skipped updater_failed"
    return "ready"


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve()
    script_dir = Path(sys.argv[2]).resolve()
    llm_dir = repo_root / "docs" / "llm"
    index_path = llm_dir / "INDEX.json"
    try:
        args = parse(sys.argv[3:])
        if not index_path.is_file():
            print("STATUS: no_docs\nCONCEPT:\nMEMORIES_WRITTEN: 0\nHUMAN_REFRESH: skipped unsupported_driver\nWROTE:")
            return 0
        index = load_json(index_path, "INDEX.json")
        concepts = index_concepts(index, "INDEX.json")
        tags_path = llm_dir / "TAGS.txt"
        tags_text = tags_path.read_text(encoding="utf-8") if tags_path.is_file() else TAG_SEED
        tags = {line for line in tags_text.splitlines() if line and not line.startswith("#") and "=" not in line}
        if args.get("kind"):
            if args["kind"] != "routing-preference":
                raise BadInput("unsupported memory kind")
            entry, slug = routing_entry(args, repo_root, script_dir)
        elif args["operation"] == "delete":
            entry, slug = {}, str(args.get("concept", ""))
        else:
            entry, slug = candidate_entry(args)
        if not SLUG_RE.fullmatch(slug):
            raise BadInput("concept must be a kebab-case slug")
        if entry:
            validate_entry(entry, tags)
        concept_path = llm_dir / f"{slug}.json"
        if concept_path.is_file():
            concept = load_json(concept_path, "concept JSON")
        else:
            if args["operation"] != "append":
                raise BadInput("edit/delete target concept does not exist")
            concept = {
                "concept": slug, "summary": f"Durable memory for {slug}.",
                "source_files": [], "last_updated": dt.datetime.now(dt.UTC).date().isoformat(),
                "confidence": "low", "depends_on": [], "consumed_by": [], "memories": [],
            }
        memories = concept.get("memories")
        if not isinstance(memories, list):
            raise BadInput("concept memories must be a list")
        operation = str(args["operation"])
        if operation in {"edit", "delete"}:
            index_value = int(args["index"])
            if index_value < 0 or index_value >= len(memories):
                raise BadInput(f"memory index outside current count {len(memories)}")
            if operation == "edit":
                memories[index_value] = entry
            else:
                del memories[index_value]
        else:
            memories.append(entry)
        concept["last_updated"] = dt.datetime.now(dt.UTC).date().isoformat()
        if not any(isinstance(item, dict) and item.get("slug") == slug for item in concepts):
            concepts.append({
                "slug": slug, "source_files": [], "last_updated": concept["last_updated"],
                "confidence": "low", "depends_on": [], "consumed_by": [],
                "summary": concept["summary"],
            })
            concepts.sort(key=lambda item: str(item.get("slug", "")))
        if args["dry_run"]:
            print(f"STATUS: ok\nCONCEPT: {slug}\nMEMORIES_WRITTEN: 0\nHUMAN_REFRESH: skipped dry_run\nWROTE:")
            print(json.dumps(entry if operation != "delete" else {"delete_index": args["index"]}, sort_keys=True))
            return 0
        had_tags = tags_path.is_file()
        snapshot = snapshot_tree(llm_dir)
        with tempfile.TemporaryDirectory(prefix=".memory-prepare.", dir=repo_root) as temp_name:
            prepared_root = Path(temp_name)
            prepared_llm = prepared_root / "docs" / "llm"
            shutil.copytree(llm_dir, prepared_llm)
            if not had_tags:
                atomic_write(prepared_llm / "TAGS.txt", TAG_SEED)
            atomic_write(
                prepared_llm / f"{slug}.json",
                json.dumps(concept, indent=2, sort_keys=True) + "\n",
            )
            atomic_write(
                prepared_llm / "INDEX.json",
                json.dumps(index, indent=2, sort_keys=True) + "\n",
            )
            regenerated = subprocess.run(
                [
                    sys.executable,
                    str(script_dir / "regenerate-memories-flat.py"),
                    "--repo-root",
                    str(prepared_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if regenerated.returncode != 0:
                raise BadInput(f"stale flat memory view: {regenerated.stderr.strip()}")
            prepared_concept, post_count = validate_prepared_tree(prepared_llm, slug)
            relative_paths = [
                Path(f"{slug}.json"),
                Path("INDEX.json"),
                Path("MEMORIES-FLAT.md"),
            ]
            if not had_tags:
                relative_paths.insert(0, Path("TAGS.txt"))
            publish_prepared(prepared_llm, llm_dir, relative_paths, snapshot)
        wrote = [llm_dir / relative for relative in relative_paths]
        human = (
            "skipped no_refresh"
            if not args["refresh"]
            else refresh_human(repo_root, slug, prepared_concept, post_count)
        )
        count = 0 if operation == "delete" else 1
        print(f"STATUS: ok\nCONCEPT: {slug}\nMEMORIES_WRITTEN: {count}\nHUMAN_REFRESH: {human}\nWROTE:")
        for path in wrote:
            print(f"  {path}")
        return 0
    except BadInput as exc:
        print(f"STATUS: bad_input\nREASON: {exc}\nCONCEPT:\nMEMORIES_WRITTEN: 0\nHUMAN_REFRESH: skipped unsupported_driver\nWROTE:")
        return 0


raise SystemExit(main())
PY
  exit $?
fi

# Resolve REPO_ROOT, PLUGIN_ROOT, LOG_EVENT, and SLUG first so the missing_args
# early-exit path can use them before RUN/PARENT_COMMAND are parsed.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"
SLUG="${Z_HARNESS_SLUG:-}"

# _build_terminal_payload <state> <skip_reason_raw> <parent_command_raw> <slug_raw>
# Builds a JSON payload string. Uses python3 when available; falls back to pure bash.
_build_terminal_payload() {
  local state="$1" skip_reason_raw="$2" parent_command_raw="$3" slug_raw="$4"
  if python3 -c '' 2>/dev/null; then
    python3 -c '
import json, sys
state, skip_reason_raw, parent_command_raw, slug_raw = sys.argv[1:5]
skip_reason = None if skip_reason_raw == "null" else skip_reason_raw
parent_command = None if not parent_command_raw else parent_command_raw
slug = None if not slug_raw else slug_raw
print(json.dumps({
  "state": state,
  "skip_reason": skip_reason,
  "parent_command": parent_command,
  "candidates": 0,
  "accepted": 0,
  "slug": slug
}))
' "$state" "$skip_reason_raw" "$parent_command_raw" "$slug_raw"
  else
    # Pure-bash fallback — no special characters in these values so no escaping needed.
    local skip_json parent_json slug_json
    [[ "$skip_reason_raw" == "null" ]] && skip_json="null" || skip_json="\"$skip_reason_raw\""
    [[ -z "$parent_command_raw" ]] && parent_json="null" || parent_json="\"$parent_command_raw\""
    [[ -z "$slug_raw" ]] && slug_json="null" || slug_json="\"$slug_raw\""
    printf '{"state":"%s","skip_reason":%s,"parent_command":%s,"candidates":0,"accepted":0,"slug":%s}' \
      "$state" "$skip_json" "$parent_json" "$slug_json"
  fi
}

if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  # Attempt to emit terminal event; degrade gracefully if log-event.sh is unavailable.
  if [[ -x "$LOG_EVENT" ]]; then
    _PAYLOAD="$(_build_terminal_payload "skipped_broken_context" "missing_args" "" "$SLUG")" || true
    [[ -n "${_PAYLOAD:-}" ]] && bash "$LOG_EVENT" "unknown" "memory_review_terminal" "$_PAYLOAD" || true
  fi
  exit 0
fi

RUN="$1"
PARENT_COMMAND="$2"

# emit_terminal <state> <skip_reason>
# Emits a single memory_review_terminal event. skip_reason may be "null" for the null literal.
emit_terminal() {
  local state="$1"
  local skip_reason="$2"
  if [[ -x "$LOG_EVENT" ]]; then
    local payload
    payload="$(_build_terminal_payload "$state" "$skip_reason" "$PARENT_COMMAND" "$SLUG")" || true
    [[ -n "${payload:-}" ]] && bash "$LOG_EVENT" "$RUN" "memory_review_terminal" "$payload" || true
  fi
}

# Resolve plan base dir — must be absolute
BASE="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  emit_terminal "skipped_broken_context" "no_plan_dir"
  exit 0
fi

# Normalize BASE to an absolute path
if [[ -d "$BASE" ]]; then
  BASE="$(cd "$BASE" && pwd)"
else
  # Directory doesn't exist yet; prefix with REPO_ROOT if relative
  case "$BASE" in
    /*) ;;  # already absolute
    *) BASE="$REPO_ROOT/$BASE" ;;
  esac
fi

RUN_DIR="$BASE/archive/$RUN"
mkdir -p "$RUN_DIR"

# --- Skip-condition 1: empty diff ---
# Resolve a valid base ref: prefer origin/main merge-base, then HEAD~5, then empty-tree.
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASE_REF=""

MERGE_BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
if [[ -n "$MERGE_BASE" ]] && git rev-parse --verify "${MERGE_BASE}^{commit}" >/dev/null 2>&1; then
  BASE_REF="$MERGE_BASE"
elif git rev-parse --verify "HEAD~5^{commit}" >/dev/null 2>&1; then
  BASE_REF="HEAD~5"
else
  BASE_REF="$EMPTY_TREE"
fi

# Test emptiness without loading the diff into memory, then stream to file.
if git diff --quiet "${BASE_REF}..HEAD" 2>/dev/null; then
  echo "STATUS: skipped empty_diff"
  emit_terminal "not_applicable" "empty_diff"
  exit 0
fi

# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
TASKS_FILE="$BASE/TASKS.md"
if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    echo "STATUS: skipped all_tasks_skipped"
    emit_terminal "not_applicable" "all_tasks_skipped"
    exit 0
  fi
fi

# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  DEBUG_MD="$BASE/DEBUG.md"
  if [[ ! -r "$DEBUG_MD" ]]; then
    echo "STATUS: skipped debug_md_missing"
    emit_terminal "not_applicable" "debug_md_missing"
    exit 0
  fi
fi

# --- Verify TAGS.txt exists ---
TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  emit_terminal "skipped_broken_context" "tags_missing"
  exit 0
fi

# --- Write cumulative diff (truncated to 5000 lines, streamed to avoid loading into memory) ---
DIFF_FILE="$RUN_DIR/cumulative.diff"
# Disable pipefail to tolerate SIGPIPE when diff output is shorter than 5000 lines.
set +o pipefail
git diff "${BASE_REF}..HEAD" | head -n 5000 > "$DIFF_FILE"
set -o pipefail

# --- Print ready + artifact paths (all absolute) ---
# On STATUS: ready, no terminal event is emitted — orchestrator owns it after dispatch.
echo "STATUS: ready"
echo "$DIFF_FILE"
if [[ -f "$BASE/SPEC.md" ]]; then
  echo "$BASE/SPEC.md"
else
  echo ""
fi
echo "$TAGS_FILE"
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  echo "$BASE/DEBUG.md"
fi

# --- Surface-aware axiom handoff ---
# axiom-extractor is development-only.  A prod installation must never emit
# its dispatch token even when a user config retained the development default.
# Resolve the same installed-vs-checkout default as the canonical release
# contract.  Import failure is fail-safe: an unknown surface cannot authorize
# a development-only dispatch.
SURFACE="${Z_HARNESS_RELEASE_SURFACE:-}"
if [[ -z "$SURFACE" ]]; then
  SURFACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  SURFACE="$(PYTHONPATH="$SURFACE_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -c \
    'from runtime.release_surface import default_surface; print(default_surface())' 2>/dev/null || echo "prod")"
fi
if [[ "$SURFACE" != "dev" && "$SURFACE" != "development" ]]; then
  echo "AXIOM_STATUS: skipped prod_surface"
else
  _AXIOM_EXTRACT="$(python3 "$PLUGIN_ROOT/scripts/config.py" get axioms.auto_extract_post_run 2>/dev/null || echo "true")"
  if [[ "$_AXIOM_EXTRACT" != "false" ]]; then
    echo "AXIOM_READY $DIFF_FILE"
  else
    echo "AXIOM_STATUS: skipped config_disabled"
  fi
fi

exit 0
