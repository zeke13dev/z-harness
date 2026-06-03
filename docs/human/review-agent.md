# review-agent

> Last updated: 2026-06-03
> Covers source: agents/review-agent.md, scripts/run-memory-review.sh

## Overview

`review-agent` is a Haiku-tier subagent defined in `agents/review-agent.md`. It fires automatically at the end of `/z-implement-all` (Phase 9), `/z-review-all` (Phase 7), and `/z-debug` (Phase 10, shipped branch only). It reads the completed run's `events.jsonl`, cumulative diff, and `SPEC.md` (or `DEBUG.md` for debug runs), and proposes 0-3 candidate memories worth persisting to the docs knowledge base. The Phase 9 wiring lives in `skills/z-implement-all/SKILL.md`; Phase 7 in `skills/z-review-all/SKILL.md`; Phase 10 in `skills/z-debug/SKILL.md`.

The agent reasons but does not write. It returns a single fenced JSON block containing candidate objects. The orchestrator owns all writes: it parses the candidates, surfaces them via `AskUserQuestion` prompts, and routes accepted candidates through `/z-suggest-memory`. Before the agent is dispatched, `scripts/run-memory-review.sh` performs skip-condition checks and assembles artifact paths — the script is always called first, and on a non-skip result the orchestrator constructs the agent prompt from its output. When `Z_HARNESS_AXIOM_EXTRACT` is not `"0"` (the default), the script also emits an `AXIOM_READY <diff_path>` line so `z-debug` Phase 10 can dispatch the axiom-extractor in parallel with the review-agent.

## Key entry points

- `agents/review-agent.md:1` — `review-agent` — subagent definition: role, procedure, output contract, hard rules, and slug naming anti-patterns
- `agents/review-agent.md:12` — `## Inputs from caller` — full input field list including `parent_command`, `debug_md_path`, and artifact primacy rules
- `agents/review-agent.md:27` — `## Procedure` — six-step candidate-generation procedure (read, scan signal patterns, prefer existing slugs, cap at 3, check tags, debug filter)
- `agents/review-agent.md:46` — `## Output contract` — fenced JSON schema for candidate objects; any other output is malformed
- `scripts/run-memory-review.sh:1` — `run-memory-review` — skip-condition guard and artifact-prep helper; called by all three parent commands before any agent dispatch
- `scripts/run-memory-review.sh:135` — `debug_md_missing` skip condition — fires when `parent_command: debug` and `DEBUG.md` is absent or unreadable
- `scripts/run-memory-review.sh:173` — `AXIOM_READY` emission — appends `AXIOM_READY <diff_path>` to stdout when `Z_HARNESS_AXIOM_EXTRACT != "0"`
- `skills/z-implement-all/SKILL.md:818` — `Phase 9` — orchestrator Phase 9: helper call, skip handling, agent dispatch, parse, accept/skip loop
- `skills/z-review-all/SKILL.md:447` — `Phase 7` — orchestrator Phase 7: same as Phase 9 but without `all_tasks_skipped` skip condition
- `skills/z-debug/SKILL.md:795` — `Phase 10 memory review` — orchestrator Phase 10 (shipped branch only): `debug_md_path` as primary artifact; abandoned sessions excluded; optional parallel axiom-extractor dispatch on `AXIOM_READY`

## How it interacts with others

- `z-implement-all` — Phase 9 calls `run-memory-review.sh`, then dispatches `review-agent`, then runs the accept/skip loop
- `z-review-all` — Phase 7 does the same; signals differ (no `all_tasks_skipped` skip condition here)
- `z-debug` — Phase 10 (shipped branch only) does the same; `debug_md_path` is passed as primary artifact; abandoned sessions are excluded; if `AXIOM_READY` is emitted, also dispatches axiom-extractor in parallel
- `z-suggest-memory` — sole write path for accepted candidates; called with `--from-candidate-json` and `--source "incident:<RUN_ID>"`
- `z-stats` — surfaces `review_agent_call`, `review_agent_failed`, and `review_agent_malformed` events for debugging
- `axioms` — `AXIOM_READY` line from `run-memory-review.sh` triggers axiom-extractor dispatch in `z-debug` Phase 10 only; proposes candidates, never auto-approves

## When it fires

The review-agent fires after the existing primary-deliverable push-notify at the end of:

- `/z-implement-all` — Phase 9 (after the Finalize phase push-notify).
- `/z-review-all` — Phase 7 (after Phase 6 `.review_state.json` cleanup push-notify).
- `/z-debug` — Phase 10 (shipped branch only; after debug_run_end is logged). Not called on abandoned sessions.

Before dispatching the agent, `scripts/run-memory-review.sh` performs a skip-conditions check:

- **Skip if `empty_diff`**: no code changed since the merge-base — nothing to remember.
- **Skip if `all_tasks_skipped`** (implement-all only): no tasks executed — no signals to mine.
- **Skip if `no_plan_dir`**: `$Z_HARNESS_PLAN_DIR` is not set — the plan directory cannot be resolved.
- **Skip if `debug_md_missing`** (debug only): `DEBUG.md` does not exist or is unreadable — required primary artifact is absent.
- **Do NOT skip on halt**: halted runs are high-signal and are always reviewed.
- **Soft-skip if `tags_missing`**: `docs/llm/TAGS.txt` is absent; emits `memory_review_terminal` with `state: skipped_broken_context` and exits without blocking.

## AXIOM_READY signal

When `Z_HARNESS_AXIOM_EXTRACT` is unset or any value other than `"0"` (meaning it is on by default), `run-memory-review.sh` appends a line of the form:

```
AXIOM_READY <abs_path_to_cumulative.diff>
```

Only `z-debug` Phase 10 (d2 sub-step) currently acts on this line. When present, it dispatches the `axiom-extractor` subagent in parallel with `review-agent`, passing the diff path. The axiom-extractor proposes up to 5 candidate axioms as a fenced JSON array — nothing is written automatically, and the candidates surface for later `/z-axiom-approve` review. `z-implement-all` and `z-review-all` do not currently handle `AXIOM_READY`.

## Artifact primacy by parent_command

When `parent_command: debug`, `debug_md_path` is the **primary artifact** the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. The agent filters candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps — single-run patches and fix-specific minutiae are not memories.

When `parent_command: implement-all` or `review-all`, `spec_path` is primary and `debug_md_path` is unset.

## What the user sees

When candidates >= 1, the orchestrator emits a `memory_candidates_ready` push-notify:

```
<N> memory candidate(s) ready for review.
```

Then, up to 3 sequential `AskUserQuestion` prompts appear, one per candidate:

| Option | Effect |
|---|---|
| **Accept** | Dispatches `/z-suggest-memory --from-candidate-json <tmp_path> --source "incident:<RUN_ID>"`. |
| **Edit** | Surfaces the candidate fields for editing, then dispatches as Accept. |
| **Skip (one-word reason)** | Logs `review_candidate_skipped {reason}` and moves to the next candidate. |
| **Skip-all-remaining** | Logs `review_skip_all` and exits the review loop immediately. |

If the agent returns zero candidates, the phase exits quietly with no push-notify and no prompts.

## What gets persisted

### Per-run candidate store

When candidates >= 1, the raw candidate array is written to:

```
$RUN_DIR/memory-candidates.jsonl
```

One JSON object per line. This file is ephemeral — it lives with the run archive and is not globally aggregated in v1.

### On Accept

`/z-suggest-memory` writes the accepted memory to `docs/llm/<slug>.json` and regenerates `MEMORIES-FLAT.md`. This is the only write path — the review-agent and orchestrator never mutate doc files directly.

## Telemetry events

| Event | When |
|---|---|
| `review_agent_call` | On successful agent return; fields: `subagent_model`, `subagent_input_tokens`, `subagent_output_tokens`, `candidates_emitted`. |
| `review_agent_failed` | Agent dispatch failed or returned no parseable output; fields include `reason`. |
| `review_agent_malformed` | Agent returned output but the fenced JSON block could not be parsed. |
| `memory_candidates_ready` | N >= 1 candidates; push-notify fired. |
| `memory_review_terminal` | Emitted at the terminal state of every review pass; fields: `state`, `skip_reason`, `parent_command`, `candidates`, `accepted`, `slug`. |
| `review_candidate_skipped` | User skipped a single candidate; includes one-word reason. |
| `review_skip_all` | User chose Skip-all-remaining. |
| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an accepted candidate; logged and iteration continues. |
| `phase_end` | Emitted at end of Phase 9 / Phase 7 / Phase 10 with `{phase, name: "memory_review", wall_ms, accepted, edited, skipped, candidates_emitted}`. |

### `memory_review_terminal` states

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
- If `AXIOM_READY` is emitted, it appears after the four standard output lines (and the optional fifth DEBUG.md line for debug parent). Only `z-debug` Phase 10 currently processes it.
- The diff base ref is resolved in order: merge-base with `origin/main`, then `HEAD~5`, then the empty-tree hash. An empty diff causes skip before any agent dispatch.
- Parse failure on agent return is a soft-skip (`review_agent_malformed` event), not a hard error — the phase exits with a push-notify hint.
- No per-call wall-clock timeout on the Agent dispatch in v1; user ctrl-c is the only escape if the Haiku call hangs. The primary-deliverable push-notify has already fired at that point.
- Candidate tags must come from `docs/llm/TAGS.txt` unless a free-form tag is explicitly justified; the agent is instructed to prefer controlled tags.
- The agent receives `index_path` (path to `docs/llm/INDEX.json`) and is expected to prefer extending an existing slug over coining a new one.
- `skills/z-implement-all/SKILL.md`, `skills/z-review-all/SKILL.md`, and `skills/z-debug/SKILL.md` are the canonical orchestrator definitions; `commands/` equivalents may be stale.
- `review_agent_failed` and `review_agent_malformed` do NOT emit `memory_review_terminal` — they are orthogonal failure classes, not terminal states of the review pass.
- `AXIOM_READY` is suppressed by setting `Z_HARNESS_AXIOM_EXTRACT=0`; any other value (including unset or `"false"`) enables it.

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

The following six mechanisms were explicitly deferred to a gated v2 plan, contingent on v1 telemetry:

1. **No utility scoring sidecar** — no `retrieval_count`, `helpful_count`, or `trust_score` tracked per candidate.
2. **No retrieval smoke-test** — after acceptance, no check that `doc-fetcher` can actually retrieve the new memory.
3. **No friction-trigger drafting** — capture happens end-of-run only. Mid-run signals resolved before exit are missed.
4. **No existing-memory verification** — stale or contradicted memories are not cross-checked during candidate generation.
5. **No Atropos / RL training** — not portable to the Claude-API-only stack.
6. **No auto-acceptance for trusted slugs** — every accepted candidate requires a user click.

## How to debug a failure

**Step 1 — Run `/z-stats` Phase 4.** Phase 4 surfaces `review_agent_failed` and `review_agent_malformed` events. Phase 4b lists recent `review_agent_call` entries with candidate counts and token spend:

```
<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>
```

**Step 2 — Inspect `events.jsonl` directly.** Filter for failure events:

```bash
jq 'select(.kind == "review_agent_failed" or .kind == "review_agent_malformed")' \
  z-harness/<slug>/archive/<RUN>/events.jsonl
```

**Step 3 — Check `memory-candidates.jsonl`.** If the file exists but is malformed, the agent returned parseable JSON but downstream write failed. If missing, the agent returned zero candidates or the phase was skipped.

**Common causes:**

- `tags_missing`: `docs/llm/TAGS.txt` does not exist. Run `/z-suggest-memory` Phase 0 to create it.
- `no_plan_dir`: `$Z_HARNESS_PLAN_DIR` is not set in the calling environment.
- `debug_md_missing`: `DEBUG.md` was not produced before Phase 10 ran (debug parent only).
- `malformed_json`: The agent returned prose outside the fenced block. One-shot soft-skip; no retry in v1.
- `empty_diff`: Skip-condition fired correctly — not an error.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/review-agent.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## See also

- `skills/z-suggest-memory/SKILL.md` — sole authoring path for accepted candidates.
- `skills/z-implement-all/SKILL.md` — Phase 9 wiring details.
- `skills/z-review-all/SKILL.md` — Phase 7 wiring details.
- `skills/z-debug/SKILL.md` — Phase 10 wiring details (debug parent) including AXIOM_READY handling.
- `skills/z-stats/SKILL.md` — Phase 4 and Phase 4b telemetry surface.
- `agents/axiom-extractor.md` — parallel dispatch target in z-debug Phase 10 when AXIOM_READY fires.
