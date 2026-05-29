#!/usr/bin/env python3
"""
scripts/sink-status-set-impl.py — Implementation for sink-status-set.sh.

Called by sink-status-set.sh with parsed flags.

Exit codes:
  0  success
  2  validation error (missing/invalid args)
  3  illegal transition (state machine violation)
  4  evidence rejected
  5  lock-timeout
  6  completion-mode conflict (mutex violation)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ── constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent

# Robust import for scripts invoked as standalone via `python3 scripts/sink-status-set-impl.py`
sys.path.insert(0, str(SCRIPT_DIR))
from followup_common import (  # noqa: E402
    iso_now,
    _get_config_bool,
    _get_config_str,
    _log_event_sh,
    _notion_push_entry_bg,
    acquire_global_lock,
    release_global_lock,
)

GLOBAL_LOCK_FILE = Path(os.environ.get(
    "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK",
    str(Path.home() / ".z-harness" / ".followup-vs-implement.lock"),
))

LOCK_TIMEOUT_SECONDS = 30

VALID_STATUSES = frozenset({
    "open", "running", "verify", "done", "failed", "blocked", "dismissed"
})

VALID_COMPLETION_MODES = frozenset({
    "human_confirmed", "audit_confirmed", "auto_closed_low_risk"
})

# State machine: {from_status: {to_status: True/False}}
# Each edge also carries actor requirements (validated contextually)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open":     {"running", "dismissed"},
    "running":  {"verify", "failed", "blocked", "open", "dismissed"},
    "verify":   {"done", "blocked", "dismissed"},
    "failed":   {"open", "dismissed"},
    "blocked":  {"open", "dismissed"},
    "done":     {"dismissed"},      # terminal but dismissed is always allowed
}


# ── helpers ────────────────────────────────────────────────────────────────────

def die(msg: str, code: int) -> None:
    print(f"sink-status-set: ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_view(sink_root: Path) -> dict:
    view_path = sink_root / "index.view.json"
    if not view_path.exists():
        return {"entries": {}}
    with view_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def rebuild_view(sink_root: Path) -> None:
    """Rebuild index.view.json by calling sink-view-rebuild.sh (must be under global lock)."""
    rebuild_sh = SCRIPT_DIR / "sink-view-rebuild.sh"
    result = subprocess.run(
        ["bash", str(rebuild_sh), str(sink_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"sink-status-set: WARNING: view rebuild exited {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )




def _read_lock_holder_record(lock_path: Path) -> dict | None:
    """Read the per-entry lock file and return the holder record dict, or None.

    Returns a dict with at least ``holder`` (str) and ``pid`` (int) if the
    lock file contains a valid T001 holder record.  Returns None if the file
    is missing, empty, unparseable, or lacks the required fields.
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


def verify_per_entry_lock(sink_root: Path, entry_id: str, via_claim_ticket: str) -> None:
    """
    Verify the per-entry lock is held by checking the claim ticket, or re-acquire it.

    Claim-ticket path (--via-claim-ticket provided):
      The ticket must carry ``entry_id``, ``lock_path``, ``holder``, and ``pid``
      matching the T001 holder-record contract.  The lock file is read and its
      ``holder`` + ``pid`` fields must match the ticket's values exactly.
      Any mismatch — wrong holder, wrong pid, wrong entry_id, or wrong lock_path
      — causes an immediate exit(2).

    No-ticket path: re-acquires via sink-lock.sh (existing behaviour preserved).
    """
    lock_path = sink_root / "pages" / f"{entry_id}.lock"

    if via_claim_ticket:
        try:
            ticket = json.loads(via_claim_ticket)
        except json.JSONDecodeError:
            die(f"--via-claim-ticket is not valid JSON: {via_claim_ticket!r}", 2)

        if not isinstance(ticket, dict):
            die(
                f"--via-claim-ticket must be a JSON object, got {type(ticket).__name__}: "
                f"{via_claim_ticket!r}",
                2,
            )

        # ── (1) entry_id must match ────────────────────────────────────────────
        ticket_entry_id = ticket.get("entry_id")
        if ticket_entry_id != entry_id:
            die(
                f"claim ticket entry_id {ticket_entry_id!r} does not match --entry={entry_id!r}",
                2,
            )

        # ── (2) lock_path must match expected path for this entry ──────────────
        ticket_lock_path = ticket.get("lock_path")
        if ticket_lock_path != str(lock_path):
            die(
                f"claim ticket lock_path {ticket_lock_path!r} does not match "
                f"expected path {str(lock_path)!r} for entry {entry_id!r}",
                2,
            )

        # ── (3) holder + pid identity check against live lock file ────────────
        ticket_holder = ticket.get("holder")
        ticket_pid = ticket.get("pid")

        if ticket_holder is None or ticket_pid is None:
            die(
                f"claim ticket for entry {entry_id!r} is missing required identity fields "
                f"(holder, pid); ticket cannot be verified",
                2,
            )

        live_record = _read_lock_holder_record(lock_path)
        if live_record is None:
            die(
                f"per-entry lock file for {entry_id!r} is missing or unreadable; "
                f"cannot verify claim ticket identity",
                2,
            )

        if live_record["holder"] != ticket_holder:
            die(
                f"claim ticket holder {ticket_holder!r} does not match lock file "
                f"holder {live_record['holder']!r} for entry {entry_id!r}",
                2,
            )

        if live_record["pid"] != ticket_pid:
            die(
                f"claim ticket pid {ticket_pid!r} does not match lock file "
                f"pid {live_record['pid']!r} for entry {entry_id!r}",
                2,
            )

        # All identity checks passed — the ticket is valid.
        return
    else:
        # No ticket — re-acquire per-entry lock
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        _reacquire_per_entry_lock(lock_path, entry_id)


def _reacquire_per_entry_lock(lock_path: Path, entry_id: str) -> None:
    """Attempt to acquire the per-entry lock via sink-lock.sh."""
    sink_lock_sh = SCRIPT_DIR / "sink-lock.sh"
    result = subprocess.run(
        ["bash", str(sink_lock_sh), "acquire", str(lock_path), f"sink-status-set:{entry_id}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 or result.returncode == 2:
        # 0 = acquired clean, 2 = stale-takeover (also acquired)
        return
    if result.returncode == 1:
        die(
            f"per-entry lock for {entry_id!r} is held by another process; "
            "try again after that process completes",
            5,
        )
    die(
        f"sink-lock acquire for {entry_id!r} returned unexpected exit code {result.returncode}: "
        f"{result.stderr.strip()}",
        5,
    )


def call_audit_validate(evidence_path: str, entry_data: dict, sink_root: Path) -> dict:
    """Invoke sink-audit-validate.py; return its JSON result dict."""
    validate_py = SCRIPT_DIR / "sink-audit-validate.py"

    # Write entry to a temp file for the validator
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(entry_data, tf)
        entry_tmp = tf.name

    try:
        result = subprocess.run(
            [sys.executable, str(validate_py), evidence_path, entry_tmp],
            capture_output=True,
            text=True,
        )
        if result.returncode not in (0, 1):
            return {
                "passed": False,
                "rejected_check": None,
                "reason": f"validator exited {result.returncode}: {result.stderr.strip()}",
            }
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "passed": False,
                "rejected_check": None,
                "reason": f"validator returned non-JSON output: {result.stdout!r}",
            }
    finally:
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass


def _repo_root() -> Path:
    """Return the git repository root (best-effort)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def call_auto_close_check(entry_data: dict, diff_path: str = "") -> dict:
    """Invoke sink-auto-close-check.py with the real cumulative diff.

    ``diff_path`` must be the path to a non-empty diff file produced by the
    caller.  When the caller omits ``--diff`` (empty string or missing file)
    the check is failed immediately — "caller forgot to pass a diff" must not
    masquerade as "command changed nothing" (noop approval).
    """
    if not diff_path:
        return {
            "passed": False,
            "reason": "auto-close requires --diff=<path>; no diff was provided",
        }
    if not Path(diff_path).is_file():
        return {
            "passed": False,
            "reason": f"auto-close diff file not found: {diff_path!r}",
        }

    auto_close_py = SCRIPT_DIR / "sink-auto-close-check.py"

    # Write entry to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(entry_data, tf)
        entry_tmp = tf.name

    try:
        result = subprocess.run(
            [
                sys.executable, str(auto_close_py),
                f"--entry={entry_tmp}",
                f"--diff={diff_path}",
                "--test-exit=0",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode not in (0, 1):
            return {
                "passed": False,
                "reason": f"auto-close-check exited {result.returncode}: {result.stderr.strip()}",
            }
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "passed": False,
                "reason": f"auto-close-check returned non-JSON output: {result.stdout!r}",
            }
    finally:
        try:
            os.unlink(entry_tmp)
        except OSError:
            pass


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sink-status-set-impl",
        description="Status transition primitive for the follow-up sink",
    )
    parser.add_argument("--entry", default="")
    parser.add_argument("--to", default="")
    parser.add_argument("--by", default="")
    parser.add_argument("--sink-root", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--completion-mode", default="")
    parser.add_argument("--via-claim-ticket", default="")
    parser.add_argument("--diff", default="")
    args = parser.parse_args()

    entry_id = args.entry
    to_status = args.to
    by_actor = args.by
    sink_root_str = args.sink_root
    evidence = args.evidence
    reason = args.reason
    completion_mode = args.completion_mode
    via_claim_ticket = args.via_claim_ticket
    diff_path = args.diff

    # ── validation ─────────────────────────────────────────────────────────────

    if not entry_id:
        die("--entry is required", 2)
    if not to_status:
        die("--to is required", 2)
    if not by_actor:
        die("--by is required", 2)
    if not sink_root_str:
        die("--sink-root is required", 2)

    if to_status not in VALID_STATUSES:
        die(f"--to must be one of {sorted(VALID_STATUSES)}, got: {to_status!r}", 2)

    if completion_mode and completion_mode not in VALID_COMPLETION_MODES:
        die(
            f"--completion-mode must be one of {sorted(VALID_COMPLETION_MODES)}, "
            f"got: {completion_mode!r}",
            2,
        )

    sink_root = Path(sink_root_str)
    if not sink_root.exists():
        die(f"--sink-root does not exist: {sink_root_str!r}", 2)

    # ── per-entry lock: must hold before global (SPEC lock-ordering invariant) ──
    # Step 1: verify/acquire per-entry lock FIRST
    verify_per_entry_lock(sink_root, entry_id, via_claim_ticket)

    # ── acquire global lock ───────────────────────────────────────────────────
    try:
        global_fd = acquire_global_lock(
            GLOBAL_LOCK_FILE,
            f"sink-status-set-{os.getpid()}",
            LOCK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        die(
            f"timed out waiting for global lock {GLOBAL_LOCK_FILE} after {LOCK_TIMEOUT_SECONDS}s; "
            "is another z-harness operation running? (try /z-followup-status)",
            5,
        )
    try:
        # Re-read view under global lock for current state
        view = load_view(sink_root)
        entries = view.get("entries", {})

        if entry_id not in entries:
            die(f"entry {entry_id!r} not found in sink view at {sink_root_str!r}", 2)

        entry = entries[entry_id]
        current_status = entry.get("status", "")

        # ── state machine validation ─────────────────────────────────────────
        allowed_targets = ALLOWED_TRANSITIONS.get(current_status, set())
        if to_status not in allowed_targets:
            err_msg = (
                f"illegal transition: {current_status!r} → {to_status!r}; "
                f"allowed from {current_status!r}: {sorted(allowed_targets) if allowed_targets else '(none)'}"
            )
            print(
                json.dumps({
                    "error": "illegal_transition",
                    "from": current_status,
                    "to": to_status,
                    "reason": err_msg,
                }),
                file=sys.stderr,
            )
            sys.exit(3)

        # ── completion_mode mutex for verify → done ───────────────────────────
        if current_status == "verify" and to_status == "done":
            current_completion_mode = entry.get("completion_mode")
            if current_completion_mode is not None:
                err_msg = (
                    f"completion_mode mutex conflict: entry already has "
                    f"completion_mode={current_completion_mode!r}; "
                    f"cannot set to {completion_mode!r}"
                )
                print(
                    json.dumps({
                        "error": "completion_mode_conflict",
                        "existing_mode": current_completion_mode,
                        "requested_mode": completion_mode,
                        "reason": err_msg,
                    }),
                    file=sys.stderr,
                )
                sys.exit(6)

            if not completion_mode:
                die(
                    "verify → done transition requires --completion-mode; "
                    "use one of: human_confirmed, audit_confirmed, auto_closed_low_risk",
                    2,
                )

            # ── evidence validation per completion_mode ───────────────────────
            if completion_mode == "human_confirmed":
                # No evidence required
                pass

            elif completion_mode == "audit_confirmed":
                if not evidence:
                    die(
                        "completion_mode=audit_confirmed requires --evidence=<path to audit_evidence.json>",
                        4,
                    )
                if not Path(evidence).exists():
                    die(f"evidence file does not exist: {evidence!r}", 4)

                audit_result = call_audit_validate(evidence, entry, sink_root)
                if not audit_result.get("passed", False):
                    rejected_check = audit_result.get("rejected_check")
                    reason_str = audit_result.get("reason", "unknown")
                    print(
                        json.dumps({
                            "error": "audit_evidence_rejected",
                            "rejected_check": rejected_check,
                            "reason": reason_str,
                        }),
                        file=sys.stderr,
                    )
                    sys.exit(4)

            elif completion_mode == "auto_closed_low_risk":
                auto_result = call_auto_close_check(entry, diff_path=diff_path)
                if not auto_result.get("passed", False):
                    reason_str = auto_result.get("reason", "unknown")
                    print(
                        json.dumps({
                            "error": "auto_close_ceiling_failed",
                            "reason": reason_str,
                        }),
                        file=sys.stderr,
                    )
                    sys.exit(4)

        # ── build status_changed event ────────────────────────────────────────
        event: dict = {
            "kind": "status_changed",
            "ts": iso_now(),
            "entry_id": entry_id,
            "from": current_status,
            "to": to_status,
            "by": by_actor,
        }
        if reason:
            event["reason"] = reason
        if completion_mode and current_status == "verify" and to_status == "done":
            event["completion_mode"] = completion_mode
        if to_status == "done":
            event["closed_at"] = event["ts"]
            event["closed_by_run"] = os.environ.get("Z_HARNESS_RUN_ID", by_actor)
        if to_status == "failed":
            if reason:
                event["failure_reason"] = reason
            event["attempt_count"] = entry.get("attempt_count", 0) + 1

        # ── append event to journal ───────────────────────────────────────────
        journal_path = sink_root / "index.jsonl"
        append_jsonl(journal_path, event)

        # ── rebuild view under global lock ────────────────────────────────────
        rebuild_view(sink_root)

    finally:
        release_global_lock(global_fd, GLOBAL_LOCK_FILE)

    # ── best-effort Notion sync (backgrounded — does not block the caller) ────
    proj_root = _repo_root()
    if _get_config_bool("followup.notion_enabled", proj_root):
        # Re-read updated entry from view for accurate notion_remote_id
        updated_view = load_view(sink_root)
        updated_entry = updated_view.get("entries", {}).get(entry_id, entry)
        _notion_push_entry_bg(updated_entry, sink_root, proj_root)

    print(
        json.dumps({
            "ok": True,
            "entry_id": entry_id,
            "from": current_status,
            "to": to_status,
            "ts": event["ts"],
        })
    )


if __name__ == "__main__":
    main()
