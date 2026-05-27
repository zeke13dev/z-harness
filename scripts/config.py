#!/usr/bin/env python3
"""
config.py — z-harness layered TOML config loader.

Subcommands:
  get <dotted.key>              Resolve a single key and print its value.
  export-env                    Print export lines for all non-meta keys.
  ensure-defaults               Write global config with defaults if absent.
  explain <dotted.key>          Print value + source layer.
  should-notify --event <kind>  Print yes/no notification gate.

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
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DEFAULTS: dict = {
    "schema_version": 1,
    "notify": {
        "level": "approval_only",   # off | approval_only | all
    },
    "docs": {
        "always_apply": "always",   # always | never
    },
}

VALIDATORS: dict = {
    "notify.level": {"off", "approval_only", "all"},
    "docs.always_apply": {"always", "never"},
}

META_KEYS: set = {"schema_version"}

# Valid event kinds for should-notify
_NOTIFY_EVENTS: set = {"approval", "phase_end", "error"}

# Key-format regex (must match dotted.key format: two segments, lowercase, underscores/digits)
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Pure helper: _dotted_to_env
# ---------------------------------------------------------------------------

def _dotted_to_env(key: str) -> str:
    """
    Translate a dotted TOML key to a Z_HARNESS_ env var name.

    notify.level  ->  Z_HARNESS_NOTIFY_LEVEL
    docs.always_apply  ->  Z_HARNESS_DOCS_ALWAYS_APPLY

    Raises SystemExit(2) if key does not match ``^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$``.
    """
    if not _KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        sys.exit(2)
    return "Z_HARNESS_" + key.upper().replace(".", "_")


# ---------------------------------------------------------------------------
# TOML key name validation
# ---------------------------------------------------------------------------

def _validate_toml_keys(data: dict, path: str) -> None:
    """
    Reject hyphenated keys and keys with >2-level nesting.
    Only validates top-level and one-level-deep keys (the schema we support).
    """
    for top_key, value in data.items():
        if "-" in top_key:
            print(
                f"[config] {path}: hyphenated key {top_key!r} is not allowed "
                "(use underscores)",
                file=sys.stderr,
            )
            sys.exit(2)
        if isinstance(value, dict):
            for sub_key, sub_val in value.items():
                if "-" in sub_key:
                    print(
                        f"[config] {path}: hyphenated key {top_key!r}.{sub_key!r} "
                        "is not allowed (use underscores)",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                if isinstance(sub_val, dict):
                    print(
                        f"[config] {path}: key {top_key!r}.{sub_key!r} has >2-level nesting; "
                        "not supported in slice 1",
                        file=sys.stderr,
                    )
                    sys.exit(2)


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
    if v is not None and v != 1:
        print(
            f"[config] {path}: schema_version must be 1 (got {v!r})",
            file=sys.stderr,
        )
        sys.exit(2)


def _global_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "z-harness" / "config.toml"


def _repo_config_path() -> Path:
    repo_env = os.environ.get("Z_HARNESS_REPO_CONFIG", "")
    if repo_env:
        p = Path(repo_env)
        if not p.exists():
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
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — allowed: {sorted(allowed)}"
        )
        if is_global:
            print(f"WARNING: {msg}; falling back to default", file=sys.stderr)
            # Get default value for this key
            section, key = dotted_key.split(".", 1)
            return DEFAULTS[section][key]
        else:
            print(msg, file=sys.stderr)
            sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# Layer merging
# ---------------------------------------------------------------------------

def _flatten_defaults() -> dict[str, object]:
    """Return flat {dotted_key: value} from DEFAULTS (excluding meta keys)."""
    result = {}
    for section, value in DEFAULTS.items():
        if section in META_KEYS:
            continue
        if isinstance(value, dict):
            for k, v in value.items():
                result[f"{section}.{k}"] = v
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
                continue
            for k, v in sv.items():
                dotted = f"{section}.{k}"
                # Silently ignore unknown keys for forward compatibility.
                if dotted not in flat_defaults:
                    continue
                v = _validate_enum(dotted, v, str(global_path), is_global=True)
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
                continue
            for k, v in sv.items():
                dotted = f"{section}.{k}"
                # Silently ignore unknown keys for forward compatibility.
                if dotted not in flat_defaults:
                    continue
                v = _validate_enum(dotted, v, str(repo_path), is_global=False)
                values[dotted] = v
                sources[dotted] = str(repo_path)

    # Layer 4: Env vars
    for dotted_key in list(flat_defaults.keys()):
        env_var = _dotted_to_env(dotted_key)
        env_val = os.environ.get(env_var, "")
        if env_val == "":
            continue
        env_val = _validate_enum(dotted_key, env_val, f"env {env_var}", is_global=False)
        values[dotted_key] = env_val
        sources[dotted_key] = f"env {env_var}"

    return values, sources


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
    """Return all dotted keys that are NOT meta keys."""
    keys = []
    for section, value in DEFAULTS.items():
        if section in META_KEYS:
            continue
        if isinstance(value, dict):
            for k in value:
                keys.append(f"{section}.{k}")
    return sorted(keys)


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
    # Print raw scalar (no quotes, no shlex)
    val = values[key]
    if isinstance(val, bool):
        print("true" if val else "false")
    else:
        print(val)


def cmd_export_env(args: list[str]) -> None:
    values, sources = load_config()
    for dotted_key in sorted(values.keys()):
        env_var = _dotted_to_env(dotted_key)
        val = values[dotted_key]
        # Coerce to shell string
        if isinstance(val, bool):
            shell_val = "true" if val else "false"
        else:
            shell_val = str(val)
        print(f"export {env_var}={shlex.quote(shell_val)}")
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
        "schema_version = 1\n"
        "\n"
        "[notify]\n"
        "# Notification verbosity. Values: off | approval_only | all\n"
        'level = "approval_only"\n'
        "\n"
        "[docs]\n"
        "# Whether to auto-apply docs in light flows. Values: always | never\n"
        'always_apply = "always"\n'
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


def cmd_should_notify(args: list[str]) -> None:
    # Parse --event <kind>
    if len(args) != 2 or args[0] != "--event":
        print("usage: config.py should-notify --event <kind>", file=sys.stderr)
        sys.exit(2)
    event = args[1]
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
    elif level == "approval_only":
        if event in {"approval", "error"}:
            print("yes")
        else:
            print("no")
    elif level == "all":
        print("yes")
    else:
        # Should not happen — VALIDATORS would have caught it
        print("no")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: config.py <get|export-env|ensure-defaults|explain|should-notify> [args...]",
            file=sys.stderr,
        )
        sys.exit(2)

    subcommand = sys.argv[1]
    args = sys.argv[2:]

    if subcommand == "get":
        cmd_get(args)
    elif subcommand == "export-env":
        cmd_export_env(args)
    elif subcommand == "ensure-defaults":
        cmd_ensure_defaults(args)
    elif subcommand == "explain":
        cmd_explain(args)
    elif subcommand == "should-notify":
        cmd_should_notify(args)
    else:
        print(
            f"[config] unknown subcommand {subcommand!r}; "
            "valid: get, export-env, ensure-defaults, explain, should-notify",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
