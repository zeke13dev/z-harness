<!-- Host sets RB_HALT_REASON, BASE, RUN before include. z-plan halt-finalize preamble:
     set outcome + next from the halt reason, then run the shared finalize sequence.
     Mirrors _fragments/run-brief-halt-finalize-execute.md but carries /z-plan's artifact
     profile (decisions.md primary; PLAN.md/SPEC.md fallbacks) and next → /z-plan. -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-$BASE/archive/$RUN/decisions.md}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-$BASE/PLAN.md:$BASE/SPEC.md}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-plan","command":"/z-plan"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- include: _fragments/run-brief-finalize.md -->
