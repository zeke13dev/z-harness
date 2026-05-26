# T007 Validation Evidence

Task: T007 - Validate route coverage and scenarios
Date: 2026-05-24

## Sources Checked

Canonical command sources:

- `commands/z-do.md`
- `commands/z-plan-light.md`
- `commands/z-plan.md`
- `commands/z-plan-split.md`
- `commands/z-brainstorm.md`
- `commands/z-research.md`
- `commands/z-audit-plan.md`

Canonical skill sources:

- `skills/z-do/SKILL.md`
- `skills/z-plan-light/SKILL.md`
- `skills/z-plan/SKILL.md`
- `skills/z-plan-split/SKILL.md`
- `skills/z-brainstorm/SKILL.md`
- `skills/z-research/SKILL.md`
- `skills/z-audit-plan/SKILL.md`

## Sentinel Search

Validation command:

```bash
python3 - <<'PY'
from pathlib import Path
root=Path('/Users/zeke/dev/z-harness')
files=[
'commands/z-do.md','commands/z-plan-light.md','commands/z-plan.md','commands/z-plan-split.md','commands/z-brainstorm.md','commands/z-research.md','commands/z-audit-plan.md',
'skills/z-do/SKILL.md','skills/z-plan-light/SKILL.md','skills/z-plan/SKILL.md','skills/z-plan-split/SKILL.md','skills/z-brainstorm/SKILL.md','skills/z-research/SKILL.md','skills/z-audit-plan/SKILL.md']
for rel in files:
    text=(root/rel).read_text()
    print(rel, text.count('PLAN_ROUTE_CHECK_START'), text.count('PLAN_ROUTE_CHECK_END'))
PY
```

Result: all 14 intended canonical sources contain exactly one `PLAN_ROUTE_CHECK_START` and exactly one `PLAN_ROUTE_CHECK_END`.

## Route Contract Consistency

Automated validation confirmed every route block includes the required route telemetry fields:

- `from_command`
- `to_command`
- `route_class`
- `reason_codes`
- `signals`
- `confidence`
- `classifier_used`
- `artifact_path`
- `route_chain`
- `user_choice`

Signal coverage is command-specific and uses the SPEC's deterministic signal names. Explicit reason-code examples in route blocks use the SPEC enum values, including `too_few_clusters`, `too_many_clusters`, `needs_research`, `cross_module`, and `schema_or_persistence`; no non-SPEC reason-code literals were found in route examples.

## No Auto-Execution Check

Searches for route handoff language confirmed the route blocks describe a user-gated handoff only. Each route block says either `Do not execute the next command automatically` or `stop after presenting the exact next command invocation; do not execute it`.

No route block says that choosing a switch automatically runs another command.

## `/z-audit-plan` Contextual-Only Check

`/z-audit-plan` is treated as contextual only:

- `commands/z-audit-plan.md` and `skills/z-audit-plan/SKILL.md` state that `/z-audit-plan` is not a front-door planning command and is valid only when plan artifacts exist.
- Both sources route the no-plan-artifacts branch to `/z-plan`.
- `/z-plan` route blocks recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist.

Consistency fix applied: `skills/z-plan/SKILL.md` now mirrors `commands/z-plan.md` by including `/z-audit-plan` in the post-plan recommended next steps.

## Export Sync Follow-up

After the final canonical `skills/z-plan/SKILL.md` consistency fix, generated exports were regenerated from repo root:

```bash
python3 scripts/export-cursor.py && python3 scripts/export-codex.py && python3 scripts/export-agy.py
```

Result: all three export scripts completed successfully, with Cursor reporting 58 validated `.mdc` files, Codex reporting 44 validated prompt files plus `AGENTS.md`, and Antigravity reporting 26 workflows, 14 rules, 18 skills, and 58 prompts validated.

Post-export verification confirmed generated `z-plan` targets now include `/z-audit-plan` in the post-plan recommendations:

- `exports/cursor/.cursor/rules/z-plan.mdc`
- `exports/codex/prompts/z-plan.md`
- `exports/agy/.agent/skills/z-plan/SKILL.md`

No generated export file still contains the stale `THREE recommendations` marker.

## Final Review-Major Fix Evidence

Reviewer-major fixes were applied only to canonical `/z-plan` sources and regenerated exports.

Usage-limit guard restoration:

- `commands/z-plan.md` and `skills/z-plan/SKILL.md` again include setup step 7: `Z_HARNESS_PAUSE_AT_PCT` / `usage_pause`.
- Post-export search confirmed the same guard in generated `z-plan` targets:
  - `exports/cursor/.cursor/rules/z-plan.mdc`
  - `exports/codex/prompts/z-plan.md`
  - `exports/agy/.agent/skills/z-plan/SKILL.md`
  - `exports/agy/.agent/workflows/z-plan.md`
  - `exports/agy/prompts/skill-z-plan.md`
  - `exports/agy/prompts/z-plan.md`

Docs-staleness route flow:

- `commands/z-plan.md` and `skills/z-plan/SKILL.md` now describe a `Docs-freshness route gate` that writes `route-decision.md`, emits `plan_route_decision`, uses `reason_codes: ["docs_stale"]`, sets `signals.docs_stale_or_drifted: true`, and presents a user-gated handoff before Phase 1.
- The branch explicitly says not to execute `/z-maintain-docs` automatically.
- Search across canonical and generated `z-plan` targets found the route-flow wording and no remaining direct `Recommend: /z-maintain-docs` / `halt before Phase 1` stale-doc branch.

Export command rerun after these final fixes:

```bash
python3 scripts/export-cursor.py && python3 scripts/export-codex.py && python3 scripts/export-agy.py
```

Result: all three export scripts completed successfully, with Cursor reporting 58 validated `.mdc` files, Codex reporting 44 validated prompt files plus `AGENTS.md`, and Antigravity reporting 26 workflows, 14 rules, 18 skills, and 58 prompts validated.

`/z-audit-plan` contextual-only spot check still passes: both canonical sources say it is not a front-door planning command, is valid only when plan artifacts exist, and must not execute the next command automatically.

## Scenario Checklist

- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
- Small targeted fix in `/z-plan` recommends `/z-plan-light`: verified in `/z-plan` command and skill route blocks.
- `/z-do` with cross-module or schema impact recommends `/z-plan`: verified in `/z-do` command and skill route blocks.
- Unknown bug symptom recommends `/z-debug`; diagnosed bug recommends `/z-fix`: verified in `/z-do`, `/z-plan-light`, and `/z-plan` route blocks where bug signals are in scope.
- Unknown terrain before approach selection recommends `/z-research`: verified in primary route blocks for `/z-plan`, `/z-plan-light`, `/z-do`, `/z-brainstorm`, `/z-research`, and `/z-plan-split`.
- Multiple plausible framings with enough terrain recommends `/z-brainstorm`: verified in `/z-plan`, `/z-plan-light`, `/z-do`, and `/z-research` route blocks.
- Existing plan change recommends `/z-amend`: verified in `/z-plan` route blocks and `/z-audit-plan` post-audit route blocks.
- Existing complete plan can recommend `/z-audit-plan`; fresh intent without plan artifacts must not: verified in `/z-plan` and `/z-audit-plan` command/skill sources; skill post-plan recommendation was corrected.
- `/z-plan-split` with one seam recommends `/z-plan`: verified in `/z-plan-split` command and skill route blocks using `reason_codes: ["too_few_clusters"]`.
- Immediate ping-pong route is blocked and surfaced to the user: verified in every route block's loop-prevention language.

## Outcome

Validation passed after the scoped `skills/z-plan/SKILL.md` consistency fix and final review-major fixes.
