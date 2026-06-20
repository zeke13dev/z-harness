#!/usr/bin/env python3
"""report-context.py — Resolve a z-harness report target and assemble the context bundle.

Usage:
    report-context.py [--resolve-only] [target]
        [--run ID] [--slug S] [--pr N|URL] [--range A..B] [--base REF]
        [--out PATH]

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


def resolve_target(
    *,
    target: str | None,
    flag_run: str | None,
    flag_slug: str | None,
    flag_pr: str | None,
    flag_range: str | None,
    flag_base: str | None,
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
    }
    active_typed = {k: v for k, v in typed_flags.items() if v is not None}
    if len(active_typed) > 1:
        names = ", ".join(f"--{k}" for k in sorted(active_typed))
        return _descriptor(
            "error",
            message=(
                f"Conflicting flags: {names}. "
                "Supply at most one of --run/--slug/--pr/--range."
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
    artifact_names = ["SPEC.md", "PLAN.md", "TASKS.md", "FIX.md", "DEBUG.md",
                      "MORNING_REPORT.md", "run-brief.json", "REPORT.md"]
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
                matches = sorted(matches)  # deterministic order
                if matches:
                    if len(matches) > 1:
                        warnings.append(
                            f"Multiple archive dirs found for run_id={run_id!r}; "
                            f"using {matches[0]}"
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
                        (d for d in archive_dir.iterdir() if d.is_dir()),
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
                    (d for d in archive_dir.iterdir() if d.is_dir()),
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


# ── bundle assembly ────────────────────────────────────────────────────────────

def assemble_bundle(descriptor: dict, *, out_path: Path | None, base: str | None) -> int:
    """Assemble the full context bundle and write it to out_path.

    T002: implements run/slug bundle assembly.
    T003: implements pr/range/base/worktree bundle assembly.
    """
    mode = descriptor.get("mode", "")
    warnings: list[str] = []

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

        _write_bundle(bundle, out_path)
        print(str(out_path))
        return 0

    if mode == "pr":
        bundle = _assemble_pr_bundle(descriptor, warnings)
        if out_path is None:
            out_path = Path("context.json")
        _write_bundle(bundle, out_path)
        print(str(out_path))
        # Return 1 if there's an error message (gh missing / unauth)
        return 1 if "message" in bundle else 0

    if mode == "range":
        bundle = _assemble_range_bundle(descriptor, warnings)
        if out_path is None:
            out_path = Path("context.json")
        _write_bundle(bundle, out_path)
        print(str(out_path))
        return 0

    if mode == "worktree":
        bundle = _assemble_worktree_bundle(warnings)
        if out_path is None:
            out_path = Path("context.json")
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


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a z-harness report target and assemble the context bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target: run-id, slug, PR (#N / URL), or range (A..B).",
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
    parser.add_argument("--out", default=None, metavar="PATH", help="Output path for bundle JSON.")

    args = parser.parse_args(argv)

    descriptor = resolve_target(
        target=args.target,
        flag_run=args.flag_run,
        flag_slug=args.flag_slug,
        flag_pr=args.flag_pr,
        flag_range=args.flag_range,
        flag_base=args.flag_base,
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

    # Full bundle assembly (T002/T003)
    out_path = Path(args.out) if args.out else None
    return assemble_bundle(descriptor, out_path=out_path, base=args.flag_base)


if __name__ == "__main__":
    raise SystemExit(main())
