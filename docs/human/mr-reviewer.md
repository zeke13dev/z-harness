# MR Reviewer

> Last updated: 2026-05-23
> Covers source: commands/z-mr-review.md, agents/mr-reviewer.md, scripts/extract-dismissals.py

## What it does

`/z-mr-review` performs a code-quality review of the current branch diff against the project's `STYLE.md`. It is distinct from `/z-audit` and `/z-review-all`, which gate correctness; the MR reviewer assumes the code is correct and instead targets AI-shaped and human-shaped quality slop.

The review fans out to all available LLM voices (Claude Sonnet inline, plus the configured `consultant-primary` and `consultant-secondary` providers). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md` on survivors.

## When to use it

- After landing a feature branch and before merging: catch quality regressions before they compound.
- After a rapid prototyping sprint where you traded quality for speed.
- As an optional post-mortem step in `/z-debug`: the debug command can invoke `mr-reviewer` on the fix diff and automatically promote P0/P1 findings to the post-mortem's preventative-action list.

Run `/z-style-init` first if the project has no `STYLE.md`; `/z-mr-review` refuses to proceed without one (no `--no-style` escape).

## The five review categories

| Category | What it targets |
|---|---|
| `abstraction` | Duplicated logic, missed extractions, cross-file symbol collisions. |
| `defensive-bloat` | Guards against impossible states; over-long error-handling chains. |
| `test-noise` | Redundant, brittle, or dead test code introduced by the diff. |
| `hygiene` | Stale comments, cosmetic naming oddities, unnecessary logging. |
| `style-drift` | Violations of rules defined in the project's `STYLE.md`. |

## P0–P4 severity rubric

| Severity | Meaning |
|---|---|
| **P0** | Would actively cause future bugs or maintenance pain (e.g. silent except-pass, abstraction collapse). Findings at this tier are never demoted — not by low voice consensus, not by a dismissal match. |
| **P1** | Clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated scaffolding, significant missed extraction). |
| **P2** | STYLE.md violation or noticeable idiom drift. |
| **P3** | Minor hygiene (stale comments, naming oddities, redundant tests). |
| **P4** | Taste-only nits. |

P0–P2 are worth acting on. P3–P4 are informational. Delete freely.

## Multi-voice consensus and dismissal adjustment

Findings raised by all available voices are promoted one tier (P3 → P2, etc.). Findings raised by only one voice are demoted one tier (P3 → P4, etc.). P0 is exempt from both adjustments — it stays at P0 regardless of consensus.

Findings whose text signature matches a prior-run dismissal pattern get tagged `[previously-dismissed-pattern]` and are demoted one tier (P1 → P2, etc.). P0 findings that match a dismissal pattern are tagged but **not demoted**.

## Large-diff chunking

When the diff exceeds `Z_MR_DIFF_CHUNK_BYTES` (default 320 000 bytes, roughly 80K tokens), the orchestrator splits the diff per file and dispatches the `mr-reviewer` agent once per chunk. A final whole-diff abstraction-only pass catches cross-file duplication that per-chunk passes cannot see. The `--deep` flag upgrades that abstraction pass to Opus.

## Dismissal learning and `/z-style-init --amend`

Every run archives a snapshot of MR-REVIEW.md at `z-harness/<slug>/archive/<run-id>/MR-REVIEW.md`. The `scripts/extract-dismissals.py` utility compares consecutive run snapshots to identify findings the user deleted. When ≥ 3 findings in a run match prior dismissal patterns, the command suggests `/z-style-init --amend` to codify the pattern into STYLE.md so future reviews don't raise it again.

## Falsifiability thresholds (living criteria)

These thresholds determine when to retire or re-examine this reviewer. They are not enforced in code — they require a human decision.

- **Retire the category:** if a category's dismissal rate exceeds **30% over ≥ 10 runs**, the category is generating noise. Run `/z-stats` — it surfaces per-category dismissal rates and emits a warning when this threshold is crossed. Consider removing that category from active review or tightening its criteria.
- **Fold into `/z-audit`:** if the reviewer's findings achieve **>90% audit parity** with `/z-audit --dimension=cleanliness` on the same diffs, the two commands are redundant and `mr-reviewer` should be retired in favor of the audit pipeline.

## Telemetry events

| Event | When emitted |
|---|---|
| `mr_run_start` | Command setup complete, diff computed |
| `mr_run_end` | All findings written to MR-REVIEW.md |
| `mr_finding_emitted` | Once per finding (fields: severity, category, voices_count, dismissal_match) |
| `mr_finding_dismissed` | Once per dismissed signature on each subsequent run |
| `mr_style_missing` | Command refused: no STYLE.md found |
| `mr_voice_failed` | A consultant voice returned malformed JSON |
| `mr_all_voices_failed` | All voices failed; command exits nonzero |
| `mr_voices_degraded` | Only Claude is available; single-voice mode |

## Integration: `/z-debug` post-mortem hook

After committing a fix, `/z-debug`'s post-mortem phase offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If accepted, the `mr-reviewer` agent runs with the debug run's slug. P0 and P1 findings are automatically appended to the post-mortem's "Preventative actions" section as bullet items, cited by `T-MR-NNN` ID. P2–P4 findings stay in MR-REVIEW.md only. See `commands/z-debug.md` for the integration details.

## See also

- `docs/human/style-init.md` — how to create and amend the STYLE.md this command requires.
- `docs/human/STYLE-md-schema.md` — the full STYLE.md schema reference including rule ID format and a worked example.
