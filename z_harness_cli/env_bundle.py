"""
env_bundle.py — Injected-env resolver for z-harness CLI (D7, AMENDED F2/F10/D14).

Resolves ONE deterministic env bundle by reusing existing z-harness scripts:

  - telemetry/state root  = output of ``bash scripts/plan-path.sh z_harness_base``
                            → injected as Z_HARNESS_PLAN_DIR
  - config                = output of ``python3 scripts/config.py export-env``
                            (layered: defaults < global < repo < env)
  - plugin-root           = host-appropriate CLAUDE_PLUGIN_ROOT /
                            ANTIGRAVITY_PLUGIN_ROOT for ephemeral launches;
                            for installed-plugin launches the host resolves it
                            itself (mode="installed" → no injection)
  - providers             = Z_HARNESS_REPO_PROVIDERS pointing at the resolved
                            repo-local providers.json (global ~/.config/z-harness
                            vs repo .z-harness)

No new logic is invented here.  The functions call the existing scripts as
subprocesses and parse their stdout.  This guarantees byte-for-byte agreement
with the harness's own log-event.sh (which also calls plan-path.sh) — no
split-brain between the CLI and the spawned host.

Pure stdlib: subprocess, os, shlex.  No third-party dependencies.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _harness_root(repo_root: str | os.PathLike) -> Path:
    """Return the harness repo root (where scripts/ lives).

    The harness repo root may differ from the user's project root.  We resolve
    it relative to *this file*: env_bundle.py lives in z_harness_cli/, and
    scripts/ is a sibling at the repo root.
    """
    return Path(__file__).parent.parent.resolve()


def _scripts_dir(repo_root: str | os.PathLike) -> Path:
    """Return the scripts/ directory inside the harness repo."""
    return _harness_root(repo_root) / "scripts"


# ---------------------------------------------------------------------------
# Public: plan-path.sh → Z_HARNESS_PLAN_DIR
# ---------------------------------------------------------------------------

def resolve_plan_dir(repo_root: str | os.PathLike) -> str:
    """Return the state root by calling ``bash scripts/plan-path.sh z_harness_base``.

    The call is made with cwd=repo_root so plan-path.sh picks up the correct
    git-common-dir and anchor for that checkout.  stdout is stripped and
    returned as the plan dir path.

    Raises ``RuntimeError`` if the script exits non-zero or produces empty
    output.  The caller is expected to surface this as a fatal error.
    """
    script = _scripts_dir(repo_root) / "plan-path.sh"
    try:
        result = subprocess.run(
            ["bash", str(script), "z_harness_base"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"plan-path.sh not found at {script}: {exc}"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"plan-path.sh z_harness_base exited {result.returncode}: "
            f"{result.stderr.strip()}"
        )

    path = result.stdout.strip()
    if not path:
        raise RuntimeError(
            "plan-path.sh z_harness_base returned empty output — cannot determine "
            "state root (stderr: " + result.stderr.strip() + ")"
        )
    return path


# ---------------------------------------------------------------------------
# Public: config.py export-env → config env dict
# ---------------------------------------------------------------------------

def _parse_export_env_lines(output: str) -> dict[str, str]:
    """Parse shell ``export VAR=VALUE`` lines into a plain dict.

    Handles shlex-quoted values (single-quoted, double-quoted, bare).
    Lines that do not match the ``export <NAME>=`` prefix are silently skipped.
    """
    env: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("export "):
            continue
        rest = line[len("export "):]
        # rest is like: VAR=value  or  VAR='val ue'
        eq = rest.find("=")
        if eq < 0:
            continue
        var_name = rest[:eq]
        raw_value = rest[eq + 1:]
        # shlex.split handles quoting; we expect exactly one token.
        try:
            tokens = shlex.split(raw_value)
        except ValueError:
            # Malformed quoting — use raw value as a fallback.
            tokens = [raw_value]
        env[var_name] = tokens[0] if tokens else ""
    return env


def resolve_config_env(repo_root: str | os.PathLike) -> dict[str, str]:
    """Return config as a dict by calling ``python3 scripts/config.py export-env``.

    The call is made with cwd=repo_root so config.py picks up the correct
    repo-local .z-harness/config.toml.  The ``export VAR=VALUE`` lines printed
    to stdout are parsed into a plain dict.

    Raises ``RuntimeError`` on non-zero exit.  Empty output is not an error
    (config with no non-default keys is valid).
    """
    script = _scripts_dir(repo_root) / "config.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), "export-env"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"config.py not found at {script}: {exc}"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"config.py export-env exited {result.returncode}: "
            f"{result.stderr.strip()}"
        )

    return _parse_export_env_lines(result.stdout)


# ---------------------------------------------------------------------------
# Public: plugin-root injection (D14)
# ---------------------------------------------------------------------------

#: Mode strings accepted by the env-bundle resolvers.  Two naming schemes meet
#: here: this module historically used ``"installed"`` for the non-injecting
#: (host-resolves-its-own-plugin-root) case, while the adapter ``inject()`` API
#: (``z_harness_cli/adapters/base.py``) names the same case ``"in_place"``.  To
#: kill the cross-module footgun (a caller that builds the bundle AND calls
#: ``inject()`` must otherwise translate the string by hand — see the T013
#: note), both spellings are accepted as synonyms here.  ``"installed"`` and
#: ``"in_place"`` both mean "do NOT inject a plugin-root"; ``"ephemeral"`` means
#: "inject the plugin-root".
BundleMode = Literal["ephemeral", "installed", "in_place"]

#: The inject-style spelling of the non-injecting mode, accepted as an alias of
#: ``"installed"`` so a single ``mode`` variable can be threaded into both
#: ``resolve_env_bundle()`` and ``adapter.inject()``.
_NO_INJECT_MODES = frozenset({"installed", "in_place"})


def _normalize_mode(mode: BundleMode) -> Literal["ephemeral", "installed"]:
    """Collapse the accepted mode spellings onto this module's two cases.

    ``"in_place"`` (the adapter ``inject()`` spelling) is treated as an alias of
    ``"installed"`` (this module's historical spelling).  Any other value raises
    ``ValueError`` so a typo fails loud rather than silently injecting the wrong
    plugin-root.
    """
    if mode == "ephemeral":
        return "ephemeral"
    if mode in _NO_INJECT_MODES:
        return "installed"
    raise ValueError(
        f"Unknown env-bundle mode {mode!r}; expected one of "
        "'ephemeral', 'installed', or 'in_place'."
    )


def resolve_plugin_root_env(
    host: str,
    mode: BundleMode,
    harness_root: str | os.PathLike | None = None,
) -> dict[str, str]:
    """Return the plugin-root env var(s) appropriate for this host + mode.

    For ``mode="installed"`` (alias ``"in_place"``) the host's own environment
    already provides the correct plugin-root (no injection needed) — returns an
    empty dict.

    For ``mode="ephemeral"`` the CLI must inject the plugin-root so that
    harness scripts executed inside the spawned host can locate commands/,
    agents/, skills/, etc.  The harness repo root (where plugin.json lives)
    is used as the plugin root.

    Host-to-var mapping:
      claude, claude-code  → CLAUDE_PLUGIN_ROOT
      antigravity, agy     → ANTIGRAVITY_PLUGIN_ROOT
      cursor, codex        → CLAUDE_PLUGIN_ROOT (fallback: these hosts read
                             the same var when the harness is injected)

    The ``harness_root`` argument allows overriding the auto-detected path
    (useful in tests).
    """
    if _normalize_mode(mode) == "installed":
        return {}

    if harness_root is None:
        # Resolve relative to this file: z_harness_cli/../ (repo root)
        harness_root = Path(__file__).parent.parent.resolve()

    plugin_root_path = str(harness_root)

    host_lower = host.lower()
    if host_lower in ("antigravity", "agy"):
        return {"ANTIGRAVITY_PLUGIN_ROOT": plugin_root_path}
    # claude, claude-code, cursor, codex all use CLAUDE_PLUGIN_ROOT
    return {"CLAUDE_PLUGIN_ROOT": plugin_root_path}


# ---------------------------------------------------------------------------
# Public: providers.json path → Z_HARNESS_REPO_PROVIDERS
# ---------------------------------------------------------------------------

def resolve_providers_env(repo_root: str | os.PathLike) -> dict[str, str]:
    """Return env hint pointing at the repo-local providers.json if it exists.

    Resolution order (mirrors resolve-provider.py):
      1. Z_HARNESS_REPO_PROVIDERS env var (already set → pass it through)
      2. <repo_root>/.z-harness/providers.json  (repo-local)

    Returns ``{"Z_HARNESS_REPO_PROVIDERS": "<path>"}`` when a repo-local file
    is found, otherwise an empty dict (global ~/.config/z-harness resolution is
    left to the scripts themselves).
    """
    # Pass through an existing explicit override.
    existing = os.environ.get("Z_HARNESS_REPO_PROVIDERS", "")
    if existing:
        return {"Z_HARNESS_REPO_PROVIDERS": existing}

    repo_providers = Path(repo_root) / ".z-harness" / "providers.json"
    if repo_providers.is_file():
        return {"Z_HARNESS_REPO_PROVIDERS": str(repo_providers)}

    return {}


# ---------------------------------------------------------------------------
# Public: composite resolver
# ---------------------------------------------------------------------------

def resolve_env_bundle(
    repo_root: str | os.PathLike,
    host: str,
    mode: BundleMode,
) -> dict[str, str]:
    """Build the full injected-env bundle for a spawned host.

    Calls plan-path.sh and config.py as subprocesses (consolidate-not-reinvent)
    and merges all four layers:

      1. config env vars  (Z_HARNESS_* from config.py export-env)
      2. Z_HARNESS_PLAN_DIR  (from plan-path.sh z_harness_base)
      3. plugin-root vars  (CLAUDE_PLUGIN_ROOT / ANTIGRAVITY_PLUGIN_ROOT for
                           ephemeral launches only)
      4. Z_HARNESS_REPO_PROVIDERS  (if repo-local providers.json exists)

    Layer 2 overrides layer 1 if both set Z_HARNESS_PLAN_DIR (they won't, but
    the ordering makes intent explicit).  Layers 3+4 are independent env vars
    that do not overlap with Z_HARNESS_* config keys.

    Args:
        repo_root:  Absolute path to the user's project repo root (the dir
                    that contains .z-harness/).  Used as cwd for script calls.
        host:       Host identifier string (e.g. ``"claude"``, ``"cursor"``,
                    ``"codex"``, ``"antigravity"``).
        mode:       ``"ephemeral"`` = CLI-managed injection (plugin-root is set);
                    ``"installed"`` (alias ``"in_place"``) = host manages its own
                    plugin-root.  The ``"in_place"`` alias lets a caller pass the
                    same ``mode`` string to both this function and
                    ``adapter.inject()`` without translation (T013 footgun fix).

    Returns:
        A plain ``dict[str, str]`` ready to be merged into ``os.environ`` of a
        subprocess via ``apply_env_bundle()``.

    Raises:
        RuntimeError: if plan-path.sh or config.py exits non-zero or cannot be
                      found.  The caller should surface this as a user-visible
                      error.
    """
    bundle: dict[str, str] = {}

    # Layer 1: config (Z_HARNESS_* vars from layered TOML config)
    bundle.update(resolve_config_env(repo_root))

    # Layer 2: telemetry/state root (always wins over any Z_HARNESS_PLAN_DIR
    # that might have been in the config layer — config.py doesn't export it,
    # but be explicit about precedence)
    plan_dir = resolve_plan_dir(repo_root)
    bundle["Z_HARNESS_PLAN_DIR"] = plan_dir

    # Layer 3: plugin-root (ephemeral only)
    bundle.update(resolve_plugin_root_env(host, mode))

    # Layer 4: providers.json hint
    bundle.update(resolve_providers_env(repo_root))

    return bundle


# ---------------------------------------------------------------------------
# Public: apply bundle onto a copy of an existing environ
# ---------------------------------------------------------------------------

def apply_env_bundle(
    bundle: dict[str, str],
    base_environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge *bundle* onto a copy of *base_environ*.

    Args:
        bundle:        The dict returned by ``resolve_env_bundle()``.
        base_environ:  The base environment to extend.  Defaults to a copy of
                       ``os.environ`` when ``None``.

    Returns:
        A new ``dict[str, str]`` suitable for passing as the ``env`` argument
        to ``subprocess.run()`` / ``subprocess.Popen()``.  The original
        *base_environ* is not modified.
    """
    base = dict(os.environ if base_environ is None else base_environ)
    base.update(bundle)
    return base
