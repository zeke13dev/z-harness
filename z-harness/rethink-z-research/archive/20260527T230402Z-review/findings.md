# Final review — rethink-z-research v1

Run: 20260527T230402Z-review
Base ref: HEAD (commit 477e990; v1a work uncommitted)
Diff stats: 19 modified + 3 new files; +2160 / -167 lines (v1a-scoped)

## Prong A — Implementation drift

### blocker
- **[both LLMs] Skill files out of sync with commands on routing references.** T011 updated `commands/z-do.md`, `commands/z-plan-light.md`, `commands/z-plan-split.md`, `commands/z-uplift.md` to use `/z-map` + `needs_terrain_map`, but the corresponding SKILL.md files were NOT updated. Three concrete misses:
  - `skills/z-do/SKILL.md` line 48: routes to `/z-research <topic>` for terrain → should be `/z-map`.
  - `skills/z-plan-light/SKILL.md` line 73: routes to `/z-research` for terrain → should be `/z-map`.
  - `skills/z-plan-split/SKILL.md` lines 152–153: routes to `/z-research` + `needs_research` reason code → should be `/z-map` + `needs_terrain_map`.
  T011 task block said "commands" — skills mirroring was assumed but not executed. Skills are the agent-dispatch surface; asymmetry breaks the agent-side routing.

- **[both LLMs] `commands/z-map.md` emits `research_run_start` instead of `map_run_start`.** The rename was mechanical; one event name leftover. `skills/z-map/SKILL.md` is correctly named `map_run_start` (T004 caught it); the command file was missed.

### major
- **[Gemini] Phase 4 `tripwires_fired` is initialized empty but never populated.** SPEC describes 3 automated tripwires (`research_high_unverified_rate`, `research_panel_degraded`, `research_judge_temptation`) that should fire during finalize, populating the array in RESEARCH.md frontmatter. Code shows `tripwires_fired = []` with no evaluation loop. Either the SPEC needs to drop this field or the orchestrator needs the evaluation loop. *One reason this might be wrong:* the evaluation might be implicit in the tripwire `bash log-event.sh` calls that DO emit the events — they just don't append to the frontmatter list. Still: the schema promises a populated list; the code doesn't deliver.

- **[Gemini] RESEARCH.md schema mismatch — orchestrator writes fields not in SPEC schema.** Phase 4 frontmatter code includes `panel_degraded` and `panel_perspective_count`, but SPEC RESEARCH.md schema (lines 218-243) doesn't list these. Either add them to the SPEC or remove from the code. Minor consistency leak.

### minor
- **[Codex] Sub-run id extraction via `ls -t | head` is fragile.** Phase 1 Steps 2-3 use `ls -1t archive/ | grep $SLUG | head -1` to find sub-run id. If `/z-map` and `/z-brainstorm` complete in the same second, the second one's archive dir may be misidentified. SPEC says "extract from sub-command's emitted run_start event"; implementation uses directory listing instead. Comment references a fallback that isn't implemented. Acceptable for v1 (sub-commands typically take minutes apart) but track as v1.1.

- **[Gemini] MAP_STATE algorithm doesn't validate frontmatter shape.** If MAP.md exists but is missing `source_files` field, algorithm silently treats it as `fresh` (loop body skipped). Should treat malformed/missing-frontmatter MAP.md as `stale` instead.

- **[Gemini] Cost gate estimate is hardcoded.** Phase 0.5 uses static numbers (2M + 200K + 3M + 0.5M) regardless of dispatch_decision. If `/z-brainstorm` is reused (not run), estimate should drop. Accurate enough for v1 since the ceiling matters more than precision; track for v1.1.

## Prong B — Spec gaps

### blocker
- (none)

### major
- **[Gemini] FORBIDS-new-design invariant relies on post-hoc self-check, not hard prevention.** SPEC says synthesis is FORBIDDEN from proposing new design recommendations. Enforcement = research-judge Step 7 (self-check, strip violations, emit `research_judge_temptation`). This is degraded enforcement — the agent can still GENERATE recommendation language; only the post-hoc scan catches it. Not actually "hard"; more like "post-hoc filtered." Acceptable for v1 with explicit acknowledgment that this is post-launch monitorable, not preventive.

- **[Gemini] N=1 panel failure case under-specified in SPEC.** Phase 2 says N=2 emits `panel_degraded: true`. The research-judge agent handles N=1 with `panel_perspective_count: 1` warning, but SPEC Phase 2 doesn't call out the N=1 case explicitly (it lands in the "2/3 fail → AskUser → proceed-with-1" branch but the synthesis-quality implications aren't spelled out). Minor SPEC clarity issue.

### minor
- **[Codex] Sub-run audit contract spread across SPEC and sub-command Setup steps.** SPEC Phase 1 references "Setup step 6 of /z-map" without showing the code; reader must hop to the sub-command file. Internal consistency is fine — just documentation hygiene.

## Consensus vs disagreement

**Both LLMs flagged (high confidence):**
- Skills routing-references drift (z-do, z-plan-light, z-plan-split). REAL BLOCKER.
- commands/z-map.md `research_run_start` event name. REAL BLOCKER (cosmetic but breaks the "no half-renamed" invariant).

**Gemini only:**
- tripwires_fired empty population
- panel_degraded schema mismatch
- FORBIDS invariant enforcement gap
- N=1 panel case under-specified
- MAP_STATE missing-frontmatter handling
- Cost gate hardcoding

**Codex only:**
- Sub-run id extraction fragility

## Net verdict

**Ship with 2 blockers fixed inline.** Other findings are major/minor and can be:
- Applied inline if quick (tripwires_fired evaluation loop, schema sync)
- Deferred to v1.1 follow-up amendments

The 2 blockers (skills sync + event name) are 5-minute mechanical fixes. After they land, v1 is shippable.
