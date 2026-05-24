MODE: brainstorm

TOPIC:
Add an MR-style code-quality reviewer to z-harness (a Claude Code plugin of slash commands + subagents that orchestrate planning, implementation, and review of code changes using Claude + cross-LLM consults to Codex and Gemini). The reviewer is distinct from the existing correctness reviewers — it assumes correctness and instead targets the failure modes AI coding agents (Claude included) typically exhibit: excessive defensive error handling for impossible edge cases while missing real ones, repetitive low-signal tests, no abstraction / code length creep, sloppy naming / dead comments / drive-by reformatting, drift from a project STYLE.md. Supports an init subflow that authors STYLE.md interactively (with cross-LLM critique of the draft), can ingest an existing style guide, or accept natural language. Open question: optional add-on after /z-review-all, bundled into /z-review-all as an extra dimension, or standalone command.

REPO CONTEXT:
z-harness has these reviewer/consult agents in `agents/`:

1. **auditor.md** — Fresh-context Sonnet auditor for a single dimension (correctness | perf | cleanliness | design). Reads target files + optional rubric file, returns structured findings (Location / Evidence / Recommendation / Severity). Read-only — never edits. Spawned in parallel by /z-audit, one per dimension.

2. **codex-reviewer.md** — After Claude finishes implementing a task from z-harness/TASKS.md, this agent has Codex scrutinize the changes. Codex is told that Claude wrote the code and is asked to find bugs, spec violations, missed edge cases, and DRY/KISS/SOLID violations. Haiku-tier, uses `codex exec` CLI.

3. **gemini-consultant.md** — Consults Gemini (via `gemini` CLI in headless plan mode) for a second opinion on specific engineering decisions or to review a plan. Used during /z-plan and final review phases.

Existing review commands:
- `/z-review-all` — final-gate Gemini + Codex review of cumulative diff vs SPEC.md, after /z-implement-all.
- `/z-audit` — pre-existing component audit with dimensions including "cleanliness" and "design", supports an optional rubric file, parallel auditor per dimension, REPORT.md + TASKS.md output.
- `codex-reviewer` runs per-task inside /z-implement-all and /z-implement-next.

CRITICAL CONSTRAINT — Overlap Risk:
The existing `auditor` already supports `cleanliness` and `design` dimensions + optional rubric file. Any new MR-style reviewer must justify why it is not just "/z-audit --dimension=style --rubric=STYLE.md".

TASK:
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation.

Be bold and distinct — diversity across the three ideators is the point.
