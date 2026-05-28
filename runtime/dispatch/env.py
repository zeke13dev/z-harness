"""
env.py — build a clean subprocess environment for provider dispatch.

Public surface:
    build_env(provider_config, base_env=None) -> dict

v1 intentionally omits ENV_STRIP_LIST (YAGNI per audit MINOR m1).
"""

from __future__ import annotations

import os


def build_env(
    provider_config: dict,
    base_env: dict | None = None,
) -> dict:
    """Return a new env dict suitable for passing to a subprocess.

    Args:
        provider_config: Provider configuration dict.  If it contains an
            ``auth_env`` key, that key's value is treated as the *name* of an
            environment variable to forward into the returned dict.
        base_env: Optional starting environment.  If None, ``os.environ`` is
            copied.  The original dict is never mutated.

    Returns:
        A new dict derived from ``base_env`` (or ``os.environ``) with:
        - ``CLAUDECODE`` set to ``""`` (empty string, not unset).
        - The variable named by ``provider_config["auth_env"]`` forwarded
          from ``base_env`` if it is present there; omitted otherwise.
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

    return env
