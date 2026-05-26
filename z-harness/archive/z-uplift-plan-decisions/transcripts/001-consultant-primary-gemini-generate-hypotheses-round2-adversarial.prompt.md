# Mode: generate-hypotheses-round2-adversarial
## Schema version: hypothesis_round2_v1

## Problem

The qt-bot repo recurringly sees local `main` and `origin/main` diverge. AI agents recommend `git push --force-with-lease origin main` claiming origin has a "stale subset" of local commits. User accepts blindly. Concrete reflog from 2026-05-25 shows: commit 908fd94 + ce95685 pushed at 16:21-16:23; `reset --hard HEAD~2` at 16:27 discarding them locally; rebuild via 179d1de + dc17640 at 16:43-16:46; `rebase (finish): onto ce956851...` at 16:57 (onto the discarded SHA). 5 resets + 3 rebases in 3 days. Worktree `.claude/worktrees/lucid-engelbart-655024` is active.

## Evidence Inventory

- EVID-001: 2026-05-25 16:27:56 `reset: moving to HEAD~2` removes 908fd94+ce95685.
- EVID-002: 908fd94 + ce95685 both still reachable from origin/main today.
- EVID-003: 5 reset events + 3 rebases between 2026-05-22 and 2026-05-25 on main.
- EVID-004: Worktree `.claude/worktrees/lucid-engelbart-655024` on branch `claude/lucid-engelbart-655024`, head 2f42def.
- EVID-005: Agent prompt quote: "Overwrites 908fd94 + ce95685 with my (superset, verified) commit. origin's commits were unauthorized and their content is a stale subset of mine."
- EVID-006: User runs parallel sessions sometimes; does not track unsolicited commits.
- EVID-007: 16:57 rebase target = ce956851 (the discarded SHA).
- EVID-008: 10+ uncommitted modifications in working tree currently.

## Current Merged Hypothesis Pool

| id | claim | proposed_by | overlap_count |
|---|---|---|---|
| H001 | Parallel Claude Code session in worktree/separate clone commits+pushes to main; primary unaware, resets behind origin. | [orchestrator, codex, gemini] | 3 |
| H002 | Agent runs `reset --hard HEAD~N` or `--soft`+recommit to consolidate WITHOUT first fetching+checking origin for the about-to-be-discarded commits. | [orchestrator, codex, gemini] | 3 |
| H003 | Parallel sessions race on rebase against a moving origin/main — concurrent rebases produce conflicting SHAs. | [codex, gemini] | 2 |
| H004 | A subagent (implementer or remote-runner) runs `git push` as part of its tool calls — incremental pushes land on origin as side effect. | [orchestrator, codex] | 2 |
| H005 | Agent operates on stale origin view (no `git fetch` before reset/rebase recommendation), unaware commits are already pushed. | [codex, gemini] | 2 |
| H006 | qt-bot CLAUDE.md frames local as canonical / origin as mirror, biasing agents toward force-push. | [orchestrator] | 1 |
| H007 | User commits manually in another terminal; AI treats those as "unauthorized." | [orchestrator] | 1 |
| H008 | `git rebase --autostash` silently stashed work; later `reset --hard` discarded the rebase result. | [codex] | 1 |
| H009 | Reset on a dirty tree loses uncommitted work that gets re-committed in a different shape, producing different SHAs than what was pushed. | [gemini] | 1 |

## Ask

Return exactly TWO markdown tables in this order:

**TABLE 1 — NEW hypotheses** (orthogonality hunt — failure modes absent from the pool). Columns: `| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |` where `orthogonality_to` is comma-separated H<NNN> IDs this fills a gap relative to. `test_cost` ∈ {free, cheap, medium, expensive}. `parallel_safe` ∈ {true, false} — true only if test mutates no shared state.

**TABLE 2 — CRITIQUES** of existing pool rows. Columns: `| target_id | critique_type | problem | recommended_action | merge_with_id |` where `target_id` is H<NNN> (required), `critique_type` ∈ {non_discriminating_test, false_parallel_safe, duplicate, weak_claim, unclear_prediction}, `problem` concrete (no "looks good", no empty cells), `false_parallel_safe` rows must cite specific mutation, `merge_with_id` populated ONLY when critique_type == duplicate.

**Your value is orthogonality and critique, not endorsement.** Do not return rows that merely restate existing pool entries.
