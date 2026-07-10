"""
tests/test_reconcile_classify.py — Unit tests for scripts/reconcile.py classifiers.

Invariant under test (criterion #3, #4, #5, #12 from the reconcile-workspace INTENT):
  The classification functions in reconcile.py must correctly assign each
  worktree and plan to exactly the right canonical class given the pre-collected
  facts, and the cross-reference join must flag the four required conditions
  without requiring any live git, filesystem, or registry I/O.

  Failure class: a misclassified worktree or plan silently hides workspace debt
  or triggers an incorrect prune/archive action, both of which are safety violations.

Test classes:
  TestWorktreeClassDead               — 'dead' (only auto-prune-eligible class)
  TestWorktreeClassDeadPatchIdentity  — 'dead' via offline patch-identity promotion
  TestWorktreeClassDirty              — 'dirty' (uncommitted changes)
  TestWorktreeClassDetached           — 'detached' (detached HEAD)
  TestWorktreeClassMergedUncertain    — 'merged-uncertain' (squash/ambiguous)
  TestWorktreeClassUnknownRemote      — 'unknown-remote' (remote unreachable)
  TestWorktreeClassActive             — 'active' (none of the above)
  TestPlanClassPrecontextOnlyAged     — 'precontext-only-aged'
  TestPlanClassTasksCompleteUnmerged  — 'tasks-complete-unmerged' (advisory)
  TestPlanClassInProgress             — 'in-progress'
  TestPlanClassStaleInProgress        — 'stale-in-progress'
  TestCrossRefJoin                    — four required cross-reference flags
  TestWorktreeClassPrecedence         — precedence ordering between flags
  TestCLISmoke                        — CLI parses and emits valid JSON

All tests construct fact inputs directly — no subprocess git calls, no
filesystem side effects.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "reconcile.py")


# ---------------------------------------------------------------------------
# Load module under test (hyphenated-like filename uses importlib)
# ---------------------------------------------------------------------------

def _load_module():
    spec = importlib.util.spec_from_file_location("reconcile", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so @dataclass can resolve the module's
    # __dict__ via cls.__module__ (Python 3.13 is strict about this).
    sys.modules["reconcile"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()

WorktreeFacts = _mod.WorktreeFacts
PlanFacts = _mod.PlanFacts
RegistryRecord = _mod.RegistryRecord
ClaimLockFacts = _mod.ClaimLockFacts
CrossRefInput = _mod.CrossRefInput
CrossRefFlags = _mod.CrossRefFlags
classify_worktree = _mod.classify_worktree
classify_plan = _mod.classify_plan
cross_ref_join = _mod.cross_ref_join
WORKTREE_CLASSES = _mod.WORKTREE_CLASSES
PLAN_CLASSES = _mod.PLAN_CLASSES


# ---------------------------------------------------------------------------
# Shared fixture helpers (no I/O)
# ---------------------------------------------------------------------------

def _dead_facts(**overrides) -> WorktreeFacts:
    """Return facts for a worktree that should classify as 'dead'."""
    base = dict(
        path="/wt/dead-branch",
        branch="feature/old",
        head_sha="abc123",
        is_detached=False,
        has_uncommitted=False,
        has_unpushed=False,
        is_head_ancestor_of_default=True,
        default_branch="main",
        remote_reachable=True,
        merge_evidence="merged",
    )
    base.update(overrides)
    return WorktreeFacts(**base)


def _active_facts(**overrides) -> WorktreeFacts:
    """Return facts for a worktree that should classify as 'active'."""
    base = dict(
        path="/wt/active-branch",
        branch="feature/wip",
        head_sha="def456",
        is_detached=False,
        has_uncommitted=False,
        has_unpushed=False,
        is_head_ancestor_of_default=False,   # HEAD is NOT an ancestor of default
        default_branch="main",
        remote_reachable=True,
        merge_evidence="not-merged",
    )
    base.update(overrides)
    return WorktreeFacts(**base)


def _now_ts() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _recent_ts() -> float:
    """A timestamp 1 day ago — definitely within the staleness window."""
    return _now_ts() - 86_400


def _old_ts(days: int = 30) -> float:
    """A timestamp `days` days ago — past the default 14-day staleness threshold."""
    return _now_ts() - (days * 86_400)


def _in_progress_facts(**overrides) -> PlanFacts:
    base = dict(
        slug="my-plan",
        path="/plans/my-plan",
        has_tasks_file=True,
        all_tasks_done=False,
        has_only_precontext=False,
        has_merge_evidence=False,
        latest_activity_ts=_recent_ts(),
        is_abandoned=False,
    )
    base.update(overrides)
    return PlanFacts(**base)


# ---------------------------------------------------------------------------
# Worktree: 'dead' class
# ---------------------------------------------------------------------------

class TestWorktreeClassDead:
    """'dead' is the ONLY auto-prune-eligible class.

    Invariant: a worktree classified 'dead' must satisfy all three of:
      - clean working tree (no uncommitted changes)
      - no unpushed commits
      - HEAD is a commit-ancestry ancestor of the default branch
    If ANY condition is false, the classification must be something other than 'dead'.
    """

    def test_clean_no_unpushed_ancestor_is_dead(self) -> None:
        """The canonical 'dead' case: all three conditions satisfied."""
        cls, action = classify_worktree(_dead_facts())
        assert cls == "dead", f"Expected 'dead' but got {cls!r}"

    def test_dead_class_is_in_constants(self) -> None:
        """'dead' must be in WORKTREE_CLASSES constant."""
        assert "dead" in WORKTREE_CLASSES

    def test_dead_action_mentions_default_branch(self) -> None:
        """Recommended action for a dead worktree must reference the default branch."""
        facts = _dead_facts(default_branch="develop")
        _, action = classify_worktree(facts)
        assert "develop" in action, f"Expected 'develop' in action: {action!r}"

    def test_not_dead_when_head_not_ancestor(self) -> None:
        """If HEAD is not an ancestor of the default branch, must NOT be 'dead'."""
        facts = _dead_facts(is_head_ancestor_of_default=False)
        cls, _ = classify_worktree(facts)
        assert cls != "dead", f"Expected non-dead when HEAD not ancestor; got {cls!r}"

    def test_not_dead_when_head_ancestor_unknown(self) -> None:
        """If ancestry check could not run (None), must NOT be 'dead'."""
        facts = _dead_facts(is_head_ancestor_of_default=None)
        cls, _ = classify_worktree(facts)
        assert cls != "dead", f"Expected non-dead when ancestry unknown; got {cls!r}"


# ---------------------------------------------------------------------------
# Worktree: 'dead' class via patch-identity promotion (new)
# ---------------------------------------------------------------------------

class TestWorktreeClassDeadPatchIdentity:
    """'dead' via offline patch-identity, even without literal commit ancestry.

    Invariant: a clean worktree whose HEAD is proven patch-identical to the
    default branch must classify 'dead' even when: (1) HEAD is NOT a commit-
    ancestry ancestor of the default branch (e.g. squash merge), and (2) the
    remote is unreachable or the branch has unpushed commits / was never
    pushed. This is the offline, squash-aware detection this feature exists
    to add. Detached and dirty must still take precedence over patch-identity.
    """

    def test_clean_patch_identical_non_ancestor_unknown_remote_is_dead(self) -> None:
        """Clean + patch-identical + non-ancestor + remote unreachable → 'dead'."""
        facts = _active_facts(
            is_head_ancestor_of_default=False,
            remote_reachable=False,
            has_unpushed=None,
            patch_identical_to_default=True,
        )
        cls, action = classify_worktree(facts)
        assert cls == "dead", f"Expected 'dead' but got {cls!r}"
        assert "patch" in action.lower()

    def test_clean_patch_identical_non_ancestor_unpushed_is_dead(self) -> None:
        """Clean + patch-identical + non-ancestor + never-pushed (has_unpushed=True)
        with remote reachable → 'dead'. This is the never-pushed-local-branch case."""
        facts = _active_facts(
            is_head_ancestor_of_default=False,
            remote_reachable=True,
            has_unpushed=True,
            patch_identical_to_default=True,
        )
        cls, _ = classify_worktree(facts)
        assert cls == "dead", f"Expected 'dead' but got {cls!r}"

    def test_dead_action_mentions_patch_identity_and_branch_deletion(self) -> None:
        """Recommended action for the patch-identity path must mention patch-identity
        and that the branch will be deleted (git branch -d), not just the worktree."""
        facts = _active_facts(
            is_head_ancestor_of_default=False,
            remote_reachable=False,
            has_unpushed=None,
            patch_identical_to_default=True,
        )
        _, action = classify_worktree(facts)
        assert "patch" in action.lower()
        assert "branch" in action.lower()

    def test_dirty_beats_patch_identity(self) -> None:
        """Uncommitted changes must prevent 'dead' promotion even when patch-identical."""
        facts = _active_facts(
            has_uncommitted=True,
            is_head_ancestor_of_default=False,
            remote_reachable=False,
            has_unpushed=None,
            patch_identical_to_default=True,
        )
        cls, _ = classify_worktree(facts)
        assert cls == "dirty", (
            "A dirty worktree must never be promoted to 'dead' by patch-identity."
        )

    def test_detached_beats_patch_identity(self) -> None:
        """Detached HEAD must prevent 'dead' promotion even when patch-identical."""
        facts = _active_facts(
            is_detached=True,
            branch=None,
            is_head_ancestor_of_default=False,
            remote_reachable=False,
            has_unpushed=None,
            patch_identical_to_default=True,
        )
        cls, _ = classify_worktree(facts)
        assert cls == "detached", (
            "A detached worktree must never be promoted to 'dead' by patch-identity."
        )

    def test_merged_uncertain_beats_patch_identity(self) -> None:
        """merged-uncertain evidence still takes precedence over patch-identity
        promotion, per the documented precedence order."""
        facts = _active_facts(
            is_head_ancestor_of_default=False,
            remote_reachable=True,
            has_unpushed=False,
            merge_evidence="merged-uncertain",
            patch_identical_to_default=True,
        )
        cls, _ = classify_worktree(facts)
        assert cls == "merged-uncertain"

    def test_patch_identical_false_does_not_promote(self) -> None:
        """patch_identical_to_default=False must not trigger promotion; falls
        through to the existing (non-)dead logic."""
        facts = _active_facts(
            is_head_ancestor_of_default=False,
            patch_identical_to_default=False,
        )
        cls, _ = classify_worktree(facts)
        assert cls != "dead"

    def test_literal_ancestor_dead_path_still_works(self) -> None:
        """Regression: the pre-existing literal-ancestor 'dead' path (with a
        reachable remote and no patch-identity fact at all) still classifies 'dead'."""
        cls, action = classify_worktree(_dead_facts())
        assert cls == "dead", f"Expected 'dead' but got {cls!r}"
        assert "ancestor" in action.lower()


# ---------------------------------------------------------------------------
# Worktree: 'dirty' class
# ---------------------------------------------------------------------------

class TestWorktreeClassDirty:
    """'dirty' when there are uncommitted changes, regardless of merge status."""

    def test_uncommitted_changes_is_dirty(self) -> None:
        """Uncommitted changes → 'dirty', never prune."""
        facts = _active_facts(has_uncommitted=True)
        cls, _ = classify_worktree(facts)
        assert cls == "dirty"

    def test_dirty_even_if_ancestor(self) -> None:
        """Dirty + ancestor of default → still 'dirty', not 'dead'."""
        facts = _dead_facts(has_uncommitted=True)
        cls, _ = classify_worktree(facts)
        assert cls == "dirty", (
            "Uncommitted changes must prevent 'dead' classification even if HEAD "
            "is an ancestor of the default branch."
        )

    def test_dirty_class_is_in_constants(self) -> None:
        assert "dirty" in WORKTREE_CLASSES

    def test_dirty_action_mentions_uncommitted(self) -> None:
        """Recommended action must mention uncommitted changes."""
        facts = _active_facts(has_uncommitted=True)
        _, action = classify_worktree(facts)
        assert "uncommitted" in action.lower()


# ---------------------------------------------------------------------------
# Worktree: 'detached' class
# ---------------------------------------------------------------------------

class TestWorktreeClassDetached:
    """'detached' when HEAD is detached, regardless of other facts."""

    def test_detached_head_is_detached(self) -> None:
        facts = _active_facts(is_detached=True, branch=None)
        cls, _ = classify_worktree(facts)
        assert cls == "detached"

    def test_detached_even_if_clean(self) -> None:
        """Detached + clean + no unpushed → still 'detached', never 'dead'."""
        facts = _dead_facts(is_detached=True, branch=None)
        cls, _ = classify_worktree(facts)
        assert cls == "detached", (
            "Detached HEAD must prevent 'dead' classification even when everything "
            "else is clean."
        )

    def test_detached_class_is_in_constants(self) -> None:
        assert "detached" in WORKTREE_CLASSES

    def test_detached_action_mentions_reattach(self) -> None:
        facts = _active_facts(is_detached=True, branch=None)
        _, action = classify_worktree(facts)
        assert "detached" in action.lower() or "re-attach" in action.lower()


# ---------------------------------------------------------------------------
# Worktree: 'merged-uncertain' class
# ---------------------------------------------------------------------------

class TestWorktreeClassMergedUncertain:
    """'merged-uncertain' when merge evidence is ambiguous (squash, etc.)."""

    def test_squash_merge_evidence_is_merged_uncertain(self) -> None:
        """Squash/ambiguous merge evidence → 'merged-uncertain', not prune-eligible."""
        facts = _dead_facts(
            merge_evidence="merged-uncertain",
            is_head_ancestor_of_default=False,  # squash detaches commit ancestry
        )
        cls, _ = classify_worktree(facts)
        assert cls == "merged-uncertain"

    def test_merged_uncertain_class_is_in_constants(self) -> None:
        assert "merged-uncertain" in WORKTREE_CLASSES

    def test_merged_uncertain_not_dead(self) -> None:
        """merged-uncertain must never classify as 'dead'."""
        facts = _dead_facts(merge_evidence="merged-uncertain")
        cls, _ = classify_worktree(facts)
        assert cls != "dead", (
            "Squash/ambiguous merge evidence must block 'dead' classification; "
            "manual verification required."
        )

    def test_invalid_merge_evidence_raises(self) -> None:
        """Unknown merge_evidence value must raise ValueError from classify_worktree."""
        # Note: ValueError is now raised at WorktreeFacts construction time
        # (via __post_init__) before classify_worktree is even called.
        with pytest.raises(ValueError, match="merge_evidence"):
            _active_facts(merge_evidence="bogus-value")

    def test_invalid_merge_evidence_raises_at_construction(self) -> None:
        """WorktreeFacts.__post_init__ raises ValueError for bad merge_evidence immediately."""
        with pytest.raises(ValueError, match="merge_evidence"):
            WorktreeFacts(
                path="/wt/test",
                branch="feature/x",
                head_sha="abc",
                is_detached=False,
                has_uncommitted=False,
                has_unpushed=False,
                is_head_ancestor_of_default=True,
                default_branch="main",
                remote_reachable=True,
                merge_evidence="INVALID_VALUE",
            )


# ---------------------------------------------------------------------------
# Worktree: 'unknown-remote' class
# ---------------------------------------------------------------------------

class TestWorktreeClassUnknownRemote:
    """'unknown-remote' when the remote was unreachable during collection."""

    def test_remote_unreachable_is_unknown_remote(self) -> None:
        """Remote unreachable → 'unknown-remote', skip unpushed check."""
        facts = _active_facts(remote_reachable=False, has_unpushed=None)
        cls, _ = classify_worktree(facts)
        assert cls == "unknown-remote"

    def test_unpushed_none_is_unknown_remote(self) -> None:
        """has_unpushed=None (remote skip) → 'unknown-remote'."""
        # has_unpushed=None signals the check was not run.
        facts = _active_facts(has_unpushed=None)
        cls, _ = classify_worktree(facts)
        assert cls == "unknown-remote"

    def test_unknown_remote_class_is_in_constants(self) -> None:
        assert "unknown-remote" in WORKTREE_CLASSES

    def test_unknown_remote_not_prune_eligible(self) -> None:
        """unknown-remote must never be 'dead'."""
        facts = _dead_facts(remote_reachable=False, has_unpushed=None)
        cls, _ = classify_worktree(facts)
        assert cls != "dead"


# ---------------------------------------------------------------------------
# Worktree: 'active' class
# ---------------------------------------------------------------------------

class TestWorktreeClassActive:
    """'active' when none of the more specific conditions apply."""

    def test_head_not_ancestor_is_active(self) -> None:
        """Clean, no unpushed, but HEAD is not ancestor of default → 'active'."""
        facts = _active_facts(is_head_ancestor_of_default=False)
        cls, _ = classify_worktree(facts)
        assert cls == "active"

    def test_unpushed_commits_is_active(self) -> None:
        """Unpushed commits present → 'active' (not prune-eligible)."""
        facts = _active_facts(has_unpushed=True)
        cls, _ = classify_worktree(facts)
        assert cls == "active"

    def test_active_class_is_in_constants(self) -> None:
        assert "active" in WORKTREE_CLASSES

    def test_active_when_ancestor_check_none_and_clean(self) -> None:
        """is_head_ancestor_of_default=None and otherwise clean → not 'dead'."""
        facts = _dead_facts(is_head_ancestor_of_default=None, remote_reachable=True)
        cls, _ = classify_worktree(facts)
        # Should be 'active' (can't confirm ancestor status → not 'dead').
        assert cls in {"active", "unknown-remote"}, f"Got unexpected class {cls!r}"


# ---------------------------------------------------------------------------
# Worktree: precedence ordering
# ---------------------------------------------------------------------------

class TestWorktreeClassPrecedence:
    """Detached takes precedence over dirty; dirty over unknown-remote; etc."""

    def test_detached_beats_dirty(self) -> None:
        """Detached HEAD + uncommitted → 'detached' (not 'dirty')."""
        facts = _active_facts(is_detached=True, branch=None, has_uncommitted=True)
        cls, _ = classify_worktree(facts)
        assert cls == "detached"

    def test_dirty_beats_unknown_remote(self) -> None:
        """Dirty + remote unreachable → 'dirty' (not 'unknown-remote')."""
        facts = _active_facts(
            has_uncommitted=True,
            remote_reachable=False,
            has_unpushed=None,
        )
        cls, _ = classify_worktree(facts)
        assert cls == "dirty"

    def test_all_six_classes_covered_in_constants(self) -> None:
        """Exactly six worktree classes must exist in the constant."""
        assert len(WORKTREE_CLASSES) == 6
        expected = {"dead", "dirty", "detached", "merged-uncertain", "unknown-remote", "active"}
        assert WORKTREE_CLASSES == expected


# ---------------------------------------------------------------------------
# Plan: 'precontext-only-aged' class
# ---------------------------------------------------------------------------

class TestPlanClassPrecontextOnlyAged:
    """'precontext-only-aged' when only INTENT/precontext artifacts exist and plan is stale."""

    def test_precontext_only_aged_past_threshold(self) -> None:
        """Only precontext artifacts + activity older than threshold → 'precontext-only-aged'."""
        facts = PlanFacts(
            slug="old-idea",
            path="/plans/old-idea",
            has_tasks_file=False,
            all_tasks_done=None,
            has_only_precontext=True,
            has_merge_evidence=False,
            latest_activity_ts=_old_ts(days=30),
        )
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "precontext-only-aged"

    def test_precontext_only_not_aged_is_in_progress(self) -> None:
        """Only precontext artifacts but recent activity → 'in-progress' (not aged yet)."""
        facts = PlanFacts(
            slug="new-idea",
            path="/plans/new-idea",
            has_tasks_file=False,
            all_tasks_done=None,
            has_only_precontext=True,
            has_merge_evidence=False,
            latest_activity_ts=_recent_ts(),
        )
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "in-progress", (
            "A precontext-only plan with recent activity must not be classified as "
            "'precontext-only-aged' — it may still be in early ideation."
        )

    def test_precontext_only_no_activity_is_aged(self) -> None:
        """No activity signal at all + precontext-only → treat as stale."""
        facts = PlanFacts(
            slug="ghost-idea",
            path="/plans/ghost-idea",
            has_tasks_file=False,
            all_tasks_done=None,
            has_only_precontext=True,
            has_merge_evidence=False,
            latest_activity_ts=None,
        )
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "precontext-only-aged"

    def test_class_is_in_constants(self) -> None:
        assert "precontext-only-aged" in PLAN_CLASSES


# ---------------------------------------------------------------------------
# Plan: 'tasks-complete-unmerged' class
# ---------------------------------------------------------------------------

class TestPlanClassTasksCompleteUnmerged:
    """'tasks-complete-unmerged' when all tasks done but no merge evidence.
    This class is ADVISORY only — the command must never auto-act on it.
    """

    def test_all_tasks_done_no_merge_evidence(self) -> None:
        """All tasks [x] + no merge evidence → 'tasks-complete-unmerged'."""
        facts = _in_progress_facts(all_tasks_done=True, has_merge_evidence=False)
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "tasks-complete-unmerged"

    def test_all_tasks_done_with_merge_evidence_is_not_this_class(self) -> None:
        """All tasks [x] + merge evidence → NOT 'tasks-complete-unmerged'."""
        facts = _in_progress_facts(all_tasks_done=True, has_merge_evidence=True)
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls != "tasks-complete-unmerged"

    def test_action_says_advisory(self) -> None:
        """Action must indicate this is advisory (no auto-action)."""
        facts = _in_progress_facts(all_tasks_done=True, has_merge_evidence=False)
        _, action = classify_plan(facts, staleness_days=14)
        # Must NOT say "auto" or imply automated action.
        assert "advisory" in action.lower() or "verify" in action.lower()

    def test_class_is_in_constants(self) -> None:
        assert "tasks-complete-unmerged" in PLAN_CLASSES


# ---------------------------------------------------------------------------
# Plan: 'in-progress' class
# ---------------------------------------------------------------------------

class TestPlanClassInProgress:
    """'in-progress' for plans with recent activity and tasks not yet complete."""

    def test_recent_activity_with_tasks_is_in_progress(self) -> None:
        """Recent activity + tasks not done → 'in-progress'."""
        facts = _in_progress_facts()
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "in-progress"

    def test_in_progress_with_merge_evidence_stays_in_progress(self) -> None:
        """In-progress plan that has some merge evidence but tasks not all done → 'in-progress'."""
        facts = _in_progress_facts(has_merge_evidence=True, all_tasks_done=False)
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "in-progress"

    def test_class_is_in_constants(self) -> None:
        assert "in-progress" in PLAN_CLASSES

    def test_custom_staleness_threshold_respected(self) -> None:
        """A plan just inside the custom threshold is 'in-progress'; just outside is stale."""
        # Activity 5 days ago with a 7-day threshold → in-progress
        facts_fresh = _in_progress_facts(latest_activity_ts=_old_ts(days=5))
        cls_fresh, _ = classify_plan(facts_fresh, staleness_days=7)
        assert cls_fresh == "in-progress", "5 days ago with 7-day threshold should be in-progress"

        # Activity 10 days ago with a 7-day threshold → stale-in-progress
        facts_stale = _in_progress_facts(latest_activity_ts=_old_ts(days=10))
        cls_stale, _ = classify_plan(facts_stale, staleness_days=7)
        assert cls_stale == "stale-in-progress", (
            "10 days ago with 7-day threshold should be stale-in-progress"
        )

    def test_staleness_boundary_just_inside_is_in_progress(self) -> None:
        """A plan with activity 1 second before the staleness boundary is 'in-progress'.

        The staleness check uses strict greater-than (>), so a timestamp just
        inside the window (elapsed < threshold) must remain 'in-progress'. This
        confirms the boundary is `>` not `>=`.

        We cannot use the exact boundary (now - days*86400) because datetime.now()
        advances by a few microseconds between the test's ts capture and classify_plan's
        internal now() call, which would make an exact-boundary ts appear stale. Using
        "boundary minus 1 second" avoids the race while still confirming the semantics.
        """
        now_ts = _now_ts()
        staleness_days = 7
        # 1 second inside the window: elapsed will be (threshold - 1s) < threshold
        just_inside_ts = now_ts - (staleness_days * 86_400) + 1
        facts = _in_progress_facts(latest_activity_ts=just_inside_ts)
        cls, _ = classify_plan(facts, staleness_days=staleness_days)
        assert cls == "in-progress", (
            "A timestamp 1 second inside the staleness window must classify as 'in-progress' "
            "because the staleness check is strict greater-than (elapsed > threshold)."
        )

        # One second past the boundary → stale, confirming the other side.
        just_past_ts = now_ts - (staleness_days * 86_400) - 1
        facts_stale = _in_progress_facts(latest_activity_ts=just_past_ts)
        cls_stale, _ = classify_plan(facts_stale, staleness_days=staleness_days)
        assert cls_stale == "stale-in-progress", (
            "A timestamp 1 second past the staleness boundary must classify as 'stale-in-progress'."
        )


# ---------------------------------------------------------------------------
# Plan: 'stale-in-progress' class
# ---------------------------------------------------------------------------

class TestPlanClassStaleInProgress:
    """'stale-in-progress' when a plan is in-progress but past the staleness threshold."""

    def test_old_activity_is_stale_in_progress(self) -> None:
        """Activity 30 days ago with 14-day threshold → 'stale-in-progress'."""
        facts = _in_progress_facts(
            has_tasks_file=True,
            all_tasks_done=False,
            has_only_precontext=False,
            latest_activity_ts=_old_ts(days=30),
        )
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "stale-in-progress"

    def test_no_activity_ts_with_tasks_is_stale_in_progress(self) -> None:
        """No activity timestamp + tasks file present → 'stale-in-progress'."""
        facts = _in_progress_facts(
            has_tasks_file=True,
            all_tasks_done=False,
            has_only_precontext=False,
            latest_activity_ts=None,
        )
        cls, _ = classify_plan(facts, staleness_days=14)
        assert cls == "stale-in-progress"

    def test_stale_in_progress_not_precontext_only(self) -> None:
        """'stale-in-progress' must not overlap with 'precontext-only-aged'."""
        # has_only_precontext=False + stale → 'stale-in-progress'
        # has_only_precontext=True + stale → 'precontext-only-aged'
        facts_precontext = PlanFacts(
            slug="precontext",
            path="/plans/precontext",
            has_tasks_file=False,
            all_tasks_done=None,
            has_only_precontext=True,
            has_merge_evidence=False,
            latest_activity_ts=_old_ts(days=30),
        )
        cls_precontext, _ = classify_plan(facts_precontext, staleness_days=14)
        assert cls_precontext == "precontext-only-aged"

        facts_stale = _in_progress_facts(
            has_only_precontext=False,
            latest_activity_ts=_old_ts(days=30),
        )
        cls_stale, _ = classify_plan(facts_stale, staleness_days=14)
        assert cls_stale == "stale-in-progress"

    def test_class_is_in_constants(self) -> None:
        assert "stale-in-progress" in PLAN_CLASSES

    def test_all_four_classes_covered_in_constants(self) -> None:
        """Exactly four plan classes must exist in the constant."""
        assert len(PLAN_CLASSES) == 4
        expected = {
            "precontext-only-aged",
            "tasks-complete-unmerged",
            "in-progress",
            "stale-in-progress",
        }
        assert PLAN_CLASSES == expected


# ---------------------------------------------------------------------------
# Cross-reference join: all four flags
# ---------------------------------------------------------------------------

class TestCrossRefJoin:
    """The four required cross-reference flags.

    Invariant: the join function must produce the correct boolean flags given
    the pre-collected worktrees + plans + registry + locks + uncommitted slugs.
    Each flag must be independently triggerable and independently suppressible.
    """

    def _empty_input(self) -> CrossRefInput:
        """Return an empty CrossRefInput — all flags should be False."""
        return CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[],
            claim_locks=[],
            uncommitted_slugs=set(),
        )

    def test_empty_input_all_flags_false(self) -> None:
        """Empty input → no flags raised."""
        result = cross_ref_join(self._empty_input())
        assert result.merged_worktree_on_disk is False
        assert result.complete_plan_no_merge_evidence is False
        assert result.orphan_claim_lock is False
        assert result.uncommitted_work_for_plan is False

    # ── (a) merged worktree still on disk ──────────────────────────────────────

    def test_flag_a_merged_worktree_on_disk(self) -> None:
        """(a) A worktree with merge_evidence='merged' not yet pruned → flag raised."""
        wt = _dead_facts(merge_evidence="merged")
        inp = CrossRefInput(
            worktrees=[(wt, "active")],  # on disk, not yet classified as dead+pruned
            plans=[],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is True

    def test_flag_a_not_raised_when_not_merged(self) -> None:
        """(a) not raised when merge_evidence is 'not-merged'."""
        wt = _dead_facts(merge_evidence="not-merged")
        inp = CrossRefInput(
            worktrees=[(wt, "active")],
            plans=[],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is False

    def test_flag_a_not_raised_when_merged_uncertain(self) -> None:
        """(a) not raised for 'merged-uncertain' — that is a different class."""
        wt = _dead_facts(merge_evidence="merged-uncertain")
        inp = CrossRefInput(
            worktrees=[(wt, "merged-uncertain")],
            plans=[],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is False

    # ── (b) plan all-[x] with no merge evidence ─────────────────────────────────

    def test_flag_b_tasks_complete_unmerged(self) -> None:
        """(b) A plan classified 'tasks-complete-unmerged' → flag raised."""
        plan = _in_progress_facts(all_tasks_done=True, has_merge_evidence=False)
        inp = CrossRefInput(
            worktrees=[],
            plans=[(plan, "tasks-complete-unmerged")],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.complete_plan_no_merge_evidence is True

    def test_flag_b_not_raised_when_in_progress(self) -> None:
        """(b) not raised when plan is 'in-progress'."""
        plan = _in_progress_facts()
        inp = CrossRefInput(
            worktrees=[],
            plans=[(plan, "in-progress")],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.complete_plan_no_merge_evidence is False

    # ── (c) orphan claim lock ────────────────────────────────────────────────────

    def test_flag_c_orphan_claim_lock(self) -> None:
        """(c) A claim lock with no matching live registry record → flag raised."""
        lock = ClaimLockFacts(
            slug="orphan-plan",
            lock_path="/locks/orphan-plan.lock",
            daemon_pid=12345,
            daemon_alive=False,
            reap_status="stale",
        )
        # No registry record for this slug.
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[],
            claim_locks=[lock],
        )
        result = cross_ref_join(inp)
        assert result.orphan_claim_lock is True

    def test_flag_c_not_raised_when_registry_record_exists(self) -> None:
        """(c) not raised when a live registry record matches the slug."""
        lock = ClaimLockFacts(
            slug="live-plan",
            lock_path="/locks/live-plan.lock",
            daemon_pid=99,
            daemon_alive=True,
            reap_status="held",
        )
        record = RegistryRecord(
            run_id="run-001",
            slug="live-plan",
            status="running",
            pid=99,
            host="localhost",
            last_heartbeat="2026-06-19T17:00:00Z",
        )
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[record],
            claim_locks=[lock],
        )
        result = cross_ref_join(inp)
        assert result.orphan_claim_lock is False

    def test_flag_c_multiple_locks_one_orphan(self) -> None:
        """(c) flag raised when one of multiple locks is orphaned."""
        lock_live = ClaimLockFacts(
            slug="live-plan", lock_path="/locks/live.lock",
            daemon_pid=1, daemon_alive=True, reap_status="held",
        )
        lock_orphan = ClaimLockFacts(
            slug="orphan-plan", lock_path="/locks/orphan.lock",
            daemon_pid=2, daemon_alive=False, reap_status="stale",
        )
        record = RegistryRecord(
            run_id="run-001", slug="live-plan", status="running",
            pid=1, host="h", last_heartbeat="2026-06-19T17:00:00Z",
        )
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[record],
            claim_locks=[lock_live, lock_orphan],
        )
        result = cross_ref_join(inp)
        assert result.orphan_claim_lock is True
        assert "orphan-plan" in result.detail

    # ── (d) uncommitted work attributed to a plan slug ──────────────────────────

    def test_flag_d_uncommitted_work_for_plan(self) -> None:
        """(d) Uncommitted work attributed to a plan slug → flag raised."""
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[],
            claim_locks=[],
            uncommitted_slugs={"my-feature-plan"},
        )
        result = cross_ref_join(inp)
        assert result.uncommitted_work_for_plan is True

    def test_flag_d_not_raised_when_no_uncommitted_slugs(self) -> None:
        """(d) not raised when uncommitted_slugs is empty."""
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[],
            claim_locks=[],
            uncommitted_slugs=set(),
        )
        result = cross_ref_join(inp)
        assert result.uncommitted_work_for_plan is False

    # ── detail dict ──────────────────────────────────────────────────────────────

    def test_detail_dict_populated_per_flag(self) -> None:
        """detail dict must contain keys for each flagged item."""
        lock = ClaimLockFacts(
            slug="orphan", lock_path="/locks/orphan.lock",
            daemon_pid=None, daemon_alive=False, reap_status="free",
        )
        inp = CrossRefInput(
            worktrees=[],
            plans=[],
            registry_records=[],
            claim_locks=[lock],
            uncommitted_slugs={"wip-plan"},
        )
        result = cross_ref_join(inp)
        assert "orphan" in result.detail
        assert "orphan-claim-lock" in result.detail["orphan"]
        assert "wip-plan" in result.detail
        assert "uncommitted-work" in result.detail["wip-plan"]

    def test_all_four_flags_can_be_raised_simultaneously(self) -> None:
        """All four flags may be raised at once from a single input."""
        wt = _dead_facts(merge_evidence="merged")
        plan = _in_progress_facts(all_tasks_done=True, has_merge_evidence=False)
        lock = ClaimLockFacts(
            slug="orphan", lock_path="/locks/o.lock",
            daemon_pid=None, daemon_alive=False, reap_status="stale",
        )
        inp = CrossRefInput(
            worktrees=[(wt, "active")],
            plans=[(plan, "tasks-complete-unmerged")],
            registry_records=[],
            claim_locks=[lock],
            uncommitted_slugs={"dirty-plan"},
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is True
        assert result.complete_plan_no_merge_evidence is True
        assert result.orphan_claim_lock is True
        assert result.uncommitted_work_for_plan is True

    def test_flag_a_detail_dict_key_and_flag_name(self) -> None:
        """(a) detail dict must contain the branch name and 'merged-worktree-on-disk' flag."""
        wt = _dead_facts(merge_evidence="merged", branch="feature/done")
        inp = CrossRefInput(
            worktrees=[(wt, "dirty")],  # merged but blocked from prune (dirty)
            plans=[],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is True
        assert "feature/done" in result.detail, (
            "detail dict must be keyed by branch name when branch is set"
        )
        assert "merged-worktree-on-disk" in result.detail["feature/done"], (
            "detail dict value must include 'merged-worktree-on-disk' flag name"
        )

    def test_flag_a_detail_dict_uses_path_when_no_branch(self) -> None:
        """(a) detail dict falls back to worktree path when branch is None."""
        wt = _dead_facts(merge_evidence="merged", branch=None, is_detached=True)
        inp = CrossRefInput(
            worktrees=[(wt, "detached")],
            plans=[],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.merged_worktree_on_disk is True
        assert wt.path in result.detail, (
            "detail dict must fall back to worktree path when branch is None"
        )
        assert "merged-worktree-on-disk" in result.detail[wt.path]

    def test_flag_b_detail_dict_key_and_flag_name(self) -> None:
        """(b) detail dict must contain the plan slug and 'tasks-complete-unmerged' flag."""
        plan = _in_progress_facts(
            slug="my-finished-plan", all_tasks_done=True, has_merge_evidence=False,
        )
        inp = CrossRefInput(
            worktrees=[],
            plans=[(plan, "tasks-complete-unmerged")],
            registry_records=[],
            claim_locks=[],
        )
        result = cross_ref_join(inp)
        assert result.complete_plan_no_merge_evidence is True
        assert "my-finished-plan" in result.detail, (
            "detail dict must be keyed by plan slug for flag (b)"
        )
        assert "tasks-complete-unmerged" in result.detail["my-finished-plan"], (
            "detail dict value must include 'tasks-complete-unmerged' flag name"
        )


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class TestCLISmoke:
    """CLI must parse and emit valid JSON without filesystem side effects."""

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, _SCRIPT] + list(args),
            capture_output=True,
            text=True,
        )

    def test_classify_worktree_cli_json_output(self) -> None:
        """classify-worktree CLI returns valid JSON with 'class' and 'action' fields."""
        facts = {
            "path": "/wt/test",
            "branch": "feature/x",
            "head_sha": "abc",
            "is_detached": False,
            "has_uncommitted": False,
            "has_unpushed": False,
            "is_head_ancestor_of_default": True,
            "default_branch": "main",
            "remote_reachable": True,
            "merge_evidence": "merged",
        }
        result = self._run_cli("classify-worktree", "--json", json.dumps(facts))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        parsed = json.loads(result.stdout)
        assert "class" in parsed
        assert "action" in parsed
        assert parsed["class"] == "dead"

    def test_classify_plan_cli_json_output(self) -> None:
        """classify-plan CLI returns valid JSON with 'class' and 'action' fields."""
        facts = {
            "slug": "test-plan",
            "path": "/plans/test-plan",
            "has_tasks_file": True,
            "all_tasks_done": False,
            "has_only_precontext": False,
            "has_merge_evidence": False,
            "latest_activity_ts": _recent_ts(),
        }
        result = self._run_cli("classify-plan", "--json", json.dumps(facts))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        parsed = json.loads(result.stdout)
        assert "class" in parsed
        assert parsed["class"] == "in-progress"

    def test_classify_plan_cli_staleness_override(self) -> None:
        """--staleness-days parameter is passed through and changes classification."""
        facts = {
            "slug": "old-plan",
            "path": "/plans/old-plan",
            "has_tasks_file": True,
            "all_tasks_done": False,
            "has_only_precontext": False,
            "has_merge_evidence": False,
            "latest_activity_ts": _old_ts(days=5),  # 5 days old
        }
        # With default 14-day threshold → in-progress.
        result_fresh = self._run_cli("classify-plan", "--json", json.dumps(facts))
        parsed_fresh = json.loads(result_fresh.stdout)
        assert parsed_fresh["class"] == "in-progress"

        # With 3-day threshold → stale-in-progress.
        result_stale = self._run_cli(
            "classify-plan", "--staleness-days", "3", "--json", json.dumps(facts)
        )
        parsed_stale = json.loads(result_stale.stdout)
        assert parsed_stale["class"] == "stale-in-progress"

    def test_invalid_merge_evidence_cli_exits_nonzero(self) -> None:
        """Invalid merge_evidence in CLI input must exit non-zero."""
        facts = {
            "path": "/wt/bad",
            "branch": "x",
            "head_sha": "abc",
            "is_detached": False,
            "has_uncommitted": False,
            "has_unpushed": False,
            "is_head_ancestor_of_default": True,
            "default_branch": "main",
            "remote_reachable": True,
            "merge_evidence": "INVALID_VALUE",
        }
        result = self._run_cli("classify-worktree", "--json", json.dumps(facts))
        assert result.returncode != 0
