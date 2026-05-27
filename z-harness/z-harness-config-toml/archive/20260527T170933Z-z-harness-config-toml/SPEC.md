# SPEC — z-harness TOML config (slice 1)

## Overview

Add a layered TOML config to z-harness exposed via a single Python helper `scripts/config.py`. Slice 1 ships the loader infrastructure, two functional knobs (`notify.level`, `docs.always_apply`), full docs, and migrates two commands as proof of pattern. Slim README to a target shape, relocate cut content into `docs/human/`.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/z-harness-config-toml/BRAINSTORM.md | 2026-05-27T17:04:48Z |
| RESEARCH.md | — | n/a |

Chosen framing: **codex** (layered policy profiles + resolver with `explain`).

---

## File 1: `scripts/config.py` (new)

**Purpose:** Single helper for reading, layering, exporting, and explaining z-harness TOML config.

**Shebang:** `#!/usr/bin/env python3`. Requires Python ≥ 3.11 (stdlib `tomllib`).

**Layered precedence (lowest → highest):**
1. Built-in defaults (module constant `DEFAULTS: dict` at top of file).
2. `$XDG_CONFIG_HOME/z-harness/config.toml` (default `~/.config/z-harness/config.toml`).
3. Repo-local: if `$Z_HARNESS_REPO_CONFIG` is set, use that path verbatim (exit 2 if it does not exist — loud failure for explicit overrides). Otherwise, run `git rev-parse --show-toplevel`; if successful, read `<toplevel>/.z-harness/config.toml`; if `git rev-parse` fails (not in a git repo), fall back to `./.z-harness/config.toml` in cwd. The `.z-harness/` directory is NOT searched upward.
4. Env vars matching the transliteration rule (`Z_HARNESS_<SECTION>_<KEY>`, uppercase, dots → underscores). Empty env vars are treated as missing layer.

Per-key shadowing (repo overrides global; env overrides both). Missing files at layers 2/3 silently skip (no error) UNLESS `$Z_HARNESS_REPO_CONFIG` was explicitly set.

**Built-in defaults (`DEFAULTS`):**
```python
DEFAULTS = {
    "schema_version": 1,
    "notify": {
        "level": "approval_only",   # off | approval_only | all
    },
    "docs": {
        "always_apply": "auto",     # always | auto | never
    },
}
```

`schema_version` MUST equal 1; mismatched user files exit 2 (matches providers.json convention).

**Subcommands:**

### `config.py get <dotted.key>`
Resolves layered value for the key. Prints raw scalar (string / number / bool) to stdout, no quotes. Unknown key → exit 3 with stderr message naming valid keys.
- `config.py get notify.level` → `approval_only`
- `config.py get docs.always_apply` → `auto`

### `config.py export-env`
Prints `export Z_HARNESS_<SECTION>_<KEY>="<value>"` lines for all defined keys. Designed for `eval "$(scripts/config.py export-env)"`.

No `--for <command>` flag in slice 1 (rejected as false-contract dead code).

**Transliteration rule** (implemented as an isolated pure function `_dotted_to_env(key: str) -> str`, independently testable):
- Lowercase TOML dotted-key → prefix `Z_HARNESS_` + uppercase + `.` to `_`.
- `notify.level` → `Z_HARNESS_NOTIFY_LEVEL`
- `docs.always_apply` → `Z_HARNESS_DOCS_ALWAYS_APPLY`
- Hyphens in keys are rejected at TOML load time (see "TOML key name validation" below). Nested keys (>2 levels) are explicitly out of scope for slice 1; if encountered, exit 2.

Values shell-quoted with `shlex.quote` unconditionally (even for current enum values; future-proofs against new knobs).

**Type coercion to shell:** TOML strings → bare quoted string. TOML booleans → `"true"` or `"false"` (lowercase string; consumers do string compare, not arithmetic test). TOML ints → quoted decimal string. No other types in slice 1 schema.

### `config.py ensure-defaults`
If `$XDG_CONFIG_HOME/z-harness/config.toml` does not exist, write it with all default keys + per-key inline comments. Idempotent: if file exists and is parseable, do nothing (no merging, no key-completion — leave user's file untouched). **Never writes repo-local.**

If the file exists but is 0 bytes OR fails TOML parse → exit 4 with actionable error ("file exists but is empty/unparseable: <path>. Remove or fix it manually."). **Never silently overwrite a broken file** (preserves the "no surprise mutations" guardrail).

Prints `created <path>` or `exists <path>` (or the error above).

### `config.py explain <dotted.key>`
Prints the effective value AND the source layer:
```
notify.level = "approval_only"   (source: defaults)
notify.level = "off"             (source: ~/.config/z-harness/config.toml)
notify.level = "all"             (source: env Z_HARNESS_NOTIFY_LEVEL)
```
Unknown key → exit 3.

### `config.py should-notify --event <kind>`
Centralized notification gate. **Exits 0 on a valid event** (whether the answer is yes or no), prints `yes` or `no` on stdout. Always-exit-0 makes shell consumers `set -e` safe: `[ "$(... should-notify --event approval)" = yes ] && <emit>`.

Strict event allowlist (slice 1):
- `approval` — approval-gate notifications (e.g. Phase 5 in /z-plan).
- `phase_end` — phase-completion notifications.
- `error` — error / blocker notifications.

Unknown event kind (typo, future kind not yet defined) → **exit 2** with stderr message listing the allowlist. This catches `--event failre` typos that would otherwise silently default to "no" and disable notifications.

Logic (when event is in allowlist):
- `notify.level == "off"` → print `no`.
- `notify.level == "approval_only"` → print `yes` if `event ∈ {"approval", "error"}`; else `no`.
- `notify.level == "all"` → print `yes`.

**Exit code truth table:**

| Code | Meaning | Examples |
|------|---------|----------|
| 0 | Success | All subcommands when no error |
| 2 | Schema / validation error | `schema_version != 1`; TOML parse failure (any layer); invalid enum value in **repo-local TOML or env**; explicitly-provided `$Z_HARNESS_REPO_CONFIG` points to nonexistent file; unknown event kind in `should-notify`; nested key >2 levels; hyphenated key |
| 3 | Unknown dotted-key | `config.py get notify.lvel` (typo) or `explain` for unknown key |
| 4 | I/O error | `ensure-defaults` can't create parent dir; existing config file is 0-byte/unparseable; permission denied reading any config file |

**Layered validation rules:**
- TOML parse failure at any layer → exit 2 (always hard-fail; never silent).
- `schema_version != 1` at any layer → exit 2.
- Invalid enum value in **repo-local TOML or env override** → exit 2 (project-specific or CI overrides should fail loud).
- Invalid enum value in **`~/.config/z-harness/config.toml` (global)** → stderr warning + fall back to built-in default for that key only (other valid keys preserved). Rationale: a typo in user-global should not brick every command across every repo.
- Unknown TOML keys (not in `DEFAULTS`) → silently ignored (forward-compatible; future schema additions don't break older readers).
- Empty env var (`Z_HARNESS_NOTIFY_LEVEL=""`) → treated as missing layer (skipped).
- Hyphenated keys (`notify-level` instead of `notify.level`) → exit 2 at TOML load with explicit error.
- Validation runs on every subcommand (same loader path).
- Schema enum validation is in Python (module-level `VALIDATORS` dict mapping dotted-key → set/callable).

**Event emission:**
On every successful invocation of **`export-env`** (NOT every subcommand — Codex suggested narrowing; `get`/`explain`/`should-notify` are read-only inspections, no event needed), emit ONE `config_resolved` event via `scripts/log-event.sh` **iff** `$Z_HARNESS_RUN` is set (events are scoped to a /z-* run).

De-dup: per-run, emit at most once. Implementation: open temp file `$TMPDIR/z-harness-config-resolved-$Z_HARNESS_RUN` with `os.open(..., O_CREAT | O_EXCL)`. If `FileExistsError`, skip event emission. Atomic by kernel guarantee; no flock needed.

Event emission lives in a small adapter function isolated from the resolver core (SRP — resolver stays testable without filesystem/harness side effects).

Event payload:
```json
{
  "values": {"notify.level": "approval_only", "docs.always_apply": "auto"},
  "sources": {"notify.level": "defaults", "docs.always_apply": "global"}
}
```

**Error handling:**
- Missing config file (global or repo) → silently skip that layer (matches providers.json).
- Permission denied reading config → exit 4 with actionable message.
- `ensure-defaults` can't create parent dir → exit 4.

---

## File 2: `scripts/config.sh` (new)

Thin wrapper, matches `resolve-provider.sh` pattern:
```bash
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/config.py" "$@"
```

---

## File 3: `docs/human/config.md` (new)

Sections (in order):
1. **What this is** — one paragraph: layered TOML config, two-knob slice 1.
2. **File locations** — global vs repo-local; how to find them; precedence ordering.
3. **The knobs** — table: `key | type | default | values | description`. Two rows.
4. **The transliteration rule** — `notify.level` → `Z_HARNESS_NOTIFY_LEVEL`, etc. Explicitly stated so renames are visible.
5. **CLI reference** — one section per subcommand with example invocations.
6. **Examples** — `~/.config/z-harness/config.toml` example with both knobs set; repo-local override example.
7. **`config_resolved` event** — shape + how to read it from events.jsonl.
8. **Future knobs** — pointer to BRAINSTORM.md slices 2 and 3; explicit "do not add knobs without a /z-plan run."

---

## File 4: `docs/llm/config-design.json` (new)

```json
{
  "concept": "config-design",
  "summary": "Layered TOML config loader. Built-in defaults → ~/.config/z-harness/config.toml → repo .z-harness/config.toml → env. Single Python helper scripts/config.py with subcommands get|export-env|ensure-defaults|explain|should-notify. Slice 1 ships notify.level and docs.always_apply.",
  "invariants": [
    "schema_version == 1 (else exit 2)",
    "ensure-defaults never writes repo-local",
    "should-notify always exits 0; prints yes|no on stdout",
    "config_resolved event emitted once per $Z_HARNESS_RUN",
    "enum values: notify.level ∈ {off, approval_only, all}; docs.always_apply ∈ {always, auto, never}",
    "transliteration: dotted.key → Z_HARNESS_<SECTION>_<KEY>"
  ],
  "key_files": [
    "scripts/config.py",
    "scripts/config.sh",
    "docs/human/config.md"
  ],
  "depends_on": ["log-event", "providers-registry"],
  "consumed_by": ["commands", "skills"]
}
```

---

## File 5: `docs/llm/INDEX.json` (modified)

Add a new entry:
```json
{
  "slug": "config-design",
  "source_file": "scripts/config.py",
  "source_files": ["scripts/config.py", "scripts/config.sh", "docs/human/config.md"],
  "last_updated": "<UTC ISO 8601 of write>",
  "confidence": "high",
  "depends_on": ["log-event", "providers-registry"],
  "consumed_by": ["commands", "skills"],
  "summary": "Layered TOML config loader. Slice 1 = notify.level + docs.always_apply."
}
```

---

## File 6: `README.md` (rewritten)

**Target shape (verbatim outline):**
```
# z-harness

<one-paragraph pitch — what this is, who it's for, why it exists>

## Install
<existing install instructions, kept verbatim>

## Quickstart
- `/z-do <small task>` — plan-less execution for small changes
- `/z-plan <task>` — rigorous planning pipeline (SPEC/PLAN/TASKS)
- `/z-implement-all` — orchestrate the queue from a /z-plan output

## Where to look next
- [docs/human/INDEX.md](docs/human/INDEX.md) — human reference (commands, skills, agents, scripts)
- [docs/llm/INDEX.json](docs/llm/INDEX.json) — LLM-tier two-tier docs; agents read this via doc-fetcher
- [docs/human/config.md](docs/human/config.md) — TOML config (new)

## License
<existing>
```

**Migration:** Any reference material currently in README.md that doesn't fit the target shape moves to `docs/human/<topic>.md` (new file if needed) or, if already there, link replaces inline content. **Mitigates Gemini's README-as-LLM-orientation risk**: cut content is preserved, just relocated where doc-fetcher can find it. Add an entry in `docs/human/INDEX.md` for any new file created during migration.

---

## File 7: `commands/z-plan.md` (modified) — migrated command 1 (notify gate only)

**Scope of /z-plan migration: notify.level ONLY.** `/z-plan` is a heavy flow; it always dispatches doc-fetcher regardless of `docs.always_apply` (heavy flows are out-of-scope for that knob, not "ignoring `never`" — the knob simply does not apply to them).

The setup-section line that says "Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`)..." becomes:
```bash
# Setup config + notification gate
eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
# Notification gate (set -e safe):
#   [ "$(bash $PLUGIN_ROOT/scripts/config.py should-notify --event approval)" = yes ] && <PushNotification ...>
```

Every existing PushNotification call in /z-plan (Phase 2.5 / 5 / 8 / 9) gets wrapped with the appropriate `should-notify --event <kind>` guard (`approval`, `phase_end`, or `error`).

Existing prose referring to `Z_HARNESS_NOTIFY` is updated to point users at `docs/human/config.md` — the command file does NOT duplicate config docs.

---

## File 8: `commands/z-do.md` (modified) — migrated command 2

`/z-do` is a light flow → it's the command where `docs.always_apply` actually matters.
- Add the same `eval "$(... config.py export-env)"` setup line.
- The existing "dispatch doc-fetcher" conditional becomes:
  - `"always"` → unconditionally dispatch doc-fetcher.
  - `"auto"` (default) → current heuristic (dispatch only if certain triggers; preserve current behavior verbatim).
  - `"never"` → skip doc-fetcher.
- All PushNotification calls in /z-do gain the should-notify guard.

---

## Behavioral invariants (apply across all migrated commands)

1. After `eval "$(... config.py export-env)"`, `$Z_HARNESS_NOTIFY_LEVEL` and `$Z_HARNESS_DOCS_ALWAYS_APPLY` are guaranteed set to valid enum values (the loader validates).
2. The `should-notify` gate is the ONLY place that interprets `notify.level`; commands never `[ "$Z_HARNESS_NOTIFY_LEVEL" = ... ]`.
3. `docs.always_apply` is interpreted **only by light flows** (slice 1: /z-do). Heavy flows (/z-plan, /z-debug, /z-implement-all) always dispatch doc-fetcher; the knob does not apply to them. This is not "heavy flows ignore `never`" — heavy flows are out-of-scope for this knob entirely. Document the heavy/light split in `docs/human/config.md`.
4. The `config_resolved` event fires at most once per `$Z_HARNESS_RUN`, only from `export-env` (not from `get`/`explain`/`should-notify`). If a command launches subagents that also invoke `config.py`, those subagent invocations DO NOT re-emit (run-scoped O_EXCL de-dup).

---

## Edge cases

- **First invocation ever, no config file:** `ensure-defaults` is NOT called automatically by every command (would create surprise file). It's called explicitly by `/z-update` (existing command, modified to invoke it) and a one-line README install step. Until then, defaults from `DEFAULTS` apply silently.
- **Repo opened in CI with no `~/.config/z-harness/`:** defaults apply; no errors. CI uses env overrides.
- **Malformed user TOML:** loader exits 2 at first command invocation, halting any /z-* command. Error message includes file path + parser line/column. **This is intentional** — silent fallback would hide user errors.
- **User sets `notify.level = "loud"`:** exit 2 with allowed-values message. Prevents typos from silently disabling notifications.
- **`scripts/config.py` invoked outside a /z-* run (no `$Z_HARNESS_RUN`):** all subcommands work; no event emitted (event needs a run scope).
- **Concurrent /z-* runs:** each has its own `$Z_HARNESS_RUN`; each emits its own `config_resolved`. The temp-file de-dup is `$Z_HARNESS_RUN`-keyed, not PPID-keyed.

## Non-goals (slice 1)

- Prompt-fragment injection mechanism. (slice 3)
- Migration of consult preferences, escalation budgets, archive retention. (slice 2)
- Per-command filtering in `export-env --for <command>`. (slice 2 — currently accepted but ignored)
- `--init-repo` flag on `ensure-defaults`. (slice 2)
- Migrating skills/ files. (slice 2)
- Refactoring the other 26 commands. (slice 2+)

## DRY / KISS / SOLID

- **DRY:** Schema lives in exactly one place (`DEFAULTS` + `VALIDATORS` in `config.py`). Docs reference, don't duplicate. The single loader is consumed by both shell (`export-env`, `should-notify`) and Python contexts (`get`).
- **KISS:** No prompt-fragment injection mechanism in slice 1. No `--for <command>` filtering yet. Two knobs, four user-facing subcommands + one gate, one config file location per layer.
- **SOLID:** SRP — `config.py` only handles config loading/resolution; gating policy decisions live in the same module (one source of truth for "what does notify.level mean") but are isolated to `should-notify`. Open/closed — adding new knobs means appending to `DEFAULTS` + `VALIDATORS`; no subcommand or layer changes needed.
