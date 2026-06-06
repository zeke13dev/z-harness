"""commands/launch.py — `z-harness launch` command (Model B).

Spec reference: SPEC.md "Commands (behavior)", D14, D6-hardening, F3, F5, T015.

Behavior (in order):
  1. Resolve PROJECT (default cwd) and enforce the F3 precondition: PROJECT must
     be inside a git work tree with a writable (or creatable) ``.gitignore``.  A
     non-git directory fails loud with an ``export``-mode hint — we never litter
     a non-git dir.
  2. Recover crash-interrupted state: ``inject_safety.detect_orphans(project)``
     surfaces a half-harnessed tree from a prior run whose cleanup never ran,
     and ``inject_safety.cleanup(project)`` finishes that restore before we
     inject anew (the durable manifest at ``<git-root>/.z-harness/
     injected_files.json`` makes this resumable).
  3. Detect / select the host adapter (``--host`` override or the Rich picker).
  4. Build the injected-env bundle via ``env_bundle.resolve_env_bundle()`` in
     ``"ephemeral"`` mode (launch is ALWAYS the gitignored/ephemeral path —
     SPEC.md:115-116) paired with the adapter's ``"ephemeral"`` inject mode.  Per
     D14 (SPEC.md:151-155) this injects the host-appropriate plugin-root env var
     (CLAUDE_PLUGIN_ROOT / ANTIGRAVITY_PLUGIN_ROOT) so the spawned host can
     resolve the runtime; without it every /z-* command fails after handover.
     The SAME ``"ephemeral"`` mode string is threaded into both
     ``resolve_env_bundle`` and ``inject``.
  5. Inject (clobber-guarded by ``inject_safety.preflight_targets`` inside the
     adapter).  A foreign-file clobber raises ``ClobberRefused`` → exit 1.
  6. Print the fidelity banner (``--quiet`` suppresses it) BEFORE handover.
  7. PTY-launch the host with a signal-trapped cleanup callback that runs
     EXACTLY ONCE on normal exit, crash, AND force-kill, and never double-cleans.
     ``inject_safety.RestoreError`` is allowed to propagate (a failed restore
     keeps the manifest so a later cleanup retries) per the T021 contract.

Cleanup-correctness (the postmortem-proof surface):
  * The cleanup callback is wrapped in a one-shot guard so it runs at most once.
  * ``pty_launch`` invokes the callback with SIGINT/SIGTERM blocked, so a second
    Ctrl+C cannot interrupt cleanup mid-restore (no double-cleanup).
  * If the host never exits, ``pty_launch`` force-kills after 30 s then runs
    cleanup — the callback still fires exactly once.
  * ``RestoreError`` from ``inject_safety.cleanup`` is NOT swallowed: it
    propagates out of ``run()`` so the operator sees the failed restore and the
    manifest is left in place for a later retry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from z_harness_cli import env_bundle, inject_safety
from z_harness_cli.adapters import registry
from z_harness_cli.adapters.base import KNOWN_COMMANDS, HostAdapter, command_tier


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_project(project: Optional[str]) -> Path:
    """Resolve the PROJECT argument to an absolute path (default: cwd)."""
    if project:
        return Path(project).expanduser().resolve()
    return Path.cwd().resolve()


def _require_git_repo(project: Path) -> None:
    """Enforce the F3 precondition: PROJECT is inside a writable git work tree.

    Raises ``typer.Exit(1)`` with an ``export``-mode hint when PROJECT is not a
    git repo — we must never litter a non-git directory with gitignored config.
    A ``.gitignore`` that does not yet exist is fine (``ensure_gitignored``
    creates it); we only require that the repo root is writable.
    """
    try:
        # _git_root raises RuntimeError if PROJECT is not inside a git work tree.
        git_root = inject_safety._git_root(project)  # noqa: SLF001 — intentional reuse
    except RuntimeError:
        typer.echo(
            f"Error: {project} is not inside a git repository.\n"
            "`z-harness launch` injects gitignored host config and refuses to "
            "litter a non-git directory.\n"
            "Use `z-harness export --in-place` (committed mode) instead, or run "
            "`git init` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # The repo root must be writable so we can create/append .gitignore and the
    # .z-harness/ manifest.  Fail loud rather than crash mid-injection.
    if not _writable(git_root):
        typer.echo(
            f"Error: git repository root {git_root} is not writable; cannot "
            "inject gitignored config.  Use `z-harness export --in-place` "
            "(committed mode) instead.",
            err=True,
        )
        raise typer.Exit(code=1)


def _writable(path: Path) -> bool:
    """Return True if *path* (a directory) is writable by this process."""
    import os

    return os.access(str(path), os.W_OK)


def _recover_orphans(project: Path) -> None:
    """Finish a crash-interrupted restore before injecting anew (T021 note).

    ``detect_orphans`` reports targets still present from a prior run whose
    cleanup never ran.  ``cleanup`` then restores/removes them per the durable
    manifest.  A ``RestoreError`` here is fatal and propagates — we must not
    inject over an unresolved restore (that would risk permanent data loss of
    the user's original file).
    """
    orphans = inject_safety.detect_orphans(project)
    if orphans:
        typer.echo(
            "Recovering injected files from a prior interrupted session:",
            err=True,
        )
        for orphan in orphans:
            typer.echo(f"  - {orphan}", err=True)
        # Let RestoreError propagate (do not swallow): a failed restore leaves
        # the manifest in place so the next launch/cleanup retries.
        inject_safety.cleanup(project)


def _print_fidelity_banner(adapter: HostAdapter, project: Path) -> None:
    """Print the fidelity banner to stderr before handing over the terminal.

    Surfaces the host's fidelity tier and a count of degraded/blocked commands
    from the command-capability matrix so the user knows what they're getting.
    """
    degraded = [c for c in KNOWN_COMMANDS if command_tier(adapter.name, c) == "degraded"]
    blocked = [c for c in KNOWN_COMMANDS if command_tier(adapter.name, c) == "blocked"]

    lines = [
        "─" * 60,
        f"z-harness launch → {adapter.name}  (fidelity: {adapter.fidelity_tier})",
        f"project: {project}",
    ]
    if degraded:
        lines.append(f"degraded commands ({len(degraded)}): {', '.join(degraded)}")
    if blocked:
        lines.append(f"blocked commands ({len(blocked)}): {', '.join(blocked)}")
    if not degraded and not blocked:
        lines.append("all /z-* commands run natively on this host.")
    lines.append("─" * 60)

    typer.echo("\n".join(lines), err=True)


# ---------------------------------------------------------------------------
# One-shot cleanup guard
# ---------------------------------------------------------------------------


class _OnceCleanup:
    """Wrap the injection cleanup so it runs EXACTLY ONCE.

    ``pty_launch`` already invokes the callback with SIGINT/SIGTERM blocked (no
    interruption mid-cleanup).  This guard adds idempotency: even if the callback
    is somehow invoked more than once (e.g. an explicit post-launch call plus the
    finally-block call inside pty_launch), the underlying cleanup runs only once.

    A ``RestoreError`` does NOT mark cleanup as done — it re-raises and leaves the
    guard armed so a later invocation (a trap-fired cleanup after the operator
    fixes the backup) can retry, matching the inject_safety.cleanup() contract.
    """

    def __init__(self, adapter: HostAdapter, injection) -> None:
        self._adapter = adapter
        self._injection = injection
        self._done = False

    def __call__(self) -> None:
        if self._done:
            return
        # Delegate to the adapter's cleanup (which delegates to inject_safety).
        # If it raises RestoreError we deliberately do NOT set _done=True so a
        # subsequent trap-fired cleanup retries the unresolved restore.
        self._adapter.cleanup(self._injection)
        self._done = True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    ctx: typer.Context,
    *,
    host: Optional[str],
    project: Optional[str],
    quiet: bool,
) -> int:
    """Inject + PTY-launch the selected host in PROJECT (Model B).

    Returns the host's exit code.  Raises ``typer.Exit(1)`` for the non-git
    precondition, a clobber refusal, or no installed host.  Lets
    ``inject_safety.RestoreError`` propagate so a failed restore is never
    silently accepted.
    """
    proj = _resolve_project(project)

    # F3 precondition — git repo + writable root (else loud export-mode hint).
    _require_git_repo(proj)

    # Recover any crash-interrupted restore before we inject anew (T021).
    _recover_orphans(proj)

    # Detect / select the host adapter.
    try:
        adapter, detect = registry.select(host=host, interactive=True)
    except registry.UnknownHostError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except registry.NoHostInstalledError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if not detect.installed:
        typer.echo(
            f"Error: host '{adapter.name}' is not installed (no binary on PATH). "
            "Install it and re-run, or pick a different --host.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Build the injected-env bundle.  `launch` is ALWAYS the gitignored/ephemeral
    # path (Model B; SPEC.md:115-116) — there is no --in-place flag here (that
    # belongs to `export`, Model A).  Per D14 (SPEC.md:151-155) an ephemeral
    # launch MUST inject the host-appropriate plugin-root env var
    # (CLAUDE_PLUGIN_ROOT / ANTIGRAVITY_PLUGIN_ROOT), or the spawned host cannot
    # resolve the runtime and every /z-* command fails after the PTY hands over.
    # The SAME "ephemeral" mode string is threaded into both resolve_env_bundle
    # (so the bundle carries the plugin-root) and adapter.inject (so the
    # gitignored config is actually written + the plugin-root lands in the child
    # env).
    mode = "ephemeral"
    try:
        bundle = env_bundle.resolve_env_bundle(proj, adapter.name, mode)
    except RuntimeError as exc:
        typer.echo(
            f"Error: could not resolve the z-harness env bundle: {exc}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Inject (clobber-guarded inside the adapter via preflight_targets).
    try:
        injection = adapter.inject(bundle, mode, proj)
    except inject_safety.ClobberRefused as exc:
        # The exception message already carries the "--force" guidance.
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # Build the full child environment (Injection.env already merges the bundle
    # + any plugin-root over a copy of os.environ inside inject()).
    child_env = injection.env

    # Fidelity banner BEFORE handover (suppressed by --quiet).
    if not quiet:
        _print_fidelity_banner(adapter, proj)

    # Signal-trapped cleanup: pty_launch invokes the callback with SIGINT/SIGTERM
    # blocked, after the child exits (normal, crash, or 30s force-kill).  The
    # one-shot guard guarantees cleanup runs at most once; a RestoreError
    # propagates (manifest left in place for retry).
    cleanup_cb = _OnceCleanup(adapter, injection)

    from z_harness_cli import pty_launch as _pty  # lazy: adapters lazy-import it too

    # We drive the PTY through the adapter's launch() so host-specific argv is
    # owned by the adapter; cleanup is registered on the low-level pty_launch via
    # a thin wrapper so it fires on every exit path.  The adapter's launch()
    # calls pty_launch WITHOUT a cleanup callback, so we patch it in here by
    # wrapping the module function for this one call.
    exit_code = _launch_with_cleanup(_pty, adapter, proj, child_env, cleanup_cb)

    return exit_code


def _launch_with_cleanup(
    pty_mod,
    adapter: HostAdapter,
    project: Path,
    env: dict,
    cleanup_cb,
) -> int:
    """Run ``adapter.launch`` but guarantee *cleanup_cb* fires on every exit.

    The adapter's ``launch()`` calls ``pty_launch(argv, env, cwd)`` without a
    cleanup callback.  To attach our signal-trapped cleanup without editing every
    adapter, we wrap ``pty_launch`` for the duration of this call so the cleanup
    callback is injected into the single real PTY spawn.  ``pty_launch`` runs the
    callback with SIGINT/SIGTERM blocked inside its own ``finally``, so cleanup
    runs exactly once on normal exit, crash, and force-kill.

    A belt-and-suspenders ``finally`` here also calls the (idempotent) one-shot
    cleanup, covering the path where ``adapter.launch`` raises BEFORE reaching
    ``pty_launch`` (e.g. PTYUnsupportedError) — the guard makes the double call
    a no-op on the normal path.
    """
    import sys

    real_pty_launch = pty_mod.pty_launch

    def _wrapped(argv, env, cwd, cleanup=None):
        # Adapters call pty_launch WITHOUT a cleanup callback (cleanup is owned
        # by launch.py via cleanup_cb).  If an adapter ever starts passing its
        # own cleanup we would silently drop it here — fail loud instead so the
        # regression is caught at the call site rather than as a missed restore.
        if cleanup is not None:
            raise ValueError(
                "adapter passed its own cleanup callback to pty_launch; launch.py "
                "owns cleanup wiring and would otherwise drop it silently"
            )
        return real_pty_launch(argv, env, cwd, cleanup=cleanup_cb)

    pty_mod.pty_launch = _wrapped
    try:
        return adapter.launch(project, env)
    finally:
        pty_mod.pty_launch = real_pty_launch
        # Idempotent safety net for the pre-spawn-failure path (adapter.launch
        # raised BEFORE reaching pty_launch, so cleanup never ran).  If
        # pty_launch already ran cleanup, the one-shot guard makes this a no-op.
        #
        # Skip the safety net when a RestoreError is already propagating: that
        # means pty_launch's cleanup ran and re-raised, leaving the manifest in
        # place for retry — re-running here would only duplicate the failure and
        # clobber the original traceback.  Any other in-flight exception (or a
        # clean exit) still gets the safety-net cleanup.
        if not isinstance(sys.exc_info()[1], inject_safety.RestoreError):
            cleanup_cb()
