# config

> Last updated: 2026-05-29
> Covers source: scripts/config.py, scripts/config.sh, scripts/propose-prefs.py, docs/human/config.md

## Overview

`config` is the unified z-harness configuration system. It has two semantic surfaces:

- **Loader API** — the 4-layer TOML config loader (built-in defaults → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars). Subcommands: `get`, `get-batch`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `inspect-all`. This is the slice-1 foundation.
- **Workflow Resolver** — the `[workflow]` config section plus the question-registry, resolver, writer, elevation proposer, and overnight gate system that sit on top of the loader. Subcommands: `resolve-question`, `check-no-ask`, `set`, `list-question-ids`. This is the slice-2 layer.

The core runtime loop for workflow preferences is: skill prose calls `config.py resolve-question <question_id>` before firing an `AskUserQuestion`; the resolver consults both the TOML config and `routing-preference` memory entries in `docs/llm/*.json`, then returns a typed JSON envelope instructing the skill to `skip`, `prefill`, `ask`, `halt`, or `defer-to-sink`. When running unattended (`Z_HARNESS_NO_ASK=halt`), the overnight gate either auto-decides questions on the allowlist or halts instead of asking. When the user wants to make a preference permanent they run `/z-suggest-memory` (memory path) or `config.py set` (TOML path). The proposer (`propose-prefs.py`) surfaces an invitation to do so when it detects a repeated command-pair pattern in `metrics.jsonl`.

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
| `docs.always_apply` | string | `always` | `always` \| `never` | Whether light flows auto-dispatch doc-fetcher when `docs/llm/INDEX.json` exists. `always` matches current /z-do default behavior. `never` skips doc-fetcher. **Applies only to light flows (slice 1: /z-do). Heavy flows always dispatch doc-fetcher regardless of this knob.** |

For `[workflow]` and `[followup]` knobs, see the sections below.

## The transliteration rule

Env-var overrides follow a deterministic rule: lowercase TOML dotted-key → prefix `Z_HARNESS_` + uppercase + `.` to `_`.

| TOML key | Env var |
|----------|---------|
| `notify.level` | `Z_HARNESS_NOTIFY_LEVEL` |
| `docs.always_apply` | `Z_HARNESS_DOCS_ALWAYS_APPLY` |

For workflow and followup keys, the rule applies identically.

Keys must match `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.  Hyphens in keys exit 2.
Nested keys >2 levels exit 2.  Empty env vars are treated as missing.

## CLI reference (Loader API)

All subcommands available via `scripts/config.sh <sub>` (bash wrapper) or `python3 scripts/config.py <sub>`.

### `get <dotted.key>`

Prints the effective value for one key (no quotes).  Unknown or meta keys exit 3.

```
$ scripts/config.sh get notify.level       → approval_only
$ scripts/config.sh get docs.always_apply  → always
```

### `get-batch <key1> [key2 ...]`

Resolves multiple config keys in a **single process** (one config load) and prints a JSON object mapping each key to its resolved value. Designed to replace N sequential `get` forks when multiple values are needed at once.

- Unknown keys: included in output as `null`; warning emitted to stderr.
- Meta keys (e.g. `schema_version`): included in output as `null`; warning emitted to stderr.
- Always exits 0 (best-effort; callers fall back to defaults for `null` values).

```
$ scripts/config.sh get-batch notify.level followup.notion_enabled
{"notify.level": "approval_only", "followup.notion_enabled": false}

$ scripts/config.sh get-batch notify.level unknown.key
# stderr: [config] get-batch: unknown key 'unknown.key'; returning null
{"notify.level": "approval_only", "unknown.key": null}
```

### `export-env`

Prints `export Z_HARNESS_<KEY>=<value>` lines for all user knobs.
Designed for `eval "$(scripts/config.sh export-env)"`.  Emits `config_resolved`
event once per `$Z_HARNESS_RUN`.

```
export Z_HARNESS_DOCS_ALWAYS_APPLY='always'
export Z_HARNESS_NOTIFY_LEVEL='approval_only'
```

### `ensure-defaults`

Writes the user-global config with defaults + inline comments if absent.
Idempotent — prints `exists <path>` if already present.  Exits 4 if the file
exists but is empty or unparseable (never silently overwrites).

```
$ scripts/config.sh ensure-defaults
created /Users/you/.config/z-harness/config.toml
```

### `explain <dotted.key>`

Prints the effective value and its source layer.

```
$ scripts/config.sh explain notify.level
notify.level = "approval_only"   (source: defaults)

$ Z_HARNESS_NOTIFY_LEVEL=all scripts/config.sh explain notify.level
notify.level = "all"   (source: env Z_HARNESS_NOTIFY_LEVEL)
```

### `should-notify --event <kind>`

Prints `yes` or `no`; always exits 0 (safe for `set -e`).  Unknown event → exit 2.
Valid event kinds: `approval`, `phase_end`, `error`.

```bash
[ "$(scripts/config.sh should-notify --event approval)" = yes ] && <PushNotification ...>
```

### `inspect-all [--json]`

Prints all configuration knobs with their current effective value, source layer, and persistence class. Covers three categories:

1. **TOML-persistent keys** — every key in `DEFAULTS` (all `notify.*`, `docs.*`, `workflow.*`, `followup.*`)
2. **Registered question_ids** — every entry in `QUESTION_IDS`, showing the resolver envelope result
3. **Env-only knobs** — environment variables that affect behavior but are never written to TOML

Default output is a human-readable concern-grouped table. `--json` emits a machine-parseable JSON object.

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

```
$ scripts/config.sh inspect-all
$ scripts/config.sh inspect-all --json
```

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

Event payload shape:

```json
{
  "values": {
    "notify.level": "approval_only",
    "docs.always_apply": "always"
  },
  "sources": {
    "notify.level": "defaults",
    "docs.always_apply": "/Users/you/.config/z-harness/config.toml"
  }
}
```

`sources` values: `"defaults"`, an absolute file path (global or repo-local), or `"env Z_HARNESS_<VAR>"`.

---

# Workflow Resolver

The slice-2 layer: the `[workflow]` config section, the question-registry, the resolver subcommand, the overnight gate system, the writer, the routing-preference memory schema, and the elevation proposer. All built on top of the Loader API.

## The knobs (Workflow Resolver)

| Key | Type | Default | Values | Description |
|-----|------|---------|--------|-------------|
| `workflow.audit_to_amend` | string | `ask` | `ask` \| `amend` \| `stop` | Controls the Phase 5 AskUserQuestion in `/z-audit-plan` and `/z-audit-plan-style`. `ask` always prompts. `amend` auto-proceeds as amend (skips prompt). `stop` auto-stops (skips prompt). |
| `workflow.slug_confirm` | string | `ask` | `ask` \| `auto_accept` \| `recommend_derived` | Controls the soft non-obvious-slug confirmation at 7 callsites. `ask` always prompts. `auto_accept` silently accepts the derived slug. `recommend_derived` pre-selects the derived slug in the AskUser prompt. **The hard slug-collision check always runs unconditionally, regardless of this setting.** |
| `workflow.implement_all_proceed` | string | `ask` | `ask` \| `auto_resume` \| `halt` | Controls the halt-resolution gate in `/z-implement-all`. `ask` prompts. `auto_resume` skips the prompt. `halt` stops unconditionally. |
| `workflow.review_all_proceed` | string | `ask` | `ask` \| `proceed` \| `halt` | Controls the Phase 3.7 proceed gate in `/z-review-all`. `ask` prompts. `proceed` skips the prompt. `halt` stops unconditionally. |
| `workflow.plan_decisions_approval` | string | `ask` | `ask` \| `approve` \| `halt` | Controls the Phase 2.5 decisions-doc approval gate in `/z-plan`. `ask` prompts. `approve` skips the prompt. `halt` stops unconditionally. |
| `workflow.spec_retro_discovery` | string | `ask` | `ask` \| `defer_to_sink_p2` | Controls how Phase 4 of `/z-implement-next` handles out-of-current-SPEC discoveries reported by the implementer. `ask` prompts interactively (default). `defer_to_sink_p2` parks the discovery as a P2 follow-up in the project sink without prompting — resolver returns `defer-to-sink`; orchestrator calls `scripts/sink-add.sh` with the question context. |

## The transliteration rule (Workflow Resolver)

| TOML key | Env var |
|----------|---------|
| `workflow.audit_to_amend` | `Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND` |
| `workflow.slug_confirm` | `Z_HARNESS_WORKFLOW_SLUG_CONFIRM` |
| `workflow.implement_all_proceed` | `Z_HARNESS_WORKFLOW_IMPLEMENT_ALL_PROCEED` |
| `workflow.review_all_proceed` | `Z_HARNESS_WORKFLOW_REVIEW_ALL_PROCEED` |
| `workflow.plan_decisions_approval` | `Z_HARNESS_WORKFLOW_PLAN_DECISIONS_APPROVAL` |
| `workflow.spec_retro_discovery` | `Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY` |

Same general rule as the Loader API surface — see [The transliteration rule](#the-transliteration-rule) for format constraints.

## CLI reference (Workflow Resolver)

### `resolve-question <question_id> [--scope-slug <slug>] [--explain]`

Returns a typed JSON envelope on stdout indicating how an AskUserQuestion should behave.
Consulted by skill prose before AskUserQuestion fires.  Never writes to config or memory.

```
$ scripts/config.sh resolve-question workflow.audit_to_amend
{
  "result":   "skip",
  "default":  "amend",
  "source":   "config",
  "rule_id":  "workflow.audit_to_amend",
  "strength": "hard",
  "reason":   "config key workflow.audit_to_amend = amend",
  "sources":  [{"kind": "config", "value": "amend", "location": ".z-harness/config.toml", "strength": "hard"}]
}
```

`result` values:
- `skip` — skip the AskUserQuestion; proceed as if the user picked `default`.
- `prefill` — present the AskUserQuestion with `default` pre-selected (recommended option).
- `ask` — present the AskUserQuestion normally.
- `halt` — do not proceed; stop the run (returned when `Z_HARNESS_NO_ASK=halt` and question is not on the overnight allowlist).
- `defer-to-sink` — do not ask interactively; instead call `scripts/sink-add.sh` with the question context to park it as a follow-up work item. Currently produced only by `workflow.spec_retro_discovery = defer_to_sink_p2`.

`source` values: `config` | `memory` | `conflict` | `none` | `override` | `overnight_allowlist` | `no_ask_halt`.

**`conflict` source:** config and memory disagree. Result is always `ask`.  The `sources[]` array lists both entries.  After the user answers, a follow-up AskUserQuestion offers to record the answer as the new preference, resolving the conflict for future runs.

**`--explain` flag (or `Z_HARNESS_EXPLAIN_RESOLUTION=1`):** prints a human-readable resolution trace on stderr.  Default off.

**`Z_HARNESS_ASK_ALL=1`:** short-circuits resolution to always return `{result: ask, source: override}`.  Use for debugging or temporary full-control.

Exit codes:
- 0 — valid JSON returned
- 2 — bad invocation (missing question_id arg)
- 3 — unknown question_id (JSON still emitted with `error` key)
- 4 — I/O error (JSON still emitted)
- 5 — config conflict: `Z_HARNESS_ASK_ALL=1` and `Z_HARNESS_NO_ASK=halt` are both set (mutually exclusive)

**Error handling in skill prose:** always capture exit code separately — never pipe through chains that swallow it.  On any non-zero exit, fall through to `ask`.

```bash
RESOLVED="$(python3 scripts/config.py resolve-question workflow.audit_to_amend)"
RESOLVE_EXIT=$?
if [[ $RESOLVE_EXIT -ne 0 ]]; then
  echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
  RESULT="ask"; DEFAULT=""; SOURCE="error"
else
  RESULT="$(echo "$RESOLVED" | jq -r .result)"
  DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
  SOURCE="$(echo "$RESOLVED" | jq -r .source)"
fi
```

### `check-no-ask --question-id <id>`

Lightweight overnight-gate checker. Returns `{"result": "halt"|"proceed", "question_id": "<id>", "rule_id": "<rule>"}` without going through the full resolution envelope. Used by `/z-implement-all` and other commands that need a simpler halt/proceed decision.

Paths:
1. `Z_HARNESS_NO_ASK != halt` → `proceed`, `rule_id=no_overnight_active`
2. `NO_ASK=halt`, question registered, on allowlist → `proceed` (treated as overnight_decision)
3. `NO_ASK=halt`, question registered, NOT on allowlist → `halt`
4. `NO_ASK=halt`, question NOT registered → `halt` + emits `unknown_ask_blocked` event

Always exits 0 on valid invocations; exits 2 on argparse error.

```bash
NO_ASK_RESULT="$(python3 scripts/config.py check-no-ask --question-id workflow.implement_all_proceed)"
if [[ "$(echo "$NO_ASK_RESULT" | jq -r .result)" == "halt" ]]; then
  # stop queue
fi
```

### `set <dotted.key> <value> [--scope=global|project]`

Atomically writes a TOML key to the user-global config (`~/.config/z-harness/config.toml`) or the
repo-local config (`.z-harness/config.toml`).  Validates against `VALIDATORS` before writing;
exits 2 with a clear message if the value is invalid.  Exits 0 silently on success (no stdout output).

```
$ scripts/config.sh set workflow.audit_to_amend amend --scope=project
(exits 0, no stdout output on success)
```

Default scope when `--scope` is omitted: `project`.

### `list-question-ids`

Prints a JSON array of all known question IDs in the `QUESTION_IDS` registry.
Consumed by `/z-suggest-memory --kind routing-preference` to validate `--question-id` inputs.

```
$ scripts/config.sh list-question-ids
["workflow.audit_to_amend", "workflow.implement_all_proceed", "workflow.plan_decisions_approval", "workflow.review_all_proceed", "workflow.slug_confirm", "workflow.spec_retro_discovery"]
```

### `migrate`

Rewrites old provider names (`codex`, `gemini`, `claude`) in `roles.*.runtime` config values to the new `-cli` suffixed form (`codex-cli`, `gemini-cli`, `claude-cli`). Applied to both global and project layers. Idempotent; skips missing files. Exits 4 on I/O error, else exits 0.

```
$ scripts/config.sh migrate
[config] migrate: global — rewrote 2 runtime value(s) in /Users/you/.config/z-harness/config.toml
```

## Overnight gate system

When `/z-overnight` or any other caller sets `Z_HARNESS_NO_ASK=halt`, the resolver applies an additional post-processing pass (`_apply_overnight_overrides`) to every `resolve-question` call:

1. If `Z_HARNESS_ASK_ALL=1` is simultaneously set → **exit 5** (config conflict; mutually exclusive).
2. If the resolved result is already `skip` or `prefill` (no ask needed) → **no-op**.
3. If the resolved result is `ask` and the `question_id` is in the overnight allowlist → swap to an `overnight_decision` envelope (result derived from the allowlist value via `RESULT_MAP`); emit `overnight_decision` event.
4. If the resolved result is `ask` and the `question_id` is NOT in the allowlist → swap to `halt` envelope; emit `askuser_halted` event.

**Default allowlist** (`OVERNIGHT_AUTODECIDE_QIDS_DEFAULT`):

| question_id | chosen value |
|-------------|-------------|
| `workflow.slug_confirm` | `recommend_derived` |
| `workflow.audit_to_amend` | `amend` |

**Custom allowlist:** set `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` to a JSON object of `{question_id: value}` entries. These are merged over the defaults (env wins on key collision). Malformed entries are dropped with a `routing_preference_malformed` event; an unparseable JSON string causes the env layer to be skipped (defaults still apply).

**New telemetry events:**

| Event | Emitted when |
|-------|-------------|
| `overnight_decision` | Question auto-decided from allowlist |
| `askuser_halted` | Question would have asked but is not on allowlist |
| `unknown_ask_blocked` | `check-no-ask` called with unregistered question_id |
| `config_conflict` | `Z_HARNESS_ASK_ALL=1` + `Z_HARNESS_NO_ASK=halt` both set |

## Key entry points

- `scripts/config.py:51` — `DEFAULTS` — built-in default values for all config keys including `[workflow]` and `[followup]` sections (layer 1)
- `scripts/config.py:86` — `VALIDATORS` — allowed enum sets per dotted-key; hard-fail on repo/env, soft-warn on global
- `scripts/config.py:102` — `QUESTION_IDS` — single source of truth for AskUserQuestion routing-class preference keys; validated against `VALIDATORS` at module load by `_run_startup_guards`
- `scripts/config.py:172` — `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT` — default overnight allowlist; question IDs auto-decided without halting
- `scripts/config.py:178` — `RESULT_MAP` — maps `(question_id, option-domain-value)` to resolver result-domain (`skip|prefill|ask|halt|defer-to-sink`)
- `scripts/config.py:204` — `_run_startup_guards` — module-load consistency check; raises `SystemExit(2)` on registry inconsistency
- `scripts/config.py:507` — `load_config` — build resolved config from all 4 layers; returns `(values, sources)` dicts
- `scripts/config.py:660` — `cmd_get` — resolve and print single key; exits 3 on unknown or meta key
- `scripts/config.py:688` — `cmd_get_batch` — resolve multiple keys in one process; outputs JSON object; always exits 0
- `scripts/config.py:717` — `cmd_export_env` — print export lines for all user knobs; emit `config_resolved` once per run
- `scripts/config.py:735` — `cmd_ensure_defaults` — write global config with defaults + inline comments if absent
- `scripts/config.py:812` — `cmd_explain` — print effective value and source layer for one key
- `scripts/config.py:844` — `cmd_list_question_ids` — print JSON array of known question IDs
- `scripts/config.py:1013` — `_apply_overnight_overrides` — post-process resolution envelope for overnight/halt-from-ask behavior
- `scripts/config.py:955` — `_parse_overnight_allowlist` — parse `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` JSON and merge with defaults
- `scripts/config.py:1179` — `_load_memory_matches` — walks `docs/llm/*.json` for `routing-preference` entries matching `question_id`; respects scope
- `scripts/config.py:1287` — `_resolve_memory_matches` — merges memory entries; highest strength wins on agreement; returns `conflict` on disagreement
- `scripts/config.py:1323` — `_build_resolve_envelope` — core resolver logic: config + memory signal combination
- `scripts/config.py:1546` — `cmd_resolve_question` — consults 4-layer config + memory + overnight overrides; returns JSON envelope
- `scripts/config.py:1669` — `cmd_check_no_ask` — lightweight overnight-gate checker; returns halt/proceed JSON
- `scripts/config.py:1875` — `cmd_set` — atomically write a TOML key to global or project config via tmp+rename
- `scripts/config.py:1957` — `ENV_ONLY_KNOBS` — list of env-only knob names surfaced by `inspect-all`
- `scripts/config.py:1997` — `cmd_inspect_all` — print all config knobs with source and persistence metadata; supports `--json`
- `scripts/config.py:2109` — `cmd_should_notify` — print yes|no for a given event kind; always exits 0; exits 2 on unknown event
- `scripts/config.py:2176` — `cmd_migrate` — rewrite old provider names in `roles.*.runtime` values to `-cli` suffixed form; idempotent
- `scripts/propose-prefs.py:1` — `propose-prefs` (module) — walks `metrics.jsonl` for repeated command-pair patterns; emits JSON proposal if threshold met; never writes

## `routing-preference` memory type

Workflow preferences can also live as memory entries in `docs/llm/workflow.json`
(global scope) or `docs/llm/workflow-<project-slug>.json` (project scope).
The resolver reads these alongside the TOML config and applies a 5-tier
signal-strength model.

Write a routing-preference memory via:

```bash
/z-suggest-memory --kind routing-preference \
  --question-id workflow.audit_to_amend \
  --value amend \
  --strength very_strong \
  --scope project
```

### Memory entry shape

```json
{
  "type": "routing-preference",
  "question_id": "workflow.audit_to_amend",
  "value": "amend",
  "scope": "project",
  "strength": "very_strong",
  "reason": "Always amend after audit on this project",
  "date": "2026-05-27",
  "project_root": "/Users/you/dev/myproject"
}
```

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `type` | yes | `routing-preference` | Identifies this as a routing-preference memory |
| `question_id` | yes | any key in `QUESTION_IDS` registry | Which AskUserQuestion this governs |
| `value` | yes | valid choices for `question_id` | The preferred option |
| `scope` | yes | `global` \| `project` | `global` applies everywhere; `project` applies only when `Z_HARNESS_PROJECT_ROOT` matches `project_root` |
| `strength` | yes | `weak` \| `strong` \| `very_strong` | Signal strength; `very_strong` → `skip`, `strong`/`weak` → `prefill` |
| `reason` | yes | string | Human-readable rationale |
| `date` | yes | ISO 8601 | When the entry was written |
| `project_root` | when `scope=project` | absolute path | Must match `Z_HARNESS_PROJECT_ROOT` (or `git rev-parse --show-toplevel`) |

### Resolver tier-mapping

| Source | Strength | Result |
|--------|----------|--------|
| config (any non-default value) | `hard` | `RESULT_MAP[(question_id, config_value)]` |
| memory | `very_strong` | `skip` |
| memory | `strong` | `prefill` |
| memory | `weak` | `prefill` |
| config + memory (agreeing) | highest | config wins |
| config + memory (disagreeing) | — | `ask` (conflict tier; both sources listed) |
| none | — | `ask` |
| `Z_HARNESS_ASK_ALL=1` | — | `ask` (override) |
| `Z_HARNESS_NO_ASK=halt` + not in allowlist | — | `halt` |
| `Z_HARNESS_NO_ASK=halt` + in allowlist | — | `skip`/`prefill` (via `RESULT_MAP`) |

## Elevation proposer

`scripts/propose-prefs.py` walks `metrics.jsonl` for repeated command-pair
patterns and surfaces a one-shot AskUserQuestion when the threshold is met.

Configurable via env:

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_PROPOSE_WINDOW_S` | `3600` | Max seconds between command A end and B start |
| `Z_HARNESS_PROPOSE_THRESHOLD` | `3` | Min repetitions to propose |
| `Z_HARNESS_PROPOSE_MAX_RUNS` | `30` | Number of recent run_start events to scan |

v1 watched patterns:
- `/z-audit-plan → /z-amend` — propose `workflow.audit_to_amend = "amend"`
- `/z-audit-plan-style → /z-amend` — propose `workflow.audit_to_amend = "amend"`

The proposer never writes automatically.  The user picks: accept as config, accept
as memory (very_strong / strong), or no.  Rejecting suppresses the proposal for
30 days, scoped to `(project_root, question_id)` in `.z-harness/.propose-suppress`.

## `askuser_resolved` event

Every successful `resolve-question` call emits an `askuser_resolved` event to
`metrics.jsonl`.

```json
{
  "kind": "askuser_resolved",
  "question_id": "workflow.audit_to_amend",
  "result": "skip",
  "source": "config",
  "strength": "hard"
}
```

`/z-stats` Phase 4c aggregates these by result, source, question_id, and conflict rate.

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
| `followup.auto_close_low_risk_enabled` | bool | `true` | `true` \| `false` | Master kill-switch for the auto-close-low-risk completion path. Defaults to `true` (on). Set to `false` to disable auto-close entirely. When false, `auto_close_eligible` entries still flow through verify but the ceiling never fires. |
| `followup.auto_close_low_risk_path_allowlist` | array\<string\> | `["docs/**/*.md", "**/CHANGELOG", "**/CHANGELOG.md"]` | glob patterns | Paths safe for auto-close. All touched paths must match at least one allowlist pattern. Default deliberately excludes `commands/**`, `agents/**`, and top-level `*.md`. |
| `followup.auto_close_low_risk_path_denylist` | array\<string\> | `["commands/**/*.md", "agents/**/*.md", ".claude/**/*.md", "/*.md"]` | glob patterns | Paths that block auto-close regardless of allowlist. Denylist takes precedence. Note: the last entry is `/*.md` (root-anchored, blocks top-level `.md` files) not `*.md` (would block all `.md` at any depth). |
| `followup.staleness_commit_window` | int | `50` | positive int | Commit distance (`git rev-list --count capture_head..HEAD`) above which staleness prompt fires at claim time. |
| `followup.staleness_warn_days` | int | `30` | positive int | Age in days after which a soft staleness warning is shown at claim time. Does not block. |
| `followup.staleness_hard_dismiss_days` | int | `0` | int | Age in days after which entries are auto-dismissed. `0` = disabled (default). Enable by setting a positive integer. |
| `followup.audit_evidence_required_artifacts` | array\<string\> | `["z_review_all_verdict", "test_exit", "cumulative_diff"]` | artifact kinds | Named artifact kinds that must be present in an `audit_evidence.json` blob. |

### `Z_HARNESS_NOTION_TOKEN` — env-only secret

`Z_HARNESS_NOTION_TOKEN` is an **env-only** Notion API token override. It is NOT a TOML config key and does not appear in `DEFAULTS` or `VALIDATORS`. When set to a non-empty string, `scripts/notion-push.py`'s `_resolve_token()` uses it directly, bypassing the `followup.notion_token_path` secrets file lookup entirely.

Use this for CI environments where writing a secrets file is inconvenient:
```bash
export Z_HARNESS_NOTION_TOKEN="secret_xxxx..."
```

Callers and wrappers of `notion-push.py` **must not run under `set -x`** — doing so would leak the token value into logs.

**Validators** (hard-fail on repo/env layer, soft-warn on global layer):
- `followup.default_sink`: must be `project` or `global`
- `followup.notion_enabled`: must be `true` or `false`
- `followup.auto_close_low_risk_enabled`: must be `true` or `false`

All other `[followup]` keys are not in `VALIDATORS` and are accepted as-is (type check only by Python's TOML parser).

## defer-to-sink resolver result

`defer-to-sink` is a resolver result value added alongside `skip|prefill|ask|halt`. When a question callsite resolves to `defer-to-sink`, the orchestrator does NOT present an `AskUserQuestion`. Instead it calls `scripts/sink-add.sh` with the question context to park it as a P2 follow-up work item.

**Currently produced by:** `workflow.spec_retro_discovery = defer_to_sink_p2` (Phase 4 of `/z-implement-next`).

**Orchestrator handler pattern:**
```bash
# On result == defer-to-sink:
scripts/sink-add.sh \
  --sink=<followup.default_sink> \
  --priority=P2 \
  --name="<question-id> decision deferred" \
  --recommended-command="/z-do \"<question context>\"" \
  --source-artifact="<current plan artifact>" \
  --cited-paths="<relevant paths>"
# Defaults: auto_close_eligible=false, safe_to_retry=false
```

---

# Common

Cross-cutting material that applies to both surfaces.

## How it interacts with others

- `commands` (z-audit-plan, z-audit-plan-style, z-plan, z-fix, z-uplift, z-amend, z-do, z-research, z-implement-all, z-review-all, z-overnight, z-implement-next) — call `export-env` + `should-notify` during Setup; call `resolve-question` before workflow AskUserQuestions; call `check-no-ask` for overnight gate checks; call `set` after proposal acceptance; call `propose-prefs.py` at command end
- `skills` (z-suggest-memory, z-map, z-plan-light, z-debug, z-brainstorm, z-do, z-plan, z-research) — call `list-question-ids` to validate routing-preference question IDs; call `resolve-question` for slug-confirm gate; call `export-env` + `should-notify` during Setup
- `scripts` — provides the `log-event.sh` + `log-phase.sh` telemetry pipeline that `config.py` writes events through (`config_resolved`, `askuser_resolved`, `overnight_decision`, `askuser_halted`, `unknown_ask_blocked`, `config_conflict`)
- `followup-sink` — `sink-add.sh` called by orchestrators when `resolve-question` returns `defer-to-sink`; creates follow-up entries in the project or global sink; `notion-push.py` reads `Z_HARNESS_NOTION_TOKEN` env override or `followup.notion_token_path` secrets file for Notion auth

## Examples

**User-global config** (`~/.config/z-harness/config.toml`) — Loader API knobs only:

```toml
schema_version = 1

[notify]
# off | approval_only | all
level = "all"

[docs]
# always | never  (applies to light flows only)
always_apply = "never"
```

**Repo-local override** (`.z-harness/config.toml` at git root) — silence notifications for this repo only (Loader API):

```toml
schema_version = 1

[notify]
level = "off"
```

**Workflow preferences** (`.z-harness/config.toml` at git root) — Workflow Resolver knobs:

```toml
schema_version = 1

[workflow]
# ask | amend | stop
audit_to_amend = "amend"

# ask | auto_accept | recommend_derived
slug_confirm = "recommend_derived"

# ask | auto_resume | halt
implement_all_proceed = "auto_resume"

# ask | proceed | halt
review_all_proceed = "proceed"

# ask | approve | halt
plan_decisions_approval = "approve"

# ask | defer_to_sink_p2
spec_retro_discovery = "defer_to_sink_p2"
```

**Follow-up namespace** (`.z-harness/config.toml` at git root):

```toml
[followup]
default_sink = "project"
notion_enabled = false
auto_close_low_risk_enabled = true
staleness_commit_window = 50
staleness_warn_days = 30
staleness_hard_dismiss_days = 0
```

**Env override for CI** — covers both surfaces:

```bash
export Z_HARNESS_NOTIFY_LEVEL=off
export Z_HARNESS_DOCS_ALWAYS_APPLY=never
export Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND=amend
export Z_HARNESS_WORKFLOW_SLUG_CONFIRM=auto_accept
```

**Overnight mode with custom allowlist:**

```bash
export Z_HARNESS_NO_ASK=halt
export Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE='{"workflow.slug_confirm":"recommend_derived","workflow.plan_decisions_approval":"approve"}'
```

**Batch key lookup (reduce N forks to 1):**

```bash
BATCH="$(python3 scripts/config.py get-batch notify.level followup.notion_enabled followup.default_sink)"
NOTIFY_LEVEL="$(echo "$BATCH" | jq -r '.["notify.level"]')"
NOTION_ENABLED="$(echo "$BATCH" | jq -r '.["followup.notion_enabled"]')"
```

## Edge cases / gotchas

- `workflow.slug_confirm` value domain (`ask`/`auto_accept`/`recommend_derived`) is NOT the same as the resolver result domain (`ask`/`prefill`/`skip`); `RESULT_MAP` translates between them — `auto_accept` → `skip`, `recommend_derived` → `prefill`
- Slug-confirm has TWO gates: hard collision check (always runs, resolver NOT consulted) + soft non-obvious confirmation (resolver-controlled). `resolve-question` only governs the soft gate
- `Z_HARNESS_ASK_ALL=1` and `Z_HARNESS_NO_ASK=halt` are mutually exclusive — setting both causes `resolve-question` to exit 5 (not 0); check for this conflict before setting both in scripts
- `check-no-ask` fails closed on unregistered question IDs when `NO_ASK=halt` — unknown question → `halt` + `unknown_ask_blocked` event
- `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` must be valid JSON and a JSON object; malformed JSON causes the env layer to be skipped entirely (defaults still apply); malformed individual entries are dropped individually
- Capture exit code separately from output: `RESOLVED=$(python3 scripts/config.py resolve-question ...); RESOLVE_EXIT=$?`. Never pipe through `set -e` chains that swallow exit codes
- When `source==conflict`, AskUser surfaces a follow-up write-back question after the user picks, to prevent conflict persisting across runs
- The proposer in v1 only watches command-pair patterns via `run_start`/`run_end` in `metrics.jsonl`; it does NOT auto-propose `workflow.slug_confirm` because AskUser responses are not yet recorded in metrics.jsonl
- Stale routing-preference memory after config supersedes it: v1 emits `memory_potentially_superseded` warning; cleanup is a v2 concern
- Memory entries missing required fields are logged as `routing_preference_malformed` events and skipped (no crash)
- Resolver falls back to `git rev-parse --show-toplevel` for `project_root` when `Z_HARNESS_PROJECT_ROOT` is unset; treats all memories as global when outside a git repo
- `_run_startup_guards()` runs at module load and raises `SystemExit(2)` if `QUESTION_IDS`, `VALIDATORS`, and `RESULT_MAP` are internally inconsistent — add to both registries when extending
- `cmd_set` exits 0 silently on success; it does NOT print a confirmation line to stdout. Check exit code only
- Valid event kinds for `should-notify` are `approval`, `phase_end`, `error` only — passing `run_complete` (used by some callers such as `z-research`) exits 2; guard with `|| true` if needed
- `defer-to-sink` result must NOT be treated as `skip` — the orchestrator must explicitly call `scripts/sink-add.sh`; absence of that call silently drops the discovery
- `[followup]` keys that are arrays (e.g. `auto_close_low_risk_path_allowlist`) are NOT in `VALIDATORS` and receive no enum validation; the TOML parser accepts any array
- `followup.auto_close_low_risk_enabled` defaults to `true` (on by default); set to `false` to disable — do not assume the default is off
- `followup.auto_close_low_risk_path_denylist` last entry is `"/*.md"` (root-anchored, blocks top-level `.md` files only), NOT `"*.md"` (which would block all `.md` at any depth including `docs/**/*.md`). Pathspecs with a leading slash are restricted to top-level only.
- `Z_HARNESS_NOTION_TOKEN` is env-only (not a TOML key); it overrides `followup.notion_token_path` secrets file lookup in `notion-push.py`. Never log it; never run `notion-push.py` wrappers under `set -x`.
- `get-batch` always exits 0 — it does NOT exit 3 for unknown keys the way `get` does. Callers must check for `null` values in the JSON output to detect missing keys.
- `inspect-all` is the canonical introspection tool — use it (not repeated `get` calls) when you need to audit the full current configuration state.

## v2 deferrals

The following are known issues documented in SPEC but deferred to v2:

- **Stale-memory hygiene** — when a routing-preference memory exists and the user writes the same `question_id` to config, the memory continues to appear in conflict checks. v1 emits `memory_potentially_superseded`; v2 will add a cleanup prompt.
- **`config.py set --dry-run` / `--backup`** — v2 will add dry-run and pre-overwrite backup flags.
- **Async memory-write telemetry** — `askuser_resolved` source field reflects intent in v1; v2 will log only after `/z-suggest-memory` returns 0.
- **Multi-IDE export precheck** — Cursor, Codex CLI, and agy fall back to raw AskUserQuestion in v1; precheck integration is a v2 concern.
- **Halt-class bypass** (`spec_problem`, `decision_needed`) — explicitly out of v1.

## Future knobs

Slices 2 and 3 of this feature (see `z-harness/z-harness-config-toml/BRAINSTORM.md`)
plan additional knobs for consult preferences, escalation budgets, archive
retention, and prompt-fragment injection.

**Do not add knobs without a `/z-plan` run.** Schema sprawl is the most common
failure mode for config systems — every new knob must be designed, documented,
and validated before it ships.  Undocumented knobs break the two-tier doc
contract and silently diverge from `docs/llm/config.json`.
