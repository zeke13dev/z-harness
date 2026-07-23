"""Export z-harness roles and orchestrated workflows to Sterling's portable IDL.

z-harness remains the authority for role instructions and workflow artifacts.
The export deliberately contains no provider, runtime, session, retry, timeout,
or scheduling decisions; Sterling resolves those when it starts a worker run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import ExportResult, enumerate_sources

_PACKAGE_DIR = ".sterling/z-harness"
_WORKFLOW_SKILLS = ("z-plan-split", "z-execute")


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path.resolve()


def _source_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _worker(entry: dict[str, Any]) -> dict[str, Any]:
    frontmatter = entry.get("frontmatter", {})
    body = str(entry["body"]).lstrip("\n")
    worker: dict[str, Any] = {
        "schema_version": 1,
        "id": entry["id"],
        "description": frontmatter.get("description", entry["id"]),
        "instructions": body,
        "instructions_sha256": _digest(body),
        "route": {
            "model_class": frontmatter.get("model_class")
            or frontmatter.get("model")
            or "standard",
            "effort": frontmatter.get("effort") or frontmatter.get("thinking") or "medium",
        },
        "tools": [
            tool.strip()
            for tool in str(frontmatter.get("tools", "")).split(",")
            if tool.strip()
        ],
    }
    return worker


def _workflow_projection(entry: dict[str, Any]) -> str:
    source = entry["source_path"].read_text(encoding="utf-8")
    bridge = """\
<!-- Generated Sterling projection. The source skill below remains canonical. -->
## Sterling worker dispatch

When the `sterling_worker` tool is available, every executable `Agent(...)`
dispatch in this workflow MUST use that tool. Submit calls that the source marks
parallel in one `dispatch` batch, then use `wait` for the required join. Do not
use an opaque nested subagent tool. Sterling owns child sessions, placement,
resumption, retries, supervision, and telemetry; this skill owns prompts,
artifacts, dependencies, and acceptance semantics.

"""
    return bridge + source


def export(
    repo_root: Path,
    export_root: Path,
    *,
    options: dict[str, Any] | None = None,
) -> ExportResult:
    """Write the portable Sterling package under ``.sterling/z-harness``."""
    del options
    repo_root = Path(repo_root).resolve()
    package_root = Path(export_root).resolve() / _PACKAGE_DIR
    sources = enumerate_sources(repo_root)
    agents = {entry["id"]: entry for entry in sources["agents"]}
    skills = {entry["id"]: entry for entry in sources["skills"]}
    emitted: list[Path] = []

    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)
    for entry in agents.values():
        emitted.append(_write_json(package_root / "workers" / f"{entry['id']}.json", _worker(entry)))

    workflow_manifest: dict[str, Any] = {}
    for skill_id in _WORKFLOW_SKILLS:
        entry = skills.get(skill_id)
        if entry is None:
            continue
        projection = _workflow_projection(entry)
        relative = f"workflows/{skill_id}.md"
        emitted.append(_write_text(package_root / relative, projection))
        workflow_manifest[skill_id] = {
            "projection": relative,
            "source": entry["source_path"].relative_to(repo_root).as_posix(),
            "source_sha256": _digest(entry["source_path"].read_text(encoding="utf-8")),
            "dispatch": "dynamic",
            "dependency_artifacts": ["workstreams.json", "work-graph.json"],
        }

    manifest = {
        "schema_version": 1,
        "name": "z-harness",
        "source_commit": _source_commit(repo_root),
        "workers": sorted(agents),
        "workflows": workflow_manifest,
        "contract": {
            "harness_owns": ["instructions", "artifacts", "dependencies", "acceptance"],
            "sterling_owns": [
                "sessions",
                "placement",
                "scheduling",
                "timeouts",
                "retries",
                "supervision",
                "telemetry",
            ],
        },
    }
    emitted.append(_write_json(package_root / "manifest.json", manifest))
    return ExportResult(
        dest=package_root.resolve(),
        files=emitted,
        fidelity="portable",
        warnings=[],
    )
