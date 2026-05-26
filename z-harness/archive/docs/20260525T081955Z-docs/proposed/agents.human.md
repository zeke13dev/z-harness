# Agents

> Last updated: 2026-05-25
> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md

## Overview

The agents concept covers the specialized subagent prompt files under `agents/`. Each file declares an isolated worker role through frontmatter (`name`, `description`, `tools`, `model`) and then defines the inputs, execution procedure, telemetry, and parseable return contract that the surrounding z-harness commands rely on.

The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), correctness review (`reviewer`), code-quality review (`mr-reviewer`), spec validation (`spec-precheck`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), auditing (`auditor`), and cross-LLM consultation (`consultant-primary`, `consultant-secondary`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.

## Key entry points

- `agents/auditor.md:1` — `auditor` — Read-only single-dimension auditor for correctness, performance, cleanliness, or design; writes `findings-<dimension>.md` and returns counts.
- `agents/cluster-planner.md:1` — `cluster-planner` — Focused `/z-plan-split` leaf planner; writes cluster SPEC.md, PLAN.md, TASKS.md, and escalates risky decisions one at a time.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Cheap task classifier that returns `low`, `medium`, or `high` for model routing.
- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; supports planning, review, debug, brainstorm, research, docs, test, and MR-review modes.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Provider-agnostic secondary consultant proxy with the same mode surface as the primary consultant and a distinct provider role.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Read-only docs context fetcher over `docs/llm/INDEX.json`, concept JSONs, and optional `MEMORIES-FLAT.md` searches.
- `agents/doc-updater.md:1` — `doc-updater` — Refreshes one concept's human and LLM docs; dry-run by default; must preserve existing `memories[]` verbatim.
- `agents/external-lookup.md:1` — `external-lookup` — Fresh-context web/API retrieval worker that returns the fixed lookup-contract envelope and refuses mutating commands.
- `agents/implementer.md:1` — `implementer` — Implements exactly one task block, reads relevant plan/docs context, performs a self-check, and returns structured status.
- `agents/mr-reviewer.md:1` — `mr-reviewer` — Branch-diff code-quality reviewer that merges inline and consultant-voice findings into a fenced JSON payload.
- `agents/planning-router.md:1` — `planning-router` — Cheap read-only advisory router for ambiguous planning-family route decisions; returns an exact parseable route contract.
- `agents/remote-runner.md:1` — `remote-runner` — Mechanical remote verifier for sandboxed builds/tests, paper service checks, logs, disk, and read-only DB queries.
- `agents/reviewer.md:1` — `reviewer` — Provider-agnostic correctness/spec reviewer proxy for completed implementation tasks.
- `agents/spec-precheck.md:1` — `spec-precheck` — Read-only preflight checker that validates SPEC claims about existing files, symbols, config keys, and schemas.

## How it interacts with others

- `commands` — Commands are the orchestrators that decide when to spawn each agent, pass compact inputs, parse exact return shapes, and write user-facing artifacts.
- `skills` — Skills mirror command behavior across agent CLIs and encode the operational gates that rely on these subagent contracts.
- `scripts` — Agents call shared scripts for telemetry, provider resolution, timeout detection, plan path handling, and remote sandbox sync.
- `lookup-contract` — `external-lookup` must follow the canonical envelope in `docs/llm/lookup-contract.json`; the JSON contract wins over inline prose if they diverge.

## Edge cases / gotchas

- `consultant-primary`, `consultant-secondary`, and `reviewer` are Haiku proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
- The proxy agents source `scripts/check-timeout.sh` so `$TIMEOUT_CMD` is available when GNU timeout or gtimeout exists, and they emit start events before provider calls so liveness checks can see hangs.
- `planning-router` is advisory only. It reads compact caller-supplied signals, performs no shell work, writes nothing, and returns `ask_user` for route-loop or conflicting-signal risk.
- `doc-updater` is the structural refresh path, not the memory authoring path. It must copy `memories[]` exactly; `/z-suggest-memory` is the only intended authoring/editing path for memories.
- `external-lookup` checks every Bash command against a mutation verb-blocklist before execution and returns `STATUS: refused` instead of trying to sanitize a risky command.
- `remote-runner` is mechanical. It can run sandboxed builds and read-only shared-state checks, but interpretive debugging or DB analysis belongs to the main reasoning thread.
- `mr-reviewer` reviews quality, not correctness, and does not write MR-REVIEW.md itself; the orchestrator parses the returned JSON and writes the artifact.
- `cluster-planner` refuses nested plan-split output by checking ancestor directories for `MANIFEST.md` before substantive repo reads or writes.
- `spec-precheck`, `implementer`, and `reviewer` read relevant LLM-tier docs themselves so stale spec references can be caught before or during task execution.

## Examples

- `/z-plan` and related plan-family commands dispatch `planning-router` only when deterministic route signals conflict or confidence is too low for an automatic route.
- `/z-plan-split` dispatches `cluster-planner` once per cluster; each cluster planner may call `doc-fetcher` and `complexity-classifier` but not external consultants.
- `/z-implement-all` dispatches `spec-precheck`, then `implementer`, optional `remote-runner`, and finally `reviewer` for each task batch.
- `/z-maintain-docs` dispatches `doc-updater` for stale concepts and can then audit the proposed update with both consultant proxies.
- `/z-mr-review` dispatches `mr-reviewer` for the whole diff or per chunk; `mr-reviewer` may fan out to consultant voices for additional quality findings.
