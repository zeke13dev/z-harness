#!/usr/bin/env python3
"""report-context.py — Resolve a z-harness report target and assemble the context bundle.

Usage:
    report-context.py [--resolve-only] [target]
        [--run ID] [--slug S] [--pr N|URL] [--range A..B] [--base REF]
        [--worktree PATH] [--resume-context PATH] [--out PATH]
``--resolve-only`` prints the resolution descriptor JSON to stdout and exits.
Otherwise assembles the full bundle and writes it to ``--out``.

T001: implements the resolution descriptor only (``--resolve-only`` path).
      Bundle assembly (``assemble_bundle``) is implemented in T002 (run/slug).
      T003 implements pr/range/base/worktree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.telemetry.native_usage import summarize_sources  # noqa: E402

SCHEMA_VERSION = 1

# ── import render-run-brief helpers (hyphenated module name) ──────────────────

def _import_render_run_brief():
    """Lazily import aggregate_decisions + extract_approach_bullets from render-run-brief.py."""
    rrb_path = SCRIPT_DIR / "render-run-brief.py"
    spec = importlib.util.spec_from_file_location("render_run_brief", rrb_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load render-run-brief.py from {rrb_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_rrb_mod = None


def _get_rrb():
    global _rrb_mod
    if _rrb_mod is None:
        _rrb_mod = _import_render_run_brief()
    return _rrb_mod

# ── shape regexes ──────────────────────────────────────────────────────────────

# ISO run-id: 20260618T123456Z-...
_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-")

# PR: #N or https://github.com/.../pull/N
_PR_HASH_RE = re.compile(r"^#(\d+)$")
_PR_URL_RE = re.compile(r"github\.com/.+/pull/(\d+)$")

# Bare integer (positive, no #)
_BARE_INT_RE = re.compile(r"^\d+$")

# Bare hex SHA (7–40 chars)
_BARE_HEX_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


# ── external helpers (plan-path.sh + active-plan-registry.py) ─────────────────

def _run_plan_path(subcommand: str, *args: str) -> tuple[int, str, str]:
    """Run plan-path.sh <subcommand> [args] and return (returncode, stdout, stderr)."""
    plan_path_sh = SCRIPT_DIR / "plan-path.sh"
    if not plan_path_sh.exists():
        return 1, "", f"plan-path.sh not found at {plan_path_sh}"
    try:
        result = subprocess.run(
            ["bash", str(plan_path_sh), subcommand, *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except OSError as exc:
        return 1, "", str(exc)


def _all_plan_slugs() -> list[str]:
    """Return all known plan slugs via plan-path.sh all_plan_slugs."""
    rc, out, _err = _run_plan_path("all_plan_slugs")
    if rc != 0 or not out:
        return []
    return [s for s in out.splitlines() if s.strip()]


def _active_plan_records() -> list[dict]:
    """Return active-plan registry records via active-plan-registry.py list --json."""
    registry_py = SCRIPT_DIR / "active-plan-registry.py"
    if not registry_py.exists():
        return []
    try:
        result = subprocess.run(
            [sys.executable, str(registry_py), "list", "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            parsed = json.loads(result.stdout)
            if isinstance(parsed, list):
                return parsed
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _slug_exists(slug: str) -> bool:
    """Return True if the slug resolves to an existing plan directory."""
    rc, out, _err = _run_plan_path("resolve_plan_path", slug)
    if rc != 0 or not out:
        return False
    return Path(out).is_dir()


# ── descriptor construction ────────────────────────────────────────────────────

def _descriptor(mode: str, **extra) -> dict:
    """Build a resolution descriptor dict."""
    desc: dict = {"mode": mode}
    desc.update(extra)
    return desc


_SELECTED_RESUME_TARGET_KEYS = {
    "target_type",
    "selection_kind",
    "selection_token",
    "slug",
    "run_id",
    "repo_id",
    "repo_root",
    "plan_dir",
    "run_dir",
    "branch",
    "worktree_path",
    "head",
    "current_state",
    "confidence",
    "score",
    "candidate_id",
    "citation_ids",
    "citations",
    "evidence_ids",
    "evidence_refs",
    "score_components",
    "negative_evidence",
    "source_status",
    "source_warnings",
    "ambiguity_warnings",
}

_SELECTED_RESUME_EVIDENCE_KEYS = {
    "evidence_id",
    "type",
    "provider",
    "source",
    "source_path",
    "citation",
    "citation_id",
    "freshness",
    "status",
    "validation_status",
    "candidate_id",
    "candidate_refs",
    "stale",
    "superseded",
    "degraded",
    "truncated",
    "side_evidence",
    "data",
}


def _compact_resume_value(value, *, max_items: int = 12, max_chars: int = 1200):
    """Return a deterministic, JSON-safe, bounded projection of resume-context data."""
    if isinstance(value, str):
        if len(value) > max_chars:
            return value[: max_chars - 3] + "..."
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [_compact_resume_value(item, max_items=max_items, max_chars=max_chars) for item in value[:max_items]]
    if isinstance(value, dict):
        projected = {}
        for idx, key in enumerate(sorted(value, key=str)):
            if idx >= max_items:
                projected["_truncated_keys"] = max(0, len(value) - max_items)
                break
            projected[str(key)] = _compact_resume_value(value[key], max_items=max_items, max_chars=max_chars)
        return projected
    return str(value)


def _load_resume_context_packet(path: Path, warnings: list[str]) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"selected resume-context read failed: {exc}")
        return None
    try:
        packet = json.loads(raw)
    except json.JSONDecodeError as exc:
        warnings.append(f"selected resume-context JSON parse failed: {exc}")
        return None
    if not isinstance(packet, dict):
        warnings.append("selected resume-context packet is not a JSON object")
        return None
    return packet


def _clean_resume_string_set(value) -> set[str]:
    return {str(item).strip() for item in value or [] if str(item).strip()}


def _safe_report_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(Path(value).expanduser())


def _descriptor_report_target_args(descriptor: dict) -> list[str] | None:
    mode = str(descriptor.get("mode") or "")
    if mode == "run":
        run_id = str(descriptor.get("run_id") or "").strip()
        if run_id:
            return ["--run", run_id]
        slug = str(descriptor.get("slug") or "").strip()
        if slug:
            return ["--slug", slug]
    if mode == "slug":
        slug = str(descriptor.get("slug") or "").strip()
        if slug:
            return ["--slug", slug]
    if mode == "worktree":
        worktree_path = str(descriptor.get("worktree_path") or "").strip()
        if worktree_path:
            return ["--worktree", worktree_path]
    return None


def _report_target_args_match(report_target: dict, descriptor: dict) -> bool:
    target_args = [str(item) for item in report_target.get("target_args") or []]
    expected = _descriptor_report_target_args(descriptor)
    if not target_args or expected is None or len(target_args) != len(expected):
        return False
    if target_args[0] != expected[0]:
        return False
    if target_args[0] == "--worktree":
        return _safe_report_path(target_args[1]) == _safe_report_path(expected[1])
    return target_args[1:] == expected[1:]


def _project_selected_resume_context(packet: dict, source_path: Path, warnings: list[str], descriptor: dict | None = None) -> dict | None:
    """Project only the selected, cited resume-context fields into context.json."""
    ambiguity = packet.get("ambiguity") if isinstance(packet.get("ambiguity"), dict) else {}
    selected = packet.get("selected_target") if isinstance(packet.get("selected_target"), dict) else None
    report_target = packet.get("report_target") if isinstance(packet.get("report_target"), dict) else {}
    if str(packet.get("status") or "").strip().lower() != "selected":
        warnings.append("selected resume-context packet status is not selected")
        return None
    if ambiguity.get("needs_selection") or selected is None:
        warnings.append("selected resume-context requires target selection before report rendering")
        return None
    if report_target.get("status") != "ready" or not report_target.get("target_args"):
        warnings.append("selected resume-context report target is not ready")
        return None
    if descriptor is not None and not _report_target_args_match(report_target, descriptor):
        warnings.append("selected resume-context report target does not match requested report target")
        return None

    selected_ids = _clean_resume_string_set(selected.get("evidence_ids") or selected.get("evidence_refs"))
    selected_citations = _clean_resume_string_set(selected.get("citation_ids") or selected.get("citations"))
    if not selected_ids:
        warnings.append("selected resume-context has no explicit selected evidence ids")
        return None
    if not selected_citations:
        warnings.append("selected resume-context has no explicit selected citation ids")
        return None

    citation_metadata_by_id: dict[str, dict] = {}
    for citation in packet.get("citation_metadata") or packet.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        citation_id = str(citation.get("citation_id") or "").strip()
        if citation_id in selected_citations and citation_id not in citation_metadata_by_id:
            citation_metadata_by_id[citation_id] = _compact_resume_value(citation)

    evidence_records: list[dict] = []
    emitted_evidence_ids: list[str] = []
    emitted_citation_ids: list[str] = []
    for record in packet.get("evidence_records") or []:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id") or "")
        include_record = evidence_id in selected_ids
        if include_record:
            record_citation = str(record.get("citation_id") or record.get("citation") or "").strip()
            if not record_citation:
                warnings.append("selected resume-context selected evidence is missing a citation")
                return None
            if record_citation not in selected_citations:
                warnings.append("selected resume-context selected evidence cites an unselected citation")
                return None
            if record_citation not in citation_metadata_by_id:
                warnings.append("selected resume-context selected evidence citation is missing metadata")
                return None
            projected = {
                key: _compact_resume_value(value)
                for key, value in record.items()
                if key in _SELECTED_RESUME_EVIDENCE_KEYS
            }
            evidence_records.append(projected)
            emitted_evidence_ids.append(evidence_id)
            if record_citation not in emitted_citation_ids:
                emitted_citation_ids.append(record_citation)
        if len(evidence_records) >= 12:
            break

    if not evidence_records:
        warnings.append("selected resume-context selected evidence ids did not match evidence records")
        return None

    citation_metadata = [citation_metadata_by_id[citation_id] for citation_id in emitted_citation_ids]

    selected_target = {
        key: _compact_resume_value(value)
        for key, value in selected.items()
        if key in _SELECTED_RESUME_TARGET_KEYS
    }
    if "citation_ids" in selected:
        selected_target["citation_ids"] = emitted_citation_ids
    if "citations" in selected:
        selected_target["citations"] = emitted_citation_ids
    if "evidence_ids" in selected:
        selected_target["evidence_ids"] = emitted_evidence_ids
    if "evidence_refs" in selected:
        selected_target["evidence_refs"] = emitted_evidence_ids

    requested_report = packet.get("requested_report") if isinstance(packet.get("requested_report"), dict) else {}
    return {
        "source": str(source_path),
        "schema_version": packet.get("schema_version"),
        "status": packet.get("status"),
        "generated_at": packet.get("generated_at"),
        "query": _compact_resume_value(packet.get("query") or {}),
        "interaction_mode": packet.get("interaction_mode"),
        "requested_report": _compact_resume_value(requested_report),
        "report_target": _compact_resume_value(report_target),
        "ambiguity": _compact_resume_value(
            {
                "state": ambiguity.get("state", "none"),
                "needs_selection": bool(ambiguity.get("needs_selection")),
                "triggers": ambiguity.get("triggers") or [],
            }
        ),
        "selected_target": selected_target,
        "selected_evidence": evidence_records,
        "citation_metadata": citation_metadata,
        "warnings": _compact_resume_value(packet.get("warnings") or []),
    }


def _resolve_selected_resume_context(resume_context_path: Path | None, warnings: list[str], descriptor: dict | None = None) -> dict | None:
    if resume_context_path is None:
        return None
    packet = _load_resume_context_packet(resume_context_path, warnings)
    if packet is None:
        return None
    return _project_selected_resume_context(packet, resume_context_path, warnings, descriptor)


def _attach_selected_resume_context(bundle: dict, projection: dict | None) -> None:
    if projection is None:
        return
    bundle["selected_resume_context_status"] = "attached"
    bundle["selected_resume_context"] = projection


def resolve_target(
    *,
    target: str | None,
    flag_run: str | None,
    flag_slug: str | None,
    flag_pr: str | None,
    flag_range: str | None,
    flag_base: str | None,
    flag_worktree: str | None = None,
) -> dict:
    """Return the resolution descriptor JSON dict.

    Precedence (from SPEC §Target resolution D2):
    1. Explicit typed flag (--pr/--run/--slug/--range); >1 flag ⇒ error.
    2. No target and no flags ⇒ latest run of active/detected slug.
    3. Positional token, shape-matched.
    """
    # ── Step 1: typed flags ────────────────────────────────────────────────────
    typed_flags = {
        "run": flag_run,
        "slug": flag_slug,
        "pr": flag_pr,
        "range": flag_range,
        "worktree": flag_worktree,
    }
    active_typed = {k: v for k, v in typed_flags.items() if v is not None}
    if len(active_typed) > 1:
        names = ", ".join(f"--{k}" for k in sorted(active_typed))
        return _descriptor(
            "error",
            message=(
                f"Conflicting flags: {names}. "
                "Supply at most one of --run/--slug/--pr/--range/--worktree."
            ),
        )

    if "run" in active_typed:
        return _descriptor("run", run_id=active_typed["run"])
    if "slug" in active_typed:
        return _descriptor("slug", slug=active_typed["slug"])
    if "pr" in active_typed:
        return _descriptor("pr", pr=active_typed["pr"])
    if "range" in active_typed:
        rng = active_typed["range"]
        base = flag_base
        return _descriptor("range", range=rng, **({"base": base} if base else {}))
    if "worktree" in active_typed:
        return _descriptor("worktree", worktree_path=active_typed["worktree"])

    # --base alone (no --range) maps to range/base mode using HEAD
    if flag_base is not None and target is None:
        return _descriptor("range", base=flag_base)

    # ── Step 2: no flags, no positional ⇒ latest run of active slug ───────────
    if target is None:
        records = _active_plan_records()
        running = [r for r in records if isinstance(r, dict)]
        unique_slugs = list(dict.fromkeys(r.get("slug", "") for r in running if r.get("slug")))

        if len(unique_slugs) == 1:
            slug = unique_slugs[0]
            return _descriptor("run", slug=slug, message=f"Resolved to latest run of active slug '{slug}'.")
        if len(unique_slugs) > 1:
            return _descriptor(
                "ambiguous",
                message=(
                    "Multiple active plan slugs found: "
                    + ", ".join(unique_slugs)
                    + ". Specify --slug <s>, --run <id>, or pass a positional target."
                ),
            )
        # No active plans: cannot determine latest run
        return _descriptor(
            "ambiguous",
            message=(
                "No active plan detected. "
                "Specify --slug <s>, --run <id>, or pass a positional target."
            ),
        )

    # ── Step 3: positional token, shape matching ───────────────────────────────
    tok = target.strip()

    # 3a. ISO run-id
    if _RUN_ID_RE.match(tok):
        return _descriptor("run", run_id=tok)

    # 3b. PR: #N or GitHub pull URL
    m_hash = _PR_HASH_RE.match(tok)
    if m_hash:
        return _descriptor("pr", pr=m_hash.group(1))
    m_url = _PR_URL_RE.search(tok)
    if m_url:
        return _descriptor("pr", pr=m_url.group(1))

    # 3c. Range: contains ".."
    if ".." in tok:
        return _descriptor("range", range=tok, **({"base": flag_base} if flag_base else {}))

    # 3c. Repo-state aliases
    if tok in {"current", "changes"}:
        return _descriptor("worktree")
    if tok.startswith("since "):
        _, _, ref = tok.partition(" ")
        if ref.strip():
            return _descriptor("range", base=ref.strip())


    # 3d. Exact slug match (check before bare-int / bare-hex so named slugs win)
    if _slug_exists(tok):
        return _descriptor("slug", slug=tok)

    # 3e. Bare integer (no '#') ⇒ ambiguous
    if _BARE_INT_RE.match(tok):
        return _descriptor(
            "ambiguous",
            message=(
                f"'{tok}' is ambiguous: it could be a PR number, a run index, or a slug. "
                "Use --pr to specify a pull request, --run for a run-id, or --slug for a plan slug."
            ),
        )

    # 3f. Bare hex (7–40 chars) with no slug match ⇒ ambiguous
    if _BARE_HEX_RE.match(tok):
        return _descriptor(
            "ambiguous",
            message=(
                f"'{tok}' looks like a git SHA but did not match any plan slug. "
                "Use --range <sha>.. for a commit range, or --run for a run-id prefix."
            ),
        )

    # 3g. Else ⇒ not_found
    return _descriptor(
        "not_found",
        message=(
            f"'{tok}' did not match any run-id, PR, range, or plan slug. "
            "Check the spelling or use --slug/--run/--pr/--range to specify the target explicitly."
        ),
    )


# ── run/slug bundle helpers ────────────────────────────────────────────────────

# Overnight run-id pattern: any run whose suffix starts with -overnight-
_OVERNIGHT_RE = re.compile(r"-overnight-")

# Halt event kinds (mirrors run-status.sh allowlist)
_HALT_KINDS = frozenset({
    "task_halt",
    "docs_freshness_halt",
    "docs_staleness_halt",
    "askuser_halted",
    "unknown_ask_blocked",
    "plan_halt",
    "review_halt",
    "implement_all_halt",
    "slug_collision_halt",
    "overnight_lock_corrupt",
})


def _load_events_jsonl(events_path: Path) -> list[dict]:
    """Parse events.jsonl; return [] on missing or malformed file."""
    if not events_path.is_file():
        return []
    events: list[dict] = []
    try:
        with events_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return events


def _run_cmd_capture(cmd: list[str], *, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command and return (rc, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or str(REPO_ROOT),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except OSError as exc:
        return 1, "", str(exc)


# ── surface-map attachment helpers ─────────────────────────────────────────────

SURFACE_POLICIES = {"auto", "off", "existing", "refresh"}
TIERS = {"summary", "standard", "deep"}


def _surface_policy_allows_refresh(policy: str, tier: str, mode: str) -> bool:
    """Return True when report-context may run a fresh deterministic mapper."""
    if policy == "off":
        return False
    if policy == "existing":
        return False
    if tier == "summary":
        return False
    if policy == "refresh":
        return mode in {"pr", "range", "worktree", "run", "slug"}
    if policy == "auto":
        return mode in {"pr", "range", "worktree"}
    return False


def _surface_context_status(payload: dict, default_status: str) -> str:
    """Map producer status onto the compact context.json status vocabulary."""
    status = str(payload.get("status") or "")
    if status in {"truncated", "too_broad"}:
        return "truncated"
    return default_status


def _surface_summary(payload: dict) -> str:
    """Build a compact neutral summary from a surface-map.json payload."""
    mode = payload.get("mode", "unknown")
    status = payload.get("status", "unknown")
    primary = payload.get("primary", [])
    clusters = payload.get("clusters", [])

    paths: list[str] = []
    for item in primary:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
        if len(paths) >= 5:
            break

    labels: list[str] = []
    for item in clusters:
        if isinstance(item, dict) and item.get("label"):
            labels.append(str(item["label"]))
        if len(labels) >= 3:
            break

    parts = [f"{mode} surface map status {status}"]
    parts.append(f"{len(primary)} primary surface(s)")
    if paths:
        parts.append("primary paths: " + ", ".join(paths))
    if labels:
        parts.append("clusters: " + ", ".join(labels))
    return "; ".join(parts) + "."


def _load_surface_payload(path: Path, warnings: list[str]) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        warnings.append(f"surface-map load failed for {path}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


def _attach_surface_payload(
    bundle: dict,
    *,
    payload: dict,
    path: Path,
    source: str,
    default_status: str,
) -> None:
    payload_warnings = payload.get("warnings", [])
    if not isinstance(payload_warnings, list):
        payload_warnings = [str(payload_warnings)]

    bundle["surface_map_status"] = _surface_context_status(payload, default_status)
    bundle["surface_map_path"] = str(path)
    bundle["surface_map_summary"] = _surface_summary(payload)
    try:
        bundle["surface_map_bytes"] = path.stat().st_size
    except OSError:
        bundle["surface_map_bytes"] = 0
    bundle["surface_map_generated_at"] = str(payload.get("generated_at") or "")
    bundle["surface_map_source"] = source
    bundle["surface_map_warnings"] = [str(w) for w in payload_warnings]


def _attach_surface_failure(bundle: dict, warnings: list[str], message: str, path: Path | None = None) -> None:
    warnings.append(message)
    bundle["surface_map_status"] = "failed"
    bundle["surface_map_path"] = str(path) if path is not None else ""
    bundle["surface_map_summary"] = ""
    bundle["surface_map_bytes"] = 0
    bundle["surface_map_generated_at"] = ""
    bundle["surface_map_source"] = ""
    bundle["surface_map_warnings"] = [message]
    bundle["warnings"] = warnings


def _attach_surface_skipped(bundle: dict, reason: str) -> None:
    bundle["surface_map_status"] = "skipped"
    bundle["surface_map_path"] = ""
    bundle["surface_map_summary"] = ""
    bundle["surface_map_bytes"] = 0
    bundle["surface_map_generated_at"] = ""
    bundle["surface_map_source"] = ""
    bundle["surface_map_warnings"] = [reason]


def _surface_artifact_candidates(roots: list[Path], *, exclude: Path | None = None, recursive: bool = True) -> list[Path]:
    """Return deterministic existing surface-map.json candidates under roots."""
    seen: set[Path] = set()
    candidates: list[Path] = []
    excluded = exclude.resolve() if exclude is not None else None
    for root in roots:
        if root is None:
            continue
        root = root.resolve()
        direct = root / "surface-map.json"
        if direct.is_file():
            candidates.append(direct)
        if recursive and root.is_dir():
            for found in sorted(root.rglob("surface-map.json")):
                candidates.append(found)
    deduped: list[Path] = []
    for item in candidates:
        resolved = item.resolve()
        if excluded is not None and resolved == excluded:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(item)
    return deduped


def _run_surface_mapper(
    *,
    repo_root: Path,
    target: str,
    diff_path: Path,
    out_path: Path,
) -> tuple[int, str, str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "surface-map.py"),
        "--repo-root",
        str(repo_root),
        "--target",
        target,
        "--mode",
        "diff",
        "--caller",
        "z-report",
        "--diff-path",
        str(diff_path),
        "--out",
        str(out_path),
    ]
    return _run_cmd_capture(cmd, cwd=str(repo_root))


def _attach_fresh_diff_surface(
    bundle: dict,
    warnings: list[str],
    *,
    out_dir: Path,
    repo_root: Path,
    diff_text: str,
    target: str,
    source: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / "surface-map.diff"
    surface_path = out_dir / "surface-map.json"
    try:
        diff_path.write_text(diff_text, encoding="utf-8")
    except OSError as exc:
        _attach_surface_failure(bundle, warnings, f"surface-map diff write failed: {exc}", surface_path)
        return

    rc, _stdout, stderr = _run_surface_mapper(
        repo_root=repo_root,
        target=target,
        diff_path=diff_path,
        out_path=surface_path,
    )
    if rc != 0 or not surface_path.is_file():
        detail = stderr or "no stderr"
        _attach_surface_failure(
            bundle,
            warnings,
            f"surface-map.py failed (rc={rc}): {detail}",
            surface_path,
        )
        return

    payload = _load_surface_payload(surface_path, warnings)
    if payload is None:
        _attach_surface_failure(bundle, warnings, "surface-map.py wrote unreadable payload", surface_path)
        return

    _attach_surface_payload(
        bundle,
        payload=payload,
        path=surface_path,
        source=source,
        default_status="fresh",
    )


def _attach_existing_surface(
    bundle: dict,
    warnings: list[str],
    *,
    roots: list[Path],
    source: str,
    exclude: Path | None = None,
    recursive: bool = True,
) -> bool:
    for path in _surface_artifact_candidates(roots, exclude=exclude, recursive=recursive):
        payload = _load_surface_payload(path, warnings)
        if payload is None:
            continue
        _attach_surface_payload(
            bundle,
            payload=payload,
            path=path,
            source=source,
            default_status="existing",
        )
        return True
    return False


def _current_worktree_diff(warnings: list[str], *, cwd: str | None = None) -> str:
    repo_cwd = cwd or str(REPO_ROOT)
    rc_us, out_us, err_us = _run_cmd_capture(["git", "diff"], cwd=repo_cwd)
    if rc_us != 0:
        warnings.append(f"git diff failed for surface refresh (rc={rc_us}): {err_us}")
        out_us = ""
    rc_st, out_st, err_st = _run_cmd_capture(["git", "diff", "--staged"], cwd=repo_cwd)
    if rc_st != 0:
        warnings.append(f"git diff --staged failed for surface refresh (rc={rc_st}): {err_st}")
        out_st = ""
    return out_us + out_st


def _classify_status(run_dir: Path) -> str:
    """Call run-status.sh classify on run_dir; return status string."""
    run_status_sh = SCRIPT_DIR / "run-status.sh"
    if not run_status_sh.exists():
        return "unknown"
    # Derive --command from run-id suffix (dir name)
    run_id = run_dir.name
    command: str | None = None
    # Pattern: <ts>-<command> e.g. 20260618T123456Z-implement-all
    suffix_match = re.match(r"^\d{8}T\d{6}Z-(.+)$", run_id)
    if suffix_match:
        command = suffix_match.group(1)

    cmd = ["bash", str(run_status_sh), "classify", str(run_dir)]
    if command:
        cmd += ["--command", command]

    rc, out, err = _run_cmd_capture(cmd)
    if rc == 0 and out in ("clean", "halted", "errored", "unknown"):
        return out
    return "unknown"


def _extract_phases(events: list[dict]) -> list[dict]:
    """Extract per-phase wall-time rows from phase_end events."""
    phases: list[dict] = []
    for ev in events:
        if ev.get("kind") != "phase_end":
            continue
        row: dict = {
            "name": ev.get("name", ""),
            "wall_ms": ev.get("wall_ms", 0),
        }
        if "user_wait_ms" in ev:
            row["user_wait_ms"] = ev["user_wait_ms"]
        phases.append(row)
    return phases


def _extract_halts(events: list[dict]) -> list[dict]:
    """Extract halt events from the event stream."""
    return [ev for ev in events if ev.get("kind") in _HALT_KINDS]


def _canonical_native_usage(run_dir: Path) -> dict | None:
    """Return canonical usage/timing for this run without cross-run fallback."""
    source = run_dir / "native-usage.jsonl"
    if not source.is_file():
        return None
    return summarize_sources([("archive", source)])


def _resolve_followups(slug: str, warnings: list[str]) -> list[dict]:
    """Load all follow-up entries from project + global sinks, filtered to this slug."""
    followup_view_py = SCRIPT_DIR / "followup-view-lookup.py"
    if not followup_view_py.exists():
        warnings.append("followup-view-lookup.py not found; follow-ups skipped")
        return []

    # Resolve project followups dir
    rc, proj_dir_out, err = _run_plan_path("followups_dir")
    if rc != 0 or not proj_dir_out:
        warnings.append(f"plan-path.sh followups_dir failed: {err or 'no output'}; follow-ups skipped")
        return []
    proj_dir = Path(proj_dir_out)

    # Global followups dir: ~/.z-harness/followups/
    home = Path.home()
    global_dir = home / ".z-harness" / "followups"

    # Load from project view
    proj_view = proj_dir / "index.view.json"
    global_view = global_dir / "index.view.json"

    def _load_view(view_path: Path, label: str) -> list[dict]:
        if not view_path.exists():
            return []
        rc2, out2, err2 = _run_cmd_capture(
            [sys.executable, str(followup_view_py), "--mode=load", f"--view={view_path}"]
        )
        if rc2 != 0:
            warnings.append(f"followup-view-lookup.py load {label} failed: {err2}")
            return []
        if not out2.strip():
            return []
        try:
            entries = json.loads(out2)
            return entries if isinstance(entries, list) else []
        except json.JSONDecodeError as exc:
            warnings.append(f"followup-view-lookup.py {label} JSON parse error: {exc}")
            return []

    all_entries = _load_view(proj_view, "project") + _load_view(global_view, "global")

    # Filter: keep entries whose slug matches OR whose cited_paths overlap run plan
    filtered: list[dict] = []
    for entry in all_entries:
        if not isinstance(entry, dict):
            continue
        entry_slug = entry.get("slug") or entry.get("plan") or ""
        cited = entry.get("cited_paths") or entry.get("paths") or []
        if entry_slug == slug or (isinstance(cited, list) and any(slug in str(p) for p in cited)):
            filtered.append(entry)
    return filtered


def _estimate_cost(run_dir: Path, warnings: list[str]) -> dict:
    """Call estimate-tokens.py subagent-costs for the run; return cost dict."""
    estimate_py = SCRIPT_DIR / "estimate-tokens.py"
    if not estimate_py.exists():
        warnings.append("estimate-tokens.py not found; cost skipped")
        return {}

    # Look for metrics.jsonl in run dir, plan dir, or z-harness base
    metrics_candidates = [
        run_dir / "metrics.jsonl",
        run_dir.parent.parent / "metrics.jsonl",  # plan-level
    ]
    metrics_path: Path | None = None
    for cand in metrics_candidates:
        if cand.is_file():
            metrics_path = cand
            break

    if metrics_path is None:
        # Also try global z-harness metrics
        rc, base_out, _ = _run_plan_path("base_dir")
        if rc == 0 and base_out:
            global_metrics = Path(base_out) / "metrics.jsonl"
            if global_metrics.is_file():
                metrics_path = global_metrics

    if metrics_path is None:
        return {}

    rc, out, err = _run_cmd_capture(
        [sys.executable, str(estimate_py), "subagent-costs", "--json",
         "--metrics", str(metrics_path)]
    )
    if rc != 0:
        warnings.append(f"estimate-tokens.py subagent-costs failed: {err}")
        return {}
    if not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        warnings.append(f"estimate-tokens.py cost JSON parse error: {exc}")
        return {}


def _collect_artifacts(run_dir: Path, plan_dir: Path | None) -> list[str]:
    """Return paths to known artifact files present in run or plan dir."""
    artifact_names = [
        "SPEC.md", "PLAN.md", "TASKS.md", "TASKS.final.md", "FIX.md", "DEBUG.md",
        "INTENT.md", "INTENT.frozen.md", "LEDGER.md", "LEDGER.final.md",
        "work-graph.json", "work-graph.final.json", "MORNING_REPORT.md",
        "run-brief.json", "REPORT.md",
    ]
    found: list[str] = []
    search_dirs = [d for d in [run_dir, plan_dir] if d is not None]
    seen: set[str] = set()
    for d in search_dirs:
        for name in artifact_names:
            p = d / name
            if p.is_file() and str(p) not in seen:
                seen.add(str(p))
                found.append(str(p))
    return found


_PLAN_CONTEXT_FILE_LIMIT = 16_000
_PLAN_CONTEXT_SUMMARY_LIMIT = 4_000
_PLAN_CONTEXT_TOTAL_LIMIT = 64_000
_TASK_SUMMARY_RE = re.compile(r"^T(\d+)$")


def _bounded_text(
    path: Path,
    *,
    limit: int,
    remaining: int,
    warnings: list[str],
) -> tuple[dict | None, int]:
    """Read a deterministic bounded text projection for report synthesis."""
    if remaining <= 0 or not path.is_file():
        return None, remaining
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        warnings.append(f"plan context read failed for {path}: {exc}")
        return None, remaining
    allowed = min(limit, remaining)
    clipped = text[:allowed]
    item = {
        "path": str(path),
        "text": clipped,
        "chars": len(clipped),
        "truncated": len(text) > len(clipped),
    }
    return item, remaining - len(clipped)


def _first_bounded_text(
    candidates: list[Path],
    *,
    limit: int,
    remaining: int,
    warnings: list[str],
) -> tuple[dict | None, int]:
    for path in candidates:
        if path.is_file():
            return _bounded_text(path, limit=limit, remaining=remaining, warnings=warnings)
    return None, remaining


def _extract_plan_context(
    run_dir: Path,
    plan_dir: Path | None,
    warnings: list[str],
) -> dict | None:
    """Expose bounded INTENT-era narrative directly in context.json.

    Standard reports cannot rely on a synthesizer opening arbitrary artifact paths.
    This projection keeps the factual contract deterministic and size-bounded.
    """
    if plan_dir is None:
        return None
    remaining = _PLAN_CONTEXT_TOTAL_LIMIT
    context: dict[str, object] = {"version": 1}

    intent, remaining = _first_bounded_text(
        [run_dir / "INTENT.frozen.md", plan_dir / "INTENT.md", run_dir / "INTENT.md"],
        limit=_PLAN_CONTEXT_FILE_LIMIT,
        remaining=remaining,
        warnings=warnings,
    )
    if intent is not None:
        context["intent"] = intent

    ledger, remaining = _first_bounded_text(
        [plan_dir / "LEDGER.md", run_dir / "LEDGER.final.md", run_dir / "LEDGER.md"],
        limit=_PLAN_CONTEXT_FILE_LIMIT,
        remaining=remaining,
        warnings=warnings,
    )
    if ledger is not None:
        context["ledger"] = ledger

    summaries: list[dict] = []
    tasks_dir = plan_dir / "archive" / "tasks"
    if tasks_dir.is_dir():
        task_dirs = []
        for path in tasks_dir.iterdir():
            match = _TASK_SUMMARY_RE.match(path.name)
            if path.is_dir() and match:
                task_dirs.append((int(match.group(1)), path.name, path))
        for _number, task_id, task_dir in sorted(task_dirs):
            item, remaining = _bounded_text(
                task_dir / "SUMMARY.md",
                limit=_PLAN_CONTEXT_SUMMARY_LIMIT,
                remaining=remaining,
                warnings=warnings,
            )
            if item is not None:
                item["task_id"] = task_id
                summaries.append(item)
            if remaining <= 0:
                break
    if summaries:
        context["task_summaries"] = summaries

    context["chars"] = _PLAN_CONTEXT_TOTAL_LIMIT - remaining
    context["truncated"] = remaining <= 0 or any(
        bool(item.get("truncated"))
        for item in [intent, ledger, *summaries]
        if isinstance(item, dict)
    )
    return context if len(context) > 3 else None


def _extract_run_brief(run_dir: Path, warnings: list[str]) -> dict | None:
    """Surface the run-brief narrative (intent / outcome / key-decision bullets) for the
    summary/standard tiers, so they get the story without re-reading run-brief.json.

    Returns a bounded sub-object, or None when no run-brief.json is present. A malformed
    run-brief never raises — it appends a warning and returns None.
    """
    rb_path = run_dir / "run-brief.json"
    if not rb_path.is_file():
        return None
    try:
        rb = json.loads(rb_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warnings.append(f"run-brief parse failed: {exc}")
        return None
    narrative: dict = {}
    intent = rb.get("intent")
    outcome = rb.get("outcome")
    # `approach` is already a bulletized list in run-brief.json — use it directly as the
    # key-decision bullets (bounded) rather than re-parsing markdown.
    approach = rb.get("approach")
    if intent:
        narrative["intent"] = intent
    if outcome:
        narrative["outcome"] = outcome
    if isinstance(approach, list) and approach:
        narrative["key_decisions"] = approach[:5]
    return narrative or None


def _resolve_run_dir(descriptor: dict, warnings: list[str]) -> Path | None:
    """Resolve the run directory from a run/slug descriptor."""
    mode = descriptor.get("mode")

    if mode == "run":
        run_id = descriptor.get("run_id")
        slug = descriptor.get("slug")

        if run_id:
            # Search for any directory named <run_id> whose parent is named "archive",
            # at any depth under base.  This handles all known layouts:
            #   <base>/plans/<slug>/archive/<run_id>          (primary)
            #   <base>/plans/archive/<slug>/archive/<run_id>  (archived plan graveyard)
            #   <base>/<slug>/archive/<run_id>                (legacy flat)
            # and any other nesting depth.
            rc2, base_out, _ = _run_plan_path("base_dir")
            if rc2 == 0 and base_out:
                base = Path(base_out)
                matches = [
                    m for m in base.glob(f"**/archive/{run_id}")
                    if m.is_dir()
                ]
                def candidate_rank(path: Path) -> tuple:
                    try:
                        relative = path.relative_to(base)
                        parts = relative.parts
                    except ValueError:
                        parts = path.parts
                    if len(parts) == 4 and parts[0] == "plans" and parts[2] == "archive":
                        layout = 0  # canonical active plan
                    elif len(parts) == 5 and parts[:2] == ("plans", "archive") and parts[3] == "archive":
                        layout = 1  # archived-plan graveyard
                    elif len(parts) == 3 and parts[1] == "archive":
                        layout = 2  # legacy flat plan
                    elif len(parts) == 2 and parts[0] == "archive":
                        layout = 3  # global telemetry fallback
                    else:
                        layout = 4
                    events = path / "events.jsonl"
                    try:
                        events_size = events.stat().st_size
                    except OSError:
                        events_size = 0
                    evidence = sum(
                        candidate.is_file()
                        for candidate in (
                            events,
                            path / "run-brief.json",
                            path / "INTENT.frozen.md",
                            path / "scope.json",
                        )
                    )
                    return (layout, -evidence, -events_size, str(path))

                matches = sorted(matches, key=candidate_rank)
                if matches:
                    if len(matches) > 1:
                        warnings.append(
                            f"Multiple archive dirs found for run_id={run_id!r} "
                            f"({len(matches)} candidates); using {matches[0]}"
                        )
                    return matches[0]

            warnings.append(f"Cannot find run dir for run_id={run_id!r}")
            return None

        if slug:
            # Resolve plan dir, then find latest run under archive/
            rc, plan_out, err = _run_plan_path("resolve_plan_path", slug)
            if rc == 0 and plan_out and Path(plan_out).is_dir():
                plan_dir = Path(plan_out)
                archive_dir = plan_dir / "archive"
                if archive_dir.is_dir():
                    run_dirs = sorted(
                        (
                            d for d in archive_dir.iterdir()
                            if d.is_dir() and _RUN_ID_RE.match(d.name)
                        ),
                        key=lambda d: d.name,
                        reverse=True,
                    )
                    if run_dirs:
                        return run_dirs[0]
            warnings.append(f"Cannot find latest run dir for slug={slug!r}")
            return None

        warnings.append("mode:run but no run_id or slug in descriptor")
        return None

    if mode == "slug":
        slug = descriptor.get("slug", "")
        rc, plan_out, err = _run_plan_path("resolve_plan_path", slug)
        if rc == 0 and plan_out and Path(plan_out).is_dir():
            plan_dir = Path(plan_out)
            archive_dir = plan_dir / "archive"
            if archive_dir.is_dir():
                run_dirs = sorted(
                    (
                        d for d in archive_dir.iterdir()
                        if d.is_dir() and _RUN_ID_RE.match(d.name)
                    ),
                    key=lambda d: d.name,
                    reverse=True,
                )
                if run_dirs:
                    return run_dirs[0]
        warnings.append(f"Cannot find plan dir for slug={slug!r}")
        return None

    return None


def _assemble_run_slug_bundle(
    descriptor: dict,
    run_dir: Path,
    warnings: list[str],
) -> dict:
    """Assemble the context bundle for mode=run or mode=slug."""
    mode = descriptor.get("mode", "run")
    slug = descriptor.get("slug") or ""
    run_id = run_dir.name

    # If mode=slug, refine slug from descriptor
    if not slug and mode == "slug":
        slug = descriptor.get("slug", "")

    # Plan dir: two levels up from run_dir (run_dir = plan_dir/archive/<run>/)
    archive_dir = run_dir.parent
    plan_dir = archive_dir.parent if archive_dir.name == "archive" else None

    events_path = run_dir / "events.jsonl"
    events_present = events_path.is_file()

    # Degradation: missing events.jsonl
    if not events_present:
        bundle: dict = {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "degraded": "no_events",
            "status": "unknown",
            "run_brief_present": (run_dir / "run-brief.json").is_file(),
            "decisions": [],
            "phases": [],
            "halts": [],
            "followups": [],
            "cost": {},
            "artifacts": _collect_artifacts(run_dir, plan_dir),
            "events_chars": 0,
            "warnings": warnings,
        }
        run_brief = _extract_run_brief(run_dir, warnings)
        if run_brief is not None:
            bundle["run_brief"] = run_brief
        transcripts_dir = run_dir / "transcripts"
        if transcripts_dir.is_dir():
            bundle["transcripts_dir"] = str(transcripts_dir)
        if slug:
            bundle["slug"] = slug
        plan_context = _extract_plan_context(run_dir, plan_dir, warnings)
        if plan_context is not None:
            bundle["plan_context"] = plan_context
        native_usage = _canonical_native_usage(run_dir)
        if native_usage is not None:
            bundle["native_usage"] = native_usage
        return bundle

    # Load events
    events = _load_events_jsonl(events_path)
    events_chars = events_path.stat().st_size

    # Infer slug from events if not already known
    if not slug:
        for ev in events:
            s = ev.get("slug")
            if s:
                slug = s
                break

    # Status
    status = _classify_status(run_dir)

    # Decisions — import from render-run-brief.py
    try:
        rrb = _get_rrb()
        decisions = rrb.aggregate_decisions(events_path)
    except Exception as exc:
        warnings.append(f"aggregate_decisions failed: {exc}")
        decisions = []

    # Phases
    phases = _extract_phases(events)

    # Halts
    halts = _extract_halts(events)

    # Follow-ups
    followups = _resolve_followups(slug, warnings)

    # Cost
    cost = _estimate_cost(run_dir, warnings)

    # Artifacts
    artifacts = _collect_artifacts(run_dir, plan_dir)

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": status,
        "run_brief_present": (run_dir / "run-brief.json").is_file(),
        "decisions": decisions,
        "phases": phases,
        "halts": halts,
        "followups": followups,
        "cost": cost,
        "artifacts": artifacts,
        "events_chars": events_chars,
        "warnings": warnings,
    }

    run_brief = _extract_run_brief(run_dir, warnings)
    if run_brief is not None:
        bundle["run_brief"] = run_brief
    transcripts_dir = run_dir / "transcripts"
    if transcripts_dir.is_dir():
        bundle["transcripts_dir"] = str(transcripts_dir)

    if slug:
        bundle["slug"] = slug
    plan_context = _extract_plan_context(run_dir, plan_dir, warnings)
    if plan_context is not None:
        bundle["plan_context"] = plan_context

    native_usage = _canonical_native_usage(run_dir)
    if native_usage is not None:
        bundle["native_usage"] = native_usage

    # Overnight special-case
    if _OVERNIGHT_RE.search(run_id):
        morning_report: Path | None = None
        if plan_dir is not None:
            candidate = plan_dir / "MORNING_REPORT.md"
            if candidate.is_file():
                morning_report = candidate
        if morning_report is not None:
            bundle["morning_report_path"] = str(morning_report)

    return bundle


# ── diff-backed bundle helpers ─────────────────────────────────────────────────

_FOLLOWUPS_NOTE_DIFF = "diff-backed target — follow-up sink not linked"


def _gh_available() -> bool:
    """Return True if `gh` CLI is on PATH and reachable."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def _gh_auth_ok() -> bool:
    """Return True if `gh auth status` exits 0 (authenticated)."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def _assemble_pr_bundle(descriptor: dict, warnings: list[str]) -> dict:
    """Assemble the context bundle for mode=pr.

    Calls ``gh pr view`` + ``gh pr diff``.  If gh is missing or unauth, returns
    a bundle with ``message`` describing the error.
    """
    pr_ref = descriptor.get("pr", "")
    base: dict = {
        "schema_version": SCHEMA_VERSION,
        "mode": "pr",
        "pr": pr_ref,
        "followups": [],
        "followups_note": _FOLLOWUPS_NOTE_DIFF,
        "diff_bytes": 0,
    }

    # Check gh availability
    try:
        gh_present = _gh_available()
    except OSError:
        gh_present = False

    if not gh_present:
        base["message"] = (
            "gh CLI not found on PATH. Install the GitHub CLI "
            "(https://cli.github.com/) and run `gh auth login` to use --pr mode."
        )
        base["warnings"] = warnings
        return base

    try:
        auth_ok = _gh_auth_ok()
    except OSError:
        auth_ok = False

    if not auth_ok:
        base["message"] = (
            "gh is installed but not authenticated. "
            "Run `gh auth login` then retry."
        )
        base["warnings"] = warnings
        return base

    # gh pr view
    rc_view, out_view, err_view = _run_cmd_capture(
        ["gh", "pr", "view", str(pr_ref),
         "--json", "title,body,state,commits,files"],
    )
    if rc_view != 0:
        warnings.append(f"gh pr view {pr_ref} failed (rc={rc_view}): {err_view}")
        base["message"] = (
            f"gh pr view failed for PR {pr_ref}: {err_view or '(no stderr)'}"
        )
        base["warnings"] = warnings
        return base

    try:
        pr_json = json.loads(out_view)
    except json.JSONDecodeError as exc:
        warnings.append(f"gh pr view JSON parse error: {exc}")
        pr_json = {}

    commits: list[dict] = pr_json.get("commits", []) or []
    # Normalise: keep only oid + message (consistent shape, tolerant of gh schema)
    commits_out: list[dict] = []
    for c in commits:
        if isinstance(c, dict):
            row: dict = {}
            if "oid" in c:
                row["oid"] = c["oid"]
            msg_obj = c.get("messageHeadline") or c.get("message") or ""
            if msg_obj:
                row["message"] = msg_obj
            commits_out.append(row)

    base["title"] = pr_json.get("title", "")
    base["body"] = pr_json.get("body", "")
    base["state"] = pr_json.get("state", "")
    base["commits"] = commits_out

    # gh pr diff
    rc_diff, out_diff, err_diff = _run_cmd_capture(
        ["gh", "pr", "diff", str(pr_ref)],
    )
    if rc_diff != 0:
        warnings.append(f"gh pr diff {pr_ref} failed (rc={rc_diff}): {err_diff}")
        base["diff"] = ""
    else:
        base["diff"] = out_diff

    base["diff_bytes"] = len(base.get("diff", "").encode("utf-8"))
    base["warnings"] = warnings
    return base


def _assemble_range_bundle(descriptor: dict, warnings: list[str], *, cwd: str | None = None) -> dict:
    """Assemble the context bundle for mode=range or mode=base.

    Handles three sub-cases:
    - ``range`` present: ``git log <range>`` + ``git diff <range>``
    - ``base`` present (no range): feature-branch diff ``git diff <base>...HEAD``
    - neither (shouldn't happen from resolver, but handled gracefully)
    """
    range_spec = descriptor.get("range")
    base_ref = descriptor.get("base")
    repo_cwd = cwd or str(REPO_ROOT)

    bundle: dict = {
        "schema_version": SCHEMA_VERSION,
        "mode": "range",
        "followups": [],
        "followups_note": _FOLLOWUPS_NOTE_DIFF,
        "commits": [],
        "diff": "",
        "diff_bytes": 0,
    }

    if range_spec:
        # git log oneline for the range
        rc_log, out_log, err_log = _run_cmd_capture(
            ["git", "log", "--oneline", range_spec],
            cwd=repo_cwd,
        )
        if rc_log != 0:
            warnings.append(f"git log --oneline {range_spec} failed (rc={rc_log}): {err_log}")
        else:
            for line in out_log.splitlines():
                parts = line.split(" ", 1)
                if parts:
                    row: dict = {"oid": parts[0]}
                    if len(parts) > 1:
                        row["message"] = parts[1]
                    bundle["commits"].append(row)

        # git diff for the range
        rc_diff, out_diff, err_diff = _run_cmd_capture(
            ["git", "diff", range_spec],
            cwd=repo_cwd,
        )
        if rc_diff != 0:
            warnings.append(f"git diff {range_spec} failed (rc={rc_diff}): {err_diff}")
        else:
            bundle["diff"] = out_diff

    elif base_ref:
        # Feature-branch diff: git log <base>...HEAD for commits
        rc_log, out_log, err_log = _run_cmd_capture(
            ["git", "log", "--oneline", f"{base_ref}...HEAD"],
            cwd=repo_cwd,
        )
        if rc_log != 0:
            warnings.append(f"git log --oneline {base_ref}...HEAD failed (rc={rc_log}): {err_log}")
        else:
            for line in out_log.splitlines():
                parts = line.split(" ", 1)
                if parts:
                    row = {"oid": parts[0]}
                    if len(parts) > 1:
                        row["message"] = parts[1]
                    bundle["commits"].append(row)

        # git diff <base>...HEAD
        rc_diff, out_diff, err_diff = _run_cmd_capture(
            ["git", "diff", f"{base_ref}...HEAD"],
            cwd=repo_cwd,
        )
        if rc_diff != 0:
            warnings.append(f"git diff {base_ref}...HEAD failed (rc={rc_diff}): {err_diff}")
        else:
            bundle["diff"] = out_diff

    else:
        warnings.append("range mode: neither 'range' nor 'base' in descriptor")

    bundle["diff_bytes"] = len(bundle["diff"].encode("utf-8"))
    bundle["warnings"] = warnings
    return bundle


def _assemble_worktree_bundle(warnings: list[str], *, cwd: str | None = None) -> dict:
    """Assemble the context bundle for mode=worktree.

    Combines unstaged (``git diff``) and staged (``git diff --staged``) diffs.
    Commits list reflects recent HEAD (``git log --oneline -10``).
    """
    repo_cwd = cwd or str(REPO_ROOT)

    bundle: dict = {
        "schema_version": SCHEMA_VERSION,
        "mode": "worktree",
        "followups": [],
        "followups_note": _FOLLOWUPS_NOTE_DIFF,
        "commits": [],
        "diff": "",
        "diff_bytes": 0,
    }

    # Recent commits (context, not the range — worktree has no explicit range)
    rc_log, out_log, err_log = _run_cmd_capture(
        ["git", "log", "--oneline", "-10"],
        cwd=repo_cwd,
    )
    if rc_log != 0:
        warnings.append(f"git log --oneline -10 failed (rc={rc_log}): {err_log}")
    else:
        for line in out_log.splitlines():
            parts = line.split(" ", 1)
            if parts:
                row: dict = {"oid": parts[0]}
                if len(parts) > 1:
                    row["message"] = parts[1]
                bundle["commits"].append(row)

    # Unstaged diff
    rc_us, out_us, err_us = _run_cmd_capture(["git", "diff"], cwd=repo_cwd)
    if rc_us != 0:
        warnings.append(f"git diff failed (rc={rc_us}): {err_us}")
        out_us = ""

    # Staged diff
    rc_st, out_st, err_st = _run_cmd_capture(["git", "diff", "--staged"], cwd=repo_cwd)
    if rc_st != 0:
        warnings.append(f"git diff --staged failed (rc={rc_st}): {err_st}")
        out_st = ""

    bundle["diff"] = out_us + out_st
    bundle["diff_bytes"] = len(bundle["diff"].encode("utf-8"))
    bundle["warnings"] = warnings
    return bundle



def _surface_target_label(descriptor: dict, mode: str) -> str:
    if mode == "pr":
        return f"PR #{descriptor.get('pr', '')}".strip()
    if mode == "range":
        if descriptor.get("range"):
            return str(descriptor["range"])
        if descriptor.get("base"):
            return f"{descriptor['base']}...HEAD"
    if mode == "worktree":
        return "current worktree"
    if mode in {"run", "slug"}:
        return str(descriptor.get("run_id") or descriptor.get("slug") or mode)
    return mode


def _attach_surface_map(
    bundle: dict,
    descriptor: dict,
    warnings: list[str],
    *,
    out_path: Path,
    surface_policy: str,
    tier: str,
    run_dir: Path | None = None,
) -> None:
    """Attach compact surface_map_* fields to a context bundle when policy allows."""
    mode = descriptor.get("mode", "")
    if surface_policy == "off":
        return

    out_dir = out_path.parent
    surface_path = out_dir / "surface-map.json"

    if _surface_policy_allows_refresh(surface_policy, tier, mode):
        if mode in {"pr", "range", "worktree"}:
            _attach_fresh_diff_surface(
                bundle,
                warnings,
                out_dir=out_dir,
                repo_root=REPO_ROOT,
                diff_text=str(bundle.get("diff") or ""),
                target=_surface_target_label(descriptor, mode),
                source="diff_context",
            )
            return
        if mode in {"run", "slug"}:
            _attach_fresh_diff_surface(
                bundle,
                warnings,
                out_dir=out_dir,
                repo_root=REPO_ROOT,
                diff_text=_current_worktree_diff(warnings),
                target=f"report-time current repo state for {_surface_target_label(descriptor, mode)}",
                source="report_time_current_repo",
            )
            return

    if mode in {"run", "slug"} and run_dir is not None:
        roots = [run_dir]
        found = _attach_existing_surface(
            bundle,
            warnings,
            roots=roots,
            source="historical_run",
            exclude=None,
        )
        if not found and run_dir.parent.name == "archive":
            found = _attach_existing_surface(
                bundle,
                warnings,
                roots=[run_dir.parent.parent],
                source="historical_plan",
                exclude=None,
                recursive=False,
            )
        if not found:
            _attach_surface_skipped(bundle, "no existing surface-map.json artifact found for historical report")
        return

    if mode in {"pr", "range", "worktree"}:
        found = _attach_existing_surface(
            bundle,
            warnings,
            roots=[out_dir],
            source="diff_context",
            exclude=None,
        )
        if not found:
            _attach_surface_skipped(bundle, "surface policy does not allow fresh mapping and no existing diff surface-map.json was found")


# ── bundle assembly ────────────────────────────────────────────────────────────

def assemble_bundle(
    descriptor: dict,
    *,
    out_path: Path | None,
    base: str | None,
    surface_policy: str = "off",
    tier: str = "standard",
    resume_context_path: Path | None = None,
) -> int:
    """Assemble the full context bundle and write it to out_path.

    T002: implements run/slug bundle assembly.
    T003: implements pr/range/base/worktree bundle assembly.
    """
    mode = descriptor.get("mode", "")
    warnings: list[str] = []
    selected_resume_context = _resolve_selected_resume_context(resume_context_path, warnings, descriptor)
    if resume_context_path is not None and selected_resume_context is None:
        print(
            "report-context.py: selected resume-context is missing, invalid, or still needs selection",
            file=sys.stderr,
        )
        return 2


    if mode in ("run", "slug"):
        run_dir = _resolve_run_dir(descriptor, warnings)
        if run_dir is None:
            # Could not resolve run dir — produce a minimal error bundle
            bundle: dict = {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "status": "unknown",
                "degraded": "no_run_dir",
                "decisions": [],
                "phases": [],
                "halts": [],
                "followups": [],
                "cost": {},
                "artifacts": [],
                "events_chars": 0,
                "warnings": warnings,
            }
        else:
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        # Determine output path
        if out_path is None:
            out_path = Path(run_dir / "context.json") if run_dir else Path("context.json")

        _attach_selected_resume_context(bundle, selected_resume_context)
        _attach_surface_map(
            bundle,
            descriptor,
            warnings,
            out_path=out_path,
            surface_policy=surface_policy,
            tier=tier,
            run_dir=run_dir,
        )
        _write_bundle(bundle, out_path)
        print(str(out_path))
        return 0

    if mode == "pr":
        bundle = _assemble_pr_bundle(descriptor, warnings)
        if out_path is None:
            out_path = Path("context.json")
        _attach_selected_resume_context(bundle, selected_resume_context)
        _attach_surface_map(
            bundle,
            descriptor,
            warnings,
            out_path=out_path,
            surface_policy=surface_policy,
            tier=tier,
        )
        _write_bundle(bundle, out_path)
        print(str(out_path))
        # Return 1 if there's an error message (gh missing / unauth)
        return 1 if "message" in bundle else 0

    if mode == "range":
        bundle = _assemble_range_bundle(descriptor, warnings)
        if out_path is None:
            out_path = Path("context.json")
        _attach_selected_resume_context(bundle, selected_resume_context)
        _attach_surface_map(
            bundle,
            descriptor,
            warnings,
            out_path=out_path,
            surface_policy=surface_policy,
            tier=tier,
        )
        _write_bundle(bundle, out_path)
        print(str(out_path))
        return 0

    if mode == "worktree":
        bundle = _assemble_worktree_bundle(warnings, cwd=descriptor.get("worktree_path"))
        if out_path is None:
            out_path = Path("context.json")
        _attach_selected_resume_context(bundle, selected_resume_context)
        _attach_surface_map(
            bundle,
            descriptor,
            warnings,
            out_path=out_path,
            surface_policy=surface_policy,
            tier=tier,
        )
        _write_bundle(bundle, out_path)
        print(str(out_path))
        return 0

    # error / ambiguous / not_found
    print(
        f"report-context.py: cannot assemble bundle for mode={mode!r}: "
        + descriptor.get("message", ""),
        file=sys.stderr,
    )
    return 2


def _write_bundle(bundle: dict, out_path: Path) -> None:
    """Write bundle JSON atomically to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2)
    tmp.rename(out_path)


def _parse_report_positionals(tokens: list[str], flag_tier: str | None) -> tuple[str | None, str, str | None]:
    """Extract optional target, tier, and since-ref from free-form positional tokens."""
    tier = flag_tier or "standard"
    target_parts: list[str] = []
    base_from_since: str | None = None
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in TIERS:
            tier = tok
            idx += 1
            continue
        if tok == "since" and idx + 1 < len(tokens):
            base_from_since = tokens[idx + 1]
            idx += 2
            continue
        target_parts.append(tok)
        idx += 1

    target = " ".join(target_parts).strip() or None
    return target, tier, base_from_since


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a z-harness report target and assemble the context bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "tokens",
        nargs="*",
        help="Target and optional tier: run-id, slug, PR, range, current, changes, or since <ref>.",
    )
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="Print resolution descriptor JSON and exit (no bundle assembly).",
    )
    parser.add_argument("--run", dest="flag_run", default=None, metavar="ID", help="Explicit run-id.")
    parser.add_argument("--slug", dest="flag_slug", default=None, metavar="S", help="Explicit plan slug.")
    parser.add_argument("--pr", dest="flag_pr", default=None, metavar="N|URL", help="Pull request number or URL.")
    parser.add_argument("--range", dest="flag_range", default=None, metavar="A..B", help="Git commit range.")
    parser.add_argument("--base", dest="flag_base", default=None, metavar="REF", help="Base ref for feature-branch diff.")
    parser.add_argument("--worktree", dest="flag_worktree", default=None, metavar="PATH", help="Explicit worktree path.")
    parser.add_argument("--resume-context", dest="resume_context", default=None, metavar="PATH", help="Attach selected /z-resume context packet.")
    parser.add_argument("--out", "--save", dest="out", default=None, metavar="PATH", help="Output path for bundle JSON.")
    parser.add_argument("--tier", choices=sorted(TIERS), default=None, help="Report depth tier.")
    parser.add_argument("--surface", choices=sorted(SURFACE_POLICIES), default="auto", help="Surface-map policy.")

    args = parser.parse_args(argv)

    target, tier, base_from_since = _parse_report_positionals(args.tokens, args.tier)
    flag_base = args.flag_base or base_from_since

    descriptor = resolve_target(
        target=target,
        flag_run=args.flag_run,
        flag_slug=args.flag_slug,
        flag_pr=args.flag_pr,
        flag_range=args.flag_range,
        flag_base=flag_base,
        flag_worktree=args.flag_worktree,
    )

    if args.resolve_only:
        # For run/slug modes, resolve and inject run_dir into the descriptor so
        # callers (e.g. z-report.md writing REPORT.md) can read RUN_DIR directly.
        mode = descriptor.get("mode", "")
        if mode in ("run", "slug"):
            warnings: list[str] = []
            run_dir = _resolve_run_dir(descriptor, warnings)
            if run_dir is not None:
                descriptor["run_dir"] = str(run_dir)
        print(json.dumps(descriptor, indent=2))
        # Exit 1 for error/not_found, 2 for ambiguous, 0 otherwise
        if mode == "error":
            return 1
        if mode in ("ambiguous", "not_found"):
            return 2
        return 0

    # Full bundle assembly (T002/T003/T006)
    out_path = Path(args.out) if args.out else None
    return assemble_bundle(
        descriptor,
        out_path=out_path,
        base=flag_base,
        surface_policy=args.surface,
        tier=tier,
        resume_context_path=Path(args.resume_context) if args.resume_context else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
