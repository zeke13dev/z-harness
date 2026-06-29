#!/usr/bin/env python3
"""resume-context.py — deterministic evidence packet builder for /z-resume.

This script is intentionally read-only and deterministic.  It gathers bounded
z-harness evidence, exposes degradation explicitly, and emits the durable
resume-context packet later command/rendering surfaces consume.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import shlex
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_ROOT = SCRIPT_DIR.parent
REPO_ROOT = HELPER_ROOT

SCHEMA_VERSION = "resume-context.v1"
SUPPORTED_SESSION_SCHEMA_VERSIONS = {"1"}
SOURCE_STATUS_ORDER = {
    "ok": 0,
    "missing": 1,
    "partial": 2,
    "stale": 3,
    "superseded": 4,
    "truncated": 5,
    "malformed": 6,
    "corrupt": 7,
    "unavailable": 8,
    "degraded": 9,
}
SOURCE_STATUSES = set(SOURCE_STATUS_ORDER)
VALIDATION_STATUSES = {
    "valid",
    "missing",
    "malformed",
    "unvalidated",
    "stale",
    "conflict",
    "degraded",
    "truncated",
    "superseded",
}
SIDE_EVIDENCE_TYPES = {"followup", "memory", "subagent_judgment", "session_context", "human_handoff"}
PRIMARY_STATE_PRECEDENCE = [
    "active",
    "paused",
    "blocked",
    "completed",
    "landed",
    "archived_only",
    "stale",
    "superseded",
    "dirty",
    "divergent",
    "unknown",
]
STATE_FLAGS = [
    "stale",
    "superseded",
    "degraded",
    "dirty",
    "divergent",
    "archived_only",
    "side_evidence_only",
    "conflicting_current_state",
    "active_registry",
    "completed_tasks",
    "landed_git",
    "stale_session",
    "stale_handoff",
    "dirty_worktree",
    "divergent_branch",
    "superseded_by_newer_run",
    "cross_repo",
    "thin_evidence",
    "conflicting_evidence",
    "degraded_sources",
]
AMBIGUITY_STATES = [
    "none",
    "needs_selection",
    "no_candidates",
    "close_scores",
    "low_confidence",
    "thin_evidence",
    "conflicting_current_state",
    "cross_repo_conflict",
]
MAX_TEXT_BYTES = 8192
MAX_SUBAGENT_PROMPT_CHARS = 12000
MAX_SUBAGENT_EVIDENCE_RECORDS = 12
MAX_SUBAGENT_CANDIDATES = 3
MAX_SUBAGENT_DEFAULT_CALLS = 2
RESUME_CLUSTER_AGENT = "resume-cluster"
REQUIRED_SUBAGENT_JUDGMENT_FIELDS = {
    "likely_work_thread",
    "current_or_landed_state",
    "latest_consensus",
    "unresolved_questions",
    "confidence",
    "confidence_reasons",
    "suggested_next_command_or_prompt",
    "citations",
}


_SUBAGENT_FACTUAL_FIELDS = (
    "likely_work_thread",
    "current_or_landed_state",
    "latest_consensus",
    "suggested_next_command_or_prompt",
)
_SUBAGENT_PROMPT_PREFIX = (
    "You are the resume-cluster read-only inference subagent. Use only the supplied JSON evidence below. "
    "Do not read files, run commands, inspect repo state, browse, or invent uncited facts. "
    "Return one JSON object with exactly these fields: likely_work_thread, current_or_landed_state, "
    "latest_consensus, unresolved_questions, confidence, confidence_reasons, "
    "suggested_next_command_or_prompt, citations. Citations must be citation ids present in the supplied JSON; "
    "use <unknown> when the supplied evidence does not establish an answer. Confidence reasons and unresolved "
    "questions that make factual claims require supplied citations; purely procedural items may be uncited. "
    "current_or_landed_state must be exactly <unknown> or supplied primary_state label(s).\n\n"
    "SUPPLIED_EVIDENCE_JSON:\n"
)

EXACT_TOKEN_PREFIXES = {
    "run": "run",
    "slug": "slug",
    "plan": "slug",
    "branch": "branch",
    "worktree": "worktree",
    "artifact": "artifact",
    "repo": "repo",
    "select": "select",
}
CURRENT_TARGET_TOKENS = {"current", "active"}
LATEST_TARGET_TOKENS = {"latest", "last"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_ARTIFACT_INVENTORY = None


def _artifact_inventory():
    global _ARTIFACT_INVENTORY
    if _ARTIFACT_INVENTORY is None:
        _ARTIFACT_INVENTORY = _load_script_module("artifact_scout_inventory_for_resume", SCRIPT_DIR / "artifact-scout-inventory.py")
    return _ARTIFACT_INVENTORY


def _merge_status(left: str, right: str) -> str:
    left = left if left in SOURCE_STATUSES else "degraded"
    right = right if right in SOURCE_STATUSES else "degraded"
    return left if SOURCE_STATUS_ORDER[left] >= SOURCE_STATUS_ORDER[right] else right


def _tokenize(value: str) -> list[str]:
    return [tok for tok in re.split(r"[^A-Za-z0-9]+", value.lower()) if len(tok) >= 2]


def _slugify(value: str) -> str:
    tokens = _tokenize(value)
    if not tokens:
        return "resume-context"
    return "-".join(tokens[:8])


def _read_text(path: Path, max_bytes: int = MAX_TEXT_BYTES) -> tuple[str, bool]:
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace"), truncated


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _run(argv: Sequence[str], *, cwd: Path | None = None, environ: Mapping[str, str] | None = None, timeout: int = 10) -> tuple[int, str, str]:
    run_cwd = cwd or REPO_ROOT
    env = dict(environ or os.environ)
    env["PWD"] = str(run_cwd)
    try:
        result = subprocess.run(
            list(argv),
            cwd=str(run_cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _run_plan_path(subcommand: str, *args: str, repo_root: Path | None = None, environ: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    return _run(["bash", str(SCRIPT_DIR / "plan-path.sh"), subcommand, *args], cwd=repo_root or Path.cwd(), environ=environ)

def _run_plan_path_for_repo(repo_root: Path, subcommand: str, *args: str, environ: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    return _run(["bash", str(SCRIPT_DIR / "plan-path.sh"), subcommand, *args], cwd=repo_root, environ=environ, timeout=5)


def _run_session_helper(function: str, *args: str, repo_root: Path | None = None, environ: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    return _run(["bash", str(SCRIPT_DIR / "session-helpers.sh"), function, *args], cwd=repo_root or Path.cwd(), environ=environ)

def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_resolve(path: str | Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(Path(path).expanduser())


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def _status_counts_map(text: str) -> dict[str, int]:
    counts = {"done": 0, "pending": 0, "in_progress": 0, "other": 0}
    for part in text.split():
        key, sep, value = part.partition("=")
        if sep and key in counts:
            try:
                counts[key] = int(value)
            except ValueError:
                pass
    return counts


def _sha_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


@dataclass
class Citation:
    citation_id: str
    source_type: str
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None and v != ""}


@dataclass
class SourceStatus:
    provider: str
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    citation_ids: list[str] = field(default_factory=list)

    def bump(self, status: str, warning: str | None = None) -> None:
        self.status = _merge_status(self.status, status)
        if warning:
            self.warnings.append(warning)
        self.degraded = self.status not in {"ok", "missing"} or bool(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "degraded": self.degraded,
            "warnings": self.warnings,
            "citation_ids": self.citation_ids,
        }


@dataclass
class EvidenceRecord:
    evidence_id: str
    evidence_type: str
    provider: str
    source: str
    status: str
    validation_status: str
    candidate_id: str | None = None
    citation_id: str | None = None
    observed_at: str | None = None
    stale: bool = False
    superseded: bool = False
    degraded: bool = False
    truncated: bool = False
    side_evidence: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "evidence_id": self.evidence_id,
            "type": self.evidence_type,
            "provider": self.provider,
            "source": self.source,
            "source_path": self.source,
            "collected_at": self.observed_at,
            "citation": self.citation_id,
            "freshness": "stale" if self.stale else ("superseded" if self.superseded else "current_or_unknown"),
            "candidate_refs": [self.candidate_id] if self.candidate_id else [],
            "status": self.status,
            "validation_status": self.validation_status,
            "candidate_id": self.candidate_id,
            "citation_id": self.citation_id,
            "observed_at": self.observed_at,
            "stale": self.stale,
            "superseded": self.superseded,
            "degraded": self.degraded,
            "truncated": self.truncated,
            "side_evidence": self.side_evidence or self.evidence_type in SIDE_EVIDENCE_TYPES,
            "data": self.data,
        }
        return {k: _json_safe(v) for k, v in payload.items() if v is not None}


@dataclass
class Candidate:
    candidate_id: str
    slug: str
    target_type: str = "plan"
    repo_id: str | None = None
    repo_root: str | None = None
    plan_dir: str | None = None
    run_id: str | None = None
    run_dir: str | None = None
    recency_evidence: str | int | float | None = None
    branch: str | None = None
    worktree_path: str | None = None
    head: str | None = None
    status: str = "unknown"
    current_state: dict[str, Any] = field(default_factory=dict)
    confidence: str = "low"
    score: int = 0
    score_components: dict[str, int] = field(default_factory=dict)
    negative_evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    source_status: dict[str, str] = field(default_factory=dict)
    source_warnings: list[str] = field(default_factory=list)
    ambiguity_warnings: list[str] = field(default_factory=list)
    summary: str = ""
    selection_token: str = ""
    def as_dict(self) -> dict[str, Any]:
        payload = self.__dict__.copy()
        payload["evidence_refs"] = list(self.evidence_ids)
        payload["citations"] = list(self.citation_ids)
        flags = self.current_state.get("flags", {}) if isinstance(self.current_state, dict) else {}
        payload["primary_state"] = self.current_state.get("primary") if isinstance(self.current_state, dict) else "unknown"
        payload["state_flags"] = sorted(k for k, v in flags.items() if v)
        payload["state_reasons"] = {
            "score_components": self.score_components,
            "negative_evidence": self.negative_evidence,
        }
        return {k: _json_safe(v) for k, v in payload.items() if v not in (None, "")}


@dataclass
class ProviderResult:
    provider: str
    records: list[EvidenceRecord] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    status: SourceStatus = field(default_factory=lambda: SourceStatus(provider="unknown"))
    warnings: list[str] = field(default_factory=list)


@dataclass
class ContextSeed:
    argv: list[str]
    query: str
    raw_query_tokens: list[str]
    args: argparse.Namespace
    repo_root: Path
    generated_at: str
    environ: Mapping[str, str]
    repo_id: str | None = None
    base_dir: str | None = None
    plan_dir: str | None = None
    target_descriptor: dict[str, Any] = field(default_factory=dict)
    repo_sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    discovered_plan_dirs: list[str] = field(default_factory=list)


def _repo_identity_for_path(path: Path, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    root = path.expanduser()
    rc_root, out_root, _err_root = _run(["git", "rev-parse", "--show-toplevel"], cwd=root, timeout=5)
    if rc_root == 0 and out_root:
        root = Path(out_root)
    resolved = _safe_resolve(root) or str(root)
    rc_head, head, _err_head = _run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, timeout=5)
    rc_branch, branch, _err_branch = _run(["git", "branch", "--show-current"], cwd=root, timeout=5)
    if rc_root == 0:
        rc_repo_id, repo_id, _err_repo_id = _run_plan_path_for_repo(root, "z_harness_repo_id", environ=environ)
        rc_base, base_dir, _err_base = _run_plan_path_for_repo(root, "base_dir", environ=environ)
    else:
        rc_repo_id, repo_id = 1, ""
        rc_base, base_dir = 1, ""
    return {
        "repo_id": repo_id if rc_repo_id == 0 and repo_id else _sha_short(resolved),
        "repo_root": resolved,
        "repo_name": Path(resolved).name,
        "branch": branch if rc_branch == 0 else "",
        "head": head if rc_head == 0 else "",
        "base_dir": base_dir if rc_base == 0 and base_dir else None,
        "repo_id_source": "plan-path" if rc_repo_id == 0 and repo_id else "path-hash-fallback",
        "source": "git",
    }


def _discover_repo_sources(seed: ContextSeed, *, current_repo_id: str | None, current_base_dir: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    cap = max(1, int(getattr(seed.args, "max_candidates", 8) or 8))
    current = {
        "repo_id": current_repo_id,
        "repo_root": str(seed.repo_root),
        "repo_name": seed.repo_root.name,
        "current_repo": True,
        "source": "current",
    }
    sources: list[dict[str, Any]] = [current]
    requested = str(getattr(seed.args, "repo", "") or "").strip()
    if requested:
        requested_path = Path(requested).expanduser()
        if requested_path.exists():
            exact = _repo_identity_for_path(requested_path, seed.environ)
            exact.update({"current_repo": _safe_resolve(exact.get("repo_root")) == _safe_resolve(seed.repo_root), "source": "requested_repo_path"})
            sources.append(exact)
        else:
            sources.append({"repo_id": requested, "repo_root": None, "repo_name": requested, "current_repo": requested == current_repo_id, "source": "requested_repo_id", "unresolved": requested != current_repo_id})
    if getattr(seed.args, "all_repos", False):
        rc, out, err = _run(["git", "worktree", "list", "--porcelain"], cwd=seed.repo_root, timeout=5)
        if rc == 0:
            for raw in out.splitlines():
                key, _, value = raw.partition(" ")
                if key != "worktree" or not value:
                    continue
                sources.append({**_repo_identity_for_path(Path(value), seed.environ), "current_repo": _safe_resolve(value) == _safe_resolve(seed.repo_root), "source": "git_worktree"})
                if len(sources) >= cap:
                    warnings.append(f"--all-repos capped repo-source discovery at {cap} entries")
                    break
        else:
            warnings.append(f"--all-repos worktree discovery unavailable: {err or 'git worktree failed'}")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        key = str(source.get("repo_id") or source.get("repo_root") or source.get("repo_name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped[:cap], warnings


class EvidenceProvider:
    name = "provider"

    def collect(self, seed: ContextSeed) -> ProviderResult:  # pragma: no cover - interface
        raise NotImplementedError


class RepoIdentityProvider(EvidenceProvider):
    name = "repo_identity"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        rc_id, repo_id, err_id = _run_plan_path("z_harness_repo_id", repo_root=seed.repo_root, environ=seed.environ)
        rc_base, base_dir, err_base = _run_plan_path("base_dir", repo_root=seed.repo_root, environ=seed.environ)
        status = "ok"
        if rc_id != 0 or not repo_id:
            status = "unavailable"
            result.warnings.append(f"repo id unavailable: {err_id or 'empty output'}")
        if rc_base != 0 or not base_dir:
            status = _merge_status(status, "unavailable")
            result.warnings.append(f"z-harness base unavailable: {err_base or 'empty output'}")
        seed.repo_id = repo_id or None
        seed.base_dir = base_dir or None
        citation = Citation("cit-repo-identity", "plan-path", str(SCRIPT_DIR / "plan-path.sh"), description="plan-path.sh repo/base identity")
        result.citations.append(citation)
        result.status.citation_ids.append(citation.citation_id)
        result.status.bump(status)
        for warning in result.warnings:
            result.status.bump("degraded", warning)
        seed.repo_sources, repo_warnings = _discover_repo_sources(seed, current_repo_id=repo_id or None, current_base_dir=base_dir or None)
        for warning in repo_warnings:
            result.status.bump("partial", warning)
            result.warnings.append(warning)
        result.records.append(
            EvidenceRecord(
                evidence_id="ev-repo-identity",
                evidence_type="repo_identity",
                provider=self.name,
                source=str(SCRIPT_DIR / "plan-path.sh"),
                status=status,
                validation_status="valid" if status == "ok" else "degraded",
                citation_id=citation.citation_id,
                observed_at=seed.generated_at,
                degraded=status != "ok",
                data={"repo_root": str(seed.repo_root), "repo_id": repo_id, "base_dir": base_dir, "repo_sources": seed.repo_sources},
            )
        )
        requested_repo_matched = _repo_matches(seed)
        if seed.args.repo:
            validation = "valid" if requested_repo_matched else "degraded"
            status_for_repo = "ok" if requested_repo_matched else "partial"
            if not requested_repo_matched:
                result.status.bump("partial", f"--repo {seed.args.repo!r} did not match any bounded repo source")
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-repo-qualifier-{_sha_short(str(seed.args.repo))}",
                    evidence_type="repo_qualifier",
                    provider=self.name,
                    source=str(seed.args.repo),
                    status=status_for_repo,
                    validation_status=validation,
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    degraded=not requested_repo_matched,
                    data={
                        "requested_repo": seed.args.repo,
                        "matched": requested_repo_matched,
                        "bounded_repo_sources": seed.repo_sources,
                        "cap": max(1, int(seed.args.max_candidates or 8)),
                    },
                )
            )
        if seed.args.all_repos:
            result.records.append(
                EvidenceRecord(
                    evidence_id="ev-all-repos-scope",
                    evidence_type="repo_scope",
                    provider=self.name,
                    source="--all-repos",
                    status="ok" if seed.repo_sources else "missing",
                    validation_status="valid",
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    degraded=False,
                    data={
                        "repo_scope": "all_repos_opt_in",
                        "bounded": True,
                        "read_only": True,
                        "cap": max(1, int(seed.args.max_candidates or 8)),
                        "repo_sources": seed.repo_sources,
                    },
                )
            )
        return result


class TargetResolutionProvider(EvidenceProvider):
    name = "target_resolution"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        descriptor = {
            "mode": "exact_anchor" if _has_exact_target(seed.args) else ("fuzzy" if seed.query else "empty"),
            "query": seed.query,
            "slug": seed.args.slug,
            "run_id": seed.args.run,
            "branch": seed.args.branch,
            "worktree": seed.args.worktree,
            "artifact": seed.args.artifact,
            "repo": seed.args.repo,
            "select": seed.args.select,
            "resume_mode": getattr(seed.args, "resume_mode", None),
        }
        source = str(SCRIPT_DIR / "resume-context.py")
        citation = Citation("cit-target-resolution", "script", source, description="resume-context deterministic target parser")
        seed.target_descriptor = descriptor
        mode = str(descriptor.get("mode", "unknown"))
        validation = "valid" if mode not in {"error"} else "malformed"
        if mode in {"ambiguous", "not_found"}:
            validation = "unvalidated"
        result.citations.append(citation)
        result.status.citation_ids.append(citation.citation_id)
        if mode in {"error"}:
            result.status.bump("degraded", str(descriptor.get("message", "target resolution error")))
        elif mode in {"ambiguous", "not_found"}:
            result.status.bump("partial", str(descriptor.get("message", "target unresolved")))
        result.records.append(
            EvidenceRecord(
                evidence_id="ev-target-resolution",
                evidence_type="target_resolution",
                provider=self.name,
                source=source,
                status="ok" if validation == "valid" else result.status.status,
                validation_status=validation,
                citation_id=citation.citation_id,
                observed_at=seed.generated_at,
                degraded=validation == "malformed",
                data=descriptor,
            )
        )
        return result


def _value_matches_requested(requested: str, requested_resolved: str | None, values: set[str]) -> bool:
    if requested in values:
        return True
    resolved_values = {_safe_resolve(value) for value in values if value}
    return requested_resolved is not None and requested_resolved in resolved_values


def _repo_source_matches_requested(seed: ContextSeed, source: Mapping[str, Any]) -> bool:
    requested = str(seed.args.repo or "").strip()
    if not requested:
        return True
    if source.get("unresolved"):
        return False
    values = {str(source.get(key) or "") for key in ("repo_id", "repo_root", "repo_name", "branch", "head")}
    return _value_matches_requested(requested, _safe_resolve(requested), values)


def _selected_repo_sources(seed: ContextSeed) -> list[dict[str, Any]]:
    sources = [dict(source) for source in seed.repo_sources]
    if not sources:
        sources = [{"repo_id": seed.repo_id, "repo_root": str(seed.repo_root), "repo_name": seed.repo_root.name, "current_repo": True, "source": "current"}]
    requested = str(seed.args.repo or "").strip()
    if requested:
        selected = [source for source in sources if _repo_source_matches_requested(seed, source)]
    elif getattr(seed.args, "all_repos", False):
        selected = [source for source in sources if not source.get("unresolved")]
    else:
        selected = [source for source in sources if source.get("current_repo")]
        if not selected:
            selected = [sources[0]]
    cap = max(1, int(getattr(seed.args, "max_candidates", 8) or 8))
    return selected[:cap]


def _current_repo_selected(seed: ContextSeed) -> bool:
    return any(bool(source.get("current_repo")) for source in _selected_repo_sources(seed))


def _repo_matches(seed: ContextSeed, *, repo_id: str | None = None, repo_root: str | None = None, worktree_path: str | None = None, branch: str | None = None) -> bool:
    requested = str(seed.args.repo or "").strip()
    if not requested:
        return True
    requested_resolved = _safe_resolve(requested)
    values = {str(repo_id or ""), str(repo_root or ""), str(worktree_path or ""), str(branch or "")}
    if _value_matches_requested(requested, requested_resolved, values):
        return True
    if not any(values):
        return bool(_selected_repo_sources(seed))
    for source in _selected_repo_sources(seed):
        source_values = {str(source.get(key) or "") for key in ("repo_id", "repo_root", "repo_name", "branch", "head")}
        if values & source_values:
            return True
        resolved_source_values = {_safe_resolve(value) for value in source_values if value}
        resolved_values = {_safe_resolve(value) for value in values if value}
        if resolved_values & resolved_source_values:
            return True
    return False


def _resolve_plan_dir_for_slug(slug: str, seed: ContextSeed) -> Path | None:
    rc, out, _err = _run_plan_path("resolve_plan_path", slug, repo_root=seed.repo_root, environ=seed.environ)
    return Path(out) if rc == 0 and out else None

def _plan_dir_for_repo_source(slug: str, seed: ContextSeed, source: Mapping[str, Any], fallback: Path | None) -> Path | None:
    if source.get("current_repo"):
        return fallback or (_resolve_plan_dir_for_slug(slug, seed) if slug else None)
    repo_root_text = str(source.get("repo_root") or "")
    if not repo_root_text or not slug:
        return None
    if source.get("repo_id_source") and source.get("repo_id_source") != "plan-path":
        return None
    repo_root = Path(repo_root_text).expanduser()
    rc, out, _err = _run_plan_path_for_repo(repo_root, "plan_dir", slug, environ=seed.environ)
    if rc == 0 and out:
        return Path(out)
    base_dir = str(source.get("base_dir") or "")
    if base_dir:
        return Path(base_dir).expanduser() / "plans" / slug
    return None


def _candidate_id_for_plan(plan_dir: str | Path | None, slug: str, repo_id: str | None = None) -> str:
    basis = str(plan_dir) if plan_dir else f"{repo_id or ''}:{slug}"
    return f"cand-{_sha_short(basis)}"


def _selection_token(candidate_id: str, *, slug: str, repo_id: str | None = None, plan_dir: str | Path | None = None, run_id: str | None = None) -> str:
    parts = [f"candidate:{candidate_id}", f"slug:{slug}"]
    if repo_id:
        parts.append(f"repo:{repo_id}")
    if run_id:
        parts.append(f"run:{run_id}")
    if plan_dir:
        parts.append(f"path:{_sha_short(str(plan_dir))}")
    return "|".join(parts)

def _shell_command(*argv: str) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def _select_command(selection_token: str) -> str:
    return _shell_command("/z-resume", "--select", selection_token)


def _artifact_plan_dir(value: str | None) -> Path | None:
    if not value:
        return None
    artifact_path = Path(value).expanduser()
    if artifact_path.name not in {"TASKS.md", "SESSION.md", "SESSION_CONTEXT.md", "handoff.json", "HANDOFF.md", "REPORT.md", "context.json", "run-brief.json"}:
        return None
    parent = artifact_path.parent
    return parent.parent.parent if parent.parent.name == "archive" else parent


def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
    if not left or not right:
        return False
    return _safe_resolve(left) == _safe_resolve(right)


def _normalized_run_prefix(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return re.sub(r"[^0-9a-z]", "", raw)


def _run_id_matches_requested(candidate_run_id: str | None, requested: str | None) -> bool:
    if not candidate_run_id or not requested:
        return False
    candidate = str(candidate_run_id)
    request = str(requested).strip()
    if candidate == request:
        return True
    normalized_candidate = _normalized_run_prefix(candidate)
    normalized_request = _normalized_run_prefix(request)
    if not normalized_request or len(normalized_request) < 4:
        return False
    return normalized_candidate.startswith(normalized_request)


def _candidate_is_current(candidate: Candidate) -> bool:
    state = candidate.current_state if isinstance(candidate.current_state, Mapping) else {}
    flags = state.get("flags", {}) if isinstance(state, Mapping) else {}
    primary = str(state.get("primary") or candidate.status or "")
    return bool(flags.get("active_registry") or primary in {"active", "in_progress"})


def _explicit_recency_value(data: Mapping[str, Any]) -> Any | None:
    for field_name in ("mtime", "modified_at", "updated_at", "timestamp", "created_at", "generated_at"):
        value = data.get(field_name)
        if value not in (None, ""):
            return value
    return None


def _parse_recency_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    parsed_run = _parse_run_timestamp(text)
    if parsed_run is not None:
        return parsed_run
    try:
        return _parse_utc(text)
    except (TypeError, ValueError):
        try:
            return datetime.fromtimestamp(float(text), timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None


def _path_mtime_utc(value: str | Path | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(Path(value).stat().st_mtime, timezone.utc)
    except OSError:
        return None


def _candidate_latest_key(candidate: Candidate) -> datetime | None:
    parsed = _parse_run_timestamp(candidate.run_id)
    if parsed is not None:
        return parsed
    parsed = _parse_recency_timestamp(candidate.recency_evidence)
    if parsed is not None:
        return parsed
    return _path_mtime_utc(candidate.run_dir)


def _exact_matches(candidates: Sequence[Candidate], seed: ContextSeed) -> list[Candidate]:
    mode = getattr(seed.args, "resume_mode", None)
    if mode == "current":
        return [candidate for candidate in candidates if _candidate_is_current(candidate)]
    if mode == "latest":
        with_recency = [
            (candidate, key)
            for candidate in candidates
            if (key := _candidate_latest_key(candidate)) is not None
        ]
        if not with_recency or len(with_recency) != len(candidates):
            return []
        top_key = max(key for _, key in with_recency)
        return [candidate for candidate, key in with_recency if key == top_key]
    return [candidate for candidate in candidates if _candidate_matches_exact(candidate, seed)]


def _candidate_matches_exact(candidate: Candidate, seed: ContextSeed) -> bool:
    args = seed.args
    slug = getattr(args, "slug", None)
    run = getattr(args, "run", None)
    branch = getattr(args, "branch", None)
    worktree = getattr(args, "worktree", None)
    if slug and candidate.slug != slug:
        return False
    if run and not _run_id_matches_requested(candidate.run_id, run):
        return False
    if branch and candidate.branch != branch:
        return False
    if worktree and not _same_path(candidate.worktree_path, worktree):
        return False
    artifact_plan_dir = _artifact_plan_dir(getattr(args, "artifact", None))
    if artifact_plan_dir is not None and not _same_path(candidate.plan_dir, artifact_plan_dir):
        return False
    return any((slug, run, branch, worktree, artifact_plan_dir is not None))


def _has_exact_target(args: argparse.Namespace) -> bool:
    return any(getattr(args, field, None) for field in ("slug", "run", "branch", "worktree", "artifact", "select")) or bool(getattr(args, "resume_mode", None))


def _extract_hermes_slug(value: str) -> str:
    parts = [part for part in value.split("/") if part]
    for idx, part in enumerate(parts):
        if part == "hermes" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""




def _slug_from_worktree_record(raw: Mapping[str, Any]) -> str:
    branch = str(raw.get("branch") or raw.get("head") or "")
    path_value = str(raw.get("path") or raw.get("worktree_path") or "")
    path_name = Path(path_value).name
    for value in (branch, path_value, path_name):
        hermes_slug = _extract_hermes_slug(value)
        if hermes_slug:
            return hermes_slug
        m = re.search(r"(?:hermes/|hermes-)?([a-z0-9]+(?:-[a-z0-9]+)+)(?:/[A-Za-z0-9_.-]+|-[A-Za-z0-9]+)?$", value)
        if m:
            return m.group(1)
    return ""


def _worktree_state(path: str) -> dict[str, Any]:
    state = {"dirty": False, "divergent": False, "landed": False, "warnings": []}
    wt = Path(path)
    if not wt.is_dir():
        state["warnings"].append("worktree path missing")
        return state
    rc, out, err = _run(["git", "status", "--porcelain"], cwd=wt, timeout=5)
    if rc == 0:
        state["dirty"] = bool(out.strip())
    else:
        state["warnings"].append(f"git status unavailable: {err}")
    rc_branch, branch, _ = _run(["git", "branch", "--show-current"], cwd=wt, timeout=5)
    state["branch"] = branch if rc_branch == 0 else ""
    if rc_branch == 0 and branch and branch not in {"main", "prod"}:
        for target in ("main", "prod", "origin/main", "origin/prod"):
            rc_ref, _ref, _err_ref = _run(["git", "rev-parse", "--verify", "--quiet", target], cwd=wt, timeout=5)
            if rc_ref != 0:
                continue
            rc_ancestor, _out_ancestor, _err_ancestor = _run(["git", "merge-base", "--is-ancestor", "HEAD", target], cwd=wt, timeout=5)
            if rc_ancestor == 0:
                state["landed"] = True
                state["landed_target"] = target
                break
    rc_div, div, err_div = _run(["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd=wt, timeout=5)
    if rc_div == 0 and div:
        parts = div.split()
        if len(parts) == 2:
            try:
                state["divergent"] = int(parts[0]) > 0 and int(parts[1]) > 0
            except ValueError:
                pass
    elif err_div:
        state["warnings"].append(f"upstream divergence unavailable: {err_div}")
    return state


class ArtifactInventoryProvider(EvidenceProvider):
    name = "artifact_inventory"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        descriptor = seed.target_descriptor or {}
        seed_slug = seed.args.slug or descriptor.get("slug") or _slugify(seed.query)
        run_id = seed.args.run or descriptor.get("run_id") or "resume-context"
        plan_dir = Path(seed.args.plan_dir).expanduser() if seed.args.plan_dir else None
        artifact_plan_dir = _artifact_plan_dir(seed.args.artifact)
        if plan_dir is None and artifact_plan_dir is not None:
            plan_dir = artifact_plan_dir
            seed_slug = plan_dir.name
        if plan_dir is None and descriptor.get("mode") == "run" and descriptor.get("run_id"):
            for run_dir in _run_dirs_for_seed(seed):
                if run_dir.name != descriptor.get("run_id"):
                    continue
                archive_dir = run_dir.parent
                plan_dir = archive_dir.parent if archive_dir.name == "archive" else None
                if plan_dir is not None:
                    seed_slug = plan_dir.name
                    break
        if plan_dir is None and _current_repo_selected(seed):
            plan_dir = _resolve_plan_dir_for_slug(str(seed_slug), seed)
        selected_sources = _selected_repo_sources(seed)
        expand_discovered = bool(seed.query) and not any((seed.args.slug, seed.args.run, seed.args.plan_dir, seed.args.artifact))
        if not selected_sources:
            result.status.bump("partial", f"artifact inventory skipped because --repo={seed.args.repo!r} did not match any bounded repo source")
            return result
        inv_mod = _artifact_inventory()
        for source_idx, repo_source in enumerate(selected_sources):
            source_repo_root = Path(str(repo_source.get("repo_root") or seed.repo_root)).expanduser()
            if not source_repo_root.exists() and not repo_source.get("current_repo"):
                result.status.bump("partial", f"artifact inventory source repo missing: {source_repo_root}")
                continue
            source_plan_dir = _plan_dir_for_repo_source(str(seed_slug), seed, repo_source, plan_dir)
            should_scan_inventory = bool(
                seed.query
                or getattr(seed.args, "branch", None)
                or getattr(seed.args, "worktree", None)
                or getattr(seed.args, "select", None)
                or getattr(seed.args, "resume_mode", None)
                or not any((getattr(seed.args, "slug", None), getattr(seed.args, "run", None), getattr(seed.args, "artifact", None), getattr(seed.args, "plan_dir", None)))
            )
            if source_plan_dir is None and should_scan_inventory:
                source_plan_dir = source_repo_root
            if source_plan_dir is None:
                result.status.bump("partial", f"plan path unresolved for slug={seed_slug!r} in repo source {repo_source.get('repo_id') or repo_source.get('repo_root')}")
                continue
            source_seed = ContextSeed(
                argv=seed.argv,
                query=seed.query,
                raw_query_tokens=seed.raw_query_tokens,
                args=seed.args,
                repo_root=source_repo_root,
                generated_at=seed.generated_at,
                environ=seed.environ,
                repo_id=str(repo_source.get("repo_id") or seed.repo_id or "") or None,
                base_dir=seed.base_dir if repo_source.get("current_repo") else None,
                plan_dir=str(source_plan_dir),
                target_descriptor=seed.target_descriptor,
                repo_sources=[dict(repo_source)],
                warnings=seed.warnings,
            )
            if repo_source.get("current_repo"):
                seed.plan_dir = str(source_plan_dir)
            try:
                inventory = inv_mod.collect_inventory(
                    command="/z-resume",
                    slug=str(seed_slug),
                    run_id=str(run_id),
                    repo_root=source_repo_root,
                    plan_dir=source_plan_dir,
                    task=seed.query or None,
                    environ=seed.environ,
                    helper_root=HELPER_ROOT,
                )
            except Exception as exc:
                result.status.bump("degraded", f"artifact inventory failed for {source_repo_root}: {exc}")
                result.records.append(
                    EvidenceRecord(
                        evidence_id=f"ev-artifact-inventory-failure-{source_idx + 1}",
                        evidence_type="provider_failure",
                        provider=self.name,
                        source=str(source_repo_root),
                        status="degraded",
                        validation_status="degraded",
                        observed_at=seed.generated_at,
                        degraded=True,
                        data={"error": str(exc), "repo_source": repo_source},
                    )
                )
                continue

            citation_id = "cit-artifact-inventory" if source_idx == 0 else f"cit-artifact-inventory-{source_idx + 1}"
            citation = Citation(citation_id, "script", str(SCRIPT_DIR / "artifact-scout-inventory.py"), description=f"artifact-scout inventory collect_inventory for {source_repo_root}")
            result.citations.append(citation)
            result.status.citation_ids.append(citation.citation_id)
            for provider_name, provider_status in sorted((inventory.get("source_status") or {}).items()):
                result.status.bump(str(provider_status))
                if provider_status not in {"ok", "missing"}:
                    result.warnings.append(f"artifact inventory source {provider_name} status={provider_status} repo={source_repo_root}")
            if inventory.get("truncated"):
                result.status.bump("truncated", "artifact inventory truncated to JSON cap")
            result.records.append(
                EvidenceRecord(
                    evidence_id="ev-artifact-inventory" if source_idx == 0 else f"ev-artifact-inventory-{source_idx + 1}",
                    evidence_type="artifact_inventory",
                    provider=self.name,
                    source=str(SCRIPT_DIR / "artifact-scout-inventory.py"),
                    status=result.status.status,
                    validation_status="truncated" if inventory.get("truncated") else "valid",
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    degraded=result.status.degraded,
                    truncated=bool(inventory.get("truncated")),
                    data={
                        "source_status": inventory.get("source_status") or {},
                        "signals": inventory.get("signals") or {},
                        "dropped_counts": inventory.get("dropped_counts") or {},
                        "repo_source": repo_source,
                        "repo_root": str(source_repo_root),
                        "plan_dir": str(source_plan_dir),
                    },
                )
            )
            if expand_discovered and source_plan_dir.is_dir():
                discovered_path = str(source_plan_dir)
                if discovered_path not in seed.discovered_plan_dirs:
                    seed.discovered_plan_dirs.append(discovered_path)
            for bucket in ("mandatory_candidates", "historical_candidates"):
                for raw in inventory.get(bucket) or []:
                    if not isinstance(raw, dict):
                        continue
                    candidate = _candidate_from_inventory(raw, source_seed, bucket)
                    result.candidates.append(candidate)
                    if expand_discovered and candidate.plan_dir and Path(candidate.plan_dir).is_dir():
                        discovered_path = str(Path(candidate.plan_dir))
                        if discovered_path not in seed.discovered_plan_dirs:
                            seed.discovered_plan_dirs.append(discovered_path)
                    result.records.append(
                        EvidenceRecord(
                            evidence_id=f"ev-candidate-{candidate.candidate_id}",
                            evidence_type="plan_artifact",
                            provider=self.name,
                            source=str(raw.get("path") or ""),
                            status=str(raw.get("status") or "unknown"),
                            validation_status="truncated" if raw.get("truncated") else "valid",
                            candidate_id=candidate.candidate_id,
                            citation_id=citation.citation_id,
                            observed_at=seed.generated_at,
                            degraded=any(v not in {"ok", "missing"} for v in (raw.get("source_status") or {}).values()),
                            truncated=bool(raw.get("truncated")),
                            data={**raw, "repo_source": repo_source},
                        )
                    )
            for idx, raw in enumerate(inventory.get("active_records") or []):
                if not isinstance(raw, dict):
                    continue
                slug = str(raw.get("slug") or raw.get("plan_slug") or "")
                if not _repo_matches(source_seed, repo_id=str(raw.get("repo_id") or source_seed.repo_id or ""), repo_root=str(raw.get("repo_root") or ""), worktree_path=str(raw.get("worktree_path") or ""), branch=str(raw.get("branch") or "")):
                    continue
                plan_for_slug = Path(str(raw.get("plan_dir") or raw.get("plan_path"))) if raw.get("plan_dir") or raw.get("plan_path") else (_plan_dir_for_repo_source(slug, source_seed, repo_source, None) if slug else None)
                record_repo_id = str(raw.get("repo_id") or source_seed.repo_id or "")
                candidate_id = _candidate_id_for_plan(plan_for_slug or raw.get("worktree_path") or raw.get("branch") or raw.get("run_id"), slug or json.dumps(raw, sort_keys=True), record_repo_id)
                if slug:
                    repo_root = str(source_repo_root)
                    active_run_id = str(raw.get("run_id") or "") or None
                    result.candidates.append(
                        Candidate(
                            candidate_id=candidate_id,
                            slug=slug,
                            repo_id=record_repo_id,
                            repo_root=repo_root,
                            plan_dir=str(plan_for_slug) if plan_for_slug else None,
                            run_id=active_run_id,
                            recency_evidence=_explicit_recency_value(raw),
                            branch=str(raw.get("branch") or "") or None,
                            worktree_path=str(raw.get("worktree_path") or raw.get("path") or "") or None,
                            head=str(raw.get("head") or raw.get("capture_head") or "") or None,
                            status=str(raw.get("status") or "active"),
                            current_state=_state_from_status("active", active=True, degraded=False, archived_only=False),
                            confidence="high",
                            score=55,
                            score_components={"active_registry": 40, "registry_branch_worktree": 15},
                            selection_token=_selection_token(candidate_id, slug=slug, repo_id=record_repo_id, plan_dir=plan_for_slug, run_id=active_run_id),
                        )
                    )
                result.records.append(
                    EvidenceRecord(
                        evidence_id=f"ev-active-registry-{source_idx + 1}-{idx + 1}",
                        evidence_type="active_registry",
                        provider=self.name,
                        source="active-plan-registry.py list --json",
                        status=str(raw.get("status") or "active"),
                        validation_status="valid",
                        candidate_id=candidate_id if slug else None,
                        citation_id=citation.citation_id,
                        observed_at=seed.generated_at,
                        data={**raw, "repo_source": repo_source},
                    )
                )
                if expand_discovered and plan_for_slug and plan_for_slug.is_dir():
                    discovered_path = str(plan_for_slug)
                    if discovered_path not in seed.discovered_plan_dirs:
                        seed.discovered_plan_dirs.append(discovered_path)
            for idx, raw in enumerate(inventory.get("worktrees") or []):
                if not isinstance(raw, dict):
                    continue
                worktree_path = str(raw.get("path") or raw.get("worktree_path") or "")
                branch = str(raw.get("branch") or "")
                if not _repo_matches(source_seed, repo_id=source_seed.repo_id, repo_root=worktree_path, worktree_path=worktree_path, branch=branch):
                    continue
                slug = _slug_from_worktree_record(raw) or (str(seed.args.slug or "") if ((seed.args.worktree and worktree_path == seed.args.worktree) or (seed.args.branch and branch == seed.args.branch)) else "")
                plan_for_slug = _plan_dir_for_repo_source(slug, source_seed, repo_source, None) if slug else None
                candidate_id = _candidate_id_for_plan(plan_for_slug or worktree_path, slug, source_seed.repo_id) if slug else None
                requested_slugs = {str(value) for value in (seed.args.slug, descriptor.get("slug"), seed_slug) if value}
                explicit_worktree = bool(seed.args.worktree and worktree_path == seed.args.worktree)
                explicit_branch = bool(seed.args.branch and branch == seed.args.branch)
                candidate_backed = bool(slug and plan_for_slug and plan_for_slug.is_dir())
                should_probe = explicit_worktree or explicit_branch or bool(slug and slug in requested_slugs) or candidate_backed
                wt_state = _worktree_state(worktree_path) if should_probe else {"warnings": ["worktree not probed; association is unvalidated"], "not_probed": True}
                wt_validation = "valid" if slug and should_probe and not wt_state.get("not_probed") else "unvalidated"
                wt_degraded = bool(wt_state.get("warnings") or wt_state.get("not_probed"))
                if slug and candidate_id:
                    flags_state = _state_from_status("paused", active=False, degraded=wt_degraded, archived_only=False)
                    flags_state["flags"]["dirty"] = bool(wt_state.get("dirty"))
                    flags_state["flags"]["dirty_worktree"] = bool(wt_state.get("dirty"))
                    flags_state["flags"]["divergent"] = bool(wt_state.get("divergent"))
                    flags_state["flags"]["divergent_branch"] = bool(wt_state.get("divergent"))
                    if wt_state.get("dirty"):
                        flags_state["primary"] = "dirty"
                    elif wt_state.get("divergent"):
                        flags_state["primary"] = "divergent"
                    elif wt_state.get("landed"):
                        flags_state["primary"] = "landed"
                        flags_state["flags"]["landed_git"] = True
                    result.candidates.append(
                        Candidate(
                            candidate_id=candidate_id,
                            slug=slug,
                            repo_id=source_seed.repo_id,
                            repo_root=str(source_repo_root),
                            plan_dir=str(plan_for_slug) if plan_for_slug else None,
                            branch=branch or None,
                            worktree_path=worktree_path or None,
                            head=str(raw.get("head") or "") or None,
                            status="worktree",
                            current_state=flags_state,
                            confidence="medium",
                            score=20 - (10 if wt_degraded else 0),
                            score_components={"worktree_association": 20 if should_probe else 5, "branch_worktree_hint": 10 if explicit_branch else 0},
                            negative_evidence=([{"reason": "worktree_dirty", "penalty": -5}] if wt_state.get("dirty") else []) + ([{"reason": "worktree_divergent", "penalty": -10}] if wt_state.get("divergent") else []),
                            selection_token=_selection_token(candidate_id, slug=slug, repo_id=source_seed.repo_id, plan_dir=plan_for_slug),
                        )
                    )
                    if expand_discovered and plan_for_slug and plan_for_slug.is_dir():
                        discovered_path = str(plan_for_slug)
                        if discovered_path not in seed.discovered_plan_dirs:
                            seed.discovered_plan_dirs.append(discovered_path)
                result.records.append(
                    EvidenceRecord(
                        evidence_id=f"ev-worktree-{source_idx + 1}-{idx + 1}",
                        evidence_type="worktree",
                        provider=self.name,
                        source="git worktree list --porcelain",
                        status="ok" if not wt_degraded else "degraded",
                        validation_status=wt_validation,
                        candidate_id=candidate_id,
                        citation_id=citation.citation_id,
                        degraded=wt_degraded,
                        observed_at=seed.generated_at,
                        data={**raw, "associated_slug": slug, "git_state": wt_state, "repo_source": repo_source},
                    )
                )
                if branch:
                    result.records.append(
                        EvidenceRecord(
                            evidence_id=f"ev-branch-{source_idx + 1}-{idx + 1}",
                            evidence_type="branch",
                            provider=self.name,
                            source=branch,
                            status="ok" if not wt_degraded else "degraded",
                            validation_status=wt_validation,
                            candidate_id=candidate_id,
                            citation_id=citation.citation_id,
                            degraded=wt_degraded,
                            observed_at=seed.generated_at,
                            data={**raw, "associated_slug": slug, "repo_source": repo_source},
                        )
                    )
        return result


class PlanStateProvider(EvidenceProvider):
    name = "plan_state"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        plan_dirs = _candidate_plan_dirs(seed)
        if not plan_dirs:
            result.status.bump("missing", "no candidate plan directory available for plan-state validation")
            return result
        for idx, plan_dir in enumerate(plan_dirs[: seed.args.max_candidates]):
            candidate_id = f"cand-{_sha_short(str(plan_dir))}"
            plan_citation = Citation(f"cit-plan-state-{idx + 1}-plan", "plan_dir", str(plan_dir), description="candidate plan directory")
            result.citations.append(plan_citation)
            result.status.citation_ids.append(plan_citation.citation_id)
            self._collect_tasks(seed, result, plan_dir, candidate_id, self._file_citation(result, idx, "tasks", plan_dir / "TASKS.md"))
            self._collect_session(seed, result, plan_dir, candidate_id, self._file_citation(result, idx, "session", plan_dir / "SESSION.md"))
            self._collect_session_context(seed, result, plan_dir, candidate_id, self._file_citation(result, idx, "session-context", plan_dir / "SESSION_CONTEXT.md"))
            self._collect_handoff(seed, result, plan_dir, candidate_id, self._file_citation(result, idx, "handoff", plan_dir / "handoff.json"))
            self._collect_human_handoff(seed, result, plan_dir, candidate_id, self._file_citation(result, idx, "human-handoff", plan_dir / "HANDOFF.md"))
            self._collect_known_artifacts(seed, result, plan_dir, candidate_id, plan_citation.citation_id)
        return result

    def _file_citation(self, result: ProviderResult, idx: int, label: str, path: Path) -> str:
        citation = Citation(f"cit-plan-state-{idx + 1}-{label}", "file", str(path), description=f"{path.name} plan-state evidence")
        result.citations.append(citation)
        result.status.citation_ids.append(citation.citation_id)
        return citation.citation_id


    def _collect_tasks(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        tasks = plan_dir / "TASKS.md"
        if not tasks.is_file():
            result.status.bump("missing")
            result.records.append(_missing_record("tasks", self.name, tasks, candidate_id, citation_id, seed.generated_at))
            return
        rc_hash, done_hash, err_hash = _run_session_helper("done_set_hash", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
        rc_counts, counts_text, err_counts = _run_session_helper("task_status_counts", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
        rc_next, next_pending, err_next = _run_session_helper("next_pending_task", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
        validation = "valid"
        degraded = False
        warnings: list[str] = []
        if rc_hash != 0 or rc_counts != 0 or rc_next != 0:
            validation = "degraded"
            degraded = True
            warnings.append("session-helpers task parser failed")
            result.status.bump("degraded", f"TASKS.md helper failed: {err_hash or err_counts or err_next}")
        counts = _status_counts_map(counts_text)
        status = "completed" if counts.get("pending", 0) == 0 and counts.get("in_progress", 0) == 0 and sum(counts.values()) > 0 else "in_progress"
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-tasks-{_sha_short(str(tasks))}",
                evidence_type="tasks",
                provider=self.name,
                source=str(tasks),
                status=status,
                validation_status=validation,
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                degraded=degraded,
                data={"done_ids_hash": done_hash, "status_counts": counts, "next_pending": next_pending or None, "warnings": warnings},
            )
        )

    def _collect_session(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        session = plan_dir / "SESSION.md"
        tasks = plan_dir / "TASKS.md"
        if not session.is_file():
            result.status.bump("missing")
            result.records.append(_missing_record("session", self.name, session, candidate_id, citation_id, seed.generated_at))
            return
        try:
            text, truncated = _read_text(session)
        except OSError as exc:
            result.status.bump("corrupt", f"SESSION.md unreadable: {exc}")
            result.records.append(_degraded_record("session", self.name, session, candidate_id, citation_id, seed.generated_at, str(exc)))
            return
        fields = _parse_frontmatter(text)
        validation = "valid"
        degraded = False
        stale = False
        warnings: list[str] = []
        schema = fields.get("schema_version", "")
        if schema not in SUPPORTED_SESSION_SCHEMA_VERSIONS:
            validation = "malformed"
            degraded = True
            warnings.append(f"unsupported SESSION.md schema_version={schema!r}")
        if truncated:
            validation = "truncated" if validation == "valid" else validation
            result.status.bump("truncated", f"SESSION.md truncated while reading {session}")
        if tasks.is_file():
            rc_hash, done_hash, err_hash = _run_session_helper("done_set_hash", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
            rc_counts, counts_text, err_counts = _run_session_helper("task_status_counts", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
            rc_next, next_pending, err_next = _run_session_helper("next_pending_task", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
            rc_last, last_done, err_last = _run_session_helper("last_done_task", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
            counts = _status_counts_map(counts_text)
            if rc_hash != 0 or rc_counts != 0 or rc_next != 0 or rc_last != 0:
                validation = "degraded" if validation == "valid" else validation
                degraded = True
                warnings.append(f"could not validate SESSION.md against TASKS.md: {err_hash or err_counts or err_next or err_last}")
            session_hash = fields.get("done_ids_hash", "")
            if rc_hash == 0:
                if not session_hash:
                    validation = "degraded" if validation == "valid" else validation
                    degraded = True
                    warnings.append("SESSION.md missing done_ids_hash")
                elif done_hash != session_hash:
                    validation = "conflict"
                    degraded = True
                    stale = True
                    warnings.append("SESSION.md done_ids_hash does not match current TASKS.md")
            if rc_counts == 0:
                raw_done_count = fields.get("done_count", "")
                try:
                    session_done_count = int(raw_done_count)
                except ValueError:
                    session_done_count = None
                if raw_done_count == "" or session_done_count is None:
                    validation = "degraded" if validation == "valid" else validation
                    degraded = True
                    warnings.append("SESSION.md missing or invalid done_count")
                elif session_done_count != counts.get("done", 0):
                    validation = "conflict"
                    degraded = True
                    stale = True
                    warnings.append("SESSION.md done_count does not match current TASKS.md")
            if rc_last == 0:
                session_last = fields.get("last_gate_task_id", "")
                if not session_last and last_done:
                    validation = "degraded" if validation == "valid" else validation
                    degraded = True
                    warnings.append("SESSION.md missing last_gate_task_id")
                elif session_last and session_last != last_done:
                    validation = "conflict"
                    degraded = True
                    stale = True
                    warnings.append("SESSION.md last_gate_task_id does not match current TASKS.md")
            if rc_next == 0:
                session_next = fields.get("next_pending", "")
                if not session_next and next_pending:
                    validation = "degraded" if validation == "valid" else validation
                    degraded = True
                    warnings.append("SESSION.md missing next_pending")
                elif session_next and session_next != next_pending:
                    validation = "conflict"
                    degraded = True
                    stale = True
                    warnings.append("SESSION.md next_pending does not match current TASKS.md")
        else:
            validation = "degraded" if validation == "valid" else validation
            degraded = True
            warnings.append("SESSION.md could not be validated because TASKS.md is missing")
        result.status.bump("degraded" if degraded else "ok")
        for warning in warnings:
            result.status.bump("degraded", warning)
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-session-{_sha_short(str(session))}",
                evidence_type="session",
                provider=self.name,
                source=str(session),
                status="ok" if not degraded else "degraded",
                validation_status=validation,
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                stale=stale,
                degraded=degraded,
                truncated=truncated,
                data={"frontmatter": fields, "warnings": warnings},
            )
        )

    def _validate_handoff_payload(self, seed: ContextSeed, plan_dir: Path, payload: Mapping[str, Any]) -> tuple[str, bool, bool, list[str]]:
        validation = "valid"
        degraded = False
        stale = False
        warnings: list[str] = []
        protocol = str(payload.get("protocol_version", ""))
        if protocol not in {"1.0", "1.1"}:
            validation = "malformed"
            degraded = True
            warnings.append(f"unsupported handoff protocol_version={protocol!r}")
        required = ("timestamp", "agent", "status", "next_step", "context_files", "slug")
        for field_name in required:
            value = payload.get(field_name)
            if value in (None, ""):
                validation = "degraded" if validation == "valid" else validation
                degraded = True
                warnings.append(f"handoff missing required field {field_name}")
        if "context_files" in payload and not isinstance(payload.get("context_files"), list):
            validation = "malformed"
            degraded = True
            warnings.append("handoff context_files is not a list")
        payload_slug = str(payload.get("slug") or "")
        if payload_slug and payload_slug != plan_dir.name:
            validation = "conflict"
            degraded = True
            stale = True
            warnings.append("handoff slug does not match plan directory")
        attend = payload.get("attend_resume") if isinstance(payload.get("attend_resume"), dict) else None
        if protocol == "1.1":
            if attend is None:
                validation = "degraded" if validation == "valid" else validation
                degraded = True
                warnings.append("handoff protocol 1.1 missing attend_resume")
            else:
                for field_name in ("expected_head_sha", "expected_phase", "done_set_hash", "dirty_state_fingerprint", "session_id"):
                    if attend.get(field_name) in (None, ""):
                        validation = "degraded" if validation == "valid" else validation
                        degraded = True
                        warnings.append(f"handoff attend_resume missing {field_name}")
        tasks = plan_dir / "TASKS.md"
        if attend and tasks.is_file():
            rc_hash, done_hash, err_hash = _run_session_helper("done_set_hash", str(tasks), repo_root=seed.repo_root, environ=seed.environ)
            if rc_hash == 0 and attend.get("done_set_hash"):
                if attend.get("done_set_hash") != done_hash:
                    validation = "conflict"
                    degraded = True
                    stale = True
                    warnings.append("handoff attend_resume done_set_hash does not match current TASKS.md")
            elif rc_hash != 0:
                validation = "degraded" if validation == "valid" else validation
                degraded = True
                warnings.append(f"could not compute TASKS.md hash for handoff validation: {err_hash}")
        elif attend and not tasks.is_file():
            validation = "degraded" if validation == "valid" else validation
            degraded = True
            warnings.append("handoff could not be validated because TASKS.md is missing")
        return validation, degraded, stale, warnings

    def _session_context_freshly_linked(self, seed: ContextSeed, plan_dir: Path, path: Path) -> bool:
        handoff = plan_dir / "handoff.json"
        if not handoff.is_file():
            return False
        try:
            payload = json.loads(handoff.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        validation, degraded, stale, _warnings = self._validate_handoff_payload(seed, plan_dir, payload)
        if validation != "valid" or degraded or stale:
            return False
        context_files = payload.get("context_files")
        if not isinstance(context_files, list):
            return False
        path_text = str(path)
        return any(isinstance(item, dict) and item.get("path") == path_text for item in context_files)

    def _collect_session_context(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        path = plan_dir / "SESSION_CONTEXT.md"
        if not path.is_file():
            result.records.append(_missing_record("session_context", self.name, path, candidate_id, citation_id, seed.generated_at, side=True))
            return
        try:
            text, truncated = _read_text(path, max_bytes=2048)
        except OSError as exc:
            result.status.bump("corrupt", f"SESSION_CONTEXT.md unreadable: {exc}")
            result.records.append(_degraded_record("session_context", self.name, path, candidate_id, citation_id, seed.generated_at, str(exc), side=True))
            return
        freshly_linked = self._session_context_freshly_linked(seed, plan_dir, path)
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-session-context-{_sha_short(str(path))}",
                evidence_type="session_context",
                provider=self.name,
                source=str(path),
                status="ok",
                validation_status="valid" if freshly_linked else "unvalidated",
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                stale=not freshly_linked,
                truncated=truncated,
                side_evidence=True,
                data={
                    "excerpt": text[:1000],
                    "freshly_linked": freshly_linked,
                    "note": "side evidence only; stale unless freshly linked by valid handoff context_files",
                },
            )
        )

    def _collect_handoff(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        path = plan_dir / "handoff.json"
        if not path.is_file():
            result.status.bump("missing")
            result.records.append(_missing_record("handoff", self.name, path, candidate_id, citation_id, seed.generated_at))
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result.status.bump("corrupt", f"handoff.json malformed: {exc}")
            result.records.append(_degraded_record("handoff", self.name, path, candidate_id, citation_id, seed.generated_at, str(exc)))
            return
        validation, degraded, stale, warnings = self._validate_handoff_payload(seed, plan_dir, payload)
        protocol = str(payload.get("protocol_version", ""))
        if degraded:
            for warning in warnings:
                result.status.bump("degraded", warning)
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-handoff-{_sha_short(str(path))}",
                evidence_type="handoff",
                provider=self.name,
                source=str(path),
                status="ok" if not degraded else "degraded",
                validation_status=validation,
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                stale=stale,
                degraded=degraded,
                data={
                    "protocol_version": protocol,
                    "status": payload.get("status"),
                    "slug": payload.get("slug"),
                    "next_step": payload.get("next_step"),
                    "context_files": payload.get("context_files") if isinstance(payload.get("context_files"), list) else [],
                    "warnings": warnings,
                },
            )
        )

    def _collect_human_handoff(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        path = plan_dir / "HANDOFF.md"
        if not path.is_file():
            result.records.append(_missing_record("human_handoff", self.name, path, candidate_id, citation_id, seed.generated_at, side=True))
            return
        try:
            text, truncated = _read_text(path, max_bytes=2048)
        except OSError as exc:
            result.status.bump("corrupt", f"HANDOFF.md unreadable: {exc}")
            result.records.append(_degraded_record("human_handoff", self.name, path, candidate_id, citation_id, seed.generated_at, str(exc), side=True))
            return
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-human-handoff-{_sha_short(str(path))}",
                evidence_type="human_handoff",
                provider=self.name,
                source=str(path),
                status="ok",
                validation_status="unvalidated",
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                side_evidence=True,
                truncated=truncated,
                data={"excerpt": text[:1000], "note": "human HANDOFF.md is side evidence until validated by selected command context"},
            )
        )

    def _collect_known_artifacts(self, seed: ContextSeed, result: ProviderResult, plan_dir: Path, candidate_id: str, citation_id: str) -> None:
        artifacts: list[str] = []
        for name in ("INTENT.md", "SPEC.md", "PLAN.md", "TASKS.md", "SESSION.md", "SESSION_CONTEXT.md", "handoff.json", "HANDOFF.md", "REPORT.md"):
            path = plan_dir / name
            if path.exists():
                artifacts.append(str(path))
        archive = plan_dir / "archive"
        if archive.is_dir():
            for run_dir in sorted((path for path in archive.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True)[:3]:
                for name in ("context.json", "run-brief.json", "REPORT.md"):
                    path = run_dir / name
                    if path.exists():
                        artifacts.append(str(path))
        result.records.append(
            EvidenceRecord(
                evidence_id=f"ev-known-artifacts-{_sha_short(str(plan_dir))}",
                evidence_type="known_artifacts",
                provider=self.name,
                source=str(plan_dir),
                status="ok" if artifacts else "missing",
                validation_status="valid",
                candidate_id=candidate_id,
                citation_id=citation_id,
                observed_at=seed.generated_at,
                data={"artifacts": artifacts},
            )
        )


def _run_dirs_for_seed(seed: ContextSeed) -> list[Path]:
    dirs: list[Path] = []
    cap = max(1, int(seed.args.max_candidates or 8))
    candidate_dirs = _candidate_plan_dirs(seed)
    for plan_dir in candidate_dirs:
        archive = plan_dir / "archive"
        if seed.args.run:
            for run_dir in archive.iterdir() if archive.is_dir() else []:
                if run_dir.is_dir() and _run_id_matches_requested(run_dir.name, seed.args.run):
                    dirs.append(run_dir)
        elif archive.is_dir():
            dirs.extend(sorted((path for path in archive.iterdir() if path.is_dir()), key=lambda p: p.name, reverse=True)[:1])
    if seed.args.run and seed.base_dir and _current_repo_selected(seed):
        plans_root = Path(seed.base_dir).expanduser() / "plans"
        if plans_root.is_dir():
            scan_cap = max(cap, len(candidate_dirs)) + cap
            plan_children: list[Path] = []
            try:
                for child in plans_root.iterdir():
                    if not child.is_dir():
                        continue
                    if len(plan_children) >= scan_cap:
                        seed.warnings.append(f"run discovery capped bounded plans root {plans_root} at {scan_cap} plan dirs")
                        break
                    plan_children.append(child)
            except OSError as exc:
                seed.warnings.append(f"run discovery could not read bounded plans root {plans_root}: {exc}")
                plan_children = []
            plan_children.sort(key=lambda p: p.name)
            for plan_dir in plan_children:
                archive = plan_dir / "archive"
                if not archive.is_dir():
                    continue
                for run_dir in archive.iterdir():
                    if run_dir.is_dir() and _run_id_matches_requested(run_dir.name, seed.args.run):
                        dirs.append(run_dir)
    if seed.args.run:
        matched_names = {path.name for path in dirs}
        if len(matched_names) > 1:
            setattr(seed.args, "run_prefix_ambiguous", True)
            seed.warnings.append(f"run prefix {seed.args.run!r} matched multiple bounded runs")
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in dirs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
        if len(deduped) >= cap:
            if len(dirs) > cap:
                seed.warnings.append(f"run discovery capped matches for run {seed.args.run!r} at {cap}")
            break
    return deduped


def _candidate_for_run_dir(run_dir: Path, seed: ContextSeed) -> tuple[str, str, Path]:
    plan_dir = run_dir.parent.parent if run_dir.parent.name == "archive" else run_dir.parent
    slug = plan_dir.name
    candidate_id = _candidate_id_for_plan(plan_dir, slug, seed.repo_id)
    return candidate_id, slug, plan_dir


class GitLogProvider(EvidenceProvider):
    name = "git_log"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        selected_sources = _selected_repo_sources(seed)
        if not selected_sources:
            result.status.bump("partial", f"git log skipped because --repo={seed.args.repo!r} did not match any bounded repo source")
            return result
        for idx, repo_source in enumerate(selected_sources):
            repo_root_text = str(repo_source.get("repo_root") or "")
            if not repo_root_text:
                result.status.bump("partial", f"git log repo source has no repo_root: {repo_source.get('repo_id') or repo_source.get('repo_name')}")
                continue
            repo_root = Path(repo_root_text).expanduser()
            citation_id = "cit-git-log" if idx == 0 else f"cit-git-log-{idx + 1}"
            citation = Citation(citation_id, "git", str(repo_root), description="bounded git HEAD/log/branch evidence")
            result.citations.append(citation)
            result.status.citation_ids.append(citation.citation_id)
            rc_head, head, err_head = _run(["git", "rev-parse", "--short=12", "HEAD"], cwd=repo_root, timeout=5)
            rc_branch, branch, _err_branch = _run(["git", "branch", "--show-current"], cwd=repo_root, timeout=5)
            source_repo_id = str(repo_source.get("repo_id") or seed.repo_id or "") or None
            if rc_head != 0:
                result.status.bump("unavailable", f"git HEAD unavailable for {repo_root}: {err_head}")
                result.records.append(_degraded_record("git_commit", self.name, repo_root, None, citation.citation_id, seed.generated_at, err_head or "git HEAD unavailable"))
                continue
            branch_value = branch if rc_branch == 0 else ""
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-git-commit-{head}-{idx + 1}",
                    evidence_type="git_commit",
                    provider=self.name,
                    source=str(repo_root),
                    status="ok",
                    validation_status="valid",
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    data={"head": head, "branch": branch_value, "repo_id": source_repo_id, "repo_root": str(repo_root), "repo_source": repo_source},
                )
            )
            if branch_value:
                result.records.append(
                    EvidenceRecord(
                        evidence_id=f"ev-branch-current-{_sha_short(str(repo_root) + ':' + branch_value)}",
                        evidence_type="branch",
                        provider=self.name,
                        source=branch_value,
                        status="ok",
                        validation_status="valid",
                        citation_id=citation.citation_id,
                        observed_at=seed.generated_at,
                        data={"branch": branch_value, "head": head, "repo_id": source_repo_id, "repo_root": str(repo_root), "repo_source": repo_source},
                    )
                )
            log_args = ["git", "log", "-n", "5", "--pretty=%H%x09%s"]
            if seed.args.branch:
                log_args.insert(2, seed.args.branch)
            rc_log, log_out, err_log = _run(log_args, cwd=repo_root, timeout=5)
            validation = "valid" if rc_log == 0 else "degraded"
            if rc_log != 0:
                result.status.bump("partial", f"git log unavailable for {repo_root}: {err_log}")
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-git-log-{_sha_short(str(repo_root) + ':' + (seed.args.branch or branch_value))}",
                    evidence_type="git_log",
                    provider=self.name,
                    source=seed.args.branch or str(repo_root),
                    status="ok" if rc_log == 0 else "partial",
                    validation_status=validation,
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    degraded=rc_log != 0,
                    data={
                        "branch": seed.args.branch or branch_value,
                        "head": head,
                        "repo_id": source_repo_id,
                        "repo_root": str(repo_root),
                        "entries": log_out.splitlines()[:5],
                        "error": err_log if rc_log != 0 else "",
                        "repo_source": repo_source,
                    },
                )
            )
        return result


class _RunFileProvider(EvidenceProvider):
    name = "run_file"
    evidence_type = "run_file"
    file_name = ""

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        run_dirs = _run_dirs_for_seed(seed)
        if not run_dirs:
            result.status.bump("missing", f"no run directory available for {self.file_name}")
        if not run_dirs:
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-{self.evidence_type}-missing",
                    evidence_type=self.evidence_type,
                    provider=self.name,
                    source=self.file_name or self.name,
                    status="missing",
                    validation_status="missing",
                    observed_at=seed.generated_at,
                )
            )
            return result
        for idx, run_dir in enumerate(run_dirs):
            candidate_id, slug, plan_dir = _candidate_for_run_dir(run_dir, seed)
            path = run_dir / self.file_name
            citation = Citation(f"cit-{self.name}-{idx + 1}", "file", str(path), description=f"{self.file_name} run evidence")
            result.citations.append(citation)
            result.status.citation_ids.append(citation.citation_id)
            if not path.is_file():
                result.status.bump("missing", f"{self.file_name} missing in {run_dir}")
                result.records.append(_missing_record(self.evidence_type, self.name, path, candidate_id, citation.citation_id, seed.generated_at))
                continue
            try:
                text, truncated = _read_text(path)
            except OSError as exc:
                result.status.bump("corrupt", f"{self.file_name} unreadable: {exc}")
                result.records.append(_degraded_record(self.evidence_type, self.name, path, candidate_id, citation.citation_id, seed.generated_at, str(exc)))
                continue
            data: dict[str, Any] = {"slug": slug, "run_id": run_dir.name, "plan_dir": str(plan_dir), "excerpt": text[:1000]}
            validation = "valid"
            if path.suffix == ".json":
                try:
                    payload = json.loads(text)
                    data["json_keys"] = sorted(str(k) for k in payload.keys())[:20] if isinstance(payload, dict) else []
                    if isinstance(payload, dict):
                        data.update({k: payload.get(k) for k in ("status", "slug", "command", "intent", "outcome") if k in payload})
                except ValueError as exc:
                    validation = "malformed"
                    result.status.bump("corrupt", f"{self.file_name} malformed: {exc}")
            if truncated:
                validation = "truncated" if validation == "valid" else validation
                result.status.bump("truncated", f"{self.file_name} truncated")
            else:
                result.status.bump("ok")
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-{self.evidence_type}-{_sha_short(str(path))}",
                    evidence_type=self.evidence_type,
                    provider=self.name,
                    source=str(path),
                    status="ok" if validation == "valid" else "degraded",
                    validation_status=validation,
                    candidate_id=candidate_id,
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    degraded=validation in {"malformed", "degraded"},
                    truncated=truncated,
                    data=data,
                )
            )
        return result


class DecisionsProvider(EvidenceProvider):
    name = "decisions"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        run_dirs = _run_dirs_for_seed(seed)
        if not run_dirs:
            result.status.bump("missing", "no run directory available for decisions")
        if not run_dirs:
            result.records.append(EvidenceRecord("ev-decisions-missing", "decisions", self.name, "events.jsonl", "missing", "missing", observed_at=seed.generated_at))
            return result
        decision_kinds = {"user_choice", "user_override", "plan_route_decision", "next_step_choice", "decision"}
        for idx, run_dir in enumerate(run_dirs):
            candidate_id, slug, plan_dir = _candidate_for_run_dir(run_dir, seed)
            path = run_dir / "events.jsonl"
            citation = Citation(f"cit-decisions-{idx + 1}", "file", str(path), description="bounded events.jsonl decisions")
            result.citations.append(citation)
            result.status.citation_ids.append(citation.citation_id)
            if not path.is_file():
                result.status.bump("missing", f"events.jsonl missing in {run_dir}")
                result.records.append(_missing_record("decisions", self.name, path, candidate_id, citation.citation_id, seed.generated_at))
                continue
            decisions: list[dict[str, Any]] = []
            try:
                text, truncated = _read_text(path)
                for line in text.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and str(event.get("kind") or event.get("type") or "") in decision_kinds:
                        decisions.append({k: event.get(k) for k in ("kind", "type", "choice", "decision", "summary", "timestamp") if k in event})
            except OSError as exc:
                result.status.bump("corrupt", f"events.jsonl unreadable: {exc}")
                result.records.append(_degraded_record("decisions", self.name, path, candidate_id, citation.citation_id, seed.generated_at, str(exc)))
                continue
            result.status.bump("truncated" if truncated else "ok")
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-decisions-{_sha_short(str(path))}",
                    evidence_type="decisions",
                    provider=self.name,
                    source=str(path),
                    status="ok",
                    validation_status="truncated" if truncated else "valid",
                    candidate_id=candidate_id,
                    citation_id=citation.citation_id,
                    observed_at=seed.generated_at,
                    truncated=truncated,
                    data={"slug": slug, "run_id": run_dir.name, "plan_dir": str(plan_dir), "decisions": decisions[:10], "decision_count": len(decisions)},
                )
            )
        return result


class ContextJsonProvider(_RunFileProvider):
    name = "context_json"
    evidence_type = "context_json"
    file_name = "context.json"


class RunBriefProvider(_RunFileProvider):
    name = "run_brief"
    evidence_type = "run_brief"
    file_name = "run-brief.json"



class SideEvidenceProvider(EvidenceProvider):
    name = "side_evidence"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        policy = Citation(
            "cit-side-evidence-policy",
            "policy",
            description="followups, memories, and cheap inference are side evidence only and never current-state proof",
        )
        result.citations.append(policy)
        result.status.citation_ids.append(policy.citation_id)
        self._collect_followups(seed, result)
        self._collect_memories(seed, result)
        result.records.append(
            EvidenceRecord(
                evidence_id="ev-subagent-judgment-side-policy",
                evidence_type="subagent_judgment",
                provider=self.name,
                source="cheap inference is disabled in deterministic resume-context",
                status="missing",
                validation_status="missing",
                citation_id=policy.citation_id,
                observed_at=seed.generated_at,
                side_evidence=True,
                data={"proof_policy": "side_evidence_only", "current_state_proof": False},
            )
        )
        return result

    def _match_text(self, seed: ContextSeed, *values: Any) -> bool:
        needles = {str(seed.args.slug or ""), str(seed.args.run or ""), str(seed.args.branch or "")}
        needles.update(_tokenize(seed.query))
        needles = {needle.lower() for needle in needles if needle}
        if not needles:
            return True
        haystack = " ".join(str(value or "") for value in values).lower()
        return any(needle in haystack for needle in needles)

    def _followup_roots(self, seed: ContextSeed) -> list[tuple[str, Path]]:
        roots: list[tuple[str, Path]] = []
        if seed.base_dir:
            roots.append(("project", Path(seed.base_dir) / "followups"))
        roots.append(("project", seed.repo_root / "z-harness" / "followups"))
        home = Path(str(seed.environ.get("HOME") or Path.home())).expanduser()
        roots.append(("global", home / ".z-harness" / "followups"))
        deduped: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for label, root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((label, root))
        return deduped

    def _load_followup_entries(self, view_path: Path) -> list[dict[str, Any]]:
        payload = json.loads(view_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
        if not isinstance(payload, dict):
            return []
        entries = payload.get("entries", payload)
        if isinstance(entries, dict):
            return [entry for entry in entries.values() if isinstance(entry, dict)]
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return []

    def _collect_followups(self, seed: ContextSeed, result: ProviderResult) -> None:
        cap = max(1, int(seed.args.max_candidates or 8))
        emitted = 0
        found_source = False
        for sink_label, root in self._followup_roots(seed):
            view_path = root / "index.view.json"
            citation = Citation(f"cit-followup-{sink_label}-{_sha_short(str(root))}", "followup_sink", str(view_path), description=f"{sink_label} followup sink materialized view")
            result.citations.append(citation)
            result.status.citation_ids.append(citation.citation_id)
            if not view_path.is_file():
                continue
            found_source = True
            try:
                entries = self._load_followup_entries(view_path)
            except (OSError, ValueError) as exc:
                result.status.bump("degraded", f"followup sink unreadable: {view_path}: {exc}")
                result.records.append(_degraded_record("followup", self.name, view_path, None, citation.citation_id, seed.generated_at, str(exc), side=True))
                continue
            for entry in entries:
                values = [
                    entry.get("id"),
                    entry.get("name"),
                    entry.get("title"),
                    entry.get("slug"),
                    entry.get("recommended_command"),
                    entry.get("source_artifact"),
                    " ".join(str(path) for path in entry.get("cited_paths") or []),
                ]
                if not self._match_text(seed, *values):
                    continue
                status = str(entry.get("status") or "unknown")
                result.records.append(
                    EvidenceRecord(
                        evidence_id=f"ev-followup-{_sha_short(str(view_path) + ':' + str(entry.get('id') or emitted))}",
                        evidence_type="followup",
                        provider=self.name,
                        source=str(view_path),
                        status="ok",
                        validation_status="unvalidated",
                        citation_id=citation.citation_id,
                        observed_at=seed.generated_at,
                        side_evidence=True,
                        data={
                            "sink": sink_label,
                            "entry_id": entry.get("id"),
                            "title": entry.get("name") or entry.get("title"),
                            "status": status,
                            "capture_head": entry.get("capture_head"),
                            "cited_paths": entry.get("cited_paths") or [],
                            "source_artifact": entry.get("source_artifact"),
                            "status_history": entry.get("status_history") or [],
                            "source_hierarchy": [str(view_path), str(root / "index.jsonl")],
                            "current_state_proof": False,
                            "proof_policy": "side_evidence_only",
                        },
                    )
                )
                emitted += 1
                if emitted >= cap:
                    result.status.bump("ok")
                    return
        if emitted:
            result.status.bump("ok")
        elif found_source:
            result.status.bump("missing")
        else:
            result.status.bump("missing")
            first_root = self._followup_roots(seed)[0][1]
            result.records.append(_missing_record("followup", self.name, first_root / "index.view.json", None, None, seed.generated_at, side=True))

    def _collect_memories(self, seed: ContextSeed, result: ProviderResult) -> None:
        cap = max(1, int(seed.args.max_candidates or 8))
        docs_dir = seed.repo_root / "docs" / "llm"
        flat = docs_dir / "MEMORIES-FLAT.md"
        citation = Citation("cit-memory-flat", "memory_doc", str(flat), description="flattened memory index")
        result.citations.append(citation)
        result.status.citation_ids.append(citation.citation_id)
        if not flat.is_file():
            result.status.bump("missing")
            result.records.append(_missing_record("memory", self.name, flat, None, citation.citation_id, seed.generated_at, side=True))
            return
        try:
            text, truncated = _read_text(flat, max_bytes=MAX_TEXT_BYTES)
        except OSError as exc:
            result.status.bump("degraded", f"memory flat doc unreadable: {exc}")
            result.records.append(_degraded_record("memory", self.name, flat, None, citation.citation_id, seed.generated_at, str(exc), side=True))
            return
        matches: list[tuple[int, str]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if self._match_text(seed, line):
                matches.append((line_no, line.strip()))
            if len(matches) >= cap:
                break
        if not matches:
            result.status.bump("missing")
            return
        for line_no, line in matches:
            line_citation = Citation(f"cit-memory-flat-{line_no}", "memory_doc", str(flat), line_no, line_no, "matching memory line")
            result.citations.append(line_citation)
            result.status.citation_ids.append(line_citation.citation_id)
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-memory-{_sha_short(str(flat) + ':' + str(line_no))}",
                    evidence_type="memory",
                    provider=self.name,
                    source=str(flat),
                    status="ok",
                    validation_status="unvalidated",
                    citation_id=line_citation.citation_id,
                    observed_at=seed.generated_at,
                    side_evidence=True,
                    truncated=truncated,
                    data={
                        "line": line,
                        "line_start": line_no,
                        "source_hierarchy": [str(flat), str(docs_dir)],
                        "current_state_proof": False,
                        "proof_policy": "side_evidence_only",
                    },
                )
            )
        result.status.bump("truncated" if truncated else "ok")



class FollowupEvidenceProvider(SideEvidenceProvider):
    name = "followup_evidence"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        self._collect_followups(seed, result)
        return result


class MemoryEvidenceProvider(SideEvidenceProvider):
    name = "memory_evidence"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        self._collect_memories(seed, result)
        return result


class SideEvidencePolicyProvider(EvidenceProvider):
    name = "side_evidence_policy"

    def collect(self, seed: ContextSeed) -> ProviderResult:
        result = ProviderResult(provider=self.name, status=SourceStatus(provider=self.name))
        citation = Citation(
            "cit-side-evidence-policy",
            "policy",
            description="cheap inference and unvalidated side evidence never prove current state",
        )
        result.citations.append(citation)
        result.status.citation_ids.append(citation.citation_id)
        result.status.bump("missing")
        result.records.append(
            EvidenceRecord(
                evidence_id="ev-subagent-judgment-side-policy",
                evidence_type="subagent_judgment",
                provider=self.name,
                source="cheap inference is disabled in deterministic resume-context",
                status="missing",
                validation_status="missing",
                citation_id=citation.citation_id,
                observed_at=seed.generated_at,
                side_evidence=True,
                data={"proof_policy": "side_evidence_only", "current_state_proof": False},
            )
        )
        return result

def _missing_record(evidence_type: str, provider: str, path: Path, candidate_id: str | None, citation_id: str | None, observed_at: str, side: bool = False) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"ev-{evidence_type}-missing-{_sha_short(str(path))}",
        evidence_type=evidence_type,
        provider=provider,
        source=str(path),
        status="missing",
        validation_status="missing",
        candidate_id=candidate_id,
        citation_id=citation_id,
        observed_at=observed_at,
        side_evidence=side,
    )


def _degraded_record(evidence_type: str, provider: str, path: Path, candidate_id: str | None, citation_id: str | None, observed_at: str, reason: str, side: bool = False) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"ev-{evidence_type}-degraded-{_sha_short(str(path))}",
        evidence_type=evidence_type,
        provider=provider,
        source=str(path),
        status="degraded",
        validation_status="degraded",
        candidate_id=candidate_id,
        citation_id=citation_id,
        observed_at=observed_at,
        degraded=True,
        side_evidence=side,
        data={"reason": reason},
    )


def _candidate_from_inventory(raw: Mapping[str, Any], seed: ContextSeed, bucket: str) -> Candidate:
    slug = str(raw.get("slug") or _slugify(str(raw.get("path") or seed.query)))
    plan_dir = str(raw.get("path") or "")
    target_run_id = str(seed.args.run or (seed.target_descriptor or {}).get("run_id") or "") or None
    target_plan = _safe_resolve(seed.plan_dir) if seed.plan_dir else None
    candidate_plan = _safe_resolve(plan_dir) if plan_dir else None
    run_id = str(raw.get("run_id") or "") or (target_run_id if target_run_id and target_plan and candidate_plan == target_plan else None)
    candidate_id = f"cand-{_sha_short(plan_dir or slug)}"
    score = int(raw.get("score") or 0)
    components = {"artifact_inventory": score}
    basis = set(str(x) for x in raw.get("basis") or [])
    if "exact_slug" in basis:
        components["exact_slug"] = 100
    if bucket == "mandatory_candidates":
        components["current_plan_dir"] = 25
    status = str(raw.get("status") or "unknown")
    source_status = {str(k): str(v) for k, v in (raw.get("source_status") or {}).items()}
    degraded = any(v not in {"ok", "missing"} for v in source_status.values()) or bool(raw.get("truncated"))
    confidence = "high" if components.get("exact_slug") else ("medium" if score >= 20 else "low")
    state = _state_from_status(status, active=False, degraded=degraded, archived_only=bucket == "historical_candidates")
    total_score = sum(components.values()) - (20 if degraded else 0)
    return Candidate(
        candidate_id=candidate_id,
        slug=slug,
        target_type="plan",
        repo_id=seed.repo_id,
        repo_root=str(seed.repo_root),
        plan_dir=plan_dir,
        run_id=run_id,
        recency_evidence=_explicit_recency_value(raw),
        status=status,
        current_state=state,
        confidence=confidence,
        score=total_score,
        score_components=components,
        negative_evidence=([{"reason": "degraded_or_truncated_sources", "penalty": -20}] if degraded else []),
        source_status=source_status,
        summary=str(raw.get("summary_excerpt") or ""),
        selection_token=_selection_token(candidate_id, slug=slug, repo_id=seed.repo_id, plan_dir=plan_dir, run_id=run_id),
    )


def _state_from_status(status: str, *, active: bool, degraded: bool, archived_only: bool) -> dict[str, Any]:
    normalized = (status or "unknown").lower()
    if active:
        primary = "active"
    elif normalized in {"landed", "merged", "released"}:
        primary = "landed"
    elif normalized in {"finished", "completed", "done"}:
        primary = "completed"
    elif normalized in {"blocked", "halted"}:
        primary = "blocked"
    elif normalized in {"dirty"}:
        primary = "dirty"
    elif normalized in {"divergent"}:
        primary = "divergent"
    elif normalized in {"stale"}:
        primary = "stale"
    elif normalized in {"superseded"}:
        primary = "superseded"
    elif normalized in {"active", "running"}:
        primary = "active"
    elif normalized in {"in_progress", "paused", "pending"}:
        primary = "paused"
    elif archived_only:
        primary = "archived_only"
    else:
        primary = "unknown"
    flags = {flag: False for flag in STATE_FLAGS}
    flags["degraded"] = bool(degraded)
    flags["degraded_sources"] = bool(degraded)
    flags["archived_only"] = bool(archived_only)
    return {"primary": primary, "flags": flags, "precedence": PRIMARY_STATE_PRECEDENCE}


def _path_within_repo_source(path: Path, source: Mapping[str, Any]) -> bool:
    repo_root = _safe_resolve(source.get("repo_root"))
    resolved = _safe_resolve(path)
    if not repo_root or not resolved:
        return bool(source.get("current_repo"))
    try:
        Path(resolved).relative_to(Path(repo_root))
        return True
    except ValueError:
        return False


def _candidate_plan_dirs(seed: ContextSeed) -> list[Path]:
    dirs: list[Path] = []
    explicit_dirs: list[Path] = []
    if seed.args.plan_dir:
        explicit_dirs.append(Path(seed.args.plan_dir).expanduser())
    if seed.args.artifact:
        artifact_path = Path(seed.args.artifact).expanduser()
        if artifact_path.name in {"TASKS.md", "SESSION.md", "SESSION_CONTEXT.md", "handoff.json", "HANDOFF.md", "REPORT.md", "context.json", "run-brief.json"}:
            parent = artifact_path.parent
            explicit_dirs.append(parent.parent.parent if parent.parent.name == "archive" else parent)
    descriptor = seed.target_descriptor or {}
    slugs: list[str] = []
    for slug in (seed.args.slug, descriptor.get("slug")):
        if slug and str(slug) not in slugs:
            slugs.append(str(slug))
    if seed.plan_dir:
        explicit_dirs.append(Path(seed.plan_dir))
        plan_slug = Path(seed.plan_dir).name
        if plan_slug and plan_slug not in slugs:
            slugs.append(plan_slug)
    selected_sources = _selected_repo_sources(seed)
    for discovered in seed.discovered_plan_dirs:
        discovered_path = Path(discovered).expanduser()
        if not selected_sources or any(_path_within_repo_source(discovered_path, source) for source in selected_sources):
            dirs.append(discovered_path)
    for path in explicit_dirs:
        dirs.append(path)
    for source in selected_sources:
        for slug in slugs:
            plan_dir = _plan_dir_for_repo_source(slug, seed, source, None)
            if plan_dir is not None:
                dirs.append(plan_dir)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in dirs:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _git_log_text(data: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("subject", "message", "body", "summary", "query", "title"):
        value = data.get(key)
        if value:
            parts.append(str(value))
    entries = data.get("entries") or []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping):
                parts.extend(str(entry.get(key) or "") for key in ("subject", "message", "body", "summary", "title"))
            else:
                raw = str(entry)
                _commit, sep, subject = raw.partition("\t")
                parts.append(subject if sep else raw)
    return " ".join(part for part in parts if part)


def _candidate_git_aliases(candidate: Candidate) -> list[str]:
    aliases: list[str] = []
    for value in (
        candidate.slug,
        candidate.slug.replace("-", " ") if candidate.slug else "",
        candidate.summary,
        candidate.branch,
        Path(candidate.worktree_path).name if candidate.worktree_path else "",
        Path(candidate.repo_root).name if candidate.repo_root else "",
    ):
        text = str(value or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def _lookup_git_log_subject_key(by_key: Mapping[str, Candidate], data: Mapping[str, Any]) -> str | None:
    haystack = f" {' '.join(_tokenize(_git_log_text(data)))} "
    if not haystack.strip():
        return None
    matches: list[str] = []
    record_repo_id = str(data.get("repo_id") or "")
    record_repo_root = _safe_resolve(data.get("repo_root"))
    for key, candidate in by_key.items():
        repo_id_matches = bool(record_repo_id and candidate.repo_id and record_repo_id == candidate.repo_id)
        if record_repo_id and candidate.repo_id and not repo_id_matches:
            continue
        if not repo_id_matches and record_repo_root and candidate.repo_root and _safe_resolve(candidate.repo_root) not in {record_repo_root, None}:
            continue
        for alias in _candidate_git_aliases(candidate):
            alias_tokens = _tokenize(alias)
            if len(alias_tokens) < 2:
                continue
            if f" {' '.join(alias_tokens)} " in haystack:
                matches.append(key)
                break
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None




def _record_values(records: Sequence[EvidenceRecord], candidate: Candidate, key: str) -> list[str]:
    values: list[str] = []
    candidate_value = getattr(candidate, key, None)
    if candidate_value:
        values.append(str(candidate_value))
    for record in records:
        data = record.data if isinstance(record.data, dict) else {}
        value = data.get(key)
        if value:
            values.append(str(value))
        if key == "worktree_path" and record.evidence_type in {"worktree", "active_registry"}:
            alt = data.get("path")
            if alt:
                values.append(str(alt))
        if key == "head":
            alt = data.get("capture_head")
            if alt:
                values.append(str(alt))
    return list(dict.fromkeys(value for value in values if value))


def _heads_conflict(heads: Sequence[str]) -> bool:
    normalized = [head.strip() for head in heads if head and head.strip()]
    if len(normalized) <= 1:
        return False
    for left in normalized:
        for right in normalized:
            if left == right or left.startswith(right) or right.startswith(left):
                continue
            return True
    return False

def _component_total(components: Mapping[str, Any]) -> int:
    total = 0
    for value in components.values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _negative_total(negative_evidence: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for item in negative_evidence:
        try:
            total += int(item.get("penalty", 0))
        except (TypeError, ValueError):
            continue
    return total


def _ensure_score_components(candidate: Candidate) -> None:
    if not candidate.score_components and candidate.score:
        candidate.score_components["initial_candidate_score"] = int(candidate.score)


def _add_score_component(candidate: Candidate, key: str, value: int) -> None:
    amount = int(value)
    if amount == 0:
        candidate.score_components.setdefault(key, 0)
        return
    candidate.score_components[key] = int(candidate.score_components.get(key, 0)) + amount
    candidate.score += amount


def _merge_score_components(target: Candidate, source: Candidate) -> None:
    for key, value in source.score_components.items():
        _add_score_component(target, key, int(value))


def _add_negative_evidence(candidate: Candidate, evidence: Mapping[str, Any]) -> None:
    payload = dict(evidence)
    try:
        penalty = int(payload.get("penalty", 0))
    except (TypeError, ValueError):
        penalty = 0
    payload["penalty"] = penalty
    candidate.negative_evidence.append(payload)
    candidate.score += penalty


def _sync_candidate_score(candidate: Candidate) -> None:
    candidate.score = _component_total(candidate.score_components) + _negative_total(candidate.negative_evidence)




def _add_candidate_warning(candidate: Candidate, reason: str, *, penalty: int = -15) -> None:
    if reason not in candidate.ambiguity_warnings:
        candidate.ambiguity_warnings.append(reason)
    flags = candidate.current_state.setdefault("flags", {})
    flags["conflicting_current_state"] = True
    flags["conflicting_evidence"] = True
    if not any(item.get("reason") == reason for item in candidate.negative_evidence):
        _add_negative_evidence(candidate, {"reason": reason, "penalty": penalty})


def _detect_candidate_conflicts(candidate: Candidate, records: Sequence[EvidenceRecord]) -> None:
    associated = [record for record in records if record.candidate_id == candidate.candidate_id or record.evidence_id in candidate.evidence_ids]
    branches = _record_values(associated, candidate, "branch")
    if len(branches) > 1:
        _add_candidate_warning(candidate, f"conflicting branch evidence: {', '.join(branches[:4])}")
    worktrees = list(dict.fromkeys(_safe_resolve(value) or value for value in _record_values(associated, candidate, "worktree_path")))
    if len(worktrees) > 1:
        _add_candidate_warning(candidate, f"conflicting worktree evidence: {', '.join(worktrees[:4])}")
    heads = _record_values(associated, candidate, "head")
    if _heads_conflict(heads):
        _add_candidate_warning(candidate, f"conflicting HEAD evidence: {', '.join(heads[:4])}")
    flags = candidate.current_state.get("flags", {}) if isinstance(candidate.current_state, dict) else {}
    if flags.get("active_registry") and flags.get("completed_tasks"):
        _add_candidate_warning(candidate, "completed TASKS conflict with active registry evidence")
    if flags.get("active_registry") and flags.get("landed_git"):
        _add_candidate_warning(candidate, "landed git evidence conflicts with active registry evidence")


def _parse_run_timestamp(run_id: str | None) -> datetime | None:
    if not run_id:
        return None
    match = re.match(r"^(\d{8})T(\d{6})Z", run_id)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _apply_recency_decay(candidate: Candidate, records: Sequence[EvidenceRecord], seed: ContextSeed | None) -> None:
    if "recency_decay" in candidate.score_components:
        return
    run_ids = [candidate.run_id]
    for record in records:
        if record.candidate_id != candidate.candidate_id and record.evidence_id not in candidate.evidence_ids:
            continue
        data = record.data if isinstance(record.data, dict) else {}
        run_ids.append(str(data.get("run_id") or "") or None)
    timestamp = next((parsed for parsed in (_parse_run_timestamp(run_id) for run_id in run_ids) if parsed is not None), None)
    if timestamp is None or seed is None:
        candidate.score_components.setdefault("recency_decay", 0)
        return
    try:
        generated_at = _parse_utc(seed.generated_at)
    except ValueError:
        candidate.score_components.setdefault("recency_decay", 0)
        return
    age_days = max(0, (generated_at - timestamp).days)
    lookback = max(1, int(getattr(seed.args, "lookback_days", 14) or 14))
    if age_days <= lookback:
        component = max(1, 10 - int((age_days / lookback) * 9))
    else:
        component = -min(15, 1 + ((age_days - lookback) // lookback))
        has_canonical_decision = "decisions_available" in candidate.score_components
        if has_canonical_decision:
            component = max(component, -3)
    if component >= 0:
        _add_score_component(candidate, "recency_decay", int(component))
    else:
        candidate.score_components.setdefault("recency_decay", 0)
        reason = "recency_decay_capped_for_canonical_decisions" if component >= -3 and "decisions_available" in candidate.score_components else "recency_decay"
        _add_negative_evidence(candidate, {"reason": reason, "penalty": int(component), "age_days": age_days})


def _merge_candidates(candidates: list[Candidate], records: list[EvidenceRecord], seed: ContextSeed | None = None) -> list[Candidate]:
    by_key: dict[str, Candidate] = {}
    slug_to_keys: dict[str, list[str]] = {}
    for candidate in candidates:
        _ensure_score_components(candidate)
        key = candidate.plan_dir or f"{candidate.repo_id or ''}:{candidate.slug}" or candidate.candidate_id
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            existing = candidate
        else:
            _merge_score_components(existing, candidate)
            for negative in candidate.negative_evidence:
                _add_negative_evidence(existing, negative)
            existing.evidence_ids.extend(x for x in candidate.evidence_ids if x not in existing.evidence_ids)
            existing.citation_ids.extend(x for x in candidate.citation_ids if x not in existing.citation_ids)
        if candidate.run_id and not existing.run_id:
            existing.run_id = candidate.run_id
            existing.selection_token = _selection_token(existing.candidate_id, slug=existing.slug, repo_id=existing.repo_id, plan_dir=existing.plan_dir, run_id=existing.run_id)
        if candidate.repo_root and not existing.repo_root:
            existing.repo_root = candidate.repo_root
        for attr in ("branch", "worktree_path", "head"):
            value = getattr(candidate, attr)
            if value and not getattr(existing, attr):
                setattr(existing, attr, value)
        existing_flags = existing.current_state.setdefault("flags", {})
        candidate_flags = candidate.current_state.get("flags", {}) if isinstance(candidate.current_state, dict) else {}
        for flag, value in candidate_flags.items():
            existing_flags[flag] = bool(existing_flags.get(flag)) or bool(value)
        candidate_primary = candidate.current_state.get("primary") if isinstance(candidate.current_state, dict) else None
        if candidate_primary in {"active", "landed", "dirty", "divergent", "superseded"}:
            existing.current_state["primary"] = candidate_primary
        slug_to_keys.setdefault(candidate.slug, [])
        if key not in slug_to_keys[candidate.slug]:
            slug_to_keys[candidate.slug].append(key)

    if not by_key:
        for record in records:
            if record.candidate_id and record.source:
                slug = Path(record.source).parent.name if Path(record.source).name in {"TASKS.md", "SESSION.md", "SESSION_CONTEXT.md", "handoff.json"} else Path(record.source).name
                key = record.candidate_id
                by_key[key] = Candidate(
                    candidate_id=record.candidate_id,
                    slug=slug,
                    repo_root=None,
                    plan_dir=str(Path(record.source).parent),
                    score=0,
                    current_state=_state_from_status("unknown", active=False, degraded=False, archived_only=False),
                    selection_token=_selection_token(record.candidate_id, slug=slug, plan_dir=str(Path(record.source).parent)),
                )
                slug_to_keys.setdefault(slug, []).append(key)

    plan_dir_to_key: dict[str, str] = {}
    id_to_key: dict[str, str] = {}
    run_id_to_key: dict[str, str] = {}
    branch_to_key: dict[str, str] = {}
    worktree_to_key: dict[str, str] = {}
    repo_root_to_key: dict[str, str] = {}
    head_to_key: dict[str, str] = {}
    repo_slug_to_key: dict[str, str] = {}

    def add_unique(index: dict[str, str], value: Any, key: str) -> None:
        text = str(value or "")
        if not text:
            return
        existing = index.get(text)
        index[text] = key if existing in (None, key) else ""

    def has_repo_root_identity(candidate: Candidate) -> bool:
        return bool(candidate.repo_root) and candidate.status != "worktree"

    for key, candidate in by_key.items():
        id_to_key[candidate.candidate_id] = key
        add_unique(plan_dir_to_key, candidate.plan_dir, key)
        add_unique(run_id_to_key, candidate.run_id, key)
        add_unique(branch_to_key, candidate.branch, key)
        add_unique(worktree_to_key, candidate.worktree_path, key)
        if has_repo_root_identity(candidate):
            add_unique(repo_root_to_key, candidate.repo_root, key)
        add_unique(head_to_key, candidate.head, key)
        if candidate.repo_id and candidate.slug:
            add_unique(repo_slug_to_key, f"{candidate.repo_id}:{candidate.slug}", key)

    def lookup_unique(index: dict[str, str], value: Any) -> str | None:
        key = index.get(str(value or ""))
        return key or None

    def record_repo_id(data: Mapping[str, Any]) -> str:
        if data.get("repo_id"):
            return str(data.get("repo_id"))
        repo_source = data.get("repo_source")
        if isinstance(repo_source, Mapping) and repo_source.get("repo_id"):
            return str(repo_source.get("repo_id"))
        return ""

    def repo_compatible(candidate_key: str, data: Mapping[str, Any]) -> bool:
        record_repo = record_repo_id(data)
        candidate_repo = str(by_key[candidate_key].repo_id or "")
        return not record_repo or not candidate_repo or record_repo == candidate_repo

    def lookup_worktree_record(data: Mapping[str, Any], evidence_type: str) -> str | None:
        if evidence_type not in {"worktree", "active_registry"}:
            return None
        return lookup_unique(worktree_to_key, data.get("worktree_path") or data.get("path"))

    def lookup_repo_root_record(data: Mapping[str, Any]) -> str | None:
        candidate_key = lookup_unique(repo_root_to_key, data.get("repo_root"))
        if candidate_key is None:
            return None
        record_repo = record_repo_id(data)
        candidate_repo = str(by_key[candidate_key].repo_id or "")
        if not record_repo or not candidate_repo or record_repo != candidate_repo:
            return None
        return candidate_key


    for record in records:
        key = id_to_key.get(record.candidate_id or "")
        data = record.data if isinstance(record.data, dict) else {}
        if key is None:
            key = lookup_unique(plan_dir_to_key, data.get("plan_dir") or data.get("plan_path"))
        if key is None and record.source:
            for plan_dir, candidate_key in plan_dir_to_key.items():
                if plan_dir and record.source.startswith(plan_dir):
                    key = candidate_key
                    break
        if key is None:
            key = lookup_unique(run_id_to_key, data.get("run_id"))
        if key is None:
            key = lookup_worktree_record(data, record.evidence_type)
        if key is None:
            key = lookup_repo_root_record(data)
        if key is None:
            branch_key = lookup_unique(branch_to_key, data.get("branch"))
            key = branch_key if branch_key and repo_compatible(branch_key, data) else None
        if key is None:
            head_key = lookup_unique(head_to_key, data.get("head") or data.get("capture_head"))
            key = head_key if head_key and repo_compatible(head_key, data) else None
        if key is None and data.get("repo_id") and (data.get("slug") or data.get("plan_slug") or data.get("associated_slug")):
            key = lookup_unique(repo_slug_to_key, f"{data.get('repo_id')}:{data.get('slug') or data.get('plan_slug') or data.get('associated_slug')}")
        if key is None and record.evidence_type == "git_log":
            key = _lookup_git_log_subject_key(by_key, data)
        if key is None and record.candidate_id:
            raw_slug = str(data.get("slug") or data.get("plan_slug") or data.get("associated_slug") or Path(record.source).parent.name)
            keys = slug_to_keys.get(raw_slug) or []
            if len(keys) == 1:
                key = keys[0]
        if key is None:
            continue
        candidate = by_key[key]
        if record.candidate_id is None:
            record.candidate_id = candidate.candidate_id
        if record.evidence_id not in candidate.evidence_ids:
            candidate.evidence_ids.append(record.evidence_id)
        if record.citation_id and record.citation_id not in candidate.citation_ids:
            candidate.citation_ids.append(record.citation_id)
        record_run_id = str(data.get("run_id") or "")
        if record_run_id and not candidate.run_id:
            candidate.run_id = record_run_id
            candidate.selection_token = _selection_token(candidate.candidate_id, slug=candidate.slug, repo_id=candidate.repo_id, plan_dir=candidate.plan_dir, run_id=candidate.run_id)
        record_recency = _explicit_recency_value(data)
        if record_recency is not None and candidate.recency_evidence in (None, ""):
            candidate.recency_evidence = record_recency
        _apply_record_to_candidate(candidate, record)
    for keys in slug_to_keys.values():
        if len(keys) > 1:
            for key in sorted(keys, key=lambda k: by_key[k].score, reverse=True)[1:]:
                flags = by_key[key].current_state.setdefault("flags", {})
                flags["superseded"] = True
                flags["superseded_by_newer_run"] = True
                if by_key[key].current_state.get("primary") in {"unknown", "paused", "archived_only"}:
                    by_key[key].current_state["primary"] = "superseded"
    for candidate in by_key.values():
        _detect_candidate_conflicts(candidate, records)
        _apply_recency_decay(candidate, records, seed)
        _reduce_primary_state(candidate)
        _sync_candidate_score(candidate)
    return sorted(by_key.values(), key=lambda c: (-c.score, c.slug, c.plan_dir or ""))


def _reduce_primary_state(candidate: Candidate) -> None:
    flags = candidate.current_state.get("flags", {}) if isinstance(candidate.current_state, dict) else {}
    primary = candidate.current_state.get("primary") if isinstance(candidate.current_state, dict) else "unknown"
    if primary == "active":
        return
    if flags.get("dirty_worktree") or flags.get("dirty"):
        candidate.current_state["primary"] = "dirty"
    elif flags.get("divergent_branch") or flags.get("divergent"):
        candidate.current_state["primary"] = "divergent"
    elif flags.get("landed_git") or flags.get("landed"):
        candidate.current_state["primary"] = "landed"


def _apply_record_to_candidate(candidate: Candidate, record: EvidenceRecord) -> None:
    candidate.source_status[record.provider] = record.validation_status
    if record.truncated:
        warning = f"{record.provider}:{record.evidence_type} truncated"
        if warning not in candidate.source_warnings:
            candidate.source_warnings.append(warning)
    if record.degraded:
        warning = f"{record.provider}:{record.evidence_type} degraded"
        if warning not in candidate.source_warnings:
            candidate.source_warnings.append(warning)
    data = record.data if isinstance(record.data, dict) else {}
    for warning in data.get("warnings") or []:
        text = f"{record.provider}:{record.evidence_type}: {warning}"
        if text not in candidate.source_warnings:
            candidate.source_warnings.append(text)
    git_state = data.get("git_state") if isinstance(data, dict) else None
    if isinstance(git_state, dict):
        for warning in git_state.get("warnings") or []:
            text = f"{record.provider}:{record.evidence_type}: {warning}"
            if text not in candidate.source_warnings:
                candidate.source_warnings.append(text)
    if record.validation_status in {"conflict", "stale"}:
        candidate.current_state.setdefault("flags", {}).update({"stale": True, "stale_session": record.evidence_type == "session", "stale_handoff": record.evidence_type == "handoff", "conflicting_current_state": True, "conflicting_evidence": True})
        _add_negative_evidence(candidate, {"evidence_id": record.evidence_id, "reason": record.validation_status, "penalty": -30})
    if record.degraded or record.validation_status in {"malformed", "degraded", "truncated"}:
        candidate.current_state.setdefault("flags", {}).update({"degraded": True, "degraded_sources": True})
        _add_negative_evidence(candidate, {"evidence_id": record.evidence_id, "reason": "degraded_evidence", "penalty": -10})
    if record.evidence_type == "tasks" and record.validation_status == "valid":
        counts = record.data.get("status_counts") or {}
        flags = candidate.current_state.setdefault("flags", {})
        completed = counts.get("pending", 0) == 0 and counts.get("in_progress", 0) == 0 and sum(int(v) for v in counts.values()) > 0
        if completed:
            flags["completed_tasks"] = True
            _add_score_component(candidate, "tasks_completed", 30)
            if candidate.current_state.get("primary") not in {"active", "dirty", "divergent", "landed"}:
                candidate.current_state["primary"] = "completed"
        else:
            _add_score_component(candidate, "tasks_present", 20)
            if candidate.current_state.get("primary") not in {"active", "dirty", "divergent", "landed", "completed"}:
                candidate.current_state["primary"] = "paused"
    if record.evidence_type in {"decisions", "context_json", "run_brief", "report"} and record.validation_status in {"valid", "truncated"}:
        component = f"{record.evidence_type}_available"
        if component not in candidate.score_components:
            _add_score_component(candidate, component, 10)
    if record.evidence_type == "session" and record.validation_status == "valid":
        _add_score_component(candidate, "session_valid", 15)
    if record.evidence_type == "handoff" and record.validation_status == "valid":
        _add_score_component(candidate, "handoff_valid", 10)
    if record.evidence_type == "active_registry":
        candidate.current_state["primary"] = "active"
        candidate.current_state.setdefault("flags", {})["active_registry"] = True
        _add_score_component(candidate, "active_registry", 40)
    if record.evidence_type == "worktree":
        git_state = record.data.get("git_state") or {}
        flags = candidate.current_state.setdefault("flags", {})
        for flag in ("dirty", "divergent", "landed"):
            if git_state.get(flag):
                flags[flag] = True
        if git_state.get("dirty"):
            flags["dirty_worktree"] = True
            if candidate.current_state.get("primary") != "active":
                candidate.current_state["primary"] = "dirty"
        if git_state.get("divergent"):
            flags["divergent_branch"] = True
            if candidate.current_state.get("primary") not in {"active", "dirty"}:
                candidate.current_state["primary"] = "divergent"
        if git_state.get("landed") and candidate.current_state.get("primary") not in {"active", "dirty", "divergent"}:
            flags["landed_git"] = True
            candidate.current_state["primary"] = "landed"
    if record.superseded or record.validation_status == "superseded":
        flags = candidate.current_state.setdefault("flags", {})
        flags["superseded"] = True
        flags["superseded_by_newer_run"] = True
        if candidate.current_state.get("primary") in {"unknown", "paused", "archived_only"}:
            candidate.current_state["primary"] = "superseded"
    if record.evidence_type == "known_artifacts" and record.data.get("artifacts"):
        artifacts = [Path(str(p)).name for p in record.data.get("artifacts", [])]
        if "REPORT.md" in artifacts:
            _add_score_component(candidate, "report_available", 5)


def _taxonomy() -> dict[str, Any]:
    return {
        "primary_states": PRIMARY_STATE_PRECEDENCE,
        "flags": STATE_FLAGS,
        "precedence": PRIMARY_STATE_PRECEDENCE,
        "definitions": {
            "active": "active registry evidence indicates a live run/session for the candidate",
            "paused": "validated TASKS or artifacts indicate pending work without active registry proof",
            "blocked": "validated events or task state indicate blocked work",
            "completed": "TASKS.md or canonical artifact status indicates all known tasks completed",
            "landed": "git evidence proves merged/landed state; not inferred from memories/followups",
            "archived_only": "only archived or historical artifact evidence is present",
            "stale": "session or handoff evidence conflicts with current task state",
            "superseded": "newer canonical evidence supersedes this candidate",
            "dirty": "worktree evidence indicates uncommitted changes",
            "divergent": "branch/worktree evidence indicates divergence from expected base",
            "unknown": "insufficient validated current-state evidence",
        },
        "side_evidence_only": sorted(SIDE_EVIDENCE_TYPES),
    }


def _blocking_ambiguity_triggers(triggers: Sequence[str]) -> set[str]:
    return set(triggers).intersection({"explicit_collision", "explicit_unresolved", "low_confidence", "thin_evidence", "conflicting_current_state"})


def _ambiguity(candidates: list[Candidate], seed: ContextSeed) -> dict[str, Any]:
    if not candidates:
        return {"state": "no_candidates", "triggers": ["no_candidates"], "needs_selection": True}
    triggers: list[str] = []
    explicit = _has_exact_target(seed.args)
    exact_matches: list[Candidate] = []
    if seed.args.select:
        exact_matches = [c for c in candidates if c.selection_token == seed.args.select or f"candidate:{c.candidate_id}" == seed.args.select]
        if len(exact_matches) != 1:
            triggers.append("explicit_unresolved" if not exact_matches else "explicit_collision")
    elif explicit:
        exact_matches = _exact_matches(candidates, seed)
        if len(exact_matches) != 1:
            triggers.append("explicit_unresolved" if not exact_matches else "explicit_collision")
        if getattr(seed.args, "run_prefix_ambiguous", False) and "explicit_collision" not in triggers:
            triggers.append("explicit_collision")
    target = exact_matches[0] if len(exact_matches) == 1 else candidates[0]
    if target.score < 30 or target.confidence == "low":
        triggers.append("low_confidence")
    if len(target.evidence_ids) < 2:
        triggers.append("thin_evidence")
    if len(candidates) > 1 and candidates[0].score - candidates[1].score <= 15:
        triggers.append("close_scores")
    conflict_scope = [target] if len(exact_matches) == 1 else candidates[:3]
    if any(c.current_state.get("flags", {}).get("conflicting_current_state") for c in conflict_scope):
        triggers.append("conflicting_current_state")
    repo_ids = {c.repo_id for c in candidates[:3] if c.repo_id}
    if len(repo_ids) > 1:
        triggers.append("cross_repo_conflict")
    if explicit and len(exact_matches) == 1 and not _blocking_ambiguity_triggers(triggers):
        return {"state": "none", "triggers": [], "needs_selection": False}
    state = "none" if not triggers else ("needs_selection" if "close_scores" in triggers or "explicit_collision" in triggers else triggers[0])
    return {"state": state, "triggers": triggers, "needs_selection": bool(triggers)}


def _select_target(candidates: list[Candidate], seed: ContextSeed, ambiguity: Mapping[str, Any]) -> dict[str, Any] | None:
    token = seed.args.select
    if token:
        matches = [candidate for candidate in candidates if candidate.selection_token == token or f"candidate:{candidate.candidate_id}" == token]
        if len(matches) == 1 and not _blocking_ambiguity_triggers(ambiguity.get("triggers", [])):
            return _selected_from_candidate(matches[0], explicit=True)
        if len(matches) == 1:
            seed.warnings.append("selection token resolved but evidence remains too thin, low-confidence, or conflicting")
            return None
        seed.warnings.append(f"selection token {token!r} did not resolve to exactly one candidate")
        return None
    if _has_exact_target(seed.args):
        matches = _exact_matches(candidates, seed)
        if len(matches) == 1 and not ambiguity.get("needs_selection"):
            return _selected_from_candidate(matches[0], explicit=True)
        if len(matches) != 1:
            seed.warnings.append("explicit target did not resolve to exactly one candidate")
            return None
        seed.warnings.append("explicit target is still ambiguous; use a full selection_token")
        return None
    if not ambiguity.get("needs_selection") and candidates:
        return _selected_from_candidate(candidates[0], explicit=False)
    return None


def _selected_from_candidate(candidate: Candidate, *, explicit: bool) -> dict[str, Any]:
    return {
        "target_type": candidate.target_type,
        "selection_kind": "explicit" if explicit else "auto_unambiguous",
        "selection_token": candidate.selection_token,
        "slug": candidate.slug,
        "run_id": candidate.run_id,
        "repo_id": candidate.repo_id,
        "repo_root": candidate.repo_root,
        "plan_dir": candidate.plan_dir,
        "run_dir": candidate.run_dir,
        "branch": candidate.branch,
        "worktree_path": candidate.worktree_path,
        "head": candidate.head,
        "current_state": candidate.current_state,
        "confidence": candidate.confidence,
        "score": candidate.score,
        "evidence_ids": candidate.evidence_ids,
        "candidate_id": candidate.candidate_id,
        "citation_ids": candidate.citation_ids,
        "evidence_refs": candidate.evidence_ids,
        "citations": candidate.citation_ids,
        "score_components": candidate.score_components,
        "negative_evidence": candidate.negative_evidence,
        "source_status": candidate.source_status,
        "source_warnings": candidate.source_warnings,
        "ambiguity_warnings": candidate.ambiguity_warnings,
    }


def _selected_report_target_args(
    selected: Mapping[str, Any] | None,
    *,
    current_repo_root: str | Path | None = None,
    current_repo_id: str | None = None,
) -> tuple[list[str], str | None]:
    if not isinstance(selected, Mapping):
        return [], None
    run_id = str(selected.get("run_id") or "").strip()
    slug = str(selected.get("slug") or "").strip()
    worktree_path = str(selected.get("worktree_path") or "").strip()
    repo_root = str(selected.get("repo_root") or "").strip()
    repo_id = str(selected.get("repo_id") or "").strip()
    if repo_root and current_repo_root:
        same_current_repo = _same_path(repo_root, current_repo_root)
    elif repo_id and current_repo_id:
        same_current_repo = repo_id == current_repo_id
    else:
        same_current_repo = not repo_root and not repo_id
    if worktree_path:
        return ["--worktree", worktree_path], "worktree"
    if run_id and same_current_repo:
        return ["--run", run_id], "run"
    if slug and same_current_repo:
        return ["--slug", slug], "slug"
    return [], None


def _report_target(selected: Mapping[str, Any] | None, args: argparse.Namespace, ambiguity: Mapping[str, Any], current_repo_id: str | None = None) -> dict[str, Any]:
    requested = args.report is not None
    payload: dict[str, Any] = {
        "requested": requested,
        "tier": args.report,
        "forwarded_args": list(args.unknown_arguments),
    }
    if not requested:
        payload["status"] = "not_requested"
        return payload
    if ambiguity.get("needs_selection") or not isinstance(selected, Mapping):
        payload.update(
            {
                "status": "needs_selection",
                "target_args": [],
                "reason": "selection_required_before_report_rendering",
            }
        )
        return payload
    target_args, mode = _selected_report_target_args(selected, current_repo_root=getattr(args, "repo_root", None), current_repo_id=current_repo_id)
    if not target_args:
        payload.update(
            {
                "status": "not_reportable",
                "target_args": [],
                "reason": "selected_target_has_no_report_context_route",
            }
        )
        return payload
    payload.update(
        {
            "status": "ready",
            "mode": mode,
            "target_args": target_args,
            "resume_context_arg": "--resume-context <selected-packet.json>",
            "selected_candidate_id": selected.get("candidate_id"),
        }
    )
    return payload

def _prepare_report_handoff(
    packet: Mapping[str, Any],
    selected_packet_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Persist a selected packet and return the read-only /z-report handoff contract."""
    ambiguity = packet.get("ambiguity") if isinstance(packet.get("ambiguity"), Mapping) else {}
    selected = packet.get("selected_target") if isinstance(packet.get("selected_target"), Mapping) else None
    report_target = packet.get("report_target") if isinstance(packet.get("report_target"), Mapping) else {}
    if packet.get("status") != "selected" or ambiguity.get("needs_selection") or selected is None:
        return {
            "status": "needs_selection",
            "reason": "selection_required_before_report_rendering",
            "should_render": False,
        }
    if report_target.get("status") != "ready" or not report_target.get("target_args"):
        return {
            "status": report_target.get("status") or "not_reportable",
            "reason": report_target.get("reason") or "selected_target_has_no_report_context_route",
            "should_render": False,
        }

    path = Path(selected_packet_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)

    handoff_env = dict(environ or {})
    handoff_env["SELECTED_RESUME_CONTEXT_PATH"] = str(path)
    target_args = [str(item) for item in report_target.get("target_args") or []]
    forwarded_args = [str(item) for item in report_target.get("forwarded_args") or []]
    requested_report = packet.get("requested_report") if isinstance(packet.get("requested_report"), Mapping) else {}
    tier = str(report_target.get("tier") or requested_report.get("tier") or "standard")
    return {
        "status": "ready",
        "should_render": True,
        "selected_packet_path": str(path),
        "environment": handoff_env,
        "z_report_args": target_args + [tier] + forwarded_args,
        "report_context_args": target_args + ["--resume-context", str(path)],
        "render_source": "context.json:selected_resume_context",
    }


def _continuations(selected: dict[str, Any] | None, candidates: list[Candidate], ambiguity: Mapping[str, Any]) -> list[dict[str, Any]]:
    continuations: list[dict[str, Any]] = []
    if selected is None:
        for candidate in candidates[:3]:
            continuations.append(
                {
                    "kind": "select_target",
                    "label": f"Select {candidate.slug}",
                    "command": _select_command(candidate.selection_token),
                    "selection_token": candidate.selection_token,
                    "reason": "ambiguity requires explicit selection before narrative/report rendering",
                    "citation_ids": candidate.citation_ids[:3],
                }
            )
        if not continuations:
            continuations.append(
                {
                    "kind": "refine_query",
                    "label": "Refine the resume topic",
                    "prompt": "Provide a slug, run id, branch, or more specific work-thread phrase.",
                    "reason": ambiguity.get("state", "no_candidates"),
                    "citation_ids": [],
                }
            )
        return continuations
    slug = selected.get("slug")
    state = (selected.get("current_state") or {}).get("primary", "unknown")
    if slug and state in {"active", "paused", "blocked", "in_progress"}:
        continuations.append(
            {
                "kind": "continue_plan",
                "label": "Continue the selected plan",
                "command": f"/z-execute {slug}",
                "reason": f"selected target state is {state}",
                "citation_ids": selected.get("citation_ids", [])[:3],
            }
        )
    if slug:
        continuations.append(
            {
                "kind": "report_selected",
                "label": "Render a report for the selected target",
                "command": f"/z-resume --slug {slug} --report",
                "reason": "report rendering is allowed only after target selection",
                "citation_ids": selected.get("citation_ids", [])[:3],
            }
        )
    return continuations


def _suggested_selection_args(selected: dict[str, Any] | None, candidates: list[Candidate], ambiguity: Mapping[str, Any]) -> list[str]:
    if selected is not None or not ambiguity.get("needs_selection"):
        return []
    suggestions: list[str] = []
    for candidate in candidates[:3]:
        suggestions.append(f"--select {shlex.quote(candidate.selection_token)}")
        if candidate.run_id:
            suggestions.append(f"--run {shlex.quote(str(candidate.run_id))}")
        elif candidate.slug:
            suggestions.append(f"--slug {shlex.quote(str(candidate.slug))}")
    return list(dict.fromkeys(suggestions))

def _branch_worktree_state(selected: Mapping[str, Any] | None) -> str:
    if not selected:
        return "none"
    flags = ((selected.get("current_state") or {}).get("flags") or {}) if isinstance(selected.get("current_state"), dict) else {}
    if flags.get("dirty_worktree") or flags.get("dirty"):
        return "dirty"
    if flags.get("divergent_branch") or flags.get("divergent"):
        return "divergent"
    if flags.get("landed_git") or flags.get("landed"):
        return "landed"
    if selected.get("branch") or selected.get("worktree_path") or selected.get("head"):
        return "associated_clean_or_unknown"
    return "none"


def _safe_next_command(selected: dict[str, Any] | None, candidates: list[Candidate], ambiguity: Mapping[str, Any]) -> dict[str, Any]:
    top = candidates[0] if candidates else None
    if selected is None:
        if top is None:
            return {
                "kind": "refine_query",
                "command": None,
                "allowed": True,
                "reason": "no bounded resume candidates were found",
                "matrix_key": {
                    "selected_target_type": "none",
                    "confidence": "none",
                    "ambiguity": ambiguity.get("state", "no_candidates"),
                    "completion": "unknown",
                    "registry_state": "none",
                    "branch_worktree_state": "none",
                    "report_available": False,
                    "known_resume_form": "query_or_exact_flags",
                },
            }
        return {
            "kind": "select_target",
            "command": _select_command(top.selection_token),
            "allowed": True,
            "reason": "selection is required before executing or rendering a report",
            "selection_token": top.selection_token,
            "matrix_key": {
                "selected_target_type": "candidate",
                "confidence": top.confidence,
                "ambiguity": ambiguity.get("state", "needs_selection"),
                "completion": top.current_state.get("primary", "unknown") if isinstance(top.current_state, dict) else "unknown",
                "registry_state": "active" if top.current_state.get("flags", {}).get("active_registry") else "none",
                "branch_worktree_state": _branch_worktree_state(_selected_from_candidate(top, explicit=False)),
                "report_available": "report_available" in top.score_components or "report_available" in top.current_state.get("flags", {}),
                "known_resume_form": "selection_token",
            },
        }
    state = (selected.get("current_state") or {}).get("primary", "unknown")
    flags = (selected.get("current_state") or {}).get("flags", {}) if isinstance(selected.get("current_state"), dict) else {}
    confidence = str(selected.get("confidence") or "low")
    report_available = "report_available" in (selected.get("score_components") or {})
    branch_state = _branch_worktree_state(selected)
    matrix_key = {
        "selected_target_type": selected.get("target_type") or "unknown",
        "confidence": confidence,
        "ambiguity": ambiguity.get("state", "none"),
        "completion": "complete" if flags.get("completed_tasks") or state in {"completed", "landed"} else "incomplete_or_unknown",
        "registry_state": "active" if flags.get("active_registry") else "none",
        "branch_worktree_state": branch_state,
        "report_available": bool(report_available),
        "known_resume_form": "run" if selected.get("run_id") else ("slug" if selected.get("slug") else "selection_token"),
    }
    token = selected.get("selection_token")
    slug = selected.get("slug")
    run_id = selected.get("run_id")
    if ambiguity.get("needs_selection") or confidence == "low" or flags.get("conflicting_current_state"):
        return {
            "kind": "select_target",
            "command": _select_command(str(token)) if token else None,
            "allowed": bool(token),
            "reason": "target evidence is ambiguous, low-confidence, or conflicting",
            "selection_token": token,
            "matrix_key": matrix_key,
        }
    if branch_state in {"dirty", "divergent"}:
        return {
            "kind": "inspect_worktree",
            "command": _select_command(str(token)) if token else None,
            "allowed": bool(token),
            "reason": f"worktree/branch state is {branch_state}; reselect before continuing",
            "selection_token": token,
            "matrix_key": matrix_key,
        }
    if state in {"active", "paused", "blocked", "in_progress"} and slug:
        return {
            "kind": "continue_plan",
            "command": _shell_command("/z-execute", str(slug)),
            "allowed": True,
            "reason": f"selected target is {state} with non-conflicting evidence",
            "selection_token": token,
            "matrix_key": matrix_key,
        }
    if run_id:
        return {
            "kind": "report_selected_run",
            "command": _shell_command("/z-resume", "--run", str(run_id), "--report"),
            "allowed": True,
            "reason": "selected target is a known run; report rendering is the safe resume form",
            "selection_token": token,
            "matrix_key": matrix_key,
        }
    return {
        "kind": "report_selected",
        "command": _shell_command("/z-resume", "--slug", str(slug), "--report") if slug else (_select_command(str(token)) if token else None),
        "allowed": bool(slug or token),
        "reason": "selected target is completed, landed, or not executable; report rendering is safe",
        "selection_token": token,
        "matrix_key": matrix_key,
    }


def _ranking(candidates: list[Candidate], ambiguity: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rank": idx,
            "candidate_id": candidate.candidate_id,
            "selection_token": candidate.selection_token,
            "slug": candidate.slug,
            "target_type": candidate.target_type,
            "score": candidate.score,
            "confidence": candidate.confidence,
            "score_components": candidate.score_components,
            "recency_decay": candidate.score_components.get("recency_decay", 0),
            "negative_evidence": candidate.negative_evidence,
            "source_status": candidate.source_status,
            "source_warnings": candidate.source_warnings,
            "truncation_warnings": [warning for warning in candidate.source_warnings if "truncated" in warning],
            "ambiguity_state": ambiguity.get("state", "none"),
            "ambiguity_triggers": list(ambiguity.get("triggers", [])),
            "ambiguity_warnings": candidate.ambiguity_warnings,
        }
        for idx, candidate in enumerate(candidates, start=1)
    ]


def _compact_for_subagent(value: Any, *, max_string: int = 700, max_mapping_items: int = 24) -> Any:
    if isinstance(value, Mapping):
        compact: dict[str, Any] = {}
        emitted = 0
        skipped = 0
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            if emitted >= max_mapping_items:
                skipped += 1
                continue
            compact[str(key)] = _compact_for_subagent(
                item,
                max_string=max_string,
                max_mapping_items=max_mapping_items,
            )
            emitted += 1
        if skipped:
            compact["_truncated_keys_count"] = skipped
        return compact
    if isinstance(value, list):
        return [_compact_for_subagent(item, max_string=max_string, max_mapping_items=max_mapping_items) for item in value[:20]]
    if isinstance(value, tuple):
        return [_compact_for_subagent(item, max_string=max_string, max_mapping_items=max_mapping_items) for item in value[:20]]
    if isinstance(value, str):
        clean = value.strip()
        if len(clean) > max_string:
            return clean[: max_string - 24] + "…[truncated-for-subagent]"
        return clean
    return _json_safe(value)


def _candidate_inference_view(candidate: Candidate) -> dict[str, Any]:
    state = candidate.current_state if isinstance(candidate.current_state, Mapping) else {}
    flags = state.get("flags", {}) if isinstance(state, Mapping) else {}
    return _compact_for_subagent(
        {
            "candidate_id": candidate.candidate_id,
            "selection_token": candidate.selection_token,
            "target_type": candidate.target_type,
            "slug": candidate.slug,
            "run_id": candidate.run_id,
            "repo_id": candidate.repo_id,
            "branch": candidate.branch,
            "worktree_path": candidate.worktree_path,
            "score": candidate.score,
            "confidence": candidate.confidence,
            "primary_state": state.get("primary", "unknown"),
            "state_flags": sorted(k for k, v in flags.items() if v),
            "score_components": candidate.score_components,
            "negative_evidence": candidate.negative_evidence,
            "source_warnings": candidate.source_warnings,
            "ambiguity_warnings": candidate.ambiguity_warnings,
            "evidence_refs": candidate.evidence_ids,
            "citations": candidate.citation_ids,
            "summary": candidate.summary,
        }
    )


def _evidence_inference_view(record: EvidenceRecord) -> dict[str, Any]:
    return _compact_for_subagent(
        {
            "evidence_id": record.evidence_id,
            "type": record.evidence_type,
            "provider": record.provider,
            "status": record.status,
            "validation_status": record.validation_status,
            "freshness": "stale" if record.stale else ("superseded" if record.superseded else "current_or_unknown"),
            "candidate_id": record.candidate_id,
            "citation": record.citation_id,
            "side_evidence": record.side_evidence or record.evidence_type in SIDE_EVIDENCE_TYPES,
            "degraded": record.degraded,
            "truncated": record.truncated,
            "data": record.data,
        }
    )


def _records_for_subagent(records: Sequence[EvidenceRecord], candidate_ids: set[str], evidence_ids: set[str]) -> list[EvidenceRecord]:
    selected: list[EvidenceRecord] = []
    for record in records:
        if record.candidate_id in candidate_ids or record.evidence_id in evidence_ids:
            selected.append(record)
        if len(selected) >= MAX_SUBAGENT_EVIDENCE_RECORDS:
            break
    return selected


def _citation_metadata_for_subagent(citations: Sequence[Citation], citation_ids: set[str]) -> list[dict[str, Any]]:
    return [
        _compact_for_subagent(citation.as_dict())
        for citation in citations
        if citation.citation_id in citation_ids
    ]


def _subagent_body_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _subagent_prompt_fits(payload: Mapping[str, Any]) -> bool:
    return len(_SUBAGENT_PROMPT_PREFIX) + len(_subagent_body_text(payload)) <= MAX_SUBAGENT_PROMPT_CHARS


def _minimal_subagent_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_for_subagent(
        {
            "candidate_id": candidate.get("candidate_id"),
            "selection_token": candidate.get("selection_token"),
            "slug": candidate.get("slug"),
            "run_id": candidate.get("run_id"),
            "repo_id": candidate.get("repo_id"),
            "score": candidate.get("score"),
            "confidence": candidate.get("confidence"),
            "primary_state": candidate.get("primary_state"),
            "state_flags": candidate.get("state_flags"),
            "citations": candidate.get("citations"),
        },
        max_string=180,
        max_mapping_items=12,
    )


def _minimal_subagent_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_for_subagent(
        {
            "evidence_id": record.get("evidence_id"),
            "type": record.get("type"),
            "provider": record.get("provider"),
            "status": record.get("status"),
            "validation_status": record.get("validation_status"),
            "candidate_id": record.get("candidate_id"),
            "citation": record.get("citation"),
            "side_evidence": record.get("side_evidence"),
            "degraded": record.get("degraded"),
            "truncated": record.get("truncated"),
        },
        max_string=120,
        max_mapping_items=12,
    )


def _sync_subagent_payload_kind(payload: dict[str, Any]) -> None:
    candidates = [candidate for candidate in payload.get("candidates") or [] if isinstance(candidate, Mapping)]
    if len(candidates) <= 1:
        payload["request_kind"] = "single_candidate"
        ambiguity = payload.get("ambiguity") if isinstance(payload.get("ambiguity"), dict) else {}
        ambiguity["needs_selection"] = False
        payload["ambiguity"] = ambiguity
    elif payload.get("request_kind") != "top_cluster_comparison":
        payload["request_kind"] = "top_cluster_comparison"


def _bounded_subagent_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    bounded_payload = json.loads(json.dumps(payload))
    _sync_subagent_payload_kind(bounded_payload)
    if _subagent_prompt_fits(bounded_payload):
        return bounded_payload

    bounded_payload["prompt_truncated"] = True
    bounded_payload["evidence_records"] = list(bounded_payload.get("evidence_records") or [])[:6]
    bounded_payload["citation_metadata"] = list(bounded_payload.get("citation_metadata") or [])[:6]
    if _subagent_prompt_fits(bounded_payload):
        return bounded_payload

    bounded_payload["evidence_records"] = [
        _minimal_subagent_evidence(record)
        for record in bounded_payload.get("evidence_records") or []
        if isinstance(record, Mapping)
    ][:3]
    bounded_payload["citation_metadata"] = [
        _compact_for_subagent(citation, max_string=120, max_mapping_items=8)
        for citation in bounded_payload.get("citation_metadata") or []
        if isinstance(citation, Mapping)
    ][:3]
    if _subagent_prompt_fits(bounded_payload):
        return bounded_payload

    candidates = [candidate for candidate in bounded_payload.get("candidates") or [] if isinstance(candidate, Mapping)]
    if len(candidates) > 2:
        bounded_payload["candidates"] = candidates[:2]
        _sync_subagent_payload_kind(bounded_payload)
        if _subagent_prompt_fits(bounded_payload):
            return bounded_payload

    if len(candidates) > 1:
        bounded_payload["candidates"] = candidates[:1]
        bounded_payload["prompt_degraded_reason"] = "prompt_budget_reduced_to_single_candidate"
        _sync_subagent_payload_kind(bounded_payload)
        if _subagent_prompt_fits(bounded_payload):
            return bounded_payload

    bounded_payload["candidates"] = [
        _minimal_subagent_candidate(candidate)
        for candidate in bounded_payload.get("candidates") or []
        if isinstance(candidate, Mapping)
    ][:1]
    bounded_payload["evidence_records"] = []
    bounded_payload["citation_metadata"] = []
    bounded_payload["prompt_degraded_reason"] = bounded_payload.get("prompt_degraded_reason") or "prompt_budget_minimal_payload"
    _sync_subagent_payload_kind(bounded_payload)
    if _subagent_prompt_fits(bounded_payload):
        return bounded_payload

    candidate = bounded_payload["candidates"][0] if bounded_payload.get("candidates") else {}
    bounded_payload = {
        "schema": "resume-cluster-input.v1",
        "request_kind": "single_candidate",
        "agent": RESUME_CLUSTER_AGENT,
        "prompt_truncated": True,
        "prompt_degraded_reason": "prompt_budget_emergency_payload",
        "candidates": [
            _compact_for_subagent(
                {
                    "candidate_id": candidate.get("candidate_id") if isinstance(candidate, Mapping) else None,
                    "slug": candidate.get("slug") if isinstance(candidate, Mapping) else None,
                    "primary_state": candidate.get("primary_state") if isinstance(candidate, Mapping) else None,
                    "citations": candidate.get("citations") if isinstance(candidate, Mapping) else None,
                },
                max_string=80,
                max_mapping_items=6,
            )
        ],
        "evidence_records": [],
        "citation_metadata": [],
    }
    return bounded_payload


def _subagent_prompt_text(payload: Mapping[str, Any]) -> str:
    bounded_payload = _bounded_subagent_payload(payload)
    body = _subagent_body_text(bounded_payload)
    prompt = f"{_SUBAGENT_PROMPT_PREFIX}{body}"
    if len(prompt) <= MAX_SUBAGENT_PROMPT_CHARS:
        return prompt
    emergency_payload = {
        "schema": "resume-cluster-input.v1",
        "request_kind": "single_candidate",
        "agent": RESUME_CLUSTER_AGENT,
        "prompt_truncated": True,
        "prompt_degraded_reason": "prompt_budget_hard_cap",
    }
    prompt = f"{_SUBAGENT_PROMPT_PREFIX}{_subagent_body_text(emergency_payload)}"
    return prompt[:MAX_SUBAGENT_PROMPT_CHARS]


def _subagent_requests(
    candidates: Sequence[Candidate],
    records: Sequence[EvidenceRecord],
    citations: Sequence[Citation],
    ambiguity: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected_id = str(selected.get("candidate_id")) if isinstance(selected, Mapping) and selected.get("candidate_id") else ""
    if selected_id and selected_id in by_id:
        request_candidates = [by_id[selected_id]]
        request_kind = "single_candidate"
    elif ambiguity.get("needs_selection"):
        request_candidates = list(candidates[:MAX_SUBAGENT_CANDIDATES])
        request_kind = "top_cluster_comparison"
    else:
        request_candidates = [candidates[0]]
        request_kind = "single_candidate"
    candidate_ids = {candidate.candidate_id for candidate in request_candidates}
    evidence_ids = {evidence_id for candidate in request_candidates for evidence_id in candidate.evidence_ids}
    selected_records = _records_for_subagent(records, candidate_ids, evidence_ids)
    citation_ids = {
        str(citation_id)
        for candidate in request_candidates
        for citation_id in candidate.citation_ids
        if str(citation_id).strip()
    }
    citation_ids.update(str(record.citation_id) for record in selected_records if record.citation_id)
    payload = {
        "schema": "resume-cluster-input.v1",
        "request_kind": request_kind,
        "agent": RESUME_CLUSTER_AGENT,
        "allowed_task": "Summarize/rank only the supplied deterministic evidence.",
        "forbidden": [
            "external_discovery",
            "repo_reads",
            "shell_commands",
            "filesystem_scans",
            "uncited_facts",
            "state_changes",
        ],
        "required_return_fields": sorted(REQUIRED_SUBAGENT_JUDGMENT_FIELDS),
        "ambiguity": {
            "state": ambiguity.get("state", "none"),
            "triggers": list(ambiguity.get("triggers", [])),
            "needs_selection": bool(ambiguity.get("needs_selection")),
        },
        "candidates": [_candidate_inference_view(candidate) for candidate in request_candidates],
        "evidence_records": [_evidence_inference_view(record) for record in selected_records],
        "citation_metadata": _citation_metadata_for_subagent(citations, citation_ids),
    }
    payload = _bounded_subagent_payload(payload)
    prompt = _subagent_prompt_text(payload)
    payload_candidates = [candidate for candidate in payload.get("candidates") or [] if isinstance(candidate, Mapping)]
    request_kind = str(payload.get("request_kind") or request_kind)
    candidate_ids = {
        str(candidate.get("candidate_id"))
        for candidate in payload_candidates
        if str(candidate.get("candidate_id") or "").strip()
    }
    citation_ids = {
        str(citation_id)
        for candidate in payload_candidates
        for citation_id in candidate.get("citations", [])
        if str(citation_id).strip()
    }
    citation_ids.update(
        str(record.get("citation"))
        for record in payload.get("evidence_records") or []
        if isinstance(record, Mapping) and record.get("citation")
    )
    citation_ids.update(
        str(citation.get("citation_id"))
        for citation in payload.get("citation_metadata") or []
        if isinstance(citation, Mapping) and citation.get("citation_id")
    )
    return [
        {
            "request_id": f"resume-cluster-{request_kind}-1",
            "agent": RESUME_CLUSTER_AGENT,
            "model": "haiku",
            "request_kind": request_kind,
            "default_call_index": 1,
            "max_default_calls": MAX_SUBAGENT_DEFAULT_CALLS,
            "input_boundary": "provided_evidence_only",
            "candidate_ids": sorted(candidate_ids),
            "citation_ids": sorted(citation_ids),
            "payload": payload,
            "prompt": prompt,
        }
    ]


def _provided_subagent_citations(request: Mapping[str, Any]) -> set[str]:
    provided = {str(item) for item in request.get("citation_ids") or [] if str(item).strip()}
    payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
    for citation in payload.get("citation_metadata") or []:
        if isinstance(citation, Mapping) and citation.get("citation_id"):
            provided.add(str(citation["citation_id"]))
    return provided


def _request_primary_states(request: Mapping[str, Any]) -> set[str]:
    payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
    states = {
        re.sub(r"\s+", " ", str(candidate.get("primary_state") or "").strip().lower())
        for candidate in payload.get("candidates") or []
        if isinstance(candidate, Mapping) and candidate.get("primary_state")
    }
    return {state for state in states if state and not _subagent_value_is_unknown(state)}


def _deterministic_subagent_fallback(request: Mapping[str, Any], reason: str) -> dict[str, Any]:
    payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
    candidates = [candidate for candidate in payload.get("candidates") or [] if isinstance(candidate, Mapping)]
    top = candidates[0] if candidates else {}
    citations = [str(item) for item in request.get("citation_ids") or [] if str(item).strip()]
    return {
        "request_id": request.get("request_id"),
        "agent": RESUME_CLUSTER_AGENT,
        "status": "degraded",
        "degraded_reason": reason,
        "likely_work_thread": top.get("slug") or top.get("candidate_id") or "<unknown>",
        "current_or_landed_state": top.get("primary_state") or "<unknown>",
        "latest_consensus": "<unknown>",
        "unresolved_questions": ["subagent inference unavailable; using deterministic resume-context fields"],
        "confidence": top.get("confidence") or "low",
        "confidence_reasons": ["deterministic fallback after invalid or unavailable bounded inference"],
        "suggested_next_command_or_prompt": "<unknown>",
        "citations": citations[:3],
    }


def _subagent_value_is_unknown(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return not value
    normalized = str(value or "").strip().lower()
    return normalized in {"", "<unknown>", "unknown", "none", "n/a", "null"}


def _subagent_has_factual_output(raw: Mapping[str, Any]) -> bool:
    if any(not _subagent_value_is_unknown(raw.get(field)) for field in _SUBAGENT_FACTUAL_FIELDS):
        return True
    for field in ("confidence_reasons", "unresolved_questions"):
        if any(not _subagent_text_is_procedural(item) for item in _subagent_text_items(raw.get(field))):
            return True
    return False


def _subagent_text_items(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif _subagent_value_is_unknown(value):
        raw_items = []
    else:
        raw_items = [value]
    return [str(item).strip() for item in raw_items if not _subagent_value_is_unknown(item) and str(item).strip()]


_SUBAGENT_PROCEDURAL_TEXT_WHITELIST = {
    "ask user to choose before execution",
    "confirm next task before execution",
    "needs user choice before execution",
    "which task should run next?",
}


_SUBAGENT_FACTUAL_TEXT_TERMS = {
    "active",
    "archived",
    "candidate",
    "candidates",
    "citation",
    "citations",
    "completed",
    "confidence",
    "consensus",
    "current",
    "evidence",
    "handoff",
    "landed",
    "plan",
    "provider",
    "providers",
    "registry",
    "registries",
    "repo",
    "running",
    "selected",
    "session",
    "shipped",
    "source",
    "sources",
    "stale",
    "state",
    "states",
    "status",
    "statuses",
    "supplied",
    "target",
    "thread",
    "validated",
    "validation",
}


def _subagent_text_is_procedural(value: Any) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if _subagent_value_is_unknown(normalized):
        return True
    words = set(re.findall(r"\b[a-z][a-z0-9_]*\b", normalized))
    if words.intersection(_SUBAGENT_FACTUAL_TEXT_TERMS):
        return False
    return normalized in _SUBAGENT_PROCEDURAL_TEXT_WHITELIST


def _subagent_state_labels(value: Any) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if _subagent_value_is_unknown(normalized):
        return set()
    labels = [
        part.strip()
        for part in re.split(r"\s*(?:,|/|\||\+|\band\b)\s*", normalized)
        if part.strip()
    ]
    return set(labels)


def _normalize_subagent_state_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        labels = {
            re.sub(r"\s+", " ", str(item or "").strip().lower())
            for item in value
            if not _subagent_value_is_unknown(item)
        }
        labels = {label for label in labels if label}
        if not labels:
            return "<unknown>"
        return ", ".join(sorted(labels))
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if _subagent_value_is_unknown(normalized):
        return "<unknown>"
    return normalized


def _normalize_subagent_judgment(raw: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    if raw in (None, ""):
        return _deterministic_subagent_fallback(request, "missing_output")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return _deterministic_subagent_fallback(request, "malformed_json")
    if not isinstance(raw, Mapping):
        return _deterministic_subagent_fallback(request, "malformed_shape")
    missing = sorted(REQUIRED_SUBAGENT_JUDGMENT_FIELDS.difference(raw))
    if missing:
        return _deterministic_subagent_fallback(request, f"missing_fields:{','.join(missing)}")
    provided = _provided_subagent_citations(request)
    used_citations = {str(item) for item in raw.get("citations") or [] if str(item).strip()}
    if _subagent_has_factual_output(raw) and not used_citations:
        return _deterministic_subagent_fallback(request, "missing_citations")
    if not used_citations.issubset(provided):
        return _deterministic_subagent_fallback(request, "citation_outside_supplied_evidence")
    state_value = _normalize_subagent_state_value(raw.get("current_or_landed_state"))
    stated_labels = _subagent_state_labels(state_value)
    request_states = _request_primary_states(request)
    if stated_labels and not stated_labels.issubset(request_states):
        return _deterministic_subagent_fallback(request, "state_contradicts_deterministic_evidence")
    confidence = str(raw.get("confidence") or "low").lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    questions = raw.get("unresolved_questions") if isinstance(raw.get("unresolved_questions"), list) else [str(raw.get("unresolved_questions"))]
    reasons = raw.get("confidence_reasons") if isinstance(raw.get("confidence_reasons"), list) else [str(raw.get("confidence_reasons"))]
    return {
        "request_id": request.get("request_id"),
        "agent": RESUME_CLUSTER_AGENT,
        "status": "ok",
        "likely_work_thread": str(raw.get("likely_work_thread") or "<unknown>"),
        "current_or_landed_state": state_value,
        "latest_consensus": str(raw.get("latest_consensus") or "<unknown>"),
        "unresolved_questions": [str(item) for item in questions if str(item).strip()],
        "confidence": confidence,
        "confidence_reasons": [str(item) for item in reasons if str(item).strip()],
        "suggested_next_command_or_prompt": str(raw.get("suggested_next_command_or_prompt") or "<unknown>"),
        "citations": sorted(used_citations),
    }


def attach_subagent_judgments(packet: Mapping[str, Any], raw_outputs: Sequence[Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(packet))
    requests = [request for request in updated.get("subagent_requests") or [] if isinstance(request, Mapping)]
    judgments: list[dict[str, Any]] = []
    for idx, request in enumerate(requests[:MAX_SUBAGENT_DEFAULT_CALLS]):
        raw = raw_outputs[idx] if idx < len(raw_outputs) else None
        judgments.append(_normalize_subagent_judgment(raw, request))
    updated["subagent_judgments"] = judgments
    return updated

def _parse_lookback_days(value: str) -> int:
    raw = value.strip().lower()
    match = re.fullmatch(r"(\d+)([dw]?)", raw)
    if not match:
        raise argparse.ArgumentTypeError("--lookback expects N, Nd, or Nw")
    amount = int(match.group(1))
    unit = match.group(2)
    days = amount * 7 if unit == "w" else amount
    if days < 1:
        raise argparse.ArgumentTypeError("--lookback must be at least one day")
    return days


def _expand_arguments(argv: Sequence[str]) -> tuple[list[str], str | None]:
    raw = list(argv)
    expanded: list[str] = []
    consumed_next = False
    raw_argument_string: str | None = None
    for idx, token in enumerate(raw):
        if consumed_next:
            consumed_next = False
            continue
        if token == "--arguments" and idx + 1 < len(raw):
            raw_argument_string = raw[idx + 1]
            expanded.extend(shlex.split(raw_argument_string))
            consumed_next = True
        elif token.startswith("--arguments="):
            raw_argument_string = token.split("=", 1)[1]
            expanded.extend(shlex.split(raw_argument_string))
        else:
            expanded.append(token)
    return expanded, raw_argument_string


def _split_exact_token(token: str) -> tuple[str, str] | None:
    prefix, sep, value = token.partition(":")
    if not sep or not value:
        return None
    attr = EXACT_TOKEN_PREFIXES.get(prefix.lower())
    if attr is None:
        return None
    return attr, value


def _apply_positional_shortcuts(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    fuzzy: list[str] = []
    exact_fields_from_positionals: list[str] = []
    resume_mode: str | None = None
    for token in list(args.query or []):
        split = _split_exact_token(token)
        if split is not None:
            attr, value = split
            existing = getattr(args, attr)
            if existing and existing != value:
                parser.error(f"conflicting {attr} target supplied")
            setattr(args, attr, value)
            if attr != "repo":
                exact_fields_from_positionals.append(attr)
            continue
        lowered = token.lower()
        if lowered in CURRENT_TARGET_TOKENS:
            resume_mode = "current"
            exact_fields_from_positionals.append("current")
            continue
        if lowered in LATEST_TARGET_TOKENS:
            resume_mode = "latest"
            exact_fields_from_positionals.append("latest")
            continue
        fuzzy.append(token)
    args.resume_mode = resume_mode
    exact_fields = [
        field
        for field in ("slug", "run", "branch", "worktree", "artifact", "select")
        if getattr(args, field, None)
    ]
    exact_fields.extend(field for field in exact_fields_from_positionals if field in {"current", "latest"})
    if args.select and len([field for field in exact_fields if field != "select"]) > 0:
        parser.error("--select cannot be combined with another exact target")
    unique_exact_fields = sorted(set(exact_fields))
    if len(unique_exact_fields) > 1:
        parser.error("supply only one exact target shortcut; --repo may qualify that target")
    args.query = [*list(args.topic or []), *fuzzy]


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str], str | None]:
    expanded, raw_argument_string = _expand_arguments(argv)
    parser = _parser()
    args, unknown = parser.parse_known_args(expanded)
    if unknown and args.report is None:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if args.report is not None and unknown:
        forwarded = list(unknown)
        query_values = list(args.query or [])
        for token in unknown:
            try:
                idx = expanded.index(token)
            except ValueError:
                continue
            if idx + 1 >= len(expanded):
                continue
            value = expanded[idx + 1]
            if value.startswith("-") or value not in query_values:
                continue
            forwarded.append(value)
            query_values.remove(value)
        args.query = query_values
        args.unknown_arguments = forwarded
    else:
        args.unknown_arguments = unknown
    args.expanded_arguments = expanded
    args.raw_argument_string = raw_argument_string
    _apply_positional_shortcuts(args, parser)
    if args.lookback_days is None:
        args.lookback_days = 30
    if args.json:
        args.format = "json"
        args.noninteractive = True
    if args.noninteractive is None:
        args.noninteractive = False
    if args.noninteractive:
        args.format = "json"
    args.interaction_mode = "noninteractive" if args.noninteractive or args.format == "json" else "interactive"
    return args, expanded, raw_argument_string


def _parsed_arguments(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "expanded_arguments": list(args.expanded_arguments),
        "unknown_arguments": list(args.unknown_arguments),
        "exact_targets": {
            "slug": args.slug,
            "run": args.run,
            "branch": args.branch,
            "worktree": args.worktree,
            "artifact": args.artifact,
            "repo": args.repo,
            "select": args.select,
            "mode": getattr(args, "resume_mode", None),
        },
        "topic": list(args.query or []),
        "lookback_days": args.lookback_days,
        "max_candidates": args.max_candidates,
        "all_repos": bool(args.all_repos),
        "format": args.format,
        "noninteractive": bool(args.noninteractive),
        "report": args.report,
    }


def build_context(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    raw_argv = list(argv or [])
    args, expanded_argv, raw_argument_string = _parse_args(raw_argv)
    generated_dt = datetime.now(timezone.utc).replace(microsecond=0)
    generated_at = _format_utc(generated_dt)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else REPO_ROOT
    query = " ".join(args.query).strip()
    seed = ContextSeed(
        argv=raw_argv,
        query=query,
        raw_query_tokens=list(args.query),
        args=args,
        repo_root=repo_root,
        generated_at=generated_at,
        environ=environ or os.environ,
    )
    providers: list[EvidenceProvider] = [
        RepoIdentityProvider(),
        TargetResolutionProvider(),
        ArtifactInventoryProvider(),
        PlanStateProvider(),
        GitLogProvider(),
        DecisionsProvider(),
        ContextJsonProvider(),
        RunBriefProvider(),
        FollowupEvidenceProvider(),
        MemoryEvidenceProvider(),
        SideEvidencePolicyProvider(),
    ]
    records: list[EvidenceRecord] = []
    candidates: list[Candidate] = []
    citations: list[Citation] = []
    source_status: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for provider in providers:
        try:
            result = provider.collect(seed)
        except Exception as exc:  # provider boundary: degrade, never crash packet assembly
            status = SourceStatus(provider=provider.name, status="degraded", degraded=True, warnings=[str(exc)])
            result = ProviderResult(provider=provider.name, status=status, warnings=[str(exc)])
            result.records.append(
                EvidenceRecord(
                    evidence_id=f"ev-{provider.name}-uncaught-failure",
                    evidence_type="provider_failure",
                    provider=provider.name,
                    source=provider.name,
                    status="degraded",
                    validation_status="degraded",
                    observed_at=generated_at,
                    degraded=True,
                    data={"error": str(exc)},
                )
            )
        records.extend(result.records)
        candidates.extend(result.candidates)
        citations.extend(result.citations)
        warnings.extend(result.warnings)
        warnings.extend(result.status.warnings)
        source_status[result.provider] = result.status.as_dict()
    merged_candidates = _merge_candidates(candidates, records, seed)
    for candidate in merged_candidates:
        if candidate.score >= 80:
            candidate.confidence = "high"
        elif candidate.score >= 35:
            candidate.confidence = "medium"
        else:
            candidate.confidence = "low"
    ambiguity = _ambiguity(merged_candidates, seed)
    selected = _select_target(merged_candidates, seed, ambiguity)
    for candidate in merged_candidates:
        warnings.extend(candidate.ambiguity_warnings)
    warnings.extend(seed.warnings)
    warnings = list(dict.fromkeys(str(w) for w in warnings if str(w).strip()))
    packet_status = "needs_selection" if ambiguity.get("needs_selection") else ("selected" if selected is not None else "not_found")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "status": packet_status,
        "generated_at": generated_at,
        "query": {
            "text": query,
            "tokens": _tokenize(query),
            "raw_tokens": list(args.query),
            "raw_argument_string": raw_argument_string,
            "target_descriptor": seed.target_descriptor,
        },
        "raw_arguments": raw_argv,
        "parsed_arguments": _parsed_arguments(args),
        "interaction_mode": args.interaction_mode,
        "requested_report": {"requested": args.report is not None, "tier": args.report, "forwarded_args": list(args.unknown_arguments)},
        "report_target": _report_target(selected, args, ambiguity, current_repo_id=seed.repo_id),
        "repo_identity": {
            "repo_root": str(repo_root),
            "repo_id": seed.repo_id,
            "base_dir": seed.base_dir,
            "current_repo": True,
            "repo_sources": seed.repo_sources,
        },
        "lookback": {
            "days": args.lookback_days,
            "cutoff": _format_utc(generated_dt - timedelta(days=args.lookback_days)),
            "max_candidates": args.max_candidates,
            "repo_scope": "current" if not args.all_repos else "all_repos_opt_in",
            "source_order": [provider.name for provider in providers],
            "caps": {
                "max_candidates": args.max_candidates,
                "max_artifact_bytes": MAX_TEXT_BYTES,
                "repo_scope": "current" if not args.all_repos else "all_repos_opt_in",
            },
            "truncated": any(r.truncated for r in records),
        },
        "source_status": source_status,
        "candidates": [candidate.as_dict() for candidate in merged_candidates[: args.max_candidates]],
        "evidence_records": [record.as_dict() for record in records],
        "score_components": {
            "component_weights": {
                "exact_slug": 100,
                "current_plan_dir": 25,
                "active_registry": 40,
                "tasks_present": 20,
                "tasks_completed": 30,
                "session_valid": 15,
                "handoff_valid": 10,
                "report_available": 5,
                "degraded_evidence": -10,
                "conflicting_or_stale_evidence": -30,
                "branch_worktree_git_conflict": -15,
                "recency_decay": "dynamic -15..+10",
            },
            "candidate_scores": [
                {"candidate_id": c.candidate_id, "score": c.score, "components": c.score_components, "negative_evidence": c.negative_evidence}
                for c in merged_candidates[: args.max_candidates]
            ],
        },
        "negative_evidence": [
            {"candidate_id": c.candidate_id, **negative}
            for c in merged_candidates[: args.max_candidates]
            for negative in c.negative_evidence
        ],
        "state_flags": {
            c.candidate_id: sorted(k for k, v in (c.current_state.get("flags", {}) if isinstance(c.current_state, dict) else {}).items() if v)
            for c in merged_candidates[: args.max_candidates]
        },
        "state_reasons": {
            c.candidate_id: {
                "primary_state": c.current_state.get("primary") if isinstance(c.current_state, dict) else "unknown",
                "score_components": c.score_components,
                "negative_evidence": c.negative_evidence,
                "source_warnings": c.source_warnings,
                "ambiguity_warnings": c.ambiguity_warnings,
            }
            for c in merged_candidates[: args.max_candidates]
        },
        "provider_allowlist": [provider.name for provider in providers],
        "current_state_taxonomy": _taxonomy(),
        "flags": {
            "has_degraded_sources": any(v.get("degraded") for v in source_status.values()),
            "has_stale_evidence": any(r.stale for r in records),
            "has_superseded_evidence": any(r.superseded for r in records),
            "has_truncated_evidence": any(r.truncated for r in records),
        },
        "ambiguity": ambiguity,
        "selected_target": selected,
        "ranking": _ranking(merged_candidates[: args.max_candidates], ambiguity),
        "subagent_request_policy": {
            "agent": RESUME_CLUSTER_AGENT,
            "model": "haiku",
            "default_dispatch": "optional_after_deterministic_clustering",
            "max_default_calls": MAX_SUBAGENT_DEFAULT_CALLS,
            "input_boundary": "provided_evidence_only",
            "degradation": "missing_malformed_uncited_or_contradictory_output_keeps_deterministic_state",
            "may_change": ["wording", "uncertainty_summary"],
            "must_not_change": ["source_status", "primary_state", "selected_target", "deterministic_citations"],
        },
        "subagent_requests": _subagent_requests(merged_candidates[: args.max_candidates], records, citations, ambiguity, selected),
        "subagent_judgments": [],
        "warnings": warnings,
        "citations": [citation.as_dict() for citation in citations],
        "citation_metadata": [citation.as_dict() for citation in citations],
        "suggested_continuations": _continuations(selected, merged_candidates, ambiguity),
        "suggested_selection_args": _suggested_selection_args(selected, merged_candidates, ambiguity),
        "safe_next_command": _safe_next_command(selected, merged_candidates, ambiguity),
        "recommendation_matrix": {
            "keys": [
                "selected_target_type",
                "confidence",
                "ambiguity",
                "completion",
                "registry_state",
                "branch_worktree_state",
                "report_available",
                "known_resume_form",
            ],
            "rules": [
                {"when": {"ambiguity": "needs_selection"}, "safe_kind": "select_target"},
                {"when": {"selected_target_type": "plan", "completion": "incomplete_or_unknown", "registry_state": "active|none", "branch_worktree_state": "none|associated_clean_or_unknown"}, "safe_kind": "continue_plan"},
                {"when": {"branch_worktree_state": "dirty|divergent"}, "safe_kind": "inspect_worktree"},
                {"when": {"selected_target_type": "run"}, "safe_kind": "report_selected_run"},
                {"when": {"completion": "complete"}, "safe_kind": "report_selected"},
                {"when": {"known_resume_form": "query_or_exact_flags"}, "safe_kind": "refine_query"},
            ],
        },
    }
    return packet
def _citation_suffix(ids: Sequence[Any]) -> str:
    clean = [str(item) for item in ids if str(item).strip()]
    if not clean:
        return "[no citation]"
    return "[" + ", ".join(clean[:3]) + "]"


def _candidate_title(candidate: Mapping[str, Any]) -> str:
    slug = str(candidate.get("slug") or "unknown-target")
    run_id = candidate.get("run_id")
    return f"{slug} / {run_id}" if run_id else slug


def _candidate_hint(candidate: Mapping[str, Any]) -> str:
    hints = []
    for label, key in (("repo", "repo_id"), ("worktree", "worktree_path"), ("branch", "branch")):
        value = candidate.get(key)
        if value:
            hints.append(f"{label}: {value}")
    return "; ".join(hints) if hints else "repo/worktree unknown"


def _candidate_reasons(candidate: Mapping[str, Any]) -> str:
    components = candidate.get("score_components") or {}
    if isinstance(components, Mapping):
        reasons = [f"{key}={value}" for key, value in sorted(components.items(), key=lambda item: str(item[0])) if value]
    else:
        reasons = []
    negatives = candidate.get("negative_evidence") or []
    if isinstance(negatives, Sequence) and not isinstance(negatives, (str, bytes)):
        reasons.extend(f"caveat:{item.get('reason')}" for item in negatives[:2] if isinstance(item, Mapping) and item.get("reason"))
    return ", ".join(reasons[:4]) if reasons else "bounded evidence only"


def _render_ambiguity_question(packet: Mapping[str, Any]) -> str:
    ambiguity = packet.get("ambiguity") if isinstance(packet.get("ambiguity"), Mapping) else {}
    lines = [
        "Selection required before resume rendering.",
        f"Ambiguity: {ambiguity.get('state', 'needs_selection')} — {', '.join(ambiguity.get('triggers') or ['needs_selection'])}",
        "",
        "Which target should /z-resume use? Reply with one selection token or rerun the matching command:",
    ]
    candidates = packet.get("candidates") if isinstance(packet.get("candidates"), list) else []
    for idx, candidate in enumerate(candidates[:3], start=1):
        if not isinstance(candidate, Mapping):
            continue
        state = (candidate.get("current_state") or {}).get("primary", candidate.get("primary_state", "unknown")) if isinstance(candidate.get("current_state"), Mapping) else candidate.get("primary_state", "unknown")
        lines.extend(
            [
                f"{idx}. {_candidate_title(candidate)}",
                f"   token: {candidate.get('selection_token') or 'candidate:' + str(candidate.get('candidate_id') or '')}",
                f"   state/confidence: {state} / {candidate.get('confidence', 'low')} (score {candidate.get('score', 0)})",
                f"   hints: {_candidate_hint(candidate)}",
                f"   reasons: {_candidate_reasons(candidate)} {_citation_suffix(candidate.get('citation_ids') or candidate.get('citations') or [])}",
            ]
        )
    continuations = packet.get("suggested_continuations") if isinstance(packet.get("suggested_continuations"), list) else []
    if continuations:
        lines.append("")
        lines.append("Safe selection commands:")
        for item in continuations[:3]:
            if isinstance(item, Mapping) and item.get("command"):
                lines.append(f"- {item['command']} — {item.get('reason', 'explicit selection')} {_citation_suffix(item.get('citation_ids') or [])}")
    return "\n".join(lines)


def _latest_consensus(packet: Mapping[str, Any], selected: Mapping[str, Any]) -> str:
    selected_ids = set(str(item) for item in (selected.get("evidence_ids") or selected.get("evidence_refs") or []))
    records = packet.get("evidence_records") if isinstance(packet.get("evidence_records"), list) else []
    preferred = {"decisions", "run_brief", "report", "handoff", "session", "context_json"}
    for record in records:
        if not isinstance(record, Mapping) or str(record.get("type")) not in preferred:
            continue
        if selected_ids and str(record.get("evidence_id")) not in selected_ids:
            continue
        data = record.get("data") if isinstance(record.get("data"), Mapping) else {}
        summary = data.get("summary") or data.get("outcome") or data.get("next_step") or data.get("status") or record.get("type")
        return f"{summary} {_citation_suffix([record.get('citation')] if record.get('citation') else [])}"
    return f"unknown {_citation_suffix(selected.get('citation_ids') or selected.get('citations') or [])}"


def _record_citations(packet: Mapping[str, Any], **flags: bool) -> list[str]:
    records = packet.get("evidence_records") if isinstance(packet.get("evidence_records"), list) else []
    citations: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if flags.get("stale") and not record.get("stale"):
            continue
        if flags.get("superseded") and not record.get("superseded"):
            continue
        if flags.get("degraded") and not record.get("degraded"):
            continue
        if flags.get("truncated") and not record.get("truncated"):
            continue
        citation = record.get("citation")
        if citation:
            citations.append(str(citation))
    return list(dict.fromkeys(citations))


def _source_status_citations(packet: Mapping[str, Any]) -> list[str]:
    source_status = packet.get("source_status") if isinstance(packet.get("source_status"), Mapping) else {}
    citations: list[str] = []
    for status in source_status.values():
        if not isinstance(status, Mapping):
            continue
        citations.extend(str(item) for item in status.get("citation_ids") or [] if str(item).strip())
    return list(dict.fromkeys(citations))


def _evidence_caveats(packet: Mapping[str, Any], selected: Mapping[str, Any] | None) -> list[str]:
    lines: list[str] = []
    flags = (packet.get("flags") or {}) if isinstance(packet.get("flags"), Mapping) else {}
    flag_specs = (
        ("has_stale_evidence", "stale evidence is present", {"stale": True}),
        ("has_superseded_evidence", "superseded evidence is present", {"superseded": True}),
        ("has_degraded_sources", "degraded source is present", {"degraded": True}),
        ("has_truncated_evidence", "truncated evidence is present", {"truncated": True}),
    )
    for key, label, citation_filter in flag_specs:
        if flags.get(key):
            lines.append(f"{label} {_citation_suffix(_record_citations(packet, **citation_filter) or _source_status_citations(packet))}")
    if packet.get("warnings"):
        lines.append(f"packet warnings are available in machine-readable output {_citation_suffix(_source_status_citations(packet))}")
    if selected:
        selected_citations = selected.get("citation_ids") or selected.get("citations") or []
        for warning in (selected.get("source_warnings") or [])[:3]:
            lines.append(f"{warning} {_citation_suffix(selected_citations)}")
        for warning in (selected.get("ambiguity_warnings") or [])[:3]:
            lines.append(f"{warning} {_citation_suffix(selected_citations)}")
    return list(dict.fromkeys(line for line in lines if line))


def _render_not_found(packet: Mapping[str, Any]) -> str:
    lookback = packet.get("lookback") if isinstance(packet.get("lookback"), Mapping) else {}
    source_status = packet.get("source_status") if isinstance(packet.get("source_status"), Mapping) else {}
    degraded = [name for name, value in source_status.items() if isinstance(value, Mapping) and value.get("status") not in {"ok", "missing"}]
    return "\n".join(
        [
            "status: not_found",
            f"Searched bounded sources for {lookback.get('days', 'unknown')} days; max candidates {lookback.get('max_candidates', 'unknown')}.",
            f"Degraded/missing context: {', '.join(degraded) if degraded else 'none beyond normal missing sources'}.",
            "Try an exact target: /z-resume --slug <plan-slug>, /z-resume --run <run-id>, /z-resume --branch <branch>, or /z-resume --worktree <path>.",
        ]
    )


def _render_human_packet(packet: Mapping[str, Any]) -> str:
    if packet.get("selected_target") is None:
        if packet.get("status") == "needs_selection" or (isinstance(packet.get("ambiguity"), Mapping) and packet["ambiguity"].get("needs_selection")):
            return _render_ambiguity_question(packet)
        return _render_not_found(packet)
    selected = packet["selected_target"]
    if not isinstance(selected, Mapping):
        return _render_not_found(packet)
    state = selected.get("current_state") if isinstance(selected.get("current_state"), Mapping) else {}
    primary = state.get("primary", "unknown") if isinstance(state, Mapping) else "unknown"
    flags = state.get("flags", {}) if isinstance(state, Mapping) else {}
    ambiguity = packet.get("ambiguity") if isinstance(packet.get("ambiguity"), Mapping) else {}
    safe_next = packet.get("safe_next_command") if isinstance(packet.get("safe_next_command"), Mapping) else {}
    continuations = packet.get("suggested_continuations") if isinstance(packet.get("suggested_continuations"), list) else []
    citation_ids = selected.get("citation_ids") or selected.get("citations") or []
    lines = [
        f"Resume target: {_candidate_title(selected)}  [{selected.get('selection_token', 'no-token')}]",
        f"Work item: type={selected.get('target_type', 'unknown')}; repo={selected.get('repo_id') or selected.get('repo_root') or 'unknown'}; worktree={selected.get('worktree_path') or 'unknown'}; branch={selected.get('branch') or 'unknown'} {_citation_suffix(citation_ids)}",
        f"State: {primary}; confidence={selected.get('confidence', 'low')}; score={selected.get('score', 0)}; flags={', '.join(sorted(k for k, v in flags.items() if v)) or 'none'} {_citation_suffix(citation_ids)}",
        "",
        "Latest consensus",
        f"- {_latest_consensus(packet, selected)}",
        "",
        "What changed / where it stands",
        f"- Current target state is {primary}; factual state and next-step claims are drawn from selected evidence { _citation_suffix(citation_ids) }",
        "",
        "Open ambiguity",
        f"- {ambiguity.get('state', 'none')}; triggers={', '.join(ambiguity.get('triggers') or []) or 'none'}",
        "",
        "Stale/superseded/degraded evidence",
    ]
    caveats = _evidence_caveats(packet, selected)
    lines.extend(f"- {line}" for line in (caveats or ["none detected"]))
    lines.extend(["", "Recommendations"])
    if safe_next:
        lines.append(f"1. {safe_next.get('command') or safe_next.get('kind') or 'refine target'} — {safe_next.get('reason', 'deterministic recommendation')} {_citation_suffix(citation_ids)}")
    for idx, item in enumerate([item for item in continuations if isinstance(item, Mapping) and item.get("command")][:2], start=2):
        lines.append(f"{idx}. {item.get('command')} — {item.get('reason', 'advisory continuation')} {_citation_suffix(item.get('citation_ids') or citation_ids)}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic /z-resume context packet.")
    parser.add_argument("query", nargs="*", help="fuzzy prior-work topic or exact target token")
    parser.add_argument("--arguments", help="raw command argument string to parse before other argv")
    parser.add_argument("--topic", action="append", default=[], help="explicit fuzzy topic text")
    parser.add_argument("--slug", "--plan", dest="slug", help="exact plan slug to seed/select")
    parser.add_argument("--run", help="exact run id to seed/select")
    parser.add_argument("--branch", help="branch-name evidence anchor")
    parser.add_argument("--worktree", help="worktree-path evidence anchor")
    parser.add_argument("--artifact", help="artifact path/kind evidence anchor")
    parser.add_argument("--repo", help="repo id/path qualifier")
    parser.add_argument("--select", help="explicit selection token from a prior packet")
    parser.add_argument("--repo-root", help="target repository root for provenance and deterministic probes; helper scripts are loaded from this script's install root", default=str(Path.cwd()))
    parser.add_argument("--plan-dir", help="explicit plan directory for provider validation")
    parser.add_argument("--lookback", "--lookback-days", dest="lookback_days", type=_parse_lookback_days)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--all-repos", action="store_true", help="opt in to bounded discovery across known repo sources")
    parser.add_argument("--format", choices=("human", "json", "pretty"), default="human")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--noninteractive", action="store_true", default=None, help="never ask; emit needs_selection when ambiguous")
    parser.add_argument("--report", nargs="?", const="standard", help="record requested report tier; rendering is later and requires selection")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    try:
        packet = build_context(argv, environ=environ)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    args, _expanded_argv, _raw_argument_string = _parse_args(argv)
    packet_json = json.dumps(packet, indent=2, sort_keys=True)
    output = packet_json if args.format in {"json", "pretty"} else _render_human_packet(packet)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
