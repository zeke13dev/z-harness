# run-brief — Unified command completion receipt

> Last updated: 2026-06-07  
> Covers source: docs/llm/run-brief-contract.json, docs/llm/run-brief-registry.json

## Overview

Every major z-command in the v1 registry emits a **Run Brief** at finalize: a fixed-schema receipt that answers what you asked for, how the harness approached it, what was decided, what happened, and what to run next.

- **Human surface:** plain text in chat (fixed headers: `INTENT:` / `APPROACH:` / `DECISIONS:` / `OUTCOME:` / `NEXT:`)
- **Machine source of truth:** `archive/$RUN/run-brief.json` under the plan or adhoc run directory
- **Push digest:** same JSON rendered to a single three-part line via `render-run-brief.py --format push`: `{intent[:80]} · {outcome[:60]} · Next: {next.label}`

Chat and push are **renders only** — they are never authored independently at finalize.

---

## Sections

| Section | Meaning |
|---------|---------|
| **Intent** | One-line statement of the user's goal (max 240 chars). Set early via `run-brief.sh init`. Must not be the command name alone. |
| **Approach** | 1–4 human bullets summarizing the plan taken (full profile only). Derived from approach.md, FIX.md, PLAN.md, or similar artifacts — no file paths in bullets. |
| **Decisions** | Table of user/orchestrator choices (`question_id`, `chosen`, optional `why`, `source`). May be empty. Aggregated from `events.jsonl` at finalize if still empty. |
| **Outcome** | What actually happened (max 400 chars): shipped, halted reason, audit summary, etc. |
| **Next** | Suggested follow-up: `{ "label": "...", "command": "/z-..." \| null }`. |

Optional `sources` object records which artifact or event fed each section (for debugging and tooling).

---

## Profiles

### Full (`profile: "full"`)

Used by workflow commands (plan, implement, audit, debug, fix, review, brainstorm). Requires **Intent, Approach, Decisions, Outcome, Next**. `decisions` may be `[]`.

### Lite (`profile: "lite"`)

Used by `/z-do` only. Requires **Intent, Outcome, Next** only. The `approach` and `decisions` keys must be **omitted** (not empty arrays). On early halt with no artifact, the finalize fragment may emit this minimal shape even for full-profile commands.

---

## v1 registry commands (11)

These commands emit a run brief on terminal completion (except noted skip paths):

| Command | Profile |
|---------|---------|
| `/z-plan` | full |
| `/z-implement-all` | full |
| `/z-implement-next` | full |
| `/z-audit` | full |
| `/z-audit-plan` | full |
| `/z-debug` | full |
| `/z-fix` | full |
| `/z-plan-light` | full |
| `/z-review-all` | full |
| `/z-brainstorm` | full |
| `/z-do` | lite |

**Skip brief (non-terminal):** `/z-implement-all` **compaction_pause** exit only — the run is paused, not finished.

Command → artifact mapping lives in `docs/llm/run-brief-registry.json` (see the unified-command-output plan SPEC).

---

## Excluded commands (meta / read-only / setup)

Not wired in v1 — no run brief at finalize:

`/z-stats`, `/z-where`, `/z-export`, `/z-setup`, `/z-update`, `/z-uplift`, `/z-research`, `/z-map`, `/z-plan-split`, `/z-overnight`, `/z-mr-review`, `/z-maintain-docs`, `/z-init-docs`, `/z-learn`, `/z-explain`

Secondary commands may be added post-v1 by extending the registry JSON.

---

## Artifacts and scripts

| Path | Role |
|------|------|
| `docs/llm/run-brief-contract.json` | JSON Schema (draft 2020-12) for `run_brief` + embedded registry schema. Root `$ref` points at `#/$defs/run_brief` so validators can load the contract file directly; validate registry JSON with `#/$defs/run_brief_registry`. |
| `docs/llm/run-brief-registry.json` | Command → profile, hooks, artifact paths |
| `scripts/run-brief.sh` | init / set-section / append-decision / finalize |
| `scripts/render-run-brief.py` | chat / push / json render; `--require` validation gate |
| `scripts/lint-run-brief.sh` | Schema + registry + fixture self-test |
| `commands/_fragments/run-brief-finalize.md` | Shared finalize block inlined into registry commands via `/z-export` |

Golden fixtures: `tests/run-brief-fixtures/full-shipped/run-brief.json`, `tests/run-brief-fixtures/lite-halted/run-brief.json`.

---

## Status values

`complete` · `halted` · `aborted` · `shipped` · `awaiting_approval`

Set by `run-brief.sh finalize` (often via `run-status.sh classify` when not preset).

---

## Debug flag

Set `Z_HARNESS_RUN_BRIEF_DEBUG=1` to additionally write a human-readable `run-brief.md` mirror beside `run-brief.json` for local debugging. Default off — JSON remains canonical.

When debugging a live run, export the flag before the command starts (or in the same shell session). After finalize, inspect:

- `archive/$RUN/run-brief.json` — canonical payload
- `archive/$RUN/run-brief.md` — mirror (debug only)
- Chat output — should match `python3 scripts/render-run-brief.py --run-dir archive/$RUN --format chat`

---

## Verification

### Automated (CI / pre-merge)

Run from repo root:

```bash
bash scripts/lint-run-brief.sh              # schema + registry + fixture self-test
bash scripts/lint-run-brief.sh --registry-only # 11 commands include finalize fragment
python3 scripts/render-run-brief.py --self-test
python3 scripts/export-common.py --self-test
```

After changing command bodies, re-export and re-lint:

```bash
python3 scripts/export-cursor.py
python3 scripts/export-codex.py
python3 scripts/export-agy.py
bash scripts/lint-run-brief.sh --registry-only
```

### Per-command smoke (manual)

For each row: run the command to a **terminal** exit (complete, shipped, or halted — not mid-run pause). Confirm `archive/$RUN/run-brief.json` exists, passes `render-run-brief.py --require`, and chat shows the expected headers.

| Command | One-line smoke |
|---------|----------------|
| `/z-plan` | Complete a plan run; expect full brief with approach from PLAN.md and decisions from `decisions.md`. |
| `/z-plan-light` | Ship or halt a light plan; expect full brief with approach from FIX.md. |
| `/z-implement-all` | Finish all tasks or halt on blocker; expect full brief — **no brief** on `compaction_pause` exit only. |
| `/z-implement-next` | Complete one task cycle; expect full brief with outcome referencing the task id. |
| `/z-audit` | Finish audit Phase 7; expect full brief with outcome summarizing REPORT.md. |
| `/z-audit-plan` | Finish plan audit; expect full brief referencing PLAN_AUDIT_REPORT.md. |
| `/z-debug` | Reach Phase 10 finalize (shipped or halted); expect full brief with DEBUG.md approach. |
| `/z-fix` | Reach Phase 10 finalize; expect full brief with FIX.md approach. |
| `/z-brainstorm` | Finish Phase 4; expect full brief with BRAINSTORM.md approach. |
| `/z-review-all` | Finish review finalize; expect full brief with outcome from `review_all_end` event payload. |
| `/z-do` | Complete adhoc run; expect **lite** brief (Intent / Outcome / Next only — no Approach or Decisions keys in JSON). |

Optional debug mirror: set `Z_HARNESS_RUN_BRIEF_DEBUG=1` and confirm `run-brief.md` appears beside JSON.

Full checkbox copy lives in the plan archive: `archive/20260607T174050Z-unified-command-output/verification-checklist.md`.

---

## Invariants

1. Chat text is always rendered from JSON.
2. `render-run-brief.py --require` runs before deregister on registry commands (complete/shipped); minimal brief on halt.
3. Empty `decisions` is valid.
4. `/z-stats` is not auto-invoked at command end.
5. Export inlines the shared finalize fragment so all IDE surfaces stay in sync.
