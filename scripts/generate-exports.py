#!/usr/bin/env python3
"""scripts/generate-exports.py — Regenerate all in-scope host exports to a target directory.

Usage:
    python3 scripts/generate-exports.py [--out DIR] [--host HOST]

Options:
    --out DIR       Destination root (default: temp/exports/ relative to repo root).
                    Created if absent.  Wiped and recreated on each run.
    --host HOST     Export only one host: cursor | codex | antigravity.
                    Default: all three.

Exits 0 if all three exports complete with zero validation warnings.
Exits 1 if any export raises an exception or emits validation warnings.

This script calls runtime driver export() directly — no network, no install
required (offline-safe).  It is NOT a wrapper of the z_harness_cli CLI, which
carries path-guard and env-resolution complexity incompatible with CI smoke runs.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Resolve repo root relative to this script's location.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Ensure the repo root is on sys.path so `runtime.drivers.*` is importable
# without installing the package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.drivers.cursor import export as _cursor_export  # noqa: E402
from runtime.drivers.codex import export as _codex_export  # noqa: E402
from runtime.drivers.antigravity import export as _agy_export  # noqa: E402

_ALL_HOSTS: dict[str, object] = {
    "cursor": _cursor_export.export,
    "codex": _codex_export.export,
    "antigravity": _agy_export.export,
}

_DEFAULT_OUT = REPO_ROOT / "temp" / "exports"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help=f"Destination root directory (default: {_DEFAULT_OUT})",
    )
    p.add_argument(
        "--host",
        choices=list(_ALL_HOSTS),
        default=None,
        help="Export only one host (default: all three).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    out_root = Path(args.out).resolve()
    hosts = {args.host: _ALL_HOSTS[args.host]} if args.host else dict(_ALL_HOSTS)

    # Wipe and recreate the output root so stale files never linger.
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    total_warnings = 0
    any_error = False

    for host_name, export_fn in hosts.items():
        host_dest = out_root / host_name
        host_dest.mkdir(parents=True, exist_ok=True)
        print(f"[{host_name}] generating → {host_dest}")
        try:
            result = export_fn(REPO_ROOT, host_dest)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001
            # Broad catch is intentional: any uncaught driver exception is a
            # hard failure — re-raise context is printed to stderr.
            print(f"[{host_name}] ERROR: {exc}", file=sys.stderr)
            any_error = True
            continue

        n_files = len(result.files)
        n_warn = len(result.warnings)
        print(f"[{host_name}] fidelity={result.fidelity}  files={n_files}  warnings={n_warn}")

        if result.warnings:
            for w in result.warnings:
                print(f"[{host_name}]   WARNING: {w}", file=sys.stderr)
            total_warnings += n_warn

    if any_error:
        print("generate-exports: FAILED (driver error)", file=sys.stderr)
        return 1

    if total_warnings:
        print(f"generate-exports: FAILED ({total_warnings} validation warning(s))", file=sys.stderr)
        return 1

    print(f"generate-exports: OK  ({len(hosts)} host(s) written to {out_root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
