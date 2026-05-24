#!/usr/bin/env python3
"""
Extract dismissed MR-review findings from archived run snapshots.

Usage:
    python3 scripts/extract-dismissals.py <slug-dir> [--max-runs N] [--global]

For each pair of consecutive runs (R_i, R_{i+1}) in chronological order:
  1. Snapshot at archive/R_i/MR-REVIEW.md = original findings.
  2. Pre-edit copy at archive/R_{i+1}/MR-REVIEW.md.previous-* = what was
     there just before R_{i+1} overrode it (the user-edited version).
  3. Dismissed = findings in (1) whose signature (file, category, normalized_snippet)
     does NOT appear in (2).

Output (stdout): JSON {"signatures": [...], "n_runs_scanned": N}

Exit codes:
  0 — success (even if no dismissals found)
  1 — argument error
"""

import argparse
import json
import re
import string
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_snippet(text: str) -> str:
    """
    Normalize a finding's title/detail for signature matching.

    Steps:
    1. Lowercase.
    2. Collapse internal whitespace to a single space.
    3. Strip leading/trailing punctuation.
    """
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(string.punctuation + " ")
    return text


# ---------------------------------------------------------------------------
# Frontmatter parser (stdlib only — no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter_block(fm_text: str) -> dict:
    """
    Parse a minimal subset of YAML frontmatter sufficient for MR-REVIEW.md.

    Handles:
      - Simple scalar fields:  key: value
      - Block list fields (findings_index):
          findings_index:
            - {id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs}
            - ...
      - Inline list fields:   voices_available: [claude, codex, gemini]

    Returns a dict. On any parse error, returns {}.
    """
    result: dict = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Top-level key: value  (no leading whitespace)
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)', line)
        if not m:
            i += 1
            continue

        key = m.group(1)
        raw_val = m.group(2).strip()

        if raw_val == "":
            # Possibly a block list follows
            block_items = []
            i += 1
            while i < len(lines):
                item_line = lines[i]
                # A list item must start with whitespace + "- "
                if re.match(r'^\s+-\s+', item_line):
                    # Extract the dict literal in braces, or plain value
                    item_content = re.sub(r'^\s+-\s+', '', item_line).strip()
                    parsed_item = _parse_inline_value(item_content)
                    block_items.append(parsed_item)
                    i += 1
                elif item_line.strip() == "" or item_line.startswith(" ") or item_line.startswith("\t"):
                    # Continuation of block or blank line inside block
                    i += 1
                else:
                    # Back to top level
                    break
            result[key] = block_items
        else:
            result[key] = _parse_inline_value(raw_val)
            i += 1

    return result


def _parse_inline_value(raw: str):
    """
    Parse a raw YAML inline value.

    Handles:
      - Inline dict:  {key: val, key2: val2}
      - Inline list:  [a, b, c]
      - Quoted string: "foo" or 'foo'
      - Bare string / number
    """
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        return _parse_inline_dict(raw[1:-1])
    if raw.startswith("[") and raw.endswith("]"):
        return _parse_inline_list(raw[1:-1])
    if (raw.startswith('"') and raw.endswith('"')) or \
       (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    # Try integer
    try:
        return int(raw)
    except ValueError:
        pass
    return raw


def _parse_inline_dict(inner: str) -> dict:
    """Parse the interior of {key: val, key2: val2}."""
    result = {}
    # Split on commas that are not inside nested braces/brackets
    parts = _split_respecting_nesting(inner)
    for part in parts:
        part = part.strip()
        colon_idx = part.find(":")
        if colon_idx == -1:
            continue
        k = part[:colon_idx].strip()
        v = part[colon_idx + 1:].strip()
        result[k] = _parse_inline_value(v)
    return result


def _parse_inline_list(inner: str) -> list:
    """Parse the interior of [a, b, c]."""
    if not inner.strip():
        return []
    parts = _split_respecting_nesting(inner)
    return [_parse_inline_value(p.strip()) for p in parts if p.strip()]


def _split_respecting_nesting(text: str) -> list[str]:
    """Handles YAML scalar splitting at top-level commas; understands single+double quoted strings (with single-quote escape via doubled '') and bracket/brace nesting. Does NOT support YAML block scalars (|, >) or multi-line values — those are not emitted by mr-reviewer's findings_index writer.

    Quote state is only entered when the quote character appears in a YAML
    string-delimiter context: immediately after ``{``, ``[``, ``(``, ``,``, or
    ``:`` (with optional intervening whitespace), or at the very start of the
    current token.  A bare apostrophe inside a plain scalar (e.g. ``Don't``)
    is treated as ordinary text so it does not cause a fake quote state that
    would merge subsequent fields.
    """
    # Characters that, when they are the last non-whitespace character before a
    # quote, signal that the quote is a YAML string delimiter rather than plain
    # text (e.g. an apostrophe in a word like "Don't").
    _DELIMITER_CHARS = frozenset("{[(,:")

    parts = []
    depth = 0
    in_quote: str | None = None  # None, '"', or "'"
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote is not None:
            # Inside a quoted string: only an unescaped matching quote ends it
            if ch == "\\" and i + 1 < len(text):
                # Escaped character — consume both
                current.append(ch)
                i += 1
                current.append(text[i])
            elif ch == in_quote:
                if in_quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    # YAML single-quote escape: doubled '' stays in quote state
                    current.append(ch)
                    i += 1
                    current.append(text[i])
                else:
                    in_quote = None
                    current.append(ch)
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            # Only enter quote state when in a delimiter context:
            # the last non-whitespace character already consumed is a
            # YAML delimiter, or the current token is empty (token start).
            current_str = "".join(current).rstrip()
            in_delimiter_context = (
                not current_str  # token start
                or current_str[-1] in _DELIMITER_CHARS
            )
            if in_delimiter_context:
                in_quote = ch
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def parse_mr_review_frontmatter(path: Path) -> dict:
    """
    Parse the YAML frontmatter block from an MR-REVIEW.md file.

    Returns {} if the file is missing, empty, or has no frontmatter.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    if not text.startswith("---"):
        return {}

    # Find closing ---
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return {}

    fm_text = text[3:end_idx]
    return _parse_frontmatter_block(fm_text)


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

def findings_to_signatures(
    frontmatter: dict,
    *,
    _drop_count: list | None = None,
) -> list[dict]:
    """
    Extract (file, category, normalized_snippet) tuples from frontmatter.

    The findings_index list looks like:
      [{id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs, title: ...}, ...]

    The `title` field is REQUIRED as the snippet source.  Findings that lack a
    `title` are dropped (counted in _drop_count[0] if a list is provided).
    Falling back to the T-MR-NNN id is intentionally NOT done: those IDs are
    re-numbered each run, so using them as snippet would produce spurious
    dismissal matches.
    """
    findings = frontmatter.get("findings_index", [])
    if not isinstance(findings, list):
        return []

    results = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        title_raw = finding.get("title")
        if title_raw is None:
            # title is absent — drop this finding from analysis
            if _drop_count is not None:
                _drop_count[0] += 1
            continue
        file_val = str(finding.get("file", "")).strip()
        category = str(finding.get("category", "")).strip()
        snippet_src = str(title_raw).strip()
        normalized = normalize_snippet(snippet_src)
        if not normalized:
            if _drop_count is not None:
                _drop_count[0] += 1
            continue
        results.append({
            "file": file_val,
            "category": category,
            "normalized_snippet": normalized,
        })
    return results


def signatures_set(sigs: list[dict]) -> set[tuple]:
    """Convert a list of signature dicts to a set of (file, category, snippet) tuples."""
    return {(s["file"], s["category"], s["normalized_snippet"]) for s in sigs}


# ---------------------------------------------------------------------------
# Archive discovery
# ---------------------------------------------------------------------------

_ISO_PREFIX_RE = re.compile(r"^(\d{8}T\d{6}Z)")


def _run_dir_sort_key(d: Path) -> tuple:
    """
    Sort key for an archive run dir.

    Primary: ISO timestamp prefix from the directory name
             (e.g. "20260523T194623Z-mr-review" → "20260523T194623Z").
             Lexicographic sort on this string gives chronological order.
    Fallback: directory mtime (used when the dir name has no ISO prefix,
              e.g. legacy "run-001" style names in tests).
    """
    m = _ISO_PREFIX_RE.match(d.name)
    if m:
        return (0, m.group(1), 0.0)
    return (1, "", d.stat().st_mtime)


def discover_archive_runs(archive_dir: Path) -> list[Path]:
    """
    Return archive run dirs sorted chronologically ascending.

    Sort order: ISO timestamp prefix in the directory name (SPEC canonical form
    "20260523T194623Z-mr-review"), with mtime as a defensive fallback for dirs
    whose names lack the prefix (e.g. test fixtures).

    Each run dir must contain an MR-REVIEW.md snapshot to be included.
    """
    if not archive_dir.is_dir():
        return []

    run_dirs = [
        d for d in archive_dir.iterdir()
        if d.is_dir() and (d / "MR-REVIEW.md").exists()
    ]
    run_dirs.sort(key=_run_dir_sort_key)
    return run_dirs


def get_previous_snapshot(next_run_dir: Path) -> Path | None:
    """
    Find the MR-REVIEW.md.previous-* file in next_run_dir (the user-edited
    version that was present when the next run started).

    If multiple exist, return the one with the highest suffix N (most recent).
    Returns None if no such file exists.
    """
    candidates = list(next_run_dir.glob("MR-REVIEW.md.previous-*"))
    if not candidates:
        return None
    # Sort by the integer suffix; fall back to lexicographic if not parseable
    def _suffix_key(p: Path) -> int:
        suffix = p.name.split("-")[-1]
        try:
            return int(suffix)
        except ValueError:
            return 0
    candidates.sort(key=_suffix_key)
    return candidates[-1]


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def extract_dismissals_from_runs(
    run_dirs: list[Path],
    max_runs: int,
) -> tuple[list[dict], int]:
    """
    Walk run_dirs (chronological ascending), cap to most recent max_runs.

    For each consecutive pair (R_i, R_{i+1}):
      - R_i snapshot: archive/R_i/MR-REVIEW.md
      - User-edited version: archive/R_{i+1}/MR-REVIEW.md.previous-*
      - Dismissed = signatures in R_i snapshot NOT in user-edited version

    Returns (list_of_dismissed_signature_dicts, n_runs_scanned).
    """
    # Cap to most recent max_runs (the runs are sorted ascending, so take from end)
    capped = run_dirs[-max_runs:] if len(run_dirs) > max_runs else run_dirs
    n_runs = len(capped)

    dismissed: list[dict] = []

    for i in range(len(capped) - 1):
        r_i = capped[i]
        r_next = capped[i + 1]

        snapshot_path = r_i / "MR-REVIEW.md"
        previous_path = get_previous_snapshot(r_next)

        if previous_path is None:
            # No user-edited copy archived — skip this pair
            continue

        snapshot_fm = parse_mr_review_frontmatter(snapshot_path)
        previous_fm = parse_mr_review_frontmatter(previous_path)

        snapshot_sigs = findings_to_signatures(snapshot_fm)
        previous_sigs = findings_to_signatures(previous_fm)

        previous_sig_set = signatures_set(previous_sigs)

        for sig in snapshot_sigs:
            key = (sig["file"], sig["category"], sig["normalized_snippet"])
            if key not in previous_sig_set:
                dismissed.append({
                    "file": sig["file"],
                    "category": sig["category"],
                    "normalized_snippet": sig["normalized_snippet"],
                    "prior_run_id": r_i.name,
                })

    return dismissed, n_runs


def collect_run_dirs_for_slug(slug_dir: Path) -> list[Path]:
    """Return sorted (ascending mtime) run dirs under slug_dir/archive/."""
    archive_dir = slug_dir / "archive"
    return discover_archive_runs(archive_dir)


def collect_slug_run_dirs_global(repo_root: Path) -> dict[Path, list[Path]]:
    """
    Walk z-harness/*/archive/ and z-harness/plans/*/archive/ and return a mapping of slug_dir → sorted run_dirs.

    The pairwise dismissal algorithm (R_i → R_{i+1}) must be applied WITHIN each
    slug independently, not across slugs.  Callers receive this grouped structure
    so they can iterate per-slug rather than interleaving runs from different slugs.
    """
    harness_root = repo_root / "z-harness"
    slug_runs: dict[Path, list[Path]] = {}
    if not harness_root.is_dir():
        return slug_runs

    # Roots to search for slugs
    search_roots = [harness_root]
    plans_root = harness_root / "plans"
    if plans_root.is_dir():
        search_roots.append(plans_root)

    for root in search_roots:
        for slug_dir in sorted(root.iterdir()):
            if not slug_dir.is_dir():
                continue
            # Skip plans root itself if we are in harness_root
            if root == harness_root and slug_dir == plans_root:
                continue
            archive_dir = slug_dir / "archive"
            runs = discover_archive_runs(archive_dir)
            if runs:
                slug_runs[slug_dir] = runs
    return slug_runs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract dismissed MR-review findings from archived run snapshots."
    )
    parser.add_argument(
        "slug_dir",
        nargs="?",
        default=None,
        help="Path to slug dir, e.g. z-harness/mr-style-reviewer/. "
             "Required unless --global is set.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=10,
        metavar="N",
        help="Limit to most recent N archived runs (default: 10).",
    )
    parser.add_argument(
        "--global",
        dest="global_scan",
        action="store_true",
        help="Scan z-harness/*/archive/*/MR-REVIEW.md across all slugs.",
    )
    args = parser.parse_args()

    if args.max_runs < 1:
        print("ERROR: --max-runs must be >= 1", file=sys.stderr)
        sys.exit(1)

    if args.global_scan:
        # Resolve repo root: go up from the cwd until we find z-harness/ or hit /
        cwd = Path.cwd()
        repo_root = cwd
        for candidate in [cwd] + list(cwd.parents):
            if (candidate / "z-harness").is_dir():
                repo_root = candidate
                break

        slug_runs = collect_slug_run_dirs_global(repo_root)
        if not slug_runs:
            output = {"signatures": [], "n_runs_scanned": 0}
            json.dump(output, sys.stdout)
            sys.stdout.write("\n")
            return

        all_signatures: list[dict] = []
        total_runs = 0
        for slug_run_dirs in slug_runs.values():
            sigs, n = extract_dismissals_from_runs(slug_run_dirs, args.max_runs)
            all_signatures.extend(sigs)
            total_runs += n

        output = {"signatures": all_signatures, "n_runs_scanned": total_runs}
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    else:
        if args.slug_dir is None:
            print(
                "ERROR: slug_dir is required unless --global is set.",
                file=sys.stderr,
            )
            sys.exit(1)
        slug_dir = Path(args.slug_dir)
        if not slug_dir.is_dir():
            # Gracefully return empty result for missing dir
            output = {"signatures": [], "n_runs_scanned": 0}
            json.dump(output, sys.stdout)
            sys.stdout.write("\n")
            return
        run_dirs = collect_run_dirs_for_slug(slug_dir)

    if not run_dirs:
        output = {"signatures": [], "n_runs_scanned": 0}
        json.dump(output, sys.stdout)
        sys.stdout.write("\n")
        return

    signatures, n_runs = extract_dismissals_from_runs(run_dirs, args.max_runs)

    output = {
        "signatures": signatures,
        "n_runs_scanned": n_runs,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
