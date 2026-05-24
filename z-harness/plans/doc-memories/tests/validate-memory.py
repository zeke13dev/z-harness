#!/usr/bin/env python3
"""
Memory schema validator — mirrors /z-suggest-memory Phase 4 validation logic.

Validates a candidate memory entry against the schema defined in SPEC.md and
enforced by /z-suggest-memory. Used by tests to confirm that the validation
rejects invalid entries (e.g. text > 200 chars) with the correct STATUS.

Usage:
    python3 validate-memory.py --type <type> --text <text> --source <source>
                               --date <YYYY-MM-DD> [--tags <t1,t2>]
                               [--expires <YYYY-MM-DD>]

Exit codes:
    0 — validation passed (STATUS: ok printed to stdout)
    1 — validation failed (STATUS: bad_input + reason printed to stdout)
    2 — argument error
"""

import argparse
import re
import sys

VALID_TYPES = {
    "anti_pattern",
    "abandoned_path",
    "incident",
    "performance_trap",
    "decision_rationale",
    "open_question",
}

SOURCE_PATTERN = re.compile(
    r"^(incident:[a-z0-9-]+|spec:[a-z0-9-]+/[A-Za-z0-9-]+|debug:[A-Za-z0-9-]+|human_review:[A-Za-z0-9_@.-]+)$"
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TAG_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

# Simple emoji detection: Unicode ranges for common emoji blocks
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002600-\U000027BF"  # misc symbols (includes ♥ U+2665 — NOT an emoji)
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002702-\U000027B0"
    "]",
    flags=re.UNICODE,
)


def validate(
    mem_type: str,
    text: str,
    source: str,
    date: str,
    tags: list[str],
    expires: str | None,
) -> tuple[bool, str]:
    """
    Validate a memory entry.
    Returns (ok: bool, message: str).
    Message is the error detail on failure, or 'ok' on success.
    """
    # type
    if mem_type not in VALID_TYPES:
        return False, f'type "{mem_type}" is not a valid memory type'

    # text length
    if len(text) > 200:
        return False, f"text exceeds 200 characters ({len(text)} chars); trim and resubmit"

    # text no newlines
    if "\n" in text or "\r" in text:
        return False, "text contains a newline; memory must be a single line"

    # text no emojis
    if EMOJI_PATTERN.search(text):
        return False, "text contains an emoji; memories must be plain ASCII/Unicode text without emoji"

    # tags kebab-case
    for tag in tags:
        if not TAG_PATTERN.match(tag):
            return False, f'tag "{tag}" is not kebab-case; use lowercase letters, digits, and hyphens only'

    # source regex
    if not SOURCE_PATTERN.match(source):
        return False, f'source "{source}" does not match the required format'

    # date format
    if not DATE_PATTERN.match(date):
        return False, f'date "{date}" is not YYYY-MM-DD'

    # expires format (optional)
    if expires is not None and not DATE_PATTERN.match(expires):
        return False, f'expires "{expires}" is not YYYY-MM-DD'

    return True, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a memory entry against /z-suggest-memory schema"
    )
    parser.add_argument("--type", dest="mem_type", required=True, help="Memory type enum")
    parser.add_argument("--text", required=True, help="Memory text (<=200 chars, no newlines)")
    parser.add_argument("--source", required=True, help="Source prefix:ref string")
    parser.add_argument("--date", required=True, help="Date YYYY-MM-DD")
    parser.add_argument("--tags", default="", help="Comma-separated tags (kebab-case)")
    parser.add_argument("--expires", default=None, help="Optional expiry date YYYY-MM-DD")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    ok, message = validate(
        mem_type=args.mem_type,
        text=args.text,
        source=args.source,
        date=args.date,
        tags=tags,
        expires=args.expires,
    )

    if ok:
        print("STATUS: ok")
        sys.exit(0)
    else:
        print(f"STATUS: bad_input")
        print(f"REASON: {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
