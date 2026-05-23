 `/z-maintain-docs`; not a rigid task on its own.
skills/z-plan/SKILL.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
skills/z-plan/SKILL.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
skills/z-plan/SKILL.md:266:The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.
commands/z-implement-all.md:2:description: Orchestrate implementation of ALL pending tasks in z-harness/TASKS.md, spawning a fresh implementer subagent per task and a codex-reviewer per task. Halts on blockers, retries once on review failure, push-notifies user on every gate.
commands/z-implement-all.md:12:2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`:
commands/z-implement-all.md:13:   - Enumerate subdirs of `z-harness/` containing a `TASKS.md`.
commands/z-implement-all.md:14:   - Also check for legacy flat layout (`z-harness/TASKS.md` directly).
commands/z-implement-all.md:15:   - One candidate → use it; export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).
commands/z-implement-all.md:19:4. Read `$BASE/TASKS.md` once into memory — you'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
commands/z-implement-all.md:25:   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
commands/z-implement-all.md:38:   This is asked exactly once per slug; it's a per-plan cache so different plans can target different test frameworks.
commands/z-implement-all.md:39:8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
commands/z-implement-all.md:49:5. **Atomic TASKS.md updates.** The orchestrator is single-writer. Read the file, modify multiple task statuses if a batch finishes together, write once. Never partial-write.
commands/z-implement-all.md:68:Re-read `TASKS.md`. Build a quick eligibility check:
commands/z-implement-all.md:105:Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
commands/z-implement-all.md:112:**Pass paths, not slices.** Do NOT extract SPEC/PLAN slices in the main thread. Subagents have Read and will pull what they need directly from `$BASE/SPEC.md` and `$BASE/PLAN.md`. This is the single biggest token-saver in v2.
commands/z-implement-all.md:127:1. **Explicit user tag.** If the task block has a `**DOCS:** <concept-slug>` line (added by `/z-plan` Phase 8), include `docs/llm/<concept-slug>.json` and `docs/human/<concept-slug>.md`.
commands/z-implement-all.md:144:  prompt="<task-id>\n\n<task block verbatim>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths from step 4b — Read these for concept grounding): <paths>"
commands/z-implement-all.md:151:- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
commands/z-implement-all.md:176:  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
commands/z-implement-all.md:182:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
commands/z-implement-all.md:190:  prompt="task_id: <id>\nslug: <Z_HARNESS_SLUG>\nremote_host: zeke-pc\nverify_cmd: <REMOTE_VERIFY line content>\n$BASE: <abs path>"
commands/z-implement-all.md:197:- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
commands/z-implement-all.md:214:  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <criteria verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelated downstream files (paths only; reviewer Reads them itself): <related_files paths from step 4a>\nrelevant_docs (paths — verify the diff didn't break invariants stated in these): <paths from step 4b>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
commands/z-implement-all.md:316:1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
commands/z-implement-all.md:332:1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
commands/z-implement-all.md:376:  "$(printf '{"slug":"%s","n_pending":%d,"parallel":%d}' "$SLUG" "$N" "$N_PAR")")"
commands/z-plan.md:2:description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
commands/z-plan.md:14:Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.
commands/z-plan.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
commands/z-plan.md:19:2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents — this is what namespaces every output path.
commands/z-plan.md:20:3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
commands/z-plan.md:32:   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
commands/z-plan.md:36:9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
commands/z-plan.md:43:**All paths in subsequent phases live under `z-harness/<slug>/`:**
commands/z-plan.md:44:- `z-harness/<slug>/SPEC.md`
commands/z-plan.md:45:- `z-harness/<slug>/PLAN.md`
commands/z-plan.md:46:- `z-harness/<slug>/TASKS.md`
commands/z-plan.md:47:- `z-harness/<slug>/archive/<run-id>/...`
commands/z-plan.md:49:Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.
commands/z-plan.md:76:## Phase 0 — Premise check
commands/z-plan.md:101:  description="Doc context for <slug>",
commands/z-plan.md:108:If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
commands/z-plan.md:111:  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
commands/z-plan.md:124:  description="Find <thing> related to <slug>",
commands/z-plan.md:208:## Phase 6 — Write SPEC.md and PLAN.md
commands/z-plan.md:210:Create `z-harness/$Z_HARNESS_SLUG/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.
commands/z-plan.md:212:Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.
commands/z-plan.md:218:Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
commands/z-plan.md:224:## Phase 8 — TASKS.md
commands/z-plan.md:226:Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.
commands/z-plan.md:241:**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.
commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
commands/z-plan.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
commands/z-plan.md:266:The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.

codex
I found `/z-plan` currently derives the slug first, then treats `z-harness/<slug>/` as the namespace for all artifacts. I’m reading the exact Phase 0 and surrounding setup now to check whether precontext detection fits cleanly or needs a new pre-Phase step.
exec
/bin/zsh -lc "sed -n '1,120p' skills/z-plan/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
argument-hint: <feature or task description>
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
   ```
   Docs are <stale_pct>% stale (>= <threshold>% threshold).
   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
   ```
   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.

**All paths in subsequent phases live under `z-harness/<slug>/`:**
- `z-harness/<slug>/SPEC.md`
- `z-harness/<slug>/PLAN.md`
- `z-harness/<slug>/TASKS.md`
- `z-harness/<slug>/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/<phase>.md` so the run is resumable.

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

### 1b. Explore for gaps (Haiku by default)

Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.

**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:

```

exec
/bin/zsh -lc "sed -n '1,80p' commands/z-plan.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
argument-hint: <feature or task description>
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
   ```
   Docs are <stale_pct>% stale (>= <threshold>% threshold).
   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
   ```
   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.

**All paths in subsequent phases live under `z-harness/<slug>/`:**
- `z-harness/<slug>/SPEC.md`
- `z-harness/<slug>/PLAN.md`
- `z-harness/<slug>/TASKS.md`
- `z-harness/<slug>/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/<phase>.md` so the run is resumable.

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)

exec
/bin/zsh -lc "sed -n '1,70p' skills/z-plan-light/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan if scope grows beyond ~5 files or >2 non-obvious decisions.
argument-hint: <fix description>
---

You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.

This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.

## Setup

1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
2. Export `Z_HARNESS_SLUG=<slug>`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
   ```
6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.

## Auto-bail thresholds (check throughout)

At any phase, if you discover:

- **>5 candidate files** need editing
- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
- **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
- **The user explicitly says** "this might be bigger than I thought"

→ STOP. Write `z-harness/$Z_HARNESS_SLUG/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.

## Phase 1 — Premise + quick exploration (combined)

**Premise check.** Don't take the task description for granted:
- Is this actually a bug? Could it be config / expected behavior / a symptom of something else?
- Will the proposed fix (if the user named one) actually solve the underlying problem?
- Is there a materially better path the user hasn't considered?

If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.

**Quick exploration.**
1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
   ```
   Agent(subagent_type="doc-fetcher",
         description="Doc context for <slug>",
         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
   ```
2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.

Output: 1-paragraph problem statement + 1-paragraph context. Save to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/phase1-context.md`.

**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.

## Phase 2 — Identify the single key decision

Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.

exec
/bin/zsh -lc "sed -n '1,65p' skills/z-amend/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendment is non-obvious.
argument-hint: <what to change about the plan>
---

You are running the **z-harness `/z-amend`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.

This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.

## Phase 0 — Discover plan slug

Multiple plans may coexist under `z-harness/<slug>/`. Determine which one to amend:

1. Enumerate candidates: immediate subdirs of `z-harness/` that contain **any** of `SPEC.md`, `PLAN.md`, `TASKS.md`, or `FIX.md`. Also check for legacy flat layout.
2. Choose:
   - **One candidate** → use it. `export Z_HARNESS_SLUG=<slug>` (or leave unset for legacy).
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
   - **Zero candidates** → tell the user there's no plan to amend; suggest `/z-plan` or `/z-plan-light`. Stop.
3. From here on, **`$BASE`** refers to `z-harness/$Z_HARNESS_SLUG` (or `z-harness` if legacy).
4. Detect **mode**:
   - `full` if `$BASE/SPEC.md` exists.
   - `light` if only `$BASE/FIX.md` exists.

## Phase 1 — Setup + telemetry

1. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-amend-<slug>`
2. `mkdir -p $BASE/archive/$RUN/transcripts`
3. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["amendment"] = sys.argv[2]; v["mode"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "<full|light>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
   ```
4. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 2 — Read the current plan

Read every artifact that exists for this slug:

- **full mode:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
- **light mode:** `$BASE/FIX.md`

For **full mode**, also snapshot completed task state. Run:
```bash
grep -E '^\- \[x\] T[0-9]+' $BASE/TASKS.md > $BASE/archive/$RUN/completed-tasks.txt || true
```
This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.

## Phase 3 — Impact analysis

Articulate, in plain prose, what the amendment changes. Write `$BASE/archive/$RUN/amendment.md`:

```markdown
# Amendment: <one-line summary>


codex
**Short Answer**

I’d keep the tentative calls, with two refinements:

- D1: **A, distinct `BRAINSTORM.md` and `RESEARCH.md`**, but give each file a small metadata header.
- D2: **D, Claude fresh subagent + Codex + Gemini**, with an explicit synthesis bias check.
- D4: **A, shared slug directory**, with `/z-plan` treating precontext-only dirs as continuations, not collisions.
- D5: **Full inline up to a cap, then structured summary fallback**, and pass the same bounded context to all ideators.

**D1: Artifact Contract**

Recommend **A: distinct artifacts**.

`BRAINSTORM.md` and `RESEARCH.md` are different products. A brainstorm artifact is about competing framings, plan shapes, unknowns, and decision surfaces. A research artifact is about external or codebase terrain, facts, constraints, evidence, and open questions. Forcing both into `PRECONTEXT.md` would make the producer and consumer APIs look simpler while making the content model less honest.

Add a lightweight header to each file:

```markdown
---
artifact: brainstorm
slug: add-foo
generated_at: 2026-05-22T...
command: z-brainstorm
input_hash: ...
depends_on:
  - RESEARCH.md
---
```

That avoids needing a manifest for v1 while still giving `/z-plan` enough information to warn about stale or mismatched artifacts.

Tradeoff: `/z-plan` learns two schemas. That is acceptable because the schemas should be small and semantically clear.

Concrete risks:
- Presence alone can be misleading if a stale `RESEARCH.md` sits in the slug dir.
- Two producers may disagree on scope if slug derivation was fuzzy.
- `/z-plan` can accidentally overweight whichever artifact is read last unless the consumption rules are explicit.

Missed consideration: include “consumed precontext” in `PLAN.md`, probably under `Inputs` or `Planning Context`, so later reviewers know whether the plan came from research, brainstorm, both, or neither.

Interaction with D4: distinct files work well in a shared slug. The slug directory becomes the project archive, not a single-command output folder.

**D2: Ideator Set**

Recommend **D: Claude fresh subagent + Codex + Gemini**, with anti-bias guardrails.

The value of `/z-brainstorm` is viewpoint diversity. Removing Claude entirely because the orchestrator is Claude gives up a useful high-quality ideator. The better fix is procedural: make Claude an ideator in a fresh context, then require synthesis to compare all three outputs against named criteria rather than “which one feels right.”

The synthesis should explicitly include:

```text
If the selected primary framing came from the Claude ideator, explain why it beats Codex and Gemini on concrete criteria. If it does not, merge only the specific Claude elements that survived comparison.
```

Tradeoff: this adds process overhead and a small risk of performative anti-bias. The orchestrator might still favor phrasing or assumptions that resemble its own style.

Concrete risks:
- Claude ideator and Claude orchestrator may converge on the same blind spot.
- If one ideator gets richer context than the others, the “best” answer may reflect context advantage, not model insight.
- If outputs are not normalized into the same structure, synthesis becomes vibes-based.

Missed consideration: force every ideator to return the same sections, such as `Framing`, `Core hypothesis`, `Risks`, `Plan implications`, `What would change my mind`. This makes synthesis comparable.

Interaction with D5: yes, the anti-bias check should flag context asymmetry. The easiest rule is: **all ideators get the same inline precontext payload**, even if Claude could theoretically read by reference.

**D4: Slug Derivation**

Recommend **A: shared slug by default**.

This fits the existing harness model. `/z-plan` already writes everything under `z-harness/<slug>/`, and other commands already discover slug directories by artifact presence. `/z-amend`, for example, treats a slug dir as an artifact set rather than a per-command run folder. So having:

```text
z-harness/add-foo/BRAINSTORM.md
z-harness/add-foo/RESEARCH.md
z-harness/add-foo/SPEC.md
z-harness/add-foo/PLAN.md
z-harness/add-foo/TASKS.md
```

is clean and discoverable.

Tradeoff: archive directories can accumulate mixed-stage artifacts. That is fine, but `/z-plan` must distinguish “existing precontext” from “existing finished plan.”

Concrete risks:
- Current `/z-plan` setup checks existing slug dirs as possible collisions. A dir containing only `BRAINSTORM.md` or `RESEARCH.md` should be treated as a continuation candidate, not a collision requiring scary wording.
- Re-running `/z-brainstorm` could overwrite an artifact that `/z-plan` already consumed.
- Different slash commands might derive slightly different slugs from similar prompts.

Missed consideration: support explicit `--slug <slug>` on both new commands. Shared slug only works well if users can intentionally chain.

Interaction with D1: no ambiguity if Phase 0 reads both independently. There should be no “preferred” artifact. Compose them as:
1. `RESEARCH.md` supplies evidence, constraints, facts, open questions.
2. `BRAINSTORM.md` supplies candidate framings and decision surfaces.
3. If they conflict, `/z-plan` raises the conflict before planning.

**D5: RESEARCH.md Into Brainstorm Ideators**

Recommend **A with a cap**, but make it symmetrical: pass th