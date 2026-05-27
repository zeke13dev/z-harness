# Final review — fanout-escalate-primitive (v1a)

Run: 20260527T201122Z-review
Base ref: c5fa111 (commit before v1a landed, bundled into mega-commit 4cba78e)
Diff stats: 16 files, +2622 / -100 lines (v1a-scoped only; TOML config bundle excluded)

## Prong A — Implementation drift

### blocker
- (none)

### major
- (none — both consultants ran exhaustive file-by-file checks against SPEC.md; all 16 tasks faithfully implement their acceptance criteria)

### minor
- **Sub-flow prompt clarity** (Gemini Q6) — `/z-brainstorm` Phase 0 HEAVY sub-flow dispatch prompt says "Write the BRAINSTORM.md at path..." while the reconciler contract explicitly says "do NOT write to disk; return content." Both use the same agent dispatch shape; sub-agents have no Write tool in either case — but the inconsistent wording could mislead future implementers. **Recommended fix:** change sub-flow prompt to "Produce BRAINSTORM.md content for path X; the orchestrator will write the file; return full markdown content."

## Prong B — Spec gaps

### blocker (spec must be corrected before shipping)
- (none)

### major (spec should be amended; existing implementation may stand)

- **Live `SCOPE-*.json` writes are NOT atomic** (Codex B2/B8) — both [commands/z-audit.md](commands/z-audit.md) and [commands/z-brainstorm.md](commands/z-brainstorm.md) write the live file via simple redirect (`python3 -c "..." > "$LIVE_SCOPE"`). The archive copy IS atomic (tmp+rename), but the live copy isn't. Two parallel runs on the same slug could partially-overwrite. Mitigation exists (`last_run_id` field lets readers detect stale entries), but the write itself is racy. **Recommended fix:** change live write to `tmp+mv` matching the archive pattern (3-line edit in each command). Severity: race-condition prevention.

### minor (worth noting for future plans)

- **`/z-plan` integration with `chosen_pair`** (both consultants) — HEAVY runs emit `chosen_pair: {chunk_id, framing}` in BRAINSTORM.md frontmatter instead of `chosen_framing: claude|codex|gemini`. `/z-plan` Setup step 10 currently only reads `chosen_framing`. PLAN.md non-goals already exclude `/z-plan` integration from v1a; documented in z-brainstorm.md T016 section. v1b follow-up. Surfaced explicitly in `z-brainstorm.md` HEAVY Phase 4 user-facing message.

- **Tripwires 3 & 4 cannot fire against v1a stub** (Codex B1, Gemini Q2) — `scripts/scope-probe-calibrate.py` stub always returns MEDIUM in non-fixture mode (T006 design). Tripwire 2 (`pct_heavy < 20%`) fires structurally, not from real signal. CALIBRATION-EPOCH-1-SIGNOFF.md is honest about this: v1a is "infrastructure shipped, hypothesis not yet validated"; v1b is correctly gated. Acceptable framing.

- **SCOPE.json live-file GC** — no garbage collection mechanism for abandoned slugs leaves stale `SCOPE-<host>.json` files indefinitely. SPEC.md notes this as deferred. Acceptable for v1a.

## Consensus vs disagreement

**Both LLMs flagged:**
- `/z-plan` chosen_pair follow-up (already documented; acceptable)
- v1a stub limitation honestly disclosed (acceptable)
- Implementation faithfully matches SPEC (no drift)

**Only Codex flagged:**
- Live SCOPE write atomicity (B2/B8) — real race-condition concern; worth fixing

**Only Gemini flagged:**
- Sub-flow prompt wording clarity (Q6) — cosmetic but worth fixing

## Net verdict

**SHIP** with two amendments:
1. (major) Make live `SCOPE-*.json` writes atomic via `tmp+mv` in both `commands/z-audit.md` and `commands/z-brainstorm.md`.
2. (minor) Clarify sub-flow dispatch prompt wording in `commands/z-brainstorm.md` Phase 0 HEAVY branch.

Both amendments are <10 lines each; no design rework needed. v1a infrastructure is sound; v1b deletions correctly gated on epoch-2 calibration (which requires a real-world HEAVY trigger).
