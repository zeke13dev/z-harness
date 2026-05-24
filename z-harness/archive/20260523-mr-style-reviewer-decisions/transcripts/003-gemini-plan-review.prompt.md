MODE: plan-review

## SPEC.md + PLAN.md critique for MR-style-reviewer feature

**Input artifacts:**

### SPEC.md (excerpt — key sections)

The feature adds three user-facing entry points (`/z-style-init`, `/z-style-init --amend`, `/z-mr-review`) and one Sonnet subagent (`mr-reviewer`) that fans out internally to `codex-consultant` and `gemini-consultant`. Findings are ranked P0–P4 (never blocks), tagged by voice (claude, codex, gemini), and output as TASKS.md-shape MR-REVIEW.md that users prune by deletion.

Key mechanics:
- STYLE.md is required; `/z-mr-review` refuses if absent.
- Findings deduplicated by `(file, line-range, category, normalized-text)`, voice-tagged, auto-tier-bumped by voice-count (3 voices → promote, 1 voice → demote).
- Dismissal-pattern matching: findings matching prior-archive deletions are auto-demoted and tagged `[previously-dismissed-pattern]`.
- Diff > 80_000 tokens → per-file chunking, merged at dedup.
- `/z-debug` post-mortem hook: optional MR-review of fix diff, P0/P1 findings auto-append to preventative-action list.

### PLAN.md (excerpt — 12-phase sequence)

1. STYLE.md schema spec
2. `/z-style-init` bootstrap (Capture → interview → draft → critique → write)
3. `mr-reviewer` single-voice (Claude only, writes MR-REVIEW.md)
4. `/z-mr-review` command (orchestration, slug, diff, dispatch, archive)
5. Multi-voice fan-out (Codex + Gemini dispatch, voice tagging, tier-bump)
6. Abstraction sub-pass tooling (Grep/Glob, `--deep` → Opus)
7. Diff chunking
8. `/z-style-init --amend` mode (archive scan, dismissal clustering, rule proposal)
9. Dismissal-pattern matching in mr-reviewer
10. `/z-implement-all --tasks` support
11. `/z-debug` post-mortem hook
12. Documentation

---

## Critique request

**Specific questions:**

1. **Agent input contract (SPEC lines 156–176):** The mr-reviewer receives `slug, run_id, diff_path (or chunked dir), style_path, recent_archives, deep`. Is this sufficient for an implementer to build the agent without gaps? Are `recent_archives` paths clear (last 5 snapshots, not live MR-REVIEW.md files)?

2. **Fragile or under-defined:**
   - **Chunking (D12):** Diff is chunked per-file if >80k tokens. How do findings from chunked diffs merge? Does the agent see each chunk independently, or do you assemble the full context per-file then split? If independent, how does the abstraction sub-pass (Grep/Glob) work across chunks?
   - **Voice tagging & dismissal matching (SPEC lines 174–179):** Dismissal-pattern match deduplication signature is `(file, line-range, category, normalized-text)` — but `line-range` is unstable across runs if the file grows. Should it be just `(file, category, normalized-text)` without line-range? Or does "normalized-text" absorb the risk?
   - **Dismissal-pattern match: "previous-dismissed-pattern" tag (SPEC line 178):** You demote by one tier *and* tag. But if a finding was P0 and is demoted to P1 *and* was dismissed once before, a second user doesn't see the P0 signal. Is that acceptable? Should dismissals be counted (e.g. `[dismissed-2x]` → demote deeper)?

3. **Ordered phases (1–12):** Phase 3 (mr-reviewer single-voice) before phase 4 (/z-mr-review command). But the orchestration command is where you set up the inputs the agent needs (diff.patch, slug, run_id, archive paths). Shouldn't phase 4 come first so you know the shape of the prompt you're passing to phase 3? Or is this testing-first (write the agent spec, then the command)?

4. **Missing tasks:**
   - **Diff-size heuristic in the orchestration (phase 4):** How do you decide to chunk? "If diff > 80k tokens" — but who tokenizes? The orchestrator bash command won't have access to a tokenizer without invoking an LLM. Is this a rough byte-count heuristic, or do you actually call Gemini/Claude to count, or is it deferred?
   - **Dismissal-archive scanning (phase 8):** `/z-style-init --amend` and mr-reviewer both scan recent archives to compute dismissal signatures. Is this logic centralized (a shared helper script) or copied?
   - **Voice unavailability fallback (D14):** "If Codex or Gemini CLI unavailable, run with available voices." What is the detection mechanism? Exit code from `which codex` / `which gemini`? Dry-run? This is late in the plan (phases 5–9) but affects orchestration setup (phase 4).

5. **DRY/KISS/SOLID violations:**
   - **Dismissal matching appears twice:** mr-reviewer does it (phase 9), `/z-style-init --amend` does it (phase 8). Same signature-extraction logic? If so, extract to a shared utility.
   - **Recent archives path resolution:** SPEC line 76 says "last 5 archived MR-REVIEW.md for this slug". Phase 8 says "last 10 z-harness/*/archive/*/MR-REVIEW.md across all slugs" (for amend). These have different scopes and recency windows. Is one forward-looking and one backward-looking? If it's intentional, document the difference clearly.

6. **`/z-debug` post-mortem hook (D15):** SPEC lines 303–312 say the hook is added to `commands/z-debug.md`'s post-mortem phase. But this plan file doesn't list z-debug.md as a source file to edit. Should it be in the modified files list, or is it genuinely out of scope for this feature's PLAN?

---

## Ask

Critique this plan — **what's wrong, missing, or fragile?** Be concrete. Point me at what needs clarification or redesign before implementation starts.
