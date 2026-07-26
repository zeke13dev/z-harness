#!/usr/bin/env python3
"""Validate a handoff for one foreground, read-only continuation.

This helper deliberately has no approval store and never executes a command.
It only returns a permitted `/z-resume --select <token>` tuple when an
operator supplied a current handoff digest, task id, and selection token in the
same invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


_TASK_ID = re.compile(r"^T[0-9]{3}$")
_TASK_HEADING = re.compile(r"^##\s+(T[0-9]{3})\b", re.MULTILINE)
_ALLOWED_PROTOCOLS = frozenset({"1.0", "1.1"})
_ALLOWED_STATUSES = frozenset({"context_pressure", "clean_break", "complete", "blocked"})
_UNSAFE_FLAGS = frozenset(
    {
        "stale",
        "superseded",
        "degraded",
        "dirty",
        "divergent",
        "stale_handoff",
        "conflicting_evidence",
        "degraded_sources",
        "thin_evidence",
    }
)


class Refusal(ValueError):
    """A safe, user-actionable refusal to authorize continuation."""


def _load_resume_builder() -> Callable[[Sequence[str], Mapping[str, str] | None], dict[str, Any]]:
    path = Path(__file__).with_name("resume-context.py")
    spec = importlib.util.spec_from_file_location("z_harness_resume_context", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load resume-context.py")
    module = importlib.util.module_from_spec(spec)
    # resume-context.py declares dataclasses; register its import name before
    # execution so dataclasses can resolve the module namespace correctly.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module.build_context


def _read_handoff(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"invalid handoff: {exc}") from exc
    if not isinstance(decoded, dict):
        raise Refusal("invalid handoff: expected an object")
    if decoded.get("protocol_version") not in _ALLOWED_PROTOCOLS:
        raise Refusal("invalid handoff: unsupported protocol_version")
    if decoded.get("status") not in _ALLOWED_STATUSES:
        raise Refusal("invalid handoff: unsupported status")
    if not isinstance(decoded.get("next_step"), str) or not decoded["next_step"].strip():
        raise Refusal("invalid handoff: next_step is required")
    if not isinstance(decoded.get("slug"), str) or not decoded["slug"].strip():
        raise Refusal("invalid handoff: a plan slug is required")
    if not isinstance(decoded.get("context_files"), list):
        raise Refusal("invalid handoff: context_files is required")
    return payload, decoded


def _task_file(handoff_path: Path, handoff: Mapping[str, Any]) -> Path:
    for entry in handoff["context_files"]:
        if isinstance(entry, Mapping) and entry.get("role") == "tasks" and isinstance(entry.get("path"), str):
            candidate = Path(entry["path"])
            return candidate if candidate.is_absolute() else handoff_path.parent / candidate
    return handoff_path.parent / "TASKS.md"


def _verify_task(handoff_path: Path, handoff: Mapping[str, Any], task_id: str) -> None:
    if not _TASK_ID.fullmatch(task_id):
        raise Refusal("task must have the form TNNN")
    if task_id not in handoff["next_step"]:
        raise Refusal("handoff next_step does not reference the approved task")
    path = _task_file(handoff_path, handoff)
    try:
        headings = set(_TASK_HEADING.findall(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise Refusal(f"cannot read task list: {exc}") from exc
    if task_id not in headings:
        raise Refusal("approved task is not present in the handoff task list")


def _packet_for(
    handoff_path: Path,
    handoff: Mapping[str, Any],
    repo_root: Path,
    select: str | None,
    resume_builder: Callable[[Sequence[str], Mapping[str, str] | None], dict[str, Any]],
) -> dict[str, Any]:
    argv = [
        "--slug", handoff["slug"],
        "--repo-root", str(repo_root),
        "--plan-dir", str(handoff_path.parent),
        "--format", "json",
        "--noninteractive",
    ]
    if select is not None:
        argv.extend(["--select", select])
    return resume_builder(argv, None)


def _packet_is_safe(packet: Mapping[str, Any], expected_select: str | None) -> tuple[bool, str]:
    selected = packet.get("selected_target")
    ambiguity = packet.get("ambiguity")
    if not isinstance(selected, Mapping):
        return False, "resume evidence has no exact selected target"
    if not isinstance(ambiguity, Mapping) or ambiguity.get("state") not in {None, "none"} or ambiguity.get("needs_selection"):
        return False, "resume evidence is ambiguous"
    token = selected.get("selection_token")
    if not isinstance(token, str) or not token:
        return False, "selected target has no selection token"
    if expected_select is not None and token != expected_select:
        return False, "selection token does not match the approved token"
    state = selected.get("current_state")
    flags = state.get("flags", {}) if isinstance(state, Mapping) else {}
    if not isinstance(flags, Mapping):
        return False, "selected target state is malformed"
    if any(flags.get(flag) for flag in _UNSAFE_FLAGS):
        return False, "resume evidence is stale, conflicting, or degraded"
    return True, token


def inspect(
    handoff_path: Path,
    repo_root: Path,
    task_id: str | None = None,
    *,
    resume_builder: Callable[[Sequence[str], Mapping[str, str] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a read-only handoff assessment without authorizing execution."""
    try:
        payload, handoff = _read_handoff(handoff_path)
        if task_id is not None:
            _verify_task(handoff_path, handoff, task_id)
        builder = resume_builder or _load_resume_builder()
        packet = _packet_for(handoff_path, handoff, repo_root, None, builder)
        safe, detail = _packet_is_safe(packet, None)
        return {
            "ok": safe,
            "reason": "ready" if safe else detail,
            "handoff_sha256": hashlib.sha256(payload).hexdigest(),
            "packet": packet,
        }
    except Refusal as exc:
        return {"ok": False, "reason": str(exc)}


def authorize(
    handoff_path: Path,
    repo_root: Path,
    task_id: str,
    expected_sha256: str,
    select: str,
    *,
    resume_builder: Callable[[Sequence[str], Mapping[str, str] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authorize exactly one read-only resume command, or return a refusal."""
    try:
        payload, handoff = _read_handoff(handoff_path)
        actual_digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 != actual_digest:
            raise Refusal("handoff SHA-256 does not match the approved handoff")
        _verify_task(handoff_path, handoff, task_id)
        builder = resume_builder or _load_resume_builder()
        packet = _packet_for(handoff_path, handoff, repo_root, select, builder)
        safe, detail = _packet_is_safe(packet, select)
        if not safe:
            raise Refusal(detail)
        return {
            "ok": True,
            "handoff_sha256": actual_digest,
            "task": task_id,
            "command": ["/z-resume", "--select", detail],
            "packet": packet,
        }
    except Refusal as exc:
        return {"ok": False, "reason": str(exc)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("inspect", "authorize"):
        child = subparsers.add_parser(name)
        child.add_argument("--handoff", required=True, type=Path)
        child.add_argument("--repo-root", required=True, type=Path)
        child.add_argument("--task")
    authorized = subparsers.choices["authorize"]
    authorized.add_argument("--sha256", required=True)
    authorized.add_argument("--select", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.operation == "inspect":
        result = inspect(args.handoff, args.repo_root, args.task)
    else:
        if not args.task:
            raise SystemExit("authorize requires --task")
        result = authorize(args.handoff, args.repo_root, args.task, args.sha256, args.select)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
