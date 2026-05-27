---
description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
argument-hint: <topic to brainstorm> [--slug=<kebab>]
---

You are running the **z-harness `/z-brainstorm`** pipeline.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.

`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.

## Setup

1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — archive existing `BRAINSTORM.md` to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
   - **abort** — exit cleanly with no changes
6. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
   ```
7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.

**All paths live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
- `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`

## Phase 0 — Scope probe

Run Phase 0 **immediately after Setup** — BEFORE Plan Route Check, BEFORE Phase 1 scaffolding begins. scope-probe internally dispatches doc-fetcher (per its step 4); Phase 0 does not depend on Phase 1's doc-fetcher run.

### 0a. Define axis taxonomy

```
AXIS_TAXONOMY=["per_vendor","per_framing"]
```

This is the fixed brainstorm axis taxonomy for v1a. Pass it verbatim to scope-probe.

### 0b. Dispatch scope-probe

```
T0_PHASE0=$(date +%s%3N)
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_start \
  '{"host_command":"z-brainstorm","axis_taxonomy":["per_vendor","per_framing"]}'

Agent(
  subagent_type="scope-probe",
  description="Scope probe for z-brainstorm: <slug>",
  prompt="host_command: z-brainstorm
topic: <topic verbatim>
axis_taxonomy: [\"per_vendor\",\"per_framing\"]
repo_root: <abs path to repo root>
run_id: <RUN>"
)
```

### 0c. Parse scope-probe return

Parse the hybrid return using the two-step parser (line-prefix headers BEFORE the first ` ```json ` fence, JSON block via fence regex `^```json\n(.*?)^```$`). Extract:

- `STATUS` (classified | refused | bad_input)
- `MODE` (LIGHT | MEDIUM | HEAVY)
- `AXIS` (one of `per_vendor`, `per_framing`, or `none`)
- `CONFIDENCE` (high | medium | low)
- `REASON_CODES` (comma-separated string)
- `chunks` array from the fenced JSON block
- `seams_counted` and `candidates_walked` integers from the fenced JSON block

**Parser failure handling:** If the response is missing line-prefix headers, has no fenced JSON block, has malformed JSON, or has line-prefix headers inside the fence, emit `scope_probe_malformed` event with `{"host_command":"z-brainstorm","raw_response_len":<len>}`, treat as `STATUS: refused` + `MODE: MEDIUM`, and continue. Never retry.

**Low-confidence handling:** If `CONFIDENCE: low`, log a warning event (`scope_probe_low_confidence`), downgrade the result to `MODE: MEDIUM`, and continue. Do not AskUser in v1a.

### 0d. Write SCOPE artifacts (archive-first)

**Step 1 — Write archive copy first (must succeed):**

Assemble the SCOPE JSON from the parsed scope-probe return plus run-context metadata:

```json
{
  "host_command": "z-brainstorm",
  "slug": "<Z_HARNESS_SLUG>",
  "last_run_id": "<RUN>",
  "last_updated": "<UTC ISO 8601 timestamp>",
  "mode": "<MODE>",
  "axis": "<AXIS>",
  "confidence": "<CONFIDENCE>",
  "reason_codes": ["<code1>", "<code2>"],
  "chunks": [ ... ],
  "seams_counted": <int>,
  "candidates_walked": <int>,
  "scope_probe_version": "1"
}
```

Write atomically via tmp+rename to `$Z_HARNESS_PLAN_DIR/archive/$RUN/SCOPE.json`.

If the archive write fails: emit `scope_probe_archive_write_failed` event, skip Phase 0 entirely, and proceed to Plan Route Check as if scope-probe was never dispatched. Do not write the live file.

**Step 2 — Write live file (only after archive succeeds):**

Write the same JSON to `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json` atomically (tmp+rename). The live file is namespaced per host command; it is overwritten on each run.

### 0e. Log classification result

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  "$(printf '{"host_command":"z-brainstorm","mode":"%s","axis":"%s","confidence":"%s","chunks_count":%d}' \
     "<MODE>" "<AXIS>" "<CONFIDENCE>" "<N chunks>")"
```

### 0f. Branch on STATUS, then MODE

**Branch on STATUS first:**

#### refused — MEDIUM fallback

If `STATUS: refused`: log a `scope_probe_refused` event, treat as `MODE: MEDIUM`, and proceed to Plan Route Check and then Phase 1 unchanged.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_refused \
  '{"host_command":"z-brainstorm"}'
```

#### bad_input — MEDIUM fallback

If `STATUS: bad_input`: log a `scope_probe_bad_input` event, treat as `MODE: MEDIUM`, and proceed to Plan Route Check and then Phase 1 unchanged.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_bad_input \
  '{"host_command":"z-brainstorm"}'
```

**Only if `STATUS: classified`, branch on MODE:**

#### LIGHT or MEDIUM — pass-through

`MODE: LIGHT` or `MODE: MEDIUM`: proceed to Plan Route Check and then Phase 1 scaffolding unchanged. SCOPE-brainstorm.json is written but Phase 1 does not consult it for brainstorm (unlike `/z-audit` LIGHT, brainstorm has no `dimensions_hint` equivalent — Phase 1 runs identically for both modes in `/z-brainstorm`).

#### HEAVY — parallel sub-flow fan-out

When `MODE: HEAVY`:

1. **Log fan-out start:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_dispatched \
     "$(printf '{"host_command":"z-brainstorm","axis":"%s","chunks_count":%d}' "<AXIS>" "<N>")"
   ```

2. **Dispatch N parallel `/z-brainstorm` sub-flows** — one per chunk from the `chunks` array. Each sub-flow runs Phases 1 (scaffolding), 2 (ideator dispatch), and **3 (synthesis)** for its chunk's `scope_hint` sub-topic, producing its own per-chunk BRAINSTORM.md. Dispatch all N in a single message (parallel).

   For each chunk `C` in `chunks`, call:
   ```
   Agent(
     subagent_type="general-purpose",
     model="sonnet",
     description="z-brainstorm sub-flow for chunk <C.id>: <C.intent>",
     prompt="MODE: brainstorm-subflow

This is a HEAVY fan-out sub-flow of /z-brainstorm. Run Phase 1 (scaffolding), Phase 2 (ideator dispatch), and Phase 3 (synthesis) for the sub-scope below. Do NOT run Phase 0 (scope-probe), Plan Route Check, or Phase 4 (user-pick gate — selection happens at the parent level for HEAVY mode). Produce the per-chunk BRAINSTORM.md content; the parent orchestrator writes the file to the path below (you have no Write tool; return the full markdown in your response).

Z_HARNESS_PARENT_RUN_ID: <interpolate $RUN value here, e.g. 20260101T000000Z-my-slug>
Parent slug: <interpolate $Z_HARNESS_SLUG value here>
Chunk id: <C.id>
Sub-scope topic: <C.scope_hint> — <C.intent>
Original topic (for context): <topic>
Axis: <AXIS>
Output path: <interpolate $Z_HARNESS_PLAN_DIR>/archive/<interpolate $RUN>/chunks/<C.id>/BRAINSTORM.md

Scaffolding instructions: follow /z-brainstorm Phase 1 (doc-fetcher, optional Explore, RESEARCH.md ingestion, input_hash). Ideator dispatch: follow /z-brainstorm Phase 2 with the IDEATOR_SCHEMA. Synthesis: follow /z-brainstorm Phase 3 (anti-bias check, orchestrator recommendation). Return the full per-chunk BRAINSTORM.md content (frontmatter + body) with chosen_framing: pending in your response; the parent orchestrator writes the file. Do NOT present an AskUserQuestion — the parent owns the user-pick gate."
   )
   ```

   Sub-flows MUST NOT themselves go HEAVY (anti-sprawl invariant: sub-flows skip Phase 0 entirely).

3. **Collect sub-flow results and write per-chunk files.** Each sub-flow returns BRAINSTORM.md content as its response text (sub-agents have no Write tool — the orchestrator owns the write). For each chunk, write the returned text to `$Z_HARNESS_PLAN_DIR/archive/$RUN/chunks/<C.id>/BRAINSTORM.md` (atomic tmp+rename; create the parent dir first). Record:
   - `brainstorm_path`: `$Z_HARNESS_PLAN_DIR/archive/$RUN/chunks/<C.id>/BRAINSTORM.md`
   - `status`: succeeded (write completed, content is non-empty + has valid frontmatter) or failed (sub-flow errored or returned empty/malformed content)

4. **Dispatch scope-reconciler-brainstorm** to merge the per-chunk BRAINSTORM.md files. The reconciler is **read-only** — it returns merged BRAINSTORM.md text as its output; the orchestrator (/z-brainstorm) writes the file. Do NOT include `output_path` in the reconciler prompt.
   ```
   Agent(
     subagent_type="scope-reconciler-brainstorm",
     description="Reconcile HEAVY brainstorm chunks for <slug>",
     prompt="host_run_id: <interpolate $RUN value here>
chunks: <JSON array of {id, brainstorm_path, status?} — mark failed sub-flows with status: failed>
axis: <AXIS>"
   )
   ```

5. **Write unified BRAINSTORM.md.** Parse the text returned by scope-reconciler-brainstorm and write it to `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` (the orchestrator performs this write, not the reconciler).

   If reconciler fails or returns no parseable content: fall back to concatenating the per-chunk BRAINSTORM.md files under a `## Reconciliation failed — raw chunks below` header, and write that to `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`.

6. **Log reconciliation:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
     "$(printf '{"host_command":"z-brainstorm","axis":"%s","chunks_total":%d,"chunks_succeeded":%d,"reconciler_ok":%s}' \
        "<AXIS>" "<N>" "<succeeded_count>" "<true|false>")"
   ```

7. **Skip Phases 1, 2, and 3.** The unified BRAINSTORM.md (produced by the reconciler or the fallback) replaces the normal Phase 1+2+3 output. Jump directly to Phase 4 — **the HEAVY branch at the top of Phase 4 owns the chunk-selection matrix logic** (see Phase 4 HEAVY-mode branch above).

---

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.

Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
- Route a framing that is already clear and ready for task planning to `/z-plan`.
- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Scaffolding

Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:

### 1a. Doc-fetcher (if INDEX.json exists)

If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.

### 1b. Optional Explore

If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:

```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Brainstorm scaffolding for <slug>",
  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
)
```

If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.

### 1c. RESEARCH.md ingestion

If `$Z_HARNESS_PLAN_DIR/RESEARCH.md` exists, read it.

- **≤20 KB:** inline the full content into the scaffolding payload.
- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.

Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.

### 1d. Assemble and hash

Compute the `input_hash` per SPEC:

```
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_summary_or_empty
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.

Checkpoint: write the assembled scaffolding to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-scaffolding.md`.

---

## Phase 2 — Parallel ideator dispatch

Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.

Define a shared instruction block `IDEATOR_SCHEMA` (used verbatim in all three prompts):

```
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
```

Then dispatch:

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Claude ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-secondary",
  description="Codex ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-primary",
  description="Gemini ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
```

All three ideators see byte-identical scaffolding AND byte-identical schema instructions. The consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.

### Ideator failure policy

Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.

- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<id>:failed"` in the `ideators` frontmatter list using the canonical id (`claude:failed` | `codex:failed` | `gemini:failed`). The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
- **2/3 fail** → halt. Use `AskUserQuestion` with options:
  - **retry** (default) — re-dispatch the failed ideators once
  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
  - **abandon** — write a minimal abandoned BRAINSTORM.md (frontmatter: `artifact`, `slug`, `generated_at`, `command`, `input_hash`, `ideators` with `:failed` suffix on the failed members, `ideator_models`, `status: abandoned`, `chosen_framing: abandoned`; body: a single `## Abandoned` section with one sentence of context) so `/z-plan` can detect the prior attempt, then exit.
- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.

Log every individual failure as `ideator_failed` regardless of the bucket above.

---

## Phase 3 — Synthesis + mandatory anti-bias check

1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.

2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.

3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.

4. **Write `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`** with YAML frontmatter:

   ```yaml
   ---
   artifact: brainstorm
   slug: <slug>
   generated_at: <UTC ISO 8601>
   command: /z-brainstorm <args>
   input_hash: <16 hex from Phase 1d>
   depends_on: [<RESEARCH.md if ingested>]
   ideators:
     - claude
     - codex
     - gemini
     # failed members recorded as "<id>:failed" (e.g. claude:failed)
   ideator_models:
     claude: sonnet
     codex: default
     gemini: default
   status: complete
   chosen_framing: pending
   ---
   ```

   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.

   Body sections, one block per ideator (in fixed order Claude → Codex → Gemini):

   ```markdown
   ## Framing: <ideator-name>

   ### Framing
   <one paragraph or `<missing>`>

   ### Core hypothesis
   <one paragraph or `<missing>`>

   ### Risks
   <bulleted list or `<missing>`>

   ### Plan implications
   <bulleted list or `<missing>`>

   ### What would change my mind
   <bulleted list or `<missing>`>
   ```

   Followed by:

   ```markdown
   ## Anti-bias check
   <section-by-section comparison with explicit justification for any Claude-favoring pick>

   ## Orchestrator recommendation
   <one-line rationale; user is free to override>
   ```

   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).

5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
   - One option per available framing (e.g. **Claude framing**, **Codex framing**, **Gemini framing** — only for ideators that succeeded)
   - **Restart** — discard this run and re-run with a refined topic
   - **Abandon** — exit cleanly without finalizing

Block until the user answers. Send a `PushNotification` if notify.level is `approval_only` or `all` (see [docs/human/config.md](docs/human/config.md)).

---

## Phase 4 — Finalize

### HEAVY-mode branch (check FIRST — fires only when mode == HEAVY)

Read `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json`. If the file exists and `mode` is `"HEAVY"`, execute this branch and **skip the LIGHT/MEDIUM branch below entirely**.

#### Step 4H-1 — Build the (chunk × framing) matrix

Parse the unified BRAINSTORM.md that was written at the end of Phase 0's HEAVY fan-out (step 6 of the 0f HEAVY sub-section). The reconciler produces a strict chunk-major structure: each successful chunk is rendered under `## Chunk: <id>` heading (e.g. `## Chunk: C1`) and inside that section the per-ideator framings appear under `## Framing: <ideator>` sub-headings (e.g. `## Framing: claude`, `## Framing: codex`, `## Framing: gemini`) — same `## Framing:` pattern used by single-run BRAINSTORM.md per `/z-brainstorm` Phase 3. A chunk's framing scope ends at the next `## Chunk:` heading or EOF. Walk each `## Chunk: <id>` section in order. Skip chunks whose heading contains `— FAILED`. For each successful chunk, enumerate every `## Framing: <ideator>` sub-section actually present (skip any sub-section marked `<missing>` per ideator-failure convention). If a chunk has zero parseable `## Framing:` sub-sections, halt with `AskUserQuestion` ("reconciler emitted no framings for chunk <id> — repair manually / abandon / restart").

Collect a flat list of pairs in the form `(chunk_id, framing)`, e.g.:
```
[("C1","claude"), ("C1","codex"), ("C1","gemini"), ("C2","claude"), ("C2","codex"), ("C2","gemini"), ...]
```

Let `N_PAIRS = len(pairs)`.

#### Step 4H-2 — Present the selection matrix to the user

**Case A — N_PAIRS ≤ 12 (single AskUserQuestion):**

Present a single `AskUserQuestion` listing all pairs as labeled options plus two standard exits:

```
Which (chunk, framing) should seed the downstream /z-plan?

Options:
  C1: claude   — <one-line summary of C1's Claude framing from BRAINSTORM.md>
  C1: codex    — <one-line summary of C1's Codex framing>
  C1: gemini   — <one-line summary of C1's Gemini framing>
  C2: claude   — <one-line summary of C2's Claude framing>
  ...           (up to 12 options)
  Restart       — discard this run and re-run with a refined topic
  Abandon       — exit cleanly without finalizing
```

The one-line summary is the first sentence of that ideator's "Framing" section in the unified BRAINSTORM.md. If that section is missing, use `<no summary available>`.

**Case B — N_PAIRS > 12 (two-step AskUserQuestion):**

First, present a question to pick the chunk:

```
This run produced <N_PAIRS> (chunk × framing) pairs (>{12}). Pick a chunk first.

Options:
  C1  — <one-line description of C1's sub-scope from unified BRAINSTORM.md>
  C2  — <one-line description>
  ...
  Restart
  Abandon
```

After the user picks a chunk (or Restart/Abandon), if they picked a chunk then present a second question to pick the framing within that chunk:

```
Chunk <id> selected. Which framing seeds the plan?

Options:
  claude   — <one-line summary of this chunk's Claude framing>
  codex    — <one-line summary of this chunk's Codex framing>
  gemini   — <one-line summary of this chunk's Gemini framing>
  Back     — go back to chunk selection
  Abandon  — exit cleanly without finalizing
```

If the user picks **Back**, loop to the chunk-selection question. Allow at most 3 Back-loops; on the fourth Back, treat it as Abandon.

#### Step 4H-3 — Handle user's pick

**User picked a (chunk, framing) pair:**

1. Update the BRAINSTORM.md frontmatter atomically (tmp-file-then-rename). Build the full new frontmatter in memory, then write to a temp file in the same directory, then `os.replace()` over the original — never leave the file in an intermediate state where both `chosen_framing` and `chosen_pair` are present or where neither is present:
   - Remove the `chosen_framing:` field entirely.
   - Add `chosen_pair: {chunk_id: "<id>", framing: "<claude|codex|gemini>"}` (e.g. `chosen_pair: {chunk_id: "C1", framing: "codex"}`).
   - Confirm `status: complete`.
2. Append (for the first time) a `## User choice` body section:
   ```markdown
   ## User choice

   **Chosen pair:** chunk `<id>` / framing `<framing>`

   The framing text below seeds any downstream `/z-plan` invocation. Run `/z-plan` in the same working directory and it will auto-detect BRAINSTORM.md and read `chosen_pair` from the frontmatter.

   <verbatim text of the picked chunk's picked ideator framing block, copied from the `## Chunk: <id>` section of the unified BRAINSTORM.md>
   ```
3. Log the pick:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" heavy_pair_selected \
     "$(printf '{"chunk_id":"%s","framing":"%s"}' "<id>" "<framing>")"
   ```

**User picked Restart:**

Follow the standard Restart path (see LIGHT/MEDIUM branch below) — archive BRAINSTORM.md with `chosen_framing: restart`, ask for a refined topic, start a fresh RUN.

**User picked Abandon:**

Follow the standard Abandon path below. For HEAVY abandons, the frontmatter MUST match LIGHT/MEDIUM abandon shape exactly: set `status: abandoned` and `chosen_framing: abandoned`. Do NOT emit a `chosen_pair` key (it is only present on successful HEAVY completion). This keeps abandon detection uniform across modes.

#### Step 4H-4 — Fall through to "In all branches" below

After completing step 4H-3, skip the LIGHT/MEDIUM branch entirely and jump to "In all branches" at the end of this section. The `brainstorm_run_end` log event and push-notify are shared with the LIGHT/MEDIUM path.

For the `brainstorm_run_end` event, serialize `chosen_framing` as `"<chunk_id>:<framing>"` (e.g. `"C1:codex"`) for HEAVY picks, or `"restart"` / `"abandoned"` for those exits.

---

### LIGHT/MEDIUM branch (fires when mode is NOT HEAVY, or SCOPE-brainstorm.json is absent)

Branch on the user's Phase 3 choice:

#### User picked a framing

1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter from `pending` to the picked ideator id (`claude` | `codex` | `gemini`).
2. Append (for the first time) a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
3. Confirm `status: complete` in the frontmatter.

#### User picked Restart

1. Archive the just-written BRAINSTORM.md to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer). Before archiving, update the archived copy's frontmatter to `status: complete`, `chosen_framing: restart` so the historical record is spec-valid.
2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.

#### User picked Abandon

1. Set the frontmatter `status: abandoned` and `chosen_framing: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.

---

### In all branches

Log `brainstorm_run_end`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
     "<complete|abandoned>" "<framing-or-empty>" "<N>")"
```

Push-notify (if policy ≠ `off`) with a next-step recommendation:

```
Brainstorm complete (framing: <chosen>).

Recommended next:
  /z-research <question>  — (optional) map terrain before planning
  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
```

For HEAVY runs, the push notification uses the chosen pair: `Brainstorm complete (pair: C1:codex).`

For the abandoned branch, the push notification just says "Brainstorm abandoned" with no next-step.

---

## Operating principles

- **Cheap and parallel.** Three ideators in one message, no per-ideator round-trips.
- **Identical scaffolding for all three.** No read-by-reference asymmetry.
- **Anti-bias is mandatory.** Every Claude-favoring pick needs explicit justification.
- **Failures degrade gracefully** — 1/3 proceeds, 2/3 asks, 3/3 halts.
- **Restart is cheap.** Archive and loop, don't try to patch.
- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
- **Log everything** via `scripts/log-event.sh`.
