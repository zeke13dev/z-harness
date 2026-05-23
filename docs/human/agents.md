# Agents

> Last updated: 2026-05-23
> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/codex-consultant.md, agents/codex-reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/gemini-consultant.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md

## Overview
The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each subagent is configured with a tailored system prompt, dedicated tools, and appropriate model profiles (typically Sonnet or specialized consultant roles) to execute discrete, high-discipline steps.

These agents act as isolated workers spawned in parallel or series by orchestration commands. By decomposing complex workflows—such as code generation, planning, security checks, and code reviews—into focused subagent roles with precise scopes, the system minimizes context drift and maximizes execution quality.

## Key entry points
- `agents/auditor.md:1` — `auditor` — Scrutinizes target codebase files across correctness, perf, cleanliness, or design dimensions.
- `agents/cluster-planner.md:1` — `cluster-planner` — Resolves specialized technical sub-tasks during large-scale workspace planning.
- `agents/codex-consultant.md:1` — `codex-consultant` — Performs secondary LLM critiques to resolve plan ambiguities and technical risks.
- `agents/codex-reviewer.md:1` — `codex-reviewer` — Scrutinizes diffs from code-generation agents against safety, rubric, and styling guidelines.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Classifies task files based on implementation complexity to guide orchestrator constraints.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Retrieves, filters, and ranks documentation concepts relevant to an ongoing plan phase.
- `agents/doc-updater.md:1` — `doc-updater` — Rebuilds or updates concept documentation files to match source files under maintain-docs.
- `agents/gemini-consultant.md:1` — `gemini-consultant` — Performs primary Gemini-level plan critiques and risk evaluations.
- `agents/implementer.md:1` — `implementer` — Executes the actual code-writing tasks under discrete plan targets.
- `agents/remote-runner.md:1` — `remote-runner` — Executes verification tests and builds inside remote sandboxes for safety.
- `agents/spec-precheck.md:1` — `spec-precheck` — Validates specifications, task lists, and designs for completeness before implementation.

## How it interacts with others
- `commands` — Commands are the orchestrators that compile configurations and spawn these subagents to perform specialized work.
- `skills` — Skills define the exact operational boundaries, steps, and telemetry wrappers that direct subagent execution.
- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.

## Edge cases / gotchas
- Many agents operate in parallel (e.g., auditors, cluster planners, and implementers) which requires strict telemetry event logging using `log-phase.sh` to prevent execution tracing conflicts.
- Memory preservation is mandatory for `doc-updater`: it must copy existing `memories[]` arrays verbatim without altering, adding, or deleting entries.

## Examples
- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review.
