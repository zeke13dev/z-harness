from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from runtime.drivers._export_utils import (
    ExportResult,
    build_prod_dependency_graph,
    enumerate_sources,
    expand_includes,
)
from z_harness_cli import release_surface
from z_harness_cli.__main__ import app
from z_harness_cli.mcp import server as mcp_server


class _FakeAdapter:
    name = "codex"

    def export_payload(self, dest: Path) -> ExportResult:
        marker = dest / "surface.txt"
        marker.write_text(os.environ.get("Z_HARNESS_RELEASE_SURFACE", "missing"), encoding="utf-8")
        return ExportResult(dest=dest, files=[marker], fidelity="flattened")


def _write_skill(root: Path, skill_id: str) -> None:
    skill_dir = root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_id}\n---\nbody\n", encoding="utf-8")


_HIDDEN_SURFACE_ONLY_PATHS = (
    "scripts/axiom-extract.py",
    "scripts/axiom-store.py",
    "scripts/overnight-preflight.sh",
    "docs/human/attend.md",
    "docs/human/axioms.md",
    "docs/human/overnight-run.md",
    "docs/human/hermes-orchestration.md",
    "docs/human/hermes-integration-v1.md",
    "docs/human/review-hermes-implementation.md",
    "docs/human/review-hermes-integration.md",
    "docs/llm/attend.json",
    "docs/llm/axioms.json",
    "docs/llm/overnight-run.json",
    "docs/llm/hermes-orchestration.json",
    "docs/schemas/axiom.schema.json",
    "exports/pi/prompts/z-plan.md",
    ".pi/agents/doc-updater.md",
    ".omp/z-harness/manifest.yml",
    "temp/exports/omp/.omp/z-harness/manifest.yml",
)


_HIDDEN_SURFACE_PATTERN_EXAMPLES = (
    "docs/human/hermes-new-surface.md",
    "docs/human/review-hermes-new-surface.md",
    "docs/llm/axiom-new-surface.json",
    "docs/schemas/axiom-v2.schema.json",
)


_PROD_APPROVED_DOC_SCHEMA_PATHS = (
    "docs/human/INSTALL.md",
    "docs/human/z-update.md",
    "docs/llm/z-update.json",
    "docs/schemas/handoff.schema.json",
)


_FORMERLY_BROAD_BACKEND_ROOTS = (
    "runtime/contract",
    "runtime/dispatch",
    "runtime/drivers/antigravity",
    "runtime/drivers/claude",
    "runtime/drivers/cline",
    "runtime/drivers/codex",
    "runtime/drivers/copilot",
    "runtime/drivers/cursor",
    "runtime/drivers/kiro",
    "runtime/drivers/omp",
    "runtime/drivers/pi",
    "runtime/drivers/windsurf",
    "z_harness_cli/adapters",
    "z_harness_cli/commands",
    "z_harness_cli/mcp",
)


_ABSENT_ADVERTISED_SKILLS = {
    "z-clear-checkpoint",
    "z-do",
    "z-evaluate",
    "z-providers-discover",
    "z-safe",
    "z-skill-fix",
    "z-uplift",
    "z-verify",
    "z-where",
}


_PREEXISTING_LITERAL_SCRIPT_PATHS = {
    "scripts/config.py",
    "scripts/discover-providers.py",
    "scripts/generate-workstreams.py",
    "scripts/log-event.sh",
    "scripts/log-phase.sh",
    "scripts/log-providers.sh",
    "scripts/log-subagent.sh",
    "scripts/resolve-provider.py",
    "scripts/resolve-provider.sh",
    "scripts/setup.py",
    "scripts/setup.sh",
    "scripts/version.sh",
}


def test_manifest_classifies_disputed_commands_and_agents() -> None:
    assert not release_surface.is_prod_visible("skills", "z-explore", "prod")
    assert not release_surface.is_prod_visible("skills", "z-axiom-scan", "prod")
    assert not release_surface.is_prod_visible("mcp_tools", "z_explore", "prod")
    assert not release_surface.is_prod_visible("agents", "research-judge", "prod")
    assert release_surface.is_prod_visible("skills", "z-plan", "prod")
    assert release_surface.is_prod_visible("mcp_tools", "z_plan", "prod")


def test_prod_visibility_and_paths_fail_closed_for_unknown_entries() -> None:
    assert not release_surface.is_prod_visible("future_kind", "z-plan", "prod")
    assert not release_surface.is_prod_visible("skills", "z-future", "prod")
    assert release_surface.prod_owner_for_path("scripts/future-release-step.py") is None
    assert release_surface.prod_owner_for_path("runtime/future_backend.py") is None
    assert release_surface.prod_owner_for_path("docs/human/future-public-claim.md") is None
    assert release_surface.first_prod_artifact_violation(
        ["./skills/z-plan/SKILL.md", "./scripts/future-release-step.py"]
    ) == "scripts/future-release-step.py"


@pytest.mark.parametrize("backend_root", _FORMERLY_BROAD_BACKEND_ROOTS)
def test_unknown_nested_backend_paths_fail_closed(backend_root: str) -> None:
    unknown_path = f"{backend_root}/future/nested.py"

    assert release_surface.prod_owner_for_path(unknown_path) is None
    assert release_surface.first_prod_artifact_violation([unknown_path]) == unknown_path


def test_skill_and_agent_ownership_accepts_only_exact_inventoried_files() -> None:
    assert release_surface.prod_owner_for_path("skills/z-plan/SKILL.md") == "skills"
    assert release_surface.prod_owner_for_path("skills/z-plan") == "skills"
    assert release_surface.prod_owner_for_path("skills/z-plan/future/nested.md") is None
    assert release_surface.prod_owner_for_path("agents/surgical-fixer.md") == "agents"
    assert release_surface.prod_owner_for_path("agents/surgical-fixer/future.md") is None


@pytest.mark.parametrize(
    ("kind", "owned_path", "unknown_path"),
    (
        ("scripts_backends", "scripts/setup.py", "scripts/future-release-step.py"),
        ("schemas", "docs/schemas/handoff.schema.json", "docs/schemas/future.schema.json"),
        ("public_documents", "README.md", "docs/human/future-public-claim.md"),
        ("generated_requirements", "pyproject.toml", "future-requirements.txt"),
    ),
)
def test_path_inventory_kinds_are_recognized_and_fail_closed(
    kind: str, owned_path: str, unknown_path: str
) -> None:
    contract = release_surface.release_contract()

    assert kind in contract["prod_kinds"]
    assert release_surface.is_prod_visible(kind, owned_path, "prod")
    assert not release_surface.is_prod_visible(kind, unknown_path, "prod")


def test_release_contract_is_positive_and_freezes_experiment_exclusions() -> None:
    contract = release_surface.release_contract()
    inventory = contract["prod_inventory"]

    assert contract["train"] == {
        "channel": "pre-1.0-beta",
        "stable_1x_compatibility": False,
        "version": None,
        "tag": None,
    }
    assert contract["generation_inputs"] == [
        "_fragments/run-brief-finalize.md",
        "_fragments/run-brief-halt-finalize-execute.md",
        "_fragments/surface-mapping.md",
        "_fragments/zplan-cost-gate-reference.md",
    ]
    assert all(
        release_surface.prod_owner_for_path(path) is None
        for path in contract["generation_inputs"]
    )
    assert {
        "skills",
        "agents",
        "scripts_backends",
        "schemas",
        "public_documents",
        "generated_requirements",
    } <= inventory.keys()
    assert "z-plan" in inventory["skills"]
    assert "implementer" in inventory["agents"]
    assert "surgical-fixer" in inventory["agents"]
    assert "safe-agent" not in inventory["agents"]
    assert _ABSENT_ADVERTISED_SKILLS.isdisjoint(inventory["skills"])
    assert "backend_units" not in inventory
    assert "scripts/setup.py" in inventory["scripts_backends"]
    assert "scripts/generate-workstreams.py" in inventory["scripts_backends"]
    assert "scripts/capture-release-host-evidence.py" in inventory["scripts_backends"]
    assert "scripts/check-pi-auth.sh" in inventory["scripts_backends"]
    assert "scripts/orchestration-status.py" in inventory["scripts_backends"]
    assert "scripts/emit-hermes-marker.sh" not in inventory["scripts_backends"]
    assert "z_harness_cli/release_host_evidence.py" in inventory["scripts_backends"]
    assert "docs/schemas/handoff.schema.json" in inventory["schemas"]
    assert "README.md" in inventory["public_documents"]
    assert ".codex-plugin/plugin.json" not in inventory["generated_requirements"]
    assert "requirements.txt" not in inventory["generated_requirements"]
    assert "install.sh" in inventory["generated_requirements"]
    assert inventory["export_skill_inventories"]["codex"] == sorted(
        set(inventory["skills"]) - {"z-execute"}
    )
    assert contract["excluded_experiments"]["skills"] == [
        "z-attend",
        "z-explore",
        "z-map",
        "z-overnight",
        "z-research",
    ]
    assert contract["excluded_experiments"]["skill_patterns"] == ["z-axiom-*"]
    assert release_surface.prod_owner_for_path("runtime/watchdog/daemon.py") is None
    assert release_surface.prod_owner_for_path("scripts/hermes/so_mcp.py") is None
    assert not release_surface.path_excluded_from_prod("scripts/generate-workstreams.py")


def test_prod_inventory_exactly_closes_retained_literal_support_scripts() -> None:
    repo_root = Path(__file__).parent.parent
    literal_scripts: set[str] = set()
    for skill_id in release_surface.prod_skill_ids():
        source = repo_root / "skills" / skill_id / "SKILL.md"
        expanded = expand_includes(source.read_text(encoding="utf-8"), repo_root)
        literal_scripts.update(release_surface._SCRIPT_REFERENCE_RE.findall(expanded))

    inventory = set(release_surface.release_contract()["prod_inventory"]["scripts_backends"])
    newly_admitted = literal_scripts - _PREEXISTING_LITERAL_SCRIPT_PATHS
    assert len(newly_admitted) == 58
    assert newly_admitted <= inventory
    assert "scripts/notify-discord.sh" not in literal_scripts
    assert "scripts/notify-discord.sh" not in inventory


def test_positive_inventory_entries_resolve_to_intended_artifacts() -> None:
    repo_root = Path(__file__).parent.parent
    inventory = release_surface.release_contract()["prod_inventory"]

    for skill_id in inventory["skills"]:
        assert (repo_root / "skills" / skill_id / "SKILL.md").is_file(), skill_id
    for agent_id in inventory["agents"]:
        assert (repo_root / "agents" / f"{agent_id}.md").is_file(), agent_id
    for kind in ("scripts_backends", "schemas", "public_documents", "generated_requirements"):
        for artifact_path in inventory[kind]:
            assert (repo_root / artifact_path).is_file(), artifact_path


def test_every_bare_script_command_in_public_docs_is_shipped() -> None:
    """Runnable script commands in public Markdown must ship canonically."""

    repo_root = Path(__file__).parent.parent
    inventory = release_surface.release_contract()["prod_inventory"]
    documented_commands: set[str] = set()
    for relative in inventory["public_documents"]:
        path = repo_root / relative
        if path.suffix != ".md":
            continue
        body = path.read_text(encoding="utf-8")
        documented_commands.update(
            re.findall(r"`(?:bash\s+)?(scripts/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:sh|py))", body)
        )
        documented_commands.update(
            line.strip().removeprefix("bash ")
            for line in body.splitlines()
            if re.fullmatch(
                r"(?:bash\s+)?scripts/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:sh|py)",
                line.strip(),
            )
        )

    assert documented_commands
    assert documented_commands <= set(inventory["scripts_backends"])
    assert all((repo_root / command).is_file() for command in documented_commands)


def test_release_contract_freezes_exact_evidence_bounded_host_claims() -> None:
    claims = release_surface.release_contract()["host_claims"]

    assert claims == {
        "claude": {"tier": "native", "status": "primary", "evidence": "blocking_clean_plugin"},
        "cli": {
            "tier": "supported",
            "status": "release",
            "scope": ["bootstrap", "install", "update"],
        },
        "codex": {"tier": "partial", "status": "preview", "evidence": "blocking_clean_plugin"},
        "omp": {
            "tier": "native",
            "status": "conditional",
            "condition": "clean_installed_wheel_proof",
        },
        "antigravity": {"tier": "dev_advanced", "status": "not_release_default"},
        "cursor": {"tier": "dev_advanced", "status": "not_release_default"},
        "cline": {"tier": "export_only", "status": "not_release_default"},
        "copilot": {"tier": "export_only", "status": "not_release_default"},
        "kiro": {"tier": "export_only", "status": "not_release_default"},
            "pi": {"tier": "export_only", "status": "not_release_default"},
            "sterling": {"tier": "export_only", "status": "not_release_default"},
        "windsurf": {"tier": "export_only", "status": "not_release_default"},
    }


def test_release_contract_freezes_clean_candidate_evidence_boundary() -> None:
    requirements = release_surface.release_contract()["clean_candidate_requirements"]

    assert requirements == {
        "source_identity": "exact_reviewed_identity",
        "artifact_identity": "exact_reviewed_identity",
        "source_origin": "tracked_clean_checkout_or_archive",
        "home": "isolated",
        "config": "isolated",
        "wheel": "installed",
        "plugin_payloads": "installed",
        "host_claim_evidence": "blocking_for_every_claim",
        "forbidden_inputs": [
            "ignored_files",
            "untracked_files",
            "user_configuration",
            "dev_only_dependencies",
        ],
    }


def test_release_contract_rejects_stable_version_contradiction() -> None:
    contract = release_surface.release_contract()
    contract["train"]["channel"] = "stable-1.x"
    contract["train"]["stable_1x_compatibility"] = True
    contract["train"]["version"] = "1.0.0"

    with pytest.raises(ValueError, match="pre-1.0 beta"):
        release_surface.validate_release_contract(contract)

    release_surface.validate_release_contract(release_surface.release_contract())


def test_release_contract_rejects_frozen_shape_contradictions() -> None:
    wrong_schema = release_surface.release_contract()
    wrong_schema["schema_version"] = 2

    missing_kind = release_surface.release_contract()
    missing_kind["prod_kinds"].remove("schemas")

    missing_train_field = release_surface.release_contract()
    missing_train_field["train"].pop("tag")

    added_stable_promise = release_surface.release_contract()
    added_stable_promise["train"]["compatibility_promise"] = "stable-1.x"

    added_top_level_field = release_surface.release_contract()
    added_top_level_field["future_contract"] = {}

    contradictions = (
        wrong_schema,
        missing_kind,
        missing_train_field,
        added_stable_promise,
        added_top_level_field,
    )
    for contradiction in contradictions:
        with pytest.raises(ValueError, match="complete canonical schema and shape"):
            release_surface.validate_release_contract(contradiction)


def test_public_release_default_helpers_include_codex() -> None:
    assert release_surface.public_release_hosts() == ("claude", "omp", "codex")
    assert release_surface.setup_target_ids("prod") == ("claude", "omp", "codex")
    assert set(release_surface.explicit_setup_target_ids()) == {"claude", "omp", "pi", "cursor", "codex"}
    assert release_surface.plugin_install_target_ids("prod") == {"claude", "codex"}
    assert release_surface.plugin_install_target_ids("dev") == {"claude", "codex"}


def test_mcp_prod_tools_are_manifest_filtered(monkeypatch) -> None:
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    tools = set(mcp_server._active_command_tools())
    assert "z_plan" in tools
    assert "z_export" in tools
    assert tools.isdisjoint(release_surface.dev_only_mcp_tool_names())
    assert {"z_do", "z_evaluate", "z_uplift"}.isdisjoint(tools)
    backings = release_surface.prod_mcp_tool_backings(tools)
    assert set(backings) == tools
    assert backings["z_plan"] == "skill:skills/z-plan/SKILL.md"
    assert backings["z_detect"] == "handler:_handle_z_detect"


def test_prod_mcp_backings_fail_closed_for_removed_and_unbacked_tools(monkeypatch) -> None:
    with pytest.raises(ValueError, match="outside frozen prod MCP inventory"):
        release_surface.prod_mcp_tool_backings(["z_do"])

    monkeypatch.setattr(release_surface, "_PROD_MCP_FAST_HANDLERS", {})
    with pytest.raises(ValueError, match="no prod skill or reviewed direct handler"):
        release_surface.prod_mcp_tool_backings(["z_detect"])


def test_runtime_enumeration_filters_dev_checkout_before_graph_validation(
    tmp_path: Path, monkeypatch
) -> None:
    _write_closure_fixture(tmp_path, "python3 scripts/run.py\n")
    (tmp_path / "agents" / "worker.md").rename(
        tmp_path / "agents" / "implementer.md"
    )
    _write_skill(tmp_path, "z-dev-only")
    (tmp_path / "agents" / "dev-agent.md").write_text("dev agent\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    contract = _closure_contract()
    contract["prod_inventory"]["agents"] = ["implementer"]
    monkeypatch.setattr(release_surface, "release_contract", lambda: contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")

    sources = enumerate_sources(tmp_path)

    assert {entry["id"] for entry in sources["skills"]} == {"z-plan"}
    assert {entry["id"] for entry in sources["agents"]} == {"implementer"}


def test_runtime_enumeration_rejects_extra_staged_prod_sources(
    tmp_path: Path, monkeypatch
) -> None:
    _write_closure_fixture(tmp_path, "python3 scripts/run.py\n")
    _write_skill(tmp_path, "z-extra")
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    with pytest.raises(ValueError, match="skills/z-extra/SKILL.md"):
        enumerate_sources(tmp_path)


def _closure_contract() -> dict[str, object]:
    return {
        "prod_inventory": {
            "skills": ["z-plan"],
            "agents": ["worker"],
            "mcp_tools": ["z_plan"],
            "export_targets": ["codex"],
            "scripts_backends": ["scripts/run.py"],
            "schemas": [],
            "public_documents": [],
            "generated_requirements": [],
        }
    }


def _write_closure_fixture(root: Path, skill_body: str) -> None:
    _write_skill(root, "z-plan")
    skill_path = root / "skills" / "z-plan" / "SKILL.md"
    skill_path.write_text(skill_body, encoding="utf-8")
    (root / "agents").mkdir()
    (root / "agents" / "worker.md").write_text("worker\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "run.py").write_text("pass\n", encoding="utf-8")


def test_prod_dependency_graph_is_deterministic_and_uses_reviewed_exceptions(
    tmp_path: Path, monkeypatch
) -> None:
    body = (
        "Agent(subagent_type=\"worker\", prompt=\"work\")\n"
        "Agent(subagent_type=\"Explore\", prompt=\"inspect\")\n"
        "python3 scripts/run.py\n"
    )
    _write_closure_fixture(tmp_path, body)
    exception = release_surface.DynamicDependencyException(
        "skills/z-plan/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    )
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: (exception,))

    graph = build_prod_dependency_graph(tmp_path)

    assert graph == build_prod_dependency_graph(tmp_path)
    assert graph.ok
    assert graph.errors == ()
    assert graph.nodes == tuple(sorted(graph.nodes))
    assert {"mcp-tool:z_plan", "export-target:codex"} <= set(graph.nodes)
    assert graph.edges == tuple(sorted(graph.edges))
    assert {(edge.source_path, edge.target, edge.classification) for edge in graph.edges} == {
        ("mcp-tool:z_plan", "skills/z-plan/SKILL.md", "skill"),
        ("skills/z-plan/SKILL.md", "agents/worker.md", "literal"),
        ("skills/z-plan/SKILL.md", "host-agent:Explore", "reviewed:host_builtin_agent"),
        ("skills/z-plan/SKILL.md", "scripts/run.py", "literal"),
    }


def test_prod_graph_resolves_mcp_and_literal_surgical_agent_edges(
    tmp_path: Path, monkeypatch
) -> None:
    contract = _closure_contract()
    contract["prod_inventory"]["agents"] = ["surgical-fixer"]
    body = 'Agent(subagent_type="surgical-fixer", prompt="repair")\npython3 scripts/run.py\n'
    _write_closure_fixture(tmp_path, body)
    (tmp_path / "agents" / "worker.md").unlink()
    (tmp_path / "agents" / "surgical-fixer.md").write_text("repair\n", encoding="utf-8")
    monkeypatch.setattr(release_surface, "release_contract", lambda: contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    graph = release_surface.build_prod_dependency_graph(
        tmp_path, {"skills/z-plan/SKILL.md": body}
    )

    assert graph.ok
    assert {
        (edge.source_path, edge.target, edge.reference_kind, edge.classification)
        for edge in graph.edges
    } == {
        ("mcp-tool:z_plan", "skills/z-plan/SKILL.md", "mcp", "skill"),
        ("skills/z-plan/SKILL.md", "agents/surgical-fixer.md", "agent", "literal"),
        ("skills/z-plan/SKILL.md", "scripts/run.py", "script", "literal"),
    }


def test_prod_dependency_graph_extracts_variable_and_absolute_script_paths_only(
    tmp_path: Path, monkeypatch
) -> None:
    contract = _closure_contract()
    contract["prod_inventory"]["scripts_backends"] = [
        "scripts/absolute.py",
        "scripts/plugin.py",
        "scripts/pwd.sh",
        "scripts/run.py",
    ]
    body = (
        "python3 ${PLUGIN_ROOT}/scripts/plugin.py\n"
        "bash ${PWD}/scripts/pwd.sh\n"
        "python3 /opt/z-harness/scripts/absolute.py\n"
        "python3 scripts/run.py\n"
        "https://example.invalid/scripts/not-a-command.py\n"
        "relative/scripts/not-rooted.py\n"
        "scripts/not-a-script.py.bak\n"
    )
    _write_closure_fixture(tmp_path, body)
    for name in ("absolute.py", "plugin.py", "pwd.sh"):
        (tmp_path / "scripts" / name).write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(release_surface, "release_contract", lambda: contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    graph = release_surface.build_prod_dependency_graph(
        tmp_path,
        {"skills/z-plan/SKILL.md": body},
    )

    assert graph.ok
    assert {
        edge.target for edge in graph.edges if edge.reference_kind == "script"
    } == {
        "scripts/absolute.py",
        "scripts/plugin.py",
        "scripts/pwd.sh",
        "scripts/run.py",
    }


def test_prod_dependency_graph_reports_extra_supplied_and_shipped_skills(
    tmp_path: Path, monkeypatch
) -> None:
    _write_closure_fixture(tmp_path, "python3 scripts/run.py\n")
    _write_skill(tmp_path, "z-shipped-extra")
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    graph = release_surface.build_prod_dependency_graph(
        tmp_path,
        {
            "skills/z-plan/SKILL.md": "python3 scripts/run.py\n",
            "skills/z-supplied-extra/SKILL.md": "body\n",
        },
    )

    assert graph.errors == (
        "extra: <inventory> -> skills/z-shipped-extra/SKILL.md: "
        "skill source is outside frozen prod inventory",
        "extra: <inventory> -> skills/z-supplied-extra/SKILL.md: "
        "skill source is outside frozen prod inventory",
    )
    assert {
        "skills/z-shipped-extra/SKILL.md",
        "skills/z-supplied-extra/SKILL.md",
    } <= set(graph.nodes)


def test_export_wrapper_preserves_extra_shipped_skill_for_validation(
    tmp_path: Path, monkeypatch
) -> None:
    _write_closure_fixture(tmp_path, "python3 scripts/run.py\n")
    _write_skill(tmp_path, "z-extra")
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    graph = build_prod_dependency_graph(tmp_path)

    assert graph.errors == (
        "extra: <inventory> -> skills/z-extra/SKILL.md: "
        "skill source is outside frozen prod inventory",
    )
    assert "skills/z-extra/SKILL.md" in graph.nodes


def test_prod_dependency_graph_reports_extra_shipped_agent(
    tmp_path: Path, monkeypatch
) -> None:
    _write_closure_fixture(tmp_path, "python3 scripts/run.py\n")
    (tmp_path / "agents" / "dev-agent.md").write_text("dev\n", encoding="utf-8")
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())

    graph = build_prod_dependency_graph(tmp_path)

    assert graph.errors == (
        "extra: <inventory> -> agents/dev-agent.md: "
        "agent source is outside frozen prod inventory",
    )


def test_prod_dependency_graph_reports_stable_fail_closed_errors_without_denylists(
    tmp_path: Path, monkeypatch
) -> None:
    body = (
        "Agent(subagent_type=\"worker\", prompt=\"work\")\n"
        "Agent(subagent_type=\"dev-agent\", prompt=\"work\")\n"
        "bash scripts/missing.sh\n"
    )
    _write_closure_fixture(tmp_path, body)
    (tmp_path / "agents" / "dev-agent.md").write_text("dev\n", encoding="utf-8")
    exceptions = (
        release_surface.DynamicDependencyException(
            "skills/z-plan/SKILL.md",
            "agent",
            "worker",
            "host_builtin_agent",
            "host-agent:worker",
        ),
        release_surface.DynamicDependencyException(
            "skills/z-plan/SKILL.md",
            "agent",
            "unused",
            "host_builtin_agent",
            "host-agent:unused",
        ),
    )
    monkeypatch.setattr(release_surface, "release_contract", _closure_contract)
    monkeypatch.setattr(
        release_surface,
        "path_excluded_from_prod",
        lambda _path: pytest.fail("dependency closure consulted a packaging denylist"),
    )
    monkeypatch.setattr(
        release_surface,
        "reviewed_dynamic_dependencies",
        lambda: exceptions,
    )

    graph = release_surface.build_prod_dependency_graph(
        tmp_path,
        {"skills/z-plan/SKILL.md": body},
    )

    assert not graph.ok
    assert graph.errors == tuple(sorted(graph.errors))
    assert graph.errors == (
        "ambiguous: skills/z-plan/SKILL.md -> agents/worker.md: "
        "literal file target conflicts with reviewed dynamic exception",
        "extra: <inventory> -> agents/dev-agent.md: "
        "agent source is outside frozen prod inventory",
        "extra: skills/z-plan/SKILL.md -> agent:unused: "
        "reviewed dynamic exception has no matching literal reference",
        "missing: skills/z-plan/SKILL.md -> scripts/missing.sh: target does not exist",
        "surface-incompatible: skills/z-plan/SKILL.md -> agents/dev-agent.md: "
        "target is outside frozen prod inventory",
    )


def test_installed_default_export_surface_is_prod_and_dev_override_remains(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with patch("z_harness_cli.release_surface._module_in_source_checkout", return_value=False), patch(
        "z_harness_cli.commands.export._repo_root", return_value=project_dir
    ), patch(
        "z_harness_cli.adapters.registry.select", return_value=(_FakeAdapter(), MagicMock(installed=True))
    ):
        prod_out = project_dir / "prod-export"
        result = runner.invoke(app, ["export", "--host", "codex", "--out", str(prod_out), "--force"])
        assert result.exit_code == 0, result.output
        assert (prod_out / "surface.txt").read_text(encoding="utf-8") == "prod"

        dev_out = project_dir / "dev-export"
        result = runner.invoke(
            app,
            ["export", "--host", "codex", "--surface", "dev", "--out", str(dev_out), "--force"],
        )
        assert result.exit_code == 0, result.output
        assert (dev_out / "surface.txt").read_text(encoding="utf-8") == "dev"


def test_prod_artifact_audit_rejects_manifest_excluded_local_paths() -> None:
    listing = [
        "./skills/z-plan/SKILL.md",
        "./scripts/hermes/so_mcp.py",
        "./scripts/notify-discord.sh",
        "./exports/pi/prompts/z-plan.md",
    ]
    assert release_surface.first_prod_artifact_violation(listing) == "scripts/hermes/so_mcp.py"
    assert release_surface.path_excluded_from_prod("scripts/notify-discord.sh")
    assert release_surface.path_excluded_from_prod("exports/pi/prompts/z-plan.md")
    assert release_surface.path_excluded_from_prod("hermes-so-watchdog/handoff.json")
    for path in _HIDDEN_SURFACE_ONLY_PATHS:
        assert release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) == path
    for path in _HIDDEN_SURFACE_PATTERN_EXAMPLES:
        assert release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) == path
    for path in _PROD_APPROVED_DOC_SCHEMA_PATHS:
        assert not release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) is None


def test_prod_manifest_exclusions_cover_tar_audit_and_stage_patterns() -> None:
    tar_args = set(release_surface.tar_exclude_args("prod"))
    for pattern in release_surface.prod_excluded_paths():
        assert f"--exclude=./{pattern.removeprefix('./').rstrip('/')}" in tar_args

    assert release_surface.path_excluded_from_prod("scripts/__pycache__/axiom-store.cpython-311.pyc")
    assert release_surface.path_excluded_from_prod("scripts/__pycache__/hermes-execute.cpython-311.pyc")
    assert "--exclude=./*/__pycache__" in tar_args


def test_prod_tarball_audit_requires_codex_manifest(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    (payload / "skills" / "z-plan").mkdir(parents=True)
    (payload / "skills" / "z-plan" / "SKILL.md").write_text("name: z-plan\n", encoding="utf-8")
    tarball = tmp_path / "payload.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(payload / "skills", arcname="skills")

    result = subprocess.run(
        ["/bin/bash", str(Path(__file__).parent.parent / "scripts" / "audit-tarball.sh"), str(tarball)],
        env={**os.environ, "Z_HARNESS_RELEASE_SURFACE": "prod"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".codex-plugin/plugin.json" in result.stdout


def _load_release_stager():
    spec = importlib.util.spec_from_file_location(
        "stage_release_surface",
        Path(__file__).parent.parent / "scripts" / "stage-release-surface.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_positive_inputs(source: Path, dest: Path, paths: tuple[str, ...]) -> None:
    for relative in paths:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)


def _required_stage_sources(module, contract) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *module._required_release_paths(contract),
                *contract["generation_inputs"],
            }
        )
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_stage_release_surface_is_positive_tracked_and_archive_reproducible(tmp_path: Path) -> None:
    module = _load_release_stager()
    repo_root = Path(__file__).parent.parent
    required = _required_stage_sources(module, release_surface.release_contract())
    archive_source = tmp_path / "archive-source"
    _copy_positive_inputs(repo_root, archive_source, required)
    subprocess.run(["git", "init", "-q", str(archive_source)], check=True)
    subprocess.run(["git", "-C", str(archive_source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(archive_source),
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=release-test@example.invalid",
            "commit",
            "-qm",
            "candidate",
        ],
        check=True,
    )
    archive_bytes = subprocess.run(
        ["git", "-C", str(archive_source), "archive", "HEAD"],
        check=True,
        capture_output=True,
    ).stdout
    ancestor_repo = tmp_path / "ancestor-worktree"
    archive_root = ancestor_repo / "extracted-candidate"
    subprocess.run(["git", "init", "-q", str(ancestor_repo)], check=True)
    archive_root.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        archive.extractall(archive_root)

    ambient_paths = ("untracked-secret.txt", ".codex-plugin/plugin.json", "personas/retired.md")
    for relative in ambient_paths:
        target = archive_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ambient sentinel\n", encoding="utf-8")

    checkout_stage = tmp_path / "checkout-stage"
    archive_stage = tmp_path / "archive-stage"
    kwargs = {
        "candidate_version": "0.9.0-beta.2",
        "candidate_commit": "0123456789abcdef0123456789abcdef01234567",
    }
    module.stage_release_surface(archive_source, checkout_stage, **kwargs)
    module.stage_release_surface(archive_root, archive_stage, **kwargs)

    assert module._tracked_paths(archive_root) is None
    assert _tree_snapshot(checkout_stage) == _tree_snapshot(archive_stage)
    status_command = Path("scripts/orchestration-status.py")
    assert (checkout_stage / status_command).read_bytes() == (
        repo_root / status_command
    ).read_bytes()
    assert (archive_stage / status_command).read_bytes() == (
        repo_root / status_command
    ).read_bytes()
    assert not (checkout_stage / "untracked-secret.txt").exists()
    assert not (checkout_stage / "personas").exists()
    assert not (checkout_stage / "_fragments").exists()
    assert not (checkout_stage / "scripts" / "emit-hermes-marker.sh").exists()
    staged_skills = sorted(checkout_stage.glob("skills/*/SKILL.md"))
    assert staged_skills
    assert all(
        "<!-- include:" not in path.read_text(encoding="utf-8")
        for path in staged_skills
    )
    assert "## Shared surface mapping contract" in (
        checkout_stage / "skills" / "z-explain" / "SKILL.md"
    ).read_text(encoding="utf-8")
    staged_graph = build_prod_dependency_graph(checkout_stage)
    assert staged_graph.ok, staged_graph.errors
    closure = release_surface.verify_prod_closure(checkout_stage)
    assert closure.ok, closure.errors
    assert closure.dimensions == (
        "skill-script",
        "skill-agent",
        "mcp-handler",
        "export",
        "optional-feature",
        "memory",
        "provider-role",
    )
    assert closure.provider_roles == (
        "consultant_primary",
        "consultant_secondary",
        "reviewer",
    )
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "z_harness_cli.release_surface",
            "verify-closure",
            "--root",
            str(checkout_stage),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert command.returncode == 0, command.stderr or command.stdout
    assert json.loads(command.stdout)["ok"] is True
    manifest = json.loads((checkout_stage / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["version"] == kwargs["candidate_version"]
    assert manifest["candidate_commit"] == kwargs["candidate_commit"]
    staged_config = tomllib.loads((checkout_stage / "pyproject.toml").read_text())
    assert staged_config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"][
        ".codex-plugin"
    ] == ".codex-plugin"

    (checkout_stage / "scripts" / "run-memory-review.sh").unlink()
    broken_closure = release_surface.verify_prod_closure(checkout_stage)
    assert not broken_closure.ok
    assert any(
        error == "missing: <inventory> -> scripts/run-memory-review.sh: target does not exist"
        for error in broken_closure.errors
    )


def test_stage_release_surface_fails_on_missing_untracked_or_unclassified_input(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_release_stager()
    repo_root = Path(__file__).parent.parent
    required = _required_stage_sources(module, release_surface.release_contract())
    archive_root = tmp_path / "archive"
    _copy_positive_inputs(repo_root, archive_root, required)
    kwargs = {"candidate_version": "0.9.0-beta.2", "candidate_commit": "a" * 40}

    (archive_root / "README.md").unlink()
    with pytest.raises(FileNotFoundError, match="missing required release input: README.md"):
        module.stage_release_surface(archive_root, tmp_path / "missing-stage", **kwargs)

    shutil.copy2(repo_root / "README.md", archive_root / "README.md")
    subprocess.run(["git", "init", "-q", str(archive_root)], check=True)
    subprocess.run(["git", "-C", str(archive_root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(archive_root), "rm", "--cached", "README.md"],
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="required release input is not tracked: README.md"):
        module.stage_release_surface(archive_root, tmp_path / "untracked-stage", **kwargs)

    contract = release_surface.release_contract()
    contract["prod_inventory"]["generated_requirements"].append("future-required.txt")
    monkeypatch.setattr(module.release_surface, "release_contract", lambda: contract)
    with pytest.raises(ValueError, match="unclassified required path: future-required.txt"):
        module.stage_release_surface(archive_root, tmp_path / "unclassified-stage", **kwargs)


def test_stage_skill_generation_fails_closed_for_invalid_include_graphs(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_release_stager()
    skill = tmp_path / "skills" / "z-plan" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    fragments = tmp_path / "_fragments"
    fragments.mkdir()
    first = "_fragments/first.md"
    second = "_fragments/second.md"

    skill.write_text("<!-- include: _fragments/undeclared.md -->\n", encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared release include"):
        module._render_staged_skill(skill, tmp_path, allowed=frozenset({first}), tracked=None)

    skill.write_text(f"<!-- include: {first} -->\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing release generation input"):
        module._render_staged_skill(skill, tmp_path, allowed=frozenset({first}), tracked=None)

    (tmp_path / first).write_text("fragment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="release generation input is not tracked"):
        module._render_staged_skill(skill, tmp_path, allowed=frozenset({first}), tracked=set())

    (tmp_path / first).write_text(f"<!-- include: {second} -->\n", encoding="utf-8")
    (tmp_path / second).write_text(f"<!-- include: {first} -->\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"circular release include: .*first.*second.*first"):
        module._render_staged_skill(
            skill,
            tmp_path,
            allowed=frozenset({first, second}),
            tracked=None,
        )

    (tmp_path / first).write_text("expanded\n", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "expand_includes",
        lambda _body, _root: f"<!-- include: {first} -->\n",
    )
    with pytest.raises(ValueError, match="unresolved include marker"):
        module._render_staged_skill(skill, tmp_path, allowed=frozenset({first}), tracked=None)


def test_wheel_packages_stage_generated_codex_metadata_without_retired_personas() -> None:
    config = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    wheel_config = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    force_include = wheel_config["force-include"]

    assert ".codex-plugin" not in force_include
    assert "personas" not in force_include
    assert "_fragments" not in force_include
