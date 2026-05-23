2026-05-22T17:02:33.432392Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T17:02:33.432418Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T17:02:33.432420Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e50a3-81da-7ed2-a24d-9718c13901e8
--------
user
You are reviewing code that Claude just wrote for task T006: Update README with new commands /z-brainstorm and /z-research, env vars, telemetry events, v1 limitations, /z-plan precontext detection note.

Acceptance criteria:
- /z-brainstorm and /z-research documented with purpose, cost targets (≤200K / ≤2M), when to use each
- Example chain /z-research → /z-brainstorm → /z-plan documented
- Z_HARNESS_BRAINSTORM_EXPLORE=1 documented
- New event types listed: brainstorm_run_start/end, research_run_start/end, ideator_failed, total_ideator_failure, research_temptation, precontext_source_deleted, precontext_freshness_check_failed, cost_gate_decision, explore_failure
- Known v1 limitations: no Agent() per-call timeout, no doc-fetcher caching across precontext + /z-plan
- /z-plan Setup step 10 precontext detection mentioned

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/README.md b/README.md
index 7b3fc4d..e2ccd9c 100644
--- a/README.md
+++ b/README.md
@@ -6,6 +6,19 @@ A Claude Code plugin that wraps planning and implementation in a rigorous, cross
 
 Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.
 
+### Pre-planning (optional; feed into `/z-plan`)
+
+- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators (Claude Sonnet + Codex + Gemini). Produces `BRAINSTORM.md` in `z-harness/<slug>/`. Cost target: ≤200K tokens. Use this when the framing or approach for a problem is still open and you want divergent perspectives before locking in a plan.
+- **`/z-research <question>`** — Heavier terrain mapping via parallel Explores + cross-LLM critique. Produces `RESEARCH.md` in `z-harness/<slug>/`. Cost target: ≤2M tokens. Use this when you need concrete file:line evidence about an existing codebase or design space before deciding what to build.
+
+**Typical chains:**
+
+- Murky problem: `/z-research → /z-brainstorm → /z-plan` — research terrain first, generate framed approaches, then plan.
+- Lighter case: `/z-brainstorm → /z-plan` — skip research when the codebase is already well understood.
+- Standard: `/z-plan` alone — when the problem and approach are already clear.
+
+`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.
+
 ### Planning
 
 - **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
@@ -45,6 +58,7 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 | `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
 | `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
 | `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries, paper qtctl restarts |
+| `ideator` | sonnet | Claude-side ideator in `/z-brainstorm` Phase 2 (one of three parallel ideators) |
 
 ## Operating principles
 
@@ -104,9 +118,35 @@ When a downstream repo defines its own skills that interoperate with z-harness,
 - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
 - `Z_HARNESS_MAX_EXPLORE` — default `3`. Cap on `Explore` subagent dispatches per `/z-plan` run.
 - `Z_HARNESS_DOC_STALENESS_THRESHOLD` — default `20` (percent). Above this, `/z-plan` halts and recommends `/z-maintain-docs` first.
-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
 - `Z_HARNESS_LOCAL_CARGO_CLEAN` — set to `1` at the start of `/z-implement-all` to trigger a one-time local `cargo clean`.
 - `Z_HARNESS_SLUG` — set by commands; namespaces all output paths under `z-harness/<slug>/`.
+- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
+
+## Telemetry event types
+
+All events are appended to `z-harness/metrics.jsonl` via `scripts/log-event.sh`. Standard per-event fields: `prompt_chars`, `response_chars`, `wall_ms`.
+
+Event kinds introduced by `/z-brainstorm` and `/z-research`:
+
+| Event | Emitted by |
+|---|---|
+| `brainstorm_run_start` | `/z-brainstorm` setup |
+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
+| `research_run_start` | `/z-research` setup |
+| `research_run_end` | `/z-research` Phase 6 |
+| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
+| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
+| `research_temptation` | `/z-research` when orchestrator drafts a recommendation it must not make |
+| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
+| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
+| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate |
+| `explore_failure` | any command that dispatches an Explore subagent that does not return |
+
+## Known v1 limitations
+
+- **No per-subagent wall-clock timeout.** `Agent()` does not expose a per-call timeout; subagents that hang block the entire run. User-facing escape: ctrl-c to abort.
+- **No doc-fetcher caching across precontext and plan runs.** If you run `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched twice (once per command). Marked as a v2 candidate; the cost is low enough today.
 
 ## Layout
 
@@ -116,6 +156,8 @@ z-harness/
 │   ├── plugin.json
 │   └── marketplace.json
 ├── commands/
+│   ├── z-brainstorm.md
+│   ├── z-research.md
 │   ├── z-plan.md
 │   ├── z-plan-light.md
 │   ├── z-test.md

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
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note).

codex
I’ll verify the README claims against the command files so I can distinguish missing docs from inaccurate docs, especially the new `/z-plan` precontext behavior and telemetry names.
exec
/bin/zsh -lc 'rg -n "precontext|Setup step 10|BRAINSTORM|RESEARCH|freshness|cost_gate_decision|brainstorm_run|research_run|ideator_failed|total_ideator_failure|research_temptation|precontext_source_deleted|precontext_freshness_check_failed|explore_failure" commands README.md scripts .codex-plugin 2>/dev/null' in /Users/zeke/dev/z-harness
 exited 2 in 0ms:
README.md:11:- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators (Claude Sonnet + Codex + Gemini). Produces `BRAINSTORM.md` in `z-harness/<slug>/`. Cost target: ≤200K tokens. Use this when the framing or approach for a problem is still open and you want divergent perspectives before locking in a plan.
README.md:12:- **`/z-research <question>`** — Heavier terrain mapping via parallel Explores + cross-LLM critique. Produces `RESEARCH.md` in `z-harness/<slug>/`. Cost target: ≤2M tokens. Use this when you need concrete file:line evidence about an existing codebase or design space before deciding what to build.
README.md:20:`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.
README.md:24:- **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
README.md:124:- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
README.md:134:| `brainstorm_run_start` | `/z-brainstorm` setup |
README.md:135:| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
README.md:136:| `research_run_start` | `/z-research` setup |
README.md:137:| `research_run_end` | `/z-research` Phase 6 |
README.md:138:| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
README.md:139:| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
README.md:140:| `research_temptation` | `/z-research` when orchestrator drafts a recommendation it must not make |
README.md:141:| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
README.md:142:| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
README.md:143:| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate |
README.md:144:| `explore_failure` | any command that dispatches an Explore subagent that does not return |
README.md:149:- **No doc-fetcher caching across precontext and plan runs.** If you run `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched twice (once per command). Marked as a v2 candidate; the cost is low enough today.
commands/z-maintain-docs.md:152:- Could be wired into CI as `claude /z-maintain-docs --apply` if the user wants automated freshness.
commands/z-implement-all.md:346:   Both are safe to run in sequence; they cover different concerns (correctness vs documentation freshness).
commands/z-brainstorm.md:2:description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
commands/z-brainstorm.md:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
commands/z-brainstorm.md:23:   - **overwrite** — archive existing `BRAINSTORM.md` to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
commands/z-brainstorm.md:33:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
commands/z-brainstorm.md:39:- `z-harness/<slug>/BRAINSTORM.md`
commands/z-brainstorm.md:83:If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
commands/z-brainstorm.md:94:If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
commands/z-brainstorm.md:96:### 1c. RESEARCH.md ingestion
commands/z-brainstorm.md:98:If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, read it.
commands/z-brainstorm.md:103:Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
commands/z-brainstorm.md:126:Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.
commands/z-brainstorm.md:161:- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<id>:failed"` in the `ideators` frontmatter list using the canonical id (`claude:failed` | `codex:failed` | `gemini:failed`). The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
commands/z-brainstorm.md:165:  - **abandon** — write a minimal abandoned BRAINSTORM.md (frontmatter: `artifact`, `slug`, `generated_at`, `command`, `input_hash`, `ideators` with `:failed` suffix on the failed members, `ideator_models`, `status: abandoned`, `chosen_framing: abandoned`; body: a single `## Abandoned` section with one sentence of context) so `/z-plan` can detect the prior attempt, then exit.
commands/z-brainstorm.md:166:- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.
commands/z-brainstorm.md:168:Log every individual failure as `ideator_failed` regardless of the bucket above.
commands/z-brainstorm.md:180:4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:
commands/z-brainstorm.md:189:   depends_on: [<RESEARCH.md if ingested>]
commands/z-brainstorm.md:254:1. Update the `chosen_framing:` field in the BRAINSTORM.md frontmatter from `pending` to the picked ideator id (`claude` | `codex` | `gemini`).
commands/z-brainstorm.md:260:1. Archive the just-written BRAINSTORM.md to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer). Before archiving, update the archived copy's frontmatter to `status: complete`, `chosen_framing: restart` so the historical record is spec-valid.
commands/z-brainstorm.md:262:3. Start a fresh RUN: regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.
commands/z-brainstorm.md:271:Log `brainstorm_run_end`:
commands/z-brainstorm.md:274:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
commands/z-brainstorm.md:286:  /z-plan <task>          — start the rigorous planning pipeline; it will auto-detect BRAINSTORM.md
commands/z-plan.md:19:   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
commands/z-plan.md:39:9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
commands/z-plan.md:45:10. **Pre-plan artifact detection.** Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
commands/z-plan.md:46:    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
commands/z-plan.md:47:    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
commands/z-plan.md:48:    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
commands/z-plan.md:85:**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
commands/z-plan.md:101:**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
commands/z-plan.md:103:- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
commands/z-plan.md:104:- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
commands/z-plan.md:107:- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
commands/z-plan.md:108:- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
commands/z-plan.md:109:- **(c) Skip both** — RESEARCH.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
commands/z-plan.md:110:- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.
commands/z-plan.md:232:The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:
commands/z-plan.md:239:| BRAINSTORM.md | z-harness/<slug>/BRAINSTORM.md | <iso timestamp or "n/a"> |
commands/z-plan.md:240:| RESEARCH.md | z-harness/<slug>/RESEARCH.md | <iso timestamp or "n/a"> |
commands/z-research.md:2:description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
commands/z-research.md:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
commands/z-research.md:36:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
commands/z-research.md:41:**Setup does NOT mutate `z-harness/<slug>/RESEARCH.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.
commands/z-research.md:44:- `z-harness/<slug>/RESEARCH.md`
commands/z-research.md:81:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
commands/z-research.md:94:   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
commands/z-research.md:98:2. **Existing-RESEARCH.md handling (deferred from old Setup step 7).** If `z-harness/$Z_HARNESS_SLUG/RESEARCH.md` exists, prompt the user via `AskUserQuestion` with three options:
commands/z-research.md:99:   - **archive-and-start-fresh** — archive the existing note (`mv z-harness/$Z_HARNESS_SLUG/RESEARCH.md z-harness/$Z_HARNESS_SLUG/archive/$RUN/RESEARCH.previous.md`) and proceed with a clean draft.
commands/z-research.md:100:   - **continue (re-use existing)** — leave the existing RESEARCH.md in place and treat this run as a refinement; the existing note's findings become inputs to Phase 3.
commands/z-research.md:101:   - **abort** — exit cleanly. **Do NOT touch the existing RESEARCH.md or any sibling file.** Log a `phase0_5_abort` event and return.
commands/z-research.md:175:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
commands/z-research.md:179:The final frontmatter uses **`EXPLORES_SUCCEEDED`** for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` frontmatter field. Do not fabricate `explore_calls` from `EXPLORE_BUDGET`.
commands/z-research.md:206:**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:
commands/z-research.md:209:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
commands/z-research.md:245:  - **abandon** — write nothing further; log `research_run_end` with `status: abandoned_critique_failure` and exit.
commands/z-research.md:262:Update the draft accordingly. If a consultant tried to recommend an approach despite the MODE prohibition, **strip the recommendation** and log `research_temptation` for the consultant turn.
commands/z-research.md:287:Write final `z-harness/$Z_HARNESS_SLUG/RESEARCH.md`:
commands/z-research.md:298:# explore_failures only emitted if (EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED) > 0:
commands/z-research.md:299:explore_failures: <N>
commands/z-research.md:328:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
commands/z-research.md:329:  "$(printf '{"slug":"%s","explore_calls":%d,"explore_failures":%d,"status":"%s"}' \
commands/z-research.md:336:Research complete. RESEARCH.md written to z-harness/<slug>/RESEARCH.md.

exec
/bin/zsh -lc "rg -n \"Z_HARNESS_RETRY_UPGRADE|complexity-classifier|Complexity:|Agent\\(model|model=\\\"opus\\\"|Z_HARNESS_BRAINSTORM_EXPLORE\" . 2>/dev/null" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./skills/z-brainstorm/SKILL.md:83:If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./skills/z-brainstorm/SKILL.md:94:If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./README.md:121:- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./README.md:124:- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
./skills/z-implement-next/SKILL.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./skills/z-implement-next/SKILL.md:49:- `high` → `model="opus"`
./skills/z-implement-next/SKILL.md:65:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./skills/z-implement-next/SKILL.md:67:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./commands/z-implement-next.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./commands/z-implement-next.md:49:- `high` → `model="opus"`
./commands/z-implement-next.md:65:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./commands/z-implement-next.md:67:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./agents/implementer.md:17:- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./agents/implementer.md:18:- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./skills/z-implement-all/SKILL.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./skills/z-implement-all/SKILL.md:162:- `high` → `model="opus"`
./skills/z-implement-all/SKILL.md:169:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./skills/z-implement-all/SKILL.md:180:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./skills/z-implement-all/SKILL.md:182:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./skills/z-implement-all/SKILL.md:249:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./skills/z-implement-all/SKILL.md:255:  model="opus",
./skills/z-plan/SKILL.md:276:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./skills/z-plan/SKILL.md:281:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./commands/z-brainstorm.md:83:If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./commands/z-brainstorm.md:94:If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./agents/complexity-classifier.md:2:name: complexity-classifier
./agents/complexity-classifier.md:24:1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./commands/z-plan.md:276:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./commands/z-plan.md:281:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./commands/z-implement-all.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./commands/z-implement-all.md:162:- `high` → `model="opus"`
./commands/z-implement-all.md:169:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./commands/z-implement-all.md:180:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./commands/z-implement-all.md:182:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./commands/z-implement-all.md:249:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./commands/z-implement-all.md:255:  model="opus",
./skills/z-amend/SKILL.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./brainstorm-and-research/TASKS.md:14:  - **Complexity:** low
./brainstorm-and-research/TASKS.md:20:  - **Complexity:** low
./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/TASKS.md:42:  - **Complexity:** high
./brainstorm-and-research/TASKS.md:66:  - **Complexity:** high
./brainstorm-and-research/TASKS.md:85:  - **Complexity:** medium
./brainstorm-and-research/TASKS.md:95:    - Env vars documented: `Z_HARNESS_BRAINSTORM_EXPLORE`.
./brainstorm-and-research/TASKS.md:99:  - **Complexity:** low
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:3:Task: per-task-model-selection. Goal: Add per-task implementer model selection driven by a Haiku complexity classifier. Stamp `**Complexity:** low|medium|high` into each task block at /z-plan time (and re-stamp on /z-amend for new/modified tasks). /z-implement-all and /z-implement-next read the stamp and pass `model="sonnet"` or `model="opus"` directly on the implementer Agent(...) call. Retry (cycle ≥ 2) always dispatches model="opus" regardless of stamp. Missing stamp falls back to Sonnet with a logged warning. Replace the prior Z_HARNESS_RETRY_UPGRADE env-var pattern.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:6:- agents/complexity-classifier.md exists with Haiku frontmatter, declares STATUS:/TIER:/REASON: return shape, no Edit/Write tools.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:7:- /z-plan and skills/z-plan Phase 8 documents the parallel classifier dispatch and the **Complexity:** stamp.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:9:- /z-implement-all and skills mirror documents reading the stamp and passing model= on the implementer Agent call; retry block rewritten with model="opus"; env-var paragraph replaced with deprecation note.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:12:- README.md Z_HARNESS_RETRY_UPGRADE entry struck through with deprecation note.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:13:- No active uses of Z_HARNESS_RETRY_UPGRADE remain (deprecation pointers are OK).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:19:3. Gap analysis — anywhere a prior code path implicitly depended on Z_HARNESS_RETRY_UPGRADE that was missed? Anywhere the new model param is referenced but control flow doesn't actually use it?
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:26:=== agents/complexity-classifier.md (NEW) ===
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:28:name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:44:Heuristic 1: User-authored override. If task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:48:- Optional: prior-attempt reviewer feedback if retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — header says `RETRY v<N>`; effective model is already Opus.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:49:- `**Complexity:** <tier>` line — orchestrator stamps at plan-time and uses to pick model: `low|medium` → Sonnet, `high` → Opus. You don't act on tier yourself.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:52:Pick model from `**Complexity:**` stamp:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:54:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:57:Retry override. Cycle ≥ 2 force `model="opus"` regardless of stamp.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:68:This replaces previous Z_HARNESS_RETRY_UPGRADE=opus env-var pattern. Agent(...) supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:70:User-authored override: A user editing `**Complexity:** high` directly hand-picks Opus. The classifier preserves user-authored stamps (returns `REASON: user-authored override`).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:77:  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:84:"This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:91:"**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task..."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:92:"If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time), the classifier returns `REASON: user-authored override` and you leave the stamp alone."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:95:"**Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte. Log one `task_classified` event per re-classified task."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:98:"- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.prompt.md:101:Only references to Z_HARNESS_RETRY_UPGRADE remaining are deprecation pointers (in the "this replaces…" sentences and the struck-through README entry). No active uses.
./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./per-task-model-selection/FIX.md:9:`/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks waste a Sonnet cycle before failing Codex review. The existing `Z_HARNESS_RETRY_UPGRADE=opus` env var and `**Complexity:** high` opt-in are documented as advisory care signals only — they do not actually change the model. The `Agent(...)` tool now supports a per-call `model` parameter, so we can right-size implementer model per task.
./per-task-model-selection/FIX.md:17:1. **New `agents/complexity-classifier.md`** (Haiku subagent). Reads one task block + a SPEC.md slice the caller passes; returns `STATUS: classified\nTIER: low|medium|high\nREASON: <one line>`. No file edits. Self-contained.
./per-task-model-selection/FIX.md:18:2. **`/z-plan` Phase 8**: after writing TASKS.md, dispatch the classifier per task in parallel (single message, multiple Agent calls). Append `**Complexity:** <tier>` to each task block. Log a `task_classified` event per task to `events.jsonl` capturing the tier and rationale.
./per-task-model-selection/FIX.md:19:3. **`/z-amend` full-mode Phase 6**: for tasks added or whose acceptance/files block was materially modified, dispatch the classifier and update/append the `**Complexity:**` line. Preserve existing stamps on untouched tasks. Light mode unaffected — no implementer subagent runs there.
./per-task-model-selection/FIX.md:20:4. **`/z-implement-all` step 5 + `/z-implement-next`**: read `**Complexity:**` from the task block. Pass `model="sonnet"` for `low|medium` and `model="opus"` for `high` on the implementer `Agent(...)` call. If the stamp is missing, default to `model="sonnet"` and log a `missing_complexity_stamp` warning event.
./per-task-model-selection/FIX.md:21:5. **Retry bump**: on cycle ≥ 2 dispatch (after Codex review blockers/majors), always pass `model="opus"` regardless of stamp. Remove the `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern — direct model param replaces it. Keep an in-prompt "this is retry v<N> — apply Opus-level care to the fix" text signal so the implementer's prompt still primes for careful work.
./per-task-model-selection/FIX.md:22:6. **`agents/implementer.md`**: frontmatter stays `model: sonnet` as the fallback default (when no override is passed). Rewrite the "Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set..." prose to reflect that the orchestrator now picks the model directly via `Agent(model=...)`, not via env-var care signal. Keep the `**Complexity:** high` user opt-in language — it still works as a user override that the classifier and orchestrator both respect.
./per-task-model-selection/FIX.md:26:- `/Users/zeke/dev/z-harness/agents/complexity-classifier.md` (new)
./per-task-model-selection/FIX.md:35:- [x] `agents/complexity-classifier.md` exists with Haiku frontmatter, declares its return shape (`STATUS:`, `TIER:`, `REASON:`), and is read-only (no Edit/Write tools).
./per-task-model-selection/FIX.md:36:- [x] `/z-plan` Phase 8 documents the parallel-classifier dispatch and the `**Complexity:**` stamp.
./per-task-model-selection/FIX.md:38:- [x] `/z-implement-all` step 5 documents reading the stamp and passing `model=` on the implementer Agent call; the retry-bump block is rewritten to use `model="opus"` directly; the env-var paragraph is replaced.
./per-task-model-selection/FIX.md:41:- [x] No `Z_HARNESS_RETRY_UPGRADE` references remain in the harness command/agent files.
./per-task-model-selection/FIX.md:48:- Synthesized call: Option A (plan-time stamping). Retry bump = always Opus (per Codex). Missing-stamp fallback = `medium` (Sonnet) with logged warning. Remove `Z_HARNESS_RETRY_UPGRADE` env var; replace with direct `model=` parameter on `Agent(...)`. Classifier rationale logged to `events.jsonl`, not stamped into TASKS.md.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:9:-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:10:+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:22:-- Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set, this is a second retry and the orchestrator wants you to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:23:-- Optional: **`**Complexity:** high`** marker in the task block — user-explicit opt-in for harder reasoning; treat as a signal even if the model running you doesn't change.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:24:+- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:25:+- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:37:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:39:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:42:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:53:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:54:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:56:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:57:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:66:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:72:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:87:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:89:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:92:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:103:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:104:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:178:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:183:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:196:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:198:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:201:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:212:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:213:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:215:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:216:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:225:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:231:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:246:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:248:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:251:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:262:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:263:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:351:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:356:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:361:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:365:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:368:+name: complexity-classifier
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:390:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:567:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:764:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:811:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:815:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:818:+name: complexity-classifier
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:840:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1017:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff-v1.patch:1214:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/SPEC.md:310:Add the new commands to the existing command list / flow diagram. Document `Z_HARNESS_BRAINSTORM_EXPLORE` env var. Add example chain: `/z-research → /z-brainstorm → /z-plan` for the murky-problem case.
./brainstorm-and-research/SPEC.md:320:- Removing the `Z_HARNESS_RETRY_UPGRADE` deprecation note (separate concern; per-task-model-selection is the right place).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:5:Today `/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks burn a wasted Sonnet cycle (often producing a diff Codex flags with blockers) before retry. The harness already has a `Z_HARNESS_RETRY_UPGRADE=opus` env var and an opt-in `**Complexity:** high` task marker, but [commands/z-implement-all.md:168](../../commands/z-implement-all.md) explicitly notes this is only an *advisory care signal* read by the implementer's prompt — not a real model override. The Agent tool now supports a per-call `model` override; this fix wires that to a Haiku-classifier-stamped `**Complexity:**` tier on each task block.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:9:Files affected: `agents/implementer.md` (frontmatter + retry-care prose), `commands/z-plan.md` (Phase 8 emits TASKS.md), `commands/z-amend.md` (full-mode TASKS.md edits), `commands/z-implement-all.md` (line 158 implementer dispatch + retry-bump block), `commands/z-implement-next.md` (single-task variant). `/z-plan-light` Phase 7 runs implementation inline in the orchestrator thread (no implementer subagent), so light mode is **out of scope** — the classifier is irrelevant there. `/z-amend` light-mode also skipped for the same reason. Scope drops from 6 → 5 files. New file: `agents/complexity-classifier.md` (Haiku).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:13:- **Is this a real problem?** Yes. Documented in z-implement-all.md:168 — the current "Z_HARNESS_RETRY_UPGRADE=opus" env var is acknowledged as a stub that does not actually change the model. Hard tasks today must fail Sonnet review once before getting Opus-level care.
./z-harness/brainstorm-and-research/archive/tasks/T006/diff.patch:37:-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
./z-harness/brainstorm-and-research/archive/tasks/T006/diff.patch:38:+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./z-harness/brainstorm-and-research/archive/tasks/T006/diff.patch:41:+- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
./z-harness/brainstorm-and-research/TASKS.md:14:  - **Complexity:** low
./z-harness/brainstorm-and-research/TASKS.md:20:  - **Complexity:** low
./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/TASKS.md:42:  - **Complexity:** high
./z-harness/brainstorm-and-research/TASKS.md:66:  - **Complexity:** high
./z-harness/brainstorm-and-research/TASKS.md:85:  - **Complexity:** medium
./z-harness/brainstorm-and-research/TASKS.md:95:    - Env vars documented: `Z_HARNESS_BRAINSTORM_EXPLORE`.
./z-harness/brainstorm-and-research/TASKS.md:99:  - **Complexity:** low
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:9:-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:10:+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:22:-- Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set, this is a second retry and the orchestrator wants you to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:23:-- Optional: **`**Complexity:** high`** marker in the task block — user-explicit opt-in for harder reasoning; treat as a signal even if the model running you doesn't change.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:24:+- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:25:+- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:37:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:39:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:46:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:57:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:58:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:60:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:61:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:70:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:76:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:91:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:93:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:109:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:110:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:112:+`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:186:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:191:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:204:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:206:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:213:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:224:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:225:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:227:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:228:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:237:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:243:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:258:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:260:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:276:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:277:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:279:+`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:367:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:372:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:377:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:381:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:384:+name: complexity-classifier
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:406:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:583:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:780:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:18:Task: per-task-model-selection. Goal: Add per-task implementer model selection driven by a Haiku complexity classifier. Stamp `**Complexity:** low|medium|high` into each task block at /z-plan time (and re-stamp on /z-amend for new/modified tasks). /z-implement-all and /z-implement-next read the stamp and pass `model="sonnet"` or `model="opus"` directly on the implementer Agent(...) call. Retry (cycle ≥ 2) always dispatches model="opus" regardless of stamp. Missing stamp falls back to Sonnet with a logged warning. Replace the prior Z_HARNESS_RETRY_UPGRADE env-var pattern.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:21:- agents/complexity-classifier.md exists with Haiku frontmatter, declares STATUS:/TIER:/REASON: return shape, no Edit/Write tools.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:22:- /z-plan and skills/z-plan Phase 8 documents the parallel classifier dispatch and the **Complexity:** stamp.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:24:- /z-implement-all and skills mirror documents reading the stamp and passing model= on the implementer Agent call; retry block rewritten with model="opus"; env-var paragraph replaced with deprecation note.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:27:- README.md Z_HARNESS_RETRY_UPGRADE entry struck through with deprecation note.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:28:- No active uses of Z_HARNESS_RETRY_UPGRADE remain (deprecation pointers are OK).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:34:3. Gap analysis — anywhere a prior code path implicitly depended on Z_HARNESS_RETRY_UPGRADE that was missed? Anywhere the new model param is referenced but control flow doesn't actually use it?
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:41:=== agents/complexity-classifier.md (NEW) ===
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:43:name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:59:Heuristic 1: User-authored override. If task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:63:- Optional: prior-attempt reviewer feedback if retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — header says `RETRY v<N>`; effective model is already Opus.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:64:- `**Complexity:** <tier>` line — orchestrator stamps at plan-time and uses to pick model: `low|medium` → Sonnet, `high` → Opus. You don't act on tier yourself.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:67:Pick model from `**Complexity:**` stamp:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:69:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:72:Retry override. Cycle ≥ 2 force `model="opus"` regardless of stamp.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:83:This replaces previous Z_HARNESS_RETRY_UPGRADE=opus env-var pattern. Agent(...) supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:85:User-authored override: A user editing `**Complexity:** high` directly hand-picks Opus. The classifier preserves user-authored stamps (returns `REASON: user-authored override`).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:92:  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:99:"This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:106:"**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task..."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:107:"If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time), the classifier returns `REASON: user-authored override` and you leave the stamp alone."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:110:"**Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte. Log one `task_classified` event per re-classified task."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:113:"- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md."
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:116:Only references to Z_HARNESS_RETRY_UPGRADE remaining are deprecation pointers (in the "this replaces…" sentences and the struck-through README entry). No active uses.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:178:./agents/complexity-classifier.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:189:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:190:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:196:/bin/zsh -lc "rg -n \"Z_HARNESS_RETRY_UPGRADE|Complexity:|complexity-classifier|Agent\\(|model=|model:\" ." in /Users/zeke/dev/z-harness
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:202:./skills/z-implement-next/SKILL.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:204:./skills/z-implement-next/SKILL.md:49:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:206:./skills/z-implement-next/SKILL.md:52:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:209:./skills/z-implement-next/SKILL.md:63:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:224:./commands/z-implement-next.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:226:./commands/z-implement-next.md:49:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:228:./commands/z-implement-next.md:52:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:231:./commands/z-implement-next.md:63:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:234:./agents/implementer.md:17:- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:235:./agents/implementer.md:18:- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:247:./skills/z-plan/SKILL.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:248:./skills/z-plan/SKILL.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:251:./commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:254:./skills/z-implement-all/SKILL.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:256:./skills/z-implement-all/SKILL.md:162:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:258:./skills/z-implement-all/SKILL.md:165:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:261:./skills/z-implement-all/SKILL.md:176:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:262:./skills/z-implement-all/SKILL.md:178:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:265:./skills/z-implement-all/SKILL.md:245:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:267:./skills/z-implement-all/SKILL.md:251:  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:271:./README.md:107:- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:272:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:5:Today `/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks burn a wasted Sonnet cycle (often producing a diff Codex flags with blockers) before retry. The harness already has a `Z_HARNESS_RETRY_UPGRADE=opus` env var and an opt-in `**Complexity:** high` task marker, but [commands/z-implement-all.md:168](../../commands/z-implement-all.md) explicitly notes this is only an *advisory care signal* read by the implementer's prompt — not a real model override. The Agent tool now supports a per-call `model` override; this fix wires that to a Haiku-classifier-stamped `**Complexity:**` tier on each task block.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:273:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:9:Files affected: `agents/implementer.md` (frontmatter + retry-care prose), `commands/z-plan.md` (Phase 8 emits TASKS.md), `commands/z-amend.md` (full-mode TASKS.md edits), `commands/z-implement-all.md` (line 158 implementer dispatch + retry-bump block), `commands/z-implement-next.md` (single-task variant). `/z-plan-light` Phase 7 runs implementation inline in the orchestrator thread (no implementer subagent), so light mode is **out of scope** — the classifier is irrelevant there. `/z-amend` light-mode also skipped for the same reason. Scope drops from 6 → 5 files. New file: `agents/complexity-classifier.md` (Haiku).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:274:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:13:- **Is this a real problem?** Yes. Documented in z-implement-all.md:168 — the current "Z_HARNESS_RETRY_UPGRADE=opus" env var is acknowledged as a stub that does not actually change the model. Hard tasks today must fail Sonnet review once before getting Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:281:./agents/complexity-classifier.md:2:name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:282:./agents/complexity-classifier.md:5:model: haiku
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:283:./agents/complexity-classifier.md:24:1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:286:./skills/z-amend/SKILL.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:290:./per-task-model-selection/FIX.md:9:`/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks waste a Sonnet cycle before failing Codex review. The existing `Z_HARNESS_RETRY_UPGRADE=opus` env var and `**Complexity:** high` opt-in are documented as advisory care signals only — they do not actually change the model. The `Agent(...)` tool now supports a per-call `model` parameter, so we can right-size implementer model per task.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:292:./per-task-model-selection/FIX.md:17:1. **New `agents/complexity-classifier.md`** (Haiku subagent). Reads one task block + a SPEC.md slice the caller passes; returns `STATUS: classified\nTIER: low|medium|high\nREASON: <one line>`. No file edits. Self-contained.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:293:./per-task-model-selection/FIX.md:18:2. **`/z-plan` Phase 8**: after writing TASKS.md, dispatch the classifier per task in parallel (single message, multiple Agent calls). Append `**Complexity:** <tier>` to each task block. Log a `task_classified` event per task to `events.jsonl` capturing the tier and rationale.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:294:./per-task-model-selection/FIX.md:19:3. **`/z-amend` full-mode Phase 6**: for tasks added or whose acceptance/files block was materially modified, dispatch the classifier and update/append the `**Complexity:**` line. Preserve existing stamps on untouched tasks. Light mode unaffected — no implementer subagent runs there.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:295:./per-task-model-selection/FIX.md:20:4. **`/z-implement-all` step 5 + `/z-implement-next`**: read `**Complexity:**` from the task block. Pass `model="sonnet"` for `low|medium` and `model="opus"` for `high` on the implementer `Agent(...)` call. If the stamp is missing, default to `model="sonnet"` and log a `missing_complexity_stamp` warning event.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:296:./per-task-model-selection/FIX.md:21:5. **Retry bump**: on cycle ≥ 2 dispatch (after Codex review blockers/majors), always pass `model="opus"` regardless of stamp. Remove the `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern — direct model param replaces it. Keep an in-prompt "this is retry v<N> — apply Opus-level care to the fix" text signal so the implementer's prompt still primes for careful work.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:297:./per-task-model-selection/FIX.md:22:6. **`agents/implementer.md`**: frontmatter stays `model: sonnet` as the fallback default (when no override is passed). Rewrite the "Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set..." prose to reflect that the orchestrator now picks the model directly via `Agent(model=...)`, not via env-var care signal. Keep the `**Complexity:** high` user opt-in language — it still works as a user override that the classifier and orchestrator both respect.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:298:./per-task-model-selection/FIX.md:26:- `/Users/zeke/dev/z-harness/agents/complexity-classifier.md` (new)
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:299:./per-task-model-selection/FIX.md:35:- [ ] `agents/complexity-classifier.md` exists with Haiku frontmatter, declares its return shape (`STATUS:`, `TIER:`, `REASON:`), and is read-only (no Edit/Write tools).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:300:./per-task-model-selection/FIX.md:36:- [ ] `/z-plan` Phase 8 documents the parallel-classifier dispatch and the `**Complexity:**` stamp.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:301:./per-task-model-selection/FIX.md:38:- [ ] `/z-implement-all` step 5 documents reading the stamp and passing `model=` on the implementer Agent call; the retry-bump block is rewritten to use `model="opus"` directly; the env-var paragraph is replaced.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:302:./per-task-model-selection/FIX.md:41:- [ ] No `Z_HARNESS_RETRY_UPGRADE` references remain in the harness command/agent files.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:303:./per-task-model-selection/FIX.md:48:- Synthesized call: Option A (plan-time stamping). Retry bump = always Opus (per Codex). Missing-stamp fallback = `medium` (Sonnet) with logged warning. Remove `Z_HARNESS_RETRY_UPGRADE` env var; replace with direct `model=` parameter on `Agent(...)`. Classifier rationale logged to `events.jsonl`, not stamped into TASKS.md.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:308:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:11:**Current tooling:** `Agent(...)` now supports per-call `model` override parameter (e.g., `model="sonnet"` or `model="opus"`).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:309:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:22:- During `/z-plan` Phase 8 (TASKS.md generation) and `/z-amend` (full-mode TASKS.md edits), dispatch a Haiku `complexity-classifier` subagent in parallel per task.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:310:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:23:- Append `**Complexity:** low|medium|high` to each task block in TASKS.md.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:311:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:49:- Store classifier result in TASKS.md as `**Complexity:**` stamp (like Option A).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:312:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:57:- **Complexity:** Adds logic to detect "has this task changed since the stamp" — doable via `mtime` on TASKS.md or hash of the task block itself.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:313:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:65:**z-implement-all.md lines 158-170:** Currently sets `Z_HARNESS_RETRY_UPGRADE=opus` env var if task has `**Complexity:** high` or if retry cycle ≥ 2. This is an *advisory signal*, not a model override — implementer reads it in its prompt.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:314:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:67:**Agent() tool:**  Now supports `model="sonnet"` / `model="opus"` per-call override, so we can pass the model directly when dispatching.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:320:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:1:Recommend **Option A: plan-time stamping**, with a narrow mitigation: `/z-amend` should preserve existing `**Complexity:**` stamps for unchanged tasks and classify only new or materially rewritten task blocks.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:321:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:5:- It is the simplest operational model: `TASKS.md` becomes the source of truth, and implementers just read `low|medium|high`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:322:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:8:- It integrates cleanly with the current pattern that already checks `**Complexity:** high`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:323:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:16:- Classify only tasks missing `**Complexity:**`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:324:./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:22:Retry interaction: dispatch should compute model from complexity plus retry bump directly, using the new `Agent(..., model=...)` override. For today:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:343:./commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:344:./commands/z-plan.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:345:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:9:-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:346:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:10:+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:347:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:22:-- Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set, this is a second retry and the orchestrator wants you to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:348:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:23:-- Optional: **`**Complexity:** high`** marker in the task block — user-explicit opt-in for harder reasoning; treat as a signal even if the model running you doesn't change.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:349:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:24:+- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:350:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:25:+- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:351:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:37:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:353:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:39:+- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:355:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:42:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:358:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:53:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:359:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:54:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:360:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:56:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:361:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:57:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:362:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:66:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:364:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:72:+  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:365:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:87:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:367:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:89:+- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:369:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:92:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:372:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:103:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:373:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:104:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:379:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:178:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:380:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:183:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:381:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:196:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:383:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:198:+- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:385:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:201:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:388:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:212:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:389:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:213:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:390:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:215:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:391:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:216:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:392:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:225:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:394:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:231:+  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:395:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:246:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:397:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:248:+- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:399:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:251:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:402:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:262:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:403:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:263:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:409:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:351:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:410:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:356:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:411:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:361:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:412:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:365:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:413:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:368:+name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:415:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:390:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:418:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:567:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:421:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:764:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:422:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:811:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:423:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:815:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:424:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:818:+name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:426:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:840:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:429:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1017:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:432:./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1214:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:446:./commands/z-implement-all.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:448:./commands/z-implement-all.md:162:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:450:./commands/z-implement-all.md:165:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:453:./commands/z-implement-all.md:176:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:454:./commands/z-implement-all.md:178:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:457:./commands/z-implement-all.md:245:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:459:./commands/z-implement-all.md:251:  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:469:/bin/zsh -lc "sed -n '1,140p' agents/complexity-classifier.md" in /Users/zeke/dev/z-harness
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:472:name: complexity-classifier
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:494:1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:533:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:535:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:538:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:549:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:551:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:618:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:624:  model="opus",
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:661:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:666:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:685:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:687:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:690:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:701:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:758:- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:759:- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:870:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:872:- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:875:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:886:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1065:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1138:    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1140:    49	- `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1143:    52	**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1154:    63	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1198:    17	- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1199:    18	- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1215:   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1234:   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1262: - `high` → `model="opus"`
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1265:-**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1266:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1274:/bin/zsh -lc "nl -ba agents/complexity-classifier.md | sed -n '20,34p'" in /Users/zeke/dev/z-harness
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1280:    24	1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1293:- **Major:** `/z-amend` reclassification is effectively disabled for existing stamped tasks. [agents/complexity-classifier.md](/Users/zeke/dev/z-harness/agents/complexity-classifier.md:24) treats any existing `**Complexity:**` as a user override, while [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) sends modified task blocks for reclassification, so previously auto-stamped modified tasks will keep stale tiers unless the old stamp is stripped or the classifier gets explicit “ignore existing auto stamp” context.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1297:- **Major:** `/z-implement-next` states the retry override but has no retry dispatch path that can actually use it. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:52) says cycle ≥ 2 forces Opus, but after review it only says to apply findings directly and then mark done, with no second implementer `Agent(..., model="opus")` call; the skill mirror has the same gap.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1303:- **Major:** `/z-amend` reclassification is effectively disabled for existing stamped tasks. [agents/complexity-classifier.md](/Users/zeke/dev/z-harness/agents/complexity-classifier.md:24) treats any existing `**Complexity:**` as a user override, while [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) sends modified task blocks for reclassification, so previously auto-stamped modified tasks will keep stale tiers unless the old stamp is stripped or the classifier gets explicit “ignore existing auto stamp” context.
./per-task-model-selection/archive/tasks/per-task-model-selection/review.response.md:1307:- **Major:** `/z-implement-next` states the retry override but has no retry dispatch path that can actually use it. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:52) says cycle ≥ 2 forces Opus, but after review it only says to apply findings directly and then mark done, with no second implementer `Agent(..., model="opus")` call; the skill mirror has the same gap.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:4:1. /z-amend re-classification was disabled because heuristic #1 treated any existing stamp as user-authored override. Claim: strip the existing **Complexity:** line BEFORE dispatching, unless user explicitly named a tier.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:5:2. Modified-task trigger too narrow (Files/Acceptance/Tests only). Claim: broadened to "any line OTHER than the **Complexity:** line itself" enumerating title, Files, Depends, Acceptance, **Tests:**, **REMOTE_VERIFY:**, **DOCS:**.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:10:- /z-plan Phase 8: parallel classifier dispatch, append **Complexity:** stamp.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:12:- /z-implement-all + /z-implement-next: read **Complexity:**, pass model="sonnet" for low|medium, model="opus" for high. Missing stamp → default sonnet + log missing_complexity_stamp warning.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:13:- Retry: cycle ≥ 2 always model="opus". Remove Z_HARNESS_RETRY_UPGRADE env var.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:19:- **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:22:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:24:- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:31:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:35:Replaces previous Z_HARNESS_RETRY_UPGRADE env-var pattern. **User-authored override.** If user writes `**Complexity:** high` directly, classifier preserves it (returns `REASON: user-authored override`).
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:37:Cycle ≥ 2 prompt block now passes model="opus" explicitly in the Agent() call.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:40:**Pick the implementer model from the task block's `**Complexity:**` stamp**:
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:42:- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:51:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:53:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"`, re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/archive/tasks/per-task-model-selection/review.prompt.md:56:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) once per task in parallel. Parse TIER/REASON, Edit TASKS.md to append `**Complexity:** <tier>`. Log `task_classified` event. If task block already has user-authored stamp, classifier returns `REASON: user-authored override` and you leave it alone.
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:321:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:326:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:632:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.prompt.md:637:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:310:Add the new commands to the existing command list / flow diagram. Document `Z_HARNESS_BRAINSTORM_EXPLORE` env var. Add example chain: `/z-research → /z-brainstorm → /z-plan` for the murky-problem case.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:320:- Removing the `Z_HARNESS_RETRY_UPGRADE` deprecation note (separate concern; per-task-model-selection is the right place).
./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:299:?? agents/complexity-classifier.md
./z-harness/archive/tasks/per-task-model-selection/review.response.md:19:1. /z-amend re-classification was disabled because heuristic #1 treated any existing stamp as user-authored override. Claim: strip the existing **Complexity:** line BEFORE dispatching, unless user explicitly named a tier.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:20:2. Modified-task trigger too narrow (Files/Acceptance/Tests only). Claim: broadened to "any line OTHER than the **Complexity:** line itself" enumerating title, Files, Depends, Acceptance, **Tests:**, **REMOTE_VERIFY:**, **DOCS:**.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:25:- /z-plan Phase 8: parallel classifier dispatch, append **Complexity:** stamp.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:27:- /z-implement-all + /z-implement-next: read **Complexity:**, pass model="sonnet" for low|medium, model="opus" for high. Missing stamp → default sonnet + log missing_complexity_stamp warning.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:28:- Retry: cycle ≥ 2 always model="opus". Remove Z_HARNESS_RETRY_UPGRADE env var.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:34:- **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:37:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:39:- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:46:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:50:Replaces previous Z_HARNESS_RETRY_UPGRADE env-var pattern. **User-authored override.** If user writes `**Complexity:** high` directly, classifier preserves it (returns `REASON: user-authored override`).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:52:Cycle ≥ 2 prompt block now passes model="opus" explicitly in the Agent() call.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:55:**Pick the implementer model from the task block's `**Complexity:**` stamp**:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:57:- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:66:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:68:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"`, re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:71:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) once per task in parallel. Parse TIER/REASON, Edit TASKS.md to append `**Complexity:** <tier>`. Log `task_classified` event. If task block already has user-authored stamp, classifier returns `REASON: user-authored override` and you leave it alone.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:80:/bin/zsh -lc "rg -n \"Re-classify complexity|missing_complexity_stamp|Retry override|single-shot command|Z_HARNESS_RETRY_UPGRADE|Complexity stamp|strip the existing\" commands /Users/zeke/.codex/skills -g 'z-amend*' -g 'z-implement-all*' -g 'z-implement-next*' -g 'z-plan*'" in /Users/zeke/dev/z-harness
./z-harness/archive/tasks/per-task-model-selection/review.response.md:84:commands/z-implement-next.md:65:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:85:commands/z-implement-next.md:67:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:86:commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:87:commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:90:commands/z-implement-all.md:169:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:91:commands/z-implement-all.md:180:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:109:?? agents/complexity-classifier.md
./z-harness/archive/tasks/per-task-model-selection/review.response.md:127:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:129:+- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:136:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:147:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./z-harness/archive/tasks/per-task-model-selection/review.response.md:148:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:150:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:151:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:160:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:166:+  model="opus",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:181:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:183:+- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:199:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:200:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:202:+`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:276:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:281:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/archive/tasks/per-task-model-selection/review.response.md:301:   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:320:    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:322:    49	- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:338:    65	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:340:    67	`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:349:   160	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:351:   162	- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:358:   169	**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:369:   180	This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:371:   182	**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:377:   249	Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:383:   255	  model="opus",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:393:   160	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:395:   162	- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:402:   169	**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:413:   180	This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:415:   182	**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:421:   249	Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:427:   255	  model="opus",
./z-harness/archive/tasks/per-task-model-selection/review.response.md:443:   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:460:    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./z-harness/archive/tasks/per-task-model-selection/review.response.md:462:    49	- `high` → `model="opus"`
./z-harness/archive/tasks/per-task-model-selection/review.response.md:478:    65	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:480:    67	`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.prompt.md:20:- Phase 1: doc-fetcher iff INDEX.json; optional Explore behind Z_HARNESS_BRAINSTORM_EXPLORE=1; RESEARCH.md ingestion (≤20KB inline; >20KB extractive summary stored to archive/<run>/research-summary-for-brainstorm.md).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.prompt.md:123:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/review.prompt.md:134:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.prompt.md:417:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/review.prompt.md:428:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:277:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:282:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:588:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:593:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:14:  - **Complexity:** low
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:20:  - **Complexity:** low
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:42:  - **Complexity:** high
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:66:  - **Complexity:** high
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:85:  - **Complexity:** medium
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:95:    - Env vars documented: `Z_HARNESS_BRAINSTORM_EXPLORE`.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:99:  - **Complexity:** low
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:11:**Current tooling:** `Agent(...)` now supports per-call `model` override parameter (e.g., `model="sonnet"` or `model="opus"`).
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:22:- During `/z-plan` Phase 8 (TASKS.md generation) and `/z-amend` (full-mode TASKS.md edits), dispatch a Haiku `complexity-classifier` subagent in parallel per task.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:23:- Append `**Complexity:** low|medium|high` to each task block in TASKS.md.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:49:- Store classifier result in TASKS.md as `**Complexity:**` stamp (like Option A).
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:57:- **Complexity:** Adds logic to detect "has this task changed since the stamp" — doable via `mtime` on TASKS.md or hash of the task block itself.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:65:**z-implement-all.md lines 158-170:** Currently sets `Z_HARNESS_RETRY_UPGRADE=opus` env var if task has `**Complexity:** high` or if retry cycle ≥ 2. This is an *advisory signal*, not a model override — implementer reads it in its prompt.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:67:**Agent() tool:**  Now supports `model="sonnet"` / `model="opus"` per-call override, so we can pass the model directly when dispatching.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:90:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:101:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:384:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:395:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:1:Recommend **Option A: plan-time stamping**, with a narrow mitigation: `/z-amend` should preserve existing `**Complexity:**` stamps for unchanged tasks and classify only new or materially rewritten task blocks.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:8:- It integrates cleanly with the current pattern that already checks `**Complexity:** high`.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:16:- Classify only tasks missing `**Complexity:**`.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:89:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:100:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:396:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/diff.patch:407:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:282:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:287:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:598:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/diff.patch:603:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:336:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:341:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:647:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:652:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T005/review.response.md:908:?? agents/complexity-classifier.md
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:2:skills/z-plan/SKILL.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:3:skills/z-plan/SKILL.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:23:commands/z-implement-all.md:182:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:55:commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/transcripts/001-codex-bundled-decisions.response.md:56:commands/z-plan.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:775:If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:786:If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:987:./agents/complexity-classifier.md
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1158:./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1181:./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1207:./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1306:./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1365:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1387:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1955:    66	  - **Complexity:** high
./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2232:   155	- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:35:- Phase 1: doc-fetcher iff INDEX.json; optional Explore behind Z_HARNESS_BRAINSTORM_EXPLORE=1; RESEARCH.md ingestion (≤20KB inline; >20KB extractive summary stored to archive/<run>/research-summary-for-brainstorm.md).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:138:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:149:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:432:+If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:443:+If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:1649:./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:1790:./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:1806:./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:1839:./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:1980:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2066:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2428:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1158:./brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2443:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1181:./z-harness/brainstorm-and-research/SPEC.md:151:- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2464:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1207:./brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2538:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1306:./z-harness/brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2589:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1365:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:32:    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:2606:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1387:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:155:- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:3086:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:2232:   155	- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:3687:    84	If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:
./z-harness/brainstorm-and-research/archive/tasks/T003/review.response.md:3698:    95	If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.

exec
/bin/zsh -lc 'git diff -- README.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
diff --git a/README.md b/README.md
index 7b3fc4d..e2ccd9c 100644
--- a/README.md
+++ b/README.md
@@ -6,6 +6,19 @@ A Claude Code plugin that wraps planning and implementation in a rigorous, cross
 
 Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.
 
+### Pre-planning (optional; feed into `/z-plan`)
+
+- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators (Claude Sonnet + Codex + Gemini). Produces `BRAINSTORM.md` in `z-harness/<slug>/`. Cost target: ≤200K tokens. Use this when the framing or approach for a problem is still open and you want divergent perspectives before locking in a plan.
+- **`/z-research <question>`** — Heavier terrain mapping via parallel Explores + cross-LLM critique. Produces `RESEARCH.md` in `z-harness/<slug>/`. Cost target: ≤2M tokens. Use this when you need concrete file:line evidence about an existing codebase or design space before deciding what to build.
+
+**Typical chains:**
+
+- Murky problem: `/z-research → /z-brainstorm → /z-plan` — research terrain first, generate framed approaches, then plan.
+- Lighter case: `/z-brainstorm → /z-plan` — skip research when the codebase is already well understood.
+- Standard: `/z-plan` alone — when the problem and approach are already clear.
+
+`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.
+
 ### Planning
 
 - **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
@@ -45,6 +58,7 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 | `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
 | `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
 | `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries, paper qtctl restarts |
+| `ideator` | sonnet | Claude-side ideator in `/z-brainstorm` Phase 2 (one of three parallel ideators) |
 
 ## Operating principles
 
@@ -104,9 +118,35 @@ When a downstream repo defines its own skills that interoperate with z-harness,
 - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
 - `Z_HARNESS_MAX_EXPLORE` — default `3`. Cap on `Explore` subagent dispatches per `/z-plan` run.
 - `Z_HARNESS_DOC_STALENESS_THRESHOLD` — default `20` (percent). Above this, `/z-plan` halts and recommends `/z-maintain-docs` first.
-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
 - `Z_HARNESS_LOCAL_CARGO_CLEAN` — set to `1` at the start of `/z-implement-all` to trigger a one-time local `cargo clean`.
 - `Z_HARNESS_SLUG` — set by commands; namespaces all output paths under `z-harness/<slug>/`.
+- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
+
+## Telemetry event types
+
+All events are appended to `z-harness/metrics.jsonl` via `scripts/log-event.sh`. Standard per-event fields: `prompt_chars`, `response_chars`, `wall_ms`.
+
+Event kinds introduced by `/z-brainstorm` and `/z-research`:
+
+| Event | Emitted by |
+|---|---|
+| `brainstorm_run_start` | `/z-brainstorm` setup |
+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
+| `research_run_start` | `/z-research` setup |
+| `research_run_end` | `/z-research` Phase 6 |
+| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
+| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
+| `research_temptation` | `/z-research` when orchestrator drafts a recommendation it must not make |
+| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
+| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
+| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate |
+| `explore_failure` | any command that dispatches an Explore subagent that does not return |
+
+## Known v1 limitations
+
+- **No per-subagent wall-clock timeout.** `Agent()` does not expose a per-call timeout; subagents that hang block the entire run. User-facing escape: ctrl-c to abort.
+- **No doc-fetcher caching across precontext and plan runs.** If you run `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched twice (once per command). Marked as a v2 candidate; the cost is low enough today.
 
 ## Layout
 
@@ -116,6 +156,8 @@ z-harness/
 │   ├── plugin.json
 │   └── marketplace.json
 ├── commands/
+│   ├── z-brainstorm.md
+│   ├── z-research.md
 │   ├── z-plan.md
 │   ├── z-plan-light.md
 │   ├── z-test.md

codex
I found that the main precontext and event claims line up with the command files. I’m checking whether the README introduces misleading guarantees around telemetry shape, because docs that over-specify metrics fields can break consumers just as easily as missing event names.
exec
/bin/zsh -lc "sed -n '1,220p' scripts/log-event.sh" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
#!/usr/bin/env bash
# Append a structured event to the run's events.jsonl.
#
# Usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>
#
# Slug namespacing: if env var Z_HARNESS_SLUG is set (non-empty), all output
# paths are namespaced under z-harness/<slug>/ so multiple plans can coexist
# in the same repo. If unset, the legacy flat layout (z-harness/archive/...)
# is used for backward compat with old plans.
#
# Example:
#   Z_HARNESS_SLUG=add-rate-limit \
#   log-event.sh 20260517T144200Z-add-rate-limit consult \
#     '{"llm":"gemini","phase":3,"prompt_chars":4821,"wall_ms":18204,"transcript":"001-gemini.md"}'
#
# Writes to (with Z_HARNESS_SLUG set):
#   z-harness/<slug>/archive/<run>/events.jsonl   (per-run log, append-only)
#   z-harness/metrics.jsonl                       (repo-wide aggregate, slug added to event)
#
# Writes to (legacy, no slug):
#   z-harness/archive/<run>/events.jsonl
#   z-harness/metrics.jsonl
#
# Both files are JSON Lines. Append-safe under concurrent calls via flock when available.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>" >&2
  exit 2
fi

RUN="$1"
KIND="$2"
PAYLOAD="$3"

# Resolve repo root (caller's cwd is assumed to be inside the target repo).
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Slug namespacing — see header comment.
SLUG="${Z_HARNESS_SLUG:-}"
if [[ -n "$SLUG" ]]; then
  RUN_DIR="$REPO_ROOT/z-harness/$SLUG/archive/$RUN"
else
  RUN_DIR="$REPO_ROOT/z-harness/archive/$RUN"
fi
mkdir -p "$RUN_DIR"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Validate payload is JSON; if not, wrap it as a string.
if ! printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
  PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.dumps({"raw": sys.stdin.read()}))')"
fi

EVENT="$(python3 -c '
import json, sys
ts, run, kind, slug, payload = sys.argv[1:6]
obj = {"ts": ts, "run": run, "kind": kind}
if slug:
    obj["slug"] = slug
obj.update(json.loads(payload))
print(json.dumps(obj, separators=(",", ":")))
' "$TS" "$RUN" "$KIND" "$SLUG" "$PAYLOAD")"

append() {
  local target="$1"
  if command -v flock >/dev/null 2>&1; then
    ( flock 9; printf '%s\n' "$EVENT" >> "$target" ) 9>>"$target.lock"
  else
    printf '%s\n' "$EVENT" >> "$target"
  fi
}

append "$RUN_DIR/events.jsonl"
append "$REPO_ROOT/z-harness/metrics.jsonl"

exec
/bin/zsh -lc "rg -n \"log-event\\.sh|events\\.jsonl|metrics\\.jsonl|prompt_chars|response_chars|wall_ms\" commands skills scripts agents README.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
README.md:7:Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.
README.md:47:- **`/z-stats`** — Read-only progress + cost report from `metrics.jsonl` and TASKS.md. No writes, no LLM calls.
README.md:128:All events are appended to `z-harness/metrics.jsonl` via `scripts/log-event.sh`. Standard per-event fields: `prompt_chars`, `response_chars`, `wall_ms`.
README.md:183:│   ├── log-event.sh
commands/z-review-all.md:27:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_all_start "$START_PAYLOAD"
commands/z-review-all.md:46:   - Find the first `task_start` event in `$BASE/metrics.jsonl` (or `events.jsonl` for the slug-namespaced events). That's the plan's start timestamp `T_start`.
commands/z-review-all.md:188:Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
skills/z-review-all/SKILL.md:27:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_all_start "$START_PAYLOAD"
skills/z-review-all/SKILL.md:46:   - Find the first `task_start` event in `$BASE/metrics.jsonl` (or `events.jsonl` for the slug-namespaced events). That's the plan's start timestamp `T_start`.
skills/z-review-all/SKILL.md:188:Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
agents/spec-precheck.md:32:This is what populates `precheck_*` rows in `metrics.jsonl` — the spec mandated it but past runs never emitted it because the orchestrator can't time a subagent from outside.
agents/gemini-consultant.md:87:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult \
agents/gemini-consultant.md:88:  "$(printf '{"llm":"gemini","mode":"%s","prompt_chars":%d,"response_chars":%d,"wall_ms":%d,"transcript":"%s"}' \
scripts/log-event.sh:2:# Append a structured event to the run's events.jsonl.
scripts/log-event.sh:4:# Usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>
scripts/log-event.sh:13:#   log-event.sh 20260517T144200Z-add-rate-limit consult \
scripts/log-event.sh:14:#     '{"llm":"gemini","phase":3,"prompt_chars":4821,"wall_ms":18204,"transcript":"001-gemini.md"}'
scripts/log-event.sh:17:#   z-harness/<slug>/archive/<run>/events.jsonl   (per-run log, append-only)
scripts/log-event.sh:18:#   z-harness/metrics.jsonl                       (repo-wide aggregate, slug added to event)
scripts/log-event.sh:21:#   z-harness/archive/<run>/events.jsonl
scripts/log-event.sh:22:#   z-harness/metrics.jsonl
scripts/log-event.sh:29:  echo "usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>" >&2
scripts/log-event.sh:75:append "$RUN_DIR/events.jsonl"
scripts/log-event.sh:76:append "$REPO_ROOT/z-harness/metrics.jsonl"
agents/codex-reviewer.md:30:  "$(printf '{"id":"%s","cycle":%d,"blockers":%d,"majors":%d,"prompt_chars":%d,"response_chars":%d,"return_chars":%d}' \
agents/codex-reviewer.md:34:This populates `review_*` rows in `metrics.jsonl` separately from the legacy single `review` event, and lets post-run analysis distinguish first-pass vs second-pass review cost. (Keep the legacy `review` event from step 6 for backward compat with the existing analysis scripts.)
agents/codex-reviewer.md:94:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/$TASK_ID" review \
agents/codex-reviewer.md:95:  "$(printf '{"prompt_chars":%d,"response_chars":%d,"return_chars":%d,"wall_ms":%d}' \
scripts/log-phase.sh:4:# This is a thin sugar layer over log-event.sh so subagents can emit the
scripts/log-phase.sh:25:#   prompt_chars         (int)     -- fallback if token counts unavailable; we
scripts/log-phase.sh:26:#   response_chars       (int)        estimate tokens ≈ chars/4 in analysis
scripts/log-phase.sh:28:# Honors Z_HARNESS_SLUG just like log-event.sh.
scripts/log-phase.sh:34:LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"
scripts/log-phase.sh:42:# back to python3 (already a hard dep of log-event.sh).
scripts/log-phase.sh:76:p["wall_ms"] = int(sys.argv[2])
scripts/log-phase.sh:100:p["wall_ms"] = int(sys.argv[2])
commands/z-implement-next.md:36:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
commands/z-implement-next.md:52:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
commands/z-implement-next.md:90:If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.
agents/codex-consultant.md:104:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult \
agents/codex-consultant.md:105:  "$(printf '{"llm":"codex","mode":"%s","prompt_chars":%d,"response_chars":%d,"wall_ms":%d,"transcript":"%s"}' \
commands/z-amend.md:42:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
commands/z-amend.md:173:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
skills/z-stats/SKILL.md:3:description: Read-only progress + cost report for a z-harness plan. Reads metrics.jsonl + TASKS.md to summarize progress, wall time per phase, estimated token spend per subagent type, recent halts, and suggested next command. No writes, no LLM calls.
skills/z-stats/SKILL.md:17:Set `$BASE = z-harness/$Z_HARNESS_SLUG` (or `z-harness` for legacy). Set `$METRICS = $BASE/metrics.jsonl` (if exists) else `z-harness/metrics.jsonl`.
skills/z-stats/SKILL.md:40:jq -r 'select(.kind | endswith("_end")) | [.kind, (.wall_ms // 0)] | @tsv' "$METRICS" \
skills/z-stats/SKILL.md:53:jq -r 'select(.subagent_model != null) | [.subagent_model, (.subagent_input_tokens // (.prompt_chars // 0)/4), (.subagent_output_tokens // (.response_chars // 0)/4)] | @tsv' "$METRICS" \
skills/z-stats/SKILL.md:107:- **READ ONLY.** Never edit any file. Never write to `metrics.jsonl` or any archive.
commands/z-brainstorm.md:33:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
commands/z-brainstorm.md:48:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
commands/z-brainstorm.md:49:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
commands/z-brainstorm.md:56:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
commands/z-brainstorm.md:58:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
commands/z-brainstorm.md:274:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
commands/z-brainstorm.md:301:- **Log everything** via `scripts/log-event.sh`.
agents/implementer.md:33:This populates `implement_*` rows in `metrics.jsonl` so post-run analysis can compute implementer wall_ms, retry rate, and files-changed distribution.
commands/z-stats.md:2:description: Read-only progress + cost report for a z-harness plan. Reads metrics.jsonl + TASKS.md to summarize progress, wall time per phase, estimated token spend per subagent type, recent halts, and suggested next command. No writes, no LLM calls.
commands/z-stats.md:17:Set `$BASE = z-harness/$Z_HARNESS_SLUG` (or `z-harness` for legacy). Set `$METRICS = $BASE/metrics.jsonl` (if exists) else `z-harness/metrics.jsonl`.
commands/z-stats.md:40:jq -r 'select(.kind | endswith("_end")) | [.kind, (.wall_ms // 0)] | @tsv' "$METRICS" \
commands/z-stats.md:53:jq -r 'select(.subagent_model != null) | [.subagent_model, (.subagent_input_tokens // (.prompt_chars // 0)/4), (.subagent_output_tokens // (.response_chars // 0)/4)] | @tsv' "$METRICS" \
commands/z-stats.md:107:- **READ ONLY.** Never edit any file. Never write to `metrics.jsonl` or any archive.
agents/remote-runner.md:93:  "$(printf '{"id":"%s","exit_code":%d,"build_log_path":"%s","subagent_model":"haiku","prompt_chars":%d,"response_chars":%d}' \
commands/z-debug.md:28:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
commands/z-debug.md:268:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
skills/z-test/SKILL.md:38:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_start "$START_PAYLOAD"
skills/z-test/SKILL.md:206:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_end \
commands/z-do.md:27:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
commands/z-do.md:143:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_end \
commands/z-research.md:36:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
commands/z-research.md:53:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
commands/z-research.md:54:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
commands/z-research.md:61:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
commands/z-research.md:63:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
commands/z-research.md:81:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
commands/z-research.md:105:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
commands/z-research.md:127:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
commands/z-research.md:175:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
commands/z-research.md:209:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
commands/z-research.md:249:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" critique_failure_decision \
commands/z-research.md:328:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
commands/z-research.md:350:- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.
skills/z-init-docs/SKILL.md:21:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_start "$VERSION_BLOB"
skills/z-init-docs/SKILL.md:216:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_end \
skills/z-debug/SKILL.md:28:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
skills/z-debug/SKILL.md:268:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
skills/z-amend/SKILL.md:42:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
skills/z-amend/SKILL.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
skills/z-amend/SKILL.md:173:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
skills/z-implement-all/SKILL.md:28:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" run_start "$START_PAYLOAD"
skills/z-implement-all/SKILL.md:107:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
skills/z-implement-all/SKILL.md:153:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" spec_precheck '{"status":"spec_problem","count":<n>}'
skills/z-implement-all/SKILL.md:165:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
skills/z-implement-all/SKILL.md:320:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_done \
skills/z-implement-all/SKILL.md:350:Every phase of every task track emits a structured event via `scripts/log-event.sh` so we can analyze where wall time goes. The orchestrator (or the subagent) records the **wall clock at phase start**, then logs an event at phase end with `wall_ms`.
skills/z-implement-all/SKILL.md:358:| `precheck_end` | Precheck returned | `id`, `status` (`ok`/`spec_problem`), `references_checked`, `wall_ms` |
skills/z-implement-all/SKILL.md:360:| `implement_end` | Implementer returned | `id`, `retry`, `status`, `files_changed_count`, `wall_ms` |
skills/z-implement-all/SKILL.md:363:| `review_end` | Reviewer returned | `id`, `cycle`, `wall_ms`, `response_chars`, `blockers`, `majors` |
skills/z-implement-all/SKILL.md:365:| `task_done` | Marked `[x]` | `id`, `total_retries`, `review_cycles`, `task_wall_ms` (start→done), `precheck_wall_ms`, `implement_wall_ms_sum`, `review_wall_ms_sum`, `user_wait_ms_sum` |
skills/z-implement-all/SKILL.md:383:For `decision_gate` (halted for user input), bracket the `AskUserQuestion` call with `start` (reason) / `end` (resolution). The helper auto-computes `wall_ms` so you get user-wait time for free.
skills/z-implement-all/SKILL.md:389:| `batch_done` | `tasks_dispatched`, `tasks_done`, `tasks_halted`, `batch_wall_ms`, `parallel_factor` (actual concurrency observed) |
skills/z-implement-all/SKILL.md:399:Repo-wide aggregate stays in `z-harness/metrics.jsonl`. The `scripts/log-event.sh` already appends to both per-run and repo-wide; no orchestrator change needed there.
skills/z-implement-all/SKILL.md:411:**Post-run.** Use `jq` on `$BASE/metrics.jsonl` to flag gaps > 30 min between consecutive events of the same `run`/`id`:
skills/z-implement-all/SKILL.md:414:jq -r '[.ts, .kind, (.id//.run//"")] | @tsv' "$BASE/metrics.jsonl" \
commands/z-implement-all.md:28:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" run_start "$START_PAYLOAD"
commands/z-implement-all.md:107:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
commands/z-implement-all.md:153:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" spec_precheck '{"status":"spec_problem","count":<n>}'
commands/z-implement-all.md:165:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
commands/z-implement-all.md:320:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_done \
commands/z-implement-all.md:350:Every phase of every task track emits a structured event via `scripts/log-event.sh` so we can analyze where wall time goes. The orchestrator (or the subagent) records the **wall clock at phase start**, then logs an event at phase end with `wall_ms`.
commands/z-implement-all.md:358:| `precheck_end` | Precheck returned | `id`, `status` (`ok`/`spec_problem`), `references_checked`, `wall_ms` |
commands/z-implement-all.md:360:| `implement_end` | Implementer returned | `id`, `retry`, `status`, `files_changed_count`, `wall_ms` |
commands/z-implement-all.md:363:| `review_end` | Reviewer returned | `id`, `cycle`, `wall_ms`, `response_chars`, `blockers`, `majors` |
commands/z-implement-all.md:365:| `task_done` | Marked `[x]` | `id`, `total_retries`, `review_cycles`, `task_wall_ms` (start→done), `precheck_wall_ms`, `implement_wall_ms_sum`, `review_wall_ms_sum`, `user_wait_ms_sum` |
commands/z-implement-all.md:383:For `decision_gate` (halted for user input), bracket the `AskUserQuestion` call with `start` (reason) / `end` (resolution). The helper auto-computes `wall_ms` so you get user-wait time for free.
commands/z-implement-all.md:389:| `batch_done` | `tasks_dispatched`, `tasks_done`, `tasks_halted`, `batch_wall_ms`, `parallel_factor` (actual concurrency observed) |
commands/z-implement-all.md:399:Repo-wide aggregate stays in `z-harness/metrics.jsonl`. The `scripts/log-event.sh` already appends to both per-run and repo-wide; no orchestrator change needed there.
commands/z-implement-all.md:411:**Post-run.** Use `jq` on `$BASE/metrics.jsonl` to flag gaps > 30 min between consecutive events of the same `run`/`id`:
commands/z-implement-all.md:414:jq -r '[.ts, .kind, (.id//.run//"")] | @tsv' "$BASE/metrics.jsonl" \
skills/z-plan-light/SKILL.md:30:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
skills/z-plan-light/SKILL.md:208:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_end \
skills/z-brainstorm/SKILL.md:33:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
skills/z-brainstorm/SKILL.md:48:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
skills/z-brainstorm/SKILL.md:49:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
skills/z-brainstorm/SKILL.md:56:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
skills/z-brainstorm/SKILL.md:58:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
skills/z-brainstorm/SKILL.md:274:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
skills/z-brainstorm/SKILL.md:301:- **Log everything** via `scripts/log-event.sh`.
commands/z-improve.md:2:description: Post-run retrospective. Analyzes ONE z-harness run's events.jsonl + artifacts, identifies friction signals (slow phases, retries, doc drift, blocked askings, reviewer cycles), and opens a discussion with the user about concrete edits to the z-harness repo itself (commands, agents, scripts). Optional cross-LLM consult on proposed changes. Discussion logged to z-harness/improvements/. Opt-in; never auto-fired.
commands/z-improve.md:24:- `$EVENTS = $RUN_DIR/events.jsonl`
commands/z-improve.md:38:- `$EVENTS` — events.jsonl. Parse with `python3 -c 'import json; [print(json.loads(l)) for l in open(sys.argv[1])]'` or jq.
commands/z-improve.md:56:| Slow phase | `max(phase_end.wall_ms) - min(phase_end.wall_ms)` outliers; phases taking >2x median | any phase taking >5 min, or >3x the run's median |
commands/z-improve.md:57:| User-wait dominance | `sum(user_wait_end.wall_ms) / total run wall` | >40% — suggests too many `AskUserQuestion` blocks |
commands/z-improve.md:167:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN-improve" improve_run_end \
skills/z-improve/SKILL.md:2:description: Post-run retrospective. Analyzes ONE z-harness run's events.jsonl + artifacts, identifies friction signals (slow phases, retries, doc drift, blocked askings, reviewer cycles), and opens a discussion with the user about concrete edits to the z-harness repo itself (commands, agents, scripts). Optional cross-LLM consult on proposed changes. Discussion logged to z-harness/improvements/. Opt-in; never auto-fired.
skills/z-improve/SKILL.md:24:- `$EVENTS = $RUN_DIR/events.jsonl`
skills/z-improve/SKILL.md:38:- `$EVENTS` — events.jsonl. Parse with `python3 -c 'import json; [print(json.loads(l)) for l in open(sys.argv[1])]'` or jq.
skills/z-improve/SKILL.md:56:| Slow phase | `max(phase_end.wall_ms) - min(phase_end.wall_ms)` outliers; phases taking >2x median | any phase taking >5 min, or >3x the run's median |
skills/z-improve/SKILL.md:57:| User-wait dominance | `sum(user_wait_end.wall_ms) / total run wall` | >40% — suggests too many `AskUserQuestion` blocks |
skills/z-improve/SKILL.md:167:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN-improve" improve_run_end \
skills/z-research/SKILL.md:36:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
skills/z-research/SKILL.md:53:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
skills/z-research/SKILL.md:54:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
skills/z-research/SKILL.md:61:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
skills/z-research/SKILL.md:63:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
skills/z-research/SKILL.md:81:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
skills/z-research/SKILL.md:105:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
skills/z-research/SKILL.md:127:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
skills/z-research/SKILL.md:175:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
skills/z-research/SKILL.md:209:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
skills/z-research/SKILL.md:249:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" critique_failure_decision \
skills/z-research/SKILL.md:328:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_end \
skills/z-research/SKILL.md:350:- **Log everything.** Every Explore dispatch, consultant call, temptation, and demotion — via `scripts/log-event.sh`.
commands/z-test.md:38:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_start "$START_PAYLOAD"
commands/z-test.md:206:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_end \
commands/z-maintain-docs.md:19:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_start \
commands/z-maintain-docs.md:32:- Concepts referenced by any `task_done` event in `z-harness/*/metrics.jsonl` since the concept's `last_updated` (recent plans touched these).
commands/z-maintain-docs.md:135:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_end \
commands/z-init-docs.md:21:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_start "$VERSION_BLOB"
commands/z-init-docs.md:216:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_end \
skills/z-do/SKILL.md:27:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
skills/z-do/SKILL.md:143:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_end \
commands/z-plan-light.md:30:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
commands/z-plan-light.md:208:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_end \
commands/z-plan.md:33:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
commands/z-plan.md:35:   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
commands/z-plan.md:56:Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.
commands/z-plan.md:66:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
commands/z-plan.md:67:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
commands/z-plan.md:74:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
commands/z-plan.md:76:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
commands/z-plan.md:79:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
commands/z-plan.md:130:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
commands/z-plan.md:278:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
commands/z-plan.md:310:- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.
skills/z-maintain-docs/SKILL.md:19:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_start \
skills/z-maintain-docs/SKILL.md:32:- Concepts referenced by any `task_done` event in `z-harness/*/metrics.jsonl` since the concept's `last_updated` (recent plans touched these).
skills/z-maintain-docs/SKILL.md:135:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_end \
commands/z-audit.md:30:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_start "$START_PAYLOAD"
commands/z-audit.md:228:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_end \
skills/z-implement-next/SKILL.md:36:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
skills/z-implement-next/SKILL.md:52:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
skills/z-implement-next/SKILL.md:90:If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.
skills/z-plan/SKILL.md:33:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
skills/z-plan/SKILL.md:35:   Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
skills/z-plan/SKILL.md:56:Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.
skills/z-plan/SKILL.md:66:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
skills/z-plan/SKILL.md:67:  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
skills/z-plan/SKILL.md:74:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
skills/z-plan/SKILL.md:76:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
skills/z-plan/SKILL.md:79:This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.
skills/z-plan/SKILL.md:130:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
skills/z-plan/SKILL.md:278:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
skills/z-plan/SKILL.md:310:- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.

exec
/bin/zsh -lc "ls agents commands skills | sed -n '1,200p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
agents:
auditor.md
codex-consultant.md
codex-reviewer.md
complexity-classifier.md
doc-fetcher.md
doc-updater.md
gemini-consultant.md
implementer.md
remote-runner.md
spec-precheck.md

commands:
z-amend.md
z-audit.md
z-brainstorm.md
z-debug.md
z-do.md
z-implement-all.md
z-implement-next.md
z-improve.md
z-init-docs.md
z-maintain-docs.md
z-plan-light.md
z-plan.md
z-research.md
z-review-all.md
z-skill-fix.md
z-stats.md
z-test.md

skills:
z-amend
z-brainstorm
z-debug
z-do
z-implement-all
z-implement-next
z-improve
z-init-docs
z-maintain-docs
z-plan
z-plan-light
z-research
z-review-all
z-stats
z-test

exec
/bin/zsh -lc "sed -n '110,180p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
  subagent_type="codex-consultant",
  description="Codex ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="gemini-consultant",
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

4. **Write `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md`** with YAML frontmatter:

exec
/bin/zsh -lc "find . -maxdepth 3 -iname '*ideator*' -o -path './agents/*' -type f" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./agents/auditor.md
./agents/doc-updater.md
./agents/remote-runner.md
./agents/codex-consultant.md
./agents/spec-precheck.md
./agents/doc-fetcher.md
./agents/codex-reviewer.md
./agents/complexity-classifier.md
./agents/implementer.md
./agents/gemini-consultant.md

exec
/bin/zsh -lc "sed -n '30,70p' README.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
- **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task `codex-reviewer` safety gate → retry once on review failure → push-notify at every task boundary.
- **`/z-implement-next`** — Same loop, one task at a time.

### Audit, debug, review

- **`/z-audit <target>`** — Read-only audit pipeline. Pre-flight scopes (target, dimensions, optional `.claude/audit-rubrics/<component>.md`), spawns one `auditor` subagent per dimension in parallel (correctness / perf / cleanliness / design), bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md in `/z-implement-all`-compatible format, codex-reviewer safety gate.
- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem.
- **`/z-review-all`** — Final-gate cross-LLM review of a completed plan's cumulative diff against SPEC.md — catches implementation drift and aggregate-only spec gaps.
- **`/z-skill-fix <skill>`** — Meta-command. Patches any `.claude/skills/*/SKILL.md` (or `commands/*.md` / `agents/*.md` inside z-harness itself). Inline diagnosis → surgical edit → codex-reviewer safety gate.

### Docs

- **`/z-init-docs`** — Bootstrap two-tier docs (`docs/human/` markdown + `docs/llm/INDEX.json` token-compacted) so `/z-plan` Phase 1 has a fast-lookup oracle.
- **`/z-maintain-docs`** — Refresh stale concepts whose source files changed since each doc's `last_updated`. Dry-run preview by default.

### Telemetry

- **`/z-stats`** — Read-only progress + cost report from `metrics.jsonl` and TASKS.md. No writes, no LLM calls.

### Subagents (invoked by commands; you don't call them directly)

| Agent | Model | Role |
|---|---|---|
| `implementer` | sonnet | Implements one task in fresh context |
| `auditor` | sonnet | Audits one dimension, returns structured findings |
| `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
| `codex-consultant` | (CLI) | Cross-LLM consult via Codex |
| `codex-reviewer` | haiku | Post-diff safety gate via Codex |
| `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
| `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
| `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries, paper qtctl restarts |
| `ideator` | sonnet | Claude-side ideator in `/z-brainstorm` Phase 2 (one of three parallel ideators) |

## Operating principles

- Push back by default — on Gemini, Codex, and the user.
- Always ask when unclear. No silent assumptions.
- No shortcuts without explicit user approval.
- DRY / KISS / SOLID are non-negotiable in the final plan.

## Requirements

exec
/bin/zsh -lc "sed -n '40,55p' commands/z-plan.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,90p' commands/z-research.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,70p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `z-harness/$Z_HARNESS_SLUG/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — archive existing `BRAINSTORM.md` to `z-harness/$Z_HARNESS_SLUG/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
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


 succeeded in 0ms:
---
description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
argument-hint: <question or technical area to research>
---

You are running the **z-harness `/z-research`** pipeline.

Question (from `$ARGUMENTS`):

$ARGUMENTS

**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.

Strict, multi-phase. Do not skip phases. `/z-research` produces a research note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.

**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.

## Setup

1. **Parse `--slug=<value>` flag** from `$ARGUMENTS` first. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the research question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned research question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.

   If `--slug=` was explicitly provided, skip auto-derivation but still defer collision handling to Phase 0.5.
2. **Export** `Z_HARNESS_SLUG=<slug>` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
   ```
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.

**Setup does NOT mutate `z-harness/<slug>/RESEARCH.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.

**All paths in subsequent phases live under `z-harness/<slug>/`:**
- `z-harness/<slug>/RESEARCH.md`
- `z-harness/<slug>/archive/<run-id>/...`

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


codex
- **Major** — `README.md:58`: The new `ideator` subagent row documents an agent that does not exist; `/z-brainstorm` uses `subagent_type="general-purpose"` for the Claude ideator, and there is no `agents/ideator.md`. Suggested fix: remove the row, or reword it as “Claude ideator uses general-purpose Sonnet” outside the “Subagents” table.

- **Major** — `README.md:128`: “Standard per-event fields: `prompt_chars`, `response_chars`, `wall_ms`” is false for several newly documented events, including run starts, `cost_gate_decision`, `ideator_failed`, and freshness failures. Suggested fix: document only guaranteed fields as `ts`, `run`, `kind`, optional `slug`, plus event-specific payload fields; describe `prompt_chars`/`response_chars`/`wall_ms` as optional when applicable.
2026-05-22T17:03:23.628466Z ERROR codex_core::session: failed to record rollout items: thread 019e50a3-81da-7ed2-a24d-9718c13901e8 not found
tokens used
76,053
- **Major** — `README.md:58`: The new `ideator` subagent row documents an agent that does not exist; `/z-brainstorm` uses `subagent_type="general-purpose"` for the Claude ideator, and there is no `agents/ideator.md`. Suggested fix: remove the row, or reword it as “Claude ideator uses general-purpose Sonnet” outside the “Subagents” table.

- **Major** — `README.md:128`: “Standard per-event fields: `prompt_chars`, `response_chars`, `wall_ms`” is false for several newly documented events, including run starts, `cost_gate_decision`, `ideator_failed`, and freshness failures. Suggested fix: document only guaranteed fields as `ts`, `run`, `kind`, optional `slug`, plus event-specific payload fields; describe `prompt_chars`/`response_chars`/`wall_ms` as optional when applicable.