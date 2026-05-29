#!/usr/bin/env python3
"""
scripts/parse-followups-block.py — tolerant parser for **FOLLOWUPS:** fenced JSON blocks.

Usage:
  python3 scripts/parse-followups-block.py [--reviewer-output <file>]

  If --reviewer-output is given, reads from that file.
  Otherwise reads reviewer return text from stdin.

Output:
  Structured JSON list to stdout (may be empty list []).
  Per-entry validation errors are logged + skipped, never abort.
  Parse failures log followup_block_parse_failed event and return [].

Exit codes:
  0 — success (even if result is empty list)
  1 — fatal I/O error (stdin unreadable, etc.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Required fields per entry
REQUIRED_FIELDS = {"priority", "name", "recommended_command", "cited_paths"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
# recommended_command structural parse: must start with /z- followed by kebab-case
COMMAND_RE = re.compile(r"^/z-[a-z][a-z-]*[a-z](\s.*)?$", re.DOTALL)


def _log_event(kind: str, payload: dict) -> None:
    """Best-effort log to metrics.jsonl via log-event.sh."""
    log_script = REPO_ROOT / "scripts" / "log-event.sh"
    plugin_root = os.environ.get("ANTIGRAVITY_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        log_script = Path(plugin_root) / "scripts" / "log-event.sh"
    try:
        subprocess.run(
            ["bash", str(log_script), "parse-followups", kind, json.dumps(payload)],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        # Logging is best-effort; never abort on log failure
        pass


def _find_followups_block(text: str) -> str | None:
    """
    Find the first ```json fenced block immediately under **FOLLOWUPS:** header.
    Returns the raw JSON string inside the fence, or None if not found.
    """
    # Locate **FOLLOWUPS:** line
    followups_pos = text.find("**FOLLOWUPS:**")
    if followups_pos == -1:
        return None

    # From that position, find the next ```json fence
    after_header = text[followups_pos:]
    fence_start = after_header.find("```json")
    if fence_start == -1:
        return None

    # Find closing ```
    content_start = fence_start + len("```json")
    fence_end = after_header.find("```", content_start)
    if fence_end == -1:
        return None

    return after_header[content_start:fence_end].strip()


def _validate_entry(entry: Any, index: int) -> dict | None:
    """
    Validate a single follow-up entry object.
    Returns the validated/normalized dict, or None if invalid (with logging).
    """
    if not isinstance(entry, dict):
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "entry_not_object",
            "raw": str(entry)[:200],
        })
        return None

    # Check required fields
    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "missing_required_fields",
            "missing": sorted(missing),
        })
        return None

    # Validate priority
    priority = entry.get("priority")
    if priority not in VALID_PRIORITIES:
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "invalid_priority",
            "value": str(priority)[:50],
        })
        return None

    # Validate name
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "invalid_name",
        })
        return None

    # Validate recommended_command
    cmd = entry.get("recommended_command")
    if not isinstance(cmd, str):
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "recommended_command_not_string",
        })
        return None
    if not COMMAND_RE.match(cmd):
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "recommended_command_invalid_format",
            "value": cmd[:200],
        })
        return None
    # No control chars (< 0x20 except space, or 0x7F)
    for ch in cmd:
        cp = ord(ch)
        if (cp < 0x20 and cp != 0x20) or cp == 0x7F or cp == 0:
            _log_event("followup_entry_validation_error", {
                "index": index,
                "reason": "recommended_command_control_chars",
            })
            return None
    if len(cmd) > 2048:
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "recommended_command_too_long",
            "length": len(cmd),
        })
        return None

    # Validate cited_paths
    cited = entry.get("cited_paths")
    if not isinstance(cited, list):
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "cited_paths_not_array",
        })
        return None
    if len(cited) > 16:
        _log_event("followup_entry_validation_error", {
            "index": index,
            "reason": "cited_paths_exceeds_cap",
            "count": len(cited),
        })
        return None
    for p in cited:
        if not isinstance(p, str):
            _log_event("followup_entry_validation_error", {
                "index": index,
                "reason": "cited_paths_entry_not_string",
            })
            return None

    # Build normalized output with defaults for optional fields
    return {
        "priority": priority,
        "name": name.strip(),
        "recommended_command": cmd,
        "cited_paths": cited,
        "recommended_command_safe_to_retry": bool(entry.get("recommended_command_safe_to_retry", False)),
        "auto_close_eligible": bool(entry.get("auto_close_eligible", False)),
    }


def parse_followups(text: str) -> list[dict]:
    """
    Parse **FOLLOWUPS:** block from reviewer return text.
    Returns list of validated follow-up entry dicts.
    On parse failure: logs event, returns [].
    Per-entry validation errors: logs + skips, never aborts.
    """
    raw_json = _find_followups_block(text)
    if raw_json is None:
        # No FOLLOWUPS block present — that's fine, return empty
        return []

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        _log_event("followup_block_parse_failed", {
            "reason": "json_decode_error",
            "error": str(exc),
            "raw_text": raw_json[:500],
        })
        return []

    if not isinstance(parsed, list):
        _log_event("followup_block_parse_failed", {
            "reason": "not_an_array",
            "type": type(parsed).__name__,
        })
        return []

    results = []
    for i, entry in enumerate(parsed):
        validated = _validate_entry(entry, i)
        if validated is not None:
            results.append(validated)

    return results


def main() -> int:
    # Parse --reviewer-output flag
    args = sys.argv[1:]
    text: str
    if "--reviewer-output" in args:
        idx = args.index("--reviewer-output")
        if idx + 1 >= len(args):
            print("error: --reviewer-output requires a file path argument", file=sys.stderr)
            return 1
        path = args[idx + 1]
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            text = sys.stdin.read()
        except OSError as exc:
            print(f"error: cannot read stdin: {exc}", file=sys.stderr)
            return 1

    results = parse_followups(text)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
