# Plan Review: z-harness TOML Config (Slice 1)

Gemini's concrete critique addressing all six questions:

## 1. What's wrong, missing, or fragile in the SPEC?

**Validation Hard-Fails:** If an invalid enum is found in the global `~/.config/z-harness/config.toml`, does it crash the entire CLI for all repos? If so, one typo locks the user out of the tool entirely. Invalid global values should likely emit a stderr warning and fall back to defaults, rather than bricking execution.

**Missing CLI Flag Precedence:** The layer hierarchy (Defaults → Global → Repo → Env Vars) is missing the top layer: CLI flags (e.g., `--notify=all`). If CLI flags aren't explicitly declared as overriding env vars, you will introduce inconsistencies where config shadows explicit user intent.

**`ensure-defaults` Idempotency Flaw:** If `ensure-defaults` only checks for file existence, it is fragile. If a file exists but is empty, or exists but is missing new keys introduced in v2, it fails to "ensure defaults". It needs to perform a deep merge or explicit key-check.

**Python TOML Dependency:** You did not specify the Python version. Native `tomllib` requires Python 3.11+. If the environment uses Python < 3.11, the script will crash unless `tomli` is bundled/installed.

## 2. Slice scope: Is it right?

**README Rewrite is Scope Creep:** Rewriting the README (pitch + quickstart + relocating content) is too much for a config slice. Keep README changes strictly to "Here is how to configure this tool." Do not blend a marketing/documentation overhaul with a foundational architecture change.

**The Exception in `/z-plan` is a Code Smell:** Proving a pattern by immediately introducing an exception (`/z-plan` ignores `docs.always_apply="never"`) means your abstraction is already leaking in slice 1. Either `/z-plan` shouldn't use this config key at all, or the key's definition is wrong. If you must prove the pattern, migrating `/z-do` alone is sufficient for Slice 1.

## 3. Edge cases SPEC misses?

**Explicitly Invalid Env Paths:** If a user explicitly sets `$Z_HARNESS_REPO_CONFIG=/path/to/typo.toml`, should the system silently fall back to global, or throw an error? Silent fallbacks on explicitly provided paths create debugging nightmares.

**Type Coercion during Transliteration:** TOML supports booleans (`true`/`false`) and integers. Env vars are strings. When `export-env` runs, does `docs.always_apply = true` become `export Z_HARNESS_DOCS_ALWAYS_APPLY='true'` or `'1'`? The bash scripts consuming these vars must align perfectly with the Python coercion.

**Dotted Keys vs. Hyphens:** What happens if a user writes `notify-level = "off"` instead of `notify.level = "off"`? The parser needs strict rules on what character combinations are valid to prevent silent ignored-key bugs.

## 4. Migration order: `/z-do` then `/z-plan` — defensible?

**Defensible Order:** Progressing from the light flow to the heavy flow is the correct approach.

**Parallel execution risk:** Do not do them in the same commit. Keep them sequential. If the config loading introduces latency or parsing errors, it will be much easier to bisect and isolate if `/z-do` is isolated.

**Testing Liability:** Yes, gating `doc-fetcher` conditionally in `/z-do` creates a testing gap. You must ensure your CI/smoke tests explicitly run `/z-do` with `docs.always_apply` set to *both* enabled and disabled states.

## 5. The `should-notify` API — final critique

**Unidiomatic Bash Pattern:** Always exiting 0 and printing `yes/no` is an anti-pattern. It forces callers to capture stdout: `if [ "$(config.py should-notify)" = "yes" ];`. 

**Fix:** Use standard POSIX exit codes. Exit `0` for true/yes. Exit `1` for false/no. Exit `2` for configuration/parsing errors. This allows native, readable shell usage: `if config.py should-notify; then`.

**Schema for Events:** Do not leave `--event <kind>` open-ended. The Python script must maintain a strict allowlist of known events. If a bash script queries `--event failre` (typo), it should exit `2` (error), not silently return `no` (exit 1).

## 6. Any DRY/KISS/SOLID violations I missed?

**YAGNI Violation on `--for <cmd>`:** If `export-env --for <command>` is "accepted but ignored" in this slice, drop it. It's dead code that creates a false contract with callers. Add it in the slice where it actually influences logic.

**Cohesion of DEFAULTS and VALIDATORS:** Splitting the schema into two separate dictionaries (`DEFAULTS` and `VALIDATORS`) is a minor cohesion violation. Use a single dictionary defining the schema config per key: `{"notify.level": {"default": "off", "choices": ["off", "approval_only", "all"]}}`.

**Transliteration Logic needs isolation:** The `dotted -> Z_HARNESS_<SECTION>_<KEY>` rule must be an isolated, testable pure function in `config.py`. Do not bury it in the `export-env` loop.
