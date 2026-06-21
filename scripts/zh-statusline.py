#!/usr/bin/env python3
"""
scripts/zh-statusline.py — Claude Code statusLine HUD for live liveness.

Reads the statusLine JSON contract on stdin and prints ONE status line to stdout.
Designed to run every ~2s (settings `refreshInterval`), so it is fast and fully
defensive: any error path still prints at least the base tier and exits 0 — a
non-zero exit or empty stdout would blank the status line.

Two tiers (plan: statusline-hud):
  - Generic tier (any session): tail the transcript jsonl and detect an in-flight
    subagent — an `Agent`/`Task` tool_use whose `id` has no matching `tool_result`
    `tool_use_id` yet — rendering `> <agent> <elapsed>s`.
  - z-harness tier (during a run): correlate cwd -> active-plan registry and overlay
    `<phase> <current_task> hb<age>s`. Degrades to base tier when no run is active.

Wire via settings.json:
  "statusLine": { "type": "command", "command": "<path>/zh-statusline.py",
                  "refreshInterval": 2 }
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# ANSI — terminals that don't support it still render the text.
DIM = "\033[2m"
RESET = "\033[0m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

# Tail tuning. We read the last N complete lines by scanning backward in blocks,
# so a single huge assistant line (the in-flight tool_use carries the full subagent
# prompt — can be hundreds of KB) is never truncated, while we still never parse a
# whole multi-MB transcript. _TAIL_MAX_BYTES caps the backward scan for safety.
_TAIL_BLOCK = 65536
_TAIL_MAX_LINES = 40
_TAIL_MAX_BYTES = 4 * 1024 * 1024
_SUBAGENT_TOOLS = ("Agent", "Task")


def _tail_lines(path):
    """Return up to the last _TAIL_MAX_LINES complete lines of a file.

    Scans backward in blocks until it has enough newlines, the byte cap is hit, or
    the start is reached — so an arbitrarily long final line is captured whole
    (the in-flight tool_use line), unlike a fixed seek-from-end which can split it.
    """
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        buf = b""
        while pos > 0 and buf.count(b"\n") <= _TAIL_MAX_LINES and len(buf) < _TAIL_MAX_BYTES:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
    lines = buf.decode("utf-8", "replace").splitlines()
    return lines[-_TAIL_MAX_LINES:]


def _read_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return {}


def _parse_ts(ts):
    """Parse an ISO-8601 timestamp (e.g. 2026-06-21T18:10:53.848Z) to epoch secs."""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(ts, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
    return None


def _fmt_elapsed(secs):
    if secs is None or secs < 0:
        return "?"
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def _base_tier(data):
    model = ((data.get("model") or {}).get("display_name")) or "claude"
    parts = [model]
    pct = (data.get("context_window") or {}).get("used_percentage")
    if isinstance(pct, (int, float)):
        parts.append(f"ctx {int(pct)}%")
    cost = (data.get("cost") or {}).get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost > 0:
        parts.append(f"${cost:.2f}")
    return " · ".join(parts)


def _agent_label(block):
    inp = block.get("input") or {}
    label = inp.get("subagent_type") or inp.get("description") or "subagent"
    label = str(label).strip().splitlines()[0]
    return label[:32]


def _inflight_subagent(transcript_path, now):
    """Return (label, elapsed_secs) for an in-flight subagent, else None."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    try:
        tail = _tail_lines(transcript_path)
    except Exception:
        return None

    starts = {}   # tool_use_id -> (block, ts)
    done = set()  # tool_use_ids that have a result
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        ts = ev.get("timestamp")
        for blk in content:
            if not isinstance(blk, dict):
                continue
            btype = blk.get("type")
            if btype == "tool_use" and blk.get("name") in _SUBAGENT_TOOLS:
                if blk.get("id"):
                    starts[blk["id"]] = (blk, ts)
            elif btype == "tool_result":
                tid = blk.get("tool_use_id")
                if tid:
                    done.add(tid)

    # Any tool_use whose result is in this window resolves; results never precede
    # their tool_use, so an in-window tool_use with no in-window result is in-flight.
    open_starts = [(blk, ts) for tid, (blk, ts) in starts.items() if tid not in done]
    if not open_starts:
        return None
    blk, ts = open_starts[-1]  # most recent
    started = _parse_ts(ts)
    elapsed = (now - started) if started is not None else None
    return _agent_label(blk), elapsed


def _zharness_tier(data, now):
    """Return '<phase> <current_task> hb<age>s' for the correlated run, else None."""
    cwd = data.get("cwd") or os.getcwd()
    registry = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "active-plan-registry.py")
    if not os.path.exists(registry):
        return None
    try:
        # Short timeout: this runs every ~2s, so a slow registry must not stall
        # the HUD. On non-zero exit or timeout, degrade to base tier.
        proc = subprocess.run(
            [sys.executable, registry, "list", "--json"],
            cwd=cwd, capture_output=True, text=True, timeout=1.5,
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout
        records = json.loads(out) if out.strip() else []
    except Exception:
        return None
    if not records:
        return None

    # Prefer a record matching this session; else the freshest heartbeat.
    sid = data.get("session_id")

    def hb_epoch(rec):
        return _parse_ts(rec.get("last_heartbeat")) or 0.0

    chosen = None
    if sid:
        matches = [r for r in records if r.get("session_id") == sid]
        if matches:
            chosen = max(matches, key=hb_epoch)
    if chosen is None:
        running = [r for r in records if r.get("status") == "running"] or records
        chosen = max(running, key=hb_epoch)

    parts = []
    phase = chosen.get("phase")
    if phase:
        parts.append(str(phase))
    task = chosen.get("current_task")
    if task:
        parts.append(str(task))
    hb = _parse_ts(chosen.get("last_heartbeat"))
    if hb is not None:
        parts.append(f"hb{_fmt_elapsed(now - hb)}")
    return " ".join(parts) if parts else None


def main():
    data = _read_stdin_json()
    now = datetime.now(timezone.utc).timestamp()
    line = _base_tier(data)

    try:
        sub = _inflight_subagent(data.get("transcript_path"), now)
    except Exception:
        sub = None
    if sub:
        label, elapsed = sub
        line += f" · {YELLOW}> {label} {_fmt_elapsed(elapsed)}{RESET}"

    try:
        zh = _zharness_tier(data, now)
    except Exception:
        zh = None
    if zh:
        line += f" · {CYAN}{zh}{RESET}"

    sys.stdout.write(line + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Last-resort: never blank the status line, never exit non-zero.
        sys.stdout.write("claude\n")
    sys.exit(0)
