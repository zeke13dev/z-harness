# run-brief — Unified command completion receipt

> Last updated: 2026-07-11
> Covers source: docs/llm/run-brief-contract.json, docs/llm/run-brief-registry.json, docs/human/run-brief.md, scripts/run-brief.sh, scripts/render-run-brief.py, scripts/render-cost-summary.py, scripts/notify-discord.sh, scripts/lint-run-brief.sh, scripts/z-preflight.sh, scripts/z-teardown.sh, _fragments/run-brief-finalize.md, _fragments/run-brief-halt-finalize-execute.md, _fragments/run-brief-halt-finalize-plan.md, skills/z-plan/SKILL.md

## Overview

Every major z-command in the v1 registry emits a **Run Brief** at finalize: a fixed-schema receipt that answers what you asked for, how the harness approached it, what was decided, what happened, and what to run next. The canonical source of truth is `archive/$RUN/run-brief.json`; all chat and push text are renders from that JSON — never independently authored at finalize.

The chat render is a warm "Briefing" format: a glyph-titled heading (`### <glyph> <command> — <slug>`) followed by `**What**`, `**How**` (full profile only), `**Key decisions**` (full profile, omitted when empty), `**Result**`, and `**Next**`. The push format is a compact single line for notifications. Both are emitted by `render-run-brief.py`. `run-brief.sh init`/`finalize` are the two calls every registry command's Setup/Finalize phase must make (directly, or via the `z-preflight.sh`/`z-teardown.sh` lifecycle wrappers described below).

---

## Chat render format

`render-run-brief.py --format chat` produces:

```
### <glyph> <command> — <slug>

**What**  <intent>

**How**  <approach bullet 1> → <approach bullet 2> → ...

**Key decisions**
- <chosen (humanized)> — *<why>*
- <chosen (humanized)>

**Result**  <outcome>
**Next**  `<next.command or next.label>`
```

**Glyph mapping:** `complete` / `shipped` → `✓`; `halted` / `aborted` → `⛔`; `awaiting_approval` and default → `◐`.

**Lite profile** omits `**How**` and `**Key decisions**`; renders `**What**` / `**Result**` / `**Next**` only.

**Key decisions** section is omitted entirely when `decisions` is empty. Decision tokens are humanized (underscores replaced with spaces) for display; verbatim values remain in `events.jsonl`. The `why` field is surfaced as italic text after an em-dash. Up to 8 decisions are shown; overflow row count is noted.

**Cost summary text** is appended when `--cost-summary-text` is provided (injected by the finalize fragment from `render-cost-summary.py`).

Push format (unchanged): `{intent[:80]} · {outcome[:60]} · Next: {next.label}`

---

## Sections

| Section | Meaning |
|---------|---------|
| **Intent** | One-line statement of the user's goal (max 240 chars). Set early via `run-brief.sh init` — called directly by the Setup phase in commands that haven't migrated to the lifecycle wrapper, or as step 6 of `scripts/z-preflight.sh` in commands that have (see "Setup/finalize wrapper migration" below). Must not be the command name alone. |
| **Approach** | 1–4 human bullets summarizing the actual solution taken (full profile only). **Orchestrator must author this** via `run-brief.sh set-section --section approach --value/--file` before finalize on full-profile success. `extract_approach_bullets` scraping is the empty-only fallback. No file paths in bullets. |
| **Decisions** | User/orchestrator choices (`question_id`, `chosen`, optional `why`, `source`). May be empty. Aggregated from `events.jsonl` at finalize if still empty. `why` is surfaced in chat. `source` enum: `event` or `artifact`. |
| **Outcome** | What actually happened (max 400 chars): shipped, halted reason, audit summary, etc. |
| **Next** | Suggested follow-up: `{ "label": "...", "command": "/z-..." | null }`. |

Optional `sources` object records which artifact or event fed each section (for debugging and tooling).

---

## Profiles

### Full (`profile: "full"`)

Used by workflow commands (plan, implement, audit, debug, fix, review, brainstorm, amend). Requires **Intent, Approach, Decisions, Outcome, Next**. `decisions` may be `[]`. Chat renders all five sections (Key decisions omitted when empty).

### Lite (`profile: "lite"`)

**No command declares the lite profile at init time.** `/z-plan --quick` always sets `RUN_BRIEF_PROFILE=full` (see `skills/z-plan/SKILL.md`), so the only live path into `lite` is the automatic downgrade inside `run-brief.sh finalize` (`apply_lite_downgrade`) when a full-profile command halts before any artifact exists. Requires **Intent, Outcome, Next** only; `approach` and `decisions` keys must be **omitted** (not empty arrays). Chat renders What/Result/Next only.

Note: `_fragments/run-brief-finalize.md` itself still contains a stale placeholder-table line claiming "`/z-do` uses `lite`; all other v1 registry commands use `full`" — `/z-do` was deleted from the registry (see below). This is a source-file inaccuracy, not a doc inaccuracy; it does not change the runtime behavior described above (lite is still init-time-inert, downgrade-only).

---

## v1 registry commands (9)

| Command | Profile | Notes |
|---------|---------|-------|
| `/z-plan` | full | Also handles `--quick` — still full profile. Setup/Finalize routed through `z-preflight.sh` / `z-teardown.sh`. |
| `/z-execute` | full | Setup/Finalize still calls `run-brief.sh init`/`finalize` inline (not migrated to the lifecycle wrapper). |
| `/z-audit` | full | Setup/Finalize routed through `z-preflight.sh` / `z-teardown.sh`. |
| `/z-audit-plan` | full | Setup/Finalize still calls `run-brief.sh init`/`finalize` inline. |
| `/z-debug` | full | Setup/Finalize still calls `run-brief.sh init`/`finalize` inline. |
| `/z-fix` | full | Setup/Finalize routed through `z-preflight.sh` / `z-teardown.sh`. |
| `/z-review-all` | full | Setup/Finalize still calls `run-brief.sh init`/`finalize` inline. |
| `/z-brainstorm` | full | Setup/Finalize still calls `run-brief.sh init`/`finalize` inline. |
| `/z-amend` | full | init_after `amend_run_start`; finalize Phase 8; primary artifact `archive/$RUN/amendment.md`; fallbacks `INTENT.md`/`SPEC.md`/`PLAN.md`/`FIX.md`. Setup/Finalize routed through `z-preflight.sh` / `z-teardown.sh`. |

`/z-do` was removed from the registry (and from the command set entirely) during the skill-overhaul-phase1 refactor; there are no `/z-do` rows or references left in this doc, the LLM-tier JSON, or `run-brief-registry.json`.

**Skip brief (non-terminal):** `/z-execute` **compaction_pause** exit only — the run is paused, not finished.

Command → artifact mapping lives in `docs/llm/run-brief-registry.json`.

---

## Setup/finalize wrapper migration (z-preflight.sh / z-teardown.sh)

`scripts/z-preflight.sh` and `scripts/z-teardown.sh` are single-call lifecycle wrappers (resolve/session-id/RUN-stamp/claim/register/**run-brief init**/run_start/kernel-resolve on the Setup side; **run-brief finalize**/claim-release/deregister/run_end on the Finalize side). Neither reimplements run-brief logic — both shell out to `run-brief.sh init` / `run-brief.sh finalize` internally, so the schema/validation contract described in this doc is identical either way. This migration is **partial** as of this refresh:

- **Migrated to `z-preflight.sh`/`z-teardown.sh`:** `/z-plan`, `/z-audit`, `/z-fix`, `/z-amend` (all registry commands), plus two non-registry commands — `/z-explore` (all depths except its own separately-excluded `--depth=deep` chat format) and `/z-stats` (registers for watcher visibility via `--no-claim`; its `z-teardown.sh` finalize call sets `outcome`/`next` but the command never includes `_fragments/run-brief-finalize.md`, so it gets no rendered chat Briefing, no push, and no `--require` hard gate — it stays off the registry and off the "Excluded commands" caveat below).
- **Still inline (`run-brief.sh init`/`finalize` called directly, no wrapper):** `/z-execute`, `/z-debug`, `/z-audit-plan`, `/z-review-all`, `/z-brainstorm`.

For a migrated command, `run-brief.sh finalize` is called **twice** on the normal path — once inside the included `_fragments/run-brief-finalize.md` (step 3), and once inside `z-teardown.sh` (its own step 1). This is intentional, not a bug: `run-brief.sh finalize` is idempotent (re-validates and rewrites), and `z-teardown.sh`'s own docstring calls out that its steps are safe to call twice. The fragment's copy is what actually produces the chat/push renders and the `--require` hard gate; `z-teardown.sh`'s copy is bookkeeping ahead of claim-release/deregister/run_end.

---

## Excluded commands (meta / read-only / setup / terrain)

Not wired in v1 — no run brief at finalize. Terrain mapping is also excluded: use `/z-explore --depth=deep` for deep terrain runs.

`/z-stats`, `/z-export`, `/z-setup`, `/z-update`, `/z-research`, `/z-explore --depth=deep`, `/z-plan-split`, `/z-overnight`, `/z-mr-review`, `/z-maintain-docs`, `/z-init-docs`, `/z-learn`, `/z-explain`

"No run brief at finalize" here means no registry entry and no rendered chat Briefing / push / `--require` gate. `/z-stats` is a partial exception worth knowing about: since adopting `z-preflight.sh`/`z-teardown.sh` for lifecycle bookkeeping (registry visibility only), it now writes an `archive/$RUN/run-brief.json` via plain `init`/`finalize` calls — but it never includes `_fragments/run-brief-finalize.md`, so that JSON is never chat-rendered, pushed, or `--require`-gated. Treat it as an internal artifact, not a Run Brief in the sense this doc otherwise describes.

Secondary commands may be added post-v1 by extending the registry JSON.

---

## Artifacts and scripts

| Path | Role |
|------|------|
| `docs/llm/run-brief-contract.json` | JSON Schema (draft 2020-12) for `run_brief` + embedded registry schema. Root `$ref` points at `#/$defs/run_brief` so validators load the contract file directly; validate registry JSON with `#/$defs/run_brief_registry`. |
| `docs/llm/run-brief-registry.json` | Command → profile, hooks, artifact paths (9 commands). |
| `scripts/run-brief.sh` | init / set-section / append-decision / finalize |
| `scripts/render-run-brief.py` | chat / push / json render; `--require` validation gate; `--self-test` golden fixture checks |
| `scripts/render-cost-summary.py` | Reads `events.jsonl`, produces cost summary Markdown text passed via `--cost-summary-text` to `render-run-brief.py`. Non-fatal if absent. |
| `scripts/notify-discord.sh` | Posts Discord webhook embed (title + push-format body). Reads webhook URL from `notify.discord_webhook_url` config. 3-second timeout; non-fatal on failure. |
| `scripts/lint-run-brief.sh` | Schema + registry + renderer self-test + `_test_finalize_preserves_decisions` integration test (default mode). `--registry-only` greps command files for finalize fragment include. |
| `scripts/z-preflight.sh` | One-call Setup ceremony (resolve → session-id → RUN stamp → claim → register → **`run-brief.sh init`** → run_start event → kernel resolve) for migrated commands; see "Setup/finalize wrapper migration" above. |
| `scripts/z-teardown.sh` | One-call Finalize ceremony (**`run-brief.sh finalize`** → claim release → deregister → run_end event), idempotent, counterpart to `z-preflight.sh`. |
| `_fragments/run-brief-finalize.md` | Shared finalize block inlined into registry commands via `<!-- include: _fragments/run-brief-finalize.md -->` markers, expanded at export time by `runtime/drivers/_export_utils.py`. |
| `_fragments/run-brief-halt-finalize-execute.md` | Halt-path preamble for `/z-execute`; sets outcome + next then includes finalize fragment. Actually wired via a real (unfenced) include marker. |
| `_fragments/run-brief-halt-finalize-plan.md` | New `/z-plan`-flavored halt-finalize preamble fragment (sets outcome/next with `/z-plan`'s `decisions.md`/`PLAN.md`/`SPEC.md` artifact profile, then includes the shared finalize fragment) — mirrors the `-execute` fragment's shape. **Exists on disk but has no real (unfenced) `<!-- include: -->` marker anywhere in the repo as of this refresh** — every reference to it in `skills/z-plan/SKILL.md` (14 occurrences) is either prose or a `# include: ...` comment inside a fenced bash block, which `expand_includes` explicitly skips. `/z-plan`'s actual halt sites manually duplicate this fragment's body inline instead of including it. See gotchas. |

`_fragments/zplan-cost-gate-reference.md` is a related-but-separate fragment (z-plan's cost-gate telemetry/decision-table reference, extracted from `skills/z-plan/SKILL.md` at T113) — it is genuinely wired via a real include marker at `skills/z-plan/SKILL.md:667`, and its "Cleanup matrix" documents when the cost gate calls the run-brief halt-finalize wrapper (`zplan_cost_gate_halt_finalize`, see Finalize sequence below), but the file itself belongs to the z-plan cost-gate concept, not this one.

Golden fixtures: `tests/run-brief-fixtures/full-shipped/run-brief.json`, `tests/run-brief-fixtures/lite-halted/run-brief.json`.

**Fragment paths corrected in an earlier refresh:** the doc/index previously listed a fragment path rooted under the old `commands/` tier — `_fragments/run-brief-finalize.md` — and two files that never existed anywhere in git history, also rooted under that same retired `commands/` tier: `_fragments/run-brief-halt-finalize-implement-all.md` and `_fragments/run-brief-halt-finalize-implement-next.md` (leftovers from before the `z-implement-all`/`z-implement-next` → `z-execute` rename in commit `2731f1d`, and from the `commands/` → `skills/` migration). Real path is `_fragments/run-brief-finalize.md`; the real halt fragment for the unified implement command is `_fragments/run-brief-halt-finalize-execute.md`. That correction remains valid — it is unrelated to the newer `run-brief-halt-finalize-plan.md` wiring gap documented above.

---

## Status values

`complete` · `halted` · `aborted` · `shipped` · `awaiting_approval`

Set by `run-brief.sh finalize` (often via `run-status.sh classify` when not preset).

---

## Finalize sequence (full-profile success path)

Steps follow the canonical ordering in `_fragments/run-brief-finalize.md`.

1. **Aggregate decisions** — if `decisions` is still empty, parse `events.jsonl` via `aggregate_decisions()` and append via `run-brief.sh append-decision`.
2. **Author the approach (required)** — before calling `run-brief.sh finalize`, the orchestrator MUST set a crisp high-level "How" describing the actual solution:
   ```bash
   bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary>"
   # or for 2-4 steps:
   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
   ```
   The `extract_approach_bullets` scrape (which greps bullet lines from the artifact) is the **empty-only fallback** and runs only when `approach` is still unset at finalize time. Authoring always wins.
3. **Finalize** — `run-brief.sh finalize --run "$RUN"`: classifies status, validates JSON Schema, emits `run_brief_end`.
3.5. **Cost summary** — non-fatal; `render-cost-summary.py` reads `events.jsonl`; result passed as `--cost-summary-text` to the chat render in step 4.
4. **Chat render** — `python3 render-run-brief.py --run-dir "$CURRENT_ARCHIVE_DIR" --format chat [--cost-summary-text ...]`; printed to user.
5. **Push render** — when notify policy (`should-notify --event phase_end`) allows; single-line format.
5.5. **Discord render** — when notify policy (`should-notify --event phase_end --channel discord`) and `notify.discord_webhook_url` config allow; uses `notify-discord.sh`; non-fatal.
6. **Hard gate** — `render-run-brief.py --require` before `deregister`; on failure set `FINALIZE_STATUS=aborted`.

Skip authoring on halt/abort paths — the lite downgrade handles those cases.

`/z-plan`'s halt paths (Phase 7 TASKS guards, the cost-gate wrapper function `zplan_cost_gate_halt_finalize` at `skills/z-plan/SKILL.md:659` — a thin shim that now shells out to `scripts/zplan-cost-gate-runtime.sh halt-finalize` rather than inlining the halt-finalize steps itself — and the general "Run Brief — halt finalize" reference block) all reuse the same generic `_fragments/run-brief-finalize.md` include, manually inlining the same outcome/next-setting steps that `_fragments/run-brief-halt-finalize-plan.md` now packages (that packaged fragment exists but is not yet actually included anywhere — see the artifacts table above and gotchas below), then call `scripts/z-teardown.sh --status aborted`.

---

## Debug flag

Set `Z_HARNESS_RUN_BRIEF_DEBUG=1` to additionally write a human-readable `run-brief.md` mirror beside `run-brief.json` for local debugging. Default off — JSON remains canonical.

---

## Verification

### Automated (CI / pre-merge)

```bash
bash scripts/lint-run-brief.sh              # schema + registry + renderer self-test + finalize integration test
bash scripts/lint-run-brief.sh --registry-only  # 9 registry commands + z-execute halt-fragment check
python3 scripts/render-run-brief.py --self-test
```

**Current status:** `scripts/lint-run-brief.sh --registry-only` passes (verified against this refresh's working tree); the registry no longer declares any deprecated pass-through alias. Note `lint-run-brief.sh` has no orphan-fragment check, so `_fragments/run-brief-halt-finalize-plan.md`'s dead-include state (see gotchas) does not fail CI.

After changing command bodies, re-export via `/z-export` (or driver modules directly) and re-lint:

```bash
python3 -m runtime.drivers.cursor.export
python3 -m runtime.drivers.codex.export
python3 -m runtime.drivers.antigravity.export
bash scripts/lint-run-brief.sh --registry-only
```

### Per-command smoke (manual)

For each row: run the command to a **terminal** exit. Confirm `archive/$RUN/run-brief.json` exists, passes `render-run-brief.py --require`, and chat shows the Briefing format (glyph title, **What**/**How**/**Key decisions**/**Result**/**Next**).

| Command | One-line smoke |
|---------|----------------|
| `/z-plan` | Complete a plan run; expect full brief with approach from PLAN.md and decisions from `decisions.md`. |
| `/z-execute` | Finish all tasks or halt on blocker; expect full brief — **no brief** on `compaction_pause` exit only. |
| `/z-audit` | Finish audit Phase 7; expect full brief with outcome summarizing REPORT.md. |
| `/z-audit-plan` | Finish plan audit; expect full brief referencing PLAN_AUDIT_REPORT.md. |
| `/z-debug` | Reach Phase 10 finalize (shipped or halted); expect full brief with DEBUG.md approach. |
| `/z-fix` | Reach Phase 10 finalize; expect full brief with FIX.md approach. |
| `/z-brainstorm` | Finish Phase 4; expect full brief with BRAINSTORM.md approach. |
| `/z-review-all` | Finish review finalize; expect full brief with outcome from `review_all_end` event payload. |
| `/z-amend` | Finish Phase 8; expect full brief with approach from `amendment.md` (or an INTENT/SPEC/PLAN/FIX fallback). |

---

## Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `render-run-brief.py --require` runs on every terminal exit that includes the finalize fragment, before deregister.
3. Empty `decisions: []` is valid for full profile.
4. `/z-stats` is not auto-invoked at command end.
5. Export inlines the shared finalize fragment (`<!-- include: ... -->` markers, expanded by `runtime/drivers/_export_utils.py`) so all IDE surfaces stay in sync.
6. Full-profile success paths require the orchestrator to author `approach` via `run-brief.sh set-section` before finalize; `extract_approach_bullets` is the empty-only fallback, not the primary path.
7. Cost summary (step 3.5) and Discord render (step 5.5) are both non-fatal — failures do not abort the run or block the hard gate.
8. `run-brief.sh init`/`finalize` are the sole writers of `run-brief.json`, whether called directly by a command's Setup/Finalize phase or indirectly through `z-preflight.sh`/`z-teardown.sh` — the lifecycle wrapper never reimplements run-brief logic.

## Gotchas

- **`_fragments/run-brief-halt-finalize-plan.md` exists but is not actually included anywhere.** This `/z-plan`-flavored halt-finalize preamble fragment was added this refactor and correctly mirrors `_fragments/run-brief-halt-finalize-execute.md`'s shape (sets outcome + next, then `<!-- include: _fragments/run-brief-finalize.md -->`). But every one of its 14 references inside `skills/z-plan/SKILL.md` is either prose or a `# include: _fragments/run-brief-halt-finalize-plan.md` bash comment sitting *inside* a fenced code block — and `expand_includes` in `runtime/drivers/_export_utils.py` explicitly skips markers inside fenced code, so these comments are inert. There is no real (unfenced) `<!-- include: -->` marker for this file anywhere in the repo. `/z-plan`'s actual halt sites instead manually duplicate the fragment's own body inline (export `RUN_BRIEF_PROFILE`/`RUN_BRIEF_ARTIFACT`/fallbacks, `set-section outcome`, `set-section next`, then the real `run-brief-finalize.md` include, then `z-teardown.sh --status aborted`) at each of the ~14 sites instead of centralizing it through the new fragment. Net effect: correct runtime behavior (each site does the right thing), but the new fragment is currently dead weight — nothing exercises it, and no lint catches that. Treat the `# include:` comments as aspirational labels for "this mirrors the halt-finalize pattern," same as documented previously for the (now-resolved) `-execute` fragment's equivalent comments.
- `_fragments/run-brief-finalize.md` line 16 still says "`/z-do` uses `lite`; all other v1 registry commands use `full`" — `/z-do` no longer exists (removed from `run-brief-registry.json` and the command set this refactor). This is a stale line inside a source file, not this doc; it doesn't change any documented runtime behavior since no command declares `lite` at init time regardless.
- Lite profile forbids `approach` and `decisions` properties — do not emit empty arrays.
- Artifact missing on early halt triggers lite downgrade via finalize (not at init time) — but only on non-success paths; success with no artifact uses `ensure_approach_for_full`, not lite downgrade.
- `/z-execute` `compaction_pause` exit skips the brief (non-terminal).
- Export must inline `_fragments/run-brief-finalize.md` so Cursor/Codex/Antigravity copies stay in sync. Legacy `scripts/export-*.py` are deleted; use `runtime/drivers/<target>/export.py` or `/z-export`.
- `Z_HARNESS_RUN_BRIEF_DEBUG=1` optionally writes a human-readable `run-brief.md` mirror for local debugging (not default).
- `extract_approach_bullets` only runs when `approach` is empty at finalize; an authored approach always wins.
- `render_push` format is unchanged — single line: `intent[:80] · outcome[:60] · Next: label`. Discord step 5.5 uses the same push-format body via `notify-discord.sh`.
- Decision `source` enum is `event | artifact` — no other values are schema-valid.
- `_test_finalize_preserves_decisions` in `lint-run-brief.sh` proves that finalize keeps `decisions[]` intact when the artifact has no bullet lines on a complete path.
- `/z-plan` cost-gate cleanup happens after run-brief init/register; if register failed and no active-plan record exists, cleanup must not call deregister.
- For migrated commands (`/z-plan`, `/z-audit`, `/z-fix`, `/z-amend`), `run-brief.sh finalize` runs twice on the normal path — once via the included finalize fragment, once via `z-teardown.sh`. This is intentional and idempotent-safe, not a double-finalize bug — see "Setup/finalize wrapper migration" above.
- `/z-stats` and `/z-explore` also route through `z-preflight.sh`/`z-teardown.sh` for lifecycle bookkeeping (registry visibility) even though they stay off the run-brief registry; `/z-stats` in particular writes a `run-brief.json` that is never chat-rendered, pushed, or `--require`-gated because it never includes `_fragments/run-brief-finalize.md`. Don't mistake the presence of `archive/$RUN/run-brief.json` for "this command has a wired Run Brief."
- `docs/llm/INDEX.json`'s `run-brief` entry's `source_file` list, as applied by `/z-maintain-docs` before this refresh, may still be missing `scripts/z-preflight.sh`, `scripts/z-teardown.sh`, and `_fragments/run-brief-halt-finalize-plan.md` — `/z-maintain-docs` owns applying the updated `source_file` list from this refreshed concept JSON.

## Examples

- Successful `/z-plan` run: chat shows `### ✓ /z-plan — <slug>` with What/How/Key decisions/Result/Next.
- Halted `/z-audit` run with no REPORT.md yet: chat downgrades to lite, showing only What/Result/Next.
