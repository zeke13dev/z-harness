# run-brief — Unified command completion receipt

> Last updated: 2026-06-19
> Covers source: docs/llm/run-brief-contract.json, docs/llm/run-brief-registry.json, docs/human/run-brief.md, scripts/run-brief.sh, scripts/render-run-brief.py, scripts/lint-run-brief.sh, _fragments/run-brief-finalize.md, _fragments/run-brief-halt-finalize-implement-all.md, _fragments/run-brief-halt-finalize-implement-next.md

## Overview

Every major z-command in the v1 registry emits a **Run Brief** at finalize: a fixed-schema receipt that answers what you asked for, how the harness approached it, what was decided, what happened, and what to run next. The canonical source of truth is `archive/$RUN/run-brief.json`; all chat and push text are renders from that JSON — never independently authored at finalize.

The chat render is a warm "Briefing" format: a glyph-titled heading (`### <glyph> <command> — <slug>`) followed by `**What**`, `**How**` (full profile only), `**Key decisions**` (full profile, omitted when empty), `**Result**`, and `**Next**`. The push format is a compact single line for notifications. Both are emitted by `render-run-brief.py`.

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
| **Intent** | One-line statement of the user's goal (max 240 chars). Set early via `run-brief.sh init`. Must not be the command name alone. |
| **Approach** | 1–4 human bullets summarizing the actual solution taken (full profile only). **Orchestrator must author this** via `run-brief.sh set-section --section approach --value/--file` before finalize on full-profile success. `extract_approach_bullets` scraping is the empty-only fallback. No file paths in bullets. |
| **Decisions** | User/orchestrator choices (`question_id`, `chosen`, optional `why`, `source`). May be empty. Aggregated from `events.jsonl` at finalize if still empty. `why` is surfaced in chat. `source` enum: `event` or `artifact`. |
| **Outcome** | What actually happened (max 400 chars): shipped, halted reason, audit summary, etc. |
| **Next** | Suggested follow-up: `{ "label": "...", "command": "/z-..." | null }`. |

Optional `sources` object records which artifact or event fed each section (for debugging and tooling).

---

## Profiles

### Full (`profile: "full"`)

Used by workflow commands (plan, implement, audit, debug, fix, review, brainstorm). Requires **Intent, Approach, Decisions, Outcome, Next**. `decisions` may be `[]`. Chat renders all five sections (Key decisions omitted when empty).

### Lite (`profile: "lite"`)

Used by `/z-do` only. Requires **Intent, Outcome, Next** only. The `approach` and `decisions` keys must be **omitted** (not empty arrays). On early halt with no artifact, the finalize fragment may emit this minimal shape even for full-profile commands. Chat renders What/Result/Next only.

---

## v1 registry commands (9)

| Command | Profile |
|---------|---------|
| `/z-plan` | full |
| `/z-execute` | full |
| `/z-audit` | full |
| `/z-audit-plan` | full |
| `/z-debug` | full |
| `/z-fix` | full |
| `/z-review-all` | full |
| `/z-brainstorm` | full |
| `/z-do` | lite |

**Skip brief (non-terminal):** `/z-execute` **compaction_pause** exit only — the run is paused, not finished.

Command → artifact mapping lives in `docs/llm/run-brief-registry.json`.

---

## Excluded commands (meta / read-only / setup / terrain)

Not wired in v1 — no run brief at finalize. Terrain mapping is also excluded: use `/z-explore --depth=deep` for current deep terrain runs; `/z-map` is retained only as legacy compatibility.

`/z-stats`, `/z-where`, `/z-export`, `/z-setup`, `/z-update`, `/z-uplift`, `/z-research`, `/z-explore --depth=deep`, `/z-map` (legacy compatibility), `/z-plan-split`, `/z-overnight`, `/z-mr-review`, `/z-maintain-docs`, `/z-init-docs`, `/z-learn`, `/z-explain`

Secondary commands may be added post-v1 by extending the registry JSON.

---

## Artifacts and scripts

| Path | Role |
|------|------|
| `docs/llm/run-brief-contract.json` | JSON Schema (draft 2020-12) for `run_brief` + embedded registry schema. Root `$ref` points at `#/$defs/run_brief` so validators load the contract file directly; validate registry JSON with `#/$defs/run_brief_registry`. |
| `docs/llm/run-brief-registry.json` | Command → profile, hooks, artifact paths |
| `scripts/run-brief.sh` | init / set-section / append-decision / finalize |
| `scripts/render-run-brief.py` | chat / push / json render; `--require` validation gate; `--self-test` golden fixture checks |
| `scripts/render-cost-summary.py` | Reads `events.jsonl`, produces cost summary Markdown text passed via `--cost-summary-text` to `render-run-brief.py`. Non-fatal if absent. |
| `scripts/notify-discord.sh` | Posts Discord webhook embed (title + push-format body). Reads webhook URL from `notify.discord_webhook_url` config. 3-second timeout; non-fatal on failure. |
| `scripts/lint-run-brief.sh` | Schema + registry + renderer self-test + `_test_finalize_preserves_decisions` integration test (default mode). `--registry-only` greps command files for finalize fragment include. |
| `_fragments/run-brief-finalize.md` | Shared finalize block inlined into registry commands via `/z-export` |
| `_fragments/run-brief-halt-finalize-execute.md` | Halt-path preamble for `/z-execute`; sets outcome + next then includes finalize fragment |

Golden fixtures: `tests/run-brief-fixtures/full-shipped/run-brief.json`, `tests/run-brief-fixtures/lite-halted/run-brief.json`.

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

---

## Debug flag

Set `Z_HARNESS_RUN_BRIEF_DEBUG=1` to additionally write a human-readable `run-brief.md` mirror beside `run-brief.json` for local debugging. Default off — JSON remains canonical.

---

## Verification

### Automated (CI / pre-merge)

```bash
bash scripts/lint-run-brief.sh              # schema + registry + renderer self-test + finalize integration test
bash scripts/lint-run-brief.sh --registry-only  # 11 commands include finalize fragment
python3 scripts/render-run-brief.py --self-test
```

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
| `/z-do` | Complete adhoc run; expect **lite** brief (What/Result/Next only — no How or Key decisions in chat; no approach or decisions keys in JSON). |

---

## Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `render-run-brief.py --require` runs on every terminal exit that includes the finalize fragment, before deregister.
3. Empty `decisions: []` is valid for full profile.
4. `/z-stats` is not auto-invoked at command end.
5. Export inlines the shared finalize fragment so all IDE surfaces stay in sync.
6. Full-profile success paths require the orchestrator to author `approach` via `run-brief.sh set-section` before finalize; `extract_approach_bullets` is the empty-only fallback, not the primary path.
7. Cost summary (step 3.5) and Discord render (step 5.5) are both non-fatal — failures do not abort the run or block the hard gate.
