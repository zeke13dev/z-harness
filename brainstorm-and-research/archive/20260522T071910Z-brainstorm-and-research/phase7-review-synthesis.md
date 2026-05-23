# Phase 7 — Plan-review synthesis

Codex returned 10 findings + 3 boundary notes. Gemini was rate-limited but its fallback critique substantively overlapped. Categorized below.

## Apply (folds into SPEC amendment)

These hold up under "one reason this might be wrong" scrutiny:

1. **Consultant return-shape conflict (Codex F1).** The existing consultant return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt) is for *validation* modes. The new `MODE: brainstorm` returns a 5-section ideator block; `MODE: research-review` returns a critique-block (gaps to fill / errors to correct / no recommendation). SPEC clarifies: these two new modes DO NOT use the standard wrapper. They return raw ideator/critique content. The wrapper exists for validation modes only.
2. **Ideator failure policy (Codex F2 + Gemini).** Concrete degradation:
   - 1-of-3 fails → proceed with 2; anti-bias check explicitly notes "comparison is 2-way"; frontmatter `ideators` array records the failed member as `"<vendor>:failed"`.
   - 2-of-3 fails → halt + `AskUserQuestion`: retry / proceed-with-1 / abandon. Default: retry.
   - 3-of-3 → hard halt, push-notify, `total_ideator_failure` event.
3. **Restart/Abandon state machine (Codex F3).** "Restart" archives current BRAINSTORM.md to `archive/<run>/BRAINSTORM.md.previous-N`, prompts for refined topic, starts new RUN. "Abandon" sets frontmatter `status: abandoned`, leaves file in place, exits cleanly.
4. **Source-mtime edge cases (Codex F4).** Add to spec: timestamps in UTC ISO 8601; follow symlinks; deleted-file = `precontext_source_deleted` event (severity higher than stale-mtime); citation line-ranges check via min-line mtime (modified anywhere in range → stale).
5. **Citation regex broadened (Codex F5 + Gemini).** New regex: `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Extensionless paths (Makefile, Dockerfile) handled by an explicit allowlist scan. Markdown-link form `[label](path:line)` parsed by extracting the inner path. Parse failure → `precontext_freshness_check_failed`, continue (fail-open).
6. **Phase 1 boundary tightened (Codex F6).** Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set. Skip Explore iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
7. **Mirror tasks collapsed (Codex F8 + Gemini).** Each `commands/<x>.md` + `skills/<x>/SKILL.md` pair becomes ONE task — the implementer produces both in the same dispatch. Drops task count from 9 → 5. R1 mitigation becomes intrinsic to the task definition rather than a "remember to pair" hint.
8. **Acceptance criteria expanded (Codex F9).** Each task's acceptance adds the negative-case integration tests Codex listed: precontext-only continuation, finished-plan collision, stale-source warning, unfinalized brainstorm, both-artifact conflict.
9. **Telemetry field alignment (Codex F10).** Use existing `prompt_chars` / `response_chars` / `wall_ms` from log-event.sh pattern. `tokens_spent` is dropped from spec — `/z-stats` can compute approximate token spend from chars × ratio. The field stays in the design intent doc but not in the per-event payload until log-event.sh is extended (out of scope).
10. **input_hash computation (Gemini).** Add to spec: `input_hash = sha256(canonicalize(topic + "\n---\n" + doc_fetcher_or_empty + "\n---\n" + explore_or_empty + "\n---\n" + research_or_empty))` where canonicalize strips leading/trailing whitespace and collapses internal whitespace to single spaces.
11. **Anti-bias "tiebreaker" reframed (Gemini).** Not a tiebreaker — synthesis explicitly accepts "complementary coverage" as a valid outcome (each ideator addressed a different dimension). Orchestrator recommendation is a judgment call regardless.
12. **Re-run versioning (Gemini).** Re-running `/z-brainstorm <topic>` on a slug with existing BRAINSTORM.md prompts overwrite / append / abort. "Append" = move existing to `archive/<run>/BRAINSTORM.md.previous-N`, write fresh.
13. **Continuation-after-/z-plan (Gemini).** A slug with BRAINSTORM + RESEARCH + PLAN re-running `/z-brainstorm` is treated as refinement — overwrite/append/abort prompt fires.

## Push back

These are flagged but the spec position holds:

- **`research_temptation` event "over-specified" (Codex boundary).** Codex says no telemetry consumer. Keeping it — `/z-stats` can grow to surface it; the event is one-line cheap; the constraint matters for measuring how often the no-recommendation rule chafes against the orchestrator's reflex to opine.
- **Wall-clock budget enforcement gap (Gemini).** Real, but `Agent()` doesn't expose a per-call timeout knob. Accepting this as a known v1 limitation. Document explicitly: orchestrator-side polling not added in v1; subagents that hang block the brainstorm. User-facing escape: ctrl-c the orchestrator.
- **doc-fetcher caching (Gemini).** Out of scope, marked as v2 candidate. Cheap-enough today.

## Note on pre-applied edits

`commands/z-plan.md` and `skills/z-plan/SKILL.md` already contain a partial Setup step 10 (precontext detection) — added by the user or linter before TASKS.md was written. T007/T008 acceptance MUST verify that the remaining pieces (Phase 0 inject prose, Phase 1 boundary tightening, Phase 6 SPEC.md template `Planning Inputs` section, collision-handling rule) are in place; they should NOT revert the pre-applied step 10 work.
