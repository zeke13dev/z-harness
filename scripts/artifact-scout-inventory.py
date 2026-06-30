#!/usr/bin/env python3
"""Deterministic artifact/worktree inventory for z-harness preflight."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_ROOT = SCRIPT_DIR.parent

SCHEMA_VERSION = "artifact-scout-inventory.v1"
SOURCE_STATUSES = {"ok", "missing", "unavailable", "partial", "corrupt", "truncated"}
ALLOWED_ARTIFACT_FILES = (
    "SPEC.md",
    "PLAN.md",
    "TASKS.md",
    "FIX.md",
    "INTENT.md",
    "BRAINSTORM.md",
    "MAP.md",
    "RESEARCH.md",
    "GRILL.md",
    "PLAN_AUDIT_REPORT.md",
    "REPORT.md",
    "DEBUG.md",
    "run-brief.json",
    "SESSION.md",
    "SESSION_CONTEXT.md",
    "handoff.json",
    "HANDOFF.md",
    "context.json",
)
BODY_DENY_NAMES = {
    "events.jsonl",
    "transcript.md",
    "transcripts.md",
    "diff.patch",
    "diff.diff",
}
SUMMARY_SECTIONS = {
    "intent",
    "problem",
    "goal",
    "approach",
    "acceptance",
    "not doing",
    "files",
    "user choice",
}
MAX_ARTIFACT_BYTES = 8192
MAX_RETAINED_SECTION_BYTES = 2048
MAX_ARTIFACT_FILES_PER_SLUG = 8
MAX_PLAN_DIRS = 200
MAX_HISTORICAL_CANDIDATES = 20
MAX_JSON_PAYLOAD_BYTES = 65536


@dataclass
class ArtifactSummary:
    kind: str
    status: str = "unknown"
    excerpt_parts: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass
class CandidateAccumulator:
    slug: str
    path: Path
    basis: set[str] = field(default_factory=set)
    artifact_kinds: set[str] = field(default_factory=set)
    status: str = "unknown"
    mtime: float = 0.0
    score: int = 0
    summary_parts: list[str] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    source_status: dict[str, str] = field(default_factory=dict)

    def add_summary(self, summary: ArtifactSummary, source: str) -> None:
        self.artifact_kinds.add(summary.kind)
        if (
            summary.status
            and summary.status != "unknown"
            and summary.status != "corrupt"
            and summary.kind != "run-brief"
            and self.status == "unknown"
        ):
            self.status = summary.status
        self.summary_parts.extend(part for part in summary.excerpt_parts if part)
        self.files.update(summary.files)
        status = "corrupt" if summary.status == "corrupt" else ("truncated" if summary.truncated else "ok")
        if self.source_status.get(source) not in {"truncated", "corrupt"}:
            self.source_status[source] = status

    def as_dict(self) -> dict[str, Any]:
        excerpt, excerpt_truncated = _compact_excerpt_with_flag(self.summary_parts)
        source_status = dict(sorted(self.source_status.items()))
        truncated = excerpt_truncated or any(status == "truncated" for status in source_status.values())
        return {
            "slug": self.slug,
            "path": str(self.path),
            "artifact_kinds": sorted(self.artifact_kinds),
            "status": self.status,
            "mtime": _iso_from_timestamp(self.mtime),
            "score": self.score,
            "basis": sorted(self.basis),
            "summary_excerpt": excerpt,
            "files": sorted(self.files),
            "source_status": source_status,
            "truncated": truncated,
        }


def _iso_from_timestamp(ts: float) -> str:
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compact_excerpt_with_flag(parts: Iterable[str], limit: int = MAX_RETAINED_SECTION_BYTES) -> tuple[str, bool]:
    seen: set[str] = set()
    out: list[str] = []
    total = 0
    truncated = False
    for raw in parts:
        text = " ".join(raw.strip().split())
        if not text or text in seen:
            continue
        seen.add(text)
        extra = ("\n" if out else "") + text
        if total + len(extra) > limit:
            remaining = limit - total
            if remaining > 1:
                out.append(extra[:remaining].rstrip())
            truncated = True
            break
        out.append(text)
        total += len(extra)
    return "\n".join(out), truncated


def _compact_excerpt(parts: Iterable[str], limit: int = MAX_RETAINED_SECTION_BYTES) -> str:
    return _compact_excerpt_with_flag(parts, limit)[0]


def _safe_read_text(path: Path, max_bytes: int = MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
    truncated = False
    try:
        truncated = path.stat().st_size > max_bytes
    except OSError:
        truncated = False
    with path.open("rb") as fh:
        payload = fh.read(max_bytes)
    return payload.decode("utf-8", errors="replace"), truncated


def _artifact_kind(path: Path, fields: Mapping[str, str] | None = None) -> str:
    fields = fields or {}
    for key in ("artifact_kind", "artifact"):
        value = fields.get(key)
        if value:
            return value
    if path.name == "run-brief.json":
        return "run-brief"
    return path.stem


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"artifact", "artifact_kind", "slug", "status", "generated_at", "frozen_at", "level", "planning_mode"}:
            fields[key] = value.strip().strip('"\'')
    rest_start = text.find("\n", end + 4)
    return fields, text[rest_start + 1 :] if rest_start != -1 else ""


def _parse_markdown_artifact(path: Path) -> ArtifactSummary:
    text, truncated = _safe_read_text(path)
    fields, body = _parse_frontmatter(text)
    summary = ArtifactSummary(kind=_artifact_kind(path, fields), status=fields.get("status", "unknown"), truncated=truncated)

    first_heading = ""
    current_section = ""
    bullets_in_section = 0
    fallback_bullets = 0
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if path.name == "TASKS.md":
            if re.match(r"^#{1,6}\s*T\d+\b", stripped) or re.match(r"^-\s*\[[ xX-]\]\s*T\d+\b", stripped):
                summary.excerpt_parts.append(stripped)
            if "Files:" in stripped or "**Files:**" in stripped:
                summary.excerpt_parts.append(stripped)
                summary.files.extend(_extract_files_from_line(stripped))
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading_match:
            title = heading_match.group(2).strip()
            if not first_heading:
                first_heading = title
                summary.excerpt_parts.append(title)
            normalized = title.lower().rstrip(":")
            current_section = normalized if normalized in SUMMARY_SECTIONS else ""
            bullets_in_section = 0
            continue
        if re.match(r"^[-*+]\s+", stripped):
            if current_section and bullets_in_section < 6:
                summary.excerpt_parts.append(stripped)
                bullets_in_section += 1
            elif not current_section and fallback_bullets < 3:
                summary.excerpt_parts.append(stripped)
                fallback_bullets += 1
    return summary


def _parse_run_brief(path: Path) -> ArtifactSummary:
    text, truncated = _safe_read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        status = "truncated" if truncated else "corrupt"
        return ArtifactSummary(kind="run-brief", status=status, excerpt_parts=[f"run-brief.json is {status}"], truncated=truncated)
    summary = ArtifactSummary(kind="run-brief", status=str(data.get("status") or "unknown"), truncated=truncated)
    for key in ("command", "slug", "task", "topic", "summary"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            summary.excerpt_parts.append(f"{key}: {value.strip()}")
    return summary


def _parse_artifact(path: Path) -> ArtifactSummary:
    if path.name == "run-brief.json":
        return _parse_run_brief(path)
    return _parse_markdown_artifact(path)


def _extract_files_from_line(line: str) -> list[str]:
    _, _, tail = line.partition("Files:")
    tail = tail.replace("**", "")
    files: list[str] = []
    for part in re.split(r",|\s+and\s+", tail):
        cleaned = part.strip().strip("` .")
        if cleaned:
            files.append(cleaned)
    return files


def _tokenize_terms(slug: str, task: str | None) -> list[str]:
    raw = f"{slug} {task or ''}".lower()
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", raw):
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _run_command(argv: Sequence[str], cwd: Path, timeout: int = 5, environ: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(environ or os.environ)
    env["PWD"] = str(cwd)
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass
class ScanState:
    dropped_counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    partial_sources: set[str] = field(default_factory=set)
    truncated_sources: set[str] = field(default_factory=set)

    def drop(self, key: str, count: int = 1, *, source: str | None = None, truncated: bool = True) -> None:
        if count <= 0:
            return
        self.dropped_counts[key] = self.dropped_counts.get(key, 0) + count
        self.truncated = self.truncated or truncated
        if source is not None:
            if truncated:
                self.truncated_sources.add(source)
            else:
                self.partial_sources.add(source)

    def mark_truncated(self, source: str | None = None) -> None:
        self.truncated = True
        if source is not None:
            self.truncated_sources.add(source)


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except OSError:
        return None


def _path_within(path: Path, roots: Sequence[Path]) -> bool:
    resolved = _safe_resolve(path)
    if resolved is None:
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _merge_source_status(status: str, state: ScanState, source: str) -> str:
    if source in state.truncated_sources:
        return "truncated"
    if source in state.partial_sources:
        return "partial" if status == "ok" else status
    return status



def _resolve_base_from_plan_dir(plan_dir: Path) -> Path | None:
    if plan_dir.parent.name == "plans":
        return plan_dir.parent.parent
    for parent in plan_dir.parents:
        if parent.name == "plans":
            return parent.parent
    return None


def _resolve_base_from_helper(repo_root: Path, helper_root: Path, environ: Mapping[str, str] | None = None) -> Path | None:
    helper = helper_root / "scripts" / "plan-path.sh"
    if not helper.exists():
        return None
    try:
        try:
            result = _run_command(["bash", str(helper), "base_dir"], cwd=repo_root, environ=environ)
        except TypeError:
            # Older tests monkeypatch _run_command without the optional environ
            # parameter; keep that compatibility while production calls still
            # pass the resolved environment through.
            result = _run_command(["bash", str(helper), "base_dir"], cwd=repo_root)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    return Path(resolved) if resolved else None


def _allowed_roots(repo_root: Path, plan_dir: Path, helper_root: Path, environ: Mapping[str, str] | None = None) -> list[Path]:
    roots: list[Path] = []
    for root in (repo_root, _resolve_base_from_plan_dir(plan_dir), _resolve_base_from_helper(repo_root, helper_root, environ)):
        if root is None:
            continue
        try:
            resolved = root.resolve(strict=root.exists())
        except OSError:
            resolved = root.absolute()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _plan_roots(repo_root: Path, plan_dir: Path, helper_root: Path, environ: Mapping[str, str] | None = None) -> list[Path]:
    roots: list[Path] = []
    base = _resolve_base_from_plan_dir(plan_dir)
    if base is not None:
        roots.append(base / "plans")
    helper_base = _resolve_base_from_helper(repo_root, helper_root, environ)
    if helper_base is not None:
        roots.append(helper_base / "plans")
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _same_existing_path(left: Path, right: Path) -> bool:
    left_resolved = _safe_resolve(left)
    right_resolved = _safe_resolve(right)
    return left_resolved is not None and left_resolved == right_resolved


def _collect_plan_dirs(
    repo_root: Path,
    plan_dir: Path,
    slug: str,
    state: ScanState,
    allowed_roots: Sequence[Path],
    helper_root: Path,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[Path], str]:
    mandatory_dirs: list[Path] = []
    historical_dirs: list[Path] = []
    partial = False

    for root in _plan_roots(repo_root, plan_dir, helper_root, environ):
        if not root.exists():
            continue
        if not _path_within(root, allowed_roots):
            state.drop("symlink_escapes", source="plans", truncated=False)
            partial = True
            continue
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            partial = True
            state.partial_sources.add("plans")
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            if not _path_within(child, allowed_roots):
                state.drop("symlink_escapes", source="plans", truncated=False)
                partial = True
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                partial = True
                state.partial_sources.add("plans")
                continue
            if not is_dir:
                continue
            if child.name == slug or _same_existing_path(child, plan_dir):
                mandatory_dirs.append(child)
            else:
                historical_dirs.append(child)

    if plan_dir.is_dir() and _path_within(plan_dir, allowed_roots):
        mandatory_dirs.append(plan_dir)
    elif plan_dir.exists() and not _path_within(plan_dir, allowed_roots):
        state.drop("symlink_escapes", source="plans", truncated=False)
        partial = True

    if len(historical_dirs) > MAX_PLAN_DIRS:
        state.drop("plan_dirs_over_cap", len(historical_dirs) - MAX_PLAN_DIRS, source="plans")
        historical_dirs = historical_dirs[:MAX_PLAN_DIRS]

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in [*mandatory_dirs, *historical_dirs]:
        resolved = _safe_resolve(path)
        key = str(resolved) if resolved is not None else str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    if deduped:
        return deduped, "partial" if partial else "ok"
    return [], "partial" if partial else "missing"


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_artifacts_from_dir(
    directory: Path,
    *,
    allowed_roots: Sequence[Path],
    state: ScanState,
    source: str,
    remaining_budget: int,
) -> tuple[list[ArtifactSummary], float, int]:
    summaries: list[ArtifactSummary] = []
    newest = _safe_mtime(directory) if directory.exists() else 0.0
    for name in ALLOWED_ARTIFACT_FILES:
        if name in BODY_DENY_NAMES:
            continue
        path = directory / name
        if not path.exists():
            continue
        if not _path_within(path, allowed_roots):
            state.drop("symlink_escapes", source=source, truncated=False)
            continue
        try:
            is_file = path.is_file()
        except OSError:
            state.partial_sources.add(source)
            continue
        if not is_file:
            continue
        if remaining_budget <= 0:
            state.drop("artifact_files_over_cap", source=source)
            continue
        try:
            summary = _parse_artifact(path)
            if summary.status == "corrupt":
                state.partial_sources.add(source)
            if summary.truncated:
                state.drop("artifact_bytes_over_cap", source=source)
            summaries.append(summary)
            newest = max(newest, _safe_mtime(path))
            remaining_budget -= 1
        except OSError:
            state.partial_sources.add(source)
    return summaries, newest, remaining_budget


def _archive_run_dirs(
    plan_dir: Path,
    current_run_id: str,
    exact_slug: bool,
    *,
    allowed_roots: Sequence[Path],
    state: ScanState,
) -> list[Path]:
    archive = plan_dir / "archive"
    if not archive.exists():
        return []
    if not _path_within(archive, allowed_roots):
        state.drop("symlink_escapes", source="archives", truncated=False)
        return []
    if not archive.is_dir():
        return []
    try:
        children = []
        for child in archive.iterdir():
            if not _path_within(child, allowed_roots):
                state.drop("symlink_escapes", source="archives", truncated=False)
                continue
            if child.is_dir():
                children.append(child)
    except OSError:
        state.partial_sources.add("archives")
        return []
    if exact_slug:
        current = [p for p in children if p.name == current_run_id]
        prior = sorted((p for p in children if p.name != current_run_id), key=_safe_mtime, reverse=True)[:1]
        return current + prior
    return sorted(children, key=_safe_mtime, reverse=True)[:1]


def _candidate_sort_key(acc: CandidateAccumulator) -> tuple[int, float, str, str]:
    return (-acc.score, -acc.mtime, acc.slug, str(acc.path))


def _score_historical_candidate(acc: CandidateAccumulator, terms: Sequence[str]) -> None:
    if "exact_slug" in acc.basis or "current_plan_dir" in acc.basis:
        return
    haystack = " ".join([acc.slug, *acc.summary_parts, *acc.files, *acc.artifact_kinds]).lower()
    overlap = sum(1 for term in terms if term in haystack)
    if acc.summary_parts or acc.artifact_kinds:
        acc.score = max(acc.score, 10 + overlap * 10)
    elif overlap:
        acc.score = max(acc.score, overlap * 10)


def _build_candidates(
    slug: str,
    repo_root: Path,
    plan_dir: Path,
    run_id: str,
    task: str | None = None,
    helper_root: Path = HELPER_ROOT,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], set[str], ScanState]:
    state = ScanState()
    allowed_roots = _allowed_roots(repo_root, plan_dir, helper_root, environ)
    plan_dirs, plans_status = _collect_plan_dirs(repo_root, plan_dir, slug, state, allowed_roots, helper_root, environ)
    candidates: dict[str, CandidateAccumulator] = {}
    archives_seen = False
    current_files: set[str] = set()
    terms = _tokenize_terms(slug, task)

    for candidate_dir in plan_dirs:
        candidate_slug = candidate_dir.name
        artifact_budget = MAX_ARTIFACT_FILES_PER_SLUG
        summaries, newest, artifact_budget = _read_artifacts_from_dir(
            candidate_dir,
            allowed_roots=allowed_roots,
            state=state,
            source="plans",
            remaining_budget=artifact_budget,
        )
        archive_payloads: list[tuple[Path, list[ArtifactSummary], float]] = []
        for run_dir in _archive_run_dirs(candidate_dir, run_id, candidate_slug == slug, allowed_roots=allowed_roots, state=state):
            archives_seen = True
            archive_summaries, archive_newest, artifact_budget = _read_artifacts_from_dir(
                run_dir,
                allowed_roots=allowed_roots,
                state=state,
                source="archives",
                remaining_budget=artifact_budget,
            )
            archive_payloads.append((run_dir, archive_summaries, archive_newest))

        if not summaries and not archive_payloads and candidate_dir != plan_dir and candidate_slug != slug:
            continue

        resolved = _safe_resolve(candidate_dir)
        key = str(resolved) if resolved is not None else str(candidate_dir)
        acc = candidates.setdefault(key, CandidateAccumulator(slug=candidate_slug, path=candidate_dir))
        acc.basis.add("plan_dir")
        if candidate_slug == slug:
            acc.basis.add("exact_slug")
            acc.score = max(acc.score, 100)
        if _same_existing_path(candidate_dir, plan_dir) or candidate_dir == plan_dir:
            acc.basis.add("current_plan_dir")
            acc.score = max(acc.score, 100)
        acc.mtime = max(acc.mtime, newest)
        for summary in summaries:
            acc.add_summary(summary, "plans")
            if _same_existing_path(candidate_dir, plan_dir) or candidate_dir == plan_dir:
                current_files.update(summary.files)

        for run_dir, archive_summaries, archive_newest in archive_payloads:
            acc.basis.add(f"archive:{run_dir.name}")
            acc.mtime = max(acc.mtime, archive_newest)
            for summary in archive_summaries:
                acc.add_summary(summary, "archives")
        _score_historical_candidate(acc, terms)

    sorted_accumulators = sorted(candidates.values(), key=_candidate_sort_key)
    mandatory_accumulators = [
        acc for acc in sorted_accumulators if "exact_slug" in acc.basis or "current_plan_dir" in acc.basis
    ]
    historical_accumulators = [acc for acc in sorted_accumulators if acc not in mandatory_accumulators]
    if len(historical_accumulators) > MAX_HISTORICAL_CANDIDATES:
        state.drop("historical_candidates_over_cap", len(historical_accumulators) - MAX_HISTORICAL_CANDIDATES, source="plans")
        historical_accumulators = historical_accumulators[:MAX_HISTORICAL_CANDIDATES]

    mandatory = [acc.as_dict() for acc in mandatory_accumulators]
    historical = [acc.as_dict() for acc in historical_accumulators]
    if any(candidate.get("truncated") for candidate in [*mandatory, *historical]):
        state.mark_truncated()
    source_status = {
        "plans": _merge_source_status(plans_status, state, "plans"),
        "archives": _merge_source_status("ok" if archives_seen else "missing", state, "archives"),
    }
    return mandatory, historical, source_status, current_files, state


def _registry_records(repo_root: Path, run_id: str, environ: Mapping[str, str], helper_root: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        try:
            result = _run_command(
                ["python3", str(helper_root / "scripts" / "active-plan-registry.py"), "list", "--json"],
                cwd=repo_root,
                environ=environ,
            )
        except TypeError:
            result = _run_command(["python3", "scripts/active-plan-registry.py", "list", "--json"], cwd=repo_root)
    except (OSError, subprocess.TimeoutExpired):
        return [], "unavailable"
    if result.returncode != 0:
        return [], "unavailable"
    if "WARNING: cannot resolve active_plans_dir" in (result.stderr or ""):
        return [], "unavailable"
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return [], "corrupt"
    if not isinstance(payload, list):
        return [], "corrupt"

    current_session = environ.get("Z_HARNESS_SESSION_ID", "")
    for rec in payload:
        if isinstance(rec, dict) and rec.get("run_id") == run_id and isinstance(rec.get("session_id"), str):
            current_session = current_session or rec.get("session_id", "")
            break

    records: list[dict[str, Any]] = []
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        if rec.get("run_id") == run_id:
            continue
        if current_session and rec.get("session_id") == current_session:
            continue
        records.append(rec)
    return records, "ok"


def _parse_worktree_porcelain(text: str) -> list[dict[str, Any]]:
    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        if not raw:
            continue
        key, _, value = raw.partition(" ")
        if key == "worktree":
            if current:
                worktrees.append(current)
            current = {"path": value, "head": "", "branch": "", "detached": False, "bare": False}
        elif current is not None:
            if key == "HEAD":
                current["head"] = value
            elif key == "branch":
                current["branch"] = value.replace("refs/heads/", "")
            elif key == "detached":
                current["detached"] = True
            elif key == "bare":
                current["bare"] = True
    if current:
        worktrees.append(current)
    return worktrees


def _worktrees(repo_root: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        result = _run_command(["git", "worktree", "list", "--porcelain"], cwd=repo_root)
    except (OSError, subprocess.TimeoutExpired):
        return [], "unavailable"
    if result.returncode != 0:
        return [], "unavailable"
    return _parse_worktree_porcelain(result.stdout), "ok"


def _path_entries(entries: Any) -> set[str]:
    paths: set[str] = set()
    if not isinstance(entries, list):
        return paths
    for entry in entries:
        if isinstance(entry, str):
            paths.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            paths.add(entry["path"])
    return paths


def _candidate_has_canonical_tasks(candidate: Mapping[str, Any]) -> bool:
    kinds = {str(kind).upper() for kind in candidate.get("artifact_kinds") or []}
    if "TASKS" not in kinds:
        return False
    excerpt = str(candidate.get("summary_excerpt") or "")
    return bool(re.search(r"(^|\n)(#{1,6}\s+T\d+\b|-\s*\[[ xX-]\]\s*T\d+\b)", excerpt))


def _signals(
    slug: str,
    plan_dir: Path,
    mandatory_candidates: list[dict[str, Any]],
    historical_candidates: list[dict[str, Any]],
    active_records: list[dict[str, Any]],
    worktrees: list[dict[str, Any]],
    current_files: set[str],
    source_status: Mapping[str, str],
    inventory_truncated: bool,
) -> dict[str, Any]:
    exact_finished = False
    exact_precontext = False
    artifact_plan_mode: str | None = None
    canonical_tasks_present = False
    artifact_match_basis: list[str] = []
    for candidate in mandatory_candidates:
        if candidate.get("slug") != slug:
            continue
        exact_precontext = True
        kinds = {str(kind).upper() for kind in candidate.get("artifact_kinds") or []}
        canonical_tasks_present = _candidate_has_canonical_tasks(candidate)
        legacy_finished = {"SPEC", "PLAN"}.issubset(kinds) and canonical_tasks_present
        intent_finished = "INTENT" in kinds and canonical_tasks_present
        fix_finished = "FIX" in kinds
        if legacy_finished:
            exact_finished = True
            artifact_plan_mode = "legacy_sdd"
            artifact_match_basis.extend(["exact_finished_plan", "exact_legacy_finished_plan", "canonical_tasks"])
        elif intent_finished:
            exact_finished = True
            artifact_plan_mode = "intent"
            artifact_match_basis.extend(["exact_finished_plan", "exact_intent_finished_plan", "canonical_tasks"])
        elif fix_finished:
            exact_finished = True
            artifact_plan_mode = "fix"
            artifact_match_basis.extend(["exact_finished_plan", "exact_fix_finished_plan"])
        elif exact_precontext:
            artifact_match_basis.append("exact_precontext")
    active_same_slug = any(rec.get("slug") == slug for rec in active_records)
    scope_paths: set[str] = set()
    held_paths: set[str] = set()
    for rec in active_records:
        scope_paths.update(_path_entries(rec.get("scope")))
        held_paths.update(_path_entries(rec.get("held_paths")))

    branch_needles = {slug, slug.replace("-", "/"), slug.replace("-", "_")}
    worktree_branch_overlap = any(
        any(needle and needle in str(wt.get("branch") or wt.get("path") or "") for needle in branch_needles)
        for wt in worktrees
    )
    unknown_statuses = {"partial", "corrupt", "unavailable", "truncated"}
    partial_status = inventory_truncated or any(
        status in unknown_statuses or (source == "plans" and status == "missing")
        for source, status in source_status.items()
    )
    if historical_candidates:
        artifact_match_basis.append("historical_similar")
    if not artifact_match_basis:
        artifact_match_basis.append("none")
    return {
        "exact_slug_finished_plan": exact_finished,
        "exact_slug_precontext": exact_precontext,
        "artifact_exact_slug_match": exact_precontext,
        "artifact_finished_plan_match": exact_finished,
        "artifact_plan_mode": artifact_plan_mode,
        "canonical_tasks_present": canonical_tasks_present,
        "artifact_match_confidence": "high" if exact_precontext else ("medium" if historical_candidates else "low"),
        "artifact_match_basis": artifact_match_basis,
        "active_same_slug": active_same_slug,
        "active_path_overlap": bool(current_files and scope_paths.intersection(current_files)),
        "held_paths_overlap": bool(current_files and held_paths.intersection(current_files)),
        "worktree_branch_overlap": worktree_branch_overlap,
        "historical_similar_count": len(historical_candidates),
        "unknown_due_to_partial_sources": partial_status,
    }


def _json_payload_size(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _bump_dropped(payload: dict[str, Any], key: str, count: int = 1) -> None:
    if count <= 0:
        return
    dropped = payload.setdefault("dropped_counts", {})
    dropped[key] = int(dropped.get(key, 0)) + count
    payload["truncated"] = True


def _compact_path_entries(entries: Any) -> list[Any]:
    compacted: list[Any] = []
    if not isinstance(entries, list):
        return compacted
    for entry in entries:
        if isinstance(entry, str):
            compacted.append(entry[:512])
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            compacted.append({"path": str(entry["path"])[:512]})
    return compacted


def _compact_active_record(record: Mapping[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key in ("run_id", "slug", "command", "phase", "status", "branch", "current_task", "host"):
        value = record.get(key)
        if value is not None:
            compacted[key] = str(value)[:512]
    for key in ("scope", "held_paths"):
        entries = _compact_path_entries(record.get(key))
        if entries:
            compacted[key] = entries
    return compacted


def _compact_worktree(record: Mapping[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key in ("path", "head", "branch"):
        value = record.get(key)
        if value is not None:
            compacted[key] = str(value)[:512]
    for key in ("detached", "bare"):
        if key in record:
            compacted[key] = bool(record.get(key))
    return compacted


def _compact_mandatory_signal_sources(payload: dict[str, Any]) -> None:
    if _json_payload_size(payload) <= MAX_JSON_PAYLOAD_BYTES:
        return
    if payload.get("active_records"):
        payload["active_records"] = [_compact_active_record(rec) for rec in payload["active_records"] if isinstance(rec, Mapping)]
        _bump_dropped(payload, "active_records_compacted_json_cap")
    if _json_payload_size(payload) <= MAX_JSON_PAYLOAD_BYTES:
        return
    if payload.get("worktrees"):
        payload["worktrees"] = [_compact_worktree(rec) for rec in payload["worktrees"] if isinstance(rec, Mapping)]
        _bump_dropped(payload, "worktrees_compacted_json_cap")
    while _json_payload_size(payload) > MAX_JSON_PAYLOAD_BYTES and payload.get("active_records"):
        payload["active_records"].pop()
        _bump_dropped(payload, "active_records_json_cap")
    while _json_payload_size(payload) > MAX_JSON_PAYLOAD_BYTES and payload.get("worktrees"):
        payload["worktrees"].pop()
        _bump_dropped(payload, "worktrees_json_cap")


def _enforce_json_payload_cap(payload: dict[str, Any]) -> None:
    while _json_payload_size(payload) > MAX_JSON_PAYLOAD_BYTES and payload.get("historical_candidates"):
        payload["historical_candidates"].pop()
        _bump_dropped(payload, "historical_candidates_json_cap")

    for collection_name in ("historical_candidates", "mandatory_candidates"):
        for candidate in payload.get(collection_name, []):
            if _json_payload_size(payload) <= MAX_JSON_PAYLOAD_BYTES:
                return
            excerpt = candidate.get("summary_excerpt")
            if isinstance(excerpt, str) and excerpt:
                candidate["summary_excerpt"] = excerpt[:512].rstrip()
                candidate["truncated"] = True
                _bump_dropped(payload, "summary_excerpt_json_cap")

    for collection_name in ("historical_candidates", "mandatory_candidates"):
        for candidate in payload.get(collection_name, []):
            if _json_payload_size(payload) <= MAX_JSON_PAYLOAD_BYTES:
                return
            files = candidate.get("files")
            if isinstance(files, list) and files:
                candidate["files"] = files[:32]
                candidate["truncated"] = True
                _bump_dropped(payload, "candidate_files_json_cap")
            if _json_payload_size(payload) > MAX_JSON_PAYLOAD_BYTES and isinstance(candidate.get("summary_excerpt"), str) and candidate["summary_excerpt"]:
                candidate["summary_excerpt"] = ""
                candidate["truncated"] = True
                _bump_dropped(payload, "summary_excerpt_json_cap")

    _compact_mandatory_signal_sources(payload)


def collect_inventory(
    *,
    command: str,
    slug: str,
    run_id: str,
    repo_root: Path,
    plan_dir: Path,
    task: str | None,
    helper_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environ = environ or os.environ
    repo_root = repo_root.expanduser().resolve() if repo_root.exists() else repo_root.expanduser().absolute()
    plan_dir = plan_dir.expanduser().resolve() if plan_dir.exists() else plan_dir.expanduser().absolute()
    helper_root = (helper_root or HELPER_ROOT).expanduser().resolve()

    mandatory_candidates, historical_candidates, artifact_status, current_files, scan_state = _build_candidates(slug, repo_root, plan_dir, run_id, task, helper_root=helper_root, environ=environ)
    active_records, registry_status = _registry_records(repo_root, run_id, environ, helper_root)
    worktree_records, worktree_status = _worktrees(repo_root)
    source_status = {
        "plans": artifact_status["plans"],
        "archives": artifact_status["archives"],
        "registry": registry_status,
        "worktrees": worktree_status,
    }
    inventory = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "slug": slug,
        "run_id": run_id,
        "repo_root": str(repo_root),
        "plan_dir": str(plan_dir),
        "task_terms": _tokenize_terms(slug, task),
        "source_status": source_status,
        "truncated": scan_state.truncated,
        "dropped_counts": dict(sorted(scan_state.dropped_counts.items())),
        "mandatory_candidates": mandatory_candidates,
        "historical_candidates": historical_candidates,
        "active_records": active_records,
        "worktrees": worktree_records,
        "signals": {},
    }
    inventory["signals"] = _signals(
        slug,
        plan_dir,
        mandatory_candidates,
        historical_candidates,
        active_records,
        worktree_records,
        current_files,
        source_status,
        bool(inventory["truncated"]),
    )
    full_signals = inventory["signals"]
    _enforce_json_payload_cap(inventory)
    if inventory.get("truncated"):
        full_signals["unknown_due_to_partial_sources"] = True
    inventory["signals"] = full_signals
    return inventory


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect z-harness artifact scout inventory.")
    parser.add_argument("--command", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--task", default=None)
    parser.add_argument("--helper-root", default=str(HELPER_ROOT), help="installed z-harness helper root containing scripts/")
    return parser


def _validate_args(args: argparse.Namespace) -> str | None:
    for attr in ("command", "slug", "run_id", "repo_root", "plan_dir", "output"):
        if not str(getattr(args, attr, "")).strip():
            return f"--{attr.replace('_', '-')} must not be empty"
    for attr in ("repo_root", "plan_dir", "output", "helper_root"):
        if not Path(getattr(args, attr)).expanduser().is_absolute():
            return f"--{attr.replace('_', '-')} must be an absolute path"
    return None


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    arg_error = _validate_args(args)
    if arg_error:
        print(f"artifact-scout-inventory: {arg_error}", file=sys.stderr)
        return 2


    output = Path(args.output).expanduser()
    try:
        inventory = collect_inventory(
            command=args.command,
            slug=args.slug,
            run_id=args.run_id,
            repo_root=Path(args.repo_root),
            plan_dir=Path(args.plan_dir),
            task=args.task,
            environ=environ,
            helper_root=Path(args.helper_root),
        )
        _atomic_write_json(output, inventory)
    except OSError as exc:
        print(f"artifact-scout-inventory: cannot write output: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(inventory, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
