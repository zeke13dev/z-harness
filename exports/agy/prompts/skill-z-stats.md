---
description: Read-only progress + cost report for a z-harness plan. Reads metrics.jsonl + TASKS.md to summarize progress, wall time per phase, estimated token spend per subagent type, recent halts, and suggested next command. No writes, no LLM calls.
role: skill
---

You are running **z-harness `/z-stats`**. Read-only diagnostic. Cheap — uses only Bash/jq/awk on the existing event log; no subagent dispatch.

## Phase 0 — Slug discovery

Same as `/z-implement-all` Phase 0:
1. Enumerate `$Z_HARNESS_PLAN_DIR/` subdirs with TASKS.md; check legacy flat layout.
2. If `--slug <slug>` arg present → use it.
3. If one candidate → use it.
4. Multiple → `AskUserQuestion` to pick.
5. Zero → tell user "no plan found"; abort.

Set `$BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy). Set `$METRICS = $BASE/metrics.jsonl` (if exists) else `z-harness/metrics.jsonl`.

## Phase 1 — Plan progress

Parse `$BASE/TASKS.md`:

```bash
grep -cE '^### \[x\]' "$BASE/TASKS.md"   # done
grep -cE '^### \[~\]' "$BASE/TASKS.md"   # in_progress
grep -cE '^### \[ \]' "$BASE/TASKS.md"   # pending
grep -cE '\*\*SKIP:'  "$BASE/TASKS.md"   # skip-flagged
```

Display as a single-line summary:

```
Plan: <slug>
Progress: <done>/<total> done · <in_progress> in_progress · <pending> pending · <skipped> skipped
```

## Phase 2 — Wall time per phase

```bash
jq -r 'select(.kind | endswith("_end")) | [.kind, (.wall_ms // 0)] | @tsv' "$METRICS" \
  | awk -F'\t' '{
      sum[$1] += $2; count[$1]++
    } END {
      for (k in sum) printf "%-25s n=%-4d sum=%dm  avg=%dms\n", k, count[k], sum[k]/60000, sum[k]/count[k]
    }' | sort
```

Display this table sorted by total time descending. Tells you whether implementer, review, or user-wait dominates.

## Phase 3 — Token spend by subagent

```bash
jq -r 'select(.subagent_model != null) | [.subagent_model, (.subagent_input_tokens // (.prompt_chars // 0)/4), (.subagent_output_tokens // (.response_chars // 0)/4)] | @tsv' "$METRICS" \
  | awk -F'\t' '{
      in_tok[$1] += $2; out_tok[$1] += $3; count[$1]++
    } END {
      for (m in count) printf "%-10s calls=%-4d input_tok=%d output_tok=%d\n", m, count[m], in_tok[m], out_tok[m]
    }' | sort
```

Tells you the haiku/sonnet/opus split. Verifies that the v2 default-to-Sonnet change is actually taking effect.

## Phase 4 — Recent halts

```bash
jq -c 'select(.kind == "task_halt" or .kind == "decision_gate" or .kind == "task_security_warn" or .kind == "review_agent_failed" or .kind == "review_agent_malformed")' "$METRICS" \
  | tail -10
```

Display last 10 halts with their reasons.

## Phase 4b — Recent memory-review activity

```bash
jq -c 'select(.kind == "review_agent_call")' "$METRICS" | tail -10
```

Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`

Where `<input>` and `<output>` come from the event's `subagent_input_tokens` / `subagent_output_tokens` fields.

### Memory review terminal states (last 10 runs)

Collect terminal-state rows from `metrics.jsonl`. Read both the new `memory_review_terminal` event and old-shape events for back-compat. Old-shape mapping rules:

- `phase_end` with `name == "memory_review"` and `skip_reason` in `["empty_diff","all_tasks_skipped"]` → `state: not_applicable`
- `phase_end` with `name == "memory_review"` and `skip_reason` in `["tags_missing","no_plan_dir","missing_args"]` → `state: skipped_broken_context`
- `phase_end` with `name == "memory_review"` and no `skip_reason` → `state: ran_empty, skip_reason: null`
- `review_agent_failed` with `reason == "tags_missing"` → `state: skipped_broken_context, skip_reason: "tags_missing"`

```bash
jq -s '
  # Normalize all events to a common shape: {run, ts, state, skip_reason, parent_command, candidates, accepted}
  map(
    if .kind == "memory_review_terminal" then
      {
        run: (.run // "unknown"),
        ts: (.ts // ""),
        state: (.state // "unknown"),
        skip_reason: (.skip_reason // null),
        parent_command: (.parent_command // null),
        candidates: (.candidates // 0),
        accepted: (.accepted // 0)
      }
    elif .kind == "phase_end" and .name == "memory_review" then
      {
        run: (.run // "unknown"),
        ts: (.ts // ""),
        state: (
          if .skip_reason == "empty_diff" or .skip_reason == "all_tasks_skipped" then "not_applicable"
          elif .skip_reason == "tags_missing" or .skip_reason == "no_plan_dir" or .skip_reason == "missing_args" then "skipped_broken_context"
          else "ran_empty"
          end
        ),
        skip_reason: (.skip_reason // null),
        parent_command: (.parent_command // null),
        candidates: (.candidates // 0),
        accepted: (.accepted // 0)
      }
    elif .kind == "review_agent_failed" and .reason == "tags_missing" then
      {
        run: (.run // "unknown"),
        ts: (.ts // ""),
        state: "skipped_broken_context",
        skip_reason: "tags_missing",
        parent_command: (.parent_command // null),
        candidates: 0,
        accepted: 0
      }
    else empty
    end
  )
  # Get last 10 distinct runs (by unique run field, newest first)
  # Group by run, pick the last event per run as authoritative
  | group_by(.run)
  | map({run: .[0].run, ts: .[0].ts, terminal: .[-1]})
  | sort_by(.ts) | reverse | .[0:10]
  | map(.terminal)
  # Aggregate by state
  | group_by(.state)
  | map({
      state: .[0].state,
      count: length,
      accepted_total: (map(.accepted // 0) | add),
      skip_reason_counts: (
        map(.skip_reason // "null")
        | group_by(.)
        | map({(.[0]): length})
        | add // {}
      ),
      parent_command_counts: (
        map(.parent_command // "unknown")
        | group_by(.)
        | map({(.[0]): length})
        | add // {}
      )
    })
' "$METRICS"
```

Display the aggregation as a human-readable section titled **"Memory review terminal states (last 10 runs across all parents):"** with one line per state:

```
Memory review terminal states (last 10 runs across all parents):
  needs_user             4    (of which accepted: 6 memories)
  ran_empty              2
  not_applicable         3    (empty_diff: 2, all_tasks_skipped: 1)
  skipped_broken_context 1    (tags_missing: 1)
```

Rules for display:
- Order: `needs_user`, `ran_empty`, `not_applicable`, `skipped_broken_context` (by severity, most actionable first).
- For `needs_user`: include `(of which accepted: <sum> memories)` parenthetical.
- For `not_applicable` and `skipped_broken_context`: include parenthetical listing each `skip_reason: count` pair.
- Omit states with count 0.
- If no terminal-state events found (section empty), print: `  (no memory-review terminal events found in metrics.jsonl)`

## Phase 5 — Stalls (post-run gap detection)

Reuse the gap-detection awk from `/z-implement-all` Detecting Stalls section. Flag any gap > 30 min between consecutive same-run events.

## Phase 6 — Plugin version history

```bash
jq -r 'select(.kind | test("^(run_start|light_run_start|debug_run_start|test_plan_start)$")) | [.ts, .kind, .z_harness_version, .z_harness_dirty] | @tsv' "$METRICS" \
  | tail -10
```

Shows which plugin commit ran each of the recent plans (full `/z-plan`, `/z-plan-light`, `/z-debug`, and `/z-test` all included). If two plans show different `z_harness_version`, that's important context when comparing their stats.

## Phase 7 — Suggested next command

Based on the state, suggest one command:

| State | Suggest |
|---|---|
| All tasks `[x]` and no `/z-review-all` ran yet | `/z-review-all` |
| `/z-review-all` ran and accepted | `/z-maintain-docs` (or `/z-maintain-docs --audit` for cross-LLM verification) |
| Some tasks `[ ]` and no in-flight halts | `/z-implement-all` |
| In-flight halts pending user | "Resolve halts before continuing" (show them) |
| Plan is fresh (no `task_start` events yet) and `$BASE/TESTS.md` absent | `/z-test` (optional, recommended for risky / financial code) then `/z-implement-all` |
| Plan is fresh and `$BASE/TESTS.md` present with `Status: drafted` | `/z-implement-all` (will pick up TESTS.md automatically) |
| No plan / no TASKS.md | `/z-plan` (full feature) or `/z-plan-light` (small fix) or `/z-debug` (existing bug) |
| Light-mode plan with `FIX.md` and `Status: shipped` | `/z-maintain-docs` if FIX.md "Docs touched" is non-empty |
| Debug plan with `DEBUG.md ## Post-mortem` action items not yet tasked | "Convert post-mortem action items via the AskUserQuestion path documented in /z-debug Phase 9 (option C seeds a /z-test follow-up)" |

## Output format

Single concise report, ~30-50 lines total. Section headers. No prose filler. The user runs this to check in, not to read documentation.

## Hard rules

- **READ ONLY.** Never edit any file. Never write to `metrics.jsonl` or any archive.
- **No subagent dispatch.** This command must run instantly (≤2s wall time).
- **No LLM API calls.** Just shell + jq + awk against existing files.
- Don't log a start/end event for `/z-stats` itself — it would pollute the metrics it's reading.
