# config

> Last updated: 2026-06-05
> Covers source: scripts/config.py, scripts/config.sh, scripts/propose-prefs.py, docs/human/config.md

## Overview

`config` is the unified z-harness configuration system. It has two semantic surfaces:

- **Loader API** — the 4-layer TOML config loader (built-in defaults → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars). Subcommands: `get`, `get-batch`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `inspect-all`. This is the slice-1 foundation.
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

## The knobs (Loader API)

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `notify.level` | string | `approval_only` | `off` \| `approval_only` \| `all` | Controls when PushNotification fires. `off` silences all notifications. `approval_only` notifies on `approval` and `error` events. `all` notifies on every `approval`, `phase_end`, and `error` event. |
| `notify.discord_webhook_url` | string | `""` | any Discord webhook URL | Discord webhook URL for notification delivery. Empty string (default) disables Discord notifications entirely. When set and `notify.level` permits, `should-notify --channel discord` returns `yes`. The webhook URL is a secret and must not be committed — `.gitignore` already protects `.z-harness/` where config lives. |
| `docs.always_apply` | string | `always` | `always` \| `never` | Whether light flows auto-dispatch doc-fetcher when `docs/llm/INDEX.json` exists. `always` matches current /z-do default behavior. `never` skips doc-fetcher. **Applies only to light flows (slice 1: /z-do). Heavy flows always dispatch doc-fetcher regardless of this knob.** |
| `runtime.consult` | string | `on` | `on` \| `off` | Single-model mode. When `off`, the `consultant_primary`, `consultant_secondary`, and `reviewer` roles resolve to the `none` sentinel, so cross-LLM consultation and review are skipped (no Gemini/Codex dispatch). Exported as `Z_HARNESS_CONSULT` (not `Z_HARNESS_RUNTIME_CONSULT` — see the transliteration note), which `resolve-provider.py` reads. |
| `cost.token_budget` | int or null | `null` | positive int or null | Token budget ceiling for cost-gate delegation. When set, `check-no-ask` with `--range-high` compares the estimate against this value. `null` (unset) means no budget is configured; any cost gate under policy will halt with `cost_budget_missing`. |

For `[brainstorm]`, `[personas]`, `[workflow]`, `[followup]`, `[axioms]`, and `[experiment]` knobs, see the sections below.

## The transliteration rule

Env-var overrides follow a deterministic rule: lowercase TOML dotted-key → prefix `Z_HARNESS_` + uppercase + `.` to `_`. One key is an explicit alias exception: `runtime.consult` exports as `Z_HARNESS_CONSULT` (the legacy name `resolve-provider.py` reads), not the mechanical `Z_HARNESS_RUNTIME_CONSULT`.

| TOML key | Env var |
|----------|---------|
| `notify.level` | `Z_HARNESS_NOTIFY_LEVEL` |
| `notify.discord_webhook_url` | `Z_HARNESS_NOTIFY_DISCORD_WEBHOOK_URL` |
| `docs.always_apply` | `Z_HARNESS_DOCS_ALWAYS_APPLY` |
| `brainstorm.personas` | `Z_HARNESS_BRAINSTORM_PERSONAS` |
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

For workflow, followup, and experiment keys, the rule applies identically.

Keys must match `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.  Hyphens in keys exit 2.
Nested keys >2 levels exit 2.  Empty env vars are treated as missing.

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

### `inspect-all [--json]`

Prints all configuration knobs with their current effective value, source layer, and persistence class. Covers three categories:

1. **TOML-persistent keys** — every key in `DEFAULTS` (all `notify.*`, `docs.*`, `brainstorm.*`, `personas.*`, `workflow.*`, `followup.*`, `axioms.*`, `experiment.*`, `runtime.*`, `cost.*`)
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
| `Z_HARNESS_STRICT_OVERLAP` | _(unset / off)_ | Set to `1` to enable blocking-overlap mode in `active-plan-registry.py overlaps`. When active, an `explicit`×`explicit` exact scope-path match between two live runs causes exit code `20` (blocking), which `/z-implement-all` and `/z-implement-next` treat as a hard halt requiring user resolution. By default (unset) scope overlaps are advisory only (exit `10`). Does NOT affect held-path conflict behavior. |

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
| `workflow.audit_to_amend` | string | `ask` | `ask` \| `amend` \| `stop` | Controls the Phase 5 AskUserQuestion in `/z-audit-plan` and `/z-audit-plan-style`. `ask` always prompts. `amend` auto-proceeds as amend (skips prompt). `stop` auto-stops (skips prompt). |
| `workflow.slug_confirm` | string | `ask` | `ask` \| `auto_accept` \| `recommend_derived` | Controls the soft non-obvious-slug confirmation at 7 callsites. `ask` always prompts. `auto_accept` silently accepts the derived slug. `recommend_derived` pre-selects the derived slug in the AskUser prompt. **The hard slug-collision check always runs unconditionally, regardless of this setting.** |
| `workflow.implement_all_proceed` | string | `ask` | `ask` \| `auto_resume` \| `halt` | Controls the halt-resolution gate in `/z-implement-all`. `ask` prompts. `auto_resume` skips the prompt. `halt` stops unconditionally. |
| `workflow.review_all_proceed` | string | `ask` | `ask` \| `proceed` \| `halt` | Controls the Phase 3.7 proceed gate in `/z-review-all`. `ask` prompts. `proceed` skips the prompt. `halt` stops unconditionally. |
| `workflow.plan_decisions_approval` | string | `ask` | `ask` \| `approve` \| `halt` | Controls the Phase 2.5 decisions-doc approval gate in `/z-plan`. `ask` prompts. `approve` skips the prompt. `halt` stops unconditionally. |
| `workflow.spec_retro_discovery` | string | `ask` | `ask` \| `defer_to_sink_p2` | Controls how Phase 4 of `/z-implement-next` handles out-of-current-SPEC discoveries reported by the implementer. `ask` prompts interactively (default). `defer_to_sink_p2` parks the discovery as a P2 follow-up in the project sink without prompting — resolver returns `defer-to-sink`; orchestrator calls `scripts/sink-add.sh` with the question context. |
| `workflow.pre_run_cost_gate` | string | `ask` | `ask` \| `auto_proceed` \| `halt` | Controls the pre-run cost gate for high-cost commands (z-research, z-uplift, z-plan-split). `ask` prompts. `auto_proceed` skips the gate check. `halt` stops unconditionally. Also consumed by `check-no-ask --question-id workflow.pre_run_cost_gate --range-high N --severity hard|soft`. |

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

The `--range-high` and `--severity` flags activate cost-gate delegation: `soft` severity always returns `auto_proceed`; `hard` severity under `NO_ASK=halt` applies the budget rule against `cost.token_budget`.

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

The `[brainstorm]` section currently contains one knob. It remains in `[brainstorm]` rather than `[personas]` to avoid churn in existing configs — do NOT move it.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `brainstorm.personas` | bool | `true` | `Z_HARNESS_BRAINSTORM_PERSONAS` | Enable persona injection for ideators in `/z-brainstorm`. When ON, up to 3 distinct `ideator` personas are drawn and positionally prepended. When OFF the dispatch is byte-identical to the pre-feature vendor-only brainstorm. |

## The knobs ([personas] section)

The `[personas]` section controls per-surface persona dispatch across all z-harness commands. Each boolean knob enables or disables persona injection at one class of dispatch site; disabling a knob is byte-identical to pre-feature behavior at that site.

| Key | Type | Default | Env var | Description |
|-----|------|---------|---------|-------------|
| `personas.critique_panel` | bool | `true` | `Z_HARNESS_PERSONAS_CRITIQUE_PANEL` | Enable persona injection at the z-plan Phase 3 + Phase 7 fixed 5-panel critique arms (DIVERGENT). When ON, 5 distinct `consultant` personas are drawn and positionally prepended. |
| `personas.audit` | bool | `true` | `Z_HARNESS_PERSONAS_AUDIT` | Enable persona injection at z-audit dimension auditors (DIVERGENT). When ON, one distinct `audit_persona` is drawn per dimension (correctness / perf / cleanliness / design). |
| `personas.review_eval` | bool | `true` | `Z_HARNESS_PERSONAS_REVIEW_EVAL` | Enable the advisory persona reviewer at code-review gates — z-implement-all, z-implement-next, z-plan-light, z-fix, z-do (CONVERGENT). When ON, one `reviewer`-role persona is dispatched advisory-only alongside the authoritative neutral codex gate. |
| `personas.consult_eval` | bool | `false` | `Z_HARNESS_PERSONAS_CONSULT_EVAL` | Enable the advisory persona consult arm at convergent evaluation sites — z-plan-light bundled consult and z-audit bundled consult (CONVERGENT). **Default OFF** — this is the most expensive and lowest-signal advisory arm. When ON, one additional `consultant`-persona advisory arm is dispatched alongside the neutral consult; its output is logged advisory-only. |
| `personas.implementer_retry` | string | `"same"` | `Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY` | Controls how the implementer persona is handled across retries. `same` (default) — reuse the cycle-1 persona for all retries of the same task. `new` — fresh draw excluding the prior persona on each retry. No effect when `experiment.persona_rotation = false`. |

**Key design constraint:** There is NO `personas.debug` knob — it was removed as dead code. Do not document or implement it.

**TOML example** (`.z-harness/config.toml`):

```toml
[brainstorm]
personas = true

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
| `experiment.persona_rotation` | bool | `true` | `Z_HARNESS_EXPERIMENT_PERSONA_ROTATION` | Master on/off switch for all persona-rotation behavior in `/z-implement-all`, `/z-implement-next`, `/z-plan`, and `/z-debug`. Set to `false` to pause data collection and restore pre-experiment behavior. |
| `experiment.control_every_n` | int | `5` | `Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N` | Forced-control cadence. Every Nth implementer attempt (counted repo-wide, persisted in `.z-harness/.persona-control-counter`) uses `boring-anchor` instead of a random draw. Default 5 means 1-in-5 attempts is a control sample. |

**Kill-switch** — to pause the experiment entirely:

```bash
export Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false
# or persistently:
scripts/config.sh set experiment.persona_rotation false --scope=project
```

---

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/config.py:53` — `DEFAULTS` — built-in default values for all config keys including `[brainstorm]`, `[personas]`, `[workflow]`, `[followup]`, `[axioms]`, `[experiment]`, `[cost]` sections (layer 1)
- `scripts/config.py:147` — `VALIDATORS` — allowed enum sets per dotted-key; hard-fail on repo/env, soft-warn on global; includes all `personas.*`, workflow, axioms, experiment, cost keys
- `scripts/config.py:178` — `_COERCERS` — post-validation normalizers; converts env-var strings to typed Python values for bool/int knobs (including all `personas.*` bool knobs)
- `scripts/config.py:239` — `QUESTION_IDS` — single source of truth for AskUserQuestion routing-class preference keys
- `scripts/config.py:320` — `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT` — default overnight allowlist
- `scripts/config.py:326` — `RESULT_MAP` — maps `(question_id, option-domain-value)` to resolver result-domain
- `scripts/config.py:355` — `_run_startup_guards` — module-load consistency check
- `scripts/config.py:664` — `load_config` — build resolved config from all 4 layers; returns `(values, sources)` dicts
- `scripts/config.py:880` — `cmd_export_env` — print export lines for all user knobs; emit `config_resolved` once per run
- `scripts/config.py:2007` — `cmd_resolve_question` — consults 4-layer config + memory + axioms + overnight overrides; returns JSON envelope
- `scripts/config.py:2264` — `cmd_check_no_ask` — lightweight overnight-gate checker with cost-gate delegation path
- `scripts/config.py:2533` — `cmd_set` — atomically write a TOML key to global or project config via tmp+rename
- `scripts/propose-prefs.py:1` — `propose-prefs` (module) — walks `metrics.jsonl` for repeated command-pair patterns; emits JSON proposal if threshold met; never writes
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `commands` (z-audit-plan, z-audit-plan-style, z-plan, z-fix, z-uplift, z-amend, z-do, z-research, z-implement-all, z-review-all, z-overnight, z-implement-next, z-debug, z-audit, z-brainstorm, z-plan-light) — call `export-env` + `should-notify` during Setup; call `resolve-question` before workflow AskUserQuestions; call `check-no-ask` for overnight gate checks; call `set` after proposal acceptance; call `propose-prefs.py` at command end; read `brainstorm.personas`, `personas.*`, `experiment.*` at each persona-dispatch site
- `skills` (z-suggest-memory, z-map, z-plan-light, z-debug, z-brainstorm, z-do, z-plan, z-research) — call `list-question-ids` to validate routing-preference question IDs; call `resolve-question` for slug-confirm gate; call `export-env` + `should-notify` during Setup
- `scripts` — provides the `log-event.sh` + `log-phase.sh` telemetry pipeline that `config.py` writes events through; `scripts/axiom-store.py` loaded dynamically by `_load_axiom_store_module` for axiom resolution
- `followup-sink` — `sink-add.sh` called by orchestrators when `resolve-question` returns `defer-to-sink`; `notion-push.py` reads `Z_HARNESS_NOTION_TOKEN` env override
- `active-plan-registry` — `Z_HARNESS_REGISTRY_ENABLED`, `Z_HARNESS_REGISTRY_STALE_SECS`, `Z_HARNESS_STRICT_OVERLAP`, `Z_HARNESS_EXTERNAL_DEFAULT`, `Z_HARNESS_BASE_DIR`, `Z_HARNESS_AUTO_WAIT`, `Z_HARNESS_AUTO_WAIT_BUDGET_SECS`, `Z_HARNESS_WAIT_POLL_SECS`, `Z_HARNESS_WAIT_TIMEOUT_SECS`, and `Z_HARNESS_WAIT_REQUIRE_MERGE` are env-only knobs (not in config.py's DEFAULTS) consumed by `plan-path.sh` and `active-plan-registry.py`
- `cost-estimation` — `cost.token_budget` is read by `check-no-ask --range-high N --severity hard` as the budget ceiling; `workflow.pre_run_cost_gate` gates the cost-gate question for z-research/z-uplift/z-plan-split

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
- `workflow.pre_run_cost_gate` governs the z-research/z-uplift/z-plan-split pre-run gate; it is a registered question_id and participates in the overnight allowlist system
- `check-no-ask --severity soft` always returns `auto_proceed` regardless of policy — soft-severity gates are never blocking

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

## v2 deferrals

The following are known issues documented in SPEC but deferred to v2:

- **Stale-memory hygiene** — when a routing-preference memory exists and the user writes the same `question_id` to config, the memory continues to appear in conflict checks. v1 emits `memory_potentially_superseded`; v2 will add a cleanup prompt.
- **`config.py set --dry-run` / `--backup`** — v2 will add dry-run and pre-overwrite backup flags.
- **Async memory-write telemetry** — `askuser_resolved` source field reflects intent in v1; v2 will log only after `/z-suggest-memory` returns 0.
- **Multi-IDE export precheck** — Cursor, Codex CLI, and agy fall back to raw AskUserQuestion in v1; precheck integration is a v2 concern.
- **Halt-class bypass** (`spec_problem`, `decision_needed`) — explicitly out of v1.

## Future knobs

Do not add knobs without a `/z-plan` run. Schema sprawl is the most common failure mode for config systems — every new knob must be designed, documented, and validated before it ships. Undocumented knobs break the two-tier doc contract and silently diverge from `docs/llm/config.json`.
