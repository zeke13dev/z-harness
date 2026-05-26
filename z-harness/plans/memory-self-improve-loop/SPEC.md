# SPEC — memory-self-improve-loop (v1 Hermes-inspired auto-review-agent)

## Overview

Ship a Haiku-tier `review-agent` subagent that auto-fires at the end of `/z-implement-all` and `/z-review-all`, examines the run's events.jsonl + cumulative diff + SPEC.md, and proposes 0–3 candidate memories. Candidates are surfaced via sequential `AskUserQuestion` prompts (Accept / Edit / Skip / Skip-all-remaining); accepted candidates flow into `/z-suggest-memory` via its existing CLI contract. Per-run token spend is logged in metrics.jsonl and surfaced by `/z-stats`.

This v1 deliberately omits utility scoring, retrieval smoke-test, asymmetric trust, friction-trigger drafting, and existing-memory verification — all deferred to gated v2 plans contingent on v1 telemetry.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/plans/memory-self-improve-loop/BRAINSTORM.md | 2026-05-25T20:56:03Z |
| RESEARCH.md | z-harness/plans/memory-self-improve-loop/RESEARCH.md | 2026-05-25T21:37:20Z |

## Known consultation gap

Phase 3 cross-LLM consultation was attempted on the 5 consult-flagged decisions and failed: both Gemini and Codex CLIs returned `session_limit`. User approved continuing with orchestrator self-critique only. A future `/z-amend` may re-consult once quotas reset. Phase 7 final review is similarly degraded.

**T001 verification — `/z-suggest-memory` batch flag audit (2026-05-25):**
Present flags: `--concept <slug>`, `--concept-hints`, `--source <prefix:ref>`, `--edit`, `--delete`, `--dry-run`, `--no-refresh-human`.
Missing flags required for non-interactive batch operation from review-agent: `--type`, `--text`, `--tags`, `--date`, `--expires`.
Decision: **T002 IS REQUIRED.** Existing flags are insufficient for non-interactive batch operation — the review-agent flow cannot drive `/z-suggest-memory` without the ability to pass memory content and metadata non-interactively.

## Coupling note (D4)

`agents/review-agent.md`'s candidate schema is intentionally aligned with `/z-suggest-memory`'s memory-object shape. Any change to either MUST update the other in the same PR.

---

## New files

### `agents/review-agent.md`

YAML frontmatter:
```yaml
---
name: review-agent
description: Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events + cumulative diff + SPEC.md; emits structured candidates as a single fenced ```json block. Does NOT write — orchestrator owns all writes via /z-suggest-memory.
tools: Read, Grep, Glob, Bash
model: haiku
---
```

Body sections (in this order):
1. **Role.** "Post-run memory candidate generator. You read what happened in this run and propose up to 3 memory candidates worth persisting. You do not write — the orchestrator handles all writes via /z-suggest-memory."
2. **Inputs from caller** (caller-prompt contract):
   - `run_dir:` absolute path to the run directory (contains events.jsonl)
   - `cumulative_diff_path:` absolute path to a pre-computed diff file (orchestrator creates this before dispatching)
   - `spec_path:` absolute path to SPEC.md if it exists (may be empty string for /z-review-all where SPEC.md still exists from /z-plan)
   - `tags_path:` absolute path to docs/llm/TAGS.txt (controlled-tag list)
   - `run_id:` the RUN string (used as `source: incident:<run_id>`)
   - `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
3. **Procedure.**
   - Read events.jsonl, cumulative_diff, SPEC.md (if present), TAGS.txt (controlled tag list).
   - Identify candidate-worthy patterns adapted from Hermes `_MEMORY_REVIEW_PROMPT` (`/tmp/hermes-agent/agent/background_review.py:34`) and `_SKILL_REVIEW_PROMPT` (`:45-148`). Signals:
     - **mistake-prevention**: a `task_review_retry` event followed by a corrected approach; a `task_halt` with a `reason`; a doc_drift event surfaced during the run.
     - **decision-rationale**: a non-obvious decision in SPEC.md that was followed despite ambiguity; a consultant pushback that the orchestrator overrode.
     - **workflow-improvement**: a step that took disproportionate wall-time; a phase that repeatedly hit the same blocker; a manual intervention the user provided that should be automated.
     - **retrieval-gap**: a doc-fetcher return of `STATUS: no_match` or `STATUS: partial` for a topic that turned out to be load-bearing.
   - For each candidate, prefer patching/extending an existing concept over creating a new one (parallels Hermes prompt preference order at `background_review.py:60-80`).
   - Hard cap: 3 candidates. If you have fewer signals, emit fewer; emit zero rather than padding.
   - Skip naming anti-patterns lifted from Hermes (`background_review.py:90-120`): no PR-number names, no library-alone names, no session-specific artifact names, no negative capability claims ("doesn't support X"), no model-specific quirks.
4. **Output contract.** Single fenced ```json block. Schema:
   ```json
   [
     {
       "candidate_kind": "mistake-prevention | decision-rationale | workflow-improvement | retrieval-gap",
       "type": "anti-pattern | invariant | gotcha | decision",
       "text": "<≤280 chars; the memory body>",
       "tags": ["<from TAGS.txt or kebab-case free-form>"],
       "suggested_concept_slug": "<existing concept slug from INDEX.json or new slug>",
       "evidence_citations": ["path/to/file.rs:42", "z-harness/plans/<slug>/SPEC.md:L120-130"],
       "rationale": "<≤200 chars; why this memory is worth persisting>"
     }
   ]
   ```
   - Empty array `[]` if nothing memory-worthy.
   - Tags MUST be from TAGS.txt unless free-form is justified by the candidate's nature.
   - `text` follows /z-suggest-memory's memory-object `text` field constraints.
5. **Hard rules.**
   - You have NO write tools beyond Bash for reading. Do not attempt to mutate `docs/llm/`. Do not call `/z-suggest-memory` directly.
   - Return exactly one fenced ```json block. Any other output is malformed and will be rejected by the orchestrator.
   - Do not echo the input prompts back.

---

### `scripts/run-memory-review.sh`

Bash helper called by both `/z-implement-all` and `/z-review-all`. Encapsulates the review-agent lifecycle so the two command files stay DRY.

Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`

Where `<parent_command>` is `implement-all` or `review-all`.

Behavior (in order):
1. Resolve `$BASE = $Z_HARNESS_PLAN_DIR` and `$RUN_DIR = $BASE/archive/$RUN`.
2. **Skip-conditions check** (D7 refined):
   - Compute `git merge-base HEAD origin/main` (fallback `HEAD~5`); store base ref.
   - Diff `<base>..HEAD`; if empty → emit `phase_end` with `name: memory_review`, `skipped: true`, `skip_reason: empty_diff`, exit 0.
   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
   - NOTE: do NOT skip on halt — halted runs are high-signal.
3. Write cumulative diff to `$RUN_DIR/cumulative.diff` (truncate to 5000 lines for context budget).
4. Verify `docs/llm/TAGS.txt` exists (if missing, emit `review_agent_failed` event with reason `tags_missing` and exit 0 — soft-skip).
5. (Caller — the orchestrator — handles the actual `Agent()` dispatch and JSON parse; this script's job is the deterministic plumbing.) Print to stdout, on separate lines: `STATUS: ready`, then `<RUN_DIR>/cumulative.diff`, then `<BASE>/SPEC.md`, then `docs/llm/TAGS.txt` (absolute paths).
6. Exit 0. The skip paths print `STATUS: skipped <reason>` on the first line and exit 0 (skipping is success, not failure).

Output contract: exit 0 always (skip is success); print `STATUS: <ready|skipped>` as first stdout line; if `ready`, also print absolute paths to the three artifacts the agent needs.

---

### `docs/human/review-agent.md`

Human-tier doc describing what the review-agent is, when it fires, what users see (the AskUser prompts), what gets persisted, how to debug a failure.

### `docs/llm/review-agent.json`

LLM-tier concept entry. Fields per docs/llm convention:
- `slug: review-agent`
- `summary:` one-paragraph
- `source_file: ["agents/review-agent.md", "scripts/run-memory-review.sh"]`
- `entry_points:` `[]` (no public CLI; it's an internal subagent)
- `consumed_by:` `["z-implement-all", "z-review-all"]`
- `depends_on:` `["z-suggest-memory", "z-stats"]`
- `invariants:` list including "subagent never writes; orchestrator owns all writes" and "skip-conditions check before dispatch (cost guard)"
- `memories: []`
- `last_updated:` will be set at write-time

Also update `docs/llm/INDEX.json` to include the new `review-agent` concept and bump `generated_at`.

---

## Modified files

### `commands/z-implement-all.md`

Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.

Phase 9 body:
1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
2. If first line is `STATUS: skipped <reason>` — emit `phase_end` with `phase: 9, name: "memory_review", skipped: true, skip_reason: "<reason>"` and exit phase.
3. If first line is `STATUS: ready`, parse the three paths.
4. Dispatch:
   ```
   Agent(
     subagent_type="review-agent",
     description="Memory review for <slug>",
     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
   )
   ```
5. Parse the agent's return: extract single fenced ```json block. On parse failure → emit `review_agent_malformed` event, soft-skip per D8 (push-notify the failure with hint, exit phase).
6. If candidates array is empty → log `phase_end` with `candidates_emitted: 0`, exit phase quietly (no push-notify).
7. If candidates ≥1:
   - Write the raw candidates array to `$RUN_DIR/memory-candidates.jsonl` (one object per line; not strict JSONL since each line is a JSON object).
   - Emit `review_agent_call` event with `{subagent_model: "haiku", subagent_input_tokens: <from Agent return>, subagent_output_tokens: <from Agent return>, candidates_emitted: N}`.
   - **Push-notify** (new event): `memory_candidates_ready` — "<N> memory candidate(s) ready for review."
   - **Sequential AskUserQuestion per candidate** (D6): per-candidate prompt with options Accept / Edit / Skip (one-word reason) / Skip-all-remaining.
   - For each Accept: dispatch `/z-suggest-memory --concept <slug> --source "incident:<RUN>"` with the candidate text + tags piped via the existing CLI. On STATUS: ok, increment `accepted` counter. On STATUS: skipped or bad_input, log `review_agent_suggest_failed` with reason and continue.
   - For each Edit: surface the candidate fields one more time with the user's edits applied, then dispatch as Accept.
   - For Skip: capture the one-word reason, log `review_candidate_skipped {reason}`.
   - For Skip-all-remaining: log `review_skip_all` and break the loop.
8. Final accounting: emit `phase_end` with `{phase: 9, name: "memory_review", wall_ms, accepted, edited, skipped, candidates_emitted}`.

### `commands/z-review-all.md`

Insert a new `## Phase 7 — Memory review (auto)` section AFTER Phase 6's `.review_state.json` cleanup (line ~368) and AFTER the existing Phase 6 push-notify, BEFORE the "Hard rules" / closing section.

Body identical to /z-implement-all Phase 9 above EXCEPT `parent_command: review-all` in the Agent dispatch, and the SPEC.md path passed to the agent should be `$BASE/SPEC.md` (which exists since /z-review-all is post-/z-plan).

### `skills/z-implement-all/SKILL.md` and `skills/z-review-all/SKILL.md`

Mirror the new phase additions verbatim (these are bundled copies of the commands).

### `commands/z-stats.md` and `skills/z-stats/SKILL.md`

In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b section called "Recent memory-review activity":
```bash
jq -c 'select(.kind == "review_agent_call")' "$METRICS" | tail -10
```
Output line per call: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>`.

No changes to Phase 3 (token spend) — the existing `subagent_model` group-by picks up `review_agent_call` events automatically because of D10.

### `commands/z-suggest-memory.md` and `skills/z-suggest-memory/SKILL.md`

Documentation-only addition: in the existing `--source` flag docs, add an example showing `--source "incident:<RUN_ID>"` is the canonical prefix used by the review-agent flow. No code change; the existing source-prefix regex already accepts `incident:`.

### Multi-IDE exports

Run the existing `scripts/export-agy.py`, `scripts/export-codex.py`, `scripts/export-cursor.py` so the new `agents/review-agent.md` and updated commands/skills propagate to `exports/agy/`, `exports/codex/`, `exports/cursor/`. This is mechanical — these scripts already handle the file set; just need to re-run them after the source files exist.

### `README.md`

One-line addition in the agents table (if there's one) referencing review-agent and its tier (Haiku).

---

## Edge cases and invariants

- **Empty events.jsonl.** Should not happen (run_start always emitted) but if events.jsonl is empty, review-agent should treat as "no signal" and return `[]`. Orchestrator skip path handles emission.
- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
- **Concurrent runs (same slug, different RUNs).** Per-run RUN_DIR isolation eliminates collisions on `memory-candidates.jsonl`. `/z-suggest-memory`'s atomic writes (existing) handle concurrent `docs/llm/<slug>.json` mutation if two reviews accept simultaneously.
- **Subagent timeout.** No per-call wall-clock timeout in current Agent infrastructure (known v1 limitation per `/z-research` spec). If the Haiku call hangs, user ctrl-c is the escape. Document this in human-tier docs.
- **Parse failure recovery.** The orchestrator does NOT retry on `review_agent_malformed` — soft-skip per D8. A v2 plan could add one retry with a "your previous output was malformed; produce a clean fenced json block" reprompt.

## DRY / KISS / SOLID

- **DRY:** Both /z-implement-all and /z-review-all share `scripts/run-memory-review.sh` for skip-conditions + path resolution. They share the same agent contract. Only the new phase's body and dispatch live in the two command files (minimal duplication; the orchestration loop is identical).
- **KISS:** v1 is one Haiku subagent + one shell helper + two phase additions + one new event kind + a new push-notify event. Six existing v1-deferred mechanisms (utility scoring, smoke test, asymmetric trust, friction trigger, existing-memory verify, auto-accept) are explicitly out of scope and live as Open Questions in PLAN.md.
- **SOLID — single responsibility:** The agent reasons about what to remember; the orchestrator owns all writes (D9); `/z-suggest-memory` remains sole authoring path; `/z-stats` surfaces telemetry. Each layer's responsibility is uncrossed.
