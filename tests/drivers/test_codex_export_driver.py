"""Focused tests for runtime/drivers/codex/export.py."""

from __future__ import annotations

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from runtime import release_surface
from runtime.capability_authority import (
    AUTHORITY_VERSION,
    Capability,
    CapabilityAuthority,
    CapabilityEvidence,
    CapabilityKey,
)
from runtime.drivers.codex.export import export
from runtime.drivers._export_utils import ExportResult

_SURFACE_MARKER = "<!-- include: _fragments/surface-mapping.md -->"
_SURFACE_SENTINEL = "Shared surface mapping contract"
_BLOCKED_WARNING_SUFFIX = (
    "; restriction applies only to the z-execute workflow; "
    "global native collaboration/subagent tools remain available"
)


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


def _authority_context(tmp_path: Path) -> tuple[dict[str, object], CapabilityKey]:
    key = CapabilityKey("codex", "app", "runtime-abc", "z-execute", "bounded")
    options: dict[str, object] = {
        "authority_path": str(tmp_path / "authority.json"),
        "host": key.host,
        "surface": key.surface,
        "runtime_build": key.runtime_build,
        "command": key.command,
        "posture": key.posture,
        "now": 150,
    }
    return options, key


def _evidence(
    key: CapabilityKey,
    installed_export_fingerprint: str,
    *,
    capability: Capability = Capability.NATIVE_BOUNDED,
) -> CapabilityEvidence:
    return CapabilityEvidence(
        evidence_id="app-proof",
        authority_version=AUTHORITY_VERSION,
        key=key,
        capability=capability,
        evidence_surface="app",
        installed_export_fingerprint=installed_export_fingerprint,
        issued_at=100,
        expires_at=200,
    )


def _computed_fingerprint(result: ExportResult) -> str:
    manifest = json.loads((result.dest / ".codex-plugin" / "plugin.json").read_text())
    return manifest["capability_authority"]["installed_export_fingerprint"]


def _blocked_warning(reason: str) -> str:
    return f"z-execute blocked: {reason}{_BLOCKED_WARNING_SUFFIX}"


def _write_execute_skill(repo_root: Path) -> Path:
    execute_skill = repo_root / "skills" / "z-execute" / "SKILL.md"
    execute_skill.parent.mkdir(parents=True)
    execute_skill.write_text(
        "---\nname: z-execute\n---\n\nDispatch child agents.\n",
        encoding="utf-8",
    )
    return execute_skill


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


def test_codex_plugin_export_blocks_z_execute_but_keeps_safe_skills(tmp_path: Path) -> None:
    """Release A blocks only direct-App /z-execute before child dispatch."""
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_execute_skill(repo_root)

    result = export(repo_root, tmp_path / "export")

    assert result.dest / "skills" / "z-explain" / "SKILL.md" in result.files
    assert not (result.dest / "skills" / "z-execute" / "SKILL.md").exists()
    assert all(path.name != "SKILL.md" or path.parent.name != "z-execute" for path in result.files)
    assert result.warnings == [_blocked_warning("release_a_static_block")]
    assert "global native collaboration/subagent tools remain available" in result.warnings[0]


def test_codex_reexport_removes_a_stale_z_execute_skill(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    export_root = tmp_path / "export"
    stale = export_root / "skills" / "z-execute" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale dispatch entrypoint\n", encoding="utf-8")

    export(repo_root, export_root)

    assert not stale.exists()
    assert (export_root / "skills" / "z-explain" / "SKILL.md").is_file()


def test_exact_native_bounded_authority_emits_z_execute_and_binding(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_execute_skill(repo_root)
    options, key = _authority_context(tmp_path)
    probe = export(repo_root, tmp_path / "probe", options=options)
    fingerprint = _computed_fingerprint(probe)
    CapabilityAuthority(options["authority_path"]).persist(_evidence(key, fingerprint))

    result = export(repo_root, tmp_path / "export", options=options)

    assert result.dest / "skills" / "z-execute" / "SKILL.md" in result.files
    binding = json.loads(
        (result.dest / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["capability_authority"]
    assert binding == {
        "host": "codex",
        "surface": "app",
        "runtime_build": "runtime-abc",
        "command": "z-execute",
        "posture": "bounded",
        "installed_export_fingerprint": fingerprint,
        "capability": "native_bounded",
        "reason": "authorized",
        "evidence_id": "app-proof",
        "z_execute_exported": True,
    }


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    (
        ("absent", "unknown_capability"),
        ("stale", "stale_evidence"),
        ("revoked", "revoked_evidence"),
        ("runtime_mismatch", "unknown_capability"),
        ("cli_only", "unknown_capability"),
        ("fingerprint_mismatch", "re_export_required"),
        ("degraded", "degraded_single_agent_only"),
    ),
)
def test_authority_uncertainty_retains_release_a_block(
    tmp_path: Path, case: str, expected_reason: str
) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_execute_skill(repo_root)
    options, key = _authority_context(tmp_path)
    authority = CapabilityAuthority(options["authority_path"])
    probe = export(repo_root, tmp_path / "probe", options=options)
    fingerprint = _computed_fingerprint(probe)
    evidence = _evidence(key, fingerprint)

    if case == "stale":
        authority.persist(evidence)
        options["now"] = evidence.expires_at
    elif case == "revoked":
        authority.persist(evidence)
        authority.revoke(evidence.key, revoked_at=125, reason="proof withdrawn")
    elif case == "runtime_mismatch":
        authority.persist(evidence)
        options["runtime_build"] = "runtime-other"
    elif case == "cli_only":
        cli_key = replace(evidence.key, surface="cli")
        authority.persist(replace(evidence, key=cli_key, evidence_surface="cli"))
    elif case == "fingerprint_mismatch":
        authority.persist(_evidence(key, "sha256:" + "0" * 64))
        options["installed_export_fingerprint"] = "sha256:" + "0" * 64
    elif case == "degraded":
        authority.persist(replace(evidence, capability=Capability.DEGRADED_SINGLE_AGENT))

    result = export(repo_root, tmp_path / "export", options=options)

    assert not (result.dest / "skills" / "z-execute").exists()
    assert result.warnings == [_blocked_warning(expected_reason)]


def test_export_payload_change_invalidates_matching_authority_evidence(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    execute_skill = _write_execute_skill(repo_root)
    options, key = _authority_context(tmp_path)
    probe = export(repo_root, tmp_path / "probe", options=options)
    original_fingerprint = _computed_fingerprint(probe)
    CapabilityAuthority(options["authority_path"]).persist(
        _evidence(key, original_fingerprint)
    )

    execute_skill.write_text(
        execute_skill.read_text(encoding="utf-8") + "Updated executable contract.\n",
        encoding="utf-8",
    )
    result = export(repo_root, tmp_path / "export", options=options)

    assert not (result.dest / "skills" / "z-execute").exists()
    assert result.warnings == [_blocked_warning("re_export_required")]
    assert _computed_fingerprint(result) != original_fingerprint


def test_atomic_authority_update_invalidates_installed_export_on_reexport(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    _write_execute_skill(repo_root)
    export_root = tmp_path / "export"
    options, key = _authority_context(tmp_path)
    authority = CapabilityAuthority(options["authority_path"])
    probe = export(repo_root, tmp_path / "probe", options=options)
    evidence = _evidence(key, _computed_fingerprint(probe))
    authority.persist(evidence)
    export(repo_root, export_root, options=options)
    assert (export_root / "skills" / "z-execute" / "SKILL.md").is_file()

    authority.persist(replace(evidence, capability=Capability.BLOCKED))
    first = export(repo_root, export_root, options=options)
    first_manifest = (export_root / ".codex-plugin" / "plugin.json").read_bytes()
    second = export(repo_root, export_root, options=options)

    assert not (export_root / "skills" / "z-execute").exists()
    assert first.warnings == second.warnings == [_blocked_warning("explicitly_blocked")]
    assert (export_root / ".codex-plugin" / "plugin.json").read_bytes() == first_manifest


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
