#!/usr/bin/env python3
"""
scripts/sink-compact-impl.py — log compaction for the follow-up sink.

Reads <sink-root>/index.jsonl, identifies terminal entries (status done or
dismissed), archives their events into <sink-root>/index.archive.jsonl, and
rewrites index.jsonl with only events for non-terminal entries.

After compaction the checkpoint in index.view.json is invalidated by deleting
the file, and sink-view-rebuild.sh <sink-root> --full is invoked to regenerate
a correct view and a fresh checkpoint.

This script MUST be invoked while the global cross-tool lock is held by the
caller — it mutates index.jsonl in place.  It does NOT acquire the lock itself
(callers already hold it; a double-acquire would deadlock).

Exit codes:
  0  success (or no-op: no terminal entries found)
  1  argument error
  2  sink-root not found or not a directory
  3  journal corruption detected (non-parseable line); no changes made
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _log_event(event_kind: str, payload: dict, sink_root: Path) -> None:
    """Emit a structured event via log-event.sh or fallback to events.jsonl."""
    import datetime

    run_id = os.environ.get("Z_HARNESS_RUN", "")
    logged = False
    if run_id:
        log_event_sh = SCRIPT_DIR / "log-event.sh"
        if log_event_sh.exists():
            try:
                subprocess.run(
                    ["bash", str(log_event_sh), run_id, event_kind, json.dumps(payload)],
                    capture_output=True,
                    check=False,
                )
                logged = True
            except OSError:
                pass

    if not logged:
        try:
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            obj = {"ts": ts, "kind": event_kind}
            obj.update(payload)
            line = json.dumps(obj, separators=(",", ":")) + "\n"
            events_path = sink_root / "events.jsonl"
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


# Terminal statuses (entries in these states are candidates for archival).
_TERMINAL_STATUSES = frozenset({"done", "dismissed"})


def compact(sink_root: Path) -> int:
    """Run compaction on the sink at sink_root.

    Returns an integer exit code (0 = success/no-op, 2 = bad dir, 3 = corruption).
    """
    if not sink_root.exists():
        print(f"sink-compact: ERROR: sink-root not found: {sink_root}", file=sys.stderr)
        return 2
    if not sink_root.is_dir():
        print(f"sink-compact: ERROR: sink-root is not a directory: {sink_root}", file=sys.stderr)
        return 2

    journal_path = sink_root / "index.jsonl"
    archive_path = sink_root / "index.archive.jsonl"
    view_path = sink_root / "index.view.json"

    if not journal_path.exists():
        print("sink-compact: journal absent — nothing to compact", file=sys.stderr)
        return 0

    # ── Step 1: Full-replay to identify terminal vs. non-terminal entries ────────
    # Import the reducer (same process — avoids a subprocess for classification).
    # The module filename contains a hyphen, so we must load it via importlib.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "sink_view_reducer",
        str(SCRIPT_DIR / "sink-view-reducer.py"),
    )
    _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
    reduce_journal = _mod.reduce_journal
    JournalCorruptionError = _mod.JournalCorruptionError

    try:
        entries = reduce_journal(journal_path, sink_root=sink_root)
    except JournalCorruptionError as exc:
        position = "final (truncated tail)" if exc.is_final_line else "interior"
        print(
            f"sink-compact: ERROR: journal corruption at line {exc.lineno} "
            f"({position}); aborting compaction without changes",
            file=sys.stderr,
        )
        return 3

    terminal_ids = frozenset(
        entry_id
        for entry_id, entry in entries.items()
        if entry.get("status") in _TERMINAL_STATUSES
    )

    if not terminal_ids:
        print("sink-compact: no terminal entries found — nothing to archive", file=sys.stderr)
        return 0

    # ── Step 2: Classify each journal line by entry ownership ──────────────────
    # A line "belongs" to a terminal entry if:
    #   - entry_created: line["entry"]["id"] in terminal_ids
    #   - all other kinds:  line["entry_id"] in terminal_ids
    #
    # Lines whose entry cannot be identified (unknown/non-standard events, or events
    # that carry neither field) are kept in the live journal (conservative default).

    raw_text = journal_path.read_text(encoding="utf-8")
    lines = raw_text.splitlines()

    terminal_lines: list[str] = []
    live_lines: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            # Preserve blank lines in the live journal (forward-compat).
            live_lines.append(raw)
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            # Corruption was already caught by reduce_journal above; this path
            # should not be reached, but keep the line in live as a safe default.
            live_lines.append(raw)
            continue

        if not isinstance(event, dict):
            live_lines.append(raw)
            continue

        kind = event.get("kind")
        if kind == "entry_created":
            entry_obj = event.get("entry")
            entry_id = entry_obj.get("id") if isinstance(entry_obj, dict) else None
        else:
            entry_id = event.get("entry_id")

        if entry_id in terminal_ids:
            terminal_lines.append(raw)
        else:
            live_lines.append(raw)

    archived_event_count = len(terminal_lines)
    dropped_event_count = len(lines) - len(live_lines)

    # ── Step 3: Append terminal lines to index.archive.jsonl ───────────────────
    archive_block = "\n".join(terminal_lines)
    if terminal_lines:
        archive_block += "\n"
    with archive_path.open("a", encoding="utf-8") as fh:
        fh.write(archive_block)

    # ── Step 4: Atomically rewrite index.jsonl with only live lines ─────────────
    live_text = "\n".join(line for line in live_lines if line.strip())
    if live_text:
        live_text += "\n"
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".index.jsonl.compact.tmp.",
        dir=str(sink_root),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(live_text)
        os.replace(tmp_path_str, str(journal_path))
    except BaseException:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise

    new_journal_size = len(live_text.encode("utf-8"))

    # ── Step 5: Invalidate the T010 checkpoint ──────────────────────────────────
    # Deleting index.view.json forces the next rebuild to do a correct full replay.
    try:
        view_path.unlink()
    except FileNotFoundError:
        pass  # already absent — fine

    # ── Step 6: Run a fresh full rebuild ────────────────────────────────────────
    rebuild_sh = SCRIPT_DIR / "sink-view-rebuild.sh"
    result = subprocess.run(
        ["bash", str(rebuild_sh), str(sink_root), "--full"],
        capture_output=False,
    )
    if result.returncode != 0:
        print(
            f"sink-compact: ERROR: view rebuild after compaction exited {result.returncode}",
            file=sys.stderr,
        )
        return result.returncode

    # ── Step 7: Log a compaction event ──────────────────────────────────────────
    _log_event(
        "followup_log_compacted",
        {
            "sink_root": str(sink_root),
            "terminal_entries_archived": len(terminal_ids),
            "events_archived": archived_event_count,
            "events_dropped": dropped_event_count,
            "new_journal_byte_size": new_journal_size,
        },
        sink_root=sink_root,
    )

    print(
        f"sink-compact: compacted {len(terminal_ids)} terminal entries "
        f"({archived_event_count} events archived, "
        f"new journal {new_journal_size} bytes)",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sink-compact-impl.py",
        description="Log compaction for the follow-up sink journal.",
    )
    parser.add_argument("sink_root", help="Path to the sink root directory")
    args = parser.parse_args()

    return compact(Path(args.sink_root))


if __name__ == "__main__":
    sys.exit(main())
