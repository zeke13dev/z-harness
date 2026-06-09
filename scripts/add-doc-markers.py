#!/usr/bin/env python3
"""
add-doc-markers.py — Add AUTO-START/AUTO-END delimiter markers to existing human-tier docs.

Scans docs/human/*.md and wraps machine-truth sections in markers:
  - ## Key entry points → AUTO-START: entry-points
  - ## Public API or equivalent → AUTO-START: exports
  - Configuration tables → AUTO-START: config-table

Idempotent: running twice on same file produces no changes.
"""

import argparse
import os
import re
import sys

SECTION_PATTERNS = [
    # (heading_regex, marker_name)
    (re.compile(r'^(## Key entry points\s*\n)', re.MULTILINE), "entry-points"),
    (re.compile(r'^(## Public API\s*\n)', re.MULTILINE), "exports"),
    (re.compile(r'^(## Exports\s*\n)', re.MULTILINE), "exports"),
    (re.compile(r'^(## Configuration\s*\n)', re.MULTILINE), "config-table"),
]

AUTO_START = "<!-- AUTO-START: {name} -->"
AUTO_END = "<!-- AUTO-END: {name} -->"
AUTO_START_RE = re.compile(r'<!--\s*AUTO-START:\s*[a-zA-Z0-9_-]+\s*-->')


def has_markers(content: str) -> bool:
    """Check if the doc already has AUTO-START/AUTO-END markers."""
    return bool(AUTO_START_RE.search(content))


def add_markers_to_doc(path: str, dry_run: bool = False) -> bool:
    """Add markers to a single doc file. Returns True if changes were made."""
    with open(path) as f:
        content = f.read()

    if has_markers(content):
        return False

    modified = content
    for heading_re, marker_name in SECTION_PATTERNS:
        match = heading_re.search(modified)
        if not match:
            continue
        hdr = match.group(1)
        # Find the end of this section (next ## heading or end of file)
        start_pos = match.end()
        next_section = re.search(r'^## ', modified[start_pos:], re.MULTILINE)
        if next_section:
            end_pos = start_pos + next_section.start()
        else:
            end_pos = len(modified)

        section_body = modified[start_pos:end_pos].rstrip()
        marked_section = (
            hdr
            + AUTO_START.format(name=marker_name) + "\n"
            + section_body + "\n"
            + AUTO_END.format(name=marker_name) + "\n"
        )
        modified = modified[:match.start()] + marked_section + modified[end_pos:]

    if modified == content:
        return False

    if dry_run:
        print(f"  [dry-run] Would add markers to {path}")
    else:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(modified)
        os.replace(tmp, path)
        print(f"  Added markers to {path}")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add AUTO-START/AUTO-END delimiter markers to human-tier docs"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show diffs, don't write")
    parser.add_argument("--doc-dir", default="docs/human",
                        help="Directory containing human-tier docs (default: docs/human)")
    args = parser.parse_args()

    if not os.path.isdir(args.doc_dir):
        print(f"Error: doc directory '{args.doc_dir}' not found", file=sys.stderr)
        sys.exit(1)

    docs = sorted(
        f for f in os.listdir(args.doc_dir)
        if f.endswith(".md") and not f.startswith(".")
    )

    changed = 0
    for doc in docs:
        path = os.path.join(args.doc_dir, doc)
        if add_markers_to_doc(path, args.dry_run):
            changed += 1

    print(f"\nProcessed {len(docs)} docs, added markers to {changed}.")
    if args.dry_run:
        print("[dry-run] No files were modified.")


if __name__ == "__main__":
    main()
