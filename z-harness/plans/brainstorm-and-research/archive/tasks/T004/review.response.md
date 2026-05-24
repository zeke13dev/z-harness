2026-05-22T16:51:15.855334Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T16:51:15.855457Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T16:51:15.855464Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e5099-2b11-7433-aff3-daf9ce497c64
--------
user
You are reviewing code that Claude just wrote for task T004: Create /z-research command + skill mirror — heavier opt-in pre-plan command for terrain mapping with cross-LLM critique.

Spec (excerpt from z-harness/brainstorm-and-research/SPEC.md):

### RESEARCH.md
YAML frontmatter:
---
artifact: research
slug: <kebab>
generated_at: <UTC ISO 8601>
command: /z-research <args>
input_hash: <16 hex>
depends_on: []
explore_calls: <N (0..3)>
status: complete | abandoned
---

Body sections (mandatory, in order): Findings, Constraints discovered, Open questions, No-recommendation (canonical text "This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one."), Cross-LLM review notes.

## input_hash algorithm
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_empty
)).hexdigest()[:16]
canonicalize: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.

### MODE: research-review (both consultants)
Consultant returns RAW. Sections: Gaps, Errors, Missing constraints. Explicit prohibition: must NOT recommend an approach.

## /z-research phase contract
- Setup: mirrors /z-brainstorm; research_run_start event.
- Phase 0 (Cost-confirmation gate): AskUserQuestion proceed / reduce-to-1-Explore / abandon. Log user's pick.
- Phase 1: doc-fetcher dispatch iff INDEX.json exists.
- Phase 2: up to 3 parallel Explore subagents on distinct facets (or 1 if user reduced). Hard cap 3; no env override in v1.
- Phase 3 (Draft): archive/<run>/research-draft.md with mandatory sections.
- Phase 4 (Critique): bundled cross-LLM critique — MODE: research-review on both consultants, parallel dispatch.
- Phase 5 (Revise): revise; record consultant feedback in Cross-LLM review notes; note filled/unfilled.
- Phase 6 (Finalize): write final RESEARCH.md; research_run_end event; push-notify next-step.

Invariants: uncited findings → Open questions; No-recommendation non-deletable; research_temptation event if orchestrator drafts recommendation.
Known v1 limitation (documented in command file): Agent() has no per-call wall-clock timeout; ctrl-c is the escape.

Acceptance criteria:
  - Both commands/z-research.md and skills/z-research/SKILL.md exist; diff shows ONLY frontmatter + blank-line differences (zero diff acceptable).
  - Setup mirrors /z-brainstorm Setup but logs research_run_start.
  - Phase 0: AskUserQuestion proceed (~2M)/reduce/abandon. Log pick.
  - Phase 1: doc-fetcher iff INDEX.json (ONE call). No Explore here.
  - Phase 2: up to 3 parallel Explores (or 1 if reduced). Hard cap = 3. No env override.
  - Phase 3: research-draft.md with 4 sections in order: Findings (file:line cites), Constraints, Open questions, No-recommendation (mandatory canonical text).
  - Phase 4: bundled MODE: research-review on BOTH consultants in parallel.
  - Phase 5: record consultant feedback in `## Cross-LLM review notes`, filled vs unfilled.
  - Phase 6: write z-harness/<slug>/RESEARCH.md with YAML frontmatter (artifact, slug, generated_at, command, input_hash per SPEC, depends_on: [], explore_calls, status: complete). Log research_run_end. Push-notify.
  - Cost guardrail ≤2M; warn.
  - v1 limitation re ctrl-c documented.

Note: `diff commands/z-research.md skills/z-research/SKILL.md` produced EXIT 0 — files are byte-identical (both share git blob a08955a). That is within the "zero diff acceptable" allowance.

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/commands/z-research.md b/commands/z-research.md
new file mode 100644
index 0000000..a08955a
--- /dev/null
+++ b/commands/z-research.md
@@ -0,0 +1,289 @@
+---
+description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
+argument-hint: <question or technical area to research>
+---
+
+You are running the **z-harness `/z-research`** pipeline.
+
+Question (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
+
+Strict, multi-phase. Do not skip phases. `/z-research` produces a research note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.
+
+**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.
+
+## Setup
+
+1. **Derive a research slug** from the question: short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
+2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
+3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
+4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
+5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
+   ```
+6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+7. **Artifact collision check.** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists:
+   - Archive it: `mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`
+   - Notify the user: "Existing RESEARCH.md archived. Starting fresh research."
+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
+
+**All paths in subsequent phases live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/RESEARCH.md`
+- `z-harness/<slug>/archive/<run-id>/...`
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+---
+
+## Phase 0 — Cost-confirmation gate
+
+Research can be expensive. The default fan-out is up to 3 parallel `Explore` subagents (Haiku) plus a bundled cross-LLM critique pass. Target spend: **≤2M tokens / 5-10 min wall time.** If you exceed 2M tokens at any point, log a `cost_warning` event and surface it to the user.
+
+Present the cost up front via `AskUserQuestion` with three options:
+
+- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores.
+- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
+- **Abandon** — exit cleanly, write nothing.
+
+Log the user's pick:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
+  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
+```
+
+If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.
+
+Checkpoint: `phase0-cost-gate.md`.
+
+## Phase 1 — Scaffolding
+
+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 2.
+
+If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
+  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
+```
+
+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
+
+Checkpoint: `phase1-scaffolding.md`.
+
+## Phase 2 — Parallel Explores
+
+Dispatch up to `EXPLORE_BUDGET` parallel `Explore` subagents (Haiku) on **distinct facets** of the question. Each Explore must answer a targeted sub-question; do not dispatch overlapping queries.
+
+**Hard cap: 3.** No env override in v1. If `EXPLORE_BUDGET=1` from Phase 0, dispatch a single Explore covering the most important facet.
+
+Send all calls in **one message** so they run in parallel:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet A: <short label>",
+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
+)
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet B: <short label>",
+  prompt="<TARGETED sub-question>\n\n..."
+)
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet C: <short label>",
+  prompt="<TARGETED sub-question>\n\n..."
+)
+```
+
+**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.
+
+Record `explore_calls = <N>` (0 if Phase 0 abandoned but you somehow got here; 1 if reduced; up to 3 otherwise) — it lands in the final frontmatter.
+
+Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).
+
+## Phase 3 — Draft research note
+
+Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-draft.md` with **these mandatory sections, in this exact order**:
+
+```markdown
+## Findings
+- <claim> (path/to/file.rs:42)
+- <claim> (path/to/other.py:117-130)
+
+## Constraints discovered
+- <constraint with citation>
+
+## Open questions
+- <question the Explores could not resolve>
+
+## No-recommendation
+This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
+```
+
+**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.
+
+**Demotion rule.** Findings without a `file:line` citation are demoted to **Open questions** — do not silently drop them, and do not add a fake citation.
+
+**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
+  '{"location":"<section>","removed_text":"<short excerpt>"}'
+```
+
+Checkpoint: `research-draft.md` (this file).
+
+## Phase 4 — Bundled cross-LLM critique
+
+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
+
+```
+Agent(
+  subagent_type="gemini-consultant",
+  description="Research review (Gemini) for <slug>",
+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
+)
+Agent(
+  subagent_type="codex-consultant",
+  description="Research review (Codex) for <slug>",
+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
+)
+```
+
+Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).
+
+Checkpoint: `phase4-critiques.md` (both critiques side-by-side).
+
+## Phase 5 — Revise
+
+For each consultant gap / error / missing-constraint:
+
+- **Fill it** if the orchestrator can resolve it from existing Explore returns or via a quick targeted Read.
+- **Note it as unfilled** in the `## Cross-LLM review notes` section if it would require another Explore dispatch (out of scope at this phase).
+
+Update the draft accordingly. If a consultant tried to recommend an approach despite the MODE prohibition, **strip the recommendation** and log `research_temptation` for the consultant turn.
+
+Add a `## Cross-LLM review notes` section to the draft summarizing:
+- Gemini's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
+- Codex's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
+
+Re-run the demotion rule from Phase 3: any new findings introduced during revision must carry a `file:line` citation or be demoted.
+
+Checkpoint: `research-draft.revised.md`.
+
+## Phase 6 — Finalize
+
+Compute `input_hash` per the SPEC algorithm:
+
+```
+input_hash = sha256(canonicalize(
+    question + "\n---\n" +
+    doc_fetcher_synthesis_or_empty + "\n---\n" +
+    explore_synthesis_or_empty + "\n---\n" +
+    research_md_or_empty
+)).hexdigest()[:16]
+```
+
+`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.
+
+Write final `z-harness/$Z_HARNESS_SLUG/RESEARCH.md`:
+
+```markdown
+---
+artifact: research
+slug: <slug>
+generated_at: <ISO-8601 UTC>
+command: /z-research
+input_hash: <16 hex chars>
+depends_on: []
+explore_calls: <0..3>
+status: complete
+---
+
+# Research: <question>
+
+## Findings
+<bulleted list with file:line citations>
+
+## Constraints discovered
+<bulleted list>
+
+## Open questions
+<bulleted list>
+
+## No-recommendation
+This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
+
+## Cross-LLM review notes
+<consultant feedback summary; filled vs unfilled gaps>
+```
+
+Log run end:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
+  "$(printf '{"slug":"%s","explore_calls":%d,"status":"complete"}' "$Z_HARNESS_SLUG" "<N>")"
+```
+
+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
+
+```
+Research complete. RESEARCH.md written to z-harness/<slug>/RESEARCH.md.
+
+Recommended next step:
+  /z-brainstorm <topic>  — ideate approaches grounded in this research, OR
+  /z-plan <task>         — go straight to planning if the approach is already clear
+```
+
+---
+
+## Operating principles
+
+- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant. Every temptation to recommend gets logged and removed.
+- **Citations are non-negotiable.** No `file:line` → not a finding.
+- **Cost discipline.** Phase 0 is the user's gate; respect their pick. If you exceed 2M tokens, warn.
+- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.
diff --git a/skills/z-research/SKILL.md b/skills/z-research/SKILL.md
new file mode 100644
index 0000000..a08955a
--- /dev/null
+++ b/skills/z-research/SKILL.md
@@ -0,0 +1,289 @@
+---
+description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
+argument-hint: <question or technical area to research>
+---
+
+You are running the **z-harness `/z-research`** pipeline.
+
+Question (from `$ARGUMENTS`):
+
+$ARGUMENTS
+
+**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
+
+Strict, multi-phase. Do not skip phases. `/z-research` produces a research note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.
+
+**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.
+
+## Setup
+
+1. **Derive a research slug** from the question: short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
+2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
+3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
+4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
+5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
+   ```bash
+   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
+   START_PAYLOAD="$(python3 -c '
+   import json, sys
+   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
+   print(json.dumps(v))
+   ' "$VERSION_BLOB" "<arguments>")"
+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
+   ```
+6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+7. **Artifact collision check.** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists:
+   - Archive it: `mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`
+   - Notify the user: "Existing RESEARCH.md archived. Starting fresh research."
+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
+
+**All paths in subsequent phases live under `z-harness/<slug>/`:**
+- `z-harness/<slug>/RESEARCH.md`
+- `z-harness/<slug>/archive/<run-id>/...`
+
+## Phase telemetry (mandatory)
+
+At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
+
+```bash
+WALL_MS=$(( $(date +%s%3N) - T0 ))
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
+  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
+     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
+```
+
+If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
+# ... AskUserQuestion ...
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
+```
+
+---
+
+## Phase 0 — Cost-confirmation gate
+
+Research can be expensive. The default fan-out is up to 3 parallel `Explore` subagents (Haiku) plus a bundled cross-LLM critique pass. Target spend: **≤2M tokens / 5-10 min wall time.** If you exceed 2M tokens at any point, log a `cost_warning` event and surface it to the user.
+
+Present the cost up front via `AskUserQuestion` with three options:
+
+- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores.
+- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
+- **Abandon** — exit cleanly, write nothing.
+
+Log the user's pick:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
+  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
+```
+
+If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.
+
+Checkpoint: `phase0-cost-gate.md`.
+
+## Phase 1 — Scaffolding
+
+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 2.
+
+If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
+  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
+```
+
+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
+
+Checkpoint: `phase1-scaffolding.md`.
+
+## Phase 2 — Parallel Explores
+
+Dispatch up to `EXPLORE_BUDGET` parallel `Explore` subagents (Haiku) on **distinct facets** of the question. Each Explore must answer a targeted sub-question; do not dispatch overlapping queries.
+
+**Hard cap: 3.** No env override in v1. If `EXPLORE_BUDGET=1` from Phase 0, dispatch a single Explore covering the most important facet.
+
+Send all calls in **one message** so they run in parallel:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet A: <short label>",
+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
+)
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet B: <short label>",
+  prompt="<TARGETED sub-question>\n\n..."
+)
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Facet C: <short label>",
+  prompt="<TARGETED sub-question>\n\n..."
+)
+```
+
+**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.
+
+Record `explore_calls = <N>` (0 if Phase 0 abandoned but you somehow got here; 1 if reduced; up to 3 otherwise) — it lands in the final frontmatter.
+
+Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).
+
+## Phase 3 — Draft research note
+
+Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-draft.md` with **these mandatory sections, in this exact order**:
+
+```markdown
+## Findings
+- <claim> (path/to/file.rs:42)
+- <claim> (path/to/other.py:117-130)
+
+## Constraints discovered
+- <constraint with citation>
+
+## Open questions
+- <question the Explores could not resolve>
+
+## No-recommendation
+This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
+```
+
+**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.
+
+**Demotion rule.** Findings without a `file:line` citation are demoted to **Open questions** — do not silently drop them, and do not add a fake citation.
+
+**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
+  '{"location":"<section>","removed_text":"<short excerpt>"}'
+```
+
+Checkpoint: `research-draft.md` (this file).
+
+## Phase 4 — Bundled cross-LLM critique
+
+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
+
+```
+Agent(
+  subagent_type="gemini-consultant",
+  description="Research review (Gemini) for <slug>",
+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
+)
+Agent(
+  subagent_type="codex-consultant",
+  description="Research review (Codex) for <slug>",
+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
+)
+```
+
+Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).
+
+Checkpoint: `phase4-critiques.md` (both critiques side-by-side).
+
+## Phase 5 — Revise
+
+For each consultant gap / error / missing-constraint:
+
+- **Fill it** if the orchestrator can resolve it from existing Explore returns or via a quick targeted Read.
+- **Note it as unfilled** in the `## Cross-LLM review notes` section if it would require another Explore dispatch (out of scope at this phase).
+
+Update the draft accordingly. If a consultant tried to recommend an approach despite the MODE prohibition, **strip the recommendation** and log `research_temptation` for the consultant turn.
+
+Add a `## Cross-LLM review notes` section to the draft summarizing:
+- Gemini's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
+- Codex's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
+
+Re-run the demotion rule from Phase 3: any new findings introduced during revision must carry a `file:line` citation or be demoted.
+
+Checkpoint: `research-draft.revised.md`.
+
+## Phase 6 — Finalize
+
+Compute `input_hash` per the SPEC algorithm:
+
+```
+input_hash = sha256(canonicalize(
+    question + "\n---\n" +
+    doc_fetcher_synthesis_or_empty + "\n---\n" +
+    explore_synthesis_or_empty + "\n---\n" +
+    research_md_or_empty
+)).hexdigest()[:16]
+```
+
+`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.
+
+Write final `z-harness/$Z_HARNESS_SLUG/RESEARCH.md`:
+
+```markdown
+---
+artifact: research
+slug: <slug>
+generated_at: <ISO-8601 UTC>
+command: /z-research
+input_hash: <16 hex chars>
+depends_on: []
+explore_calls: <0..3>
+status: complete
+---
+
+# Research: <question>
+
+## Findings
+<bulleted list with file:line citations>
+
+## Constraints discovered
+<bulleted list>
+
+## Open questions
+<bulleted list>
+
+## No-recommendation
+This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
+
+## Cross-LLM review notes
+<consultant feedback summary; filled vs unfilled gaps>
+```
+
+Log run end:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
+  "$(printf '{"slug":"%s","explore_calls":%d,"status":"complete"}' "$Z_HARNESS_SLUG" "<N>")"
+```
+
+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
+
+```
+Research complete. RESEARCH.md written to z-harness/<slug>/RESEARCH.md.
+
+Recommended next step:
+  /z-brainstorm <topic>  — ideate approaches grounded in this research, OR
+  /z-plan <task>         — go straight to planning if the approach is already clear
+```
+
+---
+
+## Operating principles
+
+- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant. Every temptation to recommend gets logged and removed.
+- **Citations are non-negotiable.** No `file:line` → not a finding.
+- **Cost discipline.** Phase 0 is the user's gate; respect their pick. If you exceed 2M tokens, warn.
+- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.

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
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug — promote to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating code already in the diff. No summaries. No restating the spec.
- If no blockers or majors, respond with exactly: `No blockers or majors found.` (plus optional 1-line note).

codex
I’ll check the existing `/z-brainstorm` command and nearby consultant/doc-fetcher conventions so the review is grounded in the current harness behavior, not just the pasted diff.
exec
/bin/zsh -lc "sed -n '1,260p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
2. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/<slug>/` exists AND already contains `BRAINSTORM.md`, prompt the user via `AskUserQuestion`:
   - **overwrite** — archive existing `BRAINSTORM.md` to `archive/<RUN>/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer) and start fresh
   - **append-to-new-run** — keep `BRAINSTORM.md` in place but write this run's output to a fresh RUN-scoped path and ask the user later whether to promote it
   - **abort** — exit cleanly with no changes
3. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
5. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
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
7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.

**All paths live under `z-harness/<slug>/`:**
- `z-harness/<slug>/BRAINSTORM.md`
- `z-harness/<slug>/archive/<RUN>/...`

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

If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, read it.

- **≤20 KB:** inline the full content into the scaffolding payload.
- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.

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

Checkpoint: write the assembled scaffolding to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/phase1-scaffolding.md`.

---

## Phase 2 — Parallel ideator dispatch

Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Claude ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\nReturn exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point."
)
Agent(
  subagent_type="codex-consultant",
  description="Codex ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
)
Agent(
  subagent_type="gemini-consultant",
  description="Gemini ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>"
)
```

Both consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.

### Ideator failure policy

Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.

- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<vendor>:failed"` in the `ideators` frontmatter list. The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
- **2/3 fail** → halt. Use `AskUserQuestion` with options:
  - **retry** (default) — re-dispatch the failed ideators once
  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
  - **abandon** — set frontmatter `status: abandoned` and exit
- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.

Log every individual failure as `ideator_failed` regardless of the bucket above.

---

## Phase 3 — Synthesis + mandatory anti-bias check

1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.

2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.

3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.

4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:

   ```yaml
   ---
   artifact: brainstorm
   slug: <slug>
   generated_at: <UTC ISO 8601>
   command: /z-brainstorm <args>
   input_hash: <16 hex from Phase 1d>
   depends_on: [<RESEARCH.md if ingested>]
   ideators:
     - claude-sonnet
     - codex
     - gemini
     # failed members recorded as "<vendor>:failed"
   status: complete
   ---
   ```

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

   ## User choice
   <filled in Phase 4>
   ```

5. **Present** the three framings + anti-bias check + recommendation to the user via `AskUserQuestion`. Options:
   - One option per available framing (e.g. **Claude framing**, **Codex framing**, **Gemini framing** — only for ideators that succeeded)
   - **Restart** — discard this run and re-run with a refined topic
   - **Abandon** — exit cleanly without finalizing

Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.

---

## Phase 4 — Finalize

Branch on the user's Phase 3 choice:

### User picked a framing

1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter to the picked ideator name (`claude` | `codex` | `gemini`).
2. Append a `## User choice` body section with the picked framing's text reproduced verbatim (so `/z-plan` can find it without re-parsing the ideator blocks) plus any free-text refinement the user provided.
3. Confirm `status: complete` in the frontmatter.

### User picked Restart

1. Archive the just-written BRAINSTORM.md to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer).
2. Ask the user (free-text or `AskUserQuestion`) for the refined topic.
3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.

### User picked Abandon

1. Set the frontmatter `status: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.

### In all branches

Log `brainstorm_run_end`:

```bash

exec
/bin/zsh -lc "find . -maxdepth 3 -type f | sort | sed -n '1,220p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./.claude-plugin/marketplace.json
./.claude-plugin/plugin.json
./.claude/settings.local.json
./.git/COMMIT_EDITMSG
./.git/FETCH_HEAD
./.git/HEAD
./.git/ORIG_HEAD
./.git/config
./.git/description
./.git/hooks/applypatch-msg.sample
./.git/hooks/commit-msg.sample
./.git/hooks/fsmonitor-watchman.sample
./.git/hooks/post-update.sample
./.git/hooks/pre-applypatch.sample
./.git/hooks/pre-commit.sample
./.git/hooks/pre-merge-commit.sample
./.git/hooks/pre-push.sample
./.git/hooks/pre-rebase.sample
./.git/hooks/pre-receive.sample
./.git/hooks/prepare-commit-msg.sample
./.git/hooks/push-to-checkout.sample
./.git/hooks/update.sample
./.git/index
./.git/info/exclude
./.git/logs/HEAD
./.gitignore
./.z-harness-rsync-exclude
./README.md
./agents/auditor.md
./agents/codex-consultant.md
./agents/codex-reviewer.md
./agents/complexity-classifier.md
./agents/doc-fetcher.md
./agents/doc-updater.md
./agents/gemini-consultant.md
./agents/implementer.md
./agents/remote-runner.md
./agents/spec-precheck.md
./brainstorm-and-research/PLAN.md
./brainstorm-and-research/SPEC.md
./brainstorm-and-research/TASKS.md
./brainstorm-and-research/escalation.md
./commands/z-amend.md
./commands/z-audit.md
./commands/z-brainstorm.md
./commands/z-debug.md
./commands/z-do.md
./commands/z-implement-all.md
./commands/z-implement-next.md
./commands/z-improve.md
./commands/z-init-docs.md
./commands/z-maintain-docs.md
./commands/z-plan-light.md
./commands/z-plan.md
./commands/z-research.md
./commands/z-review-all.md
./commands/z-skill-fix.md
./commands/z-stats.md
./commands/z-test.md
./per-task-model-selection/FIX.md
./plugin.json
./scripts/log-event.sh
./scripts/log-phase.sh
./scripts/remote-sandbox-sync.sh
./scripts/version.sh
./skills/z-amend/SKILL.md
./skills/z-brainstorm/SKILL.md
./skills/z-debug/SKILL.md
./skills/z-do/SKILL.md
./skills/z-implement-all/SKILL.md
./skills/z-implement-next/SKILL.md
./skills/z-improve/SKILL.md
./skills/z-init-docs/SKILL.md
./skills/z-maintain-docs/SKILL.md
./skills/z-plan-light/SKILL.md
./skills/z-plan/SKILL.md
./skills/z-research/SKILL.md
./skills/z-review-all/SKILL.md
./skills/z-stats/SKILL.md
./skills/z-test/SKILL.md
./z-harness/brainstorm-and-research/PLAN.md
./z-harness/brainstorm-and-research/SPEC.md
./z-harness/brainstorm-and-research/TASKS.md
./z-harness/metrics.jsonl

exec
/bin/zsh -lc 'rg -n "research-review|brainstorm-review|gemini-consultant|codex-consultant|doc-fetcher|PushNotification|phase_end|cost_gate|input_hash|research_run" -S .' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./skills/z-review-all/SKILL.md:121:  subagent_type="gemini-consultant",
./skills/z-review-all/SKILL.md:126:  subagent_type="codex-consultant",
./skills/z-research/SKILL.md:35:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
./skills/z-research/SKILL.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./skills/z-research/SKILL.md:53:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./skills/z-research/SKILL.md:81:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
./skills/z-research/SKILL.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./skills/z-research/SKILL.md:95:  subagent_type="doc-fetcher",
./skills/z-research/SKILL.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./skills/z-research/SKILL.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./skills/z-research/SKILL.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./skills/z-research/SKILL.md:186:  subagent_type="gemini-consultant",
./skills/z-research/SKILL.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./skills/z-research/SKILL.md:191:  subagent_type="codex-consultant",
./skills/z-research/SKILL.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./skills/z-research/SKILL.md:220:Compute `input_hash` per the SPEC algorithm:
./skills/z-research/SKILL.md:223:input_hash = sha256(canonicalize(
./skills/z-research/SKILL.md:241:input_hash: <16 hex chars>
./skills/z-research/SKILL.md:268:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
./skills/z-research/SKILL.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./skills/z-debug/SKILL.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./skills/z-debug/SKILL.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./skills/z-debug/SKILL.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./skills/z-debug/SKILL.md:142:  subagent_type="gemini-consultant",
./skills/z-debug/SKILL.md:147:  subagent_type="codex-consultant",
./skills/z-improve/SKILL.md:56:| Slow phase | `max(phase_end.wall_ms) - min(phase_end.wall_ms)` outliers; phases taking >2x median | any phase taking >5 min, or >3x the run's median |
./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./skills/z-do/SKILL.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./skills/z-do/SKILL.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./skills/z-do/SKILL.md:50:## Phase 2 — Ground (doc-fetcher first)
./skills/z-do/SKILL.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./skills/z-brainstorm/SKILL.md:49:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./skills/z-brainstorm/SKILL.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./skills/z-brainstorm/SKILL.md:74:  subagent_type="doc-fetcher",
./skills/z-brainstorm/SKILL.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./skills/z-brainstorm/SKILL.md:108:Compute the `input_hash` per SPEC:
./skills/z-brainstorm/SKILL.md:111:input_hash = sha256(canonicalize(
./skills/z-brainstorm/SKILL.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./skills/z-brainstorm/SKILL.md:137:  subagent_type="codex-consultant",
./skills/z-brainstorm/SKILL.md:142:  subagent_type="gemini-consultant",
./skills/z-brainstorm/SKILL.md:181:   input_hash: <16 hex from Phase 1d>
./skills/z-brainstorm/SKILL.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./skills/z-brainstorm/SKILL.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./skills/z-maintain-docs/SKILL.md:59:  subagent_type="gemini-consultant",
./skills/z-maintain-docs/SKILL.md:64:  subagent_type="codex-consultant",
./agents/gemini-consultant.md:2:name: gemini-consultant
./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./agents/gemini-consultant.md:30:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./skills/z-implement-next/SKILL.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./agents/codex-consultant.md:2:name: codex-consultant
./agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./agents/codex-consultant.md:64:     - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
./agents/codex-consultant.md:87:For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
./skills/z-implement-all/SKILL.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./skills/z-plan/SKILL.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./skills/z-plan/SKILL.md:66:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./skills/z-plan/SKILL.md:79:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
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
./skills/z-plan/SKILL.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./skills/z-plan/SKILL.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./skills/z-plan/SKILL.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./skills/z-plan/SKILL.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./skills/z-plan/SKILL.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./skills/z-plan/SKILL.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./skills/z-plan/SKILL.md:253:- codex-consultant: same.
./skills/z-plan/SKILL.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./archive/plan-review/transcripts/001-codex-plan-review.response.md:4:   SPEC requires ideators to return exactly five sections for `/z-brainstorm` [SPEC.md:169](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:169), but later says both new consultant modes follow the existing consultant return shape with recommendation/reasoning/tradeoffs/etc. [SPEC.md:268](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:268). Existing consultants also hard-code that shape [agents/codex-consultant.md:49](/Users/zeke/dev/z-harness/agents/codex-consultant.md:49). An implementer could preserve consultant consistency and break brainstorm parsing, or preserve brainstorm parsing and violate the stated agent pattern.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:18:6. **`/z-plan` "optional doc-fetcher and Explore" may conflict with current Phase 1 rule.**  
./archive/plan-review/transcripts/001-codex-plan-review.response.md:19:   Existing `/z-plan` says "doc-fetcher FIRST, Explore for gaps" and spawns doc-fetcher if docs exist [commands/z-plan.md:90](/Users/zeke/dev/z-harness/commands/z-plan.md:90). SPEC says if fresh `RESEARCH.md` exists, doc-fetcher and Explore are optional [SPEC.md:296](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:296). That is a behavioral change, not just scaffolding, and the boundary between "research is enough" and "Phase 1 must still run" is vague.
./archive/plan-review/transcripts/001-codex-plan-review.response.md:31:    New logs include `tokens_spent`, `ideator_durations_ms`, `consultant_durations_ms`, and `findings_count` [SPEC.md:191](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:191), [SPEC.md:250](/Users/zeke/dev/z-harness/brainstorm-and-research/SPEC.md:250). Existing consultant logging has prompt/response chars and wall time, not token counts [agents/codex-consultant.md:81](/Users/zeke/dev/z-harness/agents/codex-consultant.md:81). Implementers may invent incompatible approximations.
./skills/z-plan-light/SKILL.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./skills/z-plan-light/SKILL.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./skills/z-plan-light/SKILL.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./skills/z-plan-light/SKILL.md:80:  subagent_type="gemini-consultant",
./skills/z-plan-light/SKILL.md:85:  subagent_type="codex-consultant",
./skills/z-plan-light/SKILL.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./skills/z-test/SKILL.md:110:  subagent_type="gemini-consultant",
./skills/z-test/SKILL.md:115:  subagent_type="codex-consultant",
./skills/z-test/SKILL.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./skills/z-test/SKILL.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./archive/plan-review/transcripts/001-codex-plan-review.prompt.md:10:- Agent extensions: MODE: brainstorm and MODE: research-review added to codex-consultant and gemini-consultant.
./commands/z-review-all.md:121:  subagent_type="gemini-consultant",
./commands/z-review-all.md:126:  subagent_type="codex-consultant",
./agents/doc-fetcher.md:2:name: doc-fetcher
./skills/z-amend/SKILL.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./brainstorm-and-research/escalation.md:8:- `/z-research <question>` — heavier doc-fetcher + Explore + cross-LLM perspective dump, no plan commitment.
./commands/z-improve.md:56:| Slow phase | `max(phase_end.wall_ms) - min(phase_end.wall_ms)` outliers; phases taking >2x median | any phase taking >5 min, or >3x the run's median |
./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./commands/z-implement-next.md:96:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./brainstorm-and-research/TASKS.md:9:    - `## Modes` section gains two new entries (brainstorm, research-review) following the existing pattern.
./brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./brainstorm-and-research/TASKS.md:53:    - Setup mirrors `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
./brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./brainstorm-and-research/TASKS.md:60:    - Phase 6: write final `RESEARCH.md` with YAML frontmatter (artifact, slug, generated_at, command, input_hash, depends_on=none, explore_calls). `log-event.sh research_run_end`. Push-notify with next-step.
./brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./brainstorm-and-research/TASKS.md:96:    - New event types listed (brainstorm_run_*, research_run_*, ideator_failed, etc.) in the "Layout" or telemetry section if such exists.
./brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./commands/z-debug.md:31:7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Repro) and Phase 3 (Hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.
./commands/z-debug.md:121:If INDEX.json exists, dispatch `doc-fetcher` (Haiku) FIRST to scope:
./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./commands/z-debug.md:127:Then read additional files only to fill gaps doc-fetcher couldn't cover. Propose **2-3 hypotheses**, ranked by likelihood. For each:
./commands/z-debug.md:142:  subagent_type="gemini-consultant",
./commands/z-debug.md:147:  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/SPEC.md:26:input_hash: <16 hex chars — see input_hash algorithm>
./z-harness/brainstorm-and-research/SPEC.md:84:input_hash: <16 hex>
./z-harness/brainstorm-and-research/SPEC.md:112:## input_hash algorithm
./z-harness/brainstorm-and-research/SPEC.md:115:input_hash = sha256(canonicalize(
./z-harness/brainstorm-and-research/SPEC.md:127:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/SPEC.md:129:- **Caller provides:** topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/SPEC.md:138:### MODE: research-review (both consultants)
./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/SPEC.md:154:  - Codex: `codex-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/SPEC.md:155:  - Gemini: `gemini-consultant`, `MODE: brainstorm`
./z-harness/brainstorm-and-research/SPEC.md:173:- **Setup:** mirrors /z-brainstorm; `research_run_start` event.
./z-harness/brainstorm-and-research/SPEC.md:175:- **Phase 1:** doc-fetcher dispatch iff INDEX.json exists.
./z-harness/brainstorm-and-research/SPEC.md:178:- **Phase 4 (Critique):** bundled cross-LLM critique — `MODE: research-review` on both consultants, parallel dispatch.
./z-harness/brainstorm-and-research/SPEC.md:180:- **Phase 6 (Finalize):** write final RESEARCH.md; `research_run_end` event; push-notify with next-step.
./z-harness/brainstorm-and-research/SPEC.md:217:"If RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/SPEC.md:220:- Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/SPEC.md:233:- `research_run_start`, `research_run_end`
./z-harness/brainstorm-and-research/SPEC.md:244:- No doc-fetcher caching across precontext + plan runs (marked as v2 candidate; cheap enough today).
./commands/z-plan-light.md:33:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./commands/z-plan-light.md:56:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./commands/z-plan-light.md:62:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./commands/z-plan-light.md:80:  subagent_type="gemini-consultant",
./commands/z-plan-light.md:85:  subagent_type="codex-consultant",
./commands/z-plan-light.md:104:Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."
./brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./brainstorm-and-research/SPEC.md:73:- `input_hash` MUST be computed deterministically (same inputs → same hash) so re-runs are detectable.
./brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./brainstorm-and-research/SPEC.md:223:**Setup**: same shape as `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
./brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./brainstorm-and-research/SPEC.md:242:**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
./brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./brainstorm-and-research/SPEC.md:250:- `log-event.sh research_run_end` with `{status, tokens_spent, explore_calls, consultant_durations_ms, findings_count}`.
./brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./brainstorm-and-research/SPEC.md:283:- Read each artifact's YAML frontmatter (`generated_at`, `input_hash`, `depends_on`).
./brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./brainstorm-and-research/SPEC.md:344:- `research-review`: returns gaps-to-fill, errors-to-correct, undocumented constraints. No "recommendation" line — explicitly forbidden in this mode.
./brainstorm-and-research/SPEC.md:346:The consultant agent files must call this out: "For modes brainstorm and research-review, return raw content per the mode's prescribed shape. Do NOT wrap in the standard return shape."
./brainstorm-and-research/SPEC.md:348:### `input_hash` algorithm
./brainstorm-and-research/SPEC.md:351:input_hash = sha256(canonicalize(
./brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./brainstorm-and-research/SPEC.md:398:Use the existing `log-event.sh consult` payload shape: `{llm, mode, prompt_chars, response_chars, wall_ms, transcript}`. Token counts are NOT in spec — `/z-stats` can approximate via char ratio. New event types added for the new commands: `brainstorm_run_start`, `brainstorm_run_end`, `research_run_start`, `research_run_end`, `ideator_failed`, `total_ideator_failure`, `precontext_stale`, `precontext_source_deleted`, `precontext_freshness_check_failed`, `research_temptation`.
./brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./commands/z-plan.md:38:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./commands/z-plan.md:66:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./commands/z-plan.md:79:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
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
./commands/z-plan.md:145:  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./commands/z-plan.md:194:Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./commands/z-plan.md:200:- `Agent(subagent_type="gemini-consultant", ...)`
./commands/z-plan.md:201:- `Agent(subagent_type="codex-consultant", ...)`
./commands/z-plan.md:218:If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./commands/z-plan.md:252:- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./commands/z-plan.md:253:- codex-consultant: same.
./commands/z-plan.md:287:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./commands/z-amend.md:108:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./commands/z-do.md:2:description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
./commands/z-do.md:6:You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
./commands/z-do.md:50:## Phase 2 — Ground (doc-fetcher first)
./commands/z-do.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/PLAN.md:17:| D7 | New `MODE: research-review` for /z-research critique | A (new mode, not reuse `light-fix`) | Consultant return shape differs: light-fix asks for a recommendation; research-review explicitly forbids one. Reusing modes invites prompt drift. |
./z-harness/brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./z-harness/brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./brainstorm-and-research/PLAN.md:17:| D7 | New `MODE: research-review` for /z-research critique | A (new mode, not reuse `light-fix`) | Consultant return shape differs: light-fix asks for a recommendation; research-review explicitly forbids one. Reusing modes invites prompt drift. |
./brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./commands/z-maintain-docs.md:59:  subagent_type="gemini-consultant",
./commands/z-maintain-docs.md:64:  subagent_type="codex-consultant",
./commands/z-research.md:35:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
./commands/z-research.md:41:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./commands/z-research.md:53:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./commands/z-research.md:81:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
./commands/z-research.md:91:**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./commands/z-research.md:95:  subagent_type="doc-fetcher",
./commands/z-research.md:109:**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./commands/z-research.md:126:  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./commands/z-research.md:182:Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./commands/z-research.md:186:  subagent_type="gemini-consultant",
./commands/z-research.md:188:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./commands/z-research.md:191:  subagent_type="codex-consultant",
./commands/z-research.md:193:  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./commands/z-research.md:220:Compute `input_hash` per the SPEC algorithm:
./commands/z-research.md:223:input_hash = sha256(canonicalize(
./commands/z-research.md:241:input_hash: <16 hex chars>
./commands/z-research.md:268:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
./commands/z-research.md:272:Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./commands/z-brainstorm.md:49:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./commands/z-brainstorm.md:70:If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./commands/z-brainstorm.md:74:  subagent_type="doc-fetcher",
./commands/z-brainstorm.md:91:  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./commands/z-brainstorm.md:108:Compute the `input_hash` per SPEC:
./commands/z-brainstorm.md:111:input_hash = sha256(canonicalize(
./commands/z-brainstorm.md:127:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./commands/z-brainstorm.md:137:  subagent_type="codex-consultant",
./commands/z-brainstorm.md:142:  subagent_type="gemini-consultant",
./commands/z-brainstorm.md:181:   input_hash: <16 hex from Phase 1d>
./commands/z-brainstorm.md:231:Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./commands/z-brainstorm.md:287:- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/TASKS.md:5:- [x] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**  (2 blockers + 1 major resolved cycle 2)
./z-harness/brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./z-harness/brainstorm-and-research/TASKS.md:9:    - `## Modes` section gains two new entries (brainstorm, research-review) following the existing pattern.
./z-harness/brainstorm-and-research/TASKS.md:16:- [x] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**  (reviewer clean)
./z-harness/brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./z-harness/brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./z-harness/brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./z-harness/brainstorm-and-research/TASKS.md:53:    - Setup mirrors `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
./z-harness/brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/brainstorm-and-research/TASKS.md:60:    - Phase 6: write final `RESEARCH.md` with YAML frontmatter (artifact, slug, generated_at, command, input_hash, depends_on=none, explore_calls). `log-event.sh research_run_end`. Push-notify with next-step.
./z-harness/brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./z-harness/brainstorm-and-research/TASKS.md:96:    - New event types listed (brainstorm_run_*, research_run_*, ideator_failed, etc.) in the "Layout" or telemetry section if such exists.
./z-harness/brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:118:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:128:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:131:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:133:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:137:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:154:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:163:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:286:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:301:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:304:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:306:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:310:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:327:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:337:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:530:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:727:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:980:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1177:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:85:- **A. Start of Phase 0 (Premise check).** Read the artifacts at the very top; let them inform the premise statement. Phase 1 (Exploration) skips doc-fetcher/Explore if RESEARCH.md is recent and complete.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:95:## D7. Should consultants get a new MODE: research-review, or reuse MODE: light-fix?
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:100:- **A. New `MODE: research-review`.** Explicit purpose: "critique this research note for missing findings, wrong claims, undocumented constraints."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md:104:**Tentative call:** **A**. The consultant return shape and prompting differ: light-fix asks for a *recommendation*; research-review asks for *gaps and incorrect claims, no recommendation*. Reusing modes that mean different things invites prompt drift.
./commands/z-test.md:110:  subagent_type="gemini-consultant",
./commands/z-test.md:115:  subagent_type="codex-consultant",
./commands/z-test.md:141:Send `PushNotification` (if policy != `off`): "Test plan ready for review."
./commands/z-test.md:227:- **No new agents dispatched.** Reuses `gemini-consultant` and `codex-consultant` only.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:22:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:113:6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.
./commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:9:1. **Consultant return-shape conflict (Codex F1).** The existing consultant return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt) is for *validation* modes. The new `MODE: brainstorm` returns a 5-section ideator block; `MODE: research-review` returns a critique-block (gaps to fill / errors to correct / no recommendation). SPEC clarifies: these two new modes DO NOT use the standard wrapper. They return raw ideator/critique content. The wrapper exists for validation modes only.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:17:6. **Phase 1 boundary tightened (Codex F6).** Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set. Skip Explore iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:21:10. **input_hash computation (Gemini).** Add to spec: `input_hash = sha256(canonicalize(topic + "\n---\n" + doc_fetcher_or_empty + "\n---\n" + explore_or_empty + "\n---\n" + research_or_empty))` where canonicalize strips leading/trailing whitespace and collapses internal whitespace to single spaces.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase7-review-synthesis.md:32:- **doc-fetcher caching (Gemini).** Out of scope, marked as v2 candidate. Cheap-enough today.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:5:- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:6:  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:9:    - `## Modes` section gains two new entries (brainstorm, research-review) following the existing pattern.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:16:- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:17:  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:19:  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:33:    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:34:    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:53:    - Setup mirrors `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:55:    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:60:    - Phase 6: write final `RESEARCH.md` with YAML frontmatter (artifact, slug, generated_at, command, input_hash, depends_on=none, explore_calls). `log-event.sh research_run_end`. Push-notify with next-step.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:79:    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:96:    - New event types listed (brainstorm_run_*, research_run_*, ideator_failed, etc.) in the "Layout" or telemetry section if such exists.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:97:    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase0-premise.md:13:**One reason this might be wrong (mechanical pushback):** these commands might be rarely used in practice. If 90% of `/z-plan` runs don't need pre-plan exploration, we're adding 2 commands + 4 files of harness surface area for narrow value. Mitigation: ship as opt-in; if usage data after some weeks shows <5% adoption, deprecate. Adding telemetry (`brainstorm_run_start` / `research_run_start` events) lets `/z-stats` answer this empirically.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase0-premise.md:17:Build two opt-in slash commands that the user invokes when they explicitly want pre-plan exploration. `/z-brainstorm` is a cheap fan-out across model vendors (Claude / Codex / Gemini) producing N candidate problem-framings; the user picks one. `/z-research` is a heavier terrain-mapping pass using doc-fetcher + Explore + cross-LLM critique that produces a findings note with no recommendation. Both are chainable into `/z-plan` (which reads their artifacts as Phase-0 seed context).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:3:No `docs/llm/INDEX.json` in z-harness repo (it's a meta-harness, agent/command markdown files ARE the docs). doc-fetcher skipped. No Explore dispatched — main thread already has the relevant context from prior /z-plan-light runs in this conversation.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase1-context.md:7:The z-harness plugin lives at `/Users/zeke/dev/z-harness/` with parallel `commands/` and `skills/` directories — each slash command is hand-maintained as both a `commands/<name>.md` and a `skills/<name>/SKILL.md` mirror. New commands must be authored twice. The `agents/` directory holds subagent definitions; `codex-consultant.md` and `gemini-consultant.md` already implement a multi-mode pattern with `MODE:` discriminator (existing modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-audit`, `test-cases`). Adding `MODE: brainstorm` (ideation) and possibly `MODE: research-review` (research-note critique) fits the existing pattern. The `Explore` subagent (built into the harness) is dispatched via `Agent(subagent_type="Explore", model="haiku", ...)` and the `doc-fetcher` (Haiku) reads `docs/llm/` two-tier docs cheaply. `/z-plan` Phase 0 is the premise-check entry point — that's where seed-artifact (BRAINSTORM.md / RESEARCH.md) detection will hook in. `scripts/log-event.sh` accepts `$RUN` and `$Z_HARNESS_SLUG` and writes to `z-harness/<slug>/archive/<run>/events.jsonl`; new commands will follow the same convention. Slug derivation today is per-command (each `/z-plan` and `/z-plan-light` derives independently); a chain of `/z-research` → `/z-brainstorm` → `/z-plan` raises a slug-sharing question.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:10:- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:11:- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:29:input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:40:**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:73:- `input_hash` MUST be computed deterministically (same inputs → same hash) so re-runs are detectable.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:91:input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:153:**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:154:- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:159:Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:165:  doc-fetcher: <synthesis or "n/a">
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:211:description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:223:**Setup**: same shape as `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:228:**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:242:**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:243:Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:250:- `log-event.sh research_run_end` with `{status, tokens_spent, explore_calls, consultant_durations_ms, findings_count}`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:260:### `agents/codex-consultant.md` and `agents/gemini-consultant.md`
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:264:**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:283:- Read each artifact's YAML frontmatter (`generated_at`, `input_hash`, `depends_on`).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:296:"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:329:- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:341:`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:344:- `research-review`: returns gaps-to-fill, errors-to-correct, undocumented constraints. No "recommendation" line — explicitly forbidden in this mode.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:346:The consultant agent files must call this out: "For modes brainstorm and research-review, return raw content per the mode's prescribed shape. Do NOT wrap in the standard return shape."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:348:### `input_hash` algorithm
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:351:input_hash = sha256(canonicalize(
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:389:- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:398:Use the existing `log-event.sh consult` payload shape: `{llm, mode, prompt_chars, response_chars, wall_ms, transcript}`. Token counts are NOT in spec — `/z-stats` can approximate via char ratio. New event types added for the new commands: `brainstorm_run_start`, `brainstorm_run_end`, `research_run_start`, `research_run_end`, `ideator_failed`, `total_ideator_failure`, `precontext_stale`, `precontext_source_deleted`, `precontext_freshness_check_failed`, `research_temptation`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:403:- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:417:- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
./commands/z-audit.md:33:7. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./commands/z-audit.md:129:  subagent_type="gemini-consultant",
./commands/z-audit.md:134:  subagent_type="codex-consultant",
./commands/z-audit.md:218:Send `PushNotification` (if policy != `off`): "Audit complete — <N> tasks queued."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:126:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:136:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:139:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:141:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:145:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:162:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:164:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:171:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:302:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:317:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:320:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:322:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:326:+  subagent_type="doc-fetcher",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:343:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:346:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:353:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:560:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:562:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:757:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:759:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:37:6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.
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
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:672:Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:730:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:915:3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1028:Block until answered. Send a `PushNotification` if policy ≠ `off`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1042:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1044:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1183:    92	3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:1:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:15:### MODE: research-review (both consultants)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:25:- ## Modes gains brainstorm + research-review entries following existing pattern
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:27:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:29:- research-review redefined IN PLACE (not duplicated)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:33:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:36:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:39:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:45:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:49:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:61:The "Building the prompt to Codex" and "Returning to the caller" sections still only reference bundled-decisions and plan-review modes (no instructions for raw return shape for brainstorm/research-review modes).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:11:Consultant subagents (codex-consultant, gemini-consultant) are multi-mode, discriminated by MODE: <name> prefix. Modes are fully isolated — different return shapes, different prompting.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:15:- Phase 1: Exploration (2-tier: doc-fetcher Haiku first, then Explore for gaps; capped at 3 Explores per run)
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:92:1. Consultant subagents (codex-consultant.md, gemini-consultant.md) declare MODE: at the top of the caller's prompt. Each mode has its own return shape, prompt structure, and archive naming.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/003-gemini-bundled-decisions.prompt.md:100:3. The two-tier docs (docs/llm/INDEX.json + docs/llm/<concept>.json) are read by doc-fetcher (Haiku) in Phase 1, never by the main orchestrator thread.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:17:| D7 | New `MODE: research-review` for /z-research critique | A (new mode, not reuse `light-fix`) | Consultant return shape differs: light-fix asks for a recommendation; research-review explicitly forbids one. Reusing modes invites prompt drift. |
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:39:- T001: Add `MODE: brainstorm` and `MODE: research-review` to `agents/codex-consultant.md`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/PLAN.md:40:- T002: Add `MODE: brainstorm` and `MODE: research-review` to `agents/gemini-consultant.md`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/phase3-decisions-final.md:16:1. **YAML frontmatter on artifacts:** Each `BRAINSTORM.md` / `RESEARCH.md` opens with a frontmatter block: `artifact: brainstorm|research`, `slug:`, `generated_at:`, `command:`, `input_hash:` (sha256 of the topic + scaffolding inputs), `depends_on:` (path to upstream artifact if chained). Replaces the need for a manifest file (Codex).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.prompt.md:9:- Consultant subagents (`codex-consultant`, `gemini-consultant`) are multi-mode with a `MODE: <name>` discriminator.
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:1:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:5:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:6:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:15:### MODE: research-review (both consultants)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:21:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:25:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:29:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:32:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:60:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:122:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:125:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:41:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:47:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:59:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:87:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:97:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:101:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:115:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:132:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:188:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:192:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:194:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:197:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:199:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:226:+Compute `input_hash` per the SPEC algorithm:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:229:+input_hash = sha256(canonicalize(
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:247:+input_hash: <16 hex chars>
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:274:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:278:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:336:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:342:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:354:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:382:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:392:+**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:396:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:410:+**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:427:+  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:483:+Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:487:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:489:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:492:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:494:+  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:521:+Compute `input_hash` per the SPEC algorithm:
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:524:+input_hash = sha256(canonicalize(
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:542:+input_hash: <16 hex chars>
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:569:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
./z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch:573:+Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:34:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:35:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:38:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:41:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:43:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:47:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:48:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.response.md:50:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:55:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:76:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:80:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:97:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:114:+Compute the `input_hash` per SPEC:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:117:+input_hash = sha256(canonicalize(
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:133:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:143:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:148:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:187:+   input_hash: <16 hex from Phase 1d>
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:237:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:293:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:349:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:370:+If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:374:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:391:+  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:408:+Compute the `input_hash` per SPEC:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:411:+input_hash = sha256(canonicalize(
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:427:+Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:437:+  subagent_type="codex-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:442:+  subagent_type="gemini-consultant",
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:481:+   input_hash: <16 hex from Phase 1d>
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:531:+Block until the user answers. Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:587:+- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:1:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:5:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:8:+name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:40:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:70:+     - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:93:+For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:4: diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:9: +++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:13: +name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:31:++     - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
./z-harness/brainstorm-and-research/archive/tasks/T001/delta-v2.patch:46:++For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:16:You are reviewing code that Claude just wrote for task T002: Add MODE: brainstorm + redefine MODE: research-review in gemini-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:30:### MODE: research-review (both consultants)
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:36:Acceptance criteria: same as T001, applied to gemini-consultant.md — i.e., add MODE: brainstorm bullet, redefine MODE: research-review bullet to match the schema and RAW-return contract above.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:40:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:44:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:47:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:75:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:137:For reference, the parity sibling codex-consultant.md (T001) contains these mode bullets:
./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:140:- research-review: "Does NOT use the standard return wrapper. Return RAW with exactly these sections: Gaps / Errors / Missing constraints. Codex must NOT recommend an approach ... The prompt must explicitly instruct Codex to omit any recommendation."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:28:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:88:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:116:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:129:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:151:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:152:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:155:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:157:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:159:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:161:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:165:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:181:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:183:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:190:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:239:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:245:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:246:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:263:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:297:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:298:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:332:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:399:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:427:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:440:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:462:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:463:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:466:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:468:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:470:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:472:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:476:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:492:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:494:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:501:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:550:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:556:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:557:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:574:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:608:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:609:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:643:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:1:diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:5:+++ b/agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:8:+name: gemini-consultant
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:36:+- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis, optional Explore findings, optional RESEARCH.md content or extractive summary). Ask Gemini to produce an ideator block. **Return RAW — no standard wrapper.** The block must contain exactly five sections (mark `<missing>` only if the model truly cannot produce a section):
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:1:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./README.md:42:| `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
./README.md:43:| `codex-consultant` | (CLI) | Cross-LLM consult via Codex |
./README.md:60:- Claude Code with `PushNotification` available (for mobile notifications).
./README.md:97:- Skills that orchestrate should call cross-LLM consult (`gemini-consultant`, `codex-consultant`) at premise / red-team gates, not run them inline.
./README.md:135:│   ├── codex-consultant.md
./README.md:136:│   ├── gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:16:You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:20:### MODE: brainstorm (both codex-consultant and gemini-consultant)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:21:- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:30:### MODE: research-review (both consultants)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:40:- ## Modes gains brainstorm + research-review entries following existing pattern
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:42:- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:44:- research-review redefined IN PLACE (not duplicated)
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:48:diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:51:+++ b/agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:54:name: codex-consultant
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:60:[file content as in the diff — full final state of the codex-consultant.md agent]
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:64:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:76:The "Building the prompt to Codex" and "Returning to the caller" sections still only reference bundled-decisions and plan-review modes (no instructions for raw return shape for brainstorm/research-review modes).
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
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:343:skills/z-research/SKILL.md:67:Dispatch Gemini and Codex in parallel using `MODE: research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:344:skills/z-research/SKILL.md:73:  prompt="MODE: research-review\n\nRESEARCH.md draft:\n<content>\n\nRelevant code snippets:\n<short quoted code with file:line markers>"
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:345:skills/z-research/SKILL.md:78:  prompt="MODE: research-review\n\nRESEARCH.md draft:\n<content>\n\nRelevant code snippets:\n<short quoted code with file:line markers>"
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:354:agents/codex-consultant.md:34:- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:366:commands/z-research.md:67:Dispatch Gemini and Codex in parallel using `MODE: research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:367:commands/z-research.md:73:  prompt="MODE: research-review\n\nRESEARCH.md draft:\n<content>\n\nRelevant code snippets:\n<short quoted code with file:line markers>"
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:368:commands/z-research.md:78:  prompt="MODE: research-review\n\nRESEARCH.md draft:\n<content>\n\nRelevant code snippets:\n<short quoted code with file:line markers>"
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:371:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:373:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:375:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:379:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:60) still mandates the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw response excerpt` return wrapper for every response. This directly violates both new acceptance criteria; make the return section conditional so `brainstorm` and `research-review` return Codex’s raw section block unchanged.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:381:- **blocker**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:48) does not define prompt construction for `brainstorm` or `research-review`, and still says mode is only `"bundled decisions"` or `"plan review"` with asks tailored to those modes. Add explicit per-mode prompt templates, including the five exact `brainstorm` sections and the three exact `research-review` sections with a hard instruction to omit recommendations.
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:383:- **major**: [agents/codex-consultant.md](/Users/zeke/dev/z-harness/agents/codex-consultant.md:88) archive slug guidance only supports `codex-<bundled-decisions|plan-review>`, so new mode transcripts will be mislabeled or implemented inconsistently by the agent. Change the example to derive `SLUG="codex-$MODE"` or enumerate all supported modes, including `brainstorm` and `research-review`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:19:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:20:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:23:If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:26:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:28:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:32:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:33:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/review-v2.prompt.md:35:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:12:commands/z-implement-all.md:31:7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:98:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:122:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:135:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:155:**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:157:### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:159:If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:163:  subagent_type="doc-fetcher",
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:179:Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:181:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:222:8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:246:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:259:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:304:7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:327:1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:329:   Agent(subagent_type="doc-fetcher",
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:333:2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:436:input_hash: ...
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:72:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:85:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:107:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:108:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:111:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:113:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:115:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:117:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:121:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:137:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:139:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:146:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:195:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:201:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:202:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:219:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:253:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:254:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:288:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:355:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:383:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:396:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:418:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:419:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:422:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:424:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:426:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:428:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:432:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:448:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:450:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:457:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:506:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:512:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:513:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:530:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:564:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:565:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:599:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:16:You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:110:?? agents/doc-fetcher.md
./z-harness/archive/tasks/per-task-model-selection/review.response.md:216:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:226:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:229:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/archive/tasks/per-task-model-selection/review.response.md:231:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:235:+  subagent_type="doc-fetcher",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:252:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:254:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:261:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:28:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:29:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:31: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:34:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:36:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:37:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:39:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:41: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:69:-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:70:++**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:72: +- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:75:-+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:77:++- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:78:++- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:80:++- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
./z-harness/brainstorm-and-research/archive/tasks/T005/delta-v2.patch:82: +**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:44:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:72:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:85:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
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
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:151:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:200:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:206:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:207:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:224:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:258:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:259:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:293:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:360:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:388:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:401:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
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
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:467:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:516:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:522:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:523:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:540:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:574:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:575:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:609:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:43:- Skip doc-fetcher iff RESEARCH.md non-stale AND Findings has ≥1 entry citing likely-touched file.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:103:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:131:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:144:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:166:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:167:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:170:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:172:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:174:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:176:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:180:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:196:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:198:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:205:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:254:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:260:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:261:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:278:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:312:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:313:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:347:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:414:+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:442:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:455:+This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:477:+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:478:+- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:481:+If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:483:+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:485:+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:487:+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:491:+  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:507:+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:509:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:516:+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:565:+Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:571:+- `Agent(subagent_type="gemini-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:572:+- `Agent(subagent_type="codex-consultant", ...)`
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:589:+If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:623:+- gemini-consultant: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:624:+- codex-consultant: same.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:658:+Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:743:    38	8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:771:    66	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:784:    79	This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:806:   101	**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:807:   102	- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:810:   105	If neither condition is met, proceed with the full doc-fetcher + Explore flow below.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:812:   107	**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:814:   109	### 1a. Dispatch doc-fetcher (if INDEX.json exists)
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:816:   111	If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:820:   115	  subagent_type="doc-fetcher",
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:836:   131	Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:838:   133	**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:845:   140	  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:894: M agents/codex-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:895: M agents/gemini-consultant.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:909:?? agents/doc-fetcher.md
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:926:skills/z-plan/SKILL.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:932:commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and Explore optional:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:938:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:946:- **Major** — [commands/z-plan.md:105](/Users/zeke/dev/z-harness/commands/z-plan.md:105) and mirrored skill: Phase 1 treats the two shortcut conditions as a combined gate: “If neither condition is met, proceed with the full doc-fetcher + Explore flow below.” The spec requires independent skips, so fix this to explicitly handle all four cases: skip doc-fetcher only, skip Explore only, skip both, or run both.

codex
The command is documentation-as-executable-instructions, so I’m treating ambiguity as a runtime correctness issue: anything that will predictably make the orchestrator produce a malformed `RESEARCH.md` or skip required behavior is review-worthy.
exec
/bin/zsh -lc "nl -ba commands/z-brainstorm.md | sed -n '1,80p;260,310p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba brainstorm-and-research/TASKS.md | sed -n '45,75p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba brainstorm-and-research/SPEC.md | sed -n '1,260p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-research.md | sed -n '1,289p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    45	
    46	- [ ] **T004 — Create /z-research command + skill mirror**
    47	  - **Files:**
    48	    - `/Users/zeke/dev/z-harness/commands/z-research.md` (new)
    49	    - `/Users/zeke/dev/z-harness/skills/z-research/SKILL.md` (new)
    50	  - **Depends:** T001, T002
    51	  - **Acceptance:**
    52	    - Both files exist; diff shows only `name:` + blank-line differences.
    53	    - Setup mirrors `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
    54	    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
    55	    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
    56	    - Phase 2: up to 3 parallel Explore subagents on distinct facets (or 1 if user reduced). Hard cap 3; no env override in v1.
    57	    - Phase 3: write `archive/<run>/research-draft.md` with mandatory sections: Findings (with file:line citations), Constraints discovered, Open questions, No-recommendation (mandatory, non-deletable).
    58	    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
    59	    - Phase 5: revise draft based on critiques; record consultant feedback in RESEARCH.md `Cross-LLM review notes` section; note filled/unfilled gaps.
    60	    - Phase 6: write final `RESEARCH.md` with YAML frontmatter (artifact, slug, generated_at, command, input_hash, depends_on=none, explore_calls). `log-event.sh research_run_end`. Push-notify with next-step.
    61	    - Findings without file:line citations are demoted to Open questions (invariant).
    62	    - If orchestrator is tempted to recommend an approach, log `research_temptation` event and proceed without recommending.
    63	    - Cost guardrail: ≤2M tokens target; log warning if exceeded.
    64	    - Known v1 limitation documented in command file: no per-Explore wall-clock timeout (Agent() doesn't expose timeout knob).
    65	  - **DOCS:** none
    66	  - **Complexity:** high
    67	
    68	## Phase D — /z-plan integration
    69	
    70	- [ ] **T005 — Update /z-plan + skill mirror for precontext detection**
    71	  - **Files:**
    72	    - `/Users/zeke/dev/z-harness/commands/z-plan.md`
    73	    - `/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md`
    74	  - **Depends:** none (can run in parallel with T003/T004)
    75	  - **Note:** Setup step 10 and Phase 0 inject reference have been pre-applied to both files. This task verifies the existing edits are correct AND completes the remaining pieces.

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

 succeeded in 0ms:
     1	# SPEC — brainstorm-and-research
     2	
     3	## Files touched
     4	
     5	### NEW
     6	- `commands/z-brainstorm.md` + `skills/z-brainstorm/SKILL.md` (mirror)
     7	- `commands/z-research.md` + `skills/z-research/SKILL.md` (mirror)
     8	
     9	### MODIFIED
    10	- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
    11	- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
    12	- `commands/z-plan.md` + `skills/z-plan/SKILL.md` — Phase 0 seed-artifact detection, collision-handling update, source-mtime freshness gate
    13	- `README.md` — document new commands; add to flow diagram
    14	
    15	---
    16	
    17	## Artifact: BRAINSTORM.md
    18	
    19	**Path:** `z-harness/<slug>/BRAINSTORM.md`
    20	
    21	**Schema:**
    22	
    23	```markdown
    24	---
    25	artifact: brainstorm
    26	slug: <slug>
    27	generated_at: <ISO 8601 UTC>
    28	command: /z-brainstorm
    29	input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
    30	depends_on: <abs path to RESEARCH.md if chained, else "none">
    31	ideators: ["claude-sonnet", "codex", "gemini"]
    32	---
    33	
    34	# Brainstorm: <topic>
    35	
    36	## Topic
    37	<verbatim user-provided topic>
    38	
    39	## Scaffolding
    40	**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
    41	**Explore findings:** <inline, or "skipped (cap=0 by default)">
    42	**RESEARCH.md summary:** <inline if RESEARCH.md was present and ≤20 KB; extractive summary if larger; "n/a" if absent>
    43	
    44	## Framings considered
    45	
    46	### Framing 1 — Claude (Sonnet, fresh subagent context)
    47	**Framing:** <one paragraph>
    48	**Core hypothesis:** <one paragraph>
    49	**Risks:** <one paragraph>
    50	**Plan implications:** <one paragraph>
    51	**What would change my mind:** <one paragraph>
    52	
    53	### Framing 2 — Codex
    54	<same five sections>
    55	
    56	### Framing 3 — Gemini
    57	<same five sections>
    58	
    59	## Anti-bias check (mandatory)
    60	<Synthesis comparison: section-by-section, which framing wins each dimension and why. If Claude wins overall, explicit justification against the others on concrete criteria. If Claude does not win overall, list the specific Claude elements (if any) merged into the chosen framing.>
    61	
    62	## Orchestrator recommendation
    63	**Recommended framing:** <which one + one-line rationale>
    64	
    65	## User's chosen framing
    66	<set during Phase 3 user gate; one of "Framing 1" | "Framing 2" | "Framing 3" | "Restart" | free-text>
    67	
    68	## Free-text annotation
    69	<user-provided refinement notes from AskUserQuestion>
    70	```
    71	
    72	**Invariants:**
    73	- `input_hash` MUST be computed deterministically (same inputs → same hash) so re-runs are detectable.
    74	- The three ideator return blocks MUST have identical section headings (`Framing`, `Core hypothesis`, `Risks`, `Plan implications`, `What would change my mind`). An ideator that returns a different shape is treated as a malformed return — orchestrator either re-prompts or records the missing sections as `<missing>` and flags in the anti-bias check.
    75	- `User's chosen framing` is empty until the user gate completes. If user picks "Restart," BRAINSTORM.md is moved to `archive/<run>/BRAINSTORM.md.abandoned` and a fresh run starts.
    76	
    77	---
    78	
    79	## Artifact: RESEARCH.md
    80	
    81	**Path:** `z-harness/<slug>/RESEARCH.md`
    82	
    83	**Schema:**
    84	
    85	```markdown
    86	---
    87	artifact: research
    88	slug: <slug>
    89	generated_at: <ISO 8601 UTC>
    90	command: /z-research
    91	input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
    92	depends_on: none
    93	explore_calls: <integer 0-3>
    94	---
    95	
    96	# Research: <question>
    97	
    98	## Question
    99	<verbatim user-provided question>
   100	
   101	## Findings
   102	<bulleted list of factual statements with `file:line` citations and one-line synopses>
   103	
   104	## Constraints discovered
   105	<bulleted list of constraints the codebase / problem imposes; each with citation>
   106	
   107	## Open questions
   108	<things research could not answer; likely needs experiments / user input>
   109	
   110	## No-recommendation
   111	**Research does NOT pick an approach. The terrain has been mapped; the decision is downstream (`/z-brainstorm` or `/z-plan`).**
   112	
   113	## Cross-LLM review notes (from Phase 3 consult)
   114	**Gemini flagged:** <bullets>
   115	**Codex flagged:** <bullets>
   116	**Author's response:** <which gaps were filled in Phase 4, which were intentionally left, why>
   117	```
   118	
   119	**Invariants:**
   120	- `Findings` entries MUST cite specific `file:line` ranges. A finding without a citation is treated as a hypothesis, not a finding, and gets demoted to `Open questions`.
   121	- `No-recommendation` section is mandatory and non-deletable. `/z-research` MUST NOT recommend an approach; if the orchestrator feels strongly enough to recommend, it logs `research_temptation` event and proceeds without recommending (so we can measure how often this constraint chafes).
   122	- `explore_calls` is hard-capped at 3 (matching `/z-plan`'s `Z_HARNESS_MAX_EXPLORE`).
   123	
   124	---
   125	
   126	## Command: `/z-brainstorm <topic>`
   127	
   128	**File:** `commands/z-brainstorm.md`
   129	**Skill mirror:** `skills/z-brainstorm/SKILL.md`
   130	
   131	### Frontmatter
   132	```
   133	---
   134	name: z-brainstorm
   135	description: Generate N candidate problem-framings in parallel using different model vendors (Claude + Codex + Gemini), then present to user for selection. Opt-in pre-plan exploration; feeds /z-plan as Phase 0 seed.
   136	---
   137	```
   138	
   139	### CLI surface
   140	```
   141	/z-brainstorm <topic>           # default: auto-derived slug from topic
   142	/z-brainstorm <topic> --slug=X  # explicit slug (for chaining)
   143	```
   144	
   145	### Phases
   146	
   147	**Setup** (mirrors `/z-plan-light` Setup pattern):
   148	1. Derive slug (auto from topic, or use `--slug=X` if provided). If slug dir exists with `BRAINSTORM.md` already, ask via AskUserQuestion: overwrite / append to a new run / abort.
   149	2. Export `Z_HARNESS_SLUG`, pick `RUN`, mkdir, version stamp, `log-event.sh brainstorm_run_start`.
   150	3. Read `docs/llm/INDEX.json` existence flag (note for Phase 1).
   151	4. Check for `$BASE/RESEARCH.md` — if present, note `depends_on` path.
   152	
   153	**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
   154	- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
   155	- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
   156	- If `RESEARCH.md` exists, read it. If size ≤20 KB, prepare full inline payload. If >20 KB, generate an extractive summary preserving file:line citations + constraints + open questions (no abstractive generalization), and save to `archive/<run>/research-summary-for-brainstorm.md` for audit.
   157	
   158	**Phase 2 — Dispatch 3 ideators in parallel**:
   159	Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:
   160	
   161	```
   162	MODE: brainstorm
   163	Topic: <topic>
   164	Scaffolding:
   165	  doc-fetcher: <synthesis or "n/a">
   166	  Explore: <findings or "n/a">
   167	  Research: <inline content or extractive summary or "n/a">
   168	
   169	Return EXACTLY this shape (five sections, all required):
   170	  Framing: <one paragraph>
   171	  Core hypothesis: <one paragraph>
   172	  Risks: <one paragraph>
   173	  Plan implications: <one paragraph>
   174	  What would change my mind: <one paragraph>
   175	
   176	No implementation detail. No code snippets. One paragraph each.
   177	```
   178	
   179	Claude ideator uses subagent_type="general-purpose" (or a new "ideator" agent if we add one; see Open question O1 in PLAN.md) with `model="sonnet"`.
   180	
   181	**Phase 3 — Synthesis + anti-bias check**:
   182	1. Parse the three returns. If any ideator returned malformed (missing sections), record `<missing>` for that section in BRAINSTORM.md and flag in anti-bias check.
   183	2. Write BRAINSTORM.md with all three framings.
   184	3. **Anti-bias check (mandatory, mechanical):** for each of the five sections, compare the three ideators' answers and note which framing wins that dimension. If Claude wins the most dimensions, explicitly justify against the others on named criteria (matches Codex's synthesis-bias guard).
   185	4. Pick an orchestrator recommendation; record the one-line rationale.
   186	5. Push notification: "Brainstorm ready (3 framings); user gate."
   187	6. `AskUserQuestion` with previews — option per framing + "Restart with different topic framing" + "Abandon."
   188	
   189	**Phase 4 — Finalize**:
   190	- Save user's chosen framing + any free-text annotation into BRAINSTORM.md.
   191	- `log-event.sh brainstorm_run_end` with `{status, tokens_spent, ideator_durations_ms, chosen_framing}`.
   192	- Push notification with recommendation: "Run `/z-plan <slug>` (consumes this brainstorm) or run again if framing needed refinement."
   193	
   194	### Cost guardrail
   195	Target ≤200K tokens total. Log warning if exceeded.
   196	
   197	### Out of scope (v1)
   198	- Pluggable ideator list. Default is hard-coded `[claude-sonnet, codex, gemini]`; future v2 will accept `Z_HARNESS_BRAINSTORM_IDEATORS="claude-sonnet,codex,gemini,grok"` or similar.
   199	
   200	---
   201	
   202	## Command: `/z-research <question>`
   203	
   204	**File:** `commands/z-research.md`
   205	**Skill mirror:** `skills/z-research/SKILL.md`
   206	
   207	### Frontmatter
   208	```
   209	---
   210	name: z-research
   211	description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
   212	---
   213	```
   214	
   215	### CLI surface
   216	```
   217	/z-research <question>
   218	/z-research <question> --slug=X
   219	```
   220	
   221	### Phases
   222	
   223	**Setup**: same shape as `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
   224	
   225	**Phase 0 — Cost-confirmation gate**:
   226	Before any subagent dispatch, AskUserQuestion: "Research is the heaviest precontext command (target ≤2M tokens, up to 3 Explore subagents). Proceed?" Options: "Proceed" / "Reduce to 1 Explore" / "Abandon." Log user's pick.
   227	
   228	**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).
   229	
   230	**Phase 2 — Up to 3 Explore subagents on distinct facets**:
   231	- Orchestrator articulates 3 distinct facets of the question (or 1 if user reduced cap).
   232	- Parallel dispatch (single message, multiple Agent calls).
   233	- Each Explore is Haiku by default; orchestrator may upgrade individual calls to Sonnet for interpretation-heavy facets.
   234	
   235	**Phase 3 — Synthesize research-note draft**:
   236	Main thread writes the draft to `archive/<run>/research-draft.md`. MUST include:
   237	- `Findings:` with file:line citations
   238	- `Constraints discovered:`
   239	- `Open questions:`
   240	- `No-recommendation:` (mandatory)
   241	
   242	**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
   243	Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).
   244	
   245	**Phase 5 — Revise draft based on critiques**:
   246	Apply findings that hold up under "one reason it might be wrong" scrutiny. Record consultant feedback in RESEARCH.md's "Cross-LLM review notes" section. Note which gaps were filled, which were intentionally left.
   247	
   248	**Phase 6 — Finalize**:
   249	- Write final `RESEARCH.md` (with YAML frontmatter).
   250	- `log-event.sh research_run_end` with `{status, tokens_spent, explore_calls, consultant_durations_ms, findings_count}`.
   251	- Push notification with recommendation: "Run `/z-brainstorm <slug>` next (consumes this research) or run `/z-plan <slug>` directly."
   252	
   253	### Cost guardrail
   254	Target ≤2M tokens total. Log warning if exceeded.
   255	
   256	---
   257	
   258	## Consultant agent extensions
   259	
   260	### `agents/codex-consultant.md` and `agents/gemini-consultant.md`

 succeeded in 0ms:
     1	---
     2	description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
     3	argument-hint: <question or technical area to research>
     4	---
     5	
     6	You are running the **z-harness `/z-research`** pipeline.
     7	
     8	Question (from `$ARGUMENTS`):
     9	
    10	$ARGUMENTS
    11	
    12	**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.
    13	
    14	Strict, multi-phase. Do not skip phases. `/z-research` produces a research note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.
    15	
    16	**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.
    17	
    18	## Setup
    19	
    20	1. **Derive a research slug** from the question: short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
    21	   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
    22	   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
    23	   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
    24	2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
    25	3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
    26	4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
    27	5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
    28	   ```bash
    29	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    30	   START_PAYLOAD="$(python3 -c '
    31	   import json, sys
    32	   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
    33	   print(json.dumps(v))
    34	   ' "$VERSION_BLOB" "<arguments>")"
    35	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
    36	   ```
    37	6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
    38	7. **Artifact collision check.** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists:
    39	   - Archive it: `mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`
    40	   - Notify the user: "Existing RESEARCH.md archived. Starting fresh research."
    41	8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
    42	
    43	**All paths in subsequent phases live under `z-harness/<slug>/`:**
    44	- `z-harness/<slug>/RESEARCH.md`
    45	- `z-harness/<slug>/archive/<run-id>/...`
    46	
    47	## Phase telemetry (mandatory)
    48	
    49	At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
    50	
    51	```bash
    52	WALL_MS=$(( $(date +%s%3N) - T0 ))
    53	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
    54	  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
    55	     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
    56	```
    57	
    58	If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:
    59	
    60	```bash
    61	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
    62	# ... AskUserQuestion ...
    63	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
    64	```
    65	
    66	---
    67	
    68	## Phase 0 — Cost-confirmation gate
    69	
    70	Research can be expensive. The default fan-out is up to 3 parallel `Explore` subagents (Haiku) plus a bundled cross-LLM critique pass. Target spend: **≤2M tokens / 5-10 min wall time.** If you exceed 2M tokens at any point, log a `cost_warning` event and surface it to the user.
    71	
    72	Present the cost up front via `AskUserQuestion` with three options:
    73	
    74	- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores.
    75	- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
    76	- **Abandon** — exit cleanly, write nothing.
    77	
    78	Log the user's pick:
    79	
    80	```bash
    81	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
    82	  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
    83	```
    84	
    85	If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.
    86	
    87	Checkpoint: `phase0-cost-gate.md`.
    88	
    89	## Phase 1 — Scaffolding
    90	
    91	**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
    92	
    93	```
    94	Agent(
    95	  subagent_type="doc-fetcher",
    96	  description="Doc context for <slug>",
    97	  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
    98	)
    99	```
   100	
   101	It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 2.
   102	
   103	If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
   104	```bash
   105	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
   106	  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
   107	```
   108	
   109	**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.
   110	
   111	Checkpoint: `phase1-scaffolding.md`.
   112	
   113	## Phase 2 — Parallel Explores
   114	
   115	Dispatch up to `EXPLORE_BUDGET` parallel `Explore` subagents (Haiku) on **distinct facets** of the question. Each Explore must answer a targeted sub-question; do not dispatch overlapping queries.
   116	
   117	**Hard cap: 3.** No env override in v1. If `EXPLORE_BUDGET=1` from Phase 0, dispatch a single Explore covering the most important facet.
   118	
   119	Send all calls in **one message** so they run in parallel:
   120	
   121	```
   122	Agent(
   123	  subagent_type="Explore",
   124	  model: "haiku",
   125	  description="Facet A: <short label>",
   126	  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
   127	)
   128	Agent(
   129	  subagent_type="Explore",
   130	  model: "haiku",
   131	  description="Facet B: <short label>",
   132	  prompt="<TARGETED sub-question>\n\n..."
   133	)
   134	Agent(
   135	  subagent_type="Explore",
   136	  model: "haiku",
   137	  description="Facet C: <short label>",
   138	  prompt="<TARGETED sub-question>\n\n..."
   139	)
   140	```
   141	
   142	**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.
   143	
   144	Record `explore_calls = <N>` (0 if Phase 0 abandoned but you somehow got here; 1 if reduced; up to 3 otherwise) — it lands in the final frontmatter.
   145	
   146	Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).
   147	
   148	## Phase 3 — Draft research note
   149	
   150	Write `z-harness/$Z_HARNESS_SLUG/archive/$RUN/research-draft.md` with **these mandatory sections, in this exact order**:
   151	
   152	```markdown
   153	## Findings
   154	- <claim> (path/to/file.rs:42)
   155	- <claim> (path/to/other.py:117-130)
   156	
   157	## Constraints discovered
   158	- <constraint with citation>
   159	
   160	## Open questions
   161	- <question the Explores could not resolve>
   162	
   163	## No-recommendation
   164	This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
   165	```
   166	
   167	**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.
   168	
   169	**Demotion rule.** Findings without a `file:line` citation are demoted to **Open questions** — do not silently drop them, and do not add a fake citation.
   170	
   171	**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:
   172	
   173	```bash
   174	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
   175	  '{"location":"<section>","removed_text":"<short excerpt>"}'
   176	```
   177	
   178	Checkpoint: `research-draft.md` (this file).
   179	
   180	## Phase 4 — Bundled cross-LLM critique
   181	
   182	Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.
   183	
   184	```
   185	Agent(
   186	  subagent_type="gemini-consultant",
   187	  description="Research review (Gemini) for <slug>",
   188	  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
   189	)
   190	Agent(
   191	  subagent_type="codex-consultant",
   192	  description="Research review (Codex) for <slug>",
   193	  prompt="MODE: research-review\n\nOriginal question: <question>\n\nScaffolding (doc-fetcher synthesis): <paste>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
   194	)
   195	```
   196	
   197	Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).
   198	
   199	Checkpoint: `phase4-critiques.md` (both critiques side-by-side).
   200	
   201	## Phase 5 — Revise
   202	
   203	For each consultant gap / error / missing-constraint:
   204	
   205	- **Fill it** if the orchestrator can resolve it from existing Explore returns or via a quick targeted Read.
   206	- **Note it as unfilled** in the `## Cross-LLM review notes` section if it would require another Explore dispatch (out of scope at this phase).
   207	
   208	Update the draft accordingly. If a consultant tried to recommend an approach despite the MODE prohibition, **strip the recommendation** and log `research_temptation` for the consultant turn.
   209	
   210	Add a `## Cross-LLM review notes` section to the draft summarizing:
   211	- Gemini's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
   212	- Codex's flagged gaps / errors / missing constraints — and which were filled vs. left as Open questions.
   213	
   214	Re-run the demotion rule from Phase 3: any new findings introduced during revision must carry a `file:line` citation or be demoted.
   215	
   216	Checkpoint: `research-draft.revised.md`.
   217	
   218	## Phase 6 — Finalize
   219	
   220	Compute `input_hash` per the SPEC algorithm:
   221	
   222	```
   223	input_hash = sha256(canonicalize(
   224	    question + "\n---\n" +
   225	    doc_fetcher_synthesis_or_empty + "\n---\n" +
   226	    explore_synthesis_or_empty + "\n---\n" +
   227	    research_md_or_empty
   228	)).hexdigest()[:16]
   229	```
   230	
   231	`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.
   232	
   233	Write final `z-harness/$Z_HARNESS_SLUG/RESEARCH.md`:
   234	
   235	```markdown
   236	---
   237	artifact: research
   238	slug: <slug>
   239	generated_at: <ISO-8601 UTC>
   240	command: /z-research
   241	input_hash: <16 hex chars>
   242	depends_on: []
   243	explore_calls: <0..3>
   244	status: complete
   245	---
   246	
   247	# Research: <question>
   248	
   249	## Findings
   250	<bulleted list with file:line citations>
   251	
   252	## Constraints discovered
   253	<bulleted list>
   254	
   255	## Open questions
   256	<bulleted list>
   257	
   258	## No-recommendation
   259	This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
   260	
   261	## Cross-LLM review notes
   262	<consultant feedback summary; filled vs unfilled gaps>
   263	```
   264	
   265	Log run end:
   266	
   267	```bash
   268	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
   269	  "$(printf '{"slug":"%s","explore_calls":%d,"status":"complete"}' "$Z_HARNESS_SLUG" "<N>")"
   270	```
   271	
   272	Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
   273	
   274	```
   275	Research complete. RESEARCH.md written to z-harness/<slug>/RESEARCH.md.
   276	
   277	Recommended next step:
   278	  /z-brainstorm <topic>  — ideate approaches grounded in this research, OR
   279	  /z-plan <task>         — go straight to planning if the approach is already clear
   280	```
   281	
   282	---
   283	
   284	## Operating principles
   285	
   286	- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant. Every temptation to recommend gets logged and removed.
   287	- **Citations are non-negotiable.** No `file:line` → not a finding.
   288	- **Cost discipline.** Phase 0 is the user's gate; respect their pick. If you exceed 2M tokens, warn.
   289	- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.

codex
- **Major** — [commands/z-research.md:38](/Users/zeke/dev/z-harness/commands/z-research.md:38) and mirrored skill: existing `RESEARCH.md` is archived during Setup before the Phase 0 cost gate, so choosing “Abandon” still mutates the workspace and removes the current research note. Move collision handling until after `proceed` / `reduce`, and for an existing `RESEARCH.md` ask whether to archive/start fresh, continue, or abort.

- **Major** — [commands/z-research.md:20](/Users/zeke/dev/z-harness/commands/z-research.md:20) and mirrored skill: Setup does not support `/z-research <question> --slug=X`, even though the spec’s CLI surface includes explicit slug selection and “mirrors `/z-brainstorm` Setup” implies the same slug override behavior. Add `--slug=<value>` parsing before auto-derivation and exclude that flag from the research question used for prompts and hashing.

- **Major** — [commands/z-research.md:240](/Users/zeke/dev/z-harness/commands/z-research.md:240) and mirrored skill: final YAML writes `command: /z-research`, but the required frontmatter is `command: /z-research <args>`, which breaks reproducibility and loses the original invocation. Store the exact normalized invocation, including the user’s research question and any supported flags.

- **Major** — [commands/z-research.md:144](/Users/zeke/dev/z-harness/commands/z-research.md:144) and mirrored skill: `explore_calls` is defined as the planned budget, not the number actually dispatched or successfully returned, so failed/skipped Explore calls can produce false frontmatter. Track actual dispatched calls and failures explicitly, then write `explore_calls` from the actual count and mark unresolved failures in Open questions or status handling.

- **Major** — [commands/z-research.md:180](/Users/zeke/dev/z-harness/commands/z-research.md:180) and mirrored skill: there is no consultant failure policy, so a failed or malformed Gemini/Codex critique can still lead to a “complete” `RESEARCH.md` with missing `Cross-LLM review notes`. Add handling for each consultant returning error/empty/malformed output: retry once or record the failure as unfilled review notes, and only mark `status: complete` when the required critique phase was actually accounted for.
2026-05-22T16:52:05.903531Z ERROR codex_core::session: failed to record rollout items: thread 019e5099-2b11-7433-aff3-daf9ce497c64 not found
tokens used
76,479
- **Major** — [commands/z-research.md:38](/Users/zeke/dev/z-harness/commands/z-research.md:38) and mirrored skill: existing `RESEARCH.md` is archived during Setup before the Phase 0 cost gate, so choosing “Abandon” still mutates the workspace and removes the current research note. Move collision handling until after `proceed` / `reduce`, and for an existing `RESEARCH.md` ask whether to archive/start fresh, continue, or abort.

- **Major** — [commands/z-research.md:20](/Users/zeke/dev/z-harness/commands/z-research.md:20) and mirrored skill: Setup does not support `/z-research <question> --slug=X`, even though the spec’s CLI surface includes explicit slug selection and “mirrors `/z-brainstorm` Setup” implies the same slug override behavior. Add `--slug=<value>` parsing before auto-derivation and exclude that flag from the research question used for prompts and hashing.

- **Major** — [commands/z-research.md:240](/Users/zeke/dev/z-harness/commands/z-research.md:240) and mirrored skill: final YAML writes `command: /z-research`, but the required frontmatter is `command: /z-research <args>`, which breaks reproducibility and loses the original invocation. Store the exact normalized invocation, including the user’s research question and any supported flags.

- **Major** — [commands/z-research.md:144](/Users/zeke/dev/z-harness/commands/z-research.md:144) and mirrored skill: `explore_calls` is defined as the planned budget, not the number actually dispatched or successfully returned, so failed/skipped Explore calls can produce false frontmatter. Track actual dispatched calls and failures explicitly, then write `explore_calls` from the actual count and mark unresolved failures in Open questions or status handling.

- **Major** — [commands/z-research.md:180](/Users/zeke/dev/z-harness/commands/z-research.md:180) and mirrored skill: there is no consultant failure policy, so a failed or malformed Gemini/Codex critique can still lead to a “complete” `RESEARCH.md` with missing `Cross-LLM review notes`. Add handling for each consultant returning error/empty/malformed output: retry once or record the failure as unfilled review notes, and only mark `status: complete` when the required critique phase was actually accounted for.
