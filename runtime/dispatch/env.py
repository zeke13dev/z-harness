"""
env.py — build a clean subprocess environment for provider dispatch.

Public surface:
    build_env(provider_config, base_env=None, effective_model=None) -> dict

v1 intentionally omits ENV_STRIP_LIST (YAGNI per audit MINOR m1).
"""

from __future__ import annotations

import os
import sys


def build_env(
    provider_config: dict,
    base_env: dict | None = None,
    effective_model: str | None = None,
) -> dict:
    """Return a new env dict suitable for passing to a subprocess.

    Args:
        provider_config: Provider configuration dict.  If it contains an
            ``auth_env`` key, that key's value is treated as the *name* of an
            environment variable to forward into the returned dict.  If it
            contains ``model_env_var`` (and ``model_arg_template`` is None),
            the env var named by ``model_env_var`` is set to ``effective_model``
            in the returned dict.
        base_env: Optional starting environment.  If None, ``os.environ`` is
            copied.  The original dict is never mutated.
        effective_model: Optional model string.  When truthy and
            ``provider_config["model_env_var"]`` is set and
            ``provider_config["model_arg_template"]`` is None, the env var
            named by ``model_env_var`` is merged into the returned dict.
            When ``model_arg_template`` is also set, the env var injection is
            skipped and a ``model_env_var_ignored`` warning is emitted to
            stderr (best-effort).

    Returns:
        A new dict derived from ``base_env`` (or ``os.environ``) with:
        - ``CLAUDECODE`` set to ``""`` (empty string, not unset).
        - The variable named by ``provider_config["auth_env"]`` forwarded
          from ``base_env`` if it is present there; omitted otherwise.
        - Optionally, the variable named by ``provider_config["model_env_var"]``
          set to ``effective_model`` when conditions are met (see above).
    """
    env: dict = os.environ.copy() if base_env is None else dict(base_env)

    env["CLAUDECODE"] = ""

    auth_var: str | None = provider_config.get("auth_env")
    if auth_var:
        source = base_env if base_env is not None else os.environ
        if auth_var in source:
            env[auth_var] = source[auth_var]
        else:
            env.pop(auth_var, None)

    model_env_var: str | None = provider_config.get("model_env_var")
    model_arg_template = provider_config.get("model_arg_template")

    # Resolve effective_model against default_model before any guard checks.
    resolved_model: str = effective_model or provider_config.get("default_model") or ""

    if model_env_var and model_arg_template is not None:
        # Both paths configured: arg template takes precedence; warn regardless
        # of whether a model was supplied — the configuration conflict exists
        # independent of the call-site model value.
        print(
            f"[env] model_env_var_ignored: provider has both model_arg_template and "
            f"model_env_var={model_env_var!r}; model_env_var will not be set",
            file=sys.stderr,
        )
    elif model_env_var and resolved_model:
        env[model_env_var] = resolved_model

    return env
