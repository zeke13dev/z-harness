#!/usr/bin/env python3
"""
scripts/followup_common.py — Shared helpers for the notion-followup-sink subsystem.

Imported by sink-add-helpers.py, sink-status-set-impl.py, and sink-claim-helpers.py
so that utility functions exist in exactly one place.

Exported surface:
  iso_now() -> str
  git_head() -> str                     # raises RuntimeError on failure (canonical T009 version)
  _get_config_bool(key, proj_root) -> bool
  _get_config_str(key, proj_root) -> str
  get_config_batch(keys, proj_root) -> dict[str, object]
  _log_event_sh(event_kind, payload) -> None
  _notion_push_entry(entry, sink_root_path, proj_root) -> None
  _notion_push_entry_bg(entry, sink_root_path, proj_root) -> None
  log_sink_event(sink_root_path, kind, payload) -> None
  log_metrics_event(proj_root, kind, payload) -> None
  project_followups_dir(proj_root) -> Path

  GlobalLockContext(lock_file, holder_id, timeout) — context manager for the
      global cross-tool lock; holder JSON written/cleared under .hb.lock.
  acquire_global_lock(lock_file, holder_id, timeout) -> int
      Acquire without context-manager; returns the open fd.
  release_global_lock(fd, lock_file) -> None
      Release lock fd previously returned by acquire_global_lock.
"""

from __future__ import annotations

import fcntl
import json
import os

# macOS fork-safety workaround: when Python is invoked via `bash script.py`, bash
# has already initialised CoreFoundation; any subsequent fork+exec (subprocess with
# cwd= or env=) in _resolved_base_dir / project_followups_dir causes the forked
# child to abort.  Setting this env var before any subprocess call makes the child
# inherit it and skip the CF abort check.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


# ── timestamps ─────────────────────────────────────────────────────────────────

def iso_now() -> str:
    """Return the current UTC time in ISO-8601 compact format (no fractional seconds)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── git helpers ────────────────────────────────────────────────────────────────

def git_head() -> str:
    """Return the current git HEAD SHA.

    Raises RuntimeError if git is unavailable or HEAD cannot be resolved.
    Callers must treat this as a hard rejection — do NOT fall back to a sentinel.

    Canonical version per T009: the hard-error form in sink-add-helpers.py is
    authoritative.  The sentinel-returning variant that existed in sink-claim-helpers.py
    (returning "unknown" on failure) is intentionally not reproduced here.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git rev-parse HEAD failed (exit {exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    except FileNotFoundError:
        raise RuntimeError(
            "git executable not found; cannot resolve HEAD for capture_head"
        ) from None


# ── config helpers ─────────────────────────────────────────────────────────────

def _get_config_bool(key: str, proj_root: Path) -> bool:
    """Query config.py for a boolean value (best-effort; returns False on error)."""
    config_py = SCRIPT_DIR / "config.py"
    try:
        result = subprocess.run(
            ["python3", str(config_py), "get", key],
            capture_output=True,
            text=True,
            cwd=str(proj_root),
        )
        return result.returncode == 0 and result.stdout.strip().lower() in ("true", "1", "yes")
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def _get_config_str(key: str, proj_root: Path) -> str:
    """Query config.py for a string value (best-effort; returns '' on error)."""
    config_py = SCRIPT_DIR / "config.py"
    try:
        result = subprocess.run(
            ["python3", str(config_py), "get", key],
            capture_output=True,
            text=True,
            cwd=str(proj_root),
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def get_config_batch(keys: list[str], proj_root: Path) -> dict[str, object]:
    """Fetch multiple config keys in a single config.py invocation.

    Returns a dict mapping each key to its resolved value (str, bool, or other
    scalar).  Unknown or erroring keys map to None.  Best-effort: on any
    subprocess failure returns an empty dict (callers fall back to defaults).

    Use this instead of calling _get_config_bool/_get_config_str per-key when
    multiple keys are needed for one operation — it forks config.py exactly once.
    """
    if not keys:
        return {}
    config_py = SCRIPT_DIR / "config.py"
    try:
        result = subprocess.run(
            [sys.executable, str(config_py), "get-batch"] + keys,
            capture_output=True,
            text=True,
            cwd=str(proj_root),
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {}
        return {}
    except (FileNotFoundError, OSError):
        return {}


# ── event logging ──────────────────────────────────────────────────────────────

def _log_event_sh(event_kind: str, payload: dict) -> None:
    """Emit a structured event via scripts/log-event.sh (best-effort)."""
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return
    log_event_sh = SCRIPT_DIR / "log-event.sh"
    if not log_event_sh.exists():
        return
    try:
        subprocess.run(
            ["bash", str(log_event_sh), run_id, event_kind, json.dumps(payload)],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass


def _resolved_base_dir(proj_root: Path) -> Path:
    """Return the resolved artifact base dir via plan-path.sh base_dir.

    Falls back to proj_root/z-harness when plan-path.sh is unavailable or
    fails (best-effort; never raises).  The call is intentionally made at
    invocation time so that a base change (barrier-gated migration) is
    reflected immediately rather than being frozen at process start.
    """
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if plan_path_sh.exists():
        try:
            result = subprocess.run(
                ["bash", str(plan_path_sh), "base_dir"],
                capture_output=True,
                text=True,
                cwd=str(proj_root),
                env={**os.environ, "_Z_HARNESS_RESOLVING_BASE": "1"},
            )
            base = result.stdout.strip()
            if result.returncode == 0 and base:
                return Path(base)
        except (FileNotFoundError, OSError):
            pass
    return proj_root / "z-harness"


def project_followups_dir(proj_root: Path) -> Path:
    """Return the PROJECT sink followups directory, resolved via plan-path.sh.

    Delegates to ``plan-path.sh followups_dir`` so the path honours the full
    5-tier base fallback chain (Z_HARNESS_BASE_DIR, XDG_STATE_HOME, etc.) at
    call time rather than being frozen at import.  The resolution is performed
    with cwd=proj_root so git-common-dir is always found relative to the right
    repo even when the Python process CWD differs.

    Falls back to proj_root/z-harness/followups when plan-path.sh is
    unavailable or fails (best-effort; never raises).

    Do NOT use this for the GLOBAL sink — that is always Path.home() / ".z-harness" / "followups"
    and is intentionally outside the repo.
    """
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if plan_path_sh.exists():
        try:
            result = subprocess.run(
                ["bash", str(plan_path_sh), "followups_dir"],
                capture_output=True,
                text=True,
                cwd=str(proj_root),
                env={**os.environ, "_Z_HARNESS_RESOLVING_BASE": "1"},
            )
            resolved = result.stdout.strip()
            if result.returncode == 0 and resolved:
                return Path(resolved)
        except (FileNotFoundError, OSError):
            pass
    return proj_root / "z-harness" / "followups"


def log_metrics_event(proj_root: Path, kind: str, payload: dict) -> None:
    """Append a structured event to <base>/metrics.jsonl (best-effort).

    The base directory is resolved via plan-path.sh at call time so all event
    writers land under the same resolved base as telemetry and plan artifacts.
    """
    base = _resolved_base_dir(proj_root)
    metrics_path = base / "metrics.jsonl"
    try:
        obj = {"ts": iso_now(), "kind": kind}
        obj.update(payload)
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # metrics write is best-effort; never block main operation


def log_sink_event(sink_root_path: Path, kind: str, payload: dict) -> None:
    """Append a structured event to sink_root/index.jsonl."""
    index_path = sink_root_path / "index.jsonl"
    obj = {"ts": iso_now(), "kind": kind}
    obj.update(payload)
    line = json.dumps(obj, separators=(",", ":")) + "\n"
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


# ── notion push ────────────────────────────────────────────────────────────────

def _notion_push_entry(entry: dict, sink_root_path: Path, proj_root: Path) -> None:
    """
    Best-effort Notion push after local write is committed.  Runs synchronously.

    On success (exit 0): appends notion_synced event with {entry_id, remote_id}.
    On failure (exit 4): appends notion_sync_pending event; logs followup_notion_sync_failure.
    On mismatch (exit 5): logs followup_notion_remote_id_mismatch; treats as soft failure.
    Never raises; never affects caller's exit code.

    Canonical version: unified sha256:-content-hash format from sink-add-helpers.py.
    Uses sys.executable (not hard-coded "python3") for interpreter portability.

    Fetches followup.notion_database_id and followup.notion_token_path in a single
    config.py get-batch invocation (one subprocess fork instead of two).
    """
    entry_id = entry.get("id", "")
    notion_push_py = SCRIPT_DIR / "notion-push.py"

    # Batch-fetch both config keys in one config.py invocation
    cfg = get_config_batch(
        ["followup.notion_database_id", "followup.notion_token_path"],
        proj_root,
    )
    config_database_id = cfg.get("followup.notion_database_id") or ""
    config_token_path = cfg.get("followup.notion_token_path") or ""
    if not isinstance(config_database_id, str):
        config_database_id = ""
    if not isinstance(config_token_path, str):
        config_token_path = ""

    # Write entry to a temp file for notion-push.py
    try:
        fd, entry_tmp = tempfile.mkstemp(suffix=".json", prefix=".notion-entry-")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entry, fh)
    except OSError:
        # os.fdopen may fail before taking ownership of fd; close it defensively
        # (a double-close on the already-wrapped fd is caught here).
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
        return

    cmd = [
        sys.executable, str(notion_push_py),
        f"--entry-json={entry_tmp}",
        f"--config-database-id={config_database_id}",
    ]
    if config_token_path:
        cmd.append(f"--secrets-path={config_token_path}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
        return
    finally:
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass

    if result.returncode == 0:
        # Parse remote_id from stdout
        remote_id = ""
        try:
            out = json.loads(result.stdout)
            remote_id = out.get("remote_id", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        log_sink_event(sink_root_path, "notion_synced", {
            "entry_id": entry_id,
            "remote_id": remote_id,
        })

    elif result.returncode == 4:
        # Push failed — stamp pending flag and log structured failure event
        error_msg = ""
        attempts = 0
        try:
            out = json.loads(result.stdout)
            error_msg = out.get("error", "")
            attempts = out.get("attempts", 0)
        except (json.JSONDecodeError, AttributeError):
            pass
        log_sink_event(sink_root_path, "notion_sync_pending", {
            "entry_id": entry_id,
            "notion_sync_pending": True,
        })
        _log_event_sh("followup_notion_sync_failure", {
            "error": error_msg,
            "entry_id": entry_id,
            "attempts": attempts,
        })
        log_metrics_event(proj_root, "followup_notion_sync_failure", {
            "error": error_msg,
            "entry_id": entry_id,
            "attempts": attempts,
        })

    elif result.returncode == 5:
        # Idempotency mismatch — soft failure, record for reconciler
        error_msg = ""
        try:
            out = json.loads(result.stdout)
            error_msg = out.get("error", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        _log_event_sh("followup_notion_remote_id_mismatch", {
            "entry_id": entry_id,
            "error": error_msg,
        })
        log_metrics_event(proj_root, "followup_notion_remote_id_mismatch", {
            "entry_id": entry_id,
            "error": error_msg,
        })
        log_sink_event(sink_root_path, "notion_sync_pending", {
            "entry_id": entry_id,
            "notion_sync_pending": True,
            "mismatch": True,
        })


def _notion_push_entry_bg(entry: dict, sink_root_path: Path, proj_root: Path) -> None:
    """
    Background (non-blocking) Notion push via a detached child process.

    Launches ``python3 followup_common.py --push-entry ...`` as a detached
    subprocess (start_new_session=True, stdout/stderr redirected to /dev/null
    so the parent is never blocked).  The child handles all event logging.

    When Notion is disabled this is a no-op — callers must gate on
    ``_get_config_bool("followup.notion_enabled", proj_root)`` before calling.

    Failure to spawn the child (OSError, FileNotFoundError) is silently ignored
    so the interactive command always returns promptly.
    """
    entry_id = entry.get("id", "")

    # Serialize entry to a tempfile; the child is responsible for unlinking it.
    try:
        fd, entry_tmp = tempfile.mkstemp(suffix=".json", prefix=".notion-bg-entry-")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entry, fh)
    except OSError:
        # os.fdopen may fail before taking ownership of fd; close it defensively.
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
        return

    try:
        devnull = open(os.devnull, "wb")  # noqa: SIM115 — fd kept open for the duration of the Popen call, closed in finally
    except OSError:
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
        return

    cmd = [
        sys.executable, str(SCRIPT_DIR / "followup_common.py"),
        "--push-entry",
        f"--entry-json={entry_tmp}",
        f"--sink-root={sink_root_path}",
        f"--proj-root={proj_root}",
        "--unlink-entry-json",
    ]
    # Preserve Z_HARNESS_RUN so the child can emit telemetry events
    child_env = {k: v for k, v in os.environ.items()}

    try:
        subprocess.Popen(
            cmd,
            stdout=devnull,
            stderr=devnull,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=child_env,
        )
    except (FileNotFoundError, OSError):
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass
    finally:
        devnull.close()


# ── global lock ────────────────────────────────────────────────────────────────

_GLOBAL_LOCK_DEFAULT_TIMEOUT = 30


def _hb_lock_fd(lock_file: Path) -> int:
    """Open the .hb.lock sentinel for the given lock_file and return an LOCK_EX fd.

    The caller is responsible for closing the returned fd.
    """
    hb_path = Path(str(lock_file) + ".hb.lock")
    hb_fd = os.open(str(hb_path), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(hb_fd, fcntl.LOCK_EX)
    return hb_fd


class GlobalLockContext:
    """Context manager that acquires/releases the global cross-tool lock.

    This is the ONE shared helper for all callers.  Behaviour:

    - Opens ``<lock_file>.flock`` and takes ``LOCK_EX|LOCK_NB``; polls up to
      *timeout* seconds in 0.5 s increments.
    - Serializes the holder-JSON write under ``<lock_file>.hb.lock`` (LOCK_EX)
      so concurrent readers always observe an atomic record — no torn JSON.
    - On holder-write failure: releases the OS flock **and** closes the fd
      before re-raising, so no fd is leaked (CARRY-1b).
    - On ``__exit__``: zeros the holder file under ``.hb.lock``, then releases
      the OS flock. ``os.close`` is called even if ``fcntl.LOCK_UN`` raises
      (CARRY-1b).
    - Raises ``TimeoutError`` on contention timeout (caller maps to exit 5).
    """

    def __init__(
        self,
        lock_file: Path,
        holder_id: str,
        timeout: int = _GLOBAL_LOCK_DEFAULT_TIMEOUT,
    ) -> None:
        self._lock_file = lock_file
        self._holder_id = holder_id
        self._timeout = timeout
        self._acquired = False
        self._fd: int | None = None

    def __enter__(self) -> "GlobalLockContext":
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        sentinel = Path(str(self._lock_file) + ".flock")
        sentinel.touch()

        fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + self._timeout
        # `transferred` guards the outer finally so the fd is closed on every
        # non-success exit (timeout, holder-write failure, BaseException).
        # Ownership transfers to self only on the successful ``return self``.
        transferred = False
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Could not acquire global lock within {self._timeout}s: "
                            f"{self._lock_file}"
                        )
                    time.sleep(0.5)
                    continue

                # OS lock held.  Write holder record under .hb.lock so readers
                # always see an atomic JSON value.  If the write throws we MUST
                # release the OS lock; the outer finally closes the fd.
                hb_fd: int | None = None
                try:
                    hb_fd = _hb_lock_fd(self._lock_file)
                    now = iso_now()
                    holder_record = json.dumps({
                        "holder": self._holder_id,
                        "pid": os.getpid(),
                        "started_at": now,
                        "last_heartbeat": now,
                    }) + "\n"
                    self._lock_file.parent.mkdir(parents=True, exist_ok=True)
                    self._lock_file.write_text(holder_record, encoding="utf-8")
                except BaseException:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                    raise
                finally:
                    if hb_fd is not None:
                        try:
                            os.close(hb_fd)
                        except OSError:
                            pass

                self._fd = fd
                self._acquired = True
                transferred = True
                return self
        finally:
            if not transferred:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def __exit__(self, *_: object) -> None:
        if self._acquired and self._fd is not None:
            # Zero the holder file under .hb.lock so readers see an atomic clear.
            hb_fd: int | None = None
            try:
                hb_fd = _hb_lock_fd(self._lock_file)
                try:
                    self._lock_file.write_text("", encoding="utf-8")
                except OSError:
                    pass
            except OSError:
                # If .hb.lock is unavailable, do NOT clear the holder without it
                # — an unserialized clear is observable as a torn record. Leave
                # the (now stale) holder; the OS-flock check is authoritative.
                pass
            finally:
                if hb_fd is not None:
                    try:
                        os.close(hb_fd)
                    except OSError:
                        pass

            # Always close the fd even if LOCK_UN raises — closing the fd also
            # drops the OS flock.
            try:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            self._acquired = False


def acquire_global_lock(
    lock_file: Path,
    holder_id: str,
    timeout: int = _GLOBAL_LOCK_DEFAULT_TIMEOUT,
) -> int:
    """Acquire the global cross-tool lock; return the open flock-sentinel fd.

    Caller MUST pass the returned fd to :func:`release_global_lock` when done.
    Raises ``TimeoutError`` on contention timeout.
    """
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    sentinel = Path(str(lock_file) + ".flock")
    sentinel.touch()

    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    transferred = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire global lock within {timeout}s: {lock_file}"
                    )
                time.sleep(0.5)
                continue

            # OS lock held.  Write holder record under .hb.lock.
            hb_fd: int | None = None
            try:
                hb_fd = _hb_lock_fd(lock_file)
                now = iso_now()
                holder_record = json.dumps({
                    "holder": holder_id,
                    "pid": os.getpid(),
                    "started_at": now,
                    "last_heartbeat": now,
                }) + "\n"
                lock_file.write_text(holder_record, encoding="utf-8")
            except BaseException:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                raise
            finally:
                if hb_fd is not None:
                    try:
                        os.close(hb_fd)
                    except OSError:
                        pass

            transferred = True
            return fd
    finally:
        if not transferred:
            try:
                os.close(fd)
            except OSError:
                pass


def release_global_lock(fd: int, lock_file: Path) -> None:
    """Release the global cross-tool lock fd returned by :func:`acquire_global_lock`.

    Zeros the holder file under .hb.lock, then releases the OS flock.
    Best-effort: never raises.
    """
    # Zero the holder file under .hb.lock for atomic observation.
    hb_fd: int | None = None
    try:
        hb_fd = _hb_lock_fd(lock_file)
        try:
            lock_file.write_text("", encoding="utf-8")
        except OSError:
            pass
    except OSError:
        # If .hb.lock is unavailable, do NOT clear the holder without it — an
        # unserialized clear is observable as a torn record. Leave the (now
        # stale) holder; the OS-flock check is authoritative.
        pass
    finally:
        if hb_fd is not None:
            try:
                os.close(hb_fd)
            except OSError:
                pass

    # Always close the fd even if LOCK_UN raises.
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except OSError:
        pass


# ── push-entry worker entrypoint ───────────────────────────────────────────────

def _push_entry_worker(argv: list[str]) -> int:
    """
    Entrypoint for the detached background push worker.

    Called as: python3 followup_common.py --push-entry
                 --entry-json=<path>
                 --sink-root=<path>
                 --proj-root=<path>
                 [--unlink-entry-json]

    Loads the entry from ``--entry-json``, runs ``_notion_push_entry`` (which
    does all event logging), then exits.  ``--unlink-entry-json`` removes the
    temp file after loading it.
    """
    entry_json_path = ""
    sink_root_str = ""
    proj_root_str = ""
    unlink_entry_json = False

    for arg in argv:
        if arg.startswith("--entry-json="):
            entry_json_path = arg[len("--entry-json="):]
        elif arg.startswith("--sink-root="):
            sink_root_str = arg[len("--sink-root="):]
        elif arg.startswith("--proj-root="):
            proj_root_str = arg[len("--proj-root="):]
        elif arg == "--unlink-entry-json":
            unlink_entry_json = True
        elif arg == "--push-entry":
            pass  # mode flag already consumed by caller

    if not entry_json_path or not sink_root_str or not proj_root_str:
        sys.exit(1)

    try:
        with open(entry_json_path, encoding="utf-8") as fh:
            entry = json.load(fh)
    except (OSError, json.JSONDecodeError):
        if unlink_entry_json:
            try:
                os.unlink(entry_json_path)
            except OSError:
                pass
        sys.exit(1)

    if unlink_entry_json:
        try:
            os.unlink(entry_json_path)
        except OSError:
            pass

    sink_root_path = Path(sink_root_str)
    proj_root = Path(proj_root_str)
    _notion_push_entry(entry, sink_root_path, proj_root)
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--push-entry":
        sys.exit(_push_entry_worker(args))
    else:
        print(
            "followup_common.py is a library module. "
            "Use --push-entry mode for background push worker.",
            file=sys.stderr,
        )
        sys.exit(2)
