2026-05-27T19:41:44.143617Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T19:41:44.144308Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T19:41:44.144315Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T19:41:44.144316Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-suggest-memory/SKILL.md: invalid YAML: did not find expected key at line 3 column 35, while parsing a block mapping
2026-05-27T19:41:44.144318Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T19:41:44.144320Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T19:41:44.144323Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e6af5-08fe-77c1-82e5-8750fc4efd2d
--------
user
You are reviewing code that Claude just wrote for task T016: Add HEAVY-mode chunk-selection branch to /z-brainstorm Phase 4.

## Spec excerpt (from fanout-escalate-primitive SPEC.md)

**Phase 4 HEAVY-mode branch integration (v1a Task T016):**

Present the user with a `chunks × framings` matrix. User picks ONE `(chunk_id, framing)` pair (e.g. "C1: codex"). The picked pair becomes the seed for downstream `/z-plan`. 

- ≤12 pairs: single AskUserQuestion
- >12 pairs: 2-step (chunk selection, then framing selection within chunk)
- chosen_pair: {chunk_id, framing} replaces chosen_framing in BRAINSTORM.md frontmatter for HEAVY runs
- LIGHT/MEDIUM Phase 4 unchanged
- chosen_pair documented as seed for downstream /z-plan

**Related downstream:** scope-reconciler-brainstorm produces a unified BRAINSTORM.md with `## Chunk: <id>` headers and ideator framing sections (claude, codex, gemini) within each chunk section.

## Acceptance criteria
- New branch at top of Phase 4 fires ONLY when SCOPE-brainstorm.json mode == HEAVY
- Builds (chunk_id, framing) matrix from unified BRAINSTORM.md chunk-major sections
- ≤12 pairs: single AskUserQuestion; >12: 2-step chunk-then-framing
- chosen_pair: {chunk_id, framing} replaces chosen_framing in BRAINSTORM.md frontmatter for HEAVY runs
- LIGHT/MEDIUM Phase 4 unchanged
- chosen_pair documented as seed for downstream /z-plan

## Diff (primary artifact)

```diff
diff --git a/commands/z-brainstorm.md b/commands/z-brainstorm.md
index befed80..e2af05d 100644
--- a/commands/z-brainstorm.md
+++ b/commands/z-brainstorm.md
@@ -32,13 +32,192 @@ $ARGUMENTS
     ' "$VERSION_BLOB" "<arguments>")"
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
     ```
-7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
 8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.
 
 **All paths live under `$Z_HARNESS_PLAN_DIR/`:**
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+## Phase 0 — Scope probe
+
+Run Phase 0 **immediately after Setup** — BEFORE Plan Route Check, BEFORE Phase 1 scaffolding begins. scope-probe internally dispatches doc-fetcher (per its step 4); Phase 0 does not depend on Phase 1's doc-fetcher run.
+
+### 0a. Define axis taxonomy
+
+...
+[Phase 0 content: 0a through 0f describing scope-probe dispatch and HEAVY branching]
+...
+
 <!-- PLAN_ROUTE_CHECK_START -->
 ## Plan Route Check
 
@@ -59,6 +238,8 @@ If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `pl
 Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
 <!-- PLAN_ROUTE_CHECK_END -->
 
+---
+
 ## Phase telemetry (mandatory)
 
 @@ -261,31 +442,141 @@ Log every individual failure as `ideator_failed` regardless of the bucket above.
     - **Restart** — discard this run and re-run with a refined topic
     - **Abandon** — exit cleanly without finalizing
 
-Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
+Block until the user answers. Send a `PushNotification` if notify.level is `approval_only` or `all` (see [docs/human/config.md](docs/human/config.md)).
 
 ---
 
 ## Phase 4 — Finalize
 
+### HEAVY-mode branch (check FIRST — fires only when mode == HEAVY)
+
+Read `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json`. If the file exists and `mode` is `"HEAVY"`, execute this branch and **skip the LIGHT/MEDIUM branch below entirely**.
+
+#### Step 4H-1 — Build the (chunk × framing) matrix
+
+Parse the unified BRAINSTORM.md that was written at the end of Phase 0's HEAVY fan-out (step 6 of the 0f HEAVY sub-section). Walk each `## Chunk: <id>` section in order. For each chunk that succeeded (i.e. does NOT have `— FAILED` in the heading), enumerate the three standard framings: `claude`, `codex`, `gemini`. Only include framings for ideators that are present in that chunk's BRAINSTORM.md (skip any marked `:failed`).
+
+Collect a flat list of pairs in the form `(chunk_id, framing)`, e.g.:
+```
+[("C1","claude"), ("C1","codex"), ("C1","gemini"), ("C2","claude"), ("C2","codex"), ("C2","gemini"), ...]
+```
+
+Let `N_PAIRS = len(pairs)`.
+
+#### Step 4H-2 — Present the selection matrix to the user
+
+**Case A — N_PAIRS ≤ 12 (single AskUserQuestion):**
+
+Present a single `AskUserQuestion` listing all pairs as labeled options plus two standard exits:
+
+```
+Which (chunk, framing) should seed the downstream /z-plan?
+
+Options:
+  C1: claude   — <one-line summary of C1's Claude framing from BRAINSTORM.md>
+  C1: codex    — <one-line summary of C1's Codex framing>
+  C1: gemini   — <one-line summary of C1's Gemini framing>
+  C2: claude   — <one-line summary of C2's Claude framing>
+  ...           (up to 12 options)
+  Restart       — discard this run and re-run with a refined topic
+  Abandon       — exit cleanly without finalizing
+```
+
+The one-line summary is the first sentence of that ideator's "Framing" section in the unified BRAINSTORM.md. If that section is missing, use `<no summary available>`.
+
+**Case B — N_PAIRS > 12 (two-step AskUserQuestion):**
+
+First, present a question to pick the chunk:
+
+```
+This run produced <N_PAIRS> (chunk × framing) pairs (>{12}). Pick a chunk first.
+
+Options:
+  C1  — <one-line description of C1's sub-scope from unified BRAINSTORM.md>
+  C2  — <one-line description>
+  ...
+  Restart
+  Abandon
+```
+
+After the user picks a chunk (or Restart/Abandon), if they picked a chunk then present a second question to pick the framing within that chunk:
+
+```
+Chunk <id> selected. Which framing seeds the plan?
+
+Options:
+  claude   — <one-line summary of this chunk's Claude framing>
+  codex    — <one-line summary of this chunk's Codex framing>
+  gemini   — <one-line summary of this chunk's Gemini framing>
+  Back     — go back to chunk selection
+  Abandon  — exit cleanly without finalizing
+```
+
+If the user picks **Back**, loop to the chunk-selection question. Allow at most 3 Back-loops; on the fourth Back, treat it as Abandon.
+
+#### Step 4H-3 — Handle user's pick
+
+**User picked a (chunk, framing) pair:**
+
+1. Update the BRAINSTORM.md frontmatter:
+   - Remove the `chosen_framing:` field entirely.
+   - Add `chosen_pair: {chunk_id: "<id>", framing: "<claude|codex|gemini>"}` (e.g. `chosen_pair: {chunk_id: "C1", framing: "codex"}`).
+   - Confirm `status: complete`.
+2. Append (for the first time) a `## User choice` body section:
+   ```markdown
+   ## User choice
+
+   **Chosen pair:** chunk `<id>` / framing `<framing>`
+
+   The framing text below seeds any downstream `/z-plan` invocation. Run `/z-plan` in the same working directory and it will auto-detect BRAINSTORM.md and read `chosen_pair` from the frontmatter.
+
+   <verbatim text of the picked chunk's picked ideator framing block, copied from the `## Chunk: <id>` section of the unified BRAINSTORM.md>
+   ```
+3. Log the pick:
+   ```bash
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" heavy_pair_selected \
+     "$(printf '{"chunk_id":"%s","framing":"%s"}' "<id>" "<framing>")"
+   ```
+
+**User picked Restart:**
+
+Follow the standard Restart path (see LIGHT/MEDIUM branch below) — archive BRAINSTORM.md with `chosen_framing: restart`, ask for a refined topic, start a fresh RUN.
+
+**User picked Abandon:**
+
+Follow the standard Abandon path below — but set both `chosen_pair: null` and `chosen_framing: abandoned` in the frontmatter (omit `chosen_pair` from the output entirely; set `chosen_framing: abandoned`).
+
+#### Step 4H-4 — Fall through to "In all branches" below
+
+After completing step 4H-3, skip the LIGHT/MEDIUM branch entirely and jump to "In all branches" at the end of this section. The `brainstorm_run_end` log event and push-notify are shared with the LIGHT/MEDIUM path.
+
+For the `brainstorm_run_end` event, serialize `chosen_framing` as `"<chunk_id>:<framing>"` (e.g. `"C1:codex"`) for HEAVY picks, or `"restart"` / `"abandoned"` for those exits.
+
+---
+
+### LIGHT/MEDIUM branch (fires when mode is NOT HEAVY, or SCOPE-brainstorm.json is absent)
 
 Branch on the user's Phase 3 choice:
 
-### User picked a framing
+#### User picked a framing
 
 1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter from `pending` to the picked ideator id (`claude` | `codex` | `gemini`).
 2. Append (for the first time) a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
 3. Confirm `status: complete` in the frontmatter.
 
-### User picked Restart
+#### User picked Restart
 
 1. Archive the just-written BRAINSTORM.md to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer). Before archiving, update the archived copy's frontmatter to `status: complete`, `chosen_framing: restart` so the historical record is spec-valid.
 2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
 3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.
 
-### User picked Abandon
+#### User picked Abandon
 
 1. Set the frontmatter `status: abandoned` and `chosen_framing: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
 2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.
 
+---
+
 ### In all branches
 
 Log `brainstorm_run_end`:
@@ -306,6 +597,8 @@ Recommended next:
   /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
 ```
 
+For HEAVY runs, the push notification uses the chosen pair: `Brainstorm complete (pair: C1:codex).`
+
 For the abandoned branch, the push notification just says "Brainstorm abandoned" with no next-step.
 
 ---
```

## Scrutiny focus

1. **HEAVY branch guard logic:** Does it correctly check `SCOPE-brainstorm.json` for `mode == "HEAVY"`? Does the read happen at Phase 4 start (before LIGHT/MEDIUM)?
2. **Matrix construction:** Does the parsing of `## Chunk: <id>` sections from unified BRAINSTORM.md correctly enumerate framings? Does it skip FAILED chunks and marked-failed ideators?
3. **Frontmatter atomicity:** When updating from `chosen_framing: pending` to `chosen_pair: {...}`, does the spec correctly handle removal of chosen_framing and addition of chosen_pair? Is the update atomic?
4. **LIGHT/MEDIUM preservation:** Are the LIGHT/MEDIUM paths completely unmodified (besides header-level restructuring from `###` to `####`)?
5. **Fallthrough logic:** Does the spec guarantee that after HEAVY branch completes (step 4H-4), it jumps to "In all branches" correctly, skipping the entire LIGHT/MEDIUM section?
6. **Downstream /z-plan integration:** Is chosen_pair documented as the seed for downstream /z-plan? Is the format (`chunk_id` + `framing`) clear and stable?

Scrutinize this code spec rigorously. Claude is prone to: over-engineering, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention).

codex
I’ll verify the patched command text in the repo so the findings can point at exact locations instead of only the pasted diff.
exec
/bin/zsh -lc "sed -n '430,610p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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

Parse the unified BRAINSTORM.md that was written at the end of Phase 0's HEAVY fan-out (step 6 of the 0f HEAVY sub-section). Walk each `## Chunk: <id>` section in order. For each chunk that succeeded (i.e. does NOT have `— FAILED` in the heading), enumerate the three standard framings: `claude`, `codex`, `gemini`. Only include framings for ideators that are present in that chunk's BRAINSTORM.md (skip any marked `:failed`).

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

1. Update the BRAINSTORM.md frontmatter:
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

Follow the standard Abandon path below — but set both `chosen_pair: null` and `chosen_framing: abandoned` in the frontmatter (omit `chosen_pair` from the output entirely; set `chosen_framing: abandoned`).

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

exec
/bin/zsh -lc 'rg -n "HEAVY-mode branch|Step 4H|LIGHT/MEDIUM branch|chosen_pair|SCOPE-brainstorm|Phase 4" commands/z-brainstorm.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
117:Write the same JSON to `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json` atomically (tmp+rename). The live file is namespaced per host command; it is overwritten on each run.
153:`MODE: LIGHT` or `MODE: MEDIUM`: proceed to Plan Route Check and then Phase 1 scaffolding unchanged. SCOPE-brainstorm.json is written but Phase 1 does not consult it for brainstorm (unlike `/z-audit` LIGHT, brainstorm has no `dimensions_hint` equivalent — Phase 1 runs identically for both modes in `/z-brainstorm`).
175:This is a HEAVY fan-out sub-flow of /z-brainstorm. Run Phase 1 (scaffolding), Phase 2 (ideator dispatch), and Phase 3 (synthesis) for the sub-scope below. Do NOT run Phase 0 (scope-probe), Plan Route Check, or Phase 4 (user-pick gate — selection happens at the parent level for HEAVY mode). Produce a BRAINSTORM.md at the path specified.
217:7. **Skip Phases 1, 2, and 3.** The unified BRAINSTORM.md (produced by the reconciler or the fallback) replaces the normal Phase 1+2+3 output. Jump directly to Phase 4 — **the HEAVY branch at the top of Phase 4 owns the chunk-selection matrix logic** (see Phase 4 HEAVY-mode branch above).
405:   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
438:   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
449:## Phase 4 — Finalize
451:### HEAVY-mode branch (check FIRST — fires only when mode == HEAVY)
453:Read `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json`. If the file exists and `mode` is `"HEAVY"`, execute this branch and **skip the LIGHT/MEDIUM branch below entirely**.
455:#### Step 4H-1 — Build the (chunk × framing) matrix
466:#### Step 4H-2 — Present the selection matrix to the user
517:#### Step 4H-3 — Handle user's pick
523:   - Add `chosen_pair: {chunk_id: "<id>", framing: "<claude|codex|gemini>"}` (e.g. `chosen_pair: {chunk_id: "C1", framing: "codex"}`).
531:   The framing text below seeds any downstream `/z-plan` invocation. Run `/z-plan` in the same working directory and it will auto-detect BRAINSTORM.md and read `chosen_pair` from the frontmatter.
543:Follow the standard Restart path (see LIGHT/MEDIUM branch below) — archive BRAINSTORM.md with `chosen_framing: restart`, ask for a refined topic, start a fresh RUN.
547:Follow the standard Abandon path below — but set both `chosen_pair: null` and `chosen_framing: abandoned` in the frontmatter (omit `chosen_pair` from the output entirely; set `chosen_framing: abandoned`).
549:#### Step 4H-4 — Fall through to "In all branches" below
551:After completing step 4H-3, skip the LIGHT/MEDIUM branch entirely and jump to "In all branches" at the end of this section. The `brainstorm_run_end` log event and push-notify are shared with the LIGHT/MEDIUM path.
557:### LIGHT/MEDIUM branch (fires when mode is NOT HEAVY, or SCOPE-brainstorm.json is absent)

codex
I found the exact Phase 4 text and am checking it against the upstream unified brainstorm shape. The main risk area is that this is command-spec logic, so ambiguity in parse patterns and branch control becomes implementation behavior later.
exec
/bin/zsh -lc 'rg -n "Chunk:|FAILED|failed|Framing|chosen_framing|chosen_pair|scope-reconciler-brainstorm|BRAINSTORM.md" -S commands scripts docs . | head -n 200' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/bisect-isolator.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/plan-style-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/review-agent.md, agents/reviewer.md, agents/scope-probe.md, agents/scope-reconciler-audit.md, agents/scope-reconciler-brainstorm.md, agents/spec-precheck.md
docs/human/agents.md:10:The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), post-implementation correctness review (`reviewer`), code-quality review (`mr-reviewer`), plan artifact style review (`plan-style-reviewer`), spec validation (`spec-precheck`), post-run memory candidate generation (`review-agent`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), regression bisect isolation (`bisect-isolator`), auditing (`auditor`), cross-LLM consultation (`consultant-primary`, `consultant-secondary`), scope classification (`scope-probe`), and fanout reconciliation (`scope-reconciler-audit`, `scope-reconciler-brainstorm`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.
docs/human/agents.md:32:- `agents/scope-reconciler-brainstorm.md:1` — `scope-reconciler-brainstorm` — Sonnet post-fanout reconciler for HEAVY `/z-brainstorm` runs; concatenates N per-chunk `BRAINSTORM.md` files verbatim, runs a four-part cross-chunk anti-bias check (unique-framing propagation, contradiction detection, Claude-favoring bias audit, axis-coverage audit), and returns unified content with `chosen_framing: pending` for user selection.
docs/human/agents.md:90:- `scope-reconciler-brainstorm` anti-bias check has four mandatory sub-sections (A through D); omitting any sub-section — even when findings are empty — makes the unified output less trustworthy than a single chunk's output.
docs/human/agents.md:91:- `scope-reconciler-brainstorm` Claude-favoring bias check requires a concrete justification naming what Claude said that peer ideators did not. A generic preference ("Claude's framing is cleaner") is not accepted as justification.
docs/human/agents.md:106:- After a HEAVY `/z-brainstorm` fan-out completes, the host dispatches `scope-reconciler-brainstorm` once with the N per-chunk `BRAINSTORM.md` paths. The reconciler returns unified content with `chosen_framing: pending`; the host writes it and presents Phase 3 AskUserQuestion for framing selection.
commands/z-plan-split.md:71:**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.
commands/z-plan-split.md:76:- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
commands/z-plan-split.md:82:- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
commands/z-plan-split.md:88:  "$(printf '{"status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
commands/z-plan-split.md:241:  - Plus a meta-option **Abandon this cluster** — marks it `failed` with `failure_reason: user_abandoned_decision`.
commands/z-plan-split.md:245:- **`STATUS: spec_problem`** → mark cluster `failed` with `failure_reason: spec_problem`. Surface to user via push-notify (no halt). Other clusters continue.
commands/z-plan-split.md:247:- **`STATUS: anti_nesting_violation`** → mark cluster `failed` with `failure_reason: anti_nesting_violation`. Log `anti_nesting_violation` event with `ancestor_manifest_path` from the payload. Other clusters continue.
commands/z-plan-split.md:249:- **`STATUS: unable_to_complete`** → mark cluster `failed` with `failure_reason: unable_to_complete`. Other clusters continue.
commands/z-plan-split.md:251:For every `failed` cluster, emit:
commands/z-plan-split.md:254:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_failed \
commands/z-plan-split.md:258:**Total-failure gate.** If **all** clusters end in a `failed` state, halt: emit:
commands/z-plan-split.md:262:  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
commands/z-plan-split.md:265:…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
commands/z-plan-split.md:275:**Validation.** Compare each cluster's TASKS.md-parsed set against the `FILES_TOUCHED` JSON array the cluster-planner returned (the fast-path summary). If they disagree (after path normalization, see below), mark the cluster `failed` and emit:
commands/z-plan-split.md:283:Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
commands/z-plan-split.md:285:**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
commands/z-plan-split.md:293:Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
commands/z-plan-split.md:300:4. **Reject** paths that escape the repo root (`..` walks past origin after collapsing) — log a `precontext_freshness_check_failed`-style event and exclude that path from overlap detection (do not fail the cluster on this alone — only on FILES_TOUCHED↔TASKS.md disagreement).
commands/z-plan-split.md:372:status: ready | partial | failed
commands/z-plan-split.md:380:- `partial` — ≥1 cluster `failed` AND ≥1 cluster `ready`.
commands/z-plan-split.md:381:- `failed` — all clusters failed (total-failure gate already halted; this branch should not normally write a MANIFEST, but if it did emit a minimal one, use `failed`).
commands/z-plan-split.md:392:| C1 | <cluster_slug> | <scope> | <root-slug>/<cluster_slug>/ | ready / failed | 1 | <ISO> |
commands/z-plan-split.md:421:  "$(printf '{"status":"%s","total_clusters":%d,"clusters_ready":%d,"clusters_failed":%d,"overlap_count":%d,"partial_tree":%s}' \
commands/z-plan-split.md:425:where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
commands/z-plan-split.md:438:For the partial-tree branch, the push notification also names the failed clusters and reminds the user that `/z-implement-all` will refuse without `--force-partial` until the failures are addressed (drop the cluster, re-plan it, or override the gate).
commands/z-plan-split.md:447:- **Partial trees are valid.** ≥1 cluster ready → proceed. All clusters failed → halt with `total_cluster_failure`.
./skills/z-plan-split/SKILL.md:72:**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.
./skills/z-plan-split/SKILL.md:77:- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./skills/z-plan-split/SKILL.md:83:- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./skills/z-plan-split/SKILL.md:89:  "$(printf '{"status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
./skills/z-plan-split/SKILL.md:242:  - Plus a meta-option **Abandon this cluster** — marks it `failed` with `failure_reason: user_abandoned_decision`.
./skills/z-plan-split/SKILL.md:246:- **`STATUS: spec_problem`** → mark cluster `failed` with `failure_reason: spec_problem`. Surface to user via push-notify (no halt). Other clusters continue.
./skills/z-plan-split/SKILL.md:248:- **`STATUS: anti_nesting_violation`** → mark cluster `failed` with `failure_reason: anti_nesting_violation`. Log `anti_nesting_violation` event with `ancestor_manifest_path` from the payload. Other clusters continue.
./skills/z-plan-split/SKILL.md:250:- **`STATUS: unable_to_complete`** → mark cluster `failed` with `failure_reason: unable_to_complete`. Other clusters continue.
./skills/z-plan-split/SKILL.md:252:For every `failed` cluster, emit:
./skills/z-plan-split/SKILL.md:255:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_failed \
./skills/z-plan-split/SKILL.md:259:**Total-failure gate.** If **all** clusters end in a `failed` state, halt: emit:
./skills/z-plan-split/SKILL.md:263:  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./skills/z-plan-split/SKILL.md:266:…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./skills/z-plan-split/SKILL.md:276:**Validation.** Compare each cluster's TASKS.md-parsed set against the `FILES_TOUCHED` JSON array the cluster-planner returned (the fast-path summary). If they disagree (after path normalization, see below), mark the cluster `failed` and emit:
./skills/z-plan-split/SKILL.md:284:Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./skills/z-plan-split/SKILL.md:286:**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./skills/z-plan-split/SKILL.md:294:Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./skills/z-plan-split/SKILL.md:301:4. **Reject** paths that escape the repo root (`..` walks past origin after collapsing) — log a `precontext_freshness_check_failed`-style event and exclude that path from overlap detection (do not fail the cluster on this alone — only on FILES_TOUCHED↔TASKS.md disagreement).
./skills/z-plan-split/SKILL.md:373:status: ready | partial | failed
./skills/z-plan-split/SKILL.md:381:- `partial` — ≥1 cluster `failed` AND ≥1 cluster `ready`.
./skills/z-plan-split/SKILL.md:382:- `failed` — all clusters failed (total-failure gate already halted; this branch should not normally write a MANIFEST, but if it did emit a minimal one, use `failed`).
./skills/z-plan-split/SKILL.md:393:| C1 | <cluster_slug> | <scope> | <root-slug>/<cluster_slug>/ | ready / failed | 1 | <ISO> |
./skills/z-plan-split/SKILL.md:422:  "$(printf '{"status":"%s","total_clusters":%d,"clusters_ready":%d,"clusters_failed":%d,"overlap_count":%d,"partial_tree":%s}' \
./skills/z-plan-split/SKILL.md:426:where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./skills/z-plan-split/SKILL.md:439:For the partial-tree branch, the push notification also names the failed clusters and reminds the user that `/z-implement-all` will refuse without `--force-partial` until the failures are addressed (drop the cluster, re-plan it, or override the gate).
./skills/z-plan-split/SKILL.md:448:- **Partial trees are valid.** ≥1 cluster ready → proceed. All clusters failed → halt with `total_cluster_failure`.
./skills/z-research/SKILL.md:115:   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
./skills/z-research/SKILL.md:255:**Per-consultant failure policy.** A consultant return is "failed" if it errors, returns empty, or returns a payload that does not contain at least one of `Gaps` / `Errors` / `Missing constraints` sections (malformed). For each consultant independently:
./skills/z-research/SKILL.md:258:2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./skills/z-research/SKILL.md:263:- **Both consultants failed (after retry)** → DO NOT mark `status: complete`. Prompt the user via `AskUserQuestion` with three options:
./skills/z-research/SKILL.md:264:  - **proceed-with-no-critique** — finalize with `status: complete_no_critique` and an explicit `## Cross-LLM review notes` entry stating both consultants failed.
./skills/z-research/SKILL.md:274:Checkpoint: `phase4-critiques.md` (both critiques side-by-side, with `<consultant>:failed` markers where applicable).
./skills/z-research/SKILL.md:344:**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./skills/z-debug/SKILL.md:475:   - `/z-mr-review` already gates on `STYLE.md` existence and will refuse with "Run /z-style-init first." if it's missing. Do NOT try to handle this here — let it fail-fast. On failure, log "MR review skipped: STYLE.md missing" (or "MR review skipped: /z-mr-review failed — <reason>") and continue.
./skills/z-debug/SKILL.md:603:      - **Agent error / no fenced block:** log `review_agent_failed`; push-notify; exit memory-review sub-step.
./skills/z-review-all/SKILL.md:131:SUITE_FAILED=0
./skills/z-review-all/SKILL.md:135:  eval "$CMD" >> "$SUITE_LOG" 2>&1 || SUITE_FAILED=$((SUITE_FAILED+1))
./skills/z-review-all/SKILL.md:208:- Whole categories of behavior the spec failed to anticipate.
./skills/z-review-all/SKILL.md:439:       # no fenced block → review_agent_failed
./skills/z-review-all/SKILL.md:447:   - **Agent errored / no fenced block (`review_agent_failed`):**
./skills/z-review-all/SKILL.md:452:     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_failed \
./skills/z-review-all/SKILL.md:535:        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_suggest_failed \
./skills/z-review-all/SKILL.md:576:| `review_agent_failed` | Agent returned without a fenced block |
./skills/z-review-all/SKILL.md:577:| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
./skills/z-review-all/SKILL.md:581:| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an Accepted candidate |
docs/human/telemetry.md:20:| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
docs/human/telemetry.md:24:| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
docs/human/telemetry.md:38:| `cluster_failed` | `/z-plan-split` Phase 3 (per failed cluster; `failure_reason` field) |
docs/human/telemetry.md:41:| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./skills/z-brainstorm/SKILL.md:3:description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
./skills/z-brainstorm/SKILL.md:23:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
./skills/z-brainstorm/SKILL.md:24:   - **overwrite** — archive existing `BRAINSTORM.md` to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
./skills/z-brainstorm/SKILL.md:40:- `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
./skills/z-brainstorm/SKILL.md:124:Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
./skills/z-brainstorm/SKILL.md:152:Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
./skills/z-brainstorm/SKILL.md:180:Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.
./skills/z-brainstorm/SKILL.md:182:- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<id>:failed"` in the `ideators` frontmatter list using the canonical id (`claude:failed` | `codex:failed` | `gemini:failed`). The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
./skills/z-brainstorm/SKILL.md:184:  - **retry** (default) — re-dispatch the failed ideators once
./skills/z-brainstorm/SKILL.md:185:  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
./skills/z-brainstorm/SKILL.md:186:  - **abandon** — write a minimal abandoned BRAINSTORM.md (frontmatter: `artifact`, `slug`, `generated_at`, `command`, `input_hash`, `ideators` with `:failed` suffix on the failed members, `ideator_models`, `status: abandoned`, `chosen_framing: abandoned`; body: a single `## Abandoned` section with one sentence of context) so `/z-plan` can detect the prior attempt, then exit.
./skills/z-brainstorm/SKILL.md:187:- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.
./skills/z-brainstorm/SKILL.md:189:Log every individual failure as `ideator_failed` regardless of the bucket above.
./skills/z-brainstorm/SKILL.md:197:2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.
./skills/z-brainstorm/SKILL.md:201:4. **Write `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`** with YAML frontmatter:
./skills/z-brainstorm/SKILL.md:215:     # failed members recorded as "<id>:failed" (e.g. claude:failed)
./skills/z-brainstorm/SKILL.md:221:   chosen_framing: pending
./skills/z-brainstorm/SKILL.md:225:   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./skills/z-brainstorm/SKILL.md:230:   ## Framing: <ideator-name>
./skills/z-brainstorm/SKILL.md:232:   ### Framing
./skills/z-brainstorm/SKILL.md:275:1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter from `pending` to the picked ideator id (`claude` | `codex` | `gemini`).
./skills/z-brainstorm/SKILL.md:281:1. Archive the just-written BRAINSTORM.md to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer). Before archiving, update the archived copy's frontmatter to `status: complete`, `chosen_framing: restart` so the historical record is spec-valid.
./skills/z-brainstorm/SKILL.md:287:1. Set the frontmatter `status: abandoned` and `chosen_framing: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
./skills/z-brainstorm/SKILL.md:296:  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./skills/z-brainstorm/SKILL.md:307:  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
docs/human/multi-ide-exports.md:10:The pipeline is intentionally mechanical. `scripts/export-common.py` provides the shared library: frontmatter parsing, source enumeration across the three kinds, `CAPABILITIES.md` schema validation, and conventional output-path computation. Each per-target adapter (`export-cursor.py`, `export-codex.py`, `export-agy.py`) rewrites Anthropic-specific constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`) into target-specific limitation comments, writes the target tree, and validates every emitted file before reporting its summary count. The `/z-export` slash command is the user-facing entry point: it parses `--target=<cursor|codex|agy|all>`, runs the selected adapters sequentially via `python3 scripts/export-<target>.py`, and prints per-target `OK` or `FAILED` lines regardless of individual failures.
docs/human/multi-ide-exports.md:33:- `commands/z-export.md:10` — `/z-export` — Parse `--target`, run adapters sequentially, report per-target OK/FAILED, continue past failures.
docs/human/multi-ide-exports.md:61:- `/z-export --target=all` — runs all three adapters sequentially; reports `OK` or `FAILED` per target.
docs/human/PLAN-LAYOUT.md:24:        ├── BRAINSTORM.md         (if /z-brainstorm was run)
./skills/z-stats/SKILL.md:66:jq -c 'select(.kind == "task_halt" or .kind == "decision_gate" or .kind == "task_security_warn" or .kind == "review_agent_failed" or .kind == "review_agent_malformed")' "$METRICS" \
./skills/z-stats/SKILL.md:89:- `review_agent_failed` with `reason == "tags_missing"` → `state: skipped_broken_context, skip_reason: "tags_missing"`
./skills/z-stats/SKILL.md:120:    elif .kind == "review_agent_failed" and .reason == "tags_missing" then
./skills/z-implement-all/SKILL.md:12:- `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
./skills/z-implement-all/SKILL.md:59:      - `status` must be one of the legal values (`ready`, `partial`, `failed`); if `status: ready` then `clusters_ready == total_clusters`; if `status: partial` then `0 < clusters_ready < total_clusters`.
./skills/z-implement-all/SKILL.md:75:   5. **Partial-tree gate (decides which clusters will run).** Read SHARED-CONCERNS.md frontmatter. If `partial_tree: true` (some clusters failed planning, so overlap detection is a lower bound):
./skills/z-implement-all/SKILL.md:76:      - **Without `--force-partial`** → halt with `partial_tree_blocked` event naming the failed clusters parsed from MANIFEST:
./skills/z-implement-all/SKILL.md:79:        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./skills/z-implement-all/SKILL.md:85:        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./skills/z-implement-all/SKILL.md:87:      Continue, but exclude failed clusters from the run set. Define `clusters_to_run` = run-order list with `failed`-status IDs filtered out.
./skills/z-implement-all/SKILL.md:90:   6. **Cluster-readiness gate (over `clusters_to_run` only).** For each cluster in `clusters_to_run`, look up its row in the Clusters table. The `Status` column must be `ready`; equivalently, the file at the cluster's `Path` column joined with `TASKS.md` must exist, parse cleanly, and contain ≥1 task block. Any cluster in `clusters_to_run` with `status: planning` (or `failed` — which can only happen if `--force-partial` was NOT in play, since 2b.5 already filtered failed) → halt with `cluster_not_ready` event:
./skills/z-implement-all/SKILL.md:95:      Push-notify the user and abort. (No override flag — planning clusters must finish planning via `/z-plan-split` resume; failed clusters are addressed via `--force-partial` in step 2b.5.)
./skills/z-implement-all/SKILL.md:444:PASSED=0; FAILED=0
./skills/z-implement-all/SKILL.md:454:    FAILED=$((FAILED+1)); echo "[FAIL] $TEST_ID" >> "$BASE/archive/tasks/<task-id>/test-result.txt"
./skills/z-implement-all/SKILL.md:460:- **Any test fails** → halt the track with `STATUS: test_failed`. Push-notify. Present the failure log to the user via `AskUserQuestion`:
./skills/z-implement-all/SKILL.md:484:  "$(printf '{"id":"%s","retries":%d,"review_blockers":%d,"review_cycles":%d,"tests_passed":%d,"tests_failed":%d}' \
./skills/z-implement-all/SKILL.md:485:     "<task-id>" "<n>" "<n>" "<n>" "$PASSED" "$FAILED")"
./skills/z-implement-all/SKILL.md:487:(`tests_passed`/`tests_failed` are 0 if the task had no `**Tests:**` line.)
./skills/z-implement-all/SKILL.md:530:| `decision_gate` | Halted for user input | `id`, `reason` (`spec_problem`/`decision_needed`/`needs_clarification`/`review_failed`), `wait_ms` (filled in after user replies) |
./skills/z-implement-all/SKILL.md:660:       # no fenced block → review_agent_failed
./skills/z-implement-all/SKILL.md:673:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./skills/z-implement-all/SKILL.md:678:     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_failed \
./skills/z-implement-all/SKILL.md:681:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./skills/z-implement-all/SKILL.md:752:        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_suggest_failed \
./skills/z-implement-all/SKILL.md:793:| `review_agent_failed` | Agent returned without a fenced block |
./skills/z-implement-all/SKILL.md:794:| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
docs/human/commands.md:60:- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators. Produces `BRAINSTORM.md`. Cost target: ≤200K tokens.
docs/human/commands.md:142:- `/z-export` continues past individual target failures — a failed `cursor` export does not abort the `codex` or `agy` exports. All output is verbatim from adapter scripts; the command does no LLM interpretation of export results.
docs/human/MULTI-IDE.md:56:- `/z-export --target=all` runs the three adapters sequentially and continues past individual target failures so each target reports `OK` or `FAILED`.
commands/z-review-all.md:135:SUITE_FAILED=0
commands/z-review-all.md:139:  eval "$CMD" >> "$SUITE_LOG" 2>&1 || SUITE_FAILED=$((SUITE_FAILED+1))
commands/z-review-all.md:212:- Whole categories of behavior the spec failed to anticipate.
commands/z-review-all.md:434:       - **Accept** — dispatch `/z-suggest-memory --concept <suggested_concept_slug> --from-candidate-json <tmp_path> --source "incident:<RRUN>"`. On `STATUS: ok`, increment `accepted` counter. On `STATUS: skipped` or `STATUS: bad_input`, log `review_agent_suggest_failed` with reason and continue.
commands/z-review-all.md:455:| `review_agent_failed` | Agent returned without a fenced block |
commands/z-review-all.md:456:| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
commands/z-review-all.md:460:| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an Accepted candidate |
./skills/z-plan/SKILL.md:20:   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
./skills/z-plan/SKILL.md:45:9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
./skills/z-plan/SKILL.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./skills/z-plan/SKILL.md:47:    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
./skills/z-plan/SKILL.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./skills/z-plan/SKILL.md:105:**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
./skills/z-plan/SKILL.md:264:| BRAINSTORM.md | $Z_HARNESS_PLAN_DIR/BRAINSTORM.md | <iso timestamp or "n/a"> |
./skills/z-suggest-memory/SKILL.md:417:- `STATUS: bad_input` — validation failed or invalid index; nothing written.
./skills/z-suggest-memory/SKILL.md:418:- `STATUS: no_docs` — preflight failed; nothing written.
./commands/z-plan-split.md:71:**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.
./commands/z-plan-split.md:76:- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./commands/z-plan-split.md:82:- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./commands/z-plan-split.md:88:  "$(printf '{"status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
./commands/z-plan-split.md:241:  - Plus a meta-option **Abandon this cluster** — marks it `failed` with `failure_reason: user_abandoned_decision`.
./commands/z-plan-split.md:245:- **`STATUS: spec_problem`** → mark cluster `failed` with `failure_reason: spec_problem`. Surface to user via push-notify (no halt). Other clusters continue.
./commands/z-plan-split.md:247:- **`STATUS: anti_nesting_violation`** → mark cluster `failed` with `failure_reason: anti_nesting_violation`. Log `anti_nesting_violation` event with `ancestor_manifest_path` from the payload. Other clusters continue.
./commands/z-plan-split.md:249:- **`STATUS: unable_to_complete`** → mark cluster `failed` with `failure_reason: unable_to_complete`. Other clusters continue.
./commands/z-plan-split.md:251:For every `failed` cluster, emit:
./commands/z-plan-split.md:254:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_failed \
./commands/z-plan-split.md:258:**Total-failure gate.** If **all** clusters end in a `failed` state, halt: emit:
./commands/z-plan-split.md:262:  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./commands/z-plan-split.md:265:…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./commands/z-plan-split.md:275:**Validation.** Compare each cluster's TASKS.md-parsed set against the `FILES_TOUCHED` JSON array the cluster-planner returned (the fast-path summary). If they disagree (after path normalization, see below), mark the cluster `failed` and emit:
./commands/z-plan-split.md:283:Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./commands/z-plan-split.md:285:**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./commands/z-plan-split.md:293:Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./commands/z-plan-split.md:300:4. **Reject** paths that escape the repo root (`..` walks past origin after collapsing) — log a `precontext_freshness_check_failed`-style event and exclude that path from overlap detection (do not fail the cluster on this alone — only on FILES_TOUCHED↔TASKS.md disagreement).
./commands/z-plan-split.md:372:status: ready | partial | failed
./commands/z-plan-split.md:380:- `partial` — ≥1 cluster `failed` AND ≥1 cluster `ready`.
./commands/z-plan-split.md:381:- `failed` — all clusters failed (total-failure gate already halted; this branch should not normally write a MANIFEST, but if it did emit a minimal one, use `failed`).
./commands/z-plan-split.md:392:| C1 | <cluster_slug> | <scope> | <root-slug>/<cluster_slug>/ | ready / failed | 1 | <ISO> |
./commands/z-plan-split.md:421:  "$(printf '{"status":"%s","total_clusters":%d,"clusters_ready":%d,"clusters_failed":%d,"overlap_count":%d,"partial_tree":%s}' \
./commands/z-plan-split.md:425:where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./commands/z-plan-split.md:438:For the partial-tree branch, the push notification also names the failed clusters and reminds the user that `/z-implement-all` will refuse without `--force-partial` until the failures are addressed (drop the cluster, re-plan it, or override the gate).
./commands/z-plan-split.md:447:- **Partial trees are valid.** ≥1 cluster ready → proceed. All clusters failed → halt with `total_cluster_failure`.
./commands/z-review-all.md:135:SUITE_FAILED=0
./commands/z-review-all.md:139:  eval "$CMD" >> "$SUITE_LOG" 2>&1 || SUITE_FAILED=$((SUITE_FAILED+1))
./commands/z-review-all.md:212:- Whole categories of behavior the spec failed to anticipate.
./commands/z-review-all.md:434:       - **Accept** — dispatch `/z-suggest-memory --concept <suggested_concept_slug> --from-candidate-json <tmp_path> --source "incident:<RRUN>"`. On `STATUS: ok`, increment `accepted` counter. On `STATUS: skipped` or `STATUS: bad_input`, log `review_agent_suggest_failed` with reason and continue.
./commands/z-review-all.md:455:| `review_agent_failed` | Agent returned without a fenced block |
./commands/z-review-all.md:456:| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
./commands/z-review-all.md:460:| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an Accepted candidate |
docs/human/review-agent.md:27:- `z-stats` — surfaces `review_agent_call`, `review_agent_failed`, and `review_agent_malformed` events for debugging
docs/human/review-agent.md:92:| `review_agent_failed` | Agent dispatch failed or returned no parseable output; fields include `reason`. |
docs/human/review-agent.md:98:| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an accepted candidate; logged and iteration continues. |
docs/human/review-agent.md:121:- `review_agent_failed` and `review_agent_malformed` do NOT emit `memory_review_terminal` — they are orthogonal failure classes, not terminal states of the review pass.
docs/human/review-agent.md:150:**Step 1 — Run `/z-stats` Phase 4.** Phase 4 surfaces `review_agent_failed` and `review_agent_malformed` events. Phase 4b lists recent `review_agent_call` entries with candidate counts and token spend:
docs/human/review-agent.md:159:jq 'select(.kind == "review_agent_failed" or .kind == "review_agent_malformed")' \
docs/human/review-agent.md:163:**Step 3 — Check `memory-candidates.jsonl`.** If the file exists but is malformed, the agent returned parseable JSON but downstream write failed. If missing, the agent returned zero candidates or the phase was skipped.
docs/human/skills.md:17:- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Cheap pre-plan ideation with three vendor-diverse ideators, identical scaffolding, mandatory anti-bias checks, and BRAINSTORM.md output.
docs/human/skills.md:62:- `memory_review_terminal` is the canonical terminal event for all memory-review paths. It is emitted by `run-memory-review.sh` for all skip states, and by the orchestrating skill for `ran_empty` and `needs_user` states. `review_agent_failed` and `review_agent_malformed` are orthogonal failure-class events — they do NOT emit `memory_review_terminal`.
docs/human/skills.md:66:- `/z-debug` Phase 2.5 bisect is a conditional fast-path, not a required phase. It fires only when the bug is a regression with a known-good baseline and a scriptable repro. `refused`, `failed`, and `bisect_unusable` returns all fall through to Phase 3a unchanged — bisect never blocks the pipeline.
docs/human/config.md:193:Slices 2 and 3 of this feature (see `z-harness/z-harness-config-toml/BRAINSTORM.md`)
docs/human/mr-reviewer.md:72:| `mr_voice_failed` | A consultant voice returned malformed JSON |

exec
/bin/zsh -lc 'rg -n "scope-reconciler-brainstorm|## Chunk|### .*framing|:failed|FAILED" -S .' in /Users/zeke/dev/z-harness
 succeeded in 114ms:
./z-harness/plans/mr-style-reviewer/archive/20260524T004459Z-review/cumulative.diff:2118:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/mr-style-reviewer/archive/20260524T004459Z-review/cumulative.diff:5497:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:606:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1049:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1315:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1321:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1430:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1436:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.response.md:117: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.response.md:124:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.response.md:275: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.response.md:282:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review.response.md:103:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review.response.md:221:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T009/review.prompt.md:777:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/plan-decompose/archive/tasks/T003/delta-v2.patch:71: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/delta-v2.patch:78:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/delta-v2.patch:229: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/delta-v2.patch:236:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff.patch:74:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff.patch:80:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff.patch:189:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff.patch:195:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff-v1.patch:60:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/diff-v1.patch:178:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.prompt.md:102: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.prompt.md:109:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.prompt.md:260: +        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review-v2.prompt.md:267:++        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review.prompt.md:88:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/plan-decompose/archive/tasks/T003/review.prompt.md:206:+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T009/diff-v1.patch:730:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:7:- Phase 3: STATUS branching — ok→ready+attempts:1; decision_needed→halt that leaf, structured AskUserQuestion (use OPTIONS verbatim, list RECOMMENDED_OPTION first), re-spawn with RESOLVED_DECISION; spec_problem/anti_nesting_violation/unable_to_complete→failed. All fail → total_cluster_failure halt + minimal MANIFEST status:failed, no SHARED-CONCERNS.md.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:229:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:617:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:3184:' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T009/review.response.md:792:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T009/diff.patch:730:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:210:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:598:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:123: +  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:318: +  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:251:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:694:+  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/delta-v2.patch:115:-+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/delta-v2.patch:116:++' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/review.prompt.md:75:' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/diff-v2.patch:630:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/diff.patch:638:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
./z-harness/plans/mr-style-reviewer/archive/tasks/T006/diff-v1.patch:619:+' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"

exec
/bin/zsh -lc "sed -n '40,70p' skills/z-plan/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy is resolved from config via the `export-env` step above. See `docs/human/config.md` for knob details (`notify.level`).
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.

exec
/bin/zsh -lc "sed -n '1,130p' agents/scope-reconciler-brainstorm.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '185,215p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
Scaffolding instructions: follow /z-brainstorm Phase 1 (doc-fetcher, optional Explore, RESEARCH.md ingestion, input_hash). Ideator dispatch: follow /z-brainstorm Phase 2 with the IDEATOR_SCHEMA. Synthesis: follow /z-brainstorm Phase 3 (anti-bias check, orchestrator recommendation). Write the BRAINSTORM.md with chosen_framing: pending (do NOT present an AskUserQuestion — the parent owns the user-pick gate)."
   )
   ```

   Sub-flows MUST NOT themselves go HEAVY (anti-sprawl invariant: sub-flows skip Phase 0 entirely).

3. **Collect sub-flow results.** For each chunk, record:
   - `brainstorm_path`: `$Z_HARNESS_PLAN_DIR/archive/$RUN/chunks/<C.id>/BRAINSTORM.md`
   - `status`: succeeded (file exists and is non-empty) or failed

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

 succeeded in 0ms:
---
name: scope-reconciler-brainstorm
description: Post-fanout Sonnet reconciler for HEAVY /z-brainstorm runs. Reads N per-chunk BRAINSTORM.md files, concatenates their framing sections under per-chunk headers, runs a cross-chunk anti-bias check to surface unique framings and contradictions, then emits a unified top-level BRAINSTORM.md with chosen_framing set to pending for user selection.
tools: Read
model: sonnet
---

## Mission

You are a synthesis agent for HEAVY `/z-brainstorm` fan-out runs. When `scope-probe` classified the topic as HEAVY and `/z-brainstorm` dispatched N parallel sub-flows, each sub-flow produced its own `BRAINSTORM.md`. Your job is to merge those per-chunk brainstorm files into a single unified `BRAINSTORM.md` that:

1. Preserves every framing from every chunk (no lossy summarization).
2. Adds a meta-level anti-bias check that reasons across chunks, not just across ideators within one chunk.
3. Sets `chosen_framing: pending` so the user can select the winning framing.

You do not pick a framing for the user. You do not smooth over contradictions. Cross-chunk disagreement is a feature.

## Inputs from Caller

The caller prompt must provide:

- `host_run_id:` the parent `/z-brainstorm` run identifier (e.g. `20260527T175422Z-fanout-escalate-primitive`).
- `chunks:` JSON array of objects, each with:
  - `id:` chunk identifier (e.g. `C1`, `C2`).
  - `brainstorm_path:` absolute path to that chunk's `BRAINSTORM.md`.
- `axis:` the axis name used for the fan-out (e.g. `per_vendor`, `per_framing`).
- `output_path:` absolute path where the unified `BRAINSTORM.md` should be written.

A chunk entry may include a `status: failed` field if that sub-flow did not complete. Failed chunks must be represented in the output with a `## Chunk: <id> — FAILED` section rather than omitted.

## Procedure

### Step 1 — Read all chunk BRAINSTORM.md files

For each chunk in `chunks`:
- If `status: failed` is present, record that chunk as failed and skip reading.
- Otherwise, use Read to load the chunk's `BRAINSTORM.md` at `brainstorm_path`.
- If the file is missing or unreadable (but `status: failed` was not pre-declared), treat it as a failed chunk and record a note explaining the file was absent.

Record which chunks succeeded (readable) and which failed.

### Step 2 — Concatenate framing sections under per-chunk headers

For each succeeded chunk, extract and reproduce its framing content under a top-level `## Chunk: <id>` header. Include:
- The chunk's axis scope (what sub-topic or sub-scope this chunk covered — derive from the chunk's frontmatter or first paragraph if not explicitly labeled).
- All ideator framing blocks from that chunk's BRAINSTORM.md verbatim (do not paraphrase or abbreviate).
- The chunk's own anti-bias check and orchestrator recommendation (verbatim), if present.

For each failed chunk, emit a `## Chunk: <id> — FAILED` section with a one-sentence note.

### Step 3 — Run cross-chunk anti-bias check

After collecting all chunk framings, perform a meta-level anti-bias check that reasons across chunks:

**A. Unique-framing propagation check**
For each framing unique to one chunk (i.e. no analogous framing appears in any other chunk), ask: should this framing have propagated to the other chunks? If the framing addresses a concern that plausibly applies across the full topic scope and not just the chunk's sub-scope, flag it as a **cross-chunk propagation candidate** with a one-sentence explanation.

**B. Contradiction detection**
Identify pairs or clusters of framings across chunks that make incompatible claims about the same aspect (e.g. one chunk says vendor X is the safest choice, another says vendor X is the highest risk). Record each contradiction explicitly. Do NOT resolve contradictions — surface them for the user. Contradictions are evidence that the chunk division exposed genuine disagreement, which is valuable signal.

**C. Claude-favoring bias check**
For each chunk that succeeded, examine the chunk's internal anti-bias check and orchestrator recommendation section-by-section. The five sections to examine per chunk are: Framing, Core hypothesis, Risks, Plan implications, and What would change my mind.

For each section where the chunk's orchestrator (or the chunk's anti-bias analysis) preferred or recommended the Claude ideator's content over the Codex or Gemini ideator's content, ask: is the preference explicitly justified with a concrete reason? A concrete reason names what the Claude ideator said that the peer ideators did not (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). A generic preference ("Claude's framing is cleaner") is not a concrete reason.

Record each section-level Claude-favoring pick across all chunks in a table:
- Chunk ID, Section name, Claude preferred (yes/no), Justification provided (yes/no/text).

After tabulating, flag any section-level pick where Claude was preferred but no concrete justification was given as **unjustified Claude-favoring**. Additionally, if Claude-favoring picks (with or without justification) appear in ≥50% of chunks for a given section, flag that section as a **systematic-bias candidate** and note whether each instance was justified or unjustified.

**D. Axis-coverage audit**
Given that chunks were divided along `axis`, confirm each chunk covered a distinct slice of the topic. If two chunks appear to address the same sub-scope (duplicate coverage), flag the overlap.

Emit a `## Cross-chunk anti-bias check` section containing findings from all four checks. Empty findings for a check should be recorded as a one-line "none detected" — do not omit the check heading.

### Step 4 — Return unified BRAINSTORM.md content

Return the unified BRAINSTORM.md content as your response text. The caller (orchestrator) writes this content to `output_path` — you do not write files. Match the pattern used by `mr-reviewer` and `scope-reconciler-audit`: return content, let the caller write. The returned content must follow this structure:

```
---
artifact: brainstorm
slug: <derived from host_run_id>
generated_at: <UTC ISO 8601 — use current time>
command: /z-brainstorm (fanout reconciler)
host_run_id: <host_run_id>
axis: <axis>
chunks_total: <N>
chunks_succeeded: <count of non-failed chunks>
chunks_failed: <count of failed chunks; 0 if none>
chosen_framing: pending
---

## Reconciler preamble

This BRAINSTORM.md was produced by `scope-reconciler-brainstorm` after a HEAVY fan-out run along the `<axis>` axis. <N> sub-runs were dispatched; <chunks_succeeded> succeeded and <chunks_failed> failed.

The `chosen_framing` field is set to `pending`. The user should review the per-chunk sections and the cross-chunk anti-bias check below, then update `chosen_framing` to identify the selected framing (e.g. `C2:codex` for chunk C2's Codex ideator framing).

## Chunk: <id>

<!-- chunk scope: <sub-scope covered> -->

<verbatim framing blocks from chunk's BRAINSTORM.md>

<chunk's own anti-bias check and orchestrator recommendation, verbatim>

## Chunk: <id> — FAILED

<one-sentence reason>

...

## Cross-chunk anti-bias check

### A. Unique-framing propagation candidates
<findings or "None detected.">

### B. Cross-chunk contradictions
<findings or "None detected.">

### C. Claude-favoring bias check
<findings or "None detected.">

### D. Axis-coverage audit
<findings or "None detected.">

## Cross-chunk orchestrator note

<One paragraph: overall meta-observation about the fan-out. What did dividing along this axis reveal that a single-run brainstorm would likely have missed? What convergence or divergence across chunks is most significant? Keep to ≤5 sentences.>

exec
/bin/zsh -lc 'rg -n "Unfinalized brainstorm|chosen_framing" commands/z-plan.md skills/z-plan/SKILL.md docs/llm -S' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
skills/z-plan/SKILL.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
commands/z-plan.md:55:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
docs/llm/agents.json:160:      "summary": "Sonnet post-fanout reconciler for HEAVY z-brainstorm runs; concatenates N per-chunk BRAINSTORM.md files verbatim, runs cross-chunk anti-bias check; sets chosen_framing: pending for user selection."
docs/llm/agents.json:205:    "scope-reconciler-brainstorm always sets chosen_framing: pending; any other value is a spec violation.",

codex
- **Major** — [commands/z-plan.md](/Users/zeke/dev/z-harness/commands/z-plan.md:55) / [skills/z-plan/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md:48): downstream `/z-plan` still treats any `BRAINSTORM.md` without `chosen_framing` as unfinalized, so a successful HEAVY run using only `chosen_pair` will be rejected or rerouted. Update `/z-plan` detection to accept `status: complete` plus either `chosen_framing` or `chosen_pair.{chunk_id,framing}`, and then seed from `chosen_pair` when present.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:457): matrix parsing is underspecified against the actual reconciler contract, because the unified chunk content is verbatim nested brainstorm blocks and the text does not define exact headings or boundaries for `claude|codex|gemini` blocks. Specify the parser contract explicitly, e.g. within each `## Chunk: <id>` scan only `## Framing: <canonical-id>` blocks until the next `## Framing:` or `## Chunk:`, and skip ids listed as `<id>:failed` in that chunk’s frontmatter.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:206) / [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:457): the reconciler-failure fallback writes raw concatenated content under a non-chunk-major header, but Phase 4 assumes parseable `## Chunk: <id>` sections and has no zero-pair/error path. Make the fallback emit the same `## Chunk: <id>` / `## Chunk: <id> — FAILED` structure, or make Phase 4 halt with a repair/abandon question when `N_PAIRS == 0`.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:523): the frontmatter change is not specified as atomic even though it removes one seed field and adds another. Require writing a temp file, validating frontmatter contains exactly `status: complete` and one valid `chosen_pair`, then renaming over `BRAINSTORM.md`.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:547): the HEAVY abandon rule is internally contradictory: it says to set `chosen_pair: null` and also omit `chosen_pair` entirely. Pick one canonical abandoned shape, preferably matching existing abandoned handling with `status: abandoned` and `chosen_framing: abandoned`, and state that `chosen_pair` is only required for completed HEAVY selections.
tokens used
77,057
- **Major** — [commands/z-plan.md](/Users/zeke/dev/z-harness/commands/z-plan.md:55) / [skills/z-plan/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md:48): downstream `/z-plan` still treats any `BRAINSTORM.md` without `chosen_framing` as unfinalized, so a successful HEAVY run using only `chosen_pair` will be rejected or rerouted. Update `/z-plan` detection to accept `status: complete` plus either `chosen_framing` or `chosen_pair.{chunk_id,framing}`, and then seed from `chosen_pair` when present.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:457): matrix parsing is underspecified against the actual reconciler contract, because the unified chunk content is verbatim nested brainstorm blocks and the text does not define exact headings or boundaries for `claude|codex|gemini` blocks. Specify the parser contract explicitly, e.g. within each `## Chunk: <id>` scan only `## Framing: <canonical-id>` blocks until the next `## Framing:` or `## Chunk:`, and skip ids listed as `<id>:failed` in that chunk’s frontmatter.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:206) / [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:457): the reconciler-failure fallback writes raw concatenated content under a non-chunk-major header, but Phase 4 assumes parseable `## Chunk: <id>` sections and has no zero-pair/error path. Make the fallback emit the same `## Chunk: <id>` / `## Chunk: <id> — FAILED` structure, or make Phase 4 halt with a repair/abandon question when `N_PAIRS == 0`.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:523): the frontmatter change is not specified as atomic even though it removes one seed field and adds another. Require writing a temp file, validating frontmatter contains exactly `status: complete` and one valid `chosen_pair`, then renaming over `BRAINSTORM.md`.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:547): the HEAVY abandon rule is internally contradictory: it says to set `chosen_pair: null` and also omit `chosen_pair` entirely. Pick one canonical abandoned shape, preferably matching existing abandoned handling with `status: abandoned` and `chosen_framing: abandoned`, and state that `chosen_pair` is only required for completed HEAVY selections.
