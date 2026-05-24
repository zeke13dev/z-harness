# Phase 3 — Decisions final (post-consult)

Codex and Gemini bundled-consult both returned. Synthesizing per the "one reason it might be wrong" rule before accepting any recommendation.

## D2 — Dispatch pattern → KEEP (b), AMEND for provenance

- Codex: (b) is fine BUT preserve raw per-model outputs tagged by model provenance — don't let synthesis hide disagreement.
- Gemini: reject (b), use (a) because nested CLI calls are fragile.

**One reason (b) might be wrong:** synthesis loses signal — user can't see when Claude/Codex/Gemini disagree on what counts as "defensive bloat", which is a hidden taste vote.

**Resolution:** stay with (b) — `mr-reviewer.md` (Sonnet) dispatches `codex-consultant` + `gemini-consultant` internally and produces the merged MR-REVIEW.md. **BUT** each finding in MR-REVIEW.md is tagged `[voices: claude,codex,gemini]` or a subset. When only 1 of 3 voices raised a finding, it gets demoted by one P-tier automatically (signal: only one judge cares). When all 3 raised it, it gets promoted by one tier (signal: rare consensus). Gemini's CLI-fragility concern is overruled because the existing consultant agents already wrap the CLIs — that subprocess management lives in `codex-consultant.md` / `gemini-consultant.md`, not in `mr-reviewer.md`. One layer of nesting, not three.

## D3 — Output format → AMEND to "delete-what-you-don't-want" TASKS.md-shape

**User correction over consult:** drop the separate triage step entirely. The reviewer writes ONE file that is already in TASKS.md shape. User deletes the lines they don't want. `/z-implement-all --tasks=MR-REVIEW.md` (flag name TBD) consumes what's left. No `/z-mr-triage` command. No checkbox parse step. The file's existence + remaining contents IS the triage.

Original (now-rejected) plan was async checkbox triage + a second parser command. The user's "just delete tasks you don't want" is materially simpler and matches how humans use file-based task lists. Dismissed findings simply aren't in the file (if the user later wants a "what did I previously dismiss" trail, that's what `archive/<RUN>/MR-REVIEW.md` is for — every run snapshots).

### Original consult input (kept for record)

- Codex: triage must be durable; dismissed findings must persist with status.
- Gemini: reject interactive prompting; use async markdown checkboxes.

Both pushed "durable + async". The user's "delete what you don't want" is even MORE async and even MORE durable — the file is the state, no parse step, no second tool. Codex's "what did I previously dismiss?" concern is answered by the per-run archive snapshot.

## D3 — OLD draft (superseded by above)

- Codex: triage must be durable; dismissed findings must persist with status.
- Gemini: reject interactive prompting; use async markdown checkboxes.

Both push the same direction. Gemini's UX is materially better than my "interactive AskUserQuestion per finding" plan.

**Resolution:** `/z-mr-review` writes `MR-REVIEW.md` with a markdown checkbox triage block per finding:

```markdown
### F-014 [P1] [abstraction] [voices: codex,gemini]
**File:** src/foo.rs:42-67
**Finding:** This new `format_price()` duplicates `utils::display::price_str()` (src/utils/display.rs:88).
**Triage:** (check exactly one)
- [ ] accept
- [ ] dismiss — reason: ___
- [ ] defer
```

User edits the file. Then `/z-mr-triage` (a second command, cheap, no LLM) parses the file and writes accepted findings into `MR-TASKS.md`. **The file IS the state** — survives across sessions, replayable, CI-friendly, no ephemeral chat history. Dismissed findings stay in MR-REVIEW.md with `(dismissed)` annotation so future reviews can spot when the same nit comes back.

## D4 — Capture mechanism → INVERT to heuristic-prefilter-first

- Codex: heuristic prefilter FIRST (exclude node_modules, generated, migrations), then Sonnet ranks filtered candidates.
- Gemini: agree with (b)+(a).

**One reason Sonnet-first might be wrong:** burns tokens scanning vendored/generated/migration files that are guaranteed to be noise.

**Resolution:** adopt Codex's inversion. Step 1: build a candidate list from `git ls-files` excluding (a) gitignored paths, (b) hardcoded exclusion list (`node_modules/`, `vendor/`, `dist/`, `*.pb.go`, `*_pb2.py`, `migrations/`, `__generated__/`, lockfiles, minified files), (c) files smaller than 50 lines or larger than 800 lines. Step 2: Sonnet ranks the filtered set by "idiomatic-ness" — picks top 5. Step 3: Sonnet reads those 5 + drafts STYLE.md from them.

## D5 — STYLE.md schema → AMEND with stable rule IDs

- Codex: add stable rule IDs (`EH-001` etc.) so citations don't rot when prose changes.
- Gemini: agree as drafted.

**One reason free-prose-cited-by-section might be wrong:** prose shifts, citations rot. Codex is right.

**Resolution:** each rule within each section gets a stable ID. Format:

```markdown
## Error handling

### EH-001: No bare except
External-API calls may catch IOError. Internal call sites must let exceptions propagate.
Rationale: defensive try/catch around internal calls hides bugs in test runs.

### EH-002: ...
```

Frontmatter also gets `schema_version: 1`, `source: capture|interview|ingest|natural-language`, `source_files: [list of files Capture used]`, `repo: <name>`, `revision: <git-sha-at-init>`. Reviewer cites `STYLE.md: EH-001` — stable forever.

## D9 — Slug coupling → KEEP (b), HARDEN edge cases

- Codex: deterministic normalization, decide overwrite-vs-timestamp behavior.
- Gemini: guard detached HEAD / main.

**Resolution:** (b) with:
- Normalize: `git branch --show-current` → kebab-case (replace `/` with `-`, lowercase, strip non-alnum-dash).
- Detached HEAD: refuse, ask user to pass `--slug=<name>` explicitly.
- Main / master / trunk: refuse without `--force-on-trunk` flag (signals: you almost certainly want to review a feature branch, not trunk).
- Rerun on same slug: archive existing `MR-REVIEW.md` to `archive/<RUN>/MR-REVIEW.md.previous-<N>` then overwrite. Same pattern as `/z-brainstorm`.

## D11 — Model tiering → SOFTEN, default Sonnet + `--deep` for Opus

- Codex: gate Opus conditionally (diff size, Sonnet uncertainty, explicit `--deep` flag). Soften the "net diff length is suspect" principle.
- Gemini: reject Opus entirely; abstraction is a RAG/search problem, equip Sonnet with grep tools.

**One reason hardcoded-Opus-for-abstraction might be wrong:** abstraction-spotting is primarily a search problem (does this pattern already exist somewhere?), which Sonnet equipped with Grep/Glob handles fine. Opus reasoning earns its cost only on genuinely structural changes (new layer boundary, framework reshape) — that's the `--deep` case.

**Resolution:**
- **Default:** Sonnet for all five categories. Equip the abstraction sub-pass with mandatory `Grep` + `Glob` use ("before flagging a duplication, grep for the symbol or pattern; cite the existing occurrence by file:line"). This is RAG, not reasoning.
- **`--deep` flag:** upgrades the abstraction sub-pass to Opus. User opts in when they know the change is structurally significant. Cost: ~3x abstraction-pass cost, opt-in only.
- **Hardcoded principle softened (per Codex):** "Every added line must justify its weight relative to existing abstractions, local style, and the behavioral surface it supports. Net diff growth is not inherently suspect — gratuitous diff growth is." This is gentler but preserves the user's intent.

## D12 (NEW, from Gemini) — Diff chunking for large PRs

**Decision:** What happens when the cumulative diff exceeds a Nitpicker voice's working context?

**Resolution:** Threshold-based chunking. Compute `diff_tokens = wc -c on diff / 4`. If `diff_tokens < 80_000`, send the whole diff to each voice. Otherwise chunk per touched file (per-file independent review) and merge findings, deduping by `file:line` signature. Threshold configurable via `Z_MR_DIFF_CHUNK_TOKENS` env.

## D13 (NEW, from Gemini) — Feedback loop into STYLE.md

**Decision:** When a user dismisses a finding, do we learn?

**Resolution:** **v2 / deferred.** v1 keeps dismissed findings annotated in MR-REVIEW.md, but does not auto-amend STYLE.md. Re-running `/z-mr-review` on a similar diff WILL re-flag the same finding. v2 idea: `/z-mr-review --learn-from=<prior MR-REVIEW.md>` reads prior dismissals and proposes STYLE.md amendments via `AskUserQuestion`. Logged as future work in SPEC.md non-goals.

## D14 (NEW, Codex's "missing 9") — Codex/Gemini CLI unavailable

**Decision:** What does `mr-reviewer` do if `codex` or `gemini` CLI is not installed?

**Resolution:** Run with the available voices; tag findings accordingly. If all three voices fail (Claude can always run), the agent errors out with a clear message. Same failure-degradation policy as `/z-brainstorm`.

## Non-decisions (Codex's other "missing 9") — folded

- **Severity semantics:** P0/P1/P2/P3/P4 rubric already drafted in BRAINSTORM.md User-choice section. Re-paste into SPEC.md.
- **Confidence scoring:** subsumed by voice-count (1/3 vs 3/3 voices = confidence proxy).
- **Raw output retention:** the voices' raw returns are stored under `archive/<RUN>/transcripts/`.
- **Review scope (staged vs branch vs last commit):** D8 already settled as `git diff <base>...HEAD`, `--base` overrideable.
- **Generated/vendor exclusion rules:** lives in the agent prompt; same hardcoded list as D4 step 1.
- **Style precedence hierarchy:** D7 deferred to v2 (project STYLE.md only).
- **Cost/privacy controls:** out of scope v1 — same as existing codex/gemini consultants.

---

## Final decision matrix

| ID | Decision | Final call (after consult) |
|----|----------|----------------------------|
| D1 | File layout | flat: `commands/z-mr-review.md`, `commands/z-style-init.md`, `agents/mr-reviewer.md` (no triage command) |
| D2 | Dispatch | single `mr-reviewer` (Sonnet) fans out to codex/gemini consultants, **tags findings by voice**, demote 1/3-voice findings by one tier, promote 3/3 by one tier |
| D3 | Output | single `MR-REVIEW.md` in TASKS.md shape (`- [ ] T-MR-NNN title` blocks); user deletes lines they don't want; `/z-implement-all --tasks=MR-REVIEW.md` consumes survivors; archive snapshot preserves the full pre-deletion list per run |
| D4 | Capture | **heuristic prefilter first** (exclude generated/vendored/oversized), then Sonnet ranks filtered set, picks top 5 idiomatic |
| D5 | Schema | required section headers + **stable rule IDs** (`EH-001`) + frontmatter (`schema_version`, `source`, `source_files`, `repo`, `revision`); reviewer cites by ID |
| D6 | Categories fixed | yes, 5 categories hardcoded |
| D7 | Global STYLE.md | v2 deferred |
| D8 | Diff scope | `git diff <base>...HEAD`, `--base` override, `--include-untracked` flag |
| D9 | Slug | git branch (normalized); refuse detached HEAD; refuse trunk without `--force-on-trunk`; rerun = archive + overwrite |
| D10 | Telemetry | standard `phase_end` + `mr_finding_emitted` + `mr_finding_triaged` + `mr_style_missing` |
| D11 | Model tier | Sonnet default for all categories, abstraction pass uses **Grep + Glob mandatory**; `--deep` flag upgrades abstraction to Opus |
| D12 | Diff chunking | per-file chunk if diff > 80k tokens; env-tunable |
| D13 | Feedback loop | v2 deferred |
| D14 | CLI unavailable | degrade gracefully; tag findings by available voices |

## Shortcuts being taken (require explicit approval in Phase 5)

1. **Global STYLE.md (D7) deferred to v2.** Robust alternative: implement `extends:` frontmatter now. Cost of shortcut: users with cross-project style preferences re-author the same rules per repo.
2. **Feedback loop into STYLE.md (D13) deferred to v2.** Robust alternative: same-PR `--learn-from` flow now. Cost: users re-dismiss the same nits across PRs until they manually amend STYLE.md.
3. **PR-fetch from GitHub (D8 option c) deferred to v2.** Robust alternative: add `gh pr diff <num>` support now. Cost: can't review someone else's PR without checking out the branch locally.
