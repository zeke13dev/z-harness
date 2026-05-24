---
artifact: tasks
slug: mr-style-reviewer
generated_at: 2026-05-23T19:46:23Z
total: 14
---

# TASKS — MR-style code-quality reviewer

Implementation broken into 14 tasks following PLAN.md's revised phase ordering. Each task fits a fresh context window. `/z-implement-all` picks up tasks in dependency order.

---

- [ ] T001. STYLE.md schema spec + example file
  **Files:** docs/human/STYLE-md-schema.md (new, reference doc)
  **Deps:** —
  **Acceptance criteria:**
  - Document the STYLE.md frontmatter fields (`schema_version`, `source`, `source_files`, `repo`, `revision`, `generated_at`) verbatim from SPEC.md.
  - Document the 5 required sections + rule-ID format (`EH-001`, etc.).
  - Include one fully-worked example STYLE.md (≥3 rules per section) as an appendix; this will be used as a test fixture by later tasks.
  - No runtime code in this task.
  **Complexity:** low

- [ ] T002. `scripts/extract-dismissals.py` shared utility
  **Files:** scripts/extract-dismissals.py (new), scripts/test_extract_dismissals.py (new test)
  **Deps:** T001
  **Acceptance criteria:**
  - Implements the signature, algorithm, normalization, and JSON output per SPEC.md "`scripts/extract-dismissals.py`" section.
  - `--max-runs N` (default 10) limits chronological scope.
  - `--global` flag scans `z-harness/*/archive/*/MR-REVIEW.md` instead of one slug.
  - Signature format: `(file, category, normalized_snippet)` — NO line range.
  - Normalization: lowercase, collapse internal whitespace, strip leading/trailing punctuation.
  - Test fixture: 3 synthetic archive runs with known dismissal patterns; pytest verifies output JSON matches expected signatures and `n_runs_scanned`.
  - Handles missing/empty archives gracefully (returns `{signatures: [], n_runs_scanned: 0}`).
  **Complexity:** medium

- [ ] T003. `/z-style-init` Mode A — bootstrap (Capture + interview + draft + critique + write)
  **Files:** commands/z-style-init.md (new)
  **Deps:** T001
  **Acceptance criteria:**
  - Frontmatter per SPEC: `description` + `argument-hint: [--amend] [--ingest <path>]`.
  - Refuses if STYLE.md already exists (unless `--amend`).
  - Capture: heuristic prefilter (gitignored + hardcoded exclusion list per SPEC + size band 50-800 lines), then Sonnet rank → top 5, then user-confirm `AskUserQuestion` (use / edit list / re-pick / abandon).
  - Interview: ≤4 `AskUserQuestion` prompts (error handling, tests, comments, project-specific). `--ingest <path>` skips interview, reads existing guide instead.
  - Draft STYLE.md per schema (frontmatter + 5 sections + rule IDs).
  - Cross-LLM critique: parallel `codex-consultant` + `gemini-consultant` dispatch in `MODE: style-critique`. Apply findings.
  - User approval: `AskUserQuestion` accept / edit-resave / re-critique / abandon.
  - Writes STYLE.md to repo root.
  - Logs `style_init_complete {source, sections_populated, rule_count}`.
  - `--amend` mode is OUT OF SCOPE for this task (see T011).
  **DOCS:** style-init
  **Complexity:** high

- [ ] T004. `/z-mr-review` orchestrator skeleton (no agent dispatch yet)
  **Files:** commands/z-mr-review.md (new)
  **Deps:** T002
  **Acceptance criteria:**
  - Frontmatter per SPEC: `description` + `argument-hint: [--slug <slug>] [--base <git-ref>] [--include-untracked] [--deep] [--force-on-trunk]`.
  - Slug resolution: default = normalize `git branch --show-current` (lowercase, `/` → `-`, strip non-alnum-dash). `--slug` overrides. Refuse on detached HEAD with explicit message. Refuse on `main`/`master`/`trunk` unless `--force-on-trunk`.
  - STYLE.md gate: refuse if no `./STYLE.md`, message "Run /z-style-init first."
  - Voice availability pre-check: `command -v codex`, `command -v gemini`. Record `voices_available`. Log `mr_voices_degraded` if only `claude` available.
  - Diff capture: `git diff <base>...HEAD` (base = `--base` > `main` > `master`), plus untracked if `--include-untracked`. Write to `archive/$RUN/diff.patch`.
  - Size + chunking decision: `wc -c < diff.patch` vs `Z_MR_DIFF_CHUNK_BYTES` (default 320000); set `mode=full` or `mode=per-chunk`. In per-chunk mode, split into `archive/$RUN/chunks/<NNN>-<sanitized-path>.patch` + write `chunks/manifest.json` per SPEC.
  - Archive setup: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-mr-review`, `mkdir -p`, archive any existing `MR-REVIEW.md` to `archive/$RUN/MR-REVIEW.md.previous-<N>`.
  - Dismissal extraction: invoke `scripts/extract-dismissals.py` from T002, output to `archive/$RUN/dismissed_signatures.json`. Emit one `mr_finding_dismissed` event per signature.
  - Logs `mr_run_start` (with `voices_available`, `diff_stat`, `mode`).
  - **Exits with "agent dispatch pending — implemented in T006"** so this task is testable in isolation.
  **DOCS:** mr-reviewer
  **Complexity:** high

- [ ] T005. `agents/mr-reviewer.md` agent (single-voice Claude-only, single-pass)
  **Files:** agents/mr-reviewer.md (new)
  **Deps:** T001
  **Acceptance criteria:**
  - Frontmatter per SPEC: `name: mr-reviewer`, `description`, `tools: Bash, Read, Grep, Glob, Edit, Write, Agent`, `model: sonnet`.
  - Input contract per SPEC: `slug, run_id, slug_dir, base, base_sha, diff_path (single .patch file), style_path, dismissed_signatures_path, voices_available, mode, chunk_meta, deep`.
  - Reads STYLE.md, diff (single `.patch`), `dismissed_signatures.json`.
  - Inline Claude review of the 5 categories (or subset per `mode`) with hardcoded principles: assume-correctness, every-line-justifies-itself-relative-to-existing-abstractions.
  - Returns findings as fenced ```json block with schema: `{findings: [{severity, category, file, line_start, line_end, title, detail, citation}]}`.
  - Returns `## Summary` block with counts + voices_used + dismissal_match_count.
  - Multi-voice + abstraction + dismissal-matching all OUT OF SCOPE (added in T007, T008, T010).
  - Test fixture: a fake diff.patch + STYLE.md + empty dismissed_signatures.json; manually verify agent return shape matches contract.
  **DOCS:** mr-reviewer
  **Complexity:** high

- [ ] T006. Wire `/z-mr-review` orchestrator → `mr-reviewer` agent (single-voice end-to-end)
  **Files:** commands/z-mr-review.md (edit)
  **Deps:** T004, T005
  **Acceptance criteria:**
  - Orchestrator dispatches `Agent(subagent_type="mr-reviewer", model="sonnet", ...)` with the single-pass input shape from SPEC.
  - In `mode=full`: one dispatch. In `mode=per-chunk`: defer to T009 (skip for now; orchestrator forces `mode=full` if diff fits, else errors with "chunking pending T009").
  - Orchestrator parses agent return JSON, writes `z-harness/<slug>/MR-REVIEW.md` AND `archive/$RUN/MR-REVIEW.md` (identical snapshot) in TASKS.md shape per SPEC (`T-MR-NNN`, severity-grouped sections, frontmatter with `findings_index`).
  - Logs `mr_run_end` with totals.
  - Final user message names MR-REVIEW.md path, finding counts, and the "delete what you don't want; then /z-implement-all --tasks=MR-REVIEW.md" line.
  - End-to-end test: against a small synthetic diff in a scratch repo, command runs cleanly and produces a valid MR-REVIEW.md.
  **Complexity:** medium

- [ ] T007. Multi-voice fan-out in `mr-reviewer`
  **Files:** agents/mr-reviewer.md (edit)
  **Deps:** T006
  **Acceptance criteria:**
  - Agent dispatches `codex-consultant` + `gemini-consultant` in parallel (single message, multiple `Agent()` calls) for each voice in `voices_available` minus `claude` (Claude runs inline).
  - Consultant prompt uses `MODE: mr-review` with the JSON output contract from SPEC (severity, category, file, line_start, line_end, title, detail, citation).
  - Parse failure on a voice → log `mr_voice_failed {voice, reason: "malformed_json"}`, continue with other voices. No retry.
  - Merge step: dedup by `(file, category, normalized_text)`; tag each finding with `voices: [<subset>]`.
  - Consensus tier-bump: if `len(voices) == len(voices_available) >= 2`, promote one tier (P0 stays). If `len(voices) == 1` AND `voices_available >= 2`, demote one tier (P0 stays — never demote P0). Single-available disables bumps.
  - Update agent return: `voices_used`, per-finding `voices` field surfaced in JSON.
  - Codex/Gemini consultants must NOT need changes to support `MODE: mr-review` if their existing prompt-pass-through accepts arbitrary modes; if they DO need changes, log as a follow-up but do not block this task — it's a 3-line addition each.
  **Complexity:** high

- [ ] T008. Abstraction sub-pass tooling (symbol-aware grep, `--deep` Opus upgrade)
  **Files:** agents/mr-reviewer.md (edit)
  **Deps:** T007
  **Acceptance criteria:**
  - When `abstraction` is in active categories: agent extracts symbol names from diff via language-aware regex (Rust `fn (\w+)`, Python `def (\w+)`, TS `(function|const) (\w+)\s*=`, etc. — implement Rust + Python + TS/JS at minimum, document the others as easy to extend).
  - Hardcoded common-name suppression list per SPEC (`format, parse, init, get, set, new, build, run, main, default, from, to, into, as, value, name, key, id, data, result, item, handle`).
  - For each remaining symbol: `Grep -n "\b<symbol>\b"` across repo with appropriate `--include` glob, excluding diff's own files. Finding emitted only if a matching definition (not just call site) exists.
  - When `mode=abstraction-only AND deep=true`: agent dispatches sub-pass via `Agent(subagent_type="general-purpose", model="opus", ...)` over the grep-narrowed candidate pairs.
  - Test: synthetic diff that adds `fn format_price` while `fn price_str` already exists in repo → finding fires citing the existing file:line.
  **Complexity:** high

- [ ] T009. Chunked-pass mode (large diffs)
  **Files:** commands/z-mr-review.md (edit), agents/mr-reviewer.md (edit if needed)
  **Deps:** T007, T008
  **Acceptance criteria:**
  - Orchestrator: in `mode=per-chunk`, dispatch agent ONCE PER chunk with `mode=per-chunk` (4 categories — skip abstraction) + populated `chunk_meta`. Plus ONE additional whole-diff abstraction-only pass with `mode=abstraction-only` + `chunk_meta=null` + `diff_path=archive/$RUN/diff.patch`.
  - Orchestrator merges N+1 agent returns: per-chunk findings union'd, then dedup'd; abstraction-only findings appended.
  - Agent: `mode=per-chunk` suppresses abstraction category entirely. `mode=abstraction-only` runs ONLY abstraction.
  - Test: synthetic 500-KB diff (above threshold); orchestrator chunks correctly, fires N+1 dispatches, merged MR-REVIEW.md contains both per-chunk and abstraction findings.
  - `Z_MR_DIFF_CHUNK_BYTES` env override respected.
  **Complexity:** high

- [ ] T010. Dismissal-pattern matching in agent merge step
  **Files:** agents/mr-reviewer.md (edit)
  **Deps:** T002, T007
  **Acceptance criteria:**
  - Agent reads `dismissed_signatures.json` (already preprocessed by orchestrator via T002 script).
  - For each merged finding: compute `(file, category, normalized_text)` signature; check Jaccard ≥ 0.6 against any signature in dismissed file, after dropping stopwords `the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`.
  - On match: append `[previously-dismissed-pattern]` to detail. P1-P4 demote one tier. **P0 keeps severity (tag only).**
  - Test: synthetic dismissed_signatures.json with a known P1 signature; new finding matching it lands as P2 with the tag.
  **Complexity:** medium

- [ ] T011. `/z-style-init --amend` mode
  **Files:** commands/z-style-init.md (edit)
  **Deps:** T002, T003
  **Acceptance criteria:**
  - Refuses if STYLE.md does NOT exist.
  - Invokes `scripts/extract-dismissals.py <slug-dir> --max-runs 10 --global` (shared utility from T002).
  - Clusters by category + Jaccard ≥ 0.6 on normalized_snippet (after stopword strip); discards clusters with <2 members.
  - Dispatches Sonnet subagent: "given current STYLE.md (full) + N dismissal clusters, propose new rules with next-free IDs per section." Returns proposed rules.
  - User reviews via `AskUserQuestion`, multi-select per cluster: add-as-drafted / add-with-edits / reject.
  - Approved rules appended to right STYLE.md sections.
  - Logs `style_amend_complete {clusters, rules_added}`.
  **DOCS:** style-init
  **Complexity:** high

- [ ] T012. `/z-implement-all --tasks=<path>` flag verification (or add)
  **Files:** commands/z-implement-all.md (edit if needed)
  **Deps:** —
  **Acceptance criteria:**
  - Verify whether `/z-implement-all` already supports pointing at a non-default tasks file (`--tasks=<path>`).
  - If yes: document the usage in `commands/z-mr-review.md`'s final-message wording. No code change.
  - If no: add the flag. Default remains `z-harness/<slug>/TASKS.md`; `--tasks=<path>` overrides.
  - Test: `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md` correctly picks up `T-MR-NNN` tasks.
  **Complexity:** low

- [ ] T013. `/z-debug` post-mortem hook (D15)
  **Files:** commands/z-debug.md (edit)
  **Deps:** T006, T012
  **Acceptance criteria:**
  - Locate the post-mortem phase in `commands/z-debug.md`.
  - Add a new step (gated on `AskUserQuestion`): "Run MR-style quality review on the fix diff?"
  - If user accepts: invoke `Agent(subagent_type="mr-reviewer", ...)` with `slug=<debug-slug>`, `base=<pre-fix commit>`, `deep=false`, `mode=full`.
  - Parse the resulting `archive/<RUN>/MR-REVIEW.md` FRONTMATTER `findings_index` field (NOT prose) for severity=P0 and severity=P1 entries.
  - Append those finding titles (one line each, with `T-MR-NNN` cite) to the post-mortem's "Preventative actions" section.
  - Test: against a synthetic /z-debug run, accept the prompt, verify P0/P1 lines appear in the post-mortem.
  **Complexity:** medium

- [ ] T014. Documentation (human + LLM tiers, INDEX.json, README)
  **Files:** docs/human/mr-reviewer.md (new), docs/human/style-init.md (new), docs/llm/mr-reviewer.json (new), docs/llm/style-init.json (new), docs/llm/INDEX.json (edit), docs/llm/commands.json (edit), docs/llm/agents.json (edit), docs/llm/scripts.json (edit), README.md (edit)
  **Deps:** T011, T013
  **Acceptance criteria:**
  - `docs/human/mr-reviewer.md`: user-facing doc — what it does, when to use it, the 5 categories, P0-P4 rubric, the falsifiability thresholds (>90% audit parity / >30% dismissal rate → retire criteria, surfaced as living criteria).
  - `docs/human/style-init.md`: bootstrap mode + amend mode, the Capture insight, the rule-ID convention.
  - `docs/llm/mr-reviewer.json` + `style-init.json`: token-compact per existing pattern, with `last_updated`, `source_files` listing every file the concept covers.
  - `docs/llm/INDEX.json`: add 2 new concept entries.
  - `docs/llm/commands.json`: add `z-mr-review`, `z-style-init` entries.
  - `docs/llm/agents.json`: add `mr-reviewer` entry.
  - `docs/llm/scripts.json`: add `extract-dismissals.py` entry.
  - `README.md`: add commands to the listing.
  - Regenerate `docs/llm/MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py` if appropriate.
  - If `docs/human/z-debug.md` exists, add cross-reference to the new post-mortem hook (T013).
  **Complexity:** medium
