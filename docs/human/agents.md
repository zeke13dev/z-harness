# Agents

> Last updated: 2026-06-03
> Covers source: agents/auditor.md, agents/axiom-extractor.md, agents/bisect-isolator.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/plan-style-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/research-judge.md, agents/resolver.md, agents/review-agent.md, agents/reviewer.md, agents/scope-extractor.md, agents/scope-probe.md, agents/scope-reconciler-audit.md, agents/scope-reconciler-brainstorm.md, agents/self-reviewer.md, agents/spec-precheck.md

## Overview

The agents concept covers the specialized subagent prompt files under `agents/`. Each file declares an isolated worker role through frontmatter (`name`, `description`, `tools`, `model`) and then defines the inputs, execution procedure, telemetry, and parseable return contract that the surrounding z-harness commands rely on. Agents are always spawned fresh per invocation; the orchestrating command owns all context, user interaction, artifact writes, and final routing decisions.

The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), scope classification (`scope-probe`), file-scope extraction for the plan registry (`scope-extractor`), implementation (`implementer`), post-implementation correctness review (`reviewer`), self-review when `Z_HARNESS_CONSULT=off` (`self-reviewer`), code-quality review (`mr-reviewer`), plan artifact style review (`plan-style-reviewer`), spec validation (`spec-precheck`), post-run memory candidate generation (`review-agent`), behavioral axiom mining (`axiom-extractor`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), regression bisect isolation (`bisect-isolator`), auditing (`auditor`), cross-LLM consultation (`consultant-primary`, `consultant-secondary`), fanout reconciliation (`scope-reconciler-audit`, `scope-reconciler-brainstorm`), adversarial-panel final synthesis for `/z-research` (`research-judge`), and workflow question resolution (`resolver`). The three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) resolve provider CLIs at runtime through `scripts/resolve-provider.sh` and each declares an `expected_contract` that `resolve-persona.py validate` enforces when a persona is bound to the role.

## Key entry points

- `agents/auditor.md:1` — `auditor` — Read-only Sonnet auditor for one dimension (correctness, perf, cleanliness, or design); writes `findings-<dimension>.md` and returns counts.
- `agents/axiom-extractor.md:1` — `axiom-extractor` — Sonnet retrospective policy-mining agent; wraps `scripts/axiom-extract.py` with LLM judgement to produce ≤5 sharpened axiom candidates from interaction history. Proposes only; never writes the axiom store.
- `agents/bisect-isolator.md:1` — `bisect-isolator` — Haiku mechanical bisect runner; drives `git bisect run` between a known-good ref and HEAD, returns offending commit SHA and line-level diff. Refuses destructive repro scripts and interpretive work.
- `agents/cluster-planner.md:1` — `cluster-planner` — Focused `/z-plan-split` leaf planner; writes cluster SPEC.md, PLAN.md, TASKS.md, and escalates risky decisions one at a time.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Cheap Haiku task classifier returning `low`, `medium`, or `high` for model routing.
- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; `expected_contract: freeform`; supports 12 named modes: bundled-decisions, plan-review, light-fix, debug-hypotheses, brainstorm, research-review, doc-audit, test-cases, mr-review, plan-style-audit, generate-hypotheses-round1, and generate-hypotheses-round2-adversarial.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Provider-agnostic secondary consultant proxy with the same 12-mode surface as the primary consultant and a distinct provider role; `expected_contract: freeform`.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Read-only Haiku context fetcher over `docs/llm/INDEX.json`, concept JSONs, and optional `MEMORIES-FLAT.md` ripgrep searches.
- `agents/doc-updater.md:1` — `doc-updater` — Refreshes one concept's human and LLM docs; dry-run by default; must preserve existing `memories[]` verbatim. Supports `dedup_tags: true` for tag collision detection.
- `agents/external-lookup.md:1` — `external-lookup` — Fresh-context Haiku web/API retrieval worker that returns the fixed lookup-contract envelope and refuses mutating commands via verb-blocklist.
- `agents/implementer.md:1` — `implementer` — Implements exactly one task block; accepts `--tasks <path>` for promoted review artifacts (REVIEW-TASKS.md / MR-REVIEW.md); mandatory self-check before returning STATUS: ok; supports `cross_task_notes` for downstream task signaling and `tests_md_path` for TESTS.md coverage.
- `agents/mr-reviewer.md:1` — `mr-reviewer` — Sonnet branch-diff code-quality reviewer that runs inline Claude review plus optional multi-voice dispatch; supports `deep: true` for Opus upgrade on `abstraction-only` passes; merges findings with dedup, consensus tier-bump, and dismissal-pattern matching into a fenced JSON payload.
- `agents/plan-style-reviewer.md:1` — `plan-style-reviewer` — Sonnet plan artifact style reviewer; audits SPEC.md, PLAN.md, TASKS.md for design-quality issues (defensive bloat, premature abstraction, DRY/KISS/SOLID violations, over-engineering, style-drift, test-noise) before any code is written; multi-voice capable; returns fenced JSON + Summary block.
- `agents/planning-router.md:1` — `planning-router` — Cheap Haiku read-only advisory router for ambiguous planning-family route decisions; returns an exact parseable route contract. Primary routes include `/z-map` (for terrain-uncertain topics) and `/z-research` (for approach synthesis when MAP.md + BRAINSTORM.md exist). The `needs_research` reason code is a deprecated alias for `needs_terrain_map` → `/z-map`.
- `agents/research-judge.md:1` — `research-judge` — Opus final-judge synthesizer for `/z-research`; reads N adversarial-panel perspective outputs plus MAP.md and BRAINSTORM.md; produces a 10-section RESEARCH.md. Forbidden from new design recommendations; every claim must trace back to source artifacts. Read-only.
- `agents/remote-runner.md:1` — `remote-runner` — Haiku mechanical remote verifier: sandboxed builds/tests using a two-level rsync layout, paper service checks, log/disk queries, and read-only DB queries. Invokes `scripts/remote-sandbox-sync.sh` for SLUG/TASK_ID validation and atomic base seeding.
- `agents/resolver.md:1` — `resolver` — Reference doc for the workflow question resolver; maps registered `question_id` values to a result domain (`skip | prefill | ask | halt | defer-to-sink`) by consulting config layers, memory, and overnight-gate overrides. Implemented in `scripts/config.py` (`cmd_resolve_question`).
- `agents/review-agent.md:1` — `review-agent` — Haiku post-run memory candidate generator; reads run events, cumulative diff, and SPEC.md (or DEBUG.md for debug runs); proposes 0-3 memory candidates as a fenced JSON block without writing anything. Enforces slug naming anti-patterns.
- `agents/reviewer.md:1` — `reviewer` — Provider-agnostic correctness/spec reviewer proxy for completed implementation tasks; `expected_contract: review-verdict`; accepts `relevant_docs` LLM JSONs to catch contract drift. Emits a `**FOLLOWUPS:**` fenced JSON array block after `### Major` — minors and nits MUST appear here. Orchestrator parses via `scripts/parse-followups-block.py` and calls `scripts/sink-add.sh` per entry.
- `agents/scope-extractor.md:1` — `scope-extractor` — Haiku plan-scope extractor; reads SPEC.md, PLAN.md, TASKS.md and emits a JSON array of likely file changes with confidence labels (`explicit`, `inferred`, `broad`, `unknown`). Used by `z-implement-all` and `z-plan` to seed the active-plan registry so overlap detection works across concurrent sessions.
- `agents/scope-probe.md:1` — `scope-probe` — Cheap read-only Haiku Phase-0 scope classifier for `/z-audit` and `/z-brainstorm`; walks codebase structure to count natural seams, picks an axis from the caller-supplied taxonomy, and returns a parseable LIGHT/MEDIUM/HEAVY classification with a chunks manifest. Advisory only.
- `agents/scope-reconciler-audit.md:1` — `scope-reconciler-audit` — Sonnet post-fanout reconciler for HEAVY `/z-audit` runs; deduplicates by normalized-evidence-line, preserves cross-chunk dissent verbatim, elevates systemic findings by one severity tier, and returns REPORT.md content for the orchestrator to write. Never writes to disk.
- `agents/scope-reconciler-brainstorm.md:1` — `scope-reconciler-brainstorm` — Sonnet post-fanout reconciler for HEAVY `/z-brainstorm` runs; concatenates N per-chunk `BRAINSTORM.md` files verbatim, runs a four-part cross-chunk anti-bias check, and returns unified content with `chosen_framing: pending` for user selection.
- `agents/self-reviewer.md:1` — `self-reviewer` — Read-only Opus self-review agent invoked when `Z_HARNESS_CONSULT=off`; reviews a diff vs SPEC.md and returns the same response shape as the standard `reviewer` (blockers/majors/minors) without calling any external model CLI. `expected_contract: review-verdict`.
- `agents/spec-precheck.md:1` — `spec-precheck` — Read-only Haiku preflight checker that validates SPEC claims about existing files, symbols, config keys, and schemas before the implementer runs; uses `relevant_docs` LLM JSONs as a second source of truth.

## How it interacts with others

- `commands` — Commands are the orchestrators that decide when to spawn each agent, pass compact inputs, parse exact return shapes, and write user-facing artifacts. `/z-implement-all` dispatches `scope-extractor` at Phase 0 to seed the active-plan registry, then dispatches `self-reviewer` instead of `reviewer` when `Z_HARNESS_CONSULT=off`, and dispatches `axiom-extractor` in Phase 9 alongside `review-agent` when `AXIOM_READY` is signaled. `/z-debug` dispatches `bisect-isolator` in Phase 2.5 and `review-agent` with `parent_command: debug` in Phase 10. `/z-audit-plan-style` dispatches `plan-style-reviewer` before any code is written. `/z-plan` dispatches `scope-extractor` after TASKS.md is finalized.
- `skills` — Skills mirror command behavior across agent CLIs and encode the operational gates that rely on these subagent contracts. `/z-implement-all` Phase 9, `/z-review-all` Phase 7, and `/z-debug` Phase 10 all dispatch `review-agent` as a post-run pass.
- `scripts` — Agents call shared scripts for telemetry, provider resolution, timeout detection, plan path handling, remote sandbox sync, and memory review. `remote-runner` delegates all sandbox lifecycle to `scripts/remote-sandbox-sync.sh`. The three proxy agents call `scripts/resolve-persona.py` indirectly via `scripts/resolve-provider.sh` to enforce `expected_contract` validation. `scripts/parse-followups-block.py` is the canonical parser for `reviewer`'s and `self-reviewer`'s `**FOLLOWUPS:**` blocks. The resolver is implemented in `scripts/config.py` (`cmd_resolve_question`). `scope-extractor`'s output is consumed by `scripts/active-plan-registry.py update-scope`.
- `lookup-contract` — `external-lookup` must follow the canonical envelope in `docs/llm/lookup-contract.json`; the JSON contract wins over inline prose if they diverge.
- `personas-and-roles` — Each proxy agent (`consultant-primary`, `consultant-secondary`, `reviewer`, `self-reviewer`) declares an `expected_contract` field. `resolve-persona.py validate` hard-fails with an actionable message if a persona bound to a role declares a mismatched contract. `consultant-primary` and `consultant-secondary` require `contract: freeform`; `reviewer` and `self-reviewer` require `contract: review-verdict`.
- `active-plan-registry` — `scope-extractor` seeds file-scope data into the registry via `scripts/active-plan-registry.py update-scope`; overlap detection in `z-implement-all` and `z-plan` depends on this seeding being present before the plan starts.
- `axioms` — `axiom-extractor` wraps `scripts/axiom-extract.py` and is dispatched post-run by `/z-implement-all`; its output feeds the `/z-axiom-scan` / `/z-axiom-approve` workflow.

## Edge cases / gotchas

- `reviewer` and `self-reviewer` both emit a `**FOLLOWUPS:**` block (fenced JSON array) after `### Major`. Minors and nits MUST appear here — never silently dropped. The orchestrator parses via `scripts/parse-followups-block.py` and calls `scripts/sink-add.sh` per entry. Parse failure logs `followup_block_parse_failed` and never crashes the return path. Required per-entry fields: `priority`, `name`, `recommended_command`, `cited_paths`. Optional: `recommended_command_safe_to_retry` (default `false`), `auto_close_eligible` (default `false`; reviewer is on the producer-class allowlist and may set `true`).
- `self-reviewer` is the fallback when `Z_HARNESS_CONSULT=off`. It is an Opus-model agent (not a proxy), so it calls no external CLI and has no `resolve-provider.sh` step. It still emits `review_start` / `review_end` telemetry in the same shape as `reviewer`.
- `scope-extractor` is best-effort and non-fatal: if the seeding call fails, `active-plan-registry.py` self-logs a `registry_error` and the implement-all run continues. The overlap detection in the same run may then miss some files from this plan, but other sessions' overlap checks will still work correctly.
- `axiom-extractor` proposes only — the fenced JSON array it returns is NOT written to the axiom store automatically. No axiom is approved without a subsequent human `/z-axiom-approve` action.
- `resolver` result domain: `skip | prefill | ask | halt | defer-to-sink`. The `defer-to-sink` result means the orchestrator must NOT prompt the user — it calls `scripts/sink-add.sh` with the question context as the entry body, logs `followup_deferred_from_resolver`, and proceeds. If `sink-add.sh` exits non-zero, the orchestrator falls back to `ask` — the question cannot be silently dropped.
- `consultant-primary`, `consultant-secondary`, and `reviewer` are proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
- The proxy agents source `scripts/check-timeout.sh` so `$TIMEOUT_CMD` is available when GNU timeout or gtimeout exists, and they emit `consult_start` events before provider calls so liveness checks can see hangs.
- `planning-router` is advisory only; it returns `ask_user` for route-loop or conflicting-signal risk. The `needs_research` reason code is a deprecated alias for the current cycle only — callers should emit `needs_terrain_map` instead.
- `doc-updater` is the structural refresh path, not the memory authoring path. It must copy `memories[]` exactly; `/z-suggest-memory` is the only intended authoring and editing path for memories.
- `remote-runner` delegates sandbox creation to `scripts/remote-sandbox-sync.sh`, which enforces: (1) SLUG and TASK_ID are validated against path-traversal patterns and TASK_ID cannot equal the literal string `base`; (2) the shared `<slug>/base/` is seeded once via an atomic `mkdir`-lock — the winner rsync-seeds and writes a `.base-ready` marker, concurrent losers poll for that marker up to 600 s; (3) per-task overlays use `--link-dest=$BASE` for hard-linked unchanged files.
- `remote-runner` step 7 NEVER deletes `<slug>/base/` — even on success. The warm base is long-lived and shared across all tasks in a slug. Only the per-task `<slug>/<task-id>/` directory is removed on success.
- If a `remote-sandbox-sync.sh` invocation died between acquiring `.base.lock` and releasing it, the lock persists and all future seeding attempts timeout after 600 s. Recovery: `ssh <remote-host> 'rmdir ~/dev/qt-bot-sandbox/<slug>/.base.lock'`.
- `bisect-isolator` applies a POSIX-ERE verb-grep to the caller-supplied repro command before touching the repo. macOS/BSD grep does not support Perl lookaheads, so refusal checks use split patterns + explicit shell conditionals. It also installs a `cleanup_bisect` trap to guarantee `git bisect reset` on all exit paths.
- `bisect-isolator` runs a mandatory sanity gate (step 4) that verifies the repro inverts across the range before starting bisect proper. If the repro passes on the bad ref or fails on the good ref, it returns `STATUS: bisect_unusable`.
- `plan-style-reviewer` reviews design-quality of plan artifacts, not correctness. Every style-drift finding must cite a STYLE.md rule ID; every premature-abstraction finding must cite an existing duplicate by `file:line`. It never writes `PLAN_STYLE_AUDIT.md`; the orchestrator does.
- `scope-probe` returns `STATUS: refused` + `MODE: MEDIUM` when axis evidence is insufficient; this is not an error state, it is the designed graceful-degradation path. All line-prefix headers must appear before the fenced JSON block — headers inside the fence cause `scope_probe_malformed` events and the host falls back to MEDIUM.
- `scope-reconciler-audit` severity elevation applies only to systemic non-dissent findings (same normalized-evidence-line in ≥2 distinct chunks). Dissent findings are never elevated.
- `research-judge` is forbidden from proposing new design recommendations; every claim must trace back to MAP.md, BRAINSTORM.md, or a panel perspective file. The self-check (Step 7) runs on every invocation.

## Subagents quick-reference

These agents are invoked by commands; users do not call them directly.

| Agent | Model | Role |
|---|---|---|
| `implementer` | sonnet | Implements one task in fresh context |
| `mr-reviewer` | sonnet | Fans out to consultant-primary/secondary, deduplicates findings, applies P0-P4 rubric |
| `auditor` | sonnet | Audits one dimension, returns structured findings |
| `cluster-planner` | sonnet | Runs a narrow sub-`/z-plan` for one cluster of a `/z-plan-split` tree |
| `plan-style-reviewer` | sonnet | Reviews plan artifacts for design-quality issues before any code is written |
| `axiom-extractor` | sonnet | Mines interaction history for behavioral axiom candidates; proposes-only |
| `consultant-primary` | (CLI via providers.json) | Cross-LLM consult — primary role; `expected_contract: freeform` |
| `consultant-secondary` | (CLI via providers.json) | Cross-LLM consult — secondary role (must differ from primary); `expected_contract: freeform` |
| `reviewer` | (CLI via providers.json) | Post-diff safety gate; `expected_contract: review-verdict` |
| `self-reviewer` | opus | Self-review when `Z_HARNESS_CONSULT=off`; `expected_contract: review-verdict`; no external CLI |
| `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
| `scope-extractor` | haiku | Emits file-scope JSON for the active-plan registry (seeded at plan/implement start) |
| `scope-probe` | haiku | Phase-0 scope classifier: LIGHT/MEDIUM/HEAVY + axis + chunks manifest |
| `complexity-classifier` | haiku | Stamps each task with a `low/medium/high` tier for model routing |
| `planning-router` | haiku | Advisory route resolver for ambiguous planning-family decisions |
| `review-agent` | haiku | Post-run memory candidate generator; 0-3 candidates per run |
| `bisect-isolator` | haiku | Mechanical git-bisect runner; returns offending SHA + diff; no interpretation |
| `remote-runner` | haiku | Mechanical remote work — two-level rsync sandbox + cargo build, read-only DB/log queries |
| `external-lookup` | haiku | Fetch external information; read-only; returns lookup-contract envelope |
| `doc-fetcher` | haiku | Fast read-only doc fetcher over docs/llm/ |
| `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
| `research-judge` | opus | Final synthesizer for /z-research adversarial panel; 10-section RESEARCH.md; read-only |
| `scope-reconciler-audit` | sonnet | Post-fanout reconciler for HEAVY /z-audit runs |
| `scope-reconciler-brainstorm` | sonnet | Post-fanout reconciler for HEAVY /z-brainstorm runs |
| `resolver` | (scripts/config.py) | Read-only workflow question resolver; maps question_id → skip/prefill/ask/halt/defer-to-sink |

## Examples

- `/z-plan` dispatches `planning-router` only when deterministic route signals conflict or confidence is too low for an automatic route. After TASKS.md is finalized, it dispatches `scope-extractor` to seed the active-plan registry.
- `/z-plan-split` dispatches `cluster-planner` once per cluster; each cluster planner may call `doc-fetcher` and `complexity-classifier` but not external consultants.
- `/z-implement-all` dispatches `scope-extractor` at Phase 0 to seed scope, then per-task dispatches `spec-precheck`, `implementer`, optional `remote-runner`, and `reviewer` (or `self-reviewer` when `Z_HARNESS_CONSULT=off`). `spec-precheck` and `reviewer` both consume `relevant_docs` LLM JSONs.
- `/z-implement-all` Phase 9 dispatches `review-agent` as a post-run pass. When `run-memory-review.sh` signals `AXIOM_READY`, it also dispatches `axiom-extractor` in parallel. Both are proposals-only — `/z-suggest-memory` and `/z-axiom-approve` handle any downstream writes.
- `/z-audit-plan-style` dispatches `plan-style-reviewer` for the plan artifacts before any code is written; `plan-style-reviewer` may fan out to consultant voices; the orchestrator builds `PLAN_STYLE_AUDIT.md` from the returned JSON.
- `/z-maintain-docs` dispatches `doc-updater` for stale concepts and can then audit the proposed update with both consultant proxies in `doc-audit` mode.
- `/z-mr-review` dispatches `mr-reviewer` for the whole diff or per chunk; `mr-reviewer` may fan out to consultant voices and can dispatch an Opus sub-agent for deep abstraction analysis when `deep: true`.
- `/z-debug` Phase 2.5 dispatches `bisect-isolator` when the bug is a regression with a known-good baseline and the repro is scriptable. Phase 10 dispatches `review-agent` with `parent_command: debug` and `debug_md_path` pointing to DEBUG.md.
- `/z-audit` and `/z-brainstorm` dispatch `scope-probe` as Phase 0. On HEAVY classification, the host fans out N parallel sub-runs; after they complete it dispatches `scope-reconciler-audit` or `scope-reconciler-brainstorm` to merge results.
- `/z-research` dispatches `research-judge` once after all adversarial-panel perspective agents complete. The judge returns full RESEARCH.md content; the orchestrator writes the file.
- `/z-personas` (roles subcommand) validates persona-to-role bindings; `resolve-persona.py validate` hard-fails if `consultant-primary` or `consultant-secondary` is bound to a persona with `contract: review-verdict`, or if `reviewer`/`self-reviewer` is bound to a persona with `contract: freeform`.
