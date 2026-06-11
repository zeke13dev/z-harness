"""z-harness MCP server — exposes every /z-* command as an MCP tool.

Transport: stdio. Framework: FastMCP. All command execution delegates to
runtime/dispatch/dispatcher.py via _dispatch_command().
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]


# ── FastMCP server instance ────────────────────────────────────────────────

mcp = FastMCP("z-harness") if FastMCP is not None else None


# ── ToolResult dataclass stub ──────────────────────────────────────────────

@dataclass
class ToolResult:
    """Result envelope for all MCP tool calls.

    Mirrors the on-disk state at $Z_HARNESS_PLAN_DIR/<slug>/.
    """

    ok: bool
    status: str  # "complete" | "error" | "blocked" | "needs_input"
    content: str  # narrative output (markdown or natural language)
    artifacts: dict[str, str] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)

    # ── factory methods ──────────────────────────────────────────────

    @staticmethod
    def success(
        content: str,
        artifacts: dict[str, str] | None = None,
        meta: dict[str, object] | None = None,
    ) -> ToolResult:
        """Create a successful result."""
        return ToolResult(
            ok=True,
            status="complete",
            content=content,
            artifacts=artifacts or {},
            meta=meta or {},
        )

    @staticmethod
    def error(content: str) -> ToolResult:
        """Create an error result."""
        return ToolResult(
            ok=False,
            status="error",
            content=content,
        )

    @staticmethod
    def blocked(content: str) -> ToolResult:
        """Create a blocked result (e.g. plan collision)."""
        return ToolResult(
            ok=False,
            status="blocked",
            content=content,
        )

    @staticmethod
    def needs_input(content: str, question_id: str) -> ToolResult:
        """Create a result that signals the client must provide input."""
        return ToolResult(
            ok=False,
            status="needs_input",
            content=content,
            meta={"question_id": question_id},
        )

    # ── serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "ok": self.ok,
            "status": self.status,
            "content": self.content,
            "artifacts": self.artifacts,
            "meta": self.meta,
        }


# ── Agent definition loader ────────────────────────────────────────────────


class AgentNotFoundError(Exception):
    """Raised when an agent definition file cannot be found."""


class AgentDefinitionError(Exception):
    """Raised when an agent definition has malformed frontmatter."""


@dataclass
class AgentDef:
    """Parsed agent definition from agents/<name>.md."""

    name: str
    description: str
    model: str
    tools: list[str] = field(default_factory=list)
    prompt_template: str = ""


def _load_agent(name: str) -> AgentDef:
    """Load and parse an agent definition from agents/<name>.md.

    Agents are Markdown files with YAML frontmatter containing:
    name, description, tools, model.  The body is the prompt template.

    Args:
        name: Agent name (without .md extension), e.g. "explore".

    Returns:
        AgentDef with parsed metadata and prompt body.

    Raises:
        AgentNotFoundError: If the agent file does not exist.
        AgentDefinitionError: If the frontmatter is malformed.
    """
    repo_root = _get_repo_root()
    # Search agent directories: exports/<host>/agents/ and agents/.
    search_dirs = [
        repo_root / "exports",
        repo_root / "agents",
    ]
    agent_path: Path | None = None
    for base in search_dirs:
        for host_dir in base.iterdir() if base.exists() else []:
            candidate = host_dir / "agents" / f"{name}.md"
            if candidate.exists():
                agent_path = candidate
                break
        if agent_path:
            break
        # Also try direct: agents/<name>.md
        direct = base / f"{name}.md"
        if direct.exists():
            agent_path = direct
            break

    if agent_path is None:
        raise AgentNotFoundError(f"Agent '{name}' not found in agents/")

    raw = agent_path.read_text()

    # Parse YAML frontmatter (between --- markers).
    if not raw.startswith("---"):
        raise AgentDefinitionError(f"Agent '{name}': missing YAML frontmatter")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise AgentDefinitionError(f"Agent '{name}': malformed frontmatter")

    if yaml is None:
        # Fallback: manual parse for required fields.
        frontmatter_lines = parts[1].strip().split("\n")
        frontmatter: dict[str, Any] = {}
        for line in frontmatter_lines:
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val.startswith("[") and val.endswith("]"):
                    val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
                frontmatter[key] = val
    else:
        frontmatter = yaml.safe_load(parts[1]) or {}

    body = parts[2].strip()

    if "name" not in frontmatter:
        raise AgentDefinitionError(f"Agent '{name}': missing 'name' in frontmatter")

    tools_raw = frontmatter.get("tools", [])
    if isinstance(tools_raw, str):
        tools_list = [t.strip() for t in tools_raw.split(",")]
    elif isinstance(tools_raw, list):
        tools_list = tools_raw
    else:
        tools_list = []

    return AgentDef(
        name=frontmatter["name"],
        description=frontmatter.get("description", ""),
        model=frontmatter.get("model", ""),
        tools=tools_list,
        prompt_template=body,
    )


# ── Command tool registry ──────────────────────────────────────────────────

# Each entry maps a snake_case tool name to command metadata.
# Populated from the full command catalog (35 commands).
# is_heavy=True → dispatches through subagent + cross-consult.
# is_heavy=False → fast, read-only commands that return immediately.

COMMAND_TOOLS: dict[str, dict[str, Any]] = {
    # ── Heavy commands (subagent dispatch + cross-consult) ──────────
    "z_plan":            {"command_id": "/z-plan",            "description": "Run the rigorous z-harness planning pipeline",                       "is_heavy": True,  "skills_path": "skills/z-plan/SKILL.md"},
    "z_implement_all":   {"command_id": "/z-implement-all",   "description": "Implement ALL pending tasks from TASKS.md with per-task review",      "is_heavy": True,  "skills_path": "skills/z-implement-all/SKILL.md"},
    "z_implement_next":  {"command_id": "/z-implement-next",  "description": "Implement the next pending task and review",                         "is_heavy": True,  "skills_path": "skills/z-implement-next/SKILL.md"},
    "z_review_all":      {"command_id": "/z-review-all",      "description": "Final-gate cross-LLM review of cumulative diff against SPEC.md",       "is_heavy": True,  "skills_path": "skills/z-review-all/SKILL.md"},
    "z_audit":           {"command_id": "/z-audit",           "description": "Read-only audit pipeline with cross-LLM review",                      "is_heavy": True,  "skills_path": "skills/z-audit/SKILL.md"},
    "z_audit_plan_style":{"command_id": "/z-audit-plan-style","description": "Audit plan artifacts for code-quality issues before code is written",  "is_heavy": True,  "skills_path": "skills/z-audit-plan-style/SKILL.md"},
    "z_debug":           {"command_id": "/z-debug",           "description": "Investigate a bug with repro/hypothesis/evidence/isolation phases",    "is_heavy": True,  "skills_path": "skills/z-debug/SKILL.md"},
    "z_do":              {"command_id": "/z-do",              "description": "Plan-less execution for trivial changes with harness discipline",      "is_heavy": True,  "skills_path": "skills/z-do/SKILL.md"},
    "z_brainstorm":      {"command_id": "/z-brainstorm",      "description": "3-vendor parallel pre-plan ideation with anti-bias check",            "is_heavy": True,  "skills_path": "skills/z-brainstorm/SKILL.md"},
    "z_research":        {"command_id": "/z-research",        "description": "Deep research: map + brainstorm + adversarial synthesis panel",      "is_heavy": True,  "skills_path": "skills/z-research/SKILL.md"},
    "z_map":             {"command_id": "/z-map",             "description": "Map terrain with citations and cross-LLM critique",                   "is_heavy": True,  "skills_path": "skills/z-map/SKILL.md"},
    "z_plan_light":      {"command_id": "/z-plan-light",      "description": "Lightweight planner for 1-5 file fixes with bundled cross-consult",   "is_heavy": True,  "skills_path": "skills/z-plan-light/SKILL.md"},
    "z_plan_split":      {"command_id": "/z-plan-split",      "description": "Pre-emptive scope splitter — fan-out into N narrow cluster-planners", "is_heavy": True,  "skills_path": "skills/z-plan-split/SKILL.md"},
    "z_test":            {"command_id": "/z-test",            "description": "Dual-source semantic test-case planner (ERROR_POINTS + INVARIANTS)",   "is_heavy": True,  "skills_path": "skills/z-test/SKILL.md"},
    "z_amend":           {"command_id": "/z-amend",           "description": "Amend an existing plan (SPEC/PLAN/TASKS) preserving completed state", "is_heavy": True,  "skills_path": "skills/z-amend/SKILL.md"},
    "z_init_docs":       {"command_id": "/z-init-docs",       "description": "Bootstrap a two-tier docs system (human Markdown + LLM JSON)",        "is_heavy": True,  "skills_path": "skills/z-init-docs/SKILL.md"},
    "z_maintain_docs":   {"command_id": "/z-maintain-docs",   "description": "Refresh stale docs after source changes via per-concept updaters",    "is_heavy": True,  "skills_path": "skills/z-maintain-docs/SKILL.md"},
    "z_uplift":          {"command_id": "/z-uplift",          "description": "Bulk codebase quality uplift — decompose + per-component audit",     "is_heavy": True,  "skills_path": "skills/z-uplift/SKILL.md"},
    "z_improve":         {"command_id": "/z-improve",         "description": "Post-run retrospective — analyze events.jsonl for friction signals", "is_heavy": True,  "skills_path": "skills/z-improve/SKILL.md"},
    # ── Fast / read-only commands ─────────────────────────────────
    "z_where":           {"command_id": "/z-where",           "description": "List active plans, current phase, branch, age, status",               "is_heavy": False, "skills_path": "skills/z-where/SKILL.md"},
    "z_stats":           {"command_id": "/z-stats",           "description": "Progress + cost report for the current plan",                         "is_heavy": False, "skills_path": "skills/z-stats/SKILL.md"},
    "z_suggest_memory":  {"command_id": "/z-suggest-memory",  "description": "Author a memory entry for docs/llm/ from debug post-mortems",        "is_heavy": False, "skills_path": "skills/z-suggest-memory/SKILL.md"},
    "z_axiom_scan":      {"command_id": "/z-axiom-scan",      "description": "Mine candidate axioms from interaction history",                     "is_heavy": False, "skills_path": "skills/z-axiom-scan/SKILL.md"},
    "z_axiom_list":      {"command_id": "/z-axiom-list",      "description": "List axiom records from the store with filtering",                   "is_heavy": False, "skills_path": "skills/z-axiom-list/SKILL.md"},
    "z_axiom_approve":   {"command_id": "/z-axiom-approve",   "description": "Approve a candidate axiom (requires explicit confirmation)",         "is_heavy": False, "skills_path": "skills/z-axiom-approve/SKILL.md"},
    "z_axiom_reject":    {"command_id": "/z-axiom-reject",    "description": "Reject a candidate or approved axiom",                               "is_heavy": False, "skills_path": "skills/z-axiom-reject/SKILL.md"},
    "z_axiom_edit":      {"command_id": "/z-axiom-edit",      "description": "Edit a field on a candidate or approved axiom record",               "is_heavy": False, "skills_path": "skills/z-axiom-edit/SKILL.md"},
    "z_personas":        {"command_id": "/z-personas",        "description": "Inspect the persona registry, role bindings, and persona files",     "is_heavy": False, "skills_path": "skills/z-personas/SKILL.md"},
    "z_handoff":         {"command_id": "/z-handoff",         "description": "Write a handoff.json artifact for session continuity",               "is_heavy": False, "skills_path": "skills/z-handoff/SKILL.md"},
    "z_update":          {"command_id": "/z-update",          "description": "Update the local z-harness install",                                  "is_heavy": False, "skills_path": "skills/z-update/SKILL.md"},
    "z_reality":         {"command_id": "/z-reality",         "description": "Interactive premise refinement — conversational on-ramp",            "is_heavy": False, "skills_path": "skills/z-reality/SKILL.md"},
    "z_overnight":       {"command_id": "/z-overnight",       "description": "Overnight batch run of multiple /z-* commands",                      "is_heavy": False, "skills_path": "skills/z-overnight/SKILL.md"},
    "z_evaluate":        {"command_id": "/z-evaluate",        "description": "Evaluate a completed z-harness session for patterns worth preserving","is_heavy": False, "skills_path": "skills/z-evaluate/SKILL.md"},
    "z_context_budget":  {"command_id": "/z-context-budget",  "description": "Analyze context utilization and surface savings recommendations",    "is_heavy": False, "skills_path": "skills/z-context-budget/SKILL.md"},
    "z_doc_rationale":   {"command_id": "/z-doc-rationale",   "description": "Produce ADRs, design rationale, and tradeoff explanations",          "is_heavy": False, "skills_path": "skills/z-doc-rationale/SKILL.md"},
    "z_test_invariant":  {"command_id": "/z-test-invariant",  "description": "Legacy invariant-only test-case planner",                            "is_heavy": False, "skills_path": "skills/z-test-invariant/SKILL.md"},
    # ── Utility tools ────────────────────────────────────────────
    "z_export":          {"command_id": "/z-export",          "description": "Export z-harness commands/agents/skills to a host",                   "is_heavy": False, "skills_path": ""},
    "z_detect":          {"command_id": "/z-detect",          "description": "Detect installed hosts and versions",                                 "is_heavy": False, "skills_path": ""},
}


# ── Role-to-command mapping ────────────────────────────────────────────────

# Maps each command tool to the provider role used for dispatch.
# Most commands use "implementer"; audit/review use "reviewer".
_COMMAND_ROLE_MAP: dict[str, str] = {
    "z_plan": "implementer",
    "z_implement_all": "implementer",
    "z_implement_next": "implementer",
    "z_review_all": "reviewer",
    "z_audit": "reviewer",
    "z_audit_plan_style": "reviewer",
    "z_debug": "implementer",
    "z_do": "implementer",
    "z_brainstorm": "implementer",
    "z_research": "implementer",
    "z_map": "implementer",
    "z_plan_light": "implementer",
    "z_plan_split": "implementer",
    "z_test": "implementer",
    "z_amend": "implementer",
    "z_init_docs": "implementer",
    "z_maintain_docs": "implementer",
    "z_uplift": "reviewer",
    "z_improve": "implementer",
}


# ── REPO_ROOT resolution ───────────────────────────────────────────────────

_REPO_ROOT: Path | None = None


def _get_repo_root() -> Path:
    """Resolve the z-harness repo root (cached)."""
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    # Walk up from this file's location to find the repo root (contains scripts/).
    candidate = Path(__file__).resolve().parent.parent.parent
    while candidate != candidate.parent:
        if (candidate / "scripts" / "resolve-provider.py").exists():
            _REPO_ROOT = candidate
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Cannot locate z-harness repo root")


# ── Core dispatch ──────────────────────────────────────────────────────────

def _dispatch_command(
    command_id: str,
    args: dict[str, Any],
    progress_callback: Any = None,
) -> ToolResult:
    """Resolve and dispatch a z-harness command through the runtime dispatcher.

    1. Look up command metadata from COMMAND_TOOLS.
    2. Resolve the provider config for the appropriate role.
    3. Select the HostDriver for the provider's host.
    4. Build caller args and env.
    5. Call Dispatcher.run() to execute via subprocess.
    6. Bridge DispatchResult → ToolResult.
    """
    # 1. Look up command.
    tool_name = command_id.lstrip("/").replace("/", "_").replace("-", "_")
    if tool_name not in COMMAND_TOOLS:
        return ToolResult.error(f"Unknown command: {command_id}")

    meta = COMMAND_TOOLS[tool_name]
    cmd_id = meta["command_id"]

    # 1a. Fast path: read-only commands use direct handlers (no subagent dispatch).
    if not meta.get("is_heavy", True) and tool_name in _FAST_HANDLERS:
        return _FAST_HANDLERS[tool_name](args)

    # 2. Determine the provider role; fall back to reviewer (always configured).
    role = _COMMAND_ROLE_MAP.get(tool_name, "reviewer")

    try:
        repo_root = _get_repo_root()
    except RuntimeError as exc:
        return ToolResult.error(str(exc))

    # 3. Resolve provider config via resolve-provider.py.
    # Try the command's role first; if that role is unbound, fall back to reviewer.
    provider_config = None
    for attempt_role in (role, "reviewer"):
        try:
            resolve_script = repo_root / "scripts" / "resolve-provider.py"
            proc = subprocess.run(
                [sys.executable, str(resolve_script), attempt_role],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(repo_root),
            )
            if proc.returncode == 0:
                provider_config = json.loads(proc.stdout)
                break
        except subprocess.TimeoutExpired:
            continue
        except json.JSONDecodeError:
            continue
        except Exception:
            continue

    if provider_config is None:
        return ToolResult.error(
            f"Provider resolution failed: no configured provider for role '{role}' or fallback 'reviewer'"
        )

    # 4. Map provider name to driver host name, then select the HostDriver.
    # resolve-provider.py returns provider names like "codex-cli", "claude", etc.
    # select_driver expects canonical host names: "claude", "cursor", "codex", "antigravity".
    _PROVIDER_TO_HOST: dict[str, str] = {
        "codex-cli": "codex",
        "claude": "claude",
        "cursor": "cursor",
        "antigravity": "antigravity",
    }

    try:
        from runtime.drivers import select_driver

        provider_name = provider_config.get("provider", "")
        host = _PROVIDER_TO_HOST.get(provider_name, provider_name)
        if host not in ("claude", "cursor", "codex", "antigravity"):
            return ToolResult.error(f"Unsupported provider host: {provider_name}")
        driver = select_driver(host)
    except Exception as exc:
        return ToolResult.error(f"Driver selection failed for host '{host}': {exc}")

    # 5. Initialize the driver.
    try:
        driver.init()
    except Exception as exc:
        return ToolResult.error(f"Driver initialization failed: {exc}")

    # 6. Build the prompt argument from tool args.
    prompt = args.get("prompt", "")
    slug = args.get("slug")

    # Compose caller args: codex/pi drivers accept prompt via stdin (-- arg).
    # The command_id is /z-plan etc; the content goes via stdin.
    caller_args: list[str] = [prompt] if prompt else []

    # Pass slug as environment variable for drivers that read Z_HARNESS_SLUG.
    if slug:
        os.environ["Z_HARNESS_SLUG"] = slug

    # 7. Dispatch.
    try:
        import uuid

        from runtime.dispatch.dispatcher import Dispatcher

        run_id = f"mcp-{uuid.uuid4().hex[:12]}"
        dispatcher = Dispatcher(
            repo_root=str(repo_root),
            run_id=run_id,
        )

        result = dispatcher.run(
            driver=driver,
            command_id=cmd_id,
            caller_args=caller_args,
            provider_config=provider_config,
            model=args.get("model"),
        )

        # 9. Bridge DispatchResult → ToolResult.
        if result.success:
            content = result.stderr or "Command completed successfully."
            # Collect artifact content from stdout events.
            artifacts: dict[str, str] = {}
            for event in result.stdout_events:
                if isinstance(event, dict) and event.get("type") == "artifact":
                    name = event.get("name", "")
                    text = event.get("content", "")
                    if name and text:
                        artifacts[name] = text
            return ToolResult.success(
                content=content,
                artifacts=artifacts,
                meta={
                    "exit_code": result.exit_code,
                    "wall_ms": result.wall_ms,
                },
            )
        else:
            return ToolResult.error(
                content=result.stderr or f"Command '{cmd_id}' failed with exit code {result.exit_code}",
            )

    except Exception as exc:
        return ToolResult.error(f"Dispatch error: {exc}")


# ── Read-only command handlers (fast path — no subagent dispatch) ──────────


def _handle_z_where(args: dict[str, Any]) -> ToolResult:
    """List active plans from $Z_HARNESS_PLAN_DIR."""
    try:
        repo_root = _get_repo_root()
        script = repo_root / "scripts" / "plan-path.sh"
        plans_dir = os.environ.get(
            "Z_HARNESS_PLAN_DIR",
            str(Path.home() / ".local" / "state" / "z-harness"),
        )
        result = subprocess.run(
            ["bash", str(script), "list"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "Z_HARNESS_PLAN_DIR": plans_dir},
        )
        return ToolResult.success(
            content=result.stdout or "No active plans found.",
            meta={"plans_dir": plans_dir},
        )
    except Exception as exc:
        return ToolResult.error(f"z_where failed: {exc}")


def _handle_z_stats(args: dict[str, Any]) -> ToolResult:
    """Read progress + cost report from metrics.jsonl + TASKS.md."""
    slug = args.get("slug", os.environ.get("Z_HARNESS_SLUG", ""))
    if not slug:
        return ToolResult.needs_input("Please provide a plan slug.", "slug_select")
    try:
        repo_root = _get_repo_root()
        plans_dir = os.environ.get(
            "Z_HARNESS_PLAN_DIR",
            str(Path.home() / ".local" / "state" / "z-harness"),
        )
        metrics_path = Path(plans_dir) / slug / "metrics.jsonl"
        tasks_path = Path(plans_dir) / slug / "TASKS.md"
        if not metrics_path.exists():
            return ToolResult.error(f"No metrics found for slug '{slug}'")
        # Count lines for a quick summary.
        with open(metrics_path) as f:
            line_count = sum(1 for _ in f)
        return ToolResult.success(
            content=f"Plan '{slug}': {line_count} events logged.",
            meta={"slug": slug, "event_count": line_count},
        )
    except Exception as exc:
        return ToolResult.error(f"z_stats failed: {exc}")


def _handle_z_handoff(args: dict[str, Any]) -> ToolResult:
    """Produce a handoff.json artifact for session continuity."""
    try:
        repo_root = _get_repo_root()
        script = repo_root / "scripts" / "write-handoff.sh"
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_root),
            env=os.environ,
        )
        if result.returncode == 0:
            return ToolResult.success(
                content=result.stdout or "handoff.json written.",
                meta={"command": "z_handoff"},
            )
        return ToolResult.error(result.stderr or "handoff failed")
    except Exception as exc:
        return ToolResult.error(f"z_handoff failed: {exc}")


def _handle_z_personas(args: dict[str, Any]) -> ToolResult:
    """Inspect the persona registry."""
    try:
        repo_root = _get_repo_root()
        personas_dir = repo_root / "personas"
        if personas_dir.exists():
            personas = sorted(
                [p.stem for p in personas_dir.glob("*.md") if p.name != "INDEX.md"]
            )
            return ToolResult.success(
                content=f"{len(personas)} personas: {', '.join(personas)}",
                meta={"personas": personas, "count": len(personas)},
            )
        return ToolResult.success(content="No personas directory found.")
    except Exception as exc:
        return ToolResult.error(f"z_personas failed: {exc}")


def _handle_z_update(args: dict[str, Any]) -> ToolResult:
    """Check for and apply z-harness updates."""
    try:
        repo_root = _get_repo_root()
        script = repo_root / "scripts" / "version.sh"
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=10,
            cwd=str(repo_root),
            env=os.environ,
        )
        if result.returncode == 0:
            version_info = result.stdout.strip()
            return ToolResult.success(
                content=f"z-harness version info:\n{version_info}",
                meta={"command": "z_update"},
            )
        return ToolResult.error(result.stderr or "version check failed")
    except Exception as exc:
        return ToolResult.error(f"z_update failed: {exc}")


# Map fast command tool names to their handler functions.
_FAST_HANDLERS: dict[str, Any] = {
    "z_where": _handle_z_where,
    "z_stats": _handle_z_stats,
    "z_handoff": _handle_z_handoff,
    "z_personas": _handle_z_personas,
    "z_update": _handle_z_update,
}


# ── Export / Detect handlers ───────────────────────────────────────────────


def _handle_z_export(args: dict[str, Any]) -> ToolResult:
    """Export z-harness to one or all hosts."""
    try:
        from z_harness_cli.commands.export import run as export_run
        import typer

        # Build a minimal Typer Context for the export command.
        # export_run expects (ctx, host, all_hosts, in_place, out, force).
        host = args.get("host")
        all_hosts = args.get("all_hosts", False)
        in_place = args.get("in_place", False)
        out = args.get("out")
        force = args.get("force", False)

        # We call export_run directly (it doesn't actually need ctx for the core logic).
        export_run(
            ctx=None,  # type: ignore[arg-type]
            host=host,
            all_hosts=all_hosts,
            in_place=in_place,
            out=out,
            force=force,
        )
        return ToolResult.success(
            content="Export completed successfully.",
            meta={"host": host, "all_hosts": all_hosts},
        )
    except Exception as exc:
        return ToolResult.error(f"z_export failed: {exc}")


def _handle_z_detect(args: dict[str, Any]) -> ToolResult:
    """Detect installed z-harness hosts and versions."""
    try:
        from z_harness_cli.adapters.registry import detect_all

        hosts = detect_all()
        installed = [
            {"name": h.name, "installed": h.installed, "version": getattr(h, "version", None)}
            for h in hosts
        ]
        content_lines = [f"{h['name']}: {'✓' if h['installed'] else '✗'} {h['version'] or ''}".strip() for h in installed]
        return ToolResult.success(
            content="\n".join(content_lines),
            meta={"hosts": installed},
        )
    except Exception as exc:
        return ToolResult.error(f"z_detect failed: {exc}")


# Register export/detect in fast handlers.
_FAST_HANDLERS["z_export"] = _handle_z_export
_FAST_HANDLERS["z_detect"] = _handle_z_detect


# ── Entry point ────────────────────────────────────────────────────────────

def serve(*, transport: str = "stdio") -> None:
    """Start the z-harness MCP server on the given transport."""
    if mcp is None:
        raise RuntimeError(
            "FastMCP is not installed. Install with: pip install fastmcp"
        )
    mcp.run(transport=transport)
