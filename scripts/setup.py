#!/usr/bin/env python3
"""setup.py — z-harness configuration cockpit CLI.

Subcommands: inspect, wizard, apply, explain, status.
Each subcommand stub will be filled by subsequent tasks (T004–T013).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log_run_start(subcommand: str, args: list[str]) -> None:
    """Emit a setup_run_start event via scripts/log-event.sh."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_event_sh = os.path.join(script_dir, "log-event.sh")
    if not os.path.isfile(log_event_sh):
        return
    payload = json.dumps({"subcommand": subcommand, "args": args})
    run_id = os.environ.get("Z_HARNESS_RUN_ID", "setup")
    try:
        subprocess.run(
            ["bash", log_event_sh, run_id, "setup_run_start", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Subcommand handlers (stubs)
# ---------------------------------------------------------------------------

def _inspect_all_json() -> dict | None:
    """
    Call `config.py inspect-all --json` and return the parsed dict.
    Returns None on failure (caller handles gracefully).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_py = os.path.join(script_dir, "config.py")
    try:
        result = subprocess.run(
            [sys.executable, config_py, "inspect-all", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _find_providers_json() -> tuple[dict | None, str]:
    """
    Locate providers.json from global or repo locations.
    Returns (data, source_path) or (None, "") if not found.

    Search order:
      1. Z_HARNESS_REPO_PROVIDERS env var (repo-level override)
      2. Repo-level .z-harness/providers.json (git toplevel)
      3. Global ~/.config/z-harness/providers.json
    """
    candidates: list[str] = []

    repo_env = os.environ.get("Z_HARNESS_REPO_PROVIDERS", "")
    if repo_env:
        candidates.append(repo_env)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        git_root = result.stdout.strip()
        candidates.append(os.path.join(git_root, ".z-harness", "providers.json"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    candidates.append(os.path.join(xdg, "z-harness", "providers.json"))

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path) as fh:
                    return json.load(fh), path
            except (OSError, json.JSONDecodeError):
                return None, path

    return None, ""


def _find_index_json() -> tuple[dict | None, str]:
    """
    Locate docs/llm/INDEX.json relative to the harness repo root.
    Returns (data, path) or (None, "") if absent.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    harness_root = os.path.dirname(script_dir)
    index_path = os.path.join(harness_root, "docs", "llm", "INDEX.json")
    if not os.path.isfile(index_path):
        return None, index_path
    try:
        with open(index_path) as fh:
            return json.load(fh), index_path
    except (OSError, json.JSONDecodeError):
        return None, index_path


def _count_routing_preferences() -> int:
    """Count routing-preference memory entries across all docs/llm/*.json files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    harness_root = os.path.dirname(script_dir)
    docs_dir = os.path.join(harness_root, "docs", "llm")
    if not os.path.isdir(docs_dir):
        return 0
    count = 0
    try:
        for fname in os.listdir(docs_dir):
            if fname == "INDEX.json" or not fname.endswith(".json"):
                continue
            fpath = os.path.join(docs_dir, fname)
            try:
                with open(fpath) as fh:
                    data = json.load(fh)
                memories = data.get("memories", [])
                if isinstance(memories, list):
                    for m in memories:
                        if isinstance(m, dict) and m.get("type") == "routing-preference":
                            count += 1
            except (OSError, json.JSONDecodeError):
                pass
    except OSError:
        pass
    return count


def _fmt_source(source: str) -> str:
    """Format a source label for display."""
    if source in ("default", "defaults"):
        return "default"
    if source == "env":
        return "env"
    if source == "global":
        return "global"
    if source == "repo":
        return "repo"
    if source == "memory":
        return "memory"
    if source == "none":
        return "default"
    return source


def _fmt_source_bracket(source: str, sources_list: list | None = None) -> str:
    """
    Build a bracketed source label for git-config-style flat output.

    Examples:
      default                → [default]
      global                 → [global ~/.config/z-harness/config.toml]
      repo                   → [repo .z-harness/config.toml]
      env                    → [env (not persistent)]
      none                   → [default]
    """
    if source in ("default", "defaults", "none"):
        return "[default]"
    if source == "env":
        return "[env (not persistent)]"
    if source == "memory":
        return "[memory]"

    # For global/repo we try to pull the actual file path from sources_list
    if sources_list:
        for entry in sources_list:
            layer = entry.get("layer", "")
            if layer and layer not in ("defaults", "env"):
                # layer is the raw file path
                xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
                global_prefix = str(Path(xdg) / "z-harness")
                if layer.startswith(global_prefix):
                    # Shorten to ~/.config/z-harness/...
                    rel = layer[len(str(Path(xdg))):]
                    return f"[global ~{rel}]"
                elif layer.startswith("/"):
                    # repo path — try to get relative form
                    try:
                        result = subprocess.run(
                            ["git", "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, check=True,
                        )
                        git_root = result.stdout.strip()
                        if layer.startswith(git_root):
                            rel = layer[len(git_root):]
                            return f"[repo {rel.lstrip('/')}]"
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass
                    return f"[repo {layer}]"

    if source == "global":
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return f"[global ~/.config/z-harness/config.toml]"
    if source == "repo":
        return "[repo .z-harness/config.toml]"

    return f"[{source}]"


# ---------------------------------------------------------------------------
# Posture preset constants
# ---------------------------------------------------------------------------

POSTURE_PRESETS: dict[str, dict] = {
    "interactive": {
        "toml": {
            "notify.level": "approval_only",
            "docs.always_apply": "always",
            "workflow.audit_to_amend": "ask",
            "workflow.slug_confirm": "ask",
            "workflow.implement_all_proceed": "ask",
            "workflow.review_all_proceed": "ask",
            "workflow.plan_decisions_approval": "ask",
        },
        "env": {},
    },
    "overnight": {
        "toml": {
            "notify.level": "approval_only",
            "workflow.implement_all_proceed": "halt",
            "workflow.review_all_proceed": "halt",
            "workflow.plan_decisions_approval": "halt",
        },
        "env": {
            "Z_HARNESS_NO_ASK": "halt",
            "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": '{"workflow.slug_confirm":"recommend_derived","workflow.audit_to_amend":"amend"}',
        },
    },
    "ci-batch": {
        "toml": {
            "notify.level": "off",
            "workflow.audit_to_amend": "amend",
            "workflow.slug_confirm": "recommend_derived",
            "workflow.implement_all_proceed": "auto_resume",
        },
        "env": {
            "Z_HARNESS_NO_ASK": "halt",
            "Z_HARNESS_PAUSE_AT_PCT": "85",
        },
    },
}


def _compute_posture_diff(posture_name: str, current_state: dict) -> dict:
    """
    Compute what applying a posture preset would change vs the current resolved state.

    Parameters
    ----------
    posture_name : str
        One of the keys in POSTURE_PRESETS ("interactive", "overnight", "ci-batch").
    current_state : dict
        Flat mapping of key → resolved value, as returned by the inspect-all-style
        dict (toml key names as keys, env-var names as keys for env knobs).

    Returns
    -------
    dict with three keys:
      "will_change"  — {key: (old_value, new_value), ...}  keys whose value differs
      "unchanged"    — {key: current_value, ...}  preset keys already at target
      "env_to_emit"  — {env_var: value, ...}  env vars the preset wants set
    """
    preset = POSTURE_PRESETS[posture_name]
    will_change: dict[str, tuple] = {}
    unchanged: dict[str, object] = {}

    for key, target_value in preset["toml"].items():
        current_value = current_state.get(key)
        if current_value == target_value:
            unchanged[key] = current_value
        else:
            will_change[key] = (current_value, target_value)

    return {
        "will_change": will_change,
        "unchanged": unchanged,
        "env_to_emit": dict(preset["env"]),
    }


def _render_diff(diff: dict) -> str:
    """
    Render a human-readable string describing a posture diff.

    Parameters
    ----------
    diff : dict
        As returned by _compute_posture_diff.

    Returns
    -------
    str
        Multi-line display string.  Empty sections are omitted.
    """
    lines: list[str] = []

    will_change: dict = diff.get("will_change", {})
    unchanged: dict = diff.get("unchanged", {})
    env_to_emit: dict = diff.get("env_to_emit", {})

    if will_change:
        lines.append("Changes:")
        for key in sorted(will_change):
            old_val, new_val = will_change[key]
            old_display = repr(old_val) if old_val is not None else "(not set)"
            lines.append(f"  {key}: {old_display} -> {new_val!r}")

    if unchanged:
        lines.append("Already at target (no change needed):")
        for key in sorted(unchanged):
            lines.append(f"  {key} = {unchanged[key]!r}")

    if env_to_emit:
        lines.append("Env vars to set (not persistent — add to your shell profile):")
        for var in sorted(env_to_emit):
            lines.append(f"  export {var}={env_to_emit[var]!r}")

    if not lines:
        lines.append("(no changes)")

    return "\n".join(lines)


# Scope → section name mapping (lowercase for matching)
_SCOPE_SECTIONS = {
    "notifications": "Notifications",
    "workflow": "Workflow",
    "overnight": "Overnight",
    "providers": "Providers",
    "docs": "Docs",
    "memories": "Memories",
    "axioms": "Axioms",
}

# Which toml_keys prefixes belong to each scope
_SCOPE_TOML_PREFIXES: dict[str, list[str]] = {
    "notifications": ["notify."],
    "workflow": ["workflow."],
    "overnight": [],  # overnight keys are env-only
    "providers": [],
    "docs": ["docs."],
    "memories": [],
    "axioms": ["axioms."],
}

# Which env_only_knobs belong to each scope
_SCOPE_ENV_KNOBS: dict[str, list[str]] = {
    "notifications": ["Z_HARNESS_NOTIFY"],
    "workflow": [],
    "overnight": [
        "Z_HARNESS_NO_ASK",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE",
        "Z_HARNESS_PAUSE_AT_PCT",
    ],
    "providers": ["Z_HARNESS_REPO_PROVIDERS"],
    "docs": [],
    "memories": [],
    "axioms": [
        "Z_HARNESS_AXIOMS_ENABLED",
        "Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS",
        "Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE",
        "Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN",
    ],
}


def _print_section_header(title: str) -> None:
    print(f"\n=== {title} ===")


def cmd_inspect(args: argparse.Namespace) -> int:
    """
    Emit a concern-grouped inspect view of all z-harness configuration.
    Calls `config.py inspect-all --json`, then augments with providers.json
    and INDEX.json.
    Always exits 0.
    """
    if args.as_json:
        return _cmd_inspect_json(args)

    if args.flat:
        return _cmd_inspect_flat(args)

    return _cmd_inspect_grouped(args)


def _cmd_inspect_json(args: argparse.Namespace) -> int:
    """
    JSON mode: emit a flat {key: {value, source, persistence_class, strength}} object.
    With --scope, only keys belonging to that section are returned.
    """
    data = _inspect_all_json()
    if data is None:
        data = {"toml_keys": {}, "question_ids": {}, "env_only_knobs": {}}

    scope = getattr(args, "scope", None)

    output: dict[str, dict] = {}

    # TOML-persistent keys
    for key, meta in (data.get("toml_keys") or {}).items():
        if scope is not None:
            prefixes = _SCOPE_TOML_PREFIXES.get(scope.lower(), [])
            if not any(key.startswith(p) for p in prefixes):
                continue
        output[key] = {
            "value": meta.get("value"),
            "source": meta.get("source", "default"),
            "persistence_class": meta.get("persistence_class", "default"),
            "strength": meta.get("strength", "none"),
        }

    # Env-only knobs
    for knob, meta in (data.get("env_only_knobs") or {}).items():
        if scope is not None:
            allowed = _SCOPE_ENV_KNOBS.get(scope.lower(), [])
            if knob not in allowed:
                continue
        output[knob] = {
            "value": meta.get("value"),
            "source": meta.get("source", "none"),
            "persistence_class": meta.get("persistence_class", "env"),
            "strength": meta.get("strength", "none"),
        }

    # When no scope filter (or non-key scopes), also include providers/docs/memories
    if scope is None:
        providers_data, providers_path = _find_providers_json()
        index_data, index_path = _find_index_json()
        mem_count = _count_routing_preferences()

        output["__providers__"] = {
            "value": providers_data,
            "source": providers_path if providers_path else "none",
            "persistence_class": "provider_file",
            "strength": "hard" if providers_data is not None else "none",
        }
        output["__docs__"] = {
            "value": {
                "present": index_data is not None,
                "concept_count": len(index_data.get("concepts", [])) if index_data else 0,
                "index_path": index_path,
            },
            "source": index_path if index_data is not None else "none",
            "persistence_class": "generated_docs",
            "strength": "hard" if index_data is not None else "none",
        }
        output["__memories__"] = {
            "value": {"routing_preference_count": mem_count},
            "source": "docs/llm/*.json",
            "persistence_class": "memory",
            "strength": "hard" if mem_count > 0 else "none",
        }
    elif scope.lower() == "providers":
        providers_data, providers_path = _find_providers_json()
        output["__providers__"] = {
            "value": providers_data,
            "source": providers_path if providers_path else "none",
            "persistence_class": "provider_file",
            "strength": "hard" if providers_data is not None else "none",
        }
    elif scope.lower() == "docs":
        index_data, index_path = _find_index_json()
        output["__docs__"] = {
            "value": {
                "present": index_data is not None,
                "concept_count": len(index_data.get("concepts", [])) if index_data else 0,
                "index_path": index_path,
            },
            "source": index_path if index_data is not None else "none",
            "persistence_class": "generated_docs",
            "strength": "hard" if index_data is not None else "none",
        }
    elif scope.lower() == "memories":
        mem_count = _count_routing_preferences()
        output["__memories__"] = {
            "value": {"routing_preference_count": mem_count},
            "source": "docs/llm/*.json",
            "persistence_class": "memory",
            "strength": "hard" if mem_count > 0 else "none",
        }

    print(json.dumps(output, indent=2))
    return 0


def _cmd_inspect_flat(args: argparse.Namespace) -> int:
    """Flat alphabetical key=value with bracketed source column (git-config-style)."""
    data = _inspect_all_json()
    if data is None:
        print("[setup] Warning: could not retrieve config data.", file=sys.stderr)
        data = {"toml_keys": {}, "question_ids": {}, "env_only_knobs": {}}

    scope = getattr(args, "scope", None)

    # Each row: (key, value_str, bracket_source_label)
    rows: list[tuple[str, str, str]] = []

    for key, meta in (data.get("toml_keys") or {}).items():
        if scope is not None:
            prefixes = _SCOPE_TOML_PREFIXES.get(scope.lower(), [])
            if not any(key.startswith(p) for p in prefixes):
                continue
        val = meta.get("value")
        src_label = _fmt_source_bracket(
            meta.get("source", "default"),
            meta.get("sources"),
        )
        rows.append((key, str(val) if val is not None else "(not set)", src_label))

    for knob, meta in (data.get("env_only_knobs") or {}).items():
        if scope is not None:
            allowed = _SCOPE_ENV_KNOBS.get(scope.lower(), [])
            if knob not in allowed:
                continue
        val = meta.get("value")
        src_label = "[env (not persistent)]" if val is not None else "[default]"
        rows.append((knob, str(val) if val is not None else "(not set)", src_label))

    # Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE is not in ENV_ONLY_KNOBS but is
    # surfaced in the Overnight section; add it when showing overnight scope or all.
    if scope is None or scope.lower() == "overnight":
        effective_knob = "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE"
        if not any(k == effective_knob for k, _, _ in rows):
            eff_val = os.environ.get(effective_knob)
            src_label = "[env (not persistent)]" if eff_val is not None else "[default]"
            rows.append((effective_knob, str(eff_val) if eff_val is not None else "(not set)", src_label))

    rows.sort(key=lambda r: r[0])

    if not rows:
        return 0

    # Compute column widths for git-config-style alignment:
    # key=value   [source]
    # key and value are joined without spaces around =
    # The [source] bracket is right-padded so it starts at a fixed column.
    max_kv_len = max(len(f"{k}={v}") for k, v, _ in rows)
    pad_to = max_kv_len + 2  # at least 2 spaces before bracket

    for key, val, src_label in rows:
        kv = f"{key}={val}"
        padding = " " * (pad_to - len(kv))
        print(f"{kv}{padding}{src_label}")

    return 0


def _cmd_inspect_grouped(args: argparse.Namespace) -> int:
    """Emit concern-grouped sections, optionally filtered to --scope <section>."""
    data = _inspect_all_json()
    if data is None:
        print("[setup] Warning: could not retrieve config data.", file=sys.stderr)
        data = {"toml_keys": {}, "question_ids": {}, "env_only_knobs": {}}

    toml_keys = data.get("toml_keys") or {}
    env_knobs = data.get("env_only_knobs") or {}

    scope = getattr(args, "scope", None)
    scope_lower = scope.lower() if scope else None

    def _show_section(name: str) -> bool:
        """Return True if this section should be shown given the scope filter."""
        if scope_lower is None:
            return True
        return scope_lower == name.lower()

    # Load auxiliary data only when needed
    providers_data = providers_path = None
    index_data = index_path = None
    mem_count = 0

    need_providers = _show_section("providers")
    need_docs = _show_section("docs")
    need_memories = _show_section("memories")

    if need_providers:
        providers_data, providers_path = _find_providers_json()
    if need_docs:
        index_data, index_path = _find_index_json()
    if need_memories:
        mem_count = _count_routing_preferences()

    # -------------------------------------------------------------------------
    # Section 1: Notifications
    # -------------------------------------------------------------------------
    if _show_section("notifications"):
        _print_section_header("Notifications")

        notify_level_meta = toml_keys.get("notify.level", {})
        notify_level = notify_level_meta.get("value", "approval_only")
        notify_level_src = _fmt_source(notify_level_meta.get("source", "default"))

        z_harness_notify_meta = env_knobs.get("Z_HARNESS_NOTIFY", {})
        z_harness_notify = z_harness_notify_meta.get("value")

        print(f"  notify.level = {notify_level}  (from {notify_level_src})")
        if z_harness_notify is not None:
            print(f"  Z_HARNESS_NOTIFY = {z_harness_notify}  (from env; not persistent)")
        else:
            print("  Z_HARNESS_NOTIFY = (not set)  (from env; not persistent)")

    # -------------------------------------------------------------------------
    # Section 2: Workflow
    # -------------------------------------------------------------------------
    if _show_section("workflow"):
        _print_section_header("Workflow")

        workflow_keys = [
            "workflow.audit_to_amend",
            "workflow.slug_confirm",
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.plan_decisions_approval",
        ]
        for wk in workflow_keys:
            meta = toml_keys.get(wk, {})
            val = meta.get("value", "(not set)")
            src = _fmt_source(meta.get("source", "default"))
            print(f"  {wk} = {val}  (from {src})")

    # -------------------------------------------------------------------------
    # Section 3: Overnight
    # -------------------------------------------------------------------------
    if _show_section("overnight"):
        _print_section_header("Overnight")

        overnight_knobs = [
            "Z_HARNESS_NO_ASK",
            "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
            "Z_HARNESS_OVERNIGHT_AUTODECIDE",
            "Z_HARNESS_PAUSE_AT_PCT",
        ]
        # Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE may not be in env_knobs (it's not
        # in the ENV_ONLY_KNOBS list in config.py); read directly from os.environ.
        for knob in overnight_knobs:
            if knob in env_knobs:
                val = env_knobs[knob].get("value")
            else:
                val = os.environ.get(knob)
            display_val = val if val is not None else "(not set)"
            print(f"  {knob} = {display_val}  (from env; not persistent)")

    # -------------------------------------------------------------------------
    # Section 4: Providers
    # -------------------------------------------------------------------------
    if need_providers:
        _print_section_header("Providers")

        provider_roles = ["consultant_primary", "consultant_secondary", "reviewer"]
        if providers_data is not None and providers_path:
            src_label = providers_path
            roles = providers_data.get("roles", {})
            for role in provider_roles:
                if role in roles:
                    print(f"  {role} = {roles[role]}  (from {src_label})")
                else:
                    print(f"  {role} = (not bound)  (from {src_label})")
        else:
            for role in provider_roles:
                print(f"  {role} = (not bound)  (absent — run `python3 scripts/discover-providers.py` or the /z-setup wizard's provider-discovery step)")

    # -------------------------------------------------------------------------
    # Section 6: Docs
    # -------------------------------------------------------------------------
    if need_docs:
        _print_section_header("Docs")

        if index_data is not None:
            concepts = index_data.get("concepts", [])
            concept_count = len(concepts)
            print(f"  INDEX.json = present  ({concept_count} concepts)  (from {index_path})")
        else:
            print(f"  INDEX.json = (absent)  (from {index_path})")
            print("  Run /z-init-docs to bootstrap docs/llm/INDEX.json")

    # -------------------------------------------------------------------------
    # Section 7: Memories
    # -------------------------------------------------------------------------
    if need_memories:
        _print_section_header("Memories")

        if mem_count > 0:
            print(f"  routing-preference entries = {mem_count}  (from docs/llm/*.json)")
        else:
            print("  routing-preference entries = 0  (from docs/llm/*.json)")
        print("  (edit via /z-suggest-memory)")

    print()
    return 0


# ---------------------------------------------------------------------------
# Wizard section skeleton functions
# Bodies filled in by T009-T013.
# Each returns a pending-changes dict: {"toml": {key: value, ...}, "env": {var: value, ...}}
# ---------------------------------------------------------------------------

def _wizard_notifications(inspect_data: dict) -> dict:
    """Wizard section: Notifications — show current notify.level and prompt to change."""
    _print_section_header("Notifications")
    toml_keys = inspect_data.get("toml_keys") or {}
    env_knobs = inspect_data.get("env_only_knobs") or {}

    notify_level_meta = toml_keys.get("notify.level", {})
    notify_level = notify_level_meta.get("value", "approval_only")
    notify_level_src = _fmt_source(notify_level_meta.get("source", "default"))
    print(f"  notify.level = {notify_level}  (from {notify_level_src})")

    z_harness_notify_meta = env_knobs.get("Z_HARNESS_NOTIFY", {})
    z_harness_notify = z_harness_notify_meta.get("value")
    if z_harness_notify is not None:
        print(f"  Z_HARNESS_NOTIFY = {z_harness_notify}  (from env; not persistent)")
    else:
        print("  Z_HARNESS_NOTIFY = (not set)  (from env; not persistent)")

    pending: dict = {"toml": {}, "env": {}}

    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask == "halt":
        return pending

    notify_choices = ["off", "approval_only", "all"]
    choice_display = ", ".join(notify_choices)
    print(f"  Set notify.level? [{choice_display}, keep] (current: {notify_level})")
    try:
        answer = input("  > ").strip().lower()
    except EOFError:
        answer = ""

    if answer in notify_choices and answer != notify_level:
        pending["toml"]["notify.level"] = answer

    return pending


def _wizard_workflow(inspect_data: dict) -> dict:
    """Wizard section: Workflow — show resolved values and prompt to change each key."""
    _print_section_header("Workflow")
    toml_keys = inspect_data.get("toml_keys") or {}

    # Choices per question_id — from config.py QUESTION_IDS (authoritative)
    _WORKFLOW_CHOICES: dict[str, list[str]] = {
        "workflow.audit_to_amend":        ["ask", "amend", "stop"],
        "workflow.slug_confirm":           ["ask", "auto_accept", "recommend_derived"],
        "workflow.implement_all_proceed":  ["ask", "auto_resume", "halt"],
        "workflow.review_all_proceed":     ["ask", "proceed", "halt"],
        "workflow.plan_decisions_approval": ["ask", "approve", "halt"],
    }

    workflow_keys = [
        "workflow.audit_to_amend",
        "workflow.slug_confirm",
        "workflow.implement_all_proceed",
        "workflow.review_all_proceed",
        "workflow.plan_decisions_approval",
    ]

    for wk in workflow_keys:
        meta = toml_keys.get(wk, {})
        val = meta.get("value", "(not set)")
        src = _fmt_source(meta.get("source", "default"))
        print(f"  {wk} = {val}  (from {src})")

    pending: dict = {"toml": {}, "env": {}}

    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask == "halt":
        return pending

    for wk in workflow_keys:
        meta = toml_keys.get(wk, {})
        current_val = meta.get("value", "(not set)")
        choices = _WORKFLOW_CHOICES.get(wk, [])
        choice_display = ", ".join(choices)
        short_key = wk.split(".", 1)[1] if "." in wk else wk
        print(f"  Set workflow.{short_key}? [{choice_display}, keep] (current: {current_val})")
        try:
            answer = input("  > ").strip().lower()
        except EOFError:
            answer = ""

        if answer in choices and answer != current_val:
            pending["toml"][wk] = answer

    return pending


def _wizard_overnight(inspect_data: dict) -> dict:
    """Wizard section: Overnight — show env-derived values and optionally enable overnight mode."""
    _print_section_header("Overnight")
    env_knobs = inspect_data.get("env_only_knobs") or {}

    overnight_knobs = [
        "Z_HARNESS_NO_ASK",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE",
        "Z_HARNESS_PAUSE_AT_PCT",
    ]
    for knob in overnight_knobs:
        if knob in env_knobs:
            val = env_knobs[knob].get("value")
        else:
            val = os.environ.get(knob)
        display_val = val if val is not None else "(not set)"
        print(f"  {knob} = {display_val}  (from env; not persistent)")

    pending: dict = {"toml": {}, "env": {}}

    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask == "halt":
        return pending

    print("  Enable overnight mode for this session? [yes/no] (default: no)")
    try:
        answer = input("  > ").strip().lower()
    except EOFError:
        answer = ""

    if answer not in ("y", "yes"):
        return pending

    # Ask about autodecide allowlist
    default_allowlist = '{"workflow.slug_confirm":"recommend_derived","workflow.audit_to_amend":"amend"}'
    print("  Use default autodecide allowlist")
    print(f"    (slug_confirm=recommend_derived, audit_to_amend=amend)?")
    print("  [yes/custom] (default: yes)")
    try:
        allowlist_answer = input("  > ").strip().lower()
    except EOFError:
        allowlist_answer = ""

    if allowlist_answer in ("custom",):
        print("  Enter raw JSON allowlist (e.g. {\"workflow.slug_confirm\":\"recommend_derived\"}):")
        try:
            custom_json = input("  > ").strip()
        except EOFError:
            custom_json = ""
        # Validate JSON; fall back to default on parse error
        try:
            json.loads(custom_json)
            autodecide_json = custom_json
        except json.JSONDecodeError:
            print("  [overnight] invalid JSON; using default allowlist.")
            autodecide_json = default_allowlist
    else:
        autodecide_json = default_allowlist

    pending["env"]["Z_HARNESS_NO_ASK"] = "halt"
    pending["env"]["Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE"] = autodecide_json

    print()
    print("  Note: env values are NOT persisted; you must source the snippet from Final review.")

    return pending


def _wizard_providers(inspect_data: dict) -> dict:
    """Wizard section: Providers — detect role bindings and suggest discovery if any are missing."""
    _print_section_header("Providers")
    providers_data, providers_path = _find_providers_json()

    provider_roles = ["consultant_primary", "consultant_secondary", "reviewer"]
    all_bound = False

    if providers_data is not None and providers_path:
        roles = providers_data.get("roles", {})
        bound_roles = {role: roles[role] for role in provider_roles if role in roles}
        all_bound = len(bound_roles) == len(provider_roles)

        if all_bound:
            p = bound_roles.get("consultant_primary", "?")
            s = bound_roles.get("consultant_secondary", "?")
            r = bound_roles.get("reviewer", "?")
            print(f"  Providers: OK (primary={p}, secondary={s}, reviewer={r}); skip.")
        else:
            for role in provider_roles:
                if role in roles:
                    print(f"  {role} = {roles[role]}  (from {providers_path})")
                else:
                    print(f"  {role} = (not bound)  (from {providers_path})")
            print("  Providers gap detected: run `python3 scripts/discover-providers.py`"
                  " or the /z-setup wizard's provider-discovery step.")
    else:
        for role in provider_roles:
            print(f"  {role} = (not bound)  (absent)")
        print("  Providers gap detected: run `python3 scripts/discover-providers.py`"
              " or the /z-setup wizard's provider-discovery step.")

    return {"toml": {}, "env": {}}


def _wizard_docs(inspect_data: dict) -> dict:
    """Wizard section: Docs — detect INDEX.json and suggest /z-init-docs if absent."""
    _print_section_header("Docs")
    index_data, index_path = _find_index_json()

    if index_data is not None:
        concepts = index_data.get("concepts", [])
        concept_count = len(concepts)
        print(f"  Docs: INDEX.json present with {concept_count} concepts; skip.")
    else:
        print("  Docs gap detected: run `/z-init-docs` to bootstrap.")

    return {"toml": {}, "env": {}}


# ---------------------------------------------------------------------------
# Kernel-pointer / CLAUDE.md helpers
# ---------------------------------------------------------------------------

_KERNEL_POINTER_BEGIN = "<!-- z-harness-kernel-pointer BEGIN -->"
_KERNEL_POINTER_END = "<!-- z-harness-kernel-pointer END -->"

_KERNEL_POINTER_CANONICAL = (
    "<!-- z-harness-kernel-pointer BEGIN -->\n"
    "When working in a z-harness repo, before acting, Read the z-harness kernel:\n"
    "run `scripts/resolve-kernel.sh` (in the z-harness plugin) and Read the path it prints; follow its axioms.\n"
    "<!-- z-harness-kernel-pointer END -->"
)


def _kernel_pointer_blocks_differ(existing_block: str) -> bool:
    """
    Return True if the existing marker block (including the BEGIN/END delimiters)
    differs from the canonical block.

    This is a pure function (no I/O) so it can be unit-tested without filesystem access.
    """
    return existing_block.strip() != _KERNEL_POINTER_CANONICAL.strip()


def _extract_all_kernel_pointer_blocks(text: str) -> list[str]:
    """
    Extract ALL marker blocks (including delimiters) from *text*.
    Returns a list of block strings.  An empty list means no block is present.

    This correctly handles the anomalous case where a CLAUDE.md accumulated
    multiple marker blocks due to manual editing or an interrupted prior run.
    """
    blocks: list[str] = []
    search_start = 0
    while True:
        begin_idx = text.find(_KERNEL_POINTER_BEGIN, search_start)
        if begin_idx == -1:
            break
        end_idx = text.find(_KERNEL_POINTER_END, begin_idx + len(_KERNEL_POINTER_BEGIN))
        if end_idx == -1:
            break
        end_pos = end_idx + len(_KERNEL_POINTER_END)
        blocks.append(text[begin_idx:end_pos])
        search_start = end_pos
    return blocks


def _extract_kernel_pointer_block(text: str) -> str | None:
    """
    Extract the FIRST existing marker block (including delimiters) from *text*.
    Returns the block string (with delimiters) or None if not present.

    Kept for backward compatibility with _kernel_pointer_blocks_differ callers.
    Use _extract_all_kernel_pointer_blocks when multiple-block detection matters.
    """
    blocks = _extract_all_kernel_pointer_blocks(text)
    return blocks[0] if blocks else None


def _remove_all_kernel_pointer_blocks(text: str) -> str:
    """
    Remove every BEGIN...END marker block from *text* and return the result.
    Collapses any blank lines that are left behind by removing a block that was
    on its own line, but does not touch non-marker content.
    """
    result = text
    while True:
        begin_idx = result.find(_KERNEL_POINTER_BEGIN)
        if begin_idx == -1:
            break
        end_idx = result.find(_KERNEL_POINTER_END, begin_idx + len(_KERNEL_POINTER_BEGIN))
        if end_idx == -1:
            break
        end_pos = end_idx + len(_KERNEL_POINTER_END)
        # Consume a trailing newline so we don't leave a blank line
        if end_pos < len(result) and result[end_pos] == "\n":
            end_pos += 1
        # Consume a leading newline/blank-line that belonged to the block
        prefix = result[:begin_idx]
        if prefix.endswith("\n"):
            begin_idx -= 0  # keep: the newline belongs to the previous line
        result = result[:begin_idx] + result[end_pos:]
    return result


def _install_kernel_pointer(claude_md_path: str) -> str:
    """
    Idempotently install the canonical kernel-pointer marker block into the file
    at *claude_md_path*.

    Returns a status string for display:
      "appended"    — first install
      "no_op"       — block already matches canonical; nothing written
      "skipped"     — user declined to overwrite a manually-edited block
      "updated"     — user confirmed overwrite of a manually-edited block
      "error:<msg>" — I/O failure
    """
    import difflib

    # Read existing content (file may not exist yet)
    if os.path.isfile(claude_md_path):
        try:
            with open(claude_md_path, encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            return f"error:{exc}"
    else:
        content = ""

    all_blocks = _extract_all_kernel_pointer_blocks(content)
    block_count = len(all_blocks)

    if block_count == 0:
        # Fresh install — append
        sep = "\n" if content and not content.endswith("\n") else ""
        new_content = content + sep + _KERNEL_POINTER_CANONICAL + "\n"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(claude_md_path)), exist_ok=True)
            tmp = claude_md_path + f".tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp, claude_md_path)
        except OSError as exc:
            return f"error:{exc}"
        return "appended"

    if block_count == 1 and not _kernel_pointer_blocks_differ(all_blocks[0]):
        # Exactly one block and it already matches canonical — no-op
        return "no_op"

    # Either a single block that differs from canonical (manual edit),
    # OR multiple blocks (anomalous accumulation). Either way we need to
    # collapse to a single canonical block.

    if block_count == 1:
        # Show diff so the user can see what changed
        a_lines = (all_blocks[0] + "\n").splitlines(keepends=True)
        b_lines = (_KERNEL_POINTER_CANONICAL + "\n").splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            a_lines, b_lines,
            fromfile="existing CLAUDE.md block",
            tofile="canonical block",
            lineterm="",
        ))
        print(f"\n  [setup] Existing kernel-pointer block in {claude_md_path!r} differs from canonical.")
        for line in diff_lines:
            print("  " + line)
    else:
        print(
            f"\n  [setup] Found {block_count} kernel-pointer blocks in {claude_md_path!r}."
            " These will be collapsed into one canonical block."
        )

    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask == "halt":
        print("  [setup] Z_HARNESS_NO_ASK=halt — skipping overwrite.")
        return "skipped"

    print("  Overwrite with canonical? [y/N]")
    try:
        answer = input("  > ").strip().lower()
    except EOFError:
        answer = ""

    if answer not in ("y", "yes"):
        print("  [setup] Skipped — existing block(s) preserved.")
        return "skipped"

    # Remove all existing marker blocks, then append exactly one canonical block
    stripped = _remove_all_kernel_pointer_blocks(content)
    sep = "\n" if stripped and not stripped.endswith("\n") else ""
    new_content = stripped + sep + _KERNEL_POINTER_CANONICAL + "\n"
    try:
        tmp = claude_md_path + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        os.replace(tmp, claude_md_path)
    except OSError as exc:
        return f"error:{exc}"
    return "updated"


def _ensure_gitignore_entry(gitignore_path: str, entry: str) -> str:
    """
    Idempotently add *entry* to the .gitignore at *gitignore_path*.

    Returns "added" if a new line was appended, "already_present" if *entry*
    is already present (exact-line match), or "error:<msg>" on I/O failure.
    """
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, encoding="utf-8") as fh:
                existing = fh.read()
        except OSError as exc:
            return f"error:{exc}"
    else:
        existing = ""

    # Exact-line dedup check
    for line in existing.splitlines():
        if line.strip() == entry.strip():
            return "already_present"

    sep = "\n" if existing and not existing.endswith("\n") else ""
    new_content = existing + sep + entry + "\n"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(gitignore_path)), exist_ok=True)
        tmp = gitignore_path + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        os.replace(tmp, gitignore_path)
    except OSError as exc:
        return f"error:{exc}"
    return "added"


# ---------------------------------------------------------------------------
# Wizard sections
# ---------------------------------------------------------------------------


def _wizard_memories(inspect_data: dict) -> dict:
    """Wizard section: Memories — read-only display of routing-preference entries."""
    _print_section_header("Memories")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    harness_root = os.path.dirname(script_dir)
    docs_dir = os.path.join(harness_root, "docs", "llm")

    found_any = False
    if os.path.isdir(docs_dir):
        try:
            for fname in sorted(os.listdir(docs_dir)):
                if fname == "INDEX.json" or not fname.endswith(".json"):
                    continue
                fpath = os.path.join(docs_dir, fname)
                try:
                    with open(fpath) as fh:
                        data = json.load(fh)
                    memories = data.get("memories", [])
                    if not isinstance(memories, list):
                        continue
                    for m in memories:
                        if not isinstance(m, dict):
                            continue
                        if m.get("type") == "routing-preference":
                            qid = m.get("question_id", "?")
                            val = m.get("value", "?")
                            strength = m.get("strength", "?")
                            scope = m.get("scope", "?")
                            print(f"  {qid} = {val} (strength: {strength}, scope: {scope})")
                            found_any = True
                except (OSError, json.JSONDecodeError):
                    pass
        except OSError:
            pass

    if not found_any:
        print("  no routing-preference memories yet")

    print("  Tip: Edit memories via `/z-suggest-memory --kind routing-preference"
          " --question-id <id> --value <v> --strength weak|strong|very_strong`.")

    return {"toml": {}, "env": {}}


def _wizard_axioms(inspect_data: dict) -> dict:
    """Wizard section: Axioms — configure axioms keys and install the CLAUDE.md kernel pointer."""
    _print_section_header("Axioms")
    toml_keys = inspect_data.get("toml_keys") or {}

    axioms_keys = [
        ("axioms.enabled", "bool", ["true", "false"]),
        ("axioms.auto_extract_post_run", "bool", ["true", "false"]),
        ("axioms.kernel_budget_chars", "int", None),
    ]

    for key, _ktype, choices in axioms_keys:
        meta = toml_keys.get(key, {})
        val = meta.get("value", "(not set)")
        src = _fmt_source(meta.get("source", "default"))
        print(f"  {key} = {val}  (from {src})")

    pending: dict = {"toml": {}, "env": {}}

    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask == "halt":
        return pending

    # Prompt for each key
    for key, ktype, choices in axioms_keys:
        meta = toml_keys.get(key, {})
        current_val = meta.get("value", "(not set)")
        if choices:
            choice_display = ", ".join(choices)
            print(f"  Set {key}? [{choice_display}, keep] (current: {current_val})")
        else:
            print(f"  Set {key}? [integer, keep] (current: {current_val})")
        try:
            answer = input("  > ").strip()
        except EOFError:
            answer = ""

        if not answer or answer.lower() == "keep":
            continue

        if ktype == "bool" and choices and answer.lower() in choices:
            if answer.lower() != str(current_val).lower():
                pending["toml"][key] = answer.lower()
        elif ktype == "int":
            try:
                int_val = int(answer)
                if int_val > 0 and str(int_val) != str(current_val):
                    pending["toml"][key] = int_val
            except ValueError:
                print(f"  [setup] invalid integer {answer!r}; skipping {key}")

    # CLAUDE.md kernel-pointer install
    print()
    print("  Install kernel-pointer block in ~/.claude/CLAUDE.md?")
    print("  (idempotent — safe to re-run; shows diff if block was manually edited)")

    home = os.environ.get("HOME") or os.path.expanduser("~")
    global_claude_md = os.path.join(home, ".claude", "CLAUDE.md")

    print(f"  [yes/no] (target: {global_claude_md})")
    try:
        install_answer = input("  > ").strip().lower()
    except EOFError:
        install_answer = ""

    if install_answer in ("y", "yes"):
        status = _install_kernel_pointer(global_claude_md)
        if status == "appended":
            print(f"  [setup] Kernel pointer appended to {global_claude_md!r}.")
        elif status == "no_op":
            print(f"  [setup] Kernel pointer already present and up-to-date — no-op.")
        elif status == "updated":
            print(f"  [setup] Kernel pointer block updated in {global_claude_md!r}.")
        elif status == "skipped":
            print(f"  [setup] Kernel pointer install skipped.")
        elif status.startswith("error:"):
            print(f"  [setup] Could not write {global_claude_md!r}: {status[6:]}", file=sys.stderr)

    # Per-project gitignore prompt
    print()
    print("  Add .z-harness/axioms/ and .z-harness/KERNEL.md to project .gitignore?")
    print("  [yes/no] (default: yes)")
    try:
        gi_answer = input("  > ").strip().lower()
    except EOFError:
        gi_answer = ""

    if gi_answer in ("", "y", "yes"):
        try:
            git_result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            )
            git_root = git_result.stdout.strip()
            gitignore_path = os.path.join(git_root, ".gitignore")
            for entry in [".z-harness/axioms/", ".z-harness/KERNEL.md"]:
                result = _ensure_gitignore_entry(gitignore_path, entry)
                if result == "added":
                    print(f"  [setup] Added {entry!r} to {gitignore_path!r}.")
                elif result == "already_present":
                    print(f"  [setup] {entry!r} already in .gitignore — skipped.")
                elif result.startswith("error:"):
                    print(f"  [setup] Could not update .gitignore: {result[6:]}", file=sys.stderr)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("  [setup] Not in a git repo; skipping .gitignore update.")

    return pending


def _wizard_final_review(pending: dict) -> int:
    """
    Final review step: present pending changes, confirm, and write via apply logic.

    Parameters
    ----------
    pending : dict
        Accumulated pending changes: {"toml": {key: value, ...}, "env": {var: value, ...}}

    Returns
    -------
    int
        Exit code (0 on success or no changes, 1 on write failure).
    """
    _print_section_header("Final Review")

    toml_changes = pending.get("toml") or {}
    env_changes = pending.get("env") or {}

    if not toml_changes and not env_changes:
        print("No changes to apply.")
        return 0

    # Build a synthetic diff for rendering
    diff: dict = {
        "will_change": {k: (None, v) for k, v in toml_changes.items()},
        "unchanged": {},
        "env_to_emit": dict(env_changes),
    }
    print(_render_diff(diff))

    try:
        answer = input("Apply these changes? [y/N] ").strip()
    except EOFError:
        answer = ""
    if answer.lower() not in ("y", "yes"):
        print("aborted.")
        return 0

    # Write TOML changes via config.py set
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_py = os.path.join(script_dir, "config.py")

    for key, value in toml_changes.items():
        result = subprocess.run(
            [sys.executable, config_py, "set", key, str(value), "--scope=global"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"[setup] failed to set {key!r}: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    # Emit env snippet to stdout
    if env_changes:
        snippet = _build_env_snippet(env_changes)
        print(snippet)

    # Log wizard_apply_done
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_event_sh = os.path.join(script_dir, "log-event.sh")
    if os.path.isfile(log_event_sh):
        payload = json.dumps({
            "toml_changes": len(toml_changes),
            "env_changes": len(env_changes),
        })
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "setup")
        try:
            subprocess.run(
                ["bash", log_event_sh, run_id, "wizard_apply_done", payload],
                check=False, capture_output=True,
            )
        except OSError:
            pass

    return 0


def _log_wizard_event(event: str, section: str) -> None:
    """Emit a wizard_section_start or wizard_section_end event via scripts/log-event.sh."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_event_sh = os.path.join(script_dir, "log-event.sh")
    if not os.path.isfile(log_event_sh):
        return
    payload = json.dumps({"section": section})
    run_id = os.environ.get("Z_HARNESS_RUN_ID", "setup")
    try:
        subprocess.run(
            ["bash", log_event_sh, run_id, event, payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


# Ordered section definitions for the wizard
_WIZARD_SECTIONS: list[tuple[str, object]] = [
    ("notifications", _wizard_notifications),
    ("workflow", _wizard_workflow),
    ("overnight", _wizard_overnight),
    ("providers", _wizard_providers),
    ("docs", _wizard_docs),
    ("memories", _wizard_memories),
    ("axioms", _wizard_axioms),
]


def cmd_wizard(args: argparse.Namespace) -> int:
    """
    Concern-grouped guided configuration wizard.

    --scope all     : iterate all sections in fixed order.
    --scope <name>  : run only that section + Final review.
    """
    scope: str = getattr(args, "scope", "all") or "all"

    # Fetch current state once; pass to all section functions.
    inspect_data = _inspect_all_json()
    if inspect_data is None:
        inspect_data = {"toml_keys": {}, "question_ids": {}, "env_only_knobs": {}}

    # Determine which sections to run
    if scope == "all":
        sections_to_run = _WIZARD_SECTIONS
    else:
        sections_to_run = [(name, fn) for name, fn in _WIZARD_SECTIONS if name == scope]
        if not sections_to_run:
            print(f"[setup] unknown wizard scope: {scope!r}", file=sys.stderr)
            return 2

    # Accumulate pending changes across all sections
    pending: dict = {"toml": {}, "env": {}}

    for section_name, section_fn in sections_to_run:
        _log_wizard_event("wizard_section_start", section_name)
        section_pending = section_fn(inspect_data)
        _log_wizard_event("wizard_section_end", section_name)

        # Merge section changes into pending
        pending["toml"].update(section_pending.get("toml") or {})
        pending["env"].update(section_pending.get("env") or {})

    return _wizard_final_review(pending)


def _log_apply_done(posture: str, changes_count: int, env_count: int, scope: str) -> None:
    """Emit a setup_apply_done event via scripts/log-event.sh."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_event_sh = os.path.join(script_dir, "log-event.sh")
    if not os.path.isfile(log_event_sh):
        return
    payload = json.dumps({
        "posture": posture,
        "changes_count": changes_count,
        "env_count": env_count,
        "scope": scope,
    })
    run_id = os.environ.get("Z_HARNESS_RUN_ID", "setup")
    try:
        subprocess.run(
            ["bash", log_event_sh, run_id, "setup_apply_done", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


def _build_env_snippet(env_vars: dict) -> str:
    """Build shell snippet lines for the given env vars."""
    lines = []
    for var in sorted(env_vars):
        val = env_vars[var]
        # Single-quote the value; escape any embedded single quotes.
        safe_val = val.replace("'", "'\\''")
        lines.append(f"export {var}='{safe_val}'")
    return "\n".join(lines)


def cmd_apply(args: argparse.Namespace) -> int:
    """
    Apply a posture preset to the z-harness configuration.

    --dry-run: print diff and exit 0 without writing.
    --yes: skip confirmation prompt.
    --env-file <path>: write shell snippet to this file (in addition to stdout).
    --scope global|repo: target config layer (default: global).
    """
    posture = args.posture
    if posture is None:
        print("[setup] --posture is required", file=sys.stderr)
        return 2

    if posture not in POSTURE_PRESETS:
        print(
            f"[setup] unknown posture {posture!r}; valid values: {sorted(POSTURE_PRESETS)}",
            file=sys.stderr,
        )
        return 2

    dry_run: bool = args.dry_run
    skip_confirm: bool = args.yes
    env_file: str | None = args.env_file
    scope: str = getattr(args, "scope", "global") or "global"

    # Fetch current resolved state
    current_data = _inspect_all_json()
    current_state: dict[str, object] = {}
    if current_data:
        for key, meta in (current_data.get("toml_keys") or {}).items():
            current_state[key] = meta.get("value")
        for knob, meta in (current_data.get("env_only_knobs") or {}).items():
            current_state[knob] = meta.get("value")

    diff = _compute_posture_diff(posture, current_state)
    diff_text = _render_diff(diff)

    print(diff_text)

    if dry_run:
        # Emit env snippet to stdout even in dry-run
        env_vars = diff.get("env_to_emit", {})
        if env_vars:
            snippet = _build_env_snippet(env_vars)
            print(snippet)
        return 0

    # Require confirmation unless --yes
    if not skip_confirm:
        try:
            answer = input(f"Apply posture {posture}? [y/N] ").strip()
        except EOFError:
            answer = ""
        if answer.lower() not in ("y", "yes"):
            print("aborted.")
            return 0

    # Apply TOML changes via config.py set
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_py = os.path.join(script_dir, "config.py")

    # Map setup.py scope names to config.py scope names
    config_scope = "project" if scope == "repo" else "global"

    will_change: dict = diff.get("will_change", {})
    changes_count = len(will_change)

    for key, (_, new_val) in will_change.items():
        result = subprocess.run(
            [sys.executable, config_py, "set", key, str(new_val), f"--scope={config_scope}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"[setup] failed to set {key!r}: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    # Emit env snippet
    env_vars = diff.get("env_to_emit", {})
    env_count = len(env_vars)

    if env_vars:
        snippet = _build_env_snippet(env_vars)
        print(snippet)
        if env_file:
            try:
                with open(env_file, "w") as fh:
                    fh.write(snippet + "\n")
            except OSError as exc:
                print(f"[setup] cannot write env-file {env_file!r}: {exc}", file=sys.stderr)
                return 1

    # Log completion
    _log_apply_done(posture, changes_count, env_count, scope)

    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """
    Pass-through to `config.py explain <key>`.
    Proxies stdout, stderr, and exit code verbatim.
    """
    key: str = args.key
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_py = os.path.join(script_dir, "config.py")
    try:
        result = subprocess.run(
            [sys.executable, config_py, "explain", key],
            check=False,
        )
        return result.returncode
    except OSError as exc:
        print(f"[setup] cannot invoke config.py: {exc}", file=sys.stderr)
        return 1


def _detect_posture(current_state: dict) -> str:
    """
    Detect which POSTURE_PRESET (if any) the current TOML config matches.

    Compares the current resolved TOML values for all keys referenced in
    each preset's ``toml`` section.  Returns the preset name on exact match,
    ``"none"`` when every checked key is still at its DEFAULTS value,
    or ``"custom"`` otherwise.

    Parameters
    ----------
    current_state : dict
        Flat mapping of dotted key → resolved value, built from
        ``_inspect_all_json()["toml_keys"]``.
    """
    # Flatten DEFAULTS into dotted keys so we can compare easily.
    flat_defaults: dict[str, object] = {
        "notify.level": "approval_only",
        "docs.always_apply": "always",
        "workflow.audit_to_amend": "ask",
        "workflow.slug_confirm": "ask",
        "workflow.implement_all_proceed": "ask",
        "workflow.review_all_proceed": "ask",
        "workflow.plan_decisions_approval": "ask",
    }

    for posture_name, preset in POSTURE_PRESETS.items():
        toml_target = preset["toml"]
        if all(current_state.get(k) == v for k, v in toml_target.items()):
            return posture_name

    # Check whether all preset-relevant keys are still at defaults.
    all_preset_keys: set[str] = set()
    for preset in POSTURE_PRESETS.values():
        all_preset_keys.update(preset["toml"].keys())

    all_default = all(
        current_state.get(k) == flat_defaults.get(k)
        for k in all_preset_keys
        if k in flat_defaults
    )
    if all_default:
        return "none"

    return "custom"


def cmd_status(args: argparse.Namespace) -> int:
    """
    Emit a compact one-line z-harness status report and exit 0.

    Format:
      z-harness: posture=<detected|none|custom>, providers=<bound|none>,
                 docs=<initialized|missing>, prefs=<N standing>
    """
    # --- posture ---
    inspect_data = _inspect_all_json()
    current_state: dict[str, object] = {}
    if inspect_data:
        for key, meta in (inspect_data.get("toml_keys") or {}).items():
            current_state[key] = meta.get("value")

    posture = _detect_posture(current_state)

    # --- providers ---
    providers_data, _providers_path = _find_providers_json()
    if providers_data is not None:
        roles = providers_data.get("roles", {})
        required_roles = ["consultant_primary", "consultant_secondary", "reviewer"]
        providers_status = "bound" if all(r in roles for r in required_roles) else "none"
    else:
        providers_status = "none"

    # --- docs ---
    index_data, _index_path = _find_index_json()
    docs_status = "initialized" if index_data is not None else "missing"

    # --- prefs ---
    prefs_count = _count_routing_preferences()

    print(
        f"z-harness: posture={posture}, providers={providers_status},"
        f" docs={docs_status}, prefs={prefs_count} standing"
    )
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description="z-harness configuration cockpit. "
                    "Inspect, configure, and apply posture presets for all z-harness settings.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # inspect
    p_inspect = subparsers.add_parser(
        "inspect",
        help="Show resolved state and precedence lineage for every config key.",
    )
    p_inspect.add_argument(
        "--flat",
        action="store_true",
        help="Print alphabetical key=value with source column (git-config style).",
    )
    p_inspect.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Machine-parseable JSON output.",
    )
    p_inspect.add_argument(
        "--scope",
        choices=["notifications", "workflow", "overnight", "providers", "docs", "memories", "axioms"],
        default=None,
        help="Filter output to one concern section.",
    )
    p_inspect.set_defaults(func=cmd_inspect)

    # wizard
    p_wizard = subparsers.add_parser(
        "wizard",
        help="Concern-grouped guided configuration flow.",
    )
    p_wizard.add_argument(
        "--scope",
        choices=["all", "notifications", "workflow", "overnight", "providers", "docs", "memories", "axioms"],
        default="all",
        help="Run only the named section (default: all).",
    )
    p_wizard.set_defaults(func=cmd_wizard)

    # apply
    p_apply = subparsers.add_parser(
        "apply",
        help="One-shot posture-preset bootstrap.",
    )
    p_apply.add_argument(
        "--posture",
        choices=["interactive", "overnight", "ci-batch"],
        help="Posture preset to apply.",
    )
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff without writing anything.",
    )
    p_apply.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    p_apply.add_argument(
        "--env-file",
        metavar="PATH",
        help="Write shell snippet to this file (also written to stdout).",
    )
    p_apply.add_argument(
        "--scope",
        choices=["global", "repo"],
        default="global",
        help="Config layer to write to (default: global).",
    )
    p_apply.set_defaults(func=cmd_apply)

    # explain
    p_explain = subparsers.add_parser(
        "explain",
        help="Explain a config key's resolution and precedence.",
    )
    p_explain.add_argument(
        "key",
        help="Config key to explain (e.g. notify.level).",
    )
    p_explain.set_defaults(func=cmd_explain)

    # status
    p_status = subparsers.add_parser(
        "status",
        help="Compact status line: configured layers, posture, providers, docs.",
    )
    p_status.set_defaults(func=cmd_status)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help()
        return 0

    # Log run start for every subcommand.
    # Slice everything after the subcommand token (position-based, not value-based).
    extra_args = (argv if argv is not None else sys.argv[1:])[1:]
    _log_run_start(args.subcommand, extra_args)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
