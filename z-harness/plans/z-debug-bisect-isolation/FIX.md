# Fix: z-debug-bisect-isolation

**Run:** 20260527T032123Z-z-debug-bisect-isolation
**Status:** shipped (review cycle 2; user opted to skip a 3rd Codex pass after all 4 retry-1 findings were patched)
**Plugin version:** (recorded in light_run_start telemetry)

## Problem

`/z-debug` runs the full hypothesis-tournament pipeline (3 LLMs × 2 rounds × up to 5 isolation cycles) for every bug, even clean regressions with a known-good ref. For regressions, `git bisect run <repro-script>` is deterministic and locates the offending commit + line-level diff with zero LLM reasoning. Today the pipeline burns 5-10 consultant dispatches to converge on what bisect would have answered in a few minutes of mechanical work.

## Root cause

The pipeline has no fast-path for regressions. Every bug enters the same heavy loop regardless of whether a known-good baseline exists. The `Started:` field in Phase 1 captures the last-good ref but nothing downstream uses it.

## Approach

Add a new **Phase 2.5 — Regression bisect (conditional)** to `/z-debug`, gated on three preconditions:

1. `Started:` field from Phase 1 is not "unknown" (user supplied last-good ref/SHA/tag).
2. Phase 2 confirmed `Reproducibility confirmed: yes` (not partial/no).
3. Repro is scriptable (orchestrator can produce a shell command that exits 0=good, non-zero=bad).

When the gate passes, dispatch a new Haiku subagent `bisect-isolator` that:
- Verifies both refs exist.
- Sanity-checks repro: must fail on bad_ref AND pass on good_ref. If either inverts → `STATUS: bisect_unusable`, skip cleanly.
- Runs `git bisect start && git bisect bad <bad> && git bisect good <good> && git bisect run <script>`.
- Captures offending SHA, `git show --stat`, and capped diff (~4 KB).
- Always runs `git bisect reset` (even on failure) to clean up.
- Returns STATUS + OFFENDING_SHA + FILES_CHANGED + DIFF + SUMMARY. Mechanical only — no interpretation of WHY.

On `STATUS: ok`: orchestrator appends a high-confidence `EVID-NNN` entry to the Evidence Inventory tagged `source: bisect` containing the offending SHA + files changed + diff excerpt. Phase 3a hypothesis-generation prompts are augmented with the bisect result so LLMs can focus on WHY (mechanism), not WHERE (location).

On `STATUS: bisect_unusable` or gate-fail: skip silently, proceed to Phase 3a unchanged. **Bisect never replaces the hypothesis tournament** — it tells WHAT changed, not always WHY. A refactor commit can expose a latent bug elsewhere; the Round 1+2 adversarial rounds remain valuable. Bisect is a fast-path evidence-augmentation, not a gate.

**Refusal rubric for `bisect-isolator`** (Haiku, mechanical):
- Refuse if `repo_root` is not a git repo or `good_ref`/`bad_ref` don't resolve.
- Refuse if `repro_command` contains destructive shell verbs (`rm -rf` outside `repo_root/tmp/`, `git push`, `git reset --hard` on non-HEAD refs, anything writing to `~/dev/qt-bot/state/` or `~/dev/qt-bot/data/`).
- Refuse if `repro_command` references network mutations (e.g., contains `curl -X POST/PUT/DELETE`, `qtctl up <real-manifest>`).
- Refuse `interpretive_work` per the same boundary as `remote-runner` — if asked "why did this commit break it," return `STATUS: refused, reason: interpretive_work`.

**Side-effect safety:** the repro script runs ~log₂(N) times across N commits in the bisect range. The refusal grep is the primary defense. Document the constraint in the agent's "Hard rules" so callers don't pass scripts that mutate shared state.

## Files to change

- `/Users/zeke/dev/z-harness/agents/bisect-isolator.md` — NEW. Haiku subagent contract.
- `/Users/zeke/dev/z-harness/commands/z-debug.md` — EDIT. Insert Phase 2.5 section between Phase 2 and Phase 3a; add cross-references in the Phase-visibility matrix and Hard rules.

Not changed: docs/llm/ — this is a new internal command phase, not a new concept. `/z-maintain-docs` can refresh the `z-debug` concept entry later if desired.

## Acceptance

- [ ] `agents/bisect-isolator.md` exists with: YAML frontmatter (`name: bisect-isolator`, `tools: Bash, Read, Grep, Glob`, `model: haiku`); explicit input contract; refusal-check section listing destructive-verb grep + interpretive_work refusal; STATUS return shape with `ok | bisect_unusable | refused | failed`; telemetry start/end events using `scripts/log-phase.sh`.
- [ ] `commands/z-debug.md` Phase 2.5 section exists between Phase 2 (line ~138) and Phase 3a (line ~140) with: gate preconditions (Started ≠ unknown, repro reliable, scriptable); dispatch shape; behavior on `ok` (append EVID, seed Phase 3a); behavior on `bisect_unusable`/`refused` (skip silently); reference to the new agent.
- [ ] Phase-visibility matrix gains a row for Phase 2.5 (consultant call: N/A — Haiku not a consultant; bisect result becomes part of Evidence Inventory so it inherits the existing visibility rule for that section).
- [ ] Hard rules updated to note bisect is fast-path-only and never blocks the pipeline.
- [x] Codex review: cycle 1 (2 blockers + 3 majors → patched); cycle 2 (1 blocker + 3 majors → patched); user accepted ship-as-is rather than spend a 3rd cycle.

## Cross-LLM consensus

- Gemini: **unavailable** — consultant subagent stuck on permission-prompt in this session (sandboxed Bash for `gemini` CLI not authorized).
- Codex:  **unavailable** — same reason.
- Synthesized call: proceeded unilaterally with explicit self pre-mortem (one reason each design choice could be wrong, documented in conversation). Decision space is narrow: (a) insertion point post-Evidence/pre-hypothesis is the only place where bisect's output is both maximally useful and minimally disruptive to existing phase visibility, (b) "always feed in" is strictly safer than "replace" because bisect can mislead on refactor commits exposing latent bugs, (c) refusal rubric mirrors `remote-runner`'s mechanical-only boundary.

## Approved shortcuts

- **Skipped cross-LLM consult** — both consultant subagents failed on sandbox permission. The skill marks consult as "always emit" but the environmental failure is not a design risk. Codex review in Phase 8 remains the safety gate.

## Docs touched

None. (`z-debug` is a command, not a documented concept in `docs/llm/`. If desired, run `/z-maintain-docs --audit` after merge to refresh any concept referencing /z-debug's phase structure.)
