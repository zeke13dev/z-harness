"""
runtime/compat.py — thin wrappers around z-harness shell scripts.

Provides:
  resolve_provider(role, repo_root) -> dict
  log_event(run_id, kind, payload, repo_root, slug=None) -> None
"""

import json
import os
import subprocess
from pathlib import Path


def resolve_provider(role: str, repo_root: str) -> dict:
    """
    Resolve a provider role to its JSON descriptor by calling
    scripts/resolve-provider.py <role>.

    Parameters
    ----------
    role : str
        The provider role name to resolve.
    repo_root : str
        Absolute path to the repository root.

    Returns
    -------
    dict
        Parsed JSON output from the script.

    Raises
    ------
    FileNotFoundError
        If scripts/resolve-provider.py does not exist at the expected path.
    RuntimeError
        If the script exits with a non-zero status (stderr included in message).
    """
    script_path = Path(repo_root) / "scripts" / "resolve-provider.py"
    if not script_path.is_file():
        raise FileNotFoundError(
            f"scripts/resolve-provider.py not found at {script_path}"
        )

    result = subprocess.run(
        [str(script_path), role],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"resolve-provider.py exited with code {result.returncode}: {result.stderr.strip()}"
        )

    return json.loads(result.stdout)


def log_event(
    run_id: str,
    kind: str,
    payload: dict,
    repo_root: str,
    slug: str | None = None,
) -> None:
    """
    Append a structured event to the run's events.jsonl by calling
    scripts/log-event.sh <run_id> <kind> <json-payload>.

    Injects ``schema_version: 1`` into *payload* if the key is absent.
    When *slug* is provided, sets ``Z_HARNESS_SLUG=<slug>`` in the subprocess
    environment so log-event.sh applies slug namespacing.

    Parameters
    ----------
    run_id : str
        The run identifier passed as the first positional argument.
    kind : str
        The event kind string.
    payload : dict
        Event payload dict. ``schema_version`` is injected if missing.
    repo_root : str
        Absolute path to the repository root.
    slug : str or None
        Optional plan slug. When set, ``Z_HARNESS_SLUG`` is forwarded to the
        subprocess environment.

    Raises
    ------
    FileNotFoundError
        If scripts/log-event.sh does not exist at the expected path.
    RuntimeError
        If the script exits with a non-zero status (stderr included in message).
    """
    script_path = Path(repo_root) / "scripts" / "log-event.sh"
    if not script_path.is_file():
        raise FileNotFoundError(
            f"scripts/log-event.sh not found at {script_path}"
        )

    if "schema_version" not in payload:
        payload = {**payload, "schema_version": 1}

    env = os.environ.copy()
    if slug is not None:
        env["Z_HARNESS_SLUG"] = slug

    result = subprocess.run(
        [str(script_path), run_id, kind, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"log-event.sh exited with code {result.returncode}: {result.stderr.strip()}"
        )
