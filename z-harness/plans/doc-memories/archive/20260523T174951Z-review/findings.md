# Final review — doc-memories
Run: 20260523T174951Z-review
Base ref: aaa6f80 (working-tree-vs-last-commit; cumulative diff built by concatenating per-task archived diffs)
Diff stats: 12 tasks, ~2467 lines cumulative

Both consultant CLIs (gemini, codex) were unavailable in this environment → both returned Sonnet-fallback synthesis. Treat findings as one-LLM signal, not two; lean on per-task review (which had real consult cycles) as the primary correctness gate.

## Prong A — Implementation drift

### Severity: blocker
None — no implementation drift rises to blocker after applying "one reason it might be wrong."

### Severity: major

- **MEMORIES_PRESERVED baseline algorithm undefined.** SPEC says z-maintain-docs should compare `MEMORIES_PRESERVED: <N>` against an "expected count" but never defines the baseline (presumably the count in the pre-write JSON). Implementation in `skills/z-maintain-docs/SKILL.md` Phase 3 surfaces the value but does not document the comparison algorithm. *One reason it might be wrong:* doc-updater's contract already prohibits inventing memories, so MEMORIES_PRESERVED is purely advisory; a missed delta only fires the warning, never blocks. Recommend: amend SPEC to define baseline = pre-write JSON memory count; warning fires when MEMORIES_PRESERVED ≠ baseline.

- **Doc-fetcher synthesis budget excludes line-format overhead.** SPEC's 1500-byte truncation gate measures memory `text` only; each rendered line adds ~50-100 bytes (date + type + tags). At 3 memories × 3 concepts the overhead can run 450-900 bytes — non-trivial fraction of the 1500-byte budget. *One reason it might be wrong:* the 1500-byte threshold is itself conservative (below the 2 KB hard cap), and 120-char truncation is already aggressive — the margin probably absorbs the overhead in practice. Minor at most; could clarify by amending step 6 to measure rendered-line bytes.

### Severity: minor

- TAG_COLLISIONS Levenshtein heuristic is documented prose only (doc-updater is an agent, expected to be prose); could include an example pair to anchor the implementation.
- `memories_flat_missing` log emission point in doc-fetcher step 2.5a is referenced in SPEC but not tied to a specific shell branch in the agent prose.

## Prong B — Spec gaps

### Severity: blocker

- **Memory preservation on `doc-updater STATUS: not_enough_info`.** SPEC defines memory preservation only in the doc-updater success path. If doc-updater can't refresh (returns `not_enough_info` or errors), z-maintain-docs Phase 4 skips the write — but the SPEC is silent on whether existing memories in the unrefreshed JSON should survive (they will, since the JSON wasn't touched) or whether the orchestrator should attempt a memories-only preservation write. *One reason it might be wrong:* if doc-updater doesn't write, the JSON is left untouched and memories are de facto preserved by inaction — so this might be a documentation gap not a data-loss bug. Worth a one-line SPEC clarification: "on doc-updater failure, the JSON is left at prior state; memories survive by inaction; no recovery path needed."

### Severity: major

- **`expires` field lifecycle undefined.** SPEC defines `expires` as an optional author-set decay date, and /z-maintain-docs Phase 3 surfaces memories where `expires < today` for Keep/Edit/Delete. But what happens to `expires` on Keep? On `/z-suggest-memory --edit`? Should Keep auto-extend `expires` (e.g., +90 days) or leave it untouched (so the same memory re-flags every run)? *One reason it might be wrong:* the simplest design is "leave untouched on Keep; let `--edit` rewrite it" — which is implementable today without spec change. But the SPEC should say so explicitly.

- **Canonical tag taxonomy storage missing.** PLAN.md line 55 says `docs/llm/TAGS.txt` will hold the controlled set + human-canonicalized aliases. SPEC.md never describes TAGS.txt format or consumption path. Without it, every /z-maintain-docs run re-flags the same `perf` ↔ `performance` collision (no place to record the resolution). *One reason it might be wrong:* humans may prefer per-memory edit-the-tag over global aliasing; a global aliases file could mask real semantic differences. But the gap is real — PLAN mentions it, SPEC doesn't deliver it.

### Severity: minor

- **Salience-guidance vs. metric.** "Default to Cancel" is load-bearing across 3 surfaces (T007/T009/T010) but no metric exists to flag if memories-written drops below a baseline indicating institutional-memory loss. Philosophical; the design accepted this risk per PLAN D-decisions.

## Consensus vs disagreement

- **Both consultants** (such as they were): The implementation faithfully tracks SPEC across all 12 tasks; no missing files; no contract drift between producers and consumers (T001↔T006, T003↔T005, T007↔T009/T010).
- **Codex flagged but spurious** (after applying "one reason it might be wrong"):
  - Regex injection via tags — *false alarm* if kebab-case validation is enforced (it is, per SPEC).
  - Atomic-write cleanup race in regenerate-memories-flat.py — *false alarm*; os.replace() semantics are correct.
  - source regex doesn't match ISO 8601 timestamps — *false alarm*; `[A-Za-z0-9-]+` includes uppercase T/Z.
  - Concurrent read-during-write of MEMORIES-FLAT.md — *false alarm* on POSIX (atomic rename guarantees inode swap).
  - concept_hints derivation for SKILL.md paths — *already addressed* in T010 v2.

## Soft-spots to watch in production

1. Does the 1500-byte synthesis cap actually fire in real runs? Without dogfooding, the truncation path is untested in anger.
2. Are 547-day (~18-month) staleness threshold and per-memory `expires` overrides well-calibrated for actual organizational memory decay?
3. Does "Default to Cancel" lead to under-capture of genuinely novel insights? Recommend telemetry review after first month of usage.
