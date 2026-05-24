2026-05-22T16:52:18.339318Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T16:52:18.339403Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T16:52:18.339409Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e509a-1f25-7123-b632-c67fee8270bd
--------
user
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

codex
I’ll compare the new command against the existing `/z-plan` command/skill shape so the review is grounded in the repo’s actual conventions, then I’ll focus only on blockers and majors.
exec
/bin/zsh -lc "sed -n '1,260p' commands/z-plan.md" in /Users/zeke/dev/z-harness
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

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
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
10. **Pre-plan artifact detection.** Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

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

**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

The four resulting cases:
- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — RESEARCH.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

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
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.

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

The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:

```markdown
## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/<slug>/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | z-harness/<slug>/RESEARCH.md | <iso timestamp or "n/a"> |
```

If neither artifact was present, write: `none — fresh /z-plan run.`

Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.

## Phase 7 — Bundled final review

Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
- codex-consultant: same.

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md

Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.


exec
/bin/zsh -lc "sed -n '1,260p' skills/z-plan/SKILL.md" in /Users/zeke/dev/z-harness
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

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
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
10. **Pre-plan artifact detection.** Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

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

**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

The four resulting cases:
- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — RESEARCH.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

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
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.

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

The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:

```markdown
## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/<slug>/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | z-harness/<slug>/RESEARCH.md | <iso timestamp or "n/a"> |
```

If neither artifact was present, write: `none — fresh /z-plan run.`

Create `z-harness/$Z_HARNESS_SLUG/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.

## Phase 7 — Bundled final review

Spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md:
- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
- codex-consultant: same.

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md

Create `z-harness/$Z_HARNESS_SLUG/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.


exec
/bin/zsh -lc 'rg -n "codex-consultant|gemini-consultant|MODE: brainstorm|RAW|chosen_framing|AskUserQuestion|PushNotification|doc-fetcher|subagent_type" -S .' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./skills/z-maintain-docs/SKILL.md:45:  subagent_type="doc-updater",
./skills/z-maintain-docs/SKILL.md:59:  subagent_type="gemini-consultant",
./skills/z-maintain-docs/SKILL.md:64:  subagent_type="codex-consultant",
./skills/z-maintain-docs/SKILL.md:112:Ask via `AskUserQuestion`:
./skills/z-test/SKILL.md:17:4. Multiple → `AskUserQuestion` to pick.
./skills/z-test/SKILL.md:24:**Implementation-underway warning.** If TASKS.md already has any `[x]` rows, `AskUserQuestion`:
./skills/z-test/SKILL.md:63:**Brief user input.** Before drafting tests, `AskUserQuestion` (free-text):
./skills/z-test/SKILL.md:110:  subagent_type="gemini-consultant",
./skills/z-test/SKILL.md:112:  prompt="MODE: test-cases\n\nSPEC.md (verbatim):\n<contents>\n\nPLAN.md (verbatim):\n<contents>\n\nTASKS.md (verbatim):\n<contents>\n\nMy draft test cases (Phase 2):\n<contents of phase2-drafts.md>\n\nUser-stated concerns:\n<from Phase 1 AskUserQuestion>\n\nSource files referenced by the drafts (read these for real types/signatures):\n<list of abs paths>\n\nAsk:\n1. For each draft test: is the assertion strong enough to catch a real bug, or a tautology? If weak, propose a stronger assertion (be concrete).\n2. Which SPEC invariants do not yet have a corresponding test? Propose entries.\n3. What dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are not covered by my drafts?\n4. Flag any draft that is mechanically trivial (asserts what the implementation already obviously does) and recommend dropping it.\n5. Identify any draft whose target_file is in the wrong place (test framework convention mismatch).\n\nReturn structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries Claude missed."
./skills/z-test/SKILL.md:115:  subagent_type="codex-consultant",
./skills/z-test/SKILL.md:130:4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
./skills/z-test/SKILL.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./skills/z-test/SKILL.md:143:Present counts via `AskUserQuestion`:
./skills/z-test/SKILL.md:149:- **Edit subset** — orchestrator iterates each contested test (cross-LLM disagreement, or user-concern items) via per-test `AskUserQuestion`: keep / drop / modify (free-text).
./skills/z-test/SKILL.md:152:**Fixture-scaffolding gate.** For any accepted test whose `setup:` field requires non-trivial new test infrastructure (a new fixture file, a new mock framework, a new test-data generation step), get separate explicit approval via `AskUserQuestion`. Same discipline as `/z-plan` shortcuts: building new test infra without buy-in is a scope expansion.
./skills/z-test/SKILL.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./skills/z-test/SKILL.md:236:- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:4:   SPEC requires ideators to return exactly five sections for `/z-brainstorm` [SPEC.md:169](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:169), but later says both new consultant modes follow the existing consultant return shape with recommendation/reasoning/tradeoffs/etc. [SPEC.md:268](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:268). Existing consultants also hard-code that shape [agents/codex-consultant.md:49](/Users/zeke/dev/z-harness/agents/codex-consultant.md:49). An implementer could preserve consultant consistency and break brainstorm parsing, or preserve brainstorm parsing and violate the stated agent pattern.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:18:6. **`/z-plan` "optional doc-fetcher and Explore" may conflict with current Phase 1 rule.**  
./archive/plan-review/transcripts/001-codex-plan-review.response.md:19:   Existing `/z-plan` says "doc-fetcher FIRST, Explore for gaps" and spawns doc-fetcher if docs exist [commands/z-plan.md:90](/Users/zeke/dev/z-harness/commands/z-plan.md:90). SPEC says if fresh `RESEARCH.md` exists, doc-fetcher and Explore are optional [SPEC.md:296](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:296). That is a behavioral change, not just scaffolding, and the boundary between "research is enough" and "Phase 1 must still run" is vague.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:31:    New logs include `tokens_spent`, `ideator_durations_ms`, `consultant_durations_ms`, and `findings_count` [SPEC.md:191](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:191), [SPEC.md:250](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:250). Existing consultant logging has prompt/response chars and wall time, not token counts [agents/codex-consultant.md:81](/Users/zeke/dev/z-harness/agents/codex-consultant.md:81). Implementers may invent incompatible approximations.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:36:- The Claude ideator details are fragile: SPEC names `subagent_type="general-purpose"` and `model="sonnet"` [SPEC.md:179](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:179), but this repo's commands generally describe slash-command behavior for Claude Code, not portable subagent availability. That may be environment-specific command prose rather than durable framework behavior.
./skills/z-brainstorm/SKILL.md:12:**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./skills/z-brainstorm/SKILL.md:18:1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./skills/z-brainstorm/SKILL.md:19:2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./skills/z-brainstorm/SKILL.md:54:If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./skills/z-brainstorm/SKILL.md:58:# ... AskUserQuestion ...
./skills/z-brainstorm/SKILL.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./skills/z-brainstorm/SKILL.md:74:  subagent_type="doc-fetcher",
./skills/z-brainstorm/SKILL.md:88:  subagent_type="Explore",
./skills/z-brainstorm/SKILL.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./skills/z-brainstorm/SKILL.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./skills/z-brainstorm/SKILL.md:131:  subagent_type="general-purpose",
./skills/z-brainstorm/SKILL.md:134:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
./skills/z-brainstorm/SKILL.md:137:  subagent_type="codex-consultant",
./skills/z-brainstorm/SKILL.md:139:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./skills/z-brainstorm/SKILL.md:142:  subagent_type="gemini-consultant",
./skills/z-brainstorm/SKILL.md:144:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./skills/z-brainstorm/SKILL.md:148:Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
./skills/z-brainstorm/SKILL.md:155:- **2/3 fail** → halt. Use `AskUserQuestion` with options:
./skills/z-brainstorm/SKILL.md:226:5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
./skills/z-brainstorm/SKILL.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./skills/z-brainstorm/SKILL.md:241:1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
./skills/z-brainstorm/SKILL.md:248:2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
./skills/z-brainstorm/SKILL.md:262:  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./skills/z-brainstorm/SKILL.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./skills/z-improve/SKILL.md:20:- (empty) → list the 10 most recent runs across all slugs (via `ls -t z-harness/*/archive/* 2>/dev/null | head -10`) and `AskUserQuestion` to pick
./skills/z-improve/SKILL.md:57:| User-wait dominance | `sum(user_wait_end.wall_ms) / total run wall` | >40% — suggests too many `AskUserQuestion` blocks |
./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./skills/z-improve/SKILL.md:131:Present the proposals via `AskUserQuestion`. For EACH proposal separately (one question per proposal — do not batch multi-select for these, the user needs to evaluate them one at a time):
./agents/gemini-consultant.md:2:name: gemini-consultant
./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./skills/z-review-all/SKILL.md:13:2. Single candidate → use it. Multiple → `AskUserQuestion` to pick (or honor `--slug <slug>` argument). Zero → tell user nothing to review; stop.
./skills/z-review-all/SKILL.md:35:- If any `[ ]` (pending, not skip-flagged) exist → warn the user via `AskUserQuestion`:
./skills/z-review-all/SKILL.md:48:   - If that fails or returns nothing, fall back to `BASE_REF=$(git log --oneline | head -50 | grep -i "before z-plan\|baseline\|pre-z" | head -1 | awk '{print $1}')` and if still nothing, **ask the user** for the base ref via `AskUserQuestion`.
./skills/z-review-all/SKILL.md:121:  subagent_type="gemini-consultant",
./skills/z-review-all/SKILL.md:126:  subagent_type="codex-consultant",
./skills/z-review-all/SKILL.md:180:Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
./skills/z-review-all/SKILL.md:199:- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
./skills/z-stats/SKILL.md:14:4. Multiple → `AskUserQuestion` to pick.
./skills/z-stats/SKILL.md:99:| Debug plan with `POSTMORTEM.md` action items not yet tasked | "Convert post-mortem action items via the AskUserQuestion path documented in /z-debug Phase 7 (option C seeds a /z-test follow-up)" |
./skills/z-plan/SKILL.md:12:**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./skills/z-plan/SKILL.md:20:   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./skills/z-plan/SKILL.md:21:   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./skills/z-plan/SKILL.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./skills/z-plan/SKILL.md:44:   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./skills/z-plan/SKILL.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./skills/z-plan/SKILL.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./skills/z-plan/SKILL.md:71:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./skills/z-plan/SKILL.md:75:# ... AskUserQuestion ...
./skills/z-plan/SKILL.md:93:If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./skills/z-plan/SKILL.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./skills/z-plan/SKILL.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./skills/z-plan/SKILL.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./skills/z-plan/SKILL.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./skills/z-plan/SKILL.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./skills/z-plan/SKILL.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./skills/z-plan/SKILL.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./skills/z-plan/SKILL.md:120:  subagent_type="doc-fetcher",
./skills/z-plan/SKILL.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./skills/z-plan/SKILL.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./skills/z-plan/SKILL.md:142:  subagent_type="Explore",
./skills/z-plan/SKILL.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./skills/z-plan/SKILL.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./skills/z-plan/SKILL.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./skills/z-plan/SKILL.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./skills/z-plan/SKILL.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./skills/z-plan/SKILL.md:222:Use `AskUserQuestion` for explicit approval on:
./skills/z-plan/SKILL.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./skills/z-plan/SKILL.md:253:- codex-consultant: same.
./skills/z-plan/SKILL.md:261:**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./skills/z-plan/SKILL.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./skills/z-plan-light/SKILL.md:12:**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
./skills/z-plan-light/SKILL.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
./skills/z-plan-light/SKILL.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./skills/z-plan-light/SKILL.md:53:If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.
./skills/z-plan-light/SKILL.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./skills/z-plan-light/SKILL.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./skills/z-plan-light/SKILL.md:80:  subagent_type="gemini-consultant",
./skills/z-plan-light/SKILL.md:85:  subagent_type="codex-consultant",
./skills/z-plan-light/SKILL.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./skills/z-plan-light/SKILL.md:106:Present a brief synthesis (3-5 bullets) via `AskUserQuestion`:
./skills/z-plan-light/SKILL.md:111:For any flagged shortcut: separate explicit approval via `AskUserQuestion` (default to robust if not approved).
./skills/z-plan-light/SKILL.md:170:**Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
./skills/z-plan-light/SKILL.md:189:  subagent_type="codex-reviewer",
./skills/z-plan-light/SKILL.md:199:- **Second failure**: halt; `AskUserQuestion` — proceed anyway / patch manually / abandon.
./skills/z-research/SKILL.md:12:**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./skills/z-research/SKILL.md:22:   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./skills/z-research/SKILL.md:23:   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./skills/z-research/SKILL.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./skills/z-research/SKILL.md:58:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./skills/z-research/SKILL.md:62:# ... AskUserQuestion ...
./skills/z-research/SKILL.md:72:Present the cost up front via `AskUserQuestion` with three options:
./skills/z-research/SKILL.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./skills/z-research/SKILL.md:95:  subagent_type="doc-fetcher",
./skills/z-research/SKILL.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./skills/z-research/SKILL.md:123:  subagent_type="Explore",
./skills/z-research/SKILL.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./skills/z-research/SKILL.md:129:  subagent_type="Explore",
./skills/z-research/SKILL.md:135:  subagent_type="Explore",
./skills/z-research/SKILL.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./skills/z-research/SKILL.md:186:  subagent_type="gemini-consultant",
./skills/z-research/SKILL.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./skills/z-research/SKILL.md:191:  subagent_type="codex-consultant",
./skills/z-research/SKILL.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./skills/z-research/SKILL.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./archive/plan-review/transcripts/001-codex-plan-review.prompt.md:10:- Agent extensions: MODE: brainstorm and MODE: research-review added to codex-consultant and gemini-consultant.
./README.md:42:| `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
./README.md:43:| `codex-consultant` | (CLI) | Cross-LLM consult via Codex |
./README.md:60:- Claude Code with `PushNotification` available (for mobile notifications).
./README.md:97:- Skills that orchestrate should call cross-LLM consult (`gemini-consultant`, `codex-consultant`) at premise / red-team gates, not run them inline.
./README.md:135:│   ├── codex-consultant.md
./README.md:136:│   ├── gemini-consultant.md
./skills/z-debug/SKILL.md:12:**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.
./skills/z-debug/SKILL.md:16:1. **Derive slug** like `debug-<symptom-slug>` (e.g. "MLB doubleheaders mislabeled" → `debug-mlb-doubleheaders-mislabeled`). Confirm via `AskUserQuestion` if non-obvious or might collide.
./skills/z-debug/SKILL.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./skills/z-debug/SKILL.md:46:Ask clarifying questions via `AskUserQuestion`:
./skills/z-debug/SKILL.md:112:**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
./skills/z-debug/SKILL.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./skills/z-debug/SKILL.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./skills/z-debug/SKILL.md:142:  subagent_type="gemini-consultant",
./skills/z-debug/SKILL.md:147:  subagent_type="codex-consultant",
./skills/z-debug/SKILL.md:157:3. **Cross-LLM agreement** on top hypothesis = high-confidence; isolate that one first. **Disagreement** = surface to user via `AskUserQuestion`; let user pick the next experiment.
./skills/z-debug/SKILL.md:192:4. **Present + approve.** `AskUserQuestion` with the synthesized fix.
./skills/z-debug/SKILL.md:257:After writing, ask the user via `AskUserQuestion`:
./commands/z-review-all.md:13:2. Single candidate → use it. Multiple → `AskUserQuestion` to pick (or honor `--slug <slug>` argument). Zero → tell user nothing to review; stop.
./commands/z-review-all.md:35:- If any `[ ]` (pending, not skip-flagged) exist → warn the user via `AskUserQuestion`:
./commands/z-review-all.md:48:   - If that fails or returns nothing, fall back to `BASE_REF=$(git log --oneline | head -50 | grep -i "before z-plan\|baseline\|pre-z" | head -1 | awk '{print $1}')` and if still nothing, **ask the user** for the base ref via `AskUserQuestion`.
./commands/z-review-all.md:121:  subagent_type="gemini-consultant",
./commands/z-review-all.md:126:  subagent_type="codex-consultant",
./commands/z-review-all.md:180:Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
./commands/z-review-all.md:199:- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
./skills/z-init-docs/SKILL.md:14:   - **Both present** → ask the user via `AskUserQuestion`: "Docs exist — extend with new scope / overwrite specific concepts / abort".
./skills/z-init-docs/SKILL.md:68:Present the candidate list via `AskUserQuestion` (multi-select). Show: slug, source-file count, ~20-char summary. Cap at the user's pick.
./skills/z-init-docs/SKILL.md:78:For any concept where `docs/llm/<slug>.json` OR `docs/human/<slug>.md` already exists, ask the user via a SINGLE batched `AskUserQuestion`: "These N concepts already have docs. Overwrite / preserve / overwrite only LLM tier?" Default: preserve (do not overwrite without explicit consent).
./skills/z-init-docs/SKILL.md:86:  subagent_type="doc-updater",
./skills/z-init-docs/SKILL.md:225:- If a `doc-updater` returns `STATUS: not_enough_info`, surface to user (`AskUserQuestion`) and let them decide whether to drop that concept or provide more context.
./skills/z-amend/SKILL.md:12:**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./skills/z-amend/SKILL.md:23:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./skills/z-amend/SKILL.md:97:Show `amendment.md` to the user via `AskUserQuestion`:
./skills/z-amend/SKILL.md:103:If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./skills/z-amend/SKILL.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./skills/z-amend/SKILL.md:167:If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./commands/z-implement-next.md:18:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
./commands/z-implement-next.md:58:  subagent_type="implementer",
./commands/z-implement-next.md:80:  subagent_type="codex-reviewer",
./commands/z-implement-next.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./skills/z-implement-next/SKILL.md:18:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
./skills/z-implement-next/SKILL.md:58:  subagent_type="implementer",
./skills/z-implement-next/SKILL.md:80:  subagent_type="codex-reviewer",
./skills/z-implement-next/SKILL.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./skills/z-do/SKILL.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./skills/z-do/SKILL.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./skills/z-do/SKILL.md:12:**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.
./skills/z-do/SKILL.md:46:If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.
./skills/z-do/SKILL.md:50:## Phase 2 — Ground (doc-fetcher first)
./skills/z-do/SKILL.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./skills/z-do/SKILL.md:87:If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
./skills/z-do/SKILL.md:107:  subagent_type="codex-reviewer",
./skills/z-do/SKILL.md:117:- Second failure: `AskUserQuestion` — proceed anyway / patch manually / abandon.
./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./commands/z-amend.md:12:**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./commands/z-amend.md:23:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./commands/z-amend.md:97:Show `amendment.md` to the user via `AskUserQuestion`:
./commands/z-amend.md:103:If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./commands/z-amend.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./commands/z-amend.md:167:If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./agents/doc-fetcher.md:2:name: doc-fetcher
./skills/z-implement-all/SKILL.md:16:   - Multiple candidates → `AskUserQuestion` to pick.
./skills/z-implement-all/SKILL.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./skills/z-implement-all/SKILL.md:34:   - Otherwise ask the user once via `AskUserQuestion` for the run-command template, with placeholders `{TARGET_FILE}` and `{TEST_NAME}` (e.g. `pytest {TARGET_FILE} -k {TEST_NAME}`, or `cargo test --test {TEST_NAME}`). Cache to `$BASE/test-runner.json`:
./skills/z-implement-all/SKILL.md:48:4. **Halt semantics.** If one track returns `spec_problem` / `decision_needed` / `needs_clarification` / `unable_to_complete`, that *track* halts and you collect the question. **In-flight tracks for other tasks continue.** Only after the batch completes do you present the collected halts to the user (one `AskUserQuestion` per halt, in order).
./skills/z-implement-all/SKILL.md:95:When halting on a skip-flagged task, immediately push-notify (regardless of `Z_HARNESS_NOTIFY` value) and use `AskUserQuestion` with options:
./skills/z-implement-all/SKILL.md:142:  subagent_type="spec-precheck",
./skills/z-implement-all/SKILL.md:151:- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
./skills/z-implement-all/SKILL.md:173:  subagent_type="implementer",
./skills/z-implement-all/SKILL.md:188:  subagent_type="remote-runner",
./skills/z-implement-all/SKILL.md:197:- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
./skills/z-implement-all/SKILL.md:199:- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate. Record the decision in `$BASE/archive/$RUN/decisions-late.md`. After answer, re-spawn implementer.
./skills/z-implement-all/SKILL.md:212:  subagent_type="codex-reviewer",
./skills/z-implement-all/SKILL.md:225:If `NEW_HASH == OLD_HASH`, the implementer didn't actually change anything (it pushed back on the prior reviewer's findings rather than editing). **Do not spawn the reviewer.** Instead halt the track with reason `no_change_on_retry`, push-notify, and ask the user via `AskUserQuestion` whether to override (accept the unchanged diff) / patch manually / abandon. Saves one full Codex review cycle on stuck tasks.
./skills/z-implement-all/SKILL.md:234:  - **Second failure**: halt queue. Push-notify. Present diff + reviewer findings to user; await `AskUserQuestion` for "proceed anyway / patch manually / abandon task / re-spec".
./skills/z-implement-all/SKILL.md:253:  subagent_type="implementer",
./skills/z-implement-all/SKILL.md:273:  subagent_type="codex-reviewer",
./skills/z-implement-all/SKILL.md:306:- **Any test fails** → halt the track with `STATUS: test_failed`. Push-notify. Present the failure log to the user via `AskUserQuestion`:
./skills/z-implement-all/SKILL.md:383:For `decision_gate` (halted for user input), bracket the `AskUserQuestion` call with `start` (reason) / `end` (resolution). The helper auto-computes `wall_ms` so you get user-wait time for free.
./commands/z-skill-fix.md:12:**If empty** — use `AskUserQuestion` to ask "Which skill misled, and how?" before proceeding.
./commands/z-skill-fix.md:43:2. If multiple files plausibly match, use `AskUserQuestion` to disambiguate.
./commands/z-skill-fix.md:114:  subagent_type="codex-reviewer",
./commands/z-skill-fix.md:121:- **Blockers/majors** → re-edit. Re-run the reviewer once more. Second failure → halt with `AskUserQuestion` (proceed anyway / patch manually / abandon).
./commands/z-implement-all.md:16:   - Multiple candidates → `AskUserQuestion` to pick.
./commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./commands/z-implement-all.md:34:   - Otherwise ask the user once via `AskUserQuestion` for the run-command template, with placeholders `{TARGET_FILE}` and `{TEST_NAME}` (e.g. `pytest {TARGET_FILE} -k {TEST_NAME}`, or `cargo test --test {TEST_NAME}`). Cache to `$BASE/test-runner.json`:
./commands/z-implement-all.md:48:4. **Halt semantics.** If one track returns `spec_problem` / `decision_needed` / `needs_clarification` / `unable_to_complete`, that *track* halts and you collect the question. **In-flight tracks for other tasks continue.** Only after the batch completes do you present the collected halts to the user (one `AskUserQuestion` per halt, in order).
./commands/z-implement-all.md:95:When halting on a skip-flagged task, immediately push-notify (regardless of `Z_HARNESS_NOTIFY` value) and use `AskUserQuestion` with options:
./commands/z-implement-all.md:142:  subagent_type="spec-precheck",
./commands/z-implement-all.md:151:- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
./commands/z-implement-all.md:173:  subagent_type="implementer",
./commands/z-implement-all.md:188:  subagent_type="remote-runner",
./commands/z-implement-all.md:197:- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
./commands/z-implement-all.md:199:- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate. Record the decision in `$BASE/archive/$RUN/decisions-late.md`. After answer, re-spawn implementer.
./commands/z-implement-all.md:212:  subagent_type="codex-reviewer",
./commands/z-implement-all.md:225:If `NEW_HASH == OLD_HASH`, the implementer didn't actually change anything (it pushed back on the prior reviewer's findings rather than editing). **Do not spawn the reviewer.** Instead halt the track with reason `no_change_on_retry`, push-notify, and ask the user via `AskUserQuestion` whether to override (accept the unchanged diff) / patch manually / abandon. Saves one full Codex review cycle on stuck tasks.
./commands/z-implement-all.md:234:  - **Second failure**: halt queue. Push-notify. Present diff + reviewer findings to user; await `AskUserQuestion` for "proceed anyway / patch manually / abandon task / re-spec".
./commands/z-implement-all.md:253:  subagent_type="implementer",
./commands/z-implement-all.md:273:  subagent_type="codex-reviewer",
./commands/z-implement-all.md:306:- **Any test fails** → halt the track with `STATUS: test_failed`. Push-notify. Present the failure log to the user via `AskUserQuestion`:
./commands/z-implement-all.md:383:For `decision_gate` (halted for user input), bracket the `AskUserQuestion` call with `start` (reason) / `end` (resolution). The helper auto-computes `wall_ms` so you get user-wait time for free.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:46:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:70:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:96:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:118:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:128:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:131:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:133:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:137:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:154:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:160:+  subagent_type="Explore",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:163:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:205:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:229:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:255:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:286:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:292:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:301:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:304:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:306:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:310:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:327:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:334:+  subagent_type="Explore",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:337:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:434:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:445:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:519:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:525:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:530:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:589:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:631:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:642:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:716:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:722:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:727:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:786:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:884:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:895:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:969:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:975:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:980:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1039:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1081:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1092:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1166:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1172:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1177:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1236:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:22:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:61:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:75:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:113:6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.
./commands/z-improve.md:20:- (empty) → list the 10 most recent runs across all slugs (via `ls -t z-harness/*/archive/* 2>/dev/null | head -10`) and `AskUserQuestion` to pick
./commands/z-improve.md:57:| User-wait dominance | `sum(user_wait_end.wall_ms) / total run wall` | >40% — suggests too many `AskUserQuestion` blocks |
./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./commands/z-improve.md:131:Present the proposals via `AskUserQuestion`. For EACH proposal separately (one question per proposal — do not batch multi-select for these, the user needs to evaluate them one at a time):
./agents/codex-consultant.md:2:name: codex-consultant
./agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./commands/z-brainstorm.md:12:**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./commands/z-brainstorm.md:18:1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./commands/z-brainstorm.md:19:2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./commands/z-brainstorm.md:54:If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./commands/z-brainstorm.md:58:# ... AskUserQuestion ...
./commands/z-brainstorm.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./commands/z-brainstorm.md:74:  subagent_type="doc-fetcher",
./commands/z-brainstorm.md:88:  subagent_type="Explore",
./commands/z-brainstorm.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./commands/z-brainstorm.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./commands/z-brainstorm.md:131:  subagent_type="general-purpose",
./commands/z-brainstorm.md:134:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
./commands/z-brainstorm.md:137:  subagent_type="codex-consultant",
./commands/z-brainstorm.md:139:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./commands/z-brainstorm.md:142:  subagent_type="gemini-consultant",
./commands/z-brainstorm.md:144:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./commands/z-brainstorm.md:148:Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
./commands/z-brainstorm.md:155:- **2/3 fail** → halt. Use `AskUserQuestion` with options:
./commands/z-brainstorm.md:226:5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
./commands/z-brainstorm.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./commands/z-brainstorm.md:241:1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
./commands/z-brainstorm.md:248:2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
./commands/z-brainstorm.md:262:  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./commands/z-brainstorm.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:50:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:74:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:102:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:126:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:136:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:139:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:141:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:145:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:162:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:164:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:168:+  subagent_type="Explore",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:171:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:217:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:241:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:269:   subagent_type="implementer",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:302:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:308:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:317:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:320:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:322:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:326:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:343:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:346:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:350:+  subagent_type="Explore",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:353:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:450:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:461:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:535:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:541:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:560:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:562:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:605:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:647:+**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:658:+   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:732:+Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:738:+If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:757:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:759:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:802:+If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./commands/z-test.md:17:4. Multiple → `AskUserQuestion` to pick.
./commands/z-test.md:24:**Implementation-underway warning.** If TASKS.md already has any `[x]` rows, `AskUserQuestion`:
./commands/z-test.md:63:**Brief user input.** Before drafting tests, `AskUserQuestion` (free-text):
./commands/z-test.md:110:  subagent_type="gemini-consultant",
./commands/z-test.md:112:  prompt="MODE: test-cases\n\nSPEC.md (verbatim):\n<contents>\n\nPLAN.md (verbatim):\n<contents>\n\nTASKS.md (verbatim):\n<contents>\n\nMy draft test cases (Phase 2):\n<contents of phase2-drafts.md>\n\nUser-stated concerns:\n<from Phase 1 AskUserQuestion>\n\nSource files referenced by the drafts (read these for real types/signatures):\n<list of abs paths>\n\nAsk:\n1. For each draft test: is the assertion strong enough to catch a real bug, or a tautology? If weak, propose a stronger assertion (be concrete).\n2. Which SPEC invariants do not yet have a corresponding test? Propose entries.\n3. What dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are not covered by my drafts?\n4. Flag any draft that is mechanically trivial (asserts what the implementation already obviously does) and recommend dropping it.\n5. Identify any draft whose target_file is in the wrong place (test framework convention mismatch).\n\nReturn structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries Claude missed."
./commands/z-test.md:115:  subagent_type="codex-consultant",
./commands/z-test.md:130:4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
./commands/z-test.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./commands/z-test.md:143:Present counts via `AskUserQuestion`:
./commands/z-test.md:149:- **Edit subset** — orchestrator iterates each contested test (cross-LLM disagreement, or user-concern items) via per-test `AskUserQuestion`: keep / drop / modify (free-text).
./commands/z-test.md:152:**Fixture-scaffolding gate.** For any accepted test whose `setup:` field requires non-trivial new test infrastructure (a new fixture file, a new mock framework, a new test-data generation step), get separate explicit approval via `AskUserQuestion`. Same discipline as `/z-plan` shortcuts: building new test infra without buy-in is a scope expansion.
./commands/z-test.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./commands/z-test.md:236:- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.
./commands/z-init-docs.md:14:   - **Both present** → ask the user via `AskUserQuestion`: "Docs exist — extend with new scope / overwrite specific concepts / abort".
./commands/z-init-docs.md:68:Present the candidate list via `AskUserQuestion` (multi-select). Show: slug, source-file count, ~20-char summary. Cap at the user's pick.
./commands/z-init-docs.md:78:For any concept where `docs/llm/<slug>.json` OR `docs/human/<slug>.md` already exists, ask the user via a SINGLE batched `AskUserQuestion`: "These N concepts already have docs. Overwrite / preserve / overwrite only LLM tier?" Default: preserve (do not overwrite without explicit consent).
./commands/z-init-docs.md:86:  subagent_type="doc-updater",
./commands/z-init-docs.md:225:- If a `doc-updater` returns `STATUS: not_enough_info`, surface to user (`AskUserQuestion`) and let them decide whether to drop that concept or provide more context.
./commands/z-plan-light.md:12:**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
./commands/z-plan-light.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
./commands/z-plan-light.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./commands/z-plan-light.md:53:If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.
./commands/z-plan-light.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./commands/z-plan-light.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./commands/z-plan-light.md:80:  subagent_type="gemini-consultant",
./commands/z-plan-light.md:85:  subagent_type="codex-consultant",
./commands/z-plan-light.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./commands/z-plan-light.md:106:Present a brief synthesis (3-5 bullets) via `AskUserQuestion`:
./commands/z-plan-light.md:111:For any flagged shortcut: separate explicit approval via `AskUserQuestion` (default to robust if not approved).
./commands/z-plan-light.md:170:**Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
./commands/z-plan-light.md:189:  subagent_type="codex-reviewer",
./commands/z-plan-light.md:199:- **Second failure**: halt; `AskUserQuestion` — proceed anyway / patch manually / abandon.
./commands/z-stats.md:14:4. Multiple → `AskUserQuestion` to pick.
./commands/z-stats.md:99:| Debug plan with `POSTMORTEM.md` action items not yet tasked | "Convert post-mortem action items via the AskUserQuestion path documented in /z-debug Phase 7 (option C seeds a /z-test follow-up)" |
./commands/z-plan.md:12:**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./commands/z-plan.md:20:   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./commands/z-plan.md:21:   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./commands/z-plan.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./commands/z-plan.md:44:   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./commands/z-plan.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./commands/z-plan.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./commands/z-plan.md:71:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./commands/z-plan.md:75:# ... AskUserQuestion ...
./commands/z-plan.md:93:If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./commands/z-plan.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./commands/z-plan.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./commands/z-plan.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./commands/z-plan.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./commands/z-plan.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./commands/z-plan.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./commands/z-plan.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./commands/z-plan.md:120:  subagent_type="doc-fetcher",
./commands/z-plan.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./commands/z-plan.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./commands/z-plan.md:142:  subagent_type="Explore",
./commands/z-plan.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./commands/z-plan.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./commands/z-plan.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./commands/z-plan.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./commands/z-plan.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./commands/z-plan.md:222:Use `AskUserQuestion` for explicit approval on:
./commands/z-plan.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./commands/z-plan.md:253:- codex-consultant: same.
./commands/z-plan.md:261:**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./commands/z-plan.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./commands/z-audit.md:12:**If the target above is empty** — use `AskUserQuestion` to ask "What should I audit?" before proceeding. Do not invent.
./commands/z-audit.md:18:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
./commands/z-audit.md:33:7. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./commands/z-audit.md:54:If `$ARGUMENTS` supplied a target + the user already named dimensions in prose, skip ahead. Otherwise use `AskUserQuestion` to collect:
./commands/z-audit.md:78:  subagent_type="auditor",
./commands/z-audit.md:86:**If any auditor returns `unable_to_complete`** — surface the reason via `AskUserQuestion`: retry that dimension / skip it / abort the audit.
./commands/z-audit.md:129:  subagent_type="gemini-consultant",
./commands/z-audit.md:134:  subagent_type="codex-consultant",
./commands/z-audit.md:205:  subagent_type="codex-reviewer",
./commands/z-audit.md:212:- **Blockers** → re-edit the affected TASKS.md entries; re-run review once. Second failure → halt with `AskUserQuestion`.
./commands/z-audit.md:218:Send `PushNotification` (if policy != `off`): "Audit complete — <N> tasks queued."
./z-harness/brainstorm-and-research/SPEC.md:34:chosen_framing: claude | codex | gemini | restart
./z-harness/brainstorm-and-research/SPEC.md:69:<persisted post-AskUserQuestion>
./z-harness/brainstorm-and-research/SPEC.md:127:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/SPEC.md:129:- **Caller provides:** topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/SPEC.md:130:- **Consultant returns RAW** (not the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt` wrapper used by validation modes). The wrapper is for validation modes only. Brainstorm output is the five-section ideator block defined in BRAINSTORM.md body schema.
./z-harness/brainstorm-and-research/SPEC.md:141:- **Consultant returns RAW.** No standard wrapper.
./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/SPEC.md:153:  - Claude: `subagent_type="general-purpose", model="sonnet"`
./z-harness/brainstorm-and-research/SPEC.md:154:  - Codex: `codex-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/SPEC.md:155:  - Gemini: `gemini-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/SPEC.md:157:- **Phase 3 (Synthesis):** parse 3 returns; `<missing>` for malformed sections; write BRAINSTORM.md; anti-bias section-by-section comparison; orchestrator recommendation; `AskUserQuestion` with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/SPEC.md:162:- 2/3 fail → halt + `AskUserQuestion` retry/proceed-with-1/abandon (default: retry).
./z-harness/brainstorm-and-research/SPEC.md:174:- **Phase 0 (Cost-confirmation gate):** `AskUserQuestion` proceed / reduce-to-1-Explore / abandon. Log user's pick.
./z-harness/brainstorm-and-research/SPEC.md:175:- **Phase 1:** doc-fetcher dispatch iff INDEX.json exists.
./z-harness/brainstorm-and-research/SPEC.md:201:  - If any stale → `AskUserQuestion` warn the user before proceeding.
./z-harness/brainstorm-and-research/SPEC.md:203:- **Unfinalized brainstorm** (`status: complete` missing or `chosen_framing` absent): recommend `/z-brainstorm` re-run before proceeding.
./z-harness/brainstorm-and-research/SPEC.md:217:"If RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/SPEC.md:220:- Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/SPEC.md:244:- No doc-fetcher caching across precontext + plan runs (marked as v2 candidate; cheap enough today).
./commands/z-do.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./commands/z-do.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./commands/z-do.md:12:**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.
./commands/z-do.md:46:If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.
./commands/z-do.md:50:## Phase 2 — Ground (doc-fetcher first)
./commands/z-do.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./commands/z-do.md:87:If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
./commands/z-do.md:107:  subagent_type="codex-reviewer",
./commands/z-do.md:117:- Second failure: `AskUserQuestion` — proceed anyway / patch manually / abandon.
./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./commands/z-maintain-docs.md:45:  subagent_type="doc-updater",
./commands/z-maintain-docs.md:59:  subagent_type="gemini-consultant",
./commands/z-maintain-docs.md:64:  subagent_type="codex-consultant",
./commands/z-maintain-docs.md:112:Ask via `AskUserQuestion`:
./commands/z-research.md:12:**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./commands/z-research.md:22:   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./commands/z-research.md:23:   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./commands/z-research.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./commands/z-research.md:58:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./commands/z-research.md:62:# ... AskUserQuestion ...
./commands/z-research.md:72:Present the cost up front via `AskUserQuestion` with three options:
./commands/z-research.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./commands/z-research.md:95:  subagent_type="doc-fetcher",
./commands/z-research.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./commands/z-research.md:123:  subagent_type="Explore",
./commands/z-research.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./commands/z-research.md:129:  subagent_type="Explore",
./commands/z-research.md:135:  subagent_type="Explore",
./commands/z-research.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./commands/z-research.md:186:  subagent_type="gemini-consultant",
./commands/z-research.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./commands/z-research.md:191:  subagent_type="codex-consultant",
./commands/z-research.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./commands/z-research.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./commands/z-debug.md:12:**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.
./commands/z-debug.md:16:1. **Derive slug** like `debug-<symptom-slug>` (e.g. "MLB doubleheaders mislabeled" → `debug-mlb-doubleheaders-mislabeled`). Confirm via `AskUserQuestion` if non-obvious or might collide.
./commands/z-debug.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./commands/z-debug.md:46:Ask clarifying questions via `AskUserQuestion`:
./commands/z-debug.md:112:**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
./commands/z-debug.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./commands/z-debug.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./commands/z-debug.md:142:  subagent_type="gemini-consultant",
./commands/z-debug.md:147:  subagent_type="codex-consultant",
./commands/z-debug.md:157:3. **Cross-LLM agreement** on top hypothesis = high-confidence; isolate that one first. **Disagreement** = surface to user via `AskUserQuestion`; let user pick the next experiment.
./commands/z-debug.md:192:4. **Present + approve.** `AskUserQuestion` with the synthesized fix.
./commands/z-debug.md:257:After writing, ask the user via `AskUserQuestion`:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:37:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:76:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:90:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:128:6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:176:./agents/gemini-consultant.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:180:./agents/doc-fetcher.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:182:./agents/codex-consultant.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:211:./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:212:./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:213:./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:215:./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:223:./agents/gemini-consultant.md:5:model: haiku
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:241:./skills/z-plan/SKILL.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:245:./skills/z-plan/SKILL.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:246:./skills/z-plan/SKILL.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:249:./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:250:./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:277:./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:284:./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:285:./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:287:./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:304:./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:316:./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:328:./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:330:./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:331:./agents/doc-fetcher.md:5:model: haiku
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:334:./agents/codex-consultant.md:5:model: haiku
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:337:./commands/z-plan.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:341:./commands/z-plan.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:342:./commands/z-plan.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:375:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:405:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:416:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:417:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:419:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:420:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:427:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:428:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:430:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:431:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:433:./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:442:./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:443:./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:524:- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:542:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:557:  subagent_type="remote-runner",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:566:- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:568:- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate. Record the decision in `$BASE/archive/$RUN/decisions-late.md`. After answer, re-spawn implementer.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:581:  subagent_type="codex-reviewer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:594:If `NEW_HASH == OLD_HASH`, the implementer didn't actually change anything (it pushed back on the prior reviewer's findings rather than editing). **Do not spawn the reviewer.** Instead halt the track with reason `no_change_on_retry`, push-notify, and ask the user via `AskUserQuestion` whether to override (accept the unchanged diff) / patch manually / abandon. Saves one full Codex review cycle on stuck tasks.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:603:  - **Second failure**: halt queue. Push-notify. Present diff + reviewer findings to user; await `AskUserQuestion` for "proceed anyway / patch manually / abandon task / re-spec".
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:622:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:642:  subagent_type="codex-reviewer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:672:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:694:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:714:  subagent_type="codex-reviewer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:730:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:841:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:879:  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:899:  subagent_type="codex-reviewer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:915:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:932:**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:943:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1017:Show `amendment.md` to the user via `AskUserQuestion`:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1023:If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1028:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1042:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1044:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1087:If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1147:    56	  subagent_type="implementer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1167:    76	  subagent_type="codex-reviewer",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1183:    92	3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./brainstorm-and-research/escalation.md:8:- `/z-research <question>` — heavier doc-fetcher + Explore + cross-LLM perspective dump, no plan commitment.
./z-harness/brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./z-harness/brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./z-harness/brainstorm-and-research/TASKS.md:5:- [x] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**  (2 blockers + 1 major resolved cycle 2)
./z-harness/brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./z-harness/brainstorm-and-research/TASKS.md:16:- [x] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**  (reviewer clean)
./z-harness/brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./z-harness/brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/TASKS.md:36:    - Ideator failure handling: 1/3 fail → proceed; 2/3 fail → AskUserQuestion retry/proceed-with-1/abandon; 3/3 fail → hard halt with `total_ideator_failure` event.
./z-harness/brainstorm-and-research/TASKS.md:54:    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
./z-harness/brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./brainstorm-and-research/TASKS.md:36:    - Ideator failure handling: 1/3 fail → proceed; 2/3 fail → AskUserQuestion retry/proceed-with-1/abandon; 3/3 fail → hard halt with `total_ideator_failure` event.
./brainstorm-and-research/TASKS.md:54:    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
./brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:1:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:7:- Consultant returns RAW (not the standard Recommendation/Reasoning/Tradeoffs/Additional considerations/Raw excerpt wrapper).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:17:- Consultant returns RAW. No standard wrapper.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:26:- brainstorm: caller=topic+scaffolding; returns RAW 5-section block; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:27:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:33:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:36:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:39:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:45:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:49:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:85:- **A. Start of Phase 0 (Premise check).** Read the artifacts at the very top; let them inform the premise statement. Phase 1 (Exploration) skips doc-fetcher/Explore if RESEARCH.md is recent and complete.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:115:- **A. Neutral presentation.** AskUserQuestion with N framings as options, no orchestrator recommendation. User picks blind.
./brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./brainstorm-and-research/SPEC.md:69:<user-provided refinement notes from AskUserQuestion>
./brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./brainstorm-and-research/SPEC.md:148:1. Derive slug (auto from topic, or use `--slug=X` if provided). If slug dir exists with `BRAINSTORM.md` already, ask via AskUserQuestion: overwrite / append to a new run / abort.
./brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./brainstorm-and-research/SPEC.md:162:MODE: brainstorm
./brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./brainstorm-and-research/SPEC.md:179:Claude ideator uses subagent_type="general-purpose" (or a new "ideator" agent if we add one; see Open question O1 in PLAN.md) with `model="sonnet"`.
./brainstorm-and-research/SPEC.md:187:6. `AskUserQuestion` with previews — option per framing + "Restart with different topic framing" + "Abandon."
./brainstorm-and-research/SPEC.md:191:- `log-event.sh brainstorm_run_end` with `{status, tokens_spent, ideator_durations_ms, chosen_framing}`.
./brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./brainstorm-and-research/SPEC.md:226:Before any subagent dispatch, AskUserQuestion: "Research is the heaviest precontext command (target ≤2M tokens, up to 3 Explore subagents). Proceed?" Options: "Proceed" / "Reduce to 1 Explore" / "Abandon." Log user's pick.
./brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./brainstorm-and-research/SPEC.md:284:- For RESEARCH.md: parse the `Findings:` section for `file:line` citations; for each cited file, compare its `mtime` against RESEARCH.md's `generated_at`. If any source file is newer, log `precontext_stale` event and warn the user via `AskUserQuestion`: "Source files cited in RESEARCH.md were modified after the research was written. Continue, refresh `/z-research`, or abandon?" Default: continue (warned).
./brainstorm-and-research/SPEC.md:286:- If BOTH artifacts exist AND they contradict (e.g. RESEARCH lists a constraint that BRAINSTORM's chosen framing violates), surface via `AskUserQuestion`: "Detected potential conflict: <one-line description>. Reconcile, abandon, or proceed acknowledging the conflict?"
./brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./brainstorm-and-research/SPEC.md:304:- **Collision:** slug dir contains SPEC.md or PLAN.md. Prompt user via AskUserQuestion as today.
./brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./brainstorm-and-research/SPEC.md:363:- **2 of 3 fail:** halt + AskUserQuestion (retry all / proceed-with-1 / abandon). Default focus: retry.
./brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:30:Consultant returns RAW. Sections: Gaps, Errors, Missing constraints. Explicit prohibition: must NOT recommend an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:34:- Phase 0 (Cost-confirmation gate): AskUserQuestion proceed / reduce-to-1-Explore / abandon. Log user's pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:35:- Phase 1: doc-fetcher dispatch iff INDEX.json exists.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:48:  - Phase 0: AskUserQuestion proceed (~2M)/reduce/abandon. Log pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:49:  - Phase 1: doc-fetcher iff INDEX.json (ONE call). No Explore here.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:79:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:89:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:90:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:108:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:125:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:129:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:139:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:158:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:162:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:176:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:190:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:193:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:196:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:202:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:249:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:253:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:255:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:258:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:260:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:339:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:374:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:384:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:385:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:403:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:420:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:424:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:434:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:453:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:457:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:471:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:485:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:488:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:491:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:497:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:544:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:548:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:550:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:553:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:555:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.prompt.md:634:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:18:+**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:24:+1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:25:+2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:60:+If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:64:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:76:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:80:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:94:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:97:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:133:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:137:+  subagent_type="general-purpose",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:140:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:143:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:145:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:148:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:150:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:154:+Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:161:+- **2/3 fail** → halt. Use `AskUserQuestion` with options:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:232:+5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:237:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:247:+1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:254:+2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:268:+  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:293:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:312:+**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:318:+1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:319:+2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:354:+If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:358:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:370:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:374:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:388:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:391:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:427:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:431:+  subagent_type="general-purpose",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:434:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:437:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:439:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:442:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:444:+  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:448:+Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:455:+- **2/3 fail** → halt. Use `AskUserQuestion` with options:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:526:+5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:531:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:541:+1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:548:+2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:562:+  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:587:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:9:1. **Consultant return-shape conflict (Codex F1).** The existing consultant return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt) is for *validation* modes. The new `MODE: brainstorm` returns a 5-section ideator block; `MODE: research-review` returns a critique-block (gaps to fill / errors to correct / no recommendation). SPEC clarifies: these two new modes DO NOT use the standard wrapper. They return raw ideator/critique content. The wrapper exists for validation modes only.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:12:   - 2-of-3 fails → halt + `AskUserQuestion`: retry / proceed-with-1 / abandon. Default: retry.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:17:6. **Phase 1 boundary tightened (Codex F6).** Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set. Skip Explore iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:32:- **doc-fetcher caching (Gemini).** Out of scope, marked as v2 candidate. Cheap-enough today.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:21:3. MAJOR: Deleted-source citations emitted event but didn't trigger user warning. Fix required: AskUserQuestion warn-path coverage.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:31:... for line-ranges, use min-line mtime (any modification within range → stale). ... Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:34:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:35:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:38:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:41:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:43:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:47:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:48:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:50:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:36:    - Ideator failure handling: 1/3 fail → proceed; 2/3 fail → AskUserQuestion retry/proceed-with-1/abandon; 3/3 fail → hard halt with `total_ideator_failure` event.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:54:    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:4: diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:9: +++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:13: +name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:16:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:22:- Consultant returns RAW (not the standard Recommendation/Reasoning/Tradeoffs/Additional considerations/Raw excerpt wrapper).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:32:- Consultant returns RAW. No standard wrapper.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:41:- brainstorm: caller=topic+scaffolding; returns RAW 5-section block; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:42:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:48:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:51:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:54:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:60:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:64:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:95:/bin/zsh -lc "sed -n '1,220p' agents/codex-consultant.md" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:98:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:130:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:194:/bin/zsh -lc 'pwd && rg -n "brainstorm|research-review|Building the prompt|Returning to the caller|Archiving|standard return wrapper|Recommendation" agents/codex-consultant.md SPEC.md TASKS.md PLAN.md 2>/dev/null' in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:197:agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:199:agents/codex-consultant.md:48:## Building the prompt to Codex
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:200:agents/codex-consultant.md:60:## Returning to the caller
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:201:agents/codex-consultant.md:65:**Recommendation:** <Codex's pick>
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:202:agents/codex-consultant.md:79:## Archiving (required)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:207:/bin/zsh -lc "nl -ba agents/codex-consultant.md | sed -n '25,105p'" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:218:    34	- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:282:/bin/zsh -lc "git status --short && git diff -- agents/codex-consultant.md | sed -n '1,180p'" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:285: M agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:286: M agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:300:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:315:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:317:--- a/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:318:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:323:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:339:/bin/zsh -lc 'rg -n "research-review|brainstorm" agents/codex-consultant.md agents/gemini-consultant.md commands skills README.md' in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:342:agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:348:skills/z-brainstorm/SKILL.md:12:**If the topic above is empty**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:354:agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:356:commands/z-plan.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:359:commands/z-brainstorm.md:12:**If the topic above is empty**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:365:skills/z-plan/SKILL.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:371:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:373:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:375:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:379:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:381:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:383:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:1:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:7:- Consultant returns RAW (not the standard wrapper). The wrapper is for validation modes only. Brainstorm output is the five-section ideator block.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:17:- Consultant returns RAW. No standard wrapper.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:21:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:25:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:29:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:32:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:60:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:122:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:124:- brainstorm: "Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper ... Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section): 1.Framing 2.Core hypothesis 3.Risks 4.Plan implications 5.What would change my mind"
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:125:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:69:<user-provided refinement notes from AskUserQuestion>
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:148:1. Derive slug (auto from topic, or use `--slug=X` if provided). If slug dir exists with `BRAINSTORM.md` already, ask via AskUserQuestion: overwrite / append to a new run / abort.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:162:MODE: brainstorm
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:179:Claude ideator uses subagent_type="general-purpose" (or a new "ideator" agent if we add one; see Open question O1 in PLAN.md) with `model="sonnet"`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:187:6. `AskUserQuestion` with previews — option per framing + "Restart with different topic framing" + "Abandon."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:191:- `log-event.sh brainstorm_run_end` with `{status, tokens_spent, ideator_durations_ms, chosen_framing}`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:226:Before any subagent dispatch, AskUserQuestion: "Research is the heaviest precontext command (target ≤2M tokens, up to 3 Explore subagents). Proceed?" Options: "Proceed" / "Reduce to 1 Explore" / "Abandon." Log user's pick.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:284:- For RESEARCH.md: parse the `Findings:` section for `file:line` citations; for each cited file, compare its `mtime` against RESEARCH.md's `generated_at`. If any source file is newer, log `precontext_stale` event and warn the user via `AskUserQuestion`: "Source files cited in RESEARCH.md were modified after the research was written. Continue, refresh `/z-research`, or abandon?" Default: continue (warned).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:286:- If BOTH artifacts exist AND they contradict (e.g. RESEARCH lists a constraint that BRAINSTORM's chosen framing violates), surface via `AskUserQuestion`: "Detected potential conflict: <one-line description>. Reconcile, abandon, or proceed acknowledging the conflict?"
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:304:- **Collision:** slug dir contains SPEC.md or PLAN.md. Prompt user via AskUserQuestion as today.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:363:- **2 of 3 fail:** halt + AskUserQuestion (retry all / proceed-with-1 / abandon). Default focus: retry.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:17:  - If any stale → `AskUserQuestion` warn the user before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:19:- **Unfinalized brainstorm** (`status: complete` missing or `chosen_framing` absent): recommend `/z-brainstorm` re-run before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:28:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:62:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:70:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:71:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:88:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:94:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:96:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:98:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:121:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:125:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:143:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:151:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:152:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:155:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:157:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:159:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:161:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:165:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:181:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:183:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:187:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:190:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:239:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:245:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:246:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:263:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:267:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:297:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:298:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:306:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:332:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:373:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:381:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:382:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:399:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:405:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:407:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:409:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:432:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:436:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:454:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:462:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:463:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:466:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:468:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:470:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:472:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:476:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:492:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:494:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:498:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:501:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:550:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:556:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:557:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:574:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:578:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:608:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:609:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:617:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:643:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:3:No `docs/llm/INDEX.json` in z-harness repo (it's a meta-harness, agent/command markdown files ARE the docs). doc-fetcher skipped. No Explore dispatched — main thread already has the relevant context from prior /z-plan-light runs in this conversation.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:7:The z-harness plugin lives at `/Users/zeke/dev/z-harness/` with parallel `commands/` and `skills/` directories — each slash command is hand-maintained as both a `commands/<name>.md` and a `skills/<name>/SKILL.md` mirror. New commands must be authored twice. The `agents/` directory holds subagent definitions; `codex-consultant.md` and `gemini-consultant.md` already implement a multi-mode pattern with `MODE:` discriminator (existing modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-audit`, `test-cases`). Adding `MODE: brainstorm` (ideation) and possibly `MODE: research-review` (research-note critique) fits the existing pattern. The `Explore` subagent (built into the harness) is dispatched via `Agent(subagent_type="Explore", model="haiku", ...)` and the `doc-fetcher` (Haiku) reads `docs/llm/` two-tier docs cheaply. `/z-plan` Phase 0 is the premise-check entry point — that's where seed-artifact (BRAINSTORM.md / RESEARCH.md) detection will hook in. `scripts/log-event.sh` accepts `$RUN` and `$Z_HARNESS_SLUG` and writes to `z-harness/<slug>/archive/<run>/events.jsonl`; new commands will follow the same convention. Slug derivation today is per-command (each `/z-plan` and `/z-plan-light` derives independently); a chain of `/z-research` → `/z-brainstorm` → `/z-plan` raises a slug-sharing question.
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:16:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:22:- Consultant returns RAW (not the standard wrapper). The wrapper is for validation modes only. Brainstorm output is the five-section ideator block.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:32:- Consultant returns RAW. No standard wrapper.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:36:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:40:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:44:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:47:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:75:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:137:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:139:- brainstorm: "Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper ... Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section): 1.Framing 2.Core hypothesis 3.Risks 4.Plan implications 5.What would change my mind"
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:140:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:1:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase0-premise.md:17:Build two opt-in slash commands that the user invokes when they explicitly want pre-plan exploration. `/z-brainstorm` is a cheap fan-out across model vendors (Claude / Codex / Gemini) producing N candidate problem-framings; the user picks one. `/z-research` is a heavier terrain-mapping pass using doc-fetcher + Explore + cross-LLM critique that produces a findings note with no recommendation. Both are chainable into `/z-plan` (which reads their artifacts as Phase-0 seed context).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:11:Consultant subagents (codex-consultant, gemini-consultant) are multi-mode, discriminated by MODE: <name> prefix. Modes are fully isolated — different return shapes, different prompting.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:15:- Phase 1: Exploration (2-tier: doc-fetcher Haiku first, then Explore for gaps; capped at 3 Explores per run)
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:92:1. Consultant subagents (codex-consultant.md, gemini-consultant.md) declare MODE: at the top of the caller's prompt. Each mode has its own return shape, prompt structure, and archive naming.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:100:3. The two-tier docs (docs/llm/INDEX.json + docs/llm/<concept>.json) are read by doc-fetcher (Haiku) in Phase 1, never by the main orchestrator thread.
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:1:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:5:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:8:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:36:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:6:3. MAJOR: Deleted-source citations emitted event but didn't trigger user warning. Fix required: AskUserQuestion warn-path coverage.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:16:... for line-ranges, use min-line mtime (any modification within range → stale). ... Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:19:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:20:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:23:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:26:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:28:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:32:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:33:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:35:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.prompt.md:9:- Consultant subagents (`codex-consultant`, `gemini-consultant`) are multi-mode with a `MODE: <name>` discriminator.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:18:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:26:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:27:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:50:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:52:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:54:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:77:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:81:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:99:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:107:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:108:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:111:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:113:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:115:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:117:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:121:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:137:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:139:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:143:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:146:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:195:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:201:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:202:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:219:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:223:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:253:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:254:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:262:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:288:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:329:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:337:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:338:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:355:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:361:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:363:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:365:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:388:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:392:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:410:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:418:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:419:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:422:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:424:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:426:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:428:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:432:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:448:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:450:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:454:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:457:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:506:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:512:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:513:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:530:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:534:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:564:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:565:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:573:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:599:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:45:Consultant returns RAW. Sections: Gaps, Errors, Missing constraints. Explicit prohibition: must NOT recommend an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:49:- Phase 0 (Cost-confirmation gate): AskUserQuestion proceed / reduce-to-1-Explore / abandon. Log user's pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:50:- Phase 1: doc-fetcher dispatch iff INDEX.json exists.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:63:  - Phase 0: AskUserQuestion proceed (~2M)/reduce/abandon. Log pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:64:  - Phase 1: doc-fetcher iff INDEX.json (ONE call). No Explore here.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:94:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:104:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:105:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:123:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:140:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:144:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:154:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:173:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:177:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:191:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:205:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:208:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:211:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:217:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:264:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:268:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:270:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:273:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:275:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:354:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:389:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:399:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:400:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:418:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:435:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:439:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:449:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:468:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:472:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:486:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:500:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:503:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:506:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:512:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:559:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:563:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:565:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:568:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:570:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:649:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:688:I’ll check the existing `/z-brainstorm` command and nearby consultant/doc-fetcher conventions so the review is grounded in the current harness behavior, not just the pasted diff.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:703:**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:709:1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:710:2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:745:If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:749:# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:761:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:765:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:779:  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:782:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:818:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:822:  subagent_type="general-purpose",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:825:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:828:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:830:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:833:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:835:  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:839:Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:846:- **2/3 fail** → halt. Use `AskUserQuestion` with options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:917:5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:922:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:932:1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:939:2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:985:./agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:988:./agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:990:./agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1042:/bin/zsh -lc 'rg -n "research-review|brainstorm-review|gemini-consultant|codex-consultant|doc-fetcher|PushNotification|phase_end|cost_gate|input_hash|research_run" -S .' in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1044:./skills/z-review-all/SKILL.md:121:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1045:./skills/z-review-all/SKILL.md:126:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1047:./skills/z-research/SKILL.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1050:./skills/z-research/SKILL.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1051:./skills/z-research/SKILL.md:95:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1052:./skills/z-research/SKILL.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1053:./skills/z-research/SKILL.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1054:./skills/z-research/SKILL.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1055:./skills/z-research/SKILL.md:186:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1056:./skills/z-research/SKILL.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1057:./skills/z-research/SKILL.md:191:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1058:./skills/z-research/SKILL.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1063:./skills/z-research/SKILL.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1064:./skills/z-debug/SKILL.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1065:./skills/z-debug/SKILL.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1066:./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1067:./skills/z-debug/SKILL.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1068:./skills/z-debug/SKILL.md:142:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1069:./skills/z-debug/SKILL.md:147:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1071:./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1072:./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1073:./skills/z-do/SKILL.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1074:./skills/z-do/SKILL.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1075:./skills/z-do/SKILL.md:50:## Phase 2 — Ground (doc-fetcher first)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1076:./skills/z-do/SKILL.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1077:./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1078:./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1080:./skills/z-brainstorm/SKILL.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1081:./skills/z-brainstorm/SKILL.md:74:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1082:./skills/z-brainstorm/SKILL.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1085:./skills/z-brainstorm/SKILL.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1086:./skills/z-brainstorm/SKILL.md:137:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1087:./skills/z-brainstorm/SKILL.md:142:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1089:./skills/z-brainstorm/SKILL.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1090:./skills/z-brainstorm/SKILL.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1091:./skills/z-maintain-docs/SKILL.md:59:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1092:./skills/z-maintain-docs/SKILL.md:64:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1093:./agents/gemini-consultant.md:2:name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1094:./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1095:./agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1096:./skills/z-implement-next/SKILL.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1097:./agents/codex-consultant.md:2:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1098:./agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1099:./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1100:./agents/codex-consultant.md:64:     - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1101:./agents/codex-consultant.md:87:For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1102:./skills/z-implement-all/SKILL.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1103:./skills/z-plan/SKILL.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1106:./skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1107:./skills/z-plan/SKILL.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1108:./skills/z-plan/SKILL.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1109:./skills/z-plan/SKILL.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1110:./skills/z-plan/SKILL.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1111:./skills/z-plan/SKILL.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1112:./skills/z-plan/SKILL.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1113:./skills/z-plan/SKILL.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1114:./skills/z-plan/SKILL.md:120:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1115:./skills/z-plan/SKILL.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1116:./skills/z-plan/SKILL.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1117:./skills/z-plan/SKILL.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1118:./skills/z-plan/SKILL.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1119:./skills/z-plan/SKILL.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1120:./skills/z-plan/SKILL.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1121:./skills/z-plan/SKILL.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1122:./skills/z-plan/SKILL.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1123:./skills/z-plan/SKILL.md:253:- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1124:./skills/z-plan/SKILL.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1125:./archive/plan-review/transcripts/001-codex-plan-review.response.md:4:   SPEC requires ideators to return exactly five sections for `/z-brainstorm` [SPEC.md:169](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:169), but later says both new consultant modes follow the existing consultant return shape with recommendation/reasoning/tradeoffs/etc. [SPEC.md:268](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:268). Existing consultants also hard-code that shape [agents/codex-consultant.md:49](/Users/zeke/dev/z-harness/agents/codex-consultant.md:49). An implementer could preserve consultant consistency and break brainstorm parsing, or preserve brainstorm parsing and violate the stated agent pattern.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1126:./archive/plan-review/transcripts/001-codex-plan-review.response.md:18:6. **`/z-plan` "optional doc-fetcher and Explore" may conflict with current Phase 1 rule.**  
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1127:./archive/plan-review/transcripts/001-codex-plan-review.response.md:19:   Existing `/z-plan` says "doc-fetcher FIRST, Explore for gaps" and spawns doc-fetcher if docs exist [commands/z-plan.md:90](/Users/zeke/dev/z-harness/commands/z-plan.md:90). SPEC says if fresh `RESEARCH.md` exists, doc-fetcher and Explore are optional [SPEC.md:296](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:296). That is a behavioral change, not just scaffolding, and the boundary between "research is enough" and "Phase 1 must still run" is vague.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1128:./archive/plan-review/transcripts/001-codex-plan-review.response.md:31:    New logs include `tokens_spent`, `ideator_durations_ms`, `consultant_durations_ms`, and `findings_count` [SPEC.md:191](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:191), [SPEC.md:250](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:250). Existing consultant logging has prompt/response chars and wall time, not token counts [agents/codex-consultant.md:81](/Users/zeke/dev/z-harness/agents/codex-consultant.md:81). Implementers may invent incompatible approximations.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1129:./skills/z-plan-light/SKILL.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1130:./skills/z-plan-light/SKILL.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1131:./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1132:./skills/z-plan-light/SKILL.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1133:./skills/z-plan-light/SKILL.md:80:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1134:./skills/z-plan-light/SKILL.md:85:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1135:./skills/z-plan-light/SKILL.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1136:./skills/z-test/SKILL.md:110:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1137:./skills/z-test/SKILL.md:115:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1138:./skills/z-test/SKILL.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1139:./skills/z-test/SKILL.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1140:./archive/plan-review/transcripts/001-codex-plan-review.prompt.md:10:- Agent extensions: MODE: brainstorm and MODE: research-review added to codex-consultant and gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1141:./commands/z-review-all.md:121:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1142:./commands/z-review-all.md:126:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1143:./agents/doc-fetcher.md:2:name: doc-fetcher
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1144:./skills/z-amend/SKILL.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1145:./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1146:./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1147:./brainstorm-and-research/escalation.md:8:- `/z-research <question>` — heavier doc-fetcher + Explore + cross-LLM perspective dump, no plan commitment.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1149:./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1150:./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1151:./commands/z-implement-next.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1152:./brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1153:./brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1155:./brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1156:./brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1157:./brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1158:./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1159:./brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1160:./brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1162:./brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1163:./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1165:./brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1167:./brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1168:./commands/z-debug.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1169:./commands/z-debug.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1170:./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1171:./commands/z-debug.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1172:./commands/z-debug.md:142:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1173:./commands/z-debug.md:147:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1178:./z-harness/brainstorm-and-research/SPEC.md:127:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1179:./z-harness/brainstorm-and-research/SPEC.md:129:- **Caller provides:** topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1181:./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1182:./z-harness/brainstorm-and-research/SPEC.md:154:  - Codex: `codex-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1183:./z-harness/brainstorm-and-research/SPEC.md:155:  - Gemini: `gemini-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1185:./z-harness/brainstorm-and-research/SPEC.md:175:- **Phase 1:** doc-fetcher dispatch iff INDEX.json exists.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1188:./z-harness/brainstorm-and-research/SPEC.md:217:"If RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1189:./z-harness/brainstorm-and-research/SPEC.md:220:- Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1191:./z-harness/brainstorm-and-research/SPEC.md:244:- No doc-fetcher caching across precontext + plan runs (marked as v2 candidate; cheap enough today).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1192:./commands/z-plan-light.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1193:./commands/z-plan-light.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1194:./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1195:./commands/z-plan-light.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1196:./commands/z-plan-light.md:80:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1197:./commands/z-plan-light.md:85:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1198:./commands/z-plan-light.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1199:./brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1200:./brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1201:./brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1202:./brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1204:./brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1205:./brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1206:./brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1207:./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1208:./brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1209:./brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1210:./brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1212:./brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1214:./brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1216:./brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1217:./brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1218:./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1220:./brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1221:./brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1222:./brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1227:./brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1229:./brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1230:./brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1231:./commands/z-plan.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1234:./commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1235:./commands/z-plan.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1236:./commands/z-plan.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1237:./commands/z-plan.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1238:./commands/z-plan.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1239:./commands/z-plan.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1240:./commands/z-plan.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1241:./commands/z-plan.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1242:./commands/z-plan.md:120:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1243:./commands/z-plan.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1244:./commands/z-plan.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1245:./commands/z-plan.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1246:./commands/z-plan.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1247:./commands/z-plan.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1248:./commands/z-plan.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1249:./commands/z-plan.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1250:./commands/z-plan.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1251:./commands/z-plan.md:253:- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1252:./commands/z-plan.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1253:./commands/z-amend.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1254:./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1255:./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1256:./commands/z-do.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1257:./commands/z-do.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1258:./commands/z-do.md:50:## Phase 2 — Ground (doc-fetcher first)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1259:./commands/z-do.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1260:./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1261:./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1263:./z-harness/brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1264:./z-harness/brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1266:./brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1267:./brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1268:./commands/z-maintain-docs.md:59:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1269:./commands/z-maintain-docs.md:64:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1271:./commands/z-research.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1274:./commands/z-research.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1275:./commands/z-research.md:95:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1276:./commands/z-research.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1277:./commands/z-research.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1278:./commands/z-research.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1279:./commands/z-research.md:186:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1280:./commands/z-research.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1281:./commands/z-research.md:191:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1282:./commands/z-research.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1287:./commands/z-research.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1289:./commands/z-brainstorm.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1290:./commands/z-brainstorm.md:74:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1291:./commands/z-brainstorm.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1294:./commands/z-brainstorm.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1295:./commands/z-brainstorm.md:137:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1296:./commands/z-brainstorm.md:142:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1298:./commands/z-brainstorm.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1299:./commands/z-brainstorm.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1300:./z-harness/brainstorm-and-research/TASKS.md:5:- [x] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**  (2 blockers + 1 major resolved cycle 2)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1301:./z-harness/brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1303:./z-harness/brainstorm-and-research/TASKS.md:16:- [x] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**  (reviewer clean)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1304:./z-harness/brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1305:./z-harness/brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1306:./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1307:./z-harness/brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1308:./z-harness/brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1310:./z-harness/brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1311:./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1313:./z-harness/brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1315:./z-harness/brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1316:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:118:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1317:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:128:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1318:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:131:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1319:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:133:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1320:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:137:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1321:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:154:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1322:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1323:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:163:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1324:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:286:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1325:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:301:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1326:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:304:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1327:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:306:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1328:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:310:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1329:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:327:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1330:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1331:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:337:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1332:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:530:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1333:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1334:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1335:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:727:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1336:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1337:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1338:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:980:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1339:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1340:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1341:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1177:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1342:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1343:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1344:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:85:- **A. Start of Phase 0 (Premise check).** Read the artifacts at the very top; let them inform the premise statement. Phase 1 (Exploration) skips doc-fetcher/Explore if RESEARCH.md is recent and complete.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1348:./commands/z-test.md:110:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1349:./commands/z-test.md:115:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1350:./commands/z-test.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1351:./commands/z-test.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1352:./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:22:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1353:./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:113:6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1354:./commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1355:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:9:1. **Consultant return-shape conflict (Codex F1).** The existing consultant return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt) is for *validation* modes. The new `MODE: brainstorm` returns a 5-section ideator block; `MODE: research-review` returns a critique-block (gaps to fill / errors to correct / no recommendation). SPEC clarifies: these two new modes DO NOT use the standard wrapper. They return raw ideator/critique content. The wrapper exists for validation modes only.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1356:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:17:6. **Phase 1 boundary tightened (Codex F6).** Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set. Skip Explore iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1358:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:32:- **doc-fetcher caching (Gemini).** Out of scope, marked as v2 candidate. Cheap-enough today.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1359:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1360:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1362:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1363:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1364:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1365:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1366:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1367:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1369:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1370:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1372:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1374:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1376:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase0-premise.md:17:Build two opt-in slash commands that the user invokes when they explicitly want pre-plan exploration. `/z-brainstorm` is a cheap fan-out across model vendors (Claude / Codex / Gemini) producing N candidate problem-framings; the user picks one. `/z-research` is a heavier terrain-mapping pass using doc-fetcher + Explore + cross-LLM critique that produces a findings note with no recommendation. Both are chainable into `/z-plan` (which reads their artifacts as Phase-0 seed context).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1377:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:3:No `docs/llm/INDEX.json` in z-harness repo (it's a meta-harness, agent/command markdown files ARE the docs). doc-fetcher skipped. No Explore dispatched — main thread already has the relevant context from prior /z-plan-light runs in this conversation.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1378:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:7:The z-harness plugin lives at `/Users/zeke/dev/z-harness/` with parallel `commands/` and `skills/` directories — each slash command is hand-maintained as both a `commands/<name>.md` and a `skills/<name>/SKILL.md` mirror. New commands must be authored twice. The `agents/` directory holds subagent definitions; `codex-consultant.md` and `gemini-consultant.md` already implement a multi-mode pattern with `MODE:` discriminator (existing modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-audit`, `test-cases`). Adding `MODE: brainstorm` (ideation) and possibly `MODE: research-review` (research-note critique) fits the existing pattern. The `Explore` subagent (built into the harness) is dispatched via `Agent(subagent_type="Explore", model="haiku", ...)` and the `doc-fetcher` (Haiku) reads `docs/llm/` two-tier docs cheaply. `/z-plan` Phase 0 is the premise-check entry point — that's where seed-artifact (BRAINSTORM.md / RESEARCH.md) detection will hook in. `scripts/log-event.sh` accepts `$RUN` and `$Z_HARNESS_SLUG` and writes to `z-harness/<slug>/archive/<run>/events.jsonl`; new commands will follow the same convention. Slug derivation today is per-command (each `/z-plan` and `/z-plan-light` derives independently); a chain of `/z-research` → `/z-brainstorm` → `/z-plan` raises a slug-sharing question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1379:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1380:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1381:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1382:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1384:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1385:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1386:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1387:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1388:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1389:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1390:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1392:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1394:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1396:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1397:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1398:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1400:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1401:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1402:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1407:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1409:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1410:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1411:./commands/z-audit.md:33:7. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1412:./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1413:./commands/z-audit.md:129:  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1414:./commands/z-audit.md:134:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1415:./commands/z-audit.md:218:Send `PushNotification` (if policy != `off`): "Audit complete — <N> tasks queued."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1416:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:126:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1417:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:136:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1418:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:139:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1419:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:141:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1420:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:145:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1421:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:162:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1422:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:164:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1423:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:171:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1424:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:302:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1425:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:317:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1426:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:320:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1427:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:322:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1428:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:326:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1429:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:343:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1430:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:346:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1431:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:353:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1432:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1433:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:560:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1434:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:562:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1435:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1436:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:757:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1437:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:759:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1438:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:37:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1439:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:128:6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1440:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:176:./agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1441:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:180:./agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1442:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:182:./agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1443:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:211:./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1444:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:212:./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1445:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:213:./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1446:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:215:./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1447:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:223:./agents/gemini-consultant.md:5:model: haiku
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1448:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:241:./skills/z-plan/SKILL.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1449:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:245:./skills/z-plan/SKILL.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1450:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:246:./skills/z-plan/SKILL.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1451:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:249:./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1452:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:250:./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1453:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:277:./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1454:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:284:./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1455:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:285:./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1456:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:287:./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1457:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:304:./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1458:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:316:./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1459:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:328:./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1460:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:330:./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1461:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:331:./agents/doc-fetcher.md:5:model: haiku
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1462:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:334:./agents/codex-consultant.md:5:model: haiku
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1463:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:337:./commands/z-plan.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1464:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:341:./commands/z-plan.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1465:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:342:./commands/z-plan.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1466:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:375:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1467:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:405:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1468:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:416:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1469:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:417:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1470:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:419:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1471:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:420:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1472:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:427:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1473:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:428:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1474:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:430:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1475:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:431:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1476:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:433:./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1477:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:442:./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1478:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:443:./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1479:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:672:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1480:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:730:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1481:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:915:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1482:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1028:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1483:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1042:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1484:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1044:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1485:./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1183:    92	3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1486:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:1:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1487:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1488:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1491:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:27:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1493:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:33:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1494:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:36:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1495:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:39:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1496:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:45:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1497:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:49:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1498:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1500:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:11:Consultant subagents (codex-consultant, gemini-consultant) are multi-mode, discriminated by MODE: <name> prefix. Modes are fully isolated — different return shapes, different prompting.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1501:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:15:- Phase 1: Exploration (2-tier: doc-fetcher Haiku first, then Explore for gaps; capped at 3 Explores per run)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1502:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:92:1. Consultant subagents (codex-consultant.md, gemini-consultant.md) declare MODE: at the top of the caller's prompt. Each mode has its own return shape, prompt structure, and archive naming.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1503:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:100:3. The two-tier docs (docs/llm/INDEX.json + docs/llm/<concept>.json) are read by doc-fetcher (Haiku) in Phase 1, never by the main orchestrator thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1505:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1506:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1508:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.prompt.md:9:- Consultant subagents (`codex-consultant`, `gemini-consultant`) are multi-mode with a `MODE: <name>` discriminator.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1509:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1510:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1511:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1512:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1513:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1514:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:1:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1515:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1516:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1518:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:21:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1519:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:25:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1520:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:29:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1521:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:32:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1522:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1523:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:60:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1524:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:122:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1525:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:125:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1527:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:47:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1530:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:97:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1531:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:101:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1532:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:115:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1533:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:132:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1534:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:188:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1535:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:192:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1536:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:194:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1537:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:197:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1538:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:199:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1543:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:278:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1545:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:342:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1548:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:392:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1549:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:396:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1550:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:410:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1551:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:427:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1552:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:483:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1553:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:487:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1554:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:489:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1555:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:492:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1556:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:494:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1561:./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:573:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1562:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:34:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1563:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:35:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1564:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:38:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1565:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:41:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1566:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:43:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1567:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:47:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1568:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:48:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1569:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:50:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1571:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:76:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1572:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:80:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1573:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:97:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1576:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:133:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1577:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:143:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1578:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:148:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1580:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:237:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1581:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:293:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1583:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:370:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1584:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:374:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1585:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:391:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1588:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:427:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1589:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:437:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1590:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:442:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1592:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:531:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1593:./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:587:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1594:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1595:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1596:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1597:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1598:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1601:./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:4: diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1602:./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:9: +++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1603:./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:13: +name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1606:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:16:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1607:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1608:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1610:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:36:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1611:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:40:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1612:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:44:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1613:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:47:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1614:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1615:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:75:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1616:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:137:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1617:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:140:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1618:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:28:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1619:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:88:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1622:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:151:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1623:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:152:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1624:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:155:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1625:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:157:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1626:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:159:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1627:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:161:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1628:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:165:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1629:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:181:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1630:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:183:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1631:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:190:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1632:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:239:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1633:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:245:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1634:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:246:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1635:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:263:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1636:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:297:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1637:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:298:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1638:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:332:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1639:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:399:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1642:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:462:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1643:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:463:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1644:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:466:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1645:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:468:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1646:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:470:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1647:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:472:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1648:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:476:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1649:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:492:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1650:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:494:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1651:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:501:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1652:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:550:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1653:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:556:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1654:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:557:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1655:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:574:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1656:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:608:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1657:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:609:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1658:./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:643:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1659:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:1:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1660:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:5:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1661:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:8:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1662:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1663:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:36:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1664:./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:1:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1665:./README.md:42:| `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1666:./README.md:43:| `codex-consultant` | (CLI) | Cross-LLM consult via Codex |
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1667:./README.md:60:- Claude Code with `PushNotification` available (for mobile notifications).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1668:./README.md:97:- Skills that orchestrate should call cross-LLM consult (`gemini-consultant`, `codex-consultant`) at premise / red-team gates, not run them inline.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1669:./README.md:135:│   ├── codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1670:./README.md:136:│   ├── gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1671:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:16:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1672:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1673:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1676:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:42:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1678:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:48:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1679:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:51:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1680:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:54:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1681:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:60:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1682:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:64:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1683:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1685:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:95:/bin/zsh -lc "sed -n '1,220p' agents/codex-consultant.md" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1686:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:98:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1687:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:130:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1688:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1689:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:194:/bin/zsh -lc 'pwd && rg -n "brainstorm|research-review|Building the prompt|Returning to the caller|Archiving|standard return wrapper|Recommendation" agents/codex-consultant.md SPEC.md TASKS.md PLAN.md 2>/dev/null' in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1690:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:197:agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1691:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1692:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:199:agents/codex-consultant.md:48:## Building the prompt to Codex
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1693:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:200:agents/codex-consultant.md:60:## Returning to the caller
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1694:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:201:agents/codex-consultant.md:65:**Recommendation:** <Codex's pick>
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1695:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:202:agents/codex-consultant.md:79:## Archiving (required)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1696:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:207:/bin/zsh -lc "nl -ba agents/codex-consultant.md | sed -n '25,105p'" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1697:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:218:    34	- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1698:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1699:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:282:/bin/zsh -lc "git status --short && git diff -- agents/codex-consultant.md | sed -n '1,180p'" in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1700:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:285: M agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1701:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:286: M agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1702:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:300:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1703:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:315:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1704:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:317:--- a/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1705:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:318:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1706:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:323:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1707:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1708:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:339:/bin/zsh -lc 'rg -n "research-review|brainstorm" agents/codex-consultant.md agents/gemini-consultant.md commands skills README.md' in /Users/zeke/dev/z-harness
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1709:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1710:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:342:agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1714:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:354:agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1715:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1719:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:371:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1720:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:373:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1721:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:375:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1722:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:379:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1723:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:381:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1724:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:383:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1725:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:19:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1726:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:20:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1727:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:23:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1728:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:26:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1729:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:28:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1730:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:32:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1731:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:33:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1732:./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:35:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1733:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:12:commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1734:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:98:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1737:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:155:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1738:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:157:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1739:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:159:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1740:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:163:  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1741:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:179:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1742:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:181:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1743:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:222:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1746:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:304:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1747:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:327:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1748:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:329:   Agent(subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1749:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:333:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1751:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1754:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:107:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1755:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:108:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1756:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:111:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1757:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:113:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1758:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:115:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1759:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:117:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1760:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:121:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1761:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:137:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1762:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:139:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1763:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:146:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1764:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:195:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1765:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:201:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1766:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:202:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1767:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:219:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1768:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:253:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1769:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:254:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1770:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:288:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1771:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:355:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1774:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:418:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1775:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:419:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1776:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:422:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1777:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:424:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1778:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:426:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1779:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:428:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1780:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:432:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1781:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:448:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1782:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:450:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1783:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:457:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1784:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:506:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1785:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:512:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1786:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:513:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1787:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:530:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1788:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:564:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1789:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:565:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1790:./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:599:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1791:./z-harness/archive/tasks/per-task-model-selection/review.response.md:16:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1792:./z-harness/archive/tasks/per-task-model-selection/review.response.md:110:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1793:./z-harness/archive/tasks/per-task-model-selection/review.response.md:216:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1794:./z-harness/archive/tasks/per-task-model-selection/review.response.md:226:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1795:./z-harness/archive/tasks/per-task-model-selection/review.response.md:229:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1796:./z-harness/archive/tasks/per-task-model-selection/review.response.md:231:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1797:./z-harness/archive/tasks/per-task-model-selection/review.response.md:235:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1798:./z-harness/archive/tasks/per-task-model-selection/review.response.md:252:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1799:./z-harness/archive/tasks/per-task-model-selection/review.response.md:254:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1800:./z-harness/archive/tasks/per-task-model-selection/review.response.md:261:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1801:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:28:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1802:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:29:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1803:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:31: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1804:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:34:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1805:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:36:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1806:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:37:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1807:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:39:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1808:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:41: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1809:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:69:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1810:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:70:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1811:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:72: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1812:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:75:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1813:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:77:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1814:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:78:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1815:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:80:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1816:./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:82: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1817:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1820:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:107:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1821:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:109:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1822:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:113:+- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1823:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:114:+- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1824:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:116:+- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1825:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:118:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1826:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:120:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1827:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:122:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1828:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:126:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1829:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:142:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1830:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:144:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1831:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:151:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1832:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:200:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1833:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:206:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1834:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:207:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1835:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:224:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1836:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:258:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1837:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:259:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1838:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:293:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1839:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:360:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1842:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:423:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1843:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:425:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1844:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:429:+- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1845:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:430:+- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1846:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:432:+- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1847:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:434:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1848:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:436:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1849:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:438:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1850:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:442:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1851:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:458:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1852:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:460:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1853:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:467:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1854:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:516:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1855:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:522:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1856:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:523:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1857:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:540:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1858:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:574:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1859:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:575:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1860:./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:609:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1861:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:43:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1862:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:103:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1865:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:166:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1866:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:167:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1867:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:170:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1868:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:172:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1869:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:174:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1870:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:176:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1871:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:180:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1872:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:196:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1873:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:198:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1874:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:205:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1875:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:254:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1876:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:260:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1877:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:261:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1878:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:278:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1879:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:312:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1880:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:313:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1881:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:347:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1882:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:414:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1885:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:477:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1886:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:478:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1887:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:481:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1888:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:483:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1889:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:485:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1890:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:487:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1891:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:491:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1892:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:507:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1893:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:509:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1894:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:516:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1895:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:565:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1896:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:571:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1897:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:572:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1898:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:589:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1899:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:623:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1900:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:624:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1901:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:658:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1902:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:743:    38	8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1905:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:806:   101	**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1906:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:807:   102	- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1907:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:810:   105	If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1908:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:812:   107	**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1909:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:814:   109	### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1910:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:816:   111	If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1911:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:820:   115	  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1912:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:836:   131	Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1913:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:838:   133	**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1914:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:845:   140	  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1915:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:894: M agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1916:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:895: M agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1917:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:909:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1918:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:926:skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1919:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:932:commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1920:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:938:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1921:./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:946:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1943:    54	    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1944:    55	    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1947:    58	    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1978:    12	**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1984:    18	1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1985:    19	2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2020:    54	If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2024:    58	# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2036:    70	If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2040:    74	  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2049:   262	  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2074:   287	- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2087:    10	- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2088:    11	- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2106:    29	input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2117:    40	**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2146:    69	<user-provided refinement notes from AskUserQuestion>
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2168:    91	input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2225:   148	1. Derive slug (auto from topic, or use `--slug=X` if provided). If slug dir exists with `BRAINSTORM.md` already, ask via AskUserQuestion: overwrite / append to a new run / abort.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2230:   153	**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2231:   154	- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2232:   155	- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2236:   159	Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2239:   162	MODE: brainstorm
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2242:   165	  doc-fetcher: <synthesis or "n/a">
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2256:   179	Claude ideator uses subagent_type="general-purpose" (or a new "ideator" agent if we add one; see Open question O1 in PLAN.md) with `model="sonnet"`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2264:   187	6. `AskUserQuestion` with previews — option per framing + "Restart with different topic framing" + "Abandon."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2268:   191	- `log-event.sh brainstorm_run_end` with `{status, tokens_spent, ideator_durations_ms, chosen_framing}`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2288:   211	description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2303:   226	Before any subagent dispatch, AskUserQuestion: "Research is the heaviest precontext command (target ≤2M tokens, up to 3 Explore subagents). Proceed?" Options: "Proceed" / "Reduce to 1 Explore" / "Abandon." Log user's pick.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2305:   228	**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2320:   243	Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2337:   260	### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2351:    12	**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2361:    22	   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2362:    23	   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2380:    41	8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2397:    58	If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2401:    62	# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2411:    72	Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2430:    91	**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2434:    95	  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2448:   109	**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2462:   123	  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2465:   126	  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2468:   129	  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2474:   135	  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2521:   182	Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2525:   186	  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2527:   188	  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2530:   191	  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2532:   193	  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2611:   272	Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:16:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:110:?? agents/doc-fetcher.md
./z-harness/archive/tasks/per-task-model-selection/review.response.md:140:   subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:164:   subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:192:   subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:216:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:226:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:229:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/archive/tasks/per-task-model-selection/review.response.md:231:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:235:+  subagent_type="doc-fetcher",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:252:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:254:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:258:+  subagent_type="Explore",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:261:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/archive/tasks/per-task-model-selection/review.response.md:331:    58	  subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:362:   173	  subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:381:   253	  subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:406:   173	  subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:425:   253	  subagent_type="implementer",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:471:    58	  subagent_type="implementer",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:18:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:28:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:29:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:47:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:64:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:68:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:78:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:97:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:101:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:115:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:129:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:132:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:135:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:141:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:188:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:192:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:194:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:197:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:199:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:278:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:313:+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:323:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:324:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:342:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:359:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:363:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:373:+Present the cost up front via `AskUserQuestion` with three options:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:392:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:396:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:410:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:424:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:427:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:430:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:436:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:483:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:487:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:489:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:492:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:494:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:573:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:32:  - If any stale → `AskUserQuestion` warn the user before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:34:- **Unfinalized brainstorm** (`status: complete` missing or `chosen_framing` absent): recommend `/z-brainstorm` re-run before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:43:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:77:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:85:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:86:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:103:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:109:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:111:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:113:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:136:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:140:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:158:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:166:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:167:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:170:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:172:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:174:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:176:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:180:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:196:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:198:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:202:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:205:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:254:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:260:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:261:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:278:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:282:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:312:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:313:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:321:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:347:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:388:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:396:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:397:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:414:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:420:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:422:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:424:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:447:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:451:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:469:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:477:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:478:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:481:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:483:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:485:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:487:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:491:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:507:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:509:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:513:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:516:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:565:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:571:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:572:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:589:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:593:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:623:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:624:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:632:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:658:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:717:    12	**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:725:    20	   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:726:    21	   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:743:    38	8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:749:    44	   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:751:    46	    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:753:    48	    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:776:    71	If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:780:    75	# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:798:    93	If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:806:   101	**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:807:   102	- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:810:   105	If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:812:   107	**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:814:   109	### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:816:   111	If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:820:   115	  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:836:   131	Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:838:   133	**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:842:   137	  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:845:   140	  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:894: M agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:895: M agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:909:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:925:skills/z-plan/SKILL.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:926:skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:931:commands/z-plan.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:932:commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:938:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:942:- **Major** — [commands/z-plan.md:46](/Users/zeke/dev/z-harness/commands/z-plan.md:46) and mirrored skill: deleted-source detection emits `precontext_source_deleted`, but the stale warning is only triggered by “stale citation found,” leaving deleted citations without a required user warning despite the spec saying deleted-source is higher severity than stale-mtime. Fix by treating deleted cited sources as stale/blocking precontext for the AskUserQuestion warning path, while still emitting the higher-severity event.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:946:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:950:- **Major** — [commands/z-plan.md:46](/Users/zeke/dev/z-harness/commands/z-plan.md:46) and mirrored skill: deleted-source detection emits `precontext_source_deleted`, but the stale warning is only triggered by “stale citation found,” leaving deleted citations without a required user warning despite the spec saying deleted-source is higher severity than stale-mtime. Fix by treating deleted cited sources as stale/blocking precontext for the AskUserQuestion warning path, while still emitting the higher-severity event.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:17: +   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:19:-+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:20:++    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:22: +    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:28:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:29:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:31: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:34:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:36:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:37:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:39:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:41: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:58: +   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:60:-+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, any modification within the range → stale. If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime). Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:61:++    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:63: +    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:69:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:70:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:72: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:75:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:77:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:78:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:80:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:82: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:18:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:26:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:27:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:50:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:52:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:54:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:77:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:81:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:99:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:107:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:109:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:113:+- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:114:+- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:116:+- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:118:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:120:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:122:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:126:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:142:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:144:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:148:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:151:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:200:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:206:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:207:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:224:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:228:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:258:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:259:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:267:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:293:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:334:+**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:342:+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:343:+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:360:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:366:+   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:368:+    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:370:+    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:393:+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:397:+# ... AskUserQuestion ...
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:415:+If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:423:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:425:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:429:+- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:430:+- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:432:+- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:434:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:436:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:438:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:442:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:458:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:460:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:464:+  subagent_type="Explore",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:467:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:516:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:522:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:523:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:540:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:544:+Use `AskUserQuestion` for explicit approval on:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:574:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:575:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:583:+**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:609:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:12:commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:21:commands/z-implement-all.md:151:- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:25:commands/z-implement-all.md:197:- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:32:commands/z-plan.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:75:**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:81:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:98:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:104:   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:127:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:131:# ... AskUserQuestion ...
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:147:If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:155:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:157:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:159:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:163:  subagent_type="doc-fetcher",
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:179:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:181:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:199:**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:205:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Confirm with the user via `AskUserQuestion` if the auto-derived slug is non-obvious or might collide with an existing slug (run `ls z-harness/` to check for existing slug dirs first).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:222:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:228:   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:251:If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:255:# ... AskUserQuestion ...
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:283:**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:289:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:304:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:324:If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:327:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:329:   Agent(subagent_type="doc-fetcher",
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:333:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:357:**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:368:   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.

codex
The repo already has brainstorm mode in the consultant agents, so I’m checking whether the command’s subagent names and expected return shape line up with those contracts rather than just with the excerpt.
exec
/bin/zsh -lc "sed -n '1,120p' agents/gemini-consultant.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,120p' agents/codex-consultant.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: gemini-consultant
description: Consults Gemini (via the `gemini` CLI in headless plan mode) for a second opinion on a specific engineering decision or to review a plan. Use during /z-plan when a non-obvious decision needs cross-LLM input, and again to review the final plan.
tools: Bash, Read, Grep, Glob
model: haiku
---

You are a **consultant proxy** for Gemini. Your job is to (a) package the question with enough context for a useful answer, (b) call Gemini via the `gemini` CLI, and (c) return Gemini's response to the caller — unfiltered and clearly labeled.

## How to call Gemini

Use the headless, read-only mode:

```bash
gemini -p "<full prompt>" --approval-mode plan --output-format text
```

- Pipe long prompts via stdin if they exceed safe shell length: `printf '%s' "$PROMPT" | gemini -p "" --approval-mode plan`
- Always use `--approval-mode plan` so Gemini cannot mutate the filesystem.

## Modes

The caller signals a mode via a `MODE: <name>` prefix in the prompt. Handle each shape:

- **`bundled-decisions`** (Phase 3 of `/z-plan`): caller hands you the full `decisions.md` plus context. Ask Gemini to weigh in on every consult-flagged decision *and* flag interactions between decisions.
- **`plan-review`** (Phase 7 of `/z-plan`): caller hands you SPEC.md + PLAN.md. Ask Gemini to critique the plan for what's wrong, missing, or fragile.
- **`light-fix`** (Phase 3 of `/z-plan-light`; reused by `/z-debug` Phase 6 for the fix-stage consult): caller hands you a single problem statement + context + one key decision + candidate options. Ask Gemini for a concise recommendation with tradeoffs. Be brief — this is a small fix, not a feature.
- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
  1. Framing
  2. Core hypothesis
  3. Risks
  4. Plan implications
  5. What would change my mind
- **`doc-audit`** (`/z-maintain-docs --audit`): caller hands you a proposed human-tier markdown + LLM-tier JSON update + the source files the concept describes + the prior version of the doc. Ask Gemini: does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't.
- **`test-cases`** (Phase 3 of `/z-test`): caller hands you SPEC.md + PLAN.md + TASKS.md + a draft list of test cases + user-stated bug-class concerns + the source files referenced by the drafts. Ask Gemini: (1) for each draft, is the assertion strong enough to catch a real bug or a tautology — if weak, propose a stronger assertion; (2) which SPEC invariants have no corresponding test (propose entries); (3) what dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are uncovered; (4) flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed.

## Building the prompt to Gemini

The caller gives you the input artifact + pointers to relevant files. You must:

1. Read the named files yourself (Read tool) so you can quote real code — Gemini cannot see this repo.
2. Construct a single prompt that includes:
   - **Mode** — "bundled decisions" or "plan review"
   - **Input artifact** — verbatim decisions.md, or SPEC.md + PLAN.md
   - **Context** — quoted code snippets, types, surrounding patterns from the repo
   - **Constraints** — tests, perf, framework conventions, DRY/KISS/SOLID
   - **Ask** — for bundled mode: "For each consult-flagged decision, recommend an option with reasoning, tradeoffs, and anything missed. Also flag interactions between decisions." For plan review: "Critique this plan — what's wrong, missing, or fragile?"

## Returning to the caller

Return a structured response:

```
## Gemini consultation: <decision summary>

**Recommendation:** <Gemini's pick>

**Reasoning:** <Gemini's reasoning, summarized faithfully>

**Tradeoffs / risks flagged:** <bullets>

**Additional considerations Gemini raised:** <bullets>

**Raw response excerpt (if useful):**
<short quote>
```

Do not editorialize, do not "improve" Gemini's answer, do not agree or disagree — that's the caller's job. Just faithfully relay.

If `gemini` errors (auth, rate limit, network), report the exact error so the caller can decide whether to retry, fall back to Codex only, or ask the user.

## Archiving (required)

Before returning, write the full prompt + response to disk and log the event. The caller will tell you the run id; if not, derive it from the most recent `z-harness/archive/*/` directory.

```bash
RUN="<run-id from caller>"
DIR="z-harness/archive/$RUN/transcripts"
mkdir -p "$DIR"
N=$(printf '%03d' $(( $(ls "$DIR" 2>/dev/null | wc -l) + 1 )))
SLUG="gemini-<bundled-decisions|plan-review>"
printf '%s\n' "$PROMPT" > "$DIR/$N-$SLUG.prompt.md"
printf '%s\n' "$RESPONSE" > "$DIR/$N-$SLUG.response.md"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult \
  "$(printf '{"llm":"gemini","mode":"%s","prompt_chars":%d,"response_chars":%d,"wall_ms":%d,"transcript":"%s"}' \
     "$MODE" "${#PROMPT}" "${#RESPONSE}" "$WALL_MS" "$N-$SLUG")"
```

 succeeded in 0ms:
---
name: codex-consultant
description: Consults Codex (via the `codex` CLI, which uses the Codex/ChatGPT app endpoint — NOT the OpenAI API endpoint) for a second opinion on an engineering decision or to review a plan. Use during /z-plan when a non-obvious decision needs cross-LLM input, and again to review the final plan.
tools: Bash, Read, Grep, Glob
model: haiku
---

You are a **consultant proxy** for Codex. Your job is to package the caller's question with enough context, call Codex via the `codex` CLI, and return Codex's response unfiltered.

## How to call Codex

Use non-interactive mode (this hits the Codex/ChatGPT app endpoint via the `codex` CLI's stored auth, NOT the OpenAI API endpoint):

```bash
codex exec "<full prompt>"
```

For long prompts, prefer stdin:

```bash
printf '%s' "$PROMPT" | codex exec -
```

If you need Codex to run read-only against this repo, use it as-is (codex inherits cwd). Do not pass write-enabling flags.

## Modes

The caller signals a mode via a `MODE: <name>` prefix in the prompt. Handle each shape:

- **`bundled-decisions`** (Phase 3 of `/z-plan`): caller hands you the full `decisions.md`. Weigh in on every consult-flagged decision and flag interactions.
- **`plan-review`** (Phase 7 of `/z-plan`): caller hands you SPEC.md + PLAN.md. Critique for what's wrong, missing, or fragile.
- **`light-fix`** (Phase 3 of `/z-plan-light`; reused by `/z-debug` Phase 6): caller hands you a single problem statement + context + one key decision + candidate options. Ask Codex for a concise recommendation with tradeoffs. Be brief — this is a small fix, not a feature.
- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
  1. Framing
  2. Core hypothesis
  3. Risks
  4. Plan implications
  5. What would change my mind
- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
  - Gaps (things the draft missed)
  - Errors (claims the draft made that appear wrong)
  - Missing constraints (constraints the reviewer noticed that should be added)
  Codex must NOT recommend an approach. Research is terrain-mapping, not direction-picking. The prompt must explicitly instruct Codex to omit any recommendation.
- **`doc-audit`** (`/z-maintain-docs --audit`): caller hands you a proposed human-tier markdown + LLM-tier JSON update + the source files + prior doc (if any). Ask Codex: does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't.
- **`test-cases`** (Phase 3 of `/z-test`): caller hands you SPEC.md + PLAN.md + TASKS.md + a draft list of test cases + user-stated bug-class concerns + the source files referenced by the drafts. Ask Codex: (1) for each draft, is the assertion strong enough to catch a real bug or a tautology — if weak, propose a stronger assertion; (2) which SPEC invariants have no corresponding test (propose entries); (3) what dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are uncovered; (4) flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed.

## Building the prompt to Codex

The caller gives you the input artifact + file pointers. You must:

1. Read the named files yourself so you can quote real code.
2. Construct a prompt with:
   - **Mode** — the mode name from the `MODE:` prefix
   - **Input artifact** — verbatim
   - **Context** — quoted code, types, patterns
   - **Constraints** — tests, perf, framework conventions, DRY/KISS/SOLID
   - **Ask** — use the per-mode template below:
     - `bundled-decisions`: "For each consult-flagged decision, recommend with reasoning, tradeoffs, missed considerations, and decision interactions."
     - `plan-review`: "Critique this plan — what's wrong, missing, or fragile?"
     - `light-fix`: "Give a concise recommendation with tradeoffs for this single decision. Be brief."
     - `debug-hypotheses`: "Which hypothesis is most plausible and why? Have any been missed? For the top hypothesis, what is the cheapest experiment to confirm or refute it? Be concrete."
     - `brainstorm`: "Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation."
     - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
     - `doc-audit`: "Does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't."
     - `test-cases`: "(1) For each draft test, is the assertion strong enough to catch a real bug or is it a tautology — if weak, propose a stronger assertion. (2) Which SPEC invariants have no corresponding test (propose entries)? (3) What dangerous bug classes specific to this codebase domain are uncovered? (4) Flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed."

## Returning to the caller

For `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-audit`, and `test-cases`, use the standard wrapper:

```
## Codex consultation: <decision summary>

**Recommendation:** <Codex's pick>

**Reasoning:** <faithfully summarized>

**Tradeoffs / risks flagged:** <bullets>

**Additional considerations Codex raised:** <bullets>

**Raw response excerpt (if useful):**
<short quote>
```

For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).

Do not editorialize or "improve." If `codex` errors, report the exact error so the caller can decide how to proceed.

## Archiving (required)

Before returning, write the prompt + response to the run's transcripts dir and log the event:

```bash
RUN="<run-id from caller>"
DIR="z-harness/archive/$RUN/transcripts"
mkdir -p "$DIR"
N=$(printf '%03d' $(( $(ls "$DIR" 2>/dev/null | wc -l) + 1 )))
SLUG="codex-$MODE"
printf '%s\n' "$PROMPT"   > "$DIR/$N-$SLUG.prompt.md"
printf '%s\n' "$RESPONSE" > "$DIR/$N-$SLUG.response.md"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult \
  "$(printf '{"llm":"codex","mode":"%s","prompt_chars":%d,"response_chars":%d,"wall_ms":%d,"transcript":"%s"}' \
     "$MODE" "${#PROMPT}" "${#RESPONSE}" "$WALL_MS" "$N-$SLUG")"
```

exec
/bin/zsh -lc "nl -ba commands/z-brainstorm.md | sed -n '1,288p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
     3	argument-hint: <topic to brainstorm> [--slug=<kebab>]
     4	---
     5	
     6	You are running the **z-harness `/z-brainstorm`** pipeline.
     7	
     8	Topic (from `$ARGUMENTS`):
     9	
    10	$ARGUMENTS
    11	
    12	**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.
    13	
    14	`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.
    15	
    16	## Setup
    17	
    18	1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
    19	2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
    20	   - **overwrite** — archive existing `BRAINSTORM.md` to `archive/<RUN>/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer) and start fresh
    21	   - **append-to-new-run** — keep `BRAINSTORM.md` in place but write this run's output to a fresh RUN-scoped path and ask the user later whether to promote it
    22	   - **abort** — exit cleanly with no changes
    23	3. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
    24	4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
    25	5. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
    26	6. **Version stamp + log run start:**
    27	   ```bash
    28	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    29	   START_PAYLOAD="$(python3 -c '
    30	   import json, sys
    31	   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]
    32	   print(json.dumps(v))
    33	   ' "$VERSION_BLOB" "<arguments>")"
    34	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
    35	   ```
    36	7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
    37	8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.
    38	
    39	**All paths live under `z-harness/<slug>/`:**
    40	- `z-harness/<slug>/BRAINSTORM.md`
    41	- `z-harness/<slug>/archive/<RUN>/...`
    42	
    43	## Phase telemetry (mandatory)
    44	
    45	At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
    46	
    47	```bash
    48	WALL_MS=$(( $(date +%s%3N) - T0 ))
    49	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
    50	  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
    51	     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
    52	```
    53	
    54	If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:
    55	
    56	```bash
    57	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
    58	# ... AskUserQuestion ...
    59	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
    60	```
    61	
    62	---
    63	
    64	## Phase 1 — Scaffolding
    65	
    66	Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:
    67	
    68	### 1a. Doc-fetcher (if INDEX.json exists)
    69	
    70	If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
    71	
    72	```
    73	Agent(
    74	  subagent_type="doc-fetcher",
    75	  description="Doc context for <slug>",
    76	  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
    77	)
    78	```
    79	
    80	It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.
    81	
    82	### 1b. Optional Explore
    83	
    84	If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
    85	
    86	```
    87	Agent(
    88	  subagent_type="Explore",
    89	  model: "haiku",
    90	  description="Brainstorm scaffolding for <slug>",
    91	  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
    92	)
    93	```
    94	
    95	If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
    96	
    97	### 1c. RESEARCH.md ingestion
    98	
    99	If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, read it.
   100	
   101	- **≤20 KB:** inline the full content into the scaffolding payload.
   102	- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.
   103	
   104	Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
   105	
   106	### 1d. Assemble and hash
   107	
   108	Compute the `input_hash` per SPEC:
   109	
   110	```
   111	input_hash = sha256(canonicalize(
   112	    topic + "\n---\n" +
   113	    doc_fetcher_synthesis_or_empty + "\n---\n" +
   114	    explore_synthesis_or_empty + "\n---\n" +
   115	    research_md_or_summary_or_empty
   116	)).hexdigest()[:16]
   117	```
   118	
   119	`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.
   120	
   121	Checkpoint: write the assembled scaffolding to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/phase1-scaffolding.md`.
   122	
   123	---
   124	
   125	## Phase 2 — Parallel ideator dispatch
   126	
   127	Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
   128	
   129	```
   130	Agent(
   131	  subagent_type="general-purpose",
   132	  model="sonnet",
   133	  description="Claude ideator for <slug>",
   134	  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
   135	)
   136	Agent(
   137	  subagent_type="codex-consultant",
   138	  description="Codex ideator for <slug>",
   139	  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
   140	)
   141	Agent(
   142	  subagent_type="gemini-consultant",
   143	  description="Gemini ideator for <slug>",
   144	  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
   145	)
   146	```
   147	
   148	Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
   149	
   150	### Ideator failure policy
   151	
   152	Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.
   153	
   154	- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<vendor>:failed"` in the `ideators` frontmatter list. The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
   155	- **2/3 fail** → halt. Use `AskUserQuestion` with options:
   156	  - **retry** (default) — re-dispatch the failed ideators once
   157	  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
   158	  - **abandon** — set frontmatter `status: abandoned` and exit
   159	- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.
   160	
   161	Log every individual failure as `ideator_failed` regardless of the bucket above.
   162	
   163	---
   164	
   165	## Phase 3 — Synthesis + mandatory anti-bias check
   166	
   167	1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.
   168	
   169	2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.
   170	
   171	3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.
   172	
   173	4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:
   174	
   175	   ```yaml
   176	   ---
   177	   artifact: brainstorm
   178	   slug: <slug>
   179	   generated_at: <UTC ISO 8601>
   180	   command: /z-brainstorm <args>
   181	   input_hash: <16 hex from Phase 1d>
   182	   depends_on: [<RESEARCH.md if ingested>]
   183	   ideators:
   184	     - claude-sonnet
   185	     - codex
   186	     - gemini
   187	     # failed members recorded as "<vendor>:failed"
   188	   status: complete
   189	   ---
   190	   ```
   191	
   192	   Body sections, one block per ideator (in fixed order Claude → Codex → Gemini):
   193	
   194	   ```markdown
   195	   ## Framing: <ideator-name>
   196	
   197	   ### Framing
   198	   <one paragraph or `<missing>`>
   199	
   200	   ### Core hypothesis
   201	   <one paragraph or `<missing>`>
   202	
   203	   ### Risks
   204	   <bulleted list or `<missing>`>
   205	
   206	   ### Plan implications
   207	   <bulleted list or `<missing>`>
   208	
   209	   ### What would change my mind
   210	   <bulleted list or `<missing>`>
   211	   ```
   212	
   213	   Followed by:
   214	
   215	   ```markdown
   216	   ## Anti-bias check
   217	   <section-by-section comparison with explicit justification for any Claude-favoring pick>
   218	
   219	   ## Orchestrator recommendation
   220	   <one-line rationale; user is free to override>
   221	
   222	   ## User choice
   223	   <filled in Phase 4>
   224	   ```
   225	
   226	5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
   227	   - One option per available framing (e.g. **Claude framing**, **Codex framing**, **Gemini framing** — only for ideators that succeeded)
   228	   - **Restart** — discard this run and re-run with a refined topic
   229	   - **Abandon** — exit cleanly without finalizing
   230	
   231	Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
   232	
   233	---
   234	
   235	## Phase 4 — Finalize
   236	
   237	Branch on the user's Phase 3 choice:
   238	
   239	### User picked a framing
   240	
   241	1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
   242	2. Append a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
   243	3. Confirm `status: complete` in the frontmatter.
   244	
   245	### User picked Restart
   246	
   247	1. Archive the just-written BRAINSTORM.md to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer).
   248	2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
   249	3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.
   250	
   251	### User picked Abandon
   252	
   253	1. Set the frontmatter `status: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
   254	2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.
   255	
   256	### In all branches
   257	
   258	Log `brainstorm_run_end`:
   259	
   260	```bash
   261	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
   262	  "$(printf '{"status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
   263	     "<complete|abandoned>" "<framing-or-empty>" "<N>")"
   264	```
   265	
   266	Push-notify (if policy ≠ `off`) with a next-step recommendation:
   267	
   268	```
   269	Brainstorm complete (framing: <chosen>).
   270	
   271	Recommended next:
   272	  /z-research <question>  — (optional) map terrain before planning
   273	  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
   274	```
   275	
   276	For the abandoned branch, the push notification just says "Brainstorm abandoned" with no next-step.
   277	
   278	---
   279	
   280	## Operating principles
   281	
   282	- **Cheap and parallel.** Three ideators in one message, no per-ideator round-trips.
   283	- **Identical scaffolding for all three.** No read-by-reference asymmetry.
   284	- **Anti-bias is mandatory.** Every Claude-favoring pick needs explicit justification.
   285	- **Failures degrade gracefully** — 1/3 proceeds, 2/3 asks, 3/3 halts.
   286	- **Restart is cheap.** Archive and loop, don't try to patch.
   287	- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
   288	- **Log everything** via `scripts/log-event.sh`.

exec
/bin/zsh -lc "rg -n \"name: general-purpose|general-purpose|doc-fetcher|name: Explore|name: explore|subagent_type=\\\"Explore\\\"|subagent_type=\\\"doc-fetcher\\\"\" agents commands skills -S" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
commands/z-brainstorm.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
commands/z-brainstorm.md:74:  subagent_type="doc-fetcher",
commands/z-brainstorm.md:88:  subagent_type="Explore",
commands/z-brainstorm.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
commands/z-brainstorm.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
commands/z-brainstorm.md:131:  subagent_type="general-purpose",
commands/z-brainstorm.md:148:Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
commands/z-brainstorm.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
skills/z-do/SKILL.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
skills/z-do/SKILL.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
skills/z-do/SKILL.md:50:## Phase 2 — Ground (doc-fetcher first)
skills/z-do/SKILL.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
skills/z-research/SKILL.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
skills/z-research/SKILL.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
skills/z-research/SKILL.md:95:  subagent_type="doc-fetcher",
skills/z-research/SKILL.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
skills/z-research/SKILL.md:123:  subagent_type="Explore",
skills/z-research/SKILL.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
skills/z-research/SKILL.md:129:  subagent_type="Explore",
skills/z-research/SKILL.md:135:  subagent_type="Explore",
skills/z-research/SKILL.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
skills/z-research/SKILL.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
agents/doc-fetcher.md:2:name: doc-fetcher
commands/z-plan.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
commands/z-plan.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
commands/z-plan.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
commands/z-plan.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
commands/z-plan.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
commands/z-plan.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
commands/z-plan.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
commands/z-plan.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
commands/z-plan.md:120:  subagent_type="doc-fetcher",
commands/z-plan.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
commands/z-plan.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
commands/z-plan.md:142:  subagent_type="Explore",
commands/z-plan.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
commands/z-debug.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
commands/z-debug.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
commands/z-debug.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
skills/z-plan/SKILL.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
skills/z-plan/SKILL.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
skills/z-plan/SKILL.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
skills/z-plan/SKILL.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
skills/z-plan/SKILL.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
skills/z-plan/SKILL.md:112:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
skills/z-plan/SKILL.md:114:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
skills/z-plan/SKILL.md:116:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
skills/z-plan/SKILL.md:120:  subagent_type="doc-fetcher",
skills/z-plan/SKILL.md:136:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
skills/z-plan/SKILL.md:138:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
skills/z-plan/SKILL.md:142:  subagent_type="Explore",
skills/z-plan/SKILL.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
skills/z-debug/SKILL.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
skills/z-debug/SKILL.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
skills/z-debug/SKILL.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
commands/z-do.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
commands/z-do.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
commands/z-do.md:50:## Phase 2 — Ground (doc-fetcher first)
commands/z-do.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
skills/z-plan-light/SKILL.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
skills/z-plan-light/SKILL.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
skills/z-plan-light/SKILL.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
commands/z-research.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
commands/z-research.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
commands/z-research.md:95:  subagent_type="doc-fetcher",
commands/z-research.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
commands/z-research.md:123:  subagent_type="Explore",
commands/z-research.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
commands/z-research.md:129:  subagent_type="Explore",
commands/z-research.md:135:  subagent_type="Explore",
commands/z-research.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
commands/z-research.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
commands/z-plan-light.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
commands/z-plan-light.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
commands/z-plan-light.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
skills/z-brainstorm/SKILL.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
skills/z-brainstorm/SKILL.md:74:  subagent_type="doc-fetcher",
skills/z-brainstorm/SKILL.md:88:  subagent_type="Explore",
skills/z-brainstorm/SKILL.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
skills/z-brainstorm/SKILL.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
skills/z-brainstorm/SKILL.md:131:  subagent_type="general-purpose",
skills/z-brainstorm/SKILL.md:148:Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.
skills/z-brainstorm/SKILL.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
commands/z-audit.md:33:7. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",

codex
- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:19) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:19): existing-slug handling references `archive/<RUN>/...` before `RUN` is created in step 4, so the overwrite/archive path is undefined at the decision point. Move RUN creation before collision handling, or explicitly create a collision/archive run before archiving.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:21) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:21): `append-to-new-run` is introduced but never made executable; Phase 3 always writes canonical `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`, so this option either overwrites anyway or leaves no defined artifact path/promotion flow. Either remove the option or specify the exact run-scoped output path and promotion mechanics throughout Phases 3-4.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:175) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:175): the required `chosen_framing` frontmatter field is missing from the BRAINSTORM.md template, and Phase 4 says to “update” a field that was never created. Add `chosen_framing:` to the initial frontmatter with a valid provisional/final value strategy, and ensure restart/abandon branches persist a spec-valid value.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:155) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:155): the 2/3-failure `abandon` path says to set frontmatter `status: abandoned` and exit, but BRAINSTORM.md is not written until Phase 3, so there is no artifact to update. Specify that this branch writes a minimal abandoned BRAINSTORM.md with the required frontmatter and failed ideators, or change the failure policy to exit without an artifact.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:137) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:137): the Codex and Gemini `Agent()` prompts do not include the identical five-section instructions that Claude receives, only `MODE`, topic, and scaffolding. Put the same output-schema instructions in all three prompts so failures are judged against an actually identical contract.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:154) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:154): failed ideators are recorded as `"<vendor>:failed"`, but successful Claude is recorded as `claude-sonnet` while `chosen_framing` expects `claude`; this creates avoidable parsing mismatch for `/z-plan` consumers. Use canonical ids consistently, e.g. `claude`, `codex`, `gemini`, with model detail in a separate note if needed.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:222) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:222): Phase 3 writes a `## User choice` placeholder, then Phase 4 says to append another `## User choice` section, producing duplicate sections and making downstream parsing ambiguous. Change Phase 4 to replace the placeholder section in place, or do not emit the section until finalization.
2026-05-22T16:53:10.080499Z ERROR codex_core::session: failed to record rollout items: thread 019e509a-1f25-7123-b632-c67fee8270bd not found
tokens used
82,114
- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:19) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:19): existing-slug handling references `archive/<RUN>/...` before `RUN` is created in step 4, so the overwrite/archive path is undefined at the decision point. Move RUN creation before collision handling, or explicitly create a collision/archive run before archiving.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:21) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:21): `append-to-new-run` is introduced but never made executable; Phase 3 always writes canonical `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`, so this option either overwrites anyway or leaves no defined artifact path/promotion flow. Either remove the option or specify the exact run-scoped output path and promotion mechanics throughout Phases 3-4.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:175) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:175): the required `chosen_framing` frontmatter field is missing from the BRAINSTORM.md template, and Phase 4 says to “update” a field that was never created. Add `chosen_framing:` to the initial frontmatter with a valid provisional/final value strategy, and ensure restart/abandon branches persist a spec-valid value.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:155) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:155): the 2/3-failure `abandon` path says to set frontmatter `status: abandoned` and exit, but BRAINSTORM.md is not written until Phase 3, so there is no artifact to update. Specify that this branch writes a minimal abandoned BRAINSTORM.md with the required frontmatter and failed ideators, or change the failure policy to exit without an artifact.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:137) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:137): the Codex and Gemini `Agent()` prompts do not include the identical five-section instructions that Claude receives, only `MODE`, topic, and scaffolding. Put the same output-schema instructions in all three prompts so failures are judged against an actually identical contract.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:154) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:154): failed ideators are recorded as `"<vendor>:failed"`, but successful Claude is recorded as `claude-sonnet` while `chosen_framing` expects `claude`; this creates avoidable parsing mismatch for `/z-plan` consumers. Use canonical ids consistently, e.g. `claude`, `codex`, `gemini`, with model detail in a separate note if needed.

- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:222) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:222): Phase 3 writes a `## User choice` placeholder, then Phase 4 says to append another `## User choice` section, producing duplicate sections and making downstream parsing ambiguous. Change Phase 4 to replace the placeholder section in place, or do not emit the section until finalization.
