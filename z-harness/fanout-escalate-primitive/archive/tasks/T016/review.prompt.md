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
