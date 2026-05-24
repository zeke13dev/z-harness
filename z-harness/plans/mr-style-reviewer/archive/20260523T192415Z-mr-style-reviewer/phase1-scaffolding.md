# Phase 1 scaffolding — mr-style-reviewer

## Topic

Add an **MR-style reviewer** to z-harness that is **separate from `/z-review-all`**. Working assumption:

- `/z-review-all` and `codex-reviewer` cover **correctness** (bugs, spec drift, missed edge cases).
- The new reviewer covers **code quality / taste** — the things AI coding agents (including Claude) typically do badly:
  - Excessive defensive error handling / checks for impossible edge cases, while missing real substantive ones.
  - Repetitive / low-signal tests (testing the same path five ways, no coverage of the genuinely risky case).
  - Lack of abstraction; copy-paste; gratuitous code length growth.
  - Sloppy naming, dead comments, drive-by reformatting, leftover scaffolding.
  - Drift from a project STYLE.md (mix of local repo STYLE.md and a global one).
- It supports an **init** subflow: dynamic conversation with the user to author STYLE.md for a project. Cross-LLM critique of the draft STYLE.md to surface omissions. Can also ingest an existing style guide (parse + improve) or accept pure natural language.
- Open question: is this an **optional add-on after `/z-review-all`**, **bundled into `/z-review-all`** as an extra dimension, or a **fully standalone command** (e.g. `/z-mr-review` + `/z-style-init`)?

## Repo context (relevant)

Existing reviewer/consult agents in `agents/`:
- `codex-reviewer.md` — post-implementation correctness scrutiny (Codex). Used by `/z-implement-all` per task.
- `codex-consultant.md`, `gemini-consultant.md` — cross-LLM second opinions, used during plan + final review.
- `auditor.md` — used by `/z-audit`, parallel one-per-dimension (correctness | perf | cleanliness | design). Read-only, structured findings.
- No existing STYLE.md anywhere. No global style guide concept yet.

Existing review commands:
- `/z-review-all` — final-gate Gemini + Codex review of cumulative diff against SPEC.md, after `/z-implement-all`.
- `/z-audit` — pre-existing component audit with dimensions including "cleanliness" and "design" (parallel auditor per dimension, REPORT.md + TASKS.md output).
- Per-task: `codex-reviewer` runs inside `/z-implement-all` and `/z-implement-next`.

Note the **overlap risk** brainstormers should weigh: the existing `auditor` agent already accepts `cleanliness` and `design` dimensions, and `/z-audit` already supports an optional rubric file. The new reviewer must justify why it is not just "/z-audit --dimension=style with a STYLE.md rubric".

## No RESEARCH.md, no docs/llm/INDEX.json

Greenfield brainstorm. No prior research, no doc-fetcher synthesis.
