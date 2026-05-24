# Phase 1 — Context (from doc-fetcher synthesis)

## Current state — load-bearing facts

- **Plan output convention:** every command writes to `z-harness/<slug>/{SPEC,PLAN,TASKS}.md` and `z-harness/<slug>/archive/<run-id>/events.jsonl`. The path is built from the `Z_HARNESS_SLUG` env var, set in every command's Setup section.
- **Affected command files for relocation:** `commands/z-plan.md` (lines 24, 35, 50–58), `commands/z-audit.md`, `z-test.md`, `z-implement-all.md`, `z-mr-review.md`, `z-improve.md`, `z-brainstorm.md`, `z-research.md`, `z-maintain-docs.md`. Plus `scripts/log-event.sh`, `scripts/log-phase.sh`. Invariant in `docs/llm/commands.json:197` must also be updated.
- **Consultants are CLI-hardcoded:** `agents/codex-consultant.md` calls `codex exec`; `agents/gemini-consultant.md` calls `gemini -p ... --approval-mode plan`. Both Haiku, read-only.
- **Plugin install:** `/plugin marketplace add ...` then `/plugin install z-harness@zeke-tools`. Plugin root via `ANTIGRAVITY_PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT` env. No symlink option, no single-file fetch.
- **Subagent model knob:** per-task `**Complexity:**` stamp in TASKS.md (low/medium → Sonnet, high → Opus, retries → Opus). Already configurable.

## External unknowns (deferred to implementation tasks)

- Exact Cursor Rules file format (`.cursorrules` or `.cursor/rules/*.mdc`).
- Codex CLI's "custom prompt" / skill registration mechanism (if any).
- Antigravity (`agy`) plugin manifest schema.

These are best resolved by a `WebFetch` + smoke-test cycle during implementation, not during planning.

## Doc-drift signals
None reported by doc-fetcher.
