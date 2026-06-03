---
schema_version: 1
source: capture
source_files:
  - "runtime/dispatch/dispatcher.py"
  - "runtime/drivers/_persona_utils.py"
  - "runtime/validate.py"
  - "scripts/followup_common.py"
  - "scripts/log-event.sh"
repo: z-harness
revision: 2fcc6fbedf6d0c770867a09e482ebbaf8fd8fa24
generated_at: 2026-06-03T04:29:38Z
---

# z-harness Style Guide

## Error handling

### EH-001: Document the best-effort vs hard-fail contract in every function's docstring

Each function that can fail must declare its failure mode in its docstring — there is no implicit middle ground. **Best-effort** helpers catch only specific, named exceptions (`OSError`, `FileNotFoundError`, `subprocess.CalledProcessError`, `json.JSONDecodeError` — never a bare `except`), never raise, and return a documented sentinel (`''`, `{}`, `False`, or `None`); the docstring states this explicitly, as in `followup_common.py`'s `_get_config_str` ("best-effort; returns '' on error"). **Hard-fail** helpers raise `RuntimeError` (or a specific exception type) with a descriptive message, use `from exc` / `from None` chaining, and their docstring explicitly forbids sentinel fallback — e.g. `git_head()` states "Callers must treat this as a hard rejection — do NOT fall back to a sentinel." The choice between the two modes must be deliberate.

Rationale: Mixing silent swallowing with propagation unpredictably makes callers impossible to reason about; declaring the contract in the docstring forces the decision at authoring time and surfaces it at reading time.

### EH-002: Catch only named exception types — at every catch site, in both failure modes

Every `except` clause names the exact exception type(s) being handled. Bare `except` and `except Exception` are forbidden whether the function is best-effort or hard-fail. When several related exceptions are acceptable, enumerate them in a tuple — e.g. the filesystem/subprocess trio `(subprocess.CalledProcessError, FileNotFoundError, OSError)` in `followup_common.py`'s `_get_config_bool`. `json.JSONDecodeError` swallowing is permitted inside best-effort event-stream parsers (as in `dispatcher.py`'s event-iteration loop) but must carry a comment explaining the deliberate recovery strategy.

Rationale: Broad catches silently absorb programming errors and make debugging and auditing impossible; named catches communicate intent and scope.

### EH-003: Use `from exc` / `from None` chaining on all hard-fail raises

When a hard-fail helper catches a lower-level exception and re-raises, always chain with `from exc` to preserve the original traceback, or `from None` when the original is deliberately discarded (e.g. `git_head()` raises `RuntimeError(...) from None` for `FileNotFoundError`). `runtime/validate.py`'s `_load_schema` chains `jsonschema.SchemaError` with `from exc` the same way.

Rationale: Chained exceptions expose root cause without manual message duplication, making failures debuggable in production logs.

### EH-004: No-fallback is a valid, intentional stance — document it

Some helpers deliberately refuse to swallow errors even where swallowing would be technically possible, and must say so. The canonical example is `dispatcher.py`'s `_emit`: "This method intentionally has no fallback: a broken log path is a real problem that should surface immediately during development." Similarly, `log_sink_event` does not catch `OSError` — unlike the best-effort `log_metrics_event` — because sink writes are semantically mandatory. State the stance in the docstring or an inline comment.

Rationale: An undocumented no-catch reads like a forgotten try/except; an explicit note turns it into a design statement reviewers can evaluate.

### EH-005: Best-effort resource cleanup uses nested `try/except OSError` in `finally`; track fd ownership with an explicit flag

Filesystem and lock cleanup (`os.unlink`, `os.close`, `fcntl.flock(LOCK_UN)`) belongs in `finally` blocks, each operation wrapped in its own `try/except OSError` so one failed cleanup does not skip the next. When an fd is allocated and only conditionally transferred to a longer-lived owner, track ownership with an explicit boolean (e.g. `transferred = False` in `GlobalLockContext.__enter__` and `acquire_global_lock`) and close the fd in `finally` unless ownership transferred.

Rationale: Without explicit ownership tracking fds leak on every non-success exit path (tracked as CARRY-1b); nested try/except in finally prevents one failing cleanup from skipping subsequent ones.

---

## Tests

### T-001: Test observable behavior and invariants, not implementation internals

Tests assert on the external contract — event payload field sets, process exit codes, timing-phase semantics, lock acquire/release ordering — not on private helpers or internal state. Tests for `dispatcher.py` verify that `dispatch_start` / `dispatch_end` payloads contain exactly the fields fixed by SPEC Invariant #7 (not that `_compose_argv` was called N times); tests for `GlobalLockContext` verify that `TimeoutError` is raised on contention (not that `time.sleep` ran). Cite the relevant SPEC invariant by ID in the test docstring or assertion comment where one exists.

Rationale: Implementation-coupled tests break on every refactor regardless of behavioral correctness; invariant-focused tests stay green as long as the contract holds.

### T-002: Exercise real subprocess and script paths over heavy mocking where practical

Tests covering shell-script-backed behavior (e.g. `log-event.sh`, `plan-path.sh` calls from Python) invoke the actual scripts via `subprocess` rather than mocking `subprocess.run` wholesale. Reserve mocking for network calls, external services (e.g. the Notion API), and timing sources.

Rationale: Mocking subprocess removes the most likely class of integration bugs — argument quoting, path resolution, exit-code interpretation — from coverage entirely.

### T-003: Test files mirror the unit under test using the canonical naming convention

Python tests live under `tests/` as `tests/test_<module>.py` (e.g. `tests/test_validate.py` for `runtime/validate.py`). Shell tests live near the script they cover as `scripts/<script>_test.sh` or `scripts/test_<thing>.sh`. Deviations (e.g. integration tests spanning several modules) require a comment explaining why.

Rationale: Consistent naming makes the test for any source file trivially locatable and makes a new module shipping without coverage visible during review.

### T-004: Tests are hermetic — pin artifact roots, use temp dirs, and cover the error paths

A test must not read or write the developer's real z-harness artifacts. Pin `Z_HARNESS_BASE_DIR` (and `Z_HARNESS_PLANS_DIR` where relevant) to a per-test temporary directory so artifact resolution is deterministic and isolated, and clean up what the test creates. Cover the negative paths the source explicitly handles — timeout branches, lock-contention `TimeoutError`, malformed-JSON recovery, missing-file sentinels — not just the happy path.

Rationale: The base-dir default resolves into the repo, so an unpinned test silently couples to local state and can corrupt or be corrupted by a concurrent run; error-path coverage is where the best-effort/hard-fail contracts (EH-001) are actually verified.

---

## Comments

### C-001: Module docstrings carry design decisions, the public surface, and invariant references

Every Python module opens with a docstring documenting (a) its purpose and scope, (b) key design decisions with their decision IDs (e.g. `C1-D4`, `B3`, `SPEC Invariant #7`), and (c) where relevant a summary of the public surface (as in `followup_common.py`'s "Exported surface" list) or behavioral guarantees (as in `runtime/validate.py`'s "Import-time failure" and "Thread-safety" sections).

Rationale: Module-level context eliminates the need for readers to reconstruct design rationale by diffing git history or hunting through planning documents.

### C-002: Inline comments explain WHY and cross-reference by ID — not WHAT

Inline comments are reserved for non-obvious rationale, edge cases, and cross-references; they must not paraphrase the code. Strong examples: the `_Z_HARNESS_RESOLVING_BASE` recursion-guard explanation in `log-event.sh`, the macOS `OBJC_DISABLE_INITIALIZE_FORK_SAFETY` note in `followup_common.py`, and the `transferred`-flag ownership comment in `GlobalLockContext`. Reference carry-over notes by their grep-able tracking IDs (e.g. `CARRY-1b`, `T009`, `T015`) — these are informal cross-references, not entries in a formal registry.

Rationale: Rationale-only comments age gracefully; what-comments become stale the moment the code changes and create a misleading dual record.

### C-003: Public functions have structured docstrings with Args/Returns/Raises sections

Every public function (and every internal function with a non-trivial contract) carries a structured docstring. Google-style (`Args:` / `Returns:` / `Raises:`) and NumPy-style (`Parameters` / `Returns` / `Raises` with underline separators) are both acceptable — be consistent within a file. Shell functions document positional arguments via the header `# Usage:` / `# Example:` block as in `log-event.sh`. Do not omit `Raises:` from a hard-fail function; its absence implies best-effort to readers (see EH-001).

Rationale: Structured docstrings make contract scanning mechanical rather than requiring a full function-body read at every callsite.

### C-004: Section-banner comments group related helpers within a module

When a module has more than two or three logical groups of helpers, separate them with banner comments. Python files use the em-dash style `# ── <section> ──────...` seen in `followup_common.py` (`# ── timestamps ──`, `# ── git helpers ──`, `# ── global lock ──`); `_persona_utils.py` uses full-width `# ----` rules; shell scripts use `# --- <section> ---`. Apply one style consistently within a file.

Rationale: Banner dividers turn module-level grep output into a navigable table of contents and signal which logical group a new function belongs to.

---

## Naming

### N-001: Constants are `UPPER_SNAKE_CASE`; private names take a single leading underscore

Module-level constants are `UPPER_SNAKE_CASE`. A constant that is module-private additionally takes a single leading underscore (`_GLOBAL_LOCK_DEFAULT_TIMEOUT`, `_VALID_SCHEMA_NAMES`, `_CONTRACT_DIR`); a public constant gets no underscore. Private helpers and internal names use a single leading underscore (`_compose_argv`, `_load_schema`). Never use a double underscore for module-private names — that triggers Python's name-mangling. Public functions and variables use plain `snake_case`.

Rationale: The single-underscore convention is the stdlib standard and signals "internal" without name mangling; UPPER_SNAKE_CASE makes a grep for module state immediate.

### N-002: Fixed string sets use `frozenset`; mutable caches are type-annotated as `dict`

A fixed set of valid string values is declared as a module-level `frozenset` (e.g. `_VALID_SCHEMA_NAMES = frozenset({"command", "agent", ...})` in `runtime/validate.py`) — immutable, O(1) membership, no accidental-mutation footgun. A mutable module-level cache (e.g. `_schema_cache: dict[str, dict] = {}`) carries its full type annotation and a thread-safety note.

Rationale: `frozenset` mechanically enforces "this set never changes"; typed `dict` caches catch mis-keying at static-analysis time.

### N-003: Env vars use `Z_HARNESS_`; script filenames are `kebab-case`; event `kind` strings are `snake_case`

All z-harness-owned environment variables use the `Z_HARNESS_` prefix (`Z_HARNESS_RUN`, `Z_HARNESS_SLUG`, `Z_HARNESS_BASE_DIR`, `Z_HARNESS_PLANS_DIR`). Shell script filenames are `kebab-case` (`log-event.sh`, `plan-path.sh`). Structured event `kind` values are `snake_case` (`dispatch_start`, `dispatch_end`, `followup_notion_sync_failure`). Python functions and locals are `snake_case`.

Rationale: Namespace-prefixed env vars avoid collisions with host-shell variables; consistent `kind` casing keeps event-log grep patterns predictable across JSON Lines files.

### N-004: Importable Python files use underscores; standalone shell scripts use hyphens

Python files imported as modules use `underscore_case.py` (`followup_common.py`, `_persona_utils.py`). Shell scripts invoked directly use `kebab-case.sh` (`log-event.sh`). A Python file that straddles both (importable library with a `__main__` block) follows the Python convention, since import compatibility takes precedence.

Rationale: Python's import system cannot handle hyphens in module names; consistent file naming prevents accidental import failures and makes the intended invocation mode clear from the filename.

---

## Project-specific

### P-001: Every Python module starts with `from __future__ import annotations`; signatures use modern syntax

Every `.py` file opens with `from __future__ import annotations` immediately after the module docstring (or after the shebang + docstring in scripts). All signatures use PEP 604 / PEP 585 syntax: `str | None` not `Optional[str]`, `list[str]` not `List[str]`, `dict[str, dict]` not `Dict[str, Dict]`. This applies to shebang scripts too (see `followup_common.py`); the future import is what makes these annotations evaluate lazily on older interpreters.

Rationale: Modern annotation syntax is more readable and drops the `typing` import boilerplate, while the future import keeps runtime compatibility without requiring a bleeding-edge Python.

### P-002: Shell scripts open with `set -euo pipefail`, a usage header, arg-count validation, and `# shellcheck source=` directives

All shell scripts begin with `#!/usr/bin/env bash`, then a header comment block documenting `Usage:`, `Example:`, and notable output conventions (slug namespacing, fallback tiers), as in `log-event.sh`. The first executable line is `set -euo pipefail`. Arg-count validation follows: `if [[ $# -lt N ]]; then echo "usage: ..." >&2; exit 2; fi` — usage to stderr, exit code 2 (not 1). Every `source` is preceded by `# shellcheck source=<relative-path>` so ShellCheck can follow the sourced file.

Rationale: `set -euo pipefail` stops silent failure propagation; exit 2 is the POSIX convention distinguishing "wrong invocation" from "runtime failure"; ShellCheck directives keep the linter accurate across sourced helpers.

### P-003: Structured telemetry enumerates payload fields explicitly and never logs `build_env()` output or secrets

When building an event payload (Python or shell), enumerate every field by name — never spread an opaque dict or pass `**kwargs`. SPEC Invariant #7, in `dispatcher.py`'s docstring, fixes `dispatch_start` to exactly `{driver, command_id, session_id}` and `dispatch_end` to `{driver, command_id, wall_ms, exit_code, is_error}`, and forbids logging `build_env()` output. The same invariant applies to all telemetry emitted via `log-event.sh` or `log_metrics_event`: env dicts, API tokens, and secret-bearing path values never appear in payloads.

Rationale: Explicit field enumeration makes the schema auditable at a glance and prevents accidental secret exfiltration into append-only telemetry that may be retained indefinitely.

### P-004: Shared Python helpers stay stdlib-only; shell out to sibling scripts rather than importing heavyweight libraries

Modules imported by multiple callers (driver utilities, script helpers) use only the standard library. When a feature would normally come from a third-party package, implement it with stdlib primitives — as `_persona_utils.py` does with a hand-rolled `re`-based frontmatter parser instead of `import yaml` ("Minimal frontmatter parser (stdlib-only — no PyYAML dependency)"). When a Python helper needs logic already implemented in a sibling shell script, invoke that script via `subprocess` rather than re-implementing it (e.g. `_resolved_base_dir` shells out to `plan-path.sh` rather than reimplementing the 5-tier fallback chain).

Rationale: Stdlib-only shared helpers carry zero install-time dependency risk; shelling out to siblings keeps behavioral parity and avoids logic that diverges silently over time.

### P-005: Eager import-time validation over lazy first-use failure

When a module depends on external resources that must be valid for it to function (schema files, contract invariants), validate them at import time rather than deferring to first call. `runtime/validate.py` pre-loads and meta-validates all five contract schemas in a module-level loop, so a corrupt distribution raises at `import runtime.validate` rather than silently at the first `validate()` call hours into a run. Document the import-time failure semantics and any thread-safety assumption in the module docstring.

Rationale: Eager failure surfaces distribution corruption at startup — when it is cheap to diagnose — instead of mid-run, after partial results may already be committed.

### P-006: Mutating shared state uses atomic writes, and concurrency assumptions are documented

A write to a file that another process may read concurrently is performed atomically — write to a temp file in the same directory, then `os.replace()` onto the target — never a partial in-place rewrite. Holder records and locks that readers observe are serialized so no torn value is visible (see `GlobalLockContext`'s `.hb.lock` discipline in `followup_common.py`). Any concurrency assumption a module relies on (single-threaded dispatcher, advisory-only overlap, read-only-after-import cache) is stated in the module docstring, as `runtime/validate.py` does under "Thread-safety."

Rationale: Atomic replace guarantees a concurrent reader sees either the old or the new file but never a half-written one; documenting the assumption lets the next author know which invariant they must not break.
