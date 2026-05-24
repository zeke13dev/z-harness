**D2: Dispatch Pattern**

Recommend **(b), but tighten the contract**.

The risk is not orchestration cleanliness; it is hiding too much behavior inside `mr-reviewer.md`. If the Sonnet agent fans out, dedups, ranks, and summarizes, the orchestrator loses observability into disagreements between models. That matters because this reviewer is explicitly subjective code-quality judgment.

Required guardrails:

- Preserve raw per-model outputs as an appendix or sidecar, e.g. `MR-REVIEW.raw/claude.md`, `codex.md`, `gemini.md`.
- Require consolidated findings to include provenance: `reported_by: [claude, codex]`.
- Treat single-model findings as lower confidence unless severity is obvious.
- Make the mr-reviewer agent responsible for synthesis, not silent deletion.

User is right that (b) is cleaner, but wrong if "one consolidated output" means the raw disagreement disappears. You want a clean user surface, not an opaque pipeline.

D11 interacts here: if Opus owns abstraction, its findings should be provenance-tagged separately because it is using a different scope and model tier.

**D3: Output Format And TASKS Handoff**

Recommend **separate `MR-TASKS.md`**, but the interactive triage needs a durable audit trail.

The main missed consideration is deferred findings. If the user triages inline, dismissed/deferred items should not vanish into chat history. `MR-REVIEW.md` should retain every finding with status:

```yaml
status: accepted | dismissed | deferred
triaged_at:
triage_note:
```

Then `MR-TASKS.md` is generated only from accepted findings.

Also be careful with `--tasks=MR-TASKS.md`: `/z-implement-all` must know whether paths are relative to cwd, plan slug dir, or repo root. Ambiguity here will cause the first annoying failure.

Suggested shape:

- `MR-REVIEW.md`: all findings, grouped P0-P4, with triage status.
- `MR-TASKS.md`: accepted remediation tasks only.
- `MR-TASKS.md` includes backlink IDs to `MR-REVIEW.md`, not duplicated full rationale.

User is right not to append to normal `TASKS.md`.

**D4: STYLE.md Capture Mechanism**

Recommend **(b) with heuristic prefilter**, not pure subagent scan.

The user's call says Sonnet scans candidate files, with heuristic fallback. Better: heuristic generates candidates, Sonnet selects and explains. Otherwise the agent may waste context on noisy files, generated files, tests, vendored code, migrations, snapshots, or old abandoned modules.

Missed considerations:

- Need exclude rules: `node_modules`, `dist`, generated files, snapshots, lockfiles, migrations, vendored code.
- Need language/framework stratification. One idiomatic backend file should not define frontend style.
- Need recency guard. Low-churn can mean stable, or dead.
- Need user override after capture. STYLE init should show source files and allow edits.

Recommended flow:

1. Heuristic selects candidate pool.
2. Sonnet picks representative files by category.
3. Generate `STYLE.md`.
4. Record source files in frontmatter.
5. Let user confirm or amend.

**D5: STYLE.md Schema**

Recommend **(b), but add stable rule IDs**.

Required headers are a good compromise. The missed piece is citation stability. "Error handling §2" is fragile if prose changes. Use IDs:

```md
## Error handling

- EH-001: Prefer returning domain errors over catch-all wrappers.
- EH-002: Do not add defensive null checks after validated boundaries.
```

Frontmatter should include more than `generated_at` and `source`:

```yaml
generated_at:
source:
source_files:
repo:
revision:
schema_version:
```

The schema should also distinguish:

- observed convention
- explicit user preference
- inferred rule with low confidence

Otherwise the reviewer will over-enforce accidental patterns.

**D9: Slug Coupling**

Recommend **(b), with normalization and collision handling**.

Branch-name default is pragmatic, but branch names are often terrible filesystem slugs:

- `feature/foo/bar`
- `zeke/mr-review`
- `fix#123`
- detached HEAD
- dirty worktrees shared across branches
- multiple reviews on same branch

You need deterministic slug normalization plus timestamp or review ID when needed.

Suggested behavior:

- `--slug` wins.
- Else active plan slug if detectable and unambiguous.
- Else sanitized branch name.
- If branch unavailable: `mr-review-YYYYMMDD-HHMM`.
- If target dir exists, append timestamp or write a new review under that slug.

Also decide whether rerunning `/z-mr-review` overwrites, appends, or creates `MR-REVIEW-2.md`. I would create timestamped review runs and optionally update `MR-REVIEW.md` as latest.

**D11: Model Tiering**

Opus only for abstraction is probably **overkill as a default**, but useful as an escalation path.

Abstraction findings are expensive because they need repo-wide context, not necessarily because they need the strongest model every time. Sonnet plus good retrieval may catch most duplication and dead-code issues. Opus should trigger when:

- diff size exceeds threshold
- new abstraction/framework layer is introduced
- similar symbols are found by grep/AST search
- Sonnet reports uncertainty
- user passes `--deep`

Hardcoding "net positive diff length is suspect" is too blunt. It will bias against legitimate feature work and test additions. Better principle:

> Added code must carry its weight relative to existing abstractions, local style, and the behavioral surface it supports.

Use Opus for "deep abstraction review," not every abstraction category pass.

**Missing Decisions**

You still need decisions for:

- Severity semantics: exact meaning of P0-P4 for non-blocking quality findings.
- Confidence scoring: how to handle subjective or single-model findings.
- Raw output retention: especially important with multi-LLM synthesis.
- Review scope: staged diff, branch diff against main, last commit, uncommitted changes, or explicit range.
- Generated/vendor exclusions.
- Style precedence: repo `STYLE.md` vs captured style vs language norms vs reviewer judgment.
- Re-review behavior: overwrite, append, supersede, or compare against prior MR review.
- Privacy/cost controls for sending repo context to external CLIs.
- Failure mode: what happens if Codex or Gemini CLI is unavailable.

Overall: the chosen direction is sound, but the biggest shortcut is treating synthesis as equivalent to truth. Keep raw model evidence, make triage durable, and make style rules citeable by stable IDs.
