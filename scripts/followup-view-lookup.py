#!/usr/bin/env python3
"""
scripts/followup-view-lookup.py — CLI for loading/finding entries in index.view.json.

Replaces the inlined load_view / find_in_view heredocs in the 5 z-followup-* command
markdown files with a single scriptable entrypoint.

Modes
-----
--mode=find  (default)
    Search both views for a single entry by --id.
    Prints JSON: {"found": true/false, "entry": {...}, "sink": "project"|"global"}
    Requires: --id, --project-view, --global-view
    Exits 0 on success (even if not found — caller must check "found" field).
    Exits 1 on usage error.

--mode=load
    Load all entries from a single view file.
    Prints JSON array of entry objects.
    Requires: --view
    Optional: --sink-label=<string>  (stamps entry["sink"] if missing)
    Exits 0 always (returns [] on missing/invalid file).
    Exits 1 on usage error.

Exit codes
----------
0  success (output on stdout)
1  usage/argument error (message on stderr)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def load_view_entries(path: str, sink_label: str = "") -> list:
    """Load entries from an index.view.json file.

    Returns a list of entry dicts.  Returns [] if the file is absent, unreadable,
    or not valid JSON.  Stamps entry["sink"] = sink_label on each entry that does
    not already have a "sink" field (matches the inline heredoc behaviour).
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            entries_obj = data.get("entries", {})
            raw = list(entries_obj.values()) if isinstance(entries_obj, dict) else entries_obj
        else:
            raw = data
        if not isinstance(raw, list):
            return []
        # Stamp sink label if requested and field is absent
        if sink_label:
            for entry in raw:
                if isinstance(entry, dict) and "sink" not in entry:
                    entry["sink"] = sink_label
        return raw
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        return []


def find_in_view(view_path: str, entry_id: str, sink_label: str) -> dict | None:
    """Return the entry dict from a single view file, or None if not found.

    Stamps entry["_sink"] = sink_label on the returned entry (matches the inline
    heredoc behaviour in z-followup-dismiss.md and z-followup-refresh.md).
    """
    if not os.path.exists(view_path):
        return None
    try:
        with open(view_path, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        if not isinstance(entries, dict):
            return None
        entry = entries.get(entry_id)
        if entry and isinstance(entry, dict):
            entry["_sink"] = sink_label
        return entry
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def cmd_find(args: argparse.Namespace) -> int:
    if not args.id:
        print("followup-view-lookup: --id is required for --mode=find", file=sys.stderr)
        return 1
    if not args.project_view:
        print("followup-view-lookup: --project-view is required for --mode=find", file=sys.stderr)
        return 1
    if not args.global_view:
        print("followup-view-lookup: --global-view is required for --mode=find", file=sys.stderr)
        return 1

    entry_id = args.id

    entry = find_in_view(args.project_view, entry_id, "project")
    sink = "project"
    if entry is None:
        entry = find_in_view(args.global_view, entry_id, "global")
        sink = "global"

    if entry is None:
        print(json.dumps({"found": False}))
    else:
        print(json.dumps({"found": True, "entry": entry, "sink": sink}))
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    if not args.view:
        print("followup-view-lookup: --view is required for --mode=load", file=sys.stderr)
        return 1

    entries = load_view_entries(args.view, sink_label=args.sink_label or "")
    print(json.dumps(entries))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="followup-view-lookup",
        description="Load or search index.view.json files for the followup sink",
    )
    parser.add_argument(
        "--mode",
        default="find",
        choices=["find", "load"],
        help="Operation mode: 'find' (default) looks up a single entry; 'load' dumps all entries",
    )
    parser.add_argument("--id", default="", help="Entry ID to look up (--mode=find)")
    parser.add_argument("--project-view", default="", help="Path to project index.view.json (--mode=find)")
    parser.add_argument("--global-view", default="", help="Path to global index.view.json (--mode=find)")
    parser.add_argument("--view", default="", help="Path to a single index.view.json (--mode=load)")
    parser.add_argument("--sink-label", default="", help="Sink label to stamp on entries lacking 'sink' field (--mode=load)")

    args = parser.parse_args()

    if args.mode == "find":
        return cmd_find(args)
    else:
        return cmd_load(args)


if __name__ == "__main__":
    sys.exit(main())
