"""Single release-surface contract for public artifacts and runtime consumers.

The source tree intentionally keeps development, research, Hermes/Discord/tmux,
and generated mirror resources. Public release consumers must opt into this
positive contract instead of each carrying its own hidden-command denylist.
"""

from __future__ import annotations

import argparse
import os
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Literal

Surface = Literal["dev", "prod"]

_PROD_VISIBLE_SKILLS = frozenset(
    {
        "z-amend",
        "z-audit",
        "z-audit-plan",
        "z-audit-plan-style",
        "z-brainstorm",
        "z-clear-checkpoint",
        "z-context-budget",
        "z-debt",
        "z-debug",
        "z-do",
        "z-doc-rationale",
        "z-evaluate",
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
        "z-providers-discover",
        "z-reconcile",
        "z-report",
        "z-resume",
        "z-review-all",
        "z-setup",
        "z-sharpen",
        "z-skill-fix",
        "z-stats",
        "z-style-init",
        "z-suggest-memory",
        "z-test",
        "z-test-prune",
        "z-update",
        "z-uplift",
        "z-verify",
        "z-where",
        # Test fixtures and downstream host packages may carry safe local skills.
        # Known z-harness dev/research skills are excluded below; unknown entries
        # stay visible so exporters do not drop host-local resources by accident.
        "z-safe",
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
        "task-tree-generator",
        "tier1-doc-updater",
        # Test fixture / host-local safe agent; known dev-only agents are still
        # excluded by _DEV_ONLY_AGENTS below.
        "safe-agent",
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
    "scripts/generate-workstreams.py",
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

_PROD_OWNER_BY_PREFIX = {
    "scripts/": "release-runtime",
    "skills/": "release-surface",
    "agents/": "release-surface",
    "runtime/": "runtime-export",
    "z_harness_cli/": "cli",
    "docs/": "public-docs",
}


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
    return True


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
    normalized = normalize_artifact_path(path)
    for prefix, owner in _PROD_OWNER_BY_PREFIX.items():
        if normalized.startswith(prefix):
            return owner
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
        if path_excluded_from_prod(path):
            return normalize_artifact_path(path)
    return None


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    tar_parser = subparsers.add_parser("tar-excludes")
    tar_parser.add_argument("--surface", default=None)
    tar_parser.set_defaults(func=_cmd_tar_excludes)

    audit_parser = subparsers.add_parser("audit-listing")
    audit_parser.add_argument("--surface", default="prod")
    audit_parser.set_defaults(func=_cmd_audit_listing)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
