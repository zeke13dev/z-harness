"""Blocking MCP prod tool-list smoke for release candidates.

The release workflow and dry-run invoke this module with the wheel smoke venv
Python from a non-repository working directory. The import-source guard keeps
that smoke honest: importing from the checkout is a release-gate failure even
when the tool list itself looks correct.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from z_harness_cli import release_surface

REQUIRED_TOOLS = {"z_plan", "z_execute", "z_export", "z_update"}
MANIFEST_EXCLUDED_TOOLS = release_surface.dev_only_mcp_tool_names()
REMOVED_TOOLS = {"z_do", "z_evaluate", "z_uplift"}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def assert_non_repo_cwd(repo_root: Path, cwd: Path | None = None) -> None:
    resolved_repo = repo_root.resolve()
    resolved_cwd = (cwd or Path.cwd()).resolve()
    assert not _is_relative_to(resolved_cwd, resolved_repo), (
        "prod MCP tool-list smoke must run outside the checkout; "
        f"cwd={resolved_cwd} repo_root={resolved_repo}"
    )


def assert_installed_import_source(
    module_file: str | Path | None,
    repo_root: Path,
    prefix: Path | None = None,
) -> None:
    assert module_file, (
        "z_harness_cli module has no __file__; cannot prove wheel import source"
    )
    module_path = Path(module_file).resolve()
    resolved_repo = repo_root.resolve()
    resolved_prefix = (prefix or Path(sys.prefix)).resolve()

    assert not _is_relative_to(module_path, resolved_repo), (
        "prod MCP tool-list smoke imported z_harness_cli from checkout instead of installed wheel: "
        f"{module_path}"
    )
    assert _is_relative_to(module_path, resolved_prefix), (
        "prod MCP tool-list smoke imported z_harness_cli outside the smoke venv: "
        f"module={module_path} sys_prefix={resolved_prefix}"
    )


def assert_prod_tool_list(tools: set[str]) -> None:
    missing = sorted(REQUIRED_TOOLS - tools)
    leaked = sorted(MANIFEST_EXCLUDED_TOOLS & tools)
    assert not missing, f"prod MCP tool list missing required tools: {missing}"
    assert not leaked, f"prod MCP tool list leaked hidden tools: {leaked}"
    removed = sorted(REMOVED_TOOLS & tools)
    assert not removed, f"prod MCP tool list leaked removed tools: {removed}"
    release_surface.prod_mcp_tool_backings(tools)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args(argv)

    assert_non_repo_cwd(args.repo_root)

    import z_harness_cli
    from z_harness_cli.mcp.server import _active_command_tools

    assert_installed_import_source(z_harness_cli.__file__, args.repo_root)
    assert_prod_tool_list(set(_active_command_tools()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
