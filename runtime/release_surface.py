"""Canonical pre-1.0-beta release contract for public runtime consumers.

The source tree intentionally keeps development, research, Hermes/Discord/tmux,
and generated mirror resources. Public release consumers must opt into this
positive, default-deny contract instead of carrying hidden-command denylists.

``release_contract`` is the machine-readable C1 contract. It deliberately does
not select a version, tag, source identity, or artifact identity; later release
clusters bind and prove those values against ``clean_candidate_requirements``.

The C3 production graph starts from that positive inventory and derives literal
skill-to-script and skill-to-agent edges. Only source-specific reviewed dynamic
records may resolve dependencies without a prod file.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import json
import os
import re
import subprocess
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

Surface = Literal["dev", "prod"]

_PROD_VISIBLE_SKILLS = frozenset(
    {
        "z-amend",
        "z-audit",
        "z-audit-plan",
        "z-audit-plan-style",
        "z-brainstorm",
        "z-context-budget",
        "z-debt",
        "z-debug",
        "z-doc-rationale",
        "z-execute",
        "z-explain",
        "z-export",
        "z-fix",
        "z-followup-confirm",
        "z-followup-dismiss",
        "z-followup-list",
        "z-followup-next",
        "z-followup-refresh",
        "z-followup-status",
        "z-git-guardrails",
        "z-grill",
        "z-handoff",
        "z-improve",
        "z-init-docs",
        "z-learn",
        "z-maintain-docs",
        "z-mr-review",
        "z-plan",
        "z-plan-split",
        "z-reconcile",
        "z-report",
        "z-resume",
        "z-review-all",
        "z-setup",
        "z-sharpen",
        "z-stats",
        "z-style-init",
        "z-suggest-memory",
        "z-test",
        "z-test-prune",
        "z-update",
    }
)

_DEV_ONLY_SKILLS = frozenset(
    {
        "z-attend",
        "z-explore",
        "z-map",
        "z-overnight",
        "z-research",
    }
)
_DEV_ONLY_SKILL_PATTERNS = ("z-axiom-*",)

_PROD_VISIBLE_AGENTS = frozenset(
    {
        "artifact-scout",
        "auditor",
        "bisect-isolator",
        "cluster-planner",
        "complexity-classifier",
        "consultant-primary",
        "consultant-secondary",
        "context-curator",
        "doc-fetcher",
        "doc-updater",
        "explore",
        "external-lookup",
        "ideator-clusterer",
        "implementer",
        "intent-classifier",
        "mr-reviewer",
        "plan-style-reviewer",
        "planning-router",
        "pre-reviewer",
        "remote-runner",
        "report-synth",
        "resolver",
        "resume-cluster",
        "review-agent",
        "reviewer",
        "scope-extractor",
        "scope-probe",
        "scope-reconciler-audit",
        "scope-reconciler-brainstorm",
        "self-reviewer",
        "spec-precheck",
        "surgical-fixer",
        "task-tree-generator",
        "tier1-doc-updater",
    }
)
_DEV_ONLY_AGENTS = frozenset({"axiom-extractor", "research-judge"})

_PROD_VISIBLE_MCP_TOOLS = frozenset(
    {tool.replace("-", "_") for tool in _PROD_VISIBLE_SKILLS}
    | {
        "z_detect",
        "z_subagent_dispatch",
    }
)
_DEV_ONLY_MCP_TOOLS = frozenset(
    {
        "z_attend",
        "z_explore",
        "z_map",
        "z_overnight",
        "z_research",
        "z_axiom_approve",
        "z_axiom_edit",
        "z_axiom_list",
        "z_axiom_reject",
        "z_axiom_scan",
    }
)

# Hosts that may be explicitly exported in a public release. T002 narrows public
# setup/help defaults further; this list only classifies export consumers.
_PROD_EXPORT_TARGETS = frozenset(
    {"antigravity", "claude", "cline", "codex", "copilot", "cursor", "kiro", "omp", "pi", "windsurf"}
)
_RUNTIME_DRIVER_EXPORT_TARGETS = frozenset({"pi", "windsurf", "kiro", "cline", "copilot"})


# Public release defaults are intentionally narrower than the complete set of
# manifest-approved explicit export targets. Installed CLI/setup/launch/export
# defaults should present the release product: Claude plugin install, OMP
# package/export, and Codex plugin install. Source checkouts can still explicitly
# exercise dev/advanced hosts.
_PUBLIC_RELEASE_HOSTS = ("claude", "omp", "codex")
_DEV_SETUP_TARGETS = ("claude", "omp", "pi", "cursor", "codex")
_PROD_PLUGIN_INSTALL_TARGETS = frozenset({"claude", "codex"})
_DEV_PLUGIN_INSTALL_TARGETS = frozenset({"claude", "codex"})

_RELEASE_TRAIN = {
    "channel": "pre-1.0-beta",
    "stable_1x_compatibility": False,
    "version": None,
    "tag": None,
}

_PUBLIC_HOST_CLAIMS = {
    "claude": {
        "tier": "native",
        "status": "primary",
        "evidence": "blocking_clean_plugin",
    },
    "cli": {
        "tier": "supported",
        "status": "release",
        "scope": ["bootstrap", "install", "update"],
    },
    "codex": {
        "tier": "partial",
        "status": "preview",
        "evidence": "blocking_clean_plugin",
    },
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
    "windsurf": {"tier": "export_only", "status": "not_release_default"},
}

_CLEAN_CANDIDATE_REQUIREMENTS = {
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

# These are artifact units, not directory ownership shortcuts. A new top-level
# script, runtime module, document, or schema remains unowned until this
# contract names it (or a later release-readiness decision promotes its unit).
_PROD_SCRIPT_PATHS = frozenset(
    {
        "scripts/active-plan-registry.py",
        "scripts/amend-gate-decision.py",
        "scripts/amendment-brief.py",
        "scripts/append-tier2-context.py",
        "scripts/artifact-scout-inventory.py",
        "scripts/audit-tarball.sh",
        "scripts/audit-preview-misses.sh",
        "scripts/audit-scope-probe.sh",
        "scripts/block-dangerous-git.sh",
        "scripts/block-shared-tree-edit.sh",
        "scripts/bundle-plugin.sh",
        "scripts/capture-release-host-evidence.py",
        "scripts/check-compaction.sh",
        "scripts/check-pi-auth.sh",
        "scripts/check-timeout.sh",
        "scripts/checkpoint-seam.sh",
        "scripts/changelog-from-commit.sh",
        "scripts/config.py",
        "scripts/config.sh",
        "scripts/context-budget.py",
        "scripts/curl-install.sh",
        "scripts/detect-host.sh",
        "scripts/discover-providers.py",
        "scripts/emit-hermes-marker.sh",
        "scripts/estimate-tokens.py",
        "scripts/extract-dismissals.py",
        "scripts/followup-view-lookup.py",
        "scripts/followup_common.py",
        "scripts/generate-exports.py",
        "scripts/generate-workstreams.py",
        "scripts/improve-nudge.sh",
        "scripts/install-changelog-hook.sh",
        "scripts/install-version-hook.sh",
        "scripts/intent-dispatch-preflight.py",
        "scripts/intent-schema.py",
        "scripts/log-decision.sh",
        "scripts/log-event.sh",
        "scripts/log-execute-efficiency-event.py",
        "scripts/log-phase.sh",
        "scripts/log-providers.sh",
        "scripts/log-subagent.sh",
        "scripts/lint-frontmatter.sh",
        "scripts/migrate-plan-layout.sh",
        "scripts/normalize-task-state.sh",
        "scripts/omp-consult.sh",
        "scripts/omp-prod-export-smoke.py",
        "scripts/parse-followups-block.py",
        "scripts/plan-claim.sh",
        "scripts/plan-path.sh",
        "scripts/preflight.sh",
        "scripts/pre-run-cost-gate.sh",
        "scripts/propose-prefs.py",
        "scripts/reconcile-tier1-staged.py",
        "scripts/reconcile.py",
        "scripts/regenerate-memories-flat.py",
        "scripts/release-dry-run.sh",
        "scripts/render-cost-summary.py",
        "scripts/render-run-brief.py",
        "scripts/report-context.py",
        "scripts/resolve-kernel.sh",
        "scripts/resolve-provider.py",
        "scripts/resolve-provider.sh",
        "scripts/resume-context.py",
        "scripts/review-finding-state.py",
        "scripts/run-brief.sh",
        "scripts/run-memory-review.sh",
        "scripts/session-helpers.sh",
        "scripts/setup.py",
        "scripts/setup.sh",
        "scripts/sink-add.sh",
        "scripts/sink-audit-validate.py",
        "scripts/sink-auto-close-check.py",
        "scripts/sink-claim.sh",
        "scripts/sink-lock.sh",
        "scripts/sink-status-set.sh",
        "scripts/sink-view-rebuild.sh",
        "scripts/stage-release-surface.py",
        "scripts/stats.py",
        "scripts/supervised-run.sh",
        "scripts/surface-map.py",
        "scripts/surface-shortcut.sh",
        "scripts/sync-version.sh",
        "scripts/version.sh",
        "scripts/worktree-cleanup.sh",
        "scripts/write-clear-checkpoint.sh",
        "scripts/write-handoff.sh",
        "scripts/z-preflight.sh",
        "scripts/z-teardown.sh",
        "scripts/zplan-cost-gate-runtime.sh",
    }
)

# These checked-in fragments are compiler inputs for canonical staging. They
# are deliberately outside ``prod_inventory`` because no source fragment may
# appear in an assembled or installed production payload.
_PROD_GENERATION_INPUT_PATHS = frozenset(
    {
        "_fragments/run-brief-finalize.md",
        "_fragments/run-brief-halt-finalize-execute.md",
        "_fragments/surface-mapping.md",
        "_fragments/zplan-cost-gate-reference.md",
    }
)
_PROD_BACKEND_PATHS = frozenset(
    {
        "runtime/__init__.py",
        "runtime/compat.py",
        "runtime/contract/TEMPLATE-command.md",
        "runtime/dispatch/__init__.py",
        "runtime/dispatch/dispatcher.py",
        "runtime/dispatch/driver.py",
        "runtime/dispatch/env.py",
        "runtime/dispatch/result.py",
        "runtime/dispatch/timeout.py",
        "runtime/drivers/__init__.py",
        "runtime/drivers/_export_utils.py",
        "runtime/drivers/antigravity/README.md",
        "runtime/drivers/antigravity/__init__.py",
        "runtime/drivers/antigravity/auth.py",
        "runtime/drivers/antigravity/driver.py",
        "runtime/drivers/antigravity/export.py",
        "runtime/drivers/antigravity/host_driver_shim.py",
        "runtime/drivers/antigravity/mcp_config.py",
        "runtime/drivers/antigravity/preflight.py",
        "runtime/drivers/antigravity/stream_parser.py",
        "runtime/drivers/claude/__init__.py",
        "runtime/drivers/claude/env_hygiene.py",
        "runtime/drivers/claude/self_host_driver.py",
        "runtime/drivers/claude/session.py",
        "runtime/drivers/claude/subprocess_driver.py",
        "runtime/drivers/cline/__init__.py",
        "runtime/drivers/cline/export.py",
        "runtime/drivers/codex/__init__.py",
        "runtime/drivers/codex/agent_export.py",
        "runtime/drivers/codex/auth.py",
        "runtime/drivers/codex/driver.py",
        "runtime/drivers/codex/export.py",
        "runtime/drivers/codex/mcp.py",
        "runtime/drivers/codex/probe.py",
        "runtime/drivers/codex/stream.py",
        "runtime/drivers/copilot/__init__.py",
        "runtime/drivers/copilot/export.py",
        "runtime/drivers/cursor/__init__.py",
        "runtime/drivers/cursor/cli_driver.py",
        "runtime/drivers/cursor/export.py",
        "runtime/drivers/cursor/mcp_config.py",
        "runtime/drivers/cursor/sdk_driver.py",
        "runtime/drivers/cursor/session.py",
        "runtime/drivers/kiro/__init__.py",
        "runtime/drivers/kiro/export.py",
        "runtime/drivers/omp/__init__.py",
        "runtime/drivers/omp/export.py",
        "runtime/drivers/omp/subprocess_driver.py",
        "runtime/drivers/pi/__init__.py",
        "runtime/drivers/pi/export.py",
        "runtime/drivers/windsurf/__init__.py",
        "runtime/drivers/windsurf/export.py",
        "runtime/release_surface.py",
        "runtime/validate.py",
        "z_harness_cli/__init__.py",
        "z_harness_cli/__main__.py",
        "z_harness_cli/adapters/__init__.py",
        "z_harness_cli/adapters/antigravity.py",
        "z_harness_cli/adapters/base.py",
        "z_harness_cli/adapters/claude.py",
        "z_harness_cli/adapters/codex.py",
        "z_harness_cli/adapters/codex_parity_gate.py",
        "z_harness_cli/adapters/cursor.py",
        "z_harness_cli/adapters/omp.py",
        "z_harness_cli/adapters/omp_parity_gate.py",
        "z_harness_cli/adapters/registry.py",
        "z_harness_cli/commands/__init__.py",
        "z_harness_cli/commands/doctor.py",
        "z_harness_cli/commands/export.py",
        "z_harness_cli/commands/install.py",
        "z_harness_cli/commands/launch.py",
        "z_harness_cli/commands/serve.py",
        "z_harness_cli/commands/setup.py",
        "z_harness_cli/commands/update.py",
        "z_harness_cli/env_bundle.py",
        "z_harness_cli/inject_safety.py",
        "z_harness_cli/mcp/__init__.py",
        "z_harness_cli/mcp/server.py",
        "z_harness_cli/mcp_prod_tool_list_smoke.py",
        "z_harness_cli/pty_launch.py",
        "z_harness_cli/release.py",
        "z_harness_cli/release_host_evidence.py",
        "z_harness_cli/release_surface.py",
    }
)
_PROD_SCHEMA_PATHS = frozenset(
    {
        "docs/schemas/audit-evidence.schema.json",
        "docs/schemas/decision-event.schema.json",
        "docs/schemas/error_points.schema.json",
        "docs/schemas/followup-entry.schema.json",
        "docs/schemas/handoff.schema.json",
        "docs/schemas/invariant.schema.json",
        "runtime/contract/agent.schema.json",
        "runtime/contract/command.schema.json",
        "runtime/contract/event.schema.json",
        "runtime/contract/provider.schema.json",
        "runtime/contract/skill.schema.json",
    }
)
_PROD_PUBLIC_DOCUMENT_PATHS = frozenset(
    {
        "CAPABILITIES.md",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "docs/human/INSTALL.md",
        "docs/human/MULTI-IDE.md",
        "docs/human/PROVIDERS.md",
        "docs/human/SETUP.md",
        "docs/human/capabilities-matrix.md",
        "docs/human/limitations.md",
        "docs/human/multi-ide-exports.md",
        "docs/human/pi-export.md",
        "docs/human/pi-setup.md",
        "docs/human/z-update.md",
        "docs/llm/capabilities-matrix.json",
        "docs/llm/multi-ide-exports.json",
        "docs/llm/pi-export.json",
        "docs/llm/z-update.json",
    }
)
_PROD_GENERATED_REQUIREMENT_PATHS = frozenset(
    {
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        "VERSION",
        "install.sh",
        "plugin.json",
        "pyproject.toml",
    }
)

_PROD_SKILL_PATHS = frozenset(f"skills/{skill_id}/SKILL.md" for skill_id in _PROD_VISIBLE_SKILLS)
_PROD_AGENT_PATHS = frozenset(f"agents/{agent_id}.md" for agent_id in _PROD_VISIBLE_AGENTS)
# Path prefixes/globs are relative to the repository or artifact root. These are
# physically excluded from prod tarballs/staging and rejected by release audits.
_PROD_EXCLUDED_PATHS = (
    "exports/",
    "prompts/",
    "temp/",
    "z-harness/",
    "archive/",
    "hermes-*/",
    "improvements/",
    "research/",
    ".agent/",
    ".pi/",
    ".omp/",
    ".local/",
    ".pytest_cache/",
    ".claude/worktrees/",
    ".antigravitycli/",
    ".venv/",
    "dist/",
    "tests/",
    "runtime/tests/",
    "runtime/watchdog/",
    "runtime/drivers/antigravity/tests/",
    ".z-harness/",
    "__pycache__/",
    "*/__pycache__/",
    "providers.json",
    "*/providers.json",
    "skills/z-attend/",
    "skills/z-explore/",
    "skills/z-map/",
    "skills/z-overnight/",
    "skills/z-research/",
    "skills/z-axiom-*",
    "agents/axiom-extractor.md",
    "agents/research-judge.md",
    "scripts/axiom-extract.py",
    "scripts/axiom-store.py",
    "scripts/overnight-preflight.sh",
    "scripts/chain-runner.sh",
    "scripts/morning-report.py",
    "scripts/hermes/",
    "scripts/hermes-execute.py",
    "scripts/so-mcp-server.py",
    "scripts/pi-mcp-server.py",
    "scripts/notify-discord.sh",
    "scripts/test_notify_discord.bats",
    "scripts/notify-watchdog.sh",
    "scripts/test_notify_watchdog.sh",
    "scripts/hang-check.sh",
    "scripts/schedule-hang-check.sh",
    # Hidden-surface docs/schemas: classify by surface family so new attend,
    # axiom, overnight, or Hermes docs do not silently enter prod artifacts.
    "docs/human/attend*.md",
    "docs/human/axiom*.md",
    "docs/human/overnight*.md",
    "docs/human/hermes*.md",
    "docs/human/review-hermes*.md",
    "docs/human/mcp-server.md",
    "docs/human/INDEX.md",
    "docs/human/watchdog.md",
    "docs/human/scripts.md",
    "docs/llm/attend*.json",
    "docs/llm/axiom*.json",
    "docs/llm/overnight*.json",
    "docs/llm/hermes*.json",
    "docs/llm/review-hermes*.json",
    "docs/schemas/axiom*.schema.json",
)


def _tar_exclude_pattern(pattern: str) -> str:
    return pattern.removeprefix("./").rstrip("/")


_PROD_TAR_EXCLUDES = (".git", *(_tar_exclude_pattern(pattern) for pattern in _PROD_EXCLUDED_PATHS))

_PROD_KINDS = frozenset(
    {
        "agents",
        "export_targets",
        "generated_requirements",
        "mcp_tools",
        "public_documents",
        "schemas",
        "scripts_backends",
        "skills",
    }
)

_SCRIPT_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?:(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*)/"
    r"|/(?:[A-Za-z0-9_.-]+/)*)?"
    r"(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))(?![A-Za-z0-9_.-])"
)
_AGENT_REFERENCE_RE = re.compile(
    r"\bsubagent_type\s*=\s*['\"]([A-Za-z0-9_-]+)['\"]"
)
_DYNAMIC_DEPENDENCY_CLASSIFICATIONS = frozenset(
    {"conditional_runtime", "host_builtin_agent"}
)

_PROD_MCP_FAST_HANDLERS = {
    "z_detect": "_handle_z_detect",
    "z_subagent_dispatch": "_handle_subagent_dispatch",
}


@dataclass(frozen=True, order=True)
class DynamicDependencyException:
    """One reviewed dependency that cannot be resolved to a prod file.

    Attributes:
        source_path: Prod skill path containing the literal reference.
        reference_kind: Literal reference family, currently ``agent`` or
            ``script``.
        reference: Literal identifier found in the skill source.
        classification: Narrow reason this reference has no prod file target.
        target: Stable non-file graph node supplied by the host or runtime.
    """

    source_path: str
    reference_kind: str
    reference: str
    classification: str
    target: str


@dataclass(frozen=True, order=True)
class ProdDependencyEdge:
    """A deterministic dependency edge from a prod skill to its target."""

    source_path: str
    target: str
    reference_kind: str
    classification: str


@dataclass(frozen=True)
class ProdDependencyGraph:
    """Resolved production inventory, dependency edges, and stable errors."""

    nodes: tuple[str, ...]
    edges: tuple[ProdDependencyEdge, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return whether every inventoried node and derived edge resolves."""

        return not self.errors


@dataclass(frozen=True)
class ProdClosureVerification:
    """Stable focused closure-gate result for a staged or installed root."""

    root: str
    dimensions: tuple[str, ...]
    graph_nodes: int
    graph_edges: int
    provider_roles: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return whether every focused production closure dimension passed."""

        return not self.errors


# Host primitives are reviewed per source/reference, rather than globally by
# name, so a new use cannot silently inherit another skill's exception.
_REVIEWED_DYNAMIC_DEPENDENCIES = (
    DynamicDependencyException(
        "skills/z-audit/SKILL.md",
        "agent",
        "orchestrator",
        "host_builtin_agent",
        "host-agent:orchestrator",
    ),
    DynamicDependencyException(
        "skills/z-brainstorm/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
    DynamicDependencyException(
        "skills/z-brainstorm/SKILL.md",
        "agent",
        "general-purpose",
        "host_builtin_agent",
        "host-agent:general-purpose",
    ),
    DynamicDependencyException(
        "skills/z-explain/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
    DynamicDependencyException(
        "skills/z-grill/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
    DynamicDependencyException(
        "skills/z-init-docs/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
    DynamicDependencyException(
        "skills/z-plan/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
    DynamicDependencyException(
        "skills/z-style-init/SKILL.md",
        "agent",
        "general-purpose",
        "host_builtin_agent",
        "host-agent:general-purpose",
    ),
    DynamicDependencyException(
        "skills/z-test-prune/SKILL.md",
        "agent",
        "Explore",
        "host_builtin_agent",
        "host-agent:Explore",
    ),
)


def normalize_surface(surface: str | None) -> Surface:
    value = (surface or "").strip().lower()
    if value in {"prod", "production"}:
        return "prod"
    if value in {"dev", "development"}:
        return "dev"
    raise ValueError("surface must be one of: dev, prod")


def _module_in_source_checkout() -> bool:
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        if (parent / "pyproject.toml").is_file() and (parent / ".git").exists():
            return True
    return False


def default_surface(explicit: str | None = None) -> Surface:
    env_surface = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
    if explicit:
        return normalize_surface(explicit)
    if env_surface:
        return normalize_surface(env_surface)
    return "dev" if _module_in_source_checkout() else "prod"


def is_prod_visible(kind: str, entry_id: str, surface: str | None = None) -> bool:
    if default_surface(surface) == "dev":
        return True
    if kind == "skills":
        if entry_id in _DEV_ONLY_SKILLS or any(fnmatch(entry_id, pat) for pat in _DEV_ONLY_SKILL_PATTERNS):
            return False
        return entry_id in _PROD_VISIBLE_SKILLS
    if kind == "agents":
        if entry_id in _DEV_ONLY_AGENTS:
            return False
        return entry_id in _PROD_VISIBLE_AGENTS
    if kind == "mcp_tools":
        if entry_id in _DEV_ONLY_MCP_TOOLS:
            return False
        return entry_id in _PROD_VISIBLE_MCP_TOOLS
    if kind == "export_targets":
        return entry_id in _PROD_EXPORT_TARGETS
    if kind in {"generated_requirements", "public_documents", "schemas", "scripts_backends"}:
        return prod_owner_for_path(entry_id) == kind
    return False


def filter_ids(kind: str, ids: Iterable[str], surface: str | None = None) -> list[str]:
    return [entry_id for entry_id in ids if is_prod_visible(kind, entry_id, surface)]


def public_release_hosts() -> tuple[str, ...]:
    return _PUBLIC_RELEASE_HOSTS


def setup_target_ids(surface: str | None = None) -> tuple[str, ...]:
    if default_surface(surface) == "prod":
        return _PUBLIC_RELEASE_HOSTS
    return _DEV_SETUP_TARGETS


def explicit_setup_target_ids() -> tuple[str, ...]:
    return _DEV_SETUP_TARGETS


def plugin_install_target_ids(surface: str | None = None) -> frozenset[str]:
    if default_surface(surface) == "prod":
        return _PROD_PLUGIN_INSTALL_TARGETS
    return _DEV_PLUGIN_INSTALL_TARGETS


def prod_skill_ids() -> frozenset[str]:
    return _PROD_VISIBLE_SKILLS

def dev_only_skill_patterns() -> tuple[str, ...]:
    return _DEV_ONLY_SKILL_PATTERNS


def dev_only_skill_ids() -> frozenset[str]:
    return _DEV_ONLY_SKILLS


def dev_only_agent_ids() -> frozenset[str]:
    return _DEV_ONLY_AGENTS


def dev_only_mcp_tool_names() -> frozenset[str]:
    return _DEV_ONLY_MCP_TOOLS


def runtime_driver_export_hosts() -> frozenset[str]:
    return _RUNTIME_DRIVER_EXPORT_TARGETS


def prod_excluded_paths() -> tuple[str, ...]:
    return _PROD_EXCLUDED_PATHS


def prod_owner_for_path(path: str) -> str | None:
    """Return the positive prod owner for one staged artifact path.

    Args:
        path: Repository- or artifact-relative path, optionally prefixed by
            ``./`` and optionally naming a directory entry.

    Returns:
        The owning inventory category, or ``None`` when the path is excluded or
        unclassified. Unknown paths fail closed even below familiar roots.
    """

    normalized = normalize_artifact_path(path)
    if not normalized or path_excluded_from_prod(normalized):
        return None

    if normalized in _PROD_SKILL_PATHS or _is_parent_of_owned_path(normalized, _PROD_SKILL_PATHS):
        return "skills"
    if normalized in _PROD_AGENT_PATHS or _is_parent_of_owned_path(normalized, _PROD_AGENT_PATHS):
        return "agents"

    if normalized in _PROD_SCRIPT_PATHS or _is_parent_of_owned_path(normalized, _PROD_SCRIPT_PATHS):
        return "scripts_backends"
    if normalized in _PROD_SCHEMA_PATHS or _is_parent_of_owned_path(normalized, _PROD_SCHEMA_PATHS):
        return "schemas"
    if normalized in _PROD_PUBLIC_DOCUMENT_PATHS or _is_parent_of_owned_path(
        normalized, _PROD_PUBLIC_DOCUMENT_PATHS
    ):
        return "public_documents"
    if normalized in _PROD_GENERATED_REQUIREMENT_PATHS or _is_parent_of_owned_path(
        normalized, _PROD_GENERATED_REQUIREMENT_PATHS
    ):
        return "generated_requirements"
    if normalized in _PROD_BACKEND_PATHS or _is_parent_of_owned_path(normalized, _PROD_BACKEND_PATHS):
        return "scripts_backends"
    return None


def tar_exclude_args(surface: str | None = None) -> list[str]:
    if default_surface(surface) != "prod":
        return []
    return [f"--exclude=./{pattern}" for pattern in _PROD_TAR_EXCLUDES]


def cleanup_relative_paths_for_id(kind: str, entry_id: str) -> tuple[str, ...]:
    if kind == "skills":
        return (
            f"skills/{entry_id}",
            f"prompts/{entry_id}.md",
            f".cursor/skills/{entry_id}",
            f".cursor/rules/{entry_id}.mdc",
            f".agent/skills/{entry_id}",
            f".agent/workflows/{entry_id}.md",
            f".agent/rules/z-harness-{entry_id}.md",
            f".omp/z-harness/skills/{entry_id}",
            f".omp/z-harness/prompts/{entry_id}.md",
            f".omp/z-harness/rules/{entry_id}.md",
        )
    if kind == "agents":
        return (
            f"prompts/{entry_id}.md",
            f".cursor/rules/{entry_id}.mdc",
            f".agent/rules/z-harness-{entry_id}.md",
            f".omp/z-harness/agents/{entry_id}.md",
        )
    return ()


def normalize_artifact_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_parent_of_owned_path(path: str, owned_paths: frozenset[str]) -> bool:
    directory = path.rstrip("/")
    return any(owned.startswith(directory + "/") for owned in owned_paths)


def path_excluded_from_prod(path: str) -> bool:
    normalized = normalize_artifact_path(path)
    for pattern in _PROD_EXCLUDED_PATHS:
        clean = pattern.removeprefix("./")
        if clean.endswith("/"):
            prefix = clean[:-1]
            if "*" in prefix:
                if fnmatch(normalized, prefix) or fnmatch(normalized, f"{clean}*"):
                    return True
            elif normalized == prefix or normalized.startswith(clean):
                return True
        elif "*" in clean:
            if fnmatch(normalized, clean) or fnmatch(normalized + "/", clean):
                return True
        elif normalized == clean:
            return True
    return False


def first_prod_artifact_violation(paths: Iterable[str]) -> str | None:
    for path in paths:
        normalized = normalize_artifact_path(path)
        if normalized and prod_owner_for_path(normalized) is None:
            return normalized
    return None


def release_contract() -> dict[str, Any]:
    """Return an isolated, JSON-serializable copy of the canonical contract.

    Returns:
        The pre-1.0-beta train, positive prod inventory, experiment exclusions,
        evidence-bounded host claims, and clean-candidate requirements.
    """

    contract = {
        "schema_version": 1,
        "train": _RELEASE_TRAIN,
        "generation_inputs": sorted(_PROD_GENERATION_INPUT_PATHS),
        "prod_inventory": {
            "skills": sorted(_PROD_VISIBLE_SKILLS),
            "agents": sorted(_PROD_VISIBLE_AGENTS),
            "mcp_tools": sorted(_PROD_VISIBLE_MCP_TOOLS),
            "export_targets": sorted(_PROD_EXPORT_TARGETS),
            "scripts_backends": sorted(_PROD_SCRIPT_PATHS | _PROD_BACKEND_PATHS),
            "schemas": sorted(_PROD_SCHEMA_PATHS),
            "public_documents": sorted(_PROD_PUBLIC_DOCUMENT_PATHS),
            "generated_requirements": sorted(_PROD_GENERATED_REQUIREMENT_PATHS),
        },
        "prod_kinds": sorted(_PROD_KINDS),
        "excluded_experiments": {
            "skills": sorted(_DEV_ONLY_SKILLS),
            "skill_patterns": list(_DEV_ONLY_SKILL_PATTERNS),
            "agents": sorted(_DEV_ONLY_AGENTS),
            "paths": list(_PROD_EXCLUDED_PATHS),
        },
        "host_claims": _PUBLIC_HOST_CLAIMS,
        "clean_candidate_requirements": _CLEAN_CANDIDATE_REQUIREMENTS,
    }
    return deepcopy(contract)


def reviewed_dynamic_dependencies() -> tuple[DynamicDependencyException, ...]:
    """Return the immutable reviewed exception set for the prod graph."""

    return _REVIEWED_DYNAMIC_DEPENDENCIES


def prod_mcp_tool_backings(tool_ids: Iterable[str]) -> dict[str, str]:
    """Resolve active prod MCP tools to one skill or reviewed handler.

    Args:
        tool_ids: MCP names selected for public discovery.

    Returns:
        A stable mapping to ``skill:`` or ``handler:`` graph targets.

    Raises:
        ValueError: If a tool is absent from the positive inventory or has no
            prod skill and no narrowly reviewed direct handler.
    """

    backings: dict[str, str] = {}
    errors: list[str] = []
    for tool_id in sorted(set(tool_ids)):
        if tool_id not in _PROD_VISIBLE_MCP_TOOLS:
            errors.append(f"{tool_id}: outside frozen prod MCP inventory")
            continue
        skill_id = tool_id.replace("_", "-")
        if skill_id in _PROD_VISIBLE_SKILLS:
            backings[tool_id] = f"skill:skills/{skill_id}/SKILL.md"
            continue
        handler = _PROD_MCP_FAST_HANDLERS.get(tool_id)
        if handler is None:
            errors.append(f"{tool_id}: no prod skill or reviewed direct handler")
            continue
        backings[tool_id] = f"handler:{handler}"
    if errors:
        raise ValueError("invalid prod MCP closure: " + "; ".join(errors))
    return backings


def _prod_inventory_paths(contract: Mapping[str, Any]) -> frozenset[str]:
    inventory = contract.get("prod_inventory")
    if not isinstance(inventory, Mapping):
        raise ValueError("release contract must define a prod_inventory mapping")

    paths: set[str] = set()
    for skill_id in inventory.get("skills", ()):
        paths.add(f"skills/{skill_id}/SKILL.md")
    for agent_id in inventory.get("agents", ()):
        paths.add(f"agents/{agent_id}.md")
    for kind in ("scripts_backends", "schemas", "public_documents", "generated_requirements"):
        paths.update(str(path) for path in inventory.get(kind, ()))
    return frozenset(paths)


def _literal_skill_references(text: str) -> tuple[tuple[str, str], ...]:
    references = {
        *(("script", match) for match in _SCRIPT_REFERENCE_RE.findall(text)),
        *(("agent", match) for match in _AGENT_REFERENCE_RE.findall(text)),
    }
    return tuple(sorted(references))


def build_prod_dependency_graph(
    repo_root: Path,
    skill_sources: Mapping[str, str],
    *,
    selected_source_paths: Iterable[str] | None = None,
) -> ProdDependencyGraph:
    """Resolve literal prod-skill dependencies against the positive inventory.

    Args:
        repo_root: Candidate repository, staged tree, or installed payload root.
        skill_sources: Mapping of prod ``SKILL.md`` paths to their expanded
            source text.
        selected_source_paths: Explicit skill and agent source selection made
            by a production exporter. When omitted, discover every shipped
            source so staged and installed roots reject extra dependencies.

    Returns:
        A deterministically ordered graph. Errors are path-specific and stable;
        callers decide whether to print them or fail a release gate.

    Raises:
        ValueError: If the frozen release contract has no prod inventory.
    """

    repo_root = Path(repo_root).resolve()
    contract = release_contract()
    inventory_paths = _prod_inventory_paths(contract)
    existing_paths = frozenset(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*")
        if path.is_file()
    )
    exceptions = reviewed_dynamic_dependencies()
    exception_index: dict[tuple[str, str, str], list[DynamicDependencyException]] = {}
    for dependency in exceptions:
        key = (dependency.source_path, dependency.reference_kind, dependency.reference)
        exception_index.setdefault(key, []).append(dependency)

    inventory = contract["prod_inventory"]
    nodes = set(inventory_paths)
    nodes.update(f"mcp-tool:{tool_id}" for tool_id in inventory.get("mcp_tools", ()))
    nodes.update(
        f"export-target:{target_id}"
        for target_id in inventory.get("export_targets", ())
    )
    edges: set[ProdDependencyEdge] = set()
    errors: set[str] = set()
    observed_references: set[tuple[str, str, str]] = set()

    try:
        mcp_backings = prod_mcp_tool_backings(inventory.get("mcp_tools", ()))
    except ValueError as exc:
        errors.add(str(exc))
        mcp_backings = {}
    for tool_id, backing in sorted(mcp_backings.items()):
        target = backing.split(":", 1)[1]
        nodes.add(target)
        edges.add(
            ProdDependencyEdge(
                f"mcp-tool:{tool_id}",
                target,
                "mcp",
                "skill" if backing.startswith("skill:") else "reviewed:fast_handler",
            )
        )

    for path in sorted(inventory_paths):
        if path not in existing_paths:
            errors.add(f"missing: <inventory> -> {path}: target does not exist")

    prod_skill_paths = sorted(
        path for path in inventory_paths if path.startswith("skills/")
    )
    supplied_skill_paths = frozenset(str(path) for path in skill_sources)
    candidate_source_paths = (
        existing_paths
        if selected_source_paths is None
        else frozenset(normalize_artifact_path(path) for path in selected_source_paths)
    )
    shipped_skill_paths = frozenset(
        path
        for path in candidate_source_paths
        if path.startswith("skills/") and path.endswith("/SKILL.md")
    )
    nodes.update(supplied_skill_paths | shipped_skill_paths)
    for source_path in sorted(
        (supplied_skill_paths | shipped_skill_paths) - set(prod_skill_paths)
    ):
        errors.add(
            f"extra: <inventory> -> {source_path}: "
            "skill source is outside frozen prod inventory"
        )

    prod_agent_paths = frozenset(
        path for path in inventory_paths if path.startswith("agents/")
    )
    shipped_agent_paths = frozenset(
        path
        for path in candidate_source_paths
        if path.startswith("agents/") and path.endswith(".md")
    )
    nodes.update(shipped_agent_paths)
    for agent_path in sorted(shipped_agent_paths - prod_agent_paths):
        errors.add(
            f"extra: <inventory> -> {agent_path}: "
            "agent source is outside frozen prod inventory"
        )

    for source_path in prod_skill_paths:
        text = skill_sources.get(source_path)
        if text is None:
            errors.add(
                f"missing: {source_path} -> {source_path}: prod skill source was not enumerated"
            )
            continue

        for reference_kind, reference in _literal_skill_references(text):
            key = (source_path, reference_kind, reference)
            observed_references.add(key)
            matches = exception_index.get(key, [])
            target_path = (
                reference
                if reference_kind == "script"
                else f"agents/{reference}.md"
            )

            if len(matches) > 1:
                errors.add(
                    f"ambiguous: {source_path} -> {target_path}: "
                    "multiple reviewed dynamic exceptions match"
                )
                continue

            if matches:
                dependency = matches[0]
                if target_path in inventory_paths or target_path in existing_paths:
                    errors.add(
                        f"ambiguous: {source_path} -> {target_path}: "
                        "literal file target conflicts with reviewed dynamic exception"
                    )
                    continue
                if dependency.classification not in _DYNAMIC_DEPENDENCY_CLASSIFICATIONS:
                    errors.add(
                        f"surface-incompatible: {source_path} -> {dependency.target}: "
                        f"unreviewed dynamic classification {dependency.classification!r}"
                    )
                    continue
                nodes.add(dependency.target)
                edges.add(
                    ProdDependencyEdge(
                        source_path,
                        dependency.target,
                        reference_kind,
                        f"reviewed:{dependency.classification}",
                    )
                )
                continue

            edges.add(
                ProdDependencyEdge(source_path, target_path, reference_kind, "literal")
            )
            if target_path not in existing_paths:
                errors.add(
                    f"missing: {source_path} -> {target_path}: target does not exist"
                )
            elif target_path not in inventory_paths:
                errors.add(
                    f"surface-incompatible: {source_path} -> {target_path}: "
                    "target is outside frozen prod inventory"
                )

    for dependency in sorted(exceptions):
        key = (dependency.source_path, dependency.reference_kind, dependency.reference)
        if key not in observed_references:
            errors.add(
                f"extra: {dependency.source_path} -> "
                f"{dependency.reference_kind}:{dependency.reference}: "
                "reviewed dynamic exception has no matching literal reference"
            )

    return ProdDependencyGraph(
        nodes=tuple(sorted(nodes)),
        edges=tuple(sorted(edges)),
        errors=tuple(sorted(errors)),
    )


_FOCUSED_CLOSURE_DIMENSIONS = (
    "skill-script",
    "skill-agent",
    "mcp-handler",
    "export",
    "optional-feature",
    "memory",
    "provider-role",
)
_MANDATORY_PROVIDER_ROLES = (
    "consultant_primary",
    "consultant_secondary",
    "reviewer",
)


def _skill_sources_from_root(repo_root: Path) -> dict[str, str]:
    """Read staged skill sources without importing an exporter.

    Args:
        repo_root: Staged or installed production payload root.

    Returns:
        Mapping from artifact-relative skill paths to self-contained source.

    Raises:
        OSError: If an enumerated skill cannot be read.
    """

    return {
        path.relative_to(repo_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "skills").glob("*/SKILL.md"))
    }


def _verify_mcp_handler_targets(repo_root: Path, graph: ProdDependencyGraph) -> list[str]:
    """Return deterministic errors for unresolved reviewed MCP handlers."""

    server_path = repo_root / "z_harness_cli" / "mcp" / "server.py"
    try:
        server_text = server_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"mcp-handler: cannot read {server_path.relative_to(repo_root)}: {exc}"]

    errors: list[str] = []
    for edge in graph.edges:
        if edge.reference_kind != "mcp" or edge.classification != "reviewed:fast_handler":
            continue
        handler = edge.target
        if re.search(rf"^(?:async\s+)?def\s+{re.escape(handler)}\s*\(", server_text, re.MULTILINE):
            continue
        errors.append(f"mcp-handler: {edge.source_path} -> {handler}: handler is not defined")
    return errors


def _verify_export_targets(repo_root: Path, expected_skills: set[str], expected_agents: set[str]) -> list[str]:
    """Run Codex and OMP exporters and compare their resolved graph identities."""

    from runtime.drivers.codex.export import export as export_codex
    from runtime.drivers.omp.export import export as export_omp

    errors: list[str] = []
    previous_surface = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
    os.environ["Z_HARNESS_RELEASE_SURFACE"] = "prod"
    try:
        with tempfile.TemporaryDirectory(prefix="z-harness-closure-export-") as temp_name:
            export_root = Path(temp_name)
            codex_result = export_codex(repo_root, export_root / "codex")
            omp_result = export_omp(repo_root, export_root / "omp")

            codex_skills = {
                path.parent.name
                for path in (export_root / "codex" / "skills").glob("*/SKILL.md")
            }
            codex_agents = {
                path.stem
                for path in (export_root / "codex" / ".codex" / "agents").glob("*.toml")
            }
            omp_package = export_root / "omp" / ".omp" / "z-harness"
            omp_skills = {
                path.parent.name for path in (omp_package / "skills").glob("*/SKILL.md")
            }
            omp_agents = {path.stem for path in (omp_package / "agents").glob("*.md")}

            for host, actual_skills, actual_agents in (
                ("codex", codex_skills, codex_agents),
                ("omp", omp_skills, omp_agents),
            ):
                if actual_skills != expected_skills:
                    errors.append(
                        f"export: {host} skill graph mismatch: "
                        f"missing={sorted(expected_skills - actual_skills)!r} "
                        f"extra={sorted(actual_skills - expected_skills)!r}"
                    )
                if actual_agents != expected_agents:
                    errors.append(
                        f"export: {host} agent graph mismatch: "
                        f"missing={sorted(expected_agents - actual_agents)!r} "
                        f"extra={sorted(actual_agents - expected_agents)!r}"
                    )
            for warning in sorted(codex_result.warnings + omp_result.warnings):
                errors.append(f"export: {warning}")
    except (OSError, ValueError) as exc:
        errors.append(f"export: {exc}")
    finally:
        if previous_surface is None:
            os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
        else:
            os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous_surface
    return errors


def _verify_provider_roles(repo_root: Path) -> tuple[tuple[str, ...], list[str]]:
    """Preflight three distinct non-secret providers in isolated HOME/config."""

    resolver = repo_root / "scripts" / "resolve-provider.py"
    provider = {
        "kind": "cli",
        "command": sys.executable,
        "args_template": [],
        "stdin": True,
        "timeout_s": 30,
        "model_label": "closure-fixture",
    }
    registry = {
        "version": 2,
        "providers": {
            "closure-primary": dict(provider),
            "closure-secondary": dict(provider),
            "closure-reviewer": dict(provider),
        },
        "roles": dict(
            zip(
                _MANDATORY_PROVIDER_ROLES,
                ("closure-primary", "closure-secondary", "closure-reviewer"),
                strict=True,
            )
        ),
        "aliases": {},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="z-harness-closure-provider-") as temp_name:
            isolated_root = Path(temp_name)
            home = isolated_root / "home"
            config_root = isolated_root / "config"
            state_root = isolated_root / "state"
            home.mkdir()
            config_root.mkdir()
            state_root.mkdir()
            registry_path = isolated_root / "providers.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            config_path = isolated_root / "config.toml"
            config_path.write_text(
                'schema_version = 2\n\n[runtime]\nconsult = "on"\n',
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(config_root),
                    "Z_HARNESS_BASE_DIR": str(state_root),
                    "Z_HARNESS_REPO_CONFIG": str(config_path),
                    "Z_HARNESS_REPO_PROVIDERS": str(registry_path),
                    "Z_HARNESS_RELEASE_SURFACE": "prod",
                }
            )
            result = subprocess.run(
                [sys.executable, str(resolver), "--preflight-all"],
                cwd=isolated_root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return (), [f"provider-role: isolated preflight failed: {detail}"]
        payload = json.loads(result.stdout)
        roles = payload.get("roles", {})
        providers = [roles.get(role, {}).get("provider") for role in _MANDATORY_PROVIDER_ROLES]
        if any(not isinstance(provider_name, str) for provider_name in providers):
            return (), ["provider-role: preflight omitted a mandatory role binding"]
        if len(set(providers)) != len(_MANDATORY_PROVIDER_ROLES):
            return (), ["provider-role: mandatory roles did not resolve distinctly"]
        return _MANDATORY_PROVIDER_ROLES, []
    except (OSError, json.JSONDecodeError) as exc:
        return (), [f"provider-role: isolated preflight failed: {exc}"]


def verify_prod_closure(repo_root: Path) -> ProdClosureVerification:
    """Verify every focused C3 closure dimension against one candidate root.

    Args:
        repo_root: Self-contained staged or installed production payload root.

    Returns:
        Stable verification counts, covered dimensions, and sorted errors.
        The helper does not mutate the candidate root.
    """

    repo_root = Path(repo_root).resolve()
    errors: list[str] = []
    skill_sources = _skill_sources_from_root(repo_root)
    graph = build_prod_dependency_graph(repo_root, skill_sources)
    errors.extend(graph.errors)

    fragments = sorted(repo_root.glob("_fragments/**/*"))
    markers = sorted(
        path.relative_to(repo_root).as_posix()
        for path, text in (
            (repo_root / relative, body) for relative, body in skill_sources.items()
        )
        if "<!-- include:" in text
    )
    if fragments:
        errors.append("optional-feature: source-only _fragments payload is present")
    if markers:
        errors.append(f"optional-feature: unresolved skill include markers: {markers!r}")

    errors.extend(_verify_mcp_handler_targets(repo_root, graph))

    contract = release_contract()
    inventory = contract["prod_inventory"]
    expected_skills = set(inventory["skills"])
    expected_agents = set(inventory["agents"])
    if graph.ok:
        errors.extend(_verify_export_targets(repo_root, expected_skills, expected_agents))

    memory_edge = ProdDependencyEdge(
        "skills/z-suggest-memory/SKILL.md",
        "scripts/run-memory-review.sh",
        "script",
        "literal",
    )
    if memory_edge not in graph.edges:
        errors.append("memory: z-suggest-memory does not resolve run-memory-review.sh")

    provider_roles, provider_errors = _verify_provider_roles(repo_root)
    errors.extend(provider_errors)
    return ProdClosureVerification(
        root=str(repo_root),
        dimensions=_FOCUSED_CLOSURE_DIMENSIONS,
        graph_nodes=len(graph.nodes),
        graph_edges=len(graph.edges),
        provider_roles=provider_roles,
        errors=tuple(sorted(set(errors))),
    )


def validate_release_contract(contract: Mapping[str, Any]) -> None:
    """Reject a release contract that contradicts the frozen C1 decisions.

    Args:
        contract: Candidate machine-readable release contract.

    Raises:
        ValueError: If any field differs from the complete canonical contract.
    """

    train = contract.get("train")
    if not isinstance(train, Mapping):
        raise ValueError("release contract must define a train mapping")
    if train.get("channel") != "pre-1.0-beta" or train.get("stable_1x_compatibility") is not False:
        raise ValueError("release train must remain pre-1.0 beta without a stable 1.x promise")
    if train.get("version") is not None or train.get("tag") is not None:
        raise ValueError("release contract must not choose a concrete version or tag")
    canonical = release_contract()
    if contract != canonical:
        raise ValueError("release contract contradicts the complete canonical schema and shape")


def _cmd_tar_excludes(args: argparse.Namespace) -> int:
    for arg in tar_exclude_args(args.surface):
        print(arg)
    return 0


def _cmd_audit_listing(args: argparse.Namespace) -> int:
    violation = first_prod_artifact_violation(sys.stdin.read().splitlines())
    if violation:
        print(f"[release-surface] FAIL: prod-excluded path matched by: {violation}")
        return 1
    return 0


def _cmd_verify_closure(args: argparse.Namespace) -> int:
    """Run the stable staged/installed production closure gate."""

    result = verify_prod_closure(Path(args.root))
    payload = {
        "dimensions": list(result.dimensions),
        "errors": list(result.errors),
        "graph_edges": result.graph_edges,
        "graph_nodes": result.graph_nodes,
        "ok": result.ok,
        "provider_roles": list(result.provider_roles),
        "root": result.root,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    tar_parser = subparsers.add_parser("tar-excludes")
    tar_parser.add_argument("--surface", default=None)
    tar_parser.set_defaults(func=_cmd_tar_excludes)

    audit_parser = subparsers.add_parser("audit-listing")
    audit_parser.add_argument("--surface", default="prod")
    audit_parser.set_defaults(func=_cmd_audit_listing)

    closure_parser = subparsers.add_parser("verify-closure")
    closure_parser.add_argument("--root", required=True)
    closure_parser.set_defaults(func=_cmd_verify_closure)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
