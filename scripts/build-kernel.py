#!/usr/bin/env python3
"""
build-kernel.py — compile a KERNEL.md for a scope (D3, the compiler).

Assembles the single artifact every behavioral agent reads: the authority
precedence boundary, the skill dispatch index, and the approved-axiom list,
selected/sorted and truncated to a character budget.

CLI:
  build-kernel.py --scope <global|project> [--repo-root <p>] [--out <path>] [--budget <chars>]

Output path default:
  global  -> ${XDG_CONFIG_HOME:-~/.config}/z-harness/KERNEL.md
  project -> <git-root>/.z-harness/KERNEL.md

Invariants honored:
  R1 — graph validation uses the ONE shared validate_graph() from axiom-store.py;
       approved axioms are loaded through axiom-store.py's `list` subcommand so
       merge + project-shadow semantics are identical to approve.
  R2 — a graph-invalid APPROVED record is dropped AND emits a loud
       `axiom_integrity_warning` event (not a silent skip); the kernel still
       compiles without it. drop_count is recorded in the header.
  R5 — header carries source_hash + n_axioms + drop_count + compiler_version.
  R6 — same inputs -> byte-identical body AND identical source_hash; generated_at
       is the only volatile field and lives OUTSIDE the hashed region.

Stdlib only (mirrors config.py / axiom-store.py conventions).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------

COMPILER_VERSION = "1"

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT_OF_PLUGIN = _SCRIPTS_DIR.parent
_AXIOM_STORE = str(_SCRIPTS_DIR / "axiom-store.py")
_LOG_EVENT = str(_SCRIPTS_DIR / "log-event.sh")
_CONFIG_PY = str(_SCRIPTS_DIR / "config.py")

# Width of the generated_at value (ISO-8601 UTC: "YYYY-MM-DDTHH:MM:SSZ").
# It is the ONE volatile field; its width is fixed, so budget accounting uses a
# placeholder of this exact length to match the real rendered kernel byte-for-byte.
_GENERATED_AT_WIDTH = len("0000-00-00T00:00:00Z")  # 20

# Authority-precedence block, copied VERBATIM from SPEC.md "Layer authority
# boundary" so every agent that reads the kernel learns axioms are advisory.
_AUTHORITY_PRECEDENCE = (
    "explicit user instruction  >  hard safety gates  >  config/env (explicit)\n"
    "   >  routing-preference memory  >  approved axioms (project > global)  >  persona / built-in defaults"
)


# ---------------------------------------------------------------------------
# Import sibling scripts (hyphenated filenames require importlib)
# ---------------------------------------------------------------------------

def _import_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_axiom_store = _import_module("axiom_store", _AXIOM_STORE)
_skill_index = _import_module("build_skill_index", str(_SCRIPTS_DIR / "build-skill-index.py"))

# R1: the ONE shared graph validator.
validate_graph = _axiom_store.validate_graph
# R1: identical load semantics to approve — full active set (all statuses, merged
# global+project, project shadows global) so demoted supersedes targets are present.
_load_active_set = _axiom_store._load_active_set
# Reused for default project/global path resolution (mirrors axiom-store).
build_skill_index = _skill_index.build_skill_index


# ---------------------------------------------------------------------------
# Path resolution (mirrors axiom-store.py)
# ---------------------------------------------------------------------------

def _xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg)


def _default_out_path(scope: str, repo_root: str | None) -> Path:
    if scope == "global":
        return _xdg_config_home() / "z-harness" / "KERNEL.md"
    root = _axiom_store._get_project_root(repo_root)
    if not root:
        print("ERROR: cannot resolve project root for scope=project", file=sys.stderr)
        sys.exit(1)
    return Path(root) / ".z-harness" / "KERNEL.md"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _load_budget(explicit: int | None) -> int:
    """Return the char budget: --budget wins, else config axioms.kernel_budget_chars."""
    if explicit is not None:
        return explicit
    try:
        result = subprocess.run(
            [sys.executable, _CONFIG_PY, "get", "axioms.kernel_budget_chars"],
            capture_output=True, text=True, check=True,
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"WARN: could not read axioms.kernel_budget_chars ({exc}); using 6000",
              file=sys.stderr)
        return 6000


def _load_approved_axioms(scope: str, repo_root: str | None) -> list[dict]:
    """
    Load approved axioms for the scope via axiom-store.py's `list` subcommand
    (SPEC Compile step 2). This guarantees IDENTICAL merge + project-shadow
    semantics to approve (R1) — project scope merges global+project and project
    shadows global on the same id, after which the --status approved filter runs.
    """
    cmd = [sys.executable, _AXIOM_STORE, "list", "--status", "approved"]
    if scope == "project":
        # project scope == merged set (global+project), project shadows global.
        # Passing no --scope to `list` triggers the merge; we then keep the set.
        pass
    else:
        cmd += ["--scope", scope]
    if repo_root:
        cmd += ["--repo-root", repo_root]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else []


# ---------------------------------------------------------------------------
# Graph filtering (R1 + R2)
# ---------------------------------------------------------------------------

def _filter_graph_valid(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Run the shared validate_graph over the approved set. If it fails, drop the
    record(s) named in the errors and re-validate until the set is clean.

    Returns (kept_records, dropped_records). Each dropped record is excluded
    from the kernel and (by the caller) reported via an axiom_integrity_warning
    event (R2). Under normal operation approve has already graph-validated, so a
    drop here signals tampering or a bug — never a silent skip.
    """
    kept = list(records)
    dropped: list[dict] = []

    while True:
        result = validate_graph(kept)
        if result["ok"]:
            break
        offending_ids: set[str] = set()
        for err in result["errors"]:
            # Error strings are "<id>: ..." or mention "<id>" / "<target>".
            for rec in kept:
                rid = rec.get("id")
                if rid and rid in err:
                    offending_ids.add(rid)
        if not offending_ids:
            # No identifiable record to drop — drop all to avoid an infinite
            # loop and a corrupt kernel; the warnings will surface the IDs.
            offending_ids = {r.get("id") for r in kept if r.get("id")}
        new_kept = []
        for rec in kept:
            if rec.get("id") in offending_ids:
                dropped.append(rec)
            else:
                new_kept.append(rec)
        if len(new_kept) == len(kept):
            break  # nothing removed; bail to avoid infinite loop
        kept = new_kept

    return kept, dropped


# ---------------------------------------------------------------------------
# Selection / sort (D3) + rendering
# ---------------------------------------------------------------------------

def _repo_discipline(repo_root: str | None) -> str | None:
    """
    The repo's configured discipline, if any, used for the applicability
    dimension. No such config key exists today, so this is neutral (None) and
    the applicability sort dimension becomes a constant — preserving D3's
    "if a repo discipline is configured" clause without inventing a key.
    """
    return None


def _sort_key(rec: dict, discipline: str | None):
    # scope: project=0, global=1
    scope_rank = 0 if rec.get("scope") == "project" else 1
    # applicability: 0 if the axiom's discipline matches the repo discipline,
    # else 1. Neutral (constant 0) when no repo discipline is configured.
    if discipline is not None:
        applic_rank = 0 if rec.get("discipline") == discipline else 1
    else:
        applic_rank = 0
    # confidence desc -> negate
    confidence = rec.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    # recency desc: created_at string sorts lexicographically for ISO-8601;
    # negate by sorting descending via reverse-comparable tuple. We invert by
    # using a key that sorts later strings first.
    created_at = rec.get("created_at") or ""
    # Final tiebreak: id (stable, deterministic).
    rid = rec.get("id") or ""
    return (scope_rank, applic_rank, -confidence, _DescStr(created_at), rid)


class _DescStr:
    """Wrap a string so it sorts in descending order within an ascending sort."""

    __slots__ = ("s",)

    def __init__(self, s: str):
        self.s = s

    def __lt__(self, other: "_DescStr") -> bool:
        return self.s > other.s

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _DescStr) and self.s == other.s


def _render_axiom(rec: dict) -> str:
    rid = rec.get("id", "ax-????????")
    statement = rec.get("statement", "")
    scope = rec.get("scope", "")
    confidence = rec.get("confidence", "")
    line = f"- [{rid}] {statement}   (scope: {scope}, confidence: {confidence})"
    bc = rec.get("boundary_conditions") or []
    ce = rec.get("counterexamples") or []
    extras = []
    if bc:
        extras.append(f"boundary: {'; '.join(bc)}")
    if ce:
        extras.append(f"counter: {'; '.join(ce)}")
    if extras:
        line += "\n  " + "   ".join(extras)
    return line


def _rendered_size(scope: str, source_hash: str, drop_count: int,
                   skill_text: str, included: list[dict],
                   total_recs: int) -> int:
    """
    Exact char length of the kernel as it will be written, using a fixed-width
    generated_at placeholder (the only volatile field, width-stable). This is the
    SAME render path used for the real output, so the count matches byte-for-byte
    apart from the generated_at value itself. n_axioms and the omitted-count
    comment both vary with `included`, so they are computed accurately here.
    """
    omitted = total_recs - len(included)
    text = _render_kernel(
        scope, "0" * _GENERATED_AT_WIDTH, source_hash,
        len(included), drop_count, skill_text, included, omitted,
    )
    return len(text)


def _select_within_budget(sorted_recs: list[dict], skill_text: str,
                          scope: str, source_hash: str, drop_count: int,
                          budget: int) -> tuple[list[dict], int]:
    """
    Select axioms in sort order so the FINAL rendered kernel (with accurate
    n_axioms and omitted-count) is <= budget. We do a "select, then verify-and-
    trim" pass: greedily include in order, then re-render the exact kernel and
    drop the last axiom until the real rendered size fits the budget. This avoids
    the overhead-underestimation bugs of a static-overhead approximation (the
    generated_at width and the n_axioms/heading widths now match the real output).

    The first axiom is always kept even if it alone exceeds budget (so the list is
    never empty when at least one axiom exists).

    Returns (included_records, omitted_count).
    """
    total_recs = len(sorted_recs)
    if total_recs == 0:
        return [], 0

    # Greedy first pass: add axioms while the exact rendered kernel fits.
    included: list[dict] = []
    for rec in sorted_recs:
        candidate = included + [rec]
        size = _rendered_size(scope, source_hash, drop_count,
                              skill_text, candidate, total_recs)
        if included and size > budget:
            break
        included.append(rec)

    # Verify-and-trim: re-render with the accurate counts and drop the last
    # axiom until the real size fits (always keep at least the first).
    while len(included) > 1:
        size = _rendered_size(scope, source_hash, drop_count,
                              skill_text, included, total_recs)
        if size <= budget:
            break
        included.pop()

    omitted = total_recs - len(included)
    return included, omitted


# ---------------------------------------------------------------------------
# Hash (R6) + render
# ---------------------------------------------------------------------------

def _compute_source_hash(skill_text: str, approved_sorted: list[dict]) -> str:
    """
    sha256 over (skill-index text + sorted approved-axiom (id+statement) pairs).
    NO timestamp is included (R6) — same inputs => identical hash across runs.
    """
    h = hashlib.sha256()
    h.update(skill_text.encode("utf-8"))
    for rec in approved_sorted:
        h.update(b"\x00")
        h.update((rec.get("id") or "").encode("utf-8"))
        h.update(b"\x01")
        h.update((rec.get("statement") or "").encode("utf-8"))
    return h.hexdigest()


def _render_kernel(scope: str, generated_at: str, source_hash: str,
                   n_axioms: int, drop_count: int, skill_text: str,
                   included: list[dict], omitted: int) -> str:
    """Render the full KERNEL.md text per the SPEC structure block."""
    parts: list[str] = []
    parts.append("<!-- z-harness-kernel GENERATED — do not edit by hand -->")
    parts.append("## z-harness kernel")
    parts.append(f"generated_at: {generated_at}   |   scope: {scope}")
    parts.append(
        f"source_hash: {source_hash[:12]}   |   n_axioms: {n_axioms}   "
        f"|   drop_count: {drop_count}   |   compiler_version: {COMPILER_VERSION}"
    )
    parts.append("")
    parts.append("### Authority precedence")
    parts.append(_AUTHORITY_PRECEDENCE)
    parts.append("")
    parts.append("### Skill dispatch index")
    parts.append(skill_text.rstrip("\n"))
    parts.append("")
    parts.append(f"### Approved axioms ({n_axioms})")
    for rec in included:
        parts.append(_render_axiom(rec))
    if omitted:
        parts.append(f"<!-- {omitted} axioms omitted for budget -->")
    return "\n".join(parts) + "\n"


def _body_below_header(kernel_text: str) -> str:
    """
    Return the kernel body BELOW the volatile generated_at line (R6 idempotency
    target). Everything from the source_hash line down is byte-stable for
    identical inputs; generated_at is the only volatile field.
    """
    lines = kernel_text.splitlines(keepends=True)
    # Drop the generated_at line (3rd line: comment, '## z-harness kernel',
    # 'generated_at: ...'). Keep from the source_hash line onward.
    out = []
    for line in lines:
        if line.startswith("generated_at:"):
            continue
        out.append(line)
    return "".join(out)


# ---------------------------------------------------------------------------
# Atomic write (mirrors axiom-store._atomic_write but for text)
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=f".tmp.{os.getpid()}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Event emission (delegates to log-event.sh — one event store, DRY)
# ---------------------------------------------------------------------------

def _emit_event(kind: str, payload: dict) -> None:
    run = os.environ.get("Z_HARNESS_RUN", "kernel-build")
    try:
        subprocess.run(
            ["bash", _LOG_EVENT, run, kind, json.dumps(payload, separators=(",", ":"))],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        print(f"WARN: could not emit {kind} event: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

def compile_kernel(scope: str, repo_root: str | None, out_path: Path,
                   budget: int) -> dict:
    """Compile and atomically write KERNEL.md. Returns a summary dict."""
    # 1. Skill index.
    skill_repo_root = Path(repo_root) if repo_root else _REPO_ROOT_OF_PLUGIN
    skill_text = build_skill_index(skill_repo_root)

    # 2. Load the FULL active set (all statuses, merged global+project, project
    # shadows global) — this is R1's "identical load semantics" to approve.
    # Demoted supersedes targets (now in rejected/) are present in this set, so
    # validate_graph check 1 (referential integrity) does not false-fire on a
    # just-approved axiom whose superseded target is in rejected/.
    full_active = _load_active_set(scope, repo_root)

    # 3. Graph-validate over the FULL active set (R1 + R2).
    # Only approved records can reach the kernel; the wider set is validation context.
    kept_full, dropped_full = _filter_graph_valid(full_active)

    # The dropped records here are from the full active set; we only emit
    # integrity warnings for dropped APPROVED records — candidate/rejected drops
    # are not anomalies (they were never in the kernel to begin with).
    dropped_approved = [r for r in dropped_full if r.get("status") == "approved"]
    drop_count = len(dropped_approved)
    for rec in dropped_approved:
        _emit_event("axiom_integrity_warning", {
            "scope": scope,
            "axiom_id": rec.get("id"),
            "reason": "approved record failed graph validation at compile time; "
                      "excluded from kernel (signals tampering or a bug)",
        })

    # Extract only the APPROVED records from the kept set — these are the ones
    # rendered + hashed. Candidates and rejected records are validation context only.
    approved_kept = [r for r in kept_full if r.get("status") == "approved"]

    # 4. Sort (D3).
    discipline = _repo_discipline(repo_root)
    sorted_recs = sorted(approved_kept, key=lambda r: _sort_key(r, discipline))

    # 5. source_hash over (skill text + sorted approved id+statement). R6.
    # Computed BEFORE selection because the rendered header (and thus the exact
    # budget accounting) embeds the 12-char source_hash prefix.
    source_hash = _compute_source_hash(skill_text, sorted_recs)

    # 6. Budget selection against the EXACT rendered size (header width, n_axioms
    # heading, omitted-count comment, and fixed-width generated_at all accounted).
    included, omitted = _select_within_budget(
        sorted_recs, skill_text, scope, source_hash, drop_count, budget
    )
    n_axioms = len(included)

    # 7. Render with the real (volatile) generated_at value. Its width matches the
    # placeholder used during selection, so the written kernel is <= budget.
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    kernel_text = _render_kernel(
        scope, generated_at, source_hash, n_axioms, drop_count,
        skill_text, included, omitted,
    )

    # 8. Atomic write.
    _atomic_write_text(out_path, kernel_text)

    # 9. Emit kernel_built event.
    _emit_event("kernel_built", {
        "scope": scope,
        "n_axioms": n_axioms,
        "n_omitted": omitted,
        "drop_count": drop_count,
        "source_hash": source_hash[:12],
    })

    return {
        "scope": scope,
        "out": str(out_path),
        "n_axioms": n_axioms,
        "n_omitted": omitted,
        "drop_count": drop_count,
        "source_hash": source_hash[:12],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-kernel.py",
        description="Compile a KERNEL.md for a scope.",
    )
    parser.add_argument("--scope", required=True, choices=["global", "project"])
    parser.add_argument("--repo-root", dest="repo_root", default=None)
    parser.add_argument("--out", dest="out", default=None,
                        help="Output path (default: scope-resolved KERNEL.md)")
    parser.add_argument("--budget", type=int, default=None,
                        help="Max kernel body chars (default: axioms.kernel_budget_chars)")
    parser.add_argument(
        "--print-hash",
        dest="print_hash",
        action="store_true",
        default=False,
        help=(
            "Non-mutating mode: load approved axioms + build skill index, "
            "compute source_hash via _compute_source_hash, print ONLY the "
            "12-hex prefix to stdout, and exit WITHOUT writing KERNEL.md. "
            "Byte-identical to the source_hash: value the compiler would embed."
        ),
    )
    return parser


def print_hash(scope: str, repo_root: str | None) -> None:
    """
    Non-mutating mode: compute and print the source_hash the compiler would
    embed for the given scope/repo_root, then exit.  Reuses the EXISTING
    _compute_source_hash helper and the EXISTING load helpers verbatim.
    Does NOT write KERNEL.md and does NOT emit any event.
    """
    skill_repo_root = Path(repo_root) if repo_root else _REPO_ROOT_OF_PLUGIN
    skill_text = build_skill_index(skill_repo_root)
    full_active = _load_active_set(scope, repo_root)
    kept_full, _dropped = _filter_graph_valid(full_active)
    approved_kept = [r for r in kept_full if r.get("status") == "approved"]
    discipline = _repo_discipline(repo_root)
    sorted_recs = sorted(approved_kept, key=lambda r: _sort_key(r, discipline))
    source_hash = _compute_source_hash(skill_text, sorted_recs)
    print(source_hash[:12])


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.print_hash:
        print_hash(args.scope, args.repo_root)
        return
    out_path = Path(args.out) if args.out else _default_out_path(args.scope, args.repo_root)
    budget = _load_budget(args.budget)
    summary = compile_kernel(args.scope, args.repo_root, out_path, budget)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
