# amendment-brief

> Last updated: 2026-06-19
> Covers source: scripts/amendment-brief.py, scripts/amend-gate-decision.py

## Overview

`amendment-brief` is a pair of shared Python scripts that support the default-amend continuation
path in `/z-audit-plan` Phase 5 and `/z-review-all` Phase 6.6.

**`scripts/amendment-brief.py`** is the shared renderer. It takes a JSON payload describing two
lists of findings and emits a two-section markdown brief:

- **"Patched automatically (N corrections):"** — always present; lists every `spec_gap` finding
  that was auto-amended via `/z-amend --skip-user-gate`. When N is 0 the line reads "none."
- **"Worth your eyes (M):"** — present only when M > 0; renders each `premise_failure` finding as
  conversational prose ending in "rework \<affected\>, or proceed?" (or "rework this, or proceed?"
  when no `affected` field is available).

**`scripts/amend-gate-decision.py`** is the gate-decision helper consumed by `/z-audit-plan`
Phase 5. It maps the resolver envelope from `config.py resolve-question workflow.audit_to_amend`
to one of three gate tokens:

- `auto_split` — proceed without a popup; auto-amend `spec_gap` findings and render
  `premise_failure` findings via `amendment-brief.py` as conversational prose.
- `force_ask` — fall back to the 3-way interactive AskUserQuestion popup (legacy path).
- `halt` — abort immediately.

## Correction / approach split

Findings are split by their canonical `Class` field, which reuses the existing enum in
`commands/z-review-all.md:716`:

| Class | Human gloss | Default action |
|-------|-------------|----------------|
| `spec_gap` | "correction" — a factual/mechanical error in plan artifacts | Auto-amend via `/z-amend --skip-user-gate` |
| `premise_failure` | "approach" — a viability/design concern | Rendered as prose brief, no auto-action |

The discriminator is `Class`, never severity. `correction` and `approach` are human-readable
glosses only, not new enum values.

## amendment-brief.py interface

```
amendment-brief.py <file.json>
echo '{"corrections":[...],"approach_concerns":[...]}' | amendment-brief.py
```

Input JSON schema:

```json
{
  "corrections": [
    {"title": "string", "why": "string", "target": "string"}
  ],
  "approach_concerns": [
    {"concern": "string", "affected": "string (optional)", "suggestion": "string (optional)"}
  ]
}
```

- `corrections` items correspond to `spec_gap` findings successfully auto-amended.
- `approach_concerns` items correspond to `premise_failure` findings escalated to the user.
- `affected` is optional on approach concerns; when absent the brief falls back to "rework this,
  or proceed?".

Both `/z-audit-plan` and `/z-review-all` call the same script to avoid format drift.

## amend-gate-decision.py interface

```
echo '<resolver-json>' | python3 scripts/amend-gate-decision.py
python3 scripts/amend-gate-decision.py '{"result":"ask","source":"none","default":"amend"}'
```

Input: the JSON resolver envelope from `config.py resolve-question workflow.audit_to_amend`.
Output: single token (`auto_split` | `force_ask` | `halt`), no trailing newline.

Decision rules (precedence order):

1. `result == "halt"` → `halt` (explicit stop wins over everything)
2. `result == "skip"` → `auto_split` (user configured auto-amend)
3. `source == "none"` → `auto_split` (fresh user, no preference stored — new default)
4. `source in {config, memory}` AND `result in {ask, prefill}` → `force_ask` (explicit preference
   requests interaction)
5. All other combinations → `auto_split` (safe default, avoids spurious popup)

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/amendment-brief.py:1` — `amendment-brief` — shared renderer; file/stdin JSON → two-section markdown brief
- `scripts/amendment-brief.py:32` — `render_brief()` — core rendering function; returns deterministic markdown string
- `scripts/amend-gate-decision.py:1` — `amend-gate-decision` — gate-decision helper; maps resolver envelope to auto_split|force_ask|halt
- `scripts/amend-gate-decision.py:47` — `decide()` — 5-rule precedence logic
- `commands/z-audit-plan.md:554` — Phase 5 gate resolution — calls amend-gate-decision.py with resolved envelope; dispatches auto_split / force_ask / halt branches
- `commands/z-audit-plan.md:619` — Phase 5 amendment-brief render — builds JSON and pipes to amendment-brief.py
- `commands/z-review-all.md:926` — Phase 6.6 — calls amendment-brief.py with spec_gap corrections + premise_failure escalations
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `/z-audit-plan` Phase 5 — calls `amend-gate-decision.py` to get the gate token, then (on
  `auto_split`) calls `amendment-brief.py` to render the brief; presents brief conversationally
  with no popup.
- `/z-review-all` Phase 6.6 — calls `amendment-brief.py` only (no gate decision step needed;
  auto-amend was already done in Phase 6.5); writes `amendment-brief.md` to the archive;
  Finalize's `APPROACH_FILE` resolution prefers `amendment-brief.md` over the older approach seed.
- `config.py resolve-question workflow.audit_to_amend` — provides the resolver envelope consumed
  by `amend-gate-decision.py`; `source == "none"` is the fresh-user case that now maps to
  `auto_split` instead of prompting.

## Overnight / unattended behavior

`workflow.audit_to_amend` is in the default overnight allowlist
(`OVERNIGHT_AUTODECIDE_QIDS_DEFAULT`), auto-decided to `amend`. Under `Z_HARNESS_NO_ASK=halt`,
`amend-gate-decision.py` will therefore receive `result: skip, source: overnight_allowlist`, which
maps to `auto_split` (rule 2).

## Invariants

- Both commands call `scripts/amendment-brief.py` — not inline format strings. Format is
  defined in one place.
- The `auto_split` path never presents an `AskUserQuestion` popup; the brief is a conversational
  reply only.
- `amend-gate-decision.py` exits 1 on malformed input; orchestrator falls through to `ask`.
- `amendment-brief.py` always emits the "Patched automatically" line even when corrections is
  empty; it omits the "Worth your eyes" section only when approach_concerns is empty.
- `affected` on approach_concerns is optional by design — `premise_failure` findings may be
  plan-level with no single task target.
