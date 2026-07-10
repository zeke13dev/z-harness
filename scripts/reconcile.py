#!/usr/bin/env python3
"""
scripts/reconcile.py — Classification helpers for /z-reconcile.

Purpose:
  Provides testable, side-effect-free classifiers for worktree state and plan
  state, plus a cross-reference join that flags consistency problems across
  worktrees, plans, the active-plan registry, claim locks, and uncommitted work.

Design decisions:
  - classify_worktree and classify_plan perform no git, filesystem, or registry
    I/O: they accept pre-collected plain dataclasses/dicts and return a
    classification + recommended action. The collection layer (T001's command
    body) is responsible for gathering raw facts. Note: classify_plan reads
    wall-clock time (datetime.now) to evaluate staleness — it is not strictly
    pure in the functional sense, but performs no external I/O.
  - The collection layer must resolve the default branch dynamically (e.g. via
    `git symbolic-ref refs/remotes/origin/HEAD`) and pass it in. This module
    never hardcodes "main" inside a classifier.
  - Staleness for plans uses max(latest events.jsonl timestamp for the slug,
    artifact mtime), not raw directory age, so plans that have had recent
    activity are not mis-classified as stale.
  - Threshold parameters (staleness_days) are explicit keyword arguments with
    defaults so they are testable without monkey-patching.

Public surface (importable API):
  Dataclasses:
    WorktreeFacts       — pre-collected facts about a single git worktree
    PlanFacts           — pre-collected facts about a single plan directory
    RegistryRecord      — a record from active-plan-registry.py list --json
    ClaimLockFacts      — facts about a single claim lock file
    CrossRefInput       — bundle of all collections passed to cross_ref_join
    CrossRefFlags       — four boolean flags returned by cross_ref_join

  Classifiers:
    classify_worktree(facts: WorktreeFacts) -> tuple[str, str]
    classify_plan(facts: PlanFacts, staleness_days: int = 14) -> tuple[str, str]

  Join:
    cross_ref_join(inp: CrossRefInput) -> CrossRefFlags

  Constants:
    WORKTREE_CLASSES   — frozenset of all valid worktree class strings
    PLAN_CLASSES       — frozenset of all valid plan class strings

CLI (for command body to call without importing):
  python3 scripts/reconcile.py --help
  python3 scripts/reconcile.py classify-worktree --json <facts-json>
  python3 scripts/reconcile.py classify-plan [--staleness-days N] --json <facts-json>
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── constants ──────────────────────────────────────────────────────────────────

# Exactly the six worktree classes from the INTENT spec.
WORKTREE_CLASSES: frozenset[str] = frozenset({
    "dead",             # clean tree + (HEAD ancestor of default OR patch-identical to default)
    "dirty",            # uncommitted changes
    "detached",         # detached HEAD
    "merged-uncertain", # branch appears merged but evidence is ambiguous (squash, etc.)
    "unknown-remote",   # remote unreachable; unpushed-check was skipped
    "active",           # none of the above / not safe to prune
})

# Exactly the four plan classes from the INTENT spec.
PLAN_CLASSES: frozenset[str] = frozenset({
    "precontext-only-aged",      # only INTENT/precontext artifacts, past staleness threshold
    "tasks-complete-unmerged",   # all TASKS [x] but no merge/commit evidence
    "in-progress",               # active work, not stale
    "stale-in-progress",         # in-progress but staleness threshold exceeded
})

_DEFAULT_STALENESS_DAYS = 14


# ── dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class WorktreeFacts:
    """Pre-collected facts about a single git worktree.

    All I/O is done by the collection layer; this dataclass holds the results.
    Fields are intentionally flat booleans/strings so classifiers are trivially
    unit-testable without any subprocess side effects.

    Attributes:
        path:              Absolute path to the worktree on disk.
        branch:            Branch name, or None if detached HEAD.
        head_sha:          Current HEAD commit SHA (or '' if unresolvable).
        is_detached:       True when HEAD is detached (no branch reference).
        has_uncommitted:   True when the working tree is dirty (tracked or untracked changes).
        has_unpushed:      True when there are local commits not present on the remote.
                           Set to None when remote was unreachable (unknown-remote case).
        is_head_ancestor_of_default:
                           True when HEAD is a commit-ancestry ancestor of the resolved
                           default branch. Set to None when the check could not run.
        default_branch:    The dynamically-resolved default branch name (e.g. 'main').
        remote_reachable:  False when the remote was unreachable during collection.
        merge_evidence:    'merged' | 'merged-uncertain' | 'not-merged' | 'unknown'.
                           'merged-uncertain' is used for squash-merge evidence.
        patch_identical_to_default:
                           True when HEAD's patch content is identical to the default
                           branch's tip (offline `git rev-list --cherry-pick
                           --right-only --count <default>...<HEAD> == 0` proof, computed
                           by the collection layer). This is a stronger, offline proof
                           of "already merged" than commit-ancestry: it also catches
                           squash merges and branches that were never pushed. None when
                           the check could not run.
    """
    path: str
    branch: str | None
    head_sha: str
    is_detached: bool
    has_uncommitted: bool
    has_unpushed: bool | None      # None = remote unreachable, skip check
    is_head_ancestor_of_default: bool | None  # None = check could not run
    default_branch: str
    remote_reachable: bool
    merge_evidence: str = "unknown"  # merged | merged-uncertain | not-merged | unknown
    patch_identical_to_default: bool | None = None  # None = check could not run

    def __post_init__(self) -> None:
        """Fail fast if merge_evidence is not a recognised value.

        This catches bad JSON inputs at construction time rather than
        silently allowing them to propagate into classification logic.
        """
        _VALID_MERGE_EVIDENCE = frozenset({"merged", "merged-uncertain", "not-merged", "unknown"})
        if self.merge_evidence not in _VALID_MERGE_EVIDENCE:
            raise ValueError(
                f"Unrecognised merge_evidence {self.merge_evidence!r}; "
                f"expected one of {sorted(_VALID_MERGE_EVIDENCE)}"
            )


@dataclass
class PlanFacts:
    """Pre-collected facts about a single plan directory.

    Attributes:
        slug:              The plan slug (directory name under plans/).
        path:              Absolute path to the plan directory.
        has_tasks_file:    True when a TASKS.md file is present.
        all_tasks_done:    True when every task in TASKS.md is marked [x].
                           None when has_tasks_file is False.
        has_only_precontext:
                           True when the only artifacts present are INTENT.md /
                           precontext files (no TASKS.md, no LEDGER.md, no events.jsonl).
        has_merge_evidence:
                           True when any of: a merge commit touching the plan slug is
                           reachable in git history, a 'merged' or 'archived' sentinel
                           file exists, or events.jsonl contains a 'plan_merged' event.
        latest_activity_ts:
                           Unix timestamp (float) of the most recent activity signal:
                           max(latest events.jsonl entry ts for this slug, artifact mtime).
                           None when no activity signal is available.
        is_abandoned:      True when the plan directory is under plans/.abandoned/.
    """
    slug: str
    path: str
    has_tasks_file: bool
    all_tasks_done: bool | None    # None when has_tasks_file is False
    has_only_precontext: bool
    has_merge_evidence: bool
    latest_activity_ts: float | None
    is_abandoned: bool = False


@dataclass
class RegistryRecord:
    """A single record from active-plan-registry.py list --json.

    Attributes:
        run_id:    Unique run identifier.
        slug:      Plan slug this run is associated with.
        status:    'running' | 'paused' | 'stale' | 'complete' | 'aborted'
        pid:       Process ID of the owning process, or None.
        host:      Hostname of the owning process.
        last_heartbeat: ISO-8601 timestamp string of the last heartbeat.
    """
    run_id: str
    slug: str
    status: str
    pid: int | None
    host: str
    last_heartbeat: str


@dataclass
class ClaimLockFacts:
    """Pre-collected facts about a single claim-lock file.

    Attributes:
        slug:        Plan slug this lock is for.
        lock_path:   Absolute path to the lock file on disk.
        daemon_pid:  PID of the lock daemon, or None if not parseable.
        daemon_alive: True when the daemon PID exists and is alive (os.kill check).
        reap_status: Output from plan-claim.sh reap-stale (once that exists):
                     'free' | 'stale' | 'corrupt' | 'held' | 'unknown'
    """
    slug: str
    lock_path: str
    daemon_pid: int | None
    daemon_alive: bool
    reap_status: str = "unknown"  # free | stale | corrupt | held | unknown


@dataclass
class CrossRefInput:
    """Bundle of all collections passed to cross_ref_join.

    Attributes:
        worktrees:          List of (WorktreeFacts, worktree_class) tuples.
        plans:              List of (PlanFacts, plan_class) tuples.
        registry_records:   All live registry records.
        claim_locks:        All claim-lock facts on disk.
        uncommitted_slugs:  Set of plan slugs that have uncommitted file changes
                            attributed to them (e.g. via plan path overlap).
    """
    worktrees: list[tuple[WorktreeFacts, str]]
    plans: list[tuple[PlanFacts, str]]
    registry_records: list[RegistryRecord]
    claim_locks: list[ClaimLockFacts]
    uncommitted_slugs: set[str] = field(default_factory=set)


@dataclass
class CrossRefFlags:
    """Four boolean cross-reference flags returned by cross_ref_join.

    Each flag corresponds to one of the four join conditions required by the
    INTENT acceptance checklist (criterion #3, #4).

    Attributes:
        merged_worktree_on_disk:
            True when at least one worktree's branch appears merged into the
            default branch but the worktree is still on disk.
        complete_plan_no_merge_evidence:
            True when at least one plan has all tasks done but no merge/commit evidence.
        orphan_claim_lock:
            True when at least one claim lock has no matching live registry record.
        uncommitted_work_for_plan:
            True when at least one plan slug has uncommitted work attributed to it.

        detail:
            Dict of slug/path → list of flag names that triggered, for reporting.
    """
    merged_worktree_on_disk: bool
    complete_plan_no_merge_evidence: bool
    orphan_claim_lock: bool
    uncommitted_work_for_plan: bool
    detail: dict[str, list[str]] = field(default_factory=dict)


# ── worktree classifier ────────────────────────────────────────────────────────

def classify_worktree(facts: WorktreeFacts) -> tuple[str, str]:
    """Classify a worktree into one of the six canonical classes.

    Classification is pure and deterministic given the pre-collected facts.
    Precedence: detached > dirty > unknown-remote (bypassed when
    patch_identical_to_default is True) > merged-uncertain > dead (literal-ancestor
    OR patch-identity) > active. Only 'dead' is auto-prune-eligible; all others are
    surface-only.

    patch_identical_to_default is True is an offline, stronger-than-remote-ancestry
    proof of "already merged": it also catches squash merges and local branches that
    were never pushed, both of which the remote-ancestry check structurally misses.
    A clean worktree with patch_identical_to_default is True is therefore promoted to
    'dead' even without commit-ancestry confirmation and even when the remote is
    unreachable or the branch has unpushed commits — those two guards are bypassed
    specifically for the patch-identical case (see the two bypass conditions below).
    Detached and dirty are never bypassed: a mutation-risk or ambiguous-branch state
    always wins regardless of patch identity.

    Args:
        facts: Pre-collected WorktreeFacts for this worktree.

    Returns:
        (class_name, recommended_action) where class_name is one of WORKTREE_CLASSES.

    Raises:
        ValueError: If facts.merge_evidence is not one of the recognised values.
                    This is raised by WorktreeFacts.__post_init__ at construction
                    time, but the docstring contract is preserved here for callers
                    who catch ValueError from this function.
    """
    # Detached HEAD: cannot determine branch-level merge status.
    if facts.is_detached:
        return (
            "detached",
            "Manual review required: HEAD is detached. "
            "Re-attach to a branch before deciding whether to prune.",
        )

    # Uncommitted changes: any mutation risk.
    if facts.has_uncommitted:
        return (
            "dirty",
            "Uncommitted changes present. Commit, stash, or discard before pruning.",
        )

    # Remote unreachable OR unpushed status indeterminate: cannot confirm it is safe.
    # The OR condition is intentional and safety-conservative: if has_unpushed is None
    # (the check was skipped for ANY reason, not just remote failure), we must not
    # proceed toward a prunable class. A None here means "we do not know whether there
    # are commits at risk" — routing to unknown-remote (surface-only, never auto-prune)
    # is the correct fail-safe. Narrowing to `not remote_reachable` only would allow a
    # None to fall through to a prunable class if remote_reachable happens to be True.
    #
    # Bypass: patch_identical_to_default is True is an offline proof that does not
    # depend on the remote at all, so a clean worktree with a proven patch-identical
    # HEAD must not be shunted to unknown-remote just because the remote happens to be
    # unreachable or unpushed-status could not be determined.
    if (
        not facts.remote_reachable or facts.has_unpushed is None
    ) and facts.patch_identical_to_default is not True:
        return (
            "unknown-remote",
            "Remote was unreachable; unpushed-commit check skipped. "
            "Surface only — cannot auto-prune until remote is reachable.",
        )

    # Unpushed commits present.
    #
    # Bypass: a patch-identical branch that was simply never pushed (or has local
    # commits ahead of its remote-tracking ref because it was squash-merged upstream
    # under a different SHA) is exactly the case this feature exists to catch — do
    # not shunt it to 'active' just because has_unpushed is True.
    if facts.has_unpushed and facts.patch_identical_to_default is not True:
        return (
            "active",
            "Unpushed commits present. Push or discard before pruning.",
        )

    # Ambiguous merge evidence (squash merge, etc.).
    if facts.merge_evidence == "merged-uncertain":
        return (
            "merged-uncertain",
            "Branch appears merged via squash or ambiguous evidence. "
            "Verify manually before pruning.",
        )

    # Dead: clean, no unpushed, and HEAD is an ancestor of the default branch.
    # Requires commit-ancestry confirmation from the collection layer.
    if (
        facts.is_head_ancestor_of_default is True
        and not facts.has_uncommitted
        and not facts.has_unpushed
        and facts.remote_reachable
    ):
        return (
            "dead",
            f"Safe to prune: branch is an ancestor of {facts.default_branch}, "
            "no uncommitted or unpushed work. Removal will delete the worktree "
            f"and its merged branch (git worktree remove + git branch -d).",
        )

    # Dead (patch-identity promotion): clean and proven patch-identical to the
    # default branch, even without literal commit ancestry and even when the remote
    # is unreachable or unpushed status is unknown/true (both already bypassed the
    # earlier unknown-remote / unpushed-active guards above). This is the offline,
    # squash-merge-aware and never-pushed-aware case this feature exists to catch.
    if not facts.has_uncommitted and facts.patch_identical_to_default is True:
        return (
            "dead",
            f"Safe to prune: HEAD's patch content is identical to {facts.default_branch} "
            "(offline patch-identity match), no uncommitted work. Removal will delete "
            "the worktree and its merged branch (git worktree remove + git branch -d).",
        )

    # Active: none of the unambiguous prune conditions met.
    return (
        "active",
        "No evidence that this worktree is safe to prune. Leaving in place.",
    )


# ── plan classifier ────────────────────────────────────────────────────────────

def classify_plan(
    facts: PlanFacts,
    staleness_days: int = _DEFAULT_STALENESS_DAYS,
) -> tuple[str, str]:
    """Classify a plan into one of the four canonical classes.

    Staleness uses max(latest events.jsonl timestamp for the slug, artifact
    mtime) vs the configurable threshold, not raw directory age.

    Args:
        facts:          Pre-collected PlanFacts for this plan.
        staleness_days: Number of days of inactivity before a plan is stale.
                        Default 14. Pass a smaller value in tests for speed.

    Returns:
        (class_name, recommended_action) where class_name is one of PLAN_CLASSES.
    """
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    staleness_secs = staleness_days * 86_400

    def _is_stale() -> bool:
        """Return True when latest_activity_ts is past the staleness threshold."""
        if facts.latest_activity_ts is None:
            # No activity signal at all — treat as stale.
            return True
        return (now_ts - facts.latest_activity_ts) > staleness_secs

    # precontext-only-aged: only INTENT/precontext artifacts, past threshold.
    if facts.has_only_precontext and _is_stale():
        return (
            "precontext-only-aged",
            "Only precontext/INTENT artifacts present and past staleness threshold. "
            "Consider archiving with --archive-plans.",
        )

    # tasks-complete-unmerged: all tasks done but no merge evidence. Advisory only.
    if facts.has_tasks_file and facts.all_tasks_done and not facts.has_merge_evidence:
        return (
            "tasks-complete-unmerged",
            "All tasks complete but no merge/commit evidence found. "
            "Advisory: verify the branch was merged, then archive.",
        )

    # stale-in-progress: has tasks / is actively a plan, but past staleness threshold.
    if _is_stale() and not facts.has_only_precontext:
        return (
            "stale-in-progress",
            f"Plan has been inactive for >{staleness_days} days. "
            "Consider resuming or archiving with --archive-plans.",
        )

    # in-progress: the default for plans with recent activity and tasks.
    return (
        "in-progress",
        "Plan appears to be actively in progress. No action recommended.",
    )


# ── cross-reference join ───────────────────────────────────────────────────────

def cross_ref_join(inp: CrossRefInput) -> CrossRefFlags:
    """Join worktrees, plans, registry, locks, and uncommitted work into flags.

    This is the novel join across surfaces: no individual collector produces
    these flags — they emerge from the intersection of multiple collections.

    The four flags correspond to the four required cross-reference conditions
    from the INTENT acceptance checklist:
      (a) worktree merged into default branch but still on disk
      (b) plan all-[x] with no merge evidence
      (c) orphan claim lock with no live registry record
      (d) uncommitted work attributed to a plan slug

    Args:
        inp: CrossRefInput bundle.

    Returns:
        CrossRefFlags with the four boolean flags and a detail dict.

    Notes:
        Best-effort; never raises. If a collection is empty the corresponding
        flag is False.
    """
    detail: dict[str, list[str]] = {}

    def _flag(key: str, flag: str) -> None:
        """Append flag to the detail dict under the given key (slug or path)."""
        detail.setdefault(key, []).append(flag)

    # ── (a) worktree merged into default branch but still on disk ──────────────
    merged_worktree_on_disk = False
    for wt_facts, wt_class in inp.worktrees:
        # Exclude worktrees already classified 'dead': they are already on the
        # --prune-worktrees path and do not need a separate report flag. This flag
        # surfaces merged worktrees that are NOT going through the prune flow —
        # e.g. a worktree that was merged but has uncommitted work (classified
        # 'dirty') or has some other blocking condition. Raising the flag for 'dead'
        # worktrees would double-report items the prune flow already handles.
        if wt_facts.merge_evidence == "merged" and wt_class not in {"dead"}:
            merged_worktree_on_disk = True
            key = wt_facts.branch or wt_facts.path
            _flag(key, "merged-worktree-on-disk")

    # ── (b) plan all-[x] with no merge evidence ─────────────────────────────────
    complete_plan_no_merge_evidence = False
    for plan_facts, plan_class in inp.plans:
        if plan_class == "tasks-complete-unmerged":
            complete_plan_no_merge_evidence = True
            _flag(plan_facts.slug, "tasks-complete-unmerged")

    # ── (c) orphan claim lock with no live registry record ──────────────────────
    # Build a set of slugs with live registry records.
    live_registry_slugs: set[str] = {r.slug for r in inp.registry_records}
    orphan_claim_lock = False
    for lock in inp.claim_locks:
        if lock.slug not in live_registry_slugs:
            orphan_claim_lock = True
            _flag(lock.slug, "orphan-claim-lock")

    # ── (d) uncommitted work attributed to a plan slug ──────────────────────────
    uncommitted_work_for_plan = bool(inp.uncommitted_slugs)
    for slug in inp.uncommitted_slugs:
        _flag(slug, "uncommitted-work")

    return CrossRefFlags(
        merged_worktree_on_disk=merged_worktree_on_disk,
        complete_plan_no_merge_evidence=complete_plan_no_merge_evidence,
        orphan_claim_lock=orphan_claim_lock,
        uncommitted_work_for_plan=uncommitted_work_for_plan,
        detail=detail,
    )


# ── CLI entry point ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser for the CLI entry point."""
    p = argparse.ArgumentParser(
        description="Reconcile classification helpers (--json output for command body).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    wt_p = sub.add_parser(
        "classify-worktree",
        help="Classify a worktree from a JSON facts object.",
    )
    wt_p.add_argument(
        "--json",
        dest="facts_json",
        required=True,
        metavar="FACTS_JSON",
        help="JSON string representing WorktreeFacts fields.",
    )

    pl_p = sub.add_parser(
        "classify-plan",
        help="Classify a plan from a JSON facts object.",
    )
    pl_p.add_argument(
        "--json",
        dest="facts_json",
        required=True,
        metavar="FACTS_JSON",
        help="JSON string representing PlanFacts fields.",
    )
    pl_p.add_argument(
        "--staleness-days",
        type=int,
        default=_DEFAULT_STALENESS_DAYS,
        metavar="N",
        help=f"Staleness threshold in days (default {_DEFAULT_STALENESS_DAYS}).",
    )

    return p


def _cli_classify_worktree(facts_json: str) -> None:
    """Parse facts JSON and print worktree classification as JSON to stdout.

    Reads a JSON object whose keys match WorktreeFacts field names and writes a JSON
    object with 'class' and 'action' keys to stdout.

    Exit codes:
      0 — success; JSON classification written to stdout.
      1 — validation error (e.g. unrecognised merge_evidence value); error JSON on stderr.
      2 — JSON parse error; error JSON on stderr.
    """
    try:
        raw: dict[str, Any] = json.loads(facts_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON parse failed: {exc}"}), file=sys.stderr)
        sys.exit(2)

    try:
        facts = WorktreeFacts(
            path=raw.get("path", ""),
            branch=raw.get("branch"),
            head_sha=raw.get("head_sha", ""),
            is_detached=bool(raw.get("is_detached", False)),
            has_uncommitted=bool(raw.get("has_uncommitted", False)),
            has_unpushed=raw.get("has_unpushed"),
            is_head_ancestor_of_default=raw.get("is_head_ancestor_of_default"),
            default_branch=raw.get("default_branch", "main"),
            remote_reachable=bool(raw.get("remote_reachable", True)),
            merge_evidence=raw.get("merge_evidence", "unknown"),
            patch_identical_to_default=raw.get("patch_identical_to_default"),
        )
        cls, action = classify_worktree(facts)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"class": cls, "action": action}))


def _cli_classify_plan(facts_json: str, staleness_days: int) -> None:
    """Parse facts JSON and print plan classification as JSON to stdout.

    Reads a JSON object whose keys match PlanFacts field names and writes a JSON
    object with 'class' and 'action' keys to stdout.

    Exit codes:
      0 — success; JSON classification written to stdout.
      1 — validation error (e.g. unrecognised field value); error JSON on stderr.
      2 — JSON parse error; error JSON on stderr.
    """
    try:
        raw: dict[str, Any] = json.loads(facts_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON parse failed: {exc}"}), file=sys.stderr)
        sys.exit(2)

    try:
        facts = PlanFacts(
            slug=raw.get("slug", ""),
            path=raw.get("path", ""),
            has_tasks_file=bool(raw.get("has_tasks_file", False)),
            all_tasks_done=raw.get("all_tasks_done"),
            has_only_precontext=bool(raw.get("has_only_precontext", False)),
            has_merge_evidence=bool(raw.get("has_merge_evidence", False)),
            latest_activity_ts=raw.get("latest_activity_ts"),
            is_abandoned=bool(raw.get("is_abandoned", False)),
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    cls, action = classify_plan(facts, staleness_days=staleness_days)
    print(json.dumps({"class": cls, "action": action}))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for scripts/reconcile.py.

    Exits non-zero on error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "classify-worktree":
        _cli_classify_worktree(args.facts_json)
    elif args.command == "classify-plan":
        _cli_classify_plan(args.facts_json, args.staleness_days)
    else:
        # argparse's required=True already guards this branch.
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
