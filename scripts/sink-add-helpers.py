#!/usr/bin/env python3
"""
scripts/sink-add-helpers.py — heavy-lifting implementation for sink-add.sh.

Called by sink-add.sh with parsed flags. Does all validation, hash computation,
lock acquisition, atomic writes, and event logging.

Exit codes:
  0  success
  2  validation error
  3  dedup-skip
  4  depth-exceeded
  5  lock-timeout
  6  diffuse-cited-paths (common ancestor too shallow)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT_FALLBACK = SCRIPT_DIR.parent

# Robust import for scripts invoked as standalone via `python3 scripts/sink-add-helpers.py`
sys.path.insert(0, str(SCRIPT_DIR))
from followup_common import (  # noqa: E402
    GlobalLockContext,
    iso_now,
    git_head,
    _get_config_bool,
    _get_config_str,
    _log_event_sh,
    _notion_push_entry_bg,
    log_metrics_event,
    log_sink_event,
)

GLOBAL_LOCK_FILE = Path(os.environ.get(
    "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK",
    str(Path.home() / ".z-harness" / ".followup-vs-implement.lock"),
))

LOCK_TIMEOUT_SECONDS = 30

# Terminal statuses — entries in these states are NOT duplicates of new entries
TERMINAL_STATUSES = frozenset({"done", "dismissed"})

# Maximum cited paths before switching to dir_blob_hashes
CITED_PATHS_CAP = 16

# Command constraints
COMMAND_MAX_LENGTH = 2048
COMMAND_SHELL_METACHARACTERS = re.compile(r'[;&|`]|\$\(|[><\n]')

# Z_HARNESS_FOLLOWUP_CALLER_DEPTH: depth cap
MAX_DEPTH = 1


# ── helpers ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Produce a URL-safe slug from a human-readable title."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug[:64]  # cap slug length


def repo_root() -> Path:
    """Return the git repository root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return REPO_ROOT_FALLBACK


def file_content_hash(path: str) -> str | None:
    """Return ``sha256:<hex>`` content hash for a file, or None if unreadable.

    Reads raw file bytes and computes hashlib.sha256 — NOT git hash-object.
    Callers must treat None as a hard rejection — do NOT fall back.
    """
    try:
        with open(path, "rb") as fh:
            file_bytes = fh.read()
        return "sha256:" + hashlib.sha256(file_bytes).hexdigest()
    except OSError:
        return None


def git_ls_tree_hash(capture_head: str, ancestor_dir: str) -> str:
    """Compute ``sha256:<hex>`` tree hash for a directory at a given HEAD.

    Raises RuntimeError if git is unavailable or the subprocess fails.
    Callers must treat this as a hard rejection — do NOT fall back to a sentinel.
    """
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", capture_head, ancestor_dir + "/"],
            capture_output=True, text=True, check=True,
        )
        tree_listing = result.stdout
        return "sha256:" + hashlib.sha256(tree_listing.encode("utf-8")).hexdigest()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git ls-tree failed for path {ancestor_dir!r} at {capture_head!r} "
            f"(exit {exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    except FileNotFoundError:
        raise RuntimeError(
            f"git executable not found; cannot compute tree hash for {ancestor_dir!r}"
        ) from None


def path_depth_from_root(path: Path, root: Path) -> int:
    """Return the depth of path relative to root.

    root depth = 0, root/a = 1, root/a/b = 2, etc.
    """
    try:
        rel = path.resolve().relative_to(root.resolve())
        return len(rel.parts)
    except ValueError:
        return 0


def content_hash(name: str, recommended_command: str, source_artifact: str = "") -> str:
    """Compute sha256 dedup hash from name and recommended_command.

    Only ``name`` and ``recommended_command`` participate in the hash so that the
    same logical follow-up is deduplicated regardless of which artifact surfaced it
    (e.g. a per-task diff.patch from z-implement-next Phase 3.5 vs. the cumulative
    findings.md from z-review-all Phase 3.7.5).  ``source_artifact`` is accepted for
    call-site compatibility but is intentionally excluded from the hash computation.

    Fields separated by NUL bytes to prevent boundary collisions.
    """
    raw = name + "\x00" + recommended_command
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sink_root(sink: str, project_root: Path) -> Path:
    """Return the root directory for the given sink."""
    if sink == "project":
        return project_root / "z-harness" / "followups"
    elif sink == "global":
        return Path.home() / ".z-harness" / "followups"
    raise ValueError(f"Unknown sink: {sink!r}")


def run_id_from_caller() -> str:
    """Return a run ID string (best-effort from env or generated)."""
    return os.environ.get("Z_HARNESS_RUN_ID", iso_now().replace(":", "").replace("-", "") + "-sink-add")


# ── validation ─────────────────────────────────────────────────────────────────

def validate_sink(sink: str) -> str | None:
    """Return error string or None if valid."""
    if sink not in ("project", "global"):
        return f"--sink must be 'project' or 'global', got: {sink!r}"
    return None


def validate_priority(priority: str) -> str | None:
    if priority not in ("P0", "P1", "P2", "P3"):
        return f"--priority must be P0, P1, P2, or P3, got: {priority!r}"
    return None


def validate_name(name: str) -> str | None:
    if not name:
        return "--name is required and must be non-empty"
    return None


def _unquoted_metachar(cmd: str) -> str | None:
    """Return the first shell metacharacter found outside of any quotes, or None.

    Scans the original command string character-by-character, tracking whether we are
    inside single or double quotes.  Only characters that appear outside ALL quoting
    are checked against the metacharacter set.  Two-character sequences ``$(`` are
    also detected.

    Shell metacharacters checked: ``;``, ``|``, ``&``, `` ` ``, ``$(…``, ``>``, ``<``,
    and newline.
    """
    in_single = False
    in_double = False
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if in_single:
            if ch == "'":
                in_single = False
        elif in_double:
            if ch == '"':
                in_double = False
            elif ch == '\\' and i + 1 < len(cmd):
                i += 1  # skip escaped char inside double quotes
        else:
            # Outside all quotes
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch in (';', '|', '&', '`', '>', '<', '\n'):
                return ch
            elif ch == '$' and i + 1 < len(cmd) and cmd[i + 1] == '(':
                return '$('
        i += 1
    return None


def validate_recommended_command(cmd: str) -> str | None:
    """
    Structural parse per SPEC §Command-allowlist:
    1. Must start with /z- followed by 1+ kebab-case word chars.
    2. Optional whitespace + args.
    3. Total length <= 2048.
    4. NO control characters (codepoint < 0x20 except space, or 0x7F).
    5. NO NUL bytes.
    6. Args containing shell metacharacters MUST be quoted; validated by scanning
       for metacharacters that appear outside single/double quotes in the original
       command string.  shlex.split is used only as a parseability sanity check.
    """
    if not cmd:
        return "--recommended-command is required and must be non-empty"

    # Rule 3: length
    if len(cmd) > COMMAND_MAX_LENGTH:
        return f"--recommended-command exceeds {COMMAND_MAX_LENGTH} characters (rule 3)"

    # Rule 4+5: no control characters
    for ch in cmd:
        cp = ord(ch)
        if (cp < 0x20 and ch != " ") or cp == 0x7F or cp == 0x00:
            return f"--recommended-command contains forbidden control character U+{cp:04X} (rules 4+5)"

    # Rule 1: must start with /z- followed by kebab-case word.
    # Canonical pattern (matches schema): /z-[a-z][a-z-]*[a-z] (min 2-char suffix).
    # Single-letter suffixes (e.g. /z-a) do NOT satisfy this rule.
    cmd_pattern = re.compile(r'^/z-[a-z][a-z-]*[a-z](\s.*)?$')
    if not cmd_pattern.match(cmd):
        return (
            f"--recommended-command must start with '/z-' followed by kebab-case word "
            f"(e.g. /z-do, /z-implement-next), got: {cmd!r} (rule 1)"
        )

    # Rule 6: shell parseability sanity check (shlex.split raises on malformed quoting)
    try:
        shlex.split(cmd)
    except ValueError as exc:
        return f"--recommended-command failed shell parse: {exc} (rule 6)"

    # Rule 6: metacharacters outside quotes are forbidden
    bad = _unquoted_metachar(cmd)
    if bad is not None:
        return (
            f"--recommended-command contains unquoted shell metacharacter {bad!r}; "
            f"wrap args containing shell metacharacters in quotes (rule 6)"
        )

    return None


def validate_source_artifact(path: str) -> str | None:
    if not path:
        return "--source-artifact is required"
    if not Path(path).exists():
        return f"--source-artifact does not exist: {path!r}"
    return None


def validate_cited_paths(paths_str: str) -> tuple[list[str], str | None]:
    """Return (parsed_paths, error_or_None)."""
    if not paths_str:
        return [], "--cited-paths is required"
    paths = [p.strip() for p in paths_str.split(",") if p.strip()]
    if not paths:
        return [], "--cited-paths is required and must not be empty"
    errors = []
    for p in paths:
        if not Path(p).exists():
            errors.append(f"cited path does not exist: {p!r}")
    if errors:
        return paths, "; ".join(errors)
    return paths, None


# ── cited paths cap and tree hash ──────────────────────────────────────────────

def compute_hashes_for_cited_paths(
    cited_paths: list[str],
    capture_head: str,
    project_root: Path,
) -> tuple[dict | None, dict | None, str | None]:
    """
    Returns (file_blob_hashes, dir_blob_hashes, error_or_None).
    Exactly one of file_blob_hashes/dir_blob_hashes will be non-None on success.
    """
    if len(cited_paths) <= CITED_PATHS_CAP:
        hashes: dict[str, str] = {}
        for p in cited_paths:
            sha = file_content_hash(p)
            if sha is None:
                return None, None, (
                    f"cited path {p!r} is not hashable "
                    f"(file unreadable or missing)"
                )
            hashes[p] = sha
        return hashes, None, None

    # More than 16 paths — compute common ancestor
    try:
        resolved = [Path(p).resolve() for p in cited_paths]
        ancestor = Path(os.path.commonpath([str(r) for r in resolved]))
    except ValueError:
        return None, None, "cited paths have no common ancestor (paths on different drives?)"

    depth = path_depth_from_root(ancestor, project_root)
    if depth < 2:
        return None, None, (
            f"cited-paths common ancestor {str(ancestor)!r} is too shallow "
            f"(depth {depth} from repo root, minimum 2); followup would be too coarse to track"
        )

    # Use path relative to repo root for the key in dir_blob_hashes
    try:
        ancestor_rel = str(ancestor.relative_to(project_root.resolve()))
    except ValueError:
        ancestor_rel = str(ancestor)

    try:
        tree_hash = git_ls_tree_hash(capture_head, ancestor_rel)
    except RuntimeError as exc:
        return None, None, (
            f"tree hash computation failed for {ancestor_rel!r}: {exc}"
        )
    return None, {ancestor_rel: tree_hash}, None


# ── dedup check ────────────────────────────────────────────────────────────────

def check_dedup(view_path: Path, chash: str) -> bool:
    """Return True if a duplicate (non-terminal entry with same content_hash) exists."""
    if not view_path.exists():
        return False
    try:
        view = json.loads(view_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    entries = view.get("entries", {})
    for entry in entries.values():
        if entry.get("content_hash") == chash and entry.get("status") not in TERMINAL_STATUSES:
            return True
    return False


# ── view rebuild ───────────────────────────────────────────────────────────────

def rebuild_view(sink_root_path: Path, project_root: Path) -> None:
    """Invoke sink-view-rebuild.sh under the global lock (which caller already holds)."""
    rebuild_sh = SCRIPT_DIR / "sink-view-rebuild.sh"
    env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": str(GLOBAL_LOCK_FILE)}
    result = subprocess.run(
        ["bash", str(rebuild_sh), str(sink_root_path)],
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sink-view-rebuild.sh exited {result.returncode} for sink root: {sink_root_path}"
        )


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sink-add-helpers",
        description="Sink-add implementation: validation, hashing, lock, write",
    )
    parser.add_argument("--sink", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--recommended-command", default="", dest="recommended_command")
    parser.add_argument("--source-artifact", default="", dest="source_artifact")
    parser.add_argument("--cited-paths", default="", dest="cited_paths")
    parser.add_argument("--auto-close-eligible", default="false", dest="auto_close_eligible")
    parser.add_argument("--safe-to-retry", default="false", dest="safe_to_retry")
    parser.add_argument("--prompt-body", default="", dest="prompt_body")
    parser.add_argument("--prompt-body-file", default="", dest="prompt_body_file")
    args = parser.parse_args(argv)

    sink = args.sink
    priority = args.priority
    name = args.name
    recommended_command = args.recommended_command
    source_artifact = args.source_artifact
    cited_paths_str = args.cited_paths
    auto_close_eligible = args.auto_close_eligible.lower() == "true"
    safe_to_retry = args.safe_to_retry == "true"
    prompt_body = args.prompt_body
    prompt_body_file = args.prompt_body_file

    proj_root = repo_root()

    # ── step 1: depth check ──────────────────────────────────────────────────
    caller_depth = 0
    env_depth = os.environ.get("Z_HARNESS_FOLLOWUP_CALLER_DEPTH", "")
    if env_depth:
        try:
            caller_depth = int(env_depth)
        except ValueError:
            pass

    new_entry_depth = caller_depth
    if new_entry_depth > MAX_DEPTH:
        print(
            f"sink-add: depth-exceeded: caller_depth={caller_depth}, "
            f"new_entry_depth={new_entry_depth} > max={MAX_DEPTH}",
            file=sys.stderr,
        )
        log_metrics_event(proj_root, "followup_depth_exceeded", {
            "caller_depth": caller_depth,
            "new_entry_depth": new_entry_depth,
        })
        return 4

    # ── step 2: validation ───────────────────────────────────────────────────
    errors: list[str] = []

    if err := validate_sink(sink):
        errors.append(err)
    if err := validate_priority(priority):
        errors.append(err)
    if err := validate_name(name):
        errors.append(err)
    if err := validate_recommended_command(recommended_command):
        errors.append(err)
    if err := validate_source_artifact(source_artifact):
        errors.append(err)

    cited_paths, cited_err = validate_cited_paths(cited_paths_str)
    if cited_err:
        errors.append(cited_err)

    if prompt_body and prompt_body_file:
        errors.append("--prompt-body and --prompt-body-file are mutually exclusive")
    if prompt_body_file and not Path(prompt_body_file).exists():
        errors.append(f"--prompt-body-file does not exist: {prompt_body_file!r}")

    if errors:
        for e in errors:
            print(f"sink-add: validation error: {e}", file=sys.stderr)
        return 2

    # ── step 3: compute id, capture_head ─────────────────────────────────────
    now = iso_now()
    ts_compact = now.replace("-", "").replace(":", "")
    slug = slugify(name)
    entry_id = f"{ts_compact}-{slug}"
    try:
        capture_head = git_head()
    except RuntimeError as exc:
        print(f"sink-add: hash-error: capture_head computation failed: {exc}", file=sys.stderr)
        return 2

    # ── step 4: compute hashes ────────────────────────────────────────────────
    file_blob_hashes, dir_blob_hashes, hash_err = compute_hashes_for_cited_paths(
        cited_paths, capture_head, proj_root
    )
    if hash_err:
        if "not hashable" in hash_err or "tree hash computation failed" in hash_err:
            # Hard rejection: file unreadable or git tree-hash subprocess failed
            print(f"sink-add: hash-error: {hash_err}", file=sys.stderr)
            return 2
        # Diffuse-ancestor error
        print(f"sink-add: diffuse-cited-paths: {hash_err}", file=sys.stderr)
        log_metrics_event(proj_root, "followup_cited_paths_too_diffuse", {
            "entry_name": name,
            "cited_paths_count": len(cited_paths),
        })
        return 6

    # ── step 5: content hash + dedup ──────────────────────────────────────────
    chash = content_hash(name, recommended_command, source_artifact)
    s_root = sink_root(sink, proj_root)
    view_path = s_root / "index.view.json"

    if check_dedup(view_path, chash):
        print(
            f"sink-add: dedup-skip: entry with same content_hash already exists "
            f"(name={name!r})",
            file=sys.stderr,
        )
        log_metrics_event(proj_root, "followup_dedup_skipped", {
            "content_hash": chash,
            "entry_name": name,
        })
        return 3

    # ── step 6: build entry object ────────────────────────────────────────────
    run_id = run_id_from_caller()

    entry: dict = {
        "id": entry_id,
        "schema_version": 1,
        "priority": priority,
        "name": name,
        "status": "open",
        "sink": sink,
        "created_at": now,
        "created_by_run": run_id,
        "capture_head": capture_head,
        "source_artifact": source_artifact,
        "prompt_page_link": f"pages/{entry_id}.md",
        "recommended_command": recommended_command,
        "recommended_command_safe_to_retry": safe_to_retry,
        "cited_paths": cited_paths,
        "depth": new_entry_depth,
        "auto_close_eligible": auto_close_eligible,
        "completion_mode": None,
        "audit_evidence_path": None,
        "closed_at": None,
        "closed_by_run": None,
        "failure_reason": None,
        "attempt_count": 0,
        "status_history": [
            {"ts": now, "from": None, "to": "open", "by": "scripts/sink-add.sh"},
        ],
        "notion_remote_id": None,
        "content_hash": chash,
    }

    # Exactly one of file_blob_hashes / dir_blob_hashes is non-null
    if file_blob_hashes is not None:
        entry["file_blob_hashes"] = file_blob_hashes
        entry["dir_blob_hashes"] = None
    else:
        entry["file_blob_hashes"] = None
        entry["dir_blob_hashes"] = dir_blob_hashes

    # ── step 7: resolve prompt body ───────────────────────────────────────────
    if prompt_body_file:
        page_content = Path(prompt_body_file).read_text(encoding="utf-8")
    elif prompt_body:
        page_content = prompt_body
    else:
        page_content = f"# {name}\n\n{recommended_command}\n"

    # ── step 8: acquire global lock and write atomically ──────────────────────
    s_root.mkdir(parents=True, exist_ok=True)
    pages_dir = s_root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Allow tests to override timeout via env var (keep default 30s in production)
    try:
        lock_timeout = int(os.environ.get("Z_HARNESS_FOLLOWUP_LOCK_TIMEOUT", str(LOCK_TIMEOUT_SECONDS)))
    except ValueError:
        lock_timeout = LOCK_TIMEOUT_SECONDS

    try:
        with GlobalLockContext(GLOBAL_LOCK_FILE, f"sink-add-{os.getpid()}", lock_timeout):
            # Recheck dedup under lock to avoid TOCTOU
            if check_dedup(view_path, chash):
                print(
                    f"sink-add: dedup-skip (under lock): entry with same content_hash exists",
                    file=sys.stderr,
                )
                log_metrics_event(proj_root, "followup_dedup_skipped", {
                    "content_hash": chash,
                    "entry_name": name,
                })
                return 3

            # Write pages/<id>.md via tmpfile+rename
            page_path = pages_dir / f"{entry_id}.md"
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{entry_id}.tmp.",
                suffix=".md",
                dir=str(pages_dir),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(page_content)
                os.replace(tmp_path, str(page_path))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            # Append entry_created event to index.jsonl
            log_sink_event(s_root, "entry_created", {"entry": entry})

            # Rebuild materialized view
            rebuild_view(s_root, proj_root)

    except TimeoutError as exc:
        print(f"sink-add: lock-timeout: {exc}", file=sys.stderr)
        log_metrics_event(proj_root, "followup_lock_timeout", {"entry_name": name})
        return 5

    # ── step 9: best-effort Notion push (backgrounded — does not block caller) ─
    notion_enabled = _get_config_bool("followup.notion_enabled", proj_root)
    if notion_enabled:
        _notion_push_entry_bg(entry, s_root, proj_root)

    # ── step 10: log followup_created to metrics ──────────────────────────────
    log_metrics_event(proj_root, "followup_created", {
        "entry_id": entry_id,
        "sink": sink,
        "priority": priority,
        "depth": new_entry_depth,
    })

    print(f"sink-add: created entry {entry_id} in {sink} sink", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
