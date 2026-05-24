# SPEC — MR-style code-quality reviewer

## Overview

Two new slash commands and one new subagent in the z-harness plugin, focused on **code quality** (assumed-correctness review). Distinct from `codex-reviewer` and `/z-review-all`, which gate correctness. The reviewer ranks findings P0–P4 and never blocks — the user triages by deleting unwanted findings from a TASKS.md-shape output file.

Cross-LLM Nitpicker review: one Sonnet `mr-reviewer` agent fans out internally to Codex and Gemini consultants; findings tagged by which voices raised them.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/mr-style-reviewer/BRAINSTORM.md | 2026-05-23T19:24:15Z |
| RESEARCH.md | — | n/a |

## Surface

Three user-facing entry points:

1. **`/z-style-init`** — author project STYLE.md interactively, Capture-first.
2. **`/z-style-init --amend`** — read recent archived MR-REVIEW dismissals, propose STYLE.md rule additions (the feedback loop).
3. **`/z-mr-review`** — review the current branch diff against STYLE.md, write findings to `z-harness/<slug>/MR-REVIEW.md` in TASKS.md shape.

Plus one new agent:

4. **`mr-reviewer`** (Sonnet) — does the actual review. Internally dispatches `codex-consultant` and `gemini-consultant` via existing CLI-wrapper agents, dedups + tags + ranks findings, writes MR-REVIEW.md.

No `/z-mr-triage` command — user deletes lines they don't want from MR-REVIEW.md; `/z-implement-all --tasks=MR-REVIEW.md` consumes survivors.

## Files & paths

| Path | Kind | Purpose |
|------|------|---------|
| `commands/z-mr-review.md` | new | Orchestration narrative for `/z-mr-review`. |
| `commands/z-style-init.md` | new | Orchestration narrative for `/z-style-init` (with `--amend` mode). |
| `agents/mr-reviewer.md` | new | Sonnet agent contract — review the diff, fan out, return findings. |
| `STYLE.md` (in target repo) | new (created by `/z-style-init`) | Project style guide, schema below. |
| `z-harness/<slug>/MR-REVIEW.md` | new (written by `/z-mr-review`) | Findings in TASKS.md shape. User deletes unwanted lines. |
| `z-harness/<slug>/archive/<RUN>/MR-REVIEW.md` | new (snapshot) | Pre-user-edit copy of every run, source of truth for dismissal-pattern learning. |
| `docs/llm/INDEX.json` | edit | Add two concept entries: `mr-reviewer`, `style-init`. |
| `docs/llm/mr-reviewer.json` | new | LLM-tier doc for the new agent. |
| `docs/llm/style-init.json` | new | LLM-tier doc for the init flow. |
| `docs/human/mr-reviewer.md` | new | Human-tier doc. |
| `docs/human/style-init.md` | new | Human-tier doc. |

---

## File specs

### `commands/z-mr-review.md`

**Frontmatter:**
```yaml
---
description: Multi-LLM code-quality review of the current branch diff against STYLE.md. Never blocks; ranks P0-P4; output is a TASKS.md-shape file you edit and feed to /z-implement-all.
argument-hint: [--slug <slug>] [--base <git-ref>] [--include-untracked] [--deep] [--force-on-trunk]
---
```

**Required prelude (orchestration):**

1. **Setup:**
   - Resolve slug. Default: normalize `git branch --show-current` (lowercase, `/` → `-`, strip non-alnum-dash). Override: `--slug=<name>`. Refuse if detached HEAD (`git symbolic-ref -q HEAD` fails) with message "use --slug=<name>". Refuse on `main`/`master`/`trunk` unless `--force-on-trunk` (message: "almost certainly you want to review a feature branch").
   - Refuse if `STYLE.md` doesn't exist in repo root. Message: "Run /z-style-init first. There is no --no-style escape." Exit nonzero.
   - **Voice availability pre-check (Gemini fix):** `command -v codex` and `command -v gemini`. Record `voices_available = [claude, ...]`. If only `claude` is available, warn the user (continue, single-voice mode); log `mr_voices_degraded`.
   - Compute base ref: `--base` override > `main` if exists > `master` if exists. Compute diff: `git diff <base>...HEAD` plus `git ls-files --others --exclude-standard` if `--include-untracked`. Write the full diff to `archive/$RUN/diff.patch`.
   - **Size & chunking decision (Gemini fix #7):** `BYTES=$(wc -c < archive/$RUN/diff.patch)`. Threshold: `Z_MR_DIFF_CHUNK_BYTES` (default `320000`, ≈ 80k tokens). If `BYTES <= threshold`, single-pass mode. Else chunked-pass mode (see Step 3 below).
   - `RUN=$(date -u +%Y%m%dT%H%M%SZ)-mr-review`; `mkdir -p z-harness/<slug>/archive/$RUN`.
   - If existing `z-harness/<slug>/MR-REVIEW.md` exists, archive it to `archive/$RUN/MR-REVIEW.md.previous-<N>` before overwriting.
   - **Pre-compute dismissal signatures (Codex fix #1 + #11, Gemini fix #9):** orchestrator calls `scripts/extract-dismissals.py <slug-dir> --max-runs 10 > archive/$RUN/dismissed_signatures.json`. The script walks `z-harness/<slug>/archive/*/MR-REVIEW.md` (most recent 10), parses the snapshot, parses the corresponding non-archive copy at the time of that run's successor (i.e. compares snapshot to the snapshot of the FOLLOWING run, since the user's edits to MR-REVIEW.md happen between runs), and emits `{signatures: [{file, category, normalized_snippet, run_id}, ...]}`. **Signature format (Gemini fix #2):** drop line-range; use `(file_path, category, normalized_snippet)` with whitespace collapsed and case-normalized. Same script is reused by `/z-style-init --amend`.
   - Log `mr_run_start` event.

2. **Dispatch `mr-reviewer` agent — single-shape contract (Codex fix #2, Gemini fix #4):**

   The agent ALWAYS receives a single `diff_path` pointing to ONE patch file. Polymorphism is in the orchestrator, never in the agent contract.

   - **Single-pass mode:** orchestrator dispatches the agent ONCE with `diff_path = archive/$RUN/diff.patch`.
   - **Chunked mode:** orchestrator splits `diff.patch` into per-file patches at `archive/$RUN/chunks/<NNN>-<sanitized-path>.patch` (NNN preserves diff order), then dispatches the agent ONCE PER chunk with `diff_path = <chunk path>` and `chunk_meta = {index: NNN, total: M, manifest_path: archive/$RUN/chunks/manifest.json}`. Manifest format: `{chunks: [{index, path, files_touched, line_count}, ...], total_bytes, generated_at}`. Per-chunk findings are merged in step 3.
   - **Abstraction-aware merge (Codex fix #3, Gemini fix #1):** in chunked mode, after the N per-chunk passes, orchestrator runs ONE additional whole-diff abstraction-only pass with `mode=abstraction-only` and `diff_path = archive/$RUN/diff.patch`. This pass exists specifically to catch cross-file duplication and missed-extraction that per-chunk passes cannot see. The other four categories (defensive-bloat, test-noise, hygiene, style-drift) are diff-chunk-local, so chunked findings are sufficient for them.

   Agent prompt (always the same shape):
   ```
   Agent(
     subagent_type="mr-reviewer",
     model="sonnet",
     description="MR review for <slug>",
     prompt="slug: <slug>\nbase: <ref>\nbase_sha: <git-sha of base ref>\ndiff_path: <abs path — ALWAYS a single .patch file>\nstyle_path: <abs path>\nrun_id: <RUN>\nslug_dir: z-harness/<slug>\ndismissed_signatures_path: <abs path to dismissed_signatures.json>\nvoices_available: [<subset of claude,codex,gemini>]\nmode: <full | per-chunk | abstraction-only>\nchunk_meta: <null or {index,total,manifest_path}>\ndeep: <true|false>"
   )
   ```

   `base_sha` (Gemini fix #5) lets the agent `git show <base_sha>:<path>` to read pre-change file context when it needs to verify interface adherence.

3. **Merge results into one `MR-REVIEW.md`:**
   - Collect all agent returns (1 in single-pass mode, N+1 in chunked mode).
   - Dedup findings by `(file, category, normalized_text)` signature.
   - Apply consensus tier-bump (3/3 voices → promote, 1/3 → demote — see agent procedure step 5).
   - Apply dismissal-pattern matching (see agent procedure step 6). **P0 never demotes (Gemini fix #3, Codex fix #4)** — P0 with dismissal match only gets tagged `[previously-dismissed-pattern]`, severity preserved. P1–P4 demote one tier on match.
   - Write `z-harness/<slug>/MR-REVIEW.md` AND `archive/$RUN/MR-REVIEW.md` (identical pre-edit snapshot).

4. **Receive agent return(s).** Orchestrator (not agent) writes `z-harness/<slug>/MR-REVIEW.md` and `archive/$RUN/MR-REVIEW.md` (snapshot) from the merged findings. Returns include a structured `## Summary` block (counts, voices, dismissal-match count).

5. **If merged result has ≥3 dismissal-pattern matches** (findings that match prior-archive deletions), append a one-line suggestion to the orchestrator's final message: "Consider `/z-style-init --amend` — N findings match prior dismissals."

6. **Emit `mr_finding_dismissed` events (Codex fix #12 — operationalize falsifiability).** On EVERY run, after computing `dismissed_signatures.json`, emit one `mr_finding_dismissed {slug, category, prior_run_id}` per dismissed signature. This lets `/z-stats` compute dismissal rate over time; >30% triggers retire-warning in `/z-stats` output.

7. **Log `mr_run_end`. Push-notify (if policy ≠ off).** Final message to user names MR-REVIEW.md path + finding counts + "delete what you don't want; then `/z-implement-all --tasks=MR-REVIEW.md`".

**Failure modes the command handles:**
- Diff empty → exit 0 with "no changes vs <base>; nothing to review".
- All voices fail → exit nonzero, log `mr_all_voices_failed`.
- Diff > `Z_MR_DIFF_CHUNK_BYTES` (default 320_000) → chunked-pass mode (see Step 2 chunked-mode).

---

### `scripts/extract-dismissals.py` (NEW, shared utility — Gemini fix #9, Codex fix #11)

**Purpose:** the single source of truth for "what findings has the user dismissed in past runs?" Used by both `/z-mr-review` orchestrator and `/z-style-init --amend`.

**Signature:** `extract-dismissals.py <slug-dir> [--max-runs N] [--global]`
- `<slug-dir>`: e.g. `z-harness/mr-style-reviewer/`. Reads its `archive/*/MR-REVIEW.md` snapshots.
- `--max-runs N`: default 10. Most recent N archived runs (chronological by RUN id).
- `--global`: if set, scan `z-harness/*/archive/*/MR-REVIEW.md` across all slugs instead. (Used by `/z-style-init --amend` to learn cross-plan patterns.)

**Algorithm:** for each pair of consecutive runs (R_i, R_{i+1}) in chronological order:
1. Snapshot at `archive/R_i/MR-REVIEW.md` = original findings.
2. Current MR-REVIEW.md at time of R_{i+1} dispatch = the version that R_{i+1}'s setup archived to `archive/R_{i+1}/MR-REVIEW.md.previous-N`.
3. Dismissed = findings in (1) whose signature `(file, category, normalized_text)` does NOT appear in (2).

**Output:** stdout JSON `{"signatures": [{"file": ..., "category": ..., "normalized_snippet": ..., "prior_run_id": ...}, ...], "n_runs_scanned": N}`.

**Normalization:** lowercase, collapse internal whitespace to single space, strip leading/trailing punctuation. NO line-range in signature.

### `commands/z-style-init.md`

**Frontmatter:**
```yaml
---
description: Author the project STYLE.md interactively, grounded in the repo's most idiomatic existing files (Capture). Required before /z-mr-review will run.
argument-hint: [--amend] [--ingest <path-to-existing-guide>]
---
```

**Mode A: bootstrap (no `--amend`).**

1. **Refuse if `STYLE.md` already exists** unless `--amend`. Message: "STYLE.md exists; pass --amend to add rules from recent dismissals."

2. **Capture phase:**
   - Step 1 — heuristic prefilter: build candidate list from `git ls-files`, exclude (a) gitignored, (b) hardcoded exclusion list `[node_modules/, vendor/, dist/, target/, __pycache__/, *.pb.go, *_pb2.py, migrations/, __generated__/, .min.*, package-lock.json, yarn.lock, Cargo.lock, poetry.lock]`, (c) files <50 or >800 lines.
   - Step 2 — dispatch Sonnet subagent (`general-purpose`) to rank candidates by "idiomatic-ness" and pick top 5. Prompt includes the candidate list (paths only, not content) + repo language detection.
   - **Step 2.5 — user confirmation of Capture set (Codex fix #8):** present the picked 5 files via `AskUserQuestion` with options: `use these / edit list (free-text replacement paths) / re-pick (different 5) / abandon`. Prevents legacy god-objects from anchoring STYLE.md.
   - Step 3 — read the (possibly user-edited) 5 files into context.

3. **Interview phase (`AskUserQuestion`):** ask up to 4 questions:
   - Error handling philosophy (defensive vs propagate)?
   - Testing posture (mock-heavy / integration-heavy / mixed)?
   - Comment policy (when/why)?
   - Anything else this project insists on (free text)?
   If `--ingest <path>`: skip the interview, read the user's existing guide as the input instead.

4. **Draft STYLE.md** (Sonnet) using the captured files + interview answers. Conforms to schema below.

5. **Critique pass:** dispatch `codex-consultant` + `gemini-consultant` in parallel with `MODE: style-critique`. They flag missing categories, vague rules, contradictions. Apply findings.

6. **User approval via `AskUserQuestion`** with options: accept / edit-and-resave / re-critique / abandon.

7. **Write STYLE.md to repo root.** Log `style_init_complete`. Push-notify.

**Mode B: amend (`--amend`).**

1. **Refuse if STYLE.md does NOT exist.** Message: "no STYLE.md; run /z-style-init without --amend first".

2. **Scan recent archives via shared script:** `scripts/extract-dismissals.py <slug-dir> --max-runs 10 --global`. Result: `dismissed_signatures.json`. (Same script `/z-mr-review` uses — Gemini fix #9.)

3. **Cluster.** Group `signatures` by category + finding-text similarity. Cheap algorithm: Jaccard token-overlap ≥ 0.6 between `normalized_snippet` pairs, after dropping stopwords (same hardcoded list as agent procedure step 5). Discard clusters with <2 members.

4. **Propose amendments.** Dispatch Sonnet subagent: "Here are clusters of repeatedly-dismissed findings. Current STYLE.md is X. Propose new rules (with stable IDs in the next-free range per section) that would prevent these findings from being raised again." Returns proposed-rule patches.

5. **User reviews proposed rules** via `AskUserQuestion`, multi-select per cluster: add as-drafted / add with edits / reject. Approved rules are appended to the right STYLE.md sections (frontmatter `schema_version` unchanged).

6. **Log `style_amend_complete` with cluster counts.**

---

### `agents/mr-reviewer.md`

**Frontmatter:**
```yaml
---
name: mr-reviewer
description: Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to codex-reviewer).
tools: Bash, Read, Grep, Glob, Edit, Write, Agent
model: sonnet
---
```

**Input contract (orchestrator passes via prompt — ALWAYS a single .patch file, never polymorphic):**
- `slug`, `run_id`, `slug_dir`
- `base`, `base_sha` — base ref (e.g. `main`) and its resolved SHA. Agent may `git show <base_sha>:<path>` to read pre-change file context when verifying interface adherence.
- `diff_path` — abs path to a single `.patch` file (either the full diff or one chunk; agent does not branch on which).
- `style_path` — abs path to project STYLE.md (guaranteed to exist; orchestrator pre-checks).
- `dismissed_signatures_path` — abs path to `dismissed_signatures.json` written by `scripts/extract-dismissals.py`. Schema: `{signatures: [{file, category, normalized_snippet, prior_run_id}, ...]}`. Agent reads but does not recompute.
- `voices_available` — list (subset of `claude`, `codex`, `gemini`). Agent dispatches only available voices.
- `mode` — one of `full`, `per-chunk`, `abstraction-only`. Selects which categories to populate (full = all 5; per-chunk = all 5 minus abstraction; abstraction-only = only abstraction, cross-file aware).
- `chunk_meta` — null in single-pass / abstraction-only modes; `{index, total, manifest_path}` in per-chunk mode.
- `deep` — bool; if true and `mode != per-chunk`, the abstraction sub-pass is upgraded to Opus.

**Procedure:**

1. **Read inputs:** STYLE.md (full); diff (single `.patch` file at `diff_path`); `dismissed_signatures.json` (already structured by orchestrator).

2. **Determine active categories from `mode`:**
   - `mode=full` → all 5 categories.
   - `mode=per-chunk` → 4 categories (skip `abstraction` — handled by separate abstraction-only pass).
   - `mode=abstraction-only` → 1 category (`abstraction`), full whole-diff context, Grep/Glob mandatory.

3. **Voice dispatch (parallel `Agent()` calls in one message, only available voices):**
   - For each voice in `voices_available`, dispatch with **fixed structured output contract (Codex fix #6)**:
     ```
     Agent(subagent_type="codex-consultant", description="Codex Nitpicker",
       prompt="MODE: mr-review\nactive_categories: [<list>]\nSTYLE.md:\n<full>\n\nDIFF:\n<contents of diff_path>\n\nReturn findings as a fenced ```json block with this schema:
     {\"findings\": [{\"severity\": \"P0|P1|P2|P3|P4\", \"category\": \"<one of active>\", \"file\": \"<path>\", \"line_start\": <int>, \"line_end\": <int>, \"title\": \"<short>\", \"detail\": \"<prose>\", \"citation\": \"<STYLE.md rule ID or null>\"}]}
     NO correctness bugs (those belong to codex-reviewer)."
     )
     ```
   - Claude (the agent's own Sonnet) review runs in-line on the same inputs with the same JSON output contract.
   - **Parse failure handling:** if a voice returns malformed JSON (failed parse), log `mr_voice_failed {voice, reason: "malformed_json"}` and proceed with the other voices. Do not retry inline (cost guard).

4. **Abstraction tooling (Codex fix #10, Gemini fix #1):** when `category == abstraction` is active:
   - For each function/method/class introduced or modified in the diff, extract its symbol name via language-aware regex (e.g. Rust `fn (\w+)`, Python `def (\w+)`, TS `(function|const) (\w+)\s*=`).
   - Skip symbols on a hardcoded common-name suppression list: `format, parse, init, get, set, new, build, run, main, default, from, to, into, as, value, name, key, id, data, result, item, handle`.
   - For each remaining symbol: `Grep -n "\b<symbol>\b" --include="<lang glob>"` across the repo, excluding the diff's own files. Findings: "symbol `X` in diff (file:line) collides with existing `X` at <other-file:line>." Confidence threshold: cite only if the existing occurrence is also a definition (regex match on def/fn pattern), not just a call site.
   - In `mode=abstraction-only` AND `deep=true`: dispatch a sub-pass as Opus via `Agent(subagent_type="general-purpose", model="opus", ...)` over the (already-grep-narrowed) candidate pairs for deeper structural reasoning about whether the duplication is meaningful or coincidental.

5. **Merge findings within this agent invocation.**
   - Dedup by `(file, category, normalized_text)` signature (Gemini fix #2 — line-range dropped from signature; included in finding body only for display). Normalize: lowercase, collapse whitespace, strip leading/trailing punctuation.
   - Tag each finding with `voices: [<subset>]`.
   - **Consensus tier-bump:** if `len(voices) == len(voices_available)` AND `len(voices_available) >= 2`, promote one tier (P3→P2, P2→P1, P1→P0; P0 stays). If `len(voices) == 1` AND `len(voices_available) >= 2`, demote one tier (P3→P4, P2→P3, P1→P2; **P0 stays — never demote P0** per Gemini fix #3, Codex fix #4). Single-voice-available mode disables both bumps (no consensus signal available).
   - **Dismissal-pattern match:** signature = `(file, category, normalized_text)`. Jaccard token-overlap ≥ 0.6 between normalized_text and any signature in `dismissed_signatures.json`, after stopword removal (hardcoded list: `the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`). On match: append `[previously-dismissed-pattern]` to detail. **Severity action: P1-P4 demote one tier; P0 keeps severity (tag only).**

5. **Severity rubric (must be applied consistently):**
   - **P0** — would actively cause future bugs or maintenance pain (e.g. silent except-pass over a real failure mode, abstraction collapse).
   - **P1** — clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated comment scaffolding, missed-extraction of significant duplication).
   - **P2** — STYLE.md violation or noticeable idiom drift.
   - **P3** — minor hygiene (stale comments, naming oddities, redundant tests).
   - **P4** — taste-only nits.

6. **Hardcoded principles** (in agent prompt, independent of STYLE.md):
   - Assume correctness; do not raise correctness bugs (defer to codex-reviewer).
   - Every added line must justify its weight relative to existing abstractions, local style, and the behavioral surface it supports. Gratuitous diff growth is suspect; necessary growth is not.
   - When flagging abstraction, cite the duplicated existing symbol by file:line.

7. **Return findings to orchestrator (the orchestrator writes MR-REVIEW.md, not the agent).** Agent returns its findings list (JSON) + summary block. Orchestrator merges agent returns across all invocations (single-pass: 1 return; chunked: N+1 returns) and writes the final MR-REVIEW.md + archive snapshot.

8. **Return structured summary to orchestrator:**
   ```
   ## Summary
   STATUS: ok
   total_findings: N
   by_severity: P0=N P1=N P2=N P3=N P4=N
   by_category: defensive-bloat=N test-noise=N abstraction=N hygiene=N style-drift=N
   voices_succeeded: [claude, codex, gemini]
   voices_failed: []
   dismissal_pattern_matches: N
   ```

### MR-REVIEW.md format (TASKS.md-shape)

```markdown
---
artifact: mr-review
slug: <slug>
run_id: <RUN>
generated_at: <iso>
base: <git-ref>
base_sha: <sha>
diff_stat: <files-changed lines-added lines-removed>
style_md_revision: <git-sha-of-STYLE.md-at-review-time>
voices_available: [claude, codex, gemini]
voices_succeeded: [claude, codex, gemini]
total_findings: N
findings_index:
  - {id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs}
  - {id: T-MR-002, severity: P1, category: defensive-bloat, file: src/bar.rs}
  # ... one entry per finding; lets /z-debug and other consumers parse without scanning prose (Codex fix #10)
---

# MR Review — <slug>

Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=MR-REVIEW.md`.

## P0 — would cause future bugs

- [ ] T-MR-001. <one-line finding title>
  **File:** src/foo.rs:42-67
  **Category:** abstraction
  **Voices:** claude, codex, gemini
  **Citation:** STYLE.md: AB-003 (Reuse over duplication)
  **Finding:** This new `format_price()` duplicates `utils::display::price_str()` at src/utils/display.rs:88. Suggested fix: import and call the existing helper.
  **Acceptance criteria:**
  - Delete the new `format_price()` function in src/foo.rs.
  - Replace call sites with `utils::display::price_str(...)`.

## P1 — clear regression

- [ ] T-MR-002. ...

## P2 — style drift

...
```

The `T-MR-NNN` IDs are stable within a single run. Across runs, they're re-numbered (the archive snapshot keeps the historical record).

### STYLE.md schema

**Frontmatter:**
```yaml
---
schema_version: 1
source: capture | interview | ingest | natural-language | amend
source_files: [list of files Capture used]
repo: <repo name>
revision: <git-sha at init time>
generated_at: <iso>
---
```

**Required sections** (each populated by init flow; empty sections allowed but discouraged):

- `## Error handling` — rules `EH-NNN`
- `## Tests` — rules `T-NNN`
- `## Comments` — rules `C-NNN`
- `## Naming` — rules `N-NNN`
- `## Project-specific` — rules `P-NNN`

**Rule format:**

```markdown
### EH-001: <short rule title>
<one-paragraph rule prose>
Rationale: <one sentence>
```

Rule IDs are append-only and never reused. Reviewer cites by ID.

---

## Telemetry

Standard `phase_end` events. Plus:
- `mr_run_start` `{slug, run_id, base, diff_stat, deep}`
- `mr_run_end` `{slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`
- `mr_finding_emitted` (one per finding) `{slug, run_id, severity, category, voices_count, dismissal_match: bool}`
- `mr_style_missing` (if /z-mr-review refused due to no STYLE.md)
- `mr_voice_failed` `{voice, reason}`
- `style_init_complete` `{source, sections_populated, rule_count}`
- `style_amend_complete` `{clusters, rules_added}`

## Falsifiability thresholds (BRAINSTORM.md → SPEC)

Surface in docs/human/mr-reviewer.md:
- If >90% finding parity with `/z-audit --dimension=cleanliness`, fold into `/z-audit`.
- If >30% of findings are dismissed by users across a meaningful sample (≥10 runs), retire — reviewer is noise.

These are explicit retirement criteria; not enforced in code.

## Integration: `/z-debug` post-mortem hand-off

`/z-debug`'s post-mortem phase already produces preventative action items. We add an optional MR-review step there: after the fix diff is committed and the post-mortem is being authored, `/z-debug` offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If the user accepts, `/z-debug` invokes the same `mr-reviewer` agent with `slug = <debug-slug>` (the existing debug run's slug, so MR-REVIEW.md lands under that slug's dir alongside the post-mortem). Any P0/P1 findings get **automatically appended to the post-mortem's preventative-action list** as bullet items (cited back to MR-REVIEW.md by `T-MR-NNN` ID). P2-P4 stay in MR-REVIEW.md only.

Concretely:
- `commands/z-debug.md`'s post-mortem phase grows one new step (gated on `AskUserQuestion`): "Run MR-style quality review on the fix diff?"
- If yes: invoke `Agent(subagent_type="mr-reviewer", ...)` with the debug-run slug, base ref = pre-fix commit, deep = false.
- After the agent returns, parse `archive/<RUN>/MR-REVIEW.md` for P0/P1 findings (one-line title each), append them to the post-mortem's "Preventative actions" section as additional bullets.

This is a one-way hand-off — `mr-reviewer` itself is unchanged; the change lives in `z-debug.md`.

## Non-goals (v1)

- Global `~/.claude/STYLE.md` and `extends:` merge semantics (v2, D7).
- GitHub PR fetch via `gh pr diff` (v2, D8c).
- Auto-applying fixes (we write TASKS.md-shape; `/z-implement-all` applies).
- Finding correctness bugs (covered by codex-reviewer / `/z-review-all`).
- Bundling into `/z-review-all` as a phase (v2; prove signal first).
- Confidence-scoring beyond voice-count proxy.
- Per-finding cost reporting (subsumed by existing telemetry).

## DRY / KISS / SOLID self-check

- **DRY:** Reuses existing `codex-consultant` / `gemini-consultant` agents as CLI wrappers — no new CLI subprocess management. STYLE.md schema borrows the rule-ID pattern from docs/llm concept slugs. `/z-implement-all` consumes MR-REVIEW.md via existing `--tasks=<path>` mechanism (one flag, not a new command).
- **KISS:** No `/z-mr-triage` command — user deletes lines. No checkbox parsing. No multi-file diff routing beyond a token-threshold chunker. One agent (`mr-reviewer`), three commands (`/z-mr-review`, `/z-style-init`, `/z-style-init --amend`).
- **SOLID:** Single-responsibility — `mr-reviewer` reviews; `/z-style-init` authors style; `/z-style-init --amend` updates style. Open/closed — STYLE.md sections + rule IDs append-only, never break existing citations. Dependency inversion — `mr-reviewer` depends on `codex-consultant` / `gemini-consultant` interfaces, not on the CLIs directly.
