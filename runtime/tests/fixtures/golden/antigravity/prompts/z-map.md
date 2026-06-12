---
description: "Maps terrain with citations + cross-LLM critique. No recommendations — terrain only. See `/z-research` for synthesis across map + brainstorm."
role: workflow
---

You are running the **z-harness `/z-map`** pipeline.

Question (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question
     "What question should I research?" to the user via their native channel and
     accept a text reply. Silent omission is forbidden. -->
**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.

Strict, multi-phase. Do not skip phases. `/z-map` produces a map note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

## Setup

1. **Parse `--slug=<value>` flag** from `$ARGUMENTS` first. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the research question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned research question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.

   If `--slug=` was explicitly provided, skip auto-derivation but still defer collision handling to Phase 0.5.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" map_run_start "$START_PAYLOAD"
   ```
6. **Parent attribution (sub-command contract).** If `$Z_HARNESS_PARENT_RUN_ID` is set in the environment (i.e. this sub-command is being dispatched by a meta-orchestrator like `/z-research`), include `parent_run_id` and `parent_command` fields in every subsequent `log-event.sh` payload. Example:

   ```bash
   bash log-event.sh "$RUN" some_event "$(python3 -c 'import json,os,sys; p=json.loads(sys.argv[1]);
   pid=os.environ.get("Z_HARNESS_PARENT_RUN_ID"); pcmd=os.environ.get("Z_HARNESS_PARENT_COMMAND");
   if pid: p["parent_run_id"]=pid;
   if pcmd: p["parent_command"]=pcmd;
   print(json.dumps(p))' "$ORIG_PAYLOAD")"
   ```

   If env vars absent → emit events as today (no attribution fields). Backward compatible.
7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.

**Setup does NOT mutate `$Z_HARNESS_PLAN_DIR/MAP.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/MAP.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check before the Phase 0 cost gate when the request is clearly not mapping. After Phase 6 finalization, route language may appear only as a next-step handoff outside `MAP.md`; never put approach recommendations in the map note.

Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `has_fix_artifact`, and `docs_stale_or_drifted`. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters this command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- Stay in `/z-map` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
- Route clearly framed planning work with enough terrain to `/z-plan`.
- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 0 — Cost-confirmation gate

Research can be expensive. The default fan-out is up to 3 parallel `Explore` subagents (Haiku) plus a bundled cross-LLM critique pass. Target spend: **≤2M tokens / 5-10 min wall time.** If you exceed 2M tokens at any point, log a `cost_warning` event and surface it to the user.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the cost-gate
     question (Proceed/Reduce/Abandon) via their native channel and accept a
     reply before any subagent dispatch. Silent omission is forbidden. -->
Present the cost up front via `AskUserQuestion` with three options:

- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores.
- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
- **Abandon** — exit cleanly, write nothing.

Log the user's pick:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
```

If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.

Checkpoint: `phase0-cost-gate.md`.

## Phase 0.5 — Slug + artifact collision handling

This phase runs **only if** the user picked `proceed` or `reduce` in Phase 0. The `abandon` path must never reach this phase, so the existing workspace stays untouched.

1. **Slug-dir collision (deferred from Setup step 1).** If the chosen slug (auto-derived or `--slug=`) matches an existing `$Z_HARNESS_PLAN_DIR/` dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `MAP.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-collision
        confirmation question via their native channel. Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious (and `--slug=` was not provided), confirm with the user via `AskUserQuestion`.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the existing-MAP.md
     collision decision (archive-and-start-fresh/continue/abort) via their native
     channel and accept a reply. Silent omission is forbidden. -->
2. **Existing-MAP.md handling (deferred from old Setup step 7).** If `$Z_HARNESS_PLAN_DIR/MAP.md` exists, prompt the user via `AskUserQuestion` with three options:
   - **archive-and-start-fresh** — archive the existing note (`mv $Z_HARNESS_PLAN_DIR/MAP.md $Z_HARNESS_PLAN_DIR/archive/$RUN/MAP.previous.md`) and proceed with a clean draft.
   - **continue (re-use existing)** — leave the existing MAP.md in place and treat this run as a refinement; the existing note's findings become inputs to Phase 3.
   - **abort** — exit cleanly. **Do NOT touch the existing MAP.md or any sibling file.** Log a `phase0_5_abort` event and return.

   Log the user's pick:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
     "$(printf '{"choice":"%s"}' "<archive-and-start-fresh|continue|abort>")"
   ```

Checkpoint: `phase0_5-collision.md`.

## Phase 1 — Scaffolding

**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     will be skipped and Phase 2 Explores will proceed without doc grounding. -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 2.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.

Checkpoint: `phase1-scaffolding.md`.

## Phase 2 — Parallel Explores

Dispatch up to `EXPLORE_BUDGET` parallel `Explore` subagents (Haiku) on **distinct facets** of the question. Each Explore must answer a targeted sub-question; do not dispatch overlapping queries.

**Hard cap: 3.** No env override in v1. If `EXPLORE_BUDGET=1` from Phase 0, dispatch a single Explore covering the most important facet.

Send all calls in **one message** so they run in parallel:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     proceed without subagent support — terrain mapping requires Explore calls. -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="Explore",
  model: "haiku",
  description="Facet A: <short label>",
  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="Explore",
  model: "haiku",
  description="Facet B: <short label>",
  prompt="<TARGETED sub-question>\n\n..."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="Explore",
  model: "haiku",
  description="Facet C: <short label>",
  prompt="<TARGETED sub-question>\n\n..."
)
```

**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.

**Track three counts separately:**

- `EXPLORE_BUDGET` — the planned cap from Phase 0 (1 or 3).
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
- `EXPLORES_SUCCEEDED` — the number of those calls that returned a usable result (no error, non-empty findings). Failed, malformed, or empty returns do NOT count.

For every Explore that fails or returns malformed output, log it and surface the failure as an **Open question** in Phase 3:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
  "$(printf '{"facet":"%s","reason":"%s"}' "<facet-label>" "<short reason>")"
```

The final frontmatter uses **`EXPLORES_SUCCEEDED`** for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` frontmatter field. Do not fabricate `explore_calls` from `EXPLORE_BUDGET`.

Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).

## Phase 3 — Draft research note

Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` with **these mandatory sections, in this exact order**:

```markdown
## Findings
- <claim> (path/to/file.rs:42)
- <claim> (path/to/other.py:117-130)

## Constraints discovered
- <constraint with citation>

## Open questions
- <question the Explores could not resolve>

## No-recommendation
This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
```

**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.

**Demotion rule.** Findings without a `file:line` citation are demoted to **Open questions** — do not silently drop them, and do not add a fake citation.

**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
  '{"location":"<section>","removed_text":"<short excerpt>"}'
```

Checkpoint: `research-draft.md` (this file).

## Phase 4 — Bundled cross-LLM critique

Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     and consultant-secondary calls require subagent support. -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Research review (Gemini) for <slug>",
  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Research review (Codex) for <slug>",
  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
)
```

Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).

**Per-consultant failure policy.** A consultant return is "failed" if it errors, returns empty, or returns a payload that does not contain at least one of `Gaps` / `Errors` / `Missing constraints` sections (malformed). For each consultant independently:

1. **Retry once.** Re-dispatch the same consultant with the identical prompt. Log a `consultant_retry` event with `{"consultant":"<gemini|codex>","reason":"<error|empty|malformed>"}`.
2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.

**Aggregate decision** (after both consultants resolve):

- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the critique-failure
     decision (proceed-with-no-critique/retry-both/abandon) via their native channel
     and accept a reply. Silent omission is forbidden. -->
- **Both consultants failed (after retry)** → DO NOT mark `status: complete`. Prompt the user via `AskUserQuestion` with three options:
  - **proceed-with-no-critique** — finalize with `status: complete_no_critique` and an explicit `## Cross-LLM review notes` entry stating both consultants failed.
  - **retry-both** — dispatch Phase 4 from scratch once more.
  - **abandon** — write nothing further; log `research_run_end` with `status: abandoned_critique_failure` and exit.

Log the aggregate decision:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" critique_failure_decision \
  "$(printf '{"choice":"%s"}' "<proceed-with-no-critique|retry-both|abandon>")"
```

Checkpoint: `phase4-critiques.md` (both critiques side-by-side, with `<consultant>:failed` markers where applicable).

## Phase 5 — Revise

For each consultant gap / error / missing-constraint:

- **Fill it** if the orchestrator can resolve it from existing Explore returns or via a quick targeted Read.
- **Note it as unfilled** in the `## Cross-LLM review notes` section if it would require another Explore dispatch (out of scope at this phase).

Update the draft accordingly. If a consultant tried to recommend an approach despite the MODE prohibition, **strip the recommendation** and log `research_temptation` for the consultant turn.

Add a `## Cross-LLM review notes` section to the draft summarizing:
- Gemini's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
- Codex's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.

Re-run the demotion rule from Phase 3: any new findings introduced during revision must carry a `file:line` citation or be demoted.

Checkpoint: `research-draft.revised.md`.

## Phase 6 — Finalize

Compute `input_hash` per the SPEC algorithm:

```
input_hash = sha256(canonicalize(
    question + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_empty
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.

Write final `$Z_HARNESS_PLAN_DIR/MAP.md`:

```markdown
---
artifact: map
slug: <slug>
generated_at: <ISO-8601 UTC>
command: /z-map "<verbatim cleaned research question>" [--slug=<value>]
input_hash: <16 hex chars>
depends_on: []
explore_calls: <EXPLORES_SUCCEEDED, 0..3>
# explore_failures only emitted if (EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED) > 0:
explore_failures: <N>
status: <complete | complete_no_critique>
---

# Map: <question>

## Findings
<bulleted list with file:line citations>

## Constraints discovered
<bulleted list>

## Open questions
<bulleted list>

## No-recommendation
This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.

## Cross-LLM review notes
<consultant feedback summary; filled vs unfilled gaps>
```

**`command:` frontmatter rule.** Store the exact normalized invocation, including the verbatim cleaned research question (double-quoted) and any supported flags such as `--slug=<value>`. Example: `command: /z-map "What's the right schema for X?" --slug=foo-bar`. The bare `command: /z-map` form is **forbidden** — reproducibility requires the question be recoverable from the frontmatter alone.

**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.

Log run end:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" map_run_end \
  "$(printf '{"slug":"%s","explore_calls":%d,"explore_failures":%d,"status":"%s"}' \
     "$Z_HARNESS_SLUG" "$EXPLORES_SUCCEEDED" "$((EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED))" "<complete|complete_no_critique>")"
```

Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:

```
Map complete. MAP.md written to $Z_HARNESS_PLAN_DIR/MAP.md.

Recommended next step:
  /z-brainstorm <topic>  — ideate approaches grounded in this map, OR
  /z-research <topic>    — synthesize map + brainstorm into approach decision matrix, OR
  /z-plan <task>         — go straight to planning if the approach is already clear
```

---

## Operating principles

- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant. Every temptation to recommend gets logged and removed.
- **Citations are non-negotiable.** No `file:line` → not a finding.
- **Cost discipline.** Phase 0 is the user's gate; respect their pick. If you exceed 2M tokens, warn.
- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
