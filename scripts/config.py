#!/usr/bin/env python3
"""
config.py — z-harness layered TOML config loader.

Subcommands:
  get <dotted.key>                        Resolve a single key and print its value.
  export-env                              Print export lines for all non-meta keys.
  ensure-defaults                         Write global config with defaults if absent.
  explain <dotted.key>                    Print value + source layer.
  should-notify --event <kind>            Print yes/no notification gate.
  list-question-ids                       Print sorted JSON array of registered question IDs.
  resolve-question <question_id>          Return JSON resolver envelope for a question ID.
  check-no-ask --question-id <id>        Return JSON halt/proceed for overnight gate checks.
                [--range-high N]         Token estimate ceiling (cost-gate delegation path).
                [--severity hard|soft]   Gate severity; soft→always auto_proceed.
  inspect-all [--json]                   Print all config knobs with source and persistence metadata.
  resolve-halt-category <question_id>    Print the halt_category tag for a question ID, or "ask" for unknown.

Layer order (lowest → highest priority):
  1. Built-in defaults (DEFAULTS)
  2. $XDG_CONFIG_HOME/z-harness/config.toml  (global user)
  3. Repo-local: $Z_HARNESS_REPO_CONFIG or <git-toplevel>/.z-harness/config.toml
  4. Env vars: Z_HARNESS_<SECTION>_<KEY> (empty = missing)

Exit codes:
  0  Success
  2  Schema / validation error
  3  Unknown dotted-key
  4  I/O error (ensure-defaults edge cases, permission denied)
  5  Config conflict (Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt both set)
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        sys.exit("config.py requires tomllib (Python 3.11+) or tomli (pip install tomli)")

try:
    import tomlkit
    _TOMLKIT_AVAILABLE = True
except ImportError:
    _TOMLKIT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DEFAULTS: dict = {
    "schema_version": 2,
    "notify": {
        "level": "approval_only",       # off | approval_only | all
        "discord_webhook_url": "",      # string: Discord webhook URL (empty = disabled)
        "hermes_webhook_url": "",       # string: Hermes webhook URL (empty = disabled)
        "hermes_webhook_secret": "",    # string: HMAC-SHA256 signing secret for Hermes webhook (empty = disabled)
    },
    "docs": {
        "always_apply": "always",   # always | never
        "staleness_threshold": 20,  # int>0: percent of stale concepts that triggers a warning gate
    },
    "workflow": {
        "audit_to_amend": "ask",          # ask | amend | stop
        "slug_confirm":   "ask",          # ask | auto_accept | recommend_derived
        "implement_all_proceed": "ask",   # ask | auto_resume | halt
        "review_all_proceed":    "ask",   # ask | proceed | halt
        "plan_decisions_approval": "ask", # ask | approve | halt
        "pre_run_cost_gate": "ask",       # ask | auto_proceed | halt
        "planning_mode": "intent",        # intent | full
        "intent_level": "auto",           # auto | quick | standard | deep
        # LIVE within-level concurrency lever for /z-execute INTENT mode (contrast with
        # the vestigial runtime.max_parallel / runtime.max_parallel_plans above). Gated
        # in skills/z-execute/SKILL.md's "Parallelism (read first)" rule 0: true
        # allows independent same-level siblings to dispatch concurrently per
        # workstreams.json; explicit false serializes each BFS level.
        "intent_parallel_levels": True,   # bool: execute same-level tasks in parallel
        "hermes_enabled": False,          # bool: gate all old Hermes machinery
        "max_explore": 3,                 # int>0: max Explore subagent dispatches per /z-plan run
        "parallel": 3,                    # int>0: parallel batch size for z-maintain-docs and similar batch ops
        "memory_stale_days": 547,         # int>0: days after which memory entries are considered stale (z-maintain-docs)
    },
    "followup": {
        "default_sink":                      "project",    # project | global
        "notion_enabled":                    False,
        "notion_database_id":                "",
        "notion_token_path":                 "~/.z-harness/secrets.toml",
        "auto_close_low_risk_enabled":       True,   # master kill-switch; on by default, flip to False to disable auto-close
        "auto_close_low_risk_path_allowlist": ["docs/**/*.md", "**/CHANGELOG", "**/CHANGELOG.md"],
        # Pathspec semantics: a pattern with no slash (like *.md) matches any
        # depth; root-anchoring with a leading slash (/*.md) restricts it to
        # top-level files only, matching the intended "block root-level .md"
        # behaviour without accidentally blocking docs/**/*.md entries.
        "auto_close_low_risk_path_denylist":  ["skills/**/*.md", "agents/**/*.md", ".claude/**/*.md", "/*.md"],
        "staleness_commit_window":           50,
        "staleness_warn_days":               30,
        "staleness_hard_dismiss_days":       0,
        "audit_evidence_required_artifacts": ["z_review_all_verdict", "test_exit", "cumulative_diff"],
    },
    "axioms": {
        "enabled":               True,   # bool: enable axioms extraction pipeline
        "kernel_budget_chars":   6000,   # int: max chars of axiom text in context kernel
        "extract_min_recurrence": 3,     # int: minimum recurrences before auto-extracting an axiom
        "auto_extract_post_run": True,   # bool: run axiom extraction automatically after each run
    },
    "brainstorm": {
        "personas":              True,   # bool: inject persona diversity in /z-brainstorm
        "wide_overflow_model":   "haiku", # str: model for overflow ideators in wide mode; "haiku" | "cheap-mixed" | explicit model string
    },
    "changelog": {
        # Post-commit hook that drafts a human-readable CHANGELOG.md bullet.
        # Installed per-repo via scripts/install-changelog-hook.sh; these knobs
        # gate it at run-time so it can be disabled without uninstalling.
        "auto":  True,                  # bool: master switch for the post-commit changelog hook
        "types": ["feat", "fix"],       # list: conventional-commit types that earn a bullet
        "file":  "CHANGELOG.md",        # str: changelog path, relative to repo root
        "repos": ["*"],                 # list: repo-id allowlist; "*" = every repo
    },
    "personas": {
        "critique_panel":      True,    # bool: inject persona diversity in /z-plan critique panels
        "audit":               True,    # bool: inject persona diversity in /z-audit dimension auditors
        "review_eval":         True,    # bool: add advisory eval-reviewer arm at code-review gates
        "implementer_retry":   "same",  # same | new: persona draw strategy on implementer retry
        "consult_eval":        False,   # bool: add advisory persona consult arm (OFF by default — most expensive, lowest-signal)
    },
    "experiment": {
        "persona_rotation":  True,   # bool: enable persona rotation across z-harness roles
        "control_every_n":   5,      # int>0: forced-control cadence (every Nth implementer attempt)
    },
    "runtime": {
        # on | off — off = single-model mode: consultant/reviewer roles resolve to
        # the "none" sentinel so cross-LLM consult and review are skipped. Exported
        # as Z_HARNESS_CONSULT (see _ENV_VAR_ALIASES), which resolve-provider reads.
        "consult": "on",
        # Pre-review gates (opt-in, default off). Exported as Z_HARNESS_PRE_REVIEW /
        # Z_HARNESS_IMPL_PRE_REVIEW (see _ENV_VAR_ALIASES for legacy names).
        "pre_review": False,        # bool: enable pre-review cycle in /z-review-all and /z-audit-plan
        "impl_pre_review": False,   # bool: enable pre-review gate in /z-execute
        # Auto-wait / wait-for knobs. Exported as Z_HARNESS_AUTO_WAIT /
        # Z_HARNESS_AUTO_WAIT_BUDGET_SECS (see _ENV_VAR_ALIASES for legacy names).
        "auto_wait": True,              # bool: 1=auto-budget mode, 0=explicit-timeout mode
        "auto_wait_budget_secs": 300,   # int>0: auto-wait budget in seconds (auto mode)
        # Context-window pause threshold. Exported as Z_HARNESS_PAUSE_AT_PCT.
        "pause_at_pct": 85,         # int>0: context fill % at which to pause; 85 = pause at 85%
        # Fallback context window for rough pressure estimates when the host/editor
        # does not report one. Host env Z_HARNESS_CONTEXT_WINDOW_TOKENS takes
        # precedence in the estimator; this config value is the stable fallback.
        "context_window_tokens": 200000,  # int>0: explicit fallback context window tokens
        # Resolver verbosity. Exported as Z_HARNESS_EXPLAIN_RESOLUTION.
        "explain_resolution": False,  # bool: print resolver decision tree to stderr
        # Parallelism knobs. Exported as Z_HARNESS_RUNTIME_MAX_PARALLEL / Z_HARNESS_MAX_PARALLEL_PLANS.
        # (Ingress also accepts legacy HERMES_MAX_PARALLEL via _INGRESS_LEGACY_ALIASES.)
        # VESTIGIAL: defined/validated/env-aliased here but not consulted by any dispatch
        # path in scripts/, skills/, or runtime/ — setting these has no effect on
        # concurrency. The live within-level lever is workflow.intent_parallel_levels
        # (see workflow.intent_parallel_levels below), gated in
        # skills/z-execute/SKILL.md's "Parallelism (read first)" rule 0. See
        # docs/human/config.md and docs/human/hermes-orchestration.md.
        "max_parallel": 1,            # int>0: max concurrent workstream sessions (within-plan)
        "max_parallel_plans": 1,      # int>0: max concurrent plan runs (cross-plan)
        # Per-task attempt / wall-clock caps. Exported as Z_HARNESS_MAX_ATTEMPTS / Z_HARNESS_MAX_TASK_WALL_MS.
        "max_attempts": 2,            # int>0: max implementer attempts per task in /z-execute
        "max_task_wall_ms": 2700000,  # int>0: per-task wall-clock cap in ms (default 45 min)
        # Deprecation enforcement. When true, detecting a preference-class env var
        # (any var in _collect_deprecated_env_vars()) is a hard ERROR (non-zero exit)
        # instead of a non-fatal warning.  Default false (grace period).
        # Set via config.toml [runtime] env_strict = true — NOT a raw env var.
        "env_strict": False,          # bool: upgrade deprecation warnings to errors
    },
    "cost": {
        "token_budget": None,             # int > 0 or None (unset)
    },
    "models": {
        # Per-role model overrides.  Empty string = absent (use provider default).
        # Validity of the model/vendor string is cross-checked against providers.json
        # at RESOLVE time (T007), NOT at config-load time.
        "consultant_primary":   "",   # model for the primary consultant role
        "consultant_secondary": "",   # model for the secondary consultant role
        "reviewer":             "",   # model for the reviewer role
        "implementer":          "",   # model for the implementer role
        "pre_reviewer":         "",   # model for the pre-reviewer role
    },
    "model_classes": {
        # Local model classes for native-agent routing.  Each class carries BOTH a
        # legacy host-blind scalar (`model`/`thinking`/`reasoning`, retained for
        # backward-compat with pre-host-axis user configs) AND a host axis: a
        # per-host-family `(model, effort)` pair the route resolver (T002) selects
        # from the detected host.  Host families are exactly two:
        #   `claude` — native Claude Code hosts (effort applied via subagent frontmatter)
        #   `omp`    — every non-claude host (pi/codex/cursor/antigravity/unknown);
        #              effort is baked into the omp catalog model name, so its
        #              `effort` field is the empty-string sentinel.
        # The legacy scalar `model` mirrors the claude-family model so old configs
        # and host-blind lookups keep their prior values; new dispatch reads the
        # host-keyed keys.  The config loader only stores validated strings.
        "cheap": {
            "model": "haiku",
            "thinking": "",
            "reasoning": "",
            "claude": {"model": "haiku", "effort": ""},
            "omp": {"model": "gpt-5.6-luna-low", "effort": ""},
        },
        "low": {
            "model": "sonnet",
            "thinking": "",
            "reasoning": "",
            "claude": {"model": "sonnet", "effort": "medium"},
            "omp": {"model": "gpt-5.6-terra-low", "effort": ""},
        },
        "standard": {
            "model": "sonnet",
            "thinking": "",
            "reasoning": "",
            "claude": {"model": "sonnet", "effort": "high"},
            "omp": {"model": "gpt-5.6-terra-medium", "effort": ""},
        },
        "deep": {
            "model": "opus",
            "thinking": "",
            "reasoning": "",
            "claude": {"model": "opus", "effort": "high"},
            "omp": {"model": "gpt-5.6-sol-medium", "effort": ""},
        },
    },
    "model_routing": {
        # Native agents default to their checked-in frontmatter model unless a
        # specific agent key is configured under [model_routing.native_agents].
        # This preserves cheap Haiku and standard Sonnet agent defaults exactly.
        "native_agents": {
            "default": "",
        },
        # Implementer tiers route through the host-keyed model classes (T003):
        # each tier names a class, which resolve_model_route expands to the
        # detected host's (model, effort) pair.  low→low, medium→standard,
        # high→deep, retry→deep.  A repo/user config may still pin an exact
        # model label per tier to bypass class routing.
        "implementer": {
            "low": "low",
            "medium": "standard",
            "high": "deep",
            "retry": "deep",
        },
    },
    "export": {
        # Which export hosts to target.  Absent → all four current defaults.
        # Closed set: adapter names {claude, antigravity, cursor, codex} ∪
        # export-only driver names {pi, windsurf, cline, kiro, copilot}.
        # Env transport: Z_HARNESS_EXPORT_HOSTS as JSON-encoded array string.
        "hosts": ["cursor", "codex", "agy", "omp", "pi"],  # default "all" set; omp is a first-class native host
        # Export strategy enum.  Each driver interprets it for its host.
        # pointer  — single capabilities-pointer rule file
        # curated  — always-on agent subset (mirrors agy _ALWAYS_ON_AGENTS)
        # full     — one file per source (only for hosts with on-demand inclusion)
        # ""       — sentinel: defer to per-driver default (no global override).
        #            Absent [export] section → each driver uses its own default_strategy
        #            (e.g. cline → pointer, windsurf/kiro → curated).
        "strategy": "",  # empty sentinel = defer to per-driver default
    },
    "watchdog": {
        # Master switch for the background sweep layer (watchdog-sweep.sh).
        "enabled": True,                 # bool
        # How often the sweep polls events.jsonl / liveness.sh (seconds).
        "sweep_interval_secs": 60,       # int>0
        # What to do when a stall is detected.
        # observe: emit watchdog_stall event only.
        # notify: emit event + call notify-watchdog.sh (default).
        "intervention_level": "notify",  # observe | notify
        # SIGTERM→SIGKILL grace period used by supervised-run.sh bash fallback (seconds).
        "kill_grace_secs": 10,           # int>0
        # Safety backstop: sweep self-exits after this many seconds to prevent orphan leak.
        "max_lifetime_secs": 86400,      # int>0
        # Age threshold for liveness.sh subagent stale detection (seconds).
        "stale_secs": 300,               # int>0
        # Per-dispatch-type hard deadline defaults for supervised-run.sh.
        # READ VIA config.py get watchdog.timeout_secs.<type> ONLY — NOT env-exported.
        # A typo'd Z_HARNESS_WATCHDOG_TIMEOUT_SECS env var is silently ignored.
        "timeout_secs": {               # nested table: config-file-only, not env-exported
            "bash": 600,
            "ssh": 600,
            "rsync": 660,
            "cargo": 1800,
            "reviewer": 300,
        },
    },
}


def _validate_bool(value: object) -> bool:
    """Accept Python bools or the strings 'true'/'false' (case-insensitive)."""
    if isinstance(value, bool):
        return True
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return True
    return False


def _validate_bool_or_zero_one(value: object) -> bool:
    """Accept Python bools, 'true'/'false' (case-insensitive), or legacy '0'/'1' strings.

    Used for axioms.auto_extract_post_run whose legacy env var (Z_HARNESS_AXIOM_EXTRACT)
    used '0' to disable rather than the standard 'false' string.
    """
    if _validate_bool(value):
        return True
    if isinstance(value, str) and value in {"0", "1"}:
        return True
    return False


def _validate_positive_int(value: object) -> bool:
    """Accept Python ints > 0, or decimal string representations of same."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return True
    if isinstance(value, str):
        try:
            return int(value) > 0
        except ValueError:
            return False
    return False


def _validate_positive_int_or_none(value: object) -> bool:
    """Accept None (unset), Python ints > 0, or decimal string representations of same."""
    if value is None:
        return True
    return _validate_positive_int(value)


def _validate_any_string(value: object) -> bool:
    """Accept any string value (including empty string).

    Used for models.* keys where validity is cross-checked at resolve time
    against providers.json, not at config-load time.  Empty string is the
    sentinel meaning "absent — use provider default resolution".
    """
    return isinstance(value, str)


def _validate_nonempty_string(value: object) -> bool:
    """Accept any non-empty string value.

    Used for brainstorm.wide_overflow_model where the accepted values are
    "haiku", "cheap-mixed", or any explicit model string — but an empty
    string is not meaningful and is rejected.
    """
    return isinstance(value, str) and len(value) > 0


def _validate_model_class_model(value: object) -> bool:
    """Accept any non-empty string model label for a model class."""
    return isinstance(value, str) and len(value) > 0


def _validate_model_metadata(value: object) -> bool:
    """Accept string metadata values; empty string means unspecified."""
    return isinstance(value, str)


# Allowed values for a host-keyed model-class effort field.  The empty string is
# the "no applied effort" sentinel (Haiku has no effort control; omp bakes effort
# into the catalog model name so its effort field is always "").
_MODEL_EFFORT_VALUES: frozenset[str] = frozenset(
    {"", "none", "low", "medium", "high", "xhigh", "max"}
)


def _validate_model_effort(value: object) -> bool:
    """Accept an effort level: "" | none | low | medium | high | xhigh | max."""
    return isinstance(value, str) and value in _MODEL_EFFORT_VALUES


def _validate_model_route(value: object) -> bool:
    """Accept a non-empty model class name or exact model label."""
    return isinstance(value, str) and len(value) > 0


def _validate_model_route_or_empty(value: object) -> bool:
    """Accept a model route, or empty inherit sentinel for native default."""
    return isinstance(value, str)


_MODEL_CLASS_FIELDS: frozenset[str] = frozenset({"model", "thinking", "reasoning"})
# Host axis under a model class: [model_classes.<class>.<hostfamily>] sub-tables.
# Exactly two families; `omp` covers every non-claude host.
_MODEL_CLASS_HOST_FAMILIES: frozenset[str] = frozenset({"claude", "omp"})
_MODEL_CLASS_HOST_FIELDS: frozenset[str] = frozenset({"model", "effort"})
_MODEL_IMPLEMENTER_TIERS: frozenset[str] = frozenset({"low", "medium", "high", "retry"})
_DYNAMIC_MODEL_CONFIG_SECTIONS: frozenset[str] = frozenset({"model_classes", "model_routing"})


def _reject_dynamic_model_config_nested_table(
    section: str,
    group: str,
    source_label: str,
) -> None:
    """Reject dict/table leaves under dynamic model config sections."""
    if section not in _DYNAMIC_MODEL_CONFIG_SECTIONS:
        return
    print(
        f"[config] {source_label}: unsupported nested table "
        f"{section}.{group}; expected scalar route leaves",
        file=sys.stderr,
    )
    sys.exit(2)


def _validate_dynamic_model_config_key_shape(
    dotted_key: str,
    source_label: str,
) -> None:
    """Enforce canonical lowercase/underscore segments on dynamic model keys."""
    for segment in dotted_key.split("."):
        if _KEY_SEGMENT_RE.match(segment):
            continue
        if "-" in segment:
            print(
                f"[config] {source_label}: hyphenated key {dotted_key!r} is not "
                "allowed (use underscores)",
                file=sys.stderr,
            )
        else:
            print(
                f"[config] {source_label}: non-canonical key segment {segment!r} "
                f"in {dotted_key!r}; use lowercase letters, digits, and underscores",
                file=sys.stderr,
            )
        sys.exit(2)


def _reject_unsupported_dynamic_model_config_key(
    dotted_key: str,
    source_label: str,
) -> None:
    """Reject unsupported direct leaves under dynamic model config sections."""
    print(
        f"[config] {source_label}: unsupported model routing key {dotted_key!r}",
        file=sys.stderr,
    )
    sys.exit(2)



def _dynamic_model_config_validator(parts: list[str]):
    """Return a validator for a dynamic model routing key, or None if unsupported.

    Accepts the dotted key already split into segments so both the 3-level legacy
    model-class shape (``model_classes.<class>.<field>``) and the 4-level
    host-keyed shape (``model_classes.<class>.<hostfamily>.<model|effort>``) can be
    distinguished by length.
    """
    section = parts[0]
    if section == "model_classes":
        # 3-level legacy host-blind leaf: model / thinking / reasoning
        if len(parts) == 3 and parts[2] in _MODEL_CLASS_FIELDS:
            return _validate_model_class_model if parts[2] == "model" else _validate_model_metadata
        # 4-level host-keyed leaf: <hostfamily>.<model|effort>
        if (
            len(parts) == 4
            and parts[2] in _MODEL_CLASS_HOST_FAMILIES
            and parts[3] in _MODEL_CLASS_HOST_FIELDS
        ):
            return _validate_model_class_model if parts[3] == "model" else _validate_model_effort
        return None
    if section == "model_routing":
        if len(parts) != 3:
            return None
        group, leaf = parts[1], parts[2]
        if group == "native_agents":
            return _validate_model_route_or_empty if leaf == "default" else _validate_model_route
        if group == "implementer" and leaf in _MODEL_IMPLEMENTER_TIERS:
            return _validate_model_route
    return None


def _model_class_table_has_model(
    class_name: str,
    fields: dict,
    values: dict[str, object],
    source_label: str,
    is_global: bool,
) -> bool:
    """Require custom model classes to define model unless a lower layer did."""
    if class_name in DEFAULTS.get("model_classes", {}):
        return True
    if "model" in fields:
        if _validate_model_class_model(fields["model"]):
            return True
        msg = (
            f"[config] {source_label}: invalid value for "
            f"'model_classes.{class_name}.model': {fields['model']!r} — "
            f"allowed: {_describe_allowed(_validate_model_class_model)}"
        )
        if is_global:
            print(f"WARNING: {msg}; skipping class", file=sys.stderr)
            return False
        print(msg, file=sys.stderr)
        sys.exit(2)
    if f"model_classes.{class_name}.model" in values:
        return True

    msg = (
        f"[config] {source_label}: model class {class_name!r} must define "
        "'model' before optional thinking/reasoning metadata"
    )
    if is_global:
        print(f"WARNING: {msg}; skipping class", file=sys.stderr)
        return False
    print(msg, file=sys.stderr)
    sys.exit(2)


def _fill_model_class_optional_metadata(
    class_name: str,
    values: dict[str, object],
    sources: dict[str, str],
    source_label: str,
) -> None:
    """Expose omitted optional metadata for custom classes as empty strings."""
    for leaf in ("thinking", "reasoning"):
        dotted = f"model_classes.{class_name}.{leaf}"
        if dotted not in values:
            values[dotted] = ""
            sources[dotted] = source_label


def _load_model_class_table(
    class_name: str,
    table: dict,
    values: dict[str, object],
    sources: dict[str, str],
    flat_defaults: dict[str, object],
    source_label: str,
    is_global: bool,
) -> None:
    """Load one ``[model_classes.<class>]`` table from a config layer.

    A class table may mix two coexisting shapes:
      * legacy host-blind scalars — ``model`` / ``thinking`` / ``reasoning``
      * host-keyed sub-tables — ``[model_classes.<class>.<claude|omp>]`` with
        ``model`` / ``effort`` leaves

    Nested sub-tables named anything other than a valid host family (``claude`` /
    ``omp``) are rejected with the same "unsupported nested table" error the flat
    schema used, so an accidental ``[model_classes.<class>.model]`` still fails.
    """
    scalar_leaves = {k: v for k, v in table.items() if not isinstance(v, dict)}
    host_tables = {k: v for k, v in table.items() if isinstance(v, dict)}

    # Reject nested sub-tables that are not a recognized host family.
    for host_family in host_tables:
        if host_family not in _MODEL_CLASS_HOST_FAMILIES:
            _reject_dynamic_model_config_nested_table(
                "model_classes", class_name, source_label
            )

    # Gate: a custom class must define a model — via the legacy scalar or a host
    # sub-table. Built-in classes always pass via _model_class_table_has_model.
    has_host_model = any(
        _validate_model_class_model(ht.get("model")) for ht in host_tables.values()
    )
    if not has_host_model and not _model_class_table_has_model(
        class_name, scalar_leaves, values, source_label, is_global
    ):
        return

    def _store(dotted: str, raw: object) -> None:
        if dotted in flat_defaults:
            resolved = _validate_enum(dotted, raw, source_label, is_global)
        else:
            resolved = _validate_dynamic_model_config_value(
                dotted, raw, source_label, is_global
            )
            if resolved is None:
                return
        if dotted in _COERCERS:
            resolved = _COERCERS[dotted](resolved)
        values[dotted] = resolved
        sources[dotted] = source_label

    for subk, subv in scalar_leaves.items():
        _store(f"model_classes.{class_name}.{subk}", subv)
    for host_family, host_table in host_tables.items():
        for leaf_k, leaf_v in host_table.items():
            _store(f"model_classes.{class_name}.{host_family}.{leaf_k}", leaf_v)

    _fill_model_class_optional_metadata(class_name, values, sources, source_label)


def _default_for_dotted_key(dotted_key: str) -> object:
    """Return the DEFAULTS leaf for a 2+ segment dotted key."""
    current: object = DEFAULTS
    for segment in dotted_key.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise KeyError(dotted_key)
        current = current[segment]
    return current


# Closed set of valid export host names:
#   adapter names (handled by z_harness_cli adapters)
#   export-only driver names (handled by runtime/drivers/<name>/export.py)
_EXPORT_VALID_HOSTS: frozenset[str] = frozenset({
    "claude", "antigravity", "cursor", "codex", "omp",   # adapter names
    "pi", "windsurf", "cline", "kiro", "copilot",        # export-only driver names
    "agy",                                                # alias for antigravity used in z-export.md
})


def _validate_export_hosts(value: object) -> bool:
    """Accept a list of valid export host names, or a JSON-encoded list string (env layer).

    Valid host names are the union of adapter names {claude, antigravity, agy,
    cursor, codex, omp} and export-only driver names {pi, windsurf, cline,
    kiro, copilot}.  Unknown names are rejected.  The list must be non-empty.
    """
    if isinstance(value, str):
        # Env-layer transport: JSON-encoded list, e.g. '["cursor","codex"]'
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return False
    if not isinstance(value, list):
        return False
    if not value:
        return False  # empty list is not meaningful
    return all(isinstance(h, str) and h in _EXPORT_VALID_HOSTS for h in value)


# halt_category is per-question-id metadata, NOT a user-settable TOML key. This
# enum is a plain module-level constant referenced directly by the startup guard
# (_run_startup_guards, Guard 2b) and by cmd_resolve_halt_category. It is
# deliberately kept out of VALIDATORS so `config.py set workflow.halt_category ...`
# is rejected as an unknown/non-settable key (load_config() would drop it anyway,
# since it has no DEFAULTS entry).
HALT_CATEGORY_ENUM: frozenset[str] = frozenset(
    {"decision", "risk", "shortcut", "archiving", "mechanical_proceed"}
)

VALIDATORS: dict = {
    "notify.level": {"off", "approval_only", "all"},
    "notify.hermes_webhook_url": _validate_any_string,
    "notify.hermes_webhook_secret": _validate_any_string,
    "docs.always_apply": {"always", "never"},
    "docs.staleness_threshold": _validate_positive_int,
    "workflow.audit_to_amend": {"ask", "amend", "stop"},
    "workflow.slug_confirm":   {"ask", "auto_accept", "recommend_derived"},
    "workflow.implement_all_proceed":    {"ask", "auto_resume", "halt"},
    "workflow.review_all_proceed":       {"ask", "proceed", "halt"},
    "workflow.plan_decisions_approval":  {"ask", "approve", "halt"},
    "workflow.pre_run_cost_gate":        {"ask", "auto_proceed", "halt"},
    "workflow.planning_mode":            {"intent", "full"},
    "workflow.intent_level":             {"auto", "quick", "standard", "deep"},
    "workflow.intent_parallel_levels":   _validate_bool,
    "workflow.hermes_enabled":           _validate_bool,
    "workflow.max_explore":              _validate_positive_int,
    "workflow.parallel":                 _validate_positive_int,
    "workflow.memory_stale_days":        _validate_positive_int,
    "cost.token_budget":                 _validate_positive_int_or_none,
    "followup.default_sink":                   {"project", "global"},
    "followup.notion_enabled":                 _validate_bool,
    "followup.auto_close_low_risk_enabled":    _validate_bool,
    "axioms.enabled":               _validate_bool,
    "axioms.kernel_budget_chars":   _validate_positive_int,
    "axioms.extract_min_recurrence": _validate_positive_int,
    "axioms.auto_extract_post_run": _validate_bool_or_zero_one,
    "brainstorm.personas":          _validate_bool,
    "brainstorm.wide_overflow_model": _validate_nonempty_string,
    "changelog.auto":               _validate_bool,
    "personas.critique_panel":      _validate_bool,
    "personas.audit":               _validate_bool,
    "personas.review_eval":         _validate_bool,
    "personas.implementer_retry":   {"same", "new"},
    "personas.consult_eval":        _validate_bool,
    "experiment.persona_rotation":  _validate_bool,
    "experiment.control_every_n":   _validate_positive_int,
    "runtime.consult":              {"on", "off"},
    "runtime.pre_review":           _validate_bool,
    "runtime.impl_pre_review":      _validate_bool,
    "runtime.auto_wait":            _validate_bool_or_zero_one,
    "runtime.auto_wait_budget_secs": _validate_positive_int,
    "runtime.pause_at_pct":         _validate_positive_int,
    "runtime.context_window_tokens": _validate_positive_int,
    "runtime.explain_resolution":   _validate_bool,
    "runtime.max_parallel":         _validate_positive_int,
    "runtime.max_parallel_plans":   _validate_positive_int,
    "runtime.max_attempts":         _validate_positive_int,
    "runtime.max_task_wall_ms":     _validate_positive_int,
    "runtime.env_strict":           _validate_bool,
    # models.* — any string (including empty) is valid; cross-checked at resolve time (T007)
    "models.consultant_primary":   _validate_any_string,
    "models.consultant_secondary": _validate_any_string,
    "models.reviewer":             _validate_any_string,
    "models.implementer":          _validate_any_string,
    "models.pre_reviewer":         _validate_any_string,
    # model_classes.* — named classes for native-agent routing; dynamic class names allowed.
    # Each built-in class carries legacy host-blind scalars (model/thinking/reasoning,
    # retained for backward-compat) plus a host axis: per-host-family (model, effort)
    # pairs for `claude` and `omp`. Effort allowed set: "" | none | low | medium | high | xhigh | max.
    "model_classes.cheap.model":      _validate_model_class_model,
    "model_classes.cheap.thinking":   _validate_model_metadata,
    "model_classes.cheap.reasoning":  _validate_model_metadata,
    "model_classes.cheap.claude.model":  _validate_model_class_model,
    "model_classes.cheap.claude.effort": _validate_model_effort,
    "model_classes.cheap.omp.model":     _validate_model_class_model,
    "model_classes.cheap.omp.effort":    _validate_model_effort,
    "model_classes.low.model":        _validate_model_class_model,
    "model_classes.low.thinking":     _validate_model_metadata,
    "model_classes.low.reasoning":    _validate_model_metadata,
    "model_classes.low.claude.model":    _validate_model_class_model,
    "model_classes.low.claude.effort":   _validate_model_effort,
    "model_classes.low.omp.model":       _validate_model_class_model,
    "model_classes.low.omp.effort":      _validate_model_effort,
    "model_classes.standard.model":   _validate_model_class_model,
    "model_classes.standard.thinking": _validate_model_metadata,
    "model_classes.standard.reasoning": _validate_model_metadata,
    "model_classes.standard.claude.model":  _validate_model_class_model,
    "model_classes.standard.claude.effort": _validate_model_effort,
    "model_classes.standard.omp.model":     _validate_model_class_model,
    "model_classes.standard.omp.effort":    _validate_model_effort,
    "model_classes.deep.model":       _validate_model_class_model,
    "model_classes.deep.thinking":    _validate_model_metadata,
    "model_classes.deep.reasoning":   _validate_model_metadata,
    "model_classes.deep.claude.model":   _validate_model_class_model,
    "model_classes.deep.claude.effort":  _validate_model_effort,
    "model_classes.deep.omp.model":      _validate_model_class_model,
    "model_classes.deep.omp.effort":     _validate_model_effort,
    # model_routing.* — config-file-only routing values; dynamic native agent keys allowed.
    "model_routing.native_agents.default": _validate_model_route_or_empty,
    "model_routing.implementer.low":       _validate_model_route,
    "model_routing.implementer.medium":    _validate_model_route,
    "model_routing.implementer.high":      _validate_model_route,
    "model_routing.implementer.retry":     _validate_model_route,
    # export.* — closed-set validation at load time (T008)
    "export.hosts":    _validate_export_hosts,
    # "" is the sentinel meaning "defer to per-driver default".
    # Users may also explicitly set pointer|curated|full to override globally.
    # Any other value is rejected.
    "export.strategy": {"", "pointer", "curated", "full"},
    # watchdog.* — flat keys round-trip via env; nested timeout_secs is config-file-only.
    "watchdog.enabled":              _validate_bool,
    "watchdog.sweep_interval_secs":  _validate_positive_int,
    "watchdog.intervention_level":   {"observe", "notify"},
    "watchdog.kill_grace_secs":      _validate_positive_int,
    "watchdog.max_lifetime_secs":    _validate_positive_int,
    "watchdog.stale_secs":           _validate_positive_int,
    # watchdog.timeout_secs.* : per-leaf positive ints; read via config.py get only.
    "watchdog.timeout_secs.bash":     _validate_positive_int,
    "watchdog.timeout_secs.ssh":      _validate_positive_int,
    "watchdog.timeout_secs.rsync":    _validate_positive_int,
    "watchdog.timeout_secs.cargo":    _validate_positive_int,
    "watchdog.timeout_secs.reviewer": _validate_positive_int,
}

# Coercers: applied after validation to normalize values (esp. env-var strings).
# Keys that need no coercion (string enums) are absent.
_COERCERS: dict[str, object] = {
    "axioms.enabled": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "axioms.kernel_budget_chars": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "axioms.extract_min_recurrence": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "axioms.auto_extract_post_run": lambda v: (
        # Accept legacy "0"/"1" from Z_HARNESS_AXIOM_EXTRACT in addition to "true"/"false"
        v if isinstance(v, bool) else (
            False if v == "0" else (True if v == "1" else v.lower() == "true")
        )
    ),
    "brainstorm.personas": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "brainstorm.wide_overflow_model": lambda v: (
        # String passthrough — no type coercion needed; the value is always a string.
        # Included here so the knob appears in BOTH maps (per m3 invariant) and to
        # make the coercer table exhaustive for introspection tooling.
        v
    ),
    "changelog.auto": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "personas.critique_panel": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "personas.audit": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "personas.review_eval": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "personas.consult_eval": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "experiment.persona_rotation": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "experiment.control_every_n": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "cost.token_budget": lambda v: (
        None if (v is None or v == "") else (
            v if isinstance(v, int) and not isinstance(v, bool) else int(v)
        )
    ),
    "workflow.intent_parallel_levels": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "workflow.hermes_enabled": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "runtime.pre_review": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "runtime.impl_pre_review": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "runtime.auto_wait": lambda v: (
        # Accept legacy "0"/"1" from Z_HARNESS_AUTO_WAIT in addition to "true"/"false"
        v if isinstance(v, bool) else (
            False if v == "0" else (True if v == "1" else v.lower() == "true")
        )
    ),
    "runtime.auto_wait_budget_secs": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.pause_at_pct": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.context_window_tokens": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.explain_resolution": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    # T003b — parallelism/review/docs/limits group
    "docs.staleness_threshold": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "workflow.max_explore": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "workflow.parallel": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "workflow.memory_stale_days": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.max_parallel": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.max_parallel_plans": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.max_attempts": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.max_task_wall_ms": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "runtime.env_strict": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    # T008 — export.hosts: env transport is JSON-encoded array string; coerce to list
    "export.hosts": lambda v: (
        v if isinstance(v, list) else json.loads(v)
    ),
    # watchdog.* — flat bool/int coercers (round-trip via env)
    "watchdog.enabled": lambda v: (
        v if isinstance(v, bool) else v.lower() == "true"
    ),
    "watchdog.sweep_interval_secs": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.kill_grace_secs": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.max_lifetime_secs": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.stale_secs": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    # watchdog.timeout_secs.* — config-file-only; coerce TOML int (already int, passthrough)
    "watchdog.timeout_secs.bash": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.timeout_secs.ssh": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.timeout_secs.rsync": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.timeout_secs.cargo": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
    "watchdog.timeout_secs.reviewer": lambda v: (
        v if isinstance(v, int) and not isinstance(v, bool) else int(v)
    ),
}

META_KEYS: set = {"schema_version"}


def _describe_allowed(allowed: object) -> object:
    """Return a human-readable description of an ``allowed`` validator.

    When ``allowed`` is callable (e.g. ``_validate_bool``), returns its
    ``__doc__`` string (trimmed to first line) or ``repr(allowed)``.
    When ``allowed`` is a set/frozenset of string literals, returns a sorted
    list so error messages are deterministic and readable.
    """
    if callable(allowed):
        doc = getattr(allowed, "__doc__", None)
        return doc.splitlines()[0].strip() if doc else repr(allowed)
    return sorted(allowed)

# ---------------------------------------------------------------------------
# Question registry (single source of truth for resolver and /z-suggest-memory)
# ---------------------------------------------------------------------------

QUESTION_IDS: dict[str, dict] = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        "choices": {"ask", "amend", "stop"},
        "skill_default": "amend",
        "halt_category": "risk",
        "callsites": [
            "skills/z-audit-plan/SKILL.md:183",
            "skills/z-audit-plan-style/SKILL.md:384",
        ],
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        # `auto_accept` means "always accept derived slug without asking" (resolves to result: skip).
        # `recommend_derived` means "show AskUser with derived slug pre-selected" (resolves to result: prefill).
        # `ask` means "always ask" (resolves to result: ask).
        "choices": {"ask", "auto_accept", "recommend_derived"},
        "skill_default": "yes_keep_derived",
        "halt_category": "mechanical_proceed",
        "callsites": [
            "skills/z-plan/SKILL.md:21",
            "skills/z-fix/SKILL.md:18",
            "skills/z-debug/SKILL.md:17",
            "skills/z-brainstorm/SKILL.md:19",
            "skills/z-map/SKILL.md:133",
            "skills/z-uplift/SKILL.md:71",
        ],
        # Hard prerequisite: even when resolver returns skip, the slug-COLLISION check runs
        # unconditionally. The resolver only governs the soft non-obvious-slug confirmation.
        "safety_check_runs_unconditionally": True,
    },
    "workflow.implement_all_proceed": {
        "config_key": "workflow.implement_all_proceed",
        "choices": {"ask", "auto_resume", "halt"},
        "skill_default": "ask",
        "halt_category": "mechanical_proceed",
        "callsites": [
            "skills/z-execute/SKILL.md (halt-resolution gate)",
        ],
    },
    "workflow.review_all_proceed": {
        "config_key": "workflow.review_all_proceed",
        "choices": {"ask", "proceed", "halt"},
        "skill_default": "proceed",
        "halt_category": "mechanical_proceed",
        "callsites": [
            "skills/z-review-all/SKILL.md (Phase 3.7 proceed gate)",
        ],
    },
    "workflow.plan_decisions_approval": {
        "config_key": "workflow.plan_decisions_approval",
        "choices": {"ask", "approve", "halt"},
        "skill_default": "approve",
        "halt_category": "decision",
        "callsites": [
            "skills/z-plan/SKILL.md (Phase 2.5 decisions-doc approval gate)",
        ],
    },
    "workflow.pre_run_cost_gate": {
        "config_key": "workflow.pre_run_cost_gate",
        "choices": {"ask", "auto_proceed", "halt"},
        "skill_default": "ask",
        "halt_category": "risk",
        "callsites": [
            "scripts/pre-run-cost-gate.sh",
            "skills/z-research/SKILL.md",
            "skills/z-uplift/SKILL.md",
            "skills/z-plan-split/SKILL.md",
            "skills/z-plan/SKILL.md",
        ],
    },
}

# Default overnight auto-decide allowlist: question_ids that /z-overnight
# handles autonomously without halting, mapped to the chosen option-domain value.
OVERNIGHT_AUTODECIDE_QIDS_DEFAULT: dict[str, str] = {
    "workflow.slug_confirm": "recommend_derived",
    "workflow.audit_to_amend": "amend",
}

# Map each question_id's option-domain value → resolver result-domain
RESULT_MAP: dict[tuple[str, str], str] = {
    ("workflow.audit_to_amend", "ask"):             "ask",
    ("workflow.audit_to_amend", "amend"):           "skip",  # user wants auto-amend → skip the prompt
    ("workflow.audit_to_amend", "stop"):            "skip",  # user wants auto-stop → also skip the prompt
    ("workflow.slug_confirm",   "ask"):             "ask",
    ("workflow.slug_confirm",   "auto_accept"):     "skip",
    ("workflow.slug_confirm",   "recommend_derived"): "prefill",
    ("workflow.implement_all_proceed", "ask"):       "ask",
    ("workflow.implement_all_proceed", "auto_resume"): "skip",
    ("workflow.implement_all_proceed", "halt"):      "halt",
    ("workflow.review_all_proceed",    "ask"):       "ask",
    ("workflow.review_all_proceed",    "proceed"):   "skip",
    ("workflow.review_all_proceed",    "halt"):      "halt",
    ("workflow.plan_decisions_approval", "ask"):     "ask",
    ("workflow.plan_decisions_approval", "approve"): "skip",
    ("workflow.plan_decisions_approval", "halt"):    "halt",
    ("workflow.pre_run_cost_gate", "ask"):                 "ask",
    ("workflow.pre_run_cost_gate", "auto_proceed"):        "skip",
    ("workflow.pre_run_cost_gate", "halt"):                "halt",
}

# ---------------------------------------------------------------------------
# Startup guards — run at module load; raise SystemExit(2) on violation
# ---------------------------------------------------------------------------

def _run_startup_guards() -> None:
    """Validate internal registry consistency at module load."""
    # Guard 1: every question_id must have a corresponding VALIDATORS entry
    for qid in QUESTION_IDS:
        if qid not in VALIDATORS:
            raise SystemExit(
                f"[config] startup guard failed: QUESTION_IDS key {qid!r} "
                "is not present in VALIDATORS — add it before shipping"
            )

    # Guard 2: every question_id must have a non-null skill_default
    for qid, meta in QUESTION_IDS.items():
        if meta.get("skill_default") is None:
            raise SystemExit(
                f"[config] startup guard failed: QUESTION_IDS[{qid!r}]['skill_default'] "
                "is None — every question_id requires a presentation default"
            )

    # Guard 2b: every question_id must have a halt_category in HALT_CATEGORY_ENUM
    for qid, meta in QUESTION_IDS.items():
        cat = meta.get("halt_category")
        if cat not in HALT_CATEGORY_ENUM:
            raise SystemExit(
                f"[config] startup guard failed: QUESTION_IDS[{qid!r}]['halt_category'] "
                f"is {cat!r} — must be one of {sorted(HALT_CATEGORY_ENUM)}"
            )

    # Guard 3: every choice referenced in RESULT_MAP must be a valid choice in QUESTION_IDS
    for (qid, choice), result in RESULT_MAP.items():
        if qid not in QUESTION_IDS:
            raise SystemExit(
                f"[config] startup guard failed: RESULT_MAP references question_id "
                f"{qid!r} which is not in QUESTION_IDS"
            )
        if choice not in QUESTION_IDS[qid]["choices"]:
            raise SystemExit(
                f"[config] startup guard failed: RESULT_MAP[({qid!r}, {choice!r})] "
                f"references choice {choice!r} which is not in "
                f"QUESTION_IDS[{qid!r}]['choices'] = {QUESTION_IDS[qid]['choices']!r}"
            )


_run_startup_guards()

# Valid event kinds for should-notify.
# watchdog_stall / watchdog_timeout are included in the approval_only fire-set so
# that watchdog alerts fire under the DEFAULT notify.level without requiring users to
# switch to "all".  Without this, notify-watchdog.sh exits silently and the entire
# alert layer is inert out of the box.
_NOTIFY_EVENTS: set = {"approval", "phase_end", "error", "watchdog_stall", "watchdog_timeout"}

# Key-format regex: 2 to 4 segments, all lowercase with underscores/digits.
# Valid: notify.level, roles.z_plan.consultant_primary, roles.z_plan.consultant_primary.persona
# Invalid: roles..foo (empty segment), roles.z_plan.role.field.extra (5 segments), uppercase or hyphens
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")
_KEY_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Pure helper: _dotted_to_env
# ---------------------------------------------------------------------------

_ENV_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _dotted_to_env(key: str) -> str:
    """
    Translate a 2-level dotted TOML key to a Z_HARNESS_ env var name.

    notify.level  ->  Z_HARNESS_NOTIFY_LEVEL
    docs.always_apply  ->  Z_HARNESS_DOCS_ALWAYS_APPLY
    experiment.persona_rotation  ->  Z_HARNESS_EXPERIMENT_PERSONA_ROTATION

    Raises SystemExit(2) if key does not match ``^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$``
    (exactly 2 segments; 3-level role keys are not exported as env vars).
    """
    if not _ENV_KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        sys.exit(2)
    return "Z_HARNESS_" + key.upper().replace(".", "_")


# Dotted keys whose exported env var name differs from the mechanical
# _dotted_to_env() mapping. runtime.consult exports as Z_HARNESS_CONSULT — the
# legacy name resolve-provider.py reads — not Z_HARNESS_RUNTIME_CONSULT.
#
# Rule: when the raw env name a user historically set is NOT the mechanical
# transliteration (Z_HARNESS_<SECTION>_<KEY>), add a mapping here.  This has
# two effects:
#   (a) Egress: export-env emits the legacy name so downstream shell code that
#       reads $Z_HARNESS_PRE_REVIEW (etc.) continues to work.
#   (b) Ingress: load_config layer 4 checks the legacy name when the
#       transliteration is absent (see the _INGRESS_LEGACY_ALIASES map below).
_ENV_VAR_ALIASES: dict[str, str] = {
    # Pre-existing alias (egress-only before T003a)
    "runtime.consult": "Z_HARNESS_CONSULT",
    # T003a — workflow/runtime/notify group migrations.
    # These keys export under the legacy raw name (not the mechanical
    # transliteration Z_HARNESS_RUNTIME_*) so that shell code reading the
    # well-known name (e.g. $Z_HARNESS_PRE_REVIEW) continues to work after
    # eval "$(config.py export-env)".
    "runtime.pre_review":         "Z_HARNESS_PRE_REVIEW",
    "runtime.impl_pre_review":    "Z_HARNESS_IMPL_PRE_REVIEW",
    "runtime.auto_wait":          "Z_HARNESS_AUTO_WAIT",
    "runtime.auto_wait_budget_secs": "Z_HARNESS_AUTO_WAIT_BUDGET_SECS",
    "runtime.pause_at_pct":       "Z_HARNESS_PAUSE_AT_PCT",
    "runtime.explain_resolution": "Z_HARNESS_EXPLAIN_RESOLUTION",
    # T003b — parallelism/review/docs/limits group migrations.
    # Raw name differs from mechanical transliteration in every case below.
    "docs.staleness_threshold":   "Z_HARNESS_DOC_STALENESS_THRESHOLD",   # raw uses DOC (no S) vs DOCS
    "workflow.max_explore":       "Z_HARNESS_MAX_EXPLORE",                # raw has no WORKFLOW_ prefix
    "workflow.parallel":          "Z_HARNESS_PARALLEL",                   # raw has no WORKFLOW_ prefix
    "workflow.memory_stale_days": "Z_HARNESS_MEMORY_STALE_DAYS",          # raw has no WORKFLOW_ prefix
    # runtime.max_parallel intentionally NOT aliased here: its legacy raw name is
    # HERMES_MAX_PARALLEL (HERMES_ prefix), which is not a Z_HARNESS_-prefixed key.
    # Emitting a HERMES_-prefixed key on egress violates the canonical Z_HARNESS_-only
    # contract for export-env output.  The ingress alias (kept in _INGRESS_LEGACY_ALIASES
    # below) still reads HERMES_MAX_PARALLEL for backward-compat; egress emits the
    # canonical Z_HARNESS_RUNTIME_MAX_PARALLEL transliteration.
    "runtime.max_parallel_plans": "Z_HARNESS_MAX_PARALLEL_PLANS",         # raw has no RUNTIME_ infix
    "runtime.max_attempts":       "Z_HARNESS_MAX_ATTEMPTS",               # raw has no RUNTIME_ infix
    "runtime.max_task_wall_ms":   "Z_HARNESS_MAX_TASK_WALL_MS",           # raw has no RUNTIME_ infix
    "axioms.auto_extract_post_run": "Z_HARNESS_AXIOM_EXTRACT",            # completely different legacy name
}

# Ingress fallback: dotted_key → legacy raw env var name.  Used by load_config
# layer 4 when the transliteration var is absent: check the legacy raw name too.
#
# This covers all keys in _ENV_VAR_ALIASES (T003a + T003b) plus ingress-only legacies:
#   runtime.pre_review  → Z_HARNESS_PRE_REVIEW  (transliteration: Z_HARNESS_RUNTIME_PRE_REVIEW)
#   runtime.auto_wait   → Z_HARNESS_AUTO_WAIT   (transliteration: Z_HARNESS_RUNTIME_AUTO_WAIT)
#   runtime.max_parallel → HERMES_MAX_PARALLEL   (transliteration: Z_HARNESS_RUNTIME_MAX_PARALLEL)
#   axioms.auto_extract_post_run → Z_HARNESS_AXIOM_EXTRACT
#   … etc. for all keys in _ENV_VAR_ALIASES
#   notify.level        → Z_HARNESS_NOTIFY       (transliteration: Z_HARNESS_NOTIFY_LEVEL;
#                           export still uses the transliteration — this is ingress-only)
_INGRESS_LEGACY_ALIASES: dict[str, str] = {
    **_ENV_VAR_ALIASES,                     # dotted_key → legacy export name (also valid for ingress)
    "notify.level": "Z_HARNESS_NOTIFY",     # notify.level → Z_HARNESS_NOTIFY (ingress-only legacy lookup)
    # runtime.max_parallel was removed from _ENV_VAR_ALIASES (egress) because its legacy name
    # HERMES_MAX_PARALLEL violates the Z_HARNESS_-only egress contract.  The ingress alias is
    # kept here so that HERMES_MAX_PARALLEL env values are still accepted on ingress (back-compat).
    "runtime.max_parallel": "HERMES_MAX_PARALLEL",
}


# ---------------------------------------------------------------------------
# Legal-env allowlist (T001)
#
# LEGAL_ENV_KEYS   — exact full env var names that are always authoritative.
# LEGAL_ENV_PREFIXES — prefix strings; any env var whose name starts with one
#                      of these is in the allowlist.
#
# The allowlist has two categories:
#   (1) Plumbing  — per-run values set BY the orchestrator, cannot be static
#       config (e.g. PLAN_DIR, SLUG, RUN, SESSION_ID).
#   (2) Unattended-entry — per-invocation flags controlling overnight/CI
#       autonomy gates (NO_ASK, ASK_ALL, OVERNIGHT_AUTODECIDE*, CLAIM_*,
#       REGISTRY_*).
#
# Every Z_HARNESS_<SECTION>_<KEY> transliteration (and its legacy alias) for
# a key in DEFAULTS is a *preference* env var; it is NOT in this allowlist.
# load_config() uses this allowlist to skip env override when TOML has already
# provided a value for a preference key (TOML wins).
# ---------------------------------------------------------------------------

LEGAL_ENV_KEYS: frozenset[str] = frozenset({
    # ── Plumbing — per-run session/path identifiers ──
    "Z_HARNESS_PLAN_DIR",
    "Z_HARNESS_SLUG",
    "Z_HARNESS_RUN",
    "Z_HARNESS_RUN_ID",
    "Z_HARNESS_SESSION_ID",
    "Z_HARNESS_PLUGIN_ROOT",
    "ANTIGRAVITY_PLUGIN_ROOT",          # alternate plugin-root name used in some contexts
    "Z_HARNESS_BASE_DIR",
    "Z_HARNESS_PLANS_DIR",
    "Z_HARNESS_ROOT",
    "Z_HARNESS_TASK_ID",
    "Z_HARNESS_ATTEMPT_ID",
    "Z_HARNESS_PARENT_RUN_ID",
    "Z_HARNESS_PARENT_COMMAND",
    "Z_HARNESS_REPO_CONFIG",
    "Z_HARNESS_REPO_PROVIDERS",
    # ── Host/editor context pressure reports (per-session dynamic inputs) ──
    "Z_HARNESS_CONTEXT_USED_TOKENS",
    "Z_HARNESS_CONTEXT_WINDOW_TOKENS",
    # ── Unattended-entry — autonomy/overnight/CI gate flags ──
    "Z_HARNESS_NO_ASK",
    "Z_HARNESS_ASK_ALL",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
    "Z_HARNESS_STRICT_OVERLAP",
    # ── Active-plan registry (env-only, read inline) ──
    "Z_HARNESS_EXTERNAL_DEFAULT",
    "Z_HARNESS_REGISTRY_ENABLED",
    "Z_HARNESS_REGISTRY_STALE_SECS",
})

LEGAL_ENV_PREFIXES: tuple[str, ...] = (
    "Z_HARNESS_CLAIM_",     # Z_HARNESS_CLAIM_TTL_SECS, Z_HARNESS_CLAIM_OVERRIDE, Z_HARNESS_CLAIM_DISABLE
    "Z_HARNESS_REGISTRY_",  # Z_HARNESS_REGISTRY_ENABLED, Z_HARNESS_REGISTRY_STALE_SECS
)


def _is_legal_env(var_name: str) -> bool:
    """Return True if the env var is a plumbing/unattended var (not a preference var)."""
    if var_name in LEGAL_ENV_KEYS:
        return True
    return any(var_name.startswith(pfx) for pfx in LEGAL_ENV_PREFIXES)


# ---------------------------------------------------------------------------
# TOML key name validation
# ---------------------------------------------------------------------------

def _validate_toml_keys(data: dict, path: str) -> None:
    """
    Reject non-canonical TOML key segments and table nesting deeper than the
    supported dotted-key shape.

    Supported nesting depth (as TOML table headers):
      [section]                             — depth 1 (e.g. [notify])
      [section.subsection]                  — depth 2 (e.g. [workflow])
      [section.subsection.role]             — depth 3 (e.g. [roles.z_plan.consultant_primary])

    Leaf values (strings, ints, etc.) may appear at any supported depth.  Every
    segment must use the same lowercase/underscore form enforced by _KEY_RE so
    dynamic TOML keys cannot bypass canonical dotted-key validation.
    """

    def reject_noncanonical(dotted: str, segment: str) -> None:
        if "-" in segment:
            print(
                f"[config] {path}: hyphenated key {dotted!r} is not allowed "
                "(use underscores)",
                file=sys.stderr,
            )
        else:
            print(
                f"[config] {path}: non-canonical key segment {segment!r} in "
                f"{dotted!r}; use lowercase letters, digits, and underscores",
                file=sys.stderr,
            )
        sys.exit(2)

    def walk(node: dict, prefix: tuple[str, ...]) -> None:
        for key, value in node.items():
            dotted_parts = (*prefix, key)
            dotted = ".".join(dotted_parts)
            if not _KEY_SEGMENT_RE.match(key):
                reject_noncanonical(dotted, key)
            if isinstance(value, dict):
                if len(dotted_parts) >= 4:
                    print(
                        f"[config] {path}: key {dotted!r} has >3-level "
                        "nesting; not supported",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                walk(value, dotted_parts)

    walk(data, ())


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict:
    """Load TOML file; return None if file missing."""
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except PermissionError:
        print(
            f"[config] permission denied reading {path}",
            file=sys.stderr,
        )
        sys.exit(4)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"[config] {path}: TOML parse error: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    return data


def _check_schema_version(data: dict, path: str) -> None:
    if not data:
        return
    v = data.get("schema_version")
    if v is None:
        return
    if v < 2:
        print(
            f"[config] WARNING: {path}: schema_version {v!r} is outdated (current: 2);"
            " run `config.py ensure-defaults` to update your config.",
            file=sys.stderr,
        )
        # Non-fatal: continue loading with the legacy config.
    elif v > 2:
        print(
            f"[config] {path}: schema_version {v!r} is newer than supported (2);"
            " upgrade z-harness or downgrade your config.",
            file=sys.stderr,
        )
        sys.exit(2)


def _global_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "z-harness" / "config.toml"


def _repo_config_path(require_exists: bool = True) -> Path:
    """
    Return the repo-local config path.

    When ``require_exists`` is True (the default, used by readers), exits 2 if
    ``Z_HARNESS_REPO_CONFIG`` is set but the path does not yet exist.
    When ``require_exists`` is False (used by writers), returns the path even if
    the file does not exist yet.
    """
    repo_env = os.environ.get("Z_HARNESS_REPO_CONFIG", "")
    if repo_env:
        p = Path(repo_env)
        if require_exists and not p.exists():
            print(
                f"[config] Z_HARNESS_REPO_CONFIG={repo_env!r} does not exist",
                file=sys.stderr,
            )
            sys.exit(2)
        return p
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        repo_root = Path.cwd()
    return repo_root / ".z-harness" / "config.toml"


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------

def _validate_enum(dotted_key: str, value: object, source_label: str, is_global: bool) -> object:
    """
    Validate a value against VALIDATORS.
    - global layer: emit warning + return default value (soft fail).
    - repo/env layer: exit 2 (hard fail).
    Returns (possibly substituted) value.
    """
    if dotted_key not in VALIDATORS:
        return value
    allowed = VALIDATORS[dotted_key]
    if callable(allowed):
        valid = allowed(value)
    else:
        valid = value in allowed
    if not valid:
        allowed_desc = _describe_allowed(allowed)
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — allowed: {allowed_desc}"
        )
        if is_global:
            print(f"WARNING: {msg}; falling back to default", file=sys.stderr)
            return _default_for_dotted_key(dotted_key)
        else:
            print(msg, file=sys.stderr)
            sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# 3-level role key validation
# ---------------------------------------------------------------------------

from typing import Optional


def _validate_roles_value(dotted_key: str, value: object, source_label: str, is_global: bool) -> Optional[object]:
    """
    Validate a 3-level role key value (e.g. roles.z_plan.consultant_primary.persona).

    If the key is in VALIDATORS, delegate to _validate_enum.
    Otherwise, validate as a non-empty string (the default for role keys).

    Returns the (possibly substituted) value on success, or None if validation fails
    and is_global is True (soft fail — caller skips the key).
    On hard fail (repo/env layer), exits with code 2.
    """
    if dotted_key in VALIDATORS:
        return _validate_enum(dotted_key, value, source_label, is_global)

    # Default validation: must be a string.
    # Empty string is permitted for the 'model' leaf key (semantics: use provider's
    # default_model). All other role fields must be non-empty strings.
    leaf_key = dotted_key.rsplit(".", 1)[-1] if "." in dotted_key else dotted_key
    allow_empty = leaf_key == "model"
    if not isinstance(value, str) or (not allow_empty and not value):
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — must be a non-empty string"
        )
        if is_global:
            print(f"WARNING: {msg}; skipping key", file=sys.stderr)
            return None
        else:
            print(msg, file=sys.stderr)
            sys.exit(2)
    return value


def _validate_dynamic_model_config_value(
    dotted_key: str,
    value: object,
    source_label: str,
    is_global: bool,
) -> Optional[object]:
    """Validate supported dynamic model_classes/model_routing keys.

    Handles both the 3-level legacy shape and the 4-level host-keyed
    model-class shape (``model_classes.<class>.<hostfamily>.<model|effort>``).
    """
    _validate_dynamic_model_config_key_shape(dotted_key, source_label)
    parts = dotted_key.split(".")
    section = parts[0]
    validator = _dynamic_model_config_validator(parts)
    if validator is None:
        if section in _DYNAMIC_MODEL_CONFIG_SECTIONS:
            print(
                f"[config] {source_label}: unsupported model routing key "
                f"{dotted_key!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        return None
    valid = validator(value)
    if not valid:
        allowed_desc = _describe_allowed(validator)
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — allowed: {allowed_desc}"
        )
        if is_global:
            print(f"WARNING: {msg}; skipping key", file=sys.stderr)
            return None
        print(msg, file=sys.stderr)
        sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# Layer merging
# ---------------------------------------------------------------------------

def _flatten_defaults() -> dict[str, object]:
    """Return flat {dotted_key: value} from DEFAULTS (excluding meta keys).

    Recursively expands nested dict tables into dotted leaves:
      * 3-level, e.g. watchdog.timeout_secs.bash
      * 4-level, e.g. model_classes.deep.claude.model (host-keyed model classes)
    Only scalar leaves are stored; intermediate dict tables are skipped.  Nested
    (3+ level) keys are NOT env-exported (cmd_export_env skips them via the
    depth guard).
    """
    result: dict[str, object] = {}

    def walk(prefix: str, node: dict) -> None:
        for k, v in node.items():
            dotted = f"{prefix}.{k}"
            if isinstance(v, dict):
                walk(dotted, v)
            else:
                result[dotted] = v

    for section, value in DEFAULTS.items():
        if section in META_KEYS:
            continue
        if isinstance(value, dict):
            walk(section, value)
        # top-level scalars (none in current schema beyond meta keys)
    return result


def load_config() -> tuple[dict[str, object], dict[str, str]]:
    """
    Build resolved config.

    Returns:
        (values, sources) where both are {dotted_key: ...}
        sources maps each key to 'defaults' | 'global' | 'repo' | 'env:<VAR>'
    """
    values: dict[str, object] = {}
    sources: dict[str, str] = {}

    # Layer 1: Defaults
    flat_defaults = _flatten_defaults()
    for k, v in flat_defaults.items():
        values[k] = v
        sources[k] = "defaults"

    # Layer 2: Global user config
    global_path = _global_config_path()
    global_data = _load_toml(global_path)
    if global_data is not None:
        _check_schema_version(global_data, str(global_path))
        _validate_toml_keys(global_data, str(global_path))
        for section, sv in global_data.items():
            if section in META_KEYS:
                continue
            if not isinstance(sv, dict):
                if section in _DYNAMIC_MODEL_CONFIG_SECTIONS:
                    _reject_unsupported_dynamic_model_config_key(
                        section, str(global_path)
                    )
                continue
            for k, v in sv.items():
                if isinstance(v, dict):
                    if section == "model_classes":
                        # Host-keyed model classes may mix scalar legacy leaves with
                        # per-host-family sub-tables; delegate to the dedicated loader.
                        _load_model_class_table(
                            k, v, values, sources, flat_defaults,
                            str(global_path), is_global=True,
                        )
                        continue
                    if section == "model_routing" and any(
                        isinstance(subv, dict) for subv in v.values()
                    ):
                        _reject_dynamic_model_config_nested_table(
                            section, k, str(global_path)
                        )
                    # 3-level table nesting: two sub-cases:
                    # (a) watchdog.timeout_secs — dict of scalar leaves (section.k.subk)
                    # (b) roles.z_plan — dict of dicts (section.k.role_name.leaf_k)
                    is_scalar_dict = all(not isinstance(subv, dict) for subv in v.values())
                    if is_scalar_dict:
                        # Case (a): expand each leaf as a 3-level dotted key.
                        for subk, subv in v.items():
                            dotted = f"{section}.{k}.{subk}"
                            if dotted in flat_defaults:
                                subv = _validate_enum(dotted, subv, str(global_path), is_global=True)
                            else:
                                subv = _validate_dynamic_model_config_value(
                                    dotted, subv, str(global_path), is_global=True
                                )
                                if subv is None:
                                    continue
                            if dotted in _COERCERS:
                                subv = _COERCERS[dotted](subv)
                            values[dotted] = subv
                            sources[dotted] = str(global_path)
                    else:
                        # Case (b): roles-style 4-level nesting
                        # sv[k] == {"consultant_primary": {"persona": "X", ...}}
                        # k = "z_plan", v = {"consultant_primary": {"persona": "X", ...}}
                        for role_name, role_fields in v.items():
                            if not isinstance(role_fields, dict):
                                # Unexpected: skip non-dict at this level
                                continue
                            for leaf_k, leaf_v in role_fields.items():
                                dotted = f"{section}.{k}.{role_name}.{leaf_k}"
                                v_validated = _validate_roles_value(dotted, leaf_v, str(global_path), is_global=True)
                                if v_validated is not None:
                                    values[dotted] = v_validated
                                    sources[dotted] = str(global_path)
                else:
                    dotted = f"{section}.{k}"
                    if section in _DYNAMIC_MODEL_CONFIG_SECTIONS:
                        _reject_unsupported_dynamic_model_config_key(
                            dotted, str(global_path)
                        )
                    # Silently ignore unknown 2-level keys for forward compatibility.
                    if dotted not in flat_defaults:
                        continue
                    v = _validate_enum(dotted, v, str(global_path), is_global=True)
                    if dotted in _COERCERS:
                        v = _COERCERS[dotted](v)
                    values[dotted] = v
                    sources[dotted] = str(global_path)

    # Layer 3: Repo-local config
    repo_path = _repo_config_path()
    repo_data = _load_toml(repo_path)
    if repo_data is not None:
        _check_schema_version(repo_data, str(repo_path))
        _validate_toml_keys(repo_data, str(repo_path))
        for section, sv in repo_data.items():
            if section in META_KEYS:
                continue
            if not isinstance(sv, dict):
                if section in _DYNAMIC_MODEL_CONFIG_SECTIONS:
                    _reject_unsupported_dynamic_model_config_key(
                        section, str(repo_path)
                    )
                continue
            for k, v in sv.items():
                if isinstance(v, dict):
                    if section == "model_classes":
                        # Host-keyed model classes may mix scalar legacy leaves with
                        # per-host-family sub-tables; delegate to the dedicated loader.
                        _load_model_class_table(
                            k, v, values, sources, flat_defaults,
                            str(repo_path), is_global=False,
                        )
                        continue
                    if section == "model_routing" and any(
                        isinstance(subv, dict) for subv in v.values()
                    ):
                        _reject_dynamic_model_config_nested_table(
                            section, k, str(repo_path)
                        )
                    # 3-level table nesting: two sub-cases:
                    # (a) watchdog.timeout_secs — dict of scalar leaves (section.k.subk)
                    # (b) roles.z_plan — dict of dicts (section.k.role_name.leaf_k)
                    is_scalar_dict = all(not isinstance(subv, dict) for subv in v.values())
                    if is_scalar_dict:
                        # Case (a): expand each leaf as a 3-level dotted key.
                        for subk, subv in v.items():
                            dotted = f"{section}.{k}.{subk}"
                            if dotted in flat_defaults:
                                subv = _validate_enum(dotted, subv, str(repo_path), is_global=False)
                            else:
                                subv = _validate_dynamic_model_config_value(
                                    dotted, subv, str(repo_path), is_global=False
                                )
                                if subv is None:
                                    continue
                            if dotted in _COERCERS:
                                subv = _COERCERS[dotted](subv)
                            values[dotted] = subv
                            sources[dotted] = str(repo_path)
                    else:
                        # Case (b): roles-style 4-level nesting
                        # sv[k] == {"consultant_primary": {"persona": "X", ...}}
                        # k = "z_plan", v = {"consultant_primary": {"persona": "X", ...}}
                        for role_name, role_fields in v.items():
                            if not isinstance(role_fields, dict):
                                # Unexpected: skip non-dict at this level
                                continue
                            for leaf_k, leaf_v in role_fields.items():
                                dotted = f"{section}.{k}.{role_name}.{leaf_k}"
                                v_validated = _validate_roles_value(dotted, leaf_v, str(repo_path), is_global=False)
                                if v_validated is not None:
                                    values[dotted] = v_validated
                                    sources[dotted] = str(repo_path)
                else:
                    dotted = f"{section}.{k}"
                    if section in _DYNAMIC_MODEL_CONFIG_SECTIONS:
                        _reject_unsupported_dynamic_model_config_key(
                            dotted, str(repo_path)
                        )
                    # Silently ignore unknown 2-level keys for forward compatibility.
                    if dotted not in flat_defaults:
                        continue
                    v = _validate_enum(dotted, v, str(repo_path), is_global=False)
                    if dotted in _COERCERS:
                        v = _COERCERS[dotted](v)
                    values[dotted] = v
                    sources[dotted] = str(repo_path)

    # Layer 4: Env vars — TOML wins (T001 ingress-ignore gate)
    #
    # Preference-class env vars (Z_HARNESS_<SECTION>_<KEY> transliterations and
    # their legacy aliases) do NOT override a value that was already set by a TOML
    # layer (global or repo).  The env is still consulted when the key's source is
    # "defaults" (i.e. TOML was silent), so existing tests and migration aliases
    # continue to work for keys not yet written to config.toml.
    #
    # For each config key, check (a) transliteration var and (b) legacy alias var
    # (when the raw name differs from transliteration). The transliteration takes
    # precedence when both are set.
    for dotted_key in list(flat_defaults.keys()):
        # TOML-wins gate: skip env lookup if a TOML layer already provided this key.
        if sources.get(dotted_key, "defaults") != "defaults":
            continue

        # Skip 3-level nested keys (e.g. watchdog.timeout_secs.bash) — config-file-only.
        # _dotted_to_env() only accepts exactly 2 segments; 3-level keys would sys.exit(2).
        if dotted_key.count(".") >= 2:
            continue

        transliteration = _dotted_to_env(dotted_key)
        env_val = os.environ.get(transliteration, "")
        env_var = transliteration

        if env_val == "":
            # Fall back to legacy alias name (e.g. Z_HARNESS_PRE_REVIEW for
            # runtime.pre_review, whose transliteration is Z_HARNESS_RUNTIME_PRE_REVIEW).
            alias_var = _INGRESS_LEGACY_ALIASES.get(dotted_key)
            if alias_var:
                legacy_val = os.environ.get(alias_var, "")
                if legacy_val != "":
                    env_val = legacy_val
                    env_var = alias_var

        if env_val == "":
            continue
        env_val = _validate_enum(dotted_key, env_val, f"env {env_var}", is_global=False)
        if dotted_key in _COERCERS:
            env_val = _COERCERS[dotted_key](env_val)
        values[dotted_key] = env_val
        sources[dotted_key] = f"env {env_var}"

    # Deprecation surface (T005): warn (or error) when preference-class env vars
    # are detected in the raw environment.  This runs after all layers are built
    # so we can read runtime.env_strict from the resolved config.
    _check_deprecated_env_vars(values)

    return values, sources


def _check_deprecated_env_vars(values: dict) -> None:
    """
    Emit deprecation warnings (or a hard error) for preference-class env vars
    that the user has set in the raw process environment.

    When ``runtime.env_strict`` is ``True`` (set via config.toml [runtime]
    env_strict = true, NOT a raw env var), finding any such var is a hard ERROR:
    prints all offenders to stderr and exits non-zero (exit code 2).

    When ``runtime.env_strict`` is ``False`` (the default), emits a non-fatal
    WARNING to stderr for each offender and continues.

    Reuses ``_collect_deprecated_env_vars()`` — the same set that
    ``cmd_export_env`` uses for ``unset`` lines — so there is no drift between
    the two surfaces.
    """
    deprecated = _collect_deprecated_env_vars()
    if not deprecated:
        return

    env_strict = values.get("runtime.env_strict", False)
    if isinstance(env_strict, str):
        env_strict = env_strict.lower() == "true"

    lines = []
    for dotted_key, vars_list in sorted(deprecated.items()):
        for var in vars_list:
            lines.append(
                f"[config] DEPRECATED: preference env var {var!r} is set "
                f"(maps to config key {dotted_key!r}). "
                "Set it in config.toml instead: "
                f"run `config.py ensure-defaults` then edit [runtime] / relevant section."
            )

    if env_strict:
        for line in lines:
            print(line, file=sys.stderr)
        print(
            "[config] ERROR: runtime.env_strict = true — deprecated preference env vars "
            "are not allowed. Unset the vars above or migrate them to config.toml.",
            file=sys.stderr,
        )
        sys.exit(2)
    else:
        for line in lines:
            print(f"WARNING: {line}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Event emission (export-env only)
# ---------------------------------------------------------------------------

def _emit_config_resolved(values: dict, sources: dict) -> None:
    """
    Emit config_resolved event once per $Z_HARNESS_RUN via O_EXCL de-dup.
    No-op if $Z_HARNESS_RUN is not set.
    """
    run = os.environ.get("Z_HARNESS_RUN", "")
    if not run:
        return

    tmpdir = tempfile.gettempdir()
    stamp = os.path.join(tmpdir, f"z-harness-config-resolved-{run}")
    try:
        fd = os.open(stamp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return  # already emitted for this run

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({"values": values, "sources": sources})
    try:
        subprocess.run(
            ["bash", str(log_event), run, "config_resolved", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _valid_user_keys() -> list[str]:
    """Return all dotted leaf keys that are NOT meta keys.

    Includes 3-level nested keys (e.g. watchdog.timeout_secs.bash) by delegating
    to _flatten_defaults(), which already expands nested dicts into dotted leaves.
    """
    return sorted(_flatten_defaults().keys())


def cmd_get(args: list[str]) -> None:
    if len(args) != 1:
        print("usage: config.py get <dotted.key>", file=sys.stderr)
        sys.exit(2)
    key = args[0]
    if key in META_KEYS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] {key!r} is a meta key; valid user keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    values, _ = load_config()
    if key not in values:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    # Print raw scalar (no quotes, no shlex).
    # Lists are printed as JSON arrays for shell-safe consumption.
    val = values[key]
    if isinstance(val, bool):
        print("true" if val else "false")
    elif isinstance(val, list):
        print(json.dumps(val))
    else:
        print(val)


def cmd_get_batch(args: list[str]) -> None:
    """get-batch <key1> <key2> ...

    Resolve multiple config keys in a single process and print a JSON object
    mapping each key to its value.  Unknown keys are included with a null value
    and a warning to stderr.  Meta keys are excluded.

    Output: JSON object {"key1": "val1", "key2": true, ...}
    Exit 0 always (best-effort; callers fall back to defaults for null values).
    """
    if not args:
        print("usage: config.py get-batch <key1> [key2 ...]", file=sys.stderr)
        sys.exit(2)

    values, _ = load_config()
    result: dict[str, object] = {}
    for key in args:
        if key in META_KEYS:
            print(f"[config] get-batch: {key!r} is a meta key; skipping", file=sys.stderr)
            result[key] = None
            continue
        if key not in values:
            print(f"[config] get-batch: unknown key {key!r}; returning null", file=sys.stderr)
            result[key] = None
            continue
        result[key] = values[key]
    print(json.dumps(result))


def _collect_deprecated_env_vars() -> dict[str, list[str]]:
    """
    Return a mapping of dotted_key → [env_var_names] for all preference env
    vars that the user has set in the raw process environment (os.environ) and
    that are NOT allowlisted (plumbing / unattended).

    Used by cmd_export_env to emit ``unset`` lines before the corresponding
    ``export`` line.  The unset is COSMETIC single-shell cleanup only — it
    removes stale preference vars from the caller's shell so they don't
    inadvertently shadow a later eval.  Correctness across Bash tool calls
    (where the env is reset between calls) comes from T004's ``config.py get``
    conversion, not this unset.

    Both the mechanical transliteration (Z_HARNESS_<SECTION>_<KEY>) and the
    legacy alias (from _INGRESS_LEGACY_ALIASES) are checked; all that are
    actually set in os.environ and not allowlisted are collected.  Allowlisted
    vars (LEGAL_ENV_KEYS / LEGAL_ENV_PREFIXES) are never included.
    """
    result: dict[str, list[str]] = {}
    flat_defaults = _flatten_defaults()
    for dotted_key in flat_defaults:
        # Skip 3-level config-file-only keys — they have no env var transliteration.
        if dotted_key.count(".") >= 2:
            continue
        transliteration = _dotted_to_env(dotted_key)
        alias = _INGRESS_LEGACY_ALIASES.get(dotted_key)
        candidates = [transliteration]
        if alias and alias != transliteration:
            candidates.append(alias)
        deprecated = []
        for var in candidates:
            if _is_legal_env(var):
                continue  # allowlisted — never unset
            if os.environ.get(var, "") != "":
                deprecated.append(var)
        if deprecated:
            result[dotted_key] = deprecated
    return result


def _emit_config_env_deprecated(env_var: str, dotted_key: str) -> None:
    """
    Emit a config_env_deprecated event via log-event.sh for one deprecated
    preference env var.  Non-fatal: silently skips if $Z_HARNESS_RUN is unset
    or log-event.sh is unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({"env_var": env_var, "dotted_key": dotted_key})
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "config_env_deprecated", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def cmd_export_env(args: list[str]) -> None:
    """
    Print shell statements to stdout suitable for eval in a single shell session:

      - ``export VAR=value`` for every resolved user knob (excluding meta and roles keys).
      - ``unset OLD_VAR`` immediately before the corresponding ``export`` line for any
        preference env var the user has set in the raw process environment whose dotted
        key is NOT allowlisted.  This is a COSMETIC single-shell cleanup only — it
        prevents stale preference env vars from shadowing the freshly-exported resolved
        value inside the same shell session.  Correctness across Bash tool calls (where
        the process env is reset between calls) comes from T004's ``config.py get``
        conversion, not this unset.  Allowlisted (plumbing / unattended) vars are
        never unset.

    After emitting all lines, emits a ``config_env_deprecated`` event per deprecated var
    and (once per Z_HARNESS_RUN) a ``config_resolved`` event.
    """
    values, sources = load_config()
    deprecated = _collect_deprecated_env_vars()

    for dotted_key in sorted(values.keys()):
        # Skip roles.* keys — they are not exported as env vars
        first_segment = dotted_key.split(".", 1)[0]
        if first_segment == "roles":
            continue
        # Skip 3-level nested config-file-only keys (watchdog.timeout_secs.*).
        # Exporting nested int tables as env vars risks the None→'' poisoning
        # gotcha; read them via `config.py get watchdog.timeout_secs.<type>` only.
        if dotted_key.count(".") >= 2:
            continue
        env_var = _ENV_VAR_ALIASES.get(dotted_key) or _dotted_to_env(dotted_key)
        val = values[dotted_key]
        # Coerce to shell string.
        # Lists are JSON-encoded for shell transport (consumer can decode with jq or python -m json.tool).
        if val is None:
            # Nullable keys (e.g. cost.token_budget) must round-trip: emit empty
            # string, NOT the literal "None". The ingress path treats "" as unset
            # (v is None or v == ""), whereas "None" fails enum/coercion validation
            # and makes a subsequent `config.py get` exit non-zero — which silently
            # poisons every config read in a shell that sourced `export-env`.
            shell_val = ""
        elif isinstance(val, bool):
            shell_val = "true" if val else "false"
        elif isinstance(val, list):
            shell_val = json.dumps(val)
        else:
            shell_val = str(val)
        # Emit unset lines for any deprecated preference vars bound to this key,
        # BEFORE the export line.  Both the transliteration and legacy alias are
        # unset when set; the export line always uses the canonical alias name.
        if dotted_key in deprecated:
            for old_var in deprecated[dotted_key]:
                print(f"unset {old_var}")
        print(f"export {env_var}={shlex.quote(shell_val)}")

    # Emit one config_env_deprecated event per deprecated var (best-effort).
    for dotted_key, vars_list in deprecated.items():
        for old_var in vars_list:
            _emit_config_env_deprecated(old_var, dotted_key)

    _emit_config_resolved(values, sources)


def cmd_ensure_defaults(args: list[str]) -> None:
    global_path = _global_config_path()

    if global_path.exists():
        # Check for 0-byte or unparseable
        if global_path.stat().st_size == 0:
            print(
                f"[config] file exists but is empty: {global_path}. "
                "Remove or fix it manually.",
                file=sys.stderr,
            )
            sys.exit(4)
        try:
            with open(global_path, "rb") as fh:
                tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            print(
                f"[config] file exists but is unparseable: {global_path}. "
                f"Remove or fix it manually. Parse error: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)
        print(f"exists {global_path}")
        return

    # Create parent directory if needed
    try:
        global_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"[config] cannot create directory {global_path.parent}: {exc}",
            file=sys.stderr,
        )
        sys.exit(4)

    # Write default config with inline comments
    content = (
        '# z-harness config — generated by "scripts/config.py ensure-defaults"\n'
        "# Edit freely. Run 'scripts/config.py explain <key>' to see effective values.\n"
        "\n"
        "schema_version = 2\n"
        "\n"
        "[notify]\n"
        "# Notification verbosity. Values: off | approval_only | all\n"
        'level = "approval_only"\n'
        "\n"
        "[docs]\n"
        "# Whether to auto-apply docs in light flows. Values: always | never\n"
        'always_apply = "always"\n'
        "\n"
        "# Default role bindings — persona + model + runtime per logical role.\n"
        "# Override per command with [roles.<command>.<role>] sections.\n"
        "\n"
        "[roles.default.consultant_primary]\n"
        'persona = "codex-default-consultant"\n'
        'model = ""              # empty = use provider\'s default_model\n'
        'runtime = "codex-cli"\n'
        "\n"
        "[roles.default.consultant_secondary]\n"
        'persona = "gemini-default-consultant"\n'
        'runtime = "gemini-cli"\n'
        "\n"
        "[roles.default.reviewer]\n"
        'persona = "codex-default-reviewer"\n'
        'runtime = "codex-cli"\n'
    )
    try:
        global_path.write_text(content)
    except OSError as exc:
        print(
            f"[config] cannot write {global_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(4)
    print(f"created {global_path}")


def cmd_explain(args: list[str]) -> None:
    if len(args) != 1:
        print("usage: config.py explain <dotted.key>", file=sys.stderr)
        sys.exit(2)
    key = args[0]
    if not _KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            "(2 to 4 lowercase dot-separated segments, underscores/digits only)",
            file=sys.stderr,
        )
        sys.exit(2)
    if key in META_KEYS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] {key!r} is a meta key; valid user keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    values, sources = load_config()
    if key not in values:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    val = values[key]
    src = sources[key]
    print(f'{key} = "{val}"   (source: {src})')


def cmd_list_question_ids(args: list[str]) -> None:
    """Print a sorted JSON array of registered question IDs to stdout."""
    print(json.dumps(sorted(QUESTION_IDS.keys())))


def cmd_resolve_halt_category(args: list[str]) -> None:
    """
    resolve-halt-category <question_id>

    Print the halt_category tag for the given question_id to stdout, or the
    literal "ask" (fail-safe default) when the qid is unknown or untagged.

    Exit 0 with a given question_id (stdout is the bare tag string, no JSON
    wrapper). Exit 2 with no arguments (usage error to stderr).
    """
    if not args:
        print(
            "usage: config.py resolve-halt-category <question_id>",
            file=sys.stderr,
        )
        sys.exit(2)
    qid = args[0]
    meta = QUESTION_IDS.get(qid)
    if meta is None:
        print("ask")
        return
    cat = meta.get("halt_category")
    if cat not in HALT_CATEGORY_ENUM:
        # Defensive: guard should have caught this at module load, but fail safe.
        print("ask")
        return
    print(cat)


# ---------------------------------------------------------------------------
# resolve-question subcommand
# ---------------------------------------------------------------------------

def _emit_hermes_needs_input(
    question_id: str,
    choices: list,
    skill_default: str,
) -> None:
    """
    Emit a needs_input hermes marker via emit-hermes-marker.sh.

    Called when HERMES_MARKER_FILE is set and the orchestrator would normally
    call AskUserQuestion for this question.  Non-fatal — silently skips if the
    script is unavailable or the env var is unset.
    """
    marker_file = os.environ.get("HERMES_MARKER_FILE", "")
    if not marker_file:
        return

    script_dir = Path(__file__).parent
    emit_script = script_dir / "emit-hermes-marker.sh"
    if not emit_script.exists() or not shutil.which("bash"):
        return

    task = os.environ.get("Z_HARNESS_SLUG", "") or os.environ.get("Z_HARNESS_RUN", "") or "orchestration"
    payload = json.dumps({
        "question": question_id,
        "options": sorted(choices),
        "context": "hermes-managed",
    })
    try:
        subprocess.run(
            ["bash", str(emit_script), "needs_input", task, payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — best-effort


def _emit_askuser_resolved(
    question_id: str,
    result: str,
    source: str,
    strength: str,
) -> None:
    """
    Emit an askuser_resolved event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({
        "question_id": question_id,
        "result": result,
        "source": source,
        "strength": strength,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "askuser_resolved", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _get_project_root() -> str:
    """
    Return the current project root for memory scope filtering.

    Priority:
      1. Z_HARNESS_PROJECT_ROOT env var
      2. git rev-parse --show-toplevel
      3. Empty string (treat all memories as scope=global matches when outside a git repo)
    """
    project_root = os.environ.get("Z_HARNESS_PROJECT_ROOT", "")
    if project_root:
        return project_root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _emit_routing_preference_malformed(location: str, index: int, reason: str) -> None:
    """
    Emit a routing_preference_malformed event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        print(
            f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
            file=sys.stderr,
        )
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        print(
            f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
            file=sys.stderr,
        )
        return

    payload = json.dumps({
        "location": location,
        "index": index,
        "reason": reason,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "routing_preference_malformed", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort
    print(
        f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Overnight override helpers (halt-from-ask integration)
# ---------------------------------------------------------------------------

def _parse_overnight_allowlist(s: str) -> dict[str, str]:
    """
    Parse the Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE env var (a JSON object
    string) into a {question_id: chosen_value} dict.

    Returns the merged allowlist: OVERNIGHT_AUTODECIDE_QIDS_DEFAULT entries
    overlaid by the parsed env entries (env wins on key collision).

    Malformed entries (non-string keys/values, invalid question_id, or invalid
    choice for the question_id) are dropped with a routing_preference_malformed
    event and a stderr warning.  An unparseable JSON string causes the env
    layer to be skipped entirely (defaults still apply).
    """
    merged: dict[str, str] = dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT)

    if not s.strip():
        return merged

    try:
        env_data = json.loads(s)
    except json.JSONDecodeError as exc:
        print(
            f"[config] Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE is not valid JSON: {exc}; "
            "falling back to default allowlist",
            file=sys.stderr,
        )
        return merged

    if not isinstance(env_data, dict):
        print(
            "[config] Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE must be a JSON object; "
            "falling back to default allowlist",
            file=sys.stderr,
        )
        return merged

    for idx, (qid, value) in enumerate(env_data.items()):
        if not isinstance(qid, str) or not isinstance(value, str):
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                "key and value must both be strings"
            )
            continue
        if qid not in QUESTION_IDS:
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                f"unknown question_id {qid!r}"
            )
            continue
        if value not in QUESTION_IDS[qid]["choices"]:
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                f"invalid value {value!r} for question_id {qid!r}; "
                f"allowed: {sorted(QUESTION_IDS[qid]['choices'])}"
            )
            continue
        merged[qid] = value

    return merged


def _emit_config_conflict(conflict: str, payload: dict) -> None:
    """
    Emit a config_conflict event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    Also prints a warning to stderr.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    print(
        f"[config] config_conflict: {conflict}",
        file=sys.stderr,
    )
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    event_payload = json.dumps({"conflict": conflict, **payload})
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "config_conflict", event_payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _apply_overnight_overrides(
    envelope: dict,
    question_id: str,
) -> dict:
    """
    Post-process the resolution envelope for overnight/halt-from-ask behavior.

    This function is called from cmd_resolve_question AFTER building the envelope
    and BEFORE emitting telemetry + printing to stdout.

    Rules (in priority order):
    1. If Z_HARNESS_NO_ASK != 'halt' → no-op, return envelope unchanged.
    2. If Z_HARNESS_ASK_ALL=1 AND Z_HARNESS_NO_ASK=halt → conflict: emit
       config_conflict event, print error JSON, exit 5.
    3. If envelope['result'] == 'ask' and question_id in allowlist →
       swap to overnight_decision envelope; emit overnight_decision event.
    4. If envelope['result'] == 'ask' and question_id not in allowlist →
       swap to halt envelope; emit askuser_halted event.
    5. Else (result is skip/prefill — no ask needed) → no-op.

    Returns the (possibly modified) envelope.  Never returns on cases 2+.
    """
    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask != "halt":
        return envelope

    # Case 2: conflicting config
    ask_all = os.environ.get("Z_HARNESS_ASK_ALL", "")
    if ask_all == "1":
        conflict_envelope = {
            "error": "config_conflict",
            "conflict": "Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt are mutually exclusive",
            "result": "error",
        }
        _emit_config_conflict(
            "Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt",
            {"question_id": question_id},
        )
        print(json.dumps(conflict_envelope))
        sys.exit(5)

    # Only override when the resolved result is 'ask'
    if envelope.get("result") != "ask":
        return envelope

    skill_default: str = envelope.get("default", "")
    qmeta = QUESTION_IDS.get(question_id, {})
    choices: list[str] = sorted(qmeta.get("choices", []))

    # Build would_have_asked (D4: only default + choices — no question/header text)
    would_have_asked = {
        "default": skill_default,
        "choices": choices,
    }

    allowlist = _parse_overnight_allowlist(
        os.environ.get("Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", "")
    )

    if question_id in allowlist:
        # Case 3: allowlist hit → overnight_decision
        chosen_value = allowlist[question_id]
        mapped_result = RESULT_MAP.get((question_id, chosen_value), "ask")
        overnight_envelope = {
            "result": mapped_result,
            "default": skill_default,
            "source": "overnight_allowlist",
            "rule_id": f"{question_id}:{chosen_value}",
            "strength": "policy",
            "reason": f"overnight allowlist: {question_id} = {chosen_value}",
            "sources": [{"kind": "allowlist", "value": chosen_value,
                         "location": "OVERNIGHT_AUTODECIDE_QIDS or env"}],
            "chosen": chosen_value,
        }
        _emit_overnight_event("overnight_decision", {
            "question_id": question_id,
            "chosen": chosen_value,
            "source": "overnight_allowlist",
            "strength": "policy",
            "rule_id": f"{question_id}:{chosen_value}",
            "sources": overnight_envelope["sources"],
        })
        return overnight_envelope
    else:
        # Case 4: not in allowlist → halt
        halt_envelope = {
            "result": "halt",
            "default": skill_default,
            "source": "no_ask_halt",
            "rule_id": "no_ask_halt",
            "strength": "policy",
            "reason": "Z_HARNESS_NO_ASK=halt and question_id not in overnight allowlist",
            "sources": [{"kind": "env", "value": "halt", "location": "Z_HARNESS_NO_ASK"}],
            "halt_reason": "no_ask_blocked",
            "question_id": question_id,
            "would_have_asked": would_have_asked,
        }
        _emit_overnight_event("askuser_halted", {
            "question_id": question_id,
            "would_have_asked": would_have_asked,
        })
        return halt_envelope


def _emit_overnight_event(kind: str, payload: dict) -> None:
    """
    Emit an overnight-related event (overnight_decision, askuser_halted) via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    event_payload = json.dumps(payload)
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, kind, event_payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


# Required fields for a routing-preference memory entry
_ROUTING_PREF_REQUIRED_FIELDS = {"type", "question_id", "value", "scope", "strength"}


def _load_memory_matches(question_id: str, project_root: str) -> list[dict]:
    """
    Walk docs/llm/*.json (skipping INDEX.json), filter memories[] for
    type=routing-preference matching question_id, respect scope.

    Returns list of dicts: {value, strength, location, scope}
    Malformed entries are logged via _emit_routing_preference_malformed and skipped.

    NOTE: docs_dir is resolved relative to the harness repo (where config.py lives),
    not relative to project_root. project_root is only used for scope filtering.
    """
    # Resolve docs/llm relative to the harness repo root (parent of scripts/)
    harness_root = Path(__file__).parent.parent
    docs_dir = harness_root / "docs" / "llm"
    if not docs_dir.is_dir():
        # Fallback to CWD-based resolution for non-standard layouts
        docs_dir = Path.cwd() / "docs" / "llm"

    if not docs_dir.is_dir():
        return []

    matches = []
    for json_path in sorted(docs_dir.glob("*.json")):
        if json_path.name == "INDEX.json":
            continue

        try:
            with open(json_path, "rb") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[config] skipping {json_path}: {exc}",
                file=sys.stderr,
            )
            continue

        memories = data.get("memories", [])
        if not isinstance(memories, list):
            continue

        for idx, entry in enumerate(memories):
            if not isinstance(entry, dict):
                _emit_routing_preference_malformed(str(json_path), idx, "entry is not a dict")
                continue

            if entry.get("type") != "routing-preference":
                continue

            # Validate required fields
            missing = _ROUTING_PREF_REQUIRED_FIELDS - set(entry.keys())
            if missing:
                _emit_routing_preference_malformed(
                    str(json_path), idx, f"missing required fields: {sorted(missing)}"
                )
                continue

            if entry["question_id"] != question_id:
                continue

            # Validate strength field
            strength = entry["strength"]
            if strength not in {"weak", "strong", "very_strong"}:
                _emit_routing_preference_malformed(
                    str(json_path), idx,
                    f"invalid strength {strength!r}; allowed: weak, strong, very_strong"
                )
                continue

            # Validate value field
            qmeta = QUESTION_IDS.get(question_id)
            if qmeta and entry["value"] not in qmeta["choices"]:
                _emit_routing_preference_malformed(
                    str(json_path), idx,
                    f"invalid value {entry['value']!r} for question_id {question_id!r}"
                )
                continue

            # Respect scope
            scope = entry["scope"]
            if scope == "global":
                pass  # always included
            elif scope == "project":
                entry_project_root = entry.get("project_root", "")
                if not project_root:
                    # Outside a git repo: treat all as global (edge case per SPEC)
                    pass
                elif entry_project_root != project_root:
                    continue  # doesn't match current project
            else:
                _emit_routing_preference_malformed(
                    str(json_path), idx, f"invalid scope {scope!r}; allowed: global, project"
                )
                continue

            matches.append({
                "value": entry["value"],
                "strength": strength,
                "location": str(json_path),
                "scope": scope,
            })

    return matches


# ---------------------------------------------------------------------------
# Axiom layer (lowest behavioral-authority signal — advisory, conflict-surfaced)
# ---------------------------------------------------------------------------

# Cache the dynamically-loaded axiom-store module (its filename has a hyphen, so
# it cannot be imported with a plain `import`). Resolved as a sibling of config.py.
_AXIOM_STORE_MODULE = None
_AXIOM_STORE_LOAD_FAILED = False


def _load_axiom_store_module():
    """
    Dynamically load scripts/axiom-store.py (sibling of config.py) by file path.

    The store module's filename contains a hyphen, so a normal `import` is not
    possible; we resolve it relative to config.py (the same way other helpers
    locate sibling scripts via ``Path(__file__).parent``) and load it through
    importlib. Returns the module, or None if it is absent / fails to import.
    Result is cached so the resolver only pays the import cost once per process.
    """
    global _AXIOM_STORE_MODULE, _AXIOM_STORE_LOAD_FAILED
    if _AXIOM_STORE_MODULE is not None:
        return _AXIOM_STORE_MODULE
    if _AXIOM_STORE_LOAD_FAILED:
        return None

    import importlib.util

    store_path = Path(__file__).parent / "axiom-store.py"
    if not store_path.exists():
        _AXIOM_STORE_LOAD_FAILED = True
        return None
    try:
        spec = importlib.util.spec_from_file_location("axiom_store", str(store_path))
        if spec is None or spec.loader is None:
            _AXIOM_STORE_LOAD_FAILED = True
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError) as exc:
        print(f"[config] could not load axiom-store.py: {exc}", file=sys.stderr)
        _AXIOM_STORE_LOAD_FAILED = True
        return None

    _AXIOM_STORE_MODULE = module
    return module


def _load_axiom_matches(question_id: str, project_root: str) -> list[dict]:
    """
    Load graph-valid, approved axioms that answer ``question_id`` and return the
    option values they recommend. Mirrors ``_load_memory_matches`` in shape.

    Pipeline (SPEC `## scripts/config.py` + R3):
      1. If ``axioms.enabled`` is false → return ``[]`` (no participation).
      2. Load the merged global+project active set through axiom-store's
         ``_load_active_set`` (project shadows global by id).
      3. Keep only ``approved`` records, then filter through the SINGLE shared
         ``validate_graph`` (R3): only records in the validated active set
         participate. If the whole set fails graph validation, none participate.
      4. For each surviving record, scan ``applies_to`` for an entry whose
         ``<question_id>`` half (split on the FIRST ``:``) equals the requested
         ``question_id``. Records with no matching entry never participate.
      5. Extract the ``<value>`` half. DROP the match if ``<value>`` is not a
         legal choice in ``QUESTION_IDS[question_id]["choices"]`` — choice
         membership is validated HERE, not in the store (SPEC line 78).

    Returns list of dicts: ``{value, id, statement, scope}``.

    ``project_root`` is forwarded to the store loader for project-scope
    resolution. When the store module is absent or unloadable, returns ``[]``
    (axioms simply do not participate — backward-compatible).
    """
    # Step 1: axioms.enabled gate. Read it from the resolved 4-layer config
    # (a second load_config() within one resolver invocation is the per-invocation
    # snapshot R10 explicitly scopes correctness to — no cross-invocation atomicity
    # is promised). On any config error, fail closed (axioms do not participate).
    try:
        values, _sources = load_config()
    except (SystemExit, OSError):
        return []
    if not values.get("axioms.enabled", True):
        return []

    qmeta = QUESTION_IDS.get(question_id)
    if qmeta is None:
        return []
    choices = qmeta["choices"]

    store = _load_axiom_store_module()
    if store is None:
        return []

    # Step 2: merged active set (global+project, project shadows global by id).
    try:
        records = store._load_active_set(None, project_root or None)
    except (OSError, AttributeError) as exc:
        print(f"[config] axiom active-set load failed: {exc}", file=sys.stderr)
        return []

    # Step 3: keep approved records, then graph-validate via the SINGLE shared
    # validator (R3). Only the validated active set participates.
    approved = [r for r in records if isinstance(r, dict) and r.get("status") == "approved"]
    if not approved:
        return []
    try:
        graph = store.validate_graph(approved)
    except (AttributeError, TypeError) as exc:
        print(f"[config] axiom graph validation failed: {exc}", file=sys.stderr)
        return []
    if not graph.get("ok", False):
        # Corrupt active set → no axiom participates (resolver stays in agreement
        # with the kernel compiler, which also refuses to emit a bad set).
        return []

    matches: list[dict] = []
    for rec in approved:
        applies_to = rec.get("applies_to") or []
        if not isinstance(applies_to, list):
            continue
        for entry in applies_to:
            if not isinstance(entry, str) or ":" not in entry:
                continue
            # Step 4: split on the FIRST ':'. Left half = question_id, right = value.
            entry_qid, value = entry.split(":", 1)
            if entry_qid != question_id:
                continue
            # Step 5: choice-membership validation lives HERE, not in the store.
            if value not in choices:
                continue
            matches.append({
                "value": value,
                "id": rec.get("id"),
                "statement": rec.get("statement"),
                "scope": rec.get("scope"),
            })

    # Sort by id (ascending, lexicographic) so the caller always sees a deterministic
    # order regardless of dict-iteration order in _load_active_set.
    matches.sort(key=lambda m: (m["id"] or ""))
    return matches


# Strength ordering for "highest strength wins"
_STRENGTH_ORDER = {"very_strong": 3, "strong": 2, "weak": 1}


def _resolve_memory_matches(
    matches: list[dict],
) -> tuple[Optional[str], Optional[str], list[dict]]:
    """
    Given a list of memory match dicts, return (value, strength, sources).

    - No matches → (None, None, [])
    - One match → (value, strength, [source])
    - Multiple agreeing → highest strength wins → (value, strength, all_sources)
    - Multiple disagreeing → (None, "conflict", all_sources) signals conflict
    """
    if not matches:
        return None, None, []

    # Gather all unique values
    values_seen = {m["value"] for m in matches}

    sources = [
        {
            "kind": "memory",
            "value": m["value"],
            "location": m["location"],
            "strength": m["strength"],
        }
        for m in matches
    ]

    if len(values_seen) == 1:
        # All agree — pick highest strength
        best = max(matches, key=lambda m: _STRENGTH_ORDER.get(m["strength"], 0))
        return best["value"], best["strength"], sources

    # Disagreeing
    return None, "conflict", sources


def _resolve_config_memory_envelope(
    question_id: str,
    explain: bool = False,
) -> tuple[dict, str, str, str, int, Optional[str], bool]:
    """
    Build the config+memory resolution envelope for a registered question_id.

    This is the pre-axiom resolution (config + routing-pref memory only). The
    axiom layer is applied on top by ``_build_resolve_envelope``.

    Returns ``(envelope, emit_result, emit_source, emit_strength, exit_code,
    resolved_value, memory_silent)`` where:
      - the first five elements are the historical 5-tuple (unchanged meaning);
      - ``resolved_value`` is the winning *option-domain* value a higher layer
        set, or ``None`` when nothing was set (gap) or the layers conflict;
      - ``memory_silent`` is True when no routing-pref memory entry matched.
    These last two are internal signals the axiom layer uses to decide
    agree / gap-fill / direct-conflict; callers outside this module never see them.

    Precondition: ``question_id`` must be present in ``QUESTION_IDS`` (caller checks).
    ``Z_HARNESS_ASK_ALL=1`` short-circuit is NOT applied here — the caller handles it
    before calling this function so that the early-exit path stays in one place.
    """
    qmeta = QUESTION_IDS[question_id]
    skill_default: str = qmeta["skill_default"]
    config_key: str = qmeta["config_key"]

    # Consult 4-layer config
    try:
        values, sources = load_config()
    except SystemExit:
        # load_config exits on I/O or schema errors; re-raise is the right path
        raise
    except OSError as exc:
        envelope = {
            "error": "io_error",
            "message": str(exc),
            "result": "ask",
            "default": skill_default,
            "source": "none",
            "rule_id": config_key,
            "strength": "none",
            "reason": f"I/O error reading config: {exc}",
            "sources": [],
        }
        print(str(exc), file=sys.stderr)
        return envelope, "ask", "none", "none", 4, None, True

    config_value: str = values.get(config_key, "ask")
    config_source_label: str = sources.get(config_key, "defaults")

    # Default value for this config key (the "ask" string means "no preference set")
    default_config_value: str = "ask"
    config_is_default: bool = config_value == default_config_value

    # Consult memory (JSON walk over docs/llm/*.json)
    project_root = _get_project_root()
    memory_matches = _load_memory_matches(question_id, project_root)
    mem_value, mem_strength, mem_sources = _resolve_memory_matches(memory_matches)

    # Combine config + memory signals

    # Case: no memory at all
    if mem_value is None and mem_strength is None:
        if config_is_default:
            # No config preference, no memory → ask
            if explain:
                print(
                    f"[explain] question_id={question_id} → config=ask (default), "
                    "no memory → result=ask",
                    file=sys.stderr,
                )
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "none",
                "rule_id": config_key,
                "strength": "none",
                "reason": "No config preference set and no memory entries found",
                "sources": [],
            }
            return envelope, "ask", "none", "none", 0, None, True
        else:
            # Config has a non-default value, no memory → config wins
            mapped_result = RESULT_MAP.get((question_id, config_value), "ask")
            reason = (
                f"config key {config_key!r} = {config_value!r} "
                f"(source: {config_source_label}); no memory entries"
            )
            if explain:
                print(
                    f"[explain] question_id={question_id} → config={config_value!r} at "
                    f"{config_source_label} → result={mapped_result} (hard), no memory",
                    file=sys.stderr,
                )
            envelope = {
                "result": mapped_result,
                "default": skill_default,
                "source": "config",
                "rule_id": config_key,
                "strength": "hard",
                "reason": reason,
                "sources": [],
            }
            return envelope, mapped_result, "config", "hard", 0, config_value, True

    # Case: memory conflict (multiple disagreeing entries)
    if mem_strength == "conflict":
        if config_is_default:
            # Config has no opinion; memory alone is conflicted → ask, show memory sources
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "conflict",
                "rule_id": config_key,
                "strength": "none",
                "reason": "Memory entries disagree on value",
                "sources": mem_sources,
            }
        else:
            # Config has an opinion AND memory is internally conflicted → conflict
            config_source_entry = {
                "kind": "config",
                "value": config_value,
                "location": config_source_label,
                "strength": "hard",
            }
            all_sources = [config_source_entry] + mem_sources
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "conflict",
                "rule_id": config_key,
                "strength": "none",
                "reason": "Config and memory entries disagree on value",
                "sources": all_sources,
            }
        if explain:
            print(
                f"[explain] question_id={question_id} → memory conflict → result=ask",
                file=sys.stderr,
            )
        return envelope, "ask", "conflict", "none", 0, None, False

    # At this point: mem_value is set (single or agreeing multiple memory entries)
    # mem_strength is one of weak | strong | very_strong

    if config_is_default:
        # Config is "ask" (default) AND memory exists → memory wins (no conflict)
        # Derive result from memory strength
        if mem_strength == "very_strong":
            mem_result = "skip"
        else:
            # strong or weak → prefill
            mem_result = "prefill"

        if explain:
            print(
                f"[explain] question_id={question_id} → config=ask (default), "
                f"memory={mem_value!r} ({mem_strength}) → result={mem_result}",
                file=sys.stderr,
            )
        envelope = {
            "result": mem_result,
            "default": skill_default,
            "source": "memory",
            "rule_id": config_key,
            "strength": mem_strength,
            "reason": (
                f"Memory routing-preference: question_id={question_id!r}, "
                f"value={mem_value!r}, strength={mem_strength!r}"
            ),
            "sources": mem_sources,
        }
        return envelope, mem_result, "memory", mem_strength, 0, mem_value, False

    # Config is non-default AND memory exists
    # Check if they agree: translate config value to result-domain then compare mem_value
    # "Agreement" means memory's value == config's value (both are in the option-domain)
    if mem_value == config_value:
        # Config and memory agree → config wins, no conflict
        mapped_result = RESULT_MAP.get((question_id, config_value), "ask")
        if explain:
            print(
                f"[explain] question_id={question_id} → config={config_value!r} and "
                f"memory={mem_value!r} agree → result={mapped_result} (config wins)",
                file=sys.stderr,
            )
        envelope = {
            "result": mapped_result,
            "default": skill_default,
            "source": "config",
            "rule_id": config_key,
            "strength": "hard",
            "reason": (
                f"Config and memory agree: {config_key!r} = {config_value!r} "
                f"(config source: {config_source_label})"
            ),
            "sources": [],
        }
        return envelope, mapped_result, "config", "hard", 0, config_value, False

    # Config is non-default AND memory disagrees → conflict tier
    config_source_entry = {
        "kind": "config",
        "value": config_value,
        "location": config_source_label,
        "strength": "hard",
    }
    all_sources = [config_source_entry] + mem_sources
    if explain:
        print(
            f"[explain] question_id={question_id} → config={config_value!r} "
            f"vs memory={mem_value!r} → conflict → result=ask",
            file=sys.stderr,
        )
    envelope = {
        "result": "ask",
        "default": skill_default,
        "source": "conflict",
        "rule_id": config_key,
        "strength": "none",
        "reason": (
            f"Config says {config_value!r} but memory says {mem_value!r}; "
            "showing both — resolve the conflict"
        ),
        "sources": all_sources,
    }
    return envelope, "ask", "conflict", "none", 0, None, False


def _build_resolve_envelope(
    question_id: str,
    explain: bool = False,
) -> tuple[dict, str, str, str, int]:
    """
    Build the final resolution envelope for a registered ``question_id``,
    applying the axiom layer (lowest behavioral-authority signal) on top of the
    config + routing-pref-memory resolution.

    Returns the historical ``(envelope, emit_result, emit_source, emit_strength,
    exit_code)`` 5-tuple. Existing envelope fields (``result``, ``default``,
    ``source``, ``rule_id``, ``strength``, ``reason``, ``sources``) keep their
    meaning. The axiom layer only ADDS an optional nested ``axiom`` object and
    grows the ``source`` enum by ``"axiom"`` / ``"axiom_conflict"``.

    R10 precedence snapshot: config, memory, and axioms are each read within this
    single invocation; the precedence-correctness claim is scoped to this
    per-invocation snapshot (no cross-invocation atomicity is promised — fine for
    a CLI flow).

    Axiom precedence (SPEC `## scripts/config.py`, R7):
      - agree (axiom value == already-resolved value): config/memory still wins;
        the axiom is recorded in ``sources`` only — no ``source``/``result``
        change, NO nested ``axiom`` object.
      - gap-fill (config at default AND memory silent — nothing higher spoke):
        axiom fills the gap → ``source:"axiom"``, ``strength:"soft"``,
        ``result = RESULT_MAP[(question_id, axiom_value)]``, nested
        ``axiom:{id, statement}`` (no ``conflict`` key).
      - direct conflict (a higher layer set a DIFFERENT value): higher layer wins
        the value/result/strength/rule_id; emit ``source:"axiom_conflict"`` and
        nested ``axiom:{id, statement, conflict: true}``.
      - no axiom match: envelope is BYTE-IDENTICAL to the pre-axiom result — the
        ``axiom`` key is ABSENT entirely (R7 structural backward-compat).
    """
    (
        envelope,
        emit_result,
        emit_source,
        emit_strength,
        exit_code,
        resolved_value,
        memory_silent,
    ) = _resolve_config_memory_envelope(question_id, explain=explain)

    # On I/O error or an internally-conflicted higher layer, axioms do not
    # participate (there is no single winning value to compare against, and we do
    # not let an advisory layer mask a config/memory conflict).
    if exit_code != 0 or emit_source == "conflict":
        return envelope, emit_result, emit_source, emit_strength, exit_code

    project_root = _get_project_root()
    axiom_matches = _load_axiom_matches(question_id, project_root)
    if not axiom_matches:
        # No axiom participated → envelope byte-identical to pre-axiom (R7).
        return envelope, emit_result, emit_source, emit_strength, exit_code

    # Determine whether a higher layer set a value (gap vs. higher-layer-wins).
    # Gap-fill requires BOTH: config at its default AND memory silent. The only
    # pre-axiom branch with no winning value AND memory silent is the pure-gap
    # branch (source == "none"); resolved_value is None there.
    higher_layer_spoke = resolved_value is not None

    # Pick the participating axiom deterministically: prefer one that agrees with
    # the resolved value (so an agreeing axiom is not reported as a conflict);
    # otherwise take the first match (stable order from _load_axiom_matches).
    chosen = None
    if higher_layer_spoke:
        for m in axiom_matches:
            if m["value"] == resolved_value:
                chosen = m
                break
    if chosen is None:
        chosen = axiom_matches[0]

    axiom_value = chosen["value"]
    axiom_id = chosen["id"]
    axiom_statement = chosen["statement"]

    if higher_layer_spoke:
        if axiom_value == resolved_value:
            # AGREE: config/memory wins; record the axiom in `sources` only.
            # No source/result change, NO nested `axiom` object.
            envelope.setdefault("sources", [])
            envelope["sources"] = list(envelope["sources"]) + [{
                "kind": "axiom",
                "value": axiom_value,
                "id": axiom_id,
                "statement": axiom_statement,
            }]
            if explain:
                print(
                    f"[explain] question_id={question_id} → axiom {axiom_id} agrees "
                    f"({axiom_value!r}); {emit_source} wins, axiom listed in sources",
                    file=sys.stderr,
                )
            return envelope, emit_result, emit_source, emit_strength, exit_code

        # DIRECT CONFLICT: higher layer wins the value/result/strength/rule_id,
        # but surface the conflict via source="axiom_conflict" + nested axiom obj.
        envelope["source"] = "axiom_conflict"
        envelope["reason"] = (
            f"axiom {axiom_id} says {axiom_value!r}; {emit_source} says "
            f"{resolved_value!r} — higher layer wins, surfacing conflict"
        )
        envelope["axiom"] = {
            "id": axiom_id,
            "statement": axiom_statement,
            "conflict": True,
        }
        if explain:
            print(
                f"[explain] question_id={question_id} → axiom {axiom_id} "
                f"({axiom_value!r}) conflicts with {emit_source} ({resolved_value!r}); "
                "higher layer wins, surfacing conflict",
                file=sys.stderr,
            )
        # result/strength/rule_id stay the higher layer's; only `source` changes.
        return envelope, emit_result, "axiom_conflict", emit_strength, exit_code

    # GAP-FILL: nothing higher spoke (config default + memory silent) → axiom
    # fills the gap. Map the axiom's option value to the result domain.
    if not memory_silent:
        # Defensive: a no-value branch where memory was NOT silent is the conflict
        # tier already filtered above; nothing should reach here. Leave untouched.
        return envelope, emit_result, emit_source, emit_strength, exit_code

    mapped_result = RESULT_MAP.get((question_id, axiom_value), "ask")
    envelope["result"] = mapped_result
    envelope["source"] = "axiom"
    envelope["strength"] = "soft"
    envelope["reason"] = (
        f"axiom {axiom_id} recommends {axiom_value!r} (no config/memory "
        "preference set) — axiom fills the gap"
    )
    envelope["axiom"] = {
        "id": axiom_id,
        "statement": axiom_statement,
    }
    if explain:
        print(
            f"[explain] question_id={question_id} → axiom {axiom_id} fills gap with "
            f"{axiom_value!r} → result={mapped_result} (soft)",
            file=sys.stderr,
        )
    return envelope, mapped_result, "axiom", "soft", exit_code


def cmd_resolve_question(args: list[str]) -> None:
    """
    resolve-question <question_id> [--scope-slug <slug>] [--explain]

    Returns a JSON envelope to stdout. All diagnostics go to stderr.
    Exit codes:
      0  Success
      2  Bad invocation
      3  Unknown question_id (JSON with error key still emitted)
      4  I/O error (JSON still emitted)
      5  Config conflict (Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt)
    """
    if not args:
        print("usage: config.py resolve-question <question_id> [--scope-slug <slug>] [--explain]",
              file=sys.stderr)
        sys.exit(2)

    # Parse positional + optional args
    question_id: str = ""
    explain: bool = False
    i = 0
    while i < len(args):
        if args[i] == "--explain":
            explain = True
            i += 1
        elif args[i] == "--scope-slug":
            # Consume the slug value (not used by the resolver itself — scope is
            # determined by Z_HARNESS_PROJECT_ROOT / git-toplevel, not slug name)
            i += 2
        elif args[i].startswith("--"):
            print(f"[config] unknown flag {args[i]!r}", file=sys.stderr)
            sys.exit(2)
        elif not question_id:
            question_id = args[i]
            i += 1
        else:
            print(f"[config] unexpected argument {args[i]!r}", file=sys.stderr)
            sys.exit(2)

    if not question_id:
        print("usage: config.py resolve-question <question_id> [--scope-slug <slug>] [--explain]",
              file=sys.stderr)
        sys.exit(2)

    # Check Z_HARNESS_EXPLAIN_RESOLUTION
    if os.environ.get("Z_HARNESS_EXPLAIN_RESOLUTION", "") == "1":
        explain = True

    # Step 1: Validate question_id
    if question_id not in QUESTION_IDS:
        envelope = {
            "error": "unknown_question_id",
            "known": sorted(QUESTION_IDS.keys()),
        }
        print(json.dumps(envelope))
        sys.exit(3)

    # Hermes-managed mode gate: when HERMES_MARKER_FILE is set the session is
    # driven by the hermes watcher.  Interactive prompts (AskUserQuestion) must
    # not block the session.  Instead we emit a needs_input marker (the watcher
    # relays the question to the user over Discord) and return a halt envelope so
    # the orchestrator halts cleanly.  This takes priority over all other
    # resolution paths (ASK_ALL, overnight, memory, etc.).
    if os.environ.get("HERMES_MARKER_FILE", ""):
        qmeta = QUESTION_IDS[question_id]
        _hm_skill_default: str = qmeta["skill_default"]
        _hm_choices: list = sorted(qmeta.get("choices", []))
        _emit_hermes_needs_input(question_id, _hm_choices, _hm_skill_default)
        halt_envelope = {
            "result": "halt",
            "default": _hm_skill_default,
            "source": "hermes_managed",
            "rule_id": "hermes_managed",
            "strength": "policy",
            "reason": (
                "HERMES_MARKER_FILE is set — managed mode: halt instead of "
                "interactive prompt; needs_input marker emitted for watcher relay"
            ),
            "sources": [{"kind": "env", "value": "set", "location": "HERMES_MARKER_FILE"}],
            "halt_reason": "hermes_managed",
            "question_id": question_id,
            "would_have_asked": {
                "default": _hm_skill_default,
                "choices": _hm_choices,
            },
        }
        print(json.dumps(halt_envelope))
        sys.exit(0)

    # Step 2: Honor Z_HARNESS_ASK_ALL=1 short-circuit (but check for conflict first).
    # _apply_overnight_overrides handles the ASK_ALL + NO_ASK=halt conflict case
    # (exits 5), so we build the ASK_ALL envelope and pass it through the override.
    if os.environ.get("Z_HARNESS_ASK_ALL", "") == "1":
        qmeta = QUESTION_IDS[question_id]
        skill_default: str = qmeta["skill_default"]
        envelope = {
            "result": "ask",
            "default": skill_default,
            "source": "override",
            "rule_id": "Z_HARNESS_ASK_ALL",
            "strength": "none",
            "reason": "Z_HARNESS_ASK_ALL=1 forces ask for all questions",
            "sources": [],
        }
        if explain:
            print(
                f"[explain] question_id={question_id} → Z_HARNESS_ASK_ALL=1 override → result=ask",
                file=sys.stderr,
            )
        # Post-process through overnight overrides: detects ASK_ALL+NO_ASK conflict → exit 5
        envelope = _apply_overnight_overrides(envelope, question_id)
        _emit_askuser_resolved(question_id, "ask", "override", "none")
        print(json.dumps(envelope))
        sys.exit(0)

    # Steps 3-11: Build envelope via helper, then apply overnight overrides before
    # emitting telemetry and printing to stdout.
    envelope, emit_result, emit_source, emit_strength, exit_code = _build_resolve_envelope(
        question_id, explain=explain
    )
    # Post-process: halt-from-ask / overnight allowlist (no-op when NO_ASK != halt)
    envelope = _apply_overnight_overrides(envelope, question_id)
    _emit_askuser_resolved(question_id, emit_result, emit_source, emit_strength)
    print(json.dumps(envelope))
    sys.exit(exit_code)


def _is_policy_mode() -> bool:
    """
    Return True when running in benchmark/policy mode.

    Policy mode is active when Z_HARNESS_NO_ASK=halt AND either
    Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE or Z_HARNESS_OVERNIGHT_AUTODECIDE
    is set to a non-empty string (indicating a frozen policy is in use).
    """
    if os.environ.get("Z_HARNESS_NO_ASK", "") != "halt":
        return False
    return bool(
        os.environ.get("Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", "").strip()
        or os.environ.get("Z_HARNESS_OVERNIGHT_AUTODECIDE", "").strip()
    )


def _emit_unhandled_gate(question_id: str) -> None:
    """
    Emit an unhandled_gate event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({
        "question_id": question_id,
        "reason": "reachable gate not resolved by frozen policy",
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "unhandled_gate", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _emit_unknown_ask_blocked(question_id: str, callsite_hint: str = "") -> None:
    """
    Emit an unknown_ask_blocked event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({
        "question_id": question_id,
        "callsite_hint": callsite_hint,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "unknown_ask_blocked", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _resolve_cost_gate(question_id: str, range_high: Optional[int], severity: str) -> dict:
    """
    Core budget-aware resolution for the cost gate (Phase-7 single-authority path).

    Called by cmd_check_no_ask when --range-high / --severity are provided.
    Returns a result dict: {"result": ask|auto_proceed|halt|unhandled_gate, "rule_id": ...}.

    Decision tree (SPEC "New resolution entrypoint"):
      soft severity → auto_proceed always.
      hard, NO_ASK unset → ask.
      hard, NO_ASK=halt → run _apply_overnight_overrides; then:
        overnight allowlist hit (envelope.result != ask) → return that result.
        overnight allowlist MISS (envelope.result == ask still) → apply budget rule:
          range_high missing → halt (rule_id: cost_estimate_missing).
          budget <= 0  → halt (rule_id: cost_budget_invalid).
          budget unset → halt (rule_id: cost_budget_missing).
          range_high <= budget → auto_proceed.
          range_high > budget → halt (rule_id: cost_over_budget).
        registered gate not covered by active policy allowlist → unhandled_gate.
    """
    # soft severity → always auto_proceed, no policy check needed
    if severity == "soft":
        return {"result": "auto_proceed", "rule_id": "soft_gate"}

    # hard severity from here on
    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask != "halt":
        # Interactive mode: no policy active
        if range_high is None:
            # Estimate unavailable → ask rather than silently proceeding
            return {"result": "ask", "rule_id": "cost_estimate_missing"}
        return {"result": "ask", "rule_id": "interactive"}

    # NO_ASK=halt: policy mode — run overnight overrides for the gate qid first.
    # Overnight can yield:
    #   - A non-halt, non-ask result (e.g. skip) when the gate is in the allowlist → resolved.
    #   - halt with rule_id "no_ask_halt" when NOT in the allowlist → fall through to budget rule.
    envelope, _er, _es, _estr, _ec = _build_resolve_envelope(question_id, explain=False)
    envelope = _apply_overnight_overrides(envelope, question_id)
    envelope_result = envelope.get("result", "ask")
    overnight_rule_id = envelope.get("rule_id", "no_ask_halt")

    if envelope_result not in {"ask", "halt"} or (
        envelope_result == "halt" and overnight_rule_id not in {"no_ask_halt", "no_ask_blocked"}
    ):
        # Allowlist positively resolved it (skip/prefill) or explicit halt from overnight policy
        # Map skip/prefill → auto_proceed for the cost-gate result contract
        mapped = "auto_proceed" if envelope_result in {"skip", "prefill"} else envelope_result
        return {"result": mapped, "rule_id": overnight_rule_id}

    # Envelope is ask or halt(no_ask_halt/no_ask_blocked) → apply the budget rule
    # (overnight did not positively resolve the gate)
    if range_high is None:
        # --range-high missing: estimate unavailable → fail-closed under policy
        return {"result": "halt", "rule_id": "cost_estimate_missing"}

    # Read cost.token_budget from resolved config
    try:
        values, _sources = load_config()
    except SystemExit:
        # Config load failure under policy → fail-closed
        return {"result": "halt", "rule_id": "cost_budget_missing"}

    budget = values.get("cost.token_budget")
    if budget is None:
        # Budget not configured → fail-closed under policy
        return {"result": "halt", "rule_id": "cost_budget_missing"}

    # Defense-in-depth: budget <= 0 is invalid config (validator should have caught it)
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        return {"result": "halt", "rule_id": "cost_budget_invalid"}

    if range_high <= budget:
        return {"result": "auto_proceed", "rule_id": "within_budget"}

    # range_high > budget — check whether this is a policy-mode unhandled_gate
    if _is_policy_mode():
        _emit_unhandled_gate(question_id)
        return {
            "result": "unhandled_gate",
            "rule_id": "unhandled_gate",
            "reason": (
                "reachable cost gate not resolved by frozen benchmark policy; "
                "set cost.token_budget above the estimate or add workflow.pre_run_cost_gate "
                "to benchmark-autonomy.yaml"
            ),
        }
    return {"result": "halt", "rule_id": "cost_over_budget"}


def cmd_check_no_ask(args: list[str]) -> None:
    """
    check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]

    Returns JSON: {"result": "halt"|"proceed"|"unhandled_gate"|"ask"|"auto_proceed",
                   "question_id": "<id>", "rule_id": "<rule>"}

    When --range-high and --severity are provided (cost-gate delegation path), applies
    the budget-aware resolution via _resolve_cost_gate instead of the generic overnight
    path. This is the single authority the pre-run-cost-gate.sh helper delegates to.

    Generic paths (no --range-high / --severity):
      1. Z_HARNESS_NO_ASK != halt  → proceed, rule_id=no_overnight_active
      2. NO_ASK=halt, qid registered, in allowlist → proceed (resolved as overnight_decision)
      3. NO_ASK=halt, qid registered, NOT in allowlist, non-policy mode → halt
      3b.NO_ASK=halt, qid registered, NOT in allowlist, policy mode active → unhandled_gate (loud abort)
      4. NO_ASK=halt, qid NOT registered → halt + unknown_ask_blocked event
      5. Bad invocation (missing --question-id) → exit 2

    Policy mode (path 3b) is active when Z_HARNESS_NO_ASK=halt AND either
    Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE or Z_HARNESS_OVERNIGHT_AUTODECIDE is
    set to a non-empty string.  In this mode a reachable gate not covered by the
    frozen policy is a configuration error: it must ABORT LOUD via unhandled_gate
    rather than silently blocking (fail-open) or returning a plain halt.

    Exit 0 on all valid invocations, exit 2 on argparse error.
    """
    question_id: str = ""
    range_high: Optional[int] = None
    severity: Optional[str] = None
    i = 0
    while i < len(args):
        if args[i] == "--question-id":
            if i + 1 >= len(args):
                print("usage: config.py check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]",
                      file=sys.stderr)
                sys.exit(2)
            question_id = args[i + 1]
            i += 2
        elif args[i] == "--range-high":
            if i + 1 >= len(args):
                print("usage: config.py check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]",
                      file=sys.stderr)
                sys.exit(2)
            raw_rh = args[i + 1]
            try:
                range_high = int(raw_rh)
            except ValueError:
                print(f"[config] --range-high must be an integer, got {raw_rh!r}", file=sys.stderr)
                sys.exit(2)
            i += 2
        elif args[i] == "--severity":
            if i + 1 >= len(args):
                print("usage: config.py check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]",
                      file=sys.stderr)
                sys.exit(2)
            severity = args[i + 1]
            if severity not in {"hard", "soft"}:
                print(f"[config] --severity must be hard or soft, got {severity!r}", file=sys.stderr)
                sys.exit(2)
            i += 2
        elif args[i].startswith("--"):
            print(f"[config] unknown flag {args[i]!r}", file=sys.stderr)
            sys.exit(2)
        else:
            print(f"[config] unexpected argument {args[i]!r}", file=sys.stderr)
            sys.exit(2)

    if not question_id:
        print("usage: config.py check-no-ask --question-id <id> [--range-high N] [--severity hard|soft]",
              file=sys.stderr)
        sys.exit(2)

    # Cost-gate delegation path: when severity is provided, use the budget-aware resolver
    if severity is not None:
        cost_result = _resolve_cost_gate(question_id, range_high, severity)
        output = {"question_id": question_id, **cost_result}
        print(json.dumps(output))
        sys.exit(0)

    # Generic check-no-ask path (no severity flag) — original behavior preserved.

    # Path 1: overnight mode not active
    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask != "halt":
        result = {"result": "proceed", "question_id": question_id, "rule_id": "no_overnight_active"}
        print(json.dumps(result))
        sys.exit(0)

    # Path 4: question_id not registered → fail-closed
    if question_id not in QUESTION_IDS:
        _emit_unknown_ask_blocked(question_id)
        result = {"result": "halt", "question_id": question_id, "rule_id": "unknown_ask_blocked"}
        print(json.dumps(result))
        sys.exit(0)

    # Paths 2 & 3: registered question_id — build envelope, apply overnight overrides,
    # then map envelope result to halt/proceed.
    envelope, _emit_result, _emit_source, _emit_strength, _exit_code = _build_resolve_envelope(
        question_id, explain=False
    )
    # Post-process: applies allowlist / halt logic for NO_ASK=halt
    envelope = _apply_overnight_overrides(envelope, question_id)

    envelope_result = envelope.get("result", "ask")
    if envelope_result == "halt":
        rule_id = envelope.get("rule_id", "no_ask_halt")
        # In policy mode a registered gate not covered by the frozen policy is a
        # configuration error — abort loud with unhandled_gate, not a silent halt.
        if _is_policy_mode() and rule_id in {"no_ask_halt", "no_ask_blocked"}:
            _emit_unhandled_gate(question_id)
            result = {
                "result": "unhandled_gate",
                "question_id": question_id,
                "rule_id": "unhandled_gate",
                "reason": (
                    "reachable gate not resolved by frozen benchmark policy; "
                    "add this question_id to benchmark-autonomy.yaml or ensure "
                    "it is unreachable on the quick-build hot path"
                ),
            }
        else:
            result = {"result": "halt", "question_id": question_id, "rule_id": rule_id}
    else:
        rule_id = envelope.get("rule_id", "no_ask_halt")
        result = {"result": "proceed", "question_id": question_id, "rule_id": rule_id}

    print(json.dumps(result))
    sys.exit(0)


def _toml_write_scalar(lines: list, k: str, v: object) -> None:
    """Append a single TOML key = value line to ``lines``."""
    if isinstance(v, str):
        lines.append(f'{k} = "{v}"\n')
    elif isinstance(v, bool):
        lines.append(f'{k} = {"true" if v else "false"}\n')
    else:
        lines.append(f"{k} = {v}\n")


def _toml_write(path: Path, data: dict) -> None:
    """
    Write ``data`` to ``path`` atomically via tmp+rename.

    Supports up to three-level table nesting:
      schema_version = 1

      [section]
      key = "value"

      [section.subsection.role]
      key = "value"

    Only handles str, bool, and int values at leaf level.
    Raises OSError if the write fails (caller handles exit 4).
    """
    lines: list[str] = []
    # Write top-level scalars first (only schema_version in practice)
    for k, v in data.items():
        if not isinstance(v, dict):
            _toml_write_scalar(lines, k, v)

    # Write each section
    for section, sv in data.items():
        if not isinstance(sv, dict):
            continue
        # Check if any values in this section are nested dicts (3-level tables)
        has_nested = any(isinstance(sv2, dict) for sv2 in sv.values())
        if not has_nested:
            lines.append(f"\n[{section}]\n")
            for sk, sv2 in sv.items():
                _toml_write_scalar(lines, sk, sv2)
        else:
            # 3-level: emit [section.subsection.role] headers with leaf pairs
            # (used by [roles.<command>.<role>] tables)
            for sub_key, sub_val in sv.items():
                if isinstance(sub_val, dict):
                    for role_key, role_val in sub_val.items():
                        if isinstance(role_val, dict):
                            lines.append(f"\n[{section}.{sub_key}.{role_key}]\n")
                            for leaf_k, leaf_v in role_val.items():
                                _toml_write_scalar(lines, leaf_k, leaf_v)

    content = "".join(lines)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same directory, then atomically rename
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError:
        # Clean up temp file if rename failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _toml_write_key_preserving(path: Path, section: str, key: str, value) -> None:
    """
    Write a single ``section.key = value`` into ``path`` atomically,
    preserving comments and surrounding TOML structure when tomlkit is
    available.

    Handles dotted sections like ``workflow.audit_to_amend`` by ensuring
    the intermediate table exists before setting the leaf key.

    If ``path`` does not exist: creates it with ``tomlkit.document()`` (or
    falls back to ``_toml_write`` on the minimal dict if tomlkit is absent).

    If ``path`` exists: reads via ``tomlkit.loads`` (or tomllib), mutates
    ``doc[section][key] = value``, serializes via ``tomlkit.dumps``, then
    writes atomically with tmp + ``os.replace``.

    Falls back to the original ``_toml_write`` behaviour when tomlkit is not
    installed (comments will be lost, but all other invariants hold).

    Raises ``OSError`` on I/O failure (caller should handle exit 4).
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    if not _TOMLKIT_AVAILABLE:
        # Graceful degradation: read-modify-write without comment preservation
        existing = _load_toml(path)
        if existing is None:
            data: dict = {"schema_version": 1}
        else:
            data = dict(existing)
        if section not in data or not isinstance(data[section], dict):
            data[section] = {}
        else:
            data[section] = dict(data[section])
        data[section][key] = value
        _toml_write(path, data)
        return

    # --- tomlkit path: preserves comments ---
    if path.exists():
        doc = tomlkit.loads(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
        # Bootstrap schema_version for new files
        doc.add("schema_version", 1)

    # Ensure top-level section table exists (supports dotted sections)
    if section not in doc:
        doc.add(tomlkit.nl())
        doc.add(section, tomlkit.table())
    doc[section][key] = value

    content = tomlkit.dumps(doc)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def cmd_set(args: list[str]) -> None:
    """
    set <key> <value> [--scope=global|project]

    Validates <key> against _KEY_RE and VALIDATORS[<key>], then atomically
    writes the value to the target TOML file via tmp+rename.
    Preserves all other existing keys (read-modify-write).
    Comment preservation requires tomlkit (see _toml_write_key_preserving).
    Exit 0 on success, 2 on validation failure, 4 on I/O error.
    """
    scope = "project"
    positional: list[str] = []

    for arg in args:
        if arg.startswith("--scope="):
            scope = arg[len("--scope="):]
        elif arg.startswith("--"):
            print(f"[config] unknown flag {arg!r}", file=sys.stderr)
            sys.exit(2)
        else:
            positional.append(arg)

    if len(positional) != 2:
        print("usage: config.py set <key> <value> [--scope=global|project]", file=sys.stderr)
        sys.exit(2)

    key, value = positional

    if scope not in {"global", "project"}:
        print(
            f"[config] invalid scope {scope!r}; allowed: global, project",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate key format
    if not _KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate key is known (exists in VALIDATORS)
    if key not in VALIDATORS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate value against VALIDATORS
    allowed = VALIDATORS[key]
    if callable(allowed):
        valid = allowed(value)
    else:
        valid = value in allowed
    if not valid:
        print(
            f"[config] invalid value for {key!r}: {value!r} — allowed: {_describe_allowed(allowed)}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Coerce value to the correct Python type before writing to TOML
    # (e.g. "7000" → 7000 for int keys, "false" → False for bool keys)
    if key in _COERCERS:
        value = _COERCERS[key](value)

    # Resolve target path; writers pass require_exists=False to allow creating new files
    if scope == "global":
        target_path = _global_config_path()
    else:
        target_path = _repo_config_path(require_exists=False)

    # Mutate the target key with comment-preserving atomic write
    section, subkey = key.split(".", 1)
    try:
        _toml_write_key_preserving(target_path, section, subkey, value)
    except OSError as exc:
        print(f"[config] cannot write {target_path}: {exc}", file=sys.stderr)
        sys.exit(4)


# ---------------------------------------------------------------------------
# inspect-all subcommand
# ---------------------------------------------------------------------------

# Env-only knobs: these are read from env only, never written to TOML.
# NOTE: The following migrated vars are NO LONGER in this list because they
# now have DEFAULTS+VALIDATORS entries (they appear in the TOML-Persistent section
# of inspect-all output instead):
#
#   T003a-migrated:
#     Z_HARNESS_NOTIFY (→ notify.level, legacy alias)
#     Z_HARNESS_AUTO_WAIT (→ runtime.auto_wait, legacy alias)
#     Z_HARNESS_AUTO_WAIT_BUDGET_SECS (→ runtime.auto_wait_budget_secs, legacy alias)
#     Z_HARNESS_PAUSE_AT_PCT (→ runtime.pause_at_pct, legacy alias)
#     Z_HARNESS_EXPLAIN_RESOLUTION (→ runtime.explain_resolution, legacy alias)
#     Z_HARNESS_PRE_REVIEW (→ runtime.pre_review, legacy alias)
#     Z_HARNESS_IMPL_PRE_REVIEW (→ runtime.impl_pre_review, legacy alias)
#
#   T003b-migrated:
#     Z_HARNESS_MAX_EXPLORE (→ workflow.max_explore, legacy alias)
#     Z_HARNESS_PARALLEL (→ workflow.parallel, legacy alias)
#     HERMES_MAX_PARALLEL (→ runtime.max_parallel, legacy alias)
#     Z_HARNESS_MAX_PARALLEL_PLANS (→ runtime.max_parallel_plans, legacy alias)
#     Z_HARNESS_DOC_STALENESS_THRESHOLD (→ docs.staleness_threshold, legacy alias)
#     Z_HARNESS_MEMORY_STALE_DAYS (→ workflow.memory_stale_days, legacy alias)
#     Z_HARNESS_MAX_ATTEMPTS (→ runtime.max_attempts, legacy alias)
#     Z_HARNESS_MAX_TASK_WALL_MS (→ runtime.max_task_wall_ms, legacy alias)
#     Z_HARNESS_AXIOM_EXTRACT (→ axioms.auto_extract_post_run, legacy alias)
ENV_ONLY_KNOBS: list[str] = [
    # ── Unattended-entry knobs (never settable via TOML; only meaningful per-run) ──
    "Z_HARNESS_NO_ASK",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
    "Z_HARNESS_ASK_ALL",
    # ── Plumbing: provider/plan discovery (computed per-run, not user preferences) ──
    "Z_HARNESS_REPO_PROVIDERS",
    "Z_HARNESS_PLANS_DIR",
    # ── Active-plan registry knobs (env-only, read inline in active-plan-registry.py) ──
    "Z_HARNESS_BASE_DIR",
    "Z_HARNESS_EXTERNAL_DEFAULT",
    "Z_HARNESS_REGISTRY_ENABLED",
    "Z_HARNESS_REGISTRY_STALE_SECS",
    "Z_HARNESS_STRICT_OVERLAP",
    # ── Wait-for knobs (unattended-entry / plumbing; intentionally left env-only) ──
    "Z_HARNESS_WAIT_POLL_SECS",
    "Z_HARNESS_WAIT_TIMEOUT_SECS",
    "Z_HARNESS_WAIT_REQUIRE_MERGE",
    # ── Per-run signals (set BY orchestrator to signal agents, not user preferences) ──
    "Z_HARNESS_LOCAL_CARGO_CLEAN",
    # ── Error-point subsystem (z-test-error-points plan; read in commands, not config.py) ──
    "Z_HARNESS_ERROR_POINT_MAX_NEW",
    "Z_HARNESS_ERROR_POINT_PRUNE_DAYS",
    "Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ",
]

# Map source label string → persistence_class string
def _source_to_persistence_class(source: str) -> str:
    """
    Map a source label (from load_config) to a persistence_class string.

    persistence_class ∈ {default, global, repo, env, provider_file,
                         persona_file, memory, generated_docs}
    """
    if source == "defaults":
        return "default"
    if source.startswith("env "):
        return "env"
    # Global config path contains the XDG/home config dir
    global_path = str(_global_config_path())
    if global_path and source == global_path:
        return "global"
    # Repo config: any other file path (Z_HARNESS_REPO_CONFIG or git-toplevel)
    if source.startswith("/") or source.startswith("~"):
        return "repo"
    return "default"


def cmd_inspect_all(args: list[str]) -> None:
    """
    inspect-all [--json]

    Returns a structured view of all configuration knobs:
    - Every key in DEFAULTS (TOML-persistent)
    - Every registered question_id in QUESTION_IDS
    - Every env-only knob in ENV_ONLY_KNOBS

    Default output: human-readable concern-grouped table.
    --json: machine-parseable JSON object.

    Exit 0 on success.
    """
    emit_json = "--json" in args

    # --- Section 1: TOML-persistent keys (from DEFAULTS) ---
    values, sources = load_config()
    toml_keys: dict[str, dict] = {}
    flat_defaults = _flatten_defaults()
    global_path_str = str(_global_config_path())

    for dotted_key in sorted(flat_defaults.keys()):
        value = values.get(dotted_key)
        source = sources.get(dotted_key, "defaults")
        persistence_class = _source_to_persistence_class(source)

        # Build sources[] list showing all layers that have a value for this key
        sources_list = []
        # Always include the winning source
        sources_list.append({"layer": source, "value": value})

        # Map source label to simplified form for the "source" field
        if source == "defaults":
            source_label = "default"
        elif source == global_path_str:
            source_label = "global"
        elif source.startswith("env "):
            source_label = "env"
        else:
            source_label = "repo"

        toml_keys[dotted_key] = {
            "value": value,
            "source": source_label,
            "sources": sources_list,
            "strength": "hard" if source_label not in {"default", "none"} else "none",
            "persistence_class": persistence_class,
        }

    # --- Section 2: Registered question_ids (virtual config keys) ---
    qid_keys: dict[str, dict] = {}
    for qid in sorted(QUESTION_IDS.keys()):
        try:
            envelope, emit_result, emit_source, emit_strength, _exit_code = _build_resolve_envelope(
                qid, explain=False
            )
        except SystemExit:
            # Config load error — skip this qid gracefully
            continue

        result_source = envelope.get("source", "none")
        mem_sources = envelope.get("sources", [])

        # Map envelope source → persistence_class
        if result_source == "memory":
            persistence_class = "memory"
        elif result_source == "config":
            # Determine whether it came from global or repo
            config_source = sources.get(QUESTION_IDS[qid]["config_key"], "defaults")
            persistence_class = _source_to_persistence_class(config_source)
        elif result_source in ("none", "conflict", "override"):
            persistence_class = "default"
        else:
            persistence_class = "default"

        qid_keys[qid] = {
            "value": envelope.get("result"),
            "source": result_source,
            "sources": mem_sources,
            "strength": envelope.get("strength", "none"),
            "persistence_class": persistence_class,
            # Include full envelope fields for tooling consumers
            "envelope": envelope,
        }

    # --- Section 3: Env-only knobs ---
    env_keys: dict[str, dict] = {}
    for knob in ENV_ONLY_KNOBS:
        env_val = os.environ.get(knob)
        source = "env" if env_val is not None else "none"
        env_keys[knob] = {
            "value": env_val,
            "source": source,
            "sources": [{"layer": source, "value": env_val}] if env_val is not None else [],
            "strength": "hard" if source == "env" else "none",
            "persistence_class": "env",
        }

    if emit_json:
        output: dict = {
            "toml_keys": toml_keys,
            "question_ids": qid_keys,
            "env_only_knobs": env_keys,
        }
        print(json.dumps(output, indent=2))
        sys.exit(0)

    # Human-readable concern-grouped table
    def _fmt_val(v) -> str:
        if v is None:
            return "(not set)"
        return repr(v) if not isinstance(v, str) else v

    print("=== TOML-Persistent Keys ===")
    print(f"  {'Key':<40} {'Value':<25} {'Source':<12} {'Persistence'}")
    print(f"  {'-'*40} {'-'*25} {'-'*12} {'-'*15}")
    for key, meta in toml_keys.items():
        print(
            f"  {key:<40} {_fmt_val(meta['value']):<25} "
            f"{meta['source']:<12} {meta['persistence_class']}"
        )

    print()
    print("=== Question IDs (Routing Preferences) ===")
    print(f"  {'question_id':<40} {'result':<12} {'source':<12} {'strength':<12} {'persistence'}")
    print(f"  {'-'*40} {'-'*12} {'-'*12} {'-'*12} {'-'*15}")
    for qid, meta in qid_keys.items():
        print(
            f"  {qid:<40} {_fmt_val(meta['value']):<12} "
            f"{meta['source']:<12} {meta['strength']:<12} {meta['persistence_class']}"
        )

    print()
    print("=== Env-Only Knobs ===")
    print(f"  {'Knob':<45} {'Value':<25} {'Source'}")
    print(f"  {'-'*45} {'-'*25} {'-'*8}")
    for knob, meta in env_keys.items():
        print(
            f"  {knob:<45} {_fmt_val(meta['value']):<25} {meta['source']}"
        )

    sys.exit(0)


def cmd_should_notify(args: list[str]) -> None:
    # Parse --event <kind> [--channel push|discord]
    event = None
    channel = "push"
    i = 0
    while i < len(args):
        if args[i] == "--event" and i + 1 < len(args):
            event = args[i + 1]
            i += 2
        elif args[i] == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            if channel not in ("push", "discord"):
                print(f"[config] unknown channel {channel!r}; allowed: push, discord", file=sys.stderr)
                sys.exit(2)
            i += 2
        else:
            print("usage: config.py should-notify --event <kind> [--channel push|discord]", file=sys.stderr)
            sys.exit(2)

    if event is None:
        print("usage: config.py should-notify --event <kind> [--channel push|discord]", file=sys.stderr)
        sys.exit(2)

    if event not in _NOTIFY_EVENTS:
        print(
            f"[config] unknown event kind {event!r}; "
            f"allowed: {sorted(_NOTIFY_EVENTS)}",
            file=sys.stderr,
        )
        sys.exit(2)

    values, _ = load_config()
    level = values.get("notify.level", DEFAULTS["notify"]["level"])

    if level == "off":
        print("no")
        return

    if channel == "discord":
        webhook_url = values.get("notify.discord_webhook_url", "")
        if not webhook_url:
            print("no")
            return

    if level == "approval_only":
        # watchdog_stall and watchdog_timeout are included here so that the default
        # notify.level fires for watchdog alerts without requiring "all".
        if event in {"approval", "error", "watchdog_stall", "watchdog_timeout"}:
            print("yes")
        else:
            print("no")
    elif level == "all":
        print("yes")
    else:
        print("no")


# ---------------------------------------------------------------------------
# Migrate subcommand
# ---------------------------------------------------------------------------

_PROVIDER_RENAME: dict[str, str] = {
    "codex": "codex-cli",
    "gemini": "gemini-cli",
    "claude": "claude-cli",
}


def _migrate_roles_data(data: dict) -> tuple[dict, int]:
    """
    Walk ``data["roles"]`` and rewrite old provider names in ``runtime`` fields.

    Returns ``(mutated_data, rewrite_count)`` where ``rewrite_count`` is the
    number of values that were actually changed.  The input dict is mutated
    in-place and also returned.
    """
    count = 0
    roles = data.get("roles")
    if not isinstance(roles, dict):
        return data, 0
    for _cmd, cmd_val in roles.items():
        if not isinstance(cmd_val, dict):
            continue
        for _role, role_val in cmd_val.items():
            if not isinstance(role_val, dict):
                continue
            old = role_val.get("runtime")
            if isinstance(old, str) and old in _PROVIDER_RENAME:
                role_val["runtime"] = _PROVIDER_RENAME[old]
                count += 1
    return data, count


def cmd_migrate(_args: list[str]) -> None:
    """
    migrate

    Rewrites old provider names (codex, gemini, claude) in any
    ``roles.*.runtime`` config value to the new ``-cli`` form.  Applied to
    both the global (~/.config/z-harness/config.toml) and project
    (.z-harness/config.toml) layers.  Layers that do not exist are skipped.

    Atomic via temp-file rename.  Idempotent — running twice is a no-op.
    Exit 0 always unless an I/O error occurs (exit 4).
    """
    layers: list[tuple[str, Path]] = [
        ("global", _global_config_path()),
        ("project", _repo_config_path(require_exists=False)),
    ]

    for label, path in layers:
        if not path.exists():
            continue
        data = _load_toml(path)
        if data is None:
            continue
        data, count = _migrate_roles_data(data)
        if count == 0:
            continue
        try:
            _toml_write(path, data)
        except OSError as exc:
            print(
                f"[config] migrate: cannot write {path}: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)
        print(f"[config] migrate: {label} — rewrote {count} runtime value(s) in {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: config.py <get|get-batch|export-env|ensure-defaults|explain|should-notify"
            "|list-question-ids|resolve-halt-category|resolve-question|check-no-ask|set|migrate|inspect-all> [args...]",
            file=sys.stderr,
        )
        sys.exit(2)

    subcommand = sys.argv[1]
    args = sys.argv[2:]

    if subcommand == "get":
        cmd_get(args)
    elif subcommand == "get-batch":
        cmd_get_batch(args)
    elif subcommand == "export-env":
        cmd_export_env(args)
    elif subcommand == "ensure-defaults":
        cmd_ensure_defaults(args)
    elif subcommand == "explain":
        cmd_explain(args)
    elif subcommand == "should-notify":
        cmd_should_notify(args)
    elif subcommand == "list-question-ids":
        cmd_list_question_ids(args)
    elif subcommand == "resolve-halt-category":
        cmd_resolve_halt_category(args)
    elif subcommand == "resolve-question":
        cmd_resolve_question(args)
    elif subcommand == "check-no-ask":
        cmd_check_no_ask(args)
    elif subcommand == "set":
        cmd_set(args)
    elif subcommand == "migrate":
        cmd_migrate(args)
    elif subcommand == "inspect-all":
        cmd_inspect_all(args)
    else:
        print(
            f"[config] unknown subcommand {subcommand!r}; "
            "valid: get, get-batch, export-env, ensure-defaults, explain, should-notify, "
            "list-question-ids, resolve-halt-category, resolve-question, check-no-ask, set, migrate, inspect-all",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
