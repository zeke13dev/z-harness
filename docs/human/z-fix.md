# z-fix

> Last updated: 2026-06-05
> Covers source: commands/z-fix.md

## Overview

`/z-fix` is a fast, lightweight bug-fix command for the case where you already have a diagnosis. You bring the hypothesis; the command validates it against a parallel two-LLM consult, implements inline, and runs a mandatory Codex review — all targeting roughly 15 minutes wall time end-to-end. It is explicitly not for situations where the root cause is unclear. If you cannot name a concrete hypothesis before Phase 0 completes, the command exits and recommends `/z-debug` instead.

`/z-fix` produces a single artifact: `FIX.md`. There is no SPEC.md, PLAN.md, TASKS.md, PROBLEM.md, or EVIDENCE.md — the problem statement, evidence, root cause, approach, and acceptance criteria all live as sections within FIX.md. The plan directory is resolved via `scripts/plan-path.sh` and lives under the harness base directory.

## Key entry points

- `commands/z-fix.md:1` — `/z-fix` — top-level slash command definition; read this for the full phase-by-phase procedure
- `commands/z-fix.md:24` — Setup — slug derivation (two-step: `plan-path.sh all_plan_slugs` collision check then resolver gate with halt branch), run-id, directory creation, version stamp, `fix_run_start` telemetry
- `commands/z-fix.md:79` — auto-bail thresholds — >5 files / >2 non-obvious decisions / cross-module triggers `escalation.md` + `/z-plan`
- `commands/z-fix.md:90` — Phase 0 — non-skippable wrong-tool gate via `AskUserQuestion`
- `commands/z-fix.md:105` — Phase 1 — problem capture, `doc-fetcher` dispatch, auto-bail threshold check
- `commands/z-fix.md:138` — Phase 2 — single key decision; bail to `/z-plan` if >2 non-obvious decisions
- `commands/z-fix.md:144` — Phase 3 — bundled `light-fix` consult (Gemini + Codex in parallel, cause-explains-symptoms framing)
- `commands/z-fix.md:164` — Phase 4 — synthesize, one-reason-wrong check, cross-LLM disagreement surface
- `commands/z-fix.md:173` — Phase 5 — approve/modify/abandon gate; shortcuts need separate explicit approval
- `commands/z-fix.md:187` — Phase 6 — write FIX.md (single artifact, status=approved not yet shipped)
- `commands/z-fix.md:237` — Phase 7 — inline implementation by orchestrator; no implementer subagent; hard limit >7 files
- `commands/z-fix.md:259` — Phase 8 — Codex review (non-negotiable); optional advisory persona reviewer in parallel when `personas.review_eval` ON; retry once on blockers; `REVIEW_CYCLES` counter
- `commands/z-fix.md:289` — Phase 9 — optional post-mortem; auto-suggested if `REVIEW_CYCLES > 1`
- `commands/z-fix.md:334` — Phase 10 — finalize: FIX.md status=shipped, `fix_run_end` log, `/z-maintain-docs` hint
- `commands/z-fix.md:358` — Git history-rewrite safety — doctrine for `git reset`/`amend`/`rebase` on upstream-tracking branches

## How it interacts with others

- `agents` — spawns `consultant-primary` (Gemini) and `consultant-secondary` (Codex) in parallel at Phase 3; spawns `reviewer` (Codex) at Phase 8; optionally spawns an advisory persona reviewer in parallel at Phase 8 when `personas.review_eval` is ON
- `commands` — exits to `/z-debug` when root cause is unknown; escalates to `/z-plan` when auto-bail thresholds are exceeded; suggests `/z-maintain-docs --audit` at finalize if docs were touched
- `scripts` — uses `log-event.sh` for `fix_run_start` / `fix_run_end` / `fix_halt` telemetry; uses `plan-path.sh all_plan_slugs` for collision detection and `plan-path.sh resolve_plan_path` for directory resolution; uses `version.sh` for version stamp; uses `config.py resolve-question` for `workflow.slug_confirm` resolver
- `config` — notification policy is read from `docs/human/config.md` (`notify.level` key); `PushNotification` calls at Phase 5 and Phase 10 are gated on this value; `workflow.slug_confirm` preference is resolved via `config.py`; `personas.review_eval` controls the advisory eval-reviewer arm at Phase 8

## Notification policy

Push notifications are sent at two points: Phase 5 (decision ready for review) and Phase 10 (fix complete). Both are gated on the `notify.level` key in the harness config — if the level is `off`, no `PushNotification` calls are made. See [docs/human/config.md](docs/human/config.md) for the full config reference, including how to set `notify.level` per-repo or globally.

## Slug derivation — two-step pattern

Setup step 1 uses a split safety+preference pattern:

1. **Unconditional collision check** — calls `bash scripts/plan-path.sh all_plan_slugs` to detect matching slugs across both new and legacy plan layouts. If a collision is found, prompt via `AskUserQuestion` to confirm or choose a different slug. This check runs regardless of any resolver outcome and cannot be bypassed.
2. **Soft non-obvious-slug confirmation gate** (only after collision check passes) — calls `python3 scripts/config.py resolve-question workflow.slug_confirm`, which returns `skip`, `prefill`, `ask`, or `halt`. On `skip`, the derived slug is accepted silently. On `prefill`, the derived slug is pre-selected as the recommended option. On `ask`, the user is prompted normally. If `$SOURCE == "conflict"`, a conflict header is added to the question and a write-back offer is made after the user answers. On `halt`, the command emits a `fix_halt` event and exits cleanly without invoking `AskUserQuestion` — intended for unattended/overnight automation contexts where interactive questions are prohibited.

The invariant: the collision check is a hard prerequisite. The resolver only governs the soft confirmation gate.

## Auto-bail thresholds

At any phase, if any of the following are found, the command stops and writes `escalation.md` then recommends `/z-plan`:

- More than 5 candidate files need editing.
- More than 2 non-obvious decisions (new dep, public API change, algorithm with materially different tradeoffs, persistence change).
- Cross-module or cross-crate impact (fix touches multiple modules, public APIs, wire formats, or schemas).
- User says "this might be bigger than I thought."

If scope growth is discovered mid-implementation (Phase 7), the halt is immediate and non-negotiable — the orchestrator does NOT offer to continue or spawn a subagent. Hard limit: touching >7 files inline triggers halt regardless of threshold checks.

## Phase 8 — Codex review and advisory eval-reviewer

Phase 8 always runs the base Codex reviewer. When `personas.review_eval` is ON (default ON), an advisory persona reviewer also runs in parallel using `reviewer_participant=random_arm`. The advisory arm:

- Is logged for telemetry only.
- Never changes the pass/fail outcome.
- Never triggers a retry.

Only the base Codex reviewer determines whether Phase 8 passes or retries. The advisory arm is purely an observational instrument for evaluating review persona diversity.

## When to pick `/z-fix` vs `/z-debug`

| Signal | Pick |
|---|---|
| You can state a hypothesis in one sentence. | `/z-fix` |
| You cannot name what's causing the symptom. | `/z-debug` |
| The fix touches 1-5 files in one module. | `/z-fix` |
| The fix may involve multiple modules or public APIs — root cause unclear. | `/z-debug` |
| The fix scope is confirmed too large (cross-module impact, >5 files). | `/z-plan` |
| You want a fast loop — 15 min target. | `/z-fix` |
| You want adversarial hypothesis generation and Bayesian elimination. | `/z-debug` |
| A previous `/z-debug` run identified the root cause. | `/z-fix` to implement the fix. |

If you are unsure which to pick, start with `/z-fix` Phase 0. The wrong-tool gate will redirect you if you cannot name a hypothesis.

## Edge cases / gotchas

- **Phase 0 is non-skippable even if an argument is passed.** A symptom description alone is not a hypothesis. The gate fires regardless.
- **The `light-fix` consult is framed around "does this cause explain all symptoms?" — not "what's the best fix?"** This framing is intentional; accepting a hypothesis that does not explain all symptoms is the most common /z-fix failure mode.
- **Cross-LLM disagreement must be surfaced to the user.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does not explain all symptoms — the orchestrator does not silently pick one side.
- **Shortcuts require explicit separate approval at Phase 5.** If either consultant recommends a shortcut over the robust long-lasting solution, the orchestrator marks it and gets separate user confirmation. Default is the robust solution.
- **Codex review is non-negotiable.** Fix mode cuts planning overhead, not correctness guarantees.
- **Advisory eval-reviewer at Phase 8 is telemetry-only.** It runs in parallel with the Codex reviewer when `personas.review_eval` is ON (default). Its verdict never blocks or retries the fix. Only the base Codex reviewer outcome matters for pass/fail.
- **`/z-mr-review` is not auto-triggered.** If a merge-request review is needed post-fix, run it separately.
- **The `REVIEW_CYCLES` counter drives post-mortem defaults.** `<= 1` cycle defaults to skip; `> 1` cycles defaults to suggest post-mortem.
- **Collision check uses `plan-path.sh all_plan_slugs`, not a simple directory listing.** This scans both new and legacy plan layouts. Never overwrite an existing plan directory without asking the user.
- **doc-fetcher is dispatched at Phase 1 only when `docs/llm/INDEX.json` exists.** In its absence, the orchestrator reads files directly; it never spawns the `Explore` subagent (too expensive for fix mode).
- **Notification calls are gated on `notify.level` from `docs/human/config.md`.** Setting `notify.level = off` suppresses all `PushNotification` calls; the env var `Z_HARNESS_NOTIFY` is no longer the control point.
- **The `halt` resolver result exits cleanly without asking any question.** When `workflow.slug_confirm` resolves to `halt` (e.g. a `no_ask_halt` rule fires in an overnight automation context), the command logs a `fix_halt` event and exits with code 0. It does not prompt, does not proceed to slug confirmation, and does not run any further phases. This is distinct from both `skip` (which silently continues) and error conditions (which fall through to `ask`).
- **Git history-rewrite safety doctrine applies.** Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream, run `git branch -r --contains <sha>` for each commit being rewritten. If the upstream ref appears, STOP — recommend rebase or new-commit instead. Force-push to main requires explicit per-incident user authorization with the list of overwritten commits and a content-equivalence demonstration.

## Examples

```
/z-fix "Login returns 403 after session token refresh — hypothesis: SameSite attribute is hardcoded to Strict on refresh response, blocking the subsequent browser request"
```

At Phase 0 the command confirms you have a hypothesis. If you typed only a symptom with no hypothesis, Phase 0 asks you to provide one or redirects to `/z-debug`.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-fix.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## See also

- `commands/z-fix.md` — full phase-by-phase procedure
- `docs/human/commands.md` — index of all slash commands
- `docs/human/config.md` — notification policy, workflow.slug_confirm, personas.review_eval, and other harness config keys
- `docs/human/z-debug.md` — the hypothesis-generation counterpart
