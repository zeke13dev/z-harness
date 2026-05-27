You are reviewing code that Claude just wrote for task T005: Sanity-test scripts/config.py end-to-end (smoke tests).

## Task Spec

Acceptance criteria (verbatim from TASKS.md T005):

All scenarios below pass under `set -e`. Use a hermetic test fixture (`XDG_CONFIG_HOME=$(mktemp -d)` per test; cleanup on exit) to avoid touching the developer's real `~/.config/z-harness/`.

**Baseline (defaults):**
- `config.py get notify.level` → `approval_only`.
- `config.py get docs.always_apply` → `always`.
- `config.py get schema_version` → exit 3 (meta key, not user-exposed).

**Env override:**
- `Z_HARNESS_NOTIFY_LEVEL=off config.py get notify.level` → `off`.
- `Z_HARNESS_NOTIFY_LEVEL="" config.py get notify.level` → `approval_only` (empty = missing layer).
- `Z_HARNESS_NOTIFY_LEVEL=loud config.py get notify.level` → exit 2.

**Repo-local precedence:** with `.z-harness/config.toml` containing `notify.level = "off"`:
- `config.py get notify.level` → `off`.
- `config.py explain notify.level` shows source `repo`.
- With ALSO `Z_HARNESS_NOTIFY_LEVEL=all`: `get` → `all`, `explain` source → `env`.

**Unknown / typo'd keys:**
- `config.py get notify.lvel` → exit 3.
- `config.py explain notify.lvel` → exit 3.

**`should-notify` truth table (9 branches):** for every `(level, event)` pair with `level ∈ {off, approval_only, all}` and `event ∈ {approval, phase_end, error}`, assert stdout matches SPEC §"should-notify Logic":
- `off` × `{approval, phase_end, error}` → `no`, `no`, `no`.
- `approval_only` × `{approval, phase_end, error}` → `yes`, `no`, `yes`.
- `all` × `{approval, phase_end, error}` → `yes`, `yes`, `yes`.
- `config.py should-notify --event failre` (typo) → exit 2 + stderr lists allowlist.

**`ensure-defaults` behavior:**
- On empty `$XDG_CONFIG_HOME`: creates `~/.config/z-harness/config.toml`; prints `created <path>`.
- Second invocation: `exists <path>`; file unchanged.
- With pre-existing 0-byte file: exit 4 with actionable message; file NOT overwritten.
- With pre-existing malformed TOML (e.g. `notify.level = `): exit 4; file NOT overwritten.

**TOML / schema errors:**
- Repo-local file with `notify.level = "loud"` → exit 2 (project-specific invalid: hard-fail).
- Global file with `notify.level = "loud"` → stderr warn + `get notify.level` returns `approval_only` (default; per-key fallback).
- Any layer with `schema_version = 2` → exit 2 + message naming the file.
- Malformed TOML at any layer → exit 2 with parser line/column.

**Explicit override path:**
- `Z_HARNESS_REPO_CONFIG=/nonexistent/path config.py get notify.level` → exit 2 (explicit miss is loud).

**Event de-dup:** with `Z_HARNESS_RUN=test-run-123`:
- First `config.py export-env` emits one `config_resolved` event.
- Second `config.py export-env` with same `Z_HARNESS_RUN` emits zero (O_EXCL temp file blocks).
- Without `$Z_HARNESS_RUN`: zero events emitted.

**Pure transliteration function:**
- `_dotted_to_env("notify.level")` → `"Z_HARNESS_NOTIFY_LEVEL"`.
- `_dotted_to_env("docs.always_apply")` → `"Z_HARNESS_DOCS_ALWAYS_APPLY"`.
- `_dotted_to_env("notify-level")` raises / exits 2.
- `_dotted_to_env("a.b.c")` raises / exits 2 (>2 levels).
- `_dotted_to_env("notify")` raises / exits 2 (no dot).

**eval-cleanliness:** `eval "$(config.py export-env)"` under `set -e` succeeds and sets `$Z_HARNESS_NOTIFY_LEVEL` and `$Z_HARNESS_DOCS_ALWAYS_APPLY` but NOT `$Z_HARNESS_SCHEMA_VERSION`.

## Focus checks

- Hermeticity: every test must isolate XDG_CONFIG_HOME, no leaking to dev's real ~/.config/z-harness/.
- Z_HARNESS_* env var scrubbing in subprocess calls — confirm the test runner doesn't accidentally inherit Z_HARNESS_NOTIFY_LEVEL etc from the calling shell into a "baseline" test.
- 9-branch should-notify truth table actually covers all 9 combinations.
- Event de-dup test actually creates and cleans up its $TMPDIR/z-harness-config-resolved-* stamp file.
- Tests that claim to assert exit codes use the actual exit code (not just check exit != 0).
- For malformed TOML / 0-byte tests: are they checking exit codes AND that the file was NOT overwritten?
- Any test that's a no-op (always passes) due to subtle logic error?
- DRY violations or test duplication?

## Diff (primary artifact)

The diff adds a new file `scripts/test_config.py` with ~500 lines of test code. 41 tests, all passing in 2.3s. Test results:
- Baseline defaults (3 tests)
- Env override (3 tests)
- Repo-local precedence (4 tests)
- Unknown / typo'd keys (2 tests)
- should-notify truth table (10 tests including typo event)
- ensure-defaults edge cases (4 tests)
- TOML / schema errors (4 tests)
- Explicit override path (1 test)
- Event de-dup (3 tests)
- Pure _dotted_to_env function (5 tests)
- Eval cleanliness (2 tests)

Total: 41 tests, all passing.

## Context: Target implementation (scripts/config.py)

Scripts/config.py is a 556-line Python module implementing the loader with:
- DEFAULTS dict (schema_version, notify.level, docs.always_apply)
- VALIDATORS dict (enum values per key)
- _dotted_to_env pure function (dotted-key → Z_HARNESS_* env var)
- Layer merging: defaults → global → repo → env, with per-key shadowing
- Five subcommands: get, export-env, ensure-defaults, explain, should-notify
- Event emission (config_resolved) via O_EXCL de-dup on $Z_HARNESS_RUN
- Validation rules: global-config invalid-enum triggers soft-fail (warn + default), repo/env invalid-enum triggers hard-fail (exit 2)

---

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).

