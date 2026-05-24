#!/usr/bin/env python3
"""
resolve-provider.py <role>

Resolves a provider role to its full JSON descriptor.

Config locations (in priority order — repo wins):
  1. $XDG_CONFIG_HOME/z-harness/providers.json  (user-global; falls back to ~/.config if unset)
  2. $Z_HARNESS_REPO_PROVIDERS                   (env override for testability)
     or <repo>/.z-harness/providers.json         (repo-local default)

Output (stdout): JSON with keys: role, provider, command, args_template, stdin,
                 timeout_s, model_label

Exit codes:
  0  success
  1  role unbound, CLI not on PATH, or invariant violation
  2  bad usage or schema error
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    """Load JSON from path; return {} if file missing."""
    if not path.exists():
        return {}
    with open(path) as fh:
        return json.load(fh)


def _validate_version(data: dict, path: str) -> None:
    if not data:
        return  # empty / missing file — skip validation
    v = data.get("version")
    if v != 1:
        print(
            f"[providers] {path}: schema version must be 1 (got {v!r})",
            file=sys.stderr,
        )
        sys.exit(2)


def _validate_provider_entry(provider_name: str, entry: dict, config_path: str) -> None:
    """Validate all required fields for a single provider entry. Exits on violation."""

    def _fail(field: str, expected: str, actual: object) -> None:
        print(
            f"[providers] {config_path}: invalid {field} for provider={provider_name}: "
            f"expected {expected}, got {actual!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    # kind: must be the string "cli"
    kind = entry.get("kind")
    if not (isinstance(kind, str) and kind == "cli"):
        _fail("kind", '"cli"', kind)

    # command: must be a string
    command = entry.get("command")
    if not isinstance(command, str):
        _fail("command", "str", command)

    # args_template: must be list[str]
    args_template = entry.get("args_template")
    if not (isinstance(args_template, list) and all(isinstance(x, str) for x in args_template)):
        _fail("args_template", "list[str]", args_template)

    # stdin: must be bool
    stdin = entry.get("stdin")
    if not isinstance(stdin, bool):
        _fail("stdin", "bool", stdin)

    # timeout_s: must be positive int
    timeout_s = entry.get("timeout_s")
    if not (isinstance(timeout_s, int) and not isinstance(timeout_s, bool) and timeout_s > 0):
        _fail("timeout_s", "positive int", timeout_s)

    # model_label: must be string
    model_label = entry.get("model_label")
    if not isinstance(model_label, str):
        _fail("model_label", "str", model_label)


def load_configs() -> tuple[dict, dict, str, str]:
    """
    Return (global_data, repo_data, global_path_str, repo_path_str).
    """
    user_global = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    global_path = Path(user_global) / "z-harness" / "providers.json"
    global_data = _load(global_path)
    _validate_version(global_data, str(global_path))

    # Repo config: prefer explicit env override for testability.
    repo_env = os.environ.get("Z_HARNESS_REPO_PROVIDERS", "")
    if repo_env:
        repo_path = Path(repo_env)
    else:
        # Discover repo root via git, fall back to cwd.
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            )
            repo_root = Path(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            repo_root = Path.cwd()
        repo_path = repo_root / ".z-harness" / "providers.json"

    repo_data = _load(repo_path)
    _validate_version(repo_data, str(repo_path))

    return global_data, repo_data, str(global_path), str(repo_path)


# ---------------------------------------------------------------------------
# Merge + shadow detection
# ---------------------------------------------------------------------------

def merge_with_shadow(
    global_data: dict,
    repo_data: dict,
    global_path: str,
    repo_path: str,
) -> dict:
    """
    Merge global + repo configs per-key (repo wins).
    Log + emit provider_shadowed events for each key that is shadowed.
    Returns the merged dict: {"providers": {...}, "roles": {...}}.
    """
    merged: dict = {"providers": {}, "roles": {}}

    for section in ("providers", "roles"):
        g_section = global_data.get(section, {})
        r_section = repo_data.get(section, {})

        shadowed_keys = set(g_section) & set(r_section)
        for key in shadowed_keys:
            _emit_shadow(section, key, global_path, repo_path)

        merged[section] = {**g_section, **r_section}

    return merged


def _emit_shadow(section: str, key: str, global_path: str, repo_path: str) -> None:
    """Print warning to stderr and emit provider_shadowed event (de-duped)."""
    # De-dup guard: only warn once per parent process tree per (section, key).
    # Uses a stamp file keyed on PPID so the guard survives subshell boundaries.
    stamp_name = f"z-harness-provider-shadowed-{os.getppid()}-{section}-{key}"
    stamp_path = os.path.join(tempfile.gettempdir(), stamp_name)
    if os.path.exists(stamp_path):
        return
    open(stamp_path, "w").close()

    msg = (
        f"[providers] provider_shadowed: {section}.{key} "
        f"— repo ({repo_path}) overrides global ({global_path})"
    )
    print(msg, file=sys.stderr)

    # Also emit a JSONL event if log-event.sh is reachable.
    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        payload = json.dumps({"section": section, "key": key, "repo": repo_path, "global": global_path})
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, "provider_shadowed", payload],
                check=False,           # non-fatal — observability best-effort
                capture_output=True,
            )
        except OSError:
            pass  # log-event.sh unavailable — ignore


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(role: str, merged: dict) -> dict:
    """
    Resolve *role* to a provider descriptor.
    Returns dict with keys matching the output schema.
    Calls sys.exit on unresolvable situations.
    """
    roles = merged.get("roles", {})
    providers = merged.get("providers", {})

    provider_name = roles.get(role)
    if not provider_name:
        print(
            f"[providers] role={role} unbound — run /z-providers-discover",
            file=sys.stderr,
        )
        sys.exit(1)

    provider = providers.get(provider_name)
    if not provider:
        print(
            f"[providers] role={role}: provider={provider_name!r} referenced in roles "
            f"but not defined in providers map",
            file=sys.stderr,
        )
        sys.exit(1)

    command = provider.get("command", "")
    if not shutil.which(command):
        print(
            f"[providers] role={role}, provider={provider_name}, command={command} not on PATH",
            file=sys.stderr,
        )
        sys.exit(1)

    return {
        "role": role,
        "provider": provider_name,
        "command": command,
        "args_template": provider.get("args_template", []),
        "stdin": provider.get("stdin", False),
        "timeout_s": provider.get("timeout_s", 300),
        "model_label": provider.get("model_label", ""),
    }


# ---------------------------------------------------------------------------
# Invariant: consultant_primary ≠ consultant_secondary
# ---------------------------------------------------------------------------

def check_consultant_distinctness(role: str, merged: dict) -> None:
    """Error if both consultant roles are bound to the same provider."""
    if role not in ("consultant_primary", "consultant_secondary"):
        return
    roles = merged.get("roles", {})
    p = roles.get("consultant_primary")
    s = roles.get("consultant_secondary")
    if p and s and p == s:
        print(
            f"[providers] consultant_primary and consultant_secondary must resolve to "
            f"DISTINCT providers (both are {p!r})",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        print("usage: resolve-provider.py <role>", file=sys.stderr)
        sys.exit(2)

    role = sys.argv[1]

    global_data, repo_data, global_path, repo_path = load_configs()
    merged = merge_with_shadow(global_data, repo_data, global_path, repo_path)

    # Validate each provider entry in the merged config.
    # Use repo_path as the config_path since it is the effective source after merge;
    # for entries that came solely from global, fall back to global_path.
    _merged_providers = merged.get("providers", {})
    _global_providers = global_data.get("providers", {}) if global_data else {}
    _repo_providers = repo_data.get("providers", {}) if repo_data else {}
    for _pname, _entry in _merged_providers.items():
        _config_src = repo_path if _pname in _repo_providers else global_path
        _validate_provider_entry(_pname, _entry, _config_src)

    check_consultant_distinctness(role, merged)

    descriptor = resolve(role, merged)
    print(json.dumps(descriptor))


if __name__ == "__main__":
    main()
