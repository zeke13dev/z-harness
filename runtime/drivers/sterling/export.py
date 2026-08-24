"""Export z-harness roles and orchestrated workflows to Sterling's portable IDL.

z-harness remains the authority for role instructions and workflow artifacts.
The export deliberately contains no provider, runtime, session, retry, timeout,
or scheduling decisions; Sterling resolves those when it starts a worker run.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import ExportResult, _parse_frontmatter, enumerate_sources

_PACKAGE_DIR = ".sterling/z-harness"
_WORKFLOW_SKILLS = ("z-plan-split", "z-execute", "z-manager-execute")
_PORTABLE_SCRIPT = re.compile(
    r"(?<![/A-Za-z0-9_])scripts/([A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*)"
)
_PLUGIN_ROOT = "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"


def _portable_harness_paths(text: str) -> str:
    """Root unqualified harness script paths without changing rooted paths."""
    return _PORTABLE_SCRIPT.sub(rf"{_PLUGIN_ROOT}/scripts/\1", text)


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
    body = _portable_harness_paths(str(entry["body"]).lstrip("\n"))
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
    source = _portable_harness_paths(entry["source_path"].read_text(encoding="utf-8"))
    bridge = """\
<!-- Generated Sterling projection. The source skill below remains canonical. -->
## Sterling worker dispatch (`sterling_worker.v1`)

This section has precedence over host-native dispatch, provider resolution, and
model-selection instructions in the canonical source below. When the
`sterling_worker` tool is available, project every executable source
`Agent(...)` call through it using this contract:

1. Set `worker_id` to the exact source `subagent_type`.
2. Set `node_key` to `<worker_id>:<logical-id>:<callsite-ordinal>`. Derive the
   logical ID from the canonical task ID, cluster slug, or other item ID in the
   source prompt, falling back to `workflow`. The callsite ordinal is one-based
   within this projection. Replace every character outside
   `[A-Za-z0-9._:-]` with `_`.
3. Copy the complete source prompt without paraphrase.
4. Use `relationship="blocking"` whenever the source consumes or awaits the
   return or uses it as a gate. Use `supporting` only when the source explicitly
   launches the call without joining it before progress.
5. Put source calls declared parallel into one `dispatch`; otherwise dispatch
   one node. `wait` for every blocking run, map results back into source order,
   and substitute each `result.text` for its native `Agent(...)` return.
6. On retry, reuse the same `node_key`, pass the prior run ID as
   `predecessor_id`, and let Sterling assign the incremented attempt number.
7. A child state of `waiting`, `failed`, `cancelled`, `stalled`, or `looping`
   is a workflow halt. End the mainline with the matching `STERLING_STATUS`;
   never consume that child as successful agent output.
8. Every `wait` is bounded. If a nonterminal run returns with unchanged
   `last_activity_at` while `last_heartbeat_at` advances, call `nudge` exactly
   once with that run ID and concise task context, then wait once more. If
   activity is still unchanged after the post-nudge wait, `cancel` the stranded
   run and apply the source retry policy or halt. Never loop `wait` solely
   because transport check-ins continue.

### Sterling model ownership override

Sterling ignores host-native `Agent(model=...)`, pre-review gate-down,
consult-off self-review substitution, and provider-resolution blocks in this
projection. The canonical correctness gate always dispatches worker ID
`reviewer`. Route literals are exact:

- first-pass `implementer` -> `implementer`
- high-complexity or review-retry `implementer` -> `deep`
- `reviewer` and `self-reviewer` -> `reviewer`
- every other worker -> `standard`

The mainline supplies only those route literals. Provider, model, and thinking
remain Sterling configuration.

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
    reviewer_path = repo_root / "runtime" / "drivers" / "sterling" / "reviewer.md"
    reviewer_frontmatter, reviewer_body = _parse_frontmatter(
        reviewer_path.read_text(encoding="utf-8")
    )
    reviewer_id = reviewer_frontmatter.get("name", reviewer_path.stem)
    agents[reviewer_id] = {
        "id": reviewer_id,
        "source_path": reviewer_path,
        "frontmatter": reviewer_frontmatter,
        "body": reviewer_body,
    }
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
        "schema_version": 2,
        "name": "z-harness",
        "source_commit": _source_commit(repo_root),
        "driver": {
            "agent_dispatch": "sterling_worker.v1",
            "model_owner": "sterling",
            "required_routes": [
                "mainline",
                "implementer",
                "reviewer",
                "standard",
                "deep",
            ],
            "required_workers": ["implementer", "reviewer"],
        },
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
