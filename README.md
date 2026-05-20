# z-harness

A Claude Code plugin that wraps planning and implementation in a rigorous, cross-LLM-reviewed pipeline.

## What it does

Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.

### Planning

- **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
- **`/z-plan-light <fix>`** — Fast path for 1-5 file fixes; auto-bails to `/z-plan` if scope grows. Single `FIX.md` artifact, inline implementation, codex-reviewer safety gate kept.
- **`/z-test`** — Semantic test-case planner. Reads SPEC/PLAN/TASKS, drafts non-trivial tests (sign errors, schema mismatches, off-by-one, unit confusion), cross-consults Gemini+Codex, writes `TESTS.md`. The implementer reads TESTS.md alongside TASKS.md so tests land in the same diff as production code.

### Implementation

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
- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
- `Z_HARNESS_LOCAL_CARGO_CLEAN` — set to `1` at the start of `/z-implement-all` to trigger a one-time local `cargo clean`.
- `Z_HARNESS_SLUG` — set by commands; namespaces all output paths under `z-harness/<slug>/`.

## Layout

```
z-harness/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── commands/
│   ├── z-plan.md
│   ├── z-plan-light.md
│   ├── z-test.md
│   ├── z-implement-all.md
│   ├── z-implement-next.md
│   ├── z-audit.md
│   ├── z-debug.md
│   ├── z-review-all.md
│   ├── z-skill-fix.md
│   ├── z-init-docs.md
│   ├── z-maintain-docs.md
│   └── z-stats.md
├── agents/
│   ├── implementer.md
│   ├── auditor.md
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
