# Agents

> Last updated: 2026-05-24
> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md

## Overview

The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each agent is a markdown file with a frontmatter header (`name`, `description`, `tools`, `model`) that configures its context, available tools, and target model tier (Haiku for cheap mechanical work, Sonnet for implementation and review, Haiku-proxied consultant agents that shell out to an external provider CLI resolved via `scripts/resolve-provider.sh`). Agents are spawned fresh per invocation — isolated workers with no shared mutable state.

These agents decompose complex workflows into focused roles: planning (cluster-planner), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.

## Key entry points

- `agents/auditor.md:1` — `auditor` — Reads target files for one dimension (correctness | perf | cleanliness | design), writes `findings-<dimension>.md`, returns structured findings. Spawned in parallel by `/z-audit`.
- `agents/cluster-planner.md:1` — `cluster-planner` — Sub-planner for one cluster in a `/z-plan-split` run; produces SPEC.md + PLAN.md + TASKS.md, escalates risky decisions via `decision_needed` payload.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Classifies a single task block into `low | medium | high` tier; Haiku call; result stamped into TASKS.md by orchestrator.
- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Fast Haiku context-fetcher; reads `docs/llm/INDEX.json` and per-concept JSONs; optionally ripgreps `MEMORIES-FLAT.md`; returns ≤2 KB synthesis with file:line markers. Always dispatched before Explore.
- `agents/doc-updater.md:1` — `doc-updater` — Refreshes one concept's human-tier markdown + LLM-tier JSON to match current source files; dry-run by default; copies `memories[]` verbatim.
- `agents/external-lookup.md:1` — `external-lookup` — Haiku retrieval worker for web docs, public APIs, paginated JSON, and library docs outside training cutoff. Returns ≤3 KB STATUS-headed synthesis per `docs/llm/lookup-contract.json`. Enforces a verb-blocklist against mutating Bash commands before any invocation.
- `agents/implementer.md:1` — `implementer` — Executes a single task block (canonical `T<NNN>` or promoted `T-REV-NNN` / `T-MR-NNN`); runs common-critique self-check before returning `STATUS: ok`; stamps complexity tier from task block.
- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
- `agents/remote-runner.md:1` — `remote-runner` — Mechanical Haiku agent; rsyncs repo to per-(slug, task) sandbox on remote host, runs cargo/python builds, tails logs, runs read-only DB queries. Classifies commands as `needs-sandbox` vs `read-only-against-shared-state`. Enforces write-verb blocklist for DB queries.
- `agents/reviewer.md:1` — `reviewer` — Provider-agnostic proxy for the reviewer LLM (resolved via `scripts/resolve-provider.sh reviewer`). Scrutinizes diffs for bugs, spec violations, missed edge cases, DRY/KISS/SOLID. Emits `review_start` / `review_end` events; uses `scripts/check-timeout.sh` for liveness. Returns ≤8 KB findings (blockers + majors only).
- `agents/spec-precheck.md:1` — `spec-precheck` — Pre-flight Haiku verifier; checks SPEC.md factual claims (symbols, table names, config keys, file paths) against actual codebase before implementer runs. Returns `STATUS: ok` or `STATUS: spec_problem`.

## How it interacts with others

- `commands` — Commands are the orchestrators that compile configurations and spawn these subagents to perform specialized work.
- `skills` — Skills define the exact operational boundaries, steps, and telemetry wrappers that direct subagent execution.
- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
- `lookup-contract` — `external-lookup` conforms to the output contract defined in `docs/llm/lookup-contract.json`; if that file conflicts with the agent's inline prose, the JSON wins.

## Edge cases / gotchas

- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
- `external-lookup` enforces a verb-blocklist (Python regex) against every Bash command before execution. A matched pattern produces `STATUS: refused` with `mutation_blocked` rather than silently proceeding.
- `mr-reviewer` applies a two-stage dismissal filter: Jaccard token-overlap ≥ 0.6 against `dismissed_signatures.json` demotes severity and tags the finding; P0 findings are tagged but never demoted.
- `cluster-planner` has an anti-self-nesting guard as its first substantive action: it walks ancestor directories looking for `MANIFEST.md` and refuses if any ancestor contains one.
- Memory preservation is mandatory for `doc-updater`: it must copy existing `memories[]` arrays verbatim without altering, adding, or deleting entries.
- Many agents run in parallel (auditors, cluster-planners, implementers), requiring strict `log-phase.sh` telemetry brackets so wall-clock durations are traceable per invocation.

## Examples

- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
- `/z-implement-all` dispatches `spec-precheck` (Haiku) then `implementer` (Sonnet or Opus based on complexity tier) per task; after each implementer returns, `reviewer` is dispatched with the diff and relevant docs.
- `/z-mr-review` dispatches `mr-reviewer` with a diff path, STYLE.md path, and dismissed-signatures JSON; mr-reviewer fans out to available consultant voices and returns a merged fenced JSON findings block.
- `external-lookup` is dispatched by `/z-do` or any skill that needs current web docs; it writes raw artifacts to `z-harness/lookup-cache/<sha256>.raw` when the result exceeds the 3 KB budget.
