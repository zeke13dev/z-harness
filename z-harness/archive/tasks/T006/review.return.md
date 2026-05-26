## Codex review: task T006

### Blockers
None.

### Major
- `git status` shows acceptance-critical source/export files still untracked, including `agents/planning-router.md`, `commands/z-audit-plan.md`, `skills/z-audit-plan/`, `exports/cursor/.cursor/rules/planning-router.mdc`, `exports/agy/.agent/rules/z-harness-planning-router.md`, and `exports/*/z-audit-plan*`; if this diff is submitted as-is, the new router and `/z-audit-plan` exports are missing from version control. Add the untracked canonical and generated files, or make the task explicitly include only tracked output.

- `agents/planning-router.md` routes “too few clusters” only when `cluster_seams == 1`, but the invariant is fewer than 2 clusters, so `cluster_seams: 0` can fall through to generic file-count routing. Change the rule to `cluster_seams < 2` and regenerate all exports.

- `commands/z-audit-plan.md` tells the command to write a route decision and emit telemetry when zero plan artifacts exist, but `$BASE` and `$RUN` are not defined until later setup steps. Define a no-plan archive location and run id before artifact discovery, or move run initialization ahead of the zero-artifact route gate, then mirror it in the skill and exports.

- `exports/agy`, `exports/codex`, and `exports/cursor` contain broad generated churn outside the T006 surfaces, including consultant timeout/liveness changes, review-promotion changes, `/z-implement-all --tasks`, `external-lookup`, `/z-audit`, and `/z-mr-review`. Either split those unrelated canonical changes out of this task or document why they are expected source-of-truth changes before accepting the regenerated exports.
