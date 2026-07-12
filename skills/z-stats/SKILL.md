---
name: z-stats
description: Read-only progress, timing, cost, and active-plan-registry report for z-harness plans and runs. With no arguments it also reports registry-wide active-plan state (absorbs the former /z-where command). Every computed section shells out to scripts/stats.py — no inline jq/awk. No writes, no subagent dispatch, no LLM calls.
argument-hint: "[--slug <slug>]"
audience: user
driver_features_required: [ask_user]
---

You are running **z-harness `/z-stats`** — a read-only check-in report. Target: ≤2s wall time.

This is a diagnostic, not a fix. If the report surfaces a real problem (a
stuck task, a repeated halt), route to `/z-fix` or `/z-debug` rather than
editing anything here — `/z-stats` never writes.

## Phase 1 — Registry-wide header (always; no slug needed)

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" header
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" active-plans \
  ${Z_HARNESS_RUN_ID:+--run-id "$Z_HARNESS_RUN_ID"}
```

This is the former `/z-where` command's whole body (resolved base/repo-id,
the active-plan table, and the path-overlap section) — it never needs a
slug, so it always runs first, even when Phase 2 below finds no local plan.

## Phase 2 — Slug discovery

Same as `/z-execute` Phase 0:
1. Enumerate `$Z_HARNESS_PLAN_DIR/` subdirs with TASKS.md; check legacy flat layout.
2. If `--slug <slug>` present → use it.
3. If one candidate → use it.
<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
4. Multiple → `AskUserQuestion` to pick.
5. Zero → print "No local plan found — showing registry state only." and
   **stop here.** Phase 1's output already covers the no-args case; there is
   nothing to preflight or register against.

## Setup — preflight (only reached once a slug resolved)

```bash
PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
  --command /z-stats --slug "$SLUG" --no-claim)"
PREFLIGHT_RC=$?; [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
```

Read-only command: `--no-claim` (registers for watcher visibility, never
contends). On a nonzero exit follow the standard preflight menus documented
in the script header.

Set `$METRICS = $Z_HARNESS_PLAN_DIR/metrics.jsonl` (if it exists) else the
legacy `z-harness/metrics.jsonl`.

## Phase 3 — Progress

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" progress "$Z_HARNESS_PLAN_DIR" "$SLUG"
```

## Phase 4 — Wall time per phase

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" walltime "$METRICS"
```

Tells you whether implementer, review, or user-wait dominates.

## Phase 5 — Token spend by subagent

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" tokens "$METRICS"
```

Verifies the haiku/sonnet/opus split matches what `[model_routing]` should
be producing.

## Phase 6 — Per-host, per-subagent cost breakdown

This already delegates to `scripts/estimate-tokens.py subagent-costs` — the
existing read-side cost model (input/output weighted, output ~5x input per
D9), never inline jq/awk — so it is unchanged by this rewrite:

```bash
ZH_REPO_BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir 2>/dev/null)"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/estimate-tokens.py" \
  subagent-costs ${ZH_REPO_BASE:+--metrics "$ZH_REPO_BASE/metrics.jsonl"}
```

**Honest limitation:** native Claude `Agent()` calls don't expose real token
counts — only dispatch-prompt and returned-text sizes are observable — so
rows are labeled `[char-est]`, or `[real tokens]`/`[mixed: provider+chars]`
when at least one event carries real provider counts. If the command's
output is empty, print `Subagent cost breakdown: (no subagent_call events in
metrics)`.

## Phase 7 — Coordination event tallies

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" coordination "$METRICS"
```

All seven kinds always show, `0` for absent ones — a truly quiet run should
be visually indistinguishable from nothing-happened only by the zeros, never
by a missing line. `wait_timeout` nonzero is LOUD — investigate.
`coordination_warning` is the write-set-validation backstop (F5).

## Phase 8 — Recent halts

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" halts "$METRICS"
```

Last 10 `task_halt`/`decision_gate`/`task_security_warn`/
`review_agent_failed`/`review_agent_malformed` events, most-recent last.

## Phase 9 — Suggested next command

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/stats.py" next-command "$Z_HARNESS_PLAN_DIR" "$METRICS"
```

The subcommand's lookup mechanically covers every TASKS.md-driven state (no
plan, halts pending, all-done-review-not-run, all-done-review-accepted,
pending tasks, fresh-with/without-TESTS.md) plus the light-mode FIX.md
"Docs touched" case. One case it deliberately does NOT cover: a debug plan
(`DEBUG.md`) whose `## Post-mortem` section lists action items not yet
converted to tasks — deciding whether an item is "not yet tasked" means
reading free-form prose, not a table lookup. If `$Z_HARNESS_PLAN_DIR/DEBUG.md`
exists with un-linked post-mortem action items, say so and recommend
converting them via `/z-amend` — the one place in this command where you
apply judgment instead of the script's answer verbatim.

## Finalize

Set run-brief `outcome` (one sentence, e.g. "3/5 tasks done, no halts") and
`next` (the Phase 9 suggestion), then:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-stats --status complete
```

## Output format

Single concise report, ~30-50 lines total. Section headers, no prose
filler — the user runs this to check in, not to read documentation.

## Hard rules

- **READ ONLY.** Never edit any file. `/z-stats` itself never appends to
  `metrics.jsonl` — reading it is the whole point; self-logging would
  pollute the very log being read.
- **No subagent dispatch, no LLM calls.** Only `scripts/stats.py` and
  `scripts/estimate-tokens.py` against existing files.
- Phase 1 is unconditional — it never gates behind slug resolution
  succeeding.
