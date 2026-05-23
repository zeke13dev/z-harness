# Phase 1 — Premise + Context

## Problem (1 paragraph)

Today `/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks burn a wasted Sonnet cycle (often producing a diff Codex flags with blockers) before retry. The harness already has a `Z_HARNESS_RETRY_UPGRADE=opus` env var and an opt-in `**Complexity:** high` task marker, but [commands/z-implement-all.md:168](../../commands/z-implement-all.md) explicitly notes this is only an *advisory care signal* read by the implementer's prompt — not a real model override. The Agent tool now supports a per-call `model` override; this fix wires that to a Haiku-classifier-stamped `**Complexity:**` tier on each task block.

## Context (1 paragraph)

Files affected: `agents/implementer.md` (frontmatter + retry-care prose), `commands/z-plan.md` (Phase 8 emits TASKS.md), `commands/z-amend.md` (full-mode TASKS.md edits), `commands/z-implement-all.md` (line 158 implementer dispatch + retry-bump block), `commands/z-implement-next.md` (single-task variant). `/z-plan-light` Phase 7 runs implementation inline in the orchestrator thread (no implementer subagent), so light mode is **out of scope** — the classifier is irrelevant there. `/z-amend` light-mode also skipped for the same reason. Scope drops from 6 → 5 files. New file: `agents/complexity-classifier.md` (Haiku).

## Premise check

- **Is this a real problem?** Yes. Documented in z-implement-all.md:168 — the current "Z_HARNESS_RETRY_UPGRADE=opus" env var is acknowledged as a stub that does not actually change the model. Hard tasks today must fail Sonnet review once before getting Opus-level care.
- **Will the fix solve it?** Yes. The `Agent(...)` tool already has a `model` parameter (verified in tool schema: `"model": {"description": "Optional model override for this agent..."`). Wiring it removes the "this is aspirational" caveat.
- **Better path?** Auto-inference from code metrics is a v2; user-stamped + Haiku-classifier-stamped is simpler v1.
- **Cost of misclassifying:** down (high→sonnet) = same as today's baseline. Up (medium→opus) = ~3-4x token cost on that task. Asymmetric in our favor since retry-bump catches downward misses.

## Auto-bail check

- Files: 5 (under threshold of 5+). Tight.
- Non-obvious decisions: 1 (plan-time vs dispatch-time stamping). Under threshold of 2.
- Cross-module: no — single repo, harness self-edit.
- → Continue in light mode.
