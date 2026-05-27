# v1 SHIPPED — rethink-z-research

Run: 20260527T230402Z-review
Verdict: SHIP with 2 blockers + 1 schema-sync fix applied inline post-review.

## Amendments applied
1. **Skill files routing references** — `skills/z-do/SKILL.md`, `skills/z-plan-light/SKILL.md`, `skills/z-plan-split/SKILL.md` updated to use `/z-map` + `needs_terrain_map` (matching the command-side updates from T011 that were missed for skills).
2. **`commands/z-map.md` event name** — `research_run_start` → `map_run_start` (leftover from rename caught by both consultants).
3. **SPEC RESEARCH.md schema sync** — added `panel_perspective_count` + `panel_degraded` fields to the schema frontmatter (already written by orchestrator code; SPEC was missing them).

## False positive
- Gemini flagged "tripwires_fired array never populated." Verified by reading commands/z-research.md lines 1021-1073: tripwires_fired IS populated via atomic regex replacement after events fire. Array initialized empty + populated post-evaluation is the intended pattern.

## Acknowledged deferrals (v1.1 follow-ups)

| Severity | Finding | Disposition |
|---|---|---|
| Major | FORBIDS-new-design invariant relies on post-hoc self-check; not preventive | Acceptable for v1; flag for post-launch monitoring per BRAINSTORM tripwire T1 |
| Major | N=1 panel case spelled out in research-judge but not SPEC Phase 2 | Documentation hygiene; defer |
| Minor | Sub-run id extraction via `ls -t | head` is fragile to same-second collisions | Edge case; sub-commands take minutes apart in practice; v1.1 if needed |
| Minor | MAP_STATE doesn't validate frontmatter shape | v1.1 |
| Minor | Cost-gate estimate hardcoded | v1.1 — accuracy improvement |
| Minor | Sub-run audit contract spread across SPEC + sub-command Setup steps | Documentation hygiene |

## Out-of-scope follow-ups (T016 archive)
- `agents/consultant-primary.md` + `consultant-secondary.md` have dead `research-review` mode descriptions.
- `research_temptation` vs `map_temptation` event-name inconsistency in /z-map files.

## v1 SHIPPED.
