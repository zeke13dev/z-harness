#!/usr/bin/env python3
"""Materialize the canonical positive release tree from explicit inputs."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.drivers._export_utils import _next_include_match, expand_includes
from runtime.drivers.codex.export import _render_plugin_manifest
from z_harness_cli.release import parse_release_candidate
from z_harness_cli import release_surface


_PATH_INVENTORY_KINDS = (
    "scripts_backends",
    "schemas",
    "public_documents",
    "generated_requirements",
)
_WHEEL_FORCE_INCLUDE = 'force-include = { '
_STAGED_WHEEL_FORCE_INCLUDE = 'force-include = { ".codex-plugin" = ".codex-plugin", '
_INCLUDE_MARKER_RE = re.compile(r"<!--\s*include:")


def _required_release_paths(contract: Mapping[str, Any]) -> tuple[str, ...]:
    inventory = contract["prod_inventory"]
    paths = [f"skills/{skill_id}/SKILL.md" for skill_id in inventory["skills"]]
    paths.extend(f"agents/{agent_id}.md" for agent_id in inventory["agents"])
    for kind in _PATH_INVENTORY_KINDS:
        paths.extend(inventory[kind])

    required = tuple(sorted(set(paths)))
    unclassified = [path for path in required if release_surface.prod_owner_for_path(path) is None]
    if unclassified:
        raise ValueError(f"prod inventory contains unclassified required path: {unclassified[0]}")
    return required


def _generation_input_paths(contract: Mapping[str, Any]) -> tuple[str, ...]:
    paths = tuple(sorted(set(contract.get("generation_inputs", ()))))
    invalid = [path for path in paths if not path.startswith("_fragments/")]
    if invalid:
        raise ValueError(f"invalid release generation input: {invalid[0]}")
    return paths


def _tracked_paths(repo_root: Path) -> set[str] | None:
    top_level = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != repo_root:
        return None
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return {path.decode() for path in result.stdout.split(b"\0") if path}


def _normalize_stage_metadata(stage_root: Path) -> None:
    """Remove ambient checkout metadata while retaining tracked executable bits."""
    for path in sorted(stage_root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o755)
        else:
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
        os.utime(path, ns=(0, 0), follow_symlinks=False)
    stage_root.chmod(0o755)
    os.utime(stage_root, ns=(0, 0))


def _configure_staged_wheel(stage_root: Path) -> None:
    """Make generated Codex metadata mandatory only inside the canonical stage."""
    pyproject_path = stage_root / "pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    if pyproject.count(_WHEEL_FORCE_INCLUDE) != 1:
        raise ValueError("pyproject wheel force-include marker is missing or ambiguous")
    pyproject_path.write_text(
        pyproject.replace(_WHEEL_FORCE_INCLUDE, _STAGED_WHEEL_FORCE_INCLUDE),
        encoding="utf-8",
    )


def _validate_include_graph(
    body: str,
    repo_root: Path,
    *,
    allowed: frozenset[str],
    tracked: set[str] | None,
    stack: tuple[str, ...] = (),
) -> None:
    """Validate every active include before the shared expander reads it."""
    remaining = body
    while match := _next_include_match(remaining):
        relative = match.group(1)
        if relative not in allowed:
            raise ValueError(f"undeclared release include: {relative}")
        if tracked is not None and relative not in tracked:
            raise ValueError(f"release generation input is not tracked: {relative}")
        if relative in stack:
            chain = " -> ".join((*stack, relative))
            raise ValueError(f"circular release include: {chain}")

        source = repo_root / relative
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"missing release generation input: {relative}")
        _validate_include_graph(
            source.read_text(encoding="utf-8"),
            repo_root,
            allowed=allowed,
            tracked=tracked,
            stack=(*stack, relative),
        )
        remaining = remaining[: match.start()] + remaining[match.end() :]


def _render_staged_skill(
    source: Path,
    repo_root: Path,
    *,
    allowed: frozenset[str],
    tracked: set[str] | None,
) -> str:
    """Expand declared fragments and remove inert marker spellings from output."""
    body = source.read_text(encoding="utf-8")
    _validate_include_graph(body, repo_root, allowed=allowed, tracked=tracked)
    rendered = expand_includes(body, repo_root)
    if _next_include_match(rendered) is not None:
        raise ValueError(
            f"unresolved include marker in staged skill: {source.relative_to(repo_root)}"
        )
    return _INCLUDE_MARKER_RE.sub("&lt;!-- include:", rendered)


def stage_release_surface(
    repo_root: Path,
    dest: Path,
    *,
    candidate_version: str,
    candidate_commit: str,
) -> Path:
    """Copy the tracked positive inventory and generate candidate metadata."""
    repo_root = repo_root.resolve()
    dest = dest.resolve()
    if dest == repo_root or repo_root in dest.parents:
        raise ValueError("release staging destination must be outside the source tree")
    if not candidate_version or not candidate_commit:
        raise ValueError("candidate version and commit are required")
    candidate = parse_release_candidate(candidate_version)

    contract = release_surface.release_contract()
    required = _required_release_paths(contract)
    generation_inputs = _generation_input_paths(contract)
    allowed_generation_inputs = frozenset(generation_inputs)
    tracked = _tracked_paths(repo_root)
    if tracked is not None:
        untracked = [
            path for path in (*required, *generation_inputs) if path not in tracked
        ]
        if untracked:
            raise ValueError(f"required release input is not tracked: {untracked[0]}")

    sources = [(path, repo_root / path) for path in required]
    generation_sources = [(path, repo_root / path) for path in generation_inputs]
    for relative, source in (*sources, *generation_sources):
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"missing required release input: {relative}")

    if dest.exists():
        shutil.rmtree(dest)
    for relative, source in sources:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.startswith("skills/"):
            target.write_text(
                _render_staged_skill(
                    source,
                    repo_root,
                    allowed=allowed_generation_inputs,
                    tracked=tracked,
                ),
                encoding="utf-8",
            )
        else:
            shutil.copyfile(source, target)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)

    (dest / "VERSION").write_text(candidate.plugin_version + "\n", encoding="utf-8")
    manifest_path = dest / ".codex-plugin" / "plugin.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        _render_plugin_manifest(
            candidate_version=candidate.plugin_version,
            candidate_commit=candidate_commit,
        ),
        encoding="utf-8",
    )
    _configure_staged_wheel(dest)
    _normalize_stage_metadata(dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--candidate-commit", required=True)
    args = parser.parse_args(argv)
    staged = stage_release_surface(
        args.repo_root,
        args.out,
        candidate_version=args.candidate_version,
        candidate_commit=args.candidate_commit,
    )
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
