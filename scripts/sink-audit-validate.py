"""
scripts/sink-audit-validate.py — Audit evidence validator (11-point check)

Usage:
    python scripts/sink-audit-validate.py <audit_evidence.json> <entry.json> [<repo_root>]

argv[1] = path to audit_evidence.json
argv[2] = path to entry JSON file (contains id, cited_paths, recommended_command)
argv[3] = repo_root (defaults to git rev-parse --show-toplevel)

Outputs a JSON object on stdout:
    {"passed": true|false, "rejected_check": <int|null>, "reason": "<str>"}

Exit 0 if all checks pass, 1 if any check fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _git_root_from_cmd() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("git rev-parse --show-toplevel failed: " + result.stderr.strip())
    return result.stdout.strip()


def _fail(check: int, reason: str) -> dict:
    return {"passed": False, "rejected_check": check, "reason": reason}


def _pass() -> dict:
    return {"passed": True, "rejected_check": None, "reason": "all checks passed"}


def _resolve_path(path_str: str, repo_root: str) -> Path:
    """Resolve a path: absolute if it already is, otherwise relative to repo_root."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return Path(repo_root) / p


def validate(evidence_path: str, entry_path: str, repo_root: str) -> dict:
    """
    Run all 11 validation checks against the given audit_evidence.json and
    entry JSON file. Returns a result dict with 'passed', 'rejected_check',
    and 'reason'.
    """

    # ── Check 1: File exists at expected path ──────────────────────────────────
    ev_path = Path(evidence_path)
    if not ev_path.exists():
        return _fail(1, f"audit_evidence.json not found: {evidence_path}")

    # Load audit evidence JSON
    try:
        evidence = json.loads(ev_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _fail(1, f"audit_evidence.json is not valid JSON: {exc}")

    # Load entry JSON
    entry_file = Path(entry_path)
    if not entry_file.exists():
        return _fail(1, f"entry JSON not found: {entry_path}")
    try:
        entry = json.loads(entry_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _fail(1, f"entry JSON is not valid JSON: {exc}")

    # ── Check 2: schema_version == 1 ───────────────────────────────────────────
    if evidence.get("schema_version") != 1:
        return _fail(2, f"schema_version must be 1, got {evidence.get('schema_version')!r}")

    # ── Check 3: entry_id matches ──────────────────────────────────────────────
    ev_entry_id = evidence.get("entry_id")
    entry_id = entry.get("id")
    if ev_entry_id != entry_id:
        return _fail(
            3,
            f"entry_id mismatch: evidence has {ev_entry_id!r}, entry has {entry_id!r}",
        )

    # ── Check 4: review_verdict_path AND diff_artifact_path both exist ─────────
    verdict_path_str = evidence.get("review_verdict_path", "")
    diff_path_str = evidence.get("diff_artifact_path", "")

    # Reject non-string values — a JSON array or integer is not a valid file path
    # and would crash on Path() / str operations.
    if not isinstance(verdict_path_str, str):
        return _fail(4, f"review_verdict_path must be a string, got {type(verdict_path_str).__name__}")
    if not isinstance(diff_path_str, str):
        return _fail(4, f"diff_artifact_path must be a string, got {type(diff_path_str).__name__}")

    # Reject empty field values explicitly before path resolution — an empty string
    # resolves to repo_root itself (Path(root) / ""), which is always a directory,
    # causing a false-positive "exists" or a crash on read_text() later.
    if not verdict_path_str:
        return _fail(4, "review_verdict_path is missing or empty")
    if not diff_path_str:
        return _fail(4, "diff_artifact_path is missing or empty")

    verdict_path = _resolve_path(verdict_path_str, repo_root)
    diff_path = _resolve_path(diff_path_str, repo_root)

    if not verdict_path.is_file():
        return _fail(4, f"review_verdict_path does not exist: {verdict_path_str}")
    if not diff_path.is_file():
        return _fail(4, f"diff_artifact_path does not exist: {diff_path_str}")

    # ── Check 5: review_verdict == "PASS" (literal) ────────────────────────────
    if evidence.get("review_verdict") != "PASS":
        return _fail(
            5,
            f"review_verdict must be literal 'PASS', got {evidence.get('review_verdict')!r}",
        )

    # ── Check 6: test_exit_code == 0 (literal) ─────────────────────────────────
    if evidence.get("test_exit_code") != 0:
        return _fail(
            6,
            f"test_exit_code must be 0, got {evidence.get('test_exit_code')!r}",
        )

    # ── Check 7: git merge-base --is-ancestor <capture_head> <verify_head> ─────
    capture_head = evidence.get("capture_head", "")
    verify_head = evidence.get("verify_head", "")

    git_result = subprocess.run(
        ["git", "-C", repo_root, "merge-base", "--is-ancestor", capture_head, verify_head],
        capture_output=True,
    )
    if git_result.returncode != 0:
        return _fail(
            7,
            f"git merge-base --is-ancestor {capture_head!r} {verify_head!r} failed "
            f"(verify_head does not descend from capture_head, or refs are invalid): "
            f"{git_result.stderr.decode(errors='replace').strip()}",
        )

    # ── Check 8: verified_by_run is a valid run id in some plan's archive ──────
    verified_by_run = evidence.get("verified_by_run", "")
    # Reject non-string values — an integer or list is not a valid run id.
    if not isinstance(verified_by_run, str):
        return _fail(
            8,
            f"verified_by_run must be a string, got {type(verified_by_run).__name__}",
        )
    # Reject empty or path-traversal values before any filesystem lookup.
    # An empty string causes Path(archive_dir) / "" == archive_dir itself,
    # making any plan's archive directory a false match.
    if not verified_by_run or "/" in verified_by_run or ".." in verified_by_run:
        return _fail(
            8,
            f"verified_by_run {verified_by_run!r} is invalid — "
            f"must be a non-empty run id with no path separators or traversal",
        )
    # Look for z-harness/<some-slug>/archive/<run-id>/ under repo_root.
    # Two layouts are supported:
    #   Legacy:    z-harness/<slug>/archive/<run-id>/
    #   Canonical: z-harness/plans/<slug>/archive/<run-id>/
    harness_dir = Path(repo_root) / "z-harness"
    found_run = False
    if harness_dir.is_dir():
        # Legacy layout: iterate direct children of z-harness/
        for plan_dir in harness_dir.iterdir():
            if not plan_dir.is_dir():
                continue
            archive_dir = plan_dir / "archive" / verified_by_run
            if archive_dir.is_dir():
                found_run = True
                break
        # Canonical layout: iterate children of z-harness/plans/ (if it exists)
        if not found_run:
            plans_dir = harness_dir / "plans"
            if plans_dir.is_dir():
                for plan_dir in plans_dir.iterdir():
                    if not plan_dir.is_dir():
                        continue
                    archive_dir = plan_dir / "archive" / verified_by_run
                    if archive_dir.is_dir():
                        found_run = True
                        break
    if not found_run:
        return _fail(
            8,
            f"verified_by_run {verified_by_run!r} is not a valid run id — "
            f"no directory found at z-harness/<plan>/archive/{verified_by_run}/ "
            f"or z-harness/plans/<plan>/archive/{verified_by_run}/",
        )

    # ── Check 9: diff_artifact_path touches at least one cited_path ────────────
    cited_paths = entry.get("cited_paths", [])
    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")

    # Extract touched paths from unified diff:
    # New files: "+++ b/<path>"
    # Modified/deleted: "--- a/<path>" and "+++ b/<path>"
    # Also handle "--- /dev/null" (new file uses "+++ b/..." only for the path)
    touched_paths: set[str] = set()

    for m in re.finditer(r'^\+\+\+ b/(.+)$', diff_text, re.MULTILINE):
        touched_paths.add(m.group(1))
    for m in re.finditer(r'^--- a/(.+)$', diff_text, re.MULTILINE):
        touched_paths.add(m.group(1))

    # Normalize: remove a leading "./" prefix if present.
    # Using removeprefix (or explicit startswith check) rather than lstrip("./")
    # because lstrip strips *characters* in any order — lstrip("./") on ".github"
    # produces "github" (wrong), while removeprefix("./") produces ".github" (correct).
    def _strip_dot_slash(s: str) -> str:
        return s[2:] if s.startswith("./") else s

    touched_paths = {_strip_dot_slash(p) for p in touched_paths}
    cited_normalized = {_strip_dot_slash(cp) for cp in cited_paths if isinstance(cp, str)}

    # Spec requires "at least one path in cited_paths" to be touched.
    # An empty cited_paths means no path can possibly be touched → reject.
    if not cited_normalized or not (touched_paths & cited_normalized):
        return _fail(
            9,
            f"diff_artifact_path does not touch any of cited_paths {cited_paths!r}; "
            f"diff touches: {sorted(touched_paths)!r}",
        )

    # ── Check 10: verdict file contents reference entry_id OR recommended_command
    verdict_text = verdict_path.read_text(encoding="utf-8", errors="replace")
    recommended_command = entry.get("recommended_command", "")

    entry_id_in_verdict = entry_id is not None and entry_id in verdict_text
    cmd_in_verdict = recommended_command and recommended_command in verdict_text

    if not (entry_id_in_verdict or cmd_in_verdict):
        return _fail(
            10,
            f"review_verdict_path does not reference entry_id {entry_id!r} "
            f"or recommended_command {recommended_command!r}",
        )

    # ── Check 11: trust-root — audit_evidence.json must be under
    #    z-harness/<plan>/archive/<RUN>/audit_evidence/<entry-id>/ ──────────────
    #
    # The path (after resolving to absolute) must match:
    #   <repo_root>/z-harness/<plan>/archive/<RUN>/audit_evidence/<entry-id>/<filename>
    #
    ev_abs = ev_path.resolve()
    repo_abs = Path(repo_root).resolve()

    # Relative from repo root
    try:
        ev_rel = ev_abs.relative_to(repo_abs)
    except ValueError:
        return _fail(
            11,
            f"audit_evidence.json is not under repo root {repo_root!r}: {ev_abs}",
        )

    ev_parts = ev_rel.parts
    # Two accepted trust-root layouts:
    #
    # Legacy (7 parts):
    #   z-harness / <plan> / archive / <RUN> / audit_evidence / <entry-id> / audit_evidence.json
    #   indices: 0         1          2         3                4              5              6
    #
    # Canonical (8 parts):
    #   z-harness / plans / <plan> / archive / <RUN> / audit_evidence / <entry-id> / audit_evidence.json
    #   indices: 0          1        2          3        4               5              6              7
    valid_trust_root_legacy = (
        len(ev_parts) == 7
        and ev_parts[0] == "z-harness"
        and ev_parts[2] == "archive"
        and ev_parts[3] == verified_by_run
        and ev_parts[4] == "audit_evidence"
        and ev_parts[5] == entry_id
        and ev_parts[6] == "audit_evidence.json"
    )
    valid_trust_root_canonical = (
        len(ev_parts) == 8
        and ev_parts[0] == "z-harness"
        and ev_parts[1] == "plans"
        and ev_parts[3] == "archive"
        and ev_parts[4] == verified_by_run
        and ev_parts[5] == "audit_evidence"
        and ev_parts[6] == entry_id
        and ev_parts[7] == "audit_evidence.json"
    )

    if not (valid_trust_root_legacy or valid_trust_root_canonical):
        return _fail(
            11,
            f"audit_evidence.json path {str(ev_rel)!r} is not under "
            f"z-harness/<plan>/archive/<RUN>/audit_evidence/<entry-id>/audit_evidence.json "
            f"or z-harness/plans/<plan>/archive/<RUN>/audit_evidence/<entry-id>/audit_evidence.json "
            f"(trust-root check failed; expected RUN={verified_by_run!r}, entry-id={entry_id!r})",
        )

    return _pass()


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: sink-audit-validate.py <audit_evidence.json> <entry.json> [<repo_root>]",
            file=sys.stderr,
        )
        return 2

    evidence_path = sys.argv[1]
    entry_path = sys.argv[2]

    if len(sys.argv) >= 4:
        repo_root = sys.argv[3]
    else:
        try:
            repo_root = _git_root_from_cmd()
        except RuntimeError as exc:
            result = _fail(1, str(exc))
            print(json.dumps(result))
            return 1

    result = validate(evidence_path, entry_path, repo_root)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
