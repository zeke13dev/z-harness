#!/usr/bin/env python3
"""
scripts/followup-reconcile-notion-impl.py — sweep notion_sync_pending entries.

Reads the materialized view for both project + global sinks. For each entry
whose latest notion-related JSONL event is notion_sync_pending, re-invokes
notion-push.py. On success: appends notion_synced + notion_sync_cleared events.

Output: JSON summary {swept_count, succeeded, failed, conflicts} to stdout.
Exit: always 0 (best-effort sweep, not a transaction).

Usage:
  followup-reconcile-notion-impl.py [--project-sink-root=<path>]
                                    [--global-sink-root=<path>]
                                    [--dry-run]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ── constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
NOTION_PUSH_PY = SCRIPT_DIR / "notion-push.py"

# Robust import for scripts invoked as standalone
sys.path.insert(0, str(SCRIPT_DIR))
from followup_common import (  # noqa: E402
    iso_now,
    get_config_batch,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Return the git repo root, falling back to CWD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path.cwd()


def _find_pending_entry_ids(sink_root: Path) -> set[str]:
    """
    Scan the JSONL journal for entries whose latest notion-related event
    is notion_sync_pending (not yet cleared by notion_synced or notion_sync_cleared).

    Returns a set of entry IDs that are currently pending sync.
    """
    journal_path = sink_root / "index.jsonl"
    if not journal_path.exists():
        return set()

    # Replay journal: track the latest notion state per entry.
    # Keys: entry_id -> "pending" | "synced" | "cleared"
    notion_state: dict[str, str] = {}

    with journal_path.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("kind", "")
            entry_id = event.get("entry_id", "")
            if not entry_id:
                continue
            if kind == "notion_sync_pending":
                notion_state[entry_id] = "pending"
            elif kind in ("notion_synced", "notion_sync_cleared"):
                notion_state[entry_id] = "synced"

    return {eid for eid, state in notion_state.items() if state == "pending"}


def _read_view(sink_root: Path) -> dict:
    """Read the materialized view and return the entries dict."""
    view_path = sink_root / "index.view.json"
    if not view_path.exists():
        return {}
    try:
        data = json.loads(view_path.read_text(encoding="utf-8"))
        return data.get("entries", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _append_event(sink_root: Path, kind: str, payload: dict) -> None:
    """Append a structured event to sink_root/index.jsonl."""
    journal_path = sink_root / "index.jsonl"
    obj = {"ts": iso_now(), "kind": kind}
    obj.update(payload)
    line = json.dumps(obj, separators=(",", ":")) + "\n"
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _push_entry(
    entry: dict,
    sink_root: Path,
    config_database_id: str,
    config_token_path: str,
    dry_run: bool = False,
) -> tuple[str, str | None]:
    """
    Invoke notion-push.py for a single entry.

    Accepts pre-fetched config values so the caller can fetch them once
    outside the loop (one config.py invocation per sweep, not per entry).

    Returns (status, remote_id_or_None) where status is one of:
      "succeeded", "failed", "conflict"
    """
    if dry_run:
        return "succeeded", entry.get("notion_remote_id") or "dry-run-id"

    # Write entry to a temp file for notion-push.py
    try:
        fd, entry_tmp = tempfile.mkstemp(suffix=".json", prefix=".notion-reconcile-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
        except OSError:
            try:
                os.unlink(entry_tmp)
            except OSError:
                pass
            return "failed", None
    except OSError:
        return "failed", None

    try:
        cmd = [
            sys.executable, str(NOTION_PUSH_PY),
            f"--entry-json={entry_tmp}",
            f"--config-database-id={config_database_id}",
            "--check-existing",
        ]
        if config_token_path:
            cmd.append(f"--secrets-path={config_token_path}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
        return "failed", None
    finally:
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass

    if result.returncode == 0:
        remote_id = None
        try:
            out = json.loads(result.stdout)
            remote_id = out.get("remote_id") or None
        except (json.JSONDecodeError, AttributeError):
            pass
        return "succeeded", remote_id

    if result.returncode == 5:
        # Idempotency mismatch (z_harness_entry_id doesn't match remote page)
        return "conflict", None

    # exit 4 or any other failure
    return "failed", None


def _sweep_sink(
    sink_root: Path,
    proj_root: Path,
    config_database_id: str,
    config_token_path: str,
    dry_run: bool = False,
) -> dict:
    """
    Sweep one sink. Returns partial counters dict:
    {swept_count, succeeded, failed, conflicts}.

    Accepts pre-fetched config values to avoid per-iteration config.py forks.
    """
    counters = {"swept_count": 0, "succeeded": 0, "failed": 0, "conflicts": 0}

    if not sink_root.is_dir():
        return counters

    pending_ids = _find_pending_entry_ids(sink_root)
    if not pending_ids:
        return counters

    entries = _read_view(sink_root)

    for entry_id in pending_ids:
        entry = entries.get(entry_id)
        if entry is None:
            # Entry not in view (unknown entry_id in journal); skip
            print(
                f"followup-reconcile-notion: WARNING: pending entry_id {entry_id!r} "
                f"not found in view; skipping",
                file=sys.stderr,
            )
            continue

        counters["swept_count"] += 1

        status, remote_id = _push_entry(
            entry, sink_root,
            config_database_id=config_database_id,
            config_token_path=config_token_path,
            dry_run=dry_run,
        )

        if status == "succeeded":
            counters["succeeded"] += 1
            if not dry_run:
                # Append notion_synced event (with potentially new remote_id)
                _append_event(sink_root, "notion_synced", {
                    "entry_id": entry_id,
                    "remote_id": remote_id or "",
                })
                # Clear the pending flag
                _append_event(sink_root, "notion_sync_cleared", {
                    "entry_id": entry_id,
                })
        elif status == "conflict":
            counters["conflicts"] += 1
            print(
                f"followup-reconcile-notion: conflict for entry {entry_id!r} "
                f"(z_harness_entry_id mismatch); entry left pending",
                file=sys.stderr,
            )
        else:
            counters["failed"] += 1
            print(
                f"followup-reconcile-notion: push failed for entry {entry_id!r}; "
                f"entry left pending",
                file=sys.stderr,
            )

    return counters


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str]) -> dict:
    """Parse --key=value style arguments."""
    args: dict = {}
    for arg in argv:
        if arg == "--dry-run":
            args["dry_run"] = True
        elif arg.startswith("--project-sink-root="):
            args["project_sink_root"] = arg[len("--project-sink-root="):]
        elif arg.startswith("--global-sink-root="):
            args["global_sink_root"] = arg[len("--global-sink-root="):]
        else:
            print(f"followup-reconcile-notion: unknown argument: {arg}", file=sys.stderr)
            sys.exit(2)
    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    dry_run: bool = args.get("dry_run", False)

    proj_root = _find_project_root()

    # Resolve sink roots
    if "project_sink_root" in args:
        project_sink_root = Path(args["project_sink_root"])
    else:
        project_sink_root = proj_root / "z-harness" / "followups"

    if "global_sink_root" in args:
        global_sink_root = Path(args["global_sink_root"])
    else:
        global_sink_root = Path.home() / ".z-harness" / "followups"

    # Fetch constant config ONCE before the sweep loop — avoids per-entry forks.
    # In dry-run mode these values are not used but fetching them is still
    # correct (and fast, since config.py just reads TOML).
    cfg = get_config_batch(
        ["followup.notion_database_id", "followup.notion_token_path"],
        proj_root,
    )
    config_database_id = cfg.get("followup.notion_database_id") or ""
    config_token_path = cfg.get("followup.notion_token_path") or ""
    if not isinstance(config_database_id, str):
        config_database_id = ""
    if not isinstance(config_token_path, str):
        config_token_path = ""

    # Sweep both sinks and aggregate
    total = {"swept_count": 0, "succeeded": 0, "failed": 0, "conflicts": 0}

    for sink_root, label in [
        (project_sink_root, "project"),
        (global_sink_root, "global"),
    ]:
        partial = _sweep_sink(
            sink_root, proj_root,
            config_database_id=config_database_id,
            config_token_path=config_token_path,
            dry_run=dry_run,
        )
        for key in total:
            total[key] += partial[key]
        if partial["swept_count"] > 0:
            print(
                f"followup-reconcile-notion: {label} sink: "
                f"swept={partial['swept_count']} "
                f"succeeded={partial['succeeded']} "
                f"failed={partial['failed']} "
                f"conflicts={partial['conflicts']}",
                file=sys.stderr,
            )

    print(json.dumps(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
