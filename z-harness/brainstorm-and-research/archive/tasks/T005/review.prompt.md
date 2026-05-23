You are reviewing code that Claude just wrote for task T005: Update /z-plan + skill mirror for precontext detection.

Spec (excerpt):

## /z-plan integration (T005)

### Setup step 10 (precontext detection)

- Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
- **Freshness check (RESEARCH.md only):**
  - Citation regex: `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`
  - Extensionless allowlist scan: Makefile, Dockerfile.
  - Markdown link form `[label](path:line)` parsed by extracting inner path.
  - For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges use min-line mtime (any modification within range → stale).
  - Deleted-source detection → emit `precontext_source_deleted` event (higher severity than stale-mtime).
  - Parse failure → emit `precontext_freshness_check_failed`, continue (fail-open).
  - If any stale → `AskUserQuestion` warn the user before proceeding.
- **Conflict check:** if both BRAINSTORM and RESEARCH exist, surface any obvious contradictions to the user.
- **Unfinalized brainstorm** (`status: complete` missing or `chosen_framing` absent): recommend `/z-brainstorm` re-run before proceeding.

### Setup step 1 (slug collision handling)
- Precontext-only dir → continuation, no prompt.
- Finished-plan dir → collision, prompt.

### Phase 0: inject BRAINSTORM/RESEARCH if detected.

### Phase 1 boundary tightening
- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
- Skip Explore iff RESEARCH.md non-stale AND Open questions empty.

### Phase 6: Add `## Planning Inputs` section listing precontext artifacts OR "none — fresh /z-plan run."

Acceptance criteria:
1. Setup step 10 present in BOTH commands/z-plan.md AND skills/z-plan/SKILL.md, specifying: precontext detection; citation regex; extensionless allowlist; conflict surfacing; deleted-source detection.
2. Phase 0 prose: "If BRAINSTORM.md or RESEARCH.md were detected in Setup step 10, inject their content here..." present in both.
3. Phase 1 boundary tightening present.
4. Phase 6 SPEC.md template includes `## Planning Inputs` section.
5. Setup step 1 slug collision distinguishes precontext-only vs finished-plan.
6. Diff between the two files: only frontmatter/blank-line diffs (zero diff acceptable).

Note: `diff commands/z-plan.md skills/z-plan/SKILL.md` returns IDENTICAL. Both files are byte-for-byte the same.

Diff (primary artifact):

diff --git a/commands/z-plan.md b/commands/z-plan.md
new file mode 100644
index 0000000..e5e28de
--- /dev/null
+++ b/commands/z-plan.md
@@ -0,0 +1,305 @@
+---
+description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
+argument-hint: <feature or task description>
+---
+
+You are running the **z-harness `/z-plan`** pipeline.
+
+Task (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
+
+Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.
+
+## Setup
+
+1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
+2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents — this is what namespaces every output path.
+3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
+4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
+5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
+   ```
+   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
+   ```
+   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+   ```
+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+10. **Pre-plan artifact detection.** Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
+    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
+
+**All paths in subsequent phases live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/SPEC.md`
+- `z-harness/<slug>/PLAN.md`
+- `z-harness/<slug>/TASKS.md`
+- `z-harness/<slug>/archive/<run-id>/...`
+
+Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.
+
+Each phase below ends with a checkpoint — write the phase's output to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/<phase>.md` so the run is resumable.
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
+
+---
+
+## Phase 0 — Premise check
+
+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
+
+Before any planning, ask:
+
+- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
+- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
+- Is there a materially better path the user hasn't considered?
+
+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
+
+If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.
+
+Checkpoint: `phase0-premise.md`.
+
+## Phase 1 — Exploration
+
+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
+- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
+
+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
+
+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
+
+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
+
+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.
+
+If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
+  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
+```
+
+### 1b. Explore for gaps (Haiku by default)
+
+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
+
+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Find <thing> related to <slug>",
+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
+)
+```
+
+**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
+
+**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.
+
+Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.
+
+## Phase 2 — Decisions document
+
+Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/decisions.md`. For each decision:
+
+- **Decision:** what's being decided
+- **Options:** ≥1 candidate, with one-line tradeoffs
+- **Tentative call:** your current pick
+- **Consult? (yes/no):** apply the rules below
+- **Trigger:** which rule made it consult-worthy (if yes)
+
+### Consultation rules
+
+A decision is **non-obvious (consult)** if *any* applies:
+
+- Introduces a new external dependency
+- Defines or changes a public API / module boundary / wire format
+- Picks an algorithm or data structure where Big-O or memory differ between candidates
+- Touches concurrency, shared state, or ordering guarantees
+- Touches persistence: schema, migration, indexes, retention
+- Names something on a public surface (hard to rename later)
+- Affects >1 module or crosses a layer boundary
+- **Reversibility:** if wrong, >1 hour to undo
+- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs
+
+A decision is **obvious (skip consult)** if:
+- Following an existing convention in the same file/module
+- Local variable naming, internal helper structure
+- Mechanical refactor with no behavior change
+- Bug fix with root cause already identified
+
+## Phase 2.5 — User gate
+
+Show `decisions.md` to the user. They are the gate:
+- Can flip any decision's consult flag
+- Can override your tentative call
+- Can kill scope
+
+**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.
+
+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
+
+## Phase 3 — Bundled cross-LLM consultation
+
+Spawn **both** consultants in parallel in a single message:
+
+- `Agent(subagent_type="gemini-consultant", ...)`
+- `Agent(subagent_type="codex-consultant", ...)`
+
+Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. They can see all decisions and flag interactions between them. Two calls total, regardless of feature size.
+
+When both return:
+1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
+2. Synthesize. Make the final call yourself, citing which inputs you weighed.
+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
+
+Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.
+
+## Phase 4 — Final clarifications
+
+If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.
+
+## Phase 5 — Present + approve
+
+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
+
+Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.
+
+Use `AskUserQuestion` for explicit approval on:
+- Each major design decision
+- Each proposed shortcut (default to robust if not approved)
+
+Block until answered.
+
+## Phase 6 — Write SPEC.md and PLAN.md
+
+Create `z-harness/$Z_HARNESS_SLUG/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.
+
+The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:
+
+```markdown
+## Planning Inputs
+
+| Artifact | Path | generated_at |
+|----------|------|--------------|
+| BRAINSTORM.md | z-harness/<slug>/BRAINSTORM.md | <iso timestamp or "n/a"> |
+| RESEARCH.md | z-harness/<slug>/RESEARCH.md | <iso timestamp or "n/a"> |
+```
+
+If neither artifact was present, write: `none — fresh /z-plan run.`
+
+Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.
+
+Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.
+
+## Phase 7 — Bundled final review
+
+Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
+- codex-consultant: same.
+
+Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.
+
+## Phase 8 — TASKS.md
+
+Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.
+
+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
+- "Combine 2-3 tasks I'll suggest" (you propose candidate merges)
+- "Ship as-is — this plan really is that big"
+- "Restructure — let me redesign Phase 8"
+
+Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.
+
+**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
+```
+**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
+```
+The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.
+
+**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.
+
+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
+  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
+```
+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
+
+## Phase 9 — Finalize archive
+
+Copy `z-harness/$Z_HARNESS_SLUG/{SPEC,PLAN,TASKS}.md` into `z-harness/$Z_HARNESS_SLUG/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
+
+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
+```
+Plan complete. <N> tasks queued.
+
+Recommended:
+  /compact          — free planning context before next phase
+  /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
+  /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
+```
+
+The `/compact` recommendation is important: the planning phase (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. Compacting at this boundary frees ~MB of main-thread context before implementation kicks off. Subagents during implementation are fresh-context already, so no per-batch compact is needed.
+
+The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.
+
+---
+
+## Operating principles
+
+- **Premise first.** Challenge the request before planning around it.
+- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
+- **Always ask** when unclear.
+- **Shortcuts only with explicit approval.**
+- **DRY / KISS / SOLID** are non-negotiable.
+- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.
diff --git a/skills/z-plan/SKILL.md b/skills/z-plan/SKILL.md
new file mode 100644
index 0000000..e5e28de
--- /dev/null
+++ b/skills/z-plan/SKILL.md
@@ -0,0 +1,305 @@
+---
+description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
+argument-hint: <feature or task description>
+---
+
+You are running the **z-harness `/z-plan`** pipeline.
+
+Task (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
+
+Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.
+
+## Setup
+
+1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
+2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents — this is what namespaces every output path.
+3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
+4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
+5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
+   ```
+   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
+   ```
+   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+   ```
+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+10. **Pre-plan artifact detection.** Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
+    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
+
+**All paths in subsequent phases live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/SPEC.md`
+- `z-harness/<slug>/PLAN.md`
+- `z-harness/<slug>/TASKS.md`
+- `z-harness/<slug>/archive/<run-id>/...`
+
+Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.
+
+Each phase below ends with a checkpoint — write the phase's output to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/<phase>.md` so the run is resumable.
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
+
+---
+
+## Phase 0 — Premise check
+
+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
+
+Before any planning, ask:
+
+- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
+- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
+- Is there a materially better path the user hasn't considered?
+
+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
+
+If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.
+
+Checkpoint: `phase0-premise.md`.
+
+## Phase 1 — Exploration
+
+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
+- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
+
+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
+
+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
+
+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
+
+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.
+
+If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
+  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
+```
+
+### 1b. Explore for gaps (Haiku by default)
+
+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
+
+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Find <thing> related to <slug>",
+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
+)
+```
+
+**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
+
+**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.
+
+Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.
+
+## Phase 2 — Decisions document
+
+Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/decisions.md`. For each decision:
+
+- **Decision:** what's being decided
+- **Options:** ≥1 candidate, with one-line tradeoffs
+- **Tentative call:** your current pick
+- **Consult? (yes/no):** apply the rules below
+- **Trigger:** which rule made it consult-worthy (if yes)
+
+### Consultation rules
+
+A decision is **non-obvious (consult)** if *any* applies:
+
+- Introduces a new external dependency
+- Defines or changes a public API / module boundary / wire format
+- Picks an algorithm or data structure where Big-O or memory differ between candidates
+- Touches concurrency, shared state, or ordering guarantees
+- Touches persistence: schema, migration, indexes, retention
+- Names something on a public surface (hard to rename later)
+- Affects >1 module or crosses a layer boundary
+- **Reversibility:** if wrong, >1 hour to undo
+- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs
+
+A decision is **obvious (skip consult)** if:
+- Following an existing convention in the same file/module
+- Local variable naming, internal helper structure
+- Mechanical refactor with no behavior change
+- Bug fix with root cause already identified
+
+## Phase 2.5 — User gate
+
+Show `decisions.md` to the user. They are the gate:
+- Can flip any decision's consult flag
+- Can override your tentative call
+- Can kill scope
+
+**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.
+
+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
+
+## Phase 3 — Bundled cross-LLM consultation
+
+Spawn **both** consultants in parallel in a single message:
+
+- `Agent(subagent_type="gemini-consultant", ...)`
+- `Agent(subagent_type="codex-consultant", ...)`
+
+Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. They can see all decisions and flag interactions between them. Two calls total, regardless of feature size.
+
+When both return:
+1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
+2. Synthesize. Make the final call yourself, citing which inputs you weighed.
+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
+
+Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.
+
+## Phase 4 — Final clarifications
+
+If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.
+
+## Phase 5 — Present + approve
+
+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
+
+Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.
+
+Use `AskUserQuestion` for explicit approval on:
+- Each major design decision
+- Each proposed shortcut (default to robust if not approved)
+
+Block until answered.
+
+## Phase 6 — Write SPEC.md and PLAN.md
+
+Create `z-harness/$Z_HARNESS_SLUG/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.
+
+The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:
+
+```markdown
+## Planning Inputs
+
+| Artifact | Path | generated_at |
+|----------|------|--------------|
+| BRAINSTORM.md | z-harness/<slug>/BRAINSTORM.md | <iso timestamp or "n/a"> |
+| RESEARCH.md | z-harness/<slug>/RESEARCH.md | <iso timestamp or "n/a"> |
+```
+
+If neither artifact was present, write: `none — fresh /z-plan run.`
+
+Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.
+
+Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.
+
+## Phase 7 — Bundled final review
+
+Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
+- codex-consultant: same.
+
+Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.
+
+## Phase 8 — TASKS.md
+
+Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.
+
+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
+- "Combine 2-3 tasks I'll suggest" (you propose candidate merges)
+- "Ship as-is — this plan really is that big"
+- "Restructure — let me redesign Phase 8"
+
+Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.
+
+**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
+```
+**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
+```
+The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.
+
+**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.
+
+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
+  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
+```
+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
+
+## Phase 9 — Finalize archive
+
+Copy `z-harness/$Z_HARNESS_SLUG/{SPEC,PLAN,TASKS}.md` into `z-harness/$Z_HARNESS_SLUG/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
+
+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
+```
+Plan complete. <N> tasks queued.
+
+Recommended:
+  /compact          — free planning context before next phase
+  /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
+  /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
+```
+
+The `/compact` recommendation is important: the planning phase (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. Compacting at this boundary frees ~MB of main-thread context before implementation kicks off. Subagents during implementation are fresh-context already, so no per-batch compact is needed.
+
+The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.
+
+---
+
+## Operating principles
+
+- **Premise first.** Challenge the request before planning around it.
+- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
+- **Always ask** when unclear.
+- **Shortcuts only with explicit approval.**
+- **DRY / KISS / SOLID** are non-negotiable.
+- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
- If no blockers or majors, respond with exactly: `No blockers or majors found.`
