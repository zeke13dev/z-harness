#!/usr/bin/env python3
"""
scripts/sink-view-reducer.py — replay reducer for the follow-up sink.

Reads <sink-root>/index.jsonl line by line, applies events in order,
and writes the materialized view to <sink-root>/index.view.json via
an atomic tmpfile-then-rename.

Known event kinds:
  entry_created        — creates a new entry in the view
  entry_refreshed      — updates capture_head and file_blob_hashes or dir_blob_hashes
  status_changed       — updates status + appends to status_history
  evidence_attached    — records audit_evidence_path
  dismissed            — terminal status change (synonym for status_changed to dismissed)
  closed               — terminal status change (synonym for status_changed to done/closed)
  notion_sync_pending  — sets notion_sync_pending=True on an entry
  notion_synced        — sets notion_sync_pending=False after a successful Notion push
  notion_sync_cleared  — sets notion_sync_pending=False (explicit clear)

Unknown event kinds: logged to stderr as warnings, then skipped. Never crash.

Forward-compat: unknown fields in known event types are ignored silently.

Exit codes:
  0  success (view written or journal absent/empty)
  1  argument error
  2  sink-root not found or not a directory
  3  journal corruption detected (non-parseable line); index.view.json left untouched
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


# ── helpers ────────────────────────────────────────────────────────────────────

KNOWN_EVENT_KINDS = frozenset({
    "entry_created",
    "entry_refreshed",
    "status_changed",
    "evidence_attached",
    "dismissed",
    "closed",
    "notion_sync_pending",
    "notion_synced",
    "notion_sync_cleared",
})


def _warn(msg: str) -> None:
    print(f"sink-view-reducer: WARNING: {msg}", file=sys.stderr)


def _log_event_sh(event_kind: str, payload: dict, sink_root: Path | None = None) -> None:
    """Emit a structured event via scripts/log-event.sh (best-effort, unconditional).

    Attempts log-event.sh when Z_HARNESS_RUN is set. Falls back to appending
    the event directly to <sink_root>/events.jsonl (if sink_root is provided)
    so the event is always observable even in direct-CLI / test contexts.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    logged_via_sh = False
    if run_id:
        log_event_sh = SCRIPT_DIR / "log-event.sh"
        if log_event_sh.exists():
            try:
                subprocess.run(
                    ["bash", str(log_event_sh), run_id, event_kind, json.dumps(payload)],
                    capture_output=True,
                    check=False,
                )
                logged_via_sh = True
            except OSError:
                pass

    # Fallback: write directly to <sink_root>/events.jsonl so the event is
    # always recorded regardless of whether a harness run context is active.
    if not logged_via_sh and sink_root is not None:
        try:
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            obj = {"ts": ts, "kind": event_kind}
            obj.update(payload)
            line = json.dumps(obj, separators=(",", ":")) + "\n"
            events_path = sink_root / "events.jsonl"
            events_path.parent.mkdir(parents=True, exist_ok=True)
            with events_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def _apply_entry_created(entries: dict, event: dict) -> None:
    """Create a new entry from an entry_created event."""
    entry = event.get("entry")
    if not entry:
        _warn("entry_created event missing 'entry' field; skipping")
        return
    entry_id = entry.get("id")
    if not entry_id:
        _warn("entry_created event: entry missing 'id' field; skipping")
        return
    # Copy the entry as-is; reducer does not validate schema beyond id
    entries[entry_id] = dict(entry)


def _apply_status_changed(entries: dict, event: dict) -> None:
    """Apply a status_changed (or dismissed / closed) event."""
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn(f"status_changed event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"status_changed for unknown entry '{entry_id}'; skipping")
        return
    entry = entries[entry_id]
    new_status = event.get("to")
    if new_status is None:
        _warn(f"status_changed event for '{entry_id}' missing 'to' field; skipping")
        return
    old_status = entry.get("status")
    entry["status"] = new_status
    # Append to status_history
    hist_entry: dict = {
        "ts": event.get("ts", ""),
        "from": old_status,
        "to": new_status,
        "by": event.get("by", ""),
    }
    if "reason" in event:
        hist_entry["reason"] = event["reason"]
    if "status_history" not in entry or entry["status_history"] is None:
        entry["status_history"] = []
    entry["status_history"].append(hist_entry)
    # Optional fields carried by the event
    for field in ("completion_mode", "failure_reason", "closed_at", "closed_by_run", "attempt_count"):
        if field in event:
            entry[field] = event[field]
    # M2: done → dismissed audit-trail marker.
    # When an entry transitions from done to dismissed, keep the done-era
    # closed_at / completion_mode intact (they are audit evidence) and stamp
    # dismissed_after_done=True so metrics consumers can distinguish "dismissed
    # after being completed" from "dismissed before reaching done".
    # The marker is applied ONLY on the done → dismissed edge, not for any
    # other source state (open/running/verify/failed → dismissed).
    if old_status == "done" and new_status == "dismissed":
        entry["dismissed_after_done"] = True


def _apply_evidence_attached(entries: dict, event: dict) -> None:
    """Record evidence path on the entry."""
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn("evidence_attached event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"evidence_attached for unknown entry '{entry_id}'; skipping")
        return
    evidence_path = event.get("evidence_path")
    if evidence_path is not None:
        entries[entry_id]["audit_evidence_path"] = evidence_path


def _apply_entry_refreshed(entries: dict, event: dict) -> None:
    """Apply an entry_refreshed event: update capture_head and blob hashes.

    Expected payload (matches z-followup-refresh.md Phase 6 wire format):
      entry_id          — required; identifies the entry to update
      new_capture_head  — required; new git HEAD SHA for the capture snapshot
      new_file_blob_hashes — mutually exclusive with new_dir_blob_hashes; dict of
                             rel_path → "sha256:<64 hex>" content hashes for cited files
      new_dir_blob_hashes  — mutually exclusive with new_file_blob_hashes; dict of
                             rel_path → "sha256:<64 hex>" content hashes for a dir tree

    Exactly one of new_file_blob_hashes or new_dir_blob_hashes must be present.
    When file hashes are provided, dir_blob_hashes is cleared (set to None).
    When dir hashes are provided, file_blob_hashes is cleared (set to None).
    """
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn("entry_refreshed event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"entry_refreshed for unknown entry '{entry_id}'; skipping")
        return
    new_capture_head = event.get("new_capture_head")
    if new_capture_head is None:
        _warn(f"entry_refreshed event for '{entry_id}' missing 'new_capture_head'; skipping")
        return

    has_file = "new_file_blob_hashes" in event and event["new_file_blob_hashes"] is not None
    has_dir = "new_dir_blob_hashes" in event and event["new_dir_blob_hashes"] is not None

    if has_file and has_dir:
        _warn(
            f"entry_refreshed event for '{entry_id}' has both "
            "'new_file_blob_hashes' and 'new_dir_blob_hashes'; "
            "exactly one must be present — skipping event"
        )
        return
    if not has_file and not has_dir:
        _warn(
            f"entry_refreshed event for '{entry_id}' missing both "
            "'new_file_blob_hashes' and 'new_dir_blob_hashes'; "
            "exactly one must be present — skipping event"
        )
        return

    # Validation passed — now mutate the entry
    entry = entries[entry_id]
    entry["capture_head"] = new_capture_head
    if has_file:
        entry["file_blob_hashes"] = event["new_file_blob_hashes"]
        entry["dir_blob_hashes"] = None
    else:
        entry["dir_blob_hashes"] = event["new_dir_blob_hashes"]
        entry["file_blob_hashes"] = None


def _apply_dismissed(entries: dict, event: dict) -> None:
    """Dismissed is a terminal status_changed variant."""
    merged = dict(event)
    merged.setdefault("to", "dismissed")
    _apply_status_changed(entries, merged)


def _apply_closed(entries: dict, event: dict) -> None:
    """Closed is a terminal status_changed variant."""
    merged = dict(event)
    # closed events should carry 'to'; default to 'done' if absent
    merged.setdefault("to", "done")
    _apply_status_changed(entries, merged)


def _apply_notion_sync_pending(entries: dict, event: dict) -> None:
    """Mark an entry as having a pending Notion sync."""
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn("notion_sync_pending event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"notion_sync_pending for unknown entry '{entry_id}'; skipping")
        return
    entries[entry_id]["notion_sync_pending"] = True


def _apply_notion_synced(entries: dict, event: dict) -> None:
    """Clear the pending Notion sync flag after a successful push."""
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn("notion_synced event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"notion_synced for unknown entry '{entry_id}'; skipping")
        return
    entries[entry_id]["notion_sync_pending"] = False


def _apply_notion_sync_cleared(entries: dict, event: dict) -> None:
    """Clear the pending Notion sync flag (explicit clear event)."""
    entry_id = event.get("entry_id")
    if not entry_id:
        _warn("notion_sync_cleared event missing 'entry_id'; skipping")
        return
    if entry_id not in entries:
        _warn(f"notion_sync_cleared for unknown entry '{entry_id}'; skipping")
        return
    entries[entry_id]["notion_sync_pending"] = False


_HANDLERS = {
    "entry_created": _apply_entry_created,
    "entry_refreshed": _apply_entry_refreshed,
    "status_changed": _apply_status_changed,
    "evidence_attached": _apply_evidence_attached,
    "dismissed": _apply_dismissed,
    "closed": _apply_closed,
    "notion_sync_pending": _apply_notion_sync_pending,
    "notion_synced": _apply_notion_synced,
    "notion_sync_cleared": _apply_notion_sync_cleared,
}


# ── main reducer ───────────────────────────────────────────────────────────────

class JournalCorruptionError(Exception):
    """Raised when a non-parseable line is detected in the journal."""

    def __init__(self, lineno: int, raw: str, is_final_line: bool, sink_root: Path | None = None) -> None:
        self.lineno = lineno
        self.raw = raw
        self.is_final_line = is_final_line
        self.sink_root = sink_root
        position = "final" if is_final_line else "interior"
        super().__init__(
            f"line {lineno}: JSON parse error on {position} line; "
            "refusing to rebuild view from corrupted journal"
        )


def reduce_journal(journal_path: Path, sink_root: Path | None = None) -> dict:
    """Read journal_path line-by-line and return the reduced state dict.

    Raises JournalCorruptionError if a non-parseable line is found. The caller
    must NOT call write_view() after catching this error — the existing
    index.view.json must be left untouched.
    """
    entries: dict = {}

    if not journal_path.exists():
        return entries

    lines: list[str] = journal_path.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            is_final = lineno == total_lines
            raise JournalCorruptionError(
                lineno=lineno,
                raw=raw,
                is_final_line=is_final,
                sink_root=sink_root,
            )
        if not isinstance(event, dict):
            _warn(f"line {lineno}: event is not a JSON object; skipping")
            continue
        kind = event.get("kind")
        if kind not in KNOWN_EVENT_KINDS:
            _warn(f"line {lineno}: unknown event kind '{kind}'; skipping")
            continue
        handler = _HANDLERS[kind]
        handler(entries, event)

    return entries


def reduce_lines(lines: list[str], sink_root: Path | None = None) -> dict:
    """Reduce a pre-loaded list of raw lines (used by --repair path)."""
    entries: dict = {}
    total_lines = len(lines)
    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            is_final = lineno == total_lines
            raise JournalCorruptionError(
                lineno=lineno,
                raw=raw,
                is_final_line=is_final,
                sink_root=sink_root,
            )
        if not isinstance(event, dict):
            _warn(f"line {lineno}: event is not a JSON object; skipping")
            continue
        kind = event.get("kind")
        if kind not in KNOWN_EVENT_KINDS:
            _warn(f"line {lineno}: unknown event kind '{kind}'; skipping")
            continue
        handler = _HANDLERS[kind]
        handler(entries, event)
    return entries


def _prefix_and_tail(data: bytes) -> tuple[int, str | None, int]:
    """Locate the newline-aligned complete prefix of raw journal bytes.

    Returns ``(prefix_byte_length, tail_sha256, tail_len)`` where:
      - ``prefix_byte_length`` is the offset just past the LAST ``\\n`` in ``data``
        (i.e. the byte length of the maximal complete, newline-terminated prefix).
        0 if ``data`` contains no newline.
      - ``tail_sha256`` is the hex sha256 of the final complete line's bytes
        (the segment between the last two newlines, INCLUDING its trailing ``\\n``),
        or None when ``prefix_byte_length == 0``.
      - ``tail_len`` is the byte length of that final complete line (incl. ``\\n``),
        or 0 when ``prefix_byte_length == 0``.

    The tail fingerprint lets the incremental path verify that the journal's stored
    prefix is byte-identical at the checkpoint boundary before trusting it — which
    (a) anchors the resume offset to a real newline boundary (so appended events can
    never be silently merged onto an unterminated tail) and (b) detects same-length
    rewrites/compaction that a byte-length comparison alone would miss.
    """
    prefix_byte_length = data.rfind(b"\n") + 1  # 0 when no newline present
    if prefix_byte_length <= 0:
        return 0, None, 0
    prev_nl = data.rfind(b"\n", 0, prefix_byte_length - 1)
    line_start = prev_nl + 1  # 0 when this is the only line
    tail_bytes = data[line_start:prefix_byte_length]
    return prefix_byte_length, hashlib.sha256(tail_bytes).hexdigest(), len(tail_bytes)


def _scan_checkpoint_fields(journal_path: Path) -> dict:
    """Build a fresh checkpoint dict for journal_path via a full byte scan.

    Used by the cold-replay (--full) and --repair paths, which rebuild the whole
    view and therefore must stamp a checkpoint the next incremental pass can resume
    from.  ``event_count`` counts non-empty lines within the complete (newline-
    terminated) prefix only — consistent with the boundary the byte fields describe.
    """
    if not journal_path.exists():
        return {"event_count": 0, "journal_byte_length": 0, "tail_sha256": None, "tail_len": 0}
    data = journal_path.read_bytes()
    prefix_byte_length, tail_sha256, tail_len = _prefix_and_tail(data)
    prefix = data[:prefix_byte_length].decode("utf-8", errors="replace")
    event_count = sum(1 for line in prefix.splitlines() if line.strip())
    return {
        "event_count": event_count,
        "journal_byte_length": prefix_byte_length,
        "tail_sha256": tail_sha256,
        "tail_len": tail_len,
    }


def _load_checkpoint(sink_root: Path) -> tuple[dict, dict | None]:
    """Load the existing view entries and checkpoint from index.view.json.

    Returns:
        (entries, checkpoint) where:
          - entries is the dict of entries keyed by id (may be empty)
          - checkpoint is the stored ``_checkpoint`` dict, or None if absent/invalid

    The checkpoint dict (when present and valid) has:
      - ``event_count`` (int >= 0): number of events already folded into the view
      - ``journal_byte_length`` (int >= 0): newline-aligned byte offset of the prefix
        already folded into the view
      - ``tail_sha256`` (str | None): fingerprint of the final folded line
      - ``tail_len`` (int >= 0): byte length of that final folded line

    A checkpoint is treated as invalid (returns ``(... , None)``) if any required
    field is missing or has the wrong type/sign.  When the entries dict is missing
    or malformed the view itself is untrustworthy, so we return ``({}, None)`` to
    force a full cold replay rather than incrementally extending a bad base.
    """
    view_path = sink_root / "index.view.json"
    if not view_path.exists():
        return {}, None
    try:
        data = json.loads(view_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, None
    if not isinstance(data, dict):
        return {}, None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        # A view with no usable entries dict cannot be a trustworthy incremental
        # base — force a full cold replay.
        return {}, None
    raw_ckpt = data.get("_checkpoint")
    if not isinstance(raw_ckpt, dict):
        return entries, None
    event_count = raw_ckpt.get("event_count")
    journal_byte_length = raw_ckpt.get("journal_byte_length")
    tail_sha256 = raw_ckpt.get("tail_sha256")
    tail_len = raw_ckpt.get("tail_len")
    if not isinstance(event_count, int) or event_count < 0:
        return entries, None
    if not isinstance(journal_byte_length, int) or journal_byte_length < 0:
        return entries, None
    if not isinstance(tail_len, int) or tail_len < 0:
        return entries, None
    # tail_sha256 must be a hex string when there is a non-empty prefix; an empty
    # prefix (journal_byte_length == 0) legitimately has no tail anchor.
    if journal_byte_length > 0:
        if not isinstance(tail_sha256, str) or tail_len <= 0 or tail_len > journal_byte_length:
            return entries, None
    return entries, {
        "event_count": event_count,
        "journal_byte_length": journal_byte_length,
        "tail_sha256": tail_sha256,
        "tail_len": tail_len,
    }


def _apply_event(entries: dict, event: object, lineno: int) -> None:
    """Apply a single parsed event to entries (shared by full + incremental folds)."""
    if not isinstance(event, dict):
        _warn(f"line {lineno}: event is not a JSON object; skipping")
        return
    kind = event.get("kind")
    if kind not in KNOWN_EVENT_KINDS:
        _warn(f"line {lineno}: unknown event kind '{kind}'; skipping")
        return
    _HANDLERS[kind](entries, event)


def _fold_buffer(
    buf: bytes,
    entries: dict,
    base_lineno: int,
    sink_root: Path | None,
) -> int:
    """Fold the journal byte buffer ``buf`` into ``entries`` (mutated in place).

    Complete (newline-terminated) lines are folded and counted; a trailing fragment
    (bytes after the last ``\\n``, i.e. an unterminated final line) is folded too —
    to stay byte-identical with ``reduce_journal`` — but is NOT counted, because the
    checkpoint boundary only advances to newline-aligned positions.

    ``base_lineno`` is the number of journal lines preceding ``buf`` (0 for a full
    replay; the prior event count for an incremental suffix) and only affects the
    line number reported in corruption errors.

    Returns the number of non-empty COMPLETE lines folded.  Raises
    JournalCorruptionError on the first unparseable line (``is_final_line=True``
    only for an unterminated trailing fragment).
    """
    if not buf:
        return 0
    nl = buf.rfind(b"\n")
    complete = buf[: nl + 1] if nl >= 0 else b""
    fragment = buf[nl + 1 :] if nl >= 0 else buf

    folded = 0
    lineno = base_lineno
    if complete:
        # split("\n")[:-1] drops the empty element produced by the trailing newline
        for raw in complete.decode("utf-8").split("\n")[:-1]:
            lineno += 1
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                raise JournalCorruptionError(
                    lineno=lineno,
                    raw=raw,
                    is_final_line=False,
                    sink_root=sink_root,
                )
            folded += 1
            _apply_event(entries, event, lineno)

    frag_raw = fragment.decode("utf-8")
    if frag_raw.strip():
        lineno += 1
        try:
            event = json.loads(frag_raw.strip())
        except json.JSONDecodeError:
            raise JournalCorruptionError(
                lineno=lineno,
                raw=frag_raw,
                is_final_line=True,
                sink_root=sink_root,
            )
        # Parseable but unterminated tail: applied for parity with reduce_journal,
        # but deliberately excluded from the checkpoint count/offset so a later
        # appended event (which will be preceded by this fragment getting its own
        # newline, or will surface as corruption) is re-read rather than merged.
        _apply_event(entries, event, lineno)

    return folded


def reduce_journal_incremental(
    journal_path: Path,
    sink_root: Path | None = None,
) -> tuple[dict, dict]:
    """Read journal_path and apply only post-checkpoint events to the existing view.

    Incremental rebuild strategy:
      1. Load the existing view + ``_checkpoint`` from index.view.json.
      2. Validate the checkpoint against the CURRENT journal:
         - journal now SHORTER than the stored ``journal_byte_length`` → the journal
           was truncated/compacted → full cold replay.
         - the stored prefix boundary no longer matches (the bytes ending at
           ``journal_byte_length`` do not hash to the stored ``tail_sha256``) → the
           prefix was rewritten (compaction that kept the same/greater length) →
           full cold replay.
      3. Incremental path: seek to ``journal_byte_length`` and read ONLY the suffix
         bytes, folding the new events onto the loaded entries — O(new bytes), not
         O(journal).
      4. Full-replay path (cold start / invalid checkpoint / truncation / rewrite):
         read the whole journal and replay from scratch.

    Why a tail fingerprint, not just byte length:
      Byte length alone cannot detect a compaction that produces a journal of the
      same-or-greater size with DIFFERENT prefix content, and a stale byte offset
      could splice newly appended events onto an unterminated tail.  Anchoring the
      resume offset to a verified newline-terminated boundary closes both holes for
      O(tail) extra I/O (a single small read), preserving the O(new bytes) hot path.

    IMPORTANT: This function reads and may write index.view.json WITHOUT acquiring
    the global cross-tool lock.  This is safe ONLY because all callers hold the
    global lock before invoking the reducer.  Do NOT add lock acquisition here.

    NOTE for log compaction (T021): any process that rewrites/compacts index.jsonl
    in place MUST invalidate this checkpoint (delete index.view.json or its
    ``_checkpoint``).  The tail fingerprint defends against same-length rewrites,
    but deleting the checkpoint is the contract that keeps compaction unambiguous.

    Returns:
        (entries, checkpoint) where checkpoint carries ``event_count``,
        ``journal_byte_length``, ``tail_sha256`` and ``tail_len`` for the new state.

    Raises JournalCorruptionError if a non-parseable line is encountered in the
    new (post-checkpoint) events.  The caller must NOT call write_view() then.
    """
    if not journal_path.exists():
        return {}, {"event_count": 0, "journal_byte_length": 0, "tail_sha256": None, "tail_len": 0}

    existing_entries, checkpoint = _load_checkpoint(sink_root or journal_path.parent)

    use_incremental = False
    stored_len = 0
    stored_event_count = 0

    if checkpoint is not None and checkpoint["journal_byte_length"] > 0:
        stored_len = checkpoint["journal_byte_length"]
        stored_event_count = checkpoint["event_count"]
        tail_len = checkpoint["tail_len"]
        with journal_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            current_size = fh.tell()
            if current_size < stored_len:
                _warn(
                    f"incremental checkpoint invalidated: journal byte length "
                    f"{current_size} < stored checkpoint length {stored_len}; "
                    "falling back to full cold replay"
                )
            else:
                fh.seek(stored_len - tail_len)
                actual_tail = fh.read(tail_len)
                if hashlib.sha256(actual_tail).hexdigest() == checkpoint["tail_sha256"]:
                    use_incremental = True
                else:
                    _warn(
                        "incremental checkpoint invalidated: journal prefix boundary no "
                        "longer matches stored tail fingerprint (rewrite/compaction "
                        "detected); falling back to full cold replay"
                    )

    if use_incremental:
        with journal_path.open("rb") as fh:
            fh.seek(stored_len)
            suffix = fh.read()
        # Deep-copy dict values so we never mutate the loaded view's sub-objects.
        entries = {k: dict(v) if isinstance(v, dict) else v for k, v in existing_entries.items()}
        folded = _fold_buffer(suffix, entries, base_lineno=stored_event_count, sink_root=sink_root)
        new_event_count = stored_event_count + folded

        nl = suffix.rfind(b"\n")
        if nl >= 0:
            new_byte_length = stored_len + nl + 1
            prev_nl = suffix.rfind(b"\n", 0, nl)
            tail_bytes = suffix[prev_nl + 1 : nl + 1]
            new_tail_sha256 = hashlib.sha256(tail_bytes).hexdigest()
            new_tail_len = len(tail_bytes)
        else:
            # No new complete line — prefix boundary unchanged.
            new_byte_length = stored_len
            new_tail_sha256 = checkpoint["tail_sha256"]
            new_tail_len = checkpoint["tail_len"]
    else:
        data = journal_path.read_bytes()
        entries = {}
        folded = _fold_buffer(data, entries, base_lineno=0, sink_root=sink_root)
        new_event_count = folded
        new_byte_length, new_tail_sha256, new_tail_len = _prefix_and_tail(data)

    new_checkpoint = {
        "event_count": new_event_count,
        "journal_byte_length": new_byte_length,
        "tail_sha256": new_tail_sha256,
        "tail_len": new_tail_len,
    }
    return entries, new_checkpoint


def write_view(sink_root: Path, entries: dict, checkpoint: dict | None = None) -> None:
    """Write the materialized view atomically via tmpfile+rename.

    IMPORTANT: This function writes index.view.json via atomic tmpfile+rename WITHOUT
    acquiring the global cross-tool lock.  This is safe ONLY because all callers
    (sink-add-helpers.py, sink-claim-helpers.py, sink-status-set-impl.py, and the
    --repair path) already hold the global lock before invoking the reducer.
    Do NOT add lock acquisition here — that is T015's consolidation job, and a
    double-acquire from this function would deadlock. See also _repair_journal() which
    carries the same invariant.

    Args:
        sink_root:   the sink root directory
        entries:     the fully-reduced entries dict (keyed by id)
        checkpoint:  optional dict with keys ``event_count`` (int) and
                     ``journal_byte_length`` (int).  When provided, the checkpoint is
                     embedded in the view file so the next incremental rebuild can skip
                     already-folded events.  When None, no checkpoint is stored (full
                     cold-start semantics — next call will re-replay everything).
    """
    view_path = sink_root / "index.view.json"
    view_data: dict = {"entries": entries}
    if checkpoint is not None:
        view_data["_checkpoint"] = checkpoint
    payload = json.dumps(view_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    # Write to a tmpfile in the same directory, then rename for atomicity.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".index.view.tmp.",
        suffix=".json",
        dir=str(sink_root),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_path_str, str(view_path))
    except BaseException:
        # Clean up the tmpfile if rename (or write) failed
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _repair_journal(journal_path: Path, sink_root: Path) -> list[str]:
    """Strip the broken trailing line from journal_path, rewrite atomically.

    IMPORTANT: This function mutates index.jsonl and MUST be run with the queue
    quiesced / under the caller's global cross-tool lock (manual recovery operation).
    Do NOT acquire the global lock inside this function — callers already hold it and
    a double-acquire would deadlock (see T010/T015).

    Only a truncated TAIL is repairable. This function:
      1. Reads all lines.
      2. Confirms the last non-empty line is the corrupt one by attempting
         to parse each line from the end.
      3. Strips the broken tail line(s).
      4. Logs a followup_journal_repaired event with the dropped content.
      5. Atomically rewrites index.jsonl without the broken tail.

    Returns the repaired line list (ready for reduce_lines).
    Returns an empty list if journal_path does not exist (consistent with normal path).
    Raises RuntimeError if corruption is on an interior (non-tail) line.
    """
    if not journal_path.exists():
        # Consistent with normal (non-repair) path: missing journal → empty view.
        return []

    raw_text = journal_path.read_text(encoding="utf-8")
    lines = raw_text.splitlines()

    # Find the first non-parseable line from the END (tail truncation only)
    drop_from: int | None = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            drop_from = i
        else:
            # First valid line found from end — stop searching
            break

    if drop_from is None:
        # All lines are parseable — nothing to repair
        return lines

    # Verify all lines before drop_from are valid (interior corruption = hard error)
    for i in range(drop_from):
        stripped = lines[i].strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"sink-view-reducer: interior corrupt line {i + 1} found under --repair; "
                "only a truncated tail is repairable. Manual intervention required."
            )

    dropped_lines = lines[drop_from:]
    dropped_content = "\n".join(dropped_lines)
    good_lines = lines[:drop_from]

    # Log the repair event (best-effort, unconditional)
    _log_event_sh(
        "followup_journal_repaired",
        {
            "journal_path": str(journal_path),
            "dropped_from_line": drop_from + 1,
            "dropped_line_count": len(dropped_lines),
            "dropped_content": dropped_content,
            "sink_root": str(sink_root),
        },
        sink_root=sink_root,
    )
    print(
        f"sink-view-reducer: REPAIR: dropped {len(dropped_lines)} corrupt tail line(s) "
        f"starting at line {drop_from + 1}",
        file=sys.stderr,
    )

    # Atomically rewrite journal without the broken tail
    repaired_text = "\n".join(good_lines)
    if good_lines:
        repaired_text += "\n"
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".index.jsonl.repair.tmp.",
        dir=str(journal_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(repaired_text)
        os.replace(tmp_path_str, str(journal_path))
    except BaseException:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise

    return good_lines


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sink-view-reducer.py",
        description="Replay index.jsonl into index.view.json",
    )
    parser.add_argument("sink_root", help="Path to the sink root directory")
    parser.add_argument(
        "--repair",
        action="store_true",
        default=False,
        help=(
            "In repair mode, strip a broken trailing line from index.jsonl "
            "(logging what was dropped) and rebuild the view from the repaired stream. "
            "Only a truncated TAIL is repairable; interior corruption hard-errors even "
            "under --repair."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help=(
            "Force a full cold replay from scratch, ignoring any existing checkpoint. "
            "Useful for diagnostics or after manual journal edits. "
            "The resulting view will still carry an updated checkpoint."
        ),
    )
    args = parser.parse_args()

    sink_root = Path(args.sink_root)
    if not sink_root.exists():
        print(f"sink-view-reducer: ERROR: sink-root not found: {sink_root}", file=sys.stderr)
        return 2
    if not sink_root.is_dir():
        print(f"sink-view-reducer: ERROR: sink-root is not a directory: {sink_root}", file=sys.stderr)
        return 2

    journal_path = sink_root / "index.jsonl"

    if args.repair:
        try:
            good_lines = _repair_journal(journal_path, sink_root)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        # Reduce from the repaired line set (interior lines already validated clean).
        # --repair always does a full cold replay (the journal was just rewritten) and
        # stores a fresh checkpoint so the next incremental update is correct.
        try:
            entries = reduce_lines(good_lines, sink_root=sink_root)
        except JournalCorruptionError as exc:
            # Should not happen after repair, but guard defensively
            print(f"sink-view-reducer: ERROR: unexpected corruption after repair: {exc}", file=sys.stderr)
            return 3
        # Compute a fresh newline-aligned checkpoint (with tail fingerprint) from the
        # just-rewritten journal so the next incremental pass can resume from it.
        checkpoint = _scan_checkpoint_fields(journal_path)
        write_view(sink_root, entries, checkpoint=checkpoint)
        return 0

    # Default (no --repair): incremental rebuild (or forced full replay with --full).
    # Abort on any corruption without touching the view.
    if args.full:
        # Force full cold replay by deleting any existing checkpoint before the call.
        # We do this by temporarily passing a None checkpoint — achieved by calling
        # reduce_journal (the original full-replay function) instead of the incremental one.
        try:
            entries = reduce_journal(journal_path, sink_root=sink_root)
        except JournalCorruptionError as exc:
            position = "final (truncated tail)" if exc.is_final_line else "interior"
            msg = f"sink-view-reducer: ERROR: {exc}; position={position}"
            print(msg, file=sys.stderr)
            _log_event_sh(
                "followup_journal_truncated",
                {
                    "journal_path": str(journal_path),
                    "lineno": exc.lineno,
                    "position": position,
                    "raw_prefix": exc.raw[:120],
                    "sink_root": str(sink_root),
                },
                sink_root=sink_root,
            )
            return 3
        # Build a fresh newline-aligned checkpoint (with tail fingerprint) after the
        # forced full replay.
        checkpoint = _scan_checkpoint_fields(journal_path)
        write_view(sink_root, entries, checkpoint=checkpoint)
        return 0

    # Incremental path (default): apply only post-checkpoint events
    try:
        entries, checkpoint = reduce_journal_incremental(journal_path, sink_root=sink_root)
    except JournalCorruptionError as exc:
        position = "final (truncated tail)" if exc.is_final_line else "interior"
        msg = (
            f"sink-view-reducer: ERROR: {exc}; position={position}"
        )
        print(msg, file=sys.stderr)
        _log_event_sh(
            "followup_journal_truncated",
            {
                "journal_path": str(journal_path),
                "lineno": exc.lineno,
                "position": position,
                "raw_prefix": exc.raw[:120],
                "sink_root": str(sink_root),
            },
            sink_root=sink_root,
        )
        return 3

    write_view(sink_root, entries, checkpoint=checkpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
