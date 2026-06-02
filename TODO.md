# z-harness — TODO

Follow-ups after the production-readiness pass + brainstorm-personas merge
(`main`). **None of these block a release** — the full suite is green
(1863 passed), distribution builds + audits clean, and both features are
complete. These are gaps, cleanup, and deployment decisions.

## Worth doing (unblocked)

- [x] **Wire shell tests into CI.** Added a `shell` job to `tests.yml` running
  `make test-sh` (all 12 bash harnesses, incl. the two `--self-test` scripts).
- [ ] **Consolidate the duplicated base resolver.** Five scripts carry a
  near-identical inline helper that shells out to `plan-path.sh base_dir`:
  `scripts/axiom-extract.py`, `scripts/extract-dismissals.py`,
  `scripts/persona-stats.py`, `scripts/propose-prefs.py`,
  `scripts/followup_common.py`. Extract into one shared module (e.g.
  `scripts/zh_base.py`) and update all call sites. Pure DRY — all five work.
  (Deferred: a 6-file refactor with standalone-vs-imported sys.path nuances —
  not "easy".)

## Minor / robustness

- [x] **`parents[N]` path fragility.** `runtime/drivers/antigravity/tests/`
  (`test_driver.py`, `test_stream_parser.py`, `test_auth.py`) now detect the
  repo root by walking up to the dir holding both `runtime/` and `scripts/`,
  instead of counting path levels.

## Deployment decisions (need a human, not a patch)

- [ ] **Tarball auto-update release URL.** `commands/z-update.md` has a
  placeholder `https://example.com/...` URL. It degrades gracefully (halts with
  "set `Z_HARNESS_RELEASE_URL`") and symlink-mode (`git pull`) works fully.
  Real tarball auto-update needs an actual hosting URL.
- [ ] **Conformance golden fixtures.** The `claude-code` driver fixture is a
  placeholder (the suite's lone `xpass`). Record real fixtures via
  `make conformance-record` once driver runs are available.
- [ ] **`bench-autonomy` policy location.** The frozen policy lives under the
  gitignored `z-harness/bench/pier/benchmark-autonomy.yaml`, so
  `make bench-autonomy-check` only runs where the Pier bench is set up locally.
  Decide whether the policy should be version-controlled.

## Release mechanics

- [ ] **Push `main` / open a PR.** `main` is ahead of `origin/main`, clean and
  green.
- [ ] **Remove the production-readiness worktree** (`.claude/worktrees/prod-cont`,
  branch `fix/production-readiness-cont`) once no longer needed — it points at
  the same commit as `main`.
