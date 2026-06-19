# Changelog

A human-readable, brief history of how z-harness changed — what got added, what
changed, what got fixed — in plain language. For the machine-tier detail, see
commit messages and `docs/llm/`. For the *why* behind in-flight work, see the
plan artifacts.

This file is **curated, not exhaustive**: related commits are collapsed into one
line, and pure-internal churn (test de-flaking, export regeneration, doc
refreshes) is mostly omitted unless it changed behavior you'd notice.

> **Keeping this updated:** a git `post-commit` hook drafts a bullet here
> automatically whenever a `feat`/`fix` commit lands — marked `_(auto)_`,
> unstaged, under today's date. It never amends or commits; you stage it (and
> polish the wording, dropping the `_(auto)_` tag) when you're ready. Install /
> remove with `scripts/install-changelog-hook.sh {install|remove|status}`;
> tune behaviour via the `[changelog]` keys in `config.toml`
> (`auto`, `types`, `repos`, `file`). Dates are `YYYY-MM-DD`; no version tags
> yet — the project ships continuously.

---

## 2026-06-19

- _(auto)_ Add scripts/reconcile.py classification helper + tests (T002) _(reconcile)_
- _(auto)_ Add read-only reap-stale subcommand + tests (T003) _(plan-claim)_
- _(auto)_ Add commands/z-reconcile.md command definition (T001) _(z-reconcile)_

## 2026-06-18

- **Audit & review now default to amending.** After `/z-audit` or `/z-review-all`,
  findings flow straight into an amend by default, with a short prose
  correction/approach brief replacing the old popup. Less clicking, clearer intent.
- **Fixed:** export silently dropped all personas every run — adapters were
  globbing the wrong directory (`personas/*.md` instead of `personas/builtin/`).
- **Fixed:** artifact paths — `handoff.json` now lives in a single home, legacy
  plan directories get pruned, and a leaky claim-lock test was repaired.
- **Conversational decisions over popups.** Judgment calls in `/z-debug`, `/z-fix`,
  `/z-plan-light`, and `/z-amend` now come as a short brief — options, pros/cons, a
  recommendation — that you can question or answer in plain reply, instead of an
  `AskUserQuestion` popup. Popups are kept only for finite control-flow forks (slug
  collision, claim lost, cost gate). Shipped as a global axiom so it guides every
  command at runtime.
- **`/z-brainstorm` is now a conversation.** A vague idea is first sharpened into a
  buildable problem by `/z-sharpen` (the old `/z-reality` premise-refiner, reworked to
  write the shared `GRILL.md` and bounded so it stays lighter than `/z-grill`). The
  ideators' framings then arrive as a ranked brief with pros/cons — discuss, combine,
  or re-spin in plain reply and converge on a synthesized direction, instead of a
  one-shot pick. New wide/mega mode (`brainstorm this N ways`) spins N ideators in
  phased divergence waves with a configurable cheap-model overflow knob, then clusters
  them to report how much real diversity you got.

## 2026-06-17

- **`skills/` directory removed — `commands/` is now the single source of truth.**
  This was the root cause of recurring INTENT-vs-SPEC drift; exports now generate
  per-host skills on the fly instead of maintaining a parallel copy.
- **MCP server landed.** z-harness can run as an MCP server, including
  `needs_input` resume re-entry; contracts documented.
- **Fixed:** config export-env ↔ ingress round-trip (a mismatch could silently
  poison every config read after loading env).

## 2026-06-16

- **Central config overhaul.** `config.toml` is now the single source of truth;
  export hosts are always-on; added `/z-debt`. Preference reads route through
  `config.py get` instead of fragile env transport.
- **Adaptive INTENT mode (beyond strict SDD).** New default contract: a frozen
  `INTENT.md` plus an emergent task-tree and a growing ledger, instead of the
  rigid SPEC-up-front flow. Legacy SPEC plans still run in legacy mode.

## 2026-06-12

- **Parallelism went live.** Both within-plan (independent tasks run concurrently)
  and cross-plan orchestration, with a merge mutex. Caps default to off — opt in
  when you want it; the orchestrator decides degree, no env knobs to tune.
- **Faster attended runs.** Completed the attended-chain work so interactive
  `/z-implement-all` runs skip ceremony you didn't ask for.
- **Worktree-isolation guardrail.** A concurrency-aware hook keeps parallel
  implementers from clobbering each other's trees.

## 2026-06-11

- **Export migrated into `runtime/drivers/`.** Command/agent/skill export no longer
  rides on the old legacy scripts; each host driver owns its own export.
- **Warm run-briefing.** Runs open with a rendered briefing that surfaces the
  decision *why* up front.
- **Fixed:** a batch of workflow bugs — plan-artifact routing, no-session guards,
  context looping, and stale claim slugs.

## 2026-06-10

- **`/z-test` invariants overhaul.** Tests now plan from `INVARIANTS.json` and
  audit-driven `ERROR_POINTS.json`, with an adversarial subagent — aimed at
  catching real semantic bugs, not trivial coverage.
- **Cost telemetry.** Per-subagent cost capture, including the reviewer, plus an
  opt-in pre-review gate.

## 2026-06-09

- **Ported 7 high-value features from the ECC harness** (61 files).
- **Auto-amend by severity.** Review findings (blocker/major/minor) can flow
  automatically back into the plan.
- **Hermes handoff consumer** + `pi` MCP server + flash subagent config.

## 2026-06-08

- **New: `/z-reality`** — an interactive premise-refinement on-ramp for when you're
  not sure the framing is right yet.
- **Hermes parallel orchestrator v1.2** — the foundation for the parallelism that
  shipped on the 12th.
- **New export target: `pi`.**

## 2026-06-06

- **New: `/z-explain` and `/z-learn`** — code-understanding commands.

## 2026-06-05

- **Cross-session plan coordination.** Leases, a lockless active-plan registry, and
  coordination warnings so two sessions don't trample one plan.
- **`SESSION.md` context handoff** in `/z-implement-all` — a curator + done-set
  resume to kill the O(N²) context bloat on long runs.
- **Harness-portability** adapters, commands, and release/conformance scaffolding.

## 2026-06-03

- **Ported mattpocock/skills mechanics:** `/z-grill` (precontext grilling),
  `CONTEXT.md` glossary graft, a `/z-debug` feedback-loop ladder, and semi-smart
  git-guardrails.
- **Worktree-per-session convention** established.

## 2026-06-01 — 2026-06-02

- **Plan artifacts moved outside the repo by default** (gated behind a smoke test).
  This stops parallel `git clean` runs from wiping your in-flight plans; existing
  plans migrate via `scripts/migrate-plan-layout.sh`.
- **Active-plan registry** wired into the run-creating commands, plus `/z-where`
  to query it read-only.
- **Personas everywhere.** Divergent ideator/consult panels, persona rotation with
  control + no-persona arms, and per-role bindings.
- **Token-estimate cost gates** wired into commands.
- **`STYLE.md` + `/z-style-init`**, CI gating for the Python and shell test suites,
  and an **MIT LICENSE**.

## 2026-05-27 — 2026-05-29

- **`/z-research` reworked.** The old terrain-mapper became `/z-map`; `/z-research`
  is now a higher-order meta-orchestrator that synthesizes across map + brainstorm.
- **Axioms as a fourth behavioral-law channel** — mined from interaction history,
  approved by you, folded into the kernel.
- **New: `/z-setup`** configuration cockpit.
- **AskUser preference hook** — resolves/pre-fills workflow questions from config
  and memory before interrupting you.
- **Event-sourced follow-up queue** (the `/z-followup-*` family).

## 2026-05-26 — 2026-05-28

- **New: `/z-uplift`** — tiered, repo-wide quality-uplift orchestrator.
- **New: `/z-audit-plan-style`** — catches mr-review-style slop in a plan *before*
  any code is written.
- **`/z-debug` bisect fast-path** for regressions with a known-good baseline.
- **`/z-overnight`** unattended chained runs with halt-only interaction.
- **Personas-and-roles foundation** — provider schema v2, role contracts,
  `/z-personas`.

## 2026-05-23 — 2026-05-25

- **Two-tier docs system** initialized: `docs/human/` (Markdown) + `docs/llm/`
  (token-compacted JSON for fast subagent lookup).
- **Portable harness.** Multi-IDE exports (Cursor / Codex / Antigravity), a
  provider registry, and `/z-update`.
- **Doc-memories layer** added.

## 2026-05-19 — 2026-05-20

- **Initial commit — z-harness Claude Code plugin (v0.1.0).**
- **`/z-audit` and `/z-skill-fix`** added; remote-runner generalized.
