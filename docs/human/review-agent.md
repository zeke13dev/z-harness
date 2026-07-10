# review-agent

> Last updated: 2026-07-09
> Covers source: agents/review-agent.md, scripts/run-memory-review.sh

## Overview

`review-agent` is a Haiku-tier subagent defined in `agents/review-agent.md`. It fires automatically at the end of `/z-execute` (Phase 9), `/z-review-all` (Phase 7), and `/z-debug` (within Phase 10 Finalize, shipped branch only). It reads the completed run's `events.jsonl`, cumulative diff, and `SPEC.md` (or `DEBUG.md` for debug runs), and proposes 0-3 candidate memories worth persisting to the docs knowledge base. The Phase 9 wiring lives in `skills/z-execute/SKILL.md`; Phase 7 in `skills/z-review-all/SKILL.md`; the Phase 10 memory-review step in `skills/z-debug/SKILL.md`. (The `commands/` directory these files used to live under no longer exists — everything moved to `skills/` in the 2026-06-22 rename commit `2731f1d`.)

The agent reasons but does not write. It returns a single fenced JSON block containing candidate objects. Before the agent is dispatched, `scripts/run-memory-review.sh` performs skip-condition checks and assembles artifact paths — the script is always called first, and on a non-skip result the orchestrator constructs the agent prompt from its output. When `axioms.auto_extract_post_run` is not `"false"` (default on), the script also emits an `AXIOM_READY <diff_path>` line; **all three** parent commands (`z-execute` Phase 9 step 4a, `z-review-all` Phase 7 step 4a, `z-debug` Phase 10 step d2) now parse this line and dispatch the `axiom-extractor` subagent in parallel with `review-agent` — this was previously debug-only and has since been extended to all three callers. What happens after the agent returns differs by parent command: `z-review-all` and `z-debug` run a full interactive accept/edit/skip loop that dispatches `/z-suggest-memory`; `z-execute` does **not** — see "What the user sees" below.

## Key entry points

<!-- AUTO-START: entry-points -->
- `agents/review-agent.md:1` — `review-agent` — subagent definition: role, procedure, output contract, hard rules, and slug naming anti-patterns
- `agents/review-agent.md:12` — `## Inputs from caller` — full input field list including `parent_command`, `debug_md_path`, and artifact primacy rules
- `agents/review-agent.md:27` — `## Procedure` — six-step candidate-generation procedure (read, scan signal patterns, prefer existing slugs, cap at 3, check tags, debug filter)
- `agents/review-agent.md:46` — `## Output contract` — fenced JSON schema for candidate objects; any other output is malformed
- `scripts/run-memory-review.sh:1` — `run-memory-review` — skip-condition guard and artifact-prep helper; called by all three parent commands before any agent dispatch
- `scripts/run-memory-review.sh:135` — `debug_md_missing` skip condition — fires when `parent_command: debug` and `DEBUG.md` is absent or unreadable
- `scripts/run-memory-review.sh:173` — `AXIOM_READY` emission — appends `AXIOM_READY <diff_path>` to stdout when `axioms.auto_extract_post_run != "false"` (reads via `config.py get`)
- `skills/z-execute/SKILL.md:3663` — `Phase 9` — helper call, agent dispatch, writes `memory-candidates.jsonl` + `memory_review_complete` event; **no** interactive accept/skip loop, **no** auto `/z-suggest-memory` dispatch
- `skills/z-review-all/SKILL.md:1268` — `Phase 7` — helper call, agent dispatch (legacy + INTENT-mode variants), full sequential `AskUserQuestion` accept/edit/skip loop dispatching `/z-suggest-memory` on Accept
- `skills/z-debug/SKILL.md:1105` — memory review step (within `## Phase 10 — Finalize`) — `debug_md_path` as primary artifact; sequential `AskUserQuestion` loop; explicit `memory_review_terminal` emission for `ran_empty`/`needs_user` paths
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `z-execute` — Phase 9 calls `run-memory-review.sh`, dispatches `review-agent`, writes candidates to `memory-candidates.jsonl`, emits `memory_review_complete`. No accept/skip loop runs here — see "What the user sees".
- `z-review-all` — Phase 7 calls `run-memory-review.sh`, dispatches `review-agent` (legacy or INTENT-mode prompt variant), then runs the full `AskUserQuestion` accept/edit/skip loop and dispatches `/z-suggest-memory` on Accept.
- `z-debug` — the memory-review step inside Phase 10 Finalize (shipped branch only) does the same as `z-review-all`; `debug_md_path` is passed as primary artifact; abandoned sessions are excluded; if `AXIOM_READY` is emitted, also dispatches axiom-extractor in parallel.
- `z-suggest-memory` — sole write path for accepted candidates; called with `--from-candidate-json` and `--source "incident:<RUN_ID>"` by `z-review-all` and `z-debug` only (`z-execute` does not call it automatically).
- `z-stats` — surfaces `review_agent_call`, `review_agent_failed`, and `review_agent_malformed` events for debugging.
- `axioms` — `AXIOM_READY` line from `run-memory-review.sh` triggers axiom-extractor dispatch in `z-execute` Phase 9, `z-review-all` Phase 7, and `z-debug` Phase 10; proposes candidates, never auto-approves.

## When it fires

The review-agent fires after the existing primary-deliverable push-notify at the end of:

- `/z-execute` — Phase 9 (after the Finalize phase push-notify).
- `/z-review-all` — Phase 7 (after Phase 6 `.review_state.json` cleanup push-notify).
- `/z-debug` — within Phase 10 Finalize (shipped branch only; after `debug_run_end` is logged). Not called on abandoned sessions.

Before dispatching the agent, `scripts/run-memory-review.sh` performs a skip-conditions check:

- **Skip if `empty_diff`**: no code changed since the merge-base — nothing to remember.
- **Skip if `all_tasks_skipped`** (implement-all only): no tasks executed — no signals to mine.
- **Skip if `no_plan_dir`**: `$Z_HARNESS_PLAN_DIR` is not set — the plan directory cannot be resolved.
- **Skip if `debug_md_missing`** (debug only): `DEBUG.md` does not exist or is unreadable — required primary artifact is absent.
- **Do NOT skip on halt**: halted runs are high-signal and are always reviewed.
- **Soft-skip if `tags_missing`**: `docs/llm/TAGS.txt` is absent; emits `memory_review_terminal` with `state: skipped_broken_context` and exits without blocking.

## AXIOM_READY signal

When the config key `axioms.auto_extract_post_run` is not `"false"` (default on), `run-memory-review.sh` reads the value via `python3 scripts/config.py get axioms.auto_extract_post_run` and appends a line of the form:

```
AXIOM_READY <abs_path_to_cumulative.diff>
```

**All three parent commands now act on this line** — `z-execute` Phase 9 step 4a, `z-review-all` Phase 7 step 4a, and `z-debug` Phase 10 step d2 each parse it and dispatch the `axiom-extractor` subagent in parallel with `review-agent`, passing the diff path. This is a change from the prior state where only `z-debug` handled it. The axiom-extractor proposes up to 5 candidate axioms as a fenced JSON array — nothing is written automatically, and the candidates surface for later `/z-axiom-approve` review.

To suppress `AXIOM_READY`, set `axioms.auto_extract_post_run = "false"` in your z-harness config (via `/z-setup` or `config.toml`). The old env-var knob `Z_HARNESS_AXIOM_EXTRACT=0` is no longer operative.

## Artifact primacy by parent_command

When `parent_command: debug`, `debug_md_path` is the **primary artifact** the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. The agent filters candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps — single-run patches and fix-specific minutiae are not memories.

When `parent_command: implement-all` or `review-all`, `spec_path` is primary and `debug_md_path` is unset. `z-review-all` additionally has an INTENT-mode prompt variant that swaps in `$INTENT_FILE` for `spec_path` and adds `review_contract: intent` + `ledger_path: $LEDGER_FILE` fields.

## What the user sees

Behavior diverges by parent command:

**`z-review-all` and `z-debug`** — when candidates >= 1, the orchestrator emits a `memory_candidates_ready` push-notify (`z-review-all`) or equivalent, then runs up to 3 sequential `AskUserQuestion` prompts, one per candidate:

| Option | Effect |
|---|---|
| **Accept** | Dispatches `/z-suggest-memory --concept <suggested_concept_slug> --from-candidate-json <tmp_path> --source "incident:<RUN_ID>"`. |
| **Edit** | Surfaces the candidate fields for editing, then dispatches as Accept. |
| **Skip (one-word reason)** | Logs `review_candidate_skipped {reason}` and moves to the next candidate. |
| **Skip-all-remaining** | Logs `review_skip_all` and exits the review loop immediately. |

**`z-execute`** — there is **no interactive loop**. When candidates >= 1, Phase 9 writes the raw candidate array to `$RUN_DIR/memory-candidates.jsonl`, emits `review_agent_call` and `memory_review_complete` events, and stores `N_CANDIDATES` / `CANDIDATES_FILE` for the final push-notify. Nothing calls `/z-suggest-memory` automatically for `z-execute` runs — a human has to open the JSONL file and run `/z-suggest-memory` manually if they want to persist a candidate.

If the agent returns zero candidates in any parent command, the phase exits quietly with no push-notify and no prompts.

## What gets persisted

### Per-run candidate store

When candidates >= 1, the raw candidate array is written to:

```
$RUN_DIR/memory-candidates.jsonl
```

One JSON object per line. This file is ephemeral — it lives with the run archive and is not globally aggregated in v1. For `z-execute` runs this file is currently the *only* persisted artifact from the review pass (no automatic accept path).

### On Accept (z-review-all, z-debug only)

`/z-suggest-memory` writes the accepted memory to `docs/llm/<slug>.json` and regenerates `MEMORIES-FLAT.md`. This is the only write path — the review-agent and orchestrator never mutate doc files directly.

## Telemetry events

Event-kind usage differs by parent command — see the source files for the authoritative per-phase tables.

| Event | When | Emitted by |
|---|---|---|
| `review_agent_call` | Agent returned candidates (including empty-array case) | `z-execute` (target: `"orchestration"`), `z-review-all` (target: `$RRUN`) |
| `review_agent_failed` | Agent returned without a fenced block | `z-execute` (target: `"orchestration"`), `z-review-all` (target: `$RRUN`) |
| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` | all three |
| `memory_review_complete` | N >= 1 candidates written to JSONL | `z-execute` only |
| `memory_candidates_ready` | N >= 1 candidates; push-notify fired ahead of the accept/skip loop | `z-review-all` only (explicit event) |
| `phase_end` (`name: memory_review`) | Terminal state of the phase, all paths | `z-execute` (via `log-phase.sh end`), `z-review-all` (via `log-event.sh` directly) |
| `memory_review_terminal` | Terminal state of the review pass | `run-memory-review.sh` (skip-condition paths, all 3 parent commands) **and** `z-debug` orchestrator explicitly for `ran_empty`/`needs_user` — `z-execute` and `z-review-all` do **not** emit this event kind; they use `phase_end`/`memory_review_complete` instead |
| `review_candidate_skipped` | User skipped a single candidate; includes one-word reason | `z-review-all`, `z-debug` |
| `review_skip_all` | User chose Skip-all-remaining | `z-review-all`, `z-debug` |
| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an accepted candidate | `z-review-all`, `z-debug` (only relevant where the accept loop exists) |

### `memory_review_terminal` states (as emitted by run-memory-review.sh and z-debug)

| `state` | Meaning |
|---|---|
| `skipped_broken_context` | Helper exited due to `missing_args`, `no_plan_dir`, or `tags_missing`. |
| `not_applicable` | Skip condition fired: `empty_diff`, `all_tasks_skipped`, or `debug_md_missing`. |
| `ran_empty` | Agent ran and returned zero candidates. |
| `needs_user` | Agent returned >= 1 candidates; user review loop completed. |

## Edge cases / gotchas

- `run-memory-review.sh` requires `$Z_HARNESS_PLAN_DIR` to be set; if unset, the script emits `STATUS: skipped no_plan_dir` and exits 0 without error.
- `run-memory-review.sh` soft-skips (exit 0) on missing `docs/llm/TAGS.txt` rather than failing hard; the orchestrator sees `STATUS: skipped tags_missing`.
- When `parent_command: debug`, line 5 of the helper's stdout is the absolute path to `DEBUG.md`; `LINES[4]` in the orchestrator.
- If `AXIOM_READY` is emitted, it appears after the four standard output lines (and the optional fifth DEBUG.md line for debug parent). **All three** parent commands now dispatch the axiom-extractor on this line, not just `z-debug`.
- **`z-execute` has no interactive review loop.** This is the single most important behavioral gap between the three callers — do not assume `/z-suggest-memory` gets invoked automatically for `z-execute` runs.
- **`z-execute` logs review-agent events to a fixed `"orchestration"` target**, not `$RUN` — this differs from `z-review-all`, which logs the same event kinds against `$RRUN`. This affects `jq` filters that assume a per-run event target.
- The diff base ref is resolved in order: merge-base with `origin/main`, then `HEAD~5`, then the empty-tree hash. An empty diff causes skip before any agent dispatch.
- Parse failure on agent return is a soft-skip (`review_agent_malformed` event), not a hard error — the phase exits with a push-notify hint.
- No per-call wall-clock timeout on the Agent dispatch in v1; user ctrl-c is the only escape if the Haiku call hangs. The primary-deliverable push-notify has already fired at that point.
- Candidate tags must come from `docs/llm/TAGS.txt` unless a free-form tag is explicitly justified; the agent is instructed to prefer controlled tags.
- The agent receives `index_path` (path to `docs/llm/INDEX.json`) and is expected to prefer extending an existing slug over coining a new one.
- `skills/z-execute/SKILL.md`, `skills/z-review-all/SKILL.md`, and `skills/z-debug/SKILL.md` are the canonical orchestrator definitions. The `commands/` directory these previously lived under was deleted in the 2026-06-22 rename commit (`2731f1d`, "feat(plan-family): emergent sharpen-first pipeline"); any doc still referencing `commands/z-review-all.md` or `commands/z-debug.md` is stale.
- `review_agent_failed` and `review_agent_malformed` do NOT emit `memory_review_terminal` — they are orthogonal failure classes, not terminal states of the review pass.
- `AXIOM_READY` is controlled by `axioms.auto_extract_post_run` config key (read via `config.py get`); value `"false"` suppresses it. The legacy `Z_HARNESS_AXIOM_EXTRACT` env var is no longer used.
- `z-review-all` Phase 7 has a separate INTENT-mode dispatch variant (`review_contract: intent`, `ledger_path: $LEDGER_FILE`) alongside its legacy-mode dispatch; both funnel into the same accept/edit/skip loop.

## Slug naming anti-patterns

The following slug patterns are banned in candidate output:

- **PR-number references** — e.g. `pr-1234-fix`. Slugs must be conceptual, not tied to a specific PR.
- **Library-name-alone slugs** — e.g. `serde`, `tokio`. Name the concept or failure mode, not just the library.
- **Session-specific artifact names** — e.g. `run-2026-05-25-patch`. Slugs must survive across sessions.
- **Negative-capability claims** — e.g. `dont-use-threads`. Use a positive framing of the invariant.
- **Model-specific slugs** — e.g. `haiku-context-limit`. Generalize to the pattern, not the model version.

## v1 known limitation: no per-call timeout

There is no per-call wall-clock timeout in the current `Agent(...)` infrastructure. If the Haiku subagent call hangs, ctrl-c is the only escape. The parent command's primary-deliverable push-notify has already fired at this point, so ctrl-c aborts only the memory review phase, not the run's main output.

## v1 explicit deferrals

The following mechanisms were explicitly deferred to a gated v2 plan, contingent on v1 telemetry:

1. **No utility scoring sidecar** — no `retrieval_count`, `helpful_count`, or `trust_score` tracked per candidate.
2. **No retrieval smoke-test** — after acceptance, no check that `doc-fetcher` can actually retrieve the new memory.
3. **No friction-trigger drafting** — capture happens end-of-run only. Mid-run signals resolved before exit are missed.
4. **No existing-memory verification** — stale or contradicted memories are not cross-checked during candidate generation.
5. **No Atropos / RL training** — not portable to the Claude-API-only stack.
6. **No auto-acceptance for trusted slugs** — every accepted candidate requires a user click (where an accept loop exists at all).
7. **`z-execute` still has no automatic accept path** — candidates surface as a JSONL file only; whether to add an interactive loop or automatic low-risk auto-accept is an open question, not yet planned.

## How to debug a failure

**Step 1 — Run `/z-stats` Phase 4.** Phase 4 surfaces `review_agent_failed` and `review_agent_malformed` events. Phase 4b lists recent `review_agent_call` entries with candidate counts and token spend:

```
<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>
```

**Step 2 — Inspect `events.jsonl` directly.** Filter for failure events. Remember `z-execute` logs these against target `"orchestration"`, not the run id:

```bash
jq 'select(.kind == "review_agent_failed" or .kind == "review_agent_malformed")' \
  z-harness/<slug>/archive/<RUN>/events.jsonl
```

**Step 3 — Check `memory-candidates.jsonl`.** If the file exists but is malformed, the agent returned parseable JSON but downstream write failed. If missing, the agent returned zero candidates or the phase was skipped. For `z-execute` runs, a populated file with no corresponding accepted memory is expected — nothing auto-dispatches `/z-suggest-memory` there.

**Common causes:**

- `tags_missing`: `docs/llm/TAGS.txt` does not exist. Run `/z-suggest-memory` Phase 0 to create it.
- `no_plan_dir`: `$Z_HARNESS_PLAN_DIR` is not set in the calling environment.
- `debug_md_missing`: `DEBUG.md` was not produced before the Phase 10 memory-review step ran (debug parent only).
- `malformed_json`: The agent returned prose outside the fenced block. One-shot soft-skip; no retry in v1.
- `empty_diff`: Skip-condition fired correctly — not an error.

## See also

- `skills/z-suggest-memory/SKILL.md` — sole authoring path for accepted candidates.
- `skills/z-execute/SKILL.md` — Phase 9 wiring details.
- `skills/z-review-all/SKILL.md` — Phase 7 wiring details.
- `skills/z-debug/SKILL.md` — Phase 10 wiring details (debug parent) including AXIOM_READY handling.
- `skills/z-stats/SKILL.md` — Phase 4 and Phase 4b telemetry surface.
- `agents/axiom-extractor.md` — parallel dispatch target in z-execute Phase 9, z-review-all Phase 7, and z-debug Phase 10 when AXIOM_READY fires.
