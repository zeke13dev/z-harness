# Adaptive INTENT — Lighter-than-SDD Operating Model

> **Status:** Active default as of 2026-06-16.
> **Config gate:** `workflow.planning_mode` (default `intent`). Set to `full` for legacy SDD.

Adaptive INTENT replaces strict spec-driven development (SPEC.md → PLAN.md → TASKS.md, frozen
up-front) as the default z-harness planning paradigm. Instead of a thick frozen spec, it uses:

- A **thin frozen contract** (`INTENT.md`) authored at planning time and immutable after the
  execution boundary is crossed.
- An **emergent BFS task-tree** generated and frozen one level at a time, each level informed
  by the prior level's actual outcomes.
- An append-only **`LEDGER.md`** that accumulates decisions and deviations as the audit trail
  read by final review.

---

## Core insight

The win is a *thin* artifact, not a *mutable* one. INTENT is authored loosely, then frozen at the
execution boundary. Emergence lives in the task-tree *between* BFS levels, not in the contract.

---

## INTENT.md — the frozen contract

**Written by** `/z-plan` in intent mode (default).
**Frozen by** `/z-implement-all` at first execution (idempotent re-freeze on resume).
**Immutable after** `frozen_at` is stamped — Invariant 1.

### Frontmatter fields

```yaml
---
artifact: intent
slug: <slug>
level: quick | standard | deep
generated_at: <iso>
frozen_at: <iso or "pending">   # "pending" until /z-implement-all stamps it
planning_mode: intent
---
```

Validated by `scripts/intent-schema.py validate-intent` (lines 216–290).

### Required sections per level

| Section | L1 (quick) | L2 (standard) | L3 (deep) |
|---------|-----------|---------------|----------|
| `## Intent` | required | required | required |
| `## Acceptance checklist` | required | required | required |
| `## Not doing` | optional | required | required |
| `## Consider for this` | optional | required | required |

Level definitions are in `agents/intent-classifier.md` (lines 15–17).
Section-presence check is in `scripts/intent-schema.py` (lines 72–73, 267–282).

### Acceptance checklist lint

`scripts/intent-schema.py lint-criteria` (lines 297–337) flags criteria with non-observable
predicates (`runs`, `works`, etc.) that have no concrete object following them. Lint runs
before INTENT.md is written by `/z-plan` (Decision D8).

### Re-opening a frozen INTENT

To amend a frozen contract: `/z-amend` calls `reopen-intent "$BASE/INTENT.md"` via
`scripts/intent-schema.py reopen-intent` (lines 377–427), which sets `frozen_at: pending`.
The next `/z-implement-all` re-freezes before executing. This is Invariant 1's escape hatch —
always go through the explicit re-open path; never edit `frozen_at` directly.

---

## BFS task-tree

Tasks are generated in **levels** — Level 0 is the first independent batch derived from INTENT;
Level N+1 is generated from Level N outcomes + still-unmet acceptance criteria.

### Level freeze (Invariant 2)

While a level executes, its `TASKS.md` is immutable. This keeps `session-helpers.sh`
`done_set_hash` / resume valid. Mutation only happens at level boundaries.

### Level generation

The `agents/task-tree-generator.md` (Sonnet) is dispatched once per level by `/z-implement-all`.
Inputs: frozen INTENT snapshot, LEDGER so far, level number, unmet criteria, prior-level outcomes.
Output: a canonical `TASKS.md` batch for this level only — all tasks independent of each other
(cross-level dependencies are deferred to the next level). Each task carries `**Advances:** criterion #N`
linking it back to the frozen INTENT acceptance checklist.

Dispatch seam in `commands/z-implement-all.md` (lines 654–678):
```bash
GENERATOR_OUT="$(Agent(
  subagent_type="task-tree-generator",
  ...
  level: ${CURRENT_LEVEL}
  unmet_criteria: ${UNMET_JSON}
  ...))"
```

### Level cap + budget guard

The BFS loop in `/z-implement-all` (lines 574–598) enforces:
- **Level cap:** `workflow.intent_bfs_level_cap` (default 6). When `CURRENT_LEVEL >= cap`, the
  loop halts with `intent_bfs_level_cap_reached`.
- **Token budget guard:** `workflow.cost.token_budget`. When remaining budget drops below 30 000
  tokens the loop halts with `intent_bfs_budget_exhausted`.

### Acceptance-criteria evaluation (checkpoint)

After each level completes, `/z-implement-all` calls:
```bash
python3 scripts/intent-schema.py evaluate-acceptance \
  "$INTENT_FILE" "$LEDGER_FILE" "$CUMULATIVE_DIFF_FILE"
```
(`scripts/intent-schema.py` lines 635–700.) If the verdict is `DONE`, `BFS_DONE=1` and the loop
exits. Otherwise `CURRENT_LEVEL` increments and the next level is generated.

### Resume safety

The level state file (`$ARCHIVE_DIR/.intent_level_state`) persists `<level_number> <done_set_hash>`
after each completed level. On resume, `/z-implement-all` (lines 539–565) re-reads the state file,
validates the hash, and re-enters the loop at `CURRENT_LEVEL = STORED_LEVEL + 1`.

---

## LEDGER.md — append-only realized-plan

**Created** by `scripts/intent-schema.py bootstrap-ledger` (lines 494–572) on first execution
(idempotent — no overwrite).
**Appended** after each level: implementer returns `LEDGER_DECISIONS:` + `LEDGER_DEVIATIONS:`
fields (`agents/implementer.md` lines 135–149); the orchestrator writes them under the current
level heading.
**Read by** reviewer + `/z-review-all` as the realized-plan audit trail.

### Schema

```yaml
---
artifact: ledger
slug: <slug>
intent_frozen_at: <iso>
---
## Level 0
### Decisions
- <decision> (advances criterion #N)
### Deviations
- <deviation from tentative tasks> — <why>
## Level 1
...
```

Validated by `scripts/intent-schema.py validate-ledger` (lines 339–375). Append-only is Invariant 3.

---

## Levels (L1 / L2 / L3)

| Level | Name | INTENT sections | Cross-LLM consult |
|-------|------|----------------|-------------------|
| L1 | quick | Intent + Checklist | skipped |
| L2 | standard | + Not doing + Consider for this | optional |
| L3 | deep | all four sections | always |

### intent-classifier — level selection

`agents/intent-classifier.md` (Haiku, lines 1–7) reads the raw task prompt + repo signals and
returns `LEVEL: quick|standard|deep` + `REASON:` + `SIGNALS:`. Advisory — the orchestrator
announces the pick and the user can override inline.

Dispatch seam in `commands/z-plan.md` (lines 507–514):
```bash
INTENT_CLASSIFIER_OUT="$(Agent(
  subagent_type="intent-classifier",
  task_prompt: "...",
  repo_root: "...",
  forced_level: "${INTENT_LEVEL_CONFIG}"
))"
```

Fallback: if the classifier returns non-zero or empty, `/z-plan` defaults to `standard`
(`commands/z-plan.md` lines 521–524).

### Config override

Set `workflow.intent_level` in `.z-harness/config.toml` to `quick`, `standard`, or `deep` to
bypass the classifier entirely (`commands/z-plan.md` lines 490–494).

---

## Legacy fallback — SPEC-detection (Invariant 4)

Mode detection at `/z-implement-all` step 3.5 (`commands/z-implement-all.md` lines 413–423):

```bash
if [ -f "$BASE/SPEC.md" ]; then
  IMPLEMENT_MODE="legacy"
elif [ -f "$BASE/INTENT.md" ]; then
  IMPLEMENT_MODE="intent"
fi
```

`SPEC.md` presence → full legacy SDD path (SPEC/PLAN/TASKS), completely unchanged.
Legacy plans are never auto-migrated. This invariant is tested explicitly (never route a
SPEC.md plan through the INTENT engine).

Same detection in `/z-review-all` (`commands/z-review-all.md` lines 172–183) and `/z-amend`
(`commands/z-amend.md` lines 41–43).

---

## Four workflow.* config knobs

All in `scripts/config.py` `DEFAULTS["workflow"]` (lines 78–81); file-resolvable via
`config.py get workflow.<key>` from `.z-harness/config.toml`. No new env vars (Invariant 5).

| Key | Default | Values | Meaning |
|-----|---------|--------|---------|
| `workflow.planning_mode` | `intent` | `intent` \| `full` | Default planner paradigm. `full` = legacy SDD. |
| `workflow.intent_level` | `auto` | `auto` \| `quick` \| `standard` \| `deep` | Forced level, or `auto` = classifier picks. |
| `workflow.intent_parallel_levels` | `false` | bool | Execute independent same-level tasks in parallel (gated-off by default). |
| `workflow.hermes_enabled` | `false` | bool | Gates ALL old Hermes parallelism machinery. Default OFF (Invariant 6). |

Validators at `scripts/config.py` lines 180–183. Bool coercers at lines 244–247.

---

## Hermes gating (Invariant 6)

All old Hermes machinery (workstream generation, N=2 cross-cluster dispatch, `write-handoff.sh`
call, `scope-extractor` dispatch) is wrapped in `if workflow.hermes_enabled` guards. Default
`false` → none fire. The `scripts/hermes/` files are kept (not deleted) to prevent bit-rot;
deletion is a separate future task.

Gate seam in `commands/z-implement-all.md` (lines 388–404) and `commands/z-plan.md`.

To revive Hermes:
```toml
[workflow]
hermes_enabled = true
```

---

## Reviewer + final review changes

**Per-task reviewer** (`agents/reviewer.md` line 2): in INTENT mode reads the full frozen INTENT
narrative (all four sections) + LEDGER + durable tier (KERNEL, INVARIANTS.json, STYLE). Cites
failures as "fails acceptance criterion #N" (1-based index in `## Acceptance checklist`).

**`/z-review-all`** (`commands/z-review-all.md` lines 160–203): detects INTENT mode by
`INTENT.md present AND SPEC.md absent`; prefers the frozen snapshot from `archive/*/INTENT.frozen.md`.
Passes `INTENT.frozen.md` + `LEDGER.md` + durable tier to both Flash pre-review prongs instead of
SPEC.md.

---

## /z-amend in INTENT mode

1. Detects `intent` mode by `INTENT.md` present, `SPEC.md` absent (`commands/z-amend.md` line 41).
2. Notes whether `frozen_at` holds a real ISO timestamp.
3. In Phase 6: calls `reopen-intent` to set `frozen_at: pending`; edits INTENT.md body; marks
   TASKS.md stale (`stale_reason: amended-intent`) so the task-tree-generator regenerates rather
   than resumes.

`stale_reason` handling in `commands/z-amend.md` (lines 239–271).
`reopen-intent` in `scripts/intent-schema.py` (lines 377–427).

---

## /z-do and /z-plan-light (deprecated shims)

Both commands now print a deprecation notice and immediately route to `/z-plan`:
- `/z-do` → `/z-plan --quick $ARGUMENTS` (`commands/z-do.md` lines 13–18)
- `/z-plan-light` → `/z-plan --standard $ARGUMENTS` (`commands/z-plan-light.md` lines 13–18)

Command names are preserved for muscle-memory; the bodies are unchanged shims.

---

## Invariants

1. **INTENT.md is immutable after `frozen_at` is stamped.** Edits require explicit `reopen-intent`
   (`scripts/intent-schema.py:377`).
2. **A level's TASKS.md is immutable while that level executes.** Resume safety via
   `done_set_hash` checkpoint (`commands/z-implement-all.md:903`).
3. **LEDGER.md is append-only; never rewritten** (`scripts/intent-schema.py:494`).
4. **Legacy SPEC/PLAN/TASKS plans are detected and run on the unchanged legacy path — zero
   regression** (`commands/z-implement-all.md:416`).
5. **No new env vars.** All new knobs are file-resolvable via `config.py`
   (`scripts/config.py:78`).
6. **Old Hermes machinery never executes unless `workflow.hermes_enabled=true`**
   (`commands/z-implement-all.md:388`).

---

## Key source files

| File | Role |
|------|------|
| `scripts/intent-schema.py` | validate-intent, lint-criteria, validate-ledger, freeze-intent, reopen-intent, bootstrap-ledger, evaluate-acceptance |
| `scripts/config.py` | Four `workflow.*` knobs (lines 78–81, 180–183) |
| `agents/intent-classifier.md` | Haiku level classifier |
| `agents/task-tree-generator.md` | Sonnet BFS level generator |
| `commands/z-plan.md` | Adaptive planner: level announce/override, INTENT.md write, `--full` legacy route, SPEC-detection backward-compat |
| `commands/z-implement-all.md` | BFS engine: freeze, LEDGER bootstrap, generate-execute-checkpoint loop, mode detection |
| `commands/z-amend.md` | re-open frozen contract, invalidate TASKS.md on amendment |
| `commands/z-review-all.md` | Final gate: INTENT + LEDGER as realized-plan contract |
| `agents/implementer.md` | Returns LEDGER_DECISIONS + LEDGER_DEVIATIONS in INTENT mode |
| `agents/reviewer.md` | Reads full INTENT narrative + LEDGER in INTENT mode; cites criterion #N |
