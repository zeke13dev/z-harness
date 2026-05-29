#!/usr/bin/env python3
"""
axiom-extract.py — mine candidate axioms from metrics.jsonl (D6, R8).

Stdlib-only. Reads the repo-wide ``z-harness/metrics.jsonl`` event log,
groups recurring decision events, and emits a JSON array of schema-valid
CANDIDATE records (``status: "candidate"``, NO ``id`` assigned) to stdout.

CLI:
  axiom-extract.py --run <run-id>   [--repo-root PATH] [--max N]
  axiom-extract.py --historical      [--repo-root PATH] [--max N]

Exactly one of ``--run`` / ``--historical`` is required.
  --run <id>     incremental: only events whose ``run`` field == <id>.
  --historical   full scan: every event in metrics.jsonl.

Mining logic (per SPEC R8 + the decision-event emission amendment):
  - PRIMARY mined kinds: ``user_choice`` and ``user_override`` (emitted by
    scripts/log-decision.sh).  ALSO the pre-existing structured gate events:
    ``cost_gate_decision``, ``critique_failure_decision``,
    ``map_collision_decision``, ``shared_concerns_ack_override``.
  - ABSENT kinds contribute zero groups and never error (Invariant 8 —
    graceful degradation on histories that predate emission).
  - Grouping key: ``(event_kind, decision_key, normalized_value)``.
  - A candidate is proposed when a group's event count >=
    ``axioms.extract_min_recurrence`` (read from config.py, default 3).
  - confidence = min(0.95, rec / (rec + 2)).
  - Two-stage in-run dedup: (1) exact statement+scope hash → drop dup;
    (2) fuzzy token-set Jaccard ratio >= 0.9 → ``possible_duplicate_of`` hint.
  - Advisory MEMORY-overlap note when a candidate statement strongly overlaps
    an existing MEMORY.md line.

Output channels:
  - STDOUT: a JSON array of STRICTLY schema-valid candidate records (axiom
    schema is additionalProperties:false, so records carry NO extractor-only
    fields).  This is the array `axiom-store.py add` consumes.
  - STDERR: an optional ``{"advisories": [...]}`` JSON object carrying the
    dedup / MEMORY-overlap hints (R8 intent).  Each advisory binds to its
    record by ``candidate_index`` (into the stdout array) + ``statement``.

Invariant 8: this extractor NEVER writes the axiom store and NEVER approves
anything.  It only emits candidate JSON to stdout.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the store's single-record validator (read-only; never mutate the store)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import importlib

_axiom_store = importlib.import_module("axiom-store")
_validate_record = _axiom_store._validate_record  # noqa: SLF001 (intentional reuse)


# ---------------------------------------------------------------------------
# Config: extract_min_recurrence
# ---------------------------------------------------------------------------

def _extract_min_recurrence() -> int:
    """Read axioms.extract_min_recurrence from config.py (default 3 on any error)."""
    config_py = _SCRIPT_DIR / "config.py"
    try:
        result = subprocess.run(
            [sys.executable, str(config_py), "get", "axioms.extract_min_recurrence"],
            capture_output=True, text=True, check=True,
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 3


# ---------------------------------------------------------------------------
# metrics.jsonl location + reading
# ---------------------------------------------------------------------------

def _repo_root(explicit: str | None) -> Path:
    """Resolve repo root: --repo-root, else git toplevel, else cwd."""
    if explicit:
        return Path(explicit)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _read_events(metrics_path: Path) -> list[dict]:
    """Read metrics.jsonl; tolerate a missing file (returns []) and skip bad lines."""
    if not metrics_path.exists():
        return []
    events: list[dict] = []
    with open(metrics_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a malformed line, keep mining
            if isinstance(obj, dict):
                events.append(obj)
    return events


# ---------------------------------------------------------------------------
# Mined-kind contracts
# ---------------------------------------------------------------------------

# log-decision.sh kinds carry their own decision_key / chosen fields.
_DECISION_KINDS = {"user_choice", "user_override"}

# Pre-existing structured gate events.  Each entry maps the gate kind to:
#   - decision_key: a stable label used as the R8 grouping decision_key
#       (these events have no question_id/decision_key field of their own).
#   - value_field: the payload field whose value is the decision (normalized).
_GATE_KINDS: dict[str, dict[str, str]] = {
    "cost_gate_decision":          {"decision_key": "cost_gate", "value_field": "choice"},
    "critique_failure_decision":   {"decision_key": "critique_failure", "value_field": "choice"},
    "map_collision_decision":      {"decision_key": "map_collision", "value_field": "choice"},
    "shared_concerns_ack_override": {"decision_key": "shared_concerns_ack_override", "value_field": "override"},
}

_MINED_KINDS = _DECISION_KINDS | set(_GATE_KINDS)


# ---------------------------------------------------------------------------
# Routing-question id charset (mirrors schema pattern ^[a-z0-9_.]+:[^:]+$)
# Dots are admitted so that dotted config.py QUESTION_IDS like
# workflow.slug_confirm round-trip correctly through applies_to population.
# ---------------------------------------------------------------------------

_QUESTION_ID_RE = re.compile(r'^[a-z0-9_.]+$')


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalize_value(value: object) -> str:
    """Normalized form of a chosen value: str-coerce, lowercase, trim, collapse ws."""
    s = str(value)
    return _WS_RE.sub(" ", s.strip().lower())


def _group_key(event: dict) -> tuple[str, str, str] | None:
    """
    Derive the R8 grouping key (event_kind, decision_key, normalized_value) for
    an event, or None if the event is not a mined kind / lacks a usable value.
    """
    kind = event.get("kind")
    if kind not in _MINED_KINDS:
        return None

    if kind in _DECISION_KINDS:
        # decision_key field preferred; fall back to question_id.
        decision_key = event.get("decision_key") or event.get("question_id")
        raw_value = event.get("chosen")
    else:
        spec = _GATE_KINDS[kind]
        decision_key = spec["decision_key"]
        raw_value = event.get(spec["value_field"])

    if decision_key is None or raw_value is None:
        return None

    return (kind, str(decision_key), _normalize_value(raw_value))


# ---------------------------------------------------------------------------
# Evidence + statement synthesis
# ---------------------------------------------------------------------------

def _evidence_ref(event: dict) -> dict:
    """
    Build a schema-valid evidence ref for an event.

    Prefer ``event_id`` (present on log-decision.sh events).  Gate events lack
    one, so fall back to a stable ``quote`` derived from run+ts (the schema's
    ``anyOf`` accepts {run, event_id} OR {run, quote}).
    """
    run = str(event.get("run", "historical"))
    ref: dict = {"run": run}
    event_id = event.get("event_id")
    if event_id:
        ref["event_id"] = str(event_id)
    else:
        # Stable fallback ref for events without an event_id (gate events).
        ts = event.get("ts", "")
        ref["quote"] = f"{event.get('kind', '')}@{run}:{ts}"
    kind = event.get("kind")
    if kind:
        ref["kind"] = str(kind)
    return ref


def _synthesize_statement(kind: str, decision_key: str, normalized_value: str) -> str:
    """
    Synthesize a mechanical imperative draft statement for a group.

    The axiom-extractor AGENT (T015) sharpens this later; here we only need a
    reasonable, schema-valid (single sentence, <=200 chars, imperative) draft.
    """
    label = decision_key.replace("_", " ").strip()
    value = normalized_value.replace("_", " ").strip()
    statement = (
        f"When facing the {label} decision, prefer {value}"
    )
    # Schema caps statement at 200 chars; clamp defensively.
    return statement[:200]


# ---------------------------------------------------------------------------
# Token-set ratio (stdlib-only fuzzy dedup)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _statement_tokens(statement: str) -> frozenset[str]:
    """Normalized token set: casefold, strip punctuation, split on non-alnum."""
    return frozenset(_TOKEN_RE.findall(statement.lower()))


def _token_set_ratio(a: frozenset[str], b: frozenset[str]) -> float:
    """
    Token-set Jaccard ratio = |A ∩ B| / |A ∪ B|.

    Returns 1.0 for two identical (incl. both-empty) token sets, 0.0 if exactly
    one is empty.  Range [0, 1].
    """
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Advisory MEMORY-overlap
# ---------------------------------------------------------------------------

def _memory_lines(repo_root: Path) -> list[tuple[str, frozenset[str]]]:
    """
    Collect (line, token_set) pairs from a MEMORY.md if one exists at the repo
    root.  Advisory only — absence yields an empty list (never fatal).
    """
    memory_path = repo_root / "MEMORY.md"
    if not memory_path.exists():
        return []
    out: list[tuple[str, frozenset[str]]] = []
    try:
        text = memory_path.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*# ").strip()
        if not line:
            continue
        out.append((line, _statement_tokens(line)))
    return out


def _memory_overlap_note(
    statement: str,
    memory_lines: list[tuple[str, frozenset[str]]],
) -> str | None:
    """Return an advisory note if the statement strongly overlaps a memory line."""
    tokens = _statement_tokens(statement)
    for line, line_tokens in memory_lines:
        if _token_set_ratio(tokens, line_tokens) >= 0.9:
            return f"possible MEMORY.md overlap with: {line[:120]}"
    return None


# ---------------------------------------------------------------------------
# Core mining
# ---------------------------------------------------------------------------

def mine(
    events: list[dict],
    source_run: str,
    min_recurrence: int,
    repo_root: Path,
    max_candidates: int | None = None,
) -> list[dict]:
    """
    Group events, propose candidates >= min_recurrence, apply two-stage dedup
    and the advisory MEMORY-overlap note.  Returns a list of candidate records.
    """
    # Group events by R8 key (preserving first-seen order for determinism).
    groups: dict[tuple[str, str, str], list[dict]] = {}
    group_order: list[tuple[str, str, str]] = []
    for event in events:
        key = _group_key(event)
        if key is None:
            continue
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(event)

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mem_lines = _memory_lines(repo_root)

    candidates: list[dict] = []
    # Stage-1 exact dedup: statement+scope hash → drop later dups this run.
    seen_exact: set[str] = set()
    # Track emitted (statement, scope, tokens) for fuzzy comparison.
    emitted_meta: list[tuple[str, str, frozenset[str]]] = []

    for key in group_order:
        contributing = groups[key]
        rec = len(contributing)
        if rec < min_recurrence:
            continue

        kind, decision_key, normalized_value = key
        statement = _synthesize_statement(kind, decision_key, normalized_value)
        scope = "global"

        # Stage 1 — exact dedup (statement+scope).
        exact_hash = f"{statement}\x00{scope}"
        if exact_hash in seen_exact:
            continue
        seen_exact.add(exact_hash)

        confidence = min(0.95, rec / (rec + 2))

        record: dict = {
            "statement": statement,
            "scope": scope,
            "status": "candidate",
            "confidence": confidence,
            "evidence": [_evidence_ref(e) for e in contributing],
            "source_run": source_run,
            "created_at": now_iso,
        }

        # --- applies_to population (Option A: value-carrying routing) ---
        # For user_choice / user_override events, decision_key == question_id
        # (set by log-decision.sh; decision_key field is the routing question id).
        # Populate applies_to only when:
        #   1. The event kind is a _DECISION_KINDS kind (not a gate-kind), AND
        #   2. decision_key matches the routing-question id charset [a-z0-9_.]+ —
        #      dots are admitted so that dotted config.py QUESTION_IDS like
        #      workflow.slug_confirm produce valid applies_to entries (gate-kind
        #      labels like "cost_gate" are excluded by the kind check), AND
        #   3. normalized_value is non-empty.
        # Gate-kind behavioral axioms have no routing target — omit applies_to.
        if (
            kind in _DECISION_KINDS
            and _QUESTION_ID_RE.match(decision_key)
            and normalized_value
        ):
            record["applies_to"] = [f"{decision_key}:{normalized_value}"]

        # Stage 2 — fuzzy dedup: record possible_duplicate_of (do NOT drop).
        # NOTE: this annotation is extractor-only and is stripped off the record
        # at emit time (main()), re-surfacing on the stderr advisory channel; the
        # axiom schema is additionalProperties:false and has no such field.
        tokens = _statement_tokens(statement)
        for prev_stmt, prev_scope, prev_tokens in emitted_meta:
            if _token_set_ratio(tokens, prev_tokens) >= 0.9:
                record["possible_duplicate_of"] = f"{prev_scope}:{prev_stmt}"
                break

        # Advisory MEMORY-overlap note (non-fatal, informational).
        note = _memory_overlap_note(statement, mem_lines)
        if note is not None:
            record["notes"] = note

        candidates.append(record)
        emitted_meta.append((statement, scope, tokens))

        if max_candidates is not None and len(candidates) >= max_candidates:
            break

    return candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axiom-extract.py",
        description="Mine candidate axioms from metrics.jsonl (proposes only).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", dest="run", default=None,
                      help="Incremental: only events with this run id.")
    mode.add_argument("--historical", action="store_true", default=False,
                      help="Full metrics.jsonl scan (token/CPU-heavy; on-demand only).")
    parser.add_argument("--repo-root", dest="repo_root", default=None,
                        help="Repo root override (else git toplevel, else cwd).")
    parser.add_argument("--max", dest="max", type=int, default=None,
                        help="Optional cap on the number of candidates emitted.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    repo_root = _repo_root(args.repo_root)
    metrics_path = repo_root / "z-harness" / "metrics.jsonl"
    all_events = _read_events(metrics_path)

    if args.historical:
        events = all_events
        source_run = "historical"
    else:
        events = [e for e in all_events if e.get("run") == args.run]
        source_run = args.run

    min_recurrence = _extract_min_recurrence()
    candidates = mine(events, source_run, min_recurrence, repo_root, args.max)

    # stdout carries ONLY strictly schema-valid candidate records: the axiom
    # schema is additionalProperties:false and has no `notes` /
    # `possible_duplicate_of` field, so those extractor-only annotations must be
    # stripped from every emitted record.  Otherwise axiom-store.py's
    # `_validate_record` (run by `axiom-store.py add` downstream) rejects the
    # record with "unknown field" errors and the scan→add pipeline breaks.
    #
    # The dedup + MEMORY-overlap intent (R8) is preserved by moving those
    # annotations to a separate stderr ADVISORY channel (see below); the records
    # themselves stay clean.  An invalid record is dropped (never approved,
    # never written) per Invariant 8.
    valid: list[dict] = []
    advisories: list[dict] = []
    for cand in candidates:
        # Pull the extractor-only annotation fields off the record before it is
        # emitted; bind them to a stderr advisory keyed by the record's index in
        # the emitted stdout array + its statement (recoverable by T015 / human).
        possible_dup = cand.pop("possible_duplicate_of", None)
        note = cand.pop("notes", None)

        # _validate_record requires an id; candidates have none by spec, so
        # validate a copy with a placeholder id to exercise the structural rules
        # (statement/scope/status/confidence/evidence shape).  The emitted record
        # itself never carries an id.
        probe = dict(cand)
        probe["id"] = "ax-00000000"
        ok, _errors, _warns = _validate_record(probe)
        if not ok:
            continue

        emitted_index = len(valid)
        valid.append(cand)

        if possible_dup is not None or note is not None:
            advisory: dict = {
                "candidate_index": emitted_index,
                "statement": cand["statement"],
            }
            if possible_dup is not None:
                advisory["possible_duplicate_of"] = possible_dup
            if note is not None:
                advisory["memory_overlap"] = note
            advisories.append(advisory)

    print(json.dumps(valid, indent=2, ensure_ascii=False))

    # Emit dedup / MEMORY-overlap hints to stderr so they reach the T015 agent
    # and human reviewer WITHOUT polluting the schema-clean stdout records.  Each
    # advisory binds back to its record via candidate_index (into the stdout
    # array) and the statement string.
    if advisories:
        print(
            json.dumps({"advisories": advisories}, ensure_ascii=False),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
