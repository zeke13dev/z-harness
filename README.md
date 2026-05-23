# z-harness

A Claude Code plugin that wraps planning and implementation in a rigorous, cross-LLM-reviewed pipeline.

## What it does

Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.

### Pre-planning (optional; feed into `/z-plan`)

- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators (Claude Sonnet + Codex + Gemini). Produces `BRAINSTORM.md` in `z-harness/<slug>/`. Cost target: ≤200K tokens. Use this when the framing or approach for a problem is still open and you want divergent perspectives before locking in a plan.
- **`/z-research <question>`** — Heavier terrain mapping via parallel Explores + cross-LLM critique. Produces `RESEARCH.md` in `z-harness/<slug>/`. Cost target: ≤2M tokens. Use this when you need concrete file:line evidence about an existing codebase or design space before deciding what to build.

**Typical chains:**

- Murky problem: `/z-research → /z-brainstorm → /z-plan` — research terrain first, generate framed approaches, then plan.
- Lighter case: `/z-brainstorm → /z-plan` — skip research when the codebase is already well understood.
- Standard: `/z-plan` alone — when the problem and approach are already clear.

`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.

### Planning

- **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
- **`/z-plan-light <fix>`** — Fast path for 1-5 file fixes; auto-bails to `/z-plan` if scope grows. Single `FIX.md` artifact, inline implementation, codex-reviewer safety gate kept.
- **`/z-plan-split <topic>`** — Pre-emptive scope splitter for sprawling topics that would otherwise yield a ≥40-task `/z-plan` run across natural seams. Proposes 2-6 narrow clusters, dispatches one `cluster-planner` subagent per cluster in parallel, then reconciles file-path overlaps into `SHARED-CONCERNS.md` + `MANIFEST.md` under `z-harness/<root-slug>/`. One-level recursion only; no production code. Cost target: cheaper than a single mega-`/z-plan` only when the user genuinely needed N narrow plans — otherwise more expensive (opt-in, do not use as a default).

  Typical chain for a murky multi-component problem: `/z-research → /z-brainstorm → /z-plan-split → /z-implement-all`.
- **`/z-test`** — Semantic test-case planner. Reads SPEC/PLAN/TASKS, drafts non-trivial tests (sign errors, schema mismatches, off-by-one, unit confusion), cross-consults Gemini+Codex, writes `TESTS.md`. The implementer reads TESTS.md alongside TASKS.md so tests land in the same diff as production code.

### Implementation

- **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task `codex-reviewer` safety gate → retry once on review failure → push-notify at every task boundary. Walks a tree-rooted plan produced by `/z-plan-split` (one cluster at a time, in MANIFEST run order) as well as legacy single-slug plans. Flags: `--ack` (override the SHARED-CONCERNS.md ack-gate) and `--force-partial` (proceed against a tree where some clusters failed planning, excluding the failed ones from the run set). Both flags are inert for legacy single-slug plans.
- **`/z-implement-next`** — Same loop, one task at a time.

### Audit, debug, review

- **`/z-audit <target>`** — Read-only audit pipeline. Pre-flight scopes (target, dimensions, optional `.claude/audit-rubrics/<component>.md`), spawns one `auditor` subagent per dimension in parallel (correctness / perf / cleanliness / design), bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md in `/z-implement-all`-compatible format, codex-reviewer safety gate.
- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem.
- **`/z-review-all`** — Final-gate cross-LLM review of a completed plan's cumulative diff against SPEC.md — catches implementation drift and aggregate-only spec gaps.
- **`/z-skill-fix <skill>`** — Meta-command. Patches any `.claude/skills/*/SKILL.md` (or `commands/*.md` / `agents/*.md` inside z-harness itself). Inline diagnosis → surgical edit → codex-reviewer safety gate.

### Docs

- **`/z-init-docs`** — Bootstrap two-tier docs (`docs/human/` markdown + `docs/llm/INDEX.json` token-compacted) so `/z-plan` Phase 1 has a fast-lookup oracle.
- **`/z-maintain-docs`** — Refresh stale concepts whose source files changed since each doc's `last_updated`. Dry-run preview by default.
- **`/z-suggest-memory`** — Author a dated, provenance-bearing memory entry into a concept's `docs/llm/<slug>.json` `memories[]` array and rebuild `MEMORIES-FLAT.md`. The only memory-mutating path — `/z-debug` and `/z-improve` retros call this mandatorily.

### Telemetry

- **`/z-stats`** — Read-only progress + cost report from `metrics.jsonl` and TASKS.md. No writes, no LLM calls.

### Subagents (invoked by commands; you don't call them directly)

| Agent | Model | Role |
|---|---|---|
| `implementer` | sonnet | Implements one task in fresh context |
| `auditor` | sonnet | Audits one dimension, returns structured findings |
| `cluster-planner` | sonnet | Runs a narrow sub-/z-plan for one cluster of a `/z-plan-split` tree |
| `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
| `codex-consultant` | (CLI) | Cross-LLM consult via Codex |
| `codex-reviewer` | haiku | Post-diff safety gate via Codex |
| `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
| `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
| `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries, paper qtctl restarts |

`/z-brainstorm` dispatches three ideators in Phase 2: Claude as `general-purpose` Sonnet, Codex via `codex-consultant` with `MODE: brainstorm`, and Gemini via `gemini-consultant` with `MODE: brainstorm`. There is no dedicated `ideator` agent file.

## Operating principles

- Push back by default — on Gemini, Codex, and the user.
- Always ask when unclear. No silent assumptions.
- No shortcuts without explicit user approval.
- DRY / KISS / SOLID are non-negotiable in the final plan.

## Requirements

- `codex` CLI installed and authenticated (uses the Codex/ChatGPT app endpoint, *not* the OpenAI API endpoint).
- `gemini` CLI installed and authenticated.
- Claude Code with `PushNotification` available (for mobile notifications).

## Install

From any Claude Code session:

```
/plugin marketplace add /Users/zeke/dev/z-harness
/plugin install z-harness@zeke-tools
```

Or, for git distribution:

```
/plugin marketplace add <github-org>/z-harness
/plugin install z-harness@zeke-tools
```

## Per-repo auto-enable

In each project where you want z-harness on automatically, commit `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "zeke-tools": { "source": { "source": "github", "repo": "<org>/z-harness" } }
  },
  "enabledPlugins": { "z-harness@zeke-tools": true }
}
```

## Plugin-author conventions (for downstream `.claude/skills/`)

When a downstream repo defines its own skills that interoperate with z-harness, follow these conventions so they cooperate with the harness rather than fight it:

- End each skill file with `## Anti-patterns (push back)` and `## Out of scope` sections — they're the cheapest place to encode failure modes and handoff boundaries.
- Skills that diagnose should NOT also apply patches. Hand off to `/z-plan-light` (small fix) or `/z-plan` (structural) for any code change beyond initial scaffolding.
- Skills that orchestrate should call cross-LLM consult (`gemini-consultant`, `codex-consultant`) at premise / red-team gates, not run them inline.
- Use explicit slash commands instead of flag-routed `mode:` parameters — one skill per mode (`/qt-audit-strategy`, not `/qt-audit mode=strategy`).
- Domain-specific audit checklists live under `.claude/audit-rubrics/<component>.md` and are consumed by `/z-audit` via its rubric-file slot — keep them as plain checklists, not scaffolding.

## Environment knobs

- `Z_HARNESS_NOTIFY` — `off` | `approval_only` (default) | `all`. Controls push notifications.
- `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
- `Z_HARNESS_MAX_EXPLORE` — default `3`. Cap on `Explore` subagent dispatches per `/z-plan` run.
- `Z_HARNESS_DOC_STALENESS_THRESHOLD` — default `20` (percent). Above this, `/z-plan` halts and recommends `/z-maintain-docs` first.
- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
- `Z_HARNESS_LOCAL_CARGO_CLEAN` — set to `1` at the start of `/z-implement-all` to trigger a one-time local `cargo clean`.
- `Z_HARNESS_SLUG` — set by commands; namespaces all output paths under `z-harness/<slug>/`.
- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.

## Telemetry event types

All events are appended to `z-harness/metrics.jsonl` via `scripts/log-event.sh`. Standard fields present on every event: `ts`, `run`, `kind` (and `slug` when set). The fields `prompt_chars`, `response_chars`, and `wall_ms` are optional — they appear only on subagent-bracket events, not on lifecycle or gate events.

Event kinds introduced by `/z-brainstorm` and `/z-research`:

| Event | Emitted by |
|---|---|
| `brainstorm_run_start` | `/z-brainstorm` setup |
| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
| `research_run_start` | `/z-research` setup |
| `research_run_end` | `/z-research` Phase 6 |
| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
| `research_temptation` | `/z-research` when orchestrator drafts a recommendation it must not make |
| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate |
| `explore_failure` | any command that dispatches an Explore subagent that does not return |

Event kinds introduced by `/z-plan-split` and the tree-walking branch of `/z-implement-all`:

| Event | Emitted by |
|---|---|
| `plan_split_run_start` | `/z-plan-split` Setup |
| `plan_split_run_end` | `/z-plan-split` finalize (every exit path; `status` distinguishes the exit reason) |
| `cluster_proposed` | `/z-plan-split` Phase 1c (per proposed cluster) |
| `cluster_confirmed` | `/z-plan-split` Phase 1e (per confirmed cluster) |
| `cluster_planner_start` | `cluster-planner` subagent, first call |
| `cluster_planner_end` | `cluster-planner` subagent, last call (every exit path) |
| `cluster_failed` | `/z-plan-split` Phase 3 (per failed cluster; `failure_reason` distinguishes the cause) |
| `cluster_decision_escalated` | `cluster-planner` Phase 2/3 when the conservative-flagging rubric escalates |
| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
| `shared_concerns_missing` | `/z-implement-all` Setup 2b when SHARED-CONCERNS.md is absent on a tree-rooted slug |
| `shared_concerns_unacknowledged` | `/z-implement-all` Setup 2b ack-gate (halt; no override) |
| `shared_concerns_ack_override` | `/z-implement-all` Setup 2b ack-gate when `--ack` was supplied |
| `manifest_frontmatter_inconsistent` | `/z-implement-all` Setup 2b when frontmatter counts disagree with the table |
| `manifest_run_order_invalid` | `/z-implement-all` Setup 2b when run order doesn't bijectively match the table |
| `tree_depth_exceeded` | `/z-implement-all` Setup 2b when a nested MANIFEST.md is found inside the tree |
| `partial_tree_blocked` | `/z-implement-all` Setup 2b partial-tree gate (halt; no `--force-partial`) |
| `partial_tree_force_override` | `/z-implement-all` Setup 2b partial-tree gate when `--force-partial` was supplied |
| `anti_nesting_violation` | `cluster-planner` Phase 0a when an ancestor MANIFEST.md is detected |
| `cluster_not_ready` | `/z-implement-all` Setup 2b cluster-readiness gate |

## Known v1 limitations

- **No per-subagent wall-clock timeout.** `Agent()` does not expose a per-call timeout; subagents that hang block the entire run. User-facing escape: ctrl-c to abort.
- **No doc-fetcher caching across precontext and plan runs.** If you run `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched twice (once per command). Marked as a v2 candidate; the cost is low enough today.
- **`/z-plan-split`: no cross-cluster task parallelism.** `/z-implement-all` walks clusters sequentially in MANIFEST run-order; intra-cluster parallelism (N=3) is honored, cross-cluster is v2.
- **`/z-plan-split`: path-only overlap detection.** SHARED-CONCERNS.md is built from file-path intersections across cluster TASKS.md `**Files:**` lines. No semantic overlap detection (two clusters that touch disjoint files but conflict on the same in-memory invariant will not surface here).
- **`/z-plan-split`: no `--from-audit` / `--from-brainstorm` input chains.** The topic is taken verbatim from `$ARGUMENTS`; there is no structured handoff from `/z-audit`, `/z-research`, or `/z-brainstorm` artifacts beyond what the user pastes into the topic string. v2 candidate.
- **`/z-plan-split`: one-level recursion cap.** Cluster-planners refuse to write inside an existing MANIFEST.md tree, and `/z-implement-all` halts with `tree_depth_exceeded` if it finds a nested MANIFEST.md. A tree-of-trees is structurally unsupported.

## Layout

```
z-harness/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── commands/
│   ├── z-brainstorm.md
│   ├── z-research.md
│   ├── z-plan.md
│   ├── z-plan-light.md
│   ├── z-plan-split.md
│   ├── z-test.md
│   ├── z-implement-all.md
│   ├── z-implement-next.md
│   ├── z-audit.md
│   ├── z-debug.md
│   ├── z-review-all.md
│   ├── z-skill-fix.md
│   ├── z-init-docs.md
│   ├── z-maintain-docs.md
│   ├── z-suggest-memory.md
│   └── z-stats.md
├── agents/
│   ├── implementer.md
│   ├── auditor.md
│   ├── cluster-planner.md
│   ├── codex-reviewer.md
│   ├── codex-consultant.md
│   ├── gemini-consultant.md
│   ├── spec-precheck.md
│   ├── doc-updater.md
│   └── remote-runner.md
├── scripts/
│   ├── log-event.sh
│   ├── log-phase.sh
│   ├── remote-sandbox-sync.sh
│   └── version.sh
└── README.md
```
