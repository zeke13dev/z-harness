# PLAN — z-harness TOML config (slice 1)

## Goal
Ship the first slice of a layered TOML config system: a Python helper at `scripts/config.py` with four user-facing subcommands plus one gate (`should-notify`), two functional knobs (`notify.level`, `docs.always_apply`), two-tier docs, slim README, and two migrated commands (`/z-plan`, `/z-do`) as proof of pattern. Defer prompt-fragment injection, consult-prefs, escalation budgets, and refactoring the other 26 commands to slices 2 and 3.

## Decisions (with rationale)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Python 3.11+ stdlib `tomllib` only, no fallback. | Mechanical; reversible; no extra runtime dep. |
| D2 | Defaults source-of-truth = `DEFAULTS` dict in `scripts/config.py`. | Codex framing: schema in code, can't drift. |
| D3 | Layer order: defaults → global TOML → repo TOML → env. | Matches `resolve-provider.py` precedent; preserves CI env override use case. |
| D4 | `ensure-defaults` writes user-global only; never repo-local. | Brainstorm guardrail (Claude's "auto-write only to user-global"). |
| D5 | API = `get` + `export-env` + `ensure-defaults` + `explain` + `should-notify` (post-consult). | Both consultants reviewed; export-env keeps env-var precedent; explain is load-bearing for layered debuggability. |
| D6 | One `config_resolved` event per `$Z_HARNESS_RUN`. | Snapshot, not per-key shadow. |
| D7 | Tri-state enum `"always" \| "auto" \| "never"` (post-consult, renamed from "smart"). | Three states map to three distinct intents; bool conflates. |
| D8 | Repo-local config at `.z-harness/config.toml`. | Co-located with existing `.z-harness/providers.json`. |
| D9 | `should-notify --event <kind>` always exits 0, prints `yes`/`no` (post-consult). | Set-e safe; future-proof for new event kinds without N-command rewrites. |
| D10 | `docs.always_apply` enforced in command shell logic (orchestrator decides). | doc-fetcher stays dumb-by-design. |
| D11 | Docs split: `docs/human/config.md` (full) + `docs/llm/config-design.json` (compact, wired into INDEX.json). | Two-tier pattern, established precedent. |
| D12 | README target shape: pitch + install + 3 quickstart commands + pointers; cut content relocated to `docs/human/`. | Mitigates Gemini's README-as-LLM-orientation risk (preserve, don't delete). |

## Non-goals (explicit)
- Prompt-fragment injection mechanism (slice 3).
- Migration of consult preferences / escalation budgets / archive retention (slice 2).
- Per-command filtering in `export-env --for <command>` (accepted but ignored in slice 1).
- `--init-repo` flag on `ensure-defaults` (slice 2).
- Migrating `skills/*/SKILL.md` files (slice 2).
- Refactoring the other 26 commands (slice 2+).
- **Adding any knob beyond notify.level and docs.always_apply** — both consultants flagged schema sprawl as the top long-term risk. Capped here.

## Approved shortcuts
None. The slice itself is a deliberate cut from the full Codex framing; no further corners cut within the slice.

## Phase 7 review applied (post-SPEC critique)
- Removed `--for <command>` placeholder from `export-env` API (both consultants flagged dead-code false contract).
- Scoped /z-plan migration to notify gate only (removes leaky-abstraction smell of "heavy flows ignore never"; `docs.always_apply` now explicitly applies only to light flows).
- Added explicit exit-code truth table to SPEC.
- Repo discovery rule made explicit (`git rev-parse --show-toplevel`, NO upward search of `.z-harness/` directory; `$Z_HARNESS_REPO_CONFIG=<nonexistent>` exits 2 not silent fallback).
- `config_resolved` event narrowed to `export-env` invocations only (read-only inspections don't emit).
- O_EXCL atomic temp-file de-dup specified.
- Global-config typo policy: stderr warn + per-key fallback to default (not whole-file brick); repo-local / env still hard-fail.
- `should-notify` retains exit-0 + yes/no stdout (Gemini's exit-code-as-boolean alternative was rejected; conflicts with set -e safety argument she herself made earlier).
- `ensure-defaults` does not perform deep merge or write-back (rejected — preserves "no surprise mutations" guardrail). Empty/unparseable existing file → exit 4 with actionable error.
- Strict event allowlist in `should-notify`; unknown `--event` → exit 2 (catches `--event failre` typos).
- TOML key name validation: hyphens / >2 nesting levels rejected at load time.
- Transliteration rule isolated to a pure testable function.

## DRY / KISS / SOLID
- **DRY:** schema in one place (`DEFAULTS` + `VALIDATORS` in `config.py`); docs/human/config.md and docs/llm/config-design.json reference, never duplicate.
- **KISS:** four subcommands, one gate, two knobs, no fragment injection, no per-command filtering yet.
- **SOLID:** `config.py` has one responsibility (config loading + resolution + gating). Open/closed — adding knobs touches only `DEFAULTS` + `VALIDATORS`; no subcommand changes.

## Ordered phases

### Phase A — Loader infrastructure (no behavior change yet)
1. Write `scripts/config.py` with `DEFAULTS`, `VALIDATORS`, layering, all five subcommands.
2. Write `scripts/config.sh` thin wrapper.
3. Test manually: `python3 scripts/config.py get notify.level`; `... explain notify.level`; `... ensure-defaults`; `... should-notify --event approval`; `... export-env`.

### Phase B — Documentation
4. Write `docs/human/config.md` with target outline (8 sections).
5. Write `docs/llm/config-design.json` (compact concept entry).
6. Add `config-design` entry to `docs/llm/INDEX.json`.
7. Add `config.md` link to `docs/human/INDEX.md` if it exists.

### Phase C — README slim + content relocation
8. Rewrite `README.md` to target shape (pitch + install + 3 quickstart + pointers + license).
9. For each section of the old README that doesn't fit the target shape: relocate into a `docs/human/<topic>.md` (new file if needed); add to `docs/human/INDEX.md`.

### Phase D — Migrate `/z-do` (light flow proof)
10. Add `eval "$(... config.py export-env)"` to /z-do setup.
11. Convert /z-do's doc-fetcher conditional to read `$Z_HARNESS_DOCS_ALWAYS_APPLY` (always/auto/never branches).
12. Wrap every `PushNotification` in /z-do with `should-notify --event ...` guard.

### Phase E — Migrate `/z-plan` (notify gate only — heavy flow doesn't touch docs.always_apply)
13. Add `eval "$(... config.py export-env)"` to /z-plan setup.
14. Wrap every `PushNotification` in /z-plan with should-notify guard (events: `approval`, `phase_end`, `error`).
15. Document the heavy/light split in docs/human/config.md (heavy flows always dispatch doc-fetcher; `docs.always_apply` applies only to light flows). commands/z-plan.md itself does NOT duplicate config docs.

### Phase F — Validation
16. Manual end-to-end smoke test: `/z-do "trivial"` with notify.level=off then with notify.level=all; verify gate works.
17. Inspect `events.jsonl` for `config_resolved` events; verify exactly one per run.
18. Run `config.py explain notify.level` from inside a repo with an override; verify source layer is reported.
