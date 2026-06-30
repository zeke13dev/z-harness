#!/usr/bin/env python3
"""Stage a manifest-pruned release tree for wheel or tarball builds.

This is intentionally a staging step, not a source deletion step: development
and research files stay in the checkout while public artifacts are built from a
prod-surface tree.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli import release_surface


def _ignore_prod_excluded(src: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    src_path = Path(src)
    for name in names:
        rel = (src_path / name).relative_to(_ignore_prod_excluded.root).as_posix()  # type: ignore[attr-defined]
        if release_surface.path_excluded_from_prod(rel) or (name == ".git" and not _ignore_prod_excluded.keep_git):  # type: ignore[attr-defined]
            ignored.add(name)
    return ignored


def stage_release_surface(repo_root: Path, dest: Path, *, keep_git: bool = False) -> Path:
    repo_root = repo_root.resolve()
    dest = dest.resolve()
    if dest == repo_root or repo_root in dest.parents:
        raise ValueError("release staging destination must be outside the source tree")
    if dest.exists():
        shutil.rmtree(dest)
    _ignore_prod_excluded.root = repo_root  # type: ignore[attr-defined]
    _ignore_prod_excluded.keep_git = keep_git  # type: ignore[attr-defined]
    shutil.copytree(repo_root, dest, ignore=_ignore_prod_excluded)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep-git", action="store_true", help="Keep .git metadata for hatch-vcs wheel builds.")
    args = parser.parse_args(argv)
    staged = stage_release_surface(args.repo_root, args.out, keep_git=args.keep_git)
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
