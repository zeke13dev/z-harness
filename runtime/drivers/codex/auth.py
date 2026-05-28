"""
runtime/drivers/codex/auth.py — Auth resolution for the Codex CLI driver.

Implements a three-step precedence chain:

  1. CODEX_API_KEY env var         → strategy: "codex_api_key"
  2. OPENAI_API_KEY env var         → strategy: "openai_api_key_workaround"
     (uses the model_providers config.toml workaround for codex#5212;
      the actual config.toml injection is performed by T005/driver wiring,
      not here — this module's job is precedence detection and env_additions only)
  3. ~/.codex/auth.json presence    → strategy: "auth_json"
     (read-only check per C2-D3; no token extraction or env injection;
      the codex CLI reads this file itself)

Raises AuthResolutionError if none of the three paths yields a credential.

Emits the ``codex_auth_resolved`` telemetry event via runtime.compat.log_event
on every successful resolution. When the caller does not supply run_id or
repo_root, sensible defaults are used ("codex-auth" and os.getcwd()).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from runtime.compat import log_event
except ImportError:
    log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class AuthResult:
    """
    Result of a successful auth resolution.

    Attributes
    ----------
    strategy : str
        One of ``"codex_api_key"``, ``"openai_api_key_workaround"``,
        or ``"auth_json"``.
    env_additions : dict[str, str]
        Environment variables to inject into the codex subprocess.
        For ``"codex_api_key"``: ``{"CODEX_API_KEY": "<value>"}``.
        For ``"openai_api_key_workaround"``: ``{"OPENAI_API_KEY": "<value>"}``.
        For ``"auth_json"``: ``{}`` (codex CLI reads the file itself).
    """

    strategy: str
    env_additions: dict[str, str] = field(default_factory=dict)


class AuthResolutionError(Exception):
    """
    Raised when no auth path yields a usable credential.

    The message describes which paths were checked so the caller can produce
    an actionable error message without re-implementing the precedence logic.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_auth(
    provider_entry: dict,
    *,
    run_id: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> AuthResult:
    """
    Resolve Codex CLI authentication using the three-step precedence chain.

    Parameters
    ----------
    provider_entry : dict
        Provider config entry (from provider.schema.json / providers.json).
        Currently unused by auth resolution itself but kept in the signature
        for forward-compatibility with provider-level auth overrides.
    run_id : str or None
        z-harness run identifier for telemetry.  Defaults to ``"codex-auth"``
        when not supplied so that the ``codex_auth_resolved`` event always fires.
    repo_root : str or None
        Absolute path to the repository root.  Defaults to ``os.getcwd()``
        when not supplied.

    Returns
    -------
    AuthResult
        Resolved auth strategy and any env vars to inject into the subprocess.

    Raises
    ------
    AuthResolutionError
        If none of the three credential paths yields a usable credential.
    """
    result = _try_codex_api_key()
    if result is None:
        result = _try_openai_api_key()
    if result is None:
        result = _try_auth_json()
    if result is None:
        raise AuthResolutionError(
            "Codex auth resolution failed: no credential found. "
            "Checked (in order): "
            "(1) CODEX_API_KEY environment variable — not set; "
            "(2) OPENAI_API_KEY environment variable — not set; "
            "(3) ~/.codex/auth.json presence — file does not exist. "
            "Set CODEX_API_KEY, OPENAI_API_KEY, or authenticate via "
            "`codex auth` to create ~/.codex/auth.json."
        )

    effective_run_id = run_id if run_id is not None else "codex-auth"
    effective_repo_root = repo_root if repo_root is not None else os.getcwd()
    _emit_telemetry(
        result.strategy,
        run_id=effective_run_id,
        repo_root=effective_repo_root,
    )
    return result


# ---------------------------------------------------------------------------
# Private helpers — one per precedence step
# ---------------------------------------------------------------------------


def _try_codex_api_key() -> Optional[AuthResult]:
    """Step 1: check CODEX_API_KEY env var."""
    value = os.environ.get("CODEX_API_KEY", "").strip()
    if value:
        return AuthResult(
            strategy="codex_api_key",
            env_additions={"CODEX_API_KEY": value},
        )
    return None


def _try_openai_api_key() -> Optional[AuthResult]:
    """Step 2: check OPENAI_API_KEY env var (model_providers workaround)."""
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if value:
        return AuthResult(
            strategy="openai_api_key_workaround",
            env_additions={"OPENAI_API_KEY": value},
        )
    return None


def _try_auth_json() -> Optional[AuthResult]:
    """Step 3: presence-check ~/.codex/auth.json (C2-D3: read-only, no extraction)."""
    auth_json = Path.home() / ".codex" / "auth.json"
    if auth_json.is_file():
        return AuthResult(
            strategy="auth_json",
            env_additions={},
        )
    return None


# ---------------------------------------------------------------------------
# Telemetry helper
# ---------------------------------------------------------------------------


def _emit_telemetry(
    strategy_used: str,
    *,
    run_id: str,
    repo_root: str,
) -> None:
    """
    Emit the ``codex_auth_resolved`` telemetry event.

    Called on every successful auth resolution; callers must supply real
    run_id and repo_root (resolve_auth applies defaults before calling here).
    Silently swallowed when log_event is unavailable or the shell helper fails,
    so telemetry never prevents a caller from receiving a valid AuthResult.
    """
    if log_event is None:
        # runtime.compat was not importable (e.g., running outside z-harness).
        return

    try:
        log_event(
            run_id=run_id,
            kind="codex_auth_resolved",
            payload={"strategy_used": strategy_used},
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        # log-event.sh is unavailable (e.g., running outside z-harness).
        # Auth resolution itself succeeded; don't let telemetry failure
        # break the caller.
        pass
