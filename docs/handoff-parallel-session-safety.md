# Handoff — z-harness parallel-session safety

**Status:** ADDRESSED by active-plan-coordination (external default base + lockless awareness registry + session stamping); see `docs/human/active-plan-registry.md`
**Severity:** high — silent, total, cross-session loss of all planning artifacts
**Filed:** 2026-06-01, from the deepswe-pier `/z-implement-all` run (an incident occurred mid-run)
**Owner:** resolved — active-plan-coordination plan (worktree: active-plan-coordination, tasks T001–T016)

> This file lives under `docs/` (git-tracked) **on purpose**: the bug it describes destroys
> everything under the gitignored `z-harness/` tree, so a handoff written there would be wiped by
> the very failure it documents.

---

## Resolution

**Option chosen:** B (external default base) + awareness registry + session stamping. Option C (per-session git worktrees) was deferred.

The active-plan-coordination plan implements:

1. **External default base** (T001, T002, T015) — `scripts/plan-path.sh`'s `z_harness_base()` resolves the artifact base through a five-tier fallback chain (XDG_STATE_HOME > HOME/.local/state > git-common-dir > pwd) that places plans outside the gitignored working tree by default. `git clean -fdx` cannot reach files outside the checkout. The Phase-D default flip (`Z_HARNESS_EXTERNAL_DEFAULT=1`) activates tiers 2–4 automatically.

2. **Anchor enforcement** (T002) — the first `z_harness_base()` call writes `<git-common-dir>/.z-harness-base` (shared across all worktrees; survives `git clean`). Every subsequent call validates the anchor, emitting `base_mismatch_detected` and hard-failing on tier disagreement. Prevents the split-brain failure mode both reviewers flagged.

3. **Lockless awareness registry** (T006) — `scripts/active-plan-registry.py` maintains per-run JSON records under `<base>/active-plans/`. Concurrent sessions can discover each other's active plans and scope. Overlap is advisory (exit 10); `Z_HARNESS_STRICT_OVERLAP=1` makes `explicit`×`explicit` exact path matches a hard halt (exit 20).

4. **Session stamping** (T007) — every run carries an attributable session id so concurrent runs are distinguishable in the registry and in telemetry.

5. **Live-run migration barrier** (T013) — `scripts/migrate-plan-layout.sh` refuses to migrate while any record shows `status:running`, preventing TOCTOU artifact corruption.

See `docs/human/active-plan-registry.md` for the full design reference and `docs/human/config.md` for env-knob documentation.

---

## TL;DR

z-harness stores **all** run artifacts (every plan's SPEC/PLAN/TASKS, archives, `events.jsonl`,
`metrics.jsonl`, locks, and the `bench/` + `bench/pier/` code) under the repo's **`z-harness/`
directory, which is gitignored** (`.gitignore:32`). Those files are therefore working-tree-only and
never backed by git. When **any** concurrent Claude Code session running in the same checkout does
branch work and a `git clean -fdx` (a routine, legitimate operation), it **deletes the entire
`z-harness/` tree — every plan from every session at once**, unrecoverably (gitignored ⇒ not in git
⇒ not recoverable via git).

The user runs **many concurrent sessions** in this one repo. So this is not an edge case; it's a
standing hazard that already caused real loss (see Incident).

---

## Incident (the evidence)

During `/z-implement-all` on the `deepswe-pier` plan, mid-run:

- A **parallel session** created/merged a branch: reflog showed
  `74ab88d HEAD@{0}: merge add-consultant-arms: Fast-forward` and
  `commit: Add cursor + agy consultant-arm providers` — **not** made by the running orchestrator.
- The `z-harness/` tree collapsed from **~25 plan directories to 3** (`archive/`, `deepswe-pier/`,
  `metrics.jsonl` — only the dirs the running session was actively re-writing via logging survived,
  which is the tell-tale signature of a `git clean` followed by live re-creation).
- **Lost from disk:** the in-flight `deepswe-pier` SPEC/PLAN/TASKS/decisions + its `bench/pier/`
  package, **and ~24 unrelated plans** (`agent-bench`, `bench`, `benchmark-harness`, `overnight-run`,
  `personas-and-roles`, `axioms-layer`, …). The unrelated plans were **never committed** (gitignored)
  ⇒ **unrecoverable**.
- **Survived:** everything the tasks wrote under `scripts/`, `commands/`, `agents/` (git-tracked).
- `ps` showed **8+ concurrent `claude` processes** against the repo.

Recovery this session: the `deepswe-pier` artifacts were regenerable only because the orchestrator
still had them in its context; the other ~24 plans were not and are gone.

---

## Root causes (there are several; a real fix addresses more than one)

1. **Artifacts are gitignored and repo-local.** `z-harness/` is in `.gitignore:32`, so plans are
   ephemeral working-tree state with zero durability guarantee.
2. **No isolation between concurrent sessions.** Every session reads/writes the same single
   `z-harness/` tree in the same working copy. One session's destructive op hits all sessions.
3. **`git clean -fdx` is catastrophic here and is a normal command.** Branch hygiene (clean before
   switch/merge) routinely nukes ignored files. Nothing warns or protects.
4. **Existing locking is per-plan, not clean-proof.** The `/z-overnight` `.overnight.lock` serializes
   overnight runs of one plan; it does nothing against a cross-session `git clean`.

---

## Constraints / what a fix must preserve

- Plans must survive `git clean -fdx`, branch switches, and other sessions' git operations.
- Multiple sessions must be able to work concurrently without clobbering each other's plans.
- Must not pollute the repo's git history with churny plan artifacts or cause cross-session merge
  conflicts.
- Should be low-friction (no manual per-run steps) and backward-compatible with existing tooling that
  assumes `z-harness/<slug>/...` paths.
- Resumability (`/z-execute` reading TASKS.md state) must keep working.

---

## Candidate directions (for the record — design now implemented)

**B is the leading candidate** because the enabling primitive already landed this session (T001).

- **A. Commit the plans (un-gitignore).** Track `z-harness/` in git. _Pro:_ durable. _Con:_ huge
  churn, cross-session merge conflicts, secrets/log noise in history. Likely rejected.

- **B. Relocate artifacts OUTSIDE the working tree (recommended starting point).** Point the
  z-harness base dir at a per-repo location under the user's home/state dir, e.g.
  `~/.local/state/z-harness/<repo-id>/` (or `$XDG_STATE_HOME`). `git clean` can't touch files outside
  the repo. **The mechanism already exists:** T001 (this session) added `Z_HARNESS_BASE_DIR`
  (`scripts/plan-path.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`) which relocates the
  entire artifact base. The follow-up would be to (a) make an external base the **default** (with a
  stable per-repo id, e.g. hash of the repo's git toplevel or origin URL), and (b) audit every
  remaining writer to honor it. _Open:_ default location, repo-id scheme, migration of existing
  in-repo plans, discoverability (users expect `z-harness/` in the repo).

- **C. Per-session git worktrees.** Each session in its own `git worktree`, so each has its own
  `z-harness/`. _Pro:_ isolation. _Con:_ heavy workflow change; doesn't help when the user
  deliberately runs many sessions in one checkout; still gitignored-and-clean-vulnerable within a
  worktree. **Deferred** (possibly complementary to B, not a substitute).

- **D. Snapshot/backup.** Periodically copy plans to a durable, non-ignored location (or `git
  stash`-like snapshots). _Pro:_ cheap safety net. _Con:_ recovery-after-loss, not prevention; race
  windows. Good as a belt-and-suspenders alongside B.

- **E. Session-aware namespacing + advisory lock.** Give each session a namespace and a cross-session
  advisory lock around the shared tree; detect "another session is active" and warn before risky ops.
  _Con:_ can't intercept `git clean` (no hook); mostly mitigates concurrent *writes*, not the clean.

**Implemented:** **B (external default base via `Z_HARNESS_BASE_DIR`) as the durability fix** + the
awareness registry + session-id stamp. C (worktrees) and D (snapshot) were deferred.

---

## Immediate interim mitigation (until a fix lands)

*(These were the pre-resolution mitigations — kept for historical record.)*

- **Set `Z_HARNESS_BASE_DIR` to an external absolute path** (e.g. `~/.z-harness-plans`) in the
  environment for all sessions — T001 already makes every artifact writer honor it, so this moves
  plans out of `git clean`'s reach today. (Validate it covers the `bench/pier/` package too — that
  package currently lives under `z-harness/bench/pier/` and is NOT covered by `Z_HARNESS_BASE_DIR`;
  see open question below.)
- **Quiesce other sessions** before doing branch switches / merges / `git clean` in any session.
- **Avoid `git clean -fdx`** in this repo while plans are unsaved.

---

## Open questions (for the record — now answered)

1. Default external base location + per-repo id scheme (git-toplevel hash? origin URL? user config?).
   → **Answered:** `sha256(realpath(git-common-dir))[0:8]` suffix; XDG_STATE_HOME > HOME/.local/state > git-common-dir fallback chain.
2. The **`bench/`-family code** (the deepswe-pier rig at `z-harness/bench/pier/`) lives under the
   gitignored tree but is *source code*, not run artifacts. Should rig/source move to a tracked path
   (e.g. `tools/` or a real package dir) while only *run artifacts* go to the external base? This
   split matters: code wants version control, artifacts want durability-without-history.
   → **Deferred** (bench/pier concern; not in scope of active-plan-coordination).
3. Migration: do we relocate the existing in-repo plans, or start fresh externally?
   → **Answered:** `scripts/migrate-plan-layout.sh --all` handles bulk migration with live-run barrier.
4. Discoverability: users (and docs) expect `z-harness/<slug>/`. If artifacts move out of the repo,
   how do we surface "where are my plans?" (a `z-stats` pointer?).
   → **Answered:** `/z-stats` shows resolved base + tier + active-plan registry list.
5. Should `/z-overnight` / `/z-execute` refuse to start (or loudly warn) if they detect another
   active session or an in-repo (clean-vulnerable) base dir?
   → **Answered:** Phase 0 registry check does this; Z_HARNESS_STRICT_OVERLAP=1 makes it a hard halt.

---

## Worktree-per-session convention (the front-line fix)

The registry + external-base work above makes *concurrent runs* safe at the artifact layer. The
complementary front-line practice is **one git worktree per parallel session** so two sessions never
share a single dirty working tree / index in the first place.

- **Location:** a sibling container one level above the repo — `../<repo>-worktrees/<slug>`
  (e.g. `../qt-bot-worktrees/<slug>`, `../z-harness-worktrees/<slug>`). Named `-worktrees`, never
  `-sandbox` (the latter collides with the remote rsync target `~/dev/qt-bot-sandbox`). Living
  outside the repo tree, these are immune to a `git clean` run from the main checkout — which sidesteps
  the entire incident class above for working trees, the same way the external base dir sidesteps it
  for plan artifacts.
- **Lifecycle:** `git worktree add ../<repo>-worktrees/<slug> -b f/claude/z/<slug>` → `cd` in →
  edit/commit/push/PR/merge → **`cd` back to the main checkout** →
  `git worktree remove ../<repo>-worktrees/<slug>` → `git worktree prune` →
  `git branch -d f/claude/z/<slug>`. Cleanup must run from the main checkout (git won't remove the
  worktree you stand in, and the relative path only resolves from there); remove the worktree before
  deleting its branch.
- **Already worktree-safe by design:** the active-plan registry keys on `sha256(realpath(git-common-dir))`,
  so every worktree of a repo shares ONE registry (parallel awareness works across worktrees), and the
  resolved base dir lives outside the worktree (survives `git worktree remove`). No registry/base change
  was needed for worktrees.
- **remote-runner cwd-safety:** `scripts/remote-sandbox-sync.sh` rsyncs the git work tree of the current
  cwd (`git rev-parse --show-toplevel`, which for a linked worktree returns the worktree path). Operate
  with cwd = the worktree, or set `Z_HARNESS_WORKTREE_ROOT=<worktree-abs-path>` — otherwise the main tree
  is shipped and remote verify silently checks stale code (the historical
  `feedback-worktree-edit-path` burn). The script now echoes `syncing local root: <path>` to stderr so a
  wrong-tree sync is visible, not silent.

---

## Pointers

- Gitignore line: `.gitignore:32` (`z-harness/`).
- Base-dir primitive (already built): `scripts/plan-path.sh`, `scripts/log-event.sh`,
  `scripts/check-timeout.sh` — `Z_HARNESS_BASE_DIR` override (deepswe-pier task **T001**).
- The plan whose run hit the incident: `z-harness/deepswe-pier/` (SPEC/PLAN/TASKS), if it still
  exists; otherwise its content is in the originating session's transcript.
- Related guidance: the user's memory entries on committing only conversation work and checking
  upstream before history rewrites.
- Resolution docs: `docs/human/active-plan-registry.md`, `docs/human/config.md` (base-dir + registry knobs), `docs/human/PLAN-LAYOUT.md`.
