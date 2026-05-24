# Phase 0 — Premise check

## Task (as stated)
1. Inside z-harness repo, plans should not pollute top of `z-harness/`.
2. Make the harness portable:
   (a) cleaner / instant updates,
   (b) skills usable from Cursor, Codex CLI, Antigravity (agy), not just Claude Code,
   (c) any model the user wants — user-supplied CLI command, or Haiku subagent discovers it.

## Premise check outcome — accepted with clarifications

**Issue 1 — folder layout.** User confirmed: plan dirs (`brainstorm-and-research/`, `doc-memories/`, etc.) sitting at the top of `z-harness/` alongside infra (`archive/`, `metrics.jsonl`) is the pollution. Fix: move to `z-harness/plans/<slug>/`. Touches every command/skill that writes to `z-harness/<slug>/`, plus `scripts/log-event.sh` if it constructs the path itself.

**Issue 2 — scope shape.** User opted for one big plan, accepting >5 consult-flagged decisions. Will require pushing the bundle cap and likely doing two consult rounds.

**IDE targets confirmed:** Cursor (Rules), Codex CLI (its prompt format), Antigravity (= `agy` CLI from Google). Claude Code remains source-of-truth; lossless multi-IDE compile is unlikely — exports will have documented fidelity gaps.

**Multi-model:** "any model the user supplies" — provider abstraction for consultants/subagents so the user can register e.g. a `claude`, `gpt-5`, `gemini`, or arbitrary CLI. Optional Haiku discovery subagent that scans PATH for known LLM CLIs.

**Instant updates:** ambiguous — most likely "edit plugin → effect is immediate without re-install" (i.e. symlinked source-of-truth, or a single-file install). Will pin this in Phase 2 decisions.

## Premise concerns surfaced (none blocking, raised earlier; user resolved them)
- Premise "plans don't have a sub-folder" was literally false (they do — `z-harness/<slug>/`); user clarified the real complaint.
- Bundling 3 portability sub-features risks task explosion; user accepted the risk.
- Multi-IDE lossless compile probably infeasible; "best-effort with fidelity caveats" is the implicit accepted framing.

## What I take the goal to be (one paragraph)
Restructure the harness so (a) plan output lives under `z-harness/plans/<slug>/` to keep the plugin repo dogfood clean; (b) command/skill source files have a portable representation that can be exported to Cursor Rules, Codex CLI prompts, and Antigravity (agy) format with documented fidelity loss; (c) consultants and subagents address LLM providers through a user-configurable registry rather than hardcoded `gemini` / `codex` CLIs, with an optional Haiku-driven discovery step; (d) updates to the harness propagate without per-IDE re-install (likely via symlinked install or a single-file fetch).
