# Artifact-layout audit — where z-harness state lives

_Audited 2026-06-18. Scope: every on-disk artifact a z-harness skill reads or writes
(plans, intent, tasks, ledger, memories/axioms, handoffs, sinks, telemetry), how its
directory is resolved, whether resolution is deterministic, and whether the layout
supports cross-`/clear` handoff and later pruning._

## TL;DR

Resolution **is deterministic** — every skill routes path decisions through four pure
resolvers (`scripts/plan-path.sh`, `scripts/config.py`, `scripts/followup_common.py`,
`scripts/resolve-kernel.sh`), all functions of env + a stable `repo-id`. No skill guesses
a path. The problem was never determinism; it was **multiplicity**: artifacts live under
three unrelated roots, and pre-migration orphans had accumulated in-repo and in the live
state dir. The orphans are cleaned and the one genuine contradiction (handoff.json) is
fixed; the multi-root split is documented below as intentional.

## The three roots

| Root | Resolved by | Holds |
|------|-------------|-------|
| **STATE** — `~/.local/state/z-harness/<repo-id>/` (or `$XDG_STATE_HOME/...`; `<repo-id>` = `<basename>-<8hex sha256(git-common-dir)>`, stable across worktrees) | `plan-path.sh::z_harness_base()` (5-tier chain; external default; in-repo only as opt-out via `Z_HARNESS_EXTERNAL_DEFAULT=0` or explicit `Z_HARNESS_BASE_DIR`) | `plans/<slug>/` (INTENT.md · SPEC/PLAN/TASKS.md · LEDGER.md · workstreams.json · SESSION.md · handoff.json · archive/<run-id>/events.jsonl) · `active-plans/<run-id>.json` + `claims/<slug>.lock` · `followups/{project,global}/` · `metrics.jsonl` · `archive/` |
| **CONFIG** — `.z-harness/` (project) over `~/.config/z-harness/` (global) | `config.py::_repo_config_path/_global_config_path`; `axiom-store.py::_resolve_axioms_dir`; `resolve-kernel.sh` | `config.toml` · `providers.json` · `axioms/{candidates,approved,rejected}/` · `KERNEL.md` |
| **CWD** — repo working dir | `/z-handoff` fallback only | `handoff.json` **only when there is no active plan** (see P0) |

Anchor enforcement (`<git-common-dir>/.z-harness-base`) prevents split-brain between
runs; an explicit `Z_HARNESS_BASE_DIR` is the CI/benchmark escape hatch and bypasses it.

### Why STATE and CONFIG are deliberately separate
STATE is *run output* (regenerable, prunable, per-run). CONFIG is *behavioral policy*
(config.toml, axioms/KERNEL) that must **survive `/z-update`** and live in user-space or
be git-committable per-project. Keeping axioms in `.z-harness/` rather than the external
STATE base is intentional: `docs/llm/axioms.json` documents that both axiom stores sit
outside the plugin install tree so a plugin update never touches them. This split is
sound; it is documented here so it reads as a decision, not an accident.

## Findings and dispositions

### P0 — `handoff.json` had two contradictory homes — FIXED
The one artifact whose entire job is cross-`/clear` continuity had two producers that
disagreed:
- `scripts/write-handoff.sh:45` (the automated `/z-implement-all` producer, also what the
  MCP `_handle_z_handoff` calls) → `$Z_HARNESS_PLAN_DIR/handoff.json`.
- `commands/z-handoff.md` → `${WORKSPACE_ROOT:-$PWD}/handoff.json`, and explicitly said
  *"Do NOT write it inside `$Z_HARNESS_PLAN_DIR`"* citing Hermes.

Ground truth from the code: the real resume consumer `/z-attend` reads `$BASE/handoff.json`
where `$BASE = $Z_HARNESS_PLAN_DIR` (`commands/z-attend.md:124,511`); the MCP `/z-handoff`
handler shells out to `write-handoff.sh` (PLAN_DIR); and **no consumer reads a
workspace-root `handoff.json`** (Hermes's "handoff" refs are model-to-model, not this file).
So `z-handoff.md` was simply wrong.

**Fix:** `commands/z-handoff.md` now declares `$Z_HARNESS_PLAN_DIR/handoff.json` the
canonical home (co-located with SESSION.md/TASKS.md/LEDGER, survives `/clear` and a CWD
change), with `$PWD` as the documented fallback **only** when there is no active plan
(`slug` null): `HANDOFF_PATH="${Z_HARNESS_PLAN_DIR:-${WORKSPACE_ROOT:-$PWD}}/handoff.json"`.
The 7 per-host golden export fixtures were regenerated; `test_export_golden.py` +
`test_session_handoff.py` green (76 passed).

### P1 — three orphaned in-repo plan roots — FIXED
Pre-dating the external-base migration, three dead plan locations had accumulated:
- `plans/` — **7 plans, committed to git** (56 tracked files).
- `.z-harness/plans/beyond-sdd` — untracked.
- `state/z-harness/plans/hermes-handoff-consumer` — untracked.

None is where `plan_dir()` resolves today, so no skill can find them; all 7 tracked slugs
have canonical copies in the external STATE base, and the tracked content remains in git
history. **Fix:** `git rm -r plans/`; `rm -rf .z-harness/plans state/z-harness`; added
`/plans/`, `/state/`, `.z-harness/plans/` to `.gitignore` so they cannot silently
re-track. (This was the "remaining manual migration step" flagged in the
parallel-session-safety work.)

### P2 — test debris + a flaky claim test — FIXED
Two related problems were conflated under "test pollution":

1. **State-dir debris (orphans).** `tests/conftest.py` already pins `XDG_STATE_HOME` to a
   tmp for the pytest suite, and a per-script + full `make test-sh` sweep confirmed the
   *current* shell tests add **zero** new dirs to `~/.local/state/z-harness/`. The 61
   `<repo-id>`-named dirs found there were **historical debris** from older/interrupted runs,
   not active leaks — removed (real repo bases preserved).

2. **`test_plan_claim.sh` flaky + leaking (root cause found and fixed).** The test was
   intermittently failing (escalating to 18–20 failures under repeated runs) and had leaked
   **461 tmp dirs** and dozens of orphaned lock-holder daemons (`sink-lock.sh acquire` forks
   a Python daemon that blocks in `signal.pause()`). Root cause: its cleanup used a bash
   array (`CLEANUP_DIRS+=(...)`) populated inside `_tmpdir`, but `_tmpdir` is invoked via
   command substitution (`d="$(_tmpdir)"`) — a **subshell**, so every append was lost and the
   `EXIT` trap cleaned up nothing. Each run leaked all 17 of its tmp dirs and their daemons.

   **Fix (`scripts/test_plan_claim.sh`):**
   - Register cleanup paths through a **file** instead of an array, so they survive the
     command-substitution subshell.
   - `_cleanup_all` now reaps the lock-holder daemons it spawned: a graceful per-dir pass
     (SIGTERM by the PID recorded in each `.lock`), then a final **SIGKILL backstop** sweep
     keyed on the unique `test_plan_claim_` tmp prefix and scoped to daemons that appeared
     during the run (a start-of-run PID snapshot excludes any concurrent process). SIGKILL is
     required because cases like TC06 corrupt/null their lock file (no PID left to read) and
     can wedge the daemon's SIGTERM handler on a corrupt `.hb.lock`.

   **Verified:** `test_plan_claim.sh` now passes 43/0 across many consecutive and rapid-repeat
   runs; per-run delta is **0 tmp dirs and 0 daemons**. Full `make test-sh` is green (all
   scripts, exit 0) with **0** new real-state dirs.

The denied broad `pkill` (correctly blocked — it could hit a parallel session's daemons)
reframed the fix toward self-scoped reaping in the test itself, which is the durable answer.
Pre-existing orphan daemons under `/var/folders` (macOS tmp, auto-reaped on reboot) were left
in place since reaping them safely requires the user's own broad kill; the fix prevents any
new accumulation.

### P4 — (withdrawn) axiom KERNEL path
Initial pass suspected the axiom docs pointed at a non-existent `<base>/.z-harness-axioms/KERNEL.md`.
**False alarm:** `docs/llm/axioms.json:77` correctly documents the real chain
(`Z_HARNESS_KERNEL_PATH > <git-root>/.z-harness/KERNEL.md > $XDG_CONFIG_HOME/z-harness/KERNEL.md`).
The bad path was a doc-fetcher synthesis error, not drift. No fix needed.

## Determinism scorecard (the original question)

- **Each skill knows where to look** — yes; all reads/writes go through the four resolvers,
  never ad-hoc paths. ✓
- **Handoffs after `/clear`** — now single-homed at `$PLAN_DIR/handoff.json` (P0). ✓
- **Finding plans** — single canonical root (external STATE `plans/<slug>/`); legacy
  in-repo roots removed and gitignored (P1). ✓
- **Pruning plans later** — `archive/` lifecycle operates on the STATE root only; with the
  orphans gone there are no longer plan copies outside its view. ✓
- **Test hygiene** — pytest isolated; shell tests confirmed leak-free; `test_plan_claim.sh`
  subshell-cleanup bug fixed (no more leaked tmp dirs / orphan daemons) and de-flaked (P2). ✓
