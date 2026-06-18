"""
runtime/tests/test_export_golden.py

Golden-capture comparator for the multi-IDE export pipeline.

Each test checks that the runtime driver for a given target (`cursor`, `codex`,
`antigravity`, `pi`, `windsurf`, `kiro`, `cline`, `copilot`) produces output
that is equivalent to the golden snapshot stored in `fixtures/golden/<target>/`.

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

    All files under hidden directories (e.g. ``.cursor/``, ``.agent/``,
    ``.windsurf/``, ``.kiro/``, ``.clinerules/``, ``.github/``) are included —
    the golden snapshots for various hosts live under such directories.
    ``Path.rglob("*")`` matches hidden directories without any special handling.
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
    "windsurf": {
        # Windsurf rule files require frontmatter with "trigger" key
        ".windsurf/rules/*.md": ["trigger"],
    },
    "kiro": {
        # Kiro steering files require frontmatter with "inclusion" key
        ".kiro/steering/*.md": ["inclusion"],
    },
    "cline": {
        # Cline uses a single pointer file — plain markdown, no frontmatter requirement.
        # Structural check = non-empty body only (enforced globally for all files).
    },
    "copilot": {
        # Copilot uses a single instructions file — plain markdown, no frontmatter.
        # Structural check = non-empty body only (enforced globally for all files).
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
    "windsurf": "runtime.drivers.windsurf.export",
    "kiro": "runtime.drivers.kiro.export",
    "cline": "runtime.drivers.cline.export",
    "copilot": "runtime.drivers.copilot.export",
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
            f"runtime/drivers/{target}/export.py not yet implemented"
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

    def test_windsurf_snapshot_structure(self) -> None:
        """Snapshot windsurf: all .windsurf/rules/*.md files have 'trigger' frontmatter."""
        golden_dir = _GOLDEN_DIR / "windsurf"
        files = _collect_files(golden_dir)
        assert files, f"Windsurf golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("windsurf", normalized)

    def test_kiro_snapshot_structure(self) -> None:
        """Snapshot kiro: all .kiro/steering/*.md files have 'inclusion' frontmatter."""
        golden_dir = _GOLDEN_DIR / "kiro"
        files = _collect_files(golden_dir)
        assert files, f"Kiro golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("kiro", normalized)

    def test_cline_snapshot_structure(self) -> None:
        """Snapshot cline: single pointer file has non-empty body (no frontmatter required)."""
        golden_dir = _GOLDEN_DIR / "cline"
        files = _collect_files(golden_dir)
        assert files, f"Cline golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("cline", normalized)

    def test_copilot_snapshot_structure(self) -> None:
        """Snapshot copilot: single instructions file has non-empty body (no frontmatter required)."""
        golden_dir = _GOLDEN_DIR / "copilot"
        files = _collect_files(golden_dir)
        assert files, f"Copilot golden snapshot is empty: {golden_dir}"
        normalized = _normalize_snapshot(files, _REPO_ROOT)
        _run_structural_backstop("copilot", normalized)

    def test_snapshot_file_counts(self) -> None:
        """All eight golden snapshot directories have the expected file counts."""
        expected_counts = {
            # Re-baselined after the skills/ source dir was removed: commands/ is
            # now the single source, so the per-skill *-skill.* outputs are gone.
            "cursor": 86,     # .cursor/rules/*.mdc (commands + agents + z-debt)
            "codex": 57,      # prompts/*.md + AGENTS.md (commands + agents + z-debt; no personas)
            "antigravity": 175,  # .agent/workflows + .agent/rules + prompts + CAPABILITIES + README + agy-plugin.yaml + z-debt
            "pi": 93,         # agents/*.md + prompts/*.md + AGENTS.md + CAPABILITIES.md + README.md + z-debt + vendored pi_assets
            # New export-only drivers (T011–T014)
            "windsurf": 61,   # .windsurf/rules/*.md (commands + agents)
            "kiro": 61,       # .kiro/steering/*.md (commands + agents)
            "cline": 1,       # .clinerules/z-harness.md (pointer default — single file)
            "copilot": 1,     # .github/copilot-instructions.md (single pointer file)
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


class TestGoldenWindsurf:
    """windsurf runtime export matches golden snapshot (export-only driver, T011)."""

    def test_windsurf_golden(self) -> None:
        """Runtime windsurf/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="windsurf",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "windsurf",
        )


class TestGoldenKiro:
    """kiro runtime export matches golden snapshot (export-only driver, T013)."""

    def test_kiro_golden(self) -> None:
        """Runtime kiro/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="kiro",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "kiro",
        )


class TestGoldenCline:
    """cline runtime export matches golden snapshot (export-only driver, T012)."""

    def test_cline_golden(self) -> None:
        """Runtime cline/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="cline",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "cline",
        )


class TestGoldenCopilot:
    """copilot runtime export matches golden snapshot (export-only driver, T014)."""

    def test_copilot_golden(self) -> None:
        """Runtime copilot/export.py output is byte-identical to snapshot (post-norm)."""
        _assert_golden(
            target="copilot",
            repo_root=_REPO_ROOT,
            golden_dir=_GOLDEN_DIR / "copilot",
        )


# ---------------------------------------------------------------------------
# Adapter-absence validation (audit M5)
# ---------------------------------------------------------------------------

# The four new export-only drivers (windsurf, kiro, cline, copilot) must NOT
# be registered in the z_harness_cli adapter registry.  They are runtime-only
# export drivers with no HostAdapter, no launch/inject capability, and no
# command-tier registration.  This test asserts that invariant so it cannot
# be silently broken by future work.
_EXPORT_ONLY_HOSTS = ["windsurf", "kiro", "cline", "copilot"]


class TestAdapterAbsence:
    """M5 audit: export-only drivers must NOT appear in the adapter registry."""

    def test_no_adapter_registry_entries(self) -> None:
        """windsurf/kiro/cline/copilot are absent from the z_harness_cli adapter registry.

        Specifically: calling registry.select(<name>) must raise an exception
        (UnknownHostError or similar) for each of these four hosts — they are not
        registered adapters and must never be.
        """
        from z_harness_cli.adapters import registry

        for host in _EXPORT_ONLY_HOSTS:
            try:
                # select() with no installed binary — should raise UnknownHostError.
                # We pass skip_detect=True if available to bypass binary detection,
                # but even without it the host should not be found.
                result = registry.select(host)
                # If it did NOT raise, the host was found — that is a failure.
                pytest.fail(
                    f"registry.select({host!r}) returned {result!r} instead of raising; "
                    f"{host} must not be registered as an adapter"
                )
            except Exception as exc:
                # Raising is the correct outcome — the host is not a registered adapter.
                # We assert that the exception is the expected not-found kind so that
                # a spurious unrelated error (e.g. AttributeError, ImportError) does
                # NOT silently count as success.
                from z_harness_cli.adapters.registry import UnknownHostError, NoHostInstalledError
                assert isinstance(exc, (UnknownHostError, NoHostInstalledError)), (
                    f"registry.select({host!r}) raised an unexpected exception type "
                    f"{type(exc).__name__!r} (expected UnknownHostError or "
                    f"NoHostInstalledError): {exc!r}"
                )

    def test_no_adapter_modules_exist(self) -> None:
        """No adapter module exists at z_harness_cli/adapters/<host>.py for export-only hosts."""
        import importlib.util

        for host in _EXPORT_ONLY_HOSTS:
            module_name = f"z_harness_cli.adapters.{host}"
            spec = importlib.util.find_spec(module_name)
            assert spec is None, (
                f"Adapter module {module_name!r} exists but must not — "
                f"{host} is an export-only driver with no HostAdapter"
            )

    def test_z_harness_cli_does_not_hardcode_export_only_hosts(self) -> None:
        """z_harness_cli package source does not hardcode windsurf/kiro/cline/copilot.

        These names must not appear in any z_harness_cli source file (adapters, commands,
        or CLI entry points) because they are export-only and have no adapter.
        """
        import ast
        from pathlib import Path

        cli_root = _REPO_ROOT / "z_harness_cli"
        assert cli_root.is_dir(), f"z_harness_cli package not found at {cli_root}"

        violations: list[str] = []
        for py_file in sorted(cli_root.rglob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for host in _EXPORT_ONLY_HOSTS:
                # Check for string literals containing the host name using AST.
                try:
                    tree = ast.parse(source, filename=str(py_file))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        if node.value == host:
                            rel = py_file.relative_to(_REPO_ROOT)
                            violations.append(
                                f"  {rel}:{node.lineno}: literal {host!r} found"
                            )

        assert not violations, (
            "z_harness_cli hardcodes export-only host name(s):\n"
            + "\n".join(violations)
            + "\nThese hosts are export-only; remove them from z_harness_cli."
        )
