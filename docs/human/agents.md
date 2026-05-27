# Agents

> Last updated: 2026-05-28T12:00:00Z
> Covers source: agents/auditor.md, agents/bisect-isolator.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/plan-style-reviewer.md, agents/planning-router.md, agents/research-judge.md, agents/remote-runner.md, agents/review-agent.md, agents/reviewer.md, agents/scope-probe.md, agents/scope-reconciler-audit.md, agents/scope-reconciler-brainstorm.md, agents/spec-precheck.md

## Overview

The agents concept covers the specialized subagent prompt files under `agents/`. Each file declares an isolated worker role through frontmatter (`name`, `description`, `tools`, `model`) and then defines the inputs, execution procedure, telemetry, and parseable return contract that the surrounding z-harness commands rely on. Agents are always spawned fresh per invocation; the orchestrating command owns all context, user interaction, artifact writes, and final routing decisions.

The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), post-implementation correctness review (`reviewer`), code-quality review (`mr-reviewer`), plan artifact style review (`plan-style-reviewer`), spec validation (`spec-precheck`), post-run memory candidate generation (`review-agent`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), regression bisect isolation (`bisect-isolator`), auditing (`auditor`), cross-LLM consultation (`consultant-primary`, `consultant-secondary`), scope classification (`scope-probe`), fanout reconciliation (`scope-reconciler-audit`, `scope-reconciler-brainstorm`), and adversarial-panel final synthesis for `/z-research` (`research-judge`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.

## Key entry points

- `agents/auditor.md:1` — `auditor` — Read-only Sonnet auditor for one dimension (correctness, perf, cleanliness, or design); writes `findings-<dimension>.md` and returns counts.
- `agents/bisect-isolator.md:1` — `bisect-isolator` — Haiku mechanical bisect runner; drives `git bisect run` between a known-good ref and HEAD, returns offending commit SHA and line-level diff. Refuses destructive repro scripts and interpretive work.
- `agents/cluster-planner.md:1` — `cluster-planner` — Focused `/z-plan-split` leaf planner; writes cluster SPEC.md, PLAN.md, TASKS.md, and escalates risky decisions one at a time.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Cheap Haiku task classifier returning `low`, `medium`, or `high` for model routing.
- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; supports 12 named modes: bundled-decisions, plan-review, light-fix, debug-hypotheses, brainstorm, research-review, doc-audit, test-cases, mr-review, plan-style-audit, generate-hypotheses-round1, and generate-hypotheses-round2-adversarial.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Provider-agnostic secondary consultant proxy with the same 12-mode surface as the primary consultant and a distinct provider role.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Read-only Haiku context fetcher over `docs/llm/INDEX.json`, concept JSONs, and optional `MEMORIES-FLAT.md` ripgrep searches.
- `agents/doc-updater.md:1` — `doc-updater` — Refreshes one concept's human and LLM docs; dry-run by default; must preserve existing `memories[]` verbatim. Supports `dedup_tags: true` for tag collision detection.
- `agents/external-lookup.md:1` — `external-lookup` — Fresh-context Haiku web/API retrieval worker that returns the fixed lookup-contract envelope and refuses mutating commands via verb-blocklist.
- `agents/implementer.md:1` — `implementer` — Implements exactly one task block; accepts `--tasks <path>` for promoted review artifacts (REVIEW-TASKS.md / MR-REVIEW.md); mandatory self-check before returning STATUS: ok; supports `cross_task_notes` for downstream task signaling and `tests_md_path` for TESTS.md coverage.
- `agents/mr-reviewer.md:1` — `mr-reviewer` — Sonnet branch-diff code-quality reviewer that runs inline Claude review plus optional multi-voice dispatch; supports `deep: true` for Opus upgrade on `abstraction-only` passes; merges findings with dedup, consensus tier-bump, and dismissal-pattern matching into a fenced JSON payload.
- `agents/plan-style-reviewer.md:1` — `plan-style-reviewer` — Sonnet plan artifact style reviewer; audits SPEC.md, PLAN.md, TASKS.md for design-quality issues (defensive bloat, premature abstraction, DRY/KISS/SOLID violations, over-engineering, style-drift, test-noise) before any code is written; multi-voice capable; returns fenced JSON + Summary block.
- `agents/planning-router.md:1` — `planning-router` — Cheap Haiku read-only advisory router for ambiguous planning-family route decisions; returns an exact parseable route contract.
- `agents/research-judge.md:1` — `research-judge` — Opus final-judge synthesizer for `/z-research`; reads N adversarial-panel perspective outputs plus MAP.md and BRAINSTORM.md; produces a 10-section RESEARCH.md (approach decision matrix, cross-artifact contradictions, design axes, terrain summary, brainstorm frame space, high-leverage options, rejected framings, evidence gaps, adversarial perspectives summary, and mechanical rank-ordering for /z-plan handoff). Forbidden from new design recommendations; every claim must trace back to source artifacts. Read-only — returns content as text; orchestrator writes the file.
- `agents/remote-runner.md:1` — `remote-runner` — Haiku mechanical remote verifier for sandboxed builds/tests, paper service checks, logs, disk, and read-only DB queries.
- `agents/reviewer.md:1` — `reviewer` — Provider-agnostic correctness/spec reviewer proxy for completed implementation tasks; accepts `relevant_docs` LLM JSONs to catch contract drift.
- `agents/review-agent.md:1` — `review-agent` — Haiku post-run memory candidate generator; reads run events, cumulative diff, and SPEC.md (or DEBUG.md for debug runs); proposes 0-3 memory candidates as a fenced JSON block without writing anything. Enforces slug naming anti-patterns.
- `agents/scope-probe.md:1` — `scope-probe` — Cheap read-only Haiku Phase-0 scope classifier for `/z-audit` and `/z-brainstorm`; walks codebase structure to count natural seams, picks an axis from the caller-supplied taxonomy, and returns a parseable LIGHT/MEDIUM/HEAVY classification with a chunks manifest. Advisory only — the orchestrator owns the final dispatch decision.
- `agents/scope-reconciler-audit.md:1` — `scope-reconciler-audit` — Sonnet post-fanout reconciler for HEAVY `/z-audit` runs; reads N per-chunk `findings-*.md` files, deduplicates by normalized-evidence-line, preserves cross-chunk dissent verbatim, elevates systemic findings by one severity tier, and returns REPORT.md content for the orchestrator to write. Never writes to disk.
- `agents/scope-reconciler-brainstorm.md:1` — `scope-reconciler-brainstorm` — Sonnet post-fanout reconciler for HEAVY `/z-brainstorm` runs; concatenates N per-chunk `BRAINSTORM.md` files verbatim, runs a four-part cross-chunk anti-bias check (unique-framing propagation, contradiction detection, Claude-favoring bias audit, axis-coverage audit), and returns unified content with `chosen_framing: pending` for user selection.
- `agents/spec-precheck.md:1` — `spec-precheck` — Read-only Haiku preflight checker that validates SPEC claims about existing files, symbols, config keys, and schemas before the implementer runs; uses `relevant_docs` LLM JSONs as a second source of truth.

## How it interacts with others

- `commands` — Commands are the orchestrators that decide when to spawn each agent, pass compact inputs, parse exact return shapes, and write user-facing artifacts. `/z-debug` dispatches `bisect-isolator` in Phase 2.5 when a regression has a known-good baseline and a scriptable repro, and dispatches `review-agent` with `parent_command: debug` and a `debug_md_path` in Phase 10 when a DEBUG.md exists. `/z-audit-plan-style` dispatches `plan-style-reviewer` to review plan artifacts before implementation.
- `skills` — Skills mirror command behavior across agent CLIs and encode the operational gates that rely on these subagent contracts. `/z-implement-all` Phase 9, `/z-review-all` Phase 7, and `/z-debug` Phase 10 all dispatch `review-agent` as a post-run pass.
- `scripts` — Agents call shared scripts for telemetry, provider resolution, timeout detection, plan path handling, remote sandbox sync, and memory review (`scripts/run-memory-review.sh`).
- `lookup-contract` — `external-lookup` must follow the canonical envelope in `docs/llm/lookup-contract.json`; the JSON contract wins over inline prose if they diverge.

## Edge cases / gotchas

- `consultant-primary`, `consultant-secondary`, and `reviewer` are Haiku proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
- The proxy agents source `scripts/check-timeout.sh` so `$TIMEOUT_CMD` is available when GNU timeout or gtimeout exists, and they emit `consult_start` events before provider calls so liveness checks can see hangs.
- `planning-router` is advisory only. It reads compact caller-supplied signals, performs no shell work, writes nothing, and returns `ask_user` for route-loop or conflicting-signal risk.
- `doc-updater` is the structural refresh path, not the memory authoring path. It must copy `memories[]` exactly; `/z-suggest-memory` is the only intended authoring and editing path for memories.
- `external-lookup` checks every Bash command against a mutation verb-blocklist before execution and returns `STATUS: refused` instead of trying to sanitize a risky command.
- `remote-runner` is mechanical. It can run sandboxed builds and read-only shared-state checks, but interpretive debugging or DB analysis belongs to the main reasoning thread. It also refuses naked binary launches as restart substitutes — `qtctl up <manifest>` is the only correct restart path for qtctl-supervised processes.

## Subagents quick-reference

These agents are invoked by commands; users do not call them directly.

| Agent | Model | Role |
|---|---|---|
| `implementer` | sonnet | Implements one task in fresh context |
| `mr-reviewer` | sonnet | Fans out to consultant-primary/secondary, deduplicates findings, applies P0-P4 rubric |
| `auditor` | sonnet | Audits one dimension, returns structured findings |
| `cluster-planner` | sonnet | Runs a narrow sub-`/z-plan` for one cluster of a `/z-plan-split` tree |
| `consultant-primary` | (CLI via providers.json) | Cross-LLM consult — primary role |
| `consultant-secondary` | (CLI via providers.json) | Cross-LLM consult — secondary role (must differ from primary) |
| `reviewer` | (CLI via providers.json) | Post-diff safety gate |
| `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
| `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
| `research-judge` | opus | Final synthesizer for /z-research adversarial panel; produces 10-section RESEARCH.md; read-only |
| `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries |
| `external-lookup` | haiku | Fetch external information and return a tight STATUS-headed Markdown synthesis. Read-only. |

Which CLI each agent role calls is determined by `providers.json`. See [PROVIDERS.md](PROVIDERS.md).
- `bisect-isolator` applies a POSIX-ERE verb-grep to the caller-supplied repro command before touching the repo. macOS/BSD grep does not support Perl lookaheads, so refusal checks use split patterns + explicit shell conditionals. It also installs a `cleanup_bisect` trap to guarantee `git bisect reset` on all exit paths, including refusals that occur after `git bisect start`.
- `bisect-isolator` runs a mandatory sanity gate (step 4) that verifies the repro inverts across the range before starting bisect proper. If the repro passes on the bad ref or fails on the good ref, it returns `STATUS: bisect_unusable` rather than running a bisect whose answer would be garbage.
- `mr-reviewer` reviews quality, not correctness, and does not write MR-REVIEW.md itself; the orchestrator parses the returned JSON and writes the artifact. Multi-voice findings go through dedup, consensus tier-bump, and Jaccard-based dismissal-pattern matching before return. When `mode=abstraction-only` AND `deep=true`, an Opus sub-agent is dispatched for deep structural reasoning on abstraction candidate pairs.
- `plan-style-reviewer` reviews design-quality of plan artifacts, not correctness. It never finds correctness bugs, logic errors, or reference-reality issues (those belong to `/z-audit-plan`). Every style-drift finding must cite a STYLE.md rule ID; every premature-abstraction finding must cite an existing duplicate by `file:line`. It never writes `PLAN_STYLE_AUDIT.md`; the orchestrator does.
- `plan-style-reviewer` uses the same multi-voice dispatch, dedup, consensus tier-bump, and Jaccard dismissal-pattern matching pipeline as `mr-reviewer`. `dismissed_signatures.json` suppresses previously dismissed findings across runs.
- `cluster-planner` refuses nested plan-split output by checking ancestor directories for `MANIFEST.md` before substantive repo reads or writes.
- `spec-precheck` uses `relevant_docs` LLM JSONs as a second source of truth alongside SPEC.md — if SPEC says a function exists but the LLM doc lists different entry points, that is a drift signal.
- `reviewer` accepts `relevant_docs` LLM JSONs and reads them before composing the review prompt, to catch contract drift not visible from the diff alone.
- `implementer` accepts `--tasks <path>` so review artifacts (REVIEW-TASKS.md / MR-REVIEW.md) can be used as the task source without altering the main TASKS.md. The `cross_task_notes` return field lets a task signal downstream tasks before orchestrator context is cleared. The `tests_md_path` input enables TESTS.md-driven test code generation per each TEST-NNN entry.
- `review-agent` accepts `parent_command: debug` with an optional `debug_md_path` field; when set, DEBUG.md is the primary artifact for reasoning and `spec_path` is supplementary. For `implement-all` and `review-all` runs, `spec_path` remains primary and `debug_md_path` is unset.
- `review-agent` enforces slug naming anti-patterns: PR-number references, library-name-alone slugs, session-specific artifact names, negative-capability claims, and model-specific slugs are all banned.
- `review-agent` proposes memory candidates only — it never writes anything. The orchestrator handles all writes via `/z-suggest-memory`. Output is exactly one fenced JSON block; any other form is treated as malformed by the orchestrator.
- `doc-fetcher` falls back to a Python word-boundary scan when `rg` is not on PATH; the Ripgrep dependency is soft — never fail on its absence.
- Consultant modes `generate-hypotheses-round1` and `generate-hypotheses-round2-adversarial` return RAW output (no standard wrapper); callers must parse the provider's output directly.
- `scope-probe` makes at most one `doc-fetcher` call in Step 4; it never chains doc-fetcher calls. Walking more than 4 candidates is also a violation — it keeps Haiku context cheap.
- `scope-probe` returns `STATUS: refused` + `MODE: MEDIUM` when axis evidence is insufficient; this is not an error state, it is the designed graceful-degradation path. The host command proceeds as MEDIUM in all refusal/error cases.
- `scope-probe` output contract requires all line-prefix headers (STATUS, MODE, AXIS, CONFIDENCE, REASON_CODES, REASON) to appear before the fenced JSON block. Headers inside the fence are a parser error; on parser failure, hosts emit a `scope_probe_malformed` event and proceed as MEDIUM without retry.
- `scope-probe` SCOPE.json uses archive-first write order: the archive copy at `z-harness/<slug>/archive/<RUN>/SCOPE.json` must succeed before the live file at `z-harness/<slug>/SCOPE-<host>.json` is overwritten. If the archive write fails, Phase 0 aborts and the host proceeds as if scope-probe was never dispatched.
- `scope-reconciler-audit` severity elevation applies only to systemic non-dissent findings (same normalized evidence key appearing in ≥2 distinct chunks). Dissent findings are never elevated — the disagreement itself is the signal.
- `scope-reconciler-audit` normalization (lowercase, collapse whitespace, strip `<path>:<int>:` prefix, truncate to 200 chars) is used only internally for dedup detection; the original quoted evidence always appears in REPORT.md verbatim.
- `scope-reconciler-brainstorm` anti-bias check has four mandatory sub-sections (A through D); omitting any sub-section — even when findings are empty — makes the unified output less trustworthy than a single chunk's output.
- `scope-reconciler-brainstorm` Claude-favoring bias check requires a concrete justification naming what Claude said that peer ideators did not. A generic preference ("Claude's framing is cleaner") is not accepted as justification.
- `research-judge` is forbidden from proposing new design recommendations. Every claim must trace back to MAP.md, BRAINSTORM.md, or a panel perspective file — uncited claims are marked `UNVERIFIED`. The self-check (Step 7) runs on every invocation and strips any prescriptive language before return.
- `research-judge` fires `panel_degraded` mode when fewer than 3 perspectives are available; synthesis continues with available perspectives and prepends a warning to section 9. If the perspectives array is empty, or if MAP.md or BRAINSTORM.md is missing, it returns `STATUS: unable_to_complete`.
- `research-judge` produces exactly 10 sections in fixed order; no additional top-level sections are permitted. Every non-UNVERIFIED matrix cell must have a `<file>:<section> — <snippet>` citation; a cell with a verdict but no citation is treated as UNVERIFIED.

## Examples

- `/z-plan` and related plan-family commands dispatch `planning-router` only when deterministic route signals conflict or confidence is too low for an automatic route.
- `/z-plan-split` dispatches `cluster-planner` once per cluster; each cluster planner may call `doc-fetcher` and `complexity-classifier` but not external consultants.
- `/z-implement-all` dispatches `spec-precheck`, then `implementer`, optional `remote-runner`, and finally `reviewer` for each task batch. `spec-precheck` and `reviewer` both consume `relevant_docs` LLM JSONs.
- `/z-audit-plan-style` dispatches `plan-style-reviewer` for the plan artifacts; `plan-style-reviewer` may fan out to consultant voices for additional quality findings; the orchestrator builds `PLAN_STYLE_AUDIT.md` from the returned JSON.
- `/z-maintain-docs` dispatches `doc-updater` for stale concepts and can then audit the proposed update with both consultant proxies in `doc-audit` mode.
- `/z-mr-review` dispatches `mr-reviewer` for the whole diff or per chunk; `mr-reviewer` may fan out to consultant voices for additional quality findings, and can dispatch an Opus sub-agent for deep abstraction analysis when `deep: true`.
- `/z-implement-all` Phase 9, `/z-review-all` Phase 7, and `/z-debug` Phase 10 dispatch `review-agent` as a post-run pass to propose memory candidates from run events and the cumulative diff; `/z-suggest-memory` is then used to commit any accepted candidates.
- `/z-debug` Phase 2.5 dispatches `bisect-isolator` when the bug is a regression with a known-good baseline and the repro is scriptable; the orchestrator interprets the returned SHA + diff, not the bisect-isolator itself. When a DEBUG.md exists, `/z-debug` Phase 10 dispatches `review-agent` with `parent_command: debug` and `debug_md_path` pointing to DEBUG.md.
- `/z-debug` Phase 3a and 3b dispatch `consultant-primary` and `consultant-secondary` in `generate-hypotheses-round1` and `generate-hypotheses-round2-adversarial` modes for multi-LLM hypothesis generation and adversarial critique.
- `/z-audit` and `/z-brainstorm` dispatch `scope-probe` as Phase 0 to classify the topic scope before any sub-run is launched. If `scope-probe` returns `HEAVY`, the host fans out N parallel sub-runs along the chosen axis. If scope-probe returns `STATUS: refused` or the parser fails, the host falls back to standard single-run behavior.
- After a HEAVY `/z-audit` fan-out completes, the host dispatches `scope-reconciler-audit` once with the N per-chunk `findings-*.md` paths. The reconciler returns REPORT.md content and a CHUNK_ARTIFACTS list; the orchestrator writes all files.
- After a HEAVY `/z-brainstorm` fan-out completes, the host dispatches `scope-reconciler-brainstorm` once with the N per-chunk `BRAINSTORM.md` paths. The reconciler returns unified content with `chosen_framing: pending`; the host writes it and presents Phase 3 AskUserQuestion for framing selection.
- `/z-research` dispatches `research-judge` once after all adversarial-panel perspective agents have completed. The judge reads all perspective output files, MAP.md, and BRAINSTORM.md, then returns the full RESEARCH.md content as a string. The orchestrator writes the file; `research-judge` never writes to disk.
