# DEPRECATED: frozen at v0.1.0. Remove after v0.2.0. See C6-D1.
"""
export-common.py — shared helpers for the multi-IDE export pipeline.

Importable by export-cursor.py, export-codex.py, export-agy.py, and any
other per-target adapter. Stdlib only; no third-party deps.

Public surface:
  enumerate_sources(repo_root) -> dict
  expand_includes(body, repo_root) -> str
  validate_capabilities(path) -> list[str]
  output_path_for(repo_root, target, kind, id) -> Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _unquote_scalar(value: str) -> str:
    """Strip matching surrounding YAML quotes from a flat scalar value.

    Source frontmatter quotes ``description``/``argument-hint`` values that
    contain YAML-significant characters (``:``, ``[``).  Downstream emitters
    want the bare string, so undo the quoting here.  Handles the common escape
    forms: ``\\"`` / ``\\\\`` in double quotes, ``''`` in single quotes.
    """
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-fenced frontmatter at the top of *text*.

    Returns (frontmatter_dict, body_text).  Only simple ``key: value`` pairs
    are handled — no nested structures, sequences, or multi-line values.  This
    is intentional: the source files in this repo only use flat frontmatter.
    """
    frontmatter: dict[str, str] = {}
    body = text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return frontmatter, body

    end_fence = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            end_fence = i
            break

    if end_fence == -1:
        return frontmatter, body

    for line in lines[1:end_fence]:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*(.*)', stripped)
        if match:
            frontmatter[match.group(1)] = _unquote_scalar(match.group(2).strip())

    body = "".join(lines[end_fence + 1:])
    return frontmatter, body


# ---------------------------------------------------------------------------
# Fragment include expansion
# ---------------------------------------------------------------------------

_INCLUDE_LINE_RE = re.compile(
    r"^[ \t]*<!--\s*include:\s*([^\s]+)\s*-->[ \t]*(?:\n|$)",
    re.MULTILINE,
)
# CommonMark fenced code blocks open/close with 3+ backticks OR 3+ tildes.
# (The naive open/close toggle below does not enforce that a closing fence
# matches the opening run's char/length — sufficient for our doc content, which
# never interleaves backtick and tilde fences.)
_FENCE_LINE_RE = re.compile(r"^(?:`{3,}|~{3,}).*$", re.MULTILINE)


def _fence_regions(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans for content inside fenced code blocks."""
    regions: list[tuple[int, int]] = []
    in_fence = False
    fence_content_start = 0
    for match in _FENCE_LINE_RE.finditer(text):
        if not in_fence:
            in_fence = True
            fence_content_start = match.end()
        else:
            regions.append((fence_content_start, match.start()))
            in_fence = False
    if in_fence:
        regions.append((fence_content_start, len(text)))
    return regions


def _position_in_fence(pos: int, regions: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in regions)


def _next_include_match(text: str) -> re.Match[str] | None:
    """Return the first include marker not inside a fenced code block."""
    regions = _fence_regions(text)
    for match in _INCLUDE_LINE_RE.finditer(text):
        if not _position_in_fence(match.start(), regions):
            return match
    return None


def expand_includes(
    body: str,
    repo_root: Path,
    *,
    _visited: frozenset[Path] | None = None,
) -> str:
    """Inline ``<!-- include: <repo-relative-path> -->`` markers with file bodies.

    Only markers that occupy a whole line are expanded (so documentation lines
    that mention the marker inside backticks are left alone).  Markers inside
    fenced code blocks (`` ``` ``) are also skipped.  Paths are resolved
    relative to *repo_root*.  Nested includes in fragment files are expanded
    recursively.  Raises ``FileNotFoundError`` when a referenced fragment is
    missing, ``ValueError`` when a path escapes *repo_root* or when a circular
    include is detected.
    """
    repo_root = Path(repo_root).resolve()
    visited = _visited or frozenset()
    expanded = body

    while True:
        match = _next_include_match(expanded)
        if not match:
            break

        rel_path = match.group(1)
        fragment_path = (repo_root / rel_path).resolve()

        try:
            fragment_path.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"Include path {rel_path!r} escapes repo root {repo_root}"
            ) from exc

        if fragment_path in visited:
            chain = " -> ".join(
                str(path.relative_to(repo_root)) for path in visited
            )
            raise ValueError(
                f"Circular include detected: {chain} -> {rel_path}"
            )

        if not fragment_path.is_file():
            raise FileNotFoundError(
                f"Include fragment not found: {rel_path} "
                f"(resolved to {fragment_path})"
            )

        fragment_body = fragment_path.read_text(encoding="utf-8")
        nested_body = expand_includes(
            fragment_body,
            repo_root,
            _visited=visited | frozenset({fragment_path}),
        )
        expanded = expanded[: match.start()] + nested_body + expanded[match.end() :]

    return expanded


# ---------------------------------------------------------------------------
# Source enumeration
# ---------------------------------------------------------------------------

def _collect_entries(directory: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Return one entry dict per markdown file in *directory* (non-recursive)."""
    if not directory.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        body = expand_includes(body, repo_root)
        entries.append(
            {
                "id": path.stem,
                "source_path": path,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def _collect_skills(skills_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Return one entry per skill (each skill lives in its own sub-directory
    as ``skills/<name>/SKILL.md``)."""
    if not skills_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        body = expand_includes(body, repo_root)
        entries.append(
            {
                "id": skill_dir.name,
                "source_path": skill_file,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def enumerate_sources(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return a dict with keys ``commands``, ``agents``, ``skills``.

    Each value is a list of entry dicts::

        {
            "id": str,                      # stem of the source file / skill dir name
            "source_path": pathlib.Path,    # absolute path to the source file
            "frontmatter": dict[str, str],  # parsed key/value pairs (flat)
            "body": str,                    # markdown body after the frontmatter fence
        }
    """
    repo_root = Path(repo_root).resolve()
    return {
        "commands": _collect_entries(repo_root / "commands", repo_root),
        "agents": _collect_entries(repo_root / "agents", repo_root),
        "skills": _collect_skills(repo_root / "skills", repo_root),
    }


# ---------------------------------------------------------------------------
# CAPABILITIES.md schema validation
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = ("## Supported", "## Unsupported", "## Notes")


def validate_capabilities(path: Path) -> list[str]:
    """Validate that *path* is a CAPABILITIES.md file conforming to the
    minimal schema.

    Required sections: ``## Supported``, ``## Unsupported``, ``## Notes``.

    Returns a list of validation error strings.  An empty list means the file
    is valid.
    """
    errors: list[str] = []
    path = Path(path)

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    text = path.read_text(encoding="utf-8")
    for section in _REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"Missing required section: {section!r}")

    return errors


# ---------------------------------------------------------------------------
# Per-target output path computation
# ---------------------------------------------------------------------------

_TARGET_CONVENTIONS: dict[str, dict[str, str]] = {
    "cursor": {
        "commands": ".cursor/rules/{id}.mdc",
        "agents": ".cursor/rules/{id}.mdc",
        "skills": ".cursor/rules/{id}.mdc",
    },
    "codex": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "prompts/{id}.md",
    },
    # NOTE: "agy" is intentionally absent. The antigravity exporter
    # (scripts/export-agy.py) does NOT use output_path_for — it owns its own
    # dual layout (native .agent/{workflows,rules,skills}/ AND flat prompts/),
    # which a single output_path_for return value cannot express. Adding an
    # "agy" entry here would be dead and misleading. Only codex/cursor route
    # through output_path_for.
}


def output_path_for(repo_root: Path, target: str, kind: str, id: str) -> Path:
    """Return the conventional output path for a given export target.

    Args:
        repo_root: Absolute path to the repository root.
        target: Export target name — one of ``cursor``, ``codex``. The ``agy``
            target is NOT handled here; export-agy.py owns its own dual layout.
        kind: Source kind — one of ``commands``, ``agents``, ``skills``.
        id: Source identifier (file stem / skill dir name).

    Returns:
        An absolute Path inside ``exports/<target>/`` following the per-target
        convention:

        - cursor → ``exports/cursor/.cursor/rules/<id>.mdc``
        - codex  → ``exports/codex/prompts/<id>.md``

    Raises:
        ValueError: if *target* or *kind* is not recognised.
    """
    repo_root = Path(repo_root).resolve()

    if target not in _TARGET_CONVENTIONS:
        raise ValueError(
            f"Unknown target {target!r}. Valid targets: {sorted(_TARGET_CONVENTIONS)}"
        )
    kind_map = _TARGET_CONVENTIONS[target]
    if kind not in kind_map:
        raise ValueError(
            f"Unknown kind {kind!r}. Valid kinds: {sorted(kind_map)}"
        )

    relative = kind_map[kind].format(id=id)
    return repo_root / "exports" / target / relative


_RUN_BRIEF_FRAGMENT = "commands/_fragments/run-brief-finalize.md"
_RUN_BRIEF_MARKER = f"<!-- include: {_RUN_BRIEF_FRAGMENT} -->"
_RUN_BRIEF_SENTINEL = "## Run Brief finalize (shared fragment)"


def _self_test_pass(label: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(f"PASS [{label}]{suffix}")


def _self_test_fail(label: str, message: str) -> None:
    import sys

    print(f"FAIL [{label}]: {message}", file=sys.stderr)


def cmd_self_test(repo_root: Path | None = None) -> int:
    """Verify fragment include expansion against the run-brief finalize marker."""
    import shutil
    import sys
    import tempfile

    repo_root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
    overall_pass = True

    def record_pass(label: str, detail: str = "") -> None:
        _self_test_pass(label, detail)

    def record_fail(label: str, message: str) -> None:
        nonlocal overall_pass
        overall_pass = False
        _self_test_fail(label, message)

    def expect_raises(label: str, exc_type: type[BaseException], fn) -> None:
        try:
            fn()
        except exc_type as exc:
            record_pass(label, str(exc))
        except Exception as exc:
            record_fail(
                label,
                f"expected {exc_type.__name__}, got {type(exc).__name__}: {exc}",
            )
        else:
            record_fail(label, f"expected {exc_type.__name__}, no exception raised")

    sample = f"Before marker\n{_RUN_BRIEF_MARKER}\nAfter marker\n"
    try:
        expanded = expand_includes(sample, repo_root)
    except (FileNotFoundError, ValueError) as exc:
        record_fail("run-brief-include", f"expand_includes raised {exc}")
        return 1

    if _next_include_match(expanded):
        record_fail(
            "run-brief-include",
            "standalone include marker still present after expansion",
        )
    elif _RUN_BRIEF_SENTINEL not in expanded:
        record_fail(
            "run-brief-include",
            f"expected sentinel {_RUN_BRIEF_SENTINEL!r} missing from expanded body",
        )
    else:
        record_pass(
            "run-brief-include",
            f"{_RUN_BRIEF_FRAGMENT} inlined at marker",
        )

    fenced_sample = f"```markdown\n{_RUN_BRIEF_MARKER}\n```\n"
    try:
        fenced_expanded = expand_includes(fenced_sample, repo_root)
    except (FileNotFoundError, ValueError) as exc:
        record_fail("fence-skipped", f"expand_includes raised {exc}")
    else:
        if _RUN_BRIEF_MARKER not in fenced_expanded:
            record_fail(
                "fence-skipped",
                "marker inside fenced code block was removed instead of preserved",
            )
        elif _RUN_BRIEF_SENTINEL in fenced_expanded:
            record_fail(
                "fence-skipped",
                "fragment body was inlined from a fenced marker",
            )
        else:
            record_pass("fence-skipped", "marker inside ``` preserved unchanged")

    expect_raises(
        "missing-fragment",
        FileNotFoundError,
        lambda: expand_includes(
            "<!-- include: commands/_fragments/does-not-exist.md -->\n",
            repo_root,
        ),
    )

    expect_raises(
        "path-escape",
        ValueError,
        lambda: expand_includes(
            "<!-- include: ../../../etc/passwd -->\n",
            repo_root,
        ),
    )

    # The cycle fixtures must live UNDER repo_root (the include guard rejects
    # paths that escape it), so a system tempdir won't do. mkdtemp gives a
    # unique name under commands/_fragments/, avoiding a fixed-name collision
    # between concurrent self-test runs.
    fragments_dir = repo_root / "commands" / "_fragments"
    cycle_dir = Path(tempfile.mkdtemp(prefix=".self-test-cycle-", dir=fragments_dir))
    cycle_a = cycle_dir / "a.md"
    cycle_b = cycle_dir / "b.md"
    cycle_rel_a = f"{cycle_dir.relative_to(repo_root).as_posix()}/a.md"
    cycle_rel_b = f"{cycle_dir.relative_to(repo_root).as_posix()}/b.md"
    try:
        cycle_a.write_text(f"<!-- include: {cycle_rel_b} -->\n", encoding="utf-8")
        cycle_b.write_text(f"<!-- include: {cycle_rel_a} -->\n", encoding="utf-8")
        expect_raises(
            "circular-include",
            ValueError,
            lambda: expand_includes(
                f"<!-- include: {cycle_rel_a} -->\n",
                repo_root,
            ),
        )
    finally:
        shutil.rmtree(cycle_dir, ignore_errors=True)

    if overall_pass:
        print("PASS: all export-common self-tests passed")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(cmd_self_test())

    print(
        "[z-harness] NOTE: export-common.py has no direct CLI action besides"
        " --self-test. The module remains the live fragment-include library"
        " imported by export-{cursor,codex,agy}.py; run /z-export to export.",
        file=sys.stderr,
    )
