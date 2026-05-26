# Decisions — compaction-cadence

## D1. Scope of usage-% deletion

- **Decision:** What to do with `Z_HARNESS_PAUSE_AT_PCT` and all "current usage %" language.
- **Options:**
  - (a) Delete env var + spec block entirely from `/z-implement-all` (and any mirrored skill copy).
  - (b) Keep env var as a no-op for backward compat; remove spec language only.
- **Tentative:** (a). The var has never functioned; nothing depends on it; deleting outright matches the user's "cut broken features" preference. Mirror the deletion in `skills/z-implement-all/SKILL.md` and any agy/cursor/codex exports.
- **Consult? no.** Following user direction; no public API beyond an env var no one's relying on.

## D2. Primary breakpoint trigger in `/z-implement-all`

- **Decision:** What deterministic signal triggers a pause+notify in the implement-all loop.
- **Options:**
  - (a) **Every N completed tasks** — N configurable via `Z_HARNESS_COMPACT_EVERY_TASKS` (default `5`).
  - (b) **Every N batches** (where a batch is up to 3 parallel tracks) — N default `2`.
  - (c) **Cumulative implementer-subagent count** (default `8`) — counts retries too.
  - (d) Multi-trigger: any of (a) OR a 2nd signal (e.g. wall-time since last pause).
- **Tentative:** (a) with N=5. Tasks are the unit the user thinks in, the unit TASKS.md displays, and the unit that survives across re-invocations (the orchestrator can count completed `[x]` checkboxes on resume).
- **Consult? yes.** Picks a default that shapes everyone's experience; reversibility = config change so the cost is low, but the choice is articulable (≥2 candidates, materially different).
- **Trigger:** Articulation rule.

## D3. Add breakpoint in `/z-review-all`?

- **Decision:** Does `/z-review-all` need a pause point.
- **Options:**
  - (a) **Yes — before Phase 4 consultant spawn** (the heaviest single context burn in the whole harness).
  - (b) **No** — review-all is one-shot; user can manually `/compact` before invoking.
- **Tentative:** (a). Phase 4 reads the cumulative diff + SPEC + PLAN + TASKS + concept docs and hands them to two consultants — exactly the hot spot identified in Phase 1. A pre-Phase-4 push notification ("about to spawn consultants; `/compact` first if context is heavy, then continue") costs nothing if user dismisses.
- **Consult? yes.** Affects a public surface (a command's behavior) and choice between candidates is articulable.
- **Trigger:** Public API / module boundary.

## D4. Add breakpoint in `/z-maintain-docs`?

- **Decision:** Does `/z-maintain-docs` need a pause point.
- **Options:**
  - (a) Yes — between doc-updater batches when stale concept count ≥ threshold (default 6, i.e. 2 batches).
  - (b) Yes — only at the optional `--audit` prong before consultant spawns.
  - (c) No.
- **Tentative:** (b). Plain doc-updates are Sonnet subagents with fresh context; they don't pressure the orchestrator much. The `--audit` prong is the only place consultants enter `/z-maintain-docs`, and that mirrors the pre-consultant breakpoint in (D3).
- **Consult? no.** Local mechanical decision; reversible by config tweak; well-defined surface.

## D5. Event names and exit semantics

- **Decision:** What event names and exit behavior for new breakpoints.
- **Options:**
  - (a) Reuse `usage_pause` everywhere (semantic stretch — not usage-driven anymore).
  - (b) New event name `compaction_pause` with `{trigger: "task_count" | "pre_consult" | "..."}` payload.
- **Tentative:** (b). Honest naming; lets `/z-stats` distinguish reasons. Keep `usage_pause` reserved for if/when a real usage signal exists.
- **Consult? no.** Naming, but internal event schema only — no external consumer yet.

## D6. Push notification message + resume contract

- **Decision:** What the notification says, and how resume works.
- **Options:**
  - (a) "Compaction breakpoint at task N/M. Run `/compact` (or `/clear`), then re-invoke `/z-implement-all` to resume from current TASKS.md state."
  - (b) Same as (a) but with `/clear` recommended over `/compact` for inter-batch (more aggressive cleanup; orchestrator has no in-flight state because TASKS.md is the durable state).
- **Tentative:** (b). The orchestrator's resume is already idempotent (re-read TASKS.md, pick next pending) — so `/clear` is safe and reclaims more context. Mention `/compact` as the lighter alternative.
- **Consult? yes.** Cross-LLM second opinion on whether `/clear` is actually safer than `/compact` given the resume semantics. Articulation: clear vs compact trade-offs are non-obvious.
- **Trigger:** Articulation rule + reversibility (recommending `/clear` and discovering it loses needed state would be unpleasant).

## D7. Documentation / discoverability

- **Decision:** Where the new config lives in user-facing docs.
- **Options:** (a) Add a "Compaction policy" subsection to README; update `docs/human/commands.md` and the `commands` concept JSON; cross-reference in `commands/z-implement-all.md` body.
  (b) Just inline in the command files.
- **Tentative:** (a). Two-tier docs are the project's discipline; respect them.
- **Consult? no.** Mechanical.

## Consult tally

- Consult-flagged: D2, D3, D6 → **3 decisions**. Under the 5 cap. ✓
