from __future__ import annotations

import json
from pathlib import Path

from runtime.drivers.sterling.export import export


def test_sterling_export_is_portable_and_projects_orchestrated_workflows(tmp_path: Path) -> None:
    repo_root = Path(__file__).parent.parent
    result = export(repo_root, tmp_path)
    package = tmp_path / ".sterling" / "z-harness"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    implementer = json.loads((package / "workers" / "implementer.json").read_text(encoding="utf-8"))
    plan_split = (package / "workflows" / "z-plan-split.md").read_text(encoding="utf-8")

    assert result.fidelity == "portable"
    assert manifest["schema_version"] == 1
    assert manifest["workflows"]["z-plan-split"]["dispatch"] == "dynamic"
    assert "workstreams.json" in manifest["workflows"]["z-execute"]["dependency_artifacts"]
    assert implementer["route"]["model_class"]
    assert implementer["instructions"]
    assert "provider" not in implementer["route"]
    assert "runtime" not in implementer
    assert "every executable `Agent(...)`" in plan_split
    assert "opaque nested subagent tool" in plan_split
