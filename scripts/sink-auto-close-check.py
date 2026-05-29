"""
scripts/sink-auto-close-check.py — Auto-close consumer ceiling check

Usage:
    python scripts/sink-auto-close-check.py \
        --entry=<path-to-entry-json> \
        --diff=<path-to-diff-file> \
        --test-exit=<int>

Reads config via scripts/config.py:
  - followup.auto_close_low_risk_path_allowlist
  - followup.auto_close_low_risk_path_denylist

Pass conditions (ALL required → exit 0):
  - entry.auto_close_eligible == true
  - entry.completion_mode is null
  - test_exit == 0
  - Pass condition A: diff_stat == 0  (true no-op)
  - Pass condition B: ALL touched paths match allowlist globs
                      AND NONE match denylist globs (denylist takes precedence)

Outputs structured JSON to stdout:
    {"passed": bool, "reason": str, "mode": "noop"|"docs_only"|null}

Exit 0 if pass, 1 if fail.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Glob matching (fnmatch-based with ** support)
# ---------------------------------------------------------------------------

def _match_glob(pattern: str, path: str) -> bool:
    """
    Return True if `path` matches `pattern`.

    Always converts both pattern and path to forward-slash form.

    Rules (matching gitignore / pathspec semantics):
    - `**` matches zero or more path components (including path separators).
    - `*`  matches any sequence of characters that does NOT include `/`.
    - `?`  matches any single character that is not `/`.
    - `*.md` / `/*.md` → only root-level .md files (no slash in path)
    - `**/*.md`      → any .md file at any depth, including root
    - `docs/**/*.md` → any .md file under docs/ at any depth (direct child OK)
    - `commands/**/*.md` → any .md under commands/ at any depth

    A leading `/` on the PATTERN is a root-anchor marker (gitignore style). Since
    `norm_path` already has its leading `/` stripped, the pattern's leading `/`
    must be stripped too — otherwise a root-anchored pattern like `/*.md` could
    never match the (slash-less) `README.md`.
    """
    norm_path = path.replace(os.sep, "/").lstrip("/")
    norm_pattern = pattern.replace(os.sep, "/").lstrip("/")
    regex = _glob_to_regex(norm_pattern)
    return bool(re.fullmatch(regex, norm_path))


def _glob_to_regex(pattern: str) -> str:
    """
    Convert a glob pattern with optional `**` into a Python regex string
    suitable for re.fullmatch().

    `**` matches zero or more path components.
    `*`  matches [^/]* (anything except slash).
    `?`  matches [^/] (any char except slash).
    """
    # Split on ** tokens
    parts = pattern.split("**")
    regex_parts = []
    for i, part in enumerate(parts):
        regex_parts.append(_simple_glob_to_regex(part))
        if i < len(parts) - 1:
            # Between consecutive ** tokens, allow zero or more path components.
            # The adjacent simple fragments may already end/start with "/"; we
            # need to allow "any number of chars including /", including empty.
            # Using `(?:.*/)?` style would fight with adjacent slashes.
            # Simplest correct approach: replace ** with `.*` but also absorb
            # a trailing/leading slash in the adjacent fragments.
            regex_parts.append(".*")
    raw = "".join(regex_parts)
    # Collapse situations like "docs/.*/*.md" where `.*` must also allow zero
    # intermediate segments (i.e. "docs/foo.md").  We do this by making any
    # sub-expression `/<anything>/` that came from `**` also allow `//` collapse.
    # Actually the simpler fix: replace literal `/.*/' patterns to allow the
    # middle part (including the slash) to be optional.
    # We do one normalisation pass: any occurrence of `/.*` that is followed by
    # `/` should be made optional (to allow zero-segment **).
    raw = re.sub(r"/\.\*/", lambda m: "(?:/.*/|/)", raw)
    # Also handle patterns like `docs/.*/*.md` where the leading slash before .*
    # may or may not be present (for `**/*.md` at root level).
    raw = re.sub(r"^\.\*/", "(?:.+/)?", raw)
    return raw


def _simple_glob_to_regex(fragment: str) -> str:
    """Convert a simple glob fragment (no **) into a regex fragment."""
    result = []
    for ch in fragment:
        if ch == "*":
            result.append("[^/]*")
        elif ch == "?":
            result.append("[^/]")
        else:
            result.append(re.escape(ch))
    return "".join(result)


def _path_matches_any(path: str, patterns: list[str]) -> bool:
    """Return True if `path` matches any pattern in `patterns`."""
    for pat in patterns:
        if _match_glob(pat, path):
            return True
    return False


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config_list(key: str, repo_root: str) -> list[str]:
    """
    Load a list config value from config.py via subprocess.

    Falls back to the compile-time DEFAULTS if config.py is not reachable.
    Returns a Python list of strings.
    """
    config_script = Path(repo_root) / "scripts" / "config.py"
    if not config_script.exists():
        return []
    try:
        result = subprocess.run(
            [sys.executable, str(config_script), "get", key],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return []
        raw = result.stdout.strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _auto_close_kill_switch_enabled(repo_root: str) -> tuple[bool, str | None]:
    """Resolve the `followup.auto_close_low_risk_enabled` master kill-switch.

    Returns (enabled, deny_reason). `deny_reason` is non-None only when the
    switch resolves to disabled, and carries a human-readable explanation.

    Semantics (a kill-switch must fail CLOSED on ambiguity):
    - config.py absent          → enabled (no config system present at all; this
      is the unconfigured baseline, e.g. ad-hoc test temp-dirs).
    - config readable bool       → honour the configured value.
    - config present but the read fails / returns a non-bool → DISABLED. An
      operator who set a kill-switch must never be silently overridden by a
      config read error; failing closed is the safe direction for auto-close.
    """
    config_script = Path(repo_root) / "scripts" / "config.py"
    if not config_script.exists():
        return True, None
    try:
        result = subprocess.run(
            [sys.executable, str(config_script), "get",
             "followup.auto_close_low_risk_enabled"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return False, (
                "config.py present but unreadable for the auto-close kill-switch "
                f"(exit {result.returncode}); failing closed"
            )
        parsed = json.loads(result.stdout.strip())
        if not isinstance(parsed, bool):
            return False, (
                "followup.auto_close_low_risk_enabled did not resolve to a bool; "
                "failing closed"
            )
        if not parsed:
            return False, "followup.auto_close_low_risk_enabled is false (master kill-switch)"
        return True, None
    except (json.JSONDecodeError, OSError) as exc:
        return False, (
            f"config.py errored while reading the auto-close kill-switch ({exc}); "
            "failing closed"
        )


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

def _parse_diff(diff_path: str) -> tuple[int, list[str]]:
    """
    Parse a diff file; return (lines_changed, touched_paths).

    Accepts two formats:
    1. git diff --numstat format: "<added>\\t<removed>\\t<path>"
       Rename entries appear as "-\\t-\\t{old}\\t{new}" or "0\\t0\\t{path}".
       Any path present in numstat is a touched path regardless of line counts.
    2. Unified diff format: "diff --git a/<path> b/<path>" headers; or
       "+++ b/<path>" / "--- a/<path>" headers (no "diff --git" prefix).

    Returns (total_lines_changed, list_of_touched_paths).

    IMPORTANT: a diff with file headers but zero content lines (binary, rename,
    mode-only change) returns (0, [non-empty paths list]).  A truly empty diff
    (no headers, no content) returns (0, []).  Callers MUST distinguish these
    cases: the former requires allow/deny path checking; the latter is a true
    no-op.
    """
    content = Path(diff_path).read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    # ------------------------------------------------------------------
    # Numstat format detection.
    # Standard line: "<added>\t<removed>\t<path>"
    # Rename line:   "-\t-\t<old>\t{new}" or "0\t0\t<path>" (when rename
    # collapses to 0 lines changed).
    # We detect numstat if every non-blank line matches either pattern.
    # ------------------------------------------------------------------
    numstat_pattern = re.compile(r"^(\d+)\t(\d+)\t(.+)$")
    # Rename marker: git uses "-\t-\t<path>" for binary/rename in numstat
    numstat_rename_pattern = re.compile(r"^-\t-\t(.+)$")

    non_blank = [l for l in lines if l.strip()]
    if non_blank and all(
        numstat_pattern.match(l) or numstat_rename_pattern.match(l)
        for l in non_blank
    ):
        # Looks like pure numstat output
        total = 0
        paths: list[str] = []
        for line in non_blank:
            m = numstat_pattern.match(line)
            if m:
                total += int(m.group(1)) + int(m.group(2))
                raw_path = m.group(3).strip()
                # Handle rename notation "{old => new}" or plain path
                if raw_path not in paths:
                    paths.append(raw_path)
                continue
            r = numstat_rename_pattern.match(line)
            if r:
                # Binary or rename: counts as touched even though lines = 0
                raw_path = r.group(1).strip()
                if raw_path not in paths:
                    paths.append(raw_path)
        return total, paths

    # ------------------------------------------------------------------
    # Unified diff format.
    # We collect paths from:
    #   (a) "diff --git a/<from> b/<to>" headers (preferred)
    #   (b) "+++ b/<path>" headers when no "diff --git" header is present
    #       (plain `diff -u` output, /dev/null excluded)
    # ------------------------------------------------------------------
    added = 0
    removed = 0
    paths = []
    has_git_header = False

    git_diff_re = re.compile(r"^diff --git a/(.+) b/(.+)$")
    plus_file_re = re.compile(r"^\+\+\+ b/(.+)$")

    for line in lines:
        m = git_diff_re.match(line)
        if m:
            has_git_header = True
            # Use the b/ path (destination) as the canonical touched path
            p = m.group(2).strip()
            if p not in paths:
                paths.append(p)
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    # If no "diff --git" headers found, fall back to "+++ b/<path>" extraction
    if not has_git_header:
        for line in lines:
            m = plus_file_re.match(line)
            if m:
                p = m.group(1).strip()
                if p not in paths and p != "/dev/null":
                    paths.append(p)

    return added + removed, paths


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def run_check(
    entry_path: str,
    diff_path: str,
    test_exit: int,
    repo_root: str | None = None,
) -> tuple[dict, int]:
    """
    Run the auto-close ceiling check.

    Returns (result_dict, exit_code) where exit_code is 0 (pass) or 1 (fail).
    result_dict has keys: passed (bool), reason (str), mode ("noop"|"docs_only"|null).
    """
    # Resolve repo root
    if repo_root is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            )
            repo_root = result.stdout.strip() if result.returncode == 0 else os.getcwd()
        except OSError:
            repo_root = os.getcwd()

    def _fail(reason: str) -> tuple[dict, int]:
        return {"passed": False, "reason": reason, "mode": None}, 1

    def _pass(mode: str) -> tuple[dict, int]:
        return {"passed": True, "reason": "all pass conditions met", "mode": mode}, 0

    # Master kill-switch: if auto_close_low_risk_enabled resolves to false (or to
    # an ambiguous state with config present), deny immediately. Fails CLOSED when
    # config.py exists but cannot be read; stays permissive only when there is no
    # config system at all.
    ks_enabled, ks_reason = _auto_close_kill_switch_enabled(repo_root)
    if not ks_enabled:
        return _fail(ks_reason or "followup.auto_close_low_risk_enabled is false (master kill-switch)")

    # Load entry JSON
    try:
        entry = json.loads(Path(entry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _fail(f"cannot read entry file: {exc}")

    # Check: auto_close_eligible == true
    if not entry.get("auto_close_eligible", False):
        return _fail("entry.auto_close_eligible is not true")

    # Check: completion_mode is null
    if entry.get("completion_mode") is not None:
        return _fail(
            f"entry.completion_mode is not null: {entry['completion_mode']!r}"
        )

    # Check: test_exit == 0
    if test_exit != 0:
        return _fail(f"test_exit={test_exit} (must be 0)")

    # Parse diff
    try:
        diff_stat, touched_paths = _parse_diff(diff_path)
    except (OSError, ValueError) as exc:
        return _fail(f"cannot parse diff file: {exc}")

    # Pass condition A: diff_stat == 0 AND no touched paths (truly empty diff).
    # A diff with file headers but zero content lines (binary, rename, mode-only)
    # has touched_paths non-empty and must fall through to allow/deny checking.
    if diff_stat == 0 and not touched_paths:
        return _pass("noop")

    # Pass condition B: all touched paths match allowlist AND none match denylist
    allowlist = _load_config_list("followup.auto_close_low_risk_path_allowlist", repo_root)
    denylist = _load_config_list("followup.auto_close_low_risk_path_denylist", repo_root)

    # Fallback to spec defaults if config returned empty
    if not allowlist:
        allowlist = ["docs/**/*.md", "**/CHANGELOG", "**/CHANGELOG.md"]
    if not denylist:
        denylist = ["commands/**/*.md", "agents/**/*.md", ".claude/**/*.md", "/*.md"]

    if not touched_paths:
        return _fail("diff has lines but no touched paths could be parsed")

    for path in touched_paths:
        # Denylist takes precedence
        if _path_matches_any(path, denylist):
            return _fail(
                f"touched path {path!r} matches denylist glob (denylist takes precedence)"
            )

    for path in touched_paths:
        if not _path_matches_any(path, allowlist):
            return _fail(
                f"touched path {path!r} does not match any allowlist glob"
            )

    return _pass("docs_only")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-close consumer ceiling check for followup entries."
    )
    parser.add_argument("--entry", required=True, help="Path to entry JSON file")
    parser.add_argument("--diff", required=True, help="Path to diff file")
    parser.add_argument("--test-exit", type=int, required=True, help="Test suite exit code")
    parser.add_argument("--repo-root", default=None, help="Repo root (defaults to git root)")
    args = parser.parse_args(argv)

    result, exit_code = run_check(
        entry_path=args.entry,
        diff_path=args.diff,
        test_exit=args.test_exit,
        repo_root=args.repo_root,
    )
    print(json.dumps(result))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
