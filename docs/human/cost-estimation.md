# Cost Estimation

> Last updated: 2026-06-19
> Covers source: scripts/estimate-tokens.py, scripts/token-cost-profiles.json, scripts/pre-run-cost-gate.sh, scripts/config.py (workflow.pre_run_cost_gate, cost.token_budget), commands/z-research.md, commands/z-uplift.md, commands/z-plan-split.md, commands/z-brainstorm.md, commands/z-audit.md, commands/z-debug.md

## Overview

The cost-estimation subsystem provides LLM-free pre-run token-cost estimates for expensive z-harness commands. Before large commands run, the system estimates token consumption, renders a human-readable summary, and either asks the user to confirm, proceeds automatically, or halts — depending on the command's severity and the resolved `workflow.pre_run_cost_gate` preference.

The design is intentionally DRY: one estimator (`estimate-tokens.py`), one gate helper (`pre-run-cost-gate.sh`), one event kind (`cost_gate_decision`), and one profile file (`token-cost-profiles.json`). No per-command cost logic is duplicated. The estimator also exposes a `subagent-costs` subcommand that reads `subagent_call` events from `metrics.jsonl` and computes per-host, per-model cost breakdowns used by `/z-stats`.

## The estimator: `scripts/estimate-tokens.py`

`estimate-tokens.py` is a standalone Python CLI that supports two subcommands. It is LLM-free and fail-open: on any error it returns a usable envelope and exits 0; it exits non-zero only when a required argument is missing.

### CLI

```
estimate-tokens.py estimate <command> [--dispatch KEY=N ...] [--metrics PATH]
                             [--profiles PATH] [--tail-lines N] [--min-samples N]

estimate-tokens.py subagent-costs [--metrics PATH] [--tail-lines N] [--json]

# Legacy backward-compatible positional mode (injects 'estimate' automatically):
estimate-tokens.py <command> [--dispatch KEY=N ...]
```

- `<command>` — the z-harness command to estimate (accepts `/z-research`, `z-research`, or bare `research`; prefix normalization is automatic).
- `--dispatch KEY=N` — adds `multipliers[KEY] * N` tokens to the static range. Repeatable. Unknown keys warn to stderr and are ignored.
- `--metrics PATH` — path to `metrics.jsonl`. Default: resolves via `plan-path.sh base_dir` (external base after Phase-D flip) then falls back to `<repo>/z-harness/metrics.jsonl`.
- `--profiles PATH` — path to `token-cost-profiles.json`. Default: co-located with this script.
- `--tail-lines N` — max lines to read from `metrics.jsonl` tail (env `Z_HARNESS_COST_TAIL_LINES`, default 2000; default 5000 for `subagent-costs`).
- `--min-samples N` — minimum historical samples for the empirical tier to fire (env `Z_HARNESS_COST_MIN_SAMPLES`, default 3).
- `--json` — (`subagent-costs` only) emit raw JSON instead of the human-readable table.

### Output envelope (estimate subcommand)

```json
{
  "command":          "z-research",
  "estimated_tokens": 4200000,
  "range_low":        3000000,
  "range_high":       6200000,
  "confidence":       "high",
  "basis":            "static profile + dispatch(map) + 5 historical runs",
  "breakdown": [
    {"tier": "static",   "low": 3000000, "high": 6000000},
    {"tier": "dispatch", "add": 200000,  "keys": ["map"]},
    {"tier": "empirical","p50": 4200000, "p90": 6200000, "samples": 5}
  ],
  "gate": "hard"
}
```

`gate` reflects the profile's declared severity (`"hard"` | `"soft"` | `null`). A no-profile command returns a zeroed envelope with `confidence: "low"`, `range_high: 0`, and `gate: null`.

### Three estimation tiers

All three tiers compose additively. Each tier is recorded in `breakdown`.

**Tier 1 — Static.** Reads the `range` array from the command's profile in `token-cost-profiles.json`. This is always present for profiled commands and provides the floor/ceiling.

**Tier 2 — Dispatch.** Adds `multipliers[KEY] * N` for each `--dispatch KEY=N` argument. This accounts for per-invocation parameters such as the number of components in a plan-split or the brainstorm sub-run count in a research run. Unknown dispatch keys are ignored with a warning. Dispatch is added to both bounds: `range_low += dispatch_add`, `range_high += dispatch_add`.

**Tier 3 — Empirical.** Reads the tail of `metrics.jsonl`, buckets events by parent-run (using `parent_run_id` if present, else `run`), and computes p50/p90 token totals over normally-completed parent runs attributed to the command. Only runs that have a terminal event with a non-aborted/non-halted/non-errored status are included; in-flight runs (latest timestamp within 5 minutes of the file's max timestamp) and runs with `cost_gate_decision{choice: abandon}` are also excluded.

**Static-floor clamp.** The empirical tier may only widen the estimate upward, never shrink it below the static+dispatch floor:

```
estimated_tokens = max(static_low + dispatch_add, round(p50))
range_high       = max(static_high + dispatch_add, round(p90))
range_low        = static_low + dispatch_add   (never lowered)
```

**Confidence levels:**

| Situation | confidence |
|-----------|-----------|
| Empirical tier fired with `>= 2 * min_samples` | `"high"` |
| Empirical tier fired with `< 2 * min_samples` | `"medium"` |
| Static + dispatch only (no empirical) | `"medium"` |
| Static only (no dispatch, no empirical) | `"low"` |
| No profile found | `"low"` (zeroed envelope) |

### Subagent cost model (`subagent-costs` subcommand)

`estimate-tokens.py subagent-costs` reads `subagent_call` events from `metrics.jsonl` and computes per-host, per-`subagent_type` cost estimates. Pricing lives in `_DEFAULT_MODEL_RATES` — a dict of USD/1M-token rates for Claude (haiku/sonnet/opus), OpenAI (gpt-4o/mini/gpt-4/gpt-3.5), Google (gemini/flash/pro), and DeepSeek families. Pricing knowledge is consolidated here (SOLID principle); raw telemetry keeps prompt_chars and response_chars separate (D9 invariant).

When `provider_input_tokens` / `provider_output_tokens` are present in an event (external CLIs that print a usage line), those are used directly. Otherwise the estimator falls back to `chars/4` (labeled `[char-est]` in output). This honest limitation is prominently labeled: native Claude `Agent()` subagents do not expose real token counts to the orchestrator. `/z-stats` calls `estimate-tokens.py subagent-costs` for its cost breakdown section.

## The profile schema: `scripts/token-cost-profiles.json`

```json
{
  "schema_version": "1",
  "profiles": {
    "z-research":    {"range": [3000000, 6000000], "gate": "hard",
                      "multipliers": {"map": 2000000, "brainstorm": 200000}},
    "z-uplift":      {"range": [2000000, 8000000], "gate": "hard",
                      "multipliers": {"per_component": 600000}},
    "z-plan-split":  {"range": [1500000, 5000000], "gate": "hard",
                      "multipliers": {"per_cluster": 700000}},
    "z-brainstorm":  {"range": [80000, 220000], "gate": "soft",
                      "multipliers": {"per_heavy_chunk": 200000}},
    "z-audit":       {"range": [200000, 1200000], "gate": "soft",
                      "multipliers": {"per_dimension": 250000}},
    "z-debug":       {"range": [300000, 1500000], "gate": "soft"}
  }
}
```

- `range`: `[low, high]` integer token estimate forming the static floor/ceiling.
- `gate`: `"hard"` | `"soft"` | (absent = no gate). Consumed by `pre-run-cost-gate.sh`.
- `multipliers`: optional map of dispatch key to per-unit token cost. A command passes `--dispatch key=N` to apply `multipliers[key] * N`. Absent key = 0.

An unknown command produces a `confidence: "low"` envelope with `range_high: 0` and `gate: null`; the caller treats this as estimate-unavailable and proceeds.

## The gate helper: `scripts/pre-run-cost-gate.sh`

`pre-run-cost-gate.sh` is the DRY gate driver called by each gating command. It encapsulates the estimate — resolve-disposition — render-human-block pipeline. It does NOT call `AskUserQuestion` (that is the command's job) and does NOT log events (the caller logs `cost_gate_decision`).

### CLI

```
pre-run-cost-gate.sh <command> <hard|soft> <RUN> [--dispatch KEY=N ...]
```

### Stdout contract

A single JSON object (no bare text):

```json
{
  "disposition": "ask|auto_proceed|halt|unhandled_gate",
  "estimate":    { ... full envelope from estimate-tokens.py ... },
  "human_block": "Token estimate for /z-research:\n  estimate  : ~4.2M\n  range     : 3.0M–6.2M\n  confidence: high\n  basis     : static profile + 5 historical runs"
}
```

All diagnostics and warnings go to stderr only. When the estimator is unavailable the fallback envelope uses `range_high: null` (not `0`).

### Gate disposition logic

The gate helper delegates the policy decision to `config.py check-no-ask --question-id workflow.pre_run_cost_gate --range-high <N> --severity <hard|soft>`. This single delegation point ensures that:

1. The overnight-override layer (`Z_HARNESS_NO_ASK=halt`) applies correctly.
2. The `unhandled_gate` loud-abort guarantee is preserved for benchmark/policy mode.
3. The budget rule (`cost.token_budget`) is evaluated once, in one place.

**Soft gate** (`--severity soft`): `config.py` returns `auto_proceed` immediately without consulting the budget. The estimate is displayed and logged, but no AskUser is presented.

**Hard gate** (`--severity hard`): The budget rule applies. Disposition outcomes:

| Condition | Disposition |
|-----------|------------|
| Interactive mode (`Z_HARNESS_NO_ASK` not set) | `ask` |
| `Z_HARNESS_NO_ASK=halt` + in allowlist | `auto_proceed` |
| `Z_HARNESS_NO_ASK=halt` + `range_high <= budget` | `auto_proceed` (`rule_id: within_budget`) |
| `Z_HARNESS_NO_ASK=halt` + `budget` unset | `halt` (`rule_id: cost_budget_missing`) |
| `Z_HARNESS_NO_ASK=halt` + `range_high > budget` | `halt` or `unhandled_gate` (policy mode) |
| Policy/benchmark mode + range_high > budget | `unhandled_gate` (`rule_id: unhandled_gate`) |
| Estimator unavailable | Fail-open: `ask` (hard) or `auto_proceed` (soft) |

The helper is fail-open: estimator failures produce a zeroed fallback envelope and fallback disposition rather than hard-failing the caller.

## Config knobs

### `workflow.pre_run_cost_gate` (enum question_id)

Controls how the AskUser cost gate behaves when the gate helper returns `disposition: ask`. Registered in `QUESTION_IDS` and `VALIDATORS`.

| Value | Behavior |
|-------|----------|
| `ask` (default) | Present AskUserQuestion with proceed / change-dispatch / abandon choices |
| `auto_proceed` | Skip AskUser; proceed automatically |
| `halt` | Halt unconditionally without asking |

TOML key: `workflow.pre_run_cost_gate` (under `[workflow]` section).
Env var: `Z_HARNESS_WORKFLOW_PRE_RUN_COST_GATE`.

This is NOT added to `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT`; operators must opt in via the `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` env var or a config setting.

### `cost.token_budget` (integer or null)

Sets the token ceiling used by the overnight/batch gate. When `workflow.pre_run_cost_gate` resolves to `ask` but `Z_HARNESS_NO_ASK=halt` is active, config.py compares `range_high` against this budget:

- `range_high <= budget` — `auto_proceed` (`rule_id: within_budget`)
- `range_high > budget` — `halt` (`rule_id: cost_over_budget`) or `unhandled_gate` in benchmark/policy mode
- budget unset (null) — `halt` (`rule_id: cost_budget_missing`)
- budget <= 0 (invalid) — `halt` (`rule_id: cost_budget_invalid`)

TOML key: `cost.token_budget` (under `[cost]` section, default `None`).
Env var: `Z_HARNESS_COST_TOKEN_BUDGET` (string value is coerced to int).

This knob is NOT a question_id and does NOT appear in `QUESTION_IDS` or `RESULT_MAP`.

**Overnight/no-ask behavior:** Set `cost.token_budget` to a positive integer so unattended runs can auto-proceed for under-budget commands and halt for over-budget ones. Without this knob, all hard-gate commands halt in overnight mode (`cost_budget_missing`).

## Hard-gate vs soft-warn commands

| Command | Severity | Gate fires on |
|---------|----------|---------------|
| `/z-research` | hard | Always (Phase 0.5, after dispatch decision) |
| `/z-uplift` | hard | Always (Phase 1.5) |
| `/z-plan-split` | hard | Always (Phase 1.5) |
| `/z-brainstorm` | soft | HEAVY classification path only (Phase 0 HEAVY fan-out, step 1a) |
| `/z-audit` | soft | HEAVY classification path only |
| `/z-debug` | soft | Always (Phase 0 wrong-tool gate preamble) |

**Hard gates** present an AskUserQuestion with proceed / change-dispatch / abandon choices. The command halts if the user abandons or if `workflow.pre_run_cost_gate = halt`.

**Soft gates** display the estimate and log `cost_gate_decision{choice: auto_proceed, reason: soft_gate}` without blocking. No AskUser is presented.

**Wide-mode conversational gate (`/z-brainstorm` WIDE_N > 3 only).** When a wide brainstorm run is requested (WIDE_N > 3, Phase 2c), a separate inline prose cost estimate is presented at the end of the turn — this is NOT backed by `pre-run-cost-gate.sh` but is a direct calculation. The orchestrator ends the turn and awaits user confirmation before dispatching any overflow ideators. This gate is orthogonal to the HEAVY soft gate above: D2 ensures wide and HEAVY never multiply (wide requests suppress HEAVY fan-out).

## The `cost_gate_decision` event

All gates (hard and soft) emit exactly one `cost_gate_decision` event per invocation. The canonical fields are:

```json
{
  "kind":             "cost_gate_decision",
  "run":              "<RUN_ID>",
  "command":          "z-research",
  "choice":           "proceed | auto_proceed | change_dispatch | abandon | halt",
  "estimated_tokens": 4200000,
  "confidence":       "high",
  "basis":            "static profile + 5 historical runs"
}
```

`choice` values:

| Value | Meaning |
|-------|---------|
| `proceed` | User confirmed at AskUser (hard gate) |
| `auto_proceed` | Gate auto-proceeded (soft gate, or `workflow.pre_run_cost_gate=auto_proceed`, or within budget) |
| `change_dispatch` | User chose to change dispatch parameters (z-research loop-back) |
| `abandon` | User abandoned at AskUser, or `halt` disposition, or loop-back cap exceeded |
| `halt` | Automatic halt (overnight/policy mode) |

The event is logged AFTER `run_start` so it attributes to the run. An abandoned gate (`choice: abandon`) causes the empirical tier to exclude that run from future estimates.

`/z-stats` reads `cost_gate_decision` events for the read-only cost-gate decisions rollup (command, choice, estimated_tokens).

## z-research loop-back behavior

`/z-research` has a 3-loop-back cap on "change dispatch". When the user chooses to change dispatch parameters at the cost gate:

1. `cost_gate_decision{choice: change_dispatch}` is logged.
2. The loop-back counter increments.
3. Control returns to Phase 0 (dispatch decision) for the user to update `--dispatch` flags.
4. On Phase 0.5 re-entry, the gate is re-invoked with the updated `--dispatch` flags (estimate recomputes).
5. If `COST_GATE_LOOPBACKS > 3`, the gate falls through to Abandon regardless of user choice.

## Telemetry and calibration

The empirical tier reads the same `metrics.jsonl` that `z-stats` uses. Events land in the repo-wide external base (resolved via `plan-path.sh base_dir`). Each run that completes normally produces a data point for future estimates. Over time, empirical p50/p90 values converge toward actual usage patterns, and the static floor clamp ensures early low-data estimates do not pull the ceiling below the known profile minimum.

The `cost_gate_decision` events form a calibration record: `estimated_tokens` vs actual run cost (sum of child token events in the same parent-run bucket) can be compared post-run via `/z-stats subagent-costs` to assess profile accuracy.

## How it interacts with others

- `config` — `_resolve_cost_gate` in config.py is the single authority for cost-gate disposition; pre-run-cost-gate.sh delegates to it via `check-no-ask`; `cost.token_budget` and `workflow.pre_run_cost_gate` are both defined in config.py DEFAULTS
- `scripts` — estimate-tokens.py and pre-run-cost-gate.sh live in scripts/; they share no state beyond the gate helper invoking the estimator as a subprocess
- `commands` — six commands (z-research, z-uplift, z-plan-split, z-brainstorm, z-audit, z-debug) call pre-run-cost-gate.sh and own AskUser + cost_gate_decision event logging
- `subagent-telemetry` — `estimate-tokens.py subagent-costs` reads `subagent_call` events to produce the cost model output consumed by `/z-stats`; the two subsystems share `metrics.jsonl` but have no shared in-process state

## Edge cases / gotchas

- `cost.token_budget` string env values (e.g. `Z_HARNESS_COST_TOKEN_BUDGET="5000000"`) are coerced to int by `_COERCERS`. If coercion fails, config.py exits 2 (hard fail, not soft warn).
- `workflow.pre_run_cost_gate = halt` in TOML will halt ALL hard-gate commands unconditionally, including interactive sessions. Use only for CI or specialized environments.
- `--range-high` missing (estimator unavailable) causes the cost-gate delegation path to return `ask` in interactive mode and `halt` in overnight mode (`rule_id: cost_estimate_missing`). It never silently auto-proceeds.
- `budget <= 0` is invalid config (validator should catch it at write time); the `within_budget` comparison also guards against it with `rule_id: cost_budget_invalid`.
- The no-profile envelope produced by `_no_profile_envelope()` returns `range_high: 0`; the gate fallback envelope (when the estimator binary is unavailable) returns `range_high: null`. These are distinct cases.
- In benchmark/policy mode (`_is_policy_mode()` returns true), when `range_high > budget`, the gate returns `unhandled_gate` (loud abort) rather than `halt`. This is intentional: an unresolved reachable gate in a benchmark policy is a test bug, not a legitimate halt.
- The `brainstorm` multiplier in the z-research profile assumes a non-HEAVY brainstorm sub-run. A HEAVY brainstorm sub-run has a higher cost; there is no per-invocation budget override (change-dispatch is the lever).
- The empirical tier uses `parent_command` or `command` field on events for attribution. Legacy events without these fields fall back to kind-inference via `_KIND_TO_COMMAND`. Both `run_start` and `run_end` carry a `command` field (stamped by Phase-7 hardening) so a tail window that scrolled past `run_start` can still attribute via `run_end`.
- Soft gates fire only on the HEAVY classification path for `/z-brainstorm` and `/z-audit`. LIGHT/MEDIUM runs skip the gate entirely.
- The `/z-brainstorm` wide-mode conversational gate (Phase 2c-1, WIDE_N > 3) is a separate prose inline estimate — NOT backed by `pre-run-cost-gate.sh`. It uses a simple formula and ends the turn awaiting user confirmation. This fires independently of (and in addition to) the HEAVY soft gate.
- D2 (wide×HEAVY suppression): when `WIDE_N > 3`, the brainstorm command treats the run as MEDIUM and suppresses HEAVY fan-out entirely. This prevents the two fan-out axes from multiplying.
- The `cost_gate_decision` event replaces the legacy `research_cost_gate_decision` event for `/z-research`. Do not emit both.
- `_KIND_TO_COMMAND` maps generic `run_start`/`run_end` to `z-plan` as a best-effort default for legacy pre-T001 events; if pre-T001 z-research events appear in the tail window, attribution will be wrong for those runs only.
- `subagent-costs` pricing rates are approximate for native Claude subagents (chars/4 → tokens); only external CLIs that print a usage line produce `provider_input_tokens` / `provider_output_tokens` for exact accounting.
- The `_default_metrics_path()` function resolves the external base via `bash scripts/plan-path.sh base_dir` (subprocess, 10s timeout). If this fails, it falls back to the legacy in-repo `z-harness/metrics.jsonl` path. After the Phase-D external-base flip, the legacy path may be stale; `Z_HARNESS_BASE_DIR` env override is the reliable escape hatch.
