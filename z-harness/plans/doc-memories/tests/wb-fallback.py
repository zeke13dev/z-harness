#!/usr/bin/env python3
"""
Word-boundary fallback simulation for doc-fetcher step 2.5e.

Mimics what doc-fetcher does when `rg` is unavailable (exit 127):
- Reads MEMORIES-FLAT.md
- For each non-header line (skip lines starting with '#'), applies
  re.search(r'\b' + re.escape(token) + r'\b', line, re.IGNORECASE)
  for every query token, keeping lines that match ALL tokens.
- Preserves file order (no re-sorting).
- Parses the leading [<slug>] from surviving lines.
- Prints matched slugs one per line (deduplicated, preserving first occurrence order).

Usage:
    python3 wb-fallback.py --memories-flat <path> --query <query string> [--tags <tag1,tag2>]

Exit codes:
    0 — success (may print zero slugs if no match)
    1 — argument error
    2 — file read error
"""

import argparse
import re
import sys


def load_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except OSError as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def tokenize_query(query: str) -> list[str]:
    """Strip punctuation and split on whitespace to get query tokens."""
    # Remove regex metacharacters and split
    stripped = re.sub(r"[^\w\s]", " ", query)
    return [t for t in stripped.split() if t]


def word_boundary_match(line: str, tokens: list[str], tags: list[str]) -> bool:
    """Return True if the line matches all tokens and all tag constraints."""
    for token in tokens:
        pattern = r"\b" + re.escape(token) + r"\b"
        if not re.search(pattern, line, re.IGNORECASE):
            return False
    for tag in tags:
        tag_pattern = r"tags:[^)]*" + re.escape(tag)
        if not re.search(tag_pattern, line, re.IGNORECASE):
            return False
    return True


def parse_slug(line: str) -> str | None:
    """
    Parse the leading [<slug>] from a MEMORIES-FLAT.md line.

    The slug can contain regex-special characters including brackets (e.g.
    'weird-[brackets]'). The line format is:
        [<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: ...)

    The second field always has the shape '[ <TYPE-word> <YYYY-MM-DD>]'.
    We find the boundary by matching '] [<word> <digit>' to locate where
    the slug block ends, then extract everything between the first '[' and
    that boundary.
    """
    # The second [...] block starts with '] [<TYPE> <DATE>]'
    # TYPE is one of: incident, anti_pattern, abandoned_path, performance_trap,
    #                 decision_rationale, open_question, unknown
    m = re.match(r"^\[(.+)\] \[[A-Za-z_]+ \d{4}-\d{2}-\d{2}\]", line)
    if m:
        return m.group(1)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Word-boundary fallback for doc-fetcher (simulates step 2.5e)"
    )
    parser.add_argument(
        "--memories-flat",
        required=True,
        help="Path to MEMORIES-FLAT.md",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Search query string",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tag constraints (optional)",
    )
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    tokens = tokenize_query(args.query)

    if not tokens:
        # No tokens — no results
        sys.exit(0)

    lines = load_lines(args.memories_flat)

    seen_slugs: list[str] = []
    seen_set: set[str] = set()

    for line in lines:
        line = line.rstrip("\n")
        # Skip header lines
        if line.startswith("#"):
            continue
        if not line.strip():
            continue
        if word_boundary_match(line, tokens, tags):
            slug = parse_slug(line)
            if slug and slug not in seen_set:
                seen_slugs.append(slug)
                seen_set.add(slug)

    for slug in seen_slugs:
        print(slug)

    sys.exit(0)


if __name__ == "__main__":
    main()
