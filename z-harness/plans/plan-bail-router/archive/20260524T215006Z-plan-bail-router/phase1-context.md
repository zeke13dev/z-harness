# Phase 1: Context

The current plan-family routing is ad hoc. `/z-do` bails to `/z-plan-light` or `/z-plan` based on file count and non-obvious decisions; `/z-plan-light` bails upward to `/z-plan`; `/z-plan-split` refuses topics with fewer than two or more than six cluster seams; `/z-research` and `/z-brainstorm` only recommend likely next steps after producing precontext artifacts; `/z-audit-plan` assumes an existing plan and routes findings to `/z-amend`, `/z-plan`, or implementation choices after the audit. There is no shared router rubric, no common event name for plan-family route decisions, and no explicit prevention of routing loops.

The source surfaces that matter are the command files under `commands/` and the mirrored operational checklists under `skills/`. Exports are generated from these source surfaces via `scripts/export-*.py`, so implementation should edit the canonical `commands/`, `skills/`, and docs/memory sources, then run `/z-export` or the export scripts rather than hand-editing generated target files where possible. Existing docs are stale and omit `z-audit-plan` from some command/skill indexes, so the implementation plan should include doc-index updates and a post-plan `/z-maintain-docs` pass.

Useful constraints:

- Commands must remain usable as standalone prompts after export; they cannot rely on runtime includes.
- The router should recommend handoff or halt, not silently jump into another command and mutate incompatible artifacts.
- Routing must be acyclic per run: a command can recommend a better-fit variant, but the next invocation should record prior route context to avoid ping-pong.
- The optional LLM/classifier path should be reserved for ambiguous cases; deterministic thresholds should handle obvious tiny, medium, huge, unknown-terrain, and existing-plan cases.
- Plan-family exits should emit structured telemetry so `/z-improve` and future docs maintenance can see why a command bailed.
