---
name: z-plan
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
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, read it first. It's the cheap ground-truth oracle for Phase 1 Explore — use it to scope which modules to investigate. Treat it as authoritative until evidence in the code contradicts it (log `doc_drift` events when that happens; `/z-maintain-docs` will follow up).

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

Read the codebase. Use Read/Grep/Glob, and the `Explore` subagent for broad sweeps. Identify: touched files, reusable patterns, constraints (types, framework, tests, perf, security), adjacent code that could regress.

**If `docs/llm/INDEX.json` exists, use it first** — it's a cheap structured map of concepts → source files. For each Explore dispatch, include `relevant_concepts: <paths from INDEX.json>` in the prompt so the Explore agent reads those JSON entries first and treats them as scaffolding (saves ~30-50% of broad-repo grep cost). The Explore is still authorized to verify the docs against current code; if it finds drift, it should report it in its return and you log a `doc_drift` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

`/z-maintain-docs` later consumes these events to know which concepts need refresh.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore is a Claude (Opus by default) repo-mapping pass that consumes 2–3 M tokens of cache-read context. In the data-overhaul run, 5 Explore agents ate 13.9 M tokens — ~93% of the entire planning budget — and the marginal Explore beyond the third surfaced no new findings the prior three missed. If 3 is not enough, prefer running direct Read/Grep/Glob from the orchestrator (which reuses the orchestrator's already-warm context) over spawning a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.

Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.

## Phase 2 — Decisions document

Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/decisions.md`. For each decision:

- **Decision:** what's being decided
- **Options:** ≥1 candidate, with one-line tradeoffs
- **Tentative call:** your current pick
- **Consult? (yes/no):** apply the rules below
- **Trigger:** which rule made it consult-worthy (if yes)

### Consultation rules

A decision is **non-obvious (consult)** if *any* applies:

- Introduces a new external dependency
- Defines or changes a public API / module boundary / wire format
- Picks an algorithm or data structure where Big-O or memory differ between candidates
- Touches concurrency, shared state, or ordering guarantees
- Touches persistence: schema, migration, indexes, retention
- Names something on a public surface (hard to rename later)
- Affects >1 module or crosses a layer boundary
- **Reversibility:** if wrong, >1 hour to undo
- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs

A decision is **obvious (skip consult)** if:
- Following an existing convention in the same file/module
- Local variable naming, internal helper structure
- Mechanical refactor with no behavior change
- Bug fix with root cause already identified

## Phase 2.5 — User gate

Show `decisions.md` to the user. They are the gate:
- Can flip any decision's consult flag
- Can override your tentative call
- Can kill scope

**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.

Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.

## Phase 3 — Bundled cross-LLM consultation

Spawn **both** consultants in parallel in a single message:

- `Agent(subagent_type="gemini-consultant", ...)`
- `Agent(subagent_type="codex-consultant", ...)`

Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. They can see all decisions and flag interactions between them. Two calls total, regardless of feature size.

When both return:
1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
2. Synthesize. Make the final call yourself, citing which inputs you weighed.
3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.

Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."

Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.

Use `AskUserQuestion` for explicit approval on:
- Each major design decision
- Each proposed shortcut (default to robust if not approved)

Block until answered.

## Phase 6 — Write SPEC.md and PLAN.md

Create `z-harness/$Z_HARNESS_SLUG/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.

Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.

## Phase 7 — Bundled final review

Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
- codex-consultant: same.

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md

Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.

**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
- "Combine 2-3 tasks I'll suggest" (you propose candidate merges)
- "Ship as-is — this plan really is that big"
- "Restructure — let me redesign Phase 8"

Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.

**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
```
**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
```
The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.

**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.

## Phase 9 — Finalize archive

Copy `z-harness/$Z_HARNESS_SLUG/{SPEC,PLAN,TASKS}.md` into `z-harness/$Z_HARNESS_SLUG/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
```
Plan complete. <N> tasks queued.

Recommended:
  /compact          — free planning context before next phase
  /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
  /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
```

The `/compact` recommendation is important: the planning phase (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. Compacting at this boundary frees ~MB of main-thread context before implementation kicks off. Subagents during implementation are fresh-context already, so no per-batch compact is needed.

The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.

---

## Operating principles

- **Premise first.** Challenge the request before planning around it.
- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
- **Always ask** when unclear.
- **Shortcuts only with explicit approval.**
- **DRY / KISS / SOLID** are non-negotiable.
- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.
