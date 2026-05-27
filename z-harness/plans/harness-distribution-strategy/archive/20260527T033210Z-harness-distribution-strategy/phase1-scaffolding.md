# Phase 1 Scaffolding — harness-distribution-strategy

## Topic
Rethink how z-harness is distributed and delivered to non-Claude-Code hosts (Codex CLI, Antigravity, Cursor, future harnesses). Today: per-host adapter scripts (`export-codex.py`, `export-agy.py`, `export-cursor.py`) translate `commands/`, `agents/`, `skills/` into target-specific surfaces; `install.sh` symlinks or tarball-extracts the result into each host's plugin directory; `/z-update` refreshes it. The cost is a constant update loop — every time a target host's skill/command/agent format shifts, the adapter has to chase it, and unsupported constructs (subagent dispatch, AskUserQuestion, provider registry) are degraded to limitation comments rather than working features.

User's question: would it be better to package z-harness as a **standalone program that wraps the underlying agent CLI** (e.g. wrap `claude` or `codex` directly), so we own the distribution surface, the UI, and the notifications? Could this work without degrading the underlying harness's performance (prompt cache locality, tool dispatch, TUI behavior)? What are the realistic alternatives — MCP server, sidecar process, library injection, native plugin protocols — and what does each cost?

## Doc-fetcher synthesis (verbatim)

### multi-ide-exports
Distribution pipeline: Z-harness exports to three non-Claude-Code hosts via Python adapter scripts (`export-codex.py`, `export-agy.py`, `export-cursor.py`) that read the source of truth in `commands/`, `agents/`, and `skills/*/SKILL.md` and emit target-specific surfaces. Each adapter validates its output against per-target `CAPABILITIES.md` and replaces unsupported constructs (subagent dispatch, skill invocation, AskUserQuestion, provider registry) with explicit HTML/Markdown limitation comments rather than silently dropping them.

Exported surfaces:
- Codex CLI: prompt files per command (header `# /<id>`), consolidated `AGENTS.md`, per-skill prompts; collisions get a `-skill` suffix.
- Antigravity (agy): `.agent/workflows/<id>.md` (custom chat mode), `.agent/rules/<id>.md` (agents with `always_on` or `model_decision` trigger), flat prompts, `agy-plugin.yaml` manifest.
- Cursor: `.mdc` rules with YAML frontmatter; body rewriting replaces Agent/Skill calls with limitation comments.

Cross-host couplings live in `scripts/export-common.py` (shared enumeration, validation), loaded via `importlib` because hyphenated filenames prevent direct import. `/z-export` slash command runs all three adapters sequentially.

Key files:
- `scripts/export-agy.py:71` — body rewriting (replace Agent/Skill/AskUserQuestion/TaskCreate call sites with HTML comment)
- `scripts/export-common.py:107` — enumerate commands/agents/skills into kind-keyed dict
- `scripts/audit-tarball.sh:75` — reject forbidden patterns before tarball release

Invariants / gotchas:
- Source of truth is `commands/`, `agents/`, `skills/*/SKILL.md` — never the `exports/` tree.
- Unsupported constructs replaced line-by-line, never silently dropped.
- agy hard-codes implementer/reviewer/auditor/mr-reviewer/remote-runner as `always_on`; others use `model_decision`.
- Antigravity workflow bodies have ~12,000 character limit; several z-harness commands exceed it (e.g., `/z-plan`).

### z-update
Update mechanism: Two modes — symlink (repo clones) and tarball (extracted plugin dirs). `install.sh` detects mode by checking for `.git` and symlinks; `/z-update` slash command or `z-update` skill triggers update. Symlink mode: `git pull --ff-only` (aborts if dirty or diverged). Tarball mode: atomic swap.

install.sh behavior:
- Claude Code symlink: `~/.claude/plugins/z-harness@zeke-tools -> <repo-path>`.
- Codex symlink: `~/plugins/z-harness -> <repo-path>` + writes `~/.agents/plugins/marketplace.json`; if `codex` on PATH, runs `codex plugin add z-harness@personal`.
- Tarball: downloads from `Z_HARNESS_RELEASE_URL` and extracts.
- `--force` removes non-symlink existing install via `rm -rf`.

Key files:
- `install.sh:95` (`install_claude_symlink`)
- `install.sh:149` (`install_codex_symlink`)
- `commands/z-update.md` — locate plugin root, detect mode, pull or atomic-swap, emit `harness_updated` event
- `scripts/bundle-plugin.sh` — build dist tarball (excludes `plans/archive/`, `exports/`, `providers.json`, legacy plan dirs)
- `scripts/version.sh` — emits JSON with git SHA, dirty flag, branch, tag

Invariants / gotchas:
- No autoupdate — all updates user-triggered.
- Symlink mode requires clean working tree.
- Tarball release URL is a placeholder; `Z_HARNESS_RELEASE_URL` env var must be set.
- Codex caches plugin skills; new Codex thread required after update.
- `harness_updated` event with `old_version`/`new_version` written to `metrics.jsonl`.

## RESEARCH.md
Not present.

## Sibling-plan note
A `portable-harness` plan already exists at `z-harness/plans/portable-harness/` covering the *current* install.sh + provider-registry approach. This brainstorm is a meta-question about whether that approach is still the right shape — not a duplicate.
