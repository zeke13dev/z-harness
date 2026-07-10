# config

> Last updated: 2026-07-09
> Covers source: scripts/config.py, scripts/config.sh, scripts/propose-prefs.py, runtime/dispatch/dispatcher.py, docs/human/config.md

## Overview

`config` is the unified z-harness configuration system. It has two semantic surfaces:

- **Loader API** — the 4-layer TOML config loader (built-in defaults → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars). Subcommands: `get`, `get-batch`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `inspect-all`, `resolve-halt-category`. This is the slice-1 foundation.
- **Workflow Resolver** — the `[workflow]` config section plus the question-registry, resolver, writer, elevation proposer, and overnight gate system that sit on top of the loader. Subcommands: `resolve-question`, `check-no-ask`, `set`, `list-question-ids`. This is the slice-2 layer.

The core runtime loop for workflow preferences is: skill prose calls `config.py resolve-question <question_id>` before firing an `AskUserQuestion`; the resolver consults the TOML config, `routing-preference` memory entries in `docs/llm/*.json`, and (at the lowest tier) graph-validated axioms from `axiom-store.py`, then returns a typed JSON envelope instructing the skill to `skip`, `prefill`, `ask`, `halt`, or `defer-to-sink`. When running unattended (`Z_HARNESS_NO_ASK=halt`), the overnight gate either auto-decides questions on the allowlist or halts instead of asking. When the user wants to make a preference permanent they run `/z-suggest-memory` (memory path) or `config.py set` (TOML path). The proposer (`propose-prefs.py`) surfaces an invitation to do so when it detects a repeated command-pair pattern in `metrics.jsonl`.

Historical note: this concept was previously split as `config-design` (Loader API) + `config` (Workflow Resolver) in docs/llm/INDEX.json. They were merged on 2026-05-27 because they shared all source files and the split caused doc-fetcher to fire both concepts on every touch. The two h2 section groupings below preserve the boundary for human readers.

---

# Loader API

The slice-1 foundation: 4-layer TOML config loader, env transliteration, and the read-only subcommands that consult it.

## File locations

| Priority | Path | Wins on |
|----------|------|---------|
| 1 — built-in defaults | (in `scripts/config.py`) | Any key not set elsewhere |
| 2 — user-global (lower) | `~/.config/z-harness/config.toml` | All keys present in this file |
| 3 — repo-local (higher) | `<git-root>/.z-harness/config.toml` | Any key present in this file |
| 4 — env override (highest) | `Z_HARNESS_<SECTION>_<KEY>` | Any key with a matching, non-empty env var |

Per-key shadowing — repo overrides global; env overrides both.  Missing files at layers 2/3 are silently skipped (no error).

Set `$Z_HARNESS_REPO_CONFIG` to override the git-root discovery path (exits 2 if the path does not exist).  Run `scripts/config.sh ensure-defaults` once after install to create the user-global file with defaults and inline comments.

## Preference env vars — use config.toml instead

**Do not set preferences via raw `Z_HARNESS_*` env vars.** The env layer (layer 4) is deprecated for preference-class vars. Set preferences in `config.toml` instead. The three legal roles for env vars are:

1. **Plumbing** — per-run session/path identifiers set by the orchestrator (e.g. `Z_HARNESS_PLAN_DIR`, `Z_HARNESS_SLUG`, `Z_HARNESS_SESSION_ID`, `Z_HARNESS_RUN`). These are per-invocation and cannot be static config — they stay env-only.
2. **Unattended/CI** — autonomy gate flags for overnight or CI runs (e.g. `Z_HARNESS_NO_ASK`, `Z_HARNESS_ASK_ALL`, `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE`, `Z_HARNESS_CLAIM_*`). These control policy, not user preferences — they stay env-only.
3. **Internal-transport** — env vars emitted by `config.py export-env` within a single shell session to transport resolved TOML values to downstream shell code. These are set by `export-env`, not by the user directly.

All other `Z_HARNESS_*` env vars that used to be user-settable preferences are now config keys in `config.toml`.

### Migration note (overnight / CI)

Instead of setting `Z_HARNESS_PRE_REVIEW=true` in your CI environment, set it in the repo-local config:

```toml
# .z-harness/config.toml
[runtime]
pre_review = true
```

For unattended runs that previously relied on env vars:

```bash
# Old (deprecated): set preferences via env
export Z_HARNESS_MAX_PARALLEL=4
export Z_HARNESS_MAX_ATTEMPTS=3

# New: set preferences in config.toml (committed to repo)
# [runtime]
# max_parallel = 4
# max_attempts = 3
```

> **`runtime.max_parallel` is vestigial** (see the note under the alias table below and
> under `workflow.intent_parallel_levels`) — the example above is retained only to show
> the env→TOML migration shape; setting `max_parallel` has no effect on concurrency.
> `runtime.max_attempts` is unaffected and still live.

Run `scripts/config.sh ensure-defaults` once to create your user-global config file with defaults and inline comments. Then migrate each preference from env to TOML.

### Deprecation enforcement: `runtime.env_strict`

When `runtime.env_strict = true` is set in `config.toml`, detecting any preference-class env var in the raw environment becomes a **hard error** (exit 2) rather than a warning. This lets CI pipelines enforce the migration:

```toml
# .z-harness/config.toml (repo-local — committed to repo)
[runtime]
env_strict = true  # enforce: no Z_HARNESS_* preference vars in CI
```

Default is `false` (warnings only — grace period). This key is a **config key** — it cannot be set via a raw env var (doing so would create a bootstrap paradox).

### Full raw → dotted mapping table

All preference env vars and their config.toml equivalents:

| Raw env var (deprecated) | TOML dotted key | Section | Type | Default |
|--------------------------|-----------------|---------|------|---------|
| `Z_HARNESS_NOTIFY` (legacy ingress-only) | `notify.level` | `[notify]` | string | `approval_only` |
| `Z_HARNESS_NOTIFY_LEVEL` | `notify.level` | `[notify]` | string | `approval_only` |
| `Z_HARNESS_CONSULT` | `runtime.consult` | `[runtime]` | string | `on` |
| `Z_HARNESS_PRE_REVIEW` | `runtime.pre_review` | `[runtime]` | bool | `false` |
| `Z_HARNESS_RUNTIME_PRE_REVIEW` | `runtime.pre_review` | `[runtime]` | bool | `false` |
| `Z_HARNESS_IMPL_PRE_REVIEW` | `runtime.impl_pre_review` | `[runtime]` | bool | `false` |
| `Z_HARNESS_RUNTIME_IMPL_PRE_REVIEW` | `runtime.impl_pre_review` | `[runtime]` | bool | `false` |
| `Z_HARNESS_AUTO_WAIT` | `runtime.auto_wait` | `[runtime]` | bool | `true` |
| `Z_HARNESS_RUNTIME_AUTO_WAIT` | `runtime.auto_wait` | `[runtime]` | bool | `true` |
| `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` | `runtime.auto_wait_budget_secs` | `[runtime]` | int | `300` |
| `Z_HARNESS_RUNTIME_AUTO_WAIT_BUDGET_SECS` | `runtime.auto_wait_budget_secs` | `[runtime]` | int | `300` |
| `Z_HARNESS_PAUSE_AT_PCT` | `runtime.pause_at_pct` | `[runtime]` | int | `85` |
| `Z_HARNESS_RUNTIME_PAUSE_AT_PCT` | `runtime.pause_at_pct` | `[runtime]` | int | `85` |
| `Z_HARNESS_EXPLAIN_RESOLUTION` | `runtime.explain_resolution` | `[runtime]` | bool | `false` |
| `Z_HARNESS_RUNTIME_EXPLAIN_RESOLUTION` | `runtime.explain_resolution` | `[runtime]` | bool | `false` |
| `HERMES_MAX_PARALLEL` | `runtime.max_parallel` | `[runtime]` | int | `1` |
| `Z_HARNESS_RUNTIME_MAX_PARALLEL` | `runtime.max_parallel` | `[runtime]` | int | `1` |
| `Z_HARNESS_MAX_PARALLEL_PLANS` | `runtime.max_parallel_plans` | `[runtime]` | int | `1` |
| `Z_HARNESS_RUNTIME_MAX_PARALLEL_PLANS` | `runtime.max_parallel_plans` | `[runtime]` | int | `1` |
| `Z_HARNESS_MAX_ATTEMPTS` | `runtime.max_attempts` | `[runtime]` | int | `2` |
| `Z_HARNESS_RUNTIME_MAX_ATTEMPTS` | `runtime.max_attempts` | `[runtime]` | int | `2` |
| `Z_HARNESS_MAX_TASK_WALL_MS` | `runtime.max_task_wall_ms` | `[runtime]` | int | `2700000` |
| `Z_HARNESS_RUNTIME_MAX_TASK_WALL_MS` | `runtime.max_task_wall_ms` | `[runtime]` | int | `2700000` |
| `Z_HARNESS_MAX_EXPLORE` | `workflow.max_explore` | `[workflow]` | int | `3` |
| `Z_HARNESS_WORKFLOW_MAX_EXPLORE` | `workflow.max_explore` | `[workflow]` | int | `3` |
| `Z_HARNESS_PARALLEL` | `workflow.parallel` | `[workflow]` | int | `3` |
| `Z_HARNESS_WORKFLOW_PARALLEL` | `workflow.parallel` | `[workflow]` | int | `3` |
| `Z_HARNESS_MEMORY_STALE_DAYS` | `workflow.memory_stale_days` | `[workflow]` | int | `547` |
| `Z_HARNESS_WORKFLOW_MEMORY_STALE_DAYS` | `workflow.memory_stale_days` | `[workflow]` | int | `547` |
| `Z_HARNESS_DOC_STALENESS_THRESHOLD` | `docs.staleness_threshold` | `[docs]` | int | `20` |
| `Z_HARNESS_DOCS_STALENESS_THRESHOLD` | `docs.staleness_threshold` | `[docs]` | int | `20` |
| `Z_HARNESS_AXIOM_EXTRACT` | `axioms.auto_extract_post_run` | `[axioms]` | bool | `true` |
| `Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN` | `axioms.auto_extract_post_run` | `[axioms]` | bool | `true` |
| `Z_HARNESS_BRAINSTORM_PERSONAS` | `brainstorm.personas` | `[brainstorm]` | bool | `true` |
| `Z_HARNESS_BRAINSTORM_WIDE_OVERFLOW_MODEL` | `brainstorm.wide_overflow_model` | `[brainstorm]` | string | `haiku` |
| `Z_HARNESS_PERSONAS_CRITIQUE_PANEL` | `personas.critique_panel` | `[personas]` | bool | `true` |
| `Z_HARNESS_PERSONAS_AUDIT` | `personas.audit` | `[personas]` | bool | `true` |
| `Z_HARNESS_PERSONAS_REVIEW_EVAL` | `personas.review_eval` | `[personas]` | bool | `true` |
| `Z_HARNESS_PERSONAS_CONSULT_EVAL` | `personas.consult_eval` | `[personas]` | bool | `false` |
| `Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY` | `personas.implementer_retry` | `[personas]` | string | `same` |
| `Z_HARNESS_EXPERIMENT_PERSONA_ROTATION` | `experiment.persona_rotation` | `[experiment]` | bool | `true` |
| `Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N` | `experiment.control_every_n` | `[experiment]` | int | `5` |
| `Z_HARNESS_COST_TOKEN_BUDGET` | `cost.token_budget` | `[cost]` | int\|null | `null` |

> Tip: `config.py inspect-all` shows every knob with its current source (`defaults`, `global`, `repo`, or `env:<VAR>`). Check it to verify your migration.

---

## The knobs (Loader API)

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `notify.level` | string | `approval_only` | `off` \| `approval_only` \| `all` | Controls when PushNotification fires. `off` silences all notifications. `approval_only` notifies on `approval` and `error` events. `all` notifies on every `approval`, `phase_end`, and `error` event. |
| `notify.discord_webhook_url` | string | `""` | any Discord webhook URL | Discord webhook URL for notification delivery. Empty string (default) disables Discord notifications entirely. When set and `notify.level` permits, `should-notify --channel discord` returns `yes`. The webhook URL is a secret and must not be committed — `.gitignore` already protects `.z-harness/` where config lives. |
| `docs.always_apply` | string | `always` | `always` \| `never` | Whether light flows auto-dispatch doc-fetcher when `docs/llm/INDEX.json` exists. `always` matches current /z-do default behavior. `never` skips doc-fetcher. **Applies only to light flows (slice 1: /z-do). Heavy flows always dispatch doc-fetcher regardless of this knob.** |
| `runtime.consult` | string | `on` | `on` \| `off` | Single-model mode. When `off`, the `consultant_primary`, `consultant_secondary`, and `reviewer` roles resolve to the `none` sentinel, so cross-LLM consultation and review are skipped (no Gemini/Codex dispatch). Exported as `Z_HARNESS_CONSULT` (not `Z_HARNESS_RUNTIME_CONSULT` — see the transliteration note), which `resolve-provider.py` reads. |
| `cost.token_budget` | int or null | `null` | positive int or null | Token budget ceiling for cost-gate delegation. When set, `check-no-ask` with `--range-high` compares the estimate against this value. `null` (unset) means no budget is configured; under an unattended hard cost gate (`Z_HARNESS_NO_ASK=halt`), the gate halts with `cost_budget_missing`. |
| `runtime.env_strict` | bool | `false` | `true` \| `false` | When `true`, detecting any preference-class `Z_HARNESS_*` env var in the raw environment becomes a **hard error** (exit 2) instead of a warning. Set this in `config.toml` (NOT as a raw env var) to enforce the migration in CI. Default `false` (grace period — warning only). |

For `[brainstorm]`, `[personas]`, `[workflow]`, `[followup]`, `[axioms]`, `[experiment]`, `[changelog]`, `[models]`, `[model_classes]`, `[model_routing]`, and `[export]` knobs, see the sections below.

## The transliteration rule

Env-var overrides follow a deterministic rule: lowercase TOML dotted-key → prefix `Z_HARNESS_` + uppercase + `.` to `_`. One key is an explicit alias exception: `runtime.consult` exports as `Z_HARNESS_CONSULT` (the legacy name `resolve-provider.py` reads), not the mechanical `Z_HARNESS_RUNTIME_CONSULT`.

| TOML key | Env var |
|----------|---------|
| `notify.level` | `Z_HARNESS_NOTIFY_LEVEL` |
| `notify.discord_webhook_url` | `Z_HARNESS_NOTIFY_DISCORD_WEBHOOK_URL` |
| `docs.always_apply` | `Z_HARNESS_DOCS_ALWAYS_APPLY` |
| `brainstorm.personas` | `Z_HARNESS_BRAINSTORM_PERSONAS` |
| `brainstorm.wide_overflow_model` | `Z_HARNESS_BRAINSTORM_WIDE_OVERFLOW_MODEL` |
| `personas.critique_panel` | `Z_HARNESS_PERSONAS_CRITIQUE_PANEL` |
| `personas.audit` | `Z_HARNESS_PERSONAS_AUDIT` |
| `personas.review_eval` | `Z_HARNESS_PERSONAS_REVIEW_EVAL` |
| `personas.consult_eval` | `Z_HARNESS_PERSONAS_CONSULT_EVAL` |
| `personas.implementer_retry` | `Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY` |
| `experiment.persona_rotation` | `Z_HARNESS_EXPERIMENT_PERSONA_ROTATION` |
| `experiment.control_every_n` | `Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N` |
| `axioms.enabled` | `Z_HARNESS_AXIOMS_ENABLED` |
| `axioms.kernel_budget_chars` | `Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS` |
| `axioms.extract_min_recurrence` | `Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE` |
| `axioms.auto_extract_post_run` | `Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN` |
| `cost.token_budget` | `Z_HARNESS_COST_TOKEN_BUDGET` |
| `runtime.consult` | `Z_HARNESS_CONSULT` (alias — **not** the mechanical `Z_HARNESS_RUNTIME_CONSULT`) |
| `runtime.pre_review` | `Z_HARNESS_PRE_REVIEW` (alias — legacy name; mechanical: `Z_HARNESS_RUNTIME_PRE_REVIEW`) |
| `runtime.impl_pre_review` | `Z_HARNESS_IMPL_PRE_REVIEW` (alias — legacy name; mechanical: `Z_HARNESS_RUNTIME_IMPL_PRE_REVIEW`) |
| `runtime.auto_wait` | `Z_HARNESS_AUTO_WAIT` (alias — legacy name; mechanical: `Z_HARNESS_RUNTIME_AUTO_WAIT`) |
| `runtime.auto_wait_budget_secs` | `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` (alias — legacy name) |
| `runtime.pause_at_pct` | `Z_HARNESS_PAUSE_AT_PCT` (alias — legacy name; mechanical: `Z_HARNESS_RUNTIME_PAUSE_AT_PCT`) |
| `runtime.explain_resolution` | `Z_HARNESS_EXPLAIN_RESOLUTION` (alias — legacy name) |
| `runtime.max_parallel` | `HERMES_MAX_PARALLEL` (alias — uses `HERMES_` prefix, not `Z_HARNESS_RUNTIME_`) — **vestigial, no effect** (see note below the alias table) |
| `runtime.max_parallel_plans` | `Z_HARNESS_MAX_PARALLEL_PLANS` (alias — no `RUNTIME_` infix) — **vestigial, no effect** (see note below the alias table) |
| `runtime.max_attempts` | `Z_HARNESS_MAX_ATTEMPTS` (alias — no `RUNTIME_` infix) |
| `runtime.max_task_wall_ms` | `Z_HARNESS_MAX_TASK_WALL_MS` (alias — no `RUNTIME_` infix) |
| `runtime.env_strict` | `Z_HARNESS_RUNTIME_ENV_STRICT` (mechanical — **not user-settable via env**; use config.toml only) |
| `workflow.planning_mode` | `Z_HARNESS_WORKFLOW_PLANNING_MODE` |
| `workflow.intent_level` | `Z_HARNESS_WORKFLOW_INTENT_LEVEL` |
| `workflow.intent_parallel_levels` | `Z_HARNESS_WORKFLOW_INTENT_PARALLEL_LEVELS` |
| `workflow.hermes_enabled` | `Z_HARNESS_WORKFLOW_HERMES_ENABLED` |
| `workflow.max_explore` | `Z_HARNESS_MAX_EXPLORE` (alias — no `WORKFLOW_` prefix) |
| `workflow.parallel` | `Z_HARNESS_PARALLEL` (alias — no `WORKFLOW_` prefix) |
| `workflow.memory_stale_days` | `Z_HARNESS_MEMORY_STALE_DAYS` (alias — no `WORKFLOW_` prefix) |
| `docs.staleness_threshold` | `Z_HARNESS_DOC_STALENESS_THRESHOLD` (alias — uses `DOC` not `DOCS`) |
| `axioms.auto_extract_post_run` | `Z_HARNESS_AXIOM_EXTRACT` (alias — completely different legacy name) |
| `models.consultant_primary` | `Z_HARNESS_MODELS_CONSULTANT_PRIMARY` |
| `models.consultant_secondary` | `Z_HARNESS_MODELS_CONSULTANT_SECONDARY` |
| `models.reviewer` | `Z_HARNESS_MODELS_REVIEWER` |
| `models.implementer` | `Z_HARNESS_MODELS_IMPLEMENTER` |
| `models.pre_reviewer` | `Z_HARNESS_MODELS_PRE_REVIEWER` |
| `export.hosts` | `Z_HARNESS_EXPORT_HOSTS` (JSON-encoded array string) |
| `export.strategy` | `Z_HARNESS_EXPORT_STRATEGY` |

> **`runtime.max_parallel` / `runtime.max_parallel_plans` / `HERMES_MAX_PARALLEL` are vestigial.**
> They are defined, TOML-validated, and env-aliased in `scripts/config.py`, but no
> dispatch path in `scripts/`, `skills/`, or `runtime/` ever reads them — setting either key
> (or the `HERMES_MAX_PARALLEL` / `Z_HARNESS_MAX_PARALLEL_PLANS` env aliases) has **no effect**
> on run concurrency. The real within-level concurrency lever is
> `workflow.intent_parallel_levels` (see below) plus the `workstreams.json` DAG; see
> [`docs/human/hermes-orchestration.md`](hermes-orchestration.md) for the separate,
> `workflow.hermes_enabled`-gated Hermes cross-worktree concurrency machinery, which uses
> its own unrelated `hermes-config.yaml` `[concurrency]` keys.

For followup and experiment keys, the rule applies identically (no alias exceptions).
Three- and four-level model-class and model-routing keys, such as `model_classes.local_fast.model`,
`model_classes.deep.claude.effort`, and `model_routing.native_agents.explore`, are config-file-only
and are not exported as env vars.

Keys must match 2-4 lowercase underscore/digit segments (for example `notify.level`,
`model_classes.local_fast.model`, or `roles.z_plan.consultant_primary.model`). Hyphens exit 2.
Empty env vars are treated as missing.

## CLI reference (Loader API)

All subcommands available via `scripts/config.sh <sub>` (bash wrapper) or `python3 scripts/config.py <sub>`.

### `get <dotted.key>`

Prints the effective value for one key (no quotes).  Unknown or meta keys exit 3.

```
$ scripts/config.sh get notify.level       → approval_only
$ scripts/config.sh get personas.consult_eval  → false
```

### `get-batch <key1> [key2 ...]`

Resolves multiple config keys in a **single process** (one config load) and prints a JSON object mapping each key to its resolved value. Designed to replace N sequential `get` forks when multiple values are needed at once.

- Unknown keys: included in output as `null`; warning emitted to stderr.
- Meta keys (e.g. `schema_version`): included in output as `null`; warning emitted to stderr.
- Always exits 0 (best-effort; callers fall back to defaults for `null` values).

```
$ scripts/config.sh get-batch personas.critique_panel personas.consult_eval
{"personas.critique_panel": true, "personas.consult_eval": false}
```

### `export-env`

Prints `export Z_HARNESS_<KEY>=<value>` lines for all user knobs.
Designed for `eval "$(scripts/config.sh export-env)"`.  Emits `config_resolved`
event once per `$Z_HARNESS_RUN`.

```
export Z_HARNESS_BRAINSTORM_PERSONAS='true'
export Z_HARNESS_PERSONAS_AUDIT='true'
export Z_HARNESS_PERSONAS_CONSULT_EVAL='false'
export Z_HARNESS_PERSONAS_CRITIQUE_PANEL='true'
export Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY='same'
export Z_HARNESS_PERSONAS_REVIEW_EVAL='true'
```

### `ensure-defaults`

Writes the user-global config with defaults + inline comments if absent.
Idempotent — prints `exists <path>` if already present.  Exits 4 if the file
exists but is empty or unparseable (never silently overwrites).

### `explain <dotted.key>`

Prints the effective value and its source layer.

```
$ scripts/config.sh explain personas.consult_eval
personas.consult_eval = "false"   (source: defaults)

$ Z_HARNESS_PERSONAS_CONSULT_EVAL=true scripts/config.sh explain personas.consult_eval
personas.consult_eval = "true"   (source: env Z_HARNESS_PERSONAS_CONSULT_EVAL)
```

### `should-notify --event <kind>`

Prints `yes` or `no`; always exits 0 (safe for `set -e`).  Unknown event → exit 2.
Valid event kinds: `approval`, `phase_end`, `error`.

### `resolve-halt-category <question_id>`

Prints the `halt_category` tag for a registered question ID (`decision`, `risk`, `shortcut`, `archiving`, `mechanical_proceed`), or `ask` (fail-safe) for unknown IDs. Exit 0 always. Used by `scripts/lint-halt-categories.sh` and `chain-runner.sh` to drive the attend gate policy.

### `inspect-all [--json]`

Prints all configuration knobs with their current effective value, source layer, and persistence class. Covers three categories:

1. **TOML-persistent keys** — every key in `DEFAULTS` (all `notify.*`, `docs.*`, `brainstorm.*`, `personas.*`, `workflow.*`, `followup.*`, `axioms.*`, `experiment.*`, `runtime.*`, `cost.*`, `models.*`, `export.*`, `changelog.*`)
2. **Registered question_ids** — every entry in `QUESTION_IDS`, showing the resolver envelope result
3. **Env-only knobs** — environment variables that affect behavior but are never written to TOML

**Env-only knobs** surfaced by `inspect-all` (not settable via TOML):

| Env var | Description |
|---------|-------------|
| `Z_HARNESS_NO_ASK` | Set to `halt` to activate overnight/unattended mode |
| `Z_HARNESS_OVERNIGHT_AUTODECIDE` | Legacy; see `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` |
| `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` | JSON object `{question_id: value}` merged over default allowlist |
| `Z_HARNESS_PAUSE_AT_PCT` | Pause gate percentage threshold |
| `Z_HARNESS_PARALLEL` | Parallel execution flag |
| `Z_HARNESS_ASK_ALL` | Set to `1` to force all questions to ask; mutually exclusive with `Z_HARNESS_NO_ASK=halt` |
| `Z_HARNESS_NOTIFY` | Notification override |
| `Z_HARNESS_REPO_PROVIDERS` | Repo-level provider overrides |
| `Z_HARNESS_PLANS_DIR` | Override plans directory path |
| `Z_HARNESS_EXPLAIN_RESOLUTION` | Set to `1` to print resolution trace on stderr (same as `--explain`) |
| `Z_HARNESS_MAX_EXPLORE` | Maximum explore depth |
| `Z_HARNESS_IMPL_PRE_REVIEW` | Set to `1` to enable the opt-in Flash pre-reviewer gate-down at the per-task implement gate in `/z-execute`. **Default `0` (off); ships inert.** When on: runs a DeepSeek Flash pre-reviewer on low-tier tasks before codex; CLEAN verdict skips codex (emits `review_gated_down`); flagged verdict escalates to codex with Flash findings prepended. Includes a tier-drift re-check via `complexity-classifier` (strips cached `**Complexity:**` stamp). **Cost-inversion caveat:** Flash-on-all + codex-on-subset can invert total cost vs codex-on-all. Enable only after reviewing `scripts/audit-preview-misses.sh` results. Undocumented-as-recommended until the evidence gate demonstrates acceptable Flash false-negative rate. See `docs/human/impl-pre-review.md`. |

---

## Base-dir + registry env knobs (active-plan-coordination)

These env vars govern the external artifact base and the active-plan registry. They are **env-only** (not TOML keys) and take effect in `scripts/plan-path.sh` and `scripts/active-plan-registry.py`. They are NOT in `config.py`'s `DEFAULTS` or `VALIDATORS`, and `export-env` does NOT emit them. `inspect-all` surfaces them under the env-only category for discoverability.

For a full design reference including the registry layout, lease mechanics, overlap protocol, and migration guide, see `docs/human/active-plan-registry.md`.

### Base and registry knobs

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_EXTERNAL_DEFAULT` | `1` (on after Phase-D flip) | Controls whether tiers 2–4 of the base fallback chain are active. **Unset or `1`**: external resolution is active (XDG → HOME/.local/state → .git/z-harness → pwd). **`0`**: opt-out — forces old in-repo `$(pwd)/z-harness` behavior (tier 5 only). Revert to in-repo base without this knob: `Z_HARNESS_BASE_DIR=$(pwd)/z-harness`. |
| `Z_HARNESS_BASE_DIR` | _(unset)_ | Explicit absolute override for the artifact base directory. When set, this is a TRUE ESCAPE HATCH: bypasses the anchor entirely (no read/validate/write of `.z-harness-base`). Must be an absolute path; non-absolute → hard error. The caller owns consistency when using this override. |
| `Z_HARNESS_REGISTRY_ENABLED` | `1` (on) | Set to `0` to disable the active-plan registry. When `0`, the following subcommands become silent no-ops: `register`, `heartbeat`, `update-scope`, `overlaps`, `reap`, `deregister`, `claim`, `release`, `wait-for`. The read-only `list` and `session-id` subcommands are still allowed. Use in CI environments where no registry coordination is needed. |
| `Z_HARNESS_REGISTRY_STALE_SECS` | `1800` | Number of seconds after which a run's `last_heartbeat` timestamp is considered stale. Reaper behavior: (a) dead local pid → delete immediately; (b) past 2× margin AND not a live local pid → delete; (c) live local pid past 2× margin → mark `status:"stale"` only (carve-out); (d) remote/unknown host at 1× → mark stale. |
| `Z_HARNESS_STRICT_OVERLAP` | _(unset / off)_ | Set to `1` to enable blocking-overlap mode in `active-plan-registry.py overlaps`. When active, an `explicit`×`explicit` exact scope-path match between two live runs causes exit code `20` (blocking), which `/z-execute` treats as a hard halt requiring user resolution. By default (unset) scope overlaps are advisory only (exit `10`). Does NOT affect held-path conflict behavior. |

### Wait / lease knobs (cross-session-plan-coord plan)

These five knobs control the per-file lease and wait-for poll loop added by the cross-session-plan-coord plan. Like the five base/registry knobs above, they are **env-only** — read directly from `os.environ` in `active-plan-registry.py` with module-level defaults. Do NOT register them in `config.py`.

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_AUTO_WAIT` | `1` | `1` = when `claim` concedes a path to a senior peer, automatically park the run via `wait-for` using `AUTO_WAIT_BUDGET_SECS`. `0` = restore the interactive proceed/wait/abort menu for held conflicts. |
| `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` | `300` | Wall-clock ceiling (seconds) for auto-park mode. On expiry `wait-for` exits 10 (LOUD `wait_timeout` event). Orchestrator aborts the task or (interactive) prompts proceed/abort. Distinct from `WAIT_TIMEOUT_SECS`. |
| `Z_HARNESS_WAIT_POLL_SECS` | `30` | Seconds between iterations inside the `wait-for` poll loop. Each iteration: single atomic write setting `status=paused` + `waiting_on`, runs `reap`, rechecks targets, scans for new senior holders (TOCTOU). |
| `Z_HARNESS_WAIT_TIMEOUT_SECS` | `1800` | Hard ceiling (seconds) for an explicit interactive wait (user selected "wait" in the overlap menu). Distinct from `AUTO_WAIT_BUDGET_SECS`. |
| `Z_HARNESS_WAIT_REQUIRE_MERGE` | `0` | **Reserved/deferred** — not yet wired. When `1` would make a target "cleared" only when its branch is an ancestor of HEAD (`git merge-base --is-ancestor`). Leave at `0`; the operative cleared signal is deregister-only. |

**Dual budget summary:** `AUTO_WAIT_BUDGET_SECS` (300 s, auto mode) is the short LLM-session ceiling; `WAIT_TIMEOUT_SECS` (1800 s, explicit mode) is the long interactive ceiling. They are independent because interactive users can tolerate longer waits than an unattended orchestrator loop.

### Claim-lock knobs (cross-session-claim-locks plan)

These three knobs control the slug-level hard claim lock added by `/z-plan` and `/z-audit-plan`. Like the knobs above, they are **env-only** — read inline by `scripts/plan-claim.sh` from the environment. They are NOT in `config.py`'s `DEFAULTS` or `VALIDATORS`, and `export-env` does NOT emit them.

For the full claim-lock design reference (contention/takeover policy, heartbeat cadence, exit codes, self-reentry guard, session-id persist+restore, daemon-leak behavior), see `docs/human/plan-claim.md`.

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_CLAIM_TTL_SECS` | `2700` | TTL (seconds) for slug claim liveness. A heartbeat not refreshed within this window causes the next same-slug `acquire` to perform a stale-takeover (exit 2). Lower values shorten the time a dead/crashed session blocks a new one; higher values reduce false-takeover risk during slow operations. |
| `Z_HARNESS_CLAIM_OVERRIDE` | _(unset)_ | Set to `1` to allow an unattended (`Z_HARNESS_NO_ASK`) run to proceed through contention (exit 1), stale-takeover (exit 2), or corrupt lock (exit 3) without aborting. Default-safe: absent or `0` means unattended contention always aborts rather than silently double-working. |
| `Z_HARNESS_CLAIM_DISABLE` | _(unset)_ | Set to `1` to skip all claim locking entirely. Every `plan-claim.sh` subcommand (`acquire`, `heartbeat`, `release`) becomes an immediate exit-0 no-op. Use as an escape hatch (CI, testing, emergency). When disabled, `release` is a **safe no-op** and is not gated on an acquire event having been emitted — callers are always safe to call `release` regardless of this knob. |

**Manual unlock recipe** — if a plan was abandoned abnormally (hard-kill with no resume), clear the stale lock:

```bash
# Find the claims directory
bash scripts/plan-path.sh claims_dir

# Remove lock files for the specific slug
rm <claims_dir>/<slug>.lock <claims_dir>/<slug>.lock.hb.lock
```

Run `plan-claim.sh status --slug <slug>` first to confirm the current holder before removing.

**Post-crash daemon behavior** — the `sink-lock` holder daemon is `setsid`-detached and survives an orchestrator SIGKILL. It holds the flock until its heartbeat ages past `Z_HARNESS_CLAIM_TTL_SECS`, after which the next same-slug `acquire` performs a stale-takeover (exit 2). **Exit-2 is the normal post-crash recovery path**, not a rare edge case. Unattended exit-2 default-aborts (a partial SPEC/PLAN may exist) unless `Z_HARNESS_CLAIM_OVERRIDE=1`.

### Base fallback chain summary

The full base fallback chain (active when `Z_HARNESS_EXTERNAL_DEFAULT` is unset or `1`):

1. `$Z_HARNESS_BASE_DIR` — explicit absolute override (TRUE ESCAPE HATCH; bypasses anchor)
2. `$XDG_STATE_HOME/z-harness/<repo-id>` — if set and writable
3. `$HOME/.local/state/z-harness/<repo-id>` — if `HOME` set and writable
4. `<git-common-dir>/z-harness` — survives `git clean`; writable if `.git/` is writable
5. `$(pwd)/z-harness` — last resort (clean-vulnerable; also the only tier active when `Z_HARNESS_EXTERNAL_DEFAULT=0`)

**Exit code reference (Loader API):**

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Schema/validation error, bad key format, unknown event kind |
| 3 | Unknown dotted-key (`get` / `explain`) |
| 4 | I/O error (`ensure-defaults` edge cases, permission denied) |

## `config_resolved` event

Every time `export-env` runs inside a `/z-*` run, it emits a `config_resolved`
event to `metrics.jsonl` (once per `$Z_HARNESS_RUN`, de-duplicated via an
O_EXCL temp file).

---

# Workflow Resolver

The slice-2 layer: the `[workflow]` config section, the question-registry, the resolver subcommand, the overnight gate system, the writer, the routing-preference memory schema, the axiom layer, and the elevation proposer. All built on top of the Loader API.

## The knobs (Workflow Resolver)

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `workflow.audit_to_amend` | string | `ask` | `ask` \| `amend` \| `stop` | **Source-keyed force-ask override** for `/z-audit-plan` Phase 5 and `/z-review-all` Phase 6.5. The effective behavior depends on the resolver `source`, not just the value: `source=="none"` (no preference stored) → `auto_split` (default: no popup, INTENT-mode batches all spec_gaps into ONE /z-amend call); `source in {config,memory}` with `ask`/`prefill` result → `force_ask` (3-way popup); `halt`/`stop` from any source → `halt`; `amend`/`skip` from any source → `auto_split`. Setting `ask` in config explicitly opts back into the 3-way popup. Decision logic in `scripts/amend-gate-decision.py`. |
| `workflow.slug_confirm` | string | `ask` | `ask` \| `auto_accept` \| `recommend_derived` | Controls the soft non-obvious-slug confirmation at 7 callsites. `ask` always prompts. `auto_accept` silently accepts the derived slug. `recommend_derived` pre-selects the derived slug in the AskUser prompt. **The hard slug-collision check always runs unconditionally, regardless of this setting.** |
| `workflow.implement_all_proceed` | string | `ask` | `ask` \| `auto_resume` \| `halt` | Controls the halt-resolution gate in `/z-execute`. `ask` prompts. `auto_resume` skips the prompt. `halt` stops unconditionally. |
| `workflow.review_all_proceed` | string | `ask` | `ask` \| `proceed` \| `halt` | Controls the Phase 3.7 proceed gate in `/z-review-all`. `ask` prompts. `proceed` skips the prompt. `halt` stops unconditionally. |
| `workflow.plan_decisions_approval` | string | `ask` | `ask` \| `approve` \| `halt` | Controls the Phase 2.5 decisions-doc approval gate in `/z-plan`. `ask` prompts. `approve` skips the prompt. `halt` stops unconditionally. |
| `workflow.pre_run_cost_gate` | string | `ask` | `ask` \| `auto_proceed` \| `halt` | Controls the pre-run cost gate for high-cost commands (z-research, z-uplift, z-plan-split, z-plan). `ask` prompts. `auto_proceed` skips the AskUser prompt after a helper-approved estimate. For hard gates, `pre-run-cost-gate.sh` delegates to `check-no-ask --question-id workflow.pre_run_cost_gate --range-high N --severity hard`; in interactive mode (`Z_HARNESS_NO_ASK` not `halt`) the helper returns `ask`, while unattended mode applies `workflow.pre_run_cost_gate`/allowlist resolution first and then `cost.token_budget` if still unresolved. |
| `workflow.planning_mode` | string | `intent` | `intent` \| `full` | Default planner paradigm for `/z-plan`. `intent` = Adaptive INTENT mode: thin frozen INTENT.md contract + emergent BFS task-tree. `full` = legacy SDD mode: SPEC/PLAN/TASKS up-front. Env: `Z_HARNESS_WORKFLOW_PLANNING_MODE`. |
| `workflow.intent_level` | string | `auto` | `auto` \| `quick` \| `standard` \| `deep` | Forced INTENT level. `auto` = the scope-classifier picks the level. `quick` / `standard` / `deep` force that level unconditionally. Env: `Z_HARNESS_WORKFLOW_INTENT_LEVEL`. |
| `workflow.intent_parallel_levels` | bool | `true` | `true` \| `false` | **The real within-level concurrency lever** for `/z-execute` INTENT mode (not `runtime.max_parallel*` / `HERMES_MAX_PARALLEL`, which are vestigial — see the Loader API alias-table note above). Default-on means "attempt same-level INTENT BFS parallelism only when the `/z-execute` safety preconditions pass": every same-level sibling has precise parseable `**Files:**` scope, no sibling has `scope_unknown=true`, fan-out is bounded or partitioned, and review uses per-task diff isolation or serialized review capture. Missing/unparseable scope, unknown scope, file overlap, or unsafe review capture serializes the affected level/task. Set `false` to opt out and run each INTENT-BFS level strictly one task at a time. No effect in legacy (non-INTENT) mode. Env: `Z_HARNESS_WORKFLOW_INTENT_PARALLEL_LEVELS`. |
| `workflow.hermes_enabled` | bool | `false` | `true` \| `false` | Gates ALL old Hermes parallelism machinery (generate-workstreams.py, cross-cluster dispatch, handoff). Default OFF. Env: `Z_HARNESS_WORKFLOW_HERMES_ENABLED`. |

## CLI reference (Workflow Resolver)

### `resolve-question <question_id> [--scope-slug <slug>] [--explain]`

Returns a typed JSON envelope on stdout indicating how an AskUserQuestion should behave.
Consulted by skill prose before AskUserQuestion fires.  Never writes to config or memory.

`result` values: `skip`, `prefill`, `ask`, `halt`, `defer-to-sink`.
`source` values: `config | memory | axiom | axiom_conflict | conflict | none | override | overnight_allowlist | no_ask_halt`.

Exit codes: 0 (valid JSON), 2 (bad invocation), 3 (unknown question_id; JSON with error key still emitted), 4 (I/O error; JSON still emitted), 5 (config conflict: ASK_ALL=1 + NO_ASK=halt both set).

**Always capture exit code separately.** Never pipe through chains that swallow it. On any non-zero exit, fall through to `ask`.

### `check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]`

Lightweight overnight-gate checker. Returns `{"result": "halt"|"proceed"|"auto_proceed"|"unhandled_gate", "question_id": "<id>", "rule_id": "<rule>"}`. Always exits 0 on valid invocations.

The `--range-high` and `--severity` flags activate cost-gate delegation: `soft` severity always returns `auto_proceed`; `hard` severity under `Z_HARNESS_NO_ASK=halt` applies the budget rule against `cost.token_budget`. For `/z-plan`, unset `cost.token_budget` halts unattended hard gates with `cost_budget_missing`; `range_high <= budget` auto-proceeds, and `range_high > budget` halts or becomes `unhandled_gate` in policy mode.

### `set <dotted.key> <value> [--scope=global|project]`

Atomically writes a TOML key. Validates against `VALIDATORS` before writing. Exits 0 silently on success (no stdout output). Default scope: `project`.

### `list-question-ids`

Prints a JSON array of all known question IDs. Consumed by `/z-suggest-memory --kind routing-preference` for validation.

### `migrate`

Rewrites old provider names in `roles.*.runtime` config values to the new `-cli` suffixed form. Idempotent.

## Overnight gate system

When `Z_HARNESS_NO_ASK=halt`, the resolver applies an additional post-processing pass to every `resolve-question` call. The default allowlist auto-decides `workflow.slug_confirm=recommend_derived` and `workflow.audit_to_amend=amend`. Set `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` to a JSON object to customize the allowlist.

## Axiom layer

The axiom layer sits at the lowest precedence. After config and memory are consulted, `_build_resolve_envelope` loads graph-validated approved axioms. Axiom participation is gated on `axioms.enabled = true` (the default). Three outcomes: **agree** (no change), **gap-fill** (`source:"axiom"`, `strength:"soft"`), **direct conflict** (higher layer wins, `source:"axiom_conflict"`).

## `routing-preference` memory type

Workflow preferences can also live as memory entries in `docs/llm/workflow.json` (global scope) or `docs/llm/workflow-<project-slug>.json` (project scope). The resolver reads these alongside the TOML config with a 5-tier signal-strength model (`weak|strong|very_strong`).

## Elevation proposer

`scripts/propose-prefs.py` walks `metrics.jsonl` for repeated command-pair patterns and surfaces a one-shot AskUserQuestion when the threshold (default 3) is met. Never writes automatically.

---

# Follow-up Namespace

The `[followup]` TOML section controls the follow-up registry (notion-followup-sink). Added in T003 and T017.

## The knobs ([followup] section)

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `followup.default_sink` | string | `project` | `project` \| `global` | Which sink new entries go to when no explicit `--sink=` flag is passed to `sink-add.sh`. |
| `followup.notion_enabled` | bool | `false` | `true` \| `false` | Enable one-way Notion push mirror. When false, Notion sync is skipped entirely. |
| `followup.notion_database_id` | string | `""` | any string | Notion database ID for the follow-up mirror. Required when `notion_enabled=true`. |
| `followup.notion_token_path` | string | `~/.z-harness/secrets.toml` | path | Path to TOML secrets file containing `[notion].token`. Mode 0600 required. Env override: `Z_HARNESS_NOTION_TOKEN` (see below). |
| `followup.auto_close_low_risk_enabled` | bool | `true` | `true` \| `false` | Master kill-switch for the auto-close-low-risk completion path. Defaults to `true` (on). Set to `false` to disable auto-close entirely. |
| `followup.staleness_commit_window` | int | `50` | positive int | Commit distance above which staleness prompt fires at claim time. |
| `followup.staleness_warn_days` | int | `30` | positive int | Age in days after which a soft staleness warning is shown at claim time. |
| `followup.staleness_hard_dismiss_days` | int | `0` | int | Age in days after which entries are auto-dismissed. `0` = disabled (default). |
| `followup.audit_evidence_required_artifacts` | array\<string\> | `["z_review_all_verdict", "test_exit", "cumulative_diff"]` | artifact kinds | Named artifact kinds that must be present in an `audit_evidence.json` blob. |

### `Z_HARNESS_NOTION_TOKEN` — env-only secret

`Z_HARNESS_NOTION_TOKEN` is an **env-only** Notion API token override. It is NOT a TOML config key and does not appear in `DEFAULTS` or `VALIDATORS`. Callers and wrappers of `notion-push.py` **must not run under `set -x`** — doing so would leak the token value into logs.

---

# Common

Cross-cutting material that applies to both surfaces.

## The knobs ([brainstorm] section)

The `[brainstorm]` section contains knobs specific to `/z-brainstorm` behavior. It remains in `[brainstorm]` rather than `[personas]` to avoid churn in existing configs — do NOT move it.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `brainstorm.personas` | bool | `true` | `Z_HARNESS_BRAINSTORM_PERSONAS` | Enable persona injection for ideators in `/z-brainstorm`. When ON, up to 3 distinct `ideator` personas are drawn and positionally prepended. When OFF the dispatch is byte-identical to the pre-feature vendor-only brainstorm. |
| `brainstorm.wide_overflow_model` | string | `"haiku"` | `Z_HARNESS_BRAINSTORM_WIDE_OVERFLOW_MODEL` | Model used for overflow ideators (waves 2+) in wide-mode `/z-brainstorm` runs (N > 3). Accepted values: `"haiku"` (default — uses Haiku for all overflow ideators), `"cheap-mixed"` (reserved — accepted by the validator but acts as a no-op until the per-vendor cheap-model mechanism is verified; see SPEC D1/M2), or any explicit non-empty model string (e.g. `"claude-haiku-4-5"`) to pin a specific model. A prompt-level override always wins over this config value. |

## The knobs ([personas] section)

The `[personas]` section controls per-surface persona dispatch across all z-harness commands. Each boolean knob enables or disables persona injection at one class of dispatch site; disabling a knob is byte-identical to pre-feature behavior at that site.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `personas.critique_panel` | bool | `true` | `Z_HARNESS_PERSONAS_CRITIQUE_PANEL` | Enable persona injection at the z-plan Phase 3 + Phase 7 fixed 5-panel critique arms (DIVERGENT). When ON, 5 distinct `consultant` personas are drawn and positionally prepended. |
| `personas.audit` | bool | `true` | `Z_HARNESS_PERSONAS_AUDIT` | Enable persona injection at z-audit dimension auditors (DIVERGENT). When ON, one distinct `audit_persona` is drawn per dimension (correctness / perf / cleanliness / design). |
| `personas.review_eval` | bool | `true` | `Z_HARNESS_PERSONAS_REVIEW_EVAL` | Enable the advisory persona reviewer at code-review gates — z-execute, z-fix, z-do (CONVERGENT). When ON, one `reviewer`-role persona is dispatched advisory-only alongside the authoritative neutral codex gate. |
| `personas.consult_eval` | bool | `false` | `Z_HARNESS_PERSONAS_CONSULT_EVAL` | Enable the advisory persona consult arm at convergent evaluation sites — z-audit bundled consult (CONVERGENT). **Default OFF** — this is the most expensive and lowest-signal advisory arm. When ON, one additional `consultant`-persona advisory arm is dispatched alongside the neutral consult; its output is logged advisory-only. |
| `personas.implementer_retry` | string | `"same"` | `Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY` | Controls how the implementer persona is handled across retries. `same` (default) — reuse the cycle-1 persona for all retries of the same task. `new` — fresh draw excluding the prior persona on each retry. No effect when `experiment.persona_rotation = false`. |

**Key design constraint:** There is NO `personas.debug` knob — it was removed as dead code. Do not document or implement it.

**TOML example** (`.z-harness/config.toml`):

```toml
[brainstorm]
personas = true
wide_overflow_model = "haiku"  # "haiku" | "cheap-mixed" | explicit model string

[personas]
critique_panel = true
audit = true
review_eval = true
consult_eval = false          # default OFF — most expensive/lowest-signal advisory arm
implementer_retry = "same"    # "same" | "new"
```

**Invariants:**
- All boolean knobs accept `true` or `false` only. Repo/env layer violations exit 2 (hard fail); global layer violations soft-warn and fall back to defaults.
- `personas.implementer_retry` accepts only `"same"` or `"new"`. Any other value is a hard validation failure.
- `personas.consult_eval` defaults OFF. At convergent sites the neutral arm always runs; the persona advisory arm adds overhead with the lowest measured signal gain.
- The neutral-authority invariant applies at all CONVERGENT sites regardless of knob state: the neutral arm is always the decision of record.

## The knobs ([axioms] section)

The `[axioms]` TOML section controls the axiom extraction pipeline and how axioms participate in question resolution.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `axioms.enabled` | bool | `true` | `Z_HARNESS_AXIOMS_ENABLED` | Master on/off switch for axiom participation in resolve-question. When `false`, `_load_axiom_matches` returns `[]` immediately — no axiom ever participates. Also gates `auto_extract_post_run`. |
| `axioms.kernel_budget_chars` | int | `6000` | `Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS` | Maximum characters of axiom text included in the context kernel passed to implementers/consultants. Positive integer. |
| `axioms.extract_min_recurrence` | int | `3` | `Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE` | Minimum recurrence count before a behavioral pattern is auto-extracted as an axiom candidate. Positive integer. |
| `axioms.auto_extract_post_run` | bool | `true` | `Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN` | When `true`, runs the axiom extraction pipeline automatically at the end of each `/z-*` run. Set to `false` to disable automatic extraction (manual extraction still possible). |

## The knobs ([experiment] section)

The `[experiment]` section contains feature-flag knobs that are **on by default**. These govern the persona-rotation data-collection experiment. Disabling them reverts the commands to their pre-experiment behavior exactly — no events, no state files, no prompt changes.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `experiment.persona_rotation` | bool | `true` | `Z_HARNESS_EXPERIMENT_PERSONA_ROTATION` | Master on/off switch for all persona-rotation behavior in `/z-execute`, `/z-plan`, and `/z-debug`. Set to `false` to pause data collection and restore pre-experiment behavior. |
| `experiment.control_every_n` | int | `5` | `Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N` | Forced-control cadence. Every Nth implementer attempt (counted repo-wide, persisted in `.z-harness/.persona-control-counter`) uses `boring-anchor` instead of a random draw. Default 5 means 1-in-5 attempts is a control sample. |

**Kill-switch** — to pause the experiment entirely:

```bash
export Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false
# or persistently:
scripts/config.sh set experiment.persona_rotation false --scope=project
```

## The knobs ([changelog] section)

The `[changelog]` section controls the post-commit hook that drafts CHANGELOG.md bullets. Installed per-repo via `scripts/install-changelog-hook.sh`; these knobs gate it at run-time so it can be disabled without uninstalling.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `changelog.auto` | bool | `true` | Master switch for the post-commit changelog hook. Set to `false` to stop writing CHANGELOG.md bullets without uninstalling the hook. |
| `changelog.types` | array\<string\> | `["feat", "fix"]` | Conventional-commit types that earn a bullet. Commits not matching these types are silently skipped by the hook. |
| `changelog.file` | string | `"CHANGELOG.md"` | Changelog path, relative to repo root. |
| `changelog.repos` | array\<string\> | `["*"]` | Repo-ID allowlist; `"*"` means every repo. |

## The knobs ([models], [model_classes], and [model_routing] sections)

`[models]` remains the legacy external-provider role override section. These keys are separate from native-agent model routing so `models.reviewer = "codex-cli"` is never confused with a native class such as `cheap` or `standard`. An empty string (the default for all `[models]` keys) means "use the provider's `default_model`". Validity of the model/vendor string is cross-checked against `providers.json` at RESOLVE time (not at config-load time), so invalid models are caught only when the role is dispatched.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `models.consultant_primary` | string | `""` | Model override for the primary external consultant role. Empty = use provider default. |
| `models.consultant_secondary` | string | `""` | Model override for the secondary external consultant role. Empty = use provider default. |
| `models.reviewer` | string | `""` | Model override for the external reviewer role. Empty = use provider default. |
| `models.implementer` | string | `""` | Model override for an external implementer provider role. Empty = use provider default. |
| `models.pre_reviewer` | string | `""` | Model override for the pre-reviewer role. Empty = use provider default. |

`[model_classes.<name>]` defines local native-model classes for native-agent routing. There are four built-in classes — `cheap`, `low`, `standard`, `deep` — and each carries **two coexisting axes**:

1. **Legacy host-blind scalars** (retained for backward-compat, criterion #8): `model` (required, non-empty), plus optional `thinking` / `reasoning` string metadata. Old pre-host-axis configs keep working unchanged, and host-blind lookups (`model_classes.deep.model`) still resolve.
2. **Host axis** — a per-host-family `(model, effort)` pair the resolver (T002+) selects from the detected host. Host families are exactly two:
   - `claude` — native Claude Code hosts. `effort` is applied via the subagent `effort:` frontmatter field.
   - `omp` — **every non-claude host** (pi / codex / cursor / antigravity / unknown). Effort is baked into the omp catalog model name (`gpt-5.6-terra-medium`), so the `omp.effort` field is always the empty-string sentinel.

**Host detection.** The family in point 2 is not read from adapter/export host selection — it comes from `scripts/detect-host.sh` (honoring a `Z_HARNESS_HOST` override), which prints exactly one of `claude | pi | codex | cursor | antigravity` (default `claude` when no positive env marker is present). The dispatcher (`runtime/dispatch/dispatcher.py::_host_family`) then applies the fixed rule: `claude` → the `claude` family, **every other value → the `omp` family**. This is a different detection mechanism from the adapter/export "host" concept in [capabilities-matrix.md](capabilities-matrix.md) (which uses `z_harness_cli/adapters/registry.py::detect_all()` / an explicit `--host` flag for launch/export) — the two happen to share the same host-id vocabulary but are looked up independently.

**MCP dispatch path note:** the `z_harness_cli/mcp/server.py` native-agent/subagent dispatch path resolves its model route through this same `detect-host.sh`/`Z_HARNESS_HOST` mechanism (not a separate one). A non-claude host running the MCP dispatch path must have the env markers `detect-host.sh` reads (`PI_*`, `CODEX_API_KEY`/`CODEX_EXEC`, `CURSOR_API_KEY`, `ANTIGRAVITY_PLUGIN_ROOT`) actually set, or export `Z_HARNESS_HOST` explicitly — otherwise detection silently falls through to `claude`, and every class routes to the Claude-family model even though the MCP server is running on a different host.

`effort` allowed values: `""` (no applied effort — the sentinel for Haiku and for every omp entry), `none`, `low`, `medium`, `high`, `xhigh`, `max`. Custom class names must use lowercase/underscore TOML keys; a custom class must define a model via either the legacy scalar or at least one host sub-table.

**Gotcha: re-pinning a BUILT-IN class via the legacy scalar alone no longer works.** For the four built-in classes (`cheap`/`low`/`standard`/`deep`), `scripts/config.py` DEFAULTS *always* populate the host-keyed keys (`model_classes.<class>.claude.model`, `model_classes.<class>.omp.model`) alongside the legacy scalar — and the resolver checks the host-keyed key first, falling back to the legacy scalar only when the host-keyed key is absent. Because the host-keyed key is never absent for a built-in class (it ships as a DEFAULT), a config that sets **only** `model_classes.deep.model = "my-model"` is silently shadowed by the shipped `model_classes.deep.claude.model = "opus"` default on a Claude host — the legacy pin has no effect. This is different from a *custom* class (example (b) below), which has no DEFAULTS entry at all, so its legacy scalar is never shadowed. To re-pin a built-in class, set the host-keyed key(s) directly:

```toml
# Re-pin the built-in `deep` class on a Claude host — this is the key that
# actually wins; setting only `model_classes.deep.model` is silently shadowed
# by the shipped host-keyed DEFAULT.
[model_classes.deep.claude]
model = "my-model"

# Optional: also override the non-Claude (omp) side so the pin is host-complete.
[model_classes.deep.omp]
model = "my-omp-model"
```

**Two label-format facts to know:**
- The omp middle-tier model family is spelled **`terra`**, not "tera" (`gpt-5.6-terra-low`, `gpt-5.6-terra-medium`).
- On omp, effort is **baked into the model name itself** (`gpt-5.6-sol-medium` is a single catalog identifier — there is no separate `effort` value to apply). On Claude, effort is a **distinct applied axis**: the subagent's `effort:` frontmatter field (`low|medium|high|xhigh|max`). The two axes are applied differently at dispatch time: the resolved *model* is always applied per-call via `Agent(model=...)`; the resolved *effort* has no per-call `Agent()` parameter on Claude, so for the `/z-execute` implementer (whose effort varies per task by complexity tier, not just per subagent) the routed Claude effort is carried as advisory telemetry/prompt context only, while on omp the effort requires no separate application step because selecting the model already applies it. See [skills/z-execute/SKILL.md](../../skills/z-execute/SKILL.md) for the `override_applied`/`override_support` telemetry that records this honestly.

The four-tier host-keyed default matrix:

| Class | `claude` (model · effort) | `omp` (model · effort) |
|-------|---------------------------|-------------------------|
| `cheap` | `haiku` · `""` | `gpt-5.6-luna-low` · `""` |
| `low` | `sonnet` · `medium` | `gpt-5.6-terra-low` · `""` |
| `standard` | `sonnet` · `high` | `gpt-5.6-terra-medium` · `""` |
| `deep` | `opus` · `high` | `gpt-5.6-sol-medium` · `""` |

| Key pattern | Type | Default | Description |
|-------------|------|---------|-------------|
| `model_classes.<class>.model` | string | claude-family model | Legacy host-blind scalar (back-compat); mirrors the claude model. |
| `model_classes.<class>.thinking` | string | `""` | Optional legacy host-blind thinking metadata. |
| `model_classes.<class>.reasoning` | string | `""` | Optional legacy host-blind reasoning metadata. |
| `model_classes.<class>.claude.model` | string | see matrix | Concrete model for the Claude host family. |
| `model_classes.<class>.claude.effort` | string | see matrix | Applied effort (`""`\|`none`\|`low`\|`medium`\|`high`\|`xhigh`\|`max`) for Claude. |
| `model_classes.<class>.omp.model` | string | see matrix | Effort-suffixed catalog model for the omp (non-claude) host family. |
| `model_classes.<class>.omp.effort` | string | `""` | Always `""` — omp effort is baked into the model name. |

`[model_routing]` maps native agents and implementer tiers to either a named class or an exact model label. `model_routing.native_agents.default = ""` intentionally inherits each agent's checked-in frontmatter model, preserving cheap Haiku agents and standard Sonnet agents when no override is configured. Implementer tier defaults route through the host-keyed classes above (T003) — `low`→`low`, `medium`→`standard`, `high`→`deep`, `retry`→`deep` — so a tier expands to the detected host's `(model, effort)` pair rather than a fixed `sonnet`/`opus` scalar: on a `claude` host the four tiers resolve to `sonnet·medium / sonnet·high / opus·high / opus·high`, and on an `omp`-family host to `gpt-5.6-terra-low / gpt-5.6-terra-medium / gpt-5.6-sol-medium / gpt-5.6-sol-medium`.

The fixed subagent fleet (T004) is mapped the same way: every native agent id is assigned a class that mirrors its checked-in frontmatter model — Haiku agents → `cheap`, Sonnet agents → `standard`, Opus agents → `deep` — via `model_routing.native_agents.<agent_id>` entries in `DEFAULTS`. Frontmatter model/effort remains the fallback for any agent id not listed.

| Key pattern | Type | Default | Description |
|-------------|------|---------|-------------|
| `model_routing.native_agents.default` | string | `""` | Empty sentinel = inherit each native agent's frontmatter model. |
| `model_routing.native_agents.<agent_id>` | string | see `DEFAULTS` | Route a native agent id (underscore key form) to a class name such as `cheap`/`standard`/`deep`, or an exact model label. Pre-assigned for all ~35 fleet agents. |
| `model_routing.implementer.low` | string | `"low"` | Low-complexity implementer route (class name). |
| `model_routing.implementer.medium` | string | `"standard"` | Medium-complexity implementer route (class name). |
| `model_routing.implementer.high` | string | `"deep"` | High-complexity implementer route (class name). |
| `model_routing.implementer.retry` | string | `"deep"` | Retry implementer route (class name). |

Example — (a) overriding the host-keyed table, and (b) pinning prior host-blind behavior:

```toml
# (a) Host-keyed override: change what `deep` resolves to per host family.
[model_classes.deep.claude]
model = "claude-opus-4-1"        # exact Claude model
effort = "xhigh"                 # applied via subagent `effort:` frontmatter

[model_classes.deep.omp]
model = "gpt-5.6-sol-medium"     # effort baked into the catalog model name
effort = ""                      # omp effort is always the empty sentinel

# (b) Pin PRIOR (host-blind) behavior for a custom class: set only the legacy
#     scalar `model` and omit the host axis. Old configs written this way keep
#     working unchanged — the host-keyed keys are additive, not required.
[model_classes.local_fast]
model = "ollama/qwen3:8b"        # host-blind scalar; resolves for any host lookup
thinking = "low"
reasoning = "effort=low"

[model_routing.native_agents]
explore = "local_fast"           # named class
auditor = "claude-sonnet-4-5"    # exact native model override

# These implementer overrides are illustrative only — they replace the SHIPPED
# defaults (low="low", medium="standard", high="deep", retry="deep", all class
# names). An exact label like "sonnet" pins that tier to a fixed Claude model
# on every host, opting it OUT of host-aware routing.
[model_routing.implementer]
low = "sonnet"                    # exact override: opts this tier out of host-aware routing
medium = "standard"               # named class (same as the shipped default)
high = "deep"                     # named class (same as the shipped default)
retry = "claude-opus-4-1"        # exact override also allowed

[models]
reviewer = ""                    # external provider role; empty = provider default
```

### Model/config ownership and precedence

Several files can mention models, but they own different layers:

1. **Native agent frontmatter** (`agents/*.md` in z-harness source, exported to host-specific agent locations such as `.claude/agents/*.md`) owns the checked-in default model for a native agent. `model_routing.native_agents.default = ""` means "do not override this frontmatter".
2. **`CLAUDE.md`** owns human/process instructions and repository policy. It is not a model routing file; do not put per-role model overrides there.
3. **`.omp/config.yml`** owns Oh My Pi host/plugin configuration. It may affect harness runtime availability, but it does not override z-harness role routes.
4. **z-harness TOML config** (`~/.config/z-harness/config.toml` and `.z-harness/config.toml`) owns user/repo preferences such as `[models]`, `[model_classes]`, and `[model_routing]`. Repo TOML overrides global TOML; TOML overrides preference env vars when set.
5. **`.z-harness/providers.json`** owns external provider registry details (`runtime`, `default_model`, argv templates, and legacy provider-role fallback). It is consulted when resolving external `[models]` roles, after any TOML `[models.<role>]` override.

In short: frontmatter is the native-agent default, TOML is the preferred override layer, and `providers.json` is the external-provider registry/fallback. `CLAUDE.md` and `.omp/config.yml` are policy/runtime surfaces, not role-routing override layers.

Native-agent model precedence is exact `model_routing.native_agents.<agent_id>`, then `model_routing.native_agents.default` when non-empty, then the source agent frontmatter. External-provider role precedence is TOML `[models.<role>]`, then `.z-harness/providers.json` role fallback/default model. `CLAUDE.md` and `.omp/config.yml` never participate in those override chains.

## The knobs ([export] section)

The `[export]` section controls which hosts `/z-export` targets and what strategy to use. The `hosts` list is validated against a closed set at config-load time; unknown host names exit 2 on the repo/env layer and soft-warn on the global layer.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `export.hosts` | array\<string\> | `["cursor", "codex", "agy", "omp", "pi"]` | `Z_HARNESS_EXPORT_HOSTS` (JSON-encoded array) | Export target hosts. Closed set: adapter names (`claude`, `antigravity`, `agy`, `cursor`, `codex`, `omp`) and export-only driver names (`pi`, `windsurf`, `cline`, `kiro`, `copilot`). Must be non-empty. |
| `export.strategy` | string | `""` | `Z_HARNESS_EXPORT_STRATEGY` | Export strategy. `""` (default, empty sentinel) defers to each driver's own `default_strategy` (e.g. `cline` → `pointer`, `windsurf`/`kiro` → `curated`). Explicit values: `pointer`, `curated`, `full`. |

---

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/config.py:61` — `DEFAULTS` — built-in defaults for all config sections including `[brainstorm]`, `[personas]`, `[workflow]`, `[followup]`, `[axioms]`, `[experiment]`, `[runtime]`, `[cost]`, `[models]`, `[model_classes]`, `[model_routing]`, `[export]`, `[changelog]` (layer 1)
- `scripts/config.py:523` — `VALIDATORS` — allowed enum sets per dotted-key; hard-fail on repo/env, soft-warn on global; includes all `personas.*`, workflow, axioms, experiment, cost, models, model_classes, model_routing, export keys
- `scripts/config.py:618` — `_COERCERS` — post-validation normalizers; converts env-var strings to typed Python values for bool/int knobs (including all `personas.*` bool knobs)
- `scripts/config.py:785` — `QUESTION_IDS` — single source of truth for AskUserQuestion routing-class preference keys (6 workflow.* + pre_run_cost_gate); validated against VALIDATORS at module load by `_run_startup_guards`
- `scripts/config.py:860` — `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT` — default overnight allowlist: `{workflow.slug_confirm: recommend_derived, workflow.audit_to_amend: amend}`
- `scripts/config.py:866` — `RESULT_MAP` — maps `(question_id, option-domain-value)` to resolver result-domain (`skip|prefill|ask|halt|defer-to-sink`)
- `scripts/config.py:891` — `_run_startup_guards` — module-load consistency check: asserts `QUESTION_IDS <= VALIDATORS`, every qid has skill_default and halt_category, RESULT_MAP references only valid choices; raises `SystemExit(2)` on violation
- `scripts/config.py:988` — `_ENV_VAR_ALIASES` — dotted keys whose exported env var name differs from the mechanical `_dotted_to_env()` mapping (e.g. `runtime.consult` → `Z_HARNESS_CONSULT`)
- `scripts/config.py:1031` — `_INGRESS_LEGACY_ALIASES` — ingress fallback map including all `_ENV_VAR_ALIASES` plus ingress-only legacies (e.g. `notify.level` → `Z_HARNESS_NOTIFY`, `runtime.max_parallel` → `HERMES_MAX_PARALLEL`)
- `scripts/config.py:1061` — `LEGAL_ENV_KEYS` / `LEGAL_ENV_PREFIXES` — allowlist of plumbing and unattended-entry env vars that never trigger the deprecation warning
- `scripts/config.py:1379` — `load_config` — build resolved config from all 4 layers; returns `(values, sources)` dicts; TOML wins over env for preference-class vars
- `scripts/config.py:1711` — `cmd_get` — resolve and print single dotted-key value; exits 3 on unknown or meta key
- `scripts/config.py:1742` — `cmd_get_batch` — resolve multiple keys in one process; output JSON object; unknown/meta keys → null + stderr; always exits 0
- `scripts/config.py:1837` — `cmd_export_env` — print export+unset lines for all user knobs; emit `config_resolved` once per run; emit `config_env_deprecated` per deprecated var
- `scripts/config.py:1900` — `cmd_ensure_defaults` — write global config with defaults + inline comments if absent; never overwrites existing file
- `scripts/config.py:1977` — `cmd_explain` — print effective value and source layer for one key
- `scripts/config.py:2009` — `cmd_list_question_ids` — print sorted JSON array of registered question IDs
- `scripts/config.py:2014` — `cmd_resolve_halt_category` — print `halt_category` tag for a question ID (`decision|risk|shortcut|archiving|mechanical_proceed`) or `ask` for unknown IDs; always exits 0
- `scripts/config.py:2524` — `_load_axiom_store_module` — dynamically load `scripts/axiom-store.py` via importlib (hyphen in filename); cached per process; returns None when absent or fails
- `scripts/config.py:2562` — `_load_axiom_matches` — load graph-valid approved axioms for a question_id; gated on `axioms.enabled`; returns `[]` when disabled or store absent
- `scripts/config.py:2661` — `_resolve_memory_matches` — merge memory match list; highest strength wins on agreement; returns `(None, 'conflict', sources)` when entries disagree
- `scripts/config.py:2697` — `_resolve_config_memory_envelope` — pre-axiom resolution: config + routing-pref memory; returns 7-tuple including `resolved_value` and `memory_silent` signals for axiom layer
- `scripts/config.py:2928` — `_build_resolve_envelope` — full resolver: apply axiom layer on top of config+memory envelope; agree/gap-fill/direct-conflict axiom outcomes; returns 5-tuple
- `scripts/config.py:3075` — `cmd_resolve_question` — consult 4-layer config + memory + axioms + overnight overrides; return JSON `{result, default, source, rule_id, strength, reason, sources[]}`; stdout reserved for JSON
- `scripts/config.py:3364` — `cmd_check_no_ask` — overnight-gate checker with cost-gate delegation path (`--range-high`/`--severity`); returns `{result: halt|proceed|auto_proceed|unhandled_gate, question_id, rule_id}`; always exits 0
- `scripts/config.py:3633` — `cmd_set` — atomically write a TOML key to global or project config via tmp+rename; validates against VALIDATORS before writing; exit 2 on invalid value; exit 0 silently on success
- `scripts/config.py:3747` — `ENV_ONLY_KNOBS` — list of env-only knob names surfaced by `inspect-all`; not settable via TOML
- `scripts/config.py:3796` — `cmd_inspect_all` — print all config knobs with value/source/persistence_class; covers DEFAULTS keys + QUESTION_IDS + ENV_ONLY_KNOBS; `--json` for machine-parseable output
- `scripts/config.py:3941` — `cmd_should_notify` — print `yes|no` for a given event kind; always exits 0; exits 2 on unknown event; valid kinds: `approval`, `phase_end`, `error`
- `scripts/config.py:4034` — `cmd_migrate` — rewrite old provider names in `roles.*.runtime` to `-cli` suffixed form; applied to global + project layers; idempotent; exits 4 on I/O error
- `scripts/propose-prefs.py:1` — `propose-prefs` (module) — walk `metrics.jsonl` for repeated command-pair patterns; emit JSON proposal if threshold met; never writes — caller owns write
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `commands` (z-audit-plan, z-audit-plan-style, z-plan, z-fix, z-uplift, z-amend, z-do, z-research, z-explore, z-execute, z-review-all, z-overnight, z-debug, z-audit, z-brainstorm, z-attend) — call `export-env` + `should-notify` during Setup; call `resolve-question` before workflow AskUserQuestions (including the current terrain workflow, where deep terrain mapping is `/z-explore --depth=deep`); call `check-no-ask` for overnight gate checks; call `set` after proposal acceptance; call `propose-prefs.py` at command end; read `brainstorm.personas`, `personas.*`, `experiment.*` at each persona-dispatch site; call `resolve-halt-category` for halt-category tagging in chain-runner.sh
- `skills` (z-suggest-memory, z-explore, z-debug, z-brainstorm, z-do, z-plan, z-research; `z-map` only as a legacy compatibility wrapper that routes to `/z-explore --depth=deep`) — call `list-question-ids` to validate routing-preference question IDs; call `resolve-question` for slug-confirm gate; call `export-env` + `should-notify` during Setup
- `scripts` — provides the `log-event.sh` + `log-phase.sh` telemetry pipeline that `config.py` writes events through; `scripts/axiom-store.py` loaded dynamically by `_load_axiom_store_module` for axiom resolution
- `followup-sink` — `sink-add.sh` called by orchestrators when `resolve-question` returns `defer-to-sink`; `notion-push.py` reads `Z_HARNESS_NOTION_TOKEN` env override
- `active-plan-registry` — `Z_HARNESS_REGISTRY_ENABLED`, `Z_HARNESS_REGISTRY_STALE_SECS`, `Z_HARNESS_STRICT_OVERLAP`, `Z_HARNESS_EXTERNAL_DEFAULT`, `Z_HARNESS_BASE_DIR`, `Z_HARNESS_AUTO_WAIT`, `Z_HARNESS_AUTO_WAIT_BUDGET_SECS`, `Z_HARNESS_WAIT_POLL_SECS`, `Z_HARNESS_WAIT_TIMEOUT_SECS`, and `Z_HARNESS_WAIT_REQUIRE_MERGE` are env-only knobs (not in config.py's DEFAULTS) consumed by `plan-path.sh` and `active-plan-registry.py`
- `cost-estimation` — `cost.token_budget` is read by `check-no-ask --range-high N --severity hard` as the budget ceiling; `workflow.pre_run_cost_gate` gates the cost-gate question for z-research/z-uplift/z-plan-split/z-plan
- `amendment-brief` — `scripts/amend-gate-decision.py` reads `workflow.audit_to_amend` resolver output (result+source) to determine whether to auto-split, force-ask, or halt; `scripts/amendment-brief.py` renders the prose brief for approach concerns; both `/z-audit-plan` Phase 5 and `/z-review-all` Phase 6.6 use this path

## Edge cases / gotchas

- `personas.consult_eval` defaults to `false` (OFF) — it is the most expensive and lowest-signal advisory arm; turning it on adds one extra subagent call at every convergent eval site
- There is NO `personas.debug` knob — it was removed as dead code. Do not attempt to configure it; it will be silently ignored or may trigger a validation error on future schema revisions
- `brainstorm.personas` remains in `[brainstorm]` (not `[personas]`) by design; do NOT move it
- `personas.implementer_retry` only has effect when `experiment.persona_rotation = true`; when rotation is off, `implementer_retry` is a no-op regardless of its value
- `workflow.slug_confirm` value domain (`ask`/`auto_accept`/`recommend_derived`) is NOT the same as the resolver result domain (`ask`/`prefill`/`skip`); `RESULT_MAP` translates between them — `auto_accept` → `skip`, `recommend_derived` → `prefill`
- `Z_HARNESS_ASK_ALL=1` and `Z_HARNESS_NO_ASK=halt` are mutually exclusive — setting both causes `resolve-question` to exit 5 (not 0); check for this conflict before setting both in scripts
- `check-no-ask` fails closed on unregistered question IDs when `NO_ASK=halt` — unknown question → `halt` + `unknown_ask_blocked` event
- Capture exit code separately from output: `RESOLVED=$(python3 scripts/config.py resolve-question ...); RESOLVE_EXIT=$?`. Never pipe through `set -e` chains that swallow exit codes
- `cmd_set` exits 0 silently on success — no stdout output; do not parse stdout from `cmd_set`
- Valid event kinds for `should-notify`: `approval`, `phase_end`, `error` only. Passing `run_complete` exits 2; guard invocations with `|| true` if needed
- `get-batch` always exits 0 unlike `get` which exits 3 on unknown keys — callers must check for `null` values in JSON output to detect missing keys
- `[followup]` keys that are arrays (e.g. `auto_close_low_risk_path_allowlist`) are NOT in `VALIDATORS` and receive no enum validation
- `followup.auto_close_low_risk_enabled` defaults to `true` (on by default); set to `false` to disable — do not assume the default is off
- `Z_HARNESS_NOTION_TOKEN` is env-only (not a TOML key); never log it; never run `notion-push.py` wrappers under `set -x`
- Axiom participation requires `axioms.enabled = true` (the default) AND `scripts/axiom-store.py` present. When the store is absent, axioms are a silent no-op — not an error
- `Z_HARNESS_REGISTRY_ENABLED`, `Z_HARNESS_REGISTRY_STALE_SECS`, `Z_HARNESS_STRICT_OVERLAP`, `Z_HARNESS_EXTERNAL_DEFAULT`, `Z_HARNESS_BASE_DIR`, `Z_HARNESS_AUTO_WAIT`, `Z_HARNESS_AUTO_WAIT_BUDGET_SECS`, `Z_HARNESS_WAIT_POLL_SECS`, `Z_HARNESS_WAIT_TIMEOUT_SECS`, and `Z_HARNESS_WAIT_REQUIRE_MERGE` are NOT in config.py's DEFAULTS or VALIDATORS — consumed exclusively by `plan-path.sh` and `active-plan-registry.py`; `inspect-all` surfaces them under env-only but does NOT treat them as TOML keys
- `cost.token_budget = null` (the default) means no budget is configured; `check-no-ask` with `--severity hard` under `NO_ASK=halt` will return `halt` with `rule_id: cost_budget_missing` when unset
- `workflow.pre_run_cost_gate` governs the z-research/z-uplift/z-plan-split/z-plan pre-run gate; it is a registered question_id and participates in the overnight allowlist system
- `check-no-ask --severity soft` always returns `auto_proceed` regardless of policy — soft-severity gates are never blocking
- `models.*` keys accept any string including empty (empty = use provider default); cross-checked against `providers.json` at resolve time NOT at config-load time — invalid model strings are caught only when the role is dispatched
- `export.hosts` validated against a closed set at config-load time; unknown names exit 2 on repo/env layer and soft-warn on global layer; list must be non-empty; env transport is a JSON-encoded array string
- `export.strategy = ""` (empty string, the default) is the sentinel meaning "defer to per-driver default"; do not confuse it with missing/unset
- `workflow.audit_to_amend` behavior is SOURCE-KEYED: the effective action depends on the resolver's `source` field, not just the stored value; a fresh user with no preference (source=none) gets `auto_split` (no popup), not `ask`; the value `ask` in config.toml explicitly opts BACK into the popup

## Examples

**Repo-local override with all persona knobs** (`.z-harness/config.toml`):

```toml
schema_version = 1

[brainstorm]
personas = true

[personas]
critique_panel = true
audit = true
review_eval = true
consult_eval = false          # default OFF — most expensive advisory arm; enable to collect data
implementer_retry = "same"    # "same" | "new"

[experiment]
persona_rotation = true
control_every_n = 5
```

**Env override to disable the most expensive advisory arm:**

```bash
export Z_HARNESS_PERSONAS_CONSULT_EVAL=false   # already the default
export Z_HARNESS_PERSONAS_REVIEW_EVAL=true
export Z_HARNESS_PERSONAS_CRITIQUE_PANEL=true
```

**Env override for CI — disable persona injection entirely:**

```bash
export Z_HARNESS_BRAINSTORM_PERSONAS=false
export Z_HARNESS_PERSONAS_CRITIQUE_PANEL=false
export Z_HARNESS_PERSONAS_AUDIT=false
export Z_HARNESS_PERSONAS_REVIEW_EVAL=false
export Z_HARNESS_PERSONAS_CONSULT_EVAL=false
export Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false
```

**Workflow preferences** (`.z-harness/config.toml` at git root):

```toml
schema_version = 1

[workflow]
audit_to_amend = "amend"
slug_confirm = "recommend_derived"
implement_all_proceed = "auto_resume"
review_all_proceed = "proceed"
plan_decisions_approval = "approve"
spec_retro_discovery = "defer_to_sink_p2"
pre_run_cost_gate = "auto_proceed"
planning_mode = "intent"        # intent (default) | full (legacy SDD)
intent_level = "auto"           # auto | quick | standard | deep
intent_parallel_levels = false  # opt out; default true attempts safe same-level INTENT BFS parallelism
hermes_enabled = false          # true to re-enable old Hermes machinery
```

**Overnight mode with custom allowlist:**

```bash
export Z_HARNESS_NO_ASK=halt
export Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE='{"workflow.slug_confirm":"recommend_derived","workflow.plan_decisions_approval":"approve"}'
```

**Token budget for policy mode:**

```toml
[cost]
token_budget = 50000
```

**Export target override** (restrict to cursor + codex only):

```toml
[export]
hosts = ["cursor", "codex"]
strategy = ""   # empty = each driver uses its own default
```

**Per-role model override:**

```toml
[models]
consultant_primary = "claude-opus-4"   # override only the primary consultant
```

## v2 deferrals

The following are known issues documented in SPEC but deferred to v2:

- **Stale-memory hygiene** — when a routing-preference memory exists and the user writes the same `question_id` to config, the memory continues to appear in conflict checks. v1 emits `memory_potentially_superseded`; v2 will add a cleanup prompt.
- **`config.py set --dry-run` / `--backup`** — v2 will add dry-run and pre-overwrite backup flags.
- **Async memory-write telemetry** — `askuser_resolved` source field reflects intent in v1; v2 will log only after `/z-suggest-memory` returns 0.
- **Multi-IDE export precheck** — Cursor, Codex CLI, and agy fall back to raw AskUserQuestion in v1; precheck integration is a v2 concern.
- **Halt-class bypass** (`spec_problem`, `decision_needed`) — explicitly out of v1.

## Future knobs

Do not add knobs without a `/z-plan` run. Schema sprawl is the most common failure mode for config systems — every new knob must be designed, documented, and validated before it ships. Undocumented knobs break the two-tier doc contract and silently diverge from `docs/llm/config.json`.
