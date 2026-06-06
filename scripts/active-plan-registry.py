#!/usr/bin/env python3
"""
scripts/active-plan-registry.py — Lockless per-run active-plan registry.

INVARIANT (verbatim, repeated from SPEC cross-cutting invariant 1):
  Lockless registry is safe ONLY because overlap is advisory. No code may make
  overlap a hard gate without first replacing lockless delete with
  compare-and-delete or a registry lock.

INVARIANT (verbatim, from SPEC §"Cross-cutting invariant"):
  Wait/lease gates the waiter's OWN run only; it takes no lock; it never writes
  a peer's record (single-writer); every wait has a finite budget + loud timeout
  (overlap is never a hard gate); the holder is never preempted. The lockless
  registry stays safe because lease contention remains advisory and
  self-gating — F1–F5 below are the load-bearing details.

Each run owns exactly one record: <active_plans_dir>/<run-id>.json.
Writes are atomic (tmpfile in same dir + os.replace). No global lock is taken.
The per-entry→global lock ordering in followup_common.py is NOT affected.

Subcommands:
  session-id
      Print a stable session id for the current shell session.
      Returns $Z_HARNESS_SESSION_ID if set (stable across repeated calls within
      the same run). Otherwise derives <ppid>-<start_epoch> from the parent
      shell's PID and its start time (so repeated calls from the same session
      return the same value). Output is always a safe token with no spaces.
      Callers should export Z_HARNESS_SESSION_ID="$(registry.py session-id)"
      once at run start so all later calls (register, heartbeat, etc.) reuse it.

  register --run-id ID --slug S --command C --phase P [--session SID]
      Write <active>/<ID>.json atomically. Validate ID is a safe basename.
      Populate schema v1. Idempotent (re-register overwrites own record).
      Emit plan_registered via log-event.sh.

  heartbeat --run-id ID [--phase P] [--current-task T]
            [--status running|paused]
      Read own record, update last_heartbeat/phase/current_task, atomic rewrite.
      If the record is ABSENT (not registered, or already deregistered/reaped),
      emit registry_error(op:heartbeat, reason:missing_record) and return 0
      (no-op). Does NOT fabricate a zombie record with empty fields.
      NON-FATAL on error. SELF-LOGS: on an internal error it emits a registry_error
      event (op:"heartbeat") via log-event.sh before returning 0, so the non-fatal
      failure is still observable in telemetry (a caller `|| log` would be dead
      code since this always returns 0).

  update-scope --run-id ID --scope-json FILE
      Merge a scope array [{path, confidence, reason}] into the record.
      Paths are stored as-is (caller is responsible for repo-relative normalisation).
      NON-FATAL on error. SELF-LOGS a registry_error event (op:"update-scope")
      on any internal error before returning 0 (same rationale as heartbeat).

  list [--json]
      Scan <active>/*.json. Skip torn/partial files silently (try/except json).
      Print records in human-readable or JSON form.

  overlaps --run-id ID [--strict] [--scope-json FILE]
      Compute path intersection of ID's scope against every other live record's scope.
      Per overlapping peer: shared paths, min-confidence pair, actionability fields.
      Exit 0 = no overlap; 10 = advisory overlap; 20 = blocking overlap (only when
      --strict or Z_HARNESS_STRICT_OVERLAP=1 AND explicit×explicit exact path match).
      Same run-id OR same session_id → ignored (not an overlap with self).
      Stale peers → included but marked non-blocking.
      Emits scope_overlap_detected (with peers) or active_plan_scan_complete.

  reap
      Conservative reaper. Deletes a record ONLY if:
        (a) host == THIS host AND pid is dead (os.kill(pid, 0) raises ESRCH), OR
        (b) now - last_heartbeat > Z_HARNESS_REGISTRY_STALE_SECS (default 1800)
            by a 2× margin (i.e. > 3600s) AND the record does NOT have a live local
            pid (i.e. remote/unknown-host records, or local records without a pid).
      Live-local-pid carve-out: if host == THIS host AND pid is alive AND past the
      2× margin → mark status:"stale" (do NOT delete). Deletion is deferred until
      the pid dies and case (a) fires on a subsequent reap cycle.
      Otherwise if merely past the 1× threshold AND host is unknown/remote (not this
      host) → set status:"stale" via atomic rewrite (do NOT delete).
      unlink is wrapped in try/except FileNotFoundError so two reapers racing on the
      same record do not crash.
      REAPER EXCEPTION (single-writer invariant): reap is the ONE allowed cross-record
      write — marking a PEER's record status:"stale". This write is atomic + tolerant of
      the owner concurrently updating (last-writer-wins for an advisory stale flag; if
      the owner heartbeats after, it overwrites stale back to running, which is correct).
      Emits plan_reaped / plan_marked_stale. NON-FATAL overall.

  deregister --run-id ID [--status complete|aborted]
      Atomically unlink <active>/<ID>.json.
      Emit plan_deregistered. NON-FATAL on error. SELF-LOGS a registry_error
      event (op:"deregister") on a genuine internal error (unsafe id, unresolvable
      active_plans_dir, or a non-FileNotFoundError OSError on unlink) before
      returning 0. A FileNotFoundError on unlink (record already gone) is benign
      and does NOT emit an error.

  claim --run-id ID --paths p1,p2[,...]
      Stage and claim per-file leases for a run. Best-effort (advisory, never
      hard-fails). Stages paths in memory, performs a check-after-claim (F2) by
      re-reading all peer records, applies run_id lexicographic tiebreak: a live,
      lease-capable peer with a lower run_id (senior) wins the path → caller
      concedes. Multi-senior: concedes to the lowest-run_id (eldest) senior.
      Persists only the won set into held_paths (BLOCKER-1: loser record MUST NOT
      contain the conceded path). Emits lease_claimed. Z_HARNESS_REGISTRY_ENABLED=0
      → {"claimed":[],"conceded":[]}, exit 0.
      Stdout: JSON {"claimed":[...], "conceded":[{"path","holder_run_id"}]}.

  release --run-id ID (--paths p1,p2 | --all)
      Remove the named paths (or all paths) from own held_paths. Best-effort
      (advisory, never hard-fails callers). --paths and --all are mutually
      exclusive; exactly one is required. Atomic write. Refreshes last_heartbeat.
      A named path not currently held is a silent no-op (no error). --all empties
      held_paths entirely. Emits lease_released {run_id, paths} where paths is the
      set of entries actually removed. Self-logs registry_error(op:release) on any
      internal error before returning 0. Z_HARNESS_REGISTRY_ENABLED=0 → silent
      no-op, exit 0. NON-FATAL — always returns 0.

  wait-for --run-id ID --on RUNID[,...] [--paths p1,p2]
      Park the current run behind one or more senior peers (run_id < mine) until
      their records clear (gone / complete / aborted / stale) or the budget expires.
      Eligibility: non-senior or absent targets are dropped immediately; if none
      remain, exits 0 (nothing_to_wait_on). Poll loop every
      Z_HARNESS_WAIT_POLL_SECS (30): sets status=paused + waiting_on in a single
      atomic write (preserving held_paths), runs reap, rechecks targets, adds any
      NEW senior holders of --paths (TOCTOU re-scan; junior claimers ignored).
      All targets cleared → clear waiting_on, status=running, exit 0 (cleared).
      Budget expired → clear waiting_on, status=running, emit LOUD wait_timeout,
      exit 10. SIGINT/SIGTERM → clear waiting_on, status=running,
      wait_interrupted, exit 130. waiting_on cleared on EVERY exit path (finally).
      Z_HARNESS_REGISTRY_ENABLED=0 → silent no-op, exit 0.

Exit codes:
  0   — success (also: heartbeat / update-scope / deregister / reap failure — NON-FATAL)
  2   — usage / argument error
  3   — register failure (LOUD; callers MUST gate on this)
  10  — overlaps: advisory overlap found; wait-for: budget/timeout expired (LOUD)
  20  — overlaps: blocking overlap (strict mode + explicit×explicit exact match)
  130 — wait-for: SIGINT/SIGTERM received
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import signal

# macOS fork-safety workaround: when Python is invoked via `bash script.py`, bash
# has already initialised CoreFoundation; any subsequent fork+exec (subprocess with
# cwd= or env=) causes the forked child to abort.  Setting this env var before any
# subprocess call makes the child inherit it and skip the CF abort check.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Default stale margin in seconds. Overridable via Z_HARNESS_REGISTRY_STALE_SECS.
_DEFAULT_STALE_SECS = 1800

# Wait-for knob defaults — read inline from os.environ at use-site.
# ENV_ONLY_KNOBS entries in config.py list all five for inspect-all discoverability.
_DEFAULT_WAIT_POLL_SECS = 30
_DEFAULT_AUTO_WAIT_BUDGET_SECS = 300
_DEFAULT_EXPLICIT_WAIT_TIMEOUT_SECS = 1800
# Z_HARNESS_AUTO_WAIT: 1 = auto mode (budget-limited), 0 = explicit-timeout mode.
_DEFAULT_AUTO_WAIT = 1
# Z_HARNESS_WAIT_REQUIRE_MERGE: reserved for T009 (branch-ancestor cleared signal).
# Default 0 = deregister-only (current behaviour). Read inline so the constant is
# present and the knob is visible in config.py inspect-all output.
_DEFAULT_WAIT_REQUIRE_MERGE = 0


def _stale_secs() -> int:
    """Return the stale threshold in seconds from env or default."""
    try:
        return int(os.environ.get("Z_HARNESS_REGISTRY_STALE_SECS", _DEFAULT_STALE_SECS))
    except ValueError:
        return _DEFAULT_STALE_SECS


# Confidence ordering: explicit > inferred > broad > unknown (higher index = higher confidence).
_CONFIDENCE_ORDER = ["unknown", "broad", "inferred", "explicit"]


def _confidence_rank(conf: str) -> int:
    """Return a numeric rank for a confidence string (higher = more confident)."""
    try:
        return _CONFIDENCE_ORDER.index(conf)
    except ValueError:
        return 0  # unknown rank for unrecognised values


def _min_confidence(conf_a: str, conf_b: str) -> str:
    """Return the weaker (lower-confidence) of two confidence strings."""
    if _confidence_rank(conf_a) <= _confidence_rank(conf_b):
        return conf_a
    return conf_b

SCRIPT_DIR = Path(__file__).resolve().parent

# ── safe basename ──────────────────────────────────────────────────────────────

_SAFE_BASENAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')


def _is_safe_basename(name: str) -> bool:
    """Return True iff name is safe to use as a filename component.

    Rejects: empty string, leading dash, path separators, double-dot sequences.
    Accepts: letters, digits, dot, underscore, hyphen — and only when the whole
    name matches ^[A-Za-z0-9._-]+$ AND does not start with '-' AND does not
    contain '..'.
    """
    if not name:
        return False
    if name.startswith('-'):
        return False
    if '..' in name:
        return False
    if '/' in name or os.sep in name:
        return False
    return bool(_SAFE_BASENAME_RE.match(name))


# ── timestamps ─────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── active_plans_dir via plan-path.sh ─────────────────────────────────────────

def _active_plans_dir() -> Path:
    """Resolve active_plans_dir() by shelling out to plan-path.sh.

    Propagates failures loudly — a non-zero exit from plan-path.sh is a hard
    failure (SPEC invariant 4: base resolution never fails silently mid-run).
    Raises RuntimeError if the resolved path is empty or the shell call fails.
    """
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if not plan_path_sh.exists():
        raise RuntimeError(
            f"plan-path.sh not found at {plan_path_sh}; cannot resolve active_plans_dir"
        )
    try:
        result = subprocess.run(
            ["bash", str(plan_path_sh), "active_plans_dir"],
            capture_output=True,
            text=True,
            cwd=str(SCRIPT_DIR.parent),  # repo root — plan-path.sh expects to be run from repo
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"bash not found: {exc}") from exc
    if result.returncode != 0:
        # plan-path.sh already printed a FATAL message to stderr; propagate it.
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"plan-path.sh active_plans_dir failed (exit {result.returncode})"
            + (f": {stderr}" if stderr else "")
        )
    resolved = result.stdout.strip()
    if not resolved:
        raise RuntimeError(
            "plan-path.sh active_plans_dir returned empty path — refusing to continue"
        )
    return Path(resolved)


# ── git helpers (degrade gracefully when not in a git repo) ───────────────────

def _git_field(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stripped stdout. Returns '' on any failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd or str(SCRIPT_DIR.parent),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


# ── event emission (best-effort) ───────────────────────────────────────────────

def _emit_event(run_id: str, kind: str, payload: dict) -> None:
    """Emit a structured event via log-event.sh (best-effort; never raises)."""
    log_event_sh = SCRIPT_DIR / "log-event.sh"
    if not log_event_sh.exists():
        return
    try:
        subprocess.run(
            ["bash", str(log_event_sh), run_id, kind, json.dumps(payload)],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass


# ── atomic write helpers ───────────────────────────────────────────────────────

def _atomic_write(path: Path, record: dict) -> None:
    """Write record atomically to path via tmpfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_path = str(path.parent)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".tmp-registry-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_read(path: Path) -> dict | None:
    """Read a JSON record from path. Returns None if file is missing or malformed."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


# ── record factory ─────────────────────────────────────────────────────────────

def _is_lease_capable(rec: dict) -> bool:
    """Return True iff rec is a schema-v2 record with the held_paths field present.

    A record is lease-capable ONLY when schema_version >= 2 AND held_paths is
    explicitly present. Missing held_paths is NEVER interpreted as "holds nothing"
    — absence means the record pre-dates the lease schema and its lease state is
    unknown (lease-incapable). Such peers contribute to soft scope overlap only,
    never to held-path waiting.

    Type-safe: a non-numeric schema_version (e.g. string "2") is treated as
    lease-incapable rather than raising TypeError.
    """
    raw_version = rec.get("schema_version", 1)
    try:
        if int(raw_version) < 2:
            return False
    except (TypeError, ValueError):
        return False  # non-conforming schema_version → treat as lease-incapable
    return "held_paths" in rec


def _is_senior(peer_run_id: str, my_run_id: str) -> bool:
    """Return True iff peer_run_id is lexicographically less than my_run_id.

    This is the canonical seniority predicate for the registry: a lower run_id
    was issued earlier (total-order by lexicographic string comparison) and
    therefore takes priority in held-path tiebreaks.

    Type-safety: if either argument is not a str, return False — a non-conforming
    run_id is treated as not-senior and never causes a TypeError at the call site.

    NOTE: ``started_at`` is display-only throughout the module. It MUST NOT be
    used for ordering comparisons; this function is the single authoritative
    ordering predicate.

    Contract: matches the inline comparison in cmd_claim exactly —
    ``peer_run_id < my_run_id`` — so callers can substitute _is_senior without
    any behaviour change.
    """
    if not isinstance(peer_run_id, str) or not isinstance(my_run_id, str):
        return False
    return peer_run_id < my_run_id


def _set_waiting_on(run_id: str, targets: list[str], status: str | None = None) -> None:
    """Atomically set (or clear) the waiting_on field of run_id's own record.

    Performs a read-modify-write on <active_plans_dir>/<run_id>.json,
    preserving held_paths and all other fields, and refreshing last_heartbeat.
    Passing an empty list clears waiting_on (the caller is no longer parked).

    When status is provided (e.g. "paused" or "running"), it is set in the same
    single atomic write — guaranteeing that status + waiting_on change together
    with no window where a peer reads an inconsistent state (MINOR-1).

    Non-fatal: on any internal error, emits a registry_error event
    (op:"set_waiting_on") and returns silently — callers on every wait-for
    exit path rely on this never raising.

    Single-writer invariant: only the process that owns run_id should call this.
    """
    if not _is_safe_basename(run_id):
        _emit_event(run_id, "registry_error", {
            "op": "set_waiting_on", "run_id": run_id, "reason": "unsafe_run_id",
        })
        return

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "set_waiting_on", "run_id": run_id,
            "reason": "active_plans_dir", "error": str(exc),
        })
        return

    record_path = active_dir / f"{run_id}.json"
    try:
        record = _atomic_read(record_path)
        if not isinstance(record, dict):
            _emit_event(run_id, "registry_error", {
                "op": "set_waiting_on", "run_id": run_id, "reason": "missing_record",
            })
            return
        record["waiting_on"] = list(targets)
        record["last_heartbeat"] = _iso_now()
        if status is not None:
            record["status"] = status
        _atomic_write(record_path, record)
    except OSError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "set_waiting_on", "run_id": run_id,
            "reason": "write_failed", "error": str(exc),
        })


def _build_record(
    *,
    run_id: str,
    slug: str,
    command: str,
    phase: str,
    session_id: str = "",
) -> dict:
    """Build a fresh schema-v2 record populated with current host/git state."""
    now = _iso_now()
    repo_root = _git_field(["rev-parse", "--show-toplevel"])
    git_common_dir = _git_field(["rev-parse", "--git-common-dir"])
    # Normalise git-common-dir to an absolute path.
    if git_common_dir and not os.path.isabs(git_common_dir):
        git_common_dir = os.path.abspath(
            os.path.join(repo_root or str(SCRIPT_DIR.parent), git_common_dir)
        )
    worktree_path = repo_root  # same as repo_root for non-worktree; will differ for worktrees
    branch = _git_field(["rev-parse", "--abbrev-ref", "HEAD"])
    # repo_id: derive from plan-path.sh z_harness_repo_id (best-effort)
    repo_id = ""
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if plan_path_sh.exists():
        try:
            result = subprocess.run(
                ["bash", str(plan_path_sh), "z_harness_repo_id"],
                capture_output=True,
                text=True,
                cwd=repo_root or str(SCRIPT_DIR.parent),
            )
            if result.returncode == 0:
                repo_id = result.stdout.strip()
        except OSError:
            pass

    return {
        "schema_version": 2,
        "run_id": run_id,
        "session_id": session_id,
        "slug": slug,
        "command": command,
        "command_version": "",  # caller may populate via version.sh
        "phase": phase,
        "status": "running",
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "repo_id": repo_id,
        "repo_root": repo_root,
        "git_common_dir": git_common_dir,
        "worktree_path": worktree_path,
        "branch": branch,
        "started_at": now,
        "last_heartbeat": now,
        "current_task": "",
        "scope": [],
        "held_paths": [],
        "waiting_on": [],
    }


# ── session id ────────────────────────────────────────────────────────────────

def _derive_session_id() -> str:
    """Derive a stable session id from the parent process.

    Strategy: on Linux, read PPID start time from /proc to get a stable token
    across repeated calls from the same shell session.  On macOS (no /proc),
    fall back immediately to a pure-Python ``<ppid>-<epoch>`` token — no
    subprocess is spawned on macOS, eliminating the CoreFoundation fork-safety
    crash surface entirely.

    The Setup blocks export Z_HARNESS_SESSION_ID once at run start, so
    cross-independent-call stability is not required for the macOS fallback.

    Returns a safe token with no spaces, suitable for use in filenames and
    JSON fields.
    """
    ppid = os.getppid()

    # Try to read the parent's start time from /proc/<ppid>/stat (Linux only).
    proc_stat = Path(f"/proc/{ppid}/stat")
    if proc_stat.exists():
        try:
            parts = proc_stat.read_text(encoding="utf-8").split()
            # Field 22 (0-indexed: 21) is starttime in clock ticks since boot.
            start_ticks = int(parts[21])
            # Convert to epoch seconds via boot time from /proc/stat.
            boot_time = 0
            btime_path = Path("/proc/stat")
            if btime_path.exists():
                for line in btime_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("btime "):
                        boot_time = int(line.split()[1])
                        break
            if boot_time:
                # Use os.sysconf (pure Python, no subprocess) to avoid fork-safety crash.
                try:
                    clk_tck = os.sysconf("SC_CLK_TCK")
                except (OSError, ValueError):
                    clk_tck = 100  # safe default when sysconf unavailable
                start_epoch = boot_time + (start_ticks // clk_tck)
                return f"{ppid}-{start_epoch}"
        except (IndexError, ValueError, OSError):
            pass

    # macOS / BSD: no /proc, so skip all subprocess calls (they cause CoreFoundation
    # fork-safety crashes when invoked via `bash script.py`).  Fall back to a
    # pure-Python token: <ppid>-<current_epoch>.  This is less stable across repeated
    # standalone calls but is fine in practice because callers export
    # Z_HARNESS_SESSION_ID once at run start, making later calls read the env var
    # instead of deriving a new value.
    return f"{ppid}-{int(time.time())}"


def cmd_session_id(args: argparse.Namespace) -> int:  # noqa: ARG001
    """session-id subcommand.

    Prints a stable session id token for the current shell session.
    If $Z_HARNESS_SESSION_ID is already set, echoes it unchanged (stable
    across repeated calls within a run). Otherwise derives one from the
    parent shell's PID + start time and prints it.

    Always exits 0. Output is a single line with no trailing spaces.
    """
    sid = os.environ.get("Z_HARNESS_SESSION_ID", "").strip()
    if not sid:
        sid = _derive_session_id()
    print(sid)
    return 0


# ── subcommand implementations ─────────────────────────────────────────────────

def cmd_register(args: argparse.Namespace) -> int:
    """register subcommand. Returns exit code (0 = ok, 3 = failure)."""
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        print(
            f"[active-plan-registry] ERROR: run-id {run_id!r} is not a safe basename "
            "(must match ^[A-Za-z0-9._-]+$, no leading dash, no '..', no '/').",
            file=sys.stderr,
        )
        return 3

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] FATAL: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        return 3

    record_path = active_dir / f"{run_id}.json"

    try:
        record = _build_record(
            run_id=run_id,
            slug=args.slug,
            command=args.command,
            phase=args.phase,
            session_id=getattr(args, "session", "") or "",
        )
        _atomic_write(record_path, record)
    except OSError as exc:
        print(
            f"[active-plan-registry] FATAL: register failed for run-id {run_id!r}: {exc}",
            file=sys.stderr,
        )
        return 3

    _emit_event(run_id, "plan_registered", {
        "run_id": run_id,
        "slug": record["slug"],
        "command": record["command"],
        "phase": record["phase"],
    })
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    """heartbeat subcommand. NON-FATAL — always returns 0.

    Self-logging: because this subcommand always returns 0 by design, a caller's
    ``|| log registry_error`` would be dead code. Instead, on any caught internal
    error we emit a ``registry_error`` event (op:"heartbeat") via log-event.sh
    BEFORE returning 0, so the failure is still observable in telemetry.

    IMPORTANT: heartbeat does NOT fabricate a record when the target <run-id>.json
    is absent. If the file is missing (never registered, or already reaped/deregistered),
    emit a registry_error(reason:missing_record) and return 0 (no-op). Recreating
    with empty fields is worse than skipping: empty slug/session/repo_id pollutes
    other sessions' overlap detection with phantom zombie records.
    """
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        _emit_event(run_id, "registry_error", {
            "op": "heartbeat", "run_id": run_id, "reason": "unsafe_run_id",
        })
        return 0  # non-fatal; invalid id would be a bug in the caller

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "heartbeat", "run_id": run_id, "reason": "active_plans_dir", "error": str(exc),
        })
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    try:
        record = _atomic_read(record_path)
        if record is None:
            # Record is absent (never registered, or already reaped/deregistered).
            # Do NOT fabricate a zombie record with empty fields — that would pollute
            # other sessions' overlap detection. Emit a registry_error and return 0.
            _emit_event(run_id, "registry_error", {
                "op": "heartbeat", "run_id": run_id, "reason": "missing_record",
            })
            return 0  # non-fatal no-op
        record["last_heartbeat"] = _iso_now()
        if getattr(args, "phase", None):
            record["phase"] = args.phase
        if getattr(args, "current_task", None) is not None:
            record["current_task"] = args.current_task
        if getattr(args, "status", None):
            record["status"] = args.status
        _atomic_write(record_path, record)
    except OSError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "heartbeat", "run_id": run_id, "reason": "write_failed", "error": str(exc),
        })
        # non-fatal — still return 0
    return 0


def cmd_update_scope(args: argparse.Namespace) -> int:
    """update-scope subcommand. NON-FATAL — always returns 0.

    Self-logging: same rationale as ``cmd_heartbeat`` — a ``|| log`` from the
    caller is dead code because this returns 0 by design, so an internal error
    self-emits a ``registry_error`` event (op:"update-scope") before returning.
    """
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        _emit_event(run_id, "registry_error", {
            "op": "update-scope", "run_id": run_id, "reason": "unsafe_run_id",
        })
        return 0  # non-fatal

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "update-scope", "run_id": run_id, "reason": "active_plans_dir", "error": str(exc),
        })
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    try:
        scope_path = Path(args.scope_json)
        with scope_path.open("r", encoding="utf-8") as fh:
            new_scope = json.load(fh)
        if not isinstance(new_scope, list):
            _emit_event(run_id, "registry_error", {
                "op": "update-scope", "run_id": run_id, "reason": "scope_not_a_list",
            })
            return 0  # non-fatal: malformed scope is a caller bug

        record = _atomic_read(record_path)
        if record is None:
            _emit_event(run_id, "registry_error", {
                "op": "update-scope", "run_id": run_id, "reason": "record_missing",
            })
            return 0  # record gone — non-fatal

        record["scope"] = new_scope
        record["last_heartbeat"] = _iso_now()
        _atomic_write(record_path, record)
    except (OSError, json.JSONDecodeError) as exc:
        _emit_event(run_id, "registry_error", {
            "op": "update-scope", "run_id": run_id, "reason": "read_or_write_failed", "error": str(exc),
        })
        # non-fatal — still return 0
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """list subcommand. Returns 0 always."""
    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] WARNING: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        if getattr(args, "json", False):
            print("[]")
        return 0

    records: list[dict] = []
    if active_dir.is_dir():
        for p in sorted(active_dir.glob("*.json")):
            rec = _atomic_read(p)
            if rec is None:
                continue  # skip torn/partial files
            records.append(rec)

    if getattr(args, "json", False):
        print(json.dumps(records, indent=2))
    else:
        if not records:
            print("(no active plans)")
            return 0
        for rec in records:
            run_id = rec.get("run_id", "?")
            slug = rec.get("slug", "?")
            command = rec.get("command", "?")
            phase = rec.get("phase", "?")
            status = rec.get("status", "?")
            branch = rec.get("branch", "?")
            task = rec.get("current_task", "")
            hb = rec.get("last_heartbeat", "?")
            task_str = f"  task={task}" if task else ""
            print(
                f"{run_id}  slug={slug}  cmd={command}  phase={phase}  "
                f"status={status}  branch={branch}{task_str}  hb={hb}"
            )
    return 0


def cmd_deregister(args: argparse.Namespace) -> int:
    """deregister subcommand. NON-FATAL — always returns 0.

    Self-logging: same rationale as ``cmd_heartbeat`` — on a genuine internal
    error (unresolvable active_plans_dir, unsafe id, or an OSError on unlink that
    is NOT FileNotFoundError) we emit a ``registry_error`` event (op:"deregister")
    before returning 0. A FileNotFoundError on unlink (record already gone) is
    benign and does NOT emit an error.
    """
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        _emit_event(run_id, "registry_error", {
            "op": "deregister", "run_id": run_id, "reason": "unsafe_run_id",
        })
        return 0  # non-fatal

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "deregister", "run_id": run_id, "reason": "active_plans_dir", "error": str(exc),
        })
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"
    final_status = getattr(args, "status", "complete") or "complete"

    try:
        # Read record before deletion so we can include slug in the event.
        record = _atomic_read(record_path)
        record_path.unlink()
    except FileNotFoundError:
        record = None  # already gone — benign (no registry_error)
    except OSError as exc:
        record = None  # non-fatal, but a genuine error → self-log
        _emit_event(run_id, "registry_error", {
            "op": "deregister", "run_id": run_id, "reason": "unlink_failed", "error": str(exc),
        })

    _emit_event(run_id, "plan_deregistered", {
        "run_id": run_id,
        "slug": (record or {}).get("slug", ""),
        "status": final_status,
    })
    return 0


# ── claim subcommand ──────────────────────────────────────────────────────────

def cmd_claim(args: argparse.Namespace) -> int:
    """claim subcommand.

    Behaviour: best-effort (advisory, never hard-fails callers). Always exits 0.

    Stages the requested paths in memory, performs a check-after-claim (F2) by
    re-reading all peer records, applies the run_id lexicographic tiebreak to
    resolve contention, then persists only the won set into the caller's own
    record. A tiebreak loser's persisted held_paths MUST NOT contain the conceded
    path (BLOCKER-1).

    Stdout: JSON {"claimed":[...], "conceded":[{"path","holder_run_id"}]}.
    Z_HARNESS_REGISTRY_ENABLED=0: print {"claimed":[],"conceded":[]}, exit 0.
    """
    run_id = args.run_id

    # Validate run_id early so error messages are coherent.
    if not _is_safe_basename(run_id):
        print(
            f"[active-plan-registry] ERROR claim: run-id {run_id!r} is not a safe basename.",
            file=sys.stderr,
        )
        # Still emit the silent no-op JSON so callers can parse stdout.
        print(json.dumps({"claimed": [], "conceded": []}))
        return 0  # best-effort — advisory, never hard-fails

    # Parse and deduplicate requested paths.
    raw_paths: list[str] = args.paths.split(",") if args.paths else []
    # Deduplicate while preserving first occurrence order.
    seen: set[str] = set()
    staged_paths: list[str] = []
    for p in raw_paths:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            staged_paths.append(p)

    if not staged_paths:
        # Nothing to claim.
        print(json.dumps({"claimed": [], "conceded": []}))
        return 0

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "claim", "run_id": run_id, "reason": "active_plans_dir", "error": str(exc),
        })
        print(json.dumps({"claimed": [], "conceded": []}))
        return 0  # best-effort

    record_path = active_dir / f"{run_id}.json"
    stale_threshold = _stale_secs()
    now_ts = _iso_now()

    try:
        # ── Check-after-claim (F2): scan peers for held-path conflicts ─────────
        # For each staged path, find the eldest senior (lowest run_id) that holds
        # it and is a LIVE, lease-capable peer.  "LIVE" = not stale.
        # Seniority: peer_run_id < my_run_id (lexicographic) → peer is senior.

        # Map: path → lowest-run_id senior holding it (None if no senior).
        path_to_eldest_senior: dict[str, str] = {}

        if active_dir.is_dir():
            for p in sorted(active_dir.glob("*.json")):
                rec = _atomic_read(p)
                # _atomic_read returns None on missing/malformed, but json.load can
                # return a non-dict (list, str, …) for a valid-JSON but wrong-schema file.
                if not isinstance(rec, dict):
                    continue  # malformed record — skip silently

                peer_run_id = rec.get("run_id", "")
                # Guard: peer_run_id must be a non-empty string for safe comparison.
                if not isinstance(peer_run_id, str) or not peer_run_id or peer_run_id == run_id:
                    continue  # skip self or malformed id

                # Skip non-lease-capable peers (schema < 2 or missing held_paths).
                # _is_lease_capable already handles non-conforming records safely when
                # rec is a dict; the isinstance(rec, dict) guard above ensures that.
                if not _is_lease_capable(rec):
                    continue

                # Skip stale peers.
                is_stale = (rec.get("status") == "stale") or _is_stale(rec, stale_threshold)
                if is_stale:
                    continue

                # Only consider SENIOR peers (lexicographic: peer_run_id < my run_id).
                # _is_senior() is the canonical predicate for this comparison; it is
                # kept inline here for clarity but must match _is_senior exactly.
                if not (peer_run_id < run_id):
                    continue  # peer is junior — I keep my claim against juniors

                # Collect paths this peer holds; guard against non-list held_paths.
                peer_held_raw = rec.get("held_paths", [])
                peer_held: list = peer_held_raw if isinstance(peer_held_raw, list) else []
                peer_held_paths: set[str] = {
                    entry["path"] for entry in peer_held if isinstance(entry, dict) and "path" in entry
                }

                for staged in staged_paths:
                    if staged in peer_held_paths:
                        # This senior holds this path. Track the eldest (lowest run_id).
                        # _is_senior() is the canonical predicate; kept inline to match
                        # the surrounding filter above without a second function call.
                        current_holder = path_to_eldest_senior.get(staged)
                        if current_holder is None or peer_run_id < current_holder:
                            path_to_eldest_senior[staged] = peer_run_id

        # ── Partition staged paths into won set and conceded set ───────────────
        conceded_list: list[dict] = []
        won_paths: list[str] = []

        for staged in staged_paths:
            holder = path_to_eldest_senior.get(staged)
            if holder is not None:
                # A senior holds this path — concede it.
                conceded_list.append({"path": staged, "holder_run_id": holder})
            else:
                won_paths.append(staged)

        # ── Persist the won set only (BLOCKER-1) ──────────────────────────────
        # Read own record, merge in won_paths, write back.
        own_record = _atomic_read(record_path)
        if not isinstance(own_record, dict):
            # Own record is absent or malformed — cannot persist. Emit error and degrade gracefully.
            _emit_event(run_id, "registry_error", {
                "op": "claim", "run_id": run_id, "reason": "missing_record",
            })
            print(json.dumps({"claimed": [], "conceded": conceded_list}))
            return 0  # best-effort

        # Compute the set of paths being conceded so they are never persisted (BLOCKER-1).
        # held_paths = (existing_held ∪ staged_won) − conceded, deduped by path.
        conceded_paths: set[str] = {c["path"] for c in conceded_list}

        existing_held_raw = own_record.get("held_paths", [])
        existing_held: list = existing_held_raw if isinstance(existing_held_raw, list) else []

        # Build surviving entries: keep previously-held entries that are NOT conceded.
        surviving: list[dict] = [
            entry for entry in existing_held
            if isinstance(entry, dict) and entry.get("path") not in conceded_paths
        ]
        surviving_paths: set[str] = {
            entry["path"] for entry in surviving if isinstance(entry, dict) and "path" in entry
        }

        # Append newly-won paths (not already surviving, not conceded).
        new_held = list(surviving)
        for wp in won_paths:
            if wp not in surviving_paths:
                new_held.append({"path": wp, "since": now_ts})

        own_record["held_paths"] = new_held
        own_record["last_heartbeat"] = now_ts
        _atomic_write(record_path, own_record)

        # ── Emit event + write stdout ──────────────────────────────────────────
        _emit_event(run_id, "lease_claimed", {
            "run_id": run_id,
            "paths": won_paths,
            "conceded": conceded_list,
        })
        result = {"claimed": won_paths, "conceded": conceded_list}
        print(json.dumps(result))
        return 0

    except (OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        _emit_event(run_id, "registry_error", {
            "op": "claim", "run_id": run_id, "reason": "internal_error", "error": str(exc),
        })
        print(json.dumps({"claimed": [], "conceded": []}))
        return 0  # best-effort — advisory, never hard-fails


# ── release subcommand ───────────────────────────────────────────────────────

def cmd_release(args: argparse.Namespace) -> int:
    """release subcommand. NON-FATAL — always returns 0.

    Best-effort: removes the requested paths (or all paths) from own held_paths.
    A named path not currently held is a silent no-op. Atomic write. Refreshes
    last_heartbeat. Emits lease_released {run_id, paths} where paths is the set
    of entries actually removed.

    Self-logging: on any caught internal error emits registry_error(op:release)
    before returning 0, same as cmd_heartbeat/cmd_update_scope. A caller's
    ``|| log`` is dead code because this always returns 0 by design.

    Z_HARNESS_REGISTRY_ENABLED=0: silent no-op, exit 0 (handled in main()).
    """
    run_id = args.run_id

    if not _is_safe_basename(run_id):
        _emit_event(run_id, "registry_error", {
            "op": "release", "run_id": run_id, "reason": "unsafe_run_id",
        })
        return 0  # non-fatal

    # Determine the release mode and build the requested path set.
    release_all: bool = getattr(args, "all", False)
    paths_arg: str | None = getattr(args, "paths", None)

    if release_all:
        requested_paths: set[str] | None = None  # sentinel → remove all
    else:
        raw: list[str] = paths_arg.split(",") if paths_arg else []
        seen: set[str] = set()
        deduped: list[str] = []
        for p in raw:
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                deduped.append(p)
        requested_paths = set(deduped)

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        _emit_event(run_id, "registry_error", {
            "op": "release", "run_id": run_id, "reason": "active_plans_dir", "error": str(exc),
        })
        return 0  # non-fatal

    record_path = active_dir / f"{run_id}.json"

    try:
        own_record = _atomic_read(record_path)
        if not isinstance(own_record, dict):
            # Own record absent or malformed — nothing to release, no error (non-fatal no-op).
            _emit_event(run_id, "registry_error", {
                "op": "release", "run_id": run_id, "reason": "missing_record",
            })
            return 0

        existing_held_raw = own_record.get("held_paths", [])
        existing_held: list = existing_held_raw if isinstance(existing_held_raw, list) else []

        if release_all:
            # --all: collect everything currently held for the event, then clear.
            # Only include string "path" values in removed_paths (MAJOR-2: non-string
            # path values must not leak into the lease_released event payload).
            removed_paths: list[str] = [
                entry["path"]
                for entry in existing_held
                if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            ]
            new_held: list[dict] = []
        else:
            # --paths: keep entries whose "path" is NOT in the requested set.
            # Silently discard non-dict entries and entries with non-string "path"
            # values — they are corrupt and cannot be matched anyway (MAJOR-1 fix:
            # avoids TypeError when an unhashable "path" value hits `in requested_paths`).
            assert requested_paths is not None  # mypy / type narrowing
            removed_paths = []
            new_held = []
            for entry in existing_held:
                path = entry.get("path") if isinstance(entry, dict) else None
                if not isinstance(path, str):
                    # Non-dict or non-string "path": silently discard (corruption).
                    continue
                if path in requested_paths:
                    removed_paths.append(path)
                else:
                    new_held.append(entry)

        own_record["held_paths"] = new_held
        own_record["last_heartbeat"] = _iso_now()
        _atomic_write(record_path, own_record)

        _emit_event(run_id, "lease_released", {
            "run_id": run_id,
            "paths": removed_paths,
        })
    except (OSError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        _emit_event(run_id, "registry_error", {
            "op": "release", "run_id": run_id, "reason": "internal_error", "error": str(exc),
        })
        # non-fatal — still return 0

    return 0


# ── wait-for subcommand ───────────────────────────────────────────────────────


def cmd_wait_for(args: argparse.Namespace) -> int:
    """wait-for subcommand.

    Parks the CURRENT run behind one or more senior peers until their records
    clear (gone / complete / aborted / stale) or the budget expires.

    Exit codes:
      0   — cleared (all targets gone) or nothing_to_wait_on (no senior targets)
      2   — usage error
      10  — budget / timeout expired (LOUD)
      130 — SIGINT / SIGTERM received

    The waiting_on field is cleared on EVERY exit path via a try/finally block
    (EH-005) so no paused zombie record can leak.
    """
    run_id = args.run_id
    if not _is_safe_basename(run_id):
        print(
            f"[active-plan-registry] ERROR wait-for: run-id {run_id!r} is not a safe basename.",
            file=sys.stderr,
        )
        return 2

    # Read the --on list.
    raw_on: list[str] = [r.strip() for r in args.on.split(",") if r.strip()]
    if not raw_on:
        print(
            "[active-plan-registry] ERROR wait-for: --on requires at least one run-id.",
            file=sys.stderr,
        )
        return 2

    # Read --paths (optional).
    watch_paths: list[str] = []
    if getattr(args, "paths", None):
        watch_paths = [p.strip() for p in args.paths.split(",") if p.strip()]

    # Determine auto vs. explicit mode and budget.
    is_auto = os.environ.get("Z_HARNESS_AUTO_WAIT", str(_DEFAULT_AUTO_WAIT)).strip() == "1"
    try:
        budget_secs = int(os.environ.get(
            "Z_HARNESS_AUTO_WAIT_BUDGET_SECS",
            _DEFAULT_AUTO_WAIT_BUDGET_SECS,
        ))
    except ValueError:
        budget_secs = _DEFAULT_AUTO_WAIT_BUDGET_SECS

    try:
        explicit_timeout = int(os.environ.get(
            "Z_HARNESS_WAIT_TIMEOUT_SECS",
            _DEFAULT_EXPLICIT_WAIT_TIMEOUT_SECS,
        ))
    except ValueError:
        explicit_timeout = _DEFAULT_EXPLICIT_WAIT_TIMEOUT_SECS

    try:
        poll_secs = int(os.environ.get(
            "Z_HARNESS_WAIT_POLL_SECS",
            _DEFAULT_WAIT_POLL_SECS,
        ))
    except ValueError:
        poll_secs = _DEFAULT_WAIT_POLL_SECS

    # Z_HARNESS_WAIT_REQUIRE_MERGE: reserved for T009 (branch-ancestor cleared signal).
    # Read inline here so the knob is present for observability / future use.
    # Default 0 = deregister-only (current behaviour); 1 = T009 branch-ancestor check.
    try:
        _require_merge = int(os.environ.get(
            "Z_HARNESS_WAIT_REQUIRE_MERGE",
            _DEFAULT_WAIT_REQUIRE_MERGE,
        ))
    except ValueError:
        _require_merge = _DEFAULT_WAIT_REQUIRE_MERGE

    effective_budget = budget_secs if is_auto else explicit_timeout

    # Resolve active_plans_dir once; failure is a hard usage error.
    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] FATAL wait-for: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        return 2

    stale_threshold = _stale_secs()

    def _is_target_cleared(target_run_id: str) -> bool:
        """Return True if the target's record is gone, in a terminal status, or age-stale.

        An age-stale record (last_heartbeat past stale_threshold) with status
        still "running" must count as cleared — otherwise wait-for hangs
        indefinitely when the reaper carve-out (T006) keeps a live-local-pid
        record alive but the peer has effectively stopped making progress.
        """
        rec = _atomic_read(active_dir / f"{target_run_id}.json")
        if rec is None:
            return True  # record gone
        status = rec.get("status", "")
        if status in {"complete", "aborted", "stale"}:
            return True
        if _is_stale(rec, stale_threshold):
            return True
        # Z_HARNESS_WAIT_REQUIRE_MERGE=1 would add merge-ancestor check here (T009,
        # deferred). Degrades to deregister-only until T009 lands.
        return False

    def _scan_new_senior_holders(current_targets: list[str]) -> list[str]:
        """TOCTOU re-scan: return any new senior run_ids holding watch_paths.

        Only considers live, lease-capable, senior peers not already in
        current_targets. Junior claimers are ignored (MINOR-7).
        """
        if not watch_paths:
            return []
        current_set = set(current_targets)
        new_seniors: list[str] = []
        if not active_dir.is_dir():
            return []
        for p in sorted(active_dir.glob("*.json")):
            rec = _atomic_read(p)
            if not isinstance(rec, dict):
                continue
            peer_run_id = rec.get("run_id", "")
            if not isinstance(peer_run_id, str) or not peer_run_id:
                continue
            if peer_run_id == run_id:
                continue
            if peer_run_id in current_set:
                continue
            # Only senior peers (MINOR-7).
            if not _is_senior(peer_run_id, run_id):
                continue
            if not _is_lease_capable(rec):
                continue
            # Skip stale/cleared peers.
            if (rec.get("status") in {"complete", "aborted", "stale"}) or _is_stale(rec, stale_threshold):
                continue
            peer_held_raw = rec.get("held_paths", [])
            peer_held: list = peer_held_raw if isinstance(peer_held_raw, list) else []
            peer_held_paths: set[str] = {
                entry["path"]
                for entry in peer_held
                if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            }
            if any(wp in peer_held_paths for wp in watch_paths):
                new_seniors.append(peer_run_id)
        return new_seniors

    # ── Eligibility filter ────────────────────────────────────────────────────
    # Keep only live, senior (run_id < mine) targets.
    targets: list[str] = []
    for candidate in raw_on:
        if not _is_safe_basename(candidate):
            print(
                f"[active-plan-registry] NOTE wait-for: dropping unsafe run-id {candidate!r}.",
                file=sys.stderr,
            )
            continue
        if not _is_senior(candidate, run_id):
            print(
                f"[active-plan-registry] NOTE wait-for: dropping junior/equal run-id {candidate!r} "
                f"(not senior to {run_id!r}).",
                file=sys.stderr,
            )
            continue
        if _is_target_cleared(candidate):
            print(
                f"[active-plan-registry] NOTE wait-for: target {candidate!r} already cleared; skipping.",
                file=sys.stderr,
            )
            continue
        targets.append(candidate)

    if not targets:
        _emit_event(run_id, "wait_started", {
            "run_id": run_id, "waiting_on": [], "paths": watch_paths, "auto": is_auto,
        })
        print("[wait-for] nothing_to_wait_on")
        # Nothing to clear; waiting_on already empty — no cleanup needed.
        return 0

    # ── Emit wait_started ─────────────────────────────────────────────────────
    _emit_event(run_id, "wait_started", {
        "run_id": run_id, "waiting_on": list(targets), "paths": watch_paths, "auto": is_auto,
    })

    start_ts = time.monotonic()
    exit_code = 0
    interrupted = False
    waited_on_at_interrupt: list[str] = []

    # ── Signal handling ───────────────────────────────────────────────────────

    def _handle_signal(signum: int, _frame: object) -> None:
        raise SystemExit(130)

    old_sigint = signal.signal(signal.SIGINT, _handle_signal)
    old_sigterm = signal.signal(signal.SIGTERM, _handle_signal)

    try:
        # ── Poll loop ─────────────────────────────────────────────────────────
        while True:
            elapsed = time.monotonic() - start_ts

            # Check budget BEFORE sleeping so first-iteration timeout is consistent.
            if elapsed >= effective_budget:
                # Budget expired.
                print(
                    f"[wait-for] TIMEOUT after {elapsed:.0f}s (budget={effective_budget}s); "
                    f"waited_on={targets!r}",
                    file=sys.stderr,
                )
                _emit_event(run_id, "wait_timeout", {
                    "run_id": run_id,
                    "waited_on": list(targets),
                    "elapsed_s": elapsed,
                    "budget_s": effective_budget,
                })
                exit_code = 10
                break

            # Single atomic write: set status=paused + waiting_on in one shot (MINOR-1).
            _set_waiting_on(run_id, targets, status="paused")

            # Run reap to free dead peers.
            try:
                _reap_inline(active_dir, stale_threshold)
            except OSError:
                pass  # reap failure is non-fatal

            # Cap sleep to the remaining budget so we never overshoot by a full
            # poll interval when the deadline falls inside a sleep window.
            remaining_budget = effective_budget - (time.monotonic() - start_ts)
            time.sleep(min(poll_secs, max(0.0, remaining_budget)))

            # Re-check timeout immediately on wake BEFORE running reap / target-clear
            # / TOCTOU checks — a target clearing after the deadline must not produce
            # a false exit-0 (cleared) when exit-10 (timeout) is correct.
            elapsed = time.monotonic() - start_ts
            if elapsed >= effective_budget:
                print(
                    f"[wait-for] TIMEOUT after {elapsed:.0f}s (budget={effective_budget}s); "
                    f"waited_on={targets!r}",
                    file=sys.stderr,
                )
                _emit_event(run_id, "wait_timeout", {
                    "run_id": run_id,
                    "waited_on": list(targets),
                    "elapsed_s": elapsed,
                    "budget_s": effective_budget,
                })
                exit_code = 10
                break

            # Recompute cleared targets.
            targets = [t for t in targets if not _is_target_cleared(t)]

            # TOCTOU re-scan: add any new senior holders of watch_paths (senior-only, MINOR-7).
            new_seniors = _scan_new_senior_holders(targets)
            for ns in new_seniors:
                if ns not in targets:
                    targets.append(ns)

            # Check if all cleared and no new senior holders.
            if not targets:
                elapsed = time.monotonic() - start_ts
                print(f"[wait-for] cleared after {elapsed:.0f}s")
                _emit_event(run_id, "wait_cleared", {
                    "run_id": run_id,
                    "elapsed_s": elapsed,
                })
                exit_code = 0
                break

    except SystemExit as exc:
        # Raised by our signal handler (SIGINT/SIGTERM).
        if exc.code == 130:
            interrupted = True
            exit_code = 130
            waited_on_at_interrupt = list(targets)
        else:
            raise
    finally:
        # Restore original signal handlers.
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

        # ALWAYS clear waiting_on and restore status=running on every exit path (EH-005).
        _set_waiting_on(run_id, [], status="running")

        if interrupted:
            _emit_event(run_id, "wait_interrupted", {
                "run_id": run_id,
                "waited_on": waited_on_at_interrupt,
            })
            print("[wait-for] interrupted", file=sys.stderr)

    return exit_code


def _reap_inline(active_dir: Path, stale_threshold: int) -> None:
    """Run the reap logic for a single active_plans_dir.

    Extracted from cmd_reap so wait-for can call it without re-resolving
    active_plans_dir.  Identical semantics to cmd_reap — non-fatal overall.
    """
    this_host = socket.gethostname()
    if not active_dir.is_dir():
        return
    for p in sorted(active_dir.glob("*.json")):
        rec = _atomic_read(p)
        if rec is None:
            continue

        run_id_rec = rec.get("run_id", str(p.stem))
        rec_host = rec.get("host", "")
        pid = rec.get("pid")
        age_secs = _heartbeat_age_secs(rec)

        is_local_host = rec_host == this_host
        if is_local_host and isinstance(pid, int):
            if not _pid_alive(pid):
                try:
                    p.unlink()
                    _emit_event(run_id_rec, "plan_reaped", {
                        "run_id": run_id_rec, "reason": "dead_local_pid",
                        "pid": pid, "host": rec_host,
                    })
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                continue

        if age_secs > stale_threshold * 2:
            try:
                p.unlink()
                _emit_event(run_id_rec, "plan_reaped", {
                    "run_id": run_id_rec, "reason": "2x_stale_margin",
                    "age_secs": age_secs, "stale_threshold": stale_threshold,
                })
            except FileNotFoundError:
                pass
            except OSError:
                pass
            continue

        if age_secs > stale_threshold and not is_local_host:
            if rec.get("status") != "stale":
                rec["status"] = "stale"
                try:
                    _atomic_write(p, rec)
                    _emit_event(run_id_rec, "plan_marked_stale", {
                        "run_id": run_id_rec, "reason": "remote_host_stale",
                        "host": rec_host, "age_secs": age_secs,
                        "stale_threshold": stale_threshold,
                    })
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


# ── pid liveness ──────────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    """Return True if pid is alive on this host.

    Uses os.kill(pid, 0): raises ProcessLookupError (ESRCH) if dead,
    PermissionError (EPERM) if alive but not owned by us.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it → alive.
        return True


def _is_stale(record: dict, stale_threshold: int) -> bool:
    """Return True if the record's last_heartbeat is past the 1× stale threshold."""
    hb_str = record.get("last_heartbeat", "")
    if not hb_str:
        return False
    try:
        hb = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_secs = (now - hb).total_seconds()
        return age_secs > stale_threshold
    except ValueError:
        return False


def _heartbeat_age_secs(record: dict) -> float:
    """Return seconds since last_heartbeat, or infinity if unreadable."""
    hb_str = record.get("last_heartbeat", "")
    if not hb_str:
        return float("inf")
    try:
        hb = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - hb).total_seconds()
    except ValueError:
        return float("inf")


# ── overlaps subcommand ────────────────────────────────────────────────────────

def cmd_overlaps(args: argparse.Namespace) -> int:
    """overlaps subcommand.

    Exit codes:
      0  — no overlap
      10 — advisory overlap (any non-stale overlap)
      20 — blocking overlap (strict mode AND explicit×explicit exact path match with live peer)
    """
    run_id = args.run_id
    strict = getattr(args, "strict", False) or (
        os.environ.get("Z_HARNESS_STRICT_OVERLAP", "").strip() == "1"
    )

    try:
        active_dir = _active_plans_dir()
    except RuntimeError as exc:
        print(
            f"[active-plan-registry] ERROR overlaps: cannot resolve active_plans_dir: {exc}",
            file=sys.stderr,
        )
        return 4

    # Always load own record first (for session_id — needed for same-session filtering
    # regardless of whether --scope-json overrides the scope).
    own_record_path = active_dir / f"{run_id}.json"
    own_record = _atomic_read(own_record_path)
    my_session_id: str = (own_record or {}).get("session_id", "") or ""

    # Load scope: prefer --scope-json if provided, else fall back to own record.
    my_scope: list[dict] = []

    if getattr(args, "scope_json", None):
        scope_path = Path(args.scope_json)
        try:
            with scope_path.open("r", encoding="utf-8") as fh:
                my_scope = json.load(fh)
            if not isinstance(my_scope, list):
                my_scope = []
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[active-plan-registry] ERROR overlaps: cannot read --scope-json: {exc}",
                file=sys.stderr,
            )
            return 4
    else:
        # Load scope from own record (already read above).
        if own_record is not None:
            my_scope = own_record.get("scope", []) or []

    # Build a dict of {path → confidence} for fast intersection.
    def _scope_map(scope: list[dict]) -> dict[str, str]:
        return {item["path"]: item.get("confidence", "unknown") for item in scope if "path" in item}

    my_scope_map = _scope_map(my_scope)

    # Extract my held_paths as a set of path strings for held-conflict computation.
    # Guard: own_record may be None (no registered record yet); held_paths entries must
    # be dicts with a string "path" key (same guard pattern used in cmd_claim/cmd_release).
    my_held_raw = (own_record or {}).get("held_paths", [])
    my_held_paths: set[str] = {
        entry["path"]
        for entry in (my_held_raw if isinstance(my_held_raw, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }

    # Scan all peer records.
    stale_threshold = _stale_secs()
    peers_with_overlap: list[dict] = []
    # held_conflicts: flat list of per-path held-lease conflicts across ALL live
    # lease-capable peers (independent of scope overlap).  Each entry records the
    # conflicting path, the peer's run_id, and whether that peer is senior or junior
    # to this run via the canonical _is_senior() predicate.
    held_conflicts: list[dict] = []
    scanned = 0
    live_count = 0

    if active_dir.is_dir():
        for p in sorted(active_dir.glob("*.json")):
            rec = _atomic_read(p)
            if rec is None:
                continue
            scanned += 1
            peer_run_id = rec.get("run_id", "")
            peer_session_id = rec.get("session_id", "") or ""

            # Skip self (same run_id) and same session.
            if peer_run_id == run_id:
                continue
            if peer_session_id and my_session_id and peer_session_id == my_session_id:
                continue

            # Determine staleness.
            is_stale_peer = (rec.get("status") == "stale") or _is_stale(rec, stale_threshold)

            if not is_stale_peer:
                live_count += 1

            # Compute scope-path intersection (unchanged behaviour).
            peer_scope = rec.get("scope", []) or []
            peer_scope_map = _scope_map(peer_scope)

            shared: list[dict] = []
            for path, my_conf in my_scope_map.items():
                if path in peer_scope_map:
                    peer_conf = peer_scope_map[path]
                    shared.append({
                        "path": path,
                        "my_confidence": my_conf,
                        "peer_confidence": peer_conf,
                        "min_confidence": _min_confidence(my_conf, peer_conf),
                    })

            if shared:
                peers_with_overlap.append({
                    "peer": {
                        "run_id": peer_run_id,
                        "slug": rec.get("slug", ""),
                        "branch": rec.get("branch", ""),
                        "worktree_path": rec.get("worktree_path", ""),
                        "host": rec.get("host", ""),
                        "pid": rec.get("pid"),
                        "current_task": rec.get("current_task", ""),
                    },
                    "shared_paths": shared,
                    "is_stale": is_stale_peer,
                })

            # Compute held-path conflict for LIVE, lease-capable peers only.
            # Stale peers and peers without schema-v2 held_paths are skipped (F-backcompat).
            # peer_run_id must be a non-empty string (already filtered above) for
            # _is_senior() to give a meaningful result.
            if not is_stale_peer and isinstance(peer_run_id, str) and peer_run_id and _is_lease_capable(rec):
                peer_held_raw = rec.get("held_paths", [])
                peer_held_paths: set[str] = {
                    entry["path"]
                    for entry in (peer_held_raw if isinstance(peer_held_raw, list) else [])
                    if isinstance(entry, dict) and isinstance(entry.get("path"), str)
                }
                for conflict_path in sorted(my_held_paths & peer_held_paths):
                    held_conflicts.append({
                        "path": conflict_path,
                        "peer_run_id": peer_run_id,
                        "holder_seniority": "senior" if _is_senior(peer_run_id, run_id) else "junior",
                    })

    # Determine exit code.
    exit_code = 0
    has_blocking = False

    if peers_with_overlap:
        # Check for non-stale overlapping peers.
        non_stale_overlaps = [p for p in peers_with_overlap if not p["is_stale"]]
        if non_stale_overlaps:
            exit_code = 10
            # Check for blocking: strict mode AND explicit×explicit exact path match.
            if strict:
                for peer_info in non_stale_overlaps:
                    for shared_path in peer_info["shared_paths"]:
                        if (
                            shared_path.get("my_confidence") == "explicit"
                            and shared_path.get("peer_confidence") == "explicit"
                        ):
                            has_blocking = True
                            break
                    if has_blocking:
                        break
                if has_blocking:
                    exit_code = 20

    # Emit events and print output.
    if peers_with_overlap:
        payload = {
            "run_id": run_id,
            "scanned": scanned,
            "live": live_count,
            "overlapping_peers": len(peers_with_overlap),
            "blocking": has_blocking,
            "peers": peers_with_overlap,
        }
        # Additive: include held_conflict only when at least one conflict exists.
        # Scope-only overlaps (no held-path intersection) never produce this key.
        if held_conflicts:
            payload["held_conflict"] = held_conflicts
        _emit_event(run_id, "scope_overlap_detected", payload)

        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            # Human-readable summary.
            blocking_label = " [BLOCKING]" if has_blocking else ""
            print(
                f"[overlap{blocking_label}] {len(peers_with_overlap)} peer(s) share paths with run {run_id!r}"
            )
            for peer_info in peers_with_overlap:
                peer = peer_info["peer"]
                stale_label = " (stale)" if peer_info["is_stale"] else ""
                print(
                    f"  peer={peer['run_id']!r}  slug={peer['slug']!r}  "
                    f"host={peer['host']!r}  branch={peer['branch']!r}{stale_label}"
                )
                for sp in peer_info["shared_paths"]:
                    print(
                        f"    path={sp['path']!r}  "
                        f"min_confidence={sp['min_confidence']!r}"
                    )
            if held_conflicts:
                print(f"  held_conflict: {len(held_conflicts)} path(s)")
                for hc in held_conflicts:
                    print(
                        f"    path={hc['path']!r}  peer={hc['peer_run_id']!r}"
                        f"  seniority={hc['holder_seniority']!r}"
                    )
    else:
        payload = {
            "run_id": run_id,
            "scanned": scanned,
            "live": live_count,
            "overlaps": 0,
        }
        # Additive: held_conflict may exist even when there is no scope overlap.
        if held_conflicts:
            payload["held_conflict"] = held_conflicts
        _emit_event(run_id, "active_plan_scan_complete", payload)

        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"[no overlap] scanned={scanned} live={live_count} overlaps=0")
            if held_conflicts:
                print(f"  held_conflict: {len(held_conflicts)} path(s)")
                for hc in held_conflicts:
                    print(
                        f"    path={hc['path']!r}  peer={hc['peer_run_id']!r}"
                        f"  seniority={hc['holder_seniority']!r}"
                    )

    return exit_code


# ── reap subcommand ────────────────────────────────────────────────────────────

def cmd_reap(args: argparse.Namespace) -> int:  # noqa: ARG001
    """reap subcommand. Conservative reaper. NON-FATAL overall — always returns 0.

    Deletion policy:
      (a) host == this host AND pid is dead → delete immediately.
      Live-local-pid carve-out: host == this host AND pid ALIVE AND past 2× stale
        margin → mark status:"stale" only; do NOT delete. Deletion deferred until
        the pid dies and case (a) fires on a later reap cycle.
      (b) past 2× stale margin AND no live-local-pid → delete (covers remote/unknown-
        host records and local records with no pid field).
      (c) past 1× stale margin AND host is remote/unknown → mark status:"stale" only.

    REAPER EXCEPTION: reap is the ONE allowed cross-record write (marking a peer's
    status as "stale"). This is documented in the module docstring and is acceptable
    because:
      - It is atomic (tmpfile + os.replace).
      - The owner may overwrite it at any time with a fresh heartbeat (last-writer-wins).
      - Two reapers racing on the same record cannot crash (FileNotFoundError is caught).
    """
    try:
        active_dir = _active_plans_dir()
    except RuntimeError:
        return 0  # non-fatal

    stale_threshold = _stale_secs()
    this_host = socket.gethostname()

    if not active_dir.is_dir():
        return 0

    for p in sorted(active_dir.glob("*.json")):
        rec = _atomic_read(p)
        if rec is None:
            continue  # torn / missing — skip silently

        run_id = rec.get("run_id", str(p.stem))
        rec_host = rec.get("host", "")
        pid = rec.get("pid")
        age_secs = _heartbeat_age_secs(rec)

        # Case (a): dead local pid → delete.
        is_local_host = rec_host == this_host
        if is_local_host and isinstance(pid, int):
            if not _pid_alive(pid):
                # Dead local process — delete the record.
                try:
                    p.unlink()
                    _emit_event(run_id, "plan_reaped", {
                        "run_id": run_id,
                        "reason": "dead_local_pid",
                        "pid": pid,
                        "host": rec_host,
                    })
                except FileNotFoundError:
                    pass  # two reapers racing — benign
                except OSError:
                    pass  # non-fatal
                continue

            # Live local pid — even if 2× stale, do NOT delete (the process may be
            # suspended or running inside a long-lived subtask).  Mark stale so peers
            # can see it is overdue, but leave deletion to case (a) when the pid dies.
            if age_secs > stale_threshold * 2:
                if rec.get("status") != "stale":
                    rec["status"] = "stale"
                    try:
                        _atomic_write(p, rec)
                        _emit_event(run_id, "plan_marked_stale", {
                            "run_id": run_id,
                            "reason": "live_local_pid_2x_stale",
                            "pid": pid,
                            "host": rec_host,
                            "age_secs": age_secs,
                            "stale_threshold": stale_threshold,
                        })
                    except FileNotFoundError:
                        pass  # two reapers racing — benign
                    except OSError:
                        pass  # non-fatal
                continue  # do not fall through to case (b)

        # Case (b): 2× stale margin exceeded → delete (remote/unknown host, or local
        # host record with no pid field).  Live-local-pid records are handled above.
        if age_secs > stale_threshold * 2:
            try:
                p.unlink()
                _emit_event(run_id, "plan_reaped", {
                    "run_id": run_id,
                    "reason": "2x_stale_margin",
                    "age_secs": age_secs,
                    "stale_threshold": stale_threshold,
                })
            except FileNotFoundError:
                pass  # two reapers racing — benign
            except OSError:
                pass  # non-fatal
            continue

        # Case (c): past 1× threshold AND host is remote/unknown → mark stale (do NOT delete).
        if age_secs > stale_threshold and not is_local_host:
            # Only mark if not already stale.
            if rec.get("status") != "stale":
                rec["status"] = "stale"
                try:
                    _atomic_write(p, rec)
                    _emit_event(run_id, "plan_marked_stale", {
                        "run_id": run_id,
                        "reason": "remote_host_stale",
                        "host": rec_host,
                        "age_secs": age_secs,
                        "stale_threshold": stale_threshold,
                    })
                except FileNotFoundError:
                    pass  # two reapers racing — benign
                except OSError:
                    pass  # non-fatal

    return 0


# ── argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="active-plan-registry.py",
        description="Lockless per-run active-plan registry.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # session-id
    sub.add_parser(
        "session-id",
        help=(
            "Print a stable session id for the current shell session. "
            "Returns $Z_HARNESS_SESSION_ID if set; otherwise derives <ppid>-<start_epoch>. "
            "Callers should: export Z_HARNESS_SESSION_ID=\"$(session-id)\" once at run start."
        ),
    )

    # register
    p_reg = sub.add_parser("register", help="Register a new run.")
    p_reg.add_argument("--run-id", required=True, help="Unique run identifier (safe basename).")
    p_reg.add_argument("--slug", required=True, help="Plan slug.")
    p_reg.add_argument("--command", required=True, help="Command name (e.g. /z-implement-all).")
    p_reg.add_argument("--phase", required=True, help="Current phase (e.g. implement).")
    p_reg.add_argument("--session", default="", help="Session ID (optional).")

    # heartbeat
    p_hb = sub.add_parser("heartbeat", help="Update heartbeat for a live run.")
    p_hb.add_argument("--run-id", required=True)
    p_hb.add_argument("--phase", default=None)
    p_hb.add_argument("--current-task", default=None, dest="current_task")
    p_hb.add_argument("--status", choices=["running", "paused"], default=None)

    # update-scope
    p_scope = sub.add_parser("update-scope", help="Merge scope array into record.")
    p_scope.add_argument("--run-id", required=True)
    p_scope.add_argument("--scope-json", required=True, help="Path to JSON file with scope array.")

    # list
    p_list = sub.add_parser("list", help="List all active-plan records.")
    p_list.add_argument("--json", action="store_true", help="Output as JSON array.")

    # deregister
    p_dereg = sub.add_parser("deregister", help="Remove a run record.")
    p_dereg.add_argument("--run-id", required=True)
    p_dereg.add_argument(
        "--status",
        choices=["complete", "aborted"],
        default="complete",
    )

    # overlaps
    p_overlaps = sub.add_parser(
        "overlaps",
        help="Compute path-intersection overlap with peer active plans.",
    )
    p_overlaps.add_argument("--run-id", required=True, help="Run ID to check overlaps for.")
    p_overlaps.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help=(
            "Enable blocking-overlap mode: exit 20 on explicit×explicit exact path match. "
            "Also activated by Z_HARNESS_STRICT_OVERLAP=1."
        ),
    )
    p_overlaps.add_argument(
        "--scope-json",
        default=None,
        dest="scope_json",
        help="Path to a JSON scope array; overrides the scope stored in the run's record.",
    )
    p_overlaps.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output result as JSON instead of human-readable text.",
    )

    # reap
    sub.add_parser("reap", help="Conservative reaper: remove dead/2x-stale records.")

    # claim
    p_claim = sub.add_parser(
        "claim",
        help=(
            "Stage and claim per-file leases for a run. Best-effort (advisory, never "
            "hard-fails). Performs check-after-claim (F2) with run_id tiebreak: a senior "
            "peer (lower run_id) holding a path wins; caller concedes and should wait-for "
            "that peer. Persists only the won set (BLOCKER-1). "
            "Stdout: JSON {claimed:[...], conceded:[{path, holder_run_id}]}."
        ),
    )
    p_claim.add_argument("--run-id", required=True, help="Run ID that owns the claim.")
    p_claim.add_argument(
        "--paths",
        required=True,
        help="Comma-separated repo-relative paths to claim.",
    )

    # wait-for
    p_wait = sub.add_parser(
        "wait-for",
        help=(
            "Park the current run behind one or more senior peers until their records clear "
            "or the budget expires. Exit 0 = cleared/nothing_to_wait_on; 10 = budget expired; "
            "130 = SIGINT/SIGTERM. Clears waiting_on on every exit path (no paused zombie)."
        ),
    )
    p_wait.add_argument("--run-id", required=True, help="This run's ID (the waiter).")
    p_wait.add_argument(
        "--on",
        required=True,
        help="Comma-separated run-ids to wait on (non-senior ids are silently dropped).",
    )
    p_wait.add_argument(
        "--paths",
        default=None,
        help=(
            "Comma-separated repo-relative paths to watch for new senior holders "
            "(TOCTOU re-scan). Optional."
        ),
    )

    # release
    p_release = sub.add_parser(
        "release",
        help=(
            "Remove per-file leases from own held_paths. Best-effort (advisory, "
            "never hard-fails). --paths and --all are mutually exclusive; exactly "
            "one is required. Emits lease_released {run_id, paths}."
        ),
    )
    p_release.add_argument("--run-id", required=True, help="Run ID that owns the leases.")
    p_release_mx = p_release.add_mutually_exclusive_group(required=True)
    p_release_mx.add_argument(
        "--paths",
        default=None,
        help="Comma-separated repo-relative paths to release.",
    )
    p_release_mx.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Release all currently held paths.",
    )

    return parser


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Z_HARNESS_REGISTRY_ENABLED=0 disables coordination writes (register/overlaps).
    # Non-mutating read commands (list, session-id) are always allowed.
    # NON-FATAL writes (heartbeat, update-scope, deregister, reap) are also skipped
    # when the registry is disabled, since there are no records to update.
    if os.environ.get("Z_HARNESS_REGISTRY_ENABLED", "1") == "0":
        _REGISTRY_DISABLED_SUBCMDS = frozenset(
            {"register", "heartbeat", "update-scope", "overlaps", "reap", "deregister", "claim",
             "release", "wait-for"}
        )
        if args.subcommand in _REGISTRY_DISABLED_SUBCMDS:
            # Silent no-op: registry is disabled. For overlaps, exit 0 (no overlap).
            # For claim, print the expected empty JSON so callers can parse stdout.
            if args.subcommand == "claim":
                print(json.dumps({"claimed": [], "conceded": []}))
            return 0

    dispatch = {
        "session-id": cmd_session_id,
        "register": cmd_register,
        "heartbeat": cmd_heartbeat,
        "update-scope": cmd_update_scope,
        "list": cmd_list,
        "deregister": cmd_deregister,
        "overlaps": cmd_overlaps,
        "reap": cmd_reap,
        "claim": cmd_claim,
        "release": cmd_release,
        "wait-for": cmd_wait_for,
    }
    handler = dispatch.get(args.subcommand)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
