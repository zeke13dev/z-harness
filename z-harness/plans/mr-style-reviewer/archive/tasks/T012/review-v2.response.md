BLOCKER: `commands/z-implement-all.md:20`

`TASKS_FILE="${TASKS_FILE:-$BASE/TASKS.md}"` is now initialized before slug discovery has established `BASE`, so the normal non-`--tasks` path can bind `TASKS_FILE` to an invalid `/TASKS.md` and then Step 4/main loop/finalize read the wrong file. Fix by only setting `TASKS_FILE` after `BASE` is known for the normal path, or set it in Step 3 after slug/tree binding with `TASKS_FILE="${TASKS_FILE:-$BASE/TASKS.md}"`; keep the `--tasks` fast path assigning both `TASKS_FILE` and `BASE`.

The four previously identified operative references were switched correctly:
`Pick next task`, `Mark in-progress`, `Mark done`, and `Finalize` now use `$TASKS_FILE`. No remaining `$BASE/TASKS.md` operative read/write references from the v1 blocker are present in the submitted patch.
