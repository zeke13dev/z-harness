**Issues**

1. `config.py`: env var transliteration needs to be nailed down. Dotted keys map cleanly to `Z_HARNESS_NOTIFY_LEVEL`, but future nested keys, hyphens, and ambiguous names need a deterministic rule now or docs/tests will drift.

2. `config.py`: "raw scalar value" for `get` is underspecified. Booleans, ints, strings, missing keys, and unknown keys need exact stdout/stderr/exit behavior. I'd define: known scalar only; missing/unknown exits 1; invalid config exits 2.

3. `config.py`: `export-env` must shell-quote values. Even though current enum values are safe, this is a config boundary. Use `shlex.quote` or emit strict `KEY=value` only if every exported value is validator-constrained.

4. `config.py`: source tracking for `explain` is easy to get subtly wrong with nested defaults. Specify whether it prints all layers, only effective override chain, and how missing layers appear.

5. `config.py`: permission denied is too broad. Reading user/repo config denied should exit 4; failure writing `ensure-defaults` should also exit 4. But missing `~/.config` should create dirs or document failure behavior.

6. `config_resolved`: run-scoped de-dupe via temp file needs a concrete path and atomicity rule. Concurrent processes in same run can race unless creation uses `O_EXCL`/lock/atomic mkdir.

7. `config_resolved`: emitting from `export-env` may be surprising because command substitution could be used outside a command run. Spec says no `$Z_HARNESS_RUN` means no event, good. Also specify whether `get`, `explain`, and `should-notify` emit; I'd emit only from `export-env`.

8. `config.sh`: "thin wrapper exec'ing config.py" should specify path resolution from script dir, not current working directory.

9. Docs: "DRY docs reference, don't duplicate" conflicts with "full human reference." Human docs must duplicate enough CLI semantics to be useful. DRY should mean examples and schema names stay generated or tightly mirrored, not no duplication.

10. README rewrite: "relocate old content" needs an explicit destination file. Otherwise Phase C can become accidental doc loss.

11. `/z-do` and `/z-plan`: `eval "$(... export-env)"` under `set -e` must handle config errors cleanly. If config parse exits 2, the command should stop with a clear message, not continue with stale env.

12. `/z-plan`: "heavy flows ignore never" is slightly leaky. If `docs.always_apply=never` is ignored for heavy flows, the name is misleading. The invariant should be "heavy flows force docs apply regardless of knob."

**Scope**

Slice scope is mostly right. I would not add prompt fragments, consult prefs, archive retention, repo init, or all-command migration.

The only load-bearing non-goal risk is per-command filtering. Since `export-env --for <command>` exists but is ignored, tests and docs must explicitly say it is accepted for forward compatibility and currently exports the same values for all commands. Otherwise users will assume behavior that does not exist.

**Missed Edge Cases**

- Unknown config keys: warn, ignore, or fail? Pick one. I'd ignore unknown keys for forward compatibility, but fail unknown enum values for known keys.
- Env var with invalid value should exit 2, same as TOML typo.
- Env var empty string behavior should be defined; probably invalid for enums.
- Repo config discovery: only `.z-harness/config.toml` in current working directory, or search upward to repo root? This is critical.
- Symlinked config files and permission denied through symlink.
- Multiple scalar types in TOML: `notify.level = 1` should exit 2, not stringify.
- Duplicate TOML keys: parser behavior should be accepted as parse error if parser reports it.
- Windows path support likely non-goal, but shell wrapper implies POSIX-only.

**Migration Order**

`/z-do` before `/z-plan` is defensible. It is the smaller proof path and exercises the light-flow interpretation of `docs.always_apply`.

The one reason to do `/z-plan` first would be if heavy-flow semantics drive the shared shell pattern. But here `should-notify` and `export-env` are the shared contract, so starting with `/z-do` is fine.

**should-notify API**

The always-exit-0, print `yes|no` pattern is good for `set -e` and keeps policy centralized. Main critique: invalid `--event` should probably still exit nonzero unless event kinds are intentionally open-ended.

Recommended contract:

- valid config + any event string: exit 0, print `yes|no`
- invalid config: exit 2
- CLI misuse, missing `--event`: exit 64 or 2, but not silent yes/no

If event kinds are open-ended, document the current classification: approval events notify under `approval_only`; all other events require `all`.

**DRY/KISS/SOLID**

Biggest KISS risk is `explain` plus source tracking plus event emission in slice 1. If you need to cut further, cut `explain` first. It is useful, but not needed to migrate two commands.

Biggest DRY risk is validators duplicated across code, docs, and README examples. Keep enum values in code authoritative and make tests assert docs examples still match current values.

Biggest SOLID risk is `config.py` both resolving config and emitting harness events. Acceptable for slice 1, but keep event emission as a tiny adapter function so config resolution remains testable without filesystem side effects.
