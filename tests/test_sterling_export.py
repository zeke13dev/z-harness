from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.drivers.sterling.export import export


def test_sterling_export_is_portable_and_projects_orchestrated_workflows(tmp_path: Path) -> None:
    repo_root = Path(__file__).parent.parent
    bridge = tmp_path / "sterling_worker.ts"
    bridge.write_text("export const bridge = 'v1';\n", encoding="utf-8")
    result = export(repo_root, tmp_path, options={"bridge_extension": bridge})
    package = tmp_path / ".sterling" / "z-harness"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    implementer = json.loads(
        (package / "workers" / "implementer.json").read_text(encoding="utf-8")
    )
    reviewer = json.loads(
        (package / "workers" / "reviewer.json").read_text(encoding="utf-8")
    )
    plan_split = (package / "workflows" / "z-plan-split.md").read_text(
        encoding="utf-8"
    )
    plan = (package / "workflows" / "z-plan.md").read_text(encoding="utf-8")
    execute = (package / "workflows" / "z-execute.md").read_text(encoding="utf-8")
    manager_execute = (package / "workflows" / "z-manager-execute.md").read_text(
        encoding="utf-8"
    )

    assert result.fidelity == "portable"
    assert manifest["schema_version"] == 3
    assert manifest["driver"] == {
        "agent_dispatch": "sterling_worker.v1",
        "bridge_extension_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
        "model_owner": "sterling",
        "required_routes": [
            "mainline",
            "implementer",
            "reviewer",
            "standard",
            "deep",
        ],
        "required_workers": ["implementer", "reviewer"],
    }
    assert manifest["workflows"]["z-plan-split"]["dispatch"] == "dynamic"
    assert manifest["workflows"]["z-manager-execute"]["source_sha256"]
    assert manifest["workflows"]["z-plan"]["dispatch"] == "dynamic"
    assert manifest["workflows"]["z-plan"]["projection_sha256"]
    assert manifest["workflows"]["z-plan-split"]["projection_sha256"]
    assert manifest["workflows"]["z-execute"]["dependency_sha256"]
    assert manifest["workflows"]["z-manager-execute"]["projection_sha256"]
    assert "workstreams.json" in manifest["workflows"]["z-execute"][
        "dependency_artifacts"
    ]

    assert implementer["route"]["model_class"]
    assert implementer["instructions"]
    assert "provider" not in implementer["route"]
    assert "runtime" not in implementer
    assert "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/" in implementer[
        "instructions"
    ]
    assert " scripts/resolve-kernel.sh" not in implementer["instructions"]

    assert reviewer["id"] == "reviewer"
    assert reviewer["description"] == "Sterling-native direct correctness reviewer"
    assert reviewer["tools"] == ["Read", "Grep", "Glob", "Bash"]
    assert reviewer["route"] == {"model_class": "reviewer", "effort": "high"}
    assert "## Reviewer review: task <ID>" in reviewer["instructions"]
    assert "### Blockers" in reviewer["instructions"]
    assert "### Major" in reviewer["instructions"]
    assert "strictly read-only" in reviewer["instructions"]
    assert "Do not use Edit or Write" in reviewer["instructions"]
    assert "provider" not in reviewer["route"]
    assert "runtime" not in reviewer

    for projection in (plan, plan_split, execute, manager_execute):
        assert "sterling_worker.v1" in projection
        assert "`<worker_id>:<logical-id>:<callsite-ordinal>`" in projection
        assert "complete source prompt without paraphrase" in projection
        assert 'relationship="blocking"' in projection
        assert "source order" in projection
        assert "`predecessor_id`" in projection
        assert "reuse the same `node_key`" in projection
        assert "call `nudge` exactly" in projection
        assert "Never loop `wait` solely" in projection
        assert "consult-off self-review substitution" in projection
        assert "canonical correctness gate always dispatches worker ID" in projection
        assert "Provider, model, and thinking" in projection
        assert "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/" in projection

    assert "more than 12 nodes" in manager_execute
    assert "one bounded final repair" in manager_execute
    assert "Never promote it automatically" in manager_execute


def test_sterling_export_requires_exact_bridge_extension(tmp_path: Path) -> None:
    repo_root = Path(__file__).parent.parent
    with pytest.raises(RuntimeError, match="bridge_extension"):
        export(repo_root, tmp_path)
