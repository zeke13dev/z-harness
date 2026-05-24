# PLAN — MR-style code-quality reviewer

## Goals

Ship two slash commands (`/z-mr-review`, `/z-style-init` with `--amend` mode) and one new subagent (`mr-reviewer`) inside the z-harness plugin. Output is a TASKS.md-shape `MR-REVIEW.md` that the user prunes by deletion and feeds to `/z-implement-all`.

## Approved decisions (post-consult)

| ID | Decision |
|----|----------|
| D1 | Flat layout: `commands/z-mr-review.md`, `commands/z-style-init.md`, `agents/mr-reviewer.md` |
| D2 | Single `mr-reviewer` (Sonnet) fans out internally to `codex-consultant` + `gemini-consultant`. Findings tagged by voice. 3/3-voice consensus auto-promotes one tier; 1/3-voice auto-demotes one tier. |
| D3 | One file (`MR-REVIEW.md`) in TASKS.md shape. User deletes unwanted lines. `/z-implement-all --tasks=MR-REVIEW.md` consumes survivors. Pre-edit snapshot archived per run. No separate triage command. |
| D4 | `/z-style-init` Capture: heuristic prefilter (exclude vendored/generated/oversized) → Sonnet ranks → top-5 files into draft. |
| D5 | STYLE.md = required sections (`## Error handling`, `## Tests`, `## Comments`, `## Naming`, `## Project-specific`) + frontmatter (`schema_version, source, source_files, repo, revision, generated_at`) + stable rule IDs (`EH-001`, etc.). Reviewer cites by ID. |
| D6 | Five categories fixed in agent prompt: defensive-bloat / test-noise / abstraction / hygiene / style-drift. |
| D7 | Global `~/.claude/STYLE.md` — **v2 deferred** (approved shortcut). |
| D8 | `git diff <base>...HEAD` with `--base` override and `--include-untracked` flag. `gh pr diff` — v2 deferred (approved shortcut). |
| D9 | Slug default: normalized git branch name. Refuse on detached HEAD; refuse on trunk without `--force-on-trunk`. Reruns archive previous + overwrite. |
| D10 | Telemetry: `mr_run_start`, `mr_run_end`, `mr_finding_emitted`, `mr_style_missing`, `mr_voice_failed`, `style_init_complete`, `style_amend_complete`. |
| D11 | Sonnet default for all categories. Abstraction pass uses `Grep`/`Glob` mandatorily ("cite existing duplicate by file:line"). `--deep` flag upgrades the abstraction pass to Opus. |
| D12 | Diff > `Z_MR_DIFF_CHUNK_TOKENS` (default 80_000) → per-file chunking; merged at the dedup step. |
| D13 | **Robust in v1** (user override of v2 deferral): `/z-style-init --amend` reads recent MR-REVIEW.md archives, clusters dismissals (≥2 same-category similar-text findings), proposes new STYLE.md rules via `AskUserQuestion`. The `mr-reviewer` agent also reads recent archives and auto-demotes findings that match prior dismissals (tags them `[previously-dismissed-pattern]`). |
| D14 | If `codex` or `gemini` CLI unavailable, run with available voices; tag findings accordingly. All-voices-fail → error exit. |
| D15 | **`/z-debug` post-mortem integration** (v1, user-requested): post-mortem phase offers to run `mr-reviewer` on the fix diff; P0/P1 findings auto-append to post-mortem's preventative-actions list cited by `T-MR-NNN`. Change lives in `commands/z-debug.md`; mr-reviewer agent unchanged. |

## Non-goals (v1)

- Global STYLE.md merge — v2.
- GitHub PR fetch — v2.
- Auto-apply fixes (handled by `/z-implement-all`).
- Correctness bugs (handled by codex-reviewer).
- Bundling into `/z-review-all` as a phase — v2, prove signal first.
- Per-finding cost reporting beyond voice-count.

## Approved shortcuts (require explicit ack)

- (D7) Global STYLE.md deferred. Users with cross-project taste re-author per repo.
- (D8c) GitHub PR fetch deferred. Reviewing peer PRs requires local checkout.

Rejected shortcuts (user wants robust): D13 feedback loop is in v1.

## Ordered phases (implementation sequence)

Drives the TASKS.md ordering in Phase 8. Sequence revised post-Gemini-review (#6) — orchestrator skeleton lands before the agent so the agent has test fixtures (real `diff.patch` + `dismissed_signatures.json`) when first wired up.

1. **Foundation:** STYLE.md schema spec + rule-ID convention. (Pure spec/docs; no runtime code.)
2. **`scripts/extract-dismissals.py`** shared utility — used by both `/z-mr-review` and `/z-style-init --amend`. Build first; both downstream consumers depend on it.
3. **`/z-style-init` bootstrap mode** (Mode A): heuristic prefilter + Sonnet rank + user-confirm picked files + interview + draft + cross-LLM critique + write. Without this, `/z-mr-review` cannot run.
4. **`/z-mr-review` orchestrator skeleton:** slug resolution (with detached-HEAD + trunk guards), STYLE.md gate, voice-availability pre-check, diff capture, archive setup, dismissal-signature extraction (uses script from phase 2), telemetry. NO agent dispatch yet — at the end of this phase, the script writes `archive/$RUN/diff.patch` and `dismissed_signatures.json` and exits with "agent dispatch pending". This becomes the test fixture for phase 5.
5. **`mr-reviewer` agent (single-voice, single-pass first):** reads `diff_path` + STYLE.md + dismissed_signatures.json + base_sha, runs Claude-only inline review per the 5 categories with structured JSON return. Validates the JSON output contract end-to-end. Use phase 4's outputs as test fixtures.
6. **Wire orchestrator → agent (single-voice end-to-end):** orchestrator dispatches agent, parses return, writes `MR-REVIEW.md` (TASKS.md-shape) + archive snapshot. Full pipeline works for single voice.
7. **Multi-voice fan-out:** add Codex + Gemini consultant dispatch inside `mr-reviewer` (parallel `Agent()` calls). Voice tagging, consensus tier-bump (with P0-never-demote floor).
8. **Abstraction sub-pass tooling:** language-aware symbol extraction, common-name suppression list, mandatory Grep/Glob, `--deep` flag → Opus upgrade. `mode=abstraction-only` plumbed end-to-end.
9. **Chunked-pass mode (D12):** orchestrator splits diff at byte threshold, dispatches agent N times in per-chunk mode + 1 abstraction-only pass; merges findings.
10. **Dismissal-pattern matching in `mr-reviewer` merge step:** signature comparison with stopword-stripped Jaccard ≥ 0.6, tag + P1-P4 demote (P0 tag-only). Operationalize falsifiability: emit `mr_finding_dismissed` events.
11. **`/z-style-init --amend` mode** (Mode B): use shared script with `--global`, cluster dismissals, propose rules via `AskUserQuestion`, append to STYLE.md sections with next-free rule IDs.
12. **`/z-implement-all --tasks=<path>` flag:** verify (or add if missing) the ability to point implement-all at a non-default tasks file.
13. **`/z-debug` post-mortem hook (D15):** edit `commands/z-debug.md` post-mortem phase to optionally invoke `mr-reviewer` on the fix diff, parse `findings_index` frontmatter (NOT prose), append P0/P1 to preventative-actions list cited by `T-MR-NNN`.
14. **Documentation:** `docs/human/mr-reviewer.md`, `docs/human/style-init.md`, `docs/llm/mr-reviewer.json`, `docs/llm/style-init.json`, INDEX.json registration. Plus README.md update listing the new commands. Cross-reference from `docs/human/z-debug.md` (if it exists) to the new post-mortem hook.

**Files modified outside the mr-style-reviewer surface (Gemini fix #11):**
- `commands/z-debug.md` (phase 13)
- `commands/z-implement-all.md` if `--tasks=<path>` flag is not already supported (phase 12)
- `docs/llm/INDEX.json` (phase 14)
- `docs/llm/commands.json`, `docs/llm/agents.json`, `docs/llm/scripts.json` (phase 14)
- `README.md` (phase 14)

## DRY / KISS / SOLID statement

- **DRY:** Reuses `codex-consultant` / `gemini-consultant` agents and `scripts/log-event.sh`. STYLE.md rule-ID schema mirrors docs/llm concept-slug pattern. `/z-implement-all --tasks=<path>` is the existing extension point — no new command.
- **KISS:** No separate triage command (file deletion = triage). No checkbox parsing. One agent, three command entry points (counting `--amend`). Sonnet default; Opus opt-in.
- **SOLID:** Each command does one thing. STYLE.md rule IDs are append-only (open/closed). `mr-reviewer` depends on consultant-agent interfaces, not Codex/Gemini CLIs directly.

## Risk log

- **Multi-voice style review may be noisy.** Falsifiability thresholds (>30% dismissal rate over ≥10 runs → retire) are in SPEC.md non-goals/criteria and surfaced in human docs. Re-evaluate after ~20 real-world runs.
- **Capture may surface ugly idiomatic files** (god-objects with low churn). Heuristic exclusion of files >800 lines mitigates; if still bad, user can edit STYLE.md or re-run `--amend`.
- **Dismissal-pattern matching false-positive** (auto-demoting legitimate new findings that *resemble* prior dismissals): mitigated by demoting one tier rather than dropping, and by appending `[previously-dismissed-pattern]` tag so user sees the heuristic fired.
