"""
export-pi.py — Build pi (https://pi.dev) resources from z-harness commands,
agents, and skills.

Usage:
    python3 scripts/export-pi.py [--out exports/pi]

Unlike Cursor/Codex/agy, pi has no native subagent primitive — fan-out runs
through pi's *subagent extension*. So this exporter emits a richer tree:

    exports/pi/
    ├── AGENTS.md              # generated: fan-out preamble + agent index
    ├── CAPABILITIES.md        # copied asset
    ├── README.md              # copied asset
    ├── agents/<id>.md         # generated: every z-harness agent, frontmatter
    │                          #   normalized to pi tool names, model dropped
    │   └── explore.md         # copied asset (pi-only; no z-harness source)
    ├── prompts/<id>.md        # generated: commands + skills, Agent()/Skill()
    │                          #   call sites rewritten to subagent-tool hints
    └── extensions/subagent/   # copied asset: the vendored fan-out primitive

What's *generated* comes from the z-harness source of truth (commands/, agents/,
skills/). What's *copied* comes from scripts/pi_assets/ (the pi-only files that
have no z-harness source: the explore agent, the subagent extension, AGENTS
preamble, CAPABILITIES, README).

Normalization rules (vs Claude Code / z-harness source frontmatter):
  - tools:  Claude/CC names → pi names, lowercased.  Glob → find (pi has no
            Glob).  Unknown tokens are lowercased and kept (harmless no-ops in
            pi's --tools allowlist).
  - model:  dropped, so agents inherit pi's configured default (e.g.
            deepseek-v4-pro).  There is no Haiku tier in a deepseek-only setup;
            pin a model per-agent in scripts/pi_assets if you add a provider.

Body rewriting (commands/skills/agents):
  - Agent(subagent_type="X", ...) lines  → a `> [pi]` hint to use the subagent
    tool with that agent.  pi *can* fan out, so unlike the codex exporter this
    points at the real mechanism instead of just disclaiming it.
  - Skill("z-foo") lines  → a hint to run the /z-foo skill (pi loads z-harness
    skills natively as a package).
  - AskUserQuestion()/TaskCreate()/SubagentCreate() lines  → an inline-handling
    hint referencing CAPABILITIES.md.
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _REPO_ROOT / "scripts" / "pi_assets"

# export-common.py uses a hyphen so it is not directly importable; load via importlib.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common", _REPO_ROOT / "scripts" / "export-common.py"
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Frontmatter normalization
# ---------------------------------------------------------------------------

# Claude Code / z-harness tool name  →  pi tool name.
_TOOL_MAP = {
    "read": "read",
    "grep": "grep",
    "glob": "find",   # pi has no Glob; the find tool covers it
    "bash": "bash",
    "write": "write",
    "edit": "edit",
    "ls": "ls",
    "find": "find",
}

# Tools with no pi equivalent — dropped from the allowlist, recorded for the note.
_TOOL_UNSUPPORTED = {
    "agent", "task", "webfetch", "websearch", "notebookedit", "exitplanmode",
    "enterplanmode", "todowrite", "multiedit",
}


def normalize_tools(tools_raw: str | None) -> tuple[list[str], list[str]]:
    """Map a comma-separated frontmatter ``tools`` string to pi tool names.

    Returns ``(pi_tools, dropped)``.  Order is preserved; duplicates after
    mapping are collapsed.  Unknown tokens are lowercased and kept.
    """
    if not tools_raw:
        return [], []
    pi_tools: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for raw in tools_raw.split(","):
        tok = raw.strip()
        if not tok:
            continue
        key = tok.lower()
        if key in _TOOL_UNSUPPORTED:
            dropped.append(tok)
            continue
        mapped = _TOOL_MAP.get(key, key)
        if mapped not in seen:
            seen.add(mapped)
            pi_tools.append(mapped)
    return pi_tools, dropped


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

_AGENT_SUBTYPE_RE = re.compile(r'subagent_type\s*=\s*["\']([\w:-]+)["\']')
_AGENT_CALL_RE = re.compile(r"Agent\s*\(")
_SKILL_NAME_RE = re.compile(r'Skill\s*\(\s*["\']([\w:-]+)["\']')
_SKILL_CALL_RE = re.compile(r"Skill\s*\(")
_INLINE_TOOL_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(|EnterPlanMode\s*\(|ExitPlanMode\s*\("
)


def _rewrite_line(stripped: str, agent_names: set[str]) -> str | None:
    """Return a pi-flavored replacement for *stripped*, or None to keep it.

    Operates per line (like the codex exporter); multi-line call argument
    lines that do not themselves match are left as-is and documented in
    CAPABILITIES.md.

    *agent_names* is the set of real exported pi agent ids. A ``subagent_type``
    that is NOT one of them (e.g. the cross-vendor consult arms ``agy`` /
    ``cursor`` / ``codex-cli``, which are z-harness host dispatch targets, not
    portable agents) is rendered as a "no pi equivalent" note rather than a
    bogus subagent hint.
    """
    if _AGENT_CALL_RE.search(stripped):
        m = _AGENT_SUBTYPE_RE.search(stripped)
        if m:
            name = m.group(1).split(":")[-1]  # drop plugin namespace (z-harness:doc-fetcher → doc-fetcher)
            if name in agent_names:
                return (
                    f'> [pi] Use the subagent tool: {{ "agent": "{name}", '
                    f'"task": "..." }} (see CAPABILITIES.md).'
                )
            return (
                f'> [pi] Cross-vendor/consult dispatch ("{name}") — no pi subagent '
                f"equivalent; run it via that CLI yourself (see CAPABILITIES.md)."
            )
        return "> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md)."
    if _SKILL_CALL_RE.search(stripped):
        m = _SKILL_NAME_RE.search(stripped)
        if m:
            name = m.group(1).split(":")[-1]
            return f"> [pi] Run the /{name} skill."
        return "> [pi] Run the corresponding skill (see CAPABILITIES.md)."
    if _INLINE_TOOL_RE.search(stripped):
        return "> [pi] No native tool — handle inline by asking the user / tracking state yourself (see CAPABILITIES.md)."
    return None


def _rewrite_body(body: str, agent_names: set[str]) -> str:
    out: list[str] = []
    for line in body.splitlines(keepends=True):
        stripped = line.rstrip("\n\r")
        repl = _rewrite_line(stripped, agent_names)
        if repl is not None:
            leading = len(stripped) - len(stripped.lstrip())
            out.append(" " * leading + repl + "\n")
        else:
            out.append(line)
    return "".join(out)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _yaml_quote(value: str) -> str:
    """Quote a scalar for the flat YAML frontmatter the pi loader parses."""
    if re.search(r'[:\[\]{}#"\']', value) or value != value.strip():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_agent(entry: dict, agent_names: set[str]) -> tuple[str, list[str]]:
    """Render a z-harness agent as a pi agent file. Returns (text, dropped_tools)."""
    fm = entry["frontmatter"]
    name = fm.get("name", entry["id"])
    description = fm.get("description", "")
    pi_tools, dropped = normalize_tools(fm.get("tools"))

    lines = ["---\n", f"name: {name}\n"]
    if description:
        lines.append(f"description: {_yaml_quote(description)}\n")
    if pi_tools:
        lines.append(f"tools: {', '.join(pi_tools)}\n")
    # model intentionally omitted — inherit pi's configured default.
    lines.append("---\n\n")

    body = _rewrite_body(entry["body"], agent_names).lstrip("\n")
    return "".join(lines) + body, dropped


def _render_prompt(entry: dict, agent_names: set[str]) -> str:
    body = _rewrite_body(entry["body"], agent_names).lstrip("\n")
    return f"# /{entry['id']}\n\n{body}"


def _render_agents_index(agents: list[dict], explore_present: bool) -> str:
    """Auto-generated index appended to the AGENTS.md preamble."""
    lines = [
        "\n## Available subagents\n\n",
        "Dispatch any of these via the subagent tool "
        '(`subagent { "agent": "<name>", "task": "..." }`). '
        "They inherit pi's default model unless pinned.\n\n",
    ]
    rows = []
    if explore_present:
        rows.append(("explore", "Read-only fan-out recon; locates code, does not audit. pi-only."))
    for entry in agents:
        fm = entry["frontmatter"]
        desc = (fm.get("description", "") or "").strip().replace("\n", " ")
        if len(desc) > 140:
            desc = desc[:137] + "..."
        rows.append((fm.get("name", entry["id"]), desc))
    for name, desc in sorted(rows):
        lines.append(f"- **{name}** — {desc}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_agent(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("---\n"):
        errors.append(f"{path}: missing frontmatter fence")
        return errors
    fm, body = _COMMON_MOD._parse_frontmatter(text)
    if not fm.get("name"):
        errors.append(f"{path}: frontmatter missing 'name'")
    if not fm.get("description"):
        errors.append(f"{path}: frontmatter missing 'description'")
    if not body.strip():
        errors.append(f"{path}: empty body")
    return errors


def _validate_prompt(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    if not lines or not lines[0].startswith("# /"):
        errors.append(f"{path}: first line must be '# /<id>'")
    if not [ln for ln in lines[1:] if ln.strip()]:
        errors.append(f"{path}: body is empty")
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to pi resources."
    )
    p.add_argument("--out", default="exports/pi", help="Output root (default: exports/pi)")
    p.add_argument("--repo", default=str(_REPO_ROOT), help="Repo root")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    repo_root = Path(args.repo).resolve()
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = repo_root / out_root

    if not _ASSETS_DIR.is_dir():
        print(f"export-pi: ERROR: assets dir not found: {_ASSETS_DIR}", file=sys.stderr)
        return 1

    sources = enumerate_sources(repo_root)
    emitted: list[Path] = []
    errors: list[str] = []
    dropped_tools: dict[str, list[str]] = {}

    agents_dir = out_root / "agents"
    prompts_dir = out_root / "prompts"
    agents_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Real exported pi agent ids — used to distinguish a genuine subagent dispatch
    # from a cross-vendor consult arm when rewriting Agent() call sites.
    explore_src = _ASSETS_DIR / "agents" / "explore.md"
    explore_present = explore_src.is_file()
    agent_names = {e["frontmatter"].get("name", e["id"]) for e in sources["agents"]}
    if explore_present:
        agent_names.add("explore")

    # --- agents: normalize every z-harness agent into an executable pi agent ---
    for entry in sources["agents"]:
        text, dropped = _render_agent(entry, agent_names)
        path = agents_dir / f"{entry['id']}.md"
        path.write_text(text, encoding="utf-8")
        emitted.append(path)
        if dropped:
            dropped_tools[entry["id"]] = dropped

    # --- prompts: commands + skills, with subagent-aware rewrites ---
    command_ids = {e["id"] for e in sources["commands"]}
    for kind in ("commands", "skills"):
        for entry in sources[kind]:
            eid = entry["id"]
            export_id = f"{eid}-skill" if kind == "skills" and eid in command_ids else eid
            path = prompts_dir / f"{export_id}.md"
            path.write_text(_render_prompt(entry, agent_names), encoding="utf-8")
            emitted.append(path)

    # --- copy curated pi-only assets ---
    if explore_present:
        shutil.copy2(explore_src, agents_dir / "explore.md")
        emitted.append(agents_dir / "explore.md")

    ext_src = _ASSETS_DIR / "extensions"
    if ext_src.is_dir():
        dst = out_root / "extensions"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(ext_src, dst)

    for asset in ("README.md", "CAPABILITIES.md"):
        src = _ASSETS_DIR / asset
        if src.is_file():
            shutil.copy2(src, out_root / asset)

    # --- AGENTS.md = preamble + generated index ---
    preamble_src = _ASSETS_DIR / "AGENTS.preamble.md"
    preamble = preamble_src.read_text(encoding="utf-8") if preamble_src.is_file() else "# z-harness fanout rules (pi)\n"
    index = _render_agents_index(sources["agents"], explore_present)
    (out_root / "AGENTS.md").write_text(preamble.rstrip("\n") + "\n" + index, encoding="utf-8")

    # --- validate ---
    for path in emitted:
        if path.parent.name == "agents":
            errors.extend(_validate_agent(path))
        elif path.parent.name == "prompts":
            errors.extend(_validate_prompt(path))
    caps = out_root / "CAPABILITIES.md"
    if caps.exists():
        errors.extend(f"CAPABILITIES.md: {e}" for e in validate_capabilities(caps))
    else:
        errors.append("CAPABILITIES.md: missing (expected scripts/pi_assets/CAPABILITIES.md)")

    # --- summary ---
    n_agents = len(sources["agents"]) + (1 if explore_present else 0)
    n_prompts = len(emitted) - n_agents
    print(f"export-pi: {len(emitted)} files written to {out_root}")
    print(f"  agents:  {n_agents} (in {agents_dir})")
    print(f"  prompts: {n_prompts} (in {prompts_dir})")
    print(f"  extension + AGENTS.md + CAPABILITIES.md + README.md copied/generated")
    if dropped_tools:
        print("  normalization — dropped unsupported tools:")
        for aid, tools in sorted(dropped_tools.items()):
            print(f"    {aid}: {', '.join(tools)}")

    if errors:
        print(f"\nValidation errors ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1
    print(f"  all {len(emitted)} generated files passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
