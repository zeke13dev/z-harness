#!/usr/bin/env python3
"""
resolve-provider.py <role>

Resolves a provider role to its full JSON descriptor.

Config locations (in priority order — repo wins):
  1. $XDG_CONFIG_HOME/z-harness/providers.json  (user-global; falls back to ~/.config if unset)
  2. $Z_HARNESS_REPO_PROVIDERS                   (env override for testability)
     or <repo>/.z-harness/providers.json         (repo-local default)

Output (stdout): JSON with keys: role, provider, command, args_template, stdin,
                 timeout_s, model_label, model_arg_template, model_env_var,
                 default_model, auth_env, auth_backend, auth_provider


Provider role overrides live in config.toml role bindings:
  [roles.<command>.<role>].runtime = "<provider>"
  [roles.default.<role>].runtime = "<provider>"
The older [models.<role>] provider selector remains as a compatibility fallback
only; native model classes and external provider roles stay on separate axes.
Exit codes:
  0  success
  1  role/provider/preflight/auth failure, CLI not on PATH, or invariant violation
  2  bad usage or schema error
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Module-level set tracking which file paths have already emitted a
# provider_schema_v1_upgraded event in this process.  Prevents double-emission
# when both global and repo configs are v1.
_v1_upgrade_emitted: set[str] = set()

# Module-level set tracking which alias old-names have already emitted a
# provider_alias_used event in this process.  Ensures one emission per
# (process, old-name) regardless of how many times resolve() is called.
_alias_used_emitted: set[str] = set()


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
    if v not in (1, 2):
        print(
            f"[providers] {path}: schema version must be 1 or 2 (got {v!r})",
            file=sys.stderr,
        )
        sys.exit(2)


def _upgrade_v1_to_v2(data: dict, path: str) -> dict:
    """
    Upgrade a v1 provider registry to v2 in-memory.

    Adds null values for new optional fields (model_arg_template, model_env_var,
    default_model) to each provider entry. Sets version to 2. Emits
    provider_schema_v1_upgraded event once per load.
    """
    if not data or data.get("version") != 1:
        return data

    upgraded = dict(data)
    upgraded["version"] = 2

    providers = dict(data.get("providers", {}))
    for name, entry in providers.items():
        entry = dict(entry)
        if "args_template" not in entry:
            entry["args_template"] = []
        if "kind" not in entry:
            entry["kind"] = "cli"
        entry.setdefault("model_arg_template", None)
        entry.setdefault("model_env_var", None)
        entry.setdefault("default_model", None)
        providers[name] = entry
    upgraded["providers"] = providers

    # Emit upgrade event (best-effort; non-fatal). Memoized per (process, file
    # path) to avoid double-emission when both global and repo configs are v1.
    if path not in _v1_upgrade_emitted:
        _v1_upgrade_emitted.add(path)
        script_dir = Path(__file__).parent
        log_event = script_dir / "log-event.sh"
        if log_event.exists() and shutil.which("bash"):
            payload = json.dumps({"source": path, "schema_version": 1})
            run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
            try:
                subprocess.run(
                    ["bash", str(log_event), run_id, "provider_schema_v1_upgraded", payload],
                    check=False,
                    capture_output=True,
                )
            except OSError:
                pass  # log-event.sh unavailable — ignore

    return upgraded


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

    # model_arg_template: must be list[str] or None
    model_arg_template = entry.get("model_arg_template")
    if model_arg_template is not None:
        if not (isinstance(model_arg_template, list) and all(isinstance(x, str) for x in model_arg_template)):
            _fail("model_arg_template", "list[str] or null", model_arg_template)

    # model_env_var: must be str or None
    model_env_var = entry.get("model_env_var")
    if model_env_var is not None and not isinstance(model_env_var, str):
        _fail("model_env_var", "str or null", model_env_var)

    # default_model: must be str or None
    default_model = entry.get("default_model")
    if default_model is not None and not isinstance(default_model, str):
        _fail("default_model", "str or null", default_model)

    # auth_env: optional environment variable name, never its value.
    auth_env = entry.get("auth_env")
    if auth_env is not None and not isinstance(auth_env, str):
        _fail("auth_env", "str or null", auth_env)


def load_configs() -> tuple[dict, dict, str, str]:
    """
    Return (global_data, repo_data, global_path_str, repo_path_str).
    """
    user_global = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    global_path = Path(user_global) / "z-harness" / "providers.json"
    global_data = _load(global_path)
    _validate_version(global_data, str(global_path))
    global_data = _upgrade_v1_to_v2(global_data, str(global_path))

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
    repo_data = _upgrade_v1_to_v2(repo_data, str(repo_path))

    return global_data, repo_data, str(global_path), str(repo_path)


# ---------------------------------------------------------------------------
# Merge + shadow detection
# ---------------------------------------------------------------------------

def _validate_aliases(aliases: object, config_path: str) -> None:
    """Validate the 'aliases' field is a dict[str, str]. Exits on violation."""
    if aliases is None:
        return
    if not isinstance(aliases, dict):
        print(
            f"[providers] {config_path}: 'aliases' must be an object (dict), got {type(aliases).__name__!r}",
            file=sys.stderr,
        )
        sys.exit(2)
    for k, v in aliases.items():
        if not isinstance(k, str) or not isinstance(v, str):
            print(
                f"[providers] {config_path}: 'aliases' must be dict[str, str]; "
                f"got key={k!r} (type {type(k).__name__}), value={v!r} (type {type(v).__name__})",
                file=sys.stderr,
            )
            sys.exit(2)


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
    # Validate aliases in both configs before merging.
    _validate_aliases(global_data.get("aliases"), global_path)
    _validate_aliases(repo_data.get("aliases"), repo_path)

    merged: dict = {"providers": {}, "roles": {}, "aliases": {}}

    for section in ("providers", "roles", "aliases"):
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
# Alias resolution helpers
# ---------------------------------------------------------------------------

def _emit_alias_used(old_name: str, new_name: str) -> None:
    """Emit provider_alias_used event via log-event.sh (best-effort, non-fatal).

    Does NOT perform memoization — callers are responsible for checking
    _alias_used_emitted before calling this function.
    """
    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        payload = json.dumps({"old_name": old_name, "new_name": new_name})
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, "provider_alias_used", payload],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass  # log-event.sh unavailable — ignore


def _emit_legacy_roles_used(role: str, provider_name: str) -> None:
    """Emit legacy_provider_roles_used event (best-effort, non-memoized)."""
    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        payload = json.dumps({"role": role, "provider": provider_name})
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, "legacy_provider_roles_used", payload],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass  # log-event.sh unavailable — ignore


def _apply_aliases(provider_name: str, aliases: dict, role: str, is_legacy: bool) -> str:
    """
    Check if provider_name is an alias; if so, substitute the canonical name
    and emit provider_alias_used (memoized via _alias_used_emitted).
    When is_legacy is True, also emit legacy_provider_roles_used.

    Memoization guard lives here (not inside _emit_alias_used) so that tests
    can monkeypatch _emit_alias_used while the dedup logic remains testable.

    Returns the (possibly substituted) provider name.
    """
    if is_legacy:
        _emit_legacy_roles_used(role, provider_name)

    canonical = aliases.get(provider_name)
    if canonical is not None:
        if provider_name not in _alias_used_emitted:
            _alias_used_emitted.add(provider_name)
            _emit_alias_used(provider_name, canonical)
        return canonical

    return provider_name


def _canonical_provider_name(provider_name: str, aliases: dict) -> str:
    """Return provider_name after alias substitution, without emitting telemetry."""
    return aliases.get(provider_name, provider_name)


def _descriptor(role: str, provider_name: str, entry: dict) -> dict:
    """Build the public JSON descriptor for a resolved provider entry."""
    args_template = entry.get("args_template", [])
    auth_backend, auth_provider = _auth_backend_for(entry, list(args_template))
    return {
        "role": role,
        "provider": provider_name,
        "command": entry.get("command", ""),
        "args_template": args_template,
        "stdin": entry.get("stdin", False),
        "timeout_s": entry.get("timeout_s", 300),
        "model_label": entry.get("model_label", ""),
        "model_arg_template": entry.get("model_arg_template", None),
        "model_env_var": entry.get("model_env_var", None),
        "default_model": entry.get("default_model", None),
        "auth_env": entry.get("auth_env", None),
        "auth_backend": auth_backend,
        "auth_provider": auth_provider,
    }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(role: str, merged: dict) -> dict:
    """
    Resolve *role* to a provider descriptor.
    Returns dict with keys matching the output schema.
    Calls sys.exit on unresolvable situations.

    Resolution applies alias substitution: if the looked-up provider name
    matches an entry in the 'aliases' mapping, the canonical name is used
    and a memoized provider_alias_used event is emitted.  When the role
    comes from the legacy providers.json 'roles' mapping, legacy_provider_roles_used
    is also emitted.
    """
    roles = merged.get("roles", {})
    providers = merged.get("providers", {})
    aliases = merged.get("aliases", {})

    raw_provider_name = roles.get(role)
    if not raw_provider_name:
        _fail_preflight(
            role=role,
            provider_name="",
            attempted_model="",
            auth_backend="unknown",
            reason="role is unbound — add a [roles.<command/default>.<role>].runtime binding or run `python3 scripts/discover-providers.py`",
        )

    # The roles mapping in providers.json is the legacy fallback path.
    # Apply alias substitution and emit telemetry events accordingly.
    provider_name = _apply_aliases(raw_provider_name, aliases, role, is_legacy=True)

    provider = providers.get(provider_name)
    if not provider:
        _fail_preflight(
            role=role,
            provider_name=provider_name,
            attempted_model="",
            auth_backend="unknown",
            reason=(
                f"provider={provider_name!r} referenced in roles but not defined "
                "in providers map — run `python3 scripts/discover-providers.py`"
            ),
        )

    descriptor = _descriptor(role, provider_name, provider)
    _preflight_provider(role, descriptor)
    return descriptor


# ---------------------------------------------------------------------------
# Invariant: consultant_primary ≠ consultant_secondary
# ---------------------------------------------------------------------------

def check_consultant_distinctness(role: str, merged: dict) -> None:
    """Error if both consultant roles resolve to the same canonical provider."""
    if role not in ("consultant_primary", "consultant_secondary"):
        return
    p = _peek_consultant_provider("consultant_primary", merged)
    s = _peek_consultant_provider("consultant_secondary", merged)
    if p and s and p == s:
        print(
            f"[providers] consultant_primary and consultant_secondary must resolve to "
            f"DISTINCT providers (both are {p!r})",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# compose_argv
# ---------------------------------------------------------------------------


def compose_argv(provider_dict: dict, effective_model: str | None) -> list[str]:
    """Return the full argv list for a provider dispatch.

    Args:
        provider_dict: Provider descriptor dict (as returned by ``resolve()``).
            Must contain ``args_template`` (list[str]).  May contain
            ``model_arg_template`` (list[str] | None), ``model_env_var``
            (str | None), and ``default_model`` (str | None).
        effective_model: The model string requested by the caller.  Empty
            string or None causes a fallback to ``provider_dict["default_model"]``.
            If both are empty/null, ValueError is raised.

    Returns:
        A new list starting with a copy of ``args_template``, optionally
        followed by the rendered ``model_arg_template`` (with ``{model}``
        substituted by the resolved model string).  ``model_arg_template`` is
        appended only when it is not None; a v1 provider (null template) is
        handled without raising.

    Raises:
        ValueError: When both ``effective_model`` and ``provider_dict["default_model"]``
            are empty or null, so no model string can be resolved.
    """
    argv: list[str] = list(provider_dict.get("args_template", []))

    model_arg_template: list[str] | None = provider_dict.get("model_arg_template")
    if model_arg_template is None:
        # v1 provider: no model arg; return args_template immediately without
        # attempting model resolution (which might raise unnecessarily).
        return argv

    # Resolve the effective model string (only needed when model_arg_template is set).
    model: str | None = effective_model if effective_model else None
    if not model:
        model = provider_dict.get("default_model") or None
    if not model:
        raise ValueError(
            "compose_argv: effective_model is empty/null and provider has no default_model"
        )

    # Render {model} substitution in each token.  Only the exact placeholder
    # {model} is replaced; partial matches like {models} are left untouched.
    rendered = [
        token.replace("{model}", model) if "{model}" in token else token
        for token in model_arg_template
    ]
    argv.extend(rendered)

    return argv


# ---------------------------------------------------------------------------
# Provider preflight + auth classification
# ---------------------------------------------------------------------------

def _emit_provider_event(kind: str, payload: dict) -> None:
    """Emit provider preflight telemetry best-effort, without secret material."""
    log_event = Path(__file__).parent / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, kind, json.dumps(payload)],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass


def _omp_provider_from_argv(argv: list[str]) -> str:
    """Return the OMP auth-provider id embedded in an omp-consult argv."""
    if not argv:
        return ""
    first = argv[0]
    if "/" not in first:
        return ""
    return first.split("/", 1)[0]


def _auth_backend_for(provider_dict: dict, argv: list[str]) -> tuple[str, str]:
    """Return (human auth backend, omp provider id if applicable)."""
    command = os.path.basename(str(provider_dict.get("command") or ""))
    omp_provider = _omp_provider_from_argv(argv)
    if command == "omp-consult.sh" or omp_provider:
        if omp_provider == "google-antigravity":
            return "OMP OAuth / Antigravity", omp_provider
        if omp_provider == "openai-codex":
            return "OMP OAuth / Codex", omp_provider
        if omp_provider:
            return f"OMP OAuth / {omp_provider}", omp_provider
        return "OMP OAuth", ""
    if provider_dict.get("auth_env"):
        return f"env:{provider_dict['auth_env']}", ""
    return "cli-managed", ""


def _attempted_model(provider_dict: dict, argv: list[str], effective_model: str | None) -> str:
    """Return a non-secret model label for messages/telemetry."""
    if effective_model:
        return effective_model
    if provider_dict.get("default_model"):
        return str(provider_dict["default_model"])
    if argv and "/" in argv[0]:
        return argv[0]
    return str(provider_dict.get("model_label") or "")


def _fail_preflight(
    *,
    role: str,
    provider_name: str,
    attempted_model: str,
    auth_backend: str,
    reason: str,
) -> None:
    payload = {
        "role": role,
        "provider": provider_name,
        "attempted_model": attempted_model,
        "auth_backend": auth_backend,
        "auth_ready": False,
        "reason": reason,
    }
    _emit_provider_event("provider_preflight_failed", payload)
    provider_part = f", provider={provider_name}" if provider_name else ""
    model_part = f", model={attempted_model}" if attempted_model else ""
    print(
        f"[providers] provider_preflight_failed: role={role}{provider_part}{model_part}, "
        f"auth_backend={auth_backend} — {reason}",
        file=sys.stderr,
    )
    sys.exit(1)


def _preflight_provider(
    role: str,
    provider_dict: dict,
    effective_model: str | None = None,
) -> list[str]:
    """Validate provider dispatch prerequisites and emit preflight telemetry."""
    provider_name = str(provider_dict.get("provider") or "")
    command = str(provider_dict.get("command") or "")

    try:
        argv = compose_argv(provider_dict, effective_model)
    except ValueError as exc:
        _fail_preflight(
            role=role,
            provider_name=provider_name,
            attempted_model=str(effective_model or provider_dict.get("default_model") or ""),
            auth_backend="unknown",
            reason=(
                f"argv/model composition failed: {exc}; set default_model for "
                f"provider={provider_name} or configure a concrete model"
            ),
        )

    attempted_model = _attempted_model(provider_dict, argv, effective_model)
    auth_backend, omp_provider = _auth_backend_for(provider_dict, argv)

    if not command:
        _fail_preflight(
            role=role,
            provider_name=provider_name,
            attempted_model=attempted_model,
            auth_backend=auth_backend,
            reason="provider command is empty — fix providers.json command",
        )
    if not shutil.which(command):
        _fail_preflight(
            role=role,
            provider_name=provider_name,
            attempted_model=attempted_model,
            auth_backend=auth_backend,
            reason=f"command={command} not on PATH — install the CLI or update PATH",
        )

    auth_ready: bool | str = "not_required"
    auth_env = provider_dict.get("auth_env")
    if auth_env:
        if not os.environ.get(str(auth_env)):
            _fail_preflight(
                role=role,
                provider_name=provider_name,
                attempted_model=attempted_model,
                auth_backend=auth_backend,
                reason=f"auth env var {auth_env} is not set",
            )
        auth_ready = True

    if omp_provider:
        if not shutil.which("omp"):
            _fail_preflight(
                role=role,
                provider_name=provider_name,
                attempted_model=attempted_model,
                auth_backend=auth_backend,
                reason="'omp' is not on PATH — install oh-my-pi or choose a direct CLI provider",
            )
        timeout_s = float(os.environ.get("Z_HARNESS_PROVIDER_PREFLIGHT_TIMEOUT_S", "25"))
        try:
            token = subprocess.run(
                ["omp", "token", omp_provider],
                capture_output=True,
                text=False,
                timeout=timeout_s,
                check=False,
            )
            token_ok = token.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            token_ok = False
        if not token_ok:
            _fail_preflight(
                role=role,
                provider_name=provider_name,
                attempted_model=attempted_model,
                auth_backend=auth_backend,
                reason=(
                    f"auth not ready for {omp_provider}; run 'omp', then '/login' "
                    "for that provider before retrying"
                ),
            )
        auth_ready = True

    _emit_provider_event(
        "provider_preflight_ok",
        {
            "role": role,
            "provider": provider_name,
            "command": command,
            "attempted_model": attempted_model,
            "auth_backend": auth_backend,
            "auth_ready": auth_ready,
            "argv_argc": len(argv),
        },
    )
    return argv


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_CONSULT_OFF_ROLES: frozenset[str] = frozenset(
    {"consultant_primary", "consultant_secondary", "reviewer"}
)

_SCRIPT_DIR = Path(__file__).resolve().parent


def _config_get(key: str, default: str) -> str:
    """Read a config key via config.py get; return default on any failure."""
    config_py = _SCRIPT_DIR / "config.py"
    try:
        result = subprocess.run(
            [sys.executable, str(config_py), "get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return default


def _check_compose_argv_precondition(provider_name: str, entry: dict) -> bool:
    """Return True if the provider entry satisfies the compose_argv precondition.

    compose_argv raises ValueError when model_arg_template is non-null but both
    effective_model and default_model are empty/null.  When the caller does not
    supply an effective_model (the common case for [models] override lookups), the
    only safe precondition is: if model_arg_template is set, default_model must
    also be set.
    """
    model_arg_template = entry.get("model_arg_template")
    if model_arg_template is None:
        # v1-style provider: compose_argv returns early, no precondition needed.
        return True
    default_model = entry.get("default_model")
    return bool(default_model)


def _normalize_command_key(raw: str) -> str:
    """Normalize a slash-command name to config key form (e.g. /z-plan -> z_plan)."""
    token = raw.strip().split(maxsplit=1)[0] if raw.strip() else ""
    token = token.lstrip("/")
    token = token.replace("-", "_").replace("/", "_")
    return "_".join(part for part in token.split("_") if part)


def _active_command_key() -> str:
    """Return the active command key for command-specific role bindings, if known."""
    for env_name in (
        "Z_HARNESS_PROVIDER_COMMAND",
        "Z_HARNESS_COMMAND",
        "Z_HARNESS_PARENT_COMMAND",
    ):
        command_key = _normalize_command_key(os.environ.get(env_name, ""))
        if command_key:
            return command_key
    return ""


def _config_role_runtime_binding(role: str) -> tuple[str, str]:
    """Return the selected TOML role runtime and its config reference."""
    role_key = role.replace("-", "_")
    command_key = _active_command_key()
    if command_key:
        config_ref = f"roles.{command_key}.{role_key}.runtime"
        selection = _config_get(config_ref, "").strip()
        if selection:
            return selection, config_ref

    config_ref = f"roles.default.{role_key}.runtime"
    return _config_get(config_ref, "").strip(), config_ref


def _config_role_runtime_selection(role: str) -> str:
    """Return the preferred [roles.<command/default>.<role>].runtime, or ""."""
    selection, _config_ref = _config_role_runtime_binding(role)
    return selection


def _config_models_selection(role: str) -> str:
    """Return legacy [models.<role>] provider selector, or "" when unset."""
    role_key = role.replace("-", "_")
    return _config_get(f"models.{role_key}", "").strip()


def _peek_consultant_provider(role: str, merged: dict) -> str | None:
    """Return the canonical provider name a consultant role would resolve to.

    Checks the external-provider role binding first, then the legacy [models]
    selector, then the legacy providers.json roles map.  Used to enforce the
    consultant distinctness invariant across all combinations of override and
    fallback resolution without emitting alias telemetry just for the peek.
    """
    aliases = merged.get("aliases", {})
    selection = _config_role_runtime_selection(role)
    if not selection:
        selection = _config_models_selection(role)
    if not selection:
        roles = merged.get("roles", {})
        selection = roles.get(role, "")
    if not selection:
        return None
    return _canonical_provider_name(selection, aliases)


def _resolve_config_provider_selection(
    role: str,
    selection: str,
    merged: dict,
    config_ref: str,
) -> dict:
    """Resolve a TOML provider selection to a descriptor or fail loudly."""
    providers = merged.get("providers", {})
    aliases = merged.get("aliases", {})
    provider_name = _apply_aliases(selection, aliases, role, is_legacy=False)
    entry = providers.get(provider_name)

    if entry is None:
        _fail_preflight(
            role=role,
            provider_name=provider_name,
            attempted_model="",
            auth_backend="unknown",
            reason=(
                f"{config_ref} references {selection} not found in providers.json "
                "— run `python3 scripts/discover-providers.py`"
            ),
        )

    # Consultant distinctness: verify the selected provider does not collide
    # with the other consultant role after alias canonicalization.
    _CONSULTANT_PEER = {
        "consultant_primary": "consultant_secondary",
        "consultant_secondary": "consultant_primary",
    }
    peer_role = _CONSULTANT_PEER.get(role)
    if peer_role is not None:
        peer_provider = _peek_consultant_provider(peer_role, merged)
        if peer_provider and peer_provider == provider_name:
            print(
                f"[providers] consultant_primary and consultant_secondary must resolve to "
                f"DISTINCT providers (both are {provider_name!r})",
                file=sys.stderr,
            )
            sys.exit(1)

    descriptor = _descriptor(role, provider_name, entry)
    _preflight_provider(role, descriptor)
    return descriptor


def _resolve_role_runtime_override(role: str, merged: dict) -> dict | None:
    """Resolve [roles.<command/default>.<role>].runtime when configured."""
    selection, config_ref = _config_role_runtime_binding(role)
    if not selection:
        return None
    return _resolve_config_provider_selection(
        role,
        selection,
        merged,
        f"config.toml [{config_ref}]",
    )


def _resolve_models_override(role: str, merged: dict) -> dict | None:
    """Check legacy [models.<role>] config for a provider selector.

    This compatibility path is intentionally lower priority than
    [roles.default.<role>].runtime so native model routing and external provider
    routing remain separate.
    """
    role_key = role.replace("-", "_")
    selection = _config_models_selection(role)
    if not selection:
        return None  # Silent path: fall back to default resolution.
    return _resolve_config_provider_selection(
        role,
        selection,
        merged,
        f"config.toml [models.{role_key}]",
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: resolve-provider.py <role>", file=sys.stderr)
        sys.exit(2)

    role = sys.argv[1]

    # runtime.consult = "off": return sentinel "none" for consultant/reviewer roles
    # and skip the distinctness check.  Consumers that see "none" must skip the
    # external-model dispatch entirely (see z-plan.md Phase 3/7 and
    # z-execute.md reviewer gate).
    consult_val = _config_get("runtime.consult", "on").strip().lower()
    if consult_val == "off" and role in _CONSULT_OFF_ROLES:
        print("none")
        sys.exit(0)

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

    # External provider role override: [roles.default.<role>].runtime is the
    # preferred TOML binding surface and stays separate from native model classes.
    role_runtime_override = _resolve_role_runtime_override(role, merged)
    if role_runtime_override is not None:
        print(json.dumps(role_runtime_override))
        return

    # Compatibility fallback: older configs used [models.<role>] to select an
    # external provider.  Preserve it, but keep it below the role runtime axis.
    override = _resolve_models_override(role, merged)
    if override is not None:
        print(json.dumps(override))
        return

    check_consultant_distinctness(role, merged)

    descriptor = resolve(role, merged)
    print(json.dumps(descriptor))


if __name__ == "__main__":
    main()
