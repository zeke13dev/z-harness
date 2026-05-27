MODE: brainstorm

## Topic
How should z-harness be distributed and delivered to non-Claude-Code agent hosts (Codex CLI, Antigravity, Cursor, future harnesses)? 

**Current state:** z-harness uses per-host Python adapter scripts (`export-codex.py`, `export-agy.py`, `export-cursor.py`) that translate `commands/`, `agents/`, `skills/` into each host's native plugin format. An `install.sh` symlinks or tarball-extracts the result into each host's plugin directory. The `/z-update` command refreshes it.

**The cost:** constant update churn. Every time a target host's plugin/skill/command format shifts, the adapter has to chase it. Unsupported constructs (subagent dispatch, AskUserQuestion, provider registry) degrade to limitation comments rather than working features. For example, Antigravity workflow bodies have a ~12,000-character limit that already breaks `/z-plan`.

**User's leading hypothesis:** package z-harness as a **standalone program that wraps the underlying CLI** (e.g., spawn `claude` or `codex` as subprocess, intercept I/O, own the UI and notifications). Would this work without degrading performance (prompt cache locality, tool dispatch, TUI behavior)?

## Phase 1 Scaffolding (abridged)

**Current architecture:**
- Source of truth: `commands/`, `agents/`, `skills/*/SKILL.md`
- Per-target exporters: `scripts/export-{codex,agy,cursor}.py` (validate against per-target `CAPABILITIES.md`, replace unsupported constructs with HTML comments)
- Install modes: symlink (repo clones) or tarball (extracted plugin dirs)
- Update mechanism: `/z-update` command triggers git pull or atomic swap

**Exported surfaces:**
- Codex CLI: prompt files per command (`# /<id>`), consolidated `AGENTS.md`, per-skill prompts
- Antigravity: `.agent/workflows/<id>.md` (custom chat mode), `.agent/rules/<id>.md` (agents), flat prompts, `agy-plugin.yaml`
- Cursor: `.mdc` rules with YAML frontmatter; unsupported calls replaced with limitation comments

**Key gotcha:** agy hard-codes 5 agents as `always_on` (implementer, reviewer, auditor, mr-reviewer, remote-runner); others use `model_decision`. Several z-harness commands exceed the ~12k-char workflow body limit.

## Ask

Return exactly five sections: **(1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind.** Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
