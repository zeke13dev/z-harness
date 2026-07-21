"""Focused tests for runtime/drivers/codex/export.py."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from runtime import release_surface
from runtime.drivers.codex.export import export

_SURFACE_MARKER = "<!-- include: _fragments/surface-mapping.md -->"
_SURFACE_SENTINEL = "Shared surface mapping contract"


def _make_repo_with_included_skill(tmp_path: Path, skill_name: str) -> Path:
    repo_root = tmp_path / "repo"
    skill_dir = repo_root / "skills" / skill_name
    fragment_dir = repo_root / "_fragments"
    skill_dir.mkdir(parents=True)
    fragment_dir.mkdir(parents=True)

    (fragment_dir / "surface-mapping.md").write_text(
        "## Shared surface mapping contract\n\nRepo Explore facets\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        'description: "Explain code"\n'
        "runtime: c1\n"
        "---\n"
        "\n"
        "Before fragment.\n"
        f"{_SURFACE_MARKER}\n"
        "After fragment.\n",
        encoding="utf-8",
    )
    return repo_root


def _write_safe_agent(repo_root: Path, *, include_model: bool = True) -> Path:
    agent_dir = repo_root / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_path = agent_dir / "safe-agent.md"
    model_line = "model: haiku\n" if include_model else ""
    agent_path.write_text(
        "---\n"
        "name: safe-agent\n"
        'description: "Useful native Codex agent fixture"\n'
        "tools: Read, Grep\n"
        f"{model_line}"
        "---\n"
        "\n"
        "Follow the user request exactly.\n"
        'Preserve quotes like "this" and backslashes like C:\\\\tmp.\n',
        encoding="utf-8",
    )
    return agent_path


def test_codex_native_skill_export_expands_z_explain_surface_fragment(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    export_root = tmp_path / "export"

    export(repo_root, export_root)

    exported = export_root / "skills" / "z-explain" / "SKILL.md"
    text = exported.read_text(encoding="utf-8")
    assert text.startswith("---\nname: z-explain\n")
    assert _SURFACE_SENTINEL in text
    assert _SURFACE_MARKER not in text


def test_codex_native_skill_export_expands_z_learn_surface_fragment(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-learn")
    export_root = tmp_path / "export"

    export(repo_root, export_root)

    exported = export_root / "skills" / "z-learn" / "SKILL.md"
    text = exported.read_text(encoding="utf-8")
    assert text.startswith("---\nname: z-learn\n")
    assert _SURFACE_SENTINEL in text
    assert _SURFACE_MARKER not in text


class TestCodexNativeAgentExport:
    """Codex-native custom-agent export evidence for the parity gate."""

    def test_native_agent_toml_is_written_and_parseable(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        _write_safe_agent(repo_root)
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        agent_path = export_root / ".codex" / "agents" / "safe-agent.toml"
        assert agent_path in result.files
        data = tomllib.loads(agent_path.read_text(encoding="utf-8"))
        assert data["name"] == "safe-agent"
        assert data["description"] == "Useful native Codex agent fixture"
        assert "Follow the user request exactly." in data["developer_instructions"]
        assert '"this"' in data["developer_instructions"]
        assert data["model"] == "haiku"

    def test_native_agent_toml_accepts_missing_model(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        _write_safe_agent(repo_root, include_model=False)
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        agent_path = export_root / ".codex" / "agents" / "safe-agent.toml"
        assert agent_path in result.files
        data = tomllib.loads(agent_path.read_text(encoding="utf-8"))
        assert data["name"] == "safe-agent"
        assert data["developer_instructions"].strip()
        assert "model" not in data

    def test_native_agent_toml_rejects_missing_instructions(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        agent_path = _write_safe_agent(repo_root)
        agent_path.write_text(
            "---\n"
            "name: safe-agent\n"
            'description: "Useful native Codex agent fixture"\n'
            "model: haiku\n"
            "---\n",
            encoding="utf-8",
        )
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        assert export_root / ".codex" / "agents" / "safe-agent.toml" not in result.files
        assert any("developer_instructions must be a non-empty string" in w for w in result.warnings)

    def test_existing_codex_artifacts_are_still_emitted(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        _write_safe_agent(repo_root)
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        assert export_root / "skills" / "z-explain" / "SKILL.md" in result.files
        assert export_root / ".codex" / "agents" / "safe-agent.toml" in result.files
        assert export_root / "AGENTS.md" in result.files
        assert export_root / ".codex-plugin" / "plugin.json" in result.files
        assert export_root / "mcp_config.json" in result.files

    def test_mcp_config_artifact_is_written_for_adapter_registration(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        _write_safe_agent(repo_root)
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        config_path = export_root / "mcp_config.json"
        assert config_path in result.files
        data = json.loads(config_path.read_text(encoding="utf-8"))
        server = data["mcpServers"]["z-harness"]
        assert server["command"] == "python3"
        assert server["args"] == [
            "-m",
            "z_harness_cli",
            "serve",
            "--transport",
            "stdio",
        ]
        assert server["default_tools_approval_mode"] == "approve"
        assert server["enabled_tools"] == ["z_detect"]
        assert server["env"]["PYTHONPATH"] == str(repo_root.resolve())

    def test_mcp_config_prefers_repo_venv_python_when_present(self, tmp_path: Path) -> None:
        repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
        _write_safe_agent(repo_root)
        venv_python = repo_root / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
        export_root = tmp_path / "export"

        result = export(repo_root, export_root)

        config_path = export_root / "mcp_config.json"
        assert config_path in result.files
        data = json.loads(config_path.read_text(encoding="utf-8"))
        server = data["mcpServers"]["z-harness"]
        assert server["command"] == str(venv_python)


def _write_prod_implementer(repo_root: Path) -> None:
    agent_path = repo_root / "agents" / "implementer.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text(
        "---\n"
        "name: implementer\n"
        'description: "Implement one task"\n'
        "model: sonnet\n"
        "---\n\n"
        "Implement the task exactly.\n",
        encoding="utf-8",
    )


def _prod_export_contract() -> dict[str, object]:
    return {
        "prod_inventory": {
            "skills": ["z-explain"],
            "agents": ["implementer"],
            "mcp_tools": [],
            "export_targets": ["codex"],
            "scripts_backends": [],
            "schemas": [],
            "public_documents": [],
            "generated_requirements": [],
        }
    }


def test_codex_prod_export_consumes_the_canonical_skill_agent_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_prod_implementer(repo_root)
    dev_skill = repo_root / "skills" / "z-research" / "SKILL.md"
    dev_skill.parent.mkdir(parents=True)
    dev_skill.write_text("---\nname: z-research\n---\n\ndev only\n", encoding="utf-8")
    (repo_root / "agents" / "axiom-extractor.md").write_text(
        "---\nname: axiom-extractor\n---\n\ndev only\n",
        encoding="utf-8",
    )
    (repo_root / ".git").mkdir()
    monkeypatch.setattr(release_surface, "release_contract", _prod_export_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")

    result = export(repo_root, tmp_path / "export")

    assert (result.dest / "skills" / "z-explain" / "SKILL.md").is_file()
    assert (result.dest / ".codex" / "agents" / "implementer.toml").is_file()
    assert not (result.dest / "skills" / "z-research").exists()
    assert not (result.dest / ".codex" / "agents" / "axiom-extractor.toml").exists()


def test_codex_prod_export_rejects_unresolved_graph_before_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_prod_implementer(repo_root)
    (repo_root / ".git").mkdir()
    skill_path = repo_root / "skills" / "z-explain" / "SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8") + "\npython3 scripts/missing.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_surface, "release_contract", _prod_export_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    export_root = tmp_path / "export"

    with pytest.raises(ValueError, match="scripts/missing.py"):
        export(repo_root, export_root)

    assert not (export_root / ".codex-plugin" / "plugin.json").exists()
