# Agents

> Last updated: 2026-05-27
> Covers source: agents/auditor.md, agents/bisect-isolator.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/plan-style-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/review-agent.md, agents/reviewer.md, agents/spec-precheck.md

## Overview

The agents concept covers the specialized subagent prompt files under `agents/`. Each file declares an isolated worker role through frontmatter (`name`, `description`, `tools`, `model`) and then defines the inputs, execution procedure, telemetry, and parseable return contract that the surrounding z-harness commands rely on. Agents are always spawned fresh per invocation; the orchestrating command owns all context, user interaction, artifact writes, and final routing decisions.

The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), post-implementation correctness review (`reviewer`), code-quality review (`mr-reviewer`), plan artifact style review (`plan-style-reviewer`), spec validation (`spec-precheck`), post-run memory candidate generation (`review-agent`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), regression bisect isolation (`bisect-isolator`), auditing (`auditor`), and cross-LLM consultation (`consultant-primary`, `consultant-secondary`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.

## Key entry points

- `agents/auditor.md:1` — `auditor` — Read-only Sonnet auditor for one dimension (correctness, perf, cleanliness, or design); writes `findings-<dimension>.md` and returns counts.
- `agents/bisect-isolator.md:1` — `bisect-isolator` — Haiku mechanical bisect runner; drives `git bisect run` between a known-good ref and HEAD, returns offending commit SHA and line-level diff. Refuses destructive repro scripts and interpretive work.
- `agents/cluster-planner.md:1` — `cluster-planner` — Focused `/z-plan-split` leaf planner; writes cluster SPEC.md, PLAN.md, TASKS.md, and escalates risky decisions one at a time.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Cheap Haiku task classifier returning `low`, `medium`, or `high` for model routing.
- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; supports bundled-decisions, plan-review, light-fix, debug-hypotheses, brainstorm, research-review, doc-audit, test-cases, mr-review, plan-style-audit, and multi-round generate-hypotheses modes.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Provider-agnostic secondary consultant proxy with the same mode surface as the primary consultant and a distinct provider role.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Read-only Haiku context fetcher over `docs/llm/INDEX.json`, concept JSONs, and optional `MEMORIES-FLAT.md` ripgrep searches.
- `agents/doc-updater.md:1` — `doc-updater` — Refreshes one concept's human and LLM docs; dry-run by default; must preserve existing `memories[]` verbatim.
- `agents/external-lookup.md:1` — `external-lookup` — Fresh-context Haiku web/API retrieval worker that returns the fixed lookup-contract envelope and refuses mutating commands via verb-blocklist.
- `agents/implementer.md:1` — `implementer` — Implements exactly one task block, reads relevant plan/docs context, performs a mandatory self-check, and returns structured status.
- `agents/mr-reviewer.md:1` — `mr-reviewer` — Sonnet branch-diff code-quality reviewer that runs inline Claude review plus optional multi-voice dispatch; merges findings with dedup, consensus tier-bump, and dismissal-pattern matching into a fenced JSON payload.
- `agents/plan-style-reviewer.md:1` — `plan-style-reviewer` — Sonnet plan artifact style reviewer; audits SPEC.md, PLAN.md, TASKS.md for design-quality issues (defensive bloat, premature abstraction, DRY/KISS/SOLID violations, over-engineering, style-drift, test-noise) before any code is written; multi-voice capable; returns fenced JSON + Summary block.
- `agents/planning-router.md:1` — `planning-router` — Cheap Haiku read-only advisory router for ambiguous planning-family route decisions; returns an exact parseable route contract.
- `agents/remote-runner.md:1` — `remote-runner` — Haiku mechanical remote verifier for sandboxed builds/tests, paper service checks, logs, disk, and read-only DB queries.
- `agents/reviewer.md:1` — `reviewer` — Provider-agnostic correctness/spec reviewer proxy for completed implementation tasks.
- `agents/review-agent.md:1` — `review-agent` — Haiku post-run memory candidate generator; reads run events, cumulative diff, and SPEC.md (or DEBUG.md for debug runs); proposes 0-3 memory candidates as a fenced JSON block without writing anything.
- `agents/spec-precheck.md:1` — `spec-precheck` — Read-only Haiku preflight checker that validates SPEC claims about existing files, symbols, config keys, and schemas before the implementer runs.

## How it interacts with others

- `commands` — Commands are the orchestrators that decide when to spawn each agent, pass compact inputs, parse exact return shapes, and write user-facing artifacts. `/z-debug` dispatches `bisect-isolator` in Phase 2.5 when a regression has a known-good baseline and a scriptable repro; `/z-audit-plan-style` dispatches `plan-style-reviewer` to review plan artifacts before implementation.
- `skills` — Skills mirror command behavior across agent CLIs and encode the operational gates that rely on these subagent contracts.
- `scripts` — Agents call shared scripts for telemetry, provider resolution, timeout detection, plan path handling, and remote sandbox sync.
- `lookup-contract` — `external-lookup` must follow the canonical envelope in `docs/llm/lookup-contract.json`; the JSON contract wins over inline prose if they diverge.

## Edge cases / gotchas

- `consultant-primary`, `consultant-secondary`, and `reviewer` are Haiku proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
- The proxy agents source `scripts/check-timeout.sh` so `$TIMEOUT_CMD` is available when GNU timeout or gtimeout exists, and they emit `consult_start` events before provider calls so liveness checks can see hangs.
- `planning-router` is advisory only. It reads compact caller-supplied signals, performs no shell work, writes nothing, and returns `ask_user` for route-loop or conflicting-signal risk.
- `doc-updater` is the structural refresh path, not the memory authoring path. It must copy `memories[]` exactly; `/z-suggest-memory` is the only intended authoring and editing path for memories.
- `external-lookup` checks every Bash command against a mutation verb-blocklist before execution and returns `STATUS: refused` instead of trying to sanitize a risky command.
- `remote-runner` is mechanical. It can run sandboxed builds and read-only shared-state checks, but interpretive debugging or DB analysis belongs to the main reasoning thread.
- `bisect-isolator` applies a POSIX-ERE verb-grep to the caller-supplied repro command before touching the repo. macOS/BSD grep does not support Perl lookaheads, so refusal checks use split patterns + explicit shell conditionals. It also installs a `cleanup_bisect` trap to guarantee `git bisect reset` on all exit paths, including refusals that occur after `git bisect start`.
- `bisect-isolator` runs a mandatory sanity gate (step 4) that verifies the repro inverts across the range before starting bisect proper. If the repro passes on the bad ref or fails on the good ref, it returns `STATUS: bisect_unusable` rather than running a bisect whose answer would be garbage.
- `mr-reviewer` reviews quality, not correctness, and does not write MR-REVIEW.md itself; the orchestrator parses the returned JSON and writes the artifact. Multi-voice findings go through dedup, consensus tier-bump, and Jaccard-based dismissal-pattern matching before return.
- `plan-style-reviewer` reviews design-quality of plan artifacts, not correctness. It never finds correctness bugs, logic errors, or reference-reality issues (those belong to `/z-audit-plan`). Every style-drift finding must cite a STYLE.md rule ID; every premature-abstraction finding must cite an existing duplicate by `file:line`. It never writes `PLAN_STYLE_AUDIT.md`; the orchestrator does.
- `plan-style-reviewer` uses the same multi-voice dispatch, dedup, consensus tier-bump, and Jaccard dismissal-pattern matching pipeline as `mr-reviewer`. `dismissed_signatures.json` suppresses previously dismissed findings across runs.
- `cluster-planner` refuses nested plan-split output by checking ancestor directories for `MANIFEST.md` before substantive repo reads or writes.
- `spec-precheck`, `implementer`, and `reviewer` read relevant LLM-tier docs themselves so stale spec references can be caught before or during task execution.
- `review-agent` accepts `parent_command: debug` with an optional `debug_md_path` field; when set, DEBUG.md is the primary artifact for reasoning and `spec_path` is supplementary. For `implement-all` and `review-all` runs, `spec_path` remains primary and `debug_md_path` is unset.
- `review-agent` proposes memory candidates only — it never writes anything. The orchestrator handles all writes via `/z-suggest-memory`. Output is exactly one fenced JSON block; any other form is treated as malformed by the orchestrator.
- `doc-fetcher` falls back to a Python word-boundary scan when `rg` is not on PATH; the Ripgrep dependency is soft — never fail on its absence.

## Examples

- `/z-plan` and related plan-family commands dispatch `planning-router` only when deterministic route signals conflict or confidence is too low for an automatic route.
- `/z-plan-split` dispatches `cluster-planner` once per cluster; each cluster planner may call `doc-fetcher` and `complexity-classifier` but not external consultants.
- `/z-implement-all` dispatches `spec-precheck`, then `implementer`, optional `remote-runner`, and finally `reviewer` for each task batch.
- `/z-audit-plan-style` dispatches `plan-style-reviewer` for the plan artifacts; `plan-style-reviewer` may fan out to consultant voices for additional quality findings; the orchestrator builds `PLAN_STYLE_AUDIT.md` from the returned JSON.
- `/z-maintain-docs` dispatches `doc-updater` for stale concepts and can then audit the proposed update with both consultant proxies in `doc-audit` mode.
- `/z-mr-review` dispatches `mr-reviewer` for the whole diff or per chunk; `mr-reviewer` may fan out to consultant voices for additional quality findings.
- `/z-implement-all` and `/z-review-all` dispatch `review-agent` as a post-run pass to propose memory candidates from run events and the cumulative diff; `/z-suggest-memory` is then used to commit any accepted candidates.
- `/z-debug` Phase 2.5 dispatches `bisect-isolator` when the bug is a regression with a known-good baseline and the repro is scriptable; the orchestrator interprets the returned SHA + diff, not the bisect-isolator itself. When a DEBUG.md exists, `/z-debug` also dispatches `review-agent` with `parent_command: debug` and `debug_md_path` pointing to DEBUG.md.
