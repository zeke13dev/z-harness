#!/usr/bin/env python3
"""
scripts/sink-claim-helpers.py — implementation for sink-claim.sh.

Performs an atomic open→running claim on a follow-up entry.

Lock-ordering invariant (MANDATORY per SPEC §Concurrency-model):
  Per-entry lock FIRST, then global. This prevents deadlock.

Exit codes:
  0  success — prints claim ticket JSON to stdout; per-entry lock is held
  2  validation error
  3  not claimable (status not open after lock)
  4  staleness drift detected; --allow-stale not passed
  5  lock timeout
  7  depth-1 refusal
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# ── constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent

# Robust import for scripts invoked as standalone via `python3 scripts/sink-claim-helpers.py`
sys.path.insert(0, str(SCRIPT_DIR))
from followup_common import (  # noqa: E402
    iso_now,
    git_head,
    acquire_global_lock,
    release_global_lock,
)

GLOBAL_LOCK_FILE = Path(os.environ.get(
    "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK",
    str(Path.home() / ".z-harness" / ".followup-vs-implement.lock"),
))

SINK_LOCK_SH = SCRIPT_DIR / "sink-lock.sh"
VIEW_REBUILD_SH = SCRIPT_DIR / "sink-view-rebuild.sh"

LOCK_TIMEOUT_SECONDS = 30
STALENESS_COMMIT_WINDOW_DEFAULT = 50

# TTL for heartbeat staleness (2 hours in seconds)
STALE_TTL_SECONDS = 7200

EXIT_SUCCESS = 0
EXIT_VALIDATION = 2
EXIT_NOT_CLAIMABLE = 3
EXIT_STALE_DRIFT = 4
EXIT_LOCK_TIMEOUT = 5
EXIT_DEPTH_1 = 7


# ── helpers ────────────────────────────────────────────────────────────────────

def _read_lock_holder_record(lock_path: Path) -> dict | None:
    """Read the lock file JSON and return the holder record dict, or None.

    Returns a dict with at least ``holder`` (str) and ``pid`` (int) if the
    lock file contains a valid T001 holder record.  Returns None on any parse
    failure or if the fields are absent / wrong types.

    Callers (claim path) must treat a None return as a hard failure — a claim
    ticket MUST carry holder+pid; omitting them would produce an unverifiable
    ticket that sink-status-set-impl.py would later reject.
    """
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    holder = parsed.get("holder")
    pid = parsed.get("pid")
    if not isinstance(holder, str) or not holder:
        return None
    if not isinstance(pid, int) or pid <= 0:
        return None
    return {"holder": holder, "pid": pid}


def _run_sink_lock(*args: str) -> int:
    """Run sink-lock.sh with the given arguments; return its exit code."""
    result = subprocess.run(
        ["bash", str(SINK_LOCK_SH)] + list(args),
        capture_output=True,
    )
    return result.returncode


def acquire_entry_lock(lock_path: Path, holder_id: str, timeout: int = LOCK_TIMEOUT_SECONDS) -> int:
    """Acquire per-entry lock with retry. Returns 0/2 on success, raises TimeoutError on failure.

    Returns:
        0 — fresh acquire
        2 — stale-takeover succeeded
    Raises:
        TimeoutError on contention or corrupt lock
    """
    deadline = time.monotonic() + timeout
    while True:
        rc = _run_sink_lock("acquire", str(lock_path), holder_id)
        if rc in (0, 2):
            return rc
        if rc == 1:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Could not acquire per-entry lock within {timeout}s: {lock_path}"
                )
            time.sleep(1.0)
            continue
        # rc == 3 or unexpected — corrupt / non-retryable
        raise TimeoutError(
            f"Per-entry lock is corrupt (exit {rc}): {lock_path}"
        )




def read_view(sink_root: Path) -> dict:
    """Read and return the materialized view dict (entries keyed by id)."""
    view_path = sink_root / "index.view.json"
    if not view_path.exists():
        return {}
    try:
        data = json.loads(view_path.read_text(encoding="utf-8"))
        return data.get("entries", {})
    except (json.JSONDecodeError, OSError):
        return {}


def get_entry(sink_root: Path, entry_id: str) -> dict | None:
    """Return the entry dict from the materialized view, or None if not found."""
    entries = read_view(sink_root)
    return entries.get(entry_id)


def rebuild_view(sink_root: Path) -> None:
    """Invoke sink-view-rebuild.sh; assumes global lock is already held by caller."""
    env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": str(GLOBAL_LOCK_FILE)}
    result = subprocess.run(
        ["bash", str(VIEW_REBUILD_SH), str(sink_root)],
        env=env,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sink-view-rebuild.sh exited {result.returncode}: "
            f"{result.stderr.decode(errors='replace')}"
        )


def append_event(sink_root: Path, event: dict) -> None:
    """Append a JSONL event to index.jsonl."""
    index_path = sink_root / "index.jsonl"
    event_with_ts = {"ts": iso_now(), **event}
    line = json.dumps(event_with_ts, separators=(",", ":")) + "\n"
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def git_rev_distance(base_sha: str, head_sha: str) -> int | None:
    """Return the number of commits between base_sha and HEAD, or None on error."""
    if base_sha == "unknown" or head_sha == "unknown":
        return None
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{base_sha}..{head_sha}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    return None


def file_content_hash(path: str) -> str | None:
    """Return ``sha256:<hex>`` content hash for a file, or None if unreadable.

    Reads raw file bytes and computes hashlib.sha256 — NOT git hash-object.
    """
    try:
        with open(path, "rb") as fh:
            file_bytes = fh.read()
        return "sha256:" + hashlib.sha256(file_bytes).hexdigest()
    except OSError:
        return None


def check_staleness(entry: dict, staleness_commit_window: int) -> tuple[bool, str]:
    """
    Check if the entry's cited paths / capture_head are stale.

    Returns:
        (is_stale, reason) — is_stale=True means drift detected.
    """
    capture_head = entry.get("capture_head", "unknown")
    try:
        current_head = git_head()
    except RuntimeError:
        # git unavailable — cannot compute staleness; treat as non-stale to avoid
        # blocking claims in environments without git (e.g. CI sandbox)
        current_head = "unknown"

    # Check commit distance
    distance = git_rev_distance(capture_head, current_head)
    if distance is not None and distance > staleness_commit_window:
        return True, (
            f"capture_head is {distance} commits behind HEAD "
            f"(window={staleness_commit_window})"
        )

    # Check file blob hashes — recompute sha256: content hash and compare exactly
    file_blob_hashes = entry.get("file_blob_hashes")
    if file_blob_hashes:
        for path, recorded_hash in file_blob_hashes.items():
            current_hash = file_content_hash(path)
            if current_hash is None or current_hash != recorded_hash:
                return True, f"blob hash mismatch for cited path: {path!r}"

    # Check dir blob hashes (tree-hash variant for >16 cited paths)
    dir_blob_hashes = entry.get("dir_blob_hashes")
    if dir_blob_hashes:
        for dir_path, recorded_hash in dir_blob_hashes.items():
            # Re-compute sha256: tree hash at current HEAD and compare exactly
            try:
                result = subprocess.run(
                    ["git", "ls-tree", "-r", current_head, dir_path + "/"],
                    capture_output=True, text=True,
                )
                tree_listing = result.stdout
                current_hash = "sha256:" + hashlib.sha256(tree_listing.encode("utf-8")).hexdigest()
            except (subprocess.CalledProcessError, FileNotFoundError):
                current_hash = "unknown"
            if current_hash != recorded_hash:
                return True, f"tree hash mismatch for dir: {dir_path!r}"

    return False, ""


# ── main claim logic ───────────────────────────────────────────────────────────

def do_claim(
    entry_id: str,
    run_id: str,
    sink_root: Path,
    allow_stale: bool,
    staleness_commit_window: int = STALENESS_COMMIT_WINDOW_DEFAULT,
) -> int:
    """
    Execute the full claim sequence per SPEC.

    Lock-ordering invariant: per-entry first, then global.

    Returns an exit code.
    """
    # ── validation ─────────────────────────────────────────────────────────────
    if not entry_id:
        print("sink-claim: --entry is required", file=sys.stderr)
        return EXIT_VALIDATION

    if not run_id:
        print("sink-claim: --run is required", file=sys.stderr)
        return EXIT_VALIDATION

    if not sink_root or not sink_root.is_dir():
        print(f"sink-claim: --sink-root must be an existing directory: {sink_root}", file=sys.stderr)
        return EXIT_VALIDATION

    pages_dir = sink_root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    lock_path = pages_dir / f"{entry_id}.lock"
    entry_lock_holder = f"sink-claim-{run_id}-{os.getpid()}"

    # ── step 1: acquire per-entry lock FIRST (mandatory lock-ordering) ─────────
    try:
        entry_lock_rc = acquire_entry_lock(lock_path, entry_lock_holder)
    except TimeoutError as exc:
        print(f"sink-claim: {exc}", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT

    stale_takeover = (entry_lock_rc == 2)

    # ── step 2: re-read entry from materialized view AFTER acquiring lock ───────
    entry = get_entry(sink_root, entry_id)
    if entry is None:
        # Entry not found — release per-entry lock and bail
        _run_sink_lock("release", str(lock_path))
        print(f"sink-claim: entry not found in view: {entry_id!r}", file=sys.stderr)
        return EXIT_NOT_CLAIMABLE

    current_status = entry.get("status")

    # ── step 3: stale-takeover edge ─────────────────────────────────────────────
    # sink-lock.sh returned exit 2 (stale-takeover). Current status was `running`
    # with a dead/stale holder. We must append recovery events and re-check status.
    if stale_takeover:
        # The prior holder is dead; log takeover events (under global lock)
        global_holder_id = f"sink-claim-global-{run_id}-{os.getpid()}"
        try:
            global_fd = acquire_global_lock(GLOBAL_LOCK_FILE, global_holder_id)
        except TimeoutError as exc:
            _run_sink_lock("release", str(lock_path))
            print(f"sink-claim: {exc}", file=sys.stderr)
            return EXIT_LOCK_TIMEOUT

        try:
            append_event(sink_root, {
                "kind": "status_changed",
                "entry_id": entry_id,
                "from": "running",
                "to": "open",
                "by": "auto_recovery",
                "reason": "stale_lock_takeover",
            })
            append_event(sink_root, {
                "kind": "followup_lock_takeover",
                "entry_id": entry_id,
                "by": "auto_recovery",
                "prior_holder": entry.get("claimed_by_run", "unknown"),
            })
            rebuild_view(sink_root)
        finally:
            release_global_lock(global_fd, GLOBAL_LOCK_FILE)

        # Re-read entry after recovery events
        entry = get_entry(sink_root, entry_id)
        if entry is None:
            _run_sink_lock("release", str(lock_path))
            print(f"sink-claim: entry disappeared after recovery: {entry_id!r}", file=sys.stderr)
            return EXIT_NOT_CLAIMABLE
        current_status = entry.get("status")

    # ── step 4: depth-1 refusal ─────────────────────────────────────────────────
    if entry.get("depth", 0) == 1:
        _run_sink_lock("release", str(lock_path))
        print(
            f"sink-claim: entry {entry_id!r} has depth=1 and is inert; "
            "consumer refuses to claim depth-1 entries",
            file=sys.stderr,
        )
        return EXIT_DEPTH_1

    # ── step 5: status must be open ─────────────────────────────────────────────
    if current_status != "open":
        _run_sink_lock("release", str(lock_path))
        print(
            f"sink-claim: entry {entry_id!r} is not claimable; "
            f"status={current_status!r}",
            file=sys.stderr,
        )
        return EXIT_NOT_CLAIMABLE

    # ── step 6: staleness check ──────────────────────────────────────────────────
    is_stale, stale_reason = check_staleness(entry, staleness_commit_window)
    if is_stale and not allow_stale:
        _run_sink_lock("release", str(lock_path))
        print(
            f"sink-claim: staleness drift detected for entry {entry_id!r}: {stale_reason}",
            file=sys.stderr,
        )
        print(
            "  Pass --allow-stale to proceed anyway "
            "(caller should prompt user before retrying)",
            file=sys.stderr,
        )
        return EXIT_STALE_DRIFT

    # ── step 7: acquire global lock (SECOND — preserving lock order) ─────────────
    global_holder_id = f"sink-claim-global-{run_id}-{os.getpid()}"
    try:
        global_fd = acquire_global_lock(GLOBAL_LOCK_FILE, global_holder_id)
    except TimeoutError as exc:
        _run_sink_lock("release", str(lock_path))
        print(f"sink-claim: {exc}", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT

    claim_ts = iso_now()
    try:
        # ── step 8: append status_changed open→running event ──────────────────
        append_event(sink_root, {
            "kind": "status_changed",
            "entry_id": entry_id,
            "from": "open",
            "to": "running",
            "by": run_id,
            "claimed_by_run": run_id,
        })

        # ── step 9: rebuild materialized view under global lock ───────────────
        rebuild_view(sink_root)

    finally:
        # ── step 10: release global lock ──────────────────────────────────────
        release_global_lock(global_fd, GLOBAL_LOCK_FILE)

    # Per-entry lock remains held — caller responsibility to heartbeat + release.

    # ── step 11: print claim ticket to stdout ─────────────────────────────────
    # Read the holder record from the per-entry lock file to include identity
    # fields (holder + pid) in the ticket.  These are used by verify_per_entry_lock()
    # in sink-status-set-impl.py to confirm the caller is the actual lock holder.
    lock_holder_record = _read_lock_holder_record(lock_path)
    if lock_holder_record is None:
        print(
            f"sink-claim: per-entry lock file for {entry_id!r} is unreadable or missing "
            f"required holder/pid fields after successful claim; "
            f"refusing to emit an unverifiable ticket",
            file=sys.stderr,
        )
        return EXIT_VALIDATION
    ticket: dict = {
        "entry_id": entry_id,
        "run_id": run_id,
        "claim_ts": claim_ts,
        "lock_path": str(lock_path),
        "ttl_s": STALE_TTL_SECONDS,
        "holder": lock_holder_record["holder"],
        "pid": lock_holder_record["pid"],
    }
    print(json.dumps(ticket))
    return EXIT_SUCCESS


# ── arg parsing + entry point ──────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sink-claim-helpers",
        description="Atomic open→running claim for a follow-up entry",
    )
    parser.add_argument("--entry", default="")
    parser.add_argument("--run", default="")
    parser.add_argument("--sink-root", default="", dest="sink_root")
    parser.add_argument("--allow-stale", default="false", dest="allow_stale")
    args = parser.parse_args(argv)

    entry_id = args.entry
    run_id = args.run
    sink_root_str = args.sink_root
    allow_stale = args.allow_stale == "true"

    if not entry_id:
        print("sink-claim: --entry is required", file=sys.stderr)
        return EXIT_VALIDATION

    if not run_id:
        print("sink-claim: --run is required", file=sys.stderr)
        return EXIT_VALIDATION

    if not sink_root_str:
        print("sink-claim: --sink-root is required", file=sys.stderr)
        return EXIT_VALIDATION

    sink_root = Path(sink_root_str)
    if not sink_root.exists():
        print(f"sink-claim: sink-root does not exist: {sink_root_str!r}", file=sys.stderr)
        return EXIT_VALIDATION

    if not sink_root.is_dir():
        print(f"sink-claim: sink-root is not a directory: {sink_root_str!r}", file=sys.stderr)
        return EXIT_VALIDATION

    # Read staleness commit window from config if available; fall back to default
    try:
        config_result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "config.py"), "get",
             "followup.staleness_commit_window"],
            capture_output=True, text=True,
        )
        if config_result.returncode == 0:
            staleness_commit_window = int(config_result.stdout.strip())
        else:
            staleness_commit_window = STALENESS_COMMIT_WINDOW_DEFAULT
    except (ValueError, subprocess.SubprocessError, FileNotFoundError):
        staleness_commit_window = STALENESS_COMMIT_WINDOW_DEFAULT

    return do_claim(entry_id, run_id, sink_root, allow_stale, staleness_commit_window)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
