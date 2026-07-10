# z-audit-plan

> Last updated: 2026-07-09
> Covers source: skills/z-audit-plan/SKILL.md, docs/human/z-audit-plan.md

## Overview

`/z-audit-plan` is a read-only, contract-level audit of a plan's `INTENT.md` (or legacy `SPEC.md`), grounding assumptions, approach choices, and initial BFS task layer, run before implementation. It is deliberately NOT a full task-by-task enumeration of `TASKS.md` — that scrutiny is deferred to the per-task reviewer during `/z-execute`. Low-risk plans (no public API/schema changes, confined scope, `candidate_files <= 5`, `non_obvious_decisions <= 2`) skip the multi-phase audit entirely via a `skip_recommended` fast-path and route straight to `/z-execute`.

For plans that don't qualify for the fast path, the command runs a reality check (Phase 1: do referenced files/symbols/configs/tables/flags actually exist), a design/best-practices audit (Phase 2: KISS/DRY/SOLID, security, performance), an optional 3-way cheap pre-review pass (Phase 2.5, gated by `runtime.pre_review`), and a two-consultant adversarial cross-LLM review (Phase 3). Phase 4 merges all findings, applies a "one reason this finding might be wrong" pushback gate, and class-tags every surviving finding as `spec_gap` (factual/mechanical error) or `premise_failure` (viability/design concern) before writing `PLAN_AUDIT_REPORT.md`. Phase 5 resolves `workflow.audit_to_amend` and branches into `halt`, `auto_split` (auto-amend `spec_gap` findings via `/z-amend --skip-user-gate`, surface `premise_failure` findings as a prose brief), or `force_ask` (prose alignment summary, no popup). Phase 9 offers a one-shot preference-elevation proposal if the user has repeatedly chosen the same audit→amend pattern.

## Key entry points

- `skills/z-audit-plan/SKILL.md:253` — skip-by-recommendation fast-path — low-risk plans skip Phases 1-5, emit a `skip_recommended` verdict, and route directly to `/z-execute`.
- `skills/z-audit-plan/SKILL.md:395` — Phase 2.5 pre-review cycle (opt-in) — 3 parallel Flash `pre-reviewer` scans, gated by `runtime.pre_review` config; feeds `pre-review.md` into Phase 3 consultant prompts.
- `skills/z-audit-plan/SKILL.md:508` — Phase 3 adversarial cross-LLM review — `consultant-primary`/`consultant-secondary` Agent() dispatch over contract artifacts + Phase 1/2 notes.
- `skills/z-audit-plan/SKILL.md:559` — Class tagging — assigns canonical Class (`spec_gap` or `premise_failure`) to every surviving finding, using the enum defined in `z-review-all` (`skills/z-review-all/SKILL.md:773`).
- `skills/z-audit-plan/SKILL.md:644` — Phase 5 gate decision — resolves `workflow.audit_to_amend` via `config.py resolve-question` + `amend-gate-decision.py`, run before any user interaction.
- `skills/z-audit-plan/SKILL.md:679` — `auto_split` branch — extracts findings by Class, auto-amends `spec_gap` findings via `/z-amend --skip-user-gate` (batched in INTENT mode, one call per finding in legacy mode), renders `premise_failure` findings as a prose brief via `amendment-brief.py`.
- `skills/z-audit-plan/SKILL.md:826` — `force_ask` prose branch — prose alignment summary (findings/blockers/majors + recommendation) replaces the old `AskUserQuestion` popup.
- `skills/z-audit-plan/SKILL.md:855` — Run Brief finalize — sets outcome/next/approach sections via `run-brief.sh` before `plan_audit_end` is logged.
- `skills/z-audit-plan/SKILL.md:953` — Phase 9 Elevation Proposer — after repeated audit→amend patterns, offers to promote `workflow.audit_to_amend` to project/global config or a routing-preference memory.
- `skills/z-audit-plan/SKILL.md:1071` — Normal-end teardown — releases the slug claim before deregistering the active-plan record (per-resource gating); mirrored by the halt-finalize teardown at line 915.

## How it interacts with others

- `z-plan` — recommends `/z-audit-plan` after `SPEC.md`/`PLAN.md`/`TASKS.md` (or `INTENT.md`) exist; also offers a folded-in audit-plan scan during its own final read-through as an alternative to a separate invocation.
- `z-attend` — the default `attend-full` preset's chain includes an `audit` step mapped to `z-harness:z-audit-plan`; presets that omit the audit step trigger a shortcut-surface ask.
- `z-amend` — the sole downstream mutator; `/z-audit-plan` never edits plan or code artifacts directly, it always routes `spec_gap` corrections through `/z-amend --skip-user-gate` and surfaces `premise_failure` concerns for the user to act on via `/z-amend` or a re-plan.
- `z-review-all` — supplies the canonical Class enum (`implementation_drift | spec_gap | completed_task_contradiction | premise_failure | observation`); `/z-audit-plan` uses only the two values that make sense pre-implementation (`spec_gap`, `premise_failure`).
- `z-audit-plan-style` — a sibling command auditing the same plan artifacts for code-quality/style issues (STYLE.md drift, DRY/KISS/SOLID) rather than correctness; emits a separate `PLAN_STYLE_AUDIT.md`, not `PLAN_AUDIT_REPORT.md`.
- `plan-claim.sh` / `active-plan-registry.py` — `/z-audit-plan` is claim-first (acquire the slug lock before registering), unlike commands that register first; the claim is fixed to the plan's slug with no use-new-slug escape on contention.
- `run-brief.sh` — owns the single user-facing completion surface (outcome/next/approach/status) for both the normal-end and halt-finalize paths.

## Edge cases / gotchas

- The Class enum's authoritative definition lives in `z-review-all` at `skills/z-review-all/SKILL.md:773`, not line 716 as a stale internal comment once suggested — always resolve against the current file, not a hardcoded line number.
- `amend-gate-decision.py` failures (nonzero `resolve-question` exit) fall safe to `force_ask`/prose, never silently skip the gate.
- `$BASE/PLAN_AUDIT_REPORT.md` must exist and be parseable before Phase 5's finding extraction; a missing report logs `audit_artifact_missing` and exits 1.
- A `premise_failure` finding may have no single affected task/file — `amendment-brief.py`'s `affected` field is omitted in that case, not left as an empty string.
- The `skip_recommended` fast-path bypasses Phases 1-5 AND Phase 9's elevation proposer entirely — it jumps straight from the skip verdict to the Phase 9 teardown block, never asking about preference elevation.
- On any post-claim halt, `release` must run before `deregister` (both best-effort); release only fires if the claim was actually acquired (`CLAIM_RC == 0`), deregister only if `register` succeeded (`REG_RC == 0`).
- `--command /z-audit-plan` is required on every `plan-claim.sh` call (acquire/heartbeat/release) — omitting it breaks `--expected-holder` identity comparisons.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-audit-plan.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
