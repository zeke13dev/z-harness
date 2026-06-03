"""Clobber-safe injection + restore-on-cleanup (F1 BLOCKER, T021).

Adapters that write host-native config into a user's repo (``AGENTS.md``,
``.cursor/rules``, ``.agent/*``, gitignored config paths) must never silently
overwrite a file the *user* committed.  This module is the pre-flight / restore
layer that the adapter ``inject()`` / ``cleanup()`` methods delegate to.

Contract (consumed via :class:`Injection.backup_manifest` in
``z_harness_cli/adapters/base.py``):

  * :func:`preflight_targets` — STAT every target.  If a target exists and is
    NOT z-harness-authored (detected via the magic marker, see
    :data:`MAGIC_MARKER`) it is "foreign".  When any target is foreign and
    *force* is False, raise :class:`ClobberRefused` — the launch aborts before
    a single byte is written.  When *force* is True, foreign originals are
    backed up (byte-for-byte) and a restore-capable manifest is persisted.

  * :func:`record_injection` / the manifest at ``<git-root>/.z-harness/
    injected_files.json`` — durable record of (path, sha256, existed?, mtime,
    backup) so :func:`cleanup` can RESTORE the user's originals (not merely
    delete z-harness files).  The manifest lives on disk so cleanup survives a
    crash / force-kill (it ties into the T015 signal trap): a later
    ``doctor``/``cleanup`` re-reads it and finishes the job.

  * :func:`cleanup` — idempotent.  For every recorded target: if a backup
    exists, restore it byte-identical (verified by sha256); otherwise (the
    target did not pre-exist) delete the z-harness-authored file.  Removes the
    manifest only once every entry is resolved.

  * :func:`detect_orphans` — used by ``doctor`` to find half-harnessed state: a
    manifest whose targets are still present (injection never cleaned up).

Pure stdlib: ``hashlib``, ``json``, ``os``, ``shutil``, ``subprocess`` (only to
resolve the git toplevel — same consolidate-not-reinvent rule as env_bundle).
No third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Marker written into z-harness-authored injection targets so a later run can
#: tell *its own* files apart from the user's committed files.  Adapters that
#: emit text config MUST embed this exact substring (typically inside a
#: language-appropriate comment).  Files lacking the marker are treated as
#: foreign and trigger the clobber guard.
MAGIC_MARKER = "z-harness:injected"

#: Per-repo state directory (sibling of the env_bundle .z-harness layout).
_STATE_DIRNAME = ".z-harness"

#: Manifest filename inside the state dir.
_MANIFEST_NAME = "injected_files.json"

#: Manifest schema version — bumped if the on-disk shape changes.
_MANIFEST_SCHEMA = 1


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ClobberRefused(RuntimeError):
    """Raised when injection would overwrite a non-z-harness-authored file.

    Carries the list of foreign target paths so the caller can surface them.
    """

    def __init__(self, foreign: list[Path]) -> None:
        self.foreign = list(foreign)
        joined = ", ".join(str(p) for p in self.foreign)
        super().__init__(
            "Refusing to overwrite pre-existing non-z-harness file(s): "
            f"{joined}. Re-run with --force to back up and restore them."
        )


class RestoreError(RuntimeError):
    """Raised when a backup fails its sha256 integrity check on restore."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """Return the hex sha256 of *path*'s contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_root(project: Path) -> Path:
    """Return the git toplevel for *project*.

    Mirrors the consolidate-not-reinvent rule: shell out to git rather than
    re-implement repo discovery.  Raises ``RuntimeError`` if *project* is not
    inside a git work tree (the F3 precondition is enforced upstream in T015;
    here we fail loud rather than litter a non-git directory).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # git not installed
        raise RuntimeError("git executable not found on PATH") from exc
    top = result.stdout.strip()
    if result.returncode != 0 or not top:
        raise RuntimeError(
            f"{project} is not inside a git work tree "
            "(clobber-safe injection requires a git repo)"
        )
    return Path(top).resolve()


def _state_dir(git_root: Path) -> Path:
    return git_root / _STATE_DIRNAME


def manifest_path(project: Path) -> Path:
    """Return the absolute path to the injection manifest for *project*."""
    return _state_dir(_git_root(project)) / _MANIFEST_NAME


def _is_z_harness_authored(path: Path) -> bool:
    """Return True if *path* carries the z-harness magic marker.

    Reads the file as bytes and looks for the marker substring so binary or
    odd-encoding files don't raise.  A file that cannot be read (permission)
    is treated as foreign (conservative: do not clobber what we can't inspect).
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return MAGIC_MARKER.encode("utf-8") in data


# ---------------------------------------------------------------------------
# Manifest persistence
# ---------------------------------------------------------------------------


def _load_manifest(manifest_file: Path) -> dict:
    if not manifest_file.exists():
        return {"schema": _MANIFEST_SCHEMA, "entries": []}
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupt manifest — treat as empty so cleanup/doctor don't crash, but
        # do not silently drop a real one: a corrupt manifest is itself an
        # orphan signal that doctor will surface (the file still exists).
        return {"schema": _MANIFEST_SCHEMA, "entries": []}
    if not isinstance(data, dict) or "entries" not in data:
        return {"schema": _MANIFEST_SCHEMA, "entries": []}
    return data


def _write_manifest(manifest_file: Path, manifest: dict) -> None:
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_file.with_suffix(manifest_file.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, manifest_file)  # atomic on POSIX


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preflight_targets(
    targets: list[Path],
    project: Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Pre-flight every injection target and persist a restore manifest.

    For each path in *targets*:

      * If it does not exist → recorded as ``existed=False`` (cleanup will
        delete the z-harness file we are about to write; no backup needed).
      * If it exists and IS z-harness-authored (carries :data:`MAGIC_MARKER`)
        → recorded as ``existed=True, authored=True``; safe to overwrite, no
        backup needed (cleanup deletes it).
      * If it exists and is FOREIGN (user file) → it is a clobber candidate.
        When *force* is False this raises :class:`ClobberRefused` *before*
        writing anything.  When *force* is True the original is copied
        byte-for-byte into ``<git-root>/.z-harness/backups/`` and recorded with
        its sha256 + mtime so cleanup can restore it.

    The manifest is written to ``<git-root>/.z-harness/injected_files.json``
    *before* any adapter writes its config, so a crash mid-injection still
    leaves a record cleanup/doctor can act on.

    Returns the ``backup_manifest`` mapping (original-path-str → backup-path)
    suitable for :attr:`Injection.backup_manifest`.  Only foreign overwritten
    files appear in the returned mapping.

    Raises:
        ClobberRefused: a foreign target exists and *force* is False.
        RuntimeError:   *project* is not inside a git work tree.
    """
    git_root = _git_root(project)
    state = _state_dir(git_root)
    backups_dir = state / "backups"
    manifest_file = state / _MANIFEST_NAME

    # First pass: classify every target.  Detect foreign clobbers BEFORE
    # touching the filesystem so refusal is atomic (no partial backups).
    classified: list[tuple[Path, bool, bool]] = []  # (path, existed, foreign)
    foreign: list[Path] = []
    for raw in targets:
        path = Path(raw).resolve()
        existed = path.exists()
        is_foreign = existed and not _is_z_harness_authored(path)
        classified.append((path, existed, is_foreign))
        if is_foreign:
            foreign.append(path)

    if foreign and not force:
        raise ClobberRefused(foreign)

    # Second pass: back up foreign originals (force path) and build entries.
    backups_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    backup_manifest: dict[str, Path] = {}
    for path, existed, is_foreign in classified:
        entry: dict = {
            "path": str(path),
            "existed": existed,
            "authored": existed and not is_foreign,
        }
        if is_foreign:
            # Unique backup name so two targets with the same basename don't
            # collide (e.g. nested AGENTS.md files).
            digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
            backup = backups_dir / f"{path.name}.{digest}.bak"
            try:
                shutil.copy2(path, backup)  # copy2 preserves mtime/mode
                entry["sha256"] = _sha256(backup)
                entry["mtime"] = backup.stat().st_mtime
                entry["backup"] = str(backup)
                backup_manifest[str(path)] = backup
            except FileNotFoundError:
                # TOCTOU: a concurrent process deleted the source between the
                # classification pass and now.  The file is already gone — there
                # is nothing to back up and nothing to restore.  Downgrade to
                # existed=False so cleanup() simply removes whatever z-harness
                # writes here, rather than crashing and orphaning a manifest.
                entry["existed"] = False
                entry["authored"] = False
        entries.append(entry)

    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "created": time.time(),
        "git_root": str(git_root),
        "entries": entries,
    }
    _write_manifest(manifest_file, manifest)

    return backup_manifest


def ensure_gitignored(paths: list[Path], project: Path) -> None:
    """Ensure each path in *paths* is ignored by the repo's ``.gitignore``.

    Appends a z-harness-marked block to ``<git-root>/.gitignore`` for any
    target that is not already ignored (checked via ``git check-ignore``).
    Idempotent: re-running adds nothing once the paths are ignored.

    The F3 precondition (git repo + writable .gitignore) is enforced upstream
    in T015; here we fail loud if the repo is non-git rather than litter it.
    """
    git_root = _git_root(project)
    gitignore = git_root / ".gitignore"

    to_add: list[str] = []
    for raw in paths:
        path = Path(raw).resolve()
        try:
            rel = path.relative_to(git_root)
        except ValueError:
            # Outside the repo — nothing to gitignore here.
            continue
        rel_str = rel.as_posix()
        check = subprocess.run(
            ["git", "-C", str(git_root), "check-ignore", "-q", rel_str],
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:  # not currently ignored
            to_add.append(rel_str)

    if not to_add:
        return

    block_lines = [f"# {MAGIC_MARKER} (ephemeral host config)"]
    block_lines.extend(to_add)
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    sep = "" if existing.endswith("\n") or existing == "" else "\n"
    addition = sep + "\n".join(block_lines) + "\n"
    with open(gitignore, "a", encoding="utf-8") as fh:
        fh.write(addition)


def cleanup(project: Path) -> None:
    """Restore originals / remove z-harness files per the persisted manifest.

    Idempotent: if no manifest exists this is a no-op.  For each recorded
    target:

      * ``existed=True`` with a backup → restore the backup byte-identical
        (sha256-verified) over the z-harness file.
      * otherwise (target did not pre-exist, or was z-harness-authored) →
        delete the z-harness file if present.

    The manifest (and backups dir) are removed only once every entry has been
    resolved, so a crash mid-cleanup leaves a record the next run finishes.

    Raises:
        RestoreError: a backup's contents no longer match the recorded sha256
                      (tampering / partial write), the backup a restore-required
                      entry references has vanished, or the destination fails
                      its post-restore sha256 check — surfaced rather than
                      silently accepting data loss / corrupt data.  When raised,
                      the manifest is NOT removed, so a later cleanup() can
                      retry the unresolved restore.
    """
    try:
        git_root = _git_root(project)
    except RuntimeError:
        # Not a git repo / git gone — nothing we can resolve a manifest from.
        return
    state = _state_dir(git_root)
    manifest_file = state / _MANIFEST_NAME
    if not manifest_file.exists():
        return

    manifest = _load_manifest(manifest_file)
    for entry in manifest.get("entries", []):
        path = Path(entry["path"])
        backup = entry.get("backup")
        if entry.get("existed") and backup:
            backup_path = Path(backup)
            if not backup_path.exists():
                # The manifest says this target pre-existed and must be RESTORED,
                # but the backup is missing (deleted / lost).  We cannot honour
                # "RESTORED on cleanup".  Raise rather than silently leave the
                # tree as-is and then unlink the manifest, which would make the
                # data loss permanent.  Leaving the manifest in place lets a
                # crash-recovery cleanup surface the problem on a later run.
                raise RestoreError(
                    f"Backup for {path} is missing ({backup_path}); cannot "
                    "restore the user's original.  Manifest left in place."
                )
            expected = entry.get("sha256")
            if expected is not None and _sha256(backup_path) != expected:
                raise RestoreError(
                    f"Backup {backup_path} failed sha256 verification; "
                    f"refusing to restore corrupt data over {path}."
                )
            # Atomic restore: copy the backup to a temp file in the SAME dir,
            # verify the destination's contents, then os.replace() into place.
            # A partial/interrupted write (disk full, I/O error) never lands at
            # the target, and a corrupt landing is caught before we move on.
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".zh-restore.tmp")
            try:
                shutil.copy2(backup_path, tmp)
                if expected is not None and _sha256(tmp) != expected:
                    raise RestoreError(
                        f"Restored copy of {path} failed post-write sha256 "
                        "verification (interrupted/corrupt write); manifest "
                        "left in place for retry."
                    )
                os.replace(tmp, path)  # atomic on POSIX
            finally:
                # Drop the temp file if it survived (e.g. the verify raised).
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
        else:
            # Did not pre-exist (or was our own marked file): remove our write.
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    # Resolution complete — drop the manifest and backups.
    backups_dir = state / "backups"
    shutil.rmtree(backups_dir, ignore_errors=True)
    try:
        manifest_file.unlink()
    except FileNotFoundError:
        pass


def detect_orphans(project: Path) -> list[Path]:
    """Return injection targets still present from an un-cleaned-up run.

    Used by ``doctor`` to surface half-harnessed state: a manifest exists and
    one or more of its targets are still on disk (cleanup never ran, e.g. a
    crash before the T015 trap fired).  Returns an empty list when there is no
    manifest or every target has already been cleaned up.
    """
    try:
        git_root = _git_root(project)
    except RuntimeError:
        return []
    manifest_file = _state_dir(git_root) / _MANIFEST_NAME
    if not manifest_file.exists():
        return []
    manifest = _load_manifest(manifest_file)
    orphans: list[Path] = []
    for entry in manifest.get("entries", []):
        path = Path(entry["path"])
        if path.exists():
            orphans.append(path)
    return orphans
