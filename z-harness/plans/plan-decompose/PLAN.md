# PLAN — plan-decompose (`/z-plan-split`)

## Goal

Add `/z-plan-split <topic>` — a pre-emptive scope splitter that fans a big topic out into N narrow scopes (`cluster-planner` subagents in parallel), each producing its own focused `/z-plan`-equivalent. Light file-overlap reconciliation writes a SHARED-CONCERNS.md observation note. `/z-implement-all` is extended to walk the resulting nested tree.

The intent: catch "this should be 4 focused plans, not 1 sprawling plan" *before* a big `/z-plan` run produces a 60-task sprawling plan that's hard to drive to done.

## Decisions (with rationale)

| ID | Decision | Pick | Rationale |
|----|---|---|---|
| D1 | Split identification | C (B with `--clusters=` override) | Default to auto-proposed-with-confirm matches /z-brainstorm UX; flag override covers the "I already know my axes" case. |
| D2 | cluster-planner phases | B (premise + decision gate, no per-leaf consult) | Unanimous cross-LLM consult. Per-leaf consult multiplies cost without proportional benefit on narrow scopes (0-1 decisions). Decision-gate escalation to main thread keeps borderline cases safe. |
| D3 | Reconciliation depth | A + ack-gate | Codex argued for B (active shared/ scaffold); Gemini argued for A (passive note); both flagged that A without a gate is too easy to ignore. Compromise: SHARED-CONCERNS.md as observation, but `/z-implement-all` hard-halts on `acknowledged: false`. Avoids fake-scaffold "looks like progress" and forces explicit acknowledgment. |
| D4 | Sub-plan failure | A (halt failed cluster, others continue; total-failure halt) | Standard /z-brainstorm pattern. Partial trees are valid outputs — user can run /z-implement-all on what completed. |
| D5 | Decision-gate propagation | B (halt affected leaf only; siblings continue) | Cross-leaf concurrency preserved. User resolves one gate while other planners work. Resolved decision archives to MANIFEST so future readers see context. |
| D6 | Manifest format | C (single MANIFEST.md with listing + run-order) | Single source of truth. Codex flagged: MANIFEST is authoritative; cluster-status, paths, run-order, skip-markers all there. |
| D7 | /z-implement-all extension | A + one-level cap | Unanimous cross-LLM. Extending existing slug-discovery (recurse on MANIFEST.md detection) avoids maintaining two task-runner state machines. Hard cap at one level prevents tree-of-trees state explosion. |
| D8 | Command name | `/z-plan-split` | User-locked at Phase 2.5 gate. |
| D9 | Input forms (v1) | A (free-text topic only) | v1 simplicity. `--from-audit` / `--from-brainstorm` are v2; v1 user can paste audit findings as free-text topic. |
| D10 | Re-run on existing root | overwrite / abort (drop append) | Matches T003 cycle-2 precedent — append flow was under-specified there too. |

## Non-goals (v1)

- Cross-cluster task parallelism. Clusters run sequentially in MANIFEST order; tasks within a cluster honor existing N=3 batching.
- Auto-detection of "this should be /z-plan-split not /z-plan." Per `feedback-explicit-commands`, opt-in via explicit command.
- Per-leaf cross-LLM consult. Cost discipline.
- Semantic file-overlap detection. Path-only heuristics.
- Tree-of-trees nesting. One-level cap.
- Active `shared/` plan auto-generation. The user runs `/z-plan --slug=<root>/shared/` manually if the SHARED-CONCERNS findings warrant it.
- `--from-audit` and `--from-brainstorm` input chains. v2.

## Approved shortcuts

None. Every decision picked the robust option.

## Phases

The implementation breaks into independently-implementable tasks. Mirror-pair files (`commands/<x>.md` + `skills/<x>/SKILL.md`) collapse to single tasks per the brainstorm-and-research precedent.

### Phase A — Foundations
- T001: Create `agents/cluster-planner.md` (new subagent definition with the 6-phase contract from SPEC).

### Phase B — `/z-plan-split` command
- T002: Create `commands/z-plan-split.md` + `skills/z-plan-split/SKILL.md` (byte-identical mirror, one dispatch).

### Phase C — `/z-implement-all` extension
- T003: Modify `commands/z-implement-all.md` + `skills/z-implement-all/SKILL.md` to detect MANIFEST.md, walk clusters sequentially, validate ack-gate + cluster-finalized + tree-depth.

### Phase D — Documentation
- T004: Update `README.md` with `/z-plan-split` documentation, new event kinds, v1 limitations.

**Total: 4 tasks.**

## Risks (carry-forward to implementation)

- **R1.** `cluster-planner` is a new agent type. Conservative-flagging behavior (over-escalate borderline decisions) is the safety mechanism; if the agent under-flags, leaves silently make wrong calls. Mitigation: T001 acceptance criteria explicitly require the conservative-flagging rule with examples; codex-reviewer should verify.

- **R2.** Mirror-pair drift (`commands/z-plan-split.md` vs `skills/z-plan-split/SKILL.md`) — established mitigation: collapse into one task with byte-identity check.

- **R3.** `/z-implement-all` already has 5+ hard rules (skip markers, parallel batching, MAX_ATTEMPTS, halt taxonomy, telemetry). Adding MANIFEST recursion is non-trivial. Mitigation: T003 acceptance criteria include negative-case tests (nested MANIFEST → tree_depth_exceeded; unacknowledged shared → halt; cluster_planning → halt).

- **R4.** Ack-gate UX. User has to edit a YAML field in SHARED-CONCERNS.md to proceed. If they don't notice the requirement, they get a halt event with a clear instruction. The `--ack` CLI flag is the escape hatch. Mitigation: error message includes both options (edit frontmatter OR pass --ack).

- **R5.** `/z-plan-split` Phase 1 cluster proposal happens in main thread without a doc-fetcher unless `docs/llm/INDEX.json` exists. For topics in repos without LLM-tier docs, cluster naming may be off. Mitigation: user always confirms via AskUserQuestion with edit option. Bad proposal → user corrects.

- **R6.** Re-entrancy: `cluster-planner` subagent dispatches `doc-fetcher` subagent in its Phase 1. Two-level subagent nesting is supported by the `Agent()` tool in z-harness's existing patterns (`/z-implement-all` already does this: orchestrator → implementer → no further nesting needed there; but `/z-plan` Phase 1 does orchestrator → doc-fetcher). Mitigation: keep cluster-planner's doc-fetcher dispatch single-shot, no nesting beyond that.

- **R7.** SHARED-CONCERNS.md noise — Gemini's "boy who cried wolf" risk. Two clusters touching `utils.ts` will always flag. Mitigation accepted as v1 limitation: severity heuristic surfaces schema/config/migration files as `high`, code-extension matches as `low`/`medium`; user judges via ack-gate. v2: track function-level overlap (much harder).

## Consumed precontext

None — this `/z-plan` run was fresh; no `BRAINSTORM.md` or `RESEARCH.md` existed for the `plan-decompose` slug. Conversation context (the discussion thread that led here) is captured in `archive/<RUN>/proposed-shape.md` for audit.

## DRY / KISS / SOLID applied

- **DRY:** Reuses existing `complexity-classifier` for task complexity stamping; reuses `doc-fetcher` for scaffolding; reuses MANIFEST/SHARED-CONCERNS YAML-frontmatter pattern from BRAINSTORM/RESEARCH. No new helper scripts.

- **KISS:** Sequential cluster execution (no cross-cluster task parallelism in v1); path-only overlap detection (no semantic pass); single-level recursion (no tree-of-trees); free-text input only (no flag-based input chains).

- **SOLID:** Each command does one thing. `/z-plan-split` splits + reconciles (passively). `/z-plan` plans one scope. `/z-implement-all` implements (extended to walk trees, not to plan or split). `cluster-planner` is a constrained sub-/z-plan optimized for narrow scopes.
