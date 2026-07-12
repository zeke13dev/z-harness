# z-fix

> Last updated: 2026-07-11
> Covers source: skills/z-fix/SKILL.md

## Overview

`/z-fix` is a fast, lightweight bug-fix command for the case where you already have a diagnosis. You bring the hypothesis; the command validates it against a parallel two-LLM consult, implements inline, and runs a mandatory Codex review — all targeting roughly 15 minutes wall time end-to-end. It is explicitly not for situations where the root cause is unclear. If you cannot name a concrete hypothesis before Phase 0 completes, the command exits and recommends `/z-debug` instead.

`/z-fix` produces a single artifact: `FIX.md`. There is no SPEC.md, PLAN.md, TASKS.md, PROBLEM.md, or EVIDENCE.md — the problem statement, evidence, root cause, approach, and acceptance criteria all live as sections within FIX.md. The plan directory is resolved via `scripts/plan-path.sh`. As of the skill-overhaul-phase1 rewrite, `/z-fix` adopts the same delegated lifecycle ceremony as the other write commands: Setup's single `scripts/z-preflight.sh` call owns resolve/session-id/RUN-stamp/claim/register/run-brief-init/run_start/kernel-resolve in one fixed-order call, and both Phase 10 finalize and the shared halt path delegate teardown (claim release, deregister, generic `run_end`) to `scripts/z-teardown.sh`. Previously this ceremony did not exist in `/z-fix` at all; it now matches the pattern used by `/z-plan` and other registered commands.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-fix/SKILL.md:1` — `/z-fix` — top-level slash command definition; read this for the full phase-by-phase procedure
- `skills/z-fix/SKILL.md:22` — Setup — slug derivation (two-step: unconditional collision check then resolver gate with skip/prefill/ask/halt), single delegated `z-preflight.sh` preflight ceremony (claim, register, run-brief init, kernel-resolve), `fix_run_start` telemetry
- `skills/z-fix/SKILL.md:61` — Setup step 2 — `scripts/z-preflight.sh` single call owning resolve/session-id/RUN-stamp/claim/register/run-brief-init/run_start/kernel-resolve, in that fixed order; `/z-fix` claims (WRITE command, no `--no-claim`)
- `skills/z-fix/SKILL.md:78` — Setup step 2 — standard contention/corrupt-lock/register-failure menu (z-fix's deviations from the canonical `/z-plan` writer instance)
- `skills/z-fix/SKILL.md:100` — Auto-bail thresholds — >5 files / >2 non-obvious decisions / cross-module triggers `escalation.md` + `/z-plan`
- `skills/z-fix/SKILL.md:111` — Phase 0 — non-skippable wrong-tool gate; exits to `/z-debug` if no hypothesis
- `skills/z-fix/SKILL.md:126` — Phase 1 — problem capture, `doc-fetcher` dispatch, auto-bail threshold check
- `skills/z-fix/SKILL.md:159` — Phase 2 — single key decision; bail to `/z-plan` if >2 non-obvious decisions
- `skills/z-fix/SKILL.md:165` — Phase 3 — bundled `light-fix` consult (Gemini + Codex in parallel, cause-explains-symptoms framing); injects `kernel_path` line into both prompts when `KERNEL_PATH` is non-empty
- `skills/z-fix/SKILL.md:185` — Phase 4 — synthesize, one-reason-wrong check, cross-LLM disagreement surface
- `skills/z-fix/SKILL.md:194` — Phase 5 — approve/modify/abandon gate (conversational prose, not AskUserQuestion popup); shortcuts need separate explicit approval
- `skills/z-fix/SKILL.md:208` — Phase 6 — write FIX.md (single artifact, status=approved not yet shipped)
- `skills/z-fix/SKILL.md:258` — Phase 7 — inline implementation by orchestrator; no implementer subagent; hard limit >7 files
- `skills/z-fix/SKILL.md:278` — Phase 8 — Codex review (non-negotiable, sole gate); retry once on blockers; `REVIEW_CYCLES` counter
- `skills/z-fix/SKILL.md:308` — Phase 9 — optional post-mortem; auto-suggested if `REVIEW_CYCLES > 1`
- `skills/z-fix/SKILL.md:353` — Phase 10 — finalize: FIX.md status=shipped, Run Brief finalize (fragment include), `fix_run_end` log, delegated `scripts/z-teardown.sh` call, `/z-maintain-docs` hint
- `skills/z-fix/SKILL.md:386` — Run Brief — halt finalize — shared block for all terminal halts after Run Brief init; delegates teardown to `scripts/z-teardown.sh --status aborted`
- `skills/z-fix/SKILL.md:425` — Git history-rewrite safety — doctrine for `git reset`/`amend`/`rebase` on upstream-tracking branches
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `agents` — spawns `consultant-primary` (Gemini) and `consultant-secondary` (Codex) in parallel at Phase 3 (both may carry a `kernel_path` line when `KERNEL_PATH` is resolved); spawns `reviewer` (Codex) as the sole review gate at Phase 8
- `commands` — exits to `/z-debug` when root cause is unknown; escalates to `/z-plan` when auto-bail thresholds are exceeded; suggests `/z-maintain-docs` at finalize if docs were touched
- `scripts` — uses `z-preflight.sh` (Setup step 2) for the single delegated resolve/session/claim/register/run-brief-init/run_start/kernel-resolve call; uses `z-teardown.sh` at Phase 10 finalize and at Run Brief halt finalize to release the claim, deregister, and emit the generic `run_end`; uses `log-event.sh` for domain-specific `fix_run_start` / `fix_run_end` / `fix_halt` telemetry; uses `plan-path.sh` for slug-collision detection; uses `version.sh` for the version stamp; uses `config.py resolve-question` for the `workflow.slug_confirm` resolver; uses `run-brief.sh` for `set-section` calls (outcome/next)
- `config` — notification policy is read from `docs/human/config.md` (`notify.level` key); `PushNotification` calls at Phase 5 and Phase 10 are gated on this value; `workflow.slug_confirm` preference is resolved via `config.py`
- `run-brief` — Run Brief is initialised as part of the Setup step 2 `z-preflight.sh` call (profile=full, artifact=FIX.md) and finalised at Phase 10 via the shared `_fragments/run-brief-finalize.md` include; every terminal halt path after preflight succeeds calls the "Run Brief — halt finalize" block before logging `fix_run_end`

## Delegated lifecycle ceremony (new)

Setup step 2 replaces what was previously ad hoc or absent ceremony with a single call to `scripts/z-preflight.sh`, which owns — in this fixed order — resolve, session-id, RUN-stamp, claim, register, run-brief-init, run_start, and kernel-resolve. `/z-fix` is a WRITE command, so it claims by default (no `--no-claim`). The script's exit code must be captured **before** the `eval` of its stdout — reading `$?` after `eval` loses the script's exit-code contract.

On success, `RUN`, `Z_HARNESS_PLAN_DIR`, `CURRENT_ARCHIVE_DIR`, `Z_HARNESS_SESSION_ID`, `CLAIM_HELD`, `REG_RC`, and `KERNEL_PATH` are exported. When `KERNEL_PATH` is non-empty, a `kernel_path: <KERNEL_PATH>` line is injected into both Phase 3 consultant prompts; when empty, the line is omitted and each agent falls back to its own static self-resolution.

The **standard contention/corrupt-lock/register-failure menu** is documented once in the `z-preflight.sh` header, with `/z-plan` Setup step 2 as the canonical writer instance; `/z-fix`'s Setup step 2 documents only its deviations (SKILL-STYLE.md §2):

- **Contention** (`PREFLIGHT_RC==10`, nothing created) — `AskUserQuestion`: proceed anyway (re-run with `--no-claim`, log `fix_claim_override`) / abort / use a new slug (one re-derive, loop-guarded).
- **Corrupt lock** (`PREFLIGHT_RC==11`) — same shape, with a manual-cleanup hint; `AskUserQuestion`: abort (default) / proceed uncoordinated (log `fix_claim_corrupt_proceed`).
- **Register failure** (`REG_RC != 0` on `PREFLIGHT_RC==0`) — graduated, not a hard stop; `RUN`/`Z_HARNESS_PLAN_DIR`/run-brief already exist; `AskUserQuestion`: proceed without coordination / abort (runs Run Brief halt finalize with reason `active-plan registry register failed`, status `escalated`).

**Pre-preflight halts are different from post-preflight halts.** If `workflow.slug_confirm` resolves to `halt` in Setup step 1 (before `z-preflight.sh` has run), nothing is registered yet — the command logs `fix_halt` and does a plain `exit 0`. It does **not** call `scripts/z-teardown.sh` or the "Run Brief — halt finalize" block, because there is nothing to tear down. Every halt that occurs *after* `z-preflight.sh` succeeds (i.e. `RUN` is exported) funnels through the same "Run Brief — halt finalize" procedure — never a bespoke cleanup path (SKILL-STYLE.md §2).

At Phase 10 and at every post-preflight halt, teardown is delegated to `scripts/z-teardown.sh --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-fix --status <complete|aborted>`, which releases the claim, deregisters, and emits the generic `run_end` event — this always runs after the shared `_fragments/run-brief-finalize.md` include and the domain-specific `fix_run_end` log.

## Notification policy

Push notifications are sent at two points: Phase 5 (decision ready for review) and Phase 10 (fix complete). Both are gated on the `notify.level` key in the harness config — if the level is `off`, no `PushNotification` calls are made. See [docs/human/config.md](docs/human/config.md) for the full config reference, including how to set `notify.level` per-repo or globally.

## Slug derivation — two-step pattern

Setup step 1 uses a split safety+preference pattern:

1. **Unconditional collision check** — `plan-path.sh all_plan_slugs` detects matching slugs across both new and legacy plan layouts. If a collision is found, prompt via `AskUserQuestion` to confirm or choose a different slug. This check runs regardless of any resolver outcome and cannot be bypassed.
2. **Soft non-obvious-slug confirmation gate** (only after collision check passes) — calls `python3 scripts/config.py resolve-question workflow.slug_confirm`, which returns `skip`, `prefill`, `ask`, or `halt`. On `skip`, the derived slug is accepted silently. On `prefill`, the derived slug is pre-selected as the recommended option. On `ask`, the user is prompted normally. If `$SOURCE == "conflict"`, a conflict header is added to the question and a write-back offer is made after the user answers. On `halt`, the command emits a `fix_halt` event and does a plain `exit 0` without invoking `AskUserQuestion` and without touching the teardown/halt-finalize path — nothing has been registered yet at this point.

The invariant: the collision check is a hard prerequisite. The resolver only governs the soft confirmation gate.

## Run Brief integration

`/z-fix` participates in the Run Brief system:

- **Init**: as part of the Setup step 2 `z-preflight.sh` call (fixed order: resolve/session-id/RUN-stamp/claim/register/run-brief-init/run_start/kernel-resolve), `run-brief.sh init` runs with profile=full, artifact=FIX.md.
- **Halt paths**: every terminal halt *after* `z-preflight.sh` has succeeded (wrong tool, abandoned, escalated) calls the "Run Brief — halt finalize" block at `skills/z-fix/SKILL.md:386` — which itself includes the shared `_fragments/run-brief-finalize.md` fragment — before logging `fix_run_end` and delegating teardown to `scripts/z-teardown.sh --status aborted`. When FIX.md is missing (the common case, since it's written in Phase 6), the shared fragment auto-downgrades to lite mode (Intent + Outcome + Next). Pre-preflight halts (e.g. the Setup step 1 `halt` resolver result) skip this whole path — it's a plain `exit 0`, nothing was ever registered.
- **Finalize (Phase 10)**: `run-brief.sh set-section` populates outcome/next, then the shared `_fragments/run-brief-finalize.md` fragment renders the Briefing, followed by the domain `fix_run_end` log and a delegated `scripts/z-teardown.sh --status complete` call. The `$NEXT_JSON` is derived from FIX.md "Docs touched" — if non-empty, next = `/z-maintain-docs`; otherwise next = done.

## Auto-bail thresholds

At any phase, if any of the following are found, the command stops and writes `escalation.md` then recommends `/z-plan`:

- More than 5 candidate files need editing.
- More than 2 non-obvious decisions (new dep, public API change, algorithm with materially different tradeoffs, persistence change).
- Cross-module or cross-crate impact (fix touches multiple modules, public APIs, wire formats, or schemas).
- User says "this might be bigger than I thought."

If scope growth is discovered mid-implementation (Phase 7), the halt is immediate and non-negotiable — the orchestrator does NOT offer to continue or spawn a subagent. Hard limit: touching >7 files inline triggers halt regardless of threshold checks.

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
- **Phase 5 approval is conversational prose, not an AskUserQuestion popup.** The brief synthesis is presented as a conversational reply ending with a recommendation; the user replies inline. `AskUserQuestion` is only used where a `RUNTIME-GATE` comment marks a call site: Setup step 1 halt resolver header, Phase 0 (control-flow fork), Phase 5 shortcut approval and second-failure decision at Phase 8 (risk), and Phase 9 (decision).
- **Shortcuts require explicit separate approval at Phase 5.** If either consultant recommends a shortcut over the robust long-lasting solution, the orchestrator marks it and gets separate user confirmation conversationally. Default is the robust solution.
- **Codex review is non-negotiable and is the sole review gate.** Fix mode cuts planning overhead, not correctness guarantees. There is no advisory/eval-reviewer arm in `/z-fix`'s Phase 8.
- **`/z-mr-review` is not auto-triggered.** If a merge-request review is needed post-fix, run it separately.
- **The `REVIEW_CYCLES` counter drives post-mortem defaults.** `<= 1` cycle defaults to skip; `> 1` cycles defaults to suggest post-mortem. It's initialized at Setup step 5, not at Phase 8.
- **Never overwrite an existing `<slug>/` plan directory** without asking the user (checked via the unconditional collision check in Setup step 1).
- **doc-fetcher is dispatched at Phase 1 only when `docs/llm/INDEX.json` exists.** In its absence, the orchestrator reads files directly; it never spawns the `Explore` subagent (too expensive for fix mode).
- **Notification calls are gated on `notify.level` from `docs/human/config.md`.** Setting `notify.level = off` suppresses all `PushNotification` calls.
- **The `halt` resolver result (Setup step 1) exits cleanly without asking any question and without running teardown.** When `workflow.slug_confirm` resolves to `halt` (e.g. a `no_ask_halt` rule fires in an overnight automation context), the command logs a `fix_halt` event and exits with code 0 *before* `z-preflight.sh` ever runs — nothing is registered, so there is no claim to release and no Run Brief to finalize. This is distinct from `skip` (silently continues), `ask` (prompts normally), and error conditions (fall through to `ask`).
- **PREFLIGHT_RC must be captured before `eval`.** Reading `$?` after evaluating the preflight script's stdout loses the script's own exit-code contract.
- **Git history-rewrite safety doctrine applies.** Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream, run `git branch -r --contains <sha>` for each commit being rewritten. If the upstream ref appears, STOP — recommend rebase or new-commit instead. Force-push to main requires explicit per-incident user authorization with the list of overwritten commits and a content-equivalence demonstration.
- **Run Brief halt finalize must be called on every terminal halt that occurs after `z-preflight.sh` succeeds.** Omitting it leaves the run-brief.json in an incomplete state; pre-preflight halts are exempt since nothing was registered.
- **RUNTIME-GATE comments are the single source of truth for driver-conformance, not a closing table.** Each gated call site (subagent dispatch or AskUserQuestion) carries its own inline `RUNTIME-GATE` comment immediately before the call; the old end-of-file conformance table pattern is retired for rewritten skills (SKILL-STYLE.md §1).
- **Source file lives at `skills/z-fix/SKILL.md`** (the `commands/` directory tier was retired during the earlier z-harness-portability migration; `skills/` is the single source). This refresh re-verified all entry-point line numbers against the current 431-line file after the skill-overhaul-phase1 lifecycle rewrite (previously the file had no `z-preflight.sh`/`z-teardown.sh` delegation at all).

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-fix.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```
/z-fix "Login returns 403 after session token refresh — hypothesis: SameSite attribute is hardcoded to Strict on refresh response, blocking the subsequent browser request"
```

At Phase 0 the command confirms you have a hypothesis. If you typed only a symptom with no hypothesis, Phase 0 asks you to provide one or redirects to `/z-debug`.

## See also

- `skills/z-fix/SKILL.md` — full phase-by-phase procedure
- `docs/human/commands.md` — index of all slash commands
- `docs/human/config.md` — notification policy, workflow.slug_confirm, and other harness config keys
- `docs/human/z-debug.md` — the hypothesis-generation counterpart
- `docs/human/run-brief.md` — Run Brief system reference
