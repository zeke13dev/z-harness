You are reviewing code that Claude just wrote for task T003: Create /z-brainstorm command + skill mirror.

Spec (excerpt from z-harness/brainstorm-and-research/SPEC.md):

### BRAINSTORM.md frontmatter required fields:
artifact: brainstorm; slug; generated_at (UTC ISO 8601); command: /z-brainstorm <args>;
input_hash: <16 hex>; depends_on; ideators (list, failed = "<vendor>:failed");
status: complete | abandoned; chosen_framing: claude | codex | gemini | restart.

Body: one block per ideator with sections Framing / Core hypothesis / Risks / Plan implications / What would change my mind. Followed by Anti-bias check, Orchestrator recommendation, User choice. Missing/malformed -> <missing>.

input_hash algorithm:
  sha256(canonicalize(topic + "\n---\n" + doc_fetcher_synthesis_or_empty + "\n---\n" + explore_synthesis_or_empty + "\n---\n" + research_md_or_empty)).hexdigest()[:16]
  canonicalize: strip leading/trailing whitespace; collapse internal whitespace runs to single space.

MODE: brainstorm — consultants return RAW (not the standard wrapper). Five-section schema.

Phase contract:
- Setup: slug derivation; existing-slug-dir prompt (overwrite/append-to-new-run/abort); Z_HARNESS_SLUG export; RUN id; mkdir; version stamp; brainstorm_run_start.
- Phase 1: doc-fetcher iff INDEX.json; optional Explore behind Z_HARNESS_BRAINSTORM_EXPLORE=1; RESEARCH.md ingestion (≤20KB inline; >20KB extractive summary stored to archive/<run>/research-summary-for-brainstorm.md).
- Phase 2: ONE message, three parallel Agent() — Claude(general-purpose, model=sonnet) + Codex + Gemini, identical scaffolding.
- Phase 3: parse 3 returns; <missing> for malformed; write BRAINSTORM.md with frontmatter; anti-bias section-by-section; orchestrator recommendation; AskUserQuestion with previews — option per framing + Restart + Abandon.
- Phase 4: persist chosen_framing; brainstorm_run_end; push-notify.

Failures: 1/3 proceed; 2/3 AskUserQuestion retry/proceed-with-1/abandon; 3/3 hard halt + total_ideator_failure event.
Restart: archive to archive/<run>/BRAINSTORM.md.previous-<N>; new RUN.
Abandon: status: abandoned in frontmatter; exit.
Cost guardrail ≤200K tokens, warn-and-continue.

Acceptance: command + skill files exist, diff = ONLY frontmatter + blank-line differences OR zero diff (matching z-plan pair).

Diff (primary artifact):

diff --git a/commands/z-brainstorm.md b/commands/z-brainstorm.md
new file mode 100644
index 0000000..22679ba
--- /dev/null
+++ b/commands/z-brainstorm.md
@@ -0,0 +1,288 @@
+---
+description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
+argument-hint: <topic to brainstorm> [--slug=<kebab>]
+---
+
+You are running the **z-harness `/z-brainstorm`** pipeline.
+
+Topic (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
+
+`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.
+
+## Setup
+
+1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
+2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
+   - **overwrite** — archive existing `BRAINSTORM.md` to `archive/<RUN>/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer) and start fresh
+   - **append-to-new-run** — keep `BRAINSTORM.md` in place but write this run's output to a fresh RUN-scoped path and ask the user later whether to promote it
+   - **abort** — exit cleanly with no changes
+3. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
+4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
+5. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
+6. **Version stamp + log run start:**
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
+   ```
+7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.
+
+**All paths live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/BRAINSTORM.md`
+- `z-harness/<slug>/archive/<RUN>/...`
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+---
+
+## Phase 1 — Scaffolding
+
+Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:
+
+### 1a. Doc-fetcher (if INDEX.json exists)
+
+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.
+
+### 1b. Optional Explore
+
+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Brainstorm scaffolding for <slug>",
+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
+)
+```
+
+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
+
+### 1c. RESEARCH.md ingestion
+
+If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, read it.
+
+- **≤20 KB:** inline the full content into the scaffolding payload.
+- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.
+
+Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
+
+### 1d. Assemble and hash
+
+Compute the `input_hash` per SPEC:
+
+```
+input_hash = sha256(canonicalize(
+    topic + "\n---\n" +
+    doc_fetcher_synthesis_or_empty + "\n---\n" +
+    explore_synthesis_or_empty + "\n---\n" +
+    research_md_or_summary_or_empty
+)).hexdigest()[:16]
+```
+
+`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.
+
+Checkpoint: write the assembled scaffolding to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/phase1-scaffolding.md`.
+
+---
+
+## Phase 2 — Parallel ideator dispatch
+
+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
+
+```
+Agent(
+  subagent_type="general-purpose",
+  model="sonnet",
+  description="Claude ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
+)
+Agent(
+  subagent_type="codex-consultant",
+  description="Codex ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
+)
+Agent(
+  subagent_type="gemini-consultant",
+  description="Gemini ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
+)
+```
+
+Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
+
+### Ideator failure policy
+
+Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.
+
+- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<vendor>:failed"` in the `ideators` frontmatter list. The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
+- **2/3 fail** → halt. Use `AskUserQuestion` with options:
+  - **retry** (default) — re-dispatch the failed ideators once
+  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
+  - **abandon** — set frontmatter `status: abandoned` and exit
+- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.
+
+Log every individual failure as `ideator_failed` regardless of the bucket above.
+
+---
+
+## Phase 3 — Synthesis + mandatory anti-bias check
+
+1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.
+
+2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.
+
+3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.
+
+4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:
+
+   ```yaml
+   ---
+   artifact: brainstorm
+   slug: <slug>
+   generated_at: <UTC ISO 8601>
+   command: /z-brainstorm <args>
+   input_hash: <16 hex from Phase 1d>
+   depends_on: [<RESEARCH.md if ingested>]
+   ideators:
+     - claude-sonnet
+     - codex
+     - gemini
+     # failed members recorded as "<vendor>:failed"
+   status: complete
+   ---
+   ```
+
+   Body sections, one block per ideator (in fixed order Claude → Codex → Gemini):
+
+   ```markdown
+   ## Framing: <ideator-name>
+
+   ### Framing
+   <one paragraph or `<missing>`>
+
+   ### Core hypothesis
+   <one paragraph or `<missing>`>
+
+   ### Risks
+   <bulleted list or `<missing>`>
+
+   ### Plan implications
+   <bulleted list or `<missing>`>
+
+   ### What would change my mind
+   <bulleted list or `<missing>`>
+   ```
+
+   Followed by:
+
+   ```markdown
+   ## Anti-bias check
+   <section-by-section comparison with explicit justification for any Claude-favoring pick>
+
+   ## Orchestrator recommendation
+   <one-line rationale; user is free to override>
+
+   ## User choice
+   <filled in Phase 4>
+   ```
+
+5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
+   - One option per available framing (e.g. **Claude framing**, **Codex framing**, **Gemini framing** — only for ideators that succeeded)
+   - **Restart** — discard this run and re-run with a refined topic
+   - **Abandon** — exit cleanly without finalizing
+
+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
+
+---
+
+## Phase 4 — Finalize
+
+Branch on the user's Phase 3 choice:
+
+### User picked a framing
+
+1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
+2. Append a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
+3. Confirm `status: complete` in the frontmatter.
+
+### User picked Restart
+
+1. Archive the just-written BRAINSTORM.md to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer).
+2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
+3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.
+
+### User picked Abandon
+
+1. Set the frontmatter `status: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
+2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.
+
+### In all branches
+
+Log `brainstorm_run_end`:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
+  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
+     "<complete|abandoned>" "<framing-or-empty>" "<N>")"
+```
+
+Push-notify (if policy ≠ `off`) with a next-step recommendation:
+
+```
+Brainstorm complete (framing: <chosen>).
+
+Recommended next:
+  /z-research <question>  — (optional) map terrain before planning
+  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
+```
+
+For the abandoned branch, the push notification just says "Brainstorm abandoned" with no next-step.
+
+---
+
+## Operating principles
+
+- **Cheap and parallel.** Three ideators in one message, no per-ideator round-trips.
+- **Identical scaffolding for all three.** No read-by-reference asymmetry.
+- **Anti-bias is mandatory.** Every Claude-favoring pick needs explicit justification.
+- **Failures degrade gracefully** — 1/3 proceeds, 2/3 asks, 3/3 halts.
+- **Restart is cheap.** Archive and loop, don't try to patch.
+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
+- **Log everything** via `scripts/log-event.sh`.
diff --git a/skills/z-brainstorm/SKILL.md b/skills/z-brainstorm/SKILL.md
new file mode 100644
index 0000000..22679ba
--- /dev/null
+++ b/skills/z-brainstorm/SKILL.md
@@ -0,0 +1,288 @@
+---
+description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
+argument-hint: <topic to brainstorm> [--slug=<kebab>]
+---
+
+You are running the **z-harness `/z-brainstorm`** pipeline.
+
+Topic (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
+
+`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.
+
+## Setup
+
+1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
+2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
+   - **overwrite** — archive existing `BRAINSTORM.md` to `archive/<RUN>/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer) and start fresh
+   - **append-to-new-run** — keep `BRAINSTORM.md` in place but write this run's output to a fresh RUN-scoped path and ask the user later whether to promote it
+   - **abort** — exit cleanly with no changes
+3. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
+4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
+5. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
+6. **Version stamp + log run start:**
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
+   ```
+7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.
+
+**All paths live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/BRAINSTORM.md`
+- `z-harness/<slug>/archive/<RUN>/...`
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+---
+
+## Phase 1 — Scaffolding
+
+Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:
+
+### 1a. Doc-fetcher (if INDEX.json exists)
+
+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.
+
+### 1b. Optional Explore
+
+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Brainstorm scaffolding for <slug>",
+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
+)
+```
+
+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
+
+### 1c. RESEARCH.md ingestion
+
+If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, read it.
+
+- **≤20 KB:** inline the full content into the scaffolding payload.
+- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.
+
+Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
+
+### 1d. Assemble and hash
+
+Compute the `input_hash` per SPEC:
+
+```
+input_hash = sha256(canonicalize(
+    topic + "\n---\n" +
+    doc_fetcher_synthesis_or_empty + "\n---\n" +
+    explore_synthesis_or_empty + "\n---\n" +
+    research_md_or_summary_or_empty
+)).hexdigest()[:16]
+```
+
+`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.
+
+Checkpoint: write the assembled scaffolding to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/phase1-scaffolding.md`.
+
+---
+
+## Phase 2 — Parallel ideator dispatch
+
+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
+
+```
+Agent(
+  subagent_type="general-purpose",
+  model="sonnet",
+  description="Claude ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
+)
+Agent(
+  subagent_type="codex-consultant",
+  description="Codex ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
+)
+Agent(
+  subagent_type="gemini-consultant",
+  description="Gemini ideator for <slug>",
+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
+)
+```
+
+Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
+
+### Ideator failure policy
+
+Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.
+
+- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<vendor>:failed"` in the `ideators` frontmatter list. The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
+- **2/3 fail** → halt. Use `AskUserQuestion` with options:
+  - **retry** (default) — re-dispatch the failed ideators once
+  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
+  - **abandon** — set frontmatter `status: abandoned` and exit
+- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.
+
+Log every individual failure as `ideator_failed` regardless of the bucket above.
+
+---
+
+## Phase 3 — Synthesis + mandatory anti-bias check
+
+1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.
+
+2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.
+
+3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.
+
+4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:
+
+   ```yaml
+   ---
+   artifact: brainstorm
+   slug: <slug>
+   generated_at: <UTC ISO 8601>
+   command: /z-brainstorm <args>
+   input_hash: <16 hex from Phase 1d>
+   depends_on: [<RESEARCH.md if ingested>]
+   ideators:
+     - claude-sonnet
+     - codex
+     - gemini
+     # failed members recorded as "<vendor>:failed"
+   status: complete
+   ---
+   ```
+
+   Body sections, one block per ideator (in fixed order Claude → Codex → Gemini):
+
+   ```markdown
+   ## Framing: <ideator-name>
+
+   ### Framing
+   <one paragraph or `<missing>`>
+
+   ### Core hypothesis
+   <one paragraph or `<missing>`>
+
+   ### Risks
+   <bulleted list or `<missing>`>
+
+   ### Plan implications
+   <bulleted list or `<missing>`>
+
+   ### What would change my mind
+   <bulleted list or `<missing>`>
+   ```
+
+   Followed by:
+
+   ```markdown
+   ## Anti-bias check
+   <section-by-section comparison with explicit justification for any Claude-favoring pick>
+
+   ## Orchestrator recommendation
+   <one-line rationale; user is free to override>
+
+   ## User choice
+   <filled in Phase 4>
+   ```
+
+5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
+   - One option per available framing (e.g. **Claude framing**, **Codex framing**, **Gemini framing** — only for ideators that succeeded)
+   - **Restart** — discard this run and re-run with a refined topic
+   - **Abandon** — exit cleanly without finalizing
+
+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
+
+---
+
+## Phase 4 — Finalize
+
+Branch on the user's Phase 3 choice:
+
+### User picked a framing
+
+1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
+2. Append a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
+3. Confirm `status: complete` in the frontmatter.
+
+### User picked Restart
+
+1. Archive the just-written BRAINSTORM.md to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer).
+2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
+3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.
+
+### User picked Abandon
+
+1. Set the frontmatter `status: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
+2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.
+
+### In all branches
+
+Log `brainstorm_run_end`:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
+  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
+     "<complete|abandoned>" "<framing-or-empty>" "<N>")"
+```
+
+Push-notify (if policy ≠ `off`) with a next-step recommendation:
+
+```
+Brainstorm complete (framing: <chosen>).
+
+Recommended next:
+  /z-research <question>  — (optional) map terrain before planning
+  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
+```
+
+For the abandoned branch, the push notification just says "Brainstorm abandoned" with no next-step.
+
+---
+
+## Operating principles
+
+- **Cheap and parallel.** Three ideators in one message, no per-ideator round-trips.
+- **Identical scaffolding for all three.** No read-by-reference asymmetry.
+- **Anti-bias is mandatory.** Every Claude-favoring pick needs explicit justification.
+- **Failures degrade gracefully** — 1/3 proceeds, 2/3 asks, 3/3 halts.
+- **Restart is cheap.** Archive and loop, don't try to patch.
+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
+- **Log everything** via `scripts/log-event.sh`.

Note: the command file and the skill file are byte-identical (verified by `diff` returning exit 0). This matches the z-plan pair convention.

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
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding.
- No re-stating code in the diff. No summaries. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus optional 1-line note).
