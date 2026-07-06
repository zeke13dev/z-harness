"""z-harness MCP server — exposes every /z-* command as an MCP tool.

Transport: stdio. Framework: FastMCP. All command execution delegates to
runtime/dispatch/dispatcher.py via _dispatch_command().
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from z_harness_cli import release_surface

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


# ==========================================================================
# ToolResult
# ==========================================================================

@dataclass
class ToolResult:
    """Result envelope for all MCP tool calls."""

    ok: bool
    status: str  # "complete" | "error" | "blocked" | "needs_input" | "skipped"
    content: str
    artifacts: dict[str, str] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def success(
        content: str,
        artifacts: dict[str, str] | None = None,
        meta: dict[str, object] | None = None,
    ) -> ToolResult:
        return ToolResult(ok=True, status="complete", content=content,
                          artifacts=artifacts or {}, meta=meta or {})

    @staticmethod
    def error(content: str) -> ToolResult:
        return ToolResult(ok=False, status="error", content=content)

    @staticmethod
    def blocked(content: str) -> ToolResult:
        return ToolResult(ok=False, status="blocked", content=content)

    @staticmethod
    def needs_input(content: str, question_id: str) -> ToolResult:
        return ToolResult(ok=False, status="needs_input", content=content,
                          meta={"question_id": question_id})

    @staticmethod
    def skipped(content: str) -> ToolResult:
        return ToolResult(ok=False, status="skipped", content=content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "status": self.status, "content": self.content,
            "artifacts": self.artifacts, "meta": self.meta,
        }


# ==========================================================================
# Agent definition loader (T009)
# ==========================================================================

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
    model_class: str = ""
    thinking: str = ""
    reasoning: str = ""
    prompt_template: str = ""


def _load_agent(name: str) -> AgentDef:
    """Load and parse an agent definition from agents/<name>.md."""
    repo_root = _get_repo_root()
    agent_path = repo_root / "agents" / f"{name}.md"
    if not agent_path.exists():
        raise AgentNotFoundError(f"Agent '{name}' not found in agents/")

    raw = agent_path.read_text()
    if not raw.startswith("---"):
        raise AgentDefinitionError(f"Agent '{name}': missing YAML frontmatter")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise AgentDefinitionError(f"Agent '{name}': malformed frontmatter")

    if yaml is None:
        fm: dict[str, Any] = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v.startswith("[") and v.endswith("]"):
                    v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
                fm[k] = v
    else:
        fm = yaml.safe_load(parts[1]) or {}

    body = parts[2].strip()
    if "name" not in fm:
        raise AgentDefinitionError(f"Agent '{name}': missing 'name' in frontmatter")
    tools_raw = fm.get("tools", [])
    if isinstance(tools_raw, str):
        tools_list = [t.strip() for t in tools_raw.split(",")]
    elif isinstance(tools_raw, list):
        tools_list = tools_raw
    else:
        tools_list = []

    return AgentDef(
        name=fm["name"], description=fm.get("description", ""),
        model=fm.get("model", ""), model_class=fm.get("model_class", ""),
        thinking=fm.get("thinking", ""), reasoning=fm.get("reasoning", ""),
        tools=tools_list, prompt_template=body,
    )


# ==========================================================================
# Progress phases per command type (T006)
# ==========================================================================

_PROGRESS_PHASES: dict[str, list[str]] = {
    "z_plan":           ["premise_check", "explore", "decisions", "consult", "writing", "complete"],
    "z_execute":        ["task_start", "task_complete", "review", "complete"],
    "z_debug":          ["repro", "hypothesis", "evidence", "isolate", "fix", "post_mortem"],
    "z_brainstorm":     ["dispatch", "anti_bias", "synthesize", "complete"],
    "z_research":       ["map", "brainstorm", "adversarial_panel", "synthesize", "complete"],
    "z_review_all":     ["review_start", "review_complete", "complete"],
    "z_audit":          ["audit_start", "audit_complete", "complete"],
    "z_test":           ["invariant_scan", "error_point_scan", "consult", "complete"],
}


def _report_progress(
    callback: Any,
    phase: str,
    total: int,
    current: int,
    message: str,
    tool_name: str,
) -> None:
    """Emit progress via the MCP callback if available.

    Args:
        callback: MCP progress callback or None.
        phase: Current phase name.
        total: Total phases.
        current: Current phase index (1-based).
        message: Human-readable status message.
        tool_name: Tool name for context (e.g. "z_plan").
    """
    if callback is None:
        return
    try:
        callback({
            "phase": phase,
            "total": total,
            "current": current,
            "message": message,
            "tool": tool_name,
        })
    except Exception:
        pass  # Progress reporting is best-effort.


_PROVIDER_TO_HOST: dict[str, str] = {
    "codex-cli": "codex",
    "claude": "claude",
    "cursor": "cursor",
    "antigravity": "antigravity",
}

_SUPPORTED_PROVIDER_HOSTS: frozenset[str] = frozenset(
    {"claude", "cursor", "codex", "antigravity"}
)


@dataclass(frozen=True)
class MCPProviderResolution:
    """Resolved provider descriptor for one MCP tool dispatch."""

    role: str
    provider_config: dict[str, Any]
    provider_name: str
    host: str


def _resolve_mcp_provider(repo_root: Path, tool_name: str) -> MCPProviderResolution | ToolResult:
    """Resolve the configured provider for *tool_name* using MCP role rules.

    This preserves ``MCPDispatcher``'s historical behaviour: command role
    mapping, reviewer fallback, provider aliases inside ``resolve-provider.py``,
    and the ``Z_HARNESS_CONSULT=off`` / provider ``none`` skipped sentinel.
    """
    role = _COMMAND_ROLE_MAP.get(tool_name, "reviewer")
    provider_config: dict[str, Any] | None = None

    for attempt_role in (role, "reviewer"):
        try:
            resolve_script = repo_root / "scripts" / "resolve-provider.py"
            proc = subprocess.run(
                [sys.executable, str(resolve_script), attempt_role],
                capture_output=True, text=True, timeout=15,
                cwd=str(repo_root),
            )
            if proc.returncode == 0:
                # Detect the consult-off sentinel: resolve-provider.py prints
                # the bare string "none" (not JSON) when Z_HARNESS_CONSULT=off
                # and the role is a consult/reviewer role.
                stdout_stripped = proc.stdout.strip()
                if stdout_stripped == "none":
                    return ToolResult.skipped(
                        f"Consulting disabled (Z_HARNESS_CONSULT=off) — "
                        f"{tool_name} bound to a consult role was skipped."
                    )
                loaded = json.loads(proc.stdout)
                # Also handle the case where the JSON itself carries provider="none".
                if isinstance(loaded, dict) and loaded.get("provider") == "none":
                    return ToolResult.skipped(
                        f"Consulting disabled (Z_HARNESS_CONSULT=off) — "
                        f"{tool_name} bound to a consult role was skipped."
                    )
                if isinstance(loaded, dict):
                    provider_config = loaded
                    break
        except subprocess.TimeoutExpired:
            continue
        except json.JSONDecodeError:
            continue
        except Exception:
            continue

    if provider_config is None:
        return ToolResult.error(
            f"Provider resolution failed: no configured provider for role '{role}'"
        )

    provider_name = str(provider_config.get("provider", ""))
    host = _PROVIDER_TO_HOST.get(provider_name, provider_name)
    if host not in _SUPPORTED_PROVIDER_HOSTS:
        return ToolResult.error(f"Unsupported provider host: {provider_name}")

    return MCPProviderResolution(
        role=role,
        provider_config=provider_config,
        provider_name=provider_name,
        host=host,
    )


def _select_and_init_mcp_driver(
    repo_root: Path,
    run_id: str,
    provider_resolution: MCPProviderResolution,
) -> object | ToolResult:
    """Select and initialise the host driver for an MCP provider resolution."""
    try:
        from runtime.drivers import select_driver

        driver = select_driver(provider_resolution.host)
    except Exception as exc:
        return ToolResult.error(f"Driver selection failed: {exc}")

    try:
        driver.init(
            provider_resolution.provider_config,
            context={"run_id": run_id, "repo_root": str(repo_root)},
        )
    except Exception as exc:
        return ToolResult.error(f"Driver init failed: {exc}")

    return driver


@contextmanager
def _scoped_z_harness_slug(slug: Any):
    """Scope Z_HARNESS_SLUG to one dispatch and restore the prior value."""
    slug_key = "Z_HARNESS_SLUG"
    prior_slug = os.environ.get(slug_key)
    slug_text = str(slug) if slug is not None else ""
    try:
        if slug_text:
            os.environ[slug_key] = slug_text
        elif prior_slug is not None:
            os.environ.pop(slug_key, None)
        yield
    finally:
        if prior_slug is None:
            os.environ.pop(slug_key, None)
        else:
            os.environ[slug_key] = prior_slug


# ==========================================================================
# MCPDispatcher wrapper (T017)
# ==========================================================================

class MCPDispatcher:
    """Wraps runtime/dispatch/dispatcher.py for MCP tool use.

    Translates tool args → dispatcher args, bridges DispatchResult → ToolResult,
    and connects progress callbacks for MCP progress notifications.
    """

    def __init__(self, repo_root: Path, tool_name: str, args: dict[str, Any],
                 progress_callback: Any = None) -> None:
        self._repo_root = repo_root
        self._tool_name = tool_name
        self._args = args
        self._progress_callback = progress_callback
        self._phases = _PROGRESS_PHASES.get(tool_name, ["dispatch", "complete"])
        self._phase_idx = 0

    def _advance_phase(self, message: str = "") -> None:
        self._phase_idx += 1
        _report_progress(
            self._progress_callback, self._phases[min(self._phase_idx, len(self._phases) - 1)],
            len(self._phases), min(self._phase_idx, len(self._phases)),
            message, self._tool_name,
        )

    def dispatch(
        self,
        provider_resolution: MCPProviderResolution | None = None,
    ) -> ToolResult:
        """Resolve provider, select driver, run dispatcher, bridge result.

        When ``self._args`` contains a ``resume`` key of shape
        ``{"question_id": str, "answer": str}``, the answer is appended to the
        dispatch prompt as a clearly-delimited continuation block so the command
        can proceed past the pending question.  This is a re-dispatch-with-answer
        (not a live session resume — the underlying dispatcher.run session_id is
        telemetry-only and drivers do not support true subprocess continuation).
        """
        # --- Resolve command metadata ---
        meta = _active_command_tools().get(self._tool_name)
        if meta is None:
            return ToolResult.error(f"Unknown command: {self._tool_name}")
        cmd_id: str = meta["command_id"]

        # --- Provider / driver resolution ---
        resolved_provider: MCPProviderResolution | ToolResult
        if provider_resolution is None:
            resolved_provider = _resolve_mcp_provider(self._repo_root, self._tool_name)
        else:
            resolved_provider = provider_resolution
        if isinstance(resolved_provider, ToolResult):
            return resolved_provider

        provider_config = resolved_provider.provider_config
        run_id = f"mcp-{uuid.uuid4().hex[:12]}"
        driver_or_error = _select_and_init_mcp_driver(
            self._repo_root,
            run_id,
            resolved_provider,
        )
        if isinstance(driver_or_error, ToolResult):
            return driver_or_error
        driver = driver_or_error

        # --- Build args ---
        prompt = self._args.get("prompt", "")
        slug_val = self._args.get("slug")

        # Thread resume answer into the prompt when the caller supplies a
        # resume block.  This re-dispatches with the answer appended so the
        # command can proceed past the pending question.
        resume = self._args.get("resume")
        if isinstance(resume, dict):
            q_id = resume.get("question_id", "")
            answer = resume.get("answer", "")
            if q_id and answer:
                continuation = (
                    f"\n\n---\nUser answer to pending question ({q_id}): {answer}\n---"
                )
                prompt = prompt + continuation if prompt else continuation.strip()

        caller_args: list[str] = [prompt] if prompt else []

        # --- Dispatch (with scoped Z_HARNESS_SLUG mutation) ---
        # A per-call slug cannot leak into later MCP calls, and calls without
        # a slug do not inherit stale process state.
        with _scoped_z_harness_slug(slug_val):
            self._advance_phase(f"Resolving provider and driver for {cmd_id}")
            try:
                from runtime.dispatch.dispatcher import Dispatcher
                dispatcher = Dispatcher(repo_root=str(self._repo_root), run_id=run_id)

                self._advance_phase(f"Dispatching {cmd_id}")
                result = dispatcher.run(
                    driver=driver, command_id=cmd_id, caller_args=caller_args,
                    provider_config=provider_config, model=self._args.get("model"),
                    model_source=self._args.get("model_source"),
                    model_route=self._args.get("model_route"),
                    model_route_kind=self._args.get("model_route_kind"),
                    model_thinking=self._args.get("model_thinking"),
                    model_reasoning=self._args.get("model_reasoning"),
                    model_override_applied=self._args.get("model_override_applied"),
                    model_override_support=self._args.get("model_override_support"),
                )
            except Exception as exc:
                return ToolResult.error(f"Dispatch error: {exc}")

        # --- Bridge result ---
        bridged = _bridge_dispatch_result(result, cmd_id)
        if bridged.status == "complete":
            self._advance_phase("Complete")
        return bridged


# ==========================================================================
# Narrative extraction from stdout_events (T-REV-002)
# ==========================================================================


def _extract_narrative(stdout_events: list[dict]) -> str:
    """Concatenate human-readable text from type=='text' stdout events.

    Drivers emit the command's natural-language narrative as ``type="text"``
    events on stdout (NDJSON stream-json format).  The ``content`` field of
    each such event is the text fragment.  This function joins all fragments
    in order, separated by a newline.

    ``result.stderr`` is the raw OS stderr pipe and carries only CLI
    diagnostic/warning messages — it is NOT the narrative source.

    Returns an empty string when no text events are present (e.g. the
    driver emitted only artifact or metadata events).
    """
    parts = [
        event["content"]
        for event in stdout_events
        if isinstance(event, dict)
        and event.get("type") == "text"
        and isinstance(event.get("content"), str)
        and event["content"]
    ]
    return "\n".join(parts)


def _bridge_dispatch_result(
    result: Any,
    cmd_id: str,
    meta: dict[str, object] | None = None,
) -> ToolResult:
    """Convert a runtime ``DispatchResult`` into the MCP ``ToolResult`` shape."""
    # The narrative lives in stdout_events (type=="text" frames); result.stderr
    # is the raw OS stderr pipe which carries only CLI diagnostic messages.
    narrative = _extract_narrative(result.stdout_events) or result.stderr
    input_signal = _detect_needs_input(narrative)
    if input_signal:
        return ToolResult.needs_input(input_signal["content"], input_signal["question_id"])

    if result.success:
        # Drivers emit human-readable output as type=="text" events on stdout,
        # NOT on stderr.  result.stderr is the raw OS stderr pipe (CLI warnings);
        # it is only a last-resort fallback when no text events were emitted.
        content = narrative or "Command completed successfully."
        artifacts: dict[str, str] = {}
        for event in result.stdout_events:
            if isinstance(event, dict) and event.get("type") == "artifact":
                name, text = event.get("name", ""), event.get("content", "")
                if name and text:
                    artifacts[name] = text

        result_meta: dict[str, object] = {
            "exit_code": result.exit_code,
            "wall_ms": result.wall_ms,
        }
        if meta:
            result_meta.update(meta)
        return ToolResult.success(content=content, artifacts=artifacts, meta=result_meta)

    return ToolResult.error(result.stderr or f"Command '{cmd_id}' failed (exit {result.exit_code})")


# ==========================================================================
# needs_input detection (T008)
# ==========================================================================

_NEEDS_INPUT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AskUserQuestion:\s*(.+?)(?:\n|$)"), "ask_user"),
    (re.compile(r"question_id:\s*(\S+).*?content:\s*(.+?)(?:\n|$)"), "structured"),
    (re.compile(r"\[INPUT_REQUIRED\]\s*(.+?):\s*(.+?)(?:\n|$)"), "tagged"),
]


def _detect_needs_input(output: str) -> dict[str, str] | None:
    """Scan dispatch output for structured AskUserQuestion signals.

    Returns {"question_id": ..., "content": ...} if detected, else None.
    """
    if not output:
        return None
    for pattern, qid_prefix in _NEEDS_INPUT_PATTERNS:
        m = pattern.search(output)
        if m:
            if qid_prefix == "ask_user":
                return {"question_id": f"{qid_prefix}_needs_input", "content": m.group(1).strip()}
            elif qid_prefix == "tagged":
                return {"question_id": m.group(1).strip(), "content": m.group(2).strip()}
            else:
                return {"question_id": m.group(1).strip(), "content": m.group(2).strip()}
    return None


# ==========================================================================
# Command tool registry (T003)
# ==========================================================================

COMMAND_TOOLS: dict[str, dict[str, Any]] = {
    # ── Heavy ──
    "z_plan":            {"command_id": "/z-plan",            "description": "Run the rigorous z-harness planning pipeline",                       "is_heavy": True},
    "z_execute":         {"command_id": "/z-execute",         "description": "Execute ALL pending tasks from TASKS.md with per-task review",         "is_heavy": True},
    "z_review_all":      {"command_id": "/z-review-all",      "description": "Final-gate cross-LLM review of cumulative diff against SPEC.md",       "is_heavy": True},
    "z_audit":           {"command_id": "/z-audit",           "description": "Read-only audit pipeline with cross-LLM review",                      "is_heavy": True},
    "z_audit_plan_style":{"command_id": "/z-audit-plan-style","description": "Audit plan artifacts for code-quality issues before code is written",  "is_heavy": True},
    "z_debug":           {"command_id": "/z-debug",           "description": "Investigate a bug with repro/hypothesis/evidence/isolation phases",    "is_heavy": True},
    "z_do":              {"command_id": "/z-do",              "description": "Plan-less execution for trivial changes with harness discipline",      "is_heavy": True},
    "z_brainstorm":      {"command_id": "/z-brainstorm",      "description": "3-vendor parallel pre-plan ideation with anti-bias check",            "is_heavy": True},
    "z_research":        {"command_id": "/z-research",        "description": "Deep research: map + brainstorm + adversarial synthesis panel",      "is_heavy": True},
    "z_map":             {"command_id": "/z-map",             "description": "Map terrain with citations and cross-LLM critique",                   "is_heavy": True},
    "z_plan_split":      {"command_id": "/z-plan-split",      "description": "Pre-emptive scope splitter — fan-out into N narrow cluster-planners", "is_heavy": True},
    "z_test":            {"command_id": "/z-test",            "description": "Dual-source semantic test-case planner (ERROR_POINTS + INVARIANTS)",   "is_heavy": True},
    "z_amend":           {"command_id": "/z-amend",           "description": "Amend an existing plan (SPEC/PLAN/TASKS) preserving completed state", "is_heavy": True},
    "z_init_docs":       {"command_id": "/z-init-docs",       "description": "Bootstrap a two-tier docs system (human Markdown + LLM JSON)",        "is_heavy": True},
    "z_maintain_docs":   {"command_id": "/z-maintain-docs",   "description": "Refresh stale docs after source changes via per-concept updaters",    "is_heavy": True},
    "z_uplift":          {"command_id": "/z-uplift",          "description": "Bulk codebase quality uplift — decompose + per-component audit",     "is_heavy": True},
    "z_improve":         {"command_id": "/z-improve",         "description": "Post-run retrospective — analyze events.jsonl for friction signals", "is_heavy": True},
    # ── Fast / read-only ──
    "z_where":           {"command_id": "/z-where",           "description": "List active plans, current phase, branch, age, status",               "is_heavy": False},
    "z_stats":           {"command_id": "/z-stats",           "description": "Progress + cost report for the current plan",                         "is_heavy": False},
    "z_suggest_memory":  {"command_id": "/z-suggest-memory",  "description": "Author a memory entry for docs/llm/ from debug post-mortems",        "is_heavy": False},
    "z_axiom_scan":      {"command_id": "/z-axiom-scan",      "description": "Mine candidate axioms from interaction history",                     "is_heavy": False},
    "z_axiom_list":      {"command_id": "/z-axiom-list",      "description": "List axiom records from the store with filtering",                   "is_heavy": False},
    "z_axiom_approve":   {"command_id": "/z-axiom-approve",   "description": "Approve a candidate axiom (requires explicit confirmation)",         "is_heavy": False},
    "z_axiom_reject":    {"command_id": "/z-axiom-reject",    "description": "Reject a candidate or approved axiom",                               "is_heavy": False},
    "z_axiom_edit":      {"command_id": "/z-axiom-edit",      "description": "Edit a field on a candidate or approved axiom record",               "is_heavy": False},
    "z_personas":        {"command_id": "/z-personas",        "description": "Inspect the persona registry, role bindings, and persona files",     "is_heavy": False},
    "z_handoff":         {"command_id": "/z-handoff",         "description": "Write a handoff.json artifact for session continuity",               "is_heavy": False},
    "z_clear_checkpoint": {"command_id": "/z-clear-checkpoint", "description": "Write a watcher-readable clear checkpoint",                         "is_heavy": False},
    "z_update":          {"command_id": "/z-update",          "description": "Check local z-harness version; updates must be run explicitly via CLI/plugin", "is_heavy": False},
    "z_sharpen":         {"command_id": "/z-sharpen",         "description": "Conversational bounded idea-sharpener — probes, reframes, and converges a vague idea into a buildable problem statement; writes GRILL.md", "is_heavy": False},
    "z_learn":           {"command_id": "/z-learn",           "description": "Progressive codebase tutoring and orientation with citations",       "is_heavy": False},
    "z_grill":           {"command_id": "/z-grill",           "description": "Interactive pushback interview for sharpening a problem statement",  "is_heavy": False},
    "z_overnight":       {"command_id": "/z-overnight",       "description": "Overnight batch run of multiple /z-* commands",                      "is_heavy": False},
    "z_evaluate":        {"command_id": "/z-evaluate",        "description": "Evaluate a completed z-harness session for patterns worth preserving","is_heavy": False},
    "z_context_budget":  {"command_id": "/z-context-budget",  "description": "Analyze context utilization and surface savings recommendations",    "is_heavy": False},
    "z_doc_rationale":   {"command_id": "/z-doc-rationale",   "description": "Produce ADRs, design rationale, and tradeoff explanations",          "is_heavy": False},
    "z_resume":          {"command_id": "/z-resume",          "description": "Read-only recovery for selecting and continuing prior work context",  "is_heavy": False},
    # ── Utility ──
    "z_export":          {"command_id": "/z-export",          "description": "Export z-harness commands/agents/skills to a host",                   "is_heavy": False},
    "z_detect":          {"command_id": "/z-detect",          "description": "Detect installed hosts and versions",                                 "is_heavy": False},
    "z_subagent_dispatch":{"command_id": "/z-subagent-dispatch", "description": "Dispatch a subagent via LLM CLI",                                  "is_heavy": True},
}

def _release_surface() -> str:
    return release_surface.default_surface()


def _active_command_tools() -> dict[str, dict[str, Any]]:
    if _release_surface() == "dev":
        return COMMAND_TOOLS
    return {
        name: meta
        for name, meta in COMMAND_TOOLS.items()
        if release_surface.is_prod_visible("mcp_tools", name, "prod")
    }




# ==========================================================================
# Role mapping & repo root
# ==========================================================================

_COMMAND_ROLE_MAP: dict[str, str] = {
    "z_plan": "implementer", "z_execute": "implementer",
    "z_review_all": "reviewer", "z_audit": "reviewer", "z_audit_plan_style": "reviewer",
    "z_debug": "implementer", "z_do": "implementer", "z_brainstorm": "implementer",
    "z_learn": "implementer", "z_grill": "implementer", "z_resume": "implementer",
    "z_research": "implementer", "z_map": "implementer",
    "z_plan_split": "implementer", "z_test": "implementer", "z_amend": "implementer",
    "z_init_docs": "implementer", "z_maintain_docs": "implementer",
    "z_uplift": "reviewer", "z_improve": "implementer",
    "z_subagent_dispatch": "implementer",
}

_REPO_ROOT: Path | None = None


def _get_repo_root() -> Path:
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    candidate = Path(__file__).resolve().parent.parent.parent
    while candidate != candidate.parent:
        if (candidate / "scripts" / "resolve-provider.py").exists():
            _REPO_ROOT = candidate
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Cannot locate z-harness repo root")

def _resolve_caller_repo_root(args: dict[str, Any]) -> Path:
    """Return the explicit target repository root supplied by the MCP caller.

    ``_get_repo_root()`` locates the installed z-harness helper/plugin tree.
    Fast handlers that inspect user work must keep that separate from the
    caller's current repository.  Do not fall back to process ``PWD`` or
    ``os.getcwd()`` here: for MCP servers those values often point at the
    helper/plugin checkout rather than the user's workspace.
    """
    raw: object | None = None
    source = ""
    for key in (
        "repo_root",
        "cwd",
        "workspace_root",
        "workspaceRoot",
        "working_directory",
        "project_root",
    ):
        value = args.get(key)
        if value is not None and str(value).strip():
            raw = value
            source = key
            break

    if raw is None:
        env_value = os.environ.get("Z_HARNESS_TARGET_REPO_ROOT")
        if env_value and env_value.strip():
            raw = env_value
            source = "Z_HARNESS_TARGET_REPO_ROOT"

    if raw is None:
        raise ValueError(
            "z_resume requires an explicit caller workspace root via repo_root, "
            "cwd, workspace_root, or Z_HARNESS_TARGET_REPO_ROOT; refusing to use "
            "the MCP helper process cwd"
        )

    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"z_resume caller workspace root from {source} must be an absolute path"
        )
    return path.resolve()


# ==========================================================================
# Core dispatch (T004 + T006 + T007 + T008 + T017)
# ==========================================================================

def _dispatch_command(
    command_id: str,
    args: dict[str, Any],
    progress_callback: Any = None,
) -> ToolResult:
    """Resolve and dispatch a z-harness command through the runtime dispatcher."""
    tool_name = command_id.lstrip("/").replace("/", "_").replace("-", "_")

    active_tools = _active_command_tools()
    if tool_name not in active_tools:
        return ToolResult.error(f"Unknown command: {command_id}")

    meta = active_tools[tool_name]

    # Fast path: read-only commands use direct handlers.
    if not meta.get("is_heavy", True) and tool_name in _FAST_HANDLERS:
        return _FAST_HANDLERS[tool_name](args)

    # Lightweight path: non-heavy commands that aren't fast-handled are dispatched
    # by loading their skills/<id>/SKILL.md and sending it as a subagent task.
    if not meta.get("is_heavy", True):
        return _handle_skill_dispatch(tool_name, meta, args, progress_callback)

    # Subagent dispatch (T010)
    if tool_name == "z_subagent_dispatch":
        return _handle_subagent_dispatch(args, progress_callback)

    # Heavy path: MCPDispatcher
    try:
        repo_root = _get_repo_root()
    except RuntimeError as exc:
        return ToolResult.error(str(exc))

    dispatcher = MCPDispatcher(repo_root, tool_name, args, progress_callback)
    return dispatcher.dispatch()


# ==========================================================================
# Skill-only dispatch (T019)
# ==========================================================================

def _handle_skill_dispatch(
    tool_name: str,
    meta: dict[str, Any],
    args: dict[str, Any],
    progress_callback: Any,
) -> ToolResult:
    """Dispatch a lightweight command by loading its skills/<id>/SKILL.md and
    sending it as a subagent task via the standard dispatcher.

    skills/ is the single source of command content (each skill lives at
    skills/<command-id>/SKILL.md).
    """
    command_id = meta.get("command_id", "").lstrip("/")
    if not command_id:
        return ToolResult.error(f"No command_id for '{tool_name}' — cannot dispatch")

    try:
        repo_root = _get_repo_root()
        cmd_file = repo_root / "skills" / command_id / "SKILL.md"
        if not cmd_file.exists():
            return ToolResult.error(f"Command file not found: skills/{command_id}/SKILL.md")

        skill_content = cmd_file.read_text()
        prompt = args.get("prompt", "")
        full_prompt = f"{skill_content}\n\n---\n\nTask: {prompt}" if prompt else skill_content

        # Re-use MCPDispatcher with the skill content as the prompt.
        enriched_args = {**args, "prompt": full_prompt}
        dispatcher = MCPDispatcher(repo_root, tool_name, enriched_args, progress_callback)
        return dispatcher.dispatch()
    except Exception as exc:
        return ToolResult.error(f"Skill dispatch failed: {exc}")


# ==========================================================================
# Subagent dispatch (T010)
# ==========================================================================

def _codex_native_subagent_hook(driver: object) -> Callable[..., Any] | None:
    """Return the explicit native subagent hook implemented by *driver*."""
    try:
        inspect.getattr_static(driver, "dispatch_native_subagent")
    except AttributeError:
        return None

    hook = getattr(driver, "dispatch_native_subagent", None)
    return hook if callable(hook) else None


def _try_codex_native_subagent_dispatch(
    repo_root: Path,
    provider_resolution: MCPProviderResolution,
    agent_def: AgentDef,
    prompt: str,
    route: Any,
    progress_callback: Any,
    slug: Any = None,
) -> ToolResult | None:
    """Dispatch through Codex native subagent support when explicitly proven.

    ``None`` means the native gate did not pass and callers must use the
    generic MCP dispatcher fallback unchanged.  Primitive evidence alone is
    not sufficient: the selected Codex driver must expose an actual native
    dispatch hook, otherwise this fails closed to the generic dispatcher.
    """
    if provider_resolution.host != "codex":
        return None

    try:
        from z_harness_cli.adapters.codex_parity_gate import (
            codex_native_subagent_dispatch_available,
        )
    except Exception:
        return None

    if not codex_native_subagent_dispatch_available():
        return None

    meta = _active_command_tools().get("z_subagent_dispatch")
    if meta is None:
        return ToolResult.error("Unknown command: z_subagent_dispatch")
    cmd_id: str = meta["command_id"]

    run_id = f"mcp-{uuid.uuid4().hex[:12]}"
    driver_or_error = _select_and_init_mcp_driver(
        repo_root,
        run_id,
        provider_resolution,
    )
    if isinstance(driver_or_error, ToolResult):
        return driver_or_error
    driver = driver_or_error
    try:
        native_hook = _codex_native_subagent_hook(driver)
        if native_hook is None:
            return None

        try:
            _report_progress(
                progress_callback,
                "dispatch",
                2,
                1,
                f"Dispatching Codex native agent {agent_def.name}",
                "z_subagent_dispatch",
            )
            with _scoped_z_harness_slug(slug):
                result = native_hook(
                    agent_name=agent_def.name,
                    prompt=prompt,
                    env=os.environ.copy(),
                    provider_config=provider_resolution.provider_config,
                    repo_root=str(repo_root),
                    run_id=run_id,
                    model=route.effective_model,
                    model_source=route.source,
                    model_route=route.route,
                    model_route_kind=route.route_kind,
                    model_thinking=route.thinking,
                    model_reasoning=route.reasoning,
                )
        except Exception as exc:
            return ToolResult.error(f"Dispatch error: {exc}")

        bridged = _bridge_dispatch_result(
            result,
            cmd_id,
            meta={
                "dispatch_path": "codex_native_subagent",
                "agent": agent_def.name,
                "provider": provider_resolution.provider_name,
                "host": provider_resolution.host,
                "effective_model": route.effective_model,
                "model_source": route.source,
                "model_route": route.route,
                "model_route_kind": route.route_kind,
            },
        )
        if bridged.status == "complete":
            _report_progress(
                progress_callback,
                "complete",
                2,
                2,
                "Complete",
                "z_subagent_dispatch",
            )
        return bridged
    finally:
        driver.teardown()


def _handle_subagent_dispatch(args: dict[str, Any], progress_callback: Any) -> ToolResult:
    """Dispatch a subagent via the LLM CLI.

    Args:
        agent: Agent name (from agents/*.md).
        prompt: Task for the subagent.
        model: Optional model override.

    Loads the agent definition, resolves the driver, and dispatches.
    """
    agent_name = args.get("agent", "")
    if not agent_name:
        return ToolResult.error("Missing required argument: 'agent'")

    try:
        agent_def = _load_agent(agent_name)
    except AgentNotFoundError as exc:
        return ToolResult.error(str(exc))
    except AgentDefinitionError as exc:
        return ToolResult.error(str(exc))

    prompt = args.get("prompt", "")
    if not prompt:
        return ToolResult.error("Missing required argument: 'prompt'")

    # Build the full prompt: agent template + user task.
    full_prompt = f"{agent_def.prompt_template}\n\n---\n\nTask: {prompt}"

    try:
        repo_root = _get_repo_root()
    except RuntimeError as exc:
        return ToolResult.error(str(exc))

    try:
        from runtime.dispatch.dispatcher import (
            load_model_routing_config,
            resolve_model_route,
            resolve_native_agent_model,
        )
        config_values = load_model_routing_config(repo_root)
        if args.get("model"):
            route = resolve_model_route(
                str(args["model"]),
                config_values,
                source="caller",
                override_applied=False,
                override_support="advisory",
            )
        else:
            route = resolve_native_agent_model(
                agent_def.name,
                agent_def.model_class or agent_def.model,
                config_values,
                override_applied=False,
                override_support="advisory",
            )
    except Exception as exc:
        return ToolResult.error(f"Model routing failed for agent '{agent_name}': {exc}")

    # Use the subagent dispatch tool name for provider resolution. Native MCP
    # subagent routing resolves the effective label here; Dispatcher telemetry
    # infers whether the selected provider can apply the model or only record it.
    enriched_args = {
        "prompt": full_prompt,
        "model": route.effective_model,
        "model_source": route.source,
        "model_route": route.route,
        "model_route_kind": route.route_kind,
        "model_thinking": route.thinking,
        "model_reasoning": route.reasoning,
        "slug": args.get("slug"),
    }

    provider_resolution = _resolve_mcp_provider(repo_root, "z_subagent_dispatch")
    if isinstance(provider_resolution, ToolResult):
        return provider_resolution

    native_result = _try_codex_native_subagent_dispatch(
        repo_root=repo_root,
        provider_resolution=provider_resolution,
        agent_def=agent_def,
        prompt=prompt,
        route=route,
        progress_callback=progress_callback,
        slug=args.get("slug"),
    )
    if native_result is not None:
        return native_result

    dispatcher = MCPDispatcher(repo_root, "z_subagent_dispatch", enriched_args, progress_callback)
    return dispatcher.dispatch(provider_resolution=provider_resolution)


# ==========================================================================
# Read-only command handlers (T005)
# ==========================================================================

def _handle_z_where(args: dict[str, Any]) -> ToolResult:
    try:
        plans_dir = os.environ.get("Z_HARNESS_PLAN_DIR",
                                   str(Path.home() / ".local" / "state" / "z-harness"))
        plans_path = Path(plans_dir) / "plans"
        if plans_path.exists():
            slugs = [d.name for d in plans_path.iterdir() if d.is_dir()]
            return ToolResult.success(
                content=f"{len(slugs)} active plan(s): {', '.join(slugs)}" if slugs else "No active plans.",
                meta={"plans": slugs, "plans_dir": plans_dir},
            )
        return ToolResult.success(content="No active plans found.", meta={"plans_dir": plans_dir})
    except Exception as exc:
        return ToolResult.error(f"z_where failed: {exc}")


def _handle_z_stats(args: dict[str, Any]) -> ToolResult:
    slug = args.get("slug", os.environ.get("Z_HARNESS_SLUG", ""))
    if not slug:
        return ToolResult.needs_input("Please provide a plan slug.", "slug_select")
    try:
        plans_dir = os.environ.get("Z_HARNESS_PLAN_DIR",
                                   str(Path.home() / ".local" / "state" / "z-harness"))
        metrics_path = Path(plans_dir) / "plans" / slug / "metrics.jsonl"
        if not metrics_path.exists():
            return ToolResult.error(f"No metrics found for slug '{slug}'")
        with open(metrics_path) as f:
            line_count = sum(1 for _ in f)
        return ToolResult.success(
            content=f"Plan '{slug}': {line_count} events logged.",
            meta={"slug": slug, "event_count": line_count},
        )
    except Exception as exc:
        return ToolResult.error(f"z_stats failed: {exc}")


def _handle_z_resume(args: dict[str, Any]) -> ToolResult:
    try:
        helper_root = _get_repo_root()
        target_repo_root = _resolve_caller_repo_root(args)
        raw_arguments = str(args.get("prompt") or "").strip()
        cmd = [sys.executable, str(helper_root / "scripts" / "resume-context.py")]
        if raw_arguments:
            cmd.extend(["--arguments", raw_arguments])
        if args.get("slug"):
            cmd.extend(["--slug", str(args["slug"])])
        cmd.extend(["--repo-root", str(target_repo_root), "--format", "json", "--noninteractive"])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(target_repo_root),
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "resume-context failed").strip()
            return ToolResult.error(detail)

        try:
            packet = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return ToolResult.error(f"resume-context returned invalid JSON: {exc}")

        ambiguity = packet.get("ambiguity") if isinstance(packet, dict) else {}
        needs_selection = bool(
            packet.get("status") == "needs_selection"
            or (isinstance(ambiguity, dict) and ambiguity.get("needs_selection"))
        )
        selected_target = packet.get("selected_target") if isinstance(packet, dict) else None
        summary = {
            "status": packet.get("status"),
            "needs_selection": needs_selection,
            "selected_target": selected_target,
            "suggested_selection_args": packet.get("suggested_selection_args", []),
            "safe_next_command": packet.get("safe_next_command"),
        }
        return ToolResult.success(
            content=json.dumps(summary, indent=2, sort_keys=True),
            artifacts={"resume_context": json.dumps(packet, indent=2, sort_keys=True)},
            meta={
                "packet": packet,
                "needs_selection": needs_selection,
                "selected_target": selected_target,
                "status": packet.get("status"),
                "interaction_mode": packet.get("interaction_mode"),
            },
        )
    except subprocess.TimeoutExpired:
        return ToolResult.error("resume-context timed out")
    except ValueError as exc:
        return ToolResult.error(str(exc))
    except Exception as exc:
        return ToolResult.error(f"z_resume failed: {exc}")



def _handle_z_handoff(args: dict[str, Any]) -> ToolResult:
    try:
        repo_root = _get_repo_root()
        result = subprocess.run(
            ["bash", str(repo_root / "scripts" / "write-handoff.sh")],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_root), env=os.environ,
        )
        if result.returncode == 0:
            return ToolResult.success(content=result.stdout or "handoff.json written.")
        return ToolResult.error(result.stderr or "handoff failed")
    except Exception as exc:
        return ToolResult.error(f"z_handoff failed: {exc}")

def _handle_z_clear_checkpoint(args: dict[str, Any]) -> ToolResult:
    try:
        repo_root = _get_repo_root()
        result = subprocess.run(
            ["bash", str(repo_root / "scripts" / "write-clear-checkpoint.sh")],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_root), env=os.environ,
        )
        if result.returncode == 0:
            return ToolResult.success(content=result.stdout or "clear checkpoint written.")
        return ToolResult.error(result.stderr or "clear checkpoint failed")
    except Exception as exc:
        return ToolResult.error(f"z_clear_checkpoint failed: {exc}")


def _handle_z_personas(args: dict[str, Any]) -> ToolResult:
    try:
        personas_dir = _get_repo_root() / "personas"
        if personas_dir.exists():
            personas = sorted(p.stem for p in personas_dir.glob("*.md") if p.name != "INDEX.md")
            return ToolResult.success(
                content=f"{len(personas)} personas: {', '.join(personas)}",
                meta={"personas": personas, "count": len(personas)},
            )
        return ToolResult.success(content="No personas directory found.")
    except Exception as exc:
        return ToolResult.error(f"z_personas failed: {exc}")


def _handle_z_update(args: dict[str, Any]) -> ToolResult:
    try:
        result = subprocess.run(
            ["bash", str(_get_repo_root() / "scripts" / "version.sh")],
            capture_output=True, text=True, timeout=10,
            cwd=str(_get_repo_root()), env=os.environ,
        )
        if result.returncode == 0:
            return ToolResult.success(
                content=(
                    "z_update is a read-only MCP version check. It does not mutate "
                    "the install. Run `z-harness update` or the host /z-update skill "
                    "explicitly to update.\n\n"
                    f"z-harness version info:\n{result.stdout.strip()}"
                ),
                meta={"updates_applied": False, "mode": "version_check"},
            )
        return ToolResult.error(result.stderr or "version check failed")
    except Exception as exc:
        return ToolResult.error(f"z_update failed: {exc}")


def _handle_z_export(args: dict[str, Any]) -> ToolResult:
    try:
        from z_harness_cli.commands.export import run as export_run
        export_run(
            ctx=None,  # export.run() accepts ctx but never reads it
            host=args.get("host"), all_hosts=args.get("all_hosts", False),
            in_place=args.get("in_place", False), out=args.get("out"),
            force=args.get("force", False),
        )
        return ToolResult.success(content="Export completed successfully.")
    except Exception as exc:
        return ToolResult.error(f"z_export failed: {exc}")


def _handle_z_detect(args: dict[str, Any]) -> ToolResult:
    try:
        from z_harness_cli.adapters.registry import detect_all
        hosts = detect_all()
        # detect_all() returns list of (adapter, DetectResult) tuples.
        installed = [
            {"name": adapter.name, "installed": detect.installed,
             "version": getattr(detect, "version", None)}
            for adapter, detect in hosts
        ]
        lines = [f"{h['name']}: {'✓' if h['installed'] else '✗'} {h['version'] or ''}".strip()
                 for h in installed]
        return ToolResult.success(content="\n".join(lines), meta={"hosts": installed})
    except Exception as exc:
        return ToolResult.error(f"z_detect failed: {exc}")


_FAST_HANDLERS: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
    "z_where": _handle_z_where, "z_stats": _handle_z_stats,
    "z_resume": _handle_z_resume,
    "z_handoff": _handle_z_handoff, "z_clear_checkpoint": _handle_z_clear_checkpoint,
    "z_personas": _handle_z_personas,
    "z_update": _handle_z_update, "z_export": _handle_z_export,
    "z_detect": _handle_z_detect,
}


# ==========================================================================
# Safe tool wrapper (T013 — error handling hardening)
# ==========================================================================

def _safe_tool(handler: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
    """Wrap a tool handler to catch all exceptions and return ToolResult.error.

    Ensures no tool ever throws an unhandled exception — every error path
    returns a valid ToolResult.
    """
    def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            return ToolResult.error(f"Internal error in {handler.__name__}: {exc}")
    wrapper.__name__ = handler.__name__
    wrapper.__doc__ = handler.__doc__
    return wrapper


# ==========================================================================
# Entry point
# ==========================================================================

def serve(*, transport: str = "stdio") -> None:
    """Start the z-harness MCP server on the given transport."""
    if mcp is None:
        raise RuntimeError("FastMCP is not installed. Install with: pip install fastmcp")
    mcp.run(transport=transport)


# ==========================================================================
# Auto-register all COMMAND_TOOLS as @mcp.tool() (T003 complete — T007 wiring)
# ==========================================================================

def _register_tools() -> None:
    """Register all COMMAND_TOOLS entries as FastMCP tools.

    Each tool's signature: async def z_plan(prompt, slug=None, ctx=None) -> ToolResult.
    Heavy commands use _dispatch_command (with progress); fast commands use direct handlers.
    """
    if mcp is None:
        return

    for tool_name, meta in _active_command_tools().items():
        _make_tool(tool_name, meta)


def _make_tool(tool_name: str, meta: dict[str, Any]) -> None:
    """Create and register a single MCP tool from its metadata."""
    description = meta.get("description", "")

    async def tool_fn(
        prompt: str = "",
        slug: str | None = None,
        repo_root: str | None = None,
        cwd: str | None = None,
        workspace_root: str | None = None,
        ctx: Any = None,
        _tool_name: str = tool_name,
        _meta: dict[str, Any] = meta,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"prompt": prompt}
        if slug:
            args["slug"] = slug
        if repo_root:
            args["repo_root"] = repo_root
        if cwd:
            args["cwd"] = cwd
        if workspace_root:
            args["workspace_root"] = workspace_root
        # Determine if progress callback is available via ctx.
        progress_cb = getattr(ctx, "report_progress", None) if ctx is not None else None

        handler = _safe_tool(lambda a=args, cb=progress_cb: _dispatch_command(_tool_name, a, cb))
        result = handler()
        return result.to_dict()

    tool_fn.__name__ = tool_name
    tool_fn.__doc__ = description
    mcp.tool()(tool_fn)


# Register tools at import time.
_register_tools()
