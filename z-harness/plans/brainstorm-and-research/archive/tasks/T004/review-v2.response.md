2026-05-22T16:58:29.964657Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T16:58:29.965367Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T16:58:29.965373Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e509f-cad2-7d70-8b20-55bd60184307
--------
user
You are reviewing the v2 follow-up of task T004: Create /z-research command + skill mirror.

This is ROUND 2 — only evaluate whether the v1 findings below were properly addressed in the delta. Do NOT re-flag issues outside this delta. The command and SKILL files are intentionally byte-identical mirrors.

Prior findings (v1, all majors):
1. RESEARCH.md archived in Setup before Phase 0 cost gate; abandon still mutated workspace.
2. No --slug=X flag support (mirrors /z-brainstorm should have it).
3. command: frontmatter wrote bare "/z-research" instead of "/z-research <args>".
4. explore_calls computed from EXPLORE_BUDGET (planned) not actual successful returns.
5. No consultant failure policy — failed critique could still produce status: complete with empty Cross-LLM review notes.

Delta patch (v1 -> v2):

```
--- z-harness/brainstorm-and-research/archive/tasks/T004/diff-v1.patch	2026-05-22 09:53:54
+++ z-harness/brainstorm-and-research/archive/tasks/T004/diff.patch	2026-05-22 09:57:06
@@ -1,9 +1,9 @@
 diff --git a/commands/z-research.md b/commands/z-research.md
 new file mode 100644
-index 0000000..a08955a
+index 0000000..f60f5ea
 --- /dev/null
 +++ b/commands/z-research.md
-@@ -0,0 +1,289 @@
+@@ -0,0 +1,350 @@
 +---
 +description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
 +argument-hint: <question or technical area to research>
@@ -23,10 +23,11 @@
 +
 +## Setup
 +
-+1. **Derive a research slug** from the question: short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
-+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
-+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
-+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
++1. **Parse `--slug=<value>` flag** from `$ARGUMENTS` first. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the research question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned research question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.
++
++   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
++
++   If `--slug=` was explicitly provided, skip auto-derivation but still defer collision handling to Phase 0.5.
 +2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
 +3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
 +4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
@@ -41,18 +42,17 @@
 +   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
 +   ```
 +6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
-+7. **Artifact collision check.** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists:
-+   - Archive it: `mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`
-+   - Notify the user: "Existing RESEARCH.md archived. Starting fresh research."
-+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
++7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
 +
++**Setup does NOT mutate `z-harness/<slug>/RESEARCH.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.
++
 +**All paths in subsequent phases live under `z-harness/<slug>/`:**
 +- `z-harness/<slug>/RESEARCH.md`
 +- `z-harness/<slug>/archive/<run-id>/...`
 +
 +## Phase telemetry (mandatory)
 +
-+At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
++At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
 +
 +```bash
 +WALL_MS=$(( $(date +%s%3N) - T0 ))
@@ -92,6 +92,28 @@
 +
 +Checkpoint: `phase0-cost-gate.md`.
 +
++## Phase 0.5 — Slug + artifact collision handling
++
++This phase runs **only if** the user picked `proceed` or `reduce` in Phase 0. The `abandon` path must never reach this phase, so the existing workspace stays untouched.
++
++1. **Slug-dir collision (deferred from Setup step 1).** If the chosen slug (auto-derived or `--slug=`) matches an existing `z-harness/<slug>/` dir:
++   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
++   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
++   If the auto-derived slug is non-obvious (and `--slug=` was not provided), confirm with the user via `AskUserQuestion`.
++
++2. **Existing-RESEARCH.md handling (deferred from old Setup step 7).** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, prompt the user via `AskUserQuestion` with three options:
++   - **archive-and-start-fresh** — archive the existing note (`mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`) and proceed with a clean draft.
++   - **continue (re-use existing)** — leave the existing RESEARCH.md in place and treat this run as a refinement; the existing note's findings become inputs to Phase 3.
++   - **abort** — exit cleanly. **Do NOT touch the existing RESEARCH.md or any sibling file.** Log a `phase0_5_abort` event and return.
++
++   Log the user's pick:
++   ```bash
++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
++     "$(printf '{"choice":"%s"}' "<archive-and-start-fresh|continue|abort>")"
++   ```
++
++Checkpoint: `phase0_5-collision.md`.
++
 +## Phase 1 — Scaffolding
 +
 +**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
@@ -147,8 +169,21 @@
 +
 +**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.
 +
-+Record `explore_calls = <N>` (0 if Phase 0 abandoned but you somehow got here; 1 if reduced; up to 3 otherwise) — it lands in the final frontmatter.
++**Track three counts separately:**
 +
++- `EXPLORE_BUDGET` — the planned cap from Phase 0 (1 or 3).
++- `EXPLORES_DISPATCHED` — the number of `Explore` `Agent()` calls you actually sent in the parallel message (≤ `EXPLORE_BUDGET`).
++- `EXPLORES_SUCCEEDED` — the number of those calls that returned a usable result (no error, non-empty findings). Failed, malformed, or empty returns do NOT count.
++
++For every Explore that fails or returns malformed output, log it and surface the failure as an **Open question** in Phase 3:
++
++```bash
++bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
++  "$(printf '{"facet":"%s","reason":"%s"}' "<facet-label>" "<short reason>")"
++```
++
++The final frontmatter uses **`EXPLORES_SUCCEEDED`** for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` frontmatter field. Do not fabricate `explore_calls` from `EXPLORE_BUDGET`.
++
 +Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).
 +
 +## Phase 3 — Draft research note
@@ -202,8 +237,27 @@
 +
 +Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).
 +
-+Checkpoint: `phase4-critiques.md` (both critiques side-by-side).
++**Per-consultant failure policy.** A consultant return is "failed" if it errors, returns empty, or returns a payload that does not contain at least one of `Gaps` / `Errors` / `Missing constraints` sections (malformed). For each consultant independently:
 +
++1. **Retry once.** Re-dispatch the same consultant with the identical prompt. Log a `consultant_retry` event with `{"consultant":"<gemini|codex>","reason":"<error|empty|malformed>"}`.
++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
++
++**Aggregate decision** (after both consultants resolve):
++
++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
++- **Both consultants failed (after retry)** → DO NOT mark `status: complete`. Prompt the user via `AskUserQuestion` with three options:
++  - **proceed-with-no-critique** — finalize with `status: complete_no_critique` and an explicit `## Cross-LLM review notes` entry stating both consultants failed.
++  - **retry-both** — dispatch Phase 4 from scratch once more.
++  - **abandon** — write nothing further; log `research_run_end` with `status: abandoned_critique_failure` and exit.
++
++Log the aggregate decision:
++```bash
++bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" critique_failure_decision \
++  "$(printf '{"choice":"%s"}' "<proceed-with-no-critique|retry-both|abandon>")"
++```
++
++Checkpoint: `phase4-critiques.md` (both critiques side-by-side, with `<consultant>:failed` markers where applicable).
++
 +## Phase 5 — Revise
 +
 +For each consultant gap / error / missing-constraint:
@@ -243,11 +297,13 @@
 +artifact: research
 +slug: <slug>
 +generated_at: <ISO-8601 UTC>
-+command: /z-research
++command: /z-research "<verbatim cleaned research question>" [--slug=<value>]
 +input_hash: <16 hex chars>
 +depends_on: []
-+explore_calls: <0..3>
-+status: complete
++explore_calls: <EXPLORES_SUCCEEDED, 0..3>
++# explore_failures only emitted if (EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED) > 0:
++explore_failures: <N>
++status: <complete | complete_no_critique>
 +---
 +
 +# Research: <question>
@@ -268,11 +324,16 @@
 +<consultant feedback summary; filled vs unfilled gaps>
 +```
 +
++**`command:` frontmatter rule.** Store the exact normalized invocation, including the verbatim cleaned research question (double-quoted) and any supported flags such as `--slug=<value>`. Example: `command: /z-research "What's the right schema for X?" --slug=foo-bar`. The bare `command: /z-research` form is **forbidden** — reproducibility requires the question be recoverable from the frontmatter alone.
++
++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
++
 +Log run end:
 +
 +```bash
 +bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
-+  "$(printf '{"slug":"%s","explore_calls":%d,"status":"complete"}' "$Z_HARNESS_SLUG" "<N>")"
++  "$(printf '{"slug":"%s","explore_calls":%d,"explore_failures":%d,"status":"%s"}' \
++     "$Z_HARNESS_SLUG" "$EXPLORES_SUCCEEDED" "$((EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED))" "<complete|complete_no_critique>")"
 +```
 +
 +Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
@@ -295,10 +356,10 @@
 +- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.
 diff --git a/skills/z-research/SKILL.md b/skills/z-research/SKILL.md
 new file mode 100644
-index 0000000..a08955a
+index 0000000..f60f5ea
 --- /dev/null
 +++ b/skills/z-research/SKILL.md
-@@ -0,0 +1,289 @@
+@@ -0,0 +1,350 @@
 +---
 +description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
 +argument-hint: <question or technical area to research>
@@ -318,10 +379,11 @@
 +
 +## Setup
 +
-+1. **Derive a research slug** from the question: short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
-+   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
-+   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
-+   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
++1. **Parse `--slug=<value>` flag** from `$ARGUMENTS` first. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the research question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned research question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.
++
++   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
++
++   If `--slug=` was explicitly provided, skip auto-derivation but still defer collision handling to Phase 0.5.
 +2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
 +3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
 +4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
@@ -336,18 +398,17 @@
 +   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
 +   ```
 +6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
-+7. **Artifact collision check.** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists:
-+   - Archive it: `mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`
-+   - Notify the user: "Existing RESEARCH.md archived. Starting fresh research."
-+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
++7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.
 +
++**Setup does NOT mutate `z-harness/<slug>/RESEARCH.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.
++
 +**All paths in subsequent phases live under `z-harness/<slug>/`:**
 +- `z-harness/<slug>/RESEARCH.md`
 +- `z-harness/<slug>/archive/<run-id>/...`
 +
 +## Phase telemetry (mandatory)
 +
-+At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
++At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
 +
 +```bash
 +WALL_MS=$(( $(date +%s%3N) - T0 ))
@@ -387,6 +448,28 @@
 +
 +Checkpoint: `phase0-cost-gate.md`.
 +
++## Phase 0.5 — Slug + artifact collision handling
++
++This phase runs **only if** the user picked `proceed` or `reduce` in Phase 0. The `abandon` path must never reach this phase, so the existing workspace stays untouched.
++
++1. **Slug-dir collision (deferred from Setup step 1).** If the chosen slug (auto-derived or `--slug=`) matches an existing `z-harness/<slug>/` dir:
++   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
++   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
++   If the auto-derived slug is non-obvious (and `--slug=` was not provided), confirm with the user via `AskUserQuestion`.
++
++2. **Existing-RESEARCH.md handling (deferred from old Setup step 7).** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, prompt the user via `AskUserQuestion` with three options:
++   - **archive-and-start-fresh** — archive the existing note (`mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`) and proceed with a clean draft.
++   - **continue (re-use existing)** — leave the existing RESEARCH.md in place and treat this run as a refinement; the existing note's findings become inputs to Phase 3.
++   - **abort** — exit cleanly. **Do NOT touch the existing RESEARCH.md or any sibling file.** Log a `phase0_5_abort` event and return.
++
++   Log the user's pick:
++   ```bash
++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
++     "$(printf '{"choice":"%s"}' "<archive-and-start-fresh|continue|abort>")"
++   ```
++
++Checkpoint: `phase0_5-collision.md`.
++
 +## Phase 1 — Scaffolding
 +
 +**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:
@@ -442,8 +525,21 @@
 +
 +**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.
 +
-+Record `explore_calls = <N>` (0 if Phase 0 abandoned but you somehow got here; 1 if reduced; up to 3 otherwise) — it lands in the final frontmatter.
++**Track three counts separately:**
 +
++- `EXPLORE_BUDGET` — the planned cap from Phase 0 (1 or 3).
++- `EXPLORES_DISPATCHED` — the number of `Explore` `Agent()` calls you actually sent in the parallel message (≤ `EXPLORE_BUDGET`).
++- `EXPLORES_SUCCEEDED` — the number of those calls that returned a usable result (no error, non-empty findings). Failed, malformed, or empty returns do NOT count.
++
++For every Explore that fails or returns malformed output, log it and surface the failure as an **Open question** in Phase 3:
++
++```bash
++bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
++  "$(printf '{"facet":"%s","reason":"%s"}' "<facet-label>" "<short reason>")"
++```
++
++The final frontmatter uses **`EXPLORES_SUCCEEDED`** for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` frontmatter field. Do not fabricate `explore_calls` from `EXPLORE_BUDGET`.
++
 +Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).
 +
 +## Phase 3 — Draft research note
@@ -497,8 +593,27 @@
 +
 +Save the raw transcripts under `archive/$RUN/transcripts/` (the consultant subagents do this themselves).
 +
-+Checkpoint: `phase4-critiques.md` (both critiques side-by-side).
++**Per-consultant failure policy.** A consultant return is "failed" if it errors, returns empty, or returns a payload that does not contain at least one of `Gaps` / `Errors` / `Missing constraints` sections (malformed). For each consultant independently:
 +
++1. **Retry once.** Re-dispatch the same consultant with the identical prompt. Log a `consultant_retry` event with `{"consultant":"<gemini|codex>","reason":"<error|empty|malformed>"}`.
++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
++
++**Aggregate decision** (after both consultants resolve):
++
++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
++- **Both consultants failed (after retry)** → DO NOT mark `status: complete`. Prompt the user via `AskUserQuestion` with three options:
++  - **proceed-with-no-critique** — finalize with `status: complete_no_critique` and an explicit `## Cross-LLM review notes` entry stating both consultants failed.
++  - **retry-both** — dispatch Phase 4 from scratch once more.
++  - **abandon** — write nothing further; log `research_run_end` with `status: abandoned_critique_failure` and exit.
++
++Log the aggregate decision:
++```bash
++bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" critique_failure_decision \
++  "$(printf '{"choice":"%s"}' "<proceed-with-no-critique|retry-both|abandon>")"
++```
++
++Checkpoint: `phase4-critiques.md` (both critiques side-by-side, with `<consultant>:failed` markers where applicable).
++
 +## Phase 5 — Revise
 +
 +For each consultant gap / error / missing-constraint:
@@ -538,11 +653,13 @@
 +artifact: research
 +slug: <slug>
 +generated_at: <ISO-8601 UTC>
-+command: /z-research
++command: /z-research "<verbatim cleaned research question>" [--slug=<value>]
 +input_hash: <16 hex chars>
 +depends_on: []
-+explore_calls: <0..3>
-+status: complete
++explore_calls: <EXPLORES_SUCCEEDED, 0..3>
++# explore_failures only emitted if (EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED) > 0:
++explore_failures: <N>
++status: <complete | complete_no_critique>
 +---
 +
 +# Research: <question>
@@ -563,11 +680,16 @@
 +<consultant feedback summary; filled vs unfilled gaps>
 +```
 +
++**`command:` frontmatter rule.** Store the exact normalized invocation, including the verbatim cleaned research question (double-quoted) and any supported flags such as `--slug=<value>`. Example: `command: /z-research "What's the right schema for X?" --slug=foo-bar`. The bare `command: /z-research` form is **forbidden** — reproducibility requires the question be recoverable from the frontmatter alone.
++
++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
++
 +Log run end:
 +
 +```bash
 +bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
-+  "$(printf '{"slug":"%s","explore_calls":%d,"status":"complete"}' "$Z_HARNESS_SLUG" "<N>")"
++  "$(printf '{"slug":"%s","explore_calls":%d,"explore_failures":%d,"status":"%s"}' \
++     "$Z_HARNESS_SLUG" "$EXPLORES_SUCCEEDED" "$((EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED))" "<complete|complete_no_critique>")"
 +```
 +
 +Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:
```

For each of the 5 prior findings, judge:
- FIXED (cleanly addresses the issue), PARTIAL (addresses it but has a residual gap), or NOT FIXED.
- If PARTIAL or NOT FIXED, give a one-sentence reason and the fix.

OUTPUT BUDGET — respect strictly:
- Total response under 4000 characters.
- One line per finding (FIXED / PARTIAL / NOT FIXED + brief reason if not FIXED).
- Only call out NEW blockers/majors if they were introduced by the delta itself.
- If everything is FIXED and no new issues, respond with: "All 5 prior findings fixed. No new blockers or majors."
codex
1. PARTIAL - `RESEARCH.md` archiving is deferred, but Setup still creates `z-harness/<slug>/archive/$RUN/transcripts` before the Phase 0 cost gate; move all `z-harness/<slug>` mkdir/log writes until after proceed/reduce.
2. FIXED
3. FIXED
4. FIXED
5. FIXED
2026-05-22T16:58:47.408421Z ERROR codex_core::session: failed to record rollout items: thread 019e509f-cad2-7d70-8b20-55bd60184307 not found
tokens used
665
1. PARTIAL - `RESEARCH.md` archiving is deferred, but Setup still creates `z-harness/<slug>/archive/$RUN/transcripts` before the Phase 0 cost gate; move all `z-harness/<slug>` mkdir/log writes until after proceed/reduce.
2. FIXED
3. FIXED
4. FIXED
5. FIXED
