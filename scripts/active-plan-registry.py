#!/usr/bin/env python3
"""
scripts/active-plan-registry.py — Lockless per-run active-plan registry.

INVARIANT (verbatim, repeated from SPEC cross-cutting invariant 1):
  Lockless registry is safe ONLY because overlap is advisory. No code may make
  overlap a hard gate without first replacing lockless delete with
  compare-and-delete or a registry lock.

Each run owns exactly one record: <active_plans_dir>/<run-id>.json.
Writes are atomic (tmpfile in same dir + os.replace). No global lock is taken.
The per-entry→global lock ordering in followup_common.py is NOT affected.

Subcommands:
  register --run-id ID --slug S --command C --phase P [--session SID]
      Write <active>/<ID>.json atomically. Validate ID is a safe basename.
      Populate schema v1. Idempotent (re-register overwrites own record).
      Emit plan_registered via log-event.sh.

  heartbeat --run-id ID [--phase P] [--current-task T]
            [--status running|paused]
      Read own record, update last_heartbeat/phase/current_task, atomic rewrite.
      If file was reaped while alive, recreate it (benign). NON-FATAL on error.

  update-scope --run-id ID --scope-json FILE
      Merge a scope array [{path, confidence, reason}] into the record.
      Paths are stored as-is (caller is responsible for repo-relative normalisation).
      NON-FATAL on error.

  list [--json]
      Scan <active>/*.json. Skip torn/partial files silently (try/except json).
      Print records in human-readable or JSON form.

  deregister --run-id ID [--status complete|aborted]
      Atomically unlink <active>/<ID>.json.
      Emit plan_deregistered. NON-FATAL on error.

Exit codes:
  0   — success
  2   — usage / argument error
  3   — register failure (LOUD; callers MUST gate on this)
  4   — internal error in a normally-loud subcommand (reserved for overlaps/T007)
  0   — heartbeat / update-scope / deregister failure (NON-FATAL; exit 0 always)

Future subcommands (T007): overlaps, reap — leave the file structured to accept
  them as new argparse subcommands and new record field `overlaps`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ── safe basename ──────────────────────────────────────────────────────────────

_SAFE_BASENAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')


def _is_safe_basename(name: str) -> bool:
    """Return True iff name is safe to use as a filename component.

    Rejects: empty string, leading dash, path separators, double-dot sequences.
    Accepts: letters, digits, dot, underscore, hyphen — and only when the whole
    name matches ^[A-Za-z0-9._-]+$ AND does not start with '-' AND does not
    contain '..'.
    """
    if not name:
        return False
    if name.startswith('-'):
        return False
    if '..' in name:
        return False
    if '/' in name or os.sep in name:
        return False
    return bool(_SAFE_BASENAME_RE.match(name))


# ── timestamps ─────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── active_plans_dir via plan-path.sh ─────────────────────────────────────────

def _active_plans_dir() -> Path:
    """Resolve active_plans_dir() by shelling out to plan-path.sh.

    Propagates failures loudly — a non-zero exit from plan-path.sh is a hard
    failure (SPEC invariant 4: base resolution never fails silently mid-run).
    Raises RuntimeError if the resolved path is empty or the shell call fails.
    """
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if not plan_path_sh.exists():
        raise RuntimeError(
            f"plan-path.sh not found at {plan_path_sh}; cannot resolve active_plans_dir"
        )
    try:
        result = subprocess.run(
            ["bash", str(plan_path_sh), "active_plans_dir"],
            capture_output=True,
            text=True,
            cwd=str(SCRIPT_DIR.parent),  # repo root — plan-path.sh expects to be run from repo
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"bash not found: {exc}") from exc
    if result.returncode != 0:
        # plan-path.sh already printed a FATAL message to stderr; propagate it.
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"plan-path.sh active_plans_dir failed (exit {result.returncode})"
            + (f": {stderr}" if stderr else "")
        )
    resolved = result.stdout.strip()
    if not resolved:
        raise RuntimeError(
            "plan-path.sh active_plans_dir returned empty path — refusing to continue"
        )
    return Path(resolved)


# ── git helpers (degrade gracefully when not in a git repo) ───────────────────

def _git_field(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stripped stdout. Returns '' on any failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd or str(SCRIPT_DIR.parent),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


# ── event emission (best-effort) ───────────────────────────────────────────────

def _emit_event(run_id: str, kind: str, payload: dict) -> None:
    """Emit a structured event via log-event.sh (best-effort; never raises)."""
    log_event_sh = SCRIPT_DIR / "log-event.sh"
    if not log_event_sh.exists():
        return
    try:
        subprocess.run(
            ["bash", str(log_event_sh), run_id, kind, json.dumps(payload)],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass


# ── atomic write helpers ───────────────────────────────────────────────────────

def _atomic_write(path: Path, record: dict) -> None:
    """Write record atomically to path via tmpfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_path = str(path.parent)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".tmp-registry-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_read(path: Path) -> dict | None:
    """Read a JSON record from path. Returns None if file is missing or malformed."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


# ── record factory ─────────────────────────────────────────────────────────────

def _build_record(
    *,
    run_id: str,
    slug: str,
    command: str,
    phase: str,
    session_id: str = "",
) -> dict:
    """Build a fresh schema-v1 record populated with current host/git state."""
    now = _iso_now()
    repo_root = _git_field(["rev-parse", "--show-toplevel"])
    git_common_dir = _git_field(["rev-parse", "--git-common-dir"])
    # Normalise git-common-dir to an absolute path.
    if git_common_dir and not os.path.isabs(git_common_dir):
        git_common_dir = os.path.abspath(
            os.path.join(repo_root or str(SCRIPT_DIR.parent), git_common_dir)
        )
    worktree_path = repo_root  # same as repo_root for non-worktree; will differ for worktrees
    branch = _git_field(["rev-parse", "--abbrev-ref", "HEAD"])
    # repo_id: derive from plan-path.sh z_harness_repo_id (best-effort)
    repo_id = ""
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if plan_path_sh.exists():
        try:
            result = subprocess.run(
                ["bash", str(plan_path_sh), "z_harness_repo_id"],
                capture_output=True,
                text=True,
                cwd=repo_root or str(SCRIPT_DIR.parent),
            )
            if result.returncode == 0:
                repo_id = result.stdout.strip()
        except OSError:
            pass

    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "slug": slug,
        "command": command,
        "command_version": "",  # filled in by T009 session stamping
        "phase": phase,
        "status": "running",
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "repo_id": repo_id,
        "repo_root": repo_root,
        "git_common_dir": git_common_dir,
        "worktree_path": worktree_path,
        "branch": branch,
        "started_at": now,
        "last_heartbeat": now,
        "current_task": "",
        "scope": [],
    }


# ── subcommand implementations ─────────────────────────────────────────────────

def cmd_register(args: argparse.Namespace) -> int:
    """register subcommand. Returns exit code (0 = ok, 3 = failure)."""
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        print(
            f"[active-plan-registry] ERROR: run-id {run_id!r} is not a safe basename "
            "(must match ^[A-Za-z0-9._-]+$, no leading dash, no '..', no '/').",
            file=sys.stderr,
        )
        return 3

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] FATAL: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        return 3

    record_path = active_dir / f"{run_id}.json"

    try:
        record = _build_record(
            run_id=run_id,
            slug=args.slug,
            command=args.command,
            phase=args.phase,
            session_id=getattr(args, "session", "") or "",
        )
        _atomic_write(record_path, record)
    except OSError as exc:
        print(
            f"[active-plan-registry] FATAL: register failed for run-id {run_id!r}: {exc}",
            file=sys.stderr,
        )
        return 3

    _emit_event(run_id, "plan_registered", {
        "run_id": run_id,
        "slug": record["slug"],
        "command": record["command"],
        "phase": record["phase"],
    })
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    """heartbeat subcommand. NON-FATAL — always returns 0."""
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        return 0  # non-fatal; invalid id would be a bug in the caller

    try:
        active_dir = _active_plans_dir()
    except RuntimeError:
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    try:
        record = _atomic_read(record_path)
        if record is None:
            # File was reaped while alive — recreate minimal record (benign).
            record = {
                "schema_version": 1,
                "run_id": run_id,
                "session_id": "",
                "slug": "",
                "command": "",
                "command_version": "",
                "phase": getattr(args, "phase", "") or "",
                "status": "running",
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "repo_id": "",
                "repo_root": "",
                "git_common_dir": "",
                "worktree_path": "",
                "branch": "",
                "started_at": _iso_now(),
                "last_heartbeat": _iso_now(),
                "current_task": getattr(args, "current_task", "") or "",
                "scope": [],
            }
        else:
            record["last_heartbeat"] = _iso_now()
            if getattr(args, "phase", None):
                record["phase"] = args.phase
            if getattr(args, "current_task", None) is not None:
                record["current_task"] = args.current_task
            if getattr(args, "status", None):
                record["status"] = args.status
        _atomic_write(record_path, record)
    except OSError:
        pass  # non-fatal
    return 0


def cmd_update_scope(args: argparse.Namespace) -> int:
    """update-scope subcommand. NON-FATAL — always returns 0."""
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        return 0  # non-fatal

    try:
        active_dir = _active_plans_dir()
    except RuntimeError:
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    try:
        scope_path = Path(args.scope_json)
        with scope_path.open("r", encoding="utf-8") as fh:
            new_scope = json.load(fh)
        if not isinstance(new_scope, list):
            return 0  # non-fatal: malformed scope is a caller bug

        record = _atomic_read(record_path)
        if record is None:
            return 0  # record gone — non-fatal

        record["scope"] = new_scope
        record["last_heartbeat"] = _iso_now()
        _atomic_write(record_path, record)
    except (OSError, json.JSONDecodeError):
        pass  # non-fatal
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """list subcommand. Returns 0 always."""
    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] WARNING: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        if getattr(args, "json", False):
            print("[]")
        return 0

    records: list[dict] = []
    if active_dir.is_dir():
        for p in sorted(active_dir.glob("*.json")):
            rec = _atomic_read(p)
            if rec is None:
                continue  # skip torn/partial files
            records.append(rec)

    if getattr(args, "json", False):
        print(json.dumps(records, indent=2))
    else:
        if not records:
            print("(no active plans)")
            return 0
        for rec in records:
            run_id = rec.get("run_id", "?")
            slug = rec.get("slug", "?")
            command = rec.get("command", "?")
            phase = rec.get("phase", "?")
            status = rec.get("status", "?")
            branch = rec.get("branch", "?")
            task = rec.get("current_task", "")
            hb = rec.get("last_heartbeat", "?")
            task_str = f"  task={task}" if task else ""
            print(
                f"{run_id}  slug={slug}  cmd={command}  phase={phase}  "
                f"status={status}  branch={branch}{task_str}  hb={hb}"
            )
    return 0


def cmd_deregister(args: argparse.Namespace) -> int:
    """deregister subcommand. NON-FATAL — always returns 0."""
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        return 0  # non-fatal

    try:
        active_dir = _active_plans_dir()
    except RuntimeError:
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    final_status = getattr(args, "status", "complete") or "complete"

    try:
        # Read record before deletion so we can include slug in the event.
        record = _atomic_read(record_path)
        record_path.unlink()
    except FileNotFoundError:
        record = None  # already gone — benign
    except OSError:
        record = None  # non-fatal

    _emit_event(run_id, "plan_deregistered", {
        "run_id": run_id,
        "slug": (record or {}).get("slug", ""),
        "status": final_status,
    })
    return 0


# ── argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="active-plan-registry.py",
        description="Lockless per-run active-plan registry.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # register
    p_reg = sub.add_parser("register", help="Register a new run.")
    p_reg.add_argument("--run-id", required=True, help="Unique run identifier (safe basename).")
    p_reg.add_argument("--slug", required=True, help="Plan slug.")
    p_reg.add_argument("--command", required=True, help="Command name (e.g. /z-implement-all).")
    p_reg.add_argument("--phase", required=True, help="Current phase (e.g. implement).")
    p_reg.add_argument("--session", default="", help="Session ID (optional).")

    # heartbeat
    p_hb = sub.add_parser("heartbeat", help="Update heartbeat for a live run.")
    p_hb.add_argument("--run-id", required=True)
    p_hb.add_argument("--phase", default=None)
    p_hb.add_argument("--current-task", default=None, dest="current_task")
    p_hb.add_argument("--status", choices=["running", "paused"], default=None)

    # update-scope
    p_scope = sub.add_parser("update-scope", help="Merge scope array into record.")
    p_scope.add_argument("--run-id", required=True)
    p_scope.add_argument("--scope-json", required=True, help="Path to JSON file with scope array.")

    # list
    p_list = sub.add_parser("list", help="List all active-plan records.")
    p_list.add_argument("--json", action="store_true", help="Output as JSON array.")

    # deregister
    p_dereg = sub.add_parser("deregister", help="Remove a run record.")
    p_dereg.add_argument("--run-id", required=True)
    p_dereg.add_argument(
        "--status",
        choices=["complete", "aborted"],
        default="complete",
    )

    return parser


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "register": cmd_register,
        "heartbeat": cmd_heartbeat,
        "update-scope": cmd_update_scope,
        "list": cmd_list,
        "deregister": cmd_deregister,
    }
    handler = dispatch.get(args.subcommand)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
