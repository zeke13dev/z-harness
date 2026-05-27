# Phase 1 — Exploration context

## Skip evaluation
RESEARCH.md absent. BRAINSTORM.md present and exhaustive. Per RESEARCH.md shortcut rules → ran doc-fetcher (case d minus RESEARCH.md). Skipped Explore — doc-fetcher synthesis covered all the file:line references the scope-probe integration needs.

## Key findings from doc-fetcher (synthesis)

### Agent definition format
- Frontmatter: `name` (matches `subagent_type=`), `description` (1-2 sentence purpose + model tier), `tools` (CSV: `Read, Grep, Glob` for read-only Haiku; add `Bash` for ripgrep), `model` (`haiku|sonnet|opus`).
- Pattern reference for `scope-probe`: matches `planning-router` + `doc-fetcher` mold — Haiku, read-only, parseable output contract.

### Existing Phase 0 / pre-dispatch shapes
- **`/z-audit`** (commands/z-audit.md:1–50): no formal Phase 0; `$ARGUMENTS` injected; Setup → Phase 1 (Pre-flight scoping) collects dimensions via AskUserQuestion. Scope-probe inserts **between Setup and Phase 1's dimension selection**.
- **`/z-brainstorm`** (commands/z-brainstorm.md:1–80): Setup → Plan Route Check (lines 42–60) → Phase 1 scaffolding → Phase 2 ideator dispatch. Scope-probe inserts **after Plan Route Check, before Phase 1 scaffolding**.

### Planning-router output contract (precedent for scope-probe contract)
```
STATUS: routed | ask_user | bad_input
RECOMMENDED: <command-or-action>
ROUTE_CLASS: primary | contextual | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated stable codes>
REASON: <one line, <=160 chars>
```
Adaptation for scope-probe: replace `RECOMMENDED` semantics with `MODE: LIGHT|MEDIUM|HEAVY` + `AXIS: <name>` + structured chunks.

### Archive structure (calibration harness replay target)
- `z-harness/<slug>/archive/<RUN>/events.jsonl` — append-only NDJSON event log.
- `z-harness/<slug>/archive/<RUN>/manifest.json` — final summary: `slug`, `run`, `status`, `tasks_total`, `tasks_complexity {low/medium/high}`, `decisions_total`, `decisions_consulted`, `consultations`, `framing`, `depends_on`.
- Phase checkpoints (`phaseN-*.md`) preserve intermediate state.
- `transcripts/` holds subagent prompt+return pairs.
- For calibration: replay scope-probe against the BRAINSTORM/RESEARCH/topic of each historical run, then compare its `MODE` classification against what that run actually did mid-flight (file count, decision count, task count, escalation events).

### Telemetry conventions
- `scripts/log-event.sh <RUN> <kind> <json-payload>` writes to `events.jsonl` and `metrics.jsonl`.
- Existing event kinds for scope-related decisions: `plan_route_decision`, `doc_drift`, `escalation_*`. New scope-probe events should follow: `scope_probe_start`, `scope_probe_end`, `scope_probe_classified` with `{mode, axis, chunk_count, confidence}`.

### Reusable infra to lean on
- `scripts/log-event.sh` — telemetry.
- `scripts/version.sh` — version stamp.
- `scripts/plan-path.sh` — `resolve_plan_path <slug>`.
- `doc-fetcher` agent — scope-probe will call it as part of axis discovery (step 4 of the 5-step protocol).
- `complexity-classifier` agent — structurally identical pattern (Haiku, takes structured input, emits `TIER:` line) — use as the structural template.

### Constraints / gotchas to plan around
- Scope-probe runs BEFORE doc-fetcher in the typical Phase 1 ordering, BUT the 5-step axis-discovery protocol itself calls doc-fetcher (step 4). Sequence: scope-probe-step-1 → ... → scope-probe-step-4 dispatches doc-fetcher → scope-probe emits manifest → host command Phase 1 begins.
- Haiku context budget: scope-probe must NOT do heavy filesystem walks. Cap directory traversal at 2 levels deep × N candidate entities (where N ≤ 4) per the BRAINSTORM protocol.
- No per-call wall-clock timeout for Agent dispatches in v1 (see review-agent v1 limitations) — same applies here.
- Cross-host clock skew: existing INDEX.json staleness uses date-only comparison. Calibration harness must tolerate timestamp skew when comparing replay events to original `events.jsonl`.

## Context summary

To integrate scope-probe as Phase 0 of `/z-audit` and `/z-brainstorm`, we need: a new `agents/scope-probe.md` (frontmatter + 5-step protocol + parseable output contract patterned after planning-router), a SCOPE.json schema written by the host command after parsing scope-probe's return, a calibration harness Python script that replays scope-probe against historical archive runs and computes classification accuracy against actual mid-flight routing decisions, and surgical edits to `commands/z-audit.md` (insert Phase 0 between Setup and dimension selection) and `commands/z-brainstorm.md` (insert Phase 0 after Plan Route Check). v1a is read-only against existing escalation infra — the deletions are explicitly deferred to v1b.
