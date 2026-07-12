# z-resume

> Last updated: 2026-07-09
> Covers source: skills/z-resume/SKILL.md, scripts/resume-context.py, scripts/report-context.py, scripts/active-plan-registry.py, skills/z-report/SKILL.md, skills/z-explain/SKILL.md, skills/z-learn/SKILL.md, skills/z-stats/SKILL.md

## Overview

`/z-resume` is the read-only work-thread recovery command for answering: **what was I doing, what state is it actually in, and how can I continue safely?** It accepts fuzzy topics, exact run/slug/branch/worktree/artifact selectors, repo qualifiers, and noninteractive JSON mode, then selects a bounded recovery target or stops at an ambiguity gate.

It does not execute, restart, mutate, or auto-dispatch sibling commands. Safe next commands are recommendations only. `--report` is special but still gated: `/z-resume --report` may reuse `/z-report` machinery only after an unambiguous or explicitly selected target exists.

## Evidence hierarchy

`/z-resume` treats `scripts/resume-context.py` as the durable selection contract. The packet records repo identity, lookback caps, source status, evidence records, candidates, scoring components, negative evidence, current-state reasons, ambiguity state, selected target, warnings, citations, suggested continuations, and optional report target data.

Evidence authority is ordered by bounded, cited facts:

1. Exact selectors supplied by the user (`--run`, `--slug`, `--plan`, `--branch`, `--worktree`, `--artifact`, `--repo`, `--select`) after validation.
2. Current repo identity and configured z-harness state roots.
3. Active-plan registry records for live phase, current task, heartbeat, held paths, branch, worktree, repo id, and wait edges.
4. Plan/run artifacts such as `INTENT.md`, `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `LEDGER.md`, archive artifacts, reports, run briefs, context bundles, events, decisions, and follow-up exports.
5. Git/worktree/branch associations backed by repo id, HEAD/commit evidence, registry records, artifacts, or explicit user input.
6. Validated session/handoff files (`SESSION.md`, `SESSION_CONTEXT.md`, `handoff.json`, `HANDOFF.md`) when their schema, hashes, timestamps, and referenced files agree with current artifacts.
7. Optional bounded cheap inference, stored only as `subagent_judgments`, never as source truth.
8. Memories, follow-ups, and fuzzy topic text as side evidence only.

Memories and follow-ups are side evidence because they can preserve intent, reviewer findings, or later reminders without proving the current worktree, current task, landed state, completion, or ownership of a branch. They may explain why a candidate is relevant, but they never override conflicting registry, artifact, git, session, or handoff evidence.

## Key entry points

- `skills/z-resume/SKILL.md` — command contract, argument forms, evidence hierarchy, ambiguity gate, render shape, report handoff, and adjacent boundaries.
- `scripts/resume-context.py:3942` (`build_context`) — deterministic gather/score/packet producer; no mutation, no hidden expansion, no report rendering, no command dispatch.
- `scripts/report-context.py:1747` (`main`) — existing report context assembler reused only after selected `--report` targets.
- `scripts/active-plan-registry.py:2177` (`main`) — active registry evidence consumed by `/z-resume`; `/z-stats` exposes the live-only diagnostic view.
- `skills/z-report/SKILL.md` — narrative renderer for known targets and selected resume contexts.
- `skills/z-explain/SKILL.md` and `skills/z-learn/SKILL.md` — cited code/system teaching surfaces recommended only after work-thread selection when understanding is the next step.
- `agents/resume-cluster.md` — tool-less Haiku subagent invoked only for bounded Phase 4 cheap inference over a supplied candidate/evidence packet; never a source of truth.

## Target selection and ambiguity

Exact selectors are parsed before fuzzy topic text. A run id, slug, branch, worktree, artifact, or selection token must resolve through cited bounded evidence; branch substrings and worktree basenames are not proof by themselves. Cross-repo candidates must carry repo/source citations, and broader discovery requires explicit `--repo` or `--all-repos` controls with caps.

Interactive ambiguity stops before narrative or report rendering and asks exactly one bounded selection question with top candidates, tokens, dates, repo/worktree/branch hints, confidence reasons, negative evidence, current-state warnings, and citations.

Noninteractive or JSON ambiguity returns `status: needs_selection`, `selected_target: null`, candidate tokens, suggested selection args, and warnings. It must not call `report-context.py`, `report-synth`, `/z-report`, or any renderer while selection is unresolved.

## How it interacts with others

- `active-plan-registry` — `/z-resume` consumes `scripts/active-plan-registry.py list --json` as one bounded evidence provider (live phase/current task/heartbeat/held paths/wait edges/branch/worktree/repo id); `/z-stats` is the narrower live-only diagnostic surface over the same registry.
- `session-handoff` / `handoff-protocol` — `SESSION.md`, `SESSION_CONTEXT.md`, `handoff.json`, and `HANDOFF.md` only influence selected state after schema/hash/timestamp validation; otherwise they degrade to stale side evidence.
- `run-brief` — run-brief artifacts are one of the plan/run artifact families scored by the deterministic candidate clustering in `resume-context.py`.
- `followup-sink` — follow-ups are consumed strictly as side evidence (never proof of current/landed state).
- `z-report` — `--report` reuses `/z-report`'s target/context/rendering machinery (via `scripts/report-context.py --resume-context ...`) only after an unambiguous or explicitly selected target; `/z-resume` never duplicates report rendering itself.
- `z-explain` / `z-learn` — recommended only as advisory next commands after target selection, when the gap is understanding rather than work-thread recovery.
- `z-stats` — narrower sibling limited to currently registered active plans; `/z-resume` is the superset that also recovers historical/fuzzy/cross-repo targets.

## Adjacent command boundaries

| Command | Use when | Boundary with `/z-resume` |
|---|---|---|
| `/z-resume` | You need work-thread continuation/reorientation: "what was I doing and how do I continue safely?" across bounded evidence. | Selects a prior/current work thread, reports state and caveats, and recommends safe next commands without executing them. |
| `/z-stats` | You only need active-plan registry status, wait edges, or path-overlap for currently registered runs. | Live active plans only; it does not recover fuzzy topics, historical runs, branches, worktrees, reports, sessions, or cross-repo artifacts. |
| `/z-report` | You already know the report target: run, slug, PR, range, base, or worktree. | Produces a narrative for a known/resolved target. Fuzzy prior-work recovery routes to `/z-resume`; `/z-resume --report` delegates only after selection. |
| `/z-explore` | You need code terrain reconstruction: where code lives, entry points, seams, or a MAP-like source survey. | Code architecture is not work-thread state. `/z-resume` may recommend `/z-explore` after selection when the gap is terrain. |
| `/z-explain` | You want one cited answer teaching a file, symbol, subsystem, repo orientation, or behavior lens. | Teaching starts after the target is known; work-thread recovery/reorientation routes to `/z-resume`. |
| `/z-learn` | You want an interactive progressive tutor over code/system understanding. | It resumes a learning session, not a z-harness work thread. Use `/z-resume` for "where did we leave off?" across plan/run/worktree evidence. |
| `/z-attend resume` | You already know the attended chain run and want to re-enter it after its handoff predicate validates. | `/z-resume` can identify/cite the likely attend run, but does not run attended chains. |
| `/z-overnight resume` | You already know the overnight run id/state and want to continue unattended orchestration. | `/z-resume` can identify/cite the likely overnight run, but does not resume unattended orchestration. |

## Examples

- Fuzzy recovery in the current repo: `/z-resume "resume-context ranking"`
- Most plausible current work thread: `/z-resume current`
- Most recent bounded thread: `/z-resume latest --lookback 14d`
- Exact slug recovery: `/z-resume --slug z-resume`
- Exact run recovery: `/z-resume --run 20260601T120000Z-implement`
- Branch/worktree recovery: `/z-resume --branch feature/resume-context` or `/z-resume --worktree ../z-harness-resume`
- Cross-repo topic recovery: `/z-resume --repo qt-bot --topic "missing fills report"`
- Noninteractive selection packet: `/z-resume "resume docs" --json`
- Follow an ambiguity token: `/z-resume --select cand-2`
- Render a report after selection: `/z-resume --slug z-resume --report standard --profile=technical-handoff`

## Edge cases / gotchas

- Recency affects ranking, not truth. Older canonical decisions linked to a selected target remain attached as linked evidence.
- Source caps and truncation are warnings, not silent omissions.
- `SESSION.md` and handoff files influence state only when validation succeeds; stale or conflicting files degrade to side evidence.
- Worktree and branch evidence is associative unless backed by repo id, registry, HEAD/commit, artifact, or explicit user selection.
- Cross-repo answers must cite the selected repo/worktree and warn when the safe next step requires changing directories.
- `/z-resume` never marks a plan complete, restarts a service, mutates registry state, or auto-opens another command.
- Phase 4 cheap inference (via the `resume-cluster` agent) is optional, bounded to at most 2 calls, tool-less, and can only degrade to `subagent_judgments`; it never overrides deterministic `source_status`, `primary_state`, `selected_target`, evidence, or citations.
