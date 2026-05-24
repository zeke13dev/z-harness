## Phase 1 Scaffolding

### Topic
Add an MR-style code-quality reviewer to z-harness (a Claude Code plugin of slash commands + subagents that orchestrate planning, implementation, and review of code changes using Claude + cross-LLM consults to Codex and Gemini). The reviewer is distinct from the existing correctness reviewers — it assumes correctness and instead targets the failure modes AI coding agents (Claude included) typically exhibit: excessive defensive error handling for impossible edge cases while missing real ones, repetitive low-signal tests, no abstraction / code length creep, sloppy naming / dead comments / drive-by reformatting, drift from a project STYLE.md. Supports an init subflow that authors STYLE.md interactively (with cross-LLM critique of the draft), can ingest an existing style guide, or accept natural language. Open question: optional add-on after /z-review-all, bundled into /z-review-all as an extra dimension, or standalone command.

### Repo Context (Scaffolding)
- codex-reviewer.md — post-implementation correctness scrutiny (Codex), per-task in /z-implement-all.
- codex-consultant.md, gemini-consultant.md — cross-LLM second opinions during plan + final review.
- auditor.md — used by /z-audit, parallel one-per-dimension (correctness | perf | cleanliness | design). Read-only, structured Location/Evidence/Recommendation/Severity findings.
- /z-review-all — final-gate Gemini + Codex review of cumulative diff vs SPEC.md, after /z-implement-all.
- /z-audit — pre-existing component audit with dimensions including "cleanliness" and "design", supports an optional rubric file, parallel auditor per dimension, REPORT.md + TASKS.md output.
- codex-reviewer runs per-task inside /z-implement-all and /z-implement-next.
- No STYLE.md anywhere; no global style guide concept yet. Greenfield.
- OVERLAP RISK: auditor already supports cleanliness and design dimensions + optional rubric file. Must justify why not just "/z-audit --dimension=style --rubric=STYLE.md".

### Doc-fetcher synthesis
STATUS: no_docs (docs/llm/INDEX.json not present)

### Explore synthesis
Not dispatched (Z_HARNESS_BRAINSTORM_EXPLORE not set)

### RESEARCH.md
Not present
