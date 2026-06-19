#!/usr/bin/env python3
"""amendment-brief.py — Render an amendment brief from correction/approach JSON.

Usage:
    amendment-brief.py <file.json>
    echo '{"corrections":[...],"approach_concerns":[...]}' | amendment-brief.py

Input JSON schema:
    {
      "corrections": [{"title": str, "why": str, "target": str}, ...],
      "approach_concerns": [{"concern": str, "affected"?: str, "suggestion"?: str}, ...]
    }

Output (markdown):
    Patched automatically (N corrections):
    - <title> — <why> [<target>]
    (or "none." when N==0)

    Worth your eyes (M):          ← only when M > 0
    <concern prose ending in "rework <affected>, or proceed?">
    ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def render_brief(data: dict) -> str:
    """Render the amendment brief as markdown.

    Args:
        data: dict with keys "corrections" (list) and "approach_concerns" (list).

    Returns:
        Deterministic markdown string ending with a newline.
    """
    corrections: list[dict] = data.get("corrections") or []
    approach_concerns: list[dict] = data.get("approach_concerns") or []

    lines: list[str] = []

    # --- Section 1: always present ---
    n = len(corrections)
    lines.append(f"Patched automatically ({n} corrections):")
    if n == 0:
        lines[-1] += " none."
    else:
        for item in corrections:
            title = item.get("title", "").strip()
            why = item.get("why", "").strip()
            target = item.get("target", "").strip()
            bullet = f"- {title}"
            if why:
                bullet += f" — {why}"
            if target:
                bullet += f" [{target}]"
            lines.append(bullet)

    # --- Section 2: only when non-empty ---
    m = len(approach_concerns)
    if m > 0:
        lines.append("")
        lines.append(f"Worth your eyes ({m}):")
        for item in approach_concerns:
            concern = item.get("concern", "").strip()
            affected = (item.get("affected") or "").strip()
            suggestion = (item.get("suggestion") or "").strip()
            # Build prose sentence
            prose = concern
            if suggestion:
                prose += f" {suggestion}"
            if affected:
                prose += f" rework {affected}, or proceed?"
            else:
                prose += " rework this, or proceed?"
            lines.append(prose)

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render an amendment brief from correction/approach JSON",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="JSON input file (reads from stdin if omitted)",
    )
    args = parser.parse_args(argv)

    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"amendment-brief.py: cannot read {args.file}: {exc}", file=sys.stderr)
            return 1
    else:
        text = sys.stdin.read()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"amendment-brief.py: invalid JSON: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(render_brief(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
