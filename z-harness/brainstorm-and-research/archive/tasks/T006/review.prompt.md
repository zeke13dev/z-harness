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
