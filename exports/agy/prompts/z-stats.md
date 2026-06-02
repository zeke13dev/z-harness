---
description: Read-only progress + cost report for a z-harness plan. Reads metrics.jsonl + TASKS.md to summarize progress, wall time per phase, estimated token spend per subagent type, recent halts, and suggested next command. No writes, no LLM calls.
role: workflow
---

You are running **z-harness `/z-stats`**. Read-only diagnostic. Cheap — uses only Bash/jq/awk on the existing event log; no subagent dispatch.

## Phase 0 — Slug discovery

Same as `/z-implement-all` Phase 0:
1. Enumerate `$Z_HARNESS_PLAN_DIR/` subdirs with TASKS.md; check legacy flat layout.
2. If `--slug <slug>` arg present → use it.
3. If one candidate → use it.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
4. Multiple → `AskUserQuestion` to pick.
5. Zero → tell user "no plan found"; abort.

Set `$BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy). Set `$METRICS = $BASE/metrics.jsonl` (if exists) else `z-harness/metrics.jsonl`.

## Phase 0b — Resolved base header

Print a small header at the very top of the output (unconditionally — NOT gated behind `Z_HARNESS_EXPLAIN_RESOLUTION`):

```bash
_zh_base="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir 2>/dev/null)"
_zh_repo_id="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" z_harness_repo_id 2>/dev/null)"
_zh_active_count="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" list --json 2>/dev/null \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null)"
```

Display as:

```
Base:        <_zh_base>
Repo-id:     <_zh_repo_id>
Active plans: <_zh_active_count>
```

Fallback rules:
- If `_zh_base` is empty → print `Base: (unavailable)`
- If `_zh_repo_id` is empty → print `Repo-id: (unavailable)`
- If the registry call fails or `_zh_active_count` is empty → print `Active plans: (registry unavailable)`
- If the registry returns 0 → print `Active plans: 0`

This block is read-only. No writes, no LLM calls.

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

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | yes | Phase 0 slug selection (multiple candidates) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
