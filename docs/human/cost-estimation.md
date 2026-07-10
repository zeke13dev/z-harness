# Cost Estimation

> Last updated: 2026-07-09
> Covers source: scripts/estimate-tokens.py, scripts/pre-run-cost-gate.sh, scripts/token-cost-profiles.json, scripts/config.py, skills/z-research/SKILL.md, skills/z-uplift/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-audit/SKILL.md, skills/z-debug/SKILL.md, skills/z-plan/SKILL.md

## Overview

The cost-estimation subsystem provides LLM-free pre-run token-cost estimates for expensive z-harness commands. Before large commands run, the system estimates token consumption, renders a human-readable summary, and either asks the user to confirm, proceeds automatically, or halts — depending on the command's severity and the resolved `workflow.pre_run_cost_gate` preference.

The design is intentionally DRY: one estimator (`estimate-tokens.py`), one gate helper (`pre-run-cost-gate.sh`), one event kind (`cost_gate_decision`), and one profile file (`token-cost-profiles.json`). No per-command cost logic is duplicated. The estimator also exposes a `subagent-costs` subcommand that reads `subagent_call` events from `metrics.jsonl` and computes per-host, per-model cost breakdowns used by `/z-stats`. All seven gating skills now live under `skills/<name>/SKILL.md` (the pre-Phase-D `commands/*.md` layout is gone); `/z-plan`'s hard gate carries the richest telemetry contract of the group and is documented in detail below.

Hard-gated skills (`/z-plan`, `/z-research`, `/z-uplift`, `/z-plan-split`) also run Artifact Scout preflight around their hard gate (deterministic inventory pre-gate, optional `artifact-scout` Agent classifier post-gate). That mechanism is documented in its own concept doc — see "How it interacts with others" below — this doc only covers the boundary invariant it depends on: **no pre-gate Agent dispatch** of any kind.

## The estimator: `scripts/estimate-tokens.py`

`estimate-tokens.py` is a standalone Python CLI that supports three command families. It is LLM-free and fail-open: on any error it returns a usable envelope and exits 0; it exits non-zero only when a required argument is missing.

### CLI

```
estimate-tokens.py estimate <command> [--dispatch KEY=N ...] [--metrics PATH]
                             [--profiles PATH] [--tail-lines N] [--min-samples N]
                             [--e2e-forecast]

estimate-tokens.py forecast <command> [--dispatch KEY=N ...]

estimate-tokens.py subagent-costs [--metrics PATH] [--tail-lines N] [--json]

# Legacy backward-compatible positional mode (injects 'estimate' automatically):
estimate-tokens.py <command> [--dispatch KEY=N ...]
```

- `<command>` — the z-harness command to estimate (accepts `/z-research`, `z-research`, or bare `research`; prefix normalization is automatic).
- `--dispatch KEY=N` — adds `multipliers[KEY] * N` tokens to the static range. Repeatable. Unknown keys warn to stderr and are ignored. Profile `dispatch_defaults` apply unless explicitly replaced by a known key.
- `--metrics PATH` — path to `metrics.jsonl`. Default: resolves via `plan-path.sh base_dir` (external base after the Phase-D flip) then falls back to `<repo>/z-harness/metrics.jsonl`.
- `--profiles PATH` — path to `token-cost-profiles.json`. Default: co-located with this script.
- `--tail-lines N` — max lines to read from `metrics.jsonl` tail (env `Z_HARNESS_COST_TAIL_LINES`, default 2000; default 5000 for `subagent-costs`).
- `--min-samples N` — minimum historical samples for the empirical tier to fire (env `Z_HARNESS_COST_MIN_SAMPLES`, default 3).
- `--e2e-forecast` / `forecast` — emit a plan-vs-plan+execute forecast object instead of only the pre-run estimate envelope.
- `--json` — (`subagent-costs` only) emit raw JSON instead of the human-readable table.

### Output envelope (estimate subcommand)

```json
{
  "command":          "z-research",
  "estimated_tokens": 5200000,
  "range_low":        5200000,
  "range_high":       8200000,
  "confidence":       "medium",
  "basis":            "static profile + terrain/MAP dispatch (`map` key; /z-explore --depth=deep) + brainstorm dispatch",
  "breakdown": [
    {"tier": "static",   "low": 3000000, "high": 6000000},
    {"tier": "dispatch", "add": 2200000, "keys": ["map", "brainstorm"]}
  ],
  "gate": "hard"
}
```

`gate` reflects the profile's declared severity (`"hard"` | `"soft"` | `null`). A no-profile command returns a zeroed envelope with `confidence: "low"`, `range_high: 0`, and `gate: null`.

### E2E forecast output

`forecast <command>` and `estimate <command> --e2e-forecast` return a forecast object that explicitly separates the gated plan cost from the projected post-plan execution cost:

```json
{
  "schema_version": "e2e_forecast.v1",
  "mode": "e2e_forecast",
  "command": "z-plan",
  "plan_component": { "semantics": "cost_to_plan", "range_high": 10300000 },
  "execute_forecast_component": {
    "semantics": "forecast_execute_after_plan",
    "source": "static_forecast_profile",
    "range_low": 2000000,
    "range_high": 20000000,
    "confidence": "low",
    "uncertainty": "wide_static_fallback"
  },
  "total_forecast": {
    "semantics": "forecast_plan_plus_execute",
    "range_high": 30300000
  }
}
```

The `/z-plan` hard gate uses the plan component only. The execute component is an intentionally wide, low-confidence projection for later `/z-execute`; it is not exact and is not a hard cap.

### Three estimation tiers

All three tiers compose additively. Each tier is recorded in `breakdown`.

**Tier 1 — Static.** Reads the `range` array from the command's profile in `token-cost-profiles.json`. This is always present for profiled commands and provides the floor/ceiling.

**Tier 2 — Dispatch.** Adds `multipliers[KEY] * N` for each effective dispatch key. Profile `dispatch_defaults` supply conservative pre-gate counts when the command cannot know fan-out yet; explicit `--dispatch KEY=N` values replace defaults for the same key. Unknown dispatch keys are ignored with a warning. Dispatch is added to both bounds: `range_low += dispatch_add`, `range_high += dispatch_add`.

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

`estimate-tokens.py subagent-costs` reads `subagent_call` events from `metrics.jsonl` and computes per-host, per-`subagent_type` cost estimates. Pricing lives in `_DEFAULT_MODEL_RATES` — a dict of USD/1M-token rates for Claude (haiku/sonnet/opus), OpenAI (gpt-4o/mini/gpt-4/gpt-3.5), Google (gemini/flash/pro), and DeepSeek families. Pricing knowledge is consolidated here (SOLID principle); raw telemetry keeps `prompt_chars` and `response_chars` separate (D9 invariant).

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
    "z-plan":        {"range": [300000, 900000], "gate": "hard",
                      "multipliers": {"planning_mode_full": 700000,
                                      "intent_level_depth": 200000,
                                      "doc_fetcher": 100000,
                                      "explore": 2800000,
                                      "phase3_consultants": 350000,
                                      "phase7_consultants": 350000,
                                      "task_tree_generator": 300000},
                      "dispatch_defaults": {"planning_mode_full": 0,
                                            "intent_level_depth": 2,
                                            "doc_fetcher": 1,
                                            "explore": 3,
                                            "phase3_consultants": 5,
                                            "phase7_consultants": 5,
                                            "task_tree_generator": 1}},
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
- For `z-research`, the legacy `map` multiplier key is still the live profile key for terrain/MAP.md cost compatibility; user-facing command guidance should describe that child terrain work as `/z-explore --depth=deep`.
- `dispatch_defaults`: optional conservative defaults used when a command cannot know future fan-out before the gate. Explicit dispatch values for the same key replace the default; duplicate explicit values for one key are summed before replacement. Negative counts are rejected.

The real `z-plan` profile also carries `dispatch_contract.accepted_keys` documentation and an `e2e_forecast.execute_forecast` block. The latter is the static, low-confidence projected `/z-execute` component used only by forecast mode; it is not part of the hard gate's plan-cost approval.

An unknown command produces a `confidence: "low"` envelope with `range_high: 0` and `gate: null`; the caller treats this as estimate-unavailable and proceeds.

## The gate helper: `scripts/pre-run-cost-gate.sh`

`pre-run-cost-gate.sh` is the DRY gate driver called by each gating skill. It encapsulates the estimate — resolve-disposition — render-human-block pipeline. It does NOT call `AskUserQuestion` (that is the skill's job) and does NOT log events (the caller logs `cost_gate_decision`).

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
  "human_block": "Token estimate for /z-research:\n  estimate  : ~5.2M\n  range     : 5.2M–8.2M\n  confidence: medium\n  basis     : static profile + terrain/MAP dispatch (`map` key; /z-explore --depth=deep) + brainstorm dispatch"
}
```

All diagnostics and warnings go to stderr only. When the estimator is unavailable the fallback envelope uses `range_high: null` (not `0`).

### Gate disposition logic

The gate helper delegates the policy decision to `config.py check-no-ask --question-id workflow.pre_run_cost_gate --range-high <N> --severity <hard|soft>` (`_resolve_cost_gate`, `scripts/config.py`). This single delegation point ensures that:

1. The overnight-override layer (`Z_HARNESS_NO_ASK=halt`) applies correctly, and its allowlist is checked *before* the budget rule.
2. The `unhandled_gate` loud-abort guarantee is preserved for benchmark/policy mode.
3. The budget rule (`cost.token_budget`) is evaluated once, in one place.

**Soft gate** (`--severity soft`): `config.py` returns `auto_proceed` immediately (`rule_id: soft_gate`) without consulting the budget. The estimate is displayed and logged, but no AskUser is presented.

**Hard gate** (`--severity hard`): The budget rule applies. Disposition outcomes:

| Condition | Disposition |
|-----------|------------|
| Interactive mode (`Z_HARNESS_NO_ASK` not set) | `ask` (`rule_id: interactive`, or `cost_estimate_missing` if `range_high` is absent) |
| `Z_HARNESS_NO_ASK=halt` + overnight allowlist positively resolves the gate | `auto_proceed` (skip/prefill mapped to `auto_proceed`) or the overnight-resolved result |
| `Z_HARNESS_NO_ASK=halt` + not in allowlist + `range_high <= budget` | `auto_proceed` (`rule_id: within_budget`) |
| `Z_HARNESS_NO_ASK=halt` + not in allowlist + `budget` unset | `halt` (`rule_id: cost_budget_missing`) |
| `Z_HARNESS_NO_ASK=halt` + not in allowlist + `budget <= 0` | `halt` (`rule_id: cost_budget_invalid`) |
| `Z_HARNESS_NO_ASK=halt` + not in allowlist + `range_high > budget` | `halt` (`rule_id: cost_over_budget`), or `unhandled_gate` in policy/benchmark mode |
| Estimator unavailable (`range_high` missing) | Fail-closed under policy: `halt` (`cost_estimate_missing`); fail-open interactively: `ask` |

The helper is fail-open at the estimator layer: estimator failures produce a zeroed fallback envelope and fallback disposition rather than hard-failing the caller, but once a `range_high` and `severity` reach `config.py`, the hard-gate policy resolution above is fail-closed (never silently auto-proceeds on missing data).

## Config knobs

### `workflow.pre_run_cost_gate` (enum question_id)

Controls how the AskUser cost gate behaves when the gate helper returns `disposition: ask`. Registered in `QUESTION_IDS` (`scripts/config.py`) with callsites `scripts/pre-run-cost-gate.sh`, `skills/z-research/SKILL.md`, `skills/z-uplift/SKILL.md`, `skills/z-plan-split/SKILL.md`, and `skills/z-plan/SKILL.md`.

| Value | Behavior |
|-------|----------|
| `ask` (default) | Present AskUserQuestion with proceed / change-dispatch / abandon choices |
| `auto_proceed` | Skip AskUser; proceed automatically |
| `halt` | Halt unconditionally without asking |

TOML key: `workflow.pre_run_cost_gate` (under `[workflow]` section).
Env var: `Z_HARNESS_WORKFLOW_PRE_RUN_COST_GATE`.

This is NOT in `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT`; operators must opt in via the `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` env var or a config setting.

### `cost.token_budget` (integer or null)

Sets the token ceiling used by the overnight/batch gate. When the overnight allowlist does not positively resolve the gate, `config.py` compares `range_high` against this budget:

- `range_high <= budget` — `auto_proceed` (`rule_id: within_budget`)
- `range_high > budget` — `halt` (`rule_id: cost_over_budget`) or `unhandled_gate` in benchmark/policy mode
- budget unset (null) — `halt` (`rule_id: cost_budget_missing`)
- budget `<= 0` (invalid) — `halt` (`rule_id: cost_budget_invalid`)

TOML key: `cost.token_budget` (under `[cost]` section, default `None`).
Env var: `Z_HARNESS_COST_TOKEN_BUDGET` (string value is coerced to int).

This knob is NOT a question_id and does NOT appear in `QUESTION_IDS` or `RESULT_MAP`.

**Overnight/no-ask behavior:** Set `cost.token_budget` to a positive integer so unattended runs can auto-proceed for under-budget commands and halt for over-budget ones. Without this knob, all hard-gate commands halt in overnight mode (`cost_budget_missing`).

## Hard-gate vs soft-warn commands

| Command | Severity | Gate fires on |
|---------|----------|---------------|
| `/z-research` | hard | Phase 0.5, after dispatch decision and deterministic scout inventory, before the post-gate `artifact-scout` classifier or child terrain (`/z-explore --depth=deep`, producing MAP.md) / `/z-brainstorm` dispatch |
| `/z-uplift` | hard | Phase 1.5 pre-fanout gate after component count is known |
| `/z-plan-split` | hard | Phase 1.5 pre-fanout gate after cluster confirmation |
| `/z-plan` | hard | Pre-subagent gate (`skills/z-plan/SKILL.md`, "Pre-subagent cost gate (hard)"), after setup/claim/register, freshness checks, deterministic route preflight, and the explicit planning-mode gate; before deferred `planning-router`, `intent-classifier`, doc-fetcher, Explore, Phase 3/7 consultant panels, `task-tree-generator`, or any other Agent |
| `/z-brainstorm` | soft | HEAVY classification path only (Phase 0 HEAVY fan-out, step 1a) |
| `/z-audit` | soft | HEAVY classification path only |
| `/z-debug` | soft | Always (Phase 0 wrong-tool gate preamble) |

**Hard gates** present an AskUserQuestion unless policy/config auto-resolves them. The skill halts if the user abandons, if `workflow.pre_run_cost_gate = halt`, or if unattended budget policy returns `halt`/`unhandled_gate`.

**Soft gates** display the estimate and log `cost_gate_decision{choice: auto_proceed, reason: soft_gate}` without blocking. No AskUser is presented.

**Wide-mode conversational gate (`/z-brainstorm` WIDE_N > 3 only).** When a wide brainstorm run is requested (Phase 2c), a separate inline prose cost estimate is presented — this is NOT backed by `pre-run-cost-gate.sh` but is a direct calculation. The orchestrator ends the turn and awaits user confirmation before dispatching any overflow ideators. This gate is orthogonal to the HEAVY soft gate: wide and HEAVY never multiply (wide requests suppress HEAVY fan-out).

## The `/z-plan` cost gate telemetry contract (detailed)

`/z-plan`'s hard gate (`skills/z-plan/SKILL.md`, "Pre-subagent cost gate (hard)" onward) has the richest telemetry contract of the seven gating skills, and its docs previously undersold it. Key mechanics:

**Dispatch keys computed pre-gate:** `planning_mode_full`, `intent_level_depth` (0=quick/1=standard/2=deep — forced levels are charged exactly, `auto`/unknown charges deep conservatively), `doc_fetcher` (from the cheap `DOCS_LLM_INDEX_EXISTS` setup signal), `explore` (from `workflow.max_explore`, default 3), `phase3_consultants` (5, or 0 only when a pre-known L1 Quick level makes Phase 3 structurally unreachable), `phase7_consultants` (5, always conservative pre-gate), `task_tree_generator` (1 for intent-mode runs).

**`cost_gate_decision` fields** (exactly one terminal event per `/z-plan` run, emitted via `emit_zplan_cost_gate_decision_once`):

```json
{
  "command":          "z-plan",
  "choice":           "auto_proceed | proceed | abandon | halt | interrupted",
  "estimated_tokens":  900000,
  "confidence":       "medium",
  "basis":            "static profile + dispatch(...)",
  "disposition":      "auto_proceed | ask | halt | unhandled_gate | <sanitized fallback>",
  "rule_id":          "<from config.py, when known>",
  "range_high":       900000,
  "choice_source":    "helper | user | policy | sanitized_helper_error | driver_interrupt",
  "attempt_count":    0,
  "reason":           "gate_policy_halt | unhandled_gate | helper_invocation_failure | malformed_helper_json | missing_estimate_fields | user_abandoned | user_wait_interrupted (optional)"
}
```

**Nonterminal reduction attempts** emit `cost_gate_reestimate_attempt` instead (never `cost_gate_decision`):

```json
{
  "command":            "z-plan",
  "run_id":             "<RUN>",
  "gate_id":            "<RUN>:z-plan:pre-subagent-cost-gate",
  "attempt_index":      1,
  "changed_drivers":    ["intent_level_depth", "intent_level", "intent_consult_policy"],
  "prior_range_high":   900000,
  "new_range_high":     600000,
  "disposition":        "auto_proceed | ask | halt | unhandled_gate",
  "terminal_event_kind": "cost_gate_decision"
}
```

**Bounded reduction loop.** `ZPLAN_COST_REESTIMATE_MAX=2` — after two valid reduction attempts, the prompt drops all reduction options and offers only proceed-with-current-estimate or abandon. Reducible drivers are deliberately narrow: only `force_l2_standard` (downgrade to L2 Standard, `intent_level_depth=1`) and `force_l1_quick` (downgrade to L1 Quick, `intent_level_depth=0` and `phase3_consultants=0`) are offered, and only in `PLANNING_MODE=intent`. `doc_fetcher`, `task_tree_generator`, `phase7_consultants`, and `explore` are never reducible from this loop. If a reduction re-estimate refreshes `GATE_DISPOSITION=auto_proceed`, that is terminal (`choice_source=helper`) — no further prompt.

**Terminal cleanup.** Every non-proceed terminal branch (`abandon`, `halt`, `unhandled_gate`, helper failure/malformed/missing-field no-ask halt, or interrupted wait) reuses Run Brief halt-finalize semantics (`zplan_cost_gate_halt_finalize`) before any claim release or registry deregister.

This detail is specific to `/z-plan`; the other hard-gate skills (`z-research`, `z-uplift`, `z-plan-split`) use the simpler proceed/change-dispatch/abandon shape described in the `cost_gate_decision` event section below.

## The `cost_gate_decision` event (general shape)

All gates (hard and soft) emit exactly one `cost_gate_decision` event per invocation. The canonical fields common to every command are:

```json
{
  "kind":             "cost_gate_decision",
  "run":              "<RUN_ID>",
  "command":          "z-research",
  "choice":           "proceed | auto_proceed | change_dispatch | abandon | halt | interrupted",
  "estimated_tokens": 5200000,
  "confidence":       "medium",
  "basis":            "static profile + terrain/MAP dispatch (`map` key; /z-explore --depth=deep) + brainstorm dispatch"
}
```

`/z-plan` extends this shape with `disposition`, `rule_id`, `range_high`, `choice_source`, `attempt_count`, and optional `reason` — see the detailed contract above.

`choice` values:

| Value | Meaning |
|-------|---------|
| `proceed` | User confirmed at AskUser (hard gate) |
| `auto_proceed` | Gate auto-proceeded (soft gate, or `workflow.pre_run_cost_gate=auto_proceed`, or within budget) |
| `change_dispatch` | User chose to change dispatch parameters (z-research loop-back) |
| `abandon` | User abandoned at AskUser, or `halt` disposition, or loop-back cap exceeded |
| `halt` | Automatic halt (overnight/policy mode) |
| `interrupted` | Driver wait was cancelled/unknown; treated as terminal halt |

The event is logged AFTER `run_start` so it attributes to the run. An abandoned gate (`choice: abandon`) causes the empirical tier to exclude that run from future estimates.

`/z-stats` reads `cost_gate_decision` events for the read-only cost-gate decisions rollup (command, choice, estimated_tokens).

## z-research loop-back behavior

`/z-research` has a 3-loop-back cap on "change dispatch" (distinct from `/z-plan`'s 2-attempt reduction cap — the two commands do not share a loop-back counter). When the user chooses to change dispatch parameters at the cost gate:

1. `cost_gate_decision{choice: change_dispatch}` is logged.
2. The loop-back counter increments.
3. Control returns to Phase 0 (dispatch decision) for the user to update `--dispatch` flags.
4. On Phase 0.5 re-entry, the gate is re-invoked with the updated `--dispatch` flags (estimate recomputes).
5. If `COST_GATE_LOOPBACKS > 3`, the gate falls through to Abandon regardless of user choice.

## Telemetry and calibration

The empirical tier reads the same `metrics.jsonl` that `z-stats` uses. Events land in the repo-wide external base (resolved via `plan-path.sh base_dir`). Each run that completes normally produces a data point for future estimates. Over time, empirical p50/p90 values converge toward actual usage patterns, and the static floor clamp ensures early low-data estimates do not pull the ceiling below the known profile minimum.

The `cost_gate_decision` events form a calibration record: `estimated_tokens` vs actual run cost (sum of child token events in the same parent-run bucket) can be compared post-run via `/z-stats subagent-costs` to assess profile accuracy.

## How it interacts with others

- `config` — `_resolve_cost_gate` (`scripts/config.py:3274`) is the single authority for cost-gate disposition; `pre-run-cost-gate.sh` delegates to it via `check-no-ask`; `cost.token_budget` and `workflow.pre_run_cost_gate` are both defined in `config.py` DEFAULTS
- `scripts` — `estimate-tokens.py` and `pre-run-cost-gate.sh` live in `scripts/`; these scripts share no state beyond subprocess invocation and archived JSON artifacts
- `artifact-scout` — hard-gated skills (`z-plan`, `z-research`, `z-uplift`, `z-plan-split`) run Artifact Scout's deterministic inventory pre-gate and the classifier Agent post-gate; that mechanism has its own concept doc; this concept only owns the invariant that no Agent may dispatch before the hard gate resolves
- `skills` — seven skills (`z-research`, `z-uplift`, `z-plan-split`, `z-plan`, `z-brainstorm`, `z-audit`, `z-debug`) call `pre-run-cost-gate.sh` and own AskUser + `cost_gate_decision` event logging
- `subagent-telemetry` — `estimate-tokens.py subagent-costs` reads `subagent_call` events to produce the cost model output consumed by `/z-stats`

## Edge cases / gotchas

- `cost.token_budget` string env values (e.g. `Z_HARNESS_COST_TOKEN_BUDGET="5000000"`) are coerced to int by `_COERCERS`. If coercion fails, `config.py` exits 2 (hard fail, not soft warn).
- `workflow.pre_run_cost_gate = halt` in TOML will halt ALL hard-gate commands unconditionally, including interactive sessions. Use only for CI or specialized environments.
- `--range-high` missing (estimator unavailable) causes the cost-gate delegation path to return `ask` in interactive mode and `halt` in overnight mode (`rule_id: cost_estimate_missing`). It never silently auto-proceeds.
- `budget <= 0` is invalid config (validator should catch it at write time); the `within_budget` comparison also guards against it with `rule_id: cost_budget_invalid`.
- The no-profile envelope produced by `_no_profile_envelope()` returns `range_high: 0`; the gate fallback envelope (when the estimator binary is unavailable) returns `range_high: null`. These are distinct cases.
- In benchmark/policy mode (`_is_policy_mode()` returns true), when the overnight allowlist does not positively resolve the gate and `range_high > budget`, the gate returns `unhandled_gate` (loud abort) rather than `halt`. This is intentional: an unresolved reachable gate in a benchmark policy is a test bug, not a legitimate halt.
- The `brainstorm` multiplier in the z-research profile assumes a non-HEAVY brainstorm sub-run. A HEAVY brainstorm sub-run has a higher cost; there is no per-invocation budget override (change-dispatch is the lever).
- `/z-plan`'s bounded reduction loop (`ZPLAN_COST_REESTIMATE_MAX=2`) is separate from `/z-research`'s 3-loop-back cap; do not conflate the two counters or their event shapes (`cost_gate_reestimate_attempt` vs repeated `change_dispatch` choices).
- `/z-plan` reduction is only offered in `PLANNING_MODE=intent`; legacy `planning_mode=full` has no reduction option (users must abandon and rerun with an explicit flag/config for a different mode).
- Soft gates fire only on the HEAVY classification path for `/z-brainstorm` and `/z-audit`. LIGHT/MEDIUM runs skip the gate entirely.
- The `/z-brainstorm` wide-mode conversational gate (Phase 2c, WIDE_N > 3) is a separate prose inline estimate — NOT backed by `pre-run-cost-gate.sh`.
- The `cost_gate_decision` event replaces any legacy per-command cost-gate event names. Do not emit command-specific variants.
- `_KIND_TO_COMMAND` maps generic `run_start`/`run_end` to `z-plan` as a best-effort default for legacy pre-T001 events; if pre-T001 z-research events appear in the tail window, attribution will be wrong for those runs only.
- `/z-plan` dispatch defaults are fail-closed because route/depth/doc/explore/consult fan-out may not be fully known before the gate.
- `zplan_cost_gate_halt_finalize` (inside `skills/z-plan/SKILL.md`) invokes `scripts/render-cost-summary.py` to render a cost summary from `events.jsonl` on halt; that renderer is a separate script outside this concept's tracked source files but is directly wired into the `/z-plan` cost-gate halt path.
- `subagent-costs` pricing rates are approximate for native Claude subagents (chars/4 → tokens); only external CLIs that print a usage line produce `provider_input_tokens` / `provider_output_tokens` for exact accounting.
- The `_default_metrics_path()` function resolves the external base via `bash scripts/plan-path.sh base_dir` (subprocess, 10s timeout). If this fails, it falls back to the legacy in-repo `z-harness/metrics.jsonl` path. `Z_HARNESS_BASE_DIR` env override is the reliable escape hatch.
