#!/usr/bin/env python3
"""Blocking OMP prod export smoke for release candidates.

Runs the installed ``z-harness`` CLI against the current checkout and verifies
that the public OMP package matches the parity gate and prod-surface contract.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROD_HIDDEN_SKILLS = (
    "z-research",
    "z-explore",
    "z-overnight",
    "z-attend",
)
PROD_HIDDEN_AGENTS = (
    "axiom-extractor",
    "research-judge",
)


def _run_export(cli: str, out_dir: Path) -> None:
    env = os.environ.copy()
    env["Z_HARNESS_RELEASE_SURFACE"] = "prod"
    proc = subprocess.run(
        [cli, "export", "--host", "omp", "--surface", "prod", "--out", str(out_dir), "--force"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "OMP prod export failed\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )


def _require(path: Path, message: str) -> None:
    if not path.exists():
        raise AssertionError(f"{message}: {path}")


def validate_omp_export(out_dir: Path) -> None:
    """Validate an already-emitted OMP prod export directory."""
    package_root = out_dir / ".omp" / "z-harness"
    config_path = out_dir / ".omp" / "config.yml"
    manifest_path = package_root / "manifest.yml"

    _require(config_path, "missing OMP config")
    _require(manifest_path, "missing OMP manifest")

    config_text = config_path.read_text(encoding="utf-8")
    if "enableAgentsProject: false" not in config_text:
        raise AssertionError(".omp/config.yml must keep skills.enableAgentsProject: false")
    if "enableAgentsProject: true" in config_text:
        raise AssertionError(".omp/config.yml re-enabled project agent autoload")

    # Import the concrete adapter before reading the matrix; registration happens
    # at adapter import time.
    import z_harness_cli.adapters.omp  # noqa: F401

    from z_harness_cli.adapters.base import KNOWN_COMMANDS, command_tier
    from z_harness_cli.adapters.omp_parity_gate import (
        PARITY_EVIDENCE,
        omp_command_tier,
        omp_export_fidelity,
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    expected_fidelity = omp_export_fidelity()
    if f"fidelity: {expected_fidelity}" not in manifest_text:
        raise AssertionError(
            f"OMP manifest fidelity does not match parity gate: expected {expected_fidelity!r}"
        )

    for cmd in KNOWN_COMMANDS:
        actual = command_tier("omp", cmd)
        expected = omp_command_tier(cmd)
        if actual != expected:
            raise AssertionError(
                f"OMP command tier mismatch for {cmd}: matrix={actual!r} gate={expected!r}"
            )
        if actual == "native" and cmd not in PARITY_EVIDENCE:
            raise AssertionError(
                f"OMP command {cmd!r} claims native without PARITY_EVIDENCE"
            )

    for skill_id in PROD_HIDDEN_SKILLS:
        for rel in (
            Path("skills") / skill_id,
            Path("prompts") / f"{skill_id}.md",
            Path("rules") / f"{skill_id}.md",
        ):
            hidden_path = package_root / rel
            if hidden_path.exists():
                raise AssertionError(f"prod-hidden OMP skill resource leaked: {hidden_path}")

    for family_dir in ("skills", "prompts", "rules"):
        base = package_root / family_dir
        if base.is_dir():
            axiom_hits = sorted(path for path in base.glob("z-axiom-*") if path.exists())
            if axiom_hits:
                raise AssertionError(f"prod-hidden OMP axiom resource leaked: {axiom_hits[0]}")

    for agent_id in PROD_HIDDEN_AGENTS:
        hidden_agent = package_root / "agents" / f"{agent_id}.md"
        if hidden_agent.exists():
            raise AssertionError(f"prod-hidden OMP agent leaked: {hidden_agent}")


def run_smoke(cli: str, out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Plant stale bad state first. A correct prod --force export must replace it.
    package_root = out_dir / ".omp" / "z-harness"
    (out_dir / ".omp").mkdir(parents=True, exist_ok=True)
    (out_dir / ".omp" / "config.yml").write_text(
        "skills:\n  enableAgentsProject: true\n",
        encoding="utf-8",
    )
    for rel in (
        Path("skills") / "z-research" / "SKILL.md",
        Path("skills") / "z-explore" / "SKILL.md",
        Path("prompts") / "z-axiom-scan.md",
        Path("rules") / "z-overnight.md",
        Path("agents") / "axiom-extractor.md",
    ):
        target = package_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale hidden resource\n", encoding="utf-8")

    _run_export(cli, out_dir)
    validate_omp_export(out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="z-harness", help="z-harness executable to smoke")
    parser.add_argument("--out", required=True, help="repo-local export destination")
    args = parser.parse_args(argv)

    try:
        run_smoke(args.cli, Path(args.out).resolve())
    except Exception as exc:  # noqa: BLE001 - release smoke must print concise failure.
        print(f"omp-prod-export-smoke: FAIL: {exc}", file=sys.stderr)
        return 1
    print("omp-prod-export-smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
