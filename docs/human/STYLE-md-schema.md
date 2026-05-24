# STYLE.md Schema Reference

This document specifies the schema for `STYLE.md` files created by `/z-style-init` and consumed by `/z-mr-review`. `STYLE.md` lives at the root of the target repository.

---

## Frontmatter Fields

Every `STYLE.md` begins with a YAML frontmatter block. All six fields are required.

```yaml
---
schema_version: 1
source: capture | interview | ingest | natural-language | amend
source_files: [list of files Capture used]
repo: <repo name>
revision: <git-sha at init time>
generated_at: <iso>
---
```

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Schema revision. Currently always `1`. Increment only on breaking schema changes. |
| `source` | enum | How the file was authored. One of: `capture` (derived from idiomatic repo files), `interview` (answers to interactive questions), `ingest` (read from a user-supplied existing guide), `natural-language` (free-text input), `amend` (added rules from dismissal patterns via `--amend`). A single STYLE.md may combine sources; use the primary one here. |
| `source_files` | list of strings | Relative paths to the files that the Capture phase read (top-5 idiomatic files). Empty list if source is `ingest` or `natural-language`. |
| `repo` | string | Repository name (directory basename or org/repo). Used by `mr-reviewer` for display and archiving. |
| `revision` | string | Full git SHA at the time `/z-style-init` ran. Lets reviewers detect stale STYLE.md relative to large refactors. |
| `generated_at` | string | ISO 8601 timestamp of creation (e.g. `2026-05-23T19:00:00Z`). |

---

## Required Sections

A valid `STYLE.md` must contain these five top-level sections, in any order. Empty sections are allowed but discouraged — the init flow will warn if a section has zero rules.

| Section heading | Rule ID prefix | Topic |
|-----------------|---------------|-------|
| `## Error handling` | `EH-NNN` | How errors are propagated, wrapped, and silenced. |
| `## Tests` | `T-NNN` | Test structure, mocking posture, and coverage expectations. |
| `## Comments` | `C-NNN` | When to comment, what format, what to avoid. |
| `## Naming` | `N-NNN` | Identifier naming conventions for this repo's language(s) and domain. |
| `## Project-specific` | `P-NNN` | Rules that apply only to this codebase and don't fit the above categories. |

Additional sections are permitted but not consumed by `mr-reviewer` v1.

---

## Rule ID Format

Each rule within a section has a stable, unique ID derived from the section prefix.

```
EH-001   (Error handling, first rule)
EH-002   (Error handling, second rule)
T-001    (Tests, first rule)
C-001    (Comments, first rule)
N-001    (Naming, first rule)
P-001    (Project-specific, first rule)
```

Rules are **append-only and never reused**. When a rule is retired, it is replaced by a short tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that old `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).

### Rule markdown format

```markdown
### EH-001: <short rule title>
<one-paragraph rule prose — concrete, actionable>
Rationale: <one sentence explaining why this matters for the project>
```

Every rule must have:
- A heading at `###` level with the ID and a short title.
- One paragraph of rule prose (must be actionable, not vague).
- A `Rationale:` line.

---

## Appendix: Fully-worked example STYLE.md

The example below is a valid STYLE.md for a hypothetical Rust web-service project. It serves as a test fixture for tasks that validate schema parsing and `mr-reviewer` citation logic. It has at least three rules per section.

The full file content (frontmatter + body) is shown in the single fenced block below; this is exactly what `/z-style-init` would write to `STYLE.md` in the repo root.

```markdown
---
schema_version: 1
source: capture
source_files:
  - src/handlers/auth.rs
  - src/db/pool.rs
  - src/errors.rs
  - src/models/user.rs
  - tests/integration/api_test.rs
repo: acme-api
revision: a3f8c21e9b04d67f1c2e3a5b6d8e9f0a1b2c3d4e
generated_at: 2026-05-23T19:00:00Z
---

# STYLE.md — acme-api

## Error handling

### EH-001: Propagate errors with `?`; never swallow silently
Functions that can fail must return `Result<T, E>` and propagate errors with `?`. Never use `unwrap()` or `expect()` in non-test code unless the invariant making failure impossible is documented on the same line. Never use a bare `_ = fallible_call()` to discard an error silently.
Rationale: Silent failures are the leading source of production incidents in this codebase.

### EH-002: Wrap third-party errors with a typed project error variant
When calling external crates, convert their error types to an `AcmeError` variant using `map_err`. Do not `Box<dyn Error>` at module boundaries — use a concrete variant so callers can pattern-match.
Rationale: `Box<dyn Error>` at module boundaries destroys exhaustiveness and makes log parsing ambiguous.

### EH-003: Log before returning errors that cross service boundaries
Any error returned from an HTTP handler or RPC boundary must be logged at `error!` level before the `?` or `return Err(...)`. Errors that stay within a module do not need logging at each propagation step.
Rationale: Ensures every user-visible failure has a corresponding log entry, reducing mean-time-to-identify.

### EH-004: Do not use `panic!` in library code
`panic!` is allowed only in `main()` for unrecoverable startup failures (e.g. missing required environment variables) and in test code. Library functions must return `Err(...)` instead.
Rationale: Panics cannot be caught by calling crates and bypass our structured error telemetry.

## Tests

### T-001: Prefer integration tests over unit tests for handler logic
HTTP handler tests must exercise the full request/response cycle via `TestApp` (see `tests/helpers.rs`). Unit tests that mock the `HttpRequest` struct are not acceptable for handler code.
Rationale: Handlers are thin; the value is testing the composition with middleware and DB, not the handler function in isolation.

### T-002: Do not assert on log output in tests
Tests must not capture or assert on log strings. Test behavior via return values, database state, or HTTP response bodies. Log format is an internal implementation detail.
Rationale: Log-string assertions couple tests to message formatting and break whenever we improve log readability.

### T-003: Each test must clean up its own database state
Tests that write to the database must delete or roll back those rows at the end of the test, even on failure. Use the `TestDb::with_cleanup` fixture wrapper, not ad-hoc DELETE statements.
Rationale: Leaked state causes flaky test ordering dependencies.

### T-004: Name test functions as `<unit>_<scenario>_<expected_outcome>`
Test function names follow the pattern `fn auth_missing_token_returns_401()`. The unit is the thing being tested, the scenario is the condition, and the expected outcome is what the test asserts.
Rationale: Makes test failure output self-documenting without reading the test body.

## Comments

### C-001: No inline comments explaining what the code does — only why
Do not add comments like `// increment counter` above `counter += 1`. Comments must explain non-obvious intent, trade-offs, or invariants that are not visible from reading the code.
Rationale: What-comments drift and create false confidence; why-comments stay accurate longer.

### C-002: Every `unsafe` block must have a `// SAFETY:` comment
Any `unsafe { ... }` block must be preceded by a line-comment starting with `// SAFETY:` explaining which invariants the author is relying on and why they hold.
Rationale: Rustc requires unsafe for a reason; the SAFETY comment is the audit trail.

### C-003: Mark intentional TODOs with a ticket reference
`TODO` comments must include a tracking reference: `// TODO(#342): remove once migration completes`. Plain `// TODO: fix this` comments are not acceptable in merged code.
Rationale: Unanchored TODOs accumulate and are never resolved; ticket references make them actionable.

### C-004: Module-level doc comments (`//!`) are required for non-trivial modules
Any module with more than 3 public items must have a `//!` doc comment at the top of its `lib.rs` or `mod.rs` describing the module's responsibility in one paragraph.
Rationale: Speeds up onboarding and makes `cargo doc` output useful.

## Naming

### N-001: Use full English words for public identifiers; abbreviations only for locals
Public functions, types, and constants must use full words: `authenticate_user`, not `auth_usr`. Single-letter or abbreviated identifiers are acceptable only for short-lived locals inside a function body (e.g. loop index `i`, closure argument `e`).
Rationale: Public identifiers appear in docs, error messages, and grep output; abbreviations hurt discoverability.

### N-002: Boolean functions use an `is_` or `has_` prefix
Functions returning `bool` (or `Result<bool, _>`) must be named `is_<property>` or `has_<property>`: `is_expired()`, `has_admin_role()`. Avoid bare adjectives (`expired()`) or verb forms that are ambiguous (`check_expiry()`).
Rationale: Makes call sites self-documenting and lets readers identify boolean expressions quickly.

### N-003: Error type variants are past-tense events, not states
`AcmeError` variants name what went wrong, not what state resulted: `AuthTokenExpired` not `InvalidToken`; `DatabaseConnectionFailed` not `NoDatabase`. Use past-tense verb phrases.
Rationale: Past-tense event names are precise and distinct, which matters when multiple variants could describe the same bad state.

### N-004: Constants are SCREAMING_SNAKE_CASE; no magic literals in handler code
Named constants in `const` or `static` use `SCREAMING_SNAKE_CASE`. HTTP status codes, timeout values, and size limits must be named constants, not in-line integer literals.
Rationale: Named constants make intent clear and allow find-replace when values change.

## Project-specific

### P-001: Database queries go in `src/db/` — not inline in handlers or models
SQL queries (raw or via `sqlx::query!`) are permitted only inside files under `src/db/`. Handlers call `db::<module>::<function>(pool, ...)`. This is not a soft guideline; CI enforces it via a grep lint.
Rationale: Separates business logic from persistence, enabling query-level testing and future ORM migration.

### P-002: Never read environment variables outside of `src/config.rs`
`std::env::var` calls are permitted only in `src/config.rs` (which is called once at startup and returns a typed `Config` struct). All other code receives config via function argument.
Rationale: Prevents hidden runtime dependencies on environment state and makes config testable.

### P-003: Rate-limit wrappers must use the shared `RateLimiter` from `src/middleware/rate_limit.rs`
Route handlers that need rate limiting must apply `RateLimiter::new(...)` from the shared middleware, not roll their own in-handler counter logic. Custom counters in handlers are P0 findings.
Rationale: Consistent rate-limit behavior across endpoints; shared middleware is tested and audited.

### P-004: All new HTTP endpoints must have an entry in `docs/api/openapi.yaml`
Adding a new `router.route(...)` entry without a corresponding OpenAPI path entry is a P1 finding. The `openapi.yaml` is the contract with downstream consumers.
Rationale: Undocumented endpoints break API clients and violate our versioning policy.
```

---

*This reference is maintained by the z-harness project. If the SPEC.md schema section changes, update both this file and `docs/llm/style-init.json`.*
