---
description: Template for migrating z-harness command bodies to the C1 runtime contract.
---

# C1 Runtime Contract — Command Migration Template

This file documents the **standard header / footer / invoke pattern** every
`commands/z-*.md` file must adopt to conform to the C1 runtime contract
(`runtime.dispatch.driver.HostDriver` + `DispatchHandle` + `DispatchResult`).

---

## Standard Frontmatter Header

Every migrated command must carry a YAML frontmatter block at the **very top**
of the file, before any narrative text:

```yaml
---
description: <human-readable one-liner>
argument-hint: <optional; omit if the command takes no positional arguments>
runtime: c1
driver_features_required:
  - subagent          # present if the command dispatches Agent(...) calls
  - ask_user          # present if the command calls AskUserQuestion(...)
  - skill_invoke      # present if the command calls Skill(...)
unsupported_driver_behavior: explicit_gate
---
```

Key fields:

| Field | Required | Notes |
|-------|----------|-------|
| `description` | yes | Already present in most commands; keep verbatim. |
| `argument-hint` | no | Carry over if present; omit if absent. |
| `runtime` | yes | Always `c1` for this generation. |
| `driver_features_required` | yes | List only the features actually used. Empty list `[]` is valid. |
| `unsupported_driver_behavior` | yes | Always `explicit_gate` — see Gate Comment Pattern below. |

---

## Standard Footer — Runtime Contract Conformance Block

Append the following section at the **end** of every migrated command body
(after all operational phases, before any trailing separators):

```markdown
---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | <yes/no> | All `Agent(...)` calls |
| `ask_user` | <yes/no> | All `AskUserQuestion(...)` calls |
| `skill_invoke` | <yes/no> | All `Skill(...)` calls |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
```

Fill in the `yes/no` cells based on which features appear in the command body.

---

## Gate Comment Pattern

Any call to a feature that not all drivers support must be wrapped with an
**explicit gate comment**. The comment goes **immediately before** the call.

### `subagent` gate

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The command cannot
     proceed without subagent support. -->
Agent(
  subagent_type="...",
  ...
)
```

### `ask_user` gate

```
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question
     text to the user via their native interaction channel (e.g. a console
     prompt) and accept a text reply. Silent omission is forbidden. -->
AskUserQuestion(
  ...
)
```

### `skill_invoke` gate

```
<!-- RUNTIME-GATE: skill_invoke; non-supporting drivers must surface and skip
     this Skill() call, then log a skill_skipped event with the skill id. -->
Skill(
  ...
)
```

### Why explicit gate, not silent omission?

Silent omission (a driver simply not running the call) produces hard-to-debug
failures: the command appears to succeed while silently skipping a required
step. Explicit gating forces the driver to surface the gap to the user so they
can choose to abort, switch drivers, or acknowledge the limitation.

---

## Migration Checklist

Apply these substitutions to every `commands/z-*.md` file in order:

1. **Add frontmatter.** If the file already has a frontmatter block with only
   `description` / `argument-hint`, expand it to add:
   ```yaml
   runtime: c1
   driver_features_required: [...]   # populate after scanning the body
   unsupported_driver_behavior: explicit_gate
   ```
   If no frontmatter block exists, create one.

2. **Scan for `Agent(...)` calls.** For each occurrence:
   - Add `<!-- RUNTIME-GATE: subagent; ... -->` on the line immediately before.
   - Add `subagent` to `driver_features_required` if not already present.

3. **Scan for `AskUserQuestion(...)` calls.** For each occurrence:
   - Add `<!-- RUNTIME-GATE: ask_user; ... -->` on the line immediately before.
   - Add `ask_user` to `driver_features_required` if not already present.

4. **Scan for `Skill(...)` calls.** For each occurrence:
   - Add `<!-- RUNTIME-GATE: skill_invoke; ... -->` on the line immediately before.
   - Add `skill_invoke` to `driver_features_required` if not already present.

5. **Append the Runtime Contract Conformance block** (see Standard Footer above)
   at the end of the file.

6. **Verify** the `driver_features_required` list is the minimal set — include
   only features that have at least one gate comment in the body.

7. **Do NOT rewrite or simplify existing logic.** The migration is additive only:
   frontmatter fields + gate comments + conformance footer. Command behavior is
   unchanged.

8. **Run the conformance harness** on the migrated command (or at minimum on a
   representative command) before marking the migration complete:
   ```
   python3 tests/conformance/run_conformance.py --command <command-id> --mode replay --drivers claude-code
   ```
   Or via make:
   ```
   make conformance
   ```
   During the placeholder window (C5 golden fixtures not yet recorded), the
   test matrix exits 0 with `xfailed` / `xpassed` status — this counts as
   "passes exit 0" for acceptance purposes. Document the result in
   `migration-log.md`.

---

## Notes on `HostDriver` / `DispatchHandle` / `DispatchResult`

The C1 runtime contract is defined in:

- `runtime/dispatch/driver.py` — `HostDriver` ABC and `DispatchHandle` dataclass.
  - `HostDriver.init(provider_config, context=None)` — one-time driver initialisation.
  - `HostDriver.dispatch(command_id, args, env) -> DispatchHandle` — launches command, returns streaming handle.
  - `HostDriver.teardown()` — cleanup after dispatch cycle (default no-op).
  - `DispatchHandle.events() -> Iterator[dict]` — yields normalised event dicts.
  - `DispatchHandle.wait() -> DispatchResult` — blocks until subprocess exits.
- `runtime/dispatch/result.py` — `DispatchResult` dataclass (exit status, excerpts, metadata).

Command markdown files are **not** Python; they describe the orchestrator
behaviour that runs *on top of* a driver. Gate comments communicate to drivers
and humans which orchestrator features must be wired — they are not Python code.

---

## Example: Minimal Migrated Command

```markdown
---
description: Example command that asks a question and spawns a subagent.
argument-hint: <some argument>
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running /z-example.

## Phase 1

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this question
     to the user via their native channel and accept a text reply. -->
AskUserQuestion("What is the target? Options: A, B, C")

## Phase 2

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip if subagent support is unavailable. -->
Agent(
  subagent_type="Explore",
  description="Explore the target",
  prompt="..."
)

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 Agent() call |
| `ask_user` | yes | Phase 1 AskUserQuestion() call |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden.
```
