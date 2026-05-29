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


def _find_personas_dirs() -> list[str]:
    """Return existing persona directories (global and repo)."""
    dirs: list[str] = []

    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    global_personas = os.path.join(xdg, "z-harness", "personas")
    if os.path.isdir(global_personas):
        dirs.append(global_personas)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        git_root = result.stdout.strip()
        repo_personas = os.path.join(git_root, ".z-harness", "personas")
        if os.path.isdir(repo_personas):
            dirs.append(repo_personas)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return dirs


def _collect_personas(persona_dirs: list[str]) -> list[tuple[str, str]]:
    """
    Return list of (persona_name, source_path) from all persona directories.
    Persona name is the filename without extension.
    """
    personas: list[tuple[str, str]] = []
    for d in persona_dirs:
        try:
            for fname in sorted(os.listdir(d)):
                fpath = os.path.join(d, fname)
                if os.path.isfile(fpath):
                    name, _ext = os.path.splitext(fname)
                    personas.append((name, fpath))
        except OSError:
            pass
    return personas


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
    "personas": "Personas",
    "docs": "Docs",
    "memories": "Memories",
}

# Which toml_keys prefixes belong to each scope
_SCOPE_TOML_PREFIXES: dict[str, list[str]] = {
    "notifications": ["notify."],
    "workflow": ["workflow."],
    "overnight": [],  # overnight keys are env-only
    "providers": [],
    "personas": [],
    "docs": ["docs."],
    "memories": [],
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
    "personas": [],
    "docs": [],
    "memories": [],
}


def _print_section_header(title: str) -> None:
    print(f"\n=== {title} ===")


def cmd_inspect(args: argparse.Namespace) -> int:
    """
    Emit a concern-grouped inspect view of all z-harness configuration.
    Calls `config.py inspect-all --json`, then augments with providers.json,
    personas, and INDEX.json.
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

    # When no scope filter (or non-key scopes), also include providers/personas/docs/memories
    if scope is None:
        providers_data, providers_path = _find_providers_json()
        persona_dirs = _find_personas_dirs()
        personas = _collect_personas(persona_dirs)
        index_data, index_path = _find_index_json()
        mem_count = _count_routing_preferences()

        output["__providers__"] = {
            "value": providers_data,
            "source": providers_path if providers_path else "none",
            "persistence_class": "provider_file",
            "strength": "hard" if providers_data is not None else "none",
        }
        output["__personas__"] = {
            "value": [{"name": n, "path": p} for n, p in personas],
            "source": str(persona_dirs) if persona_dirs else "none",
            "persistence_class": "persona_file",
            "strength": "hard" if personas else "none",
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
    elif scope.lower() == "personas":
        persona_dirs = _find_personas_dirs()
        personas = _collect_personas(persona_dirs)
        output["__personas__"] = {
            "value": [{"name": n, "path": p} for n, p in personas],
            "source": str(persona_dirs) if persona_dirs else "none",
            "persistence_class": "persona_file",
            "strength": "hard" if personas else "none",
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
    persona_dirs: list[str] = []
    personas: list[tuple[str, str]] = []
    index_data = index_path = None
    mem_count = 0

    need_providers = _show_section("providers")
    need_personas = _show_section("personas")
    need_docs = _show_section("docs")
    need_memories = _show_section("memories")

    if need_providers:
        providers_data, providers_path = _find_providers_json()
    if need_personas:
        persona_dirs = _find_personas_dirs()
        personas = _collect_personas(persona_dirs)
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
                print(f"  {role} = (not bound)  (absent — run /z-providers-discover)")

    # -------------------------------------------------------------------------
    # Section 5: Personas
    # -------------------------------------------------------------------------
    if need_personas:
        _print_section_header("Personas")

        if personas:
            for name, path in personas:
                print(f"  {name}  (from {path})")
        else:
            print("  (no personas bound — edit ~/.config/z-harness/personas/ or .z-harness/personas/)")

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
            print("  Providers gap detected: run `/z-providers-discover` (global) or"
                  " `/z-providers-discover --repo` (repo).")
    else:
        for role in provider_roles:
            print(f"  {role} = (not bound)  (absent)")
        print("  Providers gap detected: run `/z-providers-discover` (global) or"
              " `/z-providers-discover --repo` (repo).")

    return {"toml": {}, "env": {}}


def _wizard_personas(inspect_data: dict) -> dict:
    """Wizard section: Personas — read-only display of role.persona bindings."""
    _print_section_header("Personas")
    providers_data, _providers_path = _find_providers_json()

    personas_found = False
    if providers_data is not None:
        roles = providers_data.get("roles", {})
        for role_name, role_val in roles.items():
            persona = None
            if isinstance(role_val, dict):
                persona = role_val.get("persona")
            if persona:
                print(f"  {role_name}: {persona}")
                personas_found = True

    if not personas_found:
        print("  no personas bound")

    print("  Tip: Persona setup is read-only in v1. Edit `~/.config/z-harness/providers.json`"
          " directly, or run `/z-personas` if available.")

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
    ("personas", _wizard_personas),
    ("docs", _wizard_docs),
    ("memories", _wizard_memories),
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
        choices=["notifications", "workflow", "overnight", "providers", "personas", "docs", "memories"],
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
        choices=["all", "notifications", "workflow", "overnight", "providers", "personas", "docs", "memories"],
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
