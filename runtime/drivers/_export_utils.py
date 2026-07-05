"""
runtime/drivers/_export_utils.py

Shared helpers for the multi-IDE export pipeline.  Strict port of
``scripts/export-common.py``; no behavior changes vs the legacy module.
Any quirk preserved from the legacy script is noted with a
``# preserved quirk:`` comment.

Release-surface filtering imports the neutral ``runtime.release_surface``
contract shared by CLI and runtime consumers.

Public surface
--------------
enumerate_sources(repo_root) -> dict
inline_includes(text, base_dir, repo_root) -> str
    Fragment-include marker expansion.  ``base_dir`` is accepted for API
    symmetry with SPEC callers but unused — path resolution is always relative
    to ``repo_root``.  ``expand_includes`` is kept as an alias for the legacy
    call signature used by the self-test cases.
validate_capabilities(path) -> list[str]
output_path_for(repo_root, target, kind, id) -> Path
run_self_test(repo_root=None) -> int

ExportResult
    Canonical export result dataclass (BLOCKER-1).  Owned here so
    ``runtime/drivers/<t>/export.py`` never imports up into ``z_harness_cli``.
    ``z_harness_cli/adapters/base.py`` re-exports / wraps this type.

Strategy helpers (T010)
-----------------------
_ALWAYS_ON_AGENTS
    Frozenset of agent IDs that receive ``trigger: always_on`` in Antigravity.
    Single source of truth — ``runtime/drivers/antigravity/export.py`` imports
    this constant back from here.

select_sources(strategy, sources, *, pointer_doc=None) -> dict
    Pure helper: given a strategy + enumerated sources dict, returns the subset
    dict to emit.  ``pointer`` → one-entry dict with a pointer doc;
    ``curated`` → agents filtered to ``_ALWAYS_ON_AGENTS``; ``full`` → all.

resolve_strategy(default_strategy, repo_root=None) -> str
    Read ``export.strategy`` from ``config.py get`` (subprocess), falling back
    to *default_strategy* when the config read fails or returns nothing.
    Pure/injectable for testing via the *repo_root* argument.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime import release_surface


# ---------------------------------------------------------------------------
# ExportResult — canonical result type owned by runtime (BLOCKER-1)
# ---------------------------------------------------------------------------

@dataclass
class ExportResult:
    """Result of a single export operation.

    Fields
    ------
    dest:
        Absolute path to the export destination directory.
    files:
        Absolute paths of every file written during the export.
    fidelity:
        Qualitative fidelity label, e.g. ``"flattened"``, ``"high"``.
    warnings:
        Human-readable strings describing any non-fatal issues encountered.
    """

    dest: Path
    files: list[Path] = field(default_factory=list)
    fidelity: str = "flattened"
    warnings: list[str] = field(default_factory=list)


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
# preserved quirk: open/close toggle does not enforce char/length matching
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

    This is the internal workhorse; ``inline_includes`` is the public alias
    with the extended signature required by SPEC callers.
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


def inline_includes(
    text: str,
    base_dir: Path | None,
    repo_root: Path,
    *,
    _visited: frozenset[Path] | None = None,
) -> str:
    """Public alias for ``expand_includes`` with an extended SPEC-compatible signature.

    The *base_dir* argument is accepted for API symmetry with SPEC call sites
    (T003–T006 use ``inline_includes(body, base_dir, repo_root)``) but is not
    used for path resolution — all includes are resolved relative to *repo_root*,
    exactly as the legacy ``expand_includes`` does.

    # preserved quirk: base_dir accepted but unused; resolution is always
    # relative to repo_root (matching legacy export-common.py behaviour)
    """
    return expand_includes(text, repo_root, _visited=_visited)


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


def _is_prod_visible(kind: str, entry_id: str) -> bool:
    return release_surface.is_prod_visible(kind, entry_id, "prod")


def _apply_release_surface(
    sources: dict[str, list[dict[str, Any]]],
    surface: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Filter sources through the central release-surface manifest."""
    try:
        resolved = release_surface.default_surface(surface)
    except ValueError:
        resolved = "prod"
    if resolved == "dev":
        return sources

    return {
        kind: [
            entry
            for entry in entries
            if _is_prod_visible(kind, entry["id"])
        ]
        for kind, entries in sources.items()
    }


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
    sources = {
        "commands": _collect_entries(repo_root / "commands", repo_root),
        "agents": _collect_entries(repo_root / "agents", repo_root),
        "skills": _collect_skills(repo_root / "skills", repo_root),
    }
    return _apply_release_surface(sources)


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
        "skills": ".cursor/skills/{id}/SKILL.md",
    },
    "codex": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "skills/{id}/SKILL.md",
    },
    # NOTE: "agy" is intentionally absent. The antigravity exporter
    # does NOT use output_path_for — it owns its own dual layout
    # (native .agent/{workflows,rules,skills}/ AND flat prompts/),
    # which a single output_path_for return value cannot express. Adding an
    # "agy" entry here would be dead and misleading. Only codex/cursor route
    # through output_path_for.
    # preserved quirk: agy absent from _TARGET_CONVENTIONS; matches legacy export-common.py
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

        - cursor agents/commands → ``exports/cursor/.cursor/rules/<id>.mdc``
        - cursor skills → ``exports/cursor/.cursor/skills/<id>/SKILL.md``
        - codex agents/commands → ``exports/codex/prompts/<id>.md``
        - codex skills → ``exports/codex/skills/<id>/SKILL.md``

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


# ---------------------------------------------------------------------------
# Strategy helpers (T010)
# ---------------------------------------------------------------------------

#: Agent IDs that receive ``trigger: always_on`` in Antigravity.
#:
#: This set is the single source of truth.  ``runtime/drivers/antigravity/export.py``
#: imports it from here so both files stay in sync automatically.
#: Preserved exactly from the legacy ``scripts/export-agy.py``.
_ALWAYS_ON_AGENTS: frozenset[str] = frozenset(
    {
        "implementer",
        "reviewer",
        "auditor",
        "mr-reviewer",
        "remote-runner",
    }
)

#: Valid strategy names (mirrors ``export.strategy`` allowed set in config.py).
_VALID_STRATEGIES: frozenset[str] = frozenset({"pointer", "curated", "full"})

#: Sentinel entry used by the ``pointer`` strategy.  It represents a single
#: capabilities-pointer doc emitted in place of all real sources.
_POINTER_ENTRY: dict[str, Any] = {
    "id": "z-harness-pointer",
    "source_path": None,
    "frontmatter": {
        "description": "z-harness capabilities pointer — see CAPABILITIES.md for the full feature set",
    },
    "body": (
        "# z-harness — Capabilities Pointer\n\n"
        "This IDE has been configured with the z-harness *pointer* export strategy.\n"
        "Only this single rule file is emitted.\n\n"
        "See `CAPABILITIES.md` for the full list of commands, agents, and skills\n"
        "available when a host supports on-demand inclusion.\n"
    ),
}


def select_sources(
    strategy: str,
    sources: dict[str, list[dict[str, Any]]],
    *,
    pointer_doc: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return the subset of *sources* to emit based on *strategy*.

    Parameters
    ----------
    strategy:
        One of ``"pointer"``, ``"curated"``, or ``"full"``.
    sources:
        The full enumerated source dict (keys: ``commands``, ``agents``,
        ``skills``) as returned by :func:`enumerate_sources`.
    pointer_doc:
        Optional override for the pointer entry emitted by the ``pointer``
        strategy.  Defaults to :data:`_POINTER_ENTRY`.

    Returns
    -------
    dict
        A new dict with the same key structure as *sources* but containing
        only the entries that the chosen strategy selects:

        - ``pointer`` — one entry in ``agents`` (the pointer doc); ``commands``
          and ``skills`` are empty.
        - ``curated``  — ``agents`` filtered to :data:`_ALWAYS_ON_AGENTS`;
          ``commands`` and ``skills`` passed through as-is.
        - ``full``     — *sources* returned unchanged.

    Raises
    ------
    ValueError
        When *strategy* is not one of the three recognised values.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"Unknown strategy {strategy!r}. Valid strategies: {sorted(_VALID_STRATEGIES)}"
        )

    if strategy == "full":
        return {
            "commands": list(sources.get("commands", [])),
            "agents":   list(sources.get("agents", [])),
            "skills":   list(sources.get("skills", [])),
        }

    if strategy == "curated":
        curated_agents = [
            entry for entry in sources.get("agents", [])
            if entry["id"] in _ALWAYS_ON_AGENTS
        ]
        return {
            "commands": list(sources.get("commands", [])),
            "agents":   curated_agents,
            "skills":   list(sources.get("skills", [])),
        }

    # strategy == "pointer"
    doc = pointer_doc if pointer_doc is not None else _POINTER_ENTRY
    return {
        "commands": [],
        "agents":   [doc],
        "skills":   [],
    }


def resolve_strategy(
    default_strategy: str,
    repo_root: Path | str | None = None,
) -> str:
    """Return the effective export strategy.

    Calls ``python3 scripts/config.py get export.strategy`` (subprocess) and
    returns the result.  Falls back to *default_strategy* when:

    - *repo_root* is ``None`` or ``scripts/config.py`` does not exist there,
    - the subprocess exits non-zero (config key absent / not set),
    - the returned value is empty or not a recognised strategy.

    Parameters
    ----------
    default_strategy:
        Per-driver fallback.  Used when the config read produces no value.
        Must be one of ``"pointer"``, ``"curated"``, or ``"full"``.
    repo_root:
        Absolute path to the repo root that owns ``scripts/config.py``.
        Inject a different path in unit tests to avoid touching the real repo.

    Returns
    -------
    str
        The effective strategy: a member of ``{"pointer", "curated", "full"}``.
    """
    if repo_root is not None:
        config_script = Path(repo_root) / "scripts" / "config.py"
        if config_script.is_file():
            try:
                result = subprocess.run(
                    [sys.executable, str(config_script), "get", "export.strategy"],
                    capture_output=True,
                    text=True,
                    cwd=str(repo_root),
                )
                if result.returncode == 0:
                    value = result.stdout.strip()
                    if value in _VALID_STRATEGIES:
                        return value
            except OSError:
                pass

    return default_strategy



# ---------------------------------------------------------------------------
# Deterministic runtime script export helpers
# ---------------------------------------------------------------------------

_RESUME_CONTEXT_RUNTIME_FILES: tuple[str, ...] = (
    "scripts/resume-context.py",
    "scripts/artifact-scout-inventory.py",
    "scripts/active-plan-registry.py",
    "scripts/plan-path.sh",
    "scripts/session-helpers.sh",
    "scripts/config.py",
    "scripts/log-event.sh",
    "scripts/detect-host.sh",
    "scripts/intent-schema.py",
)


def export_resume_runtime_scripts(repo_root: Path | str, export_root: Path | str) -> list[Path]:
    """Copy the deterministic ``/z-resume`` runtime scripts into an export root.

    Host exports can render the ``z-resume`` skill text without having a live
    checkout beside the exported files.  Keep the script root layout stable
    (``scripts/...``) so the skill can invoke ``scripts/resume-context.py`` and
    that script's bounded helper dependencies from the installed plugin/export.
    Fixture repos that do not carry ``scripts/resume-context.py`` are left
    unchanged so generic exporter tests stay minimal.
    """
    import shutil

    repo_root = Path(repo_root).resolve()
    export_root = Path(export_root).resolve()
    if not (repo_root / "scripts" / "resume-context.py").is_file():
        return []

    emitted: list[Path] = []
    for rel_path in _RESUME_CONTEXT_RUNTIME_FILES:
        src = repo_root / rel_path
        if not src.is_file():
            continue
        dst = export_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        emitted.append(dst)
    return emitted


# ---------------------------------------------------------------------------
# Self-test (ported verbatim from scripts/export-common.py cmd_self_test)
# ---------------------------------------------------------------------------

_RUN_BRIEF_FRAGMENT = "_fragments/run-brief-finalize.md"
_RUN_BRIEF_MARKER = f"<!-- include: {_RUN_BRIEF_FRAGMENT} -->"
_RUN_BRIEF_SENTINEL = "## Run Brief finalize (shared fragment)"


def _self_test_pass(label: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(f"PASS [{label}]{suffix}")


def _self_test_fail(label: str, message: str) -> None:
    import sys

    print(f"FAIL [{label}]: {message}", file=sys.stderr)



# ---------------------------------------------------------------------------
# Unsupported runtime-call rewriting for non-native exports
# ---------------------------------------------------------------------------

_UNSUPPORTED_CALL_START_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<name>Agent|Skill|AskUserQuestion|TaskCreate|SubagentCreate|EnterPlanMode|ExitPlanMode)\s*\("
)


def _paren_delta(line: str) -> int:
    """Return a conservative parenthesis balance delta for a source-ish line.

    Export prompt bodies are Markdown, not Python syntax trees. A lightweight
    scanner is enough here: it avoids counting parentheses inside quoted strings
    and lets renderers replace an entire multi-line ``Agent(...)`` block instead
    of only the opening line. HTML ``RUNTIME-GATE`` comments are preserved because
    this helper only triggers on lines whose first non-space token is the call.
    """
    delta = 0
    quote = ""
    escaped = False
    for ch in line:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "(":
            delta += 1
        elif ch == ")":
            delta -= 1
    return delta


def rewrite_unsupported_call_blocks(
    body: str,
    replacement_for_block: Any,
) -> str:
    """Replace whole unsupported runtime call blocks in exported prompt bodies.

    ``replacement_for_block`` receives the full matched block text and returns a
    replacement line without a trailing newline. The helper preserves leading
    indentation from the call line and consumes balanced multi-line call blocks,
    preventing orphaned ``subagent_type=`` / ``prompt=`` arguments in exports.
    Prose mentions and HTML ``RUNTIME-GATE`` comments are left untouched because
    only lines starting with the call token are matched.
    """
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n\r")
        match = _UNSUPPORTED_CALL_START_RE.match(stripped)
        if not match:
            out.append(line)
            i += 1
            continue

        block_lines = [line]
        balance = _paren_delta(stripped)
        i += 1
        while balance > 0 and i < len(lines):
            block_lines.append(lines[i])
            balance += _paren_delta(lines[i].rstrip("\n\r"))
            i += 1

        replacement = replacement_for_block("".join(block_lines))
        out.append(match.group("indent") + replacement + "\n")

    return "".join(out)

def run_self_test(repo_root: Path | None = None) -> int:
    """Verify fragment include expansion against the run-brief finalize marker.

    Ported verbatim from ``scripts/export-common.py::cmd_self_test``.
    The legacy entry point is aliased as ``cmd_self_test`` for compatibility
    with any callers that used the old name.
    """
    import shutil
    import sys
    import tempfile

    # preserved quirk: when repo_root is None, fall back to __file__'s parent.parent
    # (in scripts/ the file was two levels down; in runtime/drivers/ __file__
    # would point to the wrong location if used the same way, so callers should
    # pass repo_root explicitly)
    repo_root = (repo_root or Path(__file__).resolve().parent.parent.parent).resolve()
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
            "<!-- include: _fragments/does-not-exist.md -->\n",
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
    # unique name under _fragments/, avoiding a fixed-name collision
    # between concurrent self-test runs.
    fragments_dir = repo_root / "_fragments"
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


# Legacy alias so callers of the old scripts/export-common.py name still work.
cmd_self_test = run_self_test
