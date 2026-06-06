"""
env_hygiene.py — CLAUDECODE env-clearing helpers for SubprocessClaudeDriver.

When z-harness runs inside Claude Code (as a plugin), the parent process
exposes CLAUDECODE=<non-empty> in the environment.  Any child process that
inherits this value will itself be recognised as a Claude Code host — which
causes recursion / mis-detection.  SubprocessClaudeDriver must therefore
always clear CLAUDECODE before spawning a child claude process.

Public surface
--------------
CLAUDECODE_VAR   — canonical env-var name (single source of truth)
BARE_FLAG        — the --bare CLI flag passed to `claude -p`

build_subprocess_env()         -> dict  (fresh env with CLAUDECODE="")
apply_env_hygiene(base_env)    -> dict  (merge base_env + required overrides)
detect_self_hosted()           -> bool  (True iff running inside Claude Code)

Telemetry
---------
apply_env_hygiene returns a (dict, cleared_vars) pair so the caller can emit
the `env_hygiene_applied` event with cleared_vars (list of var *names*, never
values).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Module-level constants — no string literals elsewhere in this module
# ---------------------------------------------------------------------------

CLAUDECODE_VAR: str = "CLAUDECODE"
BARE_FLAG: str = "--bare"

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_subprocess_env() -> dict[str, str]:
    """Return a fresh env dict with CLAUDECODE forced to empty string.

    The returned dict is independent of os.environ; callers may mutate it
    freely without affecting the parent process environment.
    """
    env: dict[str, str] = dict(os.environ)
    env[CLAUDECODE_VAR] = ""
    return env


def apply_env_hygiene(base_env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Merge base_env with required hygiene overrides; return (new_dict, cleared_vars).

    Parameters
    ----------
    base_env:
        The caller's starting env dict (not mutated).

    Returns
    -------
    result_env:
        A *new* dict: shallow copy of base_env with hygiene overrides applied.
    cleared_vars:
        List of variable names whose values were cleared (set to "").  These
        names (never their values) are safe to include in telemetry payloads.
    """
    result: dict[str, str] = dict(base_env)
    cleared_vars: list[str] = []

    # Clear CLAUDECODE unconditionally — even if it was already empty in
    # base_env, we record it so the caller can emit a consistent event.
    result[CLAUDECODE_VAR] = ""
    cleared_vars.append(CLAUDECODE_VAR)

    return result, cleared_vars


def detect_self_hosted() -> bool:
    """Return True iff this process is running inside Claude Code.

    Detection is based solely on whether CLAUDECODE is present and non-empty
    in os.environ.
    """
    return bool(os.environ.get(CLAUDECODE_VAR))
