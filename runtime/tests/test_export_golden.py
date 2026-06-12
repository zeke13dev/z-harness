"""
runtime/tests/test_export_golden.py

Golden-capture comparator for the multi-IDE export pipeline.

Each test checks that the runtime driver for a given target (`cursor`, `codex`,
`antigravity`, `pi`) produces output that is equivalent to the legacy script
snapshot stored in `fixtures/golden/<target>/`.

Determinism was verified at capture time by running each legacy exporter twice
and comparing the outputs; results are documented in ``fixtures/golden/README.md``.
The legacy scripts have since been removed (T009).

Normalization
-------------
`normalize_for_comparison` replaces the repo-root absolute path with the
literal string ``<REPO>`` in file content on BOTH sides before any diff.
This makes the comparison portable across machines and checkout locations.
No additional normalization is required — all four legacy exporters were
verified deterministic (see README.md).

Wiring to future tasks
-----------------------
Each target's runtime assertion is **skipped** when the corresponding module
`runtime/drivers/<target>/export.py` does not yet exist (T003–T006 will
create them). Once a module lands, its test assertion turns green automatically.

Run with:
    python3 -m pytest runtime/tests/test_export_golden.py -v
"""

from __future__ import annotations

import importlib
import re
import tempfile
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # worktree root
_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def normalize_for_comparison(content: str, repo_root: Path) -> str:
    """Replace the absolute *repo_root* path with ``<REPO>`` in *content*.

    Applied symmetrically to both the snapshot side and the live side before
    any equality check, making the test portable across machines and checkout
    paths.
    """
    abs_str = str(repo_root.resolve())
    return content.replace(abs_str, "<REPO>")


def _collect_files(directory: Path) -> dict[str, str]:
    """Return a mapping ``{relative_path_str: file_content}`` for all files
    under *directory*, recursively.

    Hidden files (those whose path components start with ``"."`` *other than*
    `.cursor` and `.agent`) are included because the cursor golden snapshot
    lives under ``.cursor/`` and the antigravity snapshot under ``.agent/``.
    """
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = path.relative_to(directory).as_posix()
            result[rel] = path.read_text(encoding="utf-8")
    return result


def _normalize_snapshot(files: dict[str, str], repo_root: Path) -> dict[str, str]:
    """Apply ``normalize_for_comparison`` to every file in *files* mapping."""
    return {
        rel: normalize_for_comparison(content, repo_root)
        for rel, content in files.items()
    }


# ---------------------------------------------------------------------------
# Structural validation helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter_strict(text: str) -> dict | None:
    """Parse YAML frontmatter from *text* using strict PyYAML.

    Returns the parsed dict, or ``None`` if the frontmatter block is absent or
    malformed.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None


def _assert_frontmatter_valid(
    path_in_snapshot: str,
    content: str,
    required_keys: list[str],
) -> None:
    """Assert strict-YAML frontmatter is present and contains *required_keys*."""
    fm = _parse_frontmatter_strict(content)
    assert fm is not None, (
        f"{path_in_snapshot}: missing or malformed YAML frontmatter"
    )
    for key in required_keys:
        assert key in fm, (
            f"{path_in_snapshot}: frontmatter missing required key '{key}'"
        )


def _assert_body_non_empty(path_in_snapshot: str, content: str) -> None:
    """Assert the body after the frontmatter fence is non-empty."""
    m = _FRONTMATTER_RE.match(content)
    if m:
        body = content[m.end():]
    else:
        body = content
    assert body.strip(), f"{path_in_snapshot}: body is empty"


# ---------------------------------------------------------------------------
# Per-target structural rules
# ---------------------------------------------------------------------------

# For each target: {extension_glob: required_frontmatter_keys}
# Files matching the extension get their frontmatter validated.
# Files without frontmatter (e.g. plain text, YAML manifests, README) are
# checked only for non-empty body.
_TARGET_STRUCTURAL_RULES: dict[str, dict[str, list[str]]] = {
    "cursor": {
        "*.mdc": ["description", "alwaysApply"],
    },
    "codex": {
        # Codex prompt files start with "# /<id>" — no YAML frontmatter.
        # AGENTS.md also has no frontmatter.  Structural check = non-empty body only.
    },
    "antigravity": {
        # Workflow files
        ".agent/workflows/*.md": ["description"],
        # Rule files — only required key is "trigger"
        ".agent/rules/*.md": ["trigger"],
        # Skill files
        ".agent/skills/**/*.md": ["name", "description"],
        # Flat prompt files
        "prompts/*.md": ["description", "role"],
    },
    "pi": {
        # pi agent files have YAML frontmatter
        "agents/*.md": ["description"],
        # pi prompt files have no YAML frontmatter — just a "# /<id>" header.
        # Structural check = non-empty body only.
    },
}


def _matches_glob_pattern(rel_path: str, pattern: str) -> bool:
    """Return True if *rel_path* matches a simple glob-like *pattern*.

    Supports ``*`` (single-component wildcard) and ``**`` (multi-component
    wildcard), using :func:`pathlib.PurePosixPath.match`.
    """
    from pathlib import PurePosixPath
    return PurePosixPath(rel_path).match(pattern)


def _run_structural_backstop(target: str, files: dict[str, str]) -> None:
    """Run structural checks for all files in *files* for the given *target*.

    Each file is checked for:
    - Non-empty body (always).
    - YAML frontmatter present + required keys (if the file extension matches
      one of the per-target rules).
    """
    rules = _TARGET_STRUCTURAL_RULES.get(target, {})

    for rel_path, content in files.items():
        # Non-empty body for every file.
        _assert_body_non_empty(rel_path, content)

        # Frontmatter validity for files that should have it.
        for pattern, required_keys in rules.items():
            if _matches_glob_pattern(rel_path, pattern):
                _assert_frontmatter_valid(rel_path, content, required_keys)
                break


# ---------------------------------------------------------------------------
# Runtime module availability check
# ---------------------------------------------------------------------------

_TARGET_RUNTIME_MODULES = {
    "cursor": "runtime.drivers.cursor.export",
    "codex": "runtime.drivers.codex.export",
    "antigravity": "runtime.drivers.antigravity.export",
    "pi": "runtime.drivers.pi.export",
}


def _runtime_module_exists(target: str) -> bool:
    """Return True if ``runtime/drivers/<target>/export.py`` is importable."""
    module_name = _TARGET_RUNTIME_MODULES[target]
    try:
        spec = importlib.util.find_spec(module_name)
    except (ModuleNotFoundError, ValueError):
        # Parent package doesn't exist yet (e.g. runtime.drivers.pi has no
        # __init__.py).  Treat as absent.
        return False
    return spec is not None


def _skip_if_runtime_missing(target: str) -> None:
    """Skip the calling test if the runtime export module for *target* is absent."""
    if not _runtime_module_exists(target):
        pytest.skip(
            f"runtime/drivers/{target}/export.py not yet implemented "
            f"(will be created by T003–T006)"
        )


# ---------------------------------------------------------------------------
# Shared golden comparison logic
# ---------------------------------------------------------------------------


def _assert_golden(
    target: str,
    repo_root: Path,
    golden_dir: Path,
    run_runtime: bool = True,
) -> None:
    """Core assertion: runtime module output must match the golden snapshot.

    Parameters
    ----------
    target:
        Target name: one of ``cursor``, ``codex``, ``antigravity``, ``pi``.
    repo_root:
        Absolute path to the repository root (worktree root).
    golden_dir:
        Path to ``fixtures/golden/<target>/``.
    run_runtime:
        Whether to run the runtime module and compare; set to False for the
        structural-only variant.
    """
    # 1. Load the snapshot.
    assert golden_dir.is_dir(), (
        f"Golden snapshot directory not found: {golden_dir}. "
        "Run the pre-flight step to generate snapshots."
    )
    snapshot_files = _collect_files(golden_dir)
    assert snapshot_files, f"Golden snapshot for {target!r} is empty: {golden_dir}"

    # 2. Normalize snapshot.
    normalized_snapshot = _normalize_snapshot(snapshot_files, repo_root)

    # 3. Structural backstop on the snapshot itself (always runs, even without runtime).
    _run_structural_backstop(target, normalized_snapshot)

    if not run_runtime:
        return

    # 4. Skip if runtime module not yet present.
    _skip_if_runtime_missing(target)

    # 5. Import and run the runtime module.
    module_name = _TARGET_RUNTIME_MODULES[target]
    mod = importlib.import_module(module_name)
    export_fn = mod.export  # type: ignore[attr-defined]

    with tempfile.TemporaryDirectory(prefix=f"zh-golden-{target}-") as tmp_str:
        live_out = Path(tmp_str)
        result = export_fn(repo_root, live_out)

        # Sanity: result must be an ExportResult-like object.
        assert hasattr(result, "files"), (
            f"export() for {target!r} must return an ExportResult with .files"
        )
        assert hasattr(result, "dest"), (
            f"export() for {target!r} must return an ExportResult with .dest"
        )

        live_files = _collect_files(live_out)

    # 6. Normalize live output.
    normalized_live = _normalize_snapshot(live_files, repo_root)

    # 7. File-count matches.
    snapshot_count = len(normalized_snapshot)
    live_count = len(normalized_live)
    assert live_count == snapshot_count, (
        f"{target}: file count mismatch — "
        f"snapshot has {snapshot_count} files, runtime emitted {live_count}.\n"
        f"  In snapshot but not live: {sorted(set(normalized_snapshot) - set(normalized_live))}\n"
        f"  In live but not snapshot: {sorted(set(normalized_live) - set(normalized_snapshot))}"
    )

    # 8. Content equality, file by file.
    mismatches: list[str] = []
    for rel_path, snapshot_content in normalized_snapshot.items():
        if rel_path not in normalized_live:
            mismatches.append(f"  MISSING in live: {rel_path}")
            continue
        live_content = normalized_live[rel_path]
        if live_content != snapshot_content:
            # Show the first difference for diagnosis.
            snap_lines = snapshot_content.splitlines()
            live_lines = live_content.splitlines()
            diff_line = next(
                (
                    i
                    for i, (sl, ll) in enumerate(
                        zip(snap_lines, live_lines), start=1
                    )
                    if sl != ll
                ),
                None,
            )
            detail = (
                f" (first diff at line {diff_line})" if diff_line else ""
            )
            mismatches.append(f"  CONTENT MISMATCH: {rel_path}{detail}")

    assert not mismatches, (
        f"{target}: {len(mismatches)} file(s) differ from golden snapshot:\n"
        + "\n".join(mismatches)
    )

    # 9. Structural backstop on live output too.
    _run_structural_backstop(target, normalized_live)


# ---------------------------------------------------------------------------
# Golden snapshot structural tests (always run — no runtime required)
# ---------------------------------------------------------------------------


class TestGoldenSnapshotStructure:
    """Structural invariants of the captured golden snapshots.

    These run even when the runtime modules are absent. They verify that the
    snapshots themselves are well-formed (frontmatter + body). Any snapshot
    corruption would be caught here before T003–T006 even run.
    """

    def test_cursor_snapshot_structure(self) -> None:
        """Snapshot cursor: all .mdc files have valid frontmatter + non-empty body."""
        golden_dir = _GOLDEN_DIR / "cursor"
        files = _collect_files(golden_dir)
        assert files, f"Cursor golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("cursor", normalized)

    def test_codex_snapshot_structure(self) -> None:
        """Snapshot codex: all files have non-empty body."""
        golden_dir = _GOLDEN_DIR / "codex"
        files = _collect_files(golden_dir)
        assert files, f"Codex golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("codex", normalized)

    def test_antigravity_snapshot_structure(self) -> None:
        """Snapshot antigravity: workflows/rules/skills/prompts have valid frontmatter."""
        golden_dir = _GOLDEN_DIR / "antigravity"
        files = _collect_files(golden_dir)
        assert files, f"Antigravity golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("antigravity", normalized)

    def test_pi_snapshot_structure(self) -> None:
        """Snapshot pi: agent files have frontmatter; prompts have non-empty body."""
        golden_dir = _GOLDEN_DIR / "pi"
        files = _collect_files(golden_dir)
        assert files, f"Pi golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("pi", normalized)

    def test_snapshot_file_counts(self) -> None:
        """All four golden snapshot directories have the expected file counts."""
        expected_counts = {
            "cursor": 274,    # rules + agents + extensions + prompts + personas + AGENTS + CAPABILITIES + README
            "codex": 156,     # agents + extensions + prompts + personas + AGENTS + CAPABILITIES + README
            "antigravity": 126,  # agents + extensions + prompts + AGENTS + CAPABILITIES + README (z-test skill excluded)
            "pi": 126,        # agents + prompts + extensions + AGENTS.md + CAPABILITIES.md + README.md (z-test skill excluded)
        }
        for target, expected in expected_counts.items():
            golden_dir = _GOLDEN_DIR / target
            count = len(list(golden_dir.rglob("*[^/]")))
            # Count only files (not dirs)
            file_count = sum(1 for p in golden_dir.rglob("*") if p.is_file())
            assert file_count == expected, (
                f"{target}: expected {expected} snapshot files, found {file_count}"
            )


# ---------------------------------------------------------------------------
# Golden runtime comparison tests (skip when runtime module absent)
# ---------------------------------------------------------------------------


class TestGoldenCursor:
    """cursor runtime export matches legacy snapshot."""

    def test_cursor_golden(self) -> None:
        """Runtime cursor/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="cursor",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "cursor",
        )


class TestGoldenCodex:
    """codex runtime export matches legacy snapshot."""

    def test_codex_golden(self) -> None:
        """Runtime codex/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="codex",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "codex",
        )


class TestGoldenAntigravity:
    """antigravity runtime export matches legacy snapshot."""

    def test_antigravity_golden(self) -> None:
        """Runtime antigravity/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="antigravity",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "antigravity",
        )


class TestGoldenPi:
    """pi runtime export matches legacy snapshot."""

    def test_pi_golden(self) -> None:
        """Runtime pi/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="pi",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "pi",
        )
